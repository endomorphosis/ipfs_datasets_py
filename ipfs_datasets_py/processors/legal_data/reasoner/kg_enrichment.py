from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any, Dict, List

try:
    from .hybrid_legal_ir import LegalIR
except ImportError:
    from municipal_scrape_workspace.hybrid_legal_ir import LegalIR  # type: ignore[no-redef]


def _norm_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    return " ".join(text.split())


def _entity_confidence(entity: Any, label: str) -> float:
    score = 0.55
    if label and not label.startswith("ent:"):
        score += 0.20
    if str(getattr(entity, "type_name", "") or "").strip():
        score += 0.15
    if len(label) >= 8:
        score += 0.05
    if " " in label:
        score += 0.05
    return max(0.0, min(0.99, score))


def build_entity_link_adapter(
    ir: LegalIR,
    *,
    kg_namespace: str = "kg",
    confidence_floor: float = 0.0,
) -> Dict[str, Any]:
    """Build deterministic entity-to-KG link candidates with confidence scores."""
    links: List[Dict[str, Any]] = []
    skipped = 0

    for entity_ref in sorted(ir.entities.keys()):
        entity = ir.entities[entity_ref]
        label = _norm_label(entity.attrs.get("label") or entity_ref)
        etype = _norm_label(getattr(entity, "type_name", "Entity") or "Entity")
        digest_src = f"{etype}|{label}"
        digest = hashlib.sha1(digest_src.encode("utf-8")).hexdigest()[:12]
        kg_id = f"{kg_namespace}:entity:{digest}"
        confidence = _entity_confidence(entity, label)

        if confidence < float(confidence_floor):
            skipped += 1
            continue

        links.append(
            {
                "entity_ref": entity_ref,
                "kg_id": kg_id,
                "confidence": confidence,
                "label": label,
                "entity_type": etype,
            }
        )

    return {
        "summary": {
            "candidate_count": len(ir.entities),
            "linked_count": len(links),
            "skipped_count": skipped,
            "confidence_floor": float(confidence_floor),
            "kg_namespace": kg_namespace,
        },
        "entity_links": links,
    }


def build_relation_enrichment_adapter(
    ir: LegalIR,
    entity_link_adapter: Dict[str, Any],
    *,
    confidence_floor: float = 0.0,
) -> Dict[str, Any]:
    """Build frame-role enrichment records using previously linked entities."""
    link_by_entity = {
        row["entity_ref"]: row
        for row in (entity_link_adapter.get("entity_links") or [])
    }

    relations: List[Dict[str, Any]] = []
    skipped = 0
    for frame_ref in sorted(ir.frames.keys()):
        frame = ir.frames[frame_ref]
        role_links: Dict[str, Dict[str, Any]] = {}
        confidences: List[float] = []

        for role, entity_ref in sorted((frame.roles or {}).items(), key=lambda kv: kv[0]):
            link = link_by_entity.get(entity_ref)
            if not link:
                continue
            confidence = float(link.get("confidence") or 0.0)
            if confidence < float(confidence_floor):
                continue
            role_links[role] = {
                "entity_ref": entity_ref,
                "kg_id": link["kg_id"],
                "confidence": confidence,
            }
            confidences.append(confidence)

        if not role_links:
            skipped += 1
            continue

        relation_confidence = min(confidences)
        frame_kind = str(getattr(frame, "kind", "frame"))
        relation_src = f"{frame_ref}|{frame_kind}|" + "|".join(
            f"{role}:{data['kg_id']}" for role, data in sorted(role_links.items(), key=lambda kv: kv[0])
        )
        relation_id = "kg:relation:" + hashlib.sha1(relation_src.encode("utf-8")).hexdigest()[:12]
        relations.append(
            {
                "frame_ref": frame_ref,
                "relation_id": relation_id,
                "confidence": relation_confidence,
                "role_links": role_links,
            }
        )

    return {
        "summary": {
            "frame_count": len(ir.frames),
            "enriched_frame_count": len(relations),
            "skipped_frame_count": skipped,
            "confidence_floor": float(confidence_floor),
        },
        "relations": relations,
    }


def apply_kg_enrichment(
    ir: LegalIR,
    entity_link_adapter: Dict[str, Any],
    relation_enrichment_adapter: Dict[str, Any],
    *,
    enable_writes: bool = True,
) -> Dict[str, Any]:
    """Apply enrichment writes with rollback patches for reversibility."""
    out = deepcopy(ir)

    rollback: Dict[str, Any] = {
        "entity_patches": [],
        "frame_patches": [],
    }

    if not enable_writes:
        return {
            "ir": out,
            "rollback": rollback,
            "summary": {
                "writes_enabled": False,
                "entity_writes": 0,
                "frame_writes": 0,
            },
        }

    entity_writes = 0
    for row in entity_link_adapter.get("entity_links") or []:
        entity_ref = row["entity_ref"]
        entity = out.entities.get(entity_ref)
        if entity is None:
            continue

        prev_link = entity.attrs.get("kg_link")
        prev_conf = entity.attrs.get("kg_link_confidence")

        entity.attrs["kg_link"] = row["kg_id"]
        entity.attrs["kg_link_confidence"] = float(row.get("confidence") or 0.0)

        rollback["entity_patches"].append(
            {
                "entity_ref": entity_ref,
                "prev": {
                    "kg_link": prev_link,
                    "kg_link_confidence": prev_conf,
                },
            }
        )
        entity_writes += 1

    frame_writes = 0
    for row in relation_enrichment_adapter.get("relations") or []:
        frame_ref = row["frame_ref"]
        frame = out.frames.get(frame_ref)
        if frame is None:
            continue

        prev_role_links = frame.attrs.get("kg_role_links")
        prev_rel_id = frame.attrs.get("kg_relation_id")
        prev_rel_conf = frame.attrs.get("kg_relation_confidence")

        frame.attrs["kg_role_links"] = {
            role: data["kg_id"]
            for role, data in sorted((row.get("role_links") or {}).items(), key=lambda kv: kv[0])
        }
        frame.attrs["kg_relation_id"] = row["relation_id"]
        frame.attrs["kg_relation_confidence"] = float(row.get("confidence") or 0.0)

        rollback["frame_patches"].append(
            {
                "frame_ref": frame_ref,
                "prev": {
                    "kg_role_links": prev_role_links,
                    "kg_relation_id": prev_rel_id,
                    "kg_relation_confidence": prev_rel_conf,
                },
            }
        )
        frame_writes += 1

    return {
        "ir": out,
        "rollback": rollback,
        "summary": {
            "writes_enabled": True,
            "entity_writes": entity_writes,
            "frame_writes": frame_writes,
        },
    }


