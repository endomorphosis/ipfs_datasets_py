"""Data-free synthetic seal builders shared by source-safe gate tests.

This support module constructs in-memory CID-native schema records only.  It
does not open a fixture, corpus, manifest, workspace artifact, or sealed data.
"""

from __future__ import annotations

from pathlib import Path

from benchmarks.logic_pipeline.cases import (
    REPLACEMENT_HOLDOUT_PROTOCOL_KEYS,
    REPLACEMENT_HOLDOUT_SEAL_SCHEMA,
    ReplacementHoldoutSeal,
    replacement_holdout_ledger_authority_cid,
)
from benchmarks.logic_pipeline.content_addressing import (
    cid_for_bytes,
    cid_for_dag_json,
)


OPAQUE_SYNTHETIC_BLOCK = b"synthetic opaque replacement seal block v2"


def _protocol_cids() -> dict[str, str]:
    return {
        key: cid_for_dag_json(
            {"synthetic_protocol": key, "revision": 2}
        )
        for key in sorted(REPLACEMENT_HOLDOUT_PROTOCOL_KEYS)
    }


def _seal(
    *,
    opaque_block: bytes = OPAQUE_SYNTHETIC_BLOCK,
    protocol_cids: dict[str, str] | None = None,
    ledger_path: str | Path = (
        "/synthetic-independent-custody/replacement-access.jsonl"
    ),
) -> ReplacementHoldoutSeal:
    protocols = protocol_cids or _protocol_cids()
    sealed_manifest_cid = cid_for_bytes(opaque_block, codec="raw")
    payload = {
        "schema": REPLACEMENT_HOLDOUT_SEAL_SCHEMA,
        "sealed_manifest_cid": sealed_manifest_cid,
        "case_count": 6,
        "strata_counts": {"alpha": 2, "beta": 4},
        "protocol_cids": protocols,
        "access_ledger_authority_cid": (
            replacement_holdout_ledger_authority_cid(
                sealed_manifest_cid,
                ledger_path,
            )
        ),
    }
    return ReplacementHoldoutSeal(
        **payload,
        seal_contract_cid=cid_for_dag_json(payload),
    )
