"""Both supervised batches must pass custody before numerical-owner dispatch.

Only build_checkpoint/train_decoder are replaced by recording spies. Synthetic
checkpoint headers contain deliberately unqualified placeholder numerical state;
these tests neither restore a model nor execute optimizer updates.
"""
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as binding_owner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_bound_training as owner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.checkpoint_content_guard import CheckpointContentGuard


def digest(value):
    return CheckpointContentGuard(value).sha256


def text_digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fictional_row(identifier, actor, modality, action, object_name):
    modal_text = "may" if modality == "P" else "shall"
    return {"id": identifier, "source_text": f"The {actor} {modal_text} {action} {object_name}.",
            "canonical_ir": {"rules": [{"modality": modality, "actor": actor, "action": action,
                "object": object_name, "conditions": [], "exceptions": [], "temporal": []}]}}


def fictional_rows():
    training = [fictional_row("train-a", "agency", "O", "disclose", "records"),
                fictional_row("train-b", "auditor", "O", "inspect", "files")]
    tuning = [fictional_row("validation-a", "board", "P", "retain", "notices"),
              fictional_row("validation-b", "clerk", "O", "publish", "reports")]
    return training, tuning


def split_manifest(training, tuning):
    return splits.LegalIRSplitManifest(
        examples=tuple(splits.LegalIRSplitExample.from_sample(
            {"sample_id": row["id"], "text": row["source_text"]}) for row in (*training, *tuning)),
        assignments={**{row["id"]: "train" for row in training},
                     **{row["id"]: "validation" for row in tuning}},
        config_digest=text_digest("fictional frozen bound-training policy"),
    ).to_dict()


def make_batch(rows, manifest, operation, *, blocked=None):
    rows, manifest = deepcopy(rows), deepcopy(manifest)
    eligibility, exposure = [], []
    for index, row in enumerate(rows):
        exact = {"id": row["id"], "source_text_sha256": text_digest(row["source_text"]),
                 "canonical_ir_sha256": digest(row["canonical_ir"])}
        eligibility.append({**exact, "target_origin": "authored_engineering_fixture",
            "status": "unknown" if blocked == index else "eligible", "allowed_operations": [operation],
            "reason": "Fictional supervised dispatch fixture; no reviewed law or gold."})
        exposure.append({**exact, "target_exposure": "declared_supervised_training"
            if operation == "training" else "declared_validation_scoring",
            "provenance_ref": "fixture:fictional-bound-training"})
    binding = binding_owner.prepare_source_span_consumer_binding(rows,
        expected_rows_sha256=digest(rows), split_manifest=manifest,
        expected_split_manifest_sha256=digest(manifest), eligibility_records=eligibility,
        expected_eligibility_sha256=digest(eligibility), exposure_records=exposure,
        expected_exposure_sha256=digest(exposure), operation=operation)
    return owner.SourceSpanBoundBatch(binding=binding, rows=rows, split_manifest=manifest,
        eligibility_records=eligibility, exposure_records=exposure)


@pytest.fixture
def batches():
    training, tuning = fictional_rows()
    manifest = split_manifest(training, tuning)
    return make_batch(training, manifest, "training"), make_batch(tuning, manifest, "hparam_selection")


def fake_checkpoint(training, tuning=None):
    """An exact custody header, explicitly not a restorable neural checkpoint."""
    tune_rows = [] if tuning is None else tuning.rows
    return {"schema": span.SCHEMA, "lineage_id": span.LINEAGE_ID,
        "config": {"latent_dimension": 0, "batch_size": 1}, "implementation": span._implementation(),
        "training_manifest_sha256": digest(training.rows), "training_count": len(training.rows),
        "tuning_manifest_sha256": digest(tune_rows), "tuning_count": len(tune_rows),
        "model_state": {"unqualified_fixture_weights": [1., 2.]},
        "optimizer_state": {"unqualified_fixture_moments": []},
        "progress": {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0},
        "parent_checkpoint_sha256": None, **span.FALSE}


