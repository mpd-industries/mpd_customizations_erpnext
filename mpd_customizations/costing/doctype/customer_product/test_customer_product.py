# Copyright (c) 2026, mpdindustries and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from mpd_customizations.costing.api.costing import approve_customer_product


class TestCustomerProduct(FrappeTestCase):
	def setUp(self):
		self.customer = self._ensure_customer()

	def tearDown(self):
		frappe.db.rollback()

	def _ensure_customer(self):
		name = "_Test CP Customer"
		if not frappe.db.exists("Customer", name):
			frappe.get_doc({
				"doctype": "Customer",
				"customer_name": name,
				"customer_type": "Company",
				"customer_group": frappe.db.get_value("Customer Group", {}, "name") or "All Customer Groups",
				"territory": frappe.db.get_value("Territory", {}, "name") or "All Territories",
			}).insert(ignore_permissions=True)
		return name

	def _make_customer_product(self, **kwargs):
		doc = frappe.get_doc({
			"doctype": "Customer Product",
			"customer": self.customer,
			"customer_product_code": kwargs.get("customer_product_code", frappe.generate_hash(length=8)),
		})
		for key, value in kwargs.items():
			if key != "customer_product_code":
				setattr(doc, key, value)
		doc.insert(ignore_permissions=True)
		return doc

	def test_new_product_is_draft(self):
		cp = self._make_customer_product()
		self.assertEqual(cp.status, "Draft")

	def test_formulations_promote_status(self):
		cp = self._make_customer_product()
		cp.append("formulations", {"bom": "BOM-TEST-001"})
		cp.save(ignore_permissions=True)
		self.assertEqual(cp.status, "Formulations Added")

	def test_clearing_formulations_reverts_to_draft(self):
		cp = self._make_customer_product()
		cp.append("formulations", {"bom": "BOM-TEST-001"})
		cp.save(ignore_permissions=True)
		cp.formulations = []
		cp.save(ignore_permissions=True)
		self.assertEqual(cp.status, "Draft")

	def test_approved_status_not_downgraded_on_edit(self):
		cp = self._make_customer_product()
		cp.append("formulations", {"bom": "BOM-TEST-001"})
		cp.margin_type = "Per kg of Output"
		cp.margin_rate = 5
		cp.status = "Formulations Added"
		cp.save(ignore_permissions=True)

		approve_customer_product(cp.name)

		cp = frappe.get_doc("Customer Product", cp.name)
		cp.product_description = "Updated after approval"
		cp.formulations = []
		cp.save(ignore_permissions=True)
		self.assertEqual(cp.status, "Approved")

	def test_approve_requires_margin(self):
		cp = self._make_customer_product()
		cp.append("formulations", {"bom": "BOM-TEST-001"})
		cp.save(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			approve_customer_product(cp.name)

	def test_approve_success(self):
		cp = self._make_customer_product()
		cp.append("formulations", {"bom": "BOM-TEST-001"})
		cp.margin_type = "Per kg of Output"
		cp.margin_rate = 10
		cp.save(ignore_permissions=True)

		result = approve_customer_product(cp.name)
		self.assertTrue(result["success"])

		cp.reload()
		self.assertEqual(cp.status, "Approved")
		self.assertEqual(cp.approved_by, frappe.session.user)
		self.assertTrue(cp.approved_on)

	def test_pricing_request_rejects_non_approved_customer_product(self):
		cp = self._make_customer_product()
		processor = frappe.db.get_value("Processor", {}, "name")
		if not processor:
			self.skipTest("No Processor master data available")

		pr = frappe.get_doc({
			"doctype": "Pricing Request",
			"customer_product": cp.name,
			"processor": processor,
			"solids_content_pct": 50,
		})

		with self.assertRaises(frappe.ValidationError):
			pr.insert(ignore_permissions=True)
