"""Property-specific semantic witness equivalence (CounterexampleSemanticEquivalence@1).

This module owns **reviewed** semantic equivalence for counterexample witnesses:

* Syntactic variants of one witness deduplicate only under a property-specific
  semantic relation (never by content hash alone).
* Materially different causal paths remain distinct and are selected for
  diversity / coverage.
* Cross-provider differential comparison retains both receipts on disagreement
  and **quarantines** the conflict — disagreement cannot raise authority or be
  reported as consensus.
* Contradictory evidence is never discarded.

Interface: ``CounterexampleSemanticEquivalence@1`` (FVT-G043 / FVT-022).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final, Protocol, runtime_checkable

COUNTEREXAMPLE_SEMANTIC_EQUIVALENCE_INTERFACE: Final = (
    "CounterexampleSemanticEquivalence@1"
)
EQUIVALENCE_REPORT_SCHEMA: Final = (
    "ipfs_datasets_py/logic/counterexample-semantic-equivalence-report@1"
)
EQUIVALENCE_CLUSTER_SCHEMA: Final = (
    "ipfs_datasets_py/logic/counterexample-equivalence-cluster@1"
)
DIVERSITY_SELECTION_SCHEMA: Final = (
    "ipfs_datasets_py/logic/counterexample-diversity-selection@1"
)
DIFFERENTIAL_COMPARISON_SCHEMA: Final = (
    "ipfs_datasets_py/logic/counterexample-differential-comparison@1"
)
DISAGREEMENT_QUARANTINE_SCHEMA: Final = (
    "ipfs_datasets_py/logic/counterexample-disagreement-quarantine@1"
)
ALGORITHM_VERSION: Final = "counterexample-semantic-equivalence/1.0.0"
ALGORITHM_NAME: Final = "property_specific_semantic_witness_equivalence"

# Authority ranks used only to *lower* ceilings under disagreement.
# Higher rank is stronger; disagreement floors to the minimum input rank and
# never promotes above ADVISORY when outcomes conflict.
_AUTHORITY_RANK: Final[dict[str, int]] = {
    "none": 0,
    "advisory": 1,
    "bounded": 2,
    "satisfiability": 3,
    "model_check": 3,
    "monitor": 3,
    "authorization": 3,
    "protocol": 3,
    "hyperproperty": 3,
    "candidate": 2,
    "reconstruction": 2,
    "attestation": 4,
    "theorem": 5,
    "declarative": 2,
}

_DISAGREEMENT_AUTHORITY_CAP: Final = "advisory"

# Identity / metadata keys that never participate in the semantic payload.
_NON_SEMANTIC_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema",
        "interface",
        "counterexample_id",
        "content_id",
        "semantic_id",
        "summary",
        "authority",
        "tool",
        "tool_id",
        "tool_version",
        "provider_id",
        "provider_version",
        "oracle_id",
        "observation_policy_id",
        "policy_id",
        "private_artifacts",
        "redaction",
        "redacted",
        "minimized",
        "truncated",
        "contains_private_material",
        "contains_raw_prover_output",
        "contains_source",
        "envelope_version",
        "boundary",
        "repair_classes",
        "bindings",  # identity bindings treated separately
        "source_map",  # location metadata, not causal payload
        "hidden_witness",
        "credential",
        "stdout",
        "stderr",
        "raw_output",
        "prover_output",
        "source_code",
        "source_text",
        "source_excerpt",
        "file_content",
        "repository_source",
    }
)

# Keys whose values contribute to the semantic / causal projection.
_SEMANTIC_PAYLOAD_KEYS: Final[frozenset[str]] = frozenset(
    {
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
        "payload",
    }
)


class EquivalenceError(ValueError):
    """Raised when an equivalence request is malformed."""


class WitnessFamily(StrEnum):
    """Witness families with dedicated semantic projections."""

    SMT_MODEL = "smt_model"
    SMT_CORE = "smt_core"
    TRACE = "trace"
    PROTOCOL_ATTACK = "protocol_attack"
    HYPERTRACE = "hypertrace"
    KERNEL = "kernel"
    GENERIC = "generic"


class EquivalenceRelationKind(StrEnum):
    """Reviewed semantic relations (hashes alone are never a relation).

    * ``reviewed_projection`` — default property-specific projection equality.
    * ``causal_path`` — equality of causal-path features only (stricter path
      diversity companion).
    * ``property_bound`` — same property + assumptions + bounds + payload.
    * ``exact_identity`` — full identity including tool (not used for
      semantic dedup of syntactic variants).
    """

    REVIEWED_PROJECTION = "reviewed_projection"
    CAUSAL_PATH = "causal_path"
    PROPERTY_BOUND = "property_bound"
    EXACT_IDENTITY = "exact_identity"


class EquivalenceVerdict(StrEnum):
    """Outcome of comparing two witnesses under a reviewed relation."""

    EQUIVALENT = "equivalent"
    DISTINCT = "distinct"
    INCOMPARABLE = "incomparable"


class DifferentialStatus(StrEnum):
    """Cross-provider differential outcome."""

    AGREEMENT = "agreement"
    DISAGREEMENT = "disagreement"
    PARTIAL = "partial"
    INCONCLUSIVE = "inconclusive"
    SINGLE_PROVIDER = "single_provider"


class ProviderOutcome(StrEnum):
    """Normalized provider observation outcome for differential compare."""

    VIOLATION = "violation"
    NO_VIOLATION = "no_violation"
    UNSAT = "unsat"
    SAT = "sat"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    UNSUPPORTED = "unsupported"


class CoverageDimension(StrEnum):
    """Dimensions used for diversity / coverage selection."""

    PROPERTY_ID = "property_id"
    CAUSAL_PATH = "causal_path"
    ASSUMPTION_SET = "assumption_set"
    FAMILY = "family"
    BOUNDS = "bounds"
    FIRST_DIVERGENCE = "first_divergence"


DEFAULT_COVERAGE_DIMENSIONS: Final[tuple[CoverageDimension, ...]] = (
    CoverageDimension.PROPERTY_ID,
    CoverageDimension.CAUSAL_PATH,
    CoverageDimension.ASSUMPTION_SET,
    CoverageDimension.FAMILY,
)


@runtime_checkable
class CounterexampleSemanticEquivalenceProtocol(Protocol):
    """CounterexampleSemanticEquivalence@1 structural contract."""

    interface: str

    def project(
        self,
        witness: Mapping[str, Any],
        *,
        relation: EquivalenceRelationKind | str = EquivalenceRelationKind.REVIEWED_PROJECTION,
        family: WitnessFamily | str | None = None,
    ) -> "SemanticProjection":
        ...

    def are_equivalent(
        self,
        left: Mapping[str, Any],
        right: Mapping[str, Any],
        *,
        relation: EquivalenceRelationKind | str = EquivalenceRelationKind.REVIEWED_PROJECTION,
    ) -> "EquivalencePairResult":
        ...

    def deduplicate(
        self,
        witnesses: Sequence[Mapping[str, Any]],
        *,
        relation: EquivalenceRelationKind | str = EquivalenceRelationKind.REVIEWED_PROJECTION,
    ) -> "EquivalenceReport":
        ...

    def select_diverse(
        self,
        witnesses: Sequence[Mapping[str, Any]],
        *,
        dimensions: Sequence[CoverageDimension | str] | None = None,
        max_select: int | None = None,
    ) -> "DiversitySelection":
        ...

    def differential_compare(
        self,
        observations: Sequence["ProviderObservation | Mapping[str, Any]"],
        *,
        witness: Mapping[str, Any] | None = None,
    ) -> "DifferentialComparison":
        ...

    def quarantine_disagreement(
        self,
        comparison: "DifferentialComparison | Mapping[str, Any]",
    ) -> "DisagreementQuarantine":
        ...


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


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
    for key in (
        "report_id",
        "cluster_id",
        "selection_id",
        "comparison_id",
        "quarantine_id",
        "receipt_id",
        "content_id",
        "pair_id",
    ):
        body.pop(key, None)
    return f"{prefix}:{_digest(body)[:32]}"


def _text(value: object, label: str, *, optional: bool = False, maximum: int = 512) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str):
        raise EquivalenceError(f"{label} must be a string")
    text = value.strip()
    if "\x00" in text:
        raise EquivalenceError(f"{label} must not contain NUL")
    if not optional and not text:
        raise EquivalenceError(f"{label} is required")
    if len(text) > maximum:
        text = text[: max(0, maximum - 1)] + "…"
    return text


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        item = value.strip()
        return (item,) if item else ()
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        return (str(value),)
    items: list[str] = []
    for raw in value:
        item = str(raw).strip()
        if item:
            items.append(item)
    return tuple(sorted(set(items)))


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        if isinstance(payload, Mapping):
            return dict(payload)
    raise EquivalenceError("expected a mapping")


def _enum(value: object, enum_cls: type[StrEnum], label: str) -> StrEnum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(str(value).strip())
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_cls)
        raise EquivalenceError(f"{label} must be one of: {allowed}") from exc


def _normalize_authority(value: object) -> str:
    if value is None or value == "":
        return "none"
    text = str(getattr(value, "value", value)).strip().lower()
    if not text:
        return "none"
    if text not in _AUTHORITY_RANK:
        # Unknown ceilings fail closed to none (never invent stronger authority).
        return "none"
    return text


def _authority_rank(value: object) -> int:
    return _AUTHORITY_RANK.get(_normalize_authority(value), 0)


def _min_authority(values: Iterable[object]) -> str:
    items = list(values)
    if not items:
        return "none"
    return min((_normalize_authority(v) for v in items), key=_authority_rank)


def _cap_authority(value: object, cap: str) -> str:
    current = _normalize_authority(value)
    cap_n = _normalize_authority(cap)
    return current if _authority_rank(current) <= _authority_rank(cap_n) else cap_n


# ---------------------------------------------------------------------------
# Family resolution and semantic projection
# ---------------------------------------------------------------------------


def _resolve_family(
    family: WitnessFamily | str | None,
    witness: Mapping[str, Any],
) -> WitnessFamily:
    if family is not None and family != "":
        return _enum(family, WitnessFamily, "family")  # type: ignore[return-value]

    kind = str(
        witness.get("kind")
        or witness.get("property_class")
        or witness.get("family")
        or ""
    ).strip().lower()
    if kind in {
        "smt_model",
        "smt-model",
        "model",
        "sat_model",
        "countermodel",
    }:
        return WitnessFamily.SMT_MODEL
    if kind in {"smt_core", "smt-core", "unsat_core", "core"}:
        return WitnessFamily.SMT_CORE
    if kind in {
        "trace",
        "tla_trace",
        "tla-trace",
        "runtime_trace",
        "state_trace",
        "event_trace",
    }:
        return WitnessFamily.TRACE
    if kind in {
        "protocol_attack",
        "protocol-attack",
        "attack",
        "protocol",
    }:
        return WitnessFamily.PROTOCOL_ATTACK
    if kind in {"hypertrace", "hyper_trace", "hyperproperty"}:
        return WitnessFamily.HYPERTRACE
    if kind in {"kernel", "kernel_failure", "sorry", "admit"}:
        return WitnessFamily.KERNEL
    # Infer from payload shape when kind is absent.
    if witness.get("assignments") is not None or witness.get("model") is not None:
        return WitnessFamily.SMT_MODEL
    if witness.get("core") is not None or witness.get("unsat_core") is not None:
        return WitnessFamily.SMT_CORE
    if witness.get("differences") is not None or witness.get("observed_fields") is not None:
        return WitnessFamily.HYPERTRACE
    if witness.get("roles") is not None or witness.get("messages") is not None:
        return WitnessFamily.PROTOCOL_ATTACK
    if witness.get("steps") is not None or witness.get("trace") is not None:
        return WitnessFamily.TRACE
    if witness.get("failure_code") is not None or witness.get("theorem_id") is not None:
        return WitnessFamily.KERNEL
    return WitnessFamily.GENERIC


def _extract_property_id(witness: Mapping[str, Any]) -> str:
    for key in ("property_id", "violated_property", "property_snapshot_id"):
        value = witness.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_assumption_ids(witness: Mapping[str, Any]) -> tuple[str, ...]:
    raw = witness.get("assumption_ids")
    if raw is None:
        raw = witness.get("assumptions")
    if isinstance(raw, Mapping):
        return _string_tuple(list(raw.keys()))
    return _string_tuple(raw)


def _extract_bounds(witness: Mapping[str, Any]) -> dict[str, Any]:
    raw = witness.get("finite_bounds")
    if raw is None:
        raw = witness.get("bounds")
    if not isinstance(raw, Mapping):
        return {}
    return dict(_json_ready(dict(raw)))


def _label_of(step: Any) -> str:
    if isinstance(step, Mapping):
        for key in ("label", "action", "event", "name", "type", "state"):
            if key in step and step[key] is not None:
                return str(step[key])
        return _canonical(step)
    return str(step)


def _smt_assignments(witness: Mapping[str, Any]) -> dict[str, Any]:
    raw = witness.get("assignments")
    if raw is None:
        raw = witness.get("model")
    if isinstance(raw, Mapping):
        return dict(_json_ready(dict(raw)))
    payload = witness.get("payload")
    if isinstance(payload, Mapping):
        nested = payload.get("assignments") or payload.get("model")
        if isinstance(nested, Mapping):
            return dict(_json_ready(dict(nested)))
    return {}


def _smt_core(witness: Mapping[str, Any]) -> list[str]:
    raw = witness.get("core")
    if raw is None:
        raw = witness.get("unsat_core")
    if raw is None:
        payload = witness.get("payload")
        if isinstance(payload, Mapping):
            raw = payload.get("core") or payload.get("unsat_core")
    if raw is None:
        return []
    if isinstance(raw, Mapping):
        return sorted(str(k) for k in raw.keys())
    if isinstance(raw, (list, tuple, set, frozenset)):
        return sorted(str(item) for item in raw)
    return [str(raw)]


def _trace_steps(witness: Mapping[str, Any]) -> list[str]:
    raw = witness.get("steps")
    if raw is None:
        raw = witness.get("trace")
    if raw is None:
        raw = witness.get("events")
    if raw is None:
        payload = witness.get("payload")
        if isinstance(payload, Mapping):
            raw = payload.get("steps") or payload.get("trace") or payload.get("events")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return []
    return [_label_of(step) for step in raw]


def _protocol_features(witness: Mapping[str, Any]) -> dict[str, Any]:
    roles = witness.get("roles")
    if roles is None:
        payload = witness.get("payload")
        if isinstance(payload, Mapping):
            roles = payload.get("roles")
    messages = witness.get("messages")
    if messages is None:
        payload = witness.get("payload")
        if isinstance(payload, Mapping):
            messages = payload.get("messages")
    steps = witness.get("steps")
    if steps is None:
        payload = witness.get("payload")
        if isinstance(payload, Mapping):
            steps = payload.get("steps")
    role_list = sorted(str(r) for r in (roles or []))
    msg_list: list[str] = []
    if isinstance(messages, Sequence) and not isinstance(messages, (str, bytes, bytearray)):
        for m in messages:
            if isinstance(m, Mapping):
                msg_list.append(str(m.get("type") or m.get("label") or m.get("name") or m))
            else:
                msg_list.append(str(m))
    step_list: list[str] = []
    if isinstance(steps, Sequence) and not isinstance(steps, (str, bytes, bytearray)):
        step_list = [_label_of(s) for s in steps]
    return {
        "messages": msg_list,
        "roles": role_list,
        "steps": step_list,
    }


def _hypertrace_features(witness: Mapping[str, Any]) -> dict[str, Any]:
    differences = witness.get("differences")
    observed = witness.get("observed_fields")
    payload = witness.get("payload")
    if differences is None and isinstance(payload, Mapping):
        differences = payload.get("differences")
    if observed is None and isinstance(payload, Mapping):
        observed = payload.get("observed_fields")
    diff_fields: list[str] = []
    if isinstance(differences, Sequence) and not isinstance(
        differences, (str, bytes, bytearray)
    ):
        for d in differences:
            if isinstance(d, Mapping):
                field_name = d.get("field") or d.get("name") or d.get("key")
                if field_name is not None:
                    diff_fields.append(str(field_name))
                else:
                    diff_fields.append(_canonical(d))
            else:
                diff_fields.append(str(d))
    obs = sorted(str(x) for x in (observed or []))
    return {
        "difference_fields": sorted(set(diff_fields)),
        "observed_fields": obs,
    }


def _kernel_features(witness: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": str(witness.get("artifact_id") or ""),
        "failure_code": str(witness.get("failure_code") or "").lower(),
        "theorem_id": str(witness.get("theorem_id") or ""),
    }


def _generic_payload(witness: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in _SEMANTIC_PAYLOAD_KEYS:
        if key in witness and key not in _NON_SEMANTIC_KEYS:
            payload[key] = _json_ready(witness[key])
    nested = witness.get("payload")
    if isinstance(nested, Mapping):
        for key, value in nested.items():
            if key not in _NON_SEMANTIC_KEYS and key not in payload:
                payload[str(key)] = _json_ready(value)
    return payload


def _causal_features(
    family: WitnessFamily,
    witness: Mapping[str, Any],
) -> dict[str, Any]:
    if family is WitnessFamily.SMT_MODEL:
        return {"assignments": _smt_assignments(witness)}
    if family is WitnessFamily.SMT_CORE:
        return {"core": _smt_core(witness)}
    if family is WitnessFamily.TRACE:
        steps = _trace_steps(witness)
        return {
            "first_divergence": next(
                (s for s in steps if s not in {"init", "start", "begin"}),
                steps[0] if steps else "",
            ),
            "steps": steps,
        }
    if family is WitnessFamily.PROTOCOL_ATTACK:
        return _protocol_features(witness)
    if family is WitnessFamily.HYPERTRACE:
        return _hypertrace_features(witness)
    if family is WitnessFamily.KERNEL:
        return _kernel_features(witness)
    return _generic_payload(witness)


@dataclass(frozen=True, slots=True)
class SemanticProjection:
    """Reviewed, property-specific semantic projection of a witness.

    This is the **only** identity used for semantic equivalence.  Bare
    ``content_id`` / byte hashes of the raw envelope are intentionally
    excluded so syntactic variants can collapse and distinct causal paths
    cannot be forced together by a coincidental hash collision strategy.
    """

    family: WitnessFamily | str
    property_id: str
    assumption_ids: tuple[str, ...]
    bounds: Mapping[str, Any]
    causal_features: Mapping[str, Any]
    relation: EquivalenceRelationKind | str = EquivalenceRelationKind.REVIEWED_PROJECTION
    relation_reviewed: bool = True
    uses_content_hash_alone: bool = False
    projection_digest: str = ""
    causal_path_digest: str = ""

    def __post_init__(self) -> None:
        family = (
            self.family
            if isinstance(self.family, WitnessFamily)
            else WitnessFamily(str(self.family))
        )
        relation = (
            self.relation
            if isinstance(self.relation, EquivalenceRelationKind)
            else EquivalenceRelationKind(str(self.relation))
        )
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "relation", relation)
        object.__setattr__(
            self,
            "assumption_ids",
            tuple(str(a) for a in self.assumption_ids if str(a)),
        )
        object.__setattr__(
            self, "bounds", MappingProxyType(dict(_json_ready(dict(self.bounds or {}))))
        )
        object.__setattr__(
            self,
            "causal_features",
            MappingProxyType(dict(_json_ready(dict(self.causal_features or {})))),
        )
        object.__setattr__(self, "relation_reviewed", True)
        object.__setattr__(self, "uses_content_hash_alone", False)
        if not self.causal_path_digest:
            object.__setattr__(
                self,
                "causal_path_digest",
                _digest(
                    {
                        "causal_features": dict(self.causal_features),
                        "family": family.value,
                    }
                ),
            )
        if not self.projection_digest:
            object.__setattr__(
                self,
                "projection_digest",
                _digest(self._core_for_relation(relation)),
            )

    def _core_for_relation(
        self, relation: EquivalenceRelationKind | str
    ) -> dict[str, Any]:
        rel = (
            relation
            if isinstance(relation, EquivalenceRelationKind)
            else EquivalenceRelationKind(str(relation))
        )
        family = (
            self.family.value if isinstance(self.family, WitnessFamily) else str(self.family)
        )
        if rel is EquivalenceRelationKind.CAUSAL_PATH:
            return {
                "causal_features": dict(self.causal_features),
                "family": family,
                "property_id": self.property_id,
                "relation": rel.value,
            }
        if rel is EquivalenceRelationKind.PROPERTY_BOUND:
            return {
                "assumption_ids": list(self.assumption_ids),
                "bounds": dict(self.bounds),
                "causal_features": dict(self.causal_features),
                "family": family,
                "property_id": self.property_id,
                "relation": rel.value,
            }
        if rel is EquivalenceRelationKind.EXACT_IDENTITY:
            # Exact identity is still a reviewed structure — not a raw hash —
            # but includes all projection dimensions.
            return {
                "assumption_ids": list(self.assumption_ids),
                "bounds": dict(self.bounds),
                "causal_features": dict(self.causal_features),
                "family": family,
                "property_id": self.property_id,
                "relation": rel.value,
            }
        # reviewed_projection (default): property + assumptions + bounds + causal
        return {
            "assumption_ids": list(self.assumption_ids),
            "bounds": dict(self.bounds),
            "causal_features": dict(self.causal_features),
            "family": family,
            "property_id": self.property_id,
            "relation": EquivalenceRelationKind.REVIEWED_PROJECTION.value,
        }

    def semantic_key(
        self,
        relation: EquivalenceRelationKind | str | None = None,
    ) -> str:
        rel = relation if relation is not None else self.relation
        return "sem:" + _digest(self._core_for_relation(rel))[:40]

    def to_dict(self) -> dict[str, Any]:
        family = (
            self.family.value if isinstance(self.family, WitnessFamily) else str(self.family)
        )
        relation = (
            self.relation.value
            if isinstance(self.relation, EquivalenceRelationKind)
            else str(self.relation)
        )
        return {
            "assumption_ids": list(self.assumption_ids),
            "bounds": dict(self.bounds),
            "causal_features": dict(self.causal_features),
            "causal_path_digest": self.causal_path_digest,
            "family": family,
            "projection_digest": self.projection_digest,
            "property_id": self.property_id,
            "relation": relation,
            "relation_reviewed": True,
            "semantic_key": self.semantic_key(),
            "uses_content_hash_alone": False,
        }


def project_witness(
    witness: Mapping[str, Any],
    *,
    relation: EquivalenceRelationKind | str = EquivalenceRelationKind.REVIEWED_PROJECTION,
    family: WitnessFamily | str | None = None,
) -> SemanticProjection:
    """Build a reviewed semantic projection for ``witness``."""

    if not isinstance(witness, Mapping):
        raise EquivalenceError("witness must be a mapping")
    rel = _enum(relation, EquivalenceRelationKind, "relation")
    fam = _resolve_family(family, witness)
    return SemanticProjection(
        family=fam,
        property_id=_extract_property_id(witness),
        assumption_ids=_extract_assumption_ids(witness),
        bounds=_extract_bounds(witness),
        causal_features=_causal_features(fam, witness),
        relation=rel,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Pair / cluster / report results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EquivalencePairResult:
    """Result of comparing two witnesses under a reviewed relation."""

    verdict: EquivalenceVerdict | str
    relation: EquivalenceRelationKind | str
    left_semantic_key: str
    right_semantic_key: str
    left_projection: Mapping[str, Any]
    right_projection: Mapping[str, Any]
    used_content_hash_alone: bool = False
    detail: str = ""
    pair_id: str = ""
    schema: str = EQUIVALENCE_REPORT_SCHEMA
    interface: str = COUNTEREXAMPLE_SEMANTIC_EQUIVALENCE_INTERFACE

    def __post_init__(self) -> None:
        verdict = (
            self.verdict
            if isinstance(self.verdict, EquivalenceVerdict)
            else EquivalenceVerdict(str(self.verdict))
        )
        relation = (
            self.relation
            if isinstance(self.relation, EquivalenceRelationKind)
            else EquivalenceRelationKind(str(self.relation))
        )
        object.__setattr__(self, "verdict", verdict)
        object.__setattr__(self, "relation", relation)
        object.__setattr__(
            self, "left_projection", MappingProxyType(dict(self.left_projection or {}))
        )
        object.__setattr__(
            self, "right_projection", MappingProxyType(dict(self.right_projection or {}))
        )
        object.__setattr__(self, "used_content_hash_alone", False)
        if not self.pair_id:
            object.__setattr__(
                self, "pair_id", _content_id("eq-pair", self.to_dict(identity=False))
            )

    @property
    def equivalent(self) -> bool:
        return self.verdict is EquivalenceVerdict.EQUIVALENT or (
            isinstance(self.verdict, str)
            and self.verdict == EquivalenceVerdict.EQUIVALENT.value
        )

    def to_dict(self, *, identity: bool = True) -> dict[str, Any]:
        verdict = (
            self.verdict.value
            if isinstance(self.verdict, EquivalenceVerdict)
            else str(self.verdict)
        )
        relation = (
            self.relation.value
            if isinstance(self.relation, EquivalenceRelationKind)
            else str(self.relation)
        )
        payload = {
            "detail": self.detail,
            "equivalent": self.equivalent,
            "interface": self.interface,
            "left_projection": dict(self.left_projection),
            "left_semantic_key": self.left_semantic_key,
            "relation": relation,
            "right_projection": dict(self.right_projection),
            "right_semantic_key": self.right_semantic_key,
            "schema": self.schema,
            "used_content_hash_alone": False,
            "verdict": verdict,
        }
        if identity:
            payload["pair_id"] = self.pair_id
        return payload


@dataclass(frozen=True, slots=True)
class EquivalenceCluster:
    """One semantic equivalence class of syntactic variants."""

    semantic_key: str
    representative_index: int
    member_indices: tuple[int, ...]
    member_ids: tuple[str, ...]
    projection: Mapping[str, Any]
    relation: EquivalenceRelationKind | str
    cluster_id: str = ""
    schema: str = EQUIVALENCE_CLUSTER_SCHEMA
    interface: str = COUNTEREXAMPLE_SEMANTIC_EQUIVALENCE_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "member_indices", tuple(int(i) for i in self.member_indices)
        )
        object.__setattr__(
            self, "member_ids", tuple(str(i) for i in self.member_ids if str(i))
        )
        object.__setattr__(
            self, "projection", MappingProxyType(dict(self.projection or {}))
        )
        if not self.cluster_id:
            object.__setattr__(
                self, "cluster_id", _content_id("eq-cluster", self.to_dict(identity=False))
            )

    def to_dict(self, *, identity: bool = True) -> dict[str, Any]:
        relation = (
            self.relation.value
            if isinstance(self.relation, EquivalenceRelationKind)
            else str(self.relation)
        )
        payload = {
            "interface": self.interface,
            "member_ids": list(self.member_ids),
            "member_indices": list(self.member_indices),
            "projection": dict(self.projection),
            "relation": relation,
            "representative_index": int(self.representative_index),
            "schema": self.schema,
            "semantic_key": self.semantic_key,
            "size": len(self.member_indices),
        }
        if identity:
            payload["cluster_id"] = self.cluster_id
        return payload


@dataclass(frozen=True, slots=True)
class EquivalenceReport:
    """Deduplication report for a multiset of witnesses."""

    clusters: tuple[EquivalenceCluster, ...]
    relation: EquivalenceRelationKind | str
    input_count: int
    unique_count: int
    duplicate_count: int
    algorithm: str = ALGORITHM_NAME
    algorithm_version: str = ALGORITHM_VERSION
    used_content_hash_alone: bool = False
    report_id: str = ""
    schema: str = EQUIVALENCE_REPORT_SCHEMA
    interface: str = COUNTEREXAMPLE_SEMANTIC_EQUIVALENCE_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "clusters", tuple(self.clusters))
        object.__setattr__(self, "used_content_hash_alone", False)
        if not self.report_id:
            object.__setattr__(
                self, "report_id", _content_id("eq-report", self.to_dict(identity=False))
            )

    @property
    def representatives(self) -> tuple[int, ...]:
        return tuple(cluster.representative_index for cluster in self.clusters)

    def to_dict(self, *, identity: bool = True) -> dict[str, Any]:
        relation = (
            self.relation.value
            if isinstance(self.relation, EquivalenceRelationKind)
            else str(self.relation)
        )
        payload = {
            "algorithm": self.algorithm,
            "algorithm_version": self.algorithm_version,
            "clusters": [c.to_dict() for c in self.clusters],
            "duplicate_count": int(self.duplicate_count),
            "input_count": int(self.input_count),
            "interface": self.interface,
            "relation": relation,
            "representatives": list(self.representatives),
            "schema": self.schema,
            "unique_count": int(self.unique_count),
            "used_content_hash_alone": False,
        }
        if identity:
            payload["report_id"] = self.report_id
        return payload


# ---------------------------------------------------------------------------
# Diversity / coverage selection
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DiversitySelection:
    """Diverse representatives covering distinct causal / property dimensions."""

    selected_indices: tuple[int, ...]
    selected_ids: tuple[str, ...]
    coverage_keys: tuple[str, ...]
    dimensions: tuple[str, ...]
    input_count: int
    selected_count: int
    algorithm: str = ALGORITHM_NAME
    algorithm_version: str = ALGORITHM_VERSION
    selection_id: str = ""
    schema: str = DIVERSITY_SELECTION_SCHEMA
    interface: str = COUNTEREXAMPLE_SEMANTIC_EQUIVALENCE_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "selected_indices", tuple(int(i) for i in self.selected_indices)
        )
        object.__setattr__(
            self, "selected_ids", tuple(str(i) for i in self.selected_ids if str(i) or i == "")
        )
        object.__setattr__(self, "coverage_keys", tuple(self.coverage_keys))
        object.__setattr__(self, "dimensions", tuple(str(d) for d in self.dimensions))
        if not self.selection_id:
            object.__setattr__(
                self,
                "selection_id",
                _content_id("eq-diversity", self.to_dict(identity=False)),
            )

    def to_dict(self, *, identity: bool = True) -> dict[str, Any]:
        payload = {
            "algorithm": self.algorithm,
            "algorithm_version": self.algorithm_version,
            "coverage_keys": list(self.coverage_keys),
            "dimensions": list(self.dimensions),
            "input_count": int(self.input_count),
            "interface": self.interface,
            "schema": self.schema,
            "selected_count": int(self.selected_count),
            "selected_ids": list(self.selected_ids),
            "selected_indices": list(self.selected_indices),
        }
        if identity:
            payload["selection_id"] = self.selection_id
        return payload


def _coverage_key(
    projection: SemanticProjection,
    dimensions: Sequence[CoverageDimension],
) -> str:
    parts: dict[str, Any] = {}
    for dim in dimensions:
        if dim is CoverageDimension.PROPERTY_ID:
            parts["property_id"] = projection.property_id
        elif dim is CoverageDimension.CAUSAL_PATH:
            parts["causal_path"] = projection.causal_path_digest
        elif dim is CoverageDimension.ASSUMPTION_SET:
            parts["assumption_set"] = list(projection.assumption_ids)
        elif dim is CoverageDimension.FAMILY:
            family = (
                projection.family.value
                if isinstance(projection.family, WitnessFamily)
                else str(projection.family)
            )
            parts["family"] = family
        elif dim is CoverageDimension.BOUNDS:
            parts["bounds"] = dict(projection.bounds)
        elif dim is CoverageDimension.FIRST_DIVERGENCE:
            features = dict(projection.causal_features)
            parts["first_divergence"] = features.get(
                "first_divergence",
                features.get("difference_fields", features.get("steps", "")),
            )
    return "cov:" + _digest(parts)[:40]


# ---------------------------------------------------------------------------
# Cross-provider differential + quarantine
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProviderObservation:
    """One provider's observation of a (semantic) witness."""

    provider_id: str
    outcome: ProviderOutcome | str
    receipt_id: str = ""
    authority: str = "none"
    tool_version: str = ""
    semantic_key: str = ""
    detail: str = ""
    witness_content_id: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider_id", _text(self.provider_id, "provider_id", maximum=256)
        )
        outcome = (
            self.outcome
            if isinstance(self.outcome, ProviderOutcome)
            else ProviderOutcome(str(self.outcome).strip().lower())
        )
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(
            self, "receipt_id", _text(self.receipt_id, "receipt_id", optional=True)
        )
        object.__setattr__(self, "authority", _normalize_authority(self.authority))
        object.__setattr__(
            self,
            "tool_version",
            _text(self.tool_version, "tool_version", optional=True, maximum=128),
        )
        object.__setattr__(
            self,
            "semantic_key",
            _text(self.semantic_key, "semantic_key", optional=True, maximum=256),
        )
        object.__setattr__(
            self, "detail", _text(self.detail, "detail", optional=True, maximum=1024)
        )
        object.__setattr__(
            self,
            "witness_content_id",
            _text(self.witness_content_id, "witness_content_id", optional=True, maximum=256),
        )
        object.__setattr__(
            self, "extra", MappingProxyType(dict(_json_ready(dict(self.extra or {}))))
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | "ProviderObservation") -> "ProviderObservation":
        if isinstance(value, ProviderObservation):
            return value
        if not isinstance(value, Mapping):
            raise EquivalenceError("provider observation must be a mapping")
        return cls(
            provider_id=str(value.get("provider_id") or value.get("tool_id") or ""),
            outcome=str(value.get("outcome") or value.get("status") or "unknown"),
            receipt_id=str(value.get("receipt_id") or value.get("result_id") or ""),
            authority=str(value.get("authority") or "none"),
            tool_version=str(value.get("tool_version") or value.get("provider_version") or ""),
            semantic_key=str(value.get("semantic_key") or ""),
            detail=str(value.get("detail") or value.get("summary") or ""),
            witness_content_id=str(
                value.get("witness_content_id") or value.get("content_id") or ""
            ),
            extra={
                k: v
                for k, v in value.items()
                if k
                not in {
                    "provider_id",
                    "tool_id",
                    "outcome",
                    "status",
                    "receipt_id",
                    "result_id",
                    "authority",
                    "tool_version",
                    "provider_version",
                    "semantic_key",
                    "detail",
                    "summary",
                    "witness_content_id",
                    "content_id",
                }
            },
        )

    def to_dict(self) -> dict[str, Any]:
        outcome = (
            self.outcome.value
            if isinstance(self.outcome, ProviderOutcome)
            else str(self.outcome)
        )
        payload = {
            "authority": self.authority,
            "detail": self.detail,
            "outcome": outcome,
            "provider_id": self.provider_id,
            "receipt_id": self.receipt_id,
            "semantic_key": self.semantic_key,
            "tool_version": self.tool_version,
            "witness_content_id": self.witness_content_id,
        }
        if self.extra:
            payload["extra"] = dict(self.extra)
        return payload


