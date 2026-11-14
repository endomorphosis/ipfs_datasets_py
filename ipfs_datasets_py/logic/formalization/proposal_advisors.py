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


# Explicit source-only token generation. Legacy text/advice contracts above stay
# unchanged. Rich retrieval must use a separately versioned permission validator;
# this initial profile deliberately has no caller-asserted context permission.
SOURCE_CONDITIONED_TYPED_IR_PROFILE: Final = "source-only-typed-ir-proposal/v1"
SOURCE_CONDITIONED_TYPED_IR_RESULT: Final = "source-only-typed-ir-proposal-result/v1"


@runtime_checkable
class SourceConditionedTokenModel(Protocol):
    """Caller-owned token backend; this protocol loads no model or assets."""

    def binding_metadata(self) -> Mapping[str, Any]: ...

    def generate_token_ids(
        self, input_ids: tuple[int, ...], *, decoder_prefix_ids: tuple[int, ...],
        max_new_tokens: int,
    ) -> Sequence[int] | None:
        """Return the actual BOS-to-output history, or explicitly abstain."""


@runtime_checkable
class SourceConditionedTokenizer(Protocol):
    """Lossless token transport for this explicit source-only profile."""

    def binding_metadata(self) -> Mapping[str, Any]: ...

    def encode(self, text: str) -> Sequence[int]: ...

    def decode(self, token_ids: tuple[int, ...]) -> str: ...


def _proposal_token_ids(value: Any, *, maximum: int) -> tuple[int, ...]:
    if type(value) not in (list, tuple) or len(value) > maximum:
        raise ProposalAdvisorValidationError("bounded ordinary token sequence required")
    if any(type(item) is not int or not 0 <= item < 2**31 for item in value):
        raise ProposalAdvisorValidationError("plain nonnegative integer token IDs required")
    return tuple(value)


def _require_no_discarded_fields(offered: Any, canonical: Any) -> None:
    """Allow determined defaults/types, but never ignore supplied AST fields."""
    if isinstance(offered, dict):
        if not isinstance(canonical, dict) or not set(offered) <= set(canonical):
            raise ProposalAdvisorValidationError("typed IR contains unsupported fields")
        for name, item in offered.items():
            if name == "content_digest" and item == "":
                continue  # The canonical AST owner computes its derived digest.
            _require_no_discarded_fields(item, canonical[name])
    elif isinstance(offered, list):
        if not isinstance(canonical, list) or len(offered) != len(canonical):
            raise ProposalAdvisorValidationError("typed IR loses ordered structure")
        for left, right in zip(offered, canonical):
            _require_no_discarded_fields(left, right)
    elif type(offered) is not type(canonical) or offered != canonical:
        raise ProposalAdvisorValidationError("typed IR changes a supplied value")


