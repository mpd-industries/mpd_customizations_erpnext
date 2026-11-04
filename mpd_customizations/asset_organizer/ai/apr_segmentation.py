from __future__ import annotations

import base64
import io
import json
import os
import re

import frappe
from frappe.utils import now_datetime

from mpd_customizations.asset_organizer.ai import logger
from mpd_customizations.asset_organizer.ai.apr_chain import (
	_on_segmentation_complete,
)
from mpd_customizations.asset_organizer.ai.apr_context import (
	_get_task_config,
)
from mpd_customizations.asset_organizer.ai.apr_file_io import (
	_read_file_as_base64,
	_save_split_file,
	_split_pdf,
)
from mpd_customizations.asset_organizer.ai.schemas import (
	CATEGORY_SCHEMA_MAP,
	CATEGORY_TASK_KEY_MAP,
	PaymentExtractionSchema,
	SegmentationSchema,
)
from mpd_customizations.mpd_base.ai.llm import call_llm
from mpd_customizations.mpd_base.item_ai.dedup import (
	check_item_duplicates,
	check_item_duplicates_and_set_status,
)


def _handle_segmentation(
	apr_name: str,
	upload_row_name: str,
	pdf_bytes: bytes,
	original_filename: str,
	segmentation: SegmentationSchema,
) -> None:
	"""
	For each segment in the segmentation result:
	  1. Split the PDF to that page range.
	  2. Save as a Frappe File.
	  3. Append an APR Evidence Document row with detected_category, source_pages, etc.
	Then save the APR (to persist child rows) and enqueue run_evidence_extraction per row.
	Also handles asset_description_suggestion from the first segment.
	"""
	apr_doc = frappe.get_doc("Asset Procurement Record", apr_name)
	new_row_names: list[str] = []

	for idx, seg in enumerate(segmentation.segments):
		pages = seg.pages
		page_label = f"{pages[0]}-{pages[-1]}" if len(pages) > 1 else str(pages[0])
		base_name = os.path.splitext(original_filename)[0]
		seg_filename = f"{base_name}_seg{idx + 1}_p{page_label}.pdf"

		try:
			seg_bytes = _split_pdf(pdf_bytes, pages)
			file_url = _save_split_file(apr_name, seg_bytes, seg_filename)
		except Exception as exc:
			logger.error(f"APR {apr_name}: split failed for segment {idx + 1} pages {pages}: {exc}")
			frappe.log_error(title="APR PDF Split Failed", message=frappe.get_traceback())
			continue

		new_row = apr_doc.append(
			"evidence_documents",
			{
				"evidence_file": file_url,
				"detected_category": seg.category,
				"document_description": seg.description,
				"source_pages": page_label,
				"source_upload": upload_row_name,
				"extraction_status": "Queued",
			},
		)
		new_row_names.append(new_row.name or None)

	apr_doc.save(ignore_permissions=True)
	frappe.db.commit()

	# After save, row names are assigned; collect them from the saved doc
	saved_rows = [
		row
		for row in frappe.get_doc("Asset Procurement Record", apr_name).evidence_documents
		if row.source_upload == upload_row_name and row.extraction_status == "Queued"
	]

	# Handle asset_description_suggestion from first segment
	first_seg = segmentation.segments[0] if segmentation.segments else None
	if first_seg and first_seg.asset_description_suggestion:
		other_extracted = frappe.db.count(
			"APR Evidence Document",
			{"parent": apr_name, "extraction_status": "Extracted"},
		)
		if other_extracted == 0:
			if not frappe.db.get_value("Asset Procurement Record", apr_name, "ai_description_suggestion"):
				frappe.db.set_value(
					"Asset Procurement Record",
					apr_name,
					"ai_description_suggestion",
					first_seg.asset_description_suggestion,
				)
			if not frappe.db.get_value("Asset Procurement Record", apr_name, "asset_description"):
				frappe.db.set_value(
					"Asset Procurement Record",
					apr_name,
					"asset_description",
					first_seg.asset_description_suggestion,
				)

	frappe.db.commit()


def run_segmentation_job(apr_name: str, upload_row_name: str) -> None:
	"""
	Background job: segment an uploaded PDF into logical documents.
	Creates one APR Evidence Document row per segment; extraction is started
	via the APR-level chain when all pending segmentations for this batch finish.
	"""
	logger.info(f"run_segmentation_job start: APR={apr_name} upload={upload_row_name}")

	try:
		try:
			upload_row = frappe.get_doc("Asset Documentation", upload_row_name)
		except frappe.DoesNotExistError:
			logger.error(f"Upload row {upload_row_name} not found")
			return

		file_url = upload_row.upload_file
		if not file_url:
			frappe.db.set_value(
				"Asset Documentation",
				upload_row_name,
				{
					"upload_status": "Failed",
					"upload_error": "No file attached.",
				},
			)
			return

		try:
			file_data_url, filename = _read_file_as_base64(file_url)
			b64_data = file_data_url.split(",", 1)[1]
			pdf_bytes = base64.b64decode(b64_data)
		except Exception as exc:
			frappe.db.set_value(
				"Asset Documentation",
				upload_row_name,
				{
					"upload_status": "Failed",
					"upload_error": f"Could not read file: {exc}",
				},
			)
			logger.error(f"APR {apr_name}: file read failed for upload {upload_row_name}: {exc}")
			return

		try:
			from pypdf import PdfReader

			page_count = len(PdfReader(io.BytesIO(pdf_bytes)).pages)
			frappe.db.set_value("Asset Documentation", upload_row_name, "page_count", page_count)
		except Exception:
			page_count = None

		try:
			segment_config = _get_task_config("apr_document_segment")
			segment_raw = call_llm(
				config=segment_config,
				system_prompt=segment_config.system_prompt,
				user_prompt=(
					f"Segment this PDF document. It has {page_count or 'an unknown number of'} "
					"page(s). Identify every distinct logical document by page range."
				),
				reference_doctype="Asset Procurement Record",
				reference_name=apr_name,
				attached_file_data=file_data_url,
				attached_mime="application/pdf",
				attached_filename=filename,
			)
			segmentation = SegmentationSchema(**segment_raw)
		except Exception as exc:
			frappe.db.set_value(
				"Asset Documentation",
				upload_row_name,
				{
					"upload_status": "Failed",
					"upload_error": f"Segmentation LLM call failed: {exc}",
				},
			)
			logger.error(f"APR {apr_name}: segmentation failed for upload {upload_row_name}: {exc}")
			frappe.log_error(title="APR Segmentation Failed", message=frappe.get_traceback())
			return

		_handle_segmentation(apr_name, upload_row_name, pdf_bytes, filename, segmentation)

		frappe.db.set_value("Asset Documentation", upload_row_name, "upload_status", "Segmented")
		logger.info(
			f"run_segmentation_job complete: APR={apr_name} upload={upload_row_name} "
			f"segments={len(segmentation.segments)}"
		)
	finally:
		_on_segmentation_complete(apr_name)
