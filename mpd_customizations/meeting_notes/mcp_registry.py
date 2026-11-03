"""Meeting-note tools registered on the shared MCP server."""

from mpd_customizations.meeting_notes.action_extraction import tools as _tools
from mpd_customizations.meeting_notes.action_extraction.tool_definitions import TOOL_DEFINITIONS

MCP_TOOL_SCHEMAS = [
	{
		"name": tool["function"]["name"],
		"description": tool["function"]["description"],
		"inputSchema": tool["function"]["parameters"],
	}
	for tool in TOOL_DEFINITIONS
]
TOOL_NAMES = {tool["function"]["name"] for tool in TOOL_DEFINITIONS}
MCP_PROMPTS = []


def dispatch_tool(name, arguments):
	import frappe

	dispatch = {
		"get_backlog": _tools.get_backlog,
		"create_pending_task": _tools.create_pending_task,
		"update_existing_task": _tools.update_existing_task,
	}
	fn = dispatch.get(name)
	if not fn:
		frappe.throw(frappe._(f"Unknown tool: {name}"))
	return fn(**(arguments or {}))
