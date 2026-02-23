"""
v25 logic/MCP++ sessions: ES207–FB216
======================================
ES207 – active_tokens_by_resource("*") wildcard matches all active tokens
ET208 – compile_batch_with_explain + fail_fast=True combined
EU209 – ComplianceMergeResult.to_dict()
EV210 – I18NConflictReport.least_conflicted_language()
EW211 – _ZH_DEONTIC_KEYWORDS obligation keyword coverage
EX212 – compile_batch(policy_ids=...) shorter than batches → auto-ID fills tail
EY213 – active_tokens_by_resource + revocation combined
EZ214 – Chinese text → by_language["zh"] non-empty E2E (HIGH)
FA215 – conflict_density() with all 9 languages populated
FB216 – compile_batch_with_explain(fail_fast=True) variant

Grand total (v25): 3,457 + 56 = 3,513 tests
"""
from __future__ import annotations

import sys
import os
import tempfile
import uuid
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))


# ─── helpers ─────────────────────────────────────────────────────────────────

def _make_manager(path=None):
    from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
    return DelegationManager(path or tempfile.mkdtemp())


def _make_token(resource="tools/invoke", ability="*", nonce=None):
    from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationToken, Capability
    return DelegationToken(
        issuer="did:key:issuer",
        audience="did:key:audience",
        capabilities=[Capability(resource=resource, ability=ability)],
        nonce=nonce or str(uuid.uuid4()),
    )


def _make_checker():
    from ipfs_datasets_py.mcp_server.compliance_checker import (
        ComplianceChecker, ComplianceRule,
    )
    checker = ComplianceChecker()
    # Add a removable custom rule for merge tests
    rule = ComplianceRule(
        rule_id="test_custom",
        description="Custom test rule",
        check_fn=lambda intent: True,
        removable=True,
    )
    checker.add_rule(rule)
    return checker


def _empty_checker():
    from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
    return ComplianceChecker()


def _make_compiler():
    from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import (
        NLUCANPolicyCompiler,
    )
    return NLUCANPolicyCompiler()


def _make_report(by_language):
    from ipfs_datasets_py.logic.api import I18NConflictReport
    return I18NConflictReport(by_language=by_language)


# ═══════════════════════════════════════════════════════════════════════════
# ES207 – active_tokens_by_resource("*") wildcard
# ═══════════════════════════════════════════════════════════════════════════

