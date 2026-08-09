"""Common frontend and profile descriptor contract (LFP2-010).

Interfaces:

* ``LogicFrontendDescriptor@1`` — notation/profile/features, parse modes,
  resource limits, recovery policy, printer guarantees, typed shared artifact
  outputs, stable diagnostics, unsupported behavior, and feature-scoped
  fixtures
* ``SharedFrontendConformance@1`` — fail-closed registration gate; a frontend
  cannot register without shared artifact output, declared limits, stable
  diagnostics, and feature-scoped fixtures

Notation modules consume this contract without redefining core artifacts.
Downstream frontends (SMT-LIB2, TPTP, rules, protocol, …) publish descriptors
here before binding implementations into a parser registry.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.families.namespaces import (
    LogicIdentity,
    NamespaceKind,
)
from ipfs_datasets_py.logic.syntax_core.artifacts_v2 import (
    ELABORATION_ARTIFACT_V2_INTERFACE,
    PARSE_ARTIFACT_V2_INTERFACE,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    MAX_COLLECTION_ITEMS,
    MAX_STRING_CHARS,
    ParseLimits,
    ParseMode,
    SyntaxContractError,
    _freeze_mapping,
    _record_id,
    _require_mapping,
    _require_sequence,
    _text,
    _thaw_mapping,
    require_namespace_identity,
)
from ipfs_datasets_py.logic.syntax_core.registry import (
    LogicParserDescriptor,
    ParserKey,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

LOGIC_FRONTEND_DESCRIPTOR_INTERFACE: Final = "LogicFrontendDescriptor@1"
SHARED_FRONTEND_CONFORMANCE_INTERFACE: Final = "SharedFrontendConformance@1"

LOGIC_FRONTEND_DESCRIPTOR_SCHEMA_VERSION: Final = "logic-frontend-descriptor/v1"
SHARED_FRONTEND_CONFORMANCE_SCHEMA_VERSION: Final = "shared-frontend-conformance/v1"
FRONTEND_LIMITS_SCHEMA_VERSION: Final = "frontend-limits/v1"
FRONTEND_FIXTURE_SCHEMA_VERSION: Final = "frontend-fixture/v1"
FRONTEND_PRINTER_SCHEMA_VERSION: Final = "frontend-printer/v1"
FRONTEND_ARTIFACT_OUTPUT_SCHEMA_VERSION: Final = "frontend-artifact-output/v1"
FRONTEND_CONTRACT_MODULE_VERSION: Final = "1.0.0"

FRONTEND_CONTRACT_TASK_ID: Final = "LFP2-010"
FRONTEND_CONTRACT_GOAL_ID: Final = "LFP2-G030"

# Shared artifact interfaces every controlled frontend must declare.
REQUIRED_PARSE_ARTIFACT_INTERFACE: Final = PARSE_ARTIFACT_V2_INTERFACE
REQUIRED_ELABORATION_ARTIFACT_INTERFACE: Final = ELABORATION_ARTIFACT_V2_INTERFACE

_FEATURE_RE: Final = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){0,7}$")
_DIAGNOSTIC_CODE_RE: Final = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,7}$"
)
_UNSUPPORTED_NODE_RE: Final = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){0,7}$"
)

# Baseline features every controlled frontend must declare.
REQUIRED_BASELINE_FEATURES: Final[frozenset[str]] = frozenset({"parse"})

# Fixture kinds every declared feature must cover at least once (feature-scoped).
REQUIRED_FIXTURE_KINDS_FOR_PARSE: Final[frozenset[str]] = frozenset(
    {
        "positive",
        "negative",
        "round_trip",
        "resource",
    }
)
REQUIRED_FIXTURE_KINDS_FOR_ELABORATE: Final[frozenset[str]] = frozenset(
    {
        "positive",
        "negative",
    }
)
REQUIRED_FIXTURE_KINDS_FOR_PRINT: Final[frozenset[str]] = frozenset(
    {
        "round_trip",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FrontendContractError(SyntaxContractError):
    """Raised when a frontend descriptor or conformance record is malformed."""


class FrontendAdmissionError(FrontendContractError):
    """Raised when a frontend fails the shared conformance registration gate."""


class DuplicateFrontendError(FrontendAdmissionError):
    """Raised when a frontend descriptor id or exact key collides."""


class MissingArtifactOutputError(FrontendAdmissionError):
    """Raised when shared ParseArtifact@2 / ElaborationArtifact@2 output is absent."""


class MissingLimitsError(FrontendAdmissionError):
    """Raised when declared resource limits are absent or unbounded."""


class MissingDiagnosticsError(FrontendAdmissionError):
    """Raised when stable namespaced diagnostics are absent or malformed."""


class MissingFeatureFixturesError(FrontendAdmissionError):
    """Raised when feature-scoped fixtures are missing required coverage."""


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


class FrontendFeature(StrEnum):
    """Closed baseline feature identifiers for controlled frontends."""

    PARSE = "parse"
    PRINT = "print"
    ELABORATE = "elaborate"
    RECOVER = "recover"
    SOURCE_MAP = "source_map"
    TYPECHECK = "typecheck"


class RecoveryPolicy(StrEnum):
    """How the frontend behaves under parse recovery."""

    NONE = "none"
    BOUNDED = "bounded"
    FULL = "full"


class PrinterGuarantee(StrEnum):
    """Deterministic printer guarantees offered by a frontend."""

    NONE = "none"
    LEXICAL = "lexical"
    SEMANTIC = "semantic"
    EXACT_SOURCE = "exact_source"


class UnsupportedBehavior(StrEnum):
    """Fail-closed policy when an unsupported construct is encountered."""

    REJECT = "reject"
    REJECT_WITH_DIAGNOSTIC = "reject_with_diagnostic"
    RECOVER_AND_DIAGNOSE = "recover_and_diagnose"


class FixtureKind(StrEnum):
    """Closed vocabulary of feature-scoped frontend fixture kinds."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    AMBIGUOUS = "ambiguous"
    ADVERSARIAL = "adversarial"
    ROUND_TRIP = "round_trip"
    RESOURCE = "resource"
    METAMORPHIC = "metamorphic"


class ExpectedDisposition(StrEnum):
    """Expected disposition for a feature-scoped fixture."""

    ACCEPT = "accept"
    REJECT = "reject"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"
    RECOVERED = "recovered"
    ERROR = "error"


class ArtifactRole(StrEnum):
    """Role of a declared shared artifact output."""

    PARSE = "parse"
    ELABORATION = "elaboration"


# ---------------------------------------------------------------------------
# Primitive validators
# ---------------------------------------------------------------------------


def _feature_id(value: object, field_name: str = "feature") -> str:
    text = _text(value, field_name, maximum=128)
    if not _FEATURE_RE.fullmatch(text):
        raise FrontendContractError(
            f"{field_name} must be a lowercase feature id; got {text!r}"
        )
    return text


def _feature_tuple(value: object, field_name: str) -> tuple[str, ...]:
    items = tuple(
        _feature_id(item, f"{field_name} item")
        for item in _require_sequence(value, field_name)
    )
    if len(items) > MAX_COLLECTION_ITEMS:
        raise FrontendContractError(f"{field_name} exceeds collection ceiling")
    if len(items) != len(set(items)):
        raise FrontendContractError(f"{field_name} must not contain duplicates")
    return tuple(sorted(items))


def _diagnostic_code(value: object, field_name: str = "diagnostic_code") -> str:
    text = _text(value, field_name, maximum=128)
    if not _DIAGNOSTIC_CODE_RE.fullmatch(text):
        raise FrontendContractError(
            f"{field_name} must be a stable lowercase namespaced code; got {text!r}"
        )
    return text


def _diagnostic_codes(value: object, field_name: str) -> tuple[str, ...]:
    items = tuple(
        _diagnostic_code(item, f"{field_name} item")
        for item in _require_sequence(value, field_name)
    )
    if len(items) > MAX_COLLECTION_ITEMS:
        raise FrontendContractError(f"{field_name} exceeds collection ceiling")
    if len(items) != len(set(items)):
        raise FrontendContractError(f"{field_name} must not contain duplicates")
    return tuple(sorted(items))


def _unsupported_nodes(value: object, field_name: str) -> tuple[str, ...]:
    items = tuple(
        _text(item, f"{field_name} item", maximum=128)
        for item in _require_sequence(value, field_name)
    )
    ordered: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not _UNSUPPORTED_NODE_RE.fullmatch(item):
            raise FrontendContractError(
                f"{field_name} item must be a dotted construct id; got {item!r}"
            )
        if item in seen:
            raise FrontendContractError(f"{field_name} values must be unique")
        seen.add(item)
        ordered.append(item)
    if len(ordered) > MAX_COLLECTION_ITEMS:
        raise FrontendContractError(f"{field_name} exceeds collection ceiling")
    return tuple(sorted(ordered))


def _enum_value(enum_cls: type[StrEnum], value: object, field_name: str) -> StrEnum:
    if isinstance(value, enum_cls):
        return value
    text = _text(value, field_name, maximum=64)
    try:
        return enum_cls(text)
    except ValueError as error:
        allowed = ", ".join(sorted(member.value for member in enum_cls))
        raise FrontendContractError(
            f"{field_name} must be one of {{{allowed}}}; got {text!r}"
        ) from error


def _parse_modes(value: object, field_name: str = "parse_modes") -> tuple[ParseMode, ...]:
    raw = _require_sequence(value, field_name)
    modes: list[ParseMode] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, ParseMode):
            mode = item
        else:
            try:
                mode = ParseMode(_text(item, f"{field_name} item", maximum=32))
            except ValueError as error:
                raise FrontendContractError(
                    f"{field_name} item must be a ParseMode value; got {item!r}"
                ) from error
        if mode.value in seen:
            raise FrontendContractError(f"{field_name} must not contain duplicates")
        seen.add(mode.value)
        modes.append(mode)
    if not modes:
        raise FrontendContractError(f"{field_name} must declare at least one parse mode")
    if len(modes) > MAX_COLLECTION_ITEMS:
        raise FrontendContractError(f"{field_name} exceeds collection ceiling")
    return tuple(sorted(modes, key=lambda mode: mode.value))


# ---------------------------------------------------------------------------
# Nested contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FrontendLimits:
    """Declared finite resource bounds for one frontend profile.

    Wraps :class:`ParseLimits` so every registered frontend must publish an
    explicit, finite bound surface.  Unbounded or omitted limits fail closed.
    """

    parse_limits: ParseLimits = field(default_factory=ParseLimits)
    max_output_bytes: int = 1_048_576
    max_print_depth: int = 4_096
    schema_version: str = FRONTEND_LIMITS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.parse_limits, ParseLimits):
            object.__setattr__(
                self,
                "parse_limits",
                ParseLimits.from_dict(
                    _require_mapping(self.parse_limits, "parse_limits")
                ),
            )
        # Re-validate through ParseLimits construction so None/0/oversize fail.
        bounds = self.parse_limits
        if (
            bounds.max_input_bytes <= 0
            or bounds.max_tokens <= 0
            or bounds.max_depth <= 0
            or bounds.max_diagnostics <= 0
            or bounds.max_time_ms <= 0
            or bounds.max_memory_bytes <= 0
        ):
            raise MissingLimitsError(
                "FrontendLimits requires finite positive parse bounds"
            )
        if (
            isinstance(self.max_output_bytes, bool)
            or not isinstance(self.max_output_bytes, int)
            or self.max_output_bytes <= 0
        ):
            raise MissingLimitsError(
                "max_output_bytes must be a positive finite bound"
            )
        if (
            isinstance(self.max_print_depth, bool)
            or not isinstance(self.max_print_depth, int)
            or self.max_print_depth <= 0
        ):
            raise MissingLimitsError(
                "max_print_depth must be a positive finite bound"
            )
        if self.schema_version != FRONTEND_LIMITS_SCHEMA_VERSION:
            raise FrontendContractError(
                f"unsupported FrontendLimits schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_output_bytes": self.max_output_bytes,
            "max_print_depth": self.max_print_depth,
            "parse_limits": self.parse_limits.to_dict(),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FrontendLimits":
        payload = _require_mapping(data, "FrontendLimits")
        return cls(
            parse_limits=ParseLimits.from_dict(
                _require_mapping(payload.get("parse_limits") or {}, "parse_limits")
            ),
            max_output_bytes=int(payload.get("max_output_bytes") or 1_048_576),
            max_print_depth=int(payload.get("max_print_depth") or 4_096),
            schema_version=str(
                payload.get("schema_version") or FRONTEND_LIMITS_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class PrinterContract:
    """Printer guarantees and feature binding for a frontend."""

    guarantee: PrinterGuarantee | str = PrinterGuarantee.SEMANTIC
    features: tuple[str, ...] = ("print",)
    deterministic: bool = True
    schema_version: str = FRONTEND_PRINTER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "guarantee",
            _enum_value(PrinterGuarantee, self.guarantee, "guarantee"),
        )
        object.__setattr__(self, "features", _feature_tuple(self.features, "features"))
        if not isinstance(self.deterministic, bool):
            raise FrontendContractError("deterministic must be a bool")
        if self.schema_version != FRONTEND_PRINTER_SCHEMA_VERSION:
            raise FrontendContractError(
                f"unsupported PrinterContract schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "deterministic": self.deterministic,
            "features": list(self.features),
            "guarantee": (
                self.guarantee.value
                if isinstance(self.guarantee, PrinterGuarantee)
                else str(self.guarantee)
            ),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PrinterContract":
        payload = _require_mapping(data, "PrinterContract")
        return cls(
            guarantee=str(payload.get("guarantee") or PrinterGuarantee.SEMANTIC.value),
            features=tuple(payload.get("features") or ("print",)),
            deterministic=bool(payload.get("deterministic", True)),
            schema_version=str(
                payload.get("schema_version") or FRONTEND_PRINTER_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ArtifactOutputContract:
    """Declared shared typed artifact output for a frontend pipeline stage."""

    role: ArtifactRole | str
    interface: str
    schema_version: str = FRONTEND_ARTIFACT_OUTPUT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "role", _enum_value(ArtifactRole, self.role, "role")
        )
        interface = _text(self.interface, "interface", maximum=128)
        role = self.role if isinstance(self.role, ArtifactRole) else ArtifactRole(str(self.role))
        if role is ArtifactRole.PARSE and interface != REQUIRED_PARSE_ARTIFACT_INTERFACE:
            raise MissingArtifactOutputError(
                f"parse artifact output must declare {REQUIRED_PARSE_ARTIFACT_INTERFACE}; "
                f"got {interface!r}"
            )
        if (
            role is ArtifactRole.ELABORATION
            and interface != REQUIRED_ELABORATION_ARTIFACT_INTERFACE
        ):
            raise MissingArtifactOutputError(
                f"elaboration artifact output must declare "
                f"{REQUIRED_ELABORATION_ARTIFACT_INTERFACE}; got {interface!r}"
            )
        object.__setattr__(self, "interface", interface)
        if self.schema_version != FRONTEND_ARTIFACT_OUTPUT_SCHEMA_VERSION:
            raise FrontendContractError(
                f"unsupported ArtifactOutputContract schema_version "
                f"{self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface": self.interface,
            "role": (
                self.role.value
                if isinstance(self.role, ArtifactRole)
                else str(self.role)
            ),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArtifactOutputContract":
        payload = _require_mapping(data, "ArtifactOutputContract")
        return cls(
            role=str(payload.get("role") or ""),
            interface=str(payload.get("interface") or ""),
            schema_version=str(
                payload.get("schema_version")
                or FRONTEND_ARTIFACT_OUTPUT_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class FeatureScopedFixture:
    """One compact feature-scoped conformance fixture recipe.

    Fixtures are descriptor-level recipes (ids, kinds, feature tags, expected
    disposition) rather than bulk golden dumps.  Downstream modules materialize
    payloads from these recipes under their own test trees.
    """

    fixture_id: str
    kind: FixtureKind | str
    features: tuple[str, ...]
    expected_disposition: ExpectedDisposition | str = ExpectedDisposition.ACCEPT
    description: str = ""
    schema_version: str = FRONTEND_FIXTURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "fixture_id", _record_id(self.fixture_id, "fixture_id")
        )
        object.__setattr__(
            self, "kind", _enum_value(FixtureKind, self.kind, "kind")
        )
        features = _feature_tuple(self.features, "features")
        if not features:
            raise MissingFeatureFixturesError(
                f"fixture {self.fixture_id!r} must declare at least one feature scope"
            )
        object.__setattr__(self, "features", features)
        object.__setattr__(
            self,
            "expected_disposition",
            _enum_value(
                ExpectedDisposition,
                self.expected_disposition,
                "expected_disposition",
            ),
        )
        if self.description:
            object.__setattr__(
                self,
                "description",
                _text(self.description, "description", maximum=MAX_STRING_CHARS),
            )
        else:
            object.__setattr__(self, "description", "")
        if self.schema_version != FRONTEND_FIXTURE_SCHEMA_VERSION:
            raise FrontendContractError(
                f"unsupported FeatureScopedFixture schema_version "
                f"{self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "expected_disposition": (
                self.expected_disposition.value
                if isinstance(self.expected_disposition, ExpectedDisposition)
                else str(self.expected_disposition)
            ),
            "features": list(self.features),
            "fixture_id": self.fixture_id,
            "kind": (
                self.kind.value if isinstance(self.kind, FixtureKind) else str(self.kind)
            ),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FeatureScopedFixture":
        payload = _require_mapping(data, "FeatureScopedFixture")
        return cls(
            fixture_id=str(payload.get("fixture_id") or ""),
            kind=str(payload.get("kind") or ""),
            features=tuple(payload.get("features") or ()),
            expected_disposition=str(
                payload.get("expected_disposition")
                or ExpectedDisposition.ACCEPT.value
            ),
            description=str(payload.get("description") or ""),
            schema_version=str(
                payload.get("schema_version") or FRONTEND_FIXTURE_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# LogicFrontendDescriptor@1
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LogicFrontendDescriptor:
    """Immutable common frontend / profile descriptor.

    Interface: ``LogicFrontendDescriptor@1``.

    Construction validates local shape.  Full admission (shared artifact
    output, limits, diagnostics, feature-scoped fixtures) is enforced by
    :class:`SharedFrontendConformance` at registration time.
    """

    descriptor_id: str
    key: ParserKey
    family_id: LogicIdentity | Mapping[str, Any] | str
    features: tuple[str, ...]
    parse_modes: tuple[ParseMode, ...] | Sequence[ParseMode | str]
    limits: FrontendLimits
    diagnostics: tuple[str, ...]
    artifact_outputs: tuple[ArtifactOutputContract, ...] | Sequence[
        ArtifactOutputContract | Mapping[str, Any]
    ]
    fixtures: tuple[FeatureScopedFixture, ...] | Sequence[
        FeatureScopedFixture | Mapping[str, Any]
    ]
    recovery: RecoveryPolicy | str = RecoveryPolicy.NONE
    printer: PrinterContract | Mapping[str, Any] | None = None
    unsupported_behavior: UnsupportedBehavior | str = (
        UnsupportedBehavior.REJECT_WITH_DIAGNOSTIC
    )
    unsupported_nodes: tuple[str, ...] = ()
    implementation: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LOGIC_FRONTEND_DESCRIPTOR_SCHEMA_VERSION

    interface: ClassVar[str] = LOGIC_FRONTEND_DESCRIPTOR_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "descriptor_id", _record_id(self.descriptor_id, "descriptor_id")
        )
        if not isinstance(self.key, ParserKey):
            if isinstance(self.key, Mapping):
                object.__setattr__(self, "key", ParserKey.from_dict(self.key))
            else:
                raise FrontendContractError(
                    "LogicFrontendDescriptor.key must be a ParserKey"
                )
        object.__setattr__(
            self,
            "family_id",
            require_namespace_identity(
                self.family_id, NamespaceKind.FAMILY, "family_id"
            ),
        )
        features = _feature_tuple(self.features, "features")
        if not features:
            raise FrontendContractError("features must declare at least one feature")
        object.__setattr__(self, "features", features)
        object.__setattr__(self, "parse_modes", _parse_modes(self.parse_modes))

        if not isinstance(self.limits, FrontendLimits):
            if self.limits is None:
                raise MissingLimitsError(
                    "LogicFrontendDescriptor.limits is required; unbounded "
                    "frontends are rejected"
                )
            object.__setattr__(
                self,
                "limits",
                FrontendLimits.from_dict(_require_mapping(self.limits, "limits")),
            )

        object.__setattr__(
            self, "diagnostics", _diagnostic_codes(self.diagnostics, "diagnostics")
        )

        outputs = tuple(
            item
            if isinstance(item, ArtifactOutputContract)
            else ArtifactOutputContract.from_dict(
                _require_mapping(item, "artifact_outputs item")
            )
            for item in _require_sequence(self.artifact_outputs, "artifact_outputs")
        )
        if len(outputs) > MAX_COLLECTION_ITEMS:
            raise FrontendContractError("artifact_outputs exceeds collection ceiling")
        roles = [
            item.role.value if isinstance(item.role, ArtifactRole) else str(item.role)
            for item in outputs
        ]
        if len(roles) != len(set(roles)):
            raise FrontendContractError("artifact_outputs roles must be unique")
        object.__setattr__(self, "artifact_outputs", outputs)

        fixtures = tuple(
            item
            if isinstance(item, FeatureScopedFixture)
            else FeatureScopedFixture.from_dict(
                _require_mapping(item, "fixtures item")
            )
            for item in _require_sequence(self.fixtures, "fixtures")
        )
        if len(fixtures) > MAX_COLLECTION_ITEMS:
            raise FrontendContractError("fixtures exceeds collection ceiling")
        fixture_ids = [item.fixture_id for item in fixtures]
        if len(fixture_ids) != len(set(fixture_ids)):
            raise FrontendContractError("fixtures must have unique fixture_id values")
        object.__setattr__(self, "fixtures", fixtures)

        object.__setattr__(
            self, "recovery", _enum_value(RecoveryPolicy, self.recovery, "recovery")
        )

        if self.printer is None:
            if FrontendFeature.PRINT.value in features:
                object.__setattr__(self, "printer", PrinterContract())
            else:
                object.__setattr__(
                    self,
                    "printer",
                    PrinterContract(
                        guarantee=PrinterGuarantee.NONE,
                        features=(),
                        deterministic=True,
                    ),
                )
        elif not isinstance(self.printer, PrinterContract):
            object.__setattr__(
                self,
                "printer",
                PrinterContract.from_dict(_require_mapping(self.printer, "printer")),
            )

        object.__setattr__(
            self,
            "unsupported_behavior",
            _enum_value(
                UnsupportedBehavior,
                self.unsupported_behavior,
                "unsupported_behavior",
            ),
        )
        object.__setattr__(
            self,
            "unsupported_nodes",
            _unsupported_nodes(self.unsupported_nodes, "unsupported_nodes"),
        )
        object.__setattr__(
            self,
            "implementation",
            _text(self.implementation, "implementation", maximum=256)
            if self.implementation
            else "",
        )
        object.__setattr__(
            self, "metadata", _freeze_mapping(self.metadata, "metadata")
        )
        if self.schema_version != LOGIC_FRONTEND_DESCRIPTOR_SCHEMA_VERSION:
            raise FrontendContractError(
                f"unsupported LogicFrontendDescriptor schema_version "
                f"{self.schema_version!r}"
            )

        # Recovery mode consistency.
        recovery = (
            self.recovery
            if isinstance(self.recovery, RecoveryPolicy)
            else RecoveryPolicy(str(self.recovery))
        )
        mode_values = {
            mode.value if isinstance(mode, ParseMode) else str(mode)
            for mode in self.parse_modes
        }
        if recovery is not RecoveryPolicy.NONE and ParseMode.RECOVERY.value not in mode_values:
            raise FrontendContractError(
                "recovery policy other than 'none' requires parse_modes to include recovery"
            )
        if (
            ParseMode.RECOVERY.value in mode_values
            and recovery is RecoveryPolicy.NONE
            and FrontendFeature.RECOVER.value not in features
        ):
            # Recovery mode without a recovery policy or feature is contradictory.
            raise FrontendContractError(
                "parse_modes includes recovery but recovery policy is none and "
                "features omits recover"
            )

    @property
    def notation_id(self) -> str:
        return self.key.notation_id

    @property
    def notation_version(self) -> str:
        return self.key.notation_version

    @property
    def semantic_profile_id(self) -> str:
        return self.key.semantic_profile_id

    def has_feature(self, feature: str | FrontendFeature) -> bool:
        value = feature.value if isinstance(feature, FrontendFeature) else feature
        return value in self.features

    def artifact_interfaces(self) -> frozenset[str]:
        return frozenset(item.interface for item in self.artifact_outputs)

    def to_parser_descriptor(self) -> LogicParserDescriptor:
        """Project to the inert :class:`LogicParserDescriptor` registration record."""

        return LogicParserDescriptor(
            descriptor_id=self.descriptor_id,
            key=self.key,
            family_id=self.family_id,
            features=self.features,
            implementation=self.implementation,
            metadata={
                "frontend_interface": self.interface,
                "frontend_schema_version": self.schema_version,
                "recovery": (
                    self.recovery.value
                    if isinstance(self.recovery, RecoveryPolicy)
                    else str(self.recovery)
                ),
                "unsupported_behavior": (
                    self.unsupported_behavior.value
                    if isinstance(self.unsupported_behavior, UnsupportedBehavior)
                    else str(self.unsupported_behavior)
                ),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        family = self.family_id
        return {
            "artifact_outputs": [item.to_dict() for item in self.artifact_outputs],
            "descriptor_id": self.descriptor_id,
            "diagnostics": list(self.diagnostics),
            "family_id": family.to_dict() if isinstance(family, LogicIdentity) else family,
            "features": list(self.features),
            "fixtures": [item.to_dict() for item in self.fixtures],
            "implementation": self.implementation,
            "interface": self.interface,
            "key": self.key.to_dict(),
            "limits": self.limits.to_dict(),
            "metadata": _thaw_mapping(self.metadata),
            "parse_modes": [
                mode.value if isinstance(mode, ParseMode) else str(mode)
                for mode in self.parse_modes
            ],
            "printer": self.printer.to_dict() if self.printer is not None else None,
            "recovery": (
                self.recovery.value
                if isinstance(self.recovery, RecoveryPolicy)
                else str(self.recovery)
            ),
            "schema_version": self.schema_version,
            "unsupported_behavior": (
                self.unsupported_behavior.value
                if isinstance(self.unsupported_behavior, UnsupportedBehavior)
                else str(self.unsupported_behavior)
            ),
            "unsupported_nodes": list(self.unsupported_nodes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogicFrontendDescriptor":
        payload = _require_mapping(data, "LogicFrontendDescriptor")
        interface = payload.get("interface")
        if interface is not None and interface != LOGIC_FRONTEND_DESCRIPTOR_INTERFACE:
            raise FrontendContractError(
                f"unsupported LogicFrontendDescriptor interface {interface!r}"
            )
        printer_raw = payload.get("printer")
        return cls(
            descriptor_id=str(payload.get("descriptor_id") or ""),
            key=ParserKey.from_dict(_require_mapping(payload.get("key"), "key")),
            family_id=payload.get("family_id") or "",
            features=tuple(payload.get("features") or ()),
            parse_modes=tuple(payload.get("parse_modes") or ()),
            limits=FrontendLimits.from_dict(
                _require_mapping(payload.get("limits") or {}, "limits")
            ),
            diagnostics=tuple(payload.get("diagnostics") or ()),
            artifact_outputs=tuple(payload.get("artifact_outputs") or ()),
            fixtures=tuple(payload.get("fixtures") or ()),
            recovery=str(payload.get("recovery") or RecoveryPolicy.NONE.value),
            printer=(
                None
                if printer_raw is None
                else PrinterContract.from_dict(
                    _require_mapping(printer_raw, "printer")
                )
            ),
            unsupported_behavior=str(
                payload.get("unsupported_behavior")
                or UnsupportedBehavior.REJECT_WITH_DIAGNOSTIC.value
            ),
            unsupported_nodes=tuple(payload.get("unsupported_nodes") or ()),
            implementation=str(payload.get("implementation") or ""),
            metadata=_require_mapping(payload.get("metadata") or {}, "metadata"),
            schema_version=str(
                payload.get("schema_version")
                or LOGIC_FRONTEND_DESCRIPTOR_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Admission helpers
# ---------------------------------------------------------------------------


def _require_shared_artifact_outputs(descriptor: LogicFrontendDescriptor) -> None:
    interfaces = descriptor.artifact_interfaces()
    if REQUIRED_PARSE_ARTIFACT_INTERFACE not in interfaces:
        raise MissingArtifactOutputError(
            f"frontend {descriptor.descriptor_id!r} cannot register without "
            f"shared artifact output {REQUIRED_PARSE_ARTIFACT_INTERFACE}"
        )
    if (
        FrontendFeature.ELABORATE.value in descriptor.features
        and REQUIRED_ELABORATION_ARTIFACT_INTERFACE not in interfaces
    ):
        raise MissingArtifactOutputError(
            f"frontend {descriptor.descriptor_id!r} declares elaborate but "
            f"omits shared artifact output {REQUIRED_ELABORATION_ARTIFACT_INTERFACE}"
        )


def _require_declared_limits(descriptor: LogicFrontendDescriptor) -> None:
    if descriptor.limits is None:
        raise MissingLimitsError(
            f"frontend {descriptor.descriptor_id!r} cannot register without "
            "declared limits"
        )
    # FrontendLimits construction already rejects non-positive bounds; re-check
    # the nested parse surface for explicitness.
    bounds = descriptor.limits.parse_limits
    required_fields = (
        bounds.max_input_bytes,
        bounds.max_tokens,
        bounds.max_depth,
        bounds.max_diagnostics,
        bounds.max_time_ms,
        bounds.max_memory_bytes,
        descriptor.limits.max_output_bytes,
        descriptor.limits.max_print_depth,
    )
    if any(value is None or value <= 0 for value in required_fields):
        raise MissingLimitsError(
            f"frontend {descriptor.descriptor_id!r} cannot register without "
            "finite declared limits"
        )


def _require_stable_diagnostics(descriptor: LogicFrontendDescriptor) -> None:
    if not descriptor.diagnostics:
        raise MissingDiagnosticsError(
            f"frontend {descriptor.descriptor_id!r} cannot register without "
            "stable diagnostics"
        )
    for code in descriptor.diagnostics:
        if not _DIAGNOSTIC_CODE_RE.fullmatch(code):
            raise MissingDiagnosticsError(
                f"frontend {descriptor.descriptor_id!r} diagnostic {code!r} "
                "is not a stable namespaced code"
            )


def _fixture_kinds_for_feature(
    fixtures: Sequence[FeatureScopedFixture],
    feature: str,
) -> frozenset[str]:
    kinds: set[str] = set()
    for fixture in fixtures:
        if feature in fixture.features:
            kind = (
                fixture.kind.value
                if isinstance(fixture.kind, FixtureKind)
                else str(fixture.kind)
            )
            kinds.add(kind)
    return frozenset(kinds)


def _require_feature_scoped_fixtures(descriptor: LogicFrontendDescriptor) -> None:
    if not descriptor.fixtures:
        raise MissingFeatureFixturesError(
            f"frontend {descriptor.descriptor_id!r} cannot register without "
            "feature-scoped fixtures"
        )

    feature_set = set(descriptor.features)
    for fixture in descriptor.fixtures:
        unknown = set(fixture.features) - feature_set
        if unknown:
            raise MissingFeatureFixturesError(
                f"frontend {descriptor.descriptor_id!r} fixture "
                f"{fixture.fixture_id!r} scopes unknown features "
                f"{sorted(unknown)!r}; fixtures must be feature-scoped to "
                "declared features"
            )

    # Every declared baseline feature must have at least one fixture.
    for feature in descriptor.features:
        kinds = _fixture_kinds_for_feature(descriptor.fixtures, feature)
        if not kinds:
            raise MissingFeatureFixturesError(
                f"frontend {descriptor.descriptor_id!r} declares feature "
                f"{feature!r} without any feature-scoped fixture"
            )

    if FrontendFeature.PARSE.value in descriptor.features:
        kinds = _fixture_kinds_for_feature(
            descriptor.fixtures, FrontendFeature.PARSE.value
        )
        missing = REQUIRED_FIXTURE_KINDS_FOR_PARSE - kinds
        if missing:
            raise MissingFeatureFixturesError(
                f"frontend {descriptor.descriptor_id!r} parse feature missing "
                f"required fixture kinds {sorted(missing)!r}"
            )

    if FrontendFeature.ELABORATE.value in descriptor.features:
        kinds = _fixture_kinds_for_feature(
            descriptor.fixtures, FrontendFeature.ELABORATE.value
        )
        missing = REQUIRED_FIXTURE_KINDS_FOR_ELABORATE - kinds
        if missing:
            raise MissingFeatureFixturesError(
                f"frontend {descriptor.descriptor_id!r} elaborate feature missing "
                f"required fixture kinds {sorted(missing)!r}"
            )

    if FrontendFeature.PRINT.value in descriptor.features:
        kinds = _fixture_kinds_for_feature(
            descriptor.fixtures, FrontendFeature.PRINT.value
        )
        missing = REQUIRED_FIXTURE_KINDS_FOR_PRINT - kinds
        if missing:
            raise MissingFeatureFixturesError(
                f"frontend {descriptor.descriptor_id!r} print feature missing "
                f"required fixture kinds {sorted(missing)!r}"
            )


def validate_frontend_descriptor(descriptor: LogicFrontendDescriptor) -> None:
    """Fail-closed admission checks for a frontend descriptor.

    Enforces the LFP2-010 acceptance gate:

    * shared artifact output (``ParseArtifact@2``, and ``ElaborationArtifact@2``
      when elaborate is declared)
    * declared finite limits
    * stable namespaced diagnostics
    * feature-scoped fixtures with required kind coverage
    """

    if not isinstance(descriptor, LogicFrontendDescriptor):
        raise FrontendContractError(
            "validate_frontend_descriptor requires a LogicFrontendDescriptor"
        )
    missing_baseline = REQUIRED_BASELINE_FEATURES - set(descriptor.features)
    if missing_baseline:
        raise FrontendAdmissionError(
            f"frontend {descriptor.descriptor_id!r} missing required baseline "
            f"features {sorted(missing_baseline)!r}"
        )
    _require_shared_artifact_outputs(descriptor)
    _require_declared_limits(descriptor)
    _require_stable_diagnostics(descriptor)
    _require_feature_scoped_fixtures(descriptor)


# ---------------------------------------------------------------------------
# SharedFrontendConformance@1
# ---------------------------------------------------------------------------


class SharedFrontendConformance:
    """Fail-closed registry for common frontend descriptors.

    Interface: ``SharedFrontendConformance@1``.

    Registration rejects any frontend that omits shared artifact output,
    declared limits, stable diagnostics, or feature-scoped fixtures.  Exact
    ``ParserKey`` and ``descriptor_id`` collisions are rejected.
    """

    interface: ClassVar[str] = SHARED_FRONTEND_CONFORMANCE_INTERFACE
    schema_version: ClassVar[str] = SHARED_FRONTEND_CONFORMANCE_SCHEMA_VERSION

    def __init__(
        self,
        *,
        conformance_id: str = "conformance:shared-frontends",
    ) -> None:
        self._conformance_id = _record_id(conformance_id, "conformance_id")
        self._entries: dict[str, LogicFrontendDescriptor] = {}
        self._by_key: dict[tuple[str, str, str], str] = {}

    @property
    def conformance_id(self) -> str:
        return self._conformance_id

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, descriptor_id: object) -> bool:
        return isinstance(descriptor_id, str) and descriptor_id in self._entries

    def __iter__(self) -> Iterator[LogicFrontendDescriptor]:
        return iter(self.descriptors())

    def descriptors(self) -> tuple[LogicFrontendDescriptor, ...]:
        return tuple(
            self._entries[key]
            for key in sorted(self._entries)
        )

    def keys(self) -> tuple[ParserKey, ...]:
        return tuple(item.key for item in self.descriptors())

    def get(self, descriptor_id: str) -> LogicFrontendDescriptor:
        try:
            return self._entries[descriptor_id]
        except KeyError as error:
            raise FrontendAdmissionError(
                f"no frontend registered with descriptor_id {descriptor_id!r}"
            ) from error

    def resolve(
        self,
        notation_id: str,
        notation_version: str,
        semantic_profile_id: str,
    ) -> LogicFrontendDescriptor:
        key = ParserKey.from_parts(notation_id, notation_version, semantic_profile_id)
        descriptor_id = self._by_key.get(key.as_tuple)
        if descriptor_id is None:
            raise FrontendAdmissionError(
                f"no frontend registered for exact key {key.to_dict()!r}"
            )
        return self._entries[descriptor_id]

    def register(
        self,
        descriptor: LogicFrontendDescriptor | Mapping[str, Any],
        *,
        replace: bool = False,
    ) -> LogicFrontendDescriptor:
        """Admit *descriptor* only when the shared conformance gate passes."""

        if not isinstance(descriptor, LogicFrontendDescriptor):
            descriptor = LogicFrontendDescriptor.from_dict(
                _require_mapping(descriptor, "descriptor")
            )
        validate_frontend_descriptor(descriptor)

        key_tuple = descriptor.key.as_tuple
        if descriptor.descriptor_id in self._entries and not replace:
            raise DuplicateFrontendError(
                f"descriptor_id {descriptor.descriptor_id!r} is already registered"
            )
        existing_id = self._by_key.get(key_tuple)
        if existing_id is not None and existing_id != descriptor.descriptor_id and not replace:
            raise DuplicateFrontendError(
                f"parser key {descriptor.key.to_dict()!r} collides with "
                f"existing descriptor {existing_id!r}"
            )
        if replace and existing_id is not None and existing_id != descriptor.descriptor_id:
            del self._entries[existing_id]
        if replace and descriptor.descriptor_id in self._entries:
            old = self._entries[descriptor.descriptor_id]
            old_key = old.key.as_tuple
            if old_key in self._by_key and self._by_key[old_key] == descriptor.descriptor_id:
                del self._by_key[old_key]

        self._entries[descriptor.descriptor_id] = descriptor
        self._by_key[key_tuple] = descriptor.descriptor_id
        return descriptor

    def unregister(self, descriptor_id: str) -> None:
        if descriptor_id not in self._entries:
            raise FrontendAdmissionError(
                f"no frontend registered with descriptor_id {descriptor_id!r}"
            )
        descriptor = self._entries.pop(descriptor_id)
        key_tuple = descriptor.key.as_tuple
        if self._by_key.get(key_tuple) == descriptor_id:
            del self._by_key[key_tuple]

    def to_dict(self) -> dict[str, Any]:
        return {
            "conformance_id": self._conformance_id,
            "descriptors": [item.to_dict() for item in self.descriptors()],
            "interface": self.interface,
            "module_version": FRONTEND_CONTRACT_MODULE_VERSION,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SharedFrontendConformance":
        payload = _require_mapping(data, "SharedFrontendConformance")
        interface = payload.get("interface")
        if (
            interface is not None
            and interface != SHARED_FRONTEND_CONFORMANCE_INTERFACE
        ):
            raise FrontendContractError(
                f"unsupported SharedFrontendConformance interface {interface!r}"
            )
        registry = cls(
            conformance_id=str(
                payload.get("conformance_id") or "conformance:shared-frontends"
            )
        )
        for item in _require_sequence(
            payload.get("descriptors") or (), "descriptors"
        ):
            registry.register(
                LogicFrontendDescriptor.from_dict(
                    _require_mapping(item, "descriptors item")
                )
            )
        return registry


def build_baseline_fixture_set(
    *,
    features: Sequence[str],
    prefix: str = "fx",
) -> tuple[FeatureScopedFixture, ...]:
    """Return a compact recipe set covering required kinds for *features*.

    Useful for tests and for frontends that need a minimal compliant fixture
    catalog without bulk golden dumps.
    """

    feature_set = set(_feature_tuple(features, "features"))
    fixtures: list[FeatureScopedFixture] = []

    def _add(
        suffix: str,
        kind: FixtureKind,
        scoped: Sequence[str],
        disposition: ExpectedDisposition,
        description: str,
    ) -> None:
        scoped_features = tuple(item for item in scoped if item in feature_set)
        if not scoped_features:
            return
        fixtures.append(
            FeatureScopedFixture(
                fixture_id=f"{prefix}:{suffix}",
                kind=kind,
                features=scoped_features,
                expected_disposition=disposition,
                description=description,
            )
        )

    if FrontendFeature.PARSE.value in feature_set:
        _add(
            "parse-positive",
            FixtureKind.POSITIVE,
            (FrontendFeature.PARSE.value,),
            ExpectedDisposition.ACCEPT,
            "Accepted controlled source under declared profile.",
        )
        _add(
            "parse-negative",
            FixtureKind.NEGATIVE,
            (FrontendFeature.PARSE.value,),
            ExpectedDisposition.REJECT,
            "Rejected malformed or unsupported source with stable diagnostic.",
        )
        _add(
            "parse-round-trip",
            FixtureKind.ROUND_TRIP,
            (
                FrontendFeature.PARSE.value,
                FrontendFeature.PRINT.value,
            ),
            ExpectedDisposition.ACCEPT,
            "Parse/print/parse semantic identity for admitted constructs.",
        )
        _add(
            "parse-resource",
            FixtureKind.RESOURCE,
            (FrontendFeature.PARSE.value,),
            ExpectedDisposition.REJECT,
            "Bounded resource attack rejected under declared limits.",
        )

    if FrontendFeature.ELABORATE.value in feature_set:
        _add(
            "elaborate-positive",
            FixtureKind.POSITIVE,
            (FrontendFeature.ELABORATE.value, FrontendFeature.PARSE.value),
            ExpectedDisposition.ACCEPT,
            "Well-formed elaboration to TypedExpression / ElaborationArtifact@2.",
        )
        _add(
            "elaborate-negative",
            FixtureKind.NEGATIVE,
            (FrontendFeature.ELABORATE.value, FrontendFeature.PARSE.value),
            ExpectedDisposition.REJECT,
            "Ill-sorted or unbound construct fails elaboration with span.",
        )

    if (
        FrontendFeature.PRINT.value in feature_set
        and not any(
            FixtureKind.ROUND_TRIP.value
            == (
                item.kind.value
                if isinstance(item.kind, FixtureKind)
                else str(item.kind)
            )
            and FrontendFeature.PRINT.value in item.features
            for item in fixtures
        )
    ):
        _add(
            "print-round-trip",
            FixtureKind.ROUND_TRIP,
            (FrontendFeature.PRINT.value, FrontendFeature.PARSE.value),
            ExpectedDisposition.ACCEPT,
            "Printer semantic identity under declared guarantee.",
        )

    # Cover any remaining declared features with a positive fixture.
    covered = {feature for item in fixtures for feature in item.features}
    for feature in sorted(feature_set - covered):
        _add(
            f"{feature}-positive",
            FixtureKind.POSITIVE,
            (feature,),
            ExpectedDisposition.ACCEPT,
            f"Baseline positive fixture for feature {feature}.",
        )

    return tuple(fixtures)


def make_parse_artifact_output() -> ArtifactOutputContract:
    """Return the required ParseArtifact@2 output declaration."""

    return ArtifactOutputContract(
        role=ArtifactRole.PARSE,
        interface=REQUIRED_PARSE_ARTIFACT_INTERFACE,
    )


def make_elaboration_artifact_output() -> ArtifactOutputContract:
    """Return the required ElaborationArtifact@2 output declaration."""

    return ArtifactOutputContract(
        role=ArtifactRole.ELABORATION,
        interface=REQUIRED_ELABORATION_ARTIFACT_INTERFACE,
    )


# Stable alias for role enumeration consumers.
ARTIFACT_ROLE = ArtifactRole


__all__ = [
    "ARTIFACT_ROLE",
    "ArtifactOutputContract",
    "ArtifactRole",
    "DuplicateFrontendError",
    "ExpectedDisposition",
    "FRONTEND_CONTRACT_GOAL_ID",
    "FRONTEND_CONTRACT_MODULE_VERSION",
    "FRONTEND_CONTRACT_TASK_ID",
    "FeatureScopedFixture",
    "FixtureKind",
    "FrontendAdmissionError",
    "FrontendContractError",
    "FrontendFeature",
    "FrontendLimits",
    "LOGIC_FRONTEND_DESCRIPTOR_INTERFACE",
    "LOGIC_FRONTEND_DESCRIPTOR_SCHEMA_VERSION",
    "LogicFrontendDescriptor",
    "MissingArtifactOutputError",
    "MissingDiagnosticsError",
    "MissingFeatureFixturesError",
    "MissingLimitsError",
    "PrinterContract",
    "PrinterGuarantee",
    "REQUIRED_ELABORATION_ARTIFACT_INTERFACE",
    "REQUIRED_PARSE_ARTIFACT_INTERFACE",
    "RecoveryPolicy",
    "SHARED_FRONTEND_CONFORMANCE_INTERFACE",
    "SHARED_FRONTEND_CONFORMANCE_SCHEMA_VERSION",
    "SharedFrontendConformance",
    "UnsupportedBehavior",
    "build_baseline_fixture_set",
    "make_elaboration_artifact_output",
    "make_parse_artifact_output",
    "validate_frontend_descriptor",
]
