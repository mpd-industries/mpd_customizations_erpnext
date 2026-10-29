import json

import frappe
from frappe.utils import now_datetime

from mpd_customizations.mpd_base.item_ai.item_creation import (
	build_and_insert_item as _build_and_insert_item,
)
from mpd_customizations.mpd_base.item_ai.item_creation import (
	canonical_request_description as _canonical_request_description,
)

# ─── Enqueue ──────────────────────────────────────────────────────────────────


@frappe.whitelist()
def enqueue_item_ai_review(request_name):
	"""
	Called by the Generate AI Suggestion button.
	Sets status to Pending AI Review and queues the background job.
	"""
	from mpd_customizations.mpd_base.doctype.item_request.item_request import validate_item_kind

	doc = frappe.get_doc("Item Request", request_name)
	validate_item_kind(doc)

	frappe.db.set_value("Item Request", request_name, "status", "Pending AI Review")
	frappe.db.commit()

	frappe.enqueue(
		"mpd_customizations.mpd_base.item_ai.review.run_item_review",
		request_name=request_name,
		queue="default",
		timeout=180,
	)
	return {"status": "queued"}


# ─── Background job ───────────────────────────────────────────────────────────


def run_item_review(request_name):
	"""
	Main background job. Builds prompt, calls LLM, applies result.
	"""
	try:
		doc = frappe.get_doc("Item Request", request_name)

		# Get top 5 candidates from similarity search for LLM context
		from mpd_customizations.mpd_base.item_ai.dedup import check_item_duplicates

		canonical_desc = _canonical_request_description(doc)
		top_candidates = check_item_duplicates(
			description=canonical_desc,
			tally_name=doc.tally_name,
			tally_alias=doc.tally_alias,
			legacy_material_code=doc.legacy_material_code,
			hsn_code=doc.gst_hsn_code,
		)

		# Build prompt
		user_prompt = build_prompt(doc, top_candidates)

		# Multimodal only when a file is attached — otherwise plain text to the LLM
		if (doc.attach_documents or "").strip():
			file_data, file_mime = _read_attached_file(doc)
		else:
			file_data, file_mime = None, None

		# Get system prompt from AI Task Config
		from mpd_customizations.mpd_base.ai.task_config import get_task_config

		config, params = get_task_config("item_classification")

		# Call LLM
		from mpd_customizations.mpd_base.ai.llm import call_llm

		result = call_llm(
			config=config,
			system_prompt=config.system_prompt,
			user_prompt=user_prompt,
			reference_doctype="Item Request",
			reference_name=request_name,
			attached_file_data=file_data,
			attached_mime=file_mime,
		)

		# Apply result to doc
		apply_result(doc, result, config, params)

	except Exception:
		frappe.log_error(
			title=f"Item AI Review failed for {request_name}",
			message=frappe.get_traceback(),
		)
		frappe.db.set_value(
			"Item Request",
			request_name,
			"status",
			"Dedup Confirmed",
		)
		frappe.db.commit()


# ─── Prompt builder ───────────────────────────────────────────────────────────


