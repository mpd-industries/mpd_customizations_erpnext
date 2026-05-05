# MPD Costing Engine — Phase 1 Final Architecture
## Ex-Factory Cost Module

---

## Developer Preamble

Before writing a single line of code, read this document in full. Then read the official Frappe v16 documentation. Then implement.

**You must follow Frappe v16 best practices throughout. Do not use any deprecated features. Do not use Server Scripts stored in the database — all logic lives in Python files in the app. Do not use `frappe.db.sql` where the ORM suffices. Do not call `frappe.get_doc` inside loops — use bulk queries. Do not use jQuery where Frappe's form API handles it. Do not hardcode strings that belong in configuration. Every piece of business logic lives in the services layer — never in controllers, never in API endpoints, never in JavaScript. Controllers validate and delegate. API endpoints validate permissions and delegate. JavaScript handles display and user interaction only. Do not use any deprecated Frappe API. Do not access private Frappe internals. Everything is delivered as fixtures so the module is fully portable across environments.**

---

## 1. Scope

This module answers one question: **given a product and a processor, what does it cost MPD to manufacture it ex-factory?**

Nothing else. No customers. No delivery. No packaging. No quotes. Those come later and plug onto the approved ex-factory cost without touching anything built here.

---

## 2. Module Location

Inside the existing `mpd_customizations` app. New module named `costing`. Do not create a new app.

---

## 3. Repository Structure

```
mpd_customizations/
├── modules.txt                         ← add "Costing"
├── mpd_customizations/
│   ├── costing/
│   │   ├── __init__.py
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
        ├── test_costing_engine.py
        └── test_formulation_selector.py
```

---

## 4. hooks.py Additions

Append only. Do not replace existing entries.

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

## 5. Custom Fields on Standard DocTypes

Delivered as fixtures only. Never touch ERPNext core files.

**On Item:**
- `custom_solids_content_pct` — Float — label "Solids Content %" — inserted after description — module: Costing

**On BOM:**
- `custom_formulation_id` — Data — label "Formulation ID" — inserted after item — module: Costing

---

## 6. Roles

Three roles delivered as fixtures.

**Costing User**
The person doing the costing — typically a salesperson or production manager. Can create and manage Costing Requests. Read only on all masters. Cannot see internal earnings analysis.

**Costing Approver**
The MD. Can approve and reject Costing Requests. Can see the internal earnings analysis. Read only on everything else.

**Rate Manager**
Purchase team. Full access to Material Rate, Processing Charge. Read only on Costing Requests.

System Manager has full access to everything by default including internal earnings analysis.

---

## 7. DocType Specifications

---

### 7.1 City

**Type:** Regular
**Naming:** By fieldname — `city_name`
**Track Changes:** No

Fields:

| fieldname | fieldtype | label | reqd | notes |
|---|---|---|---|---|
| city_name | Data | City Name | Yes | Unique. In list view |
| state | Data | State | No | In list view |

Permissions: System Manager and Rate Manager full CRUD. Costing User and Costing Approver read only.

Controller: empty. No logic needed.

---

### 7.2 Processor

**Type:** Regular
**Naming:** By fieldname — `processor_name`
**Track Changes:** Yes

Fields:

| fieldname | fieldtype | label | reqd | notes |
|---|---|---|---|---|
| processor_name | Data | Processor Name | Yes | Unique. In list view |
| city | Link → City | City | Yes | In list view. Used for all rate lookups |
| default_rm_warehouse | Link → Warehouse | Default RM Warehouse | No | For ERPNext stock flows only. Not used in costing |
| notes | Small Text | Notes | No | |

Permissions: same as City.

Controller: empty.

---

### 7.3 Material Rate

The most important master. City-scoped so all processors in the same city share rates. Supports a pending state for placeholder records created before the purchase team has confirmed rates.

**Type:** Regular
**Naming:** `MR-.YYYY.-.#####`
**Track Changes:** Yes
**Is Submittable:** No

Fields in order:

| fieldname | fieldtype | label | reqd | notes |
|---|---|---|---|---|
| item | Link → Item | Item | Yes | In list view |
| item_name | Data | Item Name | No | Fetch from item.item_name. Read only |
| supplier | Link → Supplier | Supplier | No | Optional when pending. Required when activating |
| city | Link → City | City | Yes | In list view |
| costing_request | Link → Costing Request | Costing Request | No | Set when auto-created as pending placeholder |
| section_break_rate | Section Break | Rate | | |
| rate_type | Select | Rate Type | Yes | Options: Ex-Works + Freight\nAll-In Delivered |
| ex_works_rate | Currency | Ex-Works Rate (₹) | No | Shown only when rate_type is Ex-Works + Freight |
| freight_per_unit | Currency | Freight per Unit (₹) | No | Shown only when rate_type is Ex-Works + Freight |
| delivered_rate | Currency | Delivered Rate (₹) | No | Computed when Ex-Works + Freight. Entered directly when All-In Delivered |
| uom | Link → UOM | UOM | Yes | |
| col_break_rate | Column Break | | | |
| credit_days | Int | Supplier Credit Days | No | Default 0. Used in financing cost calculation |
| lead_time_days | Int | Lead Time Days | No | Optional. Informational |
| section_break_validity | Section Break | Validity | | |
| valid_from | Datetime | Valid From | Yes | Cannot be before current datetime for active records |
| valid_to | Datetime | Valid To | No | Auto-set from config when blank on active records |
| col_break_validity | Column Break | | | |
| is_active | Check | Active | No | Default 0. Pending until explicitly activated |
| notes | Small Text | Notes | No | |

Permissions: System Manager and Rate Manager full CRUD. Costing User and Costing Approver read only.

**Controller — validate:**

When `is_active = 0`: skip all validation entirely. Pending records save without any checks.

When `is_active = 1`:
- `supplier` must be set. Hard error if blank.
- `delivered_rate` must be greater than zero. Hard error.
- `credit_days` must be zero or positive. Hard error if negative.
- `valid_from` must be >= `now()`. Hard error. Message: *"Valid From cannot be in the past."*
- If `valid_to` is blank: call `_set_default_valid_to()` which reads `Costing Configuration` and computes end of current month at 23:59:59, end of current quarter at 23:59:59, or `now() + N days` at 23:59:59 depending on config setting.
- If `valid_to` is set: must be after `valid_from`. Hard error.
- If `rate_type` is Ex-Works + Freight: `delivered_rate = ex_works_rate + freight_per_unit`.
- Call `_check_overlap()`.

