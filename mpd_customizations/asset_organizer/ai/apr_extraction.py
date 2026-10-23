"""Asset procurement extraction pipeline.

The implementation is split by stage; this module re-exports every name so existing
imports and background-job paths keep working.
"""

from mpd_customizations.asset_organizer.ai.apr_file_io import (  # noqa: F401
    _IMAGE_EXTENSIONS,
    _image_bytes_to_pdf,
    _read_file_as_base64,
    _fetch_api_file,
    _split_pdf,
    _save_split_file,
)
from mpd_customizations.asset_organizer.ai.apr_context import (  # noqa: F401
    _LOCATION_ROOT,
    _get_task_config,
    _location_tree_nodes,
    _build_location_tree_payload,
)
from mpd_customizations.asset_organizer.ai.apr_summary import (  # noqa: F401
    _render_html_summary,
    _resolve_supplier,
)
from mpd_customizations.asset_organizer.ai.apr_item_lines import (  # noqa: F401
    _line_qty_rate_total,
    _format_prompt_line,
    _row_to_line_dict,
    _is_same_source_row,
    _existing_rows_for_merge,
    _preferred_description_on_merge,
    _preferred_hsn_on_merge,
    _llm_batch_resolve_apr_lines,
    _find_existing_by_prompt_index,
    _update_existing_apr_row,
    _format_catalog_candidates,
    _llm_resolve_catalog_item,
    _extract_source_item_code,
    _normalize_desc_lines,
    _description_token_set,
    _collect_evidence_description_variants,
    _build_canonical_item_request_description,
    _link_catalog_or_item_request,
    _append_apr_item_line,
    _resolve_item_lines,
)
from mpd_customizations.asset_organizer.ai.apr_parent_fields import (  # noqa: F401
    _write_parent_fields,
    run_label_generation_job,
    _advance_state_machine,
)
from mpd_customizations.asset_organizer.ai.apr_chain import (  # noqa: F401
    _DEFAULT_CATEGORY_PRIORITY,
    _CACHE_PENDING_SEGMENTS,
    _CACHE_CHAIN_ACTIVE,
    _category_priority,
    _source_pages_sort_key,
    _sort_evidence_rows,
    set_pending_segmentations,
    increment_pending_segmentations,
    _on_segmentation_complete,
    _is_extraction_chain_active,
    start_apr_extraction_chain,
    _clear_extraction_chain,
    _enqueue_next_evidence,
    _maybe_continue_extraction_chain,
)
from mpd_customizations.asset_organizer.ai.apr_segmentation import (  # noqa: F401
    _handle_segmentation,
    run_segmentation_job,
)
from mpd_customizations.asset_organizer.ai.apr_evidence import (  # noqa: F401
    run_evidence_extraction,
)
from mpd_customizations.asset_organizer.ai.apr_payments import (  # noqa: F401
    run_payment_extraction,
    _recompute_payment_totals,
)