def _normalize_outcome(outcome: ProviderOutcome | str) -> ProviderOutcome:
    if isinstance(outcome, ProviderOutcome):
        return outcome
    text = str(outcome).strip().lower()
    aliases = {
        "reproduced": ProviderOutcome.VIOLATION,
        "violation_reproduced": ProviderOutcome.VIOLATION,
        "counterexample": ProviderOutcome.VIOLATION,
        "sat": ProviderOutcome.SAT,
        "satisfiable": ProviderOutcome.SAT,
        "unsat": ProviderOutcome.UNSAT,
        "unsatisfiable": ProviderOutcome.UNSAT,
        "no_violation": ProviderOutcome.NO_VIOLATION,
        "not_reproduced": ProviderOutcome.NO_VIOLATION,
        "valid": ProviderOutcome.NO_VIOLATION,
        "timeout": ProviderOutcome.TIMEOUT,
        "unavailable": ProviderOutcome.UNAVAILABLE,
        "error": ProviderOutcome.ERROR,
        "unsupported": ProviderOutcome.UNSUPPORTED,
        "unknown": ProviderOutcome.UNKNOWN,
        "violation": ProviderOutcome.VIOLATION,
    }
    if text in aliases:
        return aliases[text]
    return ProviderOutcome(text)


def _outcome_polarity(outcome: ProviderOutcome | str) -> str:
    """Collapse outcomes into polarity classes for agreement detection.

    * ``positive`` — reports a violation / sat counterexample
    * ``negative`` — reports no violation / unsat
    * ``neutral`` — timeout / unavailable / unknown / error (not disagreement
      with a definitive peer; yields partial/inconclusive)
    """

    out = _normalize_outcome(outcome)
    if out in {ProviderOutcome.VIOLATION, ProviderOutcome.SAT}:
        return "positive"
    if out in {ProviderOutcome.NO_VIOLATION, ProviderOutcome.UNSAT}:
        return "negative"
    return "neutral"


