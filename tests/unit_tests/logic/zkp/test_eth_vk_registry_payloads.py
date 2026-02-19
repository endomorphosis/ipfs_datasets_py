from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.zkp.eth_vk_registry_payloads import (
    build_register_vk_payload,
    normalize_bytes32_hex,
    vk_hash_hex_to_bytes32,
)


def test_normalize_bytes32_hex_accepts_prefixed_and_unprefixed():
    v1 = normalize_bytes32_hex("0x" + "A" * 64)
    v2 = normalize_bytes32_hex("a" * 64)
    assert v1 == "0x" + "a" * 64
    assert v2 == "0x" + "a" * 64


def test_normalize_bytes32_hex_rejects_wrong_length():
    with pytest.raises(ValueError):
        normalize_bytes32_hex("0x" + "a" * 63)


def test_vk_hash_hex_to_bytes32_is_normalized():
    assert vk_hash_hex_to_bytes32("B" * 64) == "0x" + "b" * 64


def test_build_register_vk_payload_validates_uint64_and_hex():
    payload = build_register_vk_payload(
        circuit_id_bytes32="0x" + "1" * 64,
        version=1,
        vk_hash_hex="2" * 64,
    )
    assert payload.circuit_id_bytes32 == "0x" + "1" * 64
    assert payload.version == 1
    assert payload.vk_hash_bytes32 == "0x" + "2" * 64

    with pytest.raises(ValueError):
        build_register_vk_payload(
            circuit_id_bytes32="0x" + "1" * 64,
            version=-1,
            vk_hash_hex="2" * 64,
        )
