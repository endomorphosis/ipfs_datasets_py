"""Hard offline guarantees for retained state-law parser-input replay."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Mapping

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
    StateLawRetainedReplayOnlyError,
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
    OfficialFetch,
    compute_frontier_digest,
)
from ipfs_datasets_py.processors.legal_data.state_laws_run_seal import (
    IN_PROGRESS_EVIDENCE_MARKER,
    NONQUIESCENT_EVIDENCE_MARKER,
)
from ipfs_datasets_py.processors.legal_scrapers import state_laws_scraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    base_scraper,
    pennsylvania,
    state_archival_fetch,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    BaseStateScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.pennsylvania import (
    PennsylvaniaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.retained_replay_network_guard import (
    retained_replay_network_guard,
)
from ipfs_datasets_py.processors.web_archiving import (
    common_crawl_integration,
    wayback_machine_engine,
)

OFFICIAL_HIT = "https://example.gov/code/1"
OFFICIAL_MISS = "https://example.gov/code/2"
PA_CATALOG_HTML = b"""<!doctype html><html><body>
<a href="/statutes/consolidated/view-statute?txtType=PDF&amp;ttl=01">Title 1</a>
</body></html>"""


class _ReplayScraper(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://example.gov/code"

    def get_code_list(self) -> list[dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> list[Any]:
        return []


@pytest.fixture
def replay_scraper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> _ReplayScraper:
    monkeypatch.setenv(
        "LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR",
        str(tmp_path / "page-cache"),
    )
    monkeypatch.setenv("LEGAL_SCRAPER_IPFS_PAGE_CACHE_ENABLED", "0")
    monkeypatch.setenv("LEGAL_SCRAPER_FETCH_CACHE_ENABLED", "0")
    return _ReplayScraper("WI", "Wisconsin")


def _direct_receipt(url: str, body: bytes) -> dict[str, str]:
    return {
        "content_sha256": hashlib.sha256(body).hexdigest(),
        "official_url": url,
        "source_transport": "direct",
    }


def _offline_ledger(root: Path) -> StateLawMultiFetchAcquisitionLedger:
    return StateLawMultiFetchAcquisitionLedger(
        root,
        jurisdiction="WI",
        parser_name="_ReplayScraper",
        retained_replay_only=True,
    )


def test_ordinary_ledger_misses_keep_legacy_optional_replay_behavior(
    tmp_path: Path,
) -> None:
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="WI",
        parser_name="_ReplayScraper",
    )

    assert ledger.retained_replay_only is False
    assert (
        ledger.replay_retained_parser_input(
            official_url=OFFICIAL_MISS,
            sanitized_request={"method": "GET", "url": OFFICIAL_MISS},
        )
        is None
    )
    assert (
        ledger.replay_retained_parser_input_file(
            official_url=OFFICIAL_MISS,
            sanitized_request={"method": "GET", "url": OFFICIAL_MISS},
        )
        is None
    )


@pytest.mark.asyncio
async def test_retained_replay_only_exact_hits_skip_every_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replay_scraper: _ReplayScraper,
) -> None:
    evidence_root = tmp_path / "evidence"
    body = b"retained official statute body"
    seed = StateLawMultiFetchAcquisitionLedger(
        evidence_root,
        jurisdiction="WI",
        parser_name="_ReplayScraper",
    )
    seed.retain_parser_input(
        official_url=OFFICIAL_HIT,
        body=body,
        transport_receipt=_direct_receipt(OFFICIAL_HIT, body),
        sanitized_request={"method": "GET", "url": OFFICIAL_HIT},
    )
    replay_scraper.attach_state_law_acquisition_ledger(
        _offline_ledger(evidence_root)
    )

    async def _forbid_cache(*_args: Any, **_kwargs: Any) -> bytes:
        raise AssertionError("retained hit reached a cache lookup")

    def _forbid_direct(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("retained hit reached direct HTTP")

    class _ForbiddenArchivalClient:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("retained hit constructed an archival client")

    monkeypatch.setattr(
        replay_scraper,
        "_load_page_bytes_from_any_cache",
        _forbid_cache,
    )
    monkeypatch.setattr(base_scraper, "_state_law_http_request", _forbid_direct)
    monkeypatch.setattr(
        state_archival_fetch,
        "ArchivalFetchClient",
        _ForbiddenArchivalClient,
    )

    singleton = await replay_scraper._fetch_page_content_with_archival_fallback(
        OFFICIAL_HIT
    )
    plural = await replay_scraper._fetch_page_contents_with_archival_fallback(
        [OFFICIAL_HIT, OFFICIAL_HIT],
        prefer_direct=False,
        wayback_prefix_inventory=True,
    )
    custom = await replay_scraper._fetch_parser_input_with_transport(OFFICIAL_HIT)

    assert singleton == body
    assert plural.payloads == [body, body]
    assert plural.errors == [None, None]
    assert plural.stats["network_requested_pages"] == 0
    assert plural.stats["retained_replay_pages"] == 2
    assert custom == body


@pytest.mark.asyncio
async def test_retained_replay_only_miss_stops_all_network_and_pointer_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replay_scraper: _ReplayScraper,
) -> None:
    replay_scraper.attach_state_law_acquisition_ledger(
        _offline_ledger(tmp_path / "empty-evidence")
    )
    calls = {
        "cache": 0,
        "direct": 0,
        "archive": 0,
        "common_crawl": 0,
        "wayback": 0,
        "remote_pointer": 0,
    }

    async def _cache(*_args: Any, **_kwargs: Any) -> bytes:
        calls["cache"] += 1
        return b""

    def _direct(*_args: Any, **_kwargs: Any) -> Any:
        calls["direct"] += 1
        raise AssertionError("offline miss reached direct HTTP")

    class _ArchivalClient:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            calls["archive"] += 1

        async def fetch_many_with_fallback(
            self,
            *_args: Any,
            **_kwargs: Any,
        ) -> Any:
            calls["archive"] += 1
            raise AssertionError("offline miss reached archive fetch")

    class _CommonCrawlLoader:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            calls["common_crawl"] += 1

    async def _wayback(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        calls["wayback"] += 1
        raise AssertionError("offline miss reached Wayback")

    class _CommonCrawlEngine:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            calls["remote_pointer"] += 1

    monkeypatch.setattr(
        replay_scraper,
        "_load_page_bytes_from_any_cache",
        _cache,
    )
    monkeypatch.setattr(base_scraper, "_state_law_http_request", _direct)
    monkeypatch.setattr(state_archival_fetch, "ArchivalFetchClient", _ArchivalClient)
    monkeypatch.setattr(
        state_laws_scraper,
        "inventory_state_scraper_transport_bypasses",
        lambda _scraper: {"complete": True},
    )
    from ipfs_datasets_py.processors.legal_scrapers import common_crawl_index_loader

    monkeypatch.setattr(
        common_crawl_index_loader,
        "CommonCrawlIndexLoader",
        _CommonCrawlLoader,
    )
    monkeypatch.setattr(
        wayback_machine_engine,
        "fetch_wayback_cdx_rows",
        _wayback,
    )
    monkeypatch.setattr(
        wayback_machine_engine,
        "fetch_wayback_capture_inventory",
        _wayback,
    )
    monkeypatch.setattr(
        common_crawl_integration,
        "CommonCrawlSearchEngine",
        _CommonCrawlEngine,
    )

    with pytest.raises(StateLawRetainedReplayOnlyError, match="ledger miss"):
        await replay_scraper._fetch_parser_input_with_transport(OFFICIAL_MISS)
    with pytest.raises(StateLawRetainedReplayOnlyError, match="ledger miss"):
        await replay_scraper._fetch_page_contents_with_archival_fallback(
            [OFFICIAL_MISS],
            prefer_direct=False,
            wayback_prefix_inventory=True,
        )
    with pytest.raises(StateLawRetainedReplayOnlyError, match="Common Crawl"):
        await replay_scraper._search_state_common_crawl_records(
            domain_terms=["example.gov"]
        )
    with pytest.raises(StateLawRetainedReplayOnlyError, match="Wayback"):
        await replay_scraper._fetch_wayback_cdx_rows(
            "https://web.archive.org/cdx/search/cdx?url=example.gov/*"
        )
    with pytest.raises(StateLawRetainedReplayOnlyError, match="remote-pointer"):
        await replay_scraper.query_warc_file(
            "https://data.commoncrawl.org/crawl-data/example.warc.gz",
            0,
            128,
        )
    with pytest.raises(StateLawRetainedReplayOnlyError, match="file-backed"):
        replay_scraper._state_law_acquisition_ledger.replay_retained_parser_input_file(
            official_url=OFFICIAL_MISS,
            sanitized_request={"method": "GET", "url": OFFICIAL_MISS},
        )

    assert calls == {
        "cache": 0,
        "direct": 0,
        "archive": 0,
        "common_crawl": 0,
        "wayback": 0,
        "remote_pointer": 0,
    }


def test_worker_constructs_offline_ledger_before_scrape_all(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers import state_scrapers

    observed: dict[str, Any] = {}

    class _WorkerScraper:
        state_code = "WI"

        def bind_state_law_run_environment(self, _binding: Any) -> None:
            return None

        def bind_partial_checkpoint_generation(self, **_kwargs: Any) -> None:
            return None

        def attach_state_law_acquisition_ledger(self, ledger: Any) -> None:
            observed["ledger"] = ledger

        async def scrape_all(self, **_kwargs: Any) -> list[Any]:
            ledger = observed.get("ledger")
            assert ledger is not None
            assert ledger.retained_replay_only is True
            observed["scrape_all"] = True
            return []

        def get_base_url(self) -> str:
            return "https://example.gov/code"

        def get_fetch_analytics_snapshot(self) -> dict[str, Any]:
            return {}

    monkeypatch.setattr(
        state_scrapers,
        "get_scraper_for_state",
        lambda _code, _name: _WorkerScraper(),
    )
    monkeypatch.setattr(
        state_laws_scraper,
        "inventory_state_scraper_transport_bypasses",
        lambda _scraper: {"complete": True, "candidate_count": 0},
    )
    monkeypatch.setenv(
        state_laws_scraper.MULTIFETCH_EVIDENCE_ROOT_ENV,
        str(tmp_path / "evidence"),
    )
    monkeypatch.setenv(state_laws_scraper.STRICT_MULTIFETCH_EVIDENCE_ENV, "1")
    monkeypatch.setenv(state_laws_scraper.RETAINED_REPLAY_ONLY_ENV, "1")

    state_laws_scraper._scrape_state_once_sync(
        state_code="WI",
        legal_areas=None,
        rate_limit_delay=0.0,
        max_statutes=1,
        strict_full_text=False,
        min_full_text_chars=1,
        hydrate_statute_text=False,
    )

    assert observed["scrape_all"] is True
    assert observed["ledger"].retained_replay_only is True


def test_whole_retained_worker_blocks_caught_post_scrape_dns_and_poisons_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers import state_scrapers

    class _PostScrapeLeakScraper:
        state_code = "WI"

        def bind_state_law_run_environment(self, _binding: Any) -> None:
            return None

        def bind_partial_checkpoint_generation(self, **_kwargs: Any) -> None:
            return None

        def attach_state_law_acquisition_ledger(self, _ledger: Any) -> None:
            return None

        async def scrape_all(self, **_kwargs: Any) -> list[Any]:
            return []

        def get_base_url(self) -> str:
            return "https://example.gov/code"

        def get_fetch_analytics_snapshot(self) -> dict[str, Any]:
            # The runner catches analytics exceptions.  The outer guard must
            # still remember the audit violation and reject the worker.
            socket.getaddrinfo("retained-replay-must-not-resolve.invalid", 443)
            return {}

    evidence_root = tmp_path / "evidence"
    monkeypatch.setattr(
        state_scrapers,
        "get_scraper_for_state",
        lambda _code, _name: _PostScrapeLeakScraper(),
    )
    monkeypatch.setattr(
        state_laws_scraper,
        "inventory_state_scraper_transport_bypasses",
        lambda _scraper: {"complete": True, "candidate_count": 0},
    )

    with pytest.raises(
        StateLawRetainedReplayOnlyError,
        match="forbidden operation socket.getaddrinfo",
    ):
        state_laws_scraper._scrape_state_once_sync(
            state_code="WI",
            legal_areas=None,
            rate_limit_delay=0.0,
            max_statutes=1,
            strict_full_text=False,
            min_full_text_chars=1,
            hydrate_statute_text=False,
            bound_evidence_root=str(evidence_root),
            bound_strict_evidence=True,
            bound_retained_replay_only=True,
        )

    poison = evidence_root / NONQUIESCENT_EVIDENCE_MARKER
    assert poison.is_file()
    payload = json.loads(poison.read_text(encoding="utf-8"))
    assert payload["attempted_event"] == "socket.getaddrinfo"
    assert payload["affected_states"] == ["WI"]
    assert payload["authorizing_for_publication"] is False


def test_real_guard_lifecycle_preserves_fresh_source_correspondence_identity(
    tmp_path: Path,
) -> None:
    """A real guard lifecycle does not alter its loaded executable identity."""

    evidence_root = tmp_path / "evidence"
    child_program = r"""
