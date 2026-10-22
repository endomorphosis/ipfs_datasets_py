"""Bound dimensional dispatch and tiny CPU resumption, using fictional text.

Only the original-context verifier is replaced by an explicit retained-vector
engineering seam. These fixtures claim no native embedding execution, reviewed
law, statutory meaning, checkpoint qualification, or training effectiveness.
"""
from copy import deepcopy
import hashlib
import json

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dims
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_context_binding as context_owner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as base
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_bound_dimensions as owner
from ipfs_datasets_py.logic.formalization.autoencoder import gte_multilingual_profile as native768_profile


def digest(value):
    return base._guard(value).sha256


def text_digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stage_representation(stage):
    # The verifier seam simulates these exact wire identities; it does not
    # execute or authenticate the named producer's native computation.
    return native768_profile.PROFILE_ID if stage == "native768" else "actual_frozen_legal_ir/" + stage + "/v1"


def row(identifier, actor, modality, action, object_name):
    phrase = "may" if modality == "P" else "must"
    return {"id": identifier, "source_text": f"The {actor} {phrase} {action} {object_name}.",
        "canonical_ir": {"rules": [{"modality": modality, "actor": actor, "action": action,
            "object": object_name, "conditions": [], "exceptions": [], "temporal": []}]}}


def populations():
    return ([row("train-a", "agency", "O", "disclose", "records"),
             row("train-b", "auditor", "P", "inspect", "files")],
            [row("tune-a", "board", "P", "retain", "notices")])


def full_manifest(training, tuning):
    return splits.LegalIRSplitManifest(
        examples=tuple(splits.LegalIRSplitExample.from_sample(
            {"sample_id": r["id"], "text": r["source_text"]}) for r in (*training, *tuning)),
        assignments={**{r["id"]: "train" for r in training},
                     **{r["id"]: "validation" for r in tuning}},
        config_digest=text_digest("frozen fictional dimensional binding policy")).to_dict()


@pytest.fixture(scope="module", autouse=True)
def threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def parent():
    training, _ = populations()
    initial = span.build_checkpoint(training, latent_dimension=0, hidden_size=8,
        embedding_dim=4, projection_width=4, batch_size=2)
    return span.train_decoder(initial, training, max_steps=1, max_seconds=30)["checkpoint"]


@pytest.fixture
def producer(monkeypatch):
    """Independent immutable-at-registration producer observations, not a model."""
    records, calls, hooks = {}, [], []

    def verify(stage, sources, evidence, resolver):
        entry = records[evidence.get("fixture_id")]
        if stage != entry["stage"] or sources != entry["sources"] or evidence != entry["evidence"]:
            raise context_owner.SourceSpanContextBindingError("fixture original producer binding differs")
        assert all(set(source) == {"id", "source_text"} for source in sources)
        calls.append({"stage": stage, "sources": deepcopy(sources)})
        for hook in hooks:
            hook(stage, sources, evidence)
        return deepcopy(entry["result"])

    monkeypatch.setattr(context_owner, "_verify", verify)

    def register(sources, stage="raw384", operation="training", *, representation_id=None,
                 producer_sha256="b" * 64):
        dimension = 768 if stage == "native768" else 384
        contexts = [{"id": source["id"], "source_sha256": text_digest(source["source_text"]),
            "context": [(index + 1) / (dimension + j) for j in range(dimension)]}
            for index, source in enumerate(sources)]
        evidence = {"fixture_id": f"retained-fixture-{len(records)}", "stage": stage}
        result = {"contexts": contexts, "representation": {"dimension": dimension,
            "representation_id": representation_id or stage_representation(stage),
            "producer_sha256": producer_sha256}, "inspection": {
                "fixture_only": True, "source_semantics_verified": False}}
        if stage == "native768":
            result["provenance"] = {"selected_source_splits": [
                {"id": c["id"], "source_sha256": c["source_sha256"],
                 "splits": ["train" if operation == "training" else "tuning"]} for c in contexts]}
        records[evidence["fixture_id"]] = deepcopy({"stage": stage, "sources": sources,
            "evidence": evidence, "result": result})
        return contexts, evidence

    register.calls, register.hooks, register.records = calls, hooks, records
    return register


