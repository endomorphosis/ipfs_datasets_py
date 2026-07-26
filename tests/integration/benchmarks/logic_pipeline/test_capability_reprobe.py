"""Integration evidence for the frozen HSSL reassessment capability probe."""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from benchmarks.logic_pipeline import capabilities, runtime
from benchmarks.logic_pipeline import capability_reprobe as reprobe
from benchmarks.logic_pipeline.reassessment_namespace import (
    ReassessmentRunLayout,
)
from benchmarks.logic_pipeline.source_reconciliation import (
    SourceReconciliationError,
)


ROOT = Path(__file__).resolve().parents[4]
RECEIPTS = ROOT / reprobe.DEFAULT_RECEIPT_DIRECTORY
SNAPSHOT = ROOT / reprobe.DEFAULT_SNAPSHOT_PATH
EXPECTED_SAFETY = {
    "corpus_accessed": False,
    "fallback_used": False,
    "holdout_accessed": False,
    "matrix_execution_authorized": True,
    "production_routing_changed": False,
    "secrets_serialized": False,
}
FRESH_TEST_RUN_ID = "post-repair-capability-freeze-test"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _copy_receipts(tmp_path: Path) -> Path:
    destination = tmp_path / "receipts"
    shutil.copytree(RECEIPTS, destination)
    return destination


def _seal_live_receipt(value: dict[str, object]) -> None:
    value.pop("receipt_sha256", None)
    value["receipt_sha256"] = hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _fresh_test_reprobe(
    published: reprobe.LiveCapabilityReprobe,
) -> reprobe.LiveCapabilityReprobe:
    receipts: dict[str, dict[str, object]] = {}
    for component, frozen_receipt in published.receipts.items():
        receipt = json.loads(_canonical_json(dict(frozen_receipt)))
        receipt["run_id"] = FRESH_TEST_RUN_ID
        _seal_live_receipt(receipt)
        receipts[component] = receipt
    records = []
    for record in published.inventory.capabilities:
        identity = dict(record.identity)
        component = str(identity["live_receipt_component"])
        identity["live_receipt_sha256"] = receipts[component]["receipt_sha256"]
        records.append(
            capabilities.CapabilityRecord(
                kind=record.kind,
                status=record.status,
                identity=identity,
                provenance=record.provenance,
                reason=record.reason,
            )
        )
    environment = dict(published.inventory.environment)
    environment["run_id"] = FRESH_TEST_RUN_ID
    inventory = capabilities.CapabilityInventory.create(
        FRESH_TEST_RUN_ID,
        records,
        environment=environment,
        source_commit=published.inventory.source_commit,
    )
    return reprobe.LiveCapabilityReprobe(
        inventory,
        receipts,
        published.source_binding,
    )


def _stub_source_binding(
    monkeypatch: pytest.MonkeyPatch,
    source_binding: object,
) -> None:
    expected = dict(source_binding)  # type: ignore[arg-type]

    def load_binding(
        _repository: Path,
        _baseline_path: Path,
        *,
        expected_run_id: str,
        benchmark_root: str | Path,
    ) -> dict[str, object]:
        assert expected_run_id == FRESH_TEST_RUN_ID
        assert benchmark_root
        return dict(expected)

    monkeypatch.setattr(reprobe, "_source_binding", load_binding)


def _freeze_external_test_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, ReassessmentRunLayout]:
    repository = tmp_path / "repository"
    repository.mkdir()
    benchmark_root = (tmp_path / "external-benchmark-root").resolve()
    published = reprobe.validate_frozen_capability_reprobe(
        repository_root=ROOT,
        receipt_directory=RECEIPTS,
    )
    frozen = _fresh_test_reprobe(published)
    _stub_source_binding(monkeypatch, frozen.source_binding)
    layout = ReassessmentRunLayout.for_run(
        FRESH_TEST_RUN_ID,
        benchmark_root=benchmark_root,
    )
    reprobe.freeze_live_capability_reprobe(
        frozen,
        repository_root=repository,
        benchmark_root=benchmark_root,
    )
    return repository, benchmark_root, layout


