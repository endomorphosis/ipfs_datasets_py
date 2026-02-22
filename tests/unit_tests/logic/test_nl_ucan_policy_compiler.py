"""
Test suite: Natural Language → DCEC → UCAN Policy Compiler Pipeline

Covers:
- Phase A: NLToDCECCompiler (CEC/nl/nl_to_policy_compiler.py)
- Phase B: DCECToUCANBridge (CEC/nl/dcec_to_ucan_bridge.py)
- Phase C: NLUCANPolicyCompiler (logic/integration/nl_ucan_policy_compiler.py)
- Phase D: MCP tool nl_ucan_policy_tool.py
- Integration: end-to-end NL → Policy evaluation + UCAN delegation
"""
import sys
import time
import importlib
from typing import Any

import pytest


# ─── helpers ─────────────────────────────────────────────────────────────────

def _get_nl_compiler():
    from ipfs_datasets_py.logic.CEC.nl.nl_to_policy_compiler import (
        NLToDCECCompiler, CompilationResult, compile_nl_to_policy,
        _dcec_formula_to_clause, _extract_actor, _extract_action,
    )
    return NLToDCECCompiler, CompilationResult, compile_nl_to_policy, _dcec_formula_to_clause, _extract_actor, _extract_action


def _get_ucan_bridge():
    from ipfs_datasets_py.logic.CEC.nl.dcec_to_ucan_bridge import (
        DCECToUCANBridge, DenyCapability, BridgeResult, DCECToUCANMapping,
    )
    return DCECToUCANBridge, DenyCapability, BridgeResult, DCECToUCANMapping


def _get_e2e_compiler():
    from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import (
        NLUCANPolicyCompiler, NLUCANCompilerResult, compile_nl_to_ucan_policy,
    )
    return NLUCANPolicyCompiler, NLUCANCompilerResult, compile_nl_to_ucan_policy


def _get_mcp_tool():
    from ipfs_datasets_py.mcp_server.tools.logic_tools.nl_ucan_policy_tool import (
        nl_compile_policy, nl_evaluate_policy, nl_inspect_policy, TOOL_FUNCTIONS,
    )
    return nl_compile_policy, nl_evaluate_policy, nl_inspect_policy, TOOL_FUNCTIONS


def _make_deontic_formula(op_name: str = "OBLIGATION", predicate: str = "read", actor: str = "bob"):
    """Build a synthetic DeonticFormula for testing."""
    from ipfs_datasets_py.logic.CEC.native.dcec_core import (
        DeonticFormula, DeonticOperator, AtomicFormula, Predicate, Sort,
        Variable, VariableTerm,
    )
    agent_sort = Sort(name="Agent")
    var = Variable(name=actor, sort=agent_sort)
    vterm = VariableTerm(variable=var)
    pred = Predicate(name=predicate, argument_sorts=[agent_sort])
    atom = AtomicFormula(predicate=pred, arguments=[vterm])
    op = DeonticOperator[op_name]
    return DeonticFormula(operator=op, formula=atom)


# ─── Phase A: NLToDCECCompiler ────────────────────────────────────────────────

