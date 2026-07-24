"""Foundation contract for the isolated logic-pipeline benchmark package."""

from __future__ import annotations

import builtins
import importlib
import json
from pathlib import Path
import sys

import pytest

import benchmarks.logic_pipeline as logic_pipeline


OPTIONAL_OR_PRODUCTION_ROOTS = {
    "hammer",
    "leanstral",
    "spacy",
    "symai",
    "symbolicai",
    "ipfs_datasets_py",
}


def test_package_import_does_not_load_optional_or_production_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The package remains importable in a minimal benchmark environment."""

    real_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object) -> object:
        if name.partition(".")[0] in OPTIONAL_OR_PRODUCTION_ROOTS:
            raise AssertionError(f"benchmark package imported forbidden component {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    reloaded = importlib.reload(logic_pipeline)

    assert (
        reloaded.HSSLEV0009A31()
        == "isolated benchmark package and execution skeleton"
    )
    assert set(reloaded.__all__) >= {
        "ExecutionDefaults",
        "RunPaths",
        "build_smoke_manifest",
        "manifest_sha256",
    }


def test_import_has_no_filesystem_or_routing_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    production_modules_before = {
        name for name in sys.modules if name.startswith("ipfs_datasets_py.")
    }

    importlib.reload(logic_pipeline)

    assert list(tmp_path.iterdir()) == []
    assert {
        name for name in sys.modules if name.startswith("ipfs_datasets_py.")
    } == production_modules_before


def test_all_mutable_defaults_are_scoped_below_the_run_root(tmp_path: Path) -> None:
    first = logic_pipeline.ExecutionDefaults(
        "smoke-001",
        benchmark_root=tmp_path / "benchmark",
    )
    second = logic_pipeline.ExecutionDefaults(
        "smoke-002",
        benchmark_root=tmp_path / "benchmark",
    )

    assert first.paths.run_root == tmp_path / "benchmark" / "smoke-001"
    assert set(first.paths.as_dict()) == {
        "run_root",
        *logic_pipeline.RUN_DIRECTORY_NAMES,
    }
    assert all(
        path == first.paths.run_root or path.is_relative_to(first.paths.run_root)
        for path in first.paths.directories()
    )
    assert set(first.paths.directories()).isdisjoint(second.paths.directories())
    assert first.cache_namespace != second.cache_namespace
    assert not first.paths.run_root.exists()


def test_materialization_only_creates_run_scoped_directories(tmp_path: Path) -> None:
    defaults = logic_pipeline.ExecutionDefaults(
        "materialize-001",
        benchmark_root=tmp_path / "benchmark",
    )

    defaults.paths.materialize()

    assert all(path.is_dir() for path in defaults.paths.directories())
    assert {path.name for path in defaults.paths.run_root.iterdir()} == set(
        logic_pipeline.RUN_DIRECTORY_NAMES
    )


@pytest.mark.parametrize(
    "run_id",
    ["", ".", "..", "../escape", "/absolute", "space id", "slash/id", "a" * 129],
)
def test_unsafe_run_ids_are_rejected(run_id: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="run_id"):
        logic_pipeline.RunPaths.for_run(run_id, benchmark_root=tmp_path)


def test_empty_benchmark_root_and_duplicate_variants_are_rejected() -> None:
    with pytest.raises(ValueError, match="benchmark_root"):
        logic_pipeline.ExecutionDefaults("smoke-001", benchmark_root="")

    with pytest.raises(ValueError, match="duplicate"):
        logic_pipeline.ExecutionDefaults("smoke-001", variants=("A0", "A0"))


def test_smoke_manifest_is_deterministic_and_canonical(tmp_path: Path) -> None:
    root = tmp_path / "benchmark"

    first = logic_pipeline.build_smoke_manifest("repeatable-001", benchmark_root=root)
    second = logic_pipeline.build_smoke_manifest("repeatable-001", benchmark_root=root)
    canonical = logic_pipeline.canonical_manifest_json(first)

    assert first == second
    assert logic_pipeline.manifest_sha256(first) == logic_pipeline.manifest_sha256(
        second
    )
    assert json.loads(canonical) == first
    assert canonical == json.dumps(
        first,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def test_default_smoke_manifest_has_a_frozen_content_digest() -> None:
    manifest = logic_pipeline.build_smoke_manifest("smoke-contract-v1")

    assert (
        logic_pipeline.manifest_sha256(manifest)
        == "33accd31da8ba1bfdeb1a395bf84e0ff1a2b0d8ec55d4a9fa4dbf3ad127a93a4"
    )


def test_smoke_defaults_are_offline_shadow_only_and_non_promoting() -> None:
    defaults = logic_pipeline.ExecutionDefaults("safe-defaults-001")
    manifest = defaults.smoke_manifest()

    assert defaults.variants == ("A0", "A1", "A7", "A8")
    assert defaults.shadow_only is True
    assert defaults.network_enabled is False
    assert defaults.model_calls_enabled is False
    assert defaults.auto_merge is False
    assert defaults.production_routing_changes is False
    assert manifest["mode"] == "shadow"
    assert manifest["execution"] == {
        "network_enabled": False,
        "model_calls_enabled": False,
        "auto_merge": False,
        "production_routing_changes": False,
    }