def test_checked_freeze_is_strict_complete_and_source_bound() -> None:
    frozen = reprobe.validate_frozen_capability_reprobe(
        repository_root=ROOT,
        receipt_directory=RECEIPTS,
    )

    assert reprobe.HSSLEV1207F16() == runtime.HSSLEV1207F16()
    assert frozen.inventory.run_id == reprobe.REASSESSMENT_RUN_ID
    assert frozen.inventory.source_commit == frozen.source_binding["source_commit"]
    assert frozen.source_binding["detached"] is True
    assert frozen.source_binding["active_checkout_unchanged"] is True
    assert frozen.source_binding["recursive_gitlink_count"] == 20
    assert {
        record.kind for record in frozen.inventory.capabilities
    } == set(capabilities.CapabilityKind)
    assert all(
        record.status is capabilities.CapabilityStatus.AVAILABLE
        and record.identity["bounded_smoke"] is True
        for record in frozen.inventory.capabilities
    )
    assert set(frozen.receipts) == {
        "spacy_pipeline",
        "symai_router",
        "hammer",
        "leanstral_service",
        "lean_toolchain",
        "cache_backend",
        "resource_scheduler",
        reprobe.NATIVE_KERNEL_COMPONENT,
    }
    for receipt in frozen.receipts.values():
        assert receipt["requested_identity"] == receipt["effective_identity"]
        assert receipt["bounded"]["bounded"] is True
        assert receipt["safety"] == {
            key: value
            for key, value in EXPECTED_SAFETY.items()
            if key != "matrix_execution_authorized"
        }
    native = frozen.receipts[reprobe.NATIVE_KERNEL_COMPONENT]
    assert native["checks"]["accepted"] is True
    assert native["checks"]["returncode"] == 0
    assert native["checks"]["timed_out"] is False
    assert native["checks"]["process_group_reaped"] is True


def test_checked_snapshot_cross_binds_inventory_freeze_and_safety() -> None:
    validated = reprobe.validate_capability_snapshot(
        repository_root=ROOT,
        snapshot_path=SNAPSHOT,
    )
    snapshot = _load(SNAPSHOT)
    assert dict(validated) == snapshot
    results = snapshot["results"]
    assert isinstance(results, dict)
    assert results["schema"] == reprobe.SNAPSHOT_SCHEMA
    assert results["evidence"] == "HSSLEV1207F16"
    assert results["run_id"] == reprobe.REASSESSMENT_RUN_ID
    assert results["status"] == "eligible"
    assert results["frozen"] is True
    assert results["safety"] == EXPECTED_SAFETY
    assert results["capability_statuses"] == {
        kind.value: capabilities.CapabilityStatus.AVAILABLE.value
        for kind in capabilities.CapabilityKind
    }

    inventory_ref = results["inventory"]
    freeze_ref = results["freeze"]
    assert isinstance(inventory_ref, dict)
    assert isinstance(freeze_ref, dict)
    inventory_path = ROOT / str(inventory_ref["path"])
    freeze_path = ROOT / str(freeze_ref["path"])
    assert _sha256(inventory_path.read_bytes()) == inventory_ref["bytes_sha256"]
    assert _sha256(freeze_path.read_bytes()) == freeze_ref["bytes_sha256"]

    freeze = _load(freeze_path)
    freeze_sha256 = freeze.pop("freeze_sha256")
    assert hashlib.sha256(
        _canonical_json(freeze).encode("utf-8")
    ).hexdigest() == freeze_sha256 == freeze_ref["semantic_sha256"]
    assert results["source_binding"] == freeze["source_binding"]
    native = results["native_kernel"]
    assert isinstance(native, dict)
    assert native["status"] == "pass"
    assert native["receipt_sha256"] == freeze["receipts"]["native_kernel"][
        "receipt_sha256"
    ]


def test_tampered_component_receipt_is_rejected_from_a_copied_tree(
    tmp_path: Path,
) -> None:
    copied = _copy_receipts(tmp_path)
    target = copied / "native-kernel-smoke.json"
    payload = _load(target)
    payload["checks"]["accepted"] = False
    target.write_text(_canonical_json(payload) + "\n", encoding="utf-8")

    with pytest.raises(
        reprobe.CapabilityFreezeError,
        match="native_kernel receipt byte digest mismatch",
    ):
        reprobe.validate_frozen_capability_reprobe(
            repository_root=ROOT,
            receipt_directory=copied,
        )


