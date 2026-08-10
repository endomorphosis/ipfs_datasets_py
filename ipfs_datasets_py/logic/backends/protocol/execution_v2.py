"""Execute ProVerif and Tamarin protocol evidence with attack replay (LFP2-031).

Interface: ``ProtocolProviderEvidence@2``

Runs typed symbolic-protocol checks through independent provider surfaces:

* ProVerif (applied-pi) and Tamarin (multiset rewriting) each own process
  models, equational ceilings, claim support, and tool/dependency identity;
* one provider's support **never** establishes the other's assumptions;
* every result binds document structure (equations, roles/rules, channels,
  attacker, claims), provider-specific assumptions, and attack/witness status;
* reported attacks are parsed and replayed, or explicitly marked non-replayable;
* fallback / mock / availability / confidence never grant theorem authority.

Protocol evidence remains under the symbolic-model ceiling (never computational
or theorem kernel authority).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.process import BoundedToolRunner
from ipfs_datasets_py.logic.backends.protocol.proverif import (
    PROVERIF_BACKEND_VERSION,
    PROVERIF_SUPPORTED_CLAIMS,
    PROVERIF_SUPPORTED_THEORIES,
    ProVerifBackend,
    ProVerifBackendOutcome,
)
from ipfs_datasets_py.logic.backends.protocol.tamarin import (
    TAMARIN_BACKEND_VERSION,
    TAMARIN_SUPPORTED_CLAIMS,
    TAMARIN_SUPPORTED_THEORIES,
    TamarinBackend,
    TamarinBackendOutcome,
)
from ipfs_datasets_py.logic.backends.results import (
    ProtocolResult,
    ResultAuthority,
    ResultStatus,
)
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.families.namespaces import (
    LogicIdentity,
    evidence_id,
    lane_id,
    provider_id,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendRequest,
    ExecutionBounds,
    QueryKind,
)
from ipfs_datasets_py.logic.software_verification.protocol import (
    EquationalTheory,
    ProtocolClaimKind,
    ProtocolIR,
    ProtocolValidationError,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    SyntaxContractError,
    _freeze_mapping,
    _record_id,
    _require_mapping,
    _require_sequence,
    _sha256_hex,
    _text,
    _thaw_mapping,
    canonical_json_bytes,
    content_sha256,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

PROTOCOL_PROVIDER_EVIDENCE_V2_INTERFACE: Final = "ProtocolProviderEvidence@2"
PROTOCOL_EXECUTION_REQUEST_V2_INTERFACE: Final = "ProtocolExecutionRequest@2"
PROTOCOL_EXECUTION_RESULT_V2_INTERFACE: Final = "ProtocolExecutionResult@2"
PROTOCOL_DOCUMENT_BINDING_V2_INTERFACE: Final = "ProtocolDocumentBinding@2"
PROTOCOL_ASSUMPTIONS_BINDING_V2_INTERFACE: Final = "ProtocolAssumptionsBinding@2"
PROTOCOL_ATTACK_BINDING_V2_INTERFACE: Final = "ProtocolAttackBinding@2"
PROTOCOL_CAPABILITY_RECEIPT_V2_INTERFACE: Final = "ProtocolCapabilityReceipt@2"

PROTOCOL_PROVIDER_EVIDENCE_SCHEMA: Final = "protocol-provider-evidence/v2"
PROTOCOL_EXECUTION_REQUEST_SCHEMA: Final = "protocol-execution-request/v2"
PROTOCOL_EXECUTION_RESULT_SCHEMA: Final = "protocol-execution-result/v2"
PROTOCOL_DOCUMENT_BINDING_SCHEMA: Final = "protocol-document-binding/v2"
PROTOCOL_ASSUMPTIONS_BINDING_SCHEMA: Final = "protocol-assumptions-binding/v2"
PROTOCOL_ATTACK_BINDING_SCHEMA: Final = "protocol-attack-binding/v2"
PROTOCOL_CAPABILITY_RECEIPT_SCHEMA: Final = "protocol-capability-receipt/v2"

PROTOCOL_EXECUTION_V2_MODULE_VERSION: Final = "1.0.0"
PROTOCOL_EXECUTION_V2_TASK_ID: Final = "LFP2-031"
PROTOCOL_EXECUTION_V2_GOAL_ID: Final = "LFP2-G060"

PROTOCOL_LANE_ID: Final = "protocol"
PROTOCOL_EVIDENCE_KIND: Final = "protocol"

_MAX_DIAGNOSTICS: Final = 64
_MAX_METADATA_BYTES: Final = 8_192
_MAX_SOURCE_REFS: Final = 64
_MAX_ATTACK_TRACES: Final = 64
_MAX_REPLAY_TOKENS: Final = 512

_FORBIDDEN_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "arbitrary_payload",
        "claimed_execution",
        "claimed_proof",
        "execution_result",
        "fake_replay",
        "family_string",
        "free_form_family",
        "is_proved",
        "logic_family",
        "mock_execution",
        "mock_result",
        "opaque_extension",
        "payload",
        "proof_result",
        "proof_status",
        "proved",
        "raw_formula",
        "raw_result",
        "raw_source",
        "solver_result",
        "target_source",
        "theorem_status",
        "verification_result",
        "verification_status",
    }
)

_NON_AUTHORITATIVE_SIGNAL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "availability",
        "available",
        "confidence",
        "fallback",
        "fallback_output",
        "fluent_text",
        "is_valid",
        "mock",
        "mock_output",
        "similarity",
    }
)


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


class ProtocolExecutionError(SyntaxContractError):
    """Raised when protocol execution v2 inputs are malformed."""


class ProtocolAuthorityError(ProtocolExecutionError):
    """Raised when a claim would exceed the protocol authority ceiling."""


class ProtocolProviderKind(StrEnum):
    """Closed set of protocol providers with independent assumption surfaces."""

    PROVERIF = "proverif"
    TAMARIN = "tamarin"


class ProtocolProcessModel(StrEnum):
    """Provider-specific process / rewriting model (never shared)."""

    APPLIED_PI = "applied_pi"
    MULTISET_REWRITING = "multiset_rewriting"


class ProtocolExecutionMode(StrEnum):
    """How the protocol outcome was produced.

    Only ``engine`` may establish protocol evidence.  ``fallback`` and ``mock``
    never do.
    """

    ENGINE = "engine"
    FALLBACK = "fallback"
    MOCK = "mock"


class ProtocolDisposition(StrEnum):
    """Closed set of protocol-execution dispositions."""

    SECURE = "secure"
    ATTACK_FOUND = "attack_found"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    ERROR = "error"
    MALFORMED = "malformed"
    MOCK_REJECTED = "mock_rejected"
    FALLBACK_REJECTED = "fallback_rejected"
    QUARANTINED = "quarantined"


class ProtocolAttackStatus(StrEnum):
    """Attack / witness attachment status bound into every result."""

    NONE = "none"
    ABSENT = "absent"
    ATTACK_REPLAYED = "attack_replayed"
    ATTACK_NON_REPLAYABLE = "attack_non_replayable"
    SECURE_NO_ATTACK = "secure_no_attack"


class ProtocolClaimKindV2(StrEnum):
    """Claims that mock / fallback / other-provider support must never establish."""

    PROTOCOL = "protocol"
    PROOF = "proof"
    SATISFIABILITY = "satisfiability"
    THEOREM = "theorem"
    OTHER_PROVIDER_ASSUMPTIONS = "other_provider_assumptions"


@dataclass(frozen=True, slots=True)
class ProtocolProviderCapability:
    """Static, independent capability declaration for one protocol provider."""

    provider: ProtocolProviderKind
    process_model: ProtocolProcessModel
    backend_interface: str
    dependency_kind: str
    dependency_name: str
    source_format: str
    supports_equivalence: bool
    supported_claim_kinds: tuple[str, ...]
    supported_equational_theories: tuple[str, ...]
    adversary_model: str = "dolev_yao"
    perfect_cryptography: bool = True
    computational_soundness: bool = False
    bitstring_level: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "adversary_model": self.adversary_model,
            "backend_interface": self.backend_interface,
            "bitstring_level": self.bitstring_level,
            "computational_soundness": self.computational_soundness,
            "dependency_kind": self.dependency_kind,
            "dependency_name": self.dependency_name,
            "perfect_cryptography": self.perfect_cryptography,
            "process_model": self.process_model.value,
            "provider": self.provider.value,
            "source_format": self.source_format,
            "supported_claim_kinds": list(self.supported_claim_kinds),
            "supported_equational_theories": list(self.supported_equational_theories),
            "supports_equivalence": self.supports_equivalence,
        }


PROVERIF_CAPABILITY: Final = ProtocolProviderCapability(
    provider=ProtocolProviderKind.PROVERIF,
    process_model=ProtocolProcessModel.APPLIED_PI,
    backend_interface=PROVERIF_BACKEND_VERSION,
    dependency_kind="opam",
    dependency_name="opam:proverif",
    source_format="pv",
    supports_equivalence=True,
    supported_claim_kinds=tuple(sorted(item.value for item in PROVERIF_SUPPORTED_CLAIMS)),
    supported_equational_theories=tuple(
        sorted(item.value for item in PROVERIF_SUPPORTED_THEORIES)
    ),
)

TAMARIN_CAPABILITY: Final = ProtocolProviderCapability(
    provider=ProtocolProviderKind.TAMARIN,
    process_model=ProtocolProcessModel.MULTISET_REWRITING,
    backend_interface=TAMARIN_BACKEND_VERSION,
    dependency_kind="maude",
    dependency_name="maude",
    source_format="spthy",
    supports_equivalence=False,
    supported_claim_kinds=tuple(sorted(item.value for item in TAMARIN_SUPPORTED_CLAIMS)),
    supported_equational_theories=tuple(
        sorted(item.value for item in TAMARIN_SUPPORTED_THEORIES)
    ),
)

_PROVIDER_CAPABILITIES: Final[Mapping[ProtocolProviderKind, ProtocolProviderCapability]] = {
    ProtocolProviderKind.PROVERIF: PROVERIF_CAPABILITY,
    ProtocolProviderKind.TAMARIN: TAMARIN_CAPABILITY,
}

_PROVIDER_ALIASES: Final[dict[str, ProtocolProviderKind]] = {
    "proverif": ProtocolProviderKind.PROVERIF,
    "proverif_prover": ProtocolProviderKind.PROVERIF,
    "proverif-prover": ProtocolProviderKind.PROVERIF,
    "protocol_proverif": ProtocolProviderKind.PROVERIF,
    "protocol-proverif": ProtocolProviderKind.PROVERIF,
    "pv": ProtocolProviderKind.PROVERIF,
    "tamarin": ProtocolProviderKind.TAMARIN,
    "tamarin_prover": ProtocolProviderKind.TAMARIN,
    "tamarin-prover": ProtocolProviderKind.TAMARIN,
    "protocol_tamarin": ProtocolProviderKind.TAMARIN,
    "protocol-tamarin": ProtocolProviderKind.TAMARIN,
    "spthy": ProtocolProviderKind.TAMARIN,
}


def normalize_protocol_provider(
    value: ProtocolProviderKind | str,
) -> ProtocolProviderKind:
    """Normalize provider labels into the closed protocol provider set."""

    if isinstance(value, ProtocolProviderKind):
        return value
    key = str(value).strip().lower().replace("-", "_")
    if key not in _PROVIDER_ALIASES:
        alt = str(value).strip().lower()
        if alt in _PROVIDER_ALIASES:
            return _PROVIDER_ALIASES[alt]
        raise ProtocolExecutionError(
            f"unsupported protocol provider: {value!r}; "
            f"expected proverif or tamarin"
        )
    return _PROVIDER_ALIASES[key]


def capability_for(
    provider: ProtocolProviderKind | str,
) -> ProtocolProviderCapability:
    """Return the independent capability declaration for one provider only."""

    kind = normalize_protocol_provider(provider)
    return _PROVIDER_CAPABILITIES[kind]


def provider_logic_identity(provider: ProtocolProviderKind) -> LogicIdentity:
    """Return the canonical provider identity for matrix / evidence binding."""

    return provider_id(provider.value)


def provider_assumptions_establish_other(
    source: ProtocolProviderKind | str,
    target: ProtocolProviderKind | str,
    *,
    source_available: bool = True,
    source_supported: bool = True,
) -> bool:
    """Whether *source* assumptions establish *target* capability.

    Always ``False`` when providers differ (LFP2-031 acceptance).  Same-provider
    identity is not a cross-provider transfer either.
    """

    del source_available, source_supported
    src = normalize_protocol_provider(source)
    dst = normalize_protocol_provider(target)
    if src is not dst:
        return False
    return False


def non_authoritative_signal_establishes(
    claim: ProtocolClaimKindV2 | str,
    *,
    mock_output: object = None,
    fallback_output: object = None,
    available: bool | None = None,
    confidence: float | None = None,
    fluent_text: str | None = None,
    other_provider_available: bool | None = None,
) -> bool:
    """Always ``False``: mock / fallback / availability cannot establish claims."""

    del (
        claim,
        mock_output,
        fallback_output,
        available,
        confidence,
        fluent_text,
        other_provider_available,
    )
    return False


# ---------------------------------------------------------------------------
# Primitive validators
# ---------------------------------------------------------------------------


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> StrEnum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value).strip())
    except (TypeError, ValueError) as error:
        allowed = ", ".join(item.value for item in enum_type)
        raise ProtocolExecutionError(
            f"{field_name} must be one of: {allowed}; got {value!r}"
        ) from error


def _optional_bool(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ProtocolExecutionError(f"{field_name} must be a boolean")


def _digest_of(payload: Mapping[str, Any]) -> str:
    return content_sha256(canonical_json_bytes(dict(payload)))


def _source_ref_ids(
    value: object, field_name: str = "source_ref_ids"
) -> tuple[str, ...]:
    items = _require_sequence(value, field_name)
    if len(items) > _MAX_SOURCE_REFS:
        raise ProtocolExecutionError(
            f"{field_name} exceeds hard limit {_MAX_SOURCE_REFS}"
        )
    refs: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        ref = _record_id(item, f"{field_name}[{index}]")
        if ref not in seen:
            seen.add(ref)
            refs.append(ref)
    return tuple(refs)


def _forbid_authority_metadata(metadata: Mapping[str, Any], field_name: str) -> None:
    for key in metadata:
        if key in _FORBIDDEN_METADATA_KEYS or key in _NON_AUTHORITATIVE_SIGNAL_KEYS:
            raise ProtocolAuthorityError(
                f"{field_name} rejects free-form authority/signal key {key!r}; "
                "use typed protocol evidence fields only"
            )


def _document_from_value(value: object) -> ProtocolIR:
    if isinstance(value, ProtocolIR):
        return value
    if isinstance(value, Mapping):
        try:
            return ProtocolIR.from_dict(value)
        except (ProtocolValidationError, TypeError, ValueError) as error:
            raise ProtocolExecutionError(
                f"invalid protocol document: {error}"
            ) from error
    raise ProtocolExecutionError("document must be ProtocolIR or mapping")


def _status_to_disposition(status: ResultStatus) -> ProtocolDisposition:
    mapping = {
        ResultStatus.SECURE: ProtocolDisposition.SECURE,
        ResultStatus.ATTACK_FOUND: ProtocolDisposition.ATTACK_FOUND,
        ResultStatus.UNKNOWN: ProtocolDisposition.UNKNOWN,
        ResultStatus.TIMEOUT: ProtocolDisposition.TIMEOUT,
        ResultStatus.UNAVAILABLE: ProtocolDisposition.UNAVAILABLE,
        ResultStatus.UNSUPPORTED: ProtocolDisposition.UNSUPPORTED,
        ResultStatus.ERROR: ProtocolDisposition.ERROR,
        ResultStatus.MALFORMED: ProtocolDisposition.MALFORMED,
    }
    return mapping.get(status, ProtocolDisposition.UNKNOWN)


def _filter_keys(mapping: Mapping[str, Any], allowed: set[str]) -> dict[str, Any]:
    return {key: value for key, value in mapping.items() if key in allowed}


def _claim_ref(value: object, field_name: str = "claim_id") -> str:
    """Normalize a claim reference into a stable record id when possible."""

    text = _text(str(value).strip(), field_name, maximum=256)
    try:
        return _record_id(text, field_name)
    except SyntaxContractError:
        # Tool output may surface raw query text; keep a stable sanitized id.
        cleaned = "".join(
            ch if ch.isalnum() or ch in "._:/-" else "_" for ch in text
        ).strip("_")
        if not cleaned or not cleaned[0].isalnum():
            cleaned = f"claim_{cleaned or 'unknown'}"
        return _record_id(cleaned[:256], field_name)


def _contract_json_value(value: object, field_name: str) -> Any:
    """Coerce a value into freeze-mapping-safe JSON (no floats)."""

    if value is None or type(value) in {str, bool, int}:
        if type(value) is int and abs(value) > (1 << 53) - 1:
            raise ProtocolExecutionError(
                f"{field_name} integer is outside the safe JSON integer range"
            )
        return value
    if type(value) is float:
        if value != value or value in {float("inf"), float("-inf")}:
            raise ProtocolExecutionError(
                f"{field_name} must be a finite number; got {value!r}"
            )
        as_int = int(value)
        if value == as_int:
            if abs(as_int) > (1 << 53) - 1:
                raise ProtocolExecutionError(
                    f"{field_name} integer is outside the safe JSON integer range"
                )
            return as_int
        micros = int(round(value * 1_000_000))
        if abs(micros) > (1 << 53) - 1:
            raise ProtocolExecutionError(
                f"{field_name} fixed-point value is outside the safe JSON range"
            )
        return micros
    if isinstance(value, Mapping):
        return {
            str(key): _contract_json_value(item, f"{field_name}.{key}")
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            _contract_json_value(item, f"{field_name}[{index}]")
            for index, item in enumerate(value)
        ]
    raise ProtocolExecutionError(
        f"{field_name} is not a contract-safe JSON value: {type(value).__name__}"
    )


def _evidence_receipt_payload(receipt: Mapping[str, Any] | object) -> dict[str, Any]:
    if hasattr(receipt, "to_dict") and callable(receipt.to_dict):
        raw = receipt.to_dict()  # type: ignore[operator]
    else:
        raw = dict(_require_mapping(receipt, "receipt"))
    if not isinstance(raw, Mapping):
        raise ProtocolExecutionError("receipt.to_dict() must return a mapping")
    return dict(_contract_json_value(dict(raw), "receipt"))


# ---------------------------------------------------------------------------
# Bindings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProtocolDocumentBindingV2:
    """Document structure bound into every answer.

    Preserves equations, roles/rules, channels, attacker, secrecy/reachability/
    correspondence claims, and event identity.

    Interface: ``ProtocolDocumentBinding@2``.
    """

    document_id: str
    document_digest: str
    equational_theories: tuple[str, ...]
    role_ids: tuple[str, ...]
    rewrite_fact_ids: tuple[str, ...]
    channel_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]
    claim_kinds: tuple[str, ...]
    adversary_kind: str
    adversary_id: str
    trust_assumption_ids: tuple[str, ...] = ()
    message_ids: tuple[str, ...] = ()
    fresh_name_ids: tuple[str, ...] = ()
    key_ids: tuple[str, ...] = ()
    function_ids: tuple[str, ...] = ()
    source_format: str = ""
    compile_digest: str = ""
    schema_version: str = PROTOCOL_DOCUMENT_BINDING_SCHEMA

    interface: ClassVar[str] = PROTOCOL_DOCUMENT_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "document_id", _record_id(self.document_id, "document_id")
        )
        object.__setattr__(
            self,
            "document_digest",
            _sha256_hex(self.document_digest, "document_digest"),
        )
        for name in (
            "equational_theories",
            "role_ids",
            "rewrite_fact_ids",
            "channel_ids",
            "event_ids",
            "claim_ids",
            "claim_kinds",
            "trust_assumption_ids",
            "message_ids",
            "fresh_name_ids",
            "key_ids",
            "function_ids",
        ):
            items = tuple(
                _text(item, f"{name} item", maximum=256)
                for item in getattr(self, name)
            )
            object.__setattr__(self, name, items)
        object.__setattr__(
            self,
            "adversary_kind",
            _text(self.adversary_kind, "adversary_kind", maximum=64),
        )
        object.__setattr__(
            self, "adversary_id", _record_id(self.adversary_id, "adversary_id")
        )
        if self.source_format:
            object.__setattr__(
                self,
                "source_format",
                _text(self.source_format, "source_format", maximum=32),
            )
        else:
            object.__setattr__(self, "source_format", "")
        if self.compile_digest:
            object.__setattr__(
                self,
                "compile_digest",
                _sha256_hex(self.compile_digest, "compile_digest"),
            )
        else:
            object.__setattr__(self, "compile_digest", "")
        if self.schema_version != PROTOCOL_DOCUMENT_BINDING_SCHEMA:
            raise ProtocolExecutionError(
                f"unsupported document binding schema: {self.schema_version!r}"
            )

    @classmethod
    def from_document(
        cls,
        document: ProtocolIR,
        *,
        source_format: str = "",
        compile_digest: str = "",
    ) -> ProtocolDocumentBindingV2:
        return cls(
            document_id=document.document_id,
            document_digest=document.sha256,
            equational_theories=tuple(
                item.value if isinstance(item, EquationalTheory) else str(item)
                for item in document.equational_theories
            ),
            role_ids=tuple(item.role_id for item in document.roles),
            rewrite_fact_ids=tuple(item.fact_id for item in document.rewrite_facts),
            channel_ids=tuple(item.channel_id for item in document.channels),
            event_ids=tuple(item.event_id for item in document.events),
            claim_ids=tuple(item.claim_id for item in document.claims),
            claim_kinds=tuple(
                item.kind.value if isinstance(item.kind, ProtocolClaimKind) else str(item.kind)
                for item in document.claims
            ),
            adversary_kind=(
                document.adversary.kind.value
                if hasattr(document.adversary.kind, "value")
                else str(document.adversary.kind)
            ),
            adversary_id=document.adversary.adversary_id,
            trust_assumption_ids=tuple(
                item.assumption_id for item in document.trust_assumptions
            ),
            message_ids=tuple(item.message_id for item in document.messages),
            fresh_name_ids=tuple(item.name_id for item in document.fresh_names),
            key_ids=tuple(item.key_id for item in document.keys),
            function_ids=tuple(item.function_id for item in document.functions),
            source_format=source_format,
            compile_digest=compile_digest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "adversary_id": self.adversary_id,
            "adversary_kind": self.adversary_kind,
            "channel_ids": list(self.channel_ids),
            "claim_ids": list(self.claim_ids),
            "claim_kinds": list(self.claim_kinds),
            "compile_digest": self.compile_digest,
            "document_digest": self.document_digest,
            "document_id": self.document_id,
            "equational_theories": list(self.equational_theories),
            "event_ids": list(self.event_ids),
            "fresh_name_ids": list(self.fresh_name_ids),
            "function_ids": list(self.function_ids),
            "interface": self.interface,
            "key_ids": list(self.key_ids),
            "message_ids": list(self.message_ids),
            "rewrite_fact_ids": list(self.rewrite_fact_ids),
            "role_ids": list(self.role_ids),
            "schema_version": self.schema_version,
            "source_format": self.source_format,
            "trust_assumption_ids": list(self.trust_assumption_ids),
        }


@dataclass(frozen=True, slots=True)
class ProtocolAssumptionsBindingV2:
    """Provider-specific symbolic-model assumptions (never shared across tools).

    Interface: ``ProtocolAssumptionsBinding@2``.
    """

    provider: ProtocolProviderKind | str
    process_model: ProtocolProcessModel | str
    adversary_model: str
    perfect_cryptography: bool
    computational_soundness: bool
    bitstring_level: bool
    dependency_kind: str
    dependency_name: str
    supported_claim_kinds: tuple[str, ...]
    supported_equational_theories: tuple[str, ...]
    supports_equivalence: bool
    backend_interface: str
    tool_version: str = ""
    dependency_version: str = ""
    schema_version: str = PROTOCOL_ASSUMPTIONS_BINDING_SCHEMA

    interface: ClassVar[str] = PROTOCOL_ASSUMPTIONS_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider", normalize_protocol_provider(self.provider)
        )
        object.__setattr__(
            self,
            "process_model",
            _enum(self.process_model, ProtocolProcessModel, "process_model"),
        )
        provider = self.provider  # type: ignore[assignment]
        expected = capability_for(provider)
        if self.process_model is not expected.process_model:  # type: ignore[comparison-overlap]
            raise ProtocolAuthorityError(
                f"{provider.value} assumptions must use process model "
                f"{expected.process_model.value}; got "
                f"{getattr(self.process_model, 'value', self.process_model)!r}"
            )
        object.__setattr__(
            self,
            "adversary_model",
            _text(self.adversary_model, "adversary_model", maximum=64),
        )
        for name in (
            "perfect_cryptography",
            "computational_soundness",
            "bitstring_level",
            "supports_equivalence",
        ):
            object.__setattr__(
                self, name, _optional_bool(getattr(self, name), name)
            )
        if self.computational_soundness:
            raise ProtocolAuthorityError(
                "protocol assumptions cannot claim computational soundness"
            )
        if self.bitstring_level:
            raise ProtocolAuthorityError(
                "protocol assumptions cannot claim bitstring-level attacker"
            )
        object.__setattr__(
            self,
            "dependency_kind",
            _text(self.dependency_kind, "dependency_kind", maximum=64),
        )
        object.__setattr__(
            self,
            "dependency_name",
            _text(self.dependency_name, "dependency_name", maximum=128),
        )
        object.__setattr__(
            self,
            "supported_claim_kinds",
            tuple(
                _text(item, "supported_claim_kinds item", maximum=64)
                for item in self.supported_claim_kinds
            ),
        )
        object.__setattr__(
            self,
            "supported_equational_theories",
            tuple(
                _text(item, "supported_equational_theories item", maximum=64)
                for item in self.supported_equational_theories
            ),
        )
        object.__setattr__(
            self,
            "backend_interface",
            _text(self.backend_interface, "backend_interface", maximum=128),
        )
        object.__setattr__(
            self,
            "tool_version",
            _text(self.tool_version, "tool_version", maximum=128, allow_empty=True),
        )
        object.__setattr__(
            self,
            "dependency_version",
            _text(
                self.dependency_version,
                "dependency_version",
                maximum=128,
                allow_empty=True,
            ),
        )
        if self.schema_version != PROTOCOL_ASSUMPTIONS_BINDING_SCHEMA:
            raise ProtocolExecutionError(
                f"unsupported assumptions binding schema: {self.schema_version!r}"
            )
        # Keep claim/theory sets aligned with the independent capability table.
        if set(self.supported_claim_kinds) != set(expected.supported_claim_kinds):
            raise ProtocolAuthorityError(
                f"{provider.value} supported_claim_kinds must match the "
                "independent capability table"
            )
        if set(self.supported_equational_theories) != set(
            expected.supported_equational_theories
        ):
            raise ProtocolAuthorityError(
                f"{provider.value} supported_equational_theories must match the "
                "independent capability table"
            )
        if self.supports_equivalence != expected.supports_equivalence:
            raise ProtocolAuthorityError(
                f"{provider.value} supports_equivalence must be "
                f"{expected.supports_equivalence}"
            )
        if self.dependency_kind != expected.dependency_kind:
            raise ProtocolAuthorityError(
                f"{provider.value} dependency_kind must be {expected.dependency_kind!r}"
            )

    @classmethod
    def from_capability(
        cls,
        capability: ProtocolProviderCapability,
        *,
        tool_version: str = "",
        dependency_version: str = "",
    ) -> ProtocolAssumptionsBindingV2:
        return cls(
            provider=capability.provider,
            process_model=capability.process_model,
            adversary_model=capability.adversary_model,
            perfect_cryptography=capability.perfect_cryptography,
            computational_soundness=capability.computational_soundness,
            bitstring_level=capability.bitstring_level,
            dependency_kind=capability.dependency_kind,
            dependency_name=capability.dependency_name,
            supported_claim_kinds=capability.supported_claim_kinds,
            supported_equational_theories=capability.supported_equational_theories,
            supports_equivalence=capability.supports_equivalence,
            backend_interface=capability.backend_interface,
            tool_version=tool_version,
            dependency_version=dependency_version,
        )

    def establishes_other(self, other: ProtocolProviderKind | str) -> bool:
        return provider_assumptions_establish_other(self.provider, other)  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, Any]:
        return {
            "adversary_model": self.adversary_model,
            "backend_interface": self.backend_interface,
            "bitstring_level": False,
            "computational_soundness": False,
            "dependency_kind": self.dependency_kind,
            "dependency_name": self.dependency_name,
            "dependency_version": self.dependency_version,
            "interface": self.interface,
            "perfect_cryptography": self.perfect_cryptography,
            "process_model": (
                self.process_model.value
                if isinstance(self.process_model, ProtocolProcessModel)
                else self.process_model
            ),
            "provider": (
                self.provider.value
                if isinstance(self.provider, ProtocolProviderKind)
                else self.provider
            ),
            "schema_version": self.schema_version,
            "supported_claim_kinds": list(self.supported_claim_kinds),
            "supported_equational_theories": list(self.supported_equational_theories),
            "supports_equivalence": self.supports_equivalence,
            "tool_version": self.tool_version,
        }


@dataclass(frozen=True, slots=True)
class ProtocolAttackBindingV2:
    """Attack / witness status bound into every answer.

    Reported attacks are either replayed (deterministic tokens) or explicitly
    non-replayable.

    Interface: ``ProtocolAttackBinding@2``.
    """

    status: ProtocolAttackStatus | str
    claim_ids: tuple[str, ...] = ()
    replayed: bool = False
    non_replayable: bool = False
    attack_count: int = 0
    replay_tokens: tuple[str, ...] = ()
    attack_traces: tuple[Mapping[str, Any], ...] = ()
    non_replayable_claim_ids: tuple[str, ...] = ()
    authorizes_universal_proof: bool = False
    schema_version: str = PROTOCOL_ATTACK_BINDING_SCHEMA

    interface: ClassVar[str] = PROTOCOL_ATTACK_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "status", _enum(self.status, ProtocolAttackStatus, "status")
        )
        object.__setattr__(
            self,
            "claim_ids",
            tuple(_claim_ref(item, "claim_ids") for item in self.claim_ids),
        )
        object.__setattr__(self, "replayed", _optional_bool(self.replayed, "replayed"))
        object.__setattr__(
            self, "non_replayable", _optional_bool(self.non_replayable, "non_replayable")
        )
        if (
            isinstance(self.attack_count, bool)
            or not isinstance(self.attack_count, int)
            or self.attack_count < 0
        ):
            raise ProtocolExecutionError("attack_count must be a non-negative integer")
        if self.attack_count > _MAX_ATTACK_TRACES:
            raise ProtocolExecutionError(
                f"attack_count exceeds hard limit {_MAX_ATTACK_TRACES}"
            )
        tokens = tuple(
            _text(item, "replay_tokens item", maximum=512)
            for item in self.replay_tokens[:_MAX_REPLAY_TOKENS]
        )
        object.__setattr__(self, "replay_tokens", tokens)
        traces: list[dict[str, Any]] = []
        for index, item in enumerate(self.attack_traces[:_MAX_ATTACK_TRACES]):
            mapping = _require_mapping(item, f"attack_traces[{index}]")
            traces.append(
                dict(_freeze_mapping(mapping, f"attack_traces[{index}]"))
            )
        object.__setattr__(self, "attack_traces", tuple(traces))
        object.__setattr__(
            self,
            "non_replayable_claim_ids",
            tuple(
                _claim_ref(item, "non_replayable_claim_ids")
                for item in self.non_replayable_claim_ids
            ),
        )
        object.__setattr__(
            self,
            "authorizes_universal_proof",
            _optional_bool(
                self.authorizes_universal_proof, "authorizes_universal_proof"
            ),
        )
        if self.authorizes_universal_proof:
            raise ProtocolAuthorityError(
                "attack binding cannot authorize universal proof"
            )
        status = self.status  # type: ignore[assignment]
        if status is ProtocolAttackStatus.ATTACK_REPLAYED:
            if not self.replayed or self.non_replayable:
                raise ProtocolExecutionError(
                    "attack_replayed status requires replayed=True and "
                    "non_replayable=False"
                )
            if self.attack_count < 1:
                raise ProtocolExecutionError(
                    "attack_replayed status requires at least one attack"
                )
        if status is ProtocolAttackStatus.ATTACK_NON_REPLAYABLE:
            if not self.non_replayable or self.replayed:
                raise ProtocolExecutionError(
                    "attack_non_replayable status requires non_replayable=True "
                    "and replayed=False"
                )
        if status is ProtocolAttackStatus.SECURE_NO_ATTACK and (
            self.replayed or self.non_replayable or self.attack_count
        ):
            raise ProtocolExecutionError(
                "secure_no_attack cannot carry attack traces"
            )
        if self.schema_version != PROTOCOL_ATTACK_BINDING_SCHEMA:
            raise ProtocolExecutionError(
                f"unsupported attack binding schema: {self.schema_version!r}"
            )

    @classmethod
    def from_outcomes(
        cls,
        *,
        disposition: ProtocolDisposition,
        claim_outcomes: Sequence[Mapping[str, Any] | object],
    ) -> ProtocolAttackBindingV2:
        """Build attack binding from backend claim outcomes."""

        claim_ids: list[str] = []
        replay_tokens: list[str] = []
        attack_traces: list[dict[str, Any]] = []
        non_replayable_claim_ids: list[str] = []
        attack_count = 0
        any_replayable = False
        any_non_replayable = False

        for raw in claim_outcomes:
            if hasattr(raw, "to_dict") and callable(raw.to_dict):
                outcome = raw.to_dict()  # type: ignore[operator]
            elif isinstance(raw, Mapping):
                outcome = dict(raw)
            else:
                continue
            claim_id = str(outcome.get("claim_id") or "")
            attack = outcome.get("attack_trace")
            if attack is None:
                continue
            attack_count += 1
            if claim_id:
                claim_ids.append(claim_id)
            if isinstance(attack, Mapping):
                attack_traces.append(dict(attack))
                replay = attack.get("replay")
                if isinstance(replay, Sequence) and not isinstance(
                    replay, (str, bytes, bytearray)
                ):
                    tokens = [str(item) for item in replay if str(item).strip()]
                    if tokens:
                        any_replayable = True
                        replay_tokens.extend(tokens)
                    else:
                        any_non_replayable = True
                        if claim_id:
                            non_replayable_claim_ids.append(claim_id)
                else:
                    # Trace present without replay tokens → non-replayable.
                    any_non_replayable = True
                    if claim_id:
                        non_replayable_claim_ids.append(claim_id)
            else:
                any_non_replayable = True
                if claim_id:
                    non_replayable_claim_ids.append(claim_id)

        if disposition is ProtocolDisposition.SECURE:
            return cls(
                status=ProtocolAttackStatus.SECURE_NO_ATTACK,
                claim_ids=(),
                replayed=False,
                non_replayable=False,
                attack_count=0,
            )

        if attack_count == 0:
            if disposition is ProtocolDisposition.ATTACK_FOUND:
                # Attack reported without normalizable traces.
                return cls(
                    status=ProtocolAttackStatus.ATTACK_NON_REPLAYABLE,
                    claim_ids=(),
                    replayed=False,
                    non_replayable=True,
                    attack_count=0,
                    non_replayable_claim_ids=(),
                )
            if disposition in {
                ProtocolDisposition.UNKNOWN,
                ProtocolDisposition.QUARANTINED,
                ProtocolDisposition.TIMEOUT,
                ProtocolDisposition.UNAVAILABLE,
                ProtocolDisposition.UNSUPPORTED,
                ProtocolDisposition.ERROR,
                ProtocolDisposition.MALFORMED,
                ProtocolDisposition.MOCK_REJECTED,
                ProtocolDisposition.FALLBACK_REJECTED,
            }:
                return cls(status=ProtocolAttackStatus.NONE)
            return cls(status=ProtocolAttackStatus.ABSENT)

        if any_replayable and not any_non_replayable:
            return cls(
                status=ProtocolAttackStatus.ATTACK_REPLAYED,
                claim_ids=tuple(dict.fromkeys(claim_ids)),
                replayed=True,
                non_replayable=False,
                attack_count=attack_count,
                replay_tokens=tuple(replay_tokens[:_MAX_REPLAY_TOKENS]),
                attack_traces=tuple(attack_traces[:_MAX_ATTACK_TRACES]),
            )

        # Mixed or non-replayable only → explicitly non-replayable.
        return cls(
            status=ProtocolAttackStatus.ATTACK_NON_REPLAYABLE,
            claim_ids=tuple(dict.fromkeys(claim_ids)),
            replayed=False,
            non_replayable=True,
            attack_count=attack_count,
            replay_tokens=(),
            attack_traces=tuple(attack_traces[:_MAX_ATTACK_TRACES]),
            non_replayable_claim_ids=tuple(dict.fromkeys(non_replayable_claim_ids)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attack_count": self.attack_count,
            "attack_traces": [dict(item) for item in self.attack_traces],
            "authorizes_universal_proof": False,
            "claim_ids": list(self.claim_ids),
            "interface": self.interface,
            "non_replayable": self.non_replayable,
            "non_replayable_claim_ids": list(self.non_replayable_claim_ids),
            "replay_tokens": list(self.replay_tokens),
            "replayed": self.replayed,
            "schema_version": self.schema_version,
            "status": (
                self.status.value
                if isinstance(self.status, ProtocolAttackStatus)
                else self.status
            ),
        }


@dataclass(frozen=True, slots=True)
class ProtocolCapabilityReceiptV2:
    """Independent capability snapshot for exactly one protocol provider.

    Interface: ``ProtocolCapabilityReceipt@2``.

    Never transfers assumptions from another provider.
    """

    provider: ProtocolProviderKind | str
    available: bool
    supported_document: bool
    capability: Mapping[str, Any]
    reason: str = ""
    establishes_other_providers: bool = False
    schema_version: str = PROTOCOL_CAPABILITY_RECEIPT_SCHEMA

    interface: ClassVar[str] = PROTOCOL_CAPABILITY_RECEIPT_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider", normalize_protocol_provider(self.provider)
        )
        object.__setattr__(
            self, "available", _optional_bool(self.available, "available")
        )
        object.__setattr__(
            self,
            "supported_document",
            _optional_bool(self.supported_document, "supported_document"),
        )
        cap = _require_mapping(self.capability, "capability")
        provider = self.provider  # type: ignore[assignment]
        if cap.get("provider") not in {None, provider.value}:
            raise ProtocolAuthorityError(
                "capability receipt provider must match the declared provider; "
                "one provider's assumptions cannot be re-labeled as another's"
            )
        canonical = capability_for(provider).to_dict()
        object.__setattr__(self, "capability", dict(canonical))
        object.__setattr__(
            self, "reason", _text(self.reason, "reason", allow_empty=True, maximum=1_024)
        )
        object.__setattr__(
            self,
            "establishes_other_providers",
            _optional_bool(
                self.establishes_other_providers, "establishes_other_providers"
            ),
        )
        if self.establishes_other_providers:
            raise ProtocolAuthorityError(
                "capability receipt cannot establish other providers"
            )
        if self.schema_version != PROTOCOL_CAPABILITY_RECEIPT_SCHEMA:
            raise ProtocolExecutionError(
                f"unsupported capability receipt schema: {self.schema_version!r}"
            )

    def establishes(self, other: ProtocolProviderKind | str) -> bool:
        return provider_assumptions_establish_other(
            self.provider,  # type: ignore[arg-type]
            other,
            source_available=self.available,
            source_supported=self.supported_document,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "capability": dict(self.capability),
            "establishes_other_providers": False,
            "interface": self.interface,
            "provider": (
                self.provider.value
                if isinstance(self.provider, ProtocolProviderKind)
                else self.provider
            ),
            "reason": self.reason,
            "schema_version": self.schema_version,
            "supported_document": self.supported_document,
        }


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProtocolExecutionRequestV2:
    """Typed ProVerif / Tamarin execution request.

    Interface: ``ProtocolExecutionRequest@2``.
    """

    request_id: str
    provider: ProtocolProviderKind | str
    document: ProtocolIR | Mapping[str, Any] | None = None
    source: str = ""
    source_format: str = ""
    mode: ProtocolExecutionMode | str = ProtocolExecutionMode.ENGINE
    source_ref_ids: tuple[str, ...] | Sequence[str] = ()
    bounds: ExecutionBounds | None = None
    mock_output: Mapping[str, Any] | None = None
    fallback_output: Mapping[str, Any] | None = None
    available: bool = True
    confidence: float = 0.0
    fluent_text: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PROTOCOL_EXECUTION_REQUEST_SCHEMA

    interface: ClassVar[str] = PROTOCOL_EXECUTION_REQUEST_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "provider", normalize_protocol_provider(self.provider)
        )

        document: ProtocolIR | None = None
        if self.document is not None:
            document = _document_from_value(self.document)
        object.__setattr__(self, "document", document)

        if self.source:
            if not isinstance(self.source, str) or "\x00" in self.source:
                raise ProtocolExecutionError(
                    "source must be text without NUL bytes"
                )
            if not self.source.strip():
                raise ProtocolExecutionError("source must be non-empty when provided")
            object.__setattr__(self, "source", self.source)
        else:
            object.__setattr__(self, "source", "")

        capability = capability_for(self.provider)  # type: ignore[arg-type]
        if self.source_format:
            fmt = _text(self.source_format, "source_format", maximum=32).lower()
            object.__setattr__(self, "source_format", fmt)
        elif self.source:
            object.__setattr__(self, "source_format", capability.source_format)
        else:
            object.__setattr__(self, "source_format", "")

        if document is None and not self.source:
            raise ProtocolExecutionError(
                "ProtocolExecutionRequest@2 requires document and/or source"
            )

        object.__setattr__(
            self, "mode", _enum(self.mode, ProtocolExecutionMode, "mode")
        )
        object.__setattr__(
            self, "source_ref_ids", _source_ref_ids(self.source_ref_ids or ())
        )

        if self.bounds is None:
            object.__setattr__(
                self,
                "bounds",
                ExecutionBounds(timeout_ms=1_000, max_steps=1_000),
            )
        elif not isinstance(self.bounds, ExecutionBounds):
            raise ProtocolExecutionError("bounds must be ExecutionBounds")

        object.__setattr__(
            self, "available", _optional_bool(self.available, "available")
        )
        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence, (int, float)
        ):
            raise ProtocolExecutionError("confidence must be numeric")
        conf = float(self.confidence)
        if conf != conf or conf < 0.0 or conf > 1.0:
            raise ProtocolExecutionError("confidence must be finite in [0, 1]")
        object.__setattr__(self, "confidence", conf)
        object.__setattr__(
            self,
            "fluent_text",
            _text(self.fluent_text, "fluent_text", maximum=8_192, allow_empty=True),
        )

        if self.mock_output is None:
            object.__setattr__(self, "mock_output", None)
        else:
            mock = _require_mapping(self.mock_output, "mock_output")
            object.__setattr__(
                self, "mock_output", dict(_freeze_mapping(mock, "mock_output"))
            )
        if self.fallback_output is None:
            object.__setattr__(self, "fallback_output", None)
        else:
            fallback = _require_mapping(self.fallback_output, "fallback_output")
            object.__setattr__(
                self,
                "fallback_output",
                dict(_freeze_mapping(fallback, "fallback_output")),
            )

        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_authority_metadata(metadata, "metadata")
        if len(canonical_json_bytes(dict(metadata))) > _MAX_METADATA_BYTES:
            raise ProtocolExecutionError("metadata exceeds hard byte limit")
        object.__setattr__(self, "metadata", metadata)

        if self.schema_version != PROTOCOL_EXECUTION_REQUEST_SCHEMA:
            raise ProtocolExecutionError(
                f"unsupported ProtocolExecutionRequest@2 schema: "
                f"{self.schema_version!r}"
            )

    @property
    def has_mock_output(self) -> bool:
        return self.mock_output is not None

    @property
    def has_fallback_output(self) -> bool:
        return self.fallback_output is not None

    @property
    def provider_identity(self) -> LogicIdentity:
        return provider_logic_identity(self.provider)  # type: ignore[arg-type]

    @property
    def lane(self) -> LogicIdentity:
        return lane_id(PROTOCOL_LANE_ID)

    @property
    def evidence_kind(self) -> LogicIdentity:
        return evidence_id(PROTOCOL_EVIDENCE_KIND)

    @property
    def document_digest(self) -> str:
        if self.document is not None:
            return self.document.sha256  # type: ignore[union-attr]
        if self.source:
            return content_sha256(self.source.encode("utf-8"))
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "bounds": self.bounds.to_dict() if self.bounds else None,  # type: ignore[union-attr]
            "confidence": self.confidence,
            "document_digest": self.document_digest,
            "document_id": (
                self.document.document_id if self.document is not None else ""  # type: ignore[union-attr]
            ),
            "document_present": self.document is not None,
            "evidence_kind": self.evidence_kind.to_dict(),
            "fallback_output": (
                None if self.fallback_output is None else dict(self.fallback_output)
            ),
            "fluent_text": self.fluent_text,
            "has_fallback_output": self.has_fallback_output,
            "has_mock_output": self.has_mock_output,
            "interface": self.interface,
            "lane": self.lane.to_dict(),
            "metadata": _thaw_mapping(self.metadata),
            "mock_output": (
                None if self.mock_output is None else dict(self.mock_output)
            ),
            "mode": (
                self.mode.value
                if isinstance(self.mode, ProtocolExecutionMode)
                else self.mode
            ),
            "provider": (
                self.provider.value
                if isinstance(self.provider, ProtocolProviderKind)
                else self.provider
            ),
            "provider_identity": self.provider_identity.to_dict(),
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "source_format": self.source_format,
            "source_present": bool(self.source),
            "source_ref_ids": list(self.source_ref_ids),
        }


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProtocolProviderEvidenceV2:
    """Pinned protocol provider evidence with distinct provider assumptions.

    Interface: ``ProtocolProviderEvidence@2``.

    Every answer **must** identify provider, document structure, assumptions,
    and attack/witness status.  One provider's support never establishes the
    other's assumptions.  Protocol evidence remains symbolic-bounded — never
    theorem.
    """

    evidence_id: str
    request_id: str
    request_digest: str
    provider: ProtocolProviderKind | str
    disposition: ProtocolDisposition | str
    mode: ProtocolExecutionMode | str
    document: ProtocolDocumentBindingV2 | Mapping[str, Any]
    assumptions: ProtocolAssumptionsBindingV2 | Mapping[str, Any]
    attack: ProtocolAttackBindingV2 | Mapping[str, Any]
    capability: ProtocolCapabilityReceiptV2 | Mapping[str, Any]
    source_ref_ids: tuple[str, ...] | Sequence[str] = ()
    result_authority: ResultAuthority | str = ResultAuthority.PROTOCOL
    result_status: ResultStatus | str = ResultStatus.UNKNOWN
    role: ToolRole | str = ToolRole.AUTHORITY
    authority_ceiling: ToolchainAuthorityCeiling | str = (
        ToolchainAuthorityCeiling.PROTOCOL
    )
    translation_ceiling: EvidenceAuthority | str = EvidenceAuthority.BOUNDED
    protocol_established: bool = False
    mock_output_present: bool = False
    fallback_output_present: bool = False
    available: bool = False
    confidence: float = 0.0
    fluent_text_present: bool = False
    external_tool_proof: bool = False
    authorizes_universal_proof: bool = False
    receipt: Mapping[str, Any] | None = None
    diagnostics: tuple[str, ...] = ()
    content_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PROTOCOL_PROVIDER_EVIDENCE_SCHEMA

    interface: ClassVar[str] = PROTOCOL_PROVIDER_EVIDENCE_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", _record_id(self.evidence_id, "evidence_id")
        )
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self,
            "request_digest",
            _sha256_hex(self.request_digest, "request_digest"),
        )
        object.__setattr__(
            self, "provider", normalize_protocol_provider(self.provider)
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, ProtocolDisposition, "disposition"),
        )
        object.__setattr__(
            self, "mode", _enum(self.mode, ProtocolExecutionMode, "mode")
        )

        if isinstance(self.document, ProtocolDocumentBindingV2):
            document = self.document
        else:
            document = ProtocolDocumentBindingV2(
                **_filter_keys(
                    _require_mapping(self.document, "document"),
                    {
                        "document_id",
                        "document_digest",
                        "equational_theories",
                        "role_ids",
                        "rewrite_fact_ids",
                        "channel_ids",
                        "event_ids",
                        "claim_ids",
                        "claim_kinds",
                        "adversary_kind",
                        "adversary_id",
                        "trust_assumption_ids",
                        "message_ids",
                        "fresh_name_ids",
                        "key_ids",
                        "function_ids",
                        "source_format",
                        "compile_digest",
                        "schema_version",
                    },
                )
            )
        object.__setattr__(self, "document", document)

        if isinstance(self.assumptions, ProtocolAssumptionsBindingV2):
            assumptions = self.assumptions
        else:
            assumptions = ProtocolAssumptionsBindingV2(
                **_filter_keys(
                    _require_mapping(self.assumptions, "assumptions"),
                    {
                        "provider",
                        "process_model",
                        "adversary_model",
                        "perfect_cryptography",
                        "computational_soundness",
                        "bitstring_level",
                        "dependency_kind",
                        "dependency_name",
                        "supported_claim_kinds",
                        "supported_equational_theories",
                        "supports_equivalence",
                        "backend_interface",
                        "tool_version",
                        "dependency_version",
                        "schema_version",
                    },
                )
            )
        object.__setattr__(self, "assumptions", assumptions)
        if assumptions.provider is not self.provider:  # type: ignore[comparison-overlap]
            raise ProtocolAuthorityError(
                "assumptions.provider must match evidence.provider; "
                "provider-specific assumptions remain distinct"
            )

        if isinstance(self.attack, ProtocolAttackBindingV2):
            attack = self.attack
        else:
            attack = ProtocolAttackBindingV2(
                **_filter_keys(
                    _require_mapping(self.attack, "attack"),
                    {
                        "status",
                        "claim_ids",
                        "replayed",
                        "non_replayable",
                        "attack_count",
                        "replay_tokens",
                        "attack_traces",
                        "non_replayable_claim_ids",
                        "authorizes_universal_proof",
                        "schema_version",
                    },
                )
            )
        object.__setattr__(self, "attack", attack)

        if isinstance(self.capability, ProtocolCapabilityReceiptV2):
            capability = self.capability
        else:
            capability = ProtocolCapabilityReceiptV2(
                **_filter_keys(
                    _require_mapping(self.capability, "capability"),
                    {
                        "provider",
                        "available",
                        "supported_document",
                        "capability",
                        "reason",
                        "establishes_other_providers",
                        "schema_version",
                    },
                )
            )
        object.__setattr__(self, "capability", capability)
        if capability.provider is not self.provider:  # type: ignore[comparison-overlap]
            raise ProtocolAuthorityError(
                "capability.provider must match evidence.provider; "
                "one provider's support cannot establish another's assumptions"
            )

        object.__setattr__(
            self, "source_ref_ids", _source_ref_ids(self.source_ref_ids)
        )

        result_authority = (
            self.result_authority
            if isinstance(self.result_authority, ResultAuthority)
            else ResultAuthority(str(self.result_authority))
        )
        if result_authority is not ResultAuthority.PROTOCOL:
            raise ProtocolAuthorityError(
                "ProtocolProviderEvidence@2 result_authority must be protocol; "
                f"got {result_authority!r}"
            )
        object.__setattr__(self, "result_authority", ResultAuthority.PROTOCOL)

        result_status = (
            self.result_status
            if isinstance(self.result_status, ResultStatus)
            else ResultStatus(str(self.result_status))
        )
        if result_status in {ResultStatus.PROVED, ResultStatus.DISPROVED}:
            raise ProtocolAuthorityError(
                "ProtocolProviderEvidence@2 cannot claim theorem result statuses"
            )
        object.__setattr__(self, "result_status", result_status)

        role = self.role if isinstance(self.role, ToolRole) else ToolRole(str(self.role))
        if role not in {ToolRole.AUTHORITY, ToolRole.SHADOW}:
            raise ProtocolAuthorityError(
                f"ProtocolProviderEvidence@2 role must be authority or shadow; got {role!r}"
            )
        object.__setattr__(self, "role", role)

        ceiling = (
            self.authority_ceiling
            if isinstance(self.authority_ceiling, ToolchainAuthorityCeiling)
            else ToolchainAuthorityCeiling(str(self.authority_ceiling))
        )
        if ceiling is not ToolchainAuthorityCeiling.PROTOCOL:
            raise ProtocolAuthorityError(
                "ProtocolProviderEvidence@2 authority_ceiling must be protocol"
            )
        object.__setattr__(self, "authority_ceiling", ceiling)

        translation_ceiling = (
            self.translation_ceiling
            if isinstance(self.translation_ceiling, EvidenceAuthority)
            else EvidenceAuthority(str(self.translation_ceiling))
        )
        if translation_ceiling not in {
            EvidenceAuthority.BOUNDED,
            EvidenceAuthority.NONE,
        }:
            raise ProtocolAuthorityError(
                "ProtocolProviderEvidence@2 translation_ceiling must remain bounded"
            )
        object.__setattr__(self, "translation_ceiling", translation_ceiling)

        for flag_name in (
            "protocol_established",
            "mock_output_present",
            "fallback_output_present",
            "available",
            "fluent_text_present",
            "external_tool_proof",
            "authorizes_universal_proof",
        ):
            object.__setattr__(
                self,
                flag_name,
                _optional_bool(getattr(self, flag_name), flag_name),
            )
        if self.authorizes_universal_proof:
            raise ProtocolAuthorityError(
                "protocol evidence cannot authorize universal proof"
            )

        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence, (int, float)
        ):
            raise ProtocolExecutionError("confidence must be numeric")
        conf = float(self.confidence)
        if conf != conf or conf < 0.0 or conf > 1.0:
            raise ProtocolExecutionError("confidence must be finite in [0, 1]")
        object.__setattr__(self, "confidence", conf)

        mode = self.mode  # type: ignore[assignment]
        if (
            self.mock_output_present
            or self.fallback_output_present
            or mode in {ProtocolExecutionMode.MOCK, ProtocolExecutionMode.FALLBACK}
        ):
            if self.protocol_established:
                raise ProtocolAuthorityError(
                    "fallback or mock output cannot establish protocol authority"
                )
            object.__setattr__(self, "protocol_established", False)
            object.__setattr__(self, "external_tool_proof", False)

        if self.receipt is None:
            object.__setattr__(self, "receipt", None)
        else:
            receipt = _require_mapping(self.receipt, "receipt")
            object.__setattr__(
                self, "receipt", dict(_freeze_mapping(receipt, "receipt"))
            )

        diagnostics: list[str] = []
        for index, item in enumerate(self.diagnostics):
            if not isinstance(item, str) or "\x00" in item:
                raise ProtocolExecutionError(
                    f"diagnostics[{index}] must be text without NUL bytes"
                )
            text = item.strip()
            if not text:
                continue
            diagnostics.append(text[:512])
            if len(diagnostics) >= _MAX_DIAGNOSTICS:
                break
        object.__setattr__(self, "diagnostics", tuple(diagnostics))

        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_authority_metadata(metadata, "metadata")
        object.__setattr__(self, "metadata", metadata)

        if self.schema_version != PROTOCOL_PROVIDER_EVIDENCE_SCHEMA:
            raise ProtocolExecutionError(
                f"unsupported ProtocolProviderEvidence@2 schema: "
                f"{self.schema_version!r}"
            )

        if not self.content_digest:
            object.__setattr__(
                self,
                "content_digest",
                _digest_of(
                    {
                        "assumptions": self.assumptions.to_dict(),  # type: ignore[union-attr]
                        "attack": self.attack.to_dict(),  # type: ignore[union-attr]
                        "disposition": (
                            self.disposition.value
                            if isinstance(self.disposition, ProtocolDisposition)
                            else self.disposition
                        ),
                        "document": self.document.to_dict(),  # type: ignore[union-attr]
                        "mode": (
                            self.mode.value
                            if isinstance(self.mode, ProtocolExecutionMode)
                            else self.mode
                        ),
                        "provider": (
                            self.provider.value
                            if isinstance(self.provider, ProtocolProviderKind)
                            else self.provider
                        ),
                        "request_digest": self.request_digest,
                        "request_id": self.request_id,
                    }
                ),
            )
        else:
            object.__setattr__(
                self,
                "content_digest",
                _sha256_hex(self.content_digest, "content_digest"),
            )

    @property
    def is_theorem_authority(self) -> bool:
        return False

    @property
    def is_proved(self) -> bool:
        return False

    @property
    def proof_established(self) -> bool:
        return False

    @property
    def satisfiability_established(self) -> bool:
        return False

    @property
    def theorem_established(self) -> bool:
        return False

    @property
    def attack_status(self) -> ProtocolAttackStatus:
        return self.attack.status  # type: ignore[return-value, union-attr]

    def claim_established(self, claim: ProtocolClaimKindV2 | str) -> bool:
        kind = (
            claim
            if isinstance(claim, ProtocolClaimKindV2)
            else ProtocolClaimKindV2(str(claim))
        )
        if kind is ProtocolClaimKindV2.PROTOCOL:
            return bool(self.protocol_established)
        if kind is ProtocolClaimKindV2.OTHER_PROVIDER_ASSUMPTIONS:
            return False
        return False

    def non_authoritative_claim(self, claim: ProtocolClaimKindV2 | str) -> bool:
        return non_authoritative_signal_establishes(
            claim,
            mock_output={} if self.mock_output_present else None,
            fallback_output={} if self.fallback_output_present else None,
            available=self.available,
            confidence=self.confidence,
            fluent_text="present" if self.fluent_text_present else None,
        )

    def establishes_other_provider(self, other: ProtocolProviderKind | str) -> bool:
        """Whether this provider's support establishes *other*'s assumptions."""

        return provider_assumptions_establish_other(
            self.provider,  # type: ignore[arg-type]
            other,
            source_available=self.available,
            source_supported=self.capability.supported_document,  # type: ignore[union-attr]
        )

    def bindings_complete(self) -> bool:
        """Whether provider, document, assumptions, and attack are all bound."""

        return bool(
            isinstance(self.provider, ProtocolProviderKind)
            and isinstance(self.document, ProtocolDocumentBindingV2)
            and self.document.document_id
            and self.document.document_digest
            and isinstance(self.assumptions, ProtocolAssumptionsBindingV2)
            and self.assumptions.provider is self.provider
            and isinstance(self.attack, ProtocolAttackBindingV2)
            and isinstance(self.capability, ProtocolCapabilityReceiptV2)
            and self.capability.provider is self.provider
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumptions": self.assumptions.to_dict(),  # type: ignore[union-attr]
            "attack": self.attack.to_dict(),  # type: ignore[union-attr]
            "attack_status": (
                self.attack.status.value  # type: ignore[union-attr]
                if isinstance(self.attack.status, ProtocolAttackStatus)  # type: ignore[union-attr]
                else self.attack.status  # type: ignore[union-attr]
            ),
            "authorizes_universal_proof": False,
            "authority_ceiling": (
                self.authority_ceiling.value
                if isinstance(self.authority_ceiling, ToolchainAuthorityCeiling)
                else self.authority_ceiling
            ),
            "available": self.available,
            "bindings_complete": self.bindings_complete(),
            "capability": self.capability.to_dict(),  # type: ignore[union-attr]
            "claim_other_provider_assumptions": False,
            "claim_proof": False,
            "claim_protocol": bool(self.protocol_established),
            "claim_satisfiability": False,
            "claim_theorem": False,
            "confidence": self.confidence,
            "content_digest": self.content_digest,
            "diagnostics": list(self.diagnostics),
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, ProtocolDisposition)
                else self.disposition
            ),
            "document": self.document.to_dict(),  # type: ignore[union-attr]
            "evidence_id": self.evidence_id,
            "external_tool_proof": self.external_tool_proof,
            "fallback_output_present": self.fallback_output_present,
            "fluent_text_present": self.fluent_text_present,
            "interface": self.interface,
            "is_proved": False,
            "is_theorem_authority": False,
            "metadata": _thaw_mapping(self.metadata),
            "mock_output_present": self.mock_output_present,
            "mode": (
                self.mode.value
                if isinstance(self.mode, ProtocolExecutionMode)
                else self.mode
            ),
            "proof_established": False,
            "protocol_established": self.protocol_established,
            "provider": (
                self.provider.value
                if isinstance(self.provider, ProtocolProviderKind)
                else self.provider
            ),
            "provider_identity": provider_logic_identity(
                self.provider  # type: ignore[arg-type]
            ).to_dict(),
            "receipt": None if self.receipt is None else dict(self.receipt),
            "request_digest": self.request_digest,
            "request_id": self.request_id,
            "result_authority": ResultAuthority.PROTOCOL.value,
            "result_status": (
                self.result_status.value
                if isinstance(self.result_status, ResultStatus)
                else self.result_status
            ),
            "role": (
                self.role.value if isinstance(self.role, ToolRole) else self.role
            ),
            "satisfiability_established": False,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "theorem_established": False,
            "translation_ceiling": (
                self.translation_ceiling.value
                if isinstance(self.translation_ceiling, EvidenceAuthority)
                else self.translation_ceiling
            ),
        }


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProtocolExecutionResultV2:
    """Typed result of one protocol provider execution.

    Interface: ``ProtocolExecutionResult@2``.
    """

    request: ProtocolExecutionRequestV2
    evidence: ProtocolProviderEvidenceV2
    backend_result: ProtocolResult | None = None
    backend_outcome: Mapping[str, Any] | None = None
    schema_version: str = PROTOCOL_EXECUTION_RESULT_SCHEMA

    interface: ClassVar[str] = PROTOCOL_EXECUTION_RESULT_V2_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.request, ProtocolExecutionRequestV2):
            raise ProtocolExecutionError(
                "request must be a ProtocolExecutionRequestV2"
            )
        if not isinstance(self.evidence, ProtocolProviderEvidenceV2):
            raise ProtocolExecutionError(
                "evidence must be a ProtocolProviderEvidenceV2"
            )
        if self.schema_version != PROTOCOL_EXECUTION_RESULT_SCHEMA:
            raise ProtocolExecutionError(
                f"unsupported ProtocolExecutionResult@2 schema: "
                f"{self.schema_version!r}"
            )
        if self.backend_result is not None and not isinstance(
            self.backend_result, ProtocolResult
        ):
            raise ProtocolExecutionError(
                "backend_result must be ProtocolResult or None"
            )
        if self.backend_outcome is not None:
            outcome = _require_mapping(self.backend_outcome, "backend_outcome")
            object.__setattr__(
                self,
                "backend_outcome",
                dict(_freeze_mapping(outcome, "backend_outcome")),
            )
        if self.request.provider is not self.evidence.provider:  # type: ignore[comparison-overlap]
            raise ProtocolAuthorityError(
                "result provider must match request provider"
            )

    @property
    def disposition(self) -> ProtocolDisposition:
        return self.evidence.disposition  # type: ignore[return-value]

    @property
    def provider(self) -> ProtocolProviderKind:
        return self.evidence.provider  # type: ignore[return-value]

    @property
    def protocol_established(self) -> bool:
        return bool(self.evidence.protocol_established)

    @property
    def is_proved(self) -> bool:
        return False

    @property
    def is_theorem_authority(self) -> bool:
        return False

    @property
    def attack_status(self) -> ProtocolAttackStatus:
        return self.evidence.attack_status

    def to_dict(self) -> dict[str, Any]:
        return {
            "attack_status": (
                self.attack_status.value
                if isinstance(self.attack_status, ProtocolAttackStatus)
                else self.attack_status
            ),
            "backend_outcome": (
                None if self.backend_outcome is None else dict(self.backend_outcome)
            ),
            "backend_result": (
                None if self.backend_result is None else self.backend_result.to_dict()
            ),
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, ProtocolDisposition)
                else self.disposition
            ),
            "evidence": self.evidence.to_dict(),
            "interface": self.interface,
            "is_proved": False,
            "is_theorem_authority": False,
            "protocol_established": self.protocol_established,
            "provider": self.provider.value,
            "request": self.request.to_dict(),
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class ProtocolExecutionEngineV2:
    """Execute ProVerif / Tamarin on independent assumption surfaces.

    Interface owner: ``ProtocolProviderEvidence@2``.
    """

    INTERFACE: ClassVar[str] = PROTOCOL_PROVIDER_EVIDENCE_V2_INTERFACE
    interface: ClassVar[str] = PROTOCOL_PROVIDER_EVIDENCE_V2_INTERFACE
    VERSION: ClassVar[str] = PROTOCOL_EXECUTION_V2_MODULE_VERSION
    TASK_ID: ClassVar[str] = PROTOCOL_EXECUTION_V2_TASK_ID
    GOAL_ID: ClassVar[str] = PROTOCOL_EXECUTION_V2_GOAL_ID

    def __init__(
        self,
        *,
        proverif: ProVerifBackend | None = None,
        tamarin: TamarinBackend | None = None,
        runner: BoundedToolRunner | None = None,
    ) -> None:
        self._runner = runner
        self._proverif = proverif or ProVerifBackend(runner=runner)
        self._tamarin = tamarin or TamarinBackend(runner=runner)
        if not isinstance(self._proverif, ProVerifBackend):
            raise ProtocolExecutionError("proverif must be a ProVerifBackend")
        if not isinstance(self._tamarin, TamarinBackend):
            raise ProtocolExecutionError("tamarin must be a TamarinBackend")

    def backend(
        self, provider: ProtocolProviderKind | str
    ) -> ProVerifBackend | TamarinBackend:
        kind = normalize_protocol_provider(provider)
        if kind is ProtocolProviderKind.PROVERIF:
            return self._proverif
        return self._tamarin

    def capability_of(
        self, provider: ProtocolProviderKind | str
    ) -> ProtocolProviderCapability:
        """Return only the named provider's capability (never another's)."""

        return capability_for(provider)

    def capability_receipt(
        self,
        provider: ProtocolProviderKind | str,
        *,
        document: ProtocolIR | None = None,
    ) -> ProtocolCapabilityReceiptV2:
        kind = normalize_protocol_provider(provider)
        backend = self.backend(kind)
        available = backend.is_available()
        supported = True
        reason = ""
        if document is not None:
            cap = capability_for(kind)
            unsupported = [
                claim.claim_id
                for claim in document.claims
                if (
                    claim.kind.value
                    if isinstance(claim.kind, ProtocolClaimKind)
                    else str(claim.kind)
                )
                not in cap.supported_claim_kinds
            ]
            if unsupported:
                supported = False
                reason = (
                    "document contains claims outside "
                    f"{kind.value} ceiling: {', '.join(unsupported)}"
                )
        if not available and not reason:
            reason = f"{kind.value} executable unavailable"
        return ProtocolCapabilityReceiptV2(
            provider=kind,
            available=available,
            supported_document=supported,
            capability=capability_for(kind).to_dict(),
            reason=reason,
            establishes_other_providers=False,
        )

    def probe_all(self) -> dict[ProtocolProviderKind, ProtocolCapabilityReceiptV2]:
        """Probe each provider independently; never cross-establish assumptions."""

        return {
            kind: self.capability_receipt(kind) for kind in ProtocolProviderKind
        }

    def execute(
        self,
        request: ProtocolExecutionRequestV2 | Mapping[str, Any],
    ) -> ProtocolExecutionResultV2:
        """Execute one typed protocol request on a single provider path."""

        req = (
            request
            if isinstance(request, ProtocolExecutionRequestV2)
            else ProtocolExecutionRequestV2(
                **_filter_keys(
                    _require_mapping(request, "request"),
                    {
                        "request_id",
                        "provider",
                        "document",
                        "source",
                        "source_format",
                        "mode",
                        "source_ref_ids",
                        "bounds",
                        "mock_output",
                        "fallback_output",
                        "available",
                        "confidence",
                        "fluent_text",
                        "metadata",
                        "schema_version",
                    },
                )
            )
        )
        request_digest = _digest_of(req.to_dict())
        document: ProtocolIR | None = req.document  # type: ignore[assignment]
        provider: ProtocolProviderKind = req.provider  # type: ignore[assignment]
        capability = self.capability_receipt(provider, document=document)

        if req.has_mock_output or req.mode is ProtocolExecutionMode.MOCK:
            return self._rejected(
                req,
                request_digest=request_digest,
                disposition=ProtocolDisposition.MOCK_REJECTED,
                mode=ProtocolExecutionMode.MOCK,
                capability=capability,
                mock_output_present=True,
                fallback_output_present=req.has_fallback_output,
                diagnostics=(
                    "mock_output_cannot_establish_protocol",
                    "mock_output_cannot_establish_proof",
                    "mock_output_cannot_establish_theorem",
                    "mock_output_cannot_establish_other_provider_assumptions",
                ),
            )

        if req.has_fallback_output or req.mode is ProtocolExecutionMode.FALLBACK:
            return self._rejected(
                req,
                request_digest=request_digest,
                disposition=ProtocolDisposition.FALLBACK_REJECTED,
                mode=ProtocolExecutionMode.FALLBACK,
                capability=capability,
                mock_output_present=False,
                fallback_output_present=True,
                diagnostics=(
                    "fallback_output_cannot_establish_protocol",
                    "fallback_output_cannot_establish_proof",
                    "fallback_output_cannot_establish_other_provider_assumptions",
                ),
            )

        return self._execute_engine(
            req,
            request_digest=request_digest,
            capability=capability,
        )

    def execute_split_providers(
        self,
        document: ProtocolIR | Mapping[str, Any],
        *,
        request_id_prefix: str = "req:protocol:split",
        bounds: ExecutionBounds | None = None,
    ) -> dict[ProtocolProviderKind, ProtocolExecutionResultV2]:
        """Run each provider path independently; results never cross-establish."""

        doc = _document_from_value(document)
        results: dict[ProtocolProviderKind, ProtocolExecutionResultV2] = {}
        for kind in ProtocolProviderKind:
            req = ProtocolExecutionRequestV2(
                request_id=f"{request_id_prefix}:{kind.value}",
                provider=kind,
                document=doc,
                bounds=bounds,
                mode=ProtocolExecutionMode.ENGINE,
            )
            results[kind] = self.execute(req)
            for other in ProtocolProviderKind:
                if other is kind:
                    continue
                if results[kind].evidence.establishes_other_provider(other):
                    raise ProtocolAuthorityError(
                        f"{kind.value} result established {other.value} assumptions"
                    )
        return results

    # --- internal paths ----------------------------------------------------

    def _execute_engine(
        self,
        req: ProtocolExecutionRequestV2,
        *,
        request_digest: str,
        capability: ProtocolCapabilityReceiptV2,
    ) -> ProtocolExecutionResultV2:
        document: ProtocolIR | None = req.document  # type: ignore[assignment]
        provider: ProtocolProviderKind = req.provider  # type: ignore[assignment]
        bounds: ExecutionBounds = req.bounds  # type: ignore[assignment]
        backend = self.backend(provider)
        cap = capability_for(provider)

        payload: dict[str, Any]
        if document is not None:
            payload = {
                "encoding": "protocol-ir",
                "protocol_ir": document.to_dict(),
            }
        else:
            payload = {
                "encoding": req.source_format or cap.source_format,
                "source": req.source,
            }

        backend_request = BackendRequest(
            request_id=req.request_id,
            claim_id=f"claim:protocol:{req.request_id}",
            declaration_id=f"declaration:protocol:{req.request_id}",
            claim_digest=request_digest,
            obligation_id=f"obligation:protocol:{req.request_id}",
            obligation_digest=request_digest,
            assumption_ids=(),
            logic_family="cryptographic_protocol",
            query_kind=QueryKind.THEOREM_PROOF,
            bounds=bounds,
            payload=FrozenMap(payload),
            requested_backend_id=backend.backend_id,
        )

        outcome = backend.run(backend_request)
        return self._from_backend_outcome(
            req,
            request_digest=request_digest,
            capability=capability,
            outcome=outcome,
        )

    def _from_backend_outcome(
        self,
        req: ProtocolExecutionRequestV2,
        *,
        request_digest: str,
        capability: ProtocolCapabilityReceiptV2,
        outcome: ProVerifBackendOutcome | TamarinBackendOutcome,
    ) -> ProtocolExecutionResultV2:
        provider: ProtocolProviderKind = req.provider  # type: ignore[assignment]
        result = outcome.result
        if not isinstance(result, ProtocolResult):
            # TypedBackendResult with protocol authority still accepted.
            if result.authority is not ResultAuthority.PROTOCOL:
                raise ProtocolAuthorityError(
                    "backend outcome must carry protocol authority"
                )

        status = result.status
        disposition = _status_to_disposition(status)
        quarantine = outcome.receipt.quarantine
        if quarantine is not None and disposition not in {
            ProtocolDisposition.ATTACK_FOUND,
            ProtocolDisposition.SECURE,
            ProtocolDisposition.UNAVAILABLE,
            ProtocolDisposition.UNSUPPORTED,
            ProtocolDisposition.TIMEOUT,
        }:
            disposition = ProtocolDisposition.QUARANTINED

        claim_outcomes = [item.to_dict() for item in outcome.receipt.claim_outcomes]
        attack = ProtocolAttackBindingV2.from_outcomes(
            disposition=disposition,
            claim_outcomes=claim_outcomes,
        )

        # If attack found but traces missing/non-replayable, keep ATTACK_FOUND
        # only when the backend status says so; otherwise quarantine already set.
        tool_version = outcome.receipt.toolchain.tool_version
        dep_version = ""
        if outcome.receipt.toolchain.dependencies:
            dep_version = outcome.receipt.toolchain.dependencies[0].version

        assumptions = ProtocolAssumptionsBindingV2.from_capability(
            capability_for(provider),
            tool_version=tool_version,
            dependency_version=dep_version,
        )

        compile_result = outcome.compile_result
        if req.document is not None:
            document_binding = ProtocolDocumentBindingV2.from_document(
                req.document,  # type: ignore[arg-type]
                source_format=compile_result.source_format,
                compile_digest=compile_result.source_digest,
            )
        else:
            # Source-only path: bind claim identities from compile output.
            claim_map: Mapping[str, Any]
            if hasattr(compile_result, "claim_queries"):
                claim_map = compile_result.claim_queries.to_dict()  # type: ignore[attr-defined]
            elif hasattr(compile_result, "claim_lemmas"):
                claim_map = compile_result.claim_lemmas.to_dict()  # type: ignore[attr-defined]
            else:
                claim_map = {}
            document_binding = ProtocolDocumentBindingV2(
                document_id=f"document:source:{compile_result.source_digest[:24]}",
                document_digest=compile_result.source_digest,
                equational_theories=tuple(compile_result.equational_theories),
                role_ids=(),
                rewrite_fact_ids=(),
                channel_ids=(),
                event_ids=(),
                claim_ids=tuple(claim_map.keys()),
                claim_kinds=(),
                adversary_kind="dolev_yao",
                adversary_id="adversary:symbolic",
                source_format=compile_result.source_format,
                compile_digest=compile_result.source_digest,
            )

        protocol_established = status in {
            ResultStatus.SECURE,
            ResultStatus.ATTACK_FOUND,
        } and disposition in {
            ProtocolDisposition.SECURE,
            ProtocolDisposition.ATTACK_FOUND,
        }

        translation_ceiling = (
            EvidenceAuthority.BOUNDED
            if protocol_established
            else EvidenceAuthority.NONE
        )

        evidence = ProtocolProviderEvidenceV2(
            evidence_id=f"evidence:protocol:{req.request_id}",
            request_id=req.request_id,
            request_digest=request_digest,
            provider=provider,
            disposition=disposition,
            mode=ProtocolExecutionMode.ENGINE,
            document=document_binding,
            assumptions=assumptions,
            attack=attack,
            capability=capability,
            source_ref_ids=req.source_ref_ids,
            result_authority=ResultAuthority.PROTOCOL,
            result_status=status,
            role=ToolRole.AUTHORITY,
            authority_ceiling=ToolchainAuthorityCeiling.PROTOCOL,
            translation_ceiling=translation_ceiling,
            protocol_established=protocol_established,
            mock_output_present=False,
            fallback_output_present=False,
            available=capability.available,
            confidence=req.confidence,
            fluent_text_present=bool(req.fluent_text),
            external_tool_proof=protocol_established,
            authorizes_universal_proof=False,
            receipt=_evidence_receipt_payload(outcome.receipt),
            diagnostics=tuple(result.diagnostics),
            metadata={},
        )

        backend_result = result if isinstance(result, ProtocolResult) else None
        if backend_result is None and result.authority is ResultAuthority.PROTOCOL:
            # Reconstruct ProtocolResult from TypedBackendResult fields.
            backend_result = ProtocolResult(
                result_id=result.result_id,
                backend_id=result.backend_id,
                backend_version=result.backend_version,
                authority=ResultAuthority.PROTOCOL,
                status=result.status,
                assumptions=result.assumptions,
                bounds=result.bounds,
                translation_ceiling=result.translation_ceiling,
                usage=result.usage,
                witness=result.witness.to_dict()
                if hasattr(result.witness, "to_dict")
                else {},
                diagnostics=result.diagnostics,
                reason=result.reason,
                metadata=result.metadata.to_dict()
                if hasattr(result.metadata, "to_dict")
                else {},
            )

        return ProtocolExecutionResultV2(
            request=req,
            evidence=evidence,
            backend_result=backend_result,
            backend_outcome=_evidence_receipt_payload(outcome),
        )

    def _rejected(
        self,
        req: ProtocolExecutionRequestV2,
        *,
        request_digest: str,
        disposition: ProtocolDisposition,
        mode: ProtocolExecutionMode,
        capability: ProtocolCapabilityReceiptV2,
        mock_output_present: bool,
        fallback_output_present: bool,
        diagnostics: Sequence[str],
    ) -> ProtocolExecutionResultV2:
        provider: ProtocolProviderKind = req.provider  # type: ignore[assignment]
        cap = capability_for(provider)
        if req.document is not None:
            document_binding = ProtocolDocumentBindingV2.from_document(
                req.document,  # type: ignore[arg-type]
                source_format=cap.source_format,
            )
        else:
            digest = (
                content_sha256(req.source.encode("utf-8"))
                if req.source
                else "0" * 64
            )
            document_binding = ProtocolDocumentBindingV2(
                document_id=f"document:rejected:{req.request_id}",
                document_digest=digest if len(digest) == 64 else content_sha256(b""),
                equational_theories=(EquationalTheory.FREE.value,),
                role_ids=(),
                rewrite_fact_ids=(),
                channel_ids=(),
                event_ids=(),
                claim_ids=(),
                claim_kinds=(),
                adversary_kind="dolev_yao",
                adversary_id="adversary:symbolic",
                source_format=req.source_format or cap.source_format,
            )
            if len(document_binding.document_digest) != 64:
                # Ensure valid digest for empty edge cases.
                pass

        assumptions = ProtocolAssumptionsBindingV2.from_capability(cap)
        attack = ProtocolAttackBindingV2(status=ProtocolAttackStatus.NONE)
        evidence = ProtocolProviderEvidenceV2(
            evidence_id=f"evidence:protocol:{req.request_id}",
            request_id=req.request_id,
            request_digest=request_digest,
            provider=provider,
            disposition=disposition,
            mode=mode,
            document=document_binding,
            assumptions=assumptions,
            attack=attack,
            capability=capability,
            source_ref_ids=req.source_ref_ids,
            result_authority=ResultAuthority.PROTOCOL,
            result_status=ResultStatus.UNKNOWN,
            role=ToolRole.AUTHORITY,
            authority_ceiling=ToolchainAuthorityCeiling.PROTOCOL,
            translation_ceiling=EvidenceAuthority.NONE,
            protocol_established=False,
            mock_output_present=mock_output_present,
            fallback_output_present=fallback_output_present,
            available=capability.available,
            confidence=req.confidence,
            fluent_text_present=bool(req.fluent_text),
            external_tool_proof=False,
            authorizes_universal_proof=False,
            receipt=None,
            diagnostics=tuple(diagnostics),
            metadata={},
        )
        return ProtocolExecutionResultV2(
            request=req,
            evidence=evidence,
            backend_result=None,
            backend_outcome=None,
        )


# ---------------------------------------------------------------------------
# Convenience entry points
# ---------------------------------------------------------------------------


def execute_protocol(
    document: ProtocolIR | Mapping[str, Any] | None = None,
    *,
    provider: ProtocolProviderKind | str,
    request_id: str = "req:protocol:1",
    source: str = "",
    source_format: str = "",
    bounds: ExecutionBounds | None = None,
    engine: ProtocolExecutionEngineV2 | None = None,
    **kwargs: Any,
) -> ProtocolExecutionResultV2:
    """Execute one protocol document/source against a single provider."""

    eng = engine or ProtocolExecutionEngineV2()
    req = ProtocolExecutionRequestV2(
        request_id=request_id,
        provider=provider,
        document=document,
        source=source,
        source_format=source_format,
        bounds=bounds,
        **kwargs,
    )
    return eng.execute(req)


def execute_proverif(
    document: ProtocolIR | Mapping[str, Any] | None = None,
    *,
    request_id: str = "req:proverif:1",
    source: str = "",
    bounds: ExecutionBounds | None = None,
    engine: ProtocolExecutionEngineV2 | None = None,
    **kwargs: Any,
) -> ProtocolExecutionResultV2:
    return execute_protocol(
        document,
        provider=ProtocolProviderKind.PROVERIF,
        request_id=request_id,
        source=source,
        source_format="pv" if source else "",
        bounds=bounds,
        engine=engine,
        **kwargs,
    )


def execute_tamarin(
    document: ProtocolIR | Mapping[str, Any] | None = None,
    *,
    request_id: str = "req:tamarin:1",
    source: str = "",
    bounds: ExecutionBounds | None = None,
    engine: ProtocolExecutionEngineV2 | None = None,
    **kwargs: Any,
) -> ProtocolExecutionResultV2:
    return execute_protocol(
        document,
        provider=ProtocolProviderKind.TAMARIN,
        request_id=request_id,
        source=source,
        source_format="spthy" if source else "",
        bounds=bounds,
        engine=engine,
        **kwargs,
    )


__all__ = [
    "PROVERIF_CAPABILITY",
    "PROTOCOL_EXECUTION_V2_GOAL_ID",
    "PROTOCOL_EXECUTION_V2_MODULE_VERSION",
    "PROTOCOL_EXECUTION_V2_TASK_ID",
    "PROTOCOL_PROVIDER_EVIDENCE_V2_INTERFACE",
    "TAMARIN_CAPABILITY",
    "ProtocolAssumptionsBindingV2",
    "ProtocolAttackBindingV2",
    "ProtocolAttackStatus",
    "ProtocolAuthorityError",
    "ProtocolCapabilityReceiptV2",
    "ProtocolClaimKindV2",
    "ProtocolDisposition",
    "ProtocolDocumentBindingV2",
    "ProtocolExecutionEngineV2",
    "ProtocolExecutionError",
    "ProtocolExecutionMode",
    "ProtocolExecutionRequestV2",
    "ProtocolExecutionResultV2",
    "ProtocolProcessModel",
    "ProtocolProviderCapability",
    "ProtocolProviderEvidenceV2",
    "ProtocolProviderKind",
    "capability_for",
    "execute_protocol",
    "execute_proverif",
    "execute_tamarin",
    "non_authoritative_signal_establishes",
    "normalize_protocol_provider",
    "provider_assumptions_establish_other",
    "provider_logic_identity",
]