def make_batch(producer, rows, manifest, operation, stage="raw384", *, blocked=False, **identity):
    rows, manifest = deepcopy(rows), deepcopy(manifest)
    eligibility, exposure = [], []
    for r in rows:
        exact = {"id": r["id"], "source_text_sha256": text_digest(r["source_text"]),
                 "canonical_ir_sha256": digest(r["canonical_ir"])}
        eligibility.append({**exact, "target_origin": "authored_engineering_fixture",
            "status": "unknown" if blocked else "eligible", "allowed_operations": [operation],
            "reason": "Fictional engineering dispatch fixture; no reviewed law or gold."})
        exposure.append({**exact, "target_exposure": "declared_supervised_training" if operation == "training"
            else "declared_validation_scoring", "provenance_ref": "fixture:bound-dimensions"})
    sources = [{"id": r["id"], "source_text": r["source_text"]} for r in rows]
    contexts, evidence = producer(sources, stage, operation, **identity)
    binding = context_owner.prepare_source_span_context_binding(rows,
        expected_rows_sha256=digest(rows), split_manifest=manifest,
        expected_split_manifest_sha256=digest(manifest), eligibility_records=eligibility,
        expected_eligibility_sha256=digest(eligibility), exposure_records=exposure,
        expected_exposure_sha256=digest(exposure), operation=operation, stage=stage,
        contexts=contexts, expected_contexts_sha256=digest(contexts), context_evidence=evidence,
        expected_context_evidence_sha256=digest(evidence))
    return owner.ContextBoundBatch(binding=binding, rows=rows, split_manifest=manifest,
        eligibility_records=eligibility, exposure_records=exposure,
        contexts=contexts, context_evidence=evidence)


def batches(producer, stage="raw384", **tuning_identity):
    training, tuning = populations()
    manifest = full_manifest(training, tuning)
    return (make_batch(producer, training, manifest, "training", stage),
            make_batch(producer, tuning, manifest, "hparam_selection", stage, **tuning_identity))


def build(parent, training, tuning=None, **options):
    return owner.build_bound_checkpoint(parent, training, tuning,
        expected_parent_sha256=digest(parent), batch_size=2, **options)


def train(checkpoint, training, tuning=None, **options):
    return owner.train_bound_decoder(checkpoint, training, tuning,
        expected_checkpoint_sha256=digest(checkpoint), **options)


def numerical_rows(batch):
    return [{**deepcopy(r), "latent": deepcopy(c["context"])} for r, c in zip(batch.rows, batch.contexts)]


def forbid(*args, **kwargs):
    pytest.fail("numerical dispatch occurred before invalid inputs were rejected")


@pytest.mark.parametrize("stage", ["raw384", "native768"])
def test_training_identity_comes_only_from_training_population(parent, producer, stage):
    training, tuning = batches(producer, stage)
    original = deepcopy((parent, training.rows, tuning.rows, training.contexts, tuning.contexts))
    checkpoint = build(parent, training, tuning)
    direct = dims.build_checkpoint(parent, numerical_rows(training), numerical_rows(tuning),
        latent_dimension=768 if stage == "native768" else 384,
        context_contract=training.binding.receipt()["context_contract"], batch_size=2)
    assert checkpoint == direct
    assert checkpoint["context_contract"] == training.binding.receipt()["context_contract"]
    assert checkpoint["context_contract"]["training_index_sha256"] != digest(tuning.contexts)
    assert checkpoint["training_manifest_sha256"] == digest(numerical_rows(training))
    assert checkpoint["tuning_manifest_sha256"] == digest(numerical_rows(tuning))
    assert checkpoint["config"]["latent_dimension"] == (768 if stage == "native768" else 384)
    assert checkpoint["progress"]["optimizer_steps"] == 0
    assert all(checkpoint[key] is False for key in span.FALSE)
    assert (parent, training.rows, tuning.rows, training.contexts, tuning.contexts) == original


