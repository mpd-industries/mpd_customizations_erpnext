app_name = "mpd_customizations"
commands = ["mpd_customizations.commands"]
app_title = "Mpd Customizations"
app_publisher = "mpdindustries"
app_description = "Customizations For MPD Industries"
app_email = "ayush@mpdindustries.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "mpd_customizations",
# 		"logo": "/assets/mpd_customizations/logo.png",
# 		"title": "Mpd Customizations",
# 		"route": "/mpd_customizations",
# 		"has_permission": "mpd_customizations.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/mpd_customizations/css/mpd_customizations.css"
# app_include_js = "/assets/mpd_customizations/js/mpd_customizations.js"

# include js, css files in header of web template
# web_include_css = "/assets/mpd_customizations/css/mpd_customizations.css"
# web_include_js = "/assets/mpd_customizations/js/mpd_customizations.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "mpd_customizations/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
    "Item": "public/js/item_custom.js",
    "Meeting Note": "meeting_notes/doctype/meeting_note/meeting_note.js",
    "Project": "public/js/project_custom.js",
}
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "mpd_customizations/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "mpd_customizations.utils.jinja_methods",
# 	"filters": "mpd_customizations.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "mpd_customizations.install.before_install"
# after_install = "mpd_customizations.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "mpd_customizations.uninstall.before_uninstall"
# after_uninstall = "mpd_customizations.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "mpd_customizations.utils.before_app_install"
# after_app_install = "mpd_customizations.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "mpd_customizations.utils.before_app_uninstall"
# after_app_uninstall = "mpd_customizations.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "mpd_customizations.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Item": {
		"before_save": "mpd_customizations.mpd_base.item_ai.item_hooks.before_save",
		"on_trash":    "mpd_customizations.mpd_base.item_ai.item_hooks.on_trash",
	}
}

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Fixtures
# --------

fixtures = [
    {"dt": "Custom Field", "filters": [["dt", "in", ["Task"]]]},
    {"dt": "Property Setter", "filters": [["doc_type", "=", "Task"], ["field_name", "=", "description"]]},
    {"dt": "Role", "filters": [["name", "in", ["Xfloor CMS Manager"]]]},
]

# Scheduled Tasks
# ---------------

scheduler_events = {
    "cron": {
        "*/15 * * * *": [
            "mpd_customizations.action_extraction.pipeline.reset_stuck_jobs"
        ]
    }
}

# Testing
# -------

# before_tests = "mpd_customizations.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "mpd_customizations.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "mpd_customizations.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["mpd_customizations.utils.before_request"]
# after_request = ["mpd_customizations.utils.after_request"]

# Job Events
# ----------
# before_job = ["mpd_customizations.utils.before_job"]
# after_job = ["mpd_customizations.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"mpd_customizations.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

after_install = "mpd_customizations.setup.after_install"
after_migrate = "mpd_customizations.setup.after_migrate"
