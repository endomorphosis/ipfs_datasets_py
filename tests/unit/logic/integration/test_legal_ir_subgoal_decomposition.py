"""Deterministic, bounded Legal IR hammer failure decomposition tests."""

from __future__ import annotations

import json

from ipfs_datasets_py.logic.integration.reasoning.legal_ir_subgoals import (
    HARD_MAX_SUBGOALS_PER_OBLIGATION,
    LEGAL_IR_SUBGOAL_DECOMPOSITION_SCHEMA_VERSION,
    LEGAL_IR_SUBGOAL_SCHEMA_VERSION,
    build_legal_ir_subgoal_decomposition,
    decompose_failed_hammer_obligations,
    project_legal_ir_subgoals_to_codex_todos,
)
from ipfs_datasets_py.logic.modal.leanstral_audit import (
    LEANSTRAL_SUBGOAL_AUDIT_PACKET_SCHEMA_VERSION,
    build_leanstral_subgoal_audit_packets,
)


def _obligations() -> list[dict]:
    return [
        {
            "obligation_id": "obl-exception",
            "statement": "exception_scope_precedes_norm(formula:f1, exception_count:2)",
            "kind": "exception_scope_precedence",
            "legal_ir_view": "deontic.ir",
            "logic_family": "conditional_normative",
            "premise_hints": ["exception_scope_precedence"],
            "metadata": {"contract_id": "legal-ir-view/deontic/v1"},
        },
        {
            "obligation_id": "obl-temporal",
            "statement": "temporal_conditions_have_event_order(formula:f1)",
            "kind": "temporal_event_consistency",
            "legal_ir_view": "TDFOL.prover",
            "logic_family": "temporal",
            "premise_hints": ["temporal_conditions_have_event_order"],
            "metadata": {"contract_id": "legal-ir-view/tdfol/v1"},
        },
        {
            "obligation_id": "obl-kg",
            "statement": "kg_edge_typed(subject:agency,predicate:acts_on,object:record)",
            "kind": "knowledge_graph_edge_typing",
            "legal_ir_view": "knowledge_graphs.neo4j_compat",
            "logic_family": "frame",
            "premise_hints": ["kg_edges_are_typed"],
            "metadata": {"contract_id": "legal-ir-view/knowledge-graphs/v1"},
        },
        {
            "obligation_id": "obl-cec",
            "statement": "cec_lifecycle_consistent(event:e1,fluent:f1,time:t1)",
            "kind": "cec_lifecycle_consistency",
            "legal_ir_view": "CEC.native",
            "logic_family": "event_calculus",
            "premise_hints": ["cec_lifecycle_transition"],
            "metadata": {"contract_id": "legal-ir-view/cec/v1"},
        },
        {
            "obligation_id": "obl-decompiler",
            "statement": "decompiler_retains_exception_scope(formula:f1,exception_count:2)",
            "kind": "decompiler_exception_scope_retention",
            "legal_ir_view": "modal.decompiler",
            "logic_family": "conditional_normative",
            "premise_hints": ["decompiler_retains_exception_scope"],
            "metadata": {"contract_id": "legal-ir-view/decompiler/v1"},
        },
    ]


def _failures() -> dict:
    return {
        "artifacts": [
            {
                "obligation_id": obligation["obligation_id"],
                "proof_obligation_ids": [obligation["obligation_id"]],
                "proved": False,
                "trusted": False,
                "failure_reason": "unproved",
            }
            for obligation in reversed(_obligations())
        ]
    }


def test_core_failure_families_split_deterministically_into_bounded_subgoals() -> None:
    first = build_legal_ir_subgoal_decomposition(
        _obligations(), _failures(), max_subgoals_per_obligation=3
    )
    second = build_legal_ir_subgoal_decomposition(
        list(reversed(_obligations())), _failures(), max_subgoals_per_obligation=3
    )

    assert first.to_dict() == second.to_dict()
    assert first.schema_version == LEGAL_IR_SUBGOAL_DECOMPOSITION_SCHEMA_VERSION
    assert first.subgoal_count == 15
    assert first.capped_parent_obligation_ids == tuple(
        sorted(item["obligation_id"] for item in _obligations())
    )
    by_parent: dict[str, list] = {}
    for subgoal in first.subgoals:
        by_parent.setdefault(subgoal.parent_obligation_id, []).append(subgoal)
        assert subgoal.schema_version == LEGAL_IR_SUBGOAL_SCHEMA_VERSION
        assert subgoal.subgoal_id.startswith("lir-subgoal-")
        assert len(subgoal.validation_commands) == 1
        assert subgoal.validation_command
        assert subgoal.primary_contract_id.startswith("legal-ir-view/")
        assert subgoal.allowed_paths
    assert {len(items) for items in by_parent.values()} == {3}
    assert by_parent["obl-decompiler"][0].subgoal_kind == "decompiler_operator"
    assert by_parent["obl-exception"][0].subgoal_kind == "exception_trigger"
    assert by_parent["obl-temporal"][0].subgoal_kind == "temporal_event"
    assert by_parent["obl-kg"][0].subgoal_kind == "kg_subject"
    assert by_parent["obl-cec"][0].subgoal_kind == "cec_event"


