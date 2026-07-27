"""Flat ``abby_voice_evaluation_v2`` schema for Dataset Viewer releases.

Evaluation cases complete the five flat Abby configs including evaluation.
They are never mixed into response, template, audio, or provenance tables, and
they never embed nested JSON objects that would break Hugging Face schema
inference.

Nested v1 golden fixtures (``response_plan`` / ``expected`` objects) are
accepted only through :func:`migrate_evaluation_v1` which flattens them into
scalars and parallel ``list[string]`` columns.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields
from hashlib import sha256
from typing import Any, ClassVar, Final

from .schema import (
    AbbyVoiceSchemaError,
    ColumnSpec,
    SchemaDefinition,
    sha256_text,
)

ABBY_VOICE_EVALUATION_V2: Final = "abby_voice_evaluation_v2"
ABBY_VOICE_EVALUATION_V2_SCHEMA: Final = ABBY_VOICE_EVALUATION_V2
ABBY_VOICE_EVALUATION_V1: Final = "abby_voice_evaluation_v1"

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_LOCALE_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_ALLOWED_CONSENT = frozenset(
    {"granted", "not_required", "unknown", "denied", "withdrawn"}
)
_ALLOWED_STATUS = frozenset({"completed", "degraded", "failed", "skipped"})
_EVAL_SPLITS = frozenset({"validation", "test"})


def _c(name: str, kind: str = "string", nullable: bool = False) -> ColumnSpec:
    return ColumnSpec(name=name, kind=kind, nullable=nullable)


EVALUATION_COLUMNS: tuple[ColumnSpec, ...] = (
    _c("schema_version"),
    _c("evaluation_id"),
    _c("case_id"),
    _c("category"),
    _c("locale"),
    _c("split"),
    _c("reference_transcript"),
    _c("observed_transcript"),
    _c("expected_status"),
    _c("expected_response_text"),
    _c("required_phrases", "list[string]"),
    _c("forbidden_phrases", "list[string]"),
    _c("wer_max", "float64"),
    _c("template_id", nullable=True),
    _c("intent", nullable=True),
    _c("response_confidence", "float64", nullable=True),
    _c("slot_names", "list[string]"),
    _c("slot_values", "list[string]"),
    _c("evidence_source_ids", "list[string]"),
    _c("evidence_cids", "list[string]"),
    _c("safety_labels", "list[string]"),
    _c("content_sha256"),
    _c("license_id"),
    _c("consent_status"),
)

EVALUATION_COLUMN_NAMES: tuple[str, ...] = tuple(
    column.name for column in EVALUATION_COLUMNS
)


def stable_evaluation_id(
    case_id: str,
    *,
    category: str,
    locale: str,
    reference_transcript: str,
) -> str:
    """Build a deterministic evaluation ID from semantic case content."""

    payload = {
        "case_id": case_id,
        "category": category,
        "locale": locale,
        "reference_transcript": reference_transcript,
    }
    digest = sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return f"evaluation-{digest[:24]}"


def _tuple_of_strings(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        raise TypeError(f"{field_name} must be a list or tuple of strings, not null")
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, (list, tuple)):
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


@dataclass(frozen=True, slots=True)
class AbbyVoiceEvaluation:
    """One flat safety/quality evaluation case for Dataset Viewer."""

    evaluation_id: str
    case_id: str
    category: str
    reference_transcript: str
    observed_transcript: str
    expected_status: str
    expected_response_text: str
    required_phrases: tuple[str, ...] = ()
    forbidden_phrases: tuple[str, ...] = ()
    wer_max: float = 0.0
    locale: str = "en-US"
    split: str = "validation"
    template_id: str | None = None
    intent: str | None = None
    response_confidence: float | None = None
    slot_names: tuple[str, ...] = ()
    slot_values: tuple[str, ...] = ()
    evidence_source_ids: tuple[str, ...] = ()
    evidence_cids: tuple[str, ...] = ()
    safety_labels: tuple[str, ...] = ()
    content_sha256: str | None = None
    license_id: str = "CC0-1.0"
    consent_status: str = "not_required"
    schema_version: str = field(default=ABBY_VOICE_EVALUATION_V2, init=False)

    SCHEMA_VERSION: ClassVar[str] = ABBY_VOICE_EVALUATION_V2
    ID_FIELD: ClassVar[str] = "evaluation_id"
    LIST_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "required_phrases",
            "forbidden_phrases",
            "slot_names",
            "slot_values",
            "evidence_source_ids",
            "evidence_cids",
            "safety_labels",
        }
    )

    def __post_init__(self) -> None:
        for name in self.LIST_FIELDS:
            object.__setattr__(
                self, name, _tuple_of_strings(getattr(self, name), name)
            )
        for name in (
            "evaluation_id",
            "case_id",
            "category",
            "reference_transcript",
            "observed_transcript",
            "expected_status",
            "expected_response_text",
            "locale",
            "split",
            "license_id",
            "consent_status",
        ):
            value = getattr(self, name)
            if isinstance(value, str):
                object.__setattr__(self, name, value.strip())
        if self.template_id is not None and isinstance(self.template_id, str):
            object.__setattr__(self, "template_id", self.template_id.strip() or None)
        if self.intent is not None and isinstance(self.intent, str):
            object.__setattr__(self, "intent", self.intent.strip() or None)
        if self.content_sha256 is None:
            object.__setattr__(
                self,
                "content_sha256",
                sha256_text(
                    "\n".join(
                        (
                            self.case_id,
                            self.reference_transcript,
                            self.expected_response_text,
                        )
                    )
                ),
            )
        errors = self._validate()
        if errors:
            raise AbbyVoiceSchemaError(self.SCHEMA_VERSION, errors)

    def _validate(self) -> list[str]:
        errors: list[str] = []
        if self.schema_version != ABBY_VOICE_EVALUATION_V2:
            errors.append(f"schema_version must equal {ABBY_VOICE_EVALUATION_V2!r}")
        for name in (
            "evaluation_id",
            "case_id",
            "category",
            "reference_transcript",
            "observed_transcript",
            "expected_response_text",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                errors.append(f"{name} must be a non-empty string")
        if isinstance(self.evaluation_id, str) and self.evaluation_id and not _ID_RE.fullmatch(
            self.evaluation_id
        ):
            errors.append("evaluation_id contains unsupported characters")
        if isinstance(self.case_id, str) and self.case_id and not _ID_RE.fullmatch(self.case_id):
            errors.append("case_id contains unsupported characters")
        if not isinstance(self.locale, str) or not _LOCALE_RE.fullmatch(self.locale):
            errors.append("locale must be a BCP-47 language tag")
        if self.split not in _EVAL_SPLITS:
            errors.append("split must be 'validation' or 'test'")
        if self.expected_status not in _ALLOWED_STATUS:
            errors.append(
                "expected_status must be one of " + ", ".join(sorted(_ALLOWED_STATUS))
            )
        if not isinstance(self.wer_max, (int, float)) or isinstance(self.wer_max, bool):
            errors.append("wer_max must be a finite number >= 0")
        elif not math.isfinite(float(self.wer_max)) or float(self.wer_max) < 0:
            errors.append("wer_max must be a finite number >= 0")
        if self.response_confidence is not None:
            if (
                not isinstance(self.response_confidence, (int, float))
                or isinstance(self.response_confidence, bool)
                or not math.isfinite(float(self.response_confidence))
                or not 0.0 <= float(self.response_confidence) <= 1.0
            ):
                errors.append("response_confidence must be a finite number in [0, 1]")
        if len(self.slot_names) != len(self.slot_values):
            errors.append("slot_names and slot_values must have equal lengths")
        if not isinstance(self.content_sha256, str) or not _HASH_RE.fullmatch(
            self.content_sha256
        ):
            errors.append("content_sha256 must be a full lower-case SHA-256 digest")
        if self.consent_status not in _ALLOWED_CONSENT:
            errors.append(
                "consent_status must be one of " + ", ".join(sorted(_ALLOWED_CONSENT))
            )
        if not isinstance(self.license_id, str) or not self.license_id:
            errors.append("license_id must be a non-empty string")
        if not self.required_phrases:
            errors.append("required_phrases must contain at least one phrase")
        if "synthetic_public_fixture" not in self.safety_labels and "public_fixture" not in {
            label.casefold() for label in self.safety_labels
        }:
            # Soft documentation: evaluation releases should only ship public fixtures.
            # Hard-require at least one safety label for traceability.
            if not self.safety_labels:
                errors.append("safety_labels must not be empty")
        return errors

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for column in EVALUATION_COLUMNS:
            value = getattr(self, column.name)
            result[column.name] = list(value) if column.name in self.LIST_FIELDS else value
        return result

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any], *, strict: bool = True
    ) -> AbbyVoiceEvaluation:
        if not isinstance(data, Mapping):
            raise AbbyVoiceSchemaError(
                ABBY_VOICE_EVALUATION_V2, "record must be a mapping"
            )
        if data.get("schema_version") == ABBY_VOICE_EVALUATION_V1:
            data = migrate_evaluation_v1(data)
        actual = data.get("schema_version")
        if actual != ABBY_VOICE_EVALUATION_V2:
            raise AbbyVoiceSchemaError(
                ABBY_VOICE_EVALUATION_V2,
                f"schema_version must equal {ABBY_VOICE_EVALUATION_V2!r}, got {actual!r}",
            )
        allowed = set(EVALUATION_COLUMN_NAMES)
        unknown = sorted(set(data) - allowed)
        if strict and unknown:
            raise AbbyVoiceSchemaError(
                ABBY_VOICE_EVALUATION_V2, f"unknown columns: {', '.join(unknown)}"
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
            raise AbbyVoiceSchemaError(ABBY_VOICE_EVALUATION_V2, str(exc)) from exc


EVALUATION_SCHEMA_DEFINITION = SchemaDefinition(
    ABBY_VOICE_EVALUATION_V2,
    "evaluation_id",
    AbbyVoiceEvaluation,
    EVALUATION_COLUMNS,
)


def migrate_evaluation_v1(record: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten a nested v1 golden fixture into ``abby_voice_evaluation_v2``."""

    if not isinstance(record, Mapping):
        raise AbbyVoiceSchemaError(
            ABBY_VOICE_EVALUATION_V2, "v1 evaluation record must be a mapping"
        )
    if record.get("schema_version") not in {
        ABBY_VOICE_EVALUATION_V1,
        ABBY_VOICE_EVALUATION_V2,
        None,
    }:
        raise AbbyVoiceSchemaError(
            ABBY_VOICE_EVALUATION_V2,
            f"unsupported evaluation schema_version {record.get('schema_version')!r}",
        )
    if record.get("schema_version") == ABBY_VOICE_EVALUATION_V2:
        return dict(record)

    case_id = str(record.get("case_id") or "").strip()
    category = str(record.get("category") or "").strip()
    locale = str(record.get("locale") or "en-US").strip()
    reference = str(record.get("reference_transcript") or "").strip()
    observed = str(record.get("observed_transcript") or reference).strip()
    expected = record.get("expected") if isinstance(record.get("expected"), Mapping) else {}
    plan = record.get("response_plan") if isinstance(record.get("response_plan"), Mapping) else None
    slots = plan.get("slots") if plan and isinstance(plan.get("slots"), list) else []
    evidence = plan.get("evidence") if plan and isinstance(plan.get("evidence"), list) else []
    slot_names: list[str] = []
    slot_values: list[str] = []
    for slot in slots:
        if not isinstance(slot, Mapping):
            continue
        name = str(slot.get("name") or "").strip()
        value = str(slot.get("value") or "").strip()
        if name and value:
            slot_names.append(name)
            slot_values.append(value)
    evidence_source_ids: list[str] = []
    evidence_cids: list[str] = []
    for item in evidence:
        if not isinstance(item, Mapping):
            continue
        source_id = str(item.get("source_id") or "").strip()
        cid = str(item.get("cid") or "").strip()
        if source_id:
            evidence_source_ids.append(source_id)
        if cid:
            evidence_cids.append(cid)
    safety = record.get("safety_labels") or []
    if not isinstance(safety, list):
        safety = []
    split = str(record.get("split") or "validation").strip()
    if split not in _EVAL_SPLITS:
        # Deterministic bucket from case_id keeps related fixtures stable.
        digest = int.from_bytes(sha256(case_id.encode("utf-8")).digest()[:8], "big")
        split = "test" if digest % 5 == 0 else "validation"
    evaluation_id = str(record.get("evaluation_id") or "").strip() or stable_evaluation_id(
        case_id,
        category=category,
        locale=locale,
        reference_transcript=reference,
    )
    confidence = None
    if plan is not None and plan.get("confidence") is not None:
        confidence = float(plan["confidence"])
    required = expected.get("required_phrases") if isinstance(expected, Mapping) else None
    forbidden = expected.get("forbidden_phrases") if isinstance(expected, Mapping) else None
    if not isinstance(required, list) or not required:
        required = [str(expected.get("response_text") or reference)[:64] or "case"]
    if not isinstance(forbidden, list):
        forbidden = []
    return {
        "schema_version": ABBY_VOICE_EVALUATION_V2,
        "evaluation_id": evaluation_id,
        "case_id": case_id,
        "category": category,
        "locale": locale,
        "split": split,
        "reference_transcript": reference,
        "observed_transcript": observed,
        "expected_status": str(expected.get("status") or "completed"),
        "expected_response_text": str(expected.get("response_text") or ""),
        "required_phrases": [str(item) for item in required],
        "forbidden_phrases": [str(item) for item in forbidden],
        "wer_max": float(expected.get("wer_max") or 0.0),
        "template_id": (
            str(plan.get("template_id")).strip()
            if plan and plan.get("template_id")
            else None
        ),
        "intent": (
            str(plan.get("intent")).strip() if plan and plan.get("intent") else None
        ),
        "response_confidence": confidence,
        "slot_names": slot_names,
        "slot_values": slot_values,
        "evidence_source_ids": evidence_source_ids,
        "evidence_cids": evidence_cids,
        "safety_labels": [str(item) for item in safety],
        "content_sha256": sha256_text("\n".join((case_id, reference, str(expected.get("response_text") or "")))),
        "license_id": str(record.get("license_id") or "CC0-1.0"),
        "consent_status": str(record.get("consent_status") or "not_required"),
    }


