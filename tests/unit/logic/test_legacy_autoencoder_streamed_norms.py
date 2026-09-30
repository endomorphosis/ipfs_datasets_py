"""Exact behavior checks for the opt-in legacy norm bookkeeping port."""

from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import importlib.util
import inspect
import os
import textwrap

import pytest

PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages"


@pytest.fixture(scope="module")
def profile():
    # Validate staged additions without changing the live census producer tree.
    staged = os.environ.get("IPFS_DATASETS_TEST_STAGED_LEGACY_PROFILE")
    if staged:
        spec = importlib.util.spec_from_file_location(f"{PREFIX}.legacy_v1_optimized", staged)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    return importlib.import_module(f"{PREFIX}.legacy_v1_optimized")


def sample(profile, name="reports"):
    ir = importlib.import_module(f"{PREFIX}.legacy_v1._snapshot.modal_ir")
    text = f"The agency shall submit {name}."
    return profile.LegalSample(
        sample_id=name, source="us_code", title="5", section="552",
        citation="5 U.S.C. 552", text=text, normalized_text=text,
        embedding_model="test:explicit-synthetic-vector-not-semantic",
        embedding_vector=[(i % 7 - 3) / 7 for i in range(8)],
        modal_ir=ir.ModalIRDocument(
            document_id=name, source="us_code", normalized_text=text,
            formulas=[ir.ModalIRFormula(
                formula_id=name,
                operator=ir.ModalIROperator(family="deontic", system="SDL", symbol="O", label="obligation"),
                predicate=ir.ModalIRPredicate(name="submit", arguments=["agency", name]),
                provenance=ir.ModalIRProvenance(source_id=name, start_char=0, end_char=len(text)),
            )],
        ),
    )


def test_batch_override_is_only_the_reviewed_helper_and_import_port(profile):
    old = inspect.getsource(profile._legacy.AdaptiveModalAutoencoder._apply_projection_update_batch_in_transaction)
    new = inspect.getsource(profile.Autoencoder._apply_projection_update_batch_in_transaction)
    assert hashlib.sha256(old.encode()).hexdigest() == profile.FROZEN_BATCH_METHOD_SHA256
    new = new.replace("from .legacy_v1._snapshot.modal_autoencoder_cuda import", "from .modal_autoencoder_cuda import")
    assert ast.dump(ast.parse(textwrap.dedent(old))) == ast.dump(ast.parse(textwrap.dedent(new)))
    assert profile.legal_ir_trainable_head_transaction_delta_norm_report is not profile._legacy.legal_ir_trainable_head_transaction_delta_norm_report


@pytest.mark.parametrize("learning_rate", [0.0, 0.01, -0.5])
@pytest.mark.parametrize("case", ["ordinary", "collisions", "replace_component", "nonfinite", "empty"])
def test_norm_report_exact_parity_and_no_state_mutation(profile, case, learning_rate):
    state = profile.TrainingState()
    state.decompiler_plan_family_logits["before"] = {"deontic": 1.0, "frame_logic": -2.0}
    state.decompiler_plan_family_logits["deleted"] = {"cec": 3.0}
    state.feature_embedding_weights["unrelated"] = [0.1] * 8
    if case == "collisions":
        state.decompiler_plan_family_logits[1] = {"deontic": 2.0, "frame_logic": 7.0}
        state.decompiler_plan_family_logits["1"] = {"deontic": -4.0}
        state.decompiler_plan_family_logits["nested"] = {1: {"a": 1.0}, "1": {"a": 2.0, "b": 3.0}}
    transaction = state.transaction(label="norm-fixture").begin()
    try:
        if case != "empty":
            state.decompiler_plan_family_logits["before"]["deontic"] = 2.0
            state.decompiler_plan_family_logits.pop("deleted")
            state.decompiler_plan_family_logits["inserted"] = {"cec": [float(i) for i in range(12)], "skip": True}
            state.feature_embedding_weights["unrelated"][2] = -2.0
        if case == "collisions":
            state.decompiler_plan_family_logits[1]["deontic"] = 5.0
            state.decompiler_plan_family_logits["1"]["deontic"] = -1.0
            state.decompiler_plan_family_logits["nested"][1]["a"] = 8.0
            state.decompiler_plan_family_logits["nested"]["1"]["b"] = -1.0
        elif case == "replace_component":
            state.decompiler_plan_family_logits = {"before": {"deontic": 11.0}, "standalone": {"cec": 5.0}}
        elif case == "nonfinite":
            state.decompiler_plan_family_logits["before"]["deontic"] = float("nan")
            state.decompiler_plan_family_logits["inserted"]["cec"] = [float("inf"), float("-inf"), True]
        before = repr((list(state.decompiler_plan_family_logits.items()), list(state.feature_embedding_weights.items())))
        revision = state.state_revision
        expected = profile._legacy.legal_ir_trainable_head_transaction_delta_norm_report(transaction, state, learning_rate=learning_rate)
        observed = profile.legal_ir_trainable_head_transaction_delta_norm_report(transaction, state, learning_rate=learning_rate)
        assert observed == expected
        assert repr((list(state.decompiler_plan_family_logits.items()), list(state.feature_embedding_weights.items()))) == before
        assert state.state_revision == revision
    finally:
        transaction.rollback()



