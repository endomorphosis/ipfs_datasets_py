"""CIDv1 DAG-JSON helpers shared by Profile D policy artifacts.

The returned identifiers are normal IPFS CIDs: CIDv1, `dag-json` codec, and
`sha2-256` multihash.  Both Helia and Kubo can persist the exact canonical JSON
bytes as an IPLD block under these identifiers.
"""

from __future__ import annotations

import json
from typing import Any

from multiformats import CID, multihash


def canonical_dag_json(value: Any) -> bytes:
    """Encode a value with the Profile D canonical DAG-JSON byte contract."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def dag_json_cid(value: Any) -> str:
    """Return CIDv1 `dag-json`/`sha2-256` for canonical JSON content."""
    digest = multihash.digest(canonical_dag_json(value), "sha2-256")
    return str(CID("base32", 1, "dag-json", digest))


__all__ = ["canonical_dag_json", "dag_json_cid"]
