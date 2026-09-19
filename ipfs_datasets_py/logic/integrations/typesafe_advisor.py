"""Advisory TypeSafe lint for autoformalization outputs.

TypeSafe may score whether a produced formula captures a source clause.
It cannot rewrite IR, drop formulas, admit proofs, or replace FOLConverter /
hammer / kernel. No API key → no HTTP; converters keep their existing path.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from datetime import date, timedelta
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
_LAST_CITATION = threading.local()
_LAST_PICK = threading.local()
_LAST_DATE = threading.local()
_LAST_FIND = threading.local()
VERIFY_FIRE = 0.7
NOUL_UNCERTAIN_LOW = 0.30
COARSE_CONFIDENCE = 0.9
ACTION_MIN_CONFIDENCE = 0.60
CITATION_AUTO_ACCEPT = 0.8
DATE_REVIEW_BELOW = 0.60
DATE_YEAR_MIN = 1900
DATE_YEAR_MAX = 2050
FIND_MAX_LINES = 17
FIND_EXISTS_HIGH = 0.70
FIND_EXISTS_LOW = 0.35
RANK_SHORTLIST = 3
FITS_THRESHOLD = 0.30
CITATION_CHOICES = ("supports", "contradicts", "says_nothing")
PICK_NONE = "none"
PICK_MAX = 8
DATE_MONTHS = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}
DATE_WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
_YEAR_IN_TEXT = re.compile(r"\b(19\d{2}|20\d{2})\b")
_CURLY_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})
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
_LAST_STITCH = threading.local()
JOIN_AFTER_DANGLING = 0.2
JOIN_AFTER_TERMINAL = 0.5
CLASSIFY_MAX_BLOCKS = 8
HEADING_MAX_CHARS = 90
STEP_THRESHOLD = 0.5
BLOCK_TYPES = (
    "heading",
    "paragraph",
    "list_item",
    "quote",
    "code",
    "callout",
)
HEADING_LEVELS = ("title", "section", "subsection")
CALLOUT_KINDS = ("note", "tip", "warning")
_TERMINAL_END = re.compile(r'[.!?:;…]["\')\]]*$')
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
        "shortlist": [],
        "fits": {},
        "suggested": "",
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
    confirmed = _confirm_ranked_shortlist(
        obligation_id=str(obligation_id or "")[:128],
        shortlist=tuple(ranked_ids[:RANK_SHORTLIST]),
        texts=texts,
        timeout=timeout,
    )
    payload["shortlist"] = list(confirmed["shortlist"])
    payload["fits"] = dict(confirmed["fits"])
    payload["suggested"] = str(confirmed["suggested"] or "")
    payload["reason_codes"] = list(confirmed.get("reason_codes") or ["composed_in_code"])
    _LAST_RANK.value = dict(payload)
    return ranked_ids


def _confirm_ranked_shortlist(
    *,
    obligation_id: str,
    shortlist: Sequence[str],
    texts: Mapping[str, str],
    timeout: float,
) -> dict[str, Any]:
    """Second pass: Choice over the shortlist plus ``fits::id`` nouls.

    If the best fits noul is under ``FITS_THRESHOLD``, suggest nothing.
    Never invents ids. Does not rewrite the first-pass ranking.
    """

    names = tuple(
        ident for ident in shortlist if str(ident).strip()
    )[:RANK_SHORTLIST]
    payload: dict[str, Any] = {
        "shortlist": list(names),
        "fits": {},
        "suggested": "",
        "reason_codes": ["composed_in_code"],
    }
    if not names:
        payload["reason_codes"] = ["no_shortlist"]
        return payload
    try:
        from ipfs_accelerate_py.typesafe_inference import Choice, Noul, system_one
    except Exception:
        payload["reason_codes"] = ["typesafe_error_fail_open"]
        return payload
    questions: dict[str, Any] = {
        "which": Choice(
            instructions={
                "question": (
                    "Which shortlisted formula is the right one for `obligation.id`?"
                ),
                "inspect": "`formulas`",
            },
            criteria={
                ident: {"what": str(texts.get(ident) or ident)[:240]}
                for ident in names
            },
        )
    }
    for ident in names:
        questions[f"fits::{ident}"] = Noul(
            instructions={
                "question": (
                    f"Does formula `{ident}` do the specific thing "
                    "`obligation.id` asks for?"
                ),
                "inspect": f"`formulas.{ident}.summary`",
            },
        )
    try:
        result = system_one(
            {
                "obligation": {"id": obligation_id},
                "formulas": {
                    ident: {"id": ident, "summary": str(texts.get(ident) or ident)[:240]}
                    for ident in names
                },
            },
            questions,
            timeout=timeout,
        )
    except Exception:
        payload["reason_codes"] = ["typesafe_error_fail_open"]
        return payload
    nouls = getattr(result, "nouls", None) or {}
    fits = {
        ident: round(
            float(getattr(nouls.get(f"fits::{ident}"), "noul", 0.0) or 0.0), 4
        )
        for ident in names
    }
    payload["fits"] = fits
    best = max(fits.values()) if fits else 0.0
    if best < FITS_THRESHOLD:
        payload["reason_codes"] = ["composed_in_code", "nothing_fits"]
        return payload
    winner = str(
        getattr((getattr(result, "choices", None) or {}).get("which"), "choice", "")
        or ""
    ).strip()
    if winner not in names:
        payload["reason_codes"] = ["composed_in_code", "unknown_choice"]
        return payload
    payload["suggested"] = winner
    payload["reason_codes"] = ["composed_in_code", "shortlist_confirm"]
    return payload


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


def last_supporting_line() -> dict[str, Any]:
    value = getattr(_LAST_FIND, "value", None)
    return dict(value) if isinstance(value, Mapping) else {}


def _tagged_source_lines(
    text: str, *, limit: int = FIND_MAX_LINES
) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for raw in str(text or "").splitlines():
        stripped = re.sub(r"[\t ]+", " ", raw).strip()
        if not stripped:
            continue
        rows.append((f"L{len(rows):03d}", stripped))
        if len(rows) >= limit:
            break
    return rows


def find_supporting_line(
    source: str,
    query: str,
    *,
    view_id: str = "fol",
    privacy_class: str = "repository_private",
    remote_disclosure_permitted: bool = True,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Choice over existing line ids plus an exists noul.

    Ranking cannot invent a line. ``exists`` decides whether any line answers
    ``query``. Text is copied from the source only.
    """

    rows = _tagged_source_lines(source)
    payload: dict[str, Any] = {
        "accepted_as_authority": False,
        "rewrites_ir": False,
        "drops_formula": False,
        "invents_ids": False,
        "line_id": "",
        "line_text": "",
        "exists": 0.0,
        "verdict": "",
        "ranked": [],
        "view_id": str(view_id or "fol")[:32],
        "reason_codes": ["privacy_or_unconfigured"],
    }
    if not rows:
        payload["reason_codes"] = ["no_lines"]
        _LAST_FIND.value = dict(payload)
        return payload
    if not typesafe_permitted(
        privacy_class=privacy_class,
        remote_disclosure_permitted=remote_disclosure_permitted,
    ):
        _LAST_FIND.value = dict(payload)
        return payload
    from ipfs_accelerate_py.typesafe_inference import Choice, Noul, system_one

    ids = [ident for ident, _text in rows]
    by_id = {ident: text for ident, text in rows}
    tagged = "\n".join(f"{ident}| {text}" for ident, text in rows)
    ask = str(query or "")[:240]
    try:
        result = system_one(
            {
                "lines": tagged,
                "query": ask,
                "view_id": payload["view_id"],
            },
            {
                "where": Choice(
                    instructions={
                        "question": (
                            "Which line of `lines` contains the answer to `query`?"
                        ),
                        "inspect": "`lines`",
                    },
                    criteria={ident: {"what": ident} for ident in ids},
                ),
                "exists": Noul(
                    instructions={
                        "question": (
                            "Does any line of `lines` address or answer `query`?"
                        ),
                        "inspect": "`lines`",
                    },
                ),
            },
            timeout=timeout,
        )
    except Exception:
        payload["reason_codes"] = ["typesafe_error_fail_open"]
        _LAST_FIND.value = dict(payload)
        return payload
    where = (getattr(result, "choices", None) or {}).get("where")
    picked = str(getattr(where, "choice", "") or "").strip()
    if picked not in by_id:
        picked = ""
    probs = dict(getattr(where, "probabilities", None) or {})
    ranked_ids = sorted(
        ids,
        key=lambda ident: (
            -float(probs.get(ident, 0.0) or 0.0),
            ids.index(ident),
        ),
    )
    if not probs and picked:
        ranked_ids = [picked] + [ident for ident in ids if ident != picked]
    ranked = [
        {
            "id": ident,
            "score": round(float(probs.get(ident, 0.0) or 0.0), 4),
            "text": by_id[ident],
        }
        for ident in ranked_ids[:4]
    ]
    exists = float(
        getattr((getattr(result, "nouls", None) or {}).get("exists"), "noul", 0.0)
        or 0.0
    )
    if exists >= FIND_EXISTS_HIGH:
        verdict = "answered"
    elif exists < FIND_EXISTS_LOW:
        verdict = "absent"
    else:
        verdict = "partial"
    payload["line_id"] = picked
    payload["line_text"] = by_id.get(picked, "")
    payload["exists"] = round(exists, 4)
    payload["verdict"] = verdict
    payload["ranked"] = ranked
    payload["reason_codes"] = ["composed_in_code", "line_ids_from_source"]
    _LAST_FIND.value = dict(payload)
    return payload


