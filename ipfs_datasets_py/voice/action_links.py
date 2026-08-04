"""Abby content-plane route → logical-action link schema (v1).

Content artifacts may map a slotted-DAG *route* to a catalog *logical action*
and optional confirmation / outcome frame IDs.  They must never embed
executables, shell argv, import paths, network locators, environment secrets,
or other authority-plane bindings.

This module is dependency-light and deterministic: digests ignore key order,
link identity is content-addressed, and parse/validate fail closed on forbidden
fields.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Final

# Public schema identity (machine + documentation).
ACTION_LINK_SCHEMA: Final = "voice-action/action-link@1"
ACTION_LINK_SCHEMA_VERSION: Final = "abby_content_action_link_v1"
ACTION_LINK_DOC_PATH: Final = "docs/voice_action_dag/schemas/action-link-v1.md"

# Explicit content-only sentinel (fail-closed default for unmapped routes).
NO_ACTION: Final = "no_action"

ROUTE_CLASSIFICATIONS: Final = frozenset(
    {
        "content-only",
        "proposal-eligible",
        "safety-overlay",
    }
)

# Spoken outcome frame roles linked from a content action link.
OUTCOME_FRAME_KEYS: Final = frozenset(
    {
        "success",
        "denied",
        "failed",
        "cancelled",
        "unknown",
    }
)

# Align with INV-CONTENT-001 / action_runtime.contracts banned proposal keys.
FORBIDDEN_CONTENT_FIELDS: Final = frozenset(
    {
        "command",
        "argv",
        "executable",
        "shell",
        "cwd",
        "env",
        "import",
        "import_path",
        "url",
        "credentials",
        "secret",
        "webhook",
    }
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_ROUTE_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_LOGICAL_ACTION_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_PATH_SUFFIX = "_path"


class ActionLinkSchemaError(ValueError):
    """Raised when an action-link record violates the content-plane contract."""

    def __init__(self, errors: str | Iterable[str]):
        if isinstance(errors, str):
            self.errors: tuple[str, ...] = (errors,)
        else:
            self.errors = tuple(str(item) for item in errors)
        detail = "; ".join(self.errors) or "invalid action link"
        super().__init__(f"{ACTION_LINK_SCHEMA}: {detail}")


def canonical_json(value: Any) -> str:
    """Serialize a JSON-safe value with stable key order for digests."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def content_digest(value: Any) -> str:
    """Return the full lower-case SHA-256 of :func:`canonical_json` bytes."""

    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _text(value: Any, *, field_name: str, required: bool = True) -> str:
    if value is None:
        if required:
            raise ActionLinkSchemaError(f"{field_name} must not be empty")
        return ""
    if not isinstance(value, str):
        raise ActionLinkSchemaError(f"{field_name} must be a string")
    result = value.strip()
    if required and not result:
        raise ActionLinkSchemaError(f"{field_name} must not be empty")
    return result


