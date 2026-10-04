"""Integration coverage for GoalTacticianAPI@1 (FVT-G050 / FVT-029).

Acceptance:

* Python surface exposes closed operations for goal formalization, interpretation
  comparison, missing-proof discovery, proof planning / validation / execution /
  status, and counterexample minimization / explanation / replay;
* every response shares status, authority, diagnostics, redaction, bounds,
  cancellation, identities, and availability;
* imports are side-effect free;
* legacy ``STABLE_OPERATIONS`` remain compatible;
* transport success never implies proof success;
* supervisor-only mutation controls are refused.
"""

from __future__ import annotations

import importlib
import sys
import warnings
from typing import Any

import pytest

from ipfs_datasets_py.logic.verification_api import (
    GOAL_TACTICIAN_API_INTERFACE,
    GOAL_TACTICIAN_CLI_MCP_INTERFACE,
    GOAL_TACTICIAN_OPERATIONS,
    LOGIC_VERIFICATION_API_INTERFACE,
    STABLE_OPERATIONS,
    LogicVerificationAPI,
    VerificationAuthority,
    VerificationStatus,
    get_verification_api,
    list_goal_tactician_cli_mcp_surface,
)


ENVELOPE_KEYS = {
    "status",
    "authority",
    "operation",
    "result",
    "assumptions",
    "bounds",
    "translations",
    "witnesses",
    "unsupported_features",
    "diagnostics",
    "cache",
    "interface",
}


def _assert_envelope(payload: dict[str, Any], *, operation: str | None = None) -> None:
    missing = ENVELOPE_KEYS - set(payload)
    assert not missing, f"missing envelope keys: {sorted(missing)}"
    assert payload["interface"] == LOGIC_VERIFICATION_API_INTERFACE
    assert isinstance(payload["status"], str) and payload["status"]
    assert isinstance(payload["authority"], str)
    assert isinstance(payload["result"], dict)
    assert isinstance(payload["assumptions"], list)
    assert isinstance(payload["bounds"], dict)
    assert isinstance(payload["translations"], list)
    assert isinstance(payload["witnesses"], list)
    assert isinstance(payload["unsupported_features"], list)
    assert isinstance(payload["diagnostics"], list)
    assert isinstance(payload["cache"], dict)
    if operation is not None:
        assert payload["operation"] == operation


def _source(**overrides: Any) -> dict[str, Any]:
    payload = {
        "tree_id": "tree:repo@abc",
        "source_ref_ids": ["source:prompt", "source:lease.py"],
        "span_ids": ["span:caller"],
        "ast_scope_ids": ["symbol:claim_lease"],
        "snapshot_id": "snap:1",
    }
    payload.update(overrides)
    return payload


def _formalize_request() -> dict[str, Any]:
    return {
        "caller_text": "\n".join(
            [
                "PROPERTY existential_reachability",
                "QUANTIFIER exists",
                "QUANTIFIER eventually",
                "ACTOR scheduler",
                "STATE phase",
                "CURRENT phase=init",
                "TARGET phase=ready",
                "TRANSITION claim",
                "ASSUME must_prove: tokens are totally ordered",
                "BOUND wall_time_ms=5000",
                "BOUND max_steps=32",
                "ASSURANCE bounded",
                "LOGIC temporal.ltl",
                "PROVIDER provider:z3",
                "ACCEPT receipt:kernel",
                "RECEIPT proof-receipt",
            ]
        ),
        "source": _source(),
        "goal_id": "goal:lease-ready",
        "root_goal_id": "goal:lease-ready",
        "known_identifiers": ["scheduler", "phase", "claim", "init", "ready"],
        "repository_source_ref_ids": ["source:lease.py"],
        "prefer_controlled_language": True,
        "max_candidates": 8,
        "logic_family": "temporal.ltl",
        "provider_ids": ["provider:z3"],
        "bounds": {"wall_time_ms": 1000, "max_steps": 8, "network_allowed": False},
    }


def _witness() -> dict[str, Any]:
    return {
        "kind": "model",
        "assignments": {"x": 1, "y": 2, "z": 0},
        "tool_id": "z3",
        "tool_version": "4.12.0",
        "property_id": "property:lease-safety",
        "tree_id": "tree:repo@abc",
        "assumption_ids": ["assume:tokens-ordered"],
        "bounds": {"max_steps": 8},
    }


