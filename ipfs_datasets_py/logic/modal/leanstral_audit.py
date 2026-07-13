"""Structured Leanstral audit contracts and content-addressed cache.

This module keeps Leanstral audit output machine-readable and reviewable.  A
cache hit is only usable when the cached response still matches the current
evidence, prompt, model, theorem registry, schemas, and local verifier result.
"""

from __future__ import annotations

import hashlib
import asyncio
import json
import math
import os
import time
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence


LEANSTRAL_AUDIT_REQUEST_SCHEMA_VERSION = "legal-ir-leanstral-audit-request-v1"
LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION = "legal-ir-leanstral-audit-response-v1"
LEANSTRAL_AUDIT_CACHE_SCHEMA_VERSION = "legal-ir-leanstral-audit-cache-v1"

LEANSTRAL_AUDIT_REQUEST_SCHEMA: Dict[str, Any] = {
    "schema_version": LEANSTRAL_AUDIT_REQUEST_SCHEMA_VERSION,
    "required": (
        "request_id",
        "evidence",
        "prompt",
        "model",
        "theorem_registry_hash",
        "proof_obligation_ids",
        "schema_hashes",
        "cache_key",
    ),
}
LEANSTRAL_AUDIT_RESPONSE_SCHEMA: Dict[str, Any] = {
    "schema_version": LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
    "required": (
        "schema_version",
        "request_id",
        "classification",
        "missing_semantic_rule",
        "counterexample",
        "witness",
        "affected_ir_families",
        "proposed_compiler_surface",
        "confidence",
        "proof_obligation_ids",
        "abstention_reason",
    ),
    "field_constraints": {
        "abstention_reason": (
            "Use null or an empty string unless classification is abstain; "
            "abstain requires a non-empty reason."
        ),
        "counterexample_or_witness": (
            "Every non-abstain response requires at least one non-null, "
            "evidence-grounded counterexample or witness."
        ),
        "proof_obligation_ids": "Use only IDs present in the request.",
        "proposed_compiler_surface": (
            "Every non-abstain response requires at least one non-empty object."
        ),
        "request_id": "Copy request.request_id exactly.",
    },
}

LEANSTRAL_AUDIT_REQUEST_SCHEMA_HASH = ""
LEANSTRAL_AUDIT_RESPONSE_SCHEMA_HASH = ""

ALLOWED_AUDIT_CLASSIFICATIONS = frozenset(
    {
        "abstain",
        "ambiguous_source_semantics",
        "counterexample_found",
        "incorrect_compiler_surface",
        "missing_semantic_rule",
        "no_issue",
        "proof_obligation_gap",
        "witness_confirmed",
    }
)

ISSUE_AUDIT_CLASSIFICATIONS = frozenset(
    {
        "ambiguous_source_semantics",
        "counterexample_found",
        "incorrect_compiler_surface",
        "missing_semantic_rule",
        "proof_obligation_gap",
    }
)

LLMGenerateFn = Callable[..., str]


LEANSTRAL_AUDIT_WORKER_SCHEMA_VERSION = "legal-ir-leanstral-audit-worker-v1"
LEANSTRAL_AUDIT_CHECKPOINT_SCHEMA_VERSION = "legal-ir-leanstral-audit-checkpoint-v1"


