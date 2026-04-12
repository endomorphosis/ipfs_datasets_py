from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List, Optional

import pytest

from ipfs_datasets_py.processors.legal_scrapers.canonical_legal_corpora import (
    build_canonical_corpus_local_root_overrides,
)
from ipfs_datasets_py.processors.legal_scrapers import (
    BluebookCitationResolver,
    CitationExtractor,
    resolve_bluebook_citations_in_text,
)
from ipfs_datasets_py.processors.legal_scrapers.citation_extraction import BLUEBOOK_STATE_TO_CODE


"""Opt-in real-corpus Bluebook coverage against local or HF-backed Justicedao parquet sources.

Environment overrides:
- BLUEBOOK_REAL_SAMPLE_SIZE
- BLUEBOOK_REAL_STATE_CODE
- BLUEBOOK_REAL_DATA_ROOT
- BLUEBOOK_REAL_US_CODE_ROOT
- BLUEBOOK_REAL_FEDERAL_REGISTER_ROOT
- BLUEBOOK_REAL_STATE_LAWS_ROOT
- BLUEBOOK_REAL_STATE_ADMIN_RULES_ROOT
- BLUEBOOK_REAL_STATE_COURT_RULES_ROOT
"""


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
_STATE_FIELDS = ("state_code", "state", "jurisdiction", "legislation_jurisdiction")
_LOCAL_ROOT_ENV_BY_CORPUS = {
    "us_code": "BLUEBOOK_REAL_US_CODE_ROOT",
    "federal_register": "BLUEBOOK_REAL_FEDERAL_REGISTER_ROOT",
    "state_laws": "BLUEBOOK_REAL_STATE_LAWS_ROOT",
    "state_admin_rules": "BLUEBOOK_REAL_STATE_ADMIN_RULES_ROOT",
    "state_court_rules": "BLUEBOOK_REAL_STATE_COURT_RULES_ROOT",
    "caselaw_access_project": "BLUEBOOK_REAL_CASELAW_ACCESS_PROJECT_ROOT",
}
_STATE_CODE_TO_BLUEBOOK = {value: key for key, value in BLUEBOOK_STATE_TO_CODE.items()}


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


def _build_local_root_overrides() -> Dict[str, str]:
    return build_canonical_corpus_local_root_overrides(
        env=os.environ,
        env_var_by_corpus_key=_LOCAL_ROOT_ENV_BY_CORPUS,
        data_root_env_name="BLUEBOOK_REAL_DATA_ROOT",
    )


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


def _materialize_hf_dataset_source(source_ref: str) -> str:
    match = re.match(
        r"https?://huggingface\.co/datasets/(?P<repo>[^/]+/[^/]+)/resolve/(?P<revision>[^/]+)/(?P<filename>.+)",
        str(source_ref or "").strip(),
    )
    if not match:
        return str(source_ref)

    from huggingface_hub import hf_hub_download

    return str(
        hf_hub_download(
            repo_id=str(match.group("repo")),
            repo_type="dataset",
            revision=str(match.group("revision")),
            filename=str(match.group("filename")),
        )
    )


def _read_rows(connection: Any, source_ref: str, where_clause: str, limit: int) -> List[Dict[str, Any]]:
    if source_ref.startswith(("http://", "https://")):
        try:
            source_ref = _materialize_hf_dataset_source(source_ref)
        except Exception:
            pass

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

    try:
        cursor = connection.execute(query)
    except Exception:
        fallback_query = f"SELECT * FROM read_parquet('{_sql_literal_path(source_ref)}') LIMIT {int(limit)}"
        cursor = connection.execute(fallback_query)
    rows = cursor.fetchall()
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


