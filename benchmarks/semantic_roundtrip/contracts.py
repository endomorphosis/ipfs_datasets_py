"""Core contracts for source-withheld semantic round-trip benchmarks.

The classes in this module are deliberately dependency-free.  They define the
only objects that may cross the constructor/realizer boundary; adapter-private
records remain outside these contracts.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final, Protocol, runtime_checkable


CANONICAL_RULE_IR_INTERFACE: Final = "CanonicalRuleIR@1"
ROUND_TRIP_CONSTRUCTOR_INTERFACE: Final = "RoundTripConstructor@1"
ROUND_TRIP_REALIZER_INTERFACE: Final = "RoundTripRealizer@1"
ROUND_TRIP_RESULT_INTERFACE: Final = "RoundTripResult@1"

RULE_FIELDS: Final = (
    "modality",
    "actor",
    "action",
    "object",
    "conditions",
    "exceptions",
    "temporal",
)
LIST_FIELDS: Final = ("conditions", "exceptions", "temporal")
VOCABULARY_FIELDS: Final = ("actors", "actions", "objects", "qualifiers")
MODALITIES: Final = frozenset({"O", "P", "F"})

MAX_RULES: Final = 16
MAX_LIST_ITEMS: Final = 8
MAX_VOCABULARY_ITEMS: Final = 256
MAX_ATOM_LENGTH: Final = 512
MAX_TEXT_LENGTH: Final = 1_000_000
MAX_CONFIG_BYTES: Final = 65_536
MAX_CONFIG_DEPTH: Final = 12

_REALIZER_PAYLOAD_FIELDS: Final = frozenset(
    {"canonical_ir", "allowed_atom_vocabulary", "config"}
)
_CONSTRUCTOR_PAYLOAD_FIELDS: Final = frozenset(
    {"source_text", "allowed_atom_vocabulary", "config"}
)
_FORBIDDEN_REALIZER_KEYS: Final = frozenset(
    {
        "source",
        "source_text",
        "source_excerpt",
        "source_document",
        "source_metadata",
        "source_cache_key",
        "source_cid",
        "source_hash",
        "t0",
        "gold",
        "gold_ir",
        "gold_rule_count",
        "native",
        "native_ir",
        "native_payload",
        "native_record",
        "native_metadata",
        "native_compiler_record",
        "native_constructor_record",
        "compiler_record",
        "constructor_payload",
        "constructor_record",
        "parse",
        "parse_tree",
        "private_payload",
        "hidden_fields",
        "prior_reconstruction",
        "outcome",
    }
)


class ContractError(ValueError):
    """Raised when a semantic round-trip boundary is violated."""


class ComponentStatus(str, Enum):
    """Terminal status of a constructor, realizer, or round-trip coordinate."""

    SUCCESS = "success"
    FAILED = "failed"


class FailureReason(str, Enum):
    """Frozen failure outcomes that receive loss one."""

    TIMEOUT = "timeout"
    EXCEPTION = "exception"
    RETRY_EXHAUSTED = "retry_exhausted"
    CAPABILITY_UNAVAILABLE = "post_schedule_capability_unavailable"
    MISSING_OUTPUT = "missing_output"
    INVALID_OUTPUT = "invalid_output"
    EMPTY_L1 = "empty_l1"
    BLANK_T1 = "blank_t1"
    EMPTY_L2 = "empty_l2"


def _clean_text(value: object, field: str, *, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field} must be a string")
    result = " ".join(value.strip().split())
    if not result and not allow_empty:
        raise ContractError(f"{field} must be nonempty")
    if len(result) > MAX_ATOM_LENGTH:
        raise ContractError(
            f"{field} exceeds the {MAX_ATOM_LENGTH} character bound"
        )
    return result


def _bounded_text(value: object, field: str, *, allow_blank: bool) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field} must be a string")
    if len(value) > MAX_TEXT_LENGTH:
        raise ContractError(
            f"{field} exceeds the {MAX_TEXT_LENGTH} character bound"
        )
    if not allow_blank and not value.strip():
        raise ContractError(f"{field} must be nonblank")
    return value


def _canonical_items(value: object, field: str) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
    ):
        raise ContractError(f"{field} must be a string array")
    if len(value) > MAX_LIST_ITEMS:
        raise ContractError(
            f"{field} exceeds the {MAX_LIST_ITEMS} item bound"
        )
    cleaned = {
        _clean_text(item, f"{field}[{index}]", allow_empty=True)
        for index, item in enumerate(value)
    }
    cleaned.discard("")
    return tuple(sorted(cleaned))


def _canonical_vocabulary_items(
    value: object, field: str
) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
    ):
        raise ContractError(f"{field} must be a string array")
    if len(value) > MAX_VOCABULARY_ITEMS:
        raise ContractError(
            f"{field} exceeds the {MAX_VOCABULARY_ITEMS} item bound"
        )
    cleaned = {
        _clean_text(item, f"{field}[{index}]", allow_empty=False)
        for index, item in enumerate(value)
    }
    return tuple(sorted(cleaned))


def _rule_key(rule: "CanonicalRule") -> tuple[object, ...]:
    return (
        rule.modality,
        rule.actor,
        rule.action,
        rule.object,
        rule.conditions,
        rule.exceptions,
        rule.temporal,
    )


def _freeze_json(value: object, field: str, depth: int = 0) -> object:
    if depth > MAX_CONFIG_DEPTH:
        raise ContractError(f"{field} exceeds maximum JSON depth")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractError(f"{field} must contain finite JSON numbers")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError(f"{field} keys must be strings")
            frozen[key] = _freeze_json(item, f"{field}.{key}", depth + 1)
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return tuple(
            _freeze_json(item, f"{field}[{index}]", depth + 1)
            for index, item in enumerate(value)
        )
    raise ContractError(f"{field} must contain only JSON values")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _frozen_config(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ContractError("config must be an object")
    frozen = _freeze_json(value, "config")
    assert isinstance(frozen, Mapping)
    encoded = json.dumps(
        _thaw_json(frozen),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    if len(encoded) > MAX_CONFIG_BYTES:
        raise ContractError(
            f"config exceeds the {MAX_CONFIG_BYTES} encoded byte bound"
        )
    return frozen


def _reject_forbidden_realizer_config(
    value: object, path: str = "config"
) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(
                r"[^a-z0-9]+",
                "_",
                re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key).strip()),
                flags=re.IGNORECASE,
            ).strip("_").lower()
            if normalized in _FORBIDDEN_REALIZER_KEYS:
                raise ContractError(
                    f"realizer payload may not contain {path}.{key}"
                )
            _reject_forbidden_realizer_config(item, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, item in enumerate(value):
            _reject_forbidden_realizer_config(item, f"{path}[{index}]")


@dataclass(frozen=True, slots=True)
class AllowedAtomVocabulary:
    """Immutable, corpus-frozen closed vocabulary visible to both components."""

    actors: tuple[str, ...]
    actions: tuple[str, ...]
    objects: tuple[str, ...]
    qualifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        for field in VOCABULARY_FIELDS:
            object.__setattr__(
                self,
                field,
                _canonical_vocabulary_items(getattr(self, field), field),
            )

    @classmethod
    def from_dict(cls, value: object) -> "AllowedAtomVocabulary":
        if not isinstance(value, Mapping) or set(value) != set(
            VOCABULARY_FIELDS
        ):
            raise ContractError(
                "allowed atom vocabulary must contain exactly "
                + ", ".join(VOCABULARY_FIELDS)
            )
        return cls(
            actors=value["actors"],  # type: ignore[arg-type]
            actions=value["actions"],  # type: ignore[arg-type]
            objects=value["objects"],  # type: ignore[arg-type]
            qualifiers=value["qualifiers"],  # type: ignore[arg-type]
        )

    def to_dict(self) -> dict[str, list[str]]:
        return {
            field: list(getattr(self, field)) for field in VOCABULARY_FIELDS
        }


@dataclass(frozen=True, slots=True)
class CanonicalRule:
    """One immutable rule in the canonical semantic bottleneck."""

    modality: str
    actor: str
    action: str
    object: str
    conditions: tuple[str, ...] = ()
    exceptions: tuple[str, ...] = ()
    temporal: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.modality, str) or self.modality not in MODALITIES:
            raise ContractError("modality must be one of O, P, or F")
        object.__setattr__(
            self, "actor", _clean_text(self.actor, "actor", allow_empty=True)
        )
        object.__setattr__(
            self, "action", _clean_text(self.action, "action", allow_empty=True)
        )
        object.__setattr__(
            self, "object", _clean_text(self.object, "object", allow_empty=True)
        )
        for field in LIST_FIELDS:
            object.__setattr__(
                self, field, _canonical_items(getattr(self, field), field)
            )

    @classmethod
    def from_dict(cls, value: object) -> "CanonicalRule":
        if not isinstance(value, Mapping) or set(value) != set(RULE_FIELDS):
            raise ContractError(
                "canonical rule must contain exactly "
                + ", ".join(RULE_FIELDS)
            )
        return cls(
            modality=value["modality"],
            actor=value["actor"],
            action=value["action"],
            object=value["object"],
            conditions=value["conditions"],  # type: ignore[arg-type]
            exceptions=value["exceptions"],  # type: ignore[arg-type]
            temporal=value["temporal"],  # type: ignore[arg-type]
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "modality": self.modality,
            "actor": self.actor,
            "action": self.action,
            "object": self.object,
            "conditions": list(self.conditions),
            "exceptions": list(self.exceptions),
            "temporal": list(self.temporal),
        }


@dataclass(frozen=True, slots=True)
class CanonicalRuleIR:
    """Immutable and canonically ordered ``{"rules": [...]}`` IR."""

    rules: tuple[CanonicalRule, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.rules, Sequence)
            or isinstance(self.rules, (str, bytes, bytearray))
        ):
            raise ContractError("rules must be an array")
        if len(self.rules) > MAX_RULES:
            raise ContractError(f"rules exceeds the {MAX_RULES} rule bound")
        converted = tuple(
            rule
            if isinstance(rule, CanonicalRule)
            else CanonicalRule.from_dict(rule)
            for rule in self.rules
        )
        object.__setattr__(self, "rules", tuple(sorted(converted, key=_rule_key)))

    @classmethod
    def from_dict(
        cls,
        value: object,
        vocabulary: AllowedAtomVocabulary | None = None,
    ) -> "CanonicalRuleIR":
        if not isinstance(value, Mapping) or set(value) != {"rules"}:
            raise ContractError(
                "canonical IR must contain exactly the rules key"
            )
        raw_rules = value["rules"]
        if (
            not isinstance(raw_rules, Sequence)
            or isinstance(raw_rules, (str, bytes, bytearray))
        ):
            raise ContractError("rules must be an array")
        result = cls(tuple(CanonicalRule.from_dict(rule) for rule in raw_rules))
        if vocabulary is not None:
            result.validate_vocabulary(vocabulary)
        return result

    @property
    def is_empty(self) -> bool:
        return not self.rules

    def validate_vocabulary(
        self, vocabulary: AllowedAtomVocabulary
    ) -> None:
        scalar_vocabularies = {
            "actor": set(vocabulary.actors),
            "action": set(vocabulary.actions),
            "object": set(vocabulary.objects) | {""},
        }
        qualifier_vocabulary = set(vocabulary.qualifiers)
        for index, rule in enumerate(self.rules):
            for field, allowed in scalar_vocabularies.items():
                atom = getattr(rule, field)
                if atom not in allowed:
                    raise ContractError(
                        f"rule {index}.{field} is outside the allowed vocabulary"
                    )
            for field in LIST_FIELDS:
                unknown = set(getattr(rule, field)) - qualifier_vocabulary
                if unknown:
                    raise ContractError(
                        f"rule {index}.{field} contains unknown atoms: "
                        + ", ".join(sorted(unknown))
                    )

    def to_dict(self) -> dict[str, list[dict[str, object]]]:
        return {"rules": [rule.to_dict() for rule in self.rules]}


@dataclass(frozen=True, slots=True)
class ConstructorRequest:
    """Bounded public input to a constructor."""

    source_text: str
    allowed_atom_vocabulary: AllowedAtomVocabulary
    config: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_text",
            _bounded_text(self.source_text, "source_text", allow_blank=False),
        )
        if not isinstance(
            self.allowed_atom_vocabulary, AllowedAtomVocabulary
        ):
            raise ContractError(
                "allowed_atom_vocabulary must be AllowedAtomVocabulary"
            )
        object.__setattr__(self, "config", _frozen_config(self.config))

    @classmethod
    def from_payload(cls, payload: object) -> "ConstructorRequest":
        if not isinstance(payload, Mapping):
            raise ContractError("constructor payload must be an object")
        extra = set(payload) - _CONSTRUCTOR_PAYLOAD_FIELDS
        missing = _CONSTRUCTOR_PAYLOAD_FIELDS - set(payload)
        if extra or missing:
            raise ContractError(
                "constructor payload fields mismatch; "
                f"missing={sorted(missing)!r}, undeclared={sorted(extra)!r}"
            )
        return cls(
            source_text=payload["source_text"],
            allowed_atom_vocabulary=AllowedAtomVocabulary.from_dict(
                payload["allowed_atom_vocabulary"]
            ),
            config=payload["config"],
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "source_text": self.source_text,
            "allowed_atom_vocabulary": (
                self.allowed_atom_vocabulary.to_dict()
            ),
            "config": _thaw_json(self.config),
        }

    @classmethod
    def from_dict(cls, payload: object) -> "ConstructorRequest":
        """Deserialize the request's exact public wire representation."""

        return cls.from_payload(payload)

    def to_dict(self) -> dict[str, object]:
        return self.to_payload()


