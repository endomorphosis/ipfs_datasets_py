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


CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE: Final = (
    "CanonicalStructuredTextCompiler@1"
)
CANONICAL_STRUCTURED_TEXT_DECOMPILER_INTERFACE: Final = (
    "CanonicalStructuredTextDecompiler@1"
)
CANONICAL_ROUNDTRIP_CONTRACTS_INTERFACE: Final = (
    "CanonicalRoundTripContracts@1"
)
CANONICAL_ROUNDTRIP_IR_INTERFACE: Final = "CanonicalRoundTripIR@1"
CANONICAL_ROUNDTRIP_IR_SCHEMA_VERSION: Final = (
    "ipfs-datasets.canonical-roundtrip-ir.v1"
)
CANONICAL_ROUNDTRIP_PARITY_POLICY_INTERFACE: Final = (
    "CanonicalRoundTripParityPolicy@1"
)
CANONICAL_ROUNDTRIP_PARITY_POLICY_SCHEMA: Final = (
    "ipfs-datasets.semantic-roundtrip-canonical-parity-policy.v1"
)

# Immutable benchmark-to-design lineage, revalidated by SRT-027.
SRT014_REPORT_CID: Final = (
    "baguqeerakqgerwv6npdlqpgrc3bjzuxqog3hiouey3c4giw5vkdgk2jhfbpq"
)
SRT014_GATE_CID: Final = (
    "baguqeeraa7vbts26rxvqujbvgvgplq4xrprcebufol5qqmstc6cbrac2rthq"
)
SRT014_REMEDIATION_MANIFEST_CID: Final = (
    "baguqeerarr7ebjrzd3argtdekd7er3bqrnvhuzy2ogqzfi7h5nv37dbea52a"
)
REPLACEMENT_REPORT_CID: Final = (
    "baguqeeramdvshi4ynajkvsb72zncgcn2pgvklsglgxwea7za25lndnaf5cga"
)
REPLACEMENT_GATE_CID: Final = (
    "baguqeerawhggoyrnacv74kbuq3rhpmz4jikhr3tnv5uahpxcnpghfrwfj6jq"
)
CANONICAL_DESIGN_GATE_CID: Final = (
    "baguqeerab4top4ljgojms7f7p6y4ksdlivfwhyzxzhynnii4zbrfvw4mqtfq"
)
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
CANONICAL_PARITY_POLICY_CID: Final = (
    "baguqeera5g5z4yvncxbn3uk4ftqmnxxmmclwpnwjpdshiy52la2o5bzdk27a"
)

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
        raise CanonicalContractError(
            f"{field} exceeds the {maximum} character bound"
        )
    if not allow_blank and not value.strip():
        raise CanonicalContractError(f"{field} must be nonblank")
    return value


def _cid(value: object, field: str, *, codec: str) -> str:
    try:
        return validate_cid(value, codecs=(codec,))
    except (TypeError, ValueError) as exc:
        raise CanonicalContractError(
            f"{field} must be a canonical {codec} CIDv1"
        ) from exc


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
            raise CanonicalContractError(
                f"{field} contains a non-finite number"
            )
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalContractError(f"{field} keys must be strings")
            frozen[key] = _freeze_json(item, f"{field}.{key}", depth + 1)
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return tuple(
            _freeze_json(item, f"{field}[{index}]", depth + 1)
            for index, item in enumerate(value)
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
        raise CanonicalContractError(
            f"{field} exceeds the {MAX_CONFIG_BYTES} byte bound"
        )
    return result


def _string_items(
    value: object,
    field: str,
    *,
    maximum: int = MAX_QUALIFIERS_PER_FACET,
) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        raise CanonicalContractError(f"{field} must be a string array")
    if len(value) > maximum:
        raise CanonicalContractError(f"{field} exceeds the {maximum} item bound")
    return tuple(
        sorted(
            {
                _string(item, f"{field}[{index}]")
                for index, item in enumerate(value)
            }
        )
    )


def _enum(value: object, enum_type: type[Enum], field: str) -> Enum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise CanonicalContractError(f"{field} is invalid") from exc


def _normalized_key(key: object) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "_",
        re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key).strip()),
        flags=re.IGNORECASE,
    ).strip("_").lower()


