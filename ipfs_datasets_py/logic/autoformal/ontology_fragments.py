"""Proposed ontology fragments. A proposed fragment is invisible to the compiler."""
from __future__ import annotations

from typing import Any


_ATTACHMENTS = frozenset({
    "conditions",
    "exceptions",
    "temporal",
    "object",
    "cross_references",
    "defined_terms",
    "overrides",
    "penalty",
    "procedure",
    "definition_scope",
    "mental_state",
    "recipient",
    "span",
})


class FragmentRegistry:
    """Types and relations that may later attach to CanonicalRule. Not a compiler."""

    def __init__(self) -> None:
        self.fragments: dict[str, dict[str, Any]] = {}

    def propose(self, fragment: dict[str, Any]) -> dict[str, Any]:
        relation = str(fragment.get("relation") or "").strip()
        attachment = str(fragment.get("attachment") or "").strip()
        domain = str(fragment.get("domain") or "").strip()
        range_type = str(fragment.get("range") or "").strip()
        if not relation or not domain or not range_type or attachment not in _ATTACHMENTS:
            return {"status": "rejected", "reason": "unattached", "admitted": False}
        stored = {
            "relation": relation,
            "domain": domain,
            "range": range_type,
            "cardinality": str(fragment.get("cardinality") or "many"),
            "inverse": str(fragment.get("inverse") or ""),
            "attachment": attachment,
            "decompiler_phrase": str(fragment.get("decompiler_phrase") or ""),
            "fixture_id": str(fragment.get("fixture_id") or ""),
            "status": "proposed",
            "admitted": False,
        }
        self.fragments[relation] = stored
        return dict(stored)

    def admit(self, relation: str) -> dict[str, Any]:
        fragment = self.fragments.get(relation)
        if fragment is None:
            return {"status": "rejected", "reason": "missing", "admitted": False}
        if not fragment["decompiler_phrase"] or not fragment["fixture_id"]:
            return {"status": "proposed", "reason": "fixture_required", "admitted": False}
        fragment["status"] = "admitted"
        fragment["admitted"] = True
        return dict(fragment)

    def visible_to_compiler(self) -> list[dict[str, Any]]:
        """Proposed fragments are not returned. Admitted fragments are data, not a compile hook."""

        return [dict(item) for item in self.fragments.values() if item["status"] == "admitted"]

    def by_attachment(self) -> dict[str, list[dict[str, Any]]]:
        """Admitted fragments keyed by the CanonicalRule field they attach to."""

        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in self.visible_to_compiler():
            grouped.setdefault(str(item["attachment"]), []).append(item)
        return grouped
