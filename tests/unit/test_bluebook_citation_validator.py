"""Comprehensive tests for the Bluebook citation validator package.

Covers 30+ test cases across all checker functions, the StratifiedSampler,
ConfusionMatrixStats, ValidatorConfig, and the deprecation shim.

All database calls are mocked so that tests run without any external
infrastructure (no DuckDB, MySQL, or parquet files required).
"""

from __future__ import annotations

import warnings
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from ipfs_datasets_py.processors.legal_scrapers.bluebook_citation_validator import (
    ValidatorConfig,
    ConfusionMatrixStats,
    check_geography,
    check_code_type,
    check_section,
    check_date,
    check_format,
)
from ipfs_datasets_py.processors.legal_scrapers.bluebook_citation_validator.sampling import (
    StratifiedSampler,
)
from ipfs_datasets_py.processors.legal_scrapers.bluebook_citation_validator.analysis import (
    calculate_accuracy_statistics,
    analyze_error_patterns,
    ExtrapolateToFullDataset,
    ResultsAnalyzer,
)
from ipfs_datasets_py.processors.legal_scrapers.bluebook_citation_validator.database import (
    make_cid,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _make_db(result=None):
    """Return a minimal mock database connection."""
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = result
    db.execute.return_value.fetchall.return_value = []
    db.execute.return_value.fetchdf.return_value = _empty_df()
    return db


def _empty_df():
    """Return a minimal pandas-like object with .to_dict()."""
    try:
        import pandas as pd
        return pd.DataFrame({"state_code": [], "counts": []})
    except ImportError:
        mock = MagicMock()
        mock.to_dict.return_value = []
        return mock


# ===========================================================================
# check_format tests
# ===========================================================================

class TestCheckFormat:
    """Tests for :func:`check_format` (Bluebook Rule 12.9)."""

    def test_valid_citation(self):
        citation = {"bluebook_citation": "Garland, Ark., County Code, §14-75 (2007)"}
        assert check_format(citation) is None

    def test_valid_municipal_code(self):
        citation = {"bluebook_citation": "Austin, Tex., Municipal Code, §1-100 (2020)"}
        assert check_format(citation) is None

    def test_missing_field(self):
        assert check_format({}) is not None

    def test_missing_comma_between_place_and_state(self):
        citation = {"bluebook_citation": "Garland Ark., County Code, §14-75 (2007)"}
        assert check_format(citation) is not None

    def test_wrong_state_abbreviation(self):
        # "Arkansas" is not a Bluebook abbreviation — should be "Ark."
        citation = {"bluebook_citation": "Garland, Arkansas, County Code, §14-75 (2007)"}
        assert check_format(citation) is not None

    def test_invalid_year_too_old(self):
        citation = {"bluebook_citation": "Garland, Ark., County Code, §14-75 (1200)"}
        assert check_format(citation) is not None

    def test_invalid_year_future(self):
        citation = {"bluebook_citation": "Garland, Ark., County Code, §14-75 (2099)"}
        assert check_format(citation) is not None

    def test_missing_section_symbol(self):
        citation = {"bluebook_citation": "Garland, Ark., County Code, 14-75 (2007)"}
        assert check_format(citation) is not None

    def test_wrong_code_type(self):
        citation = {"bluebook_citation": "Garland, Ark., State Code, §14-75 (2007)"}
        assert check_format(citation) is not None

    def test_missing_year_parentheses(self):
        citation = {"bluebook_citation": "Garland, Ark., County Code, §14-75 2007"}
        assert check_format(citation) is not None

    def test_city_code_type_valid(self):
        citation = {"bluebook_citation": "Denver, Colo., City Code, §1-10 (2015)"}
        assert check_format(citation) is None

    def test_dc_abbreviation(self):
        citation = {"bluebook_citation": "Washington, D.C., Municipal Code, §1-1 (2010)"}
        assert check_format(citation) is None

    def test_two_word_state_abbreviation(self):
        # "W. Va." is a two-word abbreviation
        citation = {"bluebook_citation": "Charleston, W. Va., Municipal Code, §5-1 (2018)"}
        assert check_format(citation) is None

    def test_section_with_period_separator(self):
        citation = {"bluebook_citation": "Salem, Or., Municipal Code, §1.2 (2019)"}
        assert check_format(citation) is None


# ===========================================================================
# check_geography tests
# ===========================================================================

class TestCheckGeography:
    """Tests for :func:`check_geography`."""

    def test_matching_state_returns_none(self):
        db = _make_db(result=("Ark.",))
        citation = {"gnis": 123, "bluebook_state_code": "Ark."}
        assert check_geography(citation, db) is None

    def test_case_insensitive_match(self):
        db = _make_db(result=("ARK.",))
        citation = {"gnis": 123, "bluebook_state_code": "ark."}
        assert check_geography(citation, db) is None

    def test_mismatched_state_returns_error(self):
        db = _make_db(result=("Tex.",))
        citation = {"gnis": 123, "bluebook_state_code": "Ark."}
        result = check_geography(citation, db)
        assert result is not None
        assert "mismatch" in result.lower()

    def test_missing_gnis_returns_error(self):
        db = _make_db()
        citation = {"bluebook_state_code": "Ark."}
        result = check_geography(citation, db)
        assert result is not None

    def test_missing_state_code_returns_error(self):
        db = _make_db()
        citation = {"gnis": 123}
        result = check_geography(citation, db)
        assert result is not None

    def test_gnis_not_found_in_db(self):
        db = _make_db(result=None)
        citation = {"gnis": 999, "bluebook_state_code": "Ark."}
        result = check_geography(citation, db)
        assert result is not None
        assert "not found" in result.lower()

    def test_db_exception_returns_error_string(self):
        db = MagicMock()
        db.execute.side_effect = Exception("connection lost")
        citation = {"gnis": 1, "bluebook_state_code": "Ark."}
        result = check_geography(citation, db)
        assert result is not None
        assert isinstance(result, str)

    def test_uses_bluebook_state_code_not_state(self):
        """Bug #21 fix: must use 'bluebook_state_code', not 'state'."""
        db = _make_db(result=("Ark.",))
        # Citation has 'state' but NOT 'bluebook_state_code' — should fail.
        citation = {"gnis": 1, "state": "Ark."}
        result = check_geography(citation, db)
        assert result is not None  # missing bluebook_state_code → error


# ===========================================================================
# check_code_type tests
# ===========================================================================

class TestCheckCodeType:
    """Tests for :func:`check_code_type`."""

    def test_c1_municipal_code_passes(self):
        db = _make_db(result=("C1",))
        citation = {"gnis": 1, "code_type": "Municipal Code"}
        assert check_code_type(citation, db) is None

    def test_h1_county_code_passes(self):
        db = _make_db(result=("H1",))
        citation = {"gnis": 1, "code_type": "County Code"}
        assert check_code_type(citation, db) is None

    def test_c1_with_county_code_fails(self):
        db = _make_db(result=("C1",))
        citation = {"gnis": 1, "code_type": "County Code"}
        result = check_code_type(citation, db)
        assert result is not None
        assert "mismatch" in result.lower()

    def test_h4_county_code_passes(self):
        db = _make_db(result=("H4",))
        citation = {"gnis": 1, "code_type": "County Code"}
        assert check_code_type(citation, db) is None

    def test_c8_consolidated_accepts_municipal(self):
        db = _make_db(result=("C8",))
        citation = {"gnis": 1, "code_type": "Municipal Code"}
        assert check_code_type(citation, db) is None

    def test_c8_consolidated_accepts_county(self):
        db = _make_db(result=("C8",))
        citation = {"gnis": 1, "code_type": "County Code"}
        assert check_code_type(citation, db) is None

    def test_unknown_class_code_returns_error(self):
        db = _make_db(result=("ZZ",))
        citation = {"gnis": 1, "code_type": "Municipal Code"}
        result = check_code_type(citation, db)
        assert result is not None

    def test_missing_gnis_returns_error(self):
        db = _make_db()
        citation = {"code_type": "Municipal Code"}
        assert check_code_type(citation, db) is not None

    def test_gnis_not_in_db_returns_error(self):
        db = _make_db(result=None)
        citation = {"gnis": 999, "code_type": "Municipal Code"}
        result = check_code_type(citation, db)
        assert result is not None


# ===========================================================================
# check_section tests
# ===========================================================================

class TestCheckSection:
    """Tests for :func:`check_section`."""

    def test_section_found_in_doc(self):
        citation = {"title_num": "14-75"}
        docs = [{"html_body": "... §14-75 discusses permits ..."}]
        assert check_section(citation, docs) is None

    def test_section_not_found_returns_error(self):
        citation = {"title_num": "99-99"}
        docs = [{"html_body": "This document has no matching section."}]
        result = check_section(citation, docs)
        assert result is not None

    def test_empty_documents_returns_error(self):
        citation = {"title_num": "1-1"}
        result = check_section(citation, [])
        assert result is not None

    def test_section_from_bluebook_citation(self):
        citation = {"bluebook_citation": "Austin, Tex., Municipal Code, §5-3 (2020)"}
        docs = [{"html_body": "Refer to section 5-3 for details."}]
        assert check_section(citation, docs) is None

    def test_multiple_docs_found_in_second(self):
        citation = {"title_num": "7-1"}
        docs = [
            {"html_body": "Nothing relevant here."},
            {"html_body": "See §7-1 for requirements."},
        ]
        assert check_section(citation, docs) is None

    def test_missing_section_info_returns_error(self):
        citation = {}  # no title_num, no bluebook_citation
        docs = [{"html_body": "Some content."}]
        assert check_section(citation, docs) is not None

    def test_doc_with_content_field(self):
        citation = {"title_num": "3-2"}
        docs = [{"content": "§3-2 of the municipal code provides..."}]
        assert check_section(citation, docs) is None


# ===========================================================================
# check_date tests
# ===========================================================================

class TestCheckDate:
    """Tests for :func:`check_date`."""

    def test_valid_year_in_range(self):
        citation = {"bluebook_citation": "Austin, Tex., Municipal Code, §1-1 (2020)"}
        assert check_date(citation) is None

    def test_year_too_old(self):
        citation = {"bluebook_citation": "Austin, Tex., Municipal Code, §1-1 (1200)"}
        result = check_date(citation)
        assert result is not None
        assert "range" in result.lower() or "1200" in result

    def test_year_too_future(self):
        citation = {"date": "2099"}
        result = check_date(citation)
        assert result is not None

    def test_year_mismatch_between_citation_and_metadata(self):
        citation = {
            "bluebook_citation": "Austin, Tex., Municipal Code, §1-1 (2020)",
            "date": "2019",
        }
        result = check_date(citation)
        assert result is not None
        assert "mismatch" in result.lower()

    def test_year_match_citation_and_metadata(self):
        citation = {
            "bluebook_citation": "Austin, Tex., Municipal Code, §1-1 (2020)",
            "date": "2020",
        }
        assert check_date(citation) is None

    def test_document_cross_reference_found(self):
        citation = {"date": "2010"}
        docs = [{"html_body": "Revised in 2010 by council ordinance."}]
        assert check_date(citation, docs) is None

    def test_document_cross_reference_not_found(self):
        citation = {"date": "2010"}
        docs = [{"html_body": "No date information here."}]
        result = check_date(citation, docs)
        assert result is not None

    def test_no_date_info_returns_error(self):
        citation = {}
        result = check_date(citation)
        assert result is not None

    def test_integer_year_field(self):
        citation = {"year": 2005}
        assert check_date(citation) is None

    def test_returns_none_not_success_string(self):
        """Bug #9 fix: must return None (not 'Date check passed') on success."""
        citation = {"date": "2015"}
        result = check_date(citation)
        assert result is None


# ===========================================================================
# StratifiedSampler._calculate_sample_sizes tests
# ===========================================================================

class TestCalculateSampleSizes:
    """Tests for :meth:`StratifiedSampler._calculate_sample_sizes`."""

    def _sampler(self, sample_size=385):
        config = ValidatorConfig(sample_size=sample_size)
        return StratifiedSampler(config)

    def test_proportional_allocation(self):
        sampler = self._sampler(sample_size=100)
        counts = {"CA": 200, "TX": 200, "NY": 100}
        result = sampler._calculate_sample_sizes(counts)
        assert sum(result.values()) == 100

    def test_minimum_one_per_state(self):
        sampler = self._sampler(sample_size=10)
        # 50 states, tiny sample — each must get at least 1
        counts = {f"S{i}": 100 for i in range(10)}
        result = sampler._calculate_sample_sizes(counts)
        assert all(v >= 1 for v in result.values())

    def test_rounding_hits_exact_target(self):
        sampler = self._sampler(sample_size=385)
        counts = {"CA": 5000, "TX": 4000, "FL": 3000, "NY": 2000, "PA": 1000}
        result = sampler._calculate_sample_sizes(counts)
        assert sum(result.values()) == 385

    def test_empty_counts_returns_empty(self):
        sampler = self._sampler()
        result = sampler._calculate_sample_sizes({})
        assert result == {}

    def test_single_state_gets_full_sample(self):
        sampler = self._sampler(sample_size=50)
        result = sampler._calculate_sample_sizes({"CA": 1000})
        assert result["CA"] == 50


# ===========================================================================
# ConfusionMatrixStats tests
# ===========================================================================

class TestConfusionMatrixStats:
    """Tests for :class:`ConfusionMatrixStats`."""

    def _stats(self, tp=80, fp=10, tn=90, fn=20):
        return ConfusionMatrixStats(
            true_positives=tp,
            false_positives=fp,
            true_negatives=tn,
            false_negatives=fn,
        )

    def test_total(self):
        s = self._stats(tp=80, fp=10, tn=90, fn=20)
        assert s.total == 200

    def test_accuracy(self):
        s = self._stats(tp=80, fp=10, tn=90, fn=20)
        assert abs(s.accuracy - 0.85) < 1e-9

    def test_precision(self):
        s = self._stats(tp=80, fp=10, tn=90, fn=20)
        assert abs(s.precision - 80 / 90) < 1e-9

    def test_true_positive_rate_alias_recall(self):
        s = self._stats(tp=80, fp=10, tn=90, fn=20)
        assert s.true_positive_rate == s.recall

    def test_recall(self):
        s = self._stats(tp=80, fp=0, tn=90, fn=20)
        assert abs(s.recall - 80 / 100) < 1e-9

    def test_f1_score(self):
        s = self._stats(tp=80, fp=10, tn=90, fn=20)
        p = s.precision
        r = s.recall
        expected = 2 * p * r / (p + r)
        assert abs(s.f1_score - expected) < 1e-9

    def test_zero_division_precision(self):
        s = ConfusionMatrixStats(0, 0, 100, 0)
        assert s.precision == 0.0

    def test_zero_division_recall(self):
        s = ConfusionMatrixStats(0, 10, 90, 0)
        assert s.recall == 0.0


# ===========================================================================
# ValidatorConfig tests
# ===========================================================================

class TestValidatorConfig:
    """Tests for :class:`ValidatorConfig`."""

    def test_defaults(self):
        c = ValidatorConfig()
        assert c.sample_size == 385
        assert c.max_concurrency == 8
        assert c.random_seed == 420
        assert c.insert_batch_size == 5000

    def test_dict_access(self):
        c = ValidatorConfig(sample_size=100)
        assert c["sample_size"] == 100

    def test_dict_access_missing_key_raises(self):
        c = ValidatorConfig()
        with pytest.raises(KeyError):
            _ = c["nonexistent_key"]

    def test_path_coercion_from_string(self):
        from pathlib import Path
        c = ValidatorConfig(citation_dir="/tmp/cites")
        assert isinstance(c.citation_dir, Path)

    def test_mysql_configs_property(self):
        c = ValidatorConfig(
            mysql_host="db.example.com",
            mysql_user="admin",
            mysql_password="secret",
            mysql_database="mydb",
        )
        cfg = c.mysql_configs
        assert cfg["host"] == "db.example.com"
        assert cfg["user"] == "admin"


# ===========================================================================
# make_cid tests
# ===========================================================================

class TestMakeCid:
    def test_returns_32_char_hex(self):
        result = make_cid("hello world")
        assert len(result) == 32
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self):
        assert make_cid("test") == make_cid("test")

    def test_different_inputs_differ(self):
        assert make_cid("foo") != make_cid("bar")


