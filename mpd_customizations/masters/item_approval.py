import frappe


def on_update(doc, method):
    old = doc.get_doc_before_save()
    old_state = old.workflow_state if old else None
    new_state = doc.workflow_state

    if (old_state != "Pending AI Review"
            and new_state == "Pending AI Review"):
        frappe.enqueue(
            "mpd_customizations.jobs.review_item.run_ai_review",
            item_name=doc.name,
            queue="short",
            timeout=120,
            now=frappe.flags.in_test,
        )
