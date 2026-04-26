#!/usr/bin/env python3
"""Build Portland City Code formal-logic and proof-certificate artifacts."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
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

from ipfs_datasets_py.logic.deontic import DeonticConverter  # noqa: E402
from ipfs_datasets_py.logic.flogic import FLogicClass, FLogicFrame, FLogicOntology  # noqa: E402
from ipfs_datasets_py.logic.fol import FOLConverter  # noqa: E402
from ipfs_datasets_py.logic.TDFOL.nl.llm import (  # noqa: E402
    build_conversion_prompt,
    get_operator_hints_for_text,
)
from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier  # noqa: E402
from ipfs_datasets_py.llm_router import generate_text  # noqa: E402
from ipfs_datasets_py.utils.cid_utils import cid_for_obj  # noqa: E402


_WS_RE = re.compile(r"\s+")
_IDENT_RE = re.compile(r"[^A-Za-z0-9_]+")
_STOP_TERMS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "may",
    "of",
    "or",
    "s",
    "shall",
    "that",
    "the",
    "this",
    "to",
    "will",
    "with",
}
_RELATION_METHODS = {
    "PART_OF_TITLE": "partOfTitle",
    "PART_OF_CHAPTER": "partOfChapter",
    "REFERENCES_LEGAL_AUTHORITY": "referencesAuthority",
    "REFERENCES_CODE_SECTION": "referencesCodeSection",
    "REFERENCES_SECTION_CID": "referencesSection",
    "AMENDED_BY": "amendedBy",
    "MENTIONS_ACTOR": "mentionsActor",
    "IMPOSES_DUTY_ON": "imposesDutyOn",
    "GRANTS_AUTHORITY_TO": "grantsAuthorityTo",
    "REGULATES_SUBJECT": "regulatesSubject",
    "GOVERNS_AUTHORIZATION": "governsAuthorization",
    "IMPOSES_DUTY": "imposesDuty",
    "GRANTS_AUTHORITY": "grantsAuthority",
    "PROHIBITS": "prohibits",
    "DEFINES": "defines",
    "DEFINES_TERM": "definesTerm",
}
_NORM_RELATIONS = {"IMPOSES_DUTY", "GRANTS_AUTHORITY", "PROHIBITS", "DEFINES"}


@dataclass
class LogicContextArtifacts:
    """External KG/BM25/ontology context used to ground formal exports."""

    entity_by_id: Dict[str, Dict[str, Any]]
    relationships_by_source: Dict[str, List[Dict[str, Any]]]
    bm25_by_cid: Dict[str, Dict[str, Any]]
    ontology: Dict[str, Any]
    existing_logic_by_cid: Dict[str, Dict[str, Any]]


def _compact(value: Any) -> str:
    return _WS_RE.sub(" ", str(value or "")).strip()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "to_dict"):
        try:
            return _json_safe(value.to_dict())
        except Exception:
            pass
    return str(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(_json_safe(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _section_ref(row: Mapping[str, Any]) -> str:
    identifier = _compact(row.get("identifier"))
    if identifier:
        return identifier
    return _compact(row.get("source_id")) or _compact(row.get("ipfs_cid")) or "Portland City Code section"


def _symbol(value: str, *, prefix: str = "section") -> str:
    cleaned = _IDENT_RE.sub("_", value).strip("_").lower()
    if not cleaned:
        cleaned = prefix
    if cleaned[0].isdigit():
        cleaned = f"{prefix}_{cleaned}"
    return cleaned[:120]


def _class_symbol(value: str, *, fallback: str = "Thing") -> str:
    cleaned = _IDENT_RE.sub("", str(value or "")).strip()
    return cleaned or fallback


def _parse_properties(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if value is None:
        return {}
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    except Exception:
        return {}


def _unique_preserve(values: Iterable[Any]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for value in values:
        text = _compact(value)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _entity_summary(entity_id: str, artifacts: Optional[LogicContextArtifacts]) -> Dict[str, Any]:
    entity = dict((artifacts.entity_by_id if artifacts else {}).get(entity_id) or {})
    props = _parse_properties(entity.get("properties_json"))
    label = _compact(entity.get("label")) or entity_id.rsplit(":", 1)[-1].replace("_", " ")
    entity_type = _compact(entity.get("type")) or "Thing"
    return {
        "id": entity_id,
        "symbol": _symbol(entity_id, prefix="entity"),
        "type": entity_type,
        "class": _class_symbol(entity_type),
        "label": label,
        "properties": props,
    }


def _top_bm25_terms(row: Mapping[str, Any], *, limit: int = 20) -> List[Dict[str, Any]]:
    freqs = row.get("term_frequencies")
    pairs: List[Dict[str, Any]] = []
    if freqs is None:
        return pairs
    try:
        iterable = freqs.tolist() if hasattr(freqs, "tolist") else list(freqs)
    except Exception:
        iterable = []
    for item in iterable:
        if isinstance(item, Mapping):
            term = _compact(item.get("term")).lower()
            tf = int(item.get("tf") or item.get("count") or 0)
        else:
            term = _compact(item).lower()
            tf = 1
        if not term or term in _STOP_TERMS or len(term) < 3 or term.isdigit():
            continue
        pairs.append({"term": term, "tf": tf})
    pairs.sort(key=lambda item: (-int(item.get("tf") or 0), str(item.get("term") or "")))
    return pairs[:limit]


def _logic_context_for_row(
    row: Mapping[str, Any],
    artifacts: Optional[LogicContextArtifacts],
) -> Dict[str, Any]:
    source_cid = _compact(row.get("ipfs_cid"))
    rels = list((artifacts.relationships_by_source if artifacts else {}).get(source_cid) or [])
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for rel in rels:
        rel_type = _compact(rel.get("type"))
        target = _compact(rel.get("target"))
        if not rel_type or not target:
            continue
        grouped.setdefault(rel_type, []).append(
            {
                "id": _compact(rel.get("id")),
                "target": target,
                "target_symbol": _symbol(target, prefix="entity"),
                "target_entity": _entity_summary(target, artifacts),
                "properties": _parse_properties(rel.get("properties_json")),
            }
        )

    bm25_row = dict((artifacts.bm25_by_cid if artifacts else {}).get(source_cid) or {})
    section_entity = _entity_summary(source_cid, artifacts)
    context = {
        "source_ipfs_cid": source_cid,
        "ontology_version": _compact((artifacts.ontology if artifacts else {}).get("ontology_version"))
        or "unknown",
        "section_entity": section_entity,
        "relationships": grouped,
        "actors": _unique_preserve(
            item["target"] for key in ("MENTIONS_ACTOR", "IMPOSES_DUTY_ON", "GRANTS_AUTHORITY_TO") for item in grouped.get(key, [])
        ),
        "duty_actors": _unique_preserve(item["target"] for item in grouped.get("IMPOSES_DUTY_ON", [])),
        "authority_actors": _unique_preserve(item["target"] for item in grouped.get("GRANTS_AUTHORITY_TO", [])),
        "subjects": _unique_preserve(
            item["target"] for key in ("REGULATES_SUBJECT", "GOVERNS_AUTHORIZATION") for item in grouped.get(key, [])
        ),
        "referenced_sections": _unique_preserve(
            item["target"] for key in ("REFERENCES_SECTION_CID", "REFERENCES_CODE_SECTION") for item in grouped.get(key, [])
        ),
        "legal_authorities": _unique_preserve(item["target"] for item in grouped.get("REFERENCES_LEGAL_AUTHORITY", [])),
        "amendments": _unique_preserve(item["target"] for item in grouped.get("AMENDED_BY", [])),
        "norm_relations": {
            key: [item["target"] for item in grouped.get(key, [])]
            for key in sorted(_NORM_RELATIONS)
            if grouped.get(key)
        },
        "bm25": {
            "document_length": int(bm25_row.get("document_length") or 0),
            "unique_term_count": int(bm25_row.get("unique_term_count") or 0),
            "top_terms": _top_bm25_terms(bm25_row, limit=25),
            "k1": float(bm25_row.get("bm25_k1") or 0.0),
            "b": float(bm25_row.get("bm25_b") or 0.0),
            "avgdl": float(bm25_row.get("bm25_avgdl") or 0.0),
            "document_count": int(bm25_row.get("bm25_document_count") or 0),
        },
    }
    return context


def _relationship_targets(context: Mapping[str, Any], rel_type: str, *, limit: int = 8) -> List[str]:
    rels = ((context.get("relationships") or {}).get(rel_type) or [])[:limit]
    return [_compact(item.get("target_symbol")) for item in rels if _compact(item.get("target_symbol"))]


def _norm_operator(text: str) -> str:
    lower = text.lower()
    if re.search(r"\b(shall not|must not|may not|prohibit(?:ed|s)?|unlawful|forbidden)\b", lower):
        return "F"
    if re.search(r"\b(may|authorized|permitted|allowed|is entitled to|has the right)\b", lower):
        return "P"
    if re.search(r"\b(shall|must|required|will|duty|responsible|subject to)\b", lower):
        return "O"
    return "O"


def _operator_label(op: str) -> str:
    return {"O": "obligation", "P": "permission", "F": "prohibition"}.get(op, "obligation")


def _extract_llm_formula(response: str) -> str:
    lines = [line.strip() for line in str(response or "").splitlines() if line.strip()]
    for line in lines:
        if line.lower().startswith(("output:", "formula:", "tdfol:")):
            return line.split(":", 1)[1].strip()
        if _looks_like_tdfol(line):
            return line
    return lines[-1] if lines else ""


def _normalize_llm_formula(formula: str) -> str:
    text = str(formula or "").strip()
    text = re.sub(r"^\\\[\s*", "", text)
    text = re.sub(r"\s*\\\]$", "", text)
    text = re.sub(r"^\\\(\s*", "", text)
    text = re.sub(r"\s*\\\)$", "", text)
    text = re.sub(r"^\$\$\s*", "", text)
    text = re.sub(r"\s*\$\$$", "", text)
    replacements = {
        r"\forall": "∀",
        r"\exists": "∃",
        r"\rightarrow": "→",
        r"\to": "→",
        r"\land": "∧",
        r"\wedge": "∧",
        r"\lor": "∨",
        r"\vee": "∨",
        r"\neg": "¬",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = re.sub(r"\\mathrm\{([^{}]+)\}", r"\1", text)
    text = text.replace("\\,", " ")
    return _compact(text)


def _looks_like_tdfol(formula: str) -> bool:
    text = _normalize_llm_formula(formula)
    if not text:
        return False
    if len(text) > 1800:
        return False
    if text.startswith(("-", "*", "#")):
        return False
    if text.count("(") != text.count(")"):
        return False
    lower = text.lower()
    bad_fragments = [
        "universal quantifier",
        "existential quantifier",
        "logical operators",
        "temporal operators",
        "deontic operators",
        "modal operators",
        "examples:",
        "tdfol is",
        "step ",
        "in this translation",
        "formula:",
        "sentence:",
        "tax deduction",
    ]
    if any(fragment in lower for fragment in bad_fragments):
        return False
    return bool(
        re.search(
            r"[∀∃→∧∨¬]|(?:^|[^A-Za-z])(?:O|P|F|G|X|K|B)\s*\(?|\b(?:forall|exists)\s*\(",
            text,
            flags=re.IGNORECASE,
        )
    )


def _llm_assist_tdfol(
    text: str,
    *,
    provider: str,
    model: str,
    max_chars: int,
    timeout: float,
) -> Dict[str, Any]:
    source = _compact(text)[:max_chars] if max_chars and max_chars > 0 else _compact(text)
    operator_hints = get_operator_hints_for_text(source)
    prompt = build_conversion_prompt(
        source,
        include_examples=True,
        complexity="advanced",
        operator_hints=operator_hints,
    )
    prompt = (
        "Return only one valid TDFOL formula. Do not explain. Do not define TDFOL.\n\n"
        f"{prompt}"
    )
    result: Dict[str, Any] = {
        "enabled": True,
        "provider": provider or "",
        "model": model or "",
        "operator_hints": operator_hints,
        "accepted": False,
        "formula": "",
        "raw_response": "",
        "error": "",
    }
    try:
        response = generate_text(
            prompt,
            provider=provider or None,
            model_name=model or None,
            max_tokens=256,
            max_new_tokens=128,
            temperature=0.1,
            timeout=timeout,
            allow_local_fallback=False,
        )
        raw = str(response or "").strip()
        candidate_text = raw
        if raw.startswith(prompt):
            candidate_text = raw[len(prompt) :].strip()
        formula = _normalize_llm_formula(_extract_llm_formula(candidate_text))
        result.update(
            {
                "raw_response": raw,
                "candidate_response": candidate_text,
                "formula": formula,
                "accepted": _looks_like_tdfol(formula),
            }
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _make_tdfol(
    row: Mapping[str, Any],
    op: str,
    context: Optional[Mapping[str, Any]] = None,
    base_formula: str = "",
) -> str:
    section = _symbol(_section_ref(row))
    clauses: List[str] = [f"MunicipalCodeSection({section})"]
    if base_formula and not base_formula.startswith("∀a:Agent (SubjectTo"):
        clauses.append(f"PriorLLMFormalization({section})")

    if context:
        for actor in [_symbol(item, prefix="actor") for item in context.get("actors", [])[:8]]:
            clauses.append(f"LegalActor({actor}) ∧ MentionedIn({actor},{section})")
        for actor in [_symbol(item, prefix="actor") for item in context.get("duty_actors", [])[:8]]:
            clauses.append(f"DutyAppliesTo({section},{actor})")
        for actor in [_symbol(item, prefix="actor") for item in context.get("authority_actors", [])[:8]]:
            clauses.append(f"AuthorityGrantedTo({section},{actor})")
        for subject in [_symbol(item, prefix="subject") for item in context.get("subjects", [])[:8]]:
            clauses.append(f"RegulatesSubject({section},{subject})")
        for ref in [_symbol(item, prefix="ref") for item in context.get("referenced_sections", [])[:8]]:
            clauses.append(f"DependsOn({section},{ref})")
        for authority in [_symbol(item, prefix="authority") for item in context.get("legal_authorities", [])[:6]]:
            clauses.append(f"ReferencesAuthority({section},{authority})")
        for amendment in [_symbol(item, prefix="amendment") for item in context.get("amendments", [])[:6]]:
            clauses.append(f"AmendedBy({section},{amendment})")
        for term in (context.get("bm25") or {}).get("top_terms", [])[:10]:
            clauses.append(f"HasBagTerm({section},{_symbol(term.get('term'), prefix='term')})")

    if context and context.get("duty_actors"):
        clauses.append(f"∀a((LegalActor(a) ∧ DutyAppliesTo({section},a)) → O(□ComplyWith(a,{section})))")
    elif op == "O":
        clauses.append(f"∀a:Agent (SubjectTo(a,{section}) → O(□(ComplyWith(a,{section}))))")
    if context and context.get("authority_actors"):
        clauses.append(f"∀a((LegalActor(a) ∧ AuthorityGrantedTo({section},a)) → P(◇ExerciseAuthority(a,{section})))")
    elif op == "P":
        clauses.append(f"∀a:Agent (SubjectTo(a,{section}) → P(□(ComplyWith(a,{section}))))")
    if context and (context.get("norm_relations") or {}).get("PROHIBITS"):
        clauses.append(f"∀a((LegalActor(a) ∧ SubjectTo(a,{section})) → F(◇Violate(a,{section})))")
    elif op == "F":
        clauses.append(f"∀a:Agent (SubjectTo(a,{section}) → F(□(ComplyWith(a,{section}))))")
    return "(" + " ∧ ".join(_unique_preserve(clauses)) + ")"


def _make_dcec(row: Mapping[str, Any], op: str, context: Optional[Mapping[str, Any]] = None) -> str:
    section = _symbol(_section_ref(row))
    statements: List[str] = [f"(section {section})"]
    if context:
        for actor in [_symbol(item, prefix="actor") for item in context.get("actors", [])[:8]]:
            statements.append(f"(actor_mentioned_in {actor} {section})")
        for subject in [_symbol(item, prefix="subject") for item in context.get("subjects", [])[:8]]:
            statements.append(f"(regulates_subject {section} {subject})")
        for ref in [_symbol(item, prefix="ref") for item in context.get("referenced_sections", [])[:8]]:
            statements.append(f"(depends_on {section} {ref})")
        for term in (context.get("bm25") or {}).get("top_terms", [])[:10]:
            statements.append(f"(salient_term {section} {_symbol(term.get('term'), prefix='term')})")
        for actor in [_symbol(item, prefix="actor") for item in context.get("duty_actors", [])[:8]]:
            statements.append(f"(O (always (holds_at (duty_to_comply {actor} {section}) t)))")
        for actor in [_symbol(item, prefix="actor") for item in context.get("authority_actors", [])[:8]]:
            statements.append(f"(P (eventually (happens (exercise_authority {actor} {section}) t)))")
    statements.append(
        f"(forall agent (implies (subject_to agent {section}) ({op} (always (comply_with agent {section})))))"
    )
    return "(and " + " ".join(_unique_preserve(statements)) + ")"


def _make_flogic(
    row: Mapping[str, Any],
    op: str,
    context: Optional[Mapping[str, Any]] = None,
    ontology_payload: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    section_ref = _section_ref(row)
    object_id = _symbol(section_ref, prefix="portland_code_section")
    scalar_methods = {
        "identifier": json.dumps(section_ref, ensure_ascii=False),
        "ipfs_cid": json.dumps(_compact(row.get("ipfs_cid")), ensure_ascii=False),
        "source_url": json.dumps(_compact(row.get("source_url") or row.get("url")), ensure_ascii=False),
        "jurisdiction": '"City of Portland, Oregon"',
        "state_code": '"OR"',
        "gnis": '"2411471"',
        "norm_operator": json.dumps(op, ensure_ascii=False),
        "norm_type": json.dumps(_operator_label(op), ensure_ascii=False),
    }
    set_methods: Dict[str, List[str]] = {}
    frames: List[FLogicFrame] = []
    classes_by_id: Dict[str, FLogicClass] = {
        "LegalNorm": FLogicClass("LegalNorm"),
        "MunicipalLaw": FLogicClass("MunicipalLaw", superclasses=["LegalNorm"]),
        "CityCodeSection": FLogicClass("CityCodeSection", superclasses=["MunicipalLaw"]),
        "PortlandCityCodeSection": FLogicClass("PortlandCityCodeSection", superclasses=["CityCodeSection"]),
    }
    if ontology_payload:
        for cls in ontology_payload.get("classes") or []:
            if not isinstance(cls, Mapping):
                continue
            class_id = _class_symbol(cls.get("id"))
            parent = _class_symbol(cls.get("parent") or "")
            supers = [parent] if parent and parent != class_id else []
            classes_by_id[class_id] = FLogicClass(class_id, superclasses=supers)

    if context:
        relationship_groups = context.get("relationships") or {}
        for rel_type, method in _RELATION_METHODS.items():
            values = [
                _symbol(item.get("target"), prefix="entity")
                for item in relationship_groups.get(rel_type, [])[:16]
                if _compact(item.get("target"))
            ]
            if values:
                set_methods[method] = _unique_preserve(values)
        term_values = [
            json.dumps(item.get("term"), ensure_ascii=False)
            for item in (context.get("bm25") or {}).get("top_terms", [])[:20]
        ]
        if term_values:
            set_methods["hasBagTerm"] = _unique_preserve(term_values)
        for rels in relationship_groups.values():
            for item in rels[:12]:
                entity = item.get("target_entity") or {}
                entity_id = _compact(entity.get("id"))
                if not entity_id:
                    continue
                entity_symbol = _symbol(entity_id, prefix="entity")
                entity_class = _class_symbol(entity.get("class") or entity.get("type"))
                frames.append(
                    FLogicFrame(
                        object_id=entity_symbol,
                        scalar_methods={
                            "label": json.dumps(_compact(entity.get("label")) or entity_id, ensure_ascii=False),
                            "kg_id": json.dumps(entity_id, ensure_ascii=False),
                        },
                        isa=entity_class,
                    )
                )

    frame = FLogicFrame(
        object_id=object_id,
        scalar_methods=scalar_methods,
        set_methods=set_methods,
        isa="PortlandCityCodeSection",
    )
    ontology = FLogicOntology(
        name=f"Portland City Code {section_ref}",
        classes=list(classes_by_id.values()),
        frames=[frame] + frames,
        rules=[
            "requires_compliance(?Agent, ?Section) :- ?Section : PortlandCityCodeSection, ?Section[imposesDutyOn ->> ?Agent].",
            "authority_available(?Agent, ?Section) :- ?Section : PortlandCityCodeSection, ?Section[grantsAuthorityTo ->> ?Agent].",
            "regulated_entity(?Entity, ?Section) :- ?Section : PortlandCityCodeSection, ?Section[mentionsActor ->> ?Entity].",
            "regulated_entity(?Entity, ?Section) :- ?Section : PortlandCityCodeSection, ?Section[regulatesSubject ->> ?Entity].",
            "legal_dependency(?Section, ?Dependency) :- ?Section : PortlandCityCodeSection, ?Section[referencesSection ->> ?Dependency].",
        ],
    )
    return {
        "ontology_name": ontology.name,
        "object_id": object_id,
        "classes": [_json_safe(cls) for cls in ontology.classes],
        "frame": _json_safe(frame),
        "context_frames": [_json_safe(item) for item in frames],
        "ontology_version": _compact((context or {}).get("ontology_version")),
        "bm25_top_terms": (context or {}).get("bm25", {}).get("top_terms", []),
        "ergo_program": ontology.to_ergo_program(),
    }


def _conversion_output(result: Any) -> Dict[str, Any]:
    payload = result.to_dict() if hasattr(result, "to_dict") else {"output": str(result)}
    if getattr(result, "output", None) is not None:
        payload["output_structured"] = _json_safe(result.output)
    return _json_safe(payload)


def _read_parquet_rows(path: str) -> List[Dict[str, Any]]:
    if not path:
        return []
    import pyarrow.parquet as pq

    candidate = Path(path).expanduser().resolve()
    if not candidate.exists():
        raise FileNotFoundError(str(candidate))
    return pq.read_table(candidate).to_pylist()


def _load_context_artifacts(args: argparse.Namespace) -> LogicContextArtifacts:
    entity_by_id: Dict[str, Dict[str, Any]] = {}
    relationships_by_source: Dict[str, List[Dict[str, Any]]] = {}
    bm25_by_cid: Dict[str, Dict[str, Any]] = {}
    existing_logic_by_cid: Dict[str, Dict[str, Any]] = {}
    ontology: Dict[str, Any] = {}

    for row in _read_parquet_rows(str(args.knowledge_graph_entities or "")):
        entity_id = _compact(row.get("id"))
        if entity_id:
            entity_by_id[entity_id] = dict(row)
    for row in _read_parquet_rows(str(args.knowledge_graph_relationships or "")):
        source = _compact(row.get("source"))
        if source:
            relationships_by_source.setdefault(source, []).append(dict(row))
    for row in _read_parquet_rows(str(args.bm25_index or "")):
        cid = _compact(row.get("document_id")) or _compact(row.get("id"))
        if cid:
            bm25_by_cid[cid] = dict(row)
    for row in _read_parquet_rows(str(args.existing_logic_artifacts or "")):
        cid = _compact(row.get("ipfs_cid"))
        if cid:
            existing_logic_by_cid[cid] = dict(row)

    ontology_path = _compact(args.ontology)
    if ontology_path:
        candidate = Path(ontology_path).expanduser().resolve()
        if not candidate.exists():
            raise FileNotFoundError(str(candidate))
        ontology = json.loads(candidate.read_text(encoding="utf-8"))

    return LogicContextArtifacts(
        entity_by_id=entity_by_id,
        relationships_by_source=relationships_by_source,
        bm25_by_cid=bm25_by_cid,
        ontology=ontology,
        existing_logic_by_cid=existing_logic_by_cid,
    )


def _build_row(
    row: Mapping[str, Any],
    *,
    fol_converter: FOLConverter,
    deontic_converter: DeonticConverter,
    zkp_prover: ZKPProver,
    zkp_verifier: ZKPVerifier,
    zkp_backend: str,
    zkp_circuit_version: int,
    max_chars: int,
    llm_assisted: bool = False,
    llm_provider: str = "",
    llm_model: str = "",
    llm_max_chars: int = 1800,
    llm_timeout: float = 30.0,
    context_artifacts: Optional[LogicContextArtifacts] = None,
) -> Dict[str, Any]:
    text = _compact(row.get("text"))
    section_ref = _section_ref(row)
    source_cid = _compact(row.get("ipfs_cid"))
    input_text = text[:max_chars] if max_chars and max_chars > 0 else text
    op = _norm_operator(input_text)

    fol_status = "success"
    deontic_status = "success"
    fol_payload: Dict[str, Any]
    deontic_payload: Dict[str, Any]
    try:
        fol_payload = _conversion_output(fol_converter.convert(input_text))
    except Exception as exc:
        fol_status = "error"
        fol_payload = {"success": False, "errors": [f"{type(exc).__name__}: {exc}"]}
    try:
        deontic_payload = _conversion_output(deontic_converter.convert(input_text))
    except Exception as exc:
        deontic_status = "error"
        deontic_payload = {"success": False, "errors": [f"{type(exc).__name__}: {exc}"]}

    logic_context = _logic_context_for_row(row, context_artifacts)
    existing_logic = dict((context_artifacts.existing_logic_by_cid if context_artifacts else {}).get(source_cid) or {})
    existing_tdfol = _compact(existing_logic.get("deontic_temporal_fol"))
    tdfol_formula = existing_tdfol if existing_logic.get("llm_assisted_accepted") and existing_tdfol else _make_tdfol(row, op)
    llm_payload: Dict[str, Any] = {"enabled": False, "accepted": False}
    if existing_logic:
        llm_payload = {
            "enabled": bool(existing_logic.get("llm_assisted_enabled")),
            "accepted": bool(existing_logic.get("llm_assisted_accepted")),
            "provider": str(existing_logic.get("llm_assisted_provider") or ""),
            "model": str(existing_logic.get("llm_assisted_model") or ""),
            "formula": str(existing_logic.get("llm_assisted_formula") or ""),
            "reused_from_existing_logic_artifact": True,
        }
    if llm_assisted:
        llm_payload = _llm_assist_tdfol(
            input_text,
            provider=llm_provider,
            model=llm_model,
            max_chars=llm_max_chars,
            timeout=llm_timeout,
        )
        if llm_payload.get("accepted") and llm_payload.get("formula"):
            tdfol_formula = str(llm_payload["formula"])
    enhanced_tdfol_formula = _make_tdfol(row, op, context=logic_context, base_formula=tdfol_formula)
    dcec_formula = _make_dcec(row, op, context=logic_context)
    flogic_payload = _make_flogic(
        row,
        op,
        context=logic_context,
        ontology_payload=(context_artifacts.ontology if context_artifacts else {}),
    )

    logic_bundle = {
        "schema_version": "portland-logic-proof-artifacts-v2",
        "source_ipfs_cid": source_cid,
        "identifier": section_ref,
        "formalization_scope": "machine_generated_candidate",
        "fol": fol_payload,
        "base_deontic_temporal_fol": tdfol_formula,
        "deontic_temporal_fol": enhanced_tdfol_formula,
        "llm_assisted_tdfol": llm_payload,
        "deontic_cognitive_event_calculus": dcec_formula,
        "frame_logic": flogic_payload,
        "kg_context": logic_context,
        "ontology": {
            "version": logic_context.get("ontology_version"),
            "class_count": len((context_artifacts.ontology if context_artifacts else {}).get("classes") or []),
            "predicate_count": len((context_artifacts.ontology if context_artifacts else {}).get("predicates") or []),
        },
    }
    logic_bundle_cid = cid_for_obj(logic_bundle)

    theorem = f"FormalizationBundle({source_cid},{logic_bundle_cid})"
    private_axioms = [
        f"source_text_cid={_compact(row.get('text_cid'))}",
        f"fol={_json_dumps(fol_payload)[:8000]}",
        f"tdfol={enhanced_tdfol_formula}",
        f"dcec={dcec_formula}",
        f"flogic={flogic_payload['object_id']}",
        f"kg_context_cid={cid_for_obj(logic_context)}",
    ]
    proof = zkp_prover.generate_proof(
        theorem=theorem,
        private_axioms=private_axioms,
        metadata={
            "ruleset_id": "portland-city-code-formalization-v1",
            "circuit_version": int(zkp_circuit_version),
            "certificate_scope": "conversion_attestation_not_legal_validity",
            "source_ipfs_cid": source_cid,
            "logic_bundle_cid": logic_bundle_cid,
        },
    )
    proof_dict = proof.to_dict()
    proof_cid = cid_for_obj(proof_dict)
    try:
        proof_verified = bool(zkp_verifier.verify_proof(proof))
    except Exception:
        proof_verified = False

    return {
        "ipfs_cid": source_cid,
        "source_url": _compact(row.get("source_url") or row.get("url")),
        "identifier": section_ref,
        "title": _compact(row.get("title") or row.get("name")),
        "state_code": _compact(row.get("state_code")) or "OR",
        "gnis": _compact(row.get("gnis")) or "2411471",
        "text_cid": _compact(row.get("text_cid")),
        "logic_bundle_cid": logic_bundle_cid,
        "formalization_scope": "machine_generated_candidate",
        "fol_status": fol_status,
        "fol_json": _json_dumps(fol_payload),
        "deontic_status": deontic_status,
        "deontic_json": _json_dumps(deontic_payload),
        "ontology_version": logic_context.get("ontology_version", ""),
        "kg_context_json": _json_dumps(logic_context),
        "kg_context_cid": cid_for_obj(logic_context),
        "bm25_logic_terms_json": _json_dumps((logic_context.get("bm25") or {}).get("top_terms") or []),
        "base_deontic_temporal_fol": tdfol_formula,
        "deontic_temporal_fol": enhanced_tdfol_formula,
        "enhanced_tdfol_formula": enhanced_tdfol_formula,
        "llm_assisted_enabled": bool(llm_payload.get("enabled")),
        "llm_assisted_accepted": bool(llm_payload.get("accepted")),
        "llm_assisted_provider": str(llm_payload.get("provider") or ""),
        "llm_assisted_model": str(llm_payload.get("model") or ""),
        "llm_assisted_formula": str(llm_payload.get("formula") or ""),
        "llm_assisted_json": _json_dumps(llm_payload),
        "deontic_cognitive_event_calculus": dcec_formula,
        "enhanced_dcec_formula": dcec_formula,
        "frame_logic_json": _json_dumps(flogic_payload),
        "enhanced_frame_logic_json": _json_dumps(flogic_payload),
        "frame_logic_ergo": flogic_payload["ergo_program"],
        "norm_operator": op,
        "norm_type": _operator_label(op),
        "zkp_backend": zkp_backend,
        "zkp_security_note": (
            "Groth16 BN254 proof generated by bundled Rust backend"
            if zkp_backend.lower() in {"groth16", "g16"}
            else "simulated educational certificate; not cryptographically secure"
        ),
        "zkp_certificate_cid": proof_cid,
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
    parser = argparse.ArgumentParser(description="Build Portland City Code logic/proof parquet artifacts.")
    parser.add_argument("--input", required=True, help="Canonical Portland City Code parquet.")
    parser.add_argument("--output-root", required=True, help="Output directory.")
    parser.add_argument("--limit", type=int, default=0, help="Optional row limit for smoke tests.")
    parser.add_argument("--max-chars", type=int, default=4000, help="Max source text chars sent to NL converters per row.")
    parser.add_argument("--llm-assisted", action="store_true", help="Attempt LLM-assisted TDFOL conversion and accept only syntax-gated outputs.")
    parser.add_argument("--llm-provider", default="", help="LLM router provider, e.g. openai, hf_inference_api, local_hf.")
    parser.add_argument("--llm-model", default="", help="LLM model name for the selected provider.")
    parser.add_argument("--llm-max-chars", type=int, default=1800, help="Max source text chars sent to the LLM assist prompt.")
    parser.add_argument("--llm-timeout", type=float, default=30.0, help="LLM assist timeout in seconds.")
    parser.add_argument("--checkpoint-every", type=int, default=25, help="Write parquet/manifest checkpoints every N completed rows.")
    parser.add_argument("--no-resume", action="store_true", help="Ignore existing output parquet instead of resuming by ipfs_cid.")
    parser.add_argument("--zkp-backend", default="simulated", choices=["simulated", "groth16"], help="ZKP backend used for proof certificates.")
    parser.add_argument("--zkp-circuit-version", type=int, default=1, help="ZKP circuit version for the selected backend.")
    parser.add_argument("--knowledge-graph-entities", default="", help="Optional municipal KG entities parquet.")
    parser.add_argument("--knowledge-graph-relationships", default="", help="Optional municipal KG relationships parquet.")
    parser.add_argument("--bm25-index", default="", help="Optional BM25 bag-of-words parquet.")
    parser.add_argument("--ontology", default="", help="Optional municipal law ontology JSON.")
    parser.add_argument("--existing-logic-artifacts", default="", help="Optional existing logic parquet whose accepted LLM formulas should be reused as the base formula.")
    parser.add_argument("--json", action="store_true", help="Print manifest JSON.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    import pyarrow.parquet as pq

    input_path = Path(args.input).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    logic_path = output_root / "STATE-OR_logic_proof_artifacts.parquet"
    manifest_path = output_root / "manifest.json"

    rows = pq.read_table(input_path).to_pylist()
    if args.limit and args.limit > 0:
        rows = rows[: int(args.limit)]
    context_artifacts = _load_context_artifacts(args)

    fol_converter = FOLConverter(
        use_cache=True,
        use_ml=False,
        use_nlp=False,
        enable_monitoring=False,
        confidence_threshold=0.0,
        cache_maxsize=10_000,
    )
    deontic_converter = DeonticConverter(
        use_cache=True,
        use_ml=False,
        enable_monitoring=False,
        jurisdiction="us",
        document_type="statute",
        confidence_threshold=0.0,
        cache_maxsize=10_000,
    )
    zkp_backend = str(args.zkp_backend or "simulated").lower()
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
    completed_cids: set[str] = set()
    if logic_path.exists() and not args.no_resume:
        try:
            out_rows = pq.read_table(logic_path).to_pylist()
            completed_cids = {_compact(row.get("ipfs_cid")) for row in out_rows if _compact(row.get("ipfs_cid"))}
        except Exception:
            out_rows = []
            completed_cids = set()

    failures: List[Dict[str, str]] = []
    checkpoint_every = max(1, int(args.checkpoint_every or 1))
    started_at = datetime.now(timezone.utc).isoformat()

    def _manifest(status: str) -> Dict[str, Any]:
        return {
            "schema_version": "portland-logic-proof-artifacts-v2",
            "input": str(input_path),
            "output_root": str(output_root),
            "logic_proof_artifacts": str(logic_path),
            "source_row_count": len(rows),
            "artifact_row_count": len(out_rows),
            "completed_row_count": len(completed_cids),
            "remaining_row_count": max(0, len(rows) - len(completed_cids)),
            "failure_count": len(failures),
            "failures": failures[:50],
            "formalization_scope": "machine_generated_candidate",
            "ontology_version": _compact(context_artifacts.ontology.get("ontology_version")) or "unknown",
            "kg_entity_count": len(context_artifacts.entity_by_id),
            "kg_relationship_count": sum(len(values) for values in context_artifacts.relationships_by_source.values()),
            "bm25_document_count": len(context_artifacts.bm25_by_cid),
            "existing_logic_artifact_count": len(context_artifacts.existing_logic_by_cid),
            "llm_assisted": bool(args.llm_assisted),
            "llm_provider": str(args.llm_provider or ""),
            "llm_model": str(args.llm_model or ""),
            "llm_accepted_count": sum(1 for row in out_rows if row.get("llm_assisted_accepted")),
            "zkp_backend": zkp_backend,
            "zkp_circuit_version": zkp_circuit_version,
            "zkp_security_note": (
                "Groth16 BN254 proofs generated by bundled Rust backend"
                if zkp_backend == "groth16"
                else "simulated educational certificates; not cryptographically secure"
            ),
            "status": status,
            "started_at": started_at,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    processed_since_checkpoint = 0
    _write_manifest(manifest_path, _manifest("running"))
    for index, row in enumerate(rows):
        source_cid = _compact(row.get("ipfs_cid"))
        if source_cid and source_cid in completed_cids:
            continue
        try:
            built = _build_row(
                row,
                fol_converter=fol_converter,
                deontic_converter=deontic_converter,
                zkp_prover=zkp_prover,
                zkp_verifier=zkp_verifier,
                zkp_backend=zkp_backend,
                zkp_circuit_version=zkp_circuit_version,
                max_chars=int(args.max_chars),
                llm_assisted=bool(args.llm_assisted),
                llm_provider=str(args.llm_provider or ""),
                llm_model=str(args.llm_model or ""),
                llm_max_chars=int(args.llm_max_chars),
                llm_timeout=float(args.llm_timeout),
                context_artifacts=context_artifacts,
            )
            out_rows.append(built)
            if source_cid:
                completed_cids.add(source_cid)
            processed_since_checkpoint += 1
        except Exception as exc:
            failures.append(
                {
                    "index": str(index),
                    "ipfs_cid": _compact(row.get("ipfs_cid")),
                    "identifier": _section_ref(row),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            processed_since_checkpoint += 1

        if processed_since_checkpoint >= checkpoint_every:
            if out_rows:
                _write_parquet(logic_path, out_rows)
            _write_manifest(manifest_path, _manifest("running"))
            processed_since_checkpoint = 0

    _write_parquet(logic_path, out_rows)
    manifest = _manifest("complete" if not failures else "complete_with_failures")
    _write_manifest(manifest_path, manifest)

    if args.json:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
    else:
        print(f"Rows: {len(out_rows)} / {len(rows)}")
        print(f"Failures: {len(failures)}")
        print(f"Output: {logic_path}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
