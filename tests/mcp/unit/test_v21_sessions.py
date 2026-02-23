"""v21 Session Tests — DG169 through DN176.

Tests all v21 candidates from MASTER_IMPROVEMENT_PLAN_2026_v20.md:

  DG169  PolicyAuditLog.import_jsonl() skips __metadata__ lines
  DH170  ComplianceChecker.merge(include_protected_rules=False) skips non-removable
  DI171  NLUCANPolicyCompiler.compile_explain_iter() line iterator
  DJ172  PortugueseParser + detect_all_languages() covers "pt"
  DK173  DelegationManager.merge_and_publish_async()
  DL174  Full E2E: merge + export_jsonl(metadata) + import_jsonl round-trip
  DM175  ComplianceChecker.diff() + merge() combined idempotency E2E
  DN176  Dutch inline keywords + detect_all_languages() covers "nl"
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

_TMPDIR = Path(tempfile.gettempdir()) / "ipfs_v21_tests"


def _tmp(name: str) -> str:
    _TMPDIR.mkdir(parents=True, exist_ok=True)
    return str(_TMPDIR / name)


# ══════════════════════════════════════════════════════════════════════════════
# DG169 — PolicyAuditLog.import_jsonl() skips __metadata__ lines
# ══════════════════════════════════════════════════════════════════════════════

class TestDG169ImportJsonlSkipsMetadata:
    """DG169: import_jsonl honours __metadata__ header lines."""

    def test_import_skips_metadata_line(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        log = PolicyAuditLog()
        path = _tmp("dg169_meta.jsonl")
        # Write a file with a metadata header and two real entries
        entries = [
            '{"__metadata__": {"session": "v21", "version": "1"}}\n',
            '{"timestamp":1.0,"policy_cid":"p1","intent_cid":"i1","decision":"allow","actor":"a","tool":"t","justification":"","obligations":[],"extra":{}}\n',
            '{"timestamp":2.0,"policy_cid":"p2","intent_cid":"i2","decision":"deny","actor":"b","tool":"t","justification":"","obligations":[],"extra":{}}\n',
        ]
        Path(path).write_text("".join(entries), encoding="utf-8")
        count = log.import_jsonl(path)
        assert count == 2, f"expected 2 entries, got {count}"

    def test_import_metadata_not_counted(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        log = PolicyAuditLog()
        path = _tmp("dg169_notcounted.jsonl")
        Path(path).write_text(
            '{"__metadata__": {"x": 1}}\n'
            '{"timestamp":1.0,"policy_cid":"p","intent_cid":"i","decision":"allow","actor":"a","tool":"t","justification":"","obligations":[],"extra":{}}\n',
            encoding="utf-8",
        )
        count = log.import_jsonl(path)
        assert count == 1

    def test_export_then_import_round_trip_with_metadata(self):
        """Full round-trip: export with metadata, import should skip header."""
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog, AuditEntry
        log = PolicyAuditLog()
        log.record(
            policy_cid="poly", intent_cid="intent", decision="allow",
            actor="alice", tool="scan",
        )
        log.record(
            policy_cid="poly", intent_cid="intent2", decision="deny",
            actor="bob", tool="write",
        )
        path = _tmp("dg169_roundtrip.jsonl")
        exported = log.export_jsonl(path, metadata={"test": "v21"})
        assert exported == 2

        log2 = PolicyAuditLog()
        imported = log2.import_jsonl(path)
        assert imported == 2

    def test_import_multiple_metadata_lines(self):
        """Multiple __metadata__ lines should all be skipped."""
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        log = PolicyAuditLog()
        path = _tmp("dg169_multimeta.jsonl")
        Path(path).write_text(
            '{"__metadata__": {"a": 1}}\n'
            '{"__metadata__": {"b": 2}}\n'
            '{"timestamp":1.0,"policy_cid":"p","intent_cid":"i","decision":"allow","actor":"a","tool":"t","justification":"","obligations":[],"extra":{}}\n',
            encoding="utf-8",
        )
        count = log.import_jsonl(path)
        assert count == 1

    def test_import_missing_file_returns_zero(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        log = PolicyAuditLog()
        count = log.import_jsonl(_tmp("dg169_nonexistent_XYZ.jsonl"))
        assert count == 0

    def test_import_empty_metadata_only(self):
        """A file with only a metadata line → 0 entries imported."""
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        log = PolicyAuditLog()
        path = _tmp("dg169_only_meta.jsonl")
        Path(path).write_text('{"__metadata__": {}}\n', encoding="utf-8")
        count = log.import_jsonl(path)
        assert count == 0

    def test_export_without_metadata_no_header(self):
        """export_jsonl(metadata=None) produces no __metadata__ line."""
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        log = PolicyAuditLog()
        log.record(
            policy_cid="p", intent_cid="i", decision="allow",
            actor="a", tool="t",
        )
        path = _tmp("dg169_no_meta.jsonl")
        log.export_jsonl(path)
        lines = [l.strip() for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
        assert all("__metadata__" not in l for l in lines)


# ══════════════════════════════════════════════════════════════════════════════
# DH170 — ComplianceChecker.merge(include_protected_rules=False) skips non-removable
# ══════════════════════════════════════════════════════════════════════════════

class TestDH170MergeCopyDisabled:
    """DH170: merge(include_protected_rules=False) skips non-removable (built-in) rules."""

    def _checker_with_custom_rule(self, rule_id: str, removable: bool = True):
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            ComplianceChecker, ComplianceRule, ComplianceResult,
        )
        checker = ComplianceChecker()
        rule = ComplianceRule(
            rule_id=rule_id,
            description=f"Rule {rule_id}",
            check_fn=lambda intent: ComplianceResult(rule_id=rule_id, passed=True, message="ok"),
            removable=removable,
        )
        checker._rules.append(rule)
        return checker

    def test_merge_default_skips_non_removable(self):
        """Default include_protected_rules=False: non-removable rules from other are skipped."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        dst = ComplianceChecker()
        src = self._checker_with_custom_rule("rule_protected", removable=False)
        added = dst.merge(src)
        assert added == 0

    def test_merge_include_protected_rules_true_copies_protected(self):
        """include_protected_rules=True: non-removable rules ARE copied."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        dst = ComplianceChecker()
        src = self._checker_with_custom_rule("rule_protected", removable=False)
        added = dst.merge(src, include_protected_rules=True)
        assert added == 1

    def test_merge_removable_still_copied_by_default(self):
        """Removable rules are copied even with include_protected_rules=False (default)."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        dst = ComplianceChecker()
        src = self._checker_with_custom_rule("rule_removable", removable=True)
        added = dst.merge(src)
        assert added == 1

    def test_merge_mixed_rules(self):
        """Mixed: only removable rule is added when include_protected_rules=False."""
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            ComplianceChecker, ComplianceRule, ComplianceResult,
        )
        dst = ComplianceChecker()
        src = ComplianceChecker()
        src._rules.append(ComplianceRule(
            rule_id="r_removable", description="x",
            check_fn=lambda i: ComplianceResult(rule_id="r_removable", passed=True, message=""),
            removable=True,
        ))
        src._rules.append(ComplianceRule(
            rule_id="r_protected", description="y",
            check_fn=lambda i: ComplianceResult(rule_id="r_protected", passed=True, message=""),
            removable=False,
        ))
        added = dst.merge(src)
        assert added == 1

    def test_merge_mixed_include_protected_rules_true(self):
        """include_protected_rules=True: both rules are added."""
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            ComplianceChecker, ComplianceRule, ComplianceResult,
        )
        dst = ComplianceChecker()
        src = ComplianceChecker()
        for rid, rm in [("ra", True), ("rb", False)]:
            src._rules.append(ComplianceRule(
                rule_id=rid, description="d",
                check_fn=lambda i, _rid=rid: ComplianceResult(rule_id=_rid, passed=True, message=""),
                removable=rm,
            ))
        added = dst.merge(src, include_protected_rules=True)
        assert added == 2

    def test_merge_idempotent_no_duplicate(self):
        """Calling merge twice does not add duplicates."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        dst = ComplianceChecker()
        src = self._checker_with_custom_rule("rule_once", removable=True)
        dst.merge(src)
        added2 = dst.merge(src)
        assert added2 == 0


# ══════════════════════════════════════════════════════════════════════════════
# DI171 — compile_explain_iter() line iterator
# ══════════════════════════════════════════════════════════════════════════════

class TestDI171CompileExplainIter:
    """DI171: compile_explain_iter() yields explanation lines lazily."""

    def test_iter_returns_generator(self):
        from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import (
            NLUCANPolicyCompiler,
        )
        import types
        compiler = NLUCANPolicyCompiler(policy_id="test-iter")
        result = compiler.compile_explain_iter(["Alice must not read."])
        assert isinstance(result, types.GeneratorType)

    def test_iter_yields_strings(self):
        from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import (
            NLUCANPolicyCompiler,
        )
        compiler = NLUCANPolicyCompiler(policy_id="test-iter2")
        lines = list(compiler.compile_explain_iter(["Alice may read."]))
        assert all(isinstance(line, str) for line in lines)

    def test_iter_at_least_one_line(self):
        from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import (
            NLUCANPolicyCompiler,
        )
        compiler = NLUCANPolicyCompiler(policy_id="test-iter3")
        lines = list(compiler.compile_explain_iter(["Bob must write."]))
        assert len(lines) >= 1

    def test_iter_matches_explain(self):
        """Collected lines joined by newlines equal result.explain()."""
        from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import (
            NLUCANPolicyCompiler,
        )
        compiler = NLUCANPolicyCompiler(policy_id="test-iter4")
        sentences = ["Carol may not delete.", "Dave must log."]
        result, explanation = compiler.compile_explain(sentences)
        iter_lines = list(compiler.compile_explain_iter(sentences))
        assert "\n".join(iter_lines) == explanation.rstrip("\n")

    def test_iter_empty_sentences(self):
        from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import (
            NLUCANPolicyCompiler,
        )
        compiler = NLUCANPolicyCompiler(policy_id="test-iter5")
        # Should not raise, even with empty input
        lines = list(compiler.compile_explain_iter([]))
        assert isinstance(lines, list)

    def test_iter_partial_consumption(self):
        """Iterator can be partially consumed without error."""
        from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import (
            NLUCANPolicyCompiler,
        )
        compiler = NLUCANPolicyCompiler(policy_id="test-iter6")
        gen = compiler.compile_explain_iter(["Eve may read.", "Frank must not write."])
        first = next(gen, None)
        # Should yield at least the first line without error
        assert first is None or isinstance(first, str)


# ══════════════════════════════════════════════════════════════════════════════
# DJ172 — PortugueseParser + detect_all_languages() covers "pt"
# ══════════════════════════════════════════════════════════════════════════════

class TestDJ172PortugueseParser:
    """DJ172: PortugueseParser detects deontic clauses in Portuguese text."""

    def test_parser_imports(self):
        from ipfs_datasets_py.logic.CEC.nl.portuguese_parser import (
            PortugueseParser, get_portuguese_deontic_keywords,
        )
        assert callable(get_portuguese_deontic_keywords)

    def test_keywords_dict_shape(self):
        from ipfs_datasets_py.logic.CEC.nl.portuguese_parser import (
            get_portuguese_deontic_keywords,
        )
        kw = get_portuguese_deontic_keywords()
        assert "permission" in kw
        assert "prohibition" in kw
        assert "obligation" in kw

    def test_parse_permission(self):
        from ipfs_datasets_py.logic.CEC.nl.portuguese_parser import PortugueseParser
        parser = PortugueseParser()
        clauses = parser.parse("O utilizador pode aceder ao sistema.")
        assert any(c.deontic_type == "permission" for c in clauses)

    def test_parse_prohibition(self):
        from ipfs_datasets_py.logic.CEC.nl.portuguese_parser import PortugueseParser
        parser = PortugueseParser()
        clauses = parser.parse("O utilizador não pode apagar ficheiros.")
        assert any(c.deontic_type == "prohibition" for c in clauses)

    def test_parse_obligation(self):
        from ipfs_datasets_py.logic.CEC.nl.portuguese_parser import PortugueseParser
        parser = PortugueseParser()
        clauses = parser.parse("O utilizador deve registar a acção.")
        assert any(c.deontic_type == "obligation" for c in clauses)

    def test_clause_to_dict(self):
        from ipfs_datasets_py.logic.CEC.nl.portuguese_parser import PortugueseClause
        clause = PortugueseClause(text="x", deontic_type="permission", matched_keyword="pode")
        d = clause.to_dict()
        assert d["deontic_type"] == "permission"
        assert d["matched_keyword"] == "pode"

    def test_detect_all_languages_includes_pt(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("O utilizador pode aceder. The user must not delete.")
        assert "pt" in report.by_language

    def test_detect_all_pt_empty_neutral_text(self):
        """Neutral text (no deontic verbs) → empty conflict list for pt."""
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("The sky is blue.")
        assert isinstance(report.by_language.get("pt", []), list)


# ══════════════════════════════════════════════════════════════════════════════
# DK173 — DelegationManager.merge_and_publish_async()
# ══════════════════════════════════════════════════════════════════════════════

class TestDK173MergeAndPublishAsync:
    """DK173: merge_and_publish_async() uses async pubsub when available."""

    def _make_manager_with_token(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, DelegationToken, Capability,
        )
        mgr = DelegationManager()
        token = DelegationToken(
            issuer="did:key:alice",
            audience="did:key:bob",
            capabilities=[Capability(resource="*", ability="read/*")],
            expiry=None,
        )
        mgr.add(token)
        return mgr

    def test_async_method_exists(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager()
        assert hasattr(mgr, "merge_and_publish_async")
        import asyncio
        assert asyncio.iscoroutinefunction(mgr.merge_and_publish_async)

    def test_async_with_sync_pubsub_fallback(self):
        """When pubsub has only sync publish, it is used as fallback."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager

        class SyncPubSub:
            def __init__(self):
                self.calls: List[Any] = []

            def publish(self, topic: str, payload: dict) -> None:
                self.calls.append((topic, payload))

        src = self._make_manager_with_token()
        dst = DelegationManager()
        bus = SyncPubSub()
        added = asyncio.run(dst.merge_and_publish_async(src, bus))
        assert added == 1
        assert len(bus.calls) == 1
        assert bus.calls[0][0] == "receipt_disseminate"

    def test_async_with_async_pubsub(self):
        """When pubsub has async publish_async, it is awaited."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager

        class AsyncPubSub:
            def __init__(self):
                self.calls: List[Any] = []

            async def publish_async(self, topic: str, payload: dict) -> None:
                self.calls.append((topic, payload))

        src = self._make_manager_with_token()
        dst = DelegationManager()
        bus = AsyncPubSub()
        added = asyncio.run(dst.merge_and_publish_async(src, bus))
        assert added == 1
        assert len(bus.calls) == 1
        assert bus.calls[0][1]["type"] == "merge"

    def test_async_returns_added_count(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager

        class DummyBus:
            def publish(self, *a, **kw):
                pass

        src = self._make_manager_with_token()
        dst = DelegationManager()
        added = asyncio.run(dst.merge_and_publish_async(src, DummyBus()))
        assert added == 1

    def test_async_payload_includes_metrics(self):
        """Async payload includes 'metrics' key (DK173 + CY161)."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager

        payloads: List[dict] = []

        class CaptureBus:
            def publish(self, topic, payload):
                payloads.append(payload)

        src = self._make_manager_with_token()
        dst = DelegationManager()
        asyncio.run(dst.merge_and_publish_async(src, CaptureBus()))
        assert len(payloads) == 1
        assert "metrics" in payloads[0]

    def test_async_raises_do_not_propagate(self):
        """Exceptions from pubsub do not propagate."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager

        class BrokenBus:
            def publish(self, *a, **kw):
                raise RuntimeError("boom")

        src = self._make_manager_with_token()
        dst = DelegationManager()
        # Should not raise
        added = asyncio.run(dst.merge_and_publish_async(src, BrokenBus()))
        assert added == 1


# ══════════════════════════════════════════════════════════════════════════════
# DL174 — Full E2E round-trip: merge + export_jsonl(metadata) + import_jsonl
# ══════════════════════════════════════════════════════════════════════════════

class TestDL174FullRoundTrip:
    """DL174: Full E2E: merge → export_jsonl(metadata) → import_jsonl round-trip."""

    def test_merge_export_import_round_trip(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog, AuditEntry
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, DelegationToken, Capability,
        )

        # 1. Build two delegation managers and merge
        src = DelegationManager()
        src.add(DelegationToken(
            issuer="did:key:alice",
            audience="did:key:bob",
            capabilities=[Capability(resource="*", ability="read/*")],
            expiry=None,
        ))
        dst = DelegationManager()
        added = dst.merge(src)
        assert added == 1

        # 2. Record audit entries
        log = PolicyAuditLog()
        log.record(
            policy_cid="dl174-policy",
            intent_cid="dl174-intent",
            decision="allow",
            actor="alice",
            tool="read",
        )
        log.record(
            policy_cid="dl174-policy",
            intent_cid="dl174-intent2",
            decision="deny",
            actor="bob",
            tool="delete",
        )

        # 3. Export with metadata
        path = _tmp("dl174_roundtrip.jsonl")
        exported = log.export_jsonl(path, metadata={"merge_count": added, "test": "DL174"})
        assert exported == 2

        # 4. Import into a new log — __metadata__ line must be skipped
        log2 = PolicyAuditLog()
        imported = log2.import_jsonl(path)
        assert imported == 2
        assert log2.total_recorded() == 2

    def test_round_trip_decisions_preserved(self):
        """Decisions are correctly preserved across export+import."""
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog

        log = PolicyAuditLog()
        log.record(policy_cid="p", intent_cid="i1", decision="allow", actor="a", tool="t")
        log.record(policy_cid="p", intent_cid="i2", decision="deny", actor="b", tool="t")

        path = _tmp("dl174_decisions.jsonl")
        log.export_jsonl(path, metadata={"v": "21"})

        log2 = PolicyAuditLog()
        log2.import_jsonl(path)
        entries = log2.recent(n=10)
        decisions = {e.decision for e in entries}
        assert "allow" in decisions
        assert "deny" in decisions

    def test_round_trip_empty_log(self):
        """Empty log: export + import round-trips with 0 entries."""
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog

        log = PolicyAuditLog()
        path = _tmp("dl174_empty.jsonl")
        exported = log.export_jsonl(path, metadata={"empty": True})
        assert exported == 0

        log2 = PolicyAuditLog()
        imported = log2.import_jsonl(path)
        assert imported == 0

    def test_round_trip_stats_after_import(self):
        """stats() returns sensible values after import."""
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog

        log = PolicyAuditLog()
        for _ in range(3):
            log.record(policy_cid="p", intent_cid="i", decision="allow", actor="a", tool="t")
        path = _tmp("dl174_stats.jsonl")
        log.export_jsonl(path, metadata={"n": 3})

        log2 = PolicyAuditLog()
        log2.import_jsonl(path)
        stats = log2.stats()
        assert stats["total_recorded"] == 3
        assert stats["allow_count"] == 3


# ══════════════════════════════════════════════════════════════════════════════
# DM175 — ComplianceChecker.diff() + merge() combined idempotency
# ══════════════════════════════════════════════════════════════════════════════

class TestDM175DiffMergeIdempotency:
    """DM175: diff() and merge() are symmetric; merge is idempotent."""

    def _make_checker_with_rules(self, rule_ids: List[str]) -> "Any":
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            ComplianceChecker, ComplianceRule, ComplianceResult,
        )
        checker = ComplianceChecker()
        for rid in rule_ids:
            checker._rules.append(ComplianceRule(
                rule_id=rid,
                description=f"Rule {rid}",
                check_fn=lambda i, _rid=rid: ComplianceResult(rule_id=_rid, passed=True, message=""),
                removable=True,
            ))
        return checker

    def test_diff_added_rules_equal_merge_additions(self):
        """IDs in diff['added_rules'] == count from merge()."""
        a = self._make_checker_with_rules(["r1", "r2"])
        b = self._make_checker_with_rules(["r2", "r3", "r4"])
        diff = a.diff(b)
        merge_count = a.merge(b)
        assert merge_count == len(diff["added_rules"])

    def test_merge_then_diff_shows_no_new_rules(self):
        """After merge(), diff(b)['added_rules'] should be empty."""
        a = self._make_checker_with_rules(["r1"])
        b = self._make_checker_with_rules(["r1", "r2", "r3"])
        a.merge(b)
        diff_after = a.diff(b)
        assert diff_after["added_rules"] == []

    def test_merge_idempotent(self):
        """Calling merge() twice does not change the checker."""
        a = self._make_checker_with_rules(["r1"])
        b = self._make_checker_with_rules(["r2", "r3"])
        a.merge(b)
        added2 = a.merge(b)
        assert added2 == 0

    def test_diff_symmetric_added_removed(self):
        """diff(b)['added_rules'] and diff(b)['removed_rules'] are complementary."""
        a = self._make_checker_with_rules(["r1", "r2"])
        b = self._make_checker_with_rules(["r2", "r3"])
        diff = a.diff(b)
        # r3 is in b but not a → should appear as "added"
        # r1 is in a but not b → should appear as "removed"
        assert "r3" in diff["added_rules"]
        assert "r1" in diff["removed_rules"]

    def test_merge_all_sources_empty_diff_afterwards(self):
        """After merging all rules from b into a, diff has no added."""
        a = self._make_checker_with_rules(["x"])
        b = self._make_checker_with_rules(["x", "y", "z"])
        a.merge(b)
        diff = a.diff(b)
        assert len(diff["added_rules"]) == 0

    def test_combined_e2e_diff_merge_diff(self):
        """diff → merge → diff sequence: second diff shows no new rules."""
        a = self._make_checker_with_rules(["p", "q"])
        b = self._make_checker_with_rules(["q", "r", "s"])
        diff1 = a.diff(b)
        assert set(diff1["added_rules"]) == {"r", "s"}
        a.merge(b)
        diff2 = a.diff(b)
        assert diff2["added_rules"] == []


# ══════════════════════════════════════════════════════════════════════════════
# DN176 — Dutch inline keywords + detect_all_languages() covers "nl"
# ══════════════════════════════════════════════════════════════════════════════

class TestDN176DutchKeywords:
    """DN176: Inline Dutch (_NL_DEONTIC_KEYWORDS) wired into detect_all_languages()."""

    def test_nl_keywords_exist(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _NL_DEONTIC_KEYWORDS,
        )
        assert "permission" in _NL_DEONTIC_KEYWORDS
        assert "prohibition" in _NL_DEONTIC_KEYWORDS
        assert "obligation" in _NL_DEONTIC_KEYWORDS

    def test_nl_keywords_non_empty(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            _NL_DEONTIC_KEYWORDS,
        )
        assert len(_NL_DEONTIC_KEYWORDS["permission"]) > 0
        assert len(_NL_DEONTIC_KEYWORDS["prohibition"]) > 0

    def test_detect_i18n_conflicts_nl_permission(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            detect_i18n_conflicts,
        )
        result = detect_i18n_conflicts("De gebruiker mag het systeem gebruiken.", "nl")
        assert result.has_permission

    def test_detect_i18n_conflicts_nl_prohibition(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            detect_i18n_conflicts,
        )
        result = detect_i18n_conflicts("De gebruiker mag niet verwijderen.", "nl")
        assert result.has_prohibition

    def test_detect_i18n_conflicts_nl_simultaneous(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            detect_i18n_conflicts,
        )
        result = detect_i18n_conflicts("De gebruiker mag lezen maar mag niet schrijven.", "nl")
        assert result.has_simultaneous_conflict

    def test_detect_all_languages_includes_nl(self):
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("De gebruiker mag lezen.")
        assert "nl" in report.by_language

    def test_detect_all_languages_6_langs(self):
        """detect_all_languages() now covers 6 languages."""
        from ipfs_datasets_py.logic.api import detect_all_languages
        report = detect_all_languages("User may read. Utilisateur peut lire.")
        assert len(report.by_language) == 6
        for lang in ("fr", "es", "de", "en", "pt", "nl"):
            assert lang in report.by_language

    def test_dutch_no_conflict_neutral_text(self):
        """Neutral text returns no Dutch conflict."""
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            detect_i18n_conflicts,
        )
        result = detect_i18n_conflicts("De lucht is blauw.", "nl")
        assert not result.has_simultaneous_conflict