def _reject_source_channels(value: object, path: str = "config") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _normalized_key(key) in _FORBIDDEN_DECOMPILER_KEYS:
                raise CanonicalContractError(
                    f"decompiler request may not contain {path}.{key}"
                )
            _reject_source_channels(item, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
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
        object.__setattr__(
            self, "rule_cid", _cid(self.rule_cid, "rule_cid", codec="dag-json")
        )
        object.__setattr__(
            self, "source_cid", _cid(self.source_cid, "source_cid", codec="raw")
        )
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
            raise CanonicalContractError(
                "source-map offsets must form a nonempty half-open span"
            )

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
        if not isinstance(self.rules, Sequence) or isinstance(
            self.rules, (str, bytes, bytearray)
        ):
            raise CanonicalContractError("rules must be an array")
        if not 0 < len(self.rules) <= MAX_RULES:
            raise CanonicalContractError(
                f"rules must contain between 1 and {MAX_RULES} entries"
            )
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
    details: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "code", _enum(self.code, CanonicalErrorCode, "error.code")
        )
        _string(self.message, "error.message")
        if not isinstance(self.retryable, bool):
            raise CanonicalContractError("error.retryable must be boolean")
        object.__setattr__(
            self, "details", _frozen_object(self.details, "error.details")
        )

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
            raise CanonicalContractError(
                "deterministic trace cannot carry a model receipt"
            )

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
    config: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )

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
                raise CanonicalContractError(
                    "atom_vocabulary must be CanonicalAtomVocabulary"
                )
        if not isinstance(self.allow_explicit_partial, bool):
            raise CanonicalContractError(
                "allow_explicit_partial must be boolean"
            )
        object.__setattr__(
            self, "config", _frozen_object(self.config, "config")
        )

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
        if value["request_cid_codec"] != "dag-json" or value[
            "request_cid_scope"
        ] != "identity_payload_with_source_cid":
            raise CanonicalContractError("compiler request CID contract changed")
        request = cls(
            source_text=value["source_text"],  # type: ignore[arg-type]
            request_id=value["request_id"],  # type: ignore[arg-type]
            atom_vocabulary=CanonicalAtomVocabulary.from_dict(
                value["atom_vocabulary"]
            ),
            policy_cid=value["policy_cid"],  # type: ignore[arg-type]
            allow_explicit_partial=value[  # type: ignore[arg-type]
                "allow_explicit_partial"
            ],
            config=value["config"],  # type: ignore[arg-type]
        )
        if _cid(value["source_cid"], "source_cid", codec="raw") != request.source_cid:
            raise CanonicalContractError("source_cid does not match source_text")
        if (
            _cid(value["request_cid"], "request_cid", codec="dag-json")
            != request.request_cid
        ):
            raise CanonicalContractError(
                "request_cid does not match compiler request"
            )
        return request


@dataclass(frozen=True, slots=True)
class DecompilerRequest:
    """Strict source-withheld request for canonical IR to natural language."""

    canonical_ir: CanonicalRoundTripIR
    request_id: str
    policy_cid: str = CANONICAL_PARITY_POLICY_CID
    config: Mapping[str, object] = field(
        default_factory=lambda: SOURCE_WITHHELD_DECOMPILER_CONFIG
    )

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_ir, CanonicalRoundTripIR):
            raise CanonicalContractError(
                "canonical_ir must be CanonicalRoundTripIR"
            )
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
        if (
            cid_for_dag_json(dict(frozen_config))
            != SOURCE_WITHHELD_DECOMPILER_CONFIG_CID
        ):
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
        if value["request_cid_codec"] != "dag-json" or value[
            "request_cid_scope"
        ] != "identity_payload_with_canonical_ir_cid":
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
            raise CanonicalContractError(
                "canonical_ir_cid does not match canonical_ir"
            )
        request = cls(
            canonical_ir=canonical_ir,
            request_id=value["request_id"],  # type: ignore[arg-type]
            policy_cid=value["policy_cid"],  # type: ignore[arg-type]
            config=value["config"],  # type: ignore[arg-type]
        )
        if (
            _cid(value["request_cid"], "request_cid", codec="dag-json")
            != request.request_cid
        ):
            raise CanonicalContractError(
                "request_cid does not match decompiler request"
            )
        return request


def _diagnostics(value: object) -> tuple[CanonicalDiagnostic, ...]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        raise CanonicalContractError("diagnostics must be an array")
    return tuple(
        item
        if isinstance(item, CanonicalDiagnostic)
        else CanonicalDiagnostic.from_dict(item)
        for item in value
    )