**`_check_overlap()`:**

Query Material Rate records where `item = this.item`, `supplier = this.supplier`, `city = this.city`, `is_active = 1`, `name != this.name`.

For each result check datetime range overlap: `existing.valid_from < this.valid_to AND existing.valid_to > this.valid_from` treating null valid_to as far future datetime.

If overlap found and `self.flags.get("auto_expire_confirmed")` is True: set `existing.valid_to = this.valid_from - 1 second` using `frappe.db.set_value`. Do not call `existing.save()`.

If overlap found and flag not set: raise `RateConflictError` (custom exception class defined in `costing/__init__.py`) with properties: `conflicting_name`, `conflicting_valid_from`, `conflicting_valid_to`. The API layer catches this specifically and returns structured JSON. Never let it become a generic 500.

**Controller — before_save:**

Always: if `rate_type == "Ex-Works + Freight"`: `delivered_rate = ex_works_rate + freight_per_unit`. This runs even on programmatic saves.

**JS — material_rate.js:**

- On `rate_type` change: `frm.toggle_display(["ex_works_rate", "freight_per_unit"], frm.doc.rate_type === "Ex-Works + Freight")`. Also toggle `delivered_rate` as read-only when Ex-Works + Freight, editable when All-In Delivered.
- On `ex_works_rate` or `freight_per_unit` change: compute and set `delivered_rate` client-side immediately.
- On `valid_from` datepicker change: if date is today set time to `now + 15 seconds`. If future date set time to `00:00:00`.
- On form load when `is_active = 0`: `frm.dashboard.add_comment("warning", "This rate is pending. Fill in supplier, rate, and credit days then check Active to activate.")`.
- On save error when API returns structured `RateConflictError`: show `frappe.confirm` dialog: *"An active rate for [item] from [supplier] in [city] exists until [valid_to]. Expire it and save this new rate?"* On confirm: set flag and re-call `frm.save()`.

---

### 7.4 Processing Charge

**Type:** Regular
**Naming:** `PC-.YYYY.-.#####`
**Track Changes:** Yes

Fields:

| fieldname | fieldtype | label | reqd | notes |
|---|---|---|---|---|
| processor | Link → Processor | Processor | Yes | In list view |
| item | Link → Item | Item (Specific) | No | Item-specific charge. Priority over group |
| item_name | Data | Item Name | No | Fetched. Read only |
| item_group | Link → Item Group | Item Group (Fallback) | No | Used when no item-specific record |
| col_break_1 | Column Break | | | |
| charge_per_kg | Currency | Charge per kg of Solids (₹) | Yes | In list view. Always applied on solids basis |
| includes_outward_freight | Check | Includes Outward Freight | No | Default 0 |
| fg_freight_per_unit | Currency | FG Freight per Unit (₹) | No | Shown only when includes_outward_freight is unchecked |
| section_break_validity | Section Break | Validity | | |
| valid_from | Datetime | Valid From | Yes | |
| valid_to | Datetime | Valid To | No | |
| col_break_validity | Column Break | | | |
| is_active | Check | Active | No | Default 1 |
| notes | Small Text | Notes | No | |

Permissions: System Manager and Rate Manager full CRUD. Costing User and Costing Approver read only.

**Controller — validate:**
- At least one of `item` or `item_group` must be set. Hard error if both blank.
- `charge_per_kg` must be greater than zero.
- `valid_to` must be after `valid_from` if provided.
- No two active records for same `processor + item` (or `processor + item_group`) can overlap. Same overlap logic as Material Rate. Hard error with conflicting record name.

**JS — processing_charge.js:**
- Toggle `fg_freight_per_unit` visibility based on `includes_outward_freight`.

---

### 7.5 Costing Configuration

**Type:** Single Record
**Module:** Costing

Fields:

| fieldname | fieldtype | label | default | permlevel | notes |
|---|---|---|---|---|---|
| engine_version | Data | Engine Version | 1.0.0 | 0 | |
| section_break_production | Section Break | Production Parameters | | | |
| production_days | Int | Production Days | 30 | 0 | Default for new Costing Requests |
| section_break_rates | Section Break | Interest Rates | | | |
| supplier_financing_rate_pct | Float | Supplier Financing Rate % pa | 12 | 0 | Default for new requests |
| actual_cost_of_capital_pct | Float | Actual Cost of Capital % pa | 9 | 1 | Used in internal earnings only. permlevel 1 — System Manager only |
| section_break_formulation | Section Break | Formulation Selection | | | |
| auto_exclusion_threshold_pct | Float | Auto Exclusion Threshold % | 15 | 0 | Formulations above this vs cheapest are auto-excluded |
| formulation_switch_threshold_pct | Float | Formulation Switch Alert Threshold % | 5 | 0 | Alert shown when non-preferred formulation is cheaper by this % |
| section_break_validity | Section Break | Rate Validity | | | |
| default_valid_to | Select | Default Valid To | End of Month | 0 | Options: End of Month\nEnd of Quarter\nCustom Days |
| default_valid_to_days | Int | Default Valid To Days | 30 | 0 | Used only when Custom Days is selected |
| rate_expiry_warning_days | Int | Rate Expiry Warning Days | 30 | 0 | |

`permlevel 1` on `actual_cost_of_capital_pct` means only roles with level 1 read permission see it. Grant level 1 permission to System Manager only in the DocType permissions table.

Permissions: System Manager full access including level 1. All other roles read only at level 0.

**Controller:**
Single function `get_config()` — reads the single record, populates and returns a `CostingConfig` dataclass, cached on `frappe.local` for the request duration.

---

### 7.6 Costing Request

The central document. One per ex-factory evaluation.

**Type:** Regular
**Naming:** `CR-.YYYY.-.#####`
**Is Submittable:** Yes
**Track Changes:** Yes

Fields in order:

