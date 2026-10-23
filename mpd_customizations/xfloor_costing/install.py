def after_install():
	_seed_kit_rates()


def after_migrate():
	_seed_kit_rates()


def _seed_kit_rates():
	"""Seed Kit rates singleton defaults (idempotent)."""
	from mpd_customizations.xfloor_costing.seed import run as seed_xfloor_kit_rates

	seed_xfloor_kit_rates()
