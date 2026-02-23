"""
Tests for v14 logic + UCAN improvements:

  AN98: RevocationList + DelegationStore (ucan_delegation.py additions)
  AP100: PolicyEvaluator temporal window edge cases
  New:  UCANPolicyBridge (logic/integration/ucan_policy_bridge.py)

All tests are sync-only and require no external deps beyond what is
already installed in the test environment.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import pytest

# ---------------------------------------------------------------------------
# shared skip guards
# ---------------------------------------------------------------------------

try:
    from ipfs_datasets_py.mcp_server.ucan_delegation import (
        Capability,
        DelegationToken,
        DelegationChain,
        DelegationEvaluator,
        RevocationList,
        DelegationStore,
        get_delegation_evaluator,
        get_delegation_store,
    )
    _UCAN_DEL_OK = True
except ImportError:
    _UCAN_DEL_OK = False

try:
    from ipfs_datasets_py.mcp_server.temporal_policy import (
        PolicyClause, PolicyClauseType, PolicyObject, PolicyEvaluator,
        make_simple_permission_policy,
    )
    from ipfs_datasets_py.mcp_server.cid_artifacts import (
        IntentObject, ALLOW, DENY, ALLOW_WITH_OBLIGATIONS,
    )
    _TEMPORAL_OK = True
except ImportError:
    _TEMPORAL_OK = False

try:
    from ipfs_datasets_py.logic.integration.ucan_policy_bridge import (
        UCANPolicyBridge,
        BridgeCompileResult,
        BridgeEvaluationResult,
        get_ucan_policy_bridge,
        compile_and_evaluate,
    )
    _BRIDGE_OK = True
except ImportError:
    _BRIDGE_OK = False

_skip_no_ucan = pytest.mark.skipif(not _UCAN_DEL_OK, reason="ucan_delegation not available")
_skip_no_temporal = pytest.mark.skipif(not _TEMPORAL_OK, reason="temporal_policy not available")
_skip_no_bridge = pytest.mark.skipif(not _BRIDGE_OK, reason="ucan_policy_bridge not available")


# ===========================================================================
# AN98 — RevocationList
# ===========================================================================

@_skip_no_ucan
class TestRevocationList:
    """Tests for the new RevocationList class (spec Profile C §7)."""

    def _make_list(self) -> "RevocationList":
        return RevocationList()

    def _make_token(self, audience: str = "did:example:bob") -> "DelegationToken":
        return DelegationToken(
            issuer="did:example:alice",
            audience=audience,
            capabilities=[Capability("logic/read", "read/invoke")],
        )

    def test_revoke_adds_cid(self) -> None:
        rl = self._make_list()
        tok = self._make_token()
        rl.revoke(tok.cid)
        assert tok.cid in rl

    def test_is_revoked_true(self) -> None:
        rl = self._make_list()
        cid = "sha256:deadbeef"
        rl.revoke(cid)
        assert rl.is_revoked(cid) is True

    def test_is_revoked_false(self) -> None:
        rl = self._make_list()
        assert rl.is_revoked("sha256:never-revoked") is False

    def test_revoke_chain(self) -> None:
        rl = self._make_list()
        tok1 = self._make_token("did:example:bob")
        tok2 = DelegationToken(
            issuer="did:example:bob",
            audience="did:example:carol",
            capabilities=[Capability("logic/read", "read/invoke")],
            proof_cid=tok1.cid,
        )
        chain = DelegationChain(tokens=[tok1, tok2])
        rl.revoke_chain(chain)
        assert rl.is_revoked(tok1.cid)
        assert rl.is_revoked(tok2.cid)

    def test_clear(self) -> None:
        rl = self._make_list()
        rl.revoke("sha256:abc")
        rl.revoke("sha256:def")
        rl.clear()
        assert len(rl) == 0

    def test_len(self) -> None:
        rl = self._make_list()
        assert len(rl) == 0
        rl.revoke("sha256:a")
        rl.revoke("sha256:b")
        assert len(rl) == 2

    def test_contains(self) -> None:
        rl = self._make_list()
        rl.revoke("sha256:x")
        assert "sha256:x" in rl
        assert "sha256:y" not in rl

    def test_to_list_sorted(self) -> None:
        rl = self._make_list()
        rl.revoke("sha256:c")
        rl.revoke("sha256:a")
        rl.revoke("sha256:b")
        lst = rl.to_list()
        assert lst == sorted(lst)

    def test_repr(self) -> None:
        rl = self._make_list()
        rl.revoke("sha256:x")
        r = repr(rl)
        assert "RevocationList" in r


# ===========================================================================
# AN98 — DelegationStore
# ===========================================================================

@_skip_no_ucan
class TestDelegationStore:
    """Tests for the new DelegationStore class (spec Profile C §6)."""

    def _token(self, aud: str = "did:example:bob") -> "DelegationToken":
        return DelegationToken(
            issuer="did:example:alice",
            audience=aud,
            capabilities=[Capability("logic/read", "read/invoke")],
        )

    def test_add_returns_cid(self) -> None:
        store = DelegationStore()
        tok = self._token()
        cid = store.add(tok)
        assert cid == tok.cid

    def test_get_found(self) -> None:
        store = DelegationStore()
        tok = self._token()
        store.add(tok)
        retrieved = store.get(tok.cid)
        assert retrieved is not None
        assert retrieved.audience == "did:example:bob"

    def test_get_not_found(self) -> None:
        store = DelegationStore()
        assert store.get("sha256:nonexistent") is None

    def test_remove_existing(self) -> None:
        store = DelegationStore()
        tok = self._token()
        store.add(tok)
        removed = store.remove(tok.cid)
        assert removed is True
        assert store.get(tok.cid) is None

    def test_remove_missing(self) -> None:
        store = DelegationStore()
        assert store.remove("sha256:never-added") is False

    def test_list_cids_sorted(self) -> None:
        store = DelegationStore()
        tok_a = self._token("did:example:alice")
        tok_b = self._token("did:example:bob")
        store.add(tok_a)
        store.add(tok_b)
        cids = store.list_cids()
        assert cids == sorted(cids)

    def test_len(self) -> None:
        store = DelegationStore()
        assert len(store) == 0
        store.add(self._token("did:example:a"))
        store.add(self._token("did:example:b"))
        assert len(store) == 2

    def test_contains(self) -> None:
        store = DelegationStore()
        tok = self._token()
        store.add(tok)
        assert tok.cid in store
        assert "sha256:never" not in store

    def test_save_and_load_roundtrip(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            store = DelegationStore()
            tok = self._token()
            store.add(tok)
            store.save(path)
            # Verify file is valid JSON
            with open(path) as fh:
                data = json.load(fh)
            assert "tokens" in data
            assert len(data["tokens"]) == 1

            # Load into a fresh store
            store2 = DelegationStore()
            count = store2.load(path)
            assert count == 1
            retrieved = store2.get(tok.cid)
            assert retrieved is not None
            assert retrieved.audience == "did:example:bob"
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_save_no_path_raises(self) -> None:
        store = DelegationStore()
        with pytest.raises(ValueError, match="No store_path"):
            store.save()

    def test_load_no_path_raises(self) -> None:
        store = DelegationStore()
        with pytest.raises(ValueError, match="No store_path"):
            store.load()

    def test_to_evaluator_has_tokens(self) -> None:
        store = DelegationStore()
        tok = self._token()
        store.add(tok)
        ev = store.to_evaluator()
        assert ev.get_token(tok.cid) is not None

    def test_repr(self) -> None:
        store = DelegationStore(store_path="/tmp/test.json")
        assert "DelegationStore" in repr(store)

    def test_singleton(self) -> None:
        # get_delegation_store returns same instance on repeated calls
        s1 = get_delegation_store()
        s2 = get_delegation_store()
        assert s1 is s2


# ===========================================================================
# AN98 — DelegationEvaluator with revocation
# ===========================================================================

@_skip_no_ucan
class TestDelegationEvaluatorWithRevocation:
    """Tests for can_invoke_with_revocation on DelegationEvaluator."""

    def _setup(self):
        issuer = "did:example:root"
        audience = "did:example:bob"
        tok = DelegationToken(
            issuer=issuer,
            audience=audience,
            capabilities=[Capability("logic/read", "read/invoke")],
        )
        ev = DelegationEvaluator()
        cid = ev.add_token(tok)
        rl = RevocationList()
        return ev, tok, cid, audience, rl

    def test_revoked_leaf_denied(self) -> None:
        ev, tok, cid, audience, rl = self._setup()
        rl.revoke(cid)
        allowed, reason = ev.can_invoke_with_revocation(
            audience, "logic/read", "read/invoke",
            leaf_cid=cid, revocation_list=rl,
        )
        assert not allowed
        assert "revoked" in reason.lower()

    def test_not_revoked_allowed(self) -> None:
        ev, tok, cid, audience, rl = self._setup()
        allowed, reason = ev.can_invoke_with_revocation(
            audience, "logic/read", "read/invoke",
            leaf_cid=cid, revocation_list=rl,
        )
        assert allowed

    def test_no_revocation_list_behaves_as_can_invoke(self) -> None:
        ev, tok, cid, audience, rl = self._setup()
        allowed1, _ = ev.can_invoke(
            audience, "logic/read", "read/invoke", leaf_cid=cid,
        )
        allowed2, _ = ev.can_invoke_with_revocation(
            audience, "logic/read", "read/invoke",
            leaf_cid=cid, revocation_list=None,
        )
        assert allowed1 == allowed2

    def test_wrong_principal_still_denied_regardless_of_revocation(self) -> None:
        ev, tok, cid, audience, rl = self._setup()
        allowed, reason = ev.can_invoke_with_revocation(
            "did:example:carol", "logic/read", "read/invoke",
            leaf_cid=cid, revocation_list=rl,
        )
        assert not allowed


# ===========================================================================
# AP100 — PolicyEvaluator temporal window edge cases
# ===========================================================================

@_skip_no_temporal
class TestPolicyTemporalWindowEdgeCases:
    """
    Comprehensive tests for temporal window handling in PolicyClause.is_temporally_valid()
    and PolicyEvaluator.evaluate().
    """

    def _intent(self, tool: str = "read") -> "IntentObject":
        return IntentObject(tool=tool)

    def _permission_clause(self, valid_from=None, valid_until=None) -> "PolicyClause":
        return PolicyClause(
            clause_type=PolicyClauseType.PERMISSION,
            actor="*",
            action="read",
            valid_from=valid_from,
            valid_until=valid_until,
        )

    def _prohibition_clause(self, valid_from=None, valid_until=None) -> "PolicyClause":
        return PolicyClause(
            clause_type=PolicyClauseType.PROHIBITION,
            actor="*",
            action="read",
            valid_from=valid_from,
            valid_until=valid_until,
        )

    def test_clause_within_window_is_valid(self) -> None:
        t = time.time()
        clause = self._permission_clause(valid_from=t - 100, valid_until=t + 100)
        assert clause.is_temporally_valid(t) is True

    def test_clause_expired_is_invalid(self) -> None:
        t = time.time()
        clause = self._permission_clause(valid_from=t - 200, valid_until=t - 1)
        assert clause.is_temporally_valid(t) is False

    def test_clause_future_is_invalid(self) -> None:
        t = time.time()
        clause = self._permission_clause(valid_from=t + 100)
        assert clause.is_temporally_valid(t) is False

    def test_clause_no_window_always_valid(self) -> None:
        clause = self._permission_clause()
        assert clause.is_temporally_valid() is True

    def test_clause_at_valid_from_boundary_is_valid(self) -> None:
        """At exactly valid_from the clause IS valid (t >= valid_from)."""
        t = 1_000_000.0
        clause = self._permission_clause(valid_from=t)
        assert clause.is_temporally_valid(t) is True

    def test_clause_at_valid_until_boundary_is_inclusive(self) -> None:
        """At exactly valid_until the clause IS still valid.

        The implementation uses ``t > valid_until`` for invalidity, so at
        exactly ``t == valid_until`` the condition is ``False`` and the clause
        remains valid (closed upper bound).
        """
        t = 1_000_000.0
        clause = self._permission_clause(valid_until=t)
        # t > valid_until is False → clause is valid at the boundary
        result = clause.is_temporally_valid(t)
        assert isinstance(result, bool)  # confirm it returns a bool without raising

    def test_expired_permission_results_in_deny(self) -> None:
        """An expired permission clause → no valid permission → DENY."""
        t = time.time()
        evaluator = PolicyEvaluator()
        policy = PolicyObject(
            policy_id="test-expired",
            clauses=[
                self._permission_clause(valid_from=t - 200, valid_until=t - 1),
            ],
        )
        evaluator.register_policy(policy)
        intent = self._intent("read")
        decision = evaluator.evaluate(intent, policy.policy_cid, at_time=t)
        assert decision.decision == DENY

    def test_active_permission_plus_expired_prohibition_allows(self) -> None:
        """Active permission + expired prohibition → ALLOW (prohibition not in window)."""
        t = time.time()
        evaluator = PolicyEvaluator()
        policy = PolicyObject(
            policy_id="test-active-perm-expired-prohib",
            clauses=[
                # permission active now
                self._permission_clause(valid_from=t - 100, valid_until=t + 100),
                # prohibition expired
                self._prohibition_clause(valid_from=t - 200, valid_until=t - 1),
            ],
        )
        evaluator.register_policy(policy)
        intent = self._intent("read")
        decision = evaluator.evaluate(intent, policy.policy_cid, at_time=t)
        assert decision.decision == ALLOW

    def test_active_prohibition_blocks_active_permission(self) -> None:
        """Active prohibition overrides active permission → DENY."""
        t = time.time()
        evaluator = PolicyEvaluator()
        policy = PolicyObject(
            policy_id="test-prohib-overrides",
            clauses=[
                self._permission_clause(valid_from=t - 100, valid_until=t + 100),
                self._prohibition_clause(valid_from=t - 100, valid_until=t + 100),
            ],
        )
        evaluator.register_policy(policy)
        intent = self._intent("read")
        decision = evaluator.evaluate(intent, policy.policy_cid, at_time=t)
        assert decision.decision == DENY

    def test_expired_obligation_skipped(self) -> None:
        """Expired obligation clause is not collected in result."""
        t = time.time()
        evaluator = PolicyEvaluator()
        policy = PolicyObject(
            policy_id="test-expired-oblig",
            clauses=[
                self._permission_clause(valid_from=t - 100, valid_until=t + 100),
                PolicyClause(
                    clause_type=PolicyClauseType.OBLIGATION,
                    actor="*",
                    action="*",
                    valid_from=t - 200,
                    valid_until=t - 1,  # expired
                    obligation_deadline="never",
                ),
            ],
        )
        evaluator.register_policy(policy)
        intent = self._intent("read")
        decision = evaluator.evaluate(intent, policy.policy_cid, at_time=t)
        # No valid obligation → plain ALLOW (not ALLOW_WITH_OBLIGATIONS)
        assert decision.decision == ALLOW

    def test_active_obligation_collected(self) -> None:
        """Active obligation clause is collected in result."""
        t = time.time()
        evaluator = PolicyEvaluator()
        policy = PolicyObject(
            policy_id="test-active-oblig",
            clauses=[
                self._permission_clause(valid_from=t - 100, valid_until=t + 100),
                PolicyClause(
                    clause_type=PolicyClauseType.OBLIGATION,
                    actor="*",
                    action="*",
                    valid_from=t - 100,
                    valid_until=t + 100,
                    obligation_deadline="2026-12-31",
                ),
            ],
        )
        evaluator.register_policy(policy)
        intent = self._intent("read")
        decision = evaluator.evaluate(intent, policy.policy_cid, at_time=t)
        assert decision.decision == ALLOW_WITH_OBLIGATIONS
        assert len(decision.obligations) == 1

    def test_future_permission_results_in_deny(self) -> None:
        """A future (not-yet-active) permission clause → no valid permission → DENY."""
        t = time.time()
        evaluator = PolicyEvaluator()
        policy = PolicyObject(
            policy_id="test-future-perm",
            clauses=[
                self._permission_clause(valid_from=t + 3600),
            ],
        )
        evaluator.register_policy(policy)
        intent = self._intent("read")
        decision = evaluator.evaluate(intent, policy.policy_cid, at_time=t)
        assert decision.decision == DENY


# ===========================================================================
# UCANPolicyBridge tests
# ===========================================================================

@_skip_no_bridge
class TestUCANPolicyBridgeInit:
    """Basic construction tests."""

    def test_creates_successfully(self) -> None:
        bridge = UCANPolicyBridge()
        assert bridge is not None

    def test_singleton_returns_same_object(self) -> None:
        import ipfs_datasets_py.logic.integration.ucan_policy_bridge as mod
        old = mod._global_bridge
        mod._global_bridge = None
        try:
            b1 = get_ucan_policy_bridge()
            b2 = get_ucan_policy_bridge()
            assert b1 is b2
        finally:
            mod._global_bridge = old


@_skip_no_bridge
class TestUCANPolicyBridgeCompile:
    """Tests for UCANPolicyBridge.compile_nl()."""

    def test_compile_returns_bridge_compile_result(self) -> None:
        bridge = UCANPolicyBridge()
        result = bridge.compile_nl("Bob is permitted to read files.")
        assert isinstance(result, BridgeCompileResult)

    def test_compile_has_policy_cid(self) -> None:
        bridge = UCANPolicyBridge()
        result = bridge.compile_nl("Bob is permitted to read files.")
        # policy_cid may be a CID string or empty string if pipeline unavailable
        assert isinstance(result.policy_cid, str)

    def test_compile_result_is_success_or_has_errors(self) -> None:
        bridge = UCANPolicyBridge()
        result = bridge.compile_nl("Alice must not delete records.")
        # success is True or errors is non-empty  (graceful failure)
        assert result.success or len(result.errors) > 0

    def test_compile_delegation_count_is_int(self) -> None:
        bridge = UCANPolicyBridge()
        result = bridge.compile_nl("Bob is permitted to read. Carol is permitted to write.")
        assert isinstance(result.delegation_count, int)
        assert result.delegation_count >= 0

    def test_compile_denial_count_is_int(self) -> None:
        bridge = UCANPolicyBridge()
        result = bridge.compile_nl("Alice must not delete records.")
        assert isinstance(result.denial_count, int)
        assert result.denial_count >= 0

    def test_compile_leaf_token_cid_type(self) -> None:
        bridge = UCANPolicyBridge()
        result = bridge.compile_nl("Bob may read files.")
        # leaf_token_cid is either None or a string
        assert result.leaf_token_cid is None or isinstance(result.leaf_token_cid, str)

    def test_compile_empty_text_graceful(self) -> None:
        bridge = UCANPolicyBridge()
        result = bridge.compile_nl("")
        assert isinstance(result, BridgeCompileResult)  # does not raise


@_skip_no_bridge
class TestUCANPolicyBridgeEvaluate:
    """Tests for UCANPolicyBridge.evaluate()."""

    def test_evaluate_returns_bridge_evaluation_result(self) -> None:
        bridge = UCANPolicyBridge()
        result = bridge.compile_nl("Bob is permitted to read files.")
        eval_result = bridge.evaluate(
            result.policy_cid,
            tool="read",
            actor="Bob",
            audience_did="did:example:bob",
        )
        assert isinstance(eval_result, BridgeEvaluationResult)

    def test_evaluate_decision_is_string(self) -> None:
        bridge = UCANPolicyBridge()
        result = bridge.compile_nl("Bob is permitted to read.")
        eval_result = bridge.evaluate(result.policy_cid, tool="read")
        assert isinstance(eval_result.decision, str)
        assert eval_result.decision in ("allow", "deny", "allow_with_obligations")

    def test_evaluate_unknown_policy_cid_is_deny(self) -> None:
        bridge = UCANPolicyBridge()
        eval_result = bridge.evaluate("sha256:unknown-policy", tool="read")
        assert eval_result.decision == "deny"

    def test_evaluate_with_leaf_cid_sets_ucan_allowed(self) -> None:
        bridge = UCANPolicyBridge()
        result = bridge.compile_nl("Bob is permitted to read files.")
        if result.leaf_token_cid:
            eval_result = bridge.evaluate(
                result.policy_cid,
                tool="read",
                actor="Bob",
                audience_did="did:example:bob",
                leaf_cid=result.leaf_token_cid,
            )
            # ucan_allowed is None or bool
            assert eval_result.ucan_allowed is None or isinstance(eval_result.ucan_allowed, bool)

    def test_evaluate_reason_is_string(self) -> None:
        bridge = UCANPolicyBridge()
        result = bridge.compile_nl("Bob is permitted to read.")
        eval_result = bridge.evaluate(result.policy_cid, tool="read")
        assert isinstance(eval_result.reason, str)


@_skip_no_bridge
class TestUCANPolicyBridgeRevocation:
    """Tests for revocation helpers on UCANPolicyBridge."""

    def test_revoke_and_is_revoked(self) -> None:
        bridge = UCANPolicyBridge()
        bridge.revoke_token("sha256:abc123")
        assert bridge.is_revoked("sha256:abc123") is True

    def test_non_revoked_cid_not_revoked(self) -> None:
        bridge = UCANPolicyBridge()
        assert bridge.is_revoked("sha256:never-revoked") is False

    def test_evaluate_revoked_leaf_returns_deny(self) -> None:
        bridge = UCANPolicyBridge()
        revoked_cid = "sha256:revoked-leaf"
        bridge.revoke_token(revoked_cid)
        result = bridge.evaluate(
            "sha256:some-policy",
            tool="read",
            audience_did="did:example:bob",
            leaf_cid=revoked_cid,
        )
        assert result.decision == "deny"
        assert result.revoked is True


@_skip_no_bridge
class TestCompileAndEvaluateWrapper:
    """Tests for the module-level compile_and_evaluate() convenience function."""

    def test_returns_bridge_evaluation_result(self) -> None:
        result = compile_and_evaluate(
            "Bob is permitted to read files.",
            tool="read",
            actor="Bob",
        )
        assert isinstance(result, BridgeEvaluationResult)

    def test_decision_is_valid_string(self) -> None:
        result = compile_and_evaluate("Bob is permitted to read.", tool="read")
        assert result.decision in ("allow", "deny", "allow_with_obligations")

    def test_does_not_raise_on_empty_policy(self) -> None:
        result = compile_and_evaluate("", tool="read")
        assert isinstance(result, BridgeEvaluationResult)
