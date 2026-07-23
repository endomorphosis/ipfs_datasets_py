"""Canonical, flat Abby voice dataset schema (v2).

The four schemas in this module are deliberately separate.  A response row is
never also an audio, provenance, template, index, or manifest row.  This keeps
the serialized tables compatible with Arrow, Parquet, and Hugging Face Dataset
Viewer, whose schema inference cannot safely combine heterogeneous JSON files.

Only scalars, nullable scalars, and consistently typed ``list[str]`` columns
are emitted.  Python tuples are used internally to make records immutable;
``to_dict()`` always emits ordinary JSON lists.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields
from datetime import datetime
from hashlib import sha256
from string import Formatter
from typing import Any, ClassVar, TypeAlias, TypeVar

ABBY_VOICE_RESPONSE_V2 = "abby_voice_response_v2"
ABBY_VOICE_TEMPLATE_V2 = "abby_voice_template_v2"
ABBY_VOICE_AUDIO_V2 = "abby_voice_audio_v2"
ABBY_VOICE_PROVENANCE_V2 = "abby_voice_provenance_v2"

# Explicit aliases make the public names easy to discover and preserve the
# terminology used in the objective heap.
ABBY_VOICE_RESPONSE_V2_SCHEMA = ABBY_VOICE_RESPONSE_V2
ABBY_VOICE_TEMPLATE_V2_SCHEMA = ABBY_VOICE_TEMPLATE_V2
ABBY_VOICE_AUDIO_V2_SCHEMA = ABBY_VOICE_AUDIO_V2
ABBY_VOICE_PROVENANCE_V2_SCHEMA = ABBY_VOICE_PROVENANCE_V2

SCHEMA_VERSIONS = (
    ABBY_VOICE_RESPONSE_V2,
    ABBY_VOICE_TEMPLATE_V2,
    ABBY_VOICE_AUDIO_V2,
    ABBY_VOICE_PROVENANCE_V2,
)

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_LOCALE_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_ALLOWED_CONSENT = frozenset(
    {"granted", "not_required", "unknown", "denied", "withdrawn"}
)
_PUBLISHABLE_CONSENT = frozenset({"granted", "not_required"})
_SEGMENT_KINDS = frozenset(
    {"response", "template_shell", "slot_value", "vocabulary"}
)
_AGGREGATE_KEYS = frozenset(
    {
        "responses",
        "templates",
        "audios",
        "audio_assets",
        "provenance",
        "records",
        "entries",
        "items",
        "index",
        "manifest",
    }
)


class AbbyVoiceSchemaError(ValueError):
    """Raised when an Abby voice row violates its canonical contract."""

    def __init__(self, schema_version: str, errors: str | Iterable[str]):
        self.schema_version = schema_version
        self.errors = (
            (errors,) if isinstance(errors, str) else tuple(str(error) for error in errors)
        )
        detail = "; ".join(self.errors) or "invalid record"
        super().__init__(f"{schema_version}: {detail}")


# A conventional alias for consumers that do not use the Abby-specific name.
SchemaValidationError = AbbyVoiceSchemaError


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """Dependency-free description of one flat serialized column."""

    name: str
    kind: str
    nullable: bool = False
    description: str = ""


@dataclass(frozen=True, slots=True)
class SchemaDefinition:
    """Schema metadata shared by validators and optional adapters."""

    schema_version: str
    id_column: str
    row_type: type[_VoiceRow]
    columns: tuple[ColumnSpec, ...]

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)


def sha256_text(text: str) -> str:
    """Return the full lower-case SHA-256 digest of UTF-8 text."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return sha256(text.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, payload: Mapping[str, Any] | Sequence[Any] | str) -> str:
    if isinstance(payload, str):
        encoded = payload.encode("utf-8")
    else:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    return f"{prefix}-{sha256(encoded).hexdigest()[:24]}"


def stable_response_id(
    text: str, spoken_text: str, locale: str = "en-US", intent: str | None = None
) -> str:
    """Build a deterministic response ID from semantic response content."""

    return _stable_id(
        "response",
        {"intent": intent, "locale": locale, "spoken_text": spoken_text, "text": text},
    )


def stable_template_id(
    template_text: str,
    spoken_template: str,
    locale: str = "en-US",
    intent: str = "general",
) -> str:
    """Build a deterministic template ID."""

    return _stable_id(
        "template",
        {
            "intent": intent,
            "locale": locale,
            "spoken_template": spoken_template,
            "template_text": template_text,
        },
    )


def stable_audio_id(content_sha256: str, *, segment_kind: str = "response") -> str:
    """Build a deterministic audio ID without embedding mutable storage paths."""

    return _stable_id(
        "audio", {"content_sha256": content_sha256, "segment_kind": segment_kind}
    )


def stable_provenance_id(
    subject_id: str,
    source_uri: str,
    transformation_name: str,
    source_revision: str | None = None,
) -> str:
    """Build a deterministic provenance ID; timestamps are intentionally absent."""

    return _stable_id(
        "provenance",
        {
            "source_revision": source_revision,
            "source_uri": source_uri,
            "subject_id": subject_id,
            "transformation_name": transformation_name,
        },
    )


