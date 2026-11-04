"""Floor project P&L engine.

Split by concern; this module re-exports every name so existing imports keep working.
"""

from mpd_customizations.xfloor_costing.services.pl_calc import (  # noqa: F401
	_apply_project_coving,
	_legacy_coving_kits,
	_normalize_parts,
	_part_row_dict,
	_resolve_project_coving_kits,
	_rollup_budget_rows,
	build_comparison,
	calc_actual_by_component,
	calc_actual_totals,
	calc_part,
	calc_project,
	flat_fields_to_main_part,
)
from mpd_customizations.xfloor_costing.services.pl_constants import (  # noqa: F401
	BUDGET_COMPONENTS,
	COMPONENT_ALIASES,
	COMPONENT_GM_FIELD,
	COMPONENTS,
	DEFAULT_COVERAGE,
	DEFAULT_RATES,
	EPOXY_TOP_COAT_OPTS,
	GM_FIELDNAMES,
	PU_TOP_COAT_OPTS,
	SCREED_OPTS,
	SQFT_PER_SQM,
	TOP_COAT_OPTS,
)
from mpd_customizations.xfloor_costing.services.pl_helpers import (  # noqa: F401
	_ceil_div,
	_cost_per_sqft,
	_coverage_for,
	_coving_kits_from_feet,
	_epoxy_coverage_map,
	_f,
	_get_setting_value,
	_normalize_component,
	_normalize_project_data,
	_pu_coverage_map,
	_screed_coverage_map,
	coving_kits_from_feet,
	get_kit_rates_doc,
)
from mpd_customizations.xfloor_costing.services.pl_price_list import (  # noqa: F401
	PRICE_LIST_EPOXY_TOP,
	PRICE_LIST_PU_TOP,
	PRICE_LIST_SCREED_OPTS,
	_area_rate,
	_thickness_label,
	build_price_list,
	format_price_list_rate,
	round_price_list_rate,
	strip_gm_from_kit_rates,
	strip_gm_from_result,
)
from mpd_customizations.xfloor_costing.services.pl_profiles import (  # noqa: F401
	_applicator_cost,
	_attach_gm,
	_build_cost_profile,
	_build_margin_summary,
	_cost_rows_from_budget,
	_enrich_part_cost_profile,
	_enrich_part_margin,
	_gm_for_component,
	_kit_spend_total,
	_margin_rows_from_budget,
	_pct,
	_summary_from_totals,
)
