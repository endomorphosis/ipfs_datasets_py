"""Optional-dependency behavior tests for `ipfs_datasets_py.logic.zkp`.

These tests are intentionally lightweight and avoid importing optional heavy
stacks unless explicitly requested.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    # .../ipfs_datasets_py/tests/unit_tests/logic/zkp/test_optional_dependencies.py
    return Path(__file__).resolve().parents[4]


def _run_python(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_repo_root()),
        capture_output=True,
        text=True,
    )


def test_core_zkp_import_succeeds_without_optional_deps():
    result = _run_python("import ipfs_datasets_py.logic.zkp")
    assert result.returncode == 0, result.stderr


def test_eth_integration_import_error_mentions_web3_if_missing():
    if importlib.util.find_spec("web3") is not None:
        pytest.skip("web3 is installed; eth_integration import should succeed")

    result = _run_python("import ipfs_datasets_py.logic.zkp.eth_integration")
    assert result.returncode != 0

    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    assert "web3" in combined.lower()
