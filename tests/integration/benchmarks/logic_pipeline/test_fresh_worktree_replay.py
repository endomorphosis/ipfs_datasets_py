from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from benchmarks.logic_pipeline import RunPaths
from benchmarks.logic_pipeline.capabilities import prepare_isolated_worktree
from benchmarks.logic_pipeline.contracts import canonical_json
from benchmarks.logic_pipeline.holdout_execution import (
    HSSLEV1167A17,
    HOLDOUT_EXECUTION_RECEIPT_SCHEMA,
    HoldoutExecutionReceipt,
)
from benchmarks.logic_pipeline.replay import (
    ReplayError,
    ReplayReceipt,
    ReplayRequest,
    run_detached_replay,
)


ENVIRONMENT_SHA256 = hashlib.sha256(b"pinned replay environment").hexdigest()


def _git(
    repository: Path, *arguments: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
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


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, str]:
    checkout = tmp_path / "active-checkout"
    checkout.mkdir()
    _git(checkout, "init", "--initial-branch=main")
    _git(checkout, "config", "user.name", "Replay Tests")
    _git(checkout, "config", "user.email", "replay@example.invalid")
    (checkout / "source.txt").write_text("pinned source\n", encoding="utf-8")
    _git(checkout, "add", "--all")
    _git(checkout, "commit", "--no-gpg-sign", "-m", "pinned source")
    commit = _git(checkout, "rev-parse", "HEAD").stdout.strip()
    (checkout / "operator-notes.txt").write_text(
        "untracked operator work\n", encoding="utf-8"
    )
    return checkout, commit


@pytest.fixture
def repository_with_submodule(
    tmp_path: Path,
) -> tuple[Path, str, str]:
    dependency = tmp_path / "dependency-source"
    dependency.mkdir()
    _git(dependency, "init", "--initial-branch=main")
    _git(dependency, "config", "user.name", "Replay Tests")
    _git(dependency, "config", "user.email", "replay@example.invalid")
    (dependency / "dependency.txt").write_text(
        "pinned dependency\n",
        encoding="utf-8",
    )
    _git(dependency, "add", "--all")
    _git(
        dependency,
        "commit",
        "--no-gpg-sign",
        "-m",
        "pinned dependency",
    )

    checkout = tmp_path / "active-checkout-with-submodule"
    checkout.mkdir()
    _git(checkout, "init", "--initial-branch=main")
    _git(checkout, "config", "user.name", "Replay Tests")
    _git(checkout, "config", "user.email", "replay@example.invalid")
    (checkout / "source.txt").write_text("pinned source\n", encoding="utf-8")
    _git(checkout, "add", "--all")
    _git(checkout, "commit", "--no-gpg-sign", "-m", "pinned source")
    _git(
        checkout,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "--name",
        "fixture-dependency",
        dependency.as_posix(),
        "vendor/dependency",
    )
    _git(checkout, "commit", "--no-gpg-sign", "-am", "pin dependency")
    commit = _git(checkout, "rev-parse", "HEAD").stdout.strip()
    pinned_dependency = _git(
        checkout / "vendor" / "dependency",
        "rev-parse",
        "HEAD",
    ).stdout.strip()
    (checkout / "operator-notes.txt").write_text(
        "untracked operator work\n",
        encoding="utf-8",
    )
    return checkout, commit, pinned_dependency


def _execution_receipt(
    *, run_id: str, source_commit: str, cache_namespace: str
) -> HoldoutExecutionReceipt:
    payload = {
        "schema": HOLDOUT_EXECUTION_RECEIPT_SCHEMA,
        "evidence": HSSLEV1167A17(),
        "run_id": run_id,
        "source_commit": source_commit,
        "environment_sha256": ENVIRONMENT_SHA256,
        "authorization_sha256": "1" * 64,
        "pilot_gate_sha256": "2" * 64,
        "plan_sha256": "3" * 64,
        "access_audit_sha256s": ["4" * 64],
        "result_sha256s": ["5" * 64],
        "cache_namespaces": [cache_namespace],
        "executed_job_ids": ["job-source-a0-cold"],
        "complete": True,
    }
    return HoldoutExecutionReceipt(
        schema=payload["schema"],
        evidence=payload["evidence"],
        run_id=payload["run_id"],
        source_commit=payload["source_commit"],
        environment_sha256=payload["environment_sha256"],
        authorization_sha256=payload["authorization_sha256"],
        pilot_gate_sha256=payload["pilot_gate_sha256"],
        plan_sha256=payload["plan_sha256"],
        access_audit_sha256s=tuple(payload["access_audit_sha256s"]),
        result_sha256s=tuple(payload["result_sha256s"]),
        cache_namespaces=tuple(payload["cache_namespaces"]),
        executed_job_ids=tuple(payload["executed_job_ids"]),
        complete=True,
        receipt_sha256=hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest(),
    )


