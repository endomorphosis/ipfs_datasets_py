"""Inert child-environment control; no child, database or product is imported."""
import os
from pathlib import Path
import types


def test_explicit_user_site_follows_owned_sources_without_inherited_pythonpath_or_pth(tmp_path, monkeypatch):
    path = Path(__file__).with_name("registration_launcher.py")
    raw = path.read_bytes()
    module = types.ModuleType("_registration_launcher_inert_environment_control")
    module.__file__ = str(path)
    exec(compile(raw, str(path), "exec"), module.__dict__)
    user_site = tmp_path / "explicit-user-site"
    user_site.mkdir()
    marker = tmp_path / "pth-executed"
    (user_site / "authored.pth").write_text("import pathlib; pathlib.Path(" + repr(str(marker)) + ").touch()\n")
    monkeypatch.setattr(module.site, "getusersitepackages", lambda: str(user_site))
    def forbidden(*args, **kwargs):
        raise AssertionError("environment construction must execute no .pth, child or database import")
    monkeypatch.setattr(module.site, "addsitedir", forbidden)
    monkeypatch.setattr(module.subprocess, "Popen", forbidden)
    root = str(path.parents[4])
    cwd = str(tmp_path / "authored-second-source")
    inherited = {"PYTHONPATH": "/authored-unselected-search-path", "PYTHONNOUSERSITE": "0",
        "IPFS_DATASETS_AUTO_INSTALL": "1", "TRANSFORMERS_OFFLINE": "0", "OMP_NUM_THREADS": "99",
        "OPENBLAS_NUM_THREADS": "99", "PATH": "/authored-preserved-system-search"}
    result = module.registration_environment(cwd, inherited)
    assert result["PYTHONPATH"].split(os.pathsep) == [root, cwd, str(user_site)]
    assert result["PYTHONNOUSERSITE"] == result["PYTHONDONTWRITEBYTECODE"] == "1"
    assert result["IPFS_DATASETS_PY_MINIMAL_IMPORTS"] == "1"
    assert result["IPFS_DATASETS_AUTO_INSTALL"] == "0" and result["IPFS_AUTO_INSTALL"] == "false"
    assert all(result[key] == "1" for key in ("HF_HUB_OFFLINE", "HF_DATASETS_OFFLINE", "TRANSFORMERS_OFFLINE"))
    assert all(result[key] == "1" for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "RAYON_NUM_THREADS"))
    assert result["TOKENIZERS_PARALLELISM"] == "false"
    assert result["PATH"] == inherited["PATH"] and inherited["PYTHONNOUSERSITE"] == "0"
    assert not marker.exists()
