"""Install and migrate orchestration.

Each feature exposes its own ``install.py`` with ``after_install`` and/or
``after_migrate``. Register it here; steps run in list order, and a failing
step is logged without blocking the rest (a feature's DocTypes may not exist
yet on the first install, before migrate).
"""

import traceback

import click
import frappe

# (module path, function). A new feature registers itself by adding a line.
FEATURE_INSTALLERS = [
	("mpd_customizations.mpd_base.install", "after_install", "after_migrate"),
	("mpd_customizations.costing.install", "after_install", "after_migrate"),
	("mpd_customizations.xfloor_costing.install", "after_install", "after_migrate"),
]


def after_install():
	_run_feature_installers("after_install")


def after_migrate():
	_run_feature_installers("after_migrate")


def _run_feature_installers(hook):
	index = 1 if hook == "after_install" else 2
	for module_path, *hooks in FEATURE_INSTALLERS:
		function_name = hooks[index - 1]
		if not function_name:
			continue
		try:
			module = frappe.get_module(module_path)
			getattr(module, function_name)()
		except Exception:
			# click.echo rather than print: migrate captures stdout, so print output
			# never reaches the console. And rather than frappe.log_error, which
			# persists an Error Log document while the schema is mid-migration.
			click.echo(f"{module_path}.{function_name} failed during {hook}:")
			click.echo(traceback.format_exc())