| fieldname | fieldtype | label | reqd | notes |
|---|---|---|---|---|
| **Section: Product** | | | | |
| item | Link → Item | Product | Yes | In list view |
| item_name | Data | Product Name | No | Fetched. Read only |
| solids_content_pct | Float | Solids Content % | Yes | Fetched from item.custom_solids_content_pct. Editable |
| col_break_product | Column Break | | | |
| processor | Link → Processor | Processor | Yes | In list view |
| processor_name | Data | Processor Name | No | Fetched. Read only |
| **Section: Parameters** | | | | |
| production_days | Int | Production Days | Yes | Default from config. Editable. Amber when changed from config value |
| col_break_params | Column Break | | | |
| supplier_financing_rate_pct | Float | Supplier Financing Rate % pa | Yes | Default from config. Editable. Amber when changed. Re-evaluation required if changed |
| **Section: Previous Costing** | | | | |
| preferred_bom | Link → BOM | Preferred Formulation | No | Pre-filled from last approved costing for same item + processor. Editable |
| previous_costing_ref | Link → Costing Request | Pre-filled From | No | Read only. Which previous costing was used |
| **Section: Additional Charges** | | | | |
| additional_charges | Table → Costing Additional Charge | Additional Charges | No | |
| **Section: State** | | | | |
| mode | Select | Mode | No | Options: Exploring\nAwaiting Rates\nPartially Costed\nReady to Quote\nPending Approval\nApproved\nRejected. Read only |
| selected_combination | Link → Costing Combination | Selected Formulation | No | Read only |
| confirmed_ex_factory_cost_per_kg | Currency | Confirmed Ex-Factory Cost per kg | No | Read only. Locked on approval |
| last_evaluated_on | Datetime | Last Evaluated On | No | Read only |
| engine_version_used | Data | Engine Version Used | No | Read only |
| **Section: Formulation Alert** | | | | |
| formulation_switch_alert | Small Text | Formulation Alert | No | Read only. Populated by engine when a cheaper formulation exists beyond threshold |
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

**Controller — validate:**
- On submit: `mode` must be `Ready to Quote`. Hard error otherwise.
- `solids_content_pct` must be between 0 and 100 exclusive. Hard error otherwise.
- `production_days` must be positive. Hard error.
- `supplier_financing_rate_pct` must be positive. Hard error.

**Controller — on_submit:**
- Set `mode = "Approved"` using `frappe.db.set_value`.
- Lock `confirmed_ex_factory_cost_per_kg` — it cannot be changed after submission.

**Controller — on_cancel:**
- Set `mode = "Exploring"` using `frappe.db.set_value`.

**Controller — on_trash:**
- `frappe.db.delete("Costing Combination", {"costing_request": self.name})`
- `frappe.db.delete("Costing Material Line", {"costing_request": self.name})`

**JS — costing_request.js:**

Organise into clearly named sections with comments. No business logic.

*On item change:*
- Fetch `item.custom_solids_content_pct` via `frappe.db.get_value` and set `solids_content_pct`.
- Call `_load_previous_costing()`.

*On processor change:*
- Call `_load_previous_costing()`.

*`_load_previous_costing()`*:
- If both item and processor are set: call `api/costing.get_previous_costing` with item and processor.
- On response if found: set `preferred_bom`, `previous_costing_ref`, pre-fill `production_days`, `supplier_financing_rate_pct`, and all `additional_charges` rows.
- Show dashboard message: *"Pre-filled from [CR-XXXXX] dated [date]. Review all values before evaluating."* with link to that document.
- If not found: no action.

*On `production_days` change:*
- Compare to `Costing Configuration.production_days` (fetched once on form load via `frappe.db.get_single_value`).
- If different: add amber CSS class to field. Show re-evaluation banner.

*On `supplier_financing_rate_pct` change:*
- Compare to config value. If different: add amber class. Show re-evaluation banner.

*Get Rates button:*
- Always visible in Exploring, Awaiting Rates, Partially Costed modes.
- On click: disable button, show loading indicator in `combinations_html` area.
- Call `api/costing.evaluate`.
- On success: call `render_combinations(data.combinations)` and `render_cost_breakdown(data.breakdown)`. Re-enable button.
- On error: display error message in combinations area. Re-enable button.

*Create Pending Rates button:*
- Visible when evaluation has run and any combination has missing rates.
- On click: call `api/costing.create_pending_rates`.
- On success: show message with count. Show link to Material Rate list filtered by this costing request.

*`render_combinations(combinations)`*:
- Clear `combinations_html` wrapper.
- If `formulation_switch_alert` is set on the document: render a prominent amber alert box at the top of the combinations panel showing the alert message.
- For each combination render a card showing:
  - Formulation ID and BOM reference
  - Rank badge (1st, 2nd, 3rd) — only for non-excluded combinations
  - Delta % vs cheapest
  - Status badge: Ready to Quote (green) / Indicative — Rates Expired (amber) / Indicative — Rates Missing (red) / Excluded — Too Expensive (grey)
  - Is Preferred badge if `is_preferred` is true
  - Full cost breakdown table: RM / Financing / Processing / Surcharges / Total — all per kg
  - Per-ingredient rate freshness indicators
  - Select button for non-excluded combinations
  - Include Anyway button for excluded combinations
- Preferred combination card has a distinct border style.

*On Select button click:*
- Call `api/costing.select_combination` with combination name.
- On success: update `selected_combination` and `confirmed_ex_factory_cost_per_kg` on the form. Refresh breakdown panel. Show Submit for Approval button.

*Submit for Approval button:*
- Visible only when `selected_combination` is set and `mode == "Ready to Quote"`.
- Uses standard Frappe workflow transition — calls `frappe.client.submit` or the workflow action.

*`render_cost_breakdown(breakdown)`*:
- Clear `cost_breakdown_html` wrapper.
- Render Layer 1 always — full ex-factory cost justification.
- Check role client-side: `frappe.user.has_role(["Costing Approver", "System Manager"])`. If true: render Layer 3 internal earnings analysis. The data for Layer 3 is only present in the response if the server-side role check passed — the client-side check is for display only and is not the security gate.

---

### 7.7 Costing Additional Charge

**Type:** Child of Costing Request
**Module:** Costing

Fields:

| fieldname | fieldtype | label | reqd | notes |
|---|---|---|---|---|
| description | Data | Description | Yes | In list view |
| basis | Select | Basis | Yes | Options: Per kg of Output\nPer kg of Solids. In list view |
| rate | Currency | Rate (₹) | Yes | In list view |
| amount_per_kg | Currency | Amount per kg | No | Read only. Computed. In list view |

