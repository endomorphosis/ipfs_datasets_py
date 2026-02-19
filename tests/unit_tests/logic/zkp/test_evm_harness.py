from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.zkp.evm_harness import pack_public_inputs_uint256, validate_uint256_array
from ipfs_datasets_py.logic.zkp.evm_public_inputs import BN254_FR_MODULUS


def test_pack_public_inputs_uint256_returns_4_field_elements():
    arr = pack_public_inputs_uint256(
        theorem_hash_hex="4ae81572f06e1b88fd5ced7a1a000945432e83e1551e6f721ee9c00b8cc33260",
        axioms_commitment_hex="03b7344d37c0fbdabde7b6e412b8dbe08417d3267771fac23ab584b63ea50cd5",
        circuit_version=1,
        ruleset_id="TDFOL_v1",
    )
    assert isinstance(arr, list)
    assert len(arr) == 4
    assert all(isinstance(x, int) for x in arr)
    assert all(0 <= x < BN254_FR_MODULUS for x in arr)


def test_validate_uint256_array_enforces_length_and_range():
    validate_uint256_array([0, 1], expected_len=2)

    with pytest.raises(ValueError):
        validate_uint256_array([0], expected_len=2)

    with pytest.raises(ValueError):
        validate_uint256_array([-(1)], expected_len=1)

    with pytest.raises(ValueError):
        validate_uint256_array([1 << 256], expected_len=1)
