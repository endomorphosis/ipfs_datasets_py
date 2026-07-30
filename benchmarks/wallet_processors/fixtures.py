"""Fixed synthetic wallet ledger records for offline benchmarks.

Records use opaque synthetic identifiers only — no real addresses, keys, or
provider payloads.  The set size is fixed so records/sec and peak memory are
comparable across runs without depending on live provider latency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


# Fixed fixture size: large enough for meaningful throughput, small enough for
# CI.  Do not derive this from live network conditions.
FIXTURE_RECORD_COUNT = 2_048
FIXTURE_PAGE_SIZE = 64
FIXTURE_CHAIN_NAMESPACE = "eip155"
FIXTURE_NETWORK = "fixture-mainnet"
FIXTURE_PROVIDER = "fixture-rpc"
FIXTURE_GENESIS = "fixture-genesis-hash-v1"


@dataclass(frozen=True, slots=True)
class SyntheticLedgerRecord:
    """Minimal synthetic record used only by the fixture benchmark."""

    record_index: int
    block_number: int
    finality: str
    amount_units: int
    schema_version: str = "wallet-bench-record-v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "record_index": self.record_index,
            "block_number": self.block_number,
            "finality": self.finality,
            "amount_units": self.amount_units,
            # Opaque synthetic subject id — not a chain address.
            "subject_id": f"subject-{self.record_index:06d}",
            "observed_at": datetime(
                2025, 1, 1, tzinfo=timezone.utc
            ).isoformat(),
        }


def build_fixture_records(count: int = FIXTURE_RECORD_COUNT) -> tuple[SyntheticLedgerRecord, ...]:
    """Return a deterministic, fixed-size tuple of synthetic ledger records."""

    if count < 1:
        raise ValueError("count must be a positive integer")
    finalities = ("confirmed", "safe", "finalized", "pending")
    records: list[SyntheticLedgerRecord] = []
    for index in range(count):
        records.append(
            SyntheticLedgerRecord(
                record_index=index,
                block_number=10_000 + index,
                finality=finalities[index % len(finalities)],
                amount_units=(index * 17) % 1_000_000,
            )
        )
    return tuple(records)


def paginate_records(
    records: tuple[SyntheticLedgerRecord, ...],
    *,
    page_size: int = FIXTURE_PAGE_SIZE,
) -> list[tuple[SyntheticLedgerRecord, ...]]:
    """Split records into fixed pages matching streaming ingest behaviour."""

    if page_size < 1:
        raise ValueError("page_size must be a positive integer")
    pages: list[tuple[SyntheticLedgerRecord, ...]] = []
    for start in range(0, len(records), page_size):
        pages.append(records[start : start + page_size])
    return pages
