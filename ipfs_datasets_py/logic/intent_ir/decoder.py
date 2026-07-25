"""Fail-closed decoding and explicit v0.1-to-v1 migration for Intent IR."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, TypeVar

from ..ir_core.schema_registry import (
    IRSchemaRegistry,
    MigrationLoss,
    MigrationOutcome,
    MigrationReceipt,
    MigrationSpec,
    SchemaSpec,
)
from .schema import (
    INTENT_IR_SCHEMA_VERSION,
    LEGACY_INTENT_IR_SCHEMA_VERSION,
    ControlEdgeKind,
    IntentAction,
    IntentControlEdge,
    IntentIRDocument,
    IntentIRValidationError,
    IntentKind,
    IntentModality,
    IntentStatement,
    NodeGrounding,
    ReviewStatus,
    SourceRef,
    SourceSpan,
    StatementKind,
    validate_intent_ir,
)

INTENT_IR_V0_1_TO_V1_MIGRATION_ID = "intent-ir-v0.1-to-v1"


class IntentIRDecodeError(IntentIRValidationError):
    """Raised when an untrusted wire document cannot be decoded exactly."""


class MigrationSeverity(str, Enum):
    """Machine-readable importance of a migration diagnostic."""

    INFO = "info"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class MigrationDiagnostic:
    """One explicit transformation performed while migrating a document."""

    code: str
    path: str
    message: str
    severity: MigrationSeverity = MigrationSeverity.INFO
    lossy: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "lossy": self.lossy,
            "message": self.message,
            "path": self.path,
            "severity": self.severity.value,
        }


@dataclass(frozen=True, slots=True)
class IntentIRMigrationResult:
    """A decoded v1 document plus an immutable migration audit trail."""

    document: IntentIRDocument
    source_version: str
    target_version: str
    diagnostics: tuple[MigrationDiagnostic, ...] = ()
    receipt: MigrationReceipt | None = None

    @property
    def loss_diagnostics(self) -> tuple[MigrationDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.lossy)

    @property
    def is_lossless(self) -> bool:
        return not self.loss_diagnostics


_DOCUMENT_FIELDS = {
    "schema_version",
    "document_id",
    "title",
    "intent_kind",
    "sources",
    "statements",
    "actions",
    "control_edges",
    "entry_action_ids",
    "terminal_action_ids",
    "tags",
}
_SOURCE_FIELDS = {
    "ref_id",
    "source_uri",
    "source_id",
    "source_revision",
    "content_sha256",
    "container_uri",
    "container_sha256",
    "content_cid",
    "license_expression",
    "review_status",
    "span",
}
_STATEMENT_FIELDS = {
    "statement_id",
    "kind",
    "modality",
    "normalized_text",
    "source_ref_ids",
    "predicate",
    "arguments",
    "confidence",
    "review_status",
    "grounding",
}
_ACTION_FIELDS = {
    "action_id",
    "actor",
    "verb",
    "object_refs",
    "source_ref_ids",
    "tool_refs",
    "input_refs",
    "output_refs",
    "precondition_ids",
    "effect_ids",
    "verification_ids",
    "grounding",
}
_EDGE_FIELDS = {
    "edge_id",
    "source_action_id",
    "target_action_id",
    "kind",
    "guard_statement_id",
    "source_ref_ids",
    "grounding",
}
_SPAN_FIELDS = {"start_char", "end_char"}

_DOCUMENT_REQUIRED = {
    "schema_version",
    "document_id",
    "title",
    "intent_kind",
    "sources",
    "statements",
}
_SOURCE_REQUIRED = {
    "ref_id",
    "source_uri",
    "source_id",
    "source_revision",
    "content_sha256",
}
_STATEMENT_REQUIRED = {
    "statement_id",
    "kind",
    "modality",
    "normalized_text",
    "source_ref_ids",
    "grounding",
}
_ACTION_REQUIRED = {
    "action_id",
    "actor",
    "verb",
    "object_refs",
    "source_ref_ids",
    "grounding",
}
_EDGE_REQUIRED = {
    "edge_id",
    "source_action_id",
    "target_action_id",
    "grounding",
}

_LEGACY_STATEMENT_FIELDS = _STATEMENT_FIELDS - {"grounding"}
_LEGACY_ACTION_FIELDS = _ACTION_FIELDS - {"grounding"}
_LEGACY_EDGE_FIELDS = _EDGE_FIELDS - {"grounding"}

_E = TypeVar("_E", bound=Enum)


def decode_intent_ir(
    payload: Mapping[str, Any] | str | bytes | bytearray,
) -> IntentIRDocument:
    """Decode one exact v1 wire document into immutable typed records.

    The decoder rejects missing or unknown versions, unknown object fields,
    duplicate JSON keys, non-JSON values, untyped enum values, duplicate
    members of set-like collections, and every dangling internal reference.
    It never retains mutable collections from the caller.
    """

    raw = _load_payload(payload)
    version = raw.get("schema_version")
    if version != INTENT_IR_SCHEMA_VERSION:
        raise IntentIRDecodeError(
            f"Unsupported Intent IR schema_version: {version!r}; "
            f"expected {INTENT_IR_SCHEMA_VERSION!r}"
        )
    return _decode_v1(raw)


def migrate_intent_ir(
    payload: Mapping[str, Any] | str | bytes | bytearray,
    *,
    allow_lossy: bool = True,
) -> IntentIRMigrationResult:
    """Decode v1 or migrate the sole supported legacy version, v0.1.

    Because v0.1 did not record node grounding, every legacy migration reports
    that unrecoverable distinction as a loss. Duplicate members in legacy
    set-like arrays are also removed and reported. Set ``allow_lossy=False`` to
    fail closed instead. No unknown version, field, or internal reference is
    accepted.
    """

    raw = _load_payload(payload)
    version = raw.get("schema_version")
    if version == INTENT_IR_SCHEMA_VERSION:
        return IntentIRMigrationResult(
            document=_decode_v1(raw),
            source_version=INTENT_IR_SCHEMA_VERSION,
            target_version=INTENT_IR_SCHEMA_VERSION,
        )
    if version != LEGACY_INTENT_IR_SCHEMA_VERSION:
        raise IntentIRDecodeError(
            f"Unsupported Intent IR schema_version: {version!r}; supported "
            f"versions are {LEGACY_INTENT_IR_SCHEMA_VERSION!r} and "
            f"{INTENT_IR_SCHEMA_VERSION!r}"
        )

    pre_migrated, diagnostics = _migrate_v0_1(raw)
    _decode_v1(pre_migrated)
    losses = tuple(item for item in diagnostics if item.lossy)
    if losses and not allow_lossy:
        paths = ", ".join(item.path for item in losses)
        raise IntentIRDecodeError(
            f"Intent IR migration would be lossy at: {paths}"
        )
    registry_result = INTENT_IR_SCHEMA_REGISTRY.migrate(
        raw,
        source_schema_id=LEGACY_INTENT_IR_SCHEMA_VERSION,
        destination_schema_id=INTENT_IR_SCHEMA_VERSION,
    )
    migrated = _thaw_registry_json(registry_result.payload)
    if not isinstance(migrated, dict):  # Registry payloads are always objects.
        raise IntentIRDecodeError("Intent IR migration returned a non-object")
    return IntentIRMigrationResult(
        document=_decode_v1(migrated),
        source_version=LEGACY_INTENT_IR_SCHEMA_VERSION,
        target_version=INTENT_IR_SCHEMA_VERSION,
        diagnostics=tuple(diagnostics),
        receipt=registry_result.receipt,
    )


def decode_intent_ir_with_migration(
    payload: Mapping[str, Any] | str | bytes | bytearray,
    *,
    allow_lossy: bool = True,
) -> IntentIRMigrationResult:
    """Named alias for callers that want migration diagnostics at decode time."""

    return migrate_intent_ir(payload, allow_lossy=allow_lossy)


def _decode_v1(raw: Mapping[str, Any]) -> IntentIRDocument:
    _check_fields(raw, _DOCUMENT_FIELDS, _DOCUMENT_REQUIRED, "$")
    document = IntentIRDocument(
        schema_version=_string(raw["schema_version"], "$.schema_version"),
        document_id=_string(raw["document_id"], "$.document_id"),
        title=_string(raw["title"], "$.title"),
        intent_kind=_enum(IntentKind, raw["intent_kind"], "$.intent_kind"),
        sources=tuple(
            _decode_source(item, f"$.sources[{index}]")
            for index, item in enumerate(_array(raw["sources"], "$.sources"))
        ),
        statements=tuple(
            _decode_statement(item, f"$.statements[{index}]")
            for index, item in enumerate(
                _array(raw["statements"], "$.statements")
            )
        ),
        actions=tuple(
            _decode_action(item, f"$.actions[{index}]")
            for index, item in enumerate(
                _array(raw.get("actions", []), "$.actions")
            )
        ),
        control_edges=tuple(
            _decode_edge(item, f"$.control_edges[{index}]")
            for index, item in enumerate(
                _array(raw.get("control_edges", []), "$.control_edges")
            )
        ),
        entry_action_ids=_string_tuple(
            raw.get("entry_action_ids", []), "$.entry_action_ids"
        ),
        terminal_action_ids=_string_tuple(
            raw.get("terminal_action_ids", []), "$.terminal_action_ids"
        ),
        tags=_string_tuple(raw.get("tags", []), "$.tags"),
    )
    try:
        return validate_intent_ir(document)
    except IntentIRDecodeError:
        raise
    except IntentIRValidationError as exc:
        raise IntentIRDecodeError(str(exc)) from exc


def _decode_source(value: Any, path: str) -> SourceRef:
    raw = _object(value, path)
    _check_fields(raw, _SOURCE_FIELDS, _SOURCE_REQUIRED, path)
    span_value = raw.get("span")
    span = None
    if span_value is not None:
        span_raw = _object(span_value, f"{path}.span")
        _check_fields(
            span_raw, _SPAN_FIELDS, _SPAN_FIELDS, f"{path}.span"
        )
        span = SourceSpan(
            start_char=_integer(
                span_raw["start_char"], f"{path}.span.start_char"
            ),
            end_char=_integer(
                span_raw["end_char"], f"{path}.span.end_char"
            ),
        )
    return SourceRef(
        ref_id=_string(raw["ref_id"], f"{path}.ref_id"),
        source_uri=_string(raw["source_uri"], f"{path}.source_uri"),
        source_id=_string(raw["source_id"], f"{path}.source_id"),
        source_revision=_string(
            raw["source_revision"], f"{path}.source_revision"
        ),
        content_sha256=_string(
            raw["content_sha256"], f"{path}.content_sha256"
        ),
        container_uri=_string(
            raw.get("container_uri", ""), f"{path}.container_uri"
        ),
        container_sha256=_string(
            raw.get("container_sha256", ""), f"{path}.container_sha256"
        ),
        content_cid=_string(
            raw.get("content_cid", ""), f"{path}.content_cid"
        ),
        license_expression=_string(
            raw.get("license_expression", ""), f"{path}.license_expression"
        ),
        review_status=_enum(
            ReviewStatus,
            raw.get("review_status", ReviewStatus.UNREVIEWED.value),
            f"{path}.review_status",
        ),
        span=span,
    )


def _decode_statement(value: Any, path: str) -> IntentStatement:
    raw = _object(value, path)
    _check_fields(raw, _STATEMENT_FIELDS, _STATEMENT_REQUIRED, path)
    return IntentStatement(
        statement_id=_string(raw["statement_id"], f"{path}.statement_id"),
        kind=_enum(StatementKind, raw["kind"], f"{path}.kind"),
        modality=_enum(IntentModality, raw["modality"], f"{path}.modality"),
        normalized_text=_string(
            raw["normalized_text"], f"{path}.normalized_text"
        ),
        source_ref_ids=_string_tuple(
            raw["source_ref_ids"], f"{path}.source_ref_ids"
        ),
        predicate=_string(raw.get("predicate", ""), f"{path}.predicate"),
        arguments=_string_tuple(raw.get("arguments", []), f"{path}.arguments"),
        confidence=_number(raw.get("confidence", 1.0), f"{path}.confidence"),
        review_status=_enum(
            ReviewStatus,
            raw.get("review_status", ReviewStatus.MACHINE_EXTRACTED.value),
            f"{path}.review_status",
        ),
        grounding=_enum(NodeGrounding, raw["grounding"], f"{path}.grounding"),
    )


def _decode_action(value: Any, path: str) -> IntentAction:
    raw = _object(value, path)
    _check_fields(raw, _ACTION_FIELDS, _ACTION_REQUIRED, path)
    return IntentAction(
        action_id=_string(raw["action_id"], f"{path}.action_id"),
        actor=_string(raw["actor"], f"{path}.actor"),
        verb=_string(raw["verb"], f"{path}.verb"),
        object_refs=_string_tuple(raw["object_refs"], f"{path}.object_refs"),
        source_ref_ids=_string_tuple(
            raw["source_ref_ids"], f"{path}.source_ref_ids"
        ),
        tool_refs=_string_tuple(raw.get("tool_refs", []), f"{path}.tool_refs"),
        input_refs=_string_tuple(
            raw.get("input_refs", []), f"{path}.input_refs"
        ),
        output_refs=_string_tuple(
            raw.get("output_refs", []), f"{path}.output_refs"
        ),
        precondition_ids=_string_tuple(
            raw.get("precondition_ids", []), f"{path}.precondition_ids"
        ),
        effect_ids=_string_tuple(
            raw.get("effect_ids", []), f"{path}.effect_ids"
        ),
        verification_ids=_string_tuple(
            raw.get("verification_ids", []), f"{path}.verification_ids"
        ),
        grounding=_enum(NodeGrounding, raw["grounding"], f"{path}.grounding"),
    )


def _decode_edge(value: Any, path: str) -> IntentControlEdge:
    raw = _object(value, path)
    _check_fields(raw, _EDGE_FIELDS, _EDGE_REQUIRED, path)
    return IntentControlEdge(
        edge_id=_string(raw["edge_id"], f"{path}.edge_id"),
        source_action_id=_string(
            raw["source_action_id"], f"{path}.source_action_id"
        ),
        target_action_id=_string(
            raw["target_action_id"], f"{path}.target_action_id"
        ),
        kind=_enum(
            ControlEdgeKind,
            raw.get("kind", ControlEdgeKind.NEXT.value),
            f"{path}.kind",
        ),
        guard_statement_id=_string(
            raw.get("guard_statement_id", ""), f"{path}.guard_statement_id"
        ),
        source_ref_ids=_string_tuple(
            raw.get("source_ref_ids", []), f"{path}.source_ref_ids"
        ),
        grounding=_enum(NodeGrounding, raw["grounding"], f"{path}.grounding"),
    )


def _migrate_v0_1(
    raw: Mapping[str, Any],
) -> tuple[dict[str, Any], list[MigrationDiagnostic]]:
    _check_fields(raw, _DOCUMENT_FIELDS, _DOCUMENT_REQUIRED, "$")
    migrated = _plain_object(raw, "$")
    diagnostics: list[MigrationDiagnostic] = []

    for collection_name, allowed, required in (
        ("sources", _SOURCE_FIELDS, _SOURCE_REQUIRED),
        (
            "statements",
            _LEGACY_STATEMENT_FIELDS,
            _STATEMENT_REQUIRED - {"grounding"},
        ),
        (
            "actions",
            _LEGACY_ACTION_FIELDS,
            _ACTION_REQUIRED - {"grounding"},
        ),
        (
            "control_edges",
            _LEGACY_EDGE_FIELDS,
            _EDGE_REQUIRED - {"grounding"},
        ),
    ):
        for index, item in enumerate(
            _array(migrated.get(collection_name, []), f"$.{collection_name}")
        ):
            item_path = f"$.{collection_name}[{index}]"
            _check_fields(_object(item, item_path), allowed, required, item_path)

    set_paths: list[tuple[dict[str, Any], str, str]] = [
        (migrated, "entry_action_ids", "$.entry_action_ids"),
        (migrated, "terminal_action_ids", "$.terminal_action_ids"),
        (migrated, "tags", "$.tags"),
    ]
    for index, item in enumerate(migrated.get("statements", [])):
        set_paths.append(
            (item, "source_ref_ids", f"$.statements[{index}].source_ref_ids")
        )
    for index, item in enumerate(migrated.get("actions", [])):
        for name in (
            "object_refs",
            "source_ref_ids",
            "tool_refs",
            "input_refs",
            "output_refs",
            "precondition_ids",
            "effect_ids",
            "verification_ids",
        ):
            set_paths.append((item, name, f"$.actions[{index}].{name}"))
    for index, item in enumerate(migrated.get("control_edges", [])):
        set_paths.append(
            (item, "source_ref_ids", f"$.control_edges[{index}].source_ref_ids")
        )

    for owner, name, path in set_paths:
        if name not in owner:
            continue
        original = _array(owner[name], path)
        unique: list[Any] = []
        for value in original:
            if value not in unique:
                unique.append(value)
        if len(unique) != len(original):
            owner[name] = unique
            diagnostics.append(
                MigrationDiagnostic(
                    code="duplicate_set_members_removed",
                    path=path,
                    message=(
                        f"Removed {len(original) - len(unique)} duplicate "
                        "member(s) from a set-like collection"
                    ),
                    severity=MigrationSeverity.WARNING,
                    lossy=True,
                )
            )

    for collection_name in ("statements", "actions", "control_edges"):
        for index, item in enumerate(migrated.get(collection_name, [])):
            path = f"$.{collection_name}[{index}].grounding"
            if collection_name == "control_edges" and not item.get(
                "source_ref_ids", []
            ):
                grounding = NodeGrounding.INFERRED.value
                message = (
                    "Classified a legacy edge without source references as inferred"
                )
            else:
                grounding = NodeGrounding.GROUNDED.value
                message = "Classified a legacy source-referenced node as grounded"
            item["grounding"] = grounding
            diagnostics.append(
                MigrationDiagnostic(
                    code="node_grounding_classified",
                    path=path,
                    message=message,
                )
            )

    diagnostics.append(
        MigrationDiagnostic(
            code="legacy_grounding_ambiguity",
            path="$.statements|actions|control_edges",
            message=(
                "v0.1 did not encode grounded-versus-inferred status; v1 "
                "classification is deterministic but cannot recover that "
                "missing authorial distinction"
            ),
            severity=MigrationSeverity.WARNING,
            lossy=True,
        )
    )
    migrated["schema_version"] = INTENT_IR_SCHEMA_VERSION
    diagnostics.append(
        MigrationDiagnostic(
            code="schema_version_upgraded",
            path="$.schema_version",
            message=(
                f"Upgraded {LEGACY_INTENT_IR_SCHEMA_VERSION} to "
                f"{INTENT_IR_SCHEMA_VERSION}"
            ),
        )
    )
    return migrated, diagnostics


def _registry_migrate_v0_1(
    payload: Mapping[str, Any],
) -> MigrationOutcome:
    """Shared-registry transform with content-bound loss evidence."""

    thawed = _thaw_registry_json(payload)
    if not isinstance(thawed, dict):
        raise IntentIRDecodeError("Legacy Intent IR payload must be an object")
    migrated, diagnostics = _migrate_v0_1(thawed)
    canonical = _decode_v1(migrated).to_dict()
    losses = tuple(
        MigrationLoss(
            code=item.code.replace("_", "-"),
            field_path=item.path,
            message=item.message,
        )
        for item in diagnostics
        if item.lossy
    )
    return MigrationOutcome(canonical, losses)


def _load_payload(
    payload: Mapping[str, Any] | str | bytes | bytearray,
) -> dict[str, Any]:
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = bytes(payload).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IntentIRDecodeError("Intent IR bytes must be UTF-8") from exc
    if isinstance(payload, str):
        try:
            value = json.loads(
                payload,
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=_reject_non_finite_json_number,
            )
        except (json.JSONDecodeError, IntentIRDecodeError) as exc:
            if isinstance(exc, IntentIRDecodeError):
                raise
            raise IntentIRDecodeError(f"Invalid Intent IR JSON: {exc.msg}") from exc
    else:
        value = payload
    return _plain_object(_object(value, "$"), "$")


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IntentIRDecodeError(f"Duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_non_finite_json_number(value: str) -> None:
    raise IntentIRDecodeError(f"Non-finite JSON number is not allowed: {value}")


def _plain_object(value: Mapping[str, Any], path: str) -> dict[str, Any]:
    return {
        key: _plain_json(item, f"{path}.{key}")
        for key, item in value.items()
        if _validate_key(key, path)
    }


def _plain_json(value: Any, path: str) -> Any:
    if isinstance(value, Mapping):
        return _plain_object(value, path)
    if isinstance(value, list):
        return [
            _plain_json(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise IntentIRDecodeError(f"{path} contains a non-JSON value")


def _thaw_registry_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _thaw_registry_json(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_thaw_registry_json(item) for item in value]
    return value


def _validate_key(key: Any, path: str) -> bool:
    if not isinstance(key, str):
        raise IntentIRDecodeError(f"{path} contains a non-string object key")
    return True


def _object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IntentIRDecodeError(f"{path} must be an object")
    return value


def _array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise IntentIRDecodeError(f"{path} must be an array")
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise IntentIRDecodeError(f"{path} must be a string")
    return value


def _integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IntentIRDecodeError(f"{path} must be an integer")
    return value


def _number(value: Any, path: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise IntentIRDecodeError(f"{path} must be a finite number")
    return float(value)


def _string_tuple(value: Any, path: str) -> tuple[str, ...]:
    return tuple(
        _string(item, f"{path}[{index}]")
        for index, item in enumerate(_array(value, path))
    )


def _enum(enum_type: type[_E], value: Any, path: str) -> _E:
    value = _string(value, path)
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(repr(item.value) for item in enum_type)
        raise IntentIRDecodeError(
            f"{path} has unknown value {value!r}; expected one of {allowed}"
        ) from exc


def _check_fields(
    value: Mapping[str, Any],
    allowed: set[str],
    required: set[str],
    path: str,
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise IntentIRDecodeError(
            f"{path} contains unknown fields: {', '.join(unknown)}"
        )
    missing = sorted(required - set(value))
    if missing:
        raise IntentIRDecodeError(
            f"{path} is missing required fields: {', '.join(missing)}"
        )


INTENT_IR_SCHEMA_REGISTRY = IRSchemaRegistry(
    schemas=(
        SchemaSpec(
            LEGACY_INTENT_IR_SCHEMA_VERSION,
            "Legacy Intent IR scaffold without explicit node grounding",
        ),
        SchemaSpec(
            INTENT_IR_SCHEMA_VERSION,
            "Closed Intent IR v1 wire contract",
        ),
    ),
    migrations=(
        MigrationSpec(
            migration_id=INTENT_IR_V0_1_TO_V1_MIGRATION_ID,
            source_schema_id=LEGACY_INTENT_IR_SCHEMA_VERSION,
            destination_schema_id=INTENT_IR_SCHEMA_VERSION,
            transform=_registry_migrate_v0_1,
            lossy=True,
            description=(
                "Classify legacy node grounding and canonicalize declared "
                "set-like collections with explicit losses"
            ),
        ),
    ),
)


__all__ = [
    "INTENT_IR_SCHEMA_REGISTRY",
    "INTENT_IR_V0_1_TO_V1_MIGRATION_ID",
    "IntentIRDecodeError",
    "IntentIRMigrationResult",
    "MigrationDiagnostic",
    "MigrationSeverity",
    "decode_intent_ir",
    "decode_intent_ir_with_migration",
    "migrate_intent_ir",
]