@dataclass(frozen=True)
class LeanstralAuditConfig:
    """Configuration for the structured Leanstral audit lane."""

    enabled: bool = False
    provider: str = "mistral_vibe"
    model: str = "Leanstral"
    vibe_agent: str = "lean"
    timeout_seconds: float = 300.0
    max_new_tokens: int = 1800
    cache_dir: Optional[str] = None

    def model_identity(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "provider": self.provider,
            "vibe_agent": self.vibe_agent,
        }

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LeanstralAuditWorkerConfig:
    """Bounded asynchronous worker controls for immutable disagreement streams."""

    max_concurrency: int = 2
    max_retries: int = 2
    request_timeout_seconds: float = 300.0
    retry_backoff_seconds: float = 0.25
    cache_dir: Optional[str] = None
    checkpoint_path: Optional[str] = None
    expected_state_hash: str = ""
    max_records: int = 0
    max_work_items: int = 0
    provider_enabled: bool = True
    provider: str = "mistral_vibe"
    model: str = "Leanstral"
    vibe_agent: str = "lean"
    prompt_template: str = "leanstral-async-disagreement-audit-v1"
    require_leanstral_model: bool = True

    def bounded_concurrency(self) -> int:
        return max(1, int(self.max_concurrency or 1))

    def bounded_retries(self) -> int:
        return max(0, int(self.max_retries or 0))

    def bounded_max_work_items(self) -> int:
        return max(0, int(self.max_work_items or 0))

    def timeout(self) -> float:
        value = float(self.request_timeout_seconds or 0.0)
        return value if math.isfinite(value) and value > 0.0 else 300.0

    def backoff(self) -> float:
        value = float(self.retry_backoff_seconds or 0.0)
        return max(0.0, value if math.isfinite(value) else 0.0)

    def model_identity(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "provider": self.provider,
            "vibe_agent": self.vibe_agent,
        }

    def runner_config(self) -> LeanstralAuditConfig:
        return LeanstralAuditConfig(
            enabled=bool(self.provider_enabled),
            provider=self.provider,
            model=self.model,
            vibe_agent=self.vibe_agent,
            timeout_seconds=self.timeout(),
            cache_dir=self.cache_dir,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LeanstralAuditRequest:
    """A deterministic, content-addressed audit request."""

    request_id: str
    evidence: Dict[str, Any]
    prompt: Dict[str, Any]
    model: Dict[str, Any]
    theorem_registry_hash: str
    proof_obligation_ids: Sequence[str]
    evidence_hash: str
    prompt_hash: str
    model_hash: str
    request_schema_hash: str
    response_schema_hash: str
    cache_key: str
    schema_version: str = LEANSTRAL_AUDIT_REQUEST_SCHEMA_VERSION

    @classmethod
    def build(
        cls,
        *,
        evidence: Mapping[str, Any],
        prompt: Mapping[str, Any] | str,
        model: Mapping[str, Any] | str,
        theorem_registry: Optional[Mapping[str, Any]] = None,
        theorem_registry_hash: Optional[str] = None,
        proof_obligation_ids: Sequence[str] = (),
        request_schema_hash: str = "",
        response_schema_hash: str = "",
    ) -> "LeanstralAuditRequest":
        """Build a request whose identity covers all cache-validity inputs."""

        normalized_evidence = _json_ready_mapping(evidence)
        normalized_prompt = (
            {"prompt": str(prompt)}
            if isinstance(prompt, str)
            else _json_ready_mapping(prompt)
        )
        normalized_model = (
            {"model": str(model)}
            if isinstance(model, str)
            else _json_ready_mapping(model)
        )
        if theorem_registry_hash is None:
            theorem_registry_hash = canonical_sha256(theorem_registry or {})
        else:
            theorem_registry_hash = _normalize_hash("theorem_registry_hash", theorem_registry_hash)
        request_schema_hash = request_schema_hash or LEANSTRAL_AUDIT_REQUEST_SCHEMA_HASH
        response_schema_hash = response_schema_hash or LEANSTRAL_AUDIT_RESPONSE_SCHEMA_HASH
        request_schema_hash = _normalize_hash("request_schema_hash", request_schema_hash)
        response_schema_hash = _normalize_hash("response_schema_hash", response_schema_hash)
        obligations = tuple(
            str(value).strip() for value in proof_obligation_ids if str(value).strip()
        )
        if not obligations:
            raise ValueError("Leanstral audit requests require proof_obligation_ids")
        evidence_hash = canonical_sha256(normalized_evidence)
        prompt_hash = canonical_sha256(normalized_prompt)
        model_hash = canonical_sha256(normalized_model)
        cache_key = build_leanstral_audit_cache_key(
            evidence_hash=evidence_hash,
            prompt_hash=prompt_hash,
            model_hash=model_hash,
            theorem_registry_hash=theorem_registry_hash,
            request_schema_hash=request_schema_hash,
            response_schema_hash=response_schema_hash,
        )
        request_id = "leanstral-audit-" + cache_key[:16]
        return cls(
            request_id=request_id,
            evidence=normalized_evidence,
            prompt=normalized_prompt,
            model=normalized_model,
            theorem_registry_hash=theorem_registry_hash,
            proof_obligation_ids=obligations,
            evidence_hash=evidence_hash,
            prompt_hash=prompt_hash,
            model_hash=model_hash,
            request_schema_hash=request_schema_hash,
            response_schema_hash=response_schema_hash,
            cache_key=cache_key,
        )

    @property
    def content_hash(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_prompt_payload(self) -> Dict[str, Any]:
        cluster = _json_ready_mapping(self.evidence.get("cluster"))
        semantic_family = str(cluster.get("semantic_family") or "legal_ir").strip()
        compiler_surface = str(cluster.get("compiler_surface") or "legal_ir.compiler").strip()
        return {
            "allowed_classifications": sorted(ALLOWED_AUDIT_CLASSIFICATIONS),
            "instructions": [
                "Return strict JSON only.",
                "Classify the legal-IR semantic audit using one allowed classification.",
                "Copy request.request_id exactly into response.request_id.",
                "For every non-abstain response, include a non-null counterexample or witness grounded in request evidence.",
                "For every non-abstain response, include at least one non-empty proposed_compiler_surface object.",
                "For issue findings, identify a non-empty missing_semantic_rule.",
                "Use only proof_obligation_ids from the request.",
                "For non-abstain responses, set abstention_reason to JSON null or an empty string, never the text 'None'.",
                "For abstain responses, set a non-empty abstention_reason and leave issue evidence fields empty.",
            ],
            "request": self.to_dict(),
            "response_schema": LEANSTRAL_AUDIT_RESPONSE_SCHEMA,
            "response_template": {
                "abstention_reason": None,
                "affected_ir_families": [semantic_family],
                "classification": "missing_semantic_rule",
                "confidence": 0.0,
                "counterexample": {
                    "evidence_id": "copy a relevant request evidence_id",
                    "observed": "describe the observed compiler behavior",
                    "expected": "describe the expected legal semantics",
                },
                "missing_semantic_rule": {
                    "description": "describe the missing deterministic semantic rule"
                },
                "proof_obligation_ids": list(self.proof_obligation_ids[:1]),
                "proposed_compiler_surface": [
                    {
                        "component": compiler_surface,
                        "operation": "describe the deterministic compiler or decompiler change",
                    }
                ],
                "request_id": self.request_id,
                "schema_version": LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
                "witness": None,
            },
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cache_key": self.cache_key,
            "evidence": dict(self.evidence),
            "evidence_hash": self.evidence_hash,
            "model": dict(self.model),
            "model_hash": self.model_hash,
            "prompt": dict(self.prompt),
            "prompt_hash": self.prompt_hash,
            "proof_obligation_ids": list(self.proof_obligation_ids),
            "request_id": self.request_id,
            "schema_hashes": {
                "request": self.request_schema_hash,
                "response": self.response_schema_hash,
            },
            "schema_version": self.schema_version,
            "theorem_registry_hash": self.theorem_registry_hash,
        }


@dataclass(frozen=True)
class LeanstralAuditResponse:
    """Machine-readable Leanstral audit response."""

    schema_version: str
    request_id: str
    classification: str
    missing_semantic_rule: Dict[str, Any]
    counterexample: Optional[Dict[str, Any]]
    witness: Optional[Dict[str, Any]]
    affected_ir_families: Sequence[str]
    proposed_compiler_surface: Sequence[Dict[str, Any]]
    confidence: float
    proof_obligation_ids: Sequence[str]
    abstention_reason: str = ""
    rationale: str = ""
    request_cache_key: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "LeanstralAuditResponse":
        families = _string_tuple(data.get("affected_ir_families"))
        obligations = _string_tuple(data.get("proof_obligation_ids"))
        surfaces = _mapping_tuple(data.get("proposed_compiler_surface"))
        counterexample = _optional_mapping(data.get("counterexample"))
        witness = _optional_mapping(data.get("witness"))
        confidence = data.get("confidence", 0.0)
        try:
            confidence_float = float(confidence)
        except (TypeError, ValueError):
            confidence_float = float("nan")
        return cls(
            schema_version=str(data.get("schema_version", "")).strip(),
            request_id=str(data.get("request_id", "")).strip(),
            classification=_normalize_token(data.get("classification")),
            missing_semantic_rule=_json_ready_mapping(
                data.get("missing_semantic_rule")
                if isinstance(data.get("missing_semantic_rule"), Mapping)
                else {"description": str(data.get("missing_semantic_rule", "")).strip()}
            ),
            counterexample=counterexample,
            witness=witness,
            affected_ir_families=families,
            proposed_compiler_surface=surfaces,
            confidence=confidence_float,
            proof_obligation_ids=obligations,
            abstention_reason=_normalize_optional_text(data.get("abstention_reason")),
            rationale=str(data.get("rationale", "")).strip(),
            request_cache_key=str(data.get("request_cache_key", "")).strip(),
        )

    @property
    def content_hash(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "abstention_reason": self.abstention_reason,
            "affected_ir_families": list(self.affected_ir_families),
            "classification": self.classification,
            "confidence": self.confidence,
            "counterexample": dict(self.counterexample) if self.counterexample else None,
            "missing_semantic_rule": dict(self.missing_semantic_rule),
            "proof_obligation_ids": list(self.proof_obligation_ids),
            "proposed_compiler_surface": [
                dict(surface) for surface in self.proposed_compiler_surface
            ],
            "rationale": self.rationale,
            "request_cache_key": self.request_cache_key,
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "witness": dict(self.witness) if self.witness else None,
        }


@dataclass(frozen=True)
class LeanstralAuditValidation:
    """Local verifier result for one structured audit response."""

    accepted: bool
    verified: bool
    reasons: Sequence[str] = field(default_factory=tuple)
    response_hash: str = ""
    cache_key: str = ""
    verified_by: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "cache_key": self.cache_key,
            "reasons": list(self.reasons),
            "response_hash": self.response_hash,
            "verified": self.verified,
            "verified_by": list(self.verified_by),
        }


@dataclass(frozen=True)
class LeanstralAuditCacheEntry:
    """Serialized cache record for a locally verified audit response."""

    schema_version: str
    cache_key: str
    request_hash: str
    response_hash: str
    request_schema_hash: str
    response_schema_hash: str
    validation: Dict[str, Any]
    response: LeanstralAuditResponse

    @classmethod
    def build(
        cls,
        request: LeanstralAuditRequest,
        response: LeanstralAuditResponse,
        validation: LeanstralAuditValidation,
    ) -> "LeanstralAuditCacheEntry":
        return cls(
            schema_version=LEANSTRAL_AUDIT_CACHE_SCHEMA_VERSION,
            cache_key=request.cache_key,
            request_hash=request.content_hash,
            response_hash=response.content_hash,
            request_schema_hash=request.request_schema_hash,
            response_schema_hash=request.response_schema_hash,
            validation=validation.to_dict(),
            response=response,
        )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "LeanstralAuditCacheEntry":
        response_data = data.get("response")
        if not isinstance(response_data, Mapping):
            raise ValueError("audit cache entry is missing response mapping")
        validation = data.get("validation")
        if not isinstance(validation, Mapping):
            raise ValueError("audit cache entry is missing validation mapping")
        return cls(
            schema_version=str(data.get("schema_version", "")).strip(),
            cache_key=str(data.get("cache_key", "")).strip(),
            request_hash=str(data.get("request_hash", "")).strip(),
            response_hash=str(data.get("response_hash", "")).strip(),
            request_schema_hash=str(data.get("request_schema_hash", "")).strip(),
            response_schema_hash=str(data.get("response_schema_hash", "")).strip(),
            validation=dict(validation),
            response=LeanstralAuditResponse.from_mapping(response_data),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cache_key": self.cache_key,
            "request_hash": self.request_hash,
            "request_schema_hash": self.request_schema_hash,
            "response": self.response.to_dict(),
            "response_hash": self.response_hash,
            "response_schema_hash": self.response_schema_hash,
            "schema_version": self.schema_version,
            "validation": dict(self.validation),
        }


@dataclass(frozen=True)
class LeanstralAuditResult:
    """End-to-end audit run result."""

    request: LeanstralAuditRequest
    response: Optional[LeanstralAuditResponse]
    validation: LeanstralAuditValidation
    llm_called: bool
    cache_hit: bool = False
    raw_response: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cache_hit": self.cache_hit,
            "llm_called": self.llm_called,
            "raw_response": self.raw_response,
            "request": self.request.to_dict(),
            "response": self.response.to_dict() if self.response else None,
            "validation": self.validation.to_dict(),
        }


