"""Closed, deterministic durable value records for the semantic-state producer.

This module exclusively owns every self-verifying semantic-state payload type and
enum.  Later modules own algorithms only and import these values.

Authority rules (normative):

* Canonical bytes / CIDv1 come only from ``software_contracts.content``.
* Records are recursively immutable, closed to unknown fields, and restricted to
  strict DAG-JSON types admitted by content identity.
* Stable symbol IDs, version CIDs, and edge IDs are preserved verbatim from the
  final ISI producer — never translated or recalculated here.
* Sorted pair indexes reject duplicate keys.
* The datasets ``SemanticStateRoot`` excludes transition history, selections,
  receipts, clocks, local paths, leases, generations, model data, and MCP++
  envelope identities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
import unicodedata
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
    decode_and_recompute_source,
    decode_and_recompute_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    ArtifactRecord,
    RelationType,
    SourceSpan,
    SymbolRecord,
)


# ---------------------------------------------------------------------------
# Schema constants (normative)
# ---------------------------------------------------------------------------

SEMANTIC_STATE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-state@1"
)
SEMANTIC_STATE_ROOT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-state-root@1"
)
SEMANTIC_CAPSULE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-capsule@1"
)
MERKLE_COMPILER_VERSION: Final[str] = "1"
CAPSULE_COMPILER_VERSION: Final[str] = "1"

SYMBOL_FACT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-symbol-fact@1"
)
ARTIFACT_FACT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-artifact-fact@1"
)
SEMANTIC_LINK_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-link@1"
)
SYMBOL_MERKLE_NODE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-symbol-merkle-node@1"
)
SORTED_PAIR_INDEX_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-sorted-pair-index@1"
)
ENVIRONMENT_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-environment-binding@1"
)
ENVIRONMENT_BINDING_SET_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-environment-binding-set@1"
)
RELEVANT_BINDING_PROJECTION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-relevant-binding-projection@1"
)
SEMANTIC_BINDING_DELTA_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-binding-delta@1"
)
SEMANTIC_INVALIDATION_OBLIGATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-invalidation-obligation@1"
)
SEMANTIC_INVALIDATION_PLAN_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-invalidation-plan@1"
)
CAPSULE_FRESHNESS_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-capsule-freshness@1"
)
VERIFIED_SOURCE_EVIDENCE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-verified-source-evidence@1"
)
SELECTION_POLICY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-selection-policy@1"
)
SELECTION_RULE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-selection-rule@1"
)
TEST_SELECTION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-test-selection@1"
)
TEST_OUTCOME_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-test-outcome@1"
)
TEST_RUN_FACTS_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-test-run-facts@1"
)
TEST_ORACLE_COMPARISON_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-test-oracle-comparison@1"
)
ANALYSIS_LIMITATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-analysis-limitation@1"
)
REASON_PATH_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-reason-path@1"
)
PRODUCER_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-state-producer@1"
)

# Fields deliberately excluded from the datasets root (accelerate / MCP++ domain).
ROOT_EXCLUDED_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "previous_root",
        "previous_root_cid",
        "history",
        "histories",
        "transition",
        "transitions",
        "delta",
        "repository_delta",
        "invalidation_plan",
        "invalidation",
        "selection",
        "selections",
        "test_selection",
        "proof_selection",
        "receipt",
        "receipts",
        "acceptance",
        "timestamp",
        "timestamps",
        "clock",
        "clocks",
        "wall_clock",
        "process_id",
        "pid",
        "local_path",
        "local_paths",
        "checkout_path",
        "store_path",
        "lease",
        "leases",
        "fence",
        "fences",
        "generation",
        "generations",
        "cas_generation",
        "wal_position",
        "model",
        "model_data",
        "model_output",
        "provider",
        "provider_output",
        "prompt",
        "prompts",
        "context_pack",
        "context_packs",
        "task_text",
        "request_id",
        "attempt",
        "envelope",
        "envelope_cid",
        "execution_envelope",
        "execution_receipt",
        "dag_event",
        "interface_descriptor",
        "signature",
        "availability",
        "simulation",
        "simulation_flag",
    }
)


class SemanticStateModelError(ValueError):
    """Raised when a semantic-state durable record is malformed."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class LinkTargetKind(str, Enum):
    SYMBOL = "symbol"
    ARTIFACT = "artifact"
    UNRESOLVED = "unresolved"


class BindingKind(str, Enum):
    DEPENDENCY_MANIFEST = "dependency_manifest"
    DEPENDENCY_LOCK = "dependency_lock"
    PYTEST_CONFIG = "pytest_config"
    PYTEST_PLUGIN = "pytest_plugin"
    PROOF_CONFIG = "proof_config"
    POLICY = "policy"
    INTERFACE_DESCRIPTOR = "interface_descriptor"
    GENERATED_INPUT = "generated_input"
    PYTHON_TOOLCHAIN = "python_toolchain"
    SEMANTIC_SCHEMA = "semantic_schema"
    SEMANTIC_COMPILER = "semantic_compiler"


class BindingScope(str, Enum):
    GLOBAL = "global"
    PACKAGE = "package"
    MODULE = "module"
    SYMBOL = "symbol"
    UNKNOWN = "unknown"


