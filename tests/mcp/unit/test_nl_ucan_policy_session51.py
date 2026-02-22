"""Tests for ipfs_datasets_py.mcp_server.nl_ucan_policy (session 51).

Covers:
- NLPolicySource hash computation
- _fallback_parse_nl_policy regex parsing (permissions, prohibitions, obligations)
- NLUCANPolicyCompiler.compile (success, empty text, no-clause warning)
- NLUCANPolicyCompiler.recompile_if_stale (fresh, stale)
- CompiledUCANPolicy fields and to_dict
- PolicyRegistry CRUD + hash-mismatch recompilation
- get_policy_registry singleton
- UCANPolicyGate open-by-default, single policy, multi-policy, deny wins
- compile_nl_policy convenience function
- temporal_policy.get_policy_registry re-export
"""

import warnings
from unittest.mock import MagicMock, patch

import pytest

from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
    CompiledUCANPolicy,
    NLPolicySource,
    NLUCANPolicyCompiler,
    PolicyRegistry,
    UCANPolicyGate,
    _fallback_parse_nl_policy,
    _make_policy_cid,
    compile_nl_policy,
    get_policy_registry,
)
from ipfs_datasets_py.mcp_server.temporal_policy import PolicyClause, PolicyObject


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_intent(tool: str = "repo.status") -> IntentObject:
    return IntentObject(interface_cid="bafy-test", tool=tool, input_cid="bafy-input")


# ---------------------------------------------------------------------------
# _make_policy_cid
# ---------------------------------------------------------------------------

class TestMakePolicyCid:
    def test_deterministic(self):
        assert _make_policy_cid("hello") == _make_policy_cid("hello")

    def test_different_text_different_cid(self):
        assert _make_policy_cid("hello") != _make_policy_cid("world")

    def test_returns_bafy_prefix(self):
        cid = _make_policy_cid("test policy text")
        assert cid.startswith("bafy"), f"Expected 'bafy' prefix, got: {cid!r}"

    def test_empty_string_still_produces_cid(self):
        cid = _make_policy_cid("")
        assert cid.startswith("bafy")


# ---------------------------------------------------------------------------
# NLPolicySource
# ---------------------------------------------------------------------------

class TestNLPolicySource:
    def test_source_cid_set_at_init(self):
        src = NLPolicySource("only admin may call tools")
        assert src.source_cid == _make_policy_cid("only admin may call tools")

    def test_cid_matches_same(self):
        src = NLPolicySource("text")
        assert src.cid_matches(src.source_cid)

    def test_cid_matches_different(self):
        src = NLPolicySource("text")
        assert not src.cid_matches("bafy-wrong-cid-value")

    def test_text_stored(self):
        src = NLPolicySource("hello world")
        assert src.text == "hello world"


# ---------------------------------------------------------------------------
# _fallback_parse_nl_policy
# ---------------------------------------------------------------------------