@pytest.mark.parametrize("which", ["training", "tuning"])
@pytest.mark.parametrize("damage", ["vector", "source", "target", "evidence", "eligibility", "split"])
def test_changed_bound_inputs_prevent_build_dispatch(parent, producer, monkeypatch, which, damage):
    training, tuning = batches(producer)
    selected = training if which == "training" else tuning
    if damage == "vector": selected.contexts[0]["context"][0] += .25
    elif damage == "source": selected.rows[0]["source_text"] += " Altered."
    elif damage == "target": selected.rows[0]["canonical_ir"]["rules"][0]["modality"] = "F"
    elif damage == "evidence": selected.context_evidence["stage"] = "trained384"
    elif damage == "eligibility": selected.eligibility_records[0]["status"] = "ineligible"
    else: selected.split_manifest["assignments"][selected.rows[0]["id"]] = "holdout"
    monkeypatch.setattr(dims, "build_checkpoint", forbid)
    with pytest.raises(base.SourceSpanConsumerBindingError):
        build(parent, training, tuning)


@pytest.mark.parametrize("mismatch", ["dimension", "representation", "producer", "stage", "split"])
def test_ready_individual_batches_cannot_change_shared_context_identity(parent, producer, monkeypatch, mismatch):
    training, tuning = batches(producer)
    stage, identity, manifest = "raw384", {}, deepcopy(tuning.split_manifest)
    if mismatch == "dimension": stage = "native768"
    elif mismatch == "representation": identity["representation_id"] = "fixture:other-coordinate-space"
    elif mismatch == "producer": identity["producer_sha256"] = "c" * 64
    elif mismatch == "stage":
        stage, identity["representation_id"] = "core384", stage_representation("raw384")
    else:
        rebuilt = splits.LegalIRSplitManifest.from_mapping(manifest)
        rebuilt.metadata["different_declared_freeze"] = True
        manifest = rebuilt.to_dict()
    tuning = make_batch(producer, tuning.rows, manifest, "hparam_selection", stage, **identity)
    assert training.binding.receipt()["status"] == tuning.binding.receipt()["status"] == "ready"
    monkeypatch.setattr(dims, "build_checkpoint", forbid)
    with pytest.raises(base.SourceSpanConsumerBindingError):
        build(parent, training, tuning)


def test_blocked_tuning_denominator_is_not_silently_discarded(parent, producer, monkeypatch):
    training, tuning = batches(producer)
    tuning = make_batch(producer, tuning.rows, tuning.split_manifest, "hparam_selection", blocked=True)
    assert tuning.binding.receipt()["blocked_row_count"] == len(tuning.rows)
    monkeypatch.setattr(dims, "build_checkpoint", forbid)
    with pytest.raises(base.SourceSpanConsumerBindingError):
        build(parent, training, tuning)


@pytest.mark.parametrize("invalid", [None, True, "", "0" * 64, "A" * 64])
def test_independent_parent_pin_required_before_build(parent, producer, monkeypatch, invalid):
    training, tuning = batches(producer)
    monkeypatch.setattr(dims, "build_checkpoint", forbid)
    with pytest.raises(base.SourceSpanConsumerBindingError):
        owner.build_bound_checkpoint(parent, training, tuning, expected_parent_sha256=invalid)


def test_later_tuning_verification_cannot_mutate_earlier_training_batch(parent, producer, monkeypatch):
    training, tuning = batches(producer)

    def mutation(stage, sources, evidence):
        if sources[0]["id"] == tuning.rows[0]["id"]:
            training.contexts[0]["context"][0] += .25

    producer.hooks.append(mutation)
    monkeypatch.setattr(dims, "build_checkpoint", forbid)
    with pytest.raises(base.SourceSpanConsumerBindingError):
        build(parent, training, tuning)


