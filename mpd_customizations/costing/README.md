# Costing Module

Custom Frappe module for MPD Dye Chem that calculates ex-factory cost per kg for paint/resin products. It takes a sales enquiry (Pricing Request), fetches live material rates and processing charges, evaluates all available BOM formulations, and produces a costed quote that a Costing Approver can approve or reject.

---

## Table of Contents

1. [User-Facing Flow](#1-user-facing-flow)
2. [Doctypes Reference](#2-doctypes-reference)
3. [Material Rates](#3-material-rates)
4. [Processing Charges](#4-processing-charges)
5. [Costing Engine — How a Calculation Works](#5-costing-engine--how-a-calculation-works)
6. [Formulation Comparison and Selection](#6-formulation-comparison-and-selection)
7. [Cost Formula](#7-cost-formula)
8. [Reactivity — Auto-Evaluation and Recompute](#8-reactivity--auto-evaluation-and-recompute)
9. [Approval Workflow](#9-approval-workflow)
10. [Roles and Permissions](#10-roles-and-permissions)
11. [Configuration Reference](#11-configuration-reference)
12. [Services Layer Architecture](#12-services-layer-architecture)
13. [Directory Structure](#13-directory-structure)

---

## 1. User-Facing Flow

```
Sales team                  Costing team                 Approver
─────────────────────────────────────────────────────────────────
Pricing Request
  (product + city +
   solids% + qty)
        │
        │  on_after_insert
        ▼
  Pricing Calculation ◄──── auto-created and linked
        │
        │  evaluate() fires immediately (background)
        ▼
  Rate lines populated
  Formulations compared
  Mode set to:
    "Awaiting Rates"      ← one or more RM rates missing
    "Ready for Working"   ← all rates present (some expired OK)
    "Ready to Quote"      ← all rates current, formulation selected
        │
        │  Costing team reviews, optionally overrides rates,
        │  selects a formulation, adjusts additional charges
        ▼
  "Ready to Quote"
        │
        │                                Approve / Reject
        ▼                                       │
  "Approved" (PC submitted,              ───────┘
   PR status → Approved)
```

Everything after "Pricing Calculation created" is automatic or driven by the costing team. The sales team only sees the Pricing Request.

---

## 2. Doctypes Reference

### Pricing Request (`PR-YYYY-#####`)

Created by the sales team for each enquiry. Fields of note:

| Field | Purpose |
|---|---|
| `product` | Link to ERPNext Item (must have at least one BOM) |
| `city` | Delivery city — drives which Material Rates are used |
| `solids_content_pct` | Product solids % (affects processing cost calculation) |
| `quantity_kg` | Order quantity — used to compute `total_price` |
| `priority` | Urgent / High / Normal / Low — surfaced to costing team |
| `pricing_calculation` | Auto-linked to the created PC (read-only) |
| `previous_pricing_ref` | The previous approved Pricing Calculation for the same product+city, used to pre-fill the new PC |
| `status` | Mirrors the PC's `mode` (auto-synced) |
| `confirmed_price_per_kg` | Mirrors the PC's confirmed cost (auto-synced) |

**On after_insert:** creates a Pricing Calculation, fires an initial evaluation, then pushes a realtime reload to the PR form.

**On before_submit:** requires `status = "Ready to Quote"`. Sets status to "Pending Approval".

---

### Pricing Calculation (`PC-YYYY-#####`)

The main working document for the costing team. Auto-created when a Pricing Request is saved. Submittable — once approved it is locked.

**Header fields:**

| Field | Purpose |
|---|---|
| `item` / `city` / `solids_content_pct` | Copied from the PR |
| `processor` | The contract manufacturer performing production |
| `production_days` | Days from RM purchase to delivery (affects financing cost). Pre-filled from config or previous PC. |
| `supplier_financing_rate_pct` | Annual rate charged to the customer for RM financing. Pre-filled from config or previous PC. |
| `preferred_bom` | BOM to favour when selecting formulation. Pre-filled from the previous approved PC. |
| `mode` | Current stage — see Mode Lifecycle below |
| `selected_combination` | Link to the chosen Costing Combination |
| `confirmed_ex_factory_cost_per_kg` | Locked cost from the selected combination |
| `valid_until` | Quote expiry (defaults to today + 7 days) |
| `last_evaluated_on` / `engine_version_used` | Audit fields |

**Child tables:**

| Table | Purpose |
|---|---|
| `rate_lines` (Costing Rate Line) | One row per raw material — fetched rate, working rate, override, supplier, market intelligence |
| `scrap_lines` (Costing Scrap Line) | Byproducts / scrap — rates entered manually, reduce RM cost |
| `processing_lines` (Costing Processing Line) | One row for the processor's charge per kg and outward freight |
| `additional_charges` (Costing Additional Charge) | Pass-through charges (e.g. insurance, inspection) — per-kg or per-kg-of-solids |

**Mode lifecycle:**

```
Draft → Awaiting Rates → Ready for Working → Ready to Quote → Approved
                                                            └→ Rejected
```

- **Draft** — just created, evaluation not yet run
- **Awaiting Rates** — one or more RM rates are missing (no submitted Material Rate exists)
- **Ready for Working** — all BOMs have rate data but some are expired; can still calculate indicative costs
- **Ready to Quote** — all rates current, a formulation is selected, confirmed cost is set
- **Approved** — submitted, locked, synced to PR

---

### Costing Combination (`CC-YYYY-#####`)

One record per BOM evaluated for a Pricing Calculation. Deleted and recreated on every full `evaluate()` call.

| Field | Purpose |
|---|---|
| `bom` | The ERPNext BOM this represents |
| `formulation_id` | `custom_formulation_id` from the BOM |
| `formulation_description` | `custom_formulation_description` from the BOM |
| `prev_rm_cost_per_kg` | RM cost from the previous approved PC for the same BOM (for delta comparison) |
| `rm_cost_per_kg` | Raw material cost (after scrap credits) |
| `financing_cost_per_kg` | Supplier financing cost |
| `processing_cost_per_kg` | Processing charge allocated to this formulation |
| `additional_charges_per_kg` | Sum of all additional charges |
| `outward_freight_per_kg` | Outward freight (if not bundled in processing charge) |
| `total_cost_per_kg` | Sum of all the above |
| `rank` | 1 = cheapest included formulation; 0 = excluded |
| `delta_pct` | % more expensive than the cheapest included formulation |
| `status` | Ready to Quote / Indicative — Rates Expired / Indicative — Rates Missing / Excluded — Too Expensive |
| `is_preferred` | True if this BOM matches `preferred_bom` on the PC |
| `is_selected` | True if this is the chosen formulation |

**Costing Material Line** — child of Costing Combination (stored separately, not as a child table field). One row per BOM ingredient. Holds working rate, supplier, credit days, financing cost per kg.

---

### Material Rate (`MR-YYYY-#####`)

Submitted by the purchase/rate team. One record = one supplier's price for one item in one city for a date range.

| Field | Purpose |
|---|---|
| `item` / `city` / `supplier` | Identifies the rate |
| `valid_from` / `valid_to` | Validity period. `valid_to` can be blank = open-ended |
| `delivered_rate` | All-in delivered rate per kg |
| `rate_60d_equivalent` | Rate normalised to a 60-day credit baseline (computed on save) |
| `credit_days` | Payment terms in days |
| `rate_type` | All-In Delivered / Ex-Works / etc. |

**On submit:** auto-expires any overlapping rate from the same supplier for the same item+city (sets their `valid_to` to one day before the new `valid_from`). Then triggers re-evaluation of all open Pricing Calculations that were waiting on this item.

**Rate freshness terminology:**
- **Current** — within `valid_from`–`valid_to` as of today
- **Expired** — `valid_to` is in the past; can still be used for indicative pricing
- **Missing** — no submitted Material Rate exists at all for this item+city

---

### Processing Charge

Defines what a Processor charges to manufacture a product. Matched by item (exact) or item group (hierarchical — most specific ancestor wins).

| Field | Purpose |
|---|---|
| `processor` | The Processor this applies to |
| `item` / `item_group` | Scope — item-specific match beats group-based |
| `charge_per_kg` | Manufacturing charge per kg of output |
| `fg_freight_per_unit` | Finished goods outward freight per unit |
| `includes_outward_freight` | If checked, `fg_freight_per_unit` is already in `charge_per_kg` |
| `valid_from` / `valid_to` | Validity period |

---

### Processor

Master record for a contract manufacturer. Has a `city` field. The engine validates that the processor's city matches the PC's city.

---

### Costing Configuration (Single DocType)

Global parameters for the engine. See [Configuration Reference](#11-configuration-reference).

---

## 3. Material Rates

The purchase team submits a Material Rate for each item+city+supplier combination whenever a new quote is received.

**Auto-expiry on submit:** when a new rate is submitted for the same item+supplier+city, any existing submitted rate whose validity overlaps is automatically truncated — its `valid_to` is set to one day before the new rate's `valid_from`. This ensures no two rates from the same supplier are ever active at the same time.

**Rate normalisation to 60-day baseline (`rate_60d_equivalent`):** because different suppliers offer different credit terms, rates are normalised to a common 60-day credit baseline before comparison:

```
gap = 60 - actual_credit_days

if gap > 0 (supplier gives < 60d credit):
    rate_60d = rate * (1 + gap/365 * financing_rate%)

if gap < 0 (supplier gives > 60d credit):
    rate_60d = rate * (1 + gap/365 * benefit_rate%)
```

This makes rates from a 30-day supplier and a 90-day supplier directly comparable.

**Freshness and market intelligence:** the `ManualRateSource` service, when resolving rates for a calculation, also computes:
- `prev_rate` — the most recent expired rate (previous month's benchmark)
- `market_rate_count` — how many current quotes exist
- `market_rate_avg` — average of all current quotes
- `rate_valid_to` — expiry date of the chosen rate

These are stored on the `Costing Rate Line` and displayed in the rate grid. Rows with rates expiring within 30 days are highlighted amber.

---

## 4. Processing Charges

Processing charges represent what a contract manufacturer (Processor) charges to produce the finished product.

**Lookup hierarchy (most specific wins):**
1. Active charges for the processor where `item` exactly matches the PC's item
2. Active charges for the processor where `item_group` is an ancestor-or-self of the item's group (deepest ancestor = most specific)

If neither matches, the processing charge is blank. The costing team can still proceed with a zero or manually-overridden processing cost.

**Auto-fetch on processor change:** when the costing team sets the `processor` field on the PC form, the form auto-saves and immediately calls `fetch_processing_charge`. The fetched values populate `fetched_charge_per_kg` and `working_charge_per_kg`. If `working_charge_per_kg` is later overridden manually, the override is preserved through subsequent rate evaluations.

---

## 5. Costing Engine — How a Calculation Works

`CostingEngine.evaluate(pc_name, trigger)` is the top-level entry point. It does two things: fetch rates, then compute combinations.

### Step 1 — Rate fetch (`RateFetcher.fetch`)

1. Load all BOMs for the product item.
2. Collect all unique RM items across all BOMs (excluding scrap items).
3. Batch-resolve rates for every `(item, city)` pair via `ManualRateSource`.
4. **Update `rate_lines`** on the PC doc:
   - Existing rows are updated in-place (preserving manual overrides if `preserve_overrides=True`).
   - Rows for items no longer in any BOM are dropped.
   - New items are appended.
5. **Update `scrap_lines`**: sync items from BOM scrap, preserve manually-entered rates.
6. **Update `processing_lines`**: fetch current processing charge for the selected processor.

### Step 2 — Combination computation

For each BOM:

1. Look up each ingredient's `working_rate` from `rate_lines`.
2. Compute `qty_per_kg_output = bom_item.qty / bom.quantity`.
3. `rm_line_amount = qty_per_kg_output × working_rate`
4. `financing_cost = amount × (max(0, production_days - credit_days) / 365) × financing_rate%`
5. Sum all ingredient amounts → `rm_cost_per_kg` (scrap items count negative).
6. Look up processing charge → `processing_cost_per_kg = solids% × charge_per_kg`.
7. Compute `additional_charges_per_kg` from the `additional_charges` child table.
8. `outward_freight_per_kg` from processing line if freight is not bundled.
9. `total_cost_per_kg = rm + financing + processing + additional + freight`

### Step 3 — Formulation selection (`FormulationSelector.select`)

All combinations are ranked:

1. `delta_pct = (cost - min_cost) / min_cost × 100`
2. Combinations where `delta_pct > auto_exclusion_threshold_pct` (default 15%) are marked **Excluded — Too Expensive** and given `rank = 0`.
3. Remaining combinations are sorted by cost and assigned `rank = 1, 2, 3...`
4. If `preferred_bom` is set and is not rank 1, and the cost difference exceeds `formulation_switch_threshold_pct` (default 5%), a **switch alert** is generated.

### Step 4 — Save and sync

- All Costing Combination and Costing Material Line records are deleted and re-inserted.
- PC fields updated: `mode`, `last_evaluated_on`, `engine_version_used`, `formulation_switch_alert`.
- If the previously selected BOM still exists, `selected_combination` is re-linked and `confirmed_ex_factory_cost_per_kg` updated.
- PC mode is synced to the Pricing Request's `status`.
- Draft Material Rate records (rate requests for missing/expired items) are created or cleared.

---

## 6. Formulation Comparison and Selection

The **Formulation Comparison** panel on the PC form shows a table of all evaluated formulations:

| Column | Notes |
|---|---|
| Formulation | ID from `custom_formulation_id` on BOM |
| Description | From `custom_formulation_description` on BOM |
| RM Cost/kg | Raw material cost for this BOM |
| Prev RM/kg | RM cost from the previous approved PC for this BOM, with a delta % indicator |
| Total/kg | Full ex-factory cost |
| Status | Ready / Rates Expired / Rates Missing / Too Expensive |

**Row highlights:**
- **Strong green** — cheapest (rank 1) AND previously used (`is_preferred`) — best of both
- **Light green** — cheapest only
- **Amber** — previously used but not currently cheapest
- **Blue** — currently selected

Clicking **Select** calls `select_combination`, which:
1. Marks all other combinations as `is_selected = 0`.
2. Sets `confirmed_ex_factory_cost_per_kg` on the PC.
3. Sets mode to `Ready to Quote` if rates are current.
4. Syncs confirmed price and total price back to the Pricing Request.

**Common costs** (same for all formulations — financing, processing, additional charges, freight) are shown in a footer bar below the table.

When the PC is submitted (approved), the panel becomes a locked snapshot showing the full cost breakdown and override audit table.

---

## 7. Cost Formula

```
Total Ex-Factory Cost/kg =
    Σ (qty_per_kg × working_rate)          ← RM cost (scrap negative)
  + Σ (rm_amount × financed_days/365 × r%) ← supplier financing
  + (solids% × processing_charge/kg)        ← processing
  + Σ additional_charges                    ← pass-through charges
  + outward_freight                         ← if not in processing
```

**Financed days** = `max(0, production_days - supplier_credit_days)`

The 60-day normalisation means all RM rates are already on a common credit baseline before entering this formula. The financing line captures the incremental cost of days *beyond* the 60-day baseline.

**Processing cost** is scaled by solids content because the processor charges per kg of finished product, but the product is partly solvent (water or carrier). 99% solids is treated as 100% by convention.

**Additional charges** can be:
- `Per kg of Output` — fixed ₹/kg regardless of formulation
- `Per kg of Solids` — scaled by `solids_content_pct / 100`

---

## 8. Reactivity — Auto-Evaluation and Recompute

The PC form behaves like a spreadsheet — changes auto-propagate without any manual "Calculate" button.

### On form open (once per session)

`_do_evaluate` fires automatically the first time a draft PC is opened. It calls the full `evaluate` API (rate fetch + combination recompute), then reloads the form. A `Set` called `_auto_evaluated` prevents a second evaluation from firing on the reload-triggered refresh.

### On parameter change (debounced)

Changing any of the following schedules a lightweight `recompute_combinations` call (600ms debounce, saves first if dirty):

- `production_days`
- `supplier_financing_rate_pct`
- `solids_content_pct`
- `preferred_bom`
- Any `additional_charges` row (rate or basis)
- Removing an additional charge row

`recompute_combinations` does not re-fetch rates — it uses the existing `rate_lines` working rates and re-runs the cost math across all combinations.

### On rate line override

Editing `working_rate` or `working_supplier_credit_days` in the rate grid immediately calls `apply_rate_override`, which saves the override to the PC and recomputes combinations. The override is preserved through subsequent evaluations (unless explicitly reverted).

### On Material Rate submitted (webhook)

When any Material Rate is submitted, `on_material_rate_submitted` fires. It finds all open PCs (`Awaiting Rates` or `Ready for Working`) that have a rate line for the submitted item, triggers a full `evaluate` on each, and pushes a realtime reload notification to the PC owner's browser.

---

## 9. Approval Workflow

### Costing team's job

1. Review the auto-populated rate lines — check freshness indicators and market benchmarks.
2. Override rates if needed (e.g. locked-in contract price differs from spot).
3. Select the appropriate formulation.
4. Set additional charges if applicable.
5. Ensure mode reaches `Ready to Quote`.

### Approver's job

When mode is `Ready to Quote`, a Costing Approver sees **Approve** and **Reject** buttons.

**Approve:**
- Calls `approve_pricing_calculation`.
- Sets `pc.mode = "Approved"` then calls `pc.submit()` (docstatus → 1).
- Sets PR status to "Approved".
- PC is now locked — no further edits possible.

**Reject:**
- Sets PC mode to `Rejected` and PR status to `Rejected`.
- PC remains a draft (not submitted).

### Pricing Request submission

The PR itself is submittable. Before submit, status must be `Ready to Quote` (the costing team's confirmation that the rate is ready to go to the customer). On submit, status becomes `Pending Approval`. The PR is locked once the Approver approves via the PC.

---

## 10. Roles and Permissions

| Role | What they can do |
|---|---|
| **Costing User** | Create/edit Pricing Calculations and Material Rates. Cannot submit/approve. |
| **Costing Approver** | Read Pricing Calculations. Can approve or reject (calls the approve/reject APIs). Can submit Material Rates. |
| **Rate Manager** | Read-only on Material Rates and Pricing Calculations. Intended for purchase team members who enter rates but don't need the full costing view. |
| **System Manager** | Full access including cancel/delete. |

The Pricing Request is intentionally not restricted to costing roles — the sales team creates it.

---

## 11. Configuration Reference

All parameters live in the **Costing Configuration** single doctype.

| Parameter | Default | Effect |
|---|---|---|
| `engine_version` | `"1.0.0"` | Stamped on each PC for audit |
| `production_days` | `30` | Default days from RM purchase to delivery. Drives financing cost. |
| `supplier_financing_rate_pct` | `12.0%` | Annual rate charged to customer for RM financing |
| `actual_cost_of_capital_pct` | `9.0%` | MPD's actual borrowing cost (used for internal spread analysis) |
| `credit_benefit_rate_pct` | `8.0%` | Rate used to discount rates when supplier gives >60d credit |
| `auto_exclusion_threshold_pct` | `15.0%` | Formulations more than this % above cheapest are marked "Excluded — Too Expensive" |
| `formulation_switch_threshold_pct` | `5.0%` | If preferred BOM costs more than this % above cheapest, a switch alert is shown |
| `default_valid_to` / `default_valid_to_days` | `"End of Month"` / `30` | Default validity for new Material Rates |
| `rate_expiry_warning_days` | `30` | Rate lines expiring within this window are highlighted amber in the grid |

---

## 12. Services Layer Architecture

The business logic lives entirely in `services/`, keeping it testable and independent of the HTTP layer.

```
services/
├── config.py                   CostingConfig dataclass + get_config() (request-scoped cache)
├── rate_option.py              RateOption dataclass — data transfer object from source → fetcher
├── rate_source_registry.py     Registry of rate sources; batch_resolve dispatches to sources
├── sources/
│   ├── base.py                 BaseRateSource ABC
│   └── manual_rate_source.py   Reads submitted Material Rate records; computes market intelligence
├── rate_fetcher.py             Orchestrates rate fetch across all BOM items; updates PC doc in-place
├── cost_calculator.py          Pure functions: rm_line, financing, processing, additional, total
├── formulation_selector.py     Ranks combinations, excludes too-expensive ones, generates switch alert
└── costing_engine.py           Top-level evaluate() — orchestrates fetch + compute + save
```

**Data flow:**

```
CostingEngine.evaluate()
    └── RateFetcher.fetch(doc)
            └── RateSourceRegistry.batch_resolve(pairs, dt)
                    └── ManualRateSource.batch_resolve()
                            → returns {(item, city): [RateOption, ...]}
        Updates doc.rate_lines, doc.scrap_lines, doc.processing_lines in-place
        doc.save()
    └── For each BOM:
            cost_calculator functions → combination cost data
    └── FormulationSelector.select(combinations)
            → ranks, excludes, generates switch alert
    └── frappe.db operations: delete old CC/CML, insert new ones, update PC fields
```

**`api/costing.py`** is a thin HTTP layer — it receives `@frappe.whitelist()` calls from the browser, calls the service layer, and returns JSON. The heavy logic is not in the API layer.

---

## 13. Directory Structure

```
costing/
├── api/
│   └── costing.py              All @frappe.whitelist() endpoints
├── doctype/
│   ├── city/                   Simple master — city names for rate scoping
│   ├── costing_additional_charge/   Child table — pass-through charges on a PC
│   ├── costing_combination/    Result of evaluating one BOM against a PC
│   ├── costing_configuration/  Global parameters (Single DocType)
│   ├── costing_material_line/  Per-ingredient cost line inside a Costing Combination
│   ├── costing_processing_line/ Processing charge line on a PC
│   ├── costing_rate_line/      RM rate line on a PC (with override support)
│   ├── costing_scrap_line/     Scrap/byproduct rate line on a PC
│   ├── material_rate/          Supplier price records submitted by purchase team
│   ├── pricing_calculation/    Main costing workbench (PC)
│   ├── pricing_request/        Sales team enquiry that triggers a PC
│   ├── processing_charge/      Processor's manufacturing fee schedule
│   └── processor/              Contract manufacturer master
├── report/
│   └── item_rate_history/      Script report — rate history for an item across suppliers
└── services/                   Pure business logic (see §12)
```