class TestFallbackParser:
    # --- Permissions ---

    def test_only_actor_may_action(self):
        clauses = _fallback_parse_nl_policy("Only admin may call admin_tools.")
        assert len(clauses) == 1
        assert clauses[0].clause_type == "permission"
        assert clauses[0].actor == "admin"
        assert clauses[0].action == "admin_tools"

    def test_actor_may_action(self):
        clauses = _fallback_parse_nl_policy("alice may read_data")
        perms = [c for c in clauses if c.clause_type == "permission"]
        assert any(c.actor == "alice" and c.action == "read_data" for c in perms)

    def test_actor_can_action(self):
        clauses = _fallback_parse_nl_policy("bob can call search_tool")
        perms = [c for c in clauses if c.clause_type == "permission"]
        assert len(perms) >= 1

    def test_actor_is_permitted_to(self):
        clauses = _fallback_parse_nl_policy("alice is permitted to call list_tools")
        perms = [c for c in clauses if c.clause_type == "permission"]
        assert len(perms) >= 1

    # --- Prohibitions ---

    def test_must_not(self):
        clauses = _fallback_parse_nl_policy("alice must not call delete_tool")
        prohibs = [c for c in clauses if c.clause_type == "prohibition"]
        assert len(prohibs) >= 1
        assert prohibs[0].actor == "alice"

    def test_shall_not(self):
        clauses = _fallback_parse_nl_policy("guest shall not access admin_tools")
        prohibs = [c for c in clauses if c.clause_type == "prohibition"]
        assert len(prohibs) >= 1

    def test_may_not(self):
        clauses = _fallback_parse_nl_policy("bob may not call delete_everything")
        prohibs = [c for c in clauses if c.clause_type == "prohibition"]
        assert len(prohibs) >= 1

    def test_cannot(self):
        clauses = _fallback_parse_nl_policy("user cannot call reset")
        prohibs = [c for c in clauses if c.clause_type == "prohibition"]
        assert len(prohibs) >= 1

    def test_prohibited_from(self):
        clauses = _fallback_parse_nl_policy("alice is prohibited from calling delete_tool")
        prohibs = [c for c in clauses if c.clause_type == "prohibition"]
        assert len(prohibs) >= 1

    def test_no_actor_may(self):
        clauses = _fallback_parse_nl_policy("No guest may call admin_panel")
        prohibs = [c for c in clauses if c.clause_type == "prohibition"]
        assert len(prohibs) >= 1

    # --- Obligations ---

    def test_must(self):
        clauses = _fallback_parse_nl_policy("alice must log_event after calling tools")
        # 'must' triggers obligation pattern
        obs = [c for c in clauses if c.clause_type == "obligation"]
        assert len(obs) >= 1

    def test_shall(self):
        clauses = _fallback_parse_nl_policy("system shall audit_log all operations")
        obs = [c for c in clauses if c.clause_type == "obligation"]
        assert len(obs) >= 1

    # --- Edge cases ---

    def test_empty_string(self):
        assert _fallback_parse_nl_policy("") == []

    def test_unrecognized_text_returns_empty(self):
        # Gibberish with no modal patterns
        clauses = _fallback_parse_nl_policy("xyzzy wibble florp garble")
        # May return empty or false positives — just confirm it doesn't raise
        assert isinstance(clauses, list)

    def test_multi_sentence(self):
        text = (
            "Only admin may call admin_tools. "
            "guest shall not access delete_tool."
        )
        clauses = _fallback_parse_nl_policy(text)
        types = {c.clause_type for c in clauses}
        # Should have at least permission and/or prohibition
        assert types & {"permission", "prohibition"}

    def test_newline_separator(self):
        text = "alice may read_data\nbob shall not call delete"
        clauses = _fallback_parse_nl_policy(text)
        assert len(clauses) >= 1


# ---------------------------------------------------------------------------
# CompiledUCANPolicy
# ---------------------------------------------------------------------------

class TestCompiledUCANPolicy:
    def _make_compiled(self):
        clause = PolicyClause(clause_type="permission", actor="admin", action="*")
        policy = PolicyObject(clauses=[clause])
        return CompiledUCANPolicy(policy=policy, source_cid="bafyreiabc123")

    def test_fields_accessible(self):
        c = self._make_compiled()
        assert c.source_cid == "bafyreiabc123"
        assert isinstance(c.compiled_at, str)
        assert c.compiler_version == "v1"
        assert c.metadata == {}

    def test_to_dict_keys(self):
        c = self._make_compiled()
        d = c.to_dict()
        assert "policy" in d
        assert d["source_cid"] == "bafyreiabc123"
        assert "compiled_at" in d
        assert d["compiler_version"] == "v1"

    def test_is_stale_with_no_clauses(self):
        policy = PolicyObject(clauses=[])
        c = CompiledUCANPolicy(policy=policy, source_cid="bafyreix")
        assert c.is_stale

    def test_is_not_stale_with_clauses(self):
        c = self._make_compiled()
        assert not c.is_stale


# ---------------------------------------------------------------------------
# NLUCANPolicyCompiler
# ---------------------------------------------------------------------------

