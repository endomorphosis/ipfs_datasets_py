"""Canonical datasets-owned primitives for MCP++ Profile G.

This module deliberately has no dependency on the MCP server.  It provides the
package-import provider described by Profile G section 10: canonical artifact
validation, contextual goal/plan validation, deterministic risk scoring,
durable risk-evidence storage, and signed neighborhood attestations.

Planning and placement are advisory.  In particular, :class:`GoalPlanValidator`
never treats a PlanBranch as actionable until a matching PlanSelection has
been checked against the configured Profile C and Profile D validators.
"""

from __future__ import annotations

import base64
import json
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from multiformats import CID, multihash

try:  # cryptography is an optional package dependency, required only to sign.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
except ImportError:  # pragma: no cover - exercised by minimal installations
    Ed25519PrivateKey = None  # type: ignore[assignment,misc]
    Ed25519PublicKey = None  # type: ignore[assignment,misc]


PROFILE_G_VERSION = "1.0"
PROFILE_G_CAPABILITY = "mcp++/risk-scheduling"
SAFE_INTEGER = 9_007_199_254_740_991
DEFAULT_LIMITS: dict[str, int] = {
    "max_artifact_bytes": 1_048_576,
    "max_parents": 32,
    "max_dependencies": 256,
    "max_evidence": 256,
    "max_neighbors": 64,
    "max_page_size": 1_000,
    "max_history_depth": 256,
    "min_lease_ms": 5_000,
    "max_lease_ms": 300_000,
}

_SCHEMAS = {
    "Goal": "goal",
    "Subgoal": "subgoal",
    "PlanBranch": "plan-branch",
    "PlanSelection": "plan-selection",
    "TaskSpec": "task",
    "RiskModel": "risk-model",
    "RiskEvidence": "risk-evidence",
    "RiskAssessment": "risk-assessment",
    "NeighborhoodRecord": "neighborhood-record",
    "NeighborhoodAttestation": "neighborhood-attestation",
    "ScheduleProposal": "schedule-proposal",
    "TaskClaim": "task-claim",
    "ClaimResolution": "claim-resolution",
    "TaskReceipt": "task-receipt",
}

_FIELDS = {
    "Goal": "owner_did objective_cid policy_cid parent_goal_cids labels",
    "Subgoal": "goal_cid parent_subgoal_cid objective_cid decomposition_method decomposer_cid selection_cid",
    "PlanBranch": "subgoal_cid candidate_input_cids task_template_cids evaluator_cid score_millionths explanation_cid",
    "PlanSelection": "subgoal_cid plan_branch_cid selector_did proof_cid policy_decision_cid reason_cid",
    "TaskSpec": "subgoal_cid plan_branch_cid selection_cid interface_cid input_cid tool dependency_task_cids idempotency_key resource_class deadline_ms expected_value_millionths max_attempts execution_mode",
    "RiskModel": "name version factor_names weight_millionths saturation_millionths algorithm missing_evidence max_history_events risk_buckets",
    "RiskEvidence": "subject_cid evidence_type observed_cids observer_did observed_at_ms expires_at_ms classification redacted_cid signer_did signature_alg signature",
    "RiskAssessment": "task_cid subject_did model_cid evidence_cids factor_millionths score_millionths confidence_millionths action assessed_at_ms expires_at_ms",
    "NeighborhoodRecord": "peer_did interface_cids resource_classes capacity_millionths health_evidence_cid trust_domain_cid reachable_artifact_cids valid_from_ms expires_at_ms signer_did signature_alg signature",
    "NeighborhoodAttestation": "proposal_cid attester_did record_cid verdict reason_code evidence_cid observed_epoch expires_at_ms signer_did signature_alg signature",
    "ScheduleProposal": "task_cid risk_assessment_cid selection_policy_cid policy_decision_cid logical_epoch priority_tuple candidates",
    "TaskClaim": "task_cid proposal_cid claimant_did record_cid logical_epoch requested_lease_ms risk_bucket capability_fit_millionths expected_finish_ms proof_cid policy_decision_cid attempt",
    "ClaimResolution": "task_cid logical_epoch considered_claim_cids accepted_claim_cid outcome fencing_token lease_expires_at_ms attestation_cids quorum_policy_cid policy_decision_cid coordination_receipt_cid retry_not_before_ms resolver_did",
    "TaskReceipt": "task_cid claim_cid resolution_cid fencing_token profile_b_receipt_cid output_cid status failure_class attempt started_at_ms finished_at_ms resource_use_cid provider provider_version next_state",
}

_EVIDENCE_TYPES = frozenset(
    {
        "policy-denial",
        "authority-failure",
        "obligation-overdue",
        "execution-failure",
        "timeout",
        "resource-overrun",
        "dispute",
        "rollback",
        "archive-inclusion",
        "capacity-health",
    }
)
_CLASSIFICATIONS = ("public", "trust-domain", "confidential", "restricted")


