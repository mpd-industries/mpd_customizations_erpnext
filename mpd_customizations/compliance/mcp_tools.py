"""MCP tools and prompts for an external agent. Schemas import nothing from Frappe."""


def _s():
	return {"type": "string"}


def _tool(name, description, properties, required=None):
	schema = {"type": "object", "properties": properties}
	if required:
		schema["required"] = required
	return {"type": "function", "function": {"name": name, "description": description, "parameters": schema}}


TOOL_DEFINITIONS = [
	_tool(
		"compliance_get_context", "Companies, sites, registrations, domains, and banks. Call this first.", {}
	),
	_tool(
		"compliance_register",
		"Obligations in the register.",
		{"company": _s(), "site": _s(), "domain": _s(), "status": _s(), "source": _s()},
	),
	_tool("compliance_coverage", "Coverage matrix and structural gaps.", {"company": _s()}),
	_tool(
		"compliance_list_activities",
		"Activities, filterable by company, site, domain, status, owner, period, overdue, and due dates.",
		{
			"company": _s(),
			"site": _s(),
			"domain": _s(),
			"status": _s(),
			"owner": _s(),
			"period": _s(),
			"overdue": {"type": "boolean"},
			"due_from": _s(),
			"due_to": _s(),
		},
	),
	_tool(
		"compliance_get_activity", "One activity, including checklist and evidence.", {"name": _s()}, ["name"]
	),
	_tool("compliance_get_obligation", "One obligation.", {"name": _s()}, ["name"]),
	_tool(
		"compliance_list_registrations",
		"Held licences and registration numbers.",
		{"company": _s(), "site": _s(), "expiring_within_days": {"type": "integer"}},
	),
	_tool("compliance_dashboard", "Counts, on-time percentage, and pending review.", {"company": _s()}),
	_tool(
		"compliance_unmatched_evidence", "Uploaded files that did not match an activity or registration.", {}
	),
	_tool("compliance_get_settings", "Reminder, project, and library settings.", {}),
	_tool(
		"compliance_add_obligation",
		"Add an obligation. It stays Draft unless activate is true.",
		{
			"title": _s(),
			"domain": _s(),
			"scope": _s(),
			"company": _s(),
			"site": _s(),
			"frequency": _s(),
			"activate": {"type": "boolean"},
		},
		["title", "domain"],
	),
	_tool("compliance_update_obligation", "Update an obligation.", {"name": _s()}, ["name"]),
	_tool("compliance_activate_obligation", "Activate a draft obligation.", {"name": _s()}, ["name"]),
	_tool("compliance_deactivate_obligation", "Deactivate an obligation.", {"name": _s()}, ["name"]),
	_tool(
		"compliance_add_registration",
		"Record a held licence or registration number.",
		{"registration_type": _s(), "company": _s(), "registration_number": _s()},
		["registration_type", "company"],
	),
	_tool("compliance_update_registration", "Update a registration.", {"name": _s()}, ["name"]),
	_tool(
		"compliance_add_site",
		"Add a compliance site. Creates the Location when it does not exist.",
		{"location": _s(), "company": _s(), "parent_location": _s()},
		["location", "company"],
	),
	_tool("compliance_update_site", "Update site facts.", {"name": _s()}, ["name"]),
	_tool(
		"compliance_update_company_profile",
		"Update facts an agent uses to judge applicability.",
		{"company": _s()},
		["company"],
	),
	_tool("compliance_add_domain", "Add a compliance domain.", {"domain_name": _s()}, ["domain_name"]),
	_tool(
		"compliance_add_activity",
		"Add an ad-hoc activity. It goes live immediately and creates a Task.",
		{"title": _s(), "domain": _s(), "due_date": _s(), "company": _s(), "scope": _s()},
		["title"],
	),
	_tool("compliance_update_activity", "Update an activity.", {"name": _s()}, ["name"]),
	_tool("compliance_start", "Mark an activity in progress.", {"name": _s()}, ["name"]),
	_tool("compliance_submit_for_review", "Send an activity to its reviewer.", {"name": _s()}, ["name"]),
	_tool(
		"compliance_complete",
		"Complete an activity, or send it for review when a reviewer is set.",
		{"name": _s(), "ack_no": _s(), "amount_paid": {"type": "number"}},
		["name"],
	),
	_tool("compliance_approve", "Approve an activity that is pending review.", {"name": _s()}, ["name"]),
	_tool("compliance_reject", "Send an activity back to its owner.", {"name": _s()}, ["name"]),
	_tool(
		"compliance_mark_not_applicable",
		"Close an activity as not applicable.",
		{"name": _s(), "na_reason": _s()},
		["name", "na_reason"],
	),
	_tool(
		"compliance_extend_due",
		"Move the due date of open activities for an obligation or a domain.",
		{"new_date": _s(), "reason": _s(), "obligation": _s(), "domain": _s(), "period_label": _s()},
		["new_date", "reason"],
	),
	_tool(
		"compliance_attach_evidence",
		"Attach an existing Drive file to an activity.",
		{"activity": _s(), "drive_file": _s(), "note": _s()},
		["activity", "drive_file"],
	),
	_tool(
		"compliance_link_evidence",
		"Link an unmatched upload to an activity or registration.",
		{"name": _s(), "activity": _s(), "registration": _s()},
		["name"],
	),
	_tool(
		"compliance_upload_target",
		"Drive folder id to upload evidence for one activity.",
		{"activity": _s()},
		["activity"],
	),
]


