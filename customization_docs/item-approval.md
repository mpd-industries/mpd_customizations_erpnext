# MPD Industries — Item Creation AI Workflow
## Complete Implementation Plan for `mpd_customizations` Frappe App

---

## 1. Context & Background

### Company
MPD Industries Pvt. Ltd. is an Indian chemicals and coatings manufacturer. The ERPNext
instance is MPD (main company). Xcel is a trading division modelled as a Cost Center,
not a separate company. The system is mid-migration from Tally.

### Build this as well
A custom Frappe app called `mpd_customizations` already exists and is installed on the site
`production.localhost`. It already contains:

- `LLM Provider` DocType — stores provider configs (name, api_base, api_key_secret)
- `LLM Task` DocType — stores task definitions with system prompts
- `LLM Review Log` DocType — append-only audit trail of every LLM call
- `LLM Task Settings` Single DocType — stores `ai_system_user` reference
- The `Master Approver` role already exists



### LiteLLM
LiteLLM is already installed and used as the provider abstraction layer. All LLM calls go
through LiteLLM. The active provider is currently OpenRouter but the system must support
switching providers and models from the ERPNext UI without any code changes.

---

## 2. Item Code Naming Framework

Every item in ERPNext follows this structure:

```
PREFIX-NNNN          (most items)
PREFIX-NNNN-SS       (resin families — SS = solids % e.g. 99, 80, 70)
PREFIX-SUB-NNNN      (packaging — e.g. PKG-DRM-0001)
PREFIX-SUB-NNNN-SS   (packaged resin grades — rare)
```

### Rules
- `PREFIX` = 3-letter category code from the `Item Category Code` DocType
- `NNNN` = 4-digit zero-padded sequential number, unique per prefix
- `SS` = solids percentage suffix, only for resin families where `requires_solids_suffix = True`
- Codes are **permanent** — once assigned and used in any transaction, a code is never changed
- If an item is discontinued it is set to `disabled = 1`, never deleted or recycled
- Sequential numbers are assigned **only at MA approval** (or auto-approval — see Section 5)
- Two requests for the same prefix approved simultaneously must not get the same number
  (use a `SELECT ... FOR UPDATE` row lock when computing the next sequence number)

### Prefix categories (seed data — full list)

These must be created as fixture data in `Item Category Code`:

**Domain: Vegetable Oils & Fatty Derivatives**
| Prefix | Full Name |
|--------|-----------|
| VGO | Vegetable & Drying Oil |
| FAC | Fatty Acid |
| DMA | Dimer Acid & Oligomeric Acid |

**Domain: Chemical Raw Materials**
| Prefix | Full Name |
|--------|-----------|
| POL | Polyol (Pentaerythritol, Glycerine, Sorbitol, MEG…) |
| AHD | Anhydride (Phthalic, Maleic, TMA…) |
| ACA | Acid — Aromatic, Organic, Inorganic |
| PHN | Phenol & Phenol Derivatives |
| MNM | Monomer / Intermediate |
| AMN | Amine & Polyamine |
| ISO | Isocyanate |
| INO | Inorganic Chemical & Aldehyde Source |

**Domain: Solvents, Additives & Processing Aids**
| Prefix | Full Name |
|--------|-----------|
| SOL | Solvent (aromatic, aliphatic, ketone, ester, glycol ether…) |
| CAT | Catalyst, Metal Drier, Metal Salt |
| ADD | Additive, Stabiliser, Antioxidant |
| PYR | Photoinitiator, Peroxide, Radical Initiator |
| SRF | Surfactant & Emulsifier |
| FIL | Filter Medium & Bleaching Earth |
| PLT | Plasticiser |
| PIG | Pigment & Colorant |
| PLM | Polymer (HDPE, LDPE, Nylon…) |

**Domain: Resin & Product Families** (`requires_solids_suffix = True`)
| Prefix | Full Name |
|--------|-----------|
| ALK | Alkyd Resin |
| PES | Polyester Resin |
| PAM | Polyamide Resin |
| EPR | Epoxy Resin (Modified / Finished) |
| EPH | Epoxy Hardener / Curing Agent |
| AMR | Amino Resin (Melamine / Urea) |
| PHR | Phenolic Resin |
| EST | Ester Gum |
| FNP | Finished Pack / Tube Product (Xcel) |

**Domain: Packaging** (`has_sub_category = True`, sub_category_options = `DRM,CAN,CRB,LBL,BOX,SEL`)
| Prefix | Full Name |
|--------|-----------|
| PKG | Packaging Material |

**Domain: Hardware / MRO**
| Prefix | Full Name |
|--------|-----------|
| HRD | Hardware, Fastener, Fitting |
| MRO | Maintenance, Repair & Operations consumable |
| FAB | Fabrication item / custom-made part |

**Domain: Fixed Assets** (`has_sub_category = True`, sub_category_options = `PME,LAB,ELE,FUR,VEH,CIV`)
| Prefix | Full Name |
|--------|-----------|
| AST | Fixed Asset |

**Domain: Services & Utilities**
| Prefix | Full Name |
|--------|-----------|
| SRV | Service |
| UTL | Utility |

**Special**
| Prefix | Full Name |
|--------|-----------|
| OTH | Other / Unclassified — use when nothing fits; MA will assign correct prefix |

All records: `is_active = True`. Descriptions and `llm_guidance_notes` start empty — the MA
fills these in via the ERPNext UI over time to improve LLM accuracy.

---

## 3. New DocTypes to Create

### 3.1 `Item Category Code`

Standard DocType. `prefix` is the name field (unique, 3 letters).

| Field | Type | Notes |
|-------|------|-------|
| `prefix` | Data | Name field. Unique. e.g. `SOL` |
| `full_name` | Data | e.g. "Solvent (aromatic, aliphatic...)" |
| `domain` | Select | Chemicals / Packaging / Resins / Hardware / Fixed Assets / Services / Other |
| `description` | Long Text | What belongs here. Injected into LLM prompt. |
| `llm_guidance_notes` | Long Text | Disambiguation hints, common mistakes, edge cases for the LLM |
| `example_code` | Data | e.g. `SOL-0001` |
| `example_item_name` | Data | e.g. "Xylene Mix, Min 98%" |
| `requires_solids_suffix` | Check | Default 0. True for ALK, PES, PAM, EPR, EPH, AMR, PHR, EST |
| `has_sub_category` | Check | Default 0. True for PKG, AST |
| `sub_category_options` | Small Text | Comma-separated e.g. `DRM,CAN,CRB,LBL,BOX,SEL` |
| `is_active` | Check | Default 1. Inactive = excluded from prompt and new assignments |

