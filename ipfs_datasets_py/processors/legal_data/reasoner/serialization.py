from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from municipal_scrape_workspace.hybrid_legal_ir import (
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

from .models import IRReference, PROOF_SCHEMA_VERSION, ProofObject, ProofStep, SourceProvenance


SUPPORTED_IR_VERSION = "1.0"
SUPPORTED_CNL_VERSION = "1.0"


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