def test_noncanonical_and_unknown_freeze_fields_are_rejected(
    tmp_path: Path,
) -> None:
    copied = _copy_receipts(tmp_path / "noncanonical")
    freeze_path = copied / "capability-freeze.json"
    freeze = _load(freeze_path)
    freeze_path.write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(reprobe.CapabilityFreezeError, match="not canonical"):
        reprobe.validate_frozen_capability_reprobe(
            repository_root=ROOT,
            receipt_directory=copied,
        )

    copied = _copy_receipts(tmp_path / "unknown")
    freeze_path = copied / "capability-freeze.json"
    freeze = _load(freeze_path)
    freeze["post_probe_fallback"] = False
    freeze_path.write_text(_canonical_json(freeze) + "\n", encoding="utf-8")
    with pytest.raises(reprobe.CapabilityFreezeError, match="fields changed"):
        reprobe.validate_frozen_capability_reprobe(
            repository_root=ROOT,
            receipt_directory=copied,
        )


def test_live_reprobe_rejects_identity_mismatch_and_secret_bearing_receipt() -> None:
    frozen = reprobe.validate_frozen_capability_reprobe(
        repository_root=ROOT,
        receipt_directory=RECEIPTS,
    )
    receipts = {
        component: dict(receipt)
        for component, receipt in frozen.receipts.items()
    }
    mismatched = dict(receipts["spacy_pipeline"])
    mismatched["effective_identity"] = {
        **dict(mismatched["effective_identity"]),
        "model": "spacy.blank:en",
    }
    receipts["spacy_pipeline"] = mismatched
    with pytest.raises(reprobe.CapabilityFreezeError, match="identity mismatch"):
        reprobe.LiveCapabilityReprobe(
            frozen.inventory,
            receipts,
            frozen.source_binding,
        )

    receipts = {
        component: dict(receipt)
        for component, receipt in frozen.receipts.items()
    }
    secret_bearing = dict(receipts["spacy_pipeline"])
    requested = dict(secret_bearing["requested_identity"])
    requested["api_key"] = "must-not-be-frozen"
    secret_bearing["requested_identity"] = requested
    secret_bearing["effective_identity"] = dict(requested)
    _seal_live_receipt(secret_bearing)
    receipts["spacy_pipeline"] = secret_bearing
    with pytest.raises(reprobe.CapabilityFreezeError, match="secret-bearing"):
        reprobe.LiveCapabilityReprobe(
            frozen.inventory,
            receipts,
            frozen.source_binding,
        )


def test_freeze_is_exclusive_and_refuses_a_second_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = reprobe.validate_frozen_capability_reprobe(
        repository_root=ROOT,
        receipt_directory=RECEIPTS,
    )
    with pytest.raises(
        reprobe.CapabilityFreezeError,
        match="published immutable evidence",
    ):
        reprobe.freeze_live_capability_reprobe(
            published,
            repository_root=tmp_path,
            receipt_directory="published-copy",
            snapshot_path="published-snapshot.json",
        )
    repository = tmp_path / "repository"
    repository.mkdir()
    benchmark_root = (tmp_path / "external-benchmark-root").resolve()
    frozen = _fresh_test_reprobe(published)
    _stub_source_binding(monkeypatch, frozen.source_binding)
    layout = ReassessmentRunLayout.for_run(
        FRESH_TEST_RUN_ID,
        benchmark_root=benchmark_root,
    )
    result = reprobe.freeze_live_capability_reprobe(
        frozen,
        repository_root=repository,
        benchmark_root=benchmark_root,
    )
    assert result["status"] == "eligible"
    assert layout.capability_snapshot.is_file()
    snapshot = _load(layout.capability_snapshot)
    captured = date.fromisoformat(str(snapshot["captured_on"]))
    assert captured <= datetime.now(timezone.utc).date()
    assert snapshot["results"]["inventory"]["path"] == (
        "receipts/capability-inventory.json"
    )
    assert snapshot["results"]["freeze"]["path"] == (
        "receipts/capability-freeze.json"
    )
    validated = reprobe.validate_capability_snapshot(
        repository_root=repository,
        expected_run_id=FRESH_TEST_RUN_ID,
        benchmark_root=benchmark_root,
    )
    assert dict(validated) == snapshot
    with pytest.raises(
        reprobe.CapabilityFreezeError,
        match="refusing to replace frozen evidence",
    ):
        reprobe.freeze_live_capability_reprobe(
            frozen,
            repository_root=repository,
            benchmark_root=benchmark_root,
        )


