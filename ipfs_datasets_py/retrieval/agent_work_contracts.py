"""Frozen federated retrieval request, plan, and result contracts (EAAEF-060).

These records are the shared serialization boundary for agent-work retrieval.
They are immutable, DAG-JSON compatible, content addressed, and versioned at
major ``@1``.  Repository truth, imported claims, and verified receipts stay
distinct evidence classes and source domains.  Per-engine budgets, graph/AST
depth, byte, trust, recency, and effective-date bounds are required and
positive.  Imported history is never proof authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Final, TypeVar

CONTRACT_VERSION: Final[int] = 1
SCHEMA_VERSION: Final[int] = CONTRACT_VERSION

FEDERATED_RETRIEVAL_REQUEST_INTERFACE: Final[str] = "FederatedRetrievalRequest@1"
FEDERATED_RETRIEVAL_PLAN_INTERFACE: Final[str] = "FederatedRetrievalPlan@1"
FEDERATED_RETRIEVAL_RESULT_INTERFACE: Final[str] = "FederatedRetrievalResult@1"
ENGINE_BUDGET_INTERFACE: Final[str] = "FederatedRetrievalEngineBudget@1"
PROOF_POLICY_INTERFACE: Final[str] = "FederatedRetrievalProofPolicy@1"
RECENCY_POLICY_INTERFACE: Final[str] = "FederatedRetrievalRecencyPolicy@1"
EFFECTIVE_DATES_INTERFACE: Final[str] = "FederatedRetrievalEffectiveDates@1"
RETRIEVAL_HIT_INTERFACE: Final[str] = "FederatedRetrievalHit@1"

REQUEST_SCHEMA: Final[str] = (
    "ipfs_datasets_py/retrieval/federated-retrieval-request@1"
)
PLAN_SCHEMA: Final[str] = "ipfs_datasets_py/retrieval/federated-retrieval-plan@1"
RESULT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/retrieval/federated-retrieval-result@1"
)

ABSOLUTE_MAX_TEXT_BYTES: Final[int] = 16_384
ABSOLUTE_MAX_ITEMS: Final[int] = 1_024
ABSOLUTE_MAX_BYTES: Final[int] = 16_777_216
ABSOLUTE_MAX_DEPTH: Final[int] = 64
ABSOLUTE_MAX_HITS: Final[int] = 10_000
ABSOLUTE_MAX_TIMEOUT_MS: Final[int] = 600_000
ABSOLUTE_MAX_AGE_SECONDS: Final[int] = 366 * 24 * 60 * 60

_ISO_DATE: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_UTC: Final[re.Pattern[str]] = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
)
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")

TEnum = TypeVar("TEnum", bound=Enum)


class FederatedRetrievalContractError(ValueError):
    """Malformed, incomplete, or unsafe federated retrieval contract."""


class EvidenceClass(str, Enum):
    """Kind of evidence.  Distinct from the corpus that stored it."""

    REPOSITORY_TRUTH = "repository_truth"
    IMPORTED_CLAIM = "imported_claim"
    VERIFIED_RECEIPT = "verified_receipt"


class SourceDomain(str, Enum):
    """Closed provenance corpora.  Unknown domains are rejected."""

    REPOSITORY_TRUTH = "repository_truth"
    IMPORTED_CLAIMS = "imported_claims"
    VERIFIED_RECEIPTS = "verified_receipts"
    REQUIREMENTS = "requirements"
    EXTERNAL_DOCS = "external_docs"
    LEGAL_POLICY = "legal_policy"
    MODEL_HYPOTHESES = "model_hypotheses"


class RetrievalEngine(str, Enum):
    """Existing indexes that a federated plan may compose, not duplicate."""

    AST = "ast"
    SYMBOL = "symbol"
    SEMANTIC = "semantic"
    CAPSULE = "capsule"
    BM25 = "bm25"
    VECTOR = "vector"
    SPARSE_GRAPHRAG = "sparse_graphrag"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    LEGAL = "legal"
    PROOF = "proof"
    COUNTEREXAMPLE = "counterexample"


class TrustClass(str, Enum):
    """Trust floor applied to retrieved items.  Imported text is not authority."""

    UNTRUSTED = "untrusted"
    IMPORTED_UNVERIFIED = "imported_unverified"
    LOCALLY_REVERIFIED = "locally_reverified"
    INDEPENDENTLY_ADMITTED = "independently_admitted"

    @property
    def rank(self) -> int:
        return {
            TrustClass.UNTRUSTED: 0,
            TrustClass.IMPORTED_UNVERIFIED: 1,
            TrustClass.LOCALLY_REVERIFIED: 2,
            TrustClass.INDEPENDENTLY_ADMITTED: 3,
        }[self]

    @property
    def may_satisfy_completion(self) -> bool:
        return self in {
            TrustClass.LOCALLY_REVERIFIED,
            TrustClass.INDEPENDENTLY_ADMITTED,
        }


class ProofPolicyMode(str, Enum):
    """How retrieved items may participate in proof obligations."""

    CONTEXT_ONLY = "context_only"
    REQUIRE_VERIFIED_RECEIPT = "require_verified_receipt"
    FAIL_CLOSED = "fail_closed"


EVIDENCE_CLASSES: Final[frozenset[str]] = frozenset(
    item.value for item in EvidenceClass
)
SOURCE_DOMAINS: Final[frozenset[str]] = frozenset(
    item.value for item in SourceDomain
)
RETRIEVAL_ENGINES: Final[frozenset[str]] = frozenset(
    item.value for item in RetrievalEngine
)


def _enum(value: Any, enum_type: type[TEnum], name: str) -> TEnum:
    if isinstance(value, enum_type):
        return value
    raw = getattr(value, "value", value)
    try:
        return enum_type(str(raw))
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_type)
        if enum_type is SourceDomain:
            raise FederatedRetrievalContractError(
                f"unknown domain {raw!r}; {name} must be one of: {allowed}"
            ) from exc
        raise FederatedRetrievalContractError(
            f"{name} must be one of: {allowed}"
        ) from exc


def _text(
    value: Any,
    name: str,
    *,
    required: bool = True,
    max_bytes: int = ABSOLUTE_MAX_TEXT_BYTES,
) -> str:
    if value is None:
        result = ""
    elif not isinstance(value, str):
        raise FederatedRetrievalContractError(f"{name} must be a string")
    else:
        result = value.strip()
    if required and not result:
        raise FederatedRetrievalContractError(f"{name} is required")
    if "\x00" in result:
        raise FederatedRetrievalContractError(f"{name} must not contain NUL")
    if len(result.encode("utf-8")) > max_bytes:
        raise FederatedRetrievalContractError(
            f"{name} exceeds {max_bytes} UTF-8 bytes"
        )
    return result


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise FederatedRetrievalContractError(f"{name} must be a boolean")
    return value


def _nonnegative_int(value: Any, name: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FederatedRetrievalContractError(
            f"{name} must be a non-negative integer"
        )
    if value < 0:
        raise FederatedRetrievalContractError(
            f"{name} must be a non-negative integer"
        )
    if value > maximum:
        raise FederatedRetrievalContractError(
            f"{name} exceeds maximum {maximum}"
        )
    return value


def _positive_int(value: Any, name: str, *, maximum: int) -> int:
    result = _nonnegative_int(value, name, maximum=maximum)
    if result < 1:
        raise FederatedRetrievalContractError(
            f"{name} must be a positive integer"
        )
    return result


def _texts(
    values: Any,
    name: str,
    *,
    required: bool = True,
) -> tuple[str, ...]:
    if values is None:
        items: Sequence[Any] = ()
    elif isinstance(values, str):
        items = (values,)
    elif isinstance(values, Sequence) and not isinstance(values, (bytes, bytearray)):
        items = values
    else:
        raise FederatedRetrievalContractError(
            f"{name} must be a sequence of strings"
        )
    if len(items) > ABSOLUTE_MAX_ITEMS:
        raise FederatedRetrievalContractError(
            f"{name} exceeds {ABSOLUTE_MAX_ITEMS} items"
        )
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _text(item, name)
        if text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    if required and not normalized:
        raise FederatedRetrievalContractError(f"{name} must not be empty")
    return tuple(normalized)


def _enums(
    values: Any,
    enum_type: type[TEnum],
    name: str,
) -> tuple[TEnum, ...]:
    if values is None:
        items: Sequence[Any] = ()
    elif isinstance(values, (str, enum_type)):
        items = (values,)
    elif isinstance(values, Sequence) and not isinstance(values, (bytes, bytearray)):
        items = values
    else:
        raise FederatedRetrievalContractError(
            f"{name} must be a sequence of {enum_type.__name__} values"
        )
    if len(items) > ABSOLUTE_MAX_ITEMS:
        raise FederatedRetrievalContractError(
            f"{name} exceeds {ABSOLUTE_MAX_ITEMS} items"
        )
    normalized: list[TEnum] = []
    seen: set[TEnum] = set()
    for item in items:
        parsed = _enum(item, enum_type, name)
        if parsed in seen:
            continue
        seen.add(parsed)
        normalized.append(parsed)
    if not normalized:
        raise FederatedRetrievalContractError(f"{name} must not be empty")
    return tuple(normalized)


def _iso_utc(value: Any, name: str, *, required: bool = True) -> str:
    if value is None:
        if required:
            raise FederatedRetrievalContractError(f"{name} is required")
        return ""
    text = _text(value, name, required=required)
    if not text:
        return ""
    if _ISO_DATE.fullmatch(text):
        text = f"{text}T00:00:00Z"
    if _ISO_UTC.fullmatch(text) is None:
        raise FederatedRetrievalContractError(
            f"{name} must be UTC ISO-8601 YYYY-MM-DDTHH:MM:SSZ"
        )
    return text


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FederatedRetrievalContractError(f"{name} must be an object")
    return value


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise FederatedRetrievalContractError(
            "federated retrieval contracts cannot contain floats"
        )
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _canonical_value(value.to_dict())
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise FederatedRetrievalContractError(
                "canonical object keys must be strings"
            )
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    raise FederatedRetrievalContractError(
        f"unsupported federated retrieval value: {type(value).__name__}"
    )


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def content_identity(value: Any) -> str:
    digest = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    return f"sha256:{digest}"


def _require_sha256(value: Any, name: str) -> str:
    text = _text(value, name)
    if _SHA256_RE.fullmatch(text) is None:
        raise FederatedRetrievalContractError(
            f"{name} must be sha256:<64 lowercase hex>"
        )
    return text


@dataclass(frozen=True, slots=True)
class EngineBudget:
    """Positive per-engine hit, byte, and timeout bound."""

    SCHEMA: ClassVar[str] = ENGINE_BUDGET_INTERFACE

    engine: RetrievalEngine
    max_hits: int
    max_bytes: int
    timeout_ms: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "engine", _enum(self.engine, RetrievalEngine, "engine")
        )
        object.__setattr__(
            self,
            "max_hits",
            _positive_int(self.max_hits, "max_hits", maximum=ABSOLUTE_MAX_HITS),
        )
        object.__setattr__(
            self,
            "max_bytes",
            _positive_int(self.max_bytes, "max_bytes", maximum=ABSOLUTE_MAX_BYTES),
        )
        object.__setattr__(
            self,
            "timeout_ms",
            _positive_int(
                self.timeout_ms, "timeout_ms", maximum=ABSOLUTE_MAX_TIMEOUT_MS
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine.value,
            "interface": self.SCHEMA,
            "max_bytes": self.max_bytes,
            "max_hits": self.max_hits,
            "timeout_ms": self.timeout_ms,
        }

    @classmethod
    def from_mapping(
        cls, engine: Any, payload: Mapping[str, Any] | None
    ) -> "EngineBudget":
        if payload is None:
            raise FederatedRetrievalContractError(
                f"missing budget for engine {getattr(engine, 'value', engine)!r}"
            )
        body = _mapping(payload, "engine_budget")
        return cls(
            engine=_enum(engine, RetrievalEngine, "engine"),
            max_hits=body.get("max_hits"),
            max_bytes=body.get("max_bytes"),
            timeout_ms=body.get("timeout_ms"),
        )


def _engine_budgets(value: Any) -> tuple[EngineBudget, ...]:
    if value is None:
        raise FederatedRetrievalContractError("engine_budgets is required")
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if value and all(isinstance(item, EngineBudget) for item in value):
            seen: set[RetrievalEngine] = set()
            budgets = []
            for item in value:
                if item.engine in seen:
                    raise FederatedRetrievalContractError(
                        f"duplicate engine budget for {item.engine.value}"
                    )
                seen.add(item.engine)
                budgets.append(item)
            if not budgets:
                raise FederatedRetrievalContractError(
                    "engine_budgets is required and must not be empty"
                )
            return tuple(budgets)
    budgets: list[EngineBudget] = []
    seen: set[RetrievalEngine] = set()
    if isinstance(value, Mapping):
        if not value:
            raise FederatedRetrievalContractError(
                "engine_budgets is required and must not be empty"
            )
        for engine_name, body in value.items():
            budget = EngineBudget.from_mapping(engine_name, body)
            if budget.engine in seen:
                raise FederatedRetrievalContractError(
                    f"duplicate engine budget for {budget.engine.value}"
                )
            seen.add(budget.engine)
            budgets.append(budget)
        return tuple(budgets)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if not value:
            raise FederatedRetrievalContractError(
                "engine_budgets is required and must not be empty"
            )
        for item in value:
            body = _mapping(item, "engine_budget")
            if "engine" not in body:
                raise FederatedRetrievalContractError(
                    "missing budget engine identifier"
                )
            budget = EngineBudget.from_mapping(body.get("engine"), body)
            if budget.engine in seen:
                raise FederatedRetrievalContractError(
                    f"duplicate engine budget for {budget.engine.value}"
                )
            seen.add(budget.engine)
            budgets.append(budget)
        return tuple(budgets)
    raise FederatedRetrievalContractError(
        "engine_budgets must be an object or sequence of engine budgets"
    )


@dataclass(frozen=True, slots=True)
class ProofPolicy:
    """Proof participation bound.  Imported history cannot grant authority."""

    SCHEMA: ClassVar[str] = PROOF_POLICY_INTERFACE

    mode: ProofPolicyMode = ProofPolicyMode.CONTEXT_ONLY
    imported_history_is_authority: bool = False
    allow_heuristic_as_source: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "mode", _enum(self.mode, ProofPolicyMode, "proof_policy.mode")
        )
        object.__setattr__(
            self,
            "imported_history_is_authority",
            _bool(
                self.imported_history_is_authority,
                "proof_policy.imported_history_is_authority",
            ),
        )
        object.__setattr__(
            self,
            "allow_heuristic_as_source",
            _bool(
                self.allow_heuristic_as_source,
                "proof_policy.allow_heuristic_as_source",
            ),
        )
        if self.imported_history_is_authority:
            raise FederatedRetrievalContractError(
                "imported history is never proof authority"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_heuristic_as_source": self.allow_heuristic_as_source,
            "imported_history_is_authority": self.imported_history_is_authority,
            "interface": self.SCHEMA,
            "mode": self.mode.value,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "ProofPolicy":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(mode=_enum(value, ProofPolicyMode, "proof_policy"))
        body = _mapping(value, "proof_policy")
        return cls(
            mode=body.get("mode", ProofPolicyMode.CONTEXT_ONLY),
            imported_history_is_authority=body.get(
                "imported_history_is_authority", False
            ),
            allow_heuristic_as_source=body.get("allow_heuristic_as_source", False),
        )


@dataclass(frozen=True, slots=True)
class RecencyPolicy:
    """Positive recency bound in whole seconds, with optional UTC window."""

    SCHEMA: ClassVar[str] = RECENCY_POLICY_INTERFACE

    max_age_seconds: int
    since: str = ""
    until: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_age_seconds",
            _positive_int(
                self.max_age_seconds,
                "recency.max_age_seconds",
                maximum=ABSOLUTE_MAX_AGE_SECONDS,
            ),
        )
        object.__setattr__(
            self, "since", _iso_utc(self.since or None, "recency.since", required=False)
        )
        object.__setattr__(
            self, "until", _iso_utc(self.until or None, "recency.until", required=False)
        )
        if self.since and self.until and self.until < self.since:
            raise FederatedRetrievalContractError(
                "recency.until must not precede recency.since"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface": self.SCHEMA,
            "max_age_seconds": self.max_age_seconds,
            "since": self.since,
            "until": self.until,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "RecencyPolicy":
        if isinstance(value, cls):
            return value
        if value is None:
            raise FederatedRetrievalContractError("recency is required")
        if isinstance(value, int) and not isinstance(value, bool):
            return cls(max_age_seconds=value)
        body = _mapping(value, "recency")
        if "max_age_seconds" not in body:
            raise FederatedRetrievalContractError(
                "recency.max_age_seconds is required"
            )
        return cls(
            max_age_seconds=body.get("max_age_seconds"),
            since=body.get("since", ""),
            until=body.get("until", ""),
        )


@dataclass(frozen=True, slots=True)
class EffectiveDates:
    """Inclusive UTC effective window for retrieved artifacts."""

    SCHEMA: ClassVar[str] = EFFECTIVE_DATES_INTERFACE

    effective_from: str
    effective_until: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "effective_from",
            _iso_utc(self.effective_from, "effective_dates.effective_from"),
        )
        object.__setattr__(
            self,
            "effective_until",
            _iso_utc(
                self.effective_until or None,
                "effective_dates.effective_until",
                required=False,
            ),
        )
        if (
            self.effective_until
            and self.effective_until < self.effective_from
        ):
            raise FederatedRetrievalContractError(
                "effective_until must not precede effective_from"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "effective_from": self.effective_from,
            "effective_until": self.effective_until,
            "interface": self.SCHEMA,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "EffectiveDates":
        if isinstance(value, cls):
            return value
        if value is None:
            raise FederatedRetrievalContractError("effective_dates is required")
        body = _mapping(value, "effective_dates")
        if "effective_from" not in body:
            raise FederatedRetrievalContractError(
                "effective_dates.effective_from is required"
            )
        return cls(
            effective_from=body.get("effective_from"),
            effective_until=body.get("effective_until", ""),
        )


@dataclass(frozen=True, slots=True)
class FederatedRetrievalRequest:
    """Compiled retrieval request: objectives, symbols, domains, and bounds."""

    SCHEMA: ClassVar[str] = FEDERATED_RETRIEVAL_REQUEST_INTERFACE

    objectives: tuple[str, ...]
    symbols: tuple[str, ...]
    evidence_classes: tuple[EvidenceClass, ...]
    source_domains: tuple[SourceDomain, ...]
    engine_budgets: tuple[EngineBudget, ...]
    max_graph_depth: int
    max_ast_depth: int
    proof_policy: ProofPolicy
    max_bytes: int
    min_trust: TrustClass
    recency: RecencyPolicy
    effective_dates: EffectiveDates
    contract_version: int = CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "objectives", _texts(self.objectives, "objectives")
        )
        object.__setattr__(
            self, "symbols", _texts(self.symbols, "symbols", required=False)
        )
        object.__setattr__(
            self,
            "evidence_classes",
            _enums(self.evidence_classes, EvidenceClass, "evidence_classes"),
        )
        object.__setattr__(
            self,
            "source_domains",
            _enums(self.source_domains, SourceDomain, "source_domains"),
        )
        object.__setattr__(self, "engine_budgets", _engine_budgets(self.engine_budgets))
        object.__setattr__(
            self,
            "max_graph_depth",
            _positive_int(
                self.max_graph_depth, "max_graph_depth", maximum=ABSOLUTE_MAX_DEPTH
            ),
        )
        object.__setattr__(
            self,
            "max_ast_depth",
            _positive_int(
                self.max_ast_depth, "max_ast_depth", maximum=ABSOLUTE_MAX_DEPTH
            ),
        )
        if not isinstance(self.proof_policy, ProofPolicy):
            object.__setattr__(
                self, "proof_policy", ProofPolicy.from_mapping(self.proof_policy)
            )
        object.__setattr__(
            self,
            "max_bytes",
            _positive_int(self.max_bytes, "max_bytes", maximum=ABSOLUTE_MAX_BYTES),
        )
        object.__setattr__(
            self, "min_trust", _enum(self.min_trust, TrustClass, "min_trust")
        )
        if not isinstance(self.recency, RecencyPolicy):
            object.__setattr__(self, "recency", RecencyPolicy.from_mapping(self.recency))
        if not isinstance(self.effective_dates, EffectiveDates):
            object.__setattr__(
                self,
                "effective_dates",
                EffectiveDates.from_mapping(self.effective_dates),
            )
        if self.contract_version != CONTRACT_VERSION:
            raise FederatedRetrievalContractError(
                "unsupported federated retrieval contract version; rebuild with @1"
            )
        total_engine_bytes = sum(item.max_bytes for item in self.engine_budgets)
        if total_engine_bytes > self.max_bytes:
            raise FederatedRetrievalContractError(
                "sum of per-engine max_bytes exceeds request max_bytes"
            )

    @property
    def schema(self) -> str:
        return REQUEST_SCHEMA

    @property
    def interface(self) -> str:
        return self.SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "effective_dates": self.effective_dates.to_dict(),
            "engine_budgets": [item.to_dict() for item in self.engine_budgets],
            "evidence_classes": [item.value for item in self.evidence_classes],
            "interface": self.SCHEMA,
            "max_ast_depth": self.max_ast_depth,
            "max_bytes": self.max_bytes,
            "max_graph_depth": self.max_graph_depth,
            "min_trust": self.min_trust.value,
            "objectives": list(self.objectives),
            "proof_policy": self.proof_policy.to_dict(),
            "recency": self.recency.to_dict(),
            "schema": REQUEST_SCHEMA,
            "source_domains": [item.value for item in self.source_domains],
            "symbols": list(self.symbols),
        }

    @property
    def content_id(self) -> str:
        return content_identity(self.to_dict())


@dataclass(frozen=True, slots=True)
class FederatedRetrievalPlan:
    """Deterministic plan compiled from a frozen request."""

    SCHEMA: ClassVar[str] = FEDERATED_RETRIEVAL_PLAN_INTERFACE

    request_content_id: str
    engines: tuple[RetrievalEngine, ...]
    evidence_classes: tuple[EvidenceClass, ...]
    source_domains: tuple[SourceDomain, ...]
    engine_budgets: tuple[EngineBudget, ...]
    max_graph_depth: int
    max_ast_depth: int
    proof_policy: ProofPolicy
    max_bytes: int
    min_trust: TrustClass
    recency: RecencyPolicy
    effective_dates: EffectiveDates
    contract_version: int = CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "request_content_id",
            _require_sha256(self.request_content_id, "request_content_id"),
        )
        if not self.engine_budgets:
            raise FederatedRetrievalContractError("engine_budgets is required")
        object.__setattr__(
            self,
            "engines",
            tuple(
                _enum(item, RetrievalEngine, "engines")
                for item in self.engines
            ),
        )
        if tuple(item.engine for item in self.engine_budgets) != self.engines:
            raise FederatedRetrievalContractError(
                "plan engines must match engine_budgets order"
            )

    @property
    def schema(self) -> str:
        return PLAN_SCHEMA

    @property
    def interface(self) -> str:
        return self.SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "effective_dates": self.effective_dates.to_dict(),
            "engine_budgets": [item.to_dict() for item in self.engine_budgets],
            "engines": [item.value for item in self.engines],
            "evidence_classes": [item.value for item in self.evidence_classes],
            "interface": self.SCHEMA,
            "max_ast_depth": self.max_ast_depth,
            "max_bytes": self.max_bytes,
            "max_graph_depth": self.max_graph_depth,
            "min_trust": self.min_trust.value,
            "proof_policy": self.proof_policy.to_dict(),
            "recency": self.recency.to_dict(),
            "request_content_id": self.request_content_id,
            "schema": PLAN_SCHEMA,
            "source_domains": [item.value for item in self.source_domains],
        }

    @property
    def content_id(self) -> str:
        return content_identity(self.to_dict())


@dataclass(frozen=True, slots=True)
class FederatedRetrievalHit:
    """One provenance-preserving retrieval item."""

    SCHEMA: ClassVar[str] = RETRIEVAL_HIT_INTERFACE

    identity: str
    engine: RetrievalEngine
    evidence_class: EvidenceClass
    source_domain: SourceDomain
    path: str
    bytes_used: int
    trust: TrustClass
    retrieved_at: str
    effective_from: str
    effective_until: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "identity", _require_sha256(self.identity, "identity")
        )
        object.__setattr__(
            self, "engine", _enum(self.engine, RetrievalEngine, "engine")
        )
        object.__setattr__(
            self,
            "evidence_class",
            _enum(self.evidence_class, EvidenceClass, "evidence_class"),
        )
        object.__setattr__(
            self,
            "source_domain",
            _enum(self.source_domain, SourceDomain, "source_domain"),
        )
        object.__setattr__(self, "path", _text(self.path, "path"))
        object.__setattr__(
            self,
            "bytes_used",
            _positive_int(self.bytes_used, "bytes_used", maximum=ABSOLUTE_MAX_BYTES),
        )
        object.__setattr__(self, "trust", _enum(self.trust, TrustClass, "trust"))
        object.__setattr__(
            self, "retrieved_at", _iso_utc(self.retrieved_at, "retrieved_at")
        )
        object.__setattr__(
            self, "effective_from", _iso_utc(self.effective_from, "effective_from")
        )
        object.__setattr__(
            self,
            "effective_until",
            _iso_utc(self.effective_until or None, "effective_until", required=False),
        )
        object.__setattr__(
            self, "reason", _text(self.reason, "reason", required=False)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bytes_used": self.bytes_used,
            "effective_from": self.effective_from,
            "effective_until": self.effective_until,
            "engine": self.engine.value,
            "evidence_class": self.evidence_class.value,
            "identity": self.identity,
            "interface": self.SCHEMA,
            "path": self.path,
            "reason": self.reason,
            "retrieved_at": self.retrieved_at,
            "source_domain": self.source_domain.value,
            "trust": self.trust.value,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "FederatedRetrievalHit":
        if isinstance(value, cls):
            return value
        body = _mapping(value, "hit")
        return cls(
            identity=body.get("identity"),
            engine=body.get("engine"),
            evidence_class=body.get("evidence_class"),
            source_domain=body.get("source_domain"),
            path=body.get("path"),
            bytes_used=body.get("bytes_used"),
            trust=body.get("trust"),
            retrieved_at=body.get("retrieved_at"),
            effective_from=body.get("effective_from"),
            effective_until=body.get("effective_until", ""),
            reason=body.get("reason", ""),
        )


@dataclass(frozen=True, slots=True)
class FederatedRetrievalResult:
    """Result bound to the exact request and plan identities."""

    SCHEMA: ClassVar[str] = FEDERATED_RETRIEVAL_RESULT_INTERFACE

    request_content_id: str
    plan_content_id: str
    hits: tuple[FederatedRetrievalHit, ...]
    bytes_used: int
    truncated: bool = False
    contract_version: int = CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "request_content_id",
            _require_sha256(self.request_content_id, "request_content_id"),
        )
        object.__setattr__(
            self,
            "plan_content_id",
            _require_sha256(self.plan_content_id, "plan_content_id"),
        )
        hits = tuple(
            item
            if isinstance(item, FederatedRetrievalHit)
            else FederatedRetrievalHit.from_mapping(item)
            for item in self.hits
        )
        object.__setattr__(self, "hits", hits)
        object.__setattr__(
            self,
            "bytes_used",
            _nonnegative_int(self.bytes_used, "bytes_used", maximum=ABSOLUTE_MAX_BYTES),
        )
        object.__setattr__(self, "truncated", _bool(self.truncated, "truncated"))
        if self.contract_version != CONTRACT_VERSION:
            raise FederatedRetrievalContractError(
                "unsupported federated retrieval contract version; rebuild with @1"
            )
        hit_bytes = sum(item.bytes_used for item in self.hits)
        if hit_bytes != self.bytes_used:
            raise FederatedRetrievalContractError(
                "bytes_used must equal the sum of hit bytes"
            )

    @property
    def schema(self) -> str:
        return RESULT_SCHEMA

    @property
    def interface(self) -> str:
        return self.SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "bytes_used": self.bytes_used,
            "contract_version": self.contract_version,
            "hits": [item.to_dict() for item in self.hits],
            "interface": self.SCHEMA,
            "plan_content_id": self.plan_content_id,
            "request_content_id": self.request_content_id,
            "schema": RESULT_SCHEMA,
            "truncated": self.truncated,
        }

    @property
    def content_id(self) -> str:
        return content_identity(self.to_dict())


def _require_request_fields(payload: Mapping[str, Any]) -> None:
    if "engine_budgets" not in payload or payload.get("engine_budgets") in (
        None,
        {},
        [],
    ):
        raise FederatedRetrievalContractError(
            "missing budget: engine_budgets is required and must be positive"
        )
    engines = payload.get("engines")
    if engines in (None, "", ()):
        return
    names = _texts(engines, "engines")
    budgets = payload.get("engine_budgets")
    if isinstance(budgets, Mapping):
        present = {str(key) for key in budgets}
    elif isinstance(budgets, Sequence) and not isinstance(
        budgets, (str, bytes, bytearray)
    ):
        present = set()
        for item in budgets:
            body = _mapping(item, "engine_budget")
            engine = body.get("engine")
            if engine is None:
                raise FederatedRetrievalContractError(
                    "missing budget engine identifier"
                )
            present.add(str(getattr(engine, "value", engine)))
    else:
        raise FederatedRetrievalContractError(
            "engine_budgets must be an object or sequence of engine budgets"
        )
    missing = [name for name in names if name not in present]
    if missing:
        raise FederatedRetrievalContractError(
            f"missing budget for engine {missing[0]!r}"
        )


def compile_request(payload: Mapping[str, Any] | FederatedRetrievalRequest) -> FederatedRetrievalRequest:
    """Validate and freeze a federated retrieval request at ``@1``."""

    if isinstance(payload, FederatedRetrievalRequest):
        return payload
    body = _mapping(payload, "request")
    _require_request_fields(body)
    request = FederatedRetrievalRequest(
        objectives=body.get("objectives"),
        symbols=body.get("symbols") or (),
        evidence_classes=body.get("evidence_classes"),
        source_domains=body.get("source_domains"),
        engine_budgets=body.get("engine_budgets"),
        max_graph_depth=body.get("max_graph_depth"),
        max_ast_depth=body.get("max_ast_depth"),
        proof_policy=ProofPolicy.from_mapping(body.get("proof_policy")),
        max_bytes=body.get("max_bytes"),
        min_trust=body.get("min_trust", TrustClass.IMPORTED_UNVERIFIED),
        recency=RecencyPolicy.from_mapping(body.get("recency")),
        effective_dates=EffectiveDates.from_mapping(body.get("effective_dates")),
        contract_version=body.get("contract_version", CONTRACT_VERSION),
    )
    return request


def compile_plan(
    request: Mapping[str, Any] | FederatedRetrievalRequest,
) -> FederatedRetrievalPlan:
    """Compile a provenance-preserving retrieval plan from a frozen request."""

    compiled = compile_request(request)
    return FederatedRetrievalPlan(
        request_content_id=compiled.content_id,
        engines=tuple(item.engine for item in compiled.engine_budgets),
        evidence_classes=compiled.evidence_classes,
        source_domains=compiled.source_domains,
        engine_budgets=compiled.engine_budgets,
        max_graph_depth=compiled.max_graph_depth,
        max_ast_depth=compiled.max_ast_depth,
        proof_policy=compiled.proof_policy,
        max_bytes=compiled.max_bytes,
        min_trust=compiled.min_trust,
        recency=compiled.recency,
        effective_dates=compiled.effective_dates,
        contract_version=compiled.contract_version,
    )


def compile_result(
    payload: Mapping[str, Any] | FederatedRetrievalResult,
    *,
    request: Mapping[str, Any] | FederatedRetrievalRequest | None = None,
    plan: FederatedRetrievalPlan | None = None,
) -> FederatedRetrievalResult:
    """Freeze a result bound to the compiled request and plan identities."""

    if isinstance(payload, FederatedRetrievalResult):
        return payload
    compiled_request = compile_request(request) if request is not None else None
    compiled_plan = plan if plan is not None else (
        compile_plan(compiled_request) if compiled_request is not None else None
    )
    body = _mapping(payload, "result")
    request_content_id = body.get("request_content_id")
    plan_content_id = body.get("plan_content_id")
    if compiled_request is not None:
        expected = compiled_request.content_id
        if request_content_id in (None, ""):
            request_content_id = expected
        elif request_content_id != expected:
            raise FederatedRetrievalContractError(
                "result request_content_id does not match compiled request"
            )
    if compiled_plan is not None:
        expected_plan = compiled_plan.content_id
        if plan_content_id in (None, ""):
            plan_content_id = expected_plan
        elif plan_content_id != expected_plan:
            raise FederatedRetrievalContractError(
                "result plan_content_id does not match compiled plan"
            )
    hits = tuple(
        FederatedRetrievalHit.from_mapping(item) for item in (body.get("hits") or ())
    )
    if compiled_request is not None:
        allowed_domains = set(compiled_request.source_domains)
        allowed_classes = set(compiled_request.evidence_classes)
        allowed_engines = {item.engine for item in compiled_request.engine_budgets}
        for hit in hits:
            if hit.source_domain not in allowed_domains:
                raise FederatedRetrievalContractError(
                    f"unknown domain {hit.source_domain.value!r} for compiled request"
                )
            if hit.evidence_class not in allowed_classes:
                raise FederatedRetrievalContractError(
                    f"evidence_class {hit.evidence_class.value!r} is not admitted"
                )
            if hit.engine not in allowed_engines:
                raise FederatedRetrievalContractError(
                    f"engine {hit.engine.value!r} is not in the compiled plan"
                )
            if hit.trust.rank < compiled_request.min_trust.rank:
                raise FederatedRetrievalContractError(
                    "hit trust is below the request min_trust floor"
                )
            if (
                hit.effective_from < compiled_request.effective_dates.effective_from
            ):
                raise FederatedRetrievalContractError(
                    "hit effective_from precedes request effective_from"
                )
    bytes_used = body.get("bytes_used")
    if bytes_used is None:
        bytes_used = sum(item.bytes_used for item in hits)
    if compiled_request is not None and bytes_used > compiled_request.max_bytes:
        raise FederatedRetrievalContractError(
            "result bytes_used exceeds request max_bytes"
        )
    return FederatedRetrievalResult(
        request_content_id=request_content_id,
        plan_content_id=plan_content_id,
        hits=hits,
        bytes_used=bytes_used,
        truncated=_bool(body.get("truncated", False), "truncated"),
        contract_version=body.get("contract_version", CONTRACT_VERSION),
    )


__all__ = [
    "CONTRACT_VERSION",
    "ENGINE_BUDGET_INTERFACE",
    "EVIDENCE_CLASSES",
    "FEDERATED_RETRIEVAL_PLAN_INTERFACE",
    "FEDERATED_RETRIEVAL_REQUEST_INTERFACE",
    "FEDERATED_RETRIEVAL_RESULT_INTERFACE",
    "PLAN_SCHEMA",
    "PROOF_POLICY_INTERFACE",
    "REQUEST_SCHEMA",
    "RESULT_SCHEMA",
    "RETRIEVAL_ENGINES",
    "SCHEMA_VERSION",
    "SOURCE_DOMAINS",
    "EffectiveDates",
    "EngineBudget",
    "EvidenceClass",
    "FederatedRetrievalContractError",
    "FederatedRetrievalHit",
    "FederatedRetrievalPlan",
    "FederatedRetrievalRequest",
    "FederatedRetrievalResult",
    "ProofPolicy",
    "ProofPolicyMode",
    "RecencyPolicy",
    "RetrievalEngine",
    "SourceDomain",
    "TrustClass",
    "canonical_json_bytes",
    "compile_plan",
    "compile_request",
    "compile_result",
    "content_identity",
]
