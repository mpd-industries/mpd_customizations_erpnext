import frappe
from frappe.utils import now_datetime, add_to_date


def run_rate_validity_check():
	"""Daily job: notify Rate Managers about soon-to-expire material rates."""
	config = frappe.get_single("Costing Configuration")
	warning_days = config.rate_expiry_warning_days or 30
	threshold = add_to_date(now_datetime(), days=warning_days)

	expiring = frappe.get_all(
		"Material Rate",
		filters={
			"is_active": 1,
			"valid_to": ["between", [now_datetime(), threshold]],
		},
		fields=["name", "item", "city", "supplier", "valid_to"],
	)

	if not expiring:
		return

	rate_managers = frappe.get_all(
		"Has Role",
		filters={"role": "Rate Manager", "parenttype": "User"},
		fields=["parent"],
	)

	for user_row in rate_managers:
		frappe.sendmail(
			recipients=[user_row.parent],
			subject=f"{len(expiring)} Material Rate(s) expiring within {warning_days} days",
			message=(
				f"The following material rates expire within {warning_days} days:<br><br>"
				+ "<br>".join(
					f"{r.item} — {r.city} — {r.supplier} — expires {r.valid_to}"
					for r in expiring
				)
			),
		)
