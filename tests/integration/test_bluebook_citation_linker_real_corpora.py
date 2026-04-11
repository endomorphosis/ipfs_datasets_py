from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Optional

import pytest

from ipfs_datasets_py.processors.legal_scrapers import (
    BluebookCitationResolver,
    CitationExtractor,
    resolve_bluebook_citations_in_text,
)


pytestmark = [
    pytest.mark.integration,
    pytest.mark.network,
    pytest.mark.heavy,
]


_STATE_CODE_ENV = "BLUEBOOK_REAL_STATE_CODE"
_TITLE_FIELDS = ("title", "title_number", "title_no", "usc_title", "title_num")
_SECTION_FIELDS = ("section", "section_number", "section_id", "section_num")
_VOLUME_FIELDS = ("volume", "volume_number", "fr_volume")
_PAGE_FIELDS = ("page", "page_number", "start_page", "page_start", "fr_page")
_OFFICIAL_CITE_FIELDS = ("official_cite", "citation", "bluebook_citation", "identifier")
_STATE_FIELDS = ("state_code", "state")


def _parser_accepts(citation_text: str, citation_type: str, state_code: Optional[str]) -> bool:
    extractor = CitationExtractor()
    for citation in extractor.extract_citations(citation_text):
        if citation.type != citation_type:
            continue
        if state_code and str(citation.jurisdiction or "") != state_code:
            continue
        return True
    return False


