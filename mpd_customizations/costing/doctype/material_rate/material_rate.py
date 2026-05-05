import frappe
from frappe.model.document import Document
from frappe.utils.data import get_datetime, now_datetime, add_days, get_last_day
from mpd_customizations.costing import RateConflictError
from dateutil.relativedelta import relativedelta

class MaterialRate(Document):
    def validate(self):
        if not self.is_active:
            return

        if not self.supplier:
            frappe.throw("Supplier must be set for active rates.")

        if not self.delivered_rate or self.delivered_rate <= 0:
            frappe.throw("Delivered Rate must be greater than zero.")

        if self.credit_days is None or self.credit_days < 0:
            frappe.throw("Supplier Credit Days cannot be negative.")

        now_dt = now_datetime()
        valid_from_dt = get_datetime(self.valid_from)

        if valid_from_dt < get_datetime(now_dt.strftime("%Y-%m-%d %H:%M:%S")):
            frappe.throw("Valid From cannot be in the past.")

        if not self.valid_to:
            self._set_default_valid_to()
            
        if self.valid_to and get_datetime(self.valid_to) <= valid_from_dt:
            frappe.throw("Valid To must be after Valid From.")

        if self.rate_type == "Ex-Works + Freight":
            self.delivered_rate = (self.ex_works_rate or 0) + (self.freight_per_unit or 0)

        self._check_overlap()

    def before_save(self):
        if self.rate_type == "Ex-Works + Freight":
            self.delivered_rate = (self.ex_works_rate or 0) + (self.freight_per_unit or 0)

    def _set_default_valid_to(self):
        config = frappe.get_single("Costing Configuration")
        if config.default_valid_to == "End of Month":
            self.valid_to = get_last_day(self.valid_from).strftime("%Y-%m-%d 23:59:59")
        elif config.default_valid_to == "End of Quarter":
            month = get_datetime(self.valid_from).month
            quarter = (month - 1) // 3 + 1
            last_month_of_quarter = quarter * 3
            year = get_datetime(self.valid_from).year
            last_day = get_last_day(f"{year}-{last_month_of_quarter:02d}-01")
            self.valid_to = last_day.strftime("%Y-%m-%d 23:59:59")
        elif config.default_valid_to == "Custom Days":
            days = config.default_valid_to_days or 30
            self.valid_to = add_days(self.valid_from, days).strftime("%Y-%m-%d 23:59:59")

    def _check_overlap(self):
        filters = {
            "item": self.item,
            "supplier": self.supplier,
            "city": self.city,
            "is_active": 1,
            "name": ("!=", self.name)
        }
        existing_rates = frappe.get_all("Material Rate", filters=filters, fields=["name", "valid_from", "valid_to"])
        
        for existing in existing_rates:
            ext_valid_from = get_datetime(existing.valid_from)
            ext_valid_to = get_datetime(existing.valid_to) if existing.valid_to else get_datetime("2099-12-31 23:59:59")
            my_valid_from = get_datetime(self.valid_from)
            my_valid_to = get_datetime(self.valid_to) if self.valid_to else get_datetime("2099-12-31 23:59:59")
            
            if ext_valid_from < my_valid_to and ext_valid_to > my_valid_from:
                if self.flags.get("auto_expire_confirmed"):
                    new_valid_to = (my_valid_from - relativedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
                    frappe.db.set_value("Material Rate", existing.name, "valid_to", new_valid_to)
                else:
                    raise RateConflictError(
                        "An active rate for this item from this supplier in this city already exists.",
                        conflicting_name=existing.name,
                        conflicting_valid_from=existing.valid_from,
                        conflicting_valid_to=existing.valid_to
                    )