def parse_evaluation_record(
    record: Mapping[str, Any] | AbbyVoiceEvaluation, *, strict: bool = True
) -> AbbyVoiceEvaluation:
    """Validate and return one typed evaluation row."""

    if isinstance(record, AbbyVoiceEvaluation):
        errors = record._validate()
        if errors:
            raise AbbyVoiceSchemaError(ABBY_VOICE_EVALUATION_V2, errors)
        return record
    return AbbyVoiceEvaluation.from_dict(record, strict=strict)


def validate_evaluation_rows(
    records: Iterable[Mapping[str, Any] | AbbyVoiceEvaluation],
    *,
    strict: bool = True,
) -> tuple[AbbyVoiceEvaluation, ...]:
    """Validate evaluation rows and reject duplicate evaluation or case IDs."""

    parsed: list[AbbyVoiceEvaluation] = []
    seen_eval: set[str] = set()
    seen_case: set[str] = set()
    for index, record in enumerate(records):
        row = parse_evaluation_record(record, strict=strict)
        if row.evaluation_id in seen_eval:
            raise AbbyVoiceSchemaError(
                ABBY_VOICE_EVALUATION_V2,
                f"row {index}: duplicate evaluation_id {row.evaluation_id!r}",
            )
        if row.case_id in seen_case:
            raise AbbyVoiceSchemaError(
                ABBY_VOICE_EVALUATION_V2,
                f"row {index}: duplicate case_id {row.case_id!r}",
            )
        seen_eval.add(row.evaluation_id)
        seen_case.add(row.case_id)
        parsed.append(row)
    return tuple(parsed)


