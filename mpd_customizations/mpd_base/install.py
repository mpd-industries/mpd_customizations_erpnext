import os

from mpd_customizations.mpd_base.ai.llm_fixtures import (
	seed_llm_fixtures,
	sync_item_classification_system_prompt_from_code,
	sync_oth_reclassification_config,
)
from mpd_customizations.mpd_base.item_ai.backfills import backfill_item_labels, backfill_item_solids
from mpd_customizations.mpd_base.item_ai.category_codes import seed_item_category_codes


def after_install():
	seed_item_category_codes()
	seed_llm_fixtures()
	_backfill_item_labels()


def after_migrate():
	"""Ensure LLM fixtures exist on upgraded sites (idempotent)."""
	seed_llm_fixtures()
	sync_oth_reclassification_config()
	_backfill_item_labels()
	backfill_item_solids()
	if os.environ.get("MPD_SYNC_ITEM_AI_PROMPT") == "1":
		sync_item_classification_system_prompt_from_code()


def _backfill_item_labels():
	updated, _skipped = backfill_item_labels() or (0, 0)
	if updated:
		print(f"Backfilled custom_item_label for {updated} item(s).")
