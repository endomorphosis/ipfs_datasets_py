"""Resolve Bluebook-style citations against canonical legal corpora."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .canonical_legal_corpora import get_canonical_legal_corpus
from .citation_extraction import Citation, CitationExtractor
from .legal_source_recovery import build_missing_citation_recovery_query

logger = logging.getLogger(__name__)

_IDENTIFIER_FIELDS = ["statute_id", "identifier", "id", "document_number", "citation", "name", "rule_id", "source_id"]
_TITLE_FIELDS = ["section_name", "short_title", "heading", "title", "name", "title_name", "code_name"]
_URL_FIELDS = ["source_url", "url", "html_url", "pdf_url", "fr_page_url", "fr_json_url"]
_TEXT_FIELDS = ["full_text", "text", "section_text", "content", "body", "semantic_text", "summary", "head_matter"]
_CID_FIELDS = ["ipfs_cid", "cid", "source_cid"]
_OFFICIAL_CITE_FIELDS = ["official_cite", "citation", "bluebook_citation", "identifier"]
_STATE_FIELDS = ["state_code", "state"]
_SECTION_FIELDS = ["section", "section_number", "section_id", "title_num", "section_num"]
_TITLE_NUMBER_FIELDS = ["title", "title_number", "title_no", "usc_title", "title_num"]
_CODE_NAME_FIELDS = ["code_name", "code", "code_title", "title_name"]
_VOLUME_FIELDS = ["volume", "volume_number", "fr_volume"]
_PAGE_FIELDS = ["page", "page_number", "start_page", "page_start", "fr_page"]
_REPORTER_FIELDS = ["reporter", "reporter_abbrev", "reporter_abbreviation", "publication", "series"]
_CONGRESS_FIELDS = ["congress", "congress_number", "session", "volume"]
_LAW_NUMBER_FIELDS = ["law_number", "public_law", "public_law_number", "pl_number", "page"]


@dataclass(frozen=True)
class CorpusSourceConfig:
    key: str
    dataset_id: Optional[str]
    local_roots: Sequence[Path]
    preferred_parquet_names: Sequence[str] = field(default_factory=tuple)
    parquet_prefix: Optional[str] = None
    state_field: Optional[str] = None
    cid_field: str = "cid"
    dataset_id_aliases: Sequence[str] = field(default_factory=tuple)
    preferred_path_substrings: Sequence[str] = field(default_factory=tuple)


@dataclass
class CitationLink:
    citation_text: str
    citation_type: str
    normalized_citation: str
    matched: bool
    corpus_key: Optional[str] = None
    dataset_id: Optional[str] = None
    matched_field: Optional[str] = None
    confidence: float = 0.0
    source_document_id: Optional[str] = None
    source_title: Optional[str] = None
    source_url: Optional[str] = None
    source_cid: Optional[str] = None
    source_ref: Optional[str] = None
    snippet: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def citation_link_to_dict(link: CitationLink) -> Dict[str, Any]:
    return {
        "citation_text": link.citation_text,
        "citation_type": link.citation_type,
        "normalized_citation": link.normalized_citation,
        "matched": bool(link.matched),
        "corpus_key": link.corpus_key,
        "dataset_id": link.dataset_id,
        "matched_field": link.matched_field,
        "confidence": float(link.confidence),
        "source_document_id": link.source_document_id,
        "source_title": link.source_title,
        "source_url": link.source_url,
        "source_cid": link.source_cid,
        "source_ref": link.source_ref,
        "snippet": link.snippet,
        "metadata": dict(link.metadata),
    }


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("§", " section ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _normalize_section(value: Any) -> str:
    text = str(value or "").strip()
    text = text.lstrip("§ ").strip()
    return text.lower()


def _compact_alnum(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _state_section_aliases(section: Any) -> List[str]:
    raw = str(section or "").strip()
    if not raw:
        return []
    lowered = raw.lower()
    normalized = re.sub(r"^(section|rule|part)[\s:-]+", "", lowered).strip()
    candidates = [lowered]
    if normalized and normalized != lowered:
        candidates.append(normalized)
    if normalized:
        candidates.extend([
            f"section-{normalized}",
            f"section {normalized}",
            f"rule-{normalized}",
            f"rule {normalized}",
            f"part-{normalized}",
            f"part {normalized}",
        ])

    aliases: List[str] = []
    for candidate in candidates:
        candidate = candidate.strip()
        if candidate and candidate not in aliases:
            aliases.append(candidate)
    return aliases


def _first_present(row: Dict[str, Any], fields: Iterable[str]) -> Optional[Any]:
    for field in fields:
        if field in row and row.get(field) not in (None, ""):
            return row.get(field)
    return None


def _sql_literal_path(value: str) -> str:
    return str(value).replace("'", "''")


def _dataset_server_parquet_records(dataset_id: str) -> List[Dict[str, Any]]:
    try:
        import requests
    except Exception:
        return []

    dataset = str(dataset_id or "").strip()
    if not dataset:
        return []
    url = f"https://datasets-server.huggingface.co/parquet?dataset={dataset}"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.warning("Failed to fetch datasets-server parquet listing for %s: %s", dataset, exc)
        return []

    records = payload.get("parquet_files") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        record_url = str(item.get("url") or "").strip()
        if not record_url:
            continue
        normalized.append(
            {
                "dataset": str(item.get("dataset") or dataset),
                "config": str(item.get("config") or ""),
                "split": str(item.get("split") or ""),
                "filename": str(item.get("filename") or ""),
                "url": record_url,
            }
        )
    return normalized


def _is_direct_citation_source(path: str) -> bool:
    normalized = str(path or "").strip().lower()
    if not normalized:
        return False
    return not (
        normalized.endswith("_embeddings.parquet")
        or normalized.endswith("_metadata.parquet")
        or normalized.endswith(".faiss")
        or normalized.endswith(".index")
    )


def _inventory_profiles_for_repo(repo_id: str, corpus_key: str) -> List[Any]:
    try:
        from .justicedao_dataset_inventory import inspect_justicedao_datasets

        profiles = inspect_justicedao_datasets(dataset_prefix="")
    except Exception:
        return []

    matches: List[Any] = []
    normalized_repo = str(repo_id or "").strip()
    normalized_corpus = str(corpus_key or "").strip().lower()
    for profile in profiles:
        dataset_id = str(getattr(profile, "dataset_id", "") or "").strip()
        canonical_corpus_key = str(getattr(profile, "canonical_corpus_key", "") or "").strip().lower()
        if dataset_id == normalized_repo or canonical_corpus_key == normalized_corpus:
            matches.append(profile)
    return matches


def _inventory_bonus_for_candidate(
    repo_id: str,
    corpus_key: str,
    candidate: str,
    *,
    state_code: Optional[str],
) -> int:
    profiles = _inventory_profiles_for_repo(repo_id, corpus_key)
    if not profiles:
        return 0

    candidate_text = str(candidate or "").strip()
    candidate_lower = candidate_text.lower()
    bonus = 0
    for profile in profiles:
        parquet_files = [str(item) for item in list(getattr(profile, "parquet_files", []) or [])]
        if candidate_text in parquet_files:
            bonus += 200

        query_modes: set[str] = set()
        for config in list(getattr(profile, "configs", []) or []):
            for mode in list(getattr(config, "query_modes", []) or []):
                text = str(mode or "").strip().lower()
                if text:
                    query_modes.add(text)

        if _is_direct_citation_source(candidate_text):
            bonus += 60
            if query_modes.intersection({"identifier_lookup", "citation_lookup", "section_lookup", "state_section_lookup", "jsonld_lookup"}):
                bonus += 40
        else:
            bonus -= 120

        if state_code and f"state-{str(state_code).strip().lower()}" in candidate_lower:
            bonus += 80

    return bonus


def _order_dataset_server_parquet_records(
    config: CorpusSourceConfig,
    parquet_records: Sequence[Dict[str, Any]],
    *,
    state_code: Optional[str],
) -> List[str]:
    preferred_names = list(config.preferred_parquet_names)
    if state_code and config.state_field and config.key in {"state_laws", "state_admin_rules", "state_court_rules"}:
        preferred_names.insert(0, get_canonical_legal_corpus(config.key).state_parquet_filename(state_code))

    prefix = str(config.parquet_prefix or "").strip("/").lower()
    path_hints = [str(item).strip("/").lower() for item in list(config.preferred_path_substrings or []) if str(item).strip()]
    if prefix:
        path_hints.insert(0, prefix)

    def _score(record: Dict[str, Any]) -> tuple[int, int, str]:
        record_url = str(record.get("url") or "")
        config_name = str(record.get("config") or "")
        filename = str(record.get("filename") or "")
        haystack = " ".join([record_url, config_name, filename]).lower()
        score = 0

        for index, preferred_name in enumerate(preferred_names):
            preferred_lower = str(preferred_name).lower()
            if not preferred_lower:
                continue
            weight = max(1, 100 - index)
            if preferred_lower in haystack:
                score += 180 + weight

        for hint in path_hints:
            if hint and hint in haystack:
                score += 70

        if "canonical" in haystack:
            score += 220
        if "default" in haystack:
            score += 140
        if config.key == "federal_register" and "federal_register" in haystack:
            score += 100
        if config.key == "us_code" and "uscode" in haystack:
            score += 100

        if state_code:
            state_token = f"state-{str(state_code).strip().lower()}"
            if state_token in haystack:
                score += 160

        if "embedding" in haystack or "embeddings" in haystack or "vector" in haystack:
            score -= 260
        if "metadata" in haystack:
            score -= 180
        if "faiss" in haystack or haystack.endswith(".index"):
            score -= 400

        return (-score, len(record_url), record_url)

    ordered = [str(item.get("url") or "") for item in sorted(parquet_records, key=_score) if str(item.get("url") or "")]
    deduped: List[str] = []
    seen: set[str] = set()
    for item in ordered:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped[:8]


def _citation_match_terms(citation: Citation) -> List[str]:
    terms: List[str] = []

    def _add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in terms:
            terms.append(text)

    _add(citation.text)
    if citation.type == "usc" and citation.title and citation.section:
        _add(f"{citation.title} U.S.C. § {citation.section}")
        _add(f"{citation.title} USC {citation.section}")
        _add(f"{citation.title} U.S.C. {citation.section}")
    elif citation.type == "cfr" and citation.title and citation.section:
        _add(f"{citation.title} C.F.R. § {citation.section}")
        _add(f"{citation.title} CFR {citation.section}")
        _add(f"{citation.title} C.F.R. {citation.section}")
    elif citation.type == "federal_register" and citation.volume and citation.page:
        _add(f"{citation.volume} FR {citation.page}")
        _add(f"{citation.volume} Fed. Reg. {citation.page}")
    elif citation.type == "public_law" and citation.volume and citation.page:
        _add(f"Pub. L. {citation.volume}-{citation.page}")
        _add(f"Pub. L. No. {citation.volume}-{citation.page}")
        _add(f"P.L. {citation.volume}-{citation.page}")
        _add(f"Public Law {citation.volume}-{citation.page}")
    elif citation.type == "state_statute" and citation.section:
        state_abbrev = str(citation.metadata.get("bluebook_state_abbrev") or "").strip()
        code_name = str(citation.metadata.get("code_name") or citation.title or "").strip()
        if state_abbrev and code_name:
            _add(f"{state_abbrev} {code_name} § {citation.section}")
            _add(f"{state_abbrev} {code_name} {citation.section}")
        if code_name:
            _add(f"{code_name} § {citation.section}")
            _add(f"{code_name} {citation.section}")
        for alias in _state_section_aliases(citation.section):
            _add(alias)
    elif citation.type == "case" and citation.volume and citation.reporter and citation.page:
        _add(f"{citation.volume} {citation.reporter} {citation.page}")
        _add(f"{citation.volume} {citation.reporter.replace('.', '').strip()} {citation.page}")
    return terms


def _build_uscode_source_config() -> CorpusSourceConfig:
    corpus = get_canonical_legal_corpus("us_code")
    return CorpusSourceConfig(
        key="us_code",
        dataset_id=corpus.hf_dataset_id,
        local_roots=(corpus.parquet_dir(), (Path.home() / ".ipfs_datasets" / "us_code").resolve()),
        preferred_parquet_names=("uscode.parquet", "uscode", "sections", "title"),
        parquet_prefix=corpus.parquet_dir_name,
        cid_field=corpus.cid_field,
        preferred_path_substrings=("uscode_parquet/",),
    )


_CORPUS_CONFIGS: Dict[str, CorpusSourceConfig] = {
    "caselaw_access_project": CorpusSourceConfig(
        key="caselaw_access_project",
        dataset_id=get_canonical_legal_corpus("caselaw_access_project").hf_dataset_id,
        local_roots=(get_canonical_legal_corpus("caselaw_access_project").parquet_dir(),),
        preferred_parquet_names=(
            get_canonical_legal_corpus("caselaw_access_project").combined_parquet_filename,
            "ipfs_caselaw_access_project.parquet",
            "caselaw",
            "cap",
        ),
        parquet_prefix=get_canonical_legal_corpus("caselaw_access_project").parquet_dir_name,
        cid_field=get_canonical_legal_corpus("caselaw_access_project").cid_field,
        dataset_id_aliases=(
            "justicedao/dedup_ipfs_caselaw_access_project",
            "justicedao/caselaw_access_project",
        ),
        preferred_path_substrings=("repaired_parquet_batch", "repaired_parquet_shards", "caselaw"),
    ),
    "us_code": _build_uscode_source_config(),
    "federal_register": CorpusSourceConfig(
        key="federal_register",
        dataset_id=get_canonical_legal_corpus("federal_register").hf_dataset_id,
        local_roots=(get_canonical_legal_corpus("federal_register").parquet_dir(),),
        preferred_parquet_names=("federal_register.parquet", "laws.parquet", "federal_register"),
        parquet_prefix=get_canonical_legal_corpus("federal_register").parquet_dir_name,
        cid_field=get_canonical_legal_corpus("federal_register").cid_field,
    ),
    "state_laws": CorpusSourceConfig(
        key="state_laws",
        dataset_id=get_canonical_legal_corpus("state_laws").hf_dataset_id,
        local_roots=(get_canonical_legal_corpus("state_laws").parquet_dir(),),
        preferred_parquet_names=("state_laws_all_states.parquet",),
        parquet_prefix=get_canonical_legal_corpus("state_laws").parquet_dir_name,
        state_field=get_canonical_legal_corpus("state_laws").state_field,
        cid_field=get_canonical_legal_corpus("state_laws").cid_field,
        preferred_path_substrings=("state_laws_parquet_cid/",),
    ),
    "state_admin_rules": CorpusSourceConfig(
        key="state_admin_rules",
        dataset_id=get_canonical_legal_corpus("state_admin_rules").hf_dataset_id,
        local_roots=(get_canonical_legal_corpus("state_admin_rules").parquet_dir(),),
        preferred_parquet_names=("state_admin_rules_all_states.parquet",),
        parquet_prefix=get_canonical_legal_corpus("state_admin_rules").parquet_dir_name,
        state_field=get_canonical_legal_corpus("state_admin_rules").state_field,
        cid_field=get_canonical_legal_corpus("state_admin_rules").cid_field,
        preferred_path_substrings=("state_admin_rules_cid/",),
    ),
    "state_court_rules": CorpusSourceConfig(
        key="state_court_rules",
        dataset_id=get_canonical_legal_corpus("state_court_rules").hf_dataset_id,
        local_roots=(get_canonical_legal_corpus("state_court_rules").parquet_dir(),),
        preferred_parquet_names=("state_court_rules_all_states.parquet",),
        parquet_prefix=get_canonical_legal_corpus("state_court_rules").parquet_dir_name,
        state_field=get_canonical_legal_corpus("state_court_rules").state_field,
        cid_field=get_canonical_legal_corpus("state_court_rules").cid_field,
        preferred_path_substrings=("state_court_rules_parquet_cid/",),
    ),
    "netherlands_laws": CorpusSourceConfig(
        key="netherlands_laws",
        dataset_id=get_canonical_legal_corpus("netherlands_laws").hf_dataset_id,
        local_roots=(get_canonical_legal_corpus("netherlands_laws").parquet_dir(),),
        preferred_parquet_names=("netherlands_laws.parquet", "laws.parquet", "articles.parquet", "cid_index.parquet"),
        parquet_prefix="parquet",
        cid_field=get_canonical_legal_corpus("netherlands_laws").cid_field,
        preferred_path_substrings=("parquet/laws/", "parquet/articles/", "parquet/cid_index/"),
    ),
    "france_laws": CorpusSourceConfig(
        key="france_laws",
        dataset_id=get_canonical_legal_corpus("france_laws").hf_dataset_id,
        local_roots=(get_canonical_legal_corpus("france_laws").parquet_dir(),),
        preferred_parquet_names=("france_laws.parquet", "laws.parquet", "articles.parquet", "cid_index.parquet"),
        parquet_prefix="parquet",
        cid_field=get_canonical_legal_corpus("france_laws").cid_field,
        preferred_path_substrings=("parquet/laws/", "parquet/articles/", "parquet/cid_index/"),
    ),
    "spain_laws": CorpusSourceConfig(
        key="spain_laws",
        dataset_id=get_canonical_legal_corpus("spain_laws").hf_dataset_id,
        local_roots=(get_canonical_legal_corpus("spain_laws").parquet_dir(),),
        preferred_parquet_names=("spain_laws.parquet", "laws.parquet", "articles.parquet", "cid_index.parquet"),
        parquet_prefix="parquet",
        cid_field=get_canonical_legal_corpus("spain_laws").cid_field,
        preferred_path_substrings=("parquet/laws/", "parquet/articles/", "parquet/cid_index/"),
    ),
    "germany_laws": CorpusSourceConfig(
        key="germany_laws",
        dataset_id=get_canonical_legal_corpus("germany_laws").hf_dataset_id,
        local_roots=(get_canonical_legal_corpus("germany_laws").parquet_dir(),),
        preferred_parquet_names=("germany_laws.parquet", "laws.parquet", "articles.parquet", "cid_index.parquet"),
        parquet_prefix="parquet",
        cid_field=get_canonical_legal_corpus("germany_laws").cid_field,
        preferred_path_substrings=("parquet/laws/", "parquet/articles/", "parquet/cid_index/"),
    ),
}


class BluebookCitationResolver:
    """Link citations to source rows in canonical legal corpora."""

    def __init__(
        self,
        *,
        allow_hf_fallback: bool = True,
        local_root_overrides: Optional[Dict[str, str]] = None,
        parquet_file_overrides: Optional[Dict[str, Sequence[str] | str]] = None,
        extractor: Optional[CitationExtractor] = None,
    ) -> None:
        self.allow_hf_fallback = allow_hf_fallback
        self.local_root_overrides = dict(local_root_overrides or {})
        self.parquet_file_overrides = dict(parquet_file_overrides or {})
        self.extractor = extractor or CitationExtractor()
        self._schema_cache: Dict[str, set[str]] = {}

    def resolve_text(self, text: str, *, state_code: Optional[str] = None) -> List[CitationLink]:
        citations = self.extractor.extract_citations(text)
        links: List[CitationLink] = []
        seen: set[tuple[str, str]] = set()
        for citation in citations:
            key = (citation.type, citation.text.lower())
            if key in seen:
                continue
            seen.add(key)
            links.append(self.resolve_citation(citation, state_code=state_code))
        return links

    def resolve_citation(self, citation: Citation, *, state_code: Optional[str] = None) -> CitationLink:
        normalized_citation = self._normalized_citation(citation)
        corpora = self._candidate_corpora(citation)
        effective_state = (state_code or citation.jurisdiction or "").strip().upper() or None
        preferred_metadata = self._preferred_resolution_metadata(corpora, effective_state)
        recovery_corpus_key = corpora[0] if corpora else None
        recovery_query = build_missing_citation_recovery_query(
            normalized_citation,
            corpus_key=recovery_corpus_key,
            state_code=effective_state,
        )

        for corpus_key in corpora:
            for source_ref in self._iter_corpus_sources(corpus_key, state_code=effective_state):
                rows = self._query_source(source_ref, corpus_key, citation, effective_state)
                if not rows:
                    continue
                best = self._rank_rows(rows, citation, effective_state)
                if best is None:
                    continue
                row, matched_field, confidence = best
                return CitationLink(
                    citation_text=citation.text,
                    citation_type=citation.type,
                    normalized_citation=normalized_citation,
                    matched=True,
                    corpus_key=corpus_key,
                    dataset_id=_CORPUS_CONFIGS[corpus_key].dataset_id,
                    matched_field=matched_field,
                    confidence=confidence,
                    source_document_id=str(_first_present(row, _IDENTIFIER_FIELDS) or ""),
                    source_title=str(_first_present(row, _TITLE_FIELDS) or ""),
                    source_url=str(_first_present(row, _URL_FIELDS) or citation.url or ""),
                    source_cid=str(_first_present(row, _CID_FIELDS) or ""),
                    source_ref=source_ref,
                    snippet=self._snippet_for_row(row),
                    metadata={
                        "state_code": effective_state,
                        "resolution_method": "canonical_corpus_match",
                        "source_row_present": True,
                        "source_ref_kind": "local_parquet"
                        if not str(source_ref).startswith(("http://", "https://"))
                        else "hf_parquet",
                        **preferred_metadata,
                        "row": row,
                    },
                )

        return CitationLink(
            citation_text=citation.text,
            citation_type=citation.type,
            normalized_citation=normalized_citation,
            matched=False,
            confidence=0.0,
            source_url=citation.url,
            metadata={
                "state_code": effective_state,
                "resolution_method": "unmatched",
                "source_row_present": False,
                "recovery_supported": bool(recovery_corpus_key),
                "recovery_corpus_key": recovery_corpus_key,
                "recovery_query": recovery_query,
                **preferred_metadata,
            },
        )

    def _preferred_resolution_metadata(self, corpora: Sequence[str], state_code: Optional[str]) -> Dict[str, Any]:
        candidate_corpora = [str(item).strip() for item in corpora if str(item).strip()]
        preferred_dataset_ids: List[str] = []
        preferred_parquet_files: List[str] = []
        for corpus_key in candidate_corpora:
            config = _CORPUS_CONFIGS.get(corpus_key)
            if not config:
                continue
            if config.dataset_id and config.dataset_id not in preferred_dataset_ids:
                preferred_dataset_ids.append(config.dataset_id)
            if corpus_key == "us_code":
                preferred_parquet_files.append("uscode.parquet")
                continue
            corpus = get_canonical_legal_corpus(corpus_key)
            for parquet_name in corpus.preferred_parquet_names(state_code):
                if parquet_name not in preferred_parquet_files:
                    preferred_parquet_files.append(parquet_name)
        return {
            "candidate_corpora": candidate_corpora,
            "preferred_corpus_key": candidate_corpora[0] if candidate_corpora else None,
            "preferred_dataset_ids": preferred_dataset_ids,
            "preferred_parquet_files": preferred_parquet_files,
        }

    def _normalized_citation(self, citation: Citation) -> str:
        if citation.type == "usc" and citation.title and citation.section:
            return f"{citation.title} U.S.C. § {citation.section}"
        if citation.type == "cfr" and citation.title and citation.section:
            return f"{citation.title} C.F.R. § {citation.section}"
        if citation.type == "federal_register" and citation.volume and citation.page:
            return f"{citation.volume} FR {citation.page}"
        if citation.type == "public_law" and citation.volume and citation.page:
            return f"Pub. L. No. {citation.volume}-{citation.page}" if "No." in citation.text else f"Pub. L. {citation.volume}-{citation.page}"
        return citation.text

    def _candidate_corpora(self, citation: Citation) -> List[str]:
        if citation.type == "case":
            return ["caselaw_access_project"]
        if citation.type == "usc":
            return ["us_code"]
        if citation.type == "cfr":
            return ["federal_register", "us_code"]
        if citation.type == "federal_register":
            return ["federal_register"]
        if citation.type == "public_law":
            return ["us_code", "federal_register", "caselaw_access_project"]
        if citation.type == "state_statute":
            code_name = _normalize_text(citation.metadata.get("code_name"))
            if "court" in code_name or "rule" in code_name:
                return ["state_court_rules", "state_admin_rules", "state_laws"]
            if "admin" in code_name:
                return ["state_admin_rules", "state_laws", "state_court_rules"]
            return ["state_laws", "state_admin_rules", "state_court_rules"]
        return []

    def _iter_corpus_sources(self, corpus_key: str, *, state_code: Optional[str]) -> List[str]:
        config = _CORPUS_CONFIGS[corpus_key]
        override_value = self.parquet_file_overrides.get(corpus_key)
        if override_value:
            override_items = [str(override_value)] if isinstance(override_value, str) else [str(item) for item in override_value]
            filtered_items = [item for item in override_items if _is_direct_citation_source(item)]
            return filtered_items
        local_sources = self._find_local_sources(config, state_code=state_code)
        if local_sources:
            return local_sources
        if not self.allow_hf_fallback or not config.dataset_id:
            return []
        return self._find_hf_sources(config, state_code=state_code)

    def _find_local_sources(self, config: CorpusSourceConfig, *, state_code: Optional[str]) -> List[str]:
        candidate_paths: List[str] = []
        roots = [Path(item) for item in config.local_roots]
        override_root = self.local_root_overrides.get(config.key)
        if override_root:
            roots = [Path(override_root).expanduser().resolve()]
        preferred_names = list(config.preferred_parquet_names)
        if state_code and config.state_field:
            preferred_names = [get_canonical_legal_corpus(config.key).state_parquet_filename(state_code), *preferred_names]
        for root in roots:
            if not root.exists():
                continue
            for name in preferred_names:
                direct = root / name
                if direct.exists():
                    candidate_paths.append(str(direct))
            for child in root.glob("*.parquet"):
                child_name = child.name.lower()
                if any(token.lower() in child_name for token in config.preferred_parquet_names):
                    candidate_paths.append(str(child))
        deduped: List[str] = []
        seen: set[str] = set()
        for path in candidate_paths:
            if path not in seen:
                seen.add(path)
                deduped.append(path)
        return deduped

    def _find_hf_sources(self, config: CorpusSourceConfig, *, state_code: Optional[str]) -> List[str]:
        try:
            from huggingface_hub import hf_hub_url, list_repo_files
        except Exception:
            hf_hub_url = None
            list_repo_files = None
        repo_ids = [repo_id for repo_id in (config.dataset_id, *list(config.dataset_id_aliases or [])) if repo_id]
        for repo_id in repo_ids:
            had_listing_error = False
            if list_repo_files is not None and hf_hub_url is not None:
                try:
                    repo_files = list_repo_files(repo_id=repo_id, repo_type="dataset")
                except Exception as exc:
                    logger.warning("Failed to list HF files for %s: %s", repo_id, exc)
                    had_listing_error = True
                else:
                    parquet_files = [path for path in repo_files if str(path).endswith(".parquet")]
                    if parquet_files:
                        ordered = self._order_hf_parquet_files(config, repo_id, parquet_files, state_code=state_code)
                        if ordered:
                            return [hf_hub_url(repo_id=repo_id, repo_type="dataset", filename=filename) for filename in ordered]

            if had_listing_error or list_repo_files is None or hf_hub_url is None:
                parquet_records = _dataset_server_parquet_records(repo_id)
                if parquet_records:
                    ordered_urls = _order_dataset_server_parquet_records(config, parquet_records, state_code=state_code)
                    if ordered_urls:
                        return ordered_urls
        return []

    def _order_hf_parquet_files(
        self,
        config: CorpusSourceConfig,
        repo_id: str,
        parquet_files: Sequence[str],
        *,
        state_code: Optional[str],
    ) -> List[str]:
        preferred_names = list(config.preferred_parquet_names)
        if state_code and config.state_field and config.key in {"state_laws", "state_admin_rules", "state_court_rules"}:
            preferred_names.insert(0, get_canonical_legal_corpus(config.key).state_parquet_filename(state_code))

        prefix = str(config.parquet_prefix or "").strip("/").lower()
        path_hints = [str(item).strip("/").lower() for item in list(config.preferred_path_substrings or []) if str(item).strip()]
        if prefix:
            path_hints.insert(0, prefix)

        def _score(candidate: str) -> tuple[int, int, str]:
            candidate_lower = str(candidate).lower()
            filename = candidate_lower.rsplit("/", 1)[-1]
            score = 0

            for index, preferred_name in enumerate(preferred_names):
                preferred_lower = str(preferred_name).lower()
                if not preferred_lower:
                    continue
                weight = max(1, 100 - index)
                if filename == preferred_lower:
                    score += 500 + weight
                elif candidate_lower.endswith(f"/{preferred_lower}") or candidate_lower.endswith(preferred_lower):
                    score += 450 + weight
                elif preferred_lower in filename:
                    score += 250 + weight
                elif preferred_lower in candidate_lower:
                    score += 150 + weight

            for hint in path_hints:
                if hint and hint in candidate_lower:
                    score += 75

            if state_code:
                state_filename = f"state-{str(state_code).strip().lower()}.parquet"
                if candidate_lower.endswith(state_filename):
                    score += 600

            score += _inventory_bonus_for_candidate(
                repo_id,
                config.key,
                candidate,
                state_code=state_code,
            )

            if "metadata" in filename:
                score -= 200
            if "embedding" in filename or "embeddings" in filename:
                score -= 250
            if filename.endswith(".faiss") or filename.endswith(".index"):
                score -= 500

            return (-score, len(candidate), candidate)

        ordered = [item for item in sorted({str(path) for path in parquet_files}, key=_score)]
        if not ordered:
            return []
        return ordered[:8]

    def _query_source(self, source_ref: str, corpus_key: str, citation: Citation, state_code: Optional[str]) -> List[Dict[str, Any]]:
        try:
            import duckdb
        except Exception:
            if source_ref.startswith(("http://", "https://")):
                return []
            return self._query_source_with_pandas(source_ref, corpus_key, citation, state_code)
        con = duckdb.connect()
        try:
            schema = self._schema_for_source(con, source_ref)
            where_clauses, params = self._build_where_clause(schema, corpus_key, citation, state_code)
            if not where_clauses:
                return []
            query = f"SELECT * FROM read_parquet('{_sql_literal_path(source_ref)}') WHERE {' AND '.join(where_clauses)} LIMIT 25"
            cursor = con.execute(query, params)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
        except Exception as exc:
            logger.debug("Citation source query failed for %s: %s", source_ref, exc)
            return []
        finally:
            con.close()

    def _query_source_with_pandas(self, source_ref: str, corpus_key: str, citation: Citation, state_code: Optional[str]) -> List[Dict[str, Any]]:
        rows = self._load_local_parquet_rows(source_ref)
        filtered: List[Dict[str, Any]] = []
        for row in rows:
            score = self._row_score(row, citation, state_code)
            if score > 0:
                filtered.append(row)
        return filtered[:25]

    def _load_local_parquet_rows(self, source_ref: str) -> List[Dict[str, Any]]:
        try:
            import pyarrow.parquet as pq
            return pq.read_table(source_ref).to_pylist()
        except Exception:
            pass
        try:
            import pandas as pd
            return pd.read_parquet(source_ref).to_dict("records")
        except Exception:
            return []

    def _schema_for_source(self, con: Any, source_ref: str) -> set[str]:
        cached = self._schema_cache.get(source_ref)
        if cached is not None:
            return cached
        try:
            cursor = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{_sql_literal_path(source_ref)}')")
            schema = {row[0] for row in cursor.fetchall()}
        except Exception:
            cursor = con.execute(
                f"SELECT * FROM read_parquet('{_sql_literal_path(source_ref)}') LIMIT 1"
            )
            schema = {description[0] for description in cursor.description}
        self._schema_cache[source_ref] = schema
        return schema

    def _build_where_clause(self, schema: set[str], corpus_key: str, citation: Citation, state_code: Optional[str]) -> tuple[List[str], List[Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if corpus_key == "us_code":
            title_field = next((field for field in _TITLE_NUMBER_FIELDS if field in schema), None)
            section_field = next((field for field in _SECTION_FIELDS if field in schema), None)
            official_field = next((field for field in _OFFICIAL_CITE_FIELDS if field in schema), None)
            congress_field = next((field for field in _CONGRESS_FIELDS if field in schema), None)
            law_field = next((field for field in _LAW_NUMBER_FIELDS if field in schema), None)
            subclauses: List[str] = []
            if title_field and section_field and citation.title and citation.section:
                subclauses.append(f"(CAST({title_field} AS VARCHAR) = ? AND CAST({section_field} AS VARCHAR) = ?)")
                params.extend([str(citation.title), str(citation.section)])
            if official_field:
                for term in _citation_match_terms(citation):
                    subclauses.append(f"lower(CAST({official_field} AS VARCHAR)) = lower(?)")
                    params.append(term)
            if citation.type == "public_law" and congress_field and law_field and citation.volume and citation.page:
                subclauses.append(f"(CAST({congress_field} AS VARCHAR) = ? AND CAST({law_field} AS VARCHAR) = ?)")
                params.extend([str(citation.volume), str(citation.page)])
            if subclauses:
                clauses.append(f"({' OR '.join(subclauses)})")
            return clauses, params
        if corpus_key == "federal_register":
            volume_field = next((field for field in _VOLUME_FIELDS if field in schema), None)
            page_field = next((field for field in _PAGE_FIELDS if field in schema), None)
            official_field = next((field for field in _OFFICIAL_CITE_FIELDS if field in schema), None)
            subclauses: List[str] = []
            if volume_field and page_field and citation.volume and citation.page:
                subclauses.append(f"(CAST({volume_field} AS VARCHAR) = ? AND CAST({page_field} AS VARCHAR) = ?)")
                params.extend([str(citation.volume), str(citation.page)])
            if official_field:
                subclauses.append(f"lower(CAST({official_field} AS VARCHAR)) = lower(?)")
                params.append(citation.text)
            if subclauses:
                clauses.append(f"({' OR '.join(subclauses)})")
            return clauses, params
        if corpus_key in {"state_laws", "state_admin_rules", "state_court_rules"}:
            state_field = next((field for field in _STATE_FIELDS if field in schema), None)
            official_field = next((field for field in _OFFICIAL_CITE_FIELDS if field in schema), None)
            section_field = next((field for field in _SECTION_FIELDS if field in schema), None)
            identifier_fields = [field for field in _IDENTIFIER_FIELDS if field in schema]
            text_fields = [field for field in _TEXT_FIELDS if field in schema]
            if state_code and state_field:
                clauses.append(f"upper(CAST({state_field} AS VARCHAR)) = ?")
                params.append(state_code)
            subclauses: List[str] = []
            if official_field:
                for term in _citation_match_terms(citation)[:8]:
                    if not term:
                        continue
                    subclauses.append(f"lower(CAST({official_field} AS VARCHAR)) = lower(?)")
                    params.append(term)
            if section_field and citation.section:
                subclauses.append(f"CAST({section_field} AS VARCHAR) = ?")
                params.append(str(citation.section))
            if citation.type == "state_statute" and citation.section:
                for field in identifier_fields + text_fields:
                    for alias in _state_section_aliases(citation.section):
                        subclauses.append(f"lower(CAST({field} AS VARCHAR)) LIKE lower(?)")
                        params.append(f"%{alias}%")
            if subclauses:
                clauses.append(f"({' OR '.join(subclauses)})")
            return clauses, params
        search_fields = [
            field for field in (_OFFICIAL_CITE_FIELDS + _IDENTIFIER_FIELDS + _TITLE_FIELDS + _REPORTER_FIELDS + _TEXT_FIELDS)
            if field in schema
        ]
        terms = _citation_match_terms(citation)
        subclauses: List[str] = []
        for field in search_fields:
            for term in terms[:8]:
                if not term:
                    continue
                subclauses.append(f"lower(CAST({field} AS VARCHAR)) = lower(?)")
                params.append(term)
                if len(term) >= 6:
                    subclauses.append(f"lower(CAST({field} AS VARCHAR)) LIKE lower(?)")
                    params.append(f"%{term}%")
        if citation.type == "case":
            volume_field = next((field for field in _VOLUME_FIELDS if field in schema), None)
            page_field = next((field for field in _PAGE_FIELDS if field in schema), None)
            if volume_field and page_field and citation.volume and citation.page:
                subclauses.append(f"(CAST({volume_field} AS VARCHAR) = ? AND CAST({page_field} AS VARCHAR) = ?)")
                params.extend([str(citation.volume), str(citation.page)])
        if citation.type == "public_law":
            congress_field = next((field for field in _CONGRESS_FIELDS if field in schema), None)
            law_field = next((field for field in _LAW_NUMBER_FIELDS if field in schema), None)
            if congress_field and law_field and citation.volume and citation.page:
                subclauses.append(f"(CAST({congress_field} AS VARCHAR) = ? AND CAST({law_field} AS VARCHAR) = ?)")
                params.extend([str(citation.volume), str(citation.page)])
        if citation.type == "cfr":
            title_field = next((field for field in _TITLE_NUMBER_FIELDS if field in schema), None)
            section_field = next((field for field in _SECTION_FIELDS if field in schema), None)
            if title_field and section_field and citation.title and citation.section:
                subclauses.append(f"(CAST({title_field} AS VARCHAR) = ? AND CAST({section_field} AS VARCHAR) = ?)")
                params.extend([str(citation.title), str(citation.section)])
        if subclauses:
            clauses.append(f"({' OR '.join(subclauses)})")
        return clauses, params

    def _rank_rows(self, rows: Sequence[Dict[str, Any]], citation: Citation, state_code: Optional[str]) -> Optional[tuple[Dict[str, Any], str, float]]:
        best_row: Optional[Dict[str, Any]] = None
        best_field = ""
        best_score = 0.0
        for row in rows:
            score, field = self._row_score(row, citation, state_code, include_field=True)
            if score > best_score:
                best_row = row
                best_field = field
                best_score = score
        if best_row is None or best_score <= 0 or not best_field:
            return None
        return best_row, best_field, best_score

    def _row_score(self, row: Dict[str, Any], citation: Citation, state_code: Optional[str], *, include_field: bool = False) -> Any:
        score = 0.0
        matched_field = ""
        official_exact = False
        normalized_terms = {_normalize_text(term) for term in _citation_match_terms(citation) if term}
        compact_terms = {_compact_alnum(term) for term in _citation_match_terms(citation) if term}
        for field in _OFFICIAL_CITE_FIELDS:
            if field in row and _normalize_text(row.get(field)) in normalized_terms:
                score += 10.0
                matched_field = field
                official_exact = True
                break
        if score <= 0:
            for field in _IDENTIFIER_FIELDS + _TITLE_FIELDS:
                if field not in row:
                    continue
                normalized_value = _normalize_text(row.get(field))
                if normalized_value and normalized_value in normalized_terms:
                    score += 8.0
                    matched_field = matched_field or field
                    break
        for field in _OFFICIAL_CITE_FIELDS + _IDENTIFIER_FIELDS + _TITLE_FIELDS:
            if field not in row:
                continue
            compact_value = _compact_alnum(row.get(field))
            if compact_value and compact_value in compact_terms:
                score += 4.0
                matched_field = matched_field or field
                break
        if citation.type == "usc":
            row_title = _first_present(row, _TITLE_NUMBER_FIELDS)
            row_section = _first_present(row, _SECTION_FIELDS)
            if str(row_title or "") == str(citation.title or "") and _normalize_section(row_section) == _normalize_section(citation.section):
                score += 8.0
                matched_field = matched_field or "title+section"
        if citation.type == "federal_register":
            row_volume = _first_present(row, _VOLUME_FIELDS)
            row_page = _first_present(row, _PAGE_FIELDS)
            if str(row_volume or "") == str(citation.volume or "") and str(row_page or "") == str(citation.page or ""):
                score += 8.0
                matched_field = matched_field or "volume+page"
        if citation.type == "cfr":
            row_title = _first_present(row, _TITLE_NUMBER_FIELDS)
            row_section = _first_present(row, _SECTION_FIELDS)
            if str(row_title or "") == str(citation.title or "") and _normalize_section(row_section) == _normalize_section(citation.section):
                score += 8.0
                matched_field = matched_field or "title+section"
        if citation.type == "public_law":
            row_congress = _first_present(row, _CONGRESS_FIELDS)
            row_law_number = _first_present(row, _LAW_NUMBER_FIELDS)
            if str(row_congress or "") == str(citation.volume or "") and str(row_law_number or "") == str(citation.page or ""):
                score += 8.0
                matched_field = matched_field or "congress+law_number"
        if citation.type == "case":
            row_volume = _first_present(row, _VOLUME_FIELDS)
            row_page = _first_present(row, _PAGE_FIELDS)
            row_reporter = _first_present(row, _REPORTER_FIELDS)
            if str(row_volume or "") == str(citation.volume or "") and str(row_page or "") == str(citation.page or ""):
                score += 6.0
                matched_field = matched_field or "volume+page"
            if row_reporter and _compact_alnum(row_reporter) == _compact_alnum(citation.reporter):
                score += 4.0
                matched_field = matched_field or "reporter"
        if citation.type == "state_statute":
            row_state = str(_first_present(row, _STATE_FIELDS) or "").upper()
            row_section = _normalize_section(_first_present(row, _SECTION_FIELDS))
            section_exact = bool(row_section and row_section == _normalize_section(citation.section))
            source_section_exact = False
            if not section_exact and citation.section:
                state_aliases = _state_section_aliases(citation.section)
                normalized_aliases = {_normalize_text(alias) for alias in state_aliases}
                compact_aliases = {_compact_alnum(alias) for alias in state_aliases}
                for field in _IDENTIFIER_FIELDS + _TEXT_FIELDS:
                    if field not in row:
                        continue
                    normalized_value = _normalize_text(row.get(field))
                    compact_value = _compact_alnum(row.get(field))
                    if (
                        normalized_value and any(alias and alias in normalized_value for alias in normalized_aliases)
                    ) or (
                        compact_value and any(alias and alias in compact_value for alias in compact_aliases)
                    ):
                        source_section_exact = True
                        score += 6.0
                        matched_field = matched_field or field
                        break
            if section_exact:
                score += 6.0
                matched_field = matched_field or "section_number"
            if official_exact or section_exact or source_section_exact:
                if state_code and row_state == state_code:
                    score += 2.0
                    matched_field = matched_field or "state_code"
                code_name = _normalize_text(citation.metadata.get("code_name"))
                row_code_name = _normalize_text(_first_present(row, _CODE_NAME_FIELDS))
                if code_name and row_code_name and (code_name in row_code_name or row_code_name in code_name):
                    score += 2.0
                    matched_field = matched_field or "code_name"
        if _first_present(row, _URL_FIELDS):
            score += 0.25
        if _first_present(row, _CID_FIELDS):
            score += 0.25
        return (score, matched_field) if include_field else score

    def _snippet_for_row(self, row: Dict[str, Any]) -> Optional[str]:
        text = _first_present(row, _TEXT_FIELDS)
        return None if text is None else str(text)[:400]


def resolve_bluebook_citations_in_text(
    text: str,
    *,
    state_code: Optional[str] = None,
    resolver: Optional[BluebookCitationResolver] = None,
) -> List[CitationLink]:
    return (resolver or BluebookCitationResolver()).resolve_text(text, state_code=state_code)


def audit_bluebook_citation_resolution_for_documents(
    documents: Sequence[Dict[str, Any]],
    *,
    state_code: Optional[str] = None,
    resolver: Optional[BluebookCitationResolver] = None,
) -> Dict[str, Any]:
    active_resolver = resolver or BluebookCitationResolver()
    document_reports: List[Dict[str, Any]] = []
    total_citations = 0
    matched_citations = 0
    unresolved_citations = 0
    for index, document in enumerate(documents, start=1):
        if not isinstance(document, dict):
            continue
        text = str(document.get("text") or "").strip()
        document_id = str(document.get("document_id") or document.get("id") or f"document_{index}")
        document_title = str(document.get("title") or document.get("label") or f"Document {index}")
        if not text:
            document_reports.append({
                "document_id": document_id,
                "document_title": document_title,
                "citation_count": 0,
                "matched_citation_count": 0,
                "unmatched_citation_count": 0,
                "all_citations_resolved": True,
                "citations": [],
            })
            continue
        links = active_resolver.resolve_text(text, state_code=state_code)
        link_payloads = [citation_link_to_dict(link) for link in links]
        matched_count = sum(1 for item in link_payloads if bool(item.get("matched")))
        unresolved_count = len(link_payloads) - matched_count
        total_citations += len(link_payloads)
        matched_citations += matched_count
        unresolved_citations += unresolved_count
        document_reports.append({
            "document_id": document_id,
            "document_title": document_title,
            "citation_count": len(link_payloads),
            "matched_citation_count": matched_count,
            "unmatched_citation_count": unresolved_count,
            "all_citations_resolved": bool(link_payloads) and unresolved_count == 0,
            "citations": link_payloads,
        })
    documents_with_citations = sum(1 for item in document_reports if int(item.get("citation_count") or 0) > 0)
    fully_resolved_documents = sum(1 for item in document_reports if bool(item.get("all_citations_resolved")))
    unresolved_documents = [{
        "document_id": item["document_id"],
        "document_title": item["document_title"],
        "unmatched_citation_count": item["unmatched_citation_count"],
        "unmatched_citations": [citation for citation in list(item.get("citations") or []) if not bool(citation.get("matched"))],
    } for item in document_reports if int(item.get("unmatched_citation_count") or 0) > 0]
    return {
        "document_count": len(document_reports),
        "documents_with_citations": documents_with_citations,
        "fully_resolved_document_count": fully_resolved_documents,
        "citation_count": total_citations,
        "matched_citation_count": matched_citations,
        "unmatched_citation_count": unresolved_citations,
        "citation_resolution_ratio": (matched_citations / total_citations) if total_citations else 1.0,
        "document_resolution_ratio": (fully_resolved_documents / documents_with_citations) if documents_with_citations else 1.0,
        "documents": document_reports,
        "unresolved_documents": unresolved_documents,
        "source": "bluebook_citation_resolution_audit",
    }


__all__ = [
    "BluebookCitationResolver",
    "CitationLink",
    "audit_bluebook_citation_resolution_for_documents",
    "citation_link_to_dict",
    "resolve_bluebook_citations_in_text",
]
