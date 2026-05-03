import re

import frappe


def compute_item_label(item_name, tally_name, tally_alias):
    """
    Builds a searchable label from item_name plus any unique tokens
    contributed by tally_name and tally_alias.

    A candidate is only appended when it introduces at least one
    alphanumeric token not already present in the accumulated string
    (case-insensitive). Parts are joined with ' | '.

    Examples:
      "Estocat 4102" + "ESTOCAT 4102" + "CRM0540"  → "Estocat 4102 | CRM0540"
      "Sofa Cut"     + "SOFA CUT - ORM0064" + "ORM0064" → "Sofa Cut | ORM0064"
      "Alkyd Resin ALK3060, 80%" + "ALKYD RESIN - ALK3060 80" + "ALK3060 80"
                                                     → "Alkyd Resin ALK3060, 80%"
    """
    def tokens(s):
        return set(re.findall(r"[a-z0-9]+", (s or "").lower()))

    alias = (tally_alias or "").strip()
    parts = [alias] if alias else []
    seen = tokens(alias)

    for candidate in [tally_name, item_name]:
        candidate = (candidate or "").strip()
        if not candidate:
            continue
        new_tokens = tokens(candidate) - seen
        if new_tokens:
            parts.append(candidate)
            seen |= tokens(candidate)

    return " | ".join(dict.fromkeys(p for p in parts if p))


def before_save(doc, method=None):
    doc.custom_item_label = compute_item_label(
        doc.item_name,
        doc.get("custom_tally_name"),
        doc.get("custom_tally_alias"),
    )


def on_trash(doc, method=None):
    if doc.custom_item_request:
        frappe.db.set_value("Item Request", doc.custom_item_request, "created_item_code", None)
