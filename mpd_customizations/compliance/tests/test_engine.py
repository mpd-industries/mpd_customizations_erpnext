import unittest
from datetime import date

from mpd_customizations.compliance.services.coverage import find_gaps
from mpd_customizations.compliance.services.matching import plan_licence, select_target
from mpd_customizations.compliance.services.schedule import occurrences
from mpd_customizations.compliance.services.scope import scope_error
from mpd_customizations.compliance.services.status import (
	evidence_block,
	overdue_flags,
	should_escalate,
	transition,
)


class TestSchedule(unittest.TestCase):
	def test_monthly_due_on_the_20th_of_the_next_month(self):
		rows = occurrences(
			{"frequency": "Monthly", "period_basis": "Calendar", "due_day": 20, "due_month_offset": 1},
			date(2026, 11, 1),
			date(2026, 11, 30),
		)
		self.assertEqual(rows[0]["period_label"], "Oct 2026")
		self.assertEqual(rows[0]["due_date"], date(2026, 11, 20))

	def test_quarterly_q4_override(self):
		rows = occurrences(
			{
				"frequency": "Quarterly",
				"period_basis": "Financial Year",
				"due_day": 7,
				"due_month_offset": 1,
				"schedule_overrides": [{"month": 3, "due_day": 30, "due_month_offset": 1}],
			},
			date(2027, 4, 1),
			date(2027, 4, 30),
		)
		labels = {row["period_label"]: row["due_date"] for row in rows}
		self.assertEqual(labels.get("FY 2026-27 Q4"), date(2027, 4, 30))

	def test_financial_year_versus_calendar(self):
		fy = occurrences(
			{"frequency": "Yearly", "period_basis": "Financial Year", "due_day": 31, "due_month_offset": 0},
			date(2027, 3, 1),
			date(2027, 3, 31),
		)
		cal = occurrences(
			{"frequency": "Yearly", "period_basis": "Calendar", "due_day": 31, "due_month_offset": 0},
			date(2026, 12, 1),
			date(2026, 12, 31),
		)
		self.assertEqual(fy[0]["period_label"], "FY 2026-27")
		self.assertEqual(cal[0]["period_label"], "2026")

	def test_expiry_based(self):
		rows = occurrences(
			{"frequency": "Expiry-based"},
			date(2026, 1, 1),
			date(2026, 12, 31),
			valid_to=date(2026, 6, 1),
		)
		self.assertEqual(rows[0]["due_date"], date(2026, 6, 1))
		self.assertTrue(rows[0]["period_label"].startswith("Renewal"))


class TestStatus(unittest.TestCase):
	def test_evidence_gate(self):
		self.assertIsNotNone(evidence_block(True, 0, ""))
		self.assertIsNone(evidence_block(True, 0, "ACK1"))
		self.assertIsNone(evidence_block(False, 0, ""))

	def test_reviewer_complete_waits(self):
		status, error = transition("In Progress", "complete", True)
		self.assertEqual(status, "Pending Review")
		self.assertIsNone(error)

	def test_overdue_and_escalation(self):
		self.assertEqual(overdue_flags("In Progress", date(2026, 1, 1), date(2026, 1, 10)), (True, 9))
		self.assertFalse(should_escalate(date(2026, 1, 1), date(2026, 1, 10), 14, False))
		self.assertTrue(should_escalate(date(2026, 1, 1), date(2026, 1, 20), 14, False))


class TestScope(unittest.TestCase):
	def test_site_requires_location(self):
		self.assertIsNotNone(scope_error("Site", "MPD", None))
		self.assertIsNone(scope_error("Site", "MPD", "Ujjain"))
		self.assertIsNone(scope_error("Group", None, None))
		self.assertIsNotNone(scope_error("Company", None, None))


class TestCoverage(unittest.TestCase):
	def test_registration_without_obligation(self):
		gaps = find_gaps(
			[{"name": "REG-1", "registration_type": "GSTIN", "status": "Active", "company": "MPD"}],
			[],
			[],
			[],
			date(2026, 10, 1),
		)
		self.assertEqual(gaps[0]["kind"], "registration_without_obligation")