def test_freeze_revalidates_source_binding_before_any_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = reprobe.validate_frozen_capability_reprobe(
        repository_root=ROOT,
        receipt_directory=RECEIPTS,
    )
    frozen = _fresh_test_reprobe(published)
    authoritative = dict(frozen.source_binding)
    forged = {
        **authoritative,
        "baseline_manifest_sha256": "0" * 64,
    }
    supplied = reprobe.LiveCapabilityReprobe(
        frozen.inventory,
        frozen.receipts,
        forged,
    )
    repository = (tmp_path / "repository").resolve()
    repository.mkdir()
    benchmark_root = (tmp_path / "external-benchmark-root").resolve()
    layout = ReassessmentRunLayout.for_run(
        FRESH_TEST_RUN_ID,
        benchmark_root=benchmark_root,
    )
    observed: dict[str, object] = {}

    def load_binding(
        actual_repository: Path,
        baseline_path: Path,
        *,
        expected_run_id: str,
        benchmark_root: str | Path,
    ) -> dict[str, object]:
        observed.update(
            {
                "repository": actual_repository,
                "baseline_path": baseline_path,
                "run_id": expected_run_id,
                "benchmark_root": benchmark_root,
            }
        )
        return dict(authoritative)

    monkeypatch.setattr(reprobe, "_source_binding", load_binding)
    with pytest.raises(
        reprobe.CapabilityFreezeError,
        match="source binding changed before freeze",
    ):
        reprobe.freeze_live_capability_reprobe(
            supplied,
            repository_root=repository,
            benchmark_root=benchmark_root,
            baseline_manifest=layout.baseline_manifest,
        )

    assert observed == {
        "repository": repository,
        "baseline_path": layout.baseline_manifest,
        "run_id": FRESH_TEST_RUN_ID,
        "benchmark_root": benchmark_root,
    }
    assert not layout.run_paths.run_root.exists()
    assert not layout.receipt_directory.exists()
    assert not layout.capability_snapshot.exists()


@pytest.mark.parametrize(
    "escaped_reference",
    ("../outside-inventory.json", "/tmp/outside-inventory.json"),
)
def test_external_snapshot_rejects_escape_references(
    tmp_path: Path,
    escaped_reference: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, benchmark_root, layout = _freeze_external_test_snapshot(
        tmp_path,
        monkeypatch,
    )
    snapshot = _load(layout.capability_snapshot)
    snapshot["results"]["inventory"]["path"] = escaped_reference
    layout.capability_snapshot.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        reprobe.CapabilityFreezeError,
        match="path binding|relative POSIX",
    ):
        reprobe.validate_capability_snapshot(
            repository_root=repository,
            expected_run_id=FRESH_TEST_RUN_ID,
            benchmark_root=benchmark_root,
        )


