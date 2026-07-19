"""Structured Leanstral audit contracts and content-addressed cache.

This module keeps Leanstral audit output machine-readable and reviewable.  A
cache hit is only usable when the cached response still matches the current
evidence, prompt, model, theorem registry, schemas, and local verifier result.
"""

from __future__ import annotations

import hashlib
import errno
import json
import math
import os
import time
import tempfile
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from ipfs_datasets_py.utils import anyio_compat as anyio_runtime

from .leanstral_artifact_cache import LeanstralArtifactCache


LEANSTRAL_AUDIT_REQUEST_SCHEMA_VERSION = "legal-ir-leanstral-audit-request-v1"
LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION = "legal-ir-leanstral-audit-response-v2"
LEANSTRAL_AUDIT_CACHE_SCHEMA_VERSION = "legal-ir-leanstral-audit-cache-v1"
LEANSTRAL_DRAFTED_LOGIC_SCHEMA_VERSION = "legal-ir-leanstral-drafted-logic-v1"
LEANSTRAL_DRAFTED_LOGIC_MAX_CANDIDATES = 6
LEANSTRAL_DRAFTED_LOGIC_MAX_TEXT_CHARS = 240

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
        "drafted_logic_candidates": (
            "Optional bounded guidance-only draft logic candidates.  Candidates "
            "must use compact abstract predicates or IR slots, cite request proof "
            "obligations when possible, and must not copy source text spans."
        ),
        "request_id": "Copy request.request_id exactly.",
    },
    "optional": ("drafted_logic_candidates",),
}

LEANSTRAL_AUDIT_REQUEST_SCHEMA_HASH = ""
LEANSTRAL_AUDIT_RESPONSE_SCHEMA_HASH = ""
LEANSTRAL_AUDIT_STOP_TOKENS = ("<|im_end|>", "<|im_start|>")

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
LLMGenerateBatchFn = Callable[..., Sequence[str]]


LEANSTRAL_AUDIT_WORKER_SCHEMA_VERSION = "legal-ir-leanstral-audit-worker-v1"
LEANSTRAL_AUDIT_CHECKPOINT_SCHEMA_VERSION = "legal-ir-leanstral-audit-checkpoint-v1"
LEANSTRAL_EVIDENCE_REFRESH_POLICIES = (
    "full_manifest",
    "latest_compiler_snapshot",
)
LEANSTRAL_OWNED_COMPILER_SURFACES = (
    "modal.compiler",
    "modal.compiler.registry",
    "modal.compiler.ambiguity",
    "modal.ir_decompiler",
    "bridge.contracts",
    "deontic.ir",
    "external_provers.router",
    "TDFOL.prover",
    "CEC.native",
    "zkp.circuits",
    "knowledge_graphs.neo4j_compat",
    "modal.frame_logic",
)


