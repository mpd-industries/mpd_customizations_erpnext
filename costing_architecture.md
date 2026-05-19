# MPD Costing Engine — Product Requirements Document & System Architecture
## Phase 1: Ex-Factory Cost Module

---

## Developer Preamble

Before writing a single line of code, read this document in full. Then read the official Frappe v16 documentation. Then implement.

**You must follow Frappe v16 best practices throughout. Do not use any deprecated features. Do not use Server Scripts stored in the database — all logic lives in Python files in the app. Do not use `frappe.db.sql` where the ORM suffices. Do not call `frappe.get_doc` inside loops — use bulk queries. Do not use jQuery where Frappe's form API handles it. Do not hardcode strings that belong in configuration. Every piece of business logic lives in the services layer — never in controllers, never in API endpoints, never in JavaScript. Controllers validate and delegate. API endpoints validate permissions and delegate. JavaScript handles display and user interaction only. Do not use any deprecated Frappe API. Do not access private Frappe internals. Everything is delivered as fixtures so the module is fully portable across environments. Be forward compatible — use only documented public APIs.**

---

## Part 1 — Product Requirements

---

### 1.1 Problem Statement

MPD Industries manufactures resin and coating products through third-party processors (job workers). Before quoting a price to a customer, the sales team needs to know the true ex-factory cost of making a product — accounting for raw material rates, financing costs, processing charges, and product-specific surcharges.

Currently this is done in Excel. The Excel model uses approximations — normalising all supplier rates to a fictional 60-day credit basis, using fixed padding percentages, and applying the same financing cost regardless of actual supplier credit terms. The result is an inaccurate cost floor that either leaves money on the table or prices MPD out of deals.

Additionally the current process has no audit trail, no formulation comparison, no approval workflow, and no historical record of what rates were used for any given quote.

---

### 1.2 Objectives

Build a costing engine inside ERPNext that:

- Computes the true ex-factory cost per kg for any product at any processor
- Evaluates all available formulations (BOMs) simultaneously and ranks them by cost
- Uses actual supplier credit terms to compute financing costs — no approximations
- Snapshots all rates at evaluation time so historical costings are never affected by future rate changes
- Tracks manual rate overrides transparently so the MD can see exactly what was changed
- Routes the confirmed cost through an MD approval workflow before it can be used as a quote basis
- Alerts the salesperson and MD when a cheaper formulation exists beyond a configurable threshold

---

### 1.3 Scope — Phase 1

Phase 1 answers one question only: **what does it cost MPD to manufacture this product ex-factory?**

**In scope:**
- City and Processor masters
- Material Rate master with pending state and conflict detection
- Processing Charge master
- Costing Configuration
- Costing Request document with full evaluation engine
- Formulation comparison and ranking
- Rate override mechanism with audit trail
- MD approval workflow
- Item Rate History report
- Costing workspace

**Explicitly out of scope for Phase 1:**
- Customer, delivery, packaging, credit cost, MPD margin
- Customer Quote document
- Delivery Rate master
- Packaging Cost master
- Layer 2 and Layer 3 selling price stack
- Any customer-facing output

These will be built in Phase 2 as a Customer Quote document that links to an approved Costing Request and stacks customer-specific costs on top of the confirmed ex-factory cost. Nothing in Phase 1 needs to change for that to work.

---

### 1.4 User Roles

**Costing User**
The person preparing the costing — typically a salesperson or production manager. Can create and manage Costing Requests. Can enter rate overrides. Read only on all masters. Cannot see internal earnings analysis.

**Costing Approver**
The MD. Can approve and reject Costing Requests. Can see the internal earnings analysis. Read only on everything else.

**Rate Manager**
Purchase team. Full access to Material Rate and Processing Charge masters. Read only on Costing Requests.

**System Manager**
Full access to everything including internal earnings analysis and the actual cost of capital field.

---

### 1.5 Core Business Rules

**Rule 1 — Only items with active submitted BOMs can be costed.**
The item field on Costing Request is filtered to items with `has_bom = 1`. A controller validation backstops this.

**Rule 2 — Rates are city-scoped.**
All processors in the same city share the same material rates. The purchase team enters one rate per item per city, not per processor.

**Rule 3 — Rates snapshot at evaluation time.**
When Get Rates is clicked, all current rates are copied onto the Costing Request's child tables. Subsequent changes to the rate masters do not affect this document unless Get Rates is clicked again.

**Rule 4 — Get Rates runs automatically before submission.**
The `before_submit` hook re-fetches all rates. If any rate in the selected formulation is Missing at submission time, submission is blocked. Expired rates are allowed through with a warning because they carry a cost figure. Missing rates carry a zero and produce a meaningless cost.

**Rule 5 — Overrides are transparent.**
The fetched value and the working value are always stored separately. `is_overridden` is computed by comparing them to 2 decimal places — never stored. The MD sees every override at approval time.

**Rule 6 — Documents are frozen on submission.**
Once submitted, no field can be changed. If rates change, a new Costing Request must be created.

**Rule 7 — No backdating of rates.**
Material Rate `valid_from` cannot be before the current datetime for active records. Pending records (is_active = 0) are exempt from all validation.

**Rule 8 — Production days default to 30 but are configurable.**
This represents the time MPD's capital is tied up in production regardless of customer payment terms. Even an advance-paying customer does not reduce this to zero.

**Rule 9 — Two interest rates apply.**
Supplier financing rate (default 12% pa) — MPD's cost of capital applied to days MPD funds raw materials. Actual cost of capital (default 9% pa) — the real internal benchmark, used only in the internal earnings analysis, visible only to System Manager.

**Rule 10 — Formulation switch alert.**
When the preferred formulation is more expensive than the cheapest formulation by more than the configured threshold (default 5%), a prominent alert is shown to both the salesperson and the MD.

---

### 1.6 The Interest Model

This replaces the current Excel approximation with exact per-ingredient financing costs.

**At ex-factory stage (Phase 1):**

For each raw material ingredient:
```
net_financed_days = max(0, production_days - supplier_credit_days)
financing_cost = amount_per_kg × (net_financed_days / 365) × supplier_financing_rate_pct
```

If a supplier gives 45 days credit and production takes 30 days, MPD finances zero days — the supplier is effectively funding the material through production. If a supplier gives 15 days credit, MPD finances 15 days.

**Customer credit days are Phase 2.** They will be added in the Customer Quote as:
```
customer_credit_cost = confirmed_ex_factory_cost × (customer_credit_days / 365) × customer_credit_rate_pct
```

This is architecturally separate from the ex-factory cost and is never part of Phase 1 computation.

---

### 1.7 The Cost Stack — Phase 1

All costs expressed as ₹ per kg of finished goods output.

```
Raw Material Cost
  For each ingredient:
    qty_per_kg = ingredient.qty / bom.quantity
    amount_per_kg = qty_per_kg × working_rate

Financing Cost
  For each ingredient:
    net_financed_days = max(0, production_days - working_supplier_credit_days)
    financing_cost = amount_per_kg × (net_financed_days / 365) × supplier_financing_rate_pct

Processing Cost
  = (solids_content_pct / 100) × working_charge_per_kg

Additional Charges
  Per kg of Output: amount = rate
  Per kg of Solids: amount = rate × (solids_content_pct / 100)

Outward Freight
  = working_freight_per_unit (if not included in processing charge)
  = 0 (if includes_outward_freight is ticked)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONFIRMED EX-FACTORY COST PER KG
= RM Cost + Financing Cost + Processing Cost
  + Additional Charges + Outward Freight
```

---

### 1.8 The Formulation Selection Logic

The engine evaluates every active submitted BOM for the selected item. For each BOM it computes the full cost stack. The FormulationSelector then:

1. Finds the minimum total cost across all combinations
2. Computes `delta_pct = (combination_cost - min_cost) / min_cost × 100` for each
3. Auto-excludes combinations where `delta_pct > auto_exclusion_threshold_pct` (default 15%)
4. Ranks non-excluded combinations by total cost ascending
5. Checks if preferred formulation is more expensive than rank 1 by more than `formulation_switch_threshold_pct` (default 5%) — if yes, generates switch alert

---

### 1.9 The Override Mechanism

Every fetched value has a `fetched_` twin stored as a hidden field. The editable working value drives all calculations. `is_overridden` is computed — never stored — as:

```python
is_overridden = round(working_value, 2) != round(fetched_value, 2)
```

This pattern applies consistently to:
- Every material rate (rate and credit days)
- Processing charge (charge per kg, freight per unit, includes outward freight)
- Production days on the header
- Supplier financing rate on the header

When Get Rates is clicked and overrides exist, a dialog presents two choices: Keep overrides or Reset to official. The automatic re-fetch on `before_submit` always preserves overrides silently.

---

### 1.10 Rate States and What the System Does With Each

| State | Meaning | Engine behaviour | Can select formulation | Can submit |
|---|---|---|---|---|
| Current | Valid rate exists today | Used directly. Green indicator | Yes | Yes |
| Expired | Rate existed but valid_to has passed | Used as working value with amber warning. Indicative label on combination | Yes with warning | No — must enter override or get fresh rate |
| Missing | No rate record exists at all | Zero in fetched_rate. Red indicator | Yes with warning | No — hard block |

The system never hides an indicative cost. The salesperson can always see the combination card and make decisions. Submission is the only hard gate.

---

### 1.11 Approval Flow

```
Draft
  ↓ (salesperson clicks Submit)
before_submit fires → rates re-fetched → hard block if any Missing in selected formulation
  ↓
Pending Approval
  ↓ (MD reviews and approves)
Approved — confirmed_ex_factory_cost_per_kg locked forever
  ↓ (or MD rejects with reason)
Rejected → returns to Draft
```

The MD sees on the approval form:
- Full combination cards with the selected one highlighted
- Rate override table with official rates forced visible and overrides highlighted amber
- Full cost breakdown (Layer 1)
- Internal earnings analysis (Layer 3) — visible to Costing Approver and System Manager only
- Formulation switch alert if applicable

---

## Part 2 — System Architecture

---

### 2.1 Module Location

Inside existing app `mpd_customizations`. New module named `costing`. Do not create a new app.

---

### 2.2 Repository Structure

```
mpd_customizations/
├── modules.txt                          ← add "Costing"
├── mpd_customizations/
│   ├── costing/
│   │   ├── __init__.py                  ← defines RateConflictError
│   │   ├── doctype/
│   │   │   ├── city/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── city.json
│   │   │   │   └── city.py
│   │   │   ├── processor/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── processor.json
│   │   │   │   └── processor.py
│   │   │   ├── material_rate/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── material_rate.json
│   │   │   │   ├── material_rate.py
│   │   │   │   └── material_rate.js
│   │   │   ├── processing_charge/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── processing_charge.json
│   │   │   │   ├── processing_charge.py
│   │   │   │   └── processing_charge.js
│   │   │   ├── costing_configuration/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── costing_configuration.json
│   │   │   │   └── costing_configuration.py
│   │   │   ├── costing_request/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── costing_request.json
│   │   │   │   ├── costing_request.py
│   │   │   │   └── costing_request.js
│   │   │   ├── costing_additional_charge/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── costing_additional_charge.json
│   │   │   │   └── costing_additional_charge.py
│   │   │   ├── costing_rate_line/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── costing_rate_line.json
│   │   │   │   └── costing_rate_line.py
│   │   │   ├── costing_processing_line/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── costing_processing_line.json
│   │   │   │   └── costing_processing_line.py
│   │   │   ├── costing_combination/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── costing_combination.json
│   │   │   │   └── costing_combination.py
│   │   │   └── costing_material_line/
│   │   │       ├── __init__.py
│   │   │       ├── costing_material_line.json
│   │   │       └── costing_material_line.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── config.py
│   │   │   ├── rate_option.py
│   │   │   ├── cost_calculator.py
│   │   │   ├── rate_source_registry.py
│   │   │   ├── costing_engine.py
│   │   │   ├── formulation_selector.py
│   │   │   ├── rate_fetcher.py
│   │   │   └── sources/
│   │   │       ├── __init__.py
│   │   │       ├── base.py
│   │   │       └── manual_rate_source.py
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── costing.py
│   │   ├── report/
│   │   │   └── item_rate_history/
│   │   │       ├── __init__.py
│   │   │       ├── item_rate_history.json
│   │   │       └── item_rate_history.py
│   │   └── workspace/
│   │       └── costing/
│   │           └── costing.json
│   └── fixtures/
│       ├── custom_field.json
│       ├── role.json
│       ├── costing_configuration.json
│       └── workspace.json
└── tests/
    └── costing/
        ├── __init__.py
        ├── test_cost_calculator.py
        ├── test_manual_rate_source.py
        ├── test_rate_fetcher.py
        ├── test_costing_engine.py
        └── test_formulation_selector.py
```

---

### 2.3 hooks.py Additions

Append only. Never replace existing entries.

```
fixtures:
  - Custom Field filtered by module = Costing
  - Role filtered by name in [Costing User, Costing Approver, Rate Manager]
  - Costing Configuration single record
  - Workspace filtered by name = Costing

scheduler_events daily:
  mpd_customizations.costing.services.rate_validity_monitor
  .run_rate_validity_check

doc_events:
  Material Rate after_insert:
    mpd_customizations.costing.api.costing.on_material_rate_created
```

---

### 2.4 Custom Fields on Standard DocTypes

Delivered as fixtures only. Never touch ERPNext core files.

**On Item:**
- `custom_solids_content_pct` — Float — label "Solids Content %" — inserted after description — module: Costing

**On BOM:**
- `custom_formulation_id` — Data — label "Formulation ID" — inserted after item — module: Costing

---

### 2.5 `costing/__init__.py`

Define `RateConflictError` here:

```python
class RateConflictError(Exception):
    def __init__(self, conflicting_name, conflicting_valid_from, conflicting_valid_to):
        self.conflicting_name = conflicting_name
        self.conflicting_valid_from = conflicting_valid_from
        self.conflicting_valid_to = conflicting_valid_to
        super().__init__(f"Rate conflict with {conflicting_name}")
```

---

## Part 3 — DocType Specifications

---

### 3.1 City

**Type:** Regular
**Naming:** By fieldname — city_name
**Track Changes:** No

| fieldname | fieldtype | label | reqd | notes |
|---|---|---|---|---|
| city_name | Data | City Name | Yes | Unique. In list view |
| state | Data | State | No | In list view |

Permissions: System Manager and Rate Manager full CRUD. Costing User and Costing Approver read only.

Controller: empty.

---

### 3.2 Processor

**Type:** Regular
**Naming:** By fieldname — processor_name
**Track Changes:** Yes

| fieldname | fieldtype | label | reqd | notes |
|---|---|---|---|---|
| processor_name | Data | Processor Name | Yes | Unique. In list view |
| city | Link → City | City | Yes | In list view. Drives all rate lookups |
| default_rm_warehouse | Link → Warehouse | Default RM Warehouse | No | For stock flows only. Not used in costing |
| notes | Small Text | Notes | No | |

Permissions: same as City.

Controller: empty.

---

### 3.3 Material Rate

**Type:** Regular
**Naming:** MR-.YYYY.-.#####
**Track Changes:** Yes
**Is Submittable:** No