@pytest.mark.parametrize(
    "captured_on",
    ("2026/07/25", "not-a-date", "2999-01-01"),
)
def test_fresh_snapshot_rejects_invalid_or_future_capture_date(
    tmp_path: Path,
    captured_on: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, benchmark_root, layout = _freeze_external_test_snapshot(
        tmp_path,
        monkeypatch,
    )
    snapshot = _load(layout.capability_snapshot)
    snapshot["captured_on"] = captured_on
    layout.capability_snapshot.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(reprobe.CapabilityFreezeError, match="header drifted"):
        reprobe.validate_capability_snapshot(
            repository_root=repository,
            expected_run_id=FRESH_TEST_RUN_ID,
            benchmark_root=benchmark_root,
        )


def test_external_snapshot_rejects_symlinked_and_tampered_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, benchmark_root, layout = _freeze_external_test_snapshot(
        tmp_path,
        monkeypatch,
    )
    inventory = layout.receipt_directory / "capability-inventory.json"
    outside = tmp_path / "outside-inventory.json"
    inventory.rename(outside)
    inventory.symlink_to(outside)
    with pytest.raises(reprobe.CapabilityFreezeError, match="symlink"):
        reprobe.validate_capability_snapshot(
            repository_root=repository,
            expected_run_id=FRESH_TEST_RUN_ID,
            benchmark_root=benchmark_root,
        )

    inventory.unlink()
    inventory.write_bytes(outside.read_bytes() + b" ")
    with pytest.raises(reprobe.CapabilityFreezeError, match="byte binding"):
        reprobe.validate_capability_snapshot(
            repository_root=repository,
            expected_run_id=FRESH_TEST_RUN_ID,
            benchmark_root=benchmark_root,
        )


def test_fresh_freeze_rejects_symlinked_receipt_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    benchmark_root = (tmp_path / "external-benchmark-root").resolve()
    layout = ReassessmentRunLayout.for_run(
        FRESH_TEST_RUN_ID,
        benchmark_root=benchmark_root,
    )
    layout.run_paths.run_root.mkdir(parents=True)
    outside = tmp_path / "outside-receipts"
    outside.mkdir()
    aliased = layout.run_paths.run_root / "aliased-receipts"
    aliased.symlink_to(outside, target_is_directory=True)
    published = reprobe.validate_frozen_capability_reprobe(
        repository_root=ROOT,
        receipt_directory=RECEIPTS,
    )
    fresh = _fresh_test_reprobe(published)
    _stub_source_binding(monkeypatch, fresh.source_binding)

    with pytest.raises(reprobe.CapabilityFreezeError, match="symlink"):
        reprobe.freeze_live_capability_reprobe(
            fresh,
            repository_root=repository,
            benchmark_root=benchmark_root,
            receipt_directory=aliased,
        )


@pytest.mark.parametrize(
    ("requirement", "message"),
    [
        ("hammer,hammer", "duplicate required capabilities"),
        ("hammer,not_a_capability", "unknown required capabilities"),
    ],
)
def test_cli_rejects_duplicate_and_unknown_requirements_before_probing(
    requirement: str,
    message: str,
) -> None:
    with pytest.raises(runtime.RuntimeBindingError, match=message):
        runtime.main(["probe", "--validate-freeze", "--require", requirement])


def test_cli_threads_baseline_manifest_into_freeze(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    published = reprobe.validate_frozen_capability_reprobe(
        repository_root=ROOT,
        receipt_directory=RECEIPTS,
    )
    frozen = _fresh_test_reprobe(published)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        reprobe,
        "run_live_capability_reprobe",
        lambda **_kwargs: frozen,
    )

    def capture_freeze(
        _frozen: reprobe.LiveCapabilityReprobe,
        **kwargs: object,
    ) -> dict[str, object]:
        captured.update(kwargs)
        return {"status": "eligible"}

    monkeypatch.setattr(
        reprobe,
        "freeze_live_capability_reprobe",
        capture_freeze,
    )
    baseline = tmp_path / "state" / "baseline-manifest.json"
    exit_code = runtime.main(
        [
            "probe",
            "--run-id",
            FRESH_TEST_RUN_ID,
            "--baseline-manifest",
            str(baseline),
            "--freeze",
        ]
    )

    assert exit_code == 0
    assert captured["baseline_manifest"] == str(baseline)
    assert json.loads(capsys.readouterr().out)["run_id"] == FRESH_TEST_RUN_ID


def test_cli_reports_source_loader_failure_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_loader(*_args: object, **_kwargs: object) -> object:
        raise SourceReconciliationError("adversarial source drift")

    monkeypatch.setattr(
        reprobe,
        "load_source_baseline_manifest",
        fail_loader,
    )
    repository = (tmp_path / "repository").resolve()
    repository.mkdir()
    benchmark_root = (tmp_path / "external-benchmark-root").resolve()
    layout = ReassessmentRunLayout.for_run(
        FRESH_TEST_RUN_ID,
        benchmark_root=benchmark_root,
    )
    exit_code = runtime.main(
        [
            "probe",
            "--run-id",
            FRESH_TEST_RUN_ID,
            "--repository-root",
            str(repository),
            "--benchmark-root",
            str(benchmark_root),
            "--baseline-manifest",
            str(layout.baseline_manifest),
            "--freeze",
        ]
    )

    failure = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert failure["status"] == "ineligible"
    assert "source baseline revalidation failed" in failure["reason"]
    assert not layout.run_paths.run_root.exists()