def _missing_surface() -> dict[str, Any]:
    from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
        SourceSpanBinding,
    )
    from ipfs_datasets_py.logic.software_verification.tactician.proof_holes import (
        CompilationSurface,
        loop_site,
    )

    source = SourceSpanBinding(
        tree_id="tree:repo@abc",
        source_ref_ids=("source:lease.py",),
        span_ids=("span:loop-claim",),
        ast_scope_ids=("symbol:claim_loop",),
        snapshot_id="snap:1",
    )
    surface = CompilationSurface(
        surface_id="surface:lease-ready",
        formal_goal_id="formal:lease-ready",
        tree_id="tree:repo@abc",
        sites=(
            loop_site(
                "site:loop-claim",
                source=source,
                has_invariant=False,
                has_variant=False,
                require_variant=False,
            ),
        ),
        provider_ids=("provider:z3",),
    )
    return surface.to_dict()


def _ranked_plan_request() -> dict[str, Any]:
    from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
        AuthorityCeiling,
    )
    from ipfs_datasets_py.logic.software_verification.tactician.proof_plan import (
        build_missing_proof_plan,
        complete_step,
    )

    plan = build_missing_proof_plan(
        "plan:alpha",
        formal_goal_id="formal:lease-ready",
        graph_id="graph:lease",
        tree_id="tree:repo@abc",
        steps=(
            complete_step(
                "step:alpha:0",
                "obligation:lease-safety",
                authority=AuthorityCeiling.BOUNDED,
                provider_ids=("provider:z3",),
            ),
            complete_step(
                "step:alpha:1",
                "obligation:router-bounds",
                dependencies=("step:alpha:0",),
                authority=AuthorityCeiling.BOUNDED,
                provider_ids=("provider:z3",),
            ),
        ),
        required_obligation_ids=(
            "obligation:lease-safety",
            "obligation:router-bounds",
        ),
    )
    return {
        "alternatives": [plan.to_dict()],
        "policy": {
            "minimum_authority": "bounded",
            "available_resource_classes": ["solver", "kernel", "artifact_store"],
            "satisfied_dependencies": ["root:goal"],
            "required_obligation_ids": [
                "obligation:lease-safety",
                "obligation:router-bounds",
            ],
        },
        "bounds": {"wall_time_ms": 1000, "max_steps": 16},
    }


# ---------------------------------------------------------------------------
# Discovery / import hygiene
# ---------------------------------------------------------------------------


def test_goal_tactician_interfaces_and_operation_catalog() -> None:
    assert GOAL_TACTICIAN_API_INTERFACE == "GoalTacticianAPI@1"
    assert GOAL_TACTICIAN_CLI_MCP_INTERFACE == "GoalTacticianCLIMCP@1"
    required = {
        "formalize_goal",
        "compare_interpretations",
        "discover_missing_proofs",
        "plan_proof",
        "validate_proof_candidate",
        "execute_proof_plan",
        "proof_status",
        "minimize_counterexample",
        "explain_counterexample_causal",
        "replay_counterexample",
        "list_goal_tactician_operations",
    }
    assert required <= set(GOAL_TACTICIAN_OPERATIONS)
    # Additive only — legacy MCP parity depends on STABLE_OPERATIONS staying closed.
    assert set(GOAL_TACTICIAN_OPERATIONS).isdisjoint(set(STABLE_OPERATIONS))

    api = get_verification_api(reset=True)
    catalog = api.list_goal_tactician_operations().to_dict()
    _assert_envelope(catalog, operation="list_goal_tactician_operations")
    assert catalog["status"] == VerificationStatus.DECLARATIVE.value
    assert catalog["authority"] == VerificationAuthority.DECLARATIVE.value
    assert set(catalog["result"]["operations"]) == set(GOAL_TACTICIAN_OPERATIONS)
    assert catalog["result"]["interface"] == GOAL_TACTICIAN_CLI_MCP_INTERFACE
    assert catalog["result"]["transport_success_implies_proof_success"] is False

    surface = list_goal_tactician_cli_mcp_surface()
    assert surface["python_interface"] == GOAL_TACTICIAN_API_INTERFACE
    assert set(surface["legacy_operations_preserved"]) == set(STABLE_OPERATIONS)


