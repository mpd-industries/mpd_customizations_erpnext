import json
import re

import frappe
import litellm


def _ascii_header(val):
    """HTTP headers must be ASCII; site URL or titles may contain Unicode."""
    if not val:
        return ""
    return str(val).encode("ascii", "replace").decode("ascii")


def call_llm(config, system_prompt, user_prompt,
             reference_doctype=None, reference_name=None,
             attached_file_data=None, attached_mime=None):
    """
    Makes a LiteLLM call using the given AI Task Config.
    Logs the result to LLM Review Log (best-effort).
    Returns parsed dict.

    """
    provider = frappe.get_doc("LLM Provider", config.llm_provider)

    user_content = _build_user_content(user_prompt, attached_file_data, attached_mime, config.model)

    completion_kwargs = {
        "model": config.model,
        "api_base": provider.api_base,
        "api_key": provider.get_password("api_key"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ],
        "temperature": config.temperature or 0.1,
        "max_tokens": config.max_tokens or 2000,
    }
    if _use_strict_json_mode(provider, config.model):
        completion_kwargs["response_format"] = {"type": "json_object"}

    extra = _openrouter_extra_headers(provider, config.model)
    if extra:
        completion_kwargs["extra_headers"] = extra

    # write the prompt to a file with timestamp 

    response = litellm.completion(**completion_kwargs)

    # write the response to a file with timestamp

    raw = (response.choices[0].message.content or "").strip()
    if not raw:
        raise ValueError("Empty LLM response content")

    _try_insert_llm_review_log(
        config=config,
        provider_name=config.llm_provider,
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        raw_response=raw,
        response=response,
    )
    result = _parse_llm_json(raw)

    return result


def _use_strict_json_mode(provider, model):
    """OpenRouter often rejects or ignores json_object; we parse JSON from text."""
    base = (provider.api_base or "").lower()
    m = (model or "").lower()
    if "openrouter.ai" in base or m.startswith("openrouter/"):
        return False
    return True


def _parse_llm_json(raw):
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE | re.MULTILINE)
        s = re.sub(r"\s*```\s*$", "", s)
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON object in LLM response: {s[:300]!r}")
    return json.loads(s[start : end + 1])


def _try_insert_llm_review_log(config, provider_name, reference_doctype, reference_name,
                               raw_response, response):
    usage = getattr(response, "usage", None)
    pt = getattr(usage, "prompt_tokens", None) if usage else None
    ct = getattr(usage, "completion_tokens", None) if usage else None
    tt = getattr(usage, "total_tokens", None) if usage else None
    try:
        log = frappe.get_doc({
            "doctype":            "LLM Review Log",
            "task_key":           config.task_key,
            "task_label":         config.task_label,
            "provider":           provider_name,
            "model_used":         config.model,
            "reference_doctype":  reference_doctype,
            "reference_name":     reference_name,
            "prompt_tokens":      pt or 0,
            "completion_tokens":  ct or 0,
            "total_tokens":       tt or 0,
            "raw_response":       (raw_response or "")[:65000],
            "triggered_by":       frappe.session.user,
            "triggered_on":       frappe.utils.now_datetime(),
        })
        log.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.log_error(
            title="LLM Review Log insert failed",
            message=frappe.get_traceback(),
        )


def _openrouter_extra_headers(provider, model):
    m = (model or "").lower()
    base = (provider.api_base or "").lower()
    if "openrouter.ai" in base or m.startswith("openrouter/"):
        site = frappe.utils.get_url() or "https://localhost"
        return {
            "HTTP-Referer": _ascii_header(site),
            "X-Title":      "MPD Item Request - AI classification",
        }
    return None


def _build_user_content(user_prompt, file_data, mime, model):
    if not file_data or not mime:
        return user_prompt

    if mime == "application/pdf":
        if not litellm.supports_pdf_input(model=model):
            frappe.log_error(
                title=f"Model {model} does not support PDF input - sending text only",
            )
            return user_prompt
        return [
            {"type": "text", "text": user_prompt},
            {"type": "file", "file": {"file_data": file_data}},
        ]

    if mime.startswith("image/"):
        return [
            {"type": "text",      "text": user_prompt},
            {"type": "image_url", "image_url": {"url": file_data}},
        ]

    return user_prompt