def _optional_id(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    text = _text(value, field_name=field_name, required=False)
    if not text:
        return None
    if not _ID_RE.fullmatch(text):
        raise ActionLinkSchemaError(
            f"{field_name} must match the safe content id pattern"
        )
    return text


def _reject_forbidden_key(key: str, *, path: str) -> None:
    lowered = key.casefold()
    if lowered in FORBIDDEN_CONTENT_FIELDS:
        raise ActionLinkSchemaError(
            f"forbidden content field {key!r} at {path}"
        )
    if lowered.endswith(_PATH_SUFFIX):
        raise ActionLinkSchemaError(
            f"forbidden executable path field {key!r} at {path}"
        )


def reject_forbidden_content_fields(
    value: Any, *, path: str = "$"
) -> None:
    """Fail closed if *value* contains any forbidden content-executable field.

    Walks mappings and sequences.  Field names are compared case-insensitively
    against :data:`FORBIDDEN_CONTENT_FIELDS`.  Keys ending in ``_path`` are also
    rejected (executable / filesystem locator smuggling).
    """

    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            child = f"{path}.{name}" if path != "$" else f"$.{name}"
            _reject_forbidden_key(name, path=child)
            reject_forbidden_content_fields(item, path=child)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            reject_forbidden_content_fields(item, path=f"{path}[{index}]")
        return


def _json_safe(value: Any, *, path: str = "$") -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        if isinstance(value, float) and (
            value != value or value in (float("inf"), float("-inf"))
        ):
            raise ActionLinkSchemaError(f"{path} must be finite JSON")
        return value
    if isinstance(value, bytes | bytearray | memoryview):
        raise ActionLinkSchemaError(f"{path} must not contain raw bytes")
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            child = f"{path}.{name}" if path != "$" else f"$.{name}"
            _reject_forbidden_key(name, path=child)
            result[name] = _json_safe(item, path=child)
        return result
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [
            _json_safe(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_safe(to_dict(), path=path)
    raise ActionLinkSchemaError(f"{path} must contain deterministic JSON values")


def _freeze_mapping(value: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(value))


def _normalize_outcome_frame_ids(
    value: Any, *, field_name: str = "outcome_frame_ids"
) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise ActionLinkSchemaError(f"{field_name} must be a mapping")
    result: dict[str, str] = {}
    for raw_key, raw_id in value.items():
        key = _text(raw_key, field_name=f"{field_name}.key")
        if key not in OUTCOME_FRAME_KEYS:
            raise ActionLinkSchemaError(
                f"{field_name} key {key!r} is not a known outcome role "
                f"(allowed: {', '.join(sorted(OUTCOME_FRAME_KEYS))})"
            )
        frame_id = _optional_id(raw_id, field_name=f"{field_name}.{key}")
        if frame_id is None:
            raise ActionLinkSchemaError(
                f"{field_name}.{key} must be a non-empty frame id"
            )
        result[key] = frame_id
    # Stable insertion order for identity: sort by outcome role.
    return MappingProxyType({key: result[key] for key in sorted(result)})


def _normalize_logical_action(
    value: Any,
    *,
    classification: str,
    field_name: str = "logical_action",
) -> str:
    text = _text(value, field_name=field_name)
    if not _LOGICAL_ACTION_RE.fullmatch(text):
        raise ActionLinkSchemaError(
            f"{field_name} must be a lower_snake catalog id or {NO_ACTION!r}"
        )
    if classification == "content-only":
        if text != NO_ACTION:
            raise ActionLinkSchemaError(
                f"content-only links must set {field_name}={NO_ACTION!r}"
            )
    elif text == NO_ACTION:
        raise ActionLinkSchemaError(
            f"{classification} links must set a real catalog {field_name}, "
            f"not {NO_ACTION!r}"
        )
    return text


def _normalize_route(value: Any) -> str:
    route = _text(value, field_name="route")
    if not _ROUTE_RE.fullmatch(route):
        raise ActionLinkSchemaError(
            "route must be a lower_snake slotted-DAG route id"
        )
    return route


def _normalize_classification(value: Any) -> str:
    classification = _text(value, field_name="classification")
    if classification not in ROUTE_CLASSIFICATIONS:
        raise ActionLinkSchemaError(
            "classification must be one of: "
            + ", ".join(sorted(ROUTE_CLASSIFICATIONS))
        )
    return classification


def stable_action_link_id(
    *,
    route: str,
    logical_action: str,
    confirmation_frame_id: str | None = None,
    outcome_frame_ids: Mapping[str, str] | None = None,
) -> str:
    """Build a deterministic link id from semantic content fields only."""

    payload = {
        "confirmation_frame_id": confirmation_frame_id,
        "logical_action": logical_action,
        "outcome_frame_ids": dict(outcome_frame_ids or {}),
        "route": route,
        "schema": ACTION_LINK_SCHEMA,
    }
    return f"action-link-{content_digest(payload)[:24]}"


@dataclass(frozen=True, slots=True)
class ActionLink:
    """One content-plane route → logical-action link (no executables)."""

    route: str
    logical_action: str
    classification: str
    confirmation_frame_id: str | None = None
    outcome_frame_ids: Mapping[str, str] = field(default_factory=dict)
    evidence_cids: tuple[str, ...] = ()
    notes: str | None = None
    link_id: str = ""
    schema: str = ACTION_LINK_SCHEMA
    schema_version: str = ACTION_LINK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        route = _normalize_route(self.route)
        classification = _normalize_classification(self.classification)
        logical_action = _normalize_logical_action(
            self.logical_action, classification=classification
        )
        confirmation = _optional_id(
            self.confirmation_frame_id, field_name="confirmation_frame_id"
        )
        outcomes = _normalize_outcome_frame_ids(self.outcome_frame_ids)
        if classification == "content-only":
            if confirmation is not None:
                raise ActionLinkSchemaError(
                    "content-only links must not set confirmation_frame_id"
                )
            if outcomes:
                raise ActionLinkSchemaError(
                    "content-only links must not set outcome_frame_ids"
                )
        evidence: list[str] = []
        seen: set[str] = set()
        for index, raw in enumerate(self.evidence_cids or ()):
            cid = _text(raw, field_name=f"evidence_cids[{index}]")
            if cid not in seen:
                evidence.append(cid)
                seen.add(cid)
        notes = None
        if self.notes is not None:
            notes_text = _text(self.notes, field_name="notes", required=False)
            notes = notes_text or None
        schema = _text(self.schema, field_name="schema")
        if schema != ACTION_LINK_SCHEMA:
            raise ActionLinkSchemaError(
                f"unsupported action-link schema: {schema!r}"
            )
        schema_version = _text(self.schema_version, field_name="schema_version")
        if schema_version != ACTION_LINK_SCHEMA_VERSION:
            raise ActionLinkSchemaError(
                f"unsupported action-link schema_version: {schema_version!r}"
            )

        computed = stable_action_link_id(
            route=route,
            logical_action=logical_action,
            confirmation_frame_id=confirmation,
            outcome_frame_ids=outcomes,
        )
        link_id = _text(self.link_id, field_name="link_id", required=False) or computed
        if link_id != computed:
            raise ActionLinkSchemaError(
                "link_id does not match deterministic action-link content"
            )

        # Re-scan the public dict for forbidden keys (defense in depth).
        reject_forbidden_content_fields(
            {
                "route": route,
                "logical_action": logical_action,
                "classification": classification,
                "confirmation_frame_id": confirmation,
                "outcome_frame_ids": dict(outcomes),
                "evidence_cids": evidence,
                "notes": notes,
            }
        )

        object.__setattr__(self, "route", route)
        object.__setattr__(self, "logical_action", logical_action)
        object.__setattr__(self, "classification", classification)
        object.__setattr__(self, "confirmation_frame_id", confirmation)
        object.__setattr__(self, "outcome_frame_ids", outcomes)
        object.__setattr__(self, "evidence_cids", tuple(evidence))
        object.__setattr__(self, "notes", notes)
        object.__setattr__(self, "link_id", link_id)
        object.__setattr__(self, "schema", schema)
        object.__setattr__(self, "schema_version", schema_version)

    @property
    def is_no_action(self) -> bool:
        return self.logical_action == NO_ACTION

    @property
    def may_propose(self) -> bool:
        return (
            self.classification in {"proposal-eligible", "safety-overlay"}
            and not self.is_no_action
        )

    def identity_dict(self) -> dict[str, Any]:
        """Semantic fields that participate in the content digest."""

        return {
            "classification": self.classification,
            "confirmation_frame_id": self.confirmation_frame_id,
            "evidence_cids": list(self.evidence_cids),
            "link_id": self.link_id,
            "logical_action": self.logical_action,
            "notes": self.notes,
            "outcome_frame_ids": dict(self.outcome_frame_ids),
            "route": self.route,
            "schema": self.schema,
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable, key-stable representation."""

        return dict(self.identity_dict())

    def content_digest(self) -> str:
        return content_digest(self.identity_dict())


@dataclass(frozen=True, slots=True)
class ActionLinkDocument:
    """Versioned collection of action links for a content revision."""

    links: tuple[ActionLink, ...]
    schema: str = ACTION_LINK_SCHEMA
    schema_version: str = ACTION_LINK_SCHEMA_VERSION
    document_id: str = ""
    source: str | None = None

    def __post_init__(self) -> None:
        schema = _text(self.schema, field_name="schema")
        if schema != ACTION_LINK_SCHEMA:
            raise ActionLinkSchemaError(
                f"unsupported action-link document schema: {schema!r}"
            )
        schema_version = _text(self.schema_version, field_name="schema_version")
        if schema_version != ACTION_LINK_SCHEMA_VERSION:
            raise ActionLinkSchemaError(
                f"unsupported action-link document schema_version: "
                f"{schema_version!r}"
            )
        if not isinstance(self.links, Sequence) or isinstance(
            self.links, (str, bytes, bytearray)
        ):
            raise ActionLinkSchemaError("links must be a sequence of ActionLink")
        normalized: list[ActionLink] = []
        routes: set[str] = set()
        for index, item in enumerate(self.links):
            if isinstance(item, ActionLink):
                link = item
            elif isinstance(item, Mapping):
                link = parse_action_link(item)
            else:
                raise ActionLinkSchemaError(
                    f"links[{index}] must be an ActionLink or mapping"
                )
            if link.route in routes:
                raise ActionLinkSchemaError(
                    f"duplicate action link for route {link.route!r}"
                )
            routes.add(link.route)
            normalized.append(link)
        # Deterministic order: sort by route name.
        normalized.sort(key=lambda link: link.route)
        source = None
        if self.source is not None:
            source_text = _text(self.source, field_name="source", required=False)
            source = source_text or None

        identity = {
            "links": [link.identity_dict() for link in normalized],
            "schema": schema,
            "schema_version": schema_version,
            "source": source,
        }
        reject_forbidden_content_fields(identity)
        computed = f"action-link-doc-{content_digest(identity)[:24]}"
        document_id = (
            _text(self.document_id, field_name="document_id", required=False)
            or computed
        )
        if document_id != computed:
            raise ActionLinkSchemaError(
                "document_id does not match deterministic action-link document"
            )

        object.__setattr__(self, "schema", schema)
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "links", tuple(normalized))
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "document_id", document_id)

    def by_route(self) -> Mapping[str, ActionLink]:
        return MappingProxyType({link.route: link for link in self.links})

    def logical_action_for(self, route: str) -> str:
        """Return the mapped logical action, or :data:`NO_ACTION` if missing."""

        link = self.by_route().get(route)
        if link is None:
            return NO_ACTION
        return link.logical_action

    def identity_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "links": [link.identity_dict() for link in self.links],
            "schema": self.schema,
            "schema_version": self.schema_version,
            "source": self.source,
        }

    def to_dict(self) -> dict[str, Any]:
        return dict(self.identity_dict())

    def content_digest(self) -> str:
        return content_digest(self.identity_dict())


def parse_action_link(payload: Mapping[str, Any] | ActionLink) -> ActionLink:
    """Parse and validate one action-link mapping (fail closed)."""

    if isinstance(payload, ActionLink):
        return payload
    if not isinstance(payload, Mapping):
        raise ActionLinkSchemaError("action link must be a mapping")
    # Reject forbidden keys on the raw payload before field extraction.
    reject_forbidden_content_fields(payload)
    data = _json_safe(dict(payload), path="$")
    if not isinstance(data, Mapping):
        raise ActionLinkSchemaError("action link must be a mapping")

    # Accept logical_action_id as a synonym for logical_action (plan vocabulary).
    if "logical_action" not in data and "logical_action_id" in data:
        data = dict(data)
        data["logical_action"] = data.pop("logical_action_id")

    unknown = sorted(
        set(data)
        - {
            "route",
            "logical_action",
            "classification",
            "confirmation_frame_id",
            "outcome_frame_ids",
            "evidence_cids",
            "notes",
            "link_id",
            "schema",
            "schema_version",
        }
    )
    if unknown:
        raise ActionLinkSchemaError(
            "unknown action-link fields: " + ", ".join(unknown)
        )

    evidence_raw = data.get("evidence_cids") or ()
    if isinstance(evidence_raw, str):
        evidence_raw = (evidence_raw,)
    if not isinstance(evidence_raw, Sequence):
        raise ActionLinkSchemaError("evidence_cids must be a sequence of strings")

    return ActionLink(
        route=data.get("route"),  # type: ignore[arg-type]
        logical_action=data.get("logical_action"),  # type: ignore[arg-type]
        classification=data.get("classification"),  # type: ignore[arg-type]
        confirmation_frame_id=data.get("confirmation_frame_id"),
        outcome_frame_ids=data.get("outcome_frame_ids") or {},
        evidence_cids=tuple(evidence_raw),
        notes=data.get("notes"),
        link_id=str(data.get("link_id") or ""),
        schema=str(data.get("schema") or ACTION_LINK_SCHEMA),
        schema_version=str(data.get("schema_version") or ACTION_LINK_SCHEMA_VERSION),
    )


def parse_action_link_document(
    payload: Mapping[str, Any] | ActionLinkDocument,
) -> ActionLinkDocument:
    """Parse and validate a multi-link action-link document."""

    if isinstance(payload, ActionLinkDocument):
        return payload
    if not isinstance(payload, Mapping):
        raise ActionLinkSchemaError("action-link document must be a mapping")
    reject_forbidden_content_fields(payload)
    data = _json_safe(dict(payload), path="$")
    if not isinstance(data, Mapping):
        raise ActionLinkSchemaError("action-link document must be a mapping")

    unknown = sorted(
        set(data)
        - {
            "schema",
            "schema_version",
            "links",
            "document_id",
            "source",
            "content_digest",
        }
    )
    if unknown:
        raise ActionLinkSchemaError(
            "unknown action-link document fields: " + ", ".join(unknown)
        )

    links_raw = data.get("links")
    if not isinstance(links_raw, Sequence) or isinstance(links_raw, (str, bytes)):
        raise ActionLinkSchemaError("links must be a sequence")

    document = ActionLinkDocument(
        links=tuple(links_raw),  # type: ignore[arg-type]
        schema=str(data.get("schema") or ACTION_LINK_SCHEMA),
        schema_version=str(
            data.get("schema_version") or ACTION_LINK_SCHEMA_VERSION
        ),
        document_id=str(data.get("document_id") or ""),
        source=data.get("source"),
    )
    declared = data.get("content_digest")
    if declared is not None:
        expected = document.content_digest()
        if str(declared).casefold() != expected:
            raise ActionLinkSchemaError(
                "content_digest does not match deterministic document body"
            )
    return document


def validate_action_link(payload: Mapping[str, Any] | ActionLink) -> ActionLink:
    """Validate *payload* and return the normalized :class:`ActionLink`."""

    return parse_action_link(payload)


def validate_action_link_document(
    payload: Mapping[str, Any] | ActionLinkDocument,
) -> ActionLinkDocument:
    """Validate *payload* and return the normalized document."""

    return parse_action_link_document(payload)


# ---------------------------------------------------------------------------
# Golden vectors (deterministic fixtures for offline tests and rebuilds)
# ---------------------------------------------------------------------------


def golden_action_link_vectors() -> tuple[dict[str, Any], ...]:
    """Return fixed, key-sorted golden payloads covering the v1 surface.

    Vectors are pure data (no wall-clock, no random).  Digests are computed by
    the schema so reordering keys in a consumer copy cannot change identity.
    """

    proposal = ActionLink(
        route="app_surface_navigation",
        logical_action="open_app_surface",
        classification="proposal-eligible",
        confirmation_frame_id="frame.action.confirm.open_app_surface.v1",
        outcome_frame_ids={
            "success": "frame.action.outcome.open_app_surface.success.v1",
            "denied": "frame.action.outcome.open_app_surface.denied.v1",
            "failed": "frame.action.outcome.open_app_surface.failed.v1",
            "cancelled": "frame.action.outcome.open_app_surface.cancelled.v1",
            "unknown": "frame.action.outcome.open_app_surface.unknown.v1",
        },
        evidence_cids=("bafybeigdyrzt4exampleabbyactionlinkcid01",),
        notes="Pilot navigation surface proposal link",
    )
    content_only = ActionLink(
        route="clarifying_prompt",
        logical_action=NO_ACTION,
        classification="content-only",
        notes="Slot collection has no side-effect proposal",
    )
    safety = ActionLink(
        route="safety_guardrail_support",
        logical_action="escalate_safety",
        classification="safety-overlay",
        confirmation_frame_id="frame.action.confirm.escalate_safety.v1",
        outcome_frame_ids={
            "success": "frame.action.outcome.escalate_safety.success.v1",
            "failed": "frame.action.outcome.escalate_safety.failed.v1",
            "unknown": "frame.action.outcome.escalate_safety.unknown.v1",
        },
        notes="Safety overlay may propose escalate_safety under policy",
    )
    handoff = ActionLink(
        route="live_agent",
        logical_action="handoff_live_agent",
        classification="proposal-eligible",
        confirmation_frame_id="frame.action.confirm.handoff_live_agent.v1",
        outcome_frame_ids={
            "success": "frame.action.outcome.handoff_live_agent.success.v1",
            "denied": "frame.action.outcome.handoff_live_agent.denied.v1",
            "failed": "frame.action.outcome.handoff_live_agent.failed.v1",
            "unknown": "frame.action.outcome.handoff_live_agent.unknown.v1",
        },
        notes="Never claim transfer success without provider receipt",
    )
    return (
        proposal.to_dict(),
        content_only.to_dict(),
        safety.to_dict(),
        handoff.to_dict(),
    )


def golden_action_link_document() -> ActionLinkDocument:
    """Return the golden multi-link document used by unit tests."""

    return ActionLinkDocument(
        links=tuple(parse_action_link(item) for item in golden_action_link_vectors()),
        source="voice-action-004/golden",
    )


__all__ = [
    "ACTION_LINK_DOC_PATH",
    "ACTION_LINK_SCHEMA",
    "ACTION_LINK_SCHEMA_VERSION",
    "ActionLink",
    "ActionLinkDocument",
    "ActionLinkSchemaError",
    "FORBIDDEN_CONTENT_FIELDS",
    "NO_ACTION",
    "OUTCOME_FRAME_KEYS",
    "ROUTE_CLASSIFICATIONS",
    "canonical_json",
    "content_digest",
    "golden_action_link_document",
    "golden_action_link_vectors",
    "parse_action_link",
    "parse_action_link_document",
    "reject_forbidden_content_fields",
    "stable_action_link_id",
    "validate_action_link",
    "validate_action_link_document",
]