@dataclass(frozen=True)
class LeanstralAuditWorkItem:
    """One deduplicated asynchronous audit job."""

    work_key: str
    request: LeanstralAuditRequest
    evidence_ids: Sequence[str]
    compiler_commit: str
    semantic_signature: str
    state_hashes: Sequence[str]
    source_record_hashes: Sequence[str]
    cluster: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEANSTRAL_AUDIT_WORKER_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cluster": _json_ready_mapping(self.cluster),
            "compiler_commit": self.compiler_commit,
            "evidence_ids": list(self.evidence_ids),
            "request": self.request.to_dict(),
            "schema_version": self.schema_version,
            "semantic_signature": self.semantic_signature,
            "source_record_hashes": list(self.source_record_hashes),
            "state_hashes": list(self.state_hashes),
            "work_key": self.work_key,
        }


@dataclass(frozen=True)
class LeanstralAuditWorkResult:
    """Final status for one asynchronous worker item."""

    work_key: str
    status: str
    request_id: str = ""
    cache_key: str = ""
    cache_hit: bool = False
    llm_called: bool = False
    attempts: int = 0
    reasons: Sequence[str] = field(default_factory=tuple)
    response_hash: str = ""
    validation: Optional[LeanstralAuditValidation] = None
    elapsed_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempts": int(self.attempts),
            "cache_hit": bool(self.cache_hit),
            "cache_key": self.cache_key,
            "elapsed_seconds": round(float(self.elapsed_seconds), 6),
            "llm_called": bool(self.llm_called),
            "reasons": list(self.reasons),
            "request_id": self.request_id,
            "response_hash": self.response_hash,
            "status": self.status,
            "validation": self.validation.to_dict() if self.validation else None,
            "work_key": self.work_key,
        }


@dataclass(frozen=True)
class LeanstralAuditCheckpoint:
    """Atomic worker checkpoint containing completed content-addressed work keys."""

    completed_work_keys: Sequence[str]
    source_digest: str
    results: Mapping[str, Any]
    schema_version: str = LEANSTRAL_AUDIT_CHECKPOINT_SCHEMA_VERSION
    updated_at: float = field(default_factory=time.time)

    @classmethod
    def empty(cls, *, source_digest: str = "") -> "LeanstralAuditCheckpoint":
        return cls(completed_work_keys=(), source_digest=source_digest, results={})

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "LeanstralAuditCheckpoint":
        if data.get("schema_version") != LEANSTRAL_AUDIT_CHECKPOINT_SCHEMA_VERSION:
            raise ValueError("unsupported Leanstral audit checkpoint schema")
        completed = _string_tuple(data.get("completed_work_keys"))
        results = data.get("results")
        if not isinstance(results, Mapping):
            results = {}
        return cls(
            completed_work_keys=completed,
            source_digest=str(data.get("source_digest") or ""),
            results=dict(results),
            updated_at=float(data.get("updated_at") or 0.0),
        )

    def with_result(
        self,
        result: LeanstralAuditWorkResult,
        *,
        source_digest: Optional[str] = None,
    ) -> "LeanstralAuditCheckpoint":
        completed = set(self.completed_work_keys)
        if result.status in {"accepted", "cache_hit", "rejected", "provider_disabled", "model_rejected"}:
            completed.add(result.work_key)
        next_results = dict(self.results)
        next_results[result.work_key] = result.to_dict()
        return LeanstralAuditCheckpoint(
            completed_work_keys=tuple(sorted(completed)),
            source_digest=self.source_digest if source_digest is None else source_digest,
            results=next_results,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "completed_work_keys": list(self.completed_work_keys),
            "results": _json_ready(self.results),
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "updated_at": round(float(self.updated_at), 6),
        }


@dataclass(frozen=True)
class LeanstralAuditWorkerSummary:
    """Machine-readable worker run summary."""

    schema_version: str
    source_record_count: int
    valid_record_count: int
    invalid_record_count: int
    work_item_count: int
    completed_count: int
    cache_hit_count: int
    llm_call_count: int
    rejected_count: int
    failed_count: int
    skipped_checkpoint_count: int
    checkpoint_path: str
    source_digest: str
    results: Sequence[LeanstralAuditWorkResult]
    schema_failures: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    stale_state_rejections: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    unavailable_count: int = 0
    runtime_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cache_hit_count": int(self.cache_hit_count),
            "checkpoint_path": self.checkpoint_path,
            "completed_count": int(self.completed_count),
            "failed_count": int(self.failed_count),
            "invalid_record_count": int(self.invalid_record_count),
            "llm_call_count": int(self.llm_call_count),
            "rejected_count": int(self.rejected_count),
            "results": [result.to_dict() for result in self.results],
            "runtime_seconds": round(float(self.runtime_seconds), 6),
            "schema_failures": [_json_ready_mapping(item) for item in self.schema_failures],
            "schema_version": self.schema_version,
            "skipped_checkpoint_count": int(self.skipped_checkpoint_count),
            "source_digest": self.source_digest,
            "source_record_count": int(self.source_record_count),
            "stale_state_rejections": [
                _json_ready_mapping(item) for item in self.stale_state_rejections
            ],
            "unavailable_count": int(self.unavailable_count),
            "valid_record_count": int(self.valid_record_count),
            "work_item_count": int(self.work_item_count),
        }


