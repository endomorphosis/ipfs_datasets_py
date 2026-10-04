"""Optional-dependency behavior tests for `ipfs_datasets_py.logic.zkp`.

These tests are intentionally lightweight and avoid importing optional heavy
stacks unless explicitly requested.
"""

from __future__ import annotations

import importlib.util
import json
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
    result = _run_python(
        "\n".join(
            [
                "import os",
                "import sys",
                "import json",
                "os.environ.pop('IPFS_DATASETS_PY_WARN_OPTIONAL_IMPORTS', None)",
                "import ipfs_datasets_py.logic.zkp",
                "def _has_prefix(prefix: str) -> bool:",
                "    return any(name == prefix or name.startswith(prefix + '.') for name in sys.modules)",
                "print(json.dumps({'web3': _has_prefix('web3'), 'jsonschema': _has_prefix('jsonschema')}))",
            ]
        )
    )

    assert result.returncode == 0, result.stderr

    data = json.loads(result.stdout.strip() or "{}")
    assert data.get("web3") is False
    assert data.get("jsonschema") is False


def test_eth_integration_imports_without_web3_but_client_requires_web3():
    if importlib.util.find_spec("web3") is not None:
        pytest.skip("web3 is installed; cannot validate web3-missing behavior")

    result = _run_python("import ipfs_datasets_py.logic.zkp.eth_integration")
    assert result.returncode == 0, result.stderr

    # Import should be safe, but instantiating the on-chain client should error.
    result = _run_python(
        "from ipfs_datasets_py.logic.zkp.eth_integration import EthereumConfig, EthereumProofClient\n"
        "cfg = EthereumConfig(\n"
        "    rpc_url='http://localhost:8545',\n"
        "    network_id=31337,\n"
        "    network_name='local',\n"
        "    verifier_contract_address='0x' + 'a'*40,\n"
        "    registry_contract_address='0x' + 'b'*40,\n"
        " )\n"
        "EthereumProofClient(cfg)\n"
    )
    assert result.returncode != 0

    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    assert "web3" in combined.lower()
