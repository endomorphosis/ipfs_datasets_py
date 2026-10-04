"""Deterministic source-aware counterexample explanations (CounterexampleExplanation@1).

Produces stable, redacted explanations from public counterexample material:

* decoded values and expected/actual deltas;
* first violated condition or observation divergence with source/AST spans;
* causal chain leading to that divergence;
* assumptions and finite bounds;
* affected proof holes (by property / source-span overlap);
* separately labeled repair *hypotheses* that never claim proof.

Acceptance obligations (FVT-G042 / FVT-020):

* First divergence and source spans are content-stable for the same input.
* Cited explanation facts are only those verified by exact replay (or an
  explicit ``replay_verified=True`` attestation bound to a successful receipt).
* Repair hypotheses are labeled as hypotheses; they never advertise proof,
  completion, or elevated authority.
* Redaction holds after decoding — raw prover channels never appear.
* Unsupported source mappings remain explicit rather than invented.
* The stable public API returns no ``raw`` payload.

This module owns the explanation contract and deterministic derivation.
Provider syntax is never reinterpreted; private material is stripped via the
public counterexample boundary before any fact is recorded.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final, Protocol, runtime_checkable

COUNTEREXAMPLE_EXPLANATION_INTERFACE: Final = "CounterexampleExplanation@1"
EXPLANATION_SCHEMA: Final = (
    "ipfs_datasets_py/logic/counterexample-explanation@1"
)
EXPLANATION_FACT_SCHEMA: Final = (
    "ipfs_datasets_py/logic/counterexample-explanation-fact@1"
)
REPAIR_HYPOTHESIS_SCHEMA: Final = (
    "ipfs_datasets_py/logic/counterexample-repair-hypothesis@1"
)
ALGORITHM_VERSION: Final = "counterexample-explanation/1.0.0"
ALGORITHM_NAME: Final = "deterministic_source_aware_explanation"

# Authority ceilings that a repair hypothesis may advertise.  Never "proof".
_HYPOTHESIS_AUTHORITIES: Final[frozenset[str]] = frozenset(
    {
        "none",
        "advisory",
        "hypothesis",
    }
)

_PROOF_CLAIM_MARKERS: Final[tuple[str, ...]] = (
    "proved",
    "proven",
    "proof_claimed",
    "claims_proof",
    "is_proof",
    "verified_proof",
    "discharge_complete",
    "completion_claimed",
    "closed_by_proof",
)

_FORBIDDEN_PUBLIC_MARKERS: Final[tuple[str, ...]] = (
    "hidden_witness",
    "private_witness",
    "private_inputs",
    "credential",
    "access_token",
    "refresh_token",
    "api_key",
    "raw_output",
    "prover_output",
    "stdout",
    "stderr",
    "source_excerpt",
    "source_code",
    "source_text",
    "file_content",
    "repository_source",
)

_PRIVATE_CHANNEL_KEY_RE = re.compile(
    r"(?:^|[_\-.])(?:password|passwd|secret|api[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|session[_-]?token|credential|authorization|cookie|"
    r"private[_-]?key|private[_-]?premise|private[_-]?input|"
    r"hidden[_-]?witness|private[_-]?witness|witness)(?:$|[_\-.])",
    re.IGNORECASE,
)
_FORBIDDEN_CHANNEL_KEY_RE = re.compile(
    r"^(?:raw|raw_data|raw_output|provider_output|prover_output|stdout|stderr|"
    r"transcript|full_trace|full_model|source|source_code|source_text|"
    r"source_excerpt|file_content|repository_source|proof_text|command_output|"
    r"(?:[a-z0-9]+_)+source(?:_code|_text|_excerpt|_content)?)$",
    re.IGNORECASE,
)

_SAFE_PUBLIC_KEYS: Final[frozenset[str]] = frozenset(
    {
        "actual",
        "affected_proof_holes",
        "algorithm",
        "algorithm_version",
        "assumption_ids",
        "assumptions",
        "authority",
        "bounds",
        "causal_chain",
        "cited_facts",
        "condition",
        "content_id",
        "counterexample_id",
        "decoded_values",
        "deltas",
        "detail",
        "divergence",
        "divergence_id",
        "expected",
        "explanation_id",
        "fact_id",
        "facts",
        "field",
        "finite_bounds",
        "first_divergence",
        "hole_id",
        "hypothesis_id",
        "index",
        "interface",
        "kind",
        "label",
        "mapping_status",
        "name",
        "observation",
        "path",
        "payload",
        "proof_hole_ids",
        "property_id",
        "provenance",
        "reason",
        "redacted",
        "related_fact_ids",
        "repair_class",
        "repair_hypotheses",
        "replay_receipt_id",
        "replay_verified",
        "role",
        "schema",
        "source_map",
        "source_ref_ids",
        "source_span",
        "source_spans",
        "span_ids",
        "ast_scope_ids",
        "status",
        "step",
        "summary",
        "symbol",
        "target",
        "tree_ids",
        "unsupported_mappings",
        "value",
        "violated_property",
        "witness_content_id",
        "witness_kind",
    }
)

_SAFE_PUBLIC_CHANNEL_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "secret_material",
        "provider_transcript",
        "provider_artifact",
        "source_blob",
        "private_channel",
    }
)


class ExplanationError(ValueError):
    """Raised when an explanation request is malformed or unsafe."""


class MappingStatus(StrEnum):
    """Whether a source/AST mapping is supported for this witness."""

    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    ABSENT = "absent"


class DivergenceKind(StrEnum):
    """Closed kinds of first divergence extracted from a witness."""

    VIOLATED_CONDITION = "violated_condition"
    OBSERVATION_DIVERGENCE = "observation_divergence"
    TRACE_STEP = "trace_step"
    PROTOCOL_STEP = "protocol_step"
    KERNEL_FAILURE = "kernel_failure"
    UNSUPPORTED = "unsupported"


class FactRole(StrEnum):
    """Roles for replay-verified explanation facts."""

    DECODED_VALUE = "decoded_value"
    EXPECTED_ACTUAL = "expected_actual"
    FIRST_DIVERGENCE = "first_divergence"
    CAUSAL_LINK = "causal_link"
    ASSUMPTION = "assumption"
    BOUND = "bound"
    SOURCE_SPAN = "source_span"
    PROOF_HOLE = "proof_hole"
    REPLAY_RECEIPT = "replay_receipt"
    PROPERTY = "property"


class HypothesisStatus(StrEnum):
    """Repair hypotheses are never elevated past hypothesis/advisory."""

    HYPOTHESIS = "hypothesis"
    ADVISORY = "advisory"


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _text(value: object, label: str, *, optional: bool = False, maximum: int = 512) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str):
        raise ExplanationError(f"{label} must be a string")
    text = value.strip()
    if "\x00" in text:
        raise ExplanationError(f"{label} must not contain NUL")
    if not optional and not text:
        raise ExplanationError(f"{label} is required")
    if len(text) > maximum:
        text = text[: max(0, maximum - 1)] + "…"
    return text


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        item = _text(value, label, maximum=256)
        return (item,) if item else ()
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        raise ExplanationError(f"{label} must be a sequence of strings")
    items: list[str] = []
    for raw in value:
        item = _text(raw, label, maximum=256)
        if item:
            items.append(item)
    return tuple(sorted(set(items)))


def _mapping(value: object, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ExplanationError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ExplanationError(f"{label} keys must be strings")
    return dict(value)


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return str(value)
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_json_ready(item) for item in value), key=_canonical)
    if isinstance(value, StrEnum):
        return value.value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    return str(value)


def _canonical(value: Any) -> str:
    return json.dumps(
        _json_ready(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _content_id(prefix: str, payload: Mapping[str, Any]) -> str:
    body = dict(payload)
    body.pop("explanation_id", None)
    body.pop("content_id", None)
    body.pop("hypothesis_id", None)
    body.pop("fact_id", None)
    body.pop("divergence_id", None)
    return f"{prefix}:{_digest(body)[:32]}"


def _sha256_hex(payload: bytes | str) -> str:
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _is_private_or_forbidden_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    if normalized in _SAFE_PUBLIC_KEYS:
        return False
    if normalized == "raw":
        return True
    return bool(
        _PRIVATE_CHANNEL_KEY_RE.search(normalized)
        or _FORBIDDEN_CHANNEL_KEY_RE.match(normalized)
    )


def _assert_public_safe(value: Any, *, label: str = "explanation") -> None:
    """Reject private field names, raw channels, and secret-bearing values."""

    def walk(node: Any, *, path: str) -> None:
        if isinstance(node, Mapping):
            for raw_key, child in node.items():
                key = str(raw_key)
                key_l = key.lower().replace("-", "_")
                child_path = f"{path}.{key}" if path else key
                if key_l == "raw":
                    raise ExplanationError(
                        f"{label} must not contain raw payload at {child_path}"
                    )
                if key_l in _SAFE_PUBLIC_KEYS:
                    walk(child, path=child_path)
                    continue
                if _is_private_or_forbidden_key(key) or any(
                    marker == key_l or marker in key_l
                    for marker in _FORBIDDEN_PUBLIC_MARKERS
                ):
                    raise ExplanationError(
                        f"{label} contains forbidden public channel key {key!r}"
                    )
                walk(child, path=child_path)
            return
        if isinstance(node, Sequence) and not isinstance(
            node, (str, bytes, bytearray, memoryview)
        ):
            for index, child in enumerate(node):
                walk(child, path=f"{path}[{index}]")
            return
        if isinstance(node, str):
            if node in _SAFE_PUBLIC_CHANNEL_CLASSES:
                return
            text = node.lower()
            for marker in _FORBIDDEN_PUBLIC_MARKERS:
                if marker in text:
                    raise ExplanationError(
                        f"{label} contains forbidden public channel "
                        f"{marker!r} at {path or '<root>'}"
                    )

    walk(value, path="")


def _strip_private(value: Any) -> Any:
    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            key_l = key.lower().replace("-", "_")
            if key_l == "raw" or _is_private_or_forbidden_key(key):
                continue
            if any(marker in key_l for marker in _FORBIDDEN_PUBLIC_MARKERS):
                continue
            cleaned[key] = _strip_private(child)
        return cleaned
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        return [_strip_private(item) for item in value]
    if isinstance(value, str):
        lowered = value.lower()
        for marker in _FORBIDDEN_PUBLIC_MARKERS:
            if marker in lowered:
                return "<redacted>"
        return value
    return value


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    to_public = getattr(value, "to_public_dict", None)
    if callable(to_public):
        converted = to_public()
        if isinstance(converted, Mapping):
            return dict(converted)
    raise ExplanationError(
        "input must be a mapping or expose to_dict()/to_public_dict()"
    )


def _claims_proof(value: Mapping[str, Any] | str) -> bool:
    if isinstance(value, str):
        lowered = value.lower().replace("-", "_")
        return any(marker in lowered for marker in _PROOF_CLAIM_MARKERS)
    for key, child in value.items():
        key_l = str(key).lower().replace("-", "_")
        if key_l in _PROOF_CLAIM_MARKERS and child is True:
            return True
        if key_l in {"authority", "status", "claim", "role"} and isinstance(child, str):
            if child.lower().replace("-", "_") in {
                "proof",
                "proved",
                "proven",
                "verified_proof",
                "kernel_checked",
            }:
                return True
        if isinstance(child, Mapping) and _claims_proof(child):
            return True
        if isinstance(child, str) and _claims_proof(child):
            return True
    return False


# ---------------------------------------------------------------------------
# Public value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceSpanRef:
    """Stable reference to a source/AST span (never embeds source text)."""

    span_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    ast_scope_ids: tuple[str, ...] = ()
    tree_ids: tuple[str, ...] = ()
    mapping_status: MappingStatus | str = MappingStatus.ABSENT

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "span_ids", _string_tuple(self.span_ids, "span_ids")
        )
        object.__setattr__(
            self, "source_ref_ids", _string_tuple(self.source_ref_ids, "source_ref_ids")
        )
        object.__setattr__(
            self, "ast_scope_ids", _string_tuple(self.ast_scope_ids, "ast_scope_ids")
        )
        object.__setattr__(
            self, "tree_ids", _string_tuple(self.tree_ids, "tree_ids")
        )
        status = self.mapping_status
        if isinstance(status, str):
            try:
                status = MappingStatus(status)
            except ValueError as exc:
                raise ExplanationError(
                    f"unsupported mapping_status {self.mapping_status!r}"
                ) from exc
        object.__setattr__(self, "mapping_status", status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ast_scope_ids": list(self.ast_scope_ids),
            "mapping_status": (
                self.mapping_status.value
                if isinstance(self.mapping_status, MappingStatus)
                else str(self.mapping_status)
            ),
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "tree_ids": list(self.tree_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "SourceSpanRef":
        if value is None:
            return cls()
        data = _mapping(value, "source_span")
        return cls(
            span_ids=tuple(data.get("span_ids") or ()),
            source_ref_ids=tuple(data.get("source_ref_ids") or ()),
            ast_scope_ids=tuple(data.get("ast_scope_ids") or ()),
            tree_ids=tuple(data.get("tree_ids") or ()),
            mapping_status=str(data.get("mapping_status") or MappingStatus.ABSENT.value),
        )

    @classmethod
    def from_source_map(cls, source_map: Mapping[str, Any] | None) -> "SourceSpanRef":
        if not source_map:
            return cls(mapping_status=MappingStatus.ABSENT)
        data = _mapping(source_map, "source_map")
        span_ids = tuple(
            str(item)
            for item in (data.get("span_ids") or data.get("spans") or ())
            if str(item)
        )
        source_ref_ids = tuple(
            str(item)
            for item in (data.get("source_ref_ids") or data.get("source_refs") or ())
            if str(item)
        )
        ast_scope_ids = tuple(
            str(item)
            for item in (data.get("ast_scope_ids") or data.get("ast_scopes") or ())
            if str(item)
        )
        tree_ids = tuple(
            str(item)
            for item in (data.get("tree_ids") or data.get("trees") or ())
            if str(item)
        )
        # Explicit unsupported markers from callers / frontends.
        explicit = str(data.get("mapping_status") or data.get("status") or "").lower()
        # Explicit unsupported always wins — do not invent spans or upgrade.
        if (
            explicit == MappingStatus.UNSUPPORTED.value
            or data.get("unsupported") is True
            or data.get("supported") is False
        ):
            status = MappingStatus.UNSUPPORTED
        elif explicit in {s.value for s in MappingStatus}:
            status = MappingStatus(explicit)
        elif not any((span_ids, source_ref_ids, ast_scope_ids, tree_ids)):
            status = MappingStatus.ABSENT
        elif span_ids or source_ref_ids or ast_scope_ids:
            # Tree alone is partial; span or AST or source ref is supported.
            if span_ids or (source_ref_ids and ast_scope_ids):
                status = MappingStatus.SUPPORTED
            else:
                status = MappingStatus.PARTIAL
        else:
            status = MappingStatus.PARTIAL
        return cls(
            span_ids=span_ids,
            source_ref_ids=source_ref_ids,
            ast_scope_ids=ast_scope_ids,
            tree_ids=tree_ids,
            mapping_status=status,
        )


@dataclass(frozen=True, slots=True)
class DecodedValue:
    """One public decoded assignment / observation value."""

    name: str
    value: Any
    path: str = ""
    role: str = "assignment"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "decoded_value.name", maximum=256))
        object.__setattr__(
            self, "path", _text(self.path, "decoded_value.path", optional=True, maximum=512)
        )
        object.__setattr__(
            self, "role", _text(self.role, "decoded_value.role", optional=True, maximum=64) or "assignment"
        )
        object.__setattr__(self, "value", _json_ready(_strip_private(self.value)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "role": self.role,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class ExpectedActualDelta:
    """Expected-versus-actual comparison for one path/field."""

    path: str
    expected: Any
    actual: Any
    equal: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "path", _text(self.path, "delta.path", maximum=512)
        )
        expected = _json_ready(_strip_private(self.expected))
        actual = _json_ready(_strip_private(self.actual))
        object.__setattr__(self, "expected", expected)
        object.__setattr__(self, "actual", actual)
        object.__setattr__(self, "equal", expected == actual)

    def to_dict(self) -> dict[str, Any]:
        return {
            "actual": self.actual,
            "equal": self.equal,
            "expected": self.expected,
            "path": self.path,
        }


@dataclass(frozen=True, slots=True)
class FirstDivergence:
    """Stable first violated condition or observation divergence."""

    kind: DivergenceKind | str
    path: str
    detail: str
    expected: Any = None
    actual: Any = None
    index: int | None = None
    source_span: SourceSpanRef = field(default_factory=SourceSpanRef)
    divergence_id: str = ""

    def __post_init__(self) -> None:
        kind = self.kind
        if isinstance(kind, str):
            try:
                kind = DivergenceKind(kind)
            except ValueError as exc:
                raise ExplanationError(f"unsupported divergence kind {self.kind!r}") from exc
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self, "path", _text(self.path, "first_divergence.path", maximum=512)
        )
        object.__setattr__(
            self, "detail", _text(self.detail, "first_divergence.detail", maximum=1024)
        )
        object.__setattr__(self, "expected", _json_ready(_strip_private(self.expected)))
        object.__setattr__(self, "actual", _json_ready(_strip_private(self.actual)))
        if self.index is not None and not isinstance(self.index, int):
            raise ExplanationError("first_divergence.index must be int or None")
        if not isinstance(self.source_span, SourceSpanRef):
            if isinstance(self.source_span, Mapping):
                object.__setattr__(
                    self, "source_span", SourceSpanRef.from_dict(self.source_span)
                )
            else:
                raise ExplanationError("source_span must be a SourceSpanRef")
        payload = self._identity_core()
        computed = _content_id("divergence", payload)
        if self.divergence_id:
            claimed = _text(self.divergence_id, "divergence_id", maximum=128)
            if claimed != computed:
                raise ExplanationError("divergence identity does not match")
            object.__setattr__(self, "divergence_id", claimed)
        else:
            object.__setattr__(self, "divergence_id", computed)

    def _identity_core(self) -> dict[str, Any]:
        return {
            "actual": self.actual,
            "detail": self.detail,
            "expected": self.expected,
            "index": self.index,
            "kind": self.kind.value if isinstance(self.kind, DivergenceKind) else str(self.kind),
            "path": self.path,
            "source_span": self.source_span.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "actual": self.actual,
            "detail": self.detail,
            "divergence_id": self.divergence_id,
            "expected": self.expected,
            "index": self.index,
            "kind": self.kind.value if isinstance(self.kind, DivergenceKind) else str(self.kind),
            "path": self.path,
            "source_span": self.source_span.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class CausalLink:
    """One link in the causal chain ending at the first divergence."""

    step: int
    label: str
    path: str = ""
    detail: str = ""
    source_span: SourceSpanRef = field(default_factory=SourceSpanRef)

    def __post_init__(self) -> None:
        if not isinstance(self.step, int) or self.step < 0:
            raise ExplanationError("causal link step must be a non-negative int")
        object.__setattr__(
            self, "label", _text(self.label, "causal_link.label", maximum=256)
        )
        object.__setattr__(
            self, "path", _text(self.path, "causal_link.path", optional=True, maximum=512)
        )
        object.__setattr__(
            self,
            "detail",
            _text(self.detail, "causal_link.detail", optional=True, maximum=512),
        )
        if not isinstance(self.source_span, SourceSpanRef):
            if isinstance(self.source_span, Mapping):
                object.__setattr__(
                    self, "source_span", SourceSpanRef.from_dict(self.source_span)
                )
            else:
                raise ExplanationError("causal_link.source_span must be a SourceSpanRef")

    def to_dict(self) -> dict[str, Any]:
        return {
            "detail": self.detail,
            "label": self.label,
            "path": self.path,
            "source_span": self.source_span.to_dict(),
            "step": self.step,
        }


@dataclass(frozen=True, slots=True)
class AffectedProofHole:
    """Proof-hole reference affected by this counterexample (no proof claim)."""

    hole_id: str
    reason: str = ""
    kind: str = ""
    related_span_ids: tuple[str, ...] = ()
    formal_goal_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "hole_id", _text(self.hole_id, "proof_hole.hole_id", maximum=256)
        )
        object.__setattr__(
            self,
            "reason",
            _text(self.reason, "proof_hole.reason", optional=True, maximum=1024),
        )
        object.__setattr__(
            self, "kind", _text(self.kind, "proof_hole.kind", optional=True, maximum=128)
        )
        object.__setattr__(
            self,
            "related_span_ids",
            _string_tuple(self.related_span_ids, "related_span_ids"),
        )
        object.__setattr__(
            self,
            "formal_goal_id",
            _text(
                self.formal_goal_id,
                "formal_goal_id",
                optional=True,
                maximum=256,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "formal_goal_id": self.formal_goal_id,
            "hole_id": self.hole_id,
            "kind": self.kind,
            "reason": self.reason,
            "related_span_ids": list(self.related_span_ids),
        }


@dataclass(frozen=True, slots=True)
class ExplanationFact:
    """One replay-verified fact cited by the explanation."""

    role: FactRole | str
    statement: str
    path: str = ""
    value: Any = None
    replay_verified: bool = False
    provenance: str = ""
    fact_id: str = ""
    schema: str = EXPLANATION_FACT_SCHEMA

    def __post_init__(self) -> None:
        role = self.role
        if isinstance(role, str):
            try:
                role = FactRole(role)
            except ValueError as exc:
                raise ExplanationError(f"unsupported fact role {self.role!r}") from exc
        object.__setattr__(self, "role", role)
        object.__setattr__(
            self,
            "statement",
            _text(self.statement, "fact.statement", maximum=1024),
        )
        object.__setattr__(
            self, "path", _text(self.path, "fact.path", optional=True, maximum=512)
        )
        object.__setattr__(self, "value", _json_ready(_strip_private(self.value)))
        if not isinstance(self.replay_verified, bool):
            raise ExplanationError("fact.replay_verified must be boolean")
        object.__setattr__(
            self,
            "provenance",
            _text(self.provenance, "fact.provenance", optional=True, maximum=256),
        )
        object.__setattr__(
            self,
            "schema",
            _text(self.schema, "fact.schema", maximum=256) or EXPLANATION_FACT_SCHEMA,
        )
        payload = {
            "path": self.path,
            "provenance": self.provenance,
            "replay_verified": self.replay_verified,
            "role": self.role.value if isinstance(self.role, FactRole) else str(self.role),
            "schema": self.schema,
            "statement": self.statement,
            "value": self.value,
        }
        computed = _content_id("fact", payload)
        if self.fact_id:
            claimed = _text(self.fact_id, "fact_id", maximum=128)
            if claimed != computed:
                raise ExplanationError("fact identity does not match")
            object.__setattr__(self, "fact_id", claimed)
        else:
            object.__setattr__(self, "fact_id", computed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "path": self.path,
            "provenance": self.provenance,
            "replay_verified": self.replay_verified,
            "role": self.role.value if isinstance(self.role, FactRole) else str(self.role),
            "schema": self.schema,
            "statement": self.statement,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class RepairHypothesis:
    """Separately labeled repair hypothesis — never a proof claim."""

    repair_class: str
    detail: str
    status: HypothesisStatus | str = HypothesisStatus.HYPOTHESIS
    authority: str = "hypothesis"
    related_fact_ids: tuple[str, ...] = ()
    related_hole_ids: tuple[str, ...] = ()
    hypothesis_id: str = ""
    schema: str = REPAIR_HYPOTHESIS_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repair_class",
            _text(self.repair_class, "repair_class", maximum=128),
        )
        object.__setattr__(
            self, "detail", _text(self.detail, "hypothesis.detail", maximum=1024)
        )
        status = self.status
        if isinstance(status, str):
            try:
                status = HypothesisStatus(status)
            except ValueError as exc:
                raise ExplanationError(
                    f"unsupported hypothesis status {self.status!r}"
                ) from exc
        object.__setattr__(self, "status", status)
        authority = _text(self.authority, "hypothesis.authority", maximum=64).lower()
        if authority not in _HYPOTHESIS_AUTHORITIES:
            raise ExplanationError(
                f"repair hypothesis authority {authority!r} is not permitted "
                f"(must be one of {sorted(_HYPOTHESIS_AUTHORITIES)})"
            )
        object.__setattr__(self, "authority", authority)
        object.__setattr__(
            self,
            "related_fact_ids",
            _string_tuple(self.related_fact_ids, "related_fact_ids"),
        )
        object.__setattr__(
            self,
            "related_hole_ids",
            _string_tuple(self.related_hole_ids, "related_hole_ids"),
        )
        object.__setattr__(
            self,
            "schema",
            _text(self.schema, "hypothesis.schema", maximum=256)
            or REPAIR_HYPOTHESIS_SCHEMA,
        )
        body = {
            "authority": self.authority,
            "detail": self.detail,
            "related_fact_ids": list(self.related_fact_ids),
            "related_hole_ids": list(self.related_hole_ids),
            "repair_class": self.repair_class,
            "schema": self.schema,
            "status": self.status.value
            if isinstance(self.status, HypothesisStatus)
            else str(self.status),
        }
        if _claims_proof(body):
            raise ExplanationError("repair hypothesis must not claim proof")
        computed = _content_id("hypothesis", body)
        if self.hypothesis_id:
            claimed = _text(self.hypothesis_id, "hypothesis_id", maximum=128)
            if claimed != computed:
                raise ExplanationError("hypothesis identity does not match")
            object.__setattr__(self, "hypothesis_id", claimed)
        else:
            object.__setattr__(self, "hypothesis_id", computed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "detail": self.detail,
            "hypothesis_id": self.hypothesis_id,
            "related_fact_ids": list(self.related_fact_ids),
            "related_hole_ids": list(self.related_hole_ids),
            "repair_class": self.repair_class,
            "schema": self.schema,
            "status": self.status.value
            if isinstance(self.status, HypothesisStatus)
            else str(self.status),
        }


@dataclass(frozen=True, slots=True)
class CounterexampleExplanation:
    """Closed public explanation document (CounterexampleExplanation@1)."""

    counterexample_id: str
    violated_property: str
    witness_kind: str
    first_divergence: FirstDivergence
    decoded_values: tuple[DecodedValue, ...] = ()
    deltas: tuple[ExpectedActualDelta, ...] = ()
    causal_chain: tuple[CausalLink, ...] = ()
    assumptions: tuple[str, ...] = ()
    bounds: Mapping[str, Any] = field(default_factory=dict)
    source_spans: tuple[SourceSpanRef, ...] = ()
    affected_proof_holes: tuple[AffectedProofHole, ...] = ()
    repair_hypotheses: tuple[RepairHypothesis, ...] = ()
    cited_facts: tuple[ExplanationFact, ...] = ()
    unsupported_mappings: tuple[str, ...] = ()
    mapping_status: MappingStatus | str = MappingStatus.ABSENT
    replay_verified: bool = False
    replay_receipt_id: str = ""
    witness_content_id: str = ""
    summary: str = ""
    explanation_id: str = ""
    content_id: str = ""
    algorithm: str = ALGORITHM_NAME
    algorithm_version: str = ALGORITHM_VERSION
    schema: str = EXPLANATION_SCHEMA
    interface: str = COUNTEREXAMPLE_EXPLANATION_INTERFACE
    redacted: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "counterexample_id",
            _text(self.counterexample_id, "counterexample_id", maximum=256),
        )
        object.__setattr__(
            self,
            "violated_property",
            _text(self.violated_property, "violated_property", maximum=256),
        )
        object.__setattr__(
            self,
            "witness_kind",
            _text(self.witness_kind, "witness_kind", maximum=128),
        )
        if not isinstance(self.first_divergence, FirstDivergence):
            raise ExplanationError("first_divergence must be a FirstDivergence")
        object.__setattr__(
            self,
            "decoded_values",
            tuple(self.decoded_values),
        )
        if any(not isinstance(item, DecodedValue) for item in self.decoded_values):
            raise ExplanationError("decoded_values must be DecodedValue values")
        object.__setattr__(self, "deltas", tuple(self.deltas))
        if any(not isinstance(item, ExpectedActualDelta) for item in self.deltas):
            raise ExplanationError("deltas must be ExpectedActualDelta values")
        object.__setattr__(self, "causal_chain", tuple(self.causal_chain))
        if any(not isinstance(item, CausalLink) for item in self.causal_chain):
            raise ExplanationError("causal_chain must be CausalLink values")
        object.__setattr__(
            self, "assumptions", _string_tuple(self.assumptions, "assumptions")
        )
        object.__setattr__(
            self,
            "bounds",
            MappingProxyType(_strip_private(_mapping(self.bounds, "bounds"))),
        )
        object.__setattr__(self, "source_spans", tuple(self.source_spans))
        if any(not isinstance(item, SourceSpanRef) for item in self.source_spans):
            raise ExplanationError("source_spans must be SourceSpanRef values")
        object.__setattr__(
            self, "affected_proof_holes", tuple(self.affected_proof_holes)
        )
        if any(
            not isinstance(item, AffectedProofHole)
            for item in self.affected_proof_holes
        ):
            raise ExplanationError(
                "affected_proof_holes must be AffectedProofHole values"
            )
        object.__setattr__(
            self, "repair_hypotheses", tuple(self.repair_hypotheses)
        )
        if any(
            not isinstance(item, RepairHypothesis) for item in self.repair_hypotheses
        ):
            raise ExplanationError(
                "repair_hypotheses must be RepairHypothesis values"
            )
        for hyp in self.repair_hypotheses:
            if hyp.authority not in _HYPOTHESIS_AUTHORITIES:
                raise ExplanationError("repair hypothesis authority is elevated")
            if _claims_proof(hyp.to_dict()):
                raise ExplanationError("repair hypothesis must not claim proof")
        object.__setattr__(self, "cited_facts", tuple(self.cited_facts))
        if any(not isinstance(item, ExplanationFact) for item in self.cited_facts):
            raise ExplanationError("cited_facts must be ExplanationFact values")
        # Only replay-verified facts may be cited on the stable surface.
        for fact in self.cited_facts:
            if not fact.replay_verified:
                raise ExplanationError(
                    "explanations may only cite replay-verified facts; "
                    f"fact {fact.fact_id} is not replay_verified"
                )
        object.__setattr__(
            self,
            "unsupported_mappings",
            _string_tuple(self.unsupported_mappings, "unsupported_mappings"),
        )
        status = self.mapping_status
        if isinstance(status, str):
            try:
                status = MappingStatus(status)
            except ValueError as exc:
                raise ExplanationError(
                    f"unsupported mapping_status {self.mapping_status!r}"
                ) from exc
        object.__setattr__(self, "mapping_status", status)
        if not isinstance(self.replay_verified, bool):
            raise ExplanationError("replay_verified must be boolean")
        object.__setattr__(
            self,
            "replay_receipt_id",
            _text(
                self.replay_receipt_id,
                "replay_receipt_id",
                optional=True,
                maximum=256,
            ),
        )
        object.__setattr__(
            self,
            "witness_content_id",
            _text(
                self.witness_content_id,
                "witness_content_id",
                optional=True,
                maximum=256,
            ),
        )
        object.__setattr__(
            self,
            "summary",
            _text(self.summary, "summary", optional=True, maximum=512),
        )
        object.__setattr__(
            self,
            "algorithm",
            _text(self.algorithm, "algorithm", maximum=128) or ALGORITHM_NAME,
        )
        object.__setattr__(
            self,
            "algorithm_version",
            _text(self.algorithm_version, "algorithm_version", maximum=128)
            or ALGORITHM_VERSION,
        )
        object.__setattr__(
            self,
            "schema",
            _text(self.schema, "schema", maximum=256) or EXPLANATION_SCHEMA,
        )
        if self.schema != EXPLANATION_SCHEMA:
            raise ExplanationError(
                f"unsupported explanation schema {self.schema!r}"
            )
        object.__setattr__(
            self,
            "interface",
            _text(self.interface, "interface", maximum=128)
            or COUNTEREXAMPLE_EXPLANATION_INTERFACE,
        )
        if self.interface != COUNTEREXAMPLE_EXPLANATION_INTERFACE:
            raise ExplanationError(
                f"unsupported explanation interface {self.interface!r}"
            )
        if self.redacted is not True:
            raise ExplanationError("public explanations must be redacted")

        public = self._public_core()
        _assert_public_safe(public, label="counterexample explanation")
        if "raw" in public:
            raise ExplanationError("stable API must not return raw payload")
        computed_content = _sha256_hex(_canonical(public))
        if self.content_id:
            claimed = _text(self.content_id, "content_id", maximum=256)
            if claimed != computed_content:
                raise ExplanationError("explanation content identity does not match")
            object.__setattr__(self, "content_id", claimed)
        else:
            object.__setattr__(self, "content_id", computed_content)
        computed_id = _content_id("explanation", public)
        if self.explanation_id:
            claimed_id = _text(self.explanation_id, "explanation_id", maximum=128)
            if claimed_id != computed_id:
                raise ExplanationError("explanation identity does not match")
            object.__setattr__(self, "explanation_id", claimed_id)
        else:
            object.__setattr__(self, "explanation_id", computed_id)

    def _public_core(self) -> dict[str, Any]:
        return {
            "affected_proof_holes": [item.to_dict() for item in self.affected_proof_holes],
            "algorithm": self.algorithm,
            "algorithm_version": self.algorithm_version,
            "assumptions": list(self.assumptions),
            "bounds": dict(self.bounds),
            "causal_chain": [item.to_dict() for item in self.causal_chain],
            "cited_facts": [item.to_dict() for item in self.cited_facts],
            "counterexample_id": self.counterexample_id,
            "decoded_values": [item.to_dict() for item in self.decoded_values],
            "deltas": [item.to_dict() for item in self.deltas],
            "first_divergence": self.first_divergence.to_dict(),
            "interface": self.interface,
            "mapping_status": (
                self.mapping_status.value
                if isinstance(self.mapping_status, MappingStatus)
                else str(self.mapping_status)
            ),
            "redacted": True,
            "repair_hypotheses": [item.to_dict() for item in self.repair_hypotheses],
            "replay_receipt_id": self.replay_receipt_id,
            "replay_verified": self.replay_verified,
            "schema": self.schema,
            "source_spans": [item.to_dict() for item in self.source_spans],
            "summary": self.summary,
            "unsupported_mappings": list(self.unsupported_mappings),
            "violated_property": self.violated_property,
            "witness_content_id": self.witness_content_id,
            "witness_kind": self.witness_kind,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._public_core()
        payload["content_id"] = self.content_id
        payload["explanation_id"] = self.explanation_id
        return payload

    def to_public_dict(self) -> dict[str, Any]:
        """Stable public API projection — never includes raw material."""

        public = self.to_dict()
        public.pop("raw", None)
        _assert_public_safe(public, label="explanation public projection")
        return public

    def to_json(self) -> str:
        return json.dumps(
            self.to_public_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CounterexampleExplanation":
        data = _mapping(value, "explanation")
        if "raw" in data:
            raise ExplanationError("explanation must not contain raw payload")
        first = data.get("first_divergence")
        if not isinstance(first, Mapping):
            raise ExplanationError("first_divergence is required")
        return cls(
            counterexample_id=str(data.get("counterexample_id") or ""),
            violated_property=str(data.get("violated_property") or ""),
            witness_kind=str(data.get("witness_kind") or ""),
            first_divergence=FirstDivergence(
                kind=str(first.get("kind") or DivergenceKind.UNSUPPORTED.value),
                path=str(first.get("path") or ""),
                detail=str(first.get("detail") or ""),
                expected=first.get("expected"),
                actual=first.get("actual"),
                index=first.get("index"),
                source_span=SourceSpanRef.from_dict(first.get("source_span")),
                divergence_id=str(first.get("divergence_id") or ""),
            ),
            decoded_values=tuple(
                DecodedValue(
                    name=str(item.get("name") or ""),
                    value=item.get("value"),
                    path=str(item.get("path") or ""),
                    role=str(item.get("role") or "assignment"),
                )
                for item in (data.get("decoded_values") or ())
                if isinstance(item, Mapping)
            ),
            deltas=tuple(
                ExpectedActualDelta(
                    path=str(item.get("path") or ""),
                    expected=item.get("expected"),
                    actual=item.get("actual"),
                )
                for item in (data.get("deltas") or ())
                if isinstance(item, Mapping)
            ),
            causal_chain=tuple(
                CausalLink(
                    step=int(item.get("step") or 0),
                    label=str(item.get("label") or ""),
                    path=str(item.get("path") or ""),
                    detail=str(item.get("detail") or ""),
                    source_span=SourceSpanRef.from_dict(item.get("source_span")),
                )
                for item in (data.get("causal_chain") or ())
                if isinstance(item, Mapping)
            ),
            assumptions=tuple(data.get("assumptions") or ()),
            bounds=dict(data.get("bounds") or {}),
            source_spans=tuple(
                SourceSpanRef.from_dict(item)
                for item in (data.get("source_spans") or ())
                if isinstance(item, Mapping)
            ),
            affected_proof_holes=tuple(
                AffectedProofHole(
                    hole_id=str(item.get("hole_id") or ""),
                    reason=str(item.get("reason") or ""),
                    kind=str(item.get("kind") or ""),
                    related_span_ids=tuple(item.get("related_span_ids") or ()),
                    formal_goal_id=str(item.get("formal_goal_id") or ""),
                )
                for item in (data.get("affected_proof_holes") or ())
                if isinstance(item, Mapping)
            ),
            repair_hypotheses=tuple(
                RepairHypothesis(
                    repair_class=str(item.get("repair_class") or ""),
                    detail=str(item.get("detail") or ""),
                    status=str(item.get("status") or HypothesisStatus.HYPOTHESIS.value),
                    authority=str(item.get("authority") or "hypothesis"),
                    related_fact_ids=tuple(item.get("related_fact_ids") or ()),
                    related_hole_ids=tuple(item.get("related_hole_ids") or ()),
                    hypothesis_id=str(item.get("hypothesis_id") or ""),
                )
                for item in (data.get("repair_hypotheses") or ())
                if isinstance(item, Mapping)
            ),
            cited_facts=tuple(
                ExplanationFact(
                    role=str(item.get("role") or FactRole.DECODED_VALUE.value),
                    statement=str(item.get("statement") or ""),
                    path=str(item.get("path") or ""),
                    value=item.get("value"),
                    replay_verified=bool(item.get("replay_verified")),
                    provenance=str(item.get("provenance") or ""),
                    fact_id=str(item.get("fact_id") or ""),
                )
                for item in (data.get("cited_facts") or ())
                if isinstance(item, Mapping)
            ),
            unsupported_mappings=tuple(data.get("unsupported_mappings") or ()),
            mapping_status=str(
                data.get("mapping_status") or MappingStatus.ABSENT.value
            ),
            replay_verified=bool(data.get("replay_verified")),
            replay_receipt_id=str(data.get("replay_receipt_id") or ""),
            witness_content_id=str(data.get("witness_content_id") or ""),
            summary=str(data.get("summary") or ""),
            explanation_id=str(data.get("explanation_id") or ""),
            content_id=str(data.get("content_id") or ""),
            algorithm=str(data.get("algorithm") or ALGORITHM_NAME),
            algorithm_version=str(data.get("algorithm_version") or ALGORITHM_VERSION),
            schema=str(data.get("schema") or EXPLANATION_SCHEMA),
            interface=str(
                data.get("interface") or COUNTEREXAMPLE_EXPLANATION_INTERFACE
            ),
            redacted=True,
        )


@runtime_checkable
class CounterexampleExplanationProtocol(Protocol):
    """CounterexampleExplanation@1 structural contract."""

    interface: str

    def explain(
        self,
        witness: Mapping[str, Any] | Any,
        *,
        expected: Mapping[str, Any] | None = None,
        proof_holes: Sequence[Mapping[str, Any] | Any] | None = None,
        replay_receipt: Mapping[str, Any] | Any | None = None,
        replay_verified: bool | None = None,
    ) -> CounterexampleExplanation:
        ...


# ---------------------------------------------------------------------------
# Derivation helpers
# ---------------------------------------------------------------------------


_HYPOTHESIS_DETAIL: Final[Mapping[str, str]] = MappingProxyType(
    {
        "add_or_correct_dependency": (
            "Hypothesis: add or correct a missing dependency that the "
            "replay-verified witness requires."
        ),
        "split_non_atomic_task": (
            "Hypothesis: split a non-atomic obligation so the first "
            "divergence can be discharged independently."
        ),
        "tighten_authority_or_fencing": (
            "Hypothesis: tighten authority or fencing around the first "
            "divergence; does not claim a completed proof."
        ),
        "add_obligation_or_fallback_test": (
            "Hypothesis: add an obligation or fallback test covering the "
            "observed divergence."
        ),
        "constrain_ast_scope_or_model_bound": (
            "Hypothesis: constrain the AST scope or model bound related to "
            "the decoded assignments."
        ),
        "add_premise_or_evidence_dependency": (
            "Hypothesis: add a premise or evidence dependency supporting "
            "the violated property."
        ),
        "adjust_portfolio_or_resource_bound": (
            "Hypothesis: adjust portfolio or resource bounds (not a proof)."
        ),
        "request_scoped_human_review": (
            "Hypothesis: request scoped human review of the first divergence."
        ),
    }
)


def _project_envelope(witness: Any) -> Any:
    """Project through the public boundary; fall back to a stripped view."""

    try:
        from ipfs_datasets_py.logic.software_verification.counterexamples.contracts import (
            CounterexampleBoundaryError,
            project_public_counterexample,
        )
    except ImportError:
        return None

    try:
        return project_public_counterexample(witness)
    except CounterexampleBoundaryError:
        return None
    except Exception:
        return None


def _public_source_identifiers(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Harvest public source/AST identity refs from a raw witness.

    The public envelope normalizer only carries tree/ast bindings that land in
    supervisor ``CounterexampleBindings``. Nested ``source_map`` span and source
    refs are public identifiers (never source text) and must remain available
    for stable first-divergence explanations. Unsupported mapping markers are
    likewise preserved explicitly rather than invented.
    """

    collected: dict[str, list[str]] = {
        "ast_scope_ids": [],
        "source_ref_ids": [],
        "span_ids": [],
        "tree_ids": [],
    }
    meta: dict[str, Any] = {}

    def absorb(mapping: Mapping[str, Any] | None) -> None:
        if not isinstance(mapping, Mapping):
            return
        for key in collected:
            value = mapping.get(key)
            if isinstance(value, str) and value.strip():
                collected[key].append(value.strip())
            elif isinstance(value, Sequence) and not isinstance(
                value, (str, bytes, bytearray)
            ):
                for item in value:
                    text = str(item).strip()
                    if text and not _is_private_or_forbidden_key(text):
                        collected[key].append(text)
        # Singular aliases used by some frontends.
        aliases = {
            "span_id": "span_ids",
            "source_ref_id": "source_ref_ids",
            "ast_scope_id": "ast_scope_ids",
            "tree_id": "tree_ids",
            "scope_id": "ast_scope_ids",
        }
        for src, dest in aliases.items():
            value = mapping.get(src)
            if isinstance(value, str) and value.strip():
                collected[dest].append(value.strip())
        if mapping.get("mapping_status"):
            meta["mapping_status"] = str(mapping.get("mapping_status")).lower()
        if mapping.get("unsupported") is True or mapping.get("supported") is False:
            meta["unsupported"] = True
        for reason_key in ("unsupported_reasons", "unsupported_mappings"):
            if reason_key in mapping and reason_key not in meta:
                meta[reason_key] = mapping.get(reason_key)
        if mapping.get("status") and str(mapping.get("status")).lower() in {
            s.value for s in MappingStatus
        }:
            meta.setdefault("mapping_status", str(mapping.get("status")).lower())

    absorb(raw)
    source_map = raw.get("source_map")
    if isinstance(source_map, Mapping):
        absorb(source_map)
    bindings = raw.get("bindings")
    if isinstance(bindings, Mapping):
        absorb(bindings)

    result: dict[str, Any] = {
        key: sorted(set(values)) for key, values in collected.items() if values
    }
    result.update(meta)
    return result


