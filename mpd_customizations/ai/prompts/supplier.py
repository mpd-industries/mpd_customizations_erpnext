from mpd_customizations.ai.schemas import ReviewOutput


def get_response_format():
    return ReviewOutput


SYSTEM_PROMPT = """
You are a master data validator for an Indian chemicals and coatings
manufacturing company (MPD Industries Pvt. Ltd.).

Your job is to review new Supplier master records before they go
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
    "supplier_group_set": true | false,
    "supplier_type_appropriate": true | false
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
- Supplier group should match what they supply:
  Goods, Transportation, Expenses, Capital Goods, Import
- Warning: no address, supplier group not set
- issues array is empty if Approved with no concerns
"""


def build_user_prompt(supplier: dict, existing: list) -> str:
    similar = "\n".join(
        f"  - {s['name']}: {s['supplier_name']}"
        for s in existing[:10]
    ) or "  None found"

    return f"""
Review this new Supplier master record:

SUPPLIER DETAILS
─────────────────────────────────────────
Supplier Name:   {supplier.get('supplier_name')}
Supplier Type:   {supplier.get('supplier_type')}
Supplier Group:  {supplier.get('supplier_group') or 'Not set'}
GST Category:    {supplier.get('gst_category')}
GSTIN:           {supplier.get('gstin') or 'Not provided'}
PAN:             {supplier.get('pan') or 'Not provided'}
Is Transporter:  {supplier.get('is_transporter', 0)}
Tally Name:      {supplier.get('tally_name') or 'New supplier'}

SIMILAR EXISTING SUPPLIERS (for duplicate check)
─────────────────────────────────────────
{similar}

Respond with JSON only. No other text.
"""
