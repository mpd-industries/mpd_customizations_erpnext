import unittest

from mpd_customizations.compliance.mcp_tools import MCP_PROMPTS, TOOL_NAMES, get_prompt


class TestComplianceMcp(unittest.TestCase):
	def test_agent_tools_are_registered(self):
		self.assertIn("compliance_get_context", TOOL_NAMES)
		self.assertIn("compliance_coverage", TOOL_NAMES)
		self.assertIn("compliance_add_obligation", TOOL_NAMES)
		self.assertIn("compliance_add_activity", TOOL_NAMES)
		self.assertIn("compliance_complete", TOOL_NAMES)

	def test_gap_review_prompt(self):
		prompt = get_prompt("compliance_gap_review")
		self.assertIn("Draft", prompt["messages"][0]["content"]["text"])
		self.assertEqual(
			{row["name"] for row in MCP_PROMPTS}, {"compliance_gap_review", "compliance_weekly_review"}
		)