def test_norm_parity_across_all_historical_trainable_heads(profile):
    state = profile.TrainingState()
    for field in profile.LEGAL_IR_TRAINABLE_HEAD_FIELDS:
        mapping = getattr(state, field)
        if field.endswith("embedding_weights"):
            mapping["existing"] = [0.1 * i for i in range(8)]
        elif field == "legal_ir_view_logits":
            mapping["deontic"] = 0.3
        else:
            mapping["existing"] = {"deontic": 0.1, "cec": 0.5, "frame_logic": -0.3}
    transaction = state.transaction().begin()
    try:
        for field in profile.LEGAL_IR_TRAINABLE_HEAD_FIELDS:
            mapping = getattr(state, field)
            if field.endswith("embedding_weights"):
                mapping["existing"][5] = 1.2
            elif field == "legal_ir_view_logits":
                mapping["deontic"] = -0.2
            else:
                mapping["existing"]["cec"] = 0.9
        expected = profile._legacy.legal_ir_trainable_head_transaction_delta_norm_report(
            transaction, state, learning_rate=0.01)
        observed = profile.legal_ir_trainable_head_transaction_delta_norm_report(
            transaction, state, learning_rate=0.01)
        assert observed == expected
        assert set(observed["scalar_update_counts_by_head"]) == set(profile.LEGAL_IR_TRAINABLE_HEAD_FIELDS)
    finally:
        transaction.rollback()


def test_optimized_norm_does_not_capture_or_copy_unrelated_rows(profile, monkeypatch):
    state = profile.TrainingState()
    transaction = state.transaction().begin()
    state.feature_embedding_weights["embedding"] = [0.2] * 8
    state.decompiler_plan_family_logits["head"] = {"deontic": 0.1}
    original_capture = transaction.capture_patch
    def forbidden():
        raise AssertionError("norm accounting must not capture a candidate")
    monkeypatch.setattr(transaction, "capture_patch", forbidden)
    try:
        report = profile.legal_ir_trainable_head_transaction_delta_norm_report(transaction, state, learning_rate=0.01)
        assert report["scalar_update_counts_by_head"] == {"decompiler_plan_family_logits": 1}
    finally:
        monkeypatch.setattr(transaction, "capture_patch", original_capture)
        transaction.rollback()


def test_transaction_owner_and_target_guard_preserved(profile):
    state = profile.TrainingState()
    transaction = state.transaction().begin()
    norm = profile.legal_ir_trainable_head_transaction_delta_norm_report
    with pytest.raises(profile.StateTransactionConflictError):
        norm(transaction, profile.TrainingState(), learning_rate=0.1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(profile.StateTransactionConflictError):
            pool.submit(norm, transaction, state, learning_rate=0.1).result()
    transaction.rollback()
    with pytest.raises(Exception, match="not active"):
        norm(transaction, state, learning_rate=0.1)


def _without_timings(value):
    if isinstance(value, dict):
        return {key: _without_timings(item) for key, item in value.items()
                if "elapsed" not in key and key not in {"duration_seconds"}}
    if isinstance(value, list):
        return [_without_timings(item) for item in value]
    return value


def test_bounded_real_training_has_identical_reports_and_committed_weights(profile):
    baseline = profile.legacy_v1.Autoencoder(compute_device="cpu")
    optimized = profile.Autoencoder(compute_device="cpu")
    options = dict(epochs=2, learning_rate=0.01, max_seconds=30,
                   max_line_search_attempts=1, projection_update_backend="python_sparse_batch",
                   projection_max_update_families=4,
                   legal_ir_bridge_names=(), legal_ir_evaluate_provers=False)
    train = [sample(profile)]
    holdout = [sample(profile, "notices")]
    old = baseline.train_generalizable_projection(train, validation_samples=holdout, **options)
    new = optimized.train_generalizable_projection(train, validation_samples=holdout, **options)
    assert old["accepted_epochs"] > 0
    assert old["after"]["legal_ir_target_count"] == new["after"]["legal_ir_target_count"] == 0
    assert _without_timings(old) == _without_timings(new)
    assert baseline.state.to_dict() == optimized.state.to_dict()
    assert baseline.state.state_revision == optimized.state.state_revision
    assert baseline.state.state_identity() == optimized.state.state_identity()
    assert baseline.state.decoded_embeddings == {}


def test_profile_preserves_lineage_checkpoint_and_objective_contract(profile, tmp_path):
    path = tmp_path / "legacy.state.json"
    profile.TrainingState().save_json(path)
    raw = path.read_bytes()
    model = profile.load_checkpoint(path, expected_sha256=hashlib.sha256(raw).hexdigest(), compute_device="cpu")
    assert type(model.state) is profile.legacy_v1.TrainingState
    assert model.LINEAGE_ID == profile.legacy_v1.LINEAGE_ID
    assert model.DIMENSION == 8
    assert model._raw_reconstruction_default is False
    assert model.describe()["runtime_profile"] == "legacy-v1-streamed-norms/v1"
    assert path.read_bytes() == raw
    assert model.describe()["admitted"] is False
    with pytest.raises(ValueError, match="expected 8"):
        model.encode(type("BadInput", (), {"embedding_vector": [0.0] * 384})())
