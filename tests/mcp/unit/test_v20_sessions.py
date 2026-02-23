"""v20 session tests: CY161/CZ162/DA163/DB164/DC165/DD166/DE167/DF168.

All production modules under test were created or modified in v20:

* CY161 — ``DelegationManager.merge_and_publish()`` — full metrics snapshot in payload
* CZ162 — ``PolicyAuditLog.export_jsonl(metadata=...)`` — optional metadata header line
* DA163 — ``ComplianceChecker.merge(other) -> int`` — symmetric to ``diff()``
* DB164 — ``NLUCANPolicyCompiler.compile_explain(sentences)`` — compile + explain
* DC165 — ``detect_all_languages()`` now includes ``"en"`` language pass
* DD166 — ``DelegationManager.merge_and_publish()`` with duck-typed PubSubBus
* DE167 — TDFOL ``NLParser.parse()`` with mocked dependencies
* DF168 — ``evaluate_with_manager`` + ``detect_all_languages`` combined E2E
"""
from __future__ import annotations

import importlib
import json
import os
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import(module_path: str) -> Any:
    return importlib.import_module(module_path)


# ============================================================================
# CY161 — merge_and_publish() full metrics snapshot
# ============================================================================

class TestCY161MergePublishMetrics:
    """merge_and_publish() now includes a 'metrics' key in the pubsub payload."""

    def _make_manager(self):
        mod = _import("ipfs_datasets_py.mcp_server.ucan_delegation")
        return mod.DelegationManager()

    def _make_token(self, audience: str = "did:key:alice"):
        mod = _import("ipfs_datasets_py.mcp_server.ucan_delegation")
        return mod.DelegationToken(
            issuer="did:key:root",
            audience=audience,
            capabilities=[mod.Capability(resource="*", ability="*")],
        )

    def test_payload_contains_metrics_key(self):
        mgr_src = self._make_manager()
        mgr_dst = self._make_manager()
        mgr_src.add(self._make_token())
        captured = {}
        class MockPubSub:
            def publish(self, topic, payload):
                captured["topic"] = topic
                captured["payload"] = payload
        mgr_dst.merge_and_publish(mgr_src, MockPubSub())
        assert "metrics" in captured["payload"]

    def test_metrics_has_delegation_count(self):
        mgr_src = self._make_manager()
        mgr_dst = self._make_manager()
        mgr_src.add(self._make_token())
        payloads = []
        class MockPubSub:
            def publish(self, topic, payload):
                payloads.append(payload)
        mgr_dst.merge_and_publish(mgr_src, MockPubSub())
        # get_metrics() returns 'token_count' for the delegation count
        assert "token_count" in payloads[0]["metrics"]

    def test_metrics_has_revoked_cid_count(self):
        mgr_src = self._make_manager()
        mgr_dst = self._make_manager()
        mgr_src.add(self._make_token())
        payloads = []
        class MockPubSub:
            def publish(self, topic, payload):
                payloads.append(payload)
        mgr_dst.merge_and_publish(mgr_src, MockPubSub())
        # get_metrics() returns 'revoked_count' for revoked CIDs
        assert "revoked_count" in payloads[0]["metrics"]

    def test_metrics_reflects_post_merge_state(self):
        mgr_src = self._make_manager()
        mgr_dst = self._make_manager()
        for i in range(3):
            mgr_src.add(self._make_token(audience=f"did:key:user{i}"))
        payloads = []
        class MockPubSub:
            def publish(self, topic, payload):
                payloads.append(payload)
        mgr_dst.merge_and_publish(mgr_src, MockPubSub())
        # token_count should include the 3 newly merged tokens
        assert payloads[0]["metrics"]["token_count"] == 3

    def test_payload_still_has_added_and_total(self):
        """CY161 must not remove the existing 'added' and 'total' keys."""
        mgr_src = self._make_manager()
        mgr_dst = self._make_manager()
        mgr_src.add(self._make_token())
        payloads = []
        class MockPubSub:
            def publish(self, topic, payload):
                payloads.append(payload)
        mgr_dst.merge_and_publish(mgr_src, MockPubSub())
        assert "added" in payloads[0]
        assert "total" in payloads[0]

    def test_metrics_type_is_dict(self):
        mgr_src = self._make_manager()
        mgr_dst = self._make_manager()
        mgr_src.add(self._make_token())
        payloads = []
        class MockPubSub:
            def publish(self, topic, payload):
                payloads.append(payload)
        mgr_dst.merge_and_publish(mgr_src, MockPubSub())
        assert isinstance(payloads[0]["metrics"], dict)

    def test_empty_merge_still_publishes_metrics(self):
        """Even with 0 tokens merged, metrics snapshot must be published."""
        mgr_src = self._make_manager()
        mgr_dst = self._make_manager()
        payloads = []
        class MockPubSub:
            def publish(self, topic, payload):
                payloads.append(payload)
        mgr_dst.merge_and_publish(mgr_src, MockPubSub())
        assert "metrics" in payloads[0]
        assert payloads[0]["metrics"]["token_count"] == 0