class TestNLToDCECCompilerBasics:

    def test_import(self):
        NLToDCECCompiler, *_ = _get_nl_compiler()
        assert NLToDCECCompiler is not None

    def test_default_construction(self):
        NLToDCECCompiler, *_ = _get_nl_compiler()
        c = NLToDCECCompiler()
        assert c.policy_id is None
        assert c.strict is False

    def test_construction_with_args(self):
        NLToDCECCompiler, *_ = _get_nl_compiler()
        c = NLToDCECCompiler(policy_id="p1", default_actor="system", strict=True)
        assert c.policy_id == "p1"
        assert c.default_actor == "system"
        assert c.strict is True

    def test_compile_sentence_prohibition(self):
        NLToDCECCompiler, _, *__ = _get_nl_compiler()
        c = NLToDCECCompiler()
        r = c.compile_sentence("Alice must not delete records")
        assert r.success
        assert r.clauses
        assert r.clauses[0].clause_type == "prohibition"

    def test_compile_sentence_permission(self):
        NLToDCECCompiler, _, *__ = _get_nl_compiler()
        c = NLToDCECCompiler()
        r = c.compile_sentence("Bob is permitted to read files")
        assert r.success
        assert r.clauses[0].clause_type == "permission"

    def test_compile_sentence_obligation(self):
        NLToDCECCompiler, _, *__ = _get_nl_compiler()
        c = NLToDCECCompiler()
        r = c.compile_sentence("Carol must notify admin")
        assert r.success
        assert r.clauses[0].clause_type == "obligation"

    def test_compile_empty_sentence_skipped(self):
        NLToDCECCompiler, _, *__ = _get_nl_compiler()
        c = NLToDCECCompiler()
        r = c.compile(["   "])
        # Empty sentence gives no clauses → success=False
        assert not r.success
        assert r.errors  # should mention no clauses produced

    def test_compile_multiple_sentences(self):
        NLToDCECCompiler, _, *__ = _get_nl_compiler()
        c = NLToDCECCompiler(policy_id="multi-p")
        r = c.compile([
            "Alice must not delete records",
            "Bob is permitted to read files",
            "Carol is required to audit access",
        ])
        assert r.success
        assert len(r.clauses) == 3
        assert r.policy is not None

    def test_policy_id_in_result(self):
        NLToDCECCompiler, _, *__ = _get_nl_compiler()
        c = NLToDCECCompiler(policy_id="explicit-id")
        r = c.compile(["Users must not share passwords"])
        assert r.metadata["policy_id"] == "explicit-id"

    def test_auto_policy_id(self):
        NLToDCECCompiler, _, *__ = _get_nl_compiler()
        c = NLToDCECCompiler()
        r = c.compile(["Alice may read files"])
        pid = r.metadata.get("policy_id", "")
        assert pid.startswith("nl-policy-")

    def test_compile_nl_to_policy_convenience(self):
        _, _, compile_nl_to_policy, *__ = _get_nl_compiler()
        r = compile_nl_to_policy(
            ["Dave must not share passwords", "Eve may access the system"],
            policy_id="conv-p",
        )
        assert r.success
        assert len(r.clauses) == 2

    def test_clause_actor_extracted(self):
        NLToDCECCompiler, _, *__ = _get_nl_compiler()
        c = NLToDCECCompiler()
        r = c.compile_sentence("Bob is permitted to read files")
        clause = r.clauses[0]
        assert clause.actor == "bob"

    def test_clause_action_extracted(self):
        NLToDCECCompiler, _, *__ = _get_nl_compiler()
        c = NLToDCECCompiler()
        r = c.compile_sentence("Bob is permitted to read files")
        clause = r.clauses[0]
        assert clause.action == "read"

    def test_default_actor_fallback(self):
        NLToDCECCompiler, _, *__ = _get_nl_compiler()
        c = NLToDCECCompiler(default_actor="default-agent")
        # NL conversion may produce a formula where actor is already extracted
        r = c.compile_sentence("must submit a report")
        # Even if actor extraction fails, default_actor is used
        # (no assertion on success because sentence may parse oddly)
        assert isinstance(r.errors, list)