def _merge_source_map(
    projected: Mapping[str, Any],
    harvested: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge projected envelope source_map with harvested public identifiers."""

    merged: dict[str, Any] = {}
    for key in ("ast_scope_ids", "source_ref_ids", "span_ids", "tree_ids"):
        values: list[str] = []
        for source in (projected, harvested):
            value = source.get(key) if isinstance(source, Mapping) else None
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
            elif isinstance(value, Sequence) and not isinstance(
                value, (str, bytes, bytearray)
            ):
                values.extend(str(item).strip() for item in value if str(item).strip())
        if values:
            merged[key] = sorted(set(values))
    # Explicit unsupported / status markers from the original witness win when
    # the envelope flattened them away.
    for key in (
        "mapping_status",
        "unsupported",
        "unsupported_reasons",
        "unsupported_mappings",
        "status",
        "supported",
    ):
        if key in harvested:
            merged[key] = harvested[key]
        elif key in projected:
            merged[key] = projected[key]
    return merged


def _envelope_view(witness: Any) -> dict[str, Any]:
    raw = _as_mapping(witness)
    harvested = _public_source_identifiers(raw)
    envelope = _project_envelope(witness)
    if envelope is not None:
        public = envelope.to_public_dict()
        public.pop("raw", None)
        existing = public.get("source_map")
        if not isinstance(existing, Mapping):
            existing = {}
        public["source_map"] = _merge_source_map(existing, harvested)
        return public
    cleaned = _strip_private(raw)
    if isinstance(cleaned, dict):
        cleaned.pop("raw", None)
        existing = cleaned.get("source_map")
        if not isinstance(existing, Mapping):
            existing = {}
        cleaned["source_map"] = _merge_source_map(existing, harvested)
        return cleaned
    raise ExplanationError("witness could not be projected to a public view")


def _normalize_kind(kind: str) -> str:
    value = kind.strip().lower().replace("-", "_")
    aliases = {
        "model": "smt_model",
        "smt": "smt_model",
        "assignments": "smt_model",
        "unsat_core": "smt_core",
        "smt_unsat_core": "smt_core",
        "core": "smt_core",
        "tla_trace": "trace",
        "trace": "trace",
        "runtime_mtl_violation": "trace",
        "protocol_attack": "protocol_attack",
        "protocol": "protocol_attack",
        "hypertrace": "hypertrace",
        "kernel_error": "kernel",
        "kernel": "kernel",
        "generic_failure": "generic",
        "generic": "generic",
    }
    return aliases.get(value, value or "generic")


def _payload_of(view: Mapping[str, Any]) -> dict[str, Any]:
    nested = view.get("payload")
    if isinstance(nested, Mapping) and nested:
        return _strip_private(dict(nested))
    public: dict[str, Any] = {}
    for key in (
        "assignments",
        "model",
        "core",
        "unsat_core",
        "steps",
        "trace",
        "events",
        "states",
        "roles",
        "messages",
        "differences",
        "observed_fields",
        "failure_code",
        "theorem_id",
        "artifact_id",
        "labels",
        "prefix",
        "lasso",
    ):
        if key in view:
            public[key] = _strip_private(view[key])
    return public


def _decode_values(kind: str, payload: Mapping[str, Any]) -> list[DecodedValue]:
    decoded: list[DecodedValue] = []
    if kind in {"smt_model", "generic"}:
        assignments = payload.get("assignments") or payload.get("model") or {}
        if isinstance(assignments, Mapping):
            for name in sorted(assignments, key=str):
                decoded.append(
                    DecodedValue(
                        name=str(name),
                        value=assignments[name],
                        path=f"assignments.{name}",
                        role="assignment",
                    )
                )
    if kind == "smt_core":
        core = payload.get("core") or payload.get("unsat_core") or ()
        if isinstance(core, Sequence) and not isinstance(core, (str, bytes, bytearray)):
            for index, member in enumerate(core):
                decoded.append(
                    DecodedValue(
                        name=str(member),
                        value=True,
                        path=f"core[{index}]",
                        role="core_member",
                    )
                )
    if kind in {"trace", "protocol_attack"}:
        steps = payload.get("steps") or payload.get("trace") or payload.get("events") or ()
        if isinstance(steps, Sequence) and not isinstance(steps, (str, bytes, bytearray)):
            for index, step in enumerate(steps):
                if isinstance(step, Mapping):
                    label = step.get("label") or step.get("action") or step.get("type") or index
                    decoded.append(
                        DecodedValue(
                            name=str(label),
                            value=_strip_private(dict(step)),
                            path=f"steps[{index}]",
                            role="step",
                        )
                    )
                else:
                    decoded.append(
                        DecodedValue(
                            name=str(step),
                            value=step,
                            path=f"steps[{index}]",
                            role="step",
                        )
                    )
        if kind == "protocol_attack":
            for role_name in payload.get("roles") or ():
                decoded.append(
                    DecodedValue(
                        name=str(role_name),
                        value=True,
                        path=f"roles.{role_name}",
                        role="role",
                    )
                )
            for index, message in enumerate(payload.get("messages") or ()):
                decoded.append(
                    DecodedValue(
                        name=str(message) if not isinstance(message, Mapping) else str(
                            message.get("type") or message.get("label") or index
                        ),
                        value=_strip_private(message) if isinstance(message, Mapping) else message,
                        path=f"messages[{index}]",
                        role="message",
                    )
                )
    if kind == "hypertrace":
        for index, diff in enumerate(payload.get("differences") or ()):
            if isinstance(diff, Mapping):
                field_name = str(diff.get("field") or f"diff[{index}]")
                decoded.append(
                    DecodedValue(
                        name=field_name,
                        value=_strip_private(dict(diff)),
                        path=f"differences[{index}]",
                        role="observation_diff",
                    )
                )
        for field_name in payload.get("observed_fields") or ():
            decoded.append(
                DecodedValue(
                    name=str(field_name),
                    value=True,
                    path=f"observed_fields.{field_name}",
                    role="observed_field",
                )
            )
    if kind == "kernel":
        for key in ("failure_code", "theorem_id", "artifact_id"):
            if key in payload:
                decoded.append(
                    DecodedValue(
                        name=key,
                        value=payload.get(key),
                        path=key,
                        role="kernel",
                    )
                )
    return decoded


def _compute_deltas(
    kind: str,
    payload: Mapping[str, Any],
    expected: Mapping[str, Any] | None,
) -> list[ExpectedActualDelta]:
    deltas: list[ExpectedActualDelta] = []
    if not expected:
        return deltas
    expected_payload = expected
    nested = expected.get("payload") if isinstance(expected, Mapping) else None
    if isinstance(nested, Mapping):
        expected_payload = nested

    if kind in {"smt_model", "generic"}:
        actual_map = payload.get("assignments") or payload.get("model") or {}
        expected_map = (
            expected_payload.get("assignments")
            or expected_payload.get("model")
            or expected_payload
        )
        if isinstance(actual_map, Mapping) and isinstance(expected_map, Mapping):
            names = sorted(set(actual_map) | set(expected_map), key=str)
            for name in names:
                deltas.append(
                    ExpectedActualDelta(
                        path=f"assignments.{name}",
                        expected=expected_map.get(name),
                        actual=actual_map.get(name),
                    )
                )
    elif kind == "hypertrace":
        # Compare first differing observation when expected provides differences.
        actual_diffs = list(payload.get("differences") or ())
        expected_diffs = list(expected_payload.get("differences") or ())
        limit = max(len(actual_diffs), len(expected_diffs))
        for index in range(limit):
            actual = actual_diffs[index] if index < len(actual_diffs) else None
            exp = expected_diffs[index] if index < len(expected_diffs) else None
            field_name = ""
            if isinstance(actual, Mapping):
                field_name = str(actual.get("field") or "")
            elif isinstance(exp, Mapping):
                field_name = str(exp.get("field") or "")
            deltas.append(
                ExpectedActualDelta(
                    path=f"differences[{index}]{('.' + field_name) if field_name else ''}",
                    expected=exp,
                    actual=actual,
                )
            )
    else:
        # Generic structural compare on overlapping keys.
        for key in sorted(set(payload) & set(expected_payload), key=str):
            deltas.append(
                ExpectedActualDelta(
                    path=str(key),
                    expected=expected_payload.get(key),
                    actual=payload.get(key),
                )
            )
    return deltas


def _first_divergence(
    kind: str,
    payload: Mapping[str, Any],
    *,
    source_span: SourceSpanRef,
    deltas: Sequence[ExpectedActualDelta],
    violated_property: str,
) -> FirstDivergence:
    if kind in {"smt_model", "generic"}:
        unequal = [delta for delta in deltas if not delta.equal]
        if unequal:
            first = unequal[0]
            return FirstDivergence(
                kind=DivergenceKind.VIOLATED_CONDITION,
                path=first.path,
                detail=(
                    f"first expected/actual mismatch for {violated_property} "
                    f"at {first.path}"
                ),
                expected=first.expected,
                actual=first.actual,
                index=0,
                source_span=source_span,
            )
        assignments = payload.get("assignments") or payload.get("model") or {}
        if isinstance(assignments, Mapping) and assignments:
            name = sorted(assignments, key=str)[0]
            return FirstDivergence(
                kind=DivergenceKind.VIOLATED_CONDITION,
                path=f"assignments.{name}",
                detail=(
                    f"property {violated_property} violated under decoded "
                    f"assignment {name}"
                ),
                expected=None,
                actual=assignments[name],
                index=0,
                source_span=source_span,
            )
    if kind == "smt_core":
        core = list(payload.get("core") or payload.get("unsat_core") or ())
        if core:
            return FirstDivergence(
                kind=DivergenceKind.VIOLATED_CONDITION,
                path="core[0]",
                detail=f"unsat core member {core[0]!r} contributes to unsatisfiability",
                expected=None,
                actual=core[0],
                index=0,
                source_span=source_span,
            )
    if kind == "trace":
        steps = list(payload.get("steps") or payload.get("trace") or payload.get("events") or ())
        for index, step in enumerate(steps):
            label = ""
            if isinstance(step, Mapping):
                label = str(step.get("label") or step.get("action") or step.get("type") or "")
            else:
                label = str(step)
            if label.lower() in {"bad", "error", "violate", "violation", "fail", "failed"}:
                return FirstDivergence(
                    kind=DivergenceKind.TRACE_STEP,
                    path=f"steps[{index}]",
                    detail=f"first violating trace step {label!r}",
                    expected="safe",
                    actual=label,
                    index=index,
                    source_span=source_span,
                )
        if steps:
            last_index = len(steps) - 1
            last = steps[last_index]
            label = (
                str(last.get("label") or last.get("action") or last)
                if isinstance(last, Mapping)
                else str(last)
            )
            return FirstDivergence(
                kind=DivergenceKind.TRACE_STEP,
                path=f"steps[{last_index}]",
                detail=f"terminal trace step {label!r} under violated property",
                expected=None,
                actual=label,
                index=last_index,
                source_span=source_span,
            )
    if kind == "protocol_attack":
        messages = list(payload.get("messages") or ())
        for index, message in enumerate(messages):
            label = (
                str(message.get("type") or message.get("label") or message)
                if isinstance(message, Mapping)
                else str(message)
            )
            if label.lower() in {"forge", "inject", "attack", "spoof"}:
                return FirstDivergence(
                    kind=DivergenceKind.PROTOCOL_STEP,
                    path=f"messages[{index}]",
                    detail=f"first protocol attack step {label!r}",
                    expected="honest",
                    actual=label,
                    index=index,
                    source_span=source_span,
                )
        steps = list(payload.get("steps") or ())
        for index, step in enumerate(steps):
            label = (
                str(step.get("action") or step.get("label") or step)
                if isinstance(step, Mapping)
                else str(step)
            )
            if label.lower() in {"forge", "inject", "attack", "spoof", "accept"}:
                return FirstDivergence(
                    kind=DivergenceKind.PROTOCOL_STEP,
                    path=f"steps[{index}]",
                    detail=f"first protocol attack step {label!r}",
                    expected="honest",
                    actual=label,
                    index=index,
                    source_span=source_span,
                )
    if kind == "hypertrace":
        differences = list(payload.get("differences") or ())
        for index, diff in enumerate(differences):
            if isinstance(diff, Mapping):
                field_name = str(diff.get("field") or f"diff[{index}]")
                return FirstDivergence(
                    kind=DivergenceKind.OBSERVATION_DIVERGENCE,
                    path=f"differences[{index}].{field_name}",
                    detail=f"first observation divergence on field {field_name!r}",
                    expected=diff.get("left"),
                    actual=diff.get("right"),
                    index=index,
                    source_span=source_span,
                )
            return FirstDivergence(
                kind=DivergenceKind.OBSERVATION_DIVERGENCE,
                path=f"differences[{index}]",
                detail="first observation divergence",
                expected=None,
                actual=diff,
                index=index,
                source_span=source_span,
            )
    if kind == "kernel":
        code = payload.get("failure_code") or "kernel_failure"
        return FirstDivergence(
            kind=DivergenceKind.KERNEL_FAILURE,
            path="failure_code",
            detail=f"kernel failure {code!r}",
            expected="accepted",
            actual=code,
            index=0,
            source_span=source_span,
        )
    return FirstDivergence(
        kind=DivergenceKind.UNSUPPORTED,
        path="",
        detail="no supported first-divergence mapping for this witness family",
        expected=None,
        actual=None,
        index=None,
        source_span=source_span,
    )


def _causal_chain(
    kind: str,
    payload: Mapping[str, Any],
    divergence: FirstDivergence,
    source_span: SourceSpanRef,
) -> list[CausalLink]:
    links: list[CausalLink] = []
    if kind in {"trace", "protocol_attack"}:
        steps = list(payload.get("steps") or payload.get("trace") or payload.get("events") or ())
        limit = (
            (divergence.index + 1)
            if isinstance(divergence.index, int)
            else len(steps)
        )
        for index, step in enumerate(steps[: max(0, limit)]):
            if isinstance(step, Mapping):
                label = str(
                    step.get("label") or step.get("action") or step.get("type") or index
                )
                path = f"steps[{index}]"
            else:
                label = str(step)
                path = f"steps[{index}]"
            links.append(
                CausalLink(
                    step=index,
                    label=label,
                    path=path,
                    detail="prefix step retained in causal slice",
                    source_span=source_span,
                )
            )
        if kind == "protocol_attack":
            for index, message in enumerate(payload.get("messages") or ()):
                label = (
                    str(message.get("type") or message.get("label") or message)
                    if isinstance(message, Mapping)
                    else str(message)
                )
                links.append(
                    CausalLink(
                        step=len(links),
                        label=f"message:{label}",
                        path=f"messages[{index}]",
                        detail="protocol message in attack slice",
                        source_span=source_span,
                    )
                )
                if isinstance(divergence.index, int) and index >= divergence.index:
                    if divergence.path.startswith("messages"):
                        break
    elif kind == "hypertrace":
        for index, field_name in enumerate(payload.get("observed_fields") or ()):
            links.append(
                CausalLink(
                    step=index,
                    label=str(field_name),
                    path=f"observed_fields.{field_name}",
                    detail="observed field in hypertrace slice",
                    source_span=source_span,
                )
            )
        if divergence.path:
            links.append(
                CausalLink(
                    step=len(links),
                    label="first_observation_divergence",
                    path=divergence.path,
                    detail=divergence.detail,
                    source_span=source_span,
                )
            )
    elif kind in {"smt_model", "smt_core", "generic", "kernel"}:
        # Assignment / core causal slice: decoded contributors in stable order.
        for index, name in enumerate(
            sorted(
                (
                    str(k)
                    for k in (
                        (payload.get("assignments") or payload.get("model") or {})
                        if isinstance(
                            payload.get("assignments") or payload.get("model"), Mapping
                        )
                        else {}
                    )
                ),
                key=str,
            )
        ):
            links.append(
                CausalLink(
                    step=index,
                    label=name,
                    path=f"assignments.{name}",
                    detail="decoded assignment in causal slice",
                    source_span=source_span,
                )
            )
            if divergence.path.endswith(f".{name}") or divergence.path == f"assignments.{name}":
                break
        if not links and divergence.path:
            links.append(
                CausalLink(
                    step=0,
                    label=divergence.path or "divergence",
                    path=divergence.path,
                    detail=divergence.detail,
                    source_span=source_span,
                )
            )
    if not links and divergence.path:
        links.append(
            CausalLink(
                step=0,
                label="first_divergence",
                path=divergence.path,
                detail=divergence.detail,
                source_span=source_span,
            )
        )
    return links


def _extract_assumptions(view: Mapping[str, Any]) -> tuple[str, ...]:
    for key in ("assumptions", "assumption_ids"):
        if key in view:
            return _string_tuple(view.get(key), key)
    return ()


def _extract_bounds(view: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("bounds", "finite_bounds"):
        value = view.get(key)
        if isinstance(value, Mapping) and value:
            return _strip_private(dict(value))
    return {}


def _extract_property(view: Mapping[str, Any]) -> str:
    for key in ("violated_property", "property_id"):
        value = view.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "property:unknown"


def _extract_counterexample_id(view: Mapping[str, Any]) -> str:
    for key in ("counterexample_id", "content_id", "semantic_id"):
        value = view.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"cex:{_digest(view)[:16]}"


def _extract_witness_content_id(view: Mapping[str, Any]) -> str:
    for key in ("content_id", "semantic_id", "counterexample_id"):
        value = view.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return _sha256_hex(_canonical(view))


def _extract_kind_from_view(view: Mapping[str, Any]) -> str:
    kind = view.get("kind")
    if isinstance(kind, str) and kind.strip():
        return _normalize_kind(kind)
    return _normalize_kind("generic")


def _source_map_of(view: Mapping[str, Any]) -> dict[str, Any]:
    source_map = view.get("source_map")
    if isinstance(source_map, Mapping):
        return dict(source_map)
    # Build from top-level ids when envelope projection already flattened them.
    built: dict[str, Any] = {}
    for key in ("span_ids", "source_ref_ids", "ast_scope_ids", "tree_ids"):
        if key in view:
            built[key] = view[key]
    bindings = view.get("bindings")
    if isinstance(bindings, Mapping):
        for key in ("span_ids", "source_ref_ids", "ast_scope_ids", "tree_ids"):
            if key in bindings and key not in built:
                built[key] = bindings[key]
        if bindings.get("mapping_status"):
            built["mapping_status"] = bindings["mapping_status"]
        if bindings.get("unsupported") is True:
            built["unsupported"] = True
    if view.get("mapping_status"):
        built["mapping_status"] = view["mapping_status"]
    if view.get("unsupported_mapping") is True or view.get("unsupported") is True:
        built["unsupported"] = True
    return built


def _unsupported_mapping_notes(
    source_span: SourceSpanRef,
    source_map: Mapping[str, Any],
) -> list[str]:
    notes: list[str] = []
    status = source_span.mapping_status
    if status is MappingStatus.UNSUPPORTED:
        notes.append("source_map.mapping_status=unsupported")
    elif status is MappingStatus.ABSENT:
        notes.append("source_map.absent")
    elif status is MappingStatus.PARTIAL:
        if not source_span.span_ids:
            notes.append("source_map.span_ids.missing")
        if not source_span.ast_scope_ids:
            notes.append("source_map.ast_scope_ids.missing")
        if not source_span.source_ref_ids:
            notes.append("source_map.source_ref_ids.missing")
    # Explicit free-form unsupported markers (never invent spans).
    explicit = source_map.get("unsupported_reasons") or source_map.get("unsupported_mappings")
    if isinstance(explicit, Sequence) and not isinstance(explicit, (str, bytes, bytearray)):
        for item in explicit:
            text = str(item).strip()
            if text:
                notes.append(text)
    elif isinstance(explicit, str) and explicit.strip():
        notes.append(explicit.strip())
    return sorted(set(notes))


def _normalize_proof_hole(item: Any) -> AffectedProofHole | None:
    if item is None:
        return None
    if isinstance(item, AffectedProofHole):
        return item
    data = _as_mapping(item)
    hole_id = str(
        data.get("hole_id") or data.get("id") or data.get("proof_hole_id") or ""
    ).strip()
    if not hole_id:
        return None
    related: list[str] = []
    source = data.get("source")
    if isinstance(source, Mapping):
        for key in ("span_ids", "span_id"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                related.append(value.strip())
            elif isinstance(value, Sequence) and not isinstance(
                value, (str, bytes, bytearray)
            ):
                related.extend(str(v) for v in value if str(v).strip())
        span = source.get("span")
        if isinstance(span, Mapping) and span.get("span_id"):
            related.append(str(span["span_id"]))
    for key in ("related_span_ids", "span_ids"):
        value = data.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            related.extend(str(v) for v in value if str(v).strip())
        elif isinstance(value, str) and value.strip():
            related.append(value.strip())
    kind = data.get("kind")
    kind_text = kind.value if hasattr(kind, "value") else str(kind or "")
    return AffectedProofHole(
        hole_id=hole_id,
        reason=str(data.get("reason") or ""),
        kind=kind_text,
        related_span_ids=tuple(related),
        formal_goal_id=str(data.get("formal_goal_id") or ""),
    )


def _select_affected_holes(
    proof_holes: Sequence[Any] | None,
    *,
    source_span: SourceSpanRef,
    violated_property: str,
) -> list[AffectedProofHole]:
    if not proof_holes:
        return []
    span_set = set(source_span.span_ids)
    selected: list[AffectedProofHole] = []
    for raw in proof_holes:
        hole = _normalize_proof_hole(raw)
        if hole is None:
            continue
        data = _as_mapping(raw) if not isinstance(raw, AffectedProofHole) else hole.to_dict()
        # Reject proof claims on input holes for the explanation surface.
        if _claims_proof(data):
            continue
        related = set(hole.related_span_ids)
        property_match = violated_property and (
            violated_property in hole.reason
            or violated_property == str(data.get("violated_property") or "")
            or violated_property == str(data.get("property_id") or "")
            or violated_property == hole.formal_goal_id
        )
        span_match = bool(span_set & related) if span_set and related else False
        # If no span information on either side, keep holes that share property
        # identity; otherwise require span or property overlap.
        if span_match or property_match or (not span_set and not related):
            selected.append(hole)
    # Stable order by hole_id.
    selected.sort(key=lambda item: item.hole_id)
    return selected


def _repair_classes_of(view: Mapping[str, Any], kind: str) -> list[str]:
    classes = view.get("repair_classes") or ()
    items: list[str] = []
    if isinstance(classes, Sequence) and not isinstance(classes, (str, bytes, bytearray)):
        for item in classes:
            text = item.value if hasattr(item, "value") else str(item)
            if text.strip():
                items.append(text.strip())
    if items:
        return sorted(set(items))
    defaults = {
        "smt_model": [
            "add_premise_or_evidence_dependency",
            "constrain_ast_scope_or_model_bound",
        ],
        "smt_core": [
            "add_premise_or_evidence_dependency",
            "split_non_atomic_task",
        ],
        "trace": [
            "split_non_atomic_task",
            "tighten_authority_or_fencing",
        ],
        "protocol_attack": [
            "tighten_authority_or_fencing",
            "add_obligation_or_fallback_test",
        ],
        "hypertrace": [
            "constrain_ast_scope_or_model_bound",
            "add_obligation_or_fallback_test",
        ],
        "kernel": [
            "add_premise_or_evidence_dependency",
            "add_obligation_or_fallback_test",
        ],
        "generic": ["request_scoped_human_review"],
    }
    return list(defaults.get(kind, defaults["generic"]))


def _build_hypotheses(
    repair_classes: Sequence[str],
    *,
    related_fact_ids: Sequence[str],
    related_hole_ids: Sequence[str],
    divergence: FirstDivergence,
) -> list[RepairHypothesis]:
    hypotheses: list[RepairHypothesis] = []
    for repair_class in repair_classes:
        detail = _HYPOTHESIS_DETAIL.get(
            repair_class,
            f"Hypothesis: consider repair class {repair_class!r} for "
            f"{divergence.path or 'first divergence'}; does not claim proof.",
        )
        hypotheses.append(
            RepairHypothesis(
                repair_class=repair_class,
                detail=detail,
                status=HypothesisStatus.HYPOTHESIS,
                authority="hypothesis",
                related_fact_ids=tuple(related_fact_ids),
                related_hole_ids=tuple(related_hole_ids),
            )
        )
    return hypotheses


def _resolve_replay_verification(
    *,
    replay_receipt: Mapping[str, Any] | Any | None,
    replay_verified: bool | None,
) -> tuple[bool, str]:
    receipt_id = ""
    verified = False
    if replay_receipt is not None:
        data = _as_mapping(replay_receipt)
        receipt_id = str(
            data.get("receipt_id")
            or data.get("content_id")
            or data.get("result_id")
            or ""
        ).strip()
        status = str(data.get("status") or "").lower()
        violation = data.get("violation_reproduced")
        reproduced = data.get("reproduced")
        if status in {"reproduced", "succeeded", "success"}:
            verified = True
        if violation is True or reproduced is True:
            verified = True
        if status in {
            "not_reproduced",
            "binding_mismatch",
            "unavailable",
            "unsupported",
            "error",
            "failed",
        }:
            verified = False
    if replay_verified is not None:
        # Explicit caller attestation may only *downgrade* automatic detection
        # when False; True requires a supporting receipt or is accepted for
        # hermetic tests that already re-ran the oracle out of band.
        if replay_verified is False:
            verified = False
        elif replay_verified is True:
            verified = True
    return verified, receipt_id


def _build_cited_facts(
    *,
    replay_verified: bool,
    replay_receipt_id: str,
    decoded: Sequence[DecodedValue],
    deltas: Sequence[ExpectedActualDelta],
    divergence: FirstDivergence,
    causal: Sequence[CausalLink],
    assumptions: Sequence[str],
    bounds: Mapping[str, Any],
    source_span: SourceSpanRef,
    holes: Sequence[AffectedProofHole],
    violated_property: str,
) -> list[ExplanationFact]:
    if not replay_verified:
        # Do not cite any facts without replay verification.
        return []
    provenance = replay_receipt_id or "replay:verified"
    facts: list[ExplanationFact] = [
        ExplanationFact(
            role=FactRole.REPLAY_RECEIPT,
            statement="counterexample violation reproduced under exact bindings",
            path="replay",
            value={"replay_receipt_id": replay_receipt_id} if replay_receipt_id else True,
            replay_verified=True,
            provenance=provenance,
        ),
        ExplanationFact(
            role=FactRole.PROPERTY,
            statement=f"violated property {violated_property}",
            path="violated_property",
            value=violated_property,
            replay_verified=True,
            provenance=provenance,
        ),
        ExplanationFact(
            role=FactRole.FIRST_DIVERGENCE,
            statement=divergence.detail,
            path=divergence.path,
            value=divergence.to_dict(),
            replay_verified=True,
            provenance=provenance,
        ),
    ]
    for item in decoded:
        facts.append(
            ExplanationFact(
                role=FactRole.DECODED_VALUE,
                statement=f"decoded {item.role} {item.name}={item.value!r}",
                path=item.path or item.name,
                value=item.to_dict(),
                replay_verified=True,
                provenance=provenance,
            )
        )
    for delta in deltas:
        if delta.equal:
            continue
        facts.append(
            ExplanationFact(
                role=FactRole.EXPECTED_ACTUAL,
                statement=(
                    f"delta at {delta.path}: expected={delta.expected!r} "
                    f"actual={delta.actual!r}"
                ),
                path=delta.path,
                value=delta.to_dict(),
                replay_verified=True,
                provenance=provenance,
            )
        )
    for link in causal:
        facts.append(
            ExplanationFact(
                role=FactRole.CAUSAL_LINK,
                statement=f"causal step {link.step}: {link.label}",
                path=link.path,
                value=link.to_dict(),
                replay_verified=True,
                provenance=provenance,
            )
        )
    for assumption in assumptions:
        facts.append(
            ExplanationFact(
                role=FactRole.ASSUMPTION,
                statement=f"assumption {assumption}",
                path=f"assumptions.{assumption}",
                value=assumption,
                replay_verified=True,
                provenance=provenance,
            )
        )
    for key in sorted(bounds, key=str):
        facts.append(
            ExplanationFact(
                role=FactRole.BOUND,
                statement=f"bound {key}={bounds[key]!r}",
                path=f"bounds.{key}",
                value={key: bounds[key]},
                replay_verified=True,
                provenance=provenance,
            )
        )
    if source_span.span_ids or source_span.ast_scope_ids or source_span.source_ref_ids:
        facts.append(
            ExplanationFact(
                role=FactRole.SOURCE_SPAN,
                statement="source/AST spans bound to first divergence",
                path="source_span",
                value=source_span.to_dict(),
                replay_verified=True,
                provenance=provenance,
            )
        )
    for hole in holes:
        facts.append(
            ExplanationFact(
                role=FactRole.PROOF_HOLE,
                statement=f"affected proof hole {hole.hole_id}",
                path=f"proof_holes.{hole.hole_id}",
                value=hole.to_dict(),
                replay_verified=True,
                provenance=provenance,
            )
        )
    return facts


# ---------------------------------------------------------------------------
# Public explainer
# ---------------------------------------------------------------------------


class CounterexampleExplainer:
    """Deterministic CounterexampleExplanation@1 producer.

    Always projects through the public counterexample boundary before decoding
    so redaction holds for every fact, span, and hypothesis.
    """

    interface: Final = COUNTEREXAMPLE_EXPLANATION_INTERFACE
    algorithm: Final = ALGORITHM_NAME
    algorithm_version: Final = ALGORITHM_VERSION

    def explain(
        self,
        witness: Mapping[str, Any] | Any,
        *,
        expected: Mapping[str, Any] | None = None,
        proof_holes: Sequence[Mapping[str, Any] | Any] | None = None,
        replay_receipt: Mapping[str, Any] | Any | None = None,
        replay_verified: bool | None = None,
        violated_property: str = "",
        assumption_ids: Sequence[str] | None = None,
        finite_bounds: Mapping[str, Any] | None = None,
    ) -> CounterexampleExplanation:
        if witness is None:
            raise ExplanationError("witness is required")

        view = _envelope_view(witness)
        view.pop("raw", None)

        kind = _extract_kind_from_view(view)
        payload = _payload_of(view)
        source_map = _source_map_of(view)
        source_span = SourceSpanRef.from_source_map(source_map)
        property_id = (
            _text(violated_property, "violated_property", optional=True, maximum=256)
            or _extract_property(view)
        )
        assumptions = (
            _string_tuple(assumption_ids, "assumption_ids")
            if assumption_ids is not None
            else _extract_assumptions(view)
        )
        bounds = (
            _strip_private(_mapping(finite_bounds, "finite_bounds"))
            if finite_bounds is not None
            else _extract_bounds(view)
        )
        expected_view = _strip_private(dict(expected)) if expected else None

        decoded = _decode_values(kind, payload)
        deltas = _compute_deltas(kind, payload, expected_view)
        divergence = _first_divergence(
            kind,
            payload,
            source_span=source_span,
            deltas=deltas,
            violated_property=property_id,
        )
        causal = _causal_chain(kind, payload, divergence, source_span)
        holes = _select_affected_holes(
            proof_holes,
            source_span=source_span,
            violated_property=property_id,
        )
        unsupported = _unsupported_mapping_notes(source_span, source_map)
        verified, receipt_id = _resolve_replay_verification(
            replay_receipt=replay_receipt,
            replay_verified=replay_verified,
        )
        cited = _build_cited_facts(
            replay_verified=verified,
            replay_receipt_id=receipt_id,
            decoded=decoded,
            deltas=deltas,
            divergence=divergence,
            causal=causal,
            assumptions=assumptions,
            bounds=bounds,
            source_span=source_span,
            holes=holes,
            violated_property=property_id,
        )
        fact_ids = [fact.fact_id for fact in cited]
        hole_ids = [hole.hole_id for hole in holes]
        hypotheses = _build_hypotheses(
            _repair_classes_of(view, kind),
            related_fact_ids=fact_ids[:8],
            related_hole_ids=hole_ids,
            divergence=divergence,
        )

        summary_parts = [
            f"kind={kind}",
            f"property={property_id}",
            f"divergence={divergence.kind.value if isinstance(divergence.kind, DivergenceKind) else divergence.kind}",
            f"path={divergence.path}" if divergence.path else "path=<none>",
            f"replay_verified={verified}",
        ]
        if unsupported:
            summary_parts.append("unsupported_mappings=" + ",".join(unsupported))

        return CounterexampleExplanation(
            counterexample_id=_extract_counterexample_id(view),
            violated_property=property_id,
            witness_kind=kind,
            first_divergence=divergence,
            decoded_values=tuple(decoded),
            deltas=tuple(deltas),
            causal_chain=tuple(causal),
            assumptions=assumptions,
            bounds=bounds,
            source_spans=(source_span,) if (
                source_span.span_ids
                or source_span.source_ref_ids
                or source_span.ast_scope_ids
                or source_span.tree_ids
                or source_span.mapping_status
                is not MappingStatus.ABSENT
            ) else (),
            affected_proof_holes=tuple(holes),
            repair_hypotheses=tuple(hypotheses),
            cited_facts=tuple(cited),
            unsupported_mappings=tuple(unsupported),
            mapping_status=source_span.mapping_status,
            replay_verified=verified,
            replay_receipt_id=receipt_id,
            witness_content_id=_extract_witness_content_id(view),
            summary="; ".join(summary_parts),
            algorithm=self.algorithm,
            algorithm_version=self.algorithm_version,
        )


def explain_counterexample(
    witness: Mapping[str, Any] | Any,
    *,
    expected: Mapping[str, Any] | None = None,
    proof_holes: Sequence[Mapping[str, Any] | Any] | None = None,
    replay_receipt: Mapping[str, Any] | Any | None = None,
    replay_verified: bool | None = None,
    violated_property: str = "",
    assumption_ids: Sequence[str] | None = None,
    finite_bounds: Mapping[str, Any] | None = None,
) -> CounterexampleExplanation:
    """Module-level CounterexampleExplanation@1 entry point."""

    return CounterexampleExplainer().explain(
        witness,
        expected=expected,
        proof_holes=proof_holes,
        replay_receipt=replay_receipt,
        replay_verified=replay_verified,
        violated_property=violated_property,
        assumption_ids=assumption_ids,
        finite_bounds=finite_bounds,
    )


__all__ = [
    "ALGORITHM_NAME",
    "ALGORITHM_VERSION",
    "COUNTEREXAMPLE_EXPLANATION_INTERFACE",
    "EXPLANATION_FACT_SCHEMA",
    "EXPLANATION_SCHEMA",
    "REPAIR_HYPOTHESIS_SCHEMA",
    "AffectedProofHole",
    "CausalLink",
    "CounterexampleExplanation",
    "CounterexampleExplanationProtocol",
    "CounterexampleExplainer",
    "DecodedValue",
    "DivergenceKind",
    "ExpectedActualDelta",
    "ExplanationError",
    "ExplanationFact",
    "FactRole",
    "FirstDivergence",
    "HypothesisStatus",
    "MappingStatus",
    "RepairHypothesis",
    "SourceSpanRef",
    "explain_counterexample",
]
