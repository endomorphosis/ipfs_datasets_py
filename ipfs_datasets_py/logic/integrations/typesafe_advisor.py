"""Advisory TypeSafe lint for autoformalization outputs.

TypeSafe may score whether a produced formula captures a source clause.
It cannot rewrite IR, drop formulas, admit proofs, or replace FOLConverter /
hammer / kernel. No API key → no HTTP; converters keep their existing path.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

REMOTE_BLOCKED_PRIVACY = frozenset({"local_only", "forbidden_external"})
ADVISOR_SCHEMA = "ipfs_datasets_py/logic/typesafe-formula-lint@1"
TRAP_SMT_MARKERS = (
    "FloatingPoint",
    "BitVec",
    "fp.add",
    "fp.eq",
    "bvslt",
    "bvmul",
    "QF_FP",
    "QF_BV",
)
_LAST = threading.local()
_LAST_SMT = threading.local()
_LAST_VERIFY = threading.local()
VERIFY_FIRE = 0.7
COARSE_CONFIDENCE = 0.9
LOGIC_FAMILIES: tuple[str, ...] = (
    "first_order",
    "deontic",
    "temporal",
    "program",
    "authorization",
)
_VIEW_TO_FAMILY = {
    "fol": "first_order",
    "deontic": "deontic",
    "tdfol": "temporal",
    "intent": "first_order",
    "ui_ux": "deontic",
    "security_ir": "authorization",
}
_LAST_FAMILY = threading.local()
_LAST_ROUTE = threading.local()
_LAST_ACTION = threading.local()
FAMILY_CHILDREN: dict[str, tuple[str, ...]] = {
    "deontic": ("obligation", "permission", "prohibition"),
}


@dataclass(frozen=True)
class AdvisoryReceipt:
    schema: str = ADVISOR_SCHEMA
    accepted_as_authority: bool = False
    rewrites_ir: bool = False
    drops_formula: bool = False
    view_id: str = ""
    captures: float = 0.0
    modality_matches: float = 0.0
    confidence: float = 0.0
    reason_codes: tuple[str, ...] = ()
    privacy_blocked: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "accepted_as_authority", False)
        object.__setattr__(self, "rewrites_ir", False)
        object.__setattr__(self, "drops_formula", False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "accepted_as_authority": False,
            "rewrites_ir": False,
            "drops_formula": False,
            "view_id": self.view_id,
            "captures": round(float(self.captures), 4),
            "modality_matches": round(float(self.modality_matches), 4),
            "confidence": round(float(self.confidence), 4),
            "reason_codes": list(self.reason_codes),
            "privacy_blocked": self.privacy_blocked,
        }


def typesafe_permitted(
    *,
    privacy_class: str = "repository_private",
    remote_disclosure_permitted: bool = True,
    environ: Optional[Mapping[str, str]] = None,
) -> bool:
    privacy = str(privacy_class or "").strip().casefold()
    if privacy in REMOTE_BLOCKED_PRIVACY:
        return False
    if not remote_disclosure_permitted:
        return False
    try:
        from ipfs_accelerate_py.typesafe_inference import typesafe_configured

        return bool(typesafe_configured(environ=environ))
    except Exception:
        env = environ if environ is not None else os.environ
        return bool(str(env.get("TYPESAFE_API_KEY") or "").strip())


def last_formula_lint() -> dict[str, Any]:
    value = getattr(_LAST, "value", None)
    return dict(value) if isinstance(value, Mapping) else {}


_LAST_RANK = threading.local()
_LAST_EVIDENCE = threading.local()
EVIDENCE_THRESHOLDS = {
    "injection_max": 0.70,
    "contradicts_min": 0.70,
    "relevant_min": 0.45,
    "evidence_min": 0.55,
}


_LAST_CROSS_VIEW = threading.local()


def last_cross_view_lint() -> dict[str, Any]:
    value = getattr(_LAST_CROSS_VIEW, "value", None)
    return dict(value) if isinstance(value, Mapping) else {}


def lint_cross_view_formulas(
    dcec_formulas: Sequence[str] = (),
    tdfol_formulas: Sequence[str] = (),
    *,
    privacy_class: str = "repository_private",
    remote_disclosure_permitted: bool = True,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Advisory noul: do DCEC and TDFOL views mention the same actors?

    Never satisfies compiler parity. Never rewrites formulas.
    """

    payload = {
        "accepted_as_authority": False,
        "satisfies_parity": False,
        "rewrites_ir": False,
        "same_actors": 0.0,
        "same_modality": 0.0,
        "same_temporal": 0.0,
        "link_score": 0.0,
        "outcome": "different",
        "curator": False,
        "reason_codes": ["privacy_or_unconfigured"],
    }
    if not typesafe_permitted(
        privacy_class=privacy_class,
        remote_disclosure_permitted=remote_disclosure_permitted,
    ):
        _LAST_CROSS_VIEW.value = dict(payload)
        return payload
    from ipfs_accelerate_py.typesafe_inference import Noul, Score, system_one

    dcec = [str(item)[:240] for item in dcec_formulas if str(item).strip()][:4]
    tdfol = [str(item)[:240] for item in tdfol_formulas if str(item).strip()][:4]
    levels = (
        "They describe two different obligations.",
        "They describe closely related obligations that may or may not be the same one.",
        "They describe one and the same obligation.",
    )
    outcomes = ("different", "related", "same")
    try:
        result = system_one(
            {"dcec": dcec, "tdfol": tdfol},
            {
                "link_state": Score(
                    instructions={
                        "question": "How do the DCEC and TDFOL views relate as obligations?",
                        "compare": ["`dcec`", "`tdfol`"],
                    },
                    criteria=list(levels),
                ),
                "same_actors": Noul(
                    instructions={
                        "question": (
                            "Do `dcec` and `tdfol` mention the same obligation actors?"
                        ),
                        "compare": ["`dcec`", "`tdfol`"],
                    },
                ),
                "same_modality": Noul(
                    instructions={
                        "question": (
                            "Do `dcec` and `tdfol` use the same deontic modality?"
                        ),
                        "compare": ["`dcec`", "`tdfol`"],
                    },
                ),
                "same_temporal": Noul(
                    instructions={
                        "question": (
                            "Do `dcec` and `tdfol` describe the same temporal window?"
                        ),
                        "compare": ["`dcec`", "`tdfol`"],
                    },
                ),
            },
            timeout=timeout,
        )
    except Exception:
        payload["reason_codes"] = ["typesafe_error_fail_open"]
        _LAST_CROSS_VIEW.value = dict(payload)
        return payload
    nouls = getattr(result, "nouls", None) or {}
    scores = getattr(result, "scores", None) or {}
    payload["same_actors"] = round(
        float(getattr(nouls.get("same_actors"), "noul", 0.0) or 0.0), 4
    )
    payload["same_modality"] = round(
        float(getattr(nouls.get("same_modality"), "noul", 0.0) or 0.0), 4
    )
    payload["same_temporal"] = round(
        float(getattr(nouls.get("same_temporal"), "noul", 0.0) or 0.0), 4
    )
    link = float(getattr(scores.get("link_state"), "score", 0.0) or 0.0)
    payload["link_score"] = round(link, 4)
    index = min(int(link + 0.5), 2)
    payload["outcome"] = outcomes[index]
    payload["curator"] = payload["outcome"] == "related"
    payload["reason_codes"] = ["composed_in_code", "advisory_lint_only", "nearest_level"]
    payload["satisfies_parity"] = False
    _LAST_CROSS_VIEW.value = dict(payload)
    return payload


