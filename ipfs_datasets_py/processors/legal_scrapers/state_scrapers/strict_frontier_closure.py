"""Shared publication closure for exact state-law source frontiers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def replay_exact_retained_state_record(
    scraper: Any,
    *,
    official_url: str,
    sanitized_request: Mapping[str, Any],
    frontier_name: str,
    refresh: bool = True,
) -> Any:
    """Replay and verify one retained record without network fallback.

    Lifecycle producers use this narrower seam after the acquisition pass has
    finished.  It deliberately calls the ledger rather than a scraper fetch
    method, so a missing request, ambiguous observation, mutated object, or
    detached envelope fails certification instead of becoming a new request.
    The verified record retains its envelope, receipt, and transport evidence
    so high-volume callers do not need to replay or hash the same leaf twice.
    """

    import hashlib

    ledger = getattr(scraper, "_state_law_acquisition_ledger", None)
    if ledger is None:
        raise RuntimeError(
            f"{frontier_name} retained replay requires an attached ledger"
        )
    if refresh:
        refresh_entries = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh_entries):
            refresh_entries()
    retained = ledger.replay_retained_parser_input(
        official_url=str(official_url or "").strip(),
        sanitized_request=dict(sanitized_request),
    )
    if retained is None:
        raise RuntimeError(
            f"{frontier_name} retained parser input is missing: {official_url}"
        )
    body = bytes(getattr(retained.envelope, "body", b"") or b"")
    content = getattr(retained.receipt, "content", None)
    expected_sha256 = str(getattr(content, "sha256", "") or "").strip()
    if (
        not body
        or len(expected_sha256) != 64
        or hashlib.sha256(body).hexdigest() != expected_sha256
    ):
        raise RuntimeError(
            f"{frontier_name} retained parser input failed fixity: {official_url}"
        )
    return retained


def replay_exact_retained_state_input(
    scraper: Any,
    *,
    official_url: str,
    sanitized_request: Mapping[str, Any],
    frontier_name: str,
    refresh: bool = True,
) -> bytes:
    """Return verified retained parser bytes without permitting a fetch."""

    retained = replay_exact_retained_state_record(
        scraper,
        official_url=official_url,
        sanitized_request=sanitized_request,
        frontier_name=frontier_name,
        refresh=refresh,
    )
    return bytes(getattr(retained.envelope, "body", b"") or b"")


def replay_exact_retained_state_records(
    scraper: Any,
    *,
    requests: Sequence[tuple[str, Mapping[str, Any]]],
    frontier_name: str,
    refresh: bool = True,
) -> tuple[Any, ...]:
    """Replay an ordered retained batch through the ledger's O(n + m) seam."""

    import hashlib

    ledger = getattr(scraper, "_state_law_acquisition_ledger", None)
    if ledger is None:
        raise RuntimeError(
            f"{frontier_name} retained replay requires an attached ledger"
        )
    if refresh:
        refresh_entries = getattr(ledger, "refresh_existing_entries", None)
        if callable(refresh_entries):
            refresh_entries()
    replay_plural = getattr(ledger, "replay_retained_parser_inputs", None)
    if not callable(replay_plural):
        raise RuntimeError(
            f"{frontier_name} retained ledger lacks plural replay support"
        )
    normalized = [
        (str(url or "").strip(), dict(sanitized_request))
        for url, sanitized_request in requests
    ]
    retained_rows = tuple(replay_plural(requests=normalized))
    if len(retained_rows) != len(normalized):
        raise RuntimeError(
            f"{frontier_name} retained plural replay returned unaligned records"
        )
    for (official_url, _sanitized_request), retained in zip(
        normalized,
        retained_rows,
        strict=True,
    ):
        body = bytes(getattr(retained.envelope, "body", b"") or b"")
        content = getattr(retained.receipt, "content", None)
        expected_sha256 = str(getattr(content, "sha256", "") or "").strip()
        if (
            not body
            or len(expected_sha256) != 64
            or hashlib.sha256(body).hexdigest() != expected_sha256
        ):
            raise RuntimeError(
                f"{frontier_name} retained parser input failed fixity: "
                f"{official_url}"
            )
    return retained_rows