def _first_non_empty_string(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        for item in value:
            text = str(item or "").strip()
            if text:
                return text
        return ""
    return str(value or "").strip()


def _citation_text_from_value(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value).strip()
    if isinstance(value, dict):
        # CAP and some state corpora store citation text under nested keys.
        for key in (
            "cite",
            "citation",
            "official_cite",
            "bluebook_citation",
            "identifier",
            "text",
            "value",
        ):
            nested = _citation_text_from_value(value.get(key))
            if nested:
                return nested
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            nested = _citation_text_from_value(item)
            if nested:
                return nested
        return ""
    return str(value).strip()


def _citation_text_from_row(row: Dict[str, Any], fields: Iterable[str]) -> str:
    for field in fields:
        if field not in row:
            continue
        citation_text = _citation_text_from_value(row.get(field))
        if citation_text:
            return citation_text
    return ""


def _citation_text_from_row_text(
    row: Dict[str, Any],
    citation_type: str,
    state_code: Optional[str],
) -> str:
    extractor = CitationExtractor()
    for field in ("text", "head_matter", "name", "name_abbreviation"):
        value = row.get(field)
        source_text = _first_non_empty_string(value)
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


def _synthesize_state_statute_citation_from_row(
    row: Dict[str, Any],
    state_code: str,
) -> str:
    source_id = str(row.get("source_id") or "").strip()
    text = _first_non_empty_string(row.get("text"))
    bluebook_abbrev = _STATE_CODE_TO_BLUEBOOK.get(state_code)
    if not bluebook_abbrev:
        return ""

    section_match = None
    for candidate in (source_id, text):
        section_match = re.search(r"(?:Section|Rule|Part)[\s:-]+(?P<section>[A-Za-z0-9.:-]+)", candidate, re.IGNORECASE)
        if section_match:
            break
    if not section_match:
        return ""

    section = str(section_match.group("section") or "").strip().rstrip(".,;:")
    if not section:
        return ""

    lowered_source = source_id.lower()
    if "statute" in lowered_source:
        code_name = "Stat."
    elif "court-rule" in lowered_source or "court rule" in lowered_source:
        code_name = "Court Rules"
    elif "state-admin" in lowered_source or "administrative" in lowered_source:
        code_name = "Admin. Code"
    else:
        return ""
    return f"{bluebook_abbrev} {code_name} § {section}"


def _find_source(resolver: BluebookCitationResolver, corpus_key: str, state_code: Optional[str]) -> str:
    for source_ref in resolver._iter_corpus_sources(corpus_key, state_code=state_code):
        return source_ref
    env_name = _LOCAL_ROOT_ENV_BY_CORPUS.get(corpus_key)
    if env_name:
        pytest.skip(
            f"No local or Hugging Face parquet source was available for {corpus_key}. "
            f"Set {env_name} to a parquet directory or install huggingface_hub and duckdb for remote sampling."
        )
    pytest.skip(f"No local or Hugging Face parquet source was available for {corpus_key}.")


def _build_us_code_cases(connection: Any, resolver: BluebookCitationResolver, sample_size: int) -> List[Dict[str, Any]]:
    source_ref = _find_source(resolver, "us_code", state_code=None)
    rows = _read_rows(connection, source_ref, "", sample_size * 6)

    cases = []
    for row in rows:
        title = _first_present(row, _TITLE_FIELDS)
        section = _first_present(row, _SECTION_FIELDS)
        if title in (None, "") or section in (None, ""):
            continue
        citation_text = _citation_text_from_row(row, _OFFICIAL_CITE_FIELDS)
        if not citation_text:
            citation_text = f"{title} U.S.C. § {section}"
        if not _parser_accepts(citation_text, "usc", None):
            continue
        cases.append(
            {
                "citation_text": citation_text,
                "citation_type": "usc",
                "corpus_key": "us_code",
                "state_code": None,
                "source_ref": source_ref,
            }
        )
        if len(cases) >= sample_size:
            break
    return cases


def _build_federal_register_cases(
    connection: Any,
    resolver: BluebookCitationResolver,
    sample_size: int,
) -> List[Dict[str, Any]]:
    source_ref = _find_source(resolver, "federal_register", state_code=None)
    rows = _read_rows(connection, source_ref, "", sample_size * 6)

    cases = []
    for row in rows:
        citation_text = _citation_text_from_row(row, _OFFICIAL_CITE_FIELDS)
        if citation_text in (None, "") or not _parser_accepts(str(citation_text), "federal_register", None):
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
        if len(cases) >= sample_size:
            break
    return cases


def _build_state_law_cases(
    connection: Any,
    resolver: BluebookCitationResolver,
    sample_size: int,
    state_code: str,
) -> List[Dict[str, Any]]:
    source_ref = _find_source(resolver, "state_laws", state_code=state_code)
    rows = _read_rows(connection, source_ref, "", sample_size * 8)

    cases = []
    for row in rows:
        resolved_state_code = str(_first_present(row, _STATE_FIELDS) or state_code).strip().upper() or state_code
        citation_text = _citation_text_from_row(row, _OFFICIAL_CITE_FIELDS + ("citations", "name", "source_id"))
        if citation_text in (None, "") or not _parser_accepts(citation_text, "state_statute", resolved_state_code):
            citation_text = _citation_text_from_row_text(row, "state_statute", resolved_state_code)
        if citation_text in (None, "") or not _parser_accepts(citation_text, "state_statute", resolved_state_code):
            citation_text = _synthesize_state_statute_citation_from_row(row, resolved_state_code)
        if citation_text in (None, ""):
            continue
        if not _parser_accepts(citation_text, "state_statute", resolved_state_code):
            # Some citations parse without explicit jurisdiction metadata.
            if not _parser_accepts(citation_text, "state_statute", None):
                continue
        cases.append(
            {
                "citation_text": citation_text,
                "citation_type": "state_statute",
                "corpus_key": "state_laws",
                "state_code": resolved_state_code,
                "source_ref": source_ref,
            }
        )
        if len(cases) >= sample_size:
            break
    return cases


def _build_state_corpus_cases(
    connection: Any,
    resolver: BluebookCitationResolver,
    corpus_key: str,
    sample_size: int,
    state_code: str,
) -> List[Dict[str, Any]]:
    source_ref = _find_source(resolver, corpus_key, state_code=state_code)
    rows = _read_rows(connection, source_ref, "", sample_size * 8)

    cases = []
    for row in rows:
        citation_text = _citation_text_from_row(row, _OFFICIAL_CITE_FIELDS + ("citations", "name", "source_id"))
        resolved_state_code = str(_first_present(row, _STATE_FIELDS) or state_code).strip().upper() or state_code
        if citation_text in (None, "") or not _parser_accepts(str(citation_text), "state_statute", resolved_state_code):
            citation_text = _citation_text_from_row_text(row, "state_statute", resolved_state_code)
        if citation_text in (None, ""):
            continue
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


def _sample_cases_for_corpus(
    connection: Any,
    resolver: BluebookCitationResolver,
    corpus_key: str,
    sample_size: int,
    state_code: Optional[str],
) -> Dict[str, Any]:
    builder_map = {
        "us_code": lambda: _build_us_code_cases(connection, resolver, sample_size),
        "federal_register": lambda: _build_federal_register_cases(connection, resolver, sample_size),
        "state_laws": lambda: _build_state_law_cases(connection, resolver, sample_size, str(state_code or "")),
        "state_admin_rules": lambda: _build_state_corpus_cases(
            connection,
            resolver,
            "state_admin_rules",
            sample_size,
            str(state_code or ""),
        ),
        "state_court_rules": lambda: _build_state_corpus_cases(
            connection,
            resolver,
            "state_court_rules",
            sample_size,
            str(state_code or ""),
        ),
        "caselaw_access_project": lambda: _build_caselaw_cases(connection, resolver, sample_size),
    }
    if corpus_key not in builder_map:
        raise ValueError(f"Unsupported corpus key for real-corpora sampling: {corpus_key}")

    source_ref: Optional[str] = None
    try:
        source_ref = _find_source(resolver, corpus_key, state_code=state_code)
        rows = _read_rows(connection, source_ref, "", sample_size * 8)
        cases = builder_map[corpus_key]()
    except BaseException as exc:
        message = str(exc).strip() or exc.__class__.__name__
        return {
            "corpus_key": corpus_key,
            "state_code": state_code,
            "source_ref": source_ref,
            "sampled_rows": None,
            "sampled_cases": 0,
            "status": "error",
            "reason": message,
            "cases": [],
        }

    status = "ok" if cases else "empty"
    reason = None
    if not cases:
        if not rows:
            reason = "source was available but yielded no sample rows"
        else:
            reason = (
                f"source yielded {len(rows)} rows but none produced parseable "
                f"{corpus_key} citation samples"
            )
    return {
        "corpus_key": corpus_key,
        "state_code": state_code,
        "source_ref": source_ref,
        "sampled_rows": len(rows),
        "sampled_cases": len(cases),
        "status": status,
        "reason": reason,
        "cases": cases,
    }


def _collect_real_corpus_cases(
    connection: Any,
    resolver: BluebookCitationResolver,
    sample_size: int,
    state_code: str,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    diagnostics: List[Dict[str, Any]] = []
    all_cases: List[Dict[str, Any]] = []
    for corpus_key in (
        "us_code",
        "federal_register",
        "state_laws",
        "state_admin_rules",
        "state_court_rules",
        "caselaw_access_project",
    ):
        diagnostic = _sample_cases_for_corpus(
            connection,
            resolver,
            corpus_key,
            sample_size,
            state_code if corpus_key.startswith("state_") else None,
        )
        diagnostics.append(diagnostic)
        all_cases.extend(list(diagnostic.get("cases") or []))
    return all_cases, diagnostics


def _format_sampling_diagnostics(diagnostics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "corpus_key": item.get("corpus_key"),
            "status": item.get("status"),
            "sampled_rows": item.get("sampled_rows"),
            "sampled_cases": item.get("sampled_cases"),
            "state_code": item.get("state_code"),
            "reason": item.get("reason"),
            "source_ref": item.get("source_ref"),
        }
        for item in diagnostics
    ]


def _build_caselaw_cases(
    connection: Any,
    resolver: BluebookCitationResolver,
    sample_size: int,
) -> List[Dict[str, Any]]:
    source_ref = _find_source(resolver, "caselaw_access_project", state_code=None)
    rows = _read_rows(connection, source_ref, "", sample_size * 8)

    cases: List[Dict[str, Any]] = []
    for row in rows:
        citation_text = _citation_text_from_row(
            row,
            _OFFICIAL_CITE_FIELDS + ("citations", "citation", "name_abbreviation", "name"),
        )
        if citation_text in (None, "") or not _parser_accepts(citation_text, "case", None):
            citation_text = _citation_text_from_row_text(row, "case", None)
        if citation_text in (None, ""):
            continue
        if not _parser_accepts(citation_text, "case", None):
            continue
        cases.append(
            {
                "citation_text": citation_text,
                "citation_type": "case",
                "corpus_key": "caselaw_access_project",
                "state_code": None,
                "source_ref": source_ref,
            }
        )
        if len(cases) >= sample_size:
            break
    return cases


def _run_resolution_cases(
    cases: List[Dict[str, Any]],
    resolver: BluebookCitationResolver,
) -> tuple[int, List[Dict[str, Any]]]:
    matched_count = 0
    failures: List[Dict[str, Any]] = []
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
    return matched_count, failures


def _wrap_citation_text(citation_text: str) -> str:
    return f"The filing relies on {citation_text} as authority."


def test_bluebook_citation_resolver_real_justicedao_sampling(pytestconfig: pytest.Config):
    _require_opt_in(pytestconfig)

    resolver = BluebookCitationResolver(
        allow_hf_fallback=True,
        local_root_overrides=_build_local_root_overrides(),
    )
    sample_size = int(os.environ.get("BLUEBOOK_REAL_SAMPLE_SIZE", "6"))
    state_code = os.environ.get(_STATE_CODE_ENV, "MN").strip().upper() or "MN"

    connection = _connect_duckdb()
    try:
        cases, diagnostics = _collect_real_corpus_cases(connection, resolver, sample_size, state_code)
    except Exception as exc:
        pytest.skip(f"Unable to sample real Justicedao parquet sources: {exc}")
    finally:
        if connection is not None:
            connection.close()

    if not cases:
        pytest.skip(
            f"No real Justicedao citation samples were available. Diagnostics: {_format_sampling_diagnostics(diagnostics)}"
        )

    matched_count, failures = _run_resolution_cases(cases, resolver)

    coverage = matched_count / len(cases)
    assert len(cases) >= 6, {
        "cases": cases,
        "sampling_diagnostics": _format_sampling_diagnostics(diagnostics),
    }
    assert coverage >= 0.8, {
        "failures": failures,
        "sampling_diagnostics": _format_sampling_diagnostics(diagnostics),
    }


def test_bluebook_citation_resolver_real_justicedao_per_type_coverage_contract(pytestconfig: pytest.Config):
    _require_opt_in(pytestconfig)

    resolver = BluebookCitationResolver(
        allow_hf_fallback=True,
        local_root_overrides=_build_local_root_overrides(),
    )
    sample_size = int(os.environ.get("BLUEBOOK_REAL_SAMPLE_SIZE", "6"))
    state_code = os.environ.get(_STATE_CODE_ENV, "MN").strip().upper() or "MN"
    min_samples_per_type = int(os.environ.get("BLUEBOOK_REAL_MIN_SAMPLES_PER_TYPE", "3"))
    min_coverage_per_type = float(os.environ.get("BLUEBOOK_REAL_MIN_TYPE_COVERAGE", "0.70"))

    connection = _connect_duckdb()
    try:
        all_cases, diagnostics = _collect_real_corpus_cases(connection, resolver, sample_size, state_code)
    except Exception as exc:
        pytest.skip(f"Unable to sample real Justicedao parquet sources: {exc}")
    finally:
        if connection is not None:
            connection.close()

    if not all_cases:
        pytest.skip(
            f"No real Justicedao citation samples were available. Diagnostics: {_format_sampling_diagnostics(diagnostics)}"
        )

    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for case in all_cases:
        by_type.setdefault(str(case["citation_type"]), []).append(case)

    evaluated_types = 0
    failures: Dict[str, Any] = {}

    for citation_type, cases in sorted(by_type.items()):
        if len(cases) < min_samples_per_type:
            continue
        evaluated_types += 1
        matched_count, type_failures = _run_resolution_cases(cases, resolver)
        coverage = matched_count / len(cases)
        if coverage < min_coverage_per_type:
            failures[citation_type] = {
                "coverage": coverage,
                "required": min_coverage_per_type,
                "sample_count": len(cases),
                "failures": type_failures,
            }

    if evaluated_types == 0:
        pytest.skip(
            "No citation family met the minimum sample threshold; "
            "lower BLUEBOOK_REAL_MIN_SAMPLES_PER_TYPE or increase BLUEBOOK_REAL_SAMPLE_SIZE. "
            f"Diagnostics: {_format_sampling_diagnostics(diagnostics)}"
        )

    assert not failures, {
        "failures": failures,
        "sampling_diagnostics": _format_sampling_diagnostics(diagnostics),
    }