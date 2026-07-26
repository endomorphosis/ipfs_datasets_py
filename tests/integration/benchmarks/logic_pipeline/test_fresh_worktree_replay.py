from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time

import pytest

from benchmarks.logic_pipeline import RunPaths
from benchmarks.logic_pipeline import adapters
from benchmarks.logic_pipeline import contracts
from benchmarks.logic_pipeline import runtime
from benchmarks.logic_pipeline.ablation import (
    AblationCase,
    build_semantic_ablation_plan,
)
from benchmarks.logic_pipeline.capabilities import (
    CapabilityContractError,
    prepare_isolated_worktree,
)
from benchmarks.logic_pipeline.content_addressing import (
    canonical_dag_json_bytes,
    cid_for_dag_json,
)
from benchmarks.logic_pipeline.contracts import canonical_json
from benchmarks.logic_pipeline.contracts import CaseResultRecord
from benchmarks.logic_pipeline.causal_runtime import (
    execute_causal_runtime_case_v2,
)
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
    run_g240_detached_replay_v2,
)
from benchmarks.logic_pipeline.replay_gate import (
    G238DetachedReplayReceiptV2,
    G238ReplaySourceIndexV2,
    G238ReplaySourceRecordV2,
    G238SemanticObservationV2,
    build_g238_detached_replay_gate_v2,
    g238_git_commit_cid,
    validate_g238_detached_replay_gate_v2,
)
from benchmarks.logic_pipeline.namespace_provenance import (
    G240PrivateReplayValidationSourcesV2,
    G240RuntimeNamespaceReceiptV2,
    RuntimeNamespaceProvenanceError,
    build_g240_namespace_policy_v2,
    g240_cache_namespace_set_cid,
    g240_recursive_gitlinks_cid,
    g240_replay_namespace_request_v2,
    g240_worktree_safety_projection_cid,
    validate_g240_private_replay_sources_v2,
)
from benchmarks.logic_pipeline.resource_statistics import (
    IndependentComponentResourceV2,
    build_independent_resource_receipt_v2,
)
from benchmarks.logic_pipeline.source_reconciliation import (
    _capture_benchmark_bounded_gitlinks,
    _materialize_recursive_local_gitlinks,
    SourceReconciliationError,
)
from benchmarks.logic_pipeline.source_orchestration import (
    build_g240_source_executor_contract_v2,
)
from benchmarks.logic_pipeline.source_bootstrap_contract import (
    G240_BOOTSTRAP_CONFINEMENT_PROFILE_CID_V2,
)
from benchmarks.logic_pipeline.source_executor import (
    G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2,
    G240ExecutionRequestV2,
    _G240_SYNTHETIC_TEST_CAPABILITY_V2,
    build_g240_synthetic_adapter_configuration_v2,
)
import tests.integration.benchmarks.logic_pipeline.test_reviewed_control_safety as control


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


