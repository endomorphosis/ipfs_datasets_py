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
    return tuple(ranked)


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
    "last_formula_lint",
    "last_formula_rank",
    "last_smt_triage",
    "observe_smt_triage",
    "triage_smt_goal",
    "lint_formula_against_clause",
    "observe_formula_clause_lint",
    "observe_formula_rank",
    "rank_allowlisted_formulas",
    "typesafe_permitted",
]