@dataclass(frozen=True, slots=True)
class DifferentialComparison:
    """Cross-provider differential comparison of observations."""

    observations: tuple[ProviderObservation, ...]
    status: DifferentialStatus | str
    agreed: bool
    is_consensus: bool
    consensus_claimed: bool
    authority_ceiling: str
    retained_receipt_ids: tuple[str, ...]
    disagreeing_provider_ids: tuple[str, ...]
    polarities: Mapping[str, str]
    witness_semantic_key: str = ""
    comparison_id: str = ""
    algorithm: str = ALGORITHM_NAME
    algorithm_version: str = ALGORITHM_VERSION
    schema: str = DIFFERENTIAL_COMPARISON_SCHEMA
    interface: str = COUNTEREXAMPLE_SEMANTIC_EQUIVALENCE_INTERFACE
    detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "observations", tuple(self.observations))
        status = (
            self.status
            if isinstance(self.status, DifferentialStatus)
            else DifferentialStatus(str(self.status))
        )
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "agreed", bool(self.agreed))
        # Hard invariants: disagreement never reports consensus.
        if status is DifferentialStatus.DISAGREEMENT:
            object.__setattr__(self, "is_consensus", False)
            object.__setattr__(self, "consensus_claimed", False)
        else:
            object.__setattr__(self, "is_consensus", bool(self.is_consensus))
            object.__setattr__(self, "consensus_claimed", bool(self.consensus_claimed))
        object.__setattr__(
            self, "authority_ceiling", _normalize_authority(self.authority_ceiling)
        )
        object.__setattr__(
            self,
            "retained_receipt_ids",
            tuple(str(r) for r in self.retained_receipt_ids if str(r)),
        )
        object.__setattr__(
            self,
            "disagreeing_provider_ids",
            tuple(str(p) for p in self.disagreeing_provider_ids if str(p)),
        )
        object.__setattr__(
            self, "polarities", MappingProxyType(dict(self.polarities or {}))
        )
        if not self.comparison_id:
            object.__setattr__(
                self,
                "comparison_id",
                _content_id("eq-diff", self.to_dict(identity=False)),
            )

    @property
    def requires_quarantine(self) -> bool:
        return self.status is DifferentialStatus.DISAGREEMENT or (
            isinstance(self.status, str)
            and self.status == DifferentialStatus.DISAGREEMENT.value
        )

    def to_dict(self, *, identity: bool = True) -> dict[str, Any]:
        status = (
            self.status.value
            if isinstance(self.status, DifferentialStatus)
            else str(self.status)
        )
        payload = {
            "agreed": bool(self.agreed),
            "algorithm": self.algorithm,
            "algorithm_version": self.algorithm_version,
            "authority_ceiling": self.authority_ceiling,
            "consensus_claimed": bool(self.consensus_claimed),
            "detail": self.detail,
            "disagreeing_provider_ids": list(self.disagreeing_provider_ids),
            "interface": self.interface,
            "is_consensus": bool(self.is_consensus),
            "observations": [obs.to_dict() for obs in self.observations],
            "polarities": dict(self.polarities),
            "requires_quarantine": self.requires_quarantine,
            "retained_receipt_ids": list(self.retained_receipt_ids),
            "schema": self.schema,
            "status": status,
            "witness_semantic_key": self.witness_semantic_key,
        }
        if identity:
            payload["comparison_id"] = self.comparison_id
        return payload


