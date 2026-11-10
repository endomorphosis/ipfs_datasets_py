"""Writable legal-scraper defaults must resolve outside the installed package."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_scrapers import user_data_paths
from ipfs_datasets_py.processors.legal_scrapers.user_data_paths import (
    is_inside_package,
    user_data_dir,
)


def test_user_data_dir_defaults_under_home_and_honors_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("RB_TEST_DIR", raising=False)
    assert user_data_dir("a", "b", env="RB_TEST_DIR") == (tmp_path / ".ipfs_datasets" / "a" / "b").resolve()
    monkeypatch.setenv("RB_TEST_DIR", str(tmp_path / "custom"))
    assert user_data_dir("a", env="RB_TEST_DIR") == (tmp_path / "custom").resolve()
    assert not is_inside_package(user_data_dir("a"))
    assert is_inside_package(user_data_paths.LEGAL_SCRAPERS_PACKAGE_DIR / "x.json")


def test_harvest_roots_are_outside_package(monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.international.helpers import paths

    monkeypatch.delenv(paths.CORPORA_ROOT_ENV, raising=False)
    monkeypatch.delenv(paths.COLLECTORS_ROOT_ENV, raising=False)
    assert not is_inside_package(paths.corpora_root())
    assert not is_inside_package(paths.collectors_root())
    assert paths.default_data_root() == user_data_paths.default_data_root()


def test_netherlands_generated_datasets_are_outside_package(tmp_path: Path, monkeypatch) -> None:
    import ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.paths as nl_paths

    monkeypatch.delenv(nl_paths.DATASETS_DIR_ENV, raising=False)
    nl_paths = importlib.reload(nl_paths)
    for path in (
        nl_paths.DATASETS_DIR,
        nl_paths.RAW_DATA_DIR,
        nl_paths.HF_DATA_DIR,
        nl_paths.PACKAGE_RAW_OUTPUT_DIR,
        nl_paths.DEFAULT_BWBR_CATALOG_PATH,
    ):
        assert not is_inside_package(path), path
    monkeypatch.setenv(nl_paths.DATASETS_DIR_ENV, str(tmp_path / "nl"))
    try:
        assert importlib.reload(nl_paths).DATASETS_DIR == (tmp_path / "nl").resolve()
    finally:
        monkeypatch.delenv(nl_paths.DATASETS_DIR_ENV, raising=False)
        importlib.reload(nl_paths)


def test_learned_patterns_save_outside_package_and_seed_from_packaged_copy(tmp_path: Path, monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir import normalize_loop, structure

    monkeypatch.delenv("COUNTRY_LAWS_LEARNED_PATTERNS", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    write_path = structure.learned_patterns_write_path()
    assert not is_inside_package(write_path)
    # Nothing saved yet: read the packaged seed rules.
    assert structure.learned_patterns_path() == structure.PACKAGED_LEARNED_PATTERNS_PATH
    seeded = normalize_loop.load_learned_patterns()
    normalize_loop.save_learned_patterns([*seeded, r"^Desk copy \d+$"])
    assert write_path.is_file()
    assert structure.learned_patterns_path() == write_path
    saved = json.loads(write_path.read_text(encoding="utf-8"))["patterns"]
    assert saved[: len(seeded)] == seeded
    assert normalize_loop.load_learned_patterns()[-1] == r"^Desk copy \d+$"
