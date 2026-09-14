"""Independent SPAR accepted-root producer. Missing evidence never becomes acceptance."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, Final

from ipfs_datasets_py.logic.software_verification.proof_carrying_artifact import (
    verify_proof_carrying_artifact,
)

PRODUCER_INTERFACE: Final[str] = "SparAcceptedRootProducer@1"
SCHEMA: Final[str] = "ipfs-datasets.semantic-refactoring.spar-accepted-root@1"
SUBJECT_SCHEMA: Final[str] = "ipfs_accelerate_py/agent-supervisor/spar-accepted-root-subject@1"
MODE_FLOORS: Final[str] = (
    "required_mode_roots_safety_floors_capstone_fixed_point_acceptance_required"
)
MISSING: Final[str] = "datasets_independent_accepted_root_producer_and_admission_required"
REQUIRED_CLAUSES: Final[tuple[str, ...]] = (
    "required_mode_roots_accepted",
    "safety_floors_noncompensable_accepted",
    "self_hosted_capstone_accepted",
    "fixed_point_accepted",
)
EXPECTED_GOALS: Final[int] = 32
EXPECTED_TASKS: Final[int] = 51
_CID_PREFIX: Final[bytes] = b"\x01\xa9\x02\x12\x20"
_CLAUSE_EVIDENCE_KEYS: Final[Mapping[str, str]] = {
    "required_mode_roots_accepted": "mode_roots_artifact",
    "safety_floors_noncompensable_accepted": "safety_floors_artifact",
    "self_hosted_capstone_accepted": "capstone_artifact",
    "fixed_point_accepted": "fixed_point_artifact",
}


def _canonical_json_bytes(value: Any) -> bytes:
    def check(item: Any) -> None:
        if item is None or isinstance(item, (str, bool, int)):
            return
        if isinstance(item, float):
            raise ValueError("SPAR accepted-root subject cannot contain floats")
        if isinstance(item, list):
            for child in item:
                check(child)
            return
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise ValueError("SPAR accepted-root subject keys must be strings")
            for child in item.values():
                check(child)
            return
        raise ValueError(f"unsupported SPAR accepted-root value: {type(item).__name__}")

    check(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def subject_binding_cid(subject: Mapping[str, Any]) -> str:
    """Binding CID matching the SPAR closeout subject encoder; not semantic authority."""
    digest = hashlib.sha256(_canonical_json_bytes(dict(subject))).digest()
    return "b" + base64.b32encode(_CID_PREFIX + digest).decode("ascii").rstrip("=").lower()


def _cid_list(value: Any, *, expected: int) -> list[str] | None:
    if not isinstance(value, list) or len(value) != expected:
        return None
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or "\x00" in item:
            return None
        out.append(item)
    if len(set(out)) != expected:
        return None
    return out


def _refuse(default_reason: str, subject: Mapping[str, Any], **extra: Any) -> dict[str, Any]:
    reason = extra.pop("reason", default_reason)
    result = {
        "schema": SCHEMA,
        "admitted": False,
        "producer_interface": PRODUCER_INTERFACE,
        "semantic_acceptance_authority": False,
        "completion_authority": False,
        "reason": reason,
        "subject_cid": extra.pop("subject_cid", None),
        "profile_cid": subject.get("profile_cid") if isinstance(subject.get("profile_cid"), str) else None,
        "source_forest_root": subject.get("source_forest_root")
        if isinstance(subject.get("source_forest_root"), str)
        else None,
        "evidence_cids": [],
    }
    for name in REQUIRED_CLAUSES:
        result[name] = False
    result.update(extra)
    return result


def _verify_clause_artifact(artifact: Any, *, expected_root: str) -> tuple[bool, str]:
    if not isinstance(artifact, Mapping):
        return False, ""
    verification = verify_proof_carrying_artifact(artifact)
    if not getattr(verification, "accepted", False):
        return False, ""
    roots = artifact.get("roots") if isinstance(artifact.get("roots"), Mapping) else {}
    tree_id = roots.get("tree_id") or roots.get("semantic_state_root")
    if not isinstance(tree_id, str) or tree_id != expected_root:
        return False, ""
    cid = artifact.get("artifact_cid")
    if not isinstance(cid, str) or not cid:
        return False, ""
    return True, cid


def admit_spar_accepted_root(subject: Mapping[str, Any]) -> dict[str, Any]:
    """Re-verify a SPAR closeout subject. Task counts and reports cannot admit."""
    if not isinstance(subject, Mapping):
        return _refuse(MISSING, {})
    if subject.get("schema") != SUBJECT_SCHEMA:
        return _refuse(MISSING, subject)
    if subject.get("semantic_acceptance_authority") is True:
        return _refuse(MISSING, subject, reason="subject_self_authorized")
    if subject.get("completion_authority") is True:
        return _refuse(MISSING, subject, reason="subject_completion_authority_forbidden")
    for banned in (
        "worker_approved",
        "test_pass",
        "vector_score",
        "model_output",
        "nomination_report",
        "final_root_accepted",
    ):
        if banned in subject:
            return _refuse(MISSING, subject, reason=f"forbidden_subject_field:{banned}")
    profile_cid = subject.get("profile_cid")
    forest = subject.get("source_forest_root")
    if not isinstance(profile_cid, str) or not profile_cid:
        return _refuse(MISSING, subject)
    if not isinstance(forest, str) or not forest:
        return _refuse(MISSING, subject)
    goals = _cid_list(subject.get("goal_cids"), expected=EXPECTED_GOALS)
    contracts = _cid_list(subject.get("goal_contract_cids"), expected=EXPECTED_GOALS)
    tasks = _cid_list(subject.get("task_cids"), expected=EXPECTED_TASKS)
    receipts = _cid_list(subject.get("task_receipt_cids"), expected=EXPECTED_TASKS)
    if goals is None or contracts is None or tasks is None or receipts is None:
        return _refuse(MISSING, subject, reason="sealed_population_incomplete")
    try:
        binding = subject_binding_cid(subject)
    except ValueError:
        return _refuse(MISSING, subject, reason="subject_not_canonical")
    artifacts = subject.get("clause_artifacts")
    clause_ok = {name: False for name in REQUIRED_CLAUSES}
    evidence: list[str] = []
    # Clause artifacts are not part of the SPAR adapter subject. If present they
    # change the binding CID, so live closeout cannot smuggle them. Tests may
    # still prove independent artifact verification fail-closed/pass paths.
    if isinstance(artifacts, Mapping):
        for clause, key in _CLAUSE_EVIDENCE_KEYS.items():
            ok, cid = _verify_clause_artifact(artifacts.get(key), expected_root=forest)
            clause_ok[clause] = ok
            if ok:
                evidence.append(cid)
    admitted = all(clause_ok.values()) and len(evidence) >= len(REQUIRED_CLAUSES)
    result = {
        "schema": SCHEMA,
        "admitted": admitted,
        "producer_interface": PRODUCER_INTERFACE,
        "semantic_acceptance_authority": admitted,
        "completion_authority": False,
        "subject_cid": binding,
        "profile_cid": profile_cid,
        "source_forest_root": forest,
        "accepted_root_cid": binding if admitted else None,
        "evidence_cids": evidence,
        "reason": None if admitted else MODE_FLOORS,
    }
    result.update(clause_ok)
    return result
