import frappe
from frappe.utils import now_datetime
from mpd_customizations.ai.gateway import AIGateway
from mpd_customizations.ai.workflow import apply_ai_transition
from mpd_customizations.ai.prompts.item import build_user_prompt


def run_ai_review(item_name: str):
    try:
        _run(item_name)
    except Exception as e:
        frappe.log_error(
            f"AI Review failed for {item_name}", str(e)
        )
        try:
            apply_ai_transition(
                doctype="Item",
                docname=item_name,
                action="AI Flag",
                comment=(
                    f"AI review job failed with error: {e}\n"
                    "Please review manually."
                ),
            )
        except Exception:
            pass


def _run(item_name: str):
    state = frappe.db.get_value(
        "Item", item_name, "workflow_state"
    )
    if state != "Pending AI Review":
        return

    item = frappe.get_doc("Item", item_name)

    similar = frappe.get_all(
        "Item",
        filters={"name": ["!=", item_name]},
        fields=["item_code", "item_name", "item_group"],
        limit=200,
    )

    gateway = AIGateway("item_review")
    result  = gateway.run(
        user_prompt=build_user_prompt(
            item.as_dict(), similar
        ),
        doc_type="Item",
        doc_name=item_name,
    )

    threshold = gateway.task.confidence_threshold or 75
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
        doctype="Item",
        docname=item_name,
        action=action,
        comment=comment,
    )

    frappe.db.set_value("Item", item_name, {
        "ai_review_brief":     result["brief"],
        "ai_confidence_score": result["confidence"],
        "ai_decision":         result["decision"],
        "ai_reviewed_on":      now_datetime(),
        "ai_model_used":       gateway.task.model_string,
    })
    frappe.db.commit()

    if action == "AI Flag":
        _notify_approvers(item, result)
    else:
        _notify_requester(item, result)


def _notify_approvers(item, result):
    ai_user = frappe.db.get_single_value(
        "LLM Task Settings", "ai_system_user"
    )
    approvers = frappe.get_all(
        "Has Role",
        filters={
            "role":       "Master Approver",
            "parenttype": "User",
        },
        fields=["parent"],
    )
    issues_html = "".join(
        f"<li>{i}</li>"
        for i in result.get("issues", [])
    )
    url = f"{frappe.utils.get_url()}/app/item/{item.name}"

    for a in approvers:
        if a["parent"] == ai_user:
            continue
        frappe.sendmail(
            recipients=[a["parent"]],
            subject=f"[Review Needed] Item: {item.item_name}",
            message=f"""
                <p>The AI reviewer flagged this item
                   and needs your decision.</p>
                <table cellpadding="6">
                  <tr>
                    <td><b>Item</b></td>
                    <td>{item.item_name} ({item.item_code})</td>
                  </tr>
                  <tr>
                    <td><b>AI Confidence</b></td>
                    <td>{result['confidence']}/100</td>
                  </tr>
                  <tr>
                    <td><b>Summary</b></td>
                    <td>{result['brief']}</td>
                  </tr>
                </table>
                <p><b>Issues:</b><ul>{issues_html}</ul></p>
                <p><a href="{url}">Open Item to Review →</a></p>
            """,
            now=True,
        )


def _notify_requester(item, result):
    requested_by = frappe.db.get_value(
        "Workflow Action",
        {
            "reference_doctype": "Item",
            "reference_name":    item.name,
            "action":            "Submit for Review",
        },
        "user",
    )
    if not requested_by:
        return
    url = f"{frappe.utils.get_url()}/app/item/{item.name}"
    frappe.sendmail(
        recipients=[requested_by],
        subject=f"[AI Approved] Item: {item.item_name}",
        message=f"""
            <p>Your item has been approved by AI review
               and is now live.</p>
            <p><b>Item:</b> {item.item_name}</p>
            <p><b>Confidence:</b> {result['confidence']}/100</p>
            <p><b>Summary:</b> {result['brief']}</p>
            <p><a href="{url}">View Item →</a></p>
        """,
        now=True,
    )
