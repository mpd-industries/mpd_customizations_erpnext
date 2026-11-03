"""Shared MCP endpoint. Features register tool modules on the mpd_mcp_tool_modules hook."""

import json

import frappe


def registered_modules():
	modules = []
	for path in frappe.get_hooks("mpd_mcp_tool_modules") or []:
		modules.append(frappe.get_module(path))
	return modules


def all_tool_schemas():
	tools = []
	for module in registered_modules():
		tools.extend(getattr(module, "MCP_TOOL_SCHEMAS", []))
	return tools


def all_prompts():
	prompts = []
	for module in registered_modules():
		prompts.extend(getattr(module, "MCP_PROMPTS", []))
	return prompts


def dispatch(name, arguments):
	for module in registered_modules():
		names = getattr(module, "TOOL_NAMES", ())
		if name in names:
			return module.dispatch_tool(name, arguments)
	frappe.throw(frappe._(f"Unknown tool: {name}"))


def get_prompt(name, arguments=None):
	for module in registered_modules():
		prompts = {row["name"] for row in getattr(module, "MCP_PROMPTS", [])}
		if name in prompts and hasattr(module, "get_prompt"):
			return module.get_prompt(name, arguments or {})
	frappe.throw(frappe._(f"Unknown prompt: {name}"))


def respond():
	try:
		body = json.loads(frappe.request.data or "{}")
	except json.JSONDecodeError:
		return _error(None, -32700, "Parse error")
	rpc_id = body.get("id")
	method = body.get("method", "")
	params = body.get("params") or {}
	frappe.response["content_type"] = "application/json"
	if method == "initialize":
		result = {
			"protocolVersion": "2024-11-05",
			"capabilities": {"tools": {"listChanged": False}, "prompts": {"listChanged": False}},
			"serverInfo": {"name": "mpd", "version": "1.0.0"},
		}
	elif method == "tools/list":
		result = {"tools": all_tool_schemas()}
	elif method == "tools/call":
		try:
			payload = dispatch(params.get("name"), params.get("arguments") or {})
			result = {
				"content": [{"type": "text", "text": json.dumps(payload, default=str)}],
				"isError": False,
			}
		except Exception as exc:
			result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
	elif method == "prompts/list":
		result = {"prompts": all_prompts()}
	elif method == "prompts/get":
		result = get_prompt(params.get("name"), params.get("arguments") or {})
	elif method == "notifications/initialized":
		return json.dumps({"jsonrpc": "2.0", "id": rpc_id, "result": {}})
	else:
		return _error(rpc_id, -32601, f"Method not found: {method}")
	return json.dumps({"jsonrpc": "2.0", "id": rpc_id, "result": result}, default=str)


def _error(rpc_id, code, message):
	frappe.response["content_type"] = "application/json"
	return json.dumps({"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}})
