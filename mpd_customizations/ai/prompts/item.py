from mpd_customizations.ai.schemas import ReviewOutput


def get_response_format():
    """Prefer Pydantic structured output; gateway falls back to JSON mode if unsupported."""
    return ReviewOutput


SYSTEM_PROMPT = """
You are a master data validator for an Indian chemicals and coatings
manufacturing company (MPD Industries Pvt. Ltd.).

Your job is to review new Item master records before they go live
in ERPNext. The company manufactures paints, inks, coatings and
specialty chemicals. They also trade chemicals and have two divisions:
MPD (manufacturing) and Xcel (trading/distribution).

Respond ONLY with a valid JSON object. No preamble, no explanation
outside the JSON. Use this exact schema:

{
  "decision": "Approved" | "Flagged",
  "confidence": <integer 0-100>,
  "brief": "<3-5 sentence plain English summary of your review>",
  "issues": ["<issue 1>", "<issue 2>"],
  "checks": {
    "hsn_valid": true | false,
    "hsn_matches_item": true | false,
    "gst_rate_correct": true | false,
    "uom_appropriate": true | false,
    "duplicate_risk": true | false,
    "name_quality": true | false,
    "group_appropriate": true | false
  }
}

Rules:
- decision is Approved only if confidence >= 75
  AND no critical issues found
- Critical issues always Flag: invalid HSN format,
  GST rate mismatch with HSN, near-certain duplicate
- Warning issues reduce confidence but do not always Flag:
  UOM seems wrong for item type, name too short or vague,
  description missing
- issues array is empty if Approved with no concerns
- brief must be readable by a busy accountant in 10 seconds
- For chemicals: KG, LTR, MT are appropriate UOMs.
  NOS is suspicious unless it is equipment or packaging
- HSN for chemicals typically starts with 28, 29, 32, 38
"""


def build_user_prompt(item: dict, existing_items: list) -> str:
    similar = "\n".join(
        f"  - {i['item_code']}: {i['item_name']} "
        f"({i['item_group']})"
        for i in existing_items[:15]
    ) or "  None found"

    return f"""
Review this new Item master record:

ITEM DETAILS
─────────────────────────────────────────
Item Name:     {item.get('item_name')}
Item Code:     {item.get('item_code')}
Item Group:    {item.get('item_group')}
Stock UOM:     {item.get('stock_uom')}
Purchase UOM:  {item.get('purchase_uom') or 'Same as stock'}
Sales UOM:     {item.get('sales_uom') or 'Same as stock'}
HSN Code:      {item.get('gst_hsn_code')}
Tax Template:  {item.get('item_tax_template') or 'Not set'}
Is Stock Item: {item.get('is_stock_item')}
Has Batch:     {item.get('has_batch_no')}
Description:   {item.get('description') or 'Not provided'}
Tally Name:    {item.get('tally_name') or 'New item'}

SIMILAR EXISTING ITEMS (for duplicate check)
─────────────────────────────────────────
{similar}

Respond with JSON only. No other text.
"""
