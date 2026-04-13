import os

from mpd_customizations.setup.item_category_codes import seed_item_category_codes
from mpd_customizations.setup.llm_fixtures import (
    seed_llm_fixtures,
    sync_item_classification_system_prompt_from_code,
)


def after_install():
    seed_item_category_codes()
    seed_llm_fixtures()


def after_migrate():
    """Ensure LLM fixtures exist on upgraded sites (idempotent)."""
    seed_llm_fixtures()
    if os.environ.get("MPD_SYNC_ITEM_AI_PROMPT") == "1":
        sync_item_classification_system_prompt_from_code()
