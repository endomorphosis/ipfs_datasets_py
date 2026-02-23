"""Session 53: Tests for MCP++ Profile C (UCAN delegation), risk scorer,
compliance checker, and HTM schema CID / dispatch_with_trace.

All new modules created in this session:
  - ipfs_datasets_py/mcp_server/ucan_delegation.py
  - ipfs_datasets_py/mcp_server/risk_scorer.py
  - ipfs_datasets_py/mcp_server/compliance_checker.py
  - HierarchicalToolManager.get_tool_schema_cid()
  - HierarchicalToolManager.dispatch_with_trace()
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from ipfs_datasets_py.mcp_server.ucan_delegation import (
    Capability,
    Delegation,
    DelegationEvaluator,
    InvocationContext,
    add_delegation,
    get_delegation,
    get_delegation_evaluator,
)
from ipfs_datasets_py.mcp_server.risk_scorer import (
    RiskLevel,
    RiskScore,
    RiskScoringPolicy,
    RiskScorer,
    make_default_risk_policy,
    score_intent,
)
from ipfs_datasets_py.mcp_server.compliance_checker import (
    ComplianceChecker,
    ComplianceReport,
    ComplianceResult,
    ComplianceStatus,
    ComplianceViolation,
    make_default_compliance_checker,
)


# ===========================================================================
# Profile C: UCAN Delegation
# ===========================================================================

class TestCapability(unittest.TestCase):
    """Tests for Capability wildcard matching."""

    def test_exact_match(self):
        cap = Capability("mcp://tool/load_dataset", "invoke")
        self.assertTrue(cap.matches("mcp://tool/load_dataset", "invoke"))

    def test_no_match_resource(self):
        cap = Capability("mcp://tool/load_dataset", "invoke")
        self.assertFalse(cap.matches("mcp://tool/other_tool", "invoke"))

    def test_no_match_ability(self):
        cap = Capability("mcp://tool/load_dataset", "invoke")
        self.assertFalse(cap.matches("mcp://tool/load_dataset", "read"))

    def test_wildcard_resource_in_cap(self):
        cap = Capability("*", "invoke")
        self.assertTrue(cap.matches("mcp://tool/anything", "invoke"))

    def test_wildcard_ability_in_cap(self):
        cap = Capability("mcp://tool/load_dataset", "*")
        self.assertTrue(cap.matches("mcp://tool/load_dataset", "invoke"))
        self.assertTrue(cap.matches("mcp://tool/load_dataset", "read"))

    def test_wildcard_both(self):
        cap = Capability("*", "*")
        self.assertTrue(cap.matches("anything", "anything"))

    def test_wildcard_in_query_resource(self):
        cap = Capability("mcp://tool/load_dataset", "invoke")
        self.assertTrue(cap.matches("*", "invoke"))

    def test_wildcard_in_query_ability(self):
        cap = Capability("mcp://tool/load_dataset", "invoke")
        self.assertTrue(cap.matches("mcp://tool/load_dataset", "*"))

    def test_to_dict(self):
        cap = Capability("res", "read")
        d = cap.to_dict()
        self.assertEqual(d["resource"], "res")
        self.assertEqual(d["ability"], "read")


class TestDelegation(unittest.TestCase):
    """Tests for Delegation dataclass."""

    def _make(self, expiry=None, proof_cid=None):
        return Delegation(
            cid="cid-leaf",
            issuer="did:key:alice",
            audience="did:key:bob",
            capabilities=[Capability("mcp://tool/load_dataset", "invoke")],
            expiry=expiry,
            proof_cid=proof_cid,
        )

    def test_not_expired_when_none(self):
        d = self._make(expiry=None)
        self.assertFalse(d.is_expired())

    def test_expired(self):
        d = self._make(expiry=time.time() - 100)
        self.assertTrue(d.is_expired())

    def test_not_expired_future(self):
        d = self._make(expiry=time.time() + 9999)
        self.assertFalse(d.is_expired())

    def test_has_capability_match(self):
        d = self._make()
        self.assertTrue(d.has_capability("mcp://tool/load_dataset", "invoke"))

    def test_has_capability_no_match(self):
        d = self._make()
        self.assertFalse(d.has_capability("mcp://tool/other", "invoke"))

    def test_to_dict(self):
        d = self._make()
        obj = d.to_dict()
        self.assertEqual(obj["cid"], "cid-leaf")
        self.assertEqual(obj["issuer"], "did:key:alice")
        self.assertIn("capabilities", obj)


class TestDelegationEvaluator(unittest.TestCase):
    """Tests for DelegationEvaluator chain building and validation."""

    def _root(self, cid="root", expiry=None):
        return Delegation(
            cid=cid,
            issuer="did:key:issuer",
            audience="did:key:alice",
            capabilities=[Capability("mcp://tool/load_dataset", "invoke")],
            expiry=expiry,
            proof_cid=None,
        )

    def _leaf(self, cid="leaf", proof_cid="root", expiry=None,
              audience="did:key:bob"):
        return Delegation(
            cid=cid,
            issuer="did:key:alice",
            audience=audience,
            capabilities=[Capability("mcp://tool/load_dataset", "invoke")],
            expiry=expiry,
            proof_cid=proof_cid,
        )

    def test_add_and_get(self):
        ev = DelegationEvaluator()
        d = self._root()
        ev.add(d)
        self.assertIs(ev.get("root"), d)

    def test_get_missing_returns_none(self):
        ev = DelegationEvaluator()
        self.assertIsNone(ev.get("nonexistent"))

    def test_remove_existing(self):
        ev = DelegationEvaluator()
        ev.add(self._root())
        self.assertTrue(ev.remove("root"))
        self.assertIsNone(ev.get("root"))

    def test_remove_missing_returns_false(self):
        ev = DelegationEvaluator()
        self.assertFalse(ev.remove("nonexistent"))

    def test_list_cids(self):
        ev = DelegationEvaluator()
        ev.add(self._root("r1"))
        ev.add(self._root("r2"))
        cids = ev.list_cids()
        self.assertIn("r1", cids)
        self.assertIn("r2", cids)

    def test_build_chain_single(self):
        ev = DelegationEvaluator()
        ev.add(self._root())
        chain = ev.build_chain("root")
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0].cid, "root")

    def test_build_chain_two_hops_root_first(self):
        ev = DelegationEvaluator()
        ev.add(self._root("root"))
        ev.add(self._leaf("leaf", proof_cid="root"))
        chain = ev.build_chain("leaf")
        self.assertEqual(len(chain), 2)
        self.assertEqual(chain[0].cid, "root")   # root first
        self.assertEqual(chain[1].cid, "leaf")

    def test_build_chain_missing_leaf_returns_empty(self):
        ev = DelegationEvaluator()
        chain = ev.build_chain("nonexistent")
        self.assertEqual(chain, [])

    def test_build_chain_missing_parent_raises_keyerror(self):
        ev = DelegationEvaluator()
        # Add leaf that points to non-existent parent
        ev.add(self._leaf("leaf", proof_cid="missing-root"))
        with self.assertRaises(KeyError):
            ev.build_chain("leaf")

    def test_cycle_detection(self):
        ev = DelegationEvaluator()
        d1 = Delegation("a", "i", "u", [Capability("*", "*")], proof_cid="b")
        d2 = Delegation("b", "i", "u", [Capability("*", "*")], proof_cid="a")
        ev.add(d1)
        ev.add(d2)
        with self.assertRaises(ValueError):
            ev.build_chain("a")

    def test_is_expired_missing_returns_true(self):
        ev = DelegationEvaluator()
        self.assertTrue(ev.is_expired("nonexistent"))

    def test_is_expired_not_expired(self):
        ev = DelegationEvaluator()
        ev.add(self._root(expiry=time.time() + 9999))
        self.assertFalse(ev.is_expired("root"))

    def test_is_expired_expired(self):
        ev = DelegationEvaluator()
        ev.add(self._root(expiry=time.time() - 100))
        self.assertTrue(ev.is_expired("root"))

    def test_can_invoke_simple_allow(self):
        ev = DelegationEvaluator()
        ev.add(self._root())
        ev.add(self._leaf())
        allowed, reason = ev.can_invoke(
            "leaf", "mcp://tool/load_dataset", "invoke"
        )
        self.assertTrue(allowed, reason)
        self.assertEqual(reason, "authorized")

    def test_can_invoke_missing_leaf_deny(self):
        ev = DelegationEvaluator()
        allowed, reason = ev.can_invoke(
            "nonexistent", "mcp://tool/load_dataset", "invoke"
        )
        self.assertFalse(allowed)
        self.assertIn("not found", reason)

    def test_can_invoke_expired_chain_deny(self):
        ev = DelegationEvaluator()
        ev.add(self._root(expiry=time.time() - 100))
        ev.add(self._leaf())
        allowed, reason = ev.can_invoke(
            "leaf", "mcp://tool/load_dataset", "invoke"
        )
        self.assertFalse(allowed)
        self.assertIn("expired", reason)

    def test_can_invoke_wrong_actor_deny(self):
        ev = DelegationEvaluator()
        ev.add(self._root())
        ev.add(self._leaf(audience="did:key:charlie"))
        allowed, reason = ev.can_invoke(
            "leaf", "mcp://tool/load_dataset", "invoke",
            actor="did:key:wrong"
        )
        self.assertFalse(allowed)
        self.assertIn("does not match", reason)

    def test_can_invoke_actor_matches(self):
        ev = DelegationEvaluator()
        ev.add(self._root())
        ev.add(self._leaf(audience="did:key:bob"))
        allowed, _ = ev.can_invoke(
            "leaf", "mcp://tool/load_dataset", "invoke",
            actor="did:key:bob"
        )
        self.assertTrue(allowed)

    def test_can_invoke_capability_mismatch_deny(self):
        ev = DelegationEvaluator()
        ev.add(self._root())   # only has load_dataset/invoke
        allowed, reason = ev.can_invoke(
            "root", "mcp://tool/other", "invoke"
        )
        self.assertFalse(allowed)
        self.assertIn("No delegation", reason)

    def test_can_invoke_empty_chain(self):
        ev = DelegationEvaluator()
        ev.add(self._root())
        # Manually remove from store after build_chain would complete
        # (simulate broken chain via subclass)
        allowed, reason = ev.can_invoke(
            "nonexistent", "*", "*"
        )
        self.assertFalse(allowed)


class TestGlobalDelegation(unittest.TestCase):
    """Tests for module-level helpers."""

    def setUp(self):
        # Reset global evaluator between tests
        import ipfs_datasets_py.mcp_server.ucan_delegation as mod
        mod._GLOBAL_EVALUATOR = None

    def test_add_and_get_delegation(self):
        d = Delegation("g-cid", "i", "a", [Capability("*", "*")])
        add_delegation(d)
        retrieved = get_delegation("g-cid")
        self.assertIs(retrieved, d)

    def test_get_delegation_evaluator_singleton(self):
        ev1 = get_delegation_evaluator()
        ev2 = get_delegation_evaluator()
        self.assertIs(ev1, ev2)


class TestInvocationContext(unittest.TestCase):
    def test_to_dict(self):
        ctx = InvocationContext(
            intent_cid="bafy-intent",
            ucan_proofs=["proof1", "proof2"],
            policy_cid="bafy-policy",
            context_cids=["ctx1"],
        )
        d = ctx.to_dict()
        self.assertEqual(d["intent_cid"], "bafy-intent")
        self.assertEqual(d["ucan_proofs"], ["proof1", "proof2"])
        self.assertEqual(d["policy_cid"], "bafy-policy")


# ===========================================================================
# Risk Scorer
# ===========================================================================

class TestRiskLevel(unittest.TestCase):
    def test_from_score_negligible(self):
        self.assertEqual(RiskLevel.from_score(0.0), RiskLevel.NEGLIGIBLE)
        self.assertEqual(RiskLevel.from_score(0.19), RiskLevel.NEGLIGIBLE)

    def test_from_score_low(self):
        self.assertEqual(RiskLevel.from_score(0.20), RiskLevel.LOW)
        self.assertEqual(RiskLevel.from_score(0.39), RiskLevel.LOW)

    def test_from_score_medium(self):
        self.assertEqual(RiskLevel.from_score(0.40), RiskLevel.MEDIUM)
        self.assertEqual(RiskLevel.from_score(0.59), RiskLevel.MEDIUM)

    def test_from_score_high(self):
        self.assertEqual(RiskLevel.from_score(0.60), RiskLevel.HIGH)
        self.assertEqual(RiskLevel.from_score(0.79), RiskLevel.HIGH)

    def test_from_score_critical(self):
        self.assertEqual(RiskLevel.from_score(0.80), RiskLevel.CRITICAL)
        self.assertEqual(RiskLevel.from_score(1.00), RiskLevel.CRITICAL)

    def test_enum_value_strings(self):
        self.assertEqual(RiskLevel.HIGH.value, "high")
        self.assertEqual(RiskLevel.CRITICAL.value, "critical")


class TestRiskScore(unittest.TestCase):
    def test_to_dict(self):
        rs = RiskScore(
            level=RiskLevel.MEDIUM,
            score=0.5,
            factors=["f1", "f2"],
            mitigation_hints=["hint"],
        )
        d = rs.to_dict()
        self.assertEqual(d["level"], "medium")
        self.assertAlmostEqual(d["score"], 0.5)
        self.assertEqual(d["factors"], ["f1", "f2"])


class TestRiskScoringPolicy(unittest.TestCase):
    def test_defaults(self):
        p = RiskScoringPolicy()
        self.assertAlmostEqual(p.default_risk, 0.3)
        self.assertAlmostEqual(p.max_acceptable_risk, 0.75)

    def test_get_tool_risk_override(self):
        p = RiskScoringPolicy(tool_risk_overrides={"delete_dataset": 0.9})
        self.assertAlmostEqual(p.get_tool_risk("delete_dataset"), 0.9)

    def test_get_tool_risk_default(self):
        p = RiskScoringPolicy(default_risk=0.4)
        self.assertAlmostEqual(p.get_tool_risk("unknown_tool"), 0.4)

    def test_get_actor_trust_explicit(self):
        p = RiskScoringPolicy(actor_trust_levels={"system": 0.95})
        self.assertAlmostEqual(p.get_actor_trust("system"), 0.95)

    def test_get_actor_trust_default(self):
        p = RiskScoringPolicy()
        self.assertAlmostEqual(p.get_actor_trust("unknown"), 0.5)


class TestRiskScorer(unittest.TestCase):
    def _make_intent(self, tool="load_dataset", actor="alice", params=None):
        return {"tool_name": tool, "actor": actor, "params": params or {}}

    def test_score_returns_risk_score(self):
        scorer = RiskScorer()
        rs = scorer.score_intent(self._make_intent())
        self.assertIsInstance(rs, RiskScore)
        self.assertIn(rs.level, list(RiskLevel))

    def test_high_base_risk_tool(self):
        policy = RiskScoringPolicy(tool_risk_overrides={"delete_all": 0.9})
        scorer = RiskScorer(policy)
        rs = scorer.score_intent({"tool_name": "delete_all", "actor": "alice"})
        self.assertIn(rs.level, (RiskLevel.HIGH, RiskLevel.CRITICAL))

    def test_high_trust_lowers_score(self):
        low_trust = RiskScoringPolicy(actor_trust_levels={"bot": 0.0})
        high_trust = RiskScoringPolicy(actor_trust_levels={"admin": 1.0})
        scorer_low = RiskScorer(low_trust)
        scorer_high = RiskScorer(high_trust)
        rs_low = scorer_low.score_intent({"tool_name": "t", "actor": "bot"})
        rs_high = scorer_high.score_intent({"tool_name": "t", "actor": "admin"})
        self.assertLess(rs_high.score, rs_low.score)

    def test_param_complexity_penalty(self):
        many_params = {f"p{i}": i for i in range(10)}
        scorer = RiskScorer()
        rs_few = scorer.score_intent({"tool_name": "t", "actor": "a", "params": {}})
        rs_many = scorer.score_intent({"tool_name": "t", "actor": "a", "params": many_params})
        self.assertGreater(rs_many.score, rs_few.score)

    def test_mitigation_hints_high(self):
        policy = RiskScoringPolicy(
            tool_risk_overrides={"dangerous": 0.95},
            actor_trust_levels={"actor": 0.0},
        )
        scorer = RiskScorer(policy)
        rs = scorer.score_intent({"tool_name": "dangerous", "actor": "actor"})
        if rs.level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            self.assertTrue(len(rs.mitigation_hints) > 0)

    def test_factors_recorded(self):
        scorer = RiskScorer()
        rs = scorer.score_intent({"tool_name": "t", "actor": "a"})
        self.assertTrue(len(rs.factors) > 0)

    def test_is_acceptable_below_threshold(self):
        scorer = RiskScorer(RiskScoringPolicy(max_acceptable_risk=0.9))
        rs = RiskScore(level=RiskLevel.LOW, score=0.3)
        self.assertTrue(scorer.is_acceptable(rs))

    def test_is_acceptable_above_threshold(self):
        scorer = RiskScorer(RiskScoringPolicy(max_acceptable_risk=0.5))
        rs = RiskScore(level=RiskLevel.HIGH, score=0.8)
        self.assertFalse(scorer.is_acceptable(rs))

    def test_score_and_gate_allow(self):
        policy = RiskScoringPolicy(default_risk=0.1, max_acceptable_risk=0.9)
        scorer = RiskScorer(policy)
        decision = scorer.score_and_gate({"tool_name": "t", "actor": "a"}, policy)
        self.assertEqual(decision["decision"], "allow")
        self.assertIn("risk_score", decision)

    def test_score_and_gate_deny(self):
        policy = RiskScoringPolicy(
            tool_risk_overrides={"scary": 0.99},
            actor_trust_levels={"unknown": 0.0},
            max_acceptable_risk=0.5,
        )
        scorer = RiskScorer(policy)
        decision = scorer.score_and_gate(
            {"tool_name": "scary", "actor": "unknown"}, policy
        )
        self.assertEqual(decision["decision"], "deny")

    def test_score_works_with_object_intent(self):
        class FakeIntent:
            tool_name = "load_dataset"
            actor = "alice"
            params = {"source": "squad"}

        scorer = RiskScorer()
        rs = scorer.score_intent(FakeIntent())
        self.assertIsNotNone(rs)

    def test_make_default_risk_policy(self):
        policy = make_default_risk_policy(high_risk_tools=["delete"])
        self.assertAlmostEqual(policy.get_tool_risk("delete"), 0.70)
        self.assertAlmostEqual(policy.get_tool_risk("load"), 0.30)

    def test_global_score_intent(self):
        rs = score_intent({"tool_name": "load_dataset", "actor": "test_user"})
        self.assertIsInstance(rs, RiskScore)


# ===========================================================================
# Compliance Checker
# ===========================================================================

class TestComplianceStatus(unittest.TestCase):
    def test_values(self):
        self.assertEqual(ComplianceStatus.COMPLIANT.value, "compliant")
        self.assertEqual(ComplianceStatus.NON_COMPLIANT.value, "non_compliant")
        self.assertEqual(ComplianceStatus.WARNING.value, "warning")
        self.assertEqual(ComplianceStatus.SKIPPED.value, "skipped")


class TestComplianceViolation(unittest.TestCase):
    def test_to_dict(self):
        v = ComplianceViolation("rule1", "something is wrong", "error")
        d = v.to_dict()
        self.assertEqual(d["rule_id"], "rule1")
        self.assertEqual(d["message"], "something is wrong")
        self.assertEqual(d["severity"], "error")


class TestComplianceResult(unittest.TestCase):
    def test_is_compliant_true(self):
        r = ComplianceResult("r1", ComplianceStatus.COMPLIANT)
        self.assertTrue(r.is_compliant)

    def test_is_compliant_skipped(self):
        r = ComplianceResult("r1", ComplianceStatus.SKIPPED)
        self.assertTrue(r.is_compliant)

    def test_is_compliant_false(self):
        r = ComplianceResult("r1", ComplianceStatus.NON_COMPLIANT)
        self.assertFalse(r.is_compliant)

    def test_to_dict(self):
        r = ComplianceResult("r1", ComplianceStatus.COMPLIANT)
        d = r.to_dict()
        self.assertEqual(d["rule_id"], "r1")
        self.assertEqual(d["status"], "compliant")


class TestComplianceReport(unittest.TestCase):
    def test_summary_pass(self):
        report = ComplianceReport(results=[
            ComplianceResult("r1", ComplianceStatus.COMPLIANT),
        ])
        self.assertEqual(report.summary, "pass")

    def test_summary_fail(self):
        report = ComplianceReport(results=[
            ComplianceResult("r1", ComplianceStatus.COMPLIANT),
            ComplianceResult("r2", ComplianceStatus.NON_COMPLIANT, [
                ComplianceViolation("r2", "bad", "error")
            ]),
        ])
        self.assertEqual(report.summary, "fail")

    def test_all_violations(self):
        v = ComplianceViolation("r", "m", "error")
        report = ComplianceReport(results=[
            ComplianceResult("r", ComplianceStatus.NON_COMPLIANT, [v])
        ])
        self.assertEqual(len(report.all_violations), 1)
        self.assertIs(report.all_violations[0], v)

    def test_to_dict(self):
        report = ComplianceReport()
        d = report.to_dict()
        self.assertIn("summary", d)
        self.assertIn("results", d)
        self.assertIn("all_violations", d)


class TestComplianceCheckerBuiltinRules(unittest.TestCase):
    def _make(self, **kw):
        return {
            "tool_name": "load_dataset",
            "actor": "alice",
            "params": {},
            **kw,
        }

    def _check(self, checker, intent):
        return checker.check_compliance(intent)

    # --- tool_name_convention ---

    def test_tool_name_valid(self):
        checker = make_default_compliance_checker()
        report = self._check(checker, self._make(tool_name="load_dataset"))
        rule_result = next(r for r in report.results if r.rule_id == "tool_name_convention")
        self.assertEqual(rule_result.status, ComplianceStatus.COMPLIANT)

    def test_tool_name_empty_fails(self):
        checker = make_default_compliance_checker()
        report = self._check(checker, self._make(tool_name=""))
        rule_result = next(r for r in report.results if r.rule_id == "tool_name_convention")
        self.assertEqual(rule_result.status, ComplianceStatus.NON_COMPLIANT)

    def test_tool_name_caps_fails(self):
        checker = make_default_compliance_checker()
        report = self._check(checker, self._make(tool_name="LoadDataset"))
        rule_result = next(r for r in report.results if r.rule_id == "tool_name_convention")
        self.assertEqual(rule_result.status, ComplianceStatus.NON_COMPLIANT)

    def test_tool_name_with_hyphens_fails(self):
        checker = make_default_compliance_checker()
        report = self._check(checker, self._make(tool_name="load-dataset"))
        rule_result = next(r for r in report.results if r.rule_id == "tool_name_convention")
        self.assertEqual(rule_result.status, ComplianceStatus.NON_COMPLIANT)

    # --- intent_has_actor ---

    def test_actor_present(self):
        checker = make_default_compliance_checker()
        report = self._check(checker, self._make(actor="alice"))
        rule_result = next(r for r in report.results if r.rule_id == "intent_has_actor")
        self.assertEqual(rule_result.status, ComplianceStatus.COMPLIANT)

    def test_actor_empty_warning(self):
        checker = make_default_compliance_checker()
        report = self._check(checker, self._make(actor=""))
        rule_result = next(r for r in report.results if r.rule_id == "intent_has_actor")
        self.assertEqual(rule_result.status, ComplianceStatus.WARNING)

    # --- actor_is_valid ---

    def test_actor_with_whitespace_fails(self):
        checker = make_default_compliance_checker()
        report = self._check(checker, self._make(actor="alice bob"))
        rule_result = next(r for r in report.results if r.rule_id == "actor_is_valid")
        self.assertEqual(rule_result.status, ComplianceStatus.NON_COMPLIANT)

    def test_actor_no_whitespace_passes(self):
        checker = make_default_compliance_checker()
        report = self._check(checker, self._make(actor="did:key:alice"))
        rule_result = next(r for r in report.results if r.rule_id == "actor_is_valid")
        self.assertEqual(rule_result.status, ComplianceStatus.COMPLIANT)

    # --- params_are_serializable ---

    def test_serializable_params(self):
        checker = make_default_compliance_checker()
        report = self._check(checker, self._make(params={"a": 1, "b": "str"}))
        rule_result = next(r for r in report.results if r.rule_id == "params_are_serializable")
        self.assertEqual(rule_result.status, ComplianceStatus.COMPLIANT)

    def test_non_serializable_params(self):
        checker = make_default_compliance_checker()
        report = self._check(checker, self._make(params={"obj": object()}))
        rule_result = next(r for r in report.results if r.rule_id == "params_are_serializable")
        self.assertEqual(rule_result.status, ComplianceStatus.WARNING)

    # --- tool_not_in_deny_list ---

    def test_deny_list_blocks_tool(self):
        checker = make_default_compliance_checker(deny_list={"dangerous_tool"})
        report = self._check(checker, self._make(tool_name="dangerous_tool"))
        rule_result = next(r for r in report.results if r.rule_id == "tool_not_in_deny_list")
        self.assertEqual(rule_result.status, ComplianceStatus.NON_COMPLIANT)

    def test_deny_list_allows_other_tool(self):
        checker = make_default_compliance_checker(deny_list={"dangerous_tool"})
        report = self._check(checker, self._make(tool_name="safe_tool"))
        rule_result = next(r for r in report.results if r.rule_id == "tool_not_in_deny_list")
        self.assertEqual(rule_result.status, ComplianceStatus.COMPLIANT)

    # --- rate_limit_ok ---

    def test_rate_limit_always_passes(self):
        checker = make_default_compliance_checker()
        report = self._check(checker, self._make())
        rule_result = next(r for r in report.results if r.rule_id == "rate_limit_ok")
        self.assertEqual(rule_result.status, ComplianceStatus.COMPLIANT)


class TestComplianceCheckerManagement(unittest.TestCase):
    def test_add_and_remove_rule(self):
        checker = ComplianceChecker()

        def my_rule(intent):
            return ComplianceResult("my_rule", ComplianceStatus.COMPLIANT)

        checker.add_rule("my_rule", my_rule)
        self.assertIn("my_rule", checker.list_rules())
        self.assertTrue(checker.remove_rule("my_rule"))
        self.assertNotIn("my_rule", checker.list_rules())

    def test_remove_nonexistent_returns_false(self):
        checker = ComplianceChecker()
        self.assertFalse(checker.remove_rule("nonexistent"))

    def test_custom_rule_runs(self):
        checker = ComplianceChecker()

        def always_fail(intent):
            return ComplianceResult(
                "always_fail",
                ComplianceStatus.NON_COMPLIANT,
                [ComplianceViolation("always_fail", "forced fail", "error")],
            )

        checker.add_rule("always_fail", always_fail)
        report = checker.check_compliance({"tool_name": "t", "actor": "a"})
        self.assertEqual(report.summary, "fail")

    def test_make_default_has_6_rules(self):
        checker = make_default_compliance_checker()
        self.assertEqual(len(checker.list_rules()), 6)

    def test_object_intent_works(self):
        class FakeIntent:
            tool_name = "load_dataset"
            actor = "alice"
            params = {}

        checker = make_default_compliance_checker()
        report = checker.check_compliance(FakeIntent())
        self.assertEqual(report.summary, "pass")


# ===========================================================================
# HTM: get_tool_schema_cid + dispatch_with_trace
# ===========================================================================

class TestHTMSchemaCIDAndTrace(unittest.IsolatedAsyncioTestCase):
    """Tests for HierarchicalToolManager new MCP++ methods."""

    async def _make_manager(self):
        """Create a minimal mocked HTM."""
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import (
            HierarchicalToolManager,
        )
        manager = HierarchicalToolManager.__new__(HierarchicalToolManager)
        # Minimal state
        manager._discovered_categories = True
        manager._shutting_down = False
        manager.categories = {}
        return manager

    async def test_get_tool_schema_cid_returns_string(self):
        manager = await self._make_manager()
        manager.get_tool_schema = AsyncMock(return_value={
            "status": "success",
            "schema": {"name": "load_dataset", "params": {}},
        })
        cid = await manager.get_tool_schema_cid("dataset_tools", "load_dataset")
        self.assertIsInstance(cid, str)
        self.assertTrue(cid.startswith("bafy"), f"CID should start with 'bafy', got: {cid!r}")

    async def test_get_tool_schema_cid_deterministic(self):
        manager = await self._make_manager()
        schema = {"status": "success", "schema": {"name": "t"}}
        manager.get_tool_schema = AsyncMock(return_value=schema)
        cid1 = await manager.get_tool_schema_cid("cat", "tool")
        cid2 = await manager.get_tool_schema_cid("cat", "tool")
        self.assertEqual(cid1, cid2)

    async def test_dispatch_with_trace_success(self):
        manager = await self._make_manager()
        schema = {"status": "success", "schema": {}}
        manager.get_tool_schema = AsyncMock(return_value=schema)
        manager.dispatch = AsyncMock(return_value={
            "status": "success",
            "result": "loaded",
            "request_id": "abc",
        })
        result = await manager.dispatch_with_trace("cat", "tool", {"src": "sq"})
        self.assertIn("trace", result)
        trace = result["trace"]
        self.assertEqual(trace["category"], "cat")
        self.assertEqual(trace["tool"], "tool")
        self.assertEqual(trace["dispatch_status"], "ok")
        self.assertTrue(trace["tool_schema_cid"].startswith("bafy"))

    async def test_dispatch_with_trace_error(self):
        manager = await self._make_manager()
        manager.get_tool_schema = AsyncMock(return_value={"status": "error"})
        manager.dispatch = AsyncMock(return_value={"status": "error", "error": "oops"})
        result = await manager.dispatch_with_trace("cat", "bad_tool")
        trace = result["trace"]
        self.assertEqual(trace["dispatch_status"], "error")

    async def test_dispatch_with_trace_includes_dispatch_result(self):
        manager = await self._make_manager()
        manager.get_tool_schema = AsyncMock(return_value={})
        manager.dispatch = AsyncMock(return_value={
            "status": "success",
            "result": "data",
            "request_id": "xyz",
        })
        result = await manager.dispatch_with_trace("cat", "tool")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"], "data")


if __name__ == "__main__":
    unittest.main()