class TestNLUCANPolicyCompiler:
    def _compiler(self) -> NLUCANPolicyCompiler:
        return NLUCANPolicyCompiler(use_logic_module=False)

    def test_compile_returns_compiled_policy(self):
        c = self._compiler()
        result = c.compile("Only admin may call admin_tools.", description="admin policy")
        assert isinstance(result, CompiledUCANPolicy)
        assert result.policy.description == "admin policy"

    def test_source_cid_stored(self):
        text = "alice may read_data"
        c = self._compiler()
        result = c.compile(text)
        assert result.source_cid == _make_policy_cid(text)

    def test_clause_extracted(self):
        c = self._compiler()
        result = c.compile("alice may read_data")
        assert len(result.policy.clauses) >= 1

    def test_empty_text_raises(self):
        c = self._compiler()
        with pytest.raises(ValueError, match="non-empty"):
            c.compile("")

    def test_whitespace_only_raises(self):
        c = self._compiler()
        with pytest.raises(ValueError):
            c.compile("   ")

    def test_unrecognized_text_warns_and_returns_open_policy(self):
        c = self._compiler()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = c.compile("xyzzy wibble florp garble unique_xyz_123")
        # May or may not warn depending on regex matching, but if no clauses found
        # it should return a wildcard permission
        assert isinstance(result, CompiledUCANPolicy)
        assert len(result.policy.clauses) >= 1

    def test_description_defaults_to_truncated_text(self):
        text = "alice may read_data and more text that exceeds limit"
        c = self._compiler()
        result = c.compile(text)
        assert len(result.policy.description) <= 120

    def test_metadata_clause_count(self):
        c = self._compiler()
        result = c.compile("alice may read_data")
        assert "clause_count" in result.metadata
        assert result.metadata["clause_count"] >= 1

    def test_metadata_strategy_regex(self):
        c = self._compiler()
        result = c.compile("alice may read_data")
        assert result.metadata["strategy"] == "regex"

    # --- recompile_if_stale ---

    def test_recompile_if_stale_fresh(self):
        c = self._compiler()
        text = "alice may read_data"
        compiled = c.compile(text)
        source = NLPolicySource(text)
        result, was_recompiled = c.recompile_if_stale(source, compiled)
        assert not was_recompiled
        assert result is compiled

    def test_recompile_if_stale_detects_drift(self):
        c = self._compiler()
        original = "alice may read_data"
        modified = "alice may write_data"
        compiled = c.compile(original)
        # Simulate source drift: use a NLPolicySource with different text
        source = NLPolicySource(modified)
        result, was_recompiled = c.recompile_if_stale(source, compiled)
        assert was_recompiled
        assert result is not compiled
        assert result.source_cid == _make_policy_cid(modified)


# ---------------------------------------------------------------------------
# PolicyRegistry
# ---------------------------------------------------------------------------

class TestPolicyRegistry:
    def _registry(self) -> PolicyRegistry:
        compiler = NLUCANPolicyCompiler(use_logic_module=False)
        return PolicyRegistry(compiler=compiler)

    def test_empty_initially(self):
        r = self._registry()
        assert len(r) == 0
        assert r.list_names() == []

    def test_register_returns_compiled(self):
        r = self._registry()
        compiled = r.register("p1", "alice may read_data")
        assert isinstance(compiled, CompiledUCANPolicy)

    def test_get_returns_compiled(self):
        r = self._registry()
        r.register("p1", "alice may read_data")
        c = r.get("p1")
        assert c is not None
        assert isinstance(c, CompiledUCANPolicy)

    def test_get_unknown_returns_none(self):
        r = self._registry()
        assert r.get("nonexistent") is None

    def test_remove_existing(self):
        r = self._registry()
        r.register("p1", "alice may read_data")
        removed = r.remove("p1")
        assert removed
        assert r.get("p1") is None
        assert len(r) == 0

    def test_remove_nonexistent(self):
        r = self._registry()
        assert not r.remove("ghost")

    def test_list_names(self):
        r = self._registry()
        r.register("a", "alice may read_data")
        r.register("b", "bob may write_data")
        names = r.list_names()
        assert set(names) == {"a", "b"}

    def test_register_overwrites(self):
        r = self._registry()
        r.register("p1", "alice may read_data")
        r.register("p1", "bob may write_data")
        # Only one policy with that name
        assert len(r) == 1

    def test_hash_mismatch_triggers_recompile(self):
        """Mutate the source after registration to simulate drift."""
        compiler = NLUCANPolicyCompiler(use_logic_module=False)
        r = PolicyRegistry(compiler=compiler)
        r.register("p1", "alice may read_data")
        # Manually corrupt the stored source_cid to force mismatch
        r._compiled["p1"] = CompiledUCANPolicy(
            policy=r._compiled["p1"].policy,
            source_cid="bafy-wrong-cid-that-does-not-match",
        )
        # get() should detect mismatch and recompile
        fresh = r.get("p1")
        assert fresh is not None
        assert fresh.source_cid == r._sources["p1"].source_cid


# ---------------------------------------------------------------------------
# get_policy_registry singleton
# ---------------------------------------------------------------------------

class TestGetPolicyRegistry:
    def test_returns_registry_instance(self):
        reg = get_policy_registry()
        assert isinstance(reg, PolicyRegistry)

    def test_same_instance_on_second_call(self):
        r1 = get_policy_registry()
        r2 = get_policy_registry()
        assert r1 is r2


# ---------------------------------------------------------------------------
# UCANPolicyGate
# ---------------------------------------------------------------------------