Amount computation rules:
- Per kg of Output: `amount_per_kg = rate`
- Per kg of Solids: `amount_per_kg = rate × (solids_content_pct / 100)`

`solids_content_pct` is read from the parent Costing Request. Recomputed in the parent's `validate` method by iterating the child table. Never computed in the child controller directly.

No `is_commission` field. No special flags. These are purely product-level cost surcharges.

---

### 7.8 Costing Combination

One record per BOM per evaluation. Purged and rewritten on every evaluation. Standalone DocType — not a child table — so Costing Material Lines can link to it by document name using a proper foreign key.

**Type:** Regular
**Naming:** `CC-.YYYY.-.#####`
**Track Changes:** No

No delete permission for any role in the permissions table. Deletion only via engine cascade using `frappe.db.delete`.

Fields:

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
| status | Select | Status | No | Options: Ready to Quote\nIndicative — Rates Expired\nIndicative — Rates Missing\nExcluded — Too Expensive |
| is_selected | Check | Selected | No | |
| section_break_refs | Section Break | References | | |
| processing_charge_ref | Data | Processing Charge Used | No | Document name for audit |
| missing_items | Small Text | Missing Rate Items | No | |
| expired_items | Small Text | Expired Rate Items | No | |
| evaluated_on | Datetime | Evaluated On | No | |

---

### 7.9 Costing Material Line

One record per BOM ingredient per combination. Purged and rewritten on every evaluation. Override tracking lives directly on this record — no separate log DocType.

**Type:** Regular
**Naming:** `CML-.YYYY.-.#####`
**Track Changes:** No

No delete permission for any role. Deletion only via engine cascade.

Fields:

| fieldname | fieldtype | label | reqd | notes |
|---|---|---|---|---|
| costing_request | Link → Costing Request | Costing Request | Yes | Denormalised for query performance |
| combination | Link → Costing Combination | Combination | Yes | |
| item | Link → Item | Item | Yes | |
| item_name | Data | Item Name | No | |
| uom | Link → UOM | UOM | No | |
| qty_per_kg_output | Float | Qty per kg Output | No | Precision 6 |
| section_break_rate | Section Break | Rate | | |
| supplier | Link → Supplier | Winning Supplier | No | |
| city | Link → City | City | No | |
| rate_source_ref | Data | Rate Source | No | Material Rate document name |
| rate_freshness | Select | Rate Freshness | No | Options: Current\nExpired\nMissing |
| supplier_credit_days | Int | Supplier Credit Days | No | |
| lead_time_days | Int | Lead Time Days | No | Optional |
| delivered_rate | Currency | Delivered Rate | No | |
| col_break_rate | Column Break | | | |
| net_financed_days | Int | Net Financed Days | No | max(0, production_days + 0 - supplier_credit_days). Customer credit days = 0 at ex-factory stage |
| financing_cost_per_kg | Currency | Financing Cost per kg | No | |
| amount_per_kg | Currency | Amount per kg | No | qty_per_kg_output × effective_rate |
| confidence_score | Float | Confidence Score | No | 0-100 |
| section_break_override | Section Break | Manual Override | | |
| is_overridden | Check | Manually Overridden | No | |
| original_rate | Currency | Original Rate | No | Rate from resolver before override |
| override_rate | Currency | Override Rate | No | |
| override_reason | Small Text | Override Reason | No | |
| overridden_by | Link → User | Overridden By | No | |
| overridden_on | Datetime | Overridden On | No | |
| effective_rate | Currency | Effective Rate | No | override_rate if is_overridden else delivered_rate |

**Note on net_financed_days at ex-factory stage:** customer_credit_days is always zero here because we are computing ex-factory cost only. The formula is `max(0, production_days - supplier_credit_days)`. Customer credit days will be added in the quotation flow later as an additive layer on top of this cost. This is intentional and architecturally correct.

---

## 8. Services Layer

All business logic. Nothing else goes here. No Frappe form dependencies. Every service is independently testable.

---

### 8.1 `services/config.py`

Define `CostingConfig` as a Python `dataclass` with fields mirroring every field in Costing Configuration. Include `actual_cost_of_capital_pct`.

Define `get_config() -> CostingConfig`:
- Check `frappe.local` for cached instance under key `costing_config`.
- If not cached: read using `frappe.get_single("Costing Configuration")`, populate dataclass, store on `frappe.local.costing_config`, return.
- If cached: return cached instance.

This is called once per request at the start of any engine run. Configuration is never read mid-computation.

---

### 8.2 `services/rate_option.py`

Define `RateOption` as a Python `dataclass`:

Fields:
- `item` — str
- `city` — str
- `supplier` — str or None
- `rate_source_ref` — str or None
- `delivered_rate` — float
- `supplier_credit_days` — int, default 0
- `lead_time_days` — int or None, default None
- `valid_from` — datetime
- `valid_to` — datetime or None
- `rate_freshness` — str — one of: Current / Expired / Missing
- `confidence_score` — float, default 50.0
- `second_best_supplier` — str or None, default None
- `second_best_rate` — float, default 0.0

No methods. Pure data carrier.

---

### 8.3 `services/sources/base.py`

Abstract base class `BaseRateSource` using Python `abc`:

Class attributes:
- `source_type: str` — set on each subclass
- `priority: int` — set on each subclass. Lower = checked first.

Abstract methods:
- `can_resolve(item: str, city: str, pricing_dt: datetime) -> bool`
- `resolve(item: str, city: str, pricing_dt: datetime) -> list[RateOption]`

Concrete method with default implementation:
- `batch_resolve(pairs: list[tuple[str, str]], pricing_dt: datetime) -> dict[tuple, list[RateOption]]`
  Default calls `resolve()` per pair for pairs where `can_resolve()` is True. Subclasses override for efficiency.

---

### 8.4 `services/sources/manual_rate_source.py`

`ManualRateSource(BaseRateSource)`:
- `source_type = "Manual"`
- `priority = 10`

**`batch_resolve` — single SQL fetch for all pairs:**

Collect all unique items and cities from the pairs. Execute one `frappe.db.get_all` against `Material Rate` with `item` in the items list and `city` in the cities list. Fetch fields: name, item, city, supplier, delivered_rate, supplier_credit_days, lead_time_days, valid_from, valid_to, is_active, rate_type, ex_works_rate, supplier_quotation_ref.

