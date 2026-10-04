"""Render and lake-check Lean files that define a statute or a KG term.

Each file is a self-contained ``lake build Legal`` package. A successful
build locks the identity fingerprint of the statute or term. That is not a
legal admit and not a proof of the clause. Imports, sorry, admit, and axiom
are refused.
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable, Mapping, Sequence

from .lake_probe import MAX_SOURCE, _MODALITY_CODE, lake_check, pattern_from_rule, render_norm


KIND_CODE = {
    "actor": 0,
    "action": 1,
    "object": 2,
    "modality": 3,
    "conditions": 4,
    "exceptions": 5,
    "temporal": 6,
    "qualifiers": 7,
    "decompiled": 8,
}
MAX_CLAUSES = 24
MAX_TERM_STATUTES = 16


def _nat(text: str) -> int:
    return int(hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:8], 16)


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def statute_fingerprint(legal_id: str) -> int:
    return _nat("statute\n" + str(legal_id or "").strip())


def term_fingerprint(kind: str, value: str) -> int:
    return _nat(str(kind or "") + "\n" + str(value or "").strip())


def render_statute_lean(
    legal_id: str,
    clauses: Sequence[Mapping[str, Any]],
) -> str:
    """Define one statute as a locked identity plus its sealed clause fingerprints."""

    statute_id = str(legal_id or "").strip() or "unspecified"
    fingerprint = statute_fingerprint(statute_id)
    rows = [item for item in clauses if isinstance(item, Mapping)][:MAX_CLAUSES]
    lines = [
        f"def statuteFingerprint : Nat := {fingerprint}",
        "def statuteLocked (n : Nat) : Bool := decide (n = statuteFingerprint)",
        "theorem statuteDefined : statuteLocked statuteFingerprint = true := by",
        "  unfold statuteLocked statuteFingerprint",
        "  decide",
        f"def clauseCount : Nat := {len(rows)}",
        f"theorem clauseCountLocked : clauseCount = {len(rows)} := by",
        "  unfold clauseCount",
        "  decide",
    ]
    for index, row in enumerate(rows):
        span = str(row.get("source_span_id") or row.get("id") or index)
        clause_fp = _nat(span + "\n" + str(row.get("source_sha256") or row.get("text") or ""))
        lines.append(f"def clauseFingerprint{index} : Nat := {clause_fp}")
        lines.append(
            f"theorem clauseDefined{index} : clauseFingerprint{index} = {clause_fp} := by"
        )
        lines.append(f"  unfold clauseFingerprint{index}")
        lines.append("  decide")
        rule = row.get("rule") if isinstance(row.get("rule"), Mapping) else {}
        modality = str((rule or {}).get("modality") or "")
        if modality in _MODALITY_CODE:
            pattern = pattern_from_rule(rule)
            if pattern is not None:
                lines.append(render_norm(pattern, suffix=str(index)).rstrip())
    source = "\n".join(lines) + "\n"
    if len(source.encode("utf-8")) > MAX_SOURCE:
        source = source.encode("utf-8")[: MAX_SOURCE - 1].decode("utf-8", errors="ignore")
        if not source.endswith("\n"):
            source += "\n"
    return source


def _mappings(clauses: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [item for item in clauses if isinstance(item, Mapping)]


def _statute_ids(statute_ids: Sequence[str]) -> list[str]:
    return [str(item).strip() for item in statute_ids if str(item).strip()]


def statute_lean_unit(legal_id: str, clauses: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Render the capped statute file and keep the clause ids that did not fit."""

    rows = _mappings(clauses)
    overflow = [
        str(row.get("source_span_id") or row.get("id") or index)
        for index, row in enumerate(rows)
        if index >= MAX_CLAUSES
    ]
    source = render_statute_lean(legal_id, rows)
    return {
        "admitted": False,
        "count": min(len(rows), MAX_CLAUSES),
        "formalized": False,
        "kind": "lean_unit_overflow" if overflow else "",
        "lean": source,
        "overflow_ids": overflow,
        "source_sha256": _sha(source),
    }


