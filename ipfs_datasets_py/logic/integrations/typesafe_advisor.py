"""Advisory TypeSafe lint for autoformalization outputs.

TypeSafe may score whether a produced formula captures a source clause.
It cannot rewrite IR, drop formulas, admit proofs, or replace FOLConverter /
hammer / kernel. No API key → no HTTP; converters keep their existing path.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

REMOTE_BLOCKED_PRIVACY = frozenset({"local_only", "forbidden_external"})
ADVISOR_SCHEMA = "ipfs_datasets_py/logic/typesafe-formula-lint@1"
_LAST = threading.local()


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
    "last_formula_lint",
    "lint_formula_against_clause",
    "observe_formula_clause_lint",
    "typesafe_permitted",
]
