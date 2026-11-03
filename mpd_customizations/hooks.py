app_name = "mpd_customizations"
app_title = "Mpd Customizations"
app_publisher = "mpdindustries"
app_description = "Customizations For MPD Industries"
app_email = "ayush@mpdindustries.com"
app_license = "mit"

# Installation
# ------------
# Each feature registers its own steps in setup.FEATURE_INSTALLERS.

after_install = "mpd_customizations.setup.after_install"
after_migrate = "mpd_customizations.setup.after_migrate"

# mpd_base
# --------
# Item master customizations and the S3-backed File override.

doctype_js = {
	"Item": "public/js/item_custom.js",
}

doc_events = {
	"Item": {
		"before_save": "mpd_customizations.mpd_base.item_ai.item_hooks.before_save",
		"on_trash": "mpd_customizations.mpd_base.item_ai.item_hooks.on_trash",
	},
}

override_doctype_class = {
	"File": "mpd_customizations.mpd_base.files.file_override.CustomFile",
}

# costing
# -------

doc_events["Address"] = {
	"on_update": "mpd_customizations.costing.services.city_sync.on_address_update",
}

scheduler_events = {
	"daily": [
		"mpd_customizations.costing.services.rate_validity_monitor.run_rate_validity_check",
	],
}

fixtures = [
	{"dt": "Custom Field", "filters": [["module", "=", "Costing"]]},
	{
		"dt": "Role",
		"filters": [
			[
				"name",
				"in",
				[
					"Costing User",
					"Costing Approver",
					"Rate Manager",
					"Costing Sales",
					"R&D Manager",
					"Dispatch Manager",
				],
			]
		],
	},
	{"dt": "Costing Configuration"},
	{"dt": "Packaging Material"},
	{"dt": "Packaging Rate"},
]

# asset_organizer
# ---------------
# No hooks of its own; extraction jobs are enqueued from the doctype controller.

# meeting_notes
# -------------

doctype_js["Meeting Note"] = "meeting_notes/doctype/meeting_note/meeting_note.js"

scheduler_events["cron"] = {
	"*/15 * * * *": [
		"mpd_customizations.meeting_notes.action_extraction.pipeline.reset_stuck_jobs",
	],
}

# xfloor_costing
# --------------

doctype_js["Floor Project"] = "xfloor_costing/doctype/floor_project/floor_project.js"
doctype_js["Kit rates"] = "xfloor_costing/doctype/kit_rates/kit_rates.js"
doctype_js["Kit Coverage"] = "xfloor_costing/doctype/kit_coverage/kit_coverage.js"

fixtures.append({"dt": "Print Format", "filters": [["name", "in", ["Floor Project P&L"]]]})

# xfloor_cms
# ----------

fixtures.append({"dt": "Role", "filters": [["name", "in", ["Xfloor CMS Manager", "XFloor Costing Manager"]]]})

# drive
# -----

fixtures.append({"dt": "Role", "filters": [["name", "in", ["Drive Admin"]]]})

mpd_mcp_tool_modules = [
	"mpd_customizations.meeting_notes.mcp_registry",
	"mpd_customizations.drive.mcp_tools",
	"mpd_customizations.compliance.mcp_tools",
]

drive_inbox_handlers = {
	"Compliance": "mpd_customizations.compliance.ai.inbox.process_compliance_inbox",
	"Statutory Compliance": "mpd_customizations.compliance.ai.inbox.process_compliance_inbox",
}

website_route_rules = [
	{"from_route": "/drive/<path:app_path>", "to_route": "drive"},
	{"from_route": "/compliance/<path:app_path>", "to_route": "compliance"},
]

has_permission = {
	"Drive Folder": "mpd_customizations.drive.services.access.has_folder_permission",
	"Drive File": "mpd_customizations.drive.services.access.has_file_permission",
	"Compliance Activity": "mpd_customizations.compliance.services.access.has_permission",
	"Compliance Obligation": "mpd_customizations.compliance.services.access.has_permission",
	"Compliance Registration": "mpd_customizations.compliance.services.access.has_permission",
	"Compliance Site": "mpd_customizations.compliance.services.access.has_permission",
	"Compliance Company Profile": "mpd_customizations.compliance.services.access.has_permission",
	"Compliance Domain": "mpd_customizations.compliance.services.access.has_permission",
	"Compliance Settings": "mpd_customizations.compliance.services.access.has_permission",
	"Compliance Unmatched Evidence": "mpd_customizations.compliance.services.access.has_permission",
}

permission_query_conditions = {
	"Drive Folder": "mpd_customizations.drive.services.access.folder_query",
	"Drive File": "mpd_customizations.drive.services.access.file_query",
	"Compliance Activity": "mpd_customizations.compliance.services.access.activity_query",
	"Compliance Obligation": "mpd_customizations.compliance.services.access.obligation_query",
}

scheduler_events["daily"].extend(
	[
		"mpd_customizations.drive.services.tasks.cleanup_pending_uploads",
		"mpd_customizations.drive.services.tasks.cleanup_trash",
		"mpd_customizations.compliance.services.reminders.daily",
	]
)

doc_events["Task"] = {
	"on_update": "mpd_customizations.compliance.services.tasks.on_task_update",
}

fixtures.append({"dt": "Role", "filters": [["name", "in", ["Compliance Manager", "Compliance User"]]]})

# Shared
# ------
# Bench commands are collected in commands/__init__.py.

commands = ["mpd_customizations.commands"]

doctype_js["Project"] = "public/js/project_custom.js"

fixtures.insert(0, {"dt": "Custom Field", "filters": [["dt", "in", ["Task"]]]})
fixtures.insert(
	1, {"dt": "Property Setter", "filters": [["doc_type", "=", "Task"], ["field_name", "=", "description"]]}
)
