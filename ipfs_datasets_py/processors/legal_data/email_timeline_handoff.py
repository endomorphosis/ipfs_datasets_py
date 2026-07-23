from __future__ import annotations

import json
from datetime import UTC
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Sequence


def _parse_email_datetime(value: Any):
    raw = str(value or "").strip()
    if not raw:
        return "", "", None
    try:
        if "T" in raw:
            parsed = __import__("datetime").datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        parsed = parsed.astimezone(UTC)
        return parsed.isoformat(), parsed.date().isoformat(), parsed
    except Exception:
        pass
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        parsed = parsed.astimezone(UTC)
        return parsed.isoformat(), parsed.date().isoformat(), parsed
    except Exception:
        return raw, "", None


def _topic_label(item: dict[str, Any]) -> str:
    merged = f"{str(item.get('thread_subject') or '')} {str(item.get('subject') or '')}".lower()
    if "hcv orientation" in merged:
        return "hcv_orientation"
    if "annual certification" in merged:
        return "annual_certification"
    if "additional information needed" in merged:
        return "additional_information"
    if "allegations of fraud" in merged or "jc household" in merged:
        return "fraud_household"
    if "jane kay cortez" in merged:
        return "cortez_case"
    return "email_sequence"


def _normalize_candidates(candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in candidates:
        iso_value, day_value, parsed = _parse_email_datetime(item.get("email_date_iso") or item.get("email_date"))
        normalized.append(
            {
                **dict(item),
                "email_date_iso": iso_value,
                "email_date_day": day_value,
                "_parsed_dt": parsed,
                "_topic": _topic_label(dict(item)),
            }
        )
    normalized.sort(key=lambda item: ((item.get("_parsed_dt").timestamp() if item.get("_parsed_dt") else 0.0), str(item.get("subject") or "")))
    return normalized


def build_email_timeline_handoff(
    timeline_candidates: Sequence[dict[str, Any]],
    *,
    claim_type: str = "retaliation",
    claim_element_id: str = "causation",
    temporal_proof_objective: str = "establish_clackamas_email_sequence",
) -> dict[str, Any]:
    items = _normalize_candidates([dict(item) for item in timeline_candidates if isinstance(item, dict)])
    canonical_facts: list[dict[str, Any]] = []
    timeline_anchors: list[dict[str, Any]] = []
    temporal_fact_registry: list[dict[str, Any]] = []
    timeline_relations: list[dict[str, Any]] = []
    temporal_relation_registry: list[dict[str, Any]] = []
    event_ledger: list[dict[str, Any]] = []

    topic_counts: dict[str, int] = {}
    for index, item in enumerate(items, start=1):
        fact_id = f"email_fact_{index:03d}"
        anchor_id = f"timeline_anchor_{index:03d}"
        event_label = str(item.get("thread_subject") or item.get("subject") or "Email event").strip()
        event_text = str(item.get("summary") or item.get("subject") or event_label).strip()
        day_value = str(item.get("email_date_day") or "").strip()
        iso_value = str(item.get("email_date_iso") or "").strip()
        topic = str(item.get("_topic") or "email_sequence")
        topic_counts[topic] = topic_counts.get(topic, 0) + 1

        temporal_context = {
            "raw_text": str(item.get("email_date") or item.get("email_date_iso") or ""),
            "start_date": day_value,
            "end_date": day_value,
            "granularity": "day" if day_value else "unknown",
            "is_approximate": False,
            "is_range": False,
            "relative_markers": [],
            "sortable_date": day_value,
            "matched_text": str(item.get("email_date") or item.get("email_date_iso") or ""),
        }
        canonical_facts.append(
            {
                "fact_id": fact_id,
                "text": event_text,
                "fact_type": "timeline",
                "event_label": event_label,
                "event_date_or_range": day_value or iso_value,
                "predicate_family": topic,
                "source_kind": "email_timeline_candidate",
                "source_ref": str(item.get("eml_path") or ""),
                "participants": list(item.get("participants") or []),
                "sender": str(item.get("sender") or ""),
                "recipient": str(item.get("recipient") or ""),
                "temporal_context": temporal_context,
            }
        )
        timeline_anchors.append(
            {
                "anchor_id": anchor_id,
                "fact_id": fact_id,
                "anchor_text": str(item.get("email_date") or item.get("email_date_iso") or ""),
                "start_date": day_value,
                "end_date": day_value,
                "granularity": "day" if day_value else "unknown",
                "is_approximate": False,
                "sort_key": day_value,
            }
        )
        temporal_fact = {
            "fact_id": fact_id,
            "temporal_fact_id": fact_id,
            "registry_version": "temporal_fact_registry.v1",
            "claim_types": [claim_type],
            "element_tags": [claim_element_id, topic],
            "actor_ids": [],
            "target_ids": [],
            "event_label": event_label,
            "predicate_family": topic,
            "start_time": day_value,
            "end_time": day_value,
            "granularity": "day" if day_value else "unknown",
            "is_approximate": False,
            "is_range": False,
            "relative_markers": [],
            "timeline_anchor_ids": [anchor_id],
            "temporal_context": temporal_context,
            "temporal_status": "anchored" if day_value else "unanchored",
            "source_artifact_ids": [],
            "testimony_record_ids": [],
            "source_span_refs": [],
            "confidence": 1.0 if day_value else 0.7,
            "validation_status": "accepted",
            "source_kind": "email_timeline_candidate",
            "source_ref": str(item.get("eml_path") or ""),
            "event_support_refs": [f"email:{fact_id}"],
        }
        temporal_fact_registry.append(temporal_fact)
        event_ledger.append({**temporal_fact, "event_id": fact_id, "ledger_version": "event_ledger.v1"})

    for index, (left, right) in enumerate(zip(canonical_facts, canonical_facts[1:]), start=1):
        relation_id = f"timeline_relation_{index:03d}"
        relation = {
            "relation_id": relation_id,
            "source_fact_id": left["fact_id"],
            "target_fact_id": right["fact_id"],
            "relation_type": "before",
            "source_start_date": left["temporal_context"].get("start_date"),
            "source_end_date": left["temporal_context"].get("end_date"),
            "target_start_date": right["temporal_context"].get("start_date"),
            "target_end_date": right["temporal_context"].get("end_date"),
            "confidence": "high",
        }
        timeline_relations.append(relation)
        temporal_relation_registry.append(
            {
                **relation,
                "temporal_relation_id": relation_id,
                "registry_version": "temporal_relation_registry.v1",
                "source_temporal_fact_id": left["fact_id"],
                "target_temporal_fact_id": right["fact_id"],
                "claim_types": [claim_type],
                "element_tags": [claim_element_id],
            }
        )

    topic_summary = {
        topic: {
            "count": count,
            "first_fact_id": next((fact["fact_id"] for fact in canonical_facts if fact.get("predicate_family") == topic), ""),
            "last_fact_id": next((fact["fact_id"] for fact in reversed(canonical_facts) if fact.get("predicate_family") == topic), ""),
        }
        for topic, count in topic_counts.items()
    }
    handoff = {
        "contract_version": "claim_support_temporal_handoff_v1",
        "chronology_blocked": False,
        "chronology_task_count": 0,
        "unresolved_temporal_issue_count": 0,
        "unresolved_temporal_issue_ids": [],
        "event_ids": [fact["fact_id"] for fact in canonical_facts],
        "temporal_fact_ids": [fact["fact_id"] for fact in canonical_facts],
        "temporal_relation_ids": [relation["relation_id"] for relation in timeline_relations],
        "timeline_anchor_ids": [anchor["anchor_id"] for anchor in timeline_anchors],
        "timeline_issue_ids": [],
        "temporal_issue_ids": [],
        "temporal_proof_bundle_ids": [f"email-timeline:{claim_type}:{claim_element_id}:bundle_001"],
        "temporal_proof_objectives": [temporal_proof_objective],
        "timeline_anchor_count": len(timeline_anchors),
        "event_count": len(canonical_facts),
        "topic_summary": topic_summary,
    }

    return {
        "status": "success",
        "claim_type": claim_type,
        "claim_element_id": claim_element_id,
        "source_event_count": len(items),
        "canonical_facts": canonical_facts,
        "timeline_anchors": timeline_anchors,
        "temporal_fact_registry": temporal_fact_registry,
        "event_ledger": event_ledger,
        "timeline_relations": timeline_relations,
        "temporal_relation_registry": temporal_relation_registry,
        "temporal_issue_registry": [],
        "timeline_consistency_summary": {
            "event_count": len(canonical_facts),
            "anchor_count": len(timeline_anchors),
            "ordered_fact_count": len(canonical_facts),
            "unsequenced_fact_count": 0,
            "approximate_fact_count": 0,
            "range_fact_count": 0,
            "relation_count": len(timeline_relations),
            "relation_type_counts": {"before": len(timeline_relations)} if timeline_relations else {},
            "missing_temporal_fact_ids": [],
            "relative_only_fact_ids": [],
            "warnings": [],
            "partial_order_ready": bool(canonical_facts),
            "day_precision_fact_count": len(canonical_facts),
            "non_day_precision_fact_ids": [],
            "temporal_conflict_relation_count": 0,
            "orphan_anchor_count": 0,
        },
        "claim_support_temporal_handoff": handoff,
    }


def build_email_timeline_handoff_from_file(
    timeline_path: str | Path,
    *,
    output_path: str | Path | None = None,
    claim_type: str = "retaliation",
    claim_element_id: str = "causation",
    temporal_proof_objective: str = "establish_clackamas_email_sequence",
) -> dict[str, Any]:
    source_path = Path(timeline_path).expanduser().resolve()
    items = json.loads(source_path.read_text(encoding="utf-8"))
    payload = build_email_timeline_handoff(
        items,
        claim_type=claim_type,
        claim_element_id=claim_element_id,
        temporal_proof_objective=temporal_proof_objective,
    )
    payload["source_timeline_path"] = str(source_path)
    if output_path is not None:
        destination = Path(output_path).expanduser().resolve()
    else:
        destination = source_path.parent / "email_timeline_handoff.json"
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    payload["output_path"] = str(destination)
    return payload


__all__ = [
    "build_email_timeline_handoff",
    "build_email_timeline_handoff_from_file",
]
