from contextlib import contextmanager
import frappe
from frappe.model.workflow import apply_workflow


def _get_ai_user() -> str:
    return (
        frappe.db.get_single_value(
            "LLM Task Settings", "ai_system_user"
        )
        or "ai.reviewer@mpdindustries.com"
    )


@contextmanager
def as_ai_user():
    previous = frappe.session.user
    try:
        frappe.set_user(_get_ai_user())
        yield
    finally:
        frappe.set_user(previous)


def apply_ai_transition(
    doctype: str,
    docname: str,
    action: str,
    comment: str = "",
):
    with as_ai_user():
        doc = frappe.get_doc(doctype, docname)
        apply_workflow(doc, action)

        if comment:
            frappe.get_doc({
                "doctype":           "Comment",
                "comment_type":      "Workflow",
                "reference_doctype": doctype,
                "reference_name":    docname,
                "content":           comment,
            }).insert(ignore_permissions=True)

        frappe.db.commit()
