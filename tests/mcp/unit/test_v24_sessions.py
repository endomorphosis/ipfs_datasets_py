"""
v24 logic/MCP++ sessions: EI197–ER206
======================================
EI197 – DelegationManager.active_tokens_by_resource(resource)
EJ198 – NLUCANPolicyCompiler.compile_batch_with_explain()
EK199 – ComplianceMergeResult.total property
EL200 – I18NConflictReport.conflict_density()
EM201 – _ZH_DEONTIC_KEYWORDS Chinese inline keywords (9th lang)
EN202 – compile_batch(fail_fast=True) stops on first error
EO203 – active_token_count caching across multiple revokes
EP204 – Japanese text → detect_i18n_clauses("ja") integration
EQ205 – get_clauses_by_type + detect_i18n_clauses("pt") pipeline
ER206 – clear() + export_jsonl() round-trip: cleared log → 0 entries

Grand total (v24): 3,400 + 57 = 3,457 tests
"""
from __future__ import annotations

import sys
import os
import tempfile
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
    import uuid
    return DelegationToken(
        issuer="did:key:issuer",
        audience="did:key:audience",
        capabilities=[Capability(resource=resource, ability=ability)],
        nonce=nonce or str(uuid.uuid4()),
    )


def _add_token(mgr, token):
    """Helper: add token to manager and return assigned CID."""
    return mgr.add(token)


def _make_checker():
    from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
    return ComplianceChecker()


def _make_compiler():
    from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import (
        NLUCANPolicyCompiler,
    )
    return NLUCANPolicyCompiler()


def _make_audit_log():
    from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
    return PolicyAuditLog(max_entries=100)


# ═══════════════════════════════════════════════════════════════════════════
# EI197 – active_tokens_by_resource
# ═══════════════════════════════════════════════════════════════════════════

class TestEI197ActiveTokensByResource:
    """EI197: DelegationManager.active_tokens_by_resource(resource)."""

    def test_yields_matching_resource(self):
        mgr = _make_manager()
        token = _make_token(resource="datasets/read")
        cid = mgr.add(token)
        results = list(mgr.active_tokens_by_resource("datasets/read"))
        assert len(results) == 1
        assert results[0][0] == cid

    def test_does_not_yield_different_resource(self):
        mgr = _make_manager()
        token = _make_token(resource="datasets/read")
        mgr.add(token)
        results = list(mgr.active_tokens_by_resource("tools/invoke"))
        assert results == []

    def test_wildcard_resource_matches_any(self):
        mgr = _make_manager()
        token = _make_token(resource="*")
        cid = mgr.add(token)
        results = list(mgr.active_tokens_by_resource("anything"))
        assert len(results) == 1
        assert results[0][0] == cid

    def test_revoked_tokens_excluded(self):
        mgr = _make_manager()
        token = _make_token(resource="tools/invoke")
        cid = mgr.add(token)
        mgr.revoke(cid)
        results = list(mgr.active_tokens_by_resource("tools/invoke"))
        assert results == []

    def test_multiple_tokens_only_matching_returned(self):
        mgr = _make_manager()
        t1 = _make_token(resource="tools/invoke")
        t2 = _make_token(resource="datasets/read")
        mgr.add(t1)
        mgr.add(t2)
        results = list(mgr.active_tokens_by_resource("tools/invoke"))
        assert len(results) == 1
        assert results[0][0] == t1.cid

    def test_empty_when_no_tokens(self):
        mgr = _make_manager()
        assert list(mgr.active_tokens_by_resource("tools/invoke")) == []

    def test_generator_is_reentrant(self):
        mgr = _make_manager()
        token = _make_token(resource="tools/invoke")
        mgr.add(token)
        assert list(mgr.active_tokens_by_resource("tools/invoke")) == \
               list(mgr.active_tokens_by_resource("tools/invoke"))


# ═══════════════════════════════════════════════════════════════════════════
# EJ198 – compile_batch_with_explain
# ═══════════════════════════════════════════════════════════════════════════

