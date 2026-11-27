"""harvested/shared keeps one implementation per collector: national_collectors.

Every harvested collector that has a national_collectors counterpart is a small
exec shim; the shim loads offline and yields the canonical module's names.
"""

from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path

import pytest

LEGAL = Path(__file__).resolve().parents[3] / "ipfs_datasets_py" / "processors" / "legal_scrapers"
SHARED = LEGAL / "international" / "harvested" / "shared"
NATIONAL = LEGAL / "national_collectors"
SHIM_MARKER = "_ipfs_shim_canonical_path"

# Harvested files that still carry their own implementation.  Keep this list
# empty or shrinking: a file leaves it once its behavior is merged into the
# national_collectors module of the same name.
STILL_DIVERGENT: set[str] = {
    "collect_al.py",
    "collect_am.py",
    "collect_ba.py",
    "collect_bg.py",
    "collect_bn.py",
    "collect_bo.py",
    "collect_bw.py",
    "collect_cf.py",
    "collect_cl.py",
    "collect_cm.py",
    "collect_co.py",
    "collect_cy.py",
    "collect_do.py",
    "collect_dz.py",
    "collect_ec.py",
    "collect_et.py",
    "collect_fj.py",
    "collect_ge.py",
    "collect_gh.py",
    "collect_is.py",
    "collect_it.py",
    "collect_jm.py",
    "collect_kuwaitalyawm.py",
    "collect_md.py",
    "collect_mm.py",
    "collect_na.py",
    "collect_pa.py",
    "collect_pg.py",
    "collect_py.py",
    "collect_si.py",
    "collect_sn.py",
    "collect_tn.py",
    "collect_tz.py",
    "collect_vg.py",
    "collect_xk.py",
    "collect_zw.py",
}

HARVESTED_ONLY = {path.name for path in SHARED.glob("*.py") if not (NATIONAL / path.name).is_file()}


def _shared_with_counterpart() -> list[Path]:
    return sorted(path for path in SHARED.glob("*.py") if (NATIONAL / path.name).is_file())


def test_every_counterpart_is_a_shim_or_listed() -> None:
    offenders = [
        path.name
        for path in _shared_with_counterpart()
        if SHIM_MARKER not in path.read_text(encoding="utf-8") and path.name not in STILL_DIVERGENT
    ]
    assert offenders == []


def test_listed_divergent_files_really_differ() -> None:
    for name in STILL_DIVERGENT:
        assert (SHARED / name).read_bytes() != (NATIONAL / name).read_bytes(), name


def test_harvested_only_files_are_not_shims() -> None:
    for name in HARVESTED_ONLY:
        assert SHIM_MARKER not in (SHARED / name).read_text(encoding="utf-8"), name


def _load(path: Path, monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    saved_path = list(sys.path)
    saved_modules = set(sys.modules)
    spec = importlib.util.spec_from_loader(f"ipfs_shim_probe_{path.stem}", loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(path)
    sys.path.insert(0, str(path.parent))
    try:
        exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    finally:
        sys.path[:] = saved_path
        for name in set(sys.modules) - saved_modules:
            origin = str(getattr(sys.modules.get(name), "__file__", "") or "")
            if "." not in name and (origin.startswith(str(SHARED)) or origin.startswith(str(NATIONAL))):
                sys.modules.pop(name, None)
    return module


@pytest.mark.parametrize("name", ["collect_af.py", "collect_ni.py", "collect_eurlex.py", "collector.py"])
def test_shim_exposes_canonical_module(name: str, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(tmp_path / "corpora"))
    shim = _load(SHARED / name, monkeypatch)
    canonical = _load(NATIONAL / name, monkeypatch)
    assert shim.__file__ == str((NATIONAL / name).resolve())
    public = lambda m: {k for k in vars(m) if not k.startswith("_")}
    assert public(shim) == public(canonical)
    assert callable(getattr(shim, "main", None))