def test_only_failures_are_decomposed_and_unknown_ids_are_auditable() -> None:
    failures = {
        "artifacts": [
            {
                "obligation_id": "obl-exception",
                "proved": True,
                "trusted": True,
            },
            {
                "obligation_id": "obl-temporal",
                "proved": False,
                "trusted": False,
                "failure_reason": "timed_out",
            },
            {
                "obligation_id": "unknown-obligation",
                "proved": False,
                "trusted": False,
            },
        ]
    }

    report = build_legal_ir_subgoal_decomposition(_obligations(), failures)

    assert {item.parent_obligation_id for item in report.subgoals} == {"obl-temporal"}
    assert report.failed_obligation_ids == ("obl-temporal", "unknown-obligation")
    assert report.unmatched_failure_ids == ("unknown-obligation",)
    assert {item.failure_mode for item in report.subgoals} == {"timed_out"}


def test_requested_cap_is_clamped_to_a_hard_safety_limit() -> None:
    subgoals = decompose_failed_hammer_obligations(
        [_obligations()[0]],
        _failures(),
        max_subgoals_per_obligation=10_000,
    )
    report = build_legal_ir_subgoal_decomposition(
        [_obligations()[0]],
        _failures(),
        max_subgoals_per_obligation=10_000,
    )

    assert len(subgoals) <= HARD_MAX_SUBGOALS_PER_OBLIGATION
    assert report.max_subgoals_per_obligation == HARD_MAX_SUBGOALS_PER_OBLIGATION


def test_codex_projection_has_one_contract_and_one_validation_command() -> None:
    subgoals = decompose_failed_hammer_obligations(
        _obligations(), _failures(), max_subgoals_per_obligation=2
    )
    todos = project_legal_ir_subgoals_to_codex_todos(reversed(subgoals))

    assert len(todos) == 10
    assert todos == sorted(
        todos, key=lambda item: (item["parent_obligation_id"], item["ordinal"])
    )
    for todo in todos:
        assert todo["contract_id"].startswith("legal-ir-view/")
        assert len(todo["validation_commands"]) == 1
        assert todo["allowed_paths"]


def test_leanstral_packets_are_per_subgoal_source_free_and_content_addressed() -> None:
    source = "The agency shall disclose unless an emergency exists."
    packets = build_leanstral_subgoal_audit_packets(
        [_obligations()[0]],
        _failures(),
        evidence={"source_text": source, "evidence_id": "failure-1"},
        model={"provider": "leanstral_local", "model": "Leanstral"},
        theorem_registry={"schema_version": "registry-v1"},
        max_subgoals_per_obligation=2,
    )
    repeated = build_leanstral_subgoal_audit_packets(
        [_obligations()[0]],
        _failures(),
        evidence={"source_text": source, "evidence_id": "failure-1"},
        model={"provider": "leanstral_local", "model": "Leanstral"},
        theorem_registry={"schema_version": "registry-v1"},
        max_subgoals_per_obligation=2,
    )

    assert [item.to_dict() for item in packets] == [item.to_dict() for item in repeated]
    assert len(packets) == 2
    assert len({item.request.request_id for item in packets}) == 2
    for packet in packets:
        serialized = json.dumps(packet.to_dict(), sort_keys=True)
        assert packet.schema_version == LEANSTRAL_SUBGOAL_AUDIT_PACKET_SCHEMA_VERSION
        assert packet.request.proof_obligation_ids == ("obl-exception",)
        assert packet.request.evidence["failure_subgoal"]["subgoal_id"] == (
            packet.subgoal.subgoal_id
        )
        assert packet.request.prompt["primary_contract_id"] == (
            packet.subgoal.primary_contract_id
        )
        assert packet.codex_todo_projection["subgoal_id"] == packet.subgoal.subgoal_id
        assert len(packet.codex_todo_projection["validation_commands"]) == 1
        assert source not in serialized
        assert packet.request.evidence["source_text_omitted"] is True
        assert len(packet.request.evidence["source_text_sha256"]) == 64
