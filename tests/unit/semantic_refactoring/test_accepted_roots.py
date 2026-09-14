"""Fail-closed SPAR accepted-root producer. Reports and task counts cannot admit."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "0")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS", "0")
os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.semantic_refactoring.accepted_roots import (
    EXPECTED_GOALS,
    EXPECTED_TASKS,
    MISSING,
    MODE_FLOORS,
    PRODUCER_INTERFACE,
    REQUIRED_CLAUSES,
    SUBJECT_SCHEMA,
    admit_spar_accepted_root,
    subject_binding_cid,
)


def _cids(prefix: str, count: int) -> list[str]:
    return [f"sha256:{prefix}{index:0{64 - len(prefix)}x}" for index in range(count)]


def _subject(**overrides):
    body = {
        "schema": SUBJECT_SCHEMA,
        "profile_cid": "sha256:" + "a" * 64,
        "bootstrap_receipt_id": "sha256:" + "b" * 64,
        "plan_root_cid": "sha256:" + "c" * 64,
        "board_namespace": "semantic-preserving-autonomous-remodularization-v1",
        "source_forest_root": "sha256:" + "d" * 64,
        "repository_tree_id": "tree:spar",
        "source_head": "b6f592a3befee6fd2d4d81265c36904acd906353",
        "kit_transition_cid": "sha256:" + "e" * 64,
        "kit_manifest_cid": "sha256:" + "f" * 64,
        "goal_cids": _cids("11", EXPECTED_GOALS),
        "goal_contract_cids": _cids("22", EXPECTED_GOALS),
        "task_cids": _cids("33", EXPECTED_TASKS),
        "task_receipt_cids": _cids("44", EXPECTED_TASKS),
        "semantic_acceptance_authority": False,
        "completion_authority": False,
    }
    body.update(overrides)
    return body


def test_interface_is_pinned():
    from ipfs_datasets_py.semantic_refactoring import accepted_roots as producer

    assert producer.PRODUCER_INTERFACE == PRODUCER_INTERFACE
    assert callable(producer.admit_spar_accepted_root)


def test_valid_subject_without_independent_artifacts_is_not_admitted():
    subject = _subject()
    result = admit_spar_accepted_root(subject)
    assert result["admitted"] is False
    assert result["semantic_acceptance_authority"] is False
    assert result["completion_authority"] is False
    assert result["reason"] == MODE_FLOORS
    assert result["subject_cid"] == subject_binding_cid(subject)
    assert result["profile_cid"] == subject["profile_cid"]
    assert result["source_forest_root"] == subject["source_forest_root"]
    assert result["evidence_cids"] == []
    assert all(result[name] is False for name in REQUIRED_CLAUSES)


def test_task_count_and_worker_flags_cannot_admit():
    subject = _subject(worker_approved=True, test_pass=True)
    result = admit_spar_accepted_root(subject)
    assert result["admitted"] is False
    assert result["reason"] == "forbidden_subject_field:worker_approved"
    assert result["semantic_acceptance_authority"] is False


def test_self_authorized_subject_is_refused():
    result = admit_spar_accepted_root(_subject(semantic_acceptance_authority=True))
    assert result["admitted"] is False
    assert result["reason"] == "subject_self_authorized"


def test_wrong_schema_is_refused():
    result = admit_spar_accepted_root(_subject(schema="nomination-report"))
    assert result["admitted"] is False
    assert result["reason"] == MISSING


def test_incomplete_receipts_are_refused():
    receipts = _cids("44", EXPECTED_TASKS)
    receipts[-1] = None  # type: ignore[list-item]
    result = admit_spar_accepted_root(_subject(task_receipt_cids=receipts))
    assert result["admitted"] is False
    assert result["reason"] == "sealed_population_incomplete"


def test_duplicate_goal_cids_are_refused():
    goals = _cids("11", EXPECTED_GOALS)
    goals[-1] = goals[0]
    result = admit_spar_accepted_root(_subject(goal_cids=goals))
    assert result["admitted"] is False
    assert result["reason"] == "sealed_population_incomplete"


def test_forged_clause_artifact_does_not_admit():
    subject = _subject(
        clause_artifacts={
            "mode_roots_artifact": {
                "artifact_cid": "sha256:" + "0" * 64,
                "accepted": True,
                "roots": {"tree_id": "sha256:" + "d" * 64},
            }
        }
    )
    result = admit_spar_accepted_root(subject)
    assert result["admitted"] is False
    assert result["required_mode_roots_accepted"] is False
    assert result["semantic_acceptance_authority"] is False


def test_non_mapping_is_refused():
    result = admit_spar_accepted_root(["not-a-subject"])  # type: ignore[arg-type]
    assert result["admitted"] is False
    assert result["reason"] == MISSING
