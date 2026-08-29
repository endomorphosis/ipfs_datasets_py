"""Synchronous retained replay for the shared official-frontier bridge.

Retained replay runs under a process-wide quiescence guard.  AnyIO's blocking
worker can outlive the short parser and artifact-write operations performed by
the shared bridge, so state scrapers use this helper to execute those already
retained operations inline.  Live acquisition continues to use the base
scraper's blocking offload.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse


def capture_retained_shared_official_frontier_observation(
    scraper: Any,
    *,
    phase: str,
) -> Dict[str, Any]:
    """Replay and retain one shared official-frontier observation inline."""

    ledger = getattr(scraper, "_state_law_acquisition_ledger", None)
    if ledger is None:
        raise RuntimeError("official frontier observation requires an attached ledger")
    fetcher = getattr(scraper, "fetch_official", None)
    if not callable(fetcher):
        raise RuntimeError("state scraper has no official frontier enumerator")

    from ...legal_data.open_us_law_acquisition_coordinator import (
        canonical_json_bytes,
    )
    from ...legal_data.open_us_law_live_evidence import (
        OfficialFetch,
        compute_frontier_digest,
        write_retained_artifacts,
    )

    fetch, retained_inputs = (
        scraper._reparse_shared_official_frontier_from_retained_inputs(phase=phase)
    )
    if not isinstance(fetch, OfficialFetch):
        raise RuntimeError("official frontier enumerator returned the wrong contract")
    if str(fetch.jurisdiction_code or "").strip().upper() != scraper.state_code.upper():
        raise RuntimeError("official frontier observation changed jurisdiction")
    if fetch.fixture is not False:
        raise RuntimeError("fixture frontier observations cannot authorize a crawl")
    if not fetch.request_bytes or not fetch.response_bytes or not fetch.body_bytes:
        raise RuntimeError("official frontier observation omitted retained raw bytes")
    if not fetch.rows:
        raise RuntimeError("official frontier observation contains no catalog units")
    if str(fetch.transport_kind or "").strip().lower() in {
        "",
        "fixture",
        "mock",
        "synthetic",
    }:
        raise RuntimeError("official frontier observation uses an invalid transport")

    source_domain = str(fetch.source_domain or "").strip().lower().strip(".")
    parsed_domain = urlparse(f"https://{source_domain}")
    if (
        not source_domain
        or parsed_domain.hostname != source_domain
        or parsed_domain.username is not None
        or parsed_domain.password is not None
    ):
        raise RuntimeError("official frontier observation has an invalid source domain")
    source_path = str(fetch.source_path or "").strip()
    if not source_path:
        raise RuntimeError("official frontier observation has no source path")

    frontier = dict(fetch.frontier)
    if (
        frontier.get("closed") is not True
        or frontier.get("enumerator_closed") is not True
        or list(frontier.get("unvisited_continuation_links") or [])
    ):
        raise RuntimeError("official frontier enumerator did not close its catalog")
    expected = frontier.get("expected_index_units")
    visited = frontier.get("visited_index_units")
    if (
        isinstance(expected, int)
        and not isinstance(expected, bool)
        and isinstance(visited, int)
        and not isinstance(visited, bool)
        and visited < expected
    ):
        raise RuntimeError("official frontier catalog traversal is incomplete")
    computed_frontier_digest = compute_frontier_digest(frontier)
    declared_frontier_digest = (
        str(frontier.get("frontier_digest_sha256") or "").strip().lower()
    )
    if (
        declared_frontier_digest
        and declared_frontier_digest != computed_frontier_digest
    ):
        raise RuntimeError("official frontier observation digest does not replay")

    identity_material = {
        "body_sha256": hashlib.sha256(fetch.body_bytes).hexdigest(),
        "frontier_sha256": computed_frontier_digest,
        "jurisdiction": scraper.state_code.upper(),
        "request_sha256": hashlib.sha256(fetch.request_bytes).hexdigest(),
        "response_sha256": hashlib.sha256(fetch.response_bytes).hexdigest(),
        "source_domain": source_domain,
        "source_path": source_path,
        "transport_kind": str(fetch.transport_kind).strip().lower(),
    }
    observation_digest = hashlib.sha256(
        canonical_json_bytes(identity_material)
    ).hexdigest()
    observation_root = (
        Path(ledger.frontiers_dir)
        / "official-catalog-observations"
        / str(phase or "observation").strip().lower()
        / observation_digest
    )
    checkpoint = write_retained_artifacts(
        observation_root,
        fetch,
        uncapped=True,
    )
    try:
        relative_root = (
            observation_root.resolve()
            .relative_to(Path(ledger.jurisdiction_root).resolve())
            .as_posix()
        )
    except ValueError as exc:
        raise RuntimeError("official frontier evidence escaped its ledger") from exc
    if retained_inputs:
        observation_time = max(
            str(row.get("retrieved_at") or "") for row in retained_inputs
        )
    else:
        observation_time = (
            str(fetch.observed_at) or datetime.now(timezone.utc).isoformat()
        )
    return {
        "checkpoint": checkpoint,
        "fetch": fetch,
        "frontier_digest": computed_frontier_digest,
        "observation_digest": observation_digest,
        "observed_at": observation_time,
        "relative_root": relative_root,
        "retained_inputs": retained_inputs,
        "retained_replay": True,
    }