class LeanstralAuditCache:
    """Content-addressed cache for verified audit responses."""

    def __init__(self, directory: Optional[str | Path] = None) -> None:
        self.directory = Path(directory).expanduser() if directory else None
        self._memory: Dict[str, Dict[str, Any]] = {}
        if self.directory:
            self.directory.mkdir(parents=True, exist_ok=True)

    def put(
        self,
        request: LeanstralAuditRequest,
        response: LeanstralAuditResponse,
        validation: LeanstralAuditValidation,
    ) -> LeanstralAuditCacheEntry:
        entry = LeanstralAuditCacheEntry.build(request, response, validation)
        payload = entry.to_dict()
        self._memory[request.cache_key] = payload
        if self.directory:
            path = self._path_for_key(request.cache_key)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.directory,
                prefix=f".{request.cache_key}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
                handle.write("\n")
                temporary_path = Path(handle.name)
            os.replace(temporary_path, path)
        return entry

    def get_entry(self, request: LeanstralAuditRequest) -> Optional[LeanstralAuditCacheEntry]:
        payload = self._load_payload(request.cache_key)
        if payload is None:
            return None
        try:
            entry = LeanstralAuditCacheEntry.from_mapping(payload)
        except (TypeError, ValueError):
            return None
        if not cache_entry_is_current(request, entry):
            return None
        return entry

    def get_accepted_entry(
        self,
        request: LeanstralAuditRequest,
    ) -> Optional[LeanstralAuditCacheEntry]:
        entry = self.get_entry(request)
        if entry is None:
            return None
        if not _cache_validation_is_verified(entry.validation, request.cache_key):
            return None
        validation = validate_leanstral_audit_response(request, entry.response)
        if not validation.accepted or not validation.verified:
            return None
        if validation.response_hash != entry.response_hash:
            return None
        return entry

    def get_accepted(self, request: LeanstralAuditRequest) -> Optional[LeanstralAuditResponse]:
        entry = self.get_accepted_entry(request)
        return entry.response if entry else None

    def _path_for_key(self, cache_key: str) -> Path:
        if self.directory is None:
            raise ValueError("cache directory is not configured")
        return self.directory / f"{cache_key}.json"

    def _load_payload(self, cache_key: str) -> Optional[Dict[str, Any]]:
        if cache_key in self._memory:
            return dict(self._memory[cache_key])
        if self.directory is None:
            return None
        path = self._path_for_key(cache_key)
        if not path.is_file():
            return None
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, Mapping):
            return None
        normalized = dict(payload)
        self._memory[cache_key] = normalized
        return normalized


class LeanstralAuditRunner:
    """Run structured audits with verified cache admission."""

    def __init__(
        self,
        config: Optional[LeanstralAuditConfig] = None,
        *,
        llm_generate: Optional[LLMGenerateFn] = None,
        cache: Optional[LeanstralAuditCache] = None,
    ) -> None:
        self.config = config or LeanstralAuditConfig()
        self.llm_generate = llm_generate
        self.cache = cache or LeanstralAuditCache(self.config.cache_dir)

    def run(
        self,
        *,
        evidence: Mapping[str, Any],
        prompt: Mapping[str, Any] | str,
        theorem_registry: Optional[Mapping[str, Any]] = None,
        theorem_registry_hash: Optional[str] = None,
        proof_obligation_ids: Sequence[str],
    ) -> LeanstralAuditResult:
        request = LeanstralAuditRequest.build(
            evidence=evidence,
            prompt=prompt,
            model=self.config.model_identity(),
            theorem_registry=theorem_registry,
            theorem_registry_hash=theorem_registry_hash,
            proof_obligation_ids=proof_obligation_ids,
        )
        cached_entry = self.cache.get_accepted_entry(request)
        if cached_entry is not None:
            return LeanstralAuditResult(
                request=request,
                response=cached_entry.response,
                validation=validate_leanstral_audit_response(request, cached_entry.response),
                llm_called=False,
                cache_hit=True,
            )
        if not self.config.enabled:
            return LeanstralAuditResult(
                request=request,
                response=None,
                validation=LeanstralAuditValidation(
                    accepted=False,
                    verified=False,
                    reasons=("leanstral_audit_disabled",),
                    cache_key=request.cache_key,
                ),
                llm_called=False,
            )

        generate = self.llm_generate
        if generate is None:
            from ipfs_datasets_py import llm_router

            generate = llm_router.generate_text
        prompt_payload = json.dumps(
            request.to_prompt_payload(),
            ensure_ascii=True,
            sort_keys=True,
        )
        raw_response = generate(
            prompt_payload,
            provider=self.config.provider,
            model_name=self.config.model,
            allow_local_fallback=False,
            disable_model_retry=True,
            max_new_tokens=int(self.config.max_new_tokens),
            mistral_vibe_agent=self.config.vibe_agent,
            temperature=0.0,
            timeout=float(self.config.timeout_seconds),
        )
        response = parse_leanstral_audit_response(raw_response)
        validation = validate_leanstral_audit_response(request, response)
        if response is not None:
            self.cache.put(request, response, validation)
        return LeanstralAuditResult(
            request=request,
            response=response,
            validation=validation,
            llm_called=True,
            raw_response=raw_response,
        )