MCP_TOOL_SCHEMAS = [
	{
		"name": tool["function"]["name"],
		"description": tool["function"]["description"],
		"inputSchema": tool["function"]["parameters"],
	}
	for tool in TOOL_DEFINITIONS
]
TOOL_NAMES = {tool["function"]["name"] for tool in TOOL_DEFINITIONS}

MCP_PROMPTS = [
	{
		"name": "compliance_gap_review",
		"description": "Read the register and coverage, research applicable law outside ERPNext, and add Draft obligations.",
	},
	{
		"name": "compliance_weekly_review",
		"description": "Summarise overdue work, pending review, and the next actions.",
	},
]


def get_prompt(name, arguments=None):
	if name == "compliance_gap_review":
		text = (
			"Call compliance_get_context, compliance_coverage, and compliance_register. "
			"Research applicable Indian law outside this system for each company and site. "
			"Add Draft obligations with law_reference, source_reference, and applicability_reason. "
			"Do not activate them. Then summarise what is still unknown."
		)
	elif name == "compliance_weekly_review":
		text = (
			"Call compliance_dashboard, compliance_list_activities with overdue true, "
			"and list activities in Pending Review. Suggest the next actions. Do not close work unless asked."
		)
	else:
		raise ValueError(f"Unknown prompt: {name}")
	return {"messages": [{"role": "user", "content": {"type": "text", "text": text}}]}


def dispatch_tool(name, arguments):
	import frappe

	arguments = dict(arguments or {})
	frappe.flags.compliance_via_mcp = True
	try:
		return _call(name, arguments)
	finally:
		frappe.flags.compliance_via_mcp = False


def _call(name, arguments):
	from mpd_customizations.compliance.api import actions, evidence, query

	if name == "compliance_get_context":
		return query.context()
	if name == "compliance_register":
		return query.register(**arguments)
	if name == "compliance_coverage":
		return query.coverage(**arguments)
	if name == "compliance_list_activities":
		return query.list_activities(**arguments)
	if name == "compliance_get_activity":
		return query.get_activity(**arguments)
	if name == "compliance_get_obligation":
		return query.get_obligation(**arguments)
	if name == "compliance_list_registrations":
		return query.list_registrations(**arguments)
	if name == "compliance_dashboard":
		return query.dashboard(**arguments)
	if name == "compliance_unmatched_evidence":
		return query.unmatched()
	if name == "compliance_get_settings":
		return query.settings_view()
	if name == "compliance_add_obligation":
		return actions.add_obligation(**arguments)
	if name == "compliance_update_obligation":
		return actions.update_obligation(**arguments)
	if name == "compliance_activate_obligation":
		return actions.set_obligation_status(arguments["name"], "Active")
	if name == "compliance_deactivate_obligation":
		return actions.set_obligation_status(arguments["name"], "Inactive")
	if name == "compliance_add_registration":
		return actions.add_registration(**arguments)
	if name == "compliance_update_registration":
		return actions.update_registration(**arguments)
	if name == "compliance_add_site":
		return actions.add_site(**arguments)
	if name == "compliance_update_site":
		return actions.update_site(**arguments)
	if name == "compliance_update_company_profile":
		return actions.update_company_profile(**arguments)
	if name == "compliance_add_domain":
		return actions.add_domain(**arguments)
	if name == "compliance_add_activity":
		return actions.add_activity(**arguments)
	if name == "compliance_update_activity":
		return actions.update_activity(**arguments)
	if name == "compliance_start":
		return actions.act(arguments["name"], "start")
	if name == "compliance_submit_for_review":
		return actions.act(arguments["name"], "submit")
	if name == "compliance_complete":
		return actions.act(
			arguments["name"],
			"complete",
			ack_no=arguments.get("ack_no"),
			amount_paid=arguments.get("amount_paid"),
		)
	if name == "compliance_approve":
		return actions.act(arguments["name"], "approve")
	if name == "compliance_reject":
		return actions.act(arguments["name"], "reject")
	if name == "compliance_mark_not_applicable":
		return actions.act(arguments["name"], "not_applicable", na_reason=arguments.get("na_reason"))
	if name == "compliance_extend_due":
		return actions.move_due(**arguments)
	if name == "compliance_attach_evidence":
		return evidence.attach(arguments["activity"], arguments["drive_file"], note=arguments.get("note"))
	if name == "compliance_link_evidence":
		return evidence.link_unmatched(
			arguments["name"], activity=arguments.get("activity"), registration=arguments.get("registration")
		)
	if name == "compliance_upload_target":
		return evidence.upload_target(arguments["activity"])
	raise ValueError(f"Unknown tool: {name}")
