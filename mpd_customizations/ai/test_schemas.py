# Copyright (c) 2026, mpdindustries and contributors
# For license information, please see license.txt

import unittest

from mpd_customizations.ai.schemas import ReviewOutput


class TestReviewOutput(unittest.TestCase):
	def test_model_validate_json(self):
		raw = (
			'{"decision":"Approved","confidence":82.4,"brief":"ok",'
			'"issues":[],"checks":{"hsn_valid":true}}'
		)
		obj = ReviewOutput.model_validate_json(raw)
		self.assertEqual(obj.confidence, 82)
		self.assertEqual(obj.checks.get("hsn_valid"), True)

	def test_model_dump_decision_preserved(self):
		obj = ReviewOutput(
			decision="approved",
			confidence=50,
			brief="x",
			issues=["a"],
			checks={},
		)
		self.assertEqual(obj.decision, "approved")
		self.assertEqual(obj.confidence, 50)

