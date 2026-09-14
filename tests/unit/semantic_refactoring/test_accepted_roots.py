"""SPAR accepted-root producer never admits missing or caller-forged evidence."""

from __future__ import annotations

import copy
import os

os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "0")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS", "0")
os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.semantic_refactoring.accepted_roots import (
    MODE_FLOORS,
    PRODUCER_INTERFACE,
    REQUIRED_CLAUSES,
    admit_spar_accepted_root,
    subject_binding_cid,
    validate_subject,
)


def _subject() -> dict:
    return {
        "schema": "ipfs_accelerate_py/agent-supervisor/spar-accepted-root-subject@1",
        "profile_cid": "profile:sealed",
        "bootstrap_receipt_id": "bootstrap:sealed",
        "plan_root_cid": "plan:sealed",
        "board_namespace": "semantic-preserving-autonomous-remodularization-v1",
        "source_forest_root": "sha256:" + "a" * 64,
        "repository_tree_id": "b" * 40,
        "source_head": "c" * 40,
        "kit_transition_cid": "kit:transition",
        "kit_manifest_cid": "kit:manifest",
        "goal_cids": [f"goal:{i}" for i in range(32)],
        "goal_contract_cids": [f"contract:{i}" for i in range(32)],
        "task_cids": [f"task:{i}" for i in range(51)],
        "task_receipt_cids": [f"receipt:{i}" for i in range(51)],
        "semantic_acceptance_authority": False,
        "completion_authority": False,
    }


def test_valid_subject_without_clause_evidence_is_not_admitted():
    receipt = admit_spar_accepted_root(_subject())
    assert receipt["producer_interface"] == PRODUCER_INTERFACE
    assert receipt["admitted"] is False
    assert receipt["semantic_acceptance_authority"] is False
    assert receipt["reason"] == MODE_FLOORS
    assert all(receipt[name] is False for name in REQUIRED_CLAUSES)
    assert receipt["evidence_cids"] == []
    assert receipt["profile_cid"] == "profile:sealed"
    assert receipt["goal_cids"] == [f"goal:{i}" for i in range(32)]
    assert receipt["subject_cid"] == subject_binding_cid(validate_subject(_subject()))


def test_caller_supplied_accepted_boolean_cannot_admit_a_root():
    subject = _subject()
    subject["semantic_acceptance_authority"] = True
    receipt = admit_spar_accepted_root(subject)
    assert receipt["admitted"] is False
    assert "self-authorize" in receipt["error"]


def test_wrong_population_is_rejected():
    subject = _subject()
    subject["goal_cids"] = subject["goal_cids"][:-1]
    receipt = admit_spar_accepted_root(subject)
    assert receipt["admitted"] is False
    assert receipt["reason"] != ""


def test_validate_subject_rejects_duplicate_task_identities():
    subject = _subject()
    subject["task_cids"][1] = subject["task_cids"][0]
    try:
        validate_subject(subject)
    except Exception as exc:
        assert "unique" in str(exc)
    else:
        raise AssertionError("duplicate task identities were accepted")


def test_clause_outcome_injection_on_the_subject_is_ignored():
    subject = _subject()
    forged = copy.deepcopy(subject)
    # Extra keys make the subject not closed.
    forged["required_mode_roots_accepted"] = True
    receipt = admit_spar_accepted_root(forged)
    assert receipt["admitted"] is False
    assert receipt.get("required_mode_roots_accepted") is not True
