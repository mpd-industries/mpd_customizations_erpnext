import frappe
from frappe.utils import now_datetime
from mpd_customizations.ai.gateway import AIGateway
from mpd_customizations.ai.workflow import apply_ai_transition
from mpd_customizations.ai.prompts.supplier import build_user_prompt


def run_ai_review(supplier_name: str):
    try:
        _run(supplier_name)
    except Exception as e:
        frappe.log_error(
            f"AI Review failed for supplier {supplier_name}",
            str(e)
        )
        try:
            apply_ai_transition(
                doctype="Supplier",
                docname=supplier_name,
                action="AI Flag",
                comment=(
                    f"AI review job failed: {e}\n"
                    "Please review manually."
                ),
            )
        except Exception:
            pass


def _run(supplier_name: str):
    state = frappe.db.get_value(
        "Supplier", supplier_name, "workflow_state"
    )
    if state != "Pending AI Review":
        return

    supplier = frappe.get_doc("Supplier", supplier_name)

    similar = frappe.get_all(
        "Supplier",
        filters={"name": ["!=", supplier_name]},
        fields=["name", "supplier_name"],
        limit=100,
    )

    gateway = AIGateway("supplier_review")
    result  = gateway.run(
        user_prompt=build_user_prompt(
            supplier.as_dict(), similar
        ),
        doc_type="Supplier",
        doc_name=supplier_name,
    )

    threshold = gateway.task.confidence_threshold or 80
    action    = (
        "AI Approve"
        if result["decision"] == "Approved"
        and result["confidence"] >= threshold
        else "AI Flag"
    )

    issues_text = (
        "\n".join(f"• {i}" for i in result["issues"])
        if result["issues"] else "None"
    )
    comment = (
        f"Confidence: {result['confidence']}/100\n\n"
        f"{result['brief']}\n\n"
        f"Issues:\n{issues_text}"
    )

    apply_ai_transition(
        doctype="Supplier",
        docname=supplier_name,
        action=action,
        comment=comment,
    )

    frappe.db.set_value("Supplier", supplier_name, {
        "ai_review_brief":     result["brief"],
        "ai_confidence_score": result["confidence"],
        "ai_decision":         result["decision"],
        "ai_reviewed_on":      now_datetime(),
        "ai_model_used":       gateway.task.model_string,
    })
    frappe.db.commit()
