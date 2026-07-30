"""Source frontend registry with explicit semantic profiles.

``SourceFrontendSemanticProfile@1`` is the fail-closed contract every language
frontend must declare before its lowerings can feed authority-bearing software
verification.  Profiles name the admitted construct fragment, numeric / memory
/ concurrency / exception behaviour, undefined and implementation-defined
semantics, unsupported features, and supported-fragment coverage.

Hardened frontends today cover a bounded Python AST subset and a partial
JavaScript/TypeScript surface.  Rust, Go, Java, C, C++, and WASM are staged as
typed profile declarations: they never claim whole-language support, never
grant translation authority from opaque bodies or regex approximations, and
require source spans to survive the pipeline.

This module **owns registry and profile contracts only**.  Actual parsing still
lives in :mod:`ipfs_datasets_py.logic.software_verification.source_adapters`
for Python/ECMAScript; staged languages fail closed until a typed frontend is
wired to the same interface.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.software_verification.source_adapters import (
    SourceAdapterResult,
    SourceAdapterStatus,
    adapt_source_to_software_verification,
)

SOURCE_FRONTEND_SEMANTIC_PROFILE_INTERFACE: Final = "SourceFrontendSemanticProfile@1"
SOURCE_FRONTEND_REGISTRY_INTERFACE: Final = "SourceFrontendRegistry@1"
FRONTEND_REGISTRY_SCHEMA_VERSION: Final = "software-verification-frontend-registry/v1"
FRONTEND_PROFILE_SCHEMA_VERSION: Final = "software-verification-frontend-semantic-profile/v1"

# Languages admitted by the registry (canonical ids).
CANONICAL_LANGUAGES: Final[tuple[str, ...]] = (
    "python",
    "javascript",
    "typescript",
    "rust",
    "go",
    "java",
    "c",
    "cpp",
    "wasm",
)

# Alias map so callers can look up dialect labels without inventing profiles.
_LANGUAGE_ALIASES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "python": "python",
        "py": "python",
        "javascript": "javascript",
        "js": "javascript",
        "jsx": "javascript",
        "mjs": "javascript",
        "cjs": "javascript",
        "typescript": "typescript",
        "ts": "typescript",
        "tsx": "typescript",
        "mts": "typescript",
        "cts": "typescript",
        "rust": "rust",
        "rs": "rust",
        "go": "go",
        "golang": "go",
        "java": "java",
        "c": "c",
        "cpp": "cpp",
        "c++": "cpp",
        "cxx": "cpp",
        "cc": "cpp",
        "wasm": "wasm",
        "webassembly": "wasm",
        "wat": "wasm",
    }
)


class FrontendRegistryError(ValueError):
    """Raised when a frontend profile or registry operation is invalid."""


class DuplicateFrontendError(FrontendRegistryError):
    """Raised when a language is registered more than once."""


class UnknownFrontendError(FrontendRegistryError):
    """Raised when a requested language has no registered profile."""


class FrontendMaturity(StrEnum):
    """How far a frontend has advanced beyond a pure declaration."""

    HARDENED = "hardened"
    PARTIAL = "partial"
    STAGED = "staged"
    DECLARATION_ONLY = "declaration_only"


class ParserFidelity(StrEnum):
    """How source is admitted into the frontend IR."""

    STRUCTURAL_AST = "structural_ast"
    TYPED_AST = "typed_ast"
    REGEX_APPROXIMATION = "regex_approximation"
    NONE = "none"


class CoverageStatus(StrEnum):
    """Supported-fragment coverage classification (never whole-language by default)."""

    FRAGMENT = "fragment"
    PARTIAL_FRAGMENT = "partial_fragment"
    DECLARATION_ONLY = "declaration_only"
    UNSUPPORTED = "unsupported"


class SemanticModelingLevel(StrEnum):
    """How precisely a behavioural dimension is modeled."""

    PRECISE = "precise"
    ABSTRACT = "abstract"
    OPAQUE = "opaque"
    UNSUPPORTED = "unsupported"
    UNDECLARED = "undeclared"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise FrontendRegistryError(
            f"{label} must be a non-empty trimmed string"
        )
    if "\x00" in value:
        raise FrontendRegistryError(f"{label} must not contain NUL bytes")
    return value


def _enum(value: object, enum_type: type[StrEnum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(str(value))
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise FrontendRegistryError(f"{label} must be one of {choices}") from error


def _strings(
    values: Sequence[str] | Iterable[str] | object,
    label: str,
    *,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    if values is None:
        if allow_empty:
            return ()
        raise FrontendRegistryError(f"{label} must not be empty")
    if not isinstance(values, (list, tuple, set, frozenset)):
        raise FrontendRegistryError(f"{label} must be a sequence of strings")
    items = tuple(sorted({_text(item, f"{label} item") for item in values}))
    if not items and not allow_empty:
        raise FrontendRegistryError(f"{label} must not be empty")
    return items


def normalize_language_id(language: str | None) -> str:
    """Map dialect aliases onto a canonical registry language id."""

    if language is None or not isinstance(language, str) or not language.strip():
        raise FrontendRegistryError("language must be a non-empty string")
    key = language.strip().lower().replace(" ", "")
    canonical = _LANGUAGE_ALIASES.get(key)
    if canonical is None:
        raise UnknownFrontendError(f"no frontend profile registered for language {language!r}")
    return canonical


@dataclass(frozen=True, slots=True)
class NumericSemantics:
    """Declared numeric behaviour for one language fragment."""

    level: SemanticModelingLevel | str
    description: str
    integer_model: str
    floating_point_model: str
    overflow_policy: str
    implementation_defined: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "level", _enum(self.level, SemanticModelingLevel, "numeric.level")
        )
        object.__setattr__(self, "description", _text(self.description, "numeric.description"))
        object.__setattr__(
            self, "integer_model", _text(self.integer_model, "numeric.integer_model")
        )
        object.__setattr__(
            self,
            "floating_point_model",
            _text(self.floating_point_model, "numeric.floating_point_model"),
        )
        object.__setattr__(
            self, "overflow_policy", _text(self.overflow_policy, "numeric.overflow_policy")
        )
        object.__setattr__(
            self,
            "implementation_defined",
            _strings(self.implementation_defined, "numeric.implementation_defined"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "floating_point_model": self.floating_point_model,
            "implementation_defined": list(self.implementation_defined),
            "integer_model": self.integer_model,
            "level": self.level.value,
            "overflow_policy": self.overflow_policy,
        }


@dataclass(frozen=True, slots=True)
class MemorySemantics:
    """Declared memory / aliasing behaviour for one language fragment."""

    level: SemanticModelingLevel | str
    description: str
    model: str
    aliasing: str
    undefined_behavior: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "level", _enum(self.level, SemanticModelingLevel, "memory.level")
        )
        object.__setattr__(self, "description", _text(self.description, "memory.description"))
        object.__setattr__(self, "model", _text(self.model, "memory.model"))
        object.__setattr__(self, "aliasing", _text(self.aliasing, "memory.aliasing"))
        object.__setattr__(
            self,
            "undefined_behavior",
            _strings(self.undefined_behavior, "memory.undefined_behavior"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "aliasing": self.aliasing,
            "description": self.description,
            "level": self.level.value,
            "model": self.model,
            "undefined_behavior": list(self.undefined_behavior),
        }


@dataclass(frozen=True, slots=True)
class ConcurrencySemantics:
    """Declared concurrency behaviour for one language fragment."""

    level: SemanticModelingLevel | str
    description: str
    model: str
    memory_ordering: str
    unsupported_features: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "level", _enum(self.level, SemanticModelingLevel, "concurrency.level")
        )
        object.__setattr__(
            self, "description", _text(self.description, "concurrency.description")
        )
        object.__setattr__(self, "model", _text(self.model, "concurrency.model"))
        object.__setattr__(
            self,
            "memory_ordering",
            _text(self.memory_ordering, "concurrency.memory_ordering"),
        )
        object.__setattr__(
            self,
            "unsupported_features",
            _strings(self.unsupported_features, "concurrency.unsupported_features"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "level": self.level.value,
            "memory_ordering": self.memory_ordering,
            "model": self.model,
            "unsupported_features": list(self.unsupported_features),
        }


@dataclass(frozen=True, slots=True)
class ExceptionSemantics:
    """Declared exception / panic / trap behaviour for one language fragment."""

    level: SemanticModelingLevel | str
    description: str
    model: str
    unwinding: str
    unsupported_features: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "level", _enum(self.level, SemanticModelingLevel, "exception.level")
        )
        object.__setattr__(
            self, "description", _text(self.description, "exception.description")
        )
        object.__setattr__(self, "model", _text(self.model, "exception.model"))
        object.__setattr__(self, "unwinding", _text(self.unwinding, "exception.unwinding"))
        object.__setattr__(
            self,
            "unsupported_features",
            _strings(self.unsupported_features, "exception.unsupported_features"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "level": self.level.value,
            "model": self.model,
            "unwinding": self.unwinding,
            "unsupported_features": list(self.unsupported_features),
        }


@dataclass(frozen=True, slots=True)
class SupportedFragmentCoverage:
    """Fail-closed coverage declaration for the admitted fragment only.

    ``whole_language_claim`` must remain false for every partial parser.  The
    coverage ratio is computed over the *documented* construct universe of the
    fragment, never over the full surface of the host language.
    """

    status: CoverageStatus | str
    admitted_constructs: tuple[str, ...]
    documented_unsupported: tuple[str, ...]
    coverage_gates: tuple[str, ...]
    whole_language_claim: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "status", _enum(self.status, CoverageStatus, "coverage.status")
        )
        admitted = _strings(self.admitted_constructs, "coverage.admitted_constructs")
        unsupported = _strings(
            self.documented_unsupported, "coverage.documented_unsupported"
        )
        object.__setattr__(self, "admitted_constructs", admitted)
        object.__setattr__(self, "documented_unsupported", unsupported)
        object.__setattr__(
            self,
            "coverage_gates",
            _strings(self.coverage_gates, "coverage.coverage_gates", allow_empty=False),
        )
        if not isinstance(self.whole_language_claim, bool):
            raise FrontendRegistryError("coverage.whole_language_claim must be a bool")
        if self.whole_language_claim:
            raise FrontendRegistryError(
                "partial parsers must not claim whole-language support; "
                "set whole_language_claim=False and list the admitted fragment"
            )
        if self.notes is None:
            object.__setattr__(self, "notes", "")
        elif not isinstance(self.notes, str) or "\x00" in self.notes:
            raise FrontendRegistryError("coverage.notes must be a string without NUL")

    @property
    def admitted_construct_count(self) -> int:
        return len(self.admitted_constructs)

    @property
    def documented_unsupported_count(self) -> int:
        return len(self.documented_unsupported)

    @property
    def documented_universe_size(self) -> int:
        return self.admitted_construct_count + self.documented_unsupported_count

    @property
    def coverage_ratio(self) -> float:
        """Ratio of admitted constructs over the documented fragment universe."""

        size = self.documented_universe_size
        if size == 0:
            return 0.0
        return self.admitted_construct_count / size

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_construct_count": self.admitted_construct_count,
            "admitted_constructs": list(self.admitted_constructs),
            "coverage_gates": list(self.coverage_gates),
            "coverage_ratio": self.coverage_ratio,
            "documented_unsupported": list(self.documented_unsupported),
            "documented_unsupported_count": self.documented_unsupported_count,
            "documented_universe_size": self.documented_universe_size,
            "notes": self.notes,
            "status": self.status.value,
            "whole_language_claim": self.whole_language_claim,
        }


@dataclass(frozen=True, slots=True)
class SourceFrontendSemanticProfile:
    """Immutable semantic profile for one source-language frontend.

    Interface: ``SourceFrontendSemanticProfile@1``.
    """

    language_id: str
    display_name: str
    maturity: FrontendMaturity | str
    parser_fidelity: ParserFidelity | str
    parsed_constructs: tuple[str, ...]
    unsupported_features: tuple[str, ...]
    numeric: NumericSemantics
    memory: MemorySemantics
    concurrency: ConcurrencySemantics
    exceptions: ExceptionSemantics
    undefined_or_implementation_defined: tuple[str, ...]
    coverage: SupportedFragmentCoverage
    source_spans_required: bool = True
    opaque_bodies_admitted: bool = False
    opaque_bodies_fully_modeled: bool = False
    uses_regex_approximation: bool = False
    translation_enabled: bool = False
    media_types: tuple[str, ...] = ()
    file_suffixes: tuple[str, ...] = ()
    frontend_version: str = "v1"
    interface: str = SOURCE_FRONTEND_SEMANTIC_PROFILE_INTERFACE
    schema_version: str = FRONTEND_PROFILE_SCHEMA_VERSION
    metadata: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "language_id", _text(self.language_id, "language_id").lower()
        )
        object.__setattr__(
            self, "display_name", _text(self.display_name, "display_name")
        )
        object.__setattr__(
            self, "maturity", _enum(self.maturity, FrontendMaturity, "maturity")
        )
        object.__setattr__(
            self,
            "parser_fidelity",
            _enum(self.parser_fidelity, ParserFidelity, "parser_fidelity"),
        )
        object.__setattr__(
            self,
            "parsed_constructs",
            _strings(self.parsed_constructs, "parsed_constructs"),
        )
        object.__setattr__(
            self,
            "unsupported_features",
            _strings(self.unsupported_features, "unsupported_features", allow_empty=False),
        )
        if not isinstance(self.numeric, NumericSemantics):
            raise FrontendRegistryError("numeric must be a NumericSemantics instance")
        if not isinstance(self.memory, MemorySemantics):
            raise FrontendRegistryError("memory must be a MemorySemantics instance")
        if not isinstance(self.concurrency, ConcurrencySemantics):
            raise FrontendRegistryError(
                "concurrency must be a ConcurrencySemantics instance"
            )
        if not isinstance(self.exceptions, ExceptionSemantics):
            raise FrontendRegistryError(
                "exceptions must be an ExceptionSemantics instance"
            )
        object.__setattr__(
            self,
            "undefined_or_implementation_defined",
            _strings(
                self.undefined_or_implementation_defined,
                "undefined_or_implementation_defined",
                allow_empty=False,
            ),
        )
        if not isinstance(self.coverage, SupportedFragmentCoverage):
            raise FrontendRegistryError(
                "coverage must be a SupportedFragmentCoverage instance"
            )
        for flag_name in (
            "source_spans_required",
            "opaque_bodies_admitted",
            "opaque_bodies_fully_modeled",
            "uses_regex_approximation",
            "translation_enabled",
        ):
            if not isinstance(getattr(self, flag_name), bool):
                raise FrontendRegistryError(f"{flag_name} must be a bool")
        object.__setattr__(
            self, "media_types", _strings(self.media_types, "media_types")
        )
        object.__setattr__(
            self, "file_suffixes", _strings(self.file_suffixes, "file_suffixes")
        )
        object.__setattr__(
            self, "frontend_version", _text(self.frontend_version, "frontend_version")
        )
        object.__setattr__(
            self,
            "interface",
            _text(self.interface, "interface"),
        )
        if self.interface != SOURCE_FRONTEND_SEMANTIC_PROFILE_INTERFACE:
            raise FrontendRegistryError(
                f"interface must be {SOURCE_FRONTEND_SEMANTIC_PROFILE_INTERFACE!r}"
            )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        meta = (
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(self.metadata)
        )
        object.__setattr__(self, "metadata", meta)
        # Fail-closed consistency rules for authority-sensitive flags.
        if self.parser_fidelity is ParserFidelity.REGEX_APPROXIMATION:
            if not self.uses_regex_approximation:
                raise FrontendRegistryError(
                    "regex_approximation fidelity requires uses_regex_approximation=True"
                )
        if self.opaque_bodies_fully_modeled and not self.opaque_bodies_admitted:
            raise FrontendRegistryError(
                "opaque_bodies_fully_modeled requires opaque_bodies_admitted=True"
            )
        if self.coverage.whole_language_claim:
            raise FrontendRegistryError(
                "profiles must not claim whole-language support from a partial parser"
            )
        if self.maturity is FrontendMaturity.HARDENED and not self.parsed_constructs:
            raise FrontendRegistryError(
                "hardened frontends must declare a non-empty parsed construct fragment"
            )

    # ------------------------------------------------------------------
    # Authority and coverage
    # ------------------------------------------------------------------

    @property
    def blocks_translation_authority(self) -> bool:
        """True when opaque bodies or regex approximations forbid authority."""

        if self.uses_regex_approximation:
            return True
        if self.parser_fidelity is ParserFidelity.REGEX_APPROXIMATION:
            return True
        if self.parser_fidelity is ParserFidelity.NONE:
            return True
        if self.opaque_bodies_admitted and not self.opaque_bodies_fully_modeled:
            return True
        if self.maturity in {
            FrontendMaturity.STAGED,
            FrontendMaturity.DECLARATION_ONLY,
        }:
            return True
        if not self.translation_enabled:
            return True
        return False

    def translation_authority_ceiling(self) -> EvidenceAuthority:
        """Maximum evidence authority this profile may contribute.

        Opaque bodies and regex approximations always collapse to
        :attr:`EvidenceAuthority.NONE`.  Hardened structural fragments may
        reach ``bounded`` only when translation is enabled and bodies are
        fully modeled (or never admitted as opaque).
        """

        if self.blocks_translation_authority:
            return EvidenceAuthority.NONE
        if self.maturity is FrontendMaturity.PARTIAL:
            return EvidenceAuthority.ADVISORY
        if self.maturity is FrontendMaturity.HARDENED:
            return EvidenceAuthority.BOUNDED
        return EvidenceAuthority.NONE

    def admits_construct(self, construct: str) -> bool:
        key = _text(construct, "construct")
        return key in self.parsed_constructs

    def documents_unsupported(self, construct: str) -> bool:
        key = _text(construct, "construct")
        return key in self.unsupported_features or key in self.coverage.documented_unsupported

    def evaluate_observed_constructs(
        self,
        observed: Sequence[str] | Iterable[str],
    ) -> dict[str, Any]:
        """Classify observed constructs against the admitted fragment fail-closed."""

        items = _strings(tuple(observed), "observed constructs")
        admitted: list[str] = []
        unsupported: list[str] = []
        unknown: list[str] = []
        for item in items:
            if item in self.parsed_constructs:
                admitted.append(item)
            elif item in self.unsupported_features or item in self.coverage.documented_unsupported:
                unsupported.append(item)
            else:
                unknown.append(item)
        # Unknown constructs are treated as unsupported (fail-closed).
        fail_closed = bool(unknown) or bool(unsupported)
        return {
            "admitted": admitted,
            "authority_ceiling": self.translation_authority_ceiling().value,
            "fail_closed": fail_closed,
            "observed": list(items),
            "unknown_treated_as_unsupported": unknown,
            "unsupported": unsupported,
            "whole_language_claim": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocks_translation_authority": self.blocks_translation_authority,
            "concurrency": self.concurrency.to_dict(),
            "coverage": self.coverage.to_dict(),
            "display_name": self.display_name,
            "exceptions": self.exceptions.to_dict(),
            "file_suffixes": list(self.file_suffixes),
            "frontend_version": self.frontend_version,
            "interface": self.interface,
            "language_id": self.language_id,
            "maturity": self.maturity.value,
            "media_types": list(self.media_types),
            "memory": self.memory.to_dict(),
            "metadata": self.metadata.to_dict(),
            "numeric": self.numeric.to_dict(),
            "opaque_bodies_admitted": self.opaque_bodies_admitted,
            "opaque_bodies_fully_modeled": self.opaque_bodies_fully_modeled,
            "parsed_constructs": list(self.parsed_constructs),
            "parser_fidelity": self.parser_fidelity.value,
            "schema_version": self.schema_version,
            "source_spans_required": self.source_spans_required,
            "translation_authority_ceiling": self.translation_authority_ceiling().value,
            "translation_enabled": self.translation_enabled,
            "undefined_or_implementation_defined": list(
                self.undefined_or_implementation_defined
            ),
            "unsupported_features": list(self.unsupported_features),
            "uses_regex_approximation": self.uses_regex_approximation,
        }


# ---------------------------------------------------------------------------
# Source-mapping helpers (pipeline survival)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceMappingSnapshot:
    """Source-ref / span ids extracted from adapter or pipeline artifacts."""

    language_id: str
    source_ref_ids: tuple[str, ...]
    span_ids: tuple[str, ...]
    path: str = ""
    status: str = ""
    authority_ceiling: str = EvidenceAuthority.NONE.value
    intact: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling,
            "intact": self.intact,
            "language_id": self.language_id,
            "path": self.path,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "status": self.status,
        }


def extract_source_mapping(
    result: SourceAdapterResult,
    *,
    profile: SourceFrontendSemanticProfile | None = None,
) -> SourceMappingSnapshot:
    """Extract source mapping from an adapter result and check survival basics."""

    if not isinstance(result, SourceAdapterResult):
        raise FrontendRegistryError("result must be a SourceAdapterResult")
    language = normalize_language_id(result.language) if result.language else (
        profile.language_id if profile is not None else "python"
    )
    source_ref_ids: set[str] = set()
    span_ids: set[str] = set()
    if result.program is not None:
        for source in result.program.sources:
            source_ref_ids.add(source.ref_id)
        for span in result.program.spans:
            span_ids.add(span.span_id)
            if span.source_ref_id:
                source_ref_ids.add(span.source_ref_id)
        for function in result.program.functions:
            source_ref_ids.update(function.source_ref_ids)
            span_ids.update(function.span_ids)
        for symbol in result.program.symbols:
            source_ref_ids.update(symbol.source_ref_ids)
            span_ids.update(symbol.span_ids)
    if result.document is not None:
        for source in result.document.sources:
            source_ref_ids.add(source.ref_id)
        for span in result.document.spans:
            span_ids.add(span.span_id)
            if span.source_ref_id:
                source_ref_ids.add(span.source_ref_id)
        for decl in result.document.declarations:
            source_ref_ids.update(decl.source_ref_ids)
            span_ids.update(decl.span_ids)
        for prop in result.document.properties:
            source_ref_ids.update(prop.source_ref_ids)
            span_ids.update(prop.span_ids)
        for assumption in result.document.assumptions:
            source_ref_ids.update(getattr(assumption, "source_ref_ids", ()) or ())
            span_ids.update(getattr(assumption, "span_ids", ()) or ())
    for request in result.backend_requests:
        source_ref_ids.update(request.source_ref_ids)

    requires_spans = True if profile is None else profile.source_spans_required
    has_sources = bool(source_ref_ids)
    has_spans = bool(span_ids)
    intact = has_sources and (has_spans if requires_spans else True)
    # Successful / partial adaptations that produce a program must keep mapping.
    if result.program is not None and not intact:
        intact = False
    authority = (
        profile.translation_authority_ceiling().value
        if profile is not None
        else EvidenceAuthority.NONE.value
    )
    return SourceMappingSnapshot(
        language_id=language,
        source_ref_ids=tuple(sorted(source_ref_ids)),
        span_ids=tuple(sorted(span_ids)),
        path=result.path,
        status=result.status.value if isinstance(result.status, SourceAdapterStatus) else str(result.status),
        authority_ceiling=authority,
        intact=intact,
    )


def source_mapping_survives_adapter(
    source: str,
    *,
    path: str = "",
    language: str = "",
    profile: SourceFrontendSemanticProfile | None = None,
) -> SourceMappingSnapshot:
    """Adapt source and verify source mapping remains intact end-to-end."""

    result = adapt_source_to_software_verification(
        source, path=path, language=language
    )
    return extract_source_mapping(result, profile=profile)


def authority_for_adapter_result(
    profile: SourceFrontendSemanticProfile,
    result: SourceAdapterResult,
) -> EvidenceAuthority:
    """Compute effective translation authority for one adaptation under a profile.

    Fail-closed rules:
    * profile-level opaque / regex blocks always force ``none``;
    * adapter-reported opaque bodies force ``none``;
    * unsupported / malformed adaptations force ``none``;
    * incomplete (partial) adaptations cannot exceed ``advisory``.
    """

    if profile.blocks_translation_authority:
        return EvidenceAuthority.NONE
    unsupported = set(result.unsupported_constructs)
    if any("opaque" in item for item in unsupported):
        return EvidenceAuthority.NONE
    if result.program is not None:
        for function in result.program.functions:
            # Declaration payload marks JS opaque bodies.
            pass
    if result.document is not None:
        for decl in result.document.declarations:
            payload = decl.payload if isinstance(decl.payload, Mapping) else {}
            if payload.get("opaque_body") is True:
                return EvidenceAuthority.NONE
            if payload.get("complete_lowering") is False:
                # Incomplete lowering cannot carry bounded authority.
                ceiling = profile.translation_authority_ceiling()
                if ceiling is EvidenceAuthority.BOUNDED:
                    return EvidenceAuthority.ADVISORY
                return EvidenceAuthority.NONE
    if result.status is SourceAdapterStatus.UNSUPPORTED:
        return EvidenceAuthority.NONE
    if result.status is SourceAdapterStatus.MALFORMED:
        return EvidenceAuthority.NONE
    if result.status is SourceAdapterStatus.PARTIAL:
        ceiling = profile.translation_authority_ceiling()
        if ceiling in {EvidenceAuthority.BOUNDED, EvidenceAuthority.ADVISORY}:
            return EvidenceAuthority.ADVISORY
        return EvidenceAuthority.NONE
    return profile.translation_authority_ceiling()


# ---------------------------------------------------------------------------
# Built-in profiles
# ---------------------------------------------------------------------------


_PYTHON_PARSED: Final[tuple[str, ...]] = (
    "python.stmt.FunctionDef",
    "python.stmt.Return",
    "python.stmt.Assign",
    "python.stmt.AnnAssign",
    "python.stmt.If",
    "python.stmt.Pass",
    "python.stmt.Expr",
    "python.expr.Constant",
    "python.expr.Name",
    "python.expr.BinOp",
    "python.expr.UnaryOp",
    "python.expr.Compare",
    "python.expr.BoolOp",
    "python.expr.Call",
    "python.expr.Attribute",
    "python.module.Import",
    "python.module.ImportFrom",
)

_PYTHON_UNSUPPORTED: Final[tuple[str, ...]] = (
    "python.async_function",
    "python.class",
    "python.stmt.For",
    "python.stmt.While",
    "python.stmt.With",
    "python.stmt.Try",
    "python.stmt.Raise",
    "python.stmt.Match",
    "python.function.decorators",
    "python.function.vararg",
    "python.function.kwarg",
    "python.function.posonlyargs",
    "python.function.kwonlyargs",
    "python.module_level_assign",
    "python.whole_language",
)

_JS_PARSED: Final[tuple[str, ...]] = (
    "ecmascript.function_declaration",
    "ecmascript.function_expression",
    "ecmascript.arrow_function_header",
    "ecmascript.parameter_list",
    "ecmascript.return_presence",
)

_JS_UNSUPPORTED: Final[tuple[str, ...]] = (
    "ecmascript.opaque_function_body",
    "ecmascript.class",
    "ecmascript.async",
    "ecmascript.complex_arrow",
    "ecmascript.generator",
    "ecmascript.module_namespace",
    "ecmascript.regex_approximation",
    "javascript.whole_language",
    "typescript.whole_language",
)


def _python_profile() -> SourceFrontendSemanticProfile:
    return SourceFrontendSemanticProfile(
        language_id="python",
        display_name="Python",
        maturity=FrontendMaturity.HARDENED,
        parser_fidelity=ParserFidelity.STRUCTURAL_AST,
        parsed_constructs=_PYTHON_PARSED,
        unsupported_features=_PYTHON_UNSUPPORTED,
        numeric=NumericSemantics(
            level=SemanticModelingLevel.ABSTRACT,
            description=(
                "Integers are unbounded mathematical integers in the admitted "
                "fragment; floating-point and complex numbers are unsupported."
            ),
            integer_model="unbounded_mathematical_int",
            floating_point_model="unsupported",
            overflow_policy="not_applicable_unbounded_int",
            implementation_defined=("int_to_str_formatting",),
        ),
        memory=MemorySemantics(
            level=SemanticModelingLevel.ABSTRACT,
            description=(
                "Memory is modeled as abstract object identity without a precise "
                "heap graph; aliasing is not resolved beyond name binding."
            ),
            model="abstract_objects",
            aliasing="name_binding_only",
            undefined_behavior=("use_after_free_not_applicable",),
        ),
        concurrency=ConcurrencySemantics(
            level=SemanticModelingLevel.UNSUPPORTED,
            description=(
                "The admitted subset is sequential and single-threaded; the GIL, "
                "threads, asyncio, and multiprocessing are not modeled."
            ),
            model="sequential",
            memory_ordering="not_modeled",
            unsupported_features=(
                "threading",
                "asyncio",
                "multiprocessing",
                "gil_interleaving",
            ),
        ),
        exceptions=ExceptionSemantics(
            level=SemanticModelingLevel.UNSUPPORTED,
            description=(
                "try/except/raise/finally are outside the admitted fragment and "
                "are retained as unsupported diagnostics rather than executed."
            ),
            model="not_modeled",
            unwinding="not_modeled",
            unsupported_features=("try", "except", "raise", "finally", "with"),
        ),
        undefined_or_implementation_defined=(
            "hash_randomization",
            "dict_iteration_order_pre_3_7_not_assumed",
            "float_repr",
            "CPython_vs_alternate_runtime_extensions",
            "eval_exec_dynamic_code",
        ),
        coverage=SupportedFragmentCoverage(
            status=CoverageStatus.FRAGMENT,
            admitted_constructs=_PYTHON_PARSED,
            documented_unsupported=_PYTHON_UNSUPPORTED,
            coverage_gates=(
                "fail_closed_unknown_construct",
                "no_whole_language_claim",
                "source_spans_required",
                "unsupported_retained_as_diagnostics",
            ),
            whole_language_claim=False,
            notes="Bounded Python AST subset only; never whole CPython semantics.",
        ),
        source_spans_required=True,
        opaque_bodies_admitted=False,
        opaque_bodies_fully_modeled=False,
        uses_regex_approximation=False,
        translation_enabled=True,
        media_types=("text/x-python",),
        file_suffixes=(".py", ".pyi"),
        metadata={"adapter": "SourceSoftwareVerificationAdapter@1", "stage": "hardened"},
    )


def _ecmascript_profile(
    *,
    language_id: str,
    display_name: str,
    media_types: tuple[str, ...],
    file_suffixes: tuple[str, ...],
) -> SourceFrontendSemanticProfile:
    return SourceFrontendSemanticProfile(
        language_id=language_id,
        display_name=display_name,
        maturity=FrontendMaturity.PARTIAL,
        parser_fidelity=ParserFidelity.REGEX_APPROXIMATION,
        parsed_constructs=_JS_PARSED,
        unsupported_features=_JS_UNSUPPORTED,
        numeric=NumericSemantics(
            level=SemanticModelingLevel.ABSTRACT,
            description=(
                "ECMAScript numbers are IEEE-754 float64 at runtime; the staged "
                "frontend does not lower numeric operators and treats bodies as opaque."
            ),
            integer_model="not_lowered",
            floating_point_model="ieee754_float64_undeclared_in_opaque_body",
            overflow_policy="not_modeled_opaque_body",
            implementation_defined=("ToNumber_coercion", "bigint_vs_number"),
        ),
        memory=MemorySemantics(
            level=SemanticModelingLevel.OPAQUE,
            description=(
                "Object identity, prototype chains, and heap mutation are not "
                "modeled; function bodies remain opaque."
            ),
            model="opaque",
            aliasing="not_modeled",
            undefined_behavior=("prototype_mutation", "proxy_traps"),
        ),
        concurrency=ConcurrencySemantics(
            level=SemanticModelingLevel.UNSUPPORTED,
            description=(
                "The event loop, Workers, Atomics, and SharedArrayBuffer are "
                "outside the admitted fragment."
            ),
            model="not_modeled",
            memory_ordering="not_modeled",
            unsupported_features=("async", "await", "worker", "atomics", "sharedarraybuffer"),
        ),
        exceptions=ExceptionSemantics(
            level=SemanticModelingLevel.OPAQUE,
            description=(
                "throw/try/catch/finally live inside opaque bodies and cannot "
                "receive translation authority."
            ),
            model="opaque_body",
            unwinding="not_modeled",
            unsupported_features=("throw", "try", "catch", "finally"),
        ),
        undefined_or_implementation_defined=(
            "host_object_behavior",
            "annex_b_legacy_features",
            "engine_specific_optimizations",
            "type_erasure_of_typescript",
        ),
        coverage=SupportedFragmentCoverage(
            status=CoverageStatus.PARTIAL_FRAGMENT,
            admitted_constructs=_JS_PARSED,
            documented_unsupported=_JS_UNSUPPORTED,
            coverage_gates=(
                "opaque_body_blocks_authority",
                "regex_approximation_blocks_authority",
                "no_whole_language_claim",
                "source_spans_required",
            ),
            whole_language_claim=False,
            notes=(
                "Function headers are regex-approximated; bodies stay opaque and "
                "must never carry translation authority."
            ),
        ),
        source_spans_required=True,
        opaque_bodies_admitted=True,
        opaque_bodies_fully_modeled=False,
        uses_regex_approximation=True,
        translation_enabled=False,
        media_types=media_types,
        file_suffixes=file_suffixes,
        metadata={
            "adapter": "SourceSoftwareVerificationAdapter@1",
            "stage": "partial",
            "opaque_body": True,
            "regex_approximation": True,
        },
    )


def _staged_typed_profile(
    *,
    language_id: str,
    display_name: str,
    media_types: tuple[str, ...],
    file_suffixes: tuple[str, ...],
    parsed_constructs: tuple[str, ...],
    unsupported_features: tuple[str, ...],
    numeric: NumericSemantics,
    memory: MemorySemantics,
    concurrency: ConcurrencySemantics,
    exceptions: ExceptionSemantics,
    undefined_or_implementation_defined: tuple[str, ...],
    notes: str,
) -> SourceFrontendSemanticProfile:
    return SourceFrontendSemanticProfile(
        language_id=language_id,
        display_name=display_name,
        maturity=FrontendMaturity.STAGED,
        parser_fidelity=ParserFidelity.TYPED_AST,
        parsed_constructs=parsed_constructs,
        unsupported_features=unsupported_features,
        numeric=numeric,
        memory=memory,
        concurrency=concurrency,
        exceptions=exceptions,
        undefined_or_implementation_defined=undefined_or_implementation_defined,
        coverage=SupportedFragmentCoverage(
            status=CoverageStatus.DECLARATION_ONLY,
            admitted_constructs=parsed_constructs,
            documented_unsupported=unsupported_features,
            coverage_gates=(
                "staged_no_translation_authority",
                "no_whole_language_claim",
                "source_spans_required",
                "fail_closed_until_typed_frontend_wired",
            ),
            whole_language_claim=False,
            notes=notes,
        ),
        source_spans_required=True,
        opaque_bodies_admitted=False,
        opaque_bodies_fully_modeled=False,
        uses_regex_approximation=False,
        translation_enabled=False,
        media_types=media_types,
        file_suffixes=file_suffixes,
        metadata={"stage": "staged_typed", "production_frontend": False},
    )


def _builtin_profiles() -> tuple[SourceFrontendSemanticProfile, ...]:
    rust = _staged_typed_profile(
        language_id="rust",
        display_name="Rust",
        media_types=("text/x-rust",),
        file_suffixes=(".rs",),
        parsed_constructs=(
            "rust.item.fn_signature",
            "rust.type.path",
            "rust.pat.ident",
        ),
        unsupported_features=(
            "rust.whole_language",
            "rust.unsafe",
            "rust.async",
            "rust.macro",
            "rust.const_generics",
            "rust.trait_object",
            "rust.interior_mutability",
        ),
        numeric=NumericSemantics(
            level=SemanticModelingLevel.ABSTRACT,
            description="Staged: fixed-width integer and float types declared, not lowered.",
            integer_model="fixed_width_declared",
            floating_point_model="ieee754_declared",
            overflow_policy="debug_panic_release_wrap_undeclared",
            implementation_defined=("target_pointer_width",),
        ),
        memory=MemorySemantics(
            level=SemanticModelingLevel.ABSTRACT,
            description="Ownership/borrow is declared as the intended model; not yet lowered.",
            model="ownership_borrow_declared",
            aliasing="borrow_checker_not_executed",
            undefined_behavior=("unsafe_raw_pointer", "data_race_in_unsafe"),
        ),
        concurrency=ConcurrencySemantics(
            level=SemanticModelingLevel.UNSUPPORTED,
            description="Send/Sync and async executors are outside the staged fragment.",
            model="not_modeled",
            memory_ordering="not_modeled",
            unsupported_features=("thread", "async", "atomic", "mpsc"),
        ),
        exceptions=ExceptionSemantics(
            level=SemanticModelingLevel.ABSTRACT,
            description="panic/Result/Option are declared; unwinding is not modeled.",
            model="result_option_declared",
            unwinding="panic_unwinding_not_modeled",
            unsupported_features=("panic_hook", "catch_unwind"),
        ),
        undefined_or_implementation_defined=(
            "unsafe_blocks",
            "niche_layout",
            "target_specific_abi",
        ),
        notes="Staged typed Rust frontend profile; no production lowering yet.",
    )
    go = _staged_typed_profile(
        language_id="go",
        display_name="Go",
        media_types=("text/x-go",),
        file_suffixes=(".go",),
        parsed_constructs=(
            "go.decl.func",
            "go.type.ident",
            "go.stmt.return",
        ),
        unsupported_features=(
            "go.whole_language",
            "go.goroutine",
            "go.channel",
            "go.select",
            "go.interface_method_set",
            "go.unsafe",
            "go.cgo",
        ),
        numeric=NumericSemantics(
            level=SemanticModelingLevel.ABSTRACT,
            description="Staged: platform-dependent int/uint sizes declared, not lowered.",
            integer_model="platform_int_declared",
            floating_point_model="ieee754_declared",
            overflow_policy="wraparound_undeclared",
            implementation_defined=("int_size", "uintptr_size"),
        ),
        memory=MemorySemantics(
            level=SemanticModelingLevel.ABSTRACT,
            description="GC heap declared; precise alias analysis not available in stage.",
            model="gc_heap_declared",
            aliasing="not_modeled",
            undefined_behavior=("data_race", "unsafe_pointer"),
        ),
        concurrency=ConcurrencySemantics(
            level=SemanticModelingLevel.UNSUPPORTED,
            description="Goroutines and channels are explicitly unsupported in stage 1.",
            model="not_modeled",
            memory_ordering="happens_before_not_modeled",
            unsupported_features=("goroutine", "channel", "select", "sync.Mutex"),
        ),
        exceptions=ExceptionSemantics(
            level=SemanticModelingLevel.ABSTRACT,
            description="panic/recover declared unsupported for translation authority.",
            model="panic_recover_not_modeled",
            unwinding="not_modeled",
            unsupported_features=("panic", "recover", "defer"),
        ),
        undefined_or_implementation_defined=(
            "map_iteration_order",
            "scheduler_preemption",
            "race_detector_semantics",
        ),
        notes="Staged typed Go frontend profile; concurrency fails closed.",
    )
    java = _staged_typed_profile(
        language_id="java",
        display_name="Java",
        media_types=("text/x-java-source",),
        file_suffixes=(".java",),
        parsed_constructs=(
            "java.decl.method",
            "java.type.reference",
            "java.stmt.return",
        ),
        unsupported_features=(
            "java.whole_language",
            "java.reflection",
            "java.native",
            "java.synchronized",
            "java.volatile",
            "java.lambda_capture",
            "java.generics_erasure_edge_cases",
        ),
        numeric=NumericSemantics(
            level=SemanticModelingLevel.ABSTRACT,
            description="JVM primitive widths declared; operator lowering not staged yet.",
            integer_model="jvm_primitives_declared",
            floating_point_model="ieee754_declared",
            overflow_policy="silent_wrap_declared",
            implementation_defined=("strict_fp_legacy",),
        ),
        memory=MemorySemantics(
            level=SemanticModelingLevel.ABSTRACT,
            description="Java Memory Model is referenced but not executed in stage 1.",
            model="jmm_declared",
            aliasing="reference_identity_declared",
            undefined_behavior=(),  # Java has no C-style UB; empty is intentional
        ),
        concurrency=ConcurrencySemantics(
            level=SemanticModelingLevel.UNSUPPORTED,
            description="Threads, synchronized, and volatile are outside stage 1.",
            model="not_modeled",
            memory_ordering="jmm_not_executed",
            unsupported_features=("Thread", "synchronized", "volatile", "varhandle"),
        ),
        exceptions=ExceptionSemantics(
            level=SemanticModelingLevel.ABSTRACT,
            description="Checked/unchecked exceptions declared; control transfer not lowered.",
            model="throwable_declared",
            unwinding="not_modeled",
            unsupported_features=("try", "catch", "finally", "try_with_resources"),
        ),
        undefined_or_implementation_defined=(
            "class_initialization_order",
            "finalizer_timing",
            "jvm_vendor_extensions",
        ),
        notes="Staged typed Java frontend profile; no whole-JLS claim.",
    )
    c_lang = _staged_typed_profile(
        language_id="c",
        display_name="C",
        media_types=("text/x-c",),
        file_suffixes=(".c", ".h"),
        parsed_constructs=(
            "c.decl.function",
            "c.type.basic",
            "c.stmt.return",
        ),
        unsupported_features=(
            "c.whole_language",
            "c.undefined_behavior_execution",
            "c.inline_assembly",
            "c.preprocessor_full",
            "c.vla",
            "c.setjmp_longjmp",
            "c.signal",
        ),
        numeric=NumericSemantics(
            level=SemanticModelingLevel.ABSTRACT,
            description="ISO C integer promotions declared; UB on overflow not executed.",
            integer_model="iso_c_integers_declared",
            floating_point_model="iec60559_optional_declared",
            overflow_policy="signed_overflow_ub_not_executed",
            implementation_defined=("char_signedness", "int_width", "endianness"),
        ),
        memory=MemorySemantics(
            level=SemanticModelingLevel.ABSTRACT,
            description="Abstract machine memory declared; provenance not tracked yet.",
            model="iso_c_abstract_machine_declared",
            aliasing="strict_aliasing_declared",
            undefined_behavior=(
                "use_after_free",
                "buffer_overflow",
                "uninitialized_read",
                "null_deref",
            ),
        ),
        concurrency=ConcurrencySemantics(
            level=SemanticModelingLevel.UNSUPPORTED,
            description="C11 threads/atomics are outside stage 1.",
            model="not_modeled",
            memory_ordering="not_modeled",
            unsupported_features=("threads.h", "stdatomic.h", "signal_handlers"),
        ),
        exceptions=ExceptionSemantics(
            level=SemanticModelingLevel.UNSUPPORTED,
            description="C has no exceptions; longjmp is unsupported.",
            model="not_applicable",
            unwinding="not_applicable",
            unsupported_features=("setjmp", "longjmp"),
        ),
        undefined_or_implementation_defined=(
            "signed_overflow",
            "pointer_provenance",
            "evaluation_order",
            "trap_representations",
            "implementation_defined_pragma",
        ),
        notes="Staged typed C frontend; UB listed, never silently executed.",
    )
    cpp = _staged_typed_profile(
        language_id="cpp",
        display_name="C++",
        media_types=("text/x-c++",),
        file_suffixes=(".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"),
        parsed_constructs=(
            "cpp.decl.function",
            "cpp.type.simple",
            "cpp.stmt.return",
        ),
        unsupported_features=(
            "cpp.whole_language",
            "cpp.templates_full",
            "cpp.exceptions",
            "cpp.virtual_dispatch",
            "cpp.undefined_behavior_execution",
            "cpp.inline_assembly",
            "cpp.coroutines",
        ),
        numeric=NumericSemantics(
            level=SemanticModelingLevel.ABSTRACT,
            description="C++ integer/float ranks declared; constexpr not evaluated in stage.",
            integer_model="iso_cpp_integers_declared",
            floating_point_model="ieee754_declared",
            overflow_policy="signed_overflow_ub_not_executed",
            implementation_defined=("char_signedness", "abi"),
        ),
        memory=MemorySemantics(
            level=SemanticModelingLevel.ABSTRACT,
            description="Object model / lifetime declared; not lowered.",
            model="cpp_object_model_declared",
            aliasing="strict_aliasing_declared",
            undefined_behavior=(
                "use_after_free",
                "invalid_downcast",
                "data_race",
                "uninitialized_read",
            ),
        ),
        concurrency=ConcurrencySemantics(
            level=SemanticModelingLevel.UNSUPPORTED,
            description="std::thread and atomics are outside stage 1.",
            model="not_modeled",
            memory_ordering="not_modeled",
            unsupported_features=("std::thread", "std::atomic", "memory_order"),
        ),
        exceptions=ExceptionSemantics(
            level=SemanticModelingLevel.UNSUPPORTED,
            description="C++ exceptions are outside stage 1.",
            model="not_modeled",
            unwinding="not_modeled",
            unsupported_features=("throw", "try", "catch", "noexcept_violation"),
        ),
        undefined_or_implementation_defined=(
            "signed_overflow",
            "lifetime_rules",
            "odr",
            "template_instantiation_order",
        ),
        notes="Staged typed C++ frontend; templates/exceptions fail closed.",
    )
    wasm = _staged_typed_profile(
        language_id="wasm",
        display_name="WebAssembly",
        media_types=("application/wasm", "text/webassembly"),
        file_suffixes=(".wasm", ".wat"),
        parsed_constructs=(
            "wasm.module.func_type",
            "wasm.instr.local_get",
            "wasm.instr.i32_const",
        ),
        unsupported_features=(
            "wasm.whole_language",
            "wasm.threads_proposal",
            "wasm.simd",
            "wasm.gc_proposal",
            "wasm.exception_handling",
            "wasm.host_bindings",
        ),
        numeric=NumericSemantics(
            level=SemanticModelingLevel.ABSTRACT,
            description="i32/i64/f32/f64 operations declared; not yet lowered to SMT.",
            integer_model="wasm_i32_i64_declared",
            floating_point_model="ieee754_wasm_declared",
            overflow_policy="wrap_trapping_div_declared",
            implementation_defined=("non_determinism_nan",),
        ),
        memory=MemorySemantics(
            level=SemanticModelingLevel.ABSTRACT,
            description="Linear memory declared; bounds checks not executed in stage.",
            model="linear_memory_declared",
            aliasing="byte_addressable_declared",
            undefined_behavior=(),  # WASM traps rather than UB
        ),
        concurrency=ConcurrencySemantics(
            level=SemanticModelingLevel.UNSUPPORTED,
            description="Threads proposal is outside stage 1.",
            model="not_modeled",
            memory_ordering="not_modeled",
            unsupported_features=("threads", "shared_memory", "atomic_rmw"),
        ),
        exceptions=ExceptionSemantics(
            level=SemanticModelingLevel.ABSTRACT,
            description="Traps are declared; exception-handling proposal unsupported.",
            model="trap_declared",
            unwinding="not_modeled",
            unsupported_features=("exception_handling_proposal",),
        ),
        undefined_or_implementation_defined=(
            "nan_canonicalization",
            "host_function_divergence",
            "resource_limits",
        ),
        notes="Staged typed WASM frontend; traps listed, no whole-spec claim.",
    )
    return (
        _python_profile(),
        _ecmascript_profile(
            language_id="javascript",
            display_name="JavaScript",
            media_types=("text/javascript", "application/javascript"),
            file_suffixes=(".js", ".mjs", ".cjs", ".jsx"),
        ),
        _ecmascript_profile(
            language_id="typescript",
            display_name="TypeScript",
            media_types=("application/typescript", "text/typescript"),
            file_suffixes=(".ts", ".mts", ".cts", ".tsx"),
        ),
        rust,
        go,
        java,
        c_lang,
        cpp,
        wasm,
    )


class FrontendRegistry:
    """Side-effect-free registry of source-frontend semantic profiles."""

    INTERFACE: Final = SOURCE_FRONTEND_REGISTRY_INTERFACE
    SCHEMA_VERSION: Final = FRONTEND_REGISTRY_SCHEMA_VERSION

    def __init__(
        self,
        profiles: Sequence[SourceFrontendSemanticProfile] | None = None,
    ) -> None:
        self._profiles: dict[str, SourceFrontendSemanticProfile] = {}
        initial = tuple(profiles) if profiles is not None else _builtin_profiles()
        for profile in initial:
            self.register(profile)

    def register(self, profile: SourceFrontendSemanticProfile) -> None:
        if not isinstance(profile, SourceFrontendSemanticProfile):
            raise FrontendRegistryError(
                "profile must be a SourceFrontendSemanticProfile instance"
            )
        language_id = profile.language_id
        if language_id in self._profiles:
            raise DuplicateFrontendError(
                f"frontend profile for {language_id!r} is already registered"
            )
        self._profiles[language_id] = profile

    def get(self, language: str) -> SourceFrontendSemanticProfile:
        language_id = normalize_language_id(language)
        try:
            return self._profiles[language_id]
        except KeyError as error:
            raise UnknownFrontendError(
                f"no frontend profile registered for language {language!r}"
            ) from error

    def __getitem__(self, language: str) -> SourceFrontendSemanticProfile:
        return self.get(language)

    def __contains__(self, language: object) -> bool:
        if not isinstance(language, str):
            return False
        try:
            language_id = normalize_language_id(language)
        except FrontendRegistryError:
            return False
        return language_id in self._profiles

    def __iter__(self) -> Iterator[SourceFrontendSemanticProfile]:
        for language_id in sorted(self._profiles):
            yield self._profiles[language_id]

    def __len__(self) -> int:
        return len(self._profiles)

    def languages(self) -> tuple[str, ...]:
        return tuple(sorted(self._profiles))

    def profiles(self) -> tuple[SourceFrontendSemanticProfile, ...]:
        return tuple(self)

    def require_no_whole_language_claims(self) -> None:
        for profile in self:
            if profile.coverage.whole_language_claim:
                raise FrontendRegistryError(
                    f"{profile.language_id} claims whole-language support"
                )

    def authority_matrix(self) -> dict[str, str]:
        return {
            profile.language_id: profile.translation_authority_ceiling().value
            for profile in self
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_matrix": self.authority_matrix(),
            "interface": self.INTERFACE,
            "languages": list(self.languages()),
            "profiles": {
                profile.language_id: profile.to_dict() for profile in self
            },
            "schema_version": self.SCHEMA_VERSION,
        }


_DEFAULT_REGISTRY: FrontendRegistry | None = None


def default_frontend_registry() -> FrontendRegistry:
    """Return the process-wide default registry of built-in profiles."""

    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = FrontendRegistry()
    return _DEFAULT_REGISTRY


def get_frontend_profile(language: str) -> SourceFrontendSemanticProfile:
    """Look up a profile from the default registry."""

    return default_frontend_registry().get(language)


def list_frontend_profiles() -> tuple[SourceFrontendSemanticProfile, ...]:
    """List all profiles from the default registry."""

    return default_frontend_registry().profiles()


def adapt_with_profile(
    source: str,
    *,
    path: str = "",
    language: str = "",
    registry: FrontendRegistry | None = None,
) -> tuple[SourceFrontendSemanticProfile, SourceAdapterResult, SourceMappingSnapshot, EvidenceAuthority]:
    """Adapt source under its declared profile and return mapping + authority."""

    reg = registry if registry is not None else default_frontend_registry()
    result = adapt_source_to_software_verification(
        source, path=path, language=language
    )
    # Prefer explicit language, then adapter detection, then path-inferred.
    lang = language or result.language or ""
    try:
        profile = reg.get(lang)
    except UnknownFrontendError:
        # Staged languages without adapters still expose their profile when
        # the caller named them; otherwise re-raise.
        if language:
            profile = reg.get(language)
        else:
            raise
    mapping = extract_source_mapping(result, profile=profile)
    authority = authority_for_adapter_result(profile, result)
    return profile, result, mapping, authority


__all__ = [
    "CANONICAL_LANGUAGES",
    "FRONTEND_PROFILE_SCHEMA_VERSION",
    "FRONTEND_REGISTRY_SCHEMA_VERSION",
    "SOURCE_FRONTEND_REGISTRY_INTERFACE",
    "SOURCE_FRONTEND_SEMANTIC_PROFILE_INTERFACE",
    "ConcurrencySemantics",
    "CoverageStatus",
    "DuplicateFrontendError",
    "ExceptionSemantics",
    "FrontendMaturity",
    "FrontendRegistry",
    "FrontendRegistryError",
    "MemorySemantics",
    "NumericSemantics",
    "ParserFidelity",
    "SemanticModelingLevel",
    "SourceFrontendSemanticProfile",
    "SourceMappingSnapshot",
    "SupportedFragmentCoverage",
    "UnknownFrontendError",
    "adapt_with_profile",
    "authority_for_adapter_result",
    "default_frontend_registry",
    "extract_source_mapping",
    "get_frontend_profile",
    "list_frontend_profiles",
    "normalize_language_id",
    "source_mapping_survives_adapter",
]
