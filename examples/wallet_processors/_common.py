"""Shared helpers for offline wallet processor examples."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Sequence

# Prefer the vendored package checkout over any stale editable install that may
# point at a different tree (see monorepo root conftest.py for the same pattern).
_EXAMPLES_DIR = Path(__file__).resolve().parent
# .../ipfs_datasets_py/examples/wallet_processors → package root is parents[1]?
# parents[0]=wallet_processors, parents[1]=examples, parents[2]=ipfs_datasets_py package root
_PACKAGE_ROOT = _EXAMPLES_DIR.parents[2]
_REPO_ROOT = _EXAMPLES_DIR.parents[3]  # monorepo / worktree root when nested
for _candidate in (_REPO_ROOT, _PACKAGE_ROOT, _EXAMPLES_DIR):
    _candidate_str = str(_candidate)
    if _candidate.exists():
        if _candidate_str in sys.path:
            sys.path.remove(_candidate_str)
        sys.path.insert(0, _candidate_str)

# Explicit dual-gate for any future live path. Examples remain offline unless
# BOTH the environment variable and CLI flag are present.
NETWORK_ENV = "WALLET_PROCESSORS_ALLOW_NETWORK"


def network_opt_in_enabled(argv: Sequence[str] | None = None) -> bool:
    """Return True only when env and --allow-network are both set."""

    args = list(sys.argv[1:] if argv is None else argv)
    env_ok = os.environ.get(NETWORK_ENV, "").strip() == "1"
    flag_ok = "--allow-network" in args
    return env_ok and flag_ok


def refuse_network_unless_opted_in(argv: Sequence[str] | None = None) -> None:
    """Exit if the caller requested network without full opt-in; else no-op.

    Documented examples never perform network I/O. This helper makes the
    opt-in contract executable and testable.
    """

    args = list(sys.argv[1:] if argv is None else argv)
    wants_network = "--allow-network" in args or os.environ.get(NETWORK_ENV, "").strip() == "1"
    if not wants_network:
        return
    if network_opt_in_enabled(args):
        print(
            "Network opt-in detected, but this example has no live provider "
            "path and will continue offline.",
            file=sys.stderr,
        )
        return
    print(
        "Refusing partial network opt-in. Live access requires BOTH "
        f"{NETWORK_ENV}=1 and --allow-network. Continuing is not allowed "
        "when only one gate is set.",
        file=sys.stderr,
    )
    raise SystemExit(2)


# Synthetic fixture material only — not production keys or live addresses.
SYNTHETIC_EVM_ADDRESS_A = "0x1111111111111111111111111111111111111111"
SYNTHETIC_EVM_ADDRESS_B = "0x2222222222222222222222222222222222222222"
SYNTHETIC_TX_HASH = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SYNTHETIC_BLOCK_HASH = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
ETHEREUM_MAINNET_GENESIS = (
    "0xd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3"
)

FORBIDDEN_EXAMPLE_VERBS = frozenset(
    {
        "sign",
        "broadcast",
        "submit",
        "approve",
        "send",
        "transfer",
        "sign_transaction",
        "broadcast_transaction",
    }
)