@pytest.mark.parametrize("stage", ["raw384", "native768"])
def test_tiny_real_training_save_load_and_exact_adam_resumption(parent, producer, tmp_path, stage):
    training, tuning = batches(producer, stage)
    initial = build(parent, training, tuning)
    before = deepcopy((initial, training.rows, training.contexts, tuning.rows, tuning.contexts))
    whole = train(initial, training, tuning, max_steps=2, max_seconds=30)["checkpoint"]
    first = train(initial, training, tuning, max_steps=1, max_seconds=30)["checkpoint"]
    receipt = owner.save_bound_checkpoint(first, tmp_path / f"bound-{stage}.json", training, tuning,
        expected_checkpoint_sha256=digest(first))
    loaded = owner.load_bound_checkpoint(receipt["path"], training, tuning,
        expected_sha256=receipt["sha256"])
    assert loaded == first
    resumed = train(loaded, training, tuning, max_steps=1, max_seconds=30)["checkpoint"]
    for field in ("model_state", "optimizer_state", "progress"):
        assert resumed[field] == whole[field]
    assert resumed["progress"]["optimizer_steps"] == 2
    assert resumed["model_state"]["latent_up.weight"] != initial["model_state"]["latent_up.weight"]
    assert resumed["model_state"]["latent_down.weight"] != initial["model_state"]["latent_down.weight"]
    assert all(resumed[key] is False for key in span.FALSE)
    assert (initial, training.rows, training.contexts, tuning.rows, tuning.contexts) == before


def test_no_tuning_and_zero_step_resume_remain_explicit(parent, producer):
    training, _ = batches(producer)
    initial = build(parent, training)
    assert initial["tuning_count"] == 0 and initial["tuning_manifest_sha256"] == digest([])
    result = train(initial, training, max_steps=0, max_seconds=0)
    assert result["checkpoint"] == initial


@pytest.mark.parametrize("action", ["train", "save"])
def test_invalid_independent_checkpoint_pin_precedes_numerical_dispatch(parent, producer, monkeypatch, tmp_path, action):
    training, tuning = batches(producer)
    initial = build(parent, training, tuning)
    monkeypatch.setattr(dims, "train_decoder" if action == "train" else "save_checkpoint", forbid)
    with pytest.raises(base.SourceSpanConsumerBindingError):
        if action == "train":
            owner.train_bound_decoder(initial, training, tuning, expected_checkpoint_sha256="0" * 64)
        else:
            owner.save_bound_checkpoint(initial, tmp_path / "never-created.json", training, tuning,
                expected_checkpoint_sha256="0" * 64)
    assert not (tmp_path / "never-created.json").exists()


def test_training_owner_failure_is_propagated_once_without_retry(parent, producer, monkeypatch):
    training, tuning = batches(producer)
    checkpoint = build(parent, training, tuning)
    original = deepcopy((checkpoint, training.rows, tuning.rows, training.contexts, tuning.contexts))
    calls = []

    def fail(received, training_rows, tuning_rows, **options):
        calls.append((deepcopy(received), deepcopy(training_rows), deepcopy(tuning_rows), options))
        received.clear()
        training_rows[0]["latent"].clear()
        raise RuntimeError("fixture numerical failure")

    monkeypatch.setattr(dims, "train_decoder", fail)
    with pytest.raises(RuntimeError, match="fixture numerical failure"):
        train(checkpoint, training, tuning, max_steps=3, max_seconds=.25)
    assert calls == [(checkpoint, numerical_rows(training), numerical_rows(tuning),
                      {"max_steps": 3, "max_seconds": .25})]
    assert (checkpoint, training.rows, tuning.rows, training.contexts, tuning.contexts) == original


