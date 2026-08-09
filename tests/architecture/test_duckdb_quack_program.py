from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import zipfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest


duckdb = pytest.importorskip("duckdb")

from scripts.ops import ipfs_datasets_duckdb_quack_program as program


def _bootstrap_probe(environment_root: Path) -> dict[str, object]:
    digest = "sha256:" + "a" * 64
    site_root = environment_root / "site-packages"
    return {
        "environment_root": str(environment_root),
        "python_executable": str((environment_root / "bin/python").absolute()),
        "sealed_python_launcher_path": str(
            environment_root / "bin/dqk-sealed-python"
        ),
        "sealed_python_launcher_sha256": digest,
        "python_version": "3.12.3",
        "python_implementation": "CPython",
        "python_cache_tag": "cpython-312",
        "base_prefix": "/usr",
        "base_python_executable": "/usr/bin/python3.12",
        "base_python_sha256": digest,
        "isolated_environment": True,
        "system_site_packages": False,
        "pyvenv_config_sha256": digest,
        "python_sys_path": [
            "/usr/lib/python312.zip",
            "/usr/lib/python3.12",
            "/usr/lib/python3.12/lib-dynload",
            str(site_root),
        ],
        "python_flags": {
            "dont_write_bytecode": True,
            "isolated": True,
            "no_site": True,
            "no_user_site": True,
            "safe_path": True,
        },
        "stdlib_root": "/usr/lib/python3.12",
        "stdlib_zip_path": "/usr/lib/python312.zip",
        "stdlib_zip_present": False,
        "stdlib_zip_sha256": "",
        "dynload_root": "/usr/lib/python3.12/lib-dynload",
        "stdlib_manifest_sha256": digest,
        "stdlib_manifest_file_count": 1213,
        "site_package_roots": [str(site_root)],
        "site_packages_manifest_sha256": digest,
        "site_packages_manifest_file_count": 58,
        "installed_distributions": [
            {"name": "duckdb", "version": "1.5.5", "root": str(site_root)}
        ],
        "platform": {
            "system": "Linux",
            "machine": "aarch64",
            "sysconfig_platform": "linux-aarch64",
            "libc": ["glibc", "2.39"],
        },
        "duckdb_distribution_name": "duckdb",
        "duckdb_distribution_version": "1.5.5",
        "duckdb_version": "1.5.5",
        "duckdb_module_path": str(environment_root / "site-packages/duckdb/__init__.py"),
        "duckdb_module_sha256": digest,
        "duckdb_native_module_path": str(
            environment_root / "site-packages/_duckdb.cpython-312-aarch64-linux-gnu.so"
        ),
        "duckdb_native_module_sha256": digest,
        "duckdb_distribution_root": str(environment_root / "site-packages"),
        "duckdb_record_path": str(
            environment_root / "site-packages/duckdb-1.5.5.dist-info/RECORD"
        ),
        "duckdb_record_sha256": digest,
        "duckdb_record_evidence_sha256": digest,
        "duckdb_record_verified_file_count": 55,
        "duckdb_record_unhashed_paths": ["duckdb-1.5.5.dist-info/RECORD"],
        "duckdb_wheel_path": str(
            environment_root / "site-packages/duckdb-1.5.5.dist-info/WHEEL"
        ),
        "duckdb_wheel_sha256": digest,
        "duckdb_wheel_tags": ["cp312-cp312-manylinux_2_28_aarch64"],
        "duckdb_installer": "pip",
        "duckdb_install_archive_path": str(
            environment_root
            / "bootstrap-artifacts/duckdb-1.5.5-cp312-cp312-manylinux_2_28_aarch64.whl"
        ),
        "duckdb_install_archive_sha256": (
            "sha256:f316eae2323d9a851883fdf2dee91c1f9efe251ab33e14a2272f82a913422ed6"
        ),
        "duckdb_wheel_member_evidence_sha256": digest,
        "duckdb_wheel_member_count": 56,
        "pip_install_report_path": str(
            environment_root / "bootstrap-artifacts/pip-install-report.json"
        ),
        "pip_install_report_sha256": digest,
        "pip_install_report_version": "1",
    }


@pytest.fixture()
def task_source(tmp_path: Path):
    DuckDBTaskSource, _providers = program._accelerate_imports()
    repository_tree = "tree:git:test-fixture"
    source = DuckDBTaskSource(tmp_path / "control.duckdb")
    source.materialize(
        program.formal_source(repository_tree),
        repository_tree_id=repository_tree,
        expected_absent=True,
    )
    return source


def test_program_is_acyclic_and_materializes_losslessly(task_source) -> None:
    program.validate_program()

    snapshot = task_source.snapshot()
    integrity = task_source.validate_integrity()
    recompiled = task_source.recompile_formal_plan()

    assert len(program.GOALS) == snapshot.goal_count == 16
    assert len(program.TASKS) == snapshot.task_count == 97
    assert snapshot.dependency_count == 326
    assert integrity.valid
    assert recompiled.status.value == "compiled"
    assert {item.task_id for item in task_source.ready_tasks(limit=1000).tasks} == {
        "DQK-001",
        "DQK-002",
        "DQK-007",
    }

    for task_id, reason in (
        (program.RELEASE_GATE_TASK_ID, "external_release_receipt_pending"),
        (program.REFINEMENT_GATE_TASK_ID, "inventory_refinement_approval_pending"),
        (program.PROMOTION_GATE_TASK_ID, "ducklake_promotion_approval_pending"),
        (
            program.RUNTIME_ACTIVATION_GATE_TASK_ID,
            "runtime_environment_activation_pending",
        ),
    ):
        task = task_source.get_task(task_id)
        assert task is not None
        assert task.status == "blocked"
        assert task.body["blocked_reason"] == reason
        assert task.body["is_schedulable"] is False


def test_bootstrap_bridge_contract_includes_merge_crash_evidence() -> None:
    bridge = next(task for task in program.TASKS if task["task_id"] == "DQK-007")
    outputs = set(bridge["scope_paths"])
    argv = program._bootstrap_bridge_validation_argv()

    assert program.REQUIRED_ACCELERATE_BRIDGE_COMMIT == (
        "0c6ad4efbabebd97e888502846ef5bb1cb7c7ae2"
    )
    assert "ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/merge_train.py" in outputs
    assert (
        "ipfs_accelerate_py/test/api/"
        "test_agent_supervisor_duckdb_merge_evidence_e2e.py"
    ) in outputs
    assert "test/api/test_agent_supervisor_duckdb_merge_evidence_e2e.py" in argv
    assert "test/api/test_agent_supervisor_duckdb_task_source.py" in argv


def test_retry_reset_inspection_binds_the_whole_runtime_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: list[Path] = []

    class ResetModule:
        @staticmethod
        def inspect_incomplete_retry_resets(path):
            observed.append(Path(path))
            return ()

    runtime = tmp_path / "generation"
    monkeypatch.setattr(program, "RUNTIME_ROOT", runtime)
    monkeypatch.setattr(program, "STATE_ROOT", runtime / "state")
    monkeypatch.setattr(program, "_accelerate_module", lambda *_args: ResetModule)

    assert program._retry_reset_inspection() == {
        "ok": True,
        "incomplete": [],
        "error": "",
    }
    assert observed == [runtime]


def test_markdown_and_json_are_deterministic_database_exports(task_source) -> None:
    first_markdown = program.render_markdown(task_source)
    second_markdown = program.render_markdown(task_source)
    first_json = program.database_projection(task_source)
    second_json = program.database_projection(task_source)

    assert first_markdown == second_markdown
    assert first_json == second_json
    assert first_markdown.startswith(
        "# IPFS Datasets DuckDB + Quack + DuckLake Data-Platform Improvement Plan"
    )
    assert "Generated projection only" in first_markdown
    assert "Quack is deliberately only the remote SQL transport" in first_markdown
    assert "DuckLake deployment constraints" in first_markdown
    assert "independently fenced DuckDB + Quack owners" in first_markdown
    assert "one owner process is the sole client" in first_markdown
    assert "https://duckdb.org/docs/current/core_extensions/ducklake" in first_markdown
    assert "https://duckdb.org/docs/lts/core_extensions/ducklake" in first_markdown
    assert "DQK-101" in first_markdown
    assert "DQK-102" in first_markdown
    assert "DQK-103" in first_markdown
    assert "Owned Parquet in lifecycle-managed object / filesystem storage" in first_markdown
    assert "Owned Parquet in object / IPFS-addressed storage" not in first_markdown
    assert "DQK-055" in first_markdown
    assert first_json["export_digest"].startswith("sha256:")
    assert first_json["row_counts"]["tasks"] == len(program.TASKS)
    json.dumps(first_json, sort_keys=True)