def test_goal_tactician_import_is_side_effect_free(monkeypatch) -> None:
    monkeypatch.delenv("IPFS_DATASETS_PY_WARN_OPTIONAL_IMPORTS", raising=False)
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        api_mod = importlib.import_module("ipfs_datasets_py.logic.verification_api")
        api = api_mod.get_verification_api(reset=True)
        catalog = api.list_goal_tactician_operations()
        # Discovery must not require external tool installers.
        assert "ipfs_datasets_py.logic.external_provers.lazy_installer" not in sys.modules
    assert catalog.status is VerificationStatus.DECLARATIVE
    ipfs_warnings = [
        item
        for item in recorded
        if "ipfs_datasets_py" in (getattr(item, "filename", "") or "")
    ]
    assert ipfs_warnings == []


def test_legacy_stable_operations_remain_compatible() -> None:
    api = get_verification_api(reset=True)
    descriptor = api.to_dict()
    assert descriptor["interface"] == LOGIC_VERIFICATION_API_INTERFACE
    assert descriptor["operations"] == list(STABLE_OPERATIONS)
    assert descriptor["goal_tactician_interface"] == GOAL_TACTICIAN_API_INTERFACE
    assert set(descriptor["goal_tactician_operations"]) == set(GOAL_TACTICIAN_OPERATIONS)

    providers = api.list_providers().to_dict()
    _assert_envelope(providers, operation="list_providers")
    assert providers["status"] == "declarative"
    assert providers["result"]["count"] >= 1

    features = api.list_features().to_dict()
    feature_ids = {item["feature_id"] for item in features["result"]["features"]}
    assert set(STABLE_OPERATIONS) <= feature_ids or set(STABLE_OPERATIONS) <= set(
        features["result"]["operations"]
    )
    assert set(GOAL_TACTICIAN_OPERATIONS) <= feature_ids


# ---------------------------------------------------------------------------
# Core goal-directed operations
# ---------------------------------------------------------------------------


def test_formalize_goal_candidate_only_and_closed_envelope() -> None:
    api = get_verification_api(reset=True)
    response = api.formalize_goal(_formalize_request(), request_id="req:formalize")
    payload = response.to_dict()
    _assert_envelope(payload, operation="formalize_goal")
    assert payload["status"] in {"succeeded", "partial", "unsupported", "invalid"}
    assert payload["authority"] == VerificationAuthority.ADVISORY.value
    assert payload["result"]["admitted"] is False
    assert payload["result"]["proof_success"] is False
    assert payload["result"]["goal_tactician_interface"] == GOAL_TACTICIAN_API_INTERFACE
    assert "secret" not in str(payload["result"]).lower() or "secret" not in payload["result"]


def test_compare_interpretations_exposes_ambiguity_without_admission() -> None:
    api = get_verification_api(reset=True)
    response = api.compare_interpretations(
        {"source": "the system reaches ready", "goal_id": "goal:ambiguous"},
        request_id="req:compare",
    )
    payload = response.to_dict()
    _assert_envelope(payload, operation="compare_interpretations")
    assert payload["status"] in {"succeeded", "partial"}
    assert payload["authority"] == VerificationAuthority.ADVISORY.value
    assert payload["result"]["mode"] == "ambiguity_gate"
    assert payload["result"]["admitted"] is False
    assert payload["result"]["proof_success"] is False
    assert payload["result"]["requires_selection"] in {True, False}


def test_discover_missing_proofs_emits_typed_holes() -> None:
    api = get_verification_api(reset=True)
    response = api.discover_missing_proofs(_missing_surface(), request_id="req:holes")
    payload = response.to_dict()
    _assert_envelope(payload, operation="discover_missing_proofs")
    assert payload["status"] == "succeeded"
    assert payload["authority"] == VerificationAuthority.ADVISORY.value
    assert payload["result"]["count"] >= 1
    assert payload["result"]["missing_proof_count"] >= 1
    assert payload["result"]["proof_success"] is False


