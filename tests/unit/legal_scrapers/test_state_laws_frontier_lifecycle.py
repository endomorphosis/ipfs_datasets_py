from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    closed_jurisdiction_receipt,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
    OfficialFetch,
    compute_frontier_digest,
)
from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    CANONICAL_OUTPUT_PROJECTION_SCHEMA,
    StateLawMultiFetchAcquisitionError,
    StateLawMultiFetchAcquisitionLedger,
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers import state_laws_scraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
)

_GOOD_URL = "https://docs.legis.wisconsin.gov/document/statutes/1.01"
_SHORT_URL = "https://docs.legis.wisconsin.gov/document/statutes/1.02"


class _LifecycleScraper(BaseStateScraper):
    producer_calls = 0

    def get_base_url(self) -> str:
        return "https://docs.legis.wisconsin.gov/statutes/statutes/1"

    def get_code_list(self):
        return [{"name": "Wisconsin Statutes", "url": self.get_base_url()}]

    async def scrape_code(self, code_name: str, code_url: str):
        ledger = self._state_law_acquisition_ledger
        rows = [
            (_GOOD_URL, "WI-1.01", "A person shall comply. " * 20),
            (_SHORT_URL, "WI-1.02", "Short law."),
        ]
        for url, _key, text in rows:
            body = text.encode("utf-8")
            ledger.retain_parser_input(
                official_url=url,
                body=body,
                transport_receipt={
                    "content_sha256": hashlib.sha256(body).hexdigest(),
                    "official_url": url,
                    "source_transport": "direct",
                },
                retrieved_at="2026-08-24T08:00:00Z",
            )
        self._first_completion_observation = closed_jurisdiction_receipt(
            "WI",
            discovered=2,
            fetched=1,
            excluded=1,
            quarantined=0,
            failed_final=0,
            duplicates=0,
            source_domain="docs.legis.wisconsin.gov",
            canonical_keys=["WI-1.01"],
            derived_keys=["WI-1.01"],
            row_count=1,
        )
        return [
            NormalizedStatute(
                state_code="WI",
                state_name="Wisconsin",
                statute_id=key,
                code_name=code_name,
                section_number=key.removeprefix("WI-"),
                full_text=text,
                source_url=url,
            )
            for url, key, text in rows
        ]

    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Path:
        type(self).producer_calls += 1
        completion = dict(self._first_completion_observation)
        keys = list(canonical_output_projection["canonical_keys"])
        completion["canonical_row_count"] = len(keys)
        completion["row_count"] = len(keys)
        completion["disposition"] = {
            "discovered": 2,
            "duplicates": 0,
            "excluded": 1,
            "failed_final": 0,
            "fetched": len(keys),
            "quarantined": 0,
        }
        completion["index_keys"] = {
            "canonical_keys": keys,
            "derived_keys": keys,
            "parity_ok": True,
            "stale_keys": [],
        }
        # This test double represents a separately executed second traversal;
        # production code never derives this value centrally.
        independently_replayed = {
            key: value for key, value in completion["frontier"].items()
        }
        return self.retain_state_law_frontier_closure_projection(
            completion,
            replayed_frontier=independently_replayed,
            canonical_output_projection=canonical_output_projection,
            release_point=hashlib.sha256(b"wi-frontier-lifecycle").hexdigest(),
            official_source_url=self.get_base_url(),
            acquisition_path_ids=["wi-docs-statutes"],
            observation_time="2026-08-24T08:01:00Z",
            source_software_version="state-scraper/lifecycle-test",
        )


class _MissingLifecycleScraper(_LifecycleScraper):
    produce_state_law_frontier_closure = (
        BaseStateScraper.produce_state_law_frontier_closure
    )


class _FailingLifecycleScraper(_LifecycleScraper):
    async def produce_state_law_frontier_closure(
        self,
        *,
        canonical_output_projection: Mapping[str, Any],
    ) -> Path:
        del canonical_output_projection
        raise RuntimeError("independent frontier replay failed")