def test_ducklake_goal_subgoals_and_cutover_are_dependency_ordered(task_source) -> None:
    goals = {str(item["goal_id"]): item for item in program.GOALS}
    tasks = {str(item["task_id"]): item for item in program.TASKS}

    assert goals["DQK-G1200"]["parent_goal_cid"] == program.ROOT_GOAL_CID
    for goal_id in ("DQK-G1210", "DQK-G1220", "DQK-G1230"):
        assert goals[goal_id]["parent_goal_cid"] == "goal:cid:dqk-g1200"
    assert "DuckDB + Quack catalog management" in goals["DQK-G1220"]["title"]
    assert any(
        "single fenced DuckDB + Quack owner" in criterion
        for criterion in goals["DQK-G1220"]["acceptance_criteria"]
    )
    assert any(
        "private catalog-owner Quack endpoints" in criterion
        and "separate publication gateway" in criterion
        for criterion in goals["DQK-G1230"]["acceptance_criteria"]
    )

    ducklake_ids = {
        *(f"DQK-{number:03d}" for number in range(84, 103)),
        "DQK-104",
    }
    assert ducklake_ids == {
        task_id
        for task_id, task in tasks.items()
        if str(task["goal_id"]).startswith("DQK-G12")
    }
    assert {tasks[task_id]["goal_id"] for task_id in ducklake_ids} == {
        "DQK-G1210",
        "DQK-G1220",
        "DQK-G1230",
    }

    assert "DQK-082" in tasks["DQK-084"]["depends_on"]
    assert program.RUNTIME_ACTIVATION_GATE_TASK_ID in tasks["DQK-084"]["depends_on"]
    assert "DQK-082" in tasks["DQK-083"]["depends_on"]
    assert set(tasks[program.RUNTIME_ACTIVATION_GATE_TASK_ID]["depends_on"]) == {
        "DQK-082",
        "DQK-083",
    }
    assert tasks[program.RUNTIME_ACTIVATION_GATE_TASK_ID]["completion"] == "manual"
    assert tasks[program.RUNTIME_ACTIVATION_GATE_TASK_ID]["is_schedulable"] is False
    assert tasks[program.RUNTIME_ACTIVATION_GATE_TASK_ID]["status"] == "blocked"
    assert (
        tasks[program.RUNTIME_ACTIVATION_GATE_TASK_ID]["blocked_reason"]
        == "runtime_environment_activation_pending"
    )
    for task_id in ("DQK-040", "DQK-048", "DQK-049", "DQK-081", "DQK-084"):
        assert program.RUNTIME_ACTIVATION_GATE_TASK_ID in tasks[task_id]["depends_on"]
    assert "DQK-044" in tasks["DQK-088"]["depends_on"]
    assert "DQK-094" in tasks["DQK-088"]["depends_on"]
    assert "DQK-081" in tasks["DQK-089"]["depends_on"]
    assert "DQK-084" in tasks["DQK-050"]["depends_on"]
    assert set(tasks["DQK-104"]["depends_on"]) == {
        "DQK-041",
        "DQK-049",
        "DQK-050",
        "DQK-084",
        "DQK-085",
        "DQK-086",
    }
    for task_id in ("DQK-088", "DQK-090", "DQK-093", "DQK-096", "DQK-097"):
        assert "DQK-104" in tasks[task_id]["depends_on"]
    assert {"DQK-088", "DQK-090", "DQK-094"}.issubset(
        tasks["DQK-091"]["depends_on"]
    )
    assert "DQK-104" in tasks["DQK-094"]["depends_on"]
    assert "DQK-042" in tasks["DQK-092"]["depends_on"]
    assert "DQK-090" in tasks["DQK-096"]["depends_on"]
    assert "DQK-058" in tasks["DQK-097"]["depends_on"]
    assert {
        "DQK-060",
        "DQK-063",
        "DQK-066",
        "DQK-069",
        "DQK-072",
        "DQK-075",
        "DQK-100",
    }.issubset(tasks["DQK-099"]["depends_on"])
    assert "DQK-099" in tasks["DQK-053"]["depends_on"]
    assert set(tasks["DQK-100"]["depends_on"]) == {"DQK-089", "DQK-097"}
    assert set(tasks["DQK-102"]["depends_on"]) == {"DQK-053", "DQK-100"}
    assert tasks["DQK-102"]["completion"] == "manual"
    assert tasks["DQK-102"]["is_schedulable"] is False
    assert tasks["DQK-102"]["status"] == "blocked"
    assert tasks["DQK-102"]["blocked_reason"] == "ducklake_promotion_approval_pending"
    assert "DQK-102" in tasks["DQK-101"]["depends_on"]
    assert "DQK-101" in tasks["DQK-055"]["depends_on"]

    environment = " ".join(tasks["DQK-082"]["acceptance_criteria"])
    activation = " ".join(
        tasks[program.RUNTIME_ACTIVATION_GATE_TASK_ID]["acceptance_criteria"]
    )
    quack_hardening = " ".join(tasks["DQK-049"]["acceptance_criteria"])
    quack_compatibility = " ".join(tasks["DQK-050"]["acceptance_criteria"])
    capabilities = " ".join(tasks["DQK-084"]["acceptance_criteria"])
    catalog = " ".join(tasks["DQK-085"]["acceptance_criteria"])
    registry = " ".join(tasks["DQK-086"]["acceptance_criteria"])
    ingest = " ".join(tasks["DQK-088"]["acceptance_criteria"])
    shadow = " ".join(tasks["DQK-089"]["acceptance_criteria"])
    admission = " ".join(tasks["DQK-087"]["acceptance_criteria"])
    snapshots = " ".join(tasks["DQK-090"]["acceptance_criteria"])
    execution = " ".join(tasks["DQK-092"]["acceptance_criteria"])
    quack_catalog = " ".join(tasks["DQK-104"]["acceptance_criteria"])
    constraints = " ".join(tasks["DQK-094"]["acceptance_criteria"])
    concurrency = " ".join(tasks["DQK-095"]["acceptance_criteria"])
    maintenance = " ".join(tasks["DQK-096"]["acceptance_criteria"])
    security = " ".join(tasks["DQK-097"]["acceptance_criteria"])
    recovery = " ".join(tasks["DQK-098"]["acceptance_criteria"])
    lake_canary = " ".join(tasks["DQK-099"]["acceptance_criteria"])
    cutover = " ".join(tasks["DQK-100"]["acceptance_criteria"])
    release = " ".join(tasks["DQK-101"]["acceptance_criteria"])
    promotion = " ".join(tasks["DQK-102"]["acceptance_criteria"])
    assert "Docker socket access" in environment
    assert "digest-pinned image pull" in environment
    assert "disposable container run" in environment
    assert "volume disk before task dispatch" in environment
    assert "does not change the current master" in environment
    assert "provider or implementation-task completion cannot activate" in activation
    assert "outside the process tree it drains" in activation
    assert "durable pre-drain journal" in activation
    assert "authenticate and adopt the exact incomplete journal" in activation
    assert "Old masters, lanes, daemons, and DuckDB writers" in activation
    assert "sealed interpreter" in activation
    assert "two live generations" in activation
    assert "Fresh catalog-owner connections require a one-use" in quack_hardening
    assert "distinct external-access" in quack_hardening
    assert "DuckLake-over-Quack snapshot reads" in quack_compatibility
    assert "distinct snapshot versions" in quack_compatibility
    assert "Quack beta use" in quack_compatibility
    assert tasks["DQK-104"]["title"].startswith("Implement the distributed")
    assert "creates no production catalog endpoint" in quack_catalog
    assert "signed DQK-102 gate" in quack_catalog
    assert "Automatic extension installation/loading" in capabilities
    assert "ducklake, quack, and the selected object-store adapter" in capabilities
    assert "exactly one identity-bound DuckDB + Quack owner process" in catalog
    assert "Remote clients cannot directly open, mount, or mutate" in catalog
    assert "Active/passive takeover" in catalog
    assert "native DuckDB file-lock acquisition" in catalog
    assert "NFS, SMB, object URLs" in catalog
    assert "no role or authorization layer" in catalog
    assert "one-use Quack capability" in catalog
    assert "separate short-lived IAM capability" in catalog
    assert "CREATE_IF_NOT_EXISTS=false" in catalog
    assert "OVERRIDE_DATA_PATH=false" in catalog
    assert "AUTOMATIC_MIGRATION=false" in catalog
    for table_name in (
        "dataset_home_shard",
        "reader_lease",
        "logical_key_reservation",
        "ingest_outbox",
        "catalog_owner_generation",
        "maintenance_authorization",
        "promotion_decision",
        "promotion_execution",
        "lake_release_receipts",
    ):
        assert table_name in registry
    assert "small control DuckDB exclusively owns" in registry
    assert "separate private DuckDB DatabaseInstance" in registry
    assert "home-shard move requires" in registry
    assert "Source files and source CIDs remain untouched" in ingest
    assert "ownership-transfer authorization is non-self-issued" in ingest
    assert "caller/process birth" in ingest
    assert "ambient future delete authority" in ingest
    assert "accepted DQK-081 inventory" in shadow
    assert "exact active plan generation" in shadow
    assert "whole-file digest" in admission
    assert "one member per DuckDB + Quack catalog shard" in snapshots
    assert "Only the fenced owner opens the catalog file" in snapshots
    assert "remote workers open only the authenticated Quack endpoint" in snapshots
    assert "acquires an authoritative lease" in snapshots
    assert "process birth identity" in snapshots
    assert "DQK-096 maintenance" in snapshots
    assert "CREATE_IF_NOT_EXISTS=false" in snapshots
    assert "OVERRIDE_DATA_PATH=false" in snapshots
    assert "AUTOMATIC_MIGRATION=false" in snapshots
    assert "acquires, renews, and releases" in execution
    assert "complete lifetime of its remote Quack attachment" in execution
    assert "DuckDB with the pinned DuckLake extension" in quack_catalog
    assert "Quack provides the authenticated distributed transport" in quack_catalog
    assert "Exactly one identity-bound owner process" in quack_catalog
    assert "remote clients cannot directly open, copy, or mount" in quack_catalog
    assert "independent catalog shards can run concurrently" in quack_catalog
    assert "reusable default server token is not a per-operation authority" in quack_catalog
    assert "non-default quack_authentication_function" in quack_catalog
    assert "one-use capability on each fresh connection" in quack_catalog
    assert "task-owned handler independently verifies" in quack_catalog
    assert "non-default globally visible quack_authorization_function" in quack_catalog
    assert "never a prefix or regex approximation" in quack_catalog
    assert "signed, expiring, idempotent allowlisted template" in quack_catalog
    assert "Arbitrary SQL delivered by quack_query" in quack_catalog
    assert "ATTACH/DETACH/INSTALL/LOAD/SECRET" in quack_catalog
    assert "rejects concurrent cross-catalog overlap" in quack_catalog
    assert "invalidating its token" in quack_catalog
    assert "Active/passive takeover" in quack_catalog
    assert "never overlaps two owners" in quack_catalog
    assert "authorization callback blob/config" in quack_catalog
    assert "scrubs tokens, credentials, secrets, and raw SQL" in quack_catalog
    assert "cannot read control, proof" in quack_catalog
    assert "persistent logical-key/idempotency-key reservation" in constraints
    assert "durable outbox" in constraints
    assert "per-shard private companion owner-control DuckDB" in constraints
    assert "separate from DuckLake internal metadata" in constraints
    assert "single fenced catalog owner" in constraints
    assert "authoritative home shard" in constraints
    assert "unsupported cross-shard scope" in constraints
    assert "non-atomic snapshot boundary" in constraints
    assert "Independent catalog shards may progress concurrently" in constraints
    assert "successful reservation is never released or reused" in constraints
    assert "fails rather than skips" in concurrency
    assert "owner-locked and idempotent" in concurrency
    assert "clean only owned resources" in concurrency
    assert "sole client of each catalog file" in concurrency
    assert "Independent catalog shards execute concurrently" in concurrency
    assert "active/passive restart drill" in concurrency
    assert "split-brain or stale-generation owner" in concurrency
    assert "temporary in-doubt snapshot" in concurrency
    assert "terminal receipt or quarantine" in concurrency
    assert "No snapshot remains terminally unreceipted" in concurrency
    assert "Bare CHECKPOINT" in maintenance
    assert "Every compaction, expiration, scheduled cleanup, and orphan action" in maintenance
    assert "exact catalog identity" in maintenance
    assert "authoritative reader-lease set" in maintenance
    assert "candidate file set" in maintenance
    assert "accepted dry-run" in maintenance
    assert "identity distinct from the maintainer" in maintenance
    assert "separate scoped object-delete IAM" in maintenance
    assert "DQK-090 acquire/renew/release state" in maintenance
    assert "no native role layer" in security
    assert "Quack token alone cannot authorize" in security
    assert "independently authorize every privileged call" in security
    assert "directly open, copy, replace, or mount" in security
    assert "cannot open or ATTACH the DuckLake authority catalog" in security
    assert "writer/reader/maintenance drain" in recovery
    assert "closed catalog/registry file handles" in recovery
    assert "COPY FROM DATABASE" in recovery
    assert "DuckLake CHECKPOINT is forbidden" in recovery
    assert "No backup path reads or copies the live catalog file" in recovery
    assert "immutable versioned object inventory" in recovery
    assert "prohibited for the full capture window" in recovery
    assert "new owner generation and endpoint identity" in recovery
    assert "final domain-producer lineage consumed by DQK-053" in lake_canary
    assert "CREATE_IF_NOT_EXISTS=false" in lake_canary
    assert "OVERRIDE_DATA_PATH=false" in lake_canary
    assert "AUTOMATIC_MIGRATION=false" in lake_canary
    assert "does not alter production authority" in cutover
    assert "independently signed DQK-102 decision" in cutover
    assert "fresh exact-HEAD producer scan" in cutover
    assert "complete content-addressed delta through HEAD" in cutover
    assert "governed DQK-081 plan revision and DQK-083 generation rollover" in cutover
    assert "signed by an authorized identity independent" in promotion
    assert "Public producers and consumers operate with legacy mutable Parquet manifests" in promotion
    assert "dedicated signed promotion acknowledgement" in promotion
    assert "exact DQK-102 signed decision plus execution receipt" in release
    assert "every DuckDB + Quack catalog shard" in release
    assert "no catalog file had two owners" in release

    projection = program.database_projection(task_source)
    bodies = {
        str(row["task_alias"]): json.loads(str(row["body_json"]))
        for row in projection["tables"]["tasks"]
    }
    assert bodies["DQK-090"]["title"] == "Implement reproducible explicit multi-shard snapshot vectors"
    assert tasks["DQK-101"]["completion"] == "code"