def build_prompt(doc, top_candidates):
	"""
	Builds the user-turn prompt with all context the LLM needs.
	Fetches live data from ERPNext on every call so it is always current.
	"""

	# 1. Active Item Category Codes
	categories = frappe.get_all(
		"Item Category Code",
		filters={"is_active": 1},
		fields=[
			"prefix",
			"full_name",
			"domain",
			"description",
			"example_code",
			"example_item_name",
			"requires_solids_suffix",
			"has_sub_category",
			"sub_category_options",
			"llm_guidance_notes",
		],
	)

	# 2. Leaf Item Groups only — is_group = 0 prevents LLM picking a parent node
	item_groups = frappe.get_all(
		"Item Group",
		filters={"is_group": 0},
		fields=["name"],
		order_by="name",
	)

	# 3. Asset Categories (only if fixed asset)
	asset_categories = []
	if doc.is_fixed_asset:
		asset_categories = frappe.get_all("Asset Category", fields=["name"])

	# Build category lines
	cat_lines = []
	for c in categories:
		line = f"- {c.prefix}: {c.full_name}"
		if c.description:
			line += f"\n  What belongs here: {c.description}"
		if c.example_code:
			line += f"\n  Example: {c.example_code} — {c.example_item_name}"
		if c.requires_solids_suffix:
			line += f"\n  NOTE: Requires solids % suffix e.g. -99, -80, -70"
		if c.has_sub_category:
			line += f"\n  Sub-categories: {c.sub_category_options}"
		if c.llm_guidance_notes:
			line += f"\n  Guidance: {c.llm_guidance_notes}"
		cat_lines.append(line)

	# Build candidates section
	if top_candidates:
		candidate_lines = []
		for c in top_candidates:
			line = f"- {c['name']}: {c['item_name']} [{c.get('item_group', '')}]"
			extras = []
			if c.get("tally_name"):
				extras.append(f"tally:{c['tally_name']}")
			if c.get("tally_alias"):
				extras.append(f"alias:{c['tally_alias']}")
			if c.get("legacy_material_code"):
				extras.append(f"legacy:{c['legacy_material_code']}")
			if c.get("gst_hsn_code"):
				extras.append(f"hsn:{c['gst_hsn_code']}")
			if extras:
				line += f" ({', '.join(extras)})"
			candidate_lines.append(line)
		candidates_block = (
			"--- MOST SIMILAR EXISTING ITEMS ---\n"
			"The requester acknowledged these exist but believes their item is different.\n"
			"Evaluate whether you agree — chemicals often have multiple trade names But do allow same items with different packing sizes.\n\n"
			+ "\n".join(candidate_lines)
		)
	else:
		candidates_block = "--- MOST SIMILAR EXISTING ITEMS ---\n" "None found by similarity search."

	# Asset section
	asset_block = ""
	if asset_categories:
		asset_block = "\n--- ASSET CATEGORIES ---\n" + "\n".join(f"- {a.name}" for a in asset_categories)

	uom_rows = frappe.get_all(
		"UOM",
		fields=["name"],
		order_by="name",
		limit_page_length=200,
	)
	uom_block = "\n".join(f"- {u.name}" for u in uom_rows)

	if doc.is_fixed_asset:
		item_kind = "Fixed Asset"
	elif doc.is_expense_item:
		item_kind = "Expense (not stock, not fixed asset)"
	else:
		item_kind = "Stock Item"

	canonical_desc = _canonical_request_description(doc)
	prompt = f"""
ITEM REQUEST:
  Description:           {canonical_desc}
  Item Kind:             {item_kind}
  Is Fixed Asset:        {"Yes" if doc.is_fixed_asset else "No"}
  Is Stock Item:         {"Yes" if doc.is_stock_item else "No"}
  Is Expense:            {"Yes" if doc.is_expense_item else "No"}
  HSN Code:              {doc.gst_hsn_code or "Not provided"}
  Stock UOM (requester): {doc.stock_uom or "Not provided"}
  Tally Name:            {doc.tally_name or "None"}
  Tally Alias:           {doc.tally_alias or "None"}
  Legacy Material Code:  {doc.legacy_material_code or "None"}

{candidates_block}

--- ACTIVE ITEM CATEGORY CODES ---
{chr(10).join(cat_lines)}

--- VALID ITEM GROUPS (leaf nodes only — pick exactly one, exact string match) ---
{chr(10).join(f"- {g.name}" for g in item_groups)}
{asset_block}

--- VALID UOM NAMES ---
Pick suggested_stock_uom from this list only (exact name match).
{uom_block}
"""
	return prompt


# ─── Apply result ─────────────────────────────────────────────────────────────


def apply_result(doc, result, config, params):
	"""
	Writes LLM output to the Item Request doc.
	Freezes the snapshot and leaves status at AI Reviewed.
	Does not change the Stock / Fixed Asset / Expense checks.
	"""
	doc.ai_item_name_suggestion = result.get("item_name")
	doc.ai_prefix_suggestion = result.get("prefix")
	doc.ai_sub_category_suggestion = result.get("sub_category")
	doc.ai_item_group_suggestion = result.get("item_group")
	doc.ai_asset_category_suggestion = result.get("asset_category")
	doc.ai_solids_suffix_suggestion = result.get("solids_suffix")
	suggested_hsn = (result.get("suggested_hsn_code") or "").strip()
	doc.ai_hsn_suggestion = suggested_hsn or None
	doc.ai_hsn_note = (result.get("hsn_note") or "").strip() or None

	user_hsn = (doc.gst_hsn_code or "").strip()
	if not user_hsn and suggested_hsn:
		doc.gst_hsn_code = suggested_hsn
	# If user_hsn was set but differs from AI, we keep the requester's gst_hsn_code;
	# ai_hsn_suggestion + ai_hsn_note surface the AI correction.

	raw_uom = (result.get("suggested_stock_uom") or "").strip()
	if raw_uom and frappe.db.exists("UOM", raw_uom):
		doc.ai_uom_suggestion = raw_uom
	else:
		doc.ai_uom_suggestion = None
		if raw_uom:
			frappe.log_error(
				title="Invalid AI suggested_stock_uom",
				message=f"Value {raw_uom!r} is not a UOM name. Item Request: {doc.name}",
			)

	user_stock_uom = (doc.stock_uom or "").strip()
	if not user_stock_uom and doc.ai_uom_suggestion:
		doc.stock_uom = doc.ai_uom_suggestion

	doc.ai_review_brief = result.get("review_brief")
	doc.ai_confidence_score = float(result.get("confidence_score", 0))
	doc.ai_duplicate_warning = result.get("duplicate_warning")
	doc.ai_reviewed_on = now_datetime()
	doc.ai_model_used = config.model
	doc.ai_suggested_new_prefix = result.get("suggested_new_prefix")
	doc.ai_suggested_new_prefix_name = result.get("suggested_new_prefix_name")
	doc.ai_suggested_new_item_group = result.get("suggested_new_item_group")

	# Freeze snapshot — never modified after this point
	snapshot = {
		"item_name": result.get("item_name"),
		"prefix": result.get("prefix"),
		"sub_category": result.get("sub_category"),
		"item_group": result.get("item_group"),
		"asset_category": result.get("asset_category"),
		"solids_suffix": result.get("solids_suffix"),
		"suggested_hsn_code": result.get("suggested_hsn_code"),
		"hsn_note": result.get("hsn_note"),
		"suggested_stock_uom": result.get("suggested_stock_uom"),
	}
	doc.ai_snapshot = json.dumps(snapshot)

	# The requester creates the item themselves — duplicate and OTH stay
	# visible on the form but no longer block Create Item.
	doc.status = "AI Reviewed"

	doc.save(ignore_permissions=True)
	frappe.db.commit()


