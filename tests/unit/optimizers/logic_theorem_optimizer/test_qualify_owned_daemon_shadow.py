"""Small harness checks; no native workers, owner jobs or checkpoint loads."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[4]
PATH = ROOT / "scripts/ops/legal_ir/qualify_owned_daemon_shadow.py"
spec = importlib.util.spec_from_file_location("_owned_shadow_qualification_test", PATH)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


def integration_fixture():
    native = {"synthetic_provenance": deepcopy(harness.SYNTHETIC), "accepted_projection_epochs": 0,
        "sample_memory_policy": {"evaluation_passes": []},
        "summary": harness.synthetic_snapshot_fields({"state_version": "fixture"}, {})}
    capture = {"changed_components": ["legal_ir_view_logits"], "revision_only": False,
        "counts": {"changed_component_count": 1, "touched_row_count": 1, "touched_component_count": 0,
            "inserted_rows": 1, "deleted_rows": 0, "revision_witness_count": 0},
        "base_snapshot": {"component_count": 38, "component_fields": list(range(38)), "state_revision": 0},
        "result_snapshot": {"component_count": 38, "component_fields": list(range(38)), "state_revision": 1}}
    independent = {"success": True, "accepted_projection_epochs": 0, "evaluation_matches_final": False,
        "sparse_shadow": {"passed": True, "full_checkpoint_authoritative": True,
            "capture_report": capture, "checks": {"full_exact": True}}}
    completion = {"status": "completed", "promoted": False}
    evidence = dict.fromkeys(("launch", "native_result", "owner_verification", "summary_artifact",
        "log_artifact", "sparse_shadow_patch", "sparse_shadow_receipt"))
    return native, independent, completion, evidence, {"evaluation_matches_final": False}


def test_synthetic_checkpoint_passes_only_without_learning_or_evaluation_claim():
    assert all(harness.integration_checks(*integration_fixture()).values())
    assert harness.SYNTHETIC["accepted_projection_epochs"] == 0
    for key in ("daemon_main_calls", "optimizer_calls", "bridge_evaluation_calls", "async_snapshot_evaluator_calls"):
        assert harness.SYNTHETIC[key] == 0


@pytest.mark.parametrize("fault", ["verifier_evaluated", "stored_evaluated", "promoted_snapshot", "accepted",
    "evaluation_pass", "deleted", "extra_changed_component", "lost_field", "field_order", "revision",
    "missing_shadow", "missing_evidence", "fake_native", "nonboolean_check"])
def test_material_integration_or_authority_difference_fails(fault):
    native, independent, completion, evidence, stored = integration_fixture()
    capture = independent["sparse_shadow"]["capture_report"]
    if fault == "verifier_evaluated": independent["evaluation_matches_final"] = True
    elif fault == "stored_evaluated": stored["evaluation_matches_final"] = True
    elif fault == "promoted_snapshot":
        native["summary"]["latest_promoted_snapshot_evaluation"] = {"status": "succeeded"}
        native["summary"]["latest_promoted_snapshot_complete"] = True
    elif fault == "accepted": native["accepted_projection_epochs"] = 1
    elif fault == "evaluation_pass": native["sample_memory_policy"]["evaluation_passes"] = [{"phase": "synthetic"}]
    elif fault == "deleted": capture["counts"]["deleted_rows"] = 1
    elif fault == "extra_changed_component": capture["counts"]["changed_component_count"] = 2
    elif fault == "lost_field": capture["result_snapshot"]["component_fields"].pop()
    elif fault == "field_order": capture["result_snapshot"]["component_fields"].reverse()
    elif fault == "revision": capture["result_snapshot"]["state_revision"] = 0
    elif fault == "missing_shadow": independent["sparse_shadow"] = {}
    elif fault == "missing_evidence": del evidence["sparse_shadow_receipt"]
    elif fault == "fake_native": native["synthetic_provenance"] = {}
    else: independent["sparse_shadow"]["checks"]["full_exact"] = "true"
    assert not all(harness.integration_checks(native, independent, completion, evidence, stored).values())


def test_only_execute_boundary_is_synthetic(monkeypatch):
    seen, calls = [], []
    marker = object()
    def actual(mode, query, output, **kwargs):
        seen.append(("actual", mode, query, output, kwargs))
        return marker
    def synthetic(query, output, **kwargs):
        seen.append(("synthetic", "execute", query, output, kwargs))
        return marker
    monkeypatch.setattr(harness, "fixture_subprocess", synthetic)
    dispatch = harness.hybrid_dispatch(actual, calls)
    for mode in ("describe", "execute", "verify"):
        assert dispatch(mode, "query", "output", timeout_seconds=3) is marker
    assert [(row[0], row[1]) for row in seen] == [("actual", "describe"), ("synthetic", "execute"), ("actual", "verify")]
    assert [row["kind"] for row in calls] == ["actual_worker", "synthetic_fixture", "actual_worker"]
    assert all(row["wall_seconds"] >= 0 for row in calls)


def test_dispatch_retains_actual_exception_and_failed_duration():
    calls, error = [], KeyboardInterrupt("unchanged")
    def actual(*args, **kwargs):
        raise error
    with pytest.raises(KeyboardInterrupt) as caught:
        harness.hybrid_dispatch(actual, calls)("verify", "query", "output")
    assert caught.value is error
    assert calls[0]["wall_seconds"] >= 0


def test_snapshot_fixture_has_no_promoted_evaluation():
    value = harness.synthetic_snapshot_fields({"state_version": "fixture"}, {"daemon_invocation": "binding"})
    assert "latest_promoted_snapshot_evaluation" not in value
    assert value["latest_promoted_snapshot_complete"] is False
    assert value["latest_published_snapshot"]["metadata"]["synthetic_fixture"] is True


def test_scope_resource_and_protected_helper_pins():
    owner, helper = harness.helpers()
    policy = owner.resource_policy()
    assert (policy["storage_bytes"], policy["memory_mb"], policy["cpu_slots"]) == (1_000_000_000, 3072, 1)
    assert len(policy["roots"]) == 4
    assert harness.OWNER_TIMEOUT_SECONDS == 180
    assert harness.MAX_RECEIPT_BYTES == 64 * 1024 * 1024
    assert helper.PINNED_SHA == "1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd"


def test_explicit_flag_required_before_runtime_import(monkeypatch):
    monkeypatch.setattr(harness, "helpers", lambda: pytest.fail("runtime must not initialize"))
    with pytest.raises(SystemExit) as caught:
        harness.main(["--directory", "/tmp/unused", "--output", "/tmp/unused.json"])
    assert caught.value.code == 2


def test_receipt_bound_and_existing_failure_are_preserved(tmp_path, monkeypatch):
    path = tmp_path / "failure.json"
    harness.write_new(path, {"passed": False})
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        harness.write_new(path, {"passed": True})
    assert path.read_bytes() == original
    monkeypatch.setattr(harness, "MAX_RECEIPT_BYTES", 2)
    with pytest.raises(ValueError, match="receipt too large"):
        harness.write_new(tmp_path / "too_large.json", {"value": 3})


def test_receipt_publication_releases_only_after_durable_write(tmp_path, monkeypatch):
    calls = []
    class Reservation:
        def check_usage(self, path): calls.append(("check", path))
        def to_dict(self): return {"status": "retained", "reservation_id": "test"}
        def release(self, *, artifacts_durable):
            assert artifacts_durable is True
            assert (tmp_path / "receipt.json").is_file()
            calls.append(("release",))
            return {"status": "released", "reservation_id": "test"}
    actual_write = harness.write_new
    def observed_write(path, value):
        actual_write(path, value)
        calls.append(("fsynced_write",))
    monkeypatch.setattr(harness, "write_new", observed_write)
    value = {"passed": True}
    released = harness.publish_receipt(tmp_path, tmp_path / "receipt.json", value, Reservation())
    assert [row[0] for row in calls] == ["check", "fsynced_write", "release"]
    assert released["status"] == "released"
    publication = value["receipt_publication"]
    assert publication["reservation"]["status"] == "retained"
    assert publication["overall_success_requires_terminal_exit_zero_and_ledger_release"] is True


@pytest.mark.parametrize("failure", ["write", "release"])
def test_receipt_publication_failure_never_returns_success(tmp_path, monkeypatch, failure):
    calls, error = [], OSError("durability failure")
    class Reservation:
        def check_usage(self, path): pass
        def to_dict(self): return {"status": "retained", "reservation_id": "test"}
        def release(self, *, artifacts_durable):
            calls.append("release")
            raise error
    if failure == "write":
        def fail_write(*args): raise error
        monkeypatch.setattr(harness, "write_new", fail_write)
    with pytest.raises(OSError) as caught:
        harness.publish_receipt(tmp_path, tmp_path / "receipt.json", {"passed": True}, Reservation())
    assert caught.value is error
    assert calls == ([] if failure == "write" else ["release"])
    if failure == "release":
        import json
        persisted = json.loads((tmp_path / "receipt.json").read_bytes())
        assert persisted["receipt_publication"]["overall_success_requires_terminal_exit_zero_and_ledger_release"] is True


def test_fixture_bootstrap_preserves_sealed_environment_until_real_worker_check(tmp_path):
    """Dedicated filtered process; real env check, stop before configuration/use."""
    owner, helper = harness.helpers()
    environment = owner.parent_environment(helper, dict(os.environ))
    code = r'''
import importlib.util,json,os,sys
from pathlib import Path
path=Path(sys.argv[1]); spec=importlib.util.spec_from_file_location("bootstrap_test",path)
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
expected=dict(os.environ)
_,helper=h.helpers(); guard=h.deny_network(helper)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_invocation_contracts as c
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_invocation_worker as worker
assert dict(os.environ)==expected
request_path=Path.cwd()/"request.json"
request_path.write_text(json.dumps({"environment":expected}))
launch_path=Path.cwd()/"launch.json"
launch_path.write_text(json.dumps({"request":c.describe(request_path,c.MAX_REQUEST_BYTES),
    "attempt_directory":str(Path.cwd()),"daemon_argv":[]}))
# These validation stubs isolate the real _load_launch environment check from
# unrelated input/owner configuration; no full input or state is loaded.
c.validate_request=lambda value:value
c.validate_launch=lambda launch,request:None
class StopBeforeConfiguration(Exception): pass
def stop(arguments):
    assert dict(os.environ)==expected
    assert "ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner" not in sys.modules
    raise StopBeforeConfiguration("real environment equality check passed")
c.effective_configuration=stop
code=h.fixture_execute(launch_path,Path.cwd()/"result.json")
result=json.loads((Path.cwd()/"result.json").read_bytes())
assert code==1 and result["error"]["type"].endswith(".StopBeforeConfiguration"),result
assert dict(os.environ)==expected
assert guard["socket_denial_verified"] is True
print(json.dumps({"environment_equal":True,"real_worker_check_reached":True,
    "stopped_before_configuration":True,"checkpoint_or_input_loaded":False}))
'''
    completed = subprocess.run([sys.executable, "-c", code, str(PATH)], cwd=tmp_path,
        env=environment, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    observed = json.loads(completed.stdout.splitlines()[-1])
    assert observed == {"environment_equal": True, "real_worker_check_reached": True,
        "stopped_before_configuration": True, "checkpoint_or_input_loaded": False}