Group results in Python by `(item, city)` key using a defaultdict.

For each pair in the input list:
- Get the group for that `(item, city)`.
- Separate into `current` — `is_active = 1` and `valid_from <= pricing_dt` and (`valid_to` is None or `valid_to >= pricing_dt`).
- And `expired` — `is_active = 1` and `valid_to` is not None and `valid_to < pricing_dt`.
- Sort `current` by `delivered_rate` ascending.
- Sort `expired` by `valid_from` descending.
- Best option: `current[0]` if current exists, else `expired[0]` if expired exists, else a Missing placeholder.
- Set `rate_freshness` accordingly.
- Set `second_best_supplier` and `second_best_rate` from the second item in the list if available.
- Compute `confidence_score` — start at 50, +20 if `supplier_quotation_ref` is set, +20 if `valid_from >= pricing_dt - 30 days`, +10 if supplier has 3+ historical records for this item and city (count from the already-fetched results — no extra query), -30 if `rate_type == "All-In Delivered"` with no ex_works breakup. Clamp 0 to 100.

Return dict keyed by `(item, city)` → `RateOption`.

For pairs with no records at all: return a `RateOption` with `rate_freshness = "Missing"`, `delivered_rate = 0`, `supplier = None`, `rate_source_ref = None`, `confidence_score = 0`.

---

### 8.5 `services/rate_source_registry.py`

`RateSourceRegistry`:
- Constructor takes `list[BaseRateSource]`. Sorts by `priority` ascending.
- `batch_resolve(pairs, pricing_dt) -> dict[tuple, RateOption]`:
  - Call `batch_resolve` on every registered source.
  - Merge results per pair — combine lists from all sources.
  - Sort merged list per pair: Current before Expired before Missing, then by `delivered_rate` ascending within same freshness tier.
  - Best option is index 0. Set `second_best_supplier` and `second_best_rate` from index 1 if it exists.
  - Return dict keyed by `(item, city)` → best `RateOption`.

Factory function `get_default_registry() -> RateSourceRegistry`:
- Returns `RateSourceRegistry(sources=[ManualRateSource()])`.
- Future rate sources are added here only. Nothing else changes.

---

### 8.6 `services/cost_calculator.py`

Pure functions. Zero Frappe imports. Zero database calls. All inputs are plain Python primitives or simple dicts. Every function has a docstring with its formula. Fully testable without any Frappe context.

**Functions:**

`compute_rm_line_amount(qty_per_kg_output: float, effective_rate: float) -> float`
Returns `qty_per_kg_output × effective_rate`.

`compute_financing_cost_for_line(amount_per_kg: float, production_days: int, supplier_credit_days: int, financing_rate_pct: float) -> float`
`net_financed_days = max(0, production_days - supplier_credit_days)`
Returns `amount_per_kg × (net_financed_days / 365) × (financing_rate_pct / 100)`.
Note: at ex-factory stage customer_credit_days is always zero. This parameter is intentionally absent from this function. It will be added in the quotation flow service layer.

`compute_processing_cost(solids_content_pct: float, charge_per_kg: float) -> float`
Returns `(solids_content_pct / 100) × charge_per_kg`.

`compute_additional_charge_amount(rate: float, basis: str, solids_content_pct: float) -> float`
`basis == "Per kg of Output"`: returns `rate`.
`basis == "Per kg of Solids"`: returns `rate × (solids_content_pct / 100)`.
Raises `ValueError` if basis is unrecognised.

`compute_total_cost(rm_cost: float, financing_cost: float, processing_cost: float, additional_charges: float, outward_freight: float) -> float`
Returns sum of all components.

`compute_internal_earnings(material_lines: list[dict], total_cost_per_kg: float, actual_cost_of_capital_pct: float, supplier_financing_rate_pct: float) -> dict`
RM financing spread per line: `amount_per_kg × (net_financed_days / 365) × spread_pct` where `spread_pct = supplier_financing_rate_pct - actual_cost_of_capital_pct`.
Returns dict: `rm_spread_per_kg`, `rm_spread_breakdown` (list per line), `total_spread_per_kg`.
Note: customer credit spread is computed in the quotation flow, not here.

---

### 8.7 `services/formulation_selector.py`

`FormulationSelector`:

Constructor takes `CostingConfig`.

`select(combinations: list[dict], preferred_bom: str) -> dict`:

Each input dict has: `bom`, `formulation_id`, `total_cost_per_kg`, `status`, `processing_charge_ref`, `packaging_cost_ref`, `missing_items`, `expired_items`.

Logic:
1. Find `min_cost` as the minimum `total_cost_per_kg` across all combinations regardless of status. Use all combinations including indicative ones — a combination with an expired rate still has a cost figure.
2. For each combination compute `delta_pct = (total_cost_per_kg - min_cost) / min_cost × 100` if min_cost > 0.
3. If `delta_pct > config.auto_exclusion_threshold_pct`: set status to `"Excluded — Too Expensive"`.
4. For non-excluded combinations rank by `total_cost_per_kg` ascending. Assign `rank` starting at 1.
5. Set `is_preferred = True` on the combination matching `preferred_bom`. Preferred can be any rank including excluded — mark it regardless.
6. Check formulation switch condition: if the preferred combination exists and is not rank 1, and if `(preferred_cost - rank1_cost) / rank1_cost × 100 > config.formulation_switch_threshold_pct`: generate `switch_alert` message: `"Formulation {rank1_formulation_id} costs ₹{diff}/kg less than your preferred Formulation {preferred_formulation_id} — a {delta:.1f}% difference. Consider switching."`.
7. Return dict: `included` list, `excluded` list, `cheapest_cost`, `threshold_applied`, `switch_alert` (None if no alert).

---

### 8.8 `services/costing_engine.py`

`CostingEngine`:

Constructor takes `RateSourceRegistry` and `CostingConfig`.

**`evaluate(costing_request_name: str, trigger: str) -> dict`:**

Execute in this exact order:

**1. Load and validate the Costing Request:**
`frappe.get_doc("Costing Request", costing_request_name)`. Validate `item`, `processor`, `solids_content_pct`, `production_days`, `supplier_financing_rate_pct` are all present and valid. Raise descriptive `frappe.ValidationError` for any issue.

**2. Fetch processor city:**
`frappe.db.get_value("Processor", cr.processor, "city")`. Store as `processor_city`. Raise error if processor has no city.

