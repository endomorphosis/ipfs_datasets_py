"""Hybrid legal knowledge representation.

This module defines a frame-first intermediate representation (IR) that can be
compiled to DCEC-style formulas and temporal deontic FOL. It is intentionally
lightweight so it can be integrated into existing encoding/decoding pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


class DeonticOp(str, Enum):
    """Deontic modal operators."""

    O = "O"  # obligation
    P = "P"  # permission
    F = "F"  # prohibition


class FrameKind(str, Enum):
    """Core frame categories."""

    ACTION = "action"
    EVENT = "event"
    STATE = "state"


class TemporalRelation(str, Enum):
    """Temporal relation between target and anchor."""

    BEFORE = "before"
    AFTER = "after"
    DURING = "during"
    WITHIN = "within"
    UNTIL = "until"
    IMMEDIATELY_AFTER = "immediately_after"


@dataclass(frozen=True)
class CanonicalId:
    namespace: str
    value: str

    def ref(self) -> str:
        return f"{self.namespace}:{self.value}"


@dataclass
class Entity:
    id: CanonicalId
    type_name: str
    attrs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TemporalExpr:
    kind: str  # point | interval | deadline | window
    start: Optional[str] = None
    end: Optional[str] = None
    duration: Optional[str] = None
    anchor_ref: Optional[str] = None


@dataclass
class TemporalConstraint:
    id: CanonicalId
    expr: TemporalExpr
    relation: TemporalRelation
    calendar: str = "gregorian"
    tz: str = "UTC"
    attrs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BaseFrame:
    id: CanonicalId
    kind: FrameKind
    roles: Dict[str, str] = field(default_factory=dict)
    jurisdiction: Optional[str] = None
    source_span: Optional[str] = None
    attrs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionFrame(BaseFrame):
    verb: str = ""


@dataclass
class EventFrame(BaseFrame):
    event_type: str = ""


@dataclass
class StateFrame(BaseFrame):
    state_type: str = ""


@dataclass
class Atom:
    pred: str
    args: List[str] = field(default_factory=list)


@dataclass
class Condition:
    op: str  # atom | and | or | not | exists | forall
    atom: Optional[Atom] = None
    children: List["Condition"] = field(default_factory=list)
    var: Optional[str] = None
    var_type: Optional[str] = None

    @staticmethod
    def atom_pred(pred: str, *args: str) -> "Condition":
        return Condition(op="atom", atom=Atom(pred=pred, args=list(args)))


@dataclass
class Norm:
    id: CanonicalId
    op: DeonticOp
    target_frame_ref: str
    activation: Condition
    exceptions: List[Condition] = field(default_factory=list)
    temporal_ref: Optional[str] = None
    priority: int = 0
    jurisdiction: Optional[str] = None
    attrs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Rule:
    id: CanonicalId
    antecedent: Condition
    consequent: Atom
    mode: str = "strict"


@dataclass
class Query:
    id: CanonicalId
    goal: Condition
    at: Optional[str] = None


@dataclass
class LegalIR:
    version: str = "0.1"
    jurisdiction: str = "default"
    clock: str = "discrete"
    entities: Dict[str, Entity] = field(default_factory=dict)
    frames: Dict[str, BaseFrame] = field(default_factory=dict)
    temporal: Dict[str, TemporalConstraint] = field(default_factory=dict)
    norms: Dict[str, Norm] = field(default_factory=dict)
    rules: Dict[str, Rule] = field(default_factory=dict)
    queries: Dict[str, Query] = field(default_factory=dict)


def deterministic_id(namespace: str, parts: Sequence[str]) -> CanonicalId:
    """Build a deterministic canonical identifier from ordered semantic parts.

    Contract:
    - Inputs: `namespace` + ordered `parts` sequence.
    - Normalization per part: `str(part).strip().lower()`.
    - Join policy: normalized parts are concatenated with literal `"|"`.
    - Hash policy: SHA-1 digest over UTF-8 payload, truncated to first 16 hex chars.
    - Stability: output is stable for identical ordered inputs; reordering parts
      changes the resulting identifier by design.
    """
    payload = "|".join(str(p).strip().lower() for p in parts)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return CanonicalId(namespace=namespace, value=digest)


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _normalize_verb_lexical(text: str) -> str:
    """Canonicalize action verb text to a stable lexical surface."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", str(text or "").lower())
    return _norm_text(cleaned)