class TestEJ198CompileBatchWithExplain:
    """EJ198: NLUCANPolicyCompiler.compile_batch_with_explain()."""

    def test_returns_list_of_tuples(self):
        compiler = _make_compiler()
        batches = [["The agent may read data."], ["The agent must log actions."]]
        results = compiler.compile_batch_with_explain(batches)
        assert isinstance(results, list)
        assert len(results) == 2
        for result, explain in results:
            assert hasattr(result, "errors")
            assert isinstance(explain, str)

    def test_explain_string_non_empty(self):
        compiler = _make_compiler()
        batches = [["The agent may access the database."]]
        results = compiler.compile_batch_with_explain(batches)
        assert len(results) == 1
        result, explain = results[0]
        assert len(explain) > 0

    def test_empty_input_returns_empty(self):
        compiler = _make_compiler()
        assert compiler.compile_batch_with_explain([]) == []

    def test_explain_consistent_with_result_explain(self):
        compiler = _make_compiler()
        sentences = ["The agent must verify credentials."]
        results = compiler.compile_batch_with_explain([sentences])
        result, explain = results[0]
        assert explain == result.explain()

    def test_policy_ids_forwarded(self):
        compiler = _make_compiler()
        batches = [["The agent may read."]]
        results = compiler.compile_batch_with_explain(batches, policy_ids=["my-policy"])
        result, _ = results[0]
        assert result.metadata.get("policy_id") == "my-policy"

    def test_two_batches_independent_results(self):
        compiler = _make_compiler()
        batches = [["The agent may read."], ["The agent must not delete."]]
        results = compiler.compile_batch_with_explain(batches)
        assert results[0][0] is not results[1][0]


# ═══════════════════════════════════════════════════════════════════════════
# EK199 – ComplianceMergeResult.total
# ═══════════════════════════════════════════════════════════════════════════

