"""Compatibility shim. The command lives in mpd_base/item_ai/commands.py."""

from mpd_customizations.mpd_base.item_ai.commands import commands, recompute_item_labels

__all__ = ["commands", "recompute_item_labels"]