def _source_evidence(
    checkout: Path, commit: str, tmp_path: Path
):
    source_run_id = "authorized-holdout-source"
    source_cache = (
        "hammer-symai-spacy-leanstral/protocol-v1/"
        f"run/{source_run_id}/protocol/{'6' * 64}/"
        "variant/A0/split/holdout/cache/cold"
    )
    paths = RunPaths.for_run(
        source_run_id, benchmark_root=tmp_path / "source-state"
    )
    worktree = prepare_isolated_worktree(
        checkout, run_paths=paths, base_revision=commit
    )
    receipt = _execution_receipt(
        run_id=source_run_id,
        source_commit=commit,
        cache_namespace=source_cache,
    )
    return receipt, worktree, source_cache


def _request(
    source_receipt: HoldoutExecutionReceipt,
    source_worktree,
    source_cache: str,
    *,
    replay_run_id: str = "detached-replay-v2",
    script: str | None = None,
) -> ReplayRequest:
    replay_cache = source_cache.replace(
        f"/run/{source_receipt.run_id}/", f"/run/{replay_run_id}/"
    )
    if script is None:
        script = (
            "import json, os; from pathlib import Path; "
            "Path(os.environ['HSSL_REPLAY_EVIDENCE_PATH']).write_text("
            "json.dumps({'cache': os.environ['HSSL_CACHE_NAMESPACE'], "
            "'process': os.environ['HSSL_PROCESS_NAMESPACE'], "
            "'run': os.environ['HSSL_RUN_ID']}, sort_keys=True) + '\\n', "
            "encoding='utf-8')"
        )
    return ReplayRequest.create(
        source_run_id=source_receipt.run_id,
        replay_run_id=replay_run_id,
        source_commit=source_receipt.source_commit,
        environment_sha256=source_receipt.environment_sha256,
        source_execution_receipt_sha256=source_receipt.receipt_sha256,
        source_worktree_receipt_sha256=source_worktree.sha256,
        source_process_namespace="process-authorized-holdout",
        replay_process_namespace="process-detached-replay",
        source_cache_namespaces=source_receipt.cache_namespaces,
        replay_cache_namespace=replay_cache,
        command=(sys.executable, "-c", script),
        timeout_seconds=20,
    )


def _active_snapshot(checkout: Path) -> tuple[str, str, bytes]:
    return (
        _git(checkout, "rev-parse", "HEAD").stdout,
        _git(
            checkout, "status", "--porcelain=v1", "--untracked-files=all"
        ).stdout,
        (checkout / "operator-notes.txt").read_bytes(),
    )


