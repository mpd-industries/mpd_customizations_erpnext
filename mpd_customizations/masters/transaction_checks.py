import frappe

HARD_BLOCK_STATES = {
    "Draft",
    "Pending AI Review",
    "AI Flagged",
    "Pending MA Review",
    "Rejected",
}

SOFT_WARN_STATES = {
    "AI Approved",
}


def check_items(doc, method):
    if "System Manager" in frappe.get_roles(frappe.session.user):
        return

    blocked, warned, retired = [], [], []

    for row in getattr(doc, "items", []):
        if not row.item_code:
            continue
        state = frappe.db.get_value(
            "Item", row.item_code, "workflow_state"
        )
        if not state:
            continue
        if state in HARD_BLOCK_STATES:
            blocked.append((row.item_code, state))
        elif state in SOFT_WARN_STATES:
            warned.append(row.item_code)
        elif state == "Retired":
            retired.append(row.item_code)

    if blocked:
        lines = "".join(
            f"<li>{c} — {s}</li>"
            for c, s in blocked
        )
        frappe.throw(
            msg=(
                f"The following items cannot be used "
                f"yet — approval pending:"
                f"<ul>{lines}</ul>"
                "Please wait for approval or contact "
                "the Master Approver."
            ),
            title="Items Not Approved",
        )

    if warned:
        lines = "".join(
            f"<li>{c}</li>" for c in warned
        )
        frappe.msgprint(
            msg=(
                f"These items are AI Approved but pending "
                f"final Master Approver sign-off:"
                f"<ul>{lines}</ul>"
                "You can proceed. The approver has "
                "been notified."
            ),
            title="Pending Final Approval",
            indicator="orange",
        )

    if retired:
        lines = "".join(
            f"<li>{c}</li>" for c in retired
        )
        frappe.msgprint(
            msg=(
                f"These items are Retired:"
                f"<ul>{lines}</ul>"
                "Please confirm this is intentional."
            ),
            title="Retired Items",
            indicator="red",
        )