class TestMatching(unittest.TestCase):
	def test_filing_ack_uses_known_activity(self):
		choice = select_target(
			{"document_kind": "filing_ack", "activity_id": "ACT-1"},
			["ACT-1"],
			[],
		)
		self.assertEqual(choice["action"], "filing")

	def test_unknown_licence_is_unmatched(self):
		choice = select_target({"document_kind": "licence", "registration_id": "missing"}, [], ["REG-1"])
		self.assertEqual(choice["action"], "unmatched")


COMPANIES = [{"name": "MPD Industries Pvt Ltd", "company_name": "MPD Industries Pvt Ltd"}]
SITES = [{"name": "site-1", "location": "Ujjain", "company": "MPD Industries Pvt Ltd"}]
DOMAINS = [
	{"name": "Factory & Safety", "default_owner": "plant@mpd"},
	{"name": "Contracts & Other", "default_owner": None},
]


class TestLicencePlan(unittest.TestCase):
	def test_factory_licence_creates_the_registration_and_a_renewal(self):
		plan = plan_licence(
			{
				"document_kind": "licence",
				"registration_type": "Factory Licence",
				"registration_number": "FL-100",
				"company": "MPD Industries",
				"site": "Ujjain",
				"domain": "Factory",
				"valid_from": "2024-05-01",
				"valid_to": "2027-05-01",
			},
			COMPANIES,
			SITES,
			[],
			DOMAINS,
			date(2026, 11, 3),
		)
		self.assertEqual(plan["action"], "licence")
		self.assertIsNone(plan["registration"])
		created = plan["create_registration"]
		self.assertEqual(created["company"], "MPD Industries Pvt Ltd")
		self.assertEqual(created["site"], "site-1")
		self.assertEqual(created["domain"], "Factory & Safety")
		self.assertEqual(created["status"], "Active")
		renewal = plan["renewal"]
		self.assertEqual(renewal["due_date"], "2027-05-01")
		self.assertEqual(renewal["period_label"], "Renewal 2027-05-01")
		self.assertEqual(renewal["scope"], "Site")
		self.assertEqual(renewal["responsible_user"], "plant@mpd")
		self.assertGreaterEqual(renewal["generate_ahead_days"], 180)

	def test_known_number_reuses_the_registration(self):
		plan = plan_licence(
			{
				"document_kind": "license",
				"registration_type": "Factory Licence",
				"registration_number": "fl 100",
				"company": "MPD Industries Pvt Ltd",
				"valid_to": "2027-05-01",
			},
			COMPANIES,
			SITES,
			[
				{
					"name": "REG-1",
					"registration_type": "Factory Licence",
					"registration_number": "FL-100",
					"company": "MPD Industries Pvt Ltd",
					"site": "site-1",
				}
			],
			DOMAINS,
			date(2026, 11, 3),
		)
		self.assertEqual(plan["registration"], "REG-1")
		self.assertIsNone(plan["create_registration"])
		self.assertEqual(plan["renewal"]["period_label"], "Renewal 2027-05-01")

	def test_unknown_company_stays_unmatched(self):
		plan = plan_licence(
			{"document_kind": "licence", "company": "Someone Else", "valid_to": "2027-05-01"},
			[*COMPANIES, {"name": "Other", "company_name": "Other Co"}],
			[],
			[],
			DOMAINS,
			date(2026, 11, 3),
		)
		self.assertEqual(plan["action"], "unmatched")

	def test_licence_without_an_expiry_has_no_renewal(self):
		plan = plan_licence(
			{
				"document_kind": "certificate",
				"registration_type": "Factory Licence",
				"company": "MPD Industries Pvt Ltd",
			},
			COMPANIES,
			[],
			[],
			DOMAINS,
			date(2026, 11, 3),
		)
		self.assertEqual(plan["action"], "licence")
		self.assertIsNone(plan["renewal"])
		self.assertIsNone(plan["create_registration"]["site"])

	def test_unnamed_site_still_renews_for_the_company(self):
		plan = plan_licence(
			{
				"document_kind": "licence",
				"registration_type": "Factory Licence",
				"company": "MPD Industries Pvt Ltd",
				"site": "Dewas",
				"domain": "Factory",
				"valid_to": "2026-01-01",
			},
			COMPANIES,
			SITES,
			[],
			DOMAINS,
			date(2026, 11, 3),
		)
		self.assertIsNone(plan["create_registration"]["site"])
		self.assertEqual(plan["create_registration"]["status"], "Expired")
		self.assertEqual(plan["renewal"]["scope"], "Company")
		self.assertIn("Dewas", plan["renewal"]["title"])
