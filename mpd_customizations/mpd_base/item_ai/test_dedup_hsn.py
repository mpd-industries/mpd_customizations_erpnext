# Copyright (c) 2026, mpdindustries and contributors
import unittest

from mpd_customizations.mpd_base.item_ai.dedup import (
    hsn_compatible,
    normalize_hsn,
    _apply_hsn_score_adjustment,
    _build_item_corpus_text,
    _build_query_text,
)
from mpd_customizations.asset_organizer.ai.apr_extraction import (
    _preferred_description_on_merge,
    _preferred_hsn_on_merge,
)


class TestDedupHsn(unittest.TestCase):
    def test_normalize_hsn_strips_non_digits(self):
        self.assertEqual(normalize_hsn("7307.21.00"), "73072100")
        self.assertEqual(normalize_hsn(""), "")

    def test_hsn_compatible_prefix(self):
        self.assertTrue(hsn_compatible("7307", "73072100"))
        self.assertTrue(hsn_compatible("73072100", "7307"))
        self.assertFalse(hsn_compatible("84818030", "73072100"))

    def test_hsn_compatible_empty(self):
        self.assertTrue(hsn_compatible(None, "73072100"))
        self.assertTrue(hsn_compatible("7307", None))

    def test_build_item_corpus_includes_tally_and_hsn(self):
        text = _build_item_corpus_text({
            "item_name": "MS Flange",
            "custom_tally_name": "Flange A",
            "custom_tally_alias": "FL-A",
            "custom_legacy_code": "LEG-1",
            "gst_hsn_code": "73072100",
        })
        self.assertIn("MS Flange", text)
        self.assertIn("Flange A", text)
        self.assertIn("73072100", text)

    def test_build_query_includes_hsn(self):
        q = _build_query_text("Ball Valve", hsn_code="84818030")
        self.assertIn("Ball Valve", q)
        self.assertIn("84818030", q)

    def test_hsn_boost_reorders_results(self):
        results = [
            {"name": "A", "gst_hsn_code": "84818030", "similarity_score": 0.35},
            {"name": "B", "gst_hsn_code": "73072100", "similarity_score": 0.34},
        ]
        adjusted = _apply_hsn_score_adjustment(results, "73072100")
        self.assertEqual(adjusted[0]["name"], "B")
        self.assertGreater(adjusted[0]["similarity_score"], 0.34)


class TestAprInvoicePreference(unittest.TestCase):
    def test_preferred_description_invoice_new(self):
        existing = {"raw_description": "Ms Flange 1\" R/F", "source_category": "PO"}
        new_line = {"raw_description": "M.S. FLANGE ASA 150 25 MM"}
        self.assertEqual(
            _preferred_description_on_merge(existing, new_line, "Invoice", None),
            "M.S. FLANGE ASA 150 25 MM",
        )

    def test_preferred_description_keeps_invoice_when_po_merges(self):
        existing = {
            "raw_description": "M.S. FLANGE ASA 150 25 MM",
            "source_category": "Invoice",
        }
        new_line = {"raw_description": "Ms Flange 1\" R/F"}
        self.assertEqual(
            _preferred_description_on_merge(existing, new_line, "PO", "Ms Flange 1\" R/F"),
            "M.S. FLANGE ASA 150 25 MM",
        )

    def test_preferred_hsn_invoice_wins(self):
        existing = {"hsn_code": "73072100", "source_category": "Invoice"}
        new_line = {"hsn_code": "7307"}
        self.assertEqual(
            _preferred_hsn_on_merge(existing, new_line, "PO"),
            "73072100",
        )