@pytest.fixture
def numerical_spies(monkeypatch):
    calls, marker = [], object()

    def build(training_examples, tuning_examples=(), **options):
        calls.append({"owner": "build", "training": deepcopy(training_examples),
                      "tuning": deepcopy(tuning_examples), "options": deepcopy(options)})
        return marker

    def train(checkpoint, training_examples, tuning_examples=(), **options):
        calls.append({"owner": "train", "checkpoint": deepcopy(checkpoint),
                      "training": deepcopy(training_examples), "tuning": deepcopy(tuning_examples),
                      "options": deepcopy(options)})
        return marker

    monkeypatch.setattr(span, "build_checkpoint", build)
    monkeypatch.setattr(span, "train_decoder", train)
    return calls, marker


def call_train(checkpoint, training, tuning=None, **options):
    return owner.train_bound_decoder(checkpoint, training, tuning,
                                    expected_checkpoint_sha256=digest(checkpoint), **options)


def reject_both(training, tuning, checkpoint, calls):
    with pytest.raises(binding_owner.SourceSpanConsumerBindingError):
        owner.build_bound_checkpoint(training, tuning)
    with pytest.raises(binding_owner.SourceSpanConsumerBindingError):
        call_train(checkpoint, training, tuning)
    assert calls == []


def test_build_calls_owner_once_with_exact_detached_order_and_fixed_zero_latent_profile(batches, numerical_spies):
    training, tuning = batches
    calls, marker = numerical_spies
    assert owner.build_bound_checkpoint(training, tuning, learning_rate=.005, batch_size=2,
        seed=19, hidden_size=8, embedding_dim=4, projection_width=4, residual_scale=.5) is marker
    assert calls == [{"owner": "build", "training": training.rows, "tuning": tuning.rows,
        "options": {"latent_dimension": 0, "latent_enabled": True, "learning_rate": .005,
                    "batch_size": 2, "seed": 19, "hidden_size": 8, "embedding_dim": 4,
                    "projection_width": 4, "residual_scale": .5}}]


def test_train_calls_owner_once_and_preserves_checkpoint_rows_and_requested_budget(batches, numerical_spies):
    training, tuning = batches
    checkpoint = fake_checkpoint(training, tuning)
    before = deepcopy((checkpoint, training.rows, tuning.rows))
    calls, marker = numerical_spies
    assert call_train(checkpoint, training, tuning, max_steps=3, max_seconds=.25) is marker
    assert calls == [{"owner": "train", "checkpoint": checkpoint, "training": training.rows,
                      "tuning": tuning.rows, "options": {"max_steps": 3, "max_seconds": .25}}]
    assert (checkpoint, training.rows, tuning.rows) == before


def test_no_tuning_is_explicit_none_and_binds_the_empty_canonical_inventory(batches, numerical_spies):
    training, _ = batches
    calls, marker = numerical_spies
    assert owner.build_bound_checkpoint(training, None) is marker
    checkpoint = fake_checkpoint(training)
    assert checkpoint["tuning_manifest_sha256"] == span.checkpoint_digest([])
    assert call_train(checkpoint, training, None, max_steps=0, max_seconds=0) is marker
    assert [call["owner"] for call in calls] == ["build", "train"]
    assert all(list(call["tuning"]) == [] for call in calls)
    assert calls[1]["checkpoint"]["tuning_count"] == 0
    assert calls[1]["options"] == {"max_steps": 0, "max_seconds": 0}