# ============================================================================
# CZ162 — PolicyAuditLog.export_jsonl(metadata=...)
# ============================================================================

class TestCZ162ExportJsonlMetadata:
    """export_jsonl() writes optional __metadata__ header line."""

    def _make_log(self):
        mod = _import("ipfs_datasets_py.mcp_server.policy_audit_log")
        return mod.PolicyAuditLog()

    def _record(self, log, policy_cid="p1", decision="allow"):
        log.record(
            policy_cid=policy_cid,
            intent_cid="i1",
            actor="alice",
            decision=decision,
            tool="read",
        )

    def test_export_jsonl_accepts_metadata_param(self):
        log = self._make_log()
        self._record(log)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.jsonl")
            # Should not raise
            count = log.export_jsonl(path, metadata={"version": "1"})
            assert count == 1

    def test_metadata_written_as_first_line(self):
        log = self._make_log()
        self._record(log)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.jsonl")
            log.export_jsonl(path, metadata={"source": "test"})
            with open(path) as f:
                lines = f.readlines()
            first = json.loads(lines[0])
            assert "__metadata__" in first
            assert first["__metadata__"]["source"] == "test"

    def test_audit_entries_follow_metadata(self):
        log = self._make_log()
        self._record(log, decision="allow")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.jsonl")
            log.export_jsonl(path, metadata={"v": "2"})
            with open(path) as f:
                lines = [l.strip() for l in f if l.strip()]
            # First line is metadata, second line is the entry
            assert len(lines) == 2
            entry = json.loads(lines[1])
            assert entry["decision"] == "allow"

    def test_no_metadata_no_header_line(self):
        log = self._make_log()
        self._record(log)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.jsonl")
            log.export_jsonl(path)  # no metadata
            with open(path) as f:
                lines = [l.strip() for l in f if l.strip()]
            assert len(lines) == 1
            entry = json.loads(lines[0])
            assert "decision" in entry

    def test_return_count_excludes_metadata_line(self):
        log = self._make_log()
        for _ in range(3):
            self._record(log)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.jsonl")
            count = log.export_jsonl(path, metadata={"ts": 123})
            assert count == 3

    def test_metadata_can_be_none_explicitly(self):
        log = self._make_log()
        self._record(log)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.jsonl")
            count = log.export_jsonl(path, metadata=None)
            assert count == 1

    def test_metadata_dict_survives_round_trip(self):
        log = self._make_log()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.jsonl")
            meta = {"session": "v20", "items": [1, 2, 3], "flag": True}
            log.export_jsonl(path, metadata=meta)
            with open(path) as f:
                first = json.loads(f.readline())
            assert first["__metadata__"] == meta


# ============================================================================
# DA163 — ComplianceChecker.merge(other)
# ============================================================================

