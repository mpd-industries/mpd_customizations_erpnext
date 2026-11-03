import frappe
from frappe import _
from frappe.model.document import Document


class DriveFolder(Document):
	def validate(self):
		if self.is_ai_inbox and not self.organise_into:
			frappe.throw(_("An AI Inbox folder needs a folder to organise files into."))
		if self.organise_into and self.organise_into == self.name:
			frappe.throw(_("A folder cannot organise into itself."))
		if self.parent_drive_folder and self.parent_drive_folder == self.name:
			frappe.throw(_("A folder cannot be its own parent."))