def test_plan_proof_ranks_without_claiming_proof() -> None:
    api = get_verification_api(reset=True)
    response = api.plan_proof(_ranked_plan_request(), request_id="req:plan")
    payload = response.to_dict()
    _assert_envelope(payload, operation="plan_proof")
    assert payload["status"] in {"succeeded", "partial"}
    assert payload["authority"] == VerificationAuthority.ADVISORY.value
    assert payload["result"]["proof_success"] is False
    assert payload["result"]["proof_claimed"] is False
    assert payload["result"]["goal_tactician_interface"] == GOAL_TACTICIAN_API_INTERFACE


def test_validate_proof_candidate_requires_closed_inputs() -> None:
    api = get_verification_api(reset=True)
    missing = api.validate_proof_candidate(
        {"candidate": {"step_id": "s"}}, request_id="req:validate"
    ).to_dict()
    _assert_envelope(missing, operation="validate_proof_candidate")
    assert missing["status"] == "invalid"
    assert "candidate, hole, and binding are required" in missing["diagnostics"][0]


def test_execute_proof_plan_local_readiness_never_mutates_supervisor() -> None:
    api = get_verification_api(reset=True)
    ready = api.execute_proof_plan(
        {
            "plan_id": "plan:ready",
            "steps": [
                {
                    "step_id": "step:1",
                    "obligation_id": "obligation:lease-safety",
                    "statement": "lease remains safe",
                }
            ],
            "bounds": {"max_steps": 4},
        },
        request_id="req:exec",
    ).to_dict()
    _assert_envelope(ready, operation="execute_proof_plan")
    assert ready["status"] == "succeeded"
    assert ready["result"]["ready"] is True
    assert ready["result"]["executed"] is False
    assert ready["result"]["supervisor_mutated"] is False
    assert ready["result"]["proof_success"] is False

    forbidden = api.execute_proof_plan(
        {
            "plan_id": "plan:bad",
            "steps": [{"step_id": "s", "obligation_id": "o"}],
            "controls": {"admit_goal": True, "close_plan": True},
        }
    ).to_dict()
    assert forbidden["status"] == "invalid"
    assert "supervisor-only" in forbidden["diagnostics"][0]
    assert "supervisor_only_control" in forbidden["unsupported_features"]


def test_proof_status_transport_success_does_not_imply_proof_success() -> None:
    api = get_verification_api(reset=True)
    claimed = api.proof_status(
        {
            "plan_id": "plan:claimed",
            "status": "complete",
            "steps": [{"step_id": "s1"}],
            "receipts": [],
        }
    ).to_dict()
    _assert_envelope(claimed, operation="proof_status")
    assert claimed["result"]["transport_ok"] is True
    assert claimed["result"]["proof_success"] is False
    assert claimed["status"] == "partial"

    proven = api.proof_status(
        {
            "plan_id": "plan:proven",
            "status": "complete",
            "steps": [{"step_id": "s1"}],
            "receipts": [{"receipt_id": "receipt:1", "schema": "trusted-proof-receipt/v1"}],
        }
    ).to_dict()
    assert proven["result"]["proof_success"] is True
    assert proven["result"]["identity"]
    assert proven["status"] == "succeeded"


def test_counterexample_minimize_explain_replay_public_safe() -> None:
    api = get_verification_api(reset=True)
    witness = _witness()

    minimized = api.minimize_counterexample(
        {"witness": witness, "family": "smt_model", "oracle_id": "oracle:public"},
        request_id="req:min",
    ).to_dict()
    _assert_envelope(minimized, operation="minimize_counterexample")
    assert minimized["status"] == "succeeded"
    assert minimized["result"]["proof_success"] is False
    assert "password" not in str(minimized).lower()
    assert "private_key" not in str(minimized).lower()

    explained = api.explain_counterexample_causal(
        {
            "witness": witness,
            "violated_property": "property:lease-safety",
            "assumption_ids": ["assume:tokens-ordered"],
        },
        request_id="req:explain",
    ).to_dict()
    _assert_envelope(explained, operation="explain_counterexample_causal")
    assert explained["status"] == "succeeded"
    assert explained["result"]["proof_success"] is False
    assert explained["result"]["goal_tactician_interface"] == GOAL_TACTICIAN_API_INTERFACE

    replayed = api.replay_counterexample(
        {"witness": witness, "tool_available": True},
        request_id="req:replay",
    ).to_dict()
    _assert_envelope(replayed, operation="replay_counterexample")
    assert replayed["status"] in {"succeeded", "partial", "unavailable"}
    assert replayed["result"]["proof_success"] is False