@pytest.mark.parametrize("which", ["training", "tuning"])
@pytest.mark.parametrize("damage", ["source", "target", "row_order", "eligibility", "exposure", "manifest"])
def test_each_original_batch_input_is_checked_before_either_numerical_owner(batches, numerical_spies, which, damage):
    training, tuning = batches
    checkpoint = fake_checkpoint(training, tuning)
    batch = training if which == "training" else tuning
    if damage == "source":
        batch.rows[0]["source_text"] += " Changed."
    elif damage == "target":
        batch.rows[0]["canonical_ir"]["rules"][0]["modality"] = "F"
    elif damage == "row_order":
        batch.rows.reverse()
    elif damage == "eligibility":
        batch.eligibility_records[0]["status"] = "ineligible"
    elif damage == "exposure":
        batch.exposure_records[0]["provenance_ref"] = "fixture:altered-exposure"
    else:
        batch.split_manifest["assignments"][batch.rows[0]["id"]] = "holdout"
    reject_both(training, tuning, checkpoint, numerical_spies[0])


@pytest.mark.parametrize("position", ["training", "tuning"])
def test_ready_bindings_cannot_supply_the_wrong_training_or_validation_role(batches, numerical_spies, position):
    training, tuning = batches
    checkpoint = fake_checkpoint(training, tuning)
    if position == "training":
        training = tuning
    else:
        tuning = training
    reject_both(training, tuning, checkpoint, numerical_spies[0])


def test_one_blocked_tuning_member_prevents_build_and_train_on_an_otherwise_ready_training_batch(batches, numerical_spies):
    training, tuning = batches
    tuning = make_batch(tuning.rows, tuning.split_manifest, "hparam_selection", blocked=1)
    assert training.binding.receipt()["status"] == "ready"
    assert tuning.binding.receipt()["blocked_row_count"] == 1
    checkpoint = fake_checkpoint(training, tuning)
    reject_both(training, tuning, checkpoint, numerical_spies[0])


def test_individually_ready_batches_cannot_use_different_complete_split_roots(batches, numerical_spies):
    training, tuning = batches
    changed = splits.LegalIRSplitManifest.from_mapping(tuning.split_manifest)
    changed.metadata["different_declared_freeze"] = True
    changed_manifest = changed.to_dict()
    tuning = make_batch(tuning.rows, changed_manifest, "hparam_selection")
    assert training.binding.receipt()["status"] == tuning.binding.receipt()["status"] == "ready"
    reject_both(training, tuning, fake_checkpoint(training, tuning), numerical_spies[0])


def test_shared_manifest_cross_split_source_overlap_blocks_dispatch_without_dropping_members(numerical_spies):
    train_rows, tune_rows = fictional_rows()
    tune_rows[0]["source_text"] = train_rows[0]["source_text"]
    tune_rows[0]["canonical_ir"] = deepcopy(train_rows[0]["canonical_ir"])
    manifest = split_manifest(train_rows, tune_rows)
    assert manifest["legal_ir_split_guard"]["passed"] is False
    training = make_batch(train_rows, manifest, "training")
    tuning = make_batch(tune_rows, manifest, "hparam_selection")
    reject_both(training, tuning, fake_checkpoint(training, tuning), numerical_spies[0])


@pytest.mark.parametrize("invalid", [None, "", "0" * 64, True, "A" * 64])
def test_checkpoint_requires_an_independent_exact_canonical_pin_before_train(batches, numerical_spies, invalid):
    training, tuning = batches
    checkpoint = fake_checkpoint(training, tuning)
    with pytest.raises(binding_owner.SourceSpanConsumerBindingError):
        owner.train_bound_decoder(checkpoint, training, tuning, expected_checkpoint_sha256=invalid)
    assert numerical_spies[0] == []


def test_changed_model_state_cannot_reuse_the_original_checkpoint_content_pin(batches, numerical_spies):
    training, tuning = batches
    checkpoint = fake_checkpoint(training, tuning)
    expected_sha256 = digest(checkpoint)
    checkpoint["model_state"]["unqualified_fixture_weights"][0] = 9.
    with pytest.raises(binding_owner.SourceSpanConsumerBindingError):
        owner.train_bound_decoder(checkpoint, training, tuning, expected_checkpoint_sha256=expected_sha256)
    assert numerical_spies[0] == []