def test_replay_runs_in_fresh_detached_worktree_and_namespaces(
    repository: tuple[Path, str], tmp_path: Path
) -> None:
    checkout, commit = repository
    source, source_worktree, source_cache = _source_evidence(
        checkout, commit, tmp_path
    )
    request = _request(source, source_worktree, source_cache)
    before = _active_snapshot(checkout)
    benchmark_root = tmp_path / "replay-state"

    receipt, worktree = run_detached_replay(
        checkout,
        source,
        source_worktree,
        request,
        benchmark_root=benchmark_root,
        actual_environment_sha256=ENVIRONMENT_SHA256,
    )

    assert callable(HSSLEV1167A17)
    assert receipt.replay_run_id == request.replay_run_id
    assert receipt.source_run_id == source.run_id
    assert receipt.source_commit == commit
    assert receipt.process_namespace == request.replay_process_namespace
    assert receipt.cache_namespace == request.replay_cache_namespace
    assert receipt.detached is True
    assert receipt.auto_merge is False
    assert worktree.worktree_commit == commit
    assert worktree.worktree_root.is_relative_to(worktree.state_root)
    assert (
        _git(
            worktree.worktree_root,
            "symbolic-ref",
            "--quiet",
            "HEAD",
            check=False,
        ).returncode
        != 0
    )
    assert ReplayRequest.from_dict(request.to_dict()) == request
    assert ReplayReceipt.from_dict(receipt.to_dict()) == receipt
    assert (
        benchmark_root
        / request.replay_run_id
        / "receipts"
        / "detached-replay-receipt.json"
    ).is_file()
    evidence = json.loads(
        (
            benchmark_root
            / request.replay_run_id
            / "results"
            / "replay-evidence.json"
        ).read_text(encoding="utf-8")
    )
    assert evidence == {
        "cache": request.replay_cache_namespace,
        "process": request.replay_process_namespace,
        "run": request.replay_run_id,
    }
    assert _active_snapshot(checkout) == before


@pytest.mark.parametrize(
    "actual_environment",
    ("0" * 64, "f" * 64),
)
def test_environment_drift_fails_before_replay_state_creation(
    repository: tuple[Path, str],
    tmp_path: Path,
    actual_environment: str,
) -> None:
    checkout, commit = repository
    source, source_worktree, source_cache = _source_evidence(
        checkout, commit, tmp_path
    )
    request = _request(source, source_worktree, source_cache)
    replay_root = tmp_path / "replay-state"
    before = _active_snapshot(checkout)

    with pytest.raises(ReplayError, match="stale"):
        run_detached_replay(
            checkout,
            source,
            source_worktree,
            request,
            benchmark_root=replay_root,
            actual_environment_sha256=actual_environment,
        )

    assert not (replay_root / request.replay_run_id).exists()
    assert _active_snapshot(checkout) == before


def test_same_run_process_or_cache_namespace_is_rejected(
    repository: tuple[Path, str], tmp_path: Path
) -> None:
    checkout, commit = repository
    source, source_worktree, source_cache = _source_evidence(
        checkout, commit, tmp_path
    )
    base = _request(source, source_worktree, source_cache).to_dict()

    same_run = dict(base)
    same_run["replay_run_id"] = source.run_id
    same_run.pop("request_sha256")
    with pytest.raises(ReplayError, match="fresh run"):
        ReplayRequest.create(
            **{
                key: value
                for key, value in same_run.items()
                if key != "schema"
            }
        )

    with pytest.raises(ReplayError, match="fresh process"):
        ReplayRequest.create(
            source_run_id=source.run_id,
            replay_run_id="other-replay",
            source_commit=commit,
            environment_sha256=ENVIRONMENT_SHA256,
            source_execution_receipt_sha256=source.receipt_sha256,
            source_worktree_receipt_sha256=source_worktree.sha256,
            source_process_namespace="same-process",
            replay_process_namespace="same-process",
            source_cache_namespaces=source.cache_namespaces,
            replay_cache_namespace=source_cache.replace(
                f"/run/{source.run_id}/", "/run/other-replay/"
            ),
            command=(sys.executable, "-c", "pass"),
        )

    with pytest.raises(ReplayError, match="fresh replay-run cold"):
        ReplayRequest.create(
            source_run_id=source.run_id,
            replay_run_id="other-replay",
            source_commit=commit,
            environment_sha256=ENVIRONMENT_SHA256,
            source_execution_receipt_sha256=source.receipt_sha256,
            source_worktree_receipt_sha256=source_worktree.sha256,
            source_process_namespace="source-process",
            replay_process_namespace="other-process",
            source_cache_namespaces=source.cache_namespaces,
            replay_cache_namespace=source_cache,
            command=(sys.executable, "-c", "pass"),
        )