@dataclass(frozen=True, slots=True)
class RealizerRequest:
    """The strict source-withheld input accepted by a realizer."""

    canonical_ir: CanonicalRuleIR
    allowed_atom_vocabulary: AllowedAtomVocabulary
    config: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_ir, CanonicalRuleIR):
            raise ContractError("canonical_ir must be CanonicalRuleIR")
        if not isinstance(
            self.allowed_atom_vocabulary, AllowedAtomVocabulary
        ):
            raise ContractError(
                "allowed_atom_vocabulary must be AllowedAtomVocabulary"
            )
        self.canonical_ir.validate_vocabulary(self.allowed_atom_vocabulary)
        _reject_forbidden_realizer_config(self.config)
        object.__setattr__(self, "config", _frozen_config(self.config))

    @classmethod
    def from_payload(cls, payload: object) -> "RealizerRequest":
        if not isinstance(payload, Mapping):
            raise ContractError("realizer payload must be an object")
        extra = set(payload) - _REALIZER_PAYLOAD_FIELDS
        missing = _REALIZER_PAYLOAD_FIELDS - set(payload)
        if extra or missing:
            forbidden = sorted(
                str(field)
                for field in extra
                if str(field).strip().lower() in _FORBIDDEN_REALIZER_KEYS
            )
            if forbidden:
                raise ContractError(
                    "realizer payload contains forbidden source or native "
                    f"fields: {forbidden!r}"
                )
            raise ContractError(
                "realizer payload fields mismatch; "
                f"missing={sorted(missing)!r}, undeclared={sorted(extra)!r}"
            )
        vocabulary = AllowedAtomVocabulary.from_dict(
            payload["allowed_atom_vocabulary"]
        )
        return cls(
            canonical_ir=CanonicalRuleIR.from_dict(
                payload["canonical_ir"], vocabulary
            ),
            allowed_atom_vocabulary=vocabulary,
            config=payload["config"],
        )

    @property
    def ir(self) -> CanonicalRuleIR:
        """Concise read-only alias used by adapter implementations."""

        return self.canonical_ir

    def to_payload(self) -> dict[str, object]:
        return {
            "canonical_ir": self.canonical_ir.to_dict(),
            "allowed_atom_vocabulary": (
                self.allowed_atom_vocabulary.to_dict()
            ),
            "config": _thaw_json(self.config),
        }

    @classmethod
    def from_dict(cls, payload: object) -> "RealizerRequest":
        """Deserialize the request's exact source-withheld representation."""

        return cls.from_payload(payload)

    def to_dict(self) -> dict[str, object]:
        return self.to_payload()