@pytest.mark.parametrize("damage", ["schema", "lineage", "authority", "implementation", "latent_384",
    "latent_boolean", "train_hash", "tune_hash", "train_count", "tune_count", "count_boolean",
    "extra_header", "missing_header", "parent_hash", "progress_fields", "negative_steps",
    "boolean_steps", "step_identity", "cursor", "batch_zero", "batch_boolean"])
def test_repinned_checkpoint_header_failures_precede_restore_owner_dispatch(batches, numerical_spies, damage):
    training, tuning = batches
    checkpoint = fake_checkpoint(training, tuning)
    if damage == "schema":
        checkpoint["schema"] = "other-checkpoint/v1"
    elif damage == "lineage":
        checkpoint["lineage_id"] = "source_conditioned_formula_v1"
    elif damage == "authority":
        checkpoint["qualified"] = True
    elif damage == "implementation":
        checkpoint["implementation"]["span"] = "0" * 64
    elif damage == "latent_384":
        checkpoint["config"]["latent_dimension"] = 384
    elif damage == "latent_boolean":
        checkpoint["config"]["latent_dimension"] = False
    elif damage == "train_hash":
        checkpoint["training_manifest_sha256"] = "0" * 64
    elif damage == "tune_hash":
        checkpoint["tuning_manifest_sha256"] = "0" * 64
    elif damage == "train_count":
        checkpoint["training_count"] += 1
    elif damage == "tune_count":
        checkpoint["tuning_count"] += 1
    elif damage == "count_boolean":
        checkpoint["training_count"] = True
    elif damage == "extra_header":
        checkpoint["accepted"] = False
    elif damage == "missing_header":
        checkpoint.pop("model_state")
    elif damage == "parent_hash":
        checkpoint["parent_checkpoint_sha256"] = "invalid"
    elif damage == "progress_fields":
        checkpoint["progress"]["extra"] = 0
    elif damage == "negative_steps":
        checkpoint["progress"]["optimizer_steps"] = -1
    elif damage == "boolean_steps":
        checkpoint["progress"]["optimizer_steps"] = False
    elif damage == "step_identity":
        checkpoint["progress"]["optimizer_steps"] = 1
    elif damage == "cursor":
        checkpoint["progress"]["row_cursor"] = len(training.rows)
    elif damage == "batch_zero":
        checkpoint["config"]["batch_size"] = 0
    else:
        checkpoint["config"]["batch_size"] = True
    with pytest.raises(binding_owner.SourceSpanConsumerBindingError):
        call_train(checkpoint, training, tuning)
    assert numerical_spies[0] == []


@pytest.mark.parametrize("field,value", [("max_steps", True), ("max_steps", -1), ("max_steps", 10001),
    ("max_steps", 1.5), ("max_seconds", True), ("max_seconds", -1), ("max_seconds", 3601),
    ("max_seconds", float("nan")), ("max_seconds", float("inf"))])
def test_invalid_optimizer_budgets_fail_before_train_owner(batches, numerical_spies, field, value):
    training, tuning = batches
    checkpoint = fake_checkpoint(training, tuning)
    with pytest.raises(binding_owner.SourceSpanConsumerBindingError):
        call_train(checkpoint, training, tuning, **{field: value})
    assert numerical_spies[0] == []


@pytest.mark.parametrize("damage", ["nonfinite", "cycle", "custom_object", "custom_dict"])
def test_checkpoint_snapshot_requires_ordinary_bounded_json_before_owner_restore(batches, numerical_spies, damage):
    training, tuning = batches
    checkpoint = fake_checkpoint(training, tuning)
    if damage == "nonfinite":
        checkpoint["model_state"] = {"invalid": float("nan")}
    elif damage == "cycle":
        checkpoint["model_state"]["cycle"] = checkpoint
    elif damage == "custom_object":
        checkpoint["optimizer_state"] = object()
    else:
        class CustomDict(dict):
            pass
        checkpoint["model_state"] = CustomDict(checkpoint["model_state"])
    with pytest.raises(binding_owner.SourceSpanConsumerBindingError):
        owner.train_bound_decoder(checkpoint, training, tuning, expected_checkpoint_sha256="0" * 64)
    assert numerical_spies[0] == []


