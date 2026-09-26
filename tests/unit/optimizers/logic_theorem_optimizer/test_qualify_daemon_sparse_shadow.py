"""Lightweight sparse-shadow harness contracts; no endpoint loads or replay."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
PATH = ROOT / "scripts/ops/legal_ir/qualify_daemon_sparse_shadow.py"
spec = importlib.util.spec_from_file_location("_sparse_shadow_harness_test", PATH)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


def result(changed):
    case = {"name": harness.CASE_NAMES[int(changed)], "base": {"sha256": "base"},
            "final": {"sha256": "final"}}
    value = {"passed": True, "mode": "diagnostic_only", "full_checkpoint_authoritative": True,
        "base_artifact": deepcopy(case["base"]), "final_artifact": deepcopy(case["final"]),
        "checks": {"exact": True}, "admitted": False, "promoted": False, "publication_performed": False,
        "registered_base_authority_verified": False, "optimizer_acceptance_asserted": False,
        "capture_report": {"changed_components": ["legal_ir_view_logits"] if changed else [],
            "revision_only": False,
            "counts": {"changed_component_count": int(changed), "touched_row_count": 6 if changed else 0,
                "touched_component_count": 0, "inserted_rows": 6 if changed else 0,
                "deleted_rows": 0, "revision_witness_count": 0},
            "base_snapshot": {"component_fields": list(range(38)), "state_revision": 0},
            "result_snapshot": {"component_fields": list(range(38)), "state_revision": 0}}}
    return value, case


@pytest.mark.parametrize("changed", [False, True])
def test_exact_expected_endpoint_case(changed):
    value, case = result(changed)
    assert all(harness.result_checks(value, case).values())


@pytest.mark.parametrize("fault", ["wrong_final", "zero_changes", "dropped_field", "false_check",
    "nonboolean_check", "admission", "component_replacement", "invented_revision", "revision_only",
    "owner_authority"])
def test_material_changed_case_mismatch_rejects(fault):
    value, case = result(True)
    if fault == "wrong_final": value["final_artifact"]["sha256"] = "other"
    elif fault == "zero_changes": value["capture_report"]["counts"]["touched_row_count"] = 0
    elif fault == "dropped_field": value["capture_report"]["result_snapshot"]["component_fields"].pop()
    elif fault == "false_check": value["checks"]["exact"] = False
    elif fault == "nonboolean_check": value["checks"]["exact"] = "true"
    elif fault == "admission": value["admitted"] = True
    elif fault == "invented_revision": value["capture_report"]["result_snapshot"]["state_revision"] = 1
    elif fault == "revision_only": value["capture_report"]["revision_only"] = True
    elif fault == "owner_authority": value["registered_base_authority_verified"] = True
    else: value["capture_report"]["counts"]["touched_component_count"] = 1
    assert not all(harness.result_checks(value, case).values())


def test_pinned_helper_scope_and_resource_budget():
    owner, helper = harness.helpers()
    assert owner.resource_policy()["storage_bytes"] == 1_000_000_000
    assert owner.resource_policy()["memory_mb"] == 3072
    assert owner.resource_policy()["cpu_slots"] == 1
    assert len(owner.resource_policy()["roots"]) == 4
    assert harness.TIMEOUT_SECONDS == 180
    assert helper.PINNED_SHA == "1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd"


def test_explicit_offline_replay_before_any_helper_or_package_import(monkeypatch):
    monkeypatch.setattr(harness, "helpers", lambda: pytest.fail("must not initialize runtime"))
    with pytest.raises(SystemExit) as caught:
        harness.main(["--directory", "/tmp/unused", "--output", "/tmp/unused.json"])
    assert caught.value.code == 2


def test_diagnostic_receipt_write_is_exclusive_and_finite(tmp_path):
    path = tmp_path / "receipt.json"
    harness.write_new(path, {"passed": False, "error": "preserved"})
    original = path.read_bytes()
    assert json.loads(original)["error"] == "preserved"
    with pytest.raises(FileExistsError):
        harness.write_new(path, {"passed": True})
    assert path.read_bytes() == original
    with pytest.raises(ValueError):
        harness.write_new(tmp_path / "bad.json", {"seconds": float("nan")})
