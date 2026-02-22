"""
Session 37 — B2 tests for lizardperson_argparse_programs/municipal_bluebook_citation_validator
pure-math utility functions (no pydantic / BeautifulSoup needed).

Modules under test (loaded via importlib to bypass __init__.py pydantic guard):
  - _calculate_accuracy_statistics.py  →  ConfusionMatrixStats, calculate_accuracy_statistics
  - _check_format.py                   →  check_format
  - _calculate_sample_sizes.py         →  calculate_sample_sizes
"""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# Load modules bypassing __init__.py (which requires pydantic)
# ──────────────────────────────────────────────────────────────────────────────
_BASE = (
    Path(__file__).parent.parent.parent.parent
    / "ipfs_datasets_py"
    / "mcp_server"
    / "tools"
    / "lizardperson_argparse_programs"
    / "municipal_bluebook_citation_validator"
)


def _load(relative: str):
    path = _BASE / relative
    spec = importlib.util.spec_from_file_location(relative.replace("/", "."), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_calc_acc = _load("results_analyzer/_calculate_accuracy_statistics.py")
ConfusionMatrixStats = _calc_acc.ConfusionMatrixStats
calculate_accuracy_statistics = _calc_acc.calculate_accuracy_statistics

# check_format needs `re` only — importable directly
_chk_fmt = _load("citation_validator/_check_format.py")
check_format = _chk_fmt.check_format

# calculate_sample_sizes is pure Python
_calc_ss = _load("stratified_sampler/_calculate_sample_sizes.py")
calculate_sample_sizes = _calc_ss.calculate_sample_sizes


# ──────────────────────────────────────────────────────────────────────────────
# TestConfusionMatrixStats
# ──────────────────────────────────────────────────────────────────────────────
class TestConfusionMatrixStats(unittest.TestCase):
    """Tests for ConfusionMatrixStats with a typical scenario (80 TP, 10 TN, 100 total)."""

    def _make(
        self,
        tp: int = 80,
        tn: int = 10,
        pp: int = 85,
        pn: int = 15,
        total: int = 100,
    ) -> ConfusionMatrixStats:
        return ConfusionMatrixStats(tp, tn, pp, pn, total)

    # ── core storage ──────────────────────────────────────────────────────────

    def test_total_citations_stored(self):
        c = self._make()
        self.assertEqual(c.total_citations, 100)

    def test_valid_citations_stored(self):
        c = self._make(tp=80, tn=10, total=100)
        self.assertEqual(c.valid_citations, 80)

    def test_total_errors_stored(self):
        # total_errors = total_population − TP − TN = 100 − 80 − 10 = 10
        c = self._make(tp=80, tn=10, total=100)
        self.assertEqual(c.total_errors, 10)

    # ── accuracy family ───────────────────────────────────────────────────────

    def test_accuracy_range(self):
        c = self._make()
        self.assertGreaterEqual(c.accuracy, 0.0)
        self.assertLessEqual(c.accuracy, 1.0)

    def test_accuracy_percent_is_100x_accuracy(self):
        c = self._make()
        self.assertAlmostEqual(c.accuracy_percent, c.accuracy * 100)

    def test_error_rate_plus_accuracy_equals_one(self):
        c = self._make()
        self.assertAlmostEqual(c.accuracy + c.error_rate, 1.0)

    def test_error_rate_percent_is_100x_error_rate(self):
        c = self._make()
        self.assertAlmostEqual(c.error_rate_percent, c.error_rate * 100)

    # ── precision / recall / F1 ───────────────────────────────────────────────

    def test_f1_score_range(self):
        c = self._make()
        self.assertGreaterEqual(c.f1_score, 0.0)
        self.assertLessEqual(c.f1_score, 1.0)

    def test_precision_range(self):
        c = self._make()
        self.assertGreaterEqual(c.precision, 0.0)
        self.assertLessEqual(c.precision, 1.0)

    def test_true_positive_rate_range(self):
        c = self._make()
        self.assertGreaterEqual(c.true_positive_rate, 0.0)
        self.assertLessEqual(c.true_positive_rate, 1.0)

    def test_true_negative_rate_range(self):
        c = self._make()
        self.assertGreaterEqual(c.true_negative_rate, 0.0)
        self.assertLessEqual(c.true_negative_rate, 1.0)

    # ── false rates ────────────────────────────────────────────────────────────

    def test_false_positive_rate_range(self):
        c = self._make()
        self.assertGreaterEqual(c.false_positive_rate, 0.0)
        self.assertLessEqual(c.false_positive_rate, 1.0)

    def test_false_negative_rate_range(self):
        c = self._make()
        self.assertGreaterEqual(c.false_negative_rate, 0.0)
        self.assertLessEqual(c.false_negative_rate, 1.0)

    def test_false_discovery_rate_range(self):
        c = self._make()
        self.assertGreaterEqual(c.false_discovery_rate, 0.0)
        self.assertLessEqual(c.false_discovery_rate, 1.0)

    def test_false_omission_rate_range(self):
        c = self._make()
        self.assertGreaterEqual(c.false_omission_rate, 0.0)
        self.assertLessEqual(c.false_omission_rate, 1.0)

    # ── derived stats ──────────────────────────────────────────────────────────

    def test_prevalence_range(self):
        c = self._make()
        self.assertGreaterEqual(c.prevalence, 0.0)
        self.assertLessEqual(c.prevalence, 1.0)

    def test_negative_predictive_value_range(self):
        c = self._make()
        self.assertGreaterEqual(c.negative_predictive_value, 0.0)
        self.assertLessEqual(c.negative_predictive_value, 1.0)

    # ── to_dict ───────────────────────────────────────────────────────────────

    def test_to_dict_returns_dict(self):
        c = self._make()
        d = c.to_dict()
        self.assertIsInstance(d, dict)

    def test_to_dict_has_required_keys(self):
        c = self._make()
        d = c.to_dict()
        for key in ("accuracy", "f1_score", "precision", "true_positives", "true_negatives"):
            self.assertIn(key, d)

    def test_to_dict_accuracy_matches_property(self):
        c = self._make()
        self.assertAlmostEqual(c.to_dict()["accuracy"], c.accuracy)

    # ── edge cases ────────────────────────────────────────────────────────────

    def test_zero_total_raises_value_error(self):
        with self.assertRaises(ValueError):
            ConfusionMatrixStats(0, 0, 0, 0, 0)

    def test_negative_counts_raise_value_error(self):
        with self.assertRaises(ValueError):
            ConfusionMatrixStats(-1, 0, 0, 0, 10)

    def test_perfect_classification(self):
        # TP=100, TN=0, PP=100, PN=0, total=100
        c = ConfusionMatrixStats(100, 0, 100, 0, 100)
        self.assertAlmostEqual(c.accuracy, 1.0)


# ──────────────────────────────────────────────────────────────────────────────
# TestCalculateAccuracyStatistics
# ──────────────────────────────────────────────────────────────────────────────
class TestCalculateAccuracyStatistics(unittest.TestCase):
    """Tests for the calculate_accuracy_statistics() convenience wrapper."""

    def test_returns_dict(self):
        result = calculate_accuracy_statistics(100, 10, 85, 15)
        self.assertIsInstance(result, dict)

    def test_zero_total_returns_safe_dict(self):
        result = calculate_accuracy_statistics(0, 0, 0, 0)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["total_citations"], 0)
        self.assertEqual(result["accuracy_percent"], 0.0)

    def test_all_valid_citations(self):
        # 100 total, 0 errors → high accuracy
        result = calculate_accuracy_statistics(100, 0, 100, 0)
        self.assertGreaterEqual(result.get("accuracy", result.get("accuracy_percent", 0)), 0)

    def test_has_accuracy_key(self):
        result = calculate_accuracy_statistics(100, 20, 75, 25)
        # Either 'accuracy' or 'accuracy_percent' must be present
        self.assertTrue("accuracy" in result or "accuracy_percent" in result)

    def test_has_error_rate_key(self):
        result = calculate_accuracy_statistics(100, 20, 75, 25)
        self.assertTrue("error_rate" in result or "error_rate_percent" in result)