class LeanstralAuditWorker:
    """Consume disagreement packets without blocking the autoencoder loop."""

    def __init__(
        self,
        config: Optional[LeanstralAuditWorkerConfig] = None,
        *,
        audit_runner: Optional[LeanstralAuditRunner] = None,
        llm_generate: Optional[LLMGenerateFn] = None,
    ) -> None:
        self.config = config or LeanstralAuditWorkerConfig()
        self.runner = audit_runner or LeanstralAuditRunner(
            self.config.runner_config(),
            llm_generate=llm_generate,
        )

    async def run_paths(self, paths: Sequence[str | Path]) -> LeanstralAuditWorkerSummary:
        records, schema_failures, source_digest = load_leanstral_audit_disagreements(
            paths,
            max_records=self.config.max_records,
        )
        return await self.run_records(
            records,
            schema_failures=schema_failures,
            source_digest=source_digest,
        )

    async def run_records(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        schema_failures: Sequence[Mapping[str, Any]] = (),
        source_digest: str = "",
    ) -> LeanstralAuditWorkerSummary:
        started = time.monotonic()
        checkpoint, checkpoint_source_mismatch = load_leanstral_audit_checkpoint(
            self.config.checkpoint_path,
            source_digest=source_digest,
        )
        items, stale_rejections = build_leanstral_audit_work_items(
            records,
            config=self.config,
        )
        completed_keys = set(checkpoint.completed_work_keys)
        if checkpoint_source_mismatch:
            completed_keys = set()
            stale_rejections = tuple(stale_rejections) + (
                {
                    "reason": "checkpoint_source_digest_mismatch",
                    "checkpoint_source_digest": checkpoint.source_digest,
                    "current_source_digest": source_digest,
                },
            )
        pending = [item for item in items if item.work_key not in completed_keys]
        skipped = len(items) - len(pending)
        semaphore = asyncio.Semaphore(self.config.bounded_concurrency())
        checkpoint_state = checkpoint
        checkpoint_lock = asyncio.Lock()
        results: List[LeanstralAuditWorkResult] = []

        async def run_one(item: LeanstralAuditWorkItem) -> LeanstralAuditWorkResult:
            async with semaphore:
                result = await self._run_item(item)
                async with checkpoint_lock:
                    nonlocal checkpoint_state
                    checkpoint_state = checkpoint_state.with_result(
                        result,
                        source_digest=source_digest,
                    )
                    write_leanstral_audit_checkpoint(
                        self.config.checkpoint_path,
                        checkpoint_state,
                    )
                return result

        if pending:
            results = list(await asyncio.gather(*(run_one(item) for item in pending)))
        skipped_results = [
            _result_from_checkpoint(item.work_key, checkpoint.results.get(item.work_key))
            for item in items
            if item.work_key in completed_keys
        ]
        all_results = skipped_results + results
        runtime = time.monotonic() - started
        return LeanstralAuditWorkerSummary(
            schema_version=LEANSTRAL_AUDIT_WORKER_SCHEMA_VERSION,
            source_record_count=len(records) + len(schema_failures),
            valid_record_count=len(records),
            invalid_record_count=len(schema_failures),
            work_item_count=len(items),
            completed_count=sum(1 for result in all_results if result.status in {"accepted", "cache_hit"}),
            cache_hit_count=sum(1 for result in results if result.cache_hit),
            llm_call_count=sum(1 for result in results if result.llm_called),
            rejected_count=sum(1 for result in all_results if result.status in {"rejected", "provider_disabled", "model_rejected"}),
            failed_count=sum(1 for result in all_results if result.status in {"failed", "timeout"}),
            skipped_checkpoint_count=skipped,
            checkpoint_path=str(self.config.checkpoint_path or ""),
            source_digest=source_digest,
            results=tuple(all_results),
            schema_failures=tuple(schema_failures),
            stale_state_rejections=tuple(stale_rejections),
            unavailable_count=sum(1 for result in all_results if result.status == "unavailable"),
            runtime_seconds=runtime,
        )

    async def _run_item(self, item: LeanstralAuditWorkItem) -> LeanstralAuditWorkResult:
        started = time.monotonic()
        if self.config.require_leanstral_model and not _is_leanstral_model_identity(item.request.model):
            return _work_result(
                item,
                status="model_rejected",
                attempts=0,
                reasons=("non_leanstral_model_identity",),
                elapsed=time.monotonic() - started,
            )
        cached = self.runner.cache.get_accepted_entry(item.request)
        if cached is not None:
            return _work_result(
                item,
                status="cache_hit",
                attempts=0,
                reasons=(),
                cache_hit=True,
                llm_called=False,
                response_hash=cached.response_hash,
                validation=validate_leanstral_audit_response(item.request, cached.response),
                elapsed=time.monotonic() - started,
            )
        if not self.config.provider_enabled:
            return _work_result(
                item,
                status="provider_disabled",
                attempts=0,
                reasons=("provider_disabled_cache_miss",),
                elapsed=time.monotonic() - started,
            )

        attempts = 0
        last_reasons: tuple[str, ...] = ()
        for attempt in range(self.config.bounded_retries() + 1):
            attempts = attempt + 1
            try:
                audit_result = await asyncio.wait_for(
                    asyncio.to_thread(self._run_sync_item, item),
                    timeout=self.config.timeout(),
                )
            except asyncio.TimeoutError:
                last_reasons = ("leanstral_audit_timeout",)
            except Exception as exc:  # provider failures must fail closed
                unavailable_reason = _provider_unavailable_reason(exc)
                if unavailable_reason:
                    return _work_result(
                        item,
                        status="unavailable",
                        attempts=attempts,
                        reasons=(unavailable_reason,),
                        llm_called=True,
                        elapsed=time.monotonic() - started,
                    )
                last_reasons = (f"provider_error:{exc.__class__.__name__}",)
            else:
                status = (
                    "cache_hit"
                    if audit_result.cache_hit
                    else "accepted"
                    if audit_result.validation.accepted and audit_result.validation.verified
                    else "rejected"
                )
                return _work_result(
                    item,
                    status=status,
                    attempts=attempts,
                    reasons=audit_result.validation.reasons,
                    cache_hit=audit_result.cache_hit,
                    llm_called=audit_result.llm_called,
                    response_hash=audit_result.validation.response_hash,
                    validation=audit_result.validation,
                    elapsed=time.monotonic() - started,
                )
            if attempt < self.config.bounded_retries() and self.config.backoff() > 0.0:
                await asyncio.sleep(self.config.backoff() * (2**attempt))
        return _work_result(
            item,
            status="timeout" if "leanstral_audit_timeout" in last_reasons else "failed",
            attempts=attempts,
            reasons=last_reasons,
            llm_called=True,
            elapsed=time.monotonic() - started,
        )

    def _run_sync_item(self, item: LeanstralAuditWorkItem) -> LeanstralAuditResult:
        return self.runner.run(
            evidence=item.request.evidence,
            prompt=item.request.prompt,
            theorem_registry_hash=item.request.theorem_registry_hash,
            proof_obligation_ids=item.request.proof_obligation_ids,
        )


