from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    strict_frontier_closure,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_hampshire import (
    NewHampshireScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.rhode_island import (
    RhodeIslandScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.washington import (
    WashingtonScraper,
)
from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
)


class _Ledger:
    def __init__(self) -> None:
        self.refresh_count = 0

    def refresh_existing_entries(self) -> None:
        self.refresh_count += 1


def test_shared_plural_retained_replay_preserves_order_and_fixity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WA",
        parser_name="WashingtonScraper",
    )
    urls = [
        "https://app.leg.wa.gov/RCW/default.aspx?cite=1.01.010",
        "https://app.leg.wa.gov/RCW/default.aspx?cite=1.04.010",
    ]
    bodies = [b"first retained RCW body", b"second retained RCW body"]
    for url, body in zip(urls, bodies, strict=True):
        ledger.retain_parser_input(
            official_url=url,
            body=body,
            transport_receipt={
                "content_sha256": hashlib.sha256(body).hexdigest(),
                "official_url": url,
                "source_transport": "direct",
            },
            retrieved_at="2026-08-25T00:00:00Z",
            sanitized_request={"method": "GET", "url": url},
        )

    def _network_must_not_run(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("shared retained plural replay attempted network I/O")

    monkeypatch.setattr("urllib.request.urlopen", _network_must_not_run)
    scraper = SimpleNamespace(_state_law_acquisition_ledger=ledger)
    replayed = strict_frontier_closure.replay_exact_retained_state_records(
        scraper,
        requests=[
            (urls[1], {"method": "GET", "url": urls[1]}),
            (urls[0], {"method": "GET", "url": urls[0]}),
        ],
        frontier_name="Washington section frontier",
        refresh=False,
    )

    assert [row.envelope.body for row in replayed] == [bodies[1], bodies[0]]


@pytest.mark.anyio
async def test_nh_retained_frontier_batch_never_reaches_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"<html><body>retained NH input</body></html>"
    replayed: list[tuple[str, bool]] = []

    def _replay(_scraper: Any, **kwargs: Any) -> tuple[Any, ...]:
        replayed.extend(
            (official_url, kwargs["refresh"])
            for official_url, _request in kwargs["requests"]
        )
        return tuple(
            SimpleNamespace(envelope=SimpleNamespace(body=payload))
            for _request in kwargs["requests"]
        )

    async def _network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("retained replay attempted a network request")

    monkeypatch.setattr(
        strict_frontier_closure,
        "replay_exact_retained_state_records",
        _replay,
    )
    scraper = NewHampshireScraper("NH", "New Hampshire")
    scraper._new_hampshire_retained_replay = True
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _network,
    )
    url = "https://gc.nh.gov/rsa/html/NHTOC/NHTOC-I.htm"

    rows = await scraper._fetch_new_hampshire_frontier_batch(
        [url],
        frontier_name="title",
        content_validator=lambda value: value == payload,
    )

    assert rows == [payload]
    assert replayed == [(url, False)]
    assert scraper._new_hampshire_frontier_batch_stats == [
        {
            "frontier_name": "title",
            "network_requested_pages": 0,
            "requested_pages": 1,
            "retained_replay_pages": 1,
        }
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scraper", "replay_flag", "fetch_name", "url", "payload"),
    [
        (
            RhodeIslandScraper("RI", "Rhode Island"),
            "_rhode_island_retained_replay",
            "_fetch_rhode_island_frontier_batch",
            "https://webserver.rilegislature.gov/Statutes/",
            b"<html><body>RI retained input</body></html>",
        ),
        (
            WashingtonScraper("WA", "Washington"),
            "_washington_retained_replay",
            "_fetch_washington_frontier_batch",
            "https://app.leg.wa.gov/RCW/default.aspx",
            b"<html><body><div id='contentWrapper'>WA retained input</div></body></html>",
        ),
    ],
)
async def test_ri_wa_retained_batches_preserve_aligned_evidence_without_network(
    monkeypatch: pytest.MonkeyPatch,
    scraper: Any,
    replay_flag: str,
    fetch_name: str,
    url: str,
    payload: bytes,
) -> None:
    envelope = SimpleNamespace(body=payload)
    transport = {
        "content_sha256": "a" * 64,
        "official_url": url,
        "source_transport": "direct",
    }
    replayed: list[tuple[str, bool]] = []

    def _replay(_scraper: Any, **kwargs: Any) -> tuple[Any, ...]:
        replayed.extend(
            (official_url, kwargs["refresh"])
            for official_url, _request in kwargs["requests"]
        )
        return tuple(
            SimpleNamespace(
                envelope=envelope,
                transport_receipt=transport,
            )
            for _request in kwargs["requests"]
        )

    async def _network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("retained replay attempted a network request")

    monkeypatch.setattr(
        strict_frontier_closure,
        "replay_exact_retained_state_records",
        _replay,
    )
    setattr(scraper, replay_flag, True)
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _network,
    )

    batch = await getattr(scraper, fetch_name)([url], frontier_name="root")

    assert batch.payloads == [payload]
    assert batch.parser_input_envelopes == [envelope]
    assert batch.transport_receipts == [transport]
    assert batch.stats["network_requested_pages"] == 0
    assert replayed == [(url, False)]