def _traces(value: object) -> tuple[ComponentTrace, ...]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
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
    provenance: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )
    diagnostics: tuple[CanonicalDiagnostic, ...] = ()
    component_trace: tuple[ComponentTrace, ...] = ()
    error: CanonicalError | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "status", _enum(self.status, OperationStatus, "status")
        )
        object.__setattr__(
            self,
            "request_cid",
            _cid(self.request_cid, "request_cid", codec="dag-json"),
        )
        if self.canonical_ir is not None and not isinstance(
            self.canonical_ir, CanonicalRoundTripIR
        ):
            raise CanonicalContractError(
                "canonical_ir must be CanonicalRoundTripIR or None"
            )
        entries = tuple(
            entry
            if isinstance(entry, SourceMapEntry)
            else SourceMapEntry.from_dict(entry)
            for entry in self.source_map
        )
        if self.canonical_ir is None and entries:
            raise CanonicalContractError(
                "source_map requires a canonical IR result"
            )
        if self.canonical_ir is not None:
            known_rule_cids = {
                rule.rule_cid for rule in self.canonical_ir.rules
            }
            if any(entry.rule_cid not in known_rule_cids for entry in entries):
                raise CanonicalContractError(
                    "source_map references a rule outside this IR"
                )
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
            item
            if isinstance(item, UnsupportedSemantic)
            else UnsupportedSemantic.from_dict(item)
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
        object.__setattr__(
            self, "component_trace", _traces(self.component_trace)
        )
        if self.error is not None and not isinstance(self.error, CanonicalError):
            raise CanonicalContractError("error must be CanonicalError or None")
        if self.status is OperationStatus.SUCCESS:
            if self.canonical_ir is None or self.error is not None:
                raise CanonicalContractError(
                    "successful compiler result requires IR and no error"
                )
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
            "canonical_ir": (
                None if self.canonical_ir is None else self.canonical_ir.to_dict()
            ),
            "canonical_ir_cid": (
                None if self.canonical_ir is None else self.canonical_ir.ir_cid
            ),
            "source_map_receipt": self.source_map_receipt(),
            "unsupported_semantics": [
                item.to_dict() for item in self.unsupported_semantics
            ],
            "provenance": _thaw_json(self.provenance),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "component_trace": [
                item.to_dict() for item in self.component_trace
            ],
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
        canonical_ir = (
            None if raw_ir is None else CanonicalRoundTripIR.from_dict(raw_ir)
        )
        if canonical_ir is None:
            if value["canonical_ir_cid"] is not None:
                raise CanonicalContractError(
                    "compiler result has CID without canonical IR"
                )
        elif (
            _cid(
                value["canonical_ir_cid"],
                "canonical_ir_cid",
                codec="dag-json",
            )
            != canonical_ir.ir_cid
        ):
            raise CanonicalContractError(
                "compiler result canonical_ir_cid does not match IR"
            )
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
            error=(
                None
                if raw_error is None
                else CanonicalError.from_dict(raw_error)
            ),
        )
        if result.source_map_receipt() != value["source_map_receipt"]:
            raise CanonicalContractError("source-map receipt does not match result")
        if (
            _cid(value["result_cid"], "result_cid", codec="dag-json")
            != result.result_cid
        ):
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
        object.__setattr__(
            self, "status", _enum(self.status, OperationStatus, "status")
        )
        object.__setattr__(
            self,
            "request_cid",
            _cid(self.request_cid, "request_cid", codec="dag-json"),
        )
        object.__setattr__(self, "diagnostics", _diagnostics(self.diagnostics))
        object.__setattr__(
            self, "component_trace", _traces(self.component_trace)
        )
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
                raise CanonicalContractError(
                    "text_cid does not match reconstructed text"
                )
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
            "component_trace": [
                item.to_dict() for item in self.component_trace
            ],
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
            error=(
                None
                if raw_error is None
                else CanonicalError.from_dict(raw_error)
            ),
        )
        if (
            _cid(value["result_cid"], "result_cid", codec="dag-json")
            != result.result_cid
        ):
            raise CanonicalContractError(
                "result_cid does not match decompiler result"
            )
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
            "implementation_representative_arm_id": (
                IMPLEMENTATION_REPRESENTATIVE_ARM_ID
            ),
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

    @property
    def configuration_cid(self) -> str:
        """Return the frozen measured compiler configuration CID."""

    def compile(self, request: CompilerRequest) -> CompilerResult:
        """Compile structured text or return an explicit abstention/failure."""


@runtime_checkable
class CanonicalStructuredTextDecompiler(Protocol):
    """Source-withheld structural interface for canonical IR realization."""

    @property
    def identity(self) -> str:
        """Return a frozen implementation/configuration identity."""

    @property
    def deterministic(self) -> bool:
        """Return whether the realizer is fully deterministic."""

    @property
    def uses_model(self) -> bool:
        """Return whether the realizer may invoke a learned model."""

    def decompile(self, request: DecompilerRequest) -> DecompilerResult:
        """Realize canonical IR without consulting its originating source."""


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
    "IMPLEMENTATION_REPRESENTATIVE_ARM_ID",
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
    "CompilerRequest",
    "CompilerResult",
    "ComponentTrace",
    "DecompilerRequest",
    "DecompilerResult",
    "DiagnosticSeverity",
    "OperationStatus",
    "SourceMapEntry",
    "UnsupportedDisposition",
    "UnsupportedSemantic",
    "canonical_ir_schema_path",
    "load_canonical_ir_schema",
    "load_parity_policy",
]