@dataclass(frozen=True, slots=True)
class DisagreementQuarantine:
    """Explicit quarantine of cross-provider disagreement.

    Both (all) receipts are retained.  Authority cannot be raised.  Consensus
    is never claimed.  Contradictory evidence is never discarded.
    """

    comparison_id: str
    retained_receipt_ids: tuple[str, ...]
    provider_ids: tuple[str, ...]
    authority_ceiling: str
    prior_authority_ceiling: str
    authority_raised: bool
    is_consensus: bool
    consensus_claimed: bool
    discarded_evidence: bool
    status: str = "quarantined"
    reason: str = "cross_provider_disagreement"
    observations: tuple[Mapping[str, Any], ...] = ()
    quarantine_id: str = ""
    algorithm: str = ALGORITHM_NAME
    algorithm_version: str = ALGORITHM_VERSION
    schema: str = DISAGREEMENT_QUARANTINE_SCHEMA
    interface: str = COUNTEREXAMPLE_SEMANTIC_EQUIVALENCE_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "retained_receipt_ids",
            tuple(str(r) for r in self.retained_receipt_ids if str(r)),
        )
        object.__setattr__(
            self, "provider_ids", tuple(str(p) for p in self.provider_ids if str(p))
        )
        # Invariants enforced at construction time.
        object.__setattr__(self, "authority_raised", False)
        object.__setattr__(self, "is_consensus", False)
        object.__setattr__(self, "consensus_claimed", False)
        object.__setattr__(self, "discarded_evidence", False)
        object.__setattr__(
            self, "authority_ceiling", _normalize_authority(self.authority_ceiling)
        )
        object.__setattr__(
            self,
            "prior_authority_ceiling",
            _normalize_authority(self.prior_authority_ceiling),
        )
        # Ceiling must not exceed prior or the disagreement cap.
        capped = _cap_authority(
            _min_authority([self.authority_ceiling, self.prior_authority_ceiling]),
            _DISAGREEMENT_AUTHORITY_CAP,
        )
        object.__setattr__(self, "authority_ceiling", capped)
        object.__setattr__(
            self,
            "observations",
            tuple(MappingProxyType(dict(o)) for o in self.observations),
        )
        object.__setattr__(self, "status", "quarantined")
        if not self.quarantine_id:
            object.__setattr__(
                self,
                "quarantine_id",
                _content_id("eq-quarantine", self.to_dict(identity=False)),
            )

    def to_dict(self, *, identity: bool = True) -> dict[str, Any]:
        payload = {
            "algorithm": self.algorithm,
            "algorithm_version": self.algorithm_version,
            "authority_ceiling": self.authority_ceiling,
            "authority_raised": False,
            "comparison_id": self.comparison_id,
            "consensus_claimed": False,
            "discarded_evidence": False,
            "interface": self.interface,
            "is_consensus": False,
            "observations": [dict(o) for o in self.observations],
            "prior_authority_ceiling": self.prior_authority_ceiling,
            "provider_ids": list(self.provider_ids),
            "reason": self.reason,
            "retained_receipt_ids": list(self.retained_receipt_ids),
            "schema": self.schema,
            "status": self.status,
        }
        if identity:
            payload["quarantine_id"] = self.quarantine_id
        return payload


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class CounterexampleSemanticEquivalence:
    """Property-specific semantic equivalence, diversity, and quarantine.

    Interface: ``CounterexampleSemanticEquivalence@1``.
    """

    interface: Final = COUNTEREXAMPLE_SEMANTIC_EQUIVALENCE_INTERFACE
    algorithm: Final = ALGORITHM_NAME
    algorithm_version: Final = ALGORITHM_VERSION

    def project(
        self,
        witness: Mapping[str, Any],
        *,
        relation: EquivalenceRelationKind | str = EquivalenceRelationKind.REVIEWED_PROJECTION,
        family: WitnessFamily | str | None = None,
    ) -> SemanticProjection:
        return project_witness(witness, relation=relation, family=family)

    def are_equivalent(
        self,
        left: Mapping[str, Any],
        right: Mapping[str, Any],
        *,
        relation: EquivalenceRelationKind | str = EquivalenceRelationKind.REVIEWED_PROJECTION,
        family: WitnessFamily | str | None = None,
    ) -> EquivalencePairResult:
        rel = _enum(relation, EquivalenceRelationKind, "relation")
        left_proj = self.project(left, relation=rel, family=family)
        right_proj = self.project(right, relation=rel, family=family)
        left_key = left_proj.semantic_key(rel)
        right_key = right_proj.semantic_key(rel)

        left_family = (
            left_proj.family.value
            if isinstance(left_proj.family, WitnessFamily)
            else str(left_proj.family)
        )
        right_family = (
            right_proj.family.value
            if isinstance(right_proj.family, WitnessFamily)
            else str(right_proj.family)
        )
        # Different witness families are incomparable under the reviewed
        # relation (check before property_id so family mismatch is explicit).
        if left_family != right_family:
            return EquivalencePairResult(
                verdict=EquivalenceVerdict.INCOMPARABLE,
                relation=rel,  # type: ignore[arg-type]
                left_semantic_key=left_key,
                right_semantic_key=right_key,
                left_projection=left_proj.to_dict(),
                right_projection=right_proj.to_dict(),
                detail="witness families differ",
            )

        if not left_proj.property_id and not right_proj.property_id:
            # Both unscoped — still comparable by causal features under the
            # reviewed relation, but note the missing property binding.
            detail = "property_id missing on both; compared causal projection only"
        elif left_proj.property_id != right_proj.property_id:
            return EquivalencePairResult(
                verdict=EquivalenceVerdict.DISTINCT,
                relation=rel,  # type: ignore[arg-type]
                left_semantic_key=left_key,
                right_semantic_key=right_key,
                left_projection=left_proj.to_dict(),
                right_projection=right_proj.to_dict(),
                detail="property_id differs",
            )
        else:
            detail = ""

        verdict = (
            EquivalenceVerdict.EQUIVALENT
            if left_key == right_key
            else EquivalenceVerdict.DISTINCT
        )
        if verdict is EquivalenceVerdict.EQUIVALENT and not detail:
            detail = "reviewed semantic projection matches"
        elif verdict is EquivalenceVerdict.DISTINCT and not detail:
            detail = "reviewed semantic projection differs"
        return EquivalencePairResult(
            verdict=verdict,
            relation=rel,  # type: ignore[arg-type]
            left_semantic_key=left_key,
            right_semantic_key=right_key,
            left_projection=left_proj.to_dict(),
            right_projection=right_proj.to_dict(),
            detail=detail,
        )

    def deduplicate(
        self,
        witnesses: Sequence[Mapping[str, Any]],
        *,
        relation: EquivalenceRelationKind | str = EquivalenceRelationKind.REVIEWED_PROJECTION,
        family: WitnessFamily | str | None = None,
    ) -> EquivalenceReport:
        if not isinstance(witnesses, Sequence) or isinstance(
            witnesses, (str, bytes, bytearray)
        ):
            raise EquivalenceError("witnesses must be a sequence of mappings")
        rel = _enum(relation, EquivalenceRelationKind, "relation")
        buckets: dict[str, list[int]] = {}
        projections: dict[str, SemanticProjection] = {}
        member_ids: dict[str, list[str]] = {}

        for index, raw in enumerate(witnesses):
            if not isinstance(raw, Mapping):
                raise EquivalenceError(f"witnesses[{index}] must be a mapping")
            projection = self.project(raw, relation=rel, family=family)
            key = projection.semantic_key(rel)
            buckets.setdefault(key, []).append(index)
            projections.setdefault(key, projection)
            wid = str(
                raw.get("counterexample_id")
                or raw.get("content_id")
                or f"index:{index}"
            )
            member_ids.setdefault(key, []).append(wid)

        # Stable order by first-seen index.
        ordered_keys = sorted(buckets.keys(), key=lambda k: buckets[k][0])
        clusters: list[EquivalenceCluster] = []
        for key in ordered_keys:
            indices = tuple(buckets[key])
            clusters.append(
                EquivalenceCluster(
                    semantic_key=key,
                    representative_index=indices[0],
                    member_indices=indices,
                    member_ids=tuple(member_ids[key]),
                    projection=projections[key].to_dict(),
                    relation=rel,  # type: ignore[arg-type]
                )
            )

        input_count = len(witnesses)
        unique_count = len(clusters)
        duplicate_count = max(0, input_count - unique_count)
        return EquivalenceReport(
            clusters=tuple(clusters),
            relation=rel,  # type: ignore[arg-type]
            input_count=input_count,
            unique_count=unique_count,
            duplicate_count=duplicate_count,
        )

    def select_diverse(
        self,
        witnesses: Sequence[Mapping[str, Any]],
        *,
        dimensions: Sequence[CoverageDimension | str] | None = None,
        max_select: int | None = None,
        family: WitnessFamily | str | None = None,
        relation: EquivalenceRelationKind | str = EquivalenceRelationKind.REVIEWED_PROJECTION,
    ) -> DiversitySelection:
        if not isinstance(witnesses, Sequence) or isinstance(
            witnesses, (str, bytes, bytearray)
        ):
            raise EquivalenceError("witnesses must be a sequence of mappings")
        if max_select is not None and int(max_select) < 0:
            raise EquivalenceError("max_select must be non-negative")

        dims: list[CoverageDimension]
        if dimensions is None:
            dims = list(DEFAULT_COVERAGE_DIMENSIONS)
        else:
            dims = [
                _enum(d, CoverageDimension, "dimensions")  # type: ignore[misc]
                for d in dimensions
            ]
            if not dims:
                dims = list(DEFAULT_COVERAGE_DIMENSIONS)

        # Prefer one representative per semantic class first so syntactic
        # variants do not inflate coverage.
        report = self.deduplicate(witnesses, relation=relation, family=family)
        candidate_indices = list(report.representatives)

        seen_coverage: dict[str, int] = {}
        selected: list[int] = []
        selected_ids: list[str] = []
        coverage_keys: list[str] = []

        for index in candidate_indices:
            if max_select is not None and len(selected) >= int(max_select):
                break
            witness = witnesses[index]
            projection = self.project(witness, relation=relation, family=family)
            cov = _coverage_key(projection, dims)
            if cov in seen_coverage:
                continue
            seen_coverage[cov] = index
            selected.append(index)
            selected_ids.append(
                str(
                    witness.get("counterexample_id")
                    or witness.get("content_id")
                    or f"index:{index}"
                )
            )
            coverage_keys.append(cov)

        return DiversitySelection(
            selected_indices=tuple(selected),
            selected_ids=tuple(selected_ids),
            coverage_keys=tuple(coverage_keys),
            dimensions=tuple(
                d.value if isinstance(d, CoverageDimension) else str(d) for d in dims
            ),
            input_count=len(witnesses),
            selected_count=len(selected),
        )

    def differential_compare(
        self,
        observations: Sequence[ProviderObservation | Mapping[str, Any]],
        *,
        witness: Mapping[str, Any] | None = None,
        family: WitnessFamily | str | None = None,
    ) -> DifferentialComparison:
        if not isinstance(observations, Sequence) or isinstance(
            observations, (str, bytes, bytearray)
        ):
            raise EquivalenceError("observations must be a sequence")
        if not observations:
            raise EquivalenceError("observations must be non-empty")

        parsed = tuple(ProviderObservation.from_mapping(item) for item in observations)
        # Require unique provider ids for a clean differential.
        provider_ids = [obs.provider_id for obs in parsed]
        if len(set(provider_ids)) != len(provider_ids):
            raise EquivalenceError("provider_id values must be unique in a differential")

        witness_key = ""
        if witness is not None:
            witness_key = self.project(witness, family=family).semantic_key()

        polarities = {
            obs.provider_id: _outcome_polarity(obs.outcome) for obs in parsed
        }
        definitive = {
            pid: pol for pid, pol in polarities.items() if pol in {"positive", "negative"}
        }
        retained = tuple(
            obs.receipt_id for obs in parsed if obs.receipt_id
        ) or tuple(f"obs:{obs.provider_id}" for obs in parsed)

        prior_authorities = [obs.authority for obs in parsed]
        prior_ceiling = _min_authority(prior_authorities) if prior_authorities else "none"

        if len(parsed) == 1:
            return DifferentialComparison(
                observations=parsed,
                status=DifferentialStatus.SINGLE_PROVIDER,
                agreed=True,
                is_consensus=False,
                consensus_claimed=False,
                authority_ceiling=prior_ceiling,
                retained_receipt_ids=retained,
                disagreeing_provider_ids=(),
                polarities=polarities,
                witness_semantic_key=witness_key,
                detail="single provider observation; consensus not claimed",
            )

        definitive_values = set(definitive.values())
        if len(definitive_values) >= 2:
            # True cross-provider contradiction: retain all receipts, no consensus.
            disagreeing = tuple(
                sorted(pid for pid, pol in definitive.items())
            )
            # Floor authority under disagreement.
            authority = _cap_authority(prior_ceiling, _DISAGREEMENT_AUTHORITY_CAP)
            return DifferentialComparison(
                observations=parsed,
                status=DifferentialStatus.DISAGREEMENT,
                agreed=False,
                is_consensus=False,
                consensus_claimed=False,
                authority_ceiling=authority,
                retained_receipt_ids=retained,
                disagreeing_provider_ids=disagreeing,
                polarities=polarities,
                witness_semantic_key=witness_key,
                detail=(
                    "cross-provider disagreement retained with all receipts; "
                    "authority not raised; consensus not claimed"
                ),
            )

        if not definitive_values:
            return DifferentialComparison(
                observations=parsed,
                status=DifferentialStatus.INCONCLUSIVE,
                agreed=False,
                is_consensus=False,
                consensus_claimed=False,
                authority_ceiling=prior_ceiling,
                retained_receipt_ids=retained,
                disagreeing_provider_ids=(),
                polarities=polarities,
                witness_semantic_key=witness_key,
                detail="no definitive provider outcomes",
            )

        # Some definitive, some neutral → partial agreement among definitive.
        if any(pol == "neutral" for pol in polarities.values()):
            return DifferentialComparison(
                observations=parsed,
                status=DifferentialStatus.PARTIAL,
                agreed=True,
                is_consensus=False,
                consensus_claimed=False,
                authority_ceiling=prior_ceiling,
                retained_receipt_ids=retained,
                disagreeing_provider_ids=(),
                polarities=polarities,
                witness_semantic_key=witness_key,
                detail=(
                    "definitive providers agree polarity; neutral providers "
                    "prevent consensus claim"
                ),
            )

        # All definitive and same polarity.
        return DifferentialComparison(
            observations=parsed,
            status=DifferentialStatus.AGREEMENT,
            agreed=True,
            is_consensus=True,
            consensus_claimed=True,
            authority_ceiling=prior_ceiling,
            retained_receipt_ids=retained,
            disagreeing_provider_ids=(),
            polarities=polarities,
            witness_semantic_key=witness_key,
            detail="providers agree on polarity under reviewed comparison",
        )

    def quarantine_disagreement(
        self,
        comparison: DifferentialComparison | Mapping[str, Any],
        *,
        requested_authority: str | None = None,
    ) -> DisagreementQuarantine:
        """Quarantine a differential disagreement.

        Always retains every receipt from the comparison.  Never raises
        authority.  Never claims consensus.  Never discards evidence.
        """

        if isinstance(comparison, Mapping):
            # Reconstruct a minimal comparison surface from a mapping.
            observations = tuple(
                ProviderObservation.from_mapping(item)
                for item in (comparison.get("observations") or ())
            )
            status = str(comparison.get("status") or DifferentialStatus.DISAGREEMENT.value)
            if status != DifferentialStatus.DISAGREEMENT.value and not comparison.get(
                "requires_quarantine"
            ):
                raise EquivalenceError(
                    "quarantine_disagreement requires a disagreement comparison"
                )
            comparison = DifferentialComparison(
                observations=observations,
                status=DifferentialStatus.DISAGREEMENT,
                agreed=False,
                is_consensus=False,
                consensus_claimed=False,
                authority_ceiling=str(comparison.get("authority_ceiling") or "none"),
                retained_receipt_ids=tuple(
                    comparison.get("retained_receipt_ids") or ()
                ),
                disagreeing_provider_ids=tuple(
                    comparison.get("disagreeing_provider_ids") or ()
                ),
                polarities=dict(comparison.get("polarities") or {}),
                witness_semantic_key=str(comparison.get("witness_semantic_key") or ""),
                comparison_id=str(comparison.get("comparison_id") or ""),
                detail=str(comparison.get("detail") or ""),
            )

        if not isinstance(comparison, DifferentialComparison):
            raise EquivalenceError("comparison must be a DifferentialComparison")
        if not comparison.requires_quarantine:
            raise EquivalenceError(
                "quarantine_disagreement requires status=disagreement"
            )

        prior = comparison.authority_ceiling
        # Even if a caller requests a higher authority, refuse to raise it.
        if requested_authority is not None:
            requested = _normalize_authority(requested_authority)
            if _authority_rank(requested) > _authority_rank(prior):
                ceiling = _cap_authority(prior, _DISAGREEMENT_AUTHORITY_CAP)
            else:
                ceiling = _cap_authority(
                    _min_authority([prior, requested]),
                    _DISAGREEMENT_AUTHORITY_CAP,
                )
        else:
            ceiling = _cap_authority(prior, _DISAGREEMENT_AUTHORITY_CAP)

        retained = comparison.retained_receipt_ids
        if not retained:
            retained = tuple(
                obs.receipt_id or f"obs:{obs.provider_id}"
                for obs in comparison.observations
            )

        return DisagreementQuarantine(
            comparison_id=comparison.comparison_id,
            retained_receipt_ids=retained,
            provider_ids=tuple(obs.provider_id for obs in comparison.observations),
            authority_ceiling=ceiling,
            prior_authority_ceiling=prior,
            authority_raised=False,
            is_consensus=False,
            consensus_claimed=False,
            discarded_evidence=False,
            observations=tuple(obs.to_dict() for obs in comparison.observations),
        )