def test_load_rejects_changed_batch_before_numerical_checkpoint_owner(parent, producer, monkeypatch, tmp_path):
    training, tuning = batches(producer)
    checkpoint = build(parent, training, tuning)
    receipt = owner.save_bound_checkpoint(checkpoint, tmp_path / "bound.json", training, tuning,
        expected_checkpoint_sha256=digest(checkpoint))
    tuning.contexts[0]["context"][0] += .25
    monkeypatch.setattr(dims, "validate_checkpoint", forbid)
    with pytest.raises(base.SourceSpanConsumerBindingError):
        owner.load_bound_checkpoint(receipt["path"], training, tuning, expected_sha256=receipt["sha256"])


def test_raw_file_pin_and_canonical_content_pin_are_distinct(parent, producer, tmp_path, monkeypatch):
    training, tuning = batches(producer)
    checkpoint = build(parent, training, tuning)
    raw = (json.dumps(checkpoint, sort_keys=True, indent=2) + "\n").encode("utf-8")
    raw_sha = hashlib.sha256(raw).hexdigest()
    canonical_sha = digest(checkpoint)
    assert raw_sha != canonical_sha
    path = tmp_path / "pretty-printed-checkpoint.json"
    path.write_bytes(raw)
    loaded = owner.load_bound_checkpoint(path, training, tuning, expected_sha256=raw_sha)
    assert loaded == checkpoint and digest(loaded) == canonical_sha
    unchanged = owner.train_bound_decoder(loaded, training, tuning,
        expected_checkpoint_sha256=canonical_sha, max_steps=0, max_seconds=0)
    assert unchanged["checkpoint"] == checkpoint
    monkeypatch.setattr(dims, "validate_checkpoint", forbid)
    monkeypatch.setattr(dims, "train_decoder", forbid)
    with pytest.raises(base.SourceSpanConsumerBindingError, match="raw checkpoint hash"):
        owner.load_bound_checkpoint(path, training, tuning, expected_sha256=canonical_sha)
    with pytest.raises(base.SourceSpanConsumerBindingError):
        owner.train_bound_decoder(loaded, training, tuning, expected_checkpoint_sha256=raw_sha)


@pytest.mark.parametrize("options", [
    {"learning_rate": True}, {"learning_rate": 0}, {"learning_rate": float("nan")},
    {"learning_rate": float("inf")}, {"learning_rate": .101},
    {"batch_size": True}, {"batch_size": 0}, {"batch_size": 33},
    {"latent_enabled": 1}, {"latent_enabled": None},
])
def test_invalid_build_scalars_precede_numerical_dispatch(parent, producer, monkeypatch, options):
    training, tuning = batches(producer)
    monkeypatch.setattr(dims, "build_checkpoint", forbid)
    with pytest.raises(base.SourceSpanConsumerBindingError):
        owner.build_bound_checkpoint(parent, training, tuning,
            expected_parent_sha256=digest(parent), **options)


@pytest.mark.parametrize("options", [
    {"max_steps": True}, {"max_steps": -1}, {"max_steps": 10001},
    {"max_seconds": True}, {"max_seconds": -1}, {"max_seconds": 3601},
    {"max_seconds": float("nan")}, {"max_seconds": float("inf")},
])
def test_invalid_training_budgets_precede_numerical_dispatch(parent, producer, monkeypatch, options):
    training, tuning = batches(producer)
    checkpoint = build(parent, training, tuning)
    monkeypatch.setattr(dims, "train_decoder", forbid)
    with pytest.raises(base.SourceSpanConsumerBindingError):
        train(checkpoint, training, tuning, **options)