class ProfileGError(ValueError):
    """Stable Profile G error used by package and transports."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: str = "",
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path
        self.retryable = retryable
        self.details = dict(details or {})

    def to_error_data(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        details = dict(self.details)
        if self.path:
            details.setdefault("path", self.path)
        if details:
            result["details"] = details
        return result


def _fail(message: str, path: str = "", code: str = "G_INVALID_ARTIFACT") -> None:
    raise ProfileGError(code, message, path=path)


def canonical_profile_g_bytes(value: Any) -> bytes:
    """Return Profile G canonical DAG-JSON bytes after safe-integer checks."""

    def walk(item: Any, path: str = "") -> None:
        if item is None or isinstance(item, str | bool):
            return
        if isinstance(item, int):
            if not -SAFE_INTEGER <= item <= SAFE_INTEGER:
                _fail("integer is outside the JSON safe range", path)
            return
        if isinstance(item, float):
            _fail("floating point values are not canonical Profile G JSON", path)
        if isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{path}/{index}")
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    _fail("object keys must be strings", path)
                walk(child, f"{path}/{key}")
            return
        _fail("value is not representable as canonical JSON", path)

    walk(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def profile_g_cid(value: Any) -> str:
    """Compute CIDv1 DAG-JSON/sha2-256 for a Profile G value."""

    digest = multihash.digest(canonical_profile_g_bytes(value), "sha2-256")
    return str(CID("base32", 1, "dag-json", digest))


def _integer(value: Any, path: str, low: int = 0, high: int = SAFE_INTEGER) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        _fail(f"expected an integer in [{low}, {high}]", path)
    return value


def _string(value: Any, path: str, maximum: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\0" in value
        or len(value.encode("utf-8")) > maximum
    ):
        _fail(f"expected a non-empty string of at most {maximum} UTF-8 bytes", path)
    return value


def _enum(value: Any, path: str, values: Iterable[str]) -> str:
    result = _string(value, path)
    if result not in values:
        _fail("value is not in the allowed enumeration", path)
    return result


def _did(value: Any, path: str) -> str:
    result = _string(value, path)
    # DID Core: method names are lowercase alpha/digit and method-specific-id
    # cannot be empty.  URL suffixes are accepted and never interpreted here.
    import re

    if not re.fullmatch(r"did:[a-z0-9]+:[A-Za-z0-9._:%-]+(?:[/?#][^\x00]*)?", result):
        _fail("invalid absolute DID", path)
    return result


def _cid(value: Any, path: str) -> str:
    result = _string(value, path)
    if not result.startswith("b") or result.lower() != result:
        _fail("CID must use canonical lowercase base32", path)
    try:
        parsed = CID.decode(result)
    except Exception as error:
        raise ProfileGError("G_INVALID_ARTIFACT", "invalid CID", path=path) from error
    if parsed.version != 1 or parsed.hashfun.name != "sha2-256" or str(parsed) != result:
        _fail("CID must be canonical CIDv1/sha2-256", path)
    return result


def _array(value: Any, path: str, low: int, high: int) -> list[Any]:
    if not isinstance(value, list) or not low <= len(value) <= high:
        _fail(f"expected an array with {low}..{high} items", path)
    return value


def _sorted_set(
    value: Any,
    path: str,
    low: int,
    high: int,
    validator: Callable[[Any, str], Any],
) -> list[Any]:
    result = _array(value, path, low, high)
    for index, item in enumerate(result):
        validator(item, f"{path}/{index}")
    for index in range(1, len(result)):
        left = result[index - 1].encode("utf-8")
        right = result[index].encode("utf-8")
        if left >= right:
            _fail("set arrays must be sorted by UTF-8 bytes and unique", f"{path}/{index}")
    return result


def _cids(value: Any, path: str, low: int, high: int) -> list[str]:
    return _sorted_set(value, path, low, high, _cid)


def _millionths(value: Any, path: str) -> int:
    return _integer(value, path, 0, 1_000_000)


def validate_cid(value: Any, path: str = "/cid") -> str:
    """Validate a canonical CIDv1/sha2-256 link."""

    return _cid(value, path)


def validate_did(value: Any, path: str = "/did") -> str:
    """Validate an absolute DID string."""

    return _did(value, path)


def artifact_kind(artifact: Mapping[str, Any]) -> str:
    """Return the schema kind for an artifact, rejecting unknown schemas."""

    schema = artifact.get("schema")
    for kind, suffix in _SCHEMAS.items():
        if schema == f"mcp++/profile-g/{suffix}@1":
            return kind
    _fail("unknown Profile G artifact schema", "/schema")
    raise AssertionError("unreachable")


def validate_profile_g_artifact(
    kind: str,
    artifact: Mapping[str, Any],
    limits: Mapping[str, int] | None = None,
) -> str:
    """Strictly validate one Profile G artifact and return its canonical CID."""

    if kind not in _SCHEMAS:
        _fail("unknown Profile G artifact kind", "/kind")
    if not isinstance(artifact, Mapping):
        _fail("artifact must be an object")
    effective = {**DEFAULT_LIMITS, **dict(limits or {})}
    allowed = {"schema", "created_at_ms", "parents", "correlation_id"}
    allowed.update(_FIELDS[kind].split())
    unknown = set(artifact) - allowed
    if unknown:
        _fail("unknown field for schema major 1", f"/{sorted(unknown)[0]}")
    missing = allowed - set(artifact)
    if missing:
        _fail("required field is missing", f"/{sorted(missing)[0]}")
    if artifact["schema"] != f"mcp++/profile-g/{_SCHEMAS[kind]}@1":
        _fail("artifact schema does not match kind", "/schema")
    _integer(artifact["created_at_ms"], "/created_at_ms")
    _cids(artifact["parents"], "/parents", 0, effective["max_parents"])
    _string(artifact["correlation_id"], "/correlation_id", 128)
    _validate_specific(kind, artifact, effective)
    encoded = canonical_profile_g_bytes(dict(artifact))
    if len(encoded) > effective["max_artifact_bytes"]:
        _fail("artifact exceeds negotiated byte limit", code="G_LIMIT_EXCEEDED")
    return profile_g_cid(dict(artifact))


def validate_artifact(
    artifact: Mapping[str, Any], limits: Mapping[str, int] | None = None
) -> tuple[str, str]:
    """Infer the artifact kind, validate it, and return ``(kind, cid)``."""

    kind = artifact_kind(artifact)
    return kind, validate_profile_g_artifact(kind, artifact, limits)


def _validate_specific(kind: str, o: Mapping[str, Any], limits: Mapping[str, int]) -> None:
    def c(name: str) -> str:
        return _cid(o[name], f"/{name}")

    def d(name: str) -> str:
        return _did(o[name], f"/{name}")

    def i(name: str, low: int = 0, high: int = SAFE_INTEGER) -> int:
        return _integer(o[name], f"/{name}", low, high)

    def s(name: str, maximum: int = 4096) -> str:
        return _string(o[name], f"/{name}", maximum)

    if kind == "Goal":
        d("owner_did")
        c("objective_cid")
        c("policy_cid")
        _cids(o["parent_goal_cids"], "/parent_goal_cids", 0, 32)
        _sorted_set(o["labels"], "/labels", 0, 32, lambda x, p: _string(x, p, 64))
    elif kind == "Subgoal":
        c("goal_cid")
        if o["parent_subgoal_cid"] is not None:
            c("parent_subgoal_cid")
        c("objective_cid")
        s("decomposition_method", 128)
        c("decomposer_cid")
        if o["selection_cid"] is not None:
            c("selection_cid")
    elif kind == "PlanBranch":
        c("subgoal_cid")
        _cids(o["candidate_input_cids"], "/candidate_input_cids", 0, 64)
        _cids(o["task_template_cids"], "/task_template_cids", 1, 256)
        c("evaluator_cid")
        _millionths(o["score_millionths"], "/score_millionths")
        c("explanation_cid")
    elif kind == "PlanSelection":
        c("subgoal_cid")
        c("plan_branch_cid")
        d("selector_did")
        c("proof_cid")
        c("policy_decision_cid")
        c("reason_cid")
    elif kind == "TaskSpec":
        for name in "subgoal_cid plan_branch_cid selection_cid interface_cid input_cid".split():
            c(name)
        s("tool", 256)
        _cids(o["dependency_task_cids"], "/dependency_task_cids", 0, limits["max_dependencies"])
        s("idempotency_key", 128)
        s("resource_class", 128)
        if o["deadline_ms"] is not None:
            i("deadline_ms")
        _millionths(o["expected_value_millionths"], "/expected_value_millionths")
        i("max_attempts", 1, 100)
        _enum(o["execution_mode"], "/execution_mode", ("idempotent", "compensatable", "exclusive"))
    elif kind == "RiskModel":
        s("name")
        s("version")
        names = _sorted_set(
            o["factor_names"], "/factor_names", 1, 64, lambda x, p: _string(x, p, 128)
        )
        for field, low in (("weight_millionths", 0), ("saturation_millionths", 1)):
            values = o[field]
            if not isinstance(values, Mapping) or sorted(values) != names:
                _fail("factor map keys must exactly match factor_names", f"/{field}")
            for name in names:
                _integer(values[name], f"/{field}/{name}", low, 1_000_000)
        if not any(o["weight_millionths"].values()):
            _fail("at least one risk-model weight must be positive", "/weight_millionths")
        _enum(o["algorithm"], "/algorithm", ("weighted-saturated-sum-v1",))
        _enum(o["missing_evidence"], "/missing_evidence", ("deny", "challenge", "max-risk"))
        i("max_history_events", 1, limits["max_evidence"])
        buckets = _array(o["risk_buckets"], "/risk_buckets", 1, 64)
        previous = -1
        for index, value in enumerate(buckets):
            current = _millionths(value, f"/risk_buckets/{index}")
            if current <= previous:
                _fail("risk buckets must be strictly increasing", f"/risk_buckets/{index}")
            previous = current
        if buckets[-1] != 1_000_000:
            _fail("last risk bucket must be 1000000", "/risk_buckets")
    elif kind == "RiskEvidence":
        c("subject_cid")
        _enum(o["evidence_type"], "/evidence_type", _EVIDENCE_TYPES)
        _cids(o["observed_cids"], "/observed_cids", 1, limits["max_evidence"])
        d("observer_did")
        i("observed_at_ms")
        i("expires_at_ms")
        if o["expires_at_ms"] <= o["observed_at_ms"]:
            _fail("expiry must follow observation", "/expires_at_ms")
        _enum(o["classification"], "/classification", _CLASSIFICATIONS)
        if o["redacted_cid"] is not None:
            c("redacted_cid")
        d("signer_did")
        s("signature_alg", 128)
        s("signature")
    elif kind == "RiskAssessment":
        c("task_cid")
        d("subject_did")
        c("model_cid")
        _cids(o["evidence_cids"], "/evidence_cids", 0, limits["max_evidence"])
        if not isinstance(o["factor_millionths"], Mapping):
            _fail("factor_millionths must be an object", "/factor_millionths")
        for name, value in o["factor_millionths"].items():
            _string(name, "/factor_millionths")
            _millionths(value, f"/factor_millionths/{name}")
        _millionths(o["score_millionths"], "/score_millionths")
        _millionths(o["confidence_millionths"], "/confidence_millionths")
        _enum(o["action"], "/action", ("allow", "challenge", "review", "deny"))
        i("assessed_at_ms")
        i("expires_at_ms")
        if o["expires_at_ms"] <= o["assessed_at_ms"]:
            _fail("assessment expiry must follow assessment", "/expires_at_ms")
    elif kind == "NeighborhoodRecord":
        d("peer_did")
        _cids(o["interface_cids"], "/interface_cids", 1, 128)
        _sorted_set(
            o["resource_classes"], "/resource_classes", 1, 64, lambda x, p: _string(x, p, 128)
        )
        _millionths(o["capacity_millionths"], "/capacity_millionths")
        c("health_evidence_cid")
        c("trust_domain_cid")
        _cids(o["reachable_artifact_cids"], "/reachable_artifact_cids", 0, 128)
        i("valid_from_ms")
        i("expires_at_ms")
        if o["expires_at_ms"] <= o["valid_from_ms"]:
            _fail("record expiry must follow validity start", "/expires_at_ms")
        d("signer_did")
        s("signature_alg", 128)
        s("signature")
    elif kind == "NeighborhoodAttestation":
        c("proposal_cid")
        d("attester_did")
        c("record_cid")
        _enum(o["verdict"], "/verdict", ("support", "challenge", "abstain"))
        s("reason_code", 128)
        if o["evidence_cid"] is not None:
            c("evidence_cid")
        i("observed_epoch", 1)
        i("expires_at_ms")
        if o["expires_at_ms"] <= o["created_at_ms"]:
            _fail("attestation expiry must follow creation", "/expires_at_ms")
        d("signer_did")
        s("signature_alg", 128)
        s("signature")
        if o["signer_did"] != o["attester_did"]:
            _fail("attester and signer DID must match", "/signer_did")
    elif kind == "ScheduleProposal":
        for name in "task_cid risk_assessment_cid selection_policy_cid policy_decision_cid".split():
            c(name)
        i("logical_epoch", 1)
        priority = _array(o["priority_tuple"], "/priority_tuple", 8, 8)
        for index, value in enumerate(priority[:7]):
            _integer(value, f"/priority_tuple/{index}", -SAFE_INTEGER, SAFE_INTEGER)
        _cid(priority[7], "/priority_tuple/7")
        if priority[7] != o["task_cid"]:
            _fail("priority tuple task CID must match proposal", "/priority_tuple/7")
        candidates = _array(o["candidates"], "/candidates", 1, limits["max_neighbors"])
        previous = None
        for index, candidate in enumerate(candidates):
            path = f"/candidates/{index}"
            if not isinstance(candidate, Mapping) or set(candidate) != {
                "peer_did",
                "record_cid",
                "capability_fit_millionths",
                "expected_finish_ms",
                "risk_bucket",
            }:
                _fail("candidate has invalid fields", path)
            _did(candidate["peer_did"], f"{path}/peer_did")
            _cid(candidate["record_cid"], f"{path}/record_cid")
            _millionths(candidate["capability_fit_millionths"], f"{path}/capability_fit_millionths")
            _integer(candidate["expected_finish_ms"], f"{path}/expected_finish_ms")
            _integer(candidate["risk_bucket"], f"{path}/risk_bucket")
            key = candidate_order_key(candidate)
            if previous is not None and previous >= key:
                _fail("candidates are not in canonical ranked order", path)
            previous = key
    elif kind == "TaskClaim":
        c("task_cid")
        c("proposal_cid")
        d("claimant_did")
        c("record_cid")
        i("logical_epoch", 1)
        i("requested_lease_ms")
        if not limits["min_lease_ms"] <= o["requested_lease_ms"] <= limits["max_lease_ms"]:
            _fail(
                "requested lease is outside negotiated bounds",
                "/requested_lease_ms",
                "G_LIMIT_EXCEEDED",
            )
        i("risk_bucket")
        _millionths(o["capability_fit_millionths"], "/capability_fit_millionths")
        i("expected_finish_ms")
        c("proof_cid")
        c("policy_decision_cid")
        i("attempt", 1, 100)
    elif kind == "ClaimResolution":
        c("task_cid")
        i("logical_epoch", 1)
        _cids(o["considered_claim_cids"], "/considered_claim_cids", 1, limits["max_neighbors"])
        if o["accepted_claim_cid"] is not None:
            c("accepted_claim_cid")
        outcome = _enum(
            o["outcome"], "/outcome", ("accepted", "conflict", "released", "expired", "completed")
        )
        i("fencing_token", 1)
        if o["lease_expires_at_ms"] is not None:
            i("lease_expires_at_ms")
        if outcome == "accepted":
            if o["accepted_claim_cid"] is None or o["lease_expires_at_ms"] is None:
                _fail("accepted resolution requires claim and expiry", "/accepted_claim_cid")
        elif o["accepted_claim_cid"] is not None or o["lease_expires_at_ms"] is not None:
            _fail("non-accepted resolution cannot carry a lease", "/accepted_claim_cid")
        _cids(o["attestation_cids"], "/attestation_cids", 0, limits["max_neighbors"])
        c("quorum_policy_cid")
        c("policy_decision_cid")
        if o["coordination_receipt_cid"] is not None:
            c("coordination_receipt_cid")
        i("retry_not_before_ms")
        d("resolver_did")
    elif kind == "TaskReceipt":
        for name in "task_cid claim_cid resolution_cid".split():
            c(name)
        i("fencing_token", 1)
        c("profile_b_receipt_cid")
        if o["output_cid"] is not None:
            c("output_cid")
        status = _enum(o["status"], "/status", ("succeeded", "failed", "cancelled", "compensated"))
        failure = _enum(
            o["failure_class"],
            "/failure_class",
            ("none", "retryable", "permanent", "policy", "authority", "fenced", "resource"),
        )
        i("attempt", 1, 100)
        i("started_at_ms")
        i("finished_at_ms")
        if o["finished_at_ms"] < o["started_at_ms"]:
            _fail("finish precedes start", "/finished_at_ms")
        c("resource_use_cid")
        s("provider", 128)
        s("provider_version", 128)
        next_state = _enum(
            o["next_state"],
            "/next_state",
            ("complete", "ready", "blocked", "compensation-required"),
        )
        if status == "succeeded" and (
            o["output_cid"] is None or failure != "none" or next_state != "complete"
        ):
            _fail("successful receipt requires output, none failure, and complete state", "/status")


def candidate_order_key(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        candidate["risk_bucket"],
        -candidate["capability_fit_millionths"],
        candidate["expected_finish_ms"],
        candidate["peer_did"].encode("utf-8"),
        candidate["record_cid"].encode("utf-8"),
    )


def derive_priority_tuple(
    *,
    ready: bool,
    deadline_class: int,
    risk_action: str,
    age_bucket: int,
    expected_value_millionths: int,
    resource_fit_millionths: int,
    retry_not_before_ms: int,
    task_cid: str,
) -> list[Any]:
    """Build the canonical Profile G priority tuple."""

    _cid(task_cid, "/task_cid")
    if risk_action not in {"allow", "challenge", "review", "deny"}:
        _fail("invalid risk action", "/risk_action")
    return [
        0 if ready else 1,
        _integer(deadline_class, "/deadline_class"),
        {"allow": 0, "challenge": 1, "review": 2, "deny": 3}[risk_action],
        -_integer(age_bucket, "/age_bucket"),
        -_millionths(expected_value_millionths, "/expected_value_millionths"),
        -_millionths(resource_fit_millionths, "/resource_fit_millionths"),
        _integer(retry_not_before_ms, "/retry_not_before_ms"),
        task_cid,
    ]


def evaluate_risk_model(model: Mapping[str, Any], factors: Mapping[str, Any]) -> tuple[int, int]:
    """Evaluate ``weighted-saturated-sum-v1`` with integer-only arithmetic."""

    validate_profile_g_artifact("RiskModel", model)
    if set(factors) != set(model["factor_names"]):
        _fail("factor keys must exactly match the risk model", "/factor_millionths")
    weighted = 0
    total_weight = 0
    for name in model["factor_names"]:
        factor = _millionths(factors[name], f"/factor_millionths/{name}")
        weight = model["weight_millionths"][name]
        saturation = model["saturation_millionths"][name]
        saturated = min(1_000_000, factor * 1_000_000 // saturation)
        weighted += weight * saturated
        total_weight += weight
    score = min(1_000_000, weighted // total_weight)
    bucket = next(
        index for index, threshold in enumerate(model["risk_buckets"]) if score <= threshold
    )
    return score, bucket


ArtifactResolver = Callable[[str], Mapping[str, Any] | None]
DecisionValidator = Callable[[str, str, str], bool]


class GoalPlanValidator:
    """Contextual validator for goal decomposition, selection, and task links."""

    def __init__(
        self,
        resolver: ArtifactResolver,
        *,
        authority_validator: DecisionValidator | None = None,
        policy_validator: DecisionValidator | None = None,
        limits: Mapping[str, int] | None = None,
    ) -> None:
        self._resolve = resolver
        self._authority = authority_validator
        self._policy = policy_validator
        self._limits = {**DEFAULT_LIMITS, **dict(limits or {})}

    def validate_goal(self, goal: Mapping[str, Any]) -> str:
        cid = validate_profile_g_artifact("Goal", goal, self._limits)
        for parent_cid in goal["parent_goal_cids"]:
            self._require(parent_cid, "Goal", "/parent_goal_cids")
            self._assert_no_goal_cycle(cid, parent_cid)
        return cid

    def validate_decomposition(
        self, artifacts: Sequence[Mapping[str, Any]], goal_cid: str
    ) -> list[str]:
        """Validate a decomposition atomically without publishing any member."""

        _cid(goal_cid, "/goal_cid")
        self._require(goal_cid, "Goal", "/goal_cid")
        if (
            not isinstance(artifacts, Sequence)
            or isinstance(artifacts, str | bytes)
            or not artifacts
        ):
            _fail("decomposition must contain at least one artifact", "/artifacts")
        staged: dict[str, Mapping[str, Any]] = {}
        kinds: dict[str, str] = {}
        for index, artifact in enumerate(artifacts):
            kind, artifact_cid = validate_artifact(artifact, self._limits)
            if kind not in {"Subgoal", "PlanBranch"}:
                _fail(
                    "decomposition may only create Subgoal and PlanBranch artifacts",
                    f"/artifacts/{index}",
                )
            if artifact_cid in staged:
                _fail("duplicate decomposition artifact", f"/artifacts/{index}")
            staged[artifact_cid] = artifact
            kinds[artifact_cid] = kind

        def resolve(cid: str) -> Mapping[str, Any] | None:
            return staged.get(cid) or self._resolve(cid)

        for artifact_cid, artifact in staged.items():
            kind = kinds[artifact_cid]
            if kind == "Subgoal":
                if artifact["goal_cid"] != goal_cid:
                    _fail("subgoal belongs to a different goal", "/goal_cid", "G_CID_MISMATCH")
                parent = artifact["parent_subgoal_cid"]
                if parent is not None:
                    parent_artifact = resolve(parent)
                    if parent_artifact is None or artifact_kind(parent_artifact) != "Subgoal":
                        _fail(
                            "parent subgoal is missing or wrong type",
                            "/parent_subgoal_cid",
                            "G_CID_MISMATCH",
                        )
                    if parent_artifact["goal_cid"] != goal_cid:
                        _fail(
                            "parent subgoal belongs to another goal",
                            "/parent_subgoal_cid",
                            "G_CID_MISMATCH",
                        )
                    seen = {artifact_cid}
                    cursor = parent
                    for _ in range(self._limits["max_history_depth"]):
                        if cursor in seen:
                            _fail("subgoal ancestry contains a cycle", "/parent_subgoal_cid")
                        seen.add(cursor)
                        node = resolve(cursor)
                        if not node or node.get("parent_subgoal_cid") is None:
                            break
                        cursor = node["parent_subgoal_cid"]
                    else:
                        _fail(
                            "subgoal ancestry exceeds history bound",
                            "/parent_subgoal_cid",
                            "G_LIMIT_EXCEEDED",
                        )
                if artifact["selection_cid"] is not None:
                    _fail(
                        "new decomposition subgoals must remain unselected",
                        "/selection_cid",
                        "G_NOT_READY",
                    )
            else:
                subgoal = resolve(artifact["subgoal_cid"])
                if subgoal is None or artifact_kind(subgoal) != "Subgoal":
                    _fail(
                        "plan branch references a missing subgoal", "/subgoal_cid", "G_CID_MISMATCH"
                    )
                if subgoal["goal_cid"] != goal_cid:
                    _fail("plan branch belongs to another goal", "/subgoal_cid", "G_CID_MISMATCH")
        return list(staged)

    def validate_selection(self, selection: Mapping[str, Any]) -> str:
        selection_cid = validate_profile_g_artifact("PlanSelection", selection, self._limits)
        subgoal = self._require(selection["subgoal_cid"], "Subgoal", "/subgoal_cid")
        branch = self._require(selection["plan_branch_cid"], "PlanBranch", "/plan_branch_cid")
        if branch["subgoal_cid"] != selection["subgoal_cid"]:
            _fail("selection branch and subgoal do not match", "/plan_branch_cid", "G_CID_MISMATCH")
        existing = subgoal.get("selection_cid")
        if existing is not None and existing != selection_cid:
            _fail("subgoal already has a different selection", "/subgoal_cid", "G_CLAIM_CONFLICT")
        self._check_decisions(selection, "plan-selection")
        return selection_cid

    def validate_task(self, task: Mapping[str, Any], *, require_actionable: bool = True) -> str:
        task_cid = validate_profile_g_artifact("TaskSpec", task, self._limits)
        self._require(task["subgoal_cid"], "Subgoal", "/subgoal_cid")
        branch = self._require(task["plan_branch_cid"], "PlanBranch", "/plan_branch_cid")
        selection = self._require(task["selection_cid"], "PlanSelection", "/selection_cid")
        if branch["subgoal_cid"] != task["subgoal_cid"]:
            _fail("task branch does not match its subgoal", "/plan_branch_cid", "G_CID_MISMATCH")
        if (
            selection["subgoal_cid"] != task["subgoal_cid"]
            or selection["plan_branch_cid"] != task["plan_branch_cid"]
        ):
            _fail(
                "task selection does not select its exact branch", "/selection_cid", "G_NOT_READY"
            )
        if require_actionable:
            self._check_decisions(selection, "task")
        for dependency in task["dependency_task_cids"]:
            self._require(dependency, "TaskSpec", "/dependency_task_cids")
            if dependency == task_cid:
                _fail("task cannot depend on itself", "/dependency_task_cids")
        return task_cid

    def _check_decisions(self, artifact: Mapping[str, Any], purpose: str) -> None:
        proof = artifact["proof_cid"]
        policy = artifact["policy_decision_cid"]
        subject = profile_g_cid(dict(artifact))
        if self._authority is None or not self._authority(proof, subject, purpose):
            raise ProfileGError("G_AUTHORITY_DENIED", "Profile C authority did not validate")
        if self._policy is None or not self._policy(policy, subject, purpose):
            raise ProfileGError("G_POLICY_DENIED", "Profile D decision did not validate")

    def _require(self, cid: str, kind: str, path: str) -> Mapping[str, Any]:
        artifact = self._resolve(cid)
        if artifact is None:
            _fail("linked artifact is unavailable", path, "G_CID_MISMATCH")
        actual_kind, actual_cid = validate_artifact(artifact, self._limits)
        if actual_kind != kind or actual_cid != cid:
            _fail("linked artifact has the wrong CID or schema", path, "G_CID_MISMATCH")
        return artifact

    def _assert_no_goal_cycle(self, child_cid: str, parent_cid: str) -> None:
        frontier = [parent_cid]
        visited: set[str] = set()
        while frontier:
            if len(visited) >= self._limits["max_history_depth"]:
                _fail(
                    "goal ancestry exceeds history bound", "/parent_goal_cids", "G_LIMIT_EXCEEDED"
                )
            current = frontier.pop()
            if current == child_cid:
                _fail("goal ancestry contains a cycle", "/parent_goal_cids")
            if current in visited:
                continue
            visited.add(current)
            artifact = self._require(current, "Goal", "/parent_goal_cids")
            frontier.extend(artifact["parent_goal_cids"])


class RiskEvidenceStore:
    """Thread-safe SQLite artifact/evidence store with bounded deterministic reads."""

    def __init__(
        self,
        path: str | Path = ":memory:",
        *,
        limits: Mapping[str, int] | None = None,
        signature_verifier: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> None:
        self.limits = {**DEFAULT_LIMITS, **dict(limits or {})}
        self._verifier = signature_verifier
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._connection:
            self._connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS profile_g_artifacts (
                    cid TEXT PRIMARY KEY, kind TEXT NOT NULL, subject_cid TEXT,
                    observed_at_ms INTEGER, expires_at_ms INTEGER,
                    classification TEXT, artifact_json BLOB NOT NULL,
                    inserted_at_ms INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS profile_g_subject_history
                    ON profile_g_artifacts(subject_cid, observed_at_ms DESC, cid ASC);
                CREATE TABLE IF NOT EXISTS profile_g_idempotency (
                    caller_did TEXT NOT NULL, method TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL,
                    result_json BLOB NOT NULL,
                    PRIMARY KEY(caller_did, method, idempotency_key)
                );
            """)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def put(self, artifact: Mapping[str, Any], *, verify_signature: bool = True) -> str:
        return self.put_many([artifact], verify_signature=verify_signature)[0]

    def put_many(
        self, artifacts: Sequence[Mapping[str, Any]], *, verify_signature: bool = True
    ) -> list[str]:
        """Validate then atomically commit a group of artifacts."""

        prepared = []
        for artifact in artifacts:
            kind, cid = validate_artifact(artifact, self.limits)
            if kind in {"RiskEvidence", "NeighborhoodRecord", "NeighborhoodAttestation"}:
                if verify_signature and (self._verifier is None or not self._verifier(artifact)):
                    raise ProfileGError(
                        "G_EVIDENCE_INVALID", "artifact signature could not be verified"
                    )
            encoded = canonical_profile_g_bytes(dict(artifact))
            prepared.append(
                (
                    cid,
                    kind,
                    artifact.get("subject_cid", artifact.get("subgoal_cid")),
                    artifact.get("observed_at_ms", artifact.get("created_at_ms")),
                    artifact.get("expires_at_ms"),
                    artifact.get("classification", "public"),
                    encoded,
                    int(time.time() * 1000),
                )
            )
        with self._lock, self._connection:
            for row in prepared:
                existing = self._connection.execute(
                    "SELECT artifact_json FROM profile_g_artifacts WHERE cid = ?", (row[0],)
                ).fetchone()
                if existing is not None and bytes(existing[0]) != row[6]:
                    raise ProfileGError("G_CID_MISMATCH", "stored CID maps to different bytes")
            self._connection.executemany(
                "INSERT OR IGNORE INTO profile_g_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                prepared,
            )
        return [row[0] for row in prepared]

    def find_by_subject(self, kind: str, subject_cid: str) -> list[dict[str, Any]]:
        """Return a bounded deterministic set for an indexed artifact subject."""

        if kind not in _SCHEMAS:
            _fail("unknown artifact kind", "/kind")
        _cid(subject_cid, "/subject_cid")
        with self._lock:
            rows = self._connection.execute(
                "SELECT artifact_json FROM profile_g_artifacts "
                "WHERE kind = ? AND subject_cid = ? ORDER BY cid ASC LIMIT ?",
                (kind, subject_cid, self.limits["max_history_depth"] + 1),
            ).fetchall()
        if len(rows) > self.limits["max_history_depth"]:
            raise ProfileGError(
                "G_LIMIT_EXCEEDED", "subject history exceeds configured validation bound"
            )
        return [json.loads(bytes(row["artifact_json"])) for row in rows]

    def get(self, cid: str) -> dict[str, Any] | None:
        _cid(cid, "/cid")
        with self._lock:
            row = self._connection.execute(
                "SELECT artifact_json FROM profile_g_artifacts WHERE cid = ?", (cid,)
            ).fetchone()
        return json.loads(bytes(row[0])) if row else None

    def idempotency_get(
        self, caller_did: str, method: str, key: str, request_hash: str
    ) -> dict[str, Any] | None:
        """Return a prior result or reject reuse with different request bytes."""

        with self._lock:
            row = self._connection.execute(
                "SELECT request_hash, result_json FROM profile_g_idempotency "
                "WHERE caller_did = ? AND method = ? AND idempotency_key = ?",
                (caller_did, method, key),
            ).fetchone()
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise ProfileGError(
                "G_IDEMPOTENCY_CONFLICT",
                "idempotency key was reused with different request content",
            )
        result = json.loads(bytes(row["result_json"]))
        result["replayed"] = True
        return result

    def idempotency_put(
        self,
        caller_did: str,
        method: str,
        key: str,
        request_hash: str,
        result: Mapping[str, Any],
    ) -> None:
        encoded = canonical_profile_g_bytes(dict(result))
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO profile_g_idempotency VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(caller_did, method, idempotency_key) DO NOTHING",
                (caller_did, method, key, request_hash, encoded),
            )

    def list_kind(
        self, kind: str, *, limit: int = 100, cursor: str | None = None
    ) -> dict[str, Any]:
        if kind not in _SCHEMAS:
            _fail("unknown artifact kind", "/kind")
        limit = _integer(limit, "/limit", 1, self.limits["max_page_size"])
        after = self._decode_cursor(cursor, kind) if cursor else ""
        with self._lock:
            rows = self._connection.execute(
                "SELECT cid, artifact_json FROM profile_g_artifacts WHERE kind = ? AND cid > ? ORDER BY cid ASC LIMIT ?",
                (kind, after, limit + 1),
            ).fetchall()
        return self._page(rows, limit, kind)

    def evidence(
        self,
        subject_cid: str,
        *,
        at_ms: int | None = None,
        limit: int = 100,
        visible_classifications: Iterable[str] = ("public",),
        include_expired: bool = False,
    ) -> dict[str, Any]:
        _cid(subject_cid, "/subject_cid")
        instant = int(time.time() * 1000) if at_ms is None else _integer(at_ms, "/at_ms")
        limit = _integer(
            limit, "/limit", 1, min(self.limits["max_page_size"], self.limits["max_evidence"])
        )
        visible = frozenset(visible_classifications)
        if not visible.issubset(_CLASSIFICATIONS):
            _fail("unknown evidence classification", "/visible_classifications")
        with self._lock:
            rows = self._connection.execute(
                "SELECT cid, artifact_json, classification, expires_at_ms FROM profile_g_artifacts "
                "WHERE kind = 'RiskEvidence' AND subject_cid = ? "
                "ORDER BY observed_at_ms DESC, cid ASC LIMIT ?",
                (subject_cid, self.limits["max_evidence"] + 1),
            ).fetchall()
        items: list[dict[str, Any]] = []
        redacted: list[dict[str, Any]] = []
        for row in rows:
            if not include_expired and row["expires_at_ms"] <= instant:
                continue
            artifact = json.loads(bytes(row["artifact_json"]))
            if row["classification"] in visible:
                items.append({"artifact": artifact, "artifact_cid": row["cid"]})
            elif artifact.get("redacted_cid"):
                redacted.append(
                    {
                        "artifact_cid": row["cid"],
                        "redacted_cid": artifact["redacted_cid"],
                        "classification": row["classification"],
                    }
                )
        combined = items[:limit]
        truncated = len(items) > limit or len(rows) > self.limits["max_evidence"]
        return {
            "items": combined,
            "limit": limit,
            "next_cursor": None,
            "truncated": truncated,
            "archive_boundaries": [],
            "redacted": redacted[:limit],
        }

    def _page(self, rows: Sequence[sqlite3.Row], limit: int, scope: str) -> dict[str, Any]:
        selected = rows[:limit]
        more = len(rows) > limit
        return {
            "items": [
                {"artifact_cid": row["cid"], "artifact": json.loads(bytes(row["artifact_json"]))}
                for row in selected
            ],
            "limit": limit,
            "next_cursor": self._encode_cursor(scope, selected[-1]["cid"])
            if more and selected
            else None,
            "truncated": more,
            "archive_boundaries": [],
        }

    @staticmethod
    def _encode_cursor(scope: str, cid: str) -> str:
        data = canonical_profile_g_bytes({"scope": scope, "after": cid})
        return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str, scope: str) -> str:
        try:
            padded = cursor + "=" * ((4 - len(cursor) % 4) % 4)
            value = json.loads(base64.urlsafe_b64decode(padded))
            if value != {"scope": scope, "after": value.get("after")}:
                raise ValueError
            return _cid(value["after"], "/cursor")
        except Exception as error:
            raise ProfileGError(
                "G_INVALID_ARTIFACT", "invalid or mismatched cursor", path="/cursor"
            ) from error


def signing_cid(artifact: Mapping[str, Any]) -> str:
    """CID signed by Profile G detached-signature artifacts."""

    body = dict(artifact)
    body.pop("signature", None)
    return profile_g_cid(body)


@dataclass(frozen=True)
class Ed25519Signer:
    """Small detached Ed25519 signer for neighborhood/evidence artifacts."""

    did: str
    private_key: Any

    @classmethod
    def generate(cls, did: str) -> Ed25519Signer:
        _did(did, "/did")
        if Ed25519PrivateKey is None:
            raise RuntimeError("cryptography is required for Ed25519 attestations")
        return cls(did, Ed25519PrivateKey.generate())

    @property
    def public_key(self) -> Any:
        return self.private_key.public_key()

    def sign(self, artifact: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(artifact)
        result["signer_did"] = self.did
        result["signature_alg"] = "EdDSA"
        result["signature"] = "pending"
        digest_cid = signing_cid(result)
        signature = self.private_key.sign(digest_cid.encode("ascii"))
        result["signature"] = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
        return result


def verify_ed25519_artifact(artifact: Mapping[str, Any], resolver: Callable[[str], Any]) -> bool:
    """Verify a detached Ed25519 signature with a DID-to-key resolver."""

    try:
        if artifact.get("signature_alg") != "EdDSA":
            return False
        public_key = resolver(str(artifact["signer_did"]))
        if Ed25519PublicKey is not None and isinstance(public_key, bytes):
            public_key = Ed25519PublicKey.from_public_bytes(public_key)
        encoded = str(artifact["signature"])
        signature = base64.urlsafe_b64decode(encoded + "=" * ((4 - len(encoded) % 4) % 4))
        public_key.verify(signature, signing_cid(artifact).encode("ascii"))
        return True
    except Exception:
        return False


class NeighborhoodAttestationEngine:
    """Bounded, policy-filtered neighborhood query and attestation engine."""

    def __init__(
        self,
        store: RiskEvidenceStore,
        *,
        signer: Ed25519Signer | None = None,
        eligible_attesters: Iterable[str] = (),
        limits: Mapping[str, int] | None = None,
    ) -> None:
        self.store = store
        self.signer = signer
        self.eligible_attesters = frozenset(eligible_attesters)
        self.limits = {**DEFAULT_LIMITS, **dict(limits or {})}

    def query(
        self,
        *,
        interface_cid: str,
        resource_class: str,
        trust_domain_cid: str,
        required_artifact_cids: Sequence[str] = (),
        at_ms: int | None = None,
        limit: int = 64,
        policy_filter: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> dict[str, Any]:
        _cid(interface_cid, "/interface_cid")
        _string(resource_class, "/resource_class", 128)
        _cid(trust_domain_cid, "/trust_domain_cid")
        required = set(_cids(list(required_artifact_cids), "/required_artifact_cids", 0, 128))
        instant = int(time.time() * 1000) if at_ms is None else _integer(at_ms, "/at_ms")
        limit = _integer(limit, "/limit", 1, self.limits["max_neighbors"])
        records = self.store.list_kind("NeighborhoodRecord", limit=self.limits["max_page_size"])[
            "items"
        ]
        candidates = []
        for item in records:
            record = item["artifact"]
            if not record["valid_from_ms"] <= instant < record["expires_at_ms"]:
                continue
            if (
                interface_cid not in record["interface_cids"]
                or resource_class not in record["resource_classes"]
            ):
                continue
            if record["trust_domain_cid"] != trust_domain_cid:
                continue
            if not required.issubset(record["reachable_artifact_cids"]):
                continue
            if policy_filter is None or not policy_filter(record):
                continue
            candidates.append(item)
        candidates.sort(
            key=lambda item: (
                -item["artifact"]["capacity_millionths"],
                item["artifact"]["peer_did"].encode(),
                item["artifact_cid"].encode(),
            )
        )
        return {
            "items": candidates[:limit],
            "limit": limit,
            "next_cursor": None,
            "truncated": len(candidates) > limit,
            "archive_boundaries": [],
        }

    def attest(
        self,
        *,
        proposal_cid: str,
        record_cid: str,
        verdict: str,
        reason_code: str,
        observed_epoch: int,
        expires_at_ms: int,
        evidence_cid: str | None = None,
        parents: Sequence[str] = (),
        correlation_id: str,
        created_at_ms: int | None = None,
    ) -> tuple[dict[str, Any], str]:
        if self.signer is None:
            raise ProfileGError(
                "G_PROVIDER_UNAVAILABLE", "no attestation signing key is configured", retryable=True
            )
        if self.eligible_attesters and self.signer.did not in self.eligible_attesters:
            raise ProfileGError(
                "G_AUTHORITY_DENIED", "attester is not eligible under quorum policy"
            )
        record = self.store.get(record_cid)
        if record is None or artifact_kind(record) != "NeighborhoodRecord":
            raise ProfileGError("G_EVIDENCE_INVALID", "neighborhood record is unavailable")
        instant = int(time.time() * 1000) if created_at_ms is None else created_at_ms
        if not record["valid_from_ms"] <= instant < record["expires_at_ms"]:
            raise ProfileGError("G_LEASE_EXPIRED", "neighborhood record is not fresh")
        unsigned = {
            "schema": "mcp++/profile-g/neighborhood-attestation@1",
            "created_at_ms": instant,
            "parents": sorted(parents),
            "correlation_id": correlation_id,
            "proposal_cid": proposal_cid,
            "attester_did": self.signer.did,
            "record_cid": record_cid,
            "verdict": verdict,
            "reason_code": reason_code,
            "evidence_cid": evidence_cid,
            "observed_epoch": observed_epoch,
            "expires_at_ms": expires_at_ms,
        }
        artifact = self.signer.sign(unsigned)
        cid = validate_profile_g_artifact("NeighborhoodAttestation", artifact, self.limits)
        self.store.put(artifact)
        return artifact, cid

    def quorum(
        self,
        attestations: Sequence[Mapping[str, Any]],
        *,
        proposal_cid: str,
        threshold: int,
        at_ms: int | None = None,
        challenges_block: bool = True,
    ) -> dict[str, Any]:
        threshold = _integer(threshold, "/threshold", 1, self.limits["max_neighbors"])
        instant = int(time.time() * 1000) if at_ms is None else _integer(at_ms, "/at_ms")
        verdicts: dict[str, str] = {}
        cids: dict[str, str] = {}
        for artifact in attestations:
            cid = validate_profile_g_artifact("NeighborhoodAttestation", artifact, self.limits)
            if artifact["proposal_cid"] != proposal_cid or artifact["expires_at_ms"] <= instant:
                continue
            did = artifact["attester_did"]
            if self.eligible_attesters and did not in self.eligible_attesters:
                continue
            # One DID is one vote. Conflicting statements conservatively become challenge.
            prior = verdicts.get(did)
            verdicts[did] = (
                artifact["verdict"] if prior in (None, artifact["verdict"]) else "challenge"
            )
            cids[did] = min(cids.get(did, cid), cid)
        support = sorted(did for did, verdict in verdicts.items() if verdict == "support")
        challenges = sorted(did for did, verdict in verdicts.items() if verdict == "challenge")
        reached = len(support) >= threshold and (not challenges_block or not challenges)
        return {
            "reached": reached,
            "support_dids": support,
            "challenge_dids": challenges,
            "threshold": threshold,
            "attestation_cids": sorted(cids.values()),
        }


__all__ = [
    "DEFAULT_LIMITS",
    "Ed25519Signer",
    "GoalPlanValidator",
    "NeighborhoodAttestationEngine",
    "PROFILE_G_CAPABILITY",
    "PROFILE_G_VERSION",
    "ProfileGError",
    "RiskEvidenceStore",
    "artifact_kind",
    "canonical_profile_g_bytes",
    "candidate_order_key",
    "derive_priority_tuple",
    "evaluate_risk_model",
    "profile_g_cid",
    "signing_cid",
    "validate_artifact",
    "validate_cid",
    "validate_did",
    "validate_profile_g_artifact",
    "verify_ed25519_artifact",
]
