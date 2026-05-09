# Costing Module Documentation

This document explains what the `costing` module does, how data flows through it, what each major component is responsible for, and the user/product requirements (PRD) that can be inferred from the current implementation.

## 1) What This Module Solves

The module calculates **ex-factory cost per kg** for a product by combining:

- Raw material costs (from BOM lines + item-city material rates)
- Financing impact of supplier credit vs production cycle
- Processing charges (item-specific or item-group fallback)
- Additional charges (per kg output or per kg solids)
- Optional outward freight
- Scrap/byproduct credits (negative contribution)

It supports comparing multiple BOM formulations, ranking them, selecting one, and syncing status + confirmed price back to the originating sales request (`Pricing Request`).

---

## 2) Key Business Objects (DocTypes)

### Core transaction docs

- `Pricing Request`
  - Sales-side request (`product`, `city`, `quantity_kg`, `priority`, `status`)
  - Auto-creates linked `Pricing Calculation` on insert
  - Receives synced status and confirmed price from calculation

- `Pricing Calculation`
  - Costing workbench for a request
  - Holds parameters (solids, production days, financing rate), rate lines, scrap lines, processing lines, additional charges
  - Stores generated `Costing Combination` records and selected combination
  - Main state machine for the costing workflow

### Computed/result docs

- `Costing Combination`
  - One evaluated BOM option with computed breakdown:
    - RM cost, financing cost, processing cost, additional charges, outward freight, total cost
    - rank, delta %, status, selected flag

- `Costing Material Line`
  - Ingredient-level details per combination
  - Includes raw material and scrap/byproduct rows

### Master/reference docs

- `Material Rate`
  - Official purchase rate by `item + supplier + city + validity`
  - Computes and stores `rate_60d_equivalent` (credit-normalized)
  - Handles overlap validation on submit

- `Processing Charge`
  - Processing charge by processor + item (or item-group fallback)
  - Includes outward freight flag and value
  - Enforces validity overlap checks

- `Costing Configuration` (singleton)
  - Global defaults and engine knobs:
    - production days
    - financing rates
    - exclusion threshold
    - formulation switch threshold
    - rate expiry warning window

- `Pending Rate Item`
  - Queue for missing rates that purchase/rate team needs to fill
  - Created from calculations in `Awaiting Rates`

---

## 3) Main Backend Entry Points (`api/costing.py`)

Whitelisted APIs used by UI:

- `evaluate(pricing_calculation_name, trigger="manual")`
  - Permission check
  - Builds `CostingEngine`
  - Runs full fetch + evaluate + persist cycle

- `get_combinations(pricing_calculation_name)`
  - Returns combinations and nested material lines for UI cards

- `select_combination(pricing_calculation_name, combination_name)`
  - Marks one combination selected
  - Updates `Pricing Calculation.confirmed_ex_factory_cost_per_kg`
  - Updates calculation mode (if ready/indicative status)
  - Syncs confirmed price + total to linked `Pricing Request`

- Override APIs:
  - `apply_rate_override(...)`
  - `apply_processing_override(...)`
  - `revert_rate_override(...)`
  - `revert_all_overrides(...)`
  - All call `_recompute_combinations(...)` after changing working values

- `create_pending_rates(pricing_calculation_name)`
  - Creates `Pending Rate Item` rows for lines with `Missing` or `Expired` freshness

- `get_cost_breakdown(pricing_calculation_name)`
  - Returns layer-1 visible costing structure
  - Returns layer-3 internal earnings spread only for privileged roles

- Material rate helper APIs:
  - `check_rate_conflict(...)`
  - `auto_expire_rate(...)`

Hook helper in same file:

- `on_material_rate_submitted(...)`
  - Clears pending items and realtime-notifies open calculations to re-evaluate

---

## 4) End-to-End Data Flow (Current Active Flow)

## A. Request creation

1. User creates `Pricing Request`.
2. `after_insert` in `pricing_request.py` auto-creates `Pricing Calculation`.
3. Defaults are loaded from `Costing Configuration`.
4. Optional prefill from previous approved calculation (same product + city):
   - preferred BOM
   - production/financing parameters
   - additional charges

## B. Get Rates / Evaluate

1. UI calls `costing.evaluate`.
2. `CostingEngine.evaluate` validates required fields:
   - product/item
   - solids %
   - city
   - BOM existence
   - processor-city consistency (if processor set)
3. `RateFetcher.fetch`:
   - Collects BOM items (excluding scrap) and resolves best rates per `(item, city)` using registry sources
   - Updates/creates `rate_lines` with fetched + working values
   - Preserves manual overrides if requested
   - Syncs scrap lines from BOM scrap table (manual scrap rate entry)
   - Resolves processing charge
4. Engine computes each BOM combination:
   - RM amount per line
   - financing per line
   - scrap credits
   - processing cost from solids %
   - additional charges
   - outward freight (if not included in processing)
5. Engine derives combination status:
   - `Indicative — Rates Missing`
   - `Indicative — Rates Expired`
   - `Ready to Quote`
6. `FormulationSelector.select`:
   - ranks included combinations
   - auto-excludes too-expensive combinations
   - builds switch alert if preferred BOM is significantly worse than cheapest
7. Engine persists:
   - delete/recreate `Costing Combination` + `Costing Material Line`
   - attempt reselection by previously selected BOM
8. Engine updates `Pricing Calculation`:
   - `mode`, `selected_combination`, `confirmed_ex_factory_cost_per_kg`, `last_evaluated_on`, `engine_version_used`, `formulation_switch_alert`
9. Engine syncs back to `Pricing Request`:
   - `status`
   - `confirmed_price_per_kg`
   - `total_price = quantity_kg * confirmed`
