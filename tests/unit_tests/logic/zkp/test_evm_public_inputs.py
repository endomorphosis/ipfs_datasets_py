from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.zkp.evm_public_inputs import (
    BN254_FR_MODULUS,
    hash_text_to_field_sha256,
    pack_public_inputs_for_evm,
)


def _as_int(hex_str: str) -> int:
    s = hex_str.lower().strip()
    if s.startswith("0x"):
        s = s[2:]
    return int(s, 16)


def test_hash_text_to_field_sha256_is_32_bytes_and_in_field():
    h = hash_text_to_field_sha256("TDFOL_v1")
    assert h.startswith("0x")
    assert len(h) == 66
    assert 0 <= _as_int(h) < BN254_FR_MODULUS


def test_pack_public_inputs_for_evm_produces_4_scalars():
    out = pack_public_inputs_for_evm(
        theorem_hash_hex="4ae81572f06e1b88fd5ced7a1a000945432e83e1551e6f721ee9c00b8cc33260",
        axioms_commitment_hex="03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5",
        circuit_version=1,
        ruleset_id="TDFOL_v1",
    )
    assert len(out) == 4
    assert all(isinstance(x, str) and x.startswith("0x") and len(x) == 66 for x in out)
    assert all(0 <= _as_int(x) < BN254_FR_MODULUS for x in out)


def test_pack_public_inputs_for_evm_rejects_version_out_of_range():
    with pytest.raises(ValueError):
        pack_public_inputs_for_evm(
            theorem_hash_hex="4ae81572f06e1b88fd5ced7a1a000945432e83e1551e6f721ee9c00b8cc33260",
            axioms_commitment_hex="03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5",
            circuit_version=BN254_FR_MODULUS,
            ruleset_id="TDFOL_v1",
        )


def test_pack_public_inputs_for_evm_rejects_bad_hash_hex():
    with pytest.raises(ValueError):
        pack_public_inputs_for_evm(
            theorem_hash_hex="0x1234",
            axioms_commitment_hex="03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5",
            circuit_version=1,
            ruleset_id="TDFOL_v1",
        )