def test_stale_source_worktree_and_reused_replay_run_fail_closed(
    repository: tuple[Path, str], tmp_path: Path
) -> None:
    checkout, commit = repository
    source, source_worktree, source_cache = _source_evidence(
        checkout, commit, tmp_path
    )
    request = _request(source, source_worktree, source_cache)
    replay_root = tmp_path / "replay-state"

    run_detached_replay(
        checkout,
        source,
        source_worktree,
        request,
        benchmark_root=replay_root,
        actual_environment_sha256=ENVIRONMENT_SHA256,
    )
    with pytest.raises(ReplayError, match="already exists"):
        run_detached_replay(
            checkout,
            source,
            source_worktree,
            request,
            benchmark_root=replay_root,
            actual_environment_sha256=ENVIRONMENT_SHA256,
        )

    stale_request = _request(
        source,
        source_worktree,
        source_cache,
        replay_run_id="stale-source-replay",
    )
    (source_worktree.worktree_root / "source.txt").write_text(
        "changed after receipt\n", encoding="utf-8"
    )
    _git(source_worktree.worktree_root, "add", "--all")
    _git(
        source_worktree.worktree_root,
        "commit",
        "--no-gpg-sign",
        "-m",
        "drift source worktree",
    )
    with pytest.raises(ReplayError, match="stale"):
        run_detached_replay(
            checkout,
            source,
            source_worktree,
            stale_request,
            benchmark_root=replay_root,
            actual_environment_sha256=ENVIRONMENT_SHA256,
        )
    assert not (replay_root / stale_request.replay_run_id).exists()