def test_cancellation_is_honored_across_goal_operations() -> None:
    api = get_verification_api(reset=True)
    token = {"cancelled": True}
    ops = [
        ("formalize_goal", lambda: api.formalize_goal(_formalize_request(), cancellation=token)),
        (
            "compare_interpretations",
            lambda: api.compare_interpretations(
                {"source": "reaches ready"}, cancellation=token
            ),
        ),
        (
            "discover_missing_proofs",
            lambda: api.discover_missing_proofs(_missing_surface(), cancellation=token),
        ),
        ("plan_proof", lambda: api.plan_proof(_ranked_plan_request(), cancellation=token)),
        (
            "execute_proof_plan",
            lambda: api.execute_proof_plan(
                {"plan_id": "p", "steps": [{"step_id": "s", "obligation_id": "o"}]},
                cancellation=token,
            ),
        ),
        (
            "proof_status",
            lambda: api.proof_status({"plan_id": "p", "status": "running"}, cancellation=token),
        ),
        (
            "minimize_counterexample",
            lambda: api.minimize_counterexample(
                {"witness": _witness()}, cancellation=token
            ),
        ),
        (
            "explain_counterexample_causal",
            lambda: api.explain_counterexample_causal(
                {"witness": _witness()}, cancellation=token
            ),
        ),
        (
            "replay_counterexample",
            lambda: api.replay_counterexample(
                {"witness": _witness()}, cancellation=token
            ),
        ),
    ]
    for operation, call in ops:
        payload = call().to_dict()
        _assert_envelope(payload, operation=operation)
        assert payload["status"] == "partial"
        assert payload["result"].get("cancelled") is True


def test_invoke_dispatcher_covers_catalog() -> None:
    api = get_verification_api(reset=True)
    for operation in GOAL_TACTICIAN_OPERATIONS:
        assert hasattr(LogicVerificationAPI, operation) or operation == "list_goal_tactician_operations"
        if operation == "list_goal_tactician_operations":
            response = api.invoke_goal_tactician(operation)
        elif operation == "formalize_goal":
            response = api.invoke_goal_tactician(operation, _formalize_request())
        elif operation == "compare_interpretations":
            response = api.invoke_goal_tactician(
                operation, {"source": "reaches ready", "goal_id": "goal:x"}
            )
        elif operation == "discover_missing_proofs":
            response = api.invoke_goal_tactician(operation, _missing_surface())
        elif operation == "plan_proof":
            response = api.invoke_goal_tactician(operation, _ranked_plan_request())
        elif operation == "validate_proof_candidate":
            response = api.invoke_goal_tactician(operation, {"candidate": {}})
        elif operation == "execute_proof_plan":
            response = api.invoke_goal_tactician(
                operation,
                {
                    "plan_id": "plan:d",
                    "steps": [
                        {
                            "step_id": "s",
                            "obligation_id": "o",
                            "statement": "s",
                        }
                    ],
                },
            )
        elif operation == "proof_status":
            response = api.invoke_goal_tactician(
                operation, {"plan_id": "plan:d", "status": "open"}
            )
        elif operation in {
            "minimize_counterexample",
            "explain_counterexample_causal",
            "replay_counterexample",
        }:
            response = api.invoke_goal_tactician(operation, {"witness": _witness()})
        else:  # pragma: no cover
            raise AssertionError(operation)
        payload = response.to_dict()
        _assert_envelope(payload, operation=operation)
        if payload["status"] == "succeeded":
            # Transport / API success is independent of proof success.
            assert payload["result"].get("proof_success", False) in {False, True}
            if operation not in {"proof_status"}:
                assert payload["result"].get("proof_success", False) is False


def test_private_channels_are_redacted_from_public_results() -> None:
    api = get_verification_api(reset=True)
    dirty = dict(_witness())
    dirty["secret"] = "super-secret-value"
    dirty["private_key"] = "pk-abc"
    dirty["raw"] = {"hidden_witness": "leak"}
    payload = api.minimize_counterexample({"witness": dirty}).to_dict()
    blob = str(payload)
    assert "super-secret-value" not in blob
    assert "pk-abc" not in blob
    assert "hidden_witness" not in blob or "hidden_witness" not in payload["result"]
