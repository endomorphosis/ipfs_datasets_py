"""Structured Leanstral audit contracts and content-addressed cache.

This module keeps Leanstral audit output machine-readable and reviewable.  A
cache hit is only usable when the cached response still matches the current
evidence, prompt, model, theorem registry, schemas, and local verifier result.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence


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
        return {
            "allowed_classifications": sorted(ALLOWED_AUDIT_CLASSIFICATIONS),
            "instructions": [
                "Return strict JSON only.",
                "Classify the legal-IR semantic audit using one allowed classification.",
                "For non-abstention findings, include a counterexample or witness.",
                "For issue findings, identify the missing semantic rule and compiler surface.",
                "Use only proof_obligation_ids from the request.",
                "Set abstention_reason when and only when classification is abstain.",
            ],
            "request": self.to_dict(),
            "response_schema": LEANSTRAL_AUDIT_RESPONSE_SCHEMA,
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
            abstention_reason=str(data.get("abstention_reason", "")).strip(),
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
    "LeanstralAuditCache",
    "LeanstralAuditCacheEntry",
    "LeanstralAuditConfig",
    "LeanstralAuditRequest",
    "LeanstralAuditResponse",
    "LeanstralAuditResult",
    "LeanstralAuditRunner",
    "LeanstralAuditValidation",
    "build_leanstral_audit_cache_key",
    "cache_entry_is_current",
    "canonical_sha256",
    "parse_leanstral_audit_response",
    "validate_leanstral_audit_response",
]