def _normalize_temporal_duration(value: Optional[str]) -> Optional[str]:
    """Normalize human-ish duration strings to compact ISO-8601 forms."""
    if value is None:
        return None
    raw = _norm_text(str(value)).lower()
    if not raw:
        return None

    # Already ISO-like duration.
    if re.match(r"^p\d+[ydm]$", raw) or re.match(r"^pt\d+h$", raw):
        return raw.upper()

    m = re.match(
        r"^(\d+)\s*(d|day|days|h|hr|hrs|hour|hours|m|mon|month|months|y|yr|year|years)$",
        raw,
    )
    if not m:
        return value

    amount = m.group(1)
    unit = m.group(2)
    if unit in {"d", "day", "days"}:
        return f"P{amount}D"
    if unit in {"h", "hr", "hrs", "hour", "hours"}:
        return f"PT{amount}H"
    if unit in {"m", "mon", "month", "months"}:
        return f"P{amount}M"
    return f"P{amount}Y"


def _normalize_jurisdiction_label(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    raw = _norm_text(str(value))
    if not raw:
        return None

    low = raw.lower()
    if low in {"federal", "us/federal", "usa/federal", "us", "united states"}:
        return "Federal"

    if low.startswith("state:"):
        state = _norm_text(raw.split(":", 1)[1]).upper()
        if re.match(r"^[A-Z]{2}$", state):
            return f"State:{state}"
        return f"State:{state}"

    # Accept compact two-letter state codes.
    if re.match(r"^[A-Za-z]{2}$", raw):
        return f"State:{raw.upper()}"

    if low.startswith("agency:"):
        agency_name = _norm_text(raw.split(":", 1)[1])
        return f"Agency:{agency_name}"

    return raw


def _rank_modal_candidates(text: str) -> List[Dict[str, Any]]:
    """Return ranked deontic parse candidates for a CNL sentence."""
    candidates: List[Dict[str, Any]] = []

    rules: List[Tuple[str, DeonticOp, float, str]] = [
        (r"\b(shall\s+not|must\s+not|prohibited)\b", DeonticOp.F, 0.97, "explicit prohibition token"),
        (r"\bshall\b", DeonticOp.O, 0.94, "explicit obligation token"),
        (r"\bmust\b", DeonticOp.O, 0.93, "strong obligation token"),
        (r"\bmay\b", DeonticOp.P, 0.90, "permission token"),
    ]
    for pattern, op, confidence, reason in rules:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            candidates.append(
                {
                    "operator": op.value,
                    "confidence": confidence,
                    "reason": reason,
                    "match": m.group(0),
                    "start": m.start(),
                }
            )

    # Higher confidence first; if tied, prefer earliest explicit token.
    candidates.sort(key=lambda c: (-float(c["confidence"]), int(c["start"])))
    return candidates


def _clean_sentence_terminal(text: str) -> str:
    return re.sub(r"[\s\.;:]+$", "", text).strip()


def _parse_definition_template(text: str, jurisdiction: str) -> Optional[LegalIR]:
    """Parse non-deontic CNL definition templates: `means` and `includes`."""
    cleaned = _clean_sentence_terminal(text)

    means_match = re.match(r"^(.+?)\s+means\s+(.+)$", cleaned, re.IGNORECASE)
    if means_match:
        term = _norm_text(means_match.group(1))
        definition = _norm_text(means_match.group(2))
        if term and definition:
            ir = LegalIR(jurisdiction=jurisdiction)
            term_id = deterministic_id("ent", ["defined_term", term])
            ir.entities[term_id.ref()] = Entity(
                id=term_id,
                type_name="DefinedTerm",
                attrs={"label": term},
            )
            rule_id = deterministic_id("rul", ["means", term, definition, jurisdiction])
            ir.rules[rule_id.ref()] = Rule(
                id=rule_id,
                antecedent=Condition.atom_pred("defined_term", term),
                consequent=Atom(pred="definition_of", args=[term, definition]),
                mode="definition",
            )
            return ir

    includes_match = re.match(r"^(.+?)\s+includes\s+(.+)$", cleaned, re.IGNORECASE)
    if includes_match:
        term = _norm_text(includes_match.group(1))
        remainder = _norm_text(includes_match.group(2))
        if term and remainder:
            ir = LegalIR(jurisdiction=jurisdiction)
            term_id = deterministic_id("ent", ["defined_term", term])
            ir.entities[term_id.ref()] = Entity(
                id=term_id,
                type_name="DefinedTerm",
                attrs={"label": term},
            )

            parts = [_norm_text(p) for p in re.split(r",|\band\b", remainder, flags=re.IGNORECASE)]
            members = [p for p in parts if p]
            for member in members:
                member_id = deterministic_id("ent", ["included_member", term, member])
                ir.entities[member_id.ref()] = Entity(
                    id=member_id,
                    type_name="IncludedMember",
                    attrs={"label": member, "term": term},
                )
                rule_id = deterministic_id("rul", ["includes", term, member, jurisdiction])
                ir.rules[rule_id.ref()] = Rule(
                    id=rule_id,
                    antecedent=Condition.atom_pred("defined_term", term),
                    consequent=Atom(pred="includes_member", args=[term, member]),
                    mode="definition",
                )
            if members:
                return ir

    return None


def parse_cnl_sentence(
    sentence: str,
    jurisdiction: str = "default",
    *,
    fail_on_ambiguity: bool = False,
) -> LegalIR:
    """Rule-based CNL parser skeleton: NL -> one-norm IR.

    Supported patterns:
    - "X means Y" (definition template)
    - "X includes A, B, and C" (definition template)
    - "X shall ..."
    - "X may ..."
    - "X shall not ..." / "X must not ..."
    - temporal tails: "within N days/hours", "by ..."
    - activation tails: "if ...", "when ..."
    - exceptions: "unless ...", "except as to ..."

    Args:
    - fail_on_ambiguity: when True, reject CNL with conflicting modal intent
      or multiple competing activation/exception markers.
    """
    text = _norm_text(sentence)

    definition_ir = _parse_definition_template(text, jurisdiction)
    if definition_ir is not None:
        return definition_ir

    ir = LegalIR(jurisdiction=jurisdiction)

    ranked_candidates = _rank_modal_candidates(text)
    if not ranked_candidates:
        raise ValueError("Unable to detect modality token in CNL sentence.")
    selected = ranked_candidates[0]
    op = DeonticOp(str(selected["operator"]))

    # Find the token span of the selected top candidate for subject/action split.
    m = re.search(re.escape(str(selected["match"])), text, re.IGNORECASE)
    if not m:
        raise ValueError("Unable to locate selected modality token in CNL sentence.")

    ambiguity_flags: List[str] = []
    unique_ops = {str(c["operator"]) for c in ranked_candidates}
    if len(unique_ops) > 1:
        ambiguity_flags.append("multiple_modal_operators")

    agent_text = _norm_text(text[: m.start()].strip(" ,;:"))
    action_text = _norm_text(text[m.end() :].strip(" ,;:"))

    # Carve out exception/activation tails without losing source semantics.
    exception_text = None
    exception_hits = 0
    for patt in (r"\bexcept\s+as\s+to\b", r"\bunless\b"):
        em = re.search(patt, action_text, re.IGNORECASE)
        if em:
            exception_hits += 1
            exception_text = _norm_text(action_text[em.start() :])
            action_text = _norm_text(action_text[: em.start()])
            break
    # Count possible competing markers in the original sentence.
    exception_hits += len(re.findall(r"\b(unless|except\s+as\s+to)\b", text, re.IGNORECASE)) - (1 if exception_text else 0)
    if exception_hits > 1:
        ambiguity_flags.append("multiple_exception_markers")

    activation_text = None
    activation_hits = len(re.findall(r"\b(if|when)\b", text, re.IGNORECASE))
    for patt in (r"\bif\b", r"\bwhen\b"):
        cm = re.search(patt, action_text, re.IGNORECASE)
        if cm:
            activation_text = _norm_text(action_text[cm.start() :])
            action_text = _norm_text(action_text[: cm.start()])
            break
    if activation_hits > 1:
        ambiguity_flags.append("multiple_activation_markers")

    if fail_on_ambiguity and ambiguity_flags:
        raise ValueError(
            "Ambiguous CNL parse: " + ", ".join(ambiguity_flags)
        )

    temporal_ref = None
    t_match = re.search(r"\bwithin\s+(\d+)\s+(day|days|hour|hours|month|months|year|years)\b", action_text, re.IGNORECASE)
    if t_match:
        duration = f"{t_match.group(1)}{t_match.group(2).lower().rstrip('s')}"
        tc_id = deterministic_id("tmp", [duration, "window", action_text])
        tc = TemporalConstraint(
            id=tc_id,
            expr=TemporalExpr(kind="window", duration=duration, anchor_ref="T0"),
            relation=TemporalRelation.WITHIN,
        )
        ir.temporal[tc.id.ref()] = tc
        temporal_ref = tc.id.ref()
        action_text = _norm_text(action_text[: t_match.start()])

    agent_id = deterministic_id("ent", [agent_text or "anonymous_agent"])
    ir.entities[agent_id.ref()] = Entity(id=agent_id, type_name="LegalActor", attrs={"label": agent_text})

    frame_id = deterministic_id("frm", [agent_text, action_text, jurisdiction])
    frame = ActionFrame(
        id=frame_id,
        kind=FrameKind.ACTION,
        verb=action_text.split(" ")[0] if action_text else "act",
        roles={"agent": agent_id.ref()},
        jurisdiction=jurisdiction,
        source_span=text,
        attrs={
            "action_text": action_text,
            "parse_confidence": float(selected["confidence"]),
            "parse_alternatives": [
                {
                    "operator": str(c["operator"]),
                    "confidence": float(c["confidence"]),
                    "reason": str(c["reason"]),
                }
                for c in ranked_candidates[:3]
            ],
            "ambiguity_flags": list(ambiguity_flags),
        },
    )
    ir.frames[frame.id.ref()] = frame

    activation = Condition.atom_pred("true")
    if activation_text:
        activation = Condition.atom_pred("activation_clause", activation_text)

    exceptions: List[Condition] = []
    if exception_text:
        exceptions.append(Condition.atom_pred("exception_clause", exception_text))

    norm_id = deterministic_id("nrm", [op.value, frame.id.ref(), activation_text or "", exception_text or "", temporal_ref or ""])
    norm = Norm(
        id=norm_id,
        op=op,
        target_frame_ref=frame.id.ref(),
        activation=activation,
        exceptions=exceptions,
        temporal_ref=temporal_ref,
        jurisdiction=jurisdiction,
        attrs={
            "parse_confidence": float(selected["confidence"]),
            "parse_alternatives": [
                {
                    "operator": str(c["operator"]),
                    "confidence": float(c["confidence"]),
                    "reason": str(c["reason"]),
                }
                for c in ranked_candidates[:3]
            ],
            "ambiguity_flags": list(ambiguity_flags),
        },
    )
    ir.norms[norm.id.ref()] = norm
    return ir


def normalize_ir(ir: LegalIR) -> LegalIR:
    """Canonicalize role names, lexical forms, and deterministic IDs."""
    ir.jurisdiction = _normalize_jurisdiction_label(ir.jurisdiction) or ir.jurisdiction

    role_map = {
        "subject": "agent",
        "actor": "agent",
        "performer": "agent",
        "object": "patient",
        "target": "patient",
        "recipient": "beneficiary",
        "beneficiary": "beneficiary",
        "owner": "principal",
        "principal": "principal",
    }
    for frame in ir.frames.values():
        frame.jurisdiction = _normalize_jurisdiction_label(frame.jurisdiction) or frame.jurisdiction
        normalized_roles: Dict[str, str] = {}
        for role, ref in frame.roles.items():
            role_key = _norm_text(str(role).lower())
            canonical_role = role_map.get(role_key, role_key)
            normalized_roles[canonical_role] = ref
        frame.roles = normalized_roles
        if isinstance(frame, ActionFrame):
            frame.verb = _normalize_verb_lexical(frame.verb)
            if "action_text" in frame.attrs:
                frame.attrs["action_text"] = _normalize_verb_lexical(str(frame.attrs.get("action_text") or ""))

    for tmp in ir.temporal.values():
        tmp.expr.duration = _normalize_temporal_duration(tmp.expr.duration)

    for norm in ir.norms.values():
        norm.jurisdiction = _normalize_jurisdiction_label(norm.jurisdiction) or norm.jurisdiction

    return ir


def _cond_to_dcec(cond: Condition) -> str:
    if cond.op == "atom" and cond.atom:
        if cond.atom.pred == "true" and not cond.atom.args:
            return "true"
        return f"{cond.atom.pred}({', '.join(cond.atom.args)})"
    if cond.op in {"and", "or"}:
        sep = ", " if cond.op == "and" else " ; "
        return "(" + sep.join(_cond_to_dcec(c) for c in cond.children) + ")"
    if cond.op == "not" and cond.children:
        return f"not({_cond_to_dcec(cond.children[0])})"
    return "true"


def _cond_to_fol(cond: Condition) -> str:
    if cond.op == "atom" and cond.atom:
        if cond.atom.pred == "true" and not cond.atom.args:
            return "true"
        return f"{cond.atom.pred}({', '.join(cond.atom.args)})"
    if cond.op in {"and", "or"}:
        sep = " and " if cond.op == "and" else " or "
        return "(" + sep.join(_cond_to_fol(c) for c in cond.children) + ")"
    if cond.op == "not" and cond.children:
        return f"not ({_cond_to_fol(cond.children[0])})"
    return "true"


def compile_to_dcec(ir: LegalIR) -> List[str]:
    """Compile IR to DCEC/EC-flavored formulas with deontic wrappers over frames."""
    formulas: List[str] = []
    modal_name = {DeonticOp.O: "Obligated", DeonticOp.P: "Permitted", DeonticOp.F: "Forbidden"}

    for norm in ir.norms.values():
        act = _cond_to_dcec(norm.activation)
        exc = " and ".join(_cond_to_dcec(e) for e in norm.exceptions) if norm.exceptions else "false"
        t_guard = "true"
        if norm.temporal_ref and norm.temporal_ref in ir.temporal:
            tc = ir.temporal[norm.temporal_ref]
            t_guard = f"TemporalGuard({tc.id.ref()}, t)"
        formulas.append(
            f"HoldsAt({modal_name[norm.op]}({norm.target_frame_ref}), t) :- {act}, not({exc}), {t_guard}."
        )
    return formulas


def _canonical_action_predicate(frame: BaseFrame, norm: Norm) -> str:
    """Return a deterministic symbolic predicate name for action frames.

    This intentionally avoids reusing lexical action text to reduce
    source-token carry-through into compiled formulas.
    """
    action_text = ""
    if isinstance(frame, ActionFrame):
        action_text = str(frame.attrs.get("action_text") or frame.verb or "")
    payload = "|".join(
        [
            str(frame.id.ref()),
            str(norm.id.ref()),
            str(frame.kind.value),
            str(norm.op.value),
            action_text.strip().lower(),
        ]
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]
    return f"Act_{digest}"


def compile_to_temporal_deontic_fol(ir: LegalIR, *, canonical_predicates: bool = True) -> List[str]:
    """Compile IR to temporal deontic FOL formulas."""
    formulas: List[str] = []
    for norm in ir.norms.values():
        frame = ir.frames[norm.target_frame_ref]
        if canonical_predicates:
            action_name = _canonical_action_predicate(frame, norm)
        else:
            action_name = frame.attrs.get("action_text") if isinstance(frame, ActionFrame) else frame.id.value
            action_name = re.sub(r"[^A-Za-z0-9]+", "_", str(action_name)).strip("_") or "Action"
        pred = f"{action_name}({', '.join(frame.roles.values())}, t)"
        act = _cond_to_fol(norm.activation)
        exc = " or ".join(_cond_to_fol(e) for e in norm.exceptions) if norm.exceptions else "false"
        t_guard = "true"
        if norm.temporal_ref and norm.temporal_ref in ir.temporal:
            t_guard = f"TemporalGuard({norm.temporal_ref}, t)"
        formulas.append(f"forall t. ({act} and {t_guard} and not ({exc})) -> {norm.op.value}_t({pred}).")
    return formulas


def _provenance_source_for_norm(ir: LegalIR, norm: Norm) -> List[str]:
    """Collect stable source snippets that explain one compiled formula."""
    source_parts: List[str] = []
    frame = ir.frames.get(norm.target_frame_ref)
    if frame is not None:
        if frame.source_span:
            source_parts.append(_norm_text(frame.source_span))
        action_text = str(frame.attrs.get("action_text") or "").strip()
        if action_text:
            source_parts.append(_norm_text(action_text))
        for ent_ref in frame.roles.values():
            ent = ir.entities.get(ent_ref)
            if ent is not None:
                label = str(ent.attrs.get("label") or "").strip()
                if label:
                    source_parts.append(_norm_text(label))

    if norm.activation.atom and norm.activation.atom.args:
        source_parts.extend(_norm_text(a) for a in norm.activation.atom.args if str(a).strip())

    for exc in norm.exceptions:
        if exc.atom and exc.atom.args:
            source_parts.extend(_norm_text(a) for a in exc.atom.args if str(a).strip())

    deduped: List[str] = []
    for part in source_parts:
        if part and part not in deduped:
            deduped.append(part)
    return deduped


def compile_with_provenance_index(
    ir: LegalIR,
    *,
    backend: str = "dcec",
    canonical_predicates: bool = True,
) -> Dict[str, Any]:
    """Compile formulas and emit deterministic provenance index entries.

    Output shape:
    - `formulas`: ordered list of compiled formulas.
    - `provenance_index`: mapping from deterministic `formula_ref` to metadata.
      Each entry contains nested `ir_refs` with `source` snippets:
      `formula_ref -> ir_refs -> source`.
    """
    backend_key = str(backend).strip().lower()
    if backend_key == "dcec":
        formulas = compile_to_dcec(ir)
    elif backend_key in {"tdfol", "temporal_deontic_fol"}:
        formulas = compile_to_temporal_deontic_fol(ir, canonical_predicates=canonical_predicates)
        backend_key = "tdfol"
    else:
        raise ValueError(f"Unsupported backend: {backend}")

    provenance_index: Dict[str, Any] = {}
    norms = list(ir.norms.values())
    for idx, formula in enumerate(formulas):
        if idx >= len(norms):
            break
        norm = norms[idx]
        frame = ir.frames.get(norm.target_frame_ref)
        entity_refs = sorted(list(frame.roles.values())) if frame is not None else []
        formula_ref = deterministic_id("fml", [backend_key, norm.id.ref(), formula]).ref()
        provenance_index[formula_ref] = {
            "formula": formula,
            "backend": backend_key,
            "ir_refs": {
                "norm_ref": norm.id.ref(),
                "frame_ref": norm.target_frame_ref,
                "temporal_ref": norm.temporal_ref,
                "entity_refs": entity_refs,
                "source": _provenance_source_for_norm(ir, norm),
            },
        }

    return {
        "backend": backend_key,
        "formulas": formulas,
        "provenance_index": provenance_index,
    }


def compile_differential_report(
    ir: LegalIR,
    *,
    tdfol_canonical_predicates: bool = True,
    dcec_formulas: Optional[List[str]] = None,
    tdfol_formulas: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Compare DCEC and TDFOL compiler outputs and report inconsistencies.

    The report is deterministic for fixed IR/compiler outputs and intended for
    parity diagnostics during compiler evolution.
    """
    dcec = list(dcec_formulas) if dcec_formulas is not None else compile_to_dcec(ir)
    tdfol = (
        list(tdfol_formulas)
        if tdfol_formulas is not None
        else compile_to_temporal_deontic_fol(ir, canonical_predicates=tdfol_canonical_predicates)
    )

    modal_to_dcec = {
        DeonticOp.O: "Obligated(",
        DeonticOp.P: "Permitted(",
        DeonticOp.F: "Forbidden(",
    }
    modal_to_tdfol = {
        DeonticOp.O: "-> O_t(",
        DeonticOp.P: "-> P_t(",
        DeonticOp.F: "-> F_t(",
    }

    entries: List[Dict[str, Any]] = []
    inconsistencies: List[Dict[str, Any]] = []

    norms = list(ir.norms.values())
    paired_count = min(len(norms), len(dcec), len(tdfol))
    for idx in range(paired_count):
        norm = norms[idx]
        d_formula = dcec[idx]
        t_formula = tdfol[idx]

        modal_consistent = (modal_to_dcec[norm.op] in d_formula) and (modal_to_tdfol[norm.op] in t_formula)
        temporal_expected = bool(norm.temporal_ref)
        temporal_consistent = ("TemporalGuard(" in d_formula) == temporal_expected and ("TemporalGuard(" in t_formula) == temporal_expected

        activation_expected = norm.activation.op == "atom" and bool(norm.activation.atom) and norm.activation.atom.pred == "activation_clause"
        activation_consistent = ("activation_clause(" in d_formula) == activation_expected and ("activation_clause(" in t_formula) == activation_expected

        entry = {
            "formula_ref": deterministic_id("cmp", [norm.id.ref(), d_formula, t_formula]).ref(),
            "norm_ref": norm.id.ref(),
            "dcec_formula": d_formula,
            "tdfol_formula": t_formula,
            "checks": {
                "modal_consistent": modal_consistent,
                "temporal_guard_consistent": temporal_consistent,
                "activation_consistent": activation_consistent,
            },
        }
        entries.append(entry)

        if not (modal_consistent and temporal_consistent and activation_consistent):
            inconsistencies.append(entry)

    count_mismatch = len(dcec) != len(tdfol) or len(dcec) != len(norms)
    if count_mismatch:
        inconsistencies.append(
            {
                "type": "count_mismatch",
                "expected_norm_count": len(norms),
                "dcec_count": len(dcec),
                "tdfol_count": len(tdfol),
            }
        )

    return {
        "summary": {
            "norm_count": len(norms),
            "dcec_count": len(dcec),
            "tdfol_count": len(tdfol),
            "paired_count": paired_count,
            "inconsistency_count": len(inconsistencies),
            "has_inconsistencies": bool(inconsistencies),
        },
        "entries": entries,
        "inconsistencies": inconsistencies,
    }


def generate_cnl(norm: Norm, ir: LegalIR) -> str:
    """Deterministic CNL back-translation for one norm."""
    frame = ir.frames[norm.target_frame_ref]
    agent = frame.roles.get("agent", "ent:unknown")
    agent_label = ir.entities.get(agent).attrs.get("label", agent) if agent in ir.entities else agent
    action_text = frame.attrs.get("action_text", getattr(frame, "verb", "act"))

    modal = {
        DeonticOp.O: "shall",
        DeonticOp.P: "may",
        DeonticOp.F: "shall not",
    }[norm.op]

    parts = [f"Under {norm.jurisdiction or ir.jurisdiction}, {agent_label} {modal} {action_text}"]
    if norm.temporal_ref and norm.temporal_ref in ir.temporal:
        tc = ir.temporal[norm.temporal_ref]
        if tc.expr.duration:
            parts.append(f"within {tc.expr.duration}")

    if norm.activation.op == "atom" and norm.activation.atom and norm.activation.atom.pred == "activation_clause":
        parts.append(norm.activation.atom.args[0])

    if norm.exceptions:
        ex = norm.exceptions[0]
        if ex.atom and ex.atom.args:
            parts.append(ex.atom.args[0])

    sentence = " ".join(part.strip() for part in parts if part).strip()
    sentence = re.sub(r"\s+", " ", sentence)
    if sentence and sentence[-1] not in ".!?":
        sentence += "."
    return sentence


def ir_semantic_roundtrip_score(source_text: str, decoded_text: str, model_name: str = "all-MiniLM-L6-v2") -> float:
    """Cosine similarity helper for roundtrip fidelity checks.

    Uses sentence-transformers if available; raises ImportError otherwise.
    """
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np
    except ImportError as exc:
        raise ImportError(
            "sentence-transformers is required for ir_semantic_roundtrip_score"
        ) from exc

    model = SentenceTransformer(model_name)
    emb = model.encode([source_text, decoded_text], normalize_embeddings=True)
    return float(np.dot(emb[0], emb[1]))


def to_json(ir: LegalIR) -> str:
    """Debug serializer for IR snapshots."""
    return json.dumps(ir, default=lambda o: o.__dict__, indent=2, sort_keys=True)
