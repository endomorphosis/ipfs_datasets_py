"""Unit tests for the high-level Groth16 backend entrypoint.

These tests validate that configuration/metadata options are forwarded correctly
into the Rust FFI wrapper without requiring the Rust binary to be present.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from ipfs_datasets_py.logic.zkp import ZKPError
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


def test_groth16_entrypoint_setup_forwards_seed(monkeypatch):
    """setup(version, seed=...) should be forwarded to the FFI wrapper."""
    monkeypatch.setenv("IPFS_DATASETS_ENABLE_GROTH16", "1")

    backend = Groth16Backend(binary_path="/usr/bin/groth16")

    mock_ffi = MagicMock()
    mock_ffi.setup.return_value = {"schema_version": 1, "version": 1}
    backend._ffi = MagicMock(return_value=mock_ffi)

    out = backend.setup(1, seed=42)
    assert out["schema_version"] == 1

    mock_ffi.setup.assert_called_once()
    args, kwargs = mock_ffi.setup.call_args
    assert args[0] == 1
    assert kwargs.get("seed") == 42


def test_groth16_entrypoint_setup_requires_enable(monkeypatch):
    """setup should remain fail-closed when the groth16 backend isn't enabled."""
    monkeypatch.delenv("IPFS_DATASETS_ENABLE_GROTH16", raising=False)
    backend = Groth16Backend(binary_path="/usr/bin/groth16")

    with pytest.raises(ZKPError, match=r"Groth16 backend is disabled"):
        backend.setup(1)