def test_formal_source_uses_status_independent_content_identities(task_source) -> None:
    task_source_module = program._accelerate_module(
        "ipfs_accelerate_py.agent_supervisor.task_sources.duckdb_task_source",
        "ipfs_accelerate_py.agent_supervisor.duckdb_task_source",
    )
    proof_module = program._accelerate_module(
        "ipfs_accelerate_py.agent_supervisor.proof.formal_verification_contracts",
        "ipfs_accelerate_py.agent_supervisor.formal_verification_contracts",
    )
    _task_identity_payload = task_source_module._task_identity_payload
    content_identity = proof_module.content_identity

    formal = program.formal_source("tree:git:test-fixture")
    materialized = task_source.read_consistent_projection(("goals", "tasks"))
    task_cids = {str(row["task_cid"]) for row in materialized.tables["tasks"]}
    goal_cids = {str(row["goal_cid"]) for row in materialized.tables["goals"]}

    for goal in formal["objectives"]:
        identity = dict(goal)
        supplied = str(identity.pop("goal_cid"))
        assert supplied == content_identity(identity)
        assert supplied in goal_cids

    for task in formal["taskboard"]:
        assert task["task_cid"] == content_identity(_task_identity_payload(task))
        assert task["task_cid"] in task_cids
    original = deepcopy(formal["taskboard"][0])
    status_only = {**original, "status": "completed"}
    semantic_change = {**original, "objective": original["objective"] + " changed"}
    assert content_identity(_task_identity_payload(status_only)) == original["task_cid"]
    assert content_identity(_task_identity_payload(semantic_change)) != original["task_cid"]


