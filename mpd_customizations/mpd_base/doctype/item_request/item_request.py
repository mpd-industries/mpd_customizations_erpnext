import json
import frappe
from frappe.model.document import Document
from mpd_customizations.mpd_base.item_ai.dedup import build_search_index


class ItemRequest(Document):

    def before_save(self):
        if not self.requested_by:
            self.requested_by = frappe.session.user

    def validate(self):
        self._check_snapshot_modified()

    def _check_snapshot_modified(self):
        """
        If any AI suggestion field has been changed after the snapshot
        was frozen, bump status to Pending MA Approval so the MA must
        review before the item is created.
        """
        if not self.ai_snapshot:
            return
        if self.status != "AI Reviewed":
            return

        snapshot = json.loads(self.ai_snapshot)

        fields_to_check = [
            ("ai_item_name_suggestion",      "item_name"),
            ("ai_prefix_suggestion",         "prefix"),
            ("ai_sub_category_suggestion",   "sub_category"),
            ("ai_item_group_suggestion",     "item_group"),
            ("ai_asset_category_suggestion", "asset_category"),
            ("ai_solids_suffix_suggestion",  "solids_suffix"),
        ]

        for doc_field, snap_key in fields_to_check:
            current  = self.get(doc_field) or None
            original = snapshot.get(snap_key) or None
            if current != original:
                self.status = "Pending MA Approval"
                return

    def on_trash(self):
        if self.created_item_code:
            frappe.db.set_value("Item", self.created_item_code, "custom_item_request", None)

    def rebuild_item_index(self):
        """Called after Item is created on approval."""
        build_search_index()