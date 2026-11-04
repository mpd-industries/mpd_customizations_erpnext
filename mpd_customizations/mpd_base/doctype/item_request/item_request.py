import frappe
from frappe import _
from frappe.model.document import Document

from mpd_customizations.mpd_base.item_ai.dedup import build_search_index


def count_item_kind_flags(doc) -> int:
	return int(bool(doc.is_stock_item)) + int(bool(doc.is_fixed_asset)) + int(bool(doc.is_expense_item))


def validate_item_kind(doc):
	"""Exactly one of Stock, Fixed Asset, or Expense must be checked."""
	count = count_item_kind_flags(doc)
	if count == 1:
		return
	frappe.throw(
		_("Choose exactly one of Is Stock Item, Is Fixed Asset, or Expense."),
		title=_("Item kind required"),
	)


class ItemRequest(Document):
	def before_save(self):
		if not self.requested_by:
			self.requested_by = frappe.session.user

	def validate(self):
		validate_item_kind(self)

	def on_trash(self):
		if self.created_item_code:
			frappe.db.set_value("Item", self.created_item_code, "custom_item_request", None)

	def rebuild_item_index(self):
		"""Called after Item is created."""
		build_search_index()