def _propose_source_conditioned_payload(
    model: SourceConditionedTokenModel, tokenizer: SourceConditionedTokenizer, *,
    request_id: str, source_text: str, source_ref_ids: tuple[str, ...],
    source_revision: str, expected_source_sha256: str,
    expected_model_binding_sha256: str, expected_tokenizer_binding_sha256: str,
    expected_family: str, expected_profile: str,
    max_input_tokens: int, max_new_tokens: int, max_output_bytes: int = 1_048_576,
    context_profile: str = "none", rich_context: object = None,
    _known_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate one untrusted complete typed-AST proposal from original source.

    The caller supplies an already constructed, authorized model and tokenizer.
    Metadata commitments are checked before/after use; this does not authenticate
    physical model assets, actual model execution, source authority, legal review,
    or training eligibility. Completeness means typed-AST syntax only. Unexpected
    callback failures are operational errors, not intentional abstentions. No reference
    target, reference AST, supplied prefix, teacher labels, or rich context enters
    this closed API. Actual output IDs must include the fixed BOS and one final
    EOS. Budget exhaustion and abstention remain separate outcomes, never cropped
    complete outputs. This profile requires lossless tokenization; a future
    declared normalization or independently validated rich-context profile stays separate.
    """
    full_norm = _known_input is not None
    if context_profile != "none" or rich_context is not None:
        raise ProposalAdvisorValidationError(
            "unsupported context profile; versioned rich-context validation required"
        )
    request_id = _identifier(request_id, "request_id")
    source_revision = _text(source_revision, "source_revision")
    refs = _unique_identifiers(source_ref_ids, "source_ref_ids")
    if not refs or len(refs) > _MAX_SOURCE_REFS:
        raise ProposalAdvisorValidationError("bounded nonempty source references required")
    if type(source_text) is not str or not source_text or "\x00" in source_text:
        raise ProposalAdvisorValidationError("complete nonempty source text required")
    try:
        source_raw = source_text.encode("utf-8")
    except UnicodeError as exc:
        raise ProposalAdvisorValidationError("valid original UTF8 source required") from exc
    if len(source_raw) > 1_048_576:
        raise ProposalAdvisorValidationError("source exceeds explicit profile byte limit")
    _digest(expected_source_sha256, "expected_source_sha256")
    if "sha256:" + hashlib.sha256(source_raw).hexdigest() != expected_source_sha256:
        raise ProposalAdvisorValidationError("original source byte binding differs")
    if not full_norm:
        expected_family = _text(expected_family, "expected_family")
        expected_profile = _text(expected_profile, "expected_profile")
    for value, label, cap in (
        (max_input_tokens, "max_input_tokens", 65_536),
        (max_new_tokens, "max_new_tokens", 32_768),
        (max_output_bytes, "max_output_bytes", 1_048_576),
    ):
        _positive_int(value, label, maximum=cap)
    for value, label in (
        (expected_model_binding_sha256, "expected_model_binding_sha256"),
        (expected_tokenizer_binding_sha256, "expected_tokenizer_binding_sha256"),
    ):
        _digest(value, label)

    class CallbackFailure(RuntimeError):
        pass

    def bindings() -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            model_metadata = model.binding_metadata()
        except Exception:
            raise CallbackFailure("model_metadata_callback_failed") from None
        try:
            tokenizer_metadata = tokenizer.binding_metadata()
        except Exception:
            raise CallbackFailure("tokenizer_metadata_callback_failed") from None
        left = dict(_mapping(model_metadata, "model binding"))
        right = dict(_mapping(tokenizer_metadata, "tokenizer binding"))
        tokenizer_fields = {"tokenizer_id", "vocabulary_sha256", "configuration_sha256",
                            "bos_token_id", "eos_token_id"}
        if full_norm:
            tokenizer_fields.add("vocab_size")
        if set(left) != {"model_id", "checkpoint_sha256", "configuration_sha256"} or set(right) != tokenizer_fields:
            raise ProposalAdvisorValidationError("closed model/tokenizer binding required")
        _identifier(left["model_id"], "model_id")
        _identifier(right["tokenizer_id"], "tokenizer_id")
        for value in (left["checkpoint_sha256"], left["configuration_sha256"],
                      right["vocabulary_sha256"], right["configuration_sha256"]):
            _digest(value, "bound artifact")
        if any(type(right[name]) is not int or not 0 <= right[name] < 2**31
               for name in ("bos_token_id", "eos_token_id")) or right["bos_token_id"] == right["eos_token_id"]:
            raise ProposalAdvisorValidationError("distinct declared BOS/EOS required")
        if full_norm and (type(right["vocab_size"]) is not int
                or not 3 <= right["vocab_size"] <= 2**31
                or any(right[name] >= right["vocab_size"] for name in ("bos_token_id", "eos_token_id"))):
            raise ProposalAdvisorValidationError("bounded full-norm tokenizer vocabulary required")
        if _content_digest(left) != expected_model_binding_sha256 or _content_digest(right) != expected_tokenizer_binding_sha256:
            raise ProposalAdvisorValidationError("model/tokenizer binding changed")
        return json.loads(_canonical_json(left)), json.loads(_canonical_json(right))

    prompt_record = {
        "profile": SOURCE_CONDITIONED_TYPED_IR_PROFILE,
        "authority": UNVERIFIED_AUTHORITY,
        "instruction": "Return one complete canonical TypedExpression JSON; propose only.",
        "request_id": request_id,
        "source": {"text": source_text, "utf8_sha256": expected_source_sha256,
                   "revision": source_revision, "source_ref_ids": list(refs)},
        "output_family": expected_family, "output_profile": expected_profile,
    }
    if full_norm:
        prompt_record = {"profile": COMPLETE_NORM_SOURCE_PROFILE, "source_text": source_text,
                         "governing_context": _known_input["governing_context"],
                         "source_binding": _known_input["source_binding"],
                         "selection_context": _known_input["selection_context"]}
    prompt = _canonical_json(prompt_record)
    result: dict[str, Any] = {
        "schema": SOURCE_CONDITIONED_TYPED_IR_RESULT,
        "profile": SOURCE_CONDITIONED_TYPED_IR_PROFILE,
        "request_id": request_id, "input_identity": _content_digest(prompt_record),
        "source_text": source_text, "source_utf8_sha256": expected_source_sha256,
        "source_revision": source_revision, "source_ref_ids": list(refs),
        "model_binding": None, "model_binding_sha256": expected_model_binding_sha256,
        "tokenizer_binding": None, "tokenizer_binding_sha256": expected_tokenizer_binding_sha256,
        "context_profile": "none", "rich_context": None,
        "max_input_tokens": max_input_tokens, "max_new_tokens": max_new_tokens,
        "max_output_bytes": max_output_bytes, "input_token_count": 0,
        "model_call_count": 0, "generated_ids": [], "new_token_count": 0,
        "typed_ir": None, "authority": UNVERIFIED_AUTHORITY,
        "legal_review_verified": False, "proof_authority": False,
        "training_gold_authority": False, "Lean_admitted": False,
        "physical_model_assets_verified": False,
        "source_authority_authenticated": False, "model_execution_authenticated": False,
        "completeness_scope": "typed_AST_syntax_only",
    }
    if full_norm:
        result.update(schema=COMPLETE_NORM_PROPOSAL_RESULT,
                      profile=COMPLETE_NORM_SOURCE_PROFILE,
                      target_codec=COMPLETE_NORM_TARGET_CODEC,
                      complete_norm_candidate=None, candidate_syntax=None,
                      known_source_binding=_known_input["source_binding"],
                      known_governing_context=_known_input["governing_context"],
                      known_selection_context=_known_input["selection_context"],
                      semantic_selection_supported=False,
                      completeness_scope="complete_nine_field_candidate_syntax_only")
    result["inference_context_identity"] = _content_digest({
        "profile": result["profile"], "input_identity": result["input_identity"],
        "model_binding_sha256": expected_model_binding_sha256,
        "tokenizer_binding_sha256": expected_tokenizer_binding_sha256,
        "context_profile": "none", "max_input_tokens": max_input_tokens,
        "max_new_tokens": max_new_tokens, "max_output_bytes": max_output_bytes,
    })

    def finish(status: str, reason: str, *, verify_bindings: bool = True) -> dict[str, Any]:
        if verify_bindings:
            try:
                bindings()
            except CallbackFailure as error:
                status, reason = "error", str(error)
                result["typed_ir"] = None
                if full_norm:
                    result["complete_norm_candidate"] = None
                    result["candidate_syntax"] = None
        result.update(status=status, reason=reason,
                      counts={name: int(status == name) for name in
                              ("complete", "incomplete", "abstained", "unsupported", "invalid", "error")})
        result["result_identity"] = _content_digest(result)
        return json.loads(_canonical_json(result))

    try:
        model_binding, tokenizer_binding = bindings()
    except CallbackFailure as error:
        return finish("error", str(error), verify_bindings=False)
    result.update(model_binding=model_binding, tokenizer_binding=tokenizer_binding)
    if full_norm and callable(getattr(model, "validate_tokenizer_adapter", None)):
        try:
            model.validate_tokenizer_adapter(tokenizer)
        except Exception:
            return finish("error", "checkpoint_tokenizer_adapter_validation_failed")
    try:
        encoded = tokenizer.encode(prompt)
    except Exception:
        return finish("error", "tokenizer_encode_callback_failed")
    if type(encoded) in (list, tuple):
        result["input_token_count"] = len(encoded) + (2 if full_norm else 0)
        if result["input_token_count"] > max_input_tokens:
            return finish("unsupported", "complete_source_input_exceeds_token_budget")
    try:
        input_ids = _proposal_token_ids(encoded, maximum=1_048_576)
    except ProposalAdvisorValidationError:
        return finish("invalid", "tokenizer_did_not_encode_bounded_complete_prompt")
    body_input_ids = input_ids
    if full_norm:
        if any(value >= tokenizer_binding["vocab_size"] or value in
               (tokenizer_binding["bos_token_id"], tokenizer_binding["eos_token_id"])
               for value in body_input_ids):
            return finish("invalid", "tokenizer_did_not_encode_body_only_complete_source")
        input_ids = (tokenizer_binding["bos_token_id"], *body_input_ids,
                     tokenizer_binding["eos_token_id"])
    result["input_token_count"] = len(input_ids)
    if len(input_ids) > max_input_tokens:
        return finish("unsupported", "complete_source_input_exceeds_token_budget")
    try:
        restored_prompt = tokenizer.decode(body_input_ids)
    except Exception:
        return finish("error", "tokenizer_decode_callback_failed")
    if restored_prompt != prompt:
        return finish("unsupported", "tokenizer_does_not_preserve_complete_prompt")
    try:
        bindings()
    except CallbackFailure as error:
        return finish("error", str(error), verify_bindings=False)
    result["model_call_count"] = 1
    try:
        generated = model.generate_token_ids(
            input_ids, decoder_prefix_ids=(tokenizer_binding["bos_token_id"],),
            max_new_tokens=max_new_tokens,
        )
    except SourceConditionedGenerationUnsupported:
        return finish("unsupported", "generation_context_unsupported")
    except Exception:
        return finish("error", "model_generation_callback_failed")
    # Freeze the actual returned history before any further model/tokenizer
    # callbacks. An externally retained list must not acquire a later EOS or
    # different output through a binding-metadata callback.
    frozen_generated, invalid_generated = None, False
    if generated is not None:
        try:
            frozen_generated = _proposal_token_ids(generated, maximum=32_769)
        except ProposalAdvisorValidationError:
            invalid_generated = True
    try:
        bindings()
    except CallbackFailure as error:
        return finish("error", str(error), verify_bindings=False)
    if generated is None:
        return finish("abstained", "explicit_model_abstention")
    if invalid_generated:
        return finish("invalid", "invalid_or_oversized_actual_token_history")
    ids = frozen_generated
    result["generated_ids"] = list(ids)
    if full_norm and any(value >= tokenizer_binding["vocab_size"] for value in ids):
        return finish("invalid", "generated_token_outside_declared_vocabulary")
    if not ids or ids[0] != tokenizer_binding["bos_token_id"]:
        return finish("invalid", "actual_history_missing_fixed_BOS")
    result["new_token_count"] = len(ids) - 1
    if result["new_token_count"] > max_new_tokens:
        return finish("invalid", "model_exceeded_new_token_budget")
    body_ids = ids[1:]
    if not body_ids:
        return finish("incomplete", "no_generated_tokens_or_EOS")
    if tokenizer_binding["bos_token_id"] in body_ids:
        return finish("invalid", "extra_BOS_in_generated_history")
    eos = tokenizer_binding["eos_token_id"]
    if eos not in body_ids:
        return finish("incomplete", "EOS_not_generated")
    if body_ids[-1] != eos or body_ids.count(eos) != 1:
        return finish("invalid", "generation_after_or_duplicate_EOS")
    try:
        output = tokenizer.decode(body_ids[:-1])
    except Exception:
        return finish("error", "tokenizer_decode_callback_failed")
    try:
        if type(output) is not str:
            raise ValueError("output must be text")
        output_bytes = output.encode("utf-8")
    except Exception:
        return finish("invalid", "tokenizer_did_not_return_valid_UTF8_text")
    if len(output_bytes) > max_output_bytes:
        return finish("unsupported", "complete_output_exceeds_byte_budget")
    result["raw_output_text"] = output
    result["raw_output_utf8_sha256"] = "sha256:" + hashlib.sha256(output_bytes).hexdigest()
    try:
        def unique(pairs: Any) -> dict[str, Any]:
            value: dict[str, Any] = {}
            for key, item in pairs:
                if key in value:
                    raise ProposalAdvisorValidationError("duplicate typed IR JSON key")
                value[key] = item
            return value
        offered = json.loads(output, object_pairs_hook=unique,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        _reject_authority_payload(offered)
        if _json_shape(offered)[0] > 65_536:
            raise ProposalAdvisorValidationError("typed IR exceeds node budget")
        if full_norm:
            from ipfs_datasets_py.logic.autoformal.legal_norm_content_adjudication_v1 import (
                CompleteNormCandidateUnsupportedError, validate_complete_norm_candidate_v2,
            )
            try:
                syntax = validate_complete_norm_candidate_v2(
                    offered, known_source_binding=_known_input["source_binding"],
                    known_governing_context=_known_input["governing_context"],
                    known_selection_context=_known_input["selection_context"],
                )
            except CompleteNormCandidateUnsupportedError:
                return finish("unsupported", "unsupported_complete_norm_fragment")
            _require_no_discarded_fields(offered, syntax["candidate"])
            result["candidate_syntax"] = syntax
            result["complete_norm_candidate"] = syntax["candidate"]
            result["typed_ir"] = syntax["candidate"]["typed_expression"]
        else:
            from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression
            expression = TypedExpression.from_dict(_mapping(offered, "complete typed IR"))
            if not expression.is_formula:
                raise ProposalAdvisorValidationError("typed IR must be a complete formula")
            if expression.family.value != expected_family or expression.profile.value != expected_profile:
                raise ProposalAdvisorValidationError("typed IR family/profile differs")
            canonical = expression.to_dict()
            _require_no_discarded_fields(offered, canonical)
            result["typed_ir"] = canonical
    except (ValueError, TypeError, KeyError, RecursionError):
        return finish("invalid", "invalid_complete_norm_candidate" if full_norm
                      else "unsupported_or_invalid_complete_typed_IR")
    return finish("complete", "unverified_complete_norm_candidate" if full_norm
                  else "unverified_complete_typed_IR_candidate")


COMPLETE_NORM_SOURCE_PROFILE: Final = "reviewed-source-selection-context/v2"
COMPLETE_NORM_TARGET_CODEC: Final = "complete-reviewed-norm-json/v2"
COMPLETE_NORM_PROPOSAL_RESULT: Final = "source-complete-norm-proposal-result/v2"


class SourceConditionedGenerationUnsupported(ProposalAdvisorValidationError):
    """The complete source/output window is unsupported before generation."""


def propose_source_conditioned_typed_ir(
    model: SourceConditionedTokenModel, tokenizer: SourceConditionedTokenizer, *,
    request_id: str, source_text: str, source_ref_ids: tuple[str, ...],
    source_revision: str, expected_source_sha256: str,
    expected_model_binding_sha256: str, expected_tokenizer_binding_sha256: str,
    expected_family: str, expected_profile: str,
    max_input_tokens: int, max_new_tokens: int, max_output_bytes: int = 1_048_576,
    context_profile: str = "none", rich_context: object = None,
) -> dict[str, Any]:
    """Preserved typed-only public profile, using the shared bounded transport."""
    return _propose_source_conditioned_payload(
        model, tokenizer, request_id=request_id, source_text=source_text,
        source_ref_ids=source_ref_ids, source_revision=source_revision,
        expected_source_sha256=expected_source_sha256,
        expected_model_binding_sha256=expected_model_binding_sha256,
        expected_tokenizer_binding_sha256=expected_tokenizer_binding_sha256,
        expected_family=expected_family, expected_profile=expected_profile,
        max_input_tokens=max_input_tokens, max_new_tokens=max_new_tokens,
        max_output_bytes=max_output_bytes, context_profile=context_profile,
        rich_context=rich_context,
    )


def propose_source_conditioned_complete_norm(
    model: SourceConditionedTokenModel, tokenizer: SourceConditionedTokenizer, *,
    request_id: str, source_text: str, known_source_binding: dict[str, Any],
    known_governing_context: dict[str, Any], known_selection_context: dict[str, Any],
    expected_source_sha256: str,
    expected_model_binding_sha256: str, expected_tokenizer_binding_sha256: str,
    max_input_tokens: int, max_new_tokens: int, max_output_bytes: int = 1_048_576,
) -> dict[str, Any]:
    """Propose the full nine-field norm from the exact reviewed-source wire.

    Known facts are caller supplied and are not authenticated here. No target,
    review transport, definition label, role list or admission record enters
    generation. The separately supplied interpretation identifier permits only
    an equality check; it supplies no substantive meaning-selection policy.
    The canonical owner validates the complete offered envelope and compares
    source/context/identifier with those facts; it never fills omitted output.
    Semantic selection is unsupported and all candidates remain unreviewed,
    including syntactically complete ones.
    """
    from ipfs_datasets_py.logic.autoformal.legal_norm_content_adjudication_v1 import (
        validate_complete_norm_known_input_v2,
    )
    known = validate_complete_norm_known_input_v2(
        known_source_binding=known_source_binding,
        known_governing_context=known_governing_context,
        known_selection_context=known_selection_context,
    )
    return _propose_source_conditioned_payload(
        model, tokenizer, request_id=request_id, source_text=source_text,
        source_ref_ids=(known["source_binding"]["occurrence_cid"],),
        source_revision=known["source_binding"]["document_revision"],
        expected_source_sha256=expected_source_sha256,
        expected_model_binding_sha256=expected_model_binding_sha256,
        expected_tokenizer_binding_sha256=expected_tokenizer_binding_sha256,
        expected_family="", expected_profile="", max_input_tokens=max_input_tokens,
        max_new_tokens=max_new_tokens, max_output_bytes=max_output_bytes,
        _known_input=known,
    )


__all__ += [
    "SOURCE_CONDITIONED_TYPED_IR_PROFILE", "SOURCE_CONDITIONED_TYPED_IR_RESULT",
    "SourceConditionedTokenModel", "SourceConditionedTokenizer",
    "propose_source_conditioned_typed_ir", "propose_source_conditioned_complete_norm",
    "COMPLETE_NORM_SOURCE_PROFILE", "COMPLETE_NORM_TARGET_CODEC", "COMPLETE_NORM_PROPOSAL_RESULT",
    "SourceConditionedGenerationUnsupported",
]


class ReviewedDecoderTokenizerAdapter:
    """Bind an already-loaded body-only reviewed tokenizer to the P5 protocol.

    The maintained input owner derives the complete live pipeline commitment;
    metadata supplied by a caller must match that derivation. This adapter
    neither constructs a tokenizer nor grants asset or execution authority.
    The independent commitment and caller's asset policy remain required.
    Existing body-only encode/decode behavior is preserved, including disabled
    truncation and disabled implicit special IDs.
    """

    def __init__(self, tokenizer: Any, *, binding: dict[str, Any]) -> None:
        if type(binding) is not dict or set(binding) != {
            "tokenizer_id", "vocabulary_sha256", "configuration_sha256",
            "bos_token_id", "eos_token_id", "vocab_size",
        }:
            raise ProposalAdvisorValidationError("closed complete-norm tokenizer binding required")
        self._tokenizer = tokenizer
        self._binding = json.loads(_canonical_json(binding))
        if not all(callable(getattr(tokenizer, name, None)) for name in
                   ("encode", "decode", "pipeline_serialization", "binding_metadata")):
            raise ProposalAdvisorValidationError("loaded body-only tokenizer required")

    def binding_metadata(self) -> dict[str, Any]:
        for key in ("bos_token_id", "eos_token_id", "vocab_size"):
            actual = getattr(self._tokenizer, key, None)
            if type(self._binding[key]) is not int or type(actual) is not int or actual != self._binding[key]:
                raise ProposalAdvisorValidationError("reviewed tokenizer special IDs/vocabulary changed")
        contract = _complete_norm_tokenizer_pipeline_contract(self._tokenizer)
        actual = self._tokenizer.binding_metadata()
        if (type(actual) is not dict or _canonical_json(actual) != _canonical_json(self._binding)
                or actual["configuration_sha256"] != "sha256:" + contract["pipeline_sha256"]):
            raise ProposalAdvisorValidationError("actual complete tokenizer pipeline binding changed")
        return json.loads(_canonical_json(self._binding))

    def encode(self, text: str) -> Sequence[int]:
        self.binding_metadata()
        # Freeze before the post-tokenization identity callback can mutate a
        # retained list. The actual maintained tokenizer remains body-only.
        body = _proposal_token_ids(self._tokenizer.encode(text), maximum=1_048_576)
        self.binding_metadata()
        return body

    def decode(self, token_ids: tuple[int, ...]) -> str:
        tokens = _proposal_token_ids(token_ids, maximum=1_048_576)
        self.binding_metadata()
        # An owned ordinary list prevents a decoder callback from modifying
        # the P5 transport's immutable token snapshot.
        decoded = self._tokenizer.decode(list(tokens))
        self.binding_metadata()
        return decoded


def _complete_norm_tokenizer_pipeline_contract(tokenizer: Any) -> dict[str, Any]:
    """Reuse the current input owner's full live-pipeline derivation.

    This is the exact v2 implementation shared with the numerical worker, not
    acceptance of a caller-supplied digest or a replacement tokenizer verifier.
    Source/vocabulary/normalization/configuration identity does not confer
    source meaning, model-quality, execution or licensing authority.
    """
    from ipfs_datasets_py.logic.autoformal.training_cycle_inputs import (
        _reviewed_decoder_tokenizer_contract,
    )
    contract = _reviewed_decoder_tokenizer_contract(tokenizer)
    if (type(contract) is not dict or set(contract) != {"schema", "bos_token_id", "eos_token_id",
            "vocab_size", "pipeline_kind", "pipeline_sha256", "pipeline_bytes"}
            or contract["schema"] != "reviewed-decoder-tokenizer-contract/v2"):
        raise ProposalAdvisorValidationError("current complete tokenizer pipeline contract required")
    return json.loads(_canonical_json(contract))


class TorchCompleteNormGenerationAdapter:
    """Normal guarded Torch ``model.generate`` for a caller-loaded v9 backend.

    The already initialized model architecture/configuration is mandatory;
    checkpoint bytes do not reconstruct an architecture or grant execution.
    Pair restoration uses the existing reviewed backend implementation. It may
    mutate caller-owned model/optimizer/RNG state, including on failure; this
    class performs no automatic rollback, optimizer update, download or grant.
    All compatibility observations stay caller-scoped and unverified. Neither
    a well-shaped parent manifest nor a successful generation proves asset
    licensing, pretrained quality, legal meaning, or corpus eligibility.
    """

    _PARENT_FIELDS = {
        "schema", "checkpoint_lineage_id", "base_version_id", "backend_identity", "assets",
        "training_binding", "model_state", "optimizer_state", "progress", "batch_size", "seed",
        "parent_checkpoint_sha256", "producer_pins", "token_budgets", "qualified", "promotion_performed",
    }
    _GENERATION_POLICY = {
        "schema": "complete-norm-explicit-generation-overrides/v2",
        "do_sample": False, "num_beams": 1, "num_return_sequences": 1,
        "forced_bos_token_id": None, "forced_eos_token_id": None,
        "min_length": 0, "min_new_tokens": 0,
        "decoder_start": "declared_training_BOS", "source_prefix_repair_permitted": False,
        "extra_forcing_fields": ["forced_decoder_ids", "force_words_ids", "constraints",
                                 "sequence_bias", "bad_words_ids", "suppress_tokens", "begin_suppress_tokens"],
    }
    _DECLARED_GENERATION_POLICY_WIRE = _canonical_json(_GENERATION_POLICY).encode("utf-8")

    def __init__(self, backend: Any, *, model_id: str,
                 parent_checkpoint_bytes: bytes, model_state_bytes: bytes,
                 optimizer_state_bytes: bytes,
                 expected_parent_checkpoint_sha256: str,
                 expected_backend_identity_sha256: str,
                 expected_generation_configuration_sha256: str,
                 execution_guard: Any, asset_policy_guard: Any) -> None:
        import threading
        if not callable(execution_guard) or not callable(asset_policy_guard):
            raise ProposalAdvisorValidationError("caller-owned execution and asset-policy guards required")
        if not all(callable(getattr(backend, name, None)) for name in (
                "identity", "inspect_checkpoint", "restore_checkpoint", "restored_checkpoint_matches")):
            raise ProposalAdvisorValidationError("existing reviewed decoder checkpoint backend required")
        for raw, limit in ((parent_checkpoint_bytes, 1_048_576),
                           (model_state_bytes, 512 * 1024**2),
                           (optimizer_state_bytes, 512 * 1024**2)):
            if type(raw) is not bytes or not 0 < len(raw) <= limit:
                raise ProposalAdvisorValidationError("bounded immutable checkpoint bytes required")
        _identifier(model_id, "model_id")
        _digest(expected_parent_checkpoint_sha256, "expected_parent_checkpoint_sha256")
        _digest(expected_backend_identity_sha256, "expected_backend_identity_sha256")
        _digest(expected_generation_configuration_sha256, "expected_generation_configuration_sha256")
        if "sha256:" + hashlib.sha256(parent_checkpoint_bytes).hexdigest() != expected_parent_checkpoint_sha256:
            raise ProposalAdvisorValidationError("independently selected parent checkpoint differs")

        def unique(pairs: Any) -> dict[str, Any]:
            value: dict[str, Any] = {}
            for key, item in pairs:
                if key in value:
                    raise ProposalAdvisorValidationError("duplicate parent checkpoint JSON key")
                value[key] = item
            return value
        try:
            parent = json.loads(parent_checkpoint_bytes, object_pairs_hook=unique,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        except (ValueError, TypeError, RecursionError) as error:
            raise ProposalAdvisorValidationError("complete parent checkpoint JSON required") from error
        if (type(parent) is not dict or set(parent) != self._PARENT_FIELDS
                or parent["schema"] != "reviewed-legal-ir-decoder-checkpoint/v1"
                or _canonical_json(parent).encode("utf-8") != parent_checkpoint_bytes
                or parent["qualified"] is not False or parent["promotion_performed"] is not False):
            raise ProposalAdvisorValidationError("closed unpromoted v9 parent checkpoint required")
        identity = parent["backend_identity"]
        if (type(identity) is not dict or set(identity) != {
                "backend_id", "implementation_sha256", "checkpoint_format", "target_codec",
                "source_conditioned", "pretrained"}
                or identity["checkpoint_format"] != "torch-weights-only-complete-reviewed-state-pair/v2"
                or identity["target_codec"] != COMPLETE_NORM_TARGET_CODEC
                or identity["source_conditioned"] is not True or type(identity["pretrained"]) is not bool
                or _content_digest(identity) != expected_backend_identity_sha256):
            raise ProposalAdvisorValidationError("complete reviewed backend identity differs")
        prefix = "torch-complete-reviewed-decoder/v2:"
        backend_id = identity["backend_id"]
        if type(backend_id) is not str or not backend_id.startswith(prefix):
            raise ProposalAdvisorValidationError("explicit existing Torch backend identity required")
        configuration_sha = "sha256:" + backend_id[len(prefix):]
        _digest(configuration_sha, "backend configuration")
        if type(identity["implementation_sha256"]) is not str:
            raise ProposalAdvisorValidationError("backend source commitment required")
        _digest("sha256:" + identity["implementation_sha256"], "backend implementation")
        pins = parent["producer_pins"]
        if type(pins) is not dict or set(pins) != {"worker", "inputs", "consumer", "admission", "splits"}:
            raise ProposalAdvisorValidationError("complete parent producer commitments required")
        for value in pins.values():
            if type(value) is not str:
                raise ProposalAdvisorValidationError("parent producer commitment must be text")
            _digest("sha256:" + value, "parent producer")
        if pins["worker"] != identity["implementation_sha256"]:
            raise ProposalAdvisorValidationError("checkpoint backend and worker source identities differ")
        if type(parent["assets"]) is not list or not 3 <= len(parent["assets"]) <= 256:
            raise ProposalAdvisorValidationError("explicit parent model/tokenizer/license asset commitments required")
        seen_assets = set()
        for reference in parent["assets"]:
            if (type(reference) is not dict or set(reference) != {"path", "bytes", "sha256"}
                    or type(reference["path"]) is not str or not reference["path"].startswith("/")
                    or type(reference["bytes"]) is not int or not 0 < reference["bytes"] <= 512 * 1024**2
                    or reference["path"] in seen_assets or type(reference["sha256"]) is not str):
                raise ProposalAdvisorValidationError("closed distinct parent asset commitments required")
            _digest("sha256:" + reference["sha256"], "parent asset")
            seen_assets.add(reference["path"])
        model_sha = "sha256:" + hashlib.sha256(model_state_bytes).hexdigest()
        optimizer_sha = "sha256:" + hashlib.sha256(optimizer_state_bytes).hexdigest()
        for name, raw, digest in (("model_state", model_state_bytes, model_sha),
                                  ("optimizer_state", optimizer_state_bytes, optimizer_sha)):
            reference = parent[name]
            if (type(reference) is not dict or set(reference) != {"path", "bytes", "sha256"}
                    or type(reference["path"]) is not str or not reference["path"].startswith("/")
                    or type(reference["bytes"]) is not int or reference["bytes"] != len(raw)
                    or reference["sha256"] != digest.removeprefix("sha256:")):
                raise ProposalAdvisorValidationError("exact parent model/optimizer content binding required")
        progress = parent["progress"]
        if (type(progress) is not dict or set(progress) != {"epochs_completed", "row_cursor", "optimizer_steps"}
                or any(type(value) is not int or not 0 <= value <= 10**9 for value in progress.values())):
            raise ProposalAdvisorValidationError("bounded paired checkpoint progress required")
        budgets = parent["token_budgets"]
        if (type(budgets) is not dict or set(budgets) != {
                "max_source_tokens", "max_target_tokens", "tokenizer_contract"}
                or any(type(budgets[key]) is not int or not 3 <= budgets[key] <= 262144
                       for key in ("max_source_tokens", "max_target_tokens"))):
            raise ProposalAdvisorValidationError("declared full source/target token budgets required")
        contract = budgets["tokenizer_contract"]
        if (type(contract) is not dict or set(contract) != {"schema", "bos_token_id", "eos_token_id", "vocab_size",
                "pipeline_kind", "pipeline_sha256", "pipeline_bytes"}
                or contract["schema"] != "reviewed-decoder-tokenizer-contract/v2"
                or contract["pipeline_kind"] not in {"huggingface_fast", "fictional_fixed_byte"}
                or type(contract["pipeline_bytes"]) is not int or not 0 < contract["pipeline_bytes"] <= 32 * 1024**2
                or type(contract["pipeline_sha256"]) is not str
                or type(contract["vocab_size"]) is not int or not 3 <= contract["vocab_size"] <= 2**31
                or any(type(contract[key]) is not int or not 0 <= contract[key] < contract["vocab_size"]
                       for key in ("bos_token_id", "eos_token_id"))
                or contract["bos_token_id"] == contract["eos_token_id"]):
            raise ProposalAdvisorValidationError("complete parent tokenizer contract required")
        _digest("sha256:" + contract["pipeline_sha256"], "parent tokenizer pipeline")
        training = parent["training_binding"]
        if training is None:
            if any(progress.values()):
                raise ProposalAdvisorValidationError("nonzero checkpoint requires its exact training binding")
        elif (type(training) is not dict or training.get("source_profile") != COMPLETE_NORM_SOURCE_PROFILE
                or training.get("target_codec") != COMPLETE_NORM_TARGET_CODEC
                or training.get("tokenizer_contract") != contract):
            raise ProposalAdvisorValidationError("full-norm checkpoint source/target codec differs")
        self._backend = backend
        self._original_backend = backend
        self._bound_objects = None
        self._parent = json.loads(_canonical_json(parent))
        self._model_bytes, self._optimizer_bytes = model_state_bytes, optimizer_state_bytes
        self._expected_identity = json.loads(_canonical_json(identity))
        self._expected_generation_configuration_sha256 = expected_generation_configuration_sha256
        self._execution_guard, self._asset_policy_guard = execution_guard, asset_policy_guard
        self._lock = threading.Lock()
        # Capture the complete declaration once, before any policy callback.
        # Canonical bytes own every nested value without retaining the class
        # dict/list. Bindings, guard records and actual overrides below all
        # derive from this same immutable snapshot, never a later class read.
        self._generation_policy_wire = _canonical_json(self._GENERATION_POLICY).encode("utf-8")
        if self._generation_policy_wire != self._DECLARED_GENERATION_POLICY_WIRE:
            raise ProposalAdvisorValidationError("declared generation policy changed before construction")
        self._binding = {"model_id": model_id,
            "checkpoint_sha256": _content_digest({"schema": "complete-norm-inference-pair/v1",
                "parent_checkpoint_sha256": expected_parent_checkpoint_sha256,
                "model_state_sha256": model_sha, "optimizer_state_sha256": optimizer_sha}),
            "configuration_sha256": _content_digest({"schema": "complete-norm-inference-configuration/v1",
                "backend_configuration_sha256": configuration_sha,
                "generation_configuration_sha256": expected_generation_configuration_sha256,
                "generation_policy": self._generation_policy()})}
        self._policy_record = {"schema": "caller-owned-complete-norm-inference-policy/v1",
            "parent_checkpoint_sha256": expected_parent_checkpoint_sha256,
            "backend_identity": self._expected_identity, "assets": self._parent["assets"],
            "model_state": self._parent["model_state"], "optimizer_state": self._parent["optimizer_state"],
            "producer_pins": self._parent["producer_pins"],
            "training_binding": self._parent["training_binding"], "token_budgets": budgets,
            "generation_configuration_sha256": expected_generation_configuration_sha256,
            "generation_policy": self._generation_policy(), "authority": UNVERIFIED_AUTHORITY}
        self._observation = {"checkpoint_restore_attempts": 0, "checkpoint_restores_completed": 0,
                             "model_generate_calls": 0, "execution_guard_calls": 0,
                             "asset_policy_guard_calls": 0, "caller_backend_may_have_changed": False}

    def _generation_policy(self) -> dict[str, Any]:
        # Each public/guard observation gets a detached ordinary JSON value.
        # No returned record can mutate the policy used by actual generation.
        return json.loads(self._generation_policy_wire)

    def _objects(self) -> tuple[Any, Any, Any]:
        if self._backend is not self._original_backend:
            raise ProposalAdvisorValidationError("caller-owned backend object was replaced")
        return tuple(getattr(self._backend, name, None) for name in ("model", "tokenizer", "optimizer"))

    def _check_objects(self, *, establish: bool = False) -> None:
        actual = self._objects()
        if any(value is None for value in actual):
            raise ProposalAdvisorValidationError("loaded backend model/tokenizer/optimizer objects required")
        if self._bound_objects is None and establish:
            self._bound_objects = actual
        if self._bound_objects is not None and any(left is not right for left, right in zip(actual, self._bound_objects)):
            raise ProposalAdvisorValidationError("loaded backend model/tokenizer/optimizer object identity changed")

    def _generation_configuration(self) -> dict[str, Any]:
        config = getattr(self._backend.model, "generation_config", None)
        if not callable(getattr(config, "to_dict", None)):
            raise SourceConditionedGenerationUnsupported("explicit initialized generation configuration required")
        offered = config.to_dict()
        if type(offered) is not dict:
            raise ProposalAdvisorValidationError("ordinary generation configuration required")
        try:
            raw = _canonical_json(offered)
            shape = _json_shape(offered)
        except (TypeError, ValueError, RecursionError) as error:
            raise ProposalAdvisorValidationError("bounded finite generation configuration required") from error
        if len(raw.encode("utf-8")) > 1_048_576 or shape[0] > 65536 or shape[1] > 64:
            raise ProposalAdvisorValidationError("generation configuration exceeds profile bounds")
        if _content_digest(offered) != self._expected_generation_configuration_sha256:
            raise ProposalAdvisorValidationError("independently selected generation configuration changed")
        self._check_objects()
        return json.loads(raw)

    def _guard(self, phase: str, *, source_token_count: int | None = None,
               max_new_tokens: int | None = None) -> None:
        if self._backend is not self._original_backend:
            raise ProposalAdvisorValidationError("caller-owned backend object was replaced")
        self._execution_guard()
        self._observation["execution_guard_calls"] += 1
        record = json.loads(_canonical_json(self._policy_record))
        record.update(operation=phase, source_token_count=source_token_count,
                      max_new_tokens=max_new_tokens)
        self._asset_policy_guard(record)
        self._observation["asset_policy_guard_calls"] += 1
        self._check_objects(establish=True)
        identity = self._backend.identity()
        if type(identity) is not dict or _canonical_json(identity) != _canonical_json(self._expected_identity):
            raise ProposalAdvisorValidationError("current loaded backend configuration differs")
        self._check_objects()
        contract = _complete_norm_tokenizer_pipeline_contract(self._backend.tokenizer)
        if _canonical_json(contract) != _canonical_json(self._parent["token_budgets"]["tokenizer_contract"]):
            raise ProposalAdvisorValidationError("actual complete tokenizer pipeline differs from checkpoint")
        self._check_objects()
        self._generation_configuration()

    def validate_tokenizer_adapter(self, tokenizer: Any) -> None:
        self._guard("validate_inference_tokenizer")
        if (not isinstance(tokenizer, ReviewedDecoderTokenizerAdapter)
                or tokenizer._tokenizer is not self._backend.tokenizer):
            raise ProposalAdvisorValidationError("generation must use the loaded checkpoint backend tokenizer")
        tokenizer.binding_metadata()
        self._check_objects()

    def binding_metadata(self) -> dict[str, Any]:
        self._guard("inspect_generation_identity")
        return json.loads(_canonical_json(self._binding))

    def generation_observation(self) -> dict[str, Any]:
        return {**self._observation,
                "generation_configuration_sha256": self._expected_generation_configuration_sha256,
                "generation_policy": self._generation_policy(),
                "scope": "caller-owned-protocol-observation_not_independent_execution_or_asset_authentication",
                "physical_model_assets_verified": False, "model_execution_authenticated": False,
                "legal_review_verified": False, "proof_authority": False, "training_gold_authority": False}

    def generate_token_ids(self, input_ids: tuple[int, ...], *,
                           decoder_prefix_ids: tuple[int, ...], max_new_tokens: int) -> Sequence[int]:
        if not self._lock.acquire(blocking=False):
            raise ProposalAdvisorValidationError("one generation call per adapter; caller serializes shared backend")
        try:
            return self._generate(input_ids, decoder_prefix_ids=decoder_prefix_ids,
                                  max_new_tokens=max_new_tokens)
        finally:
            self._lock.release()

    def _generate(self, input_ids: tuple[int, ...], *, decoder_prefix_ids: tuple[int, ...],
                  max_new_tokens: int) -> Sequence[int]:
        # Take owned immutable inputs before caller guards can observe/mutate
        # an externally retained ordinary token list.
        tokens = _proposal_token_ids(input_ids, maximum=262144)
        prefix = _proposal_token_ids(decoder_prefix_ids, maximum=1)
        _positive_int(max_new_tokens, "max_new_tokens", maximum=32768)
        budgets = self._parent["token_budgets"]
        # H's complete target capacity counts BOS/body/EOS. P5 supplies the
        # fixed BOS and generates body/EOS, so its full capacity is exactly
        # 1 + max_new_tokens. Refuse an unmatched capacity before callbacks,
        # Torch import, restoration or generation; never shorten a target.
        # Population eligibility and denominators remain caller-owned work.
        if 1 + max_new_tokens != budgets["max_target_tokens"]:
            raise SourceConditionedGenerationUnsupported(
                "selected generation capacity must match the declared complete target budget")
        self._guard("validate_generation", source_token_count=len(tokens), max_new_tokens=max_new_tokens)
        contract = self._parent["token_budgets"]["tokenizer_contract"]
        bos, eos, vocab = (contract[key] for key in ("bos_token_id", "eos_token_id", "vocab_size"))
        if (len(tokens) < 3 or tokens[0] != bos or tokens[-1] != eos
                or any(value in (bos, eos) or value >= vocab for value in tokens[1:-1])
                or prefix != (bos,)):
            raise ProposalAdvisorValidationError("complete source BOS/body/EOS and fixed decoder BOS required")
        backend = self._backend
        architecture, limit = getattr(backend, "architecture", None), getattr(backend, "max_sequence_tokens", None)
        if (architecture not in {"encoder_decoder", "causal_lm"} or type(limit) is not int
                or not 3 <= limit <= 262144):
            raise ProposalAdvisorValidationError("explicit initialized backend architecture/context required")
        used = len(tokens) + 1 + max_new_tokens if architecture == "causal_lm" else max(len(tokens), 1 + max_new_tokens)
        if len(tokens) > budgets["max_source_tokens"] or 1 + max_new_tokens > budgets["max_target_tokens"] or used > limit:
            raise SourceConditionedGenerationUnsupported("complete generation exceeds selected checkpoint/model budget")
        model = getattr(backend, "model", None)
        tokenizer = getattr(backend, "tokenizer", None)
        if (model is None or not callable(getattr(model, "generate", None))
                or not callable(getattr(model, "eval", None)) or not callable(getattr(model, "train", None))
                or type(getattr(model, "training", None)) is not bool
                or any(type(getattr(tokenizer, name, None)) is not int
                       or getattr(tokenizer, name, None) != contract[name]
                       for name in ("bos_token_id", "eos_token_id", "vocab_size"))):
            raise ProposalAdvisorValidationError("actual loaded generation model/tokenizer interface differs")
        self._check_objects()
        # Normal Torch is imported only after the existing caller guards. There
        # is no provider/asset loader and no fallback synthetic token model.
        import torch
        parameters = list(model.parameters())
        if not parameters or len({value.device for value in parameters}) != 1:
            raise ProposalAdvisorValidationError("one caller-owned model device required")
        device = parameters[0].device
        if device.type not in {"cpu", "cuda"}:
            raise ProposalAdvisorValidationError("unsupported model device")
        for embedding in (model.get_input_embeddings(), model.get_output_embeddings()):
            if embedding is None or embedding.weight.shape[0] < vocab:
                raise ProposalAdvisorValidationError("model vocabulary does not cover source/target IDs")
        self._guard("restore_checkpoint_pair", source_token_count=len(tokens), max_new_tokens=max_new_tokens)
        inspected = backend.inspect_checkpoint(self._model_bytes, self._optimizer_bytes)
        if (type(inspected) is not dict or set(inspected) != {"optimizer_steps"}
                or type(inspected["optimizer_steps"]) is not int
                or inspected["optimizer_steps"] != self._parent["progress"]["optimizer_steps"]):
            raise ProposalAdvisorValidationError("checkpoint optimizer progress differs before restoration")
        self._observation["checkpoint_restore_attempts"] += 1
        self._observation["caller_backend_may_have_changed"] = True
        backend.restore_checkpoint(self._model_bytes, self._optimizer_bytes)
        self._observation["checkpoint_restores_completed"] += 1
        if backend.restored_checkpoint_matches(self._model_bytes, self._optimizer_bytes) is not True:
            raise ProposalAdvisorValidationError("actual checkpoint pair failed exact restore")
        self._check_objects()
        self._guard("generate", source_token_count=len(tokens), max_new_tokens=max_new_tokens)
        # Re-read only after restoration and the point-of-use guard. The guard
        # may refuse a changed object; it cannot make a stale pre-restore model
        # masquerade as the freshly inspected backend's checkpoint.
        model = backend.model
        device = next(model.parameters()).device
        config = self._generation_configuration()
        policy = self._generation_policy()
        source = tokens if architecture == "encoder_decoder" else (*tokens, bos)
        inputs = torch.tensor([source], dtype=torch.long, device=device)
        kwargs = {"input_ids": inputs, "attention_mask": torch.ones_like(inputs),
                  "max_new_tokens": max_new_tokens, "eos_token_id": eos, "pad_token_id": eos,
                  "do_sample": policy["do_sample"], "num_beams": policy["num_beams"],
                  "num_return_sequences": policy["num_return_sequences"],
                  "forced_eos_token_id": policy["forced_eos_token_id"],
                  "forced_bos_token_id": policy["forced_bos_token_id"],
                  "bos_token_id": bos, "decoder_start_token_id": bos,
                  "min_length": policy["min_length"], "min_new_tokens": policy["min_new_tokens"],
                  "return_dict_in_generate": False}
        # Disable explicitly represented forcing/suppression lists too. An
        # unsupported model API fails; no target-assisted token repair occurs.
        for name in tuple(policy["extra_forcing_fields"]):
            if name in config:
                kwargs[name] = None
        if architecture == "encoder_decoder":
            kwargs["decoder_input_ids"] = torch.tensor([[bos]], dtype=torch.long, device=device)
        if not callable(getattr(model, "modules", None)):
            raise ProposalAdvisorValidationError("actual Torch module traversal required")
        modules = tuple(model.modules())
        if not modules or modules[0] is not model or len({id(value) for value in modules}) != len(modules):
            raise ProposalAdvisorValidationError("stable distinct model module inventory required")
        modes = tuple((module, getattr(module, "training", None)) for module in modules)
        if any(type(flag) is not bool for _, flag in modes):
            raise ProposalAdvisorValidationError("plain module training modes required")
        try:
            model.eval()
            self._check_objects()
            self._generation_configuration()
            if backend.restored_checkpoint_matches(self._model_bytes, self._optimizer_bytes) is not True:
                raise ProposalAdvisorValidationError("model/optimizer/RNG changed before generation")
            self._check_objects()
            self._observation["model_generate_calls"] += 1
            with torch.no_grad():
                generated = model.generate(**kwargs)
                expected_maximum = (1 + max_new_tokens if architecture == "encoder_decoder"
                                    else len(source) + max_new_tokens)
                if (not torch.is_tensor(generated) or generated.ndim != 2 or generated.shape[0] != 1
                        or generated.dtype not in {torch.int32, torch.int64}
                        or generated.numel() > expected_maximum):
                    raise ProposalAdvisorValidationError("bounded actual integer generation history required")
                # Freeze the actual return BEFORE mode cleanup, policy guards
                # or backend callbacks can mutate a model-retained Tensor.
                history = tuple(generated.detach().cpu()[0].tolist())
                if any(type(value) is not int or not 0 <= value < vocab for value in history):
                    raise ProposalAdvisorValidationError("generated model IDs outside declared vocabulary")
                self._check_objects()
                if backend.restored_checkpoint_matches(self._model_bytes, self._optimizer_bytes) is not True:
                    raise ProposalAdvisorValidationError("model/optimizer/RNG changed during generation")
                self._check_objects()
        finally:
            # Preserve mixed pre-existing submodule modes. Calling only
            # model.train(was_training) would overwrite every descendant mode.
            for module, flag in modes:
                module.training = flag
            current_modules = tuple(model.modules())
            if (len(current_modules) != len(modules) or
                    any(left is not right for left, right in zip(current_modules, modules)) or
                    any(type(module.training) is not bool or module.training is not flag
                        for module, flag in modes)):
                raise ProposalAdvisorValidationError("model module modes/topology did not restore")
        self._guard("after_generate", source_token_count=len(tokens), max_new_tokens=max_new_tokens)
        if backend.restored_checkpoint_matches(self._model_bytes, self._optimizer_bytes) is not True:
            raise ProposalAdvisorValidationError("model/optimizer/RNG changed during generation")
        self._check_objects()
        if architecture == "causal_lm":
            if history[:len(source)] != tuple(source):
                raise ProposalAdvisorValidationError("actual causal history differs from the exact source prefix")
            history = (bos, *history[len(source):])
        return history


__all__ += ["ReviewedDecoderTokenizerAdapter", "TorchCompleteNormGenerationAdapter"]
