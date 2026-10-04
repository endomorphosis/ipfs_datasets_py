"""Script descriptors, amounts, and network genesis binding."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.wallets.bitcoin import (
    BitcoinNetwork,
    MAINNET_GENESIS,
    TESTNET_GENESIS,
    chain_ref_for,
    classify_script_hex,
    describe_address,
    exact_sats,
    network_profile,
    parse_sats,
)
from ipfs_datasets_py.processors.wallets.bitcoin.networks import assert_chain_matches
from ipfs_datasets_py.processors.wallets.errors import (
    InvalidRequestError,
    NormalizationError,
)
from ipfs_datasets_py.processors.wallets.models import ChainRef


def test_mainnet_genesis_binding() -> None:
    chain = chain_ref_for(BitcoinNetwork.MAINNET)
    assert chain.namespace == "bip122"
    assert chain.genesis_hash == MAINNET_GENESIS
    assert chain.chain_id == MAINNET_GENESIS[:32]
    assert chain.network == "bitcoin-mainnet"


def test_testnet_differs_from_mainnet() -> None:
    main = chain_ref_for(BitcoinNetwork.MAINNET)
    test = chain_ref_for(BitcoinNetwork.TESTNET)
    assert main.chain_ref_id != test.chain_ref_id
    assert test.genesis_hash == TESTNET_GENESIS


def test_assert_chain_matches_rejects_foreign_genesis() -> None:
    foreign = ChainRef(
        namespace="bip122",
        network="bitcoin-mainnet",
        chain_id=TESTNET_GENESIS[:32],
        genesis_hash=TESTNET_GENESIS,
    )
    with pytest.raises(NormalizationError, match="does not match"):
        assert_chain_matches(foreign, BitcoinNetwork.MAINNET)


def test_script_vectors_from_fixture(load_fixture) -> None:
    data = load_fixture("scripts_legacy_segwit_taproot.json")
    for vector in data["vectors"]:
        if "address" in vector:
            descriptor = describe_address(
                vector["address"], network=BitcoinNetwork.MAINNET
            )
            assert descriptor.script_type.value == vector["expect_script_type"]
            assert descriptor.encoding.value == vector["expect_encoding"]
            assert descriptor.is_legacy is vector["expect_legacy"]
            assert descriptor.is_segwit is vector["expect_segwit"]
            assert descriptor.is_taproot is vector["expect_taproot"]
            if "expect_witness_version" in vector:
                assert descriptor.witness_version == vector["expect_witness_version"]
        if "script_hex" in vector and "address" not in vector:
            assert (
                classify_script_hex(vector["script_hex"]).value
                == vector["expect_script_type"]
            )


def test_network_mismatch_vectors(load_fixture) -> None:
    data = load_fixture("network_mismatch.json")
    for case in data["cases"]:
        if case["id"] == "chain-ref-genesis-binding":
            main = chain_ref_for(case["configured_network"])
            assert main.genesis_hash != case["foreign_genesis"]
            continue
        network = BitcoinNetwork(case["configured_network"])
        if case["expect_error"]:
            with pytest.raises(NormalizationError, match=case["error_substring"]):
                describe_address(case["address"], network=network)
        else:
            descriptor = describe_address(case["address"], network=network)
            assert descriptor.script_type.value == case["expect_script_type"]


def test_exact_sats_reject_float() -> None:
    with pytest.raises(InvalidRequestError, match="binary float"):
        parse_sats(1.5)
    amount = exact_sats(100_000_000)
    assert amount.base_units == "100000000"
    assert amount.decimals == 8


def test_network_profile_hrp() -> None:
    assert network_profile(BitcoinNetwork.MAINNET).hrp == "bc"
    assert network_profile(BitcoinNetwork.TESTNET).hrp == "tb"
