import frappe

from mpd_customizations.drive.services.access import require_folder
from mpd_customizations.drive.services.folders import set_sharing


@frappe.whitelist()
def get_sharing(folder):
	require_folder(folder, "Manage")
	doc = frappe.get_doc("Drive Folder", folder)
	return {
		"inherit_permissions": doc.inherit_permissions,
		"rules": [
			{
				"principal_type": row.principal_type,
				"role": row.role,
				"user": row.user,
				"level": row.level,
			}
			for row in doc.permissions
		],
	}


@frappe.whitelist()
def set_folder_sharing(folder, rules, inherit=1):
	require_folder(folder, "Manage")
	if isinstance(rules, str):
		rules = frappe.parse_json(rules)
	doc = set_sharing(folder, rules, frappe.utils.cint(inherit))
	return {"name": doc.name, "inherit_permissions": doc.inherit_permissions}


@frappe.whitelist()
def set_inbox(folder, is_ai_inbox, inbox_kind="General", organise_into=None):
	require_folder(folder, "Manage")
	doc = frappe.get_doc("Drive Folder", folder)
	doc.is_ai_inbox = frappe.utils.cint(is_ai_inbox)
	doc.inbox_kind = inbox_kind or "General"
	doc.organise_into = organise_into
	doc.save()
	return {"name": doc.name, "is_ai_inbox": doc.is_ai_inbox, "inbox_kind": doc.inbox_kind}
