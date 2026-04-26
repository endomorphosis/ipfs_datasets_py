#!/usr/bin/env python3
"""Build U.S. Code formal-logic and Groth16 proof artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional
import warnings


def _bootstrap_pythonpath() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


_bootstrap_pythonpath()

from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier  # noqa: E402
from ipfs_datasets_py.utils.cid_utils import cid_for_obj  # noqa: E402


_WS_RE = re.compile(r"\s+")
_IDENT_RE = re.compile(r"[^A-Za-z0-9_]+")
_STOP_TERMS = {
    "and",
    "are",
    "for",
    "from",
    "may",
    "of",
    "or",
    "shall",
    "that",
    "the",
    "this",
    "to",
    "with",
}
_RELATION_METHODS = {
    "IDENTIFIED_BY": "identifiedBy",
    "HAS_CITATION": "hasCitation",
    "IN_TITLE": "inTitle",
    "HAS_SECTION": "hasSection",
    "contains_section": "containsSection",
    "references": "references",
}


def _compact(value: Any) -> str:
    return _WS_RE.sub(" ", str(value or "")).strip()


def _symbol(value: Any, *, prefix: str = "entity") -> str:
    cleaned = _IDENT_RE.sub("_", _compact(value)).strip("_").lower()
    if not cleaned:
        cleaned = prefix
    if cleaned[0].isdigit():
        cleaned = f"{prefix}_{cleaned}"
    return cleaned[:140]


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "tolist"):
        try:
            return _json_safe(value.tolist())
        except Exception:
            pass
    return str(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(_json_safe(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _parse_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (Mapping, list)):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _extract_json_object(text: str) -> Dict[str, Any]:
    """Parse a JSON object from an LLM response, including fenced output."""
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("empty LLM response")
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()
    if not raw.startswith("{"):
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        start = raw.find("{")
        if start < 0:
            raise
        parsed, _ = decoder.raw_decode(raw[start:])
    if not isinstance(parsed, dict):
        raise ValueError("LLM response JSON was not an object")
    return parsed


def _normalize_llm_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    if "frame_logic_json" not in out:
        for key in ("frame_logic", "flogic", "frame_logic_object"):
            if isinstance(out.get(key), Mapping):
                out["frame_logic_json"] = out[key]
                break
    frame_logic = out.get("frame_logic_json")
    if isinstance(frame_logic, str):
        parsed_frame = _parse_json(frame_logic)
        if isinstance(parsed_frame, Mapping):
            frame_logic = dict(parsed_frame)
            out["frame_logic_json"] = frame_logic
    if isinstance(frame_logic, Mapping) and "ergo_program" not in frame_logic:
        for key in ("frame_logic_ergo", "ergo", "ergo_rules", "flora_program"):
            if _compact(frame_logic.get(key)):
                frame_logic = dict(frame_logic)
                frame_logic["ergo_program"] = _compact(frame_logic.get(key))
                out["frame_logic_json"] = frame_logic
                break
    if "deontic_temporal_fol" not in out:
        for key in ("tdfol", "temporal_deontic_fol", "deontic_temporal_first_order_logic"):
            if _compact(out.get(key)):
                out["deontic_temporal_fol"] = _compact(out.get(key))
                break
    if "deontic_cognitive_event_calculus" not in out:
        for key in ("dcec", "deontic_event_calculus", "cognitive_event_calculus"):
            if _compact(out.get(key)):
                out["deontic_cognitive_event_calculus"] = _compact(out.get(key))
                break
    return out


def _unique(values: Iterable[Any]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for value in values:
        text = _compact(value)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _top_terms(row: Mapping[str, Any], *, limit: int = 25) -> List[Dict[str, int]]:
    raw = row.get("term_frequencies")
    try:
        items = raw.tolist() if hasattr(raw, "tolist") else list(raw or [])
    except Exception:
        items = []
    pairs: List[Dict[str, int]] = []
    for item in items:
        if isinstance(item, Mapping):
            term = _compact(item.get("term")).lower()
            tf = int(item.get("tf") or 0)
        else:
            term = _compact(item).lower()
            tf = 1
        if not term or term in _STOP_TERMS or len(term) < 3 or term.isdigit():
            continue
        pairs.append({"term": term, "tf": tf})
    pairs.sort(key=lambda item: (-int(item["tf"]), item["term"]))
    return pairs[:limit]


def _norm_operator(text: str) -> str:
    lower = str(text or "").lower()
    if re.search(r"\b(shall not|may not|must not|prohibited|unlawful|forbidden)\b", lower):
        return "F"
    if re.search(r"\b(may|authorized|permitted|allowed|entitled|right to)\b", lower):
        return "P"
    if re.search(r"\b(shall|must|required|duty|responsible|subject to)\b", lower):
        return "O"
    return "O"


def _operator_label(op: str) -> str:
    return {"O": "obligation", "P": "permission", "F": "prohibition"}.get(op, "obligation")


def _read_parquet_rows(path: str) -> List[Dict[str, Any]]:
    import pyarrow.parquet as pq

    return pq.read_table(Path(path).expanduser().resolve()).to_pylist()


def _load_lookup(path: str, key_fields: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not path:
        return out
    for row in _read_parquet_rows(path):
        for field in key_fields:
            key = _compact(row.get(field))
            if key:
                out[key] = dict(row)
                break
    return out


def _load_relationships(path: str) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    if not path:
        return grouped
    for row in _read_parquet_rows(path):
        source = _compact(row.get("source"))
        if source:
            grouped.setdefault(source, []).append(dict(row))
    return grouped


def _section_ref(row: Mapping[str, Any]) -> str:
    title = _compact(row.get("title_number"))
    section = _compact(row.get("section_number"))
    if title and section:
        return f"{title} U.S.C. § {section}"
    return _compact(row.get("law_name")) or _compact(row.get("ipfs_cid")) or "U.S. Code section"


def _logic_context(
    row: Mapping[str, Any],
    *,
    bm25_by_cid: Mapping[str, Mapping[str, Any]],
    relationships_by_source: Mapping[str, List[Mapping[str, Any]]],
) -> Dict[str, Any]:
    cid = _compact(row.get("ipfs_cid"))
    rels = list(relationships_by_source.get(cid) or [])
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for rel in rels[:48]:
        rel_type = _compact(rel.get("type"))
        target = _compact(rel.get("target"))
        if rel_type and target:
            grouped.setdefault(rel_type, []).append(
                {"target": target, "target_symbol": _symbol(target, prefix="target")}
            )
    citations = _parse_json(row.get("citations_json")) or {}
    chapter = _parse_json(row.get("chapter_json")) or {}
    bm25_row = dict(bm25_by_cid.get(cid) or {})
    return {
        "source_ipfs_cid": cid,
        "schema_version": "uscode-logic-context-v1",
        "title_number": _compact(row.get("title_number")),
        "section_number": _compact(row.get("section_number")),
        "official_cite": _section_ref(row),
        "chapter": chapter,
        "public_laws": list(citations.get("public_laws") or [])[:12] if isinstance(citations, Mapping) else [],
        "usc_citations": list(citations.get("usc_citations") or [])[:12] if isinstance(citations, Mapping) else [],
        "relationships": grouped,
        "bm25": {
            "document_length": int(bm25_row.get("document_length") or 0),
            "unique_term_count": int(bm25_row.get("unique_term_count") or 0),
            "top_terms": _top_terms(bm25_row, limit=25),
            "document_count": int(bm25_row.get("bm25_document_count") or 0),
        },
    }


def _make_tdfol(row: Mapping[str, Any], op: str, context: Mapping[str, Any]) -> str:
    section = _symbol(_section_ref(row), prefix="usc_section")
    title = _symbol(f"usc_title_{row.get('title_number')}", prefix="usc_title")
    clauses = [
        f"FederalStatuteSection({section})",
        f"PartOfTitle({section},{title})",
    ]
    chapter_name = _compact((context.get("chapter") or {}).get("chapter_name") if isinstance(context.get("chapter"), Mapping) else "")
    if chapter_name:
        clauses.append(f"PartOfChapter({section},{_symbol(chapter_name, prefix='chapter')})")
    for term in (context.get("bm25") or {}).get("top_terms", [])[:10]:
        clauses.append(f"HasBagTerm({section},{_symbol(term.get('term'), prefix='term')})")
    for law in context.get("public_laws", [])[:8]:
        clauses.append(f"EnactedOrAmendedBy({section},{_symbol(law, prefix='public_law')})")
    for cite in context.get("usc_citations", [])[:8]:
        clauses.append(f"ReferencesUSC({section},{_symbol(cite, prefix='usc_ref')})")
    if op == "P":
        clauses.append(f"∀a((SubjectTo(a,{section}) ∧ FederalActorOrPerson(a)) → P(◇ExerciseRightOrAuthority(a,{section})))")
    elif op == "F":
        clauses.append(f"∀a((SubjectTo(a,{section}) ∧ FederalActorOrPerson(a)) → F(◇Violate(a,{section})))")
    else:
        clauses.append(f"∀a((SubjectTo(a,{section}) ∧ FederalActorOrPerson(a)) → O(□ComplyWith(a,{section})))")
    return "(" + " ∧ ".join(_unique(clauses)) + ")"


def _make_dcec(row: Mapping[str, Any], op: str, context: Mapping[str, Any]) -> str:
    section = _symbol(_section_ref(row), prefix="usc_section")
    statements = [f"(section {section})", f"(title {section} usc_title_{_symbol(row.get('title_number'), prefix='title')})"]
    for term in (context.get("bm25") or {}).get("top_terms", [])[:10]:
        statements.append(f"(salient_term {section} {_symbol(term.get('term'), prefix='term')})")
    for law in context.get("public_laws", [])[:6]:
        statements.append(f"(source_public_law {section} {_symbol(law, prefix='public_law')})")
    statements.append(f"(forall agent (implies (subject_to agent {section}) ({op} (always (comply_with agent {section})))))")
    return "(and " + " ".join(_unique(statements)) + ")"


def _make_flogic(row: Mapping[str, Any], op: str, context: Mapping[str, Any]) -> Dict[str, Any]:
    object_id = _symbol(_section_ref(row), prefix="usc_section")
    set_methods: Dict[str, List[str]] = {}
    for rel_type, method in _RELATION_METHODS.items():
        values = [
            _compact(item.get("target_symbol"))
            for item in (context.get("relationships") or {}).get(rel_type, [])[:16]
        ]
        if values:
            set_methods[method] = _unique(values)
    set_methods["hasBagTerm"] = [
        json.dumps(item.get("term"), ensure_ascii=False)
        for item in (context.get("bm25") or {}).get("top_terms", [])[:20]
    ]
    set_methods["sourcePublicLaw"] = [
        json.dumps(item, ensure_ascii=False)
        for item in list(context.get("public_laws") or [])[:12]
    ]
    scalar_methods = {
        "identifier": json.dumps(_section_ref(row), ensure_ascii=False),
        "ipfs_cid": json.dumps(_compact(row.get("ipfs_cid")), ensure_ascii=False),
        "source_url": json.dumps(_compact(row.get("source_url")), ensure_ascii=False),
        "title_number": json.dumps(_compact(row.get("title_number")), ensure_ascii=False),
        "section_number": json.dumps(_compact(row.get("section_number")), ensure_ascii=False),
        "norm_operator": json.dumps(op, ensure_ascii=False),
        "norm_type": json.dumps(_operator_label(op), ensure_ascii=False),
    }
    frame_json = {
        "object_id": object_id,
        "isa": "UnitedStatesCodeSection",
        "scalar_methods": scalar_methods,
        "set_methods": {k: v for k, v in set_methods.items() if v},
    }
    ergo_lines = [
        "FederalLaw :: LegalNorm.",
        "UnitedStatesCodeSection :: FederalLaw.",
        "UnitedStatesCodeTitle :: FederalLaw.",
        f"{object_id}["
        + ", ".join([f"{k} -> {v}" for k, v in scalar_methods.items()])
        + (
            (", " if scalar_methods and any(set_methods.values()) else "")
            + ", ".join(f"{k} ->> {{{','.join(v)}}}" for k, v in set_methods.items() if v)
        )
        + "] : UnitedStatesCodeSection.",
        "requires_compliance(?Agent, ?Section) :- ?Section : UnitedStatesCodeSection, subject_to(?Agent, ?Section).",
        "cites_public_law(?Section, ?Law) :- ?Section : UnitedStatesCodeSection, ?Section[sourcePublicLaw ->> ?Law].",
    ]
    return {
        "ontology_name": f"United States Code {_section_ref(row)}",
        "object_id": object_id,
        "ontology_version": "uscode-logic-ontology-v1",
        "frame": frame_json,
        "bm25_top_terms": (context.get("bm25") or {}).get("top_terms", []),
        "ergo_program": "\n".join(ergo_lines),
    }


def _logic_generation_prompt(
    row: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    deterministic_tdfol: str,
    deterministic_dcec: str,
    deterministic_flogic: Mapping[str, Any],
    max_chars: int,
) -> str:
    text = _compact(row.get("text"))
    statute_text = text[:max_chars] if max_chars > 0 else text
    prompt_payload = {
        "task": "Convert a U.S. Code statute section into formal logic artifacts.",
        "requirements": [
            "Use the statute text as the primary source of obligations, permissions, prohibitions, definitions, conditions, exceptions, actors, objects, deadlines, and cross references.",
            "Use metadata, BM25 terms, and knowledge-graph relationships only as grounding context; do not invent requirements not supported by the statute text.",
            "Return strict JSON only. No prose, markdown, or code fences.",
            "If the statute is definitional or structural, represent definitions/classifications instead of forcing a duty.",
            "Use stable symbols compatible with first-order/deontic/frame-logic downstream tooling.",
        ],
        "required_json_schema": {
            "norm_operator": "O | P | F | DEF | MIXED",
            "norm_type": "obligation | permission | prohibition | definition | mixed",
            "fol_json": {
                "schema_version": "uscode-fol-v1",
                "section": "official citation",
                "predicates": ["predicate names"],
                "candidate_axioms": ["first-order logic formulas derived from the statute text"],
                "textual_support": [
                    {"quote": "short statute phrase", "supports": "axiom or predicate name"}
                ],
            },
            "deontic_json": {
                "operator": "O | P | F | DEF | MIXED",
                "norm_type": "obligation | permission | prohibition | definition | mixed",
                "actors": ["regulated actors/entities"],
                "actions": ["regulated actions"],
                "conditions": ["conditions, exceptions, or temporal triggers"],
            },
            "deontic_temporal_fol": "single TDFOL formula or conjunction",
            "deontic_cognitive_event_calculus": "single DCEC expression",
            "frame_logic_json": {
                "ontology_name": "name",
                "object_id": "stable symbol",
                "ontology_version": "uscode-logic-ontology-v1",
                "frame": {
                    "object_id": "stable symbol",
                    "isa": "UnitedStatesCodeSection",
                    "scalar_methods": {},
                    "set_methods": {}
                },
                "ergo_program": "Ergo/Flora-2 style frame logic rules"
            },
            "confidence": 0.0,
            "notes": "brief caveats about ambiguity or missing context",
        },
        "metadata": {
            "ipfs_cid": _compact(row.get("ipfs_cid")),
            "source_url": _compact(row.get("source_url")),
            "official_cite": _section_ref(row),
            "title_number": _compact(row.get("title_number")),
            "section_number": _compact(row.get("section_number")),
            "title": _compact(row.get("law_name")),
            "title_name": _compact(row.get("title_name")),
            "jsonld_id": _compact(row.get("jsonld_id")),
        },
        "kg_bm25_context": context,
        "deterministic_scaffold_for_style_only": {
            "deontic_temporal_fol": deterministic_tdfol,
            "deontic_cognitive_event_calculus": deterministic_dcec,
            "frame_logic_json": deterministic_flogic,
        },
        "statute_text": statute_text,
    }
    return (
        "You are a formal-methods legal knowledge-engineering assistant. "
        "Convert the supplied statute into machine-readable logic. "
        "Return only a JSON object matching required_json_schema.\n\n"
        + json.dumps(_json_safe(prompt_payload), ensure_ascii=False, indent=2)
    )


def _generate_llm_logic(
    row: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    deterministic_tdfol: str,
    deterministic_dcec: str,
    deterministic_flogic: Mapping[str, Any],
    max_chars: int,
    llm_provider: str,
    llm_model: str,
    llm_timeout: float,
    llm_max_new_tokens: int,
    llm_temperature: float,
    llm_trace_dir: str,
    llm_retries: int,
    llm_fallback_models: str,
) -> Dict[str, Any]:
    from ipfs_datasets_py import llm_router

    prompt = _logic_generation_prompt(
        row,
        context=context,
        deterministic_tdfol=deterministic_tdfol,
        deterministic_dcec=deterministic_dcec,
        deterministic_flogic=deterministic_flogic,
        max_chars=max_chars,
    )
    response = ""
    parsed: Dict[str, Any] | None = None
    last_error: Exception | None = None
    attempts = max(1, int(llm_retries or 0) + 1)
    model_candidates = [llm_model or ""]
    model_candidates.extend(
        item.strip()
        for item in str(llm_fallback_models or "").split(",")
        if item.strip() and item.strip() not in model_candidates
    )
    active_model = llm_model or ""
    for model_candidate in model_candidates:
        active_model = model_candidate
        for attempt in range(attempts):
            request_prompt = prompt
            if attempt > 0:
                request_prompt = (
                    "Return strict valid JSON only. Repair the following malformed JSON-like "
                    "formal-logic response so it has exactly these required top-level keys: "
                    "norm_operator, norm_type, fol_json, deontic_json, deontic_temporal_fol, "
                    "deontic_cognitive_event_calculus, frame_logic_json, confidence, notes. "
                    "frame_logic_json must contain ergo_program. Do not add markdown.\n\n"
                    f"{response}"
                )
            try:
                response = llm_router.generate_text(
                    request_prompt,
                    provider=llm_provider or None,
                    model_name=model_candidate or None,
                    allow_local_fallback=False,
                    max_new_tokens=int(llm_max_new_tokens),
                    temperature=float(llm_temperature),
                    timeout=float(llm_timeout),
                    trace=bool(llm_trace_dir),
                    trace_dir=llm_trace_dir or None,
                )
            except Exception as exc:
                last_error = exc
                if "usage limit" in str(exc).lower() or "quota" in str(exc).lower():
                    break
                continue
            try:
                candidate = _normalize_llm_payload(_extract_json_object(response))
                frame_logic = candidate.get("frame_logic_json")
                if not isinstance(frame_logic, Mapping):
                    raise ValueError("LLM response missing frame_logic_json object")
                if "ergo_program" not in frame_logic:
                    raise ValueError("LLM frame_logic_json missing ergo_program")
                fol_payload = candidate.get("fol_json")
                if not isinstance(fol_payload, Mapping):
                    raise ValueError("LLM response missing fol_json object")
                tdfol = _compact(candidate.get("deontic_temporal_fol"))
                dcec = _compact(candidate.get("deontic_cognitive_event_calculus"))
                if not tdfol or not dcec:
                    raise ValueError("LLM response missing deontic_temporal_fol or deontic_cognitive_event_calculus")
                parsed = candidate
                break
            except Exception as exc:
                last_error = exc
        if parsed is not None:
            break
    if parsed is None:
        raise ValueError(f"LLM response could not be parsed/validated after {attempts} attempt(s): {last_error}")
    frame_logic = parsed.get("frame_logic_json")
    fol_payload = parsed.get("fol_json")
    deontic_payload = parsed.get("deontic_json")
    if not isinstance(deontic_payload, Mapping):
        deontic_payload = {
            "operator": _compact(parsed.get("norm_operator")) or "MIXED",
            "norm_type": _compact(parsed.get("norm_type")) or "mixed",
        }
    tdfol = _compact(parsed.get("deontic_temporal_fol"))
    dcec = _compact(parsed.get("deontic_cognitive_event_calculus"))
    return {
        "fol_payload": dict(fol_payload),
        "deontic_payload": dict(deontic_payload),
        "tdfol": tdfol,
        "dcec": dcec,
        "flogic": dict(frame_logic),
        "norm_operator": _compact(parsed.get("norm_operator")) or _compact(deontic_payload.get("operator")) or "MIXED",
        "norm_type": _compact(parsed.get("norm_type")) or _compact(deontic_payload.get("norm_type")) or "mixed",
        "llm_model": active_model,
        "llm_prompt_cid": cid_for_obj({"prompt": prompt}),
        "llm_response_cid": cid_for_obj({"response": response}),
        "llm_response_json": parsed,
    }


def _build_row(
    row: Mapping[str, Any],
    *,
    bm25_by_cid: Mapping[str, Mapping[str, Any]],
    relationships_by_source: Mapping[str, List[Mapping[str, Any]]],
    zkp_prover: ZKPProver,
    zkp_verifier: ZKPVerifier,
    zkp_backend: str,
    zkp_circuit_version: int,
    max_chars: int,
    logic_source: str,
    require_llm: bool,
    llm_provider: str,
    llm_model: str,
    llm_timeout: float,
    llm_max_new_tokens: int,
    llm_temperature: float,
    llm_trace_dir: str,
    llm_retries: int,
    llm_fallback_models: str,
) -> Dict[str, Any]:
    cid = _compact(row.get("ipfs_cid"))
    text = _compact(row.get("text"))
    input_text = text[:max_chars] if max_chars > 0 else text
    op = _norm_operator(input_text)
    context = _logic_context(row, bm25_by_cid=bm25_by_cid, relationships_by_source=relationships_by_source)
    tdfol = _make_tdfol(row, op, context)
    dcec = _make_dcec(row, op, context)
    flogic = _make_flogic(row, op, context)
    fol_payload = {
        "schema_version": "uscode-fol-v1",
        "section": _section_ref(row),
        "predicates": [
            "FederalStatuteSection",
            "PartOfTitle",
            "SubjectTo",
            "FederalActorOrPerson",
            "ComplyWith",
        ],
        "candidate_axioms": [tdfol],
    }
    deontic_payload = {"operator": op, "norm_type": _operator_label(op)}
    generation_method = "deterministic_scaffold"
    llm_prompt_cid = ""
    llm_response_cid = ""
    llm_response_json: Dict[str, Any] = {}
    llm_error = ""
    if logic_source == "llm_router":
        try:
            generated = _generate_llm_logic(
                row,
                context=context,
                deterministic_tdfol=tdfol,
                deterministic_dcec=dcec,
                deterministic_flogic=flogic,
                max_chars=max_chars,
                llm_provider=llm_provider,
                llm_model=llm_model,
                llm_timeout=llm_timeout,
                llm_max_new_tokens=llm_max_new_tokens,
                llm_temperature=llm_temperature,
                llm_trace_dir=llm_trace_dir,
                llm_retries=llm_retries,
                llm_fallback_models=llm_fallback_models,
            )
            fol_payload = generated["fol_payload"]
            deontic_payload = generated["deontic_payload"]
            tdfol = generated["tdfol"]
            dcec = generated["dcec"]
            flogic = generated["flogic"]
            op = generated["norm_operator"]
            llm_model = generated.get("llm_model") or llm_model
            llm_prompt_cid = generated["llm_prompt_cid"]
            llm_response_cid = generated["llm_response_cid"]
            llm_response_json = generated["llm_response_json"]
            generation_method = "llm_router"
        except Exception as exc:
            llm_error = f"{type(exc).__name__}: {exc}"
            if require_llm:
                raise
            generation_method = "deterministic_scaffold_after_llm_error"
    norm_type = _compact(deontic_payload.get("norm_type")) or _operator_label(op)
    logic_bundle = {
        "schema_version": "uscode-logic-proof-artifacts-v1",
        "source_ipfs_cid": cid,
        "identifier": _section_ref(row),
        "formalization_scope": "machine_generated_candidate",
        "logic_generation_method": generation_method,
        "llm_provider": llm_provider if generation_method == "llm_router" else "",
        "llm_model": llm_model if generation_method == "llm_router" else "",
        "llm_prompt_cid": llm_prompt_cid,
        "llm_response_cid": llm_response_cid,
        "fol": fol_payload,
        "deontic_temporal_fol": tdfol,
        "deontic_cognitive_event_calculus": dcec,
        "frame_logic": flogic,
        "kg_context": context,
    }
    logic_bundle_cid = cid_for_obj(logic_bundle)
    proof = zkp_prover.generate_proof(
        theorem=f"FormalizationBundle({cid},{logic_bundle_cid})",
        private_axioms=[
            f"tdfol={tdfol}",
            f"dcec={dcec}",
            f"flogic={flogic.get('object_id') or (flogic.get('frame') or {}).get('object_id')}",
            f"kg_context_cid={cid_for_obj(context)}",
            f"logic_generation_method={generation_method}",
        ],
        metadata={
            "ruleset_id": "uscode-formalization-v1",
            "circuit_version": int(zkp_circuit_version),
            "certificate_scope": "conversion_attestation_not_legal_validity",
            "source_ipfs_cid": cid,
            "logic_bundle_cid": logic_bundle_cid,
        },
    )
    proof_dict = proof.to_dict()
    try:
        proof_verified = bool(zkp_verifier.verify_proof(proof))
    except Exception:
        proof_verified = False
    return {
        "ipfs_cid": cid,
        "source_url": _compact(row.get("source_url")),
        "identifier": _section_ref(row),
        "official_cite": _section_ref(row),
        "title_number": _compact(row.get("title_number")),
        "section_number": _compact(row.get("section_number")),
        "title": _compact(row.get("law_name")),
        "title_name": _compact(row.get("title_name")),
        "jsonld_id": _compact(row.get("jsonld_id")),
        "logic_bundle_cid": logic_bundle_cid,
        "formalization_scope": "machine_generated_candidate",
        "fol_status": "success",
        "fol_json": _json_dumps(fol_payload),
        "deontic_status": "success",
        "deontic_json": _json_dumps(deontic_payload),
        "ontology_version": "uscode-logic-ontology-v1",
        "kg_context_json": _json_dumps(context),
        "kg_context_cid": cid_for_obj(context),
        "bm25_logic_terms_json": _json_dumps((context.get("bm25") or {}).get("top_terms") or []),
        "deontic_temporal_fol": tdfol,
        "enhanced_tdfol_formula": tdfol,
        "deontic_cognitive_event_calculus": dcec,
        "enhanced_dcec_formula": dcec,
        "frame_logic_json": _json_dumps(flogic),
        "enhanced_frame_logic_json": _json_dumps(flogic),
        "frame_logic_ergo": _compact(flogic.get("ergo_program")),
        "norm_operator": op,
        "norm_type": norm_type,
        "logic_generation_method": generation_method,
        "llm_provider": llm_provider if generation_method == "llm_router" else "",
        "llm_model": llm_model if generation_method == "llm_router" else "",
        "llm_prompt_cid": llm_prompt_cid,
        "llm_response_cid": llm_response_cid,
        "llm_response_json": _json_dumps(llm_response_json),
        "llm_error": llm_error,
        "zkp_backend": zkp_backend,
        "zkp_security_note": (
            "Groth16 BN254 proof generated by bundled Rust backend"
            if zkp_backend.lower() == "groth16"
            else "simulated educational certificate; not cryptographically secure"
        ),
        "zkp_certificate_cid": cid_for_obj(proof_dict),
        "zkp_certificate_json": _json_dumps(proof_dict),
        "zkp_verified": proof_verified,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _write_parquet(path: Path, rows: List[Dict[str, Any]]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def _write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(manifest), indent=2, ensure_ascii=False), encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build U.S. Code formal logic and proof artifacts.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--bm25-index", required=True)
    parser.add_argument("--knowledge-graph-relationships", required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--max-chars", type=int, default=3200)
    parser.add_argument("--checkpoint-every", type=int, default=250)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--zkp-backend", default="groth16", choices=["simulated", "groth16"])
    parser.add_argument("--zkp-circuit-version", type=int, default=1)
    parser.add_argument(
        "--logic-source",
        default="deterministic_scaffold",
        choices=["deterministic_scaffold", "llm_router"],
        help="Use llm_router to derive logic from statute text, or the deterministic scaffold.",
    )
    parser.add_argument(
        "--require-llm",
        action="store_true",
        help="Fail a row instead of falling back when llm_router generation or JSON parsing fails.",
    )
    parser.add_argument("--llm-provider", default="codex_cli")
    parser.add_argument("--llm-model", default="gpt-5.3-codex-spark")
    parser.add_argument("--llm-fallback-models", default="")
    parser.add_argument("--llm-timeout", type=float, default=240.0)
    parser.add_argument("--llm-max-new-tokens", type=int, default=4096)
    parser.add_argument("--llm-temperature", type=float, default=0.0)
    parser.add_argument("--llm-trace-dir", default="")
    parser.add_argument("--llm-retries", type=int, default=2)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    import pyarrow.parquet as pq

    logging.getLogger("ipfs_datasets_py.logic.zkp.backends.groth16_ffi").setLevel(logging.WARNING)
    input_path = Path(args.input).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / "laws_logic_proof_artifacts.parquet"
    manifest_path = output_root / "manifest.json"

    rows = pq.read_table(input_path).to_pylist()
    rows = [dict(row) for row in rows if _compact(row.get("ipfs_cid"))]
    if args.start_index and args.start_index > 0:
        rows = rows[int(args.start_index) :]
    if args.limit and args.limit > 0:
        rows = rows[: int(args.limit)]
    bm25_by_cid = _load_lookup(args.bm25_index, ["document_id", "id"])
    relationships_by_source = _load_relationships(args.knowledge_graph_relationships)

    zkp_backend = str(args.zkp_backend or "groth16").lower()
    zkp_circuit_version = int(args.zkp_circuit_version or 1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        zkp_prover = ZKPProver(backend=zkp_backend, enable_caching=True)
        zkp_verifier = ZKPVerifier(backend=zkp_backend)
    if zkp_backend == "groth16":
        backend_instance = zkp_prover.get_backend_instance()
        if hasattr(backend_instance, "ensure_setup"):
            backend_instance.ensure_setup(version=zkp_circuit_version)

    out_rows: List[Dict[str, Any]] = []
    completed: set[str] = set()
    if output_path.exists() and not args.no_resume:
        try:
            out_rows = pq.read_table(output_path).to_pylist()
            if str(args.logic_source) == "llm_router":
                completed = {
                    _compact(row.get("ipfs_cid"))
                    for row in out_rows
                    if _compact(row.get("ipfs_cid")) and row.get("logic_generation_method") == "llm_router"
                }
                out_rows = [row for row in out_rows if _compact(row.get("ipfs_cid")) in completed]
            else:
                completed = {_compact(row.get("ipfs_cid")) for row in out_rows if _compact(row.get("ipfs_cid"))}
        except Exception:
            out_rows = []
            completed = set()
    failures: List[Dict[str, str]] = []
    started_at = datetime.now(timezone.utc).isoformat()
    checkpoint_every = max(1, int(args.checkpoint_every or 1))

    def _manifest(status: str) -> Dict[str, Any]:
        return {
            "schema_version": "uscode-logic-proof-artifacts-v1",
            "input": str(input_path),
            "output_root": str(output_root),
            "logic_proof_artifacts": str(output_path),
            "source_row_count": len(rows),
            "artifact_row_count": len(out_rows),
            "completed_row_count": len(completed),
            "remaining_row_count": max(0, len(rows) - len(completed)),
            "failure_count": len(failures),
            "failures": failures[:50],
            "bm25_document_count": len(bm25_by_cid),
            "kg_relationship_source_count": len(relationships_by_source),
            "formalization_scope": "machine_generated_candidate",
            "logic_source": str(args.logic_source),
            "require_llm": bool(args.require_llm),
            "llm_provider": str(args.llm_provider or "") if str(args.logic_source) == "llm_router" else "",
            "llm_model": str(args.llm_model or "") if str(args.logic_source) == "llm_router" else "",
            "ontology_version": "uscode-logic-ontology-v1",
            "zkp_backend": zkp_backend,
            "zkp_circuit_version": zkp_circuit_version,
            "zkp_verified_count": sum(1 for row in out_rows if row.get("zkp_verified")),
            "llm_generated_count": sum(1 for row in out_rows if row.get("logic_generation_method") == "llm_router"),
            "llm_fallback_count": sum(1 for row in out_rows if str(row.get("logic_generation_method") or "").startswith("deterministic_scaffold")),
            "status": status,
            "started_at": started_at,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    _write_manifest(manifest_path, _manifest("running"))
    since_checkpoint = 0
    for index, row in enumerate(rows):
        cid = _compact(row.get("ipfs_cid"))
        if cid in completed:
            continue
        try:
            built = _build_row(
                row,
                bm25_by_cid=bm25_by_cid,
                relationships_by_source=relationships_by_source,
                zkp_prover=zkp_prover,
                zkp_verifier=zkp_verifier,
                zkp_backend=zkp_backend,
                zkp_circuit_version=zkp_circuit_version,
                max_chars=int(args.max_chars),
                logic_source=str(args.logic_source),
                require_llm=bool(args.require_llm),
                llm_provider=str(args.llm_provider or ""),
                llm_model=str(args.llm_model or ""),
                llm_timeout=float(args.llm_timeout),
                llm_max_new_tokens=int(args.llm_max_new_tokens),
                llm_temperature=float(args.llm_temperature),
                llm_trace_dir=str(args.llm_trace_dir or ""),
                llm_retries=int(args.llm_retries),
                llm_fallback_models=str(args.llm_fallback_models or ""),
            )
            out_rows.append(built)
            completed.add(cid)
        except Exception as exc:
            failures.append({"index": str(index), "ipfs_cid": cid, "error": f"{type(exc).__name__}: {exc}"})
        since_checkpoint += 1
        if since_checkpoint >= checkpoint_every:
            if out_rows:
                _write_parquet(output_path, out_rows)
            _write_manifest(manifest_path, _manifest("running"))
            since_checkpoint = 0

    _write_parquet(output_path, out_rows)
    manifest = _manifest("complete" if not failures else "complete_with_failures")
    _write_manifest(manifest_path, manifest)
    if args.json:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
    else:
        print(f"Rows: {len(out_rows)} / {len(rows)}")
        print(f"Failures: {len(failures)}")
        print(f"Output: {output_path}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
