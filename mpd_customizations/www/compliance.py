import frappe

no_cache = 1

_DESK = {
	"calendar": "/desk/compliance-activity/view/calendar/default",
	"activities": "/desk/compliance-activity",
	"register": "/desk/compliance-obligation",
	"registrations": "/desk/compliance-registration",
	"sites": "/desk/compliance-site",
	"unmatched": "/desk/compliance-unmatched-evidence",
}


def get_context(context):
	path = frappe.request.path if frappe.request else "/compliance"
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=" + path
		raise frappe.Redirect
	parts = [part for part in path.split("/") if part]
	rest = parts[1:] if parts and parts[0] == "compliance" else parts
	if rest[:1] == ["activity"] and len(rest) > 1:
		target = "/desk/compliance-activity/" + rest[1]
	else:
		target = _DESK.get(rest[0] if rest else "", "/desk/compliance")
	frappe.local.flags.redirect_location = target
	raise frappe.Redirect
