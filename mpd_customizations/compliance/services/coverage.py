"""Structural gaps an agent can read. Pure data in, gap list out."""

from datetime import date, datetime, timedelta

SAFETY_DOMAINS = {"Factory & Safety", "Environment"}


def _as_date(value):
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	if isinstance(value, str) and value:
		try:
			return datetime.strptime(value[:10], "%Y-%m-%d").date()
		except ValueError:
			return None
	return None


def find_gaps(registrations, obligations, sites, activities, today, expiring_days=90):
	today = _as_date(today) or date.today()
	horizon = today + timedelta(days=int(expiring_days or 90))
	active_obligations = [row for row in obligations or [] if (row.get("status") or "Active") == "Active"]
	by_registration = {}
	for row in active_obligations:
		if row.get("registration"):
			by_registration.setdefault(row["registration"], []).append(row)
	gaps = []
	for reg in registrations or []:
		if (reg.get("status") or "Active") not in ("Active", "Applied"):
			continue
		linked = by_registration.get(reg.get("name")) or []
		if not linked:
			gaps.append(
				{
					"kind": "registration_without_obligation",
					"message": f"{reg.get('registration_type') or 'Registration'} {reg.get('registration_number') or reg.get('name')} has no obligation.",
					"registration": reg.get("name"),
					"company": reg.get("company"),
					"site": reg.get("site"),
				}
			)
		valid_to = _as_date(reg.get("valid_to"))
		if valid_to and today <= valid_to <= horizon:
			expiry = [row for row in linked if row.get("frequency") == "Expiry-based"]
			if not expiry:
				gaps.append(
					{
						"kind": "expiring_without_renewal",
						"message": f"{reg.get('registration_type') or 'Registration'} expires on {valid_to.isoformat()} with no renewal obligation.",
						"registration": reg.get("name"),
						"company": reg.get("company"),
						"site": reg.get("site"),
					}
				)
	for site in sites or []:
		if site.get("active") in (0, False):
			continue
		covered = {
			row.get("domain")
			for row in active_obligations
			if row.get("scope") == "Site" and row.get("site") == site.get("name")
		}
		missing = sorted(SAFETY_DOMAINS - covered)
		if missing:
			gaps.append(
				{
					"kind": "site_domain_gap",
					"message": f"{site.get('location') or site.get('name')} has no {', '.join(missing)} obligation.",
					"site": site.get("name"),
					"company": site.get("company"),
					"domains": missing,
				}
			)
	for row in active_obligations:
		if not row.get("responsible_user"):
			gaps.append(
				{
					"kind": "obligation_without_owner",
					"message": f"{row.get('title') or row.get('name')} has no owner.",
					"obligation": row.get("name"),
				}
			)
	for row in activities or []:
		if row.get("is_overdue") in (1, True) and (row.get("status") or "") not in (
			"Completed",
			"Not Applicable",
			"Waived",
		):
			gaps.append(
				{
					"kind": "missed_period",
					"message": f"{row.get('title') or row.get('name')} ({row.get('period_label') or ''}) is overdue.",
					"activity": row.get("name"),
				}
			)
		if (
			row.get("status") == "Completed"
			and row.get("evidence_required") in (1, True)
			and not int(row.get("evidence_count") or 0)
			and not (row.get("ack_no") or "").strip()
		):
			gaps.append(
				{
					"kind": "completion_without_evidence",
					"message": f"{row.get('title') or row.get('name')} was completed without evidence.",
					"activity": row.get("name"),
				}
			)
	return gaps