| fieldname | fieldtype | label | reqd | notes |
|---|---|---|---|---|
| item | Link → Item | Item | Yes | In list view |
| item_name | Data | Item Name | No | Fetched. Read only |
| supplier | Link → Supplier | Supplier | No | Optional when pending. Required when activating |
| city | Link → City | City | Yes | In list view |
| costing_request | Link → Costing Request | Costing Request | No | Set when auto-created as pending placeholder |
| section_break_rate | Section Break | Rate | | |
| rate_type | Select | Rate Type | Yes | Ex-Works + Freight / All-In Delivered |
| ex_works_rate | Currency | Ex-Works Rate (₹) | No | Shown when Ex-Works + Freight only |
| freight_per_unit | Currency | Freight per Unit (₹) | No | Shown when Ex-Works + Freight only |
| delivered_rate | Currency | Delivered Rate (₹) | No | Computed or entered |
| uom | Link → UOM | UOM | Yes | |
| col_break_rate | Column Break | | | |
| credit_days | Int | Supplier Credit Days | No | Default 0 |
| lead_time_days | Int | Lead Time Days | No | Optional. Informational |
| section_break_validity | Section Break | Validity | | |
| valid_from | Datetime | Valid From | Yes | Cannot backdate on active records |
| valid_to | Datetime | Valid To | No | Auto-set from config when blank |
| col_break_validity | Column Break | | | |
| is_active | Check | Active | No | Default 0. Pending until activated |
| notes | Small Text | Notes | No | |

Permissions: System Manager and Rate Manager full CRUD. Costing User and Costing Approver read only.

**Controller — validate:**

When `is_active = 0`: skip all validation. Save without checks.

When `is_active = 1`:
- `supplier` required. Hard error if blank.
- `delivered_rate` must be > 0. Hard error.
- `credit_days` must be >= 0. Hard error.
- `valid_from` must be >= now(). Hard error: *"Valid From cannot be in the past."*
- If `valid_to` blank: call `_set_default_valid_to()` — reads config, computes end of month at 23:59:59, end of quarter at 23:59:59, or now() + N days at 23:59:59.
- If `valid_to` set: must be after `valid_from`. Hard error.
- If rate_type is Ex-Works + Freight: `delivered_rate = ex_works_rate + freight_per_unit`.
- Call `_check_overlap()`.

**`_check_overlap()`:**
Query Material Rate where `item = this.item`, `supplier = this.supplier`, `city = this.city`, `is_active = 1`, `name != this.name`. For each result check: `existing.valid_from < this.valid_to AND existing.valid_to > this.valid_from` (null valid_to treated as far future).

If overlap and `self.flags.get("auto_expire_confirmed")`: set `existing.valid_to = this.valid_from - 1 second` via `frappe.db.set_value`. Do not call existing.save().

If overlap and flag not set: raise `RateConflictError` with conflicting record details.

**Controller — before_save:**
Always compute `delivered_rate = ex_works_rate + freight_per_unit` when rate_type is Ex-Works + Freight.

**JS — material_rate.js:**
- On rate_type change: toggle ex_works_rate and freight_per_unit visibility. Toggle delivered_rate editability.
- On ex_works_rate or freight_per_unit change: compute delivered_rate client-side instantly.
- On valid_from date change: if today set time to now + 15 seconds. If future set time to 00:00:00.
- On form load with is_active = 0: show yellow dashboard message: *"This rate is pending. Fill in supplier, rate, and credit days then check Active to activate."*
- On save returning RateConflictError: show frappe.confirm dialog offering to expire the conflicting record. On confirm: set flag, re-save.

---

### 3.4 Processing Charge

**Type:** Regular
**Naming:** PC-.YYYY.-.#####
**Track Changes:** Yes

| fieldname | fieldtype | label | reqd | notes |
|---|---|---|---|---|
| processor | Link → Processor | Processor | Yes | In list view |
| item | Link → Item | Item (Specific) | No | Priority over item_group |
| item_name | Data | Item Name | No | Fetched. Read only |
| item_group | Link → Item Group | Item Group (Fallback) | No | Used when no item-specific record |
| col_break_1 | Column Break | | | |
| charge_per_kg | Currency | Charge per kg of Solids (₹) | Yes | In list view |
| includes_outward_freight | Check | Includes Outward Freight | No | Default 0 |
| fg_freight_per_unit | Currency | FG Freight per Unit (₹) | No | Shown when includes_outward_freight is unchecked |
| section_break_validity | Section Break | Validity | | |
| valid_from | Datetime | Valid From | Yes | |
| valid_to | Datetime | Valid To | No | |
| col_break_validity | Column Break | | | |
| is_active | Check | Active | No | Default 1 |
| notes | Small Text | Notes | No | |

Permissions: System Manager and Rate Manager full CRUD. Costing User and Costing Approver read only.

**Controller — validate:**
- At least one of item or item_group must be set.
- charge_per_kg > 0.
- valid_to after valid_from if provided.
- No overlap for same processor + item (or processor + item_group). Same overlap logic. Hard error with conflicting record name.

**JS — processing_charge.js:**
Toggle fg_freight_per_unit visibility based on includes_outward_freight.

---

### 3.5 Costing Configuration

**Type:** Single Record
**Module:** Costing

| fieldname | fieldtype | label | default | permlevel | notes |
|---|---|---|---|---|---|
| engine_version | Data | Engine Version | 1.0.0 | 0 | |
| section_break_production | Section Break | Production | | | |
| production_days | Int | Production Days | 30 | 0 | Default for new requests |
| section_break_rates | Section Break | Interest Rates | | | |
| supplier_financing_rate_pct | Float | Supplier Financing Rate % pa | 12 | 0 | Default for new requests |
| actual_cost_of_capital_pct | Float | Actual Cost of Capital % pa | 9 | 1 | System Manager only. Internal earnings only |
| section_break_formulation | Section Break | Formulation Selection | | | |
| auto_exclusion_threshold_pct | Float | Auto Exclusion Threshold % | 15 | 0 | |
| formulation_switch_threshold_pct | Float | Formulation Switch Alert Threshold % | 5 | 0 | |
| section_break_validity | Section Break | Rate Validity | | | |
| default_valid_to | Select | Default Valid To | End of Month | 0 | End of Month / End of Quarter / Custom Days |
| default_valid_to_days | Int | Default Valid To Days | 30 | 0 | Used when Custom Days selected |
| rate_expiry_warning_days | Int | Rate Expiry Warning Days | 30 | 0 | |

`actual_cost_of_capital_pct` uses permlevel 1. Grant level 1 read permission to System Manager only.

**Controller:** `get_config()` function — reads single record, returns populated `CostingConfig` dataclass, cached on `frappe.local`.

---

### 3.6 Costing Request

**Type:** Regular
**Naming:** CR-.YYYY.-.#####
**Is Submittable:** Yes
**Track Changes:** Yes

Fields in order — this is the form layout:

| fieldname | fieldtype | label | reqd | notes |
|---|---|---|---|---|
| **Section: Product** | | | | |
| item | Link → Item | Product | Yes | Filter: has_bom = 1. In list view |
| item_name | Data | Product Name | No | Fetched. Read only |
| solids_content_pct | Float | Solids Content % | Yes | Fetched from item.custom_solids_content_pct. Editable |
| col_break_product | Column Break | | | |
| processor | Link → Processor | Processor | Yes | In list view |
| processor_name | Data | Processor Name | No | Fetched. Read only |
| **Section: Parameters** | | | | |
| production_days | Int | Production Days | Yes | Working value. Editable. Amber when differs from fetched |
| fetched_production_days | Int | — | No | Hidden. Populated from config on create |
| col_break_params | Column Break | | | |
| supplier_financing_rate_pct | Float | Supplier Financing Rate % pa | Yes | Working value. Editable. Amber when differs from fetched |
| fetched_supplier_financing_rate_pct | Float | — | No | Hidden. Populated from config on create |
| **Section: Previous Costing** | | | | |
| preferred_bom | Link → BOM | Preferred Formulation | No | Pre-filled from last approved costing for this item |
| previous_costing_ref | Link → Costing Request | Pre-filled From | No | Read only |
| **Section: Additional Charges** | | | | |
| additional_charges | Table → Costing Additional Charge | Additional Charges | No | |
| **Section: Rates** | | | | |
| rate_lines | Table → Costing Rate Line | Material Rates | No | Populated by Get Rates |
| **Section: Processing** | | | | |
| processing_lines | Table → Costing Processing Line | Processing Charge | No | Populated by Get Rates. Single row |
| **Section: State** | | | | |
| mode | Select | Mode | No | Exploring / Awaiting Rates / Partially Costed / Ready to Quote / Pending Approval / Approved / Rejected. Read only |
| selected_combination | Link → Costing Combination | Selected Formulation | No | Read only |
| confirmed_ex_factory_cost_per_kg | Currency | Confirmed Ex-Factory Cost per kg | No | Read only. Locked on approval |
| last_evaluated_on | Datetime | Last Evaluated On | No | Read only |
| engine_version_used | Data | Engine Version Used | No | Read only |
| formulation_switch_alert | Small Text | Formulation Alert | No | Read only. Set by engine |
| **Section: Panels** | | | | |
| combinations_html | HTML | Formulation Comparison | No | Mount point for combination cards |
| cost_breakdown_html | HTML | Cost Breakdown | No | Mount point for breakdown panel |

Permissions:

| Role | Read | Write | Create | Submit | Amend |
|---|---|---|---|---|---|
| System Manager | Yes | Yes | Yes | Yes | Yes |
| Costing User | Yes | Yes | Yes | Yes | No |
| Costing Approver | Yes | No | No | No | No |
| Rate Manager | Yes | No | No | No | No |

**Controller — on_load:**
On new document: fetch `production_days` and `supplier_financing_rate_pct` from Costing Configuration and set both working and fetched fields.

**Controller — validate:**
- `solids_content_pct` must be between 0 and 100 exclusive.
- `production_days` must be positive.
- `supplier_financing_rate_pct` must be positive.
- If item is set: verify active submitted BOM exists. Hard error if not.
- Recompute `amount_per_kg` on all additional_charges rows using current `solids_content_pct`.

**Controller — before_submit:**
1. Call `RateFetcher.fetch(self)` — re-fetches all rates from masters.
2. Apply override preservation — update fetched values but preserve working values.
3. Check selected formulation: if any Costing Material Line for the selected combination has `rate_freshness = "Missing"` and `working_rate = 0` — hard block. Error names specific items.
4. Recompute all combination costs.
5. Update mode to Pending Approval.

**Controller — on_submit:**
Set `mode = "Approved"` via `frappe.db.set_value`.

**Controller — on_cancel:**
Set `mode = "Exploring"` via `frappe.db.set_value`.

**Controller — on_trash:**
`frappe.db.delete("Costing Material Line", {"costing_request": self.name})`
`frappe.db.delete("Costing Combination", {"costing_request": self.name})`

---

### 3.7 Costing Additional Charge

**Type:** Child of Costing Request

| fieldname | fieldtype | label | reqd | notes |
|---|---|---|---|---|
| description | Data | Description | Yes | In list view |
| basis | Select | Basis | Yes | Per kg of Output / Per kg of Solids. In list view |
| rate | Currency | Rate (₹) | Yes | In list view |
| amount_per_kg | Currency | Amount per kg | No | Read only. Computed by parent controller |

Computation in parent validate:
- Per kg of Output: `amount_per_kg = rate`
- Per kg of Solids: `amount_per_kg = rate × (solids_content_pct / 100)`

---

### 3.8 Costing Rate Line

**Type:** Child of Costing Request

One row per unique item across all formulations. Populated by Get Rates.

| fieldname | fieldtype | label | reqd | notes |
|---|---|---|---|---|
| item | Link → Item | Item | Yes | In list view. Read only after fetch |
| item_name | Data | Item Name | No | Fetched. Read only |
| uom | Link → UOM | UOM | No | Read only |
| city | Link → City | City | No | Read only |
| supplier | Link → Supplier | Winning Supplier | No | Read only |
| rate_source_ref | Data | Rate Source | No | Hidden. Material Rate document name |
| fetched_rate | Currency | Official Rate | No | Hidden by default. Rate from master at fetch time |
| fetched_supplier_credit_days | Int | Official Credit Days | No | Hidden. Credit days from master |
| rate_freshness | Select | Freshness | No | Current / Expired / Missing. Read only |
| working_rate | Currency | Rate to Use | No | Editable. Pre-filled with fetched_rate |
| working_supplier_credit_days | Int | Credit Days | No | Editable. Pre-filled with fetched value |
| override_reason | Small Text | Override Reason | No | Optional |

`is_overridden` — never stored. Computed in Python and JS:
`round(working_rate, 2) != round(fetched_rate, 2) OR working_supplier_credit_days != fetched_supplier_credit_days`

---

### 3.9 Costing Processing Line

**Type:** Child of Costing Request

Single row. Populated by Get Rates.

| fieldname | fieldtype | label | reqd | notes |
|---|---|---|---|---|
| processor | Link → Processor | Processor | No | Read only |
| processing_charge_ref | Data | Processing Charge Source | No | Hidden. Document name |
| fetched_charge_per_kg | Currency | Official Charge per kg | No | Hidden |
| fetched_freight_per_unit | Currency | Official Freight per Unit | No | Hidden |
| fetched_includes_outward_freight | Check | Official Includes Freight | No | Hidden |
| working_charge_per_kg | Currency | Charge per kg to Use | No | Editable |
| working_freight_per_unit | Currency | Freight per Unit to Use | No | Editable |
| working_includes_outward_freight | Check | Includes Outward Freight | No | Editable |
| override_reason | Small Text | Override Reason | No | Optional |

`is_overridden` — computed: any working value differs from its fetched counterpart.

---

### 3.10 Costing Combination

**Type:** Regular
**Naming:** CC-.YYYY.-.#####
**Track Changes:** No
No delete permission for any role. Deletion only via engine cascade.

| fieldname | fieldtype | label | reqd | notes |
|---|---|---|---|---|
| costing_request | Link → Costing Request | Costing Request | Yes | In list view |
| bom | Link → BOM | BOM | Yes | |
| formulation_id | Data | Formulation ID | No | From BOM.custom_formulation_id |
| is_preferred | Check | Is Preferred | No | Matches preferred_bom on the request |
| section_break_costs | Section Break | Cost Breakdown per kg | | |
| rm_cost_per_kg | Currency | RM Cost per kg | No | |
| financing_cost_per_kg | Currency | Financing Cost per kg | No | |
| processing_cost_per_kg | Currency | Processing Cost per kg | No | |
| additional_charges_per_kg | Currency | Additional Charges per kg | No | |
| outward_freight_per_kg | Currency | Outward Freight per kg | No | |
| total_cost_per_kg | Currency | Total Cost per kg | No | |
| col_break_costs | Column Break | | | |
| rank | Int | Rank | No | Null if excluded |
| delta_pct | Float | Delta % vs Cheapest | No | |
| status | Select | Status | No | Ready to Quote / Indicative — Rates Expired / Indicative — Rates Missing / Excluded — Too Expensive |
| is_selected | Check | Selected | No | |
| section_break_refs | Section Break | References | | |
| processing_charge_ref | Data | Processing Charge Used | No | |
| missing_items | Small Text | Missing Rate Items | No | |
| expired_items | Small Text | Expired Rate Items | No | |
| evaluated_on | Datetime | Evaluated On | No | |

---

### 3.11 Costing Material Line

**Type:** Regular
**Naming:** CML-.YYYY.-.#####
**Track Changes:** No
No delete permission for any role. Deletion only via engine cascade.