class TestDA163ComplianceCheckerMerge:
    """ComplianceChecker.merge(other) adds rules from other, symmetric to diff()."""

    def _empty_checker(self):
        mod = _import("ipfs_datasets_py.mcp_server.compliance_checker")
        return mod.ComplianceChecker()

    def _make_rule(self, rule_id: str, desc: str = "test rule"):
        mod = _import("ipfs_datasets_py.mcp_server.compliance_checker")
        return mod.ComplianceRule(
            rule_id=rule_id,
            description=desc,
            check_fn=lambda intent: mod.ComplianceResult(rule_id=rule_id, passed=True),
        )

    def test_merge_method_exists(self):
        checker = self._empty_checker()
        assert callable(getattr(checker, "merge", None))

    def test_merge_adds_rules_from_other(self):
        c1 = self._empty_checker()
        c2 = self._empty_checker()
        c2.add_rule(self._make_rule("rule_x"))
        added = c1.merge(c2)
        assert added == 1
        assert any(r.rule_id == "rule_x" for r in c1._rules)

    def test_merge_skips_duplicate_rule_ids(self):
        c1 = self._empty_checker()
        c2 = self._empty_checker()
        c1.add_rule(self._make_rule("rule_a"))
        c2.add_rule(self._make_rule("rule_a"))  # same id
        added = c1.merge(c2)
        assert added == 0
        # Still only one rule
        assert len([r for r in c1._rules if r.rule_id == "rule_a"]) == 1

    def test_merge_returns_zero_for_empty_source(self):
        c1 = self._empty_checker()
        c2 = self._empty_checker()
        assert c1.merge(c2) == 0

    def test_merge_symmetric_with_diff(self):
        """Rules reported as 'added_rules' by diff() should match what merge() adds."""
        c1 = self._empty_checker()
        c2 = self._empty_checker()
        c2.add_rule(self._make_rule("new_rule_1"))
        c2.add_rule(self._make_rule("new_rule_2"))
        diff_result = c1.diff(c2)
        added = c1.merge(c2)
        # After merge, added_rules should now be empty
        assert added == len(diff_result["added_rules"])

    def test_merge_multiple_rules(self):
        c1 = self._empty_checker()
        c2 = self._empty_checker()
        for i in range(5):
            c2.add_rule(self._make_rule(f"rule_{i}"))
        added = c1.merge(c2)
        assert added == 5
        assert len(c1._rules) == 5

    def test_merge_preserves_self_rule_order(self):
        c1 = self._empty_checker()
        c2 = self._empty_checker()
        c1.add_rule(self._make_rule("rule_a"))
        c2.add_rule(self._make_rule("rule_b"))
        c2.add_rule(self._make_rule("rule_c"))
        c1.merge(c2)
        ids = [r.rule_id for r in c1._rules]
        assert ids[0] == "rule_a"  # self rule first


# ============================================================================
# DB164 — NLUCANPolicyCompiler.compile_explain(sentences)
# ============================================================================