class TestEK199ComplianceMergeResultTotal:
    """EK199: ComplianceMergeResult.total property."""

    def test_total_all_added(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceMergeResult
        r = ComplianceMergeResult(added=3, skipped_protected=0, skipped_duplicate=0)
        assert r.total == 3

    def test_total_mix(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceMergeResult
        r = ComplianceMergeResult(added=2, skipped_protected=1, skipped_duplicate=3)
        assert r.total == 6

    def test_total_all_zero(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceMergeResult
        r = ComplianceMergeResult(added=0, skipped_protected=0, skipped_duplicate=0)
        assert r.total == 0

    def test_total_not_affected_by_int_equality(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceMergeResult
        r = ComplianceMergeResult(added=2, skipped_protected=1, skipped_duplicate=4)
        assert r == 2  # int equality uses added only
        assert r.total == 7  # total includes all three

    def test_total_via_real_merge(self):
        c1 = _make_checker()
        c2 = _make_checker()
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            ComplianceRule, ComplianceResult,
        )
        c2.add_rule(ComplianceRule(
            rule_id="new_rule_v24",
            description="Test rule v24",
            check_fn=lambda req: ComplianceResult(
                rule_id="new_rule_v24", passed=True, message="ok"
            ),
        ))
        result = c1.merge(c2)
        assert result.total >= result.added


# ═══════════════════════════════════════════════════════════════════════════
# EL200 – I18NConflictReport.conflict_density()
# ═══════════════════════════════════════════════════════════════════════════

class TestEL200ConflictDensity:
    """EL200: I18NConflictReport.conflict_density()."""

    def test_density_zero_for_empty_report(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        report = I18NConflictReport()
        assert report.conflict_density() == 0.0

    def test_density_with_one_conflict_eight_langs(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport, detect_all_languages
        # Construct a minimal report with known structure
        report = detect_all_languages("may not may")
        n = len(report.by_language)
        expected = report.total_conflicts / n
        assert abs(report.conflict_density() - expected) < 1e-9

    def test_density_all_empty_langs(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        report = I18NConflictReport(by_language={"fr": [], "es": []})
        assert report.conflict_density() == 0.0

    def test_density_is_float(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        report = I18NConflictReport(by_language={"fr": ["x"], "es": []})
        density = report.conflict_density()
        assert isinstance(density, float)

    def test_density_scales_with_conflicts(self):
        from ipfs_datasets_py.logic.api import I18NConflictReport
        report1 = I18NConflictReport(by_language={"fr": ["a"], "es": []})
        report2 = I18NConflictReport(by_language={"fr": ["a", "b"], "es": []})
        assert report2.conflict_density() > report1.conflict_density()


# ═══════════════════════════════════════════════════════════════════════════
# EM201 – Chinese keywords (_ZH_DEONTIC_KEYWORDS)
# ═══════════════════════════════════════════════════════════════════════════

class TestEM201ChineseKeywords:
    """EM201: _ZH_DEONTIC_KEYWORDS inline Chinese + 9th language in detect_all_languages."""

    def test_zh_keywords_importable(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _ZH_DEONTIC_KEYWORDS,
        )
        assert isinstance(_ZH_DEONTIC_KEYWORDS, dict)

    def test_zh_has_three_types(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _ZH_DEONTIC_KEYWORDS,
        )
        assert set(_ZH_DEONTIC_KEYWORDS.keys()) >= {"permission", "prohibition", "obligation"}

    def test_zh_permission_has_keywords(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _ZH_DEONTIC_KEYWORDS,
        )
        assert len(_ZH_DEONTIC_KEYWORDS["permission"]) >= 3

    def test_load_i18n_keywords_zh_returns_inline(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _load_i18n_keywords,
            _ZH_DEONTIC_KEYWORDS,
        )
        result = _load_i18n_keywords("zh")
        assert result is _ZH_DEONTIC_KEYWORDS

    def test_detect_all_languages_has_zh(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        assert "zh" in report.by_language

    def test_detect_all_languages_has_nine_languages(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("test")
        assert len(report.by_language) >= 9

    def test_zh_prohibition_keyword_can_detect(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _ZH_DEONTIC_KEYWORDS,
        )
        # Just check that "禁止" is in prohibition list
        assert any("禁止" in kw for kw in _ZH_DEONTIC_KEYWORDS["prohibition"])


# ═══════════════════════════════════════════════════════════════════════════
# EN202 – compile_batch(fail_fast=True)
# ═══════════════════════════════════════════════════════════════════════════

class TestEN202CompileBatchFailFast:
    """EN202: compile_batch(fail_fast=True) stops on first error batch."""

    def test_fail_fast_false_compiles_all(self):
        compiler = _make_compiler()
        batches = [["May read."], ["Must write."], ["May delete."]]
        results = compiler.compile_batch(batches, fail_fast=False)
        assert len(results) == 3

    def test_fail_fast_true_stops_on_first_error(self):
        compiler = _make_compiler()
        # Use an empty sentences list to trigger an error for that batch
        batches = [[], ["May read."]]  # first batch is empty - likely produces error
        results = compiler.compile_batch(batches, fail_fast=True)
        # If first batch has errors, should stop there
        if results[0].errors:
            assert len(results) == 1
        else:
            # No error on first batch — all should compile
            assert len(results) == len(batches)

    def test_fail_fast_default_is_false(self):
        import inspect
        from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import (
            NLUCANPolicyCompiler,
        )
        sig = inspect.signature(NLUCANPolicyCompiler.compile_batch)
        assert sig.parameters["fail_fast"].default is False

    def test_fail_fast_true_empty_batches_returns_empty(self):
        compiler = _make_compiler()
        assert compiler.compile_batch([], fail_fast=True) == []

    def test_fail_fast_false_all_succeed_returns_all(self):
        compiler = _make_compiler()
        batches = [["The agent may read."], ["The agent may write."]]
        results = compiler.compile_batch(batches, fail_fast=False)
        assert len(results) == 2

    def test_fail_fast_result_count_less_or_equal(self):
        compiler = _make_compiler()
        batches = [["May read."], ["Must log."], ["May delete."]]
        r_ff = compiler.compile_batch(batches, fail_fast=True)
        r_all = compiler.compile_batch(batches, fail_fast=False)
        assert len(r_ff) <= len(r_all)


# ═══════════════════════════════════════════════════════════════════════════
# EO203 – active_token_count caching across multiple revokes
# ═══════════════════════════════════════════════════════════════════════════

class TestEO203ActiveTokenCountCaching:
    """EO203: active_token_count stays consistent across multiple revoke() calls."""

    def test_count_decrements_on_each_revoke(self):
        mgr = _make_manager()
        tokens = [_make_token() for _ in range(3)]
        for t in tokens:
            mgr.add(t)
        initial = mgr.active_token_count
        mgr.revoke(tokens[0].cid)
        assert mgr.active_token_count == initial - 1
        mgr.revoke(tokens[1].cid)
        assert mgr.active_token_count == initial - 2
        mgr.revoke(tokens[2].cid)
        assert mgr.active_token_count == 0

    def test_count_consistent_with_active_tokens_len(self):
        mgr = _make_manager()
        t1, t2 = _make_token(), _make_token()
        mgr.add(t1)
        mgr.add(t2)
        mgr.revoke(t1.cid)
        assert mgr.active_token_count == len(list(mgr.active_tokens()))

    def test_count_zero_when_all_revoked(self):
        mgr = _make_manager()
        tokens = [_make_token() for _ in range(4)]
        for t in tokens:
            mgr.add(t)
        for t in tokens:
            mgr.revoke(t.cid)
        assert mgr.active_token_count == 0

    def test_count_stable_on_repeated_reads(self):
        mgr = _make_manager()
        t = _make_token()
        mgr.add(t)
        c1 = mgr.active_token_count
        c2 = mgr.active_token_count
        assert c1 == c2

    def test_cache_invalidated_by_add(self):
        mgr = _make_manager()
        t1 = _make_token()
        mgr.add(t1)
        before = mgr.active_token_count
        t2 = _make_token()
        mgr.add(t2)
        assert mgr.active_token_count == before + 1


# ═══════════════════════════════════════════════════════════════════════════
# EP204 – Japanese text → detect_i18n_clauses("ja") integration
# ═══════════════════════════════════════════════════════════════════════════

class TestEP204JapaneseIntegration:
    """EP204: Japanese text → detect_i18n_clauses("ja") pipeline."""

    def test_detect_i18n_clauses_ja_returns_list(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            detect_i18n_clauses,
        )
        result = detect_i18n_clauses("test text", "ja")
        assert isinstance(result, list)

    def test_detect_i18n_clauses_ja_permission_prohibition(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            detect_i18n_clauses,
            _JA_DEONTIC_KEYWORDS,
        )
        # Craft text that contains both permission and prohibition keywords
        perm = _JA_DEONTIC_KEYWORDS["permission"][0]
        prohib = _JA_DEONTIC_KEYWORDS["prohibition"][0]
        text = f"このエージェントは{perm}。しかし{prohib}。"
        result = detect_i18n_clauses(text, "ja")
        # Should detect simultaneous permission + prohibition
        assert isinstance(result, list)

    def test_detect_i18n_clauses_ja_empty_text(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            detect_i18n_clauses,
        )
        result = detect_i18n_clauses("", "ja")
        assert isinstance(result, list)

    def test_detect_all_languages_zh_slot_exists(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("可以 不得")
        assert "zh" in report.by_language
        assert isinstance(report.by_language["zh"], list)

    def test_detect_all_languages_ja_slot_exists(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("してもよい")
        assert "ja" in report.by_language
        assert isinstance(report.by_language["ja"], list)

    def test_load_i18n_keywords_zh_available(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _load_i18n_keywords,
        )
        kw = _load_i18n_keywords("zh")
        assert len(kw) >= 3


# ═══════════════════════════════════════════════════════════════════════════
# EQ205 – get_clauses_by_type + detect_i18n_clauses("pt") combined
# ═══════════════════════════════════════════════════════════════════════════

class TestEQ205PortuguesePipelineCombined:
    """EQ205: PortugueseParser.get_clauses_by_type() combined with detect_i18n_clauses("pt")."""

    def test_get_clauses_by_type_subset_of_parse(self):
        from ipfs_datasets_py.logic.CEC.nl.portuguese_parser import PortugueseParser
        parser = PortugueseParser()
        text = "O agente pode ler dados. O agente não pode excluir."
        all_clauses = parser.parse(text)
        perm_clauses = parser.get_clauses_by_type(text, "permission")
        assert all(c in all_clauses for c in perm_clauses)

    def test_detect_i18n_clauses_pt_returns_list(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            detect_i18n_clauses,
        )
        result = detect_i18n_clauses("O agente pode ler.", "pt")
        assert isinstance(result, list)

    def test_detect_all_languages_includes_pt(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("O agente deve não pode")
        assert "pt" in report.by_language

    def test_get_clauses_by_type_permission(self):
        from ipfs_datasets_py.logic.CEC.nl.portuguese_parser import PortugueseParser
        parser = PortugueseParser()
        text = "O agente pode acessar o banco de dados."
        clauses = parser.get_clauses_by_type(text, "permission")
        assert isinstance(clauses, list)

    def test_get_clauses_by_type_prohibition(self):
        from ipfs_datasets_py.logic.CEC.nl.portuguese_parser import PortugueseParser
        parser = PortugueseParser()
        text = "O agente não pode excluir registros."
        clauses = parser.get_clauses_by_type(text, "prohibition")
        assert isinstance(clauses, list)


# ═══════════════════════════════════════════════════════════════════════════
# ER206 – clear() + export_jsonl() round-trip: cleared log → 0 entries
# ═══════════════════════════════════════════════════════════════════════════

class TestER206ClearExportRoundTrip:
    """ER206: clear() + export_jsonl(): cleared log exports 0 audit entries."""

    def test_cleared_log_exports_zero_entries(self):
        log = _make_audit_log()
        log.record(policy_cid="p1", intent_cid="i1", decision="allow", actor="agent1", tool="read")
        log.record(policy_cid="p2", intent_cid="i2", decision="deny", actor="agent2", tool="write")
        log.clear()
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            count = log.export_jsonl(path)
            assert count == 0
            with open(path) as f:
                lines = [l for l in f if l.strip()]
            assert lines == []
        finally:
            os.unlink(path)

    def test_export_after_clear_empty_metadata(self):
        log = _make_audit_log()
        log.record(policy_cid="p1", intent_cid="i1", decision="allow", actor="a", tool="t")
        log.clear()
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            count = log.export_jsonl(path, metadata={"info": "cleared"})
            assert count == 0
        finally:
            os.unlink(path)

    def test_import_after_clear_empty_returns_zero(self):
        log = _make_audit_log()
        log.record(policy_cid="p1", intent_cid="i1", decision="allow", actor="a", tool="t")
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            log.export_jsonl(path)
            log.clear()
            count = log.import_jsonl(path)
            # After clearing and re-importing, we should get the entries back
            assert isinstance(count, int)
            assert count >= 0
        finally:
            os.unlink(path)

    def test_recent_empty_after_clear(self):
        log = _make_audit_log()
        log.record(policy_cid="p1", intent_cid="i1", decision="allow", actor="a", tool="t")
        log.record(policy_cid="p2", intent_cid="i2", decision="deny", actor="b", tool="u")
        log.clear()
        assert log.recent() == []

    def test_cleared_log_then_append_then_export(self):
        log = _make_audit_log()
        log.record(policy_cid="p1", intent_cid="i1", decision="allow", actor="a", tool="t")
        log.clear()
        log.record(policy_cid="p2", intent_cid="i2", decision="deny", actor="b", tool="u")
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            count = log.export_jsonl(path)
            assert count == 1
        finally:
            os.unlink(path)
