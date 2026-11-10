"""Harvested/helpers copies of the collector helpers load the one canonical module."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import ipfs_datasets_py.processors.legal_scrapers as legal_scrapers
from ipfs_datasets_py.processors.legal_scrapers.international.runtime import _prepare_env

PKG = Path(legal_scrapers.__file__).resolve().parent
SHARED = PKG / "international" / "harvested" / "shared"
HELPERS = ["common", "world_lib", "archive_fallbacks", "pdf_extract_lib"]

_CHILD = r"""
import json, os, sys
shared, guard = sys.argv[1], sys.argv[2]
if guard:
    os.environ["IPFS_DATASETS_LEGAL_ROBOTS_GUARD"] = guard
else:
    os.environ.pop("IPFS_DATASETS_LEGAL_ROBOTS_GUARD", None)
sys.path.insert(0, shared)
before = list(sys.path)
mods = {name: __import__(name) for name in ("common", "world_lib", "archive_fallbacks", "pdf_extract_lib")}
import robots_guard
calls = []
robots_guard.check = lambda url: calls.append(url) or (_ for _ in ()).throw(RuntimeError("checked"))
blocked = []
for name in ("common", "archive_fallbacks"):
    try:
        blocked.append(mods[name]._robots_blocked("https://example.invalid/law", "test"))
    except RuntimeError:
        blocked.append("checked")
print(json.dumps({
    "files": {name: mod.__file__ for name, mod in mods.items()},
    "path_unchanged": sys.path == before,
    "blocked": blocked,
    "calls": len(calls),
    "same_common": mods["world_lib"].live_get.__globals__["_robots_get"].__globals__["_RobotsSession"] is mods["common"]._RobotsSession,
}))
"""


def _run(guard: str) -> dict:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD, str(SHARED), guard],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_shims_are_not_forks() -> None:
    for folder in (SHARED, PKG / "international" / "helpers"):
        for name in HELPERS:
            text = (folder / f"{name}.py").read_text(encoding="utf-8")
            assert "national_collectors" in text and "exec(compile(" in text, folder / name
            assert len(text.splitlines()) < 80, folder / name
            assert (PKG / "national_collectors" / f"{name}.py").is_file()


def test_harvested_imports_resolve_to_canonical_and_guard_switch_off() -> None:
    result = _run("0")
    for name, path in result["files"].items():
        assert Path(path).resolve() == (PKG / "national_collectors" / f"{name}.py").resolve()
    assert result["path_unchanged"] is True
    assert result["blocked"] == [None, None]
    assert result["calls"] == 0
    assert result["same_common"] is True


def test_guard_defaults_on_outside_harvested_runtime() -> None:
    result = _run("")
    assert result["blocked"] == ["checked", "checked"]
    assert result["calls"] == 2


def test_harvested_runtime_defaults_guard_off_but_respects_opt_in(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("IPFS_DATASETS_LEGAL_ROBOTS_GUARD", raising=False)
    assert _prepare_env(tmp_path, tmp_path)["IPFS_DATASETS_LEGAL_ROBOTS_GUARD"] == "0"
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_ROBOTS_GUARD", "1")
    assert _prepare_env(tmp_path, tmp_path)["IPFS_DATASETS_LEGAL_ROBOTS_GUARD"] == "1"
