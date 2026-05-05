import frappe
from frappe.model.document import Document
from frappe.utils.data import get_datetime
from mpd_customizations.costing import RateConflictError
from dateutil.relativedelta import relativedelta

class ProcessingCharge(Document):
    def validate(self):
        if not self.item and not self.item_group:
            frappe.throw("At least one of Item or Item Group must be set.")

        if not self.charge_per_kg or self.charge_per_kg <= 0:
            frappe.throw("Charge per kg must be greater than zero.")

        if self.valid_to and get_datetime(self.valid_to) <= get_datetime(self.valid_from):
            frappe.throw("Valid To must be after Valid From.")

        self._check_overlap()

    def _check_overlap(self):
        if not self.is_active:
            return

        filters = {
            "processor": self.processor,
            "is_active": 1,
            "name": ("!=", self.name)
        }
        if self.item:
            filters["item"] = self.item
        elif self.item_group:
            filters["item_group"] = self.item_group
            filters["item"] = ("is", "not set")

        existing_charges = frappe.get_all("Processing Charge", filters=filters, fields=["name", "valid_from", "valid_to"])
        
        for existing in existing_charges:
            ext_valid_from = get_datetime(existing.valid_from)
            ext_valid_to = get_datetime(existing.valid_to) if existing.valid_to else get_datetime("2099-12-31 23:59:59")
            my_valid_from = get_datetime(self.valid_from)
            my_valid_to = get_datetime(self.valid_to) if self.valid_to else get_datetime("2099-12-31 23:59:59")
            
            if ext_valid_from < my_valid_to and ext_valid_to > my_valid_from:
                if self.flags.get("auto_expire_confirmed"):
                    new_valid_to = (my_valid_from - relativedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
                    frappe.db.set_value("Processing Charge", existing.name, "valid_to", new_valid_to)
                else:
                    raise RateConflictError(
                        "An active processing charge for this processor and item/group already exists.",
                        conflicting_name=existing.name,
                        conflicting_valid_from=existing.valid_from,
                        conflicting_valid_to=existing.valid_to
                    )