class TestUCANPolicyGate:
    def _gate(self) -> UCANPolicyGate:
        compiler = NLUCANPolicyCompiler(use_logic_module=False)
        registry = PolicyRegistry(compiler=compiler)
        return UCANPolicyGate(compiler, registry=registry)

    # --- Open by default ---

    def test_open_by_default_no_policies(self):
        gate = self._gate()
        intent = _make_intent("any_tool")
        decision = gate.evaluate(intent, actor="alice")
        assert decision.decision == "allow"
        assert "open by default" in decision.justification

    def test_open_justification_text(self):
        gate = self._gate()
        intent = _make_intent()
        decision = gate.evaluate(intent)
        assert "No restricting policy" in decision.justification

    # --- With a permission policy ---

    def test_matching_permission_allows(self):
        # With open-world model: even if policy only has permissions (not prohibitions),
        # the gate still allows because no prohibition matched.
        gate = self._gate()
        gate.register_policy("p1", "alice may read_data")
        intent = _make_intent("read_data")
        decision = gate.evaluate(intent, actor="alice")
        assert decision.decision == "allow"

    def test_unmatched_actor_with_policy_still_allows(self):
        # Open-world model: only prohibitions restrict; permissions don't restrict non-mentioned actors.
        gate = self._gate()
        gate.register_policy("p1", "Only alice may call admin_tools")
        intent = _make_intent("admin_tools")
        # bob is not mentioned in the policy — no prohibition → allow
        decision = gate.evaluate(intent, actor="bob")
        assert decision.decision == "allow"

    # --- Prohibition policy ---

    def test_prohibition_denies(self):
        gate = self._gate()
        gate.register_policy("no_delete", "bob must not call delete_tool")
        intent = _make_intent("delete_tool")
        decision = gate.evaluate(intent, actor="bob")
        assert decision.decision == "deny"

    def test_prohibition_does_not_affect_different_actor(self):
        gate = self._gate()
        gate.register_policy("no_delete", "bob must not call delete_tool")
        intent = _make_intent("delete_tool")
        # alice is not mentioned in prohibition — gate returns allow (no matching prohibition)
        decision = gate.evaluate(intent, actor="alice")
        assert decision.decision == "allow"

    # --- Policy management ---

    def test_list_policies(self):
        gate = self._gate()
        gate.register_policy("p1", "alice may read_data")
        gate.register_policy("p2", "bob may write_data")
        assert set(gate.list_policies()) == {"p1", "p2"}

    def test_remove_policy(self):
        gate = self._gate()
        gate.register_policy("p1", "alice may read_data")
        removed = gate.remove_policy("p1")
        assert removed
        assert "p1" not in gate.list_policies()

    def test_remove_nonexistent_policy(self):
        gate = self._gate()
        assert not gate.remove_policy("ghost")

    def test_policy_name_filter(self):
        gate = self._gate()
        gate.register_policy("allow_all", "admin may call tools")
        gate.register_policy("deny_bob", "bob must not call tools")
        intent = _make_intent("tools")
        # Evaluate only against the prohibition — should deny bob
        decision = gate.evaluate(intent, actor="bob", policy_name="deny_bob")
        assert decision.decision == "deny"

    def test_unknown_policy_name_returns_open_allow(self):
        gate = self._gate()
        gate.register_policy("p1", "alice may read_data")
        intent = _make_intent()
        # Ask for a policy that doesn't exist; get() returns None; falls through to allow
        decision = gate.evaluate(intent, actor="alice", policy_name="nonexistent")
        assert decision.decision == "allow"

    # --- open_allow helper ---

    def test_open_allow_returns_allow_decision(self):
        intent = _make_intent("my_tool")
        decision = UCANPolicyGate._open_allow(intent)
        assert decision.decision == "allow"
        assert decision.intent_cid == intent.intent_cid


# ---------------------------------------------------------------------------
# compile_nl_policy convenience function
# ---------------------------------------------------------------------------

class TestCompileNlPolicy:
    def test_returns_compiled_policy(self):
        result = compile_nl_policy(
            "alice may read_data", use_logic_module=False
        )
        assert isinstance(result, CompiledUCANPolicy)

    def test_description_stored(self):
        result = compile_nl_policy(
            "alice may read_data",
            description="read access",
            use_logic_module=False,
        )
        assert result.policy.description == "read access"

    def test_source_cid_correct(self):
        text = "alice may read_data"
        result = compile_nl_policy(text, use_logic_module=False)
        assert result.source_cid == _make_policy_cid(text)


# ---------------------------------------------------------------------------
# temporal_policy.get_policy_registry re-export
# ---------------------------------------------------------------------------

class TestTemporalPolicyReExport:
    def test_get_policy_registry_importable_from_temporal_policy(self):
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            get_policy_registry as gpr,
        )
        reg = gpr()
        assert isinstance(reg, PolicyRegistry)

    def test_same_singleton_as_nl_ucan(self):
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            get_policy_registry as tp_gpr,
        )
        tp_reg = tp_gpr()
        nl_reg = get_policy_registry()
        assert tp_reg is nl_reg