Permissions: read for all roles, write for Master Approver and System Manager only.

### 3.2 `AI Task Config` (Standard DocType — central model registry)

This is the **central place for all LLM task configuration** across the entire
`mpd_customizations` app — not just item creation. Every LLM-powered feature (item
classification, CoA review, any future tasks) gets one record here. This replaces any
per-feature settings doctype.

The `task_key` field is the unique identifier used in code to look up config, e.g.
`"item_classification"`, `"coa_review"`. Adding a new LLM task means adding one record
here — no code changes to plumbing.

| Field | Type | Notes |
|-------|------|-------|
| `task_key` | Data | Name field. Unique slug used in code. e.g. `item_classification` |
| `task_label` | Data | Human-readable name. e.g. "Item Classification & Deduplication" |
| `description` | Small Text | What this task does. For documentation only. |
| `llm_provider` | Link → LLM Provider | Which provider to use for this task |
| `model` | Data | Model string passed to LiteLLM e.g. `openai/gpt-4o`, `anthropic/claude-3-5-sonnet`, `openrouter/anthropic/claude-3.5-sonnet` |
| `system_prompt` | Long Text | Full system prompt template for this task. Editable without deployment. |
| `temperature` | Float | Default 0.1. Low = consistent, high = creative. |
| `max_tokens` | Int | Default 2000. |
| `is_active` | Check | Default 1. Inactive tasks fall back to system default or raise a clear error. |
| `fallback_task` | Link → AI Task Config | Optional. If this task fails, retry with this config (e.g. cheaper model). |

**Task-specific extra config** — stored as child table rows so any task can have arbitrary
settings without adding columns:

Child table: `AI Task Config Parameter`

| Field | Type | Notes |
|-------|------|-------|
| `parameter_key` | Data | e.g. `confidence_threshold`, `max_candidates`, `dedup_threshold` |
| `parameter_value` | Data | String value — code parses to float/int as needed |
| `description` | Small Text | What this parameter does |

**Seed records to create as fixtures:**

| task_key | task_label | model | temperature | Key parameters |
|----------|------------|-------|-------------|----------------|
| `item_classification` | Item Classification & Deduplication | `openrouter/anthropic/claude-3.5-sonnet` | 0.1 | `confidence_threshold=0.85`, `max_candidates=10` |
| `coa_review` | Chart of Accounts Review | `openrouter/anthropic/claude-3.5-sonnet` | 0.1 | (existing task — migrate its prompt here) |

**Helper function** (add to `mpd_customizations/utils.py`):

```python
def get_task_config(task_key):
    """
    Fetch AI Task Config by task_key. Raises clear error if not found or inactive.
    Use this everywhere instead of frappe.get_single("Item AI Settings").
    """
    config = frappe.get_all("AI Task Config",
        filters={"task_key": task_key, "is_active": 1},
        fields=["name", "llm_provider", "model", "system_prompt",
                "temperature", "max_tokens", "fallback_task"],
        limit=1
    )
    if not config:
        frappe.throw(f"No active AI Task Config found for task key: '{task_key}'. "
                     f"Please configure it in AI Task Config.")
    doc = frappe.get_doc("AI Task Config", config[0].name)

    # Parse parameters into a plain dict for convenience
    params = {row.parameter_key: row.parameter_value for row in doc.parameters}
    return doc, params
```

Usage in any LLM task:
```python
config, params = get_task_config("item_classification")
threshold = float(params.get("confidence_threshold", 0.85))
```

Permissions: read for all roles (so staff can see what model is in use), write for
System Manager only.

---

## 4. Custom Fields on the Existing `Item` DocType

Add these fields via `custom_fields` in `mpd_customizations`. Group them into clearly
labelled sections on the Item form.

### Section: "Item Request" (visible to all, collapsible)

| Field | Type | Permlevel | Notes |
|-------|------|-----------|-------|
| `requester_description` | Text | 0 | Free-text description from the person requesting the item. Required before check. |
| `item_reference_files` | Attach / Table MultiSelect | 0 | Optional. One or more files (PDF invoice, datasheet, photo, spec sheet) the requester uploads to help the LLM classify the item. Stored as Frappe file attachments linked to this Item. |
| `gst_hsn_code` | Data | 0 | Standard ERPNext field — ensure it is prominent in this section |
| `is_fixed_asset` | Check | 0 | Standard ERPNext field |
| `is_stock_item` | Check | 0 | Standard ERPNext field |
| `tally_name` | Data | 0 | Optional. Exact legacy Tally item code (e.g. ORM0010). Read-only after first save if populated. |
| `tally_alias` | Data | 0 | Optional. Tally alias or proprietary supplier code (e.g. RZH 0670). |
| `legacy_material_code` | Data | 0 | Optional. Any other legacy or internal code from a previous system. Free-form. |
| `dedup_check_done` | Check | 2 | Hidden (permlevel 2). Set server-side only. Cleared automatically if description, tally_name, or tally_alias changes after it was set. |
| `item_approval_status` | Select | 0 (read), 1 (write MA only) | Draft / Pending Dedup Check / Dedup Confirmed / Pending AI Review / AI Reviewed / Duplicate Flagged / Pending MA Approval / Approved / Rejected |

All three legacy fields (`tally_name`, `tally_alias`, `legacy_material_code`) are always
visible in Phase 1 — no toggle required. They are optional. The LLM receives all three
if populated.

### Section: "AI Suggestion" (hidden until `item_approval_status` is not Draft)

All fields in this section are **permlevel 1** — readable by all, writable only by Master Approver role.

| Field | Type | Notes |
|-------|------|-------|
| `ai_item_name_suggestion` | Data | AI suggested item name |
| `ai_prefix_suggestion` | Link → Item Category Code | AI suggested prefix |
| `ai_sub_category_suggestion` | Data | AI suggested sub-category (if applicable) |
| `ai_item_group_suggestion` | Link → Item Group | AI suggested item group |
| `ai_asset_category_suggestion` | Link → Asset Category | AI suggested asset category (fixed assets only) |
| `ai_solids_suffix_suggestion` | Data | e.g. `99` — for resin families |
| `ai_review_brief` | Small Text | AI reasoning — 2-3 sentences |
| `ai_confidence_score` | Float | 0.0–1.0 |
| `ai_duplicate_warning` | Small Text | Non-null if LLM flagged a possible duplicate |
| `ai_reviewed_on` | Datetime | Read-only. Timestamp of review. |
| `ai_model_used` | Data | Read-only. Which model ran this review. |

