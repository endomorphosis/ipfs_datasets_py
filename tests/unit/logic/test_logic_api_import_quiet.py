from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_logic_api_import_is_quiet_and_lightweight(monkeypatch):
    monkeypatch.delenv("IPFS_DATASETS_PY_WARN_OPTIONAL_IMPORTS", raising=False)

    import ipfs_datasets_py
    import ipfs_datasets_py.logic as parent_logic
    import ipfs_datasets_py.logic.api as parent_api

    parent_modules = {
        "ipfs_datasets_py": ipfs_datasets_py,
        "ipfs_datasets_py.logic": parent_logic,
        "ipfs_datasets_py.logic.api": parent_api,
    }
    script = textwrap.dedent(
        """
        import importlib
        import sys
        import warnings

        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            api = importlib.import_module("ipfs_datasets_py.logic.api")

        ipfs_warnings = [
            item
            for item in recorded
            if "ipfs_datasets_py" in (getattr(item, "filename", "") or "")
        ]
        assert ipfs_warnings == [], [str(item.message) for item in ipfs_warnings]
        expected_exports = {
            "FOLConverter",
            "DeonticConverter",
            "ConversionResult",
            "ConversionStatus",
            "ProofResult",
            "ProofStatus",
        }
        exported = set(getattr(api, "__all__", []))
        missing_from_all = sorted(expected_exports - exported)
        assert missing_from_all == [], missing_from_all
        assert "ipfs_datasets_py.logic.integration" not in sys.modules
        print("ok")
        """
    )
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (str(REPO_ROOT), env.get("PYTHONPATH", ""))
        if part
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "ok" in completed.stdout
    for name, module in parent_modules.items():
        assert sys.modules.get(name) is module