import sys
from pathlib import Path

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import base_scraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    retained_replay_network_guard as guard_module,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.pennsylvania import (
    PennsylvaniaScraper,
)

scraper = PennsylvaniaScraper("PA", "Pennsylvania")
assert not hasattr(guard_module, "_AUDIT_HOOK_INSTALLED")
before = scraper._state_law_frontier_source_software_version(
    require_loaded_source_correspondence=True,
)
ledger = StateLawMultiFetchAcquisitionLedger(
    Path(sys.argv[1]),
    jurisdiction="PA",
    parser_name="PennsylvaniaScraper",
    retained_replay_only=True,
)
with guard_module.retained_replay_network_guard(
    ledger=ledger,
    state_code="PA",
):
    pass
with base_scraper._SOURCE_CORRESPONDENCE_CACHE_LOCK:
    base_scraper._SOURCE_CORRESPONDENCE_CACHE.clear()
after = scraper._state_law_frontier_source_software_version(
    require_loaded_source_correspondence=True,
)
assert after == before
print(after)
"""
    environment = dict(os.environ)
    environment["PYTHONPYCACHEPREFIX"] = str(tmp_path / "pycache")
    completed = subprocess.run(
        [sys.executable, "-c", child_program, str(evidence_root)],
        cwd=Path(__file__).resolve().parents[3],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert "PennsylvaniaScraper@sha256:" in completed.stdout


def test_pre_guard_audit_installer_tampering_cannot_suppress_denial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        retained_replay_network_guard as guard_module,
    )

    evidence_root = tmp_path / "evidence"
    ledger = _offline_ledger(evidence_root)
    late_install_calls = 0

    def _suppressed_late_install(_hook: Any) -> None:
        nonlocal late_install_calls
        late_install_calls += 1

    # The inert hook was installed when the module executable loaded.  A
    # parser cannot forge mutable first-use state or suppress that hook by
    # replacing the public installer before guard entry.
    monkeypatch.setattr(sys, "addaudithook", _suppressed_late_install)
    assert not hasattr(guard_module, "_AUDIT_HOOK_INSTALLED")
    with pytest.raises(
        StateLawRetainedReplayOnlyError,
        match="forbidden operation socket.__new__",
    ):
        with guard_module.retained_replay_network_guard(
            ledger=ledger,
            state_code="WI",
        ):
            socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    assert late_install_calls == 0
    poison = evidence_root / NONQUIESCENT_EVIDENCE_MARKER
    assert poison.is_file()
    payload = json.loads(poison.read_text(encoding="utf-8"))
    assert payload["attempted_event"] == "socket.__new__"
    assert payload["authorizing_for_publication"] is False


def test_worker_rejects_transport_bypass_before_scrape_all(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers import state_scrapers

    called = False

    class _BypassScraper:
        def bind_state_law_run_environment(self, _binding: Any) -> None:
            return None

        async def scrape_all(self, **_kwargs: Any) -> list[Any]:
            nonlocal called
            called = True
            return []

    monkeypatch.setattr(
        state_scrapers,
        "get_scraper_for_state",
        lambda _code, _name: _BypassScraper(),
    )
    monkeypatch.setattr(
        state_laws_scraper,
        "inventory_state_scraper_transport_bypasses",
        lambda _scraper: {
            "complete": False,
            "candidate_count": 1,
            "candidates": [{"kind": "direct_http"}],
        },
    )
    monkeypatch.setenv(
        state_laws_scraper.MULTIFETCH_EVIDENCE_ROOT_ENV,
        str(tmp_path / "evidence"),
    )
    monkeypatch.setenv(state_laws_scraper.STRICT_MULTIFETCH_EVIDENCE_ENV, "1")
    monkeypatch.setenv(state_laws_scraper.RETAINED_REPLAY_ONLY_ENV, "1")

    with pytest.raises(RuntimeError, match="transport bypass"):
        state_laws_scraper._scrape_state_once_sync(
            state_code="WI",
            legal_areas=None,
            rate_limit_delay=0.0,
            max_statutes=1,
            strict_full_text=False,
            min_full_text_chars=1,
            hydrate_statute_text=False,
        )

    assert called is False


def _load_refresh_module() -> Any:
    script_path = (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "ops"
        / "legal_data"
        / "refresh_state_laws_corpus.py"
    )
    spec = importlib.util.spec_from_file_location(
        "refresh_state_laws_corpus_retained_replay_only_test",
        script_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_refresh_cli_threads_and_restores_retained_replay_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refresh = _load_refresh_module()
    evidence_root = tmp_path / "evidence"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "refresh_state_laws_corpus.py",
            "--states",
            "WI",
            "--output-root",
            str(tmp_path / "output"),
            "--scrape",
            "--acquisition-evidence-root",
            str(evidence_root),
            "--retained-replay-only",
            "--dry-run",
        ],
    )
    args = refresh.parse_args()
    assert args.retained_replay_only is True

    result = asyncio.run(refresh.refresh_state_laws_corpus(args))
    assert result["status"] == "dry_run"
    assert result["plan"]["retained_replay_only"] is True
    assert result["plan"]["strict_acquisition_evidence"] is True

    replay_env = state_laws_scraper.RETAINED_REPLAY_ONLY_ENV
    strict_env = state_laws_scraper.STRICT_MULTIFETCH_EVIDENCE_ENV
    monkeypatch.setenv(replay_env, "prior-replay")
    monkeypatch.setenv(strict_env, "prior-strict")
    with refresh._state_scraper_run_environment(
        output_root=tmp_path / "output",
        full_corpus=True,
        acquisition_evidence_root=evidence_root,
        strict_acquisition_evidence=True,
        retained_replay_only=True,
    ):
        assert os.environ[replay_env] == "1"
        assert os.environ[strict_env] == "1"
    assert os.environ[replay_env] == "prior-replay"
    assert os.environ[strict_env] == "prior-strict"


def test_refresh_retained_replay_only_rejects_remote_release_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refresh = _load_refresh_module()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "refresh_state_laws_corpus.py",
            "--states",
            "WI",
            "--output-root",
            str(tmp_path / "output"),
            "--scrape",
            "--acquisition-evidence-root",
            str(tmp_path / "evidence"),
            "--retained-replay-only",
            "--publish-to-hf",
            "--dry-run",
        ],
    )

    result = asyncio.run(refresh.refresh_state_laws_corpus(refresh.parse_args()))

    assert result["status"] == "failed_preflight"
    assert result["reason"] == (
        "refresh_external_mutation_requires_sealed_production_runner"
    )
    assert result["authorizing_for_publication"] is False


def _seed_retained_catalog(
    root: Path,
    *,
    jurisdiction: str,
    parser_name: str,
    official_url: str,
    body: bytes,
    sanitized_request: Mapping[str, Any] | None = None,
) -> None:
    seed = StateLawMultiFetchAcquisitionLedger(
        root,
        jurisdiction=jurisdiction,
        parser_name=parser_name,
    )
    seed.retain_parser_input(
        official_url=official_url,
        body=body,
        transport_receipt=_direct_receipt(official_url, body),
        retrieved_at="2026-08-24T08:00:00Z",
        sanitized_request=(
            dict(sanitized_request)
            if sanitized_request is not None
            else {"method": "GET", "url": official_url}
        ),
    )


@pytest.mark.asyncio
async def test_pa_shared_frontier_first_and_replay_reparse_retained_bytes_zero_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_root = tmp_path / "evidence"
    _seed_retained_catalog(
        evidence_root,
        jurisdiction="PA",
        parser_name="PennsylvaniaScraper",
        official_url=PennsylvaniaScraper.OFFICIAL_ENTRY_URL,
        body=PA_CATALOG_HTML,
    )
    scraper = PennsylvaniaScraper("PA", "Pennsylvania")
    scraper.attach_state_law_acquisition_ledger(
        StateLawMultiFetchAcquisitionLedger(
            evidence_root,
            jurisdiction="PA",
            parser_name="PennsylvaniaScraper",
            retained_replay_only=True,
        )
    )
    calls = {"urlopen": 0, "socket": 0, "subprocess": 0}

    def _forbid_urlopen(*_args: Any, **_kwargs: Any) -> Any:
        calls["urlopen"] += 1
        raise AssertionError("PA retained catalog replay reached raw urllib")

    def _forbid_socket(*_args: Any, **_kwargs: Any) -> Any:
        calls["socket"] += 1
        raise AssertionError("PA retained catalog replay reached raw socket/DNS")

    def _forbid_subprocess(*_args: Any, **_kwargs: Any) -> Any:
        calls["subprocess"] += 1
        raise AssertionError("PA retained catalog replay launched a subprocess")

    monkeypatch.setattr(pennsylvania.urllib.request, "urlopen", _forbid_urlopen)
    monkeypatch.setattr(socket, "getaddrinfo", _forbid_socket)
    monkeypatch.setattr(pennsylvania.subprocess, "run", _forbid_subprocess)

    first = await scraper._capture_shared_official_frontier_observation(
        phase="first"
    )
    scraper._state_law_first_official_frontier_observation = first
    scraper._state_law_official_frontier_observation_error = ""
    projection = build_canonical_state_law_output_projection(
        [{"state_code": "PA", "statute_id": "PA-1.01"}],
        jurisdiction="PA",
    )
    closure_path = await scraper.produce_state_law_frontier_closure(
        canonical_output_projection=projection,
    )

    assert calls == {"urlopen": 0, "socket": 0, "subprocess": 0}
    assert first["retained_replay"] is True
    assert first["fetch"].transport_kind == "retained_parser_input_replay:direct"
    assert len(first["retained_inputs"]) == 1
    assert first["retained_inputs"][0]["body_sha256"] == hashlib.sha256(
        PA_CATALOG_HTML
    ).hexdigest()
    assert closure_path is not None
    closure = json.loads(Path(closure_path).read_text(encoding="utf-8"))
    completion = closure["completion_receipt"]
    assert completion["replay"]["network_requests"] == 0
    assert completion["replay"]["source"] == "retained_parser_inputs"
    assert completion["transport"]["retained_replay"] is True
    assert completion["transport"]["kind"] == (
        "retained_parser_input_replay:direct"
    )
    replay_observation = completion["source_catalog_evidence"][
        "replay_observation"
    ]
    assert replay_observation["retained_replay"] is True
    assert replay_observation["retained_parser_inputs"][0]["body_sha256"] == (
        hashlib.sha256(PA_CATALOG_HTML).hexdigest()
    )


def test_pa_inventory_exposes_live_bridge_transport_but_attests_replay_guard() -> None:
    inventory = state_laws_scraper.inventory_state_scraper_transport_bypasses(
        PennsylvaniaScraper
    )

    assert inventory["complete"] is True
    assert inventory["candidate_count"] == 0
    assert inventory["shared_frontier_live_transport_candidate_count"] == 2
    assert {
        item["kind"]
        for item in inventory["shared_frontier_live_transport_candidates"]
    } == {"urllib_urlopen"}
    assert inventory["shared_frontier_retained_replay_guard"] == (
        "exact_ledger_input_reparse_with_process_global_network_deny"
    )


class _TripletCatalogScraper(BaseStateScraper):
    OFFICIAL_ENTRY_URL = "https://example.gov/catalog"

    def get_base_url(self) -> str:
        return self.OFFICIAL_ENTRY_URL

    def get_code_list(self) -> list[dict[str, str]]:
        return []

    async def scrape_code(self, code_name: str, code_url: str) -> list[Any]:
        return []

    def _official_http_get(
        self,
        url: str,
        timeout: int = 20,
    ) -> tuple[bytes, bytes, bytes]:
        del url, timeout
        raise AssertionError("triplet live transport must be injected")

    def fetch_official(self, code: str = "WI") -> OfficialFetch:
        request, response, body = self._official_http_get(self.OFFICIAL_ENTRY_URL)
        assert request and response == body == b"triplet retained catalog"
        frontier = {
            "bundle_closed": False,
            "closed": True,
            "enumerator_closed": True,
            "expected_index_units": 1,
            "pagination_closed": True,
            "remaining_bundle_members": [],
            "toc_exhausted": True,
            "unvisited_continuation_links": [],
            "visited_index_units": 1,
        }
        frontier["frontier_digest_sha256"] = compute_frontier_digest(frontier)
        return OfficialFetch(
            jurisdiction_code=code,
            request_bytes=request,
            response_bytes=response,
            body_bytes=body,
            source_domain="example.gov",
            source_path="/catalog",
            frontier=frontier,
            rows=(
                {
                    "canonical_key": "wi:title-1",
                    "source_url": self.OFFICIAL_ENTRY_URL,
                    "text": "Exact retained triplet catalog unit",
                },
            ),
            transport_kind="live_https",
            fixture=False,
            first_hierarchy_unit="wi:title-1",
            last_hierarchy_unit="wi:title-1",
        )


@pytest.mark.asyncio
async def test_shared_frontier_triplet_helper_receives_exact_retained_body(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    body = b"triplet retained catalog"
    _seed_retained_catalog(
        evidence_root,
        jurisdiction="WI",
        parser_name="_TripletCatalogScraper",
        official_url=_TripletCatalogScraper.OFFICIAL_ENTRY_URL,
        body=body,
    )
    scraper = _TripletCatalogScraper("WI", "Wisconsin")
    scraper.attach_state_law_acquisition_ledger(
        StateLawMultiFetchAcquisitionLedger(
            evidence_root,
            jurisdiction="WI",
            parser_name="_TripletCatalogScraper",
            retained_replay_only=True,
        )
    )

    observation = await scraper._capture_shared_official_frontier_observation(
        phase="first"
    )

    assert observation["retained_replay"] is True
    assert observation["fetch"].body_bytes == body
    assert observation["retained_inputs"][0]["body_sha256"] == (
        hashlib.sha256(body).hexdigest()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["missing", "ambiguous"])
async def test_shared_frontier_missing_or_ambiguous_input_fails_before_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    evidence_root = tmp_path / "evidence"
    if mode == "ambiguous":
        _seed_retained_catalog(
            evidence_root,
            jurisdiction="PA",
            parser_name="PennsylvaniaScraper",
            official_url=PennsylvaniaScraper.OFFICIAL_ENTRY_URL,
            body=PA_CATALOG_HTML,
        )
        _seed_retained_catalog(
            evidence_root,
            jurisdiction="PA",
            parser_name="PennsylvaniaScraper",
            official_url=PennsylvaniaScraper.OFFICIAL_ENTRY_URL,
            body=PA_CATALOG_HTML,
            sanitized_request={
                "headers": {"Accept": "text/html"},
                "method": "GET",
                "url": PennsylvaniaScraper.OFFICIAL_ENTRY_URL,
            },
        )
    scraper = PennsylvaniaScraper("PA", "Pennsylvania")
    scraper.attach_state_law_acquisition_ledger(
        StateLawMultiFetchAcquisitionLedger(
            evidence_root,
            jurisdiction="PA",
            parser_name="PennsylvaniaScraper",
            retained_replay_only=True,
        )
    )
    calls = {"urlopen": 0, "socket": 0}

    def _urlopen(*_args: Any, **_kwargs: Any) -> Any:
        calls["urlopen"] += 1
        raise AssertionError("fail-closed catalog replay reached urllib")

    def _socket(*_args: Any, **_kwargs: Any) -> Any:
        calls["socket"] += 1
        raise AssertionError("fail-closed catalog replay reached DNS")

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    monkeypatch.setattr(socket, "getaddrinfo", _socket)

    expected = "missing" if mode == "missing" else "ambiguous"
    with pytest.raises(Exception, match=expected):
        await scraper._capture_shared_official_frontier_observation(phase="first")
    assert calls == {"urlopen": 0, "socket": 0}


@pytest.mark.asyncio
async def test_forbidden_replay_observation_poisons_root_and_cannot_retain_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_root = tmp_path / "evidence"
    _seed_retained_catalog(
        evidence_root,
        jurisdiction="PA",
        parser_name="PennsylvaniaScraper",
        official_url=PennsylvaniaScraper.OFFICIAL_ENTRY_URL,
        body=PA_CATALOG_HTML,
    )
    scraper = PennsylvaniaScraper("PA", "Pennsylvania")
    scraper.attach_state_law_acquisition_ledger(
        StateLawMultiFetchAcquisitionLedger(
            evidence_root,
            jurisdiction="PA",
            parser_name="PennsylvaniaScraper",
            retained_replay_only=True,
        )
    )
    first = await scraper._capture_shared_official_frontier_observation(
        phase="first"
    )
    scraper._state_law_first_official_frontier_observation = first
    original_fetch = scraper.fetch_official

    def _leaking_fetch(code: str = "PA") -> OfficialFetch:
        socket.getaddrinfo("www.palegis.us", 443)
        return original_fetch(code)

    retained_closure_calls = 0

    def _retain(*_args: Any, **_kwargs: Any) -> Path:
        nonlocal retained_closure_calls
        retained_closure_calls += 1
        return tmp_path / "must-not-exist.json"

    monkeypatch.setattr(scraper, "fetch_official", _leaking_fetch)
    monkeypatch.setattr(
        scraper,
        "retain_state_law_frontier_closure_projection",
        _retain,
    )
    projection = build_canonical_state_law_output_projection(
        [{"state_code": "PA", "statute_id": "PA-1.01"}],
        jurisdiction="PA",
    )

    with pytest.raises(StateLawRetainedReplayOnlyError, match="forbidden operation"):
        await scraper.produce_state_law_frontier_closure(
            canonical_output_projection=projection,
        )

    poison = evidence_root / NONQUIESCENT_EVIDENCE_MARKER
    assert poison.is_file()
    assert retained_closure_calls == 0
    assert json.loads(poison.read_text(encoding="utf-8"))[
        "authorizing_for_publication"
    ] is False


@pytest.mark.parametrize(
    "launch_kind",
    ["exec", "fork_spawn", "posix_spawn", "popen", "system"],
)
def test_process_wide_guard_blocks_raw_process_launch_paths(
    tmp_path: Path,
    launch_kind: str,
) -> None:
    evidence_root = tmp_path / launch_kind
    ledger = _offline_ledger(evidence_root)

    with pytest.raises(StateLawRetainedReplayOnlyError, match="forbidden operation"):
        with retained_replay_network_guard(ledger=ledger, state_code="WI"):
            try:
                if launch_kind == "exec":
                    os.execv("/bin/true", ["/bin/true"])
                elif launch_kind == "fork_spawn":
                    os.spawnv(os.P_WAIT, "/bin/true", ["/bin/true"])
                elif launch_kind == "posix_spawn":
                    os.posix_spawn("/bin/true", ["/bin/true"], dict(os.environ))
                elif launch_kind == "popen":
                    subprocess.Popen(["/bin/true"])
                else:
                    os.system("true")
            except StateLawRetainedReplayOnlyError:
                # The exit check must still fail if state code catches the
                # immediate audit-hook exception.
                pass

    assert (evidence_root / NONQUIESCENT_EVIDENCE_MARKER).is_file()


def test_unpropagated_child_thread_cannot_outlive_global_deny_lease(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    ledger = _offline_ledger(evidence_root)
    in_progress = {
        "active_states": ["WI"],
        "authorizing_for_publication": False,
        "in_progress": True,
        "run_id": "01234567-89ab-cdef-0123-456789abcdef",
        "schema": "test-in-progress",
    }
    (evidence_root / IN_PROGRESS_EVIDENCE_MARKER).write_text(
        json.dumps(in_progress, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    started = threading.Event()
    release = threading.Event()
    child_errors: list[BaseException] = []

    def _delayed_network() -> None:
        started.set()
        release.wait(timeout=10)
        try:
            socket.getaddrinfo("example.com", 443)
        except BaseException as exc:
            child_errors.append(exc)

    child = threading.Thread(target=_delayed_network, name="delayed-network")
    with pytest.raises(
        StateLawRetainedReplayOnlyError,
        match="thread.survived_retained_worker",
    ):
        with retained_replay_network_guard(ledger=ledger, state_code="WI"):
            child.start()
            assert started.wait(timeout=5)

    poison = evidence_root / NONQUIESCENT_EVIDENCE_MARKER
    assert poison.is_file()
    payload = json.loads(poison.read_text(encoding="utf-8"))
    assert payload["run_id"] == in_progress["run_id"]
    assert payload["affected_states"] == ["WI"]
    assert payload["attempted_event"] == "thread.survived_retained_worker"

    release.set()
    child.join(timeout=5)
    assert not child.is_alive()
    assert child_errors
    assert isinstance(child_errors[0], StateLawRetainedReplayOnlyError)
    deadline = time.monotonic() + 5
    while any(
        thread.name == "state-laws-retained-replay-quiescence-monitor"
        for thread in threading.enumerate()
    ) and time.monotonic() < deadline:
        time.sleep(0.01)


def test_guard_allows_only_local_pdftotext_subprocess(
    tmp_path: Path,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        retained_replay_network_guard as guard_module,
    )

    trusted = str(guard_module._TRUSTED_PDFTOTEXT_PATH or "")
    if not trusted or not Path(trusted).is_file():
        pytest.skip("no trusted root-owned pdftotext is bound")
    evidence_root = tmp_path / "evidence"
    ledger = _offline_ledger(evidence_root)

    with retained_replay_network_guard(ledger=ledger, state_code="WI"):
        result = subprocess.run(
            [trusted, "-v"],
            capture_output=True,
            check=False,
        )

    assert result.returncode == 0
    assert not (evidence_root / NONQUIESCENT_EVIDENCE_MARKER).exists()


def test_pennsylvania_pdf_extract_uses_trusted_absolute_pdftotext(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        retained_replay_network_guard as guard_module,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.pennsylvania import (
        PennsylvaniaScraper,
    )

    trusted = str(guard_module._TRUSTED_PDFTOTEXT_PATH or "")
    if not trusted:
        pytest.skip("no trusted root-owned pdftotext is bound")
    seen: list[list[str]] = []

    def _capture(command, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        seen.append([str(part) for part in command])
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="§ 1. Hello\n".encode("utf-8"),
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", _capture)
    scraper = PennsylvaniaScraper("PA", "Pennsylvania")
    ledger = _offline_ledger(tmp_path / "evidence")
    with retained_replay_network_guard(ledger=ledger, state_code="PA"):
        text = scraper._extract_pdf_text_preserve_layout(b"%PDF-1.4 fake")

    assert text.startswith("§ 1. Hello")
    assert seen
    assert seen[0][0] == trusted
    assert Path(seen[0][0]).is_absolute()
    assert "pdftotext" not in seen[0][:1]


def test_basename_and_path_lookalike_pdftotext_are_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_root = tmp_path / "evidence"
    ledger = _offline_ledger(evidence_root)
    lookalike = tmp_path / "pdftotext"
    lookalike.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    lookalike.chmod(0o755)
    monkeypatch.setenv(
        "PATH",
        str(tmp_path) + os.pathsep + os.environ.get("PATH", ""),
    )

    with pytest.raises(
        StateLawRetainedReplayOnlyError,
        match="forbidden operation subprocess.Popen",
    ):
        with retained_replay_network_guard(ledger=ledger, state_code="WI"):
            try:
                subprocess.Popen(["pdftotext", "-v"])
            except StateLawRetainedReplayOnlyError:
                pass

    poison = evidence_root / NONQUIESCENT_EVIDENCE_MARKER
    assert poison.is_file()

    absolute_root = tmp_path / "absolute-lookalike"
    absolute_ledger = _offline_ledger(absolute_root)
    with pytest.raises(
        StateLawRetainedReplayOnlyError,
        match="forbidden operation subprocess.Popen",
    ):
        with retained_replay_network_guard(
            ledger=absolute_ledger,
            state_code="WI",
        ):
            try:
                subprocess.Popen([str(lookalike), "-v"])
            except StateLawRetainedReplayOnlyError:
                pass

    assert (absolute_root / NONQUIESCENT_EVIDENCE_MARKER).is_file()


def test_guard_entry_fails_closed_if_audit_hook_is_inert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        retained_replay_network_guard as guard_module,
    )

    def _inert_hook(event: str, args: tuple[Any, ...]) -> None:
        return None

    monkeypatch.setattr(
        guard_module._retained_replay_audit_hook,
        "__code__",
        _inert_hook.__code__,
    )
    evidence_root = tmp_path / "evidence"
    ledger = _offline_ledger(evidence_root)

    with pytest.raises(
        StateLawRetainedReplayOnlyError,
        match="audit.hook_not_live",
    ):
        with retained_replay_network_guard(ledger=ledger, state_code="WI"):
            raise AssertionError("inert audit hook must not enter the worker")

    poison = evidence_root / NONQUIESCENT_EVIDENCE_MARKER
    assert poison.is_file()
    payload = json.loads(poison.read_text(encoding="utf-8"))
    assert payload["attempted_event"] == "audit.hook_not_live"
    assert payload["authorizing_for_publication"] is False


def test_finished_nested_worker_ident_cannot_hide_later_child(
    tmp_path: Path,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        retained_replay_network_guard as guard_module,
    )

    evidence_root = tmp_path / "evidence"
    ledger = _offline_ledger(evidence_root)
    nested_ident: dict[str, int | None] = {"value": None}
    nested_error: list[BaseException] = []

    def _nested_worker() -> None:
        nested_ident["value"] = threading.get_ident()
        try:
            with retained_replay_network_guard(
                ledger=ledger,
                state_code="WI",
            ):
                pass
        except BaseException as exc:
            nested_error.append(exc)

    started = threading.Event()
    release = threading.Event()
    child_errors: list[BaseException] = []

    def _delayed_network() -> None:
        started.set()
        release.wait(timeout=10)
        try:
            socket.getaddrinfo("example.com", 443)
        except BaseException as exc:
            child_errors.append(exc)

    child = threading.Thread(target=_delayed_network, name="post-nested-child")
    with pytest.raises(
        StateLawRetainedReplayOnlyError,
        match="thread.survived_retained_worker",
    ):
        with retained_replay_network_guard(ledger=ledger, state_code="WI"):
            nested = threading.Thread(
                target=_nested_worker,
                name="nested-retained-worker",
            )
            nested.start()
            nested.join(timeout=5)
            assert not nested.is_alive()
            assert not nested_error
            assert nested_ident["value"] is not None
            with guard_module._ACTIVE_GUARDS_LOCK:
                active_idents = (
                    guard_module._active_worker_thread_idents_locked()
                )
            assert nested_ident["value"] not in active_idents
            child.start()
            assert started.wait(timeout=5)

    poison = evidence_root / NONQUIESCENT_EVIDENCE_MARKER
    assert poison.is_file()
    release.set()
    child.join(timeout=5)
    assert not child.is_alive()
    assert child_errors
    assert isinstance(child_errors[0], StateLawRetainedReplayOnlyError)
    deadline = time.monotonic() + 5
    while any(
        thread.name == "state-laws-retained-replay-quiescence-monitor"
        for thread in threading.enumerate()
    ) and time.monotonic() < deadline:
        time.sleep(0.01)


@pytest.mark.parametrize("socket_kind", ["bind", "create", "sendmsg"])
def test_guard_denies_exposed_inet_socket_operations_but_preserves_af_unix(
    tmp_path: Path,
    socket_kind: str,
) -> None:
    evidence_root = tmp_path / socket_kind
    ledger = _offline_ledger(evidence_root)
    inet_socket = None
    if socket_kind in {"bind", "sendmsg"}:
        inet_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        with pytest.raises(
            StateLawRetainedReplayOnlyError,
            match="forbidden operation",
        ):
            with retained_replay_network_guard(ledger=ledger, state_code="WI"):
                try:
                    if socket_kind == "create":
                        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    elif socket_kind == "bind":
                        assert inet_socket is not None
                        inet_socket.bind(("127.0.0.1", 0))
                    else:
                        assert inet_socket is not None
                        inet_socket.sendmsg(
                            [b"retained-replay-must-not-send"],
                            [],
                            0,
                            ("127.0.0.1", 9),
                        )
                except StateLawRetainedReplayOnlyError:
                    pass
    finally:
        if inet_socket is not None:
            inet_socket.close()

    assert (evidence_root / NONQUIESCENT_EVIDENCE_MARKER).is_file()

    unix_root = tmp_path / f"{socket_kind}-unix"
    unix_ledger = _offline_ledger(unix_root)
    left, right = socket.socketpair()
    try:
        with retained_replay_network_guard(
            ledger=unix_ledger,
            state_code="WI",
        ):
            left.sendmsg([b"local"])
            assert right.recv(5) == b"local"
    finally:
        left.close()
        right.close()
    assert not (unix_root / NONQUIESCENT_EVIDENCE_MARKER).exists()


def test_overlapping_guards_poison_each_root_before_earlier_child_can_escape(
    tmp_path: Path,
) -> None:
    roots = {name: tmp_path / name for name in ("a", "b")}
    ledgers = {name: _offline_ledger(root) for name, root in roots.items()}
    ready_a = threading.Event()
    ready_b = threading.Event()
    child_started = threading.Event()
    exit_a = threading.Event()
    exit_b = threading.Event()
    release_child = threading.Event()
    worker_errors: dict[str, BaseException] = {}
    child_errors: list[BaseException] = []
    child_holder: list[threading.Thread] = []

    def _child() -> None:
        child_started.set()
        release_child.wait(timeout=10)
        try:
            socket.getaddrinfo("example.com", 443)
        except BaseException as exc:
            child_errors.append(exc)

    def _worker_a() -> None:
        try:
            with retained_replay_network_guard(
                ledger=ledgers["a"],
                state_code="WI",
            ):
                ready_a.set()
                assert ready_b.wait(timeout=5)
                child = threading.Thread(target=_child, name="guard-a-child")
                child_holder.append(child)
                child.start()
                assert child_started.wait(timeout=5)
                assert exit_a.wait(timeout=5)
        except BaseException as exc:
            worker_errors["a"] = exc

    def _worker_b() -> None:
        assert ready_a.wait(timeout=5)
        try:
            with retained_replay_network_guard(
                ledger=ledgers["b"],
                state_code="WI",
            ):
                ready_b.set()
                assert exit_b.wait(timeout=10)
        except BaseException as exc:
            worker_errors["b"] = exc

    worker_a = threading.Thread(target=_worker_a, name="retained-worker-a")
    worker_b = threading.Thread(target=_worker_b, name="retained-worker-b")
    worker_a.start()
    worker_b.start()
    assert child_started.wait(timeout=5)
    exit_a.set()
    worker_a.join(timeout=5)
    assert not worker_a.is_alive()
    assert isinstance(worker_errors.get("a"), StateLawRetainedReplayOnlyError)
    assert all(
        (root / NONQUIESCENT_EVIDENCE_MARKER).is_file()
        for root in roots.values()
    )

    release_child.set()
    assert child_holder
    child_holder[0].join(timeout=5)
    assert not child_holder[0].is_alive()
    assert child_errors
    assert isinstance(child_errors[0], StateLawRetainedReplayOnlyError)
    exit_b.set()
    worker_b.join(timeout=5)
    assert not worker_b.is_alive()
    assert isinstance(worker_errors.get("b"), StateLawRetainedReplayOnlyError)

    deadline = time.monotonic() + 5
    while any(
        thread.name == "state-laws-retained-replay-quiescence-monitor"
        for thread in threading.enumerate()
    ) and time.monotonic() < deadline:
        time.sleep(0.01)