### Section: "AI Snapshot" (hidden from UI entirely — permlevel 2)

| Field | Type | Notes |
|-------|------|-------|
| `ai_snapshot` | Long Text | Frozen JSON of exactly what the AI returned. Never modified after being written. |

### Section: "Approval" (visible to Master Approver only via depends_on)

| Field | Type | Permlevel | Notes |
|-------|------|-----------|-------|
| `ma_review_note` | Small Text | 1 | MA's comment when approving, rejecting, or resolving duplicate. Required on reject. |
| `approved_by` | Link → User | 1 | Read-only. Set on approval. |
| `approved_on` | Datetime | 1 | Read-only. Set on approval. |

### Existing fields (already present — do not recreate)
`ai_review_brief` and `ai_confidence_score` may already exist from the CoA workflow.
Check before adding — use the existing fields if present.

---

## 5. Approval Logic — The Core Rule

This is the most important business rule in the entire system:

```
IF   item_approval_status == "AI Reviewed"
AND  current AI field values == ai_snapshot values   (no human modification)
AND  ai_confidence_score >= confidence_threshold_for_auto_approve
THEN → status = "Approved" automatically, permanent code assigned, item usable

IF   any AI field was modified after the snapshot was written
OR   ai_confidence_score < confidence_threshold_for_auto_approve
OR   ai_duplicate_warning is not null
THEN → status = "Pending MA Approval", MA must review before item is usable
```

The snapshot comparison runs in the server-side `validate` hook on the Item DocType.
The comparison checks these fields against the snapshot:
- `ai_item_name_suggestion`
- `ai_prefix_suggestion`
- `ai_sub_category_suggestion`
- `ai_item_group_suggestion`
- `ai_asset_category_suggestion`
- `ai_solids_suffix_suggestion`

If any of these differ from the snapshot at save time, and the current status is
`AI Reviewed`, the status must flip to `Pending MA Approval` before the save completes.

The permanent item code (`item_code` / `name`) is assigned:
- Immediately by the background job if auto-approval conditions are met
- By the MA approval handler if MA review was required

Until the code is assigned, the item's `name` in Frappe is a temporary system-generated
name (Frappe autoname). The final code is written to `item_code` (a custom field that
eventually becomes the item name via a rename). Actually — use Frappe's naming series
override: set `autoname = "field:item_code"` is not practical here. Instead, create the
item with a temp name like `ITEM-DRAFT-{timestamp}` and rename it to the final code on
approval using `frappe.rename_doc`. Linked documents update automatically.

---

## 6. The Two-Phase UI Flow

### Phase 1: Fill & Deduplicate

The Item form in Draft state shows:
- `requester_description` (required before check button activates)
- `item_reference_files` — optional file upload. The user can attach a supplier invoice,
  product datasheet, MSDS, photo, or any document that describes the item. These are
  uploaded as Frappe file attachments and passed to the LLM as additional context.
  Accepted formats: PDF, PNG, JPG, JPEG. Multiple files allowed.
- `gst_hsn_code`
- `is_fixed_asset`, `is_stock_item`
- `tally_name` (optional)
- `tally_alias` (optional)
- `legacy_material_code` (optional)

One button: **[ Check for Similar Items ]**

This calls `check_item_duplicates` synchronously, passing `description`, `tally_name`,
`tally_alias`, and `legacy_material_code`. Returns up to `max_candidates` matches.

**If candidates found:**
A results section expands inline on the form showing a table of candidates:
item code, item name, item group, tally name if any. Each row has an **[ Open ]** link.

Below the table, one button:

**[ I acknowledge that these items are different from the existing ones ]**

No text input. No explanation required. The user reads the list, decides none match,
clicks the acknowledgement button. The server sets `dedup_check_done = 1`. The generate
button appears.

If they think one IS the same item, they click **[ Open ]** on that row to navigate to
the existing item. They do not proceed.

**If no candidates found:**
Green indicator: "No similar items found." `dedup_check_done = 1` set immediately.
Generate button appears.

**If description, tally_name, tally_alias, or legacy_material_code changes after
`dedup_check_done = 1`:**
Client script `onchange` on all four fields calls `reset_dedup` server-side,
hides the generate button, shows the check button again.

### Phase 2: Generate & Review

**[ Generate AI Suggestion ]** — only visible when `dedup_check_done = 1`.

Clicking it calls `enqueue_item_ai_review`. Status → `Pending AI Review`. Button disables.
Banner shows: "AI review in progress — refresh in a moment."

When background job completes:
- AI fields populated
- `ai_snapshot` written and frozen
- If auto-approval conditions met → code assigned, status → `Approved`
- If MA needed → status → `Pending MA Approval` or `Duplicate Flagged`

The requester refreshes. If `Approved`, done — item is usable immediately.
If `Pending MA Approval`, read-only AI fields visible with banner: "Sent to Master Approver."
If `Duplicate Flagged`, banner: "AI flagged a possible duplicate. Master Approver will resolve."

---

## 7. Deduplication — Layer 1 (Synchronous)

File: `mpd_customizations/item_ai/dedup.py`

