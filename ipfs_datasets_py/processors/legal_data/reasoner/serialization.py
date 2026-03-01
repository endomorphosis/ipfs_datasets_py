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

from .models import IRReference, ProofObject, ProofStep, SourceProvenance


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

    This loader is intentionally permissive and supports id refs serialized either
    as `{namespace,value}` objects or `namespace:value` strings.
    """
    data = _load_json(path)
    ir = LegalIR(
        version=str(data.get("version") or "0.1"),
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


def proof_to_dict(proof: ProofObject) -> Dict[str, Any]:
    return {
        "proof_id": proof.proof_id,
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