@pytest.mark.parametrize("operation", ["train", "save", "decode"])
def test_rehashed_4096_checkpoint_is_outside_this_profile(parent, producer, monkeypatch, tmp_path, operation):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions_cpu_inference as cpu
    training, tuning = batches(producer)
    checkpoint = build(parent, training, tuning)
    checkpoint["config"]["latent_dimension"] = 4096
    checkpoint["context_contract"]["dimension"] = 4096
    checkpoint["context_contract_sha256"] = digest(checkpoint["context_contract"])
    monkeypatch.setattr(dims, "train_decoder", forbid)
    monkeypatch.setattr(dims, "save_checkpoint", forbid)
    monkeypatch.setattr(cpu, "CpuDimensionalSpanDecoder", forbid)
    with pytest.raises(base.SourceSpanConsumerBindingError, match="384D or 768D"):
        if operation == "train":
            train(checkpoint, training, tuning)
        elif operation == "save":
            owner.save_bound_checkpoint(checkpoint, tmp_path / "forbidden-4096.json", training, tuning,
                expected_checkpoint_sha256=digest(checkpoint))
        else:
            sources, options = inference_inputs(producer, "raw384")
            owner.decode_bound_sources(checkpoint, sources,
                expected_checkpoint_sha256=digest(checkpoint), **options)
    assert not (tmp_path / "forbidden-4096.json").exists()


@pytest.mark.parametrize("damage", ["dimension", "representation", "producer", "training_index",
    "training_manifest", "tuning_manifest", "authority"])
def test_rehashed_checkpoint_identity_failures_precede_train_dispatch(parent, producer, monkeypatch, damage):
    training, tuning = batches(producer)
    initial = build(parent, training, tuning)
    if damage == "dimension": initial["config"]["latent_dimension"] = 768
    elif damage == "representation": initial["context_contract"]["representation_id"] = "fixture:other"
    elif damage == "producer": initial["context_contract"]["producer_sha256"] = "d" * 64
    elif damage == "training_index": initial["context_contract"]["training_index_sha256"] = digest(tuning.contexts)
    elif damage == "training_manifest": initial["training_manifest_sha256"] = digest(numerical_rows(tuning))
    elif damage == "tuning_manifest": initial["tuning_manifest_sha256"] = digest([])
    else: initial["qualified"] = True
    monkeypatch.setattr(dims, "train_decoder", forbid)
    with pytest.raises(base.SourceSpanConsumerBindingError):
        train(initial, training, tuning, max_steps=1)


def inference_inputs(producer, stage):
    sources = [{"id": "new-a", "source_text": "The trustee may publish registers."},
               {"id": "new-b", "source_text": "The clerk must disclose accounts."}]
    contexts, evidence = producer(sources, stage, "hparam_selection")
    return sources, dict(stage=stage, contexts=contexts, expected_contexts_sha256=digest(contexts),
        context_evidence=evidence, expected_context_evidence_sha256=digest(evidence))


@pytest.mark.parametrize("stage", ["raw384", "native768"])
@pytest.mark.parametrize("ablation", ["none", "zero", "rotate", "disabled"])
def test_target_free_inference_matches_direct_owner_without_optimizer(parent, producer, monkeypatch, stage, ablation):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions_cpu_inference as cpu
    training, tuning = batches(producer, stage)
    checkpoint = train(build(parent, training, tuning), training, tuning,
        max_steps=1, max_seconds=30)["checkpoint"]
    sources, options = inference_inputs(producer, stage)
    original = deepcopy((checkpoint, sources, options))
    direct = cpu.CpuDimensionalSpanDecoder(checkpoint).decode_formal_logic(
        [source["source_text"] for source in sources],
        [context["context"] for context in options["contexts"]], latent_ablation=ablation)
    monkeypatch.setattr(torch.optim, "Adam", forbid)
    observed = owner.decode_bound_sources(checkpoint, sources,
        expected_checkpoint_sha256=digest(checkpoint), latent_ablation=ablation, **options)
    assert observed == direct
    assert observed["target_access"] is observed["teacher_forcing"] is observed["training_executed"] is False
    assert observed["model_state_unchanged"] is True
    assert (checkpoint, sources, options) == original


@pytest.mark.parametrize("damage", ["vector", "evidence", "source", "extra_target", "context_target",
    "dimension", "boolean", "overflow", "context_pin", "evidence_pin", "checkpoint_pin"])