| fieldname | fieldtype | label | reqd | notes |
|---|---|---|---|---|
| costing_request | Link → Costing Request | Costing Request | Yes | Denormalised |
| combination | Link → Costing Combination | Combination | Yes | |
| item | Link → Item | Item | Yes | |
| item_name | Data | Item Name | No | |
| uom | Link → UOM | UOM | No | |
| qty_per_kg_output | Float | Qty per kg Output | No | Precision 6 |
| supplier | Link → Supplier | Supplier | No | |
| city | Link → City | City | No | |
| rate_freshness | Select | Rate Freshness | No | Current / Expired / Missing |
| working_rate | Currency | Rate Used | No | From Costing Rate Line at evaluation time |
| working_supplier_credit_days | Int | Credit Days Used | No | From Costing Rate Line |
| net_financed_days | Int | Net Financed Days | No | max(0, production_days - supplier_credit_days) |
| amount_per_kg | Currency | Amount per kg | No | qty_per_kg_output × working_rate |
| financing_cost_per_kg | Currency | Financing Cost per kg | No | |
| confidence_score | Float | Confidence Score | No | 0-100 |

Note: `is_overridden` is not stored here. It is read from the parent Costing Rate Line row for display purposes only.

---

## Part 4 — Services Layer

All business logic. Zero Frappe form dependencies. Every service independently testable.

---

### 4.1 `services/config.py`

`CostingConfig` dataclass with all Costing Configuration fields including `actual_cost_of_capital_pct`.

`get_config() -> CostingConfig`:
- Check `frappe.local` for cached instance.
- If not cached: `frappe.get_single("Costing Configuration")`, populate dataclass, cache on `frappe.local.costing_config`, return.
- Called once per request. Never re-read mid-computation.

---

### 4.2 `services/rate_option.py`

`RateOption` dataclass:

| field | type | default |
|---|---|---|
| item | str | required |
| city | str | required |
| supplier | str or None | None |
| rate_source_ref | str or None | None |
| delivered_rate | float | required |
| supplier_credit_days | int | 0 |
| lead_time_days | int or None | None |
| valid_from | datetime | required |
| valid_to | datetime or None | None |
| rate_freshness | str | required |
| confidence_score | float | 50.0 |
| second_best_supplier | str or None | None |
| second_best_rate | float | 0.0 |

No methods. Pure data carrier.

---

### 4.3 `services/sources/base.py`

Abstract base class `BaseRateSource`:

Class attributes: `source_type: str`, `priority: int`

Abstract methods:
- `can_resolve(item, city, pricing_dt) -> bool`
- `resolve(item, city, pricing_dt) -> list[RateOption]`

Default concrete method:
- `batch_resolve(pairs, pricing_dt) -> dict[tuple, list[RateOption]]`
  Default calls resolve() per pair. Subclasses override for efficiency.

---

### 4.4 `services/sources/manual_rate_source.py`

`ManualRateSource(BaseRateSource)`:
`source_type = "Manual"`, `priority = 10`

**`batch_resolve` — single SQL fetch:**

Collect all unique items and cities from pairs. One `frappe.db.get_all` against Material Rate with item IN items and city IN cities. Fetch all relevant fields including supplier_quotation_ref.

Group by (item, city) in Python using defaultdict.

For each pair:
- `current` — is_active=1, valid_from <= pricing_dt, valid_to >= pricing_dt or null
- `expired` — is_active=1, valid_to < pricing_dt
- Sort current by delivered_rate ascending. Sort expired by valid_from descending.
- Best = current[0] if exists, else expired[0] if exists, else Missing placeholder.
- second_best from index 1 of merged sorted list.

Confidence score per option (clamp 0-100):
- Base: 50
- +20 if supplier_quotation_ref set
- +20 if valid_from >= pricing_dt - 30 days
- +10 if supplier has 3+ historical records for this item + city (count from already-fetched data — no extra query)
- -30 if All-In Delivered with no ex_works breakup

Missing placeholder: delivered_rate=0, supplier=None, rate_source_ref=None, confidence_score=0, rate_freshness="Missing".

---

### 4.5 `services/rate_source_registry.py`

`RateSourceRegistry`:
Constructor takes `list[BaseRateSource]`. Sorts by priority ascending.

`batch_resolve(pairs, pricing_dt) -> dict[tuple, RateOption]`:
- Call batch_resolve on every source.
- Merge per pair. Sort: Current before Expired before Missing, then by delivered_rate ascending within tier.
- Best = index 0. Set second_best from index 1.
- Return dict keyed by (item, city) → best RateOption.

`get_default_registry() -> RateSourceRegistry`:
Returns `RateSourceRegistry([ManualRateSource()])`.
Future sources added here only.

---

### 4.6 `services/rate_fetcher.py`

`RateFetcher` — handles the fetch-and-snapshot operation for the Costing Request child tables. Separate from the engine because it runs both on Get Rates button and in before_submit.

`fetch(costing_request_doc, preserve_overrides=True) -> FetchResult`:

1. Get processor city from `frappe.db.get_value("Processor", doc.processor, "city")`.
2. Fetch all active submitted BOMs for doc.item.
3. Fetch all BOM items for those BOMs in one query. Collect unique item codes.
4. Batch resolve rates via `get_default_registry().batch_resolve(pairs, now())`.
5. Fetch Processing Charge — item-specific first, item_group fallback. Store None if not found.
6. Update Costing Rate Line rows:
   - If `preserve_overrides = True` and row already exists for this item: update `fetched_rate`, `fetched_supplier_credit_days`, `rate_freshness`, `supplier`, `rate_source_ref`. Leave `working_rate` and `working_supplier_credit_days` unchanged.
   - If row does not exist: create row with both fetched and working values set to the resolved rate.
   - If `preserve_overrides = False`: set working values equal to fetched values for all rows.
7. Update Costing Processing Line row:
   - Same preserve logic for working_charge_per_kg, working_freight_per_unit, working_includes_outward_freight.
8. Return `FetchResult` with: `has_missing_rates`, `missing_items`, `has_expired_rates`, `expired_items`, `overrides_detected`, `overrides_changed` (items where fetched value changed since override was set).

The override dialog in JS is driven by `FetchResult.overrides_detected`. If overrides_detected is true, the dialog appears before the fetch is applied.

---

### 4.7 `services/cost_calculator.py`

Pure functions. Zero Frappe imports. Zero database calls. Fully unit testable.

```
compute_rm_line_amount(qty_per_kg_output, working_rate) -> float
  Returns qty_per_kg_output × working_rate

compute_financing_cost_for_line(
    amount_per_kg,
    production_days,
    working_supplier_credit_days,
    supplier_financing_rate_pct
) -> float
  net_financed_days = max(0, production_days - working_supplier_credit_days)
  Returns amount_per_kg × (net_financed_days / 365) × (supplier_financing_rate_pct / 100)

compute_processing_cost(solids_content_pct, working_charge_per_kg) -> float
  Returns (solids_content_pct / 100) × working_charge_per_kg

compute_additional_charge_amount(rate, basis, solids_content_pct) -> float
  "Per kg of Output": returns rate
  "Per kg of Solids": returns rate × (solids_content_pct / 100)
  Raises ValueError for unrecognised basis

compute_total_cost(
    rm_cost, financing_cost, processing_cost,
    additional_charges, outward_freight
) -> float
  Returns sum of all components

compute_internal_earnings(
    material_lines,
    actual_cost_of_capital_pct,
    supplier_financing_rate_pct
) -> dict
  spread_pct = max(0, supplier_financing_rate_pct - actual_cost_of_capital_pct)
  Per line: spread = amount_per_kg × (net_financed_days / 365) × (spread_pct / 100)
  Returns rm_spread_per_kg, rm_spread_breakdown, total_spread_per_kg
```

---

### 4.8 `services/formulation_selector.py`

