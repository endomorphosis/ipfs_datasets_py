"""Benchmark boundary checks without starting an Isabelle build."""
from dataclasses import replace
import errno
import hashlib
import importlib.util
import json
from pathlib import Path
import threading
import time

import pytest


@pytest.fixture(scope="module")
def bench_module():
    path = Path(__file__).resolve().parents[4] / "benchmarks/bench_isabelle_hol_build.py"
    spec = importlib.util.spec_from_file_location("isabelle_hol_build_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("value", ["0", "-1", "60", "nan", "inf", "3601", "invalid"])
def test_cli_requires_finite_overall_budget_and_warm_reserve(bench_module, value):
    with pytest.raises(SystemExit) as exc:
        bench_module.parser().parse_args(["--archive", "official.tar.gz", "--output", "fresh", "--timeout", value])
    assert exc.value.code == 2


def test_cli_default_and_source_scope_include_real_controller_build_worker_and_limits(bench_module):
    args = bench_module.parser().parse_args(["--archive", "official.tar.gz", "--output", "fresh"])
    assert args.timeout == 3600 and bench_module.WARM_RESERVE_SECONDS == 60
    sources = bench_module.source_hashes()
    names = {Path(path).name for path in sources}
    assert {"bench_isabelle_hol_build.py", "isabelle_installation.py", "isabelle_hol_build.py",
            "isabelle_install_worker.py", "process.py", "resource_scheduler.py", "proof_resource_safety.py"} <= names
    assert all(len(value) == 64 for value in sources.values())


def _pin(bench_module, content):
    legacy = bench_module.installer.legacy
    original = legacy.select_strict_pin("isabelle", platform_key=legacy.detect_platform_key())
    return replace(original, sha256=hashlib.sha256(content).hexdigest(), artifact_url="https://official.invalid/archive.tar.gz")


def test_cache_seed_checks_bytes_before_hardlink_and_never_copies(bench_module, tmp_path, monkeypatch):
    content = b"controlled archive bytes"
    archive = tmp_path / "retained.tar.gz"
    archive.write_bytes(content)
    pin = _pin(bench_module, content)
    observed = bench_module.seed_archive_cache(archive, tmp_path / "new", pin, lambda: None)
    cached = Path(observed["path"])
    assert cached.samefile(archive) and observed["method"] == "hardlink"
    assert observed["observed_sha256"] == pin.sha256
    def cross_device(*args, **kwargs):
        raise OSError(errno.EXDEV, "controlled cross-device refusal")
    monkeypatch.setattr(bench_module.os, "link", cross_device)
    with pytest.raises(OSError, match="cross-device"):
        bench_module.seed_archive_cache(archive, tmp_path / "other", pin, lambda: None)
    assert list((tmp_path / "other" / "downloads").iterdir()) == []


def test_wrong_archive_fails_before_target_or_link_creation(bench_module, tmp_path):
    archive = tmp_path / "retained.tar.gz"
    archive.write_bytes(b"wrong")
    target = tmp_path / "new"
    with pytest.raises(RuntimeError, match="differs from reviewed"):
        bench_module.seed_archive_cache(archive, target, _pin(bench_module, b"expected"), lambda: None)
    assert not target.exists()


def test_progress_records_atomic_json_with_current_phase_and_bounded_events(bench_module, tmp_path):
    record = bench_module.ProgressArtifact(tmp_path / "progress.json", time.monotonic())
    errors, finished = [], threading.Event()
    record.phase("cold", "hol_build", "Native build is running")
    record.write(sample={"owned_leases": [{"lease_id": "child"}]})
    def read():
        while not finished.is_set():
            try:
                value = json.loads(record.path.read_text())
                assert value["schema"] == "isabelle-hol-build-progress@1"
            except Exception as exc:
                errors.append(exc)
                return
    reader = threading.Thread(target=read)
    reader.start()
    try:
        for number in range(20):
            record.write(sample={"elapsed_build_sample": number})
    finally:
        finished.set()
        reader.join(2)
    assert not reader.is_alive() and not errors
    final = json.loads(record.path.read_text())
    assert final["active_phase"]["phase"] == "hol_build" and final["status"] == "running"
    assert final["observation"]["elapsed_build_sample"] == 19
    assert not list(tmp_path.glob(".json-*"))
    for _ in range(255):
        record.phase("cold", "progress", "bounded")
    with pytest.raises(RuntimeError, match="event bound"):
        record.phase("cold", "progress", "overflow")


def test_failed_native_controller_receipt_is_retained_and_parent_drains(bench_module, tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
        GlobalResourceScheduler, ResourceSchedulerConfig,
    )
    owner = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "resources.json",
        proof_resource_sampler=lambda: ProofHostResources(16, 16384, 16384),
        lane_reservations={}, auto_renew_leases=False,
    ))
    archive = tmp_path / "retained.tar.gz"
    archive.write_bytes(b"controlled archive bytes")
    pin = _pin(bench_module, archive.read_bytes())
    monkeypatch.setattr(bench_module.installer.legacy, "select_strict_pin", lambda *args, **kw: pin)
    monkeypatch.setattr(bench_module, "get_global_resource_scheduler", lambda: owner)
    calls = []
    def fail(**kwargs):
        calls.append(kwargs)
        assert kwargs["build_hol"] is True and kwargs["allow_download"] is False
        assert kwargs["parent_lease"].memory_mb == 6400
        assert kwargs["build_memory_mb"] == 6144
        assert kwargs["parent_lease"].cpu_slots == 4 and kwargs["parent_lease"].child_process_slots == 12
        assert 0 < kwargs["timeout_seconds"] <= 3540
        kwargs["on_progress"]("hol_build", "controlled failure before native launch")
        receipt = bench_module.installer.IsabelleInstallationReceipt(
            reason_codes=["controlled_native_build_failure"], build_hol_requested=True)
        raise bench_module.installer.IsabelleInstallationError(receipt)
    monkeypatch.setattr(bench_module.installer, "ensure_isabelle_installation", fail)
    output = tmp_path / "result"
    assert bench_module.main(["--archive", str(archive), "--output", str(output)]) == 1
    result = json.loads((output / "result.json").read_text())
    assert len(calls) == 1 and result["status"] == "failed"
    assert result["cold"]["reason_codes"] == ["controlled_native_build_failure"]
    assert result["checks"]["owned_leases_drained"]
    assert result["checks"]["selected_sources_unchanged"]
    assert result["checks"]["sampled_descendants_drained"]
    assert result["checks"]["retained_archive_unchanged"] is False
    assert owner.active_leases() == []
    assert json.loads((output / "progress.json").read_text())["status"] == "failed"


