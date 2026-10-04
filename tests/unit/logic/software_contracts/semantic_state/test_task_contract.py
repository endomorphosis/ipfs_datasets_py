"""ASEH-051 task-contract conformance and negative vectors."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_state.task_contract import (
    COMPLETENESS_WITNESS_SCHEMA,
    ENVELOPE_FIELDS,
    TASK_CONTRACT_INTERFACE,
    TASK_CONTRACT_SCHEMA,
    TaskContract,
    TaskContractError,
    build_task_contract,
    canonical_payload_from_envelope,
    load_task_contract_schema,
    validate_task_contract_envelope,
)


COMMIT = "1" * 40
TREE = "2" * 40


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _kwargs(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "task_id": "ASEH-051",
        "objective_revision": "objective:revision-1",
        "repository_commit": COMMIT,
        "repository_tree": TREE,
        "policy_identity": "policy:planning-v1",
        "assumptions": [{"id": "a_source", "statement": "the source tree is available"}],
        "guarantees": [{
            "id": "g_scoped", "statement": "all mutations remain in declared paths",
            "under_assumptions": ["a_source"],
        }],
        "cone": {
            "affected_symbols": ["task_contract.build"],
            "affected_paths": ["ipfs_datasets_py/logic/software_contracts/semantic_state/task_contract.py"],
            "dependencies": ["content.cid_for_structured"],
            "dependents": ["accelerate.planning"],
        },
        "interfaces": ["SemanticTaskContract@1"],
        "permitted_paths": [
            "ipfs_datasets_py/logic/software_contracts/semantic_state/task_contract.py",
            "tests/unit/logic/software_contracts/semantic_state/test_task_contract.py",
        ],
        "side_effects": [{
            "id": "write_contract", "kind": "write",
            "paths": ["ipfs_datasets_py/logic/software_contracts/semantic_state/task_contract.py"],
            "description": "write the declared contract implementation",
        }],
        "acceptance": [{"id": "a_closed", "statement": "the contract is closed and canonical"}],
        "tests": [{"id": "t_unit", "command": "python3 -m pytest -q tests/unit/.../test_task_contract.py"}],
        "proofs": [{"id": "p_cid", "claim": "the claimed CID recomputes from canonical facts"}],
        "questions": [],
        "obligations": [
            {"id": "o_acceptance", "kind": "acceptance", "subject_id": "a_closed", "required": True},
            {"id": "o_test", "kind": "test", "subject_id": "t_unit", "required": True},
            {"id": "o_proof", "kind": "proof", "subject_id": "p_cid", "required": True},
        ],
        "budget": {
            "max_tokens": 1000, "max_tool_calls": 20, "max_wall_time_seconds": 600,
            "validation_reserve": {"max_tokens": 200, "max_tool_calls": 4, "max_wall_time_seconds": 120},
        },
        "fallback": {"trigger": "proof is unavailable", "action": "report a typed capability gap"},
        "recovery": {"trigger": "validation fails", "rollback": "discard only the scoped patch", "retry": "replan from the same identity"},
        "completeness_witness": {
            "schema": COMPLETENESS_WITNESS_SCHEMA,
            "witness_cid": _cid("completeness-witness"),
            "task_id": "ASEH-051",
            "objective_revision": "objective:revision-1",
            "repository_commit": COMMIT,
            "repository_tree": TREE,
            "policy_identity": "policy:planning-v1",
            "obligation_ids": ["o_acceptance", "o_proof", "o_test"],
        },
    }
    values.update(overrides)
    return values


def _build(**overrides: object) -> TaskContract:
    return build_task_contract(**_kwargs(**overrides))  # type: ignore[arg-type]


def test_closed_canonical_contract_round_trips_and_binds_every_fact() -> None:
    first = _build()
    reordered = _build(
        interfaces=["SemanticTaskContract@1"],
        obligations=list(reversed(_kwargs()["obligations"])),  # type: ignore[arg-type]
    )
    assert first.task_contract_cid == reordered.task_contract_cid
    assert first.is_complete is True
    assert first.verify_identity() == first.task_contract_cid
    assert first.canonical_payload()["schema"] == TASK_CONTRACT_SCHEMA
    assert first.canonical_payload()["interface"] == TASK_CONTRACT_INTERFACE
    envelope = first.to_dict()
    assert tuple(envelope) == ENVELOPE_FIELDS
    assert validate_task_contract_envelope(envelope) == envelope
    assert TaskContract.from_dict(envelope).canonical_bytes() == first.canonical_bytes()
    assert canonical_payload_from_envelope(envelope) == first.canonical_payload()
    with pytest.raises(TypeError):
        first._canonical["task_id"] = "forged"  # type: ignore[index]

    changed = _build(fallback={"trigger": "test is unavailable", "action": "record unresolved evidence"})
    assert changed.task_contract_cid != first.task_contract_cid


def test_assumption_guarantee_consistency_is_structural_and_fail_closed() -> None:
    with pytest.raises(TaskContractError, match="unknown assumptions"):
        _build(guarantees=[{"id": "g", "statement": "scoped", "under_assumptions": ["missing"]}])
    with pytest.raises(TaskContractError, match="every assumption"):
        _build(guarantees=[])


def test_completeness_witness_covers_required_obligations_and_has_fresh_identity() -> None:
    witness = dict(_kwargs()["completeness_witness"])  # type: ignore[arg-type]
    witness["obligation_ids"] = ["o_acceptance", "o_test"]
    with pytest.raises(TaskContractError, match="exactly every required obligation"):
        _build(completeness_witness=witness)

    envelope = _build().to_dict()
    envelope["objective_revision"] = "objective:revision-2"
    with pytest.raises(TaskContractError, match="stale"):
        validate_task_contract_envelope(envelope)

    with pytest.raises(TaskContractError, match="blocking questions"):
        _build(questions=[{"id": "q1", "question": "is a dependency available?", "blocking": True}])
    partial = _build(
        questions=[{"id": "q1", "question": "is a dependency available?", "blocking": True}],
        completeness_witness=None,
    )
    assert partial.is_complete is False


def test_mutating_effects_are_confined_to_permitted_normalized_paths() -> None:
    effect = dict(_kwargs()["side_effects"][0])  # type: ignore[index]
    effect["paths"] = ["protected/policy.py"]
    with pytest.raises(TaskContractError, match="outside permitted_paths"):
        _build(side_effects=[effect])
    with pytest.raises(TaskContractError, match="repository-relative"):
        _build(permitted_paths=["/etc/passwd"])
    with pytest.raises(TaskContractError, match="normalized"):
        _build(permitted_paths=["src/../policy.py"])


def test_obligations_close_acceptance_tests_and_proofs() -> None:
    incomplete = list(_kwargs()["obligations"])  # type: ignore[arg-type]
    incomplete.pop()
    with pytest.raises(TaskContractError, match="every proof fact"):
        _build(obligations=incomplete)

    bad_subject = list(_kwargs()["obligations"])  # type: ignore[arg-type]
    bad_subject[0] = {**bad_subject[0], "subject_id": "missing"}
    with pytest.raises(TaskContractError, match="unknown acceptance subject"):
        _build(obligations=bad_subject)


def test_validation_reserve_is_not_spendable_implementation_capacity() -> None:
    budget = dict(_kwargs()["budget"])  # type: ignore[arg-type]
    budget["validation_reserve"] = {"max_tokens": 1000, "max_tool_calls": 4, "max_wall_time_seconds": 120}
    with pytest.raises(TaskContractError, match="leave implementation capacity"):
        _build(budget=budget)


def test_envelope_and_json_schema_are_closed() -> None:
    envelope = _build().to_dict()
    malformed = {**envelope, "untrusted": True}
    with pytest.raises(TaskContractError, match="unknown field"):
        validate_task_contract_envelope(malformed)

    schema = load_task_contract_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(ENVELOPE_FIELDS)
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator(schema).validate(json.loads(json.dumps(envelope)))
