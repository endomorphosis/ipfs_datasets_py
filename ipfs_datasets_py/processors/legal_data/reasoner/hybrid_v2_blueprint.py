"""Hybrid legal V2 blueprint types and interface contracts.

This module is intentionally additive. It provides a typed blueprint for the
next-generation IR/CNL/compiler/reasoner integration without changing existing
runtime behavior in the current engine.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import re
from typing import Any, Dict, List, Optional, Protocol, Tuple

from .kg_enrichment import (
    apply_kg_enrichment,
    build_entity_link_adapter,
    build_kg_drift_assessment,
    build_relation_enrichment_adapter,
)
from .optimizer_policy import (
    build_optimizer_acceptance_decision,
    build_optimizer_chain_plan,
)
from .prover_backends import create_default_prover_registry


class DeonticOpV2(str, Enum):
    """Deontic operators that wrap frame references."""

    O = "O"
    P = "P"
    F = "F"


class FrameKindV2(str, Enum):
    ACTION = "action"
    EVENT = "event"
    STATE = "state"


class TemporalRelationV2(str, Enum):
    BEFORE = "before"
    AFTER = "after"
    WITHIN = "within"
    BY = "by"
    DURING = "during"


@dataclass(frozen=True)
class CanonicalIdV2:
    namespace: str
    value: str

    def ref(self) -> str:
        return f"{self.namespace}:{self.value}"


@dataclass
class SourceRefV2:
    source_id: str
    sentence_text: str
    sentence_span: Optional[str] = None


@dataclass
class EntityV2:
    id: CanonicalIdV2
    type_name: str
    attrs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TemporalExprV2:
    kind: str
    start: Optional[str] = None
    end: Optional[str] = None
    duration: Optional[str] = None


@dataclass
class TemporalConstraintV2:
    id: CanonicalIdV2
    relation: TemporalRelationV2
    expr: TemporalExprV2
    anchor_ref: Optional[str] = None


@dataclass
class FrameV2:
    id: CanonicalIdV2
    kind: FrameKindV2
    predicate: str
    roles: Dict[str, str] = field(default_factory=dict)
    attrs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AtomV2:
    pred: str
    args: List[str] = field(default_factory=list)


@dataclass
class ConditionNodeV2:
    op: str
    atom: Optional[AtomV2] = None
    children: List["ConditionNodeV2"] = field(default_factory=list)
    var: Optional[str] = None
    var_type: Optional[str] = None


@dataclass
class NormV2:
    id: CanonicalIdV2
    op: DeonticOpV2
    target_frame_ref: str
    activation: ConditionNodeV2
    exceptions: List[ConditionNodeV2] = field(default_factory=list)
    temporal_ref: Optional[str] = None
    priority: int = 0
    source_ref: Optional[str] = None
    attrs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RuleV2:
    id: CanonicalIdV2
    antecedent: ConditionNodeV2
    consequent: AtomV2
    mode: str = "strict"
    source_ref: Optional[str] = None
    attrs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LegalIRV2:
    ir_version: str = "2.0"
    cnl_version: str = "2.0"
    jurisdiction: str = "default"
    entities: Dict[str, EntityV2] = field(default_factory=dict)
    frames: Dict[str, FrameV2] = field(default_factory=dict)
    temporals: Dict[str, TemporalConstraintV2] = field(default_factory=dict)
    norms: Dict[str, NormV2] = field(default_factory=dict)
    rules: Dict[str, RuleV2] = field(default_factory=dict)
    provenance: Dict[str, SourceRefV2] = field(default_factory=dict)


@dataclass
class ProofStepV2:
    step_id: str
    rule_id: str
    premises: List[str]
    conclusion: str
    ir_refs: List[str] = field(default_factory=list)
    source_refs: List[str] = field(default_factory=list)


@dataclass
class ProofObjectV2:
    proof_id: str
    root_conclusion: str
    steps: List[ProofStepV2] = field(default_factory=list)


_PROOF_STORE_V2: Dict[str, ProofObjectV2] = {}
SUPPORTED_V2_IR_VERSION = "2.0"
SUPPORTED_V2_CNL_VERSION = "2.0"


class OptimizerHook(Protocol):
    """Score-only optimizer hook. Must not change semantics without a drift check."""

    def optimize_ir(self, ir: LegalIRV2) -> Tuple[LegalIRV2, Dict[str, Any]]:
        ...


class KGHook(Protocol):
    """Additive enrichment hook. Must preserve canonical IDs."""

    def enrich_ir(self, ir: LegalIRV2) -> Tuple[LegalIRV2, Dict[str, Any]]:
        ...


class ProverHook(Protocol):
    """Backend theorem prover contract for DCEC/FOL obligations."""

    def prove(self, formulas: List[str], assumptions: Optional[List[str]] = None) -> Dict[str, Any]:
        ...


class DefaultOptimizerHookV2:
    """Default optimizer adapter backed by optimizer policy utilities."""

    def __init__(
        self,
        *,
        min_gain_threshold: float = 0.0,
        max_modality_regression: float = 0.0,
        default_modality_floor: float = 0.85,
    ) -> None:
        self.min_gain_threshold = float(min_gain_threshold)
        self.max_modality_regression = float(max_modality_regression)
        self.default_modality_floor = float(default_modality_floor)

    def _score_report(self, ir: LegalIRV2) -> Dict[str, Any]:
        frame_count = float(len(ir.frames) or 1)
        norm_count = float(len(ir.norms) or 1)
        temporal_count = float(len(ir.temporals) or 0)

        # Deterministic quality heuristic to feed acceptance policy.
        deontic_score = min(1.0, 0.80 + 0.03 * norm_count + 0.01 * temporal_count)
        fol_score = min(1.0, 0.79 + 0.02 * frame_count + 0.01 * temporal_count)
        global_score = round((deontic_score + fol_score) / 2.0, 4)
        return {
            "summary": {
                "semantic_similarity_final_decoded_mean": global_score,
                "semantic_similarity_by_modality": {
                    "deontic": round(deontic_score, 4),
                    "fol": round(fol_score, 4),
                },
                "semantic_similarity_floors": {
                    "deontic": self.default_modality_floor,
                    "fol": self.default_modality_floor,
                },
            }
        }

    def optimize_ir(self, ir: LegalIRV2) -> Tuple[LegalIRV2, Dict[str, Any]]:
        baseline = self._score_report(ir)
        candidate_ir = deepcopy(ir)

        # Safe no-op canonical mutation: enforce priority >= 0.
        for norm in candidate_ir.norms.values():
            norm.priority = max(0, int(norm.priority))

        candidate = self._score_report(candidate_ir)
        decision = build_optimizer_acceptance_decision(
            baseline,
            candidate,
            min_gain_threshold=self.min_gain_threshold,
            max_modality_regression=self.max_modality_regression,
            default_modality_floor=self.default_modality_floor,
        )
        chain = build_optimizer_chain_plan(decision)
        accepted = bool((decision.get("summary") or {}).get("accepted"))

        report: Dict[str, Any] = {
            "optimizer": "default_optimizer_hook_v2",
            "semantic_equivalence_assertion": True,
            "drift_score": 0.0,
            "acceptance_decision": decision,
            "chain_plan": chain,
        }
        return (candidate_ir if accepted else ir), report


class DefaultKGHookV2:
    """Default KG adapter backed by KG enrichment utilities."""

    def __init__(
        self,
        *,
        kg_namespace: str = "kgv2",
        confidence_floor: float = 0.0,
        max_relation_growth_factor: float = 3.0,
        max_relations_per_frame: int = 12,
    ) -> None:
        self.kg_namespace = kg_namespace
        self.confidence_floor = float(confidence_floor)
        self.max_relation_growth_factor = float(max_relation_growth_factor)
        self.max_relations_per_frame = int(max_relations_per_frame)

    def enrich_ir(self, ir: LegalIRV2) -> Tuple[LegalIRV2, Dict[str, Any]]:
        entity_adapter = build_entity_link_adapter(
            ir,
            kg_namespace=self.kg_namespace,
            confidence_floor=self.confidence_floor,
        )
        relation_adapter = build_relation_enrichment_adapter(
            ir,
            entity_adapter,
            confidence_floor=self.confidence_floor,
        )
        drift = build_kg_drift_assessment(
            baseline_relation_count=0,
            baseline_frame_count=max(1, len(ir.frames)),
            candidate_relation_adapter=relation_adapter,
            max_relation_growth_factor=self.max_relation_growth_factor,
            max_relations_per_frame=self.max_relations_per_frame,
        )
        accepted = bool((drift.get("summary") or {}).get("accepted"))
        if not accepted:
            return ir, {
                "kg": "default_kg_hook_v2",
                "accepted": False,
                "drift_assessment": drift,
            }

        enriched = apply_kg_enrichment(ir, entity_adapter, relation_adapter, enable_writes=True)
        return enriched["ir"], {
            "kg": "default_kg_hook_v2",
            "accepted": True,
            "entity_adapter": entity_adapter.get("summary"),
            "relation_adapter": relation_adapter.get("summary"),
            "drift_assessment": drift,
            "write_summary": (enriched.get("summary") or {}),
        }


class RegistryProverHookV2:
    """Default prover adapter backed by the prover backend registry."""

    def __init__(self, *, backend_id: str = "mock_smt") -> None:
        self.backend_id = backend_id
        self.registry = create_default_prover_registry()

    def prove(self, formulas: List[str], assumptions: Optional[List[str]] = None) -> Dict[str, Any]:
        backend = self.registry.get(self.backend_id)
        joined = " and ".join(formulas) if formulas else "true"
        result = backend.prove(joined, list(assumptions or []))
        return {
            "backend": result.backend,
            "status": result.status,
            "certificate": result.certificate,
            "theorem": result.theorem,
            "assumptions": result.assumptions,
        }


def _norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _norm_token(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "_", _norm_space(text).lower()).strip("_")
    return value or "x"


def _det_id(namespace: str, parts: List[str]) -> CanonicalIdV2:
    payload = "|".join(_norm_space(p).lower() for p in parts)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return CanonicalIdV2(namespace=namespace, value=digest)


def _cond_true() -> ConditionNodeV2:
    return ConditionNodeV2(op="atom", atom=AtomV2(pred="true", args=[]))


def _cond_from_phrase(prefix: str, phrase: str) -> ConditionNodeV2:
    clean = _norm_space(phrase)
    if not clean:
        return _cond_true()
    pred = f"{prefix}_{_norm_token(clean)}"
    return ConditionNodeV2(op="atom", atom=AtomV2(pred=pred, args=[]))


def _normalize_duration(raw: str) -> str:
    text = _norm_space(raw).lower()
    m = re.match(r"^(\d+)\s*(day|days|hour|hours|week|weeks)$", text)
    if not m:
        return raw
    amount = m.group(1)
    unit = m.group(2)
    if unit.startswith("day"):
        return f"P{amount}D"
    if unit.startswith("hour"):
        return f"PT{amount}H"
    return f"P{int(amount) * 7}D"


def _render_condition(cond: ConditionNodeV2) -> str:
    if cond.op == "atom" and cond.atom is not None:
        if cond.atom.args:
            return f"{cond.atom.pred}({', '.join(cond.atom.args)})"
        return cond.atom.pred
    if cond.op in {"and", "or"}:
        joiner = " and " if cond.op == "and" else " or "
        return "(" + joiner.join(_render_condition(c) for c in cond.children) + ")"
    if cond.op == "not" and cond.children:
        return f"not({_render_condition(cond.children[0])})"
    return "true"


def _eval_condition(cond: ConditionNodeV2, facts: Dict[str, bool]) -> bool:
    if cond.op == "atom" and cond.atom is not None:
        if cond.atom.pred == "true":
            return True
        return bool(facts.get(cond.atom.pred, False))
    if cond.op == "and":
        return all(_eval_condition(c, facts) for c in cond.children)
    if cond.op == "or":
        return any(_eval_condition(c, facts) for c in cond.children)
    if cond.op == "not" and cond.children:
        return not _eval_condition(cond.children[0], facts)
    return True


def _temporal_guard(norm: NormV2, ir: LegalIRV2) -> str:
    if norm.temporal_ref is None or norm.temporal_ref not in ir.temporals:
        return "true"
    temporal = ir.temporals[norm.temporal_ref]
    expr = temporal.expr
    if temporal.relation == TemporalRelationV2.WITHIN and expr.duration:
        return f"Within(t,{expr.duration})"
    if temporal.relation == TemporalRelationV2.BY and expr.start:
        return f"By(t,{expr.start})"
    if temporal.relation == TemporalRelationV2.AFTER and expr.start:
        return f"After(t,{expr.start})"
    if temporal.relation == TemporalRelationV2.BEFORE and expr.start:
        return f"Before(t,{expr.start})"
    if temporal.relation == TemporalRelationV2.DURING and expr.start and expr.end:
        return f"During(t,{expr.start},{expr.end})"
    return "true"


def _event_match(norm: NormV2, events: List[str]) -> bool:
    return norm.target_frame_ref in set(str(e) for e in events)


def _proof_id(root_conclusion: str, steps: List[ProofStepV2]) -> str:
    payload = root_conclusion + "|" + "|".join(f"{s.rule_id}:{s.conclusion}" for s in steps)
    return "pf2_" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def _collect_markers(text: str, markers: List[str]) -> List[str]:
    hits: List[str] = []
    for marker in markers:
        pattern = rf"\b{re.escape(marker)}\b"
        hit_count = len(re.findall(pattern, text, flags=re.IGNORECASE))
        hits.extend([marker] * hit_count)
    return hits


def _parse_confidence(
    *,
    modal: DeonticOpV2,
    has_temporal: bool,
    has_activation: bool,
    has_exception: bool,
    is_definition: bool,
) -> float:
    if is_definition:
        return 0.99

    score = 0.90
    if has_temporal:
        score += 0.03
    if has_activation:
        score += 0.03
    if has_exception:
        score += 0.02
    if modal == DeonticOpV2.F:
        score += 0.01
    return round(min(0.99, score), 3)


def _parse_alternatives(modal: DeonticOpV2) -> List[Dict[str, Any]]:
    ranked = [
        DeonticOpV2.O,
        DeonticOpV2.P,
        DeonticOpV2.F,
    ]
    if modal in ranked:
        ranked.remove(modal)
        ranked.insert(0, modal)
    return [{"operator": op.value, "rank": idx + 1} for idx, op in enumerate(ranked)]


def validate_ir_v2_contract(ir: LegalIRV2, *, strict: bool = True) -> Dict[str, Any]:
    """Validate runtime invariants for V2 IR/provenance contract enforcement."""
    if not isinstance(ir, LegalIRV2):
        raise ValueError("invalid_v2_ir_contract: value is not LegalIRV2")

    errors: List[str] = []
    warnings: List[str] = []

    if ir.ir_version != SUPPORTED_V2_IR_VERSION:
        errors.append(
            f"unsupported_ir_version:{ir.ir_version} expected:{SUPPORTED_V2_IR_VERSION}"
        )
    if ir.cnl_version != SUPPORTED_V2_CNL_VERSION:
        errors.append(
            f"unsupported_cnl_version:{ir.cnl_version} expected:{SUPPORTED_V2_CNL_VERSION}"
        )

    for key, source in ir.provenance.items():
        if source.source_id != key:
            errors.append(f"provenance_key_mismatch:{key}->{source.source_id}")

    for key, frame in ir.frames.items():
        if frame.id.ref() != key:
            errors.append(f"frame_id_key_mismatch:{key}->{frame.id.ref()}")

    for key, norm in ir.norms.items():
        if norm.id.ref() != key:
            errors.append(f"norm_id_key_mismatch:{key}->{norm.id.ref()}")
        if norm.target_frame_ref not in ir.frames:
            errors.append(f"unknown_target_frame_ref:{norm.id.ref()}->{norm.target_frame_ref}")
        if norm.temporal_ref and norm.temporal_ref not in ir.temporals:
            errors.append(f"unknown_temporal_ref:{norm.id.ref()}->{norm.temporal_ref}")

        if not norm.source_ref:
            msg = f"missing_source_ref:norm:{norm.id.ref()}"
            if strict:
                errors.append(msg)
            else:
                warnings.append(msg)
        elif norm.source_ref not in ir.provenance:
            errors.append(f"unknown_source_ref:norm:{norm.id.ref()}->{norm.source_ref}")

    for key, rule in ir.rules.items():
        if rule.id.ref() != key:
            errors.append(f"rule_id_key_mismatch:{key}->{rule.id.ref()}")
        if not rule.source_ref:
            msg = f"missing_source_ref:rule:{rule.id.ref()}"
            if strict:
                errors.append(msg)
            else:
                warnings.append(msg)
        elif rule.source_ref not in ir.provenance:
            errors.append(f"unknown_source_ref:rule:{rule.id.ref()}->{rule.source_ref}")

    if errors:
        raise ValueError("invalid_v2_ir_contract: " + "; ".join(errors))

    return {
        "ok": True,
        "strict": bool(strict),
        "warnings": warnings,
        "counts": {
            "provenance": len(ir.provenance),
            "frames": len(ir.frames),
            "norms": len(ir.norms),
            "rules": len(ir.rules),
        },
    }


def _split_modal(sentence: str) -> Tuple[str, DeonticOpV2, str]:
    low = sentence.lower()
    if " shall not " in low:
        i = low.index(" shall not ")
        return sentence[:i], DeonticOpV2.F, sentence[i + len(" shall not ") :]
    if " shall " in low:
        i = low.index(" shall ")
        return sentence[:i], DeonticOpV2.O, sentence[i + len(" shall ") :]
    if " may " in low:
        i = low.index(" may ")
        return sentence[:i], DeonticOpV2.P, sentence[i + len(" may ") :]
    raise ValueError("Unsupported CNL template: missing modal operator (shall/may/shall not)")


def _extract_suffix_clause(text: str, markers: List[str]) -> Tuple[str, Optional[str], Optional[str]]:
    low = text.lower()
    best_idx = None
    best_marker = None
    for marker in markers:
        needle = f" {marker} "
        idx = low.find(needle)
        if idx >= 0 and (best_idx is None or idx < best_idx):
            best_idx = idx
            best_marker = marker
    if best_idx is None or best_marker is None:
        return text, None, None
    head = _norm_space(text[:best_idx])
    tail = _norm_space(text[best_idx + len(best_marker) + 2 :])
    return head, best_marker, tail


def _extract_temporal(text: str) -> Tuple[str, Optional[TemporalRelationV2], Optional[TemporalExprV2]]:
    t = _norm_space(text)
    m = re.search(r"\bwithin\s+(\d+\s+(?:day|days|hour|hours|week|weeks))$", t, flags=re.IGNORECASE)
    if m:
        head = _norm_space(t[: m.start()])
        duration = _normalize_duration(m.group(1))
        return head, TemporalRelationV2.WITHIN, TemporalExprV2(kind="deadline", duration=duration)

    m = re.search(r"\bby\s+([0-9]{4}-[0-9]{2}-[0-9]{2})$", t, flags=re.IGNORECASE)
    if m:
        head = _norm_space(t[: m.start()])
        return head, TemporalRelationV2.BY, TemporalExprV2(kind="point", start=m.group(1))

    for rel, marker in [
        (TemporalRelationV2.AFTER, "after"),
        (TemporalRelationV2.BEFORE, "before"),
        (TemporalRelationV2.DURING, "during"),
    ]:
        m = re.search(rf"\b{marker}\s+(.+)$", t, flags=re.IGNORECASE)
        if m:
            head = _norm_space(t[: m.start()])
            return head, rel, TemporalExprV2(kind="point", start=_norm_space(m.group(1)))

    return t, None, None


def _parse_definition_sentence(clean: str, jurisdiction: str) -> Optional[LegalIRV2]:
    means_match = re.match(r"^(.+?)\s+means\s+(.+)$", clean, flags=re.IGNORECASE)
    if means_match:
        term = _norm_space(means_match.group(1))
        definition = _norm_space(means_match.group(2))
        ir = LegalIRV2(jurisdiction=jurisdiction)
        src_id = _det_id("src", [jurisdiction, clean])
        ir.provenance[src_id.ref()] = SourceRefV2(source_id=src_id.ref(), sentence_text=clean)
        rule_id = _det_id("rul", [jurisdiction, "means", term, definition])
        ir.rules[rule_id.ref()] = RuleV2(
            id=rule_id,
            antecedent=ConditionNodeV2(op="atom", atom=AtomV2(pred="defined_term", args=[term])),
            consequent=AtomV2(pred="definition_of", args=[term, definition]),
            mode="definition",
            source_ref=src_id.ref(),
            attrs={
                "parse_mode": "definition",
                "parse_confidence": _parse_confidence(
                    modal=DeonticOpV2.O,
                    has_temporal=False,
                    has_activation=False,
                    has_exception=False,
                    is_definition=True,
                ),
                "parse_alternatives": [{"operator": "definition", "rank": 1}],
                "ambiguity_flags": [],
            },
        )
        return ir

    includes_match = re.match(r"^(.+?)\s+includes\s+(.+)$", clean, flags=re.IGNORECASE)
    if includes_match:
        term = _norm_space(includes_match.group(1))
        members_raw = _norm_space(includes_match.group(2))
        members = [_norm_space(x) for x in re.split(r",|\band\b", members_raw, flags=re.IGNORECASE) if _norm_space(x)]
        ir = LegalIRV2(jurisdiction=jurisdiction)
        src_id = _det_id("src", [jurisdiction, clean])
        ir.provenance[src_id.ref()] = SourceRefV2(source_id=src_id.ref(), sentence_text=clean)
        for member in members:
            rule_id = _det_id("rul", [jurisdiction, "includes", term, member])
            ir.rules[rule_id.ref()] = RuleV2(
                id=rule_id,
                antecedent=ConditionNodeV2(op="atom", atom=AtomV2(pred="defined_term", args=[term])),
                consequent=AtomV2(pred="includes_member", args=[term, member]),
                mode="definition",
                source_ref=src_id.ref(),
                attrs={
                    "parse_mode": "definition",
                    "parse_confidence": _parse_confidence(
                        modal=DeonticOpV2.O,
                        has_temporal=False,
                        has_activation=False,
                        has_exception=False,
                        is_definition=True,
                    ),
                    "parse_alternatives": [{"operator": "definition", "rank": 1}],
                    "ambiguity_flags": [],
                },
            )
        return ir

    return None


def parse_cnl_to_ir_with_diagnostics(sentence: str, jurisdiction: str = "default") -> Tuple[LegalIRV2, Dict[str, Any]]:
    """Parse supported CNL templates into V2 IR.

    Supported templates:
    - <Agent> shall <Verb Phrase> [Temporal] [if/when ...] [unless/except ...]
    - <Agent> may <Verb Phrase> [Temporal] [if/when ...] [unless/except ...]
    - <Agent> shall not <Verb Phrase> [Temporal] [if/when ...] [unless/except ...]
    """
    clean = _norm_space(sentence).rstrip(".;")
    if not clean:
        raise ValueError("Empty CNL sentence")

    definition_ir = _parse_definition_sentence(clean, jurisdiction)
    if definition_ir is not None:
        diagnostics = {
            "parse_mode": "definition",
            "parse_confidence": 0.99,
            "parse_alternatives": [{"operator": "definition", "rank": 1}],
            "ambiguity_flags": [],
            "temporal_detected": False,
            "activation_marker": None,
            "exception_marker": None,
        }
        return definition_ir, diagnostics

    actor_text, modal, remainder = _split_modal(clean)
    actor_text = _norm_space(actor_text)
    remainder = _norm_space(remainder)

    activation_markers = _collect_markers(remainder, ["if", "when"])
    exception_markers = _collect_markers(remainder, ["unless", "except"])
    ambiguity_flags: List[str] = []
    if len(activation_markers) > 1:
        ambiguity_flags.append("multiple_activation_markers")
    if len(exception_markers) > 1:
        ambiguity_flags.append("multiple_exception_markers")
    if ambiguity_flags:
        raise ValueError("Ambiguous CNL parse: " + ",".join(ambiguity_flags))

    body, ex_marker, ex_tail = _extract_suffix_clause(remainder, ["unless", "except"])
    body, act_marker, act_tail = _extract_suffix_clause(body, ["if", "when"])
    body, rel, expr = _extract_temporal(body)

    parts = body.split(" ", 1)
    verb = _norm_space(parts[0])
    rest = _norm_space(parts[1] if len(parts) > 1 else "")

    patient_text = rest
    recipient_text = None
    m_to = re.search(r"\bto\s+(.+)$", rest, flags=re.IGNORECASE)
    if m_to:
        patient_text = _norm_space(rest[: m_to.start()])
        recipient_text = _norm_space(m_to.group(1))

    ir = LegalIRV2(jurisdiction=jurisdiction)
    src_id = _det_id("src", [jurisdiction, clean])
    ir.provenance[src_id.ref()] = SourceRefV2(source_id=src_id.ref(), sentence_text=clean)

    agent_id = _det_id("ent", [jurisdiction, "agent", actor_text])
    ir.entities[agent_id.ref()] = EntityV2(id=agent_id, type_name="Agent", attrs={"label": actor_text})

    roles: Dict[str, str] = {"agent": agent_id.ref(), "jurisdiction": jurisdiction}
    if patient_text:
        patient_id = _det_id("ent", [jurisdiction, "patient", patient_text])
        ir.entities[patient_id.ref()] = EntityV2(id=patient_id, type_name="Thing", attrs={"label": patient_text})
        roles["patient"] = patient_id.ref()
    if recipient_text:
        recipient_id = _det_id("ent", [jurisdiction, "recipient", recipient_text])
        ir.entities[recipient_id.ref()] = EntityV2(id=recipient_id, type_name="Party", attrs={"label": recipient_text})
        roles["recipient"] = recipient_id.ref()

    frame_id = _det_id("frm", [jurisdiction, "action", actor_text, verb, patient_text or "", recipient_text or ""])
    frame = FrameV2(id=frame_id, kind=FrameKindV2.ACTION, predicate=_norm_token(verb), roles=roles)
    ir.frames[frame_id.ref()] = frame

    temporal_ref = None
    if rel is not None and expr is not None:
        temporal_id = _det_id("tmp", [jurisdiction, rel.value, expr.kind, expr.start or "", expr.end or "", expr.duration or ""])
        ir.temporals[temporal_id.ref()] = TemporalConstraintV2(
            id=temporal_id,
            relation=rel,
            expr=expr,
        )
        temporal_ref = temporal_id.ref()

    activation = _cond_from_phrase(act_marker or "active", act_tail or "") if act_tail else _cond_true()
    exceptions: List[ConditionNodeV2] = []
    if ex_tail:
        exceptions.append(_cond_from_phrase(ex_marker or "except", ex_tail))

    parse_confidence = _parse_confidence(
        modal=modal,
        has_temporal=temporal_ref is not None,
        has_activation=bool(act_tail),
        has_exception=bool(ex_tail),
        is_definition=False,
    )
    parse_alternatives = _parse_alternatives(modal)
    diagnostics = {
        "parse_mode": "norm",
        "parse_confidence": parse_confidence,
        "parse_alternatives": parse_alternatives,
        "ambiguity_flags": [],
        "temporal_detected": temporal_ref is not None,
        "activation_marker": act_marker,
        "exception_marker": ex_marker,
    }

    norm_id = _det_id(
        "nrm",
        [
            jurisdiction,
            modal.value,
            frame_id.ref(),
            _render_condition(activation),
            ";".join(_render_condition(e) for e in exceptions),
            temporal_ref or "",
        ],
    )
    ir.norms[norm_id.ref()] = NormV2(
        id=norm_id,
        op=modal,
        target_frame_ref=frame_id.ref(),
        activation=activation,
        exceptions=exceptions,
        temporal_ref=temporal_ref,
        source_ref=src_id.ref(),
        attrs={
            "parse_confidence": parse_confidence,
            "parse_alternatives": parse_alternatives,
            "ambiguity_flags": [],
        },
    )
    return ir, diagnostics


def parse_cnl_to_ir(sentence: str, jurisdiction: str = "default") -> LegalIRV2:
    ir, _diagnostics = parse_cnl_to_ir_with_diagnostics(sentence, jurisdiction=jurisdiction)
    return ir


def normalize_ir(ir: LegalIRV2) -> LegalIRV2:
    """Canonicalize roles, durations, lexical forms, and IDs."""
    out = deepcopy(ir)

    role_map = {
        "subject": "agent",
        "object": "patient",
    }
    for frame in out.frames.values():
        frame.predicate = _norm_token(frame.predicate)
        normalized_roles: Dict[str, str] = {}
        for role, ref in frame.roles.items():
            normalized_roles[role_map.get(role, role)] = ref
        frame.roles = normalized_roles

    for temporal in out.temporals.values():
        if temporal.expr.duration:
            temporal.expr.duration = _normalize_duration(temporal.expr.duration)

    return out


def compile_ir_to_dcec(ir: LegalIRV2) -> List[str]:
    """Compile V2 IR into DCEC/Event Calculus-oriented formulas."""
    formulas: List[str] = []
    for frame in ir.frames.values():
        formulas.append(f"Frame({frame.id.ref()},{frame.kind.value},{frame.predicate})")

    for norm in ir.norms.values():
        activation = _render_condition(norm.activation)
        exceptions = " and ".join(_render_condition(e) for e in norm.exceptions) if norm.exceptions else "false"
        temporal_guard = _temporal_guard(norm, ir)
        formulas.append(
            "forall t ("
            f"{activation} and {temporal_guard} and not({exceptions})"
            f" -> {norm.op.value}({norm.target_frame_ref})"
            ")"
        )

    for rule in ir.rules.values():
        formulas.append(
            "forall x ("
            f"{_render_condition(rule.antecedent)} -> {rule.consequent.pred}({', '.join(rule.consequent.args)})"
            ")"
        )
    return formulas


def compile_ir_to_temporal_deontic_fol(ir: LegalIRV2) -> List[str]:
    """Compile V2 IR into temporal deontic FOL formulas."""
    formulas: List[str] = []
    for norm in ir.norms.values():
        activation = _render_condition(norm.activation)
        exceptions = " and ".join(_render_condition(e) for e in norm.exceptions) if norm.exceptions else "false"
        temporal_guard = _temporal_guard(norm, ir)
        formulas.append(
            "forall t ("
            f"{activation} and {temporal_guard} and not({exceptions})"
            f" -> {norm.op.value}({norm.target_frame_ref},t)"
            ")"
        )

    for rule in ir.rules.values():
        formulas.append(
            "forall x ("
            f"{_render_condition(rule.antecedent)} -> {rule.consequent.pred}({', '.join(rule.consequent.args)})"
            ")"
        )
    return formulas


def generate_cnl_from_ir(norm_ref: str, ir: LegalIRV2) -> str:
    """Deterministically regenerate controlled natural language for one norm."""
    norm = ir.norms[norm_ref]
    frame = ir.frames[norm.target_frame_ref]

    agent_label = ir.entities.get(frame.roles.get("agent", ""), EntityV2(id=CanonicalIdV2("ent", "x"), type_name="Agent", attrs={"label": "Agent"})).attrs.get("label", "Agent")
    patient_ref = frame.roles.get("patient")
    recipient_ref = frame.roles.get("recipient")
    patient_label = ir.entities.get(patient_ref, EntityV2(id=CanonicalIdV2("ent", "x"), type_name="Thing", attrs={"label": ""})).attrs.get("label", "") if patient_ref else ""
    recipient_label = ir.entities.get(recipient_ref, EntityV2(id=CanonicalIdV2("ent", "x"), type_name="Party", attrs={"label": ""})).attrs.get("label", "") if recipient_ref else ""

    modal = {
        DeonticOpV2.O: "shall",
        DeonticOpV2.P: "may",
        DeonticOpV2.F: "shall not",
    }[norm.op]
    phrase = f"{agent_label} {modal} {frame.predicate}"
    if patient_label:
        phrase += f" {patient_label}"
    if recipient_label:
        phrase += f" to {recipient_label}"

    if norm.temporal_ref and norm.temporal_ref in ir.temporals:
        temporal = ir.temporals[norm.temporal_ref]
        if temporal.relation == TemporalRelationV2.WITHIN and temporal.expr.duration:
            phrase += f" within {temporal.expr.duration}"
        elif temporal.relation == TemporalRelationV2.BY and temporal.expr.start:
            phrase += f" by {temporal.expr.start}"
        elif temporal.relation in {TemporalRelationV2.AFTER, TemporalRelationV2.BEFORE, TemporalRelationV2.DURING} and temporal.expr.start:
            phrase += f" {temporal.relation.value} {temporal.expr.start}"

    if norm.activation.atom is not None and norm.activation.atom.pred != "true":
        phrase += f" if {norm.activation.atom.pred}"
    if norm.exceptions:
        phrase += f" unless {_render_condition(norm.exceptions[0])}"

    return phrase.strip() + "."


def check_compliance(query: dict, time_context: dict) -> dict:
    """Reasoner API for compliance checking over V2 IR.

    Expected query keys:
    - ir: LegalIRV2
    - facts: dict[str, bool] (optional)
    - events: list[str] frame refs that happened (optional)
    """
    ir = query.get("ir")
    if not isinstance(ir, LegalIRV2):
        raise ValueError("query['ir'] must be a LegalIRV2 instance")
    validate_ir_v2_contract(ir, strict=True)

    facts = query.get("facts") or {}
    events = [str(e) for e in (query.get("events") or [])]

    steps: List[ProofStepV2] = []
    violations: List[Dict[str, Any]] = []
    step_idx = 1

    for norm in ir.norms.values():
        active = _eval_condition(norm.activation, facts)
        excepted = any(_eval_condition(ex, facts) for ex in norm.exceptions)
        in_force = active and not excepted

        steps.append(
            ProofStepV2(
                step_id=f"s{step_idx}",
                rule_id="NORM_IN_FORCE",
                premises=[],
                conclusion=f"in_force({norm.id.ref()})={str(in_force).lower()}",
                ir_refs=[norm.id.ref(), norm.target_frame_ref],
                source_refs=[norm.source_ref] if norm.source_ref else [],
            )
        )
        step_idx += 1

        if not in_force:
            continue

        happened = _event_match(norm, events)
        if norm.op == DeonticOpV2.O and not happened:
            violations.append({"norm_id": norm.id.ref(), "type": "omission", "frame_id": norm.target_frame_ref})
        if norm.op == DeonticOpV2.F and happened:
            violations.append({"norm_id": norm.id.ref(), "type": "forbidden_action", "frame_id": norm.target_frame_ref})

    status = "non_compliant" if violations else "compliant"
    root = f"compliance={status}"
    proof_id = _proof_id(root, steps)
    _PROOF_STORE_V2[proof_id] = ProofObjectV2(proof_id=proof_id, root_conclusion=root, steps=steps)

    return {
        "status": status,
        "violations": violations,
        "proof_id": proof_id,
        "checked_norms": sorted(ir.norms.keys()),
        "time_context": time_context,
    }


def find_violations(state: dict, time_range: Tuple[str, str]) -> dict:
    """Reasoner API for violation scanning over a time range."""
    ir = state.get("ir")
    if not isinstance(ir, LegalIRV2):
        raise ValueError("state['ir'] must be a LegalIRV2 instance")
    validate_ir_v2_contract(ir, strict=True)

    result = check_compliance({"ir": ir, "facts": state.get("facts", {}), "events": state.get("events", [])}, {"range": time_range})
    return {
        "time_range": time_range,
        "violations": result["violations"],
        "proof_id": result["proof_id"],
    }


def explain_proof(proof_id: str, format: str = "nl") -> dict:
    """Reasoner API for proof explanation output."""
    proof = _PROOF_STORE_V2.get(proof_id)
    if proof is None:
        raise KeyError(f"unknown proof_id: {proof_id}")

    if format == "nl":
        lines = [f"Proof {proof.proof_id}: {proof.root_conclusion}"]
        for step in proof.steps:
            lines.append(f"- {step.rule_id}: {step.conclusion}")
        return {
            "proof_id": proof.proof_id,
            "format": "nl",
            "text": "\n".join(lines),
            "steps": [s.__dict__ for s in proof.steps],
        }

    return {
        "proof_id": proof.proof_id,
        "format": "json",
        "root_conclusion": proof.root_conclusion,
        "steps": [s.__dict__ for s in proof.steps],
    }


def run_v2_pipeline(
    sentence: str,
    *,
    jurisdiction: str = "default",
    optimizer_hook: Optional[OptimizerHook] = None,
    kg_hook: Optional[KGHook] = None,
    prover_hook: Optional[ProverHook] = None,
    drift_threshold: float = 0.05,
    strict_contract: bool = True,
) -> Dict[str, Any]:
    """Run the V2 parse-normalize-compile pipeline with optional hooks.

    Hook policy:
    - optimizer and KG hooks are optional
    - optimizer output is rejected when drift_score > threshold or semantic assertion is false
    - prover is used to evaluate compiled formula bundles
    """
    ir = normalize_ir(parse_cnl_to_ir(sentence, jurisdiction=jurisdiction))
    contract_report = validate_ir_v2_contract(ir, strict=strict_contract)

    optimizer_report: Dict[str, Any] = {"applied": False}
    if optimizer_hook is not None:
        proposed_ir, report = optimizer_hook.optimize_ir(ir)
        drift = float(report.get("drift_score", 0.0))
        sem_ok = bool(report.get("semantic_equivalence_assertion", False))
        if drift <= drift_threshold and sem_ok:
            ir = proposed_ir
            optimizer_report = {"applied": True, **report}
        else:
            optimizer_report = {"applied": False, "rejected": True, **report}

    kg_report: Dict[str, Any] = {"applied": False}
    if kg_hook is not None:
        ir, report = kg_hook.enrich_ir(ir)
        kg_report = {"applied": True, **report}

    dcec = compile_ir_to_dcec(ir)
    tdfol = compile_ir_to_temporal_deontic_fol(ir)

    prover_report: Dict[str, Any] = {"applied": False}
    if prover_hook is not None:
        prover_report = {
            "applied": True,
            "dcec": prover_hook.prove(dcec),
            "tdfol": prover_hook.prove(tdfol),
        }

    return {
        "ir": ir,
        "contract_report": contract_report,
        "dcec": dcec,
        "tdfol": tdfol,
        "optimizer_report": optimizer_report,
        "kg_report": kg_report,
        "prover_report": prover_report,
    }


def run_v2_pipeline_with_defaults(
    sentence: str,
    *,
    jurisdiction: str = "default",
    enable_optimizer: bool = True,
    enable_kg: bool = True,
    enable_prover: bool = True,
    prover_backend_id: str = "mock_smt",
) -> Dict[str, Any]:
    """Run V2 pipeline using concrete adapters from existing reasoner modules."""
    optimizer = DefaultOptimizerHookV2() if enable_optimizer else None
    kg = DefaultKGHookV2() if enable_kg else None
    prover = RegistryProverHookV2(backend_id=prover_backend_id) if enable_prover else None
    return run_v2_pipeline(
        sentence,
        jurisdiction=jurisdiction,
        optimizer_hook=optimizer,
        kg_hook=kg,
        prover_hook=prover,
    )