@pytest.mark.anyio
@pytest.mark.parametrize(
    (
        "scraper",
        "first_attr",
        "replay_attr",
        "replay_flag",
        "runner_name",
        "jurisdiction",
    ),
    [
        (
            NewHampshireScraper("NH", "New Hampshire"),
            "_last_new_hampshire_full_frontier",
            "_last_new_hampshire_replayed_frontier",
            "_new_hampshire_retained_replay",
            "_scrape_official_rsa_tree_batched",
            "NH",
        ),
        (
            RhodeIslandScraper("RI", "Rhode Island"),
            "_last_rhode_island_full_frontier",
            "_last_rhode_island_replayed_frontier",
            "_rhode_island_retained_replay",
            "_scrape_unbounded_rhode_island_frontier",
            "RI",
        ),
        (
            WashingtonScraper("WA", "Washington"),
            "_last_washington_full_frontier",
            "_last_washington_replayed_frontier",
            "_washington_retained_replay",
            "_scrape_unbounded_washington_frontier",
            "WA",
        ),
    ],
)
async def test_nh_ri_wa_closure_uses_independent_retained_replay(
    monkeypatch: pytest.MonkeyPatch,
    scraper: Any,
    first_attr: str,
    replay_attr: str,
    replay_flag: str,
    runner_name: str,
    jurisdiction: str,
) -> None:
    frontier = {
        "algebra_closed": True,
        "closed": True,
        "disposition": {
            "discovered": 1,
            "duplicates": 0,
            "excluded": 0,
            "failed_final": 0,
            "fetched": 1,
            "quarantined": 0,
        },
        "enumerator_closed": True,
        "frontier_digest_sha256": "b" * 64,
        "scope_closed": True,
        "source_input_count": 1,
    }
    observation = {
        "boundary_first": "first",
        "boundary_last": "last",
        "chapter_pages_fetched": 0,
        "code_name": f"{jurisdiction} code",
        "frontier": frontier,
        "input_reports": [
            {
                "content_sha256": "c" * 64,
                "source_role": "section",
                "source_url": "https://example.invalid/section",
            }
        ],
        "legal_as_of": "2026-08-25",
        "observed_at": "2026-08-25T00:00:00+00:00",
        "title_pages_fetched": 0,
    }
    setattr(scraper, first_attr, observation)
    ledger = _Ledger()
    scraper._state_law_acquisition_ledger = ledger

    async def _replay_runner(*_args: Any, **_kwargs: Any) -> list[Any]:
        assert getattr(scraper, replay_flag) is True
        setattr(scraper, replay_attr, dict(observation))
        return []

    captured: dict[str, Any] = {}

    def _retain(scraper_arg: Any, **kwargs: Any) -> Path:
        assert scraper_arg is scraper
        captured.update(kwargs)
        return Path("/tmp/nh-ri-wa-closure.json")

    monkeypatch.setattr(scraper, runner_name, _replay_runner)
    monkeypatch.setattr(
        strict_frontier_closure,
        "retain_exact_state_frontier_closure",
        _retain,
    )

    retained = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection={"canonical_keys": ["one"]}
    )

    assert retained == Path("/tmp/nh-ri-wa-closure.json")
    assert ledger.refresh_count == 1
    assert captured["jurisdiction"] == jurisdiction
    assert captured["first_frontier"] == frontier
    assert captured["replayed_frontier"] == frontier
    assert captured["transport"]["grouped_warc_recovery"] is True
    assert captured["transport"]["per_page_archive_loop"] is False
    assert captured["transport"]["retained_replay_network_requests"] == 0
    if jurisdiction == "WA":
        assert captured["transport"][
            "repeat_grouped_archive_inventory_on_residual"
        ] is False
        assert captured["transport"]["source_ordered_cross_parent_union"] is True
        assert captured["transport"]["wayback_prefix_inventory"] is True
    assert getattr(scraper, replay_flag) is False
