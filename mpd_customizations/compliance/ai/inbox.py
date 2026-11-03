"""Turn a compliance-inbox upload into evidence on an activity or registration."""

import json

import frappe

from mpd_customizations.compliance.ai.prompts import EVIDENCE_EXTRACT_PROMPT
from mpd_customizations.compliance.services.generate import ensure_expiry_activity
from mpd_customizations.compliance.services.matching import is_licence, plan_licence, select_target
from mpd_customizations.drive.ai.filing import year_label
from mpd_customizations.drive.ai.inbox import _read_for_model
from mpd_customizations.drive.services.files import move_file, rename_file
from mpd_customizations.drive.services.folders import ensure_path
from mpd_customizations.mpd_base.ai.llm import call_llm
from mpd_customizations.mpd_base.ai.task_config import get_task_config


def process_compliance_inbox(file_name):
	doc = frappe.get_doc("Drive File", file_name)
	folder = frappe.get_doc("Drive Folder", doc.folder)
	if not folder.organise_into:
		frappe.db.set_value("Drive File", file_name, "ai_status", "Skipped")
		return
	frappe.db.set_value("Drive File", file_name, "ai_status", "Processing")
	try:
		extraction = _extract(doc)
		target = select_target(
			extraction,
			_open_activity_ids(),
			frappe.get_all("Compliance Registration", pluck="name"),
		)
		if is_licence(extraction):
			target = _prepare_licence(extraction, target)
		_file_document(doc, folder, extraction, target)
		_apply(doc.name, extraction, target)
		frappe.db.set_value("Drive File", file_name, "ai_status", "Filed")
	except Exception:
		frappe.db.set_value("Drive File", file_name, "ai_status", "Failed")
		frappe.log_error(title=f"Compliance inbox failed for {file_name}", message=frappe.get_traceback())
		raise


def _extract(doc):
	filename_only = True
	file_data = mime = None
	text = ""
	if doc.s3_key:
		try:
			file_data, mime, text, filename_only = _read_for_model(doc)
		except Exception:
			frappe.log_error(title="Compliance inbox could not read file", message=frappe.get_traceback())
	config, _params = get_task_config("compliance_evidence_extract")
	activities = frappe.get_all(
		"Compliance Activity",
		filters={"status": ["not in", ["Completed", "Not Applicable", "Waived"]]},
		fields=["name", "title", "period_label", "due_date", "obligation"],
		limit=40,
	)
	registrations = frappe.get_all(
		"Compliance Registration",
		filters={"status": ["in", ["Active", "Applied"]]},
		fields=["name", "registration_type", "registration_number", "company", "site", "valid_to"],
		limit=40,
	)
	user_prompt = (
		f"File name: {doc.original_filename or doc.title}\n\n"
		f"Open activities:\n{json.dumps(activities, default=str)}\n\n"
		f"Registrations:\n{json.dumps(registrations, default=str)}\n"
	)
	if text:
		user_prompt += f"\nDocument text:\n{text[:20000]}"
	if filename_only:
		user_prompt += "\nFile contents were not available. Set confidence below 0.5."
	result = call_llm(
		config,
		config.system_prompt or EVIDENCE_EXTRACT_PROMPT,
		user_prompt,
		reference_doctype="Drive File",
		reference_name=doc.name,
		attached_file_data=file_data,
		attached_mime=mime,
		attached_filename=doc.original_filename or "document.pdf",
	)
	return result if isinstance(result, dict) else {}


def _open_activity_ids():
	return frappe.get_all(
		"Compliance Activity",
		filters={"status": ["not in", ["Completed", "Not Applicable", "Waived"]]},
		pluck="name",
	)


def _file_document(doc, folder, extraction, target):
	domain = extraction.get("domain") or "Unsorted"
	leaf_name = extraction.get("title") or doc.title or "Evidence"
	if target.get("action") == "filing" and target.get("activity"):
		activity = frappe.db.get_value(
			"Compliance Activity", target["activity"], ["title", "domain"], as_dict=True
		)
		if activity:
			domain = activity.domain or domain
			leaf_name = activity.title
	elif target.get("registration"):
		reg = frappe.db.get_value(
			"Compliance Registration",
			target["registration"],
			["registration_type", "registration_number"],
			as_dict=True,
		)
		if reg:
			leaf_name = " ".join(part for part in (reg.registration_type, reg.registration_number) if part)
	year = None
	if extraction.get("use_year") in (True, 1, "1", "true", "True"):
		style = "Financial Year"
		if frappe.db.exists("Drive Settings", "Drive Settings"):
			style = frappe.db.get_single_value("Drive Settings", "year_style") or style
		year = year_label(frappe.utils.getdate(), style)
	segments = [part for part in (domain, leaf_name, year) if part]
	leaf = ensure_path(folder.organise_into, segments, ignore_permissions=True)
	if extraction.get("title"):
		rename_file(doc.name, extraction["title"])
	move_file(doc.name, leaf)


def _apply(file_name, extraction, target):
	action = target.get("action")
	confidence = _confidence(extraction)
	if action == "unmatched":
		_unmatched(file_name, extraction, confidence)
		return
	if action == "notice":
		_notice(file_name, extraction)
		return
	if action == "licence":
		_licence(file_name, extraction, target, confidence)
		return
	if action == "filing":
		_filing(file_name, extraction, target["activity"], confidence)


def _confidence(extraction):
	try:
		return float(extraction.get("confidence") or 0)
	except (TypeError, ValueError):
		return 0.0


