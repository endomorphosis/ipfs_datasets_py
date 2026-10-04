"""Synthetic metadata only: no model, native proof, training or qualification."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[5]
MODULE = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/decoder_length_trial.py"
SPEC = importlib.util.spec_from_file_location("length_trial_subject", MODULE)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


def inputs():
    codec = {"target_vocabulary": ["PAD", "BOS", "EOS", "a", "b"]}
    lineage = dict(lane_id="source_384d", domain_id="legal_ir", dimension=384,
        runtime_id="explicit-source384-parent/v1", checkpoint_sha256="a" * 64,
        representation_id="verified-local-384", encoder_context_tokens=512,
        head_id="primary384", codec=codec, codec_sha256=subject.digest(codec),
        bos_token_id=1, eos_token_id=2, pad_token_id=0, codec_origin="inherited",
        codec_fit_training_ids_sha256=None, inherited_max_target_tokens=64, owner_max_target_tokens=1024)
    rows = [dict(id="row-" + str(i), group_id="group-" + str(i), split=split,
        source_sha256=subject.digest([i, "source"]), normalized_source_sha256=subject.digest([i, "normalized"]),
        target_sha256=subject.digest([i, "target"]), codec_sha256=lineage["codec_sha256"],
        token_ids=[1, 3, 4, 2], input_status="ready", input_sha256=subject.digest([i, "input"]), teacher_replay=None)
        for i, split in enumerate(("train", "validation", "test"))]
    return lineage, rows


def prepare(lineage, rows, **options):
    return subject.prepare_trial(lineage, rows, split_manifest=subject.split_manifest(rows), **options)


def migration(lineage):
    return dict(schema="explicit-decoder-length-migration/v1", parent_checkpoint_sha256=lineage["checkpoint_sha256"],
        parent_runtime_id=lineage["runtime_id"], new_runtime_id="explicit-length-owner/v2",
        old_max_target_tokens=64, new_max_target_tokens=512, codec_sha256=lineage["codec_sha256"],
        encoder_context_tokens=lineage["encoder_context_tokens"], inherited_tensor_sha256="b" * 64,
        migrated_inherited_tensor_sha256="b" * 64, new_checkpoint_sha256="c" * 64)


def replay_scope(lineage, rows):
    scope = dict(scope_id="diagnostic-source-scope", teacher_checkpoint_sha256="d" * 64,
        codec_sha256=lineage["codec_sha256"], split="train", head_id=lineage["head_id"],
        distribution="raw", eligible_training_ids_sha256=subject.digest([rows[0]["id"]]))
    rows[0]["teacher_replay"] = {key: scope[key] for key in
        ("scope_id", "teacher_checkpoint_sha256", "codec_sha256", "head_id", "distribution")}
    rows[0]["teacher_replay"].update(reference_prefix_sha256=subject.digest(rows[0]["token_ids"][:-1]),
        teacher_logits_sha256="e" * 64, token_mask=[True] * 3)
    return scope


def test_all_requested_limits_retained_and_parent_not_silently_extended():
    lineage, rows = inputs()
    original = deepcopy((lineage, rows))
    plan = prepare(lineage, rows)
    assert plan["requested_output_limits"] == [64, 128, 256, 512, 1024]
    assert plan["requested_trial_count"] == 5 and plan["ready_trial_count"] == 1
    assert [t["training_admission"] for t in plan["trials"]] == ["ready", "blocked", "blocked", "blocked", "blocked"]
    assert all(t["selected_row_count"] == 3 for t in plan["trials"])
    assert (lineage, rows) == original
    assert all(plan[key] is False for key in subject.FALSE)
    assert plan["generation_temperature"] == 0 and plan["distillation_temperature"] is None
    assert plan["trials"][0]["rows"][0]["used_for_fit"] is True
    assert not any(r["used_for_fit"] for r in plan["trials"][0]["rows"][1:])


@pytest.mark.parametrize("lane,dimension", [("legacy_8d",8),("source_384d",384),("multilingual_768d",768)])
def test_explicit_lanes_never_selected_only_by_dimension(lane, dimension):
    lineage, rows = inputs()
    lineage.update(lane_id=lane, dimension=dimension)
    if lane == "legacy_8d": lineage["encoder_context_tokens"] = None
    assert prepare(lineage, rows)["lineage"]["lane_id"] == lane
    lineage["dimension"] = 999
    with pytest.raises(ValueError, match="lane dimension"): prepare(lineage, rows)


def test_whole_target_over_limit_remains_blocked_without_prefix_truncation():
    lineage, rows = inputs()
    rows[0]["token_ids"] = [1] + [3] * 63 + [2]
    plan = prepare(lineage, rows)
    assert plan["trials"][0]["rows"][0]["target_tokens_including_bos_eos"] == 65
    assert "complete_target_exceeds_output_limit" in plan["trials"][0]["rows"][0]["reasons"]
    assert plan["trials"][0]["training_admission"] == "blocked"
    assert len(rows[0]["token_ids"]) == 65


@pytest.mark.parametrize("tokens", [[1,3],[1,3,0,2],[1,2,3,2],[1,1,3,2],[3,4,2],[True,3,2],[1,99,2]])
def test_requires_complete_original_canonical_token_envelope(tokens):
    lineage, rows = inputs(); rows[0]["token_ids"] = tokens
    with pytest.raises(ValueError): prepare(lineage, rows)


@pytest.mark.parametrize("key", ["group_id","source_sha256","normalized_source_sha256","input_sha256"])
def test_split_leakage_rejected_before_trial_generation(key):
    lineage, rows = inputs(); rows[1][key] = rows[0][key]
    with pytest.raises(ValueError, match="cross-split"): prepare(lineage, rows)


def test_external_partition_manifest_must_match():
    lineage, rows = inputs(); manifest = subject.split_manifest(rows)
    rows[0]["group_id"] = "changed"
    with pytest.raises(ValueError, match="immutable split manifest"):
        subject.prepare_trial(lineage, rows, split_manifest=manifest)


def test_fitted_vocabulary_only_training_tokens_and_ids():
    lineage, rows = inputs(); lineage.update(codec_origin="train_only",
        codec_fit_training_ids_sha256=subject.digest([rows[0]["id"]]))
    assert prepare(lineage, rows)["ready_trial_count"] == 1
    rows[0]["token_ids"] = [1,3,2]
    with pytest.raises(ValueError, match="absent from training"): prepare(lineage, rows)


def test_validation_id_cannot_enter_codec_fit():
    lineage, rows = inputs(); lineage.update(codec_origin="train_only",
        codec_fit_training_ids_sha256=subject.digest([r["id"] for r in rows]))
    with pytest.raises(ValueError, match="exactly the training split"): prepare(lineage, rows)


def test_missing_native_inputs_preserve_denominator_and_block_training():
    lineage, rows = inputs(); rows[0].update(input_status="missing_native", input_sha256=None)
    trial = prepare(lineage, rows)["trials"][0]
    assert trial["status"] == "partial" and trial["ready_row_count"] == 2
    assert trial["training_admission"] == "blocked" and trial["rows"][0]["reasons"] == ["missing_native"]


def test_missing_validation_keeps_training_admission_separate_from_coverage():
    lineage, rows = inputs(); rows[1].update(input_status="quarantined", input_sha256=None)
    trial = prepare(lineage, rows)["trials"][0]
    assert trial["status"] == "partial" and trial["training_admission"] == "ready"
    assert trial["selected_row_count"] == 3 and trial["ready_row_count"] == 2


def test_explicit_migration_is_structural_only_preserves_fixed_encoder_and_codec():
    lineage, rows = inputs(); value = migration(lineage)
    plan = prepare(lineage, rows, migration=value)
    assert plan["ready_trial_count"] == 4
    assert plan["trials"][1]["requires_migration_authentication"] is True
    assert plan["migration_authenticated"] is False and plan["checkpoint_authenticated"] is False
    assert plan["encoder_context_tokens"] == 512 and plan["encoder_context_changed"] is False
    assert plan["trials"][-1]["training_admission"] == "blocked"


@pytest.mark.parametrize("key,value", [("parent_checkpoint_sha256","f"*64),("parent_runtime_id","wrong"),
    ("new_runtime_id","explicit-source384-parent/v1"),("codec_sha256","f"*64),("encoder_context_tokens",1024),
    ("old_max_target_tokens",32),("new_max_target_tokens",2048),("migrated_inherited_tensor_sha256","f"*64),
    ("new_checkpoint_sha256","a"*64)])
def test_migration_cannot_relabel_ancestry_context_or_tensors(key,value):
    lineage, rows = inputs(); spec = migration(lineage); spec[key] = value
    with pytest.raises(ValueError): prepare(lineage, rows, migration=spec)


def test_diagnostic_kd_requires_scope_and_replay_but_never_claims_qualification():
    lineage, rows = inputs()
    missing = prepare(lineage, rows, objective="diagnostic_kd")
    assert missing["trials"][0]["rows"][0]["reasons"] == ["teacher_scope_missing"]
    scope = replay_scope(lineage, rows)
    plan = prepare(lineage, rows, objective="diagnostic_kd", teacher_scope=scope)
    assert plan["trials"][0]["training_admission"] == "ready"
    assert plan["distillation_temperature"] == 1 and plan["generation_temperature"] == 0
    assert plan["production_kd_eligible"] is False and plan["teacher_qualified"] is False
    rows[0]["teacher_replay"] = None
    assert prepare(lineage, rows, objective="diagnostic_kd", teacher_scope=scope)["trials"][0]["rows"][0]["reasons"] == ["teacher_replay_missing"]


@pytest.mark.parametrize("key,value", [("head_id","other"),("codec_sha256","f"*64),
    ("reference_prefix_sha256","f"*64),("teacher_checkpoint_sha256","f"*64),
    ("token_mask",[True]),("token_mask",[1,1,1])])
def test_cross_head_prefix_or_mask_replay_rejected(key,value):
    lineage, rows = inputs(); scope = replay_scope(lineage, rows)
    rows[0]["teacher_replay"][key] = value
    with pytest.raises(ValueError): prepare(lineage, rows, objective="diagnostic_kd", teacher_scope=scope)


def test_all_excluded_kd_tokens_block_fit_not_false_zero_loss_success():
    lineage, rows = inputs(); scope = replay_scope(lineage, rows)
    rows[0]["teacher_replay"]["token_mask"] = [False]*3
    trial = prepare(lineage, rows, objective="diagnostic_kd", teacher_scope=scope)["trials"][0]
    assert trial["training_admission"] == "blocked"
    assert trial["rows"][0]["reasons"] == ["teacher_scope_excludes_all_tokens"]


def test_control_does_not_accept_teacher_scope():
    lineage, rows = inputs(); scope = replay_scope(lineage, rows)
    with pytest.raises(ValueError, match="reference-only"): prepare(lineage, rows, teacher_scope=scope)


def test_replay_detects_changed_rows_plan_or_cap():
    lineage, rows = inputs(); options = {"split_manifest":subject.split_manifest(rows)}
    plan = subject.prepare_trial(lineage, rows, **options)
    assert subject.validate_trial(plan,lineage,rows,**options) == plan
    plan["trials"][0]["rows"][0]["status"] = "blocked"
    with pytest.raises(ValueError, match="plan differs"): subject.validate_trial(plan,lineage,rows,**options)


@pytest.mark.parametrize("limits", [[True],[64,64],[0],[2048],[]])
def test_invalid_caps_rejected(limits):
    lineage, rows = inputs()
    with pytest.raises(ValueError): prepare(lineage, rows, output_limits=limits)


def test_import_and_preparation_have_no_numerical_dependencies():
    code = "import importlib.util,sys; s=importlib.util.spec_from_file_location('m',sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); assert not ({'torch','transformers','numpy','ipfs_datasets_py'} & set(sys.modules))"
    subprocess.run([sys.executable,"-c",code,str(MODULE)],check=True,capture_output=True,text=True)


def test_training_only_diagnostic_is_not_convergence_ready():
    lineage, rows = inputs(); rows = rows[:1]
    trial = prepare(lineage,rows)["trials"][0]
    assert trial["training_admission"] == "ready" and trial["validation_row_count"] == 0
    assert trial["convergence_evaluation_ready"] is False


def test_test_coverage_does_not_block_ready_train_and_validation():
    lineage, rows = inputs(); rows[2].update(input_status="quarantined", input_sha256=None)
    trial = prepare(lineage,rows)["trials"][0]
    assert trial["status"] == "partial" and trial["training_admission"] == "ready"
    assert trial["convergence_evaluation_ready"] is True and trial["ready_validation_row_count"] == 1
    assert trial["rows"][2]["used_for_fit"] is False


def test_unready_validation_blocks_convergence_evaluation_only():
    lineage, rows = inputs(); rows[1].update(input_status="missing_native", input_sha256=None)
    trial = prepare(lineage,rows)["trials"][0]
    assert trial["training_admission"] == "ready" and trial["validation_row_count"] == 1
    assert trial["convergence_evaluation_ready"] is False


@pytest.mark.parametrize("key,value",[("input_sha256",[]),("input_status","unknown")])
def test_malformed_representation_binding_is_rejected(key,value):
    lineage, rows = inputs(); rows[0][key] = value
    with pytest.raises(ValueError): prepare(lineage,rows)


def test_unhashable_lane_identity_is_rejected_cleanly():
    lineage,rows=inputs(); lineage["lane_id"]=[]
    with pytest.raises(ValueError): prepare(lineage,rows)