@pytest.mark.parametrize("function,options", [("build", {"latent_dimension": 384}),
    ("build", {"latent_enabled": False}), ("build", {"training_examples": []}),
    ("train", {"learning_rate": .1}), ("train", {"tuning_examples": []})])
def test_unknown_keywords_cannot_override_bound_batches_or_zero_latent_profile(batches, numerical_spies, function, options):
    training, tuning = batches
    with pytest.raises(TypeError):
        if function == "build":
            owner.build_bound_checkpoint(training, tuning, **options)
        else:
            call_train(fake_checkpoint(training, tuning), training, tuning, **options)
    assert numerical_spies[0] == []


@pytest.mark.parametrize("operation", ["build", "train"])
def test_numerical_owner_receives_detached_rows_and_checkpoint_without_aliasing_callers(batches, monkeypatch, operation):
    training, tuning = batches
    checkpoint = fake_checkpoint(training, tuning)
    before = deepcopy((checkpoint, training.rows, tuning.rows, training.eligibility_records,
                       tuning.exposure_records))
    calls, marker = [], object()

    def build(train_rows, tune_rows=(), **options):
        calls.append((deepcopy(train_rows), deepcopy(tune_rows)))
        train_rows[0]["canonical_ir"]["rules"][0]["conditions"].append("private mutation")
        tune_rows.reverse()
        return marker

    def train(detached_checkpoint, train_rows, tune_rows=(), **options):
        detached_checkpoint["model_state"]["unqualified_fixture_weights"].append(3.)
        return build(train_rows, tune_rows, **options)

    monkeypatch.setattr(span, "build_checkpoint", build)
    monkeypatch.setattr(span, "train_decoder", train)
    result = (owner.build_bound_checkpoint(training, tuning) if operation == "build"
              else call_train(checkpoint, training, tuning))
    assert result is marker and calls == [(training.rows, tuning.rows)]
    assert (checkpoint, training.rows, tuning.rows, training.eligibility_records, tuning.exposure_records) == before


@pytest.mark.parametrize("operation", ["build", "train"])
def test_owner_exception_propagates_exactly_once_without_retry_or_replacement(batches, monkeypatch, operation):
    training, tuning = batches
    checkpoint = fake_checkpoint(training, tuning)
    calls, error = [], RuntimeError("fictional numerical-owner failure")

    def failing(*args, **kwargs):
        calls.append((args, kwargs))
        raise error

    monkeypatch.setattr(span, "build_checkpoint", failing)
    monkeypatch.setattr(span, "train_decoder", failing)
    with pytest.raises(RuntimeError) as caught:
        if operation == "build":
            owner.build_bound_checkpoint(training, tuning)
        else:
            call_train(checkpoint, training, tuning)
    assert caught.value is error and len(calls) == 1


@pytest.mark.parametrize("module", [owner, binding_owner])
def test_live_wrapper_or_binding_source_drift_blocks_numerical_dispatch(batches, numerical_spies, monkeypatch, module):
    training, tuning = batches
    checkpoint = fake_checkpoint(training, tuning)
    changed_path, original_read_bytes = Path(module.__file__).resolve(), Path.read_bytes

    def changed_bytes(path):
        raw = original_read_bytes(path)
        return raw + b"\n# fictional source drift\n" if path.resolve() == changed_path else raw

    monkeypatch.setattr(Path, "read_bytes", changed_bytes)
    reject_both(training, tuning, checkpoint, numerical_spies[0])