def test_replay_rejects_source_mutation_after_command(
    repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    checkout, commit = repository
    source, source_worktree, source_cache = _source_evidence(
        checkout,
        commit,
        tmp_path,
    )
    script = (
        "import json, os; from pathlib import Path; "
        "Path(os.environ['HSSL_REPLAY_EVIDENCE_PATH']).write_text("
        "json.dumps({'produced': True}) + '\\n', encoding='utf-8'); "
        "Path('source.txt').write_text('mutated replay source\\n', "
        "encoding='utf-8')"
    )
    request = _request(
        source,
        source_worktree,
        source_cache,
        replay_run_id="source-mutating-replay",
        script=script,
    )
    replay_root = tmp_path / "source-mutating-state"

    with pytest.raises(ReplayError, match="stale or dirty"):
        run_detached_replay(
            checkout,
            source,
            source_worktree,
            request,
            benchmark_root=replay_root,
            actual_environment_sha256=ENVIRONMENT_SHA256,
        )

    assert not (
        replay_root
        / request.replay_run_id
        / "receipts"
        / "detached-replay-receipt.json"
    ).exists()


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
def test_replay_reaps_and_rejects_lingering_descendant(
    repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    checkout, commit = repository
    source, source_worktree, source_cache = _source_evidence(
        checkout,
        commit,
        tmp_path,
    )
    script = (
        "import json, os, subprocess, sys; from pathlib import Path; "
        "child = subprocess.Popen("
        "[sys.executable, '-c', 'import time; time.sleep(60)'], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
        "stderr=subprocess.DEVNULL); "
        "Path(os.environ['HSSL_REPLAY_EVIDENCE_PATH']).write_text("
        "json.dumps({'child_pid': child.pid}) + '\\n', encoding='utf-8')"
    )
    request = _request(
        source,
        source_worktree,
        source_cache,
        replay_run_id="lingering-child-replay",
        script=script,
    )
    replay_root = tmp_path / "lingering-child-state"

    with pytest.raises(ReplayError, match="lingering process-group"):
        run_detached_replay(
            checkout,
            source,
            source_worktree,
            request,
            benchmark_root=replay_root,
            actual_environment_sha256=ENVIRONMENT_SHA256,
        )

    evidence = json.loads(
        (
            replay_root
            / request.replay_run_id
            / "results"
            / "replay-evidence.json"
        ).read_text(encoding="utf-8")
    )
    child_stat = Path("/proc") / str(evidence["child_pid"]) / "stat"
    deadline = time.monotonic() + 2
    while child_stat.exists() and time.monotonic() < deadline:
        try:
            state = child_stat.read_text(encoding="utf-8").rsplit(
                ") ",
                maxsplit=1,
            )[1].split()[0]
        except (IndexError, OSError):
            break
        if state == "Z":
            break
        time.sleep(0.01)
    if child_stat.exists():
        state = child_stat.read_text(encoding="utf-8").rsplit(
            ") ",
            maxsplit=1,
        )[1].split()[0]
        assert state == "Z"
    assert not (
        replay_root
        / request.replay_run_id
        / "receipts"
        / "detached-replay-receipt.json"
    ).exists()


def test_replay_materializes_exact_pinned_local_gitlinks(
    repository_with_submodule: tuple[Path, str, str],
    tmp_path: Path,
) -> None:
    checkout, commit, pinned_dependency = repository_with_submodule
    source, source_worktree, source_cache = _source_evidence(
        checkout,
        commit,
        tmp_path,
    )
    source_dependency = checkout / "vendor" / "dependency"
    replay_source_dependency = (
        source_worktree.worktree_root / "vendor" / "dependency"
    )
    _git(
        source_worktree.worktree_root,
        "-c",
        "protocol.file.allow=always",
        "-c",
        f"submodule.fixture-dependency.url={source_dependency}",
        "submodule",
        "update",
        "--init",
        "--checkout",
        "--no-fetch",
        "--",
        "vendor/dependency",
    )
    assert (
        _git(replay_source_dependency, "rev-parse", "HEAD").stdout.strip()
        == pinned_dependency
    )

    _git(source_dependency, "config", "user.name", "Replay Tests")
    _git(
        source_dependency,
        "config",
        "user.email",
        "replay@example.invalid",
    )
    (source_dependency / "dependency.txt").write_text(
        "newer local dependency\n",
        encoding="utf-8",
    )
    _git(source_dependency, "add", "--all")
    _git(
        source_dependency,
        "commit",
        "--no-gpg-sign",
        "-m",
        "advance local dependency",
    )
    assert (
        _git(source_dependency, "rev-parse", "HEAD").stdout.strip()
        != pinned_dependency
    )

    request = _request(
        source,
        source_worktree,
        source_cache,
        replay_run_id="local-gitlink-replay",
    )
    receipt, worktree = run_detached_replay(
        checkout,
        source,
        source_worktree,
        request,
        benchmark_root=tmp_path / "local-gitlink-state",
        actual_environment_sha256=ENVIRONMENT_SHA256,
    )

    materialized = worktree.worktree_root / "vendor" / "dependency"
    assert receipt.replay_worktree_receipt_sha256 == worktree.sha256
    assert materialized.joinpath("dependency.txt").read_text(
        encoding="utf-8"
    ) == "pinned dependency\n"
    assert _git(materialized, "rev-parse", "HEAD").stdout.strip() == (
        pinned_dependency
    )
    assert (
        _git(
            materialized,
            "symbolic-ref",
            "--quiet",
            "HEAD",
            check=False,
        ).returncode
        != 0
    )
    assert (
        _git(
            worktree.worktree_root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignore-submodules=none",
        ).stdout
        == ""
    )

    mutating_script = (
        "import json, os; from pathlib import Path; "
        "Path(os.environ['HSSL_REPLAY_EVIDENCE_PATH']).write_text("
        "json.dumps({'produced': True}) + '\\n', encoding='utf-8'); "
        "Path('vendor/dependency/dependency.txt').write_text("
        "'mutated materialized dependency\\n', encoding='utf-8')"
    )
    mutating_request = _request(
        source,
        source_worktree,
        source_cache,
        replay_run_id="dirty-gitlink-replay",
        script=mutating_script,
    )
    mutating_root = tmp_path / "dirty-gitlink-state"
    with pytest.raises(ReplayError, match="stale or dirty"):
        run_detached_replay(
            checkout,
            source,
            source_worktree,
            mutating_request,
            benchmark_root=mutating_root,
            actual_environment_sha256=ENVIRONMENT_SHA256,
        )
    assert not (
        mutating_root
        / mutating_request.replay_run_id
        / "receipts"
        / "detached-replay-receipt.json"
    ).exists()
