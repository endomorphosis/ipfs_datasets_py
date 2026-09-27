"""Repair notes for a span that the codec reconstructed and the compiler rejected.

The note carries both results, the files and symbols a supervisor can edit,
and whether each codec formula is a duty lock or a definitional Lake fixture.
It does not admit the span or emit a Lean axiom.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any, Mapping

from .lake_probe import FIXTURE_BEARER, pattern_from_fixture, pattern_from_rule
from .supervisor_queue import EDIT_SCOPES


_FIELD_REPAIR = {
    "penalty": (
        "The compiler abstains because the predicate is a penalty, such as imprison or fine.",
        "Extend canonical_compiler.py so a penalty predicate becomes a prohibition or obligation the decompiler can render. Keep lake build Legal free of axiom, sorry, and admit.",
    ),
    "cross_references": (
        "The compiler abstains because the sentence points at another provision, such as under this title.",
        "Resolve the cross-reference in deontic_parser.py and formula_builder.py, or compile the local duty without requiring the cited section to already be sealed.",
    ),
    "resolved_cross_references": (
        "The compiler abstains because a cross-reference was recognized and still not compiled.",
        "Make the resolved citation a qualifier on the local duty in formula_builder.py instead of an unsupported field.",
    ),
    "definition_scope": (
        "The compiler abstains because the sentence is a definition or a scope clause rather than a duty.",
        "Parse definition and scope text in deontic_parser.py and give it a norm type the compiler accepts.",
    ),
    "unsupported_norm_type": (
        "The compiler abstains because the norm type is outside obligation, permission, and prohibition.",
        "Map the norm type onto O, P, or F in canonical_compiler.py, or record it as a belief, knowledge, or actorless-prohibition fixture.",
    ),
    "no_parser_elements": (
        "The parser found no actor and action, so the compiler has no duty to compile.",
        "Add the missing actor and action cues in deontic_parser.py. Citation scraps should stay gaps until they contain a duty.",
    ),
    "no_clause": (
        "The sentence did not split into a clause the compiler can open.",
        "Adjust clause splitting in the autoformal compiler entry so a single duty still opens one clause.",
    ),
}
_DEFAULT_REPAIR = (
    "The codec returned text and the compiler abstained.",
    "Compare the codec formulas with the compiler reason, then edit the parser or compiler path listed here so the reconstructed text round-trips. Do not mark the span admitted.",
)


def _package_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _symbols(paths: list[str], needles: list[str]) -> list[str]:
    found: list[str] = []
    root = _package_root()
    lowered = [item.lower() for item in needles if item]
    for rel in paths:
        file_path = root / rel
        if not file_path.is_file():
            continue
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            name = node.name.lower()
            if lowered and not any(needle in name for needle in lowered):
                continue
            found.append(f"{rel}:{node.name}")
            if len(found) >= 8:
                return found
    return found


def _formulas(autoencoder: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in list(autoencoder.get("formulas") or [])[:6]:
        if not isinstance(item, Mapping):
            continue
        arguments = [str(part) for part in item.get("arguments") or []]
        actor = ""
        scope = ""
        for part in arguments:
            if part.startswith("actor:"):
                actor = part.split(":", 1)[1]
            elif part.startswith("scope:"):
                scope = part.split(":", 1)[1]
        rule = {
            "action": str(item.get("predicate") or ""),
            "actor": actor,
            "modality": str(item.get("op") or ""),
            "object": scope,
        }
        duty = pattern_from_rule(rule)
        fixture = pattern_from_fixture(rule)
        if duty is not None:
            lake = "duty"
            code = int(duty["modality"])
        elif fixture is not None:
            lake = "fixture"
            code = int(fixture["modality"])
        else:
            lake = "unrendered"
            code = -1
        row = {
            "arguments": arguments[:4],
            "lake": lake,
            "lake_code": code,
            "op": str(item.get("op") or ""),
            "predicate": str(item.get("predicate") or ""),
        }
        aliased = str(item.get("aliased_from") or "")
        role = str(item.get("role") or "")
        if aliased:
            row["aliased_from"] = aliased
        if role:
            row["role"] = role
        rows.append(row)
    return rows


def formula_evidence(autoencoder: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Lake disposition for each codec formula. This does not admit the span."""

    return _formulas(autoencoder)


def _fields(reason: str) -> list[str]:
    text = " ".join(str(reason or "").split())
    head = text.split(" ", 1)[0]
    if ":" not in head:
        return [head] if head else []
    _code, _, tail = head.partition(":")
    return [part for part in tail.split(",") if part] or [head]