```python
@frappe.whitelist()
def check_item_duplicates(description, tally_name=None, tally_alias=None,
                          legacy_material_code=None):
    """
    Fast synchronous duplicate check. Called before LLM review.
    Searches by description terms, tally_name, tally_alias, and legacy_material_code.

    Returns the top 5 most relevant candidates, scored by how many search passes
    they appeared in. A candidate that matched on tally_name AND description terms
    scores higher than one that matched on description alone.

    The LLM also receives these same 5 candidates in its prompt so it can make
    a final semantic judgement before classifying.
    """
    from mpd_customizations.utils import get_task_config
    _, params = get_task_config("item_classification")

    # Score dict: name → {record, score}
    scored = {}

    def add_candidate(record, points):
        name = record["name"]
        if name not in scored:
            scored[name] = {"record": record, "score": 0}
        scored[name]["score"] += points

    # Pass 1: term search on item_name (1 point per term match)
    terms = extract_search_terms(description)
    for term in terms:
        results = frappe.get_all("Item",
            filters=[
                ["item_name", "like", f"%{term}%"],
                ["disabled", "=", 0],
                ["name", "not like", "ITEM-DRAFT-%"],
            ],
            fields=["name", "item_name", "item_group", "item_approval_status",
                    "tally_name", "tally_alias", "legacy_material_code", "gst_hsn_code"],
            limit=50
        )
        for r in results:
            add_candidate(r, 1)

    # Pass 2: exact tally_name match (high signal — 10 points)
    if tally_name:
        results = frappe.get_all("Item",
            filters={"tally_name": tally_name, "disabled": 0},
            fields=["name", "item_name", "item_group", "item_approval_status",
                    "tally_name", "tally_alias", "legacy_material_code", "gst_hsn_code"]
        )
        for r in results:
            add_candidate(r, 10)

    # Pass 3: exact tally_alias match (high signal — 10 points)
    if tally_alias:
        results = frappe.get_all("Item",
            filters={"tally_alias": tally_alias, "disabled": 0},
            fields=["name", "item_name", "item_group", "item_approval_status",
                    "tally_name", "tally_alias", "legacy_material_code", "gst_hsn_code"]
        )
        for r in results:
            add_candidate(r, 10)

    # Pass 4: legacy_material_code match (high signal — 10 points)
    if legacy_material_code:
        results = frappe.get_all("Item",
            filters={"legacy_material_code": legacy_material_code, "disabled": 0},
            fields=["name", "item_name", "item_group", "item_approval_status",
                    "tally_name", "tally_alias", "legacy_material_code", "gst_hsn_code"]
        )
        for r in results:
            add_candidate(r, 10)

    # Sort by score descending, return top 5
    sorted_candidates = sorted(
        scored.values(), key=lambda x: x["score"], reverse=True
    )
    return [c["record"] for c in sorted_candidates[:5]]


@frappe.whitelist()
def confirm_dedup(item_name):
    """
    Called when user clicks the acknowledgement button confirming these candidates
    are different from the item they are creating. No text reason required.
    Sets dedup_check_done = 1.
    """
    frappe.db.set_value("Item", item_name, "dedup_check_done", 1)
    frappe.db.commit()
    return {"status": "confirmed"}


@frappe.whitelist()
def reset_dedup(item_name):
    """
    Called client-side when description, tally_name, tally_alias, or
    legacy_material_code changes after dedup was already confirmed.
    Forces the user to re-check before generating.
    """
    frappe.db.set_value("Item", item_name, "dedup_check_done", 0)
    frappe.db.commit()
    return {"status": "reset"}


def extract_search_terms(description):
    """
    Extract meaningful search terms from description.
    Strips chemical stop words, splits on common separators.
    Returns terms of 4+ characters.
    """
    import re
    stop_words = {
        "with", "and", "the", "for", "min", "max", "grade", "type", "class",
        "approx", "technical", "pure", "purity", "acid", "value", "resin",
        "based", "from", "this", "that", "used", "made", "have", "high",
    }
    words = re.split(r'[\s,/\-\(\)\.%]+', description.lower())
    return [w for w in words if len(w) >= 4 and w not in stop_words]
```

---

## 8. LLM Review — Layer 2 (Background Job)

File: `mpd_customizations/item_ai/review.py`

### Prompt builder

```python
def build_item_review_prompt(doc, top_candidates):
    """
    Builds the full user-turn prompt by fetching live data from ERPNext.

    top_candidates: list of up to 5 candidate dicts from check_item_duplicates.
    These are passed directly to the LLM for a final semantic dedup decision —
    the LLM only needs to evaluate these 5, not the entire item master.

    All available item metadata is sent including HSN, tally fields, legacy codes.
    Attached files (invoices, datasheets) are fetched and included as base64
    for models that support vision/document input.
    """
    # 1. Active Item Category Codes
    categories = frappe.get_all("Item Category Code",
        filters={"is_active": 1},
        fields=["prefix", "full_name", "domain", "description",
                "example_code", "example_item_name", "requires_solids_suffix",
                "has_sub_category", "sub_category_options", "llm_guidance_notes"]
    )

    # 2. Leaf Item Groups only (is_group = 0)
    # IMPORTANT: Never fetch parent/group nodes. If the LLM picks a parent node,
    # ERPNext will reject it. Only leaf nodes are valid item group values.
    item_groups = frappe.get_all("Item Group",
        filters={"is_group": 0},
        fields=["name"],
        order_by="name"
    )

    # 3. Asset Categories (only if fixed asset)
    asset_categories = []
    if doc.is_fixed_asset:
        asset_categories = frappe.get_all("Asset Category", fields=["name"])

    # Build category table
    cat_lines = []
    for c in categories:
        line = f"- {c.prefix}: {c.full_name}"
        if c.description:
            line += f"\n  Description: {c.description}"
        if c.example_code:
            line += f"\n  Example: {c.example_code} — {c.example_item_name}"
        if c.requires_solids_suffix:
            line += f"\n  NOTE: Requires solids % suffix (e.g. -99, -80, -70)"
        if c.has_sub_category:
            line += f"\n  Sub-categories: {c.sub_category_options}"
        if c.llm_guidance_notes:
            line += f"\n  LLM guidance: {c.llm_guidance_notes}"
        cat_lines.append(line)

    asset_section = ""
    if asset_categories:
        names = "\n".join(f"- {a.name}" for a in asset_categories)
        asset_section = f"\n--- ASSET CATEGORIES (pick one if is_fixed_asset) ---\n{names}\n"

    # Top 5 candidates from Layer 1 dedup — this is what the LLM evaluates for dedup,
    # not the entire item master. Much more focused and accurate.
    if top_candidates:
        candidate_lines = []
        for c in top_candidates:
            line = f"- {c['name']}: {c['item_name']} [{c['item_group']}]"
            extras = []
            if c.get("tally_name"):         extras.append(f"tally:{c['tally_name']}")
            if c.get("tally_alias"):        extras.append(f"alias:{c['tally_alias']}")
            if c.get("legacy_material_code"): extras.append(f"legacy:{c['legacy_material_code']}")
            if c.get("gst_hsn_code"):       extras.append(f"hsn:{c['gst_hsn_code']}")
            if extras:
                line += f" ({', '.join(extras)})"
            candidate_lines.append(line)
        candidates_section = (
            "--- TOP SIMILAR ITEMS (the requester acknowledged these exist but believes "
            "their item is different — evaluate whether you agree) ---\n"
            + "\n".join(candidate_lines)
        )
    else:
        candidates_section = (
            "--- TOP SIMILAR ITEMS ---\n"
            "None found by text search. Still assess from your knowledge whether "
            "this item could already exist under a different name.\n"
        )

    prompt = f"""
ITEM REQUEST:
  Description:           {doc.requester_description}
  Is Fixed Asset:        {"Yes" if doc.is_fixed_asset else "No"}
  Is Stock Item:         {"Yes" if doc.is_stock_item else "No"}
  HSN Code:              {doc.gst_hsn_code or "Not provided"}
  Tally Name:            {doc.tally_name or "None"}
  Tally Alias:           {doc.tally_alias or "None"}
  Legacy Material Code:  {doc.legacy_material_code or "None"}

{candidates_section}

--- ACTIVE ITEM CATEGORY CODES ---
{chr(10).join(cat_lines)}

--- VALID ITEM GROUPS (leaf nodes only — you must pick exactly one, exact string match) ---
{chr(10).join(f"- {g.name}" for g in item_groups)}
{asset_section}"""
    return prompt


def get_attached_files_for_llm(item_name):
    """
    Fetches files attached to this Item that were uploaded as reference documents.
    Returns a list of dicts with filename and base64-encoded content, for
    models that support document/vision input (PDF, PNG, JPG).

    These are included as additional content blocks in the LiteLLM message payload,
    not in the text prompt string. The caller (run_item_review) assembles the
    full messages list using both the text prompt and these file blocks.
    """
    import base64

    attached_files = frappe.get_all("File",
        filters={
            "attached_to_doctype": "Item",
            "attached_to_name": item_name,
        },
        fields=["name", "file_name", "file_url", "is_private"]
    )

    file_blocks = []
    supported_types = {
        ".pdf":  "application/pdf",
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
    }

    for f in attached_files:
        ext = "." + f.file_name.rsplit(".", 1)[-1].lower() if "." in f.file_name else ""
        if ext not in supported_types:
            continue  # skip unsupported formats silently

        try:
            # Resolve physical path from Frappe file URL
            file_doc = frappe.get_doc("File", f.name)
            file_path = file_doc.get_full_path()

            with open(file_path, "rb") as fp:
                encoded = base64.b64encode(fp.read()).decode("utf-8")

            file_blocks.append({
                "filename": f.file_name,
                "media_type": supported_types[ext],
                "data": encoded,
            })
        except Exception:
            # Don't let a bad attachment break the whole review
            frappe.log_error(
                title=f"Item AI: could not read attachment {f.file_name}",
                message=frappe.get_traceback()
            )

    return file_blocks
```