def get_evaluation_pyarrow_schema() -> Any:
    """Build a fixed ``pyarrow.Schema`` for the evaluation config."""

    try:
        import pyarrow as pa
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "get_evaluation_pyarrow_schema requires the optional 'pyarrow' package"
        ) from exc
    types = {
        "string": pa.string(),
        "int64": pa.int64(),
        "float64": pa.float64(),
        "list[string]": pa.list_(pa.string()),
    }
    return pa.schema(
        [
            pa.field(column.name, types[column.kind], nullable=column.nullable)
            for column in EVALUATION_COLUMNS
        ],
        metadata={
            b"abby_voice_schema_version": ABBY_VOICE_EVALUATION_V2.encode("utf-8"),
            b"abby_voice_flat_contract": b"2",
        },
    )


__all__ = [
    "ABBY_VOICE_EVALUATION_V1",
    "ABBY_VOICE_EVALUATION_V2",
    "ABBY_VOICE_EVALUATION_V2_SCHEMA",
    "EVALUATION_COLUMNS",
    "EVALUATION_COLUMN_NAMES",
    "EVALUATION_SCHEMA_DEFINITION",
    "AbbyVoiceEvaluation",
    "get_evaluation_pyarrow_schema",
    "migrate_evaluation_v1",
    "parse_evaluation_record",
    "stable_evaluation_id",
    "validate_evaluation_rows",
]