`FormulationSelector(config: CostingConfig)`:

`select(combinations: list[dict], preferred_bom: str) -> SelectionResult`:

1. Find `min_cost` across all combinations.
2. Compute `delta_pct` per combination.
3. Mark `Excluded — Too Expensive` where `delta_pct > auto_exclusion_threshold_pct`.
4. Rank non-excluded by total_cost ascending. Assign rank starting 1.
5. Set `is_preferred = True` on combination matching preferred_bom regardless of rank.
6. If preferred exists and is not rank 1 and `(preferred_cost - rank1_cost) / rank1_cost × 100 > formulation_switch_threshold_pct`: generate switch_alert string.

Returns: `SelectionResult` dataclass with `included`, `excluded`, `cheapest_cost`, `threshold_applied`, `switch_alert`.

---

### 4.9 `services/costing_engine.py`

`CostingEngine(registry: RateSourceRegistry, config: CostingConfig)`:

**`evaluate(costing_request_name, trigger) -> dict`:**

Execute in this exact order:

1. Load Costing Request via `frappe.get_doc`. Validate all required fields present.
2. Validate active submitted BOM exists for item.
3. Get processor city.
4. Call `RateFetcher.fetch(doc, preserve_overrides=True)` — this updates the rate line child tables on the document.
5. Fetch active submitted BOMs.
6. Fetch all BOM items in one `frappe.get_all` call. Group by BOM in Python.
7. For each BOM compute combination result using working values from rate_lines and processing_lines child tables:
   - Per ingredient: get working_rate and working_supplier_credit_days from the matching Costing Rate Line row.
   - compute_rm_line_amount per ingredient.
   - compute_financing_cost_for_line per ingredient.
   - Aggregate rm_cost_per_kg and financing_cost_per_kg.
   - compute_processing_cost using working_charge_per_kg from processing_lines.
   - compute additional_charges_per_kg from additional_charges child table.
   - outward_freight_per_kg from working_freight_per_unit if not working_includes_outward_freight.
   - compute_total_cost.
   - Determine status from rate_freshness values of constituent lines.
8. Run FormulationSelector.select() with all combination results and doc.preferred_bom.
9. Set doc.formulation_switch_alert from selector result.
10. Purge: `frappe.db.delete("Costing Material Line", {"costing_request": name})` then `frappe.db.delete("Costing Combination", {"costing_request": name})`. Delete material lines before combinations.
11. Write Costing Combination records via `frappe.get_doc({...}).insert(ignore_permissions=True)`.
12. Write Costing Material Line records. Set working_rate and working_supplier_credit_days from the Costing Rate Line rows (not from resolver directly — always via the child table).
13. Update Costing Request state via `frappe.db.set_value`: last_evaluated_on, engine_version_used, mode, formulation_switch_alert.
14. Return structured response dict for the API.

**Critical design note:** The engine reads working values from the Costing Rate Line and Costing Processing Line child tables — not directly from the rate masters. The rate fetcher has already populated those tables. The engine is downstream of the fetcher. This means the engine is always working with snapshotted values.

---

## Part 5 — API Layer

All in `api/costing.py`. All `@frappe.whitelist()`. Pattern: validate permission → validate params → call one service → catch known exceptions → return structured dict. Zero business logic.

---

| Endpoint | Role | Does |
|---|---|---|
| `evaluate(costing_request_name, trigger)` | Costing User | Calls CostingEngine.evaluate(). Returns combinations and breakdown data |
| `get_combinations(costing_request_name)` | Costing User | Returns all current combinations with nested material lines |
| `select_combination(costing_request_name, combination_name)` | Costing User | Sets is_selected. Updates confirmed_ex_factory_cost_per_kg and mode on request |
| `apply_rate_override(costing_request_name, item, working_rate, working_supplier_credit_days, reason)` | Costing User | Updates the Costing Rate Line row for this item. Triggers combination recomputation |
| `apply_processing_override(costing_request_name, working_charge_per_kg, working_freight_per_unit, working_includes_outward_freight, reason)` | Costing User | Updates Costing Processing Line. Triggers recomputation |
| `revert_rate_override(costing_request_name, item)` | Costing User | Sets working values equal to fetched values for this item. Triggers recomputation |
| `revert_all_overrides(costing_request_name)` | Costing User | Resets all working values to fetched values. Full recomputation |
| `create_pending_rates(costing_request_name)` | Costing User | Creates pending Material Rate placeholders for missing/expired items |
| `get_previous_costing(item)` | Costing User | Returns most recent approved CR for this item for prefill |
| `get_cost_breakdown(costing_request_name)` | Costing User | Returns Layer 1 always. Returns Layer 3 only if user has permlevel 1 on Costing Configuration |
| `check_rate_conflict(item, supplier, city, valid_from, valid_to, exclude_name)` | Rate Manager | Overlap check. Returns structured conflict info |
| `auto_expire_rate(rate_name, new_valid_to)` | Rate Manager | Sets valid_to on named Material Rate via frappe.db.set_value |
| `on_material_rate_created(doc, method)` | Hook | Checks if new rate fills gaps in open costings. Sends notification to owners |

**Override recomputation sequence** (used by apply and revert endpoints):

1. Update the Costing Rate Line or Costing Processing Line row.
2. For each Costing Combination linked to this request: re-fetch its material lines, recompute totals using updated working values.
3. Re-run FormulationSelector on updated combination totals.
4. Update rank, delta_pct, status, switch_alert on all combinations via frappe.db.set_value.
5. If a combination is selected: update confirmed_ex_factory_cost_per_kg on the request.
6. Return updated combination data.

---

## Part 6 — Form Layout and UX

---

### 6.1 Costing Request Form — Six Zones

**Zone 1 — Header Fields (standard Frappe)**

Product and Processor side by side. Solids Content % below product. Parameters (production_days and supplier_financing_rate_pct) below processor. Amber CSS class on production_days when `round(production_days, 0) != round(fetched_production_days, 0)`. Same for supplier_financing_rate_pct. Previous costing reference shown as a link when set.

**Zone 2 — Additional Charges (standard Frappe child table)**

Description, Basis, Rate, Amount per kg. Standard child table with Add Row button. Amount per kg computed and shown inline.

**Zone 3 — Action Bar**

```
[ Get Rates ]   [ Create Pending Rates ]

Last evaluated: {datetime}  |  Engine {version}
```

Get Rates always visible. Create Pending Rates visible only after evaluation with missing/expired rates.

**Zone 4 — Rate Lines (standard Frappe child table with toggle)**

The toggle **Show Official Rates** adds/removes the fetched columns from view.

Default view (Official Rates hidden):

```
Item          | City   | Supplier        | Rate to Use | Credit Days | Freshness
Alkyd Resin   | Indore | Raj Chemicals   | ₹87.50      | 30          | ✓ Current
TiO2          | Indore | Asian Pigments  | ₹131.00 ⚠   | 15          | ✓ Current
Catalyst      | Indore | —               | [ Enter ]   | 0           | ✗ Missing
```

Official Rates visible view:

```
Item        | Official | Freshness  | Override  | Credit | Off.Credit | Variance
Alkyd Resin | ₹87.50   | ✓ Current  | ₹87.50    | 30     | 30         | —
TiO2        | ₹124.00  | ✓ Current  | ₹131.00 ⚠ | 15     | 15         | +5.6%
Catalyst    | —        | ✗ Missing  | ₹12.00    | 0      | 0          | —
```

Amber styling on working_rate cell when is_overridden computed true. Variance shown as +X% or -X% in amber/green.

Processing Line shown as a single row below with same toggle pattern.

Summary line below the table:

```
⚠ 1 rate expired  ·  ✗ 1 rate missing  ·  3 formulations affected
```

**Zone 5 — Formulation Comparison Cards (custom HTML section)**

Switch alert (if present) shown above cards:

```
┌─────────────────────────────────────────────────────┐
│  ⚠ FORMULATION SWITCH RECOMMENDED                   │
│  Form-002 costs ₹6.48/kg less than preferred        │
│  Form-001 — a 5.8% difference (threshold: 5%)       │
│  [ Switch to Form-002 ]  [ Keep Form-001 ]          │
└─────────────────────────────────────────────────────┘
```

Each combination card:

```
┌─────────────────────────────────────────────────────┐
│  Form-001  BOM-00123          Rank 1  ★ Preferred   │
│                               READY TO QUOTE  ✓     │
├─────────────────────────────────────────────────────┤
│  Raw Material Cost                      ₹85.77/kg   │
│    2 rates overridden  [ Show detail ▼ ]            │
│  Financing Cost                          ₹0.13/kg   │
│  Processing Cost                        ₹12.60/kg   │
│  Additional Charges                     ₹15.00/kg   │
│  Outward Freight                         ₹3.50/kg   │
│  ───────────────────────────────────────────────    │
│  TOTAL EX-FACTORY COST                 ₹116.90/kg   │
│                                                     │
│                        [ Select This Formulation ]  │
└─────────────────────────────────────────────────────┘
```

Expanded ingredient detail (on Show detail click):

```
│  INGREDIENTS                                        │
│  Alkyd Resin  0.342kg × ₹87.50 ✓        ₹29.93/kg  │
│    Raj Chemicals | 30d credit | 0d financed         │
│  TiO2  0.218kg × ₹131.00 ⚠ overridden  ₹28.56/kg  │
│    (official ₹124.00) | 15d credit | 15d financed   │
│  Solvent  0.440kg × ₹62.00 ✓            ₹27.28/kg  │
│    Petrochem | 45d credit | 0d financed             │
```

Excluded combination card (collapsed):

```
┌─────────────────────────────────────────────────────┐
│  Form-003  BOM-00125    EXCLUDED  +22.4% vs cheapest │
│                              [ Include Anyway ]     │
└─────────────────────────────────────────────────────┘
```

**Zone 6 — Cost Breakdown Panel (custom HTML section)**

Appears after a formulation is selected. Full Layer 1 always. Layer 3 if role permits.

Layer 1 exact layout:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COST BREAKDOWN — Form-001 (BOM-00123)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RAW MATERIAL COST
  Alkyd Resin 70%
    0.342 kg × ₹87.50                  ₹29.93/kg
    Raj Chemicals | Credit: 30d | Lead: 7d | ✓ Current

  TiO2
    0.218 kg × ₹131.00 ⚠ overridden    ₹28.56/kg
    (official rate was ₹124.00 — +5.6%)
    Asian Pigments | Credit: 15d | ✓ Current

  Solvent
    0.440 kg × ₹62.00                  ₹27.28/kg
    Petrochem Ltd | Credit: 45d | ✓ Current

  RM Total                              ₹85.77/kg

FINANCING COST  (12% pa, 30 days production)
  Alkyd Resin   ₹29.93 × (0d/365) × 12%    ₹0.00/kg
    [30d production − 30d supplier credit = 0d]
  TiO2          ₹28.56 × (15d/365) × 12%   ₹0.14/kg
    [30d production − 15d supplier credit = 15d]
  Solvent       ₹27.28 × (0d/365) × 12%    ₹0.00/kg
    [30d production − 45d supplier credit = 0d]
  Financing Total                           ₹0.14/kg

PROCESSING COST
  70% solids × ₹18.00/kg               ₹12.60/kg
  [PC-00012 — ABC Processors]

ADDITIONAL CHARGES
  Alkyd surcharge  (per kg solids)      ₹14.00/kg
  Filtering        (per kg output)       ₹1.00/kg
  Surcharges Total                      ₹15.00/kg

OUTWARD FREIGHT                          ₹3.50/kg

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONFIRMED EX-FACTORY COST              ₹117.01/kg
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Layer 3 (Costing Approver and System Manager only):

```
══════════════════════════════════════════════════
INTERNAL EARNINGS ANALYSIS — CONFIDENTIAL
══════════════════════════════════════════════════

RM FINANCING SPREAD
  Charged at 12% pa. Actual cost 9% pa. Spread = 3% pa.

  Alkyd Resin  ₹29.93 × (0d/365) × 3%    ₹0.00/kg
  TiO2         ₹28.56 × (15d/365) × 3%   ₹0.04/kg
  Solvent      ₹27.28 × (0d/365) × 3%    ₹0.00/kg

  RM Spread per kg                        ₹0.04/kg

Note: Customer credit spread is added in the
Customer Quote (Phase 2).
══════════════════════════════════════════════════
```

---

### 6.2 MD Approval View

When document is in Pending Approval and opened by Costing Approver, an approval summary panel appears above Zone 1:

```
┌─────────────────────────────────────────────────────┐
│  PENDING YOUR APPROVAL                              │
│  Submitted by: Ravi Kumar  |  15 Apr 2025 14:32     │
├─────────────────────────────────────────────────────┤
│  Selected: Form-001 (Rank 1)                        │
│  Confirmed Ex-Factory Cost: ₹117.01/kg              │
│                                                     │
│  Rate Overrides: 2                                  │
│  · TiO2: ₹124.00 → ₹131.00  (+5.6%)                │
│  · Hardener: ₹45.00 → ₹48.00  (+6.7%) ⚠ expired    │
│                                                     │
│  All rates resolved ✓                               │
└─────────────────────────────────────────────────────┘
[ Approve ]    [ Reject ]  ← rejection requires reason
```

Zone 4 (rate lines table) is shown with Official Rates forced visible for the MD. The entire form is read only for the MD — they can see everything but change nothing. Only Approve and Reject are available.

---

### 6.3 costing_request.js Structure

Organise into clearly named sections. Zero business logic.

*Initialisation:*
On form load: fetch `production_days` and `supplier_financing_rate_pct` from Costing Configuration via `frappe.db.get_single_value`. Store as form-level constants for amber comparison.

*Item field:*
- Filter: `has_bom: 1`
- On change: fetch `custom_solids_content_pct` and set `solids_content_pct`. Call `_load_previous_costing()`.

*Processor field:*
- On change: no additional fetch needed (city is only used server-side).

*`_load_previous_costing()`:*
If item is set: call `api/costing.get_previous_costing` with item only. On response: populate preferred_bom, previous_costing_ref, production_days, supplier_financing_rate_pct, additional_charges rows, and rate_lines rows. Show dashboard message with link.

*Parameter fields:*
On production_days or supplier_financing_rate_pct change: compare to stored config constants. If different: add amber CSS class. Show re-evaluation banner.

*Get Rates button:*
Before calling evaluate: check if any rate_lines row has is_overridden computed true. If yes: show override preservation dialog. On user choice: call evaluate with `preserve_overrides` flag accordingly. Disable button, show spinner in combinations_html. On response: `render_combinations()` and `render_cost_breakdown()`. Re-enable button.

*Override preservation dialog:*
List each overridden item with original and working values. Two buttons: Keep My Overrides / Reset to Official.

*Working rate field changes (in rate_lines child table):*
On working_rate or working_supplier_credit_days change: compute is_overridden client-side. Apply/remove amber class. Call `api/costing.apply_rate_override`. On response: `render_combinations()` to update all cards.

*Processing line field changes:*
Same pattern via `api/costing.apply_processing_override`.

*Show Official Rates toggle:*
Toggle visibility of fetched_ columns in rate_lines and processing_lines tables. Toggle forces visible when mode is Pending Approval and user is Costing Approver.

*`render_combinations(combinations)`:*
Clear combinations_html. If formulation_switch_alert: render alert box at top with Switch and Keep buttons. Render combination cards. Preferred card has distinct styling. Excluded cards collapsed. Select button on each non-excluded card.