# Module-level convenience API matching minimization/replay style.
_DEFAULT_ENGINE = CounterexampleSemanticEquivalence()


def are_semantically_equivalent(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    relation: EquivalenceRelationKind | str = EquivalenceRelationKind.REVIEWED_PROJECTION,
    family: WitnessFamily | str | None = None,
) -> EquivalencePairResult:
    return _DEFAULT_ENGINE.are_equivalent(
        left, right, relation=relation, family=family
    )


def deduplicate_witnesses(
    witnesses: Sequence[Mapping[str, Any]],
    *,
    relation: EquivalenceRelationKind | str = EquivalenceRelationKind.REVIEWED_PROJECTION,
    family: WitnessFamily | str | None = None,
) -> EquivalenceReport:
    return _DEFAULT_ENGINE.deduplicate(witnesses, relation=relation, family=family)


def select_diverse_witnesses(
    witnesses: Sequence[Mapping[str, Any]],
    *,
    dimensions: Sequence[CoverageDimension | str] | None = None,
    max_select: int | None = None,
    family: WitnessFamily | str | None = None,
) -> DiversitySelection:
    return _DEFAULT_ENGINE.select_diverse(
        witnesses,
        dimensions=dimensions,
        max_select=max_select,
        family=family,
    )


def differential_compare_providers(
    observations: Sequence[ProviderObservation | Mapping[str, Any]],
    *,
    witness: Mapping[str, Any] | None = None,
) -> DifferentialComparison:
    return _DEFAULT_ENGINE.differential_compare(observations, witness=witness)