def test_accelerate_imports_prefer_release_layout_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = "example.agent_supervisor.task_sources.duckdb_task_source"
    legacy = "example.agent_supervisor.duckdb_task_source"
    release_module = SimpleNamespace(
        layout="release",
        __file__=str(program.ACCELERATE_ROOT / "example/release.py"),
    )
    legacy_module = SimpleNamespace(
        layout="bridge",
        __file__=str(program.ACCELERATE_ROOT / "example/bridge.py"),
    )
    calls: list[str] = []

    def release_import(name: str):
        calls.append(name)
        if name == canonical:
            return release_module
        raise AssertionError(name)

    monkeypatch.setattr(program.importlib, "import_module", release_import)
    assert program._accelerate_module(canonical, legacy) is release_module
    assert calls == [canonical]

    calls.clear()

    def bridge_import(name: str):
        calls.append(name)
        if name == canonical:
            error = ModuleNotFoundError(canonical)
            error.name = canonical
            raise error
        if name == legacy:
            return legacy_module
        raise AssertionError(name)

    monkeypatch.setattr(program.importlib, "import_module", bridge_import)
    assert program._accelerate_module(canonical, legacy) is legacy_module
    assert calls == [canonical, legacy]

    def broken_release_import(name: str):
        if name == canonical:
            error = ModuleNotFoundError("missing release dependency")
            error.name = "unrelated_runtime_dependency"
            raise error
        raise AssertionError("legacy fallback must not mask a broken release module")

    monkeypatch.setattr(program.importlib, "import_module", broken_release_import)
    with pytest.raises(ModuleNotFoundError, match="missing release dependency"):
        program._accelerate_module(canonical, legacy)


def test_bootstrap_environment_is_hash_locked_atomic_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    environment_root = tmp_path / ".venvs/ipfs-datasets-duckdb-quack"
    receipt_path = environment_root / "environment-receipt.json"
    probe = _bootstrap_probe(environment_root)
    repository = {
        "repository_root": str(program.REPO_ROOT.resolve()),
        "commit": "1" * 40,
        "tree": "2" * 40,
        "artifacts": program._bootstrap_artifact_evidence(),
    }
    builder_calls: list[tuple[dict[str, object], Path]] = []
    install_calls: list[list[str]] = []

    class FakeEnvBuilder:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def create(self, path):
            selected = Path(path)
            builder_calls.append((self.kwargs, selected))
            (selected / "bin").mkdir(parents=True)
            (selected / "bin/python").write_bytes(b"mock-python")

    def fake_run(argv, **_kwargs):
        install_calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="installed", stderr="")

    monkeypatch.setattr(program, "EXPECTED_ENV_ROOT", environment_root)
    monkeypatch.setattr(
        program,
        "ENVIRONMENT_LIFECYCLE_LOCK",
        tmp_path / ".environment.lock",
    )
    monkeypatch.setattr(program, "ENVIRONMENT_RECEIPT", receipt_path)
    monkeypatch.setattr(
        program,
        "SEALED_PYTHON_LAUNCHER",
        environment_root / "bin/dqk-sealed-python",
    )
    monkeypatch.setattr(program, "_assert_supported_bootstrap_host", lambda: None)
    monkeypatch.setattr(program, "_bootstrap_repository_evidence", lambda: repository)
    monkeypatch.setattr(
        program,
        "_bootstrap_repository_evidence_valid",
        lambda evidence: (evidence == repository, "mock repository binding"),
    )
    monkeypatch.setattr(
        program,
        "_run_environment_probe",
        lambda _python, **_kwargs: probe,
    )
    monkeypatch.setattr(program.venv, "EnvBuilder", FakeEnvBuilder)
    monkeypatch.setattr(program.subprocess, "run", fake_run)
    monkeypatch.setattr(
        program,
        "_provision_bootstrap_validator",
        lambda: {"receipt_id": "sha256:" + "f" * 64},
    )

    args = program.build_parser().parse_args(["bootstrap-environment"])
    assert args.handler(args) == 0
    assert len(builder_calls) == 1
    builder_options, created_root = builder_calls[0]
    assert created_root == environment_root
    assert builder_options["system_site_packages"] is False
    assert builder_options["clear"] is False
    assert builder_options["upgrade"] is False
    assert len(install_calls) == 3
    download_argv, install_argv, remove_installer_argv = install_calls
    assert download_argv[0] == str(environment_root / "bin/python")
    assert "download" in download_argv
    assert "--require-hashes" in download_argv
    assert "--only-binary=:all:" in download_argv
    assert download_argv[-1] == str(program.BOOTSTRAP_REQUIREMENTS)
    assert install_argv[0] == str(environment_root / "bin/python")
    assert "install" in install_argv
    assert "--require-hashes" in install_argv
    assert "--only-binary=:all:" in install_argv
    assert "--ignore-installed" in install_argv
    assert "--no-index" in install_argv
    assert "--report" in install_argv
    assert install_argv[-1] == str(program.BOOTSTRAP_REQUIREMENTS)
    assert "uninstall" in remove_installer_argv
    assert remove_installer_argv[-2:] == ["--yes", "pip"]

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt_without_id = dict(receipt)
    receipt_id = receipt_without_id.pop("receipt_id")
    assert receipt_id == (
        "receipt:sha256:"
        + program._sha256_text(program._canonical_json(receipt_without_id))
    )
    assert receipt["requirements"]["sha256"] == (
        program.BOOTSTRAP_REQUIREMENTS_SHA256
    )
    assert receipt["probe"]["duckdb_record_verified_file_count"] == 55
    assert receipt["quack_extension_attested"] is False

    idempotent_args = program.build_parser().parse_args(["bootstrap-environment"])
    assert idempotent_args.handler(idempotent_args) == 0
    assert len(builder_calls) == 1
    assert len(install_calls) == 3


def test_bootstrap_environment_refuses_existing_unattested_prefix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    environment_root = tmp_path / ".venvs/ipfs-datasets-duckdb-quack"
    receipt_path = environment_root / "environment-receipt.json"
    (environment_root / "bin").mkdir(parents=True)
    (environment_root / "bin/python").write_bytes(b"existing-python")
    sentinel = environment_root / "preserve-me"
    sentinel.write_text("untouched\n", encoding="utf-8")
    monkeypatch.setattr(program, "EXPECTED_ENV_ROOT", environment_root)
    monkeypatch.setattr(
        program,
        "ENVIRONMENT_LIFECYCLE_LOCK",
        tmp_path / ".environment.lock",
    )
    monkeypatch.setattr(program, "ENVIRONMENT_RECEIPT", receipt_path)
    monkeypatch.setattr(
        program,
        "SEALED_PYTHON_LAUNCHER",
        environment_root / "bin/dqk-sealed-python",
    )
    monkeypatch.setattr(
        program,
        "_run_environment_probe",
        lambda _python, **_kwargs: _bootstrap_probe(environment_root),
    )
    monkeypatch.setattr(
        program.venv,
        "EnvBuilder",
        lambda **_kwargs: pytest.fail("existing environments must not be recreated"),
    )
    monkeypatch.setattr(
        program.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("existing environments must not be upgraded"),
    )

    args = program.build_parser().parse_args(["bootstrap-environment"])
    with pytest.raises(RuntimeError, match="refusing to modify or recreate"):
        args.handler(args)
    assert sentinel.read_text(encoding="utf-8") == "untouched\n"
    assert not receipt_path.exists()


def test_bootstrap_receipt_validation_rejects_mutable_json_forgery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    environment_root = tmp_path / ".venvs/ipfs-datasets-duckdb-quack"
    probe = _bootstrap_probe(environment_root)
    repository = {
        "repository_root": str(program.REPO_ROOT.resolve()),
        "commit": "1" * 40,
        "tree": "2" * 40,
        "artifacts": program._bootstrap_artifact_evidence(),
    }
    monkeypatch.setattr(program, "EXPECTED_ENV_ROOT", environment_root)
    monkeypatch.setattr(
        program,
        "SEALED_PYTHON_LAUNCHER",
        environment_root / "bin/dqk-sealed-python",
    )
    monkeypatch.setattr(
        program,
        "ENVIRONMENT_RECEIPT",
        environment_root / "environment-receipt.json",
    )
    monkeypatch.setattr(
        program,
        "_bootstrap_repository_evidence_valid",
        lambda evidence: (evidence == repository, "mock repository binding"),
    )
    receipt = program._environment_receipt_payload(probe, repository)
    assert program._validate_environment_receipt(receipt, probe)[0]

    forged_probe = deepcopy(probe)
    forged_probe["duckdb_record_verified_file_count"] = 54
    forged = program._environment_receipt_payload(forged_probe, repository)
    assert not program._validate_environment_receipt(forged, probe)[0]
    forged = deepcopy(receipt)
    forged["receipt_id"] = "receipt:sha256:" + "0" * 64
    assert not program._validate_environment_receipt(forged, probe)[0]
    forged_repository = {**repository, "commit": "3" * 40}
    forged = program._environment_receipt_payload(probe, forged_repository)
    assert not program._validate_environment_receipt(forged, probe)[0]

    inherited = deepcopy(probe)
    inherited["system_site_packages"] = True
    assert not program._bootstrap_probe_compatible(inherited)[0]
    unpinned_archive = deepcopy(probe)
    unpinned_archive["duckdb_install_archive_sha256"] = "sha256:" + "0" * 64
    assert not program._bootstrap_probe_compatible(unpinned_archive)[0]
    foreign_path = deepcopy(probe)
    foreign_path["python_sys_path"].append("/usr/local/lib/python3.12/dist-packages")
    assert not program._bootstrap_probe_compatible(foreign_path)[0]
    foreign_distribution = deepcopy(probe)
    foreign_distribution["installed_distributions"].append(
        {
            "name": "requests",
            "version": "999",
            "root": "/usr/local/lib/python3.12/dist-packages",
        }
    )
    assert not program._bootstrap_probe_compatible(foreign_distribution)[0]

    monkeypatch.setattr(
        program.sys,
        "path",
        [
            str(program.ACCELERATE_ROOT.resolve()),
            *probe["python_sys_path"],
            "/usr/lib/python3/dist-packages",
        ],
    )
    runtime_valid, runtime_detail = program._live_runtime_import_contract(probe)
    assert not runtime_valid
    assert "sys.path is not sealed" in runtime_detail


