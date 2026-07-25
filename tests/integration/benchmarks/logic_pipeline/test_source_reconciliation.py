"""Integration evidence for source-fresh HSSL reassessment baselines."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Iterable

import pytest

from benchmarks.logic_pipeline import RunPaths
from benchmarks.logic_pipeline.contracts import canonical_json
from benchmarks.logic_pipeline.source_reconciliation import (
    DEFAULT_FRESH_PREDECESSOR_ARTIFACT_PATHS,
    DEFAULT_RECONCILED_MANIFEST_PATH,
    FRESH_SOURCE_BASELINE_SCHEMA,
    FreshSourceBaselineManifest,
    HSSLEV1134D84,
    REASSESSMENT_RUN_ID,
    SOURCE_RECONCILIATION_SCHEMA,
    SourceReconciledBaselineManifest,
    SourceReconciliationError,
    build_run_namespaces,
    canonical_reconciled_baseline_json,
    capture_recursive_gitlinks,
    compare_a0_outputs,
    create_fresh_source_baseline,
    environment_inventory_record,
    fresh_environment_inventory_record,
    load_fresh_source_baseline_manifest,
    load_reconciled_baseline_manifest,
    load_source_baseline_manifest,
    reconciled_baseline_sha256,
    write_fresh_source_baseline_manifest,
    write_reconciled_baseline_manifest,
)


ROOT = Path(__file__).resolve().parents[4]
V1_MANIFEST = (
    ROOT
    / "workspace/benchmarks/hammer-symai-spacy-leanstral"
    / "a0-baseline-v1/state/baseline-manifest.json"
)
V2_MANIFEST = ROOT / DEFAULT_RECONCILED_MANIFEST_PATH
V1_BYTES_SHA256 = (
    "063caddfa99fcb0307d59fdefb3a6313c194e1dc07054e92254b7d6dc2bca8fa"
)
IMMUTABLE_V1_ARTIFACTS = {
    V1_MANIFEST: V1_BYTES_SHA256,
    ROOT
    / "workspace/benchmarks/hammer-symai-spacy-leanstral/results"
    / "frontend-overlap-v1.json": (
        "5f4646679b3d58884a872378bb8adbc3770bf8491e9cd49b627adebaff8b31c2"
    ),
    ROOT
    / "workspace/benchmarks/hammer-symai-spacy-leanstral/results"
    / "holdout-evaluation-v1.json": (
        "7826db140c6cd722d141b775f69d0c431143307a27e07bbd621b88bc03b79e4a"
    ),
    ROOT
    / "workspace/benchmarks/hammer-symai-spacy-leanstral/results"
    / "pilot-shortlist-v1.json": (
        "0e702d4e19dbc242b445f4f6ef91647506ee4c0174072318098a6f6be2173e45"
    ),
    ROOT
    / "workspace/benchmarks/hammer-symai-spacy-leanstral/results"
    / "proof-overlap-ordering-v1.json": (
        "a8276ea6bd814b20c3e5407d77202e0b9b025de2f36b37e870d84e33d26fd35f"
    ),
    ROOT
    / "docs/performance_snapshots"
    / "2026-07-24_hammer_symai_spacy_leanstral_final_decision.json": (
        "0e53798d3f1deaab040cf99f10034644f421ffd51f15090a948aa7085041a84e"
    ),
}
V2_MANIFEST_SHA256 = (
    "6c7084db784022d81abc65148fb0d72a8046da881c4d4b448434b9b13af7e469"
)
NORMALIZED_PILOT_SHA256 = (
    "599e85c5c19c87c370cdf28f8a156ff5af3fc6f6c186028c963c84f659319b22"
)
FRESH_TEST_RUN_ID = "post-repair-source-test"


def _git(
    repository: Path,
    *arguments: str,
    check: bool = True,
    config: Iterable[str] = (),
) -> subprocess.CompletedProcess[str]:
    command = ["git", "-c", "core.autocrlf=false"]
    for item in config:
        command.extend(("-c", item))
    command.extend(("-C", str(repository), *arguments))
    return subprocess.run(
        command,
        check=check,
        capture_output=True,
        text=True,
        timeout=20,
        env={
            "PATH": os.environ.get("PATH", ""),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        },
    )


def _init_repository(path: Path) -> None:
    path.mkdir(parents=True)
    _git(path, "init", "--initial-branch=main")
    _git(path, "config", "user.name", "Source Reconciliation Tests")
    _git(path, "config", "user.email", "source-reconciliation@example.invalid")


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", "--all")
    _git(repository, "commit", "--no-gpg-sign", "-m", message)
    return _git(repository, "rev-parse", "HEAD").stdout.strip()


def _copy_published_predecessor_artifacts(repository: Path) -> None:
    for relative in DEFAULT_FRESH_PREDECESSOR_ARTIFACT_PATHS:
        destination = repository / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)


def _fresh_source_repository(tmp_path: Path) -> tuple[Path, str]:
    leaf = tmp_path / "leaf"
    _init_repository(leaf)
    (leaf / "leaf.txt").write_text("local leaf\n", encoding="utf-8")
    _commit(leaf, "local leaf")

    middle = tmp_path / "middle"
    _init_repository(middle)
    (middle / "middle.txt").write_text("local middle\n", encoding="utf-8")
    _git(
        middle,
        "submodule",
        "add",
        str(leaf),
        "deps/leaf",
        config=("protocol.file.allow=always",),
    )
    _commit(middle, "local nested dependency")

    source = tmp_path / "source"
    _init_repository(source)
    (source / "source.txt").write_text("repaired source\n", encoding="utf-8")
    _git(
        source,
        "submodule",
        "add",
        str(middle),
        "ipfs_accelerate_py",
        config=("protocol.file.allow=always",),
    )
    _git(
        source,
        "submodule",
        "add",
        str(middle),
        "ipfs_kit_py",
        config=("protocol.file.allow=always",),
    )
    _copy_published_predecessor_artifacts(source)
    commit = _commit(source, "repaired source and immutable predecessor")
    _git(
        source,
        "submodule",
        "update",
        "--init",
        "--recursive",
        "--checkout",
        config=("protocol.file.allow=always",),
    )
    return source, commit


def _create_fresh_manifest(
    tmp_path: Path,
) -> tuple[Path, RunPaths, FreshSourceBaselineManifest]:
    source, commit = _fresh_source_repository(tmp_path)
    paths = RunPaths.for_run(
        FRESH_TEST_RUN_ID,
        benchmark_root=tmp_path / "external-runs",
    )
    manifest = create_fresh_source_baseline(
        source,
        base_revision=commit,
        run_paths=paths,
        capability_inventory={
            "python": {"implementation": "cpython", "version": "3.12.3"},
            "platform": {"system": "Linux", "machine": "test-generic"},
            "capabilities": [
                {"kind": "spacy", "status": "available"},
                {"kind": "leanstral", "status": "available"},
            ],
        },
    )
    return source, paths, manifest


def _detached_source(paths: RunPaths) -> Path:
    return paths.worktrees / "source"


def _payload() -> dict[str, object]:
    return load_reconciled_baseline_manifest(V2_MANIFEST).to_dict()


def _fresh_payload() -> dict[str, object]:
    def rebind(value: object) -> object:
        if isinstance(value, dict):
            return {key: rebind(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rebind(item) for item in value]
        if isinstance(value, str):
            return value.replace(REASSESSMENT_RUN_ID, FRESH_TEST_RUN_ID)
        return value

    payload = rebind(_payload())
    assert isinstance(payload, dict)
    environment = payload["environment"]
    assert isinstance(environment, dict)
    environment["sha256"] = hashlib.sha256(
        canonical_json(environment["inventory"]).encode("utf-8")
    ).hexdigest()
    return payload


def _semantic_output(
    case_id: str,
    *,
    run_id: str,
    wall_time_ms: float,
    modal_ir_sha256: str = "a" * 64,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "case_id": case_id,
        "split": "pilot",
        "cache_mode": "cold",
        "variant_id": "A0",
        "status": "not_verified",
        "failure_code": None,
        "failure_detail": None,
        "kernel_accepted": False,
        "kernel_receipt_sha256": None,
        "verification_authority": "none",
        "stages": [
            {
                "stage": "compiler",
                "status": "success",
                "failure_code": None,
                "failure_detail": None,
                "kernel_accepted": False,
                "kernel_receipt_sha256": None,
                "output_sha256": "e" * 64,
                "data": {
                    "modal_ir_sha256": modal_ir_sha256,
                    "parser_name": "spacy_modal_codec_v1",
                },
                "provenance": {
                    "adapter_id": "a0-current-modal-codec",
                    "effective_identity": {
                        "spacy_effective_model": "spacy.blank:en",
                    },
                },
                "telemetry": {
                    "wall_time_ms": wall_time_ms,
                    "cpu_time_ms": wall_time_ms / 2,
                    "peak_memory_bytes": 1000,
                    "model_calls": 0,
                },
            }
        ],
    }


def test_checked_manifest_is_canonical_complete_and_source_fresh() -> None:
    manifest = load_reconciled_baseline_manifest(V2_MANIFEST)
    payload = manifest.to_dict()
    source = payload["source"]
    reconciliation = payload["reconciliation"]

    assert manifest.digest == V2_MANIFEST_SHA256
    assert reconciled_baseline_sha256(manifest) == V2_MANIFEST_SHA256
    assert payload["schema"] == SOURCE_RECONCILIATION_SCHEMA
    assert payload["evidence"] == HSSLEV1134D84()
    assert payload["run_id"] == REASSESSMENT_RUN_ID
    assert payload["predecessor"]["manifest_sha256"] == (
        "6b37a6493d6328102b558258843218128ad0bf6f8cc7be13f8d0c2e0bb61e156"
    )
    assert payload["predecessor"]["immutable"] is True
    assert source["repository_commit"] == (
        "3e053f6edece026fef48c153aa5c4d62a50da3d2"
    )
    assert source["detached"] is True
    assert len(manifest.recursive_gitlinks) == 20
    assert [item.path for item in manifest.recursive_gitlinks] == sorted(
        item.path for item in manifest.recursive_gitlinks
    )
    assert {
        item.path: item.commit for item in manifest.recursive_gitlinks
    }["ipfs_accelerate_py"] == (
        "0c27224e02b91ebd102647f93781ca2b27e9cd88"
    )
    assert reconciliation["coordinate_count"] == 20
    assert reconciliation["predecessor_sha256"] == NORMALIZED_PILOT_SHA256
    assert reconciliation["fresh_sha256"] == NORMALIZED_PILOT_SHA256
    assert reconciliation["equivalent"] is True
    assert reconciliation["unexplained_drift"] == []
    assert payload["environment"]["source_commit"] == source["repository_commit"]
    assert payload["environment"]["run_id"] == REASSESSMENT_RUN_ID
    assert V2_MANIFEST.read_bytes() == (
        canonical_reconciled_baseline_json(manifest) + "\n"
    ).encode("utf-8")


def test_v1_manifest_remains_byte_exact_historical_evidence() -> None:
    assert {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in IMMUTABLE_V1_ARTIFACTS
    } == IMMUTABLE_V1_ARTIFACTS
    payload = json.loads(V1_MANIFEST.read_text(encoding="utf-8"))

    assert payload["schema"].endswith("frozen-baseline-manifest.v1")
    assert payload["source"]["repository_commit"] == (
        "2a1be00b1b76e6652c25d418752affbf0f85d176"
    )
    assert next(
        item
        for item in payload["source"]["submodules"]
        if item["path"] == "ipfs_accelerate_py"
    )["commit"] == "d3db5eea637a69c2e919b1c850f0f0089071cbcb"


def test_recursive_gitlinks_come_from_pinned_trees_not_active_heads(
    tmp_path: Path,
) -> None:
    leaf = tmp_path / "leaf"
    _init_repository(leaf)
    (leaf / "identity.txt").write_text("leaf v1\n", encoding="utf-8")
    leaf_v1 = _commit(leaf, "leaf v1")

    middle = tmp_path / "middle"
    _init_repository(middle)
    (middle / "middle.txt").write_text("middle\n", encoding="utf-8")
    _git(
        middle,
        "submodule",
        "add",
        str(leaf),
        "deps/nested leaf",
        config=("protocol.file.allow=always",),
    )
    middle_v1 = _commit(middle, "middle with leaf")

    root = tmp_path / "root"
    _init_repository(root)
    (root / "root.txt").write_text("root\n", encoding="utf-8")
    _git(
        root,
        "submodule",
        "add",
        str(middle),
        "vendor/middle",
        config=("protocol.file.allow=always",),
    )
    root_v1 = _commit(root, "root with nested dependency")
    _git(
        root,
        "submodule",
        "update",
        "--init",
        "--recursive",
        config=("protocol.file.allow=always",),
    )

    # Advance both source repositories and the checked-out child without
    # changing root_v1.  Capture must still traverse root_v1 -> middle_v1 ->
    # leaf_v1 rather than report the ambient branch heads.
    (leaf / "identity.txt").write_text("leaf v2\n", encoding="utf-8")
    leaf_v2 = _commit(leaf, "leaf v2")
    middle_leaf = middle / "deps/nested leaf"
    _git(middle_leaf, "fetch", "origin")
    _git(middle_leaf, "checkout", "--detach", leaf_v2)
    middle_v2 = _commit(middle, "middle pins leaf v2")
    root_middle = root / "vendor/middle"
    _git(root_middle, "fetch", "origin")
    _git(root_middle, "checkout", "--detach", middle_v2)

    links = capture_recursive_gitlinks(root, root_v1)

    assert [(item.path, item.commit, item.depth) for item in links] == [
        ("vendor/middle", middle_v1, 1),
        ("vendor/middle/deps/nested leaf", leaf_v1, 2),
    ]


def test_uninitialized_nested_repository_fails_closed(tmp_path: Path) -> None:
    dependency = tmp_path / "dependency"
    _init_repository(dependency)
    (dependency / "tracked.txt").write_text("dependency\n", encoding="utf-8")
    _commit(dependency, "dependency")

    root = tmp_path / "root"
    _init_repository(root)
    _git(
        root,
        "submodule",
        "add",
        str(dependency),
        "vendor/dependency",
        config=("protocol.file.allow=always",),
    )
    revision = _commit(root, "add dependency")
    clone = tmp_path / "uninitialized"
    _git(
        tmp_path,
        "clone",
        "--no-checkout",
        str(root),
        str(clone),
        config=("protocol.file.allow=always",),
    )
    _git(clone, "checkout", revision)

    with pytest.raises(SourceReconciliationError, match="partial|inspect"):
        capture_recursive_gitlinks(clone, revision)

    partial = capture_recursive_gitlinks(
        clone, revision, require_complete=False
    )
    assert [(item.path, item.commit) for item in partial] == [
        (
            "vendor/dependency",
            _git(dependency, "rev-parse", "HEAD").stdout.strip(),
        )
    ]


def test_normalized_output_comparison_ignores_only_run_volatile_fields() -> None:
    case_ids = ("pilot-p01", "pilot-p02")
    old = [
        _semantic_output(case_id, run_id="a0-baseline-v1", wall_time_ms=1.0)
        for case_id in case_ids
    ]
    fresh = [
        _semantic_output(case_id, run_id="reassessment-v2", wall_time_ms=99.0)
        for case_id in case_ids
    ]

    comparison = compare_a0_outputs(
        old, fresh, expected_case_ids=case_ids
    )

    assert comparison["equivalent"] is True
    assert comparison["predecessor_sha256"] == comparison["fresh_sha256"]
    assert comparison["coordinate_count"] == 2


@pytest.mark.parametrize(
    "mutation",
    ("semantic", "status", "missing", "reordered"),
)
def test_normalized_output_drift_fails_closed(
    mutation: str,
) -> None:
    case_ids = ("pilot-p01", "pilot-p02")
    old = [
        _semantic_output(case_id, run_id="old", wall_time_ms=1.0)
        for case_id in case_ids
    ]
    fresh = [
        _semantic_output(case_id, run_id="fresh", wall_time_ms=2.0)
        for case_id in case_ids
    ]
    if mutation == "semantic":
        fresh[0]["stages"][0]["data"]["modal_ir_sha256"] = "b" * 64
    elif mutation == "status":
        fresh[0]["status"] = "infrastructure_failure"
    elif mutation == "missing":
        fresh.pop()
    else:
        fresh.reverse()

    with pytest.raises(SourceReconciliationError, match="drift|complete ordered"):
        compare_a0_outputs(old, fresh, expected_case_ids=case_ids)


def test_all_mutable_namespaces_are_v2_scoped_and_disjoint(
    tmp_path: Path,
) -> None:
    paths = RunPaths.for_run(
        REASSESSMENT_RUN_ID,
        benchmark_root=tmp_path / "state-root",
    )
    namespaces = build_run_namespaces(paths, protocol_sha256="c" * 64)
    cache = namespaces["cache"]
    filesystem = [
        namespaces[name]
        for name in (
            "state",
            "results",
            "receipts",
            "worktree",
            "process",
        )
    ]

    assert len(filesystem) == len(set(filesystem))
    assert all(REASSESSMENT_RUN_ID in value for value in filesystem)
    assert cache["cold"] != cache["warm"]
    assert all(
        REASSESSMENT_RUN_ID in cache[name]
        for name in ("root", "cold", "warm")
    )
    assert "a0-baseline-v1" not in canonical_json(namespaces)


def test_environment_inventory_is_source_bound_and_rejects_credentials() -> None:
    commit = "d" * 40
    record = environment_inventory_record(
        {"python": {"version": "3.12.3"}, "status": "pre-repair"},
        run_id=REASSESSMENT_RUN_ID,
        source_commit=commit,
    )

    assert record["run_id"] == REASSESSMENT_RUN_ID
    assert record["source_commit"] == commit
    assert record["sha256"] == hashlib.sha256(
        canonical_json(record["inventory"]).encode("utf-8")
    ).hexdigest()
    with pytest.raises(SourceReconciliationError, match="credential"):
        environment_inventory_record(
            {"api_token": "must-not-be-serialized"},
            run_id=REASSESSMENT_RUN_ID,
            source_commit=commit,
        )


def test_manifest_rejects_tampering_duplicate_keys_and_noncanonical_json(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["reconciliation"]["fresh_sha256"] = "f" * 64
    tampered = tmp_path / "tampered.json"
    tampered.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    with pytest.raises(SourceReconciliationError, match="equivalence"):
        load_reconciled_baseline_manifest(tampered)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schema":"one","schema":"two"}\n',
        encoding="utf-8",
    )
    with pytest.raises(SourceReconciliationError, match="duplicate"):
        load_reconciled_baseline_manifest(duplicate)

    noncanonical = tmp_path / "noncanonical.json"
    noncanonical.write_text(
        json.dumps(_payload(), indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SourceReconciliationError, match="canonical"):
        load_reconciled_baseline_manifest(noncanonical)


def test_manifest_is_deeply_immutable_and_writer_is_exclusive(
    tmp_path: Path,
) -> None:
    published = load_reconciled_baseline_manifest(V2_MANIFEST)
    destination = tmp_path / "state" / "baseline-manifest.json"

    with pytest.raises(
        SourceReconciliationError,
        match="published immutable evidence",
    ):
        write_reconciled_baseline_manifest(
            published,
            destination,
            run_id=REASSESSMENT_RUN_ID,
        )
    manifest = SourceReconciledBaselineManifest(_fresh_payload())
    write_reconciled_baseline_manifest(
        manifest,
        destination,
        run_id=FRESH_TEST_RUN_ID,
    )

    assert (
        load_reconciled_baseline_manifest(
            destination,
            expected_run_id=FRESH_TEST_RUN_ID,
        ).digest
        == manifest.digest
    )
    with pytest.raises(SourceReconciliationError, match="overwrite"):
        write_reconciled_baseline_manifest(
            manifest,
            destination,
            run_id=FRESH_TEST_RUN_ID,
        )
    with pytest.raises(TypeError):
        manifest.payload["run_id"] = "changed"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        manifest.payload = {}  # type: ignore[misc]


def test_manifest_constructor_rejects_namespace_collision() -> None:
    payload = _payload()
    payload["namespaces"]["process"] = payload["namespaces"]["results"]

    with pytest.raises(SourceReconciliationError, match="collide"):
        SourceReconciledBaselineManifest(payload)


def test_fresh_repaired_source_baseline_is_external_local_only_and_matrix_deferred(
    tmp_path: Path,
) -> None:
    source, paths, manifest = _create_fresh_manifest(tmp_path)
    destination = paths.state / "baseline-manifest.json"
    detached = _detached_source(paths)
    loaded = load_fresh_source_baseline_manifest(
        destination,
        expected_run_id=FRESH_TEST_RUN_ID,
        repository_root=detached,
        benchmark_root=paths.benchmark_root,
    )
    common = load_source_baseline_manifest(
        destination,
        expected_run_id=FRESH_TEST_RUN_ID,
        repository_root=detached,
        benchmark_root=paths.benchmark_root,
    )
    payload = loaded.to_dict()

    assert loaded.digest == manifest.digest == common.digest
    assert payload["schema"] == FRESH_SOURCE_BASELINE_SCHEMA
    assert payload["control"] == {
        "variant_id": "A0",
        "definition": "repaired_source_within_run_control",
        "historical_a0_equivalence_claimed": False,
        "reason": (
            "repaired_environment_and_code_define_a_new_within_run_A0_control"
        ),
    }
    assert payload["behavior_comparison"] == {
        "status": "deferred",
        "authority": "complete_source_bound_matrix",
        "scope": "all_frozen_non_holdout_coordinates",
        "source_commit": payload["source"]["worktree_commit"],
    }
    assert payload["predecessor"]["run_id"] == REASSESSMENT_RUN_ID
    assert payload["predecessor"]["immutable"] is True
    assert [
        item["path"] for item in payload["predecessor"]["artifacts"]
    ] == [
        path.as_posix() for path in DEFAULT_FRESH_PREDECESSOR_ARTIFACT_PATHS
    ]
    assert [(item.path, item.depth) for item in loaded.recursive_gitlinks] == [
        ("ipfs_accelerate_py", 1),
        ("ipfs_accelerate_py/deps/leaf", 2),
        ("ipfs_kit_py", 1),
    ]
    assert payload["source"]["local_only_gitlinks"] is True
    assert destination.resolve().is_relative_to(paths.run_root.resolve())
    assert not (source / "state" / "baseline-manifest.json").exists()
    assert _git(source, "status", "--porcelain=v1").stdout == ""

    for item in loaded.recursive_gitlinks:
        if item.depth != 1:
            continue
        materialized = paths.worktrees / "source" / item.path
        local_source = source / item.path
        origin = _git(
            materialized,
            "config",
            "--get",
            "remote.origin.url",
        ).stdout.strip()
        assert Path(origin).resolve() == local_source.resolve()
        assert _git(
            materialized,
            "symbolic-ref",
            "--quiet",
            "HEAD",
            check=False,
        ).returncode != 0
    assert not (
        detached / "ipfs_accelerate_py" / "deps" / "leaf" / ".git"
    ).exists()
    assert all(
        item.path != "ipfs_kit_py/deps/leaf"
        for item in loaded.recursive_gitlinks
    )

    forbidden = source / "fresh-baseline.json"
    with pytest.raises(SourceReconciliationError, match="external run root"):
        write_fresh_source_baseline_manifest(
            manifest,
            forbidden,
            run_id=FRESH_TEST_RUN_ID,
            repository_root=source,
            benchmark_root=paths.benchmark_root,
        )
    assert not forbidden.exists()


def test_fresh_source_baseline_fails_closed_on_semantic_and_byte_tampering(
    tmp_path: Path,
) -> None:
    source, paths, _manifest = _create_fresh_manifest(tmp_path)
    detached = _detached_source(paths)
    destination = paths.state / "baseline-manifest.json"
    original_manifest = destination.read_bytes()
    original_payload = json.loads(original_manifest)

    def assert_rejected(payload: dict[str, object], match: str) -> None:
        destination.write_text(
            canonical_json(payload) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(SourceReconciliationError, match=match):
            load_fresh_source_baseline_manifest(
                destination,
                expected_run_id=FRESH_TEST_RUN_ID,
                repository_root=detached,
                benchmark_root=paths.benchmark_root,
            )
        destination.write_bytes(original_manifest)

    payload = json.loads(json.dumps(original_payload))
    payload["control"]["historical_a0_equivalence_claimed"] = True
    assert_rejected(payload, "must not claim historical equivalence")

    payload = json.loads(json.dumps(original_payload))
    payload["behavior_comparison"]["status"] = "complete"
    assert_rejected(payload, "deferred")

    payload = json.loads(json.dumps(original_payload))
    payload["environment"]["inventory"]["note"] = "ghp_" + ("x" * 32)
    payload["environment"]["sha256"] = hashlib.sha256(
        canonical_json(payload["environment"]["inventory"]).encode("utf-8")
    ).hexdigest()
    assert_rejected(payload, "credential-shaped")

    payload = json.loads(json.dumps(original_payload))
    payload["predecessor"]["artifacts"][0]["bytes_sha256"] = "f" * 64
    payload["predecessor"]["artifacts_sha256"] = hashlib.sha256(
        canonical_json(payload["predecessor"]["artifacts"]).encode("utf-8")
    ).hexdigest()
    assert_rejected(payload, "artifact bytes drifted")

    receipt = paths.receipts / "worktree-safety.json"
    original_receipt = receipt.read_bytes()
    receipt.write_bytes(original_receipt + b" ")
    with pytest.raises(
        SourceReconciliationError,
        match="newline-terminated|canonical JSON",
    ):
        load_fresh_source_baseline_manifest(
            destination,
            expected_run_id=FRESH_TEST_RUN_ID,
            repository_root=detached,
            benchmark_root=paths.benchmark_root,
        )
    receipt.write_bytes(original_receipt)

    predecessor_artifact = (
        detached / DEFAULT_FRESH_PREDECESSOR_ARTIFACT_PATHS[0]
    )
    original_artifact = predecessor_artifact.read_bytes()
    predecessor_artifact.write_bytes(original_artifact + b"\n")
    with pytest.raises(
        SourceReconciliationError,
        match="must be clean|artifact bytes drifted",
    ):
        load_fresh_source_baseline_manifest(
            destination,
            expected_run_id=FRESH_TEST_RUN_ID,
            repository_root=detached,
            benchmark_root=paths.benchmark_root,
        )
    predecessor_artifact.write_bytes(original_artifact)


def test_fresh_loader_requires_exact_clean_detached_materialized_source(
    tmp_path: Path,
) -> None:
    source, paths, manifest = _create_fresh_manifest(tmp_path)
    detached = _detached_source(paths)
    destination = paths.state / "baseline-manifest.json"

    with pytest.raises(SourceReconciliationError, match="exactly name"):
        load_fresh_source_baseline_manifest(
            destination,
            expected_run_id=FRESH_TEST_RUN_ID,
            repository_root=source,
            benchmark_root=paths.benchmark_root,
        )

    top_dirty = detached / "untracked-live-file.txt"
    top_dirty.write_text("dirty\n", encoding="utf-8")
    with pytest.raises(SourceReconciliationError, match="source worktree.*clean"):
        load_fresh_source_baseline_manifest(
            destination,
            expected_run_id=FRESH_TEST_RUN_ID,
            repository_root=detached,
            benchmark_root=paths.benchmark_root,
        )
    top_dirty.unlink()

    submodule = detached / "ipfs_kit_py"
    child_dirty = submodule / "untracked-child-file.txt"
    child_dirty.write_text("dirty\n", encoding="utf-8")
    with pytest.raises(SourceReconciliationError, match="submodule worktree.*clean"):
        load_fresh_source_baseline_manifest(
            destination,
            expected_run_id=FRESH_TEST_RUN_ID,
            repository_root=detached,
            benchmark_root=paths.benchmark_root,
        )
    child_dirty.unlink()

    _git(submodule, "switch", "--create", "tampered-live-branch")
    with pytest.raises(SourceReconciliationError, match="submodule HEAD.*detached"):
        load_fresh_source_baseline_manifest(
            destination,
            expected_run_id=FRESH_TEST_RUN_ID,
            repository_root=detached,
            benchmark_root=paths.benchmark_root,
        )
    child_commit = next(
        item.commit
        for item in manifest.recursive_gitlinks
        if item.path == "ipfs_kit_py"
    )
    _git(submodule, "checkout", "--detach", child_commit)

    _git(detached, "switch", "--create", "tampered-live-root")
    with pytest.raises(SourceReconciliationError, match="HEAD must remain detached"):
        load_fresh_source_baseline_manifest(
            destination,
            expected_run_id=FRESH_TEST_RUN_ID,
            repository_root=detached,
            benchmark_root=paths.benchmark_root,
        )


def test_fresh_creation_rejects_dirty_source_before_creating_run_state(
    tmp_path: Path,
) -> None:
    source, commit = _fresh_source_repository(tmp_path)
    dirty = source / "untracked-source-file.txt"
    dirty.write_text("dirty\n", encoding="utf-8")
    paths = RunPaths.for_run(
        FRESH_TEST_RUN_ID,
        benchmark_root=tmp_path / "external-runs",
    )

    with pytest.raises(SourceReconciliationError, match="source checkout.*clean"):
        create_fresh_source_baseline(
            source,
            base_revision=commit,
            run_paths=paths,
            capability_inventory={},
        )
    assert not paths.run_root.exists()


def test_fresh_paths_reject_symlinked_root_state_and_manifest(
    tmp_path: Path,
) -> None:
    source, commit = _fresh_source_repository(tmp_path / "root-alias-case")
    real_root = tmp_path / "real-external-root"
    real_root.mkdir()
    root_alias = tmp_path / "external-root-alias"
    root_alias.symlink_to(real_root, target_is_directory=True)
    aliased_paths = RunPaths.for_run(
        FRESH_TEST_RUN_ID,
        benchmark_root=root_alias,
    )
    with pytest.raises(SourceReconciliationError, match="symlink"):
        create_fresh_source_baseline(
            source,
            base_revision=commit,
            run_paths=aliased_paths,
            capability_inventory={},
        )
    assert not (real_root / FRESH_TEST_RUN_ID).exists()

    source_two, commit_two = _fresh_source_repository(
        tmp_path / "state-alias-case"
    )
    state_paths = RunPaths.for_run(
        FRESH_TEST_RUN_ID,
        benchmark_root=tmp_path / "state-external-root",
    )
    state_paths.run_root.mkdir(parents=True)
    outside_state = tmp_path / "outside-state"
    outside_state.mkdir()
    state_paths.state.symlink_to(outside_state, target_is_directory=True)
    with pytest.raises(SourceReconciliationError, match="symlink"):
        create_fresh_source_baseline(
            source_two,
            base_revision=commit_two,
            run_paths=state_paths,
            capability_inventory={},
        )
    assert list(outside_state.iterdir()) == []

    _source_three, manifest_paths, _manifest = _create_fresh_manifest(
        tmp_path / "manifest-alias-case"
    )
    destination = manifest_paths.state / "baseline-manifest.json"
    original = destination.read_bytes()
    destination.unlink()
    outside_manifest = tmp_path / "outside-manifest.json"
    outside_manifest.write_bytes(original)
    destination.symlink_to(outside_manifest)
    with pytest.raises(SourceReconciliationError, match="symlink"):
        load_fresh_source_baseline_manifest(
            destination,
            expected_run_id=FRESH_TEST_RUN_ID,
            repository_root=_detached_source(manifest_paths),
            benchmark_root=manifest_paths.benchmark_root,
        )


def test_common_loader_preserves_published_v2_and_rejects_it_for_fresh_runs(
    tmp_path: Path,
) -> None:
    before = V2_MANIFEST.read_bytes()
    published = load_source_baseline_manifest(
        V2_MANIFEST,
        expected_run_id=REASSESSMENT_RUN_ID,
    )

    assert isinstance(published, SourceReconciledBaselineManifest)
    assert published.digest == V2_MANIFEST_SHA256
    assert V2_MANIFEST.read_bytes() == before

    historical_fresh = tmp_path / "historical-fresh.json"
    historical_fresh.write_text(
        canonical_json(_fresh_payload()) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        SourceReconciliationError,
        match="historical A0 equivalence cannot authorize",
    ):
        load_source_baseline_manifest(
            historical_fresh,
            expected_run_id=FRESH_TEST_RUN_ID,
            repository_root=ROOT,
            benchmark_root=tmp_path / "external-runs",
        )


def test_fresh_generic_inventory_rejects_credential_shaped_values() -> None:
    with pytest.raises(SourceReconciliationError, match="credential-shaped"):
        fresh_environment_inventory_record(
            {"diagnostic": "sk-" + ("q" * 32)},
            run_id=FRESH_TEST_RUN_ID,
            source_commit="d" * 40,
        )
