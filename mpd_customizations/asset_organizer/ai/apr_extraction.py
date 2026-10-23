"""Asset procurement extraction pipeline.

The implementation is split by stage; this module re-exports every name so existing
imports and background-job paths keep working.
"""

from mpd_customizations.asset_organizer.ai.apr_chain import (  # noqa: F401
	_CACHE_CHAIN_ACTIVE,
	_CACHE_PENDING_SEGMENTS,
	_DEFAULT_CATEGORY_PRIORITY,
	_category_priority,
	_clear_extraction_chain,
	_enqueue_next_evidence,
	_is_extraction_chain_active,
	_maybe_continue_extraction_chain,
	_on_segmentation_complete,
	_sort_evidence_rows,
	_source_pages_sort_key,
	increment_pending_segmentations,
	set_pending_segmentations,
	start_apr_extraction_chain,
)
from mpd_customizations.asset_organizer.ai.apr_context import (  # noqa: F401
	_LOCATION_ROOT,
	_build_location_tree_payload,
	_get_task_config,
	_location_tree_nodes,
)
from mpd_customizations.asset_organizer.ai.apr_evidence import (  # noqa: F401
	run_evidence_extraction,
)
from mpd_customizations.asset_organizer.ai.apr_file_io import (  # noqa: F401
	_IMAGE_EXTENSIONS,
	_fetch_api_file,
	_image_bytes_to_pdf,
	_read_file_as_base64,
	_save_split_file,
	_split_pdf,
)
from mpd_customizations.asset_organizer.ai.apr_item_lines import (  # noqa: F401
	_append_apr_item_line,
	_build_canonical_item_request_description,
	_collect_evidence_description_variants,
	_description_token_set,
	_existing_rows_for_merge,
	_extract_source_item_code,
	_find_existing_by_prompt_index,
	_format_catalog_candidates,
	_format_prompt_line,
	_is_same_source_row,
	_line_qty_rate_total,
	_link_catalog_or_item_request,
	_llm_batch_resolve_apr_lines,
	_llm_resolve_catalog_item,
	_normalize_desc_lines,
	_preferred_description_on_merge,
	_preferred_hsn_on_merge,
	_resolve_item_lines,
	_row_to_line_dict,
	_update_existing_apr_row,
)
from mpd_customizations.asset_organizer.ai.apr_parent_fields import (  # noqa: F401
	_advance_state_machine,
	_write_parent_fields,
	run_label_generation_job,
)
from mpd_customizations.asset_organizer.ai.apr_payments import (  # noqa: F401
	_recompute_payment_totals,
	run_payment_extraction,
)
from mpd_customizations.asset_organizer.ai.apr_segmentation import (  # noqa: F401
	_handle_segmentation,
	run_segmentation_job,
)
from mpd_customizations.asset_organizer.ai.apr_summary import (  # noqa: F401
	_render_html_summary,
	_resolve_supplier,
)
