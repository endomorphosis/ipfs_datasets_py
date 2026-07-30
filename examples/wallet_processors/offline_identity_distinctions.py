#!/usr/bin/env python3
"""Print World ID / World Chain / WLD and Xaman / XRPL distinctions (offline).

This example exists so documentation claims are executable and regression-tested.
It performs no network I/O and does not load signing material.

Usage:
    python offline_identity_distinctions.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_EXAMPLES_DIR = Path(__file__).resolve().parent
if str(_EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES_DIR))

from _common import refuse_network_unless_opted_in  # noqa: E402


def main() -> int:
    refuse_network_unless_opted_in()

    from ipfs_datasets_py.processors.wallets import default_registry

    reg = default_registry()

    worldcoin = reg.get_spec("worldcoin")
    world_chain = reg.get_spec("world-chain")
    xrpl = reg.get_spec("xrpl")
    xaman = reg.get_spec("xaman")

    # WLD is an asset catalog entry, not a registry family.
    wld = {
        "kind": "asset",
        "symbol": "WLD",
        "bound_chain_id": "480",
        "module": "ipfs_datasets_py.processors.wallets.worldcoin.assets",
        "note": (
            "WLD is the World Chain mainnet ERC-20 asset identity; it is not "
            "World ID and not World Chain itself."
        ),
    }

    payload = {
        "offline": True,
        "World ID": {
            "registry_family": worldcoin.family,
            "extra": worldcoin.extra,
            "aliases": sorted(worldcoin.aliases),
            "is_ledger_scanner": False,
            "description": worldcoin.description,
            "metadata": dict(worldcoin.metadata),
        },
        "World Chain": {
            "registry_family": world_chain.family,
            "extra": world_chain.extra,
            "aliases": sorted(world_chain.aliases),
            "networks": sorted(world_chain.networks),
            "composes": sorted(world_chain.composes),
            "description": world_chain.description,
            "metadata": dict(world_chain.metadata),
        },
        "WLD": wld,
        "XRPL": {
            "registry_family": xrpl.family,
            "extra": xrpl.extra,
            "aliases": sorted(xrpl.aliases),
            "xaman_payloads": bool(xrpl.metadata.get("xaman_payloads", False)),
            "description": xrpl.description,
        },
        "Xaman": {
            "registry_family": xaman.family,
            "extra": xaman.extra,
            "aliases": sorted(xaman.aliases),
            "composes": sorted(xaman.composes),
            "supports_sign": bool(xaman.metadata.get("supports_sign", False)),
            "supports_submit": bool(xaman.metadata.get("supports_submit", False)),
            "supports_approve": bool(xaman.metadata.get("supports_approve", False)),
            "description": xaman.description,
            "metadata": dict(xaman.metadata),
        },
        "schema_migration_window": "ledger and export manifests are major v1; dual-read on future v2 lasts at least one package minor",
        "import_migration_window": "one compatibility release of wrapper aliases after cutover; then target package imports only",
        "rollback": {
            "target_package_version": "restore ipfs_datasets_py pin/commit",
            "outer_gitlink_wrapper": "restore gitlink/submodule pointer and wallet_interface.world_id thin wrapper",
        },
    }
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
