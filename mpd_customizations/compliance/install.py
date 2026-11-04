"""Seed roles, domains, projects, the Drive library, and the evidence prompt."""

import frappe

from mpd_customizations.compliance.ai.prompts import EVIDENCE_EXTRACT_PROMPT

DOMAINS = [
	"Corporate & ROC",
	"Direct Tax",
	"GST & Indirect Tax",
	"Accounting & Audit",
	"Bank & Finance",
	"Labour & Payroll",
	"Factory & Safety",
	"Environment",
	"Product & Trade",
	"Controlled Substances",
	"Insurance",
	"Contracts & Other",
]


def after_install():
	after_migrate()


def after_migrate():
	if not frappe.db.exists("DocType", "Compliance Settings"):
		return
	_ensure_roles()
	_ensure_domains()
	_ensure_settings()
	_ensure_projects()
	_ensure_library()
	_ensure_prompt()
	_rename_legacy_inbox()
	frappe.db.commit()


def _ensure_roles():
	for role_name in ("Compliance Manager", "Compliance User"):
		if frappe.db.exists("Role", role_name):
			continue
		frappe.get_doc({"doctype": "Role", "role_name": role_name, "desk_access": 1, "is_custom": 1}).insert(
			ignore_permissions=True
		)


def _ensure_domains():
	for name in DOMAINS:
		if frappe.db.exists("Compliance Domain", name):
			continue
		frappe.get_doc({"doctype": "Compliance Domain", "domain_name": name}).insert(ignore_permissions=True)


def _ensure_settings():
	if frappe.db.exists("Compliance Settings", "Compliance Settings"):
		return
	frappe.get_doc({"doctype": "Compliance Settings"}).insert(ignore_permissions=True)


def _ensure_projects():
	if not frappe.db.exists("DocType", "Project"):
		return
	settings = frappe.get_single("Compliance Settings")
	known = {row.company: row for row in settings.companies}
	changed = False
	for company in frappe.get_all("Company", pluck="name"):
		title = f"Compliance — {company}"
		project = frappe.db.get_value("Project", {"project_name": title, "company": company}, "name")
		if not project:
			doc = frappe.get_doc(
				{
					"doctype": "Project",
					"naming_series": "PROJ-.####",
					"project_name": title,
					"company": company,
					"status": "Open",
				}
			)
			doc.insert(ignore_permissions=True)
			project = doc.name
		row = known.get(company)
		if row:
			if row.project != project:
				row.project = project
				changed = True
			continue
		settings.append("companies", {"company": company, "project": project})
		changed = True
	if changed:
		settings.save(ignore_permissions=True)


def _ensure_library():
	if not frappe.db.exists("DocType", "Drive Folder"):
		return
	from mpd_customizations.drive.services.folders import create_folder

	_rename_legacy_inbox()
	roots = frappe.get_all(
		"Drive Folder",
		filters={"title": "Compliance", "is_trashed": 0, "parent_drive_folder": ["is", "not set"]},
		pluck="name",
		order_by="creation asc",
	)
	settings = frappe.get_single("Compliance Settings")
	root = settings.library_folder if settings.library_folder in roots else (roots[0] if roots else None)
	if not root:
		root = create_folder("Compliance", ignore_permissions=True).name
		_grant(root, "All", "View")
	for extra in roots:
		if extra == root or _folder_has_files(extra):
			continue
		for child in frappe.get_all(
			"Drive Folder", filters={"parent_drive_folder": extra, "is_trashed": 0}, pluck="name"
		):
			if not _folder_has_files(child):
				frappe.db.set_value("Drive Folder", child, "is_trashed", 1)
		frappe.db.set_value("Drive Folder", extra, "is_trashed", 1)
	inbox = frappe.db.get_value(
		"Drive Folder",
		{"parent_drive_folder": root, "is_ai_inbox": 1, "is_trashed": 0},
		"name",
	)
	if not inbox:
		inbox = create_folder(
			"AI Input",
			parent=root,
			ignore_permissions=True,
			is_ai_inbox=1,
			inbox_kind="Compliance",
			organise_into=root,
		).name
		_grant(inbox, "All", "Edit")
	else:
		frappe.db.set_value(
			"Drive Folder",
			inbox,
			{"title": "AI Input", "inbox_kind": "Compliance", "organise_into": root},
		)
	settings = frappe.get_single("Compliance Settings")
	if settings.library_folder != root or settings.inbox_folder != inbox:
		settings.library_folder = root
		settings.inbox_folder = inbox
		settings.save(ignore_permissions=True)


def _folder_has_files(folder):
	return bool(frappe.db.count("Drive File", {"folder": folder, "is_trashed": 0}))


def _grant(folder, role, level):
	doc = frappe.get_doc("Drive Folder", folder)
	for row in doc.permissions or []:
		if row.principal_type == "Role" and row.role == role:
			return
	doc.append("permissions", {"principal_type": "Role", "role": role, "level": level})
	doc.save(ignore_permissions=True)


def _ensure_prompt():
	if not frappe.db.exists("DocType", "AI Task Config"):
		return
	if not frappe.db.exists("LLM Provider", "OpenRouter"):
		return
	name = frappe.db.get_value("AI Task Config", {"task_key": "compliance_evidence_extract"}, "name")
	if name:
		doc = frappe.get_doc("AI Task Config", name)
		if doc.system_prompt != EVIDENCE_EXTRACT_PROMPT:
			doc.system_prompt = EVIDENCE_EXTRACT_PROMPT
			doc.save(ignore_permissions=True)
		return
	frappe.get_doc(
		{
			"doctype": "AI Task Config",
			"name": "compliance_evidence_extract",
			"task_key": "compliance_evidence_extract",
			"task_label": "Compliance Evidence Extraction",
			"description": "Matches an uploaded licence, filing, or notice to the compliance register.",
			"llm_provider": "OpenRouter",
			"model": "openrouter/google/gemini-3.1-flash-lite",
			"temperature": 0.1,
			"max_tokens": 4000,
			"system_prompt": EVIDENCE_EXTRACT_PROMPT,
			"is_active": 1,
		}
	).insert(ignore_permissions=True)


def _rename_legacy_inbox():
	frappe.db.sql(
		"""update `tabDrive Folder` set inbox_kind = 'Compliance'
		where inbox_kind = 'Statutory Compliance'"""
	)
	frappe.db.sql(
		"""update `tabDrive Folder` set title = 'Compliance'
		where title = 'Statutory Compliance' and ifnull(parent_drive_folder, '') = ''"""
	)