### Assembling the full LiteLLM message with files

In `run_item_review`, the messages list is assembled to include both the text prompt and
any file blocks, using the Anthropic/OpenAI multi-modal content format that LiteLLM
normalises across providers:

```python
def build_messages(system_prompt, user_prompt_text, file_blocks):
    """
    Assembles the messages list for LiteLLM.
    Text prompt always comes first. File blocks follow as document/image parts.
    Falls back gracefully if the provider doesn't support vision — file blocks
    are simply omitted and the text prompt is used alone.
    """
    user_content = [{"type": "text", "text": user_prompt_text}]

    for fb in file_blocks:
        if fb["media_type"] == "application/pdf":
            user_content.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": fb["data"],
                },
            })
        else:
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{fb['media_type']};base64,{fb['data']}"
                },
            })

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_content},
    ]
```

### System prompt (stored in `Item AI Settings.system_prompt`)

```
You are an item master classification assistant for MPD Industries Pvt. Ltd.,
an Indian chemicals and coatings manufacturer.

Your task is to classify a new item request and return a JSON object.
Return ONLY valid JSON. No preamble, no markdown, no explanation outside the JSON.

The JSON must have EXACTLY these fields:

{
  "item_name": string,
  "prefix": string,
  "sub_category": string or null,
  "item_group": string,
  "asset_category": string or null,
  "solids_suffix": string or null,
  "confidence_score": float between 0.0 and 1.0,
  "review_brief": string,
  "duplicate_warning": string or null
}

RULES:

item_name:
  - Must be fully descriptive. Include grade, specification, purity where relevant.
  - "Linseed Oil" is not acceptable. "Raw Linseed Oil, Min 95% Purity, AV ≤5 mgKOH/g" is.
  - Use standard chemical names, not trade names where possible.

prefix:
  - Must be exactly one of the prefixes listed in ACTIVE ITEM CATEGORY CODES.
  - Use OTH if nothing fits. Never invent a new prefix.

sub_category:
  - Set only if the prefix has sub-categories (e.g. PKG → DRM, CAN, etc.; AST → PME, LAB, etc.)
  - Set to null for all other prefixes.

item_group:
  - Must be exactly one string from the EXISTING ITEM GROUPS list. Exact match required.
  - Never invent a new item group.

asset_category:
  - Set only if is_fixed_asset is Yes. Must be exactly one string from ASSET CATEGORIES.
  - Set to null if not a fixed asset.

solids_suffix:
  - Set only if the prefix has requires_solids_suffix = true.
  - Default to "99" for reactor base / undiluted grade.
  - Set to the target solids % if the requester has specified a thinned grade.
  - Set to null for all other prefixes.

confidence_score:
  - Your confidence in the classification. Be honest.
  - Below 0.7 means the classification is uncertain.
  - Below 0.6 should almost always use prefix OTH.

review_brief:
  - 2-3 sentences explaining why you chose this prefix and item group.
  - If duplicate_warning is set, explain why you suspect a duplicate.

duplicate_warning:
  - Set to a string like "Possible duplicate of SOL-0003: Xylene Mix, Min 98% — same chemical, similar purity spec"
  - Chemicals have many trade names. Be thorough.
  - If the requester provided a not-a-duplicate confirmation, weigh it but still flag if unconvinced.
  - Set to null if no duplicate suspected.
```

### Calling sequence in `run_item_review`

