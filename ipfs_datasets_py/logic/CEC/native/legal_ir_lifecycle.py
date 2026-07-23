"""Deterministic Legal IR lifecycle-event compilation for native CEC."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


LEGAL_IR_LIFECYCLE_SCHEMA_VERSION = "legal-ir-cec-lifecycle-v1"

_LIFECYCLE_RE = re.compile(
    r"\b(?P<event>files?|filed|filing|issues?|issued|issuance|grants?|granted|"
    r"denies|denied|denial|revokes?|revoked|revocation|terminates?|terminated|"
    r"termination|expires?|expired|expiration|appeals?|appealed|review(?:s|ed)?|"
    r"enforces?|enforced|enforcement)\b",
    re.IGNORECASE,
)
_EVENT_CANONICAL = {
    "appeal": "appeal",
    "deni": "deny",
    "enforc": "enforce",
    "expir": "expire",
    "fil": "file",
    "grant": "grant",
    "issu": "issue",
    "revoc": "revoke",
    "revok": "revoke",
    "review": "review",
    "terminat": "terminate",
}
_EVENT_EFFECT = {
    "appeal": ("Initiates", "appealed"),
    "deny": ("Terminates", "pending"),
    "enforce": ("Initiates", "enforcement_active"),
    "expire": ("Terminates", "active"),
    "file": ("Initiates", "filed"),
    "grant": ("Initiates", "active"),
    "issue": ("Initiates", "active"),
    "revoke": ("Terminates", "active"),
    "review": ("Initiates", "under_review"),
    "terminate": ("Terminates", "active"),
}


def compile_lifecycle_events(
    text: str,
    *,
    provenance_id: str = "",
) -> dict[str, Any]:
    """Compile lexical lifecycle cues into typed CEC events and transitions.

    Events retain source order and are deduplicated by canonical event kind.
    Every event has a ``Happens`` occurrence and an ``Initiates`` or
    ``Terminates`` event-to-fluent transition.  Only semantic symbols and
    provenance IDs are emitted; source text and offsets are deliberately absent.
    """

    provenance_ids = [str(provenance_id).strip()] if str(provenance_id).strip() else []
    event_kinds: list[str] = []
    for match in _LIFECYCLE_RE.finditer(str(text or "")):
        kind = _canonical_event(match.group("event"))
        if kind and kind not in event_kinds:
            event_kinds.append(kind)

    identity = {"events": event_kinds, "provenance_ids": provenance_ids}
    formula_id = f"cec-lifecycle:{_digest(identity)[:24]}"
    events: list[dict[str, Any]] = []
    fluents_by_id: dict[str, dict[str, Any]] = {}
    transitions: list[dict[str, Any]] = []
    for order, kind in enumerate(event_kinds, start=1):
        relation, fluent_name = _EVENT_EFFECT[kind]
        event_id = f"cec-event:{_digest({'formula_id': formula_id, 'kind': kind})[:24]}"
        fluent_id = f"cec-fluent:{_digest({'formula_id': formula_id, 'name': fluent_name})[:24]}"
        time_anchor = f"t{order}"
        events.append(
            {
                "event_id": event_id,
                "formula": f"Happens({kind},{time_anchor})",
                "happens": f"Happens({kind},{time_anchor})",
                "name": kind,
                "order": order,
                "predicate": "Happens",
                "time_anchor": time_anchor,
                "type": "lifecycle_event",
            }
        )
        fluents_by_id.setdefault(
            fluent_id,
            {
                "fluent_id": fluent_id,
                "name": fluent_name,
                "type": "lifecycle_state",
            },
        )
        transition_identity = {
            "event_id": event_id,
            "fluent_id": fluent_id,
            "relation": relation,
            "time_anchor": time_anchor,
        }
        transitions.append(
            {
                "event_id": event_id,
                "fluent_id": fluent_id,
                "formula": f"{relation}({kind},{fluent_name},{time_anchor})",
                "relation": relation,
                "time_anchor": time_anchor,
                "transition_id": f"cec-transition:{_digest(transition_identity)[:24]}",
            }
        )

    return {
        "events": events,
        "fluents": list(fluents_by_id.values()),
        "formula_id": formula_id,
        "lifecycle_transitions": transitions,
        "provenance_ids": provenance_ids,
        "schema_version": LEGAL_IR_LIFECYCLE_SCHEMA_VERSION,
    }


def _canonical_event(value: Any) -> str:
    token = str(value or "").strip().lower()
    for stem, canonical in _EVENT_CANONICAL.items():
        if token.startswith(stem):
            return canonical
    return ""


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


__all__ = ["LEGAL_IR_LIFECYCLE_SCHEMA_VERSION", "compile_lifecycle_events"]