def test_environment_probe_rejects_loose_code_and_rewritten_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The admitted wheel, not mutable RECORD metadata, is the code root."""

    root = tmp_path / "venv"
    site_root = root / "lib/python3.12/site-packages"
    artifact_root = root / "bootstrap-artifacts"
    dist_info = "duckdb-1.5.5.dist-info"
    site_root.mkdir(parents=True)
    artifact_root.mkdir(parents=True)
    (root / "bin").mkdir(parents=True)
    (root / "pyvenv.cfg").write_text(
        "home = /usr/bin\ninclude-system-site-packages = false\n",
        encoding="utf-8",
    )
    wheel_payloads = {
        "duckdb/__init__.py": b"__version__ = '1.5.5'\n",
        "_duckdb.cpython-312-test.so": b"synthetic-native-module",
        f"{dist_info}/METADATA": b"Name: duckdb\nVersion: 1.5.5\n",
        f"{dist_info}/WHEEL": b"Wheel-Version: 1.0\nTag: cp312-cp312-manylinux_2_28_x86_64\n",
        f"{dist_info}/RECORD": b"",
    }
    archive_path = artifact_root / "duckdb-1.5.5-cp312-test.whl"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for relative, payload in wheel_payloads.items():
            archive.writestr(relative, payload)
    archive_digest = program._sha256_file(archive_path)
    for relative, payload in wheel_payloads.items():
        if relative.endswith("/RECORD"):
            continue
        destination = site_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    (site_root / dist_info / "INSTALLER").write_bytes(b"pip\n")
    (site_root / dist_info / "REQUESTED").write_bytes(b"")
    record_path = site_root / dist_info / "RECORD"

    def rewrite_record() -> None:
        rows: list[list[str]] = []
        for candidate in sorted(site_root.rglob("*")):
            if not candidate.is_file() or candidate == record_path:
                continue
            payload = candidate.read_bytes()
            digest = hashlib.sha256(payload).digest()
            encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
            rows.append(
                [
                    candidate.relative_to(site_root).as_posix(),
                    f"sha256={encoded}",
                    str(len(payload)),
                ]
            )
        rows.append([f"{dist_info}/RECORD", "", ""])
        buffer = io.StringIO(newline="")
        csv.writer(buffer, lineterminator="\n").writerows(rows)
        record_path.write_text(buffer.getvalue(), encoding="utf-8")

    rewrite_record()
    report = {
        "version": "1",
        "install": [
            {
                "metadata": {"name": "duckdb", "version": "1.5.5"},
                "download_info": {
                    "url": archive_path.as_uri(),
                    "archive_info": {
                        "hashes": {"sha256": archive_digest.removeprefix("sha256:")}
                    },
                },
            }
        ],
    }
    (artifact_root / "pip-install-report.json").write_text(
        json.dumps(report), encoding="utf-8"
    )

    class FakeDistribution:
        version = "1.5.5"
        metadata = {"Name": "duckdb"}

        @property
        def files(self):
            return tuple(
                candidate.relative_to(site_root).as_posix()
                for candidate in sorted(site_root.rglob("*"))
                if candidate.is_file()
            )

        def locate_file(self, relative):
            return site_root / str(relative)

    fake_distribution = FakeDistribution()
    module = SimpleNamespace(
        __file__=str(site_root / "duckdb/__init__.py"), __version__="1.5.5"
    )
    native = SimpleNamespace(
        __file__=str(site_root / "_duckdb.cpython-312-test.so")
    )
    original_import = program.importlib.import_module

    def fake_import(name: str):
        if name == "duckdb":
            return module
        if name == "_duckdb":
            return native
        return original_import(name)

    stdlib_root = Path(os.__file__).resolve().parent
    sealed_paths = [
        str(stdlib_root.parent / "python312.zip"),
        str(stdlib_root),
        str(stdlib_root / "lib-dynload"),
        str(site_root),
    ]
    monkeypatch.setattr(program, "EXPECTED_ENV_ROOT", root)
    monkeypatch.setattr(
        program, "SEALED_PYTHON_LAUNCHER", root / "bin/dqk-sealed-python"
    )
    monkeypatch.setattr(program.importlib.metadata, "distribution", lambda _name: fake_distribution)
    monkeypatch.setattr(program.importlib.metadata, "distributions", lambda: [fake_distribution])
    monkeypatch.setattr(program.importlib, "import_module", fake_import)
    monkeypatch.setattr(
        program, "_bootstrap_allowed_wheel_hashes", lambda: frozenset({archive_digest})
    )
    monkeypatch.setattr(program.sys, "path", sealed_paths)
    launcher = program._sealed_python_launcher_content(sealed_paths)
    program.SEALED_PYTHON_LAUNCHER.write_text(launcher, encoding="utf-8")
    program.SEALED_PYTHON_LAUNCHER.chmod(0o500)

    probe = program._local_environment_probe(
        environment_root=root, sealed_site_roots=[str(site_root)]
    )
    assert probe["installed_distributions"] == [
        {"name": "duckdb", "version": "1.5.5", "root": str(site_root)}
    ]

    loose_code = site_root / "sitecustomize.py"
    loose_code.write_text("raise RuntimeError('must never execute')\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="does not exactly match"):
        program._local_environment_probe(
            environment_root=root, sealed_site_roots=[str(site_root)]
        )
    loose_code.unlink()

    (site_root / "duckdb/__init__.py").write_bytes(
        b"__version__ = '1.5.5'\nMUTATED = True\n"
    )
    rewrite_record()
    with pytest.raises(RuntimeError, match="differs from admitted wheel"):
        program._local_environment_probe(
            environment_root=root, sealed_site_roots=[str(site_root)]
        )


def test_environment_probe_executes_only_the_opened_trusted_base_python(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    environment_root = tmp_path / "venv"
    environment_python = environment_root / "bin/python"
    environment_python.parent.mkdir(parents=True)
    environment_python.symlink_to(program._trusted_base_python_path())
    monkeypatch.setattr(
        program,
        "ENVIRONMENT_LIFECYCLE_LOCK",
        tmp_path / ".environment.lock",
    )
    monkeypatch.setenv("LD_PRELOAD", "/tmp/foreign-loader.so")
    captured: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        captured["kwargs"] = dict(kwargs)
        return SimpleNamespace(returncode=0, stdout="{}\n", stderr="")

    monkeypatch.setattr(program.subprocess, "run", fake_run)
    assert program._run_environment_probe(environment_python) == {}
    assert str(captured["argv"][0]).startswith("/proc/self/fd/")
    assert captured["kwargs"]["pass_fds"]
    assert "LD_PRELOAD" not in captured["kwargs"]["env"]
    assert captured["kwargs"]["env"][
        "IPFS_DATASETS_DQK_PYTHON_EXECUTABLE"
    ] == str(environment_python.absolute())

    environment_python.unlink()
    environment_python.write_bytes(b"malicious replay executable")
    with pytest.raises(RuntimeError, match="does not resolve to the admitted base"):
        program._run_environment_probe(environment_python)


def test_launcher_binds_duckdb_roots_and_disables_markdown_mutators(
    task_source,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(program, "DATABASE_PATH", task_source.database_path)
    monkeypatch.setattr(program, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(program, "WORKTREE_ROOT", tmp_path / "worktrees")
    monkeypatch.setattr(program, "MERGE_QUEUE_ROOT", tmp_path / "merge-queue")
    monkeypatch.setattr(program, "MASTER_ROOT", tmp_path / "master")
    monkeypatch.setattr(program, "MASTER_LOG", tmp_path / "master/supervisor.log")
    monkeypatch.setattr(program, "MASTER_PID", tmp_path / "master/supervisor.pid")

    command = program.supervisor_command(lanes=2, duration_seconds=3600, detach=True)
    joined = "\n".join(command)
    snapshot = task_source.snapshot()

    assert "--implementation-supervisor-lanes-per-track\n2" in joined
    assert "--common-arg=--task-source-kind" in command
    assert "--common-arg=duckdb" in command
    assert f"--common-arg={snapshot.plan_root_cid}" in command
    assert f"--common-arg={snapshot.repository_tree_id}" in command
    assert "--common-arg=--no-retry-budget-guardrail" in command
    assert "--common-arg=--no-dependency-guardrail" in command
    assert "--common-arg=--no-reconciliation-guardrail" in command
    assert "--common-arg=--no-objective-task-janitor" in command
    assert "--implementation-supervisor-defaults" not in command
    assert command[-1] == "--detach"

    from ipfs_accelerate_py.agent_supervisor.multi_supervisor_runner import (
        build_arg_parser,
        common_args_from_parsed_args,
        tracks_from_parsed_args,
    )
    from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_daemon import (
        parse_args as parse_daemon_args,
    )
    from ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_supervisor import (
        PortalImplementationSupervisor,
        parse_args as parse_supervisor_args,
        supervisor_config_from_args,
    )

    runner_args = build_arg_parser().parse_args(command[3:])
    tracks = tracks_from_parsed_args(runner_args)
    common = common_args_from_parsed_args(runner_args)
    assert len(tracks) == 2
    for index, track in enumerate(tracks):
        supervisor_args = parse_supervisor_args([*common, *track.extra_args])
        config = supervisor_config_from_args(supervisor_args, repo_root=program.REPO_ROOT)
        daemon_command = PortalImplementationSupervisor(config)._build_daemon_command()
        assert config.managed_python_executable == str(program.SEALED_PYTHON_LAUNCHER)
        assert daemon_command[0] == str(program.SEALED_PYTHON_LAUNCHER)
        daemon_args = parse_daemon_args(daemon_command[3:])
        assert config.task_source_kind == daemon_args.task_source_kind == "duckdb"
        assert config.task_shard_index == daemon_args.task_shard_index == index
        assert config.task_shard_count == daemon_args.task_shard_count == 2
        assert daemon_args.expected_task_source_root == snapshot.plan_root_cid
        assert (
            daemon_args.expected_task_source_repository_root
            == snapshot.repository_tree_id
        )
        expected_slice = {
            str(task["task_id"])
            for task in program.TASKS
            if task.get("is_schedulable", True)
        }
        _hold_snapshot, hold = program._manual_gate_hold_projection(task_source)
        expected_slice.difference_update(hold["held_task_aliases"])
        assert set(daemon_args.execution_slice_task_id) == expected_slice
        assert program.RELEASE_GATE_TASK_ID not in daemon_args.execution_slice_task_id
        assert program.REFINEMENT_GATE_TASK_ID not in daemon_args.execution_slice_task_id
        assert program.PROMOTION_GATE_TASK_ID not in daemon_args.execution_slice_task_id
        assert (
            program.RUNTIME_ACTIVATION_GATE_TASK_ID
            not in daemon_args.execution_slice_task_id
        )


def test_launcher_derives_execution_slice_from_accepted_database_generation(
    task_source,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projection = task_source.read_consistent_projection(
        ("tasks", "task_dependencies", "task_events")
    )
    rows = [dict(row) for row in projection.tables["tasks"]]
    removed_alias = next(
        str(row["task_alias"])
        for row in rows
        if program._decode_body(row).get("is_schedulable", True)
    )
    removed_cid = next(
        str(row["task_cid"])
        for row in rows
        if str(row["task_alias"]) == removed_alias
    )
    rows = [row for row in rows if str(row["task_alias"]) != removed_alias]
    template = deepcopy(rows[0])
    revised_body = program._decode_body(template)
    revised_body.update(
        {
            "task_id": "DQK-999",
            "title": "Accepted rollover task",
            "is_schedulable": True,
        }
    )
    template.update(
        {
            "task_alias": "DQK-999",
            "task_cid": "task:accepted-generation:dqk-999",
            "body_json": program._canonical_json(revised_body),
            "status": "pending",
        }
    )
    rows.append(template)
    revised_snapshot = SimpleNamespace(
        **{
            **vars(projection.snapshot),
            "plan_root_cid": "plan:accepted-rollover",
        }
    )
    revised_projection = SimpleNamespace(
        snapshot=revised_snapshot,
        tables={
            "tasks": tuple(rows),
            "task_dependencies": tuple(
                row
                for row in projection.tables["task_dependencies"]
                if removed_cid
                not in {
                    str(row["task_cid"]),
                    str(row["dependency_task_cid"]),
                }
            ),
            "task_events": projection.tables["task_events"],
        },
        row_counts={
            "tasks": len(rows),
            "task_dependencies": sum(
                removed_cid
                not in {
                    str(row["task_cid"]),
                    str(row["dependency_task_cid"]),
                }
                for row in projection.tables["task_dependencies"]
            ),
            "task_events": projection.row_counts["task_events"],
        },
    )
    revised_source = SimpleNamespace(
        read_consistent_projection=lambda _tables: revised_projection
    )
    monkeypatch.setattr(program, "_source", lambda: revised_source)
    monkeypatch.setattr(program, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(program, "WORKTREE_ROOT", tmp_path / "worktrees")
    monkeypatch.setattr(program, "MERGE_QUEUE_ROOT", tmp_path / "merge-queue")
    monkeypatch.setattr(program, "MASTER_ROOT", tmp_path / "master")
    monkeypatch.setattr(program, "MASTER_LOG", tmp_path / "master/supervisor.log")
    monkeypatch.setattr(program, "MASTER_PID", tmp_path / "master/supervisor.pid")

    command = program.supervisor_command(
        lanes=1,
        duration_seconds=3600,
        detach=True,
        launch_token="d" * 32,
    )
    execution_slice = program._master_execution_slice(command)
    assert "DQK-999" in execution_slice
    assert removed_alias not in execution_slice
    assert execution_slice == tuple(sorted(execution_slice))
    assert f"--common-arg={revised_snapshot.plan_root_cid}" in command


def test_master_command_binding_requires_exact_supervisor_contract(
    task_source,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(program, "DATABASE_PATH", task_source.database_path)
    monkeypatch.setattr(program, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(program, "WORKTREE_ROOT", tmp_path / "worktrees")
    monkeypatch.setattr(program, "MERGE_QUEUE_ROOT", tmp_path / "merge-queue")
    monkeypatch.setattr(program, "MASTER_ROOT", tmp_path / "master")
    monkeypatch.setattr(program, "MASTER_LOG", tmp_path / "master/supervisor.log")
    monkeypatch.setattr(program, "MASTER_PID", tmp_path / "master/supervisor.pid")

    detached_logical = program.supervisor_command(
        lanes=2,
        duration_seconds=3600,
        detach=True,
        launch_token="a" * 32,
    )
    foreground_logical = program.supervisor_command(
        lanes=2,
        duration_seconds=float("inf"),
        detach=False,
        launch_token="b" * 32,
    )
    detached = program._expanded_sealed_python_argv(detached_logical)
    foreground = program._expanded_sealed_python_argv(foreground_logical)
    assert program._actual_master_command_matches({"argv": detached})
    assert program._actual_master_command_matches({"argv": foreground})

    nonce_free = program._expanded_sealed_python_argv(
        program.supervisor_command(
            lanes=2,
            duration_seconds=3600,
            detach=True,
        )
    )
    assert not program._actual_master_command_matches({"argv": nonce_free})

    wrong_config = list(detached_logical)
    worktree_value = f"--common-arg={program.WORKTREE_ROOT}"
    wrong_config[wrong_config.index(worktree_value)] = (
        f"--common-arg={tmp_path / 'other-worktrees'}"
    )
    assert program._option_value(wrong_config, "--label") == program.PROGRAM_ID
    assert program._option_value(wrong_config, "--repo-root") == str(program.REPO_ROOT)
    assert not program._actual_master_command_matches(
        {"argv": program._expanded_sealed_python_argv(wrong_config)}
    )


def test_launch_binding_requires_unique_nonce_birth_and_new_pidfile(
    task_source,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(program, "DATABASE_PATH", task_source.database_path)
    monkeypatch.setattr(program, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(program, "WORKTREE_ROOT", tmp_path / "worktrees")
    monkeypatch.setattr(program, "MERGE_QUEUE_ROOT", tmp_path / "merge-queue")
    monkeypatch.setattr(program, "MASTER_ROOT", tmp_path / "master")
    monkeypatch.setattr(program, "MASTER_LOG", tmp_path / "master/supervisor.log")
    pid_path = tmp_path / "master/supervisor.pid"
    monkeypatch.setattr(program, "MASTER_PID", pid_path)
    pid_path.parent.mkdir(parents=True)
    pid_path.write_text("4242\n", encoding="utf-8")

    launch_token = "a" * 32
    command = program.supervisor_command(
        lanes=2,
        duration_seconds=3600,
        detach=True,
        launch_token=launch_token,
    )
    identity = {
        "pid": 4242,
        "boot_id": "boot-a",
        "start_ticks": 101,
        "argv": program._expanded_sealed_python_argv(command),
    }
    process_environment = program._sealed_python_environment()
    monkeypatch.setattr(
        program,
        "_process_python_environment",
        lambda _pid: process_environment,
    )
    marker = {
        "boot_id": "boot-a",
        "start_ticks_floor": 100,
        "wall_time_ns": 0,
        "pidfile_before": None,
    }
    assert program._actual_master_command_matches(identity)
    assert program._launched_identity_matches(
        identity,
        expected_command=command,
        marker=marker,
        expected_pid=4242,
    )

    current = pid_path.lstat()
    stale_marker = {
        **marker,
        "pidfile_before": {
            "device": current.st_dev,
            "inode": current.st_ino,
            "mtime_ns": current.st_mtime_ns,
            "size": current.st_size,
            "value": "4242\n",
        },
    }
    assert not program._launched_identity_matches(
        identity,
        expected_command=command,
        marker=stale_marker,
    )
    wrong_command = program.supervisor_command(
        lanes=2,
        duration_seconds=3600,
        detach=True,
        launch_token="b" * 32,
    )
    assert not program._launched_identity_matches(
        identity,
        expected_command=wrong_command,
        marker=marker,
    )
    assert not program._launched_identity_matches(
        identity,
        expected_command=command,
        marker=marker,
        expected_pid=4243,
    )


def test_detached_launch_keeps_the_sealed_wrapper_as_the_master(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    master_root = tmp_path / "master"
    monkeypatch.setattr(program, "MASTER_ROOT", master_root)
    monkeypatch.setattr(program, "MASTER_LOG", master_root / "supervisor.log")
    monkeypatch.setattr(program, "MASTER_PID", master_root / "supervisor.pid")
    monkeypatch.setattr(program, "preflight_checks", lambda **_kwargs: [])
    monkeypatch.setattr(program, "_print_checks", lambda _checks: None)
    expected_command = [
        str(program.SEALED_PYTHON_LAUNCHER),
        "-m",
        "ipfs_accelerate_py.agent_supervisor.multi_supervisor_runner",
        "--stamp",
        "dqk-test-" + "a" * 32,
    ]
    monkeypatch.setattr(
        program,
        "supervisor_command",
        lambda **kwargs: (
            expected_command
            if kwargs["detach"] is False
            else pytest.fail("cmd_launch delegated detach to the runner")
        ),
    )
    snapshot = SimpleNamespace(plan_root_cid="plan:a", repository_tree_id="tree:a")
    monkeypatch.setattr(
        program,
        "_source",
        lambda: SimpleNamespace(snapshot=lambda: snapshot),
    )
    marker = {"boot_id": "boot-a", "start_ticks_floor": 10, "wall_time_ns": 1}
    monkeypatch.setattr(program, "_launch_marker", lambda: marker)
    captured: dict[str, object] = {}

    class Process:
        pid = 4242

        def poll(self):
            return None

        def terminate(self):
            pytest.fail("successful launch must not terminate its master")

    def popen(command, **kwargs):
        captured["command"] = list(command)
        captured["kwargs"] = dict(kwargs)
        return Process()

    monkeypatch.setattr(program.subprocess, "Popen", popen)

    def bind(selected_snapshot, **kwargs):
        captured["bound_snapshot"] = selected_snapshot
        captured["bind_kwargs"] = dict(kwargs)
        return 4242

    monkeypatch.setattr(program, "_bind_launched_master", bind)
    monkeypatch.setattr(program, "task_status", lambda _source: {"master_alive": True})

    result = program.cmd_launch(
        SimpleNamespace(
            lanes=1,
            duration_seconds=3600.0,
            foreground=False,
            dry_run=False,
        )
    )
    assert result == 0
    assert captured["command"] == expected_command
    assert "--detach" not in expected_command
    assert captured["kwargs"]["start_new_session"] is True
    assert captured["bind_kwargs"]["expected_pid"] == 4242


def test_manual_gates_cannot_enter_ready_set(task_source) -> None:
    for task_id in (program.BOOTSTRAP_TASK_ID, program.RELEASE_VERIFIER_TASK_ID):
        task = task_source.get_task(task_id)
        assert task is not None
        task_source.compare_and_set_status(
            task_id,
            expected_revision=task.revision,
            status="completed",
            receipt={"schema": "test/receipt@1"},
        )

    ready = {item.task_id for item in task_source.ready_tasks(limit=1000).tasks}
    release_gate = task_source.get_task(program.RELEASE_GATE_TASK_ID)
    refinement_gate = task_source.get_task(program.REFINEMENT_GATE_TASK_ID)
    promotion_gate = task_source.get_task(program.PROMOTION_GATE_TASK_ID)
    runtime_gate = task_source.get_task(program.RUNTIME_ACTIVATION_GATE_TASK_ID)
    assert release_gate is not None and release_gate.status == "blocked"
    assert refinement_gate is not None and refinement_gate.status == "blocked"
    assert promotion_gate is not None and promotion_gate.status == "blocked"
    assert runtime_gate is not None and runtime_gate.status == "blocked"
    assert program.RELEASE_GATE_TASK_ID not in ready
    assert program.REFINEMENT_GATE_TASK_ID not in ready
    assert program.PROMOTION_GATE_TASK_ID not in ready
    assert program.RUNTIME_ACTIVATION_GATE_TASK_ID not in ready


def test_doctor_rejects_bare_manual_gate_cas_while_promotion_waits(
    task_source,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for task in task_source.query("tasks", limit=1_000):
        task_id = str(task["task_alias"])
        if task_id == program.PROMOTION_GATE_TASK_ID:
            continue
        record = task_source.get_task(task_id)
        assert record is not None
        if record.status != "completed":
            task_source.compare_and_set_status(
                task_id,
                expected_revision=record.revision,
                status="completed",
                receipt={"schema": "test/manual-wait-prerequisite@1"},
            )

    runtime = tmp_path / "runtime"
    monkeypatch.setattr(program, "STATE_ROOT", runtime / "state")
    monkeypatch.setattr(program, "MASTER_PID", runtime / "master.pid")
    monkeypatch.setattr(program, "MASTER_IDENTITY", runtime / "master-identity.json")
    monkeypatch.setattr(program, "MASTER_LOG", runtime / "master.log")
    monkeypatch.setattr(program, "_source", lambda: task_source)

    payload = program.task_status(task_source)
    assert payload["manual_gate_wait_only"] is True
    assert payload["master_alive"] is False
    blocked = [
        gate for gate in payload["blocked_gates"] if gate["status"] == "blocked"
    ]
    assert len(blocked) == 1
    assert blocked[0]["task_id"] == program.PROMOTION_GATE_TASK_ID
    assert blocked[0]["authorization_verified"] is False
    assert payload["authorization_evidence_failed"] is True

    assert program.cmd_doctor(SimpleNamespace(stale_seconds=1_200.0)) == 2
    doctor = json.loads(capsys.readouterr().out)
    assert doctor["healthy"] is False
    assert any(
        finding["kind"] == "manual_gate_authentication_failed"
        for finding in doctor["findings"]
    )


def test_program_exports_use_one_consistent_projection(task_source) -> None:
    class ProjectionOnlySource:
        def read_consistent_projection(self, tables):
            return task_source.read_consistent_projection(tables)

        def snapshot(self):  # pragma: no cover - must never be called
            raise AssertionError("torn snapshot read")

        def query(self, *args, **kwargs):  # pragma: no cover - must never be called
            raise AssertionError("paginated connection read")

    projection = program.database_projection(ProjectionOnlySource())
    assert projection["row_counts"]["tasks"] == len(program.TASKS) == 97
    assert len(projection["tables"]["tasks"]) == len(program.TASKS) == 97


def test_program_export_does_not_truncate_more_than_one_thousand_events(
    task_source,
) -> None:
    base = task_source.read_consistent_projection(program.EXPORT_TABLES)
    events = tuple(
        {
            "event_cid": f"event:{index:04d}",
            "sequence": index + 1,
            "revision": index + 1,
            "task_cid": "task:test",
            "event_type": "test",
            "body_json": "{}",
        }
        for index in range(1001)
    )
    tables = dict(base.tables)
    counts = dict(base.row_counts)
    tables["task_events"] = events
    counts["task_events"] = len(events)

    class LargeProjectionSource:
        def read_consistent_projection(self, _tables):
            return SimpleNamespace(
                snapshot=base.snapshot,
                tables=tables,
                row_counts=counts,
            )

    projection = program.database_projection(LargeProjectionSource())
    assert projection["row_counts"]["task_events"] == 1001
    assert len(projection["tables"]["task_events"]) == 1001


def test_export_defaults_are_distinct_and_replace_atomically(
    task_source,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    markdown_path = tmp_path / "plan.md"
    json_path = tmp_path / "runtime/plan.json"
    markdown_path.write_text("do not overwrite\n", encoding="utf-8")
    monkeypatch.setattr(program, "DEFAULT_MARKDOWN_EXPORT", markdown_path)
    monkeypatch.setattr(program, "DEFAULT_JSON_EXPORT", json_path)
    monkeypatch.setattr(program, "_source", lambda **_kwargs: task_source)

    args = program.build_parser().parse_args(["export", "--format", "json"])
    assert args.output is None
    assert args.handler(args) == 0
    assert markdown_path.read_text(encoding="utf-8") == "do not overwrite\n"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "ipfs_datasets_py/duckdb-quack-plan-export@1"

    victim = tmp_path / "existing.txt"
    victim.write_text("old\n", encoding="utf-8")

    def fail_replace(_source, _destination):
        raise OSError("injected replace failure")

    monkeypatch.setattr(program.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected"):
        program._atomic_write_text(victim, "new\n")
    assert victim.read_text(encoding="utf-8") == "old\n"
    assert not tuple(tmp_path.glob(".existing.txt.*.tmp"))


def test_master_identity_rejects_pid_reuse(
    task_source,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    master_root = tmp_path / "master"
    master_pid = master_root / "master.pid"
    master_identity = master_root / "identity.json"
    monkeypatch.setattr(program, "DATABASE_PATH", task_source.database_path)
    monkeypatch.setattr(program, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(program, "WORKTREE_ROOT", tmp_path / "worktrees")
    monkeypatch.setattr(program, "MERGE_QUEUE_ROOT", tmp_path / "merge-queue")
    monkeypatch.setattr(program, "MASTER_ROOT", master_root)
    monkeypatch.setattr(program, "MASTER_LOG", master_root / "supervisor.log")
    monkeypatch.setattr(program, "MASTER_PID", master_pid)
    monkeypatch.setattr(program, "MASTER_IDENTITY", master_identity)
    pid = 4242
    logical_argv = tuple(
        program.supervisor_command(
            lanes=2,
            duration_seconds=float("inf"),
            detach=False,
            launch_token="c" * 32,
        )
    )
    argv = program._expanded_sealed_python_argv(logical_argv)
    snapshot = task_source.snapshot()
    execution_slice = program._master_execution_slice(logical_argv)
    _hold_snapshot, hold = program._manual_gate_hold_projection(task_source)
    actual = {
        "pid": pid,
        "boot_id": "boot-a",
        "start_ticks": 100,
        "cmdline_sha256": "sha256:abc",
        "argv": argv,
    }
    stored = {
        "schema": "ipfs_datasets_py/duckdb-quack-master-identity@2",
        "program_id": program.PROGRAM_ID,
        "repository_root": str(program.REPO_ROOT),
        "master_root": str(master_root),
        "master_pid_path": str(master_pid),
        "plan_root_cid": snapshot.plan_root_cid,
        "repository_tree_id": snapshot.repository_tree_id,
        "lane_count": 2,
        "execution_slice_sha256": program._execution_slice_digest(
            plan_root_cid=snapshot.plan_root_cid,
            repository_tree_id=snapshot.repository_tree_id,
            task_aliases=execution_slice,
            held_task_aliases=hold["held_task_aliases"],
            held_set_sha256=hold["held_set_sha256"],
        ),
        "execution_slice_task_count": len(execution_slice),
        "authorization_held_set_sha256": hold["held_set_sha256"],
        "authorization_held_task_count": len(hold["held_task_aliases"]),
        "python_environment_sha256": (
            "sha256:"
            + program._sha256_text(
                program._canonical_json(program._sealed_python_environment())
            )
        ),
        **{key: actual[key] for key in ("pid", "boot_id", "start_ticks", "cmdline_sha256")},
    }
    program._atomic_write_text(master_identity, json.dumps(stored))
    monkeypatch.setattr(program, "_pid_exists", lambda selected: selected == pid)
    monkeypatch.setattr(program, "_process_birth_identity", lambda selected: actual)
    process_environment = program._sealed_python_environment()
    monkeypatch.setattr(
        program,
        "_process_python_environment",
        lambda _pid: process_environment,
    )
    assert program._master_process_status(
        pid,
        expected_plan_root=snapshot.plan_root_cid,
        expected_repository_root=snapshot.repository_tree_id,
    ) == (True, "bound_process_live")

    process_environment = {
        **program._sealed_python_environment(),
        "LD_PRELOAD": "/tmp/foreign-loader.so",
    }
    assert program._master_process_status(pid) == (
        False,
        "master_python_environment_is_not_sealed",
    )
    process_environment = program._sealed_python_environment()

    actual["start_ticks"] = 101
    assert program._master_process_status(pid)[0] is False


def test_cli_rejects_unsafe_parallelism_and_monitor_windows() -> None:
    parser = program.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["launch", "--lanes", "3"])
    with pytest.raises(SystemExit):
        parser.parse_args(["launch", "--duration-seconds", "0"])
    with pytest.raises(SystemExit):
        parser.parse_args(["watch", "--no-progress-seconds", "100"])


def test_idle_shard_with_fresh_bound_supervisor_is_not_stale() -> None:
    idle_lane = {
        "active_task_id": "",
        "active_worker_count": 0,
        "stalled_without_active_worker": False,
        "selection_idle_reason": "no_shard_selectable_ready_tasks",
        "heartbeat_age_seconds": 1343.0,
        "status_age_seconds": 2.0,
        "daemon_bound": True,
        "supervisor_bound": True,
    }

    assert program._lane_is_expectedly_idle(idle_lane)
    assert not program._lane_task_heartbeat_is_stale(
        idle_lane,
        stale_seconds=1200,
    )

    unknown_idle = {**idle_lane, "selection_idle_reason": ""}
    assert program._lane_task_heartbeat_is_stale(
        unknown_idle,
        stale_seconds=1200,
    )

    active_attempt_limited = {
        **idle_lane,
        "selection_idle_reason": "all_selectable_ready_tasks_reached_max_task_attempts",
    }
    assert program._lane_task_heartbeat_is_stale(
        active_attempt_limited,
        stale_seconds=1200,
    )


def test_attempt_limit_projection_checks_display_and_canonical_ledgers() -> None:
    limited, divergences = program._attempt_limit_projection(
        {
            "implementation_attempts": {"DQK-001": 1, "DQK-002": 4},
            "implementation_attempts_by_cid": {
                "cid-001": 4,
                "cid-002": 4,
            },
        },
        task_alias_by_cid={"cid-001": "DQK-001", "cid-002": "DQK-002"},
        eligible_task_aliases={"DQK-001", "DQK-002"},
        max_attempts=4,
    )

    assert limited == ["DQK-001", "DQK-002"]
    assert divergences == [
        {
            "task_id": "DQK-001",
            "task_cids": ["cid-001"],
            "display_attempts": 1,
            "canonical_attempts": 4,
        }
    ]

    completed_limited, completed_divergences = program._attempt_limit_projection(
        {
            "implementation_attempts": {"DQK-001": 4},
            "implementation_attempts_by_cid": {
                "cid-001": 4,
                "cid:stale-generation": 99,
            },
        },
        task_alias_by_cid={"cid-001": "DQK-001"},
        eligible_task_aliases=set(),
        max_attempts=4,
    )
    assert completed_limited == []
    assert completed_divergences == []