```python
@frappe.whitelist()
def enqueue_item_ai_review(item_name):
    """Whitelisted. Called by client script Generate button."""
    frappe.db.set_value("Item", item_name, "item_approval_status", "Pending AI Review")
    frappe.db.commit()
    frappe.enqueue(
        "mpd_customizations.item_ai.review.run_item_review",
        item_name=item_name,
        queue="default",
        timeout=180,
    )


def run_item_review(item_name):
    from mpd_customizations.item_ai.dedup import check_item_duplicates
    from mpd_customizations.item_ai.llm_call import call_llm_for_item
    from mpd_customizations.utils import get_task_config

    doc = frappe.get_doc("Item", item_name)
    config, params = get_task_config("item_classification")

    # Re-run dedup to get the top 5 candidates to pass to the LLM
    top_candidates = check_item_duplicates(
        description=doc.requester_description,
        tally_name=doc.tally_name,
        tally_alias=doc.tally_alias,
        legacy_material_code=doc.legacy_material_code,
    )

    # Get any attached reference files
    file_blocks = get_attached_files_for_llm(item_name)

    # Build prompt and messages
    user_prompt = build_item_review_prompt(doc, top_candidates)
    messages = build_messages(config.system_prompt, user_prompt, file_blocks)

    result = call_llm_for_item(messages)
    apply_ai_result(doc, result, config, params)
    frappe.db.commit()
```

```python
def apply_ai_result(doc, result, settings):
    """
    Write AI results to doc, freeze snapshot, decide auto vs MA approval.
    """
    import json
    from datetime import datetime

    doc.ai_item_name_suggestion      = result.get("item_name")
    doc.ai_prefix_suggestion         = result.get("prefix")
    doc.ai_sub_category_suggestion   = result.get("sub_category")
    doc.ai_item_group_suggestion     = result.get("item_group")
    doc.ai_asset_category_suggestion = result.get("asset_category")
    doc.ai_solids_suffix_suggestion  = result.get("solids_suffix")
    doc.ai_review_brief              = result.get("review_brief")
    doc.ai_confidence_score          = result.get("confidence_score", 0.0)
    doc.ai_duplicate_warning         = result.get("duplicate_warning")
    doc.ai_reviewed_on               = datetime.now()
    doc.ai_model_used                = settings.active_model

    # Freeze snapshot — never modified after this point
    snapshot = {
        "item_name":       result.get("item_name"),
        "prefix":          result.get("prefix"),
        "sub_category":    result.get("sub_category"),
        "item_group":      result.get("item_group"),
        "asset_category":  result.get("asset_category"),
        "solids_suffix":   result.get("solids_suffix"),
    }
    doc.ai_snapshot = json.dumps(snapshot)

    # Decide approval path
    threshold = settings.confidence_threshold_for_auto_approve or 0.85
    has_duplicate_flag = bool(result.get("duplicate_warning"))
    high_confidence = doc.ai_confidence_score >= threshold

    if high_confidence and not has_duplicate_flag:
        doc.item_approval_status = "AI Reviewed"
        # auto_approve will be called after save
    else:
        doc.item_approval_status = "Duplicate Flagged" if has_duplicate_flag \
            else "Pending MA Approval"
```

---

## 9. Sequential Code Assignment

File: `mpd_customizations/item_ai/code_assign.py`

```python
def assign_item_code(doc):
    """
    Computes and assigns the permanent item code.
    Uses row-level lock to prevent race conditions.
    Called on: auto-approval by background job, or MA approval.
    """
    prefix = doc.ai_prefix_suggestion
    cat = frappe.get_doc("Item Category Code", prefix)

    # Build the full prefix string
    if cat.has_sub_category and doc.ai_sub_category_suggestion:
        full_prefix = f"{prefix}-{doc.ai_sub_category_suggestion}"
    else:
        full_prefix = prefix

    # Lock to prevent concurrent code assignment for the same prefix
    frappe.db.sql("""
        SELECT name FROM `tabItem`
        WHERE name LIKE %(pattern)s
        ORDER BY name DESC LIMIT 1 FOR UPDATE
    """, {"pattern": f"{full_prefix}-%"}, as_dict=True)

    # Find the next number in sequence
    like_pattern = f"{full_prefix}-%"
    existing = frappe.db.sql("""
        SELECT name FROM `tabItem`
        WHERE name LIKE %(pattern)s
        AND disabled = 0
    """, {"pattern": like_pattern}, as_dict=True)

    numbers = []
    for e in existing:
        parts = e.name.split("-")
        # For resin suffixes like ALK-0001-99, the number is parts[-2]
        # For normal like SOL-0001, the number is parts[-1]
        try:
            if cat.requires_solids_suffix:
                numbers.append(int(parts[-2]))
            elif cat.has_sub_category:
                numbers.append(int(parts[-1]))
            else:
                numbers.append(int(parts[-1]))
        except (ValueError, IndexError):
            pass

    next_num = (max(numbers) + 1) if numbers else 1
    seq = f"{next_num:04d}"

    # Build final code
    if cat.requires_solids_suffix:
        suffix = doc.ai_solids_suffix_suggestion or "99"
        final_code = f"{full_prefix}-{seq}-{suffix}"
    else:
        final_code = f"{full_prefix}-{seq}"

    return final_code


def finalise_item(doc, final_code):
    """
    Renames item from temp name to final code and marks as Approved.
    """
    from datetime import datetime

    old_name = doc.name

    # Rename the document — Frappe updates all linked records automatically
    if old_name != final_code:
        frappe.rename_doc("Item", old_name, final_code, merge=False)
        doc = frappe.get_doc("Item", final_code)

    doc.item_approval_status = "Approved"
    doc.approved_on = datetime.now()
    doc.approved_by = frappe.session.user

    # Update item_name to the AI suggestion (or MA override if applicable)
    doc.item_name = doc.ai_item_name_suggestion
    doc.item_group = doc.ai_item_group_suggestion

    if doc.ai_asset_category_suggestion:
        doc.asset_category = doc.ai_asset_category_suggestion

    doc.save(ignore_permissions=True)
    frappe.db.commit()
```

---

## 10. Validate Hook on Item

File: `mpd_customizations/item_ai/item_hooks.py`

```python
import json
import frappe

SNAPSHOT_FIELDS = [
    ("ai_item_name_suggestion",      "item_name"),
    ("ai_prefix_suggestion",         "prefix"),
    ("ai_sub_category_suggestion",   "sub_category"),
    ("ai_item_group_suggestion",     "item_group"),
    ("ai_asset_category_suggestion", "asset_category"),
    ("ai_solids_suffix_suggestion",  "solids_suffix"),
]

def validate_item(doc, method):
    if not doc.ai_snapshot:
        return
    if doc.item_approval_status not in ("AI Reviewed",):
        return

    snapshot = json.loads(doc.ai_snapshot)

    for doc_field, snap_key in SNAPSHOT_FIELDS:
        current_val = doc.get(doc_field) or None
        snap_val = snapshot.get(snap_key) or None
        if current_val != snap_val:
            doc.item_approval_status = "Pending MA Approval"
            return  # one mismatch is enough
```

