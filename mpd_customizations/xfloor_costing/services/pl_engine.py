"""Floor project P&L engine.

Split by concern; this module re-exports every name so existing imports keep working.
"""

from mpd_customizations.xfloor_costing.services.pl_constants import (  # noqa: F401
	COMPONENTS,
	BUDGET_COMPONENTS,
	COMPONENT_ALIASES,
	COMPONENT_GM_FIELD,
	TOP_COAT_OPTS,
	EPOXY_TOP_COAT_OPTS,
	PU_TOP_COAT_OPTS,
	SCREED_OPTS,
	SQFT_PER_SQM,
	DEFAULT_RATES,
	DEFAULT_COVERAGE,
	GM_FIELDNAMES,
)
from mpd_customizations.xfloor_costing.services.pl_helpers import (  # noqa: F401
	_f,
	_ceil_div,
	_coving_kits_from_feet,
	coving_kits_from_feet,
	_normalize_component,
	_epoxy_coverage_map,
	_pu_coverage_map,
	_screed_coverage_map,
	_coverage_for,
	get_kit_rates_doc,
	_get_setting_value,
	_normalize_project_data,
	_cost_per_sqft,
)
from mpd_customizations.xfloor_costing.services.pl_profiles import (  # noqa: F401
	_summary_from_totals,
	_gm_for_component,
	_attach_gm,
	_pct,
	_applicator_cost,
	_kit_spend_total,
	_margin_rows_from_budget,
	_enrich_part_margin,
	_build_margin_summary,
	_cost_rows_from_budget,
	_enrich_part_cost_profile,
	_build_cost_profile,
)
from mpd_customizations.xfloor_costing.services.pl_calc import (  # noqa: F401
	calc_part,
	_part_row_dict,
	_normalize_parts,
	_rollup_budget_rows,
	_apply_project_coving,
	_legacy_coving_kits,
	_resolve_project_coving_kits,
	calc_project,
	flat_fields_to_main_part,
	calc_actual_totals,
	calc_actual_by_component,
	build_comparison,
)
from mpd_customizations.xfloor_costing.services.pl_price_list import (  # noqa: F401
	_area_rate,
	round_price_list_rate,
	format_price_list_rate,
	_thickness_label,
	PRICE_LIST_SCREED_OPTS,
	PRICE_LIST_EPOXY_TOP,
	PRICE_LIST_PU_TOP,
	build_price_list,
	strip_gm_from_result,
	strip_gm_from_kit_rates,
)