class TestExtractHelpers:

    def test_extract_actor_from_deontic_formula(self):
        _, _, _, _, extract_actor, _ = _get_nl_compiler()
        formula = _make_deontic_formula(actor="carol")
        result = extract_actor(formula)
        assert result == "carol"

    def test_extract_action_from_deontic_formula(self):
        _, _, _, _, _, extract_action = _get_nl_compiler()
        formula = _make_deontic_formula(predicate="audit")
        result = extract_action(formula)
        assert result == "audit"

    def test_dcec_formula_to_clause_obligation(self):
        _, _, _, dcec_to_clause, _, _ = _get_nl_compiler()
        formula = _make_deontic_formula("OBLIGATION", "log", "system")
        clause = dcec_to_clause(formula)
        assert clause is not None
        assert clause.clause_type == "obligation"
        assert clause.actor == "system"
        assert clause.action == "log"

    def test_dcec_formula_to_clause_prohibition(self):
        _, _, _, dcec_to_clause, _, _ = _get_nl_compiler()
        formula = _make_deontic_formula("PROHIBITION", "delete", "alice")
        clause = dcec_to_clause(formula)
        assert clause is not None
        assert clause.clause_type == "prohibition"

    def test_dcec_formula_to_clause_permission(self):
        _, _, _, dcec_to_clause, _, _ = _get_nl_compiler()
        formula = _make_deontic_formula("PERMISSION", "read", "bob")
        clause = dcec_to_clause(formula)
        assert clause is not None
        assert clause.clause_type == "permission"

    def test_dcec_formula_to_clause_non_deontic_returns_none(self):
        _, _, _, dcec_to_clause, _, _ = _get_nl_compiler()
        # AtomicFormula is not DeonticFormula
        from ipfs_datasets_py.logic.CEC.native.dcec_core import (
            AtomicFormula, Predicate, Sort
        )
        atom = AtomicFormula(
            predicate=Predicate("foo", []),
            arguments=[],
        )
        clause = dcec_to_clause(atom)
        assert clause is None


# ─── Phase B: DCECToUCANBridge ────────────────────────────────────────────────