@dataclass(frozen=True)
class LeanstralAuditConfig:
    """Configuration for the structured Leanstral audit lane."""

    enabled: bool = False
    provider: str = "leanstral_local"
    model: str = "Leanstral"
    vibe_agent: str = "lean"
    timeout_seconds: float = 300.0
    max_new_tokens: int = 1800
    cache_dir: Optional[str] = None
    validation_repair_retries: int = 1
    cache_writes_enabled: bool = True
    prompt_payload_mode: str = "full"

    def bounded_validation_repair_retries(self) -> int:
        return max(0, min(3, int(self.validation_repair_retries or 0)))

    def model_identity(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "provider": self.provider,
            "vibe_agent": self.vibe_agent,
        }

    def compact_prompt_payload(self) -> bool:
        return str(self.prompt_payload_mode or "full").strip().lower() in {
            "compact",
            "daemon",
        }

    def normalized_prompt_payload_mode(self) -> str:
        value = str(self.prompt_payload_mode or "full").strip().lower()
        return value if value in {"full", "compact", "daemon"} else "full"

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
    max_evidence_packets_per_item: int = 6
    evidence_refresh_policy: str = "full_manifest"
    provider_enabled: bool = True
    provider: str = "leanstral_local"
    model: str = "Leanstral"
    vibe_agent: str = "lean"
    prompt_template: str = "leanstral-async-disagreement-audit-v1"
    require_leanstral_model: bool = True
    provider_fallbacks: str = "llama_cpp_native,mistral_vibe"
    validation_repair_retries: int = 1
    max_new_tokens: int = 1800
    batch_size: int = 1
    batch_max_workers: int = 0
    batch_use_mesh: bool = True
    prompt_payload_mode: str = "full"

    def bounded_concurrency(self) -> int:
        return max(1, int(self.max_concurrency or 1))

    def bounded_retries(self) -> int:
        return max(0, int(self.max_retries or 0))

    def bounded_max_work_items(self) -> int:
        return max(0, int(self.max_work_items or 0))

    def bounded_max_evidence_packets_per_item(self) -> int:
        return max(1, int(self.max_evidence_packets_per_item or 1))

    def bounded_validation_repair_retries(self) -> int:
        return max(0, min(3, int(self.validation_repair_retries or 0)))

    def bounded_max_new_tokens(self) -> int:
        return max(32, min(4096, int(self.max_new_tokens or 1800)))

    def bounded_batch_size(self) -> int:
        return max(1, min(64, int(self.batch_size or 1)))

    def bounded_batch_max_workers(self) -> Optional[int]:
        value = int(self.batch_max_workers or 0)
        return value if value > 0 else None

    def provider_candidates(self) -> tuple[str, ...]:
        raw_values: List[Any] = [self.provider]
        raw_values.extend(
            token
            for chunk in str(self.provider_fallbacks or "").replace(":", ",").split(",")
            for token in (chunk.strip(),)
            if token
        )
        values: List[str] = []
        seen = set()
        for value in raw_values:
            provider = str(value or "").strip()
            provider_key = provider.lower().replace("-", "_").replace(".", "_")
            if not provider or provider_key in seen:
                continue
            values.append(provider)
            seen.add(provider_key)
        return tuple(values or (str(self.provider or "leanstral_local").strip(),))

    def normalized_evidence_refresh_policy(self) -> str:
        value = str(self.evidence_refresh_policy or "full_manifest").strip().lower()
        return (
            value
            if value in LEANSTRAL_EVIDENCE_REFRESH_POLICIES
            else "full_manifest"
        )

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

    def normalized_prompt_payload_mode(self) -> str:
        value = str(self.prompt_payload_mode or "full").strip().lower()
        return value if value in {"full", "compact", "daemon"} else "full"

    def runner_config(self) -> LeanstralAuditConfig:
        return LeanstralAuditConfig(
            enabled=bool(self.provider_enabled),
            provider=self.provider,
            model=self.model,
            vibe_agent=self.vibe_agent,
            timeout_seconds=self.timeout(),
            max_new_tokens=self.bounded_max_new_tokens(),
            cache_dir=self.cache_dir,
            validation_repair_retries=self.bounded_validation_repair_retries(),
            prompt_payload_mode=self.normalized_prompt_payload_mode(),
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
        owned_surfaces = [
            str(surface)
            for surface in self.evidence.get(
                "owned_compiler_surfaces",
                LEANSTRAL_OWNED_COMPILER_SURFACES,
            )
            or ()
            if str(surface).strip()
        ]
        reference_examples = [
            dict(example)
            for example in self.evidence.get("referenced_examples", []) or []
            if isinstance(example, Mapping)
        ][:8]
        response_identity = {
            "request_cache_key": self.cache_key,
            "request_id": self.request_id,
            "primary_proof_obligation_id": (
                str(self.proof_obligation_ids[0])
                if self.proof_obligation_ids
                else ""
            ),
            "proof_obligation_ids": list(self.proof_obligation_ids),
        }
        return {
            "allowed_classifications": sorted(ALLOWED_AUDIT_CLASSIFICATIONS),
            "audit_response_identity": response_identity,
            "instructions": [
                "Return strict JSON only.",
                "Classify the legal-IR semantic audit using one allowed classification.",
                "Copy request.request_id exactly into response.request_id.",
                "Do not copy request.cache_key into response.request_id.",
                "For every non-abstain response, include a non-null counterexample or witness grounded in request evidence.",
                "Counterexamples and witnesses must cite an example_id or evidence_id from request.evidence.referenced_examples when that manifest is non-empty.",
                "For every non-abstain response, include at least one non-empty proposed_compiler_surface object.",
                "Set proposed_compiler_surface[].component to one owned compiler surface from request.evidence.owned_compiler_surfaces; use TDFOL, CEC, ZKP, or prover surfaces only when they are present in that owned surface list; do not invent architecture-only components.",
                "Optionally include drafted_logic_candidates as guidance-only candidate frame/modal/deontic/TDFOL/KG/CEC/prover logic; each candidate must be compact, abstract, and cite a request proof_obligation_id when possible.",
                "Do not copy full legal text spans into drafted_logic_candidates; use predicates, slots, symbols, hashes, and short identifiers instead.",
                "For issue findings, identify a non-empty missing_semantic_rule.",
                "Use only proof_obligation_ids from the request.",
                "For non-abstain responses, set abstention_reason to JSON null or an empty string, never the text 'None'.",
                "For abstain responses, set a non-empty abstention_reason and leave issue evidence fields empty.",
            ],
            "output_contract": [
                "Return exactly one compact JSON object; the first non-whitespace character must be { and the last must be }.",
                "Do not emit markdown fences, prose, XML tags, chat-template tokens, or a copy of this prompt.",
                "Set request_id exactly to audit_response_identity.request_id.",
                "If request_cache_key is present, set it exactly to audit_response_identity.request_cache_key.",
                "Keep every free-text string under 140 characters except drafted_logic_candidates[].candidate, which must stay under 240 characters.",
                "Use one short counterexample or witness; do not narrate the full disagreement packet.",
            ],
            "owned_compiler_surfaces": owned_surfaces,
            "referenced_examples": reference_examples,
            "request": self.to_dict(),
            "response_schema": LEANSTRAL_AUDIT_RESPONSE_SCHEMA,
            "response_template": {
                "abstention_reason": None,
                "affected_ir_families": [semantic_family],
                "classification": "missing_semantic_rule",
                "confidence": 0.0,
                "counterexample": {
                    "evidence_id": "copy a relevant request evidence_id",
                    "observed": "compiler loses or distorts this semantic signal",
                    "expected": "legal semantics should be preserved",
                },
                "drafted_logic_candidates": [
                    {
                        "logic_family": semantic_family,
                        "candidate": "obligation(actor, action) unless exception_condition",
                        "compiler_surface": compiler_surface,
                        "confidence": 0.0,
                        "intended_use": "guidance_only",
                        "proof_obligation_id": (
                            str(self.proof_obligation_ids[0])
                            if self.proof_obligation_ids
                            else ""
                        ),
                    }
                ],
                "missing_semantic_rule": {
                    "description": "missing deterministic semantic rule"
                },
                "proof_obligation_ids": list(self.proof_obligation_ids[:1]),
                "proposed_compiler_surface": [
                    {
                        "component": compiler_surface,
                        "operation": "add deterministic compiler or decompiler rule",
                    }
                ],
                "request_cache_key": self.cache_key,
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
    drafted_logic_candidates: Sequence[Dict[str, Any]] = field(default_factory=tuple)
    abstention_reason: str = ""
    rationale: str = ""
    request_cache_key: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "LeanstralAuditResponse":
        families = _string_tuple(data.get("affected_ir_families"))
        obligations = _string_tuple(data.get("proof_obligation_ids"))
        surfaces = _mapping_tuple(data.get("proposed_compiler_surface"))
        drafted_logic = _drafted_logic_candidates(data.get("drafted_logic_candidates"))
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
            drafted_logic_candidates=drafted_logic,
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
            "drafted_logic_candidates": [
                dict(candidate) for candidate in self.drafted_logic_candidates
            ],
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
    generation_attempts: int = 0
    repair_reasons: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cache_hit": self.cache_hit,
            "generation_attempts": int(self.generation_attempts),
            "llm_called": self.llm_called,
            "raw_response": self.raw_response,
            "repair_reasons": list(self.repair_reasons),
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
    generation_attempts: int = 0
    reasons: Sequence[str] = field(default_factory=tuple)
    repair_reasons: Sequence[str] = field(default_factory=tuple)
    response_hash: str = ""
    validation: Optional[LeanstralAuditValidation] = None
    elapsed_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempts": int(self.attempts),
            "cache_hit": bool(self.cache_hit),
            "cache_key": self.cache_key,
            "elapsed_seconds": round(float(self.elapsed_seconds), 6),
            "generation_attempts": int(self.generation_attempts),
            "llm_called": bool(self.llm_called),
            "repair_reasons": list(self.repair_reasons),
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
        if _checkpoint_result_is_reusable(result):
            completed.add(result.work_key)
        else:
            completed.discard(result.work_key)
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

    def __init__(
        self,
        directory: Optional[str | Path] = None,
        *,
        artifact_cache: Optional[LeanstralArtifactCache] = None,
    ) -> None:
        self.directory = Path(directory).expanduser() if directory else None
        self.artifact_cache = (
            artifact_cache
            if artifact_cache is not None
            else LeanstralArtifactCache.from_env(self.directory)
        )
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
        self._write_local_payload(request.cache_key, payload)
        if self.artifact_cache is not None:
            try:
                self.artifact_cache.put_json(
                    request.cache_key,
                    payload,
                    artifact_type="leanstral_audit_cache_entry",
                )
            except Exception:
                pass
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
        payload = self._load_local_payload(cache_key)
        if payload is None and self.artifact_cache is not None:
            try:
                payload = self.artifact_cache.get_json(cache_key)
            except Exception:
                payload = None
        if not isinstance(payload, Mapping):
            return None
        normalized = dict(payload)
        self._memory[cache_key] = normalized
        if self.directory is not None:
            try:
                self._write_local_payload(cache_key, normalized)
            except OSError:
                pass
        return normalized

    def _load_local_payload(self, cache_key: str) -> Optional[Dict[str, Any]]:
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
        return dict(payload) if isinstance(payload, Mapping) else None

    def _write_local_payload(self, cache_key: str, payload: Mapping[str, Any]) -> None:
        if self.directory is None:
            return
        path = self._path_for_key(cache_key)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.directory,
            prefix=f".{cache_key}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.write("\n")
            temporary_path = Path(handle.name)
        os.replace(temporary_path, path)


class LeanstralAuditRunner:
    """Run structured audits with verified cache admission."""

    def __init__(
        self,
        config: Optional[LeanstralAuditConfig] = None,
        *,
        llm_generate: Optional[LLMGenerateFn] = None,
        llm_generate_batch: Optional[LLMGenerateBatchFn] = None,
        cache: Optional[LeanstralAuditCache] = None,
    ) -> None:
        self.config = config or LeanstralAuditConfig()
        self.llm_generate = llm_generate
        self.llm_generate_batch = llm_generate_batch
        self.cache = cache or LeanstralAuditCache(self.config.cache_dir)

    def run(
        self,
        *,
        evidence: Mapping[str, Any],
        prompt: Mapping[str, Any] | str,
        theorem_registry: Optional[Mapping[str, Any]] = None,
        theorem_registry_hash: Optional[str] = None,
        proof_obligation_ids: Sequence[str],
        provider: Optional[str] = None,
        model: Optional[str] = None,
        vibe_agent: Optional[str] = None,
    ) -> LeanstralAuditResult:
        provider_name = str(provider or self.config.provider).strip()
        model_name = str(model or self.config.model).strip()
        vibe_agent_name = str(vibe_agent or self.config.vibe_agent).strip()
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
                generation_attempts=0,
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
                generation_attempts=0,
            )

        generate = self.llm_generate
        trace_getter = None
        if generate is None:
            from ipfs_datasets_py import llm_router

            generate = llm_router.generate_text
            trace_getter = llm_router.get_last_generation_trace
        response = None
        raw_response = ""
        validation = LeanstralAuditValidation(
            accepted=False,
            verified=False,
            reasons=("leanstral_audit_not_called",),
            cache_key=request.cache_key,
        )
        repair_reasons: tuple[str, ...] = ()
        generation_attempts = 0
        for repair_attempt in range(self.config.bounded_validation_repair_retries() + 1):
            prompt_payload = json.dumps(
                _leanstral_audit_prompt_payload(
                    request,
                    repair_attempt=repair_attempt,
                    previous_response_text=raw_response,
                    previous_validation=validation if generation_attempts else None,
                    payload_mode=self.config.normalized_prompt_payload_mode(),
                ),
                ensure_ascii=True,
                sort_keys=True,
            )
            raw_response = generate(
                prompt_payload,
                provider=provider_name,
                model_name=model_name,
                allow_local_fallback=False,
                disable_model_retry=True,
                max_new_tokens=int(self.config.max_new_tokens),
                mistral_vibe_agent=vibe_agent_name,
                response_format={"type": "json_object"},
                stop=list(LEANSTRAL_AUDIT_STOP_TOKENS),
                temperature=0.0,
                timeout=float(self.config.timeout_seconds),
            )
            generation_attempts += 1
            if trace_getter is not None:
                trace = trace_getter()
                effective_provider = str(trace.get("effective_provider_name") or "").strip()
                allowed = _allowed_effective_provider_identities(provider_name)
                if effective_provider and _canonical_provider_identity(effective_provider) not in allowed:
                    raise RuntimeError(
                        "unexpected_effective_provider:"
                        f"{effective_provider}:expected:{provider_name}"
                    )
            response = parse_leanstral_audit_response(raw_response)
            response, normalization_reasons = normalize_leanstral_audit_response_for_request(
                request,
                response,
            )
            repair_reasons = _merge_reasons(repair_reasons, normalization_reasons)
            validation = validate_leanstral_audit_response(request, response)
            if response is not None and self.config.cache_writes_enabled:
                self.cache.put(request, response, validation)
            if validation.accepted and validation.verified:
                break
            repair_reasons = _merge_reasons(repair_reasons, validation.reasons)
            if repair_attempt >= self.config.bounded_validation_repair_retries():
                break
            if not _leanstral_validation_reasons_repairable(validation.reasons):
                break
        return LeanstralAuditResult(
            request=request,
            response=response,
            validation=validation,
            llm_called=True,
            raw_response=raw_response,
            generation_attempts=generation_attempts,
            repair_reasons=repair_reasons,
        )

    def run_initial_batch(
        self,
        requests: Sequence[LeanstralAuditRequest],
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        vibe_agent: Optional[str] = None,
        use_mesh: bool = False,
        max_workers: Optional[int] = None,
    ) -> List[LeanstralAuditResult]:
        """Run the first audit generation attempt for an ordered request batch."""

        request_list = list(requests or [])
        if not request_list:
            return []

        provider_name = str(provider or self.config.provider).strip()
        model_name = str(model or self.config.model).strip()
        vibe_agent_name = str(vibe_agent or self.config.vibe_agent).strip()
        if not self.config.enabled:
            return [
                LeanstralAuditResult(
                    request=request,
                    response=None,
                    validation=LeanstralAuditValidation(
                        accepted=False,
                        verified=False,
                        reasons=("leanstral_audit_disabled",),
                        cache_key=request.cache_key,
                    ),
                    llm_called=False,
                    generation_attempts=0,
                )
                for request in request_list
            ]
        generate_batch = self.llm_generate_batch
        trace_getter = None
        if generate_batch is None:
            from ipfs_datasets_py import llm_router

            generate_batch = getattr(llm_router, "generate_text_batch", None)
            trace_getter = llm_router.get_last_generation_trace
        if generate_batch is None:
            return [
                self.run(
                    evidence=request.evidence,
                    prompt=request.prompt,
                    theorem_registry_hash=request.theorem_registry_hash,
                    proof_obligation_ids=request.proof_obligation_ids,
                    provider=provider_name,
                    model=model_name,
                    vibe_agent=vibe_agent_name,
                )
                for request in request_list
            ]

        prompt_payloads = [
            json.dumps(
                _leanstral_audit_prompt_payload(
                    request,
                    repair_attempt=0,
                    payload_mode=self.config.normalized_prompt_payload_mode(),
                ),
                ensure_ascii=True,
                sort_keys=True,
            )
            for request in request_list
        ]
        raw_responses = list(
            generate_batch(
                prompt_payloads,
                provider=provider_name,
                model_name=model_name,
                allow_local_fallback=False,
                disable_model_retry=True,
                max_new_tokens=int(self.config.max_new_tokens),
                mistral_vibe_agent=vibe_agent_name,
                response_format={"type": "json_object"},
                stop=list(LEANSTRAL_AUDIT_STOP_TOKENS),
                temperature=0.0,
                timeout=float(self.config.timeout_seconds),
                use_mesh=bool(use_mesh),
                max_workers=max_workers,
            )
        )
        if len(raw_responses) != len(request_list):
            raise RuntimeError(
                "Leanstral batch returned "
                f"{len(raw_responses)} responses for {len(request_list)} requests"
            )
        if trace_getter is not None:
            trace = trace_getter()
            effective_provider = str(trace.get("effective_provider_name") or "").strip()
            allowed = _allowed_effective_provider_identities(provider_name)
            if effective_provider and _canonical_provider_identity(effective_provider) not in allowed:
                raise RuntimeError(
                    "unexpected_effective_provider:"
                    f"{effective_provider}:expected:{provider_name}"
                )

        results: List[LeanstralAuditResult] = []
        for request, raw_response in zip(request_list, raw_responses):
            response = parse_leanstral_audit_response(str(raw_response or ""))
            response, normalization_reasons = normalize_leanstral_audit_response_for_request(
                request,
                response,
            )
            validation = validate_leanstral_audit_response(request, response)
            repair_reasons = _merge_reasons(normalization_reasons, validation.reasons)
            if response is not None and self.config.cache_writes_enabled:
                self.cache.put(request, response, validation)
            results.append(
                LeanstralAuditResult(
                    request=request,
                    response=response,
                    validation=validation,
                    llm_called=True,
                    raw_response=str(raw_response or ""),
                    generation_attempts=1,
                    repair_reasons=repair_reasons,
                )
            )
        return results


class LeanstralAuditWorker:
    """Consume disagreement packets without blocking the autoencoder loop."""

    def __init__(
        self,
        config: Optional[LeanstralAuditWorkerConfig] = None,
        *,
        audit_runner: Optional[LeanstralAuditRunner] = None,
        llm_generate: Optional[LLMGenerateFn] = None,
        llm_generate_batch: Optional[LLMGenerateBatchFn] = None,
    ) -> None:
        self.config = config or LeanstralAuditWorkerConfig()
        self.runner = audit_runner or LeanstralAuditRunner(
            self.config.runner_config(),
            llm_generate=llm_generate,
            llm_generate_batch=llm_generate_batch,
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
        completed_keys = _checkpoint_reusable_work_keys(checkpoint)
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
        semaphore = anyio_runtime.Semaphore(self.config.bounded_concurrency())
        checkpoint_state = checkpoint
        checkpoint_lock = anyio_runtime.Lock()
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

        async def run_many(
            batch: Sequence[LeanstralAuditWorkItem],
        ) -> Sequence[LeanstralAuditWorkResult]:
            async with semaphore:
                batch_results = await self._run_items_batch(batch)
                async with checkpoint_lock:
                    nonlocal checkpoint_state
                    for result in batch_results:
                        checkpoint_state = checkpoint_state.with_result(
                            result,
                            source_digest=source_digest,
                        )
                    write_leanstral_audit_checkpoint(
                        self.config.checkpoint_path,
                        checkpoint_state,
                    )
                return batch_results

        if pending:
            batch_size = self.config.bounded_batch_size()
            if batch_size <= 1:
                gathered = await anyio_runtime.gather(
                    *(run_one(item) for item in pending),
                    return_exceptions=False,
                )
                results = list(gathered)
            else:
                batches = [
                    pending[idx : idx + batch_size]
                    for idx in range(0, len(pending), batch_size)
                ]
                nested_results = await anyio_runtime.gather(
                    *(run_many(batch) for batch in batches),
                    return_exceptions=False,
                )
                results = [
                    result
                    for batch_results in nested_results
                    for result in batch_results
                ]
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

    async def _run_items_batch(
        self,
        items: Sequence[LeanstralAuditWorkItem],
    ) -> Sequence[LeanstralAuditWorkResult]:
        item_list = list(items or [])
        if not item_list:
            return ()
        if len(item_list) <= 1 or self.config.bounded_batch_size() <= 1:
            return tuple([await self._run_item(item) for item in item_list])
        if self.runner.llm_generate is not None and self.runner.llm_generate_batch is None:
            return tuple([await self._run_item(item) for item in item_list])

        starts = {item.work_key: time.monotonic() for item in item_list}
        results_by_key: Dict[str, LeanstralAuditWorkResult] = {}
        candidates: List[LeanstralAuditWorkItem] = []
        for item in item_list:
            started = starts[item.work_key]
            if self.config.require_leanstral_model and not _is_leanstral_model_identity(item.request.model):
                results_by_key[item.work_key] = _work_result(
                    item,
                    status="model_rejected",
                    attempts=0,
                    reasons=("non_leanstral_model_identity",),
                    elapsed=time.monotonic() - started,
                )
                continue
            cached = self.runner.cache.get_accepted_entry(item.request)
            if cached is not None:
                results_by_key[item.work_key] = _work_result(
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
                continue
            if not self.config.provider_enabled:
                results_by_key[item.work_key] = _work_result(
                    item,
                    status="provider_disabled",
                    attempts=0,
                    reasons=("provider_disabled_cache_miss",),
                    elapsed=time.monotonic() - started,
                )
                continue
            candidates.append(item)

        if candidates:
            attempts_by_key = {item.work_key: 0 for item in candidates}
            last_reasons_by_key: Dict[str, tuple[str, ...]] = {
                item.work_key: () for item in candidates
            }
            providers = self.config.provider_candidates()
            handled_batch = False
            for attempt in range(self.config.bounded_retries() + 1):
                for provider in providers:
                    for item in candidates:
                        attempts_by_key[item.work_key] += 1
                    try:
                        audit_results = await anyio_runtime.wait_for(
                            anyio_runtime.to_thread(
                                self._run_sync_items_initial_batch,
                                candidates,
                                provider=provider,
                            ),
                            timeout=self.config.timeout(),
                        )
                    except TimeoutError:
                        for item in candidates:
                            last_reasons_by_key[item.work_key] = _merge_reasons(
                                last_reasons_by_key[item.work_key],
                                (
                                    _provider_attempt_reason(
                                        provider,
                                        "leanstral_audit_timeout",
                                        len(providers),
                                    ),
                                ),
                            )
                    except Exception as exc:
                        reason = _provider_unavailable_reason(exc) or _provider_error_reason(exc)
                        for item in candidates:
                            last_reasons_by_key[item.work_key] = _merge_reasons(
                                last_reasons_by_key[item.work_key],
                                (
                                    _provider_attempt_reason(
                                        provider,
                                        reason,
                                        len(providers),
                                    ),
                                ),
                            )
                    else:
                        handled_batch = True
                        for item, audit_result in zip(candidates, audit_results):
                            if audit_result.response is not None:
                                self.runner.cache.put(
                                    item.request,
                                    audit_result.response,
                                    audit_result.validation,
                                )
                            if audit_result.validation.accepted and audit_result.validation.verified:
                                results_by_key[item.work_key] = _work_result(
                                    item,
                                    status="accepted",
                                    attempts=attempts_by_key[item.work_key],
                                    reasons=audit_result.validation.reasons,
                                    cache_hit=audit_result.cache_hit,
                                    llm_called=audit_result.llm_called,
                                    generation_attempts=audit_result.generation_attempts,
                                    repair_reasons=audit_result.repair_reasons,
                                    response_hash=audit_result.validation.response_hash,
                                    validation=audit_result.validation,
                                    elapsed=time.monotonic() - starts[item.work_key],
                                )
                            else:
                                results_by_key[item.work_key] = await self._run_item(item)
                        break
                if handled_batch:
                    break
                if attempt < self.config.bounded_retries() and self.config.backoff() > 0.0:
                    await anyio_runtime.sleep(self.config.backoff() * (2**attempt))

            if not handled_batch:
                for item in candidates:
                    reasons = last_reasons_by_key[item.work_key]
                    failed_status = (
                        "timeout"
                        if _all_attempt_reasons_match(reasons, "leanstral_audit_timeout")
                        else "failed"
                    )
                    if _all_attempt_reasons_match(reasons, "leanstral_labs_model_unavailable"):
                        failed_status = "unavailable"
                    results_by_key[item.work_key] = _work_result(
                        item,
                        status=failed_status,
                        attempts=attempts_by_key[item.work_key],
                        reasons=reasons,
                        llm_called=True,
                        elapsed=time.monotonic() - starts[item.work_key],
                    )

        return tuple(results_by_key[item.work_key] for item in item_list)

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
        providers = self.config.provider_candidates()
        for attempt in range(self.config.bounded_retries() + 1):
            for provider in providers:
                attempts += 1
                try:
                    audit_result = await anyio_runtime.wait_for(
                        anyio_runtime.to_thread(
                            self._run_sync_item,
                            item,
                            provider=provider,
                        ),
                        timeout=self.config.timeout(),
                    )
                except TimeoutError:
                    last_reasons = _merge_reasons(
                        last_reasons,
                        (_provider_attempt_reason(provider, "leanstral_audit_timeout", len(providers)),),
                    )
                except Exception as exc:  # provider failures must fail closed
                    reason = _provider_unavailable_reason(exc) or _provider_error_reason(exc)
                    last_reasons = _merge_reasons(
                        last_reasons,
                        (_provider_attempt_reason(provider, reason, len(providers)),),
                    )
                else:
                    if audit_result.response is not None:
                        self.runner.cache.put(
                            item.request,
                            audit_result.response,
                            audit_result.validation,
                        )
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
                        generation_attempts=audit_result.generation_attempts,
                        repair_reasons=audit_result.repair_reasons,
                        response_hash=audit_result.validation.response_hash,
                        validation=audit_result.validation,
                        elapsed=time.monotonic() - started,
                    )
            if attempt < self.config.bounded_retries() and self.config.backoff() > 0.0:
                await anyio_runtime.sleep(self.config.backoff() * (2**attempt))
        failed_status = "timeout" if _all_attempt_reasons_match(last_reasons, "leanstral_audit_timeout") else "failed"
        if _all_attempt_reasons_match(last_reasons, "leanstral_labs_model_unavailable"):
            failed_status = "unavailable"
        return _work_result(
            item,
            status=failed_status,
            attempts=attempts,
            reasons=last_reasons,
            llm_called=True,
            elapsed=time.monotonic() - started,
        )

    def _run_sync_item(
        self,
        item: LeanstralAuditWorkItem,
        *,
        provider: Optional[str] = None,
    ) -> LeanstralAuditResult:
        thread_runner = LeanstralAuditRunner(
            replace(
                self.runner.config,
                cache_dir=None,
                cache_writes_enabled=False,
            ),
            llm_generate=self.runner.llm_generate,
            cache=LeanstralAuditCache(),
        )
        return thread_runner.run(
            evidence=item.request.evidence,
            prompt=item.request.prompt,
            theorem_registry_hash=item.request.theorem_registry_hash,
            proof_obligation_ids=item.request.proof_obligation_ids,
            provider=provider,
            model=self.config.model,
            vibe_agent=self.config.vibe_agent,
        )

    def _run_sync_items_initial_batch(
        self,
        items: Sequence[LeanstralAuditWorkItem],
        *,
        provider: Optional[str] = None,
    ) -> List[LeanstralAuditResult]:
        thread_runner = LeanstralAuditRunner(
            replace(
                self.runner.config,
                cache_dir=None,
                cache_writes_enabled=False,
            ),
            llm_generate=self.runner.llm_generate,
            llm_generate_batch=self.runner.llm_generate_batch,
            cache=LeanstralAuditCache(),
        )
        return thread_runner.run_initial_batch(
            [item.request for item in items],
            provider=provider,
            model=self.config.model,
            vibe_agent=self.config.vibe_agent,
            use_mesh=bool(self.config.batch_use_mesh),
            max_workers=self.config.bounded_batch_max_workers(),
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
        request_records = _worker_request_records(cluster_records, config=cfg)
        request = _build_worker_audit_request(
            cluster,
            request_records,
            config=cfg,
        )
        compiler_commit = _records_compiler_commit(request_records)
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
            -float(item.cluster.get("rank_score", 0.0) or 0.0),
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


def _json_mappings_from_text(text: str) -> List[Mapping[str, Any]]:
    decoder = json.JSONDecoder()
    mappings: List[Mapping[str, Any]] = []
    raw = str(text or "").strip()
    candidates = [raw]
    if raw.startswith("```json"):
        end = raw.find("```", len("```json"))
        if end >= 0:
            candidates.insert(0, raw[len("```json") : end].strip())
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(parsed, Mapping):
                mappings.append(parsed)
                continue
        for index, char in enumerate(candidate):
            if char != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(candidate[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, Mapping):
                mappings.append(parsed)
    deduped: List[Mapping[str, Any]] = []
    seen: set[str] = set()
    for mapping in mappings:
        digest = canonical_sha256(mapping)
        if digest in seen:
            continue
        seen.add(digest)
        deduped.append(mapping)
    return deduped


def parse_leanstral_audit_response(response: str) -> Optional[LeanstralAuditResponse]:
    """Parse strict or recoverably fenced JSON Leanstral audit output."""

    mappings = _json_mappings_from_text(response)
    if not mappings:
        return None
    for parsed in mappings:
        if str(parsed.get("schema_version") or "").strip() == LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION:
            return LeanstralAuditResponse.from_mapping(parsed)
    return LeanstralAuditResponse.from_mapping(mappings[0])


def normalize_leanstral_audit_response_for_request(
    request: LeanstralAuditRequest,
    response: Optional[LeanstralAuditResponse],
) -> tuple[Optional[LeanstralAuditResponse], tuple[str, ...]]:
    """Repair non-semantic response fields that are determined by the request.

    Leanstral commonly confuses adjacent identifiers in the prompt, especially
    request_id, cache_key, and proof obligation IDs.  These fields identify the
    current audit envelope rather than the substantive finding, so we only
    normalize when the observed value is empty or is another known identifier
    from the same request.
    """

    if response is None:
        return None, ()

    data = response.to_dict()
    reasons: list[str] = []
    known_request_identifiers = {
        request.request_id,
        request.cache_key,
        *[str(value) for value in request.proof_obligation_ids],
    }
    response_request_id = str(response.request_id or "").strip()
    if (
        response_request_id != request.request_id
        and (
            not response_request_id
            or response_request_id in known_request_identifiers
        )
    ):
        data["request_id"] = request.request_id
        reasons.append("normalized_request_id_from_request_context")

    response_cache_key = str(response.request_cache_key or "").strip()
    if not response_cache_key:
        data["request_cache_key"] = request.cache_key
        reasons.append("filled_request_cache_key_from_request_context")
    elif response_cache_key != request.cache_key and response_cache_key in known_request_identifiers:
        data["request_cache_key"] = request.cache_key
        reasons.append("normalized_request_cache_key_from_request_context")

    if not response.proof_obligation_ids and len(request.proof_obligation_ids) == 1:
        data["proof_obligation_ids"] = [str(request.proof_obligation_ids[0])]
        reasons.append("filled_single_proof_obligation_from_request_context")

    if not response.affected_ir_families:
        cluster = _json_ready_mapping(request.evidence.get("cluster"))
        semantic_family = str(cluster.get("semantic_family") or "").strip()
        if semantic_family:
            data["affected_ir_families"] = [semantic_family]
            reasons.append("filled_affected_ir_families_from_request_cluster")

    if not reasons:
        return response, ()
    return LeanstralAuditResponse.from_mapping(data), tuple(dict.fromkeys(reasons))


def _leanstral_audit_prompt_payload(
    request: LeanstralAuditRequest,
    *,
    repair_attempt: int = 0,
    previous_response_text: str = "",
    previous_validation: Optional[LeanstralAuditValidation] = None,
    compact: bool = False,
    payload_mode: Optional[str] = None,
) -> Dict[str, Any]:
    mode = str(payload_mode or ("compact" if compact else "full")).strip().lower()
    if mode == "daemon":
        payload = _daemon_leanstral_audit_prompt_payload(request)
    elif mode == "compact":
        payload = _compact_leanstral_audit_prompt_payload(request)
    else:
        payload = request.to_prompt_payload()
    if repair_attempt <= 0 or previous_validation is None:
        return payload
    payload["repair_instructions"] = {
        "mode": "validation_repair",
        "repair_attempt": int(repair_attempt),
        "validation_reasons": list(previous_validation.reasons),
        "required_action": (
            "Return one corrected JSON object only. Copy request.request_id, "
            "request.cache_key, and one proof_obligation_id exactly from the "
            "request. Fix every listed validation reason without changing the "
            "evidence, request identity, schema version, or model identity."
        ),
        "previous_response_excerpt": _bounded_text(previous_response_text, 4000),
    }
    return payload


def _daemon_leanstral_audit_prompt_payload(
    request: LeanstralAuditRequest,
) -> Dict[str, Any]:
    """Return the smallest prompt shape suitable for always-on guidance."""

    evidence = _json_ready_mapping(request.evidence)
    cluster = _json_ready_mapping(evidence.get("cluster"))
    semantic_family = str(cluster.get("semantic_family") or "legal_ir").strip()
    compiler_surface = str(cluster.get("compiler_surface") or "legal_ir.compiler").strip()
    evidence_packets = [
        _daemon_prompt_evidence_packet(packet)
        for packet in evidence.get("evidence_packets", []) or []
        if isinstance(packet, Mapping)
    ][:1]
    referenced_examples = [
        _daemon_prompt_reference_example(example)
        for example in evidence.get("referenced_examples", []) or []
        if isinstance(example, Mapping)
    ][:1]
    primary_proof_obligation_id = (
        str(request.proof_obligation_ids[0]) if request.proof_obligation_ids else ""
    )
    return {
        "allowed_classifications": sorted(ALLOWED_AUDIT_CLASSIFICATIONS),
        "instructions": [
            "Return one strict JSON object only.",
            "Copy request_id, request_cache_key, schema_version, and one proof_obligation_id exactly.",
            "Do not copy legal text spans; cite evidence_id/example_id and use predicates or hashes.",
            "For non-abstain, include missing_semantic_rule, counterexample or witness, and proposed_compiler_surface.",
        ],
        "request": {
            "cache_key": request.cache_key,
            "compiler_surface": compiler_surface,
            "evidence": {
                "cluster": _daemon_prompt_cluster(cluster),
                "evidence_packets": evidence_packets,
                "referenced_examples": referenced_examples,
                "source_record_hashes": list(evidence.get("source_record_hashes", []) or [])[:2],
                "state_hashes": list(evidence.get("state_hashes", []) or [])[:2],
            },
            "hashes": {
                "evidence": request.evidence_hash,
                "model": request.model_hash,
                "prompt": request.prompt_hash,
                "request_schema": request.request_schema_hash,
                "response_schema": request.response_schema_hash,
                "theorem_registry": request.theorem_registry_hash,
            },
            "proof_obligation_ids": list(request.proof_obligation_ids[:2]),
            "request_id": request.request_id,
            "schema_version": request.schema_version,
            "semantic_family": semantic_family,
        },
        "response_template": {
            "abstention_reason": None,
            "affected_ir_families": [semantic_family],
            "classification": "missing_semantic_rule",
            "confidence": 0.0,
            "counterexample": {
                "evidence_id": "copy evidence_id or example_id from request.evidence",
                "observed": "compiler loses or distorts this semantic signal",
                "expected": "legal semantics should be preserved",
            },
            "drafted_logic_candidates": [
                {
                    "logic_family": semantic_family,
                    "candidate": "obligation(actor, action) unless exception_condition",
                    "compiler_surface": compiler_surface,
                    "confidence": 0.0,
                    "intended_use": "guidance_only",
                    "proof_obligation_id": primary_proof_obligation_id,
                }
            ],
            "missing_semantic_rule": {"description": "missing deterministic semantic rule"},
            "proof_obligation_ids": [primary_proof_obligation_id] if primary_proof_obligation_id else [],
            "proposed_compiler_surface": [
                {
                    "component": compiler_surface,
                    "operation": "add deterministic compiler or decompiler rule",
                }
            ],
            "request_cache_key": request.cache_key,
            "request_id": request.request_id,
            "schema_version": LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
            "witness": None,
        },
    }


def _compact_leanstral_audit_prompt_payload(
    request: LeanstralAuditRequest,
) -> Dict[str, Any]:
    """Return a daemon-sized prompt that preserves verifiable identifiers."""

    evidence = _json_ready_mapping(request.evidence)
    cluster = _json_ready_mapping(evidence.get("cluster"))
    semantic_family = str(cluster.get("semantic_family") or "legal_ir").strip()
    compiler_surface = str(cluster.get("compiler_surface") or "legal_ir.compiler").strip()
    evidence_packets = [
        _compact_prompt_evidence_packet(packet)
        for packet in evidence.get("evidence_packets", []) or []
        if isinstance(packet, Mapping)
    ][:1]
    referenced_examples = [
        _compact_prompt_reference_example(example)
        for example in evidence.get("referenced_examples", []) or []
        if isinstance(example, Mapping)
    ][:1]
    owned_surfaces = [
        str(surface)
        for surface in evidence.get(
            "owned_compiler_surfaces",
            LEANSTRAL_OWNED_COMPILER_SURFACES,
        )
        or ()
        if str(surface).strip()
    ]
    compact_request = {
        "cache_key": request.cache_key,
        "evidence": {
            "cluster": _compact_prompt_cluster(cluster),
            "compiler_commit": evidence.get("compiler_commit"),
            "evidence_packet_count": evidence.get("evidence_packet_count"),
            "evidence_packet_selection": evidence.get("evidence_packet_selection"),
            "evidence_packets": evidence_packets,
            "owned_compiler_surfaces": owned_surfaces,
            "referenced_examples": referenced_examples,
            "semantic_signature": evidence.get("semantic_signature"),
            "source_record_hashes": list(evidence.get("source_record_hashes", []) or [])[:4],
            "state_hashes": list(evidence.get("state_hashes", []) or [])[:4],
        },
        "hashes": {
            "evidence": request.evidence_hash,
            "model": request.model_hash,
            "prompt": request.prompt_hash,
            "request_schema": request.request_schema_hash,
            "response_schema": request.response_schema_hash,
            "theorem_registry": request.theorem_registry_hash,
        },
        "model": dict(request.model),
        "prompt": dict(request.prompt),
        "proof_obligation_ids": list(request.proof_obligation_ids),
        "request_id": request.request_id,
        "schema_version": request.schema_version,
    }
    response_identity = {
        "request_cache_key": request.cache_key,
        "request_id": request.request_id,
        "primary_proof_obligation_id": (
            str(request.proof_obligation_ids[0])
            if request.proof_obligation_ids
            else ""
        ),
        "proof_obligation_ids": list(request.proof_obligation_ids),
    }
    return {
        "allowed_classifications": sorted(ALLOWED_AUDIT_CLASSIFICATIONS),
        "audit_response_identity": response_identity,
        "instructions": [
            "Return strict JSON only.",
            "Classify the LegalIR semantic audit using one allowed classification.",
            "Copy request.request_id exactly into response.request_id.",
            "Use only proof_obligation_ids from the request.",
            "For non-abstain responses, cite a compact evidence_id or example_id from request.evidence.",
            "Do not copy legal text spans; use predicates, slots, hashes, and short identifiers.",
            "For issue findings, include missing_semantic_rule and proposed_compiler_surface.",
        ],
        "output_contract": [
            "Return exactly one compact JSON object.",
            "No markdown, prose, XML tags, chat-template tokens, or prompt copies.",
            "Keep every free-text string under 140 characters.",
        ],
        "request": compact_request,
        "response_schema_hash": request.response_schema_hash,
        "response_template": {
            "abstention_reason": None,
            "affected_ir_families": [semantic_family],
            "classification": "missing_semantic_rule",
            "confidence": 0.0,
            "counterexample": {
                "evidence_id": "copy a relevant request evidence_id",
                "observed": "compiler loses or distorts this semantic signal",
                "expected": "legal semantics should be preserved",
            },
            "drafted_logic_candidates": [
                {
                    "logic_family": semantic_family,
                    "candidate": "obligation(actor, action) unless exception_condition",
                    "compiler_surface": compiler_surface,
                    "confidence": 0.0,
                    "intended_use": "guidance_only",
                    "proof_obligation_id": (
                        str(request.proof_obligation_ids[0])
                        if request.proof_obligation_ids
                        else ""
                    ),
                }
            ],
            "missing_semantic_rule": {
                "description": "missing deterministic semantic rule"
            },
            "proof_obligation_ids": list(request.proof_obligation_ids[:1]),
            "proposed_compiler_surface": [
                {
                    "component": compiler_surface,
                    "operation": "add deterministic compiler or decompiler rule",
                }
            ],
            "request_cache_key": request.cache_key,
            "request_id": request.request_id,
            "schema_version": LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
            "witness": None,
        },
    }


def _compact_prompt_cluster(cluster: Mapping[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for key in (
        "compiler_surface",
        "evidence_ids",
        "gap_count",
        "gap_detail_selection",
        "sample_ids",
        "schema_version",
        "semantic_family",
        "semantic_signature",
    ):
        if key in cluster:
            payload[key] = _json_ready(cluster.get(key))
    gaps = [
        _prompt_bounded_json(gap, max_chars=140)
        for gap in cluster.get("gaps", []) or []
        if isinstance(gap, Mapping)
    ][:1]
    if gaps:
        payload["gaps"] = gaps
    omitted = cluster.get("omitted_gap_hashes")
    if isinstance(omitted, Sequence) and not isinstance(omitted, (str, bytes)):
        payload["omitted_gap_hashes"] = [str(value) for value in omitted[:4]]
    return payload


def _compact_prompt_evidence_packet(packet: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "anti_copy_evidence": _prompt_bounded_json(
            packet.get("anti_copy_evidence"),
            max_chars=100,
        ),
        "compiler_decompiler_metrics": _prompt_bounded_json(
            packet.get("compiler_decompiler_metrics"),
            max_chars=120,
        ),
        "evidence_hashes": _selected_prompt_mapping(
            packet.get("evidence_hashes"),
            (
                "canonical_modal_ir_hash",
                "source_text_hash",
                "state_hash",
            ),
        ),
        "evidence_id": str(packet.get("evidence_id") or ""),
        "legal_ir_views": _prompt_bounded_json(
            packet.get("legal_ir_views"),
            max_chars=120,
        ),
        "learned_view_gaps": _prompt_bounded_json(
            packet.get("learned_view_gaps"),
            max_chars=160,
        ),
        "proof_route_status": _prompt_bounded_json(
            packet.get("proof_route_status"),
            max_chars=120,
        ),
        "run_context": _selected_prompt_mapping(
            packet.get("run_context"),
            (
                "compiler_commit",
                "cycle",
                "evaluation_role",
                "state_hash",
            ),
        ),
        "sample_hashes": _selected_prompt_mapping(
            packet.get("sample_hashes"),
            (
                "modal_ir_hash",
                "sample_id",
                "source_text_hash",
            ),
        ),
        "schema_version": str(packet.get("schema_version") or ""),
        "versions": _prompt_bounded_json(packet.get("versions"), max_chars=80),
    }


def _compact_prompt_reference_example(example: Mapping[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for key in (
        "citation",
        "evidence_id",
        "example_id",
        "expected_modal_ir_hash",
        "sample_id",
        "section",
        "source_text_hash",
        "source_span_hash_format",
        "title",
    ):
        value = example.get(key)
        if value not in (None, "", (), []):
            payload[key] = _json_ready(value)
    if "compiler_decompiler_metrics" in example:
        payload["compiler_decompiler_metrics"] = _prompt_bounded_json(
            example.get("compiler_decompiler_metrics"),
            max_chars=100,
        )
    if "source_span_hashes" in example:
        payload["source_span_hashes"] = _prompt_bounded_json(
            example.get("source_span_hashes"),
            max_chars=80,
        )
    text = str(example.get("source_text") or "").strip()
    if text:
        payload["source_text_excerpt"] = _bounded_text(text, 80)
    return payload


def _daemon_prompt_cluster(cluster: Mapping[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for key in (
        "compiler_surface",
        "gap_count",
        "schema_version",
        "semantic_family",
        "semantic_signature",
    ):
        value = cluster.get(key)
        if value not in (None, "", (), []):
            payload[key] = _json_ready(value)
    evidence_ids = cluster.get("evidence_ids")
    if isinstance(evidence_ids, Sequence) and not isinstance(evidence_ids, (str, bytes)):
        payload["evidence_ids"] = [str(value) for value in evidence_ids[:3]]
    sample_ids = cluster.get("sample_ids")
    if isinstance(sample_ids, Sequence) and not isinstance(sample_ids, (str, bytes)):
        payload["sample_ids"] = [str(value) for value in sample_ids[:3]]
    gap_summaries = [
        _daemon_prompt_gap_summary(gap)
        for gap in cluster.get("gaps", []) or []
        if isinstance(gap, Mapping)
    ][:1]
    if gap_summaries:
        payload["gaps"] = gap_summaries
    return payload


def _daemon_prompt_evidence_packet(packet: Mapping[str, Any]) -> Dict[str, Any]:
    evidence_hashes = _json_ready_mapping(packet.get("evidence_hashes"))
    sample_hashes = _json_ready_mapping(packet.get("sample_hashes"))
    return _drop_empty_values(
        {
            "anti_copy": _daemon_prompt_scalar_summary(
                packet.get("anti_copy_evidence"),
                (
                    "source_span_copy_ratio",
                    "exact_source_span_count",
                    "dense_weight_tables_included",
                ),
            ),
            "evidence_id": str(packet.get("evidence_id") or ""),
            "hashes": _drop_empty_values(
                {
                    "modal_ir": _short_prompt_hash(
                        evidence_hashes.get("canonical_modal_ir_hash")
                        or sample_hashes.get("modal_ir_hash")
                    ),
                    "source_text": _short_prompt_hash(
                        evidence_hashes.get("source_text_hash")
                        or sample_hashes.get("source_text_hash")
                    ),
                    "state": _short_prompt_hash(evidence_hashes.get("state_hash")),
                }
            ),
            "learned_gaps": _daemon_prompt_scalar_summary(
                packet.get("learned_view_gaps"),
                (
                    "cross_entropy_excess_loss",
                    "cross_entropy_loss",
                    "cosine_similarity_gap",
                    "source_copy_penalty",
                    "structural_validity_gap",
                ),
                max_fallback_items=3,
            ),
            "metrics": _daemon_prompt_scalar_summary(
                packet.get("compiler_decompiler_metrics"),
                (
                    "cross_entropy_loss",
                    "cosine_similarity",
                    "compiler_ir_cross_entropy_loss",
                    "compiler_ir_cosine_similarity",
                    "source_copy_penalty",
                    "structural_validity",
                ),
            ),
            "proof": _daemon_prompt_scalar_summary(
                packet.get("proof_route_status"),
                (
                    "attempted_count",
                    "compiles",
                    "failure_ratio",
                    "route_status",
                    "valid_count",
                ),
            ),
            "sample_id": sample_hashes.get("sample_id"),
            "views": _daemon_prompt_view_summary(packet.get("legal_ir_views")),
        }
    )


def _daemon_prompt_reference_example(example: Mapping[str, Any]) -> Dict[str, Any]:
    return _drop_empty_values(
        {
            "evidence_id": str(example.get("evidence_id") or ""),
            "example_id": str(example.get("example_id") or ""),
            "expected_modal_ir": _short_prompt_hash(example.get("expected_modal_ir_hash")),
            "sample_id": str(example.get("sample_id") or ""),
            "source_text": _short_prompt_hash(example.get("source_text_hash")),
        }
    )


def _daemon_prompt_gap_summary(gap: Mapping[str, Any]) -> Dict[str, Any]:
    selected = _daemon_prompt_scalar_summary(
        gap,
        (
            "component",
            "compiler_surface",
            "description",
            "family",
            "gap",
            "metric",
            "observed",
            "score",
            "semantic_family",
            "view_family",
        ),
        max_fallback_items=4,
    )
    if selected:
        return selected
    return {"sha256_16": _short_prompt_hash(canonical_sha256(gap))}


def _daemon_prompt_view_summary(value: Any) -> Dict[str, Any]:
    views = _json_ready_mapping(value)
    canonical = _json_ready_mapping(views.get("canonical"))
    predicted = _json_ready_mapping(views.get("predicted"))
    return _drop_empty_values(
        {
            "canonical_family": (
                canonical.get("target_family")
                or canonical.get("predicted_family")
                or _top_family_name(canonical.get("family_distribution"))
            ),
            "predicted_family": (
                predicted.get("predicted_family")
                or _top_family_name(predicted.get("family_distribution"))
            ),
            "target_family": (
                predicted.get("target_family")
                or canonical.get("target_family")
                or _top_family_name(canonical.get("family_distribution"))
            ),
        }
    )


def _daemon_prompt_scalar_summary(
    value: Any,
    keys: Sequence[str],
    *,
    max_fallback_items: int = 0,
) -> Dict[str, Any]:
    mapping = _json_ready_mapping(value)
    selected = {
        key: _json_ready(mapping.get(key))
        for key in keys
        if mapping.get(key) not in (None, "", (), [])
    }
    if selected or max_fallback_items <= 0:
        return _drop_empty_values(selected)
    fallback: Dict[str, Any] = {}
    for key in sorted(mapping):
        raw = mapping.get(key)
        if raw in (None, "", (), []):
            continue
        if isinstance(raw, (bool, int, float, str)):
            fallback[key] = _json_ready(raw)
        if len(fallback) >= max_fallback_items:
            break
    return _drop_empty_values(fallback)


def _top_family_name(value: Any) -> str:
    mapping = _json_ready_mapping(value)
    best_key = ""
    best_score = float("-inf")
    for key, raw_score in mapping.items():
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            continue
        if score > best_score:
            best_key = str(key)
            best_score = score
    return best_key


def _short_prompt_hash(value: Any, length: int = 16) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text[: max(4, int(length or 16))]


def _drop_empty_values(mapping: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in mapping.items()
        if value not in (None, "", (), [], {})
    }


def _selected_prompt_mapping(value: Any, keys: Sequence[str]) -> Dict[str, Any]:
    mapping = _json_ready_mapping(value)
    selected = {
        key: mapping.get(key)
        for key in keys
        if mapping.get(key) not in (None, "", (), [])
    }
    omitted = {
        key: mapping.get(key)
        for key in sorted(mapping)
        if key not in selected and mapping.get(key) not in (None, "", (), [])
    }
    if omitted:
        selected["omitted_sha256"] = canonical_sha256(omitted)
        selected["omitted_key_count"] = len(omitted)
    return _json_ready_mapping(selected)


def _prompt_bounded_json(value: Any, *, max_chars: int) -> Any:
    ready = _json_ready(value)
    try:
        text = json.dumps(ready, ensure_ascii=True, sort_keys=True)
    except (TypeError, ValueError):
        text = str(ready)
    if len(text) <= max_chars:
        return ready
    return {
        "sha256": canonical_sha256(ready),
        "summary": _bounded_text(text, max_chars),
        "truncated": True,
    }


def _leanstral_validation_reasons_repairable(reasons: Sequence[str]) -> bool:
    return bool(tuple(reason for reason in reasons if str(reason).strip()))


def _bounded_text(value: Any, max_chars: int) -> str:
    text = str(value or "")
    limit = max(0, int(max_chars or 0))
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def validate_leanstral_audit_response(
    request: LeanstralAuditRequest,
    response: Optional[LeanstralAuditResponse],
    *,
    verifier_id: str = "leanstral-audit-schema-v2",
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
    request_obligations = set(request.proof_obligation_ids)
    for candidate in response.drafted_logic_candidates:
        if not _mapping_has_content(candidate):
            reasons.append("empty_drafted_logic_candidate")
            break
        if not str(candidate.get("candidate") or "").strip():
            reasons.append("missing_drafted_logic_candidate")
            break
        candidate_obligation = str(candidate.get("proof_obligation_id") or "").strip()
        if candidate_obligation and candidate_obligation not in request_obligations:
            reasons.append("unknown_drafted_logic_proof_obligation_id")
            break
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
    packet_limit = config.bounded_max_evidence_packets_per_item()
    selected_records = list(records[:packet_limit])
    snapshot_policy = (
        config.normalized_evidence_refresh_policy()
        == "latest_compiler_snapshot"
    )
    manifest_records = selected_records if snapshot_policy else list(records)
    source_record_hashes = [canonical_sha256(record) for record in manifest_records]
    selected_evidence_ids = {
        str(record.get("evidence_id") or "")
        for record in selected_records
        if str(record.get("evidence_id") or "")
    }
    evidence = {
        "cluster": _bounded_worker_cluster_payload(
            cluster,
            selected_evidence_ids=selected_evidence_ids,
            include_full_hash_manifest=not snapshot_policy,
        ),
        "compiler_commit": _records_compiler_commit(records),
        "evidence_packets": [_compact_worker_packet(record) for record in selected_records],
        "owned_compiler_surfaces": list(LEANSTRAL_OWNED_COMPILER_SURFACES),
        "referenced_examples": _worker_reference_examples(selected_records),
        "semantic_signature": str(getattr(cluster, "semantic_signature", "")),
        "source_record_hashes": source_record_hashes,
        "state_hashes": sorted(
            {
                value
                for record in manifest_records
                for value in _record_state_hashes(record)
            }
        ),
    }
    if snapshot_policy:
        evidence.update(
            {
                "evidence_packet_count": len(selected_records),
                "evidence_packet_selection": "latest_compiler_stable_snapshot",
            }
        )
    elif len(selected_records) < len(records):
        evidence["evidence_packet_count"] = len(records)
        evidence.update(
            {
                "evidence_packet_selection": "ranked_prefix_with_full_hash_manifest",
                "omitted_evidence_packet_hashes": source_record_hashes[
                    len(selected_records) :
                ],
            }
        )
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


def _bounded_worker_cluster_payload(
    cluster: Any,
    *,
    selected_evidence_ids: set[str],
    include_full_hash_manifest: bool = True,
) -> Dict[str, Any]:
    """Keep full cluster lineage while bounding duplicated gap details."""

    payload = cluster.to_dict(include_gaps=True)
    raw_gaps = payload.get("gaps")
    if not isinstance(raw_gaps, Sequence) or isinstance(raw_gaps, (str, bytes)):
        return payload
    detailed_gaps: List[Dict[str, Any]] = []
    omitted_gaps: List[Any] = []
    for gap in raw_gaps:
        evidence_id = (
            str(gap.get("evidence_id") or "")
            if isinstance(gap, Mapping)
            else ""
        )
        if evidence_id and evidence_id in selected_evidence_ids:
            detailed_gaps.append(dict(gap))
        else:
            omitted_gaps.append(gap)
    detailed_gaps.sort(
        key=lambda gap: (
            str(gap.get("evidence_id") or ""),
            str(gap.get("gap_id") or ""),
        )
    )
    payload["gap_count"] = len(raw_gaps)
    payload["gaps"] = detailed_gaps
    if omitted_gaps:
        if include_full_hash_manifest:
            payload["gap_detail_selection"] = (
                "selected_evidence_packets_with_hash_manifest"
            )
            payload["omitted_gap_hashes"] = [
                canonical_sha256(gap) for gap in omitted_gaps
            ]
        else:
            payload = {
                "compiler_surface": str(payload.get("compiler_surface") or ""),
                "evidence_ids": sorted(selected_evidence_ids),
                "gap_count": len(detailed_gaps),
                "gap_detail_selection": "latest_compiler_stable_snapshot",
                "gaps": detailed_gaps,
                "owned_code_paths": sorted(
                    {
                        str(path)
                        for gap in detailed_gaps
                        if isinstance(gap, Mapping)
                        for path in gap.get("owned_code_paths", []) or []
                        if str(path)
                    }
                ),
                "sample_ids": sorted(
                    {
                        str(gap.get("sample_id") or "")
                        for gap in detailed_gaps
                        if isinstance(gap, Mapping)
                        and str(gap.get("sample_id") or "")
                    }
                ),
                "schema_version": str(payload.get("schema_version") or ""),
                "semantic_family": str(payload.get("semantic_family") or ""),
                "semantic_signature": str(
                    payload.get("semantic_signature") or ""
                ),
            }
    return payload


def _worker_request_records(
    records: Sequence[Mapping[str, Any]],
    *,
    config: LeanstralAuditWorkerConfig,
) -> List[Mapping[str, Any]]:
    """Select stable evidence for the newest compiler revision in a cluster."""

    values = list(records)
    if (
        not values
        or config.normalized_evidence_refresh_policy() != "latest_compiler_snapshot"
    ):
        return values
    indexed = list(enumerate(values))

    def record_order(item: tuple[int, Mapping[str, Any]]) -> tuple[int, int]:
        index, record = item
        context = _json_ready_mapping(_root_record(record).get("run_context"))
        try:
            cycle = int(context.get("cycle") or 0)
        except (TypeError, ValueError):
            cycle = 0
        return cycle, index

    _, newest_record = max(indexed, key=record_order)
    newest_context = _json_ready_mapping(
        _root_record(newest_record).get("run_context")
    )
    newest_commit = str(newest_context.get("compiler_commit") or "").strip()
    if not newest_commit:
        return values
    matching = [
        record
        for record in values
        if str(
            _json_ready_mapping(_root_record(record).get("run_context")).get(
                "compiler_commit"
            )
            or ""
        ).strip()
        == newest_commit
    ]
    if not matching:
        return values

    def stable_record_order(record: Mapping[str, Any]) -> tuple[int, int, str, str]:
        root = _root_record(record)
        context = _json_ready_mapping(root.get("run_context"))
        try:
            cycle = int(context.get("cycle") or 0)
        except (TypeError, ValueError):
            cycle = 0
        role = str(context.get("evaluation_role") or "").strip().lower()
        role_priority = 0 if role == "unguided" else 1 if role == "guided" else 2
        return (
            cycle,
            role_priority,
            str(root.get("evidence_id") or ""),
            canonical_sha256(root),
        )

    return sorted(matching, key=stable_record_order)


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


def _worker_reference_examples(records: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    examples: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        root = _root_record(record)
        sample_hashes = _json_ready_mapping(root.get("sample_hashes"))
        evidence_hashes = _json_ready_mapping(root.get("evidence_hashes"))
        legal_ir_views = _json_ready_mapping(root.get("legal_ir_views"))
        canonical_view = _json_ready_mapping(legal_ir_views.get("canonical"))
        evidence_id = str(root.get("evidence_id") or "").strip()
        sample_id = str(
            sample_hashes.get("sample_id")
            or root.get("sample_id")
            or evidence_id
        ).strip()
        if not evidence_id and not sample_id:
            continue
        expected_hash = str(
            sample_hashes.get("modal_ir_hash")
            or evidence_hashes.get("canonical_modal_ir_hash")
            or canonical_view.get("modal_ir_hash")
            or ""
        ).strip()
        span_hashes = _json_ready_mapping(sample_hashes.get("source_span_hashes"))
        example: Dict[str, Any] = {
            "compiler_decompiler_metrics": _json_ready_mapping(
                root.get("compiler_decompiler_metrics")
            ),
            "evidence_id": evidence_id,
            "example_id": sample_id or evidence_id,
            "expected_modal_ir_hash": expected_hash,
            "sample_id": sample_id,
            "source_text_hash": str(
                sample_hashes.get("source_text_hash")
                or evidence_hashes.get("source_text_hash")
                or ""
            ).strip(),
        }
        if span_hashes:
            example["source_span_hashes"] = span_hashes
            example["source_span_hash_format"] = "introspection_packet_v1"
        for key in ("citation", "section", "title"):
            value = str(root.get(key) or "").strip()
            if value:
                example[key] = value
        text = str(
            root.get("source_text")
            or root.get("text")
            or root.get("sample_text")
            or ""
        ).strip()
        if text:
            example["source_text"] = text
        key = str(example.get("example_id") or example.get("evidence_id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        examples.append(example)
    return examples


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
            str(
                _json_ready_mapping(_root_record(record).get("run_context")).get(
                    "compiler_commit"
                )
                or ""
            ).strip()
            for record in records
            if str(
                _json_ready_mapping(_root_record(record).get("run_context")).get(
                    "compiler_commit"
                )
                or ""
            ).strip()
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
    generation_attempts: int = 0,
    response_hash: str = "",
    repair_reasons: Sequence[str] = (),
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
        generation_attempts=generation_attempts,
        reasons=tuple(reasons),
        repair_reasons=tuple(repair_reasons),
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
        generation_attempts=int(data.get("generation_attempts") or 0),
        reasons=_string_tuple(data.get("reasons")),
        repair_reasons=_string_tuple(data.get("repair_reasons")),
        response_hash=str(data.get("response_hash") or ""),
        validation=validation,
        elapsed_seconds=float(data.get("elapsed_seconds") or 0.0),
    )


def _checkpoint_reusable_work_keys(
    checkpoint: LeanstralAuditCheckpoint,
) -> set[str]:
    reusable: set[str] = set()
    for work_key in checkpoint.completed_work_keys:
        result = _result_from_checkpoint(work_key, checkpoint.results.get(work_key))
        if _checkpoint_result_is_reusable(result):
            reusable.add(work_key)
    return reusable


def _checkpoint_result_is_reusable(result: LeanstralAuditWorkResult) -> bool:
    if result.status not in {"accepted", "cache_hit"}:
        return False
    validation = result.validation
    return bool(validation is not None and validation.accepted and validation.verified)


def _canonical_provider_identity(provider: Any) -> str:
    value = str(provider or "").strip().lower().replace("-", "_").replace(".", "_")
    aliases = {
        "dry_run": "mock",
        "hf": "local_hf",
        "huggingface": "local_hf",
        "llama_cpp": "leanstral_local",
        "llama_cpp_native": "leanstral_local",
        "llamacpp": "leanstral_local",
        "llamacpp_native": "leanstral_local",
        "local_openai": "leanstral_local",
        "mistral_vibe": "mistral_vibe",
        "native_llama_cpp": "leanstral_local",
        "openai_compatible": "leanstral_local",
        "vibe": "mistral_vibe",
    }
    return aliases.get(value, value)


def _allowed_effective_provider_identities(provider: Any) -> set[str]:
    canonical = _canonical_provider_identity(provider)
    allowed = {canonical}
    if canonical == "leanstral_local":
        allowed.update({"ipfs_accelerate_py", "leanstral_local"})
    return allowed


def _merge_reasons(
    existing: Sequence[str],
    additions: Sequence[str],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(reason)
            for reason in [*existing, *additions]
            if str(reason).strip()
        )
    )


def _provider_attempt_reason(provider: str, reason: str, provider_count: int) -> str:
    reason = str(reason or "").strip()
    if provider_count <= 1:
        return reason
    return f"{_canonical_provider_identity(provider)}:{reason}"


def _attempt_reason_kind(reason: str) -> str:
    value = str(reason or "").strip()
    if ":" not in value:
        return value
    prefix, suffix = value.split(":", 1)
    if _canonical_provider_identity(prefix) in {
        "ipfs_accelerate_py",
        "leanstral_local",
        "local_hf",
        "mistral_vibe",
        "mock",
        "openai",
        "openrouter",
    }:
        return suffix
    return value


def _all_attempt_reasons_match(reasons: Sequence[str], kind: str) -> bool:
    values = tuple(str(reason) for reason in reasons if str(reason).strip())
    return bool(values) and all(
        _attempt_reason_kind(reason) == kind for reason in values
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


def _provider_error_reason(exc: Exception) -> str:
    if isinstance(exc, OSError):
        if exc.errno == errno.E2BIG:
            return "provider_error:OSError:argument_list_too_long"
        if exc.errno == errno.ENOMEM:
            return "provider_error:OSError:out_of_memory"
        if exc.errno == errno.EAGAIN:
            return "provider_error:OSError:resource_temporarily_unavailable"
    message = " ".join(str(exc).split()).replace(":", ";")
    if message:
        return f"provider_error:{exc.__class__.__name__}:{_bounded_text(message, 240)}"
    return f"provider_error:{exc.__class__.__name__}"


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


def _drafted_logic_candidates(value: Any) -> Sequence[Dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    candidates: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            continue
        raw_candidate = (
            item.get("candidate")
            or item.get("logic")
            or item.get("formula")
            or item.get("ir")
            or ""
        )
        candidate_text = str(raw_candidate or "").strip()
        if len(candidate_text) > LEANSTRAL_DRAFTED_LOGIC_MAX_TEXT_CHARS:
            candidate_text = candidate_text[:LEANSTRAL_DRAFTED_LOGIC_MAX_TEXT_CHARS].rstrip()
        if not candidate_text:
            continue
        logic_family = _normalize_token(
            item.get("logic_family")
            or item.get("family")
            or item.get("view")
            or "legal_ir"
        )
        normalized: Dict[str, Any] = {
            "candidate": candidate_text,
            "intended_use": "guidance_only",
            "logic_family": logic_family or "legal_ir",
            "schema_version": LEANSTRAL_DRAFTED_LOGIC_SCHEMA_VERSION,
        }
        for key in (
            "compiler_surface",
            "evidence_id",
            "example_id",
            "proof_obligation_id",
            "request_id",
            "source_span_hash",
            "target_metric",
        ):
            text = str(item.get(key) or "").strip()
            if text:
                normalized[key] = text[:140].rstrip()
        rationale = str(item.get("rationale") or "").strip()
        if rationale:
            normalized["rationale"] = rationale[:140].rstrip()
        confidence = item.get("confidence")
        try:
            confidence_float = float(confidence)
        except (TypeError, ValueError):
            confidence_float = float("nan")
        if math.isfinite(confidence_float):
            normalized["confidence"] = max(0.0, min(1.0, confidence_float))
        identity = json.dumps(
            {
                "candidate": normalized.get("candidate"),
                "logic_family": normalized.get("logic_family"),
                "proof_obligation_id": normalized.get("proof_obligation_id"),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(normalized)
        if len(candidates) >= LEANSTRAL_DRAFTED_LOGIC_MAX_CANDIDATES:
            break
    return tuple(candidates)


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
    "LEANSTRAL_DRAFTED_LOGIC_SCHEMA_VERSION",
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