**3. Fetch active submitted BOMs:**
`frappe.get_all("BOM", filters={"item": cr.item, "is_active": 1, "docstatus": 1}, fields=["name", "quantity", "custom_formulation_id"])`. Raise descriptive error if none found.

**4. Fetch BOM items for all BOMs in one query:**
`frappe.get_all("BOM Item", filters={"parent": ["in", bom_names]}, fields=["parent", "item_code", "item_name", "qty", "uom"])`. Group by `parent` in Python using a defaultdict. Never query BOM items per BOM in a loop.

**5. Collect unique (item, city) pairs:**
From all BOM items across all BOMs. City is `processor_city` for all pairs.

**6. Fetch Processing Charge:**
Query `frappe.get_all("Processing Charge", filters={"processor": cr.processor, "item": cr.item, "is_active": 1, "valid_from": ["<=", now()], ["or", "valid_to": [">=", now()], "valid_to": ""]}, fields=[...])`. If empty, retry with `item_group` matching the item's item_group fetched via `frappe.db.get_value("Item", cr.item, "item_group")`. If still empty: store `None` — processing charge is missing.

**7. Batch resolve rates:**
`self._registry.batch_resolve(pairs, frappe.utils.now_datetime())`.

**8. For each BOM compute the combination result:**

For each BOM:
- For each BOM item: `qty_per_kg = item.qty / bom.quantity`. Get `RateOption` from rate map for `(item.item_code, processor_city)`.
- `effective_rate = rate_option.delivered_rate`
- `amount_per_kg = compute_rm_line_amount(qty_per_kg, effective_rate)`
- `net_financed_days = max(0, cr.production_days - rate_option.supplier_credit_days)`
- `line_financing = compute_financing_cost_for_line(amount_per_kg, cr.production_days, rate_option.supplier_credit_days, cr.supplier_financing_rate_pct)`
- Accumulate `rm_cost_per_kg`, `financing_cost_per_kg`

- If processing charge found: `processing_cost_per_kg = compute_processing_cost(cr.solids_content_pct, pc.charge_per_kg)`
- Else: `processing_cost_per_kg = 0`

- `additional_charges_per_kg = sum(compute_additional_charge_amount(line.rate, line.basis, cr.solids_content_pct) for line in cr.additional_charges)`

- `outward_freight_per_kg = 0 if pc.includes_outward_freight else pc.fg_freight_per_unit` (or 0 if no processing charge)

- `total_cost_per_kg = compute_total_cost(rm_cost, financing_cost, processing_cost, additional_charges, outward_freight)`

Determine status:
- Any ingredient with `rate_freshness == "Missing"` OR processing charge is None → `"Indicative — Rates Missing"`
- Elif any ingredient with `rate_freshness == "Expired"` → `"Indicative — Rates Expired"`
- Else → `"Ready to Quote"`

Build per-ingredient line dicts for material line writing.

**9. Run FormulationSelector:**
`FormulationSelector(self._config).select(all_combination_results, cr.preferred_bom)`.
Get `included`, `excluded`, ranked combinations, `switch_alert`.

**10. Purge old data:**
`frappe.db.delete("Costing Material Line", {"costing_request": costing_request_name})`
`frappe.db.delete("Costing Combination", {"costing_request": costing_request_name})`
Purge material lines before combinations because of the foreign key from material line to combination.

**11. Write Costing Combination records:**
For each combination use `frappe.get_doc({...}).insert(ignore_permissions=True)`. Do not use raw SQL insert — use the document API so the naming series applies and hooks fire correctly.

**12. Write Costing Material Line records:**
For each ingredient in each combination. Set all fields including: `is_overridden = 0`, `original_rate = delivered_rate`, `effective_rate = delivered_rate`, `net_financed_days`, `financing_cost_per_kg`, `confidence_score`.

**13. Update Costing Request state:**
Use `frappe.db.set_value` for these fields — do not call `cr.save()`:
- `last_evaluated_on = now()`
- `engine_version_used = config.engine_version`
- `formulation_switch_alert = switch_alert or ""`
- `mode` = determined as follows: if any combination is `Ready to Quote` → `"Ready to Quote"`. Elif any is Indicative → `"Partially Costed"`. Else → `"Awaiting Rates"`.

**14. Assemble and return response dict:**

```
{
  "combinations": [...],   ← for render_combinations()
  "breakdown": {...},      ← for render_cost_breakdown()
  "mode": "...",
  "switch_alert": "..." or null
}
```

The `breakdown` dict contains Layer 1 data always. Contains Layer 3 (internal earnings) only if `frappe.has_permission("Costing Configuration", ptype="read", permLevel=1)` returns True for the current user — i.e. only System Manager.

---

## 9. API Layer

All endpoints in `api/costing.py`. All decorated with `@frappe.whitelist()`. All follow this pattern:

1. Validate calling user has required role via `frappe.has_permission`.
2. Validate required parameters.
3. Call exactly one service or perform one simple data operation.
4. Catch `RateConflictError` and other known exceptions — return structured JSON, never let a traceback reach the client.
5. Return structured dict.

Zero business logic in this file.

---

**`evaluate(costing_request_name, trigger="manual")`**
Role: Costing User.
Calls `CostingEngine(get_default_registry(), get_config()).evaluate(costing_request_name, trigger)`.
Returns engine response dict.

**`get_combinations(costing_request_name)`**
Role: Costing User.
`frappe.get_all("Costing Combination", filters={"costing_request": costing_request_name}, fields=[all fields], order_by="rank asc")`.
For each combination fetch its material lines from `Costing Material Line`.
Returns list of combination dicts with nested material lines.

**`select_combination(costing_request_name, combination_name)`**
Role: Costing User.
Sets `is_selected = 1` on named combination. Sets `is_selected = 0` on all others for this request.
Gets `total_cost_per_kg` from the selected combination.
Sets `confirmed_ex_factory_cost_per_kg`, `selected_combination`, `mode = "Ready to Quote"` on the Costing Request via `frappe.db.set_value`.
Returns updated cost figure.