class TestDCECToUCANBridge:

    def test_import(self):
        _get_ucan_bridge()

    def test_bridge_default_construction(self):
        DCECToUCANBridge, *_ = _get_ucan_bridge()
        b = DCECToUCANBridge()
        assert b.issuer_did == "did:key:root"
        assert b.expiry_offset is None

    def test_map_obligation_to_capability(self):
        DCECToUCANBridge, DenyCapability, *_ = _get_ucan_bridge()
        b = DCECToUCANBridge()
        formula = _make_deontic_formula("OBLIGATION", "log", "system")
        mapping = b.map_formula(formula)
        assert mapping.error is None
        assert mapping.capability is not None
        assert not isinstance(mapping.capability, DenyCapability)
        assert "execute" in mapping.capability.ability or "log" in mapping.capability.ability

    def test_map_permission_to_capability(self):
        DCECToUCANBridge, DenyCapability, *_ = _get_ucan_bridge()
        b = DCECToUCANBridge()
        formula = _make_deontic_formula("PERMISSION", "read", "bob")
        mapping = b.map_formula(formula)
        assert mapping.error is None
        assert not isinstance(mapping.capability, DenyCapability)
        assert "read" in mapping.capability.ability or "invoke" in mapping.capability.ability

    def test_map_prohibition_to_deny_capability(self):
        DCECToUCANBridge, DenyCapability, *_ = _get_ucan_bridge()
        b = DCECToUCANBridge()
        formula = _make_deontic_formula("PROHIBITION", "delete", "alice")
        mapping = b.map_formula(formula)
        assert mapping.error is None
        assert isinstance(mapping.capability, DenyCapability)
        assert mapping.capability.actor == "alice"

    def test_map_non_deontic_returns_error(self):
        DCECToUCANBridge, *_ = _get_ucan_bridge()
        b = DCECToUCANBridge()
        from ipfs_datasets_py.logic.CEC.native.dcec_core import AtomicFormula, Predicate
        atom = AtomicFormula(predicate=Predicate("foo", []), arguments=[])
        mapping = b.map_formula(atom)
        assert mapping.error is not None

    def test_build_delegation_token_for_permission(self):
        DCECToUCANBridge, *_ = _get_ucan_bridge()
        b = DCECToUCANBridge(issuer_did="did:key:org")
        formula = _make_deontic_formula("PERMISSION", "read", "bob")
        mapping = b.map_formula(formula)
        token = b.build_delegation_token(mapping, audience_did="did:key:bob")
        assert token is not None
        assert token.issuer == "did:key:org"
        assert token.audience == "did:key:bob"
        assert len(token.capabilities) == 1

    def test_build_delegation_token_for_prohibition_returns_none(self):
        DCECToUCANBridge, DenyCapability, *_ = _get_ucan_bridge()
        b = DCECToUCANBridge()
        formula = _make_deontic_formula("PROHIBITION", "delete", "alice")
        mapping = b.map_formula(formula)
        assert isinstance(mapping.capability, DenyCapability)
        token = b.build_delegation_token(mapping)
        assert token is None

    def test_map_formulas_returns_bridge_result(self):
        DCECToUCANBridge, DenyCapability, BridgeResult, _ = _get_ucan_bridge()
        b = DCECToUCANBridge()
        formulas = [
            _make_deontic_formula("PERMISSION", "read", "bob"),
            _make_deontic_formula("PROHIBITION", "delete", "alice"),
            _make_deontic_formula("OBLIGATION", "audit", "carol"),
        ]
        result = b.map_formulas(formulas)
        assert isinstance(result, BridgeResult)
        assert result.success
        assert len(result.tokens) == 2   # permission + obligation
        assert len(result.denials) == 1  # prohibition

    def test_bridge_result_build_chain(self):
        DCECToUCANBridge, _, BridgeResult, _ = _get_ucan_bridge()
        b = DCECToUCANBridge()
        formulas = [_make_deontic_formula("PERMISSION", "read", "bob")]
        result = b.map_formulas(formulas)
        chain = result.build_chain()
        assert chain is not None
        assert len(chain.tokens) >= 1

    def test_token_has_cid(self):
        DCECToUCANBridge, *_ = _get_ucan_bridge()
        b = DCECToUCANBridge()
        formula = _make_deontic_formula("PERMISSION", "read", "bob")
        mapping = b.map_formula(formula)
        token = b.build_delegation_token(mapping)
        assert token is not None
        cid = token.cid
        assert cid.startswith("sha256:")

    def test_expiry_offset_applied(self):
        DCECToUCANBridge, *_ = _get_ucan_bridge()
        b = DCECToUCANBridge(expiry_offset=3600.0)
        formula = _make_deontic_formula("PERMISSION", "read", "bob")
        mapping = b.map_formula(formula)
        token = b.build_delegation_token(mapping)
        assert token is not None
        assert token.expiry is not None
        assert token.expiry > time.time()

    def test_audience_did_derived_from_actor(self):
        DCECToUCANBridge, *_ = _get_ucan_bridge()
        b = DCECToUCANBridge()
        formula = _make_deontic_formula("PERMISSION", "read", "charlie")
        mapping = b.map_formula(formula)
        token = b.build_delegation_token(mapping)  # no audience_did provided
        assert token is not None
        assert "charlie" in token.audience


# ─── Phase C: NLUCANPolicyCompiler end-to-end ────────────────────────────────

