from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
    OfficialFetch,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import base_scraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    BaseStateScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.registry import (
    StateScraperRegistry,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.retained_shared_frontier import (
    capture_retained_shared_official_frontier_observation,
)


class _RetainedCatalogScraper:
    state_code = "AK"

    def __init__(self, evidence_root: Path) -> None:
        self._state_law_acquisition_ledger = SimpleNamespace(
            frontiers_dir=evidence_root / "frontiers",
            jurisdiction_root=evidence_root,
        )
        self.reparse_phases: list[str] = []

    def fetch_official(self, code: str = "AK") -> OfficialFetch:
        del code
        raise AssertionError("retained replay must not call live acquisition")

    def _reparse_shared_official_frontier_from_retained_inputs(
        self,
        *,
        phase: str,
    ) -> tuple[OfficialFetch, list[dict[str, Any]]]:
        self.reparse_phases.append(phase)
        return (
            OfficialFetch(
                jurisdiction_code="AK",
                request_bytes=b"GET /catalog HTTP/1.1\nhost: law.example.gov\n",
                response_bytes=b"retained official catalog",
                body_bytes=b"retained official catalog",
                source_domain="law.example.gov",
                source_path="/catalog",
                frontier={
                    "closed": True,
                    "enumerator_closed": True,
                    "expected_index_units": 1,
                    "unvisited_continuation_links": [],
                    "visited_index_units": 1,
                },
                rows=(
                    {
                        "canonical_key": "ak:title-1",
                        "source_url": "https://law.example.gov/catalog",
                        "text": "Exact retained official catalog unit",
                    },
                ),
                transport_kind="live_https",
                fixture=False,
                observed_at="2026-08-28T00:00:00Z",
            ),
            [
                {
                    "official_url": "https://law.example.gov/catalog",
                    "retrieved_at": "2026-08-29T00:00:00+00:00",
                }
            ],
        )


def test_retained_shared_frontier_helper_never_offloads_to_anyio_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scraper = _RetainedCatalogScraper(tmp_path / "evidence")

    def _forbid_thread_offload(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("retained catalog replay created a worker thread")

    monkeypatch.setattr(base_scraper.asyncio, "to_thread", _forbid_thread_offload)

    observation = capture_retained_shared_official_frontier_observation(
        scraper,
        phase="replay",
    )

    assert scraper.reparse_phases == ["replay"]
    assert observation["retained_replay"] is True
    assert observation["observed_at"] == "2026-08-29T00:00:00+00:00"
    assert observation["fetch"].rows[0]["canonical_key"] == "ak:title-1"
    assert observation["checkpoint"].completed is True
    assert observation["relative_root"].startswith(
        "frontiers/official-catalog-observations/replay/"
    )


def test_every_shared_official_frontier_state_owns_capture_override() -> None:
    inherited_base_capture: list[str] = []

    for state_code in sorted(StateScraperRegistry.get_all_registered_states()):
        scraper_class = StateScraperRegistry.get_scraper_class(state_code)
        assert scraper_class is not None
        scraper = scraper_class.__new__(scraper_class)
        if not scraper._supports_shared_official_frontier_bridge():
            continue
        state_capture = scraper_class.__dict__.get(
            "_capture_shared_official_frontier_observation"
        )
        if (
            state_capture is None
            or state_capture
            is BaseStateScraper._capture_shared_official_frontier_observation
        ):
            inherited_base_capture.append(state_code)

    assert inherited_base_capture == [], (
        "shared official-frontier states must own a retained-inline capture "
        "override instead of inheriting BaseStateScraper: "
        + ",".join(inherited_base_capture)
    )
