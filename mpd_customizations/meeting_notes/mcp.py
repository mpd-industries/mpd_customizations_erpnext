"""MCP endpoint kept at the original path so existing clients keep working."""

import frappe

from mpd_customizations.mpd_base.mcp.server import respond


@frappe.whitelist(allow_guest=False)
def handle_mcp():
	return respond()
