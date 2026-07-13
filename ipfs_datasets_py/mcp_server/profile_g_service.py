"""Datasets-owned MCP++ Profile G service and transport-neutral dispatcher."""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ipfs_datasets_py.logic.profile_g import (
    DEFAULT_LIMITS,
    PROFILE_G_VERSION,
    Ed25519Signer,
    GoalPlanValidator,
    NeighborhoodAttestationEngine,
    ProfileGError,
    RiskEvidenceStore,
    canonical_profile_g_bytes,
    evaluate_risk_model,
    profile_g_cid,
    validate_artifact,
    validate_cid,
    validate_did,
    validate_profile_g_artifact,
    verify_ed25519_artifact,
)

AuthorizationCheck = Callable[[str, str, str], bool]
RecordPolicyCheck = Callable[[Mapping[str, Any]], bool]

_ERROR_NUMBERS = {
    "G_INVALID_ARTIFACT": -32602,
    "G_CAPABILITY_NOT_NEGOTIATED": -32040,
    "G_CID_MISMATCH": -32041,
    "G_AUTHORITY_DENIED": -32042,
    "G_POLICY_DENIED": -32043,
    "G_NOT_READY": -32044,
    "G_IDEMPOTENCY_CONFLICT": -32045,
    "G_CLAIM_CONFLICT": -32046,
    "G_LEASE_EXPIRED": -32047,
    "G_QUORUM_UNAVAILABLE": -32049,
    "G_LIMIT_EXCEEDED": -32050,
    "G_PROVIDER_UNAVAILABLE": -32051,
    "G_EVIDENCE_INVALID": -32052,
    "G_REDACTED": -32053,
}

PROFILE_G_METHODS = (
    "mcp++/risk/profile", "mcp++/goals/create", "mcp++/goals/get", "mcp++/goals/list",
    "mcp++/goals/decompose", "mcp++/goals/select", "mcp++/tasks/create", "mcp++/tasks/get",
    "mcp++/tasks/list", "mcp++/tasks/ready", "mcp++/risk/assess", "mcp++/risk/evidence",
    "mcp++/risk/history", "mcp++/neighborhood/query", "mcp++/neighborhood/attest",
    "mcp++/schedule/frontier", "mcp++/schedule/status", "mcp++/schedule/propose",
    "mcp++/schedule/claim", "mcp++/schedule/renew", "mcp++/schedule/release",
    "mcp++/schedule/resolve", "mcp++/schedule/reconcile",
)
PROFILE_G_REST_BINDINGS = {
    "mcp++/risk/profile": ("GET", "/mcp/risk/profile"),
    "mcp++/goals/create": ("POST", "/mcp/goals"),
    "mcp++/goals/get": ("GET", "/mcp/goals/{cid}"),
    "mcp++/goals/list": ("GET", "/mcp/goals"),
    "mcp++/goals/decompose": ("POST", "/mcp/goals/{cid}/decompose"),
    "mcp++/goals/select": ("POST", "/mcp/goals/{cid}/select"),
    "mcp++/tasks/create": ("POST", "/mcp/tasks"),
    "mcp++/tasks/get": ("GET", "/mcp/tasks/{cid}"),
    "mcp++/tasks/list": ("GET", "/mcp/tasks"),
    "mcp++/tasks/ready": ("GET", "/mcp/tasks/ready"),
    "mcp++/risk/assess": ("POST", "/mcp/risk/assess"),
    "mcp++/risk/evidence": ("GET", "/mcp/risk/evidence"),
    "mcp++/risk/history": ("GET", "/mcp/risk/history"),
    "mcp++/neighborhood/query": ("POST", "/mcp/neighborhood/query"),
    "mcp++/neighborhood/attest": ("POST", "/mcp/neighborhood/attest"),
    "mcp++/schedule/frontier": ("GET", "/mcp/schedule/frontier"),
    "mcp++/schedule/status": ("GET", "/mcp/schedule/status/{task_cid}"),
    "mcp++/schedule/propose": ("POST", "/mcp/schedule/proposals"),
    "mcp++/schedule/claim": ("POST", "/mcp/schedule/claims"),
    "mcp++/schedule/renew": ("POST", "/mcp/schedule/claims/{claim_cid}/renew"),
    "mcp++/schedule/release": ("POST", "/mcp/schedule/claims/{claim_cid}/release"),
    "mcp++/schedule/resolve": ("POST", "/mcp/schedule/resolutions"),
    "mcp++/schedule/reconcile": ("POST", "/mcp/schedule/reconcile"),
}


class ProfileGService:
    """Stateful implementation of the datasets-owned Profile G operations.

    Profile C/D checks are injected and fail closed when absent.  Set
    ``trusted_local=True`` only for an already-authenticated in-process caller;
    network servers must supply real validators.
    """

    def __init__(
        self,
        *,
        store: RiskEvidenceStore | None = None,
        store_path: str | Path = ":memory:",
        authority_validator: AuthorizationCheck | None = None,
        policy_validator: AuthorizationCheck | None = None,
        record_policy_filter: RecordPolicyCheck | None = None,
        signer: Ed25519Signer | None = None,
        trusted_local: bool = False,
        limits: Mapping[str, int] | None = None,
    ) -> None:
        self.limits = {**DEFAULT_LIMITS, **dict(limits or {})}
        if trusted_local:
            authority_validator = authority_validator or (lambda _cid, _subject, _purpose: True)
            policy_validator = policy_validator or (lambda _cid, _subject, _purpose: True)
            record_policy_filter = record_policy_filter or (lambda _record: True)
        self.authority_validator = authority_validator
        self.policy_validator = policy_validator
        self.record_policy_filter = record_policy_filter
        self.signer = signer
        verifier = None
        if signer is not None:

            def verifier(artifact: Mapping[str, Any]) -> bool:
                return verify_ed25519_artifact(
                    artifact,
                    lambda did: signer.public_key if did == signer.did else None,
                )

        self.store = store or RiskEvidenceStore(
            store_path, limits=self.limits, signature_verifier=verifier
        )
        self.goal_validator = GoalPlanValidator(
            self.store.get,
            authority_validator=authority_validator,
            policy_validator=policy_validator,
            limits=self.limits,
        )
        self.neighborhood = NeighborhoodAttestationEngine(
            self.store, signer=signer, limits=self.limits
        )
        self._lock = threading.RLock()

    @property
    def profile(self) -> dict[str, Any]:
        models = self.store.list_kind("RiskModel", limit=self.limits["max_page_size"])["items"]
        descriptor = {
            "schema": "mcp++/profile-g/interface@1",
            "profile": "mcp++/risk-scheduling",
            "methods": [
                {"name": method, "http_method": PROFILE_G_REST_BINDINGS[method][0],
                 "rest_path": PROFILE_G_REST_BINDINGS[method][1]}
                for method in PROFILE_G_METHODS
            ],
        }
        return {
            "version": PROFILE_G_VERSION,
            "artifact_schema_major": 1,
            "risk_model_cids": [item["artifact_cid"] for item in models],
            "lease_clock": "unix-ms-with-logical-epoch",
            "limits": dict(self.limits),
            "transports": ["jsonrpc-http", "mcp+p2p"],
            "provider": "ipfs_datasets_py",
            "provider_version": "0.2.0",
            "contract_version": "1",
            "methods": list(PROFILE_G_METHODS),
            "interface_descriptor": descriptor,
            "interface_cid": profile_g_cid(descriptor),
        }

    def dispatch(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        """Dispatch one canonical JSON-RPC params object."""

        if not isinstance(params, Mapping):
            raise ProfileGError("G_INVALID_ARTIFACT", "params must be an object")
        if method == "mcp++/risk/profile":
            return self.profile
        reads = {
            "mcp++/goals/get": ("Goal", self._get),
            "mcp++/goals/list": ("Goal", self._list),
            "mcp++/tasks/get": ("TaskSpec", self._get),
            "mcp++/tasks/list": ("TaskSpec", self._list),
            "mcp++/tasks/ready": ("TaskSpec", self._ready),
        }
        if method in reads:
            kind, operation = reads[method]
            return operation(kind, params)
        if method in {"mcp++/risk/evidence", "mcp++/risk/history"}:
            return self._evidence(params)
        if method == "mcp++/neighborhood/query":
            return self._neighborhood_query(params)
        if method == "mcp++/schedule/frontier":
            return self._list("ScheduleProposal", params)
        if method == "mcp++/schedule/status":
            return self._status(params)

        mutations = {
            "mcp++/goals/create": self._create_goal,
            "mcp++/goals/decompose": self._decompose,
            "mcp++/goals/select": self._select,
            "mcp++/tasks/create": self._create_task,
            "mcp++/risk/assess": self._assess,
            "mcp++/neighborhood/attest": self._attest,
            "mcp++/schedule/propose": self._propose,
        }
        operation = mutations.get(method)
        if operation is None:
            raise ProfileGError(
                "G_PROVIDER_UNAVAILABLE",
                "operation belongs to the execution/lease provider and is not implemented by datasets",
                retryable=True,
                details={"method": method},
            )
        return self._idempotent(method, params, operation)

    def register_artifact(
        self, artifact: Mapping[str, Any], *, verify_signature: bool = True
    ) -> str:
        """Register a risk model, evidence item, or signed neighborhood record."""

        return self.store.put(artifact, verify_signature=verify_signature)

    def _idempotent(
        self,
        method: str,
        params: Mapping[str, Any],
        operation: Callable[[Mapping[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        caller = str(params.get("caller_did") or "")
        key = str(params.get("idempotency_key") or "")
        validate_did(caller, "/caller_did")
        if not key or "\0" in key or len(key.encode("utf-8")) > 128:
            raise ProfileGError(
                "G_INVALID_ARTIFACT", "invalid idempotency key", path="/idempotency_key"
            )
        correlation_id = params.get("correlation_id")
        if (
            not isinstance(correlation_id, str)
            or not correlation_id
            or "\0" in correlation_id
            or len(correlation_id.encode("utf-8")) > 128
        ):
            raise ProfileGError(
                "G_INVALID_ARTIFACT", "invalid correlation ID", path="/correlation_id"
            )
        parents = params.get("parents")
        if not isinstance(parents, list):
            raise ProfileGError(
                "G_INVALID_ARTIFACT", "mutation parents must be an array", path="/parents"
            )
        if len(parents) > self.limits["max_parents"]:
            raise ProfileGError(
                "G_LIMIT_EXCEEDED", "mutation parent set exceeds the bound", path="/parents"
            )
        for index, parent in enumerate(parents):
            validate_cid(parent, f"/parents/{index}")
        if parents != sorted(set(parents), key=lambda value: value.encode("utf-8")):
            raise ProfileGError(
                "G_INVALID_ARTIFACT", "parents must be sorted and unique", path="/parents"
            )
        validate_cid(params.get("proof_cid"), "/proof_cid")
        validate_cid(params.get("policy_decision_cid"), "/policy_decision_cid")
        request_hash = (
            "sha256:" + hashlib.sha256(canonical_profile_g_bytes(dict(params))).hexdigest()
        )
        prior = self.store.idempotency_get(caller, method, key, request_hash)
        if prior is not None:
            return prior
        result = operation(params)
        result.setdefault("replayed", False)
        self.store.idempotency_put(caller, method, key, request_hash, result)
        return result

    def _authorize(self, params: Mapping[str, Any], subject: str, purpose: str) -> None:
        proof = str(params.get("proof_cid") or "")
        decision = str(params.get("policy_decision_cid") or "")
        if self.authority_validator is None or not self.authority_validator(
            proof, subject, purpose
        ):
            raise ProfileGError("G_AUTHORITY_DENIED", "Profile C authority did not validate")
        if self.policy_validator is None or not self.policy_validator(decision, subject, purpose):
            raise ProfileGError("G_POLICY_DENIED", "Profile D decision did not validate")

    def _artifact_param(self, params: Mapping[str, Any]) -> Mapping[str, Any]:
        artifact = params.get("artifact")
        if not isinstance(artifact, Mapping):
            raise ProfileGError(
                "G_INVALID_ARTIFACT", "artifact must be an object", path="/artifact"
            )
        return artifact

    def _check_claimed_cid(self, params: Mapping[str, Any], cid: str) -> None:
        claimed = params.get("artifact_cid")
        if claimed is not None and claimed != cid:
            raise ProfileGError(
                "G_CID_MISMATCH", "supplied artifact CID does not match canonical bytes"
            )

    def _create_goal(self, params: Mapping[str, Any]) -> dict[str, Any]:
        artifact = self._artifact_param(params)
        cid = self.goal_validator.validate_goal(artifact)
        self._check_claimed_cid(params, cid)
        self._authorize(params, cid, "goal-create")
        self.store.put(artifact, verify_signature=False)
        return self._mutation_result(artifact, cid, "goal_created")

    def _decompose(self, params: Mapping[str, Any]) -> dict[str, Any]:
        goal_cid = str(params.get("goal_cid") or "")
        artifacts = params.get("artifacts")
        if not isinstance(artifacts, list):
            raise ProfileGError("G_INVALID_ARTIFACT", "artifacts must be an array")
        cids = self.goal_validator.validate_decomposition(artifacts, goal_cid)
        subject = profile_g_cid({"goal_cid": goal_cid, "artifact_cids": cids})
        self._authorize(params, subject, "goal-decompose")
        self.store.put_many(artifacts, verify_signature=False)
        events = [
            self._event_cid("goal_decomposed" if index == 0 else "plan_branch_proposed", cid)
            for index, cid in enumerate(cids)
        ]
        return {
            "artifacts": list(artifacts),
            "artifact_cids": cids,
            "event_cids": events,
            "replayed": False,
        }

    def _select(self, params: Mapping[str, Any]) -> dict[str, Any]:
        artifact = self._artifact_param(params)
        cid = self.goal_validator.validate_selection(artifact)
        self._check_claimed_cid(params, cid)
        self._authorize(params, cid, "goal-select")
        with self._lock:
            previous_artifacts = self.store.find_by_subject(
                "PlanSelection", artifact["subgoal_cid"]
            )
            previous = profile_g_cid(previous_artifacts[0]) if previous_artifacts else None
            if previous is not None and previous != cid:
                raise ProfileGError(
                    "G_CLAIM_CONFLICT",
                    "subgoal already has a selected branch",
                    details={"selection_cid": previous},
                )
            self.store.put(artifact, verify_signature=False)
        return self._mutation_result(artifact, cid, "plan_branch_selected")

    def _create_task(self, params: Mapping[str, Any]) -> dict[str, Any]:
        artifact = self._artifact_param(params)
        cid = self.goal_validator.validate_task(artifact)
        committed_artifacts = self.store.find_by_subject("PlanSelection", artifact["subgoal_cid"])
        committed = profile_g_cid(committed_artifacts[0]) if committed_artifacts else None
        if committed != artifact["selection_cid"]:
            raise ProfileGError("G_NOT_READY", "task references an unselected ToT branch")
        self._check_claimed_cid(params, cid)
        self._authorize(params, cid, "task-create")
        self.store.put(artifact, verify_signature=False)
        return self._mutation_result(artifact, cid, "task_created")

    def _assess(self, params: Mapping[str, Any]) -> dict[str, Any]:
        artifact = self._artifact_param(params)
        model = params.get("model")
        if not isinstance(model, Mapping):
            model = self.store.get(str(artifact.get("model_cid") or ""))
        if not isinstance(model, Mapping):
            raise ProfileGError("G_EVIDENCE_INVALID", "risk model is unavailable")
        model_cid = validate_profile_g_artifact("RiskModel", model, self.limits)
        if artifact.get("model_cid") != model_cid:
            raise ProfileGError("G_CID_MISMATCH", "assessment model CID mismatch")
        score, _bucket = evaluate_risk_model(model, artifact.get("factor_millionths", {}))
        if artifact.get("score_millionths") != score:
            raise ProfileGError(
                "G_EVIDENCE_INVALID", "risk score is not reproducible from model and factors"
            )
        evidence = self.store.evidence(
            artifact["task_cid"],
            at_ms=artifact["assessed_at_ms"],
            limit=model["max_history_events"],
            visible_classifications=params.get("visible_classifications", ["public"]),
        )
        expected = sorted(item["artifact_cid"] for item in evidence["items"])
        if artifact["evidence_cids"] != expected:
            raise ProfileGError(
                "G_EVIDENCE_INVALID",
                "assessment evidence is not the deterministic bounded evidence set",
            )
        cid = validate_profile_g_artifact("RiskAssessment", artifact, self.limits)
        self._check_claimed_cid(params, cid)
        self._authorize(params, cid, "risk-assess")
        self.store.put(artifact, verify_signature=False)
        return self._mutation_result(artifact, cid, "risk_assessed")

    def _attest(self, params: Mapping[str, Any]) -> dict[str, Any]:
        proposal_cid = str(params.get("proposal_cid") or "")
        self._authorize(params, proposal_cid, "neighborhood-attest")
        artifact, cid = self.neighborhood.attest(
            proposal_cid=proposal_cid,
            record_cid=str(params.get("record_cid") or ""),
            verdict=str(params.get("verdict") or ""),
            reason_code=str(params.get("reason_code") or ""),
            observed_epoch=params.get("observed_epoch"),
            expires_at_ms=params.get("expires_at_ms"),
            evidence_cid=params.get("evidence_cid"),
            parents=params.get("parents", []),
            correlation_id=str(params.get("correlation_id") or ""),
            created_at_ms=params.get("created_at_ms"),
        )
        return self._mutation_result(artifact, cid, "neighborhood_attested")

    def _propose(self, params: Mapping[str, Any]) -> dict[str, Any]:
        artifact = self._artifact_param(params)
        cid = validate_profile_g_artifact("ScheduleProposal", artifact, self.limits)
        task = self.store.get(artifact["task_cid"])
        assessment = self.store.get(artifact["risk_assessment_cid"])
        if task is None or assessment is None:
            raise ProfileGError("G_NOT_READY", "task or risk assessment is unavailable")
        self.goal_validator.validate_task(task)
        if assessment.get("task_cid") != artifact["task_cid"]:
            raise ProfileGError("G_CID_MISMATCH", "risk assessment belongs to another task")
        if assessment.get("action") == "deny":
            raise ProfileGError("G_POLICY_DENIED", "denied risk assessment cannot be scheduled")
        for candidate in artifact["candidates"]:
            record = self.store.get(candidate["record_cid"])
            if record is None or record.get("peer_did") != candidate["peer_did"]:
                raise ProfileGError(
                    "G_EVIDENCE_INVALID", "candidate record is missing or mismatched"
                )
            if self.record_policy_filter is None or not self.record_policy_filter(record):
                raise ProfileGError("G_POLICY_DENIED", "candidate is not policy eligible")
            at_ms = artifact["created_at_ms"]
            if not record["valid_from_ms"] <= at_ms < record["expires_at_ms"]:
                raise ProfileGError("G_LEASE_EXPIRED", "candidate record is not fresh")
            if task["interface_cid"] not in record["interface_cids"]:
                raise ProfileGError("G_NOT_READY", "candidate lacks the task interface")
            if task["resource_class"] not in record["resource_classes"]:
                raise ProfileGError("G_NOT_READY", "candidate lacks the task resource class")
            if task["input_cid"] not in record["reachable_artifact_cids"]:
                raise ProfileGError("G_NOT_READY", "candidate cannot reach the task input")
        self._check_claimed_cid(params, cid)
        self._authorize(params, cid, "schedule-propose")
        self.store.put(artifact, verify_signature=False)
        return self._mutation_result(artifact, cid, "schedule_proposed")

    def _get(self, kind: str, params: Mapping[str, Any]) -> dict[str, Any]:
        cid = str(params.get("cid") or params.get("task_cid") or params.get("goal_cid") or "")
        artifact = self.store.get(cid)
        if artifact is None:
            raise ProfileGError("G_CID_MISMATCH", "artifact was not found")
        actual_kind, actual_cid = validate_artifact(artifact, self.limits)
        if actual_kind != kind or actual_cid != cid:
            raise ProfileGError("G_CID_MISMATCH", "artifact kind does not match request")
        return {"artifact": artifact, "artifact_cid": cid}

    def _list(self, kind: str, params: Mapping[str, Any]) -> dict[str, Any]:
        return self.store.list_kind(
            kind, limit=params.get("limit", 100), cursor=params.get("cursor")
        )

    def _ready(self, kind: str, params: Mapping[str, Any]) -> dict[str, Any]:
        page = self._list(kind, params)
        ready = []
        for item in page["items"]:
            try:
                self.goal_validator.validate_task(item["artifact"])
            except ProfileGError:
                continue
            ready.append(item)
        page["items"] = ready
        return page

    def _evidence(self, params: Mapping[str, Any]) -> dict[str, Any]:
        return self.store.evidence(
            str(params.get("subject_cid") or ""),
            at_ms=params.get("at_ms"),
            limit=params.get("limit", 100),
            visible_classifications=params.get("visible_classifications", ["public"]),
            include_expired=bool(params.get("include_expired", False)),
        )

    def _neighborhood_query(self, params: Mapping[str, Any]) -> dict[str, Any]:
        if self.record_policy_filter is None:
            raise ProfileGError(
                "G_POLICY_DENIED", "no neighborhood disclosure policy is configured"
            )
        return self.neighborhood.query(
            interface_cid=str(params.get("interface_cid") or ""),
            resource_class=str(params.get("resource_class") or ""),
            trust_domain_cid=str(params.get("trust_domain_cid") or ""),
            required_artifact_cids=params.get("required_artifact_cids", []),
            at_ms=params.get("at_ms"),
            limit=params.get("limit", 64),
            policy_filter=self.record_policy_filter,
        )

    def _status(self, params: Mapping[str, Any]) -> dict[str, Any]:
        task_cid = str(params.get("task_cid") or "")
        task = self.store.get(task_cid)
        if task is None:
            raise ProfileGError("G_CID_MISMATCH", "task was not found")
        proposals = self.store.list_kind("ScheduleProposal", limit=self.limits["max_page_size"])[
            "items"
        ]
        related = [item for item in proposals if item["artifact"]["task_cid"] == task_cid]
        related.sort(key=lambda item: (-item["artifact"]["logical_epoch"], item["artifact_cid"]))
        return {
            "task_cid": task_cid,
            "state": "proposed" if related else "ready",
            "proposal_cid": related[0]["artifact_cid"] if related else None,
            "logical_epoch": related[0]["artifact"]["logical_epoch"] if related else 0,
            "resolution_cid": None,
            "fencing_token": None,
        }

    @staticmethod
    def _event_cid(event_type: str, artifact_cid: str) -> str:
        return profile_g_cid(
            {
                "schema": "mcp++/profile-f/profile-g-event@1",
                "event_type": event_type,
                "artifact_cid": artifact_cid,
            }
        )

    def _mutation_result(
        self, artifact: Mapping[str, Any], cid: str, event_type: str
    ) -> dict[str, Any]:
        return {
            "artifact": dict(artifact),
            "artifact_cid": cid,
            "event_cid": self._event_cid(event_type, cid),
            "replayed": False,
        }


def profile_g_jsonrpc_error(request_id: Any, error: ProfileGError) -> dict[str, Any]:
    """Translate a package error to the normative JSON-RPC error contract."""

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": _ERROR_NUMBERS.get(error.code, -32603),
            "message": error.message,
            "data": error.to_error_data(),
        },
    }


_SERVICE: ProfileGService | None = None
_SERVICE_LOCK = threading.Lock()


def get_profile_g_service() -> ProfileGService:
    """Return the process service using a durable configured SQLite path."""

    global _SERVICE
    if _SERVICE is None:
        with _SERVICE_LOCK:
            if _SERVICE is None:
                path = os.environ.get("IPFS_DATASETS_PROFILE_G_DB", ":memory:")
                # Network deployments must replace these validators using
                # configure_profile_g_service before advertising the profile.
                _SERVICE = ProfileGService(store_path=path)
    return _SERVICE


def configure_profile_g_service(service: ProfileGService) -> None:
    global _SERVICE
    with _SERVICE_LOCK:
        _SERVICE = service


__all__ = [
    "ProfileGService",
    "configure_profile_g_service",
    "get_profile_g_service",
    "profile_g_jsonrpc_error",
    "PROFILE_G_METHODS",
    "PROFILE_G_REST_BINDINGS",
]