def rollback_kg_enrichment(ir: LegalIR, rollback_plan: Dict[str, Any]) -> LegalIR:
    """Rollback KG enrichment writes from a prior `apply_kg_enrichment` result."""
    out = deepcopy(ir)

    for patch in rollback_plan.get("entity_patches") or []:
        entity_ref = patch.get("entity_ref")
        entity = out.entities.get(entity_ref)
        if entity is None:
            continue
        prev = patch.get("prev") or {}

        if prev.get("kg_link") is None:
            entity.attrs.pop("kg_link", None)
        else:
            entity.attrs["kg_link"] = prev.get("kg_link")

        if prev.get("kg_link_confidence") is None:
            entity.attrs.pop("kg_link_confidence", None)
        else:
            entity.attrs["kg_link_confidence"] = prev.get("kg_link_confidence")

    for patch in rollback_plan.get("frame_patches") or []:
        frame_ref = patch.get("frame_ref")
        frame = out.frames.get(frame_ref)
        if frame is None:
            continue
        prev = patch.get("prev") or {}

        if prev.get("kg_role_links") is None:
            frame.attrs.pop("kg_role_links", None)
        else:
            frame.attrs["kg_role_links"] = prev.get("kg_role_links")

        if prev.get("kg_relation_id") is None:
            frame.attrs.pop("kg_relation_id", None)
        else:
            frame.attrs["kg_relation_id"] = prev.get("kg_relation_id")

        if prev.get("kg_relation_confidence") is None:
            frame.attrs.pop("kg_relation_confidence", None)
        else:
            frame.attrs["kg_relation_confidence"] = prev.get("kg_relation_confidence")

    return out


def build_kg_drift_assessment(
    *,
    baseline_relation_count: int,
    baseline_frame_count: int,
    candidate_relation_adapter: Dict[str, Any],
    max_relation_growth_factor: float = 2.0,
    max_relations_per_frame: int = 8,
) -> Dict[str, Any]:
    """Assess KG enrichment drift risk to guard against relation explosion."""
    relations = list(candidate_relation_adapter.get("relations") or [])
    candidate_relation_count = len(relations)
    candidate_frame_count = int((candidate_relation_adapter.get("summary") or {}).get("frame_count") or 0)

    baseline_relation_count = int(max(0, baseline_relation_count))
    baseline_frame_count = int(max(0, baseline_frame_count))
    candidate_frame_count = max(candidate_frame_count, baseline_frame_count, 1)

    candidate_relations_per_frame = float(candidate_relation_count) / float(candidate_frame_count)
    baseline_relations_per_frame = (
        float(baseline_relation_count) / float(baseline_frame_count)
        if baseline_frame_count > 0
        else 0.0
    )

    growth_factor = float("inf")
    if baseline_relation_count > 0:
        growth_factor = float(candidate_relation_count) / float(baseline_relation_count)
    elif candidate_relation_count == 0:
        growth_factor = 1.0

    checks: List[Dict[str, Any]] = []
    checks.append(
        {
            "type": "relation_growth_factor",
            "baseline": baseline_relation_count,
            "candidate": candidate_relation_count,
            "value": growth_factor,
            "threshold": float(max_relation_growth_factor),
            "passed": bool(growth_factor <= float(max_relation_growth_factor)),
            "message": "candidate relation growth must stay under configured factor",
        }
    )
    checks.append(
        {
            "type": "relations_per_frame",
            "baseline": baseline_relations_per_frame,
            "candidate": candidate_relations_per_frame,
            "threshold": float(max_relations_per_frame),
            "passed": bool(candidate_relations_per_frame <= float(max_relations_per_frame)),
            "message": "candidate average relations per frame must stay under configured cap",
        }
    )

    failures = [c for c in checks if not c.get("passed")]
    return {
        "summary": {
            "baseline_relation_count": baseline_relation_count,
            "candidate_relation_count": candidate_relation_count,
            "baseline_relations_per_frame": baseline_relations_per_frame,
            "candidate_relations_per_frame": candidate_relations_per_frame,
            "drift_safe": len(failures) == 0,
            "failure_count": len(failures),
        },
        "checks": checks,
    }