def _marker_script(path: Path, marker: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n"
        f"printf executed > {marker.as_posix()}\n"
        "cat\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, str]:
    checkout = tmp_path / "active-checkout"
    checkout.mkdir()
    _git(checkout, "init", "--initial-branch=main")
    _git(checkout, "config", "user.name", "Replay Tests")
    _git(checkout, "config", "user.email", "replay@example.invalid")
    repository_root = Path(__file__).resolve().parents[4]
    shutil.copytree(
        repository_root / "benchmarks",
        checkout / "benchmarks",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    hammer_package = checkout / "ipfs_datasets_py" / "logic" / "hammers"
    hammer_package.mkdir(parents=True)
    for package in (
        checkout / "ipfs_datasets_py",
        checkout / "ipfs_datasets_py" / "logic",
        hammer_package,
    ):
        package.joinpath("__init__.py").write_text("", encoding="utf-8")
    shutil.copy2(
        repository_root
        / "ipfs_datasets_py"
        / "logic"
        / "hammers"
        / "process_lifecycle.py",
        hammer_package / "process_lifecycle.py",
    )
    (checkout / "source.txt").write_text("pinned source\n", encoding="utf-8")
    (checkout / "g240_replay_executor.py").write_text(
        "import base64\n"
        "import os\n"
        "from pathlib import Path\n"
        "Path(os.environ['HSSL_G240_EVIDENCE_PATH']).write_bytes(\n"
        "    base64.b64decode("
        "os.environ['SYNTHETIC_REPLAY_PAYLOAD_B64'])\n"
        ")\n",
        encoding="utf-8",
    )
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


def test_prepare_rejects_filter_only_in_initialized_submodule(
    repository_with_submodule: tuple[Path, str, str],
    tmp_path: Path,
) -> None:
    checkout, _commit, _pinned_dependency = repository_with_submodule
    dependency = checkout / "vendor" / "dependency"
    _git(dependency, "config", "user.name", "Replay Tests")
    _git(
        dependency,
        "config",
        "user.email",
        "replay@example.invalid",
    )
    (dependency / ".gitattributes").write_text(
        "*.txt filter=child-audit\n",
        encoding="utf-8",
    )
    _git(dependency, "add", "--all")
    _git(
        dependency,
        "commit",
        "--no-gpg-sign",
        "-m",
        "child filter attribute",
    )
    _git(checkout, "add", "vendor/dependency")
    _git(
        checkout,
        "commit",
        "--no-gpg-sign",
        "-m",
        "pin child filter attribute",
    )
    commit = _git(checkout, "rev-parse", "HEAD").stdout.strip()
    marker = tmp_path / "child-filter-marker"
    driver = _marker_script(
        tmp_path / "child-clean-filter",
        marker,
    )
    _git(
        dependency,
        "config",
        "filter.child-audit.clean",
        driver.as_posix(),
    )
    _git(
        dependency,
        "config",
        "filter.child-audit.required",
        "true",
    )

    with pytest.raises(
        CapabilityContractError,
        match="checkout filters",
    ):
        prepare_isolated_worktree(
            checkout,
            run_paths=RunPaths.for_run(
                "child-filter-rejected",
                benchmark_root=tmp_path / "child-filter-state",
            ),
            base_revision=commit,
        )

    assert not marker.exists()


def test_submodule_materialization_disables_source_and_template_hooks(
    repository_with_submodule: tuple[Path, str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout, commit, pinned_dependency = repository_with_submodule
    worktree = prepare_isolated_worktree(
        checkout,
        run_paths=RunPaths.for_run(
            "submodule-hook-safe",
            benchmark_root=tmp_path / "submodule-hook-state",
        ),
        base_revision=commit,
    )
    gitlinks = _capture_benchmark_bounded_gitlinks(checkout, commit)
    source_marker = tmp_path / "source-submodule-hook-marker"
    source_submodule_git_dir = Path(
        _git(
            checkout / "vendor" / "dependency",
            "rev-parse",
            "--path-format=absolute",
            "--git-dir",
        ).stdout.strip()
    )
    _marker_script(
        source_submodule_git_dir
        / "hooks"
        / "post-checkout",
        source_marker,
    )
    template_marker = tmp_path / "template-hook-marker"
    malicious_template = tmp_path / "malicious-template"
    _marker_script(
        malicious_template / "hooks" / "post-checkout",
        template_marker,
    )
    _git(
        checkout,
        "config",
        "init.templateDir",
        malicious_template.as_posix(),
    )
    monkeypatch.setenv("GIT_TEMPLATE_DIR", malicious_template.as_posix())
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "init.templateDir")
    monkeypatch.setenv(
        "GIT_CONFIG_VALUE_0",
        malicious_template.as_posix(),
    )

    _materialize_recursive_local_gitlinks(
        checkout,
        worktree.worktree_root,
        tuple(item for item in gitlinks if item.depth == 1),
    )

    materialized = worktree.worktree_root / "vendor" / "dependency"
    assert (
        _git(materialized, "rev-parse", "HEAD").stdout.strip()
        == pinned_dependency
    )
    assert not source_marker.exists()
    assert not template_marker.exists()


def test_submodule_materialization_never_falls_back_to_remote_helper(
    repository_with_submodule: tuple[Path, str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout, _commit, _pinned_dependency = repository_with_submodule
    _git(
        checkout,
        "config",
        "-f",
        ".gitmodules",
        "submodule.fixture-dependency.url",
        "adversarial::payload",
    )
    _git(checkout, "add", ".gitmodules")
    _git(
        checkout,
        "commit",
        "--no-gpg-sign",
        "-m",
        "adversarial recorded submodule URL",
    )
    commit = _git(checkout, "rev-parse", "HEAD").stdout.strip()
    worktree = prepare_isolated_worktree(
        checkout,
        run_paths=RunPaths.for_run(
            "submodule-remote-helper-safe",
            benchmark_root=tmp_path / "submodule-remote-state",
        ),
        base_revision=commit,
    )
    gitlinks = _capture_benchmark_bounded_gitlinks(checkout, commit)
    unavailable = tmp_path / "unavailable-local-submodule"
    (checkout / "vendor" / "dependency").rename(unavailable)
    marker = tmp_path / "remote-helper-marker"
    helper = tmp_path / "malicious-bin" / "git-remote-adversarial"
    helper.parent.mkdir()
    helper.write_text(
        "#!/bin/sh\n"
        f"printf executed > {marker.as_posix()}\n"
        "exit 1\n",
        encoding="utf-8",
    )
    helper.chmod(0o755)
    monkeypatch.setenv(
        "PATH",
        f"{helper.parent.as_posix()}:{os.defpath}",
    )
    monkeypatch.setenv("GIT_EXEC_PATH", helper.parent.as_posix())

    with pytest.raises(
        SourceReconciliationError,
        match="local submodule repository unavailable",
    ):
        _materialize_recursive_local_gitlinks(
            checkout,
            worktree.worktree_root,
            tuple(item for item in gitlinks if item.depth == 1),
        )

    assert not marker.exists()
    assert not (
        worktree.worktree_root / "vendor" / "dependency" / "dependency.txt"
    ).exists()


def test_submodule_materialization_rejects_ext_url_rewrite(
    repository_with_submodule: tuple[Path, str, str],
    tmp_path: Path,
) -> None:
    checkout, commit, _pinned_dependency = repository_with_submodule
    worktree = prepare_isolated_worktree(
        checkout,
        run_paths=RunPaths.for_run(
            "submodule-ext-rewrite-safe",
            benchmark_root=tmp_path / "submodule-ext-state",
        ),
        base_revision=commit,
    )
    gitlinks = _capture_benchmark_bounded_gitlinks(checkout, commit)
    marker = tmp_path / "remote-ext-marker"
    rewrite = (
        "ext::sh -c 'printf executed > "
        f"{marker.as_posix()}'"
    )
    _git(
        worktree.worktree_root,
        "config",
        f"url.{rewrite}.insteadOf",
        (checkout / "vendor" / "dependency").as_posix(),
    )
    _git(
        worktree.worktree_root,
        "config",
        "protocol.ext.allow",
        "always",
    )

    with pytest.raises(
        SourceReconciliationError,
        match="transport overrides are forbidden",
    ):
        _materialize_recursive_local_gitlinks(
            checkout,
            worktree.worktree_root,
            tuple(item for item in gitlinks if item.depth == 1),
        )

    assert not marker.exists()
    assert not (
        worktree.worktree_root / "vendor" / "dependency" / "dependency.txt"
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
    assert (
        stat.S_IMODE(
            materialized.joinpath("dependency.txt").lstat().st_mode
        )
        & 0o022
        == 0
    )
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


def _g240_verified_runtime(
    root: Path,
    *,
    run_id: str,
    cache_mode: contracts.CacheMode = contracts.CacheMode.COLD,
):
    previous = control.RUN_ID
    control.RUN_ID = run_id
    try:
        template = control._coordinate_evidence(
            root,
            cache_mode=cache_mode,
            variant_ids=("A0",),
            kernel_returncode=0,
            namespace=run_id,
        )[0]
        kernel = runtime.NativeKernelRunner(
            "/bin/true",
            template.semantic_frontend[
                0
            ].provenance.environment_sha256,
            root / run_id / "tracked-executor-kernel",
            timeout_seconds=1.0,
        )
        return execute_causal_runtime_case_v2(
            CaseResultRecord.from_stages(template.semantic_frontend),
            template.source_text,
            template.proof_context,
            template.compiler_exposure,
            {
                contracts.StageName.KERNEL: adapters.StageAdapter(
                    contracts.StageName.KERNEL,
                    handler=kernel,
                )
            },
        )
    finally:
        control.RUN_ID = previous


def _g240_resource_receipt(
    runtime_evidence,
    *,
    producer_identity_cid: str,
    meter_identity_cid: str,
    validator_identity_cid: str,
):
    return build_independent_resource_receipt_v2(
        runtime_evidence,
        (
            IndependentComponentResourceV2(
                component_id="pipeline",
                wall_time_ms=10.0,
                peak_memory_bytes=1_000_000,
                model_calls=0,
                retries=0,
                solver_processes=0,
                accelerator_minutes=0.0,
                queue_delay_ms=1.0,
                released=True,
                process_group_reaped=True,
                missing_reasons={},
            ),
        ),
        producer_identity_cid=producer_identity_cid,
        meter_identity_cid=meter_identity_cid,
        validator_identity_cid=validator_identity_cid,
    )


def test_g240_runner_binds_actual_detached_process_and_worktree(
    repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    checkout, commit = repository
    source_run_id = "g240-source-run"
    replay_run_id = "g240-replay-run"
    source_runtime = _g240_verified_runtime(
        tmp_path / "g240-source-runtime",
        run_id=source_run_id,
        cache_mode=contracts.CacheMode.WARM,
    )
    replay_runtime = _g240_verified_runtime(
        tmp_path / "g240-replay-runtime",
        run_id=replay_run_id,
        cache_mode=contracts.CacheMode.WARM,
    )
    source_result = source_runtime.case_result
    plan = build_semantic_ablation_plan(
        source_run_id,
        (
            AblationCase.create(
                source_result.case_id,
                {"text": source_runtime.source_text},
                split=source_result.split,
            ),
        ),
        case_manifest_sha256=source_result.case_manifest_sha256,
        split=source_result.split,
        seed=89,
        variant_ids=(source_result.variant_id,),
        cache_modes=(source_result.cache_mode,),
        environment_sha256=(
            source_result.stages[0].provenance.environment_sha256
        ),
    )
    gitlinks = _capture_benchmark_bounded_gitlinks(checkout, commit)
    namespace_authority = cid_for_dag_json(
        {"authority": "synthetic-g240-namespace-policy"}
    )
    source_executor = cid_for_dag_json(
        {"authority": "synthetic-g240-source-executor"}
    )
    source_observer = cid_for_dag_json(
        {"authority": "synthetic-g240-source-observer"}
    )
    replay_executor = cid_for_dag_json(
        {"authority": "synthetic-g240-replay-executor"}
    )
    replay_validator = cid_for_dag_json(
        {"authority": "synthetic-g240-replay-namespace-observer"}
    )
    orchestration_observer = cid_for_dag_json(
        {"authority": "synthetic-g240-orchestration-observer"}
    )
    replay_meter = cid_for_dag_json(
        {"authority": "synthetic-g240-replay-meter"}
    )
    environment_cid = cid_for_dag_json(
        {"schema": "synthetic-g240-environment.v1"}
    )
    executor_contract = build_g240_source_executor_contract_v2(
        (
            "python",
            "-m",
            "benchmarks.logic_pipeline.source_executor",
        ),
        entrypoint_kind="python-module",
        environment_cid=environment_cid,
        environment_sha256=plan.environment_sha256,
        executor_identity_cid=source_executor,
    )
    policy = build_g240_namespace_policy_v2(
        (plan,),
        source_commit_cid=g238_git_commit_cid(commit),
        recursive_gitlinks_cid=g240_recursive_gitlinks_cid(gitlinks),
        environment_cid=environment_cid,
        runtime_orchestration_policy_cid=str(
            executor_contract.contract_cid
        ),
        namespace_authority_cid=namespace_authority,
    )
    source_namespace_receipt = G240RuntimeNamespaceReceiptV2.create(
        policy=policy,
        plan=plan,
        job=plan.jobs[0],
        evidence=source_runtime,
        executor_identity_cid=source_executor,
        observer_identity_cid=source_observer,
        process_group_started=True,
        process_group_reaped=True,
        active_process_count_after_reap=0,
        state_namespace_created_exclusive=True,
        state_namespace_finalized=True,
        output_namespace_created_exclusive=True,
        output_namespace_finalized=True,
        cache_namespaces_mounted=True,
    )
    source_execution_request = G240ExecutionRequestV2.create(
        execution_mode="source",
        execution_run_id=source_run_id,
        source_run_id=source_run_id,
        source_commit=commit,
        policy_cid=str(policy.policy_cid),
        runtime_orchestration_policy_cid=str(
            executor_contract.contract_cid
        ),
        plan=plan,
        job=plan.jobs[0],
        coordinate=policy.job_map[
            (policy.plan_cids[0], plan.jobs[0].job_id)
        ],
        environment_cid=environment_cid,
        environment_sha256=str(plan.environment_sha256),
        semantic_result=CaseResultRecord.from_stages(
            source_runtime.semantic_frontend
        ),
        compiler_exposure=source_runtime.compiler_exposure,
        source_text=source_runtime.source_text,
        proof_context=source_runtime.proof_context,
        adapter_factory_id=G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2,
        adapter_configuration=(
            build_g240_synthetic_adapter_configuration_v2()
        ),
        _test_only_synthetic_capability=(
            _G240_SYNTHETIC_TEST_CAPABILITY_V2
        ),
    )
    replay_launch = g240_replay_namespace_request_v2(
        source_policy=policy,
        source_receipt=source_namespace_receipt,
        replay_run_id=replay_run_id,
    )
    replay_execution_request = G240ExecutionRequestV2.create_replay(
        source_execution_request,
        replay_run_id=replay_run_id,
        replay_process_namespace_cid=str(
            replay_launch["replay_process_namespace_cid"]
        ),
        replay_state_namespace_cid=str(
            replay_launch["replay_state_namespace_cid"]
        ),
        replay_output_namespace_cid=str(
            replay_launch["replay_output_namespace_cid"]
        ),
        replay_cache_namespace_cids=(
            replay_launch["replay_cache_namespace_cids"]
        ),
        source_runtime_evidence=source_runtime,
        _test_only_synthetic_capability=(
            _G240_SYNTHETIC_TEST_CAPABILITY_V2
        ),
    )
    assert (
        replay_execution_request.source_runtime_evidence_cid
        == source_runtime.receipt_cid
    )
    source_paths = RunPaths.for_run(
        source_run_id,
        benchmark_root=tmp_path / "g240-source-worktree-state",
    )
    source_worktree = prepare_isolated_worktree(
        checkout,
        run_paths=source_paths,
        base_revision=commit,
    )
    before = _active_snapshot(checkout)
    (
        restored_runtime,
        replay_namespace_receipt,
        orchestration_receipt,
        replay_request,
        replay_receipt,
        replay_worktree,
    ) = run_g240_detached_replay_v2(
        checkout,
        source_worktree,
        policy,
        source_namespace_receipt,
        source_runtime,
        source_execution_request=source_execution_request,
        replay_execution_request=replay_execution_request,
        replay_run_id=replay_run_id,
        executor_contract=executor_contract,
        benchmark_root=tmp_path / "g240-replay-state",
        replay_executor_identity_cid=replay_executor,
        replay_namespace_observer_identity_cid=replay_validator,
        orchestration_observer_identity_cid=orchestration_observer,
        timeout_seconds=20,
        _test_only_synthetic_capability=(
            _G240_SYNTHETIC_TEST_CAPABILITY_V2
        ),
    )
    replay_payload = (
        canonical_dag_json_bytes(restored_runtime.to_dict()) + b"\n"
    )
    private_sources = G240PrivateReplayValidationSourcesV2(
        source_policy=policy,
        executor_contract=executor_contract,
        source_namespace_receipt=source_namespace_receipt,
        namespace_receipt=replay_namespace_receipt,
        orchestration_receipt=orchestration_receipt,
        source_worktree_safety_receipt=source_worktree,
        replay_request=replay_request,
        replay_receipt=replay_receipt,
        replay_worktree_safety_receipt=replay_worktree,
        evidence_payload=replay_payload,
    )

    restored = validate_g240_private_replay_sources_v2(
        private_sources,
        source_runtime_evidence=source_runtime,
        replay_runtime_evidence=restored_runtime,
    )

    assert restored_runtime.case_result.run_id == replay_run_id
    assert (
        replay_request.execution_request_cid
        == replay_execution_request.request_cid
    )
    replay_runtime = restored_runtime
    assert restored[3].receipt_cid == orchestration_receipt.receipt_cid
    assert (
        orchestration_receipt.runtime_orchestration_policy_cid
        == executor_contract.contract_cid
    )
    assert (
        Path(replay_receipt._process_observation.arguments[0])
        == Path(executor_contract.interpreter_path)
    )
    public_replay = json.dumps(
        replay_receipt.to_dict(),
        sort_keys=True,
    )
    assert str(Path(sys.executable).resolve(strict=True)) not in public_replay
    assert "_process_observation" not in public_replay
    assert "_g240_private_execution_sources" not in public_replay

    foreign_source_runtime_request = replace(
        replay_execution_request,
        source_runtime_evidence_cid=cid_for_dag_json(
            {"runtime": "foreign-source-evidence"}
        ),
        request_cid=None,
    )
    foreign_source_runtime_root = (
        tmp_path / "g240-foreign-source-runtime-state"
    )
    with pytest.raises(
        ReplayError,
        match="source/replay execution request differs",
    ):
        run_g240_detached_replay_v2(
            checkout,
            source_worktree,
            policy,
            source_namespace_receipt,
            source_runtime,
            source_execution_request=source_execution_request,
            replay_execution_request=foreign_source_runtime_request,
            replay_run_id=replay_run_id,
            executor_contract=executor_contract,
            benchmark_root=foreign_source_runtime_root,
            replay_executor_identity_cid=replay_executor,
            replay_namespace_observer_identity_cid=replay_validator,
            orchestration_observer_identity_cid=orchestration_observer,
            timeout_seconds=20,
            _test_only_synthetic_capability=(
                _G240_SYNTHETIC_TEST_CAPABILITY_V2
            ),
        )
    assert not (
        foreign_source_runtime_root / replay_run_id
    ).exists()

    with pytest.raises(
        RuntimeNamespaceProvenanceError,
        match="live process|inputs failed typed replay",
    ):
        validate_g240_private_replay_sources_v2(
            replace(
                private_sources,
                replay_receipt=ReplayReceipt.from_dict(
                    replay_receipt.to_dict()
                ),
            ),
            source_runtime_evidence=source_runtime,
            replay_runtime_evidence=restored_runtime,
        )
    assert (
        orchestration_receipt.command_cid
        == executor_contract.command_template_cid
    )
    assert (
        orchestration_receipt.confinement_profile_cid
        == G240_BOOTSTRAP_CONFINEMENT_PROFILE_CID_V2
    )
    assert orchestration_receipt.synthetic_test_only is True
    assert orchestration_receipt.runtime_preflight_cid is not None
    assert orchestration_receipt.landlock_policy_cid is None
    assert orchestration_receipt.landlock_receipt_cid is None
    assert orchestration_receipt.landlock_receipt_payload_cid is None
    assert replay_request.command == executor_contract.command_template
    assert replay_request.source_execution_receipt_sha256 == hashlib.sha256(
        canonical_json(source_namespace_receipt.to_dict()).encode("utf-8")
    ).hexdigest()
    assert (
        replay_receipt.process_namespace
        == replay_namespace_receipt.replay_process_namespace_cid
    )
    assert replay_receipt.cache_namespace.endswith("/cache/warm")
    assert (
        g240_cache_namespace_set_cid(
            replay_namespace_receipt.replay_cache_namespace_cids
        )
        in replay_receipt.cache_namespace
    )
    assert replay_worktree.detached is True
    assert _active_snapshot(checkout) == before

    source_resource = _g240_resource_receipt(
        source_runtime,
        producer_identity_cid=source_executor,
        meter_identity_cid=cid_for_dag_json(
            {"authority": "synthetic-g240-source-meter"}
        ),
        validator_identity_cid=cid_for_dag_json(
            {"authority": "synthetic-g240-source-resource-validator"}
        ),
    )
    replay_resource = _g240_resource_receipt(
        replay_runtime,
        producer_identity_cid=replay_executor,
        meter_identity_cid=replay_meter,
        validator_identity_cid=replay_validator,
    )
    source_record = G238ReplaySourceRecordV2.create(
        runtime_evidence=source_runtime,
        semantic_observation=G238SemanticObservationV2.create(
            source_runtime
        ),
        resource_receipt=source_resource,
    )
    source_index = G238ReplaySourceIndexV2.create(
        source_run_id=source_run_id,
        source_commit=commit,
        recursive_gitlinks_cid=policy.recursive_gitlinks_cid,
        environment_cid=policy.environment_cid,
        route_manifest_cid=cid_for_dag_json(
            {"schema": "synthetic-g240-routes.v1"}
        ),
        case_index_cid=cid_for_dag_json(
            {"schema": "synthetic-g240-cases.v1"}
        ),
        run_plan_cid=cid_for_dag_json(
            {"schema": "synthetic-g240-run-plan.v1"}
        ),
        source_worktree_cid=g240_worktree_safety_projection_cid(
            source_worktree
        ),
        source_executor_authority_cid=source_executor,
        records=(source_record,),
    )
    detached_receipt = G238DetachedReplayReceiptV2.create(
        source_index=source_index,
        source_record=source_record,
        replay_run_id=replay_run_id,
        replay_worktree_cid=(
            replay_namespace_receipt.replay_worktree_cid
        ),
        source_namespace_receipt_cid=(
            source_namespace_receipt.receipt_cid
        ),
        source_process_namespace_cid=(
            source_namespace_receipt.process_namespace_cid
        ),
        source_state_namespace_cid=(
            source_namespace_receipt.state_namespace_cid
        ),
        source_cache_namespace_cid=g240_cache_namespace_set_cid(
            source_namespace_receipt.cache_namespace_cids
        ),
        replay_process_namespace_cid=(
            replay_namespace_receipt.replay_process_namespace_cid
        ),
        replay_state_namespace_cid=(
            replay_namespace_receipt.replay_state_namespace_cid
        ),
        replay_cache_namespace_cid=g240_cache_namespace_set_cid(
            replay_namespace_receipt.replay_cache_namespace_cids
        ),
        replay_executor_authority_cid=replay_executor,
        replay_validator_authority_cid=replay_validator,
        replay_runtime_evidence=replay_runtime,
        replay_semantic_observation=G238SemanticObservationV2.create(
            replay_runtime
        ),
        replay_resource_receipt=replay_resource,
    )
    operational_sources = {
        source_record.record_cid: private_sources
    }
    gate = build_g238_detached_replay_gate_v2(
        source_index,
        (detached_receipt,),
        validator_authority_cid=replay_validator,
        operational_replay_sources=operational_sources,
    )

    assert gate["passed"] is True
    assert gate["failure_codes"] == []
    assert gate["validated_namespace_receipt_cids"] == [
        replay_namespace_receipt.receipt_cid
    ]
    assert gate["validated_orchestration_receipt_cids"] == [
        orchestration_receipt.receipt_cid
    ]
    assert (
        validate_g238_detached_replay_gate_v2(
            gate,
            source_index,
            (detached_receipt,),
            validator_authority_cid=replay_validator,
            operational_replay_sources=operational_sources,
        )
        == gate["receipt_cid"]
    )

    forged_source_namespace = detached_receipt.to_dict()
    forged_source_namespace["source_process_namespace_cid"] = (
        cid_for_dag_json(
            {"namespace": "copied-source-process-claim"}
        )
    )
    forged_source_namespace["receipt_cid"] = cid_for_dag_json(
        {
            key: value
            for key, value in forged_source_namespace.items()
            if key != "receipt_cid"
        }
    )
    forged_source_receipt = G238DetachedReplayReceiptV2.from_dict(
        forged_source_namespace
    )
    forged_source_gate = build_g238_detached_replay_gate_v2(
        source_index,
        (forged_source_receipt,),
        validator_authority_cid=replay_validator,
        operational_replay_sources=operational_sources,
    )
    assert forged_source_gate["passed"] is False
    assert "operational_replay_not_source_recomputed" in (
        forged_source_gate["failure_codes"]
    )

    rebased_request = ReplayRequest.create(
        source_run_id=replay_request.source_run_id,
        replay_run_id=replay_request.replay_run_id,
        source_commit=replay_request.source_commit,
        environment_sha256=replay_request.environment_sha256,
        source_execution_receipt_sha256=(
            replay_request.source_execution_receipt_sha256
        ),
        source_worktree_receipt_sha256=(
            replay_request.source_worktree_receipt_sha256
        ),
        source_process_namespace=(
            replay_request.source_process_namespace
        ),
        replay_process_namespace=cid_for_dag_json(
            {"namespace": "caller-rebased-process"}
        ),
        source_cache_namespaces=(
            replay_request.source_cache_namespaces
        ),
        replay_cache_namespace=replay_request.replay_cache_namespace,
        command=replay_request.command,
        evidence_relative_path=replay_request.evidence_relative_path,
        timeout_seconds=replay_request.timeout_seconds,
    )
    rebased_sources = replace(
        private_sources,
        replay_request=rebased_request,
    )
    rebased_gate = build_g238_detached_replay_gate_v2(
        source_index,
        (detached_receipt,),
        validator_authority_cid=replay_validator,
        operational_replay_sources={
            source_record.record_cid: rebased_sources
        },
    )
    assert rebased_gate["passed"] is False
    assert "operational_replay_not_source_recomputed" in (
        rebased_gate["failure_codes"]
    )
    forged_source_request = ReplayRequest.create(
        source_run_id=replay_request.source_run_id,
        replay_run_id=replay_request.replay_run_id,
        source_commit=replay_request.source_commit,
        environment_sha256=replay_request.environment_sha256,
        source_execution_receipt_sha256=hashlib.sha256(
            b"copied source namespace claim"
        ).hexdigest(),
        source_worktree_receipt_sha256=(
            replay_request.source_worktree_receipt_sha256
        ),
        source_process_namespace=(
            replay_request.source_process_namespace
        ),
        replay_process_namespace=(
            replay_request.replay_process_namespace
        ),
        source_cache_namespaces=(
            replay_request.source_cache_namespaces
        ),
        replay_cache_namespace=replay_request.replay_cache_namespace,
        command=replay_request.command,
        evidence_relative_path=replay_request.evidence_relative_path,
        timeout_seconds=replay_request.timeout_seconds,
    )
    with pytest.raises(RuntimeNamespaceProvenanceError):
        validate_g240_private_replay_sources_v2(
            replace(
                private_sources,
                replay_request=forged_source_request,
            ),
            source_runtime_evidence=source_runtime,
            replay_runtime_evidence=replay_runtime,
        )

    foreign_producer = cid_for_dag_json(
        {"authority": "synthetic-foreign-resource-producer"}
    )
    foreign_resource = _g240_resource_receipt(
        replay_runtime,
        producer_identity_cid=foreign_producer,
        meter_identity_cid=replay_meter,
        validator_identity_cid=replay_validator,
    )
    foreign_resource_receipt = G238DetachedReplayReceiptV2.create(
        source_index=source_index,
        source_record=source_record,
        replay_run_id=replay_run_id,
        replay_worktree_cid=(
            replay_namespace_receipt.replay_worktree_cid
        ),
        source_namespace_receipt_cid=(
            source_namespace_receipt.receipt_cid
        ),
        source_process_namespace_cid=(
            source_namespace_receipt.process_namespace_cid
        ),
        source_state_namespace_cid=(
            source_namespace_receipt.state_namespace_cid
        ),
        source_cache_namespace_cid=g240_cache_namespace_set_cid(
            source_namespace_receipt.cache_namespace_cids
        ),
        replay_process_namespace_cid=(
            replay_namespace_receipt.replay_process_namespace_cid
        ),
        replay_state_namespace_cid=(
            replay_namespace_receipt.replay_state_namespace_cid
        ),
        replay_cache_namespace_cid=g240_cache_namespace_set_cid(
            replay_namespace_receipt.replay_cache_namespace_cids
        ),
        replay_executor_authority_cid=replay_executor,
        replay_validator_authority_cid=replay_validator,
        replay_runtime_evidence=replay_runtime,
        replay_semantic_observation=G238SemanticObservationV2.create(
            replay_runtime
        ),
        replay_resource_receipt=foreign_resource,
    )
    authority_gate = build_g238_detached_replay_gate_v2(
        source_index,
        (foreign_resource_receipt,),
        validator_authority_cid=replay_validator,
        operational_replay_sources=operational_sources,
    )
    assert authority_gate["passed"] is False
    assert "operational_replay_not_source_recomputed" in (
        authority_gate["failure_codes"]
    )

    foreign_contract = build_g240_source_executor_contract_v2(
        ("python",),
        entrypoint_kind="installed-cli",
        environment_cid=environment_cid,
        environment_sha256=plan.environment_sha256,
        executor_identity_cid=source_executor,
    )
    foreign_contract_root = tmp_path / "g240-foreign-contract-state"
    with pytest.raises(
        ReplayError,
        match="contract differs from the frozen policy",
    ):
        run_g240_detached_replay_v2(
            checkout,
            source_worktree,
            policy,
            source_namespace_receipt,
            source_runtime,
            source_execution_request=source_execution_request,
            replay_execution_request=replay_execution_request,
            replay_run_id="g240-foreign-contract-replay",
            executor_contract=foreign_contract,
            benchmark_root=foreign_contract_root,
            replay_executor_identity_cid=replay_executor,
            replay_namespace_observer_identity_cid=replay_validator,
            orchestration_observer_identity_cid=(
                orchestration_observer
            ),
            timeout_seconds=20,
        )
    assert not (
        foreign_contract_root / "g240-foreign-contract-replay"
    ).exists()
    with pytest.raises(
        RuntimeNamespaceProvenanceError,
        match="private replay sources failed typed validation",
    ):
        validate_g240_private_replay_sources_v2(
            replace(
                private_sources,
                executor_contract=foreign_contract,
            ),
            source_runtime_evidence=source_runtime,
            replay_runtime_evidence=replay_runtime,
        )

    reserved_root = tmp_path / "g240-reserved-replay-state"
    with pytest.raises(
        ReplayError,
        match="cannot override G240 replay namespaces",
    ):
        run_g240_detached_replay_v2(
            checkout,
            source_worktree,
            policy,
            source_namespace_receipt,
            source_runtime,
            source_execution_request=source_execution_request,
            replay_execution_request=replay_execution_request,
            replay_run_id=replay_run_id,
            executor_contract=executor_contract,
            benchmark_root=reserved_root,
            replay_executor_identity_cid=replay_executor,
            replay_namespace_observer_identity_cid=replay_validator,
            orchestration_observer_identity_cid=(
                orchestration_observer
            ),
            environment={"HSSL_G240_STATE_PATH": "/caller/override"},
            timeout_seconds=20,
            _test_only_synthetic_capability=(
                _G240_SYNTHETIC_TEST_CAPABILITY_V2
            ),
        )
    assert not (reserved_root / "g240-reserved-replay").exists()

    for key in ("PATH", "PYTHONPATH", "PYTHONHOME"):
        interpreter_root = (
            tmp_path / f"g240-replay-{key.lower()}-override"
        )
        with pytest.raises(
            ReplayError,
            match="cannot override G240 replay namespaces",
        ):
            run_g240_detached_replay_v2(
                checkout,
                source_worktree,
                policy,
                source_namespace_receipt,
                source_runtime,
                source_execution_request=source_execution_request,
                replay_execution_request=replay_execution_request,
                replay_run_id=replay_run_id,
                executor_contract=executor_contract,
                benchmark_root=interpreter_root,
                replay_executor_identity_cid=replay_executor,
                replay_namespace_observer_identity_cid=replay_validator,
                orchestration_observer_identity_cid=(
                    orchestration_observer
                ),
                environment={key: "/caller/override"},
                timeout_seconds=20,
                _test_only_synthetic_capability=(
                    _G240_SYNTHETIC_TEST_CAPABILITY_V2
                ),
            )
        assert not (interpreter_root / replay_run_id).exists()