10. Engine manages `Pending Rate Item` queue when mode is `Awaiting Rates`.

## C. Manual overrides / what-if

1. User edits working rate or processing values.
2. API writes override values to child lines.
3. `_recompute_combinations` recalculates all combinations without refetching external rates.
4. UI updates immediately with revised totals/rank/status.

## D. Selection and confirmation

1. User selects one combination.
2. Selection is persisted (`is_selected = 1`).
3. Confirmed ex-factory cost is written on calculation and pricing request.
4. Mode moves to quote-ready when selected combination is quoteable.

## E. Rate lifecycle feedback loop

1. Missing/expired rates can be converted into `Pending Rate Item`.
2. Rate manager submits `Material Rate`.
3. Pending items for item+city are cleared.
4. Open calculations with missing/expired lines for that item are notified to re-evaluate.

---

## 5) Calculation Logic (Formula Layer)

Implemented in `services/cost_calculator.py`.

- RM line amount:
  - `qty_per_kg_output * working_rate`

- Financing cost per line:
  - `amount_per_kg * (max(0, production_days - supplier_credit_days) / 365) * (supplier_financing_rate_pct / 100)`

- Processing cost:
  - `(effective_solids_pct / 100) * working_charge_per_kg`
  - 99% solids treated as 100% by convention

- Additional charge:
  - Per output kg: direct rate
  - Per solids kg: `rate * solids_factor`

- Total:
  - `rm + financing + processing + additional + outward_freight`

- 60-day equivalent rate normalization:
  - Stored in `Material Rate.rate_60d_equivalent`
  - Used to compare suppliers fairly on credit terms

- Internal earnings layer (role-gated):
  - Spread between charged supplier financing and actual cost of capital

---

## 6) State/Mode Flow

## Pricing Request.status

Values:

- `Draft`
- `Awaiting Rates`
- `Ready for Working`
- `Ready to Quote`
- `Pending Approval`
- `Approved`
- `Rejected`

How it changes:

- Starts as `Draft`
- Synced from `Pricing Calculation.mode` during/after evaluate and selection
- `before_submit` requires `Ready to Quote`, then sets `Pending Approval`

## Pricing Calculation.mode (active engine state machine)

Values:

- `Draft`
- `Awaiting Rates`
- `Ready for Working`
- `Ready to Quote`

Decision logic (`_compute_mode`):

- Missing rates -> `Awaiting Rates`
- No missing, but expired rates -> `Ready for Working`
- No missing/expired + selected combination -> `Ready to Quote`
- Else -> `Ready for Working`

## Combination-level status (`Costing Combination.status`)

Values seen:

- `Ready to Quote`
- `Indicative — Rates Expired`
- `Indicative — Rates Missing`
- `Excluded — Too Expensive` (selector overlay)

This status feeds selection readiness and user messaging.

---

## 7) Role-Based Behavior

- `Costing User`
  - Works in `Pricing Calculation`, evaluates, overrides, selects formulation

- `Costing Approver` / `System Manager`
  - Can view confidential layer-3 spread details in cost breakdown

- `Rate Manager`
  - Maintains `Material Rate` and `Processing Charge`
  - Receives expiry alerts (`rate_validity_monitor.py`)

- `Costing Sales`
  - Creates/submits `Pricing Request`
  - Sees status and confirmed prices synced from costing

---

## 8) Source of Truth for Rate Resolution

`RateSourceRegistry` + sources under `services/sources/`:

- Current default registry uses `ManualRateSource`.
- `batch_resolve` gathers options from all sources, then picks best by:
  1. freshness (`Current` > `Expired` > `Missing`)
  2. lower delivered/equivalent rate

If no options exist, synthetic `Missing` option is returned to keep pipeline deterministic.

---

## 9) Inferred User PRD (from Current Code)

The implementation indicates the following product requirements:

1. Sales must create a simple pricing request and track status without doing costing internals.
2. Costing team must evaluate all BOM formulations and compare total ex-factory outcomes.
3. System must normalize supplier rates to a 60-day credit baseline for fairness.
4. Missing/expired rates must not silently pass; they must drive explicit modes and pending-rate actions.
5. Users must be able to apply temporary “working” overrides for scenario analysis.
6. Selection of one formulation must produce one confirmed ex-factory number and sync to sales request totals.
7. Preferred formulation should be prefilled from previous approved records to reduce repeat work.
8. System should alert when a non-preferred formulation is materially cheaper (switch recommendation threshold).
9. Costing sensitivity/confidential profitability layer should be visible only to privileged roles.
10. Rate team should get feedback loops:
   - pending items to work on
   - expiry warnings
   - realtime prompts to re-evaluate after new rates are posted

---

## 10) Legacy Note

The module still contains `Costing Request` files (`doctype/costing_request/*`) with older mode names (`Exploring`, `Partially Costed`, etc.), but current API and engine pathways are centered on `Pricing Request` + `Pricing Calculation`.

Treat `Pricing Request`/`Pricing Calculation` as the active flow unless your deployment explicitly routes through legacy `Costing Request`.

---

## 11) Quick File Map

- API: `costing/api/costing.py`
- Engine: `costing/services/costing_engine.py`
- Fetching: `costing/services/rate_fetcher.py`
- Math: `costing/services/cost_calculator.py`
- Selection/ranking: `costing/services/formulation_selector.py`
- Config: `costing/services/config.py`
- Rate source orchestration: `costing/services/rate_source_registry.py`
- Sales request: `costing/doctype/pricing_request/*`
- Costing workbench: `costing/doctype/pricing_calculation/*`
- Rate master: `costing/doctype/material_rate/*`
- Processing master: `costing/doctype/processing_charge/*`
- Pending queue: `costing/doctype/pending_rate_item/*`

