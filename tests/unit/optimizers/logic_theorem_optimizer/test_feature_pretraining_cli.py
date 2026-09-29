"""Feature training is an explicit purpose and never a formalization bypass."""
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import (
    TrainingConfig, TrainingJobSpec, TrainingJobValidationError,
)

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("feature_pretraining_cli", ROOT / "scripts/ops/legal_ir/run_incremental_autoencoders.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def test_raw_objective_is_opt_in_and_preserves_archived_default_identity():
    default = TrainingConfig()
    assert "projection_reconstruction_objective" not in default.to_dict()
    assert "projection_reconstruction_objective" not in default.projection_kwargs()
    assert TrainingConfig.from_dict({**default.to_dict(), "projection_reconstruction_objective": "safety_projected"}).to_dict() == default.to_dict()
    raw = TrainingConfig(projection_reconstruction_objective="raw_decoder")
    assert raw.projection_kwargs()["projection_reconstruction_objective"] == "raw_decoder"


@pytest.mark.parametrize("value", [None, True, [], "projected", "disable_checks"])
def test_unknown_objectives_are_rejected(value):
    with pytest.raises(TrainingJobValidationError, match="reconstruction_objective"):
        TrainingConfig(projection_reconstruction_objective=value)


@pytest.mark.parametrize("extra", [[], ["--validation-jsonl", "validation"],
    ["--validation-jsonl", "validation", "--feature-input-manifest", "manifest", "--publish-repository", "justicedao/uscode-autoformal-span-cache"],
    ["--validation-jsonl", "validation", "--feature-input-manifest", "manifest", "--execution-mode", "inference"]])
def test_feature_mode_rejects_missing_provenance_or_wrong_execution_before_work(tmp_path, extra):
    output = tmp_path / "uncreated"
    with pytest.raises(SystemExit):
        cli.main(["--state-directory", str(output), "--input-jsonl", "input",
                  "--shared-targets", "targets", "--target-snapshot-id", "sha256:" + "a" * 64,
                  "--training-purpose", "feature_pretraining", *extra])
    assert not output.exists()


def test_purpose_cannot_change_on_resume(tmp_path):
    cli.bind_training_purpose(tmp_path, "feature_pretraining")
    cli.bind_training_purpose(tmp_path, "feature_pretraining")
    with pytest.raises(ValueError, match="new state directory"):
        cli.bind_training_purpose(tmp_path, "formalization")


def test_feature_templates_are_separate_raw_variants_and_require_disjoint_validation(tmp_path):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState
    checkpoint = tmp_path / "baseline.json"
    checkpoint.write_text(ModalAutoencoderTrainingState().to_json())
    train = {"record_id": "a" * 64, "sample": {"title": "5", "section": "1", "text": "The agency shall retain records."}}
    tune = {"record_id": "b" * 64, "sample": {"title": "5", "section": "2", "text": "The officer shall file reports."}}
    options = dict(state_directory=tmp_path, checkpoint=checkpoint,
                   source_hashes={key: "0" * 64 for key in ("compiler", "decompiler", "parser", "autoencoder", "samples", "worker")})
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "cas") as registry:
        formal = cli.make_templates(registry, [train], validation_records=[tune], **options)[0]
        feature = cli.make_templates(registry, [train], validation_records=[tune], training_purpose="feature_pretraining", **options)[0]
        assert formal.variant != feature.variant
        assert feature.training_config.projection_reconstruction_objective == "raw_decoder"
        assert formal.training_config.projection_reconstruction_objective == "safety_projected"
        assert feature.samples == formal.samples and feature.validation_samples == formal.validation_samples
        assert feature.capture_sparse_patches and feature.candidate_storage == "sparse"
        assert TrainingJobSpec.from_dict(feature.to_dict()).canonical_sha256 == feature.canonical_sha256
        for validation in ([], [train]):
            with pytest.raises(TrainingJobValidationError, match="disjoint"):
                cli.make_templates(registry, [train], validation_records=validation,
                    training_purpose="feature_pretraining", **options)


def test_default_purpose_retains_formalization():
    args = cli.parser().parse_args(["--state-directory", "state", "--input-jsonl", "input"])
    assert args.training_purpose == "formalization"
    assert cli._training_purpose(vars(args)) == "formalization"
    assert not hasattr(args, "disable_qualification")