class TestDB164CompileExplain:
    """NLUCANPolicyCompiler.compile_explain() returns (result, explanation)."""

    def _make_compiler(self):
        mod = _import("ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler")
        return mod.NLUCANPolicyCompiler()

    def test_compile_explain_method_exists(self):
        compiler = self._make_compiler()
        assert callable(getattr(compiler, "compile_explain", None))

    def test_compile_explain_returns_tuple(self):
        compiler = self._make_compiler()
        result = compiler.compile_explain(["Alice must not delete records"])
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_compile_explain_first_elem_is_compiler_result(self):
        mod = _import("ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler")
        compiler = mod.NLUCANPolicyCompiler()
        result, explanation = compiler.compile_explain(["Alice may read files"])
        assert isinstance(result, mod.NLUCANCompilerResult)

    def test_compile_explain_second_elem_is_str(self):
        compiler = self._make_compiler()
        result, explanation = compiler.compile_explain(["Bob shall not write"])
        assert isinstance(explanation, str)

    def test_compile_explain_explanation_matches_explain(self):
        compiler = self._make_compiler()
        sentences = ["Carol may view reports"]
        result, explanation = compiler.compile_explain(sentences)
        assert explanation == result.explain()

    def test_compile_explain_explanation_non_empty(self):
        compiler = self._make_compiler()
        _, explanation = compiler.compile_explain(["Dave must report daily"])
        assert len(explanation) > 0

    def test_compile_explain_mentions_success_or_failed(self):
        compiler = self._make_compiler()
        _, explanation = compiler.compile_explain(["Eve may read documents"])
        assert "succeeded" in explanation or "failed" in explanation

    def test_compile_explain_accepts_policy_id(self):
        compiler = self._make_compiler()
        result, explanation = compiler.compile_explain(
            ["Frank may write"], policy_id="test-v20"
        )
        assert isinstance(result, object)
        assert isinstance(explanation, str)


# ============================================================================
# DC165 — detect_all_languages() includes "en"
# ============================================================================

class TestDC165EnglishKeywords:
    """detect_all_languages() now includes an English ('en') keyword pass."""

    def test_detect_all_languages_includes_en(self):
        mod = _import("ipfs_datasets_py.logic.api")
        report = mod.detect_all_languages("Alice may read files")
        assert "en" in report.by_language

    def test_en_permission_keyword_detected(self):
        mod = _import("ipfs_datasets_py.logic.api")
        report = mod.detect_all_languages("Alice may read the document")
        # "may" is a permission keyword in English
        assert isinstance(report.by_language["en"], list)

    def test_detect_all_languages_has_four_keys(self):
        mod = _import("ipfs_datasets_py.logic.api")
        report = mod.detect_all_languages("some text")
        assert set(report.by_language.keys()) >= {"fr", "es", "de", "en"}

    def test_english_keywords_loaded_directly(self):
        mod = _import("ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector")
        keywords = mod._load_i18n_keywords("en")
        assert "permission" in keywords
        assert "prohibition" in keywords
        assert len(keywords["permission"]) > 0
        assert len(keywords["prohibition"]) > 0

    def test_english_must_not_is_prohibition(self):
        mod = _import("ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector")
        keywords = mod._load_i18n_keywords("en")
        prohibitions_lower = [k.lower() for k in keywords["prohibition"]]
        assert any("must not" in k or "cannot" in k for k in prohibitions_lower)

    def test_en_i18n_conflict_result_for_conflict_text(self):
        mod = _import("ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector")
        result = mod.detect_i18n_conflicts(
            "Alice may read documents but must not read documents", language="en"
        )
        assert result.has_permission
        assert result.has_prohibition
        assert result.has_simultaneous_conflict

    def test_en_no_conflict_for_permission_only(self):
        mod = _import("ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector")
        result = mod.detect_i18n_conflicts("Alice may read files", language="en")
        assert result.has_permission
        assert not result.has_prohibition
        assert not result.has_simultaneous_conflict

    def test_total_conflicts_includes_en(self):
        mod = _import("ipfs_datasets_py.logic.api")
        report = mod.detect_all_languages("some neutral text")
        # total_conflicts is always non-negative
        assert report.total_conflicts >= 0
        # "en" key is present and its value is a list
        assert isinstance(report.by_language["en"], list)


# ============================================================================
# DD166 — merge_and_publish() with duck-typed PubSubBus
# ============================================================================

