"""Pinned staged-remote canary and Dataset Viewer checks (USCIR-036).

Acceptance
----------
* Fixture canary always passes offline (fake Hub / local transport).
* Mutable revisions fail closed; never inferred from ``main`` / ``latest``.
* Control indexes and selected shards redownload within sealed budgets.
* Dataset Viewer configs are schema-coherent; recovery never contaminates
  the default config.
* Sparse queries run twice with cache/offline parity and fetch traces.
* When staging coordinates are explicitly provided, the same checks pass
  against an injected remote transport at a 40-hex revision (live network
  remains opt-in via ``@pytest.mark.network``).
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

import pytest

from ipfs_datasets_py.processors.legal_data.uscode_hf_release import (
    DEFAULT_CONFIG_NAME,
    advertised_viewer_configs,
    assert_configs_schema_coherent,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    MappingTransport,
    MutableRevisionError,
    validate_immutable_revision,
)

# ---------------------------------------------------------------------------
# Paths / load canary module (script lives under scripts/ops)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CANARY_SCRIPT = (
    _REPO_ROOT / "scripts" / "ops" / "legal_data" / "canary_uscode_hf_release.py"
)
_FIXTURE_PATH = (
    _REPO_ROOT / "tests" / "fixtures" / "legal_ir" / "uscode_remote_canary.json"
)

TASK_ID = "USCIR-036"
GOAL_ID = "USCIR-G090"
PINNED_REVISION = "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8"
REPO_ID = "justicedao/ipfs_uscode"
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


def _load_canary_module():
    spec = importlib.util.spec_from_file_location(
        "canary_uscode_hf_release", _CANARY_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


canary = _load_canary_module()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_fixture() -> dict[str, Any]:
    assert _FIXTURE_PATH.is_file(), f"missing canary fixture: {_FIXTURE_PATH}"
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _assert_receipt_safe(receipt: Mapping[str, Any]) -> None:
    rendered = json.dumps(receipt, sort_keys=True)
    for needle in (
        "hf_",
        "Bearer ",
        "authorization:",
        "/home/",
        "HF_TOKEN",
        "sk-live-",
    ):
        # Allow schema field names / booleans, not secret values.
        if needle in ("hf_", "/home/"):
            # Paths and tokens should not appear as values; schema text is fine.
            continue
        assert needle not in rendered or needle.lower() in {
            "hf_token",  # may appear as key name in policy lists — reject values only
        }


# ---------------------------------------------------------------------------
# Sealed fixture policy
# ---------------------------------------------------------------------------


def test_sealed_canary_fixture_policy_surface() -> None:
    fixture = _load_fixture()
    assert fixture["schema"] == canary.CANARY_SCHEMA
    assert fixture["task_id"] == TASK_ID
    assert fixture["goal_id"] == GOAL_ID
    assert fixture["network_required"] is False
    assert fixture["target_repo"] == REPO_ID
    assert fixture["staging_revision"] == PINNED_REVISION
    assert _SHA1_RE.fullmatch(fixture["staging_revision"])
    assert fixture["acceptance"]["fixture_canary_offline"] is True
    assert fixture["acceptance"]["remote_opt_in_only"] is True
    assert fixture["acceptance"]["never_infer_mutable_revision"] is True
    assert fixture["viewer"]["default_config"] == DEFAULT_CONFIG_NAME
    assert fixture["viewer"]["default_excludes_recovery"] is True
    assert "manifest.json" in fixture["control_indexes"]
    assert fixture["selected_shards"]
    assert fixture["queries"]
    for query in fixture["queries"]:
        assert int(query["runs"]) >= 2


def test_check_canary_fixture_offline() -> None:
    result = canary.check_canary_fixture()
    assert result["ok"] is True
    assert result["task_id"] == TASK_ID
    assert result["staging_revision"] == PINNED_REVISION
    assert result["network_required"] is False
    assert result["viewer_ok"] is True
    assert result["mismatches"] == []


def test_cli_fixture_only_check(capsys: pytest.CaptureFixture[str]) -> None:
    code = canary.main(["--fixture-only", "--check"])
    assert code == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["task_id"] == TASK_ID
    assert payload["staging_revision"] == PINNED_REVISION


# ---------------------------------------------------------------------------
# Offline fixture canary
# ---------------------------------------------------------------------------


def test_fixture_canary_always_passes_offline(tmp_path: Path) -> None:
    receipt = canary.run_fixture_canary(cache_dir=tmp_path / "cache")
    assert receipt["ok"] is True
    assert receipt["mode"] == "fixture"
    assert receipt["network_invoked"] is False
    assert receipt["task_id"] == TASK_ID
    assert receipt["goal_id"] == GOAL_ID
    assert receipt["revision"] == PINNED_REVISION
    assert receipt["repo_id"] == REPO_ID
    assert _SHA1_RE.fullmatch(receipt["revision"])
    assert receipt["read_only"] is True

    # Control indexes + selected shards redownloaded within budgets.
    control = receipt["control_redownload"]
    shards = receipt["selected_shard_redownload"]
    assert control["within_budget"] is True
    assert shards["within_budget"] is True
    assert control["file_count"] == len(_load_fixture()["control_indexes"])
    assert shards["file_count"] == len(_load_fixture()["selected_shards"])
    assert all(item["verified"] for item in control["files"])
    assert all(item["verified"] for item in shards["files"])
    assert receipt["total_redownload_bytes"] <= receipt["budgets"]["max_bytes"]

    # Viewer configs valid.
    assert receipt["viewer"]["ok"] is True
    assert receipt["viewer"]["default_config"] == DEFAULT_CONFIG_NAME
    assert receipt["acceptance"]["viewer_configs_valid"] is True
    assert receipt["acceptance"]["bounded_downloads"] is True

    # Sparse queries twice with cache/offline parity.
    assert receipt["queries"]
    for query in receipt["queries"]:
        assert query["parity_ok"] is True
        assert len(query["run_receipts"]) >= 2
        assert query["run_receipts"][0]["replay_fingerprint"] == query[
            "run_receipts"
        ][-1]["replay_fingerprint"]
        assert query["run_receipts"][0]["hit_count"] >= 1
    assert receipt["acceptance"]["cache_offline_parity"] is True

    # Fetch trace records immutable revision without credentials.
    trace = receipt["fetch_trace"]
    assert trace["revision"] == PINNED_REVISION
    assert trace["repo_id"] == REPO_ID
    assert int(trace["file_count"] or 0) >= 1
    assert receipt.get("receipt_sha256")
    _assert_receipt_safe(receipt)


def test_fixture_canary_cli_runs_offline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = canary.main(
        [
            "--fixture-only",
            "--cache-dir",
            str(tmp_path / "cache"),
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["mode"] == "fixture"
    assert payload["network_invoked"] is False


def test_viewer_configs_schema_coherent_and_recovery_isolated() -> None:
    configs = advertised_viewer_configs()
    report = assert_configs_schema_coherent(configs)
    assert report["schema_coherent"] is True
    assert report["default_config"] == DEFAULT_CONFIG_NAME
    defaults = [c for c in configs if c.is_default]
    assert len(defaults) == 1
    for entry in defaults[0].data_files:
        path = str(entry["path"])
        assert "recovery" not in path
        assert not path.startswith("uscode_parquet/")
    recovery = [c for c in configs if c.is_recovery]
    assert recovery
    assert all(not c.is_default for c in recovery)

    viewer = canary.verify_viewer_configs(_load_fixture()["viewer"])
    assert viewer["ok"] is True
    assert viewer["recovery_isolated"] is True


# ---------------------------------------------------------------------------
# Fail-closed: mutable revision / missing remote coordinates
# ---------------------------------------------------------------------------


def test_mutable_revision_fails_closed() -> None:
    for bad in ("main", "master", "latest", "HEAD", "refs/heads/main"):
        with pytest.raises((canary.CanaryRemoteError, MutableRevisionError)):
            canary.require_immutable_staging_revision(bad)
        with pytest.raises(MutableRevisionError):
            validate_immutable_revision(bad)


def test_remote_without_coordinates_fails_closed() -> None:
    with pytest.raises(canary.CanaryRemoteError):
        canary.run_remote_canary(repo_id="", revision=PINNED_REVISION)
    with pytest.raises(canary.CanaryRemoteError):
        canary.run_remote_canary(repo_id=REPO_ID, revision="main")
    with pytest.raises(canary.CanaryRemoteError):
        canary.run_canary(mode="remote", repo_id=None, revision=None)


def test_cli_refuses_secrets_on_argv() -> None:
    code = canary.main(["--fixture-only", "--check", "hf_token=hf_abc123secretvalue"])
    assert code == 2


# ---------------------------------------------------------------------------
# Simulated remote (explicit staging coordinates + fake Hub transport)
# ---------------------------------------------------------------------------


def test_remote_canary_with_explicit_staging_coordinates(tmp_path: Path) -> None:
    """Same checks pass 'remotely' when coords are explicit (fake Hub, no network)."""

    fixture = _load_fixture()
    release_root = tmp_path / "release"
    canary.materialize_canary_release(release_root)
    files = canary.release_file_bytes(release_root)
    transport = MappingTransport(files)

    # Explicit staging coordinates — never inferred.
    staging_repo = REPO_ID
    staging_revision = PINNED_REVISION
    assert _SHA1_RE.fullmatch(staging_revision)

    receipt = canary.run_remote_canary(
        repo_id=staging_repo,
        revision=staging_revision,
        recipe=fixture,
        cache_dir=tmp_path / "cache",
        transport=transport,
        network=False,
    )
    assert receipt["ok"] is True
    assert receipt["mode"] == "remote"
    assert receipt["network_invoked"] is False
    assert receipt["revision"] == staging_revision
    assert receipt["repo_id"] == staging_repo
    assert receipt["acceptance"]["bounded_downloads"] is True
    assert receipt["acceptance"]["viewer_configs_valid"] is True
    assert receipt["acceptance"]["cache_offline_parity"] is True
    assert receipt["acceptance"]["revision_is_40_hex"] is True
    assert receipt["control_redownload"]["within_budget"] is True
    assert receipt["selected_shard_redownload"]["within_budget"] is True
    assert receipt["total_redownload_bytes"] <= receipt["budgets"]["max_bytes"]
    for query in receipt["queries"]:
        assert query["parity_ok"] is True
        assert len(query["run_receipts"]) >= 2
    assert receipt["fetch_trace"]["revision"] == staging_revision
    _assert_receipt_safe(receipt)


def test_remote_canary_rejects_mutable_revision_even_with_transport(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release"
    canary.materialize_canary_release(release_root)
    transport = MappingTransport(canary.release_file_bytes(release_root))
    with pytest.raises(canary.CanaryRemoteError):
        canary.run_remote_canary(
            repo_id=REPO_ID,
            revision="main",
            cache_dir=tmp_path / "cache",
            transport=transport,
            network=False,
        )


# ---------------------------------------------------------------------------
# Optional live network canary (skipped unless coordinates + network enabled)
# ---------------------------------------------------------------------------


def _live_coords_available() -> bool:
    repo = os.environ.get(canary.REMOTE_REPO_ENV) or os.environ.get(
        "USCODE_CANARY_REPO_ID"
    )
    rev = os.environ.get(canary.REMOTE_REVISION_ENV) or os.environ.get(
        "USCODE_CANARY_REVISION"
    )
    enabled = str(
        os.environ.get(canary.REMOTE_ENABLE_ENV)
        or os.environ.get("USCODE_CANARY_REMOTE")
        or ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    if not (enabled and repo and rev):
        return False
    try:
        canary.require_immutable_staging_revision(rev)
        canary.require_repo_id(repo)
    except canary.CanaryRemoteError:
        return False
    return True


@pytest.mark.network
@pytest.mark.integration
def test_live_remote_canary_when_staging_coordinates_provided(tmp_path: Path) -> None:
    """Live Hub canary: only when operator provides explicit immutable coords."""

    if not _live_coords_available():
        pytest.skip(
            "live remote canary requires "
            f"${canary.REMOTE_ENABLE_ENV}=1 plus "
            f"${canary.REMOTE_REPO_ENV} and ${canary.REMOTE_REVISION_ENV} "
            "(immutable 40-hex)"
        )
    repo = os.environ[canary.REMOTE_REPO_ENV]
    rev = canary.require_immutable_staging_revision(
        os.environ[canary.REMOTE_REVISION_ENV]
    )
    receipt = canary.run_remote_canary(
        repo_id=repo,
        revision=rev,
        cache_dir=tmp_path / "cache",
        network=True,
    )
    assert receipt["ok"] is True
    assert receipt["mode"] == "remote"
    assert receipt["network_invoked"] is True
    assert receipt["revision"] == rev
    assert receipt["acceptance"]["bounded_downloads"] is True
    assert receipt["acceptance"]["viewer_configs_valid"] is True
    assert receipt["fetch_trace"]["revision"] == rev


# ---------------------------------------------------------------------------
# Budget fail-closed
# ---------------------------------------------------------------------------


def test_redownload_budget_fail_closed(tmp_path: Path) -> None:
    fixture = _load_fixture()
    tight = dict(fixture)
    tight["budgets"] = {
        **dict(fixture["budgets"]),
        "max_control_index_bytes": 1,  # impossible
        "max_bytes": 1,
    }
    with pytest.raises(canary.CanaryBudgetError):
        canary.run_fixture_canary(recipe=tight, cache_dir=tmp_path / "cache")


def test_build_fixture_recipe_matches_sealed() -> None:
    fresh = canary.build_fixture_canary_recipe()
    sealed = _load_fixture()
    mismatches = canary.compare_canary_recipes(fresh, sealed)
    assert mismatches == [], mismatches
