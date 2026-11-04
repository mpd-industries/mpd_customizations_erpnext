from __future__ import annotations

import base64
import io
import json
import os
import re

import frappe
from frappe.utils import now_datetime

from mpd_customizations.asset_organizer.ai.schemas import (
	CATEGORY_SCHEMA_MAP,
	CATEGORY_TASK_KEY_MAP,
	PaymentExtractionSchema,
	SegmentationSchema,
)
from mpd_customizations.mpd_base.ai.llm import call_llm
from mpd_customizations.mpd_base.item_ai.dedup import (
	check_item_duplicates,
	check_item_duplicates_and_set_status,
)

_LOCATION_ROOT = "MPD Ujjain"


def _get_task_config(task_key: str):
	"""Load an AI Task Config by task_key. Raises if missing or inactive."""
	name = frappe.db.get_value("AI Task Config", {"task_key": task_key, "is_active": 1}, "name")
	if not name:
		raise ValueError(f"No active AI Task Config found for task_key={task_key!r}")
	return frappe.get_doc("AI Task Config", name)


def _location_tree_nodes(root_name: str = _LOCATION_ROOT) -> dict[str, dict]:
	root = frappe.db.get_value("Location", {"location_name": root_name}, ["name", "lft", "rgt"], as_dict=True)
	if not root:
		return {}
	rows = frappe.get_all(
		"Location",
		filters={"lft": [">=", root.lft], "rgt": ["<=", root.rgt]},
		fields=["name", "location_name", "parent_location", "lft"],
		order_by="lft asc",
	)
	return {r.name: r for r in rows}


def _build_location_tree_payload(root_name: str = _LOCATION_ROOT) -> dict:
	"""
	Build compact nested tree payload for prompt context:
	{"name": "...", "children": [{"name": "...", "children": [...]}, ...]}
	"""
	nodes = _location_tree_nodes(root_name)
	if not nodes:
		return {}

	children_by_parent: dict[str | None, list[dict]] = {}
	for node in nodes.values():
		parent = node.get("parent_location")
		children_by_parent.setdefault(parent, []).append(node)

	for lst in children_by_parent.values():
		lst.sort(key=lambda n: (n.get("location_name") or n.get("name") or "").lower())

	root_node = None
	for name, node in nodes.items():
		if (node.get("location_name") or "") == root_name:
			root_node = {**node, "name": name}
			break
	if not root_node:
		return {}

	def _walk(node: dict) -> dict:
		node_name = node.get("name")
		label = node.get("location_name") or node_name
		kids = children_by_parent.get(node_name, [])
		return {
			"name": label,
			"children": [_walk(k) for k in kids],
		}

	return _walk(root_node)
