"""Narrow program-world domain adapters that never change domain identities.

This module owns the datasets ``ProgramWorldDomainAdapter@1`` and
``DomainCapabilityUnavailable@1`` contracts.  Adapters consume public
identities of currently admitted domains and return typed unavailability
everywhere else.

Authority rules (normative):

* Existing domain CIDs and ``@1`` payloads are immutable here.  Adapters cite
  those identities; they never rehash, rewrite, simulate, or reimplement a
  domain schema.
* Source authority, scope, freshness, and limitations are retained.  An
  adapter envelope is not a second semantic authority and cannot replace a
  domain identity.
* Canonical bytes / CIDv1 for adapter envelopes come only from
  ``software_contracts.content``.  Domain identities stay in the form the
  owning domain already publishes (CID or digest).
* Absent, historical, or out-of-profile domains return
  ``DomainCapabilityUnavailable@1``.  They are never filled in from similar
  types, embeddings, or reconstructed payloads.
* This module does not own VFS storage, scheduling, model invocation, mutable
  indexes, or operational transition acceptance.
* Importing this module does not import Legal/Security/Intent IR, Tactician,
  or kit VFS implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence
import re
import unicodedata

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_structured,
    decode_and_recompute_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    STATE_SCHEMA,
    RepositoryState,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    SEMANTIC_CAPSULE_SCHEMA,
    SEMANTIC_STATE_ROOT_SCHEMA,
    CapsuleFreshness,
    SemanticCapsule,
    SemanticStateBundle,
    SemanticStateRoot,
)


# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

PROGRAM_WORLD_DOMAIN_ADAPTER_INTERFACE: Final[str] = "ProgramWorldDomainAdapter@1"
DOMAIN_CAPABILITY_UNAVAILABLE_INTERFACE: Final[str] = "DomainCapabilityUnavailable@1"

PROGRAM_WORLD_DOMAIN_ADAPTER_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.program-world-domain-adapter@1"
)
DOMAIN_CAPABILITY_UNAVAILABLE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.domain-capability-unavailable@1"
)
DOMAIN_ADAPTER_SCOPE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.domain-adapter-scope@1"
)
DOMAIN_ADAPTER_FRESHNESS_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.domain-adapter-freshness@1"
)

LEGAL_IR_DOMAIN_SCHEMA: Final[str] = "legal-ir/v1"
SECURITY_IR_DOMAIN_SCHEMA: Final[str] = "security-ir/v1"
INTENT_IR_DOMAIN_SCHEMA: Final[str] = "intent-ir/v1"
PROOF_OBLIGATION_GRAPH_SCHEMA: Final[str] = (
    "ipfs_datasets_py/logic/software_verification/proof-obligation-graph@1"
)
VFS_NAMESPACE_ROUTER_SCHEMA: Final[str] = (
    "ipfs_kit_py/core/vfs/namespace/namespace-router@1"
)

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_COLLECTION_ITEMS: Final[int] = 100_000
MAX_SAFE_INTEGER: Final[int] = (1 << 53) - 1

ADMITTED_LANGUAGES: Final[tuple[str, ...]] = ("python",)
UNAVAILABLE_LANGUAGES: Final[tuple[str, ...]] = (
    "javascript",
    "typescript",
    "rust",
    "c",
    "cpp",
    "java",
    "shell",
)

_SHA256_DIGEST_RE: Final[re.Pattern[str]] = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_HEX64_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")

SOURCE_AUTHORITY_DATASETS: Final[str] = "ipfs_datasets_py"
SOURCE_AUTHORITY_KIT: Final[str] = "ipfs_kit_py"

FORBIDDEN_ADAPTER_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "ann_score",
        "api_key",
        "authorization",
        "cosine",
        "credential",
        "distance",
        "embedding",
        "embedding_score",
        "embeddings",
        "knn",
        "model",
        "model_cid",
        "nearest",
        "password",
        "private_key",
        "rank",
        "score",
        "scores",
        "secret",
        "similarity",
        "tokenizer_cid",
        "vector",
        "vector_cid",
        "vectors",
        "wall_clock",
        "payload",
        "domain_payload",
        "simulated_payload",
        "reconstructed_payload",
    }
)


class DomainAdapterError(ValueError):
    """Raised when a domain-adapter request or envelope is malformed."""


class DomainKind(str, Enum):
    REPOSITORY_SEMANTIC_STATE = "repository_semantic_state"
    SEMANTIC_CAPSULE = "semantic_capsule"
    LEGAL_IR = "legal_ir"
    SECURITY_IR = "security_ir"
    INTENT_IR = "intent_ir"
    PROOF_CONTEXT = "proof_context"
    DATASET_STATE = "dataset_state"
    VFS_NAMESPACE = "vfs_namespace"


class UnsupportedDomainKind(str, Enum):
    UI_UX_IR = "ui_ux_ir"
    E_GRAPH = "e_graph"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    RUST = "rust"
    C = "c"
    CPP = "cpp"
    JAVA = "java"
    SHELL = "shell"
    REPOSITORY_WORLD_MODEL = "repository_world_model"
    PROOF_CARRYING_PROCEDURE_COMPILER = "proof_carrying_procedure_compiler"
    VERIFIED_RESIDUAL_INTELLIGENCE_FOUNDRY = "verified_residual_intelligence_foundry"
    AUTONOMOUS_META_CONTROLLER = "autonomous_meta_controller"
    CAUSAL_ABSTRACTION_SUPERVISOR_FEDERATION = (
        "causal_abstraction_supervisor_federation"
    )
    DYNAMIC_EXECUTION_TRACE = "dynamic_execution_trace"
    ANN_INDEX = "ann_index"
    MODEL_CHECKPOINT = "model_checkpoint"


class DomainIdentityForm(str, Enum):
    CID = "cid"
    DIGEST = "digest"


class DomainAvailability(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class DomainUnavailabilityReason(str, Enum):
    UNSUPPORTED_DOMAIN = "unsupported_domain"
    MISSING_DOMAIN = "missing_domain"
    HISTORICAL_ONLY = "historical_only"
    TYPED_UNAVAILABLE = "typed_unavailable"
    SOURCE_ABSENT = "source_absent"
    LANGUAGE_UNAVAILABLE = "language_unavailable"
    FUTURE_VERSION_REQUIRED = "future_version_required"


class DomainScopeKind(str, Enum):
    REPOSITORY = "repository"
    SYMBOL = "symbol"
    DECLARATION = "declaration"
    PROOF_GRAPH = "proof_graph"
    WORLD = "world"
    NAMESPACE = "namespace"


class AdapterFreshnessState(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class ProgramLanguage(str, Enum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    RUST = "rust"
    C = "c"
    CPP = "cpp"
    JAVA = "java"
    SHELL = "shell"


ADMITTED_DOMAIN_KINDS: Final[frozenset[str]] = frozenset(item.value for item in DomainKind)
UNSUPPORTED_DOMAIN_KINDS: Final[frozenset[str]] = frozenset(
    item.value for item in UnsupportedDomainKind
)

HISTORICAL_ONLY_DOMAINS: Final[frozenset[str]] = frozenset(
    {
        UnsupportedDomainKind.REPOSITORY_WORLD_MODEL.value,
        UnsupportedDomainKind.PROOF_CARRYING_PROCEDURE_COMPILER.value,
        UnsupportedDomainKind.VERIFIED_RESIDUAL_INTELLIGENCE_FOUNDRY.value,
        UnsupportedDomainKind.AUTONOMOUS_META_CONTROLLER.value,
    }
)
LANGUAGE_UNAVAILABLE_DOMAINS: Final[frozenset[str]] = frozenset(UNAVAILABLE_LANGUAGES)
MISSING_DOMAINS: Final[frozenset[str]] = frozenset(
    {
        UnsupportedDomainKind.E_GRAPH.value,
        UnsupportedDomainKind.CAUSAL_ABSTRACTION_SUPERVISOR_FEDERATION.value,
        UnsupportedDomainKind.DYNAMIC_EXECUTION_TRACE.value,
        UnsupportedDomainKind.ANN_INDEX.value,
        UnsupportedDomainKind.MODEL_CHECKPOINT.value,
    }
)

DEFAULT_LIMITATIONS: Final[Mapping[str, tuple[str, ...]]] = {
    DomainKind.REPOSITORY_SEMANTIC_STATE.value: (
        "adapter_does_not_rescan",
        "adapter_does_not_mutate_index",
        "adapter_does_not_recompute_state_cid",
    ),
    DomainKind.SEMANTIC_CAPSULE.value: (
        "adapter_does_not_recompile_capsule",
        "adapter_does_not_recompute_capsule_cid",
        "freshness_is_separate_from_capsule_identity",
    ),
    DomainKind.LEGAL_IR.value: (
        "adapter_does_not_recompile_legal_ir",
        "adapter_does_not_replace_modal_canonical_hash",
        "embeddings_are_not_legal_identity",
        "raw_source_bodies_are_externalized",
    ),
    DomainKind.SECURITY_IR.value: (
        "adapter_does_not_decide_authorization",
        "adapter_does_not_recompute_security_ir_cid",
        "verification_results_are_not_declaration_identity",
    ),
    DomainKind.INTENT_IR.value: (
        "adapter_does_not_authorize_or_execute",
        "adapter_does_not_recompute_intent_digest",
        "embeddings_and_graphrag_are_not_intent_identity",
    ),
    DomainKind.PROOF_CONTEXT.value: (
        "adapter_does_not_claim_proof_or_completion",
        "adapter_does_not_search_or_discharge_holes",
        "adapter_does_not_recompute_proof_graph_identity",
    ),
    DomainKind.DATASET_STATE.value: (
        "adapter_does_not_recompute_root_cid",
        "operational_root_fields_remain_excluded",
        "adapter_is_not_task_completion_authority",
    ),
    DomainKind.VFS_NAMESPACE.value: (
        "adapter_does_not_own_vfs_storage",
        "adapter_does_not_mutate_namespace",
        "adapter_does_not_open_host_mounts",
        "generation_is_freshness_not_domain_identity",
    ),
}

DOMAIN_SOURCE_AUTHORITY: Final[Mapping[str, str]] = {
    DomainKind.REPOSITORY_SEMANTIC_STATE.value: SOURCE_AUTHORITY_DATASETS,
    DomainKind.SEMANTIC_CAPSULE.value: SOURCE_AUTHORITY_DATASETS,
    DomainKind.LEGAL_IR.value: SOURCE_AUTHORITY_DATASETS,
    DomainKind.SECURITY_IR.value: SOURCE_AUTHORITY_DATASETS,
    DomainKind.INTENT_IR.value: SOURCE_AUTHORITY_DATASETS,
    DomainKind.PROOF_CONTEXT.value: SOURCE_AUTHORITY_DATASETS,
    DomainKind.DATASET_STATE.value: SOURCE_AUTHORITY_DATASETS,
    DomainKind.VFS_NAMESPACE.value: SOURCE_AUTHORITY_KIT,
}

DOMAIN_SCOPE_KIND: Final[Mapping[str, str]] = {
    DomainKind.REPOSITORY_SEMANTIC_STATE.value: DomainScopeKind.REPOSITORY.value,
    DomainKind.SEMANTIC_CAPSULE.value: DomainScopeKind.SYMBOL.value,
    DomainKind.LEGAL_IR.value: DomainScopeKind.DECLARATION.value,
    DomainKind.SECURITY_IR.value: DomainScopeKind.DECLARATION.value,
    DomainKind.INTENT_IR.value: DomainScopeKind.DECLARATION.value,
    DomainKind.PROOF_CONTEXT.value: DomainScopeKind.PROOF_GRAPH.value,
    DomainKind.DATASET_STATE.value: DomainScopeKind.WORLD.value,
    DomainKind.VFS_NAMESPACE.value: DomainScopeKind.NAMESPACE.value,
}

DOMAIN_PUBLIC_SCHEMA: Final[Mapping[str, str]] = {
    DomainKind.REPOSITORY_SEMANTIC_STATE.value: STATE_SCHEMA,
    DomainKind.SEMANTIC_CAPSULE.value: SEMANTIC_CAPSULE_SCHEMA,
    DomainKind.LEGAL_IR.value: LEGAL_IR_DOMAIN_SCHEMA,
    DomainKind.SECURITY_IR.value: SECURITY_IR_DOMAIN_SCHEMA,
    DomainKind.INTENT_IR.value: INTENT_IR_DOMAIN_SCHEMA,
    DomainKind.PROOF_CONTEXT.value: PROOF_OBLIGATION_GRAPH_SCHEMA,
    DomainKind.DATASET_STATE.value: SEMANTIC_STATE_ROOT_SCHEMA,
    DomainKind.VFS_NAMESPACE.value: VFS_NAMESPACE_ROUTER_SCHEMA,
}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise DomainAdapterError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise DomainAdapterError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise DomainAdapterError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    if isinstance(value, enum_type):
        return value.value
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise DomainAdapterError(f"{name} has unsupported value {value!r}") from exc


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise DomainAdapterError(f"{name} must be a boolean")
    return value


def _nonneg_int_or_none(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise DomainAdapterError(f"{name} must be a nonnegative integer or null")
    if value > MAX_SAFE_INTEGER:
        raise DomainAdapterError(f"{name} exceeds the safe JSON integer range")
    return value


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise DomainAdapterError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _unique_sorted_texts(values: Iterable[Any], name: str) -> tuple[str, ...]:
    items = [_text(value, name) for value in values]
    if len(items) > MAX_COLLECTION_ITEMS:
        raise DomainAdapterError(f"{name} exceeds its item bound")
    ordered = tuple(sorted(items))
    if len(ordered) != len(set(ordered)):
        raise DomainAdapterError(f"{name} must not contain duplicates")
    return ordered


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise DomainAdapterError(f"{name} must be a mapping")
    actual = set(data)
    extra = actual - fields
    missing = fields - actual
    if extra:
        raise DomainAdapterError(f"{name} rejects unknown fields {sorted(extra)}")
    if missing:
        raise DomainAdapterError(f"{name} missing fields {sorted(missing)}")
    return dict(data)


def _language(value: Any, name: str = "language") -> str:
    language = _enum(value, ProgramLanguage, name)
    if language not in ADMITTED_LANGUAGES:
        raise DomainAdapterError(
            f"{name} {language!r} is typed unavailable in this profile"
        )
    return language


def _classify_identity(value: Any, name: str) -> tuple[str, str]:
    identity = _text(value, name)
    try:
        return validate_cid(identity), DomainIdentityForm.CID.value
    except Exception:
        pass
    if _SHA256_DIGEST_RE.fullmatch(identity):
        return identity, DomainIdentityForm.DIGEST.value
    raise DomainAdapterError(
        f"{name} must be a domain CID or sha256 digest, not a newly minted identity"
    )


def _verify_claimed(name: str, claimed: Any, payload: Mapping[str, Any]) -> str:
    try:
        validate_structured_value(payload)
        return decode_and_recompute_structured(claimed, dict(payload))
    except Exception as exc:
        raise DomainAdapterError(f"{name} cid does not verify") from exc


def _reject_forbidden_keys(mapping: Mapping[str, Any], name: str) -> None:
    forbidden = set(mapping) & FORBIDDEN_ADAPTER_FIELDS
    if forbidden:
        raise DomainAdapterError(
            f"{name} rejects non-identity fields {sorted(forbidden)}"
        )


def _is_type(value: object, module: str, qualname: str) -> bool:
    cls = type(value)
    return cls.__module__ == module and cls.__qualname__ == qualname


def _mapping_view(source: object, name: str) -> Mapping[str, Any] | None:
    if isinstance(source, Mapping):
        _reject_forbidden_keys(source, name)
        return source
    return None


def _attr(source: object, *names: str) -> Any:
    mapping = source if isinstance(source, Mapping) else None
    for name in names:
        if mapping is not None and name in mapping:
            value = mapping[name]
        else:
            value = getattr(source, name, None)
            if callable(value) and name in {
                "canonical_hash",
                "intent_ir_sha256",
            }:
                value = value()
        if value is not None and value != "":
            return value
    return None


def _snapshot_public_payload(source: object) -> Mapping[str, Any] | None:
    serializer = getattr(source, "to_dict", None)
    if not callable(serializer):
        return None
    payload = serializer()
    if not isinstance(payload, Mapping):
        raise DomainAdapterError("domain to_dict() must return a mapping")
    return dict(payload)


def _merge_limitations(
    domain_kind: str, extra: Iterable[str] | None
) -> tuple[str, ...]:
    seen: set[str] = set()
    merged: list[str] = []
    for item in (*(DEFAULT_LIMITATIONS[domain_kind]), *(extra or ())):
        text = _text(item, "limitation")
        if text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return tuple(sorted(merged))


def _freshness_from_capsule(assessment: CapsuleFreshness) -> tuple[str, str | None, str | None, tuple[str, ...]]:
    return (
        str(assessment.freshness),
        assessment.producer_repository_state_cid,
        assessment.assessment_cid,
        tuple(assessment.caveats),
    )


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DomainAdapterScope:
    """Exact scope retained from the source domain; unscoped adapters fail."""

    scope_kind: DomainScopeKind | str
    language: ProgramLanguage | str
    source_authority: str
    repository_id: str | None = None
    namespace_id: str | None = None
    unavailable_dimensions: Sequence[str] = ()

    SCHEMA: ClassVar[str] = DOMAIN_ADAPTER_SCOPE_SCHEMA
    CID_FIELD: ClassVar[str] = "scope_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "scope_kind",
            "language",
            "source_authority",
            "repository_id",
            "namespace_id",
            "unavailable_dimensions",
            "scope_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "scope_kind", _enum(self.scope_kind, DomainScopeKind, "scope_kind")
        )
        object.__setattr__(self, "language", _language(self.language))
        object.__setattr__(
            self, "source_authority", _text(self.source_authority, "source_authority")
        )
        if self.source_authority not in {
            SOURCE_AUTHORITY_DATASETS,
            SOURCE_AUTHORITY_KIT,
        }:
            raise DomainAdapterError(
                f"source_authority {self.source_authority!r} is not admitted"
            )
        object.__setattr__(
            self, "repository_id", _optional_text(self.repository_id, "repository_id")
        )
        object.__setattr__(
            self, "namespace_id", _optional_text(self.namespace_id, "namespace_id")
        )
        object.__setattr__(
            self,
            "unavailable_dimensions",
            _unique_sorted_texts(
                self.unavailable_dimensions, "unavailable_dimension"
            ),
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "scope_kind": self.scope_kind,
            "language": self.language,
            "source_authority": self.source_authority,
            "repository_id": self.repository_id,
            "namespace_id": self.namespace_id,
            "unavailable_dimensions": list(self.unavailable_dimensions),
        }

    @property
    def scope_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["scope_cid"] = self.scope_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DomainAdapterScope":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("scope_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise DomainAdapterError("unsupported DomainAdapterScope schema version")
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


@dataclass(frozen=True, slots=True)
class DomainAdapterFreshness:
    """Freshness retained beside the immutable domain identity."""

    state: AdapterFreshnessState | str
    producer_state_cid: str | None = None
    assessment_cid: str | None = None
    generation: int | None = None
    caveats: Sequence[str] = ()

    SCHEMA: ClassVar[str] = DOMAIN_ADAPTER_FRESHNESS_SCHEMA
    CID_FIELD: ClassVar[str] = "freshness_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "state",
            "producer_state_cid",
            "assessment_cid",
            "generation",
            "caveats",
            "freshness_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "state", _enum(self.state, AdapterFreshnessState, "state")
        )
        object.__setattr__(
            self,
            "producer_state_cid",
            _optional_cid(self.producer_state_cid, "producer_state_cid"),
        )
        object.__setattr__(
            self,
            "assessment_cid",
            _optional_cid(self.assessment_cid, "assessment_cid"),
        )
        object.__setattr__(
            self, "generation", _nonneg_int_or_none(self.generation, "generation")
        )
        object.__setattr__(self, "caveats", _unique_sorted_texts(self.caveats, "caveat"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "state": self.state,
            "producer_state_cid": self.producer_state_cid,
            "assessment_cid": self.assessment_cid,
            "generation": self.generation,
            "caveats": list(self.caveats),
        }

    @property
    def freshness_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["freshness_cid"] = self.freshness_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DomainAdapterFreshness":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("freshness_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise DomainAdapterError(
                "unsupported DomainAdapterFreshness schema version"
            )
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


@dataclass(frozen=True, slots=True)
class ProgramWorldDomainAdapter:
    """Typed citation of one admitted domain identity.

    The adapter CID identifies this envelope.  It is never a replacement for
    ``domain_identity``, which is copied verbatim from the owning domain.
    """

    domain_kind: DomainKind | str
    domain_identity: str
    domain_identity_form: DomainIdentityForm | str
    domain_schema: str
    scope: DomainAdapterScope
    freshness: DomainAdapterFreshness
    limitations: Sequence[str] = ()
    retains_domain_authority: bool = True
    adapter_may_replace_domain_identity: bool = False
    availability: DomainAvailability | str = DomainAvailability.AVAILABLE

    SCHEMA: ClassVar[str] = PROGRAM_WORLD_DOMAIN_ADAPTER_SCHEMA
    INTERFACE: ClassVar[str] = PROGRAM_WORLD_DOMAIN_ADAPTER_INTERFACE
    CID_FIELD: ClassVar[str] = "adapter_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "domain_kind",
            "domain_identity",
            "domain_identity_form",
            "domain_schema",
            "scope",
            "freshness",
            "limitations",
            "retains_domain_authority",
            "adapter_may_replace_domain_identity",
            "availability",
            "adapter_cid",
        }
    )

    def __post_init__(self) -> None:
        kind = _enum(self.domain_kind, DomainKind, "domain_kind")
        if kind not in ADMITTED_DOMAIN_KINDS:
            raise DomainAdapterError(
                f"domain_kind {kind!r} is not admitted; return typed unavailability"
            )
        identity, form = _classify_identity(self.domain_identity, "domain_identity")
        declared_form = _enum(
            self.domain_identity_form, DomainIdentityForm, "domain_identity_form"
        )
        if declared_form != form:
            raise DomainAdapterError(
                "domain_identity_form does not match the retained domain identity"
            )
        object.__setattr__(self, "domain_kind", kind)
        object.__setattr__(self, "domain_identity", identity)
        object.__setattr__(self, "domain_identity_form", form)
        object.__setattr__(self, "domain_schema", _text(self.domain_schema, "domain_schema"))
        if not isinstance(self.scope, DomainAdapterScope):
            raise DomainAdapterError("scope must be a DomainAdapterScope")
        expected_authority = DOMAIN_SOURCE_AUTHORITY[kind]
        if self.scope.source_authority != expected_authority:
            raise DomainAdapterError(
                "scope source_authority does not match the admitted domain owner"
            )
        if self.scope.scope_kind != DOMAIN_SCOPE_KIND[kind]:
            raise DomainAdapterError("scope_kind does not match the admitted domain")
        if not isinstance(self.freshness, DomainAdapterFreshness):
            raise DomainAdapterError("freshness must be a DomainAdapterFreshness")
        object.__setattr__(
            self, "limitations", _merge_limitations(kind, self.limitations)
        )
        if not _bool(self.retains_domain_authority, "retains_domain_authority"):
            raise DomainAdapterError("adapters must retain source domain authority")
        if _bool(
            self.adapter_may_replace_domain_identity,
            "adapter_may_replace_domain_identity",
        ):
            raise DomainAdapterError("adapters may not replace domain identities")
        availability = _enum(self.availability, DomainAvailability, "availability")
        if availability != DomainAvailability.AVAILABLE.value:
            raise DomainAdapterError(
                "ProgramWorldDomainAdapter is only for available domains"
            )
        object.__setattr__(self, "availability", availability)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "interface": self.INTERFACE,
            "domain_kind": self.domain_kind,
            "domain_identity": self.domain_identity,
            "domain_identity_form": self.domain_identity_form,
            "domain_schema": self.domain_schema,
            "scope": self.scope.identity_payload(),
            "freshness": self.freshness.identity_payload(),
            "limitations": list(self.limitations),
            "retains_domain_authority": self.retains_domain_authority,
            "adapter_may_replace_domain_identity": (
                self.adapter_may_replace_domain_identity
            ),
            "availability": self.availability,
        }

    @property
    def adapter_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["adapter_cid"] = self.adapter_cid
        value["scope"] = self.scope.to_dict()
        value["freshness"] = self.freshness.to_dict()
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProgramWorldDomainAdapter":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("adapter_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise DomainAdapterError(
                "unsupported ProgramWorldDomainAdapter schema version"
            )
        if payload.pop("interface") != cls.INTERFACE:
            raise DomainAdapterError(
                "unsupported ProgramWorldDomainAdapter interface version"
            )
        payload["scope"] = DomainAdapterScope.from_dict(payload["scope"])
        payload["freshness"] = DomainAdapterFreshness.from_dict(payload["freshness"])
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


@dataclass(frozen=True, slots=True)
class DomainCapabilityUnavailable:
    """Typed unavailability for a domain that must not be simulated."""

    domain_kind: str
    reason: DomainUnavailabilityReason | str
    limitations: Sequence[str] = ()
    source_authority: str | None = None
    evidence: str = "domain is not adapted in ProgramWorldDomainAdapter@1"
    availability: DomainAvailability | str = DomainAvailability.UNAVAILABLE

    SCHEMA: ClassVar[str] = DOMAIN_CAPABILITY_UNAVAILABLE_SCHEMA
    INTERFACE: ClassVar[str] = DOMAIN_CAPABILITY_UNAVAILABLE_INTERFACE
    CID_FIELD: ClassVar[str] = "unavailable_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface",
            "domain_kind",
            "reason",
            "limitations",
            "source_authority",
            "evidence",
            "availability",
            "unavailable_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "domain_kind", _text(self.domain_kind, "domain_kind"))
        if self.domain_kind in ADMITTED_DOMAIN_KINDS and self.reason not in {
            DomainUnavailabilityReason.SOURCE_ABSENT,
            DomainUnavailabilityReason.SOURCE_ABSENT.value,
        }:
            # Admitted domains may only be unavailable when the source is absent.
            reason = _enum(self.reason, DomainUnavailabilityReason, "reason")
            if reason != DomainUnavailabilityReason.SOURCE_ABSENT.value:
                raise DomainAdapterError(
                    "admitted domains cannot be marked missing or historical"
                )
        object.__setattr__(
            self, "reason", _enum(self.reason, DomainUnavailabilityReason, "reason")
        )
        object.__setattr__(
            self, "limitations", _unique_sorted_texts(self.limitations, "limitation")
        )
        object.__setattr__(
            self,
            "source_authority",
            _optional_text(self.source_authority, "source_authority"),
        )
        object.__setattr__(self, "evidence", _text(self.evidence, "evidence"))
        availability = _enum(self.availability, DomainAvailability, "availability")
        if availability != DomainAvailability.UNAVAILABLE.value:
            raise DomainAdapterError(
                "DomainCapabilityUnavailable must remain unavailable"
            )
        object.__setattr__(self, "availability", availability)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "interface": self.INTERFACE,
            "domain_kind": self.domain_kind,
            "reason": self.reason,
            "limitations": list(self.limitations),
            "source_authority": self.source_authority,
            "evidence": self.evidence,
            "availability": self.availability,
        }

    @property
    def unavailable_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["unavailable_cid"] = self.unavailable_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DomainCapabilityUnavailable":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("unavailable_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise DomainAdapterError(
                "unsupported DomainCapabilityUnavailable schema version"
            )
        if payload.pop("interface") != cls.INTERFACE:
            raise DomainAdapterError(
                "unsupported DomainCapabilityUnavailable interface version"
            )
        result = cls(**payload)
        _verify_claimed(cls.__name__, claimed, result.identity_payload())
        return result


def unavailable_domain(
    domain_kind: str,
    *,
    reason: str | None = None,
    evidence: str | None = None,
) -> DomainCapabilityUnavailable:
    """Return typed unavailability without simulating the named domain."""

    kind = _text(domain_kind, "domain_kind")
    if kind in ADMITTED_DOMAIN_KINDS:
        resolved_reason = reason or DomainUnavailabilityReason.SOURCE_ABSENT.value
        limitations = (
            "source_absent",
            "absent_domains_are_never_simulated",
        )
        authority = DOMAIN_SOURCE_AUTHORITY[kind]
    elif kind in HISTORICAL_ONLY_DOMAINS:
        resolved_reason = reason or DomainUnavailabilityReason.HISTORICAL_ONLY.value
        limitations = (
            "historical_worktree_is_not_current_authority",
            "absent_domains_are_never_simulated",
        )
        authority = None
    elif kind in LANGUAGE_UNAVAILABLE_DOMAINS:
        resolved_reason = (
            reason or DomainUnavailabilityReason.LANGUAGE_UNAVAILABLE.value
        )
        limitations = (
            "language_typed_unavailable_in_python_profile",
            "absent_domains_are_never_simulated",
        )
        authority = None
    elif kind in MISSING_DOMAINS or kind in UNSUPPORTED_DOMAIN_KINDS:
        resolved_reason = reason or (
            DomainUnavailabilityReason.MISSING_DOMAIN.value
            if kind in MISSING_DOMAINS
            else DomainUnavailabilityReason.UNSUPPORTED_DOMAIN.value
        )
        limitations = (
            "future_domain_support_requires_versioned_successor",
            "absent_domains_are_never_simulated",
        )
        authority = None
    else:
        resolved_reason = reason or DomainUnavailabilityReason.UNSUPPORTED_DOMAIN.value
        limitations = (
            "unknown_domain_is_typed_unavailable",
            "absent_domains_are_never_simulated",
        )
        authority = None
    return DomainCapabilityUnavailable(
        domain_kind=kind,
        reason=resolved_reason,
        limitations=limitations,
        source_authority=authority,
        evidence=evidence
        or (
            f"domain {kind!r} is not an admitted ProgramWorldDomainAdapter@1 source"
        ),
    )


def _build_adapter(
    *,
    domain_kind: str,
    domain_identity: str,
    domain_schema: str | None,
    repository_id: str | None,
    namespace_id: str | None,
    limitations: Iterable[str] | None,
    freshness: DomainAdapterFreshness,
    unavailable_dimensions: Sequence[str] = (),
    language: str = ProgramLanguage.PYTHON.value,
) -> ProgramWorldDomainAdapter:
    identity, form = _classify_identity(domain_identity, "domain_identity")
    scope = DomainAdapterScope(
        scope_kind=DOMAIN_SCOPE_KIND[domain_kind],
        language=language,
        source_authority=DOMAIN_SOURCE_AUTHORITY[domain_kind],
        repository_id=repository_id,
        namespace_id=namespace_id,
        unavailable_dimensions=unavailable_dimensions,
    )
    return ProgramWorldDomainAdapter(
        domain_kind=domain_kind,
        domain_identity=identity,
        domain_identity_form=form,
        domain_schema=domain_schema or DOMAIN_PUBLIC_SCHEMA[domain_kind],
        scope=scope,
        freshness=freshness,
        limitations=_merge_limitations(domain_kind, limitations),
    )


def _freshness_from_source(
    source: object,
    *,
    default_state: str = AdapterFreshnessState.UNKNOWN.value,
    assessment: CapsuleFreshness | None = None,
) -> DomainAdapterFreshness:
    if assessment is not None:
        state, producer, assessment_cid, caveats = _freshness_from_capsule(assessment)
        return DomainAdapterFreshness(
            state=state,
            producer_state_cid=producer,
            assessment_cid=assessment_cid,
            caveats=caveats,
        )
    mapping = _mapping_view(source, "source") if isinstance(source, Mapping) else None
    if mapping is not None:
        freshness_value = mapping.get("freshness")
        if isinstance(freshness_value, Mapping):
            return DomainAdapterFreshness(
                state=freshness_value.get("state", default_state),
                producer_state_cid=freshness_value.get("producer_state_cid"),
                assessment_cid=freshness_value.get("assessment_cid"),
                generation=freshness_value.get("generation"),
                caveats=tuple(freshness_value.get("caveats") or ()),
            )
        return DomainAdapterFreshness(
            state=mapping.get("freshness", default_state),
            producer_state_cid=mapping.get("producer_state_cid"),
            assessment_cid=mapping.get("assessment_cid")
            or mapping.get("freshness_assessment_cid"),
            generation=mapping.get("generation"),
            caveats=tuple(mapping.get("caveats") or ()),
        )
    return DomainAdapterFreshness(state=default_state)


def _require_source(source: object, domain_kind: str) -> object | DomainCapabilityUnavailable:
    if source is None:
        return unavailable_domain(
            domain_kind,
            reason=DomainUnavailabilityReason.SOURCE_ABSENT.value,
            evidence=f"{domain_kind} source is absent; adapters do not simulate it",
        )
    return source


def _limitations_from_source(source: object) -> tuple[str, ...] | None:
    value = _attr(source, "limitations")
    if value is None:
        return None
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise DomainAdapterError("limitations must be a sequence of strings")
    return tuple(value)


# ---------------------------------------------------------------------------
# Domain adapters (pure; consume public identities only)
# ---------------------------------------------------------------------------


class _DomainAdapter:
    domain_kind: ClassVar[str]

    def adapt(
        self, source: object | None, /, **kwargs: Any
    ) -> ProgramWorldDomainAdapter | DomainCapabilityUnavailable:
        raise NotImplementedError


class RepositorySemanticStateAdapter(_DomainAdapter):
    """Cite ``RepositoryState.state_cid`` without rebuilding the index."""

    domain_kind: ClassVar[str] = DomainKind.REPOSITORY_SEMANTIC_STATE.value

    def adapt(
        self,
        source: object | None,
        /,
        **kwargs: Any,
    ) -> ProgramWorldDomainAdapter | DomainCapabilityUnavailable:
        required = _require_source(source, self.domain_kind)
        if isinstance(required, DomainCapabilityUnavailable):
            return required
        source = required
        if isinstance(source, RepositoryState):
            identity = source.state_cid
            # identity_payload schema is STATE_SCHEMA; to_dict()["schema"] is not.
            identity_payload = source.identity_payload()
            schema = identity_payload.get("schema") or STATE_SCHEMA
            repository_id = source.repository_id
        else:
            mapping = _mapping_view(source, "repository_state")
            if mapping is None and not hasattr(source, "state_cid"):
                raise DomainAdapterError(
                    "RepositorySemanticStateAdapter requires RepositoryState "
                    "or a public state_cid identity view"
                )
            identity = _attr(source, "state_cid", "domain_identity")
            schema = (
                _attr(source, "identity_schema", "domain_schema") or STATE_SCHEMA
            )
            repository_id = _attr(source, "repository_id")
            if identity is None:
                raise DomainAdapterError(
                    "repository semantic state is missing its public state_cid"
                )
        return _build_adapter(
            domain_kind=self.domain_kind,
            domain_identity=identity,
            domain_schema=schema,
            repository_id=repository_id,
            namespace_id=None,
            limitations=_limitations_from_source(source),
            freshness=_freshness_from_source(source),
        )


class SemanticCapsuleAdapter(_DomainAdapter):
    """Cite ``SemanticCapsule.capsule_cid``; freshness stays a separate fact."""

    domain_kind: ClassVar[str] = DomainKind.SEMANTIC_CAPSULE.value

    def adapt(
        self,
        source: object | None,
        /,
        freshness: CapsuleFreshness | None = None,
        **kwargs: Any,
    ) -> ProgramWorldDomainAdapter | DomainCapabilityUnavailable:
        required = _require_source(source, self.domain_kind)
        if isinstance(required, DomainCapabilityUnavailable):
            return required
        source = required
        if isinstance(source, SemanticCapsule):
            identity = source.capsule_cid
            schema = source.capsule_schema
            repository_id = None
        else:
            if not isinstance(source, Mapping) and not hasattr(source, "capsule_cid"):
                raise DomainAdapterError(
                    "SemanticCapsuleAdapter requires SemanticCapsule "
                    "or a public capsule_cid identity view"
                )
            identity = _attr(source, "capsule_cid", "domain_identity")
            schema = _attr(source, "capsule_schema", "domain_schema") or SEMANTIC_CAPSULE_SCHEMA
            repository_id = _attr(source, "repository_id")
            if identity is None:
                raise DomainAdapterError("semantic capsule is missing its public capsule_cid")
        if freshness is None and isinstance(source, Mapping):
            raw = source.get("freshness_assessment")
            if isinstance(raw, CapsuleFreshness):
                freshness = raw
        return _build_adapter(
            domain_kind=self.domain_kind,
            domain_identity=identity,
            domain_schema=schema,
            repository_id=repository_id,
            namespace_id=None,
            limitations=_limitations_from_source(source),
            freshness=_freshness_from_source(source, assessment=freshness),
        )


class LegalIRAdapter(_DomainAdapter):
    """Cite Legal IR ``canonical_hash`` / declaration digest without rewriting it.

    This class is the SAWM program-world adapter.  It does not replace
    ``legal_ir.adapter.LegalIRAdapter`` and never recompiles Modal IR.
    """

    domain_kind: ClassVar[str] = DomainKind.LEGAL_IR.value

    def adapt(
        self,
        source: object | None,
        /,
        **kwargs: Any,
    ) -> ProgramWorldDomainAdapter | DomainCapabilityUnavailable:
        required = _require_source(source, self.domain_kind)
        if isinstance(required, DomainCapabilityUnavailable):
            return required
        source = required
        identity = _attr(
            source,
            "declaration_digest",
            "legacy_output_identity",
            "legacy_modal_ir_canonical_hash",
            "canonical_hash",
            "domain_identity",
        )
        if identity is None:
            raise DomainAdapterError(
                "Legal IR source is missing its public canonical_hash/declaration_digest"
            )
        identity_text = _text(identity, "legal_ir_identity")
        schema = (
            _attr(source, "schema_version", "domain_schema", "schema")
            or LEGAL_IR_DOMAIN_SCHEMA
        )
        return _build_adapter(
            domain_kind=self.domain_kind,
            domain_identity=identity_text,
            domain_schema=schema,
            repository_id=_attr(source, "repository_id"),
            namespace_id=None,
            limitations=_limitations_from_source(source),
            freshness=_freshness_from_source(source),
        )


class SecurityIRAdapter(_DomainAdapter):
    """Cite ``SecurityIR.cid`` without deciding authorization."""

    domain_kind: ClassVar[str] = DomainKind.SECURITY_IR.value

    def adapt(
        self,
        source: object | None,
        /,
        **kwargs: Any,
    ) -> ProgramWorldDomainAdapter | DomainCapabilityUnavailable:
        required = _require_source(source, self.domain_kind)
        if isinstance(required, DomainCapabilityUnavailable):
            return required
        source = required
        if not (
            isinstance(source, Mapping)
            or _is_type(
                source, "ipfs_datasets_py.logic.security_ir.model", "SecurityIR"
            )
            or hasattr(source, "cid")
        ):
            raise DomainAdapterError(
                "SecurityIRAdapter requires SecurityIR or a public cid identity view"
            )
        identity = _attr(source, "cid", "domain_identity")
        if identity is None:
            identity_obj = getattr(source, "identity", None)
            identity = getattr(identity_obj, "cid", None) if identity_obj is not None else None
        if identity is None:
            raise DomainAdapterError("Security IR source is missing its public cid")
        schema = (
            _attr(source, "schema_version", "domain_schema") or SECURITY_IR_DOMAIN_SCHEMA
        )
        return _build_adapter(
            domain_kind=self.domain_kind,
            domain_identity=identity,
            domain_schema=schema,
            repository_id=_attr(source, "repository_id"),
            namespace_id=None,
            limitations=_limitations_from_source(source),
            freshness=_freshness_from_source(source),
        )


class IntentIRAdapter(_DomainAdapter):
    """Cite ``intent_ir_sha256`` without executing or authorizing the skill."""

    domain_kind: ClassVar[str] = DomainKind.INTENT_IR.value

    def adapt(
        self,
        source: object | None,
        /,
        **kwargs: Any,
    ) -> ProgramWorldDomainAdapter | DomainCapabilityUnavailable:
        required = _require_source(source, self.domain_kind)
        if isinstance(required, DomainCapabilityUnavailable):
            return required
        source = required
        identity = _attr(source, "intent_ir_sha256", "domain_identity", "digest")
        if identity is None and _is_type(
            source, "ipfs_datasets_py.logic.intent_ir.schema", "IntentIRDocument"
        ):
            from ipfs_datasets_py.logic.intent_ir.canonicalize import intent_ir_sha256

            identity = intent_ir_sha256(source)
        if identity is None:
            raise DomainAdapterError(
                "Intent IR source is missing its public intent_ir_sha256 digest"
            )
        schema = (
            _attr(source, "schema_version", "domain_schema") or INTENT_IR_DOMAIN_SCHEMA
        )
        return _build_adapter(
            domain_kind=self.domain_kind,
            domain_identity=identity,
            domain_schema=schema,
            repository_id=_attr(source, "repository_id"),
            namespace_id=None,
            limitations=_limitations_from_source(source),
            freshness=_freshness_from_source(source),
        )


class ProofContextAdapter(_DomainAdapter):
    """Cite a proof-obligation graph identity without claiming proof."""

    domain_kind: ClassVar[str] = DomainKind.PROOF_CONTEXT.value

    def adapt(
        self,
        source: object | None,
        /,
        **kwargs: Any,
    ) -> ProgramWorldDomainAdapter | DomainCapabilityUnavailable:
        required = _require_source(source, self.domain_kind)
        if isinstance(required, DomainCapabilityUnavailable):
            return required
        source = required
        if not (
            isinstance(source, Mapping)
            or _is_type(
                source,
                "ipfs_datasets_py.logic.software_verification.tactician.contracts",
                "ProofObligationGraph",
            )
            or hasattr(source, "content_id")
        ):
            raise DomainAdapterError(
                "ProofContextAdapter requires ProofObligationGraph "
                "or a public content_id identity view"
            )
        identity = _attr(source, "content_id", "identity", "domain_identity")
        if identity is None:
            raise DomainAdapterError(
                "proof context is missing its public content_id identity"
            )
        schema = (
            _attr(source, "SCHEMA", "schema", "domain_schema")
            or PROOF_OBLIGATION_GRAPH_SCHEMA
        )
        claimed_proof = _attr(source, "proof_claimed")
        claimed_completion = _attr(source, "completion_claimed")
        if claimed_proof is True or claimed_completion is True:
            raise DomainAdapterError(
                "proof context adapters cannot accept claimed proof or completion"
            )
        extra = _limitations_from_source(source)
        return _build_adapter(
            domain_kind=self.domain_kind,
            domain_identity=identity,
            domain_schema=schema,
            repository_id=_attr(source, "repository_id"),
            namespace_id=None,
            limitations=extra,
            freshness=_freshness_from_source(source),
        )


class DatasetStateAdapter(_DomainAdapter):
    """Cite ``SemanticStateRoot.root_cid`` without operational root fields."""

    domain_kind: ClassVar[str] = DomainKind.DATASET_STATE.value

    def adapt(
        self,
        source: object | None,
        /,
        **kwargs: Any,
    ) -> ProgramWorldDomainAdapter | DomainCapabilityUnavailable:
        required = _require_source(source, self.domain_kind)
        if isinstance(required, DomainCapabilityUnavailable):
            return required
        source = required
        if isinstance(source, SemanticStateBundle):
            root = source.root
            identity = root.root_cid
            schema = SEMANTIC_STATE_ROOT_SCHEMA
            repository_id = root.repository_id
        elif isinstance(source, SemanticStateRoot):
            identity = source.root_cid
            schema = SEMANTIC_STATE_ROOT_SCHEMA
            repository_id = source.repository_id
        else:
            if not isinstance(source, Mapping) and not hasattr(source, "root_cid"):
                raise DomainAdapterError(
                    "DatasetStateAdapter requires SemanticStateRoot/Bundle "
                    "or a public root_cid identity view"
                )
            identity = _attr(source, "root_cid", "domain_identity")
            schema = (
                _attr(source, "semantic_state_schema", "domain_schema")
                or SEMANTIC_STATE_ROOT_SCHEMA
            )
            repository_id = _attr(source, "repository_id")
            if identity is None:
                raise DomainAdapterError(
                    "dataset state is missing its public root_cid"
                )
        return _build_adapter(
            domain_kind=self.domain_kind,
            domain_identity=identity,
            domain_schema=schema,
            repository_id=repository_id,
            namespace_id=None,
            limitations=_limitations_from_source(source),
            freshness=_freshness_from_source(source),
        )


class VFSNamespaceAdapter(_DomainAdapter):
    """Cite a kit VFS namespace snapshot identity without owning storage."""

    domain_kind: ClassVar[str] = DomainKind.VFS_NAMESPACE.value

    def adapt(
        self,
        source: object | None,
        /,
        **kwargs: Any,
    ) -> ProgramWorldDomainAdapter | DomainCapabilityUnavailable:
        required = _require_source(source, self.domain_kind)
        if isinstance(required, DomainCapabilityUnavailable):
            return required
        source = required
        if not isinstance(source, Mapping) and not hasattr(source, "namespace_id"):
            raise DomainAdapterError(
                "VFSNamespaceAdapter requires a public namespace identity reference"
            )
        # Never call mutation / open / mount methods on a live VFS object.
        for banned in (
            "put",
            "mkdir",
            "unlink",
            "rename",
            "mount",
            "open",
            "write",
            "create",
        ):
            method = getattr(source, banned, None)
            if callable(method) and not isinstance(source, Mapping):
                raise DomainAdapterError(
                    "VFSNamespaceAdapter refuses live VFS mutation surfaces; "
                    "pass a namespace identity reference"
                )
        identity = _attr(
            source,
            "snapshot_cid",
            "snapshot_identity",
            "namespace_snapshot_cid",
            "domain_identity",
        )
        if identity is None:
            raise DomainAdapterError(
                "VFS namespace reference is missing its public snapshot identity"
            )
        schema = (
            _attr(source, "schema", "domain_schema") or VFS_NAMESPACE_ROUTER_SCHEMA
        )
        namespace_id = _attr(source, "namespace_id")
        generation = _attr(source, "generation", "namespace_generation")
        freshness = _freshness_from_source(source)
        if generation is not None and freshness.generation is None:
            freshness = DomainAdapterFreshness(
                state=freshness.state,
                producer_state_cid=freshness.producer_state_cid,
                assessment_cid=freshness.assessment_cid,
                generation=generation,
                caveats=freshness.caveats,
            )
        return _build_adapter(
            domain_kind=self.domain_kind,
            domain_identity=identity,
            domain_schema=schema,
            repository_id=_attr(source, "repository_id"),
            namespace_id=namespace_id,
            limitations=_limitations_from_source(source),
            freshness=freshness,
        )


ADMITTED_ADAPTERS: Final[Mapping[str, type[_DomainAdapter]]] = {
    DomainKind.REPOSITORY_SEMANTIC_STATE.value: RepositorySemanticStateAdapter,
    DomainKind.SEMANTIC_CAPSULE.value: SemanticCapsuleAdapter,
    DomainKind.LEGAL_IR.value: LegalIRAdapter,
    DomainKind.SECURITY_IR.value: SecurityIRAdapter,
    DomainKind.INTENT_IR.value: IntentIRAdapter,
    DomainKind.PROOF_CONTEXT.value: ProofContextAdapter,
    DomainKind.DATASET_STATE.value: DatasetStateAdapter,
    DomainKind.VFS_NAMESPACE.value: VFSNamespaceAdapter,
}


def adapter_for(domain_kind: str) -> _DomainAdapter | None:
    """Return the admitted adapter class instance, or ``None`` if unsupported."""

    kind = _text(domain_kind, "domain_kind")
    adapter_type = ADMITTED_ADAPTERS.get(kind)
    if adapter_type is None:
        return None
    return adapter_type()


def adapt_program_world_domain(
    domain_kind: str,
    source: object | None = None,
    /,
    **kwargs: Any,
) -> ProgramWorldDomainAdapter | DomainCapabilityUnavailable:
    """Adapt one domain by kind.  Unsupported kinds never inspect ``source``."""

    kind = _text(domain_kind, "domain_kind")
    if kind not in ADMITTED_DOMAIN_KINDS:
        return unavailable_domain(kind)
    adapter = adapter_for(kind)
    assert adapter is not None
    return adapter.adapt(source, **kwargs)


def domain_identity_preserved(
    source: object,
    adapted: ProgramWorldDomainAdapter,
    *,
    before_payload: Mapping[str, Any] | None = None,
    before_identity: str | None = None,
) -> bool:
    """Return True when the source identity and ``@1`` payload did not change."""

    if not isinstance(adapted, ProgramWorldDomainAdapter):
        return False
    if not adapted.retains_domain_authority:
        return False
    if adapted.adapter_may_replace_domain_identity:
        return False
    if adapted.adapter_cid == adapted.domain_identity:
        return False
    current_payload = _snapshot_public_payload(source)
    if before_payload is not None:
        if current_payload != dict(before_payload):
            return False
    identity_fn = getattr(source, "identity_payload", None)
    if callable(identity_fn):
        live_identity_payload = identity_fn()
        if isinstance(live_identity_payload, Mapping):
            schema = live_identity_payload.get("schema")
            if isinstance(schema, str) and schema and adapted.domain_schema != schema:
                return False
    if before_identity is not None:
        current_identity, _form = _classify_identity(
            before_identity, "before_identity"
        )
        live = _attr(
            source,
            "state_cid",
            "capsule_cid",
            "root_cid",
            "cid",
            "content_id",
            "declaration_digest",
            "canonical_hash",
            "intent_ir_sha256",
            "snapshot_cid",
            "domain_identity",
        )
        if live is not None:
            live_identity, _live_form = _classify_identity(live, "live_identity")
            if live_identity != current_identity:
                return False
        if adapted.domain_identity != current_identity:
            return False
    return True


__all__ = [
    "ADMITTED_ADAPTERS",
    "ADMITTED_DOMAIN_KINDS",
    "DOMAIN_CAPABILITY_UNAVAILABLE_INTERFACE",
    "DOMAIN_CAPABILITY_UNAVAILABLE_SCHEMA",
    "PROGRAM_WORLD_DOMAIN_ADAPTER_INTERFACE",
    "PROGRAM_WORLD_DOMAIN_ADAPTER_SCHEMA",
    "UNSUPPORTED_DOMAIN_KINDS",
    "AdapterFreshnessState",
    "DatasetStateAdapter",
    "DomainAdapterError",
    "DomainAdapterFreshness",
    "DomainAdapterScope",
    "DomainAvailability",
    "DomainCapabilityUnavailable",
    "DomainIdentityForm",
    "DomainKind",
    "DomainScopeKind",
    "DomainUnavailabilityReason",
    "IntentIRAdapter",
    "LegalIRAdapter",
    "ProgramWorldDomainAdapter",
    "ProofContextAdapter",
    "RepositorySemanticStateAdapter",
    "SecurityIRAdapter",
    "SemanticCapsuleAdapter",
    "UnsupportedDomainKind",
    "VFSNamespaceAdapter",
    "adapt_program_world_domain",
    "adapter_for",
    "domain_identity_preserved",
    "unavailable_domain",
]