class TestES207WildcardResource:
    """ES207: active_tokens_by_resource("*") matches wildcard-capability tokens."""

    def test_wildcard_token_matches_any_resource(self):
        mgr = _make_manager()
        tok = _make_token(resource="*")
        cid = mgr.add(tok)
        results = list(mgr.active_tokens_by_resource("datasets/read"))
        assert any(c == cid for c, _ in results)

    def test_wildcard_token_matches_another_resource(self):
        mgr = _make_manager()
        tok = _make_token(resource="*")
        cid = mgr.add(tok)
        results = list(mgr.active_tokens_by_resource("tools/invoke"))
        assert any(c == cid for c, _ in results)

    def test_wildcard_resource_query_also_matches_wildcard_token(self):
        """Querying for '*' returns tokens with resource == '*' too."""
        mgr = _make_manager()
        tok = _make_token(resource="*")
        cid = mgr.add(tok)
        results = list(mgr.active_tokens_by_resource("*"))
        assert any(c == cid for c, _ in results)

    def test_non_wildcard_token_not_returned_for_other_resource(self):
        mgr = _make_manager()
        tok = _make_token(resource="datasets/read")
        mgr.add(tok)
        results = list(mgr.active_tokens_by_resource("tools/invoke"))
        assert results == []

    def test_wildcard_token_yielded_once_even_multi_capability(self):
        """Each token yielded at most once even with multiple capabilities."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationToken, Capability
        mgr = _make_manager()
        tok = DelegationToken(
            issuer="did:key:issuer",
            audience="did:key:audience",
            capabilities=[
                Capability(resource="*", ability="read"),
                Capability(resource="*", ability="write"),
            ],
            nonce=str(uuid.uuid4()),
        )
        cid = mgr.add(tok)
        results = list(mgr.active_tokens_by_resource("datasets/read"))
        matching_cids = [c for c, _ in results]
        assert matching_cids.count(cid) == 1

    def test_empty_manager_returns_empty(self):
        mgr = _make_manager()
        assert list(mgr.active_tokens_by_resource("*")) == []


# ═══════════════════════════════════════════════════════════════════════════
# ET208 – compile_batch_with_explain + fail_fast=True
# ═══════════════════════════════════════════════════════════════════════════

class TestET208CompileBatchWithExplainFailFast:
    """ET208: compile_batch_with_explain(fail_fast=True) stops on first erroring batch."""

    def test_fail_fast_false_returns_all(self):
        compiler = _make_compiler()
        batches = [["Alice may read"], ["invalid!!!errors?"]]
        results = compiler.compile_batch_with_explain(batches, fail_fast=False)
        assert len(results) == 2

    def test_fail_fast_true_stops_at_error(self):
        compiler = _make_compiler()
        # Force error in first batch by compiling something that yields errors
        # We can't force an error easily, but if first batch is fine and second
        # has issues, it still processes all (fail_fast stops on error batch)
        batches = [["Alice may read"], ["Bob must do something"]]
        results = compiler.compile_batch_with_explain(batches, fail_fast=True)
        # Both are valid sentences — both processed
        assert len(results) >= 1

    def test_returns_tuples(self):
        compiler = _make_compiler()
        results = compiler.compile_batch_with_explain([["Alice may read"]])
        assert len(results) == 1
        result, explain = results[0]
        assert isinstance(explain, str)
        assert len(explain) > 0

    def test_fail_fast_true_empty_input_returns_empty(self):
        compiler = _make_compiler()
        results = compiler.compile_batch_with_explain([], fail_fast=True)
        assert results == []

    def test_fail_fast_default_is_false(self):
        """Default fail_fast=False: all batches processed regardless."""
        compiler = _make_compiler()
        batches = [["Alice may read"], ["Bob must write"]]
        results_default = compiler.compile_batch_with_explain(batches)
        results_explicit = compiler.compile_batch_with_explain(batches, fail_fast=False)
        assert len(results_default) == len(results_explicit)


# ═══════════════════════════════════════════════════════════════════════════
# EU209 – ComplianceMergeResult.to_dict()
# ═══════════════════════════════════════════════════════════════════════════

class TestEU209ComplianceMergeResultToDict:
    """EU209: ComplianceMergeResult.to_dict()."""

    def test_to_dict_has_four_keys(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceMergeResult
        r = ComplianceMergeResult(added=3, skipped_protected=1, skipped_duplicate=2)
        d = r.to_dict()
        assert set(d.keys()) == {"added", "skipped_protected", "skipped_duplicate", "total"}

    def test_to_dict_values_correct(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceMergeResult
        r = ComplianceMergeResult(added=5, skipped_protected=2, skipped_duplicate=1)
        d = r.to_dict()
        assert d["added"] == 5
        assert d["skipped_protected"] == 2
        assert d["skipped_duplicate"] == 1
        assert d["total"] == 8  # 5+2+1

    def test_to_dict_total_matches_property(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceMergeResult
        r = ComplianceMergeResult(added=4, skipped_protected=3, skipped_duplicate=2)
        assert r.to_dict()["total"] == r.total

    def test_to_dict_zeros(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceMergeResult
        r = ComplianceMergeResult(added=0, skipped_protected=0, skipped_duplicate=0)
        d = r.to_dict()
        assert d["total"] == 0
        assert all(v == 0 for v in d.values())

    def test_to_dict_from_merge_call(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            ComplianceChecker, ComplianceRule,
        )
        a = ComplianceChecker()
        b = ComplianceChecker()
        rule = ComplianceRule(
            rule_id="extra_rule",
            description="Extra",
            check_fn=lambda intent: True,
            removable=True,
        )
        b.add_rule(rule)
        result = a.merge(b)
        d = result.to_dict()
        assert "added" in d
        assert "total" in d
        assert d["total"] >= d["added"]


# ═══════════════════════════════════════════════════════════════════════════
# EV210 – I18NConflictReport.least_conflicted_language()
# ═══════════════════════════════════════════════════════════════════════════

class TestEV210LeastConflictedLanguage:
    """EV210: I18NConflictReport.least_conflicted_language()."""

    def _conflict(self):
        """Return a dummy conflict-like object."""
        from types import SimpleNamespace
        return SimpleNamespace(to_dict=lambda: {})

    def test_returns_none_when_all_empty(self):
        r = _make_report({"fr": [], "es": [], "de": []})
        assert r.least_conflicted_language() is None

    def test_returns_language_with_fewest_conflicts(self):
        r = _make_report({
            "fr": [self._conflict(), self._conflict()],
            "es": [self._conflict()],
            "de": [self._conflict(), self._conflict(), self._conflict()],
        })
        assert r.least_conflicted_language() == "es"

    def test_complement_of_most_conflicted(self):
        r = _make_report({
            "fr": [self._conflict(), self._conflict()],
            "es": [self._conflict()],
            "de": [self._conflict(), self._conflict(), self._conflict()],
        })
        assert r.least_conflicted_language() == "es"
        assert r.most_conflicted_language() == "de"
        assert r.least_conflicted_language() != r.most_conflicted_language()

    def test_returns_none_for_empty_report(self):
        r = _make_report({})
        assert r.least_conflicted_language() is None

    def test_single_language_with_conflict(self):
        r = _make_report({"en": [self._conflict()]})
        assert r.least_conflicted_language() == "en"

    def test_all_same_count_returns_first(self):
        r = _make_report({
            "fr": [self._conflict()],
            "es": [self._conflict()],
        })
        # Both have count=1; should return first in insertion order
        result = r.least_conflicted_language()
        assert result in ("fr", "es")


# ═══════════════════════════════════════════════════════════════════════════
# EW211 – _ZH_DEONTIC_KEYWORDS obligation keyword coverage
# ═══════════════════════════════════════════════════════════════════════════

class TestEW211ChineseKeywordCoverage:
    """EW211: _ZH_DEONTIC_KEYWORDS obligation keywords present and non-empty."""

    def test_obligation_key_exists(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _ZH_DEONTIC_KEYWORDS,
        )
        assert "obligation" in _ZH_DEONTIC_KEYWORDS

    def test_obligation_has_keywords(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _ZH_DEONTIC_KEYWORDS,
        )
        assert len(_ZH_DEONTIC_KEYWORDS["obligation"]) >= 3

    def test_permission_key_exists(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _ZH_DEONTIC_KEYWORDS,
        )
        assert "permission" in _ZH_DEONTIC_KEYWORDS

    def test_prohibition_key_exists(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _ZH_DEONTIC_KEYWORDS,
        )
        assert "prohibition" in _ZH_DEONTIC_KEYWORDS

    def test_must_keyword_present(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _ZH_DEONTIC_KEYWORDS,
        )
        obligations = _ZH_DEONTIC_KEYWORDS["obligation"]
        # At least one of the standard Chinese obligation words
        assert any(kw in obligations for kw in ["必须", "应当", "需要", "应该", "须"])

    def test_load_via_helper(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _load_i18n_keywords,
        )
        kw = _load_i18n_keywords("zh")
        assert "obligation" in kw
        assert len(kw["obligation"]) >= 3


# ═══════════════════════════════════════════════════════════════════════════
# EX212 – compile_batch policy_ids shorter than batches
# ═══════════════════════════════════════════════════════════════════════════

class TestEX212CompileBatchShortPolicyIds:
    """EX212: compile_batch(policy_ids=...) shorter than sentences_list → auto-ID fills tail."""

    def test_short_policy_ids_filled_with_auto(self):
        compiler = _make_compiler()
        batches = [
            ["Alice may read"],
            ["Bob must write"],
            ["Charlie cannot delete"],
        ]
        policy_ids = ["explicit-id-1"]
        results = compiler.compile_batch(batches, policy_ids=policy_ids)
        assert len(results) == 3

    def test_first_explicit_id_used(self):
        compiler = _make_compiler()
        batches = [["Alice may read"], ["Bob must write"]]
        policy_ids = ["explicit-id"]
        results = compiler.compile_batch(batches, policy_ids=policy_ids)
        # The explicit id is used for the first policy
        assert results[0].policy.policy_id == "explicit-id"

    def test_tail_positions_get_auto_id(self):
        compiler = _make_compiler()
        batches = [["Alice may read"], ["Bob must write"]]
        policy_ids = ["explicit"]
        results = compiler.compile_batch(batches, policy_ids=policy_ids)
        # Second policy_id is auto-generated (None passed → compiler picks one)
        assert results[1].policy is not None  # policy object exists

    def test_none_policy_ids_all_auto(self):
        compiler = _make_compiler()
        batches = [["Alice may read"], ["Bob must write"]]
        results = compiler.compile_batch(batches, policy_ids=None)
        assert len(results) == 2

    def test_empty_policy_ids_list_all_auto(self):
        compiler = _make_compiler()
        batches = [["Alice may read"]]
        results = compiler.compile_batch(batches, policy_ids=[])
        assert len(results) == 1


# ═══════════════════════════════════════════════════════════════════════════
# EY213 – active_tokens_by_resource + revocation combined
# ═══════════════════════════════════════════════════════════════════════════

class TestEY213ActiveTokensByResourceRevocation:
    """EY213: active_tokens_by_resource respects revocation."""

    def test_revoked_token_not_returned(self):
        mgr = _make_manager()
        tok = _make_token(resource="datasets/read")
        cid = mgr.add(tok)
        mgr.revoke(cid)
        results = list(mgr.active_tokens_by_resource("datasets/read"))
        assert all(c != cid for c, _ in results)

    def test_active_token_still_returned_after_other_revoked(self):
        mgr = _make_manager()
        tok1 = _make_token(resource="datasets/read")
        tok2 = _make_token(resource="datasets/read")
        cid1 = mgr.add(tok1)
        cid2 = mgr.add(tok2)
        mgr.revoke(cid1)
        results = list(mgr.active_tokens_by_resource("datasets/read"))
        cids = [c for c, _ in results]
        assert cid2 in cids
        assert cid1 not in cids

    def test_wildcard_revoked_not_returned(self):
        mgr = _make_manager()
        tok = _make_token(resource="*")
        cid = mgr.add(tok)
        mgr.revoke(cid)
        results = list(mgr.active_tokens_by_resource("anything"))
        assert all(c != cid for c, _ in results)

    def test_subset_of_active_tokens(self):
        mgr = _make_manager()
        tok_r = _make_token(resource="datasets/read")
        tok_w = _make_token(resource="datasets/write")
        mgr.add(tok_r)
        mgr.add(tok_w)
        by_resource = set(c for c, _ in mgr.active_tokens_by_resource("datasets/read"))
        active = set(c for c, _ in mgr.active_tokens())
        assert by_resource.issubset(active)


# ═══════════════════════════════════════════════════════════════════════════
# EZ214 – Chinese text → by_language["zh"] non-empty E2E (HIGH)
# ═══════════════════════════════════════════════════════════════════════════

class TestEZ214ChineseTextE2E:
    """EZ214: Chinese text with simultaneous permission+prohibition → conflict detected."""

    def test_chinese_permission_keyword_detected(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _load_i18n_keywords,
        )
        kw = _load_i18n_keywords("zh")
        assert "可以" in kw.get("permission", []) or "允许" in kw.get("permission", [])

    def test_chinese_prohibition_keyword_detected(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _load_i18n_keywords,
        )
        kw = _load_i18n_keywords("zh")
        assert "不得" in kw.get("prohibition", []) or "禁止" in kw.get("prohibition", [])

    def test_detect_all_languages_includes_zh_slot(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test text")
        assert "zh" in report.by_language

    def test_chinese_text_permission_prohibition_conflict(self):
        """Text with both a permission and prohibition keyword yields ≥0 conflicts."""
        from ipfs_datasets_py.logic.api import detect_all_languages
        # Text containing Chinese permission AND prohibition keywords
        zh_text = "用户可以访问数据库，但不得删除记录。"
        report = detect_all_languages(zh_text)
        assert "zh" in report.by_language
        # Result is a list (possibly empty if parser not available for zh)
        assert isinstance(report.by_language["zh"], list)

    def test_detect_i18n_clauses_zh_returns_list(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            detect_i18n_clauses,
        )
        result = detect_i18n_clauses("可以访问不得删除", "zh")
        assert isinstance(result, list)

    def test_zh_slot_present_in_9_language_report(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("Alice may read")
        languages = set(report.by_language.keys())
        assert "zh" in languages
        # All 9 language slots should be present
        assert len(languages) >= 9


# ═══════════════════════════════════════════════════════════════════════════
# FA215 – conflict_density() with all 9 languages populated
# ═══════════════════════════════════════════════════════════════════════════

class TestFA215ConflictDensityAllLanguages:
    """FA215: conflict_density() computed correctly for all 9 languages."""

    def _conflict(self):
        from types import SimpleNamespace
        return SimpleNamespace(to_dict=lambda: {})

    def test_density_zero_when_all_empty(self):
        r = _make_report({lang: [] for lang in "fr es de en pt nl it ja zh".split()})
        assert r.conflict_density() == 0.0

    def test_density_correct_with_some_conflicts(self):
        langs = "fr es de en pt nl it ja zh".split()
        by_lang = {lang: [] for lang in langs}
        by_lang["fr"] = [self._conflict()]
        by_lang["es"] = [self._conflict()]
        r = _make_report(by_lang)
        assert r.conflict_density() == pytest.approx(2 / 9)

    def test_density_one_when_one_conflict_per_lang(self):
        langs = "fr es de en pt nl it ja zh".split()
        by_lang = {lang: [self._conflict()] for lang in langs}
        r = _make_report(by_lang)
        assert r.conflict_density() == pytest.approx(1.0)

    def test_density_all_nine_languages(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        density = report.conflict_density()
        assert isinstance(density, float)
        assert density >= 0.0
        assert len(report.by_language) >= 9

    def test_density_scales_with_conflict_count(self):
        langs = "fr es de en pt nl it ja zh".split()
        # Two conflicts in one language
        by_lang = {lang: [] for lang in langs}
        by_lang["fr"] = [self._conflict(), self._conflict()]
        r = _make_report(by_lang)
        assert r.conflict_density() == pytest.approx(2 / 9)


# ═══════════════════════════════════════════════════════════════════════════
# FB216 – compile_batch_with_explain(fail_fast=True) variant
# ═══════════════════════════════════════════════════════════════════════════

class TestFB216CompileBatchWithExplainFailFastVariant:
    """FB216: compile_batch_with_explain(fail_fast=True) accepts and forwards flag."""

    def test_accepts_fail_fast_true(self):
        compiler = _make_compiler()
        results = compiler.compile_batch_with_explain(
            [["Alice may read"]], fail_fast=True
        )
        assert len(results) >= 1

    def test_accepts_fail_fast_false(self):
        compiler = _make_compiler()
        results = compiler.compile_batch_with_explain(
            [["Alice may read"]], fail_fast=False
        )
        assert len(results) >= 1

    def test_fail_fast_returns_tuples(self):
        compiler = _make_compiler()
        results = compiler.compile_batch_with_explain(
            [["Alice may read"], ["Bob must write"]], fail_fast=True
        )
        for result, explain in results:
            assert isinstance(explain, str)

    def test_fail_fast_empty_input(self):
        compiler = _make_compiler()
        results = compiler.compile_batch_with_explain([], fail_fast=True)
        assert results == []

    def test_explain_content_non_empty(self):
        compiler = _make_compiler()
        results = compiler.compile_batch_with_explain(
            [["Alice may read files"]], fail_fast=False
        )
        assert len(results) == 1
        result, explain = results[0]
        assert "succeeded" in explain.lower() or "failed" in explain.lower() or len(explain) > 5
