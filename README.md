# Mpd Customizations

Frappe app for MPD Industries. Each business area is one Frappe module, and that module folder is the feature. Features may depend on `mpd_base`. They do not depend on each other.

| Feature | Folder | What it does |
|---|---|---|
| Platform | `mpd_customizations/mpd_base` | LLM providers, AI task config, item classification, OTH reclassification, S3-backed files |
| Costing | `mpd_customizations/costing` | Ex-factory cost per kg and pricing approval |
| Asset organizer | `mpd_customizations/asset_organizer` | Asset procurement records and AI extraction from PDFs |
| Meeting notes | `mpd_customizations/meeting_notes` | Transcription, action extraction, MCP server |
| XFloor costing | `mpd_customizations/xfloor_costing` | Floor-project P&L, kit rates, project manager page |
| XFloor CMS | `mpd_customizations/xfloor_cms` | Website content for xfloor.in |

Inside a feature the layout is the same:

```
<feature>/
  doctype/ report/ page/ print_format/ workspace/ custom/   # Frappe-managed
  api.py or api/        # whitelisted endpoints: permission check, then delegate
  services/             # business logic and background jobs
  ai/                   # prompts and LLM extraction, when the feature uses AI
  install.py            # after_install / after_migrate for this feature
  patches/              # this feature's patches
  tests/                # unit tests that do not need a site
```

`hooks.py` has one section per feature. `mpd_customizations/setup/__init__.py` runs each feature's `install.py` from `FEATURE_INSTALLERS`.

## Install

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app mpd_customizations
```

`after_install` and `after_migrate` seed item category codes, LLM fixtures (OpenRouter provider and AI Task Config rows), item labels, cities, and XFloor kit-rate defaults. Each step is idempotent. A step that fails is printed and skipped so the others still run.

Set `OPENROUTER_API_KEY` before the first install if the OpenRouter provider should be created with a real key. Migrate always overwrites the `item_classification` and `oth_reclassification` system prompts from code.

## Develop

```bash
cd apps/mpd_customizations
pre-commit install
```

Pre-commit runs ruff (lint, import order, format) plus prettier and eslint on JavaScript. Ruff is configured in `pyproject.toml` (tabs, line length 110).

Python dependencies (installed by bench from `pyproject.toml`): `litellm`, `scikit-learn`, `mcp`, `sarvamai`, `pypdf`.

### Tests

Unit tests do not boot a site:

```bash
cd apps/mpd_customizations
python -m unittest \
  mpd_customizations.costing.tests.test_cost_calculator \
  mpd_customizations.costing.tests.test_costing_engine \
  mpd_customizations.costing.tests.test_formulation_selector \
  mpd_customizations.costing.tests.test_manual_rate_source \
  mpd_customizations.costing.tests.test_rate_fetcher \
  mpd_customizations.xfloor_costing.tests.test_pl_engine \
  mpd_customizations.mpd_base.tests.test_dedup_hsn