**`apply_rate_override(line_name, override_rate, reason="")`**
Role: Costing User.
Loads Costing Material Line. Validates `override_rate > 0`.
Sets override fields. Recomputes `amount_per_kg` and `financing_cost_per_kg` using cost_calculator functions.
Recomputes parent combination's `rm_cost_per_kg`, `financing_cost_per_kg`, `total_cost_per_kg` by summing all its material lines via `frappe.get_all`.
Updates combination via `frappe.db.set_value`.
If this combination is the selected one: update `confirmed_ex_factory_cost_per_kg` on the Costing Request.
Returns updated combination totals.

**`revert_rate_override(line_name)`**
Role: Costing User.
Clears all override fields on the material line. Restores `effective_rate = delivered_rate`. Recomputes amounts and combination totals. Returns updated totals.

**`create_pending_rates(costing_request_name)`**
Role: Costing User.
Fetches all Costing Material Lines for this request where `rate_freshness != "Current"`.
For each unique `(item, city)` pair that does not already have a pending (is_active = 0) Material Rate linked to this costing request: create a new Material Rate with `is_active = 0`, `item`, `city`, `costing_request = costing_request_name`, `rate_type = "All-In Delivered"`, `valid_from = now()`.
Returns count created.

**`get_previous_costing(item, processor)`**
Role: Costing User.
Queries for the most recent approved Costing Request with `item = item` and `processor = processor` and `docstatus = 1`.
If found: returns `preferred_bom`, `previous_costing_ref`, `production_days`, `supplier_financing_rate_pct`, and `additional_charges` rows for pre-filling.
If not found: returns null.

**`get_cost_breakdown(costing_request_name)`**
Role: Costing User.
Loads selected combination and its material lines.
Assembles Layer 1 breakdown dict.
If `frappe.has_permission("Costing Configuration", ptype="read", permLevel=1)`: assembles Layer 3 using `cost_calculator.compute_internal_earnings` and appends to response.
Returns breakdown dict.

**`on_material_rate_created(doc, method)`**
Called via doc_events hook.
Checks if `doc.item` and `doc.city` appear in any Costing Material Line for an open Costing Request with `rate_freshness = "Missing"`.
If found: creates a Frappe notification to the owner of that Costing Request: *"A rate has been entered for [item] in [city]. Your costing [CR-XXXXX] may now be evaluatable."*

---

## 10. Cost Breakdown Panel — Layer Specifications

---

### Layer 1 — Ex-Factory Cost Justification (all roles)

```
RAW MATERIAL COST
  {item_name}
    {qty_per_kg} {uom} × ₹{delivered_rate}     ₹{amount_per_kg}/kg
    Supplier: {supplier} | Credit: {days}d
    Rate: [Current ✓] / [Expired ⚠] / [Missing ✗]
    [Overridden: original ₹{original} → ₹{override_rate}]
  ...
  RM Total                                        ₹{total}/kg

FINANCING COST  ({financing_rate}% pa)
  {item_name}
    ₹{amount} × ({net_days}d / 365) × {rate}%    ₹{financing}/kg
    [{production_days}d production − {credit_days}d supplier credit]
  ...
  Financing Total                                 ₹{total}/kg

PROCESSING COST
  {solids_pct}% solids × ₹{charge_per_kg}/kg     ₹{total}/kg
  [{processing_charge_ref}]

ADDITIONAL CHARGES
  {description}  [{basis}]                        ₹{amount}/kg
  ...
  Surcharges Total                                ₹{total}/kg

OUTWARD FREIGHT                                   ₹{total}/kg

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONFIRMED EX-FACTORY COST                        ₹{total}/kg
```

---

### Layer 3 — Internal Earnings (Costing Approver and System Manager only)

Never present in the API response for other roles. Never rendered for other roles.

```
══════════════════════════════════════════════
INTERNAL EARNINGS ANALYSIS — CONFIDENTIAL
══════════════════════════════════════════════

RM FINANCING SPREAD
  Charged at {supplier_rate}% pa
  Actual cost {actual_rate}% pa
  Spread = {spread}% pa

  {item_name}
    ₹{amount} × ({net_days}d/365) × {spread}%    ₹{spread}/kg
  ...
  RM Spread per kg                               ₹{total}/kg

Note: Customer credit spread will appear here
when quotation flow is added.

══════════════════════════════════════════════
```

The note is intentional — it tells the MD why customer credit spread is not shown here and where it will appear. This avoids confusion when the quotation flow is added later.

---

## 11. Formulation Switch Alert

When `FormulationSelector.select()` returns a non-null `switch_alert`:

The engine stores it in `costing_request.formulation_switch_alert` via `frappe.db.set_value`.

On the form the JS renders a distinct amber alert box at the top of the combinations panel:

```
⚠ FORMULATION SWITCH RECOMMENDED

Formulation B (Form-002) costs ₹6.48/kg less than your
preferred Formulation A (Form-001) — a 5.8% difference.

This exceeds the configured switch threshold of 5%.
Consider selecting Formulation B for this costing.

[Select Formulation B]  [Keep Formulation A]
```

The MD sees the same alert on the approval form. It is not a block — it is information. The approver can approve either formulation. But they cannot ignore the alert — it is prominently displayed.

When the alert is dismissed (either button clicked) the alert is cleared on the form but remains in `formulation_switch_alert` on the document for audit purposes.

---

## 12. Item Rate History Report

**Type:** Script Report
**Module:** Costing
**Roles:** Costing User, Rate Manager, Costing Approver, System Manager

**Filters:**

| filter | fieldtype | label | reqd |
|---|---|---|---|
| item | Link → Item | Item | Yes |
| city | Link → City | City | No |
| supplier | Link → Supplier | Supplier | No |
| status | Select | Status — All / Current / Expired / Pending | No |
| from_date | Date | From Date | No |
| to_date | Date | To Date | No |

**Columns:**

Item, City, Supplier, Rate Type, Ex-Works Rate, Freight per Unit, Delivered Rate, Credit Days, Lead Time Days, Valid From, Valid To, Status (computed), Quotation Ref, Costing Request (when auto-created as pending)

**Report logic:**
Single `frappe.db.get_all` query with all filters applied. Compute Status in Python: if `is_active = 0` → Pending; if `is_active = 1` and `valid_to` >= today or null → Current; if `is_active = 1` and `valid_to` < today → Expired. Sort by `valid_from` descending. Standard Frappe report return format.

---

## 13. Workspace

Delivered as fixture. Named `Costing`.