def test_local_embedding_rows_resume_after_json_roundtrip_and_reject_changed_content(tmp_path):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState
    checkpoint = tmp_path / "baseline.json"
    checkpoint.write_text(ModalAutoencoderTrainingState().to_json())
    source = tmp_path / "input.jsonl"
    source.write_text(json.dumps({"title": "5", "section": "1", "text": "The agency shall retain records.",
                                  "embedding_vector": [0.25, 0.75], "embedding_model": "local:verified"}) + "\n")
    records = cli.local_records(source)
    options = dict(state_directory=tmp_path, checkpoint=checkpoint,
                   source_hashes={key: "0" * 64 for key in ("compiler", "decompiler", "parser", "autoencoder", "samples", "worker")})
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "cas") as registry:
        first = cli.make_templates(registry, records, **options)
        resumed = cli.make_templates(registry, cli.local_records(source), **options)
        assert first[0].canonical_sha256 == resumed[0].canonical_sha256
        records[0]["sample"]["embedding_vector"] = (0.5, 0.5)
        with pytest.raises(ValueError, match="immutable input identity collision"):
            cli.make_templates(registry, records, **options)


def test_feature_cycle_routes_to_private_runner_without_legal_qualification(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_feature_training as feature
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_feature_inputs as inputs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_qualified_training as formal
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState
    checkpoint = tmp_path / "base.json"
    checkpoint.write_text(ModalAutoencoderTrainingState().to_json())
    targets = tmp_path / "targets"
    targets.write_text("{}")
    train = tmp_path / "train.jsonl"
    tune = tmp_path / "tune.jsonl"
    train.write_text(json.dumps({"title": "5", "section": "1", "text": "The agency shall retain records."}) + "\n")
    tune.write_text(json.dumps({"title": "5", "section": "2", "text": "The officer shall submit reports."}) + "\n")
    verification = {"local_embedding_verification": True, "admitted": False,
        "training": {"count": 1, "rows": {"sha256": cli._sha(train)}},
        "validation": {"count": 1, "rows": {"sha256": cli._sha(tune)}}}
    monkeypatch.setattr(inputs, "verify_feature_training_inputs", lambda *args: verification)
    hashes = {key: "0" * 64 for key in ("compiler", "decompiler", "parser", "autoencoder", "samples", "worker")}
    monkeypatch.setattr(cli, "_pin", lambda **kwargs: hashes)
    monkeypatch.setattr(cli, "orchestration_hashes", lambda: {"bound": "1" * 64})
    def never(*args, **kwargs):
        raise AssertionError("feature pretraining must not execute formal qualification")
    monkeypatch.setattr(formal, "run_qualified_incremental_training", never)
    calls = []
    def run(registry, templates, **kwargs):
        calls.append(kwargs)
        assert templates[0].training_config.projection_reconstruction_objective == "raw_decoder"
        assert kwargs["producer_identity"]["embedding_verification"] == verification
        assert kwargs["control_transport"] == "quack"
        return {"dispatched_run_ids": [], "qualified": False, "admitted": False}
    monkeypatch.setattr(feature, "run_feature_incremental_training", run)
    result = cli.run_cycle({"state_directory": str(tmp_path), "training_purpose": "feature_pretraining",
        "feature_input_manifest": "manifest", "input_jsonl": str(train), "validation_jsonl": str(tune),
        "checkpoint": str(checkpoint), "shared_targets": str(targets), "target_snapshot_id": "sha256:" + "b" * 64,
        "source_language": "en", "model_variant": "test", "max_seconds": 10, "shard_count": 1,
        "shard_index": 0, "workers": 2, "max_batches": 2, "memory_mb": 8192,
        "cycle_receipt": str(tmp_path / "cycle.json")})
    assert len(calls) == 1 and result["training_purpose"] == "feature_pretraining"
    assert result["feature_input_verification"] == verification
    assert result["admitted"] is False and result["formalized"] is False
    assert result["weight_publications"] == []


def test_feature_input_replacement_between_reads_cannot_rebind_training_rows(tmp_path):
    source = tmp_path / "train.jsonl"
    source.write_text(json.dumps({"title": "5", "section": "1", "text": "Original source"}) + "\n")
    already_read = cli.local_records(source)
    source.write_text(json.dumps({"title": "5", "section": "1", "text": "Replacement source"}) + "\n")
    verification = {"training": {"count": 1, "rows": {"sha256": cli._sha(source)}}}
    with pytest.raises(ValueError, match="changed between intake and verification"):
        cli.bind_verified_feature_records(already_read, [], verification)
