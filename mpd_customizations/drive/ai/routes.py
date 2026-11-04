"""Inbox routes into other features. Handlers return a doctype and name."""

import frappe

from mpd_customizations.drive.ai.filing import APR_HANDLER, s3_file_url


def run_route(file_name, handler):
	file_doc = frappe.get_doc("Drive File", file_name)
	if file_doc.routed_to_name:
		return
	function = frappe.get_attr(handler)
	result = function(file_name)
	if not result:
		return
	frappe.db.set_value(
		"Drive File",
		file_name,
		{"routed_to_doctype": result.get("doctype"), "routed_to_name": result.get("name")},
	)


def create_asset_procurement_record(file_name):
	"""Create a draft Asset Procurement Record that points at this Drive file in S3."""
	file_doc = frappe.get_doc("Drive File", file_name)
	url = s3_file_url(file_doc.s3_key, file_doc.original_filename or file_doc.title)
	apr = frappe.get_doc(
		{
			"doctype": "Asset Procurement Record",
			"asset_description": file_doc.ai_summary or file_doc.title,
			"uploaded_documents": [{"upload_file": url, "upload_status": "Queued"}],
		}
	)
	apr.insert(ignore_permissions=True)
	return {"doctype": "Asset Procurement Record", "name": apr.name}
