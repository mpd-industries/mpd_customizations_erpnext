"""Scope rules shared by obligations and activities."""


def scope_error(scope, company, site):
	scope = scope or "Company"
	if scope != "Group" and not company:
		return "Company is required unless the scope is Group."
	if scope == "Site" and not site:
		return "A site is required when the scope is Site."
	if scope != "Site" and site:
		return "A site is only set when the scope is Site."
	return None
