"""Integration evidence for the frozen HSSL reassessment capability probe."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from benchmarks.logic_pipeline import capabilities, runtime
from benchmarks.logic_pipeline import capability_reprobe as reprobe


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


def test_freeze_is_exclusive_and_refuses_a_second_write(tmp_path: Path) -> None:
    frozen = reprobe.validate_frozen_capability_reprobe(
        repository_root=ROOT,
        receipt_directory=RECEIPTS,
    )
    receipt_directory = Path("new-receipts")
    snapshot = Path("snapshot.json")

    result = reprobe.freeze_live_capability_reprobe(
        frozen,
        repository_root=tmp_path,
        receipt_directory=receipt_directory,
        snapshot_path=snapshot,
    )
    assert result["status"] == "eligible"
    assert (tmp_path / snapshot).is_file()
    with pytest.raises(
        reprobe.CapabilityFreezeError,
        match="refusing to replace frozen evidence",
    ):
        reprobe.freeze_live_capability_reprobe(
            frozen,
            repository_root=tmp_path,
            receipt_directory=receipt_directory,
            snapshot_path=snapshot,
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