def test_completed_path_joins_heap_receipts_and_distinct_child_envelopes(bench_module, tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
        GlobalResourceScheduler, ResourceSchedulerConfig,
    )
    owner = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "resources.json",
        proof_resource_sampler=lambda: ProofHostResources(16, 16384, 16384),
        lane_reservations={}, auto_renew_leases=False,
    ))
    archive = tmp_path / "retained.tar.gz"
    archive.write_bytes(b"controlled bytes; no native tools invoked")
    pin = _pin(bench_module, archive.read_bytes())
    monkeypatch.setattr(bench_module.installer.legacy, "select_strict_pin", lambda *args, **kw: pin)
    monkeypatch.setattr(bench_module, "get_global_resource_scheduler", lambda: owner)
    calls = []
    def installed(**kwargs):
        calls.append(kwargs)
        build = kwargs["build_hol"]
        runtime = kwargs["install_root"] / "Isabelle2025-2"
        for name in ("bin/isabelle", "etc/settings", "heaps/test/HOL", "heaps/test/Pure"):
            path = runtime / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"controlled " + name.encode())
        preparation = {"usable": True, "smoke_accepted": True, "native_runtime": {"runtime_root": str(runtime)}}
        after = {"session": {"uuid": "fresh"}, "files": {"Pure": {"sha256": "unchanged"}, "log/Pure.db": {"sha256": "unchanged"}}}
        before = {**after, "session": {"uuid": "prebuilt"}}
        with kwargs["parent_lease"].acquire_child(lane="orchestration", cpu_slots=4 if build else 3,
                memory_mb=6400 if build else 2304, child_process_slots=12, timeout=0) as child:
            receipt = bench_module.installer.IsabelleInstallationReceipt(
                status="installed" if build else "already_present", installed=build, already_present=not build,
                checksum_verified=build, build_hol_requested=build, preparation=preparation,
                staged_preparation=preparation if build else {}, resource_lease_id=child.lease_id,
                limits={"allow_download": False}, hol_build={"build_succeeded": True,
                    "persistent_heap_published": True, "heap_before": before, "heap_after": after,
                    "publication_verification": {"verified": True, "heap_after": after}} if build else {})
        return receipt
    monkeypatch.setattr(bench_module.installer, "ensure_isabelle_installation", installed)
    output = tmp_path / "result"
    assert bench_module.main(["--archive", str(archive), "--output", str(output)]) == 0
    result = json.loads((output / "result.json").read_text())
    assert [row["build_hol"] for row in calls] == [True, False]
    assert calls[0]["parent_lease"] is calls[1]["parent_lease"]
    assert all(row["allow_download"] is False for row in calls)
    assert all(row["build_memory_mb"] == 6144 for row in calls)
    assert result["status"] == "completed" and all(result["checks"].values())
    assert result["parent_lease"]["cpu_slots"] == 4 and result["parent_lease"]["memory_mb"] == 6400
    assert result["limits"]["native_build_memory_mb"] == 6144
    assert result["parent_lease"]["child_process_slots"] == 12
    assert result["parent_lease"]["scheduler_state_path"] == str(owner.state_path)
    assert result["archive"]["sha256_after"] == pin.sha256
    assert owner.active_leases() == []
