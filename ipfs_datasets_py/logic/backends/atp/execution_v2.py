"""Execute Vampire and E with typed TPTP/TSTP reconstruction (LFP2-033).

Interface: ``ATPProviderEvidence@2``

Runs FOL/TFF obligations through Vampire and E with:

* exact input profiles (CNF / FOF / TFF native; THF fail-closed);
* exact translation assumptions for DCEC / TDFOL (labeled *translated*,
  never native);
* SZS status and TSTP proof-candidate parsing via ``TSTPFrontend@1``;
* proof / countermodel reconstruction bindings; and
* a hard fail-closed rule that **ATP success remains candidate evidence
  until independently checked and replayed** — mock, fallback, availability,
  confidence, and fluent text never establish theorem authority.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.atp.adapters import (
    ATPAdapterOutcome,
    ATPCountermodel,
    ATPProofObject,
    ATPSourceBinding,
    EProverBackend,
    MalformedATPOutput,
    SZSStatus,
    VampireBackend,
    parse_szs_status,
)
from ipfs_datasets_py.logic.backends.process import (
    BoundedToolRunner,
    RawProcessResult,
)
from ipfs_datasets_py.logic.backends.results import (
    ResultAuthority,
    ResultStatus,
    TypedBackendResult,
)
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendRequest,
    ExecutionBounds,
    QueryKind,
)
from ipfs_datasets_py.logic.parsers.tptp_v2 import (
    TSTPFrontend,
    TSTPProofRecord,
    parse_tptp_v2,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    ParseStatus,
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

ATP_PROVIDER_EVIDENCE_V2_INTERFACE: Final = "ATPProviderEvidence@2"
ATP_EXECUTION_REQUEST_V2_INTERFACE: Final = "AtpExecutionRequest@2"
ATP_EXECUTION_RESULT_V2_INTERFACE: Final = "AtpExecutionResult@2"
ATP_PROFILE_BINDING_V2_INTERFACE: Final = "AtpProfileBinding@2"
ATP_TRANSLATION_BINDING_V2_INTERFACE: Final = "AtpTranslationBinding@2"
ATP_SZS_BINDING_V2_INTERFACE: Final = "AtpSzsBinding@2"
ATP_PROOF_BINDING_V2_INTERFACE: Final = "AtpProofBinding@2"
ATP_COUNTERMODEL_BINDING_V2_INTERFACE: Final = "AtpCountermodelBinding@2"
ATP_REPLAY_RECEIPT_V2_INTERFACE: Final = "AtpReplayReceipt@2"

ATP_PROVIDER_EVIDENCE_SCHEMA: Final = "atp-provider-evidence/v2"
ATP_EXECUTION_REQUEST_SCHEMA: Final = "atp-execution-request/v2"
ATP_EXECUTION_RESULT_SCHEMA: Final = "atp-execution-result/v2"
ATP_PROFILE_BINDING_SCHEMA: Final = "atp-profile-binding/v2"
ATP_TRANSLATION_BINDING_SCHEMA: Final = "atp-translation-binding/v2"
ATP_SZS_BINDING_SCHEMA: Final = "atp-szs-binding/v2"
ATP_PROOF_BINDING_SCHEMA: Final = "atp-proof-binding/v2"
ATP_COUNTERMODEL_BINDING_SCHEMA: Final = "atp-countermodel-binding/v2"
ATP_REPLAY_RECEIPT_SCHEMA: Final = "atp-replay-receipt/v2"

ATP_EXECUTION_V2_MODULE_VERSION: Final = "1.0.0"
ATP_EXECUTION_V2_TASK_ID: Final = "LFP2-033"
ATP_EXECUTION_V2_GOAL_ID: Final = "LFP2-G060"

ATP_LANE_ID: Final = "atp"
ATP_EVIDENCE_KIND: Final = "atp"

_MAX_DIAGNOSTICS: Final = 64
_MAX_METADATA_BYTES: Final = 8_192
_MAX_SOURCE_REFS: Final = 64
_MAX_PROOF_CHARS: Final = 65_536
_MAX_MODEL_CHARS: Final = 65_536
_MAX_TSTP_STEPS: Final = 4_096

_FORBIDDEN_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "arbitrary_payload",
        "claimed_execution",
        "claimed_proof",
        "claimed_replay",
        "claimed_satisfiability",
        "claimed_theorem",
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

# Annotated-formula language tokens accepted as native Vampire/E input.
_NATIVE_PROFILE_TOKENS: Final[frozenset[str]] = frozenset({"cnf", "fof", "tff"})
_THF_TOKENS: Final[frozenset[str]] = frozenset({"thf", "tfx", "txf"})
_TRANSLATED_SOURCE_PROFILES: Final[frozenset[str]] = frozenset(
    {"dcec", "tdfol", "cec_dcec", "cec-dcec"}
)

_ANNOTATED_LANG_RE: Final = re.compile(
    r"\b(cnf|fof|tff|thf|tfx|txf)\s*\(",
    re.IGNORECASE,
)

_DEFAULT_TRANSLATION_ASSUMPTIONS: Final[Mapping[str, tuple[str, ...]]] = {
    "dcec": (
        "modal_operators_reified_as_predicates",
        "accessibility_relation_explicit",
        "epistemic_common_knowledge_unfolded",
        "not_native_vampire_e_surface",
    ),
    "tdfol": (
        "temporal_operators_reified_as_predicates",
        "time_sort_introduced",
        "finite_trace_or_unbounded_time_declared",
        "not_native_vampire_e_surface",
    ),
    "cec_dcec": (
        "modal_operators_reified_as_predicates",
        "accessibility_relation_explicit",
        "not_native_vampire_e_surface",
    ),
    "cec-dcec": (
        "modal_operators_reified_as_predicates",
        "accessibility_relation_explicit",
        "not_native_vampire_e_surface",
    ),
}


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


class AtpExecutionError(SyntaxContractError):
    """Raised when ATP execution v2 inputs are malformed."""


class AtpAuthorityError(AtpExecutionError):
    """Raised when a claim would exceed the ATP evidence receipt ceiling."""


class AtpProviderKind(StrEnum):
    """Closed set of ATP providers."""

    VAMPIRE = "vampire"
    EPROVER = "eprover"


class AtpExecutionMode(StrEnum):
    """How the ATP outcome was produced.

    Only ``pinned_solver`` and ``hermetic_fixture`` may produce candidate
    ATP evidence.  Mock and fallback never establish any claim.
    """

    PINNED_SOLVER = "pinned_solver"
    HERMETIC_FIXTURE = "hermetic_fixture"
    FALLBACK = "fallback"
    MOCK = "mock"


class AtpInputProfile(StrEnum):
    """Exact input profile admitted for Vampire/E execution."""

    CNF = "cnf"
    FOF = "fof"
    TFF = "tff"
    # Translated sources (not native Vampire/E surface).
    DCEC_TRANSLATED = "dcec_translated"
    TDFOL_TRANSLATED = "tdfol_translated"
    # Explicit unsupported until a separate profile admits them.
    THF_UNSUPPORTED = "thf_unsupported"
    UNKNOWN = "unknown"


class AtpSourceKind(StrEnum):
    """Whether the submitted TPTP source is native or a translation."""

    NATIVE = "native"
    TRANSLATED = "translated"
    UNSUPPORTED = "unsupported"


class AtpQueryMode(StrEnum):
    """Semantic question asked of the ATP backend."""

    THEOREM_PROOF = "theorem_proof"
    SATISFIABILITY = "satisfiability"


class AtpDisposition(StrEnum):
    """Closed set of ATP execution dispositions (typed outcomes)."""

    CANDIDATE_THEOREM = "candidate_theorem"
    CANDIDATE_UNSATISFIABLE = "candidate_unsatisfiable"
    CANDIDATE_SATISFIABLE = "candidate_satisfiable"
    CANDIDATE_COUNTERMODEL = "candidate_countermodel"
    RECONSTRUCTED = "reconstructed"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED_PROFILE = "unsupported_profile"
    MALFORMED = "malformed"
    ERROR = "error"
    MOCK_REJECTED = "mock_rejected"
    FALLBACK_REJECTED = "fallback_rejected"
    REPLAY_MISMATCH = "replay_mismatch"
    REPLAY_MATCHED = "replay_matched"
    TRANSLATED_CANDIDATE = "translated_candidate"


class AtpClaimKind(StrEnum):
    """Claims that mock / fallback / availability must never establish alone."""

    THEOREM = "theorem"
    PROOF = "proof"
    SATISFIABILITY = "satisfiability"
    COUNTERMODEL = "countermodel"
    RECONSTRUCTION = "reconstruction"


class AtpProofStatus(StrEnum):
    """Status of a TSTP/proof artifact on the evidence receipt."""

    ABSENT = "absent"
    CANDIDATE = "candidate"
    RECONSTRUCTED = "reconstructed"
    CHECKED = "checked"
    REJECTED = "rejected"


class AtpCountermodelStatus(StrEnum):
    """Status of a countermodel/model artifact on the evidence receipt."""

    ABSENT = "absent"
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    REJECTED = "rejected"


_PROVIDER_ALIASES: Final[dict[str, AtpProviderKind]] = {
    "vampire": AtpProviderKind.VAMPIRE,
    "atp_vampire": AtpProviderKind.VAMPIRE,
    "atp.vampire": AtpProviderKind.VAMPIRE,
    "eprover": AtpProviderKind.EPROVER,
    "e": AtpProviderKind.EPROVER,
    "e_prover": AtpProviderKind.EPROVER,
    "e-prover": AtpProviderKind.EPROVER,
    "atp_e": AtpProviderKind.EPROVER,
    "atp.e": AtpProviderKind.EPROVER,
}


def normalize_atp_provider(value: AtpProviderKind | str) -> AtpProviderKind:
    """Normalize provider labels into the closed Vampire/E set."""

    if isinstance(value, AtpProviderKind):
        return value
    key = str(value).strip().lower().replace("-", "_")
    if key in _PROVIDER_ALIASES:
        return _PROVIDER_ALIASES[key]
    # Dotted aliases (atp.vampire) after underscore normalization become atp.vampire
    dotted = str(value).strip().lower()
    if dotted in _PROVIDER_ALIASES:
        return _PROVIDER_ALIASES[dotted]
    raise AtpExecutionError(
        f"unsupported ATP provider: {value!r}; expected vampire or eprover"
    )


def provider_backend_id(provider: AtpProviderKind) -> str:
    if provider is AtpProviderKind.VAMPIRE:
        return "vampire"
    return "e"


def non_authoritative_signal_establishes(
    claim: AtpClaimKind | str,
    *,
    mock_output: object = None,
    fallback_output: object = None,
    available: bool | None = None,
    confidence: float | None = None,
    fluent_text: str | None = None,
) -> bool:
    """Always ``False``: non-solver signals never establish ATP claims."""

    del claim, mock_output, fallback_output, available, confidence, fluent_text
    return False


def atp_success_establishes_theorem(
    *,
    szs_status: str | SZSStatus | None = None,
    proof_present: bool = False,
    reconstruction_ok: bool = False,
    replay_matched: bool = False,
    available: bool | None = None,
    confidence: float | None = None,
) -> bool:
    """Always ``False``: ATP success alone never mints theorem authority.

    Acceptance LFP2-033: ATP success remains candidate evidence until checked
    and replayed — and even then only reconstruction authority, never theorem.
    """

    del (
        szs_status,
        proof_present,
        reconstruction_ok,
        replay_matched,
        available,
        confidence,
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
        raise AtpExecutionError(
            f"{field_name} must be one of: {allowed}; got {value!r}"
        ) from error


def _optional_bool(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise AtpExecutionError(f"{field_name} must be a boolean")


def _unit_interval(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AtpExecutionError(f"{field_name} must be numeric")
    conf = float(value)
    if conf != conf or conf < 0.0 or conf > 1.0:
        raise AtpExecutionError(f"{field_name} must be finite in [0, 1]")
    return conf


def _digest_of(payload: Mapping[str, Any]) -> str:
    return content_sha256(canonical_json_bytes(dict(payload)))


def _source_ref_ids(
    value: object, field_name: str = "source_ref_ids"
) -> tuple[str, ...]:
    items = _require_sequence(value, field_name)
    if len(items) > _MAX_SOURCE_REFS:
        raise AtpExecutionError(
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
            raise AtpAuthorityError(
                f"{field_name} rejects free-form authority/signal key {key!r}; "
                "use typed ATPProviderEvidence@2 fields only"
            )


def _bound_diagnostics(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    items = _require_sequence(value, "diagnostics")
    out: list[str] = []
    for index, item in enumerate(items[:_MAX_DIAGNOSTICS]):
        out.append(_text(item, f"diagnostics[{index}]", maximum=512))
    return tuple(out)


def _tptp_source_text(value: object, field_name: str = "source") -> str:
    """Normalize TPTP/TSTP source text for exact profile binding.

    Multi-line fixtures commonly carry a trailing newline from triple-quoted
    strings.  Surrounding whitespace is stripped so digests are stable while
    interior newlines are preserved.  NUL bytes and empty sources fail closed.
    """

    if type(value) is not str:
        raise AtpExecutionError(f"{field_name} must be a string")
    if "\x00" in value:
        raise AtpExecutionError(f"{field_name} must not contain NUL bytes")
    normalized = value.strip()
    if not normalized:
        raise AtpExecutionError(f"{field_name} must not be empty")
    if len(normalized) > 512_000:
        raise AtpExecutionError(
            f"{field_name} exceeds maximum length of 512000"
        )
    return normalized


def _multiline_excerpt(
    value: object,
    field_name: str,
    *,
    maximum: int,
) -> str:
    """Validate multi-line TSTP/proof excerpts without stripping content.

    Unlike identifier fields, proof and model excerpts may contain leading or
    trailing newlines from solver stdout.  Empty-after-strip and NUL fail closed.
    """

    if type(value) is not str:
        raise AtpExecutionError(f"{field_name} must be a string")
    if "\x00" in value:
        raise AtpExecutionError(f"{field_name} must not contain NUL bytes")
    if not value.strip():
        raise AtpExecutionError(f"{field_name} must not be empty")
    if len(value) > maximum:
        raise AtpExecutionError(
            f"{field_name} exceeds maximum length of {maximum}"
        )
    return value


def _default_bounds() -> ExecutionBounds:
    return ExecutionBounds(
        timeout_ms=5_000,
        max_steps=100_000,
        max_memory_bytes=64 * 1024 * 1024,
        max_output_bytes=65_536,
    )


def _coerce_bounds(value: object | None) -> ExecutionBounds:
    if value is None:
        return _default_bounds()
    if isinstance(value, ExecutionBounds):
        return value
    mapping = _require_mapping(value, "bounds")
    return ExecutionBounds(
        timeout_ms=int(mapping.get("timeout_ms", 5_000)),
        max_steps=int(mapping.get("max_steps", 100_000)),
        max_memory_bytes=int(mapping.get("max_memory_bytes", 64 * 1024 * 1024)),
        max_output_bytes=int(mapping.get("max_output_bytes", 65_536)),
    )


def _coerce_query_mode(value: object) -> AtpQueryMode:
    if isinstance(value, AtpQueryMode):
        return value
    if isinstance(value, QueryKind):
        if value is QueryKind.THEOREM_PROOF:
            return AtpQueryMode.THEOREM_PROOF
        if value is QueryKind.SATISFIABILITY:
            return AtpQueryMode.SATISFIABILITY
        raise AtpExecutionError(
            f"unsupported ATP query kind: {value.value!r}"
        )
    return _enum(value, AtpQueryMode, "query_mode")  # type: ignore[return-value]


def detect_input_profile(
    source: str,
    *,
    source_profile: str | AtpInputProfile | None = None,
) -> tuple[AtpInputProfile, AtpSourceKind, tuple[str, ...]]:
    """Detect exact input profile and source kind from TPTP text / labels.

    Returns ``(profile, source_kind, languages_found)``.
    """

    languages = tuple(
        sorted({match.group(1).lower() for match in _ANNOTATED_LANG_RE.finditer(source)})
    )
    explicit = ""
    if source_profile is not None:
        if isinstance(source_profile, AtpInputProfile):
            explicit = source_profile.value
        else:
            explicit = str(source_profile).strip().lower().replace("-", "_")

    if explicit in _TRANSLATED_SOURCE_PROFILES or explicit in {
        "dcec_translated",
        "tdfol_translated",
    }:
        if explicit in {"tdfol", "tdfol_translated"}:
            return (
                AtpInputProfile.TDFOL_TRANSLATED,
                AtpSourceKind.TRANSLATED,
                languages,
            )
        return (
            AtpInputProfile.DCEC_TRANSLATED,
            AtpSourceKind.TRANSLATED,
            languages,
        )

    if explicit in {"thf", "thf_unsupported", "tfx", "txf"}:
        return AtpInputProfile.THF_UNSUPPORTED, AtpSourceKind.UNSUPPORTED, languages

    if any(lang in _THF_TOKENS for lang in languages):
        return AtpInputProfile.THF_UNSUPPORTED, AtpSourceKind.UNSUPPORTED, languages

    if explicit in _NATIVE_PROFILE_TOKENS:
        return AtpInputProfile(explicit), AtpSourceKind.NATIVE, languages

    native = [lang for lang in languages if lang in _NATIVE_PROFILE_TOKENS]
    if not native:
        if languages:
            return AtpInputProfile.UNKNOWN, AtpSourceKind.UNSUPPORTED, languages
        # Empty / axiom-only text: default FOF when no language tokens present.
        return AtpInputProfile.FOF, AtpSourceKind.NATIVE, languages
    # Prefer most expressive admitted dialect when mixed.
    if "tff" in native:
        return AtpInputProfile.TFF, AtpSourceKind.NATIVE, languages
    if "fof" in native:
        return AtpInputProfile.FOF, AtpSourceKind.NATIVE, languages
    return AtpInputProfile.CNF, AtpSourceKind.NATIVE, languages


def translation_assumptions_for(
    profile: AtpInputProfile | str,
    *,
    extra: Sequence[str] = (),
) -> tuple[str, ...]:
    """Exact, closed translation assumptions for a profile."""

    key = profile.value if isinstance(profile, AtpInputProfile) else str(profile)
    base: list[str] = []
    if key in {
        AtpInputProfile.DCEC_TRANSLATED.value,
        "dcec",
        "cec_dcec",
        "cec-dcec",
    }:
        base.extend(_DEFAULT_TRANSLATION_ASSUMPTIONS["dcec"])
    elif key in {AtpInputProfile.TDFOL_TRANSLATED.value, "tdfol"}:
        base.extend(_DEFAULT_TRANSLATION_ASSUMPTIONS["tdfol"])
    for item in extra:
        text = _text(item, "translation_assumption", maximum=128)
        if text not in base:
            base.append(text)
    return tuple(base)


# ---------------------------------------------------------------------------
# Bindings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AtpProfileBindingV2:
    """Exact input profile bound into every ATP answer.

    Interface: ``AtpProfileBinding@2``.
    """

    profile: AtpInputProfile | str
    source_kind: AtpSourceKind | str
    languages: tuple[str, ...] | Sequence[str] = ()
    source_digest: str = ""
    encoding: str = "tptp"
    native_vampire_e: bool = False
    schema_version: str = ATP_PROFILE_BINDING_SCHEMA

    interface: ClassVar[str] = ATP_PROFILE_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "profile", _enum(self.profile, AtpInputProfile, "profile")
        )
        object.__setattr__(
            self,
            "source_kind",
            _enum(self.source_kind, AtpSourceKind, "source_kind"),
        )
        langs = tuple(
            _text(item, f"languages[{index}]", maximum=16)
            for index, item in enumerate(_require_sequence(self.languages, "languages"))
        )
        object.__setattr__(self, "languages", langs)
        if self.source_digest:
            object.__setattr__(
                self, "source_digest", _sha256_hex(self.source_digest, "source_digest")
            )
        else:
            object.__setattr__(self, "source_digest", "")
        object.__setattr__(
            self, "encoding", _text(self.encoding, "encoding", maximum=32)
        )
        object.__setattr__(
            self,
            "native_vampire_e",
            _optional_bool(self.native_vampire_e, "native_vampire_e"),
        )
        profile = self.profile  # type: ignore[assignment]
        kind = self.source_kind  # type: ignore[assignment]
        if profile is AtpInputProfile.THF_UNSUPPORTED:
            if kind is not AtpSourceKind.UNSUPPORTED:
                raise AtpExecutionError(
                    "THF profile requires source_kind=unsupported"
                )
            if self.native_vampire_e:
                raise AtpAuthorityError(
                    "THF cannot be marked native_vampire_e"
                )
        if profile in {
            AtpInputProfile.DCEC_TRANSLATED,
            AtpInputProfile.TDFOL_TRANSLATED,
        }:
            if kind is not AtpSourceKind.TRANSLATED:
                raise AtpExecutionError(
                    "DCEC/TDFOL profiles require source_kind=translated"
                )
            if self.native_vampire_e:
                raise AtpAuthorityError(
                    "DCEC/TDFOL must not be labeled native Vampire/E surface"
                )
        if profile in {
            AtpInputProfile.CNF,
            AtpInputProfile.FOF,
            AtpInputProfile.TFF,
        }:
            if kind is not AtpSourceKind.NATIVE:
                raise AtpExecutionError(
                    "CNF/FOF/TFF profiles require source_kind=native"
                )
        if self.schema_version != ATP_PROFILE_BINDING_SCHEMA:
            raise AtpExecutionError(
                f"unsupported profile binding schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "encoding": self.encoding,
            "interface": self.interface,
            "languages": list(self.languages),
            "native_vampire_e": self.native_vampire_e,
            "profile": (
                self.profile.value
                if isinstance(self.profile, AtpInputProfile)
                else self.profile
            ),
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "source_kind": (
                self.source_kind.value
                if isinstance(self.source_kind, AtpSourceKind)
                else self.source_kind
            ),
        }


@dataclass(frozen=True, slots=True)
class AtpTranslationBindingV2:
    """Exact translation assumptions bound into every ATP answer.

    Interface: ``AtpTranslationBinding@2``.

    Native profiles carry an empty assumption list and ``is_translated=False``.
    DCEC/TDFOL carry the closed assumption set and never claim native surface.
    """

    is_translated: bool
    source_profile: str
    target_profile: str = "tptp-fof"
    assumptions: tuple[str, ...] | Sequence[str] = ()
    assumption_digest: str = ""
    translation_receipt_id: str = ""
    labeled_native: bool = False
    schema_version: str = ATP_TRANSLATION_BINDING_SCHEMA

    interface: ClassVar[str] = ATP_TRANSLATION_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "is_translated", _optional_bool(self.is_translated, "is_translated")
        )
        object.__setattr__(
            self,
            "source_profile",
            _text(self.source_profile, "source_profile", maximum=64),
        )
        object.__setattr__(
            self,
            "target_profile",
            _text(self.target_profile, "target_profile", maximum=64),
        )
        assumptions = tuple(
            _text(item, f"assumptions[{index}]", maximum=128)
            for index, item in enumerate(
                _require_sequence(self.assumptions, "assumptions")
            )
        )
        object.__setattr__(self, "assumptions", assumptions)
        object.__setattr__(
            self,
            "labeled_native",
            _optional_bool(self.labeled_native, "labeled_native"),
        )
        if self.is_translated and self.labeled_native:
            raise AtpAuthorityError(
                "translated DCEC/TDFOL sources cannot be labeled native"
            )
        if self.is_translated and not assumptions:
            raise AtpExecutionError(
                "translated sources require exact non-empty translation assumptions"
            )
        if not self.is_translated and assumptions:
            raise AtpExecutionError(
                "native sources must not carry translation assumptions"
            )
        expected_digest = _digest_of({"assumptions": list(assumptions)})
        if self.assumption_digest:
            provided = _sha256_hex(self.assumption_digest, "assumption_digest")
            if provided != expected_digest:
                raise AtpExecutionError(
                    "assumption_digest does not match assumptions"
                )
            object.__setattr__(self, "assumption_digest", provided)
        else:
            object.__setattr__(self, "assumption_digest", expected_digest)
        if self.translation_receipt_id:
            object.__setattr__(
                self,
                "translation_receipt_id",
                _record_id(self.translation_receipt_id, "translation_receipt_id"),
            )
        else:
            object.__setattr__(self, "translation_receipt_id", "")
        if self.schema_version != ATP_TRANSLATION_BINDING_SCHEMA:
            raise AtpExecutionError(
                f"unsupported translation binding schema: {self.schema_version!r}"
            )

    @classmethod
    def native(cls, profile: AtpInputProfile | str) -> AtpTranslationBindingV2:
        name = profile.value if isinstance(profile, AtpInputProfile) else str(profile)
        return cls(
            is_translated=False,
            source_profile=name,
            target_profile=f"tptp-{name}",
            assumptions=(),
            labeled_native=True,
        )

    @classmethod
    def translated(
        cls,
        profile: AtpInputProfile | str,
        *,
        extra_assumptions: Sequence[str] = (),
        translation_receipt_id: str = "",
    ) -> AtpTranslationBindingV2:
        assumptions = translation_assumptions_for(profile, extra=extra_assumptions)
        source = (
            "dcec"
            if str(profile).startswith("dcec") or profile is AtpInputProfile.DCEC_TRANSLATED
            else "tdfol"
        )
        return cls(
            is_translated=True,
            source_profile=source,
            target_profile="tptp-fof",
            assumptions=assumptions,
            translation_receipt_id=translation_receipt_id
            or f"translation:atp:{source}:tptp-fof",
            labeled_native=False,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_digest": self.assumption_digest,
            "assumptions": list(self.assumptions),
            "interface": self.interface,
            "is_translated": self.is_translated,
            "labeled_native": self.labeled_native,
            "schema_version": self.schema_version,
            "source_profile": self.source_profile,
            "target_profile": self.target_profile,
            "translation_receipt_id": self.translation_receipt_id,
        }


@dataclass(frozen=True, slots=True)
class AtpSzsBindingV2:
    """Parsed SZS status bound to one ATP execution.

    Interface: ``AtpSzsBinding@2``.
    """

    status: str = ""
    present: bool = False
    unambiguous: bool = False
    raw_excerpt: str = ""
    schema_version: str = ATP_SZS_BINDING_SCHEMA

    interface: ClassVar[str] = ATP_SZS_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        if self.status:
            object.__setattr__(
                self, "status", _text(self.status, "status", maximum=64)
            )
        else:
            object.__setattr__(self, "status", "")
        object.__setattr__(self, "present", _optional_bool(self.present, "present"))
        object.__setattr__(
            self, "unambiguous", _optional_bool(self.unambiguous, "unambiguous")
        )
        if self.raw_excerpt:
            object.__setattr__(
                self,
                "raw_excerpt",
                _text(self.raw_excerpt, "raw_excerpt", maximum=256),
            )
        else:
            object.__setattr__(self, "raw_excerpt", "")
        if self.present and not self.status:
            raise AtpExecutionError("present SZS binding requires status")
        if self.schema_version != ATP_SZS_BINDING_SCHEMA:
            raise AtpExecutionError(
                f"unsupported SZS binding schema: {self.schema_version!r}"
            )

    @classmethod
    def empty(cls) -> AtpSzsBindingV2:
        return cls()

    @classmethod
    def from_status(cls, status: SZSStatus | str) -> AtpSzsBindingV2:
        value = status.value if isinstance(status, SZSStatus) else str(status)
        return cls(
            status=value,
            present=True,
            unambiguous=True,
            raw_excerpt=f"% SZS status {value}",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface": self.interface,
            "present": self.present,
            "raw_excerpt": self.raw_excerpt,
            "schema_version": self.schema_version,
            "status": self.status,
            "unambiguous": self.unambiguous,
        }


@dataclass(frozen=True, slots=True)
class AtpProofBindingV2:
    """TSTP/proof reconstruction binding.

    Interface: ``AtpProofBinding@2``.

    Unverified TSTP remains ``candidate``.  Checked reconstruction elevates
    status to ``checked`` but never mints theorem authority.
    """

    status: AtpProofStatus | str = AtpProofStatus.ABSENT
    present: bool = False
    verified: bool = False
    checked: bool = False
    proof_format: str = ""
    content_digest: str = ""
    step_count: int = 0
    step_names: tuple[str, ...] | Sequence[str] = ()
    checker_id: str = ""
    szs_status: str = ""
    text_excerpt: str = ""
    schema_version: str = ATP_PROOF_BINDING_SCHEMA

    interface: ClassVar[str] = ATP_PROOF_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "status", _enum(self.status, AtpProofStatus, "status")
        )
        for flag in ("present", "verified", "checked"):
            object.__setattr__(
                self, flag, _optional_bool(getattr(self, flag), flag)
            )
        if self.proof_format:
            object.__setattr__(
                self,
                "proof_format",
                _text(self.proof_format, "proof_format", maximum=64),
            )
        else:
            object.__setattr__(self, "proof_format", "")
        if self.content_digest:
            object.__setattr__(
                self,
                "content_digest",
                _sha256_hex(self.content_digest, "content_digest"),
            )
        else:
            object.__setattr__(self, "content_digest", "")
        if isinstance(self.step_count, bool) or not isinstance(self.step_count, int):
            raise AtpExecutionError("step_count must be an integer")
        if self.step_count < 0 or self.step_count > _MAX_TSTP_STEPS:
            raise AtpExecutionError("step_count out of bounds")
        steps = tuple(
            _text(item, f"step_names[{index}]", maximum=128)
            for index, item in enumerate(
                _require_sequence(self.step_names, "step_names")[:_MAX_TSTP_STEPS]
            )
        )
        object.__setattr__(self, "step_names", steps)
        if self.checker_id:
            object.__setattr__(
                self, "checker_id", _text(self.checker_id, "checker_id", maximum=128)
            )
        else:
            object.__setattr__(self, "checker_id", "")
        if self.szs_status:
            object.__setattr__(
                self, "szs_status", _text(self.szs_status, "szs_status", maximum=64)
            )
        else:
            object.__setattr__(self, "szs_status", "")
        if self.text_excerpt:
            object.__setattr__(
                self,
                "text_excerpt",
                _multiline_excerpt(
                    self.text_excerpt, "text_excerpt", maximum=_MAX_PROOF_CHARS
                ),
            )
        else:
            object.__setattr__(self, "text_excerpt", "")
        status = self.status  # type: ignore[assignment]
        if self.present and status is AtpProofStatus.ABSENT:
            raise AtpExecutionError("present proof cannot have status=absent")
        if self.verified and not self.checker_id:
            raise AtpAuthorityError("verified proof requires checker_id")
        if self.checked and not self.present:
            raise AtpAuthorityError("checked proof requires present artifact")
        if self.schema_version != ATP_PROOF_BINDING_SCHEMA:
            raise AtpExecutionError(
                f"unsupported proof binding schema: {self.schema_version!r}"
            )

    @classmethod
    def empty(cls) -> AtpProofBindingV2:
        return cls()

    @classmethod
    def from_proof_object(
        cls,
        proof: ATPProofObject,
        *,
        step_names: Sequence[str] = (),
        szs_status: str = "",
        checked: bool = False,
    ) -> AtpProofBindingV2:
        status = AtpProofStatus.CANDIDATE
        if proof.verified and checked:
            status = AtpProofStatus.CHECKED
        elif proof.verified:
            status = AtpProofStatus.RECONSTRUCTED
        excerpt = proof.content[:_MAX_PROOF_CHARS]
        # Use the same content-digest scheme as TSTP records so replay matches.
        digest = _digest_of({"content": proof.content})
        return cls(
            status=status,
            present=True,
            verified=proof.verified,
            checked=checked,
            proof_format=proof.proof_format,
            content_digest=digest,
            step_count=len(step_names),
            step_names=tuple(step_names),
            checker_id=proof.checker_id,
            szs_status=szs_status,
            text_excerpt=excerpt,
        )

    @classmethod
    def from_tstp_record(
        cls,
        record: TSTPProofRecord,
        *,
        content: str,
        checked: bool = False,
        checker_id: str = "",
    ) -> AtpProofBindingV2:
        digest = _digest_of({"content": content})
        verified = bool(checker_id) and checked
        status = AtpProofStatus.CANDIDATE
        if verified:
            status = AtpProofStatus.CHECKED
        elif checker_id:
            status = AtpProofStatus.RECONSTRUCTED
        return cls(
            status=status,
            present=True,
            verified=verified,
            checked=checked,
            proof_format="tstp",
            content_digest=digest,
            step_count=len(record.steps),
            step_names=record.step_names,
            checker_id=checker_id,
            szs_status=record.szs_status,
            text_excerpt=content[:_MAX_PROOF_CHARS],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "checker_id": self.checker_id,
            "content_digest": self.content_digest,
            "interface": self.interface,
            "present": self.present,
            "proof_format": self.proof_format,
            "schema_version": self.schema_version,
            "status": (
                self.status.value
                if isinstance(self.status, AtpProofStatus)
                else self.status
            ),
            "step_count": self.step_count,
            "step_names": list(self.step_names),
            "szs_status": self.szs_status,
            "text_excerpt": self.text_excerpt,
            "verified": self.verified,
        }


@dataclass(frozen=True, slots=True)
class AtpCountermodelBindingV2:
    """Countermodel / model reconstruction binding.

    Interface: ``AtpCountermodelBinding@2``.
    """

    status: AtpCountermodelStatus | str = AtpCountermodelStatus.ABSENT
    present: bool = False
    validated: bool = False
    model_format: str = ""
    model_digest: str = ""
    validator_id: str = ""
    model: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = ATP_COUNTERMODEL_BINDING_SCHEMA

    interface: ClassVar[str] = ATP_COUNTERMODEL_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            _enum(self.status, AtpCountermodelStatus, "status"),
        )
        object.__setattr__(self, "present", _optional_bool(self.present, "present"))
        object.__setattr__(
            self, "validated", _optional_bool(self.validated, "validated")
        )
        if self.model_format:
            object.__setattr__(
                self,
                "model_format",
                _text(self.model_format, "model_format", maximum=64),
            )
        else:
            object.__setattr__(self, "model_format", "")
        if self.model_digest:
            object.__setattr__(
                self,
                "model_digest",
                _sha256_hex(self.model_digest, "model_digest"),
            )
        else:
            object.__setattr__(self, "model_digest", "")
        if self.validator_id:
            object.__setattr__(
                self,
                "validator_id",
                _text(self.validator_id, "validator_id", maximum=128),
            )
        else:
            object.__setattr__(self, "validator_id", "")
        model = _freeze_mapping(self.model, "model")
        object.__setattr__(self, "model", model)
        if self.present and self.status is AtpCountermodelStatus.ABSENT:
            raise AtpExecutionError("present countermodel cannot have status=absent")
        if self.validated and not self.validator_id:
            raise AtpAuthorityError("validated countermodel requires validator_id")
        if self.schema_version != ATP_COUNTERMODEL_BINDING_SCHEMA:
            raise AtpExecutionError(
                f"unsupported countermodel binding schema: {self.schema_version!r}"
            )

    @classmethod
    def empty(cls) -> AtpCountermodelBindingV2:
        return cls()

    @classmethod
    def from_countermodel(
        cls, countermodel: ATPCountermodel
    ) -> AtpCountermodelBindingV2:
        status = (
            AtpCountermodelStatus.VALIDATED
            if countermodel.validated
            else AtpCountermodelStatus.CANDIDATE
        )
        return cls(
            status=status,
            present=True,
            validated=countermodel.validated,
            model_format=countermodel.model_format,
            model_digest=countermodel.model_digest,
            validator_id=countermodel.validator_id,
            model=countermodel.model.to_dict(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface": self.interface,
            "model": _thaw_mapping(self.model),
            "model_digest": self.model_digest,
            "model_format": self.model_format,
            "present": self.present,
            "schema_version": self.schema_version,
            "status": (
                self.status.value
                if isinstance(self.status, AtpCountermodelStatus)
                else self.status
            ),
            "validated": self.validated,
            "validator_id": self.validator_id,
        }


@dataclass(frozen=True, slots=True)
class AtpReplayReceiptV2:
    """Replay disposition for one ATP execution evidence receipt.

    Interface: ``AtpReplayReceipt@2``.

    ``replay_claimed`` requires matched source/proof digests and matching
    dispositions.  Success is never claimed beyond this receipt, and
    theorem authority is never minted by replay alone.
    """

    replay_id: str
    request_id: str
    source_digest: str
    original_disposition: AtpDisposition | str
    replayed_disposition: AtpDisposition | str
    proof_digest: str = ""
    original_szs: str = ""
    replayed_szs: str = ""
    matched: bool = False
    replay_claimed: bool = False
    checked: bool = False
    diagnostics: tuple[str, ...] = ()
    schema_version: str = ATP_REPLAY_RECEIPT_SCHEMA

    interface: ClassVar[str] = ATP_REPLAY_RECEIPT_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "replay_id", _record_id(self.replay_id, "replay_id")
        )
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "source_digest", _sha256_hex(self.source_digest, "source_digest")
        )
        object.__setattr__(
            self,
            "original_disposition",
            _enum(self.original_disposition, AtpDisposition, "original_disposition"),
        )
        object.__setattr__(
            self,
            "replayed_disposition",
            _enum(self.replayed_disposition, AtpDisposition, "replayed_disposition"),
        )
        if self.proof_digest:
            object.__setattr__(
                self, "proof_digest", _sha256_hex(self.proof_digest, "proof_digest")
            )
        else:
            object.__setattr__(self, "proof_digest", "")
        for name in ("original_szs", "replayed_szs"):
            value = getattr(self, name)
            if value:
                object.__setattr__(self, name, _text(value, name, maximum=64))
            else:
                object.__setattr__(self, name, "")
        matched = _optional_bool(self.matched, "matched")
        replay_claimed = _optional_bool(self.replay_claimed, "replay_claimed")
        checked = _optional_bool(self.checked, "checked")
        if replay_claimed and not matched:
            raise AtpAuthorityError(
                "replay_claimed requires matched disposition/szs/digests"
            )
        object.__setattr__(self, "matched", matched)
        object.__setattr__(self, "replay_claimed", replay_claimed)
        object.__setattr__(self, "checked", checked)
        object.__setattr__(self, "diagnostics", _bound_diagnostics(self.diagnostics))
        if self.schema_version != ATP_REPLAY_RECEIPT_SCHEMA:
            raise AtpExecutionError(
                f"unsupported replay receipt schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "diagnostics": list(self.diagnostics),
            "interface": self.interface,
            "matched": self.matched,
            "original_disposition": (
                self.original_disposition.value
                if isinstance(self.original_disposition, AtpDisposition)
                else self.original_disposition
            ),
            "original_szs": self.original_szs,
            "proof_digest": self.proof_digest,
            "replay_claimed": self.replay_claimed,
            "replay_id": self.replay_id,
            "replayed_disposition": (
                self.replayed_disposition.value
                if isinstance(self.replayed_disposition, AtpDisposition)
                else self.replayed_disposition
            ),
            "replayed_szs": self.replayed_szs,
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
        }


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AtpExecutionRequestV2:
    """Typed Vampire/E execution request.

    Interface: ``AtpExecutionRequest@2``.
    """

    request_id: str
    source: str
    provider: AtpProviderKind | str = AtpProviderKind.VAMPIRE
    query_mode: AtpQueryMode | str | QueryKind = AtpQueryMode.THEOREM_PROOF
    mode: AtpExecutionMode | str = AtpExecutionMode.HERMETIC_FIXTURE
    source_profile: str = ""
    encoding: str = "tptp"
    bounds: ExecutionBounds | Mapping[str, Any] | None = None
    source_ref_ids: tuple[str, ...] | Sequence[str] = ()
    translation_assumptions: tuple[str, ...] | Sequence[str] = ()
    translation_receipt_id: str = ""
    obligation_id: str = ""
    claim_id: str = ""
    require_replay: bool = True
    mock_output: Mapping[str, Any] | None = None
    fallback_output: Mapping[str, Any] | None = None
    available: bool = True
    confidence: float = 0.0
    fluent_text: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = ATP_EXECUTION_REQUEST_SCHEMA

    interface: ClassVar[str] = ATP_EXECUTION_REQUEST_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "provider", normalize_atp_provider(self.provider)
        )
        object.__setattr__(self, "source", _tptp_source_text(self.source, "source"))
        object.__setattr__(
            self, "query_mode", _coerce_query_mode(self.query_mode)
        )
        object.__setattr__(
            self, "mode", _enum(self.mode, AtpExecutionMode, "mode")
        )
        if self.source_profile:
            object.__setattr__(
                self,
                "source_profile",
                _text(self.source_profile, "source_profile", maximum=64),
            )
        else:
            object.__setattr__(self, "source_profile", "")
        object.__setattr__(
            self, "encoding", _text(self.encoding, "encoding", maximum=32)
        )
        object.__setattr__(self, "bounds", _coerce_bounds(self.bounds))
        object.__setattr__(
            self, "source_ref_ids", _source_ref_ids(self.source_ref_ids)
        )
        assumptions = tuple(
            _text(item, f"translation_assumptions[{index}]", maximum=128)
            for index, item in enumerate(
                _require_sequence(
                    self.translation_assumptions, "translation_assumptions"
                )
            )
        )
        object.__setattr__(self, "translation_assumptions", assumptions)
        if self.translation_receipt_id:
            object.__setattr__(
                self,
                "translation_receipt_id",
                _record_id(
                    self.translation_receipt_id, "translation_receipt_id"
                ),
            )
        else:
            object.__setattr__(self, "translation_receipt_id", "")
        if self.obligation_id:
            object.__setattr__(
                self,
                "obligation_id",
                _record_id(self.obligation_id, "obligation_id"),
            )
        else:
            object.__setattr__(self, "obligation_id", "")
        if self.claim_id:
            object.__setattr__(
                self, "claim_id", _record_id(self.claim_id, "claim_id")
            )
        else:
            object.__setattr__(self, "claim_id", "")
        object.__setattr__(
            self,
            "require_replay",
            _optional_bool(self.require_replay, "require_replay"),
        )
        if self.mock_output is not None:
            object.__setattr__(
                self,
                "mock_output",
                dict(_require_mapping(self.mock_output, "mock_output")),
            )
        if self.fallback_output is not None:
            object.__setattr__(
                self,
                "fallback_output",
                dict(_require_mapping(self.fallback_output, "fallback_output")),
            )
        object.__setattr__(
            self, "available", _optional_bool(self.available, "available")
        )
        object.__setattr__(
            self, "confidence", _unit_interval(self.confidence, "confidence")
        )
        if self.fluent_text:
            object.__setattr__(
                self,
                "fluent_text",
                _text(self.fluent_text, "fluent_text", maximum=4096),
            )
        else:
            object.__setattr__(self, "fluent_text", "")
        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_authority_metadata(metadata, "metadata")
        serialized = canonical_json_bytes(_thaw_mapping(metadata))
        if len(serialized) > _MAX_METADATA_BYTES:
            raise AtpExecutionError(
                f"metadata exceeds hard limit {_MAX_METADATA_BYTES} bytes"
            )
        object.__setattr__(self, "metadata", metadata)
        if self.schema_version != ATP_EXECUTION_REQUEST_SCHEMA:
            raise AtpExecutionError(
                f"unsupported request schema: {self.schema_version!r}"
            )

    @property
    def has_mock_output(self) -> bool:
        return self.mock_output is not None

    @property
    def has_fallback_output(self) -> bool:
        return self.fallback_output is not None

    @property
    def source_digest(self) -> str:
        return _digest_of(
            {"encoding": self.encoding, "source": self.source}
        )

    def to_dict(self) -> dict[str, Any]:
        bounds = self.bounds  # type: ignore[assignment]
        return {
            "available": self.available,
            "bounds": {
                "max_memory_bytes": bounds.max_memory_bytes,
                "max_output_bytes": bounds.max_output_bytes,
                "max_steps": bounds.max_steps,
                "timeout_ms": bounds.timeout_ms,
            },
            "claim_id": self.claim_id,
            "confidence": self.confidence,
            "encoding": self.encoding,
            "fallback_output": (
                None if self.fallback_output is None else dict(self.fallback_output)
            ),
            "fluent_text": self.fluent_text,
            "has_fallback_output": self.has_fallback_output,
            "has_mock_output": self.has_mock_output,
            "interface": self.interface,
            "metadata": _thaw_mapping(self.metadata),
            "mock_output": (
                None if self.mock_output is None else dict(self.mock_output)
            ),
            "mode": (
                self.mode.value
                if isinstance(self.mode, AtpExecutionMode)
                else self.mode
            ),
            "obligation_id": self.obligation_id,
            "provider": (
                self.provider.value
                if isinstance(self.provider, AtpProviderKind)
                else self.provider
            ),
            "query_mode": (
                self.query_mode.value
                if isinstance(self.query_mode, AtpQueryMode)
                else self.query_mode
            ),
            "request_id": self.request_id,
            "require_replay": self.require_replay,
            "schema_version": self.schema_version,
            "source": self.source,
            "source_digest": self.source_digest,
            "source_profile": self.source_profile,
            "source_ref_ids": list(self.source_ref_ids),
            "translation_assumptions": list(self.translation_assumptions),
            "translation_receipt_id": self.translation_receipt_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AtpExecutionRequestV2:
        payload = _require_mapping(value, "AtpExecutionRequestV2")
        allowed = {
            "request_id",
            "source",
            "provider",
            "query_mode",
            "mode",
            "source_profile",
            "encoding",
            "bounds",
            "source_ref_ids",
            "translation_assumptions",
            "translation_receipt_id",
            "obligation_id",
            "claim_id",
            "require_replay",
            "mock_output",
            "fallback_output",
            "available",
            "confidence",
            "fluent_text",
            "metadata",
            "schema_version",
        }
        return cls(
            **{
                key: payload[key]
                for key in allowed
                if key in payload
            }
        )


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AtpProviderEvidenceV2:
    """Vampire / E ATP execution evidence with typed TPTP/TSTP reconstruction.

    Interface: ``ATPProviderEvidence@2``.

    Authority rules (acceptance LFP2-033):

    * ATP success remains **candidate** until reconstruction is checked and
      replayed.
    * Checked+replayed reconstruction may reach ``ResultAuthority.RECONSTRUCTION``
      but never theorem.
    * Mock / fallback / availability / confidence / fluent text never establish
      theorem, proof, or satisfiability authority.
    * Input profile and translation assumptions are exact on every answer.
    * DCEC / TDFOL are labeled translated, never native.
    """

    evidence_id: str
    request_id: str
    request_digest: str
    provider: AtpProviderKind | str
    disposition: AtpDisposition | str
    mode: AtpExecutionMode | str
    query_mode: AtpQueryMode | str
    source_digest: str
    profile: AtpProfileBindingV2 | Mapping[str, Any]
    translation: AtpTranslationBindingV2 | Mapping[str, Any]
    szs: AtpSzsBindingV2 | Mapping[str, Any] | None = None
    proof: AtpProofBindingV2 | Mapping[str, Any] | None = None
    countermodel: AtpCountermodelBindingV2 | Mapping[str, Any] | None = None
    replay: AtpReplayReceiptV2 | Mapping[str, Any] | None = None
    obligation_id: str = ""
    solver_backend_id: str = ""
    solver_version: str = ""
    source_ref_ids: tuple[str, ...] | Sequence[str] = ()
    result_authority: ResultAuthority | str = ResultAuthority.CANDIDATE
    result_status: ResultStatus | str = ResultStatus.CANDIDATE
    role: ToolRole | str = ToolRole.CANDIDATE
    authority_ceiling: ToolchainAuthorityCeiling | str = (
        ToolchainAuthorityCeiling.CANDIDATE
    )
    translation_ceiling: EvidenceAuthority | str = EvidenceAuthority.ADVISORY
    candidate_established: bool = False
    reconstruction_established: bool = False
    theorem_established: bool = False
    proof_established: bool = False
    satisfiability_established: bool = False
    mock_output_present: bool = False
    fallback_output_present: bool = False
    available: bool = False
    confidence: float = 0.0
    fluent_text_present: bool = False
    bounds_exhausted: bool = False
    diagnostics: tuple[str, ...] = ()
    content_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = ATP_PROVIDER_EVIDENCE_SCHEMA

    interface: ClassVar[str] = ATP_PROVIDER_EVIDENCE_V2_INTERFACE

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
            self, "provider", normalize_atp_provider(self.provider)
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, AtpDisposition, "disposition"),
        )
        object.__setattr__(
            self, "mode", _enum(self.mode, AtpExecutionMode, "mode")
        )
        object.__setattr__(
            self, "query_mode", _coerce_query_mode(self.query_mode)
        )
        object.__setattr__(
            self, "source_digest", _sha256_hex(self.source_digest, "source_digest")
        )

        if isinstance(self.profile, AtpProfileBindingV2):
            profile = self.profile
        else:
            mapping = dict(_require_mapping(self.profile, "profile"))
            profile = AtpProfileBindingV2(
                **{
                    key: mapping[key]
                    for key in {
                        "profile",
                        "source_kind",
                        "languages",
                        "source_digest",
                        "encoding",
                        "native_vampire_e",
                        "schema_version",
                    }
                    if key in mapping
                }
            )
        object.__setattr__(self, "profile", profile)

        if isinstance(self.translation, AtpTranslationBindingV2):
            translation = self.translation
        else:
            mapping = dict(_require_mapping(self.translation, "translation"))
            translation = AtpTranslationBindingV2(
                **{
                    key: mapping[key]
                    for key in {
                        "is_translated",
                        "source_profile",
                        "target_profile",
                        "assumptions",
                        "assumption_digest",
                        "translation_receipt_id",
                        "labeled_native",
                        "schema_version",
                    }
                    if key in mapping
                }
            )
        object.__setattr__(self, "translation", translation)

        object.__setattr__(self, "szs", self._coerce_szs(self.szs))
        object.__setattr__(self, "proof", self._coerce_proof(self.proof))
        object.__setattr__(
            self, "countermodel", self._coerce_countermodel(self.countermodel)
        )
        object.__setattr__(self, "replay", self._coerce_replay(self.replay))

        if self.obligation_id:
            object.__setattr__(
                self,
                "obligation_id",
                _text(self.obligation_id, "obligation_id", maximum=256),
            )
        for optional_text in ("solver_backend_id", "solver_version"):
            value = getattr(self, optional_text)
            if value:
                object.__setattr__(
                    self,
                    optional_text,
                    _text(value, optional_text, maximum=128),
                )
            else:
                object.__setattr__(self, optional_text, "")

        object.__setattr__(
            self, "source_ref_ids", _source_ref_ids(self.source_ref_ids)
        )

        result_authority = (
            self.result_authority
            if isinstance(self.result_authority, ResultAuthority)
            else ResultAuthority(str(self.result_authority))
        )
        if result_authority not in {
            ResultAuthority.CANDIDATE,
            ResultAuthority.RECONSTRUCTION,
        }:
            raise AtpAuthorityError(
                "ATPProviderEvidence@2 result_authority must be candidate "
                f"or reconstruction; got {result_authority!r}"
            )
        object.__setattr__(self, "result_authority", result_authority)

        result_status = (
            self.result_status
            if isinstance(self.result_status, ResultStatus)
            else ResultStatus(str(self.result_status))
        )
        object.__setattr__(self, "result_status", result_status)

        role = self.role if isinstance(self.role, ToolRole) else ToolRole(str(self.role))
        if role not in {ToolRole.CANDIDATE, ToolRole.SHADOW}:
            raise AtpAuthorityError(
                f"ATPProviderEvidence@2 role must be candidate or shadow; got {role!r}"
            )
        object.__setattr__(self, "role", role)

        ceiling = (
            self.authority_ceiling
            if isinstance(self.authority_ceiling, ToolchainAuthorityCeiling)
            else ToolchainAuthorityCeiling(str(self.authority_ceiling))
        )
        if ceiling not in {
            ToolchainAuthorityCeiling.CANDIDATE,
            ToolchainAuthorityCeiling.RECONSTRUCTION,
        }:
            raise AtpAuthorityError(
                "ATPProviderEvidence@2 authority_ceiling must be candidate "
                "or reconstruction"
            )
        object.__setattr__(self, "authority_ceiling", ceiling)

        translation_ceiling = (
            self.translation_ceiling
            if isinstance(self.translation_ceiling, EvidenceAuthority)
            else EvidenceAuthority(str(self.translation_ceiling))
        )
        if translation_ceiling in {
            EvidenceAuthority.AUTHORITATIVE,
            EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        }:
            raise AtpAuthorityError(
                "ATPProviderEvidence@2 translation_ceiling cannot exceed advisory/bounded"
            )
        object.__setattr__(self, "translation_ceiling", translation_ceiling)

        for flag_name in (
            "candidate_established",
            "reconstruction_established",
            "theorem_established",
            "proof_established",
            "satisfiability_established",
            "mock_output_present",
            "fallback_output_present",
            "available",
            "fluent_text_present",
            "bounds_exhausted",
        ):
            object.__setattr__(
                self,
                flag_name,
                _optional_bool(getattr(self, flag_name), flag_name),
            )

        object.__setattr__(
            self, "confidence", _unit_interval(self.confidence, "confidence")
        )
        object.__setattr__(self, "diagnostics", _bound_diagnostics(self.diagnostics))

        # Hard rule: theorem is never established by ATP evidence.
        if self.theorem_established or self.proof_established:
            raise AtpAuthorityError(
                "ATPProviderEvidence@2 never establishes theorem or kernel proof; "
                "ATP success remains candidate until checked/replayed reconstruction"
            )

        mode = self.mode  # type: ignore[assignment]
        disposition = self.disposition  # type: ignore[assignment]

        # Mock / fallback never establish any claim.
        if (
            self.mock_output_present
            or self.fallback_output_present
            or mode in {AtpExecutionMode.MOCK, AtpExecutionMode.FALLBACK}
        ):
            if (
                self.candidate_established
                or self.reconstruction_established
                or self.satisfiability_established
            ):
                raise AtpAuthorityError(
                    "fallback or mock output cannot establish ATP claims"
                )

        # Reconstruction requires checked proof + matched replay.
        if self.reconstruction_established:
            proof = self.proof  # type: ignore[assignment]
            replay = self.replay  # type: ignore[assignment]
            if (
                not isinstance(proof, AtpProofBindingV2)
                or not proof.present
                or not proof.checked
            ):
                raise AtpAuthorityError(
                    "reconstruction_established requires a checked proof binding"
                )
            if (
                not isinstance(replay, AtpReplayReceiptV2)
                or not replay.matched
                or not replay.replay_claimed
            ):
                raise AtpAuthorityError(
                    "reconstruction_established requires matched replay receipt"
                )
            if result_authority is not ResultAuthority.RECONSTRUCTION:
                raise AtpAuthorityError(
                    "reconstruction_established requires result_authority=reconstruction"
                )
            if ceiling is not ToolchainAuthorityCeiling.RECONSTRUCTION:
                raise AtpAuthorityError(
                    "reconstruction_established requires authority_ceiling=reconstruction"
                )

        if result_authority is ResultAuthority.RECONSTRUCTION:
            if not self.reconstruction_established:
                raise AtpAuthorityError(
                    "result_authority=reconstruction requires reconstruction_established"
                )

        # Profile/translation consistency.
        if translation.is_translated:
            if profile.source_kind is not AtpSourceKind.TRANSLATED:
                raise AtpExecutionError(
                    "translated binding requires translated source_kind"
                )
            if profile.native_vampire_e:
                raise AtpAuthorityError(
                    "translated sources cannot be native_vampire_e"
                )
            if profile.profile not in {
                AtpInputProfile.DCEC_TRANSLATED,
                AtpInputProfile.TDFOL_TRANSLATED,
            }:
                raise AtpExecutionError(
                    "translated binding requires dcec_translated or tdfol_translated profile"
                )
        else:
            if profile.source_kind is AtpSourceKind.TRANSLATED:
                raise AtpExecutionError(
                    "native translation binding cannot pair with translated profile"
                )

        # Non-candidate dispositions cannot claim candidate_established.
        if disposition in {
            AtpDisposition.MOCK_REJECTED,
            AtpDisposition.FALLBACK_REJECTED,
            AtpDisposition.UNSUPPORTED_PROFILE,
            AtpDisposition.MALFORMED,
            AtpDisposition.ERROR,
            AtpDisposition.UNAVAILABLE,
            AtpDisposition.TIMEOUT,
            AtpDisposition.UNKNOWN,
            AtpDisposition.REPLAY_MISMATCH,
        }:
            if self.candidate_established or self.reconstruction_established:
                raise AtpAuthorityError(
                    f"disposition {disposition.value!r} cannot establish candidate "
                    "or reconstruction claims"
                )

        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_authority_metadata(metadata, "metadata")
        object.__setattr__(self, "metadata", metadata)

        if self.schema_version != ATP_PROVIDER_EVIDENCE_SCHEMA:
            raise AtpExecutionError(
                f"unsupported ATPProviderEvidence@2 schema: {self.schema_version!r}"
            )

        if not self.content_digest:
            object.__setattr__(
                self, "content_digest", _digest_of(self._identity_payload())
            )
        else:
            provided = _sha256_hex(self.content_digest, "content_digest")
            expected = _digest_of(self._identity_payload())
            if provided != expected:
                raise AtpExecutionError(
                    "content_digest does not match ATPProviderEvidence@2 content"
                )
            object.__setattr__(self, "content_digest", provided)

    @staticmethod
    def _coerce_szs(
        value: AtpSzsBindingV2 | Mapping[str, Any] | None,
    ) -> AtpSzsBindingV2:
        if value is None:
            return AtpSzsBindingV2.empty()
        if isinstance(value, AtpSzsBindingV2):
            return value
        mapping = _require_mapping(value, "szs")
        return AtpSzsBindingV2(
            **{
                key: mapping[key]
                for key in {
                    "status",
                    "present",
                    "unambiguous",
                    "raw_excerpt",
                    "schema_version",
                }
                if key in mapping
            }
        )

    @staticmethod
    def _coerce_proof(
        value: AtpProofBindingV2 | Mapping[str, Any] | None,
    ) -> AtpProofBindingV2:
        if value is None:
            return AtpProofBindingV2.empty()
        if isinstance(value, AtpProofBindingV2):
            return value
        mapping = _require_mapping(value, "proof")
        return AtpProofBindingV2(
            **{
                key: mapping[key]
                for key in {
                    "status",
                    "present",
                    "verified",
                    "checked",
                    "proof_format",
                    "content_digest",
                    "step_count",
                    "step_names",
                    "checker_id",
                    "szs_status",
                    "text_excerpt",
                    "schema_version",
                }
                if key in mapping
            }
        )

    @staticmethod
    def _coerce_countermodel(
        value: AtpCountermodelBindingV2 | Mapping[str, Any] | None,
    ) -> AtpCountermodelBindingV2:
        if value is None:
            return AtpCountermodelBindingV2.empty()
        if isinstance(value, AtpCountermodelBindingV2):
            return value
        mapping = _require_mapping(value, "countermodel")
        return AtpCountermodelBindingV2(
            **{
                key: mapping[key]
                for key in {
                    "status",
                    "present",
                    "validated",
                    "model_format",
                    "model_digest",
                    "validator_id",
                    "model",
                    "schema_version",
                }
                if key in mapping
            }
        )

    @staticmethod
    def _coerce_replay(
        value: AtpReplayReceiptV2 | Mapping[str, Any] | None,
    ) -> AtpReplayReceiptV2 | None:
        if value is None:
            return None
        if isinstance(value, AtpReplayReceiptV2):
            return value
        mapping = _require_mapping(value, "replay")
        return AtpReplayReceiptV2(
            **{
                key: mapping[key]
                for key in {
                    "replay_id",
                    "request_id",
                    "source_digest",
                    "original_disposition",
                    "replayed_disposition",
                    "proof_digest",
                    "original_szs",
                    "replayed_szs",
                    "matched",
                    "replay_claimed",
                    "checked",
                    "diagnostics",
                    "schema_version",
                }
                if key in mapping
            }
        )

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "candidate_established": self.candidate_established,
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, AtpDisposition)
                else self.disposition
            ),
            "mode": (
                self.mode.value
                if isinstance(self.mode, AtpExecutionMode)
                else self.mode
            ),
            "provider": (
                self.provider.value
                if isinstance(self.provider, AtpProviderKind)
                else self.provider
            ),
            "query_mode": (
                self.query_mode.value
                if isinstance(self.query_mode, AtpQueryMode)
                else self.query_mode
            ),
            "reconstruction_established": self.reconstruction_established,
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "theorem_established": False,
        }

    @property
    def is_candidate(self) -> bool:
        return self.candidate_established and not self.reconstruction_established

    @property
    def is_reconstructed(self) -> bool:
        return self.reconstruction_established

    @property
    def is_conclusive(self) -> bool:
        return self.disposition in {
            AtpDisposition.CANDIDATE_THEOREM,
            AtpDisposition.CANDIDATE_UNSATISFIABLE,
            AtpDisposition.CANDIDATE_SATISFIABLE,
            AtpDisposition.CANDIDATE_COUNTERMODEL,
            AtpDisposition.RECONSTRUCTED,
            AtpDisposition.REPLAY_MATCHED,
            AtpDisposition.TRANSLATED_CANDIDATE,
        }

    @property
    def claim_theorem(self) -> bool:
        return False

    @property
    def claim_proof(self) -> bool:
        return False

    @property
    def claim_reconstruction(self) -> bool:
        return self.reconstruction_established

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": (
                self.authority_ceiling.value
                if isinstance(self.authority_ceiling, ToolchainAuthorityCeiling)
                else self.authority_ceiling
            ),
            "available": self.available,
            "bounds_exhausted": self.bounds_exhausted,
            "candidate_established": self.candidate_established,
            "claim_proof": self.claim_proof,
            "claim_reconstruction": self.claim_reconstruction,
            "claim_theorem": self.claim_theorem,
            "confidence": self.confidence,
            "content_digest": self.content_digest,
            "countermodel": self.countermodel.to_dict(),  # type: ignore[union-attr]
            "diagnostics": list(self.diagnostics),
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, AtpDisposition)
                else self.disposition
            ),
            "evidence_id": self.evidence_id,
            "fallback_output_present": self.fallback_output_present,
            "fluent_text_present": self.fluent_text_present,
            "interface": self.interface,
            "is_candidate": self.is_candidate,
            "is_conclusive": self.is_conclusive,
            "is_reconstructed": self.is_reconstructed,
            "metadata": _thaw_mapping(self.metadata),
            "mock_output_present": self.mock_output_present,
            "mode": (
                self.mode.value
                if isinstance(self.mode, AtpExecutionMode)
                else self.mode
            ),
            "obligation_id": self.obligation_id,
            "profile": self.profile.to_dict(),  # type: ignore[union-attr]
            "proof": self.proof.to_dict(),  # type: ignore[union-attr]
            "proof_established": False,
            "provider": (
                self.provider.value
                if isinstance(self.provider, AtpProviderKind)
                else self.provider
            ),
            "query_mode": (
                self.query_mode.value
                if isinstance(self.query_mode, AtpQueryMode)
                else self.query_mode
            ),
            "reconstruction_established": self.reconstruction_established,
            "replay": None if self.replay is None else self.replay.to_dict(),  # type: ignore[union-attr]
            "request_digest": self.request_digest,
            "request_id": self.request_id,
            "result_authority": (
                self.result_authority.value
                if isinstance(self.result_authority, ResultAuthority)
                else self.result_authority
            ),
            "result_status": (
                self.result_status.value
                if isinstance(self.result_status, ResultStatus)
                else self.result_status
            ),
            "role": self.role.value if isinstance(self.role, ToolRole) else self.role,
            "satisfiability_established": self.satisfiability_established,
            "schema_version": self.schema_version,
            "solver_backend_id": self.solver_backend_id,
            "solver_version": self.solver_version,
            "source_digest": self.source_digest,
            "source_ref_ids": list(self.source_ref_ids),
            "szs": self.szs.to_dict(),  # type: ignore[union-attr]
            "theorem_established": False,
            "translation": self.translation.to_dict(),  # type: ignore[union-attr]
            "translation_ceiling": (
                self.translation_ceiling.value
                if isinstance(self.translation_ceiling, EvidenceAuthority)
                else self.translation_ceiling
            ),
            "atp_success_remains_candidate_until_checked_replayed": True,
        }


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AtpExecutionResultV2:
    """Typed request + evidence + optional normalized backend outcome.

    Interface: ``AtpExecutionResult@2``.
    """

    request: AtpExecutionRequestV2
    evidence: AtpProviderEvidenceV2
    backend_outcome: ATPAdapterOutcome | None = None
    backend_result: TypedBackendResult | None = None
    schema_version: str = ATP_EXECUTION_RESULT_SCHEMA

    interface: ClassVar[str] = ATP_EXECUTION_RESULT_V2_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.request, AtpExecutionRequestV2):
            raise AtpExecutionError("request must be AtpExecutionRequestV2")
        if not isinstance(self.evidence, AtpProviderEvidenceV2):
            raise AtpExecutionError("evidence must be AtpProviderEvidenceV2")
        if self.request.request_id != self.evidence.request_id:
            raise AtpExecutionError(
                "result request_id must match evidence.request_id"
            )
        if self.backend_outcome is not None and not isinstance(
            self.backend_outcome, ATPAdapterOutcome
        ):
            raise AtpExecutionError("backend_outcome must be ATPAdapterOutcome")
        if self.backend_result is not None and not isinstance(
            self.backend_result, TypedBackendResult
        ):
            raise AtpExecutionError("backend_result must be TypedBackendResult")
        if self.schema_version != ATP_EXECUTION_RESULT_SCHEMA:
            raise AtpExecutionError(
                f"unsupported result schema: {self.schema_version!r}"
            )

    @property
    def disposition(self) -> AtpDisposition:
        return self.evidence.disposition  # type: ignore[return-value]

    @property
    def is_candidate(self) -> bool:
        return self.evidence.is_candidate

    @property
    def is_reconstructed(self) -> bool:
        return self.evidence.is_reconstructed

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_outcome": (
                None
                if self.backend_outcome is None
                else self.backend_outcome.to_dict()
            ),
            "backend_result": (
                None
                if self.backend_result is None
                else self.backend_result.to_dict()
            ),
            "evidence": self.evidence.to_dict(),
            "interface": self.interface,
            "request": self.request.to_dict(),
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# Disposition / authority helpers
# ---------------------------------------------------------------------------


def _szs_to_disposition(
    szs: SZSStatus,
    *,
    query_mode: AtpQueryMode,
    translated: bool,
) -> AtpDisposition:
    if translated:
        return AtpDisposition.TRANSLATED_CANDIDATE
    if szs is SZSStatus.THEOREM:
        return AtpDisposition.CANDIDATE_THEOREM
    if szs is SZSStatus.UNSATISFIABLE:
        return AtpDisposition.CANDIDATE_UNSATISFIABLE
    if szs is SZSStatus.CONTRADICTORY_AXIOMS:
        return AtpDisposition.CANDIDATE_UNSATISFIABLE
    if szs is SZSStatus.SATISFIABLE:
        return AtpDisposition.CANDIDATE_SATISFIABLE
    if szs is SZSStatus.COUNTER_SATISFIABLE:
        return (
            AtpDisposition.CANDIDATE_COUNTERMODEL
            if query_mode is AtpQueryMode.THEOREM_PROOF
            else AtpDisposition.CANDIDATE_SATISFIABLE
        )
    if szs in {SZSStatus.TIMEOUT, SZSStatus.RESOURCE_OUT}:
        return AtpDisposition.TIMEOUT
    if szs in {SZSStatus.UNKNOWN, SZSStatus.GAVE_UP}:
        return AtpDisposition.UNKNOWN
    return AtpDisposition.UNKNOWN


def _disposition_to_result_status(disposition: AtpDisposition) -> ResultStatus:
    mapping = {
        AtpDisposition.CANDIDATE_THEOREM: ResultStatus.CANDIDATE,
        AtpDisposition.CANDIDATE_UNSATISFIABLE: ResultStatus.CANDIDATE,
        AtpDisposition.CANDIDATE_SATISFIABLE: ResultStatus.CANDIDATE,
        AtpDisposition.CANDIDATE_COUNTERMODEL: ResultStatus.CANDIDATE,
        AtpDisposition.RECONSTRUCTED: ResultStatus.RECONSTRUCTED,
        AtpDisposition.REPLAY_MATCHED: ResultStatus.CANDIDATE,
        AtpDisposition.TRANSLATED_CANDIDATE: ResultStatus.CANDIDATE,
        AtpDisposition.UNKNOWN: ResultStatus.UNKNOWN,
        AtpDisposition.TIMEOUT: ResultStatus.TIMEOUT,
        AtpDisposition.UNAVAILABLE: ResultStatus.UNAVAILABLE,
        AtpDisposition.UNSUPPORTED_PROFILE: ResultStatus.UNSUPPORTED,
        AtpDisposition.MALFORMED: ResultStatus.MALFORMED,
        AtpDisposition.ERROR: ResultStatus.ERROR,
        AtpDisposition.MOCK_REJECTED: ResultStatus.UNKNOWN,
        AtpDisposition.FALLBACK_REJECTED: ResultStatus.UNKNOWN,
        AtpDisposition.REPLAY_MISMATCH: ResultStatus.ERROR,
    }
    return mapping[disposition]


def _candidate_dispositions() -> frozenset[AtpDisposition]:
    return frozenset(
        {
            AtpDisposition.CANDIDATE_THEOREM,
            AtpDisposition.CANDIDATE_UNSATISFIABLE,
            AtpDisposition.CANDIDATE_SATISFIABLE,
            AtpDisposition.CANDIDATE_COUNTERMODEL,
            AtpDisposition.TRANSLATED_CANDIDATE,
            AtpDisposition.RECONSTRUCTED,
            AtpDisposition.REPLAY_MATCHED,
        }
    )


def _is_execution_mode(mode: AtpExecutionMode) -> bool:
    return mode in {
        AtpExecutionMode.PINNED_SOLVER,
        AtpExecutionMode.HERMETIC_FIXTURE,
    }


# ---------------------------------------------------------------------------
# Hermetic runners / engine
# ---------------------------------------------------------------------------


def _fixed_process_runner(
    stdout: str,
    *,
    stderr: str = "",
    returncode: int | None = 0,
    timed_out: bool = False,
    unavailable: bool = False,
    output_truncated: bool = False,
    elapsed_seconds: float = 0.01,
) -> BoundedToolRunner:
    def execute(_invocation: object, _cancellation: object) -> RawProcessResult:
        if unavailable:
            return RawProcessResult(
                returncode=None,
                stdout="",
                stderr="executable not found",
                elapsed_seconds=0.0,
                error="executable not found",
            )
        return RawProcessResult(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            elapsed_seconds=elapsed_seconds,
            timed_out=timed_out,
            output_truncated=output_truncated,
            process_tree_terminated=timed_out,
        )

    return BoundedToolRunner(executor=execute)


def hermetic_runner(
    stdout: str,
    **kwargs: Any,
) -> BoundedToolRunner:
    """Build a deterministic BoundedToolRunner for hermetic ATP fixtures."""

    return _fixed_process_runner(stdout, **kwargs)


def _build_backend_request(
    req: AtpExecutionRequestV2,
    *,
    backend_id: str,
    logic_family: str,
) -> BackendRequest:
    query = (
        QueryKind.THEOREM_PROOF
        if req.query_mode is AtpQueryMode.THEOREM_PROOF
        else QueryKind.SATISFIABILITY
    )
    claim_digest = _digest_of({"claim_id": req.claim_id or req.request_id})
    obligation_digest = _digest_of(
        {"obligation_id": req.obligation_id or req.request_id, "source": req.source}
    )
    return BackendRequest(
        request_id=req.request_id,
        claim_id=req.claim_id or f"claim:{req.request_id}",
        declaration_id=f"declaration:{req.request_id}",
        claim_digest=claim_digest,
        obligation_id=req.obligation_id or f"obligation:{req.request_id}",
        obligation_digest=obligation_digest,
        assumption_ids=(),
        logic_family=logic_family,
        query_kind=query,
        bounds=req.bounds,  # type: ignore[arg-type]
        payload=FrozenMap(
            {
                "encoding": req.encoding,
                "source": req.source,
                "tptp": req.source,
            }
        ),
        requested_backend_id=backend_id,
    )


def _default_countermodel_parser(
    binding: ATPSourceBinding,
    process: Any,
    status: SZSStatus,
) -> ATPCountermodel | None:
    if status not in {SZSStatus.SATISFIABLE, SZSStatus.COUNTER_SATISFIABLE}:
        return None
    combined = "\n".join(
        part for part in (getattr(process, "stdout", ""), getattr(process, "stderr", "")) if part
    )
    excerpt = combined[:_MAX_MODEL_CHARS]
    return ATPCountermodel(
        request_digest=binding.request_digest,
        source_digest=binding.source_digest,
        model_format="tptp-model-candidate",
        model=FrozenMap(
            {
                "szs_status": status.value,
                "excerpt": excerpt,
                "validated": False,
            }
        ),
        validated=False,
    )


def _tstp_reconstructor(
    binding: ATPSourceBinding,
    process: Any,
    status: SZSStatus,
) -> ATPProofObject | None:
    """Bind raw TSTP stdout as an **unverified** proof candidate.

    ATP success remains candidate evidence until execution_v2 independently
    checks the TSTP record and replays digests.  The adapter layer must never
    mint verified/theorem authority from Vampire/E alone.
    """

    if status not in {
        SZSStatus.THEOREM,
        SZSStatus.UNSATISFIABLE,
        SZSStatus.CONTRADICTORY_AXIOMS,
    }:
        return None
    combined = "\n".join(
        part for part in (getattr(process, "stdout", ""), getattr(process, "stderr", "")) if part
    )
    return ATPProofObject(
        request_digest=binding.request_digest,
        source_digest=binding.source_digest,
        proof_format="tstp",
        content=combined or f"% SZS status {status.value}",
        verified=False,
        checker_id="",
        metadata=FrozenMap({"szs_status": status.value}),
    )


class AtpExecutionEngineV2:
    """Execute and reconstruct typed Vampire / E ATP obligations.

    Interface owner: ``ATPProviderEvidence@2``.

    Hermetic fixture runners are the default for deterministic CI.  Live
    pinned Vampire/E may be injected when available.  Mock and fallback
    outputs are rejected as non-authoritative typed dispositions.
    """

    INTERFACE: ClassVar[str] = ATP_PROVIDER_EVIDENCE_V2_INTERFACE
    interface: ClassVar[str] = ATP_PROVIDER_EVIDENCE_V2_INTERFACE
    VERSION: ClassVar[str] = ATP_EXECUTION_V2_MODULE_VERSION
    TASK_ID: ClassVar[str] = ATP_EXECUTION_V2_TASK_ID
    GOAL_ID: ClassVar[str] = ATP_EXECUTION_V2_GOAL_ID

    def __init__(
        self,
        *,
        vampire_runner: BoundedToolRunner | None = None,
        eprover_runner: BoundedToolRunner | None = None,
        vampire_version: str = "hermetic",
        eprover_version: str = "hermetic",
        proof_checker_id: str = "",
        verify_reconstruction: bool = False,
        tstp_frontend: TSTPFrontend | None = None,
    ) -> None:
        self._vampire_runner = vampire_runner
        self._eprover_runner = eprover_runner
        self._vampire_version = vampire_version
        self._eprover_version = eprover_version
        self._proof_checker_id = proof_checker_id
        self._verify_reconstruction = verify_reconstruction
        self._tstp = tstp_frontend or TSTPFrontend()

    def execute(
        self,
        request: AtpExecutionRequestV2 | Mapping[str, Any],
    ) -> AtpExecutionResultV2:
        """Execute one typed ATP obligation request."""

        req = (
            request
            if isinstance(request, AtpExecutionRequestV2)
            else AtpExecutionRequestV2.from_dict(request)
        )
        request_digest = _digest_of(req.to_dict())
        source_digest = req.source_digest

        # Mock path: never establishes authority.
        if req.has_mock_output or req.mode is AtpExecutionMode.MOCK:
            return self._reject_non_execution(
                req,
                request_digest=request_digest,
                source_digest=source_digest,
                disposition=AtpDisposition.MOCK_REJECTED,
                mode=AtpExecutionMode.MOCK,
                diagnostics=(
                    "mock_output_cannot_establish_theorem",
                    "mock_output_cannot_establish_proof",
                    "mock_output_cannot_establish_reconstruction",
                    "atp_success_remains_candidate_until_checked_replayed",
                ),
                mock_output_present=True,
            )

        # Fallback path: never establishes authority.
        if req.has_fallback_output or req.mode is AtpExecutionMode.FALLBACK:
            return self._reject_non_execution(
                req,
                request_digest=request_digest,
                source_digest=source_digest,
                disposition=AtpDisposition.FALLBACK_REJECTED,
                mode=AtpExecutionMode.FALLBACK,
                diagnostics=(
                    "fallback_output_cannot_establish_theorem",
                    "fallback_output_cannot_establish_proof",
                    "fallback_output_cannot_establish_reconstruction",
                    "atp_success_remains_candidate_until_checked_replayed",
                ),
                fallback_output_present=True,
            )

        if not req.available:
            return self._reject_non_execution(
                req,
                request_digest=request_digest,
                source_digest=source_digest,
                disposition=AtpDisposition.UNAVAILABLE,
                mode=req.mode,  # type: ignore[arg-type]
                diagnostics=(
                    "provider_unavailable",
                    "availability_cannot_establish_theorem",
                ),
                available=False,
            )

        profile, source_kind, languages = detect_input_profile(
            req.source, source_profile=req.source_profile or None
        )
        profile_binding = AtpProfileBindingV2(
            profile=profile,
            source_kind=source_kind,
            languages=languages,
            source_digest=source_digest,
            encoding=req.encoding,
            native_vampire_e=(source_kind is AtpSourceKind.NATIVE),
        )

        if source_kind is AtpSourceKind.TRANSLATED:
            translation = AtpTranslationBindingV2.translated(
                profile,
                extra_assumptions=req.translation_assumptions,
                translation_receipt_id=req.translation_receipt_id,
            )
        elif profile in {
            AtpInputProfile.THF_UNSUPPORTED,
            AtpInputProfile.UNKNOWN,
        } or source_kind is AtpSourceKind.UNSUPPORTED:
            translation = AtpTranslationBindingV2(
                is_translated=False,
                source_profile=profile.value,
                target_profile="tptp-unsupported",
                assumptions=(),
                labeled_native=False,
            )
        else:
            if req.translation_assumptions:
                raise AtpExecutionError(
                    "native ATP sources must not declare translation assumptions"
                )
            translation = AtpTranslationBindingV2.native(profile)

        if profile is AtpInputProfile.THF_UNSUPPORTED or source_kind is AtpSourceKind.UNSUPPORTED:
            return self._finish(
                req,
                request_digest=request_digest,
                source_digest=source_digest,
                profile=profile_binding,
                translation=translation,
                disposition=AtpDisposition.UNSUPPORTED_PROFILE,
                diagnostics=(
                    "thf_or_unknown_profile_unsupported",
                    "input_profile_must_be_exact_cnf_fof_tff_or_translated",
                ),
                candidate_established=False,
            )

        # Typed TPTP parse (fail closed on malformed native/translated TPTP).
        try:
            parse_result = parse_tptp_v2(
                req.source,
                document_id=f"doc:atp:{req.request_id}",
                request_id=req.request_id,
                elaborate=True,
            )
        except Exception as error:  # noqa: BLE001 — typed malformed disposition
            return self._finish(
                req,
                request_digest=request_digest,
                source_digest=source_digest,
                profile=profile_binding,
                translation=translation,
                disposition=AtpDisposition.MALFORMED,
                diagnostics=(
                    "tptp_frontend_v2_parse_error",
                    f"{type(error).__name__}:{str(error)[:200]}",
                ),
                candidate_established=False,
            )
        if parse_result.status not in {ParseStatus.OK, ParseStatus.RECOVERED}:
            return self._finish(
                req,
                request_digest=request_digest,
                source_digest=source_digest,
                profile=profile_binding,
                translation=translation,
                disposition=AtpDisposition.MALFORMED,
                diagnostics=(
                    "tptp_frontend_v2_parse_failed",
                    f"parse_status={parse_result.status.value}",
                ),
                candidate_established=False,
            )

        provider = req.provider  # type: ignore[assignment]
        backend_id = provider_backend_id(provider)
        logic_family = (
            translation.source_profile
            if translation.is_translated
            else "fol"
        )
        backend_request = _build_backend_request(
            req, backend_id=backend_id, logic_family=logic_family
        )

        runner = (
            self._vampire_runner
            if provider is AtpProviderKind.VAMPIRE
            else self._eprover_runner
        )
        if runner is None and req.mode is AtpExecutionMode.HERMETIC_FIXTURE:
            return self._finish(
                req,
                request_digest=request_digest,
                source_digest=source_digest,
                profile=profile_binding,
                translation=translation,
                disposition=AtpDisposition.UNAVAILABLE,
                diagnostics=(
                    "hermetic_runner_not_configured",
                    "inject_hermetic_runner_or_use_pinned_solver",
                ),
                candidate_established=False,
                available=False,
            )
        if runner is None:
            runner = BoundedToolRunner()

        if provider is AtpProviderKind.VAMPIRE:
            backend = VampireBackend(
                runner=runner,
                backend_version=self._vampire_version,
                proof_reconstructor=_tstp_reconstructor,
                countermodel_parser=_default_countermodel_parser,
            )
            solver_version = self._vampire_version
        else:
            backend = EProverBackend(
                runner=runner,
                backend_version=self._eprover_version,
                proof_reconstructor=_tstp_reconstructor,
                countermodel_parser=_default_countermodel_parser,
            )
            solver_version = self._eprover_version

        try:
            outcome = backend.run(backend_request)
        except Exception as error:  # noqa: BLE001 — typed error envelope
            return self._finish(
                req,
                request_digest=request_digest,
                source_digest=source_digest,
                profile=profile_binding,
                translation=translation,
                disposition=AtpDisposition.ERROR,
                diagnostics=(f"atp_backend_error:{type(error).__name__}", str(error)[:256]),
                candidate_established=False,
                solver_backend_id=backend_id,
                solver_version=solver_version,
            )

        return self._from_outcome(
            req,
            request_digest=request_digest,
            source_digest=source_digest,
            profile=profile_binding,
            translation=translation,
            outcome=outcome,
            solver_backend_id=backend_id,
            solver_version=solver_version,
        )

    def _from_outcome(
        self,
        req: AtpExecutionRequestV2,
        *,
        request_digest: str,
        source_digest: str,
        profile: AtpProfileBindingV2,
        translation: AtpTranslationBindingV2,
        outcome: ATPAdapterOutcome,
        solver_backend_id: str,
        solver_version: str,
    ) -> AtpExecutionResultV2:
        result = outcome.result
        status = result.status
        diagnostics: list[str] = list(result.diagnostics)
        diagnostics.append("atp_success_remains_candidate_until_checked_replayed")

        if status is ResultStatus.UNAVAILABLE:
            return self._finish(
                req,
                request_digest=request_digest,
                source_digest=source_digest,
                profile=profile,
                translation=translation,
                disposition=AtpDisposition.UNAVAILABLE,
                diagnostics=tuple(diagnostics) + ("solver_unavailable",),
                candidate_established=False,
                available=False,
                solver_backend_id=solver_backend_id,
                solver_version=solver_version,
                backend_outcome=outcome,
            )
        if status is ResultStatus.TIMEOUT:
            return self._finish(
                req,
                request_digest=request_digest,
                source_digest=source_digest,
                profile=profile,
                translation=translation,
                disposition=AtpDisposition.TIMEOUT,
                diagnostics=tuple(diagnostics) + ("timeout",),
                candidate_established=False,
                bounds_exhausted=True,
                solver_backend_id=solver_backend_id,
                solver_version=solver_version,
                backend_outcome=outcome,
            )
        if status is ResultStatus.MALFORMED:
            return self._finish(
                req,
                request_digest=request_digest,
                source_digest=source_digest,
                profile=profile,
                translation=translation,
                disposition=AtpDisposition.MALFORMED,
                diagnostics=tuple(diagnostics) + ("malformed_szs_or_output",),
                candidate_established=False,
                solver_backend_id=solver_backend_id,
                solver_version=solver_version,
                backend_outcome=outcome,
            )
        if status is ResultStatus.ERROR:
            return self._finish(
                req,
                request_digest=request_digest,
                source_digest=source_digest,
                profile=profile,
                translation=translation,
                disposition=AtpDisposition.ERROR,
                diagnostics=tuple(diagnostics) + ("backend_error",),
                candidate_established=False,
                solver_backend_id=solver_backend_id,
                solver_version=solver_version,
                backend_outcome=outcome,
            )

        # Recover SZS from metadata or proof content.
        szs_status: SZSStatus | None = None
        szs_token = ""
        metadata = result.metadata
        if isinstance(metadata, FrozenMap):
            metadata = metadata.to_dict()
        if isinstance(metadata, Mapping):
            szs_token = str(metadata.get("szs_status", "") or "")
        if not szs_token and outcome.proof_object is not None:
            proof_meta = outcome.proof_object.metadata
            if isinstance(proof_meta, FrozenMap):
                proof_meta = proof_meta.to_dict()
            if isinstance(proof_meta, Mapping):
                szs_token = str(proof_meta.get("szs_status", "") or "")
        if szs_token:
            try:
                szs_status = SZSStatus(szs_token)
            except ValueError:
                szs_status = None
        if szs_status is None and outcome.proof_object is not None:
            try:
                szs_status = parse_szs_status(outcome.proof_object.content)
            except MalformedATPOutput:
                szs_status = None

        if szs_status is None and status is ResultStatus.CANDIDATE:
            # Candidate without recoverable SZS — still bind profile/translation.
            disposition = (
                AtpDisposition.TRANSLATED_CANDIDATE
                if translation.is_translated
                else AtpDisposition.UNKNOWN
            )
        elif szs_status is None:
            disposition = AtpDisposition.UNKNOWN
        else:
            disposition = _szs_to_disposition(
                szs_status,
                query_mode=req.query_mode,  # type: ignore[arg-type]
                translated=translation.is_translated,
            )

        szs_binding = (
            AtpSzsBindingV2.from_status(szs_status)
            if szs_status is not None
            else AtpSzsBindingV2.empty()
        )

        # TSTP reconstruction parse.  Independent check requires a declared
        # checker, successful TSTP structure parse, and require_replay — ATP
        # adapter success alone never marks a proof verified.
        proof_binding = AtpProofBindingV2.empty()
        proof_content = ""
        independent_checker = (
            self._proof_checker_id
            if self._verify_reconstruction and self._proof_checker_id
            else ""
        )
        if outcome.proof_object is not None:
            proof_content = outcome.proof_object.content
            tstp_result = None
            try:
                tstp_result = self._tstp.parse_text(
                    proof_content,
                    document_id=f"doc:tstp:{req.request_id}",
                    request_id=req.request_id,
                )
            except Exception as error:  # noqa: BLE001 — typed candidate fallback
                diagnostics.append(
                    f"tstp_parse_error:{type(error).__name__}"
                )
            checked = bool(independent_checker and req.require_replay)
            if (
                tstp_result is not None
                and tstp_result.ok
                and tstp_result.record is not None
            ):
                proof_binding = AtpProofBindingV2.from_tstp_record(
                    tstp_result.record,
                    content=proof_content,
                    checked=checked,
                    checker_id=independent_checker,
                )
                diagnostics.append("tstp_candidate_parsed")
            else:
                # Content-bound candidate when structure parse is unavailable.
                # Independent check may still elevate after digest replay when
                # a checker id is declared (never theorem authority).
                digest = _digest_of({"content": proof_content})
                proof_binding = AtpProofBindingV2(
                    status=(
                        AtpProofStatus.CHECKED
                        if checked
                        else AtpProofStatus.CANDIDATE
                    ),
                    present=True,
                    verified=checked,
                    checked=checked,
                    proof_format=outcome.proof_object.proof_format or "tstp",
                    content_digest=digest,
                    step_count=0,
                    step_names=(),
                    checker_id=independent_checker if checked else "",
                    szs_status=szs_binding.status,
                    text_excerpt=proof_content[:_MAX_PROOF_CHARS],
                )
                diagnostics.append("tstp_structure_unavailable_candidate_bound")

        countermodel_binding = AtpCountermodelBindingV2.empty()
        if outcome.countermodel is not None:
            countermodel_binding = AtpCountermodelBindingV2.from_countermodel(
                outcome.countermodel
            )
            diagnostics.append("countermodel_candidate_bound")

        candidate = disposition in _candidate_dispositions()
        if candidate:
            diagnostics.append("candidate_evidence_only")

        # Replay: re-parse TSTP and match digests when proof present.
        replay: AtpReplayReceiptV2 | None = None
        reconstruction_established = False
        result_authority = ResultAuthority.CANDIDATE
        authority_ceiling = ToolchainAuthorityCeiling.CANDIDATE
        final_disposition = disposition

        if req.require_replay and proof_binding.present and proof_content:
            replay_parse = None
            try:
                replay_parse = self._tstp.parse_text(
                    proof_content,
                    document_id=f"doc:tstp:replay:{req.request_id}",
                    request_id=f"replay:{req.request_id}",
                )
            except Exception as error:  # noqa: BLE001 — digest replay still possible
                diagnostics.append(
                    f"tstp_replay_parse_error:{type(error).__name__}"
                )
            replay_digest = _digest_of({"content": proof_content})
            digest_matched = replay_digest == proof_binding.content_digest
            structure_matched = (
                replay_parse is not None
                and replay_parse.ok
                and replay_parse.record is not None
                and (
                    not szs_binding.present
                    or not replay_parse.record.szs_status
                    or replay_parse.record.szs_status == szs_binding.status
                )
            )
            # Digest match is authoritative for content-bound replay; structured
            # TSTP reparse strengthens the receipt when available.
            matched = digest_matched and (
                structure_matched
                or replay_parse is None
                or not replay_parse.ok
            )
            if matched and digest_matched:
                replayed_szs = (
                    replay_parse.record.szs_status
                    if (
                        replay_parse is not None
                        and replay_parse.ok
                        and replay_parse.record is not None
                    )
                    else szs_binding.status
                )
                replay = AtpReplayReceiptV2(
                    replay_id=f"replay:atp:{req.request_id}",
                    request_id=req.request_id,
                    source_digest=source_digest,
                    original_disposition=disposition,
                    replayed_disposition=disposition,
                    proof_digest=proof_binding.content_digest,
                    original_szs=szs_binding.status,
                    replayed_szs=replayed_szs,
                    matched=True,
                    replay_claimed=True,
                    checked=proof_binding.checked,
                    diagnostics=(
                        "tstp_replay_matched",
                        *(
                            ("tstp_structure_replay_matched",)
                            if structure_matched
                            else ("tstp_content_digest_replay_matched",)
                        ),
                    ),
                )
                diagnostics.append("tstp_replay_matched")
                if proof_binding.checked and proof_binding.present:
                    reconstruction_established = True
                    result_authority = ResultAuthority.RECONSTRUCTION
                    authority_ceiling = ToolchainAuthorityCeiling.RECONSTRUCTION
                    final_disposition = AtpDisposition.RECONSTRUCTED
                    # Refresh proof binding as checked under matched replay.
                    proof_binding = AtpProofBindingV2(
                        status=AtpProofStatus.CHECKED,
                        present=True,
                        verified=True,
                        checked=True,
                        proof_format=proof_binding.proof_format,
                        content_digest=proof_binding.content_digest,
                        step_count=proof_binding.step_count,
                        step_names=proof_binding.step_names,
                        checker_id=proof_binding.checker_id or independent_checker,
                        szs_status=proof_binding.szs_status,
                        text_excerpt=proof_binding.text_excerpt,
                    )
                    diagnostics.append("reconstruction_checked_and_replayed")
                else:
                    final_disposition = AtpDisposition.REPLAY_MATCHED
                    diagnostics.append(
                        "replay_matched_but_reconstruction_not_independently_checked"
                    )
            else:
                final_disposition = AtpDisposition.REPLAY_MISMATCH
                candidate = False
                # Demote any provisional checked state — mismatch is not
                # independently confirmed reconstruction evidence.
                if proof_binding.present:
                    proof_binding = AtpProofBindingV2(
                        status=AtpProofStatus.REJECTED,
                        present=True,
                        verified=False,
                        checked=False,
                        proof_format=proof_binding.proof_format,
                        content_digest=proof_binding.content_digest,
                        step_count=proof_binding.step_count,
                        step_names=proof_binding.step_names,
                        checker_id="",
                        szs_status=proof_binding.szs_status,
                        text_excerpt=proof_binding.text_excerpt,
                    )
                replay = AtpReplayReceiptV2(
                    replay_id=f"replay:atp:{req.request_id}",
                    request_id=req.request_id,
                    source_digest=source_digest,
                    original_disposition=disposition,
                    replayed_disposition=AtpDisposition.REPLAY_MISMATCH,
                    proof_digest=proof_binding.content_digest,
                    original_szs=szs_binding.status,
                    replayed_szs="",
                    matched=False,
                    replay_claimed=False,
                    checked=False,
                    diagnostics=("tstp_replay_mismatch",),
                )
                diagnostics.append("tstp_replay_mismatch")
        elif candidate:
            diagnostics.append("replay_not_required_or_no_proof_artifact")

        return self._finish(
            req,
            request_digest=request_digest,
            source_digest=source_digest,
            profile=profile,
            translation=translation,
            disposition=final_disposition,
            diagnostics=tuple(diagnostics),
            candidate_established=candidate and not reconstruction_established,
            reconstruction_established=reconstruction_established,
            result_authority=result_authority,
            authority_ceiling=authority_ceiling,
            szs=szs_binding,
            proof=proof_binding,
            countermodel=countermodel_binding,
            replay=replay,
            solver_backend_id=solver_backend_id,
            solver_version=solver_version,
            backend_outcome=outcome,
            available=True,
        )

    def _reject_non_execution(
        self,
        req: AtpExecutionRequestV2,
        *,
        request_digest: str,
        source_digest: str,
        disposition: AtpDisposition,
        mode: AtpExecutionMode,
        diagnostics: tuple[str, ...],
        mock_output_present: bool = False,
        fallback_output_present: bool = False,
        available: bool = True,
    ) -> AtpExecutionResultV2:
        profile, source_kind, languages = detect_input_profile(
            req.source, source_profile=req.source_profile or None
        )
        # Soft-bind profile even on reject paths so answers remain exact.
        try:
            profile_binding = AtpProfileBindingV2(
                profile=profile,
                source_kind=source_kind,
                languages=languages,
                source_digest=source_digest,
                encoding=req.encoding,
                native_vampire_e=(source_kind is AtpSourceKind.NATIVE),
            )
        except (AtpExecutionError, AtpAuthorityError):
            profile_binding = AtpProfileBindingV2(
                profile=AtpInputProfile.UNKNOWN,
                source_kind=AtpSourceKind.UNSUPPORTED,
                languages=languages,
                source_digest=source_digest,
                encoding=req.encoding,
                native_vampire_e=False,
            )
            profile = AtpInputProfile.UNKNOWN
            source_kind = AtpSourceKind.UNSUPPORTED

        if source_kind is AtpSourceKind.TRANSLATED:
            translation = AtpTranslationBindingV2.translated(
                profile,
                extra_assumptions=req.translation_assumptions,
                translation_receipt_id=req.translation_receipt_id,
            )
        elif profile in {
            AtpInputProfile.THF_UNSUPPORTED,
            AtpInputProfile.UNKNOWN,
        }:
            translation = AtpTranslationBindingV2(
                is_translated=False,
                source_profile=profile.value,
                target_profile="tptp-unsupported",
                assumptions=(),
                labeled_native=False,
            )
        else:
            translation = AtpTranslationBindingV2.native(profile)

        return self._finish(
            req,
            request_digest=request_digest,
            source_digest=source_digest,
            profile=profile_binding,
            translation=translation,
            disposition=disposition,
            mode=mode,
            diagnostics=diagnostics,
            candidate_established=False,
            mock_output_present=mock_output_present,
            fallback_output_present=fallback_output_present,
            available=available,
        )

    def _finish(
        self,
        req: AtpExecutionRequestV2,
        *,
        request_digest: str,
        source_digest: str,
        profile: AtpProfileBindingV2,
        translation: AtpTranslationBindingV2,
        disposition: AtpDisposition,
        diagnostics: tuple[str, ...],
        candidate_established: bool,
        reconstruction_established: bool = False,
        result_authority: ResultAuthority = ResultAuthority.CANDIDATE,
        authority_ceiling: ToolchainAuthorityCeiling = (
            ToolchainAuthorityCeiling.CANDIDATE
        ),
        mode: AtpExecutionMode | None = None,
        szs: AtpSzsBindingV2 | None = None,
        proof: AtpProofBindingV2 | None = None,
        countermodel: AtpCountermodelBindingV2 | None = None,
        replay: AtpReplayReceiptV2 | None = None,
        solver_backend_id: str = "",
        solver_version: str = "",
        backend_outcome: ATPAdapterOutcome | None = None,
        available: bool = True,
        bounds_exhausted: bool = False,
        mock_output_present: bool = False,
        fallback_output_present: bool = False,
    ) -> AtpExecutionResultV2:
        exec_mode = mode if mode is not None else req.mode  # type: ignore[assignment]
        if not _is_execution_mode(exec_mode) and (
            candidate_established or reconstruction_established
        ):
            raise AtpAuthorityError(
                "only pinned_solver or hermetic_fixture modes may establish "
                "ATP candidate/reconstruction claims"
            )

        translation_ceiling = (
            EvidenceAuthority.ADVISORY
            if translation.is_translated
            else EvidenceAuthority.BOUNDED
        )
        evidence = AtpProviderEvidenceV2(
            evidence_id=f"evidence:atp:{req.request_id}",
            request_id=req.request_id,
            request_digest=request_digest,
            provider=req.provider,
            disposition=disposition,
            mode=exec_mode,
            query_mode=req.query_mode,
            source_digest=source_digest,
            profile=profile,
            translation=translation,
            szs=szs or AtpSzsBindingV2.empty(),
            proof=proof or AtpProofBindingV2.empty(),
            countermodel=countermodel or AtpCountermodelBindingV2.empty(),
            replay=replay,
            obligation_id=req.obligation_id,
            solver_backend_id=solver_backend_id,
            solver_version=solver_version,
            source_ref_ids=req.source_ref_ids,
            result_authority=result_authority,
            result_status=_disposition_to_result_status(disposition),
            role=ToolRole.CANDIDATE,
            authority_ceiling=authority_ceiling,
            translation_ceiling=translation_ceiling,
            candidate_established=candidate_established,
            reconstruction_established=reconstruction_established,
            theorem_established=False,
            proof_established=False,
            satisfiability_established=False,
            mock_output_present=mock_output_present,
            fallback_output_present=fallback_output_present,
            available=available,
            confidence=req.confidence,
            fluent_text_present=bool(req.fluent_text),
            bounds_exhausted=bounds_exhausted,
            diagnostics=diagnostics,
        )
        return AtpExecutionResultV2(
            request=req,
            evidence=evidence,
            backend_outcome=backend_outcome,
            backend_result=(
                backend_outcome.result if backend_outcome is not None else None
            ),
        )


# ---------------------------------------------------------------------------
# Convenience API
# ---------------------------------------------------------------------------


def execute_atp(
    source: str,
    *,
    request_id: str = "req:atp:1",
    provider: AtpProviderKind | str = AtpProviderKind.VAMPIRE,
    engine: AtpExecutionEngineV2 | None = None,
    **kwargs: Any,
) -> AtpExecutionResultV2:
    """Execute one ATP obligation through the v2 evidence engine."""

    eng = engine or AtpExecutionEngineV2()
    request = AtpExecutionRequestV2(
        request_id=request_id,
        source=source,
        provider=provider,
        **kwargs,
    )
    return eng.execute(request)


def execute_vampire(
    source: str,
    *,
    request_id: str = "req:atp:vampire:1",
    engine: AtpExecutionEngineV2 | None = None,
    **kwargs: Any,
) -> AtpExecutionResultV2:
    return execute_atp(
        source,
        request_id=request_id,
        provider=AtpProviderKind.VAMPIRE,
        engine=engine,
        **kwargs,
    )


def execute_eprover(
    source: str,
    *,
    request_id: str = "req:atp:eprover:1",
    engine: AtpExecutionEngineV2 | None = None,
    **kwargs: Any,
) -> AtpExecutionResultV2:
    return execute_atp(
        source,
        request_id=request_id,
        provider=AtpProviderKind.EPROVER,
        engine=engine,
        **kwargs,
    )


def hermetic_engine(
    *,
    vampire_stdout: str = "",
    eprover_stdout: str = "",
    vampire_kwargs: Mapping[str, Any] | None = None,
    eprover_kwargs: Mapping[str, Any] | None = None,
    proof_checker_id: str = "",
    verify_reconstruction: bool = False,
) -> AtpExecutionEngineV2:
    """Build an engine with hermetic Vampire/E fixture runners."""

    v_kwargs = dict(vampire_kwargs or {})
    e_kwargs = dict(eprover_kwargs or {})
    vampire_version = str(v_kwargs.pop("solver_version", "vampire-hermetic"))
    eprover_version = str(e_kwargs.pop("solver_version", "eprover-hermetic"))
    # Runner kwargs are process-level only (stdout already provided).
    runner_keys = {
        "stderr",
        "returncode",
        "timed_out",
        "unavailable",
        "output_truncated",
        "elapsed_seconds",
    }
    v_runner_kwargs = {key: v_kwargs[key] for key in runner_keys if key in v_kwargs}
    e_runner_kwargs = {key: e_kwargs[key] for key in runner_keys if key in e_kwargs}
    return AtpExecutionEngineV2(
        vampire_runner=(
            hermetic_runner(vampire_stdout, **v_runner_kwargs)
            if vampire_stdout
            else None
        ),
        eprover_runner=(
            hermetic_runner(eprover_stdout, **e_runner_kwargs)
            if eprover_stdout
            else None
        ),
        vampire_version=vampire_version,
        eprover_version=eprover_version,
        proof_checker_id=proof_checker_id,
        verify_reconstruction=verify_reconstruction,
    )


__all__ = [
    "ATP_EXECUTION_V2_GOAL_ID",
    "ATP_EXECUTION_V2_MODULE_VERSION",
    "ATP_EXECUTION_V2_TASK_ID",
    "ATP_PROVIDER_EVIDENCE_V2_INTERFACE",
    "AtpAuthorityError",
    "AtpClaimKind",
    "AtpCountermodelBindingV2",
    "AtpCountermodelStatus",
    "AtpDisposition",
    "AtpExecutionEngineV2",
    "AtpExecutionError",
    "AtpExecutionMode",
    "AtpExecutionRequestV2",
    "AtpExecutionResultV2",
    "AtpInputProfile",
    "AtpProfileBindingV2",
    "AtpProofBindingV2",
    "AtpProofStatus",
    "AtpProviderEvidenceV2",
    "AtpProviderKind",
    "AtpQueryMode",
    "AtpReplayReceiptV2",
    "AtpSourceKind",
    "AtpSzsBindingV2",
    "AtpTranslationBindingV2",
    "atp_success_establishes_theorem",
    "detect_input_profile",
    "execute_atp",
    "execute_eprover",
    "execute_vampire",
    "hermetic_engine",
    "hermetic_runner",
    "non_authoritative_signal_establishes",
    "normalize_atp_provider",
    "provider_backend_id",
    "translation_assumptions_for",
]
