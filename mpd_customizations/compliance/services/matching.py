"""Choose what an extracted document should update."""

from datetime import date, datetime

LICENCE_KINDS = {"licence", "license", "certificate"}


def _kind(extraction):
	return (extraction.get("document_kind") or "").strip().lower().replace(" ", "_")


def is_licence(extraction):
	return _kind(extraction) in LICENCE_KINDS


def select_target(extraction, activity_ids, registration_ids):
	kind = (extraction.get("document_kind") or "").strip().lower().replace(" ", "_")
	activity = extraction.get("activity_id") or None
	registration = extraction.get("registration_id") or None
	known_activity = activity in set(activity_ids or [])
	known_registration = registration in set(registration_ids or [])
	if kind in ("", "unrelated", "unknown"):
		return {"action": "unmatched"}
	if kind in ("notice", "order"):
		return {"action": "notice", "activity": activity if known_activity else None}
	if kind in ("licence", "certificate", "license"):
		if known_registration:
			return {
				"action": "licence",
				"registration": registration,
				"activity": activity if known_activity else None,
			}
		return {"action": "unmatched"}
	if kind in ("filing_ack", "challan", "return", "filing"):
		if known_activity:
			return {"action": "filing", "activity": activity}
		return {"action": "unmatched"}
	if known_activity:
		return {"action": "filing", "activity": activity}
	if known_registration:
		return {"action": "licence", "registration": registration, "activity": None}
	return {"action": "unmatched"}


def plan_licence(extraction, companies, sites, registrations, domains, today):
	"""Decide the registration and renewal a licence should write.

	companies: {name, company_name}. sites: {name, location, company}.
	registrations: {name, registration_type, registration_number, company, site}.
	domains: {name, default_owner}. A licence with no matching registration is created
	when the company is known. A valid_to date adds a renewal due on that date.
	"""
	if not is_licence(extraction):
		return {"action": "unmatched"}
	today = _as_date(today)
	company = _match_company(extraction.get("company"), companies)
	if not company:
		return {"action": "unmatched"}
	site_text = (extraction.get("site") or "").strip()
	site = _match_site(site_text, company, sites)
	domain = _match_domain(extraction.get("domain") or extraction.get("registration_type"), domains)
	registration_type = (extraction.get("registration_type") or extraction.get("title") or "Licence").strip()
	number = (extraction.get("registration_number") or "").strip()
	valid_from = _as_date(extraction.get("valid_from"))
	valid_to = _as_date(extraction.get("valid_to"))
	known = {row.get("name") for row in registrations or []}
	named = extraction.get("registration_id") if extraction.get("registration_id") in known else None
	existing = named or _match_registration(
		registrations, company, site, registration_type, number
	)
	created = None
	if not existing:
		created = {
			"registration_type": registration_type,
			"registration_number": number or None,
			"company": company,
			"site": site,
			"authority": (extraction.get("authority") or "").strip() or None,
			"status": "Expired" if valid_to and today and valid_to < today else "Active",
			"valid_from": valid_from.isoformat() if valid_from else None,
			"valid_to": valid_to.isoformat() if valid_to else None,
			"domain": domain,
		}
	renewal = None
	if valid_to and domain:
		title = f"Renew {registration_type}"
		description = ""
		if site_text and not site:
			title = f"{title} — {site_text}"
			description = f"Site named on the document: {site_text}"
		ahead = 400
		if today:
			ahead = max(ahead, (valid_to - today).days + 1)
		owner = next(
			(row.get("default_owner") for row in domains or [] if row.get("name") == domain),
			None,
		)
		renewal = {
			"title": title,
			"domain": domain,
			"scope": "Site" if site else "Company",
			"company": company,
			"site": site,
			"due_date": valid_to.isoformat(),
			"period_label": f"Renewal {valid_to.isoformat()}",
			"responsible_user": owner,
			"description": description,
			"generate_ahead_days": ahead,
		}
	return {
		"action": "licence",
		"registration": existing,
		"create_registration": created,
		"renewal": renewal,
	}


def _as_date(value):
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	if isinstance(value, str) and value:
		try:
			return date.fromisoformat(value[:10])
		except ValueError:
			return None
	return None


def _match_company(text, companies):
	rows = list(companies or [])
	raw = (text or "").strip()
	if not raw:
		return rows[0]["name"] if len(rows) == 1 else None
	folded = raw.casefold()
	for row in rows:
		names = [row.get("name") or "", row.get("company_name") or ""]
		if any(name.casefold() == folded for name in names if name):
			return row["name"]
	for row in rows:
		label = (row.get("company_name") or row.get("name") or "").casefold()
		if label and (folded in label or label in folded):
			return row["name"]
	return rows[0]["name"] if len(rows) == 1 else None


def _match_site(text, company, sites):
	raw = (text or "").strip()
	if not raw:
		return None
	folded = raw.casefold()
	pool = [row for row in sites or [] if row.get("company") == company]
	for row in pool:
		for key in ("location", "name"):
			if (row.get(key) or "").casefold() == folded:
				return row["name"]
	for row in pool:
		for key in ("location", "name"):
			label = (row.get(key) or "").casefold()
			if label and (folded in label or label in folded):
				return row["name"]
	return None


def _match_domain(text, domains):
	names = [row.get("name") for row in domains or [] if row.get("name")]
	raw = (text or "").strip()
	if raw:
		folded = raw.casefold()
		for name in names:
			if name.casefold() == folded:
				return name
		for name in names:
			if folded in name.casefold() or name.casefold() in folded:
				return name
		for word in folded.replace("&", " ").split():
			if len(word) < 4:
				continue
			for name in names:
				if word in name.casefold():
					return name
	for name in names:
		if name.casefold() == "contracts & other":
			return name
	return names[0] if names else None


def _match_registration(registrations, company, site, registration_type, number):
	number_key = _norm_number(number)
	if number_key:
		for row in registrations or []:
			if _norm_number(row.get("registration_number")) == number_key:
				return row.get("name")
	type_key = (registration_type or "").casefold()
	for row in registrations or []:
		if row.get("company") != company:
			continue
		if (row.get("registration_type") or "").casefold() != type_key:
			continue
		if (row.get("site") or None) != (site or None):
			continue
		return row.get("name")
	return None


def _norm_number(value):
	return "".join(ch for ch in (value or "").casefold() if ch.isalnum())