@dataclass(frozen=True, slots=True)
class ConstructorResult:
    """Bounded terminal result returned by a constructor adapter."""

    status: ComponentStatus
    canonical_ir: CanonicalRuleIR | None = None
    failure_reason: FailureReason | None = None
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ComponentStatus):
            raise ContractError("constructor result status is invalid")
        if self.canonical_ir is not None and not isinstance(
            self.canonical_ir, CanonicalRuleIR
        ):
            raise ContractError(
                "constructor result canonical_ir must be CanonicalRuleIR"
            )
        if self.failure_reason is not None and not isinstance(
            self.failure_reason, FailureReason
        ):
            raise ContractError("constructor result failure reason is invalid")
        if self.status is ComponentStatus.SUCCESS:
            if (
                self.canonical_ir is None
                or self.canonical_ir.is_empty
                or self.failure_reason is not None
                or self.failure_detail is not None
            ):
                raise ContractError(
                    "successful constructor result requires nonempty "
                    "canonical_ir and cannot carry failure information"
                )
        elif self.failure_reason is None or self.canonical_ir is not None:
            raise ContractError(
                "failed constructor result requires a failure reason and no IR"
            )
        if self.failure_detail is not None:
            _bounded_text(
                self.failure_detail, "failure_detail", allow_blank=False
            )


