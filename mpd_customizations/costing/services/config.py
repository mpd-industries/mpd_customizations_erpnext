from dataclasses import dataclass

import frappe


@dataclass
class CostingConfig:
	engine_version: str
	production_days: int
	supplier_financing_rate_pct: float
	actual_cost_of_capital_pct: float
	auto_exclusion_threshold_pct: float
	formulation_switch_threshold_pct: float
	default_valid_to: str
	default_valid_to_days: int
	rate_expiry_warning_days: int


def get_config() -> CostingConfig:
	if hasattr(frappe.local, "costing_config") and frappe.local.costing_config:
		return frappe.local.costing_config

	doc = frappe.get_single("Costing Configuration")
	config = CostingConfig(
		engine_version=doc.engine_version or "1.0.0",
		production_days=doc.production_days or 30,
		supplier_financing_rate_pct=doc.supplier_financing_rate_pct or 12.0,
		actual_cost_of_capital_pct=doc.actual_cost_of_capital_pct or 9.0,
		auto_exclusion_threshold_pct=doc.auto_exclusion_threshold_pct or 15.0,
		formulation_switch_threshold_pct=doc.formulation_switch_threshold_pct or 5.0,
		default_valid_to=doc.default_valid_to or "End of Month",
		default_valid_to_days=doc.default_valid_to_days or 30,
		rate_expiry_warning_days=doc.rate_expiry_warning_days or 30,
	)
	frappe.local.costing_config = config
	return config