```

DocType tests under `doctype/test_*.py` are Frappe test stubs and run with `bench run-tests --app mpd_customizations`.

### Bench commands

```bash
bench --site <site> recompute-item-labels
bench --site <site> recompute-item-labels --force
```

Rebuilds `custom_item_label` on Item. Without `--force`, rows that already match are skipped.

## Hooks, scheduler, patches

| Hook | Path |
|---|---|
| `after_install` / `after_migrate` | `mpd_customizations.setup` |
| Item `before_save` / `on_trash` | `mpd_base.item_ai.item_hooks` |
| Address `on_update` | `costing.services.city_sync.on_address_update` |
| File class override | `mpd_base.files.file_override.CustomFile` |
| Daily | `costing.services.rate_validity_monitor.run_rate_validity_check` |
| Every 15 minutes | `meeting_notes.action_extraction.pipeline.reset_stuck_jobs` |

Client scripts are included for Item, Project, Meeting Note, Floor Project, Kit rates, and Kit Coverage.

Fixtures export Task customizations, costing custom fields and roles, Costing Configuration, packaging masters, the Floor Project P&L print format, and the XFloor roles.

Patches in `mpd_customizations/patches.txt` have already run on existing sites. Do not rename or move them: Frappe records each patch by dotted path and will run it again if the path changes. New patches go in `<feature>/patches/` and are listed in `patches.txt`.

Three import paths are shims. Jobs and clients that still use the old path keep working:

| Old path | Real module |
|---|---|
| `mpd_customizations.mcp.handle_mcp` | `meeting_notes.mcp` |
| `mpd_customizations.action_extraction.pipeline` | `meeting_notes.action_extraction.pipeline` |
| `mpd_customizations.overrides.file.CustomFile` | `mpd_base.files.file_override` |

## mpd_base

Shared platform for the other features.

**LLM.** `LLM Provider` and `AI Task Config` (with parameter rows) live here. `mpd_base/ai/llm.py` is the LiteLLM wrapper (`call_llm`). `mpd_base/ai/task_config.py` loads an active config by `task_key`. `mpd_base/ai/llm_fixtures.py` seeds OpenRouter plus the `item_classification`, `meeting_note_extraction`, and `oth_reclassification` tasks.

**Item AI.** New items are raised as Item Request, not Item (`public/js/item_custom.js`). The requester chooses Stock, Fixed Asset, or Expense, runs dedup, then generates an AI suggestion (prefix, group, HSN, UOM) via `item_classification` / `run_item_review`. They can edit the suggestion and create the Item themselves — there is no Master Approver step. `item_ai/dedup.py` keeps a TF-IDF search index used by Item Request and by asset procurement. `bench recompute-item-labels` and the migrate backfill both call `item_ai/backfills.py`.

**OTH review.** `oth_review/review.py` batch-reviews items still on the catch-all `OTH` prefix and suggests a real prefix, item group, and cleaned name.

**Files.** `mpd_base/files/file_override.py` replaces ERPNext File so S3-backed files (`mpd_base/files/s3.py`) return their bytes from `get_content`.

## Costing

Ex-factory cost per kg for resin and coating products made by contract processors.

A Costing User creates a Pricing Request (item, city, solids, quantity). That inserts a Pricing Calculation and evaluates it. A customer quote instead starts from an approved Customer Product and its formulations. `CostingEngine.evaluate` in `costing/services/costing_engine.py`:

1. Loads BOMs (or Customer Product formulations) and fetches material, packaging, freight, and processing rates. Manual overrides on the calculation are kept.
2. Builds one combination per BOM: raw-material cost, process loss, scrap credit, processing, additional charges, outward freight, packaging, and delivery.
3. Adds margin, customer credit, and commission to reach a selling price per kg.
4. Stores the snapshot on `costing_raw` and sets the mode.

`costing/api/costing.py` is the whitelisted surface the forms call (`evaluate`, select combination, overrides, approve, reject, `fetch_processing_charge`). Approval and rate-conflict rules live in `costing/services/pricing_workflow.py`. Approving a calculation submits it, marks the Pricing Request approved, and upserts an Item Price on the Standard Costed price list.

Material Rate is one submitted quote per item, supplier, and city. Overlapping submitted rates for the same key are truncated on submit. Processing Charge resolves processor plus item first, then processor plus item group. Cities on Address are mirrored into the City master by `costing/services/city_sync.py`.

Roles: Costing User, Costing Approver, Rate Manager, Costing Sales, R&D Manager, Dispatch Manager. Only Costing Approver or System Manager can approve or reject.

A daily job checks rate validity (`rate_validity_monitor`).

## Asset organizer

One Asset Procurement Record (APR) per capital purchase. Uploaded PDFs are segmented, classified, and extracted into evidence rows, supplier, milestones, item lines, and payments.

Saving an APR with `upload_status = Queued` enqueues `run_segmentation_job` on the `long` queue. Segmentation calls the `apr_document_segment` task, splits the PDF, and creates APR Evidence Document rows. Those rows are then extracted one at a time in category order (Quote, PO, IGP, then the rest). Quote and PO extraction also queue a label job. Payment rows with evidence enqueue `run_payment_extraction` separately.

The pipeline is split under `asset_organizer/ai/` (`apr_file_io`, `apr_context`, `apr_item_lines`, `apr_segmentation`, `apr_evidence`, `apr_payments`, and related modules). `ai/apr_extraction.py` re-exports every public name, and background jobs still target that module.

Item lines are built from PO and Invoice extractions. Descriptions are merged onto one row per physical product, then matched to an Item or an Item Request through the shared search index plus an LLM.

Whitelisted actions in `asset_organizer/api/apr.py` (System Manager or Stock Manager): `requeue_evidence_extraction`, `rerun_full_apr_extraction`, `rerun_apr_payment_extraction`, plus the bulk variants, and `get_apr_summary`.

APR task configs (`apr_document_segment`, `apr_extract_*`) are seeded by `asset_organizer/patches/seed_apr_ai_task_configs.py`. Rebuild the item search index with:

```bash
bench --site <site> execute mpd_customizations.mpd_base.item_ai.dedup.rebuild_search_index
```

## Meeting notes

A Meeting Note holds the recording, transcript, summary, and proposed tasks. `start_transcription` and `start_extraction` enqueue `meeting_notes.action_extraction.pipeline`. Transcription uses Sarvam. Extraction uses the `meeting_note_extraction` AI Task Config and the tools in `action_extraction/tools.py` (`get_backlog`, `create_pending_task`, `update_existing_task`). The form then bulk-approves pending tasks onto a Project.

`reset_stuck_jobs` runs every 15 minutes and returns jobs stuck in a running state.

The MCP server speaks JSON-RPC 2.0 (`initialize`, `tools/list`, `tools/call`) for those three tools. Authenticate with a Frappe API key:

```
POST /api/method/mpd_customizations.mcp.handle_mcp
Authorization: token <api_key>:<api_secret>
```

`mpd_customizations.meeting_notes.mcp.handle_mcp` is the same function.

## XFloor costing

Kit rates and kit coverage are singletons. A Floor Project is costed from one or more parts (area, epoxy and PU top coat, screed, coving, hi-build) by `xfloor_costing/services/pl_engine.py`. The engine is split into `pl_constants`, `pl_helpers`, `pl_profiles`, `pl_calc`, and `pl_price_list`; `pl_engine` re-exports them.

`calc_project` returns budget rows, a margin summary, and a cost profile. `build_price_list` builds the commercial rate sheet used by the Kit rates print. Gross-margin fields are stripped for users who are not System Manager.

The XFloor Project Manager page (`xfloor_costing/page/xfloor_project_manager`) calls `xfloor_costing/api/pl.py` to load, save, calculate, and delete projects. Print formats: Floor Project P&L, Floor Project Cost Profile, Floor Project Margin, Kit Rates Price List.

`xfloor_costing/install.py` seeds kit-rate defaults on install and migrate.

## XFloor CMS

Single pages (home, about, contact, FAQ, applicator) and child content (product systems, industries, testimonials, gallery) for the XFloor website. Roles: Xfloor CMS Manager, XFloor Costing Manager.

Seed content lives in `xfloor_cms/seed_data.py` and is shared by both seeders:

```bash
bench --site <site> execute mpd_customizations.xfloor_cms.seed.run
python mpd_customizations/xfloor_cms/scripts/seed_via_rest.py --host ... --key ... --secret ...
```

The bench seeder writes through the ORM. The REST script talks to a remote site and is not called by migrate.

## Adding a feature

1. Add the module name to `mpd_customizations/modules.txt` and create the folder, or create the Module Def from Desk and export it.
2. Copy the layout above. Put DocTypes in `<feature>/doctype/`. Put business logic in `services/`, and keep `@frappe.whitelist` functions in `api/` as a permission check plus a call into `services/`.
3. Add a labelled section to `hooks.py` for this feature's `doctype_js`, `doc_events`, scheduler jobs, and fixtures.
4. If the feature seeds data on install or migrate, add `<feature>/install.py` with `after_install` and `after_migrate`, then register the module in `FEATURE_INSTALLERS` in `mpd_customizations/setup/__init__.py`. Keep the functions idempotent.
5. Put new patches in `<feature>/patches/` and append the dotted path to `patches.txt`. Never rename a patch that has already been released.
6. Put unit tests in `<feature>/tests/`.

## CI

GitHub Actions on pull requests runs pre-commit (ruff, prettier, eslint), Frappe semgrep rules, and pip-audit. The test workflow installs the app and runs unit tests on pushes to `develop`.

## License

MIT.