def load_leanstral_audit_disagreements(
    paths: Sequence[str | Path],
    *,
    max_records: int = 0,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
    """Load immutable disagreement JSON/JSONL inputs and return valid records."""

    records: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    source_fingerprints: List[Dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(str(path))
        files = (
            sorted(path.rglob("*.json")) + sorted(path.rglob("*.jsonl"))
            if path.is_dir()
            else [path]
        )
        for file_path in files:
            file_hash = _file_sha256(file_path)
            stat = file_path.stat()
            source_fingerprints.append(
                {
                    "path": str(file_path),
                    "sha256": file_hash,
                    "size": int(stat.st_size),
                }
            )
            for line_number, record in _records_from_json_file(file_path):
                if max_records and len(records) >= max_records:
                    break
                if not isinstance(record, Mapping):
                    failures.append(
                        {
                            "failures": ("non_mapping_record",),
                            "line": line_number,
                            "path": str(file_path),
                        }
                    )
                    continue
                root = _root_record(record)
                try:
                    from .introspection_export import validate_disagreement_packet

                    packet_failures = validate_disagreement_packet(root)
                except Exception as exc:  # pragma: no cover - defensive schema path
                    packet_failures = (f"schema_validator_error:{exc.__class__.__name__}",)
                if packet_failures:
                    failures.append(
                        {
                            "evidence_id": str(root.get("evidence_id") or ""),
                            "failures": tuple(packet_failures),
                            "line": line_number,
                            "path": str(file_path),
                        }
                    )
                    continue
                records.append(dict(root))
            if max_records and len(records) >= max_records:
                break
    source_digest = canonical_sha256(
        {
            "files": source_fingerprints,
            "record_count": len(records),
            "schema_failure_count": len(failures),
        }
    )
    return records, failures, source_digest


def build_leanstral_audit_work_items(
    records: Sequence[Mapping[str, Any]],
    *,
    config: Optional[LeanstralAuditWorkerConfig] = None,
) -> tuple[List[LeanstralAuditWorkItem], List[Dict[str, Any]]]:
    """Cluster and deduplicate records into content-addressed audit work."""

    cfg = config or LeanstralAuditWorkerConfig()
    if not records:
        return [], []
    from .introspection_analysis import (
        IntrospectionAnalysisConfig,
        IntrospectionAnalysisSchemaError,
        analyze_introspection_disagreements,
    )

    stale_rejections: List[Dict[str, Any]] = []
    filtered_records: List[Dict[str, Any]] = []
    expected_state_hash = str(cfg.expected_state_hash or "").strip()
    for record in records:
        state_hashes = _record_state_hashes(record)
        if expected_state_hash and expected_state_hash not in state_hashes:
            stale_rejections.append(
                {
                    "evidence_id": str(record.get("evidence_id") or ""),
                    "reason": "stale_state_hash",
                    "state_hashes": tuple(state_hashes),
                    "expected_state_hash": expected_state_hash,
                }
            )
            continue
        filtered_records.append(dict(record))
    if not filtered_records:
        return [], stale_rejections
    try:
        analysis = analyze_introspection_disagreements(
            filtered_records,
            config=IntrospectionAnalysisConfig(max_gaps_per_cluster=50),
        )
    except IntrospectionAnalysisSchemaError as exc:
        return [], stale_rejections + [
            {
                "reason": "analysis_schema_error",
                "message": str(exc),
            }
        ]
    record_index: Dict[str, Dict[str, Any]] = {
        str(record.get("evidence_id") or ""): dict(record)
        for record in filtered_records
        if str(record.get("evidence_id") or "")
    }
    items_by_key: Dict[str, LeanstralAuditWorkItem] = {}
    for cluster in analysis.clusters:
        cluster_records = [
            record_index[evidence_id]
            for evidence_id in cluster.evidence_ids
            if evidence_id in record_index
        ]
        if not cluster_records:
            continue
        request = _build_worker_audit_request(
            cluster,
            cluster_records,
            config=cfg,
        )
        compiler_commit = _records_compiler_commit(cluster_records)
        semantic_signature = str(cluster.semantic_signature)
        state_hashes = tuple(sorted({value for record in cluster_records for value in _record_state_hashes(record)}))
        source_record_hashes = tuple(canonical_sha256(record) for record in cluster_records)
        work_key = canonical_sha256(
            {
                "compiler_commit": compiler_commit,
                "evidence_hash": request.evidence_hash,
                "model_hash": request.model_hash,
                "prompt_hash": request.prompt_hash,
                "request_schema_hash": request.request_schema_hash,
                "response_schema_hash": request.response_schema_hash,
                "semantic_signature": semantic_signature,
                "theorem_registry_hash": request.theorem_registry_hash,
            }
        )
        items_by_key.setdefault(
            work_key,
            LeanstralAuditWorkItem(
                work_key=work_key,
                request=request,
                evidence_ids=tuple(cluster.evidence_ids),
                compiler_commit=compiler_commit,
                semantic_signature=semantic_signature,
                state_hashes=state_hashes,
                source_record_hashes=source_record_hashes,
                cluster=cluster.to_dict(include_gaps=True),
            ),
        )
    items = sorted(
        items_by_key.values(),
        key=lambda item: (
            item.compiler_commit,
            item.semantic_signature,
            item.work_key,
        ),
    )
    max_work_items = cfg.bounded_max_work_items()
    if max_work_items:
        items = items[:max_work_items]
    return items, stale_rejections


def load_leanstral_audit_checkpoint(
    path: Optional[str | Path],
    *,
    source_digest: str = "",
) -> tuple[LeanstralAuditCheckpoint, bool]:
    """Load a worker checkpoint and report whether it belongs to stale inputs."""

    if not path:
        return LeanstralAuditCheckpoint.empty(source_digest=source_digest), False
    checkpoint_path = Path(path).expanduser()
    if not checkpoint_path.is_file():
        return LeanstralAuditCheckpoint.empty(source_digest=source_digest), False
    try:
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        checkpoint = LeanstralAuditCheckpoint.from_mapping(payload)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return LeanstralAuditCheckpoint.empty(source_digest=source_digest), True
    mismatch = bool(checkpoint.source_digest and source_digest and checkpoint.source_digest != source_digest)
    return checkpoint, mismatch


def write_leanstral_audit_checkpoint(
    path: Optional[str | Path],
    checkpoint: LeanstralAuditCheckpoint,
) -> Optional[Path]:
    """Atomically write the worker checkpoint."""

    if not path:
        return None
    checkpoint_path = Path(path).expanduser()
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=checkpoint_path.parent,
        prefix=f".{checkpoint_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(checkpoint.to_dict(), handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")
        temporary_path = Path(handle.name)
    os.replace(temporary_path, checkpoint_path)
    return checkpoint_path


def build_leanstral_audit_cache_key(
    *,
    evidence_hash: str,
    prompt_hash: str,
    model_hash: str,
    theorem_registry_hash: str,
    request_schema_hash: str,
    response_schema_hash: str,
) -> str:
    """Return the cache key for one audit validity domain."""

    material = {
        "cache_schema_version": LEANSTRAL_AUDIT_CACHE_SCHEMA_VERSION,
        "evidence_hash": _normalize_hash("evidence_hash", evidence_hash),
        "model_hash": _normalize_hash("model_hash", model_hash),
        "prompt_hash": _normalize_hash("prompt_hash", prompt_hash),
        "request_schema_hash": _normalize_hash("request_schema_hash", request_schema_hash),
        "response_schema_hash": _normalize_hash("response_schema_hash", response_schema_hash),
        "theorem_registry_hash": _normalize_hash(
            "theorem_registry_hash",
            theorem_registry_hash,
        ),
    }
    return canonical_sha256(material)


def parse_leanstral_audit_response(response: str) -> Optional[LeanstralAuditResponse]:
    """Parse strict JSON Leanstral audit output."""

    raw = str(response or "").strip()
    if raw.startswith("```json") and raw.endswith("```"):
        raw = raw[len("```json") : -len("```")].strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, Mapping):
        return None
    return LeanstralAuditResponse.from_mapping(parsed)