Register in `hooks.py`:

```python
doc_events = {
    "Item": {
        "validate": "mpd_customizations.item_ai.item_hooks.validate_item"
    },
    # ... existing doc_events
}
```

---

## 11. Transaction Gates

File: `mpd_customizations/item_ai/gates.py`

```python
import frappe

BLOCKED_STATUSES = (
    "Draft",
    "Pending Dedup Check",
    "Dedup Confirmed",
    "Pending AI Review",
    "AI Reviewed",
    "Duplicate Flagged",
    "Pending MA Approval",
)

def block_unapproved_items(doc, method):
    if "System Manager" in frappe.get_roles():
        return

    blocked = []
    for row in doc.items:
        status = frappe.db.get_value("Item", row.item_code, "item_approval_status")
        if status in BLOCKED_STATUSES:
            blocked.append(f"{row.item_code} — {row.item_name} (status: {status})")

    if blocked:
        item_list = "<br>".join(blocked)
        frappe.throw(
            f"The following items are not yet approved for committed transactions:"
            f"<br><br>{item_list}<br><br>"
            f"These items require Master Approver sign-off before they can be used "
            f"in Purchase Orders, Sales Quotations, or Sales Orders. "
            f"They may be used in RFQs and Supplier Quotations."
        )
```

Register in `hooks.py`:

```python
doc_events = {
    # ... existing
    "Purchase Order":    {"validate": "mpd_customizations.item_ai.gates.block_unapproved_items"},
    "Sales Quotation":   {"validate": "mpd_customizations.item_ai.gates.block_unapproved_items"},
    "Sales Order":       {"validate": "mpd_customizations.item_ai.gates.block_unapproved_items"},
    "Purchase Invoice":  {"validate": "mpd_customizations.item_ai.gates.block_unapproved_items"},
}
```

---

## 12. LiteLLM Call Wrapper

File: `mpd_customizations/item_ai/llm_call.py`

Uses the existing `LLM Provider` DocType and `LLM Review Log`. Provider and model come
from `AI Task Config` — one `get_task_config` call anywhere in the codebase gets the
right model for any task.

`call_llm_for_item` accepts a fully-assembled `messages` list (built by `build_messages`
in `review.py`) so it never needs to know about file attachments or prompt structure.

```python
import frappe
import litellm
import json

def call_llm_for_item(messages):
    """
    Makes a LiteLLM call for item classification.
    messages: fully assembled list from build_messages() in review.py —
              includes text prompt and any base64 file blocks.
    Provider, model, and settings come from AI Task Config "item_classification".
    Logs to LLM Review Log. Returns parsed dict.
    """
    from mpd_customizations.utils import get_task_config
    config, params = get_task_config("item_classification")

    provider_doc = frappe.get_doc("LLM Provider", config.llm_provider)

    response = litellm.completion(
        model=config.model,
        api_base=provider_doc.api_base,
        api_key=provider_doc.get_password("api_key_secret"),
        messages=messages,
        response_format={"type": "json_object"},
        temperature=config.temperature or 0.1,
        max_tokens=config.max_tokens or 2000,
    )

    raw_response = response.choices[0].message.content
    result = json.loads(raw_response)

    log = frappe.get_doc({
        "doctype":           "LLM Review Log",
        "task_type":         "Item Classification",
        "task_key":          "item_classification",
        "model_used":        config.model,
        "provider":          config.llm_provider,
        "prompt_tokens":     response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
        "raw_response":      raw_response,
    })
    log.insert(ignore_permissions=True)
    frappe.db.commit()

    return result
```

**To switch provider or model:** open `AI Task Config`, find `item_classification`,
change `llm_provider` and/or `model`. Takes effect on the next review job. No restart,
no code change, no migration.

**Note on file support:** Not all providers support PDF document input. Claude (Anthropic)
and GPT-4o (OpenAI) both support it. If a provider does not support multi-modal content,
LiteLLM will raise an error for the file blocks. The fallback is to use a model that
does support it, or to strip file blocks and retry text-only. The `fallback_task` field
on `AI Task Config` can point to a text-only config for this purpose.

---

## 13. Client Script

File: `mpd_customizations/public/js/item_ai.js`

This must be registered in `hooks.py` under `app_include_js` or as a DocType client
script fixture. Register as a Client Script fixture targeting the `Item` DocType.

Key behaviours to implement:

1. **Show/hide "Check for Similar Items" button**
   - Show when `item_approval_status` is `Draft` or empty
   - Hide after `dedup_check_done = 1`

2. **"Check for Similar Items" click handler**
   - Calls `mpd_customizations.item_ai.dedup.check_item_duplicates` with description,
     tally_name, tally_alias, legacy_material_code
   - If results: render an inline table (not a modal) below the check button showing
     item code, item name, item group, tally name. Each row has an **[ Open ]** link.
   - Below the table: one button labelled exactly:
     **"I acknowledge that these items are different from the existing ones"**
   - On click: calls `confirm_dedup`, sets `dedup_check_done`, shows generate button
   - If no results: calls `confirm_dedup` automatically, shows green banner + generate button

3. **File upload UI**
   - `item_reference_files` renders as a standard Frappe file attachment field
   - Show helper text: "Attach an invoice, datasheet, MSDS, or photo to help the AI
     classify this item. Supported: PDF, PNG, JPG."
   - Files upload immediately via standard Frappe attachment — no extra handling needed
   - The background job fetches them server-side via `get_attached_files_for_llm`

3. **Show/hide "Generate AI Suggestion" button**
   - Only visible when `dedup_check_done = 1`
   - Hides and shows spinner when clicked
   - Calls `mpd_customizations.item_ai.review.enqueue_item_ai_review`

4. **`requester_description`, `tally_name`, `tally_alias`, `legacy_material_code` onchange**
   - If `dedup_check_done == 1` on the server: call `reset_dedup` whitelisted method, hide
     generate button, show check button again
   - Show inline warning: "You changed the item details — please re-check for duplicates"

5. **Status banner**
   - `Draft` → blue: "Fill in the description and check for similar items"
   - `Pending AI Review` → blue: "AI review in progress. Refresh in a moment."
   - `AI Reviewed` + `Approved` → green: "Item approved. Code: {item_code}"
   - `Duplicate Flagged` → red: "AI flagged a possible duplicate. Sent to Master Approver."
   - `Pending MA Approval` → amber: "Awaiting Master Approver review."
   - `Rejected` → red: "Item rejected. See MA note."

