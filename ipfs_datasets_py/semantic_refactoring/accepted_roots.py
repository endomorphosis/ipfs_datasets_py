"""SPAR accepted-root producer. Missing clause evidence is not admission.

This module is the datasets-owned verifier for SPAR current-root acceptance.
It re-checks the sealed subject and independently classifies required clauses.
Worker booleans, nominated reports, and task counts cannot admit a root.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from typing import Any, Final

PRODUCER_INTERFACE: Final[str] = "SparAcceptedRootProducer@1"
SCHEMA: Final[str] = "ipfs-datasets.semantic-refactoring.spar-accepted-root@1"
SUBJECT_SCHEMA: Final[str] = (
    "ipfs_accelerate_py/agent-supervisor/spar-accepted-root-subject@1"
)
MISSING: Final[str] = (
    "datasets_independent_accepted_root_producer_and_admission_required"
)
MODE_FLOORS: Final[str] = (
    "required_mode_roots_safety_floors_capstone_fixed_point_acceptance_required"
)
REQUIRED_CLAUSES: Final[tuple[str, ...]] = (
    "required_mode_roots_accepted",
    "safety_floors_noncompensable_accepted",
    "self_hosted_capstone_accepted",
    "fixed_point_accepted",
)
REQUIRED_SUBJECT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema",
        "profile_cid",
        "bootstrap_receipt_id",
        "plan_root_cid",
        "board_namespace",
        "source_forest_root",
        "repository_tree_id",
        "source_head",
        "kit_transition_cid",
        "kit_manifest_cid",
        "goal_cids",
        "goal_contract_cids",
        "task_cids",
        "task_receipt_cids",
        "semantic_acceptance_authority",
        "completion_authority",
    }
)


class SparAcceptedRootError(ValueError):
    """Closed SPAR accepted-root subject or clause contract failed."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


_CID_PREFIX: Final[bytes] = b"\x01\xa9\x02\x12\x20"


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def subject_binding_cid(value: Mapping[str, Any]) -> str:
    """SPAR closeout subject binding CID; not semantic acceptance authority."""
    digest = hashlib.sha256(_canonical(dict(value))).digest()
    return "b" + base64.b32encode(_CID_PREFIX + digest).decode("ascii").rstrip("=").lower()


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise SparAcceptedRootError(f"{name} must be a nonempty string")
    return value


def _cid_list(value: Any, name: str, *, count: int) -> list[str]:
    if not isinstance(value, list) or len(value) != count:
        raise SparAcceptedRootError(f"{name} must contain exactly {count} entries")
    items = []
    for item in value:
        if type(item) is not str or not item.strip():
            raise SparAcceptedRootError(f"{name} entries must be nonempty strings")
        items.append(item)
    if len(set(items)) != count:
        raise SparAcceptedRootError(f"{name} identities must be unique")
    return items


def validate_subject(subject: Mapping[str, Any]) -> dict[str, Any]:
    """Reject malformed, self-authorizing, or population-changed SPAR subjects."""
    if not isinstance(subject, Mapping) or set(subject) != REQUIRED_SUBJECT_KEYS:
        raise SparAcceptedRootError("SPAR accepted-root subject is not closed")
    if subject.get("schema") != SUBJECT_SCHEMA:
        raise SparAcceptedRootError("SPAR accepted-root subject schema differs")
    if (
        subject.get("semantic_acceptance_authority") is not False
        or subject.get("completion_authority") is not False
    ):
        raise SparAcceptedRootError("SPAR subject cannot self-authorize acceptance")
    if subject.get("board_namespace") != (
        "semantic-preserving-autonomous-remodularization-v1"
    ):
        raise SparAcceptedRootError("SPAR subject board namespace differs")
    closed = {
        "schema": SUBJECT_SCHEMA,
        "profile_cid": _text(subject.get("profile_cid"), "profile_cid"),
        "bootstrap_receipt_id": _text(
            subject.get("bootstrap_receipt_id"), "bootstrap_receipt_id"
        ),
        "plan_root_cid": _text(subject.get("plan_root_cid"), "plan_root_cid"),
        "board_namespace": subject["board_namespace"],
        "source_forest_root": _text(
            subject.get("source_forest_root"), "source_forest_root"
        ),
        "repository_tree_id": _text(
            subject.get("repository_tree_id"), "repository_tree_id"
        ),
        "source_head": _text(subject.get("source_head"), "source_head"),
        "kit_transition_cid": _text(
            subject.get("kit_transition_cid"), "kit_transition_cid"
        ),
        "kit_manifest_cid": _text(subject.get("kit_manifest_cid"), "kit_manifest_cid"),
        "goal_cids": _cid_list(subject.get("goal_cids"), "goal_cids", count=32),
        "goal_contract_cids": _cid_list(
            subject.get("goal_contract_cids"), "goal_contract_cids", count=32
        ),
        "task_cids": _cid_list(subject.get("task_cids"), "task_cids", count=51),
        "task_receipt_cids": _cid_list(
            subject.get("task_receipt_cids"), "task_receipt_cids", count=51
        ),
        "semantic_acceptance_authority": False,
        "completion_authority": False,
    }
    return closed


