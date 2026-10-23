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

# Shared
# ------
# Bench commands are collected in commands/__init__.py.

commands = ["mpd_customizations.commands"]

doctype_js["Project"] = "public/js/project_custom.js"

fixtures.insert(0, {"dt": "Custom Field", "filters": [["dt", "in", ["Task"]]]})
fixtures.insert(
	1, {"dt": "Property Setter", "filters": [["doc_type", "=", "Task"], ["field_name", "=", "description"]]}
)