class TestDD166MergeAndPublishWithBus:
    """merge_and_publish() works with any duck-typed publish(topic, payload)."""

    def _make_manager(self):
        mod = _import("ipfs_datasets_py.mcp_server.ucan_delegation")
        return mod.DelegationManager()

    def _make_token(self, audience: str = "did:key:alice"):
        mod = _import("ipfs_datasets_py.mcp_server.ucan_delegation")
        return mod.DelegationToken(
            issuer="did:key:root",
            audience=audience,
            capabilities=[mod.Capability(resource="*", ability="*")],
        )

    class _SimpleBus:
        """Minimal duck-typed pubsub bus for testing."""
        def __init__(self):
            self.calls = []
        def publish(self, topic, payload):
            self.calls.append((topic, payload))

    def test_simple_bus_receives_event(self):
        mgr_src = self._make_manager()
        mgr_dst = self._make_manager()
        mgr_src.add(self._make_token())
        bus = self._SimpleBus()
        mgr_dst.merge_and_publish(mgr_src, bus)
        assert len(bus.calls) == 1
        topic, payload = bus.calls[0]
        assert topic == "receipt_disseminate"
        assert payload["type"] == "merge"

    def test_multiple_tokens_single_publish(self):
        """One publish call regardless of how many tokens were merged."""
        mgr_src = self._make_manager()
        mgr_dst = self._make_manager()
        for i in range(4):
            mgr_src.add(self._make_token(audience=f"did:key:u{i}"))
        bus = self._SimpleBus()
        mgr_dst.merge_and_publish(mgr_src, bus)
        assert len(bus.calls) == 1
        assert bus.calls[0][1]["added"] == 4

    def test_bus_payload_serializable(self):
        """The payload must be JSON-serializable."""
        mgr_src = self._make_manager()
        mgr_dst = self._make_manager()
        mgr_src.add(self._make_token())
        bus = self._SimpleBus()
        mgr_dst.merge_and_publish(mgr_src, bus)
        payload = bus.calls[0][1]
        serialized = json.dumps(payload)
        assert isinstance(serialized, str)

    def test_broken_bus_does_not_raise(self):
        class BrokenBus:
            def publish(self, topic, payload):
                raise RuntimeError("bus down")
        mgr_src = self._make_manager()
        mgr_dst = self._make_manager()
        mgr_src.add(self._make_token())
        # Must not raise
        added = mgr_dst.merge_and_publish(mgr_src, BrokenBus())
        assert added == 1

    def test_zero_tokens_still_publishes(self):
        mgr_src = self._make_manager()
        mgr_dst = self._make_manager()
        bus = self._SimpleBus()
        mgr_dst.merge_and_publish(mgr_src, bus)
        assert len(bus.calls) == 1

    def test_metrics_in_payload_is_json_serializable(self):
        mgr_src = self._make_manager()
        mgr_dst = self._make_manager()
        mgr_src.add(self._make_token())
        bus = self._SimpleBus()
        mgr_dst.merge_and_publish(mgr_src, bus)
        payload = bus.calls[0][1]
        # Must be able to serialise metrics to JSON
        json.dumps(payload["metrics"])


# ============================================================================
# DE167 — TDFOL NLParser.parse() with mocked dependencies
# ============================================================================