# ─── Flag for MA review (kept as a no-op for cached desk scripts) ──────────────


@frappe.whitelist()
def flag_for_ma_approval(request_name):
	"""Editing the AI suggestion no longer escalates for Master Approver review."""
	return {"status": "no_change"}


# ─── Create item (requester accepts the current suggestion fields) ─────────────

_CREATE_ALLOWED_STATUSES = ("AI Reviewed", "Pending MA Approval", "Duplicate Flagged")


@frappe.whitelist()
def create_item_from_request(request_name):
	"""
	Called when the requester clicks 'Create Item' after reviewing the AI output.
	Uses the suggestion fields currently on the form (including any edits).
	"""
	from mpd_customizations.mpd_base.doctype.item_request.item_request import validate_item_kind

	doc = frappe.get_doc("Item Request", request_name)

	if doc.status not in _CREATE_ALLOWED_STATUSES:
		frappe.throw(
			f"Item can only be created after AI review "
			f"(allowed: {', '.join(_CREATE_ALLOWED_STATUSES)}; current: {doc.status})."
		)

	validate_item_kind(doc)

	item_code = _build_and_insert_item(doc)

	doc.status = "Approved"
	doc.created_item_code = item_code
	doc.approved_by = frappe.session.user
	doc.approved_on = now_datetime()
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	_rebuild_search_index()
	return item_code


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _rebuild_search_index():
	from mpd_customizations.mpd_base.item_ai.dedup import build_search_index

	try:
		build_search_index()
	except Exception:
		frappe.log_error(
			title="Search index rebuild failed after item creation",
			message=frappe.get_traceback(),
		)


def _read_attached_file(doc):
	"""
	Reads the file attached to the Item Request (local disk or S3) and returns
	(base64_data_url, mime_type). Call only when attach_documents is set.

	Returns (None, None) if unsupported type or read error (LLM call falls back to text-only).

	Supported: PDF, PNG, JPG/JPEG
	"""
	import base64
	import os

	file_url = (doc.attach_documents or "").strip()
	if not file_url:
		return None, None

	ext = os.path.splitext(file_url)[1].lower()
	mime_map = {
		".pdf": "application/pdf",
		".png": "image/png",
		".jpg": "image/jpeg",
		".jpeg": "image/jpeg",
	}
	mime_type = mime_map.get(ext)
	if not mime_type:
		frappe.log_error(
			title=f"Unsupported attachment type '{ext}' on {doc.name} — skipping",
		)
		return None, None

	try:
		# frappe.get_doc("File", ...).get_content() works for both
		# local files and S3-backed files (frappe_s3_attachment)
		file_doc = frappe.get_doc("File", {"file_url": file_url})
		content = file_doc.get_content()
		if isinstance(content, str):
			content = content.encode("latin-1")
		encoded = base64.b64encode(content).decode("ascii")
		data_url = f"data:{mime_type};base64,{encoded}"
		return data_url, mime_type

	except Exception:
		frappe.log_error(
			title=f"Could not read attachment for Item Request {doc.name}",
			message=frappe.get_traceback(),
		)
		return None, None
