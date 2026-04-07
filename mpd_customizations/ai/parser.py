import re
import json
import frappe

REQUIRED = {"decision", "confidence", "brief", "issues"}


def parse_response(raw: str) -> dict:
    text = raw.strip()

    for candidate in [
        text,
        _extract_code_block(text),
        _extract_first_object(text),
    ]:
        if candidate:
            result = _try_parse(candidate)
            if result:
                return normalise_parsed(result)

    frappe.log_error("LLM Parser failed", raw[:2000])
    return _fallback()


def _extract_code_block(text):
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    return m.group(1).strip() if m else None


def _extract_first_object(text):
    m = re.search(r"\{[\s\S]+\}", text)
    return m.group(0) if m else None


def _try_parse(text):
    try:
        data = json.loads(text)
        if isinstance(data, dict) and REQUIRED.issubset(data):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def normalise_parsed(data: dict) -> dict:
    """Normalize a parsed review dict to the canonical shape used downstream."""
    return _normalise(data)


def _normalise(data: dict) -> dict:
    decision = str(data.get("decision", "Flagged")).strip().title()
    if decision not in ("Approved", "Flagged"):
        decision = "Flagged"
    try:
        confidence = max(0, min(100, int(data.get("confidence", 0))))
    except (ValueError, TypeError):
        confidence = 0
    issues = data.get("issues", [])
    if isinstance(issues, str):
        issues = [issues]
    return {
        "decision":   decision,
        "confidence": confidence,
        "brief":      str(data.get("brief", "")).strip(),
        "issues":     [str(i) for i in issues if i],
        "checks":     data.get("checks", {}),
    }


def _fallback() -> dict:
    return {
        "decision":   "Flagged",
        "confidence": 0,
        "brief":      (
            "AI returned an unreadable response. "
            "Sent to Master Approver."
        ),
        "issues":     ["Parser error: invalid response format"],
        "checks":     {},
    }