# ===========================================================================
# calculate_accuracy_statistics tests
# ===========================================================================

class TestCalculateAccuracyStatistics:
    def test_basic(self):
        stats = calculate_accuracy_statistics(total_citations=200, total_errors=20)
        assert stats.total == 200
        assert stats.true_positives == 20
        assert stats.true_negatives == 180
        assert stats.false_negatives == 0

    def test_zero_errors(self):
        stats = calculate_accuracy_statistics(100, 0)
        assert stats.accuracy == 1.0

    def test_all_errors(self):
        stats = calculate_accuracy_statistics(100, 100)
        assert stats.true_negatives == 0


# ===========================================================================
# ExtrapolateToFullDataset tests
# ===========================================================================

class TestExtrapolateToFullDataset:
    def _run(self, tp=80, fp=0, tn=120, fn=0):
        stats = ConfusionMatrixStats(tp, fp, tn, fn)
        extrap = ExtrapolateToFullDataset()
        gnis_counts = {"CA": 5000, "TX": 4000, "FL": 3000}
        return extrap.extrapolate(stats, gnis_counts, sample_size=stats.total)

    def test_returns_dict_with_estimated_accuracy(self):
        result = self._run()
        assert "estimated_accuracy" in result

    def test_confidence_interval_ordered(self):
        result = self._run()
        assert result["confidence_interval_lower"] <= result["confidence_interval_upper"]

    def test_total_estimated_records(self):
        result = self._run()
        assert result["total_estimated_records"] == 12000

    def test_reliability_label_high(self):
        result = self._run(tp=308, fp=0, tn=77, fn=0)
        assert result["extrapolation_reliability"] == "high"

    def test_raises_on_zero_sample_size(self):
        with pytest.raises(ValueError):
            ExtrapolateToFullDataset().extrapolate(
                ConfusionMatrixStats(0, 0, 0, 0), {"CA": 100}, sample_size=0
            )

    def test_raises_on_empty_gnis_counts(self):
        with pytest.raises(ValueError):
            stats = ConfusionMatrixStats(10, 0, 90, 0)
            ExtrapolateToFullDataset().extrapolate(stats, {}, sample_size=100)


# ===========================================================================
# Deprecation shim test
# ===========================================================================

class TestDeprecationShim:
    def test_import_raises_deprecation_warning(self):
        import importlib
        import sys

        mod_name = (
            "ipfs_datasets_py.mcp_server.tools"
            ".lizardperson_argparse_programs"
            ".municipal_bluebook_citation_validator"
        )
        # Remove cached module so warnings fire.
        sys.modules.pop(mod_name, None)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            importlib.import_module(mod_name)
            dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
            assert len(dep_warnings) >= 1
            assert "deprecated" in str(dep_warnings[0].message).lower()

    def test_shim_exports_validator_config(self):
        """The shim must re-export ValidatorConfig."""
        import importlib
        import sys

        mod_name = (
            "ipfs_datasets_py.mcp_server.tools"
            ".lizardperson_argparse_programs"
            ".municipal_bluebook_citation_validator"
        )
        sys.modules.pop(mod_name, None)
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            mod = importlib.import_module(mod_name)

        assert hasattr(mod, "ValidatorConfig")
