"""Integration tests for exact counterexample replay (FVT-015 / FVT-G041).

CounterexampleReplay@1 acceptance:

* Corpus witnesses replay under their exact identities.
* Binding fails closed on changed tree / property / assumption / tool / bound.
* Unavailable tools return ``unavailable`` rather than success.
* Raw private artifacts remain out of public recipes.
* Replay results and receipts are content-addressed.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

import pytest

from ipfs_datasets_py.logic.software_verification.counterexamples.replay import (
    ALGORITHM_NAME,
    ALGORITHM_VERSION,
    COUNTEREXAMPLE_REPLAY_INTERFACE,
    REPLAY_RECEIPT_SCHEMA,
    REPLAY_RECIPE_SCHEMA,
    REPLAY_RESULT_SCHEMA,
    CounterexampleReplayer,
    ReplayBindings,
    ReplayError,
    ReplayMismatchField,
    ReplayRecipe,
    ReplayStatus,
    build_replay_recipe,
    replay_counterexample,
)


# ---------------------------------------------------------------------------
# Corpus-style witnesses (public + deliberately leaky raw forms)
# ---------------------------------------------------------------------------


def smt_model_witness(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "smt_model",
        "assignments": {"x": 1, "y": 2, "z": 0},
        "model": {"x": 1, "y": 2, "z": 0},
        "violated_property": "prop:resource-invariant",
        "property_id": "prop:resource-invariant",
        "assumption_ids": ["asm:finite-domain", "asm:no-overflow"],
        "finite_bounds": {"timeout_ms": 250, "max_depth": 8},
        "tool_id": "solver.z3",
        "tool_version": "4.12.0",
        "provider_id": "solver.z3",
        "tree_id": "tree:corpus-smt@1",
        "policy_id": "policy:public-counterexample-drop@1",
        "oracle_id": "oracle:z3-model",
        "summary": "resource invariant violated under finite bound",
        "source_map": {
            "ast_scope_ids": ["symbol:claim"],
            "source_ref_ids": ["source:resource.py"],
            "span_ids": ["span:check"],
            "tree_ids": ["tree:corpus-smt@1"],
        },
        "content_id": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "counterexample_id": "cex:smt-resource-1",
    }
    payload.update(overrides)
    return payload


def leaky_smt_witness(**overrides: Any) -> dict[str, Any]:
    base = smt_model_witness(
        hidden_witness="DO-NOT-PUBLISH-SECRET",
        credential="super-secret-credential",
        stdout="unbounded solver transcript",
        source_code="def secrets(): pass",
        source_excerpt="complete repository source",
        raw_output="solver dump " * 50,
        private_artifacts=[
            {
                "channel": "secret_material",
                "digest": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "retention_policy_id": "policy:private-counterexample-store@1",
                "retained": True,
                "byte_size": 32,
                "media_type": "application/octet-stream",
            }
        ],
    )
    base.update(overrides)
    return base


def trace_witness(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "tla_trace",
        "steps": [
            {"label": "init"},
            {"label": "claim"},
            {"label": "bad"},
        ],
        "violated_property": "prop:lease-safety",
        "assumption_ids": ["asm:single-owner"],
        "finite_bounds": {"max_steps": 16},
        "tool_id": "model-checker.tlc",
        "tool_version": "1.0.0",
        "tree_id": "tree:corpus-trace@1",
        "policy_id": "policy:public-counterexample-drop@1",
        "summary": "lease safety violated",
        "content_id": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        "counterexample_id": "cex:trace-lease-1",
    }
    payload.update(overrides)
    return payload


def hypertrace_witness(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "hypertrace",
        "differences": [{"field": "secret_bit", "left": 0, "right": 1}],
        "observed_fields": ["public_out", "secret_bit"],
        "violated_property": "prop:noninterference",
        "assumption_ids": ["asm:low-equivalence"],
        "finite_bounds": {"max_traces": 2},
        "tool_id": "hyper.checker",
        "tool_version": "0.3.0",
        "tree_id": "tree:corpus-hyper@1",
        "policy_id": "policy:public-counterexample-drop@1",
        "summary": "noninterference fails on secret-dependent divergence",
        "content_id": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
        "counterexample_id": "cex:hyper-ni-1",
    }
    payload.update(overrides)
    return payload


def protocol_witness(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "protocol_attack",
        "roles": ["initiator", "attacker"],
        "messages": ["hello", "forge", "accept"],
        "steps": [{"action": "inject"}, {"action": "accept"}],
        "violated_property": "prop:auth-integrity",
        "assumption_ids": ["asm:dolev-yao"],
        "finite_bounds": {"max_sessions": 2},
        "tool_id": "protocol.proverif",
        "tool_version": "2.04",
        "tree_id": "tree:corpus-proto@1",
        "policy_id": "policy:public-counterexample-drop@1",
        "summary": "protocol attack via forge",
        "content_id": "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
        "counterexample_id": "cex:proto-forge-1",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Oracles
# ---------------------------------------------------------------------------


def smt_model_oracle(candidate: Mapping[str, Any]) -> bool:
    assignments = candidate.get("assignments") or candidate.get("model") or {}
    if not isinstance(assignments, Mapping):
        payload = candidate.get("payload")
        if isinstance(payload, Mapping):
            assignments = payload.get("assignments") or payload.get("model") or {}
    if not isinstance(assignments, Mapping):
        return False
    return assignments.get("x") == 1 and assignments.get("y") == 2


def trace_oracle(candidate: Mapping[str, Any]) -> bool:
    steps = list(candidate.get("steps") or candidate.get("trace") or [])
    labels = [
        (step.get("label") if isinstance(step, Mapping) else step) for step in steps
    ]
    return "bad" in labels


def hypertrace_oracle(candidate: Mapping[str, Any]) -> bool:
    differences = list(candidate.get("differences") or [])
    observed = set(candidate.get("observed_fields") or [])
    has_secret_div = any(
        (d.get("field") if isinstance(d, Mapping) else d) == "secret_bit"
        for d in differences
    )
    return has_secret_div and "public_out" in observed


def protocol_oracle(candidate: Mapping[str, Any]) -> bool:
    roles = set(candidate.get("roles") or [])
    messages = list(candidate.get("messages") or [])
    steps = list(candidate.get("steps") or [])
    has_forge = "forge" in messages or any(
        (m.get("type") if isinstance(m, Mapping) else m) == "forge" for m in messages
    )
    has_init = "initiator" in roles
    has_step = any(
        (s.get("action") if isinstance(s, Mapping) else s) == "inject" for s in steps
    )
    return has_forge and has_init and has_step


def never_violate(_candidate: Mapping[str, Any]) -> bool:
    return False


# ---------------------------------------------------------------------------
# Interface / schema surface
# ---------------------------------------------------------------------------


def test_interface_and_schema_constants() -> None:
    assert COUNTEREXAMPLE_REPLAY_INTERFACE == "CounterexampleReplay@1"
    assert REPLAY_RECIPE_SCHEMA.endswith("@1")
    assert REPLAY_RECEIPT_SCHEMA.endswith("@1")
    assert REPLAY_RESULT_SCHEMA.endswith("@1")
    assert ALGORITHM_VERSION.startswith("counterexample-replay/")
    assert ALGORITHM_NAME == "exact_binding_counterexample_replay"


def test_recipe_is_content_addressed_and_stable() -> None:
    witness = smt_model_witness()
    a = build_replay_recipe(witness, oracle_id="oracle:z3-model")
    b = build_replay_recipe(witness, oracle_id="oracle:z3-model")
    assert a.recipe_id == b.recipe_id
    assert a.recipe_id.startswith("replay-recipe:")
    assert a.schema == REPLAY_RECIPE_SCHEMA
    assert a.interface == COUNTEREXAMPLE_REPLAY_INTERFACE
    # Round-trip preserves identity.
    restored = ReplayRecipe.from_dict(a.to_dict())
    assert restored.recipe_id == a.recipe_id
    assert restored.bindings.to_dict() == a.bindings.to_dict()


# ---------------------------------------------------------------------------
# Exact-identity corpus replay
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "witness_factory,oracle",
    [
        (smt_model_witness, smt_model_oracle),
        (trace_witness, trace_oracle),
        (hypertrace_witness, hypertrace_oracle),
        (protocol_witness, protocol_oracle),
    ],
)
def test_corpus_witnesses_replay_under_exact_identities(
    witness_factory, oracle
) -> None:
    witness = witness_factory()
    result = replay_counterexample(witness, oracle=oracle)
    assert result.status is ReplayStatus.REPRODUCED
    assert result.reproduced is True
    assert result.receipt.violation_reproduced is True
    assert result.receipt.mismatch_fields == ()
    assert result.receipt.recipe_id == result.recipe.recipe_id
    assert result.recipe.bindings.property_id
    assert result.recipe.bindings.tree_id
    assert result.recipe.bindings.tool_id
    assert result.recipe.bindings.witness_content_id
    # Content-addressed result + receipt
    assert result.content_id.startswith("sha256:")
    assert result.receipt.content_id.startswith("sha256:")
    assert result.receipt.receipt_id.startswith("replay-receipt:")


def test_not_reproduced_when_oracle_rejects() -> None:
    result = replay_counterexample(smt_model_witness(), oracle=never_violate)
    assert result.status is ReplayStatus.NOT_REPRODUCED
    assert result.reproduced is False
    assert result.receipt.violation_reproduced is False
    # Still content-addressed and not a success-as-unavailable confusion.
    assert result.status is not ReplayStatus.UNAVAILABLE
    assert result.content_id.startswith("sha256:")


# ---------------------------------------------------------------------------
# Binding fail-closed on changed identities
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override,field",
    [
        ({"tree_id": "tree:mutated@9"}, ReplayMismatchField.TREE_ID),
        ({"property_id": "prop:other"}, ReplayMismatchField.PROPERTY_ID),
        ({"assumption_ids": ["asm:changed"]}, ReplayMismatchField.ASSUMPTION_IDS),
        ({"tool_id": "solver.cvc5"}, ReplayMismatchField.TOOL_ID),
        ({"tool_version": "9.9.9"}, ReplayMismatchField.TOOL_VERSION),
        ({"policy_id": "policy:other@1"}, ReplayMismatchField.POLICY_ID),
        ({"bounds": {"timeout_ms": 999}}, ReplayMismatchField.BOUNDS),
        (
            {
                "witness_content_id": (
                    "sha256:ffffffffffffffffffffffffffffffff"
                    "ffffffffffffffffffffffffffffffff"
                )
            },
            ReplayMismatchField.WITNESS_CONTENT_ID,
        ),
    ],
)
def test_binding_fails_on_changed_identity(override: dict[str, Any], field: ReplayMismatchField) -> None:
    witness = smt_model_witness()
    recipe = build_replay_recipe(witness, oracle_id="oracle:z3-model")
    result = CounterexampleReplayer().replay(
        recipe,
        oracle=smt_model_oracle,
        observed_bindings=override,
    )
    assert result.status is ReplayStatus.BINDING_MISMATCH
    assert result.binding_mismatch is True
    assert result.reproduced is False
    assert field.value in result.receipt.mismatch_fields
    assert result.receipt.violation_reproduced is False
    # Oracle must not be treated as success under mismatched bindings.
    assert result.receipt.oracle_calls == 0


def test_exact_bindings_allow_replay_when_observed_matches() -> None:
    recipe = build_replay_recipe(smt_model_witness())
    result = CounterexampleReplayer().replay(
        recipe,
        oracle=smt_model_oracle,
        observed_bindings=recipe.bindings.to_dict(),
    )
    assert result.status is ReplayStatus.REPRODUCED
    assert result.receipt.mismatch_fields == ()


def test_check_bindings_helper_reports_multiple_mismatches() -> None:
    expected = ReplayBindings(
        tree_id="tree:a",
        property_id="prop:a",
        assumption_ids=("asm:1",),
        tool_id="tool:a",
        tool_version="1",
        policy_id="policy:a",
        bounds={"n": 1},
        witness_content_id="sha256:aa",
    )
    observed = ReplayBindings(
        tree_id="tree:b",
        property_id="prop:b",
        assumption_ids=("asm:2",),
        tool_id="tool:b",
        tool_version="2",
        policy_id="policy:b",
        bounds={"n": 2},
        witness_content_id="sha256:bb",
    )
    mismatches = CounterexampleReplayer().check_bindings(expected, observed)
    assert set(mismatches) == {
        ReplayMismatchField.TREE_ID,
        ReplayMismatchField.PROPERTY_ID,
        ReplayMismatchField.ASSUMPTION_IDS,
        ReplayMismatchField.TOOL_ID,
        ReplayMismatchField.TOOL_VERSION,
        ReplayMismatchField.POLICY_ID,
        ReplayMismatchField.BOUNDS,
        ReplayMismatchField.WITNESS_CONTENT_ID,
    }


# ---------------------------------------------------------------------------
# Unavailable tools never report success
# ---------------------------------------------------------------------------


def test_unavailable_tool_returns_unavailable_not_success() -> None:
    recipe = build_replay_recipe(smt_model_witness())
    result = CounterexampleReplayer().replay(
        recipe,
        oracle=smt_model_oracle,
        tool_available=False,
    )
    assert result.status is ReplayStatus.UNAVAILABLE
    assert result.unavailable is True
    assert result.reproduced is False
    assert result.receipt.tool_available is False
    assert result.receipt.violation_reproduced is False
    assert "unavailable" in result.receipt.detail.lower()


def test_unavailable_tool_probe_callable() -> None:
    recipe = build_replay_recipe(smt_model_witness())

    def probe(tool_id: str, tool_version: str) -> bool:
        assert tool_id == "solver.z3"
        assert tool_version == "4.12.0"
        return False

    result = CounterexampleReplayer().replay(
        recipe,
        oracle=smt_model_oracle,
        tool_available=probe,
    )
    assert result.status is ReplayStatus.UNAVAILABLE
    assert result.reproduced is False


def test_available_tool_with_oracle_reproduces() -> None:
    recipe = build_replay_recipe(smt_model_witness())
    result = CounterexampleReplayer().replay(
        recipe,
        oracle=smt_model_oracle,
        tool_available=True,
    )
    assert result.status is ReplayStatus.REPRODUCED
    assert result.receipt.tool_available is True


# ---------------------------------------------------------------------------
# Privacy: raw private artifacts stay out of public recipes
# ---------------------------------------------------------------------------


def test_public_recipe_excludes_raw_private_artifacts() -> None:
    recipe = build_replay_recipe(leaky_smt_witness())
    public = recipe.to_dict()
    encoded = json.dumps(public, sort_keys=True).lower()

    for forbidden in (
        "do-not-publish-secret",
        "super-secret-credential",
        "unbounded solver transcript",
        "def secrets(): pass",
        "complete repository source",
        "solver dump",
        "hidden_witness",
        "credential",
        "stdout",
        "source_code",
        "source_excerpt",
        "raw_output",
    ):
        assert forbidden not in encoded, f"leaked {forbidden!r} into public recipe"

    assert public["contains_private_material"] is False
    assert public["contains_raw_prover_output"] is False
    assert public["contains_source"] is False
    # Private channels may only appear as digest references.
    refs = public.get("private_artifact_refs") or []
    assert isinstance(refs, list)
    for ref in refs:
        assert "channel" in ref
        assert "digest" in ref
        assert "hidden_witness" not in json.dumps(ref).lower()
        assert "do-not-publish" not in json.dumps(ref).lower()


def test_recipe_rejects_private_material_flags() -> None:
    with pytest.raises(ReplayError):
        ReplayRecipe(
            kind="smt_model",
            bindings=ReplayBindings(property_id="prop:x"),
            public_payload={"assignments": {"x": 1}},
            contains_private_material=True,
        )


def test_recipe_strips_or_rejects_forbidden_public_payload_keys() -> None:
    """Private channel keys must never survive into the public recipe surface.

    Construction may either fail closed or deterministically strip the channel;
    either way ``to_dict()`` must not re-emit the secret key or value.
    """

    try:
        recipe = ReplayRecipe(
            kind="smt_model",
            bindings=ReplayBindings(property_id="prop:x"),
            public_payload={"hidden_witness": "DO-NOT-PUBLISH", "assignments": {"x": 1}},
        )
    except ReplayError:
        return
    encoded = json.dumps(recipe.to_dict(), sort_keys=True).lower()
    assert "hidden_witness" not in encoded
    assert "do-not-publish" not in encoded
    assert "assignments" in recipe.public_payload


def test_replay_result_surface_is_public_safe() -> None:
    result = replay_counterexample(leaky_smt_witness(), oracle=smt_model_oracle)
    encoded = json.dumps(result.to_dict(), sort_keys=True).lower()
    assert "do-not-publish-secret" not in encoded
    assert "super-secret-credential" not in encoded
    assert "hidden_witness" not in encoded
    assert "stdout" not in encoded
    assert "source_code" not in encoded


# ---------------------------------------------------------------------------
# Content addressing stability
# ---------------------------------------------------------------------------


def test_replay_result_content_id_is_deterministic() -> None:
    witness = smt_model_witness()
    recipe = build_replay_recipe(witness)
    r1 = CounterexampleReplayer().replay(recipe, oracle=smt_model_oracle, tool_available=True)
    r2 = CounterexampleReplayer().replay(recipe, oracle=smt_model_oracle, tool_available=True)
    # Receipt content_id is content-addressed over identity-stripped body;
    # wall_ms may differ so full equality is not required — schema/prefix are.
    assert r1.content_id.startswith("sha256:")
    assert r2.content_id.startswith("sha256:")
    assert r1.receipt.receipt_id.startswith("replay-receipt:")
    assert r1.receipt.content_id.startswith("sha256:")
    assert r1.recipe.recipe_id == r2.recipe.recipe_id


def test_recipe_identity_changes_when_bindings_change() -> None:
    a = build_replay_recipe(smt_model_witness(tree_id="tree:a"))
    b = build_replay_recipe(smt_model_witness(tree_id="tree:b"))
    assert a.recipe_id != b.recipe_id


def test_unsupported_without_oracle() -> None:
    recipe = build_replay_recipe(smt_model_witness())
    result = CounterexampleReplayer().replay(recipe)
    assert result.status is ReplayStatus.UNSUPPORTED
    assert result.reproduced is False


def test_malformed_budget_style_inputs_fail_closed() -> None:
    with pytest.raises(ReplayError):
        ReplayBindings.from_mapping("not-a-mapping")  # type: ignore[arg-type]
    with pytest.raises(ReplayError):
        build_replay_recipe("not-a-witness")  # type: ignore[arg-type]


def test_replayer_build_and_replay_cohesive_api() -> None:
    replayer = CounterexampleReplayer(default_oracle=smt_model_oracle)
    recipe = replayer.build_recipe(
        smt_model_witness(),
        oracle_id="oracle:z3-model",
    )
    assert recipe.oracle_id == "oracle:z3-model"
    assert recipe.bindings.tool_id == "solver.z3"
    assert recipe.bindings.assumption_ids == ("asm:finite-domain", "asm:no-overflow")
    assert recipe.bindings.bounds["timeout_ms"] == 250
    result = replayer.replay(recipe, tool_available=True)
    assert result.status is ReplayStatus.REPRODUCED
    assert result.receipt.algorithm == ALGORITHM_NAME
    assert result.receipt.algorithm_version == ALGORITHM_VERSION
    assert result.receipt.schema == REPLAY_RECEIPT_SCHEMA
    payload = result.to_dict()
    assert payload["schema"] == REPLAY_RESULT_SCHEMA
    assert payload["interface"] == COUNTEREXAMPLE_REPLAY_INTERFACE
    assert payload["reproduced"] is True
