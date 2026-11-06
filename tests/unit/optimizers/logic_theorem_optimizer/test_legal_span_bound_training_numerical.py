"""Two synthetic Adam updates through the opt-in bound source-span entrypoints.

This numerical smoke test uses fictional authored rows and fresh tiny weights.
It does not evaluate statutory accuracy, load archived weights, save model
payloads, or constitute a scientific training campaign. Run it only through a
resource-admitted numerical qualifier; the pure binding cohort stays separate.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_bound_training as bound
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as custody
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.checkpoint_content_guard import CheckpointContentGuard


def _digest(value):
    return CheckpointContentGuard(value).sha256


def _source_digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _row(identifier, text, modality, actor, action, object_atom):
    return {"id": identifier, "source_text": text,
            "canonical_ir": {"rules": [{"modality": modality, "actor": actor,
                "action": action, "object": object_atom, "conditions": [],
                "exceptions": [], "temporal": []}]}}


def _bound_batch(rows, manifest, operation):
    exposure_kind = {"training": "declared_supervised_training",
                     "hparam_selection": "declared_validation_scoring"}[operation]
    eligibility, exposure = [], []
    for row in rows:
        identity = {"id": row["id"], "source_text_sha256": _source_digest(row["source_text"]),
                    "canonical_ir_sha256": _digest(row["canonical_ir"])}
        eligibility.append({**identity, "target_origin": "authored_engineering_fixture",
            "status": "eligible", "allowed_operations": [operation],
            "reason": "Fictional one-row numerical plumbing fixture; no reviewed legal gold."})
        exposure.append({**identity, "target_exposure": exposure_kind,
            "provenance_ref": "fixture:bound-training-two-update-smoke"})
    binding = custody.prepare_source_span_consumer_binding(rows,
        expected_rows_sha256=_digest(rows), split_manifest=manifest,
        expected_split_manifest_sha256=_digest(manifest),
        eligibility_records=eligibility, expected_eligibility_sha256=_digest(eligibility),
        exposure_records=exposure, expected_exposure_sha256=_digest(exposure),
        operation=operation)
    receipt = binding.receipt()
    assert receipt["status"] == "ready"
    assert receipt["semantic_authority"] is receipt["training_gold_authority"] is False
    assert receipt["evaluation_gold_authority"] is False
    inputs = {"rows": rows, "split_manifest": manifest,
              "eligibility_records": eligibility, "exposure_records": exposure}
    batch = bound.SourceSpanBoundBatch(binding, rows, manifest, eligibility, exposure)
    return batch, inputs


def _assert_false_authorities(value):
    assert all(value[key] is False for key in span.FALSE)


def test_two_bound_synthetic_updates_preserve_exact_resume_and_input_custody(tmp_path):
    training_rows = [_row("fictional-bound-train", "The agency shall disclose records.",
                          "O", "agency", "disclose", "records")]
    tuning_rows = [_row("fictional-bound-validation", "The board may retain notices.",
                        "P", "board", "retain", "notices")]
    manifest = splits.LegalIRSplitManifest(
        examples=tuple(splits.LegalIRSplitExample.from_sample(
            {"sample_id": row["id"], "text": row["source_text"]})
            for row in training_rows + tuning_rows),
        assignments={training_rows[0]["id"]: "train", tuning_rows[0]["id"]: "validation"},
        config_digest=_source_digest("fictional bound-training numerical smoke policy"),
    ).to_dict()
    training, training_inputs = _bound_batch(training_rows, manifest, "training")
    tuning, tuning_inputs = _bound_batch(tuning_rows, manifest, "hparam_selection")
    input_snapshot = deepcopy((training_inputs, tuning_inputs))
    binding_receipts = deepcopy((training.binding.receipt(), tuning.binding.receipt()))

    initial = bound.build_bound_checkpoint(training, tuning, hidden_size=8,
        embedding_dim=4, projection_width=4, batch_size=1, seed=17)
    initial_snapshot = deepcopy(initial)
    initial_sha256 = _digest(initial)
    assert initial["schema"] == span.SCHEMA
    assert initial["lineage_id"] == span.LINEAGE_ID == "source_span_formula_v1"
    assert initial["config"]["latent_dimension"] == 0
    assert initial["training_manifest_sha256"] == span.checkpoint_digest(training_rows) == _digest(training_rows)
    assert initial["tuning_manifest_sha256"] == span.checkpoint_digest(tuning_rows) == _digest(tuning_rows)
    assert initial["training_count"] == initial["tuning_count"] == 1
    assert initial["parent_checkpoint_sha256"] is None
    assert initial["progress"] == {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0}
    assert initial["optimizer_state"]["parameters"] == {}

    first = bound.train_bound_decoder(initial, training, tuning,
        expected_checkpoint_sha256=initial_sha256, max_steps=1, max_seconds=30)
    trained = first["checkpoint"]
    trained_snapshot = deepcopy(trained)
    trained_sha256 = _digest(trained)
    assert initial == initial_snapshot
    assert trained["parent_checkpoint_sha256"] == initial_sha256
    assert trained["progress"] == {"epochs_completed": 1, "row_cursor": 0, "optimizer_steps": 1}
    assert trained["model_state"] != initial["model_state"]
    assert first["report"]["optimizer_steps"] == 1
    assert first["report"]["training_executed"] is True
    assert first["report"]["checkpoint_sha256"] == trained_sha256

    second = bound.train_bound_decoder(trained, training, tuning,
        expected_checkpoint_sha256=trained_sha256, max_steps=1, max_seconds=30)
    resumed = second["checkpoint"]
    resumed_sha256 = _digest(resumed)
    assert initial == initial_snapshot
    assert trained == trained_snapshot
    assert resumed["parent_checkpoint_sha256"] == trained_sha256
    assert resumed["progress"] == {"epochs_completed": 2, "row_cursor": 0, "optimizer_steps": 2}
    assert resumed["model_state"] != trained["model_state"]
    assert second["report"]["optimizer_steps"] == 1
    assert second["report"]["training_executed"] is True
    assert second["report"]["checkpoint_sha256"] == resumed_sha256
    assert resumed["optimizer_state"]["schema"] == "adam-default-betas-eps/v1"
    moments = resumed["optimizer_state"]["parameters"]
    assert moments and all(moment["step"] == 2 for moment in moments.values())

    for checkpoint in (initial, trained, resumed):
        assert checkpoint["training_manifest_sha256"] == _digest(training_rows)
        assert checkpoint["tuning_manifest_sha256"] == _digest(tuning_rows)
        assert checkpoint["training_count"] == checkpoint["tuning_count"] == 1
        _assert_false_authorities(checkpoint)
    for result in (first, second):
        assert len(result["report"]["batch_losses"]) == 1
        assert result["report"]["tuning"]["rows_evaluated"] == 1
        assert result["report"]["tuning"]["complete"] is True
        _assert_false_authorities(result["report"])
    assert (training_inputs, tuning_inputs) == input_snapshot
    assert (training.binding.receipt(), tuning.binding.receipt()) == binding_receipts
    assert first["report"]["optimizer_steps"] + second["report"]["optimizer_steps"] == 2

    observation = {
        "schema": "source-span-bound-training-numerical-smoke/v1",
        "scope": "Two actual synthetic Adam updates on one fictional TRAIN row; one fictional validation row.",
        "optimizer_updates_executed": 2,
        "scientific_training_campaign": False,
        "archived_checkpoints_read": False,
        "legal_accuracy_established": False,
        "synthetic_optimizer_updates": 2,
        "per_call_optimizer_updates": [first["report"]["optimizer_steps"], second["report"]["optimizer_steps"]],
        "checkpoint_progress_steps": [checkpoint["progress"]["optimizer_steps"]
                                      for checkpoint in (initial, trained, resumed)],
        "lineage_id": initial["lineage_id"], "latent_dimension": 0,
        "checkpoint_sha256s": {"initial": initial_sha256, "trained": trained_sha256, "resumed": resumed_sha256},
        "parent_checkpoint_sha256s": [trained["parent_checkpoint_sha256"], resumed["parent_checkpoint_sha256"]],
        "input_sha256s": {"training_rows": _digest(training_rows), "tuning_rows": _digest(tuning_rows),
                          "complete_split_manifest": _digest(manifest)},
        "binding_input_sha256s": {"training": binding_receipts[0]["input_sha256s"],
                                 "validation": binding_receipts[1]["input_sha256s"]},
        "span_implementation": initial["implementation"],
        "bound_training_source_sha256": hashlib.sha256(Path(bound.__file__).read_bytes()).hexdigest(),
        "consumer_binding_implementation": binding_receipts[0]["implementation"],
        "all_adam_moment_steps": sorted({moment["step"] for moment in moments.values()}),
        "input_custody_unchanged": True, "input_checkpoints_unchanged": True,
        "model_state_changed_each_update": True, "training_executed": True,
        "legal_gold_targets": 0, "legal_accuracy_claimed": False, "scientific_campaign": False,
        "promotion_performed": False, "archived_weights_loaded": False,
        "model_payloads_or_checkpoints_saved": False,
    }
    observation_path = tmp_path / "smoke-summary.json"
    observation_path.write_text(json.dumps(observation, sort_keys=True, indent=2, allow_nan=False) + "\n",
                                encoding="utf-8")
    assert json.loads(observation_path.read_text(encoding="utf-8")) == observation