*Select button click:*
Call `api/costing.select_combination`. On response: update selected_combination and confirmed_ex_factory_cost_per_kg on form. Render cost breakdown.

*`render_cost_breakdown(breakdown)`:*
Clear cost_breakdown_html. Render Layer 1 always. If `frappe.user.has_role(["Costing Approver", "System Manager"])` AND breakdown response contains layer3 data: render Layer 3. Server-side check is authoritative — client-side check is for display only.

*Submit for Approval button:*
Visible only when selected_combination is set and mode is Ready to Quote. Disabled with tooltip if any rate_lines row for selected combination ingredients has rate_freshness Missing and working_rate is 0.

*Create Pending Rates button:*
Visible after evaluation when missing/expired rates exist. Call `api/costing.create_pending_rates`. Show success with count and link to Material Rate list filtered by this Costing Request.

---

## Part 7 — Item Rate History Report

**Type:** Script Report
**Module:** Costing

**Filters:**

| filter | fieldtype | label | reqd |
|---|---|---|---|
| item | Link → Item | Item | Yes |
| city | Link → City | City | No |
| supplier | Link → Supplier | Supplier | No |
| status | Select | All / Current / Expired / Pending | No |
| from_date | Date | From Date | No |
| to_date | Date | To Date | No |

**Columns:** Item, City, Supplier, Rate Type, Ex-Works Rate, Freight per Unit, Delivered Rate, Credit Days, Lead Time Days, Valid From, Valid To, Status (computed), Quotation Ref, Costing Request (when pending placeholder)

**Logic:** Single `frappe.db.get_all` with filters applied. Compute Status in Python: is_active=0 → Pending, is_active=1 and valid_to >= today or null → Current, is_active=1 and valid_to < today → Expired. Sort by valid_from descending.

---

## Part 8 — Workspace

Named `Costing`. Delivered as fixture.

**Shortcuts:** Costing Request, Material Rate, Processing Charge, City, Processor, Costing Configuration, Item Rate History

**Cards:**
- Rate Masters: Material Rate, Processing Charge
- Master Data: City, Processor
- Costing Workflow: Costing Request
- Reports: Item Rate History
- Configuration: Costing Configuration

---

## Part 9 — Tests

All in `tests/costing/`. Use `frappe.tests.utils.FrappeTestCase`. Mock all database calls in unit tests.

**`test_cost_calculator.py`** — zero mocking needed:
- RM line amount
- Financing when supplier credit >= production days → result zero not negative
- Financing with partial supplier credit
- Financing with zero supplier credit
- Processing cost at various solids percentages including 1% and 99%
- Additional charge both bases
- Total cost sum
- Internal earnings with positive spread
- Internal earnings with zero spread (rates equal)
- Internal earnings spread never negative (clamp)

**`test_manual_rate_source.py`** — mock `frappe.db.get_all`:
- Current rate selected over expired
- Cheapest current wins when multiple exist
- Expired fallback when no current
- Missing placeholder when no records
- Confidence score each adjustment
- Batch resolve multiple pairs in one call
- Second best populated correctly

**`test_rate_fetcher.py`** — mock frappe.db calls:
- Preserve overrides mode: fetched values updated, working values unchanged
- Reset mode: working values set to fetched
- New items added to rate_lines when BOM items change
- Override preservation dialog triggered when overrides exist

**`test_formulation_selector.py`** — zero mocking:
- Cheapest gets rank 1
- Above threshold excluded
- Preferred flagged regardless of rank
- Switch alert when preferred above threshold
- No switch alert below threshold
- All same cost all get rank 1
- Single combination rank 1 never excluded
- All excluded — no ranks

**`test_costing_engine.py`** — mock frappe calls:
- Full evaluation produces correct combination count
- Processing cost on solids basis correct
- Combination status from rate freshness
- Switch alert written to request
- Purge deletes material lines before combinations
- No BOM raises descriptive error
- No processor city raises descriptive error
- Working values from rate_lines used not resolver directly
- Recomputation after override reflects in all affected combinations

---

## Part 10 — Build Sequence

Follow exactly. `bench migrate` after each phase. Do not proceed until current phase has zero errors and smoke tests pass.

**Phase 1 — Module skeleton**
Add Costing to modules.txt. Create `costing/__init__.py` with RateConflictError. Add hooks entries. Create role fixtures. Create custom field fixtures. `bench migrate`. Confirm module appears on desk.

**Phase 2 — City and Processor**
DocTypes and empty controllers. Migrate. Create one City and one Processor manually.

**Phase 3 — Material Rate and Processing Charge**
Full controller logic including pending state, validation, conflict detection, auto-expiry. Create Costing Configuration fixture. Migrate. Test pending state and conflict detection manually.

**Phase 4 — Services foundation**
config.py, rate_option.py, base.py, manual_rate_source.py, rate_source_registry.py, cost_calculator.py. Write and run all tests. All must pass before Phase 5.

**Phase 5 — Rate Fetcher and Formulation Selector**
rate_fetcher.py, formulation_selector.py. Write and run tests. All must pass before Phase 6.

**Phase 6 — Costing DocTypes**
Costing Additional Charge, Costing Rate Line, Costing Processing Line, Costing Combination, Costing Material Line, Costing Request. Migrate. Verify on_trash cascade.

**Phase 7 — Costing Engine and API**
costing_engine.py. All API endpoints. Before touching the form: verify full evaluate → select → confirm flow end-to-end using `bench execute` calls.

**Phase 8 — Costing Request JS**
In order: item filter, item/processor change handlers, parameter amber indicators, previous costing prefill, Get Rates button with override dialog, render_combinations, rate override inline editing, render_cost_breakdown, Create Pending Rates, Submit for Approval. Test each piece manually.

**Phase 9 — Report and Workspace**
Item Rate History report. Costing workspace. Migrate. Export all fixtures via `bench export-fixtures`.

**Phase 10 — Final verification**
Run all tests. Full end-to-end workflow: create masters, enter rates (including one conflict test), create costing request, evaluate, see combinations, trigger switch alert, override a rate, verify all formulations update, select formulation, review breakdown, submit, verify before_submit re-fetch, approve as MD, verify document locked. Confirm Layer 3 visible to System Manager only.

---

## Part 11 — Extension Points for Phase 2

When Phase 2 (Customer Quote) is built it will:

- Create a `Customer Quote` DocType linking to an approved Costing Request
- Read `confirmed_ex_factory_cost_per_kg` as the floor
- Add its own child tables: customer credit line (fetched/working pattern), delivery line (fetched/working), packaging line (fetched/working)
- Add `customer_credit_rate_pct` field fetched from Costing Configuration with same override mechanism
- Compute Layer 2 selling price stack on top of the ex-factory floor
- Add Layer 3 customer credit spread section to the internal earnings analysis
- Own its own workflow — salesperson submits, no MD approval required

Nothing in Phase 1 changes. The Costing Request is a stable approved document that Phase 2 reads from. The extension is purely additive.

---

## Part 12 — What Not to Do

- Do not store logic in Server Scripts in the database
- Do not use `frappe.db.sql` where ORM suffices
- Do not call `frappe.get_doc` inside any loop
- Do not use `doc.save()` to update computed fields — use `frappe.db.set_value`
- Do not store `is_overridden` — compute it always
- Do not put business logic in controllers, API endpoints, or JavaScript
- Do not delete Costing Combination or Costing Material Line from anywhere except the engine purge and on_trash
- Do not modify ERPNext core DocType definitions
- Do not use positional arguments in `frappe.db.get_all`
- Do not use any pre-v14 Frappe API
- Do not call `frappe.db.commit()` explicitly
- Do not allow items without active submitted BOMs on Costing Request
- Do not read from rate masters during combination computation — always read from the child table snapshots
- Do not start Phase 2 code until Phase 1 is fully working in production