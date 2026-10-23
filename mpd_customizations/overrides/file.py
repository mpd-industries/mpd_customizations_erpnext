"""Compatibility shim. The File override lives in mpd_base/files/file_override.py."""

from mpd_customizations.mpd_base.files.file_override import CustomFile

__all__ = ["CustomFile"]
