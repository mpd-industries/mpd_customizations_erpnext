"""Compatibility shim for jobs queued before the extraction pipeline moved.

Background jobs reference their function by dotted path, so jobs already
waiting in Redis still resolve:
  mpd_customizations.action_extraction.pipeline.run
  mpd_customizations.action_extraction.pipeline.run_transcription
  mpd_customizations.action_extraction.pipeline.reset_stuck_jobs
"""

from mpd_customizations.meeting_notes.action_extraction.pipeline import (  # noqa: F401
	reset_stuck_jobs,
	run,
	run_transcription,
)
