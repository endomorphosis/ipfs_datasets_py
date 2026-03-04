from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .hybrid_legal_ir import (
        ActionFrame,
        Atom,
        CanonicalId,
        Condition,
        DeonticOp,
        Entity,
        EventFrame,
        FrameKind,
        LegalIR,
        Norm,
        Query,
        Rule,
        StateFrame,
        TemporalConstraint,
        TemporalExpr,
        TemporalRelation,
    )
except ImportError:
    from municipal_scrape_workspace.hybrid_legal_ir import (  # type: ignore[no-redef]
        ActionFrame, Atom, CanonicalId, Condition, DeonticOp, Entity,
        EventFrame, FrameKind, LegalIR, Norm, Query, Rule, StateFrame,
        TemporalConstraint, TemporalExpr, TemporalRelation,
    )

from .models import (
    IRReference,
    PROOF_SCHEMA_VERSION,
    ProofCertificate,
    ProofObject,
    ProofStep,
    SourceProvenance,
)


SUPPORTED_IR_VERSION = "1.0"
SUPPORTED_CNL_VERSION = "1.0"
SUPPORTED_V2_IR_VERSION = "2.0"
SUPPORTED_V2_CNL_VERSION = "2.0"
SUPPORTED_V3_IR_VERSION = "3.0"
SUPPORTED_V3_CNL_VERSION = "3.0"

V3_ID_NAMESPACES = {"ent", "frm", "tmp", "nrm", "src"}
V3_SCHEMA_ERROR_CODES: Dict[str, str] = {
    "unsupported_ir_version": "V3_SCHEMA_UNSUPPORTED_IR_VERSION",
    "unsupported_cnl_version": "V3_SCHEMA_UNSUPPORTED_CNL_VERSION",
    "invalid_namespace": "V3_SCHEMA_INVALID_NAMESPACE",
    "id_key_mismatch": "V3_SCHEMA_ID_KEY_MISMATCH",
    "unknown_target_frame_ref": "V3_SCHEMA_UNKNOWN_TARGET_FRAME_REF",
    "unknown_temporal_ref": "V3_SCHEMA_UNKNOWN_TEMPORAL_REF",
    "unknown_source_ref": "V3_SCHEMA_UNKNOWN_SOURCE_REF",
    "unknown_role_entity_ref": "V3_SCHEMA_UNKNOWN_ROLE_ENTITY_REF",
    "orphan_frame_id": "V3_SCHEMA_ORPHAN_FRAME_ID",
    "orphan_temporal_id": "V3_SCHEMA_ORPHAN_TEMPORAL_ID",
}


