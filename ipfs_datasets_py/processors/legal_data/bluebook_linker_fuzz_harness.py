"""LLM-driven fuzz harness for the Bluebook citation linker.

This module generates Bluebook-style citations with ``llm_router``, attempts to
resolve them through the canonical linker/Hugging Face dataset layer, and can
optionally promote unresolved citation recoveries into the local canonical
dataset merge path that later gets published back to Hugging Face.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
import random
import re
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence

from ipfs_datasets_py import llm_router
from ipfs_datasets_py.processors.legal_data.citation_extraction import CitationExtractor
from ipfs_datasets_py.processors.legal_data.bluebook_citation_linker import (
    BluebookCitationResolver,
    CitationLink,
    citation_link_to_dict,
    resolve_bluebook_lookup_result_document,
    _normalize_malformed_citation,
    _IDENTIFIER_FIELDS,
    _OFFICIAL_CITE_FIELDS,
    _PAGE_FIELDS,
    _SECTION_FIELDS,
    _STATE_FIELDS,
    _TITLE_FIELDS,
    _TITLE_NUMBER_FIELDS,
    _URL_FIELDS,
    _VOLUME_FIELDS,
    _first_present,
)
from ipfs_datasets_py.processors.legal_data.legal_source_recovery import (
    recover_missing_legal_citation_source,
)
from ipfs_datasets_py.processors.legal_data.legal_source_recovery_promotion import (
    merge_recovery_manifest_into_canonical_dataset,
)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.IGNORECASE | re.DOTALL)
_SEEDED_SOURCE_ROW_CACHE: Dict[tuple[str, str, str], Dict[str, Any]] = {}
_DEFAULT_FUZZ_CORPORA = [
    "us_code",
    "federal_register",
    "state_laws",
    "state_admin_rules",
    "state_court_rules",
    "caselaw_access_project",
]
_STATE_CODE_TO_BLUEBOOK = {
    "AK": "Alaska",
    "AL": "Ala.",
    "AR": "Ark.",
    "AZ": "Ariz.",
    "CA": "Cal.",
    "CO": "Colo.",
    "CT": "Conn.",
    "DC": "D.C.",
    "DE": "Del.",
    "FL": "Fla.",
    "GA": "Ga.",
    "HI": "Haw.",
    "IA": "Iowa",
    "ID": "Idaho",
    "IL": "Ill.",
    "IN": "Ind.",
    "KS": "Kan.",
    "KY": "Ky.",
    "LA": "La.",
    "MA": "Mass.",
    "MD": "Md.",
    "ME": "Me.",
    "MI": "Mich.",
    "MN": "Minn.",
    "MO": "Mo.",
    "MS": "Miss.",
    "MT": "Mont.",
    "NC": "N.C.",
    "ND": "N.D.",
    "NE": "Neb.",
    "NH": "N.H.",
    "NJ": "N.J.",
    "NM": "N.M.",
    "NV": "Nev.",
    "NY": "N.Y.",
    "OH": "Ohio",
    "OK": "Okla.",
    "OR": "Or.",
    "PA": "Pa.",
    "RI": "R.I.",
    "SC": "S.C.",
    "SD": "S.D.",
    "TN": "Tenn.",
    "TX": "Tex.",
    "UT": "Utah",
    "VA": "Va.",
    "VT": "Vt.",
    "WA": "Wash.",
    "WI": "Wis.",
    "WV": "W. Va.",
    "WY": "Wyo.",
}


@dataclass
class BluebookCitationCandidate:
    citation_text: str
    context_text: str = ""
    state_code: Optional[str] = None
    corpus_key_hint: Optional[str] = None
    citation_type_hint: Optional[str] = None
    expected_valid: Optional[bool] = None
    notes: Optional[str] = None

    def render_document_text(self) -> str:
        context = str(self.context_text or "").strip()
        if context:
            return context
        return f"The filing cites {self.citation_text} as supporting authority."

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "BluebookCitationCandidate":
        return cls(
            citation_text=str(payload.get("citation_text") or "").strip(),
            context_text=str(payload.get("context_text") or "").strip(),
            state_code=(str(payload.get("state_code") or "").strip().upper() or None),
            corpus_key_hint=(str(payload.get("corpus_key_hint") or payload.get("corpus_key") or "").strip() or None),
            citation_type_hint=(str(payload.get("citation_type_hint") or payload.get("citation_type") or "").strip() or None),
            expected_valid=payload.get("expected_valid") if isinstance(payload.get("expected_valid"), bool) else None,
            notes=(str(payload.get("notes") or "").strip() or None),
        )


@dataclass
class BluebookCitationFuzzAttempt:
    ordinal: int
    candidate: BluebookCitationCandidate
    resolution: Dict[str, Any]
    recoveries: List[Dict[str, Any]] = field(default_factory=list)
    merge_reports: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "candidate": asdict(self.candidate),
            "resolution": dict(self.resolution),
            "recoveries": [dict(item) for item in self.recoveries],
            "merge_reports": [dict(item) for item in self.merge_reports],
        }


@dataclass
class BluebookCitationFuzzRun:
    prompt: str
    raw_generation: str
    candidates: List[BluebookCitationCandidate]
    attempts: List[BluebookCitationFuzzAttempt]
    summary: Dict[str, Any]
    seeded_examples: List[Dict[str, Any]] = field(default_factory=list)
    output_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt": self.prompt,
            "raw_generation": self.raw_generation,
            "candidates": [asdict(item) for item in self.candidates],
            "attempts": [item.to_dict() for item in self.attempts],
            "summary": dict(self.summary),
            "seeded_examples": [dict(item) for item in self.seeded_examples],
            "output_path": self.output_path,
        }


def build_bluebook_fuzz_generation_prompt(
    *,
    sample_count: int,
    corpus_keys: Optional[Sequence[str]] = None,
    state_codes: Optional[Sequence[str]] = None,
    adversarial_ratio: float = 0.35,
    seeded_examples: Optional[Sequence[Dict[str, Any]]] = None,
) -> str:
    requested_corpora = ", ".join(str(item) for item in (corpus_keys or []) if str(item).strip()) or "usc, cfr, federal_register, public_law, state_statute, case"
    requested_states = ", ".join(str(item).upper() for item in (state_codes or []) if str(item).strip()) or "MN, OR, NY, CA, TX"
    ratio = max(0.0, min(1.0, float(adversarial_ratio)))
    prompt = (
        "Generate synthetic Bluebook-style legal citation fuzz cases for a citation linker.\n"
        f"Return exactly {int(sample_count)} items as JSON only, no markdown, no commentary.\n"
        "Each item must be an object with keys:\n"
        "- citation_text\n"
        "- context_text\n"
        "- state_code\n"
        "- corpus_key_hint\n"
        "- citation_type_hint\n"
        "- expected_valid\n"
        "- notes\n"
        f"Use these target corpora when possible: {requested_corpora}.\n"
        f"Use these state codes when state-specific: {requested_states}.\n"
        f"Make about {ratio:.0%} of the items adversarial or likely-unresolvable edge cases.\n"
        "The remaining items should be plausible real-world legal citations that look resolvable.\n"
        "For context_text, embed the citation naturally inside one short sentence.\n"
        "Keep every object compact and valid JSON.\n"
    )
    examples = [dict(item) for item in list(seeded_examples or []) if isinstance(item, dict)]
    if examples:
        prompt += (
            "Use these real dataset-grounded seed examples as style anchors.\n"
            "Do not copy them verbatim; mutate formats, sections, reporters, or jurisdictions while staying Bluebook-like.\n"
            f"Seed examples JSON:\n{json.dumps(examples, indent=2, sort_keys=True)}\n"
        )
    return prompt


def _first_non_empty_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        for item in value:
            text = _first_non_empty_string(item)
            if text:
                return text
    return str(value).strip()


def _citation_text_from_row(row: Dict[str, Any], fields: Sequence[str]) -> str:
    for field in fields:
        text = _first_non_empty_string(row.get(field))
        if text:
            return text
    return ""


def _citation_text_from_row_text(
    row: Dict[str, Any],
    citation_type: str,
    state_code: Optional[str],
) -> str:
    extractor = CitationExtractor()
    for field in ("text", "head_matter", "name", "name_abbreviation"):
        source_text = _first_non_empty_string(row.get(field))
        if not source_text:
            continue
        for citation in extractor.extract_citations(source_text):
            if citation.type != citation_type:
                continue
            if state_code:
                parsed_state = str(citation.jurisdiction or "").strip().upper()
                if parsed_state not in ("", state_code):
                    continue
            text_value = str(citation.text or "").strip()
            if text_value:
                return text_value
    return ""


def _citation_text_parses_as(citation_text: str, citation_type: str) -> bool:
    text = str(citation_text or "").strip()
    if not text:
        return False
    extractor = CitationExtractor()
    return any(citation.type == citation_type for citation in extractor.extract_citations(text))


def _parsed_citation_type(citation_text: str, citation_types: Sequence[str]) -> str:
    text = str(citation_text or "").strip()
    if not text:
        return ""
    wanted = {str(item or "").strip() for item in citation_types if str(item or "").strip()}
    extractor = CitationExtractor()
    for citation in extractor.extract_citations(text):
        if citation.type in wanted:
            return str(citation.type)
    return ""


def _candidate_source_ref(candidate: BluebookCitationCandidate) -> str:
    notes = str(candidate.notes or "")
    match = re.search(r"(?:^|;\s*)source_ref=(?P<source_ref>[^;]+)", notes)
    return str(match.group("source_ref") if match else "").strip()


def _seeded_row_cache_key(corpus_key: str, source_ref: str, citation_text: str) -> tuple[str, str, str]:
    return (
        str(corpus_key or "").strip(),
        str(source_ref or "").strip(),
        str(citation_text or "").strip().lower(),
    )


def _resolve_candidate_from_seeded_row_cache(
    candidate: BluebookCitationCandidate,
    *,
    resolver: BluebookCitationResolver,
    exhaustive: bool,
) -> Optional[Dict[str, Any]]:
    source_ref = _candidate_source_ref(candidate)
    corpus_key = str(candidate.corpus_key_hint or "").strip()
    citation_text = str(candidate.citation_text or "").strip()
    if not (source_ref and corpus_key and citation_text):
        return None
    row = _SEEDED_SOURCE_ROW_CACHE.get(_seeded_row_cache_key(corpus_key, source_ref, citation_text))
    if not row:
        return None

    links: List[Dict[str, Any]] = []
    for citation in resolver.extractor.extract_citations(candidate.render_document_text()):
        if str(citation.text or "").strip().lower() != citation_text.lower():
            continue
        ranked = resolver._rank_rows([dict(row)], citation, candidate.state_code)
        if ranked is None:
            return None
        matched_row, matched_field, confidence = ranked
        normalized_citation = resolver._normalized_citation(citation)
        link = CitationLink(
            citation_text=citation.text,
            citation_type=citation.type,
            normalized_citation=normalized_citation,
            matched=True,
            corpus_key=corpus_key,
            matched_field=matched_field,
            confidence=confidence,
            source_document_id=str(_first_present(matched_row, _IDENTIFIER_FIELDS) or ""),
            source_title=str(_first_present(matched_row, _TITLE_FIELDS) or ""),
            source_url=str(_first_present(matched_row, _URL_FIELDS) or ""),
            source_cid=str(_first_present(matched_row, ("ipfs_cid", "cid", "source_cid")) or ""),
            source_ref=source_ref,
            snippet=resolver._snippet_for_row(matched_row),
            metadata={
                "state_code": candidate.state_code,
                "resolution_method": "seeded_source_row_cache",
                "resolution_quality": "exact_anchor",
                "require_exact_anchor": bool(getattr(resolver, "require_exact_anchor", True)),
                "source_row_present": True,
                "source_ref_kind": "seeded_source_ref",
                "row": dict(matched_row),
            },
        )
        links.append(citation_link_to_dict(link))

    if not links:
        return None
    matched_count = sum(1 for item in links if bool(item.get("matched")))
    return {
        "source": "bluebook_lookup_result_document",
        "input_text": candidate.render_document_text(),
        "state_code": candidate.state_code,
        "exhaustive": bool(exhaustive),
        "recovery": {"enabled": False, "attempted": False, "skipped_reason": "seeded_source_row_cache"},
        "citation_count": len(links),
        "matched_citation_count": matched_count,
        "unmatched_citation_count": len(links) - matched_count,
        "citation_resolution_ratio": (matched_count / len(links)) if links else 1.0,
        "citations": links,
        "unresolved_citations": [item for item in links if not bool(item.get("matched"))],
        "citation_suggestions": [],
        "recovery_results": [],
    }


def _sql_literal_path(path: str) -> str:
    return str(path).replace("'", "''")


def _load_targeted_seed_rows_from_parquet(
    source_ref: str,
    *,
    corpus_key: str,
    limit: int,
) -> List[Dict[str, Any]]:
    source_text = str(source_ref or "").strip()
    is_remote = source_text.startswith(("http://", "https://"))
    if is_remote:
        sql_source = source_text
    else:
        path = Path(source_text).expanduser()
        if not path.exists() or path.suffix.lower() != ".parquet":
            return []
        sql_source = str(path)
    if not sql_source:
        return []
    try:
        import duckdb
    except Exception:
        return []

    field_preferences = {
        "federal_register": ["citation_text", "normalized_citation", "official_cite", "citation", "bluebook_citation"],
        "us_code": ["citation_text", "normalized_citation", "official_cite", "citation", "identifier", "title_number", "section_number"],
        "caselaw_access_project": ["citation", "citations", "official_cite", "name_abbreviation", "name"],
        "state_laws": ["official_cite", "citation_text", "normalized_citation", "citation", "citations", "identifier", "section"],
        "state_admin_rules": ["citation_text", "normalized_citation", "official_cite", "citations", "section", "rule_number", "source_id"],
        "state_court_rules": ["citation_text", "normalized_citation", "official_cite", "citations", "section", "rule_number", "source_id"],
    }
    wanted_fields = field_preferences.get(corpus_key, ["citation_text", "normalized_citation", "official_cite", "citation"])
    try:
        con = duckdb.connect()
        schema_rows = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{_sql_literal_path(sql_source)}')").fetchall()
        schema = {str(row[0]) for row in schema_rows}
        available = [field for field in wanted_fields if field in schema]
        if not available:
            return []
        clauses = [
            f"({field} IS NOT NULL AND trim(cast({field} AS varchar)) <> '')"
            for field in available
        ]
        query = (
            f"SELECT * FROM read_parquet('{_sql_literal_path(sql_source)}') "
            f"WHERE {' OR '.join(clauses)} LIMIT {max(1, int(limit))}"
        )
        rows = con.execute(query).fetchall()
        names = [desc[0] for desc in con.description]
        return [dict(zip(names, row)) for row in rows]
    except Exception:
        return []
    finally:
        try:
            con.close()
        except Exception:
            pass


def _synthetic_state_identifier(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return bool(
        re.match(r"^[A-Z]{2}-ADMIN-[0-9a-f]{8,}$", text, flags=re.IGNORECASE)
        or re.match(r"^[A-Z]{2}-[a-z_]+-\d{8,}$", text, flags=re.IGNORECASE)
        or re.match(r"^doc-\d+$", text, flags=re.IGNORECASE)
    )


def _court_rule_section_from_value(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    patterns = (
        r"\bUTCR\s+(?P<section>\d+(?:\.\d+)*(?:\([^)]+\))?)(?![\w.])",
        r"\bLocal\s+Rule\s+(?P<section>\d+(?:\.\d+)*(?:\([^)]+\))?)(?![\w.])",
        r"\bSupplemental\s+Local\s+Court\s+Rule\s+(?P<section>\d+(?:\.\d+)*(?:\([^)]+\))?)(?![\w.])",
        r"\bRule\s+(?P<section>\d+(?:\.\d+)*(?:\([^)]+\))?)(?![\w.])",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        section = str(match.group("section") or "").strip().rstrip(".,;:")
        if section and re.search(r"\d", section) and not _synthetic_state_identifier(section):
            return section
    return ""


def _state_rule_section_from_row(row: Dict[str, Any], *, corpus_key: str) -> str:
    if corpus_key == "state_court_rules":
        for field in ("rule_number", "name", "title", "text", "source_id", "section", "section_number"):
            section = _court_rule_section_from_value(_first_non_empty_string(row.get(field)))
            if section:
                return section

    values = [
        _first_non_empty_string(row.get(field))
        for field in ("section", "section_number", "rule_number", "source_id", "text", "name", "title", "source_url", "url")
    ]
    for value in values:
        if not value:
            continue
        if corpus_key == "state_admin_rules":
            match = re.search(r"\b(?P<section>\d{3}-\d{3}-\d{4})\b", value)
            if match:
                return str(match.group("section")).strip()
        match = re.search(r"(?:Section|Rule|Part)[\s:-]+(?P<section>[A-Za-z0-9.:-]+)", value, re.IGNORECASE)
        if match:
            section = str(match.group("section") or "").strip().rstrip(".,;:")
            section = re.sub(r"^(?:section|rule|part)[-\\s:]+", "", section, flags=re.IGNORECASE).strip()
            if section and re.search(r"\d", section) and not _synthetic_state_identifier(section):
                return section
    return ""


def _state_seed_citation_matches_corpus(citation_text: str, corpus_key: str, state_code: Optional[str]) -> bool:
    citations = CitationExtractor().extract_citations(citation_text)
    for citation in citations:
        if citation.type != "state_statute":
            continue
        parsed_state = str(citation.jurisdiction or "").strip().upper()
        if state_code and parsed_state not in ("", str(state_code).strip().upper()):
            continue
        code_name = str(citation.metadata.get("code_name") or "").lower()
        if corpus_key == "state_admin_rules":
            return "admin" in code_name
        if corpus_key == "state_court_rules":
            return "court" in code_name or "r." in code_name
        return True
    return False


def _synthesize_state_statute_citation_from_row(
    row: Dict[str, Any],
    state_code: str,
    *,
    corpus_key: str = "state_laws",
) -> str:
    source_id = str(row.get("source_id") or "").strip()
    text = _first_non_empty_string(row.get("text"))
    bluebook_abbrev = _STATE_CODE_TO_BLUEBOOK.get(state_code)
    if not bluebook_abbrev:
        return ""

    section = _state_rule_section_from_row(row, corpus_key=corpus_key)
    if not section:
        return ""

    lowered_source = source_id.lower()
    if corpus_key == "state_admin_rules" or "state-admin" in lowered_source or "administrative" in lowered_source:
        code_name = "Admin. Code"
    elif corpus_key == "state_court_rules" or "court-rule" in lowered_source or "court rule" in lowered_source:
        code_name = "Court Rules"
    elif "statute" in lowered_source or corpus_key == "state_laws":
        code_name = "Stat."
    else:
        return ""
    return f"{bluebook_abbrev} {code_name} § {section}"


def _synthesize_seed_candidate_from_row(
    *,
    corpus_key: str,
    row: Dict[str, Any],
    state_code: Optional[str],
    source_ref: str,
) -> Optional[BluebookCitationCandidate]:
    citation_text = ""
    citation_type = ""
    resolved_state = state_code
    if corpus_key == "us_code":
        title = _first_present(row, _TITLE_NUMBER_FIELDS)
        section = _first_present(row, _SECTION_FIELDS)
        if title not in (None, "") and section not in (None, ""):
            citation_text = _citation_text_from_row(row, _OFFICIAL_CITE_FIELDS) or f"{title} U.S.C. § {section}"
            citation_type = "usc"
    elif corpus_key == "federal_register":
        for field in ("citation_text", "normalized_citation", "official_cite", "citation", "bluebook_citation"):
            candidate_text = _first_non_empty_string(row.get(field))
            parsed_type = _parsed_citation_type(candidate_text, ("federal_register", "cfr"))
            if parsed_type:
                citation_text = candidate_text
                citation_type = parsed_type
                break
        volume = _first_present(row, _VOLUME_FIELDS)
        page = _first_present(row, _PAGE_FIELDS)
        if not citation_text and volume not in (None, "") and page not in (None, ""):
            citation_text = _citation_text_from_row(row, _OFFICIAL_CITE_FIELDS) or f"{volume} FR {page}"
            citation_type = "federal_register"
    elif corpus_key == "caselaw_access_project":
        citation_text = _citation_text_from_row(row, tuple(list(_OFFICIAL_CITE_FIELDS) + ["citations", "name_abbreviation", "name"]))
        if not citation_text:
            citation_text = _citation_text_from_row_text(row, "case", None)
        citation_type = "case"
    elif corpus_key in {"state_laws", "state_admin_rules", "state_court_rules"}:
        resolved_state = str(_first_present(row, _STATE_FIELDS) or state_code or "").strip().upper() or None
        if corpus_key == "state_laws":
            citation_text = _citation_text_from_row(row, tuple(list(_OFFICIAL_CITE_FIELDS) + ["citations"]))
        else:
            citation_text = _citation_text_from_row(row, ("citation_text", "normalized_citation", "official_cite", "bluebook_citation", "citations"))
            if _synthetic_state_identifier(citation_text):
                citation_text = ""
        if not citation_text and resolved_state:
            identifier_fields = [field for field in _IDENTIFIER_FIELDS if field not in {"source_id", "name", "name_abbreviation"}]
            has_structured_fields = any(
                _first_present(row, fields) not in (None, "")
                for fields in (_OFFICIAL_CITE_FIELDS, _SECTION_FIELDS, _TITLE_NUMBER_FIELDS, identifier_fields)
            )
            has_source_backed_fields = bool(_first_non_empty_string(row.get("source_id")) or _first_non_empty_string(row.get("text")))
            if has_structured_fields or has_source_backed_fields:
                citation_text = _synthesize_state_statute_citation_from_row(row, resolved_state, corpus_key=corpus_key)
        if not citation_text:
            extracted_text = _citation_text_from_row_text(row, "state_statute", resolved_state)
            if corpus_key == "state_laws" or _state_seed_citation_matches_corpus(extracted_text, corpus_key, resolved_state):
                citation_text = extracted_text
        if citation_text and corpus_key != "state_laws" and not _state_seed_citation_matches_corpus(citation_text, corpus_key, resolved_state):
            citation_text = ""
        citation_type = "state_statute"
    if not citation_text:
        return None

    title = _citation_text_from_row(row, _TITLE_FIELDS)
    url = _citation_text_from_row(row, _URL_FIELDS)
    context = f"The filing relies on {citation_text} as authority."
    note_parts = [f"seeded from {corpus_key}", f"source_ref={source_ref}"]
    if title:
        note_parts.append(f"title={title}")
    if url:
        note_parts.append(f"url={url}")
    candidate = BluebookCitationCandidate(
        citation_text=citation_text,
        context_text=context,
        state_code=resolved_state,
        corpus_key_hint=corpus_key,
        citation_type_hint=citation_type,
        expected_valid=True,
        notes="; ".join(note_parts),
    )
    _SEEDED_SOURCE_ROW_CACHE[_seeded_row_cache_key(corpus_key, source_ref, citation_text)] = dict(row)
    return candidate


def _normalized_partition_key(corpus_key: str, state_code: Optional[str]) -> str:
    corpus_value = str(corpus_key or "").strip() or "unknown"
    state_value = str(state_code or "").strip().upper() or "federal"
    return f"{corpus_value}:{state_value}"


def _select_evenly_spaced_candidates(
    candidates: Sequence[BluebookCitationCandidate],
    *,
    limit: int,
) -> List[BluebookCitationCandidate]:
    if limit <= 0:
        return []
    values = list(candidates)
    if len(values) <= limit:
        return values
    if limit == 1:
        return [values[0]]

    selected: List[BluebookCitationCandidate] = []
    used_indexes = set()
    last_index = len(values) - 1
    for offset in range(limit):
        raw_index = round((offset * last_index) / (limit - 1))
        index = min(last_index, max(0, int(raw_index)))
        while index in used_indexes and index < last_index:
            index += 1
        while index in used_indexes and index > 0:
            index -= 1
        if index in used_indexes:
            continue
        used_indexes.add(index)
        selected.append(values[index])
    return selected


def _balanced_select_candidates(
    candidates: Sequence[BluebookCitationCandidate],
    *,
    total_limit: int,
    per_partition_limit: Optional[int] = None,
) -> List[BluebookCitationCandidate]:
    values = [item for item in candidates if isinstance(item, BluebookCitationCandidate)]
    if total_limit <= 0 or not values:
        return []

    by_partition: Dict[str, List[BluebookCitationCandidate]] = {}
    partition_order: List[str] = []
    for item in values:
        key = _normalized_partition_key(str(item.corpus_key_hint or ""), item.state_code)
        if key not in by_partition:
            partition_order.append(key)
            by_partition[key] = []
        by_partition[key].append(item)

    working: Dict[str, List[BluebookCitationCandidate]] = {}
    for key, group in by_partition.items():
        is_state_partition = any(str(item.state_code or "").strip() for item in group)
        limit = len(group)
        if is_state_partition and per_partition_limit is not None:
            limit = min(len(group), max(1, int(per_partition_limit)))
        working[key] = list(_select_evenly_spaced_candidates(group, limit=limit))

    selected: List[BluebookCitationCandidate] = []
    while len(selected) < total_limit:
        advanced = False
        for key in partition_order:
            group = working.get(key) or []
            if not group:
                continue
            selected.append(group.pop(0))
            advanced = True
            if len(selected) >= total_limit:
                break
        if not advanced:
            break
    return selected


def collect_seeded_bluebook_fuzz_candidates(
    *,
    resolver: BluebookCitationResolver,
    corpus_keys: Optional[Sequence[str]] = None,
    state_codes: Optional[Sequence[str]] = None,
    examples_per_corpus: int = 2,
    sample_count: Optional[int] = None,
    max_examples_per_state: Optional[int] = None,
    max_examples_per_source: Optional[int] = None,
    shuffle_seed: int = 0,
) -> List[BluebookCitationCandidate]:
    requested_corpora = [str(item).strip() for item in (corpus_keys or []) if str(item).strip()] or [
        "us_code",
        "federal_register",
        "state_laws",
        "state_admin_rules",
        "state_court_rules",
        "caselaw_access_project",
    ]
    requested_states = [str(item).strip().upper() for item in (state_codes or []) if str(item).strip()] or ["MN", "OR", "NY"]

    max_per_corpus = max(1, int(examples_per_corpus))
    max_per_state = max(1, int(max_examples_per_state or max_per_corpus))
    max_per_source = max(1, int(max_examples_per_source or max_per_state))
    candidates: List[BluebookCitationCandidate] = []
    for corpus_key in requested_corpora:
        state_iter = requested_states if corpus_key.startswith("state_") else [None]
        corpus_candidates: List[BluebookCitationCandidate] = []
        for state_code in state_iter:
            state_candidates: List[BluebookCitationCandidate] = []
            for source_ref in resolver._iter_corpus_sources(corpus_key, state_code=state_code):
                source_candidates: List[BluebookCitationCandidate] = []
                if str(source_ref).startswith(("http://", "https://")):
                    targeted_rows = _load_targeted_seed_rows_from_parquet(
                        source_ref,
                        corpus_key=corpus_key,
                        limit=max(max_per_source * 10, 50),
                    )
                    for row in targeted_rows:
                        candidate = _synthesize_seed_candidate_from_row(
                            corpus_key=corpus_key,
                            row=dict(row),
                            state_code=state_code,
                            source_ref=source_ref,
                        )
                        if candidate is None:
                            continue
                        if corpus_key.startswith("state_") and state_code:
                            candidate_state = str(candidate.state_code or "").strip().upper()
                            if candidate_state and candidate_state != str(state_code).strip().upper():
                                continue
                        source_candidates.append(candidate)
                    if source_candidates:
                        state_candidates.extend(_select_evenly_spaced_candidates(source_candidates, limit=max_per_source))
                        continue
                local_source = source_ref
                if str(source_ref).startswith(("http://", "https://")):
                    materialized = resolver._materialize_remote_parquet(source_ref)
                    if not materialized:
                        continue
                    local_source = materialized
                rows = resolver._load_local_parquet_rows(local_source)
                for row in rows:
                    candidate = _synthesize_seed_candidate_from_row(
                        corpus_key=corpus_key,
                        row=dict(row),
                        state_code=state_code,
                        source_ref=source_ref,
                    )
                    if candidate is None:
                        continue
                    if corpus_key.startswith("state_") and state_code:
                        candidate_state = str(candidate.state_code or "").strip().upper()
                        if candidate_state and candidate_state != str(state_code).strip().upper():
                            continue
                    source_candidates.append(candidate)
                if not source_candidates:
                    targeted_rows = _load_targeted_seed_rows_from_parquet(
                        local_source,
                        corpus_key=corpus_key,
                        limit=max(max_per_source * 10, 50),
                    )
                    for row in targeted_rows:
                        candidate = _synthesize_seed_candidate_from_row(
                            corpus_key=corpus_key,
                            row=dict(row),
                            state_code=state_code,
                            source_ref=source_ref,
                        )
                        if candidate is None:
                            continue
                        if corpus_key.startswith("state_") and state_code:
                            candidate_state = str(candidate.state_code or "").strip().upper()
                            if candidate_state and candidate_state != str(state_code).strip().upper():
                                continue
                        source_candidates.append(candidate)
                state_candidates.extend(_select_evenly_spaced_candidates(source_candidates, limit=max_per_source))
            state_limit = max_per_state if corpus_key.startswith("state_") else max_per_corpus
            corpus_candidates.extend(_select_evenly_spaced_candidates(state_candidates, limit=state_limit))
        candidates.extend(_select_evenly_spaced_candidates(corpus_candidates, limit=max_per_corpus))

    rng = random.Random(int(shuffle_seed))
    ordered_candidates = list(candidates)
    rng.shuffle(ordered_candidates)
    if sample_count is not None:
        ordered_candidates = _balanced_select_candidates(
            ordered_candidates,
            total_limit=max(1, int(sample_count)),
            per_partition_limit=max_examples_per_state,
        )
    return ordered_candidates


def _extract_json_payload(raw_text: str) -> Any:
    text = str(raw_text or "").strip()
    if not text:
        raise ValueError("LLM generation returned empty text")

    candidates = [text]
    fenced = _JSON_FENCE_RE.findall(text)
    candidates.extend(item.strip() for item in fenced if item.strip())

    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except Exception:
            pass
        try:
            parsed, _end = decoder.raw_decode(candidate)
            return parsed
        except Exception:
            pass

    raise ValueError("Unable to parse JSON payload from LLM generation output")


def parse_bluebook_fuzz_candidates(raw_text: str) -> List[BluebookCitationCandidate]:
    payload = _extract_json_payload(raw_text)
    if isinstance(payload, dict):
        for key in ("candidates", "items", "citations", "results", "cases"):
            value = payload.get(key)
            if isinstance(value, list):
                payload = value
                break
    if not isinstance(payload, list):
        raise ValueError("Expected generated citation payload to be a JSON list")

    candidates: List[BluebookCitationCandidate] = []
    for item in payload:
        if isinstance(item, str):
            item = {"citation_text": item}
        if not isinstance(item, dict):
            continue
        candidate = BluebookCitationCandidate.from_dict(item)
        if candidate.citation_text:
            candidates.append(candidate)
    if not candidates:
        raise ValueError("Generated citation payload did not contain any usable citations")
    return candidates


def _fallback_bluebook_fuzz_candidates(
    *,
    sample_count: int,
    corpus_keys: Optional[Sequence[str]] = None,
    state_codes: Optional[Sequence[str]] = None,
) -> List[BluebookCitationCandidate]:
    requested_corpora = {
        str(item or "").strip().lower()
        for item in (corpus_keys or [])
        if str(item or "").strip()
    }
    requested_states = [
        str(item or "").strip().upper()
        for item in (state_codes or [])
        if str(item or "").strip()
    ]
    if not requested_corpora:
        requested_corpora = {
            "caselaw_access_project",
            "cfr",
            "federal_register",
            "state_admin_rules",
            "state_court_rules",
            "state_laws",
            "us_code",
        }
    if not requested_states:
        requested_states = ["MN", "OR", "NY", "CA", "TX"]

    state_examples = {
        "MN": ("Minn. Stat. § 518.17", "Minnesota best interests custody factor", "Minn. Stat.", "state_statute"),
        "OR": ("Or. Rev. Stat. § 659A.030", "Oregon unlawful employment practice", "Or. Rev. Stat.", "state_statute"),
        "NY": ("N.Y. C.P.L.R. 3211", "New York motion to dismiss standard", "N.Y. C.P.L.R.", "state_statute"),
        "CA": ("Cal. Civ. Proc. Code § 425.16", "California anti-SLAPP procedure", "Cal. Civ. Proc. Code", "state_statute"),
        "TX": ("Tex. Civ. Prac. & Rem. Code § 27.003", "Texas dismissal procedure", "Tex. Civ. Prac. & Rem. Code", "state_statute"),
    }
    corpus_examples = {
        "us_code": [
            BluebookCitationCandidate(
                citation_text="42 U.S.C. § 1983",
                context_text="The complaint cites 42 U.S.C. § 1983 for civil rights relief.",
                corpus_key_hint="us_code",
                citation_type_hint="usc",
                expected_valid=True,
                notes="deterministic fallback federal statute",
            )
        ],
        "federal_register": [
            BluebookCitationCandidate(
                citation_text="89 Fed. Reg. 1001",
                context_text="The agency notice appears at 89 Fed. Reg. 1001.",
                corpus_key_hint="federal_register",
                citation_type_hint="federal_register",
                expected_valid=True,
                notes="deterministic fallback federal register citation",
            )
        ],
        "cfr": [
            BluebookCitationCandidate(
                citation_text="21 C.F.R. § 314.80",
                context_text="The safety reporting rule appears at 21 C.F.R. § 314.80.",
                corpus_key_hint="cfr",
                citation_type_hint="cfr",
                expected_valid=True,
                notes="deterministic fallback regulation citation",
            )
        ],
        "state_admin_rules": [
            BluebookCitationCandidate(
                citation_text="Minn. R. 3400.0100",
                context_text="The administrative rule cites Minn. R. 3400.0100.",
                state_code="MN",
                corpus_key_hint="state_admin_rules",
                citation_type_hint="state_admin_rule",
                expected_valid=True,
                notes="deterministic fallback state rule citation",
            )
        ],
        "state_court_rules": [
            BluebookCitationCandidate(
                citation_text="Minn. R. Civ. P. 56.03",
                context_text="The motion invokes Minn. R. Civ. P. 56.03.",
                state_code="MN",
                corpus_key_hint="state_court_rules",
                citation_type_hint="state_court_rule",
                expected_valid=True,
                notes="deterministic fallback court rule citation",
            )
        ],
        "caselaw_access_project": [
            BluebookCitationCandidate(
                citation_text="410 U.S. 113",
                context_text="The brief discusses 410 U.S. 113 as controlling precedent.",
                corpus_key_hint="caselaw_access_project",
                citation_type_hint="case",
                expected_valid=True,
                notes="deterministic fallback case citation",
            )
        ],
    }

    state_candidates: List[BluebookCitationCandidate] = []
    if "state_laws" in requested_corpora or "state_statute" in requested_corpora:
        for state_code in requested_states:
            citation, topic, _prefix, citation_type = state_examples.get(
                state_code,
                (
                    f"{_STATE_CODE_TO_BLUEBOOK.get(state_code, state_code)} Stat. § 1.01",
                    f"{state_code} fallback state statute",
                    "Stat.",
                    "state_statute",
                ),
            )
            state_candidates.append(
                BluebookCitationCandidate(
                    citation_text=citation,
                    context_text=f"The filing cites {citation} for {topic}.",
                    state_code=state_code,
                    corpus_key_hint="state_laws",
                    citation_type_hint=citation_type,
                    expected_valid=True,
                    notes="deterministic fallback after generation parse failure",
                )
            )

    corpus_candidates: List[BluebookCitationCandidate] = []
    for corpus_key in sorted(requested_corpora):
        corpus_candidates.extend(corpus_examples.get(corpus_key, []))

    candidates: List[BluebookCitationCandidate] = []
    if state_candidates:
        candidates.append(state_candidates[0])
    candidates.extend(corpus_candidates)
    candidates.extend(state_candidates[1:])

    if not candidates:
        candidates = corpus_examples["us_code"] + corpus_examples["caselaw_access_project"]
    limit = max(1, int(sample_count))
    repeated: List[BluebookCitationCandidate] = []
    while len(repeated) < limit:
        repeated.extend(candidates)
    return repeated[:limit]


def _attempt_succeeded(attempt: BluebookCitationFuzzAttempt) -> bool:
    return int(attempt.resolution.get("matched_citation_count") or 0) > 0


def _attempt_corpus_key(attempt: BluebookCitationFuzzAttempt) -> str:
    candidate_hint = str(attempt.candidate.corpus_key_hint or "").strip()
    if candidate_hint:
        return candidate_hint
    for recovery in attempt.recoveries:
        recovery_hint = str(recovery.get("corpus_key") or "").strip()
        if recovery_hint:
            return recovery_hint
    for unresolved in attempt.resolution.get("unresolved_citations") or []:
        if not isinstance(unresolved, dict):
            continue
        metadata = unresolved.get("metadata") if isinstance(unresolved.get("metadata"), dict) else {}
        for key in ("recovery_corpus_key", "preferred_corpus_key", "corpus_key"):
            metadata_hint = str(metadata.get(key) or unresolved.get(key) or "").strip()
            if metadata_hint:
                return metadata_hint
    return "unknown"


def _wilson_upper_bound(failures: int, total: int, *, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    phat = failures / total
    z2 = z * z
    denom = 1.0 + z2 / total
    center = phat + z2 / (2.0 * total)
    margin = z * math.sqrt((phat * (1.0 - phat) + z2 / (4.0 * total)) / total)
    return min(1.0, (center + margin) / denom)


def _summarize_attempts_by_corpus(
    attempts: Sequence[BluebookCitationFuzzAttempt],
    *,
    max_acceptable_failure_rate: float,
    min_actionable_failures: int,
) -> Dict[str, Any]:
    by_corpus: Dict[str, List[BluebookCitationFuzzAttempt]] = {}
    for attempt in attempts:
        corpus_key = _attempt_corpus_key(attempt)
        by_corpus.setdefault(corpus_key, []).append(attempt)

    summary_rows: List[Dict[str, Any]] = []
    for corpus_key, corpus_attempts in sorted(by_corpus.items()):
        total = len(corpus_attempts)
        failures = sum(1 for item in corpus_attempts if not _attempt_succeeded(item))
        successes = total - failures
        failure_rate = (failures / total) if total else 0.0
        upper_bound = _wilson_upper_bound(failures, total)
        actionable = failures >= max(1, int(min_actionable_failures)) and upper_bound > float(max_acceptable_failure_rate)
        sample_failure_examples = [
            {
                "citation_text": item.candidate.citation_text,
                "state_code": item.candidate.state_code,
                "notes": item.candidate.notes,
            }
            for item in corpus_attempts
            if not _attempt_succeeded(item)
        ][:5]
        summary_rows.append(
            {
                "corpus_key": corpus_key,
                "sample_count": total,
                "success_count": successes,
                "failure_count": failures,
                "failure_rate": failure_rate,
                "estimated_success_rate": (successes / total) if total else 0.0,
                "wilson_upper_bound_95": upper_bound,
                "wilson_lower_bound_success_95": max(0.0, 1.0 - upper_bound),
                "max_acceptable_failure_rate": float(max_acceptable_failure_rate),
                "actionable_failure_cluster": actionable,
                "sample_failure_examples": sample_failure_examples,
            }
        )

    actionable = [row for row in summary_rows if bool(row.get("actionable_failure_cluster"))]
    return {
        "per_corpus": summary_rows,
        "actionable_corpora": [row["corpus_key"] for row in actionable],
        "actionable_corpus_count": len(actionable),
    }


def _cluster_failure_recoveries(attempts: Sequence[BluebookCitationFuzzAttempt]) -> List[Dict[str, Any]]:
    clusters: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    for attempt in attempts:
        if _attempt_succeeded(attempt):
            continue
        corpus_key = _attempt_corpus_key(attempt)
        for recovery in attempt.recoveries:
            scraper_patch = dict(recovery.get("scraper_patch") or {})
            host = str(scraper_patch.get("host") or "").strip()
            target_file = str(scraper_patch.get("target_file") or "").strip()
            key = (corpus_key, host, target_file)
            cluster = clusters.setdefault(
                key,
                {
                    "corpus_key": corpus_key,
                    "host": host,
                    "target_file": target_file,
                    "failure_count": 0,
                    "citations": [],
                    "manifest_paths": [],
                    "patch_paths": [],
                },
            )
            cluster["failure_count"] += 1
            citation_text = str(recovery.get("citation_text") or attempt.candidate.citation_text or "").strip()
            if citation_text and citation_text not in cluster["citations"]:
                cluster["citations"].append(citation_text)
            manifest_path = str(recovery.get("manifest_path") or "").strip()
            if manifest_path and manifest_path not in cluster["manifest_paths"]:
                cluster["manifest_paths"].append(manifest_path)
            patch_path = str(scraper_patch.get("patch_path") or "").strip()
            if patch_path and patch_path not in cluster["patch_paths"]:
                cluster["patch_paths"].append(patch_path)

    ordered = sorted(clusters.values(), key=lambda item: (-int(item["failure_count"]), item["corpus_key"], item["host"], item["target_file"]))
    for item in ordered:
        item["citations"] = item["citations"][:10]
    return ordered


def _summarize_scraper_coverage(attempts: Sequence[BluebookCitationFuzzAttempt]) -> Dict[str, Any]:
    by_target: Dict[str, Dict[str, Any]] = {}
    host_counts: Counter[str] = Counter()
    corpus_counts: Counter[str] = Counter()
    recovery_count = 0

    for attempt in attempts:
        corpus_key = _attempt_corpus_key(attempt)
        for recovery in attempt.recoveries:
            scraper_patch = recovery.get("scraper_patch") if isinstance(recovery.get("scraper_patch"), dict) else {}
            target_file = str(scraper_patch.get("target_file") or "").strip() or "unknown"
            host = str(scraper_patch.get("host") or "").strip() or "unknown"
            citation_text = str(recovery.get("citation_text") or attempt.candidate.citation_text or "").strip()
            recovery_count += 1
            host_counts[host] += 1
            corpus_counts[corpus_key] += 1

            row = by_target.setdefault(
                target_file,
                {
                    "target_file": target_file,
                    "recovery_count": 0,
                    "failure_count": 0,
                    "merge_status_counts": {},
                    "merge_success_count": 0,
                    "merge_failure_count": 0,
                    "target_local_parquet_paths": [],
                    "hosts": [],
                    "corpora": [],
                    "citations": [],
                },
            )
            row["recovery_count"] += 1
            if not _attempt_succeeded(attempt):
                row["failure_count"] += 1
            if host not in row["hosts"]:
                row["hosts"].append(host)
            if corpus_key not in row["corpora"]:
                row["corpora"].append(corpus_key)
            if citation_text and citation_text not in row["citations"]:
                row["citations"].append(citation_text)
            for merge_report in attempt.merge_reports:
                status = str(merge_report.get("status") or "unknown").strip() or "unknown"
                row["merge_status_counts"][status] = int(row["merge_status_counts"].get(status, 0)) + 1
                if status.lower() == "success":
                    row["merge_success_count"] += 1
                else:
                    row["merge_failure_count"] += 1
                target_path = str(merge_report.get("target_local_parquet_path") or "").strip()
                if target_path and target_path not in row["target_local_parquet_paths"]:
                    row["target_local_parquet_paths"].append(target_path)

    targets = sorted(by_target.values(), key=lambda item: (-int(item["recovery_count"]), item["target_file"]))
    for target in targets:
        target["hosts"] = sorted(target["hosts"])
        target["corpora"] = sorted(target["corpora"])
        target["citations"] = target["citations"][:10]
        target["merge_status_counts"] = dict(sorted(target["merge_status_counts"].items()))
        target["target_local_parquet_paths"] = target["target_local_parquet_paths"][:10]

    return {
        "recovery_count": recovery_count,
        "scraper_target_count": len(targets),
        "host_count": len(host_counts),
        "corpus_count": len(corpus_counts),
        "targets": targets,
        "hosts": dict(sorted(host_counts.items())),
        "corpora": dict(sorted(corpus_counts.items())),
    }


def _requested_fuzz_corpora(corpus_keys: Optional[Sequence[str]]) -> List[str]:
    values = [str(item or "").strip() for item in list(corpus_keys or []) if str(item or "").strip()]
    return values or list(_DEFAULT_FUZZ_CORPORA)


def _summarize_scraper_family_matrix(
    attempts: Sequence[BluebookCitationFuzzAttempt],
    *,
    requested_corpora: Sequence[str],
) -> Dict[str, Any]:
    requested = [str(item or "").strip() for item in requested_corpora if str(item or "").strip()]
    requested_set = set(requested)
    matrix: Dict[str, Dict[str, Any]] = {}

    def row_for(corpus_key: str) -> Dict[str, Any]:
        key = str(corpus_key or "").strip() or "unknown"
        return matrix.setdefault(
            key,
            {
                "corpus_key": key,
                "requested": key in requested_set,
                "attempt_count": 0,
                "matched_attempt_count": 0,
                "failed_attempt_count": 0,
                "recovery_count": 0,
                "merge_success_count": 0,
                "merge_failure_count": 0,
                "hosts": [],
                "target_files": [],
                "target_local_parquet_paths": [],
                "sample_citations": [],
            },
        )

    for corpus_key in requested:
        row_for(corpus_key)

    for attempt in attempts:
        corpus_key = _attempt_corpus_key(attempt)
        row = row_for(corpus_key)
        row["attempt_count"] += 1
        if _attempt_succeeded(attempt):
            row["matched_attempt_count"] += 1
        else:
            row["failed_attempt_count"] += 1
        citation_text = str(attempt.candidate.citation_text or "").strip()
        if citation_text and citation_text not in row["sample_citations"]:
            row["sample_citations"].append(citation_text)

        for recovery in attempt.recoveries:
            row["recovery_count"] += 1
            scraper_patch = recovery.get("scraper_patch") if isinstance(recovery.get("scraper_patch"), dict) else {}
            host = str(scraper_patch.get("host") or "").strip()
            if host and host not in row["hosts"]:
                row["hosts"].append(host)
            target_file = str(scraper_patch.get("target_file") or "").strip()
            if target_file and target_file not in row["target_files"]:
                row["target_files"].append(target_file)

        for merge_report in attempt.merge_reports:
            status = str(merge_report.get("status") or "unknown").strip().lower()
            if status == "success":
                row["merge_success_count"] += 1
            else:
                row["merge_failure_count"] += 1
            target_path = str(merge_report.get("target_local_parquet_path") or "").strip()
            if target_path and target_path not in row["target_local_parquet_paths"]:
                row["target_local_parquet_paths"].append(target_path)

    rows = []
    for row in matrix.values():
        row["hosts"] = sorted(row["hosts"])
        row["target_files"] = sorted(row["target_files"])
        row["target_local_parquet_paths"] = row["target_local_parquet_paths"][:10]
        row["sample_citations"] = row["sample_citations"][:10]
        rows.append(row)

    rows = sorted(rows, key=lambda item: (not bool(item["requested"]), item["corpus_key"]))
    missing_requested = [
        row["corpus_key"]
        for row in rows
        if bool(row["requested"]) and int(row["attempt_count"]) <= 0
    ]
    unmerged_recoveries = [
        row["corpus_key"]
        for row in rows
        if bool(row["requested"])
        and int(row["recovery_count"]) > 0
        and int(row["merge_success_count"]) <= 0
    ]

    return {
        "requested_corpora": requested,
        "covered_corpora": [row["corpus_key"] for row in rows if int(row["attempt_count"]) > 0],
        "missing_requested_corpora": missing_requested,
        "unmerged_recovery_corpora": unmerged_recoveries,
        "fully_merged_recovery_corpora": [
            row["corpus_key"]
            for row in rows
            if int(row["recovery_count"]) > 0 and int(row["merge_success_count"]) > 0 and int(row["merge_failure_count"]) <= 0
        ],
        "rows": rows,
    }


def _summarize_recovery_publication(attempts: Sequence[BluebookCitationFuzzAttempt]) -> Dict[str, Any]:
    status_counts: Counter[str] = Counter()
    repo_counts: Counter[str] = Counter()
    publish_error_counts: Counter[str] = Counter()
    upload_urls: List[str] = []
    patch_path_count = 0
    manifest_path_count = 0

    for attempt in attempts:
        for recovery in attempt.recoveries:
            status = str(recovery.get("status") or "unknown").strip() or "unknown"
            status_counts[status] += 1

            repo_id = str(recovery.get("hf_dataset_id") or "").strip()
            if repo_id:
                repo_counts[repo_id] += 1

            if str(recovery.get("manifest_path") or "").strip():
                manifest_path_count += 1

            scraper_patch = recovery.get("scraper_patch") if isinstance(recovery.get("scraper_patch"), dict) else {}
            if str(scraper_patch.get("patch_path") or "").strip():
                patch_path_count += 1

            publish_report = recovery.get("publish_report")
            if not isinstance(publish_report, dict):
                continue
            error = str(publish_report.get("error") or "").strip()
            if error:
                publish_error_counts[error] += 1
            upload_url = str(publish_report.get("upload_commit") or "").strip()
            if upload_url and upload_url not in upload_urls:
                upload_urls.append(upload_url)

    published_count = sum(count for status, count in status_counts.items() if "published" in status)
    return {
        "status_counts": dict(sorted(status_counts.items())),
        "published_count": published_count,
        "repo_counts": dict(sorted(repo_counts.items())),
        "publish_error_counts": dict(sorted(publish_error_counts.items())),
        "manifest_path_count": manifest_path_count,
        "patch_path_count": patch_path_count,
        "sample_upload_urls": upload_urls[:10],
    }


def _summarize_recovery_merges(attempts: Sequence[BluebookCitationFuzzAttempt]) -> Dict[str, Any]:
    status_counts: Counter[str] = Counter()
    target_paths: List[str] = []
    merge_report_paths: List[str] = []
    error_counts: Counter[str] = Counter()

    for attempt in attempts:
        for merge_report in attempt.merge_reports:
            status = str(merge_report.get("status") or "unknown").strip() or "unknown"
            status_counts[status] += 1
            target_path = str(merge_report.get("target_local_parquet_path") or "").strip()
            if target_path and target_path not in target_paths:
                target_paths.append(target_path)
            report_path = str(merge_report.get("merge_report_path") or "").strip()
            if report_path and report_path not in merge_report_paths:
                merge_report_paths.append(report_path)
            error = str(merge_report.get("error") or "").strip()
            if error:
                error_counts[error] += 1

    success_count = sum(count for status, count in status_counts.items() if status.lower() == "success")
    return {
        "status_counts": dict(sorted(status_counts.items())),
        "success_count": success_count,
        "failure_count": sum(status_counts.values()) - success_count,
        "target_local_parquet_paths": target_paths[:25],
        "merge_report_paths": merge_report_paths[:25],
        "error_counts": dict(sorted(error_counts.items())),
    }


def _load_candidate_file_metadata(candidate_file: Dict[str, Any]) -> Dict[str, Any]:
    metadata_path = str(candidate_file.get("metadata_path") or "").strip()
    if not metadata_path:
        return {}
    try:
        path = Path(metadata_path).expanduser()
        if not path.exists() or not path.is_file():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _summarize_recovery_artifact_quality(attempts: Sequence[BluebookCitationFuzzAttempt]) -> Dict[str, Any]:
    notes_counts: Counter[str] = Counter()
    content_type_counts: Counter[str] = Counter()
    common_crawl_domain_errors: Counter[str] = Counter()
    sample_unconfirmed: List[Dict[str, Any]] = []

    candidate_file_count = 0
    fetch_success_count = 0
    fetch_failure_count = 0
    validation_metadata_count = 0
    citation_confirmed_count = 0
    citation_unconfirmed_count = 0
    no_result_marker_count = 0
    blocked_page_count = 0

    for attempt in attempts:
        for recovery in attempt.recoveries:
            backend_status = recovery.get("search_backend_status") if isinstance(recovery.get("search_backend_status"), dict) else {}
            for domain, error in dict(backend_status.get("common_crawl_domain_errors") or {}).items():
                error_text = str(error or "").strip()
                if error_text:
                    common_crawl_domain_errors[f"{domain}:{error_text}"] += 1

            for candidate_file in list(recovery.get("candidate_files") or []):
                if not isinstance(candidate_file, dict):
                    continue
                candidate_file_count += 1
                if bool(candidate_file.get("fetch_success")):
                    fetch_success_count += 1
                else:
                    fetch_failure_count += 1

                for note in str(candidate_file.get("notes") or "").split(";"):
                    cleaned_note = note.strip()
                    if cleaned_note:
                        notes_counts[cleaned_note] += 1

                metadata = _load_candidate_file_metadata(candidate_file)
                content_type = str(metadata.get("content_type") or candidate_file.get("content_type") or "").strip()
                if content_type:
                    content_type_counts[content_type] += 1
                recipe = metadata.get("extraction_recipe") if isinstance(metadata.get("extraction_recipe"), dict) else {}
                if bool(recipe.get("blocked_signals_detected")):
                    blocked_page_count += 1
                validation = metadata.get("candidate_validation") if isinstance(metadata.get("candidate_validation"), dict) else {}
                if not validation:
                    continue
                validation_metadata_count += 1
                if bool(validation.get("no_result_detected")):
                    no_result_marker_count += 1
                if bool(validation.get("confirmed")):
                    citation_confirmed_count += 1
                else:
                    citation_unconfirmed_count += 1
                    if len(sample_unconfirmed) < 10:
                        sample_unconfirmed.append(
                            {
                                "citation_text": str(validation.get("citation_text") or recovery.get("citation_text") or attempt.candidate.citation_text or ""),
                                "candidate_url": str(candidate_file.get("url") or ""),
                                "metadata_path": str(candidate_file.get("metadata_path") or ""),
                                "notes": str(candidate_file.get("notes") or ""),
                                "matched_fragments": list(validation.get("matched_fragments") or [])[:8],
                                "no_result_detected": bool(validation.get("no_result_detected")),
                                "confidence": validation.get("confidence"),
                            }
                        )

    return {
        "candidate_file_count": candidate_file_count,
        "fetch_success_count": fetch_success_count,
        "fetch_failure_count": fetch_failure_count,
        "validation_metadata_count": validation_metadata_count,
        "citation_confirmed_count": citation_confirmed_count,
        "citation_unconfirmed_count": citation_unconfirmed_count,
        "no_result_marker_count": no_result_marker_count,
        "blocked_page_count": blocked_page_count,
        "notes_counts": dict(sorted(notes_counts.items())),
        "content_type_counts": dict(sorted(content_type_counts.items())),
        "common_crawl_domain_error_counts": dict(sorted(common_crawl_domain_errors.items())),
        "sample_unconfirmed": sample_unconfirmed,
    }


def _collect_malformed_repairs(
    candidates: Sequence[BluebookCitationCandidate],
) -> List[Dict[str, Any]]:
    repairs: Dict[tuple[str, str], Dict[str, Any]] = {}
    for candidate in candidates:
        raw = str(candidate.citation_text or "").strip()
        normalized = _normalize_malformed_citation(raw)
        if not raw or normalized == raw:
            continue
        key = (raw, normalized)
        entry = repairs.setdefault(
            key,
            {
                "raw_citation": raw,
                "normalized_citation": normalized,
                "count": 0,
                "examples": [],
            },
        )
        entry["count"] += 1
        examples = entry["examples"]
        if len(examples) < 3:
            examples.append(
                {
                    "state_code": candidate.state_code,
                    "corpus_key_hint": candidate.corpus_key_hint,
                    "context_text": candidate.context_text,
                }
            )
    ranked = sorted(repairs.values(), key=lambda item: (-int(item["count"]), item["raw_citation"]))
    return ranked


def _build_failure_backlog(
    *,
    attempts: Sequence[BluebookCitationFuzzAttempt],
    coverage_summary: Dict[str, Any],
    failure_patch_clusters: Sequence[Dict[str, Any]],
    scraper_coverage: Dict[str, Any],
    recovery_merge: Dict[str, Any],
    recovery_artifact_quality: Dict[str, Any],
    scraper_family_matrix: Dict[str, Any],
    malformed_repairs: Sequence[Dict[str, Any]],
    max_acceptable_failure_rate: float,
    min_actionable_failures: int,
) -> Dict[str, Any]:
    actionable_corpora = {
        str(item).strip()
        for item in list(coverage_summary.get("actionable_corpora") or [])
        if str(item).strip()
    }
    backlog_clusters: List[Dict[str, Any]] = []
    for cluster in failure_patch_clusters:
        corpus_key = str(cluster.get("corpus_key") or "").strip() or "unknown"
        if corpus_key not in actionable_corpora:
            continue
        matching_attempts = [
            attempt
            for attempt in attempts
            if not _attempt_succeeded(attempt)
            and _attempt_corpus_key(attempt) == corpus_key
            and any(
                str((recovery.get("scraper_patch") or {}).get("target_file") or "").strip() == str(cluster.get("target_file") or "").strip()
                and str((recovery.get("scraper_patch") or {}).get("host") or "").strip() == str(cluster.get("host") or "").strip()
                for recovery in attempt.recoveries
            )
        ]
        backlog_clusters.append(
            {
                **dict(cluster),
                "actionable": True,
                "recommended_next_step": "Use recovery candidates and manifest evidence to patch the target scraper, then rerun the seed-only audit for this corpus cluster.",
                "sample_contexts": [
                    {
                        "citation_text": attempt.candidate.citation_text,
                        "context_text": attempt.candidate.context_text,
                        "state_code": attempt.candidate.state_code,
                        "notes": attempt.candidate.notes,
                    }
                    for attempt in matching_attempts[:5]
                ],
            }
        )

    return {
        "max_acceptable_failure_rate": float(max_acceptable_failure_rate),
        "min_actionable_failures": int(min_actionable_failures),
        "actionable_corpora": sorted(actionable_corpora),
        "cluster_count": len(backlog_clusters),
        "clusters": backlog_clusters,
        "scraper_coverage": dict(scraper_coverage or {}),
        "scraper_family_matrix": dict(scraper_family_matrix or {}),
        "recovery_merge": dict(recovery_merge or {}),
        "recovery_artifact_quality": dict(recovery_artifact_quality or {}),
        "malformed_repairs": list(malformed_repairs or [])[:50],
    }


async def run_bluebook_linker_fuzz_harness(
    *,
    sample_count: int = 12,
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
    temperature: float = 1.0,
    corpus_keys: Optional[Sequence[str]] = None,
    state_codes: Optional[Sequence[str]] = None,
    adversarial_ratio: float = 0.35,
    allow_hf_fallback: bool = True,
    prefer_hf_corpora: bool = False,
    primary_corpora_only: bool = False,
    exact_state_partitions_only: bool = False,
    materialize_hf_corpora: bool = False,
    exhaustive: bool = True,
    enable_recovery: bool = True,
    recovery_max_candidates: int = 8,
    recovery_archive_top_k: int = 3,
    publish_to_hf: bool = False,
    hf_token: Optional[str] = None,
    merge_recovered_rows: bool = False,
    hydrate_merge_from_hf: bool = False,
    publish_merged_parquet_to_hf: bool = False,
    seed_from_corpora: bool = False,
    seed_only: bool = False,
    seed_examples_per_corpus: int = 2,
    max_seed_examples_per_state: Optional[int] = None,
    max_seed_examples_per_source: Optional[int] = None,
    sampling_shuffle_seed: int = 0,
    max_acceptable_failure_rate: float = 0.10,
    min_actionable_failures: int = 2,
    output_dir: Optional[str | Path] = None,
    resolver: Optional[BluebookCitationResolver] = None,
    llm_generate_func: Optional[Callable[..., str]] = None,
    resolve_document_func: Optional[Callable[..., Dict[str, Any]]] = None,
    recovery_func: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
    merge_manifest_func: Optional[Callable[..., Dict[str, Any]]] = None,
) -> BluebookCitationFuzzRun:
    active_resolver = resolver or BluebookCitationResolver(
        allow_hf_fallback=allow_hf_fallback,
        prefer_hf_sources=prefer_hf_corpora,
        primary_corpora_only=primary_corpora_only,
        exact_state_partition_only=exact_state_partitions_only,
        materialize_remote_sources=materialize_hf_corpora,
    )
    seeded_candidates = collect_seeded_bluebook_fuzz_candidates(
        resolver=active_resolver,
        corpus_keys=corpus_keys,
        state_codes=state_codes,
        examples_per_corpus=seed_examples_per_corpus,
        sample_count=sample_count if (seed_from_corpora or seed_only) else None,
        max_examples_per_state=max_seed_examples_per_state,
        max_examples_per_source=max_seed_examples_per_source,
        shuffle_seed=sampling_shuffle_seed,
    ) if seed_from_corpora else []
    seeded_examples = [asdict(item) for item in seeded_candidates]
    prompt = build_bluebook_fuzz_generation_prompt(
        sample_count=sample_count,
        corpus_keys=corpus_keys,
        state_codes=state_codes,
        adversarial_ratio=adversarial_ratio,
        seeded_examples=seeded_examples,
    )

    if seed_only:
        raw_generation = ""
        candidates = list(seeded_candidates)[: max(1, int(sample_count))]
        generation_parse_error = None
        used_fallback_candidates = False
    else:
        active_generate = llm_generate_func or llm_router.generate_text
        raw_generation = active_generate(
            prompt,
            provider=provider,
            model_name=model_name,
            temperature=temperature,
        )
        try:
            candidates = parse_bluebook_fuzz_candidates(raw_generation)[: max(1, int(sample_count))]
            generation_parse_error = None
            used_fallback_candidates = False
        except ValueError as exc:
            generation_parse_error = str(exc)
            fallback_candidates = list(seeded_candidates) or _fallback_bluebook_fuzz_candidates(
                sample_count=sample_count,
                corpus_keys=corpus_keys,
                state_codes=state_codes,
            )
            candidates = fallback_candidates[: max(1, int(sample_count))]
            used_fallback_candidates = True

    active_resolve_document = resolve_document_func or resolve_bluebook_lookup_result_document
    active_recovery = recovery_func or recover_missing_legal_citation_source
    active_merge = merge_manifest_func or merge_recovery_manifest_into_canonical_dataset

    attempts: List[BluebookCitationFuzzAttempt] = []
    matched_attempts = 0
    unmatched_citations = 0
    recovery_count = 0
    merged_count = 0

    for ordinal, candidate in enumerate(candidates, start=1):
        candidate_resolver = active_resolver
        candidate_source_ref = _candidate_source_ref(candidate)
        candidate_corpus_key = str(candidate.corpus_key_hint or "").strip()
        if resolve_document_func is None and candidate_source_ref and candidate_corpus_key:
            candidate_resolver = BluebookCitationResolver(
                allow_hf_fallback=bool(getattr(active_resolver, "allow_hf_fallback", allow_hf_fallback)),
                prefer_hf_sources=bool(getattr(active_resolver, "prefer_hf_sources", prefer_hf_corpora)),
                primary_corpora_only=bool(getattr(active_resolver, "primary_corpora_only", primary_corpora_only)),
                exact_state_partition_only=bool(getattr(active_resolver, "exact_state_partition_only", exact_state_partitions_only)),
                materialize_remote_sources=bool(getattr(active_resolver, "materialize_remote_sources", materialize_hf_corpora)),
                require_exact_anchor=bool(getattr(active_resolver, "require_exact_anchor", True)),
                parquet_file_overrides={candidate_corpus_key: [candidate_source_ref]},
                extractor=getattr(active_resolver, "extractor", None),
            )
        resolution = None
        if resolve_document_func is None:
            resolution = _resolve_candidate_from_seeded_row_cache(
                candidate,
                resolver=candidate_resolver,
                exhaustive=exhaustive,
            )
        if resolution is None:
            resolution = active_resolve_document(
                candidate.render_document_text(),
                state_code=candidate.state_code,
                resolver=candidate_resolver,
                exhaustive=exhaustive,
                include_recovery=False,
                include_suggestions=False,
            )

        if int(resolution.get("matched_citation_count") or 0) > 0:
            matched_attempts += 1
        unmatched_payloads = [dict(item) for item in list(resolution.get("unresolved_citations") or []) if isinstance(item, dict)]
        if (
            enable_recovery
            and not unmatched_payloads
            and int(resolution.get("matched_citation_count") or 0) <= 0
            and int(resolution.get("citation_count") or 0) <= 0
            and candidate.expected_valid is True
            and str(candidate.citation_text or "").strip()
        ):
            unmatched_payloads = [
                {
                    "citation_text": str(candidate.citation_text or "").strip(),
                    "normalized_citation": str(candidate.citation_text or "").strip(),
                    "corpus_key": str(candidate.corpus_key_hint or "").strip(),
                    "metadata": {
                        "recovery_corpus_key": str(candidate.corpus_key_hint or "").strip(),
                        "state_code": str(candidate.state_code or "").strip().upper(),
                        "candidate_corpora": [str(candidate.corpus_key_hint or "").strip()]
                        if str(candidate.corpus_key_hint or "").strip()
                        else [],
                        "recovery_reason": "expected_valid_candidate_not_extracted",
                    },
                }
            ]
            resolution["unresolved_citations"] = unmatched_payloads
            resolution["unmatched_citation_count"] = 1
            resolution["citation_count"] = 1
        unmatched_citations += len(unmatched_payloads)

        recoveries: List[Dict[str, Any]] = []
        merge_reports: List[Dict[str, Any]] = []
        if enable_recovery:
            for unresolved in unmatched_payloads:
                metadata = dict(unresolved.get("metadata") or {})
                recovery_corpus_key = (
                    str(metadata.get("recovery_corpus_key") or unresolved.get("corpus_key") or "").strip()
                    or str(candidate.corpus_key_hint or "").strip()
                    or None
                )
                recovery_state_code = (
                    str(metadata.get("state_code") or "").strip().upper()
                    or str(candidate.state_code or "").strip().upper()
                    or None
                )
                recovery = await active_recovery(
                    citation_text=str(unresolved.get("citation_text") or ""),
                    normalized_citation=str(unresolved.get("normalized_citation") or unresolved.get("citation_text") or ""),
                    corpus_key=recovery_corpus_key,
                    state_code=recovery_state_code,
                    metadata={
                        "candidate_corpora": list(metadata.get("candidate_corpora") or []),
                    },
                    max_candidates=recovery_max_candidates,
                    archive_top_k=recovery_archive_top_k,
                    publish_to_hf=publish_to_hf,
                    hf_token=hf_token,
                )
                recoveries.append(dict(recovery))
                recovery_count += 1

                manifest_path = str(recovery.get("manifest_path") or "").strip()
                if merge_recovered_rows and manifest_path:
                    if hydrate_merge_from_hf or publish_merged_parquet_to_hf:
                        merge_report = active_merge(
                            manifest_path,
                            hydrate_from_hf=True,
                            hf_token=hf_token,
                            publish_merged_to_hf=publish_merged_parquet_to_hf,
                        )
                    else:
                        merge_report = active_merge(manifest_path)
                    merge_reports.append(dict(merge_report))
                    if str(merge_report.get("status") or "").lower() == "success":
                        merged_count += 1

        attempts.append(
            BluebookCitationFuzzAttempt(
                ordinal=ordinal,
                candidate=candidate,
                resolution=dict(resolution),
                recoveries=recoveries,
                merge_reports=merge_reports,
            )
        )

    summary = {
        "sample_count_requested": int(sample_count),
        "sample_count_executed": len(candidates),
        "matched_attempt_count": matched_attempts,
        "matched_attempt_ratio": (matched_attempts / len(candidates)) if candidates else 0.0,
        "unmatched_citation_count": unmatched_citations,
        "recovery_count": recovery_count,
        "merged_recovery_count": merged_count,
        "provider": provider,
        "model_name": model_name,
        "allow_hf_fallback": bool(allow_hf_fallback),
        "prefer_hf_corpora": bool(prefer_hf_corpora),
        "primary_corpora_only": bool(primary_corpora_only),
        "exact_state_partitions_only": bool(exact_state_partitions_only),
        "materialize_hf_corpora": bool(materialize_hf_corpora),
        "exhaustive": bool(exhaustive),
        "publish_to_hf": bool(publish_to_hf),
        "merge_recovered_rows": bool(merge_recovered_rows),
        "hydrate_merge_from_hf": bool(hydrate_merge_from_hf),
        "publish_merged_parquet_to_hf": bool(publish_merged_parquet_to_hf),
        "seed_from_corpora": bool(seed_from_corpora),
        "seed_only": bool(seed_only),
        "seeded_example_count": len(seeded_examples),
        "generation_parse_error": generation_parse_error,
        "used_fallback_candidates": used_fallback_candidates,
        "max_acceptable_failure_rate": float(max_acceptable_failure_rate),
        "min_actionable_failures": int(min_actionable_failures),
    }
    summary["coverage_by_corpus"] = _summarize_attempts_by_corpus(
        attempts,
        max_acceptable_failure_rate=max_acceptable_failure_rate,
        min_actionable_failures=min_actionable_failures,
    )
    summary["recovery_publication"] = _summarize_recovery_publication(attempts)
    summary["recovery_merge"] = _summarize_recovery_merges(attempts)
    summary["recovery_artifact_quality"] = _summarize_recovery_artifact_quality(attempts)
    summary["failure_patch_clusters"] = _cluster_failure_recoveries(attempts)
    summary["scraper_coverage"] = _summarize_scraper_coverage(attempts)
    summary["scraper_family_matrix"] = _summarize_scraper_family_matrix(
        attempts,
        requested_corpora=_requested_fuzz_corpora(corpus_keys),
    )
    summary["malformed_repairs"] = _collect_malformed_repairs(candidates)
    summary["sampling"] = {
        "seed_examples_per_corpus": int(seed_examples_per_corpus),
        "max_seed_examples_per_state": int(max_seed_examples_per_state or seed_examples_per_corpus),
        "max_seed_examples_per_source": int(max_seed_examples_per_source or max_seed_examples_per_state or seed_examples_per_corpus),
        "sampling_shuffle_seed": int(sampling_shuffle_seed),
    }
    failure_backlog = _build_failure_backlog(
        attempts=attempts,
        coverage_summary=summary["coverage_by_corpus"],
        failure_patch_clusters=summary["failure_patch_clusters"],
        scraper_coverage=summary["scraper_coverage"],
        recovery_merge=summary["recovery_merge"],
        recovery_artifact_quality=summary["recovery_artifact_quality"],
        scraper_family_matrix=summary["scraper_family_matrix"],
        malformed_repairs=summary["malformed_repairs"],
        max_acceptable_failure_rate=max_acceptable_failure_rate,
        min_actionable_failures=min_actionable_failures,
    )
    summary["failure_patch_backlog"] = failure_backlog

    output_path: Optional[str] = None
    run = BluebookCitationFuzzRun(
        prompt=prompt,
        raw_generation=str(raw_generation),
        candidates=candidates,
        attempts=attempts,
        summary=summary,
        seeded_examples=seeded_examples,
    )
    if output_dir is not None:
        output_root = Path(output_dir).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        output_file = output_root / "bluebook_linker_fuzz_run.json"
        backlog_file = output_root / "bluebook_linker_fuzz_patch_backlog.json"
        repairs_file = output_root / "bluebook_linker_fuzz_malformed_repairs.json"
        run.summary["failure_patch_backlog_path"] = str(backlog_file)
        run.summary["malformed_repairs_path"] = str(repairs_file)
        output_path = str(output_file)
        run.output_path = output_path
        output_file.write_text(json.dumps(run.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        backlog_file.write_text(json.dumps(failure_backlog, indent=2, sort_keys=True), encoding="utf-8")
        repairs_file.write_text(json.dumps(summary["malformed_repairs"], indent=2, sort_keys=True), encoding="utf-8")

    return run


__all__ = [
    "BluebookCitationCandidate",
    "BluebookCitationFuzzAttempt",
    "BluebookCitationFuzzRun",
    "build_bluebook_fuzz_generation_prompt",
    "collect_seeded_bluebook_fuzz_candidates",
    "parse_bluebook_fuzz_candidates",
    "run_bluebook_linker_fuzz_harness",
]