def test_inference_rejects_mismatch_before_model_construction(parent, producer, monkeypatch, damage):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions_cpu_inference as cpu
    training, tuning = batches(producer)
    checkpoint = build(parent, training, tuning)
    sources, options = inference_inputs(producer, "raw384")
    checkpoint_pin = digest(checkpoint)
    if damage == "vector": options["contexts"][0]["context"][0] += .25
    elif damage == "evidence": options["context_evidence"]["stage"] = "core384"
    elif damage == "source": sources[0]["source_text"] += " Altered."
    elif damage == "extra_target": sources[0]["canonical_ir"] = training.rows[0]["canonical_ir"]
    elif damage == "context_target": options["contexts"][0]["canonical_ir"] = training.rows[0]["canonical_ir"]
    elif damage == "dimension": options["contexts"][0]["context"].pop()
    elif damage == "boolean": options["contexts"][0]["context"][0] = True
    elif damage == "overflow": options["contexts"][0]["context"][0] = 1e100
    elif damage == "checkpoint_pin": checkpoint_pin = "0" * 64
    # Rehash content tampering to test producer checks, not only stale pins.
    options["expected_contexts_sha256"] = digest(options["contexts"])
    options["expected_context_evidence_sha256"] = digest(options["context_evidence"])
    if damage == "context_pin": options["expected_contexts_sha256"] = "0" * 64
    elif damage == "evidence_pin": options["expected_context_evidence_sha256"] = "0" * 64
    monkeypatch.setattr(cpu, "CpuDimensionalSpanDecoder", forbid)
    with pytest.raises(base.SourceSpanConsumerBindingError):
        owner.decode_bound_sources(checkpoint, sources, expected_checkpoint_sha256=checkpoint_pin, **options)


@pytest.mark.parametrize("damage", ["representation_id", "producer_sha256", "stage"])
def test_inference_requires_the_trained_coordinate_system(parent, producer, monkeypatch, damage):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions_cpu_inference as cpu
    training, tuning = batches(producer)
    checkpoint = build(parent, training, tuning)
    sources, _ = inference_inputs(producer, "raw384")
    stage, identity = "raw384", {}
    if damage == "stage":
        stage, identity["representation_id"] = "core384", stage_representation("raw384")
    else:
        identity[damage] = "fixture:other" if damage == "representation_id" else "d" * 64
    contexts, evidence = producer(sources, stage, "hparam_selection", **identity)
    monkeypatch.setattr(cpu, "CpuDimensionalSpanDecoder", forbid)
    with pytest.raises(base.SourceSpanConsumerBindingError):
        owner.decode_bound_sources(checkpoint, sources, expected_checkpoint_sha256=digest(checkpoint),
            stage=stage, contexts=contexts, expected_contexts_sha256=digest(contexts),
            context_evidence=evidence, expected_context_evidence_sha256=digest(evidence))


def test_inference_token_bound_is_checked_before_producer_or_model(parent, producer, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions_cpu_inference as cpu
    training, tuning = batches(producer)
    checkpoint = build(parent, training, tuning)
    sources = [{"id": "too-many-tokens", "source_text": "word " * (span.MAX_SOURCE_TOKENS + 1)}]
    assert len(sources[0]["source_text"]) < span.MAX_SOURCE_CHARACTERS
    contexts, evidence = producer(sources, "raw384", "hparam_selection")
    monkeypatch.setattr(context_owner, "_verify", forbid)
    monkeypatch.setattr(cpu, "CpuDimensionalSpanDecoder", forbid)
    with pytest.raises(base.SourceSpanConsumerBindingError, match="token limit"):
        owner.decode_bound_sources(checkpoint, sources, expected_checkpoint_sha256=digest(checkpoint),
            stage="raw384", contexts=contexts, expected_contexts_sha256=digest(contexts),
            context_evidence=evidence, expected_context_evidence_sha256=digest(evidence))
