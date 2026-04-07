# Mpd Customizations

Frappe app for **MPD Industries**: AI-assisted master-data review (via LiteLLM), workflow-driven approvals, and guards on transactions that reference Items by workflow state.

## Architecture overview

### Master data AI review

1. A document (e.g. **Item**) uses a **Workflow** with states such as `Pending AI Review`.
2. When the workflow state transitions into `Pending AI Review`, a hook enqueues a background job (see `hooks.py` → `doc_events` → `Item` `on_update` → `masters/item_approval.py`).
3. The job calls **`AIGateway`** (`mpd_customizations/ai/gateway.py`) with a **`task_key`** (e.g. `item_review`) that selects an **`LLM Task`** row.
4. **`AIGateway`** loads:
   - **`LLM Provider`**: API key, optional **API Base URL**, and provider key (anthropic, openai, openrouter, etc.).
   - **`LLM Task`**: model string (LiteLLM format), temperature, max tokens, confidence threshold, optional custom system prompt.
5. The gateway builds messages from the **system prompt** (from the Task document or from `ai/prompts/<task_key>.py`) and the **user prompt** from `build_user_prompt(...)`.
6. **Structured output**: each prompt module can export `get_response_format()`, which returns a **Pydantic** model (`ReviewOutput` in `ai/schemas.py`) for [LiteLLM structured outputs](https://docs.litellm.ai/docs/completion/json_mode). If the provider rejects that, the gateway retries with JSON mode `response_format={"type": "json_object"}`.
7. The model reply is parsed (Pydantic `model_validate_json` when possible, otherwise `ai/parser.py` heuristics), confidence is compared to the task threshold, and an **`LLM Review Log`** row is written.
8. **`apply_ai_transition`** (`ai/workflow.py`) applies the workflow action (e.g. AI Approve / AI Flag) as the configured **AI system user** from **LLM Task Settings**.

### Transaction checks

Hooks on **Purchase Order**, **Purchase Receipt**, **Request for Quotation**, **Supplier Quotation**, **Sales Order**, and **Sales Invoice** call `masters/transaction_checks.check_items`, which reads each line item’s **`Item.workflow_state`** and blocks or warns according to configured state sets (see `transaction_checks.py`). **System Manager** bypasses these checks.

### DocTypes (Mpd Core module)

| DocType | Purpose |
|--------|---------|
| **LLM Provider** | Named provider, **Provider Key**, password **API Key**, optional **API Base URL** (required for OpenAI-compatible proxies such as OpenRouter), enable flag, fallback order. |
| **LLM Task** | `task_key` (used in code), link to provider, **Model String** (LiteLLM, e.g. `anthropic/claude-sonnet-4-6` or `openrouter/...`), sampling limits, **Confidence Threshold**, optional **System Prompt** override, optional **Fallback Task**. |
| **LLM Task Settings** | Single settings; includes **AI system user** for workflow actions. |
| **LLM Review Log** | Audit trail per run (decision, tokens, latency, raw response, etc.). |
| **Validation Log** | Reserved / optional use. |

### Default seed data

On **`after_install`**, fixtures are synced and default **LLM Provider** and **LLM Task** rows are created if missing (`setup.py`). **`after_migrate`** syncs fixtures and runs **`_seed_providers()`** again so new providers (e.g. **OpenRouter**) appear on existing sites without reinstalling the app.

## Configuration

### API Base URL

Set **API Base URL** on **LLM Provider** when the provider needs a non-default OpenAI-compatible endpoint:

- **OpenRouter**: `https://openrouter.ai/api/v1` (seeded on new installs and on migrate if missing).
- **LiteLLM proxy**: your proxy base URL.

Leave blank to use LiteLLM’s default routing for that provider key.

### OpenRouter

1. Ensure the **OpenRouter** provider row exists (migrate after upgrading this app).
2. Enable it (and optionally disable others), set the **API Key** to your OpenRouter key, and confirm **API Base URL** is `https://openrouter.ai/api/v1`.
3. Set **Model String** on the **LLM Task** to a LiteLLM-supported id, typically prefixed with `openrouter/` (see [LiteLLM provider docs](https://docs.litellm.ai/docs/providers/openrouter) and [JSON mode](https://docs.litellm.ai/docs/completion/json_mode)).

### JSON mode and JSON schema

- The gateway requests **structured JSON** using `response_format` as described in [LiteLLM Structured Outputs (JSON mode)](https://docs.litellm.ai/docs/completion/json_mode).
- **Shared schema**: `ReviewOutput` in `ai/schemas.py` (Pydantic) is the canonical shape: `decision`, `confidence`, `brief`, `issues`, `checks`.
- Per-task customization: implement `get_response_format()` in `ai/prompts/<task_key>.py` to return `ReviewOutput` or a subclass if you need a stricter schema.
- Completions use `drop_params=False` so `response_format` is not silently dropped.

## Adding a new verification (checklist)

1. **LLM Task**  
   Create a row (or add to `DEFAULT_TASKS` in `setup.py` for greenfield installs) with a unique **`task_key`**, **`model_string`**, thresholds, and link to an **LLM Provider**.

2. **Prompt module**  
   Add `mpd_customizations/ai/prompts/<task_key>.py` with:
   - `SYSTEM_PROMPT`
   - `build_user_prompt(...)` (signature depends on your job)
   - `get_response_format()` returning `ReviewOutput` (or a subclass) — optional; defaults to JSON object mode if omitted.

3. **Schema**  
   Extend or subclass **`ReviewOutput`** in `ai/schemas.py` if the new task needs extra fields; keep downstream jobs and logging compatible.

4. **Job**  
   Implement a job (see `jobs/review_item.py`) that instantiates `AIGateway("<task_key>")`, builds the user prompt, calls `gateway.run(...)`, then applies workflow / notifications as needed.

5. **Hooks & workflow**  
   Register `doc_events` in `hooks.py` and ensure the target DocType has workflow states and transitions matching your job (fixtures under `fixtures/` if you ship defaults).

6. **Migrate**  
   Run `bench migrate` on each site after deploying DocType or code changes.

## Development

Install the app with [bench](https://github.com/frappe/bench):

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app mpd_customizations
```

This package declares **`litellm`** and **`pydantic`** in `pyproject.toml`. After pulling changes, reinstall dependencies if needed:

```bash
cd apps/mpd_customizations && pip install -e .
```

Pre-commit (ruff, eslint, prettier, pyupgrade) is configured under `.pre-commit-config.yaml`.

## CI

GitHub Actions workflows may run tests and linters on push/PR; see `.github/workflows/`.

## License

MIT