def _truthy_env(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def _require_opt_in(pytestconfig: pytest.Config) -> None:
    run_network = bool(pytestconfig.getoption("--run-network")) or _truthy_env("RUN_NETWORK_TESTS")
    run_heavy = bool(pytestconfig.getoption("--run-heavy")) or _truthy_env("RUN_HEAVY_TESTS")
    if run_network and run_heavy:
        return
    pytest.skip(
        "Real Justicedao fuzzing is opt-in; use --run-network --run-heavy or set RUN_NETWORK_TESTS=1 and RUN_HEAVY_TESTS=1."
    )


def _sql_literal_path(value: str) -> str:
    return str(value).replace("'", "''")


def _first_present(mapping: Dict[str, Any], fields: Iterable[str]) -> Optional[Any]:
    for field in fields:
        if field in mapping and mapping.get(field) not in (None, ""):
            return mapping[field]
    return None


def _connect_duckdb():
    try:
        import duckdb
    except Exception:
        return None

    connection = duckdb.connect()
    for statement in ("INSTALL httpfs", "LOAD httpfs"):
        try:
            connection.execute(statement)
        except Exception:
            continue
    return connection


def _read_rows(connection: Any, source_ref: str, where_clause: str, limit: int) -> List[Dict[str, Any]]:
    if not source_ref.startswith(("http://", "https://")):
        table = pytest.importorskip("pyarrow.parquet").read_table(source_ref)
        rows = table.to_pylist()
        return rows[: int(limit)]

    if connection is None:
        pytest.skip("duckdb is required to sample remote parquet sources over HTTP(S).")

    query = f"SELECT * FROM read_parquet('{_sql_literal_path(source_ref)}')"
    if where_clause:
        query += f" WHERE {where_clause}"
    query += f" LIMIT {int(limit)}"

    cursor = connection.execute(query)
    rows = cursor.fetchall()
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


def _find_source(resolver: BluebookCitationResolver, corpus_key: str, state_code: Optional[str]) -> str:
    for source_ref in resolver._iter_corpus_sources(corpus_key, state_code=state_code):
        return source_ref
    pytest.skip(f"No local or Hugging Face parquet source was available for {corpus_key}.")


def _build_us_code_cases(connection: Any, resolver: BluebookCitationResolver, sample_size: int) -> List[Dict[str, Any]]:
    source_ref = _find_source(resolver, "us_code", state_code=None)
    rows = _read_rows(
        connection,
        source_ref,
        "title IS NOT NULL AND section IS NOT NULL",
        sample_size,
    )

    cases = []
    for row in rows:
        title = _first_present(row, _TITLE_FIELDS)
        section = _first_present(row, _SECTION_FIELDS)
        if title in (None, "") or section in (None, ""):
            continue
        citation_text = f"{title} U.S.C. § {section}"
        cases.append(
            {
                "citation_text": citation_text,
                "citation_type": "usc",
                "corpus_key": "us_code",
                "state_code": None,
                "source_ref": source_ref,
            }
        )
    return cases


def _build_federal_register_cases(
    connection: Any,
    resolver: BluebookCitationResolver,
    sample_size: int,
) -> List[Dict[str, Any]]:
    source_ref = _find_source(resolver, "federal_register", state_code=None)
    rows = _read_rows(
        connection,
        source_ref,
        "volume IS NOT NULL AND page IS NOT NULL",
        sample_size,
    )

    cases = []
    for row in rows:
        citation_text = _first_present(row, _OFFICIAL_CITE_FIELDS)
        if citation_text in (None, ""):
            volume = _first_present(row, _VOLUME_FIELDS)
            page = _first_present(row, _PAGE_FIELDS)
            if volume in (None, "") or page in (None, ""):
                continue
            citation_text = f"{volume} FR {page}"
        cases.append(
            {
                "citation_text": str(citation_text),
                "citation_type": "federal_register",
                "corpus_key": "federal_register",
                "state_code": None,
                "source_ref": source_ref,
            }
        )
    return cases


def _build_state_law_cases(
    connection: Any,
    resolver: BluebookCitationResolver,
    sample_size: int,
    state_code: str,
) -> List[Dict[str, Any]]:
    source_ref = _find_source(resolver, "state_laws", state_code=state_code)
    rows = _read_rows(
        connection,
        source_ref,
        "official_cite IS NOT NULL",
        sample_size,
    )

    cases = []
    for row in rows:
        citation_text = _first_present(row, _OFFICIAL_CITE_FIELDS)
        if citation_text in (None, ""):
            continue
        resolved_state_code = str(_first_present(row, _STATE_FIELDS) or state_code).strip().upper() or state_code
        cases.append(
            {
                "citation_text": str(citation_text),
                "citation_type": "state_statute",
                "corpus_key": "state_laws",
                "state_code": resolved_state_code,
                "source_ref": source_ref,
            }
        )
    return cases


def _build_state_corpus_cases(
    connection: Any,
    resolver: BluebookCitationResolver,
    corpus_key: str,
    sample_size: int,
    state_code: str,
) -> List[Dict[str, Any]]:
    source_ref = _find_source(resolver, corpus_key, state_code=state_code)
    rows = _read_rows(
        connection,
        source_ref,
        "official_cite IS NOT NULL",
        sample_size * 4,
    )

    cases = []
    for row in rows:
        citation_text = _first_present(row, _OFFICIAL_CITE_FIELDS)
        if citation_text in (None, ""):
            continue
        resolved_state_code = str(_first_present(row, _STATE_FIELDS) or state_code).strip().upper() or state_code
        if not _parser_accepts(str(citation_text), "state_statute", resolved_state_code):
            continue
        cases.append(
            {
                "citation_text": str(citation_text),
                "citation_type": "state_statute",
                "corpus_key": corpus_key,
                "state_code": resolved_state_code,
                "source_ref": source_ref,
            }
        )
        if len(cases) >= sample_size:
            break
    return cases


def _wrap_citation_text(citation_text: str) -> str:
    return f"The filing relies on {citation_text} as authority."


def test_bluebook_citation_resolver_real_justicedao_sampling(pytestconfig: pytest.Config):
    _require_opt_in(pytestconfig)

    resolver = BluebookCitationResolver(allow_hf_fallback=True)
    sample_size = int(os.environ.get("BLUEBOOK_REAL_SAMPLE_SIZE", "6"))
    state_code = os.environ.get(_STATE_CODE_ENV, "MN").strip().upper() or "MN"

    connection = _connect_duckdb()
    try:
        cases = []
        cases.extend(_build_us_code_cases(connection, resolver, sample_size))
        cases.extend(_build_federal_register_cases(connection, resolver, sample_size))
        cases.extend(_build_state_law_cases(connection, resolver, sample_size, state_code))
        cases.extend(_build_state_corpus_cases(connection, resolver, "state_admin_rules", sample_size, state_code))
        cases.extend(_build_state_corpus_cases(connection, resolver, "state_court_rules", sample_size, state_code))
    except Exception as exc:
        pytest.skip(f"Unable to sample real Justicedao parquet sources: {exc}")
    finally:
        if connection is not None:
            connection.close()

    if not cases:
        pytest.skip("No real Justicedao citation samples were available.")

    matched_count = 0
    failures = []

    for case in cases:
        links = resolve_bluebook_citations_in_text(
            _wrap_citation_text(case["citation_text"]),
            resolver=resolver,
            state_code=case["state_code"],
        )
        success = any(
            link.matched is True
            and link.citation_type == case["citation_type"]
            and link.corpus_key == case["corpus_key"]
            and (
                case["state_code"] is None
                or str(link.metadata.get("state_code") or "") == case["state_code"]
            )
            for link in links
        )
        if success:
            matched_count += 1
            continue
        if len(failures) < 12:
            failures.append(
                {
                    "citation_text": case["citation_text"],
                    "expected_corpus": case["corpus_key"],
                    "expected_type": case["citation_type"],
                    "state_code": case["state_code"],
                    "source_ref": case["source_ref"],
                    "links": [
                        {
                            "citation_text": link.citation_text,
                            "citation_type": link.citation_type,
                            "matched": link.matched,
                            "corpus_key": link.corpus_key,
                            "state_code": link.metadata.get("state_code"),
                        }
                        for link in links
                    ],
                }
            )

    coverage = matched_count / len(cases)
    assert len(cases) >= 6, cases
    assert coverage >= 0.8, failures