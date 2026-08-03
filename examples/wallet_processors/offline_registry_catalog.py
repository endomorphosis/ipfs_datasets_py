#!/usr/bin/env python3
"""List wallet processor families, extras, and composition metadata (offline).

Demonstrates the lazy registry without opening network sockets or loading
optional chain SDKs beyond static family specs.

Usage:
    python offline_registry_catalog.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running as a script from any cwd.
_EXAMPLES_DIR = Path(__file__).resolve().parent
if str(_EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES_DIR))

from _common import refuse_network_unless_opted_in  # noqa: E402


def main() -> int:
    refuse_network_unless_opted_in()

    from ipfs_datasets_py.processors.wallets import default_registry

    reg = default_registry()
    rows = []
    for family in reg.list_families():
        spec = reg.get_spec(family)
        caps = reg.capabilities_for(family)
        rows.append(
            {
                "family": spec.family,
                "extra": spec.extra,
                "aliases": sorted(spec.aliases),
                "chain_namespaces": sorted(spec.chain_namespaces),
                "default_network": spec.default_network,
                "composes": sorted(spec.composes),
                "features": sorted(f.value for f in caps.features),
                "description": spec.description,
                "supports_sign": bool(spec.metadata.get("supports_sign", False)),
                "supports_broadcast": bool(
                    spec.metadata.get("supports_broadcast", False)
                    or spec.metadata.get("supports_submit", False)
                ),
                "world_id": bool(spec.metadata.get("world_id", False)),
                "world_chain": bool(spec.metadata.get("world_chain", False))
                or family == "world-chain",
                "composed_xrpl": bool(spec.metadata.get("composed_xrpl", False)),
            }
        )

    # Explicit identity callouts required by WALPROC-G700 acceptance.
    distinctions = {
        "World ID": "Protocol family 'worldcoin' — IDKit / proofs / bindings; not a ledger scanner.",
        "World Chain": "Ledger family 'world-chain' — eip155 chain ids 480/4801; composes ethereum.",
        "WLD": "ERC-20 asset on World Chain mainnet (chain id 480); not a protocol or chain.",
        "XRPL": "Ledger family 'xrpl' — classic accounts and ledger ranges.",
        "Xaman": "Payload family 'xaman' — composed over XRPL settlement; no approve/sign/submit.",
    }

    payload = {
        "offline": True,
        "network_opt_in_required": [
            "WALLET_PROCESSORS_ALLOW_NETWORK=1",
            "--allow-network",
        ],
        "identity_distinctions": distinctions,
        "families": rows,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
