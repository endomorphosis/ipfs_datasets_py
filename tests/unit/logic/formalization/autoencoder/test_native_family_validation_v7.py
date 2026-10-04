"""V7 gate boundaries; bounded execution doubles are not Lake evidence."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v6 as previous
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v7 as native
from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract_v6 as old_policy
from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract_v7 as policy
from ipfs_datasets_py.logic.formalization.autoencoder import parallel_projection_checks_v3 as parallel
from ipfs_datasets_py.logic.formalization.autoencoder import ui_source_contract_384_v5 as adapter
from ipfs_datasets_py.logic.formalization.autoencoder import native_ui_bounded_event_calculus as ec


def prepared():
    path = Path(__file__).resolve().parents[4] / "fixtures/logic/ui_bounded_event_v1/cases.py"
    spec = importlib.util.spec_from_file_location("v7_native_ui_ec_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    row = module.cases()[1]
    return adapter.prepare_family_targets(row["source_text"], row["candidate"], **row["options"])


@pytest.mark.parametrize("domain", ("legal_ir", "intent_ir", "security_ir", "ui_ux_ir"))
def test_all_family_floors_and_evidence_requirements_remain_unchanged(domain):
    old, current = old_policy.domain_projection_policy(domain), policy.domain_projection_policy(domain)
    for key in ("family_inventory", "minimum_batch_floor", "required_projection_evidence",
                "all_emitted_projections_require_validation", "narrow_request_can_complete",
                "inapplicability_can_waive_minimum_batch_floor"):
        assert current[key] == old[key]
    assert len(current["family_inventory"]) == 40
    assert current["policy_id"] != old["policy_id"]
    assert parallel.native is native and parallel.validation is policy


def test_v7_dispatches_ec_and_every_preserved_projection_without_old_issuer_upgrade():
    packet = prepared()
    receipt = native.prepare_native_family_lean(packet["report"], source_inputs=packet["source_inputs"])
    assert all(row["parser_status"] == "passed" for row in receipt["per_projection"])
    assert len(receipt["per_projection"]) == len(packet["report"]["projections"]) == 5
    assert not receipt["backend_executed"]
    assert all(row["lake_status"] == "not_run" for row in receipt["per_projection"])
    ec_row = next(row for row in receipt["per_projection"] if row["projection_id"] == ec.PROJECTION_ID)
    assert ec_row["lowering"]["capability_floor_eligible"]
    with pytest.raises(ValueError, match="known native family producer schema"):
        previous.prepare_native_family_lean(packet["report"], source_inputs=packet["source_inputs"])


@pytest.fixture
def tool_double(monkeypatch, tmp_path):
    path = tmp_path / "bounded-external-tool-double"
    path.write_text("test dependency; never executed as Lean or Java\n")
    path.chmod(0o755)
    calls = []

    class Runner:
        def run(self, request):
            calls.append(request)
            text = "Lake version unit (Lean version 4.30.0)" if request.argv[-1] == "--version" else "UNIT ONLY"
            return SimpleNamespace(ok=True, stdout=text, stderr="", returncode=0, timed_out=False,
                output_truncated=False, workspace_limit_exceeded=False)

    monkeypatch.setattr(native, "BoundedToolRunner", Runner)
    # Native TLA's bounded runner is a separate subprocess boundary.
    monkeypatch.setattr(native.tla, "BoundedToolRunner", Runner)
    return path, calls


def test_partial_live_custom_report_still_blocks_strict_training_and_detached_authority(tool_double, tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated_v7 as trainer
    packet = prepared()
    path, calls = tool_double
    handle = native.build_native_family_lake(packet["report"], source_inputs=packet["source_inputs"],
        lake_executable=str(path), java_executable=str(path), tla2tools_jar=str(path))
    wire = native.verify_native_family_lake(handle, packet["report"])
    assert wire["execution"]["command"][1:] == ["build", "UIUXIR"]
    observation = policy.validate_projection_report(packet["report"], lake_execution=handle)
    assert not policy.evaluate_projection_training_batch([observation], domain_id="ui_ux_ir")["strict_training_allowed"]
    with pytest.raises(ValueError):
        native.verify_native_family_lake(handle.to_dict(), packet["report"])
    with pytest.raises(ValueError):
        previous.verify_native_family_lake(handle, packet["report"])
    destination = tmp_path / "must-not-train"
    with pytest.raises(ValueError):
        trainer.train_validated_family_projection_autoencoder([observation], [observation], domain_id="ui_ux_ir",
            output_dir=destination, epochs=1, latent_width=2)
    assert calls and not destination.exists()


def test_custom_report_retains_every_projection_in_loss_and_archive_is_not_a_target():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated_v7 as trainer
    report = prepared()["report"]
    seen = []
    def atoms(payload):
        seen.append(deepcopy(payload))
        return [native._raw(payload).decode()]
    rows = trainer._reports([report], atoms=atoms)
    assert seen == [row["payload"] for row in report["projections"]]
    assert ec.PROJECTION_ID in rows[0] and "ui_ux_ir:event_calculus" not in rows[0]
    coverage = {"untrained_projection_ids": [], "projections": [
        {"row": 0, "projection_id": identity, "has_coverage": True} for identity in rows[0]]}
    assert trainer._loss_coverage(rows, coverage)["projection_occurrences"] == 5
    coverage["projections"].pop()
    with pytest.raises(ValueError, match="every emitted projection"):
        trainer._loss_coverage(rows, coverage)


def test_v6_checkpoint_is_not_implicitly_migrated(tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated_v6 as old
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated_v7 as new
    assert old.SCHEMA != new.SCHEMA
    with pytest.raises(ValueError, match="closed validated checkpoint descriptor"):
        new._read({"schema": old.SCHEMA, "path": str(tmp_path / "never-opened.json"), "sha256": "0"*64})
