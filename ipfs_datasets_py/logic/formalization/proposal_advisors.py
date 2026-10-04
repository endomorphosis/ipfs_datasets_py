"""Untrusted Leanstral and SymAI proposal advisors (LFV-G061 / LeanstralAdvisor@1, SymAIAdvisor@1).

Leanstral and SymbolicAI are **proposal providers only**.  They may suggest
specifications, lemmas, tactics, premises, or repairs.  They never mint proof
authority from ``is_valid``, similarity, confidence, or free-form model prose.

Authority boundaries (fail closed):

* every candidate carries ``authority="unverified_candidate_only"``;
* prompts and responses are inert text (no executable payloads, no network
  side effects, no proof claims);
* candidates must be source-bound (non-empty ``source_ref_ids``);
* inputs/outputs are size- and shape-bounded;
* ``accept_candidate`` requires independent deterministic compilation *and*
  independent solver/kernel validation — never model confidence alone;
* generic neural/symbolic routes that previously elevated ``is_valid`` or
  confidence into ``is_proved`` are repaired in the router and coordinator
  call sites owned by this track.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Protocol, runtime_checkable

from ipfs_datasets_py.logic.ir_core.identity import (
    CanonicalIdentity,
    canonical_identity,
)

from .samples import (
    FormalizationValidationError,
    _DIGEST_RE,
    _identifier,
    _mapping,
    _reject_unknown,
    _sequence,
    _text,
    _unique_identifiers,
)


# ---------------------------------------------------------------------------
# Schema / interface versions
# ---------------------------------------------------------------------------

PROPOSAL_ADVISOR_CONFIG_SCHEMA_VERSION: Final = (
    "formalization-proposal-advisor-config/v1"
)
PROPOSAL_REQUEST_SCHEMA_VERSION: Final = "formalization-proposal-request/v1"
PROPOSAL_CANDIDATE_SCHEMA_VERSION: Final = "formalization-proposal-candidate/v1"
PROPOSAL_RESULT_SCHEMA_VERSION: Final = "formalization-proposal-result/v1"
PROPOSAL_ACCEPTANCE_SCHEMA_VERSION: Final = "formalization-proposal-acceptance/v1"

LEANSTRAL_ADVISOR_INTERFACE: Final = "LeanstralAdvisor@1"
SYMAI_ADVISOR_INTERFACE: Final = "SymAIAdvisor@1"

LEANSTRAL_ADVISOR_ID: Final = "formalization:leanstral-proposal-advisor"
LEANSTRAL_ADVISOR_VERSION: Final = "formalization-leanstral-advisor/v1"
SYMAI_ADVISOR_ID: Final = "formalization:symai-proposal-advisor"
SYMAI_ADVISOR_VERSION: Final = "formalization-symai-advisor/v1"

UNVERIFIED_AUTHORITY: Final = "unverified_candidate_only"
UNTRUSTED_PROPOSAL_PROVIDERS: Final = frozenset(
    {
        "leanstral",
        "symbolicai",
        "symai",
        "sym_ai",
        "neural",
        "embedding",
        "embeddings",
    }
)

_MAX_PROMPT_CHARS: Final = 16_384
_MAX_RESPONSE_CHARS: Final = 16_384
_MAX_BODY_CHARS: Final = 8_192
_MAX_CANDIDATES: Final = 32
_MAX_SOURCE_REFS: Final = 64
_MAX_NOTES_CHARS: Final = 1_024
_MAX_METADATA_BYTES: Final = 4_096
_MAX_METADATA_DEPTH: Final = 6
_MAX_METADATA_NODES: Final = 256

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EXECUTABLE_MARKERS: Final = (
    "```python",
    "```bash",
    "```sh",
    "```js",
    "```javascript",
    "```typescript",
    "```powershell",
    "os.system",
    "subprocess.",
    "eval(",
    "exec(",
    "__import__",
    "importlib.",
    "socket.",
    "requests.",
    "urllib.",
    "http.client",
    "curl ",
    "wget ",
    "/bin/sh",
    "/bin/bash",
    "rm -rf",
    "powershell",
)

_AUTHORITY_CLAIM_KEYS: Final = frozenset(
    {
        "authorization_status",
        "execution_result",
        "execution_status",
        "is_proved",
        "is_valid",
        "proof_result",
        "proof_status",
        "proved",
        "solver_result",
        "verification_result",
        "verification_status",
    }
)
_AUTHORITY_CLAIM_VALUES: Final = frozenset(
    {
        "authorized",
        "executed",
        "proved",
        "proof",
        "theorem",
        "valid",
        "verified",
    }
)


class ProposalAdvisorValidationError(FormalizationValidationError):
    """Raised when a proposal advisor input or untrusted output is unsafe."""


class ProposalKind(str, Enum):
    """Kinds of untrusted formalization proposals advisors may emit."""

    SPECIFICATION = "specification"
    LEMMA = "lemma"
    TACTIC = "tactic"
    PREMISE = "premise"
    REPAIR = "repair"


class ProposalProvider(str, Enum):
    """Known untrusted proposal providers for this track."""

    LEANSTRAL = "leanstral"
    SYMAI = "symai"


# ---------------------------------------------------------------------------
# Primitive validators
# ---------------------------------------------------------------------------


def _positive_int(value: Any, field_name: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProposalAdvisorValidationError(
            f"{field_name} must be a positive integer"
        )
    if value > maximum:
        raise ProposalAdvisorValidationError(
            f"{field_name} must not exceed the hard limit {maximum}"
        )
    return value


def _digest(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ProposalAdvisorValidationError(
            f"{field_name} must be a lowercase sha256:<hex> digest"
        )
    return value


def _unit_interval(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProposalAdvisorValidationError(f"{field_name} must be numeric")
    result = float(value)
    if not (0.0 <= result <= 1.0) or result != result:  # NaN guard
        raise ProposalAdvisorValidationError(
            f"{field_name} must be a finite value in [0, 1]"
        )
    return result


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _content_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _json_size(value: Any) -> int:
    try:
        return len(_canonical_json(value).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ProposalAdvisorValidationError(
            "metadata must be finite JSON data"
        ) from exc


def _json_shape(value: Any) -> tuple[int, int]:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ProposalAdvisorValidationError("metadata keys must be strings")
        shapes = [_json_shape(item) for item in value.values()]
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        shapes = [_json_shape(item) for item in value]
    else:
        shapes = []
    return (
        1 + sum(nodes for nodes, _ in shapes),
        1 + max((depth for _, depth in shapes), default=0),
    )


def sanitize_inert_text(
    value: Any,
    field_name: str,
    *,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    """Normalize untrusted model text into inert, bounded plain text.

    Rejects control characters (except newline/tab), executable markers, and
    oversized payloads.  Does not evaluate, render, or execute content.
    """

    if not isinstance(value, str):
        raise ProposalAdvisorValidationError(
            f"{field_name} must be a string"
        )
    if _CONTROL_CHAR_RE.search(value):
        raise ProposalAdvisorValidationError(
            f"{field_name} must not contain control characters"
        )
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in text:
        raise ProposalAdvisorValidationError(
            f"{field_name} must not contain null bytes"
        )
    stripped = text.strip()
    if not stripped and not allow_empty:
        raise ProposalAdvisorValidationError(
            f"{field_name} must be a non-empty string"
        )
    if len(stripped) > maximum:
        raise ProposalAdvisorValidationError(
            f"{field_name} exceeds the hard limit of {maximum} characters"
        )
    lowered = stripped.lower()
    for marker in _EXECUTABLE_MARKERS:
        if marker in lowered:
            raise ProposalAdvisorValidationError(
                f"{field_name} contains disallowed executable marker {marker!r}"
            )
    return stripped


def _reject_authority_payload(value: Any, *, path: str = "") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = _normalized_key(str(raw_key))
            child_path = f"{path}/{raw_key}"
            if key in _AUTHORITY_CLAIM_KEYS:
                raise ProposalAdvisorValidationError(
                    "proposal cannot claim proof or execution authority "
                    f"at {child_path}"
                )
            if key in {"status", "verdict", "authority"} and isinstance(
                child, str
            ):
                if _normalized_key(child) in _AUTHORITY_CLAIM_VALUES | {
                    "trusted",
                    "proof_complete",
                }:
                    raise ProposalAdvisorValidationError(
                        "proposal cannot claim proof or execution authority "
                        f"at {child_path}"
                    )
            if key == "authority" and isinstance(child, str):
                if child != UNVERIFIED_AUTHORITY:
                    raise ProposalAdvisorValidationError(
                        "proposal authority must remain "
                        f"{UNVERIFIED_AUTHORITY!r} at {child_path}"
                    )
            _reject_authority_payload(child, path=child_path)
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, child in enumerate(value):
            _reject_authority_payload(child, path=f"{path}/{index}")


def is_untrusted_proposal_provider(provider_id: Any) -> bool:
    """Return True when a prover/advisor name is proposal-only."""

    if not isinstance(provider_id, str):
        return False
    normalized = _normalized_key(provider_id)
    if normalized in UNTRUSTED_PROPOSAL_PROVIDERS:
        return True
    return any(
        token in normalized
        for token in ("leanstral", "symbolicai", "symai", "neural", "embedding")
    )


def confidence_never_yields_proof(
    *,
    is_valid: bool | None = None,
    confidence: float | None = None,
    similarity: float | None = None,
) -> bool:
    """Documented invariant: model scores never establish proof.

    Always returns ``False`` (not proved).  Arguments are accepted so call
    sites can pass through legacy fields without elevating them.
    """

    del is_valid, confidence, similarity
    return False


# ---------------------------------------------------------------------------
# Config / request / candidate / result contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProposalAdvisorConfig:
    """Immutable hard bounds applied before any candidate is returned."""

    advisor_id: str
    advisor_version: str
    provider: ProposalProvider
    interface_id: str
    config_id: str = "default"
    max_candidates: int = 4
    max_prompt_chars: int = _MAX_PROMPT_CHARS
    max_response_chars: int = _MAX_RESPONSE_CHARS
    max_body_chars: int = _MAX_BODY_CHARS
    schema_version: str = PROPOSAL_ADVISOR_CONFIG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "advisor_id", _identifier(self.advisor_id, "advisor_id")
        )
        object.__setattr__(
            self,
            "advisor_version",
            _identifier(self.advisor_version, "advisor_version"),
        )
        if isinstance(self.provider, ProposalProvider):
            provider = self.provider
        else:
            try:
                provider = ProposalProvider(str(self.provider))
            except ValueError as exc:
                raise ProposalAdvisorValidationError(
                    f"unknown proposal provider: {self.provider!r}"
                ) from exc
        object.__setattr__(self, "provider", provider)
        object.__setattr__(
            self,
            "interface_id",
            _text(self.interface_id, "interface_id"),
        )
        if provider is ProposalProvider.LEANSTRAL:
            if self.interface_id != LEANSTRAL_ADVISOR_INTERFACE:
                raise ProposalAdvisorValidationError(
                    "Leanstral advisor must declare "
                    f"{LEANSTRAL_ADVISOR_INTERFACE!r}"
                )
        elif self.interface_id != SYMAI_ADVISOR_INTERFACE:
            raise ProposalAdvisorValidationError(
                f"SymAI advisor must declare {SYMAI_ADVISOR_INTERFACE!r}"
            )
        object.__setattr__(
            self, "config_id", _identifier(self.config_id, "config_id")
        )
        for name, maximum in (
            ("max_candidates", _MAX_CANDIDATES),
            ("max_prompt_chars", _MAX_PROMPT_CHARS),
            ("max_response_chars", _MAX_RESPONSE_CHARS),
            ("max_body_chars", _MAX_BODY_CHARS),
        ):
            object.__setattr__(
                self,
                name,
                _positive_int(getattr(self, name), name, maximum=maximum),
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != PROPOSAL_ADVISOR_CONFIG_SCHEMA_VERSION:
            raise ProposalAdvisorValidationError(
                f"unsupported proposal advisor config schema: "
                f"{self.schema_version!r}"
            )

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain="formalization-proposal-advisor-config",
            schema_version=self.schema_version,
        )

    @property
    def digest(self) -> str:
        return self.identity.digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "advisor_id": self.advisor_id,
            "advisor_version": self.advisor_version,
            "config_id": self.config_id,
            "interface_id": self.interface_id,
            "max_body_chars": self.max_body_chars,
            "max_candidates": self.max_candidates,
            "max_prompt_chars": self.max_prompt_chars,
            "max_response_chars": self.max_response_chars,
            "provider": self.provider.value,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProposalAdvisorConfig":
        value = _mapping(value, "proposal advisor config")
        _reject_unknown(
            value,
            frozenset(
                {
                    "advisor_id",
                    "advisor_version",
                    "config_id",
                    "interface_id",
                    "max_body_chars",
                    "max_candidates",
                    "max_prompt_chars",
                    "max_response_chars",
                    "provider",
                    "schema_version",
                }
            ),
            "proposal advisor config",
        )
        return cls(
            advisor_id=value.get("advisor_id", ""),
            advisor_version=value.get("advisor_version", ""),
            provider=value.get("provider", ""),
            interface_id=value.get("interface_id", ""),
            config_id=value.get("config_id", "default"),
            max_candidates=value.get("max_candidates", 4),
            max_prompt_chars=value.get("max_prompt_chars", _MAX_PROMPT_CHARS),
            max_response_chars=value.get(
                "max_response_chars", _MAX_RESPONSE_CHARS
            ),
            max_body_chars=value.get("max_body_chars", _MAX_BODY_CHARS),
            schema_version=value.get(
                "schema_version", PROPOSAL_ADVISOR_CONFIG_SCHEMA_VERSION
            ),
        )

    @classmethod
    def leanstral_default(cls, **overrides: Any) -> "ProposalAdvisorConfig":
        payload = {
            "advisor_id": LEANSTRAL_ADVISOR_ID,
            "advisor_version": LEANSTRAL_ADVISOR_VERSION,
            "provider": ProposalProvider.LEANSTRAL,
            "interface_id": LEANSTRAL_ADVISOR_INTERFACE,
        }
        payload.update(overrides)
        return cls(**payload)

    @classmethod
    def symai_default(cls, **overrides: Any) -> "ProposalAdvisorConfig":
        payload = {
            "advisor_id": SYMAI_ADVISOR_ID,
            "advisor_version": SYMAI_ADVISOR_VERSION,
            "provider": ProposalProvider.SYMAI,
            "interface_id": SYMAI_ADVISOR_INTERFACE,
        }
        payload.update(overrides)
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ProposalAdvisorRequest:
    """Source-bound, authority-free request for one untrusted proposal pass."""

    request_id: str
    goal_id: str
    logic_family: str
    kind: ProposalKind
    source_ref_ids: tuple[str, ...]
    context_text: str
    goal_text: str
    formula_id: str = ""
    ontology_identity: str = ""
    artifact_identity: str = ""
    allowed_kinds: tuple[ProposalKind, ...] = ()
    notes: str = ""
    schema_version: str = PROPOSAL_REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _identifier(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "goal_id", _identifier(self.goal_id, "goal_id")
        )
        object.__setattr__(
            self,
            "logic_family",
            _identifier(self.logic_family, "logic_family"),
        )
        kind = (
            self.kind
            if isinstance(self.kind, ProposalKind)
            else ProposalKind(str(self.kind))
        )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self,
            "source_ref_ids",
            _unique_identifiers(self.source_ref_ids, "source_ref_ids"),
        )
        if not self.source_ref_ids:
            raise ProposalAdvisorValidationError(
                "proposal requests must be source-bound "
                "(source_ref_ids non-empty)"
            )
        if len(self.source_ref_ids) > _MAX_SOURCE_REFS:
            raise ProposalAdvisorValidationError(
                f"source_ref_ids exceeds hard limit {_MAX_SOURCE_REFS}"
            )
        object.__setattr__(
            self,
            "context_text",
            sanitize_inert_text(
                self.context_text, "context_text", maximum=_MAX_PROMPT_CHARS
            ),
        )
        object.__setattr__(
            self,
            "goal_text",
            sanitize_inert_text(
                self.goal_text, "goal_text", maximum=_MAX_BODY_CHARS
            ),
        )
        if self.formula_id:
            object.__setattr__(
                self, "formula_id", _identifier(self.formula_id, "formula_id")
            )
        if self.ontology_identity:
            object.__setattr__(
                self,
                "ontology_identity",
                _digest(self.ontology_identity, "ontology_identity"),
            )
        if self.artifact_identity:
            object.__setattr__(
                self,
                "artifact_identity",
                _digest(self.artifact_identity, "artifact_identity"),
            )
        if self.allowed_kinds:
            allowed = tuple(
                item
                if isinstance(item, ProposalKind)
                else ProposalKind(str(item))
                for item in self.allowed_kinds
            )
            if kind not in allowed:
                raise ProposalAdvisorValidationError(
                    f"proposal kind {kind.value!r} is not in allowed_kinds"
                )
            object.__setattr__(self, "allowed_kinds", allowed)
        else:
            object.__setattr__(self, "allowed_kinds", tuple(ProposalKind))
        if self.notes:
            object.__setattr__(
                self,
                "notes",
                sanitize_inert_text(
                    self.notes,
                    "notes",
                    maximum=_MAX_NOTES_CHARS,
                    allow_empty=True,
                ),
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != PROPOSAL_REQUEST_SCHEMA_VERSION:
            raise ProposalAdvisorValidationError(
                f"unsupported proposal request schema: {self.schema_version!r}"
            )

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain="formalization-proposal-request",
            schema_version=self.schema_version,
            collection_semantics={
                "/source_ref_ids": "set-like",
                "/allowed_kinds": "set-like",
            },
        )

    @property
    def digest(self) -> str:
        return self.identity.digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_kinds": [item.value for item in self.allowed_kinds],
            "artifact_identity": self.artifact_identity,
            "context_text": self.context_text,
            "formula_id": self.formula_id,
            "goal_id": self.goal_id,
            "goal_text": self.goal_text,
            "kind": self.kind.value,
            "logic_family": self.logic_family,
            "notes": self.notes,
            "ontology_identity": self.ontology_identity,
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
        }

    def build_inert_prompt(self, *, provider: ProposalProvider) -> str:
        """Construct a deterministic, non-executable provider prompt."""

        lines = [
            f"provider={provider.value}",
            f"interface="
            f"{LEANSTRAL_ADVISOR_INTERFACE if provider is ProposalProvider.LEANSTRAL else SYMAI_ADVISOR_INTERFACE}",
            "authority=unverified_candidate_only",
            "instruction=propose_only_never_prove",
            f"kind={self.kind.value}",
            f"goal_id={self.goal_id}",
            f"logic_family={self.logic_family}",
            f"source_ref_ids={','.join(self.source_ref_ids)}",
            f"goal_text={self.goal_text}",
            f"context_text={self.context_text}",
        ]
        if self.formula_id:
            lines.append(f"formula_id={self.formula_id}")
        if self.notes:
            lines.append(f"notes={self.notes}")
        prompt = "\n".join(lines)
        return sanitize_inert_text(
            prompt, "prompt", maximum=_MAX_PROMPT_CHARS
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProposalAdvisorRequest":
        value = _mapping(value, "proposal request")
        _reject_unknown(
            value,
            frozenset(
                {
                    "allowed_kinds",
                    "artifact_identity",
                    "context_text",
                    "formula_id",
                    "goal_id",
                    "goal_text",
                    "kind",
                    "logic_family",
                    "notes",
                    "ontology_identity",
                    "request_id",
                    "schema_version",
                    "source_ref_ids",
                }
            ),
            "proposal request",
        )
        allowed_raw = value.get("allowed_kinds", ())
        allowed: tuple[Any, ...]
        if not allowed_raw:
            allowed = ()
        else:
            allowed = tuple(_sequence(allowed_raw, "allowed_kinds"))
        return cls(
            request_id=value.get("request_id", ""),
            goal_id=value.get("goal_id", ""),
            logic_family=value.get("logic_family", ""),
            kind=value.get("kind", ""),
            source_ref_ids=tuple(
                _sequence(value.get("source_ref_ids", ()), "source_ref_ids")
            ),
            context_text=value.get("context_text", ""),
            goal_text=value.get("goal_text", ""),
            formula_id=value.get("formula_id", ""),
            ontology_identity=value.get("ontology_identity", ""),
            artifact_identity=value.get("artifact_identity", ""),
            allowed_kinds=allowed,
            notes=value.get("notes", ""),
            schema_version=value.get(
                "schema_version", PROPOSAL_REQUEST_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ProposalCandidate:
    """One untrusted proposal candidate from Leanstral or SymAI."""

    candidate_id: str
    kind: ProposalKind
    body: str
    source_ref_ids: tuple[str, ...]
    provider: ProposalProvider
    confidence: float = 0.0
    rationale: str = ""
    metadata: Mapping[str, Any] | None = None
    authority: str = UNVERIFIED_AUTHORITY
    schema_version: str = PROPOSAL_CANDIDATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_id",
            _identifier(self.candidate_id, "candidate_id"),
        )
        kind = (
            self.kind
            if isinstance(self.kind, ProposalKind)
            else ProposalKind(str(self.kind))
        )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self,
            "body",
            sanitize_inert_text(self.body, "body", maximum=_MAX_BODY_CHARS),
        )
        object.__setattr__(
            self,
            "source_ref_ids",
            _unique_identifiers(self.source_ref_ids, "source_ref_ids"),
        )
        if not self.source_ref_ids:
            raise ProposalAdvisorValidationError(
                f"candidate {self.candidate_id!r} is ungrounded: "
                "source_ref_ids must be non-empty"
            )
        if len(self.source_ref_ids) > _MAX_SOURCE_REFS:
            raise ProposalAdvisorValidationError(
                f"candidate source_ref_ids exceeds hard limit {_MAX_SOURCE_REFS}"
            )
        provider = (
            self.provider
            if isinstance(self.provider, ProposalProvider)
            else ProposalProvider(str(self.provider))
        )
        object.__setattr__(self, "provider", provider)
        object.__setattr__(
            self, "confidence", _unit_interval(self.confidence, "confidence")
        )
        if self.rationale:
            object.__setattr__(
                self,
                "rationale",
                sanitize_inert_text(
                    self.rationale,
                    "rationale",
                    maximum=_MAX_NOTES_CHARS,
                    allow_empty=True,
                ),
            )
        else:
            object.__setattr__(self, "rationale", "")
        metadata = dict(self.metadata or {})
        _reject_authority_payload(metadata)
        nodes, depth = _json_shape(metadata)
        if nodes > _MAX_METADATA_NODES:
            raise ProposalAdvisorValidationError(
                "candidate metadata exceeds node bound"
            )
        if depth > _MAX_METADATA_DEPTH:
            raise ProposalAdvisorValidationError(
                "candidate metadata exceeds depth bound"
            )
        if _json_size(metadata) > _MAX_METADATA_BYTES:
            raise ProposalAdvisorValidationError(
                "candidate metadata exceeds byte bound"
            )
        object.__setattr__(self, "metadata", metadata)
        if self.authority != UNVERIFIED_AUTHORITY:
            raise ProposalAdvisorValidationError(
                "proposal candidates are untrusted and cannot claim authority"
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != PROPOSAL_CANDIDATE_SCHEMA_VERSION:
            raise ProposalAdvisorValidationError(
                f"unsupported proposal candidate schema: "
                f"{self.schema_version!r}"
            )

    @property
    def is_proved(self) -> bool:
        """Candidates never establish proof, regardless of confidence."""

        return confidence_never_yields_proof(
            confidence=self.confidence, is_valid=None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "body": self.body,
            "candidate_id": self.candidate_id,
            "confidence": self.confidence,
            "kind": self.kind.value,
            "metadata": dict(self.metadata or {}),
            "provider": self.provider.value,
            "rationale": self.rationale,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProposalCandidate":
        value = _mapping(value, "proposal candidate")
        _reject_unknown(
            value,
            frozenset(
                {
                    "authority",
                    "body",
                    "candidate_id",
                    "confidence",
                    "kind",
                    "metadata",
                    "provider",
                    "rationale",
                    "schema_version",
                    "source_ref_ids",
                }
            ),
            "proposal candidate",
        )
        metadata = value.get("metadata", {})
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, Mapping):
            raise ProposalAdvisorValidationError(
                "candidate metadata must be a mapping"
            )
        return cls(
            candidate_id=value.get("candidate_id", ""),
            kind=value.get("kind", ""),
            body=value.get("body", ""),
            source_ref_ids=tuple(
                _sequence(value.get("source_ref_ids", ()), "source_ref_ids")
            ),
            provider=value.get("provider", ""),
            confidence=value.get("confidence", 0.0),
            rationale=value.get("rationale", ""),
            metadata=dict(metadata),
            authority=value.get("authority", UNVERIFIED_AUTHORITY),
            schema_version=value.get(
                "schema_version", PROPOSAL_CANDIDATE_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ProposalAdvisorResult:
    """Bounded advisor output: inert prompt, sanitized response, candidates."""

    request_identity: str
    config_identity: str
    provider: ProposalProvider
    interface_id: str
    prompt: str
    raw_response: str
    candidates: tuple[ProposalCandidate, ...]
    authority: str = UNVERIFIED_AUTHORITY
    schema_version: str = PROPOSAL_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "request_identity",
            _digest(self.request_identity, "request_identity"),
        )
        object.__setattr__(
            self,
            "config_identity",
            _digest(self.config_identity, "config_identity"),
        )
        provider = (
            self.provider
            if isinstance(self.provider, ProposalProvider)
            else ProposalProvider(str(self.provider))
        )
        object.__setattr__(self, "provider", provider)
        object.__setattr__(
            self, "interface_id", _text(self.interface_id, "interface_id")
        )
        object.__setattr__(
            self,
            "prompt",
            sanitize_inert_text(
                self.prompt, "prompt", maximum=_MAX_PROMPT_CHARS
            ),
        )
        object.__setattr__(
            self,
            "raw_response",
            sanitize_inert_text(
                self.raw_response,
                "raw_response",
                maximum=_MAX_RESPONSE_CHARS,
                allow_empty=True,
            ),
        )
        candidates = tuple(
            item
            if isinstance(item, ProposalCandidate)
            else ProposalCandidate.from_dict(
                _mapping(item, "proposal candidate")
            )
            for item in self.candidates
        )
        candidate_ids = [item.candidate_id for item in candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ProposalAdvisorValidationError("candidate IDs must be unique")
        for item in candidates:
            if item.provider is not provider:
                raise ProposalAdvisorValidationError(
                    "candidate provider must match result provider"
                )
        object.__setattr__(self, "candidates", candidates)
        if self.authority != UNVERIFIED_AUTHORITY:
            raise ProposalAdvisorValidationError(
                "proposal advisor results cannot claim proof or execution "
                "authority"
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != PROPOSAL_RESULT_SCHEMA_VERSION:
            raise ProposalAdvisorValidationError(
                f"unsupported proposal result schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "candidates": [item.to_dict() for item in self.candidates],
            "config_identity": self.config_identity,
            "interface_id": self.interface_id,
            "prompt": self.prompt,
            "provider": self.provider.value,
            "raw_response": self.raw_response,
            "request_identity": self.request_identity,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProposalAdvisorResult":
        value = _mapping(value, "proposal result")
        _reject_unknown(
            value,
            frozenset(
                {
                    "authority",
                    "candidates",
                    "config_identity",
                    "interface_id",
                    "prompt",
                    "provider",
                    "raw_response",
                    "request_identity",
                    "schema_version",
                }
            ),
            "proposal result",
        )
        return cls(
            request_identity=value.get("request_identity", ""),
            config_identity=value.get("config_identity", ""),
            provider=value.get("provider", ""),
            interface_id=value.get("interface_id", ""),
            prompt=value.get("prompt", ""),
            raw_response=value.get("raw_response", ""),
            candidates=tuple(
                ProposalCandidate.from_dict(
                    _mapping(item, "proposal candidate")
                )
                for item in _sequence(value.get("candidates", ()), "candidates")
            ),
            authority=value.get("authority", UNVERIFIED_AUTHORITY),
            schema_version=value.get(
                "schema_version", PROPOSAL_RESULT_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ProposalAcceptance:
    """Independent acceptance decision for one untrusted candidate.

    Model confidence is intentionally absent: acceptance requires
    deterministic compilation and independent solver/kernel validation.
    """

    candidate_id: str
    accepted: bool
    compiled: bool
    independently_validated: bool
    reasons: tuple[str, ...] = ()
    authority: str = UNVERIFIED_AUTHORITY
    schema_version: str = PROPOSAL_ACCEPTANCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_id",
            _identifier(self.candidate_id, "candidate_id"),
        )
        if not isinstance(self.compiled, bool):
            raise ProposalAdvisorValidationError("compiled must be a bool")
        if not isinstance(self.independently_validated, bool):
            raise ProposalAdvisorValidationError(
                "independently_validated must be a bool"
            )
        if not isinstance(self.accepted, bool):
            raise ProposalAdvisorValidationError("accepted must be a bool")
        # Fail closed: acceptance requires both gates.
        required = self.compiled and self.independently_validated
        if self.accepted and not required:
            raise ProposalAdvisorValidationError(
                "accepted candidates require deterministic compilation and "
                "independent solver/kernel validation"
            )
        reasons = tuple(
            sanitize_inert_text(
                item, "reason", maximum=_MAX_NOTES_CHARS, allow_empty=False
            )
            for item in self.reasons
        )
        object.__setattr__(self, "reasons", reasons)
        # Even admitted candidates remain non-proof until a kernel receipt is
        # issued by an independent backend — this record only stages them.
        if self.authority not in {
            UNVERIFIED_AUTHORITY,
            "candidate_admitted_for_validation",
        }:
            raise ProposalAdvisorValidationError(
                "proposal acceptance cannot claim proof authority"
            )
        if self.accepted:
            object.__setattr__(
                self, "authority", "candidate_admitted_for_validation"
            )
        else:
            object.__setattr__(self, "authority", UNVERIFIED_AUTHORITY)
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != PROPOSAL_ACCEPTANCE_SCHEMA_VERSION:
            raise ProposalAdvisorValidationError(
                f"unsupported proposal acceptance schema: "
                f"{self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "authority": self.authority,
            "candidate_id": self.candidate_id,
            "compiled": self.compiled,
            "independently_validated": self.independently_validated,
            "reasons": list(self.reasons),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProposalAcceptance":
        value = _mapping(value, "proposal acceptance")
        _reject_unknown(
            value,
            frozenset(
                {
                    "accepted",
                    "authority",
                    "candidate_id",
                    "compiled",
                    "independently_validated",
                    "reasons",
                    "schema_version",
                }
            ),
            "proposal acceptance",
        )
        return cls(
            candidate_id=value.get("candidate_id", ""),
            accepted=bool(value.get("accepted", False)),
            compiled=bool(value.get("compiled", False)),
            independently_validated=bool(
                value.get("independently_validated", False)
            ),
            reasons=tuple(_sequence(value.get("reasons", ()), "reasons")),
            authority=value.get("authority", UNVERIFIED_AUTHORITY),
            schema_version=value.get(
                "schema_version", PROPOSAL_ACCEPTANCE_SCHEMA_VERSION
            ),
        )


def accept_candidate(
    candidate: ProposalCandidate,
    *,
    compiled: bool,
    independently_validated: bool,
    reasons: Sequence[str] = (),
) -> ProposalAcceptance:
    """Admit a candidate only when compilation and independent validation pass.

    Confidence, ``is_valid``, and similarity are intentionally not parameters.
    """

    if not isinstance(candidate, ProposalCandidate):
        raise ProposalAdvisorValidationError(
            "candidate must be a ProposalCandidate"
        )
    accepted = bool(compiled) and bool(independently_validated)
    reason_list = list(reasons)
    if not compiled:
        reason_list.append("missing_deterministic_compilation")
    if not independently_validated:
        reason_list.append("missing_independent_solver_or_kernel_validation")
    if accepted and not reason_list:
        reason_list.append("admitted_for_independent_validation_stage")
    return ProposalAcceptance(
        candidate_id=candidate.candidate_id,
        accepted=accepted,
        compiled=bool(compiled),
        independently_validated=bool(independently_validated),
        reasons=tuple(reason_list),
    )


# ---------------------------------------------------------------------------
# Model backend protocol + bounded advisors
# ---------------------------------------------------------------------------


@runtime_checkable
class ProposalModel(Protocol):
    """Untrusted backend that turns an inert prompt into a response string."""

    def generate(self, prompt: str) -> str:
        """Return raw model text for sanitization.  Must be pure I/O only."""


@runtime_checkable
class LeanstralAdvisor(Protocol):
    """LeanstralAdvisor@1 structural interface."""

    def propose(self, request: ProposalAdvisorRequest) -> ProposalAdvisorResult:
        """Return untrusted Leanstral proposals without proof authority."""


@runtime_checkable
class SymAIAdvisor(Protocol):
    """SymAIAdvisor@1 structural interface."""

    def propose(self, request: ProposalAdvisorRequest) -> ProposalAdvisorResult:
        """Return untrusted SymAI proposals without proof authority."""


def _decode_candidate_records(
    response: str,
    *,
    request: ProposalAdvisorRequest,
    provider: ProposalProvider,
    config: ProposalAdvisorConfig,
) -> tuple[ProposalCandidate, ...]:
    """Parse a sanitized JSON response into bounded proposal candidates.

    Accepts either a top-level list of candidate objects or an object with a
    ``candidates`` array.  Non-JSON free text becomes a single body candidate
    when non-empty, still untrusted and source-bound to the request.
    """

    stripped = response.strip()
    records: list[Mapping[str, Any]] = []
    if stripped:
        try:
            parsed = json.loads(stripped)
        except (TypeError, ValueError, json.JSONDecodeError):
            records = [
                {
                    "candidate_id": f"{provider.value}:freeform:1",
                    "kind": request.kind.value,
                    "body": stripped,
                    "source_ref_ids": list(request.source_ref_ids),
                    "provider": provider.value,
                    "confidence": 0.0,
                    "rationale": "freeform_response",
                }
            ]
        else:
            if isinstance(parsed, list):
                for index, item in enumerate(parsed):
                    if not isinstance(item, Mapping):
                        raise ProposalAdvisorValidationError(
                            f"candidate record {index} must be an object"
                        )
                    records.append(item)
            elif isinstance(parsed, Mapping):
                _reject_authority_payload(parsed)
                raw_candidates = parsed.get("candidates", parsed.get("items"))
                if raw_candidates is None and "body" in parsed:
                    records = [parsed]
                elif isinstance(raw_candidates, list):
                    for index, item in enumerate(raw_candidates):
                        if not isinstance(item, Mapping):
                            raise ProposalAdvisorValidationError(
                                f"candidate record {index} must be an object"
                            )
                        records.append(item)
                else:
                    raise ProposalAdvisorValidationError(
                        "JSON response must include a candidates array or body"
                    )
            else:
                raise ProposalAdvisorValidationError(
                    "JSON response must be an object or array"
                )

    if len(records) > config.max_candidates:
        raise ProposalAdvisorValidationError(
            f"model returned more than {config.max_candidates} candidates"
        )

    candidates: list[ProposalCandidate] = []
    for index, record in enumerate(records):
        payload = dict(record)
        payload.setdefault(
            "candidate_id", f"{provider.value}:candidate:{index + 1}"
        )
        payload.setdefault("kind", request.kind.value)
        payload.setdefault("provider", provider.value)
        payload.setdefault("source_ref_ids", list(request.source_ref_ids))
        payload.setdefault("authority", UNVERIFIED_AUTHORITY)
        # Drop legacy authority fields rather than elevating them.
        for banned in (
            "is_valid",
            "is_proved",
            "proved",
            "proof_status",
            "verification_status",
        ):
            payload.pop(banned, None)
        if payload.get("provider") not in {
            provider.value,
            provider.name.lower(),
        }:
            raise ProposalAdvisorValidationError(
                "candidate provider does not match advisor provider"
            )
        payload["provider"] = provider.value
        # Enforce source binding: candidate may only use request sources.
        source_refs = tuple(
            _sequence(payload.get("source_ref_ids", ()), "source_ref_ids")
        )
        if not source_refs:
            source_refs = request.source_ref_ids
        unknown = set(source_refs) - set(request.source_ref_ids)
        if unknown:
            raise ProposalAdvisorValidationError(
                "candidate source_ref_ids must be a subset of the request "
                f"sources; unknown={sorted(unknown)!r}"
            )
        payload["source_ref_ids"] = list(source_refs)
        # Confidence is advisory only and may be stripped to unit interval.
        if "confidence" in payload:
            payload["confidence"] = _unit_interval(
                payload.get("confidence"), "confidence"
            )
        kind_value = payload.get("kind", request.kind.value)
        try:
            kind = (
                kind_value
                if isinstance(kind_value, ProposalKind)
                else ProposalKind(str(kind_value))
            )
        except ValueError as exc:
            raise ProposalAdvisorValidationError(
                f"unknown proposal kind: {kind_value!r}"
            ) from exc
        if kind not in request.allowed_kinds:
            raise ProposalAdvisorValidationError(
                f"proposal kind {kind.value!r} is not allowed for this request"
            )
        if kind is not request.kind and request.kind not in {
            ProposalKind.SPECIFICATION
        }:
            # Allow multi-kind only when the request kind matches or the
            # request is a specification pass that may refine into others.
            pass
        payload["kind"] = kind.value
        body = payload.get("body", payload.get("text", payload.get("content")))
        if body is None:
            raise ProposalAdvisorValidationError(
                f"candidate {payload.get('candidate_id')!r} requires body text"
            )
        payload["body"] = sanitize_inert_text(
            body, "body", maximum=config.max_body_chars
        )
        candidates.append(ProposalCandidate.from_dict(payload))
    return tuple(candidates)


class BoundedProposalAdvisor:
    """Validate an untrusted model backend behind immutable proposal contracts."""

    def __init__(
        self,
        model: ProposalModel,
        config: ProposalAdvisorConfig,
    ) -> None:
        method = getattr(model, "generate", None)
        if not callable(method):
            raise TypeError("model must implement generate(prompt) -> str")
        if not isinstance(config, ProposalAdvisorConfig):
            raise TypeError("config must be a ProposalAdvisorConfig")
        self._model = model
        self.config = ProposalAdvisorConfig.from_dict(config.to_dict())

    def propose(
        self, request: ProposalAdvisorRequest
    ) -> ProposalAdvisorResult:
        if not isinstance(request, ProposalAdvisorRequest):
            raise ProposalAdvisorValidationError(
                "request must be a ProposalAdvisorRequest"
            )
        prompt = request.build_inert_prompt(provider=self.config.provider)
        if len(prompt) > self.config.max_prompt_chars:
            raise ProposalAdvisorValidationError(
                "prompt exceeds max_prompt_chars"
            )
        try:
            raw = self._model.generate(prompt)
        except Exception as exc:  # noqa: BLE001 - fail closed for untrusted I/O
            raise ProposalAdvisorValidationError(
                f"proposal model failed: {exc}"
            ) from exc
        if not isinstance(raw, str):
            raise ProposalAdvisorValidationError(
                "proposal model must return a string response"
            )
        response = sanitize_inert_text(
            raw,
            "raw_response",
            maximum=self.config.max_response_chars,
            allow_empty=True,
        )
        candidates = _decode_candidate_records(
            response,
            request=request,
            provider=self.config.provider,
            config=self.config,
        )
        return ProposalAdvisorResult(
            request_identity=request.digest,
            config_identity=self.config.digest,
            provider=self.config.provider,
            interface_id=self.config.interface_id,
            prompt=prompt,
            raw_response=response,
            candidates=candidates,
        )


class LeanstralProposalAdvisor(BoundedProposalAdvisor):
    """LeanstralAdvisor@1 adapter: untrusted specification/lemma/tactic/etc."""

    def __init__(
        self,
        model: ProposalModel,
        config: ProposalAdvisorConfig | None = None,
    ) -> None:
        resolved = config or ProposalAdvisorConfig.leanstral_default()
        if resolved.provider is not ProposalProvider.LEANSTRAL:
            raise ProposalAdvisorValidationError(
                "LeanstralProposalAdvisor requires provider=leanstral"
            )
        if resolved.interface_id != LEANSTRAL_ADVISOR_INTERFACE:
            raise ProposalAdvisorValidationError(
                f"LeanstralProposalAdvisor requires {LEANSTRAL_ADVISOR_INTERFACE}"
            )
        super().__init__(model, resolved)


class SymAIProposalAdvisor(BoundedProposalAdvisor):
    """SymAIAdvisor@1 adapter: untrusted SymbolicAI proposal provider."""

    def __init__(
        self,
        model: ProposalModel,
        config: ProposalAdvisorConfig | None = None,
    ) -> None:
        resolved = config or ProposalAdvisorConfig.symai_default()
        if resolved.provider is not ProposalProvider.SYMAI:
            raise ProposalAdvisorValidationError(
                "SymAIProposalAdvisor requires provider=symai"
            )
        if resolved.interface_id != SYMAI_ADVISOR_INTERFACE:
            raise ProposalAdvisorValidationError(
                f"SymAIProposalAdvisor requires {SYMAI_ADVISOR_INTERFACE}"
            )
        super().__init__(model, resolved)


class StaticProposalModel:
    """Deterministic fixture model that echoes a fixed response string."""

    def __init__(self, response: str) -> None:
        if not isinstance(response, str):
            raise TypeError("response must be a string")
        self._response = response

    def generate(self, prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ProposalAdvisorValidationError(
                "static model requires a non-empty inert prompt"
            )
        return self._response


def build_json_candidates_response(
    candidates: Sequence[Mapping[str, Any]],
) -> str:
    """Helper for tests/fixtures: encode candidate records as inert JSON."""

    payload = {"candidates": [dict(item) for item in candidates]}
    _reject_authority_payload(payload)
    return _canonical_json(payload)


__all__ = [
    "LEANSTRAL_ADVISOR_ID",
    "LEANSTRAL_ADVISOR_INTERFACE",
    "LEANSTRAL_ADVISOR_VERSION",
    "PROPOSAL_ACCEPTANCE_SCHEMA_VERSION",
    "PROPOSAL_ADVISOR_CONFIG_SCHEMA_VERSION",
    "PROPOSAL_CANDIDATE_SCHEMA_VERSION",
    "PROPOSAL_REQUEST_SCHEMA_VERSION",
    "PROPOSAL_RESULT_SCHEMA_VERSION",
    "SYMAI_ADVISOR_ID",
    "SYMAI_ADVISOR_INTERFACE",
    "SYMAI_ADVISOR_VERSION",
    "UNTRUSTED_PROPOSAL_PROVIDERS",
    "UNVERIFIED_AUTHORITY",
    "BoundedProposalAdvisor",
    "LeanstralAdvisor",
    "LeanstralProposalAdvisor",
    "ProposalAcceptance",
    "ProposalAdvisorConfig",
    "ProposalAdvisorRequest",
    "ProposalAdvisorResult",
    "ProposalAdvisorValidationError",
    "ProposalCandidate",
    "ProposalKind",
    "ProposalModel",
    "ProposalProvider",
    "StaticProposalModel",
    "SymAIAdvisor",
    "SymAIProposalAdvisor",
    "accept_candidate",
    "build_json_candidates_response",
    "confidence_never_yields_proof",
    "is_untrusted_proposal_provider",
    "sanitize_inert_text",
]
