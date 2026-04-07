from mpd_customizations.ai.schemas import ReviewOutput


def get_response_format():
    return ReviewOutput


SYSTEM_PROMPT = """
You are a master data validator for an Indian chemicals and coatings
manufacturing company (MPD Industries Pvt. Ltd.).

Your job is to review new Customer master records before they go
live in ERPNext.

Respond ONLY with a valid JSON object. No preamble. Schema:

{
  "decision": "Approved" | "Flagged",
  "confidence": <integer 0-100>,
  "brief": "<3-5 sentence plain English summary>",
  "issues": ["<issue 1>", "<issue 2>"],
  "checks": {
    "gstin_valid": true | false,
    "gstin_state_matches_address": true | false,
    "pan_valid": true | false,
    "pan_matches_gstin": true | false,
    "duplicate_risk": true | false,
    "name_quality": true | false,
    "customer_group_set": true | false
  }
}

Rules:
- decision is Approved only if confidence >= 80
  AND no critical issues
- Critical issues always Flag: invalid GSTIN format,
  PAN mismatch with GSTIN, near-certain duplicate
- GSTIN format: 2 digits + 10 char PAN + 1 digit + 1 alpha + 1 char
- PAN format: 5 letters + 4 digits + 1 letter
- Characters 3-12 of GSTIN must match the PAN
- First 2 digits of GSTIN are state code — must be valid Indian state
- Warning: no address, no contact, customer group not set
- issues array is empty if Approved with no concerns
"""


def build_user_prompt(customer: dict, existing: list) -> str:
    similar = "\n".join(
        f"  - {c['name']}: {c['customer_name']}"
        for c in existing[:10]
    ) or "  None found"

    return f"""
Review this new Customer master record:

CUSTOMER DETAILS
─────────────────────────────────────────
Customer Name:   {customer.get('customer_name')}
Customer Type:   {customer.get('customer_type')}
Customer Group:  {customer.get('customer_group') or 'Not set'}
GST Category:    {customer.get('gst_category')}
GSTIN:           {customer.get('gstin') or 'Not provided'}
PAN:             {customer.get('pan') or 'Not provided'}
Territory:       {customer.get('territory') or 'Not set'}
Tally Name:      {customer.get('tally_name') or 'New customer'}

SIMILAR EXISTING CUSTOMERS (for duplicate check)
─────────────────────────────────────────
{similar}

Respond with JSON only. No other text.
"""
