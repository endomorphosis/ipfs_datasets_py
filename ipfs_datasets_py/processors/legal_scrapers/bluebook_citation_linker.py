"""Resolve Bluebook-style citations against canonical legal corpora.

This module links citations found in documents to the underlying official source
records in local-first legal corpora, with optional HuggingFace fallback for the
canonical datasets already used elsewhere in the repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .canonical_legal_corpora import get_canonical_legal_corpus
from .citation_extraction import Citation, CitationExtractor
from .legal_source_recovery import build_missing_citation_recovery_query

logger = logging.getLogger(__name__)


_IDENTIFIER_FIELDS = [
    "statute_id",
    "identifier",
    "id",
    "document_number",
    "citation",
    "name",
]
_TITLE_FIELDS = [
    "section_name",
    "short_title",
    "heading",
    "title",
    "name",
    "title_name",
    "code_name",
]
_URL_FIELDS = [
    "source_url",
    "url",
    "html_url",
    "pdf_url",
    "fr_page_url",
    "fr_json_url",
]
_TEXT_FIELDS = [
    "full_text",
    "text",
    "section_text",
    "content",
    "body",
    "semantic_text",
    "summary",
]
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


def _citation_match_terms(citation: Citation) -> List[str]:
    terms: List[str] = []

    def _add(value: Any) -> None:
        text = str(value or "").strip()
        if not text:
            return
        if text not in terms:
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
        _add(f"P.L. {citation.volume}-{citation.page}")
        _add(f"Public Law {citation.volume}-{citation.page}")
    elif citation.type == "case" and citation.volume and citation.reporter and citation.page:
        _add(f"{citation.volume} {citation.reporter} {citation.page}")
        _add(f"{citation.volume} {citation.reporter.replace('.', '').strip()} {citation.page}")
    return terms


def _first_present(row: Dict[str, Any], fields: Iterable[str]) -> Optional[Any]:
    for field in fields:
        if field in row and row.get(field) not in (None, ""):
            return row.get(field)
    return None


def _sql_literal_path(value: str) -> str:
    return str(value).replace("'", "''")


def _build_uscode_source_config() -> CorpusSourceConfig:
    us_code_corpus = get_canonical_legal_corpus("us_code")
    roots = [
        us_code_corpus.parquet_dir(),
        (Path.home() / ".ipfs_datasets" / "us_code").resolve(),
    ]
    return CorpusSourceConfig(
        key="us_code",
        dataset_id=us_code_corpus.hf_dataset_id,
        local_roots=roots,
        preferred_parquet_names=("uscode", "sections", "title"),
        parquet_prefix=us_code_corpus.parquet_dir_name,
        cid_field=us_code_corpus.cid_field,
    )


_CORPUS_CONFIGS: Dict[str, CorpusSourceConfig] = {
    "caselaw_access_project": CorpusSourceConfig(
        key="caselaw_access_project",
        dataset_id=get_canonical_legal_corpus("caselaw_access_project").hf_dataset_id,
        local_roots=(get_canonical_legal_corpus("caselaw_access_project").parquet_dir(),),
        preferred_parquet_names=(
            get_canonical_legal_corpus("caselaw_access_project").combined_parquet_filename,
            "caselaw",
            "cap",
        ),
        parquet_prefix=get_canonical_legal_corpus("caselaw_access_project").parquet_dir_name,
        cid_field=get_canonical_legal_corpus("caselaw_access_project").cid_field,
    ),
    "us_code": _build_uscode_source_config(),
    "federal_register": CorpusSourceConfig(
        key="federal_register",
        dataset_id=get_canonical_legal_corpus("federal_register").hf_dataset_id,
        local_roots=(get_canonical_legal_corpus("federal_register").parquet_dir(),),
        preferred_parquet_names=("laws.parquet", "federal_register"),
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
    ),
    "state_admin_rules": CorpusSourceConfig(
        key="state_admin_rules",
        dataset_id=get_canonical_legal_corpus("state_admin_rules").hf_dataset_id,
        local_roots=(get_canonical_legal_corpus("state_admin_rules").parquet_dir(),),
        preferred_parquet_names=("state_admin_rules_all_states.parquet",),
        parquet_prefix=get_canonical_legal_corpus("state_admin_rules").parquet_dir_name,
        state_field=get_canonical_legal_corpus("state_admin_rules").state_field,
        cid_field=get_canonical_legal_corpus("state_admin_rules").cid_field,
    ),
    "state_court_rules": CorpusSourceConfig(
        key="state_court_rules",
        dataset_id=get_canonical_legal_corpus("state_court_rules").hf_dataset_id,
        local_roots=(get_canonical_legal_corpus("state_court_rules").parquet_dir(),),
        preferred_parquet_names=("state_court_rules_all_states.parquet",),
        parquet_prefix=get_canonical_legal_corpus("state_court_rules").parquet_dir_name,
        state_field=get_canonical_legal_corpus("state_court_rules").state_field,
        cid_field=get_canonical_legal_corpus("state_court_rules").cid_field,
    ),
}


class BluebookCitationResolver:
    """Link citations to source rows in the canonical legal corpora."""

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
        seen: set[tuple[str, str]] = set()
        links: List[CitationLink] = []
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
                "recovery_supported": bool(recovery_corpus_key),
                "recovery_corpus_key": recovery_corpus_key,
                "recovery_query": recovery_query,
                **preferred_metadata,
            },
        )

    def _preferred_resolution_metadata(
        self,
        corpora: Sequence[str],
        state_code: Optional[str],
    ) -> Dict[str, Any]:
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
            if "rule" in code_name:
                return ["state_court_rules", "state_admin_rules", "state_laws"]
            if "admin" in code_name:
                return ["state_admin_rules", "state_laws", "state_court_rules"]
            return ["state_laws", "state_admin_rules", "state_court_rules"]
        return []

    def _iter_corpus_sources(self, corpus_key: str, *, state_code: Optional[str]) -> List[str]:
        config = _CORPUS_CONFIGS[corpus_key]

        override_value = self.parquet_file_overrides.get(corpus_key)
        if override_value:
            if isinstance(override_value, str):
                return [override_value]
            return [str(item) for item in override_value]

        local_sources = self._find_local_sources(config, state_code=state_code)
        if local_sources:
            return local_sources

        if not self.allow_hf_fallback or not config.dataset_id:
            return []

        return self._find_hf_sources(config, state_code=state_code)

    def _find_local_sources(self, config: CorpusSourceConfig, *, state_code: Optional[str]) -> List[str]:
        candidate_paths: List[str] = []
        roots = list(config.local_roots)
        override_root = self.local_root_overrides.get(config.key)
        if override_root:
            roots = [Path(override_root).expanduser().resolve()]

        preferred_names = list(config.preferred_parquet_names)
        if state_code and config.state_field:
            corpus = get_canonical_legal_corpus(config.key)
            preferred_names = [corpus.state_parquet_filename(state_code), *preferred_names]

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
            return []

        assert config.dataset_id is not None
        try:
            repo_files = list_repo_files(repo_id=config.dataset_id, repo_type="dataset")
        except Exception as exc:
            logger.warning("Failed to list HF files for %s: %s", config.dataset_id, exc)
            return []

        parquet_files = [path for path in repo_files if path.endswith(".parquet")]
        if config.parquet_prefix:
            prefix = config.parquet_prefix.strip("/")
            parquet_files = [
                path for path in parquet_files if path == prefix or path.startswith(f"{prefix}/")
            ]

        preferred_names = list(config.preferred_parquet_names)
        if state_code and config.state_field and config.key in {"state_laws", "state_admin_rules", "state_court_rules"}:
            preferred_names.insert(0, get_canonical_legal_corpus(config.key).state_parquet_filename(state_code))

        ordered: List[str] = []
        for preferred_name in preferred_names:
            for candidate in parquet_files:
                if candidate.endswith(preferred_name):
                    ordered.append(candidate)
        if not ordered and parquet_files:
            ordered.append(sorted(parquet_files)[0])

        return [
            hf_hub_url(repo_id=config.dataset_id, repo_type="dataset", filename=filename)
            for filename in ordered
        ]

    def _query_source(
        self,
        source_ref: str,
        corpus_key: str,
        citation: Citation,
        state_code: Optional[str],
    ) -> List[Dict[str, Any]]:
        try:
            import duckdb
        except Exception:
            if source_ref.startswith("http://") or source_ref.startswith("https://"):
                return []
            return self._query_source_with_pandas(source_ref, corpus_key, citation, state_code)

        con = duckdb.connect()
        try:
            schema = self._schema_for_source(con, source_ref)
            where_clauses, params = self._build_where_clause(schema, corpus_key, citation, state_code)
            if not where_clauses:
                return []
            query = (
                f"SELECT * FROM read_parquet('{_sql_literal_path(source_ref)}') "
                f"WHERE {' AND '.join(where_clauses)} LIMIT 25"
            )
            cursor = con.execute(query, params)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
        except Exception as exc:
            logger.debug("Citation source query failed for %s: %s", source_ref, exc)
            return []
        finally:
            con.close()

    def _query_source_with_pandas(
        self,
        source_ref: str,
        corpus_key: str,
        citation: Citation,
        state_code: Optional[str],
    ) -> List[Dict[str, Any]]:
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
        cursor = con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{_sql_literal_path(source_ref)}')"
        )
        schema = {row[0] for row in cursor.fetchall()}
        self._schema_cache[source_ref] = schema
        return schema

    def _build_where_clause(
        self,
        schema: set[str],
        corpus_key: str,
        citation: Citation,
        state_code: Optional[str],
    ) -> tuple[List[str], List[Any]]:
        clauses: List[str] = []
        params: List[Any] = []

        if corpus_key == "us_code":
            title_field = next((field for field in _TITLE_NUMBER_FIELDS if field in schema), None)
            section_field = next((field for field in _SECTION_FIELDS if field in schema), None)
            official_field = next((field for field in _OFFICIAL_CITE_FIELDS if field in schema), None)
            subclauses: List[str] = []
            if title_field and section_field and citation.title and citation.section:
                subclauses.append(f"(CAST({title_field} AS VARCHAR) = ? AND CAST({section_field} AS VARCHAR) = ?)")
                params.extend([str(citation.title), str(citation.section)])
            if official_field:
                subclauses.append(f"lower(CAST({official_field} AS VARCHAR)) = lower(?)")
                params.append(citation.text)
            if subclauses:
                clauses.append(f"({' OR '.join(subclauses)})")
            return clauses, params

        if corpus_key == "federal_register":
            volume_field = next((field for field in _VOLUME_FIELDS if field in schema), None)
            page_field = next((field for field in _PAGE_FIELDS if field in schema), None)
            official_field = next((field for field in _OFFICIAL_CITE_FIELDS if field in schema), None)
            subclauses = []
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
            code_name_field = next((field for field in _CODE_NAME_FIELDS if field in schema), None)

            if state_code and state_field:
                clauses.append(f"upper(CAST({state_field} AS VARCHAR)) = ?")
                params.append(state_code)

            subclauses = []
            if official_field:
                subclauses.append(f"lower(CAST({official_field} AS VARCHAR)) = lower(?)")
                params.append(citation.text)
            if section_field and citation.section:
                subclauses.append(f"CAST({section_field} AS VARCHAR) = ?")
                params.append(str(citation.section))
            if code_name_field and citation.metadata.get("code_name"):
                subclauses.append(f"lower(CAST({code_name_field} AS VARCHAR)) LIKE lower(?)")
                params.append(f"%{citation.metadata['code_name']}%")
            if subclauses:
                clauses.append(f"({' OR '.join(subclauses)})")
            return clauses, params

        if corpus_key in {"caselaw_access_project", "us_code", "federal_register"}:
            search_fields = [
                field
                for field in (
                    _OFFICIAL_CITE_FIELDS
                    + _IDENTIFIER_FIELDS
                    + _TITLE_FIELDS
                    + _REPORTER_FIELDS
                    + _TEXT_FIELDS
                )
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

        return clauses, params

    def _rank_rows(
        self,
        rows: Sequence[Dict[str, Any]],
        citation: Citation,
        state_code: Optional[str],
    ) -> Optional[tuple[Dict[str, Any], str, float]]:
        best_row: Optional[Dict[str, Any]] = None
        best_field = ""
        best_score = 0.0

        for row in rows:
            score, field = self._row_score(row, citation, state_code, include_field=True)
            if score > best_score:
                best_row = row
                best_field = field
                best_score = score

        if best_row is None or best_score <= 0:
            return None
        return best_row, best_field, best_score

    def _row_score(
        self,
        row: Dict[str, Any],
        citation: Citation,
        state_code: Optional[str],
        *,
        include_field: bool = False,
    ) -> Any:
        score = 0.0
        matched_field = ""
        normalized_terms = {_normalize_text(term) for term in _citation_match_terms(citation) if term}
        compact_terms = {_compact_alnum(term) for term in _citation_match_terms(citation) if term}

        for field in _OFFICIAL_CITE_FIELDS:
            if field in row and _normalize_text(row.get(field)) in normalized_terms:
                score += 10.0
                matched_field = field
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
            if state_code and row_state == state_code:
                score += 2.0
                matched_field = matched_field or "state_code"

            row_section = _normalize_section(_first_present(row, _SECTION_FIELDS))
            if row_section and row_section == _normalize_section(citation.section):
                score += 6.0
                matched_field = matched_field or "section_number"

            code_name = _normalize_text(citation.metadata.get("code_name"))
            row_code_name = _normalize_text(_first_present(row, _CODE_NAME_FIELDS))
            if code_name and row_code_name and (code_name in row_code_name or row_code_name in code_name):
                score += 2.0
                matched_field = matched_field or "code_name"

        if _first_present(row, _URL_FIELDS):
            score += 0.25
        if _first_present(row, _CID_FIELDS):
            score += 0.25

        if include_field:
            return score, matched_field
        return score

    def _snippet_for_row(self, row: Dict[str, Any]) -> Optional[str]:
        text = _first_present(row, _TEXT_FIELDS)
        if text is None:
            return None
        return str(text)[:400]


def resolve_bluebook_citations_in_text(
    text: str,
    *,
    state_code: Optional[str] = None,
    resolver: Optional[BluebookCitationResolver] = None,
) -> List[CitationLink]:
    """Extract citations from *text* and resolve them against the legal corpora."""
    return (resolver or BluebookCitationResolver()).resolve_text(text, state_code=state_code)


__all__ = [
    "BluebookCitationResolver",
    "CitationLink",
    "resolve_bluebook_citations_in_text",
]