@dataclass(frozen=True, slots=True)
class RealizerResult:
    """Bounded terminal result returned by a realizer adapter."""

    status: ComponentStatus
    text: str | None = None
    failure_reason: FailureReason | None = None
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ComponentStatus):
            raise ContractError("realizer result status is invalid")
        if self.failure_reason is not None and not isinstance(
            self.failure_reason, FailureReason
        ):
            raise ContractError("realizer result failure reason is invalid")
        if self.status is ComponentStatus.SUCCESS:
            if (
                self.text is None
                or self.failure_reason is not None
                or self.failure_detail is not None
            ):
                raise ContractError(
                    "successful realizer result requires text and cannot "
                    "carry failure information"
                )
            _bounded_text(self.text, "text", allow_blank=False)
        elif self.failure_reason is None or self.text is not None:
            raise ContractError(
                "failed realizer result requires a failure reason and no text"
            )
        if self.failure_detail is not None:
            _bounded_text(
                self.failure_detail, "failure_detail", allow_blank=False
            )


def _loss(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise ContractError(f"{field} must be a finite number from zero to one")
    return float(value)


@dataclass(frozen=True, slots=True)
class RoundTripResult:
    """Immutable terminal coordinate with three non-interchangeable losses."""

    status: ComponentStatus
    l1: CanonicalRuleIR | None
    reconstruction: str | None
    l2: CanonicalRuleIR | None
    forward_loss: float
    cycle_loss: float
    end_to_end_loss: float
    failure_reason: FailureReason | None = None
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ComponentStatus):
            raise ContractError("round-trip status is invalid")
        for field in ("l1", "l2"):
            value = getattr(self, field)
            if value is not None and not isinstance(value, CanonicalRuleIR):
                raise ContractError(
                    f"round-trip {field} must be CanonicalRuleIR or None"
                )
        if self.failure_reason is not None and not isinstance(
            self.failure_reason, FailureReason
        ):
            raise ContractError("round-trip failure reason is invalid")
        for field in ("forward_loss", "cycle_loss", "end_to_end_loss"):
            object.__setattr__(
                self, field, _loss(getattr(self, field), field)
            )
        if self.reconstruction is not None:
            _bounded_text(
                self.reconstruction, "reconstruction", allow_blank=True
            )
        complete = (
            self.status is ComponentStatus.SUCCESS
            and self.l1 is not None
            and not self.l1.is_empty
            and self.reconstruction is not None
            and bool(self.reconstruction.strip())
            and self.l2 is not None
            and not self.l2.is_empty
        )
        if complete:
            if self.failure_reason is not None or self.failure_detail is not None:
                raise ContractError(
                    "complete round trip cannot carry failure information"
                )
        else:
            if self.status is not ComponentStatus.FAILED:
                raise ContractError(
                    "missing, blank, or empty round trips must be failed"
                )
            if (
                self.forward_loss,
                self.cycle_loss,
                self.end_to_end_loss,
            ) != (1.0, 1.0, 1.0):
                raise ContractError(
                    "failed, missing, blank, or empty round trips must assign "
                    "one to every loss"
                )
            if self.failure_reason is None:
                raise ContractError(
                    "failed round trip requires a failure reason"
                )
        if self.failure_detail is not None:
            _bounded_text(
                self.failure_detail, "failure_detail", allow_blank=False
            )

    @property
    def primary_loss(self) -> float:
        """The protocol's primary loss: gold IR versus L2."""

        return self.end_to_end_loss

    @property
    def is_complete(self) -> bool:
        return (
            self.status is ComponentStatus.SUCCESS
            and self.l1 is not None
            and not self.l1.is_empty
            and self.reconstruction is not None
            and bool(self.reconstruction.strip())
            and self.l2 is not None
            and not self.l2.is_empty
        )


