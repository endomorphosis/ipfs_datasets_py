from __future__ import annotations

from copy import deepcopy

import pytest

from ipfs_datasets_py.processors.wallets.errors import NormalizationError
from ipfs_datasets_py.processors.wallets.solana import (
    SOLANA_MAINNET,
    normalize_pubkey,
    normalize_signature,
    parse_non_negative_int,
    resolve_message_account_keys,
)


def test_network_identity_and_base58_shapes_are_exact(rpc_session: dict) -> None:
    chain = SOLANA_MAINNET.to_chain_ref()
    assert chain.namespace == "solana"
    assert chain.network == "solana-mainnet-beta"
    assert chain.genesis_hash == rpc_session["network"]["genesis_hash"]
    assert normalize_pubkey(rpc_session["addresses"]["alice"]) == rpc_session["addresses"]["alice"]
    assert normalize_signature(rpc_session["signatures"]["versioned"]) == rpc_session["signatures"]["versioned"]
    with pytest.raises(NormalizationError, match="32 bytes"):
        normalize_pubkey("111")
    with pytest.raises(NormalizationError, match="non-base58"):
        normalize_pubkey("0" * 32)


def test_exact_integer_parser_rejects_float_bool_sign_and_exponent() -> None:
    assert parse_non_negative_int("900719925474099312345", field_name="amount") == 900719925474099312345
    for value in (1.0, True, "-1", "1e9", ""):
        with pytest.raises(NormalizationError):
            parse_non_negative_int(value, field_name="amount")


def test_versioned_lookup_resolution_is_deterministic(rpc_session: dict) -> None:
    native = rpc_session["transactions"][rpc_session["signatures"]["versioned"]]
    message = native["transaction"]["message"]
    keys, tables = resolve_message_account_keys(message, native["meta"])
    assert keys[:2] == (
        rpc_session["addresses"]["alice"],
        rpc_session["addresses"]["bob"],
    )
    assert keys[-2:] == (
        rpc_session["addresses"]["source_token_account"],
        rpc_session["addresses"]["destination_token_account"],
    )
    assert tables[0].account_key == rpc_session["addresses"]["lookup_table"]
    assert tables[0].writable_indexes == (1, 2)
    assert resolve_message_account_keys(message, native["meta"]) == (keys, tables)


def test_partial_lookup_resolution_fails_closed(rpc_session: dict) -> None:
    native = rpc_session["transactions"][rpc_session["signatures"]["versioned"]]
    message = deepcopy(native["transaction"]["message"])
    meta = deepcopy(native["meta"])
    meta["loadedAddresses"]["writable"].pop()
    with pytest.raises(NormalizationError, match="unresolved"):
        resolve_message_account_keys(message, meta)