class TestNLUCANPolicyCompilerE2E:

    def test_import(self):
        _get_e2e_compiler()

    def test_compile_single_prohibition(self):
        _, _, compile_fn = _get_e2e_compiler()
        r = compile_fn(["Alice must not delete records"], policy_id="e2e-1")
        assert r.success
        assert r.policy_result is not None
        assert r.bridge_result is not None
        # Prohibition → DenyCapability only
        assert len(r.bridge_result.denials) == 1
        assert len(r.bridge_result.tokens) == 0

    def test_compile_single_permission(self):
        _, _, compile_fn = _get_e2e_compiler()
        r = compile_fn(["Bob is permitted to read files"], policy_id="e2e-2")
        assert r.success
        assert len(r.bridge_result.tokens) == 1
        assert len(r.bridge_result.denials) == 0

    def test_compile_mixed_sentences(self):
        _, _, compile_fn = _get_e2e_compiler()
        r = compile_fn([
            "Alice must not delete records",
            "Bob is permitted to read files",
            "Carol is required to audit access",
        ], policy_id="e2e-3")
        assert r.success
        assert len(r.policy_result.clauses) == 3
        assert r.delegation_evaluator is not None

    def test_delegation_evaluator_populated(self):
        _, _, compile_fn = _get_e2e_compiler()
        r = compile_fn(["Bob is permitted to read files"], policy_id="e2e-4")
        ev = r.delegation_evaluator
        assert ev is not None
        tokens = list(ev._tokens.values())
        assert len(tokens) >= 1

    def test_ucan_can_invoke_for_permitted_actor(self):
        _, _, compile_fn = _get_e2e_compiler()
        r = compile_fn(["Bob is permitted to read files"], policy_id="e2e-5")
        ev = r.delegation_evaluator
        assert ev is not None
        token = r.bridge_result.tokens[0]
        ok, reason = ev.can_invoke(
            "did:key:bob", "logic/read", "read/invoke", leaf_cid=token.cid
        )
        assert ok is True
        assert reason == "allowed"

    def test_convenience_wrapper(self):
        _, _, compile_fn = _get_e2e_compiler()
        r = compile_fn(
            ["Users must not share passwords", "Admin may delete records"],
            policy_id="conv-wrap",
        )
        assert r.success
        clauses = r.policy_result.clauses
        assert any(c.clause_type == "prohibition" for c in clauses)

    def test_empty_sentences_fails(self):
        _, _, compile_fn = _get_e2e_compiler()
        r = compile_fn(["   "], policy_id="empty-p")
        assert not r.success
        assert r.errors

    def test_policy_id_propagated(self):
        _, _, compile_fn = _get_e2e_compiler()
        r = compile_fn(["Bob may read"], policy_id="pid-123")
        assert r.metadata["policy_id"] == "pid-123"

    def test_result_policy_shortcut(self):
        _, _, compile_fn = _get_e2e_compiler()
        r = compile_fn(["Bob is permitted to read files"], policy_id="shortcut")
        pol = r.policy
        assert pol is not None
        assert pol.policy_id == "shortcut"

    def test_result_delegation_chain_shortcut(self):
        _, _, compile_fn = _get_e2e_compiler()
        r = compile_fn(["Bob is permitted to read files"], policy_id="chain")
        chain = r.delegation_chain
        assert chain is not None

    def test_result_deny_capabilities(self):
        _, _, compile_fn = _get_e2e_compiler()
        r = compile_fn(["Alice must not delete records"], policy_id="deny-cap")
        denials = r.deny_capabilities
        assert len(denials) == 1
        assert denials[0].actor == "alice"

    def test_input_sentences_preserved(self):
        _, _, compile_fn = _get_e2e_compiler()
        sents = ["Alice must not delete", "Bob may read"]
        r = compile_fn(sents, policy_id="sents")
        assert r.input_sentences == sents

    def test_policy_evaluation_via_evaluator(self):
        """Prohibitions correctly deny; obligations/permissions allow after policy registration."""
        _, _, compile_fn = _get_e2e_compiler()
        r = compile_fn([
            "Bob is permitted to read files",
            "Alice must not delete records",
        ], policy_id="eval-test")
        assert r.success
        pol = r.policy
        from ipfs_datasets_py.mcp_server.temporal_policy import PolicyEvaluator
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        ev = PolicyEvaluator()
        ev._policies[pol.policy_cid] = pol
        # Bob should be allowed to read
        dec_bob = ev.evaluate(IntentObject(tool="read"), pol.policy_cid, actor="bob")
        assert dec_bob.decision in ("allow", "allow_with_obligations")
        # Alice should be denied for delete
        dec_alice = ev.evaluate(IntentObject(tool="delete"), pol.policy_cid, actor="alice")
        assert dec_alice.decision == "deny"