def retain_exact_state_frontier_closure(
    scraper: Any,
    *,
    canonical_output_projection: Mapping[str, Any],
    first_frontier: Mapping[str, Any],
    replayed_frontier: Mapping[str, Any],
    replay_rows: Sequence[Any],
    jurisdiction: str,
    source_domain: str,
    official_source_url: str,
    observed_at: str,
    legal_as_of: str,
    edition: str = "",
    boundary_first: str,
    boundary_last: str,
    bundle_total: int,
    pagination_total: int,
    transport: Mapping[str, Any],
) -> Path:
    """Seal exact retained replay, output identity, and disposition parity.

    State adapters remain responsible for source-specific enumeration and
    parsing.  This shared seam owns the publication invariants so adapters do
    not duplicate completion-receipt or canonical-output algebra.
    """

    from ...legal_data.open_us_law_acquisition_coordinator import (
        canonical_json_bytes,
    )
    from ...legal_data.state_laws_completeness import (
        closed_jurisdiction_receipt,
    )
    from ...legal_data.state_laws_multifetch_acquisition import (
        build_canonical_state_law_output_projection,
    )

    first = dict(first_frontier)
    replayed = dict(replayed_frontier)
    if canonical_json_bytes(first) != canonical_json_bytes(replayed):
        raise RuntimeError(
            f"{jurisdiction} first and retained-replay exact frontiers differ"
        )
    if any(
        frontier.get(field) is not True
        for frontier in (first, replayed)
        for field in ("closed", "enumerator_closed", "scope_closed", "algebra_closed")
    ):
        raise RuntimeError(f"{jurisdiction} exact frontier is not closed")

    replay_dict_rows = []
    for row in replay_rows:
        enriched = scraper._enrich_statute_structure(row)
        replay_dict_rows.append(enriched.to_dict())
    replay_projection = build_canonical_state_law_output_projection(
        replay_dict_rows,
        jurisdiction=jurisdiction,
    )

    output_keys_raw = canonical_output_projection.get("canonical_keys")
    replay_keys_raw = replay_projection.get("canonical_keys")
    if (
        not isinstance(output_keys_raw, Sequence)
        or isinstance(output_keys_raw, (str, bytes, bytearray))
        or not isinstance(replay_keys_raw, Sequence)
        or isinstance(replay_keys_raw, (str, bytes, bytearray))
    ):
        raise TypeError(
            f"{jurisdiction} canonical output lacks exact section identities"
        )
    output_keys = [str(item).strip() for item in output_keys_raw]
    replay_keys = [str(item).strip() for item in replay_keys_raw]
    if (
        not output_keys
        or any(not item for item in output_keys)
        or len(output_keys) != len(set(output_keys))
        or output_keys != replay_keys
    ):
        missing = sorted(set(replay_keys) - set(output_keys))
        extra = sorted(set(output_keys) - set(replay_keys))
        raise RuntimeError(
            f"{jurisdiction} final canonical identities do not exactly match "
            "retained source replay: "
            f"expected={len(replay_keys)} actual={len(output_keys)} "
            f"missing={missing[:3]} extra={extra[:3]}"
        )

    disposition = first.get("disposition")
    if not isinstance(disposition, Mapping):
        raise TypeError(f"{jurisdiction} exact frontier lacks disposition algebra")
    counts = {
        field: int(disposition.get(field) or 0)
        for field in (
            "discovered",
            "fetched",
            "excluded",
            "quarantined",
            "failed_final",
            "duplicates",
        )
    }
    if counts["discovered"] != sum(
        counts[field]
        for field in (
            "fetched",
            "excluded",
            "quarantined",
            "failed_final",
            "duplicates",
        )
    ):
        raise RuntimeError(f"{jurisdiction} source disposition algebra is not exact")
    if (
        counts["fetched"] != len(output_keys)
        or counts["fetched"] != len(replay_keys)
        or counts["quarantined"] != 0
        or counts["failed_final"] != 0
        or counts["duplicates"] != 0
    ):
        raise RuntimeError(
            f"{jurisdiction} final output changed exact source disposition counts"
        )

    completion = closed_jurisdiction_receipt(
        jurisdiction,
        discovered=counts["discovered"],
        fetched=counts["fetched"],
        excluded=counts["excluded"],
        quarantined=counts["quarantined"],
        failed_final=counts["failed_final"],
        duplicates=counts["duplicates"],
        source_domain=source_domain,
        canonical_keys=output_keys,
        derived_keys=output_keys,
    )
    completion.update(
        {
            "boundary_probes": {
                "bundle_total": int(bundle_total),
                "first_hierarchy_unit": str(boundary_first or ""),
                "last_hierarchy_unit": str(boundary_last or ""),
                "pagination_total": int(pagination_total),
            },
            "canonical_row_count": len(output_keys),
            "frontier": first,
            "legal_as_of": str(legal_as_of or ""),
            "observed_at": str(observed_at or ""),
            "replay": {
                "closed": True,
                "first_frontier_digest": str(
                    first.get("frontier_digest_sha256") or ""
                ),
                "network_requests": 0,
                "second_frontier_digest": str(
                    replayed.get("frontier_digest_sha256") or ""
                ),
                "source": "retained_parser_inputs",
            },
            "rights": {
                "basis": "public_law_no_state_copyright",
                "decision": "admit",
                "scope": "statutory_text",
            },
            "transport": dict(transport),
        }
    )
    normalized_edition = str(edition or "").strip()
    if normalized_edition:
        completion["edition"] = normalized_edition
    frontier_digest = str(first.get("frontier_digest_sha256") or "").strip()
    if len(frontier_digest) != 64:
        raise RuntimeError(f"{jurisdiction} exact frontier lacks a digest")
    return scraper.retain_state_law_frontier_closure_projection(
        completion,
        replayed_frontier=replayed,
        canonical_output_projection=canonical_output_projection,
        release_point=f"sha256:{frontier_digest}",
        official_source_url=official_source_url,
        acquisition_path_ids=scraper._catalog_acquisition_path_ids_for_source(
            official_source_url
        ),
        observation_time=str(observed_at or ""),
        source_software_version=scraper._state_law_frontier_source_software_version(),
    )


__all__ = [
    "replay_exact_retained_state_input",
    "replay_exact_retained_state_record",
    "replay_exact_retained_state_records",
    "retain_exact_state_frontier_closure",
]
