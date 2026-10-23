from __future__ import annotations

import base64
import io
import json
import os
import re

import frappe
from frappe.utils import now_datetime

from mpd_customizations.asset_organizer.ai import logger
from mpd_customizations.asset_organizer.ai.apr_context import (
	_get_task_config,
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


def _line_qty_rate_total(line: dict) -> tuple[float, float, float]:
	qty = float(line.get("qty") or 0)
	rate = float(line.get("rate") or 0)
	return qty, rate, round(qty * rate, 2)


def _format_prompt_line(index: str | int, line: dict, source_category: str = "") -> str:
	qty, rate, total = _line_qty_rate_total(line)
	hsn = (line.get("hsn_code") or "—").strip() or "—"
	desc = (line.get("raw_description") or "").strip()
	src = source_category or line.get("source_category") or ""
	src_bit = f" | {src}" if src else ""
	return f"  [{index}] {desc}{src_bit} | qty {qty} | total {total} | " f"rate {rate} | hsn {hsn}"


def _row_to_line_dict(row) -> dict:
	return {
		"raw_description": row.raw_description,
		"source_category": row.source_category,
		"source_document_ref": row.source_document_ref,
		"hsn_code": row.hsn_code,
		"qty": row.qty,
		"uom": row.uom,
		"rate": row.rate,
		"line_total": row.line_total,
		"name": row.name,
	}


def _is_same_source_row(row, category: str, ref_no: str) -> bool:
	return (row.source_category or "") == category and (row.source_document_ref or "") == ref_no


def _existing_rows_for_merge(apr_doc, category: str, ref_no: str) -> list[dict]:
	"""Existing APR lines from other documents, labelled A, B, C…"""
	rows = []
	label = ord("A")
	for row in apr_doc.item_lines:
		if not (row.raw_description or "").strip():
			continue
		if _is_same_source_row(row, category, ref_no):
			continue
		rows.append(
			{
				**_row_to_line_dict(row),
				"prompt_index": chr(label),
				"row": row,
			}
		)
		label += 1
	return rows


def _preferred_description_on_merge(
	existing: dict,
	new_line: dict,
	category: str,
	llm_preferred: str | None,
) -> str:
	"""Invoice wording wins over PO when merging lines on the APR."""
	if category == "Invoice":
		return (new_line.get("raw_description") or "").strip()
	if (existing.get("source_category") or "") == "Invoice":
		return (existing.get("raw_description") or "").strip()
	if llm_preferred:
		return llm_preferred.strip()
	return (new_line.get("raw_description") or existing.get("raw_description") or "").strip()


def _preferred_hsn_on_merge(existing: dict, new_line: dict, category: str) -> str | None:
	if category == "Invoice":
		return new_line.get("hsn_code") or existing.get("hsn_code")
	if (existing.get("source_category") or "") == "Invoice":
		return existing.get("hsn_code") or new_line.get("hsn_code")
	return new_line.get("hsn_code") or existing.get("hsn_code")


def _llm_batch_resolve_apr_lines(
	apr_name: str,
	category: str,
	ref_no: str,
	new_lines: list[dict],
	existing_rows: list[dict],
) -> list[dict]:
	"""One LLM call: map each new line to add or same-as-existing on this APR."""
	new_block = "\n".join(_format_prompt_line(i, line) for i, line in enumerate(new_lines))
	existing_block = "\n".join(_format_prompt_line(r["prompt_index"], r) for r in existing_rows)
	user_prompt = (
		f"NEW LINES (from {category} ref {ref_no}):\n{new_block}\n\n"
		f"EXISTING LINES (already on this APR):\n{existing_block}\n\n"
		"Return a decision for every new_line_index."
	)

	try:
		config = _get_task_config("apr_item_line_merge")
		result = call_llm(
			config=config,
			system_prompt=config.system_prompt,
			user_prompt=user_prompt,
			reference_doctype="Asset Procurement Record",
			reference_name=apr_name,
		)
		decisions = result.get("decisions") or []
		if isinstance(decisions, list) and decisions:
			return decisions
	except Exception as exc:
		logger.warning(f"APR {apr_name}: batch item merge LLM failed: {exc} — defaulting to add")
		frappe.log_error(
			title=f"APR Item Line Merge Failed [{apr_name}]",
			message=frappe.get_traceback(),
		)

	return [{"new_line_index": i, "action": "add"} for i in range(len(new_lines))]


def _find_existing_by_prompt_index(existing_rows: list[dict], index: str) -> dict | None:
	for row in existing_rows:
		if row.get("prompt_index") == index:
			return row
	return None


def _update_existing_apr_row(
	existing_entry: dict,
	new_line: dict,
	category: str,
	preferred_description: str,
) -> None:
	row = existing_entry["row"]
	row.raw_description = preferred_description
	hsn = _preferred_hsn_on_merge(existing_entry, new_line, category)
	if hsn and not row.hsn_code:
		row.hsn_code = hsn
	if new_line.get("uom") and not row.uom:
		row.uom = new_line.get("uom")
	if new_line.get("rate") and not row.rate:
		row.rate = new_line.get("rate")
	qty, rate, total = _line_qty_rate_total(new_line)
	if qty and not row.qty:
		row.qty = qty
	if total and not row.line_total:
		row.line_total = total


def _format_catalog_candidates(candidates: list[dict]) -> str:
	lines = []
	for c in candidates:
		hsn = c.get("gst_hsn_code") or "—"
		score = c.get("similarity_score", "")
		lines.append(
			f"  - {c.get('name')}: {c.get('item_name')} "
			f"[{c.get('item_group', '')}] (score {score}, hsn {hsn})"
		)
	return "\n".join(lines) if lines else "  (none above threshold)"


def _llm_resolve_catalog_item(
	apr_name: str,
	line: dict,
	candidates: list[dict],
) -> tuple[str | None, bool]:
	"""
	LLM picks an Item from dedup candidates or declares a new product.
	Returns (item_code, is_existing_item).
	"""
	qty, rate, total = _line_qty_rate_total(line)
	desc = (line.get("raw_description") or "").strip()
	hsn = line.get("hsn_code") or "—"
	user_prompt = (
		f"LINE:\n{_format_prompt_line('?', line)}\n\n"
		f"CANDIDATES (from similarity search):\n"
		f"{_format_catalog_candidates(candidates)}\n"
	)

	try:
		config = _get_task_config("apr_item_catalog_match")
		result = call_llm(
			config=config,
			system_prompt=config.system_prompt,
			user_prompt=user_prompt,
			reference_doctype="Asset Procurement Record",
			reference_name=apr_name,
		)
		if result.get("is_existing_item"):
			code = (result.get("matched_item_code") or "").strip()
			valid = {c.get("name") for c in candidates}
			if code and code in valid:
				return code, True
			logger.warning(f"APR {apr_name}: catalog LLM returned invalid item {code!r} for '{desc}'")
		return None, False
	except Exception as exc:
		logger.warning(f"APR {apr_name}: catalog match LLM failed for '{desc}': {exc}")
		frappe.log_error(
			title=f"APR Catalog Match Failed [{apr_name}]",
			message=frappe.get_traceback(),
		)
		return None, False


def _extract_source_item_code(raw_description: str) -> str | None:
	"""Extract a leading equipment/item code like VCS00001."""
	desc = (raw_description or "").strip()
	if not desc:
		return None
	first_line = desc.splitlines()[0].strip()
	match = re.match(r"^([A-Z]{2,}[A-Z0-9\-_/]{2,})\b", first_line)
	return match.group(1) if match else None


def _normalize_desc_lines(text: str) -> list[str]:
	lines: list[str] = []
	for raw in (text or "").splitlines():
		cleaned = re.sub(r"\s+", " ", raw).strip()
		if cleaned:
			lines.append(cleaned)
	return lines


def _description_token_set(text: str) -> set[str]:
	return {t.lower() for t in re.findall(r"[A-Za-z0-9]+", text or "") if len(t) > 2}


def _collect_evidence_description_variants(
	apr_name: str,
	primary_description: str,
	source_item_code: str | None,
) -> list[str]:
	"""Collect related PO/Invoice item descriptions from extracted evidence JSON."""
	variants: list[str] = []
	primary_tokens = _description_token_set(primary_description)
	rows = frappe.get_all(
		"APR Evidence Document",
		filters={
			"parent": apr_name,
			"extraction_status": "Extracted",
			"detected_category": ["in", ["PO", "Invoice"]],
		},
		fields=["name", "extracted_json_vault"],
	)
	for row in rows:
		payload = row.extracted_json_vault
		if not payload:
			continue
		try:
			data = json.loads(payload)
		except Exception:
			continue
		for item_line in data.get("item_lines") or []:
			desc = (item_line.get("raw_description") or "").strip()
			if not desc:
				continue
			if source_item_code and source_item_code.lower() in desc.lower():
				variants.append(desc)
				continue
			overlap = primary_tokens.intersection(_description_token_set(desc))
			if len(overlap) >= 2:
				variants.append(desc)
	return variants


def _build_canonical_item_request_description(
	apr_name: str,
	apr_row,
	line: dict,
) -> tuple[str, str | None]:
	"""
	Build a rich Item Request description using merged line context:
	consolidated APR line + related PO/Invoice evidence variants.
	"""
	primary = (line.get("raw_description") or "").strip()
	source_item_code = _extract_source_item_code(primary)

	variant_pool = [primary]
	# Include current APR row description (may already be merged by PO/Invoice logic)
	row_desc = (apr_row.raw_description or "").strip()
	if row_desc:
		variant_pool.append(row_desc)
	variant_pool.extend(_collect_evidence_description_variants(apr_name, primary, source_item_code))

	# Deduplicate while preserving order
	unique_variants: list[str] = []
	seen: set[str] = set()
	for variant in variant_pool:
		key = re.sub(r"\s+", " ", variant).strip().lower()
		if not key or key in seen:
			continue
		seen.add(key)
		unique_variants.append(variant.strip())

	lead_text = unique_variants[0] if unique_variants else primary
	if source_item_code:
		lead_text = re.sub(
			rf"^\s*{re.escape(source_item_code)}\s*[-:|]?\s*",
			"",
			lead_text,
			flags=re.IGNORECASE,
		).strip()
	headline = f"{source_item_code} - {lead_text}" if source_item_code and lead_text else lead_text

	detail_lines: list[str] = []
	for variant in unique_variants:
		if source_item_code:
			variant = re.sub(
				rf"^\s*{re.escape(source_item_code)}\s*[-:|]?\s*",
				"",
				variant,
				flags=re.IGNORECASE,
			).strip()
		for ln in _normalize_desc_lines(variant):
			if ln and ln.lower() != (headline or "").lower():
				detail_lines.append(ln)

	# Unique detail lines
	final_details: list[str] = []
	seen_details: set[str] = set()
	for ln in detail_lines:
		key = ln.lower()
		if key in seen_details:
			continue
		seen_details.add(key)
		final_details.append(ln)

	qty, rate, line_total = _line_qty_rate_total(line)
	hsn = (line.get("hsn_code") or "").strip()
	uom = (line.get("uom") or "").strip()
	source_ref = (apr_row.source_document_ref or "").strip()
	source_cat = (apr_row.source_category or "").strip()

	meta_parts = []
	if hsn:
		meta_parts.append(f"HSN: {hsn}")
	if qty:
		qty_text = f"{qty:g}"
		if uom:
			qty_text = f"{qty_text} {uom}"
		meta_parts.append(f"Qty: {qty_text}")
	if rate:
		meta_parts.append(f"Rate: {rate:g}")
	if line_total:
		meta_parts.append(f"Line Total: {line_total:g}")
	if source_ref:
		source_label = f"{source_cat} " if source_cat else ""
		meta_parts.append(f"Source: {source_label}{source_ref}".strip())

	parts = [headline] if headline else []
	if final_details:
		parts.append("\n".join(final_details[:20]))
	if meta_parts:
		parts.append(" | ".join(meta_parts))

	canonical_description = "\n".join(p for p in parts if p).strip()
	return canonical_description or primary, source_item_code


def _link_catalog_or_item_request(
	apr_name: str,
	apr_row,
	line: dict,
) -> None:
	"""dedup.py retrieves candidates; LLM confirms Item link or Item Request."""
	if (apr_row.item_doctype or "") == "Item" and apr_row.item_reference:
		return

	desc = (line.get("raw_description") or "").strip()
	if not desc:
		return

	candidates = check_item_duplicates(
		description=desc,
		hsn_code=line.get("hsn_code"),
	)
	item_code, is_existing = _llm_resolve_catalog_item(apr_name, line, candidates)

	if is_existing and item_code:
		apr_row.item_doctype = "Item"
		apr_row.item_reference = item_code
		apr_row.match_confidence = "Exact Match"
		logger.info(f"APR {apr_name}: catalog LLM linked '{desc}' → {item_code}")
		return

	canonical_desc, source_item_code = _build_canonical_item_request_description(
		apr_name,
		apr_row,
		line,
	)

	ir = frappe.get_doc(
		{
			"doctype": "Item Request",
			"requester_description": canonical_desc,
			"combined_asset_description": canonical_desc,
			"source_item_code": source_item_code,
			"gst_hsn_code": line.get("hsn_code"),
			"is_fixed_asset": 1,
			"reference_doctype": "Asset Procurement Record",
			"reference_name": apr_name,
			"requested_by": "Administrator",
			"status": "Draft",
		}
	)
	ir.insert(ignore_permissions=True)
	check_item_duplicates_and_set_status(
		ir.name,
		canonical_desc,
		hsn_code=line.get("hsn_code"),
	)
	apr_row.item_doctype = "Item Request"
	apr_row.item_reference = ir.name
	apr_row.match_confidence = "No Match - Request Created"
	logger.info(f"APR {apr_name}: created Item Request {ir.name} for '{desc}'")


def _append_apr_item_line(apr_doc, category: str, ref_no: str, line: dict):
	qty, rate, total = _line_qty_rate_total(line)
	row = apr_doc.append(
		"item_lines",
		{
			"source_document_ref": ref_no,
			"source_category": category,
			"raw_description": (line.get("raw_description") or "").strip(),
			"hsn_code": line.get("hsn_code"),
			"qty": qty,
			"uom": line.get("uom"),
			"rate": rate,
			"line_total": total,
		},
	)
	line_with_desc = {**line, "raw_description": row.raw_description}
	_link_catalog_or_item_request(apr_doc.name, row, line_with_desc)
	return row


def _resolve_item_lines(apr_name: str, category: str, data: dict) -> None:
	"""
	PO and Invoice only. Batch LLM merges against existing APR lines; dedup.py +
	catalog LLM links Items or creates Item Requests for new lines.
	"""
	if category not in ("PO", "Invoice"):
		return

	item_lines = data.get("item_lines") or []
	ref_no = data.get("extracted_ref_no") or data.get("po_number") or data.get("invoice_number") or ""

	apr_doc = frappe.get_doc("Asset Procurement Record", apr_name)

	new_lines: list[dict] = []
	for line in item_lines:
		raw_desc = (line.get("raw_description") or "").strip()
		if not raw_desc:
			continue
		if any(
			_is_same_source_row(r, category, ref_no) and (r.raw_description or "").strip() == raw_desc
			for r in apr_doc.item_lines
		):
			continue
		new_lines.append(line)

	if not new_lines:
		return

	existing_rows = _existing_rows_for_merge(apr_doc, category, ref_no)

	if existing_rows:
		decisions = _llm_batch_resolve_apr_lines(apr_name, category, ref_no, new_lines, existing_rows)
	else:
		decisions = [{"new_line_index": i, "action": "add"} for i in range(len(new_lines))]

	matched_existing_indices: set[str] = set()

	for decision in decisions:
		idx = decision.get("new_line_index")
		if idx is None or idx < 0 or idx >= len(new_lines):
			continue
		new_line = new_lines[idx]
		action = (decision.get("action") or "add").strip().lower()

		if action == "same":
			matched_idx = (decision.get("matched_existing_index") or "").strip()
			existing_entry = _find_existing_by_prompt_index(existing_rows, matched_idx)
			if not existing_entry or matched_idx in matched_existing_indices:
				logger.warning(f"APR {apr_name}: invalid merge index {matched_idx!r} — adding line")
				_append_apr_item_line(apr_doc, category, ref_no, new_line)
				continue
			matched_existing_indices.add(matched_idx)
			preferred = _preferred_description_on_merge(
				existing_entry,
				new_line,
				category,
				decision.get("preferred_description"),
			)
			_update_existing_apr_row(existing_entry, new_line, category, preferred)
			merge_line = {**new_line, "raw_description": preferred}
			_link_catalog_or_item_request(apr_name, existing_entry["row"], merge_line)
			logger.info(f"APR {apr_name}: merged line [{idx}] into existing [{matched_idx}]")
		else:
			_append_apr_item_line(apr_doc, category, ref_no, new_line)

	apr_doc.save(ignore_permissions=True)
	frappe.db.commit()