def _tuple_of_strings(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        raise TypeError(f"{field_name} must be a list or tuple of strings, not null")
    if isinstance(value, str | bytes | bytearray) or not isinstance(value, list | tuple):
        raise TypeError(f"{field_name} must be a list or tuple of strings")
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise TypeError(f"{field_name}[{index}] must be a non-empty string")
        item = item.strip()
        if item not in seen:
            result.append(item)
            seen.add(item)
    return tuple(result)


def _normalize_row(instance: _VoiceRow) -> None:
    for item in fields(instance):
        value = getattr(instance, item.name)
        if item.name in instance.LIST_FIELDS:
            object.__setattr__(
                instance, item.name, _tuple_of_strings(value, item.name)
            )
        elif isinstance(value, str):
            object.__setattr__(instance, item.name, value.strip())


def _valid_timestamp(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return parsed.tzinfo is not None


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


class _VoiceRow:
    """Shared immutable-row serialization and strict construction behavior."""

    SCHEMA_VERSION: ClassVar[str]
    ID_FIELD: ClassVar[str]
    LIST_FIELDS: ClassVar[frozenset[str]] = frozenset()

    def __post_init__(self) -> None:
        _normalize_row(self)
        errors = _validate_instance(self)
        if errors:
            raise AbbyVoiceSchemaError(self.SCHEMA_VERSION, errors)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON/Arrow-safe flat mapping in canonical column order."""

        result: dict[str, Any] = {}
        for column in schema_columns(self.SCHEMA_VERSION):
            value = getattr(self, column)
            result[column] = list(value) if column in self.LIST_FIELDS else value
        return result

    @classmethod
    def from_dict(
        cls: type[_RowT], data: Mapping[str, Any], *, strict: bool = True
    ) -> _RowT:
        """Construct from one canonical mapping.

        Unknown keys are rejected by default so that aggregate manifests and
        rows from another config cannot silently enter a table.
        """

        if not isinstance(data, Mapping):
            raise AbbyVoiceSchemaError(cls.SCHEMA_VERSION, "record must be a mapping")
        actual = data.get("schema_version")
        if actual != cls.SCHEMA_VERSION:
            raise AbbyVoiceSchemaError(
                cls.SCHEMA_VERSION,
                f"schema_version must equal {cls.SCHEMA_VERSION!r}, got {actual!r}",
            )
        allowed = set(schema_columns(cls.SCHEMA_VERSION))
        unknown = sorted(set(data) - allowed)
        if strict and unknown:
            raise AbbyVoiceSchemaError(
                cls.SCHEMA_VERSION, f"unknown columns: {', '.join(unknown)}"
            )
        missing = sorted(allowed - set(data))
        if strict and missing:
            raise AbbyVoiceSchemaError(
                cls.SCHEMA_VERSION,
                f"missing canonical columns: {', '.join(missing)}",
            )
        kwargs: dict[str, Any] = {}
        for item in fields(cls):
            if item.init and item.name in data:
                kwargs[item.name] = data[item.name]
        try:
            return cls(**kwargs)
        except AbbyVoiceSchemaError:
            raise
        except (TypeError, ValueError) as exc:
            raise AbbyVoiceSchemaError(cls.SCHEMA_VERSION, str(exc)) from exc


_RowT = TypeVar("_RowT", bound=_VoiceRow)


@dataclass(frozen=True, slots=True)
class AbbyVoiceResponse(_VoiceRow):
    """One caller utterance/response pair and its grounded slot bindings."""

    response_id: str
    text: str
    spoken_text: str
    locale: str = "en-US"
    content_sha256: str | None = None
    template_id: str | None = None
    intent: str | None = None
    utterance: str | None = None
    slot_names: tuple[str, ...] = ()
    slot_values: tuple[str, ...] = ()
    slot_source_cids: tuple[str, ...] = ()
    audio_ids: tuple[str, ...] = ()
    provenance_ids: tuple[str, ...] = ()
    source_cids: tuple[str, ...] = ()
    route_labels: tuple[str, ...] = ()
    service_tags: tuple[str, ...] = ()
    location_tags: tuple[str, ...] = ()
    safety_labels: tuple[str, ...] = ()
    license_id: str = "NOASSERTION"
    consent_status: str = "unknown"
    created_at: str | None = None
    schema_version: str = field(default=ABBY_VOICE_RESPONSE_V2, init=False)

    SCHEMA_VERSION: ClassVar[str] = ABBY_VOICE_RESPONSE_V2
    ID_FIELD: ClassVar[str] = "response_id"
    LIST_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "slot_names",
            "slot_values",
            "slot_source_cids",
            "audio_ids",
            "provenance_ids",
            "source_cids",
            "route_labels",
            "service_tags",
            "location_tags",
            "safety_labels",
        }
    )

    def __post_init__(self) -> None:
        if self.content_sha256 is None and isinstance(self.spoken_text, str):
            object.__setattr__(self, "content_sha256", sha256_text(self.spoken_text.strip()))
        super(AbbyVoiceResponse, self).__post_init__()


@dataclass(frozen=True, slots=True)
class AbbyVoiceTemplate(_VoiceRow):
    """A response plan with declared, machine-checkable slot placeholders."""

    template_id: str
    template_text: str
    intent: str
    spoken_template: str | None = None
    locale: str = "en-US"
    content_sha256: str | None = None
    slot_names: tuple[str, ...] = ()
    required_slot_names: tuple[str, ...] = ()
    factual_slot_names: tuple[str, ...] = ()
    provenance_ids: tuple[str, ...] = ()
    source_cids: tuple[str, ...] = ()
    safety_labels: tuple[str, ...] = ()
    license_id: str = "NOASSERTION"
    consent_status: str = "unknown"
    created_at: str | None = None
    schema_version: str = field(default=ABBY_VOICE_TEMPLATE_V2, init=False)

    SCHEMA_VERSION: ClassVar[str] = ABBY_VOICE_TEMPLATE_V2
    ID_FIELD: ClassVar[str] = "template_id"
    LIST_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "slot_names",
            "required_slot_names",
            "factual_slot_names",
            "provenance_ids",
            "source_cids",
            "safety_labels",
        }
    )

    def __post_init__(self) -> None:
        if self.spoken_template is None and isinstance(self.template_text, str):
            object.__setattr__(self, "spoken_template", self.template_text)
        if self.content_sha256 is None and isinstance(self.spoken_template, str):
            object.__setattr__(
                self, "content_sha256", sha256_text(self.spoken_template.strip())
            )
        super(AbbyVoiceTemplate, self).__post_init__()


@dataclass(frozen=True, slots=True)
class AbbyVoiceAudio(_VoiceRow):
    """Metadata for one external audio asset; raw bytes are never a row column."""

    audio_id: str
    spoken_text: str
    content_sha256: str
    text_sha256: str | None = None
    locale: str = "en-US"
    uri: str | None = None
    ipfs_cid: str | None = None
    response_id: str | None = None
    template_id: str | None = None
    segment_kind: str = "response"
    slot_name: str | None = None
    slot_value: str | None = None
    mime_type: str = "audio/mpeg"
    codec: str | None = None
    byte_length: int | None = None
    duration_ms: float | None = None
    sample_rate_hz: int | None = None
    channels: int | None = None
    provider: str | None = None
    model: str | None = None
    voice: str | None = None
    provenance_ids: tuple[str, ...] = ()
    source_cids: tuple[str, ...] = ()
    safety_labels: tuple[str, ...] = ()
    license_id: str = "NOASSERTION"
    consent_status: str = "unknown"
    created_at: str | None = None
    schema_version: str = field(default=ABBY_VOICE_AUDIO_V2, init=False)

    SCHEMA_VERSION: ClassVar[str] = ABBY_VOICE_AUDIO_V2
    ID_FIELD: ClassVar[str] = "audio_id"
    LIST_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"provenance_ids", "source_cids", "safety_labels"}
    )

    def __post_init__(self) -> None:
        if self.text_sha256 is None and isinstance(self.spoken_text, str):
            object.__setattr__(self, "text_sha256", sha256_text(self.spoken_text.strip()))
        super(AbbyVoiceAudio, self).__post_init__()


@dataclass(frozen=True, slots=True)
class AbbyVoiceProvenance(_VoiceRow):
    """Lineage for a response, template, or audio row."""

    provenance_id: str
    subject_id: str
    subject_schema_version: str
    transformation_name: str
    source_uri: str | None = None
    source_revision: str | None = None
    source_sha256: str | None = None
    source_cids: tuple[str, ...] = ()
    parent_provenance_ids: tuple[str, ...] = ()
    transformation_version: str | None = None
    generated_at: str | None = None
    locale: str | None = None
    license_id: str = "NOASSERTION"
    consent_status: str = "unknown"
    consent_id: str | None = None
    safety_labels: tuple[str, ...] = ()
    schema_version: str = field(default=ABBY_VOICE_PROVENANCE_V2, init=False)

    SCHEMA_VERSION: ClassVar[str] = ABBY_VOICE_PROVENANCE_V2
    ID_FIELD: ClassVar[str] = "provenance_id"
    LIST_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"source_cids", "parent_provenance_ids", "safety_labels"}
    )


VoiceRow: TypeAlias = (
    AbbyVoiceResponse | AbbyVoiceTemplate | AbbyVoiceAudio | AbbyVoiceProvenance
)


def _c(name: str, kind: str = "string", nullable: bool = False) -> ColumnSpec:
    return ColumnSpec(name=name, kind=kind, nullable=nullable)


_COMMON_END = (
    _c("license_id"),
    _c("consent_status"),
)

_DEFINITIONS = (
    SchemaDefinition(
        ABBY_VOICE_RESPONSE_V2,
        "response_id",
        AbbyVoiceResponse,
        (
            _c("schema_version"),
            _c("response_id"),
            _c("text"),
            _c("spoken_text"),
            _c("locale"),
            _c("content_sha256"),
            _c("template_id", nullable=True),
            _c("intent", nullable=True),
            _c("utterance", nullable=True),
            _c("slot_names", "list[string]"),
            _c("slot_values", "list[string]"),
            _c("slot_source_cids", "list[string]"),
            _c("audio_ids", "list[string]"),
            _c("provenance_ids", "list[string]"),
            _c("source_cids", "list[string]"),
            _c("route_labels", "list[string]"),
            _c("service_tags", "list[string]"),
            _c("location_tags", "list[string]"),
            _c("safety_labels", "list[string]"),
            *_COMMON_END,
            _c("created_at", nullable=True),
        ),
    ),
    SchemaDefinition(
        ABBY_VOICE_TEMPLATE_V2,
        "template_id",
        AbbyVoiceTemplate,
        (
            _c("schema_version"),
            _c("template_id"),
            _c("template_text"),
            _c("intent"),
            _c("spoken_template"),
            _c("locale"),
            _c("content_sha256"),
            _c("slot_names", "list[string]"),
            _c("required_slot_names", "list[string]"),
            _c("factual_slot_names", "list[string]"),
            _c("provenance_ids", "list[string]"),
            _c("source_cids", "list[string]"),
            _c("safety_labels", "list[string]"),
            *_COMMON_END,
            _c("created_at", nullable=True),
        ),
    ),
    SchemaDefinition(
        ABBY_VOICE_AUDIO_V2,
        "audio_id",
        AbbyVoiceAudio,
        (
            _c("schema_version"),
            _c("audio_id"),
            _c("spoken_text"),
            _c("content_sha256"),
            _c("text_sha256"),
            _c("locale"),
            _c("uri", nullable=True),
            _c("ipfs_cid", nullable=True),
            _c("response_id", nullable=True),
            _c("template_id", nullable=True),
            _c("segment_kind"),
            _c("slot_name", nullable=True),
            _c("slot_value", nullable=True),
            _c("mime_type"),
            _c("codec", nullable=True),
            _c("byte_length", "int64", nullable=True),
            _c("duration_ms", "float64", nullable=True),
            _c("sample_rate_hz", "int64", nullable=True),
            _c("channels", "int64", nullable=True),
            _c("provider", nullable=True),
            _c("model", nullable=True),
            _c("voice", nullable=True),
            _c("provenance_ids", "list[string]"),
            _c("source_cids", "list[string]"),
            _c("safety_labels", "list[string]"),
            *_COMMON_END,
            _c("created_at", nullable=True),
        ),
    ),
    SchemaDefinition(
        ABBY_VOICE_PROVENANCE_V2,
        "provenance_id",
        AbbyVoiceProvenance,
        (
            _c("schema_version"),
            _c("provenance_id"),
            _c("subject_id"),
            _c("subject_schema_version"),
            _c("transformation_name"),
            _c("source_uri", nullable=True),
            _c("source_revision", nullable=True),
            _c("source_sha256", nullable=True),
            _c("source_cids", "list[string]"),
            _c("parent_provenance_ids", "list[string]"),
            _c("transformation_version", nullable=True),
            _c("generated_at", nullable=True),
            _c("locale", nullable=True),
            *_COMMON_END,
            _c("consent_id", nullable=True),
            _c("safety_labels", "list[string]"),
        ),
    ),
)

SCHEMA_REGISTRY: dict[str, SchemaDefinition] = {
    definition.schema_version: definition for definition in _DEFINITIONS
}
SCHEMA_DEFINITIONS = SCHEMA_REGISTRY
ROW_TYPE_REGISTRY: dict[str, type[_VoiceRow]] = {
    name: definition.row_type for name, definition in SCHEMA_REGISTRY.items()
}
HUGGINGFACE_FEATURE_SPECS: dict[str, dict[str, str]] = {
    name: {column.name: column.kind for column in definition.columns}
    for name, definition in SCHEMA_REGISTRY.items()
}


def get_schema_definition(schema_version: str) -> SchemaDefinition:
    """Return a canonical definition or raise a schema-specific error."""

    try:
        return SCHEMA_REGISTRY[schema_version]
    except KeyError as exc:
        raise AbbyVoiceSchemaError(
            str(schema_version),
            f"unsupported schema_version; expected one of {', '.join(SCHEMA_VERSIONS)}",
        ) from exc


def schema_columns(schema_version: str) -> tuple[str, ...]:
    """Return the fixed serialized column order for one dataset config."""

    return get_schema_definition(schema_version).column_names


def _validate_string(
    errors: list[str], name: str, value: Any, *, optional: bool = False
) -> None:
    if value is None and optional:
        return
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{name} must be a non-empty string")


def _validate_id(errors: list[str], name: str, value: Any) -> None:
    _validate_string(errors, name, value)
    if isinstance(value, str) and value and not _ID_RE.fullmatch(value):
        errors.append(f"{name} contains unsupported characters or is too long")


def _validate_hash(
    errors: list[str], name: str, value: Any, *, optional: bool = False
) -> None:
    if value is None and optional:
        return
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        errors.append(f"{name} must be a full lower-case SHA-256 digest")


def _template_placeholders(text: str, field_name: str, errors: list[str]) -> set[str]:
    placeholders: set[str] = set()
    try:
        parsed = Formatter().parse(text)
        for _, name, format_spec, conversion in parsed:
            if name is None:
                continue
            if (
                not name
                or "." in name
                or "[" in name
                or "]" in name
                or format_spec
                or conversion
                or not _ID_RE.fullmatch(name)
            ):
                errors.append(
                    f"{field_name} contains unsafe placeholder {name!r}; "
                    "only simple slot names are allowed"
                )
            else:
                placeholders.add(name)
    except ValueError as exc:
        errors.append(f"{field_name} has invalid braces: {exc}")
    return placeholders


def _validate_instance(row: _VoiceRow) -> list[str]:
    errors: list[str] = []
    if row.schema_version != row.SCHEMA_VERSION:
        errors.append(f"schema_version must equal {row.SCHEMA_VERSION!r}")
    _validate_id(errors, row.ID_FIELD, getattr(row, row.ID_FIELD))

    locale = getattr(row, "locale", None)
    if locale is not None and (
        not isinstance(locale, str) or not _LOCALE_RE.fullmatch(locale)
    ):
        errors.append("locale must be a BCP-47 language tag such as 'en' or 'en-US'")

    license_id = getattr(row, "license_id", None)
    _validate_string(errors, "license_id", license_id)
    consent = getattr(row, "consent_status", None)
    if consent not in _ALLOWED_CONSENT:
        errors.append(
            "consent_status must be one of " + ", ".join(sorted(_ALLOWED_CONSENT))
        )

    for timestamp_name in ("created_at", "generated_at"):
        value = getattr(row, timestamp_name, None)
        if value is not None and (
            not isinstance(value, str) or not _valid_timestamp(value)
        ):
            errors.append(f"{timestamp_name} must be a timezone-aware RFC 3339 timestamp")

    if isinstance(row, AbbyVoiceResponse):
        _validate_string(errors, "text", row.text)
        _validate_string(errors, "spoken_text", row.spoken_text)
        _validate_hash(errors, "content_sha256", row.content_sha256)
        if (
            isinstance(row.spoken_text, str)
            and row.spoken_text
            and row.content_sha256 != sha256_text(row.spoken_text)
        ):
            errors.append("content_sha256 must equal SHA-256(spoken_text UTF-8)")
        if not (
            len(row.slot_names)
            == len(row.slot_values)
            == len(row.slot_source_cids)
        ):
            errors.append(
                "slot_names, slot_values, and slot_source_cids must have equal lengths"
            )
        for name in row.slot_names:
            if not _ID_RE.fullmatch(name):
                errors.append(f"slot name {name!r} is not a stable identifier")

    elif isinstance(row, AbbyVoiceTemplate):
        _validate_string(errors, "template_text", row.template_text)
        _validate_string(errors, "spoken_template", row.spoken_template)
        _validate_string(errors, "intent", row.intent)
        _validate_hash(errors, "content_sha256", row.content_sha256)
        if (
            isinstance(row.spoken_template, str)
            and row.spoken_template
            and row.content_sha256 != sha256_text(row.spoken_template)
        ):
            errors.append("content_sha256 must equal SHA-256(spoken_template UTF-8)")
        declared = set(row.slot_names)
        if not set(row.required_slot_names) <= declared:
            errors.append("required_slot_names must be a subset of slot_names")
        if not set(row.factual_slot_names) <= declared:
            errors.append("factual_slot_names must be a subset of slot_names")
        text_slots = _template_placeholders(row.template_text, "template_text", errors)
        spoken_slots = _template_placeholders(
            row.spoken_template or "", "spoken_template", errors
        )
        if text_slots != declared:
            errors.append("template_text placeholders must exactly match slot_names")
        if spoken_slots != declared:
            errors.append("spoken_template placeholders must exactly match slot_names")

    elif isinstance(row, AbbyVoiceAudio):
        _validate_string(errors, "spoken_text", row.spoken_text)
        _validate_hash(errors, "content_sha256", row.content_sha256)
        _validate_hash(errors, "text_sha256", row.text_sha256)
        if (
            isinstance(row.spoken_text, str)
            and row.spoken_text
            and row.text_sha256 != sha256_text(row.spoken_text)
        ):
            errors.append("text_sha256 must equal SHA-256(spoken_text UTF-8)")
        if not row.uri and not row.ipfs_cid:
            errors.append("audio requires at least one of uri or ipfs_cid")
        if not row.response_id and not row.template_id and not row.slot_name:
            errors.append(
                "audio requires a response_id, template_id, or slot_name subject"
            )
        if row.segment_kind not in _SEGMENT_KINDS:
            errors.append("segment_kind must be one of " + ", ".join(sorted(_SEGMENT_KINDS)))
        if not isinstance(row.mime_type, str) or not row.mime_type.startswith("audio/"):
            errors.append("mime_type must be an audio/* media type")
        if row.byte_length is not None and (
            not isinstance(row.byte_length, int)
            or isinstance(row.byte_length, bool)
            or row.byte_length < 0
        ):
            errors.append("byte_length must be an integer greater than or equal to zero")
        if row.duration_ms is not None and (
            not _is_number(row.duration_ms) or float(row.duration_ms) < 0
        ):
            errors.append("duration_ms must be a finite number >= 0")
        for name in ("sample_rate_hz", "channels"):
            value = getattr(row, name)
            if value is not None and (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
            ):
                errors.append(f"{name} must be a positive integer")
        if row.segment_kind == "slot_value" and (not row.slot_name or not row.slot_value):
            errors.append("slot_value audio requires both slot_name and slot_value")

    elif isinstance(row, AbbyVoiceProvenance):
        _validate_id(errors, "subject_id", row.subject_id)
        if row.subject_schema_version not in {
            ABBY_VOICE_RESPONSE_V2,
            ABBY_VOICE_TEMPLATE_V2,
            ABBY_VOICE_AUDIO_V2,
        }:
            errors.append(
                "subject_schema_version must identify a response, template, or audio schema"
            )
        _validate_string(errors, "transformation_name", row.transformation_name)
        if not row.source_uri and not row.source_cids:
            errors.append("provenance requires source_uri or at least one source_cid")
        _validate_hash(errors, "source_sha256", row.source_sha256, optional=True)

    return errors


def parse_abby_voice_record(
    record: Mapping[str, Any] | VoiceRow, *, strict: bool = True
) -> VoiceRow:
    """Dispatch and validate a canonical row using its exact schema version."""

    if isinstance(record, _VoiceRow):
        errors = _validate_instance(record)
        if errors:
            raise AbbyVoiceSchemaError(record.SCHEMA_VERSION, errors)
        return record
    if not isinstance(record, Mapping):
        raise AbbyVoiceSchemaError("unknown", "record must be a mapping")
    schema_version = record.get("schema_version")
    if not isinstance(schema_version, str):
        raise AbbyVoiceSchemaError("unknown", "schema_version is required")
    definition = get_schema_definition(schema_version)
    return definition.row_type.from_dict(record, strict=strict)


def validate_abby_voice_record(
    record: Mapping[str, Any] | VoiceRow, *, strict: bool = True
) -> VoiceRow:
    """Validate and return one typed canonical row."""

    return parse_abby_voice_record(record, strict=strict)


validate_record = validate_abby_voice_record
validate_row = validate_abby_voice_record


def validate_records(
    records: Iterable[Mapping[str, Any] | VoiceRow], *, strict: bool = True
) -> tuple[VoiceRow, ...]:
    """Validate a sequence and reject duplicate IDs within each schema."""

    parsed: list[VoiceRow] = []
    seen: set[tuple[str, str]] = set()
    for index, record in enumerate(records):
        try:
            row = parse_abby_voice_record(record, strict=strict)
        except AbbyVoiceSchemaError as exc:
            raise AbbyVoiceSchemaError(exc.schema_version, f"row {index}: {exc}") from exc
        identity = (row.SCHEMA_VERSION, getattr(row, row.ID_FIELD))
        if identity in seen:
            raise AbbyVoiceSchemaError(
                row.SCHEMA_VERSION, f"row {index}: duplicate ID {identity[1]!r}"
            )
        seen.add(identity)
        parsed.append(row)
    return tuple(parsed)


validate_rows = validate_records


@dataclass(frozen=True, slots=True)
class AbbyVoiceDatasetBundle:
    """Validated in-memory view of the four independently serialized configs."""

    responses: tuple[AbbyVoiceResponse, ...] = ()
    templates: tuple[AbbyVoiceTemplate, ...] = ()
    audio: tuple[AbbyVoiceAudio, ...] = ()
    provenance: tuple[AbbyVoiceProvenance, ...] = ()


def _typed_rows(
    values: Iterable[Mapping[str, Any] | VoiceRow],
    expected: type[_RowT],
) -> tuple[_RowT, ...]:
    result: list[_RowT] = []
    for row in validate_records(values):
        if not isinstance(row, expected):
            raise AbbyVoiceSchemaError(
                expected.SCHEMA_VERSION,
                f"expected {expected.SCHEMA_VERSION}, got {row.SCHEMA_VERSION}",
            )
        result.append(row)
    return tuple(result)


def validate_bundle(
    *,
    responses: Iterable[Mapping[str, Any] | AbbyVoiceResponse] = (),
    templates: Iterable[Mapping[str, Any] | AbbyVoiceTemplate] = (),
    audio: Iterable[Mapping[str, Any] | AbbyVoiceAudio] = (),
    provenance: Iterable[Mapping[str, Any] | AbbyVoiceProvenance] = (),
    require_references: bool = True,
) -> AbbyVoiceDatasetBundle:
    """Validate four configs and, by default, every local cross-row reference."""

    bundle = AbbyVoiceDatasetBundle(
        responses=_typed_rows(responses, AbbyVoiceResponse),
        templates=_typed_rows(templates, AbbyVoiceTemplate),
        audio=_typed_rows(audio, AbbyVoiceAudio),
        provenance=_typed_rows(provenance, AbbyVoiceProvenance),
    )
    if not require_references:
        return bundle

    response_ids = {row.response_id for row in bundle.responses}
    template_ids = {row.template_id for row in bundle.templates}
    audio_ids = {row.audio_id for row in bundle.audio}
    provenance_ids = {row.provenance_id for row in bundle.provenance}
    errors: list[str] = []

    for row in bundle.responses:
        if row.template_id and row.template_id not in template_ids:
            errors.append(f"{row.response_id}: missing template {row.template_id}")
        errors.extend(
            f"{row.response_id}: missing audio {ref}"
            for ref in row.audio_ids
            if ref not in audio_ids
        )
        errors.extend(
            f"{row.response_id}: missing provenance {ref}"
            for ref in row.provenance_ids
            if ref not in provenance_ids
        )

    for row in (*bundle.templates, *bundle.audio):
        errors.extend(
            f"{getattr(row, row.ID_FIELD)}: missing provenance {ref}"
            for ref in row.provenance_ids
            if ref not in provenance_ids
        )
    for row in bundle.audio:
        if row.response_id and row.response_id not in response_ids:
            errors.append(f"{row.audio_id}: missing response {row.response_id}")
        if row.template_id and row.template_id not in template_ids:
            errors.append(f"{row.audio_id}: missing template {row.template_id}")
    subject_sets = {
        ABBY_VOICE_RESPONSE_V2: response_ids,
        ABBY_VOICE_TEMPLATE_V2: template_ids,
        ABBY_VOICE_AUDIO_V2: audio_ids,
    }
    for row in bundle.provenance:
        if row.subject_id not in subject_sets[row.subject_schema_version]:
            errors.append(
                f"{row.provenance_id}: missing subject {row.subject_id} "
                f"in {row.subject_schema_version}"
            )
        errors.extend(
            f"{row.provenance_id}: missing parent provenance {ref}"
            for ref in row.parent_provenance_ids
            if ref not in provenance_ids
        )
    if errors:
        raise AbbyVoiceSchemaError("abby_voice_bundle_v2", errors)
    return bundle


def validate_publishable(
    value: Mapping[str, Any] | VoiceRow | AbbyVoiceDatasetBundle,
) -> None:
    """Enforce distribution policy separately from structural validity.

    ``unknown`` consent and ``NOASSERTION`` licensing are useful during
    non-destructive migration, but they are not sufficient for publication.
    """

    if isinstance(value, AbbyVoiceDatasetBundle):
        rows: Iterable[VoiceRow] = (
            *value.responses,
            *value.templates,
            *value.audio,
            *value.provenance,
        )
    else:
        rows = (parse_abby_voice_record(value),)
    errors: list[str] = []
    for row in rows:
        row_id = getattr(row, row.ID_FIELD)
        if row.consent_status not in _PUBLISHABLE_CONSENT:
            errors.append(f"{row_id}: consent_status is not publishable")
        if row.license_id.upper() in {"NOASSERTION", "UNKNOWN"}:
            errors.append(f"{row_id}: license_id is not publication-ready")
    if errors:
        raise AbbyVoiceSchemaError("abby_voice_publishable_v2", errors)


def get_huggingface_features(schema_version: str) -> Any:
    """Build ``datasets.Features`` lazily for one canonical config."""

    try:
        from datasets import Features, Value
        from datasets import Sequence as HFSequence
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise ImportError(
            "get_huggingface_features requires the optional 'datasets' package"
        ) from exc
    converters = {
        "string": lambda: Value("string"),
        "int64": lambda: Value("int64"),
        "float64": lambda: Value("float64"),
        "list[string]": lambda: HFSequence(Value("string")),
    }
    definition = get_schema_definition(schema_version)
    return Features(
        {column.name: converters[column.kind]() for column in definition.columns}
    )


def get_pyarrow_schema(schema_version: str) -> Any:
    """Build a lazy ``pyarrow.Schema`` with fixed scalar/list column types."""

    try:
        import pyarrow as pa
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise ImportError("get_pyarrow_schema requires the optional 'pyarrow' package") from exc
    types = {
        "string": pa.string(),
        "int64": pa.int64(),
        "float64": pa.float64(),
        "list[string]": pa.list_(pa.string()),
    }
    definition = get_schema_definition(schema_version)
    return pa.schema(
        [
            pa.field(column.name, types[column.kind], nullable=column.nullable)
            for column in definition.columns
        ],
        metadata={
            b"abby_voice_schema_version": schema_version.encode("utf-8"),
            b"abby_voice_flat_contract": b"2",
        },
    )


get_arrow_schema = get_pyarrow_schema


def _reject_aggregate(record: Mapping[str, Any], schema_version: str) -> None:
    found = sorted(
        key
        for key in _AGGREGATE_KEYS
        if key in record and isinstance(record[key], list | dict)
    )
    if found:
        raise AbbyVoiceSchemaError(
            schema_version,
            "aggregate manifests/indexes are not rows; found wrapper columns: "
            + ", ".join(found),
        )


def _legacy_lists(record: Mapping[str, Any], *names: str) -> tuple[str, ...]:
    for name in names:
        value = record.get(name)
        if value is None:
            continue
        if isinstance(value, str):
            return (value,) if value.strip() else ()
        return _tuple_of_strings(value, name)
    return ()


def _first_present(record: Mapping[str, Any], *names: str) -> Any:
    """Return the first non-null legacy field while preserving falsey values."""

    for name in names:
        if name in record and record[name] is not None:
            return record[name]
    return None


def migrate_legacy_response(
    record: Mapping[str, Any],
    *,
    locale: str = "en-US",
    license_id: str = "NOASSERTION",
    consent_status: str = "unknown",
) -> AbbyVoiceResponse:
    """Migrate one legacy response item without mutating its source mapping."""

    _reject_aggregate(record, ABBY_VOICE_RESPONSE_V2)
    spoken = str(record.get("spoken_text") or record.get("spokenText") or record.get("text") or "").strip()
    originals = record.get("originalTexts")
    text = str(
        record.get("response_text")
        or record.get("responseText")
        or (originals[0] if isinstance(originals, list) and originals else "")
        or spoken
    ).strip()
    intent_value = record.get("intent")
    routes = _legacy_lists(record, "route_labels", "routes")
    intent = str(intent_value).strip() if intent_value else (routes[0] if routes else None)
    return AbbyVoiceResponse(
        response_id=stable_response_id(text, spoken, locale, intent),
        text=text,
        spoken_text=spoken,
        locale=locale,
        intent=intent,
        utterance=record.get("utterance") or record.get("query"),
        source_cids=_legacy_lists(record, "source_cids", "sourceCids"),
        # Legacy sourceIds are opaque corpus identifiers, not provenance-row
        # IDs or IPFS CIDs.  Only explicitly named provenance columns can be
        # carried into the canonical relationship column.
        provenance_ids=_legacy_lists(record, "provenance_ids", "provenanceIds"),
        route_labels=routes,
        service_tags=_legacy_lists(record, "service_tags", "serviceTags"),
        location_tags=_legacy_lists(record, "location_tags", "locationTags"),
        safety_labels=_legacy_lists(record, "safety_labels", "safetyLabels"),
        license_id=license_id,
        consent_status=consent_status,
        created_at=record.get("created_at") or record.get("createdAt"),
    )


def migrate_legacy_template(
    record: Mapping[str, Any],
    *,
    locale: str = "en-US",
    license_id: str = "NOASSERTION",
    consent_status: str = "unknown",
) -> AbbyVoiceTemplate:
    """Migrate one legacy response-template item."""

    _reject_aggregate(record, ABBY_VOICE_TEMPLATE_V2)
    template_text = str(
        record.get("template_text") or record.get("templateText") or record.get("text") or ""
    ).strip()
    spoken = str(
        record.get("spoken_template") or record.get("spokenTemplate") or template_text
    ).strip()
    intent = str(record.get("intent") or "general").strip()
    slot_names = _legacy_lists(record, "slot_names", "slotNames", "slots")
    if not slot_names:
        slot_errors: list[str] = []
        slot_names = tuple(sorted(_template_placeholders(template_text, "template_text", slot_errors)))
        if slot_errors:
            raise AbbyVoiceSchemaError(ABBY_VOICE_TEMPLATE_V2, slot_errors)
    return AbbyVoiceTemplate(
        template_id=stable_template_id(template_text, spoken, locale, intent),
        template_text=template_text,
        spoken_template=spoken,
        intent=intent,
        locale=locale,
        slot_names=slot_names,
        required_slot_names=_legacy_lists(
            record, "required_slot_names", "requiredSlotNames", "requiredSlots"
        ),
        factual_slot_names=_legacy_lists(
            record, "factual_slot_names", "factualSlotNames", "factualSlots"
        ),
        provenance_ids=_legacy_lists(record, "provenance_ids", "provenanceIds"),
        source_cids=_legacy_lists(record, "source_cids", "sourceCids"),
        safety_labels=_legacy_lists(record, "safety_labels", "safetyLabels"),
        license_id=license_id,
        consent_status=consent_status,
        created_at=record.get("created_at") or record.get("createdAt"),
    )


def migrate_legacy_audio(
    record: Mapping[str, Any],
    *,
    spoken_text: str | None = None,
    response_id: str | None = None,
    locale: str = "en-US",
    license_id: str = "NOASSERTION",
    consent_status: str = "unknown",
) -> AbbyVoiceAudio:
    """Migrate one legacy audio metadata item; audio bytes remain external."""

    _reject_aggregate(record, ABBY_VOICE_AUDIO_V2)
    spoken = str(spoken_text or record.get("spoken_text") or record.get("text") or "").strip()
    digest = str(
        record.get("content_sha256")
        or record.get("audioSha256")
        or record.get("sha256")
        or ""
    ).strip()
    # Truncated legacy textHash values are intentionally not accepted as audio
    # integrity hashes.  Callers must hash the bytes before publishing.
    if not _HASH_RE.fullmatch(digest):
        raise AbbyVoiceSchemaError(
            ABBY_VOICE_AUDIO_V2,
            "legacy audio requires a full audio content_sha256; truncated textHash is insufficient",
        )
    uri = (
        record.get("uri")
        or record.get("preferredAudioPath")
        or record.get("mp3Path")
        or record.get("audioPath")
    )
    media_type = (
        record.get("mime_type")
        or record.get("preferredMimeType")
        or record.get("mp3MimeType")
        or record.get("mimeType")
        or "audio/mpeg"
    )
    resolved_response = response_id or record.get("response_id") or record.get("responseId")
    return AbbyVoiceAudio(
        audio_id=stable_audio_id(digest),
        spoken_text=spoken,
        content_sha256=digest,
        locale=locale,
        uri=str(uri).strip() if uri else None,
        ipfs_cid=record.get("ipfs_cid") or record.get("cid"),
        response_id=str(resolved_response).strip() if resolved_response else None,
        template_id=record.get("template_id") or record.get("templateId"),
        segment_kind=str(record.get("segment_kind") or "response"),
        mime_type=str(media_type),
        byte_length=_first_present(
            record, "byte_length", "preferredBytes", "mp3Bytes", "audioBytes"
        ),
        duration_ms=_first_present(record, "duration_ms", "durationMs"),
        sample_rate_hz=_first_present(record, "sample_rate_hz", "sampleRateHz"),
        channels=record.get("channels"),
        provider=record.get("provider"),
        model=record.get("model"),
        voice=record.get("voice") or record.get("voiceDescription"),
        provenance_ids=_legacy_lists(record, "provenance_ids", "provenanceIds"),
        source_cids=_legacy_lists(record, "source_cids", "sourceCids"),
        safety_labels=_legacy_lists(record, "safety_labels", "safetyLabels"),
        license_id=license_id,
        consent_status=consent_status,
        created_at=record.get("created_at") or record.get("createdAt"),
    )


def migrate_legacy_provenance(
    record: Mapping[str, Any],
    *,
    subject_id: str | None = None,
    subject_schema_version: str | None = None,
    license_id: str = "NOASSERTION",
    consent_status: str = "unknown",
) -> AbbyVoiceProvenance:
    """Migrate one legacy lineage record."""

    _reject_aggregate(record, ABBY_VOICE_PROVENANCE_V2)
    resolved_subject = str(
        subject_id or record.get("subject_id") or record.get("subjectId") or ""
    ).strip()
    resolved_schema = str(
        subject_schema_version
        or record.get("subject_schema_version")
        or record.get("subjectSchemaVersion")
        or ""
    ).strip()
    source_uri = record.get("source_uri") or record.get("sourceUri")
    transformation = str(
        record.get("transformation_name")
        or record.get("transformationName")
        or "legacy_v1_migration"
    ).strip()
    source_revision = record.get("source_revision") or record.get("sourceRevision")
    provenance_id = stable_provenance_id(
        resolved_subject, str(source_uri or ""), transformation, source_revision
    )
    return AbbyVoiceProvenance(
        provenance_id=provenance_id,
        subject_id=resolved_subject,
        subject_schema_version=resolved_schema,
        transformation_name=transformation,
        source_uri=str(source_uri).strip() if source_uri else None,
        source_revision=source_revision,
        source_sha256=record.get("source_sha256") or record.get("sourceSha256"),
        source_cids=_legacy_lists(record, "source_cids", "sourceCids"),
        parent_provenance_ids=_legacy_lists(
            record, "parent_provenance_ids", "parentProvenanceIds"
        ),
        transformation_version=record.get("transformation_version")
        or record.get("transformationVersion"),
        generated_at=record.get("generated_at")
        or record.get("generatedAt")
        or record.get("createdAt"),
        locale=record.get("locale"),
        license_id=license_id,
        consent_status=consent_status,
        consent_id=record.get("consent_id") or record.get("consentId"),
        safety_labels=_legacy_lists(record, "safety_labels", "safetyLabels"),
    )


def migrate_v1_record(
    record: Mapping[str, Any],
    target_schema_version: str,
    **kwargs: Any,
) -> VoiceRow:
    """Migrate exactly one v1 row to an explicitly selected v2 config.

    Aggregate batch manifests are rejected instead of being implicitly
    expanded.  Normalization (G005) owns batch iteration and quarantine policy.
    """

    if not isinstance(record, Mapping):
        raise AbbyVoiceSchemaError(target_schema_version, "legacy record must be a mapping")
    if record.get("schema_version") in SCHEMA_REGISTRY:
        row = parse_abby_voice_record(record)
        if row.SCHEMA_VERSION != target_schema_version:
            raise AbbyVoiceSchemaError(
                target_schema_version,
                f"canonical row belongs to {row.SCHEMA_VERSION}, not {target_schema_version}",
            )
        return row
    migrations = {
        ABBY_VOICE_RESPONSE_V2: migrate_legacy_response,
        ABBY_VOICE_TEMPLATE_V2: migrate_legacy_template,
        ABBY_VOICE_AUDIO_V2: migrate_legacy_audio,
        ABBY_VOICE_PROVENANCE_V2: migrate_legacy_provenance,
    }
    try:
        migration = migrations[target_schema_version]
    except KeyError as exc:
        get_schema_definition(target_schema_version)
        raise AssertionError("unreachable") from exc
    return migration(dict(record), **kwargs)


migrate_legacy_row = migrate_v1_record
migrate_row = migrate_v1_record
validate_abby_voice_bundle = validate_bundle


__all__ = [
    "ABBY_VOICE_AUDIO_V2",
    "ABBY_VOICE_AUDIO_V2_SCHEMA",
    "ABBY_VOICE_PROVENANCE_V2",
    "ABBY_VOICE_PROVENANCE_V2_SCHEMA",
    "ABBY_VOICE_RESPONSE_V2",
    "ABBY_VOICE_RESPONSE_V2_SCHEMA",
    "ABBY_VOICE_TEMPLATE_V2",
    "ABBY_VOICE_TEMPLATE_V2_SCHEMA",
    "AbbyVoiceAudio",
    "AbbyVoiceDatasetBundle",
    "AbbyVoiceProvenance",
    "AbbyVoiceResponse",
    "AbbyVoiceSchemaError",
    "AbbyVoiceTemplate",
    "ColumnSpec",
    "HUGGINGFACE_FEATURE_SPECS",
    "ROW_TYPE_REGISTRY",
    "SCHEMA_DEFINITIONS",
    "SCHEMA_REGISTRY",
    "SCHEMA_VERSIONS",
    "SchemaDefinition",
    "SchemaValidationError",
    "get_arrow_schema",
    "get_huggingface_features",
    "get_pyarrow_schema",
    "get_schema_definition",
    "migrate_legacy_audio",
    "migrate_legacy_provenance",
    "migrate_legacy_response",
    "migrate_legacy_row",
    "migrate_legacy_template",
    "migrate_row",
    "migrate_v1_record",
    "parse_abby_voice_record",
    "schema_columns",
    "sha256_text",
    "stable_audio_id",
    "stable_provenance_id",
    "stable_response_id",
    "stable_template_id",
    "validate_abby_voice_record",
    "validate_abby_voice_bundle",
    "validate_bundle",
    "validate_publishable",
    "validate_record",
    "validate_records",
    "validate_rows",
    "validate_row",
]