class FreshnessState(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class AdmissionDecision(str, Enum):
    EXACT_SUBSTITUTE = "exact_substitute"
    CONSERVATIVE_SUBSTITUTE_WITH_CAVEATS = "conservative_substitute_with_caveats"
    RAW_SOURCE_REQUIRED = "raw_source_required"


class SelectionFallback(str, Enum):
    NONE = "none"
    FULL_PYTEST = "full_pytest"
    FULL_PROOFS = "full_proofs"
    BOTH = "both"


class SelectionRuleKind(str, Enum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    FORCE_FULL = "force_full"
    FORCE_FULL_PYTEST = "force_full_pytest"
    FORCE_FULL_PROOFS = "force_full_proofs"


class NormalizedTestStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    XFAILED = "xfailed"
    XPASSED = "xpassed"
    ERROR = "error"
    TIMEOUT = "timeout"


class ObligationOrigin(str, Enum):
    ISI = "isi"
    ENVIRONMENT = "environment"


class OracleApplicability(str, Enum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise SemanticStateModelError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise SemanticStateModelError(f"{name} must be trimmed NFC text")
    if len(value) > 16_384 or any(not char.isprintable() for char in value):
        raise SemanticStateModelError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise SemanticStateModelError(
            f"{name} has unsupported value {value!r}"
        ) from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise SemanticStateModelError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _freeze_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_structured(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_structured(item) for item in value)
    return value


def _thaw_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_structured(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_structured(item) for item in value]
    return value


def _mapping(value: Any, name: str, *, frozen: bool = True) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SemanticStateModelError(f"{name} must be a mapping")
    result = _thaw_structured(dict(value))
    try:
        validate_structured_value(result)
    except Exception as exc:
        raise SemanticStateModelError(f"{name} must be strict DAG-JSON") from exc
    return _freeze_structured(result) if frozen else result


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise SemanticStateModelError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        raise SemanticStateModelError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


def _unique_sorted(values: Iterable[str], name: str) -> tuple[str, ...]:
    ordered = tuple(sorted(_text(value, name) for value in values))
    if len(ordered) != len(set(ordered)):
        raise SemanticStateModelError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_cids(values: Iterable[str], name: str) -> tuple[str, ...]:
    ordered = tuple(sorted(_cid(value, name) for value in values))
    if len(ordered) != len(set(ordered)):
        raise SemanticStateModelError(f"{name} must not contain duplicates")
    return ordered


def _ordered_texts(values: Iterable[str], name: str) -> tuple[str, ...]:
    return tuple(_text(value, name) for value in values)


def _sorted_records(values: Iterable[Any], attribute: str, name: str) -> tuple[Any, ...]:
    result = tuple(sorted(values, key=lambda item: getattr(item, attribute)))
    if len({getattr(item, attribute) for item in result}) != len(result):
        raise SemanticStateModelError(
            f"{name} must not contain duplicate {attribute}s"
        )
    return result


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise SemanticStateModelError(f"{name} must be a nonnegative integer")
    return value


def _optional_basis_points(value: Any, name: str) -> int | None:
    """Optional ratio as integer basis points in ``[0, 10000]``, or null."""
    if value is None:
        return None
    if type(value) is not int or isinstance(value, bool) or value < 0 or value > 10_000:
        raise SemanticStateModelError(
            f"{name} must be an integer basis-point ratio in [0, 10000] or null"
        )
    return value


def _git_oid_or_null(value: Any, name: str) -> str | None:
    if value is None:
        return None
    text = _text(value, name)
    if len(text) not in {40, 64} or any(
        ch not in "0123456789abcdef" for ch in text
    ):
        raise SemanticStateModelError(
            f"{name} must be a lowercase hex Git OID or null"
        )
    return text


# ---------------------------------------------------------------------------
# Sorted pair index
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SortedPairIndex:
    """Sorted, duplicate-free list of ``[logical_key, cid]`` pairs."""

    pairs: Sequence[Sequence[str]] = ()

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"schema", "pairs", "index_cid"})

    def __post_init__(self) -> None:
        normalized: list[tuple[str, str]] = []
        seen: set[str] = set()
        for item in self.pairs:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise SemanticStateModelError(
                    "pairs must be length-2 [logical_key, cid] sequences"
                )
            key = _text(item[0], "logical_key")
            cid = _cid(item[1], "pair_cid")
            if key in seen:
                raise SemanticStateModelError(
                    f"sorted pair index rejects duplicate key {key!r}"
                )
            seen.add(key)
            normalized.append((key, cid))
        ordered = tuple(sorted(normalized, key=lambda pair: pair[0]))
        object.__setattr__(self, "pairs", ordered)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SORTED_PAIR_INDEX_SCHEMA,
            "pairs": [[key, cid] for key, cid in self.pairs],
        }

    @property
    def index_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["index_cid"] = self.index_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SortedPairIndex":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("index_cid")
        if payload.pop("schema") != SORTED_PAIR_INDEX_SCHEMA:
            raise SemanticStateModelError(
                "unsupported SortedPairIndex schema version"
            )
        result = cls(pairs=payload["pairs"])
        if claimed != result.index_cid:
            raise SemanticStateModelError(
                "SortedPairIndex index_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# Producer identity (root sub-record)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SemanticStateProducer:
    """Producer identity copied from and verified against the final ISI view."""

    repository_state_cid: str
    repository_snapshot_cid: str
    git_commit_oid_or_null: str | None
    git_tree_oid_or_null: str | None
    source_manifest_cid: str
    semantic_index_schema: str
    extractor_name: str
    extractor_version: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "repository_state_cid",
            "repository_snapshot_cid",
            "git_commit_oid_or_null",
            "git_tree_oid_or_null",
            "source_manifest_cid",
            "semantic_index_schema",
            "extractor_name",
            "extractor_version",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "repository_state_cid", _cid(self.repository_state_cid, "repository_state_cid")
        )
        object.__setattr__(
            self,
            "repository_snapshot_cid",
            _cid(self.repository_snapshot_cid, "repository_snapshot_cid"),
        )
        object.__setattr__(
            self,
            "git_commit_oid_or_null",
            _git_oid_or_null(self.git_commit_oid_or_null, "git_commit_oid_or_null"),
        )
        object.__setattr__(
            self,
            "git_tree_oid_or_null",
            _git_oid_or_null(self.git_tree_oid_or_null, "git_tree_oid_or_null"),
        )
        object.__setattr__(
            self, "source_manifest_cid", _cid(self.source_manifest_cid, "source_manifest_cid")
        )
        object.__setattr__(
            self,
            "semantic_index_schema",
            _text(self.semantic_index_schema, "semantic_index_schema"),
        )
        object.__setattr__(self, "extractor_name", _text(self.extractor_name, "extractor_name"))
        object.__setattr__(
            self, "extractor_version", _text(self.extractor_version, "extractor_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PRODUCER_SCHEMA,
            "repository_state_cid": self.repository_state_cid,
            "repository_snapshot_cid": self.repository_snapshot_cid,
            "git_commit_oid_or_null": self.git_commit_oid_or_null,
            "git_tree_oid_or_null": self.git_tree_oid_or_null,
            "source_manifest_cid": self.source_manifest_cid,
            "semantic_index_schema": self.semantic_index_schema,
            "extractor_name": self.extractor_name,
            "extractor_version": self.extractor_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticStateProducer":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        if payload.pop("schema") != PRODUCER_SCHEMA:
            raise SemanticStateModelError(
                "unsupported SemanticStateProducer schema version"
            )
        return cls(**payload)


# ---------------------------------------------------------------------------
# Fact nodes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SymbolFactNode:
    """Binds an exact ISI ``SymbolRecord`` and its preserved identity fields."""

    symbol: SymbolRecord

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "stable_symbol_id",
            "version_cid",
            "repository_id",
            "source_cid",
            "span",
            "confidence",
            "symbol",
            "fact_cid",
        }
    )

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, SymbolRecord):
            raise SemanticStateModelError("symbol must be a SymbolRecord")

    @property
    def stable_symbol_id(self) -> str:
        return self.symbol.stable_id

    @property
    def version_cid(self) -> str:
        return self.symbol.version_cid

    @property
    def repository_id(self) -> str:
        return self.symbol.repository_id

    @property
    def source_cid(self) -> str | None:
        return self.symbol.source_cid

    @property
    def span(self) -> SourceSpan | None:
        return self.symbol.span

    @property
    def confidence(self) -> str:
        return str(self.symbol.confidence)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SYMBOL_FACT_SCHEMA,
            "stable_symbol_id": self.stable_symbol_id,
            "version_cid": self.version_cid,
            "repository_id": self.repository_id,
            "source_cid": self.source_cid,
            "span": None if self.span is None else self.span.to_dict(),
            "confidence": self.confidence,
            "symbol": self.symbol.to_dict(),
        }

    @property
    def fact_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["fact_cid"] = self.fact_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SymbolFactNode":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("fact_cid")
        if payload.pop("schema") != SYMBOL_FACT_SCHEMA:
            raise SemanticStateModelError(
                "unsupported SymbolFactNode schema version"
            )
        symbol = SymbolRecord.from_dict(payload["symbol"])
        # Preserve ISI stable/version IDs verbatim: claimed outer fields must
        # match the embedded symbol without translation.
        if payload["stable_symbol_id"] != symbol.stable_id:
            raise SemanticStateModelError(
                "stable_symbol_id must match embedded SymbolRecord.stable_id verbatim"
            )
        if payload["version_cid"] != symbol.version_cid:
            raise SemanticStateModelError(
                "version_cid must match embedded SymbolRecord.version_cid verbatim"
            )
        if payload["repository_id"] != symbol.repository_id:
            raise SemanticStateModelError(
                "repository_id must match embedded SymbolRecord.repository_id"
            )
        if payload["source_cid"] != symbol.source_cid:
            raise SemanticStateModelError(
                "source_cid must match embedded SymbolRecord.source_cid"
            )
        claimed_span = payload["span"]
        symbol_span = None if symbol.span is None else symbol.span.to_dict()
        if claimed_span != symbol_span:
            raise SemanticStateModelError(
                "span must match embedded SymbolRecord.span"
            )
        if payload["confidence"] != str(symbol.confidence):
            raise SemanticStateModelError(
                "confidence must match embedded SymbolRecord.confidence"
            )
        result = cls(symbol=symbol)
        if claimed != result.fact_cid:
            raise SemanticStateModelError("SymbolFactNode fact_cid does not verify")
        return result


