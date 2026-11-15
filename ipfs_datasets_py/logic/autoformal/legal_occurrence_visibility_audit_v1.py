"""Audit selected-occurrence visibility without creating a governing edge.

Every selected occurrence stays on the occurrence list. The unsupported
outcome and the missing unresolved outcome stay named. A retrieved locator
stays on the lookup record and is not written as a governing-definition
edge. The producer packet is checked as already written before a separate
post-freeze evaluation packet, with no evaluation reference on the producer.
This module calls no decoder, scores no federal corpus, and records an
authored fixture only.
"""

from __future__ import annotations

SCHEMA = "legal-occurrence-visibility-audit/v1"
OCCURRENCE_VISIBILITY_BOUNDARY = """Every selected occurrence stays visible.
Unsupported and missing outcomes stay visible.
Retrieved locator evidence is not automatically a governing-definition edge.
The producer packet is written before the evaluation packet.
The producer packet receives no evaluation reference.
"""


class OccurrenceVisibilityAuditError(ValueError):
    """An occurrence was hidden, a locator became an edge, or a packet merged."""


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise OccurrenceVisibilityAuditError(message)


def _selected_ids(value: object) -> tuple[str, ...]:
    _need(type(value) is list and 1 <= len(value) <= 32, "selected occurrences stay explicit")
    identifiers: list[str] = []
    for item in value:
        _need(type(item) is str and item.strip() == item and bool(item), "selected occurrences stay explicit")
        identifiers.append(item)
    _need(len(set(identifiers)) == len(identifiers), "selected occurrences stay explicit")
    return tuple(identifiers)


def _occurrences(value: object) -> tuple[dict[str, str], ...]:
    _need(type(value) is list and 1 <= len(value) <= 32, "occurrence outcomes stay explicit")
    rows: list[dict[str, str]] = []
    for item in value:
        _need(
            type(item) is dict and set(item) == {"id", "status"},
            "occurrence outcomes stay explicit",
        )
        identifier = item["id"]
        status = item["status"]
        _need(
            type(identifier) is str and identifier.strip() == identifier and bool(identifier),
            "occurrence outcomes stay explicit",
        )
        _need(type(status) is str and status.strip() == status and bool(status), "occurrence outcomes stay explicit")
        _need(status != "accepted", "accepted is not an occurrence outcome")
        rows.append({"id": identifier, "status": status})
    return tuple(rows)


def _edges(value: object, locator_cid: str) -> tuple[dict[str, str], ...]:
    _need(type(value) is list, "dependency edges stay explicit")
    rows: list[dict[str, str]] = []
    for item in value:
        _need(
            type(item) is dict and set(item) == {"dependent_id", "dependency_id"},
            "dependency edges stay explicit",
        )
        dependent = item["dependent_id"]
        dependency = item["dependency_id"]
        _need(
            type(dependent) is str and type(dependency) is str and bool(dependent) and bool(dependency),
            "dependency edges stay explicit",
        )
        blob = dependent + "\n" + dependency
        _need("governing-definition" not in blob, "retrieved locator is a governing-definition edge")
        _need(locator_cid not in blob, "retrieved locator is a governing-definition edge")
        rows.append({"dependent_id": dependent, "dependency_id": dependency})
    return tuple(rows)


def audit_occurrence_visibility(
    selected_ids: list[str],
    occurrences: list[dict[str, str]],
    edges: list[dict[str, str]],
    *,
    locator_cid: str,
    locator_on_lookup: str,
    pin_kinds: list[str],
    governing_scope_verified: bool,
    semantic_definition_binding_verified: bool,
    producer_written_before_evaluation: bool,
    separate_packet_owners: bool,
    producer_evaluation_reference_access: bool,
    evaluation_metric_reference_access: bool,
) -> dict[str, object]:
    """Record visible outcomes, a retained locator, and separated packets.

    A hidden selected id, a hidden unsupported or missing outcome, a
    governing-definition edge, a locator promoted into an edge, or an
    evaluation reference on the producer is refused.
    """

    identifiers = _selected_ids(selected_ids)
    visible = _occurrences(occurrences)
    _need(
        type(locator_cid) is str and locator_cid.strip() == locator_cid and bool(locator_cid),
        "retrieved locator stays on the lookup record",
    )
    _need(locator_on_lookup == locator_cid, "retrieved locator stays on the lookup record")
    checked_edges = _edges(edges, locator_cid)
    _need(type(pin_kinds) is list and pin_kinds, "dependency pin kinds stay explicit")
    _need(
        all(type(kind) is str and bool(kind) for kind in pin_kinds),
        "dependency pin kinds stay explicit",
    )
    _need("governing-definition" not in pin_kinds, "retrieved locator is a governing-definition edge")
    counts: dict[str, int] = {}
    for row in visible:
        counts[row["id"]] = counts.get(row["id"], 0) + 1
    _need(all(counts.get(identifier) == 1 for identifier in identifiers), "selected occurrence is not visible")
    statuses = [row["status"] for row in visible if row["id"] in identifiers]
    _need("unsupported" in statuses, "unsupported outcome is not visible")
    _need("missing" in statuses, "missing outcome is not visible")
    _need(governing_scope_verified is False, "governing scope stays unverified")
    _need(
        semantic_definition_binding_verified is False,
        "governing scope stays unverified",
    )
    _need(producer_written_before_evaluation is True, "producer packet is not written first")
    _need(separate_packet_owners is True, "producer and evaluation packets share an owner")
    _need(
        producer_evaluation_reference_access is False,
        "producer packet grants evaluation reference access",
    )
    _need(
        evaluation_metric_reference_access is True,
        "evaluation metric reference access was not the recorded flag",
    )
    return {
        "schema": SCHEMA,
        "authored_fixture_only": True,
        "selected_occurrence_count": len(identifiers),
        "selected_occurrences_visible": True,
        "unsupported_outcome_visible": True,
        "missing_outcome_visible": True,
        "unresolved_outcome_status": "missing",
        "locator_retained_on_lookup": True,
        "locator_promoted_to_edge": False,
        "governing_definition_edge_count": 0,
        "governing_scope_verified": False,
        "semantic_definition_binding_verified": False,
        "producer_written_before_evaluation": True,
        "separate_packet_owners": True,
        "producer_evaluation_reference_access": False,
        "evaluation_metric_reference_access": True,
        "decoder_executed": False,
        "model_executed": False,
        "training_executed": False,
        "worker_launched": False,
        "federal_corpus_scored": False,
        "legal_meaning_established": False,
        "legal_acceptance_claimed": False,
        "admitted": False,
        "formalized": False,
    }
