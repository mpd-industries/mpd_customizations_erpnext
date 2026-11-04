"""Compatibility shim.

The MCP server lives in meeting_notes/mcp.py. This module keeps the original
endpoint URL working for clients already configured against it:
  POST /api/method/mpd_customizations.mcp.handle_mcp
"""

from mpd_customizations.meeting_notes.mcp import handle_mcp

__all__ = ["handle_mcp"]
