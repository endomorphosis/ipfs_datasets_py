"""Unit tests for the high-level Groth16 backend entrypoint.

These tests validate that configuration/metadata options are forwarded correctly
into the Rust FFI wrapper without requiring the Rust binary to be present.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from ipfs_datasets_py.logic.zkp.backends.groth16 import Groth16Backend


def test_groth16_entrypoint_passes_seed_via_metadata(monkeypatch):
    """`metadata['seed']` should be forwarded as the FFI seed argument."""
    monkeypatch.setenv("IPFS_DATASETS_ENABLE_GROTH16", "1")

    backend = Groth16Backend(binary_path="/usr/bin/groth16")

    mock_ffi = MagicMock()
    mock_ffi.generate_proof.return_value = MagicMock()

    backend._ffi = MagicMock(return_value=mock_ffi)

    backend.generate_proof("Q", ["P", "P -> Q"], metadata={"seed": 42})

    args, kwargs = mock_ffi.generate_proof.call_args
    witness_json = args[0]
    witness = json.loads(witness_json)
    assert witness["theorem"] == "Q"

    assert kwargs.get("seed") == 42


def test_groth16_entrypoint_allows_seed_none(monkeypatch):
    """If seed is not provided, forwarding should remain stable."""
    monkeypatch.setenv("IPFS_DATASETS_ENABLE_GROTH16", "1")

    backend = Groth16Backend(binary_path="/usr/bin/groth16")

    mock_ffi = MagicMock()
    mock_ffi.generate_proof.return_value = MagicMock()

    backend._ffi = MagicMock(return_value=mock_ffi)

    backend.generate_proof("Q", ["P", "P -> Q"], metadata={})

    _args, kwargs = mock_ffi.generate_proof.call_args
    assert kwargs.get("seed") is None