def term_lean_unit(
    kind: str,
    value: str,
    *,
    statute_ids: Sequence[str] = (),
    term_id: str = "",
) -> dict[str, Any]:
    """Render the capped term file and keep the statute ids that did not fit."""

    statutes = _statute_ids(statute_ids)
    overflow = statutes[MAX_TERM_STATUTES:]
    source = render_term_lean(kind, value, statute_ids=statutes)
    return {
        "admitted": False,
        "count": min(len(statutes), MAX_TERM_STATUTES),
        "formalized": False,
        "kind": str(kind or ""),
        "lean": source,
        "overflow_ids": overflow,
        "overflow_kind": "lean_unit_overflow" if overflow else "",
        "source_sha256": _sha(source),
        "statute_ids": statutes[:MAX_TERM_STATUTES],
        "term_id": str(term_id or ""),
        "value": str(value or ""),
    }


def lake_receipt(
    source: str,
    previous: Mapping[str, Any] | None = None,
    *,
    verify: bool = False,
    check: Callable[[str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reuse a stored Lake result when the source hash is unchanged."""

    digest = _sha(source)
    if isinstance(previous, Mapping) and str(previous.get("source_sha256") or "") == digest:
        return {
            "admitted": False,
            "checked": False,
            "formalized": False,
            "lake_error": str(previous.get("lake_error") or ""),
            "lake_ok": bool(previous.get("lake_ok")),
            "source_sha256": digest,
        }
    if verify:
        probed = probe_lean_source(source, check=check)
        return {
            "admitted": False,
            "checked": True,
            "formalized": False,
            "lake_error": str(probed.get("error") or ""),
            "lake_ok": bool(probed.get("lake_ok")),
            "source_sha256": digest,
        }
    return {
        "admitted": False,
        "checked": False,
        "formalized": False,
        "lake_error": "lake_not_run",
        "lake_ok": False,
        "source_sha256": digest,
    }


def render_term_lean(
    kind: str,
    value: str,
    *,
    statute_ids: Sequence[str] = (),
) -> str:
    """Define one knowledge-graph term as a locked kind and value fingerprint."""

    key = str(kind or "").strip() or "object"
    text = str(value or "").strip()
    kind_code = int(KIND_CODE.get(key, 2))
    fingerprint = term_fingerprint(key, text)
    statutes = [str(item).strip() for item in statute_ids if str(item).strip()][:MAX_TERM_STATUTES]
    lines = [
        f"def termKindCode : Nat := {kind_code}",
        f"def termFingerprint : Nat := {fingerprint}",
        "def termLocked (k f : Nat) : Bool := decide (k = termKindCode /\\ f = termFingerprint)",
        "theorem termDefined : termLocked termKindCode termFingerprint = true := by",
        "  unfold termLocked termKindCode termFingerprint",
        "  decide",
        f"def statuteCount : Nat := {len(statutes)}",
        f"theorem statuteCountLocked : statuteCount = {len(statutes)} := by",
        "  unfold statuteCount",
        "  decide",
    ]
    for index, legal_id in enumerate(statutes):
        fp = statute_fingerprint(legal_id)
        lines.append(f"def usedStatute{index} : Nat := {fp}")
        lines.append(f"theorem usedStatuteDefined{index} : usedStatute{index} = {fp} := by")
        lines.append(f"  unfold usedStatute{index}")
        lines.append("  decide")
    source = "\n".join(lines) + "\n"
    if len(source.encode("utf-8")) > MAX_SOURCE:
        source = source.encode("utf-8")[: MAX_SOURCE - 1].decode("utf-8", errors="ignore")
        if not source.endswith("\n"):
            source += "\n"
    return source


def probe_lean_source(
    source: str,
    *,
    check: Callable[[str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run ``lake build Legal`` on one unit. Not an admit."""

    probed = dict((check or lake_check)(source))
    probed["admitted"] = False
    probed["formalized"] = False
    probed["source_sha256"] = _sha(source)
    return probed