def observe_supporting_line(
    source: str,
    query: str,
    *,
    view_id: str = "fol",
) -> dict[str, Any]:
    """Never-raises wrapper. Does not rewrite IR or admit a source span."""

    try:
        return find_supporting_line(source, query, view_id=view_id)
    except Exception:
        payload = {
            "accepted_as_authority": False,
            "rewrites_ir": False,
            "drops_formula": False,
            "invents_ids": False,
            "line_id": "",
            "verdict": "",
        }
        _LAST_FIND.value = dict(payload)
        return payload


def last_line_stitch() -> dict[str, Any]:
    value = getattr(_LAST_STITCH, "value", None)
    return dict(value) if isinstance(value, Mapping) else {}


def stitch_hard_wrapped_lines(
    text: str,
    *,
    privacy_class: str = "repository_private",
    remote_disclosure_permitted: bool = True,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Merge hard-wrapped lines. Output characters come only from the input.

    Fail-open keeps the original text. Never generates formulas or markup.
    """

    original = str(text or "")
    payload = {
        "accepted_as_authority": False,
        "generates_text": False,
        "generates_markup": False,
        "rewrites_ir": False,
        "text": original,
        "original": original,
        "blocks": [],
        "reason_codes": ["privacy_or_unconfigured"],
    }
    raw_lines = original.split("\n")
    lines: list[dict[str, Any]] = []
    gap = False
    for raw in raw_lines:
        stripped = re.sub(r"[\t ]+", " ", raw).strip()
        if not stripped:
            gap = bool(lines)
            continue
        lines.append({"text": stripped, "gap": gap})
        gap = False
        if len(lines) >= 17:
            break
    if len(lines) < 2 or not typesafe_permitted(
        privacy_class=privacy_class,
        remote_disclosure_permitted=remote_disclosure_permitted,
    ):
        _LAST_STITCH.value = dict(payload)
        return payload
    from ipfs_accelerate_py.typesafe_inference import Noul, system_one

    questions: dict[str, Any] = {}
    for index in range(1, len(lines)):
        if lines[index]["gap"]:
            continue
        ident = f"L{index:03d}"
        questions[ident] = Noul(
            instructions={
                "question": (
                    f"Does line L{index:03d} pick up mid-sentence, continuing "
                    f"a sentence left unfinished at the end of line L{index - 1:03d}?"
                ),
            },
        )
    if not questions:
        _LAST_STITCH.value = dict(payload)
        return payload
    tagged = "\n".join(
        f"{chr(10) if item['gap'] else ''}L{i:03d}| {item['text']}"
        for i, item in enumerate(lines)
    )
    try:
        result = system_one({"lines": tagged}, questions, timeout=timeout)
    except Exception:
        payload["reason_codes"] = ["typesafe_error_fail_open"]
        _LAST_STITCH.value = dict(payload)
        return payload
    nouls = getattr(result, "nouls", None) or {}
    joins = [0.0] * len(lines)
    for index in range(1, len(lines)):
        ident = f"L{index:03d}"
        joins[index] = float(getattr(nouls.get(ident), "noul", 0.0) or 0.0)
    block_rows: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        bar = (
            JOIN_AFTER_TERMINAL
            if index and _TERMINAL_END.search(lines[index - 1]["text"])
            else JOIN_AFTER_DANGLING
        )
        if block_rows and not line["gap"] and joins[index] >= bar:
            block_rows[-1]["text"] += " " + line["text"]
        else:
            block_rows.append({"text": line["text"], "gap": bool(line["gap"])})
    merged = "\n".join(item["text"] for item in block_rows)
    payload["text"] = merged
    payload["reason_codes"] = ["composed_in_code", "characters_from_input"]
    payload["blocks"] = _classify_stitched_blocks(
        block_rows, timeout=timeout
    )
    _LAST_STITCH.value = dict(payload)
    return payload


def _classify_stitched_blocks(
    block_rows: Sequence[Mapping[str, Any]],
    *,
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """Pass-2 Choice over stitched blocks. Labels only; characters stay from input."""

    rows = list(block_rows)[:CLASSIFY_MAX_BLOCKS]
    labeled = [
        {
            "id": f"B{index:03d}",
            "text": str(item.get("text") or ""),
            "type": "",
            "confidence": 0.0,
            "hlevel": "",
            "step": 0.0,
            "ordered": False,
            "callout": "",
        }
        for index, item in enumerate(rows)
        if str(item.get("text") or "").strip()
    ]
    if not labeled:
        return []
    try:
        from ipfs_accelerate_py.typesafe_inference import Choice, Noul, system_one
    except Exception:
        return labeled
    questions: dict[str, Any] = {}
    for item in labeled:
        bid = item["id"]
        questions[f"type_{bid}"] = Choice(
            instructions={
                "question": f"What kind of content is block {bid}?",
                "inspect": "`blocks`",
            },
            criteria={
                "heading": {
                    "what": "A short label or title, not a full sentence of content"
                },
                "paragraph": {
                    "what": "Running prose of one or more complete sentences"
                },
                "list_item": {
                    "what": "One entry in a list of parallel items"
                },
                "quote": {"what": "Words attributed to a person or source"},
                "code": {"what": "Code, a shell command, or a config snippet"},
                "callout": {
                    "what": "A warning, tip, or note set apart from the main text"
                },
            },
        )
        if len(item["text"]) <= HEADING_MAX_CHARS:
            questions[f"hlevel_{bid}"] = Choice(
                instructions={
                    "question": (
                        f"As a heading, what level would block {bid} occupy?"
                    )
                },
                criteria={
                    "title": {"what": "The title of the whole document"},
                    "section": {"what": "A major section heading"},
                    "subsection": {"what": "A minor heading under a section"},
                },
            )
        questions[f"step_{bid}"] = Noul(
            instructions={
                "question": (
                    f"Is block {bid} a step in a sequence where order matters?"
                )
            },
        )
        questions[f"callout_{bid}"] = Choice(
            instructions={"question": f"What kind of aside is block {bid}?"},
            criteria={
                "note": {"what": "Neutral extra information"},
                "tip": {"what": "A helpful suggestion"},
                "warning": {"what": "A caution about harm or failure"},
            },
        )
    tagged = "\n".join(f"{item['id']}| {item['text']}" for item in labeled)
    try:
        result = system_one({"blocks": tagged}, questions, timeout=timeout)
    except Exception:
        return labeled
    choices = getattr(result, "choices", None) or {}
    nouls = getattr(result, "nouls", None) or {}
    for item in labeled:
        bid = item["id"]
        type_answer = choices.get(f"type_{bid}")
        picked = str(getattr(type_answer, "choice", "") or "").strip()
        item["type"] = picked if picked in BLOCK_TYPES else "paragraph"
        item["confidence"] = round(
            float(getattr(type_answer, "confidence", 0.0) or 0.0), 4
        )
        if item["type"] == "heading":
            level = str(
                getattr(choices.get(f"hlevel_{bid}"), "choice", "") or ""
            ).strip()
            item["hlevel"] = level if level in HEADING_LEVELS else "section"
        if item["type"] == "list_item":
            item["step"] = round(
                float(getattr(nouls.get(f"step_{bid}"), "noul", 0.0) or 0.0), 4
            )
            item["ordered"] = item["step"] >= STEP_THRESHOLD
        if item["type"] == "callout":
            kind = str(
                getattr(choices.get(f"callout_{bid}"), "choice", "") or ""
            ).strip()
            item["callout"] = kind if kind in CALLOUT_KINDS else "note"
    return labeled


def observe_line_stitch(text: str) -> dict[str, Any]:
    try:
        return stitch_hard_wrapped_lines(text)
    except Exception:
        payload = {
            "accepted_as_authority": False,
            "generates_text": False,
            "generates_markup": False,
            "text": str(text or ""),
            "original": str(text or ""),
            "blocks": [],
        }
        _LAST_STITCH.value = dict(payload)
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
        "confidence": 0.0,
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
    answer = (getattr(result, "choices", None) or {}).get("action")
    picked = str(getattr(answer, "choice", "") or "").strip()
    conf = float(getattr(answer, "confidence", 0.0) or 0.0)
    payload["confidence"] = round(conf, 4)
    if picked not in allowed or conf < ACTION_MIN_CONFIDENCE:
        payload["action"] = ""
        payload["reason_codes"] = [
            "composed_in_code",
            "declared_actions_only",
            "low_confidence" if picked in allowed else "unknown_choice",
        ]
    else:
        payload["action"] = picked
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

    Escalate if any flag exceeds ``fire``. Flags in
    ``[NOUL_UNCERTAIN_LOW, fire]`` are ``uncertain`` and do not escalate.
    Never rewrites or drops the formula.
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
        "uncertain": False,
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
    in_band = False
    threshold = float(fire)
    for key in questions:
        noul = float(getattr(nouls.get(key), "noul", 0.0) or 0.0)
        flags[key] = round(noul, 4)
        if noul > threshold:
            fired = True
        elif noul >= NOUL_UNCERTAIN_LOW:
            in_band = True
    payload["flags"] = flags
    payload["escalate"] = fired
    payload["uncertain"] = bool(in_band and not fired)
    payload["reason_codes"] = ["composed_in_code", "any_flag_gate"]
    if payload["uncertain"]:
        payload["reason_codes"] = list(payload["reason_codes"]) + ["uncertain_band"]
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
            "uncertain": False,
        }
        _LAST_VERIFY.value = dict(payload)
        return payload


def last_formula_citation() -> dict[str, Any]:
    value = getattr(_LAST_CITATION, "value", None)
    return dict(value) if isinstance(value, Mapping) else {}


def _normalize_citation_text(text: str) -> str:
    """Collapse whitespace and fold curly quotes so a quote matches across wraps."""

    return re.sub(r"\s+", " ", str(text or "").translate(_CURLY_QUOTES)).strip()


def check_formula_citation(
    source: str,
    formula: str,
    *,
    quote: str = "",
    view_id: str = "fol",
    privacy_class: str = "repository_private",
    remote_disclosure_permitted: bool = True,
    timeout: float = 15.0,
    auto_accept: float = CITATION_AUTO_ACCEPT,
) -> dict[str, Any]:
    """String-match the quote first, then Choice how the source relates to the formula.

    A missing quote is ``fabricated`` with no HTTP. Cookbook ``verified`` is stored
    as ``supports`` — never kernel VERIFIED or Leanstral accepted.
    """

    payload: dict[str, Any] = {
        "accepted_as_authority": False,
        "rewrites_ir": False,
        "drops_formula": False,
        "verdict": "",
        "confidence": 0.0,
        "auto": False,
        "status": "privacy_or_unconfigured",
        "view_id": str(view_id or "fol")[:32],
        "reason_codes": ["privacy_or_unconfigured"],
    }
    needle = _normalize_citation_text(quote)
    haystack = _normalize_citation_text(source)
    if needle:
        if not haystack or needle not in haystack:
            payload["status"] = "missing"
            payload["verdict"] = "fabricated"
            payload["auto"] = True
            payload["confidence"] = None
            payload["reason_codes"] = ["string_match", "fabricated_no_http"]
            _LAST_CITATION.value = dict(payload)
            return payload
        payload["status"] = "found"
    else:
        payload["status"] = "section-only"
    if not typesafe_permitted(
        privacy_class=privacy_class,
        remote_disclosure_permitted=remote_disclosure_permitted,
    ):
        _LAST_CITATION.value = dict(payload)
        return payload
    from ipfs_accelerate_py.typesafe_inference import Choice, system_one

    try:
        result = system_one(
            {
                "claim": str(formula or "")[:240],
                "section": str(source or "")[:800],
                "view_id": payload["view_id"],
            },
            {
                "relation": Choice(
                    instructions={
                        "question": "How does the section relate to the claim?",
                        "compare": ["`section`", "`claim`"],
                    },
                    criteria={
                        "supports": {
                            "what": (
                                "The section states the claim or directly "
                                "implies that it is true"
                            )
                        },
                        "contradicts": {
                            "what": (
                                "The section states the opposite of the claim "
                                "or implies it is false"
                            )
                        },
                        "says_nothing": {
                            "what": (
                                "The section does not address what the claim "
                                "asserts, either way"
                            )
                        },
                    },
                )
            },
            timeout=timeout,
        )
    except Exception:
        payload["reason_codes"] = ["typesafe_error_fail_open"]
        _LAST_CITATION.value = dict(payload)
        return payload
    answer = (getattr(result, "choices", None) or {}).get("relation")
    picked = str(getattr(answer, "choice", "") or "").strip()
    if picked not in CITATION_CHOICES:
        picked = "says_nothing"
    conf = float(getattr(answer, "confidence", 0.0) or 0.0)
    payload["verdict"] = picked
    payload["confidence"] = round(conf, 4)
    payload["auto"] = conf >= float(auto_accept)
    payload["reason_codes"] = ["composed_in_code", "citation_check", "advisory_only"]
    _LAST_CITATION.value = dict(payload)
    return payload


def observe_formula_citation(
    source: str,
    formula: str,
    *,
    quote: str = "",
    view_id: str = "fol",
) -> dict[str, Any]:
    """Never-raises wrapper. Does not rewrite IR or admit proofs."""

    try:
        return check_formula_citation(
            source, formula, quote=quote, view_id=view_id
        )
    except Exception:
        payload = {
            "accepted_as_authority": False,
            "rewrites_ir": False,
            "drops_formula": False,
            "verdict": "",
            "auto": False,
        }
        _LAST_CITATION.value = dict(payload)
        return payload


def last_extracted_span() -> dict[str, Any]:
    value = getattr(_LAST_PICK, "value", None)
    return dict(value) if isinstance(value, Mapping) else {}


def pick_extracted_span(
    clause: str,
    candidates: Sequence[str],
    *,
    view_id: str = "fol",
    privacy_class: str = "repository_private",
    remote_disclosure_permitted: bool = True,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Choice among regex/NLP-extracted spans plus ``none``.

    Copies the pick verbatim. Never invents a name. Callers keep the full
    extracted set; this is sidecar metadata only.
    """

    ordered = tuple(
        dict.fromkeys(
            str(item).strip()
            for item in candidates
            if str(item).strip() and str(item).strip().casefold() != PICK_NONE
        )
    )[:PICK_MAX]
    payload: dict[str, Any] = {
        "accepted_as_authority": False,
        "rewrites_ir": False,
        "drops_formula": False,
        "invents_span": False,
        "pick": "",
        "candidates": list(ordered),
        "confidence": 0.0,
        "view_id": str(view_id or "fol")[:32],
        "reason_codes": ["privacy_or_unconfigured"],
    }
    if not ordered:
        payload["reason_codes"] = ["no_candidates"]
        _LAST_PICK.value = dict(payload)
        return payload
    if not typesafe_permitted(
        privacy_class=privacy_class,
        remote_disclosure_permitted=remote_disclosure_permitted,
    ):
        _LAST_PICK.value = dict(payload)
        return payload
    from ipfs_accelerate_py.typesafe_inference import Choice, system_one

    criteria = {
        ident: {"what": ident, "not_for": "any other listed span"}
        for ident in ordered
    }
    criteria[PICK_NONE] = {"what": "None of these is the requested value."}
    try:
        result = system_one(
            {
                "clause": str(clause or "")[:240],
                "candidates": list(ordered),
                "view_id": payload["view_id"],
            },
            {
                "pick": Choice(
                    instructions={
                        "question": (
                            "Which extracted span is the primary predicate "
                            "or actor named by `clause`?"
                        ),
                        "inspect": "`clause`",
                    },
                    criteria=criteria,
                )
            },
            timeout=timeout,
        )
    except Exception:
        payload["reason_codes"] = ["typesafe_error_fail_open"]
        _LAST_PICK.value = dict(payload)
        return payload
    answer = (getattr(result, "choices", None) or {}).get("pick")
    picked = str(getattr(answer, "choice", "") or "").strip()
    conf = float(getattr(answer, "confidence", 0.0) or 0.0)
    payload["confidence"] = round(conf, 4)
    allowed = set(ordered) | {PICK_NONE}
    if picked not in allowed:
        payload["pick"] = PICK_NONE
        payload["reason_codes"] = ["composed_in_code", "unknown_choice"]
    else:
        payload["pick"] = picked
        payload["reason_codes"] = ["composed_in_code", "pre_parsed_pick"]
    _LAST_PICK.value = dict(payload)
    return payload


def observe_extracted_span(
    clause: str,
    candidates: Sequence[str],
    *,
    view_id: str = "fol",
) -> dict[str, Any]:
    """Never-raises wrapper. Does not rewrite the extracted set."""

    try:
        return pick_extracted_span(clause, candidates, view_id=view_id)
    except Exception:
        payload = {
            "accepted_as_authority": False,
            "rewrites_ir": False,
            "drops_formula": False,
            "invents_span": False,
            "pick": "",
        }
        _LAST_PICK.value = dict(payload)
        return payload


def last_clause_date() -> dict[str, Any]:
    value = getattr(_LAST_DATE, "value", None)
    return dict(value) if isinstance(value, Mapping) else {}


def _years_in_clause(clause: str) -> tuple[str, ...]:
    found: list[str] = []
    for match in _YEAR_IN_TEXT.findall(str(clause or "")):
        year = int(match)
        if DATE_YEAR_MIN <= year <= DATE_YEAR_MAX and match not in found:
            found.append(match)
        if len(found) >= PICK_MAX:
            break
    return tuple(found)


def _date_part(
    parts: Mapping[str, Any], key: str
) -> tuple[str, float]:
    raw = parts.get(key) if isinstance(parts.get(key), Mapping) else {}
    choice = str((raw or {}).get("choice") or "none").strip() or "none"
    conf = float((raw or {}).get("confidence") or 0.0)
    return choice, conf


def assemble_date_parts(
    parts: Mapping[str, Any],
    *,
    today: date,
) -> dict[str, Any]:
    """Turn TypeSafe date *parts* into a calendar date in Python.

    The model never adds numbers or does weekday arithmetic.
    """

    mode, mode_conf = _date_part(parts, "mode")
    confs = [mode_conf]

    def _result(resolved: date | None, note: str) -> dict[str, Any]:
        usable = [float(item) for item in confs]
        confidence = min(usable) if usable else 0.0
        incomplete = resolved is None
        needs_review = incomplete or confidence < DATE_REVIEW_BELOW
        return {
            "date": resolved.isoformat() if resolved is not None else "",
            "mode": mode,
            "confidence": round(confidence, 4),
            "needs_review": needs_review,
            "incomplete": incomplete,
            "note": note,
        }

    if mode == "none":
        return _result(None, "no such date stated")
    if mode == "absolute":
        month, month_conf = _date_part(parts, "month")
        day, day_conf = _date_part(parts, "day")
        year, year_conf = _date_part(parts, "year")
        confs += [month_conf, day_conf, year_conf]
        if month not in DATE_MONTHS or day in {"none", ""} or not day.isdigit():
            return _result(None, "absolute date incomplete")
        if year == "out_of_range":
            return _result(
                None, f"year outside {DATE_YEAR_MIN}-{DATE_YEAR_MAX}"
            )
        month_num = DATE_MONTHS[month]
        day_num = int(day)
        if year == "none":
            try:
                resolved = date(today.year, month_num, day_num)
            except ValueError:
                return _result(None, f"impossible date: {month} {day}")
            if resolved < today - timedelta(days=31):
                try:
                    resolved = date(today.year + 1, month_num, day_num)
                except ValueError:
                    return _result(None, f"impossible date: {month} {day}")
            return _result(resolved, "")
        if not year.isdigit():
            return _result(None, "absolute date incomplete")
        try:
            return _result(date(int(year), month_num, day_num), "")
        except ValueError:
            return _result(None, f"impossible date: {year}-{month}-{day}")
    if mode == "relative":
        anchor, anchor_conf = _date_part(parts, "day_anchor")
        confs.append(anchor_conf)
        if anchor == "today":
            return _result(today, "")
        if anchor == "tomorrow":
            return _result(today + timedelta(days=1), "")
        if anchor == "day_after":
            return _result(today + timedelta(days=2), "")
        if anchor == "weekday":
            weekday, weekday_conf = _date_part(parts, "weekday")
            offset, offset_conf = _date_part(parts, "week_offset")
            confs += [weekday_conf, offset_conf]
            if weekday not in DATE_WEEKDAYS:
                return _result(None, "relative weekday not read")
            weekday_index = DATE_WEEKDAYS.index(weekday)
            this_monday = today - timedelta(days=today.weekday())
            if offset == "next":
                resolved = this_monday + timedelta(days=7 + weekday_index)
            elif offset == "current":
                resolved = this_monday + timedelta(days=weekday_index)
            else:
                resolved = today + timedelta(
                    days=(weekday_index - today.weekday()) % 7
                )
            return _result(resolved, "")
        return _result(None, "relative day not read")
    return _result(None, f"unrecognized mode: {mode}")


def extract_clause_date(
    clause: str,
    *,
    role: str = "the primary date stated in the clause",
    today: date | None = None,
    view_id: str = "tdfol",
    privacy_class: str = "repository_private",
    remote_disclosure_permitted: bool = True,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """TypeSafe reads date parts; code assembles the calendar date."""

    today = today or date.today()
    payload: dict[str, Any] = {
        "accepted_as_authority": False,
        "rewrites_ir": False,
        "drops_formula": False,
        "date": "",
        "mode": "",
        "confidence": 0.0,
        "needs_review": False,
        "incomplete": False,
        "note": "",
        "parts": {},
        "view_id": str(view_id or "tdfol")[:32],
        "reason_codes": ["privacy_or_unconfigured"],
    }
    if not typesafe_permitted(
        privacy_class=privacy_class,
        remote_disclosure_permitted=remote_disclosure_permitted,
    ):
        _LAST_DATE.value = dict(payload)
        return payload
    from ipfs_accelerate_py.typesafe_inference import Choice, system_one

    absent = "The document does not state this, or it is not this kind of date."
    years = _years_in_clause(clause)
    year_criteria = {
        year: {"what": year} for year in years
    }
    year_criteria["out_of_range"] = {
        "what": (
            f"A year is stated but is outside {DATE_YEAR_MIN}-{DATE_YEAR_MAX}"
        )
    }
    year_criteria["none"] = {"what": "No year is stated for this date."}
    labeled = str(role or "the primary date stated in the clause").strip()[:80]
    questions = {
        "mode": Choice(
            instructions={
                "question": (
                    f"How is {labeled} written? absolute names a month; "
                    "relative is today/tomorrow/weekday; none if unstated."
                ),
                "inspect": "`clause`",
            },
            criteria={
                "absolute": {"what": "A calendar date naming a month"},
                "relative": {"what": "A date relative to today"},
                "none": {"what": "The document does not state this date"},
            },
        ),
        "month": Choice(
            instructions={
                "question": f"If {labeled} is absolute, which month?",
                "inspect": "`clause`",
            },
            criteria={
                **{name: {"what": name} for name in DATE_MONTHS},
                "none": {"what": absent},
            },
        ),
        "day": Choice(
            instructions={
                "question": (
                    f"If {labeled} is absolute, which day of the month (1-31)?"
                ),
                "inspect": "`clause`",
            },
            criteria={
                **{str(day): {"what": str(day)} for day in range(1, 32)},
                "none": {"what": absent},
            },
        ),
        "year": Choice(
            instructions={
                "question": f"If {labeled} is absolute, which year?",
                "inspect": "`clause`",
            },
            criteria=year_criteria,
        ),
        "day_anchor": Choice(
            instructions={
                "question": (
                    f"If {labeled} is relative, which day is it relative to today?"
                ),
                "inspect": "`clause`",
            },
            criteria={
                "today": {"what": "today"},
                "tomorrow": {"what": "tomorrow"},
                "day_after": {"what": "the day after tomorrow"},
                "weekday": {"what": "a named weekday"},
                "none": {"what": absent},
            },
        ),
        "weekday": Choice(
            instructions={
                "question": f"If {labeled} names a weekday, which one?",
                "inspect": "`clause`",
            },
            criteria={
                **{name: {"what": name} for name in DATE_WEEKDAYS},
                "none": {"what": absent},
            },
        ),
        "week_offset": Choice(
            instructions={
                "question": (
                    f"If {labeled} names a weekday, which week: current, next, or none?"
                ),
                "inspect": "`clause`",
            },
            criteria={
                "current": {"what": "this week"},
                "next": {"what": "next week"},
                "none": {"what": absent},
            },
        ),
    }
    try:
        result = system_one(
            {
                "clause": str(clause or "")[:240],
                "role": labeled,
                "view_id": payload["view_id"],
            },
            questions,
            timeout=timeout,
        )
    except Exception:
        payload["reason_codes"] = ["typesafe_error_fail_open"]
        _LAST_DATE.value = dict(payload)
        return payload
    parts: dict[str, dict[str, Any]] = {}
    choices = getattr(result, "choices", None) or {}
    for key in questions:
        answer = choices.get(key)
        parts[key] = {
            "choice": str(getattr(answer, "choice", "") or "").strip() or "none",
            "confidence": round(
                float(getattr(answer, "confidence", 0.0) or 0.0), 4
            ),
        }
    assembled = assemble_date_parts(parts, today=today)
    payload["parts"] = parts
    payload["date"] = assembled["date"]
    payload["mode"] = assembled["mode"]
    payload["confidence"] = assembled["confidence"]
    payload["needs_review"] = assembled["needs_review"]
    payload["incomplete"] = assembled["incomplete"]
    payload["note"] = assembled["note"]
    payload["reason_codes"] = ["composed_in_code", "date_parts_only"]
    _LAST_DATE.value = dict(payload)
    return payload


def observe_clause_date(
    clause: str,
    *,
    role: str = "the primary date stated in the clause",
    today: date | None = None,
    view_id: str = "tdfol",
) -> dict[str, Any]:
    """Never-raises wrapper. Does not rewrite TDFOL formulas."""

    try:
        return extract_clause_date(
            clause, role=role, today=today, view_id=view_id
        )
    except Exception:
        payload = {
            "accepted_as_authority": False,
            "rewrites_ir": False,
            "drops_formula": False,
            "date": "",
            "incomplete": False,
        }
        _LAST_DATE.value = dict(payload)
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
    "assemble_date_parts",
    "extract_clause_date",
    "find_supporting_line",
    "last_clause_date",
    "last_extracted_span",
    "last_supporting_line",
    "last_formula_citation",
    "last_formula_lint",
    "last_formula_rank",
    "last_smt_triage",
    "check_formula_citation",
    "observe_clause_date",
    "observe_extracted_span",
    "observe_formula_citation",
    "observe_supporting_line",
    "pick_extracted_span",
    "observe_conversion_verify",
    "verify_conversion_fields",
    "align_cross_view_entities",
    "gate_evidence_passages",
    "last_line_stitch",
    "observe_line_stitch",
    "stitch_hard_wrapped_lines",
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