@dataclass(frozen=True, slots=True)
class ArtifactFactNode:
    """Binds an exact ISI ``ArtifactRecord`` and its source identity."""

    artifact: ArtifactRecord

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "artifact_id",
            "kind",
            "path",
            "source_cid",
            "confidence",
            "artifact",
            "fact_cid",
        }
    )

    def __post_init__(self) -> None:
        if not isinstance(self.artifact, ArtifactRecord):
            raise SemanticStateModelError("artifact must be an ArtifactRecord")

    @property
    def artifact_id(self) -> str:
        return self.artifact.artifact_id

    @property
    def kind(self) -> str:
        return self.artifact.kind

    @property
    def path(self) -> str:
        return self.artifact.path

    @property
    def source_cid(self) -> str | None:
        return self.artifact.source_cid

    @property
    def confidence(self) -> str:
        return str(self.artifact.confidence)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": ARTIFACT_FACT_SCHEMA,
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "path": self.path,
            "source_cid": self.source_cid,
            "confidence": self.confidence,
            "artifact": self.artifact.to_dict(),
        }

    @property
    def fact_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["fact_cid"] = self.fact_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArtifactFactNode":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("fact_cid")
        if payload.pop("schema") != ARTIFACT_FACT_SCHEMA:
            raise SemanticStateModelError(
                "unsupported ArtifactFactNode schema version"
            )
        artifact = ArtifactRecord.from_dict(payload["artifact"])
        if payload["artifact_id"] != artifact.artifact_id:
            raise SemanticStateModelError(
                "artifact_id must match embedded ArtifactRecord.artifact_id"
            )
        if payload["kind"] != artifact.kind:
            raise SemanticStateModelError(
                "kind must match embedded ArtifactRecord.kind"
            )
        if payload["path"] != artifact.path:
            raise SemanticStateModelError(
                "path must match embedded ArtifactRecord.path"
            )
        if payload["source_cid"] != artifact.source_cid:
            raise SemanticStateModelError(
                "source_cid must match embedded ArtifactRecord.source_cid"
            )
        if payload["confidence"] != str(artifact.confidence):
            raise SemanticStateModelError(
                "confidence must match embedded ArtifactRecord.confidence"
            )
        result = cls(artifact=artifact)
        if claimed != result.fact_cid:
            raise SemanticStateModelError(
                "ArtifactFactNode fact_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# Links and Merkle nodes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SemanticLinkNode:
    """Wraps an authoritative ISI edge ID without replacing it."""

    edge_id: str
    source_stable_id: str
    source_version_cid: str
    source_fact_cid: str
    target_kind: LinkTargetKind | str
    target_stable_id: str | None
    target_version_cid: str | None
    target_fact_cid: str | None
    relation: RelationType | str
    source_span: SourceSpan | None
    extraction_method: str
    confidence: AnalysisConfidence | str
    extractor_version: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "edge_id",
            "source_stable_id",
            "source_version_cid",
            "source_fact_cid",
            "target_kind",
            "target_stable_id",
            "target_version_cid",
            "target_fact_cid",
            "relation",
            "source_span",
            "extraction_method",
            "confidence",
            "extractor_version",
            "metadata",
            "link_cid",
        }
    )

    def __post_init__(self) -> None:
        # edge_id is preserved verbatim from ISI (validate as CID only).
        object.__setattr__(self, "edge_id", _cid(self.edge_id, "edge_id"))
        object.__setattr__(
            self, "source_stable_id", _cid(self.source_stable_id, "source_stable_id")
        )
        object.__setattr__(
            self, "source_version_cid", _cid(self.source_version_cid, "source_version_cid")
        )
        object.__setattr__(
            self, "source_fact_cid", _cid(self.source_fact_cid, "source_fact_cid")
        )
        object.__setattr__(
            self, "target_kind", _enum(self.target_kind, LinkTargetKind, "target_kind")
        )
        kind = self.target_kind
        if kind == LinkTargetKind.UNRESOLVED.value:
            if self.target_stable_id is not None or self.target_version_cid is not None:
                raise SemanticStateModelError(
                    "unresolved targets must not carry resolved identity"
                )
            object.__setattr__(self, "target_stable_id", None)
            object.__setattr__(self, "target_version_cid", None)
            object.__setattr__(
                self, "target_fact_cid", _optional_cid(self.target_fact_cid, "target_fact_cid")
            )
        else:
            object.__setattr__(
                self, "target_stable_id", _text(self.target_stable_id, "target_stable_id")
            )
            # Symbol targets use CID stable IDs; artifact targets use text IDs.
            if kind == LinkTargetKind.SYMBOL.value:
                object.__setattr__(
                    self,
                    "target_stable_id",
                    _cid(self.target_stable_id, "target_stable_id"),
                )
                object.__setattr__(
                    self,
                    "target_version_cid",
                    _cid(self.target_version_cid, "target_version_cid"),
                )
            else:
                object.__setattr__(
                    self,
                    "target_version_cid",
                    _optional_cid(self.target_version_cid, "target_version_cid"),
                )
            object.__setattr__(
                self, "target_fact_cid", _optional_cid(self.target_fact_cid, "target_fact_cid")
            )
        object.__setattr__(self, "relation", _enum(self.relation, RelationType, "relation"))
        if self.source_span is not None and not isinstance(self.source_span, SourceSpan):
            raise SemanticStateModelError("source_span must be a SourceSpan or None")
        object.__setattr__(
            self, "extraction_method", _text(self.extraction_method, "extraction_method")
        )
        object.__setattr__(
            self, "confidence", _enum(self.confidence, AnalysisConfidence, "confidence")
        )
        object.__setattr__(
            self, "extractor_version", _text(self.extractor_version, "extractor_version")
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SEMANTIC_LINK_SCHEMA,
            "edge_id": self.edge_id,
            "source_stable_id": self.source_stable_id,
            "source_version_cid": self.source_version_cid,
            "source_fact_cid": self.source_fact_cid,
            "target_kind": self.target_kind,
            "target_stable_id": self.target_stable_id,
            "target_version_cid": self.target_version_cid,
            "target_fact_cid": self.target_fact_cid,
            "relation": self.relation,
            "source_span": None if self.source_span is None else self.source_span.to_dict(),
            "extraction_method": self.extraction_method,
            "confidence": self.confidence,
            "extractor_version": self.extractor_version,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def link_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["link_cid"] = self.link_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticLinkNode":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("link_cid")
        if payload.pop("schema") != SEMANTIC_LINK_SCHEMA:
            raise SemanticStateModelError(
                "unsupported SemanticLinkNode schema version"
            )
        if payload["source_span"] is not None:
            payload["source_span"] = SourceSpan.from_dict(payload["source_span"])
        result = cls(**payload)
        if claimed != result.link_cid:
            raise SemanticStateModelError(
                "SemanticLinkNode link_cid does not verify"
            )
        return result


@dataclass(frozen=True, slots=True)
class SymbolMerkleNode:
    """Acyclic symbol-level Merkle node bound to fact and capsule CIDs."""

    stable_symbol_id: str
    version_cid: str
    symbol_fact_cid: str
    capsule_cid: str
    incoming_link_cids: Sequence[str] = ()
    outgoing_link_cids: Sequence[str] = ()
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT
    raw_source_required_reasons: Sequence[str] = ()

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "stable_symbol_id",
            "version_cid",
            "symbol_fact_cid",
            "capsule_cid",
            "incoming_link_cids",
            "outgoing_link_cids",
            "confidence",
            "raw_source_required_reasons",
            "node_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "stable_symbol_id", _cid(self.stable_symbol_id, "stable_symbol_id")
        )
        object.__setattr__(self, "version_cid", _cid(self.version_cid, "version_cid"))
        object.__setattr__(
            self, "symbol_fact_cid", _cid(self.symbol_fact_cid, "symbol_fact_cid")
        )
        object.__setattr__(self, "capsule_cid", _cid(self.capsule_cid, "capsule_cid"))
        object.__setattr__(
            self,
            "incoming_link_cids",
            _unique_sorted_cids(self.incoming_link_cids, "incoming_link_cid"),
        )
        object.__setattr__(
            self,
            "outgoing_link_cids",
            _unique_sorted_cids(self.outgoing_link_cids, "outgoing_link_cid"),
        )
        object.__setattr__(
            self, "confidence", _enum(self.confidence, AnalysisConfidence, "confidence")
        )
        object.__setattr__(
            self,
            "raw_source_required_reasons",
            _unique_sorted(self.raw_source_required_reasons, "raw_source_required_reason"),
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SYMBOL_MERKLE_NODE_SCHEMA,
            "stable_symbol_id": self.stable_symbol_id,
            "version_cid": self.version_cid,
            "symbol_fact_cid": self.symbol_fact_cid,
            "capsule_cid": self.capsule_cid,
            "incoming_link_cids": list(self.incoming_link_cids),
            "outgoing_link_cids": list(self.outgoing_link_cids),
            "confidence": self.confidence,
            "raw_source_required_reasons": list(self.raw_source_required_reasons),
        }

    @property
    def node_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["node_cid"] = self.node_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SymbolMerkleNode":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("node_cid")
        if payload.pop("schema") != SYMBOL_MERKLE_NODE_SCHEMA:
            raise SemanticStateModelError(
                "unsupported SymbolMerkleNode schema version"
            )
        result = cls(**payload)
        if claimed != result.node_cid:
            raise SemanticStateModelError(
                "SymbolMerkleNode node_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# Capsules
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SemanticCapsule:
    """Deterministic authoritative capsule for one symbol version."""

    stable_symbol_id: str
    version_cid: str
    semantic_index_schema: str
    extractor_version: str
    capsule_schema: str = SEMANTIC_CAPSULE_SCHEMA
    capsule_compiler_version: str = CAPSULE_COMPILER_VERSION
    source_slice_path: str = ""
    source_cid: str | None = None
    symbol_fact_cid: str | None = None
    signature: Mapping[str, Any] = field(default_factory=dict)
    annotations: Mapping[str, Any] = field(default_factory=dict)
    defaults: Mapping[str, Any] = field(default_factory=dict)
    decorators: Sequence[str] = ()
    contracts: Mapping[str, Any] = field(default_factory=dict)
    effects: Sequence[str] = ()
    exception_behavior: Mapping[str, Any] = field(default_factory=dict)
    schema_relations: Sequence[str] = ()
    serialization_relations: Sequence[str] = ()
    test_refs: Sequence[str] = ()
    fixture_refs: Sequence[str] = ()
    proof_obligation_refs: Sequence[str] = ()
    dependency_stable_ids: Sequence[str] = ()
    dependency_version_cids: Sequence[str] = ()
    dependency_fact_cids: Sequence[str] = ()
    dependency_link_ids: Sequence[str] = ()
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT
    relevant_binding_projection_cid: str | None = None
    docstring_hint: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "stable_symbol_id",
            "version_cid",
            "semantic_index_schema",
            "extractor_version",
            "capsule_schema",
            "capsule_compiler_version",
            "source_slice_path",
            "source_cid",
            "symbol_fact_cid",
            "signature",
            "annotations",
            "defaults",
            "decorators",
            "contracts",
            "effects",
            "exception_behavior",
            "schema_relations",
            "serialization_relations",
            "test_refs",
            "fixture_refs",
            "proof_obligation_refs",
            "dependency_stable_ids",
            "dependency_version_cids",
            "dependency_fact_cids",
            "dependency_link_ids",
            "confidence",
            "relevant_binding_projection_cid",
            "docstring_hint",
            "metadata",
            "capsule_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "stable_symbol_id", _cid(self.stable_symbol_id, "stable_symbol_id")
        )
        object.__setattr__(self, "version_cid", _cid(self.version_cid, "version_cid"))
        object.__setattr__(
            self,
            "semantic_index_schema",
            _text(self.semantic_index_schema, "semantic_index_schema"),
        )
        object.__setattr__(
            self, "extractor_version", _text(self.extractor_version, "extractor_version")
        )
        if self.capsule_schema != SEMANTIC_CAPSULE_SCHEMA:
            raise SemanticStateModelError("unsupported capsule_schema version")
        if self.capsule_compiler_version != CAPSULE_COMPILER_VERSION:
            raise SemanticStateModelError(
                "unsupported capsule_compiler_version"
            )
        object.__setattr__(
            self, "source_slice_path", _text(self.source_slice_path, "source_slice_path", empty=True)
        )
        object.__setattr__(self, "source_cid", _optional_cid(self.source_cid, "source_cid"))
        object.__setattr__(
            self, "symbol_fact_cid", _optional_cid(self.symbol_fact_cid, "symbol_fact_cid")
        )
        object.__setattr__(self, "signature", _mapping(self.signature, "signature"))
        object.__setattr__(self, "annotations", _mapping(self.annotations, "annotations"))
        object.__setattr__(self, "defaults", _mapping(self.defaults, "defaults"))
        object.__setattr__(self, "decorators", _ordered_texts(self.decorators, "decorator"))
        object.__setattr__(self, "contracts", _mapping(self.contracts, "contracts"))
        object.__setattr__(self, "effects", _unique_sorted(self.effects, "effect"))
        object.__setattr__(
            self, "exception_behavior", _mapping(self.exception_behavior, "exception_behavior")
        )
        object.__setattr__(
            self, "schema_relations", _unique_sorted(self.schema_relations, "schema_relation")
        )
        object.__setattr__(
            self,
            "serialization_relations",
            _unique_sorted(self.serialization_relations, "serialization_relation"),
        )
        object.__setattr__(self, "test_refs", _unique_sorted(self.test_refs, "test_ref"))
        object.__setattr__(
            self, "fixture_refs", _unique_sorted(self.fixture_refs, "fixture_ref")
        )
        object.__setattr__(
            self,
            "proof_obligation_refs",
            _unique_sorted(self.proof_obligation_refs, "proof_obligation_ref"),
        )
        object.__setattr__(
            self,
            "dependency_stable_ids",
            _unique_sorted(self.dependency_stable_ids, "dependency_stable_id"),
        )
        object.__setattr__(
            self,
            "dependency_version_cids",
            _unique_sorted_cids(self.dependency_version_cids, "dependency_version_cid"),
        )
        object.__setattr__(
            self,
            "dependency_fact_cids",
            _unique_sorted_cids(self.dependency_fact_cids, "dependency_fact_cid"),
        )
        object.__setattr__(
            self,
            "dependency_link_ids",
            _unique_sorted_cids(self.dependency_link_ids, "dependency_link_id"),
        )
        object.__setattr__(
            self, "confidence", _enum(self.confidence, AnalysisConfidence, "confidence")
        )
        object.__setattr__(
            self,
            "relevant_binding_projection_cid",
            _optional_cid(
                self.relevant_binding_projection_cid, "relevant_binding_projection_cid"
            ),
        )
        object.__setattr__(
            self, "docstring_hint", _optional_text(self.docstring_hint, "docstring_hint")
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def producer_key(self) -> tuple[str, str, str, str]:
        """Normative ISI producer key for this capsule."""
        return (
            self.stable_symbol_id,
            self.version_cid,
            self.semantic_index_schema,
            self.extractor_version,
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SEMANTIC_CAPSULE_SCHEMA,
            "stable_symbol_id": self.stable_symbol_id,
            "version_cid": self.version_cid,
            "semantic_index_schema": self.semantic_index_schema,
            "extractor_version": self.extractor_version,
            "capsule_schema": self.capsule_schema,
            "capsule_compiler_version": self.capsule_compiler_version,
            "source_slice_path": self.source_slice_path,
            "source_cid": self.source_cid,
            "symbol_fact_cid": self.symbol_fact_cid,
            "signature": _thaw_structured(self.signature),
            "annotations": _thaw_structured(self.annotations),
            "defaults": _thaw_structured(self.defaults),
            "decorators": list(self.decorators),
            "contracts": _thaw_structured(self.contracts),
            "effects": list(self.effects),
            "exception_behavior": _thaw_structured(self.exception_behavior),
            "schema_relations": list(self.schema_relations),
            "serialization_relations": list(self.serialization_relations),
            "test_refs": list(self.test_refs),
            "fixture_refs": list(self.fixture_refs),
            "proof_obligation_refs": list(self.proof_obligation_refs),
            "dependency_stable_ids": list(self.dependency_stable_ids),
            "dependency_version_cids": list(self.dependency_version_cids),
            "dependency_fact_cids": list(self.dependency_fact_cids),
            "dependency_link_ids": list(self.dependency_link_ids),
            "confidence": self.confidence,
            "relevant_binding_projection_cid": self.relevant_binding_projection_cid,
            "docstring_hint": self.docstring_hint,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def capsule_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["capsule_cid"] = self.capsule_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticCapsule":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("capsule_cid")
        if payload.pop("schema") != SEMANTIC_CAPSULE_SCHEMA:
            raise SemanticStateModelError(
                "unsupported SemanticCapsule schema version"
            )
        result = cls(**payload)
        if claimed != result.capsule_cid:
            raise SemanticStateModelError(
                "SemanticCapsule capsule_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# Environment bindings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EnvironmentBinding:
    """One environment binding with stable identity and version CID."""

    binding_id: str
    kind: BindingKind | str
    version_cid: str
    scope: BindingScope | str
    extraction_authority: str
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT
    subject_id: str | None = None
    content_cid: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "binding_id",
            "kind",
            "version_cid",
            "scope",
            "extraction_authority",
            "confidence",
            "subject_id",
            "content_cid",
            "metadata",
            "record_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_id", _text(self.binding_id, "binding_id"))
        object.__setattr__(self, "kind", _enum(self.kind, BindingKind, "kind"))
        object.__setattr__(self, "version_cid", _cid(self.version_cid, "version_cid"))
        object.__setattr__(self, "scope", _enum(self.scope, BindingScope, "scope"))
        object.__setattr__(
            self,
            "extraction_authority",
            _text(self.extraction_authority, "extraction_authority"),
        )
        object.__setattr__(
            self, "confidence", _enum(self.confidence, AnalysisConfidence, "confidence")
        )
        object.__setattr__(self, "subject_id", _optional_text(self.subject_id, "subject_id"))
        object.__setattr__(self, "content_cid", _optional_cid(self.content_cid, "content_cid"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": ENVIRONMENT_BINDING_SCHEMA,
            "binding_id": self.binding_id,
            "kind": self.kind,
            "version_cid": self.version_cid,
            "scope": self.scope,
            "extraction_authority": self.extraction_authority,
            "confidence": self.confidence,
            "subject_id": self.subject_id,
            "content_cid": self.content_cid,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def record_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["record_cid"] = self.record_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EnvironmentBinding":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("record_cid")
        if payload.pop("schema") != ENVIRONMENT_BINDING_SCHEMA:
            raise SemanticStateModelError(
                "unsupported EnvironmentBinding schema version"
            )
        result = cls(**payload)
        if claimed != result.record_cid:
            raise SemanticStateModelError(
                "EnvironmentBinding record_cid does not verify"
            )
        return result


@dataclass(frozen=True, slots=True)
class EnvironmentBindingSet:
    """Complete sorted set of environment bindings for one semantic state."""

    bindings: Sequence[EnvironmentBinding] = ()

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"schema", "bindings", "binding_set_cid"}
    )

    def __post_init__(self) -> None:
        if any(not isinstance(item, EnvironmentBinding) for item in self.bindings):
            raise SemanticStateModelError("bindings must be EnvironmentBinding values")
        object.__setattr__(
            self, "bindings", _sorted_records(self.bindings, "binding_id", "bindings")
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": ENVIRONMENT_BINDING_SET_SCHEMA,
            "bindings": [item.to_dict() for item in self.bindings],
        }

    @property
    def binding_set_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["binding_set_cid"] = self.binding_set_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EnvironmentBindingSet":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("binding_set_cid")
        if payload.pop("schema") != ENVIRONMENT_BINDING_SET_SCHEMA:
            raise SemanticStateModelError(
                "unsupported EnvironmentBindingSet schema version"
            )
        bindings = tuple(
            EnvironmentBinding.from_dict(item) for item in payload["bindings"]
        )
        result = cls(bindings=bindings)
        if claimed != result.binding_set_cid:
            raise SemanticStateModelError(
                "EnvironmentBindingSet binding_set_cid does not verify"
            )
        return result


@dataclass(frozen=True, slots=True)
class RelevantBindingProjection:
    """Per-symbol projection of environment bindings relevant to a capsule."""

    stable_symbol_id: str
    binding_ids: Sequence[str] = ()
    includes_global: bool = False
    binding_set_cid: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "stable_symbol_id",
            "binding_ids",
            "includes_global",
            "binding_set_cid",
            "projection_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "stable_symbol_id", _cid(self.stable_symbol_id, "stable_symbol_id")
        )
        object.__setattr__(
            self, "binding_ids", _unique_sorted(self.binding_ids, "binding_id")
        )
        if type(self.includes_global) is not bool:
            raise SemanticStateModelError("includes_global must be a bool")
        object.__setattr__(
            self, "binding_set_cid", _optional_cid(self.binding_set_cid, "binding_set_cid")
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": RELEVANT_BINDING_PROJECTION_SCHEMA,
            "stable_symbol_id": self.stable_symbol_id,
            "binding_ids": list(self.binding_ids),
            "includes_global": self.includes_global,
            "binding_set_cid": self.binding_set_cid,
        }

    @property
    def projection_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["projection_cid"] = self.projection_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RelevantBindingProjection":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("projection_cid")
        if payload.pop("schema") != RELEVANT_BINDING_PROJECTION_SCHEMA:
            raise SemanticStateModelError(
                "unsupported RelevantBindingProjection schema version"
            )
        result = cls(**payload)
        if claimed != result.projection_cid:
            raise SemanticStateModelError(
                "RelevantBindingProjection projection_cid does not verify"
            )
        return result


@dataclass(frozen=True, slots=True)
class SemanticBindingDelta:
    """Compares environment bindings by stable ID and old/new version CIDs."""

    previous_binding_set_cid: str | None
    current_binding_set_cid: str
    added_binding_ids: Sequence[str] = ()
    deleted_binding_ids: Sequence[str] = ()
    modified_binding_ids: Sequence[str] = ()
    unchanged_binding_ids: Sequence[str] = ()
    previous_version_cids: Mapping[str, str] = field(default_factory=dict)
    current_version_cids: Mapping[str, str] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "previous_binding_set_cid",
            "current_binding_set_cid",
            "added_binding_ids",
            "deleted_binding_ids",
            "modified_binding_ids",
            "unchanged_binding_ids",
            "previous_version_cids",
            "current_version_cids",
            "delta_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "previous_binding_set_cid",
            _optional_cid(self.previous_binding_set_cid, "previous_binding_set_cid"),
        )
        object.__setattr__(
            self,
            "current_binding_set_cid",
            _cid(self.current_binding_set_cid, "current_binding_set_cid"),
        )
        for name in (
            "added_binding_ids",
            "deleted_binding_ids",
            "modified_binding_ids",
            "unchanged_binding_ids",
        ):
            object.__setattr__(self, name, _unique_sorted(getattr(self, name), name))
        prev = {
            _text(key, "previous_version_cids.key"): _cid(
                value, "previous_version_cids.value"
            )
            for key, value in dict(self.previous_version_cids).items()
        }
        curr = {
            _text(key, "current_version_cids.key"): _cid(
                value, "current_version_cids.value"
            )
            for key, value in dict(self.current_version_cids).items()
        }
        object.__setattr__(self, "previous_version_cids", MappingProxyType(dict(sorted(prev.items()))))
        object.__setattr__(self, "current_version_cids", MappingProxyType(dict(sorted(curr.items()))))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SEMANTIC_BINDING_DELTA_SCHEMA,
            "previous_binding_set_cid": self.previous_binding_set_cid,
            "current_binding_set_cid": self.current_binding_set_cid,
            "added_binding_ids": list(self.added_binding_ids),
            "deleted_binding_ids": list(self.deleted_binding_ids),
            "modified_binding_ids": list(self.modified_binding_ids),
            "unchanged_binding_ids": list(self.unchanged_binding_ids),
            "previous_version_cids": dict(self.previous_version_cids),
            "current_version_cids": dict(self.current_version_cids),
        }

    @property
    def delta_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["delta_cid"] = self.delta_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticBindingDelta":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("delta_cid")
        if payload.pop("schema") != SEMANTIC_BINDING_DELTA_SCHEMA:
            raise SemanticStateModelError(
                "unsupported SemanticBindingDelta schema version"
            )
        result = cls(**payload)
        if claimed != result.delta_cid:
            raise SemanticStateModelError(
                "SemanticBindingDelta delta_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SemanticInvalidationObligation:
    """One additive invalidation obligation (ISI-preserved or environment)."""

    subject_id: str
    reason_code: str
    remediation_kind: str
    confidence: AnalysisConfidence | str
    origin: ObligationOrigin | str = ObligationOrigin.ISI
    old_identity: str | None = None
    new_identity: str | None = None
    supporting_edge_ids: Sequence[str] = ()
    supporting_link_cids: Sequence[str] = ()
    details: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "obligation_id",
            "subject_id",
            "reason_code",
            "remediation_kind",
            "confidence",
            "origin",
            "old_identity",
            "new_identity",
            "supporting_edge_ids",
            "supporting_link_cids",
            "details",
        }
    )

    def __post_init__(self) -> None:
        for name in ("subject_id", "reason_code", "remediation_kind"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(
            self, "confidence", _enum(self.confidence, AnalysisConfidence, "confidence")
        )
        object.__setattr__(self, "origin", _enum(self.origin, ObligationOrigin, "origin"))
        object.__setattr__(
            self, "old_identity", _optional_text(self.old_identity, "old_identity")
        )
        object.__setattr__(
            self, "new_identity", _optional_text(self.new_identity, "new_identity")
        )
        object.__setattr__(
            self,
            "supporting_edge_ids",
            _unique_sorted(self.supporting_edge_ids, "supporting_edge_id"),
        )
        object.__setattr__(
            self,
            "supporting_link_cids",
            _unique_sorted_cids(self.supporting_link_cids, "supporting_link_cid"),
        )
        object.__setattr__(self, "details", _mapping(self.details, "details"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SEMANTIC_INVALIDATION_OBLIGATION_SCHEMA,
            "subject_id": self.subject_id,
            "reason_code": self.reason_code,
            "remediation_kind": self.remediation_kind,
            "confidence": self.confidence,
            "origin": self.origin,
            "old_identity": self.old_identity,
            "new_identity": self.new_identity,
            "supporting_edge_ids": list(self.supporting_edge_ids),
            "supporting_link_cids": list(self.supporting_link_cids),
            "details": _thaw_structured(self.details),
        }

    @property
    def obligation_id(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["obligation_id"] = self.obligation_id
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticInvalidationObligation":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("obligation_id")
        if payload.pop("schema") != SEMANTIC_INVALIDATION_OBLIGATION_SCHEMA:
            raise SemanticStateModelError(
                "unsupported SemanticInvalidationObligation schema version"
            )
        result = cls(**payload)
        if claimed != result.obligation_id:
            raise SemanticStateModelError(
                "SemanticInvalidationObligation obligation_id does not verify"
            )
        return result


@dataclass(frozen=True, slots=True)
class SemanticInvalidationPlan:
    """Semantic invalidation plan over previous/current state roots."""

    previous_root_cid: str | None
    current_root_cid: str
    isi_plan_cid: str | None = None
    obligations: Sequence[SemanticInvalidationObligation] = ()

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "previous_root_cid",
            "current_root_cid",
            "isi_plan_cid",
            "obligations",
            "plan_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "previous_root_cid", _optional_cid(self.previous_root_cid, "previous_root_cid")
        )
        object.__setattr__(
            self, "current_root_cid", _cid(self.current_root_cid, "current_root_cid")
        )
        object.__setattr__(
            self, "isi_plan_cid", _optional_cid(self.isi_plan_cid, "isi_plan_cid")
        )
        if any(
            not isinstance(item, SemanticInvalidationObligation)
            for item in self.obligations
        ):
            raise SemanticStateModelError(
                "obligations must be SemanticInvalidationObligation values"
            )
        object.__setattr__(
            self,
            "obligations",
            _sorted_records(self.obligations, "obligation_id", "obligations"),
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SEMANTIC_INVALIDATION_PLAN_SCHEMA,
            "previous_root_cid": self.previous_root_cid,
            "current_root_cid": self.current_root_cid,
            "isi_plan_cid": self.isi_plan_cid,
            "obligations": [item.to_dict() for item in self.obligations],
        }

    @property
    def plan_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["plan_cid"] = self.plan_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticInvalidationPlan":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("plan_cid")
        if payload.pop("schema") != SEMANTIC_INVALIDATION_PLAN_SCHEMA:
            raise SemanticStateModelError(
                "unsupported SemanticInvalidationPlan schema version"
            )
        obligations = tuple(
            SemanticInvalidationObligation.from_dict(item)
            for item in payload["obligations"]
        )
        result = cls(
            previous_root_cid=payload["previous_root_cid"],
            current_root_cid=payload["current_root_cid"],
            isi_plan_cid=payload["isi_plan_cid"],
            obligations=obligations,
        )
        if claimed != result.plan_cid:
            raise SemanticStateModelError(
                "SemanticInvalidationPlan plan_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# Freshness and source evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CapsuleFreshness:
    """Separate freshness assessment for one capsule (not a capsule field)."""

    capsule_cid: str
    root_cid: str
    capsule_schema: str
    capsule_compiler_version: str
    producer_repository_state_cid: str
    relevant_binding_projection_cid: str | None
    freshness: FreshnessState | str
    admission: AdmissionDecision | str
    applicable_obligation_ids: Sequence[str] = ()
    caveats: Sequence[str] = ()

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "capsule_cid",
            "root_cid",
            "capsule_schema",
            "capsule_compiler_version",
            "producer_repository_state_cid",
            "relevant_binding_projection_cid",
            "freshness",
            "admission",
            "applicable_obligation_ids",
            "caveats",
            "assessment_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "capsule_cid", _cid(self.capsule_cid, "capsule_cid"))
        object.__setattr__(self, "root_cid", _cid(self.root_cid, "root_cid"))
        object.__setattr__(
            self, "capsule_schema", _text(self.capsule_schema, "capsule_schema")
        )
        object.__setattr__(
            self,
            "capsule_compiler_version",
            _text(self.capsule_compiler_version, "capsule_compiler_version"),
        )
        object.__setattr__(
            self,
            "producer_repository_state_cid",
            _cid(self.producer_repository_state_cid, "producer_repository_state_cid"),
        )
        object.__setattr__(
            self,
            "relevant_binding_projection_cid",
            _optional_cid(
                self.relevant_binding_projection_cid, "relevant_binding_projection_cid"
            ),
        )
        object.__setattr__(
            self, "freshness", _enum(self.freshness, FreshnessState, "freshness")
        )
        object.__setattr__(
            self, "admission", _enum(self.admission, AdmissionDecision, "admission")
        )
        object.__setattr__(
            self,
            "applicable_obligation_ids",
            _unique_sorted(self.applicable_obligation_ids, "applicable_obligation_id"),
        )
        object.__setattr__(self, "caveats", _unique_sorted(self.caveats, "caveat"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CAPSULE_FRESHNESS_SCHEMA,
            "capsule_cid": self.capsule_cid,
            "root_cid": self.root_cid,
            "capsule_schema": self.capsule_schema,
            "capsule_compiler_version": self.capsule_compiler_version,
            "producer_repository_state_cid": self.producer_repository_state_cid,
            "relevant_binding_projection_cid": self.relevant_binding_projection_cid,
            "freshness": self.freshness,
            "admission": self.admission,
            "applicable_obligation_ids": list(self.applicable_obligation_ids),
            "caveats": list(self.caveats),
        }

    @property
    def assessment_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["assessment_cid"] = self.assessment_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CapsuleFreshness":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("assessment_cid")
        if payload.pop("schema") != CAPSULE_FRESHNESS_SCHEMA:
            raise SemanticStateModelError(
                "unsupported CapsuleFreshness schema version"
            )
        result = cls(**payload)
        if claimed != result.assessment_cid:
            raise SemanticStateModelError(
                "CapsuleFreshness assessment_cid does not verify"
            )
        return result


@dataclass(frozen=True, slots=True)
class VerifiedSourceEvidence:
    """Serializable evidence for a verified raw-source materialization.

    The authoritative raw bytes themselves are not part of this structured
    record; they retain the producer raw CID and are carried separately.
    """

    stable_symbol_id: str
    producer_state_cid: str
    source_cid: str
    source_slice_path: str
    start_offset: int
    end_offset: int
    extractor_name: str
    extractor_version: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "stable_symbol_id",
            "producer_state_cid",
            "source_cid",
            "source_slice_path",
            "start_offset",
            "end_offset",
            "extractor_name",
            "extractor_version",
            "evidence_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "stable_symbol_id", _cid(self.stable_symbol_id, "stable_symbol_id")
        )
        object.__setattr__(
            self, "producer_state_cid", _cid(self.producer_state_cid, "producer_state_cid")
        )
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(
            self, "source_slice_path", _text(self.source_slice_path, "source_slice_path")
        )
        object.__setattr__(
            self, "start_offset", _nonneg_int(self.start_offset, "start_offset")
        )
        object.__setattr__(self, "end_offset", _nonneg_int(self.end_offset, "end_offset"))
        if self.end_offset < self.start_offset:
            raise SemanticStateModelError("end_offset must not precede start_offset")
        object.__setattr__(
            self, "extractor_name", _text(self.extractor_name, "extractor_name")
        )
        object.__setattr__(
            self, "extractor_version", _text(self.extractor_version, "extractor_version")
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": VERIFIED_SOURCE_EVIDENCE_SCHEMA,
            "stable_symbol_id": self.stable_symbol_id,
            "producer_state_cid": self.producer_state_cid,
            "source_cid": self.source_cid,
            "source_slice_path": self.source_slice_path,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "extractor_name": self.extractor_name,
            "extractor_version": self.extractor_version,
        }

    @property
    def evidence_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["evidence_cid"] = self.evidence_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VerifiedSourceEvidence":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("evidence_cid")
        if payload.pop("schema") != VERIFIED_SOURCE_EVIDENCE_SCHEMA:
            raise SemanticStateModelError(
                "unsupported VerifiedSourceEvidence schema version"
            )
        result = cls(**payload)
        if claimed != result.evidence_cid:
            raise SemanticStateModelError(
                "VerifiedSourceEvidence evidence_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# Selection and oracle
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SelectionPolicy:
    """Closed policy controlling test/proof selection behavior."""

    policy_id: str
    allow_full_fallback: bool = True
    include_proofs: bool = True
    include_fixtures: bool = True
    max_selected_tests: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "policy_id",
            "allow_full_fallback",
            "include_proofs",
            "include_fixtures",
            "max_selected_tests",
            "metadata",
            "policy_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _text(self.policy_id, "policy_id"))
        for name in ("allow_full_fallback", "include_proofs", "include_fixtures"):
            if type(getattr(self, name)) is not bool:
                raise SemanticStateModelError(f"{name} must be a bool")
        if self.max_selected_tests is not None:
            object.__setattr__(
                self,
                "max_selected_tests",
                _nonneg_int(self.max_selected_tests, "max_selected_tests"),
            )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SELECTION_POLICY_SCHEMA,
            "policy_id": self.policy_id,
            "allow_full_fallback": self.allow_full_fallback,
            "include_proofs": self.include_proofs,
            "include_fixtures": self.include_fixtures,
            "max_selected_tests": self.max_selected_tests,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def policy_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["policy_cid"] = self.policy_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SelectionPolicy":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("policy_cid")
        if payload.pop("schema") != SELECTION_POLICY_SCHEMA:
            raise SemanticStateModelError(
                "unsupported SelectionPolicy schema version"
            )
        result = cls(**payload)
        if claimed != result.policy_cid:
            raise SemanticStateModelError(
                "SelectionPolicy policy_cid does not verify"
            )
        return result


@dataclass(frozen=True, slots=True)
class SelectionRule:
    """Explicit user selection rule applied after graph seeds."""

    rule_id: str
    kind: SelectionRuleKind | str
    subjects: Sequence[str] = ()
    reason: str = "explicit"

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"schema", "rule_id", "kind", "subjects", "reason", "rule_cid"}
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _text(self.rule_id, "rule_id"))
        object.__setattr__(self, "kind", _enum(self.kind, SelectionRuleKind, "kind"))
        object.__setattr__(self, "subjects", _unique_sorted(self.subjects, "subject"))
        object.__setattr__(self, "reason", _text(self.reason, "reason"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SELECTION_RULE_SCHEMA,
            "rule_id": self.rule_id,
            "kind": self.kind,
            "subjects": list(self.subjects),
            "reason": self.reason,
        }

    @property
    def rule_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["rule_cid"] = self.rule_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SelectionRule":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("rule_cid")
        if payload.pop("schema") != SELECTION_RULE_SCHEMA:
            raise SemanticStateModelError(
                "unsupported SelectionRule schema version"
            )
        result = cls(**payload)
        if claimed != result.rule_cid:
            raise SemanticStateModelError("SelectionRule rule_cid does not verify")
        return result


@dataclass(frozen=True, slots=True)
class ReasonPath:
    """Shortest selection reason path with producer edge IDs and link CIDs."""

    seed_subject_id: str
    target_node_id: str
    edge_ids: Sequence[str] = ()
    link_cids: Sequence[str] = ()
    relation_steps: Sequence[str] = ()

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "seed_subject_id",
            "target_node_id",
            "edge_ids",
            "link_cids",
            "relation_steps",
            "path_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "seed_subject_id", _text(self.seed_subject_id, "seed_subject_id")
        )
        object.__setattr__(
            self, "target_node_id", _text(self.target_node_id, "target_node_id")
        )
        object.__setattr__(
            self, "edge_ids", tuple(_text(value, "edge_id") for value in self.edge_ids)
        )
        object.__setattr__(
            self, "link_cids", tuple(_cid(value, "link_cid") for value in self.link_cids)
        )
        object.__setattr__(
            self,
            "relation_steps",
            tuple(_text(value, "relation_step") for value in self.relation_steps),
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": REASON_PATH_SCHEMA,
            "seed_subject_id": self.seed_subject_id,
            "target_node_id": self.target_node_id,
            "edge_ids": list(self.edge_ids),
            "link_cids": list(self.link_cids),
            "relation_steps": list(self.relation_steps),
        }

    @property
    def path_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["path_cid"] = self.path_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReasonPath":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("path_cid")
        if payload.pop("schema") != REASON_PATH_SCHEMA:
            raise SemanticStateModelError("unsupported ReasonPath schema version")
        result = cls(**payload)
        if claimed != result.path_cid:
            raise SemanticStateModelError("ReasonPath path_cid does not verify")
        return result


@dataclass(frozen=True, slots=True)
class TestSelection:
    """Pure selection result bound to previous/current root CIDs."""

    previous_root_cid: str | None
    current_root_cid: str
    selected_pytest_node_ids: Sequence[str] = ()
    selected_proof_ids: Sequence[str] = ()
    reason_paths: Sequence[ReasonPath] = ()
    covered_seed_obligation_ids: Sequence[str] = ()
    unresolved_obligation_ids: Sequence[str] = ()
    known_test_universe_cid: str | None = None
    known_test_universe_count: int = 0
    fallback: SelectionFallback | str = SelectionFallback.NONE
    fallback_reasons: Sequence[str] = ()
    policy_cid: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "previous_root_cid",
            "current_root_cid",
            "selected_pytest_node_ids",
            "selected_proof_ids",
            "reason_paths",
            "covered_seed_obligation_ids",
            "unresolved_obligation_ids",
            "known_test_universe_cid",
            "known_test_universe_count",
            "fallback",
            "fallback_reasons",
            "policy_cid",
            "selection_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "previous_root_cid", _optional_cid(self.previous_root_cid, "previous_root_cid")
        )
        object.__setattr__(
            self, "current_root_cid", _cid(self.current_root_cid, "current_root_cid")
        )
        object.__setattr__(
            self,
            "selected_pytest_node_ids",
            _unique_sorted(self.selected_pytest_node_ids, "selected_pytest_node_id"),
        )
        object.__setattr__(
            self,
            "selected_proof_ids",
            _unique_sorted(self.selected_proof_ids, "selected_proof_id"),
        )
        if any(not isinstance(item, ReasonPath) for item in self.reason_paths):
            raise SemanticStateModelError("reason_paths must be ReasonPath values")
        object.__setattr__(
            self, "reason_paths", _sorted_records(self.reason_paths, "path_cid", "reason_paths")
        )
        object.__setattr__(
            self,
            "covered_seed_obligation_ids",
            _unique_sorted(self.covered_seed_obligation_ids, "covered_seed_obligation_id"),
        )
        object.__setattr__(
            self,
            "unresolved_obligation_ids",
            _unique_sorted(self.unresolved_obligation_ids, "unresolved_obligation_id"),
        )
        object.__setattr__(
            self,
            "known_test_universe_cid",
            _optional_cid(self.known_test_universe_cid, "known_test_universe_cid"),
        )
        object.__setattr__(
            self,
            "known_test_universe_count",
            _nonneg_int(self.known_test_universe_count, "known_test_universe_count"),
        )
        object.__setattr__(
            self, "fallback", _enum(self.fallback, SelectionFallback, "fallback")
        )
        object.__setattr__(
            self, "fallback_reasons", _unique_sorted(self.fallback_reasons, "fallback_reason")
        )
        object.__setattr__(self, "policy_cid", _optional_cid(self.policy_cid, "policy_cid"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": TEST_SELECTION_SCHEMA,
            "previous_root_cid": self.previous_root_cid,
            "current_root_cid": self.current_root_cid,
            "selected_pytest_node_ids": list(self.selected_pytest_node_ids),
            "selected_proof_ids": list(self.selected_proof_ids),
            "reason_paths": [item.to_dict() for item in self.reason_paths],
            "covered_seed_obligation_ids": list(self.covered_seed_obligation_ids),
            "unresolved_obligation_ids": list(self.unresolved_obligation_ids),
            "known_test_universe_cid": self.known_test_universe_cid,
            "known_test_universe_count": self.known_test_universe_count,
            "fallback": self.fallback,
            "fallback_reasons": list(self.fallback_reasons),
            "policy_cid": self.policy_cid,
        }

    @property
    def selection_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["selection_cid"] = self.selection_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TestSelection":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("selection_cid")
        if payload.pop("schema") != TEST_SELECTION_SCHEMA:
            raise SemanticStateModelError(
                "unsupported TestSelection schema version"
            )
        paths = tuple(ReasonPath.from_dict(item) for item in payload.pop("reason_paths"))
        result = cls(reason_paths=paths, **payload)
        if claimed != result.selection_cid:
            raise SemanticStateModelError(
                "TestSelection selection_cid does not verify"
            )
        return result


@dataclass(frozen=True, slots=True)
class TestOutcome:
    """Normalized test outcome keyed by authoritative pytest node ID."""

    node_id: str
    status: NormalizedTestStatus | str
    failure_fingerprint: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"schema", "node_id", "status", "failure_fingerprint", "outcome_cid"}
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _text(self.node_id, "node_id"))
        object.__setattr__(
            self, "status", _enum(self.status, NormalizedTestStatus, "status")
        )
        object.__setattr__(
            self,
            "failure_fingerprint",
            _optional_text(self.failure_fingerprint, "failure_fingerprint"),
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": TEST_OUTCOME_SCHEMA,
            "node_id": self.node_id,
            "status": self.status,
            "failure_fingerprint": self.failure_fingerprint,
        }

    @property
    def outcome_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["outcome_cid"] = self.outcome_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TestOutcome":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("outcome_cid")
        if payload.pop("schema") != TEST_OUTCOME_SCHEMA:
            raise SemanticStateModelError("unsupported TestOutcome schema version")
        result = cls(**payload)
        if claimed != result.outcome_cid:
            raise SemanticStateModelError("TestOutcome outcome_cid does not verify")
        return result


