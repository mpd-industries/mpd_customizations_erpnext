"""Permission checks for the compliance register."""

import frappe

BANK_DOMAIN = "Bank & Finance"
MANAGER_ROLES = ("System Manager", "Compliance Manager")
USER_ROLES = ("Compliance User",)


def roles(user=None):
	user = user or frappe.session.user
	if user == "Administrator":
		return {"Administrator", "System Manager", "Compliance Manager"}
	return set(frappe.get_roles(user))


def is_manager(user=None):
	return bool(roles(user) & set(MANAGER_ROLES)) or (user or frappe.session.user) == "Administrator"


def is_party(doc, user=None):
	user = user or frappe.session.user
	if not doc:
		return False
	return user in {doc.get("responsible_user"), doc.get("reviewer")}


def domain_name(doc):
	if not doc:
		return None
	return doc.get("domain")


def has_permission(doc, ptype="read", user=None):
	user = user or frappe.session.user
	if is_manager(user):
		return True
	if user == "Guest":
		return False
	doctype = getattr(doc, "doctype", None) or (doc.get("doctype") if doc else None)
	if doctype in ("Compliance Settings", "Compliance Domain") and ptype != "read":
		return False
	if ptype in ("create", "delete"):
		return False
	bank = domain_name(doc) == BANK_DOMAIN
	if bank and not is_party(doc, user):
		return False
	if ptype == "read":
		return bool(roles(user) & set(USER_ROLES)) or is_party(doc, user)
	if ptype == "write":
		return is_party(doc, user)
	return False


def require_manager():
	if not is_manager():
		frappe.throw(frappe._("Compliance Manager role required"), frappe.PermissionError)


def require_activity_write(doc):
	if not has_permission(doc, "write"):
		frappe.throw(frappe._("You cannot change this activity"), frappe.PermissionError)


def activity_query(user=None):
	user = user or frappe.session.user
	if is_manager(user):
		return ""
	escaped = frappe.db.escape(user)
	return (
		f"(`tabCompliance Activity`.domain != {frappe.db.escape(BANK_DOMAIN)} "
		f"OR `tabCompliance Activity`.responsible_user = {escaped} "
		f"OR `tabCompliance Activity`.reviewer = {escaped})"
	)


def obligation_query(user=None):
	user = user or frappe.session.user
	if is_manager(user):
		return ""
	escaped = frappe.db.escape(user)
	return (
		f"(`tabCompliance Obligation`.domain != {frappe.db.escape(BANK_DOMAIN)} "
		f"OR `tabCompliance Obligation`.responsible_user = {escaped} "
		f"OR `tabCompliance Obligation`.reviewer = {escaped})"
	)