def quarantine_provider_disagreement(
    comparison: DifferentialComparison | Mapping[str, Any],
    *,
    requested_authority: str | None = None,
) -> DisagreementQuarantine:
    return _DEFAULT_ENGINE.quarantine_disagreement(
        comparison, requested_authority=requested_authority
    )


__all__ = [
    "ALGORITHM_NAME",
    "ALGORITHM_VERSION",
    "COUNTEREXAMPLE_SEMANTIC_EQUIVALENCE_INTERFACE",
    "CoverageDimension",
    "CounterexampleSemanticEquivalence",
    "CounterexampleSemanticEquivalenceProtocol",
    "DEFAULT_COVERAGE_DIMENSIONS",
    "DIFFERENTIAL_COMPARISON_SCHEMA",
    "DISAGREEMENT_QUARANTINE_SCHEMA",
    "DIVERSITY_SELECTION_SCHEMA",
    "DifferentialComparison",
    "DifferentialStatus",
    "DisagreementQuarantine",
    "DiversitySelection",
    "EQUIVALENCE_CLUSTER_SCHEMA",
    "EQUIVALENCE_REPORT_SCHEMA",
    "EquivalenceCluster",
    "EquivalenceError",
    "EquivalencePairResult",
    "EquivalenceRelationKind",
    "EquivalenceReport",
    "EquivalenceVerdict",
    "ProviderObservation",
    "ProviderOutcome",
    "SemanticProjection",
    "WitnessFamily",
    "are_semantically_equivalent",
    "deduplicate_witnesses",
    "differential_compare_providers",
    "project_witness",
    "quarantine_provider_disagreement",
    "select_diverse_witnesses",
]