@dataclass(frozen=True, slots=True)
class TestRunFacts:
    """Normalized node-ID-keyed test run facts (no execution timestamps)."""

    run_id: str
    outcomes: Sequence[TestOutcome] = ()

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"schema", "run_id", "outcomes", "facts_cid"}
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _text(self.run_id, "run_id"))
        if any(not isinstance(item, TestOutcome) for item in self.outcomes):
            raise SemanticStateModelError("outcomes must be TestOutcome values")
        object.__setattr__(
            self, "outcomes", _sorted_records(self.outcomes, "node_id", "outcomes")
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": TEST_RUN_FACTS_SCHEMA,
            "run_id": self.run_id,
            "outcomes": [item.to_dict() for item in self.outcomes],
        }

    @property
    def facts_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["facts_cid"] = self.facts_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TestRunFacts":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("facts_cid")
        if payload.pop("schema") != TEST_RUN_FACTS_SCHEMA:
            raise SemanticStateModelError(
                "unsupported TestRunFacts schema version"
            )
        outcomes = tuple(TestOutcome.from_dict(item) for item in payload["outcomes"])
        result = cls(run_id=payload["run_id"], outcomes=outcomes)
        if claimed != result.facts_cid:
            raise SemanticStateModelError("TestRunFacts facts_cid does not verify")
        return result