def repair_report(
    *,
    compiler: Mapping[str, Any] | None = None,
    autoencoder: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One repair capsule. The diagnostic stays the compiler class."""

    compiled = dict(compiler or {})
    captured = dict(autoencoder or {})
    reason = " ".join(str(compiled.get("reason") or "").split())
    diagnostic = reason.split(" ", 1)[0] if reason else "compiler_disagreement"
    fields = [str(item) for item in compiled.get("fields") or [] if str(item)] or _fields(diagnostic)
    error, fix = _DEFAULT_REPAIR
    for field in fields:
        if field in _FIELD_REPAIR:
            error, fix = _FIELD_REPAIR[field]
            break
    citations = [str(item) for item in captured.get("citations") or [] if str(item)]
    if citations and any(field in {"cross_references", "resolved_cross_references"} for field in fields):
        fix = fix + " Use the resolved citation symbols: " + ", ".join(citations[:6]) + "."
    mode = diagnostic.split(":", 1)[0]
    if mode.startswith("CanonicalErrorCode."):
        mode = "compiler_abstain"
    paths = [str(path) for path in EDIT_SCOPES.get(mode, EDIT_SCOPES["compiler_abstain"])]
    needles = ["compile", "decompil", "parse", "formula", *fields]
    formulas = _formulas(captured)
    return {
        "admitted": False,
        "autoencoder": {
            "cosine_loss": captured.get("cosine_loss"),
            "cosine_similarity": captured.get("cosine_similarity"),
            "cross_entropy_loss": captured.get("cross_entropy_loss"),
            "ir_compression_loss": captured.get("ir_compression_loss"),
            "ir_compression_ratio": captured.get("ir_compression_ratio"),
            "reconstruction_loss": captured.get("reconstruction_loss"),
            "view_cross_entropy_loss": captured.get("view_cross_entropy_loss"),
            "decoded_text": str(captured.get("decoded_text") or "")[:240],
            "formulas": formulas,
            "structural": str(captured.get("structural") or "")[:180],
        },
        "compiler": {
            "decompiled": str(compiled.get("decompiled") or "")[:240],
            "fields": fields[:8],
            "reason": diagnostic,
            "rule": compiled.get("rule") if isinstance(compiled.get("rule"), dict) else {},
            "status": str(compiled.get("compiler_status") or compiled.get("status") or ""),
        },
        "citations": citations[:6],
        "diagnostic": diagnostic,
        "edit_paths": paths,
        "error": error,
        "fix": fix,
        "formalized": False,
        "lake": {
            "admits": False,
            "command": "lake build Legal",
            "fixtures": {"B": 3, "Frame": 6, "K": 4, "actorless_F": 5, "bearer": FIXTURE_BEARER},
            "refuses": ["axiom", "sorry", "admit"],
        },
        "symbols": _symbols(paths, needles),
        "wrote_compiler": False,
    }


_CODEC: Any = None


def codec_capture(text: str) -> dict[str, Any]:
    """Run the modal codec. Returns formulas and reconstructed text."""

    global _CODEC
    source = str(text or "").strip()
    if not source:
        return {"decoded_text": "", "formulas": [], "structural": ""}
    if _CODEC is None:
        from ipfs_datasets_py.logic.modal.codec import DeterministicModalLogicCodec

        _CODEC = DeterministicModalLogicCodec()
    document_id = "repair-" + hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    try:
        encoded = _CODEC.encode(source, document_id=document_id)
    except Exception:
        return {"decoded_text": "", "formulas": [], "structural": ""}
    formulas = []
    for formula in list(getattr(encoded.modal_ir, "formulas", []) or [])[:6]:
        operator = formula.operator.to_dict()
        predicate = formula.predicate.to_dict()
        metadata = dict(getattr(formula, "metadata", {}) or {})
        entry = {
            "arguments": [str(item) for item in predicate.get("arguments") or []][:4],
            "op": str(operator.get("symbol") or operator.get("name") or ""),
            "predicate": str(predicate.get("name") or ""),
        }
        aliased = str(metadata.get("aliased_from") or "")
        role = str(predicate.get("role") or "")
        if aliased:
            entry["aliased_from"] = aliased
        if role:
            entry["role"] = role
        formulas.append(entry)
    losses = dict(getattr(encoded, "losses", {}) or {})
    from ipfs_datasets_py.logic.modal.ir_symbol_catalog import bluebook_symbols

    citations = bluebook_symbols(source)
    return {
        "cosine_loss": float(losses.get("source_decompiled_text_embedding_cosine_loss") or 0.0),
        "cosine_similarity": float(losses.get("source_decompiled_text_embedding_cosine_similarity") or 0.0),
        "cross_entropy_loss": losses.get("cross_entropy_loss"),
        "ir_compression_loss": float(losses.get("ir_compression_loss") or 0.0),
        "ir_compression_ratio": float(losses.get("ir_compression_ratio") or 0.0),
        "reconstruction_loss": float(losses.get("text_reconstruction_loss") or 0.0),
        "view_cross_entropy_loss": losses.get("guidance_legal_ir_view_cross_entropy_loss"),
        "citations": citations[:6],
        "decoded_text": " ".join(str(getattr(encoded, "decoded_text", "") or "").split()),
        "formulas": formulas,
        "structural": " ".join(str((encoded.metadata or {}).get("modal_decompiler_structural_text") or "").split())[:180],
        "token_loss": float(losses.get("source_decompiled_text_token_loss") or 0.0),
    }
