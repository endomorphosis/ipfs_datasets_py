"""Offline end-to-end certification for Arkansas's exact-current preflight."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas import (
    ArkansasDelegatedCorpusBlockedError,
    ArkansasScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas_lexis import (
    ARKANSAS_DELEGATED_INVENTORY_SHA256,
    ARKANSAS_ENACTMENT_TOC_SELECTION_PLAN_SHA256,
    ARKANSAS_ENACTMENT_TOC_SOURCE_INPUT_CONTRACT,
    CURRENT_VARIANT_RESOLVER_PARSER_NAME,
    load_exact_retained_inventory,
    resolve_enactment_toc_source_bound_variants,
)

_DEFAULT_REINDEX_ROOT = Path(
    "/home/barberb/.ipfs_datasets/state_laws/"
    "legal-corpora-reindex-20260824"
)
_INVENTORY_PATH = Path(
    os.environ.get("ARKANSAS_EXACT_CURRENT_TEST_INVENTORY")
    or _DEFAULT_REINDEX_ROOT
    / "arkansas-delegated-inventory-v6"
    / "arkansas-lexis-toc.json"
)
_PROOF_ROOT = Path(
    os.environ.get("ARKANSAS_EXACT_CURRENT_TEST_EVIDENCE_ROOT")
    or _DEFAULT_REINDEX_ROOT / "arkansas-current-resolution-evidence-v1"
)
_EXPECTED_UNRESOLVED = [
    "11-10-803",
    "19-42-201",
    "23-4-909",
    "26-51-905",
    "27-14-802",
    "27-14-803",
    "5-64-308",
]


def _require_retained_evidence() -> None:
    if not _INVENTORY_PATH.is_file():
        pytest.skip("exact retained Arkansas inventory is not installed")
    fetches = _PROOF_ROOT / "AR" / "fetches"
    objects = _PROOF_ROOT / "AR" / "objects"
    if not fetches.is_dir() or not objects.is_dir():
        pytest.skip("exact retained Arkansas proof ledger is not installed")


def _evidence_counts() -> tuple[int, int]:
    return (
        len(list((_PROOF_ROOT / "AR" / "fetches").glob("*.json"))),
        len(list((_PROOF_ROOT / "AR" / "objects").glob("*.bin"))),
    )


def _proof_ledger() -> StateLawMultiFetchAcquisitionLedger:
    return StateLawMultiFetchAcquisitionLedger(
        _PROOF_ROOT,
        jurisdiction="AR",
        parser_name=CURRENT_VARIANT_RESOLVER_PARSER_NAME,
        retained_replay_only=True,
    )


def test_retained_current_frontier_replays_to_exact_30_selected_7_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_retained_evidence()
    before = _evidence_counts()
    inventory, inventory_sha256 = load_exact_retained_inventory(_INVENTORY_PATH)
    assert inventory_sha256 == ARKANSAS_DELEGATED_INVENTORY_SHA256

    ledger = _proof_ledger()
    scraper = ArkansasScraper("AR", "Arkansas")
    scraper.attach_arkansas_current_variant_resolution_ledger(ledger)

    async def _network_forbidden(*_args, **_kwargs):
        raise AssertionError("exact-current preflight must be retained replay only")

    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback",
        _network_forbidden,
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_page_contents_with_archival_fallback_retrying_residuals",
        _network_forbidden,
    )
    result = asyncio.run(
        scraper._resolve_exact_current_variant_frontier(
            nodes=inventory.nodes,
            observed_at=inventory.observed_at,
            inventory_sha256=inventory_sha256,
        )
    )

    assert result["baseline_counts"] == {
        "selected_current_locator": 94,
        "no_current_locator": 1,
        "unresolved": 37,
    }
    assert result["current_counts"] == {
        "selected_current_locator": 124,
        "no_current_locator": 1,
        "unresolved": 7,
    }
    assert result["original_conflict_counts"] == {
        "selected_current_locator": 30,
        "no_current_locator": 0,
        "unresolved": 7,
    }
    assert result["unresolved_section_numbers"] == _EXPECTED_UNRESOLVED
    assert result["enactment_toc"]["resolution_count"] == 29
    assert all(
        item["selection_plan_sha256"]
        == ARKANSAS_ENACTMENT_TOC_SELECTION_PLAN_SHA256
        for item in result["enactment_toc"]["resolutions"]
    )
    assert result["hr5330"]["disposition"] == "selected_current_locator"
    assert result["hr5330"]["transport_batch"]["network_requested_pages"] == 0
    assert result["act283"]["disposition"] == "unresolved"
    assert len(result["act283"]["missing_source_urls"]) == 2
    assert result["decision_sha256"] == (
        "edb8578ae9029280f6bd134d89fd81722a2291e6e1a63158bf4dfbe8002b9450"
    )
    assert result["authorizing_for_materialization"] is False

    ordered_keys = sorted(ARKANSAS_ENACTMENT_TOC_SOURCE_INPUT_CONTRACT)
    retained = ledger.replay_retained_parser_inputs(
        requests=tuple(
            (
                ARKANSAS_ENACTMENT_TOC_SOURCE_INPUT_CONTRACT[key][0],
                {
                    "method": "GET",
                    "url": ARKANSAS_ENACTMENT_TOC_SOURCE_INPUT_CONTRACT[key][0],
                },
            )
            for key in ordered_keys
        )
    )
    retained_by_key = dict(zip(ordered_keys, retained, strict=True))
    retained_by_key.pop("A2")
    with pytest.raises(ValueError, match="proof bundle is incomplete"):
        resolve_enactment_toc_source_bound_variants(
            inventory.nodes,
            inventory_sha256=inventory_sha256,
            retained_inputs=retained_by_key,
        )
    with pytest.raises(ValueError, match="inventory fingerprint drifted"):
        resolve_enactment_toc_source_bound_variants(
            inventory.nodes,
            inventory_sha256="0" * 64,
            retained_inputs={},
        )
    assert _evidence_counts() == before == (65, 65)


def test_full_corpus_path_runs_retained_preflight_before_any_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_retained_evidence()
    before = _evidence_counts()
    scraper = ArkansasScraper("AR", "Arkansas")
    checkpoints: list[tuple[list[object], dict[str, object]]] = []

    async def _no_official(*_args, **_kwargs):
        return []

    async def _network_forbidden(*_args, **_kwargs):
        raise AssertionError("configured retained preflight must precede network")

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setenv("ARKANSAS_LEXIS_INVENTORY_PATH", str(_INVENTORY_PATH))
    monkeypatch.setenv(
        "ARKANSAS_CURRENT_VARIANT_EVIDENCE_ROOT",
        str(_PROOF_ROOT),
    )
    monkeypatch.delenv("ARKANSAS_CONSTITUTION_TEXT", raising=False)
    monkeypatch.delenv("ARKANSAS_SECTION_HTML", raising=False)
    monkeypatch.setattr(scraper, "_scrape_official_arkansas_code", _no_official)
    monkeypatch.setattr(scraper, "_probe_delegated_arkansas_code", _network_forbidden)
    monkeypatch.setattr(scraper, "_scrape_justia_titles", _network_forbidden)
    monkeypatch.setattr(
        scraper,
        "_write_partial_checkpoint",
        lambda rows, **kwargs: checkpoints.append((list(rows), kwargs)) or True,
    )

    with pytest.raises(
        ArkansasDelegatedCorpusBlockedError,
        match="current_variant_frontier_unresolved",
    ) as exc_info:
        asyncio.run(
            scraper.scrape_code(
                "Arkansas Code",
                scraper.OFFICIAL_CODE_INDEX,
                max_statutes=None,
            )
        )

    current = exc_info.value.evidence["current_variants"]
    assert current["original_conflict_counts"] == {
        "selected_current_locator": 30,
        "no_current_locator": 0,
        "unresolved": 7,
    }
    assert current["unresolved_section_numbers"] == _EXPECTED_UNRESOLVED
    assert checkpoints[-1][1]["stage_label"] == "arkansas:delegated_body_blocked"
    assert _evidence_counts() == before == (65, 65)