def validate_leanstral_audit_response(
    request: LeanstralAuditRequest,
    response: Optional[LeanstralAuditResponse],
    *,
    verifier_id: str = "leanstral-audit-schema-v1",
) -> LeanstralAuditValidation:
    """Verify response shape, identity, and evidence-bearing fields."""

    if response is None:
        return LeanstralAuditValidation(
            accepted=False,
            verified=False,
            reasons=("invalid_json_audit_response",),
            cache_key=request.cache_key,
        )
    reasons: list[str] = []
    if response.schema_version != LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION:
        reasons.append("unexpected_schema_version")
    if response.request_id != request.request_id:
        reasons.append("request_id_mismatch")
    if response.request_cache_key and response.request_cache_key != request.cache_key:
        reasons.append("request_cache_key_mismatch")
    if response.classification not in ALLOWED_AUDIT_CLASSIFICATIONS:
        reasons.append("unsupported_classification")
    if not math.isfinite(response.confidence) or not (0.0 <= response.confidence <= 1.0):
        reasons.append("invalid_confidence")
    if not response.proof_obligation_ids:
        reasons.append("missing_proof_obligation_ids")
    unknown_obligations = [
        obligation
        for obligation in response.proof_obligation_ids
        if obligation not in set(request.proof_obligation_ids)
    ]
    if unknown_obligations:
        reasons.append("unknown_proof_obligation_id")
    if not response.affected_ir_families:
        reasons.append("missing_affected_ir_families")
    if response.classification == "abstain":
        if not response.abstention_reason:
            reasons.append("missing_abstention_reason")
    else:
        if response.abstention_reason:
            reasons.append("abstention_reason_for_non_abstention")
        if not response.counterexample and not response.witness:
            reasons.append("missing_counterexample_or_witness")
        if not response.proposed_compiler_surface:
            reasons.append("missing_proposed_compiler_surface")
    if response.classification in ISSUE_AUDIT_CLASSIFICATIONS:
        if not _mapping_has_content(response.missing_semantic_rule):
            reasons.append("missing_semantic_rule_required_for_issue")
    for surface in response.proposed_compiler_surface:
        if not _mapping_has_content(surface):
            reasons.append("empty_proposed_compiler_surface")
            break
    response_hash = response.content_hash
    accepted = not reasons
    return LeanstralAuditValidation(
        accepted=accepted,
        verified=accepted and bool(verifier_id),
        reasons=tuple(dict.fromkeys(reasons)),
        response_hash=response_hash,
        cache_key=request.cache_key,
        verified_by=(verifier_id,) if accepted and verifier_id else (),
    )


def cache_entry_is_current(
    request: LeanstralAuditRequest,
    entry: LeanstralAuditCacheEntry,
) -> bool:
    """Return True only when a cache entry still belongs to ``request``."""

    return (
        entry.schema_version == LEANSTRAL_AUDIT_CACHE_SCHEMA_VERSION
        and entry.cache_key == request.cache_key
        and entry.request_hash == request.content_hash
        and entry.request_schema_hash == request.request_schema_hash
        and entry.response_schema_hash == request.response_schema_hash
        and entry.response_hash == entry.response.content_hash
    )