align_cross_view_entities = lint_cross_view_formulas


def observe_cross_view_lint(**kwargs: Any) -> dict[str, Any]:
    try:
        return lint_cross_view_formulas(**kwargs)
    except Exception:
        payload = {
            "accepted_as_authority": False,
            "satisfies_parity": False,
            "rewrites_ir": False,
        }
        _LAST_CROSS_VIEW.value = dict(payload)
        return payload


def last_smt_triage() -> dict[str, Any]:
    value = getattr(_LAST_SMT, "value", None)
    return dict(value) if isinstance(value, Mapping) else {}


def is_trap_family(*, smtlib: str = "", case_id: str = "") -> bool:
    ident = str(case_id or "").casefold()
    if ident.startswith("float") or ident.startswith("bv") or "uninterpreted" in ident:
        return True
    blob = str(smtlib or "")
    return any(marker in blob for marker in TRAP_SMT_MARKERS)


def triage_smt_goal(
    *,
    smtlib: str = "",
    english: str = "",
    case_id: str = "",
    privacy_class: str = "repository_private",
    remote_disclosure_permitted: bool = True,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Advisory sat/unsat hint. Always spends solvers. Never VERIFIED.

    FP/BV traps skip HTTP and still run the portfolio.
    """

    trap = is_trap_family(smtlib=smtlib, case_id=case_id)
    payload = {
        "accepted_as_authority": False,
        "skips_solver": False,
        "verified": False,
        "hint_only": True,
        "action": "run_solver",
        "claim_status": "",
        "trap_family": trap,
        "reason_codes": ["trap_family_force_solver", "skip_typesafe_http"]
        if trap
        else ["privacy_or_unconfigured"],
    }
    if trap:
        _LAST_SMT.value = dict(payload)
        return payload
    if not typesafe_permitted(
        privacy_class=privacy_class,
        remote_disclosure_permitted=remote_disclosure_permitted,
    ):
        payload["privacy_blocked"] = str(privacy_class or "").casefold() in REMOTE_BLOCKED_PRIVACY
        _LAST_SMT.value = dict(payload)
        return payload
    from ipfs_accelerate_py.typesafe_inference import Choice, Noul, system_one

    try:
        result = system_one(
            {
                "english": str(english or "")[:240],
                "smtlib": str(smtlib or "")[:800],
                "case_id": str(case_id or "")[:64],
            },
            {
                "claim_status": Choice(
                    instructions={
                        "question": "What does SMT-LIB check-sat return?",
                        "focus": "sat, unsat, or unknown. Not a kernel verdict.",
                    },
                    criteria={
                        "sat": {"what": "Assertions can hold together"},
                        "unsat": {"what": "Assertions contradict"},
                        "unknown": {"what": "Cannot decide"},
                    },
                ),
                "uses_fp_or_bv": Noul(
                    instructions={
                        "question": "Does `smtlib` use floating-point or bit-vector theory?",
                        "inspect": "`smtlib`",
                    },
                ),
                "likely_unsat": Noul(
                    instructions={
                        "question": "Do the assertions look contradictory?",
                        "inspect": "`english`",
                    },
                ),
            },
            timeout=timeout,
        )
    except Exception:
        payload["reason_codes"] = ["typesafe_error_fail_open"]
        _LAST_SMT.value = dict(payload)
        return payload
    choice = getattr((getattr(result, "choices", None) or {}).get("claim_status"), "choice", "")
    status = str(choice or "").strip().lower()
    if status not in {"sat", "unsat", "unknown"}:
        status = "unknown"
    payload["claim_status"] = status
    payload["reason_codes"] = ["composed_in_code", "hint_only", "always_run_solver"]
    _LAST_SMT.value = dict(payload)
    return payload


def observe_smt_triage(**kwargs: Any) -> dict[str, Any]:
    try:
        return triage_smt_goal(**kwargs)
    except Exception:
        payload = {
            "accepted_as_authority": False,
            "skips_solver": False,
            "verified": False,
            "hint_only": True,
            "action": "run_solver",
        }
        _LAST_SMT.value = dict(payload)
        return payload


def last_formula_rank() -> dict[str, Any]:
    value = getattr(_LAST_RANK, "value", None)
    return dict(value) if isinstance(value, Mapping) else {}


def rank_allowlisted_formulas(
    formula_ids: Sequence[str],
    *,
    summaries: Mapping[str, str] | None = None,
    obligation_id: str = "",
    privacy_class: str = "repository_private",
    remote_disclosure_permitted: bool = True,
    timeout: float = 15.0,
) -> tuple[str, ...]:
    """Order existing formula/candidate ids. Fail-open to input order.

    Never invents ids. Never rewrites IR. Never admits a candidate.
    """

    ordered: list[str] = []
    seen: set[str] = set()
    for item in formula_ids:
        ident = str(item).strip()
        if not ident or ident in seen:
            continue
        seen.add(ident)
        ordered.append(ident)
        if len(ordered) >= 8:
            break
    payload = {
        "accepted_as_authority": False,
        "invents_ids": False,
        "admits_candidate": False,
        "rewrites_ir": False,
        "obligation_id": str(obligation_id or "")[:128],
        "ranked_ids": list(ordered),
        "matches": {},
    }
    if not ordered:
        _LAST_RANK.value = dict(payload)
        return ()
    if not typesafe_permitted(
        privacy_class=privacy_class,
        remote_disclosure_permitted=remote_disclosure_permitted,
    ):
        _LAST_RANK.value = dict(payload)
        return tuple(ordered)
    from ipfs_accelerate_py.typesafe_inference import Noul, system_one

    texts = {
        ident: str((summaries or {}).get(ident) or ident)[:240] for ident in ordered
    }
    questions = {
        f"matches_{ident}": Noul(
            instructions={
                "question": (
                    f"Does `formulas.{ident}.summary` match `obligation.id`?"
                ),
                "inspect": f"`formulas.{ident}.summary`",
            },
        )
        for ident in ordered
    }
    try:
        result = system_one(
            {
                "obligation": {"id": str(obligation_id or "")[:128]},
                "formulas": {
                    ident: {"id": ident, "summary": texts[ident]} for ident in ordered
                },
            },
            questions,
            timeout=timeout,
        )
    except Exception:
        _LAST_RANK.value = dict(payload)
        return tuple(ordered)
    nouls = getattr(result, "nouls", None) or {}
    matches = {
        ident: round(
            float(getattr(nouls.get(f"matches_{ident}"), "noul", 0.0) or 0.0), 4
        )
        for ident in ordered
    }
    ranked = sorted(
        ordered,
        key=lambda ident: (-matches.get(ident, 0.0), ordered.index(ident)),
    )
    payload["ranked_ids"] = list(ranked)
    payload["matches"] = matches
    _LAST_RANK.value = dict(payload)
    ranked_ids = tuple(ranked)
    if summaries:
        gated = gate_evidence_passages(
            str(obligation_id or ""),
            tuple({"id": ident, "text": texts.get(ident, "")} for ident in ranked_ids),
            privacy_class=privacy_class,
            remote_disclosure_permitted=remote_disclosure_permitted,
            timeout=timeout,
        )
        routes = dict(gated.get("routes") or {})
        filtered = tuple(
            ident
            for ident in ranked_ids
            if routes.get(ident, "include") != "exclude"
        )
        if filtered:
            ranked_ids = filtered
            payload["ranked_ids"] = list(ranked_ids)
            payload["evidence_routes"] = routes
            _LAST_RANK.value = dict(payload)
    return ranked_ids


def last_evidence_gate() -> dict[str, Any]:
    value = getattr(_LAST_EVIDENCE, "value", None)
    return dict(value) if isinstance(value, Mapping) else {}


def route_evidence_answers(answers: Mapping[str, float]) -> str:
    """Thresholds in code. Injection first. Never admits a formula."""

    inj = float(answers.get("prompt_injection") or 0.0)
    contra = float(answers.get("contradicts_premise") or 0.0)
    relevant = float(answers.get("relevant") or 0.0)
    usable = float(answers.get("usable") or 0.0)
    if inj > EVIDENCE_THRESHOLDS["injection_max"]:
        return "exclude"
    if contra > EVIDENCE_THRESHOLDS["contradicts_min"]:
        return "conflict"
    if relevant < EVIDENCE_THRESHOLDS["relevant_min"]:
        return "exclude"
    if usable > EVIDENCE_THRESHOLDS["evidence_min"]:
        return "include"
    return "exclude"


def gate_evidence_passages(
    query: str,
    passages: Sequence[Mapping[str, Any]] = (),
    *,
    privacy_class: str = "repository_private",
    remote_disclosure_permitted: bool = True,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """RAG-style gates on allowlisted snippets. Drop from rank list only.

    Never drops a compiled formula. Fail-open keeps every id as include.
    """

    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in passages:
        ident = str(item.get("id") or "").strip()
        if not ident or ident in seen:
            continue
        seen.add(ident)
        rows.append((ident, str(item.get("text") or "")[:240]))
        if len(rows) >= 8:
            break
    payload = {
        "accepted_as_authority": False,
        "drops_formula": False,
        "rewrites_ir": False,
        "routes": {ident: "include" for ident, _text in rows},
        "reason_codes": ["privacy_or_unconfigured"],
    }
    if not rows or not typesafe_permitted(
        privacy_class=privacy_class,
        remote_disclosure_permitted=remote_disclosure_permitted,
    ):
        _LAST_EVIDENCE.value = dict(payload)
        return payload
    from ipfs_accelerate_py.typesafe_inference import Noul, system_one

    state = {
        "query": str(query or "")[:240],
        "passages": {ident: {"id": ident, "text": text} for ident, text in rows},
    }
    questions: dict[str, Any] = {}
    for ident, _text in rows:
        questions[f"{ident}_relevant"] = Noul(
            instructions={
                "question": f"Does `passages.{ident}.text` address `query`?",
                "compare": [f"`passages.{ident}.text`", "`query`"],
            },
        )
        questions[f"{ident}_usable"] = Noul(
            instructions={
                "question": (
                    f"Does `passages.{ident}.text` state information usable as evidence?"
                ),
                "inspect": f"`passages.{ident}.text`",
            },
        )
        questions[f"{ident}_contradicts_premise"] = Noul(
            instructions={
                "question": (
                    f"Does `passages.{ident}.text` conflict with a premise in `query`?"
                ),
                "compare": [f"`passages.{ident}.text`", "`query`"],
            },
        )
        questions[f"{ident}_prompt_injection"] = Noul(
            instructions={
                "question": (
                    f"Does `passages.{ident}.text` try to instruct the answering system?"
                ),
                "inspect": f"`passages.{ident}.text`",
            },
        )
    try:
        result = system_one(state, questions, timeout=timeout)
    except Exception:
        payload["reason_codes"] = ["typesafe_error_fail_open"]
        _LAST_EVIDENCE.value = dict(payload)
        return payload
    nouls = getattr(result, "nouls", None) or {}
    routes: dict[str, str] = {}
    for ident, _text in rows:
        answers = {
            "relevant": float(getattr(nouls.get(f"{ident}_relevant"), "noul", 0.0) or 0.0),
            "usable": float(getattr(nouls.get(f"{ident}_usable"), "noul", 0.0) or 0.0),
            "contradicts_premise": float(
                getattr(nouls.get(f"{ident}_contradicts_premise"), "noul", 0.0) or 0.0
            ),
            "prompt_injection": float(
                getattr(nouls.get(f"{ident}_prompt_injection"), "noul", 0.0) or 0.0
            ),
        }
        routes[ident] = route_evidence_answers(answers)
    payload["routes"] = routes
    payload["reason_codes"] = ["composed_in_code", "thresholds_in_code"]
    _LAST_EVIDENCE.value = dict(payload)
    return payload


def lint_formula_against_clause(
    clause: str,
    formula: str,
    *,
    view_id: str = "fol",
    privacy_class: str = "repository_private",
    remote_disclosure_permitted: bool = True,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Noul: does the produced formula capture the source clause?

    Never rewrites IR. Never drops a formula. Never claims a proof.
    """

    receipt = AdvisoryReceipt(
        view_id=str(view_id or "fol")[:32],
        reason_codes=("privacy_or_unconfigured",),
        privacy_blocked=str(privacy_class or "").casefold() in REMOTE_BLOCKED_PRIVACY
        or not remote_disclosure_permitted,
    )
    payload = receipt.to_dict()
    payload["clause"] = str(clause or "")[:240]
    payload["formula"] = str(formula or "")[:240]
    if not typesafe_permitted(
        privacy_class=privacy_class,
        remote_disclosure_permitted=remote_disclosure_permitted,
    ):
        _LAST.value = dict(payload)
        return payload
    from ipfs_accelerate_py.typesafe_inference import Noul, system_one

    try:
        result = system_one(
            {
                "clause": payload["clause"],
                "formula": payload["formula"],
                "view_id": payload["view_id"],
            },
            {
                "captures": Noul(
                    instructions={
                        "question": "Does `formula` capture the actors in `clause`?",
                        "compare": ["`formula`", "`clause`"],
                    },
                ),
                "modality_matches": Noul(
                    instructions={
                        "question": (
                            "Do deontic or temporal operators in `formula` "
                            "match the verbs in `clause`?"
                        ),
                        "compare": ["`formula`", "`clause`"],
                    },
                ),
            },
            timeout=timeout,
        )
    except Exception:
        payload["reason_codes"] = ["typesafe_error_fail_open"]
        _LAST.value = dict(payload)
        return payload
    nouls = getattr(result, "nouls", None) or {}
    captures = float(getattr(nouls.get("captures"), "noul", 0.0) or 0.0)
    modality = float(getattr(nouls.get("modality_matches"), "noul", 0.0) or 0.0)
    conf = float(getattr(nouls.get("captures"), "confidence", 0.0) or 0.0)
    payload["captures"] = round(captures, 4)
    payload["modality_matches"] = round(modality, 4)
    payload["confidence"] = round(conf, 4)
    payload["reason_codes"] = ["composed_in_code", "advisory_lint_only"]
    _LAST.value = dict(payload)
    return payload


def last_logic_family() -> dict[str, Any]:
    value = getattr(_LAST_FAMILY, "value", None)
    return dict(value) if isinstance(value, Mapping) else {}


def classify_logic_family(
    clause: str,
    *,
    produced_view: str = "fol",
    privacy_class: str = "repository_private",
    remote_disclosure_permitted: bool = True,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Choice over closed logic families. Low confidence → coarser tag only.

    Never rewrites the produced formula. Fail-open keeps the converter's family
    at specificity ``group``.
    """

    fallback = _VIEW_TO_FAMILY.get(str(produced_view or "fol"), "first_order")
    payload = {
        "accepted_as_authority": False,
        "rewrites_ir": False,
        "family": fallback,
        "specificity": "group",
        "confidence": 0.0,
        "reason_codes": ["privacy_or_unconfigured"],
    }
    if not typesafe_permitted(
        privacy_class=privacy_class,
        remote_disclosure_permitted=remote_disclosure_permitted,
    ):
        _LAST_FAMILY.value = dict(payload)
        return payload
    from ipfs_accelerate_py.typesafe_inference import Choice, system_one

    try:
        result = system_one(
            {"clause": str(clause or "")[:240], "produced_view": fallback},
            {
                "family": Choice(
                    instructions={
                        "question": (
                            "Which closed logic family best matches `clause`?"
                        ),
                        "inspect": "`clause`",
                    },
                    criteria={
                        "first_order": {
                            "what": "Classical first-order / FOL facts and implications"
                        },
                        "deontic": {
                            "what": "Obligations, permissions, prohibitions"
                        },
                        "temporal": {
                            "what": "Time, workflows, until/always operators"
                        },
                        "program": {
                            "what": "Hoare / dynamic skill effects"
                        },
                        "authorization": {
                            "what": "Tool or resource permissions"
                        },
                    },
                )
            },
            timeout=timeout,
        )
    except Exception:
        payload["reason_codes"] = ["typesafe_error_fail_open"]
        _LAST_FAMILY.value = dict(payload)
        return payload
    answer = (getattr(result, "choices", None) or {}).get("family")
    picked = str(getattr(answer, "choice", "") or "").strip()
    conf = float(getattr(answer, "confidence", 0.0) or 0.0)
    if picked not in LOGIC_FAMILIES:
        picked = fallback
    payload["family"] = picked if conf >= COARSE_CONFIDENCE else fallback
    payload["specificity"] = "group" if conf >= COARSE_CONFIDENCE else "family"
    payload["confidence"] = round(conf, 4)
    payload["reason_codes"] = ["composed_in_code", "confidence_gated"]
    _LAST_FAMILY.value = dict(payload)
    return payload


def observe_logic_family(clause: str, *, produced_view: str = "fol") -> dict[str, Any]:
    try:
        return classify_logic_family(clause, produced_view=produced_view)
    except Exception:
        payload = {
            "accepted_as_authority": False,
            "rewrites_ir": False,
            "family": _VIEW_TO_FAMILY.get(produced_view, "first_order"),
            "specificity": "group",
        }
        _LAST_FAMILY.value = dict(payload)
        return payload


def last_logic_route() -> dict[str, Any]:
    value = getattr(_LAST_ROUTE, "value", None)
    return dict(value) if isinstance(value, Mapping) else {}


def route_logic_hierarchy(
    clause: str,
    *,
    produced_view: str = "fol",
    privacy_class: str = "repository_private",
    remote_disclosure_permitted: bool = True,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Greedy Choice over declared family children. Never switches converters."""

    base = classify_logic_family(
        clause,
        produced_view=produced_view,
        privacy_class=privacy_class,
        remote_disclosure_permitted=remote_disclosure_permitted,
        timeout=timeout,
    )
    family = str(base.get("family") or "first_order")
    payload = dict(base)
    payload["switches_converter"] = False
    payload["rewrites_ir"] = False
    payload["path"] = [family]
    payload["leaf"] = family
    children = FAMILY_CHILDREN.get(family) or ()
    if (
        payload.get("specificity") != "group"
        or not children
        or not typesafe_permitted(
            privacy_class=privacy_class,
            remote_disclosure_permitted=remote_disclosure_permitted,
        )
    ):
        _LAST_ROUTE.value = dict(payload)
        return payload
    from ipfs_accelerate_py.typesafe_inference import Choice, system_one

    try:
        result = system_one(
            {"clause": str(clause or "")[:240], "family": family},
            {
                "child": Choice(
                    instructions={
                        "question": (
                            "Which declared child of `family` best matches `clause`?"
                        ),
                        "inspect": "`clause`",
                    },
                    criteria={
                        "obligation": {"what": "shall / must / duty"},
                        "permission": {"what": "may / can / allowed"},
                        "prohibition": {"what": "must not / shall not / forbidden"},
                    },
                )
            },
            timeout=timeout,
        )
    except Exception:
        payload["reason_codes"] = list(payload.get("reason_codes") or []) + [
            "child_choice_fail_open"
        ]
        _LAST_ROUTE.value = dict(payload)
        return payload
    answer = (getattr(result, "choices", None) or {}).get("child")
    picked = str(getattr(answer, "choice", "") or "").strip()
    conf = float(getattr(answer, "confidence", 0.0) or 0.0)
    if picked in children and conf >= COARSE_CONFIDENCE:
        payload["path"] = [family, picked]
        payload["leaf"] = picked
    payload["child_confidence"] = round(conf, 4)
    payload["switches_converter"] = False
    _LAST_ROUTE.value = dict(payload)
    return payload


def observe_logic_route(clause: str, *, produced_view: str = "fol") -> dict[str, Any]:
    try:
        return route_logic_hierarchy(clause, produced_view=produced_view)
    except Exception:
        fallback = _VIEW_TO_FAMILY.get(produced_view, "first_order")
        payload = {
            "accepted_as_authority": False,
            "rewrites_ir": False,
            "switches_converter": False,
            "family": fallback,
            "path": [fallback],
            "leaf": fallback,
        }
        _LAST_ROUTE.value = dict(payload)
        return payload


def last_declared_action() -> dict[str, Any]:
    value = getattr(_LAST_ACTION, "value", None)
    return dict(value) if isinstance(value, Mapping) else {}


def suggest_declared_action(
    clause: str,
    *,
    allowed_actions: Sequence[str] = (),
    allowed_paths: Sequence[str] = (),
    privacy_class: str = "repository_private",
    remote_disclosure_permitted: bool = True,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Choice over already-declared compiler actions. Never invents paths."""

    allowed = tuple(
        dict.fromkeys(str(item).strip() for item in allowed_actions if str(item).strip())
    )[:8]
    paths = tuple(
        dict.fromkeys(str(item).strip() for item in allowed_paths if str(item).strip())
    )[:8]
    payload = {
        "accepted_as_authority": False,
        "invents_action": False,
        "invents_path": False,
        "rewrites_ir": False,
        "action": "",
        "allowed_actions": list(allowed),
        "allowed_paths": list(paths),
        "reason_codes": ["privacy_or_unconfigured"],
    }
    if not allowed or not typesafe_permitted(
        privacy_class=privacy_class,
        remote_disclosure_permitted=remote_disclosure_permitted,
    ):
        _LAST_ACTION.value = dict(payload)
        return payload
    from ipfs_accelerate_py.typesafe_inference import Choice, system_one

    try:
        result = system_one(
            {
                "clause": str(clause or "")[:240],
                "allowed_actions": list(allowed),
                "allowed_paths": list(paths),
            },
            {
                "action": Choice(
                    instructions={
                        "question": (
                            "Which declared `allowed_actions` item matches `clause`?"
                        ),
                        "inspect": "`clause`",
                    },
                    criteria={
                        ident: {"what": ident, "not_for": "any other listed action"}
                        for ident in allowed
                    },
                )
            },
            timeout=timeout,
        )
    except Exception:
        payload["reason_codes"] = ["typesafe_error_fail_open"]
        _LAST_ACTION.value = dict(payload)
        return payload
    picked = str(
        getattr((getattr(result, "choices", None) or {}).get("action"), "choice", "")
        or ""
    ).strip()
    payload["action"] = picked if picked in allowed else ""
    payload["reason_codes"] = ["composed_in_code", "declared_actions_only"]
    _LAST_ACTION.value = dict(payload)
    return payload


def observe_declared_action(
    clause: str,
    *,
    allowed_actions: Sequence[str] = (),
    allowed_paths: Sequence[str] = (),
) -> dict[str, Any]:
    try:
        return suggest_declared_action(
            clause,
            allowed_actions=allowed_actions,
            allowed_paths=allowed_paths,
        )
    except Exception:
        payload = {
            "accepted_as_authority": False,
            "invents_action": False,
            "invents_path": False,
            "action": "",
        }
        _LAST_ACTION.value = dict(payload)
        return payload


def last_conversion_verify() -> dict[str, Any]:
    value = getattr(_LAST_VERIFY, "value", None)
    return dict(value) if isinstance(value, Mapping) else {}


def verify_conversion_fields(
    clause: str,
    formula: str,
    *,
    parts: Mapping[str, str] | None = None,
    view_id: str = "fol",
    fire: float = VERIFY_FIRE,
    privacy_class: str = "repository_private",
    remote_disclosure_permitted: bool = True,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """SDE-style per-field noul battery. True = something is wrong.

    Escalate if any flag exceeds ``fire``. Never rewrites or drops the formula.
    """

    fields = {
        str(key).strip()[:32]: str(value or "")[:64]
        for key, value in dict(parts or {}).items()
        if str(key).strip() and str(value or "").strip()
    }
    if len(fields) > 6:
        fields = dict(list(fields.items())[:6])
    payload = {
        "accepted_as_authority": False,
        "rewrites_ir": False,
        "drops_formula": False,
        "escalate": False,
        "fire": float(fire),
        "flags": {},
        "view_id": str(view_id or "fol")[:32],
        "reason_codes": ["privacy_or_unconfigured"],
    }
    if not typesafe_permitted(
        privacy_class=privacy_class,
        remote_disclosure_permitted=remote_disclosure_permitted,
    ):
        _LAST_VERIFY.value = dict(payload)
        return payload
    from ipfs_accelerate_py.typesafe_inference import Noul, system_one

    questions: dict[str, Any] = {
        "formula::hallucinated": Noul(
            instructions={
                "question": (
                    "Is `formula` unsupported by, or absent from, `clause`?"
                ),
                "compare": ["`formula`", "`clause`"],
            },
        ),
        "formula::off_target": Noul(
            instructions={
                "question": (
                    "Was `formula` pulled from incidental wording rather than "
                    "the claim in `clause`?"
                ),
                "compare": ["`formula`", "`clause`"],
            },
        ),
        "formula::incomplete": Noul(
            instructions={
                "question": (
                    "Does `formula` omit an actor or modality that `clause` supports?"
                ),
                "compare": ["`formula`", "`clause`"],
            },
        ),
    }
    for name, token in fields.items():
        questions[f"{name}::hallucinated"] = Noul(
            instructions={
                "question": (
                    f"Is extracted token `{token}` unsupported by `clause`?"
                ),
                "inspect": "`clause`",
            },
        )
    try:
        result = system_one(
            {
                "clause": str(clause or "")[:240],
                "formula": str(formula or "")[:240],
                "parts": fields,
                "view_id": payload["view_id"],
            },
            questions,
            timeout=timeout,
        )
    except Exception:
        payload["reason_codes"] = ["typesafe_error_fail_open"]
        _LAST_VERIFY.value = dict(payload)
        return payload
    nouls = getattr(result, "nouls", None) or {}
    flags: dict[str, float] = {}
    fired = False
    threshold = float(fire)
    for key in questions:
        noul = float(getattr(nouls.get(key), "noul", 0.0) or 0.0)
        flags[key] = round(noul, 4)
        if noul > threshold:
            fired = True
    payload["flags"] = flags
    payload["escalate"] = fired
    payload["reason_codes"] = ["composed_in_code", "any_flag_gate"]
    _LAST_VERIFY.value = dict(payload)
    return payload


def observe_conversion_verify(
    clause: str,
    formula: str,
    *,
    parts: Mapping[str, str] | None = None,
    view_id: str = "fol",
) -> dict[str, Any]:
    try:
        return verify_conversion_fields(
            clause, formula, parts=parts, view_id=view_id
        )
    except Exception:
        payload = {
            "accepted_as_authority": False,
            "rewrites_ir": False,
            "drops_formula": False,
            "escalate": False,
        }
        _LAST_VERIFY.value = dict(payload)
        return payload


def observe_formula_rank(
    formula_ids: Sequence[str],
    *,
    summaries: Mapping[str, str] | None = None,
    obligation_id: str = "",
) -> tuple[str, ...]:
    """Never-raises ranking of already-allowlisted ids."""

    try:
        return rank_allowlisted_formulas(
            formula_ids, summaries=summaries, obligation_id=obligation_id
        )
    except Exception:
        ordered = tuple(
            str(item).strip() for item in formula_ids if str(item).strip()
        )
        _LAST_RANK.value = {
            "accepted_as_authority": False,
            "invents_ids": False,
            "admits_candidate": False,
            "rewrites_ir": False,
            "ranked_ids": list(ordered[:8]),
        }
        return ordered[:8]


def observe_formula_clause_lint(
    clause: str,
    formula: str,
    *,
    view_id: str = "fol",
) -> dict[str, Any]:
    """Never-raises wrapper for converter hooks."""

    try:
        return lint_formula_against_clause(clause, formula, view_id=view_id)
    except Exception:
        payload = AdvisoryReceipt(view_id=str(view_id or "fol")[:32]).to_dict()
        _LAST.value = dict(payload)
        return payload


__all__ = [
    "AdvisoryReceipt",
    "is_trap_family",
    "classify_logic_family",
    "last_conversion_verify",
    "last_cross_view_lint",
    "last_logic_family",
    "observe_logic_family",
    "observe_logic_route",
    "route_logic_hierarchy",
    "last_logic_route",
    "last_declared_action",
    "observe_declared_action",
    "suggest_declared_action",
    "last_formula_lint",
    "last_formula_rank",
    "last_smt_triage",
    "observe_conversion_verify",
    "verify_conversion_fields",
    "align_cross_view_entities",
    "gate_evidence_passages",
    "last_evidence_gate",
    "route_evidence_answers",
    "lint_cross_view_formulas",
    "observe_cross_view_lint",
    "observe_smt_triage",
    "triage_smt_goal",
    "lint_formula_against_clause",
    "observe_formula_clause_lint",
    "observe_formula_rank",
    "rank_allowlisted_formulas",
    "typesafe_permitted",
]