@dataclass(frozen=True, slots=True)
class TestOracleComparison:
    """Pure selected-versus-full oracle metrics (no fabricated 100% empty)."""

    selection_cid: str
    baseline_facts_cid: str
    selected_facts_cid: str
    candidate_full_facts_cid: str
    applicability: OracleApplicability | str
    new_regressions: Sequence[str] = ()
    missed_regressions: Sequence[str] = ()
    true_positives: Sequence[str] = ()
    false_negatives: Sequence[str] = ()
    false_positives: Sequence[str] = ()
    fixture_recall_bp: int | None = None
    fixture_precision_bp: int | None = None
    selected_count: int = 0
    full_count: int = 0
    selection_ratio_bp: int | None = None
    execution_reduction_bp: int | None = None
    fallback_rate_bp: int | None = None
    changed_outcome_node_ids: Sequence[str] = ()
    regression_recall_bp: int | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "selection_cid",
            "baseline_facts_cid",
            "selected_facts_cid",
            "candidate_full_facts_cid",
            "applicability",
            "new_regressions",
            "missed_regressions",
            "true_positives",
            "false_negatives",
            "false_positives",
            "fixture_recall_bp",
            "fixture_precision_bp",
            "selected_count",
            "full_count",
            "selection_ratio_bp",
            "execution_reduction_bp",
            "fallback_rate_bp",
            "changed_outcome_node_ids",
            "regression_recall_bp",
            "comparison_cid",
        }
    )

    def __post_init__(self) -> None:
        for name in (
            "selection_cid",
            "baseline_facts_cid",
            "selected_facts_cid",
            "candidate_full_facts_cid",
        ):
            object.__setattr__(self, name, _cid(getattr(self, name), name))
        object.__setattr__(
            self,
            "applicability",
            _enum(self.applicability, OracleApplicability, "applicability"),
        )
        for name in (
            "new_regressions",
            "missed_regressions",
            "true_positives",
            "false_negatives",
            "false_positives",
            "changed_outcome_node_ids",
        ):
            object.__setattr__(self, name, _unique_sorted(getattr(self, name), name))
        for name in (
            "fixture_recall_bp",
            "fixture_precision_bp",
            "selection_ratio_bp",
            "execution_reduction_bp",
            "fallback_rate_bp",
            "regression_recall_bp",
        ):
            object.__setattr__(
                self, name, _optional_basis_points(getattr(self, name), name)
            )
        object.__setattr__(
            self, "selected_count", _nonneg_int(self.selected_count, "selected_count")
        )
        object.__setattr__(self, "full_count", _nonneg_int(self.full_count, "full_count"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": TEST_ORACLE_COMPARISON_SCHEMA,
            "selection_cid": self.selection_cid,
            "baseline_facts_cid": self.baseline_facts_cid,
            "selected_facts_cid": self.selected_facts_cid,
            "candidate_full_facts_cid": self.candidate_full_facts_cid,
            "applicability": self.applicability,
            "new_regressions": list(self.new_regressions),
            "missed_regressions": list(self.missed_regressions),
            "true_positives": list(self.true_positives),
            "false_negatives": list(self.false_negatives),
            "false_positives": list(self.false_positives),
            "fixture_recall_bp": self.fixture_recall_bp,
            "fixture_precision_bp": self.fixture_precision_bp,
            "selected_count": self.selected_count,
            "full_count": self.full_count,
            "selection_ratio_bp": self.selection_ratio_bp,
            "execution_reduction_bp": self.execution_reduction_bp,
            "fallback_rate_bp": self.fallback_rate_bp,
            "changed_outcome_node_ids": list(self.changed_outcome_node_ids),
            "regression_recall_bp": self.regression_recall_bp,
        }

    @property
    def comparison_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["comparison_cid"] = self.comparison_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TestOracleComparison":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("comparison_cid")
        if payload.pop("schema") != TEST_ORACLE_COMPARISON_SCHEMA:
            raise SemanticStateModelError(
                "unsupported TestOracleComparison schema version"
            )
        result = cls(**payload)
        if claimed != result.comparison_cid:
            raise SemanticStateModelError(
                "TestOracleComparison comparison_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# Analysis limitations and root
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnalysisLimitation:
    """Visible analysis limitation retained as durable evidence."""

    code: str
    message: str
    subject_id: str | None = None
    confidence: AnalysisConfidence | str = AnalysisConfidence.OPAQUE

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "code",
            "message",
            "subject_id",
            "confidence",
            "limitation_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _text(self.code, "code"))
        object.__setattr__(self, "message", _text(self.message, "message"))
        object.__setattr__(
            self, "subject_id", _optional_text(self.subject_id, "subject_id")
        )
        object.__setattr__(
            self, "confidence", _enum(self.confidence, AnalysisConfidence, "confidence")
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": ANALYSIS_LIMITATION_SCHEMA,
            "code": self.code,
            "message": self.message,
            "subject_id": self.subject_id,
            "confidence": self.confidence,
        }

    @property
    def limitation_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["limitation_cid"] = self.limitation_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AnalysisLimitation":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("limitation_cid")
        if payload.pop("schema") != ANALYSIS_LIMITATION_SCHEMA:
            raise SemanticStateModelError(
                "unsupported AnalysisLimitation schema version"
            )
        result = cls(**payload)
        if claimed != result.limitation_cid:
            raise SemanticStateModelError(
                "AnalysisLimitation limitation_cid does not verify"
            )
        return result


@dataclass(frozen=True, slots=True)
class SemanticStateRoot:
    """Authoritative datasets-domain semantic-state root.

    Deliberately excludes histories, selections, receipts, clocks, local paths,
    leases, generations, model data, and MCP++ envelope identities.
    """

    repository_id: str
    producer: SemanticStateProducer
    semantic_state_schema: str = SEMANTIC_STATE_SCHEMA
    merkle_compiler_version: str = MERKLE_COMPILER_VERSION
    capsule_schema: str = SEMANTIC_CAPSULE_SCHEMA
    capsule_compiler_version: str = CAPSULE_COMPILER_VERSION
    symbol_fact_index_cid: str = ""
    artifact_fact_index_cid: str = ""
    semantic_link_index_cid: str = ""
    symbol_node_index_cid: str = ""
    capsule_index_cid: str = ""
    environment_binding_set_cid: str = ""
    analysis_limitation_index_cid: str = ""

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "repository_id",
            "producer",
            "semantic_state_schema",
            "merkle_compiler_version",
            "capsule_schema",
            "capsule_compiler_version",
            "symbol_fact_index_cid",
            "artifact_fact_index_cid",
            "semantic_link_index_cid",
            "symbol_node_index_cid",
            "capsule_index_cid",
            "environment_binding_set_cid",
            "analysis_limitation_index_cid",
            "root_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository_id", _text(self.repository_id, "repository_id"))
        if not isinstance(self.producer, SemanticStateProducer):
            raise SemanticStateModelError("producer must be a SemanticStateProducer")
        if self.semantic_state_schema != SEMANTIC_STATE_SCHEMA:
            raise SemanticStateModelError(
                "unsupported semantic_state_schema version"
            )
        if self.merkle_compiler_version != MERKLE_COMPILER_VERSION:
            raise SemanticStateModelError("unsupported merkle_compiler_version")
        if self.capsule_schema != SEMANTIC_CAPSULE_SCHEMA:
            raise SemanticStateModelError("unsupported capsule_schema version")
        if self.capsule_compiler_version != CAPSULE_COMPILER_VERSION:
            raise SemanticStateModelError("unsupported capsule_compiler_version")
        for name in (
            "symbol_fact_index_cid",
            "artifact_fact_index_cid",
            "semantic_link_index_cid",
            "symbol_node_index_cid",
            "capsule_index_cid",
            "environment_binding_set_cid",
            "analysis_limitation_index_cid",
        ):
            object.__setattr__(self, name, _cid(getattr(self, name), name))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SEMANTIC_STATE_ROOT_SCHEMA,
            "repository_id": self.repository_id,
            "producer": self.producer.to_dict(),
            "semantic_state_schema": self.semantic_state_schema,
            "merkle_compiler_version": self.merkle_compiler_version,
            "capsule_schema": self.capsule_schema,
            "capsule_compiler_version": self.capsule_compiler_version,
            "symbol_fact_index_cid": self.symbol_fact_index_cid,
            "artifact_fact_index_cid": self.artifact_fact_index_cid,
            "semantic_link_index_cid": self.semantic_link_index_cid,
            "symbol_node_index_cid": self.symbol_node_index_cid,
            "capsule_index_cid": self.capsule_index_cid,
            "environment_binding_set_cid": self.environment_binding_set_cid,
            "analysis_limitation_index_cid": self.analysis_limitation_index_cid,
        }

    @property
    def root_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["root_cid"] = self.root_cid
        # Fail closed if an excluded operational field ever appears.
        forbidden = ROOT_EXCLUDED_FIELD_NAMES.intersection(value)
        if forbidden:
            raise SemanticStateModelError(
                f"SemanticStateRoot must not contain excluded fields {sorted(forbidden)}"
            )
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticStateRoot":
        if not isinstance(data, Mapping):
            raise SemanticStateModelError("SemanticStateRoot must be a mapping")
        forbidden = ROOT_EXCLUDED_FIELD_NAMES.intersection(data)
        if forbidden:
            raise SemanticStateModelError(
                f"SemanticStateRoot rejects excluded fields {sorted(forbidden)}"
            )
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("root_cid")
        if payload.pop("schema") != SEMANTIC_STATE_ROOT_SCHEMA:
            raise SemanticStateModelError(
                "unsupported SemanticStateRoot schema version"
            )
        producer = SemanticStateProducer.from_dict(payload.pop("producer"))
        result = cls(producer=producer, **payload)
        if claimed != result.root_cid:
            raise SemanticStateModelError(
                "SemanticStateRoot root_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# Bundle (finite CID -> canonical bytes)
# ---------------------------------------------------------------------------


def verify_block_bytes(claimed_cid: str, data: bytes) -> str:
    """Reverify one bundle block against its claimed CID (raw or dag-json)."""
    if type(data) is not bytes:
        raise SemanticStateModelError("block data must be bytes")
    try:
        claimed = validate_cid(claimed_cid)
    except Exception as exc:
        raise SemanticStateModelError("block key must be a valid CID") from exc
    from multiformats import CID

    codec = CID.decode(claimed).codec.name
    if codec == "raw":
        try:
            return decode_and_recompute_source(claimed, data)
        except Exception as exc:
            raise SemanticStateModelError(
                f"forged or mismatched raw block CID {claimed}"
            ) from exc
    if codec == "dag-json":
        try:
            text = data.decode("utf-8")
            import json

            obj = json.loads(text)
            # Require exact canonical encoding, not just semantic JSON equality.
            if canonical_dag_json_bytes(obj) != data:
                raise SemanticStateModelError(
                    f"dag-json block {claimed} is not canonical"
                )
            return decode_and_recompute_structured(claimed, obj)
        except SemanticStateModelError:
            raise
        except Exception as exc:
            raise SemanticStateModelError(
                f"forged or mismatched structured block CID {claimed}"
            ) from exc
    raise SemanticStateModelError(f"unsupported block codec {codec!r}")


@dataclass(frozen=True, slots=True)
class SemanticStateBundle:
    """Verified root plus a finite mapping from CID to canonical bytes.

    Has no storage mutation methods.  Every block is rehashed on construction.
    """

    root: SemanticStateRoot
    blocks: Mapping[str, bytes] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.root, SemanticStateRoot):
            raise SemanticStateModelError("root must be a SemanticStateRoot")
        if not isinstance(self.blocks, Mapping):
            raise SemanticStateModelError("blocks must be a mapping")
        verified: dict[str, bytes] = {}
        for key, data in self.blocks.items():
            cid = verify_block_bytes(key, data)
            if cid in verified:
                raise SemanticStateModelError(
                    f"bundle blocks reject duplicate CID {cid}"
                )
            verified[cid] = data
        # Root must be present and match its content-addressed payload.
        root_bytes = canonical_dag_json_bytes(self.root.identity_payload())
        root_cid = self.root.root_cid
        if root_cid not in verified:
            verified[root_cid] = root_bytes
        else:
            try:
                decode_and_recompute_structured(
                    root_cid, self.root.identity_payload()
                )
            except Exception as exc:
                raise SemanticStateModelError(
                    "bundle root block does not match SemanticStateRoot"
                ) from exc
            if verified[root_cid] != root_bytes:
                raise SemanticStateModelError(
                    "bundle root block bytes are not canonical for root"
                )
        object.__setattr__(
            self, "blocks", MappingProxyType(dict(sorted(verified.items())))
        )

    def get_block(self, cid: str) -> bytes:
        key = _cid(cid, "cid")
        try:
            return self.blocks[key]
        except KeyError as exc:
            raise SemanticStateModelError(f"missing block {key}") from exc

    def verify(self) -> SemanticStateRoot:
        """Reverify every block and return the root."""
        for cid, data in self.blocks.items():
            verify_block_bytes(cid, data)
        root_bytes = self.get_block(self.root.root_cid)
        if root_bytes != canonical_dag_json_bytes(self.root.identity_payload()):
            raise SemanticStateModelError("root block failed reverify")
        return self.root

    def root_cid(self) -> str:
        return self.root.root_cid