def canonical_sha256(value: Any) -> str:
    canonical = json.dumps(
        _json_ready(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _cache_validation_is_verified(validation: Mapping[str, Any], cache_key: str) -> bool:
    return (
        bool(validation.get("accepted"))
        and bool(validation.get("verified"))
        and str(validation.get("cache_key", "")).strip() == cache_key
        and bool(validation.get("verified_by"))
    )


def _build_worker_audit_request(
    cluster: Any,
    records: Sequence[Mapping[str, Any]],
    *,
    config: LeanstralAuditWorkerConfig,
) -> LeanstralAuditRequest:
    proof_obligations = _worker_proof_obligation_ids(cluster)
    theorem_registry_hash = canonical_sha256(
        {
            "compiler_commit": _records_compiler_commit(records),
            "proof_obligation_ids": proof_obligations,
            "schema_version": "leanstral-async-audit-theorem-registry-v1",
            "semantic_family": str(getattr(cluster, "semantic_family", "")),
            "semantic_signature": str(getattr(cluster, "semantic_signature", "")),
        }
    )
    evidence = {
        "cluster": cluster.to_dict(include_gaps=True),
        "compiler_commit": _records_compiler_commit(records),
        "evidence_packets": [_compact_worker_packet(record) for record in records],
        "semantic_signature": str(getattr(cluster, "semantic_signature", "")),
        "source_record_hashes": [canonical_sha256(record) for record in records],
        "state_hashes": sorted({value for record in records for value in _record_state_hashes(record)}),
    }
    prompt = {
        "template": config.prompt_template,
        "instructions": [
            "Audit this LegalIR disagreement cluster asynchronously.",
            "Return only the structured Leanstral audit response JSON.",
            "Bind findings to evidence hashes, compiler commit, semantic signature, theorem obligations, and schema hashes.",
            "Echo request_id and proof obligation IDs exactly; do not invent identifiers.",
            "Use the cluster compiler_surface in a non-empty proposed_compiler_surface object for every non-abstain response.",
            "Set abstention_reason to JSON null for non-abstain responses.",
            "Do not use or describe a fallback model as Leanstral.",
        ],
    }
    return LeanstralAuditRequest.build(
        evidence=evidence,
        prompt=prompt,
        model=config.model_identity(),
        theorem_registry_hash=theorem_registry_hash,
        proof_obligation_ids=proof_obligations,
    )


def _compact_worker_packet(record: Mapping[str, Any]) -> Dict[str, Any]:
    root = _root_record(record)
    return {
        "anti_copy_evidence": _json_ready_mapping(root.get("anti_copy_evidence") or root.get("anti_copy")),
        "compiler_decompiler_metrics": _json_ready_mapping(root.get("compiler_decompiler_metrics")),
        "evidence_hashes": _json_ready_mapping(root.get("evidence_hashes")),
        "evidence_id": str(root.get("evidence_id") or ""),
        "legal_ir_views": _json_ready_mapping(root.get("legal_ir_views")),
        "learned_view_gaps": _json_ready_mapping(root.get("learned_view_gaps")),
        "proof_route_status": _json_ready_mapping(root.get("proof_route_status")),
        "run_context": _json_ready_mapping(root.get("run_context")),
        "sample_hashes": _json_ready_mapping(root.get("sample_hashes")),
        "schema_version": str(root.get("schema_version") or ""),
        "versions": _json_ready_mapping(root.get("versions")),
    }


def _worker_proof_obligation_ids(cluster: Any) -> tuple[str, ...]:
    material = canonical_sha256(
        {
            "compiler_surface": str(getattr(cluster, "compiler_surface", "")),
            "semantic_signature": str(getattr(cluster, "semantic_signature", "")),
        }
    )[:12]
    family = _normalize_token(getattr(cluster, "semantic_family", "legal_ir")).replace("_", "-")
    return (f"PO-async-{family}-{material}",)


def _records_compiler_commit(records: Sequence[Mapping[str, Any]]) -> str:
    commits = sorted(
        {
            str(_json_ready_mapping(record.get("run_context")).get("compiler_commit") or "").strip()
            for record in records
            if str(_json_ready_mapping(record.get("run_context")).get("compiler_commit") or "").strip()
        }
    )
    return ",".join(commits) if commits else "unknown"


def _record_state_hashes(record: Mapping[str, Any]) -> tuple[str, ...]:
    root = _root_record(record)
    context = _json_ready_mapping(root.get("run_context"))
    evidence_hashes = _json_ready_mapping(root.get("evidence_hashes"))
    values = [
        str(context.get("state_hash") or "").strip(),
        str(evidence_hashes.get("state_hash") or "").strip(),
    ]
    return tuple(sorted({value for value in values if value}))


def _root_record(record: Mapping[str, Any]) -> Dict[str, Any]:
    payload = record.get("payload")
    return dict(payload) if isinstance(payload, Mapping) else dict(record)


def _records_from_json_file(path: Path) -> Iterable[tuple[int, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                yield line_number, json.loads(line)
            except json.JSONDecodeError:
                yield line_number, {"_invalid_json": True}
        return
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        yield 1, {"_invalid_json": True}
        return
    if isinstance(data, list):
        for index, item in enumerate(data, start=1):
            yield index, item
        return
    if isinstance(data, Mapping):
        for key in ("packets", "records", "disagreements", "items"):
            value = data.get(key)
            if isinstance(value, list):
                for index, item in enumerate(value, start=1):
                    yield index, item
                return
        yield 1, data


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _work_result(
    item: LeanstralAuditWorkItem,
    *,
    status: str,
    attempts: int,
    reasons: Sequence[str],
    cache_hit: bool = False,
    llm_called: bool = False,
    response_hash: str = "",
    validation: Optional[LeanstralAuditValidation] = None,
    elapsed: float = 0.0,
) -> LeanstralAuditWorkResult:
    return LeanstralAuditWorkResult(
        work_key=item.work_key,
        status=status,
        request_id=item.request.request_id,
        cache_key=item.request.cache_key,
        cache_hit=cache_hit,
        llm_called=llm_called,
        attempts=attempts,
        reasons=tuple(reasons),
        response_hash=response_hash,
        validation=validation,
        elapsed_seconds=elapsed,
    )


def _result_from_checkpoint(work_key: str, data: Any) -> LeanstralAuditWorkResult:
    if not isinstance(data, Mapping):
        return LeanstralAuditWorkResult(
            work_key=work_key,
            status="checkpoint_skipped",
        )
    validation_data = data.get("validation")
    validation = None
    if isinstance(validation_data, Mapping):
        validation = LeanstralAuditValidation(
            accepted=bool(validation_data.get("accepted")),
            verified=bool(validation_data.get("verified")),
            reasons=_string_tuple(validation_data.get("reasons")),
            response_hash=str(validation_data.get("response_hash") or ""),
            cache_key=str(validation_data.get("cache_key") or ""),
            verified_by=_string_tuple(validation_data.get("verified_by")),
        )
    return LeanstralAuditWorkResult(
        work_key=work_key,
        status=str(data.get("status") or "checkpoint_skipped"),
        request_id=str(data.get("request_id") or ""),
        cache_key=str(data.get("cache_key") or ""),
        cache_hit=bool(data.get("cache_hit")),
        llm_called=bool(data.get("llm_called")),
        attempts=int(data.get("attempts") or 0),
        reasons=_string_tuple(data.get("reasons")),
        response_hash=str(data.get("response_hash") or ""),
        validation=validation,
        elapsed_seconds=float(data.get("elapsed_seconds") or 0.0),
    )


def _provider_unavailable_reason(exc: Exception) -> str:
    text = f"{exc.__class__.__name__}: {exc}".lower()
    if any(
        token in text
        for token in (
            "leanstral",
            "labs",
            "lab model",
            "permission",
            "unauthorized",
            "forbidden",
            "not available",
            "unavailable",
            "access",
            "404",
            "403",
        )
    ):
        return "leanstral_labs_model_unavailable"
    return ""


def _is_leanstral_model_identity(model: Mapping[str, Any]) -> bool:
    return str(model.get("model") or "").strip().lower() == "leanstral"


def _json_ready_mapping(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    normalized = _json_ready(value)
    return dict(normalized) if isinstance(normalized, Mapping) else {}


def _json_ready(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_ready(value.to_dict())
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, set):
        return [_json_ready(item) for item in sorted(value, key=str)]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    return str(value)


def _normalize_hash(name: str, value: str) -> str:
    normalized = str(value or "").strip().lower()
    if len(normalized) != 64:
        raise ValueError(f"{name} must be a 64-character sha256 hex string")
    try:
        int(normalized, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a sha256 hex string") from exc
    return normalized


def _normalize_token(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _normalize_optional_text(value: Any) -> str:
    if value is None:
        return ""
    normalized = str(value).strip()
    if normalized.lower() in {"none", "null", "n/a", "not applicable", "not_applicable"}:
        return ""
    return normalized


def _string_tuple(value: Any) -> Sequence[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(
        _normalize_token(item) if item != str(item).strip() else str(item).strip()
        for item in value
        if str(item).strip()
    )


def _mapping_tuple(value: Any) -> Sequence[Dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(_json_ready_mapping(item) for item in value if isinstance(item, Mapping))


def _optional_mapping(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    normalized = _json_ready_mapping(value)
    return normalized if _mapping_has_content(normalized) else None


def _mapping_has_content(value: Mapping[str, Any]) -> bool:
    for item in value.values():
        if isinstance(item, Mapping):
            if _mapping_has_content(item):
                return True
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            if len(item) > 0:
                return True
        elif str(item).strip():
            return True
    return False


LEANSTRAL_AUDIT_REQUEST_SCHEMA_HASH = canonical_sha256(LEANSTRAL_AUDIT_REQUEST_SCHEMA)
LEANSTRAL_AUDIT_RESPONSE_SCHEMA_HASH = canonical_sha256(LEANSTRAL_AUDIT_RESPONSE_SCHEMA)


__all__ = [
    "ALLOWED_AUDIT_CLASSIFICATIONS",
    "LEANSTRAL_AUDIT_CACHE_SCHEMA_VERSION",
    "LEANSTRAL_AUDIT_REQUEST_SCHEMA",
    "LEANSTRAL_AUDIT_REQUEST_SCHEMA_HASH",
    "LEANSTRAL_AUDIT_REQUEST_SCHEMA_VERSION",
    "LEANSTRAL_AUDIT_RESPONSE_SCHEMA",
    "LEANSTRAL_AUDIT_RESPONSE_SCHEMA_HASH",
    "LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION",
    "LEANSTRAL_AUDIT_CHECKPOINT_SCHEMA_VERSION",
    "LEANSTRAL_AUDIT_WORKER_SCHEMA_VERSION",
    "LeanstralAuditCache",
    "LeanstralAuditCacheEntry",
    "LeanstralAuditConfig",
    "LeanstralAuditCheckpoint",
    "LeanstralAuditRequest",
    "LeanstralAuditResponse",
    "LeanstralAuditResult",
    "LeanstralAuditRunner",
    "LeanstralAuditValidation",
    "LeanstralAuditWorker",
    "LeanstralAuditWorkerConfig",
    "LeanstralAuditWorkerSummary",
    "LeanstralAuditWorkItem",
    "LeanstralAuditWorkResult",
    "build_leanstral_audit_cache_key",
    "build_leanstral_audit_work_items",
    "cache_entry_is_current",
    "canonical_sha256",
    "load_leanstral_audit_checkpoint",
    "load_leanstral_audit_disagreements",
    "parse_leanstral_audit_response",
    "validate_leanstral_audit_response",
    "write_leanstral_audit_checkpoint",
]