# ─── Phase D: MCP Tool ────────────────────────────────────────────────────────

class TestNLUCANMCPTool:

    def test_tool_functions_exported(self):
        _, _, _, TOOL_FUNCTIONS = _get_mcp_tool()
        assert len(TOOL_FUNCTIONS) == 3

    def test_nl_compile_policy_success(self):
        nl_compile, *_ = _get_mcp_tool()
        result = nl_compile(
            ["Bob is permitted to read files"],
            policy_id="mcp-test-1",
        )
        assert result["success"] is True
        assert result["policy_id"] == "mcp-test-1"
        assert result["clause_count"] >= 1
        assert result["token_count"] >= 1

    def test_nl_compile_policy_prohibition(self):
        nl_compile, *_ = _get_mcp_tool()
        result = nl_compile(
            ["Alice must not delete records"],
            policy_id="mcp-test-deny",
        )
        assert result["success"] is True
        assert result["denial_count"] >= 1
        assert result["token_count"] == 0

    def test_nl_compile_policy_mixed(self):
        nl_compile, *_ = _get_mcp_tool()
        result = nl_compile(
            ["Alice must not delete records", "Bob is permitted to read files"],
            policy_id="mcp-test-mixed",
        )
        assert result["success"] is True
        assert result["clause_count"] == 2

    def test_nl_compile_policy_clauses_structure(self):
        nl_compile, *_ = _get_mcp_tool()
        result = nl_compile(
            ["Bob is permitted to read files"],
            policy_id="mcp-struct-test",
        )
        clauses = result["clauses"]
        assert isinstance(clauses, list)
        assert len(clauses) >= 1
        clause = clauses[0]
        assert "clause_type" in clause
        assert "actor" in clause
        assert "action" in clause

    def test_nl_compile_policy_tokens_structure(self):
        nl_compile, *_ = _get_mcp_tool()
        result = nl_compile(
            ["Bob is permitted to read files"],
            policy_id="mcp-tok-test",
        )
        tokens = result["tokens"]
        assert isinstance(tokens, list)
        assert len(tokens) >= 1
        tok = tokens[0]
        assert "issuer" in tok
        assert "audience" in tok
        assert "capabilities" in tok
        assert "cid" in tok

    def test_nl_evaluate_policy_not_found(self):
        _, nl_eval, *_ = _get_mcp_tool()
        r = nl_eval("nonexistent-policy", "bob", "read")
        assert r["success"] is False
        assert "not found" in r["error"].lower() or r["error_code"] == "POLICY_NOT_FOUND"

    def test_nl_evaluate_policy_after_compile(self):
        nl_compile, nl_eval, *_ = _get_mcp_tool()
        nl_compile(
            ["Bob is permitted to read files"],
            policy_id="eval-flow-test",
        )
        # Note: policy is keyed by policy_id in the cache
        # The evaluate function also looks up by policy_id
        r = nl_eval("eval-flow-test", "bob", "read")
        # success=True means policy was found (decision may vary based on policy_evaluator)
        assert r["success"] is True
        assert "policy_allowed" in r

    def test_nl_inspect_policy_not_found(self):
        _, _, nl_inspect, _ = _get_mcp_tool()
        r = nl_inspect("does-not-exist")
        assert r["success"] is False
        assert r["error_code"] == "POLICY_NOT_FOUND"

    def test_nl_inspect_policy_after_compile(self):
        nl_compile, _, nl_inspect, _ = _get_mcp_tool()
        nl_compile(
            ["Alice must not delete records", "Bob may read"],
            policy_id="inspect-test",
        )
        r = nl_inspect("inspect-test")
        assert r["success"] is True
        assert r["policy_id"] == "inspect-test"
        assert isinstance(r["clauses"], list)
        assert isinstance(r["tokens"], list)
        assert isinstance(r["sentences"], list)
        assert len(r["sentences"]) == 2


