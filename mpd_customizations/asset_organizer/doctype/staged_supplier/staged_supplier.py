import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class StagedSupplier(Document):

    def before_save(self):
        if self.status in ("Converted", "Rejected") and not self.converted_by:
            self.converted_by = frappe.session.user
            self.converted_on = now_datetime()