6. **Master Approver section**
   - Only render if `frappe.user_roles.includes('Master Approver')`
   - Show Approve and Reject buttons when status is `Pending MA Approval` or `Duplicate Flagged`
   - Approve calls `mpd_customizations.item_ai.review.approve_item`
   - Reject calls `mpd_customizations.item_ai.review.reject_item` (requires `ma_review_note`)

7. **AI fields read-only enforcement**
   - For non-MA users: set all `ai_*` fields to `read_only = 1` via `frm.set_df_property`
   - This is belt-and-suspenders — permlevel handles server-side, client script handles UI

---

## 14. File Structure

```
mpd_customizations/
├── item_ai/
│   ├── __init__.py
│   ├── dedup.py           # Layer 1 duplicate check (synchronous, whitelisted)
│   ├── review.py          # Background job, prompt builder, apply_ai_result, approve/reject
│   ├── llm_call.py        # LiteLLM wrapper using AI Task Config
│   ├── code_assign.py     # Sequential code assignment with row lock
│   ├── item_hooks.py      # validate hook — snapshot comparison
│   └── gates.py           # Transaction gate hooks
├── public/
│   └── js/
│       └── item_ai.js     # Client script
├── fixtures/
│   ├── item_category_code.json    # All prefix seed records
│   ├── custom_fields.json         # All Item custom fields
│   ├── ai_task_config.json        # item_classification and coa_review seed records
│   ├── ai_task_config_parameter.json  # Seed parameters for each task
│   └── client_scripts.json        # Item DocType client script
└── hooks.py               # doc_events registrations + fixture list
```

---

## 15. hooks.py Additions

Add these to the existing `hooks.py`:

```python
doc_events = {
    # Existing entries preserved — add these:
    "Item": {
        "validate": "mpd_customizations.item_ai.item_hooks.validate_item"
    },
    "Purchase Order":   {"validate": "mpd_customizations.item_ai.gates.block_unapproved_items"},
    "Sales Quotation":  {"validate": "mpd_customizations.item_ai.gates.block_unapproved_items"},
    "Sales Order":      {"validate": "mpd_customizations.item_ai.gates.block_unapproved_items"},
    "Purchase Invoice": {"validate": "mpd_customizations.item_ai.gates.block_unapproved_items"},
}

fixtures = [
    # Existing fixtures preserved — add these:
    {"dt": "Custom Field",            "filters": [["dt", "=", "Item"]]},
    {"dt": "Item Category Code"},
    {"dt": "AI Task Config"},
    {"dt": "AI Task Config Parameter"},
    {"dt": "Client Script",           "filters": [["dt", "=", "Item"]]},
]
```

---

## 16. Implementation Order

Build in this exact order to avoid dependency issues:

1. `Item Category Code` DocType + all seed fixture records
2. `AI Task Config` DocType + `AI Task Config Parameter` child table + seed records
   for `item_classification` and `coa_review` (migrate existing CoA prompt here)
3. Add `get_task_config()` helper to `mpd_customizations/utils.py`
4. All custom fields on `Item` (via Custom Field — use fixtures)
5. `item_ai/llm_call.py` — LiteLLM wrapper using `get_task_config("item_classification")`
6. `item_ai/dedup.py` — Layer 1 duplicate check (scored 4-pass search, top 5 returned,
   button-only acknowledgement, reset_dedup whitelisted method)
7. `item_ai/review.py` — background job; prompt builder (`is_group=0` item groups, top 5
   candidates section, HSN + tally + legacy in prompt); `get_attached_files_for_llm`;
   `build_messages` (text + file blocks); `apply_ai_result`; approve/reject handlers
8. `item_ai/code_assign.py` — sequential code assignment with row lock
9. `item_ai/item_hooks.py` — validate hook (snapshot comparison)
10. `item_ai/gates.py` — transaction gates
11. `hooks.py` — register all doc_events and fixtures
12. `public/js/item_ai.js` — client script (4-field onchange reset, button-only dedup confirm)
13. Run `bench --site production.localhost migrate`
14. Verify fixtures: `bench --site production.localhost console` → `sync_fixtures()`

---

## 17. Key Constraints & Gotchas

- **Never hardcode model names or provider URLs** — always call `get_task_config("item_classification")`
- **Item groups must be leaf nodes only** — always filter `is_group = 0` when fetching
  item groups for the LLM prompt. If the LLM picks a parent/group node, ERPNext throws a
  validation error on save. This filter is the only safeguard.
- **File attachments in `run_item_review` use the server filesystem path** — use
  `frappe.get_doc("File", name).get_full_path()`, not `file_url` (which requires auth).
  `get_full_path()` returns the absolute disk path the background worker can read directly.
- **Not all providers support PDF/image input** — if `file_blocks` is non-empty and the
  provider doesn't support multi-modal content, LiteLLM will raise. Catch this, retry
  with `build_messages(system_prompt, user_prompt, [])` (text only), and log the fallback
  via `frappe.log_error`.
- **`dedup_check_done` resets on any of four fields changing** — `requester_description`,
  `tally_name`, `tally_alias`, `legacy_material_code`. All four onchange handlers in the
  client script must call `reset_dedup` (a whitelisted server method) before saving.
- **The `ai_snapshot` field must never be written to after the background job writes it** —
  the validate hook must not touch it, the MA approval must not touch it
- **`frappe.rename_doc` is the correct way to set the final item code** — do not try to
  set `name` directly on the doc
- **The row lock (`FOR UPDATE`) in `code_assign.py` only works if called inside a
  transaction** — `frappe.db.begin()` is implicit in most Frappe operations but verify
- **Background jobs run as the system user unless `as_ai_user()` context manager is used** —
  use it for the LLM call portion so audit logs record the AI user correctly
- **`dedup_check_done` is permlevel 2 (server-set only)** — the client script reads it via
  `frm.doc.dedup_check_done` which Frappe populates from the server response; the client
  cannot set it directly, only the server `confirm_dedup` method sets it
- **All whitelisted methods must have `@frappe.whitelist()` decorator**
- **Do not use `frappe.session.user` inside background jobs** — the user is the queue
  worker, not the requester; store the requester's name on the item before enqueuing if needed
- **Test the auto-approval path first** — it is the common case; MA approval is the
  exception