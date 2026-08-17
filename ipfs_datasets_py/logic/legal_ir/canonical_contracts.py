"""Immutable contracts for the measured canonical legal round trip.

This module is the shared boundary between the independently implemented
compiler and decompiler.  It intentionally contains no parser, model, solver,
or benchmark imports.  The selected implementation is evidence-bound, while
the wire contract remains open to legal vocabularies beyond the five frozen
benchmark cases.  The semantic IR deliberately keeps the measured
``{"rules": [...]}`` shape so its CID is directly comparable with benchmark L1
artifacts.  Source maps and provenance travel beside that source-withheld
semantic object in compiler results, never inside decompiler requests.

Every persistent identity is a CIDv1.  DAG-shaped records use canonical
DAG-JSON; source and reconstructed text use the raw codec.  Each self-addressed
record states its CID scope explicitly; notably, the parity policy hashes the
whole document with only ``policy_cid`` omitted.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from importlib import resources
from types import MappingProxyType
from typing import Final, Protocol, runtime_checkable

from ipfs_datasets_py.utils.cid_utils import (
    cid_for_bytes,
    cid_for_dag_json,
    validate_cid,
)


CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE: Final = "CanonicalStructuredTextCompiler@1"
CANONICAL_STRUCTURED_TEXT_DECOMPILER_INTERFACE: Final = "CanonicalStructuredTextDecompiler@1"
CANONICAL_ROUNDTRIP_CONTRACTS_INTERFACE: Final = "CanonicalRoundTripContracts@1"
CANONICAL_ROUNDTRIP_IR_INTERFACE: Final = "CanonicalRoundTripIR@1"
CANONICAL_ROUNDTRIP_IR_SCHEMA_VERSION: Final = "ipfs-datasets.canonical-roundtrip-ir.v1"
CANONICAL_ROUNDTRIP_PARITY_POLICY_INTERFACE: Final = "CanonicalRoundTripParityPolicy@1"
CANONICAL_ROUNDTRIP_PARITY_POLICY_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-canonical-parity-policy.v1"
)
CANONICAL_TYPED_BRIDGE_INTERFACE: Final = "CanonicalTypedBridge@1"
CANONICAL_TYPED_BRIDGE_SCHEMA_VERSION: Final = "ipfs-datasets.canonical-typed-bridge.v1"
CANONICAL_TYPED_BRIDGE_MIGRATION_INTERFACE: Final = "CanonicalTypedBridgeMigration@1"
CANONICAL_TYPED_BRIDGE_CONFORMANCE_INTERFACE: Final = "CanonicalTypedBridgeConformance@1"

# Immutable benchmark-to-design lineage, revalidated by SRT-027.
SRT014_REPORT_CID: Final = "baguqeerakqgerwv6npdlqpgrc3bjzuxqog3hiouey3c4giw5vkdgk2jhfbpq"
SRT014_GATE_CID: Final = "baguqeeraa7vbts26rxvqujbvgvgplq4xrprcebufol5qqmstc6cbrac2rthq"
SRT014_REMEDIATION_MANIFEST_CID: Final = (
    "baguqeerarr7ebjrzd3argtdekd7er3bqrnvhuzy2ogqzfi7h5nv37dbea52a"
)
REPLACEMENT_REPORT_CID: Final = "baguqeeramdvshi4ynajkvsb72zncgcn2pgvklsglgxwea7za25lndnaf5cga"
REPLACEMENT_GATE_CID: Final = "baguqeerawhggoyrnacv74kbuq3rhpmz4jikhr3tnv5uahpxcnpghfrwfj6jq"
CANONICAL_DESIGN_GATE_CID: Final = "baguqeerab4top4ljgojms7f7p6y4ksdlivfwhyzxzhynnii4zbrfvw4mqtfq"
SELECTION_BASIS: Final = "replacement_bounded_tie_policy"
SELECTABLE_ARM_IDS: Final = (
    "typed_deontic__no_guidance__no_repair__not_applicable__deterministic",
    "typed_deontic__no_guidance__selective__not_applicable__deterministic",
)
IMPLEMENTATION_REPRESENTATIVE_ARM_ID: Final = SELECTABLE_ARM_IDS[0]
IMPLEMENTATION_REPRESENTATIVE_ARM_IDENTITY_CID: Final = (
    "baguqeeraylvbngffosmvcvwowelspcdbbk5wom5itjvfanbzty4eioxsauhq"
)
TIED_SELECTIVE_ARM_IDENTITY_CID: Final = (
    "baguqeeraaslupqmtxclda2ml7ppssprxecn64wwywehq6x6tfz6vd73zr32q"
)
SELECTED_CONSTRUCTOR_INTERFACE: Final = "TypedDeonticCanonicalConstructor@1"
SELECTED_CONSTRUCTOR_ADAPTER_RAW_CID: Final = (
    "bafkreig2yeibug44tbffleyvju4zvo62thdqkpht3n2qn6guefkvbv7z2a"
)
SELECTED_REALIZER_INTERFACE: Final = "SourceWithheldCanonicalParaphraser@1"
SELECTED_REALIZER_ADAPTER_RAW_CID: Final = (
    "bafkreifrmafgdy5wajq7sepxxatwc2mnnubqt2c7kwped456vukyptfi6y"
)
SELECTED_COORDINATE_RUNNER_RAW_CID: Final = (
    "bafkreigxa4dwxkqipox36emw7m3qyd7axxb3cqwfv4ckiniewtw5ftix6u"
)

SOURCE_WITHHELD_DECOMPILER_CONFIG: Final[Mapping[str, str]] = MappingProxyType(
    {
        "profile": "typed_deontic_must_paraphrase_v1",
        "atom_surface": "underscore_to_space_v1",
        "obligation_surface": "must",
        "permission_surface": "may",
        "prohibition_surface": "must not",
        "temporal_position": "before_conditions",
        "condition_connector": "if",
        "exception_connector": "unless",
        "rule_order": "canonical_rule_ir_v1",
    }
)
SOURCE_WITHHELD_DECOMPILER_CONFIG_CID: Final = (
    "baguqeeratlk326nodsva4rxwm65xgnpenhcovspm7crtyd4enaqhgjciqayq"
)
SOURCE_WITHHELD_RENDERING_SPEC_CID: Final = (
    "baguqeera72pqowlkovfqvydbtk5lxc7g42o75xtfgmx7cm4vqdvnaimjpjvq"
)

# Filled from the checked-in policy.  The value is verified again at import
# boundary by ``load_parity_policy``; it is not trusted merely as a constant.
CANONICAL_PARITY_POLICY_CID: Final = "baguqeera5g5z4yvncxbn3uk4ftqmnxxmmclwpnwjpdshiy52la2o5bzdk27a"

MAX_TEXT_CHARS: Final = 1_000_000
MAX_ATOM_CHARS: Final = 4_096
MAX_RULES: Final = 10_000
MAX_QUALIFIERS_PER_FACET: Final = 1_000
MAX_JSON_DEPTH: Final = 20
MAX_CONFIG_BYTES: Final = 65_536

_CID_SCOPE: Final = "payload_without_cid_fields"
_CID_CODEC: Final = "dag-json"
_CID_RE = re.compile(r"^b[a-z2-7]{20,}$")
_FORBIDDEN_DECOMPILER_KEYS: Final = frozenset(
    {
        "source",
        "source_body",
        "source_cache",
        "source_cache_key",
        "source_cid",
        "source_document",
        "source_excerpt",
        "source_hash",
        "source_map",
        "source_metadata",
        "source_path",
        "source_ref",
        "source_text",
        "source_uri",
        "t0",
        "gold",
        "gold_ir",
        "prior_reconstruction",
        "native",
        "native_ir",
        "native_metadata",
        "native_payload",
        "native_record",
        "parse",
        "parse_tree",
        "constructor_record",
        "constructor_payload",
        "compiler_record",
        "compiler_payload",
        "private_payload",
        "hidden_fields",
    }
)


class CanonicalContractError(ValueError):
    """Raised when a canonical compiler/decompiler boundary is violated."""


class OperationStatus(str, Enum):
    """Terminal outcome of one compiler or decompiler request."""

    SUCCESS = "success"
    ABSTAINED = "abstained"
    FAILED = "failed"


class CanonicalErrorCode(str, Enum):
    """Stable machine-readable failure and abstention classes."""

    INVALID_REQUEST = "invalid_request"
    INVALID_IR = "invalid_ir"
    UNSUPPORTED_SEMANTICS = "unsupported_semantics"
    POLICY_MISMATCH = "policy_mismatch"
    COMPONENT_UNAVAILABLE = "component_unavailable"
    COMPONENT_FAILED = "component_failed"
    SOURCE_WITHHOLDING_VIOLATION = "source_withholding_violation"
    EMPTY_OUTPUT = "empty_output"


class DiagnosticSeverity(str, Enum):
    """Severity of a source-grounded diagnostic."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class UnsupportedDisposition(str, Enum):
    """Required handling for semantics outside the v1 representation."""

    ABSTAIN = "abstain"
    EXPLICIT_PARTIAL = "explicit_partial"


def _string(
    value: object,
    field: str,
    *,
    allow_blank: bool = False,
    maximum: int = MAX_ATOM_CHARS,
) -> str:
    if not isinstance(value, str):
        raise CanonicalContractError(f"{field} must be a string")
    if len(value) > maximum:
        raise CanonicalContractError(f"{field} exceeds the {maximum} character bound")
    if not allow_blank and not value.strip():
        raise CanonicalContractError(f"{field} must be nonblank")
    return value


def _cid(value: object, field: str, *, codec: str) -> str:
    try:
        return validate_cid(value, codecs=(codec,))
    except (TypeError, ValueError) as exc:
        raise CanonicalContractError(f"{field} must be a canonical {codec} CIDv1") from exc


def _cid_with_declared_codec(
    value: object,
    codec: object,
    field: str,
) -> tuple[str, str]:
    if codec not in {"raw", "dag-json"}:
        raise CanonicalContractError(f"{field}_codec must be raw or dag-json")
    assert isinstance(codec, str)
    return _cid(value, field, codec=codec), codec


def _freeze_json(value: object, field: str, depth: int = 0) -> object:
    if depth > MAX_JSON_DEPTH:
        raise CanonicalContractError(f"{field} exceeds maximum JSON depth")
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise CanonicalContractError(f"{field} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalContractError(f"{field} keys must be strings")
            frozen[key] = _freeze_json(item, f"{field}.{key}", depth + 1)
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(
            _freeze_json(item, f"{field}[{index}]", depth + 1) for index, item in enumerate(value)
        )
    raise CanonicalContractError(f"{field} must contain only JSON values")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _frozen_object(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CanonicalContractError(f"{field} must be an object")
    result = _freeze_json(value, field)
    assert isinstance(result, Mapping)
    encoded = json.dumps(
        _thaw_json(result),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > MAX_CONFIG_BYTES:
        raise CanonicalContractError(f"{field} exceeds the {MAX_CONFIG_BYTES} byte bound")
    return result


def _string_items(
    value: object,
    field: str,
    *,
    maximum: int = MAX_QUALIFIERS_PER_FACET,
) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise CanonicalContractError(f"{field} must be a string array")
    if len(value) > maximum:
        raise CanonicalContractError(f"{field} exceeds the {maximum} item bound")
    return tuple(sorted({_string(item, f"{field}[{index}]") for index, item in enumerate(value)}))


def _enum(value: object, enum_type: type[Enum], field: str) -> Enum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise CanonicalContractError(f"{field} is invalid") from exc


def _normalized_key(key: object) -> str:
    return (
        re.sub(
            r"[^a-z0-9]+",
            "_",
            re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key).strip()),
            flags=re.IGNORECASE,
        )
        .strip("_")
        .lower()
    )


def _reject_source_channels(value: object, path: str = "config") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _normalized_key(key) in _FORBIDDEN_DECOMPILER_KEYS:
                raise CanonicalContractError(f"decompiler request may not contain {path}.{key}")
            _reject_source_channels(item, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_source_channels(item, f"{path}[{index}]")


@dataclass(frozen=True, slots=True)
class CanonicalAtomVocabulary:
    """Caller-supplied open vocabulary for reproducible projection.

    This is not the benchmark fixture vocabulary.  It is a general transport
    contract whose values are explicit request data.  It lets conformance
    tests reproduce a measured projection without importing hidden case data;
    automatic vocabulary inference is a different, currently unmeasured stage.
    """

    actors: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    objects: tuple[str, ...] = ()
    qualifiers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("actors", "actions", "objects", "qualifiers"):
            object.__setattr__(
                self,
                name,
                _string_items(getattr(self, name), f"vocabulary.{name}"),
            )

    def to_dict(self) -> dict[str, list[str]]:
        return {
            name: list(getattr(self, name))
            for name in ("actors", "actions", "objects", "qualifiers")
        }

    @classmethod
    def from_dict(cls, value: object) -> "CanonicalAtomVocabulary":
        if not isinstance(value, Mapping) or set(value) != {
            "actors",
            "actions",
            "objects",
            "qualifiers",
        }:
            raise CanonicalContractError("atom vocabulary fields changed")
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class CanonicalRule:
    """One open-vocabulary rule in the v1 semantic bottleneck.

    The seven measured facets are stable, but their string values are not a
    production closed vocabulary.  New semantic facets require a new schema
    version; a v1 implementation must report them as unsupported rather than
    silently discard them.
    """

    modality: str
    actor: str
    action: str
    object: str = ""
    conditions: tuple[str, ...] = ()
    exceptions: tuple[str, ...] = ()
    temporal: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "modality", _string(self.modality, "modality"))
        if self.modality not in {"O", "P", "F"}:
            raise CanonicalContractError(
                "modality must be O, P, or F under the measured v1 grammar"
            )
        object.__setattr__(self, "actor", _string(self.actor, "actor"))
        object.__setattr__(self, "action", _string(self.action, "action"))
        object.__setattr__(
            self,
            "object",
            _string(self.object, "object", allow_blank=True),
        )
        for field in ("conditions", "exceptions", "temporal"):
            object.__setattr__(
                self,
                field,
                _string_items(getattr(self, field), field),
            )

    def to_dict(self) -> dict[str, object]:
        """Return the exact open-vocabulary rule payload measured by SRT-026."""

        return {
            "modality": self.modality,
            "actor": self.actor,
            "action": self.action,
            "object": self.object,
            "conditions": list(self.conditions),
            "exceptions": list(self.exceptions),
            "temporal": list(self.temporal),
        }

    @property
    def rule_cid(self) -> str:
        return cid_for_dag_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> "CanonicalRule":
        if not isinstance(value, Mapping):
            raise CanonicalContractError("canonical rule must be an object")
        expected = {
            "modality",
            "actor",
            "action",
            "object",
            "conditions",
            "exceptions",
            "temporal",
        }
        if set(value) != expected:
            raise CanonicalContractError("canonical rule fields changed")
        return cls(
            modality=value["modality"],  # type: ignore[arg-type]
            actor=value["actor"],  # type: ignore[arg-type]
            action=value["action"],  # type: ignore[arg-type]
            object=value["object"],  # type: ignore[arg-type]
            conditions=value["conditions"],  # type: ignore[arg-type]
            exceptions=value["exceptions"],  # type: ignore[arg-type]
            temporal=value["temporal"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class SourceMapEntry:
    """Ground one semantic field in a half-open source-text character span."""

    rule_cid: str
    field_path: str
    source_cid: str
    start: int
    end: int
    attribution: str = "direct"

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_cid", _cid(self.rule_cid, "rule_cid", codec="dag-json"))
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid", codec="raw"))
        _string(self.field_path, "field_path")
        _string(self.attribution, "attribution")
        if (
            isinstance(self.start, bool)
            or not isinstance(self.start, int)
            or isinstance(self.end, bool)
            or not isinstance(self.end, int)
            or self.start < 0
            or self.end <= self.start
        ):
            raise CanonicalContractError("source-map offsets must form a nonempty half-open span")

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_cid": self.rule_cid,
            "field_path": self.field_path,
            "source_cid": self.source_cid,
            "start": self.start,
            "end": self.end,
            "attribution": self.attribution,
        }

    @classmethod
    def from_dict(cls, value: object) -> "SourceMapEntry":
        if not isinstance(value, Mapping) or set(value) != {
            "rule_cid",
            "field_path",
            "source_cid",
            "start",
            "end",
            "attribution",
        }:
            raise CanonicalContractError("source-map entry fields changed")
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class UnsupportedSemantic:
    """Explicit record of meaning that v1 could not faithfully represent."""

    code: str
    message: str
    disposition: UnsupportedDisposition
    source_cid: str
    start: int
    end: int

    def __post_init__(self) -> None:
        _string(self.code, "unsupported.code")
        _string(self.message, "unsupported.message")
        object.__setattr__(
            self,
            "disposition",
            _enum(
                self.disposition,
                UnsupportedDisposition,
                "unsupported.disposition",
            ),
        )
        object.__setattr__(
            self,
            "source_cid",
            _cid(self.source_cid, "unsupported.source_cid", codec="raw"),
        )
        if (
            isinstance(self.start, bool)
            or not isinstance(self.start, int)
            or isinstance(self.end, bool)
            or not isinstance(self.end, int)
            or self.start < 0
            or self.end <= self.start
        ):
            raise CanonicalContractError(
                "unsupported semantic offsets must form a nonempty half-open span"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "disposition": self.disposition.value,
            "source_cid": self.source_cid,
            "start": self.start,
            "end": self.end,
        }

    @classmethod
    def from_dict(cls, value: object) -> "UnsupportedSemantic":
        if not isinstance(value, Mapping) or set(value) != {
            "code",
            "message",
            "disposition",
            "source_cid",
            "start",
            "end",
        }:
            raise CanonicalContractError("unsupported semantic fields changed")
        return cls(**value)  # type: ignore[arg-type]


def _rule_sort_key(rule: CanonicalRule) -> tuple[object, ...]:
    return (
        rule.modality,
        rule.actor,
        rule.action,
        rule.object,
        rule.conditions,
        rule.exceptions,
        rule.temporal,
        rule.rule_cid,
    )


@dataclass(frozen=True, slots=True)
class CanonicalRoundTripIR:
    """CID-addressed semantic IR with the exact measured payload shape."""

    rules: tuple[CanonicalRule, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.rules, Sequence) or isinstance(self.rules, (str, bytes, bytearray)):
            raise CanonicalContractError("rules must be an array")
        if not 0 < len(self.rules) <= MAX_RULES:
            raise CanonicalContractError(f"rules must contain between 1 and {MAX_RULES} entries")
        rules = tuple(
            rule if isinstance(rule, CanonicalRule) else CanonicalRule.from_dict(rule)
            for rule in self.rules
        )
        object.__setattr__(self, "rules", tuple(sorted(rules, key=_rule_sort_key)))

    @property
    def ir_cid(self) -> str:
        return cid_for_dag_json(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {"rules": [rule.to_dict() for rule in self.rules]}

    @classmethod
    def from_dict(cls, value: object) -> "CanonicalRoundTripIR":
        if not isinstance(value, Mapping):
            raise CanonicalContractError("canonical IR must be an object")
        if set(value) != {"rules"}:
            raise CanonicalContractError("canonical IR fields changed")
        return cls(rules=value["rules"])  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class CanonicalDiagnostic:
    """One immutable, optionally source-grounded diagnostic."""

    code: str
    message: str
    severity: DiagnosticSeverity
    source_cid: str | None = None
    start: int | None = None
    end: int | None = None

    def __post_init__(self) -> None:
        _string(self.code, "diagnostic.code")
        _string(self.message, "diagnostic.message")
        object.__setattr__(
            self,
            "severity",
            _enum(self.severity, DiagnosticSeverity, "diagnostic.severity"),
        )
        span_values = (self.source_cid, self.start, self.end)
        if all(value is None for value in span_values):
            return
        if any(value is None for value in span_values):
            raise CanonicalContractError(
                "diagnostic source_cid/start/end must be supplied together"
            )
        object.__setattr__(
            self,
            "source_cid",
            _cid(self.source_cid, "diagnostic.source_cid", codec="raw"),
        )
        if (
            isinstance(self.start, bool)
            or not isinstance(self.start, int)
            or isinstance(self.end, bool)
            or not isinstance(self.end, int)
            or self.start < 0
            or self.end <= self.start
        ):
            raise CanonicalContractError("diagnostic source span is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "source_cid": self.source_cid,
            "start": self.start,
            "end": self.end,
        }

    @classmethod
    def from_dict(cls, value: object) -> "CanonicalDiagnostic":
        if not isinstance(value, Mapping) or set(value) != {
            "code",
            "message",
            "severity",
            "source_cid",
            "start",
            "end",
        }:
            raise CanonicalContractError("diagnostic fields changed")
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class CanonicalError:
    """Terminal structured error returned instead of a partial artifact."""

    code: CanonicalErrorCode
    message: str
    retryable: bool = False
    details: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _enum(self.code, CanonicalErrorCode, "error.code"))
        _string(self.message, "error.message")
        if not isinstance(self.retryable, bool):
            raise CanonicalContractError("error.retryable must be boolean")
        object.__setattr__(self, "details", _frozen_object(self.details, "error.details"))

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
            "details": _thaw_json(self.details),
        }

    @classmethod
    def from_dict(cls, value: object) -> "CanonicalError":
        if not isinstance(value, Mapping) or set(value) != {
            "code",
            "message",
            "retryable",
            "details",
        }:
            raise CanonicalContractError("error fields changed")
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ComponentTrace:
    """CID-bound attribution for one explicit compiler/decompiler component."""

    component_id: str
    component_interface: str
    input_cid: str
    input_codec: str
    output_cid: str
    output_codec: str
    config_cid: str
    deterministic: bool
    model_receipt_cid: str | None = None

    def __post_init__(self) -> None:
        _string(self.component_id, "trace.component_id")
        _string(self.component_interface, "trace.component_interface")
        input_cid, input_codec = _cid_with_declared_codec(
            self.input_cid,
            self.input_codec,
            "trace.input_cid",
        )
        output_cid, output_codec = _cid_with_declared_codec(
            self.output_cid,
            self.output_codec,
            "trace.output_cid",
        )
        object.__setattr__(self, "input_cid", input_cid)
        object.__setattr__(self, "input_codec", input_codec)
        object.__setattr__(self, "output_cid", output_cid)
        object.__setattr__(self, "output_codec", output_codec)
        object.__setattr__(
            self,
            "config_cid",
            _cid(self.config_cid, "trace.config_cid", codec="dag-json"),
        )
        if not isinstance(self.deterministic, bool):
            raise CanonicalContractError("trace.deterministic must be boolean")
        if self.model_receipt_cid is not None:
            object.__setattr__(
                self,
                "model_receipt_cid",
                _cid(
                    self.model_receipt_cid,
                    "trace.model_receipt_cid",
                    codec="dag-json",
                ),
            )
        if self.deterministic and self.model_receipt_cid is not None:
            raise CanonicalContractError("deterministic trace cannot carry a model receipt")

    def to_dict(self) -> dict[str, object]:
        return {
            "component_id": self.component_id,
            "component_interface": self.component_interface,
            "input_cid": self.input_cid,
            "input_codec": self.input_codec,
            "output_cid": self.output_cid,
            "output_codec": self.output_codec,
            "config_cid": self.config_cid,
            "deterministic": self.deterministic,
            "model_receipt_cid": self.model_receipt_cid,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ComponentTrace":
        if not isinstance(value, Mapping) or set(value) != {
            "component_id",
            "component_interface",
            "input_cid",
            "input_codec",
            "output_cid",
            "output_codec",
            "config_cid",
            "deterministic",
            "model_receipt_cid",
        }:
            raise CanonicalContractError("component trace fields changed")
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class CompilerRequest:
    """Bounded public request for structured text to canonical IR."""

    source_text: str
    request_id: str
    atom_vocabulary: CanonicalAtomVocabulary
    policy_cid: str = CANONICAL_PARITY_POLICY_CID
    allow_explicit_partial: bool = False
    config: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        _string(
            self.source_text,
            "source_text",
            maximum=MAX_TEXT_CHARS,
        )
        _string(self.request_id, "request_id")
        object.__setattr__(
            self,
            "policy_cid",
            _cid(self.policy_cid, "policy_cid", codec="dag-json"),
        )
        if self.policy_cid != CANONICAL_PARITY_POLICY_CID:
            raise CanonicalContractError("compiler request policy CID changed")
        if not isinstance(self.atom_vocabulary, CanonicalAtomVocabulary):
            if isinstance(self.atom_vocabulary, Mapping):
                object.__setattr__(
                    self,
                    "atom_vocabulary",
                    CanonicalAtomVocabulary.from_dict(self.atom_vocabulary),
                )
            else:
                raise CanonicalContractError("atom_vocabulary must be CanonicalAtomVocabulary")
        if not isinstance(self.allow_explicit_partial, bool):
            raise CanonicalContractError("allow_explicit_partial must be boolean")
        object.__setattr__(self, "config", _frozen_object(self.config, "config"))

    @property
    def source_cid(self) -> str:
        return cid_for_bytes(self.source_text.encode("utf-8"))

    def identity_payload(self) -> dict[str, object]:
        return {
            "interface": CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE,
            "request_id": self.request_id,
            "source_cid": self.source_cid,
            "policy_cid": self.policy_cid,
            "atom_vocabulary": self.atom_vocabulary.to_dict(),
            "allow_explicit_partial": self.allow_explicit_partial,
            "config": _thaw_json(self.config),
        }

    @property
    def request_cid(self) -> str:
        return cid_for_dag_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        """Return the complete executable wire request with verified IDs."""

        return {
            **self.identity_payload(),
            "source_text": self.source_text,
            "request_cid": self.request_cid,
            "request_cid_codec": "dag-json",
            "request_cid_scope": "identity_payload_with_source_cid",
        }

    @classmethod
    def from_dict(cls, value: object) -> "CompilerRequest":
        if not isinstance(value, Mapping) or set(value) != {
            "interface",
            "request_id",
            "source_text",
            "source_cid",
            "policy_cid",
            "atom_vocabulary",
            "allow_explicit_partial",
            "config",
            "request_cid",
            "request_cid_codec",
            "request_cid_scope",
        }:
            raise CanonicalContractError("compiler request fields changed")
        if value["interface"] != CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE:
            raise CanonicalContractError("compiler request interface changed")
        if (
            value["request_cid_codec"] != "dag-json"
            or value["request_cid_scope"] != "identity_payload_with_source_cid"
        ):
            raise CanonicalContractError("compiler request CID contract changed")
        request = cls(
            source_text=value["source_text"],  # type: ignore[arg-type]
            request_id=value["request_id"],  # type: ignore[arg-type]
            atom_vocabulary=CanonicalAtomVocabulary.from_dict(value["atom_vocabulary"]),
            policy_cid=value["policy_cid"],  # type: ignore[arg-type]
            allow_explicit_partial=value[  # type: ignore[arg-type]
                "allow_explicit_partial"
            ],
            config=value["config"],  # type: ignore[arg-type]
        )
        if _cid(value["source_cid"], "source_cid", codec="raw") != request.source_cid:
            raise CanonicalContractError("source_cid does not match source_text")
        if _cid(value["request_cid"], "request_cid", codec="dag-json") != request.request_cid:
            raise CanonicalContractError("request_cid does not match compiler request")
        return request


@dataclass(frozen=True, slots=True)
class DecompilerRequest:
    """Strict source-withheld request for canonical IR to natural language."""

    canonical_ir: CanonicalRoundTripIR
    request_id: str
    policy_cid: str = CANONICAL_PARITY_POLICY_CID
    config: Mapping[str, object] = field(default_factory=lambda: SOURCE_WITHHELD_DECOMPILER_CONFIG)

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_ir, CanonicalRoundTripIR):
            raise CanonicalContractError("canonical_ir must be CanonicalRoundTripIR")
        _string(self.request_id, "request_id")
        object.__setattr__(
            self,
            "policy_cid",
            _cid(self.policy_cid, "policy_cid", codec="dag-json"),
        )
        if self.policy_cid != CANONICAL_PARITY_POLICY_CID:
            raise CanonicalContractError("decompiler request policy CID changed")
        _reject_source_channels(self.config)
        frozen_config = _frozen_object(self.config, "config")
        if dict(frozen_config) != dict(SOURCE_WITHHELD_DECOMPILER_CONFIG):
            raise CanonicalContractError(
                "decompiler config must equal the measured source-withheld "
                f"profile {SOURCE_WITHHELD_DECOMPILER_CONFIG_CID}"
            )
        if cid_for_dag_json(dict(frozen_config)) != SOURCE_WITHHELD_DECOMPILER_CONFIG_CID:
            raise CanonicalContractError(
                "decompiler config CID does not match the measured profile"
            )
        object.__setattr__(self, "config", frozen_config)

    def identity_payload(self) -> dict[str, object]:
        return {
            "interface": CANONICAL_STRUCTURED_TEXT_DECOMPILER_INTERFACE,
            "request_id": self.request_id,
            "canonical_ir_cid": self.canonical_ir.ir_cid,
            "policy_cid": self.policy_cid,
            "source_withheld": True,
            "config": _thaw_json(self.config),
            "config_cid": SOURCE_WITHHELD_DECOMPILER_CONFIG_CID,
            "rendering_spec_cid": SOURCE_WITHHELD_RENDERING_SPEC_CID,
        }

    @property
    def request_cid(self) -> str:
        return cid_for_dag_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        """Return the complete source-withheld executable wire request."""

        return {
            **self.identity_payload(),
            "canonical_ir": self.canonical_ir.to_dict(),
            "request_cid": self.request_cid,
            "request_cid_codec": "dag-json",
            "request_cid_scope": "identity_payload_with_canonical_ir_cid",
        }

    @classmethod
    def from_dict(cls, value: object) -> "DecompilerRequest":
        if not isinstance(value, Mapping) or set(value) != {
            "interface",
            "request_id",
            "canonical_ir",
            "canonical_ir_cid",
            "policy_cid",
            "source_withheld",
            "config",
            "config_cid",
            "rendering_spec_cid",
            "request_cid",
            "request_cid_codec",
            "request_cid_scope",
        }:
            raise CanonicalContractError("decompiler request fields changed")
        if value["interface"] != CANONICAL_STRUCTURED_TEXT_DECOMPILER_INTERFACE:
            raise CanonicalContractError("decompiler request interface changed")
        if value["source_withheld"] is not True:
            raise CanonicalContractError("decompiler request is not source-withheld")
        if value["config_cid"] != SOURCE_WITHHELD_DECOMPILER_CONFIG_CID:
            raise CanonicalContractError("decompiler config CID changed")
        if value["rendering_spec_cid"] != SOURCE_WITHHELD_RENDERING_SPEC_CID:
            raise CanonicalContractError("decompiler rendering spec CID changed")
        if (
            value["request_cid_codec"] != "dag-json"
            or value["request_cid_scope"] != "identity_payload_with_canonical_ir_cid"
        ):
            raise CanonicalContractError("decompiler request CID contract changed")
        canonical_ir = CanonicalRoundTripIR.from_dict(value["canonical_ir"])
        if (
            _cid(
                value["canonical_ir_cid"],
                "canonical_ir_cid",
                codec="dag-json",
            )
            != canonical_ir.ir_cid
        ):
            raise CanonicalContractError("canonical_ir_cid does not match canonical_ir")
        request = cls(
            canonical_ir=canonical_ir,
            request_id=value["request_id"],  # type: ignore[arg-type]
            policy_cid=value["policy_cid"],  # type: ignore[arg-type]
            config=value["config"],  # type: ignore[arg-type]
        )
        if _cid(value["request_cid"], "request_cid", codec="dag-json") != request.request_cid:
            raise CanonicalContractError("request_cid does not match decompiler request")
        return request


def _diagnostics(value: object) -> tuple[CanonicalDiagnostic, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise CanonicalContractError("diagnostics must be an array")
    return tuple(
        item if isinstance(item, CanonicalDiagnostic) else CanonicalDiagnostic.from_dict(item)
        for item in value
    )


def _traces(value: object) -> tuple[ComponentTrace, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise CanonicalContractError("component_trace must be an array")
    return tuple(
        item if isinstance(item, ComponentTrace) else ComponentTrace.from_dict(item)
        for item in value
    )


@dataclass(frozen=True, slots=True)
class CompilerResult:
    """Terminal compiler result; partial meaning can never be silent."""

    status: OperationStatus
    request_cid: str
    canonical_ir: CanonicalRoundTripIR | None = None
    source_map: tuple[SourceMapEntry, ...] = ()
    unsupported_semantics: tuple[UnsupportedSemantic, ...] = ()
    provenance: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))
    diagnostics: tuple[CanonicalDiagnostic, ...] = ()
    component_trace: tuple[ComponentTrace, ...] = ()
    error: CanonicalError | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _enum(self.status, OperationStatus, "status"))
        object.__setattr__(
            self,
            "request_cid",
            _cid(self.request_cid, "request_cid", codec="dag-json"),
        )
        if self.canonical_ir is not None and not isinstance(
            self.canonical_ir, CanonicalRoundTripIR
        ):
            raise CanonicalContractError("canonical_ir must be CanonicalRoundTripIR or None")
        entries = tuple(
            entry if isinstance(entry, SourceMapEntry) else SourceMapEntry.from_dict(entry)
            for entry in self.source_map
        )
        if self.canonical_ir is None and entries:
            raise CanonicalContractError("source_map requires a canonical IR result")
        if self.canonical_ir is not None:
            known_rule_cids = {rule.rule_cid for rule in self.canonical_ir.rules}
            if any(entry.rule_cid not in known_rule_cids for entry in entries):
                raise CanonicalContractError("source_map references a rule outside this IR")
        object.__setattr__(
            self,
            "source_map",
            tuple(
                sorted(
                    entries,
                    key=lambda item: (
                        item.rule_cid,
                        item.field_path,
                        item.start,
                        item.end,
                    ),
                )
            ),
        )
        unsupported = tuple(
            item if isinstance(item, UnsupportedSemantic) else UnsupportedSemantic.from_dict(item)
            for item in self.unsupported_semantics
        )
        object.__setattr__(
            self,
            "unsupported_semantics",
            tuple(
                sorted(
                    unsupported,
                    key=lambda item: (
                        item.code,
                        item.source_cid,
                        item.start,
                        item.end,
                    ),
                )
            ),
        )
        object.__setattr__(
            self,
            "provenance",
            _frozen_object(self.provenance, "provenance"),
        )
        object.__setattr__(self, "diagnostics", _diagnostics(self.diagnostics))
        object.__setattr__(self, "component_trace", _traces(self.component_trace))
        if self.error is not None and not isinstance(self.error, CanonicalError):
            raise CanonicalContractError("error must be CanonicalError or None")
        if self.status is OperationStatus.SUCCESS:
            if self.canonical_ir is None or self.error is not None:
                raise CanonicalContractError("successful compiler result requires IR and no error")
            if any(
                item.disposition is UnsupportedDisposition.ABSTAIN
                for item in self.unsupported_semantics
            ):
                raise CanonicalContractError(
                    "successful result cannot carry abstain-required semantics"
                )
        elif self.canonical_ir is not None or self.error is None:
            raise CanonicalContractError(
                "abstained/failed compiler result requires an error and no IR"
            )
        elif self.source_map:
            raise CanonicalContractError(
                "abstained/failed compiler result cannot carry a source map"
            )

    def source_map_receipt(self) -> dict[str, object] | None:
        """Bind the source map to the exact request and semantic IR."""

        if self.canonical_ir is None:
            return None
        body: dict[str, object] = {
            "interface": "CanonicalSourceMapReceipt@1",
            "request_cid": self.request_cid,
            "canonical_ir_cid": self.canonical_ir.ir_cid,
            "entries": [entry.to_dict() for entry in self.source_map],
        }
        return {**body, "receipt_cid": cid_for_dag_json(body)}

    def identity_payload(self) -> dict[str, object]:
        return {
            "interface": CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE,
            "status": self.status.value,
            "request_cid": self.request_cid,
            "canonical_ir": (None if self.canonical_ir is None else self.canonical_ir.to_dict()),
            "canonical_ir_cid": (None if self.canonical_ir is None else self.canonical_ir.ir_cid),
            "source_map_receipt": self.source_map_receipt(),
            "unsupported_semantics": [item.to_dict() for item in self.unsupported_semantics],
            "provenance": _thaw_json(self.provenance),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "component_trace": [item.to_dict() for item in self.component_trace],
            "error": None if self.error is None else self.error.to_dict(),
        }

    @property
    def result_cid(self) -> str:
        return cid_for_dag_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "result_cid": self.result_cid,
            "result_cid_codec": "dag-json",
            "result_cid_scope": "identity_payload",
        }

    @classmethod
    def from_dict(cls, value: object) -> "CompilerResult":
        if not isinstance(value, Mapping) or set(value) != {
            "interface",
            "status",
            "request_cid",
            "canonical_ir",
            "canonical_ir_cid",
            "source_map_receipt",
            "unsupported_semantics",
            "provenance",
            "diagnostics",
            "component_trace",
            "error",
            "result_cid",
            "result_cid_codec",
            "result_cid_scope",
        }:
            raise CanonicalContractError("compiler result fields changed")
        if value["interface"] != CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE:
            raise CanonicalContractError("compiler result interface changed")
        if (
            value["result_cid_codec"] != "dag-json"
            or value["result_cid_scope"] != "identity_payload"
        ):
            raise CanonicalContractError("compiler result CID contract changed")
        raw_ir = value["canonical_ir"]
        canonical_ir = None if raw_ir is None else CanonicalRoundTripIR.from_dict(raw_ir)
        if canonical_ir is None:
            if value["canonical_ir_cid"] is not None:
                raise CanonicalContractError("compiler result has CID without canonical IR")
        elif (
            _cid(
                value["canonical_ir_cid"],
                "canonical_ir_cid",
                codec="dag-json",
            )
            != canonical_ir.ir_cid
        ):
            raise CanonicalContractError("compiler result canonical_ir_cid does not match IR")
        raw_error = value["error"]
        result = cls(
            status=value["status"],  # type: ignore[arg-type]
            request_cid=value["request_cid"],  # type: ignore[arg-type]
            canonical_ir=canonical_ir,
            source_map=(
                ()
                if value["source_map_receipt"] is None
                else tuple(
                    SourceMapEntry.from_dict(item)
                    for item in value["source_map_receipt"][  # type: ignore[index,union-attr]
                        "entries"
                    ]
                )
            ),
            unsupported_semantics=tuple(
                UnsupportedSemantic.from_dict(item)
                for item in value["unsupported_semantics"]  # type: ignore[union-attr]
            ),
            provenance=value["provenance"],  # type: ignore[arg-type]
            diagnostics=tuple(
                CanonicalDiagnostic.from_dict(item)
                for item in value["diagnostics"]  # type: ignore[union-attr]
            ),
            component_trace=tuple(
                ComponentTrace.from_dict(item)
                for item in value["component_trace"]  # type: ignore[union-attr]
            ),
            error=(None if raw_error is None else CanonicalError.from_dict(raw_error)),
        )
        if result.source_map_receipt() != value["source_map_receipt"]:
            raise CanonicalContractError("source-map receipt does not match result")
        if _cid(value["result_cid"], "result_cid", codec="dag-json") != result.result_cid:
            raise CanonicalContractError("result_cid does not match compiler result")
        return result


@dataclass(frozen=True, slots=True)
class DecompilerResult:
    """Terminal source-withheld decompiler result with stable attribution."""

    status: OperationStatus
    request_cid: str
    text: str | None = None
    text_cid: str | None = None
    diagnostics: tuple[CanonicalDiagnostic, ...] = ()
    component_trace: tuple[ComponentTrace, ...] = ()
    error: CanonicalError | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _enum(self.status, OperationStatus, "status"))
        object.__setattr__(
            self,
            "request_cid",
            _cid(self.request_cid, "request_cid", codec="dag-json"),
        )
        object.__setattr__(self, "diagnostics", _diagnostics(self.diagnostics))
        object.__setattr__(self, "component_trace", _traces(self.component_trace))
        if self.error is not None and not isinstance(self.error, CanonicalError):
            raise CanonicalContractError("error must be CanonicalError or None")
        if self.status is OperationStatus.SUCCESS:
            if self.text is None or self.text_cid is None or self.error is not None:
                raise CanonicalContractError(
                    "successful decompiler result requires text/CID and no error"
                )
            _string(self.text, "text", maximum=MAX_TEXT_CHARS)
            supplied = _cid(self.text_cid, "text_cid", codec="raw")
            expected = cid_for_bytes(self.text.encode("utf-8"))
            if supplied != expected:
                raise CanonicalContractError("text_cid does not match reconstructed text")
        elif self.text is not None or self.text_cid is not None or self.error is None:
            raise CanonicalContractError(
                "abstained/failed decompiler result requires an error and no text"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "interface": CANONICAL_STRUCTURED_TEXT_DECOMPILER_INTERFACE,
            "status": self.status.value,
            "request_cid": self.request_cid,
            "text": self.text,
            "text_cid": self.text_cid,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "component_trace": [item.to_dict() for item in self.component_trace],
            "error": None if self.error is None else self.error.to_dict(),
            "source_withheld": True,
        }

    @property
    def result_cid(self) -> str:
        return cid_for_dag_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "result_cid": self.result_cid,
            "result_cid_codec": "dag-json",
            "result_cid_scope": "identity_payload",
        }

    @classmethod
    def from_dict(cls, value: object) -> "DecompilerResult":
        if not isinstance(value, Mapping) or set(value) != {
            "interface",
            "status",
            "request_cid",
            "text",
            "text_cid",
            "diagnostics",
            "component_trace",
            "error",
            "source_withheld",
            "result_cid",
            "result_cid_codec",
            "result_cid_scope",
        }:
            raise CanonicalContractError("decompiler result fields changed")
        if value["interface"] != CANONICAL_STRUCTURED_TEXT_DECOMPILER_INTERFACE:
            raise CanonicalContractError("decompiler result interface changed")
        if value["source_withheld"] is not True:
            raise CanonicalContractError("decompiler result is not source-withheld")
        if (
            value["result_cid_codec"] != "dag-json"
            or value["result_cid_scope"] != "identity_payload"
        ):
            raise CanonicalContractError("decompiler result CID contract changed")
        raw_error = value["error"]
        result = cls(
            status=value["status"],  # type: ignore[arg-type]
            request_cid=value["request_cid"],  # type: ignore[arg-type]
            text=value["text"],  # type: ignore[arg-type]
            text_cid=value["text_cid"],  # type: ignore[arg-type]
            diagnostics=tuple(
                CanonicalDiagnostic.from_dict(item)
                for item in value["diagnostics"]  # type: ignore[union-attr]
            ),
            component_trace=tuple(
                ComponentTrace.from_dict(item)
                for item in value["component_trace"]  # type: ignore[union-attr]
            ),
            error=(None if raw_error is None else CanonicalError.from_dict(raw_error)),
        )
        if _cid(value["result_cid"], "result_cid", codec="dag-json") != result.result_cid:
            raise CanonicalContractError("result_cid does not match decompiler result")
        return result


@dataclass(frozen=True, slots=True)
class CanonicalParityPolicy:
    """Validated immutable view of the checked-in SRT-015 parity policy."""

    document: Mapping[str, object]

    def __post_init__(self) -> None:
        policy = _frozen_object(self.document, "parity_policy")
        plain = _thaw_json(policy)
        assert isinstance(plain, dict)
        if plain.get("interface") != CANONICAL_ROUNDTRIP_PARITY_POLICY_INTERFACE:
            raise CanonicalContractError("parity policy interface changed")
        if plain.get("schema_version") != CANONICAL_ROUNDTRIP_PARITY_POLICY_SCHEMA:
            raise CanonicalContractError("parity policy schema changed")
        if plain.get("policy_cid_codec") != _CID_CODEC:
            raise CanonicalContractError("parity policy CID codec changed")
        if plain.get("policy_cid_scope") != "document_without_policy_cid":
            raise CanonicalContractError("parity policy CID scope changed")
        supplied = _cid(plain.get("policy_cid"), "policy_cid", codec="dag-json")
        payload = dict(plain)
        payload.pop("policy_cid", None)
        expected = cid_for_dag_json(payload)
        if supplied != expected or supplied != CANONICAL_PARITY_POLICY_CID:
            raise CanonicalContractError("parity policy CID does not match payload")
        evidence = plain.get("evidence")
        if not isinstance(evidence, Mapping):
            raise CanonicalContractError("parity policy evidence must be an object")
        expected_evidence = {
            "srt014_report_cid": SRT014_REPORT_CID,
            "srt014_gate_cid": SRT014_GATE_CID,
            "remediation_manifest_cid": SRT014_REMEDIATION_MANIFEST_CID,
            "replacement_report_cid": REPLACEMENT_REPORT_CID,
            "replacement_gate_cid": REPLACEMENT_GATE_CID,
            "canonical_design_gate_cid": CANONICAL_DESIGN_GATE_CID,
        }
        if dict(evidence) != expected_evidence:
            raise CanonicalContractError("parity policy evidence lineage changed")
        selection = plain.get("selection")
        if not isinstance(selection, Mapping) or dict(selection) != {
            "outcome": "exact_tie",
            "selection_basis": SELECTION_BASIS,
            "selectable_arm_ids": list(SELECTABLE_ARM_IDS),
            "implementation_representative_arm_id": (IMPLEMENTATION_REPRESENTATIVE_ARM_ID),
            "representative_semantically_superior": False,
        }:
            raise CanonicalContractError("parity policy selection lineage changed")
        object.__setattr__(self, "document", policy)

    @property
    def policy_cid(self) -> str:
        return CANONICAL_PARITY_POLICY_CID

    def to_dict(self) -> dict[str, object]:
        result = _thaw_json(self.document)
        assert isinstance(result, dict)
        return result


def canonical_ir_schema_path() -> resources.abc.Traversable:
    """Return the packaged v1 schema resource without assuming a filesystem."""

    return resources.files("ipfs_datasets_py.logic.legal_ir").joinpath(
        "schemas/canonical_roundtrip_ir.schema.json"
    )


def load_canonical_ir_schema() -> dict[str, object]:
    """Load a detached copy of the packaged canonical IR JSON Schema."""

    with canonical_ir_schema_path().open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise CanonicalContractError("canonical IR schema must be an object")
    return value


def load_parity_policy() -> CanonicalParityPolicy:
    """Load and validate the repository/package SRT-015 parity policy."""

    package_root = resources.files("ipfs_datasets_py")
    policy_path = package_root.parent.joinpath(
        "docs/benchmarks/semantic_roundtrip_canonical_parity_policy.json"
    )
    try:
        with policy_path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except (FileNotFoundError, TypeError):
        # Wheels need not ship repository documentation.  The exact immutable
        # policy payload remains available beside this module as a package
        # resource through the schema's ``x-parity-policy`` annotation.
        schema = load_canonical_ir_schema()
        value = schema.get("x-parity-policy")
    if not isinstance(value, Mapping):
        raise CanonicalContractError("canonical parity policy is unavailable")
    return CanonicalParityPolicy(value)


@runtime_checkable
class CanonicalStructuredTextCompiler(Protocol):
    """Structural interface consumed by orchestration and round-trip code."""

    @property
    def identity(self) -> str:
        """Return a frozen implementation/configuration identity."""

    def compile(self, request: CompilerRequest) -> CompilerResult:
        """Compile structured text or return an explicit abstention/failure."""


@runtime_checkable
class CanonicalStructuredTextDecompiler(Protocol):
    """Source-withheld structural interface for canonical IR realization."""

    @property
    def identity(self) -> str:
        """Return a frozen implementation/configuration identity."""

    def decompile(self, request: DecompilerRequest) -> DecompilerResult:
        """Realize canonical IR without consulting its originating source."""


class ConstructDisposition(str, Enum):
    """How one required typed-bridge construct is carried."""

    REPRESENTED = "represented"
    EXPLICIT_PARTIAL = "explicit_partial"
    UNSUPPORTED = "unsupported"


class RequiredBridgeConstruct(str, Enum):
    """Closed catalog of constructs every typed-bridge envelope must account for."""

    FAMILY_IDENTITY = "family_identity"
    SOURCE_REFERENCES = "source_references"
    ASSUMPTIONS = "assumptions"
    PROVENANCE = "provenance"
    UNSUPPORTED_CONSTRUCTS = "unsupported_constructs"
    SOURCE_TEXT = "source_text"
    TYPED_SYNTAX = "typed_syntax"
    CANONICAL_IR = "canonical_ir"
    DOMAIN_LOGIC_SLICE = "domain_logic_slice"
    LOGIC_FAMILY_REPRESENTATIONS = "logic_family_representations"
    FAMILY_EXTENSIONS = "family_extensions"
    FORMALIZATION_ARTIFACT = "formalization_artifact"
    LEGAL_IR_DOCUMENT = "legal_ir_document"
    PROVER_SYNTAX = "prover_syntax"
    CONTROLLED_NATURAL_LANGUAGE = "controlled_natural_language"
    PROOF_TRACES = "proof_traces"
    TACTIC_TRACES = "tactic_traces"
    COUNTEREXAMPLE_TRACES = "counterexample_traces"
    TRANSLATION_TRACES = "translation_traces"


class BridgeRepresentationKind(str, Enum):
    """Closed representation kinds aligned with the existing training vocabulary."""

    SOURCE_TEXT = "source_text"
    CONTROLLED_NATURAL_LANGUAGE = "controlled_natural_language"
    TYPED_SYNTAX = "typed_syntax"
    CANONICAL_IR = "canonical_ir"
    DOMAIN_LOGIC_SLICE = "domain_logic_slice"
    LOGIC_FAMILY = "logic_family"
    PROVER_SYNTAX = "prover_syntax"
    FORMALIZATION_ARTIFACT = "formalization_artifact"
    LEGAL_IR_DOCUMENT = "legal_ir_document"
    TRACE = "trace"
    FAMILY_EXTENSION = "family_extension"


class BridgeTraceKind(str, Enum):
    """Closed trace kinds carried by the typed bridge."""

    PROOF = "proof"
    TACTIC = "tactic"
    COUNTEREXAMPLE = "counterexample"
    TRANSLATION = "translation"


REGISTERED_BRIDGE_FAMILY_IDS: Final[frozenset[str]] = frozenset(
    {
        "canonical_roundtrip",
        "legal",
        "security",
        "intent",
        "deontic",
        "modal",
        "tdfol",
        "cec",
        "zkp",
        "first_order",
        "temporal",
        "policy",
        "threat_model",
        "frame_logic",
        "unspecified",
        "propositional",
        "higher_order",
        "datalog",
        "hoare",
        "smt",
        "linear",
        "separation",
    }
)
FORBIDDEN_BRIDGE_FAMILY_IDS: Final[frozenset[str]] = frozenset(
    {
        "domain_logic_slice",
        "DomainLogicSlice",
        "domain-logic-slice",
        "domainlogic slice",
    }
)
CORE_BRIDGE_VIEW_NAMES: Final[frozenset[str]] = frozenset(
    {
        "canonical_roundtrip_ir",
        "typed_syntax",
        "source_text",
        "formalization_artifact",
        "legal_ir_document",
        "prover_syntax",
        "controlled_natural_language",
        "logic_family",
        "domain_logic_slice",
    }
)
_DEFAULT_UNSUPPORTED_CONSTRUCT_MESSAGES: Final[Mapping[str, str]] = MappingProxyType(
    {
        RequiredBridgeConstruct.DOMAIN_LOGIC_SLICE.value: (
            "No DomainLogicSlice schema or family exists at the bound authority "
            "tree; the construct is retained as unsupported rather than invented "
            "or silently aliased to an existing family AST."
        ),
        RequiredBridgeConstruct.CANONICAL_IR.value: (
            "No CanonicalRoundTripIR view was supplied to this envelope."
        ),
        RequiredBridgeConstruct.TYPED_SYNTAX.value: (
            "No typed-syntax view was supplied to this envelope."
        ),
        RequiredBridgeConstruct.SOURCE_TEXT.value: (
            "No source-text view or source reference was supplied to this envelope."
        ),
        RequiredBridgeConstruct.FORMALIZATION_ARTIFACT.value: (
            "No FormalizationArtifact view was supplied to this envelope."
        ),
        RequiredBridgeConstruct.LEGAL_IR_DOCUMENT.value: (
            "No LegalIRDocument view was supplied to this envelope."
        ),
        RequiredBridgeConstruct.PROVER_SYNTAX.value: (
            "No prover-syntax view was supplied to this envelope."
        ),
        RequiredBridgeConstruct.CONTROLLED_NATURAL_LANGUAGE.value: (
            "No controlled-natural-language view was supplied to this envelope."
        ),
        RequiredBridgeConstruct.PROOF_TRACES.value: (
            "No proof-trace reference was supplied to this envelope."
        ),
        RequiredBridgeConstruct.TACTIC_TRACES.value: (
            "No tactic-trace reference was supplied to this envelope."
        ),
        RequiredBridgeConstruct.COUNTEREXAMPLE_TRACES.value: (
            "No counterexample-trace reference was supplied to this envelope."
        ),
        RequiredBridgeConstruct.TRANSLATION_TRACES.value: (
            "No translation-trace reference was supplied to this envelope."
        ),
        RequiredBridgeConstruct.LOGIC_FAMILY_REPRESENTATIONS.value: (
            "No existing logic-family representation view was supplied."
        ),
        RequiredBridgeConstruct.FAMILY_EXTENSIONS.value: (
            "No family-extension view was supplied to this envelope."
        ),
    }
)
_CONSTRUCT_VIEW_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {
        RequiredBridgeConstruct.CANONICAL_IR.value: "canonical_roundtrip_ir",
        RequiredBridgeConstruct.TYPED_SYNTAX.value: "typed_syntax",
        RequiredBridgeConstruct.SOURCE_TEXT.value: "source_text",
        RequiredBridgeConstruct.FORMALIZATION_ARTIFACT.value: "formalization_artifact",
        RequiredBridgeConstruct.LEGAL_IR_DOCUMENT.value: "legal_ir_document",
        RequiredBridgeConstruct.PROVER_SYNTAX.value: "prover_syntax",
        RequiredBridgeConstruct.CONTROLLED_NATURAL_LANGUAGE.value: (
            "controlled_natural_language"
        ),
        RequiredBridgeConstruct.LOGIC_FAMILY_REPRESENTATIONS.value: "logic_family",
    }
)
_CONSTRUCT_VIEW_KINDS: Final[Mapping[str, BridgeRepresentationKind]] = MappingProxyType(
    {
        RequiredBridgeConstruct.CANONICAL_IR.value: BridgeRepresentationKind.CANONICAL_IR,
        RequiredBridgeConstruct.TYPED_SYNTAX.value: BridgeRepresentationKind.TYPED_SYNTAX,
        RequiredBridgeConstruct.SOURCE_TEXT.value: BridgeRepresentationKind.SOURCE_TEXT,
        RequiredBridgeConstruct.FORMALIZATION_ARTIFACT.value: (
            BridgeRepresentationKind.FORMALIZATION_ARTIFACT
        ),
        RequiredBridgeConstruct.LEGAL_IR_DOCUMENT.value: (
            BridgeRepresentationKind.LEGAL_IR_DOCUMENT
        ),
        RequiredBridgeConstruct.PROVER_SYNTAX.value: BridgeRepresentationKind.PROVER_SYNTAX,
        RequiredBridgeConstruct.CONTROLLED_NATURAL_LANGUAGE.value: (
            BridgeRepresentationKind.CONTROLLED_NATURAL_LANGUAGE
        ),
        RequiredBridgeConstruct.LOGIC_FAMILY_REPRESENTATIONS.value: (
            BridgeRepresentationKind.LOGIC_FAMILY
        ),
    }
)


def _view_represents_construct(
    construct: str,
    views: Mapping[str, "BridgeView"],
) -> bool:
    """Return whether a reserved name or matching view kind carries ``construct``."""

    reserved = _CONSTRUCT_VIEW_NAMES.get(construct)
    if reserved is not None and reserved in views:
        return True
    expected_kind = _CONSTRUCT_VIEW_KINDS.get(construct)
    if expected_kind is None:
        return False
    return any(view.kind is expected_kind for view in views.values())


_CONSTRUCT_TRACE_KINDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        RequiredBridgeConstruct.PROOF_TRACES.value: BridgeTraceKind.PROOF.value,
        RequiredBridgeConstruct.TACTIC_TRACES.value: BridgeTraceKind.TACTIC.value,
        RequiredBridgeConstruct.COUNTEREXAMPLE_TRACES.value: (
            BridgeTraceKind.COUNTEREXAMPLE.value
        ),
        RequiredBridgeConstruct.TRANSLATION_TRACES.value: (
            BridgeTraceKind.TRANSLATION.value
        ),
    }
)


def _bridge_family_id(value: object, field: str) -> str:
    family_id = _string(value, field)
    if family_id in FORBIDDEN_BRIDGE_FAMILY_IDS or family_id.lower() in {
        item.lower() for item in FORBIDDEN_BRIDGE_FAMILY_IDS
    }:
        raise CanonicalContractError(
            f"{field} cannot be a DomainLogicSlice family; that name is not a "
            "logic family and must not alias an existing family AST"
        )
    if family_id not in REGISTERED_BRIDGE_FAMILY_IDS:
        raise CanonicalContractError(
            f"{field} {family_id!r} is not a registered existing logic family"
        )
    return family_id


def _optional_raw_cid(value: object, field: str) -> str | None:
    if value is None or value == "":
        return None
    return _cid(value, field, codec="raw")


def _optional_dag_cid(value: object, field: str) -> str | None:
    if value is None or value == "":
        return None
    return _cid(value, field, codec="dag-json")


def _optional_span(start: object, end: object, field: str) -> tuple[int | None, int | None]:
    if start is None and end is None:
        return None, None
    if (
        isinstance(start, bool)
        or not isinstance(start, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
        or start < 0
        or end <= start
    ):
        raise CanonicalContractError(f"{field} offsets must form a nonempty half-open span")
    return start, end


@dataclass(frozen=True, slots=True)
class BridgeFamilyIdentity:
    """Existing-family identity retained by one typed-bridge envelope."""

    family_id: str
    authority_schema: str
    payload_cid: str
    payload_codec: str = "dag-json"
    representation_kind: BridgeRepresentationKind = BridgeRepresentationKind.LOGIC_FAMILY

    def __post_init__(self) -> None:
        object.__setattr__(self, "family_id", _bridge_family_id(self.family_id, "family_id"))
        object.__setattr__(
            self,
            "authority_schema",
            _string(self.authority_schema, "authority_schema"),
        )
        object.__setattr__(
            self,
            "representation_kind",
            _enum(
                self.representation_kind,
                BridgeRepresentationKind,
                "representation_kind",
            ),
        )
        if self.representation_kind is BridgeRepresentationKind.DOMAIN_LOGIC_SLICE:
            raise CanonicalContractError(
                "family identity cannot use the domain_logic_slice representation "
                "kind; that kind is a projection role, not a family"
            )
        payload_cid, payload_codec = _cid_with_declared_codec(
            self.payload_cid,
            self.payload_codec,
            "payload_cid",
        )
        object.__setattr__(self, "payload_cid", payload_cid)
        object.__setattr__(self, "payload_codec", payload_codec)

    def to_dict(self) -> dict[str, object]:
        return {
            "authority_schema": self.authority_schema,
            "family_id": self.family_id,
            "payload_cid": self.payload_cid,
            "payload_codec": self.payload_codec,
            "representation_kind": self.representation_kind.value,
        }

    @classmethod
    def from_dict(cls, value: object) -> "BridgeFamilyIdentity":
        if not isinstance(value, Mapping) or set(value) != {
            "authority_schema",
            "family_id",
            "payload_cid",
            "payload_codec",
            "representation_kind",
        }:
            raise CanonicalContractError("family identity fields changed")
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class BridgeSourceReference:
    """Content-addressed source binding carried beside family payloads."""

    ref_id: str
    source_cid: str
    source_uri: str = ""
    source_revision: str = ""
    start: int | None = None
    end: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref_id", _string(self.ref_id, "source_ref.ref_id"))
        object.__setattr__(
            self,
            "source_cid",
            _cid(self.source_cid, "source_ref.source_cid", codec="raw"),
        )
        object.__setattr__(
            self,
            "source_uri",
            _string(self.source_uri, "source_ref.source_uri", allow_blank=True),
        )
        object.__setattr__(
            self,
            "source_revision",
            _string(
                self.source_revision,
                "source_ref.source_revision",
                allow_blank=True,
            ),
        )
        start, end = _optional_span(self.start, self.end, "source_ref")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    def to_dict(self) -> dict[str, object]:
        return {
            "end": self.end,
            "ref_id": self.ref_id,
            "source_cid": self.source_cid,
            "source_revision": self.source_revision,
            "source_uri": self.source_uri,
            "start": self.start,
        }

    @classmethod
    def from_dict(cls, value: object) -> "BridgeSourceReference":
        if not isinstance(value, Mapping) or set(value) != {
            "end",
            "ref_id",
            "source_cid",
            "source_revision",
            "source_uri",
            "start",
        }:
            raise CanonicalContractError("source reference fields changed")
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class BridgeAssumption:
    """Caller-visible assumption retained with the typed bridge."""

    assumption_id: str
    statement: str
    source_ref_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "assumption_id",
            _string(self.assumption_id, "assumption.assumption_id"),
        )
        object.__setattr__(
            self,
            "statement",
            _string(self.statement, "assumption.statement"),
        )
        object.__setattr__(
            self,
            "source_ref_ids",
            _string_items(self.source_ref_ids, "assumption.source_ref_ids"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "assumption_id": self.assumption_id,
            "source_ref_ids": list(self.source_ref_ids),
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: object) -> "BridgeAssumption":
        if not isinstance(value, Mapping) or set(value) != {
            "assumption_id",
            "source_ref_ids",
            "statement",
        }:
            raise CanonicalContractError("assumption fields changed")
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class BridgeUnsupportedConstruct:
    """Explicit record that a required construct could not be faithfully carried."""

    construct_id: str
    code: str
    message: str
    disposition: UnsupportedDisposition = UnsupportedDisposition.EXPLICIT_PARTIAL
    family_id: str = ""
    source_cid: str | None = None
    start: int | None = None
    end: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "construct_id",
            _string(self.construct_id, "unsupported.construct_id"),
        )
        object.__setattr__(self, "code", _string(self.code, "unsupported.code"))
        object.__setattr__(self, "message", _string(self.message, "unsupported.message"))
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, UnsupportedDisposition, "unsupported.disposition"),
        )
        if self.family_id:
            object.__setattr__(
                self,
                "family_id",
                _bridge_family_id(self.family_id, "unsupported.family_id"),
            )
        else:
            object.__setattr__(self, "family_id", "")
        object.__setattr__(
            self,
            "source_cid",
            _optional_raw_cid(self.source_cid, "unsupported.source_cid"),
        )
        start, end = _optional_span(self.start, self.end, "unsupported")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "construct_id": self.construct_id,
            "disposition": self.disposition.value,
            "end": self.end,
            "family_id": self.family_id,
            "message": self.message,
            "source_cid": self.source_cid,
            "start": self.start,
        }

    @classmethod
    def from_dict(cls, value: object) -> "BridgeUnsupportedConstruct":
        if not isinstance(value, Mapping) or set(value) != {
            "code",
            "construct_id",
            "disposition",
            "end",
            "family_id",
            "message",
            "source_cid",
            "start",
        }:
            raise CanonicalContractError("unsupported construct fields changed")
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class BridgeView:
    """One existing-contract payload retained under its own schema identity."""

    name: str
    kind: BridgeRepresentationKind
    schema_id: str
    family_id: str
    payload: Mapping[str, object]
    payload_cid: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _string(self.name, "view.name"))
        object.__setattr__(
            self,
            "kind",
            _enum(self.kind, BridgeRepresentationKind, "view.kind"),
        )
        if self.kind is BridgeRepresentationKind.DOMAIN_LOGIC_SLICE:
            raise CanonicalContractError(
                "views cannot carry a domain_logic_slice kind; that role is the "
                "dedicated DomainLogicSlice projection, not a family view"
            )
        object.__setattr__(self, "schema_id", _string(self.schema_id, "view.schema_id"))
        object.__setattr__(self, "family_id", _bridge_family_id(self.family_id, "view.family_id"))
        object.__setattr__(self, "payload", _frozen_object(self.payload, "view.payload"))
        expected = cid_for_dag_json(_thaw_json(self.payload))
        if self.payload_cid:
            supplied = _cid(self.payload_cid, "view.payload_cid", codec="dag-json")
            if supplied != expected:
                raise CanonicalContractError("view.payload_cid does not match payload")
            object.__setattr__(self, "payload_cid", supplied)
        else:
            object.__setattr__(self, "payload_cid", expected)

    def to_dict(self) -> dict[str, object]:
        payload = _thaw_json(self.payload)
        assert isinstance(payload, dict)
        return {
            "family_id": self.family_id,
            "kind": self.kind.value,
            "name": self.name,
            "payload": payload,
            "payload_cid": self.payload_cid,
            "schema_id": self.schema_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> "BridgeView":
        if not isinstance(value, Mapping) or set(value) != {
            "family_id",
            "kind",
            "name",
            "payload",
            "payload_cid",
            "schema_id",
        }:
            raise CanonicalContractError("bridge view fields changed")
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class BridgeTraceRef:
    """Reference to an existing proof, tactic, counterexample, or translation trace."""

    kind: BridgeTraceKind
    trace_id: str
    trace_cid: str | None = None
    schema_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _enum(self.kind, BridgeTraceKind, "trace.kind"))
        object.__setattr__(self, "trace_id", _string(self.trace_id, "trace.trace_id"))
        object.__setattr__(
            self,
            "trace_cid",
            _optional_dag_cid(self.trace_cid, "trace.trace_cid"),
        )
        object.__setattr__(
            self,
            "schema_id",
            _string(self.schema_id, "trace.schema_id", allow_blank=True),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "schema_id": self.schema_id,
            "trace_cid": self.trace_cid,
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> "BridgeTraceRef":
        if not isinstance(value, Mapping) or set(value) != {
            "kind",
            "schema_id",
            "trace_cid",
            "trace_id",
        }:
            raise CanonicalContractError("trace reference fields changed")
        return cls(**value)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class DomainLogicSliceRole:
    """Family-preserving projection role; not a logic family and not a family AST.

    A projected slice references an existing family payload by CID and member
    identifiers.  It never renames that payload into a DomainLogicSlice family.
    When no faithful projection exists, the role is explicitly unsupported.
    """

    disposition: ConstructDisposition
    family_id: str
    source_view: str = ""
    source_schema_id: str = ""
    source_payload_cid: str | None = None
    member_ids: tuple[str, ...] = ()
    projected_payload_cid: str | None = None
    unsupported: BridgeUnsupportedConstruct | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, ConstructDisposition, "slice.disposition"),
        )
        object.__setattr__(self, "family_id", _bridge_family_id(self.family_id, "slice.family_id"))
        object.__setattr__(
            self,
            "source_view",
            _string(self.source_view, "slice.source_view", allow_blank=True),
        )
        object.__setattr__(
            self,
            "source_schema_id",
            _string(self.source_schema_id, "slice.source_schema_id", allow_blank=True),
        )
        object.__setattr__(
            self,
            "source_payload_cid",
            _optional_dag_cid(self.source_payload_cid, "slice.source_payload_cid"),
        )
        object.__setattr__(
            self,
            "member_ids",
            _string_items(self.member_ids, "slice.member_ids"),
        )
        object.__setattr__(
            self,
            "projected_payload_cid",
            _optional_dag_cid(
                self.projected_payload_cid,
                "slice.projected_payload_cid",
            ),
        )
        if self.unsupported is not None and not isinstance(
            self.unsupported, BridgeUnsupportedConstruct
        ):
            if isinstance(self.unsupported, Mapping):
                object.__setattr__(
                    self,
                    "unsupported",
                    BridgeUnsupportedConstruct.from_dict(self.unsupported),
                )
            else:
                raise CanonicalContractError(
                    "slice.unsupported must be BridgeUnsupportedConstruct or None"
                )
        if self.disposition is ConstructDisposition.UNSUPPORTED:
            if self.unsupported is None:
                raise CanonicalContractError(
                    "unsupported DomainLogicSlice role requires an explicit record"
                )
            if self.projected_payload_cid is not None:
                raise CanonicalContractError(
                    "unsupported DomainLogicSlice role cannot carry a projection CID"
                )
        elif self.disposition is ConstructDisposition.REPRESENTED:
            raise CanonicalContractError(
                "DomainLogicSlice cannot be fully represented; project as "
                "explicit_partial or retain it as unsupported"
            )
        else:
            if not self.source_view or self.source_payload_cid is None:
                raise CanonicalContractError(
                    "projected DomainLogicSlice role requires a source view and payload CID"
                )
            expected = cid_for_dag_json(self.projection_payload())
            if self.projected_payload_cid is None:
                object.__setattr__(self, "projected_payload_cid", expected)
            elif self.projected_payload_cid != expected:
                raise CanonicalContractError(
                    "slice.projected_payload_cid does not match the projection"
                )

    def projection_payload(self) -> dict[str, object]:
        """Return the reference-only projection; never a renamed family AST."""

        return {
            "family_id": self.family_id,
            "member_ids": list(self.member_ids),
            "slice_kind": BridgeRepresentationKind.DOMAIN_LOGIC_SLICE.value,
            "source_payload_cid": self.source_payload_cid,
            "source_schema_id": self.source_schema_id,
            "source_view": self.source_view,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "disposition": self.disposition.value,
            "family_id": self.family_id,
            "member_ids": list(self.member_ids),
            "projected_payload_cid": self.projected_payload_cid,
            "source_payload_cid": self.source_payload_cid,
            "source_schema_id": self.source_schema_id,
            "source_view": self.source_view,
            "unsupported": None if self.unsupported is None else self.unsupported.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> "DomainLogicSliceRole":
        if not isinstance(value, Mapping) or set(value) != {
            "disposition",
            "family_id",
            "member_ids",
            "projected_payload_cid",
            "source_payload_cid",
            "source_schema_id",
            "source_view",
            "unsupported",
        }:
            raise CanonicalContractError("DomainLogicSlice role fields changed")
        return cls(**value)  # type: ignore[arg-type]


def _bridge_source_references(value: object) -> tuple[BridgeSourceReference, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise CanonicalContractError("source_references must be an array")
    items = tuple(
        item if isinstance(item, BridgeSourceReference) else BridgeSourceReference.from_dict(item)
        for item in value
    )
    return tuple(sorted(items, key=lambda item: (item.ref_id, item.source_cid)))


def _bridge_assumptions(value: object) -> tuple[BridgeAssumption, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise CanonicalContractError("assumptions must be an array")
    items = tuple(
        item if isinstance(item, BridgeAssumption) else BridgeAssumption.from_dict(item)
        for item in value
    )
    return tuple(sorted(items, key=lambda item: item.assumption_id))


def _bridge_unsupported(value: object) -> tuple[BridgeUnsupportedConstruct, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise CanonicalContractError("unsupported_constructs must be an array")
    items = tuple(
        item
        if isinstance(item, BridgeUnsupportedConstruct)
        else BridgeUnsupportedConstruct.from_dict(item)
        for item in value
    )
    return tuple(
        sorted(
            items,
            key=lambda item: (item.construct_id, item.code, item.message),
        )
    )


def _bridge_views(value: object) -> Mapping[str, BridgeView]:
    if not isinstance(value, Mapping):
        raise CanonicalContractError("views must be an object")
    views: dict[str, BridgeView] = {}
    for name, item in value.items():
        view = item if isinstance(item, BridgeView) else BridgeView.from_dict(item)
        if view.name != name:
            raise CanonicalContractError("view name does not match views map key")
        views[name] = view
    return MappingProxyType(dict(sorted(views.items())))


def _bridge_trace_refs(value: object) -> tuple[BridgeTraceRef, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise CanonicalContractError("trace_refs must be an array")
    items = tuple(
        item if isinstance(item, BridgeTraceRef) else BridgeTraceRef.from_dict(item)
        for item in value
    )
    return tuple(sorted(items, key=lambda item: (item.kind.value, item.trace_id)))


def _bridge_dispositions(value: object) -> Mapping[str, ConstructDisposition]:
    if not isinstance(value, Mapping):
        raise CanonicalContractError("construct_dispositions must be an object")
    dispositions: dict[str, ConstructDisposition] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise CanonicalContractError("construct_dispositions keys must be strings")
        dispositions[key] = _enum(  # type: ignore[assignment]
            item,
            ConstructDisposition,
            f"construct_dispositions.{key}",
        )
    return MappingProxyType(dict(sorted(dispositions.items())))


def _default_unsupported(
    construct: RequiredBridgeConstruct,
    *,
    family_id: str = "",
) -> BridgeUnsupportedConstruct:
    return BridgeUnsupportedConstruct(
        construct_id=construct.value,
        code=f"gap.{construct.value}",
        message=_DEFAULT_UNSUPPORTED_CONSTRUCT_MESSAGES[construct.value],
        disposition=UnsupportedDisposition.EXPLICIT_PARTIAL,
        family_id=family_id,
    )


def _slice_projection(
    *,
    family_id: str,
    view: BridgeView,
    member_ids: Sequence[str] = (),
) -> DomainLogicSliceRole:
    return DomainLogicSliceRole(
        disposition=ConstructDisposition.EXPLICIT_PARTIAL,
        family_id=family_id,
        source_view=view.name,
        source_schema_id=view.schema_id,
        source_payload_cid=view.payload_cid,
        member_ids=tuple(member_ids),
        unsupported=BridgeUnsupportedConstruct(
            construct_id="domain_logic_slice.family",
            code="gap.domain_logic_slice",
            message=_DEFAULT_UNSUPPORTED_CONSTRUCT_MESSAGES[
                RequiredBridgeConstruct.DOMAIN_LOGIC_SLICE.value
            ],
            disposition=UnsupportedDisposition.EXPLICIT_PARTIAL,
            family_id=family_id,
        ),
    )


def infer_slice_member_ids(payload: Mapping[str, object]) -> tuple[str, ...]:
    """Extract stable member identifiers from an existing family payload."""

    members: list[str] = []
    rules = payload.get("rules")
    if isinstance(rules, Sequence) and not isinstance(rules, (str, bytes, bytearray)):
        for item in rules:
            if isinstance(item, Mapping):
                try:
                    members.append(CanonicalRule.from_dict(item).rule_cid)
                except CanonicalContractError:
                    continue
    formulas = payload.get("formulas")
    if isinstance(formulas, Sequence) and not isinstance(formulas, (str, bytes, bytearray)):
        for item in formulas:
            if isinstance(item, Mapping):
                formula_id = item.get("formula_id") or item.get("id")
                if isinstance(formula_id, str) and formula_id.strip():
                    members.append(formula_id)
    views = payload.get("views")
    if isinstance(views, Mapping):
        members.extend(str(name) for name in views)
    return tuple(sorted(set(members)))


@dataclass(frozen=True, slots=True)
class CanonicalTypedBridge:
    """Versioned composition of existing typed contracts.

    CanonicalRoundTripIR, FormalizationArtifact, and LegalIRDocument remain
    distinct views.  Family identity is retained.  DomainLogicSlice is a
    projection role, never a new logic family.
    """

    family_identity: BridgeFamilyIdentity
    source_references: tuple[BridgeSourceReference, ...] = ()
    assumptions: tuple[BridgeAssumption, ...] = ()
    provenance: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))
    unsupported_constructs: tuple[BridgeUnsupportedConstruct, ...] = ()
    views: Mapping[str, BridgeView] = field(default_factory=lambda: MappingProxyType({}))
    trace_refs: tuple[BridgeTraceRef, ...] = ()
    domain_logic_slice: DomainLogicSliceRole | None = None
    construct_dispositions: Mapping[str, ConstructDisposition] = field(
        default_factory=lambda: MappingProxyType({})
    )
    adapter_name: str = ""
    metadata: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not isinstance(self.family_identity, BridgeFamilyIdentity):
            if isinstance(self.family_identity, Mapping):
                object.__setattr__(
                    self,
                    "family_identity",
                    BridgeFamilyIdentity.from_dict(self.family_identity),
                )
            else:
                raise CanonicalContractError(
                    "family_identity must be BridgeFamilyIdentity"
                )
        object.__setattr__(
            self,
            "source_references",
            _bridge_source_references(self.source_references),
        )
        object.__setattr__(self, "assumptions", _bridge_assumptions(self.assumptions))
        object.__setattr__(self, "provenance", _frozen_object(self.provenance, "provenance"))
        object.__setattr__(
            self,
            "unsupported_constructs",
            _bridge_unsupported(self.unsupported_constructs),
        )
        object.__setattr__(self, "views", _bridge_views(self.views))
        object.__setattr__(self, "trace_refs", _bridge_trace_refs(self.trace_refs))
        if self.domain_logic_slice is not None and not isinstance(
            self.domain_logic_slice, DomainLogicSliceRole
        ):
            if isinstance(self.domain_logic_slice, Mapping):
                object.__setattr__(
                    self,
                    "domain_logic_slice",
                    DomainLogicSliceRole.from_dict(self.domain_logic_slice),
                )
            else:
                raise CanonicalContractError(
                    "domain_logic_slice must be DomainLogicSliceRole or None"
                )
        if self.domain_logic_slice is None:
            raise CanonicalContractError(
                "domain_logic_slice must be projected or explicitly unsupported"
            )
        if self.domain_logic_slice.family_id != self.family_identity.family_id:
            raise CanonicalContractError(
                "DomainLogicSlice role family_id must match envelope family identity"
            )
        object.__setattr__(
            self,
            "construct_dispositions",
            _bridge_dispositions(self.construct_dispositions),
        )
        object.__setattr__(
            self,
            "adapter_name",
            _string(self.adapter_name, "adapter_name", allow_blank=True),
        )
        object.__setattr__(self, "metadata", _frozen_object(self.metadata, "metadata"))
        for view in self.views.values():
            if view.family_id != self.family_identity.family_id and view.kind not in {
                BridgeRepresentationKind.FAMILY_EXTENSION,
                BridgeRepresentationKind.TRACE,
            }:
                raise CanonicalContractError(
                    f"view {view.name!r} family_id {view.family_id!r} collapses or "
                    "cross-aliases the envelope family identity"
                )
        expected = self._expected_dispositions()
        if dict(self.construct_dispositions) != expected:
            raise CanonicalContractError("construct_dispositions do not match envelope contents")
        self._validate_construct_coverage()

    def _expected_dispositions(self) -> dict[str, ConstructDisposition]:
        dispositions: dict[str, ConstructDisposition] = {
            RequiredBridgeConstruct.FAMILY_IDENTITY.value: ConstructDisposition.REPRESENTED,
            RequiredBridgeConstruct.SOURCE_REFERENCES.value: (
                ConstructDisposition.REPRESENTED
            ),
            RequiredBridgeConstruct.ASSUMPTIONS.value: ConstructDisposition.REPRESENTED,
            RequiredBridgeConstruct.PROVENANCE.value: ConstructDisposition.REPRESENTED,
            RequiredBridgeConstruct.UNSUPPORTED_CONSTRUCTS.value: (
                ConstructDisposition.REPRESENTED
            ),
        }
        if self.domain_logic_slice is None:
            dispositions[RequiredBridgeConstruct.DOMAIN_LOGIC_SLICE.value] = (
                ConstructDisposition.UNSUPPORTED
            )
        else:
            dispositions[RequiredBridgeConstruct.DOMAIN_LOGIC_SLICE.value] = (
                self.domain_logic_slice.disposition
            )
        for construct in _CONSTRUCT_VIEW_NAMES:
            dispositions[construct] = (
                ConstructDisposition.REPRESENTED
                if _view_represents_construct(construct, self.views)
                else ConstructDisposition.UNSUPPORTED
            )
        extension_views = [
            view
            for view in self.views.values()
            if view.kind is BridgeRepresentationKind.FAMILY_EXTENSION
            or view.name not in CORE_BRIDGE_VIEW_NAMES
        ]
        dispositions[RequiredBridgeConstruct.FAMILY_EXTENSIONS.value] = (
            ConstructDisposition.REPRESENTED
            if extension_views
            else ConstructDisposition.UNSUPPORTED
        )
        trace_kinds = {item.kind.value for item in self.trace_refs}
        for construct, kind in _CONSTRUCT_TRACE_KINDS.items():
            dispositions[construct] = (
                ConstructDisposition.REPRESENTED
                if kind in trace_kinds
                else ConstructDisposition.UNSUPPORTED
            )
        return dict(sorted(dispositions.items()))

    def _validate_construct_coverage(self) -> None:
        required = {item.value for item in RequiredBridgeConstruct}
        present = set(self.construct_dispositions)
        if present != required:
            missing = ", ".join(sorted(required - present)) or "none"
            extra = ", ".join(sorted(present - required)) or "none"
            raise CanonicalContractError(
                f"construct catalog mismatch; missing={missing}; extra={extra}"
            )
        unsupported_ids = {item.construct_id for item in self.unsupported_constructs}
        for construct, disposition in self.construct_dispositions.items():
            if disposition is ConstructDisposition.UNSUPPORTED and construct not in {
                RequiredBridgeConstruct.FAMILY_IDENTITY.value,
                RequiredBridgeConstruct.SOURCE_REFERENCES.value,
                RequiredBridgeConstruct.ASSUMPTIONS.value,
                RequiredBridgeConstruct.PROVENANCE.value,
                RequiredBridgeConstruct.UNSUPPORTED_CONSTRUCTS.value,
            }:
                if construct not in unsupported_ids and not (
                    construct == RequiredBridgeConstruct.DOMAIN_LOGIC_SLICE.value
                    and self.domain_logic_slice is not None
                    and self.domain_logic_slice.unsupported is not None
                ):
                    raise CanonicalContractError(
                        f"unsupported construct {construct!r} lacks an explicit record"
                    )

    def identity_payload(self) -> dict[str, object]:
        return {
            "adapter_name": self.adapter_name,
            "assumptions": [item.to_dict() for item in self.assumptions],
            "construct_dispositions": {
                key: value.value for key, value in self.construct_dispositions.items()
            },
            "domain_logic_slice": self.domain_logic_slice.to_dict(),
            "family_identity": self.family_identity.to_dict(),
            "interface": CANONICAL_TYPED_BRIDGE_INTERFACE,
            "metadata": _thaw_json(self.metadata),
            "provenance": _thaw_json(self.provenance),
            "schema_version": CANONICAL_TYPED_BRIDGE_SCHEMA_VERSION,
            "source_references": [item.to_dict() for item in self.source_references],
            "trace_refs": [item.to_dict() for item in self.trace_refs],
            "unsupported_constructs": [item.to_dict() for item in self.unsupported_constructs],
            "views": {name: view.to_dict() for name, view in self.views.items()},
        }

    @property
    def bridge_cid(self) -> str:
        return cid_for_dag_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "bridge_cid": self.bridge_cid,
            "bridge_cid_codec": "dag-json",
            "bridge_cid_scope": "identity_payload",
        }

    @classmethod
    def from_dict(cls, value: object) -> "CanonicalTypedBridge":
        if not isinstance(value, Mapping) or set(value) != {
            "adapter_name",
            "assumptions",
            "bridge_cid",
            "bridge_cid_codec",
            "bridge_cid_scope",
            "construct_dispositions",
            "domain_logic_slice",
            "family_identity",
            "interface",
            "metadata",
            "provenance",
            "schema_version",
            "source_references",
            "trace_refs",
            "unsupported_constructs",
            "views",
        }:
            raise CanonicalContractError("typed bridge fields changed")
        if value["interface"] != CANONICAL_TYPED_BRIDGE_INTERFACE:
            raise CanonicalContractError("typed bridge interface changed")
        if value["schema_version"] != CANONICAL_TYPED_BRIDGE_SCHEMA_VERSION:
            raise CanonicalContractError("typed bridge schema version changed")
        if (
            value["bridge_cid_codec"] != "dag-json"
            or value["bridge_cid_scope"] != "identity_payload"
        ):
            raise CanonicalContractError("typed bridge CID contract changed")
        bridge = cls(
            family_identity=BridgeFamilyIdentity.from_dict(value["family_identity"]),
            source_references=tuple(
                BridgeSourceReference.from_dict(item)
                for item in value["source_references"]  # type: ignore[union-attr]
            ),
            assumptions=tuple(
                BridgeAssumption.from_dict(item)
                for item in value["assumptions"]  # type: ignore[union-attr]
            ),
            provenance=value["provenance"],  # type: ignore[arg-type]
            unsupported_constructs=tuple(
                BridgeUnsupportedConstruct.from_dict(item)
                for item in value["unsupported_constructs"]  # type: ignore[union-attr]
            ),
            views={
                name: BridgeView.from_dict(item)
                for name, item in value["views"].items()  # type: ignore[union-attr]
            },
            trace_refs=tuple(
                BridgeTraceRef.from_dict(item)
                for item in value["trace_refs"]  # type: ignore[union-attr]
            ),
            domain_logic_slice=DomainLogicSliceRole.from_dict(value["domain_logic_slice"]),
            construct_dispositions=value["construct_dispositions"],  # type: ignore[arg-type]
            adapter_name=value["adapter_name"],  # type: ignore[arg-type]
            metadata=value["metadata"],  # type: ignore[arg-type]
        )
        if _cid(value["bridge_cid"], "bridge_cid", codec="dag-json") != bridge.bridge_cid:
            raise CanonicalContractError("bridge_cid does not match typed bridge")
        return bridge

    @classmethod
    def compose(
        cls,
        *,
        family_id: str,
        authority_schema: str,
        views: Mapping[str, BridgeView] | Sequence[BridgeView] = (),
        source_references: Sequence[BridgeSourceReference] = (),
        assumptions: Sequence[BridgeAssumption] = (),
        provenance: Mapping[str, object] | None = None,
        unsupported_constructs: Sequence[BridgeUnsupportedConstruct] = (),
        trace_refs: Sequence[BridgeTraceRef] = (),
        domain_logic_slice: DomainLogicSliceRole | None = None,
        adapter_name: str = "",
        metadata: Mapping[str, object] | None = None,
        payload_cid: str | None = None,
        representation_kind: BridgeRepresentationKind = BridgeRepresentationKind.LOGIC_FAMILY,
    ) -> "CanonicalTypedBridge":
        """Build a fail-closed envelope that accounts for every required construct."""

        if isinstance(views, Mapping):
            view_map = {
                name: (view if isinstance(view, BridgeView) else BridgeView.from_dict(view))
                for name, view in views.items()
            }
        else:
            view_map = {}
            for view in views:
                item = view if isinstance(view, BridgeView) else BridgeView.from_dict(view)
                view_map[item.name] = item
        if not view_map:
            raise CanonicalContractError("typed bridge compose requires at least one view")
        authority_view = (
            view_map.get("canonical_roundtrip_ir")
            or view_map.get("formalization_artifact")
            or view_map.get("legal_ir_document")
            or view_map.get("logic_family")
            or next(iter(view_map.values()))
        )
        family_identity = BridgeFamilyIdentity(
            family_id=family_id,
            authority_schema=authority_schema,
            payload_cid=payload_cid or authority_view.payload_cid,
            representation_kind=representation_kind,
        )
        if domain_logic_slice is None:
            domain_logic_slice = _slice_projection(
                family_id=family_id,
                view=authority_view,
                member_ids=infer_slice_member_ids(authority_view.payload),
            )
        unsupported = {
            item.construct_id: item
            for item in (
                item
                if isinstance(item, BridgeUnsupportedConstruct)
                else BridgeUnsupportedConstruct.from_dict(item)
                for item in unsupported_constructs
            )
        }
        for construct in _CONSTRUCT_VIEW_NAMES:
            if (
                not _view_represents_construct(construct, view_map)
                and construct not in unsupported
            ):
                unsupported[construct] = _default_unsupported(
                    RequiredBridgeConstruct(construct),
                    family_id=family_id,
                )
        extension_present = any(
            view.kind is BridgeRepresentationKind.FAMILY_EXTENSION
            or view.name not in CORE_BRIDGE_VIEW_NAMES
            for view in view_map.values()
        )
        if (
            not extension_present
            and RequiredBridgeConstruct.FAMILY_EXTENSIONS.value not in unsupported
        ):
            unsupported[RequiredBridgeConstruct.FAMILY_EXTENSIONS.value] = (
                _default_unsupported(
                    RequiredBridgeConstruct.FAMILY_EXTENSIONS,
                    family_id=family_id,
                )
            )
        trace_kinds = {
            (item.kind.value if isinstance(item, BridgeTraceRef) else str(item["kind"]))
            for item in trace_refs
        }
        for construct, kind in _CONSTRUCT_TRACE_KINDS.items():
            if kind not in trace_kinds and construct not in unsupported:
                unsupported[construct] = _default_unsupported(
                    RequiredBridgeConstruct(construct),
                    family_id=family_id,
                )
        if (
            domain_logic_slice.disposition is ConstructDisposition.UNSUPPORTED
            and RequiredBridgeConstruct.DOMAIN_LOGIC_SLICE.value not in unsupported
        ):
            record = domain_logic_slice.unsupported or _default_unsupported(
                RequiredBridgeConstruct.DOMAIN_LOGIC_SLICE,
                family_id=family_id,
            )
            unsupported[RequiredBridgeConstruct.DOMAIN_LOGIC_SLICE.value] = record
        dispositions = {
            RequiredBridgeConstruct.FAMILY_IDENTITY.value: (
                ConstructDisposition.REPRESENTED
            ),
            RequiredBridgeConstruct.SOURCE_REFERENCES.value: (
                ConstructDisposition.REPRESENTED
            ),
            RequiredBridgeConstruct.ASSUMPTIONS.value: ConstructDisposition.REPRESENTED,
            RequiredBridgeConstruct.PROVENANCE.value: ConstructDisposition.REPRESENTED,
            RequiredBridgeConstruct.UNSUPPORTED_CONSTRUCTS.value: (
                ConstructDisposition.REPRESENTED
            ),
            RequiredBridgeConstruct.DOMAIN_LOGIC_SLICE.value: (
                domain_logic_slice.disposition
            ),
        }
        for construct in _CONSTRUCT_VIEW_NAMES:
            dispositions[construct] = (
                ConstructDisposition.REPRESENTED
                if _view_represents_construct(construct, view_map)
                else ConstructDisposition.UNSUPPORTED
            )
        dispositions[RequiredBridgeConstruct.FAMILY_EXTENSIONS.value] = (
            ConstructDisposition.REPRESENTED
            if extension_present
            else ConstructDisposition.UNSUPPORTED
        )
        for construct, kind in _CONSTRUCT_TRACE_KINDS.items():
            dispositions[construct] = (
                ConstructDisposition.REPRESENTED
                if kind in trace_kinds
                else ConstructDisposition.UNSUPPORTED
            )
        return cls(
            family_identity=family_identity,
            source_references=tuple(source_references),
            assumptions=tuple(assumptions),
            provenance=provenance or {},
            unsupported_constructs=tuple(unsupported.values()),
            views=view_map,
            trace_refs=tuple(trace_refs),
            domain_logic_slice=domain_logic_slice,
            construct_dispositions=dispositions,
            adapter_name=adapter_name,
            metadata=metadata or {},
        )


__all__ = [
    "CANONICAL_DESIGN_GATE_CID",
    "CANONICAL_PARITY_POLICY_CID",
    "CANONICAL_ROUNDTRIP_CONTRACTS_INTERFACE",
    "CANONICAL_ROUNDTRIP_IR_INTERFACE",
    "CANONICAL_ROUNDTRIP_IR_SCHEMA_VERSION",
    "CANONICAL_ROUNDTRIP_PARITY_POLICY_INTERFACE",
    "CANONICAL_ROUNDTRIP_PARITY_POLICY_SCHEMA",
    "CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE",
    "CANONICAL_STRUCTURED_TEXT_DECOMPILER_INTERFACE",
    "CANONICAL_TYPED_BRIDGE_CONFORMANCE_INTERFACE",
    "CANONICAL_TYPED_BRIDGE_INTERFACE",
    "CANONICAL_TYPED_BRIDGE_MIGRATION_INTERFACE",
    "CANONICAL_TYPED_BRIDGE_SCHEMA_VERSION",
    "CORE_BRIDGE_VIEW_NAMES",
    "FORBIDDEN_BRIDGE_FAMILY_IDS",
    "IMPLEMENTATION_REPRESENTATIVE_ARM_ID",
    "REGISTERED_BRIDGE_FAMILY_IDS",
    "IMPLEMENTATION_REPRESENTATIVE_ARM_IDENTITY_CID",
    "REPLACEMENT_GATE_CID",
    "REPLACEMENT_REPORT_CID",
    "SELECTABLE_ARM_IDS",
    "SELECTED_CONSTRUCTOR_ADAPTER_RAW_CID",
    "SELECTED_CONSTRUCTOR_INTERFACE",
    "SELECTED_COORDINATE_RUNNER_RAW_CID",
    "SELECTED_REALIZER_ADAPTER_RAW_CID",
    "SELECTED_REALIZER_INTERFACE",
    "SELECTION_BASIS",
    "SOURCE_WITHHELD_DECOMPILER_CONFIG",
    "SOURCE_WITHHELD_DECOMPILER_CONFIG_CID",
    "SOURCE_WITHHELD_RENDERING_SPEC_CID",
    "SRT014_GATE_CID",
    "SRT014_REMEDIATION_MANIFEST_CID",
    "SRT014_REPORT_CID",
    "TIED_SELECTIVE_ARM_IDENTITY_CID",
    "CanonicalContractError",
    "CanonicalAtomVocabulary",
    "CanonicalDiagnostic",
    "CanonicalError",
    "CanonicalErrorCode",
    "CanonicalParityPolicy",
    "CanonicalRoundTripIR",
    "CanonicalRule",
    "CanonicalStructuredTextCompiler",
    "CanonicalStructuredTextDecompiler",
    "CanonicalTypedBridge",
    "CompilerRequest",
    "CompilerResult",
    "ComponentTrace",
    "ConstructDisposition",
    "DecompilerRequest",
    "DecompilerResult",
    "DiagnosticSeverity",
    "DomainLogicSliceRole",
    "BridgeAssumption",
    "BridgeFamilyIdentity",
    "BridgeRepresentationKind",
    "BridgeSourceReference",
    "BridgeTraceKind",
    "BridgeTraceRef",
    "BridgeUnsupportedConstruct",
    "BridgeView",
    "OperationStatus",
    "RequiredBridgeConstruct",
    "SourceMapEntry",
    "UnsupportedDisposition",
    "UnsupportedSemantic",
    "canonical_ir_schema_path",
    "infer_slice_member_ids",
    "load_canonical_ir_schema",
    "load_parity_policy",
]
