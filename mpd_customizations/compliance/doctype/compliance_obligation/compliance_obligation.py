import frappe
from frappe.model.document import Document

from mpd_customizations.compliance.services.scope import scope_error


class ComplianceObligation(Document):
	def validate(self):
		if self.scope != "Site":
			self.site = None
		error = scope_error(self.scope, self.company, self.site)
		if error:
			frappe.throw(error)
		if self.frequency == "Expiry-based" and not self.registration:
			frappe.throw("An expiry-based obligation needs a registration.")
		if frappe.flags.get("compliance_via_mcp") and self.is_new() and self.source == "Manual":
			self.source = "Agent"

	def on_update(self):
		if self.status == "Active":
			from mpd_customizations.compliance.services.generate import generate_for

			generate_for(self.name)