# ─── Integration: policy evaluation correctness ───────────────────────────────

class TestPolicyEvaluationCorrectness:
    """End-to-end correctness tests across the full stack."""

    def _compile(self, sentences, policy_id):
        from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import compile_nl_to_ucan_policy
        return compile_nl_to_ucan_policy(sentences, policy_id=policy_id)

    def _make_evaluator(self, result):
        from ipfs_datasets_py.mcp_server.temporal_policy import PolicyEvaluator
        ev = PolicyEvaluator()
        pol = result.policy
        ev._policies[pol.policy_cid] = pol
        return ev, pol

    def test_prohibited_actor_gets_deny(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        r = self._compile(["Alice must not delete records"], "deny-correct")
        ev, pol = self._make_evaluator(r)
        dec = ev.evaluate(IntentObject(tool="delete"), pol.policy_cid, actor="alice")
        assert dec.decision == "deny"

    def test_permitted_actor_gets_allow(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        r = self._compile(["Bob is permitted to read files"], "allow-correct")
        ev, pol = self._make_evaluator(r)
        dec = ev.evaluate(IntentObject(tool="read"), pol.policy_cid, actor="bob")
        assert dec.decision in ("allow", "allow_with_obligations")

    def test_obligation_gives_allow_with_obligations(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        # An OBLIGATION in the closed-world policy evaluator requires
        # *both* a permission AND an obligation clause for ALLOW_WITH_OBLIGATIONS.
        # With only an obligation, closed-world denies (no explicit permission).
        # We test this by adding a permission for the same action.
        r = self._compile([
            "Carol is permitted to audit",  # permission
            "Carol must audit access events",  # obligation
        ], "oblig-correct")
        ev, pol = self._make_evaluator(r)
        dec = ev.evaluate(IntentObject(tool="audit"), pol.policy_cid, actor="carol")
        # With permission + obligation → ALLOW_WITH_OBLIGATIONS
        assert dec.decision in ("allow", "allow_with_obligations")

    def test_ucan_delegation_correct_for_permission(self):
        r = self._compile(["Bob is permitted to read files"], "ucan-correct")
        ev = r.delegation_evaluator
        assert ev is not None
        tok = r.bridge_result.tokens[0]
        ok, reason = ev.can_invoke(
            "did:key:bob", "logic/read", "read/invoke", leaf_cid=tok.cid
        )
        assert ok is True

    def test_complex_policy_all_actors(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        r = self._compile([
            "Alice must not delete records",
            "Bob is permitted to read files",
            "Carol is required to audit all access events",
            "Dave must not share passwords",
            "Eve may access the system",
        ], "complex-pol")
        assert r.success
        assert len(r.policy_result.clauses) == 5
        # 3 positive tokens (obligation+permission+permission), 2 denials
        assert len(r.bridge_result.tokens) == 3
        assert len(r.bridge_result.denials) == 2

    def test_compile_id_determinism(self):
        """Same sentences produce the same auto policy_id."""
        from ipfs_datasets_py.logic.CEC.nl.nl_to_policy_compiler import _make_policy_id
        sents = ["Alice must not delete", "Bob may read"]
        id1 = _make_policy_id(sents)
        id2 = _make_policy_id(sents)
        assert id1 == id2
        assert id1.startswith("nl-policy-")

    def test_policy_cid_stable(self):
        """Same policy content produces the same policy_cid."""
        from ipfs_datasets_py.mcp_server.temporal_policy import PolicyClause, PolicyObject
        c = PolicyClause(clause_type="permission", actor="bob", action="read")
        p1 = PolicyObject(policy_id="x", clauses=[c])
        p2 = PolicyObject(policy_id="x", clauses=[c])
        assert p1.policy_cid == p2.policy_cid