def deterministic_v3_canonical_id(namespace: str, parts: List[str]) -> str:
    ns = str(namespace or "").strip().lower()
    if ns not in V3_ID_NAMESPACES:
        raise ValueError(f"invalid_namespace:{ns}: code={V3_SCHEMA_ERROR_CODES['invalid_namespace']}")
    normalized_parts = [str(p).strip().lower() for p in parts]
    payload = "|".join(normalized_parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{ns}:{digest}"


def _normalize_ref(ref_or_id: Any, fallback_namespace: str, fallback_key: str) -> str:
    if isinstance(ref_or_id, str) and ":" in ref_or_id:
        return ref_or_id
    if isinstance(ref_or_id, dict):
        ns = str(ref_or_id.get("namespace") or fallback_namespace)
        value = str(ref_or_id.get("value") or "")
        if value:
            return f"{ns}:{value}"
    return str(fallback_key)


def map_v2_payload_to_v3(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Map a V2 payload dict to a V3-compatible payload shape.

    The mapper preserves stable IDs and cross-reference fields while normalizing
    top-level version fields and source collection naming.
    """
    entities = dict(payload.get("entities") or {})
    frames = dict(payload.get("frames") or {})
    temporals = dict(payload.get("temporals") or payload.get("temporal") or {})
    norms = dict(payload.get("norms") or {})
    rules = dict(payload.get("rules") or {})
    provenance = dict(payload.get("provenance") or {})

    v3_sources: Dict[str, Dict[str, Any]] = {}
    for key, src in provenance.items():
        source_ref = _normalize_ref(key, "src", str(key))
        src_obj = dict(src or {})
        v3_sources[source_ref] = {
            "source_id": source_ref,
            "sentence_text": str(src_obj.get("sentence_text") or ""),
            "sentence_span": src_obj.get("sentence_span"),
        }

    def _normalize_id_table(items: Dict[str, Any], namespace: str) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for key, item in items.items():
            obj = dict(item or {})
            ref = _normalize_ref(obj.get("id"), namespace, str(key))
            obj["id"] = ref
            out[ref] = obj
        return out

    v3 = {
        "ir_version": SUPPORTED_V3_IR_VERSION,
        "cnl_version": SUPPORTED_V3_CNL_VERSION,
        "jurisdiction": str(payload.get("jurisdiction") or "default"),
        "entities": _normalize_id_table(entities, "ent"),
        "frames": _normalize_id_table(frames, "frm"),
        "temporals": _normalize_id_table(temporals, "tmp"),
        "norms": _normalize_id_table(norms, "nrm"),
        "definitions": _normalize_id_table({
            k: v for k, v in rules.items() if str((v or {}).get("mode") or "") == "definition"
        }, "rul"),
        "sources": v3_sources,
    }
    return v3


def validate_v3_ir_payload(payload: Dict[str, Any], *, strict: bool = True) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    ir_version = _stringify_version(payload.get("ir_version") or payload.get("version"))
    cnl_version = _stringify_version(payload.get("cnl_version"))
    if ir_version != SUPPORTED_V3_IR_VERSION:
        errors.append(
            f"unsupported_ir_version:{ir_version}: code={V3_SCHEMA_ERROR_CODES['unsupported_ir_version']}"
        )
    if cnl_version != SUPPORTED_V3_CNL_VERSION:
        errors.append(
            f"unsupported_cnl_version:{cnl_version}: code={V3_SCHEMA_ERROR_CODES['unsupported_cnl_version']}"
        )

    entities = dict(payload.get("entities") or {})
    frames = dict(payload.get("frames") or {})
    temporals = dict(payload.get("temporals") or {})
    norms = dict(payload.get("norms") or {})
    sources = dict(payload.get("sources") or {})

    def _check_table(table: Dict[str, Any], namespace: str, kind: str) -> None:
        for key, item in table.items():
            ref = _normalize_ref((item or {}).get("id") if isinstance(item, dict) else None, namespace, str(key))
            if not ref.startswith(f"{namespace}:"):
                errors.append(
                    f"invalid_namespace:{kind}:{ref}: code={V3_SCHEMA_ERROR_CODES['invalid_namespace']}"
                )
            if str(key) != ref:
                errors.append(
                    f"id_key_mismatch:{kind}:{key}->{ref}: code={V3_SCHEMA_ERROR_CODES['id_key_mismatch']}"
                )

    _check_table(entities, "ent", "entity")
    _check_table(frames, "frm", "frame")
    _check_table(temporals, "tmp", "temporal")
    _check_table(norms, "nrm", "norm")
    _check_table(sources, "src", "source")

    referenced_frames = set()
    referenced_temporals = set()

    for key, norm in norms.items():
        norm_obj = dict(norm or {})
        target_frame_ref = str(norm_obj.get("target_frame_ref") or "")
        if target_frame_ref:
            referenced_frames.add(target_frame_ref)
            if target_frame_ref not in frames:
                errors.append(
                    "unknown_target_frame_ref:"
                    f"{key}->{target_frame_ref}: code={V3_SCHEMA_ERROR_CODES['unknown_target_frame_ref']}"
                )

        temporal_ref = norm_obj.get("temporal_ref")
        if temporal_ref:
            temporal_ref = str(temporal_ref)
            referenced_temporals.add(temporal_ref)
            if temporal_ref not in temporals:
                errors.append(
                    "unknown_temporal_ref:"
                    f"{key}->{temporal_ref}: code={V3_SCHEMA_ERROR_CODES['unknown_temporal_ref']}"
                )

        source_ref = norm_obj.get("source_ref")
        if source_ref:
            source_ref = str(source_ref)
            if source_ref not in sources:
                errors.append(
                    "unknown_source_ref:"
                    f"{key}->{source_ref}: code={V3_SCHEMA_ERROR_CODES['unknown_source_ref']}"
                )

    for frame_key, frame in frames.items():
        frame_obj = dict(frame or {})
        for role_ref in (frame_obj.get("roles") or {}).values():
            role_ref = str(role_ref)
            if role_ref.startswith("ent:") and role_ref not in entities:
                errors.append(
                    "unknown_role_entity_ref:"
                    f"{frame_key}->{role_ref}: code={V3_SCHEMA_ERROR_CODES['unknown_role_entity_ref']}"
                )

    for frame_ref in frames.keys():
        if frame_ref not in referenced_frames:
            warnings.append(
                f"orphan_frame_id:{frame_ref}: code={V3_SCHEMA_ERROR_CODES['orphan_frame_id']}"
            )
    for temporal_ref in temporals.keys():
        if temporal_ref not in referenced_temporals:
            warnings.append(
                f"orphan_temporal_id:{temporal_ref}: code={V3_SCHEMA_ERROR_CODES['orphan_temporal_id']}"
            )

    if strict and warnings:
        errors.extend(warnings)

    if errors:
        raise ValueError("invalid_v3_ir_payload: " + "; ".join(errors))

    return {
        "ok": True,
        "warnings": warnings,
        "warning_codes": [
            str(w.split("code=", 1)[1]) for w in warnings if "code=" in str(w)
        ],
    }


def _stringify_version(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def validate_contract_versions(
    *,
    ir_version: str,
    cnl_version: str,
    source_label: str,
) -> None:
    if ir_version != SUPPORTED_IR_VERSION:
        raise ValueError(
            f"{source_label}: unsupported ir_version '{ir_version}' "
            f"(expected '{SUPPORTED_IR_VERSION}')"
        )
    if cnl_version != SUPPORTED_CNL_VERSION:
        raise ValueError(
            f"{source_label}: unsupported cnl_version '{cnl_version}' "
            f"(expected '{SUPPORTED_CNL_VERSION}')"
        )


def validate_v2_contract_versions(
    *,
    ir_version: str,
    cnl_version: str,
    source_label: str,
) -> None:
    """Validate version fields for the V2 IR/CNL contract."""
    if ir_version != SUPPORTED_V2_IR_VERSION:
        raise ValueError(
            f"{source_label}: unsupported v2 ir_version '{ir_version}' "
            f"(expected '{SUPPORTED_V2_IR_VERSION}')"
        )
    if cnl_version != SUPPORTED_V2_CNL_VERSION:
        raise ValueError(
            f"{source_label}: unsupported v2 cnl_version '{cnl_version}' "
            f"(expected '{SUPPORTED_V2_CNL_VERSION}')"
        )


def _upgrade_legacy_contract_versions(payload: Dict[str, Any]) -> Dict[str, Any]:
    upgraded = dict(payload)
    upgraded["version"] = SUPPORTED_IR_VERSION
    upgraded["ir_version"] = SUPPORTED_IR_VERSION
    upgraded["cnl_version"] = SUPPORTED_CNL_VERSION
    return upgraded


def _find_embedded_hybrid_ir_json(payload: Any) -> Optional[Dict[str, Any]]:
    queue: List[Any] = [payload]
    while queue:
        current = queue.pop(0)
        if isinstance(current, dict):
            embedded = current.get("hybridIRJson")
            if isinstance(embedded, str):
                try:
                    candidate = json.loads(embedded)
                except json.JSONDecodeError:
                    candidate = None
                if isinstance(candidate, dict):
                    return candidate
            queue.extend(v for v in current.values() if isinstance(v, (dict, list)))
            continue
        if isinstance(current, list):
            queue.extend(current)
    return None


def _looks_like_legacy_logic_hybrid_fixture(payload: Dict[str, Any], source_label: str) -> bool:
    is_logic_hybrid_name = Path(source_label).name == "logic.hybrid.jsonld"
    has_embedded_ir = _find_embedded_hybrid_ir_json(payload) is not None
    return is_logic_hybrid_name or has_embedded_ir


def _extract_ir_payload(payload: Dict[str, Any], source_label: str) -> Dict[str, Any]:
    if "norms" in payload and "frames" in payload:
        return payload
    embedded = _find_embedded_hybrid_ir_json(payload)
    if embedded is not None:
        return embedded
    raise ValueError(f"{source_label}: could not locate LegalIR payload in JSON")


def _normalize_and_validate_contract(
    payload: Dict[str, Any],
    *,
    source_label: str,
    allow_legacy_versions: bool,
) -> Dict[str, Any]:
    ir_version = _stringify_version(payload.get("ir_version") or payload.get("version"))
    cnl_version = _stringify_version(payload.get("cnl_version"))

    if allow_legacy_versions:
        if ir_version in {"", "0.1"}:
            ir_version = SUPPORTED_IR_VERSION
        if cnl_version in {"", "0.1"}:
            cnl_version = SUPPORTED_CNL_VERSION
        payload = dict(payload)
        payload["version"] = ir_version
        payload["ir_version"] = ir_version
        payload["cnl_version"] = cnl_version

    validate_contract_versions(
        ir_version=ir_version,
        cnl_version=cnl_version,
        source_label=source_label,
    )
    return payload


def _load_json(path: str | Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _canonical_id_from_ref(ref: str) -> CanonicalId:
    ns, value = str(ref).split(":", 1)
    return CanonicalId(namespace=ns, value=value)


def _condition_from_dict(data: Dict[str, Any]) -> Condition:
    atom_data = data.get("atom")
    atom = None
    if isinstance(atom_data, dict):
        atom = Atom(
            pred=str(atom_data.get("pred") or ""),
            args=[str(x) for x in (atom_data.get("args") or [])],
        )
    children = [_condition_from_dict(c) for c in (data.get("children") or []) if isinstance(c, dict)]
    return Condition(
        op=str(data.get("op") or "atom"),
        atom=atom,
        children=children,
        var=(str(data.get("var")) if data.get("var") is not None else None),
        var_type=(str(data.get("var_type")) if data.get("var_type") is not None else None),
    )


def _frame_from_dict(data: Dict[str, Any]):
    fid = _canonical_id_from_ref(str(data.get("id", {}).get("namespace", "frm") + ":" + data.get("id", {}).get("value", ""))) if isinstance(data.get("id"), dict) else _canonical_id_from_ref(str(data.get("id") if isinstance(data.get("id"), str) else "frm:unknown"))
    kind_raw = str(data.get("kind") or FrameKind.ACTION.value)
    kind = FrameKind(kind_raw)

    base_kwargs = dict(
        id=fid,
        kind=kind,
        roles={str(k): str(v) for k, v in (data.get("roles") or {}).items()},
        jurisdiction=(str(data.get("jurisdiction")) if data.get("jurisdiction") is not None else None),
        source_span=(str(data.get("source_span")) if data.get("source_span") is not None else None),
        attrs=dict(data.get("attrs") or {}),
    )

    if kind == FrameKind.ACTION:
        return ActionFrame(verb=str(data.get("verb") or ""), **base_kwargs)
    if kind == FrameKind.EVENT:
        return EventFrame(event_type=str(data.get("event_type") or ""), **base_kwargs)
    return StateFrame(state_type=str(data.get("state_type") or ""), **base_kwargs)


def load_legal_ir_from_json(path: str | Path) -> LegalIR:
    """Load LegalIR from a JSON snapshot produced by `hybrid_legal_ir.to_json`.

    Runtime contract:
    - `ir_version` must be `1.0`
    - `cnl_version` must be `1.0`

    Existing `logic.hybrid.jsonld` fixtures are supported through automatic
    backward-compat extraction/upgrading of embedded `hybridIRJson` payloads.
    """
    path_obj = Path(path)
    data = _load_json(path_obj)
    source_label = str(path_obj)

    allow_legacy_versions = False
    if isinstance(data, dict) and _looks_like_legacy_logic_hybrid_fixture(data, source_label):
        data = _extract_ir_payload(data, source_label)
        allow_legacy_versions = True

    data = _normalize_and_validate_contract(
        data,
        source_label=source_label,
        allow_legacy_versions=allow_legacy_versions,
    )

    ir = LegalIR(
        version=str(data.get("ir_version") or data.get("version") or SUPPORTED_IR_VERSION),
        jurisdiction=str(data.get("jurisdiction") or "default"),
        clock=str(data.get("clock") or "discrete"),
    )

    for k, ent in (data.get("entities") or {}).items():
        ent_id = ent.get("id")
        if isinstance(ent_id, dict):
            cid = CanonicalId(namespace=str(ent_id.get("namespace") or "ent"), value=str(ent_id.get("value") or "unknown"))
        else:
            cid = _canonical_id_from_ref(str(ent_id or k))
        ir.entities[cid.ref()] = Entity(
            id=cid,
            type_name=str(ent.get("type_name") or "Entity"),
            attrs=dict(ent.get("attrs") or {}),
        )

    for k, frm in (data.get("frames") or {}).items():
        try:
            frame = _frame_from_dict(frm)
        except Exception:
            frame = _frame_from_dict({"id": k, **dict(frm or {})})
        ir.frames[frame.id.ref()] = frame

    for k, tmp in (data.get("temporal") or {}).items():
        tid_raw = tmp.get("id")
        if isinstance(tid_raw, dict):
            tid = CanonicalId(namespace=str(tid_raw.get("namespace") or "tmp"), value=str(tid_raw.get("value") or "unknown"))
        else:
            tid = _canonical_id_from_ref(str(tid_raw or k))
        expr_data = dict(tmp.get("expr") or {})
        expr = TemporalExpr(
            kind=str(expr_data.get("kind") or "window"),
            start=(str(expr_data.get("start")) if expr_data.get("start") is not None else None),
            end=(str(expr_data.get("end")) if expr_data.get("end") is not None else None),
            duration=(str(expr_data.get("duration")) if expr_data.get("duration") is not None else None),
            anchor_ref=(str(expr_data.get("anchor_ref")) if expr_data.get("anchor_ref") is not None else None),
        )
        rel = TemporalRelation(str(tmp.get("relation") or TemporalRelation.WITHIN.value))
        ir.temporal[tid.ref()] = TemporalConstraint(
            id=tid,
            expr=expr,
            relation=rel,
            calendar=str(tmp.get("calendar") or "gregorian"),
            tz=str(tmp.get("tz") or "UTC"),
            attrs=dict(tmp.get("attrs") or {}),
        )

    for k, n in (data.get("norms") or {}).items():
        nid_raw = n.get("id")
        if isinstance(nid_raw, dict):
            nid = CanonicalId(namespace=str(nid_raw.get("namespace") or "nrm"), value=str(nid_raw.get("value") or "unknown"))
        else:
            nid = _canonical_id_from_ref(str(nid_raw or k))
        op = DeonticOp(str(n.get("op") or DeonticOp.O.value))
        activation = _condition_from_dict(dict(n.get("activation") or {"op": "atom", "atom": {"pred": "true", "args": []}}))
        exceptions = [_condition_from_dict(e) for e in (n.get("exceptions") or []) if isinstance(e, dict)]
        ir.norms[nid.ref()] = Norm(
            id=nid,
            op=op,
            target_frame_ref=str(n.get("target_frame_ref") or ""),
            activation=activation,
            exceptions=exceptions,
            temporal_ref=(str(n.get("temporal_ref")) if n.get("temporal_ref") is not None else None),
            priority=int(n.get("priority") or 0),
            jurisdiction=(str(n.get("jurisdiction")) if n.get("jurisdiction") is not None else None),
            attrs=dict(n.get("attrs") or {}),
        )

    for k, r in (data.get("rules") or {}).items():
        rid_raw = r.get("id")
        if isinstance(rid_raw, dict):
            rid = CanonicalId(namespace=str(rid_raw.get("namespace") or "rul"), value=str(rid_raw.get("value") or "unknown"))
        else:
            rid = _canonical_id_from_ref(str(rid_raw or k))
        consequent_data = dict(r.get("consequent") or {})
        consequent = Atom(
            pred=str(consequent_data.get("pred") or "true"),
            args=[str(x) for x in (consequent_data.get("args") or [])],
        )
        ir.rules[rid.ref()] = Rule(
            id=rid,
            antecedent=_condition_from_dict(dict(r.get("antecedent") or {"op": "atom", "atom": {"pred": "true", "args": []}})),
            consequent=consequent,
            mode=str(r.get("mode") or "strict"),
        )

    for k, q in (data.get("queries") or {}).items():
        qid_raw = q.get("id")
        if isinstance(qid_raw, dict):
            qid = CanonicalId(namespace=str(qid_raw.get("namespace") or "qry"), value=str(qid_raw.get("value") or "unknown"))
        else:
            qid = _canonical_id_from_ref(str(qid_raw or k))
        ir.queries[qid.ref()] = Query(
            id=qid,
            goal=_condition_from_dict(dict(q.get("goal") or {"op": "atom", "atom": {"pred": "true", "args": []}})),
            at=(str(q.get("at")) if q.get("at") is not None else None),
        )

    return ir


def load_legacy_logic_hybrid_fixture(path: str | Path) -> LegalIR:
    """Load `logic.hybrid.jsonld` fixtures produced by older conversion runs.

    The legacy fixture embeds one or more `hybridIRJson` snapshots (typically
    with `version=0.1`) inside report-like JSON. This loader extracts the first
    embedded IR payload and upgrades contract fields to runtime `1.0` versions.
    """
    source_label = str(path)
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"{source_label}: expected object payload")
    embedded = _extract_ir_payload(payload, source_label)
    upgraded = _upgrade_legacy_contract_versions(embedded)
    tmp_path = Path(path)
    # Reuse canonical loader behavior by materializing an in-memory payload path contract.
    # The write/read round-trip is avoided by directly applying the same parse path.
    data = _normalize_and_validate_contract(
        upgraded,
        source_label=f"{tmp_path}#legacy",
        allow_legacy_versions=False,
    )
    scratch = tmp_path.parent / f".{tmp_path.stem}.contract.v1.tmp.json"
    write_json(scratch, data)
    try:
        return load_legal_ir_from_json(scratch)
    finally:
        if scratch.exists():
            scratch.unlink()


def proof_to_dict(proof: ProofObject) -> Dict[str, Any]:
    return {
        "proof_id": proof.proof_id,
        "schema_version": proof.schema_version,
        "proof_hash": proof.proof_hash,
        "created_at": proof.created_at,
        "query": proof.query,
        "root_conclusion": proof.root_conclusion,
        "status": proof.status,
        "certificates": [
            {
                "certificate_id": c.certificate_id,
                "backend": c.backend,
                "format": c.format,
                "theorem": c.theorem,
                "assumptions": list(c.assumptions),
                "payload": dict(c.payload),
                "normalized_hash": c.normalized_hash,
            }
            for c in proof.certificates
        ],
        "certificate_trace_map": {
            cid: [{"kind": r.kind, "id": r.id} for r in refs]
            for cid, refs in sorted(proof.certificate_trace_map.items(), key=lambda kv: kv[0])
        },
        "steps": [
            {
                "step_id": s.step_id,
                "rule_id": s.rule_id,
                "premises": list(s.premises),
                "conclusion": s.conclusion,
                "ir_refs": [{"kind": r.kind, "id": r.id} for r in s.ir_refs],
                "provenance": [
                    {
                        "source_path": p.source_path,
                        "source_id": p.source_id,
                        "source_span": p.source_span,
                    }
                    for p in s.provenance
                ],
                "timestamp": s.timestamp,
                "confidence": s.confidence,
            }
            for s in proof.steps
        ],
    }


def proof_from_dict(data: Dict[str, Any]) -> ProofObject:
    certificates: List[ProofCertificate] = []
    for c in (data.get("certificates") or []):
        if not isinstance(c, dict):
            continue
        certificates.append(
            ProofCertificate(
                certificate_id=str(c.get("certificate_id") or ""),
                backend=str(c.get("backend") or ""),
                format=str(c.get("format") or ""),
                theorem=str(c.get("theorem") or ""),
                assumptions=[str(x) for x in (c.get("assumptions") or [])],
                payload=dict(c.get("payload") or {}),
                normalized_hash=str(c.get("normalized_hash") or ""),
            )
        )

    certificate_trace_map: Dict[str, List[IRReference]] = {}
    trace_map_raw = data.get("certificate_trace_map") or {}
    if isinstance(trace_map_raw, dict):
        for cid, refs in trace_map_raw.items():
            if not isinstance(refs, list):
                continue
            certificate_trace_map[str(cid)] = [
                IRReference(kind=str(r.get("kind") or "derived"), id=str(r.get("id") or ""))
                for r in refs
                if isinstance(r, dict)
            ]

    steps: List[ProofStep] = []
    for s in (data.get("steps") or []):
        ir_refs = [
            IRReference(kind=str(r.get("kind") or "derived"), id=str(r.get("id") or ""))
            for r in (s.get("ir_refs") or [])
        ]
        provenance = [
            SourceProvenance(
                source_path=str(p.get("source_path") or ""),
                source_id=str(p.get("source_id") or ""),
                source_span=(str(p.get("source_span")) if p.get("source_span") is not None else None),
            )
            for p in (s.get("provenance") or [])
        ]
        steps.append(
            ProofStep(
                step_id=str(s.get("step_id") or ""),
                rule_id=str(s.get("rule_id") or ""),
                premises=[str(x) for x in (s.get("premises") or [])],
                conclusion=str(s.get("conclusion") or ""),
                ir_refs=ir_refs,
                provenance=provenance,
                timestamp=(str(s.get("timestamp")) if s.get("timestamp") is not None else None),
                confidence=float(s.get("confidence") or 1.0),
            )
        )

    return ProofObject(
        proof_id=str(data.get("proof_id") or ""),
        query=dict(data.get("query") or {}),
        root_conclusion=str(data.get("root_conclusion") or ""),
        steps=steps,
        status=str(data.get("status") or "inconclusive"),
        schema_version=str(data.get("schema_version") or PROOF_SCHEMA_VERSION),
        proof_hash=str(data.get("proof_hash") or ""),
        created_at=(str(data.get("created_at")) if data.get("created_at") is not None else None),
        certificates=certificates,
        certificate_trace_map=certificate_trace_map,
    )


def write_json(path: str | Path, payload: Dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_proof_store(path: str | Path) -> Dict[str, ProofObject]:
    """Load a proof store from disk.

    Accepted formats:
    - {"proofs": [proof_obj, ...]}
    - {"proofs": {"proof_id": proof_obj, ...}}
    - {"proof_id": proof_obj, ...} (bare map)
    """
    p = Path(path)
    if not p.exists():
        return {}
    payload = _load_json(p)
    root = payload.get("proofs") if isinstance(payload, dict) and "proofs" in payload else payload
    out: Dict[str, ProofObject] = {}

    if isinstance(root, list):
        for item in root:
            if not isinstance(item, dict):
                continue
            po = proof_from_dict(item)
            if po.proof_id:
                out[po.proof_id] = po
        return out

    if isinstance(root, dict):
        for key, value in root.items():
            if isinstance(value, dict):
                po = proof_from_dict(value)
                pid = po.proof_id or str(key)
                if pid:
                    if not po.proof_id:
                        po.proof_id = pid
                    out[pid] = po
        return out

    return {}


def write_proof_store(path: str | Path, proofs: Dict[str, ProofObject]) -> None:
    payload = {
        "proofs": {
            pid: proof_to_dict(proof)
            for pid, proof in sorted(proofs.items(), key=lambda kv: kv[0])
        }
    }
    write_json(path, payload)


def append_proof_to_store(path: str | Path, proof: ProofObject) -> None:
    proofs = load_proof_store(path)
    proofs[proof.proof_id] = proof
    write_proof_store(path, proofs)
