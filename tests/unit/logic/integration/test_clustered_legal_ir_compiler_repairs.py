"""Contract tests for repairs compiled from recurring verified gap clusters."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ipfs_datasets_py.logic.CEC.native import compile_lifecycle_events
from ipfs_datasets_py.logic.TDFOL import compile_temporal_deadline
from ipfs_datasets_py.logic.deontic import compile_prohibition_polarity
from ipfs_datasets_py.logic.external_provers import select_deterministic_prover_route
from ipfs_datasets_py.logic.integration.reasoning import (
    LEGAL_IR_CLUSTERED_GAP_REPAIR_SCHEMA_VERSION,
    generate_clustered_legal_ir_compiler_repairs,
    generate_clustered_verified_legal_ir_gap_repairs,
)
from ipfs_datasets_py.logic.knowledge_graphs import compile_legal_role_graph
from ipfs_datasets_py.logic.modal import (
    compile_exception_precedence,
    compile_frame_role_bindings,
)


SOURCE = (
    "Except as provided by this subsection, the Agency shall not disclose "
    "records before notice is issued and must file a report within 30 days "
    "after receipt. The Agency may grant, revoke, or enforce the permit. "
    "A civil penalty is an available remedy."
)
SAMPLE = {"sample_id": "usc-5-552", "text": SOURCE}

_LANES = (
    (
        "legal-ir-view/deontic/v1",
        "exception_scope_precedence",
        "deontic.ir",
        "ipfs_datasets_py/logic/deontic/ir.py",
    ),
    (
        "legal-ir-view/deontic/v1",
        "deontic_polarity",
        "deontic.ir",
        "ipfs_datasets_py/logic/deontic/converter.py",
    ),
    (
        "legal-ir-view/tdfol/v1",
        "temporal_anchor",
        "TDFOL.prover",
        "ipfs_datasets_py/logic/TDFOL/tdfol_converter.py",
    ),
    (
        "legal-ir-view/frame-logic/v1",
        "frame_role_typing",
        "modal.frame_logic",
        "ipfs_datasets_py/logic/modal/compiler.py",
    ),
    (
        "legal-ir-view/knowledge-graphs/v1",
        "knowledge_graph_endpoint_typing",
        "knowledge_graphs.neo4j_compat",
        "ipfs_datasets_py/logic/modal/kg_bridge.py",
    ),
    (
        "legal-ir-view/cec/v1",
        "cec_lifecycle_transition",
        "CEC.native",
        "ipfs_datasets_py/logic/CEC/native/event_calculus.py",
    ),
    (
        "legal-ir-view/external-provers/v1",
        "external_prover_route_preservation",
        "external_provers.router",
        "ipfs_datasets_py/logic/external_provers/prover_router.py",
    ),
)


def _cluster(
    contract_id: str,
    family: str,
    target_view: str,
    path: str,
    *,
    support_count: int = 2,
    failure_reason: str = "hammer_unproved",
    recurring: bool = True,
) -> dict[str, Any]:
    key = {
        "allowed_paths": [path],
        "contract_id": contract_id,
        "failure_reason": failure_reason,
        "obligation_family": family,
        "target_view": target_view,
    }
    signature = "hammer-failure:" + hashlib.sha256(
        json.dumps(key, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    return {
        **key,
        "available_backends": ["z3", "vampire", "lean"],
        "cluster_key": key,
        "cluster_schema_version": "legal-ir-hammer-failure-cluster-v1",
        "dedupe_signature": signature,
        "high_impact_replay_failure": False,
        "proof_obligation_ids": [f"obl-{family}"],
        "qualification_reason": "recurring_verified_failure" if recurring else "",
        "recurrence_threshold": 2,
        "recurring_verified_failure": recurring,
        "source": "hammer_failure_projection_v1",
        "support_count": support_count,
        "validation_commands": [
            "python -m pytest -q tests/unit/logic/integration/"
            "test_clustered_legal_ir_compiler_repairs.py"
        ],
    }


def _clusters() -> list[dict[str, Any]]:
    return [_cluster(*lane) for lane in _LANES]


def test_clustered_repairs_compile_every_priority_lane_deterministically() -> None:
    clusters = _clusters()
    forward = generate_clustered_verified_legal_ir_gap_repairs(
        clusters,
        sample_or_document=SAMPLE,
    )
    reverse = generate_clustered_legal_ir_compiler_repairs(
        [*reversed(clusters), clusters[0]],
        sample_or_document=SAMPLE,
    )

    assert len(forward) == len(_LANES)
    assert [item.to_dict() for item in forward] == [item.to_dict() for item in reverse]
    assert all(
        item.schema_version == LEGAL_IR_CLUSTERED_GAP_REPAIR_SCHEMA_VERSION
        for item in forward
    )
    assert all(item.allowed_paths and item.validation_commands for item in forward)
    assert all(
        item.metadata["promotion_rule"].startswith("improve_or_preserve_fixed_canary")
        for item in forward
    )

    by_family = {item.gap_family: item for item in forward}
    exception = by_family["exception_scope_precedence"].typed_semantics
    assert exception["precedence"] == "exception_over_general_rule"
    assert exception["exceptions"][0]["relation"] == "overrides"

    prohibition = by_family["deontic_polarity"].typed_semantics
    assert prohibition["norms"][0]["deontic_operator"] == "F"
    assert prohibition["norms"][0]["polarity"] == "negative"
    assert prohibition["norms"][0]["action_negated"] is False

    temporal = by_family["temporal_anchor"].typed_semantics
    relative = next(item for item in temporal["constraints"] if item["offset"] == 30)
    assert (relative["anchor"], relative["relation"], relative["unit"]) == (
        "receipt",
        "after",
        "days",
    )

    frame_roles = {
        item["role"] for item in by_family["frame_role_typing"].typed_semantics["bindings"]
    }
    assert {"agent", "action", "object"}.issubset(frame_roles)

    graph = by_family["knowledge_graph_endpoint_typing"].typed_semantics
    assert {edge["role"] for edge in graph["relationships"]} == {
        "actor",
        "action",
        "object",
        "remedy",
    }
    assert all(edge["directed"] for edge in graph["relationships"])

    lifecycle = by_family["cec_lifecycle_transition"].typed_semantics
    assert {event["predicate"] for event in lifecycle["events"]} == {"Happens"}
    assert {row["relation"] for row in lifecycle["lifecycle_transitions"]} == {
        "Initiates",
        "Terminates",
    }

    route = by_family["external_prover_route_preservation"].typed_semantics
    assert route["backend_route"] == ["vampire", "z3", "lean"]
    assert route["reconstruction_status"] == "planned"
    assert route["route_status"] == "planned"

    forbidden = {"text", "raw_source", "source_text", "source_span", "normalized_text"}
    for repair in forward:
        assert not (_nested_keys(repair.typed_semantics) & forbidden)
        json.dumps(repair.to_dict(), sort_keys=True)


def test_cluster_boundary_rejects_noise_unsafe_paths_and_contract_mismatches() -> None:
    one_off = _cluster(*_LANES[0], support_count=1, recurring=False)
    # A caller cannot bypass recurrence by forging only the descriptive label.
    one_off["qualification_reason"] = "recurring_verified_failure"
    unavailable = _cluster(*_LANES[1], failure_reason="backend_unavailable")
    unsafe = _cluster(
        "legal-ir-view/tdfol/v1",
        "temporal_anchor",
        "TDFOL.prover",
        "../../tdfol.py",
    )
    mismatch = _cluster(
        "legal-ir-view/deontic/v1",
        "deontic_polarity",
        "TDFOL.prover",
        "ipfs_datasets_py/logic/deontic/ir.py",
    )

    assert generate_clustered_legal_ir_compiler_repairs(
        [one_off, unavailable, unsafe, mismatch],
        sample_or_document=SAMPLE,
    ) == []


def test_duplicate_cluster_evidence_is_merged_independent_of_input_order() -> None:
    first = _cluster(*_LANES[1])
    second = {**first, "proof_obligation_ids": ["obl-second", "obl-deontic_polarity"]}

    left = generate_clustered_legal_ir_compiler_repairs(
        [first, second], sample_or_document=SAMPLE
    )
    right = generate_clustered_legal_ir_compiler_repairs(
        [second, first], sample_or_document=SAMPLE
    )

    assert [repair.to_dict() for repair in left] == [repair.to_dict() for repair in right]
    assert left[0].proof_obligation_ids == ["obl-deontic_polarity", "obl-second"]


def test_lane_apis_are_typed_source_free_and_stable() -> None:
    compilers = (
        compile_exception_precedence,
        compile_frame_role_bindings,
        compile_prohibition_polarity,
        compile_temporal_deadline,
        compile_legal_role_graph,
        compile_lifecycle_events,
    )
    for compiler in compilers:
        first = compiler(SOURCE, provenance_id="usc-5-552")
        assert first == compiler(SOURCE, provenance_id="usc-5-552")
        assert first["schema_version"].startswith("legal-ir-")
        assert "text" not in _nested_keys(first)

    first_route = select_deterministic_prover_route(
        "tdfol",
        ["lean", "z3", "vampire"],
        provenance_id="usc-5-552",
        require_reconstruction=True,
    )
    second_route = select_deterministic_prover_route(
        "tdfol",
        ["vampire", "lean", "z3"],
        provenance_id="usc-5-552",
        require_reconstruction=True,
    )
    assert first_route == second_route
    assert first_route["backend_route"] == ["vampire", "z3", "lean"]


def _nested_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {str(key) for key in value} | {
            nested
            for item in value.values()
            for nested in _nested_keys(item)
        }
    if isinstance(value, (list, tuple)):
        return {nested for item in value for nested in _nested_keys(item)}
    return set()