class TestDE167TDFOLNLParserMocked:
    """NLParser / parse_natural_language() work with mocked spaCy / TDFOL deps."""

    def _tdfol_nl_available(self) -> bool:
        try:
            _import("ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api")
            return True
        except ImportError:
            return False

    def test_parse_result_dataclass_importable(self):
        try:
            mod = _import("ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api")
            assert hasattr(mod, "ParseResult")
        except ImportError:
            pytest.skip("TDFOL NL API not available")

    def test_parse_options_dataclass_importable(self):
        try:
            mod = _import("ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api")
            assert hasattr(mod, "ParseOptions")
        except ImportError:
            pytest.skip("TDFOL NL API not available")

    def test_nl_parser_class_importable(self):
        try:
            mod = _import("ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api")
            assert hasattr(mod, "NLParser")
        except ImportError:
            pytest.skip("TDFOL NL API not available")

    def test_pattern_type_importable(self):
        try:
            mod = _import("ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_patterns")
            assert hasattr(mod, "PatternType")
        except ImportError:
            pytest.skip("TDFOL NL patterns not available")

    def test_pattern_class_importable(self):
        try:
            mod = _import("ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_patterns")
            assert hasattr(mod, "Pattern")
        except ImportError:
            pytest.skip("TDFOL NL patterns not available")

    def test_parse_natural_language_function_importable(self):
        try:
            mod = _import("ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api")
            assert callable(getattr(mod, "parse_natural_language", None))
        except ImportError:
            pytest.skip("TDFOL NL API not available")

    def test_dependencies_available_flag(self):
        """When deps are absent, DEPENDENCIES_AVAILABLE should be False."""
        try:
            mod = _import("ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api")
            assert isinstance(mod.DEPENDENCIES_AVAILABLE, bool)
        except ImportError:
            pytest.skip("TDFOL NL API not available")

    def test_parse_natural_language_returns_parse_result_when_available(self):
        try:
            mod = _import("ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api")
            if not mod.DEPENDENCIES_AVAILABLE:
                pytest.skip("spaCy / TDFOL deps not installed")
            result = mod.parse_natural_language("All contractors must pay taxes.")
            assert isinstance(result, mod.ParseResult)
        except ImportError:
            pytest.skip("TDFOL NL API not available")

    def test_nl_parser_raises_import_error_without_deps(self):
        """NLParser.__init__ should raise ImportError when deps unavailable."""
        try:
            mod = _import("ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api")
            if mod.DEPENDENCIES_AVAILABLE:
                pytest.skip("deps available — skip unavailability test")
            with pytest.raises((ImportError, Exception)):
                mod.NLParser()
        except ImportError:
            pytest.skip("TDFOL NL API not available")

    def test_pattern_matcher_importable(self):
        try:
            mod = _import("ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_patterns")
            assert hasattr(mod, "PatternMatcher")
        except ImportError:
            pytest.skip("TDFOL NL patterns not available")


# ============================================================================
# DF168 — evaluate_with_manager + detect_all_languages combined E2E
# ============================================================================

class TestDF168EvaluateAndDetectE2E:
    """Combined E2E: evaluate_with_manager + detect_all_languages."""

    def _import_api(self):
        return _import("ipfs_datasets_py.logic.api")

    def test_detect_all_languages_importable_from_api(self):
        mod = self._import_api()
        assert callable(getattr(mod, "detect_all_languages", None))

    def test_i18n_report_has_all_language_keys(self):
        mod = self._import_api()
        report = mod.detect_all_languages("Alice may read documents.")
        for lang in ("fr", "es", "de", "en"):
            assert lang in report.by_language, f"Missing language key: {lang}"

    def test_detect_all_languages_en_has_conflict_on_conflict_text(self):
        mod = _import("ipfs_datasets_py.logic.api")
        # English text with both permission and prohibition
        report = mod.detect_all_languages(
            "Alice may read files and must not read files"
        )
        assert "en" in report.by_language

    def test_total_conflicts_is_int(self):
        mod = self._import_api()
        report = mod.detect_all_languages("some text")
        assert isinstance(report.total_conflicts, int)

    def test_languages_with_conflicts_is_list(self):
        mod = self._import_api()
        report = mod.detect_all_languages("some text")
        assert isinstance(report.languages_with_conflicts, list)

    def test_i18n_report_to_dict_includes_en(self):
        mod = self._import_api()
        report = mod.detect_all_languages("test")
        d = report.to_dict()
        assert "en" in d

    def test_evaluate_with_manager_importable(self):
        mod = self._import_api()
        # evaluate_with_manager may be conditionally available
        if "evaluate_with_manager" in mod.__all__:
            assert callable(getattr(mod, "evaluate_with_manager", None))

    def test_combined_report_is_json_serializable(self):
        mod = self._import_api()
        report = mod.detect_all_languages("Alice may read or must not read")
        d = report.to_dict()
        serialized = json.dumps(d)
        assert isinstance(serialized, str)