def _unmatched(file_name, extraction, confidence):
	if frappe.db.exists("Compliance Unmatched Evidence", {"drive_file": file_name, "status": "Open"}):
		return
	frappe.get_doc(
		{
			"doctype": "Compliance Unmatched Evidence",
			"drive_file": file_name,
			"document_kind": extraction.get("document_kind"),
			"summary": extraction.get("summary"),
			"confidence": confidence,
			"status": "Open",
		}
	).insert(ignore_permissions=True)


def _notice(file_name, extraction):
	domain = _known_domain(extraction.get("domain")) or frappe.db.get_value("Compliance Domain", {}, "name")
	doc = frappe.get_doc(
		{
			"doctype": "Compliance Activity",
			"title": extraction.get("title") or "Notice",
			"domain": domain,
			"risk": "High",
			"scope": "Company" if extraction.get("company") else "Group",
			"company": extraction.get("company") if _known_company(extraction.get("company")) else None,
			"status": "Not Started",
			"due_date": frappe.utils.add_days(frappe.utils.getdate(), 7),
			"period_label": "Notice",
			"source": "Document ingest",
			"evidence_required": 1,
			"evidence": [{"drive_file": file_name, "note": extraction.get("summary"), "source": "Inbox"}],
		}
	)
	if doc.scope == "Company" and not doc.company:
		doc.scope = "Group"
	doc.insert(ignore_permissions=True)


def _prepare_licence(extraction, target):
	plan = plan_licence(
		extraction,
		frappe.get_all("Company", fields=["name", "company_name"]),
		frappe.get_all("Compliance Site", fields=["name", "location", "company"]),
		frappe.get_all(
			"Compliance Registration",
			fields=["name", "registration_type", "registration_number", "company", "site", "status"],
		),
		frappe.get_all("Compliance Domain", fields=["name", "default_owner"]),
		frappe.utils.getdate(),
	)
	if plan.get("action") != "licence":
		return target
	registration = plan.get("registration")
	if not registration and plan.get("create_registration"):
		created = {key: value for key, value in plan["create_registration"].items() if value is not None}
		registration = (
			frappe.get_doc({"doctype": "Compliance Registration", **created})
			.insert(ignore_permissions=True)
			.name
		)
	if not registration:
		return target
	prepared = {
		"action": "licence",
		"registration": registration,
		"activity": target.get("activity") if target.get("action") == "licence" else None,
		"renewal": plan.get("renewal"),
	}
	return prepared


def _licence(file_name, extraction, target, confidence):
	reg = frappe.get_doc("Compliance Registration", target["registration"])
	if extraction.get("valid_from"):
		reg.valid_from = extraction.get("valid_from")
	if extraction.get("valid_to"):
		reg.valid_to = extraction.get("valid_to")
	if extraction.get("registration_number"):
		reg.registration_number = extraction.get("registration_number")
	reg.append("evidence", {"drive_file": file_name, "note": extraction.get("summary"), "source": "Inbox"})
	reg.save(ignore_permissions=True)
	if target.get("renewal"):
		_ensure_renewal(reg.name, target["renewal"])
	if target.get("activity"):
		_filing(file_name, extraction, target["activity"], confidence)


def _ensure_renewal(registration, renewal):
	obligation = frappe.db.get_value(
		"Compliance Obligation",
		{"registration": registration, "frequency": "Expiry-based", "status": ["!=", "Inactive"]},
		"name",
	)
	if obligation:
		doc = frappe.get_doc("Compliance Obligation", obligation)
		changed = False
		if doc.status == "Draft":
			doc.status = "Active"
			changed = True
		if (doc.generate_ahead_days or 0) < renewal["generate_ahead_days"]:
			doc.generate_ahead_days = renewal["generate_ahead_days"]
			changed = True
		if changed:
			doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Compliance Obligation",
				"title": renewal["title"],
				"domain": renewal["domain"],
				"risk": "Medium",
				"status": "Active",
				"source": "Document ingest",
				"description": renewal.get("description") or "",
				"scope": renewal["scope"],
				"company": renewal["company"],
				"site": renewal.get("site"),
				"registration": registration,
				"frequency": "Expiry-based",
				"evidence_required": 1,
				"auto_complete_from_evidence": 0,
				"responsible_user": renewal.get("responsible_user"),
				"generate_ahead_days": renewal["generate_ahead_days"],
			}
		)
		doc.insert(ignore_permissions=True)
	ensure_expiry_activity(doc.name, renewal["due_date"])


def _filing(file_name, extraction, activity_name, confidence):
	activity = frappe.get_doc("Compliance Activity", activity_name)
	activity.append(
		"evidence", {"drive_file": file_name, "note": extraction.get("summary"), "source": "Inbox"}
	)
	if extraction.get("ack_no"):
		activity.ack_no = extraction.get("ack_no")
	if extraction.get("amount") not in (None, ""):
		activity.amount_paid = extraction.get("amount")
	threshold = 0.85
	if frappe.db.exists("Compliance Settings", "Compliance Settings"):
		threshold = float(
			frappe.db.get_single_value("Compliance Settings", "auto_complete_confidence") or 0.85
		)
	if activity.reviewer:
		activity.status = "Pending Review"
	elif (
		activity.auto_complete_from_evidence
		and confidence >= threshold
		and (activity.evidence or activity.ack_no)
	):
		activity.status = "Completed"
	activity.save(ignore_permissions=True)
	if activity.status not in ("Completed", "Pending Review") and activity.responsible_user:
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"subject": frappe._("Evidence added: {0}").format(activity.title),
				"for_user": activity.responsible_user,
				"type": "Alert",
				"document_type": "Compliance Activity",
				"document_name": activity.name,
			}
		).insert(ignore_permissions=True)


def _known_domain(name):
	if name and frappe.db.exists("Compliance Domain", name):
		return name
	return None


def _known_company(name):
	return bool(name and frappe.db.exists("Company", name))