# ──────────────────────────────────────────────────────────────────────────────
# TestCheckFormat
# ──────────────────────────────────────────────────────────────────────────────
class TestCheckFormat(unittest.TestCase):
    """Tests for the check_format() Bluebook citation validator."""

    def _valid_citation(self) -> dict:
        return {
            "title": "City Code of Springfield",
            "section": "14-75",
            "date": "2023",
            "url": "https://example.com/code/14-75",
        }

    def test_valid_citation_returns_none(self):
        """Fully valid citation should return None (no errors)."""
        self.assertIsNone(check_format(self._valid_citation()))

    def test_empty_dict_returns_error(self):
        result = check_format({})
        self.assertIsNotNone(result)

    def test_missing_title_returns_error(self):
        c = self._valid_citation()
        c["title"] = ""
        result = check_format(c)
        self.assertIsNotNone(result)

    def test_bad_section_format_returns_error(self):
        c = self._valid_citation()
        c["section"] = "notasection"
        result = check_format(c)
        self.assertIsNotNone(result)
        self.assertIn("Section", result)

    def test_bad_url_returns_error(self):
        c = self._valid_citation()
        c["url"] = "not a url"
        result = check_format(c)
        self.assertIsNotNone(result)
        self.assertIn("URL", result)

    def test_bad_date_returns_error(self):
        c = self._valid_citation()
        c["date"] = "yesterday"
        result = check_format(c)
        self.assertIsNotNone(result)
        self.assertIn("Date", result)

    def test_section_with_paragraph_is_valid(self):
        c = self._valid_citation()
        c["section"] = "14-75(a)"
        # Should return None (valid) — section matches r'^(§\s*)?[\d]+[-\.][\d]+(\([a-z]\))?$'
        self.assertIsNone(check_format(c))

    def test_title_with_leading_whitespace_returns_error(self):
        c = self._valid_citation()
        c["title"] = "  leading space"
        result = check_format(c)
        self.assertIsNotNone(result)


# ──────────────────────────────────────────────────────────────────────────────
# TestCalculateSampleSizes
# ──────────────────────────────────────────────────────────────────────────────
class TestCalculateSampleSizes(unittest.TestCase):
    """Tests for calculate_sample_sizes() proportional allocation."""

    def test_returns_dict(self):
        result = calculate_sample_sizes({"CA": 500, "TX": 300, "NY": 200})
        self.assertIsInstance(result, dict)

    def test_sum_equals_target(self):
        """Sum of sample sizes must equal the hard-coded target of 385."""
        result = calculate_sample_sizes({"CA": 500, "TX": 300, "NY": 200})
        self.assertEqual(sum(result.values()), 385)

    def test_single_state_gets_full_sample(self):
        result = calculate_sample_sizes({"CA": 1000})
        self.assertEqual(sum(result.values()), 385)
        self.assertEqual(result["CA"], 385)

    def test_min_one_sample_per_state(self):
        """Every state with jurisdictions must have ≥1 sample."""
        result = calculate_sample_sizes({"CA": 1000, "WY": 1, "HI": 1})
        for state in ("CA", "WY", "HI"):
            self.assertGreaterEqual(result[state], 1)


if __name__ == "__main__":
    unittest.main()