class _SharedCatalogLifecycleScraper(_LifecycleScraper):
    catalog_calls = 0
    produce_state_law_frontier_closure = (
        BaseStateScraper.produce_state_law_frontier_closure
    )

    def fetch_official(self, code: str = "WI") -> OfficialFetch:
        type(self).catalog_calls += 1
        assert code == "WI"
        rows = (
            {
                "canonical_key": "wi:title-1",
                "source_url": self.get_base_url(),
                "text": "Wisconsin Statutes title one catalog unit",
            },
        )
        body = b"Wisconsin official title catalog"
        frontier = {
            "bundle_closed": False,
            "closed": True,
            "enumerator_closed": True,
            "expected_index_units": 1,
            "method": "pagination",
            "pagination_closed": True,
            "remaining_bundle_members": [],
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": 1,
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return OfficialFetch(
            jurisdiction_code="WI",
            request_bytes=b"GET /statutes/statutes/1 HTTP/1.1\nhost: docs.legis.wisconsin.gov\n",
            response_bytes=b"HTTP/1.1 200 OK\n\n" + body,
            body_bytes=body,
            source_domain="docs.legis.wisconsin.gov",
            source_path="/statutes/statutes/1",
            frontier=frontier,
            rows=rows,
            transport_kind="live_https",
            fixture=False,
            observed_at="2026-08-24T08:00:00Z",
            edition="2026",
            legal_as_of="2026-08-24T00:00:00Z",
            first_hierarchy_unit="wi:title-1",
            last_hierarchy_unit="wi:title-1",
        )


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scraper_type: type[BaseStateScraper],
    *,
    strict: bool,
    max_statutes: int | None = None,
    strict_full_text: bool = True,
) -> dict[str, Any]:
    from ipfs_datasets_py.processors.legal_scrapers import state_scrapers

    monkeypatch.setenv(
        state_laws_scraper.MULTIFETCH_EVIDENCE_ROOT_ENV,
        str(tmp_path / "evidence"),
    )
    if strict:
        monkeypatch.setenv(state_laws_scraper.STRICT_MULTIFETCH_EVIDENCE_ENV, "1")
    else:
        monkeypatch.delenv(
            state_laws_scraper.STRICT_MULTIFETCH_EVIDENCE_ENV,
            raising=False,
        )
    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(
        state_scrapers,
        "get_scraper_for_state",
        lambda state_code, state_name: scraper_type(state_code, state_name),
    )
    return state_laws_scraper._scrape_state_once_sync(
        state_code="WI",
        legal_areas=None,
        rate_limit_delay=0.0,
        max_statutes=max_statutes,
        strict_full_text=strict_full_text,
        min_full_text_chars=100,
        hydrate_statute_text=False,
    )


def test_output_projection_binds_exact_final_statute_keys() -> None:
    projection = build_canonical_state_law_output_projection(
        [
            {"state_code": "WI", "statute_id": "WI-1.01"},
            {"state_code": "WI", "statute_id": "WI-1.02"},
        ],
        jurisdiction="WI",
    )

    assert projection["schema_version"] == CANONICAL_OUTPUT_PROJECTION_SCHEMA
    assert projection["canonical_row_count"] == 2
    assert projection["canonical_keys"] == ["WI-1.01", "WI-1.02"]
    assert len(projection["canonical_keys_sha256"]) == 64

    with pytest.raises(StateLawMultiFetchAcquisitionError, match="unique"):
        build_canonical_state_law_output_projection(
            [
                {"state_code": "WI", "statute_id": "WI-1.01"},
                {"state_code": "WI", "statute_id": "WI-1.01"},
            ],
            jurisdiction="WI",
        )


def test_runner_invokes_producer_after_strict_final_filtering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _LifecycleScraper.producer_calls = 0
    result = _run(tmp_path, monkeypatch, _LifecycleScraper, strict=True)

    assert result["error"] is None
    assert result["statutes_count"] == 1
    assert result["statute_data"]["strict_removed_count"] == 1
    lifecycle = result["acquisition_evidence"]["source_frontier_lifecycle"]
    assert lifecycle["status"] == "retained_and_verified"
    assert lifecycle["canonical_output_projection"]["canonical_row_count"] == 1
    assert _LifecycleScraper.producer_calls == 1


def test_shared_bridge_reuses_state_owned_enumerator_before_and_after_parser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _SharedCatalogLifecycleScraper.catalog_calls = 0
    monkeypatch.setattr(
        state_laws_scraper,
        "inventory_state_scraper_transport_bypasses",
        lambda _scraper: {"complete": True, "candidate_count": 0, "candidates": []},
    )

    result = _run(
        tmp_path,
        monkeypatch,
        _SharedCatalogLifecycleScraper,
        strict=True,
    )

    assert result["error"] is None
    assert _SharedCatalogLifecycleScraper.catalog_calls == 2
    lifecycle = result["acquisition_evidence"]["source_frontier_lifecycle"]
    assert lifecycle["status"] == "retained_and_verified"
    assert lifecycle["canonical_output_projection"]["canonical_row_count"] == 1
    closure_input_path = Path(lifecycle["closure_input_path"])
    assert closure_input_path.parent.name == "closure-inputs"
    assert result["acquisition_evidence"]["closure_input_path"] == str(
        closure_input_path
    )
    closure_input = json.loads(closure_input_path.read_text(encoding="utf-8"))
    assert closure_input["acquisition_path_ids"] == ["wi-docs-statutes"]
    observations = sorted(
        (tmp_path / "evidence" / "WI" / "frontiers" / "official-catalog-observations")
        .glob("*/*/WI/body.bin")
    )
    assert len(observations) == 2
    assert all(path.read_bytes() == b"Wisconsin official title catalog" for path in observations)


def test_missing_producer_is_diagnostic_non_strict_and_blocking_strict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagnostic = _run(
        tmp_path / "diagnostic",
        monkeypatch,
        _MissingLifecycleScraper,
        strict=False,
    )
    assert diagnostic["error"] is None
    assert "source_frontier_producer_missing" in diagnostic[
        "acquisition_evidence"
    ]["eligibility_blockers"]
    assert diagnostic["acquisition_evidence"]["source_frontier_lifecycle"][
        "status"
    ] == "missing"

    blocked = _run(
        tmp_path / "strict",
        monkeypatch,
        _MissingLifecycleScraper,
        strict=True,
    )
    assert "source_frontier_producer_missing" in str(blocked["error"])


def test_producer_failure_is_diagnostic_non_strict_and_fail_closed_strict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagnostic = _run(
        tmp_path / "diagnostic",
        monkeypatch,
        _FailingLifecycleScraper,
        strict=False,
    )
    assert diagnostic["error"] is None
    lifecycle = diagnostic["acquisition_evidence"]["source_frontier_lifecycle"]
    assert lifecycle["status"] == "failed"
    assert "independent frontier replay failed" in lifecycle["error"]

    blocked = _run(
        tmp_path / "strict",
        monkeypatch,
        _FailingLifecycleScraper,
        strict=True,
    )
    assert "source_frontier_producer_failed" in str(blocked["error"])


def test_bounded_run_never_invokes_frontier_producer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _LifecycleScraper.producer_calls = 0
    result = _run(
        tmp_path,
        monkeypatch,
        _LifecycleScraper,
        strict=False,
        max_statutes=1,
        strict_full_text=False,
    )

    lifecycle = result["acquisition_evidence"]["source_frontier_lifecycle"]
    assert lifecycle["status"] == "not_invoked_non_full_scope"
    assert _LifecycleScraper.producer_calls == 0
    assert "bounded_scrape_cannot_close_full_frontier" in result[
        "acquisition_evidence"
    ]["eligibility_blockers"]


def test_retention_rejects_catalog_keys_in_place_of_final_section_keys(
    tmp_path: Path,
) -> None:
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="WisconsinParser",
    )
    projection = build_canonical_state_law_output_projection(
        [{"state_code": "WI", "statute_id": "WI-1.01"}],
        jurisdiction="WI",
    )
    completion = closed_jurisdiction_receipt(
        "WI",
        discovered=1,
        fetched=1,
        excluded=0,
        quarantined=0,
        failed_final=0,
        source_domain="docs.legis.wisconsin.gov",
        canonical_keys=["title-1"],
        derived_keys=["title-1"],
        row_count=1,
    )

    with pytest.raises(StateLawMultiFetchAcquisitionError, match="canonical_keys"):
        ledger.retain_frontier_closure_projection(
            completion,
            replayed_frontier=dict(completion["frontier"]),
            canonical_output_projection=projection,
            release_point=hashlib.sha256(b"wi-release").hexdigest(),
            official_source_url=(
                "https://docs.legis.wisconsin.gov/statutes/statutes/1"
            ),
            acquisition_path_ids=["wi-docs-statutes"],
            observation_time="2026-08-24T08:02:00Z",
            source_software_version="state-scraper/lifecycle-test",
        )
