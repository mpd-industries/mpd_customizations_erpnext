"""
MCP (Model Context Protocol) server for Meeting Notes tools.

Exposes a JSON-RPC 2.0 endpoint at:
  POST /api/method/mpd_customizations.mcp.handle_mcp

Authentication: Frappe API key/secret via Authorization header:
  Authorization: token <api_key>:<api_secret>

Supported methods:
  initialize    — MCP handshake
  tools/list    — list available tools
  tools/call    — invoke a tool
"""

import json
import frappe
from frappe import _

from mpd_customizations.meeting_notes.action_extraction.tool_definitions import TOOL_DEFINITIONS
from mpd_customizations.meeting_notes.action_extraction import tools as _tools

_MCP_TOOL_SCHEMAS = [
    {
        "name": t["function"]["name"],
        "description": t["function"]["description"],
        "inputSchema": t["function"]["parameters"],
    }
    for t in TOOL_DEFINITIONS
]


@frappe.whitelist(allow_guest=False)
def handle_mcp():
    try:
        body = json.loads(frappe.request.data or "{}")
    except json.JSONDecodeError:
        return _rpc_error(None, -32700, "Parse error")

    rpc_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {})

    frappe.response["content_type"] = "application/json"

    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "mpd-meeting-notes", "version": "1.0.0"},
        }

    elif method == "tools/list":
        result = {"tools": _MCP_TOOL_SCHEMAS}

    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        try:
            tool_result = _dispatch_tool(tool_name, arguments)
            result = {
                "content": [{"type": "text", "text": json.dumps(tool_result, ensure_ascii=False)}],
                "isError": False,
            }
        except Exception as e:
            result = {
                "content": [{"type": "text", "text": str(e)}],
                "isError": True,
            }

    elif method == "notifications/initialized":
        return json.dumps({"jsonrpc": "2.0", "id": rpc_id, "result": {}})

    else:
        return _rpc_error(rpc_id, -32601, f"Method not found: {method}")

    return json.dumps({"jsonrpc": "2.0", "id": rpc_id, "result": result}, ensure_ascii=False)


def _dispatch_tool(name, args):
    dispatch = {
        "get_backlog": _tools.get_backlog,
        "create_pending_task": _tools.create_pending_task,
        "update_existing_task": _tools.update_existing_task,
    }
    fn = dispatch.get(name)
    if not fn:
        frappe.throw(_(f"Unknown tool: {name}"))
    return fn(**args)


def _rpc_error(rpc_id, code, message):
    frappe.response["content_type"] = "application/json"
    return json.dumps({
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": code, "message": message},
    })
