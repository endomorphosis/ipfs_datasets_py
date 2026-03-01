from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple

from municipal_scrape_workspace.hybrid_legal_ir import (
    ActionFrame,
    DeonticOp,
    LegalIR,
    Norm,
    generate_cnl,
)

from .models import (
    IRReference,
    PROOF_SCHEMA_VERSION,
    ProofCertificate,
    ProofObject,
    ProofStep,
    SourceProvenance,
)
from .prover_backends import ProverBackendRegistry, create_default_prover_registry


TimeRange = Tuple[str, str]


class HybridLawReasoner:
    """Proof-producing hybrid reasoner over LegalIR.

    Architecture:
    - DCEC/dynamic deontic lane for norm activation and compliance checks,
    - temporal FOL lane for deadline/window/interval reasoning,
    - proof graph lane for explainability and source traceability.
    """

    def __init__(
        self,
        kb: LegalIR,
        *,
        provenance_by_norm: Optional[Dict[str, SourceProvenance]] = None,
        definitions: Optional[Dict[str, Any]] = None,
        prover_registry: Optional[ProverBackendRegistry] = None,
    ) -> None:
        self.kb = kb
        self.definitions = definitions or {}
        self.provenance_by_norm = provenance_by_norm or {}
        self._prover_registry = prover_registry or create_default_prover_registry()
        self._proof_store: Dict[str, ProofObject] = {}

    def list_proof_ids(self) -> List[str]:
        return sorted(self._proof_store.keys())

    def get_proof(self, proof_id: str) -> ProofObject:
        if proof_id not in self._proof_store:
            raise KeyError(f"unknown proof_id: {proof_id}")
        return self._proof_store[proof_id]

    def register_proof(self, proof: ProofObject) -> None:
        if not proof.schema_version:
            proof.schema_version = PROOF_SCHEMA_VERSION
        canonical_payload = self._canonical_proof_payload(
            query=proof.query,
            root_conclusion=proof.root_conclusion,
            steps=proof.steps,
            status=proof.status,
            certificates=proof.certificates,
            certificate_trace_map=proof.certificate_trace_map,
        )
        canonical_json = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"))
        expected_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        expected_id = f"pf_{expected_hash[:12]}"
        if not proof.proof_hash:
            proof.proof_hash = expected_hash
        if not proof.proof_id:
            proof.proof_id = expected_id
        self._proof_store[proof.proof_id] = proof

    def validate_proof_replay(self, proof_id: str) -> Dict[str, Any]:
        proof = self.get_proof(proof_id)
        canonical_payload = self._canonical_proof_payload(
            query=proof.query,
            root_conclusion=proof.root_conclusion,
            steps=proof.steps,
            status=proof.status,
            certificates=proof.certificates,
            certificate_trace_map=proof.certificate_trace_map,
        )
        canonical_json = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"))
        expected_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        expected_proof_id = f"pf_{expected_hash[:12]}"
        return {
            "proof_id": proof.proof_id,
            "expected_proof_id": expected_proof_id,
            "proof_hash": proof.proof_hash,
            "expected_proof_hash": expected_hash,
            "replay_match": bool(proof.proof_id == expected_proof_id and proof.proof_hash == expected_hash),
        }

    def check_compliance(
        self,
        query: Dict[str, Any],
        time_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Check compliance of active norms for the query/time context.

        API signature required by architecture contract.
        """
        steps: List[ProofStep] = []
        facts = query.get("facts") or {}
        events = query.get("events") or []
        actor_ref = str(query.get("actor_ref") or "")
        frame_ref = str(query.get("frame_ref") or "")

        norm_candidates = self._select_norms(actor_ref=actor_ref, frame_ref=frame_ref)
        obligations_checked: List[str] = []
        violations: List[Dict[str, Any]] = []
        exceptions_applied: List[str] = []
        conflicts: List[Dict[str, Any]] = []
        active_modalities: Dict[str, List[DeonticOp]] = {}

        for norm in norm_candidates:
            obligations_checked.append(norm.id.ref())
            activation = self._eval_activation(norm, facts)
            exception_hit = self._eval_exceptions(norm, facts)
            temporal_ok = self._eval_temporal(norm, time_context)

            step_activation = self._emit_step(
                steps,
                rule_id="DCEC_ACTIVATION",
                premises=[],
                conclusion=f"active({norm.id.ref()})={activation}",
                norm=norm,
                timestamp=time_context.get("at_time"),
            )
            step_exception = self._emit_step(
                steps,
                rule_id="DCEC_EXCEPTION_CHECK",
                premises=[step_activation.step_id],
                conclusion=f"exception({norm.id.ref()})={exception_hit}",
                norm=norm,
                timestamp=time_context.get("at_time"),
            )
            step_temporal = self._emit_step(
                steps,
                rule_id="TEMPORAL_GUARD",
                premises=[step_activation.step_id],
                conclusion=f"temporal_guard({norm.id.ref()})={temporal_ok}",
                norm=norm,
                timestamp=time_context.get("at_time"),
            )

            is_in_force = activation and (not exception_hit) and temporal_ok
            self._emit_step(
                steps,
                rule_id="NORM_IN_FORCE",
                premises=[step_activation.step_id, step_exception.step_id, step_temporal.step_id],
                conclusion=f"in_force({norm.id.ref()})={is_in_force}",
                norm=norm,
                timestamp=time_context.get("at_time"),
            )

            if exception_hit:
                exceptions_applied.append(norm.id.ref())

            if not is_in_force:
                continue

            active_modalities.setdefault(norm.target_frame_ref, []).append(norm.op)
            matched = self._has_matching_event(norm, events, time_context)
            self._emit_step(
                steps,
                rule_id="EVENT_MATCH",
                premises=[],
                conclusion=f"event_match({norm.target_frame_ref})={matched}",
                norm=norm,
                timestamp=time_context.get("at_time"),
            )

            if norm.op == DeonticOp.O and not matched:
                violations.append(
                    {
                        "norm_id": norm.id.ref(),
                        "frame_id": norm.target_frame_ref,
                        "violation_type": "omission",
                        "time": time_context.get("at_time"),
                    }
                )
            if norm.op == DeonticOp.F and matched:
                violations.append(
                    {
                        "norm_id": norm.id.ref(),
                        "frame_id": norm.target_frame_ref,
                        "violation_type": "forbidden_action",
                        "time": time_context.get("at_time"),
                    }
                )

        for frame_id, mods in active_modalities.items():
            if DeonticOp.O in mods and DeonticOp.F in mods:
                conflicts.append(
                    {
                        "frame_id": frame_id,
                        "conflict": "O(phi) and F(phi) active concurrently",
                    }
                )
                self._emit_step(
                    steps,
                    rule_id="CONFLICT_O_F",
                    premises=[],
                    conclusion=f"conflict({frame_id})=true",
                    norm=None,
                    frame_id=frame_id,
                    timestamp=time_context.get("at_time"),
                )

        status: Literal["compliant", "non_compliant", "inconclusive"]
        if violations:
            status = "non_compliant"
        elif obligations_checked:
            status = "compliant"
        else:
            status = "inconclusive"

        proof = self._store_proof(
            query={"kind": "check_compliance", "query": query, "time_context": time_context},
            root_conclusion=f"compliance={status}",
            steps=steps,
            status="proved" if status != "inconclusive" else "inconclusive",
        )
        return {
            "status": status,
            "obligations_checked": obligations_checked,
            "violations": violations,
            "exceptions_applied": exceptions_applied,
            "conflicts": conflicts,
            "proof_id": proof.proof_id,
        }

    def find_violations(
        self,
        state: Dict[str, Any],
        time_range: TimeRange,
    ) -> Dict[str, Any]:
        """Find violations across a time range.

        API signature required by architecture contract.
        """
        start_ts, end_ts = time_range
        events = state.get("events") or []
        facts = state.get("facts") or {}

        steps: List[ProofStep] = []
        violations: List[Dict[str, Any]] = []
        conflicting_obligations: List[Dict[str, Any]] = []
        active_by_frame: Dict[str, List[DeonticOp]] = {}

        for norm in self.kb.norms.values():
            activation = self._eval_activation(norm, facts)
            exception_hit = self._eval_exceptions(norm, facts)
            temporal_ok = self._eval_temporal(norm, {"start": start_ts, "end": end_ts})
            in_force = activation and (not exception_hit) and temporal_ok
            self._emit_step(
                steps,
                rule_id="SCAN_NORM",
                premises=[],
                conclusion=f"scan_in_force({norm.id.ref()})={in_force}",
                norm=norm,
                timestamp=end_ts,
            )
            if not in_force:
                continue

            active_by_frame.setdefault(norm.target_frame_ref, []).append(norm.op)
            matched = self._has_matching_event(norm, events, {"start": start_ts, "end": end_ts})
            if norm.op == DeonticOp.O and not matched:
                violation_type = "deadline_missed" if norm.temporal_ref else "omission"
                violations.append(
                    {
                        "norm_id": norm.id.ref(),
                        "frame_id": norm.target_frame_ref,
                        "violation_type": violation_type,
                        "time": end_ts,
                    }
                )
                self._emit_step(
                    steps,
                    rule_id="VIOLATION_OMISSION",
                    premises=[],
                    conclusion=f"violation({norm.id.ref()})={violation_type}",
                    norm=norm,
                    timestamp=end_ts,
                )
            if norm.op == DeonticOp.F and matched:
                violations.append(
                    {
                        "norm_id": norm.id.ref(),
                        "frame_id": norm.target_frame_ref,
                        "violation_type": "forbidden_action",
                        "time": end_ts,
                    }
                )
                self._emit_step(
                    steps,
                    rule_id="VIOLATION_FORBIDDEN_ACTION",
                    premises=[],
                    conclusion=f"violation({norm.id.ref()})=forbidden_action",
                    norm=norm,
                    timestamp=end_ts,
                )

        for frame_id, ops in active_by_frame.items():
            if DeonticOp.O in ops and DeonticOp.F in ops:
                conflicting_obligations.append(
                    {
                        "frame_id": frame_id,
                        "conflict": "O(phi) and F(phi)",
                    }
                )

        proof = self._store_proof(
            query={"kind": "find_violations", "time_range": [start_ts, end_ts]},
            root_conclusion=f"violations={len(violations)}",
            steps=steps,
            status="proved",
        )
        return {
            "violations": violations,
            "conflicting_obligations": conflicting_obligations,
            "summary": {
                "start": start_ts,
                "end": end_ts,
                "violation_count": len(violations),
                "conflict_count": len(conflicting_obligations),
            },
            "proof_id": proof.proof_id,
        }

    def explain_proof(self, proof_id: str, format: str = "nl") -> Dict[str, Any]:
        """Explain a stored proof object with IR and source references.

        API signature required by architecture contract.
        """
        if proof_id not in self._proof_store:
            raise KeyError(f"unknown proof_id: {proof_id}")
        proof = self._proof_store[proof_id]

        if format == "json":
            return {
                "proof_id": proof.proof_id,
                "format": "json",
                "status": proof.status,
                "query": proof.query,
                "root_conclusion": proof.root_conclusion,
                "steps": [asdict(s) for s in proof.steps],
                "reconstructed_nl": self._reconstruct_nl_lines(proof),
            }

        if format == "graph":
            edges: List[Dict[str, str]] = []
            for step in proof.steps:
                for prem in step.premises:
                    edges.append({"from": prem, "to": step.step_id})
            return {
                "proof_id": proof.proof_id,
                "format": "graph",
                "nodes": [asdict(s) for s in proof.steps],
                "edges": edges,
                "reconstructed_nl": self._reconstruct_nl_lines(proof),
            }

        nl_lines = self._reconstruct_nl_lines(proof)
        query_kind = str(proof.query.get("kind") or "unknown")
        query_summary = f"query_kind={query_kind}; steps={len(proof.steps)}"
        return {
            "proof_id": proof.proof_id,
            "format": "nl",
            "status": proof.status,
            "root_conclusion": proof.root_conclusion,
            "query_summary": query_summary,
            "renderer_version": "1.0",
            "explanation": " ".join(nl_lines),
            "steps": [asdict(s) for s in proof.steps],
            "reconstructed_nl": nl_lines,
        }

    def _select_norms(self, *, actor_ref: str, frame_ref: str) -> List[Norm]:
        selected: List[Norm] = []
        for norm in self.kb.norms.values():
            if frame_ref and norm.target_frame_ref != frame_ref:
                continue
            if actor_ref:
                frame = self.kb.frames.get(norm.target_frame_ref)
                if not frame:
                    continue
                if frame.roles.get("agent") != actor_ref:
                    continue
            selected.append(norm)
        return selected

    def _eval_activation(self, norm: Norm, facts: Dict[str, Any]) -> bool:
        cond = norm.activation
        if cond.op == "atom" and cond.atom:
            if cond.atom.pred == "true":
                return True
            if not cond.atom.args:
                return bool(facts.get(cond.atom.pred, False))
            key = f"{cond.atom.pred}:{'|'.join(str(a) for a in cond.atom.args)}"
            return bool(facts.get(key, False) or facts.get(cond.atom.pred, False))
        return True

    def _eval_exceptions(self, norm: Norm, facts: Dict[str, Any]) -> bool:
        for exc in norm.exceptions:
            if exc.op != "atom" or not exc.atom:
                continue
            if not exc.atom.args:
                if facts.get(exc.atom.pred, False):
                    return True
                continue
            key = f"{exc.atom.pred}:{'|'.join(str(a) for a in exc.atom.args)}"
            if facts.get(key, False) or facts.get(exc.atom.pred, False):
                return True
        return False

    def _eval_temporal(self, norm: Norm, time_context: Dict[str, Any]) -> bool:
        if not norm.temporal_ref:
            return True
        tc = self.kb.temporal.get(norm.temporal_ref)
        if tc is None:
            return False

        # Temporal FOL lane: normalize query interval and validate window/deadline constraints.
        start = self._parse_dt(time_context.get("start") or time_context.get("at_time"))
        end = self._parse_dt(time_context.get("end") or time_context.get("at_time"))
        if not start or not end:
            return False
        if end < start:
            return False

        expr = tc.expr
        if expr.kind == "window" and expr.duration:
            dur = self._parse_duration(expr.duration)
            if dur is None:
                return False
            return (end - start) <= dur

        if expr.kind == "deadline" and expr.end:
            deadline = self._parse_dt(expr.end)
            return bool(deadline and end <= deadline)

        if expr.kind == "interval" and expr.start and expr.end:
            lo = self._parse_dt(expr.start)
            hi = self._parse_dt(expr.end)
            return bool(lo and hi and start >= lo and end <= hi)

        return True

    def _has_matching_event(self, norm: Norm, events: Iterable[Dict[str, Any]], time_context: Dict[str, Any]) -> bool:
        frame = self.kb.frames.get(norm.target_frame_ref)
        if not isinstance(frame, ActionFrame):
            return False

        start = self._parse_dt(time_context.get("start") or time_context.get("at_time"))
        end = self._parse_dt(time_context.get("end") or time_context.get("at_time"))
        if not start or not end:
            return False

        for ev in events:
            if str(ev.get("frame_ref") or "") != norm.target_frame_ref:
                continue
            ev_t = self._parse_dt(ev.get("time"))
            if not ev_t:
                continue
            if start <= ev_t <= end:
                return True
        return False

    def _emit_step(
        self,
        sink: List[ProofStep],
        *,
        rule_id: str,
        premises: List[str],
        conclusion: str,
        norm: Optional[Norm],
        timestamp: Optional[str],
        frame_id: Optional[str] = None,
    ) -> ProofStep:
        payload = f"{rule_id}|{conclusion}|{timestamp}|{len(sink)}"
        step_id = f"st_{hashlib.sha1(payload.encode('utf-8')).hexdigest()[:10]}"
        refs: List[IRReference] = []
        prov: List[SourceProvenance] = []

        if norm is not None:
            refs.append(IRReference(kind="norm", id=norm.id.ref()))
            refs.append(IRReference(kind="frame", id=norm.target_frame_ref))
            if norm.temporal_ref:
                refs.append(IRReference(kind="temporal", id=norm.temporal_ref))
            p = self.provenance_by_norm.get(norm.id.ref())
            if p:
                prov.append(p)
            else:
                prov.append(self._fallback_provenance_for_frame(norm.target_frame_ref))
        elif frame_id:
            refs.append(IRReference(kind="frame", id=frame_id))
            prov.append(self._fallback_provenance_for_frame(frame_id))

        if not refs:
            refs.append(IRReference(kind="derived", id=f"derived:{rule_id.lower()}"))
        if not prov:
            prov.append(SourceProvenance(source_path="unknown", source_id="unknown", source_span=None))

        step = ProofStep(
            step_id=step_id,
            rule_id=rule_id,
            premises=list(premises),
            conclusion=conclusion,
            ir_refs=refs,
            provenance=prov,
            timestamp=timestamp,
            confidence=1.0,
        )
        sink.append(step)
        return step

    def _store_proof(
        self,
        *,
        query: Dict[str, Any],
        root_conclusion: str,
        steps: List[ProofStep],
        status: Literal["proved", "refuted", "inconclusive"],
    ) -> ProofObject:
        certificates, certificate_trace_map = self._build_certificates_and_traces(
            query=query,
            root_conclusion=root_conclusion,
            steps=steps,
        )
        canonical_payload = self._canonical_proof_payload(
            query=query,
            root_conclusion=root_conclusion,
            steps=steps,
            status=status,
            certificates=certificates,
            certificate_trace_map=certificate_trace_map,
        )
        canonical_json = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"))
        proof_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        proof_id = f"pf_{proof_hash[:12]}"
        po = ProofObject(
            proof_id=proof_id,
            query=query,
            root_conclusion=root_conclusion,
            steps=steps,
            status=status,
            schema_version=PROOF_SCHEMA_VERSION,
            proof_hash=proof_hash,
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            certificates=certificates,
            certificate_trace_map=certificate_trace_map,
        )
        self._proof_store[proof_id] = po
        return po

    def _canonical_proof_payload(
        self,
        *,
        query: Dict[str, Any],
        root_conclusion: str,
        steps: List[ProofStep],
        status: Literal["proved", "refuted", "inconclusive"],
        certificates: Optional[List[ProofCertificate]] = None,
        certificate_trace_map: Optional[Dict[str, List[IRReference]]] = None,
    ) -> Dict[str, Any]:
        normalized_steps: List[Dict[str, Any]] = []
        for step in steps:
            normalized_steps.append(
                {
                    "step_id": step.step_id,
                    "rule_id": step.rule_id,
                    "premises": list(step.premises),
                    "conclusion": step.conclusion,
                    "ir_refs": [{"kind": r.kind, "id": r.id} for r in step.ir_refs],
                    "provenance": [
                        {
                            "source_path": p.source_path,
                            "source_id": p.source_id,
                            "source_span": p.source_span,
                        }
                        for p in step.provenance
                    ],
                    "timestamp": step.timestamp,
                    "confidence": float(step.confidence),
                }
            )

        return {
            "schema_version": PROOF_SCHEMA_VERSION,
            "query": query,
            "root_conclusion": root_conclusion,
            "status": status,
            "steps": normalized_steps,
            "certificates": [
                {
                    "certificate_id": c.certificate_id,
                    "backend": c.backend,
                    "format": c.format,
                    "theorem": c.theorem,
                    "assumptions": list(c.assumptions),
                    "payload": self._normalize_certificate_payload(c.payload),
                    "normalized_hash": c.normalized_hash,
                }
                for c in (certificates or [])
            ],
            "certificate_trace_map": {
                cid: [{"kind": r.kind, "id": r.id} for r in refs]
                for cid, refs in sorted((certificate_trace_map or {}).items(), key=lambda kv: kv[0])
            },
        }

    @staticmethod
    def _normalize_certificate_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        normalized_json = json.dumps(dict(payload or {}), sort_keys=True, separators=(",", ":"))
        return json.loads(normalized_json)

    def _build_certificates_and_traces(
        self,
        *,
        query: Dict[str, Any],
        root_conclusion: str,
        steps: List[ProofStep],
    ) -> Tuple[List[ProofCertificate], Dict[str, List[IRReference]]]:
        theorem = str(root_conclusion)
        assumptions = [str(step.conclusion) for step in steps]

        ref_pairs = sorted(
            {
                (ref.kind, ref.id)
                for step in steps
                for ref in step.ir_refs
            },
            key=lambda kv: (kv[0], kv[1]),
        )
        trace_refs = [IRReference(kind=kind, id=rid) for kind, rid in ref_pairs]

        certificates: List[ProofCertificate] = []
        trace_map: Dict[str, List[IRReference]] = {}

        preferred_backends = ["smt_style", "first_order"]
        for backend_id in preferred_backends:
            try:
                backend = self._prover_registry.get(backend_id)
            except KeyError:
                continue
            result = backend.prove(theorem, assumptions)
            payload = self._normalize_certificate_payload(result.certificate)
            normalized = {
                "backend": result.backend,
                "status": result.status,
                "theorem": result.theorem,
                "assumptions": list(result.assumptions),
                "payload": payload,
                "query": query,
            }
            normalized_json = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
            normalized_hash = hashlib.sha256(normalized_json.encode("utf-8")).hexdigest()
            certificate_id = f"cert_{normalized_hash[:12]}"

            certificates.append(
                ProofCertificate(
                    certificate_id=certificate_id,
                    backend=result.backend,
                    format=str(payload.get("format") or "unknown"),
                    theorem=result.theorem,
                    assumptions=list(result.assumptions),
                    payload=payload,
                    normalized_hash=normalized_hash,
                )
            )
            trace_map[certificate_id] = list(trace_refs)

        return certificates, trace_map

    def _fallback_provenance_for_frame(self, frame_id: str) -> SourceProvenance:
        frame = self.kb.frames.get(frame_id)
        if frame is None:
            return SourceProvenance(source_path="unknown", source_id=frame_id or "unknown", source_span=None)
        attrs = getattr(frame, "attrs", {}) or {}
        source_path = str(attrs.get("source_path") or "kb://frame")
        source_id = str(attrs.get("source_id") or frame_id)
        source_span = frame.source_span or attrs.get("source_span")
        return SourceProvenance(
            source_path=source_path,
            source_id=source_id,
            source_span=(str(source_span) if source_span is not None else None),
        )

    def _reconstruct_nl_lines(self, proof: ProofObject) -> List[str]:
        lines: List[str] = []
        seen_norms = set()

        lines.append(
            f"Proof {proof.proof_id} concludes {proof.root_conclusion} ({proof.status})."
        )

        for idx, step in enumerate(proof.steps, start=1):
            lines.append(f"Step {idx}: {step.rule_id} infers {step.conclusion}.")
            if step.premises:
                lines.append(f"Premises: {', '.join(step.premises)}.")

            norm_ids = [r.id for r in step.ir_refs if r.kind == "norm"]
            for norm_id in norm_ids:
                if norm_id in seen_norms:
                    continue
                seen_norms.add(norm_id)
                norm = self.kb.norms.get(norm_id)
                if norm is not None:
                    lines.append(f"Norm context: {generate_cnl(norm, self.kb)}")

            if step.ir_refs:
                ref_tokens = [f"{r.kind}:{r.id}" for r in step.ir_refs]
                lines.append(f"IR refs: {', '.join(ref_tokens)}.")

            if step.provenance:
                p = step.provenance[0]
                span = f" [{p.source_span}]" if p.source_span else ""
                lines.append(
                    f"Evidence from {p.source_path}:{p.source_id}{span} supports {step.conclusion}."
                )
            else:
                lines.append(f"Rule {step.rule_id} derives {step.conclusion}.")

        if len(lines) == 1:
            lines.append(f"No proof steps found for {proof.proof_id}.")
        return lines

    @staticmethod
    def _parse_dt(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        v = value.strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(v)
        except ValueError:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def _parse_duration(token: str) -> Optional[timedelta]:
        t = token.strip().lower()
        if t.endswith("day"):
            n = t[:-3]
            return timedelta(days=int(n)) if n.isdigit() else None
        if t.endswith("hour"):
            n = t[:-4]
            return timedelta(hours=int(n)) if n.isdigit() else None
        if t.endswith("month"):
            n = t[:-5]
            return timedelta(days=30 * int(n)) if n.isdigit() else None
        if t.endswith("year"):
            n = t[:-4]
            return timedelta(days=365 * int(n)) if n.isdigit() else None
        return None