@runtime_checkable
class RoundTripConstructor(Protocol):
    """Structural protocol implemented by independently crossable constructors."""

    @property
    def identity(self) -> str:
        """Return the frozen implementation/configuration identity."""

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        """Construct canonical IR from one bounded request."""


@runtime_checkable
class RoundTripRealizer(Protocol):
    """Structural protocol implemented by source-withheld realizers."""

    @property
    def identity(self) -> str:
        """Return the frozen implementation/configuration identity."""

    def realize(self, request: RealizerRequest) -> RealizerResult:
        """Realize text from only canonical IR and declared public inputs."""


__all__ = [
    "CANONICAL_RULE_IR_INTERFACE",
    "ROUND_TRIP_CONSTRUCTOR_INTERFACE",
    "ROUND_TRIP_REALIZER_INTERFACE",
    "ROUND_TRIP_RESULT_INTERFACE",
    "RULE_FIELDS",
    "LIST_FIELDS",
    "VOCABULARY_FIELDS",
    "MODALITIES",
    "MAX_RULES",
    "MAX_LIST_ITEMS",
    "MAX_VOCABULARY_ITEMS",
    "MAX_ATOM_LENGTH",
    "MAX_TEXT_LENGTH",
    "MAX_CONFIG_BYTES",
    "MAX_CONFIG_DEPTH",
    "ContractError",
    "ComponentStatus",
    "FailureReason",
    "AllowedAtomVocabulary",
    "CanonicalRule",
    "CanonicalRuleIR",
    "ConstructorRequest",
    "RealizerRequest",
    "ConstructorResult",
    "RealizerResult",
    "RoundTripResult",
    "RoundTripConstructor",
    "RoundTripRealizer",
]