def _clause_outcomes(subject: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Classify required SPAR clauses. Absence of current evidence is not success.

    Datasets can reconstruct semantic-state bundles and verify their blocks, but
    those APIs do not by themselves prove SPAR mode roots, noncompensable safety
    floors, self-hosted capstone, or fixed-point acceptance. Missing current
    clause records remain typed non-admission.
    """
    del subject
    missing = {
        "accepted": False,
        "reason": "current_source_clause_evidence_unavailable",
        "semantic_acceptance_authority": False,
    }
    return {name: dict(missing) for name in REQUIRED_CLAUSES}


def admit_spar_accepted_root(subject: Mapping[str, Any]) -> dict[str, Any]:
    """Independently admit or reject a SPAR accepted-root subject.

    Returns a closed receipt. ``admitted`` is true only when every required
    clause has independently verified current-source evidence. This function
    never copies a caller-supplied accepted boolean.
    """
    try:
        closed = validate_subject(subject)
    except SparAcceptedRootError as exc:
        return {
            "schema": SCHEMA,
            "admitted": False,
            "producer_interface": PRODUCER_INTERFACE,
            "semantic_acceptance_authority": False,
            "completion_authority": False,
            "reason": MISSING,
            "error": str(exc)[:512],
        }
    outcomes = _clause_outcomes(closed)
    clauses_accepted = all(row.get("accepted") is True for row in outcomes.values())
    evidence_cids = [
        row["evidence_cid"]
        for row in outcomes.values()
        if isinstance(row.get("evidence_cid"), str) and row["evidence_cid"]
    ]
    receipt = {
        "schema": SCHEMA,
        "admitted": False,
        "producer_interface": PRODUCER_INTERFACE,
        "semantic_acceptance_authority": False,
        "completion_authority": False,
        "profile_cid": closed["profile_cid"],
        "source_forest_root": closed["source_forest_root"],
        "kit_transition_cid": closed["kit_transition_cid"],
        "goal_cids": list(closed["goal_cids"]),
        "task_cids": list(closed["task_cids"]),
        "clause_outcomes": outcomes,
        "required_mode_roots_accepted": outcomes["required_mode_roots_accepted"][
            "accepted"
        ],
        "safety_floors_noncompensable_accepted": outcomes[
            "safety_floors_noncompensable_accepted"
        ]["accepted"],
        "self_hosted_capstone_accepted": outcomes["self_hosted_capstone_accepted"][
            "accepted"
        ],
        "fixed_point_accepted": outcomes["fixed_point_accepted"]["accepted"],
        "evidence_cids": evidence_cids,
        "subject_digest": _digest(closed),
        "subject_cid": subject_binding_cid(closed),
        "reason": MODE_FLOORS if not clauses_accepted else MISSING,
    }
    if (
        clauses_accepted
        and len(evidence_cids) == len(REQUIRED_CLAUSES)
        and all(outcomes[name]["accepted"] is True for name in REQUIRED_CLAUSES)
    ):
        # Unreachable until independent clause evidence exists. Kept as the
        # only success path so callers cannot inject an accepted boolean.
        receipt.update(
            admitted=True,
            semantic_acceptance_authority=True,
            accepted_root_cid=_digest(
                {
                    "subject_digest": receipt["subject_digest"],
                    "evidence_cids": evidence_cids,
                    "clause_outcomes": outcomes,
                }
            ),
            reason="",
        )
    return dict(receipt)


PROVIDER_FREE_EXPORTS: Final[tuple[str, ...]] = (
    "PRODUCER_INTERFACE",
    "SCHEMA",
    "admit_spar_accepted_root",
    "validate_subject",
)