**Shortcuts:**
Costing Request, Material Rate, Processing Charge, City, Processor, Costing Configuration, Item Rate History

**Cards:**

*Rate Masters:* Material Rate, Processing Charge

*Master Data:* City, Processor

*Costing Workflow:* Costing Request

*Reports:* Item Rate History

*Configuration:* Costing Configuration

---

## 14. Tests

All in `tests/costing/`. Use `frappe.tests.utils.FrappeTestCase`. Mock all database calls in unit tests. No live database required for service tests.

**`test_cost_calculator.py`** — pure Python, zero mocking needed:
- RM line amount basic multiplication
- Financing cost when supplier credit days exceed production days — result must be zero not negative
- Financing cost with partial supplier credit
- Financing cost with zero supplier credit days
- Processing cost at various solids percentages including edge cases 1% and 99%
- Additional charge both bases
- Total cost sum
- Internal earnings spread — positive spread
- Internal earnings spread — zero spread when rates equal
- Internal earnings spread — negative spread impossible (clamp at zero)

**`test_manual_rate_source.py`** — mock `frappe.db.get_all`:
- Current rate selected over expired
- Cheapest current rate wins when multiple current rates exist
- Expired rate used as fallback when no current rate
- Missing placeholder returned when no records at all
- Confidence score: each adjustment applied correctly
- Batch resolve: multiple (item, city) pairs resolved in one call
- Second best supplier populated correctly

**`test_formulation_selector.py`** — pure Python, zero mocking:
- Cheapest gets rank 1
- Above threshold gets excluded
- Preferred flagged regardless of rank
- Switch alert generated when preferred is more expensive than threshold
- Switch alert not generated when difference is below threshold
- All combinations at same cost all get rank 1
- Single combination always rank 1
- All combinations excluded — no ranks assigned

**`test_costing_engine.py`** — mock `frappe.get_doc`, `frappe.get_all`, `frappe.db.delete`, registry `batch_resolve`, and `frappe.get_doc({...}).insert`:
- Full evaluation produces correct number of combinations
- Processing cost applied on solids basis correctly
- Combination status set correctly from rate freshness
- Switch alert written to Costing Request
- Purge step deletes material lines before combinations
- Missing BOM raises descriptive error
- Missing processor city raises descriptive error

---

## 15. Build Sequence

Follow exactly. Run `bench migrate` after each phase. Do not start the next phase until the current phase has zero errors and basic smoke testing passes.

**Phase 1 — Module skeleton**
Add Costing to modules.txt. Create `costing/__init__.py`. Define `RateConflictError` in it. Add hooks entries. Create role fixtures. Create custom field fixtures. Run `bench migrate`. Confirm module appears on desk.

**Phase 2 — City and Processor**
Create DocTypes, controllers, migrate. Create one City and one Processor manually. Confirm forms work and linking is correct.

**Phase 3 — Material Rate and Processing Charge**
Create DocTypes with full controller logic. Create Costing Configuration with fixture default. Run `bench migrate`. Test pending state — save with is_active = 0, confirm validation skipped. Activate and confirm validation runs. Test conflict detection by creating two overlapping rates.

**Phase 4 — Services foundation**
`config.py`, `rate_option.py`, `sources/base.py`, `sources/manual_rate_source.py`, `rate_source_registry.py`, `cost_calculator.py`. Write all tests for these files. Run all tests. All must pass before proceeding.

**Phase 5 — FormulationSelector and CostingEngine**
`formulation_selector.py`, `costing_engine.py`. Write all tests. All must pass before proceeding.

**Phase 6 — Costing DocTypes**
Costing Additional Charge, Costing Combination, Costing Material Line, Costing Request. Migrate. Verify on_trash cascade works by creating and deleting a test Costing Request.

**Phase 7 — API and end-to-end test**
All endpoints in `api/costing.py`. Before touching the form: verify a full evaluate → select → confirm flow works end-to-end using `bench execute` calls directly against the API functions.

**Phase 8 — Costing Request JS**
Implement `costing_request.js` in order: item/processor change handlers, parameter change amber indicators, Get Rates button, `render_combinations`, formulation switch alert rendering, Select button, `render_cost_breakdown`, Create Pending Rates button, Submit for Approval. Test each piece manually.

**Phase 9 — Report and Workspace**
Item Rate History report. Costing workspace. Migrate. Export all fixtures using `bench export-fixtures`.

**Phase 10 — Final verification**
Run all tests. Run `bench migrate`. Confirm full workflow end-to-end: create masters, enter rates, create costing request, evaluate, see combinations, get switch alert if applicable, select formulation, review breakdown, submit for approval, approve. Confirm internal earnings visible to System Manager only.

---

## 16. What This Architecture Does Not Build

These are explicitly out of scope and have clean attachment points for later:

- Customer, customer address, customer city — will be on Customer Quote
- Delivery Rate and delivery charge — will be on Customer Quote
- Packaging Cost and packaging type — will be on Customer Quote
- Customer credit days and credit cost (16% pa) — will be computed in Customer Quote and added to Layer 2
- MPD cost per kg — will be on Customer Quote
- Suggested selling price and total amount — will be on Customer Quote
- Layer 2 of the cost breakdown panel — will be rendered on Customer Quote
- Layer 3 customer credit spread section — will be added to Customer Quote's earnings analysis

When the Customer Quote is built it will link to an approved Costing Request, read `confirmed_ex_factory_cost_per_kg` as its floor, and add all customer-specific costs on top. Nothing in this architecture needs to change for that to work.

---

## 17. What Not to Do

- Do not store logic in Server Scripts in the database
- Do not use `frappe.db.sql` where the ORM suffices
- Do not call `frappe.get_doc` inside any loop
- Do not use `doc.save()` to update computed fields on related documents — use `frappe.db.set_value`
- Do not put business logic in DocType controllers
- Do not put business logic in API endpoints
- Do not put business logic in JavaScript
- Do not delete Costing Combination or Costing Material Line records from anywhere except the engine's purge step and the on_trash cascade
- Do not modify ERPNext core DocType definitions
- Do not use positional arguments in `frappe.db.get_all`
- Do not use any pre-v14 Frappe API
- Do not call `frappe.db.commit()` explicitly
- Do not assume field order in `frappe.db.get_all` results — always access by key
- Do not write Phase 2 code before Phase 1 is verified working