"""Tiny fictional CPU fits with a doubled private native issuance registry.

The completed-source reader and span binding remain real. Only the private
native owner issuance registry is populated with synthetic receipt observations.
No native encoder, legal source corpus, model download or legal qualification
runs. Native execution and statistical effectiveness are not established here.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import threading

import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_4096_full_owner as owner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as base
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_native4096_binding as binding_owner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_4096 as old_head


def _sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return base._guard(value).sha256


def text_digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module", autouse=True)
def one_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.fixture(autouse=True)
def prohibit_native_execution(monkeypatch):
    def forbidden(*_, **__):
        pytest.fail("completed-source numerical fixture attempted native execution")
    monkeypatch.setattr(owner, "run_full_forward", forbidden)
    monkeypatch.setattr(owner.vocab, "run_vocab_probe", forbidden)
    monkeypatch.setattr(owner.subprocess, "Popen", forbidden)


@pytest.fixture
def native_factory(monkeypatch):
    cases = []

    def make(rows, *, vector_offset=0, model_sha256="a" * 64):
        rows = deepcopy(rows)
        producer = {"profile": owner.PROFILE, "model_sha256": model_sha256,
            "worker_sha256": "b" * 64, "worker_source_sha256": "c" * 64,
            "owner_source_sha256": _sha_file(owner.__file__),
            "vocabulary_owner_source_sha256": _sha_file(owner.vocab.__file__),
            "library_sha256": {"/native/libllama.so": "d" * 64}}
        own = {"pid": os.getpid(), "thread_id": threading.get_native_id()}
        identity = {"device": 1, "inode": 2, "bytes": 3, "mtime_ns": 4, "ctime_ns": 5}
        maps = {"/native/worker": {"identity": deepcopy(identity), "sha256": None},
            "/native/libllama.so": {"identity": deepcopy(identity), "sha256": "d" * 64}}
        geometry = {"native_input_dimension": 4096, "native_output_dimension": 4096,
            "metadata_architecture": "deepseek2", "metadata_embedding_length": 4096,
            "metadata_embedding_length_out": None, "metadata_embedding_length_key": "deepseek2.embedding_length",
            "metadata_embedding_length_out_key": "deepseek2.embedding_length_out", "vocabulary_size": 131072,
            "actual_context": 512, "actual_batch": 512, "actual_ubatch": 512, "actual_sequences": 1,
            "actual_pooling": "last", "context_created": True}
        observed = []
        for number, row in enumerate(rows):
            vector = [0.] * 4096
            vector[(4095 - number + vector_offset) % 4096] = 1.
            observed.append({**row, "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
                "embedding": vector, "token_ids": [1, 40 + number, 2], "token_count": 3,
                "native_tokens_evaluated": 3, "normalized_l2_norm": 1., "raw_output_l2_norm": 2.,
                "geometry": deepcopy(geometry)})
        nonce = hashlib.sha256((str(len(cases)) + repr(rows)).encode()).hexdigest()
        request = {"schema": "native-source4096-worker-request/v1", "nonce": nonce, "rows": rows}
        receipt = {"schema": owner.SCHEMA, "complete": True, "owner": own,
            "child": {"pid": 9001, "birth": "9002", "parent_pid": own["pid"], "group_pid": 9001},
            "operation_nonce": nonce, **{key: producer[key] for key in producer if key != "library_sha256"},
            "model_file_identity": deepcopy(identity), "model_content_hash_verified": True,
            "model_content_hash_seconds": .5, "full_forward_executed": True, "native_tokens_evaluated": 3 * len(rows),
            "vectors_produced": len(rows), "dimension": 4096,
            "request_sha256": hashlib.sha256(owner._wire(request) + b"\n").hexdigest(),
            "protocol": {"entry_sha256": "1" * 64, "authorization_sha256": "2" * 64,
                "entry_mappings": maps, "closing_sha256": "3" * 64, "closing_ack_sha256": "4" * 64,
                "closing_mappings": deepcopy(maps), "exit_observed": True},
            "resource_cgroup": {"memory_max_bytes": 8 * 1024**3, "memory_swap_max_bytes": 0,
                "memory_oom_group": 1, "pids_max": 8, "only_owner_after_exit": True},
            "sampled_native_child_max_rss_bytes": 4096, "sampled_owner_max_rss_bytes": 8192,
            "sampled_combined_max_rss_bytes": 12288, "rss_observation_count": 2,
            "combined_owner_child_rss_limit_bytes": 8 * 1024**3, "rss_scope": "synthetic owner-boundary double",
            "native_child_elapsed_seconds": .1, "elapsed_seconds": .7, "sample_count": len(rows),
            "cleanup": {"leader_reaped": True, "returncode": 0, "live_group_processes": 0},
            "wall_time_scope": "synthetic owner-boundary double", "bridge_names": [],
            "legal_ir_evaluate_provers": False, "metric_disk_cache_used": False,
            "workers": 1, "temperature": 0, "context_tokens": 512,
            "operating_system_page_cache": "uncontrolled", "training_executed": False,
            "qualified": False, "admitted": False, "proof_authority": False,
            "source_semantics_verified": False, "native_service_mutated": False,
            "downloads_performed": False, "persisted_receipt_is_execution_authority": False,
            "rows": observed}
        result = owner.VerifiedForwardResult(owner._TOKEN)
        case = {"rows": rows, "producer": producer, "receipt": receipt, "native": result}

        def issue(value=None):
            selected = receipt if value is None else value
            raw = owner._wire(selected)
            # Explicitly controlled private native boundary. Caller-facing JSON
            # and unissued handles remain unable to enter the real live reader.
            monkeypatch.setitem(owner._ISSUED, result, {"owner": own,
                "owner_source_sha256": producer["owner_source_sha256"], "serialized": raw,
                "receipt_sha256": hashlib.sha256(raw + b"\n").hexdigest()})
        case["issue"] = issue
        issue()
        cases.append(case)
        return case

    make.cases = cases
    return make


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
        config_digest=text_digest("fictional native4096 numerical integration split")).to_dict()


@pytest.fixture(scope="module")
def parent():
    training, _ = populations()
    initial = span.build_checkpoint(training, latent_dimension=0, hidden_size=8,
        embedding_dim=4, projection_width=4, batch_size=2)
    return span.train_decoder(initial, training, max_steps=1, max_seconds=30)["checkpoint"]


from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_bound_native4096 as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_native4096_numeric as numeric


def make_batch(native_factory, rows, manifest, operation, *, blocked=False, native_options=None):
    rows, manifest = deepcopy(rows), deepcopy(manifest)
    eligibility, exposure = [], []
    for item in rows:
        exact = {"id": item["id"], "source_text_sha256": text_digest(item["source_text"]),
                 "canonical_ir_sha256": digest(item["canonical_ir"])}
        eligibility.append({**exact, "target_origin": "authored_engineering_fixture",
            "status": "unknown" if blocked else "eligible", "allowed_operations": [operation],
            "reason": "Fictional CPU integration fixture; no reviewed legal meaning."})
        exposure.append({**exact, "target_exposure": "declared_supervised_training" if operation == "training"
            else "declared_validation_scoring", "provenance_ref": "fixture:bound-native4096"})
    sources = [{"id": item["id"], "source_text": item["source_text"]} for item in rows]
    native = native_factory(sources, **(native_options or {}))
    producer = deepcopy(native["producer"])
    binding = binding_owner.prepare_native4096_span_binding(rows,
        expected_rows_sha256=digest(rows), split_manifest=manifest,
        expected_split_manifest_sha256=digest(manifest), eligibility_records=eligibility,
        expected_eligibility_sha256=digest(eligibility), exposure_records=exposure,
        expected_exposure_sha256=digest(exposure), operation=operation,
        native_result=native["native"], expected_producer=producer,
        expected_producer_sha256=digest(producer),
        expected_native_receipt_sha256=hashlib.sha256(owner._wire(native["receipt"]) + b"\n").hexdigest())
    return subject.Native4096BoundBatch(binding=binding, rows=rows,
        split_manifest=manifest, eligibility_records=eligibility, exposure_records=exposure,
        native_result=native["native"], expected_producer=producer)


def batches(native_factory):
    training, tuning = populations()
    manifest = full_manifest(training, tuning)
    return (make_batch(native_factory, training, manifest, "training"),
            make_batch(native_factory, tuning, manifest, "hparam_selection"))


def build(parent, training, tuning=None, **options):
    return subject.build_bound_checkpoint(parent, training, tuning,
        expected_parent_sha256=digest(parent), batch_size=2, **options)


def train(checkpoint, training, tuning=None, **options):
    return subject.train_bound_decoder(checkpoint, training, tuning,
        expected_checkpoint_sha256=digest(checkpoint), **options)


def numerical_rows(batch):
    return binding_owner.consume_native4096_span_binding(batch.binding, batch.rows,
        split_manifest=batch.split_manifest, eligibility_records=batch.eligibility_records,
        exposure_records=batch.exposure_records, native_result=batch.native_result,
        expected_producer=batch.expected_producer, consumer=lambda value: value)


def forbidden(*args, **kwargs):
    pytest.fail("invalid inputs reached the numerical implementation")


def test_initial_checkpoint_preserves_source_parent_and_training_population_identity(parent, native_factory):
    training, tuning = batches(native_factory)
    original = deepcopy((parent, training.rows, tuning.rows))
    checkpoint = build(parent, training, tuning)
    assert checkpoint["schema"] == numeric.SCHEMA != old_head.SCHEMA
    assert checkpoint["lineage_id"] == numeric.LINEAGE_ID != old_head.LINEAGE_ID
    assert checkpoint["config"]["latent_dimension"] == 4096
    assert checkpoint["context_contract"] == training.binding.receipt()["context_contract"]
    assert checkpoint["context_contract"] != tuning.binding.receipt()["context_contract"]
    assert checkpoint["training_manifest_sha256"] == digest(numerical_rows(training))
    assert checkpoint["tuning_manifest_sha256"] == digest(numerical_rows(tuning))
    assert checkpoint["source_parent_checkpoint_sha256"] == digest(parent)
    assert checkpoint["source_parent_optimizer_steps"] == parent["progress"]["optimizer_steps"] == 1
    assert checkpoint["progress"]["optimizer_steps"] == 0
    assert checkpoint["optimizer_state"]["parameters"] == {}
    for name, value in parent["model_state"].items():
        if not name.startswith(("latent_down.", "latent_up.")):
            assert checkpoint["model_state"][name] == value
    assert len(checkpoint["model_state"]["latent_down.weight"][0]) == 4096
    assert all(checkpoint[name] is False for name in span.FALSE)
    assert (parent, training.rows, tuning.rows) == original


def test_tiny_real_fit_save_load_and_exact_adam_resumption(parent, native_factory, tmp_path):
    training, tuning = batches(native_factory)
    initial = build(parent, training, tuning)
    before = deepcopy((initial, training.rows, tuning.rows))
    whole_result = train(initial, training, tuning, max_steps=2, max_seconds=30)
    first_result = train(initial, training, tuning, max_steps=1, max_seconds=30)
    whole, first = whole_result["checkpoint"], first_result["checkpoint"]
    saved = subject.save_bound_checkpoint(first, tmp_path / "native4096-bound.json", training, tuning,
        expected_checkpoint_sha256=digest(first))
    loaded = subject.load_bound_checkpoint(saved["path"], training, tuning, expected_sha256=saved["sha256"])
    assert loaded == first
    resumed_result = train(loaded, training, tuning, max_steps=1, max_seconds=30)
    resumed = resumed_result["checkpoint"]
    for field in ("model_state", "optimizer_state", "progress"):
        assert resumed[field] == whole[field]
    assert resumed["progress"]["optimizer_steps"] == 2
    assert resumed["model_state"]["latent_up.weight"] != initial["model_state"]["latent_up.weight"]
    assert resumed["model_state"]["latent_down.weight"] != initial["model_state"]["latent_down.weight"]
    assert resumed["model_state"]["latent_down.weight"][0][4095] != initial["model_state"]["latent_down.weight"][0][4095]
    assert whole_result["report"]["optimizer_steps"] == 2
    assert whole_result["report"]["training_executed"] is True
    assert whole_result["report"]["tuning"]["used_for_fit_or_selection"] is False
    assert all(resumed[name] is False for name in span.FALSE)
    assert (initial, training.rows, tuning.rows) == before


def test_fresh_live_native_operations_can_resume_same_inputs_without_receipt_replay(parent, native_factory):
    training, tuning = batches(native_factory)
    first = train(build(parent, training, tuning), training, tuning, max_steps=1, max_seconds=30)["checkpoint"]
    expected = train(first, training, tuning, max_steps=1, max_seconds=30)["checkpoint"]
    fresh_training, fresh_tuning = batches(native_factory)
    assert fresh_training.native_result is not training.native_result
    assert fresh_tuning.native_result is not tuning.native_result
    assert fresh_training.binding.receipt()["native_receipt_sha256"] != training.binding.receipt()["native_receipt_sha256"]
    assert fresh_training.binding.receipt()["context_contract"] == training.binding.receipt()["context_contract"]
    resumed = train(first, fresh_training, fresh_tuning, max_steps=1, max_seconds=30)["checkpoint"]
    for field in ("model_state", "optimizer_state", "progress"):
        assert resumed[field] == expected[field]


def test_no_tuning_and_zero_step_are_preserved(parent, native_factory):
    training, _ = batches(native_factory)
    initial = build(parent, training)
    assert initial["tuning_count"] == 0 and initial["tuning_manifest_sha256"] == digest([])
    result = train(initial, training, max_steps=0, max_seconds=0)
    assert result["checkpoint"] == initial
    assert result["report"]["optimizer_steps"] == 0
    assert result["report"]["training_executed"] is False


@pytest.mark.parametrize("which", ["training", "tuning"])
@pytest.mark.parametrize("damage", ["source", "target", "eligibility", "exposure", "split", "producer", "revoked"])
def test_mutated_or_revoked_batches_refuse_before_numerical_build(parent, native_factory, monkeypatch, which, damage):
    training, tuning = batches(native_factory)
    selected = training if which == "training" else tuning
    if damage == "source": selected.rows[0]["source_text"] += " Changed."
    elif damage == "target": selected.rows[0]["canonical_ir"]["rules"][0]["modality"] = "F"
    elif damage == "eligibility": selected.eligibility_records[0]["status"] = "ineligible"
    elif damage == "exposure": selected.exposure_records[0]["target_exposure"] = "unknown"
    elif damage == "split": selected.split_manifest["assignments"][selected.rows[0]["id"]] = "holdout"
    elif damage == "producer": selected.expected_producer["model_sha256"] = "f" * 64
    else: monkeypatch.delitem(owner._ISSUED, selected.native_result)
    monkeypatch.setattr(numeric, "_build", forbidden)
    with pytest.raises(subject.Native4096BoundError):
        build(parent, training, tuning)


def test_blocked_tuning_rows_are_not_dropped(parent, native_factory, monkeypatch):
    training, tuning = batches(native_factory)
    tuning = make_batch(native_factory, tuning.rows, tuning.split_manifest, "hparam_selection", blocked=True)
    assert tuning.binding.receipt()["blocked_row_count"] == len(tuning.rows)
    monkeypatch.setattr(numeric, "_build", forbidden)
    with pytest.raises(subject.Native4096BoundError):
        build(parent, training, tuning)


def test_tuning_requires_same_complete_split_manifest(parent, native_factory, monkeypatch):
    training, tuning = batches(native_factory)
    manifest = splits.LegalIRSplitManifest.from_mapping(tuning.split_manifest)
    manifest.metadata["different_declared_freeze"] = True
    tuning = make_batch(native_factory, tuning.rows, manifest.to_dict(), "hparam_selection")
    assert tuning.binding.receipt()["status"] == "ready"
    monkeypatch.setattr(numeric, "_build", forbidden)
    with pytest.raises(subject.Native4096BoundError):
        build(parent, training, tuning)


@pytest.mark.parametrize("invalid", [None, True, "", "0" * 64, "A" * 64])
def test_parent_independent_pin_precedes_numerical_build(parent, native_factory, monkeypatch, invalid):
    training, tuning = batches(native_factory)
    monkeypatch.setattr(numeric, "_build", forbidden)
    with pytest.raises(subject.Native4096BoundError):
        subject.build_bound_checkpoint(parent, training, tuning, expected_parent_sha256=invalid)


@pytest.mark.parametrize("operation", ["train", "save"])
def test_checkpoint_independent_pin_precedes_numerical_dispatch(parent, native_factory, monkeypatch, tmp_path, operation):
    training, tuning = batches(native_factory)
    checkpoint = build(parent, training, tuning)
    monkeypatch.setattr(numeric, "_train", forbidden)
    monkeypatch.setattr(numeric, "_restore", forbidden)
    with pytest.raises(subject.Native4096BoundError):
        if operation == "train":
            subject.train_bound_decoder(checkpoint, training, tuning, expected_checkpoint_sha256="0" * 64)
        else:
            subject.save_bound_checkpoint(checkpoint, tmp_path / "never-created.json", training, tuning,
                expected_checkpoint_sha256="0" * 64)
    assert not (tmp_path / "never-created.json").exists()


def test_reloaded_checkpoint_does_not_replace_a_revoked_live_handle(parent, native_factory, tmp_path, monkeypatch):
    training, tuning = batches(native_factory)
    checkpoint = build(parent, training, tuning)
    saved = subject.save_bound_checkpoint(checkpoint, tmp_path / "saved.json", training, tuning,
        expected_checkpoint_sha256=digest(checkpoint))
    monkeypatch.delitem(owner._ISSUED, training.native_result)
    monkeypatch.setattr(numeric, "_restore", forbidden)
    with pytest.raises(subject.Native4096BoundError):
        subject.load_bound_checkpoint(saved["path"], training, tuning, expected_sha256=saved["sha256"])


def test_raw_file_pin_is_separate_from_canonical_checkpoint_digest(parent, native_factory, tmp_path, monkeypatch):
    training, tuning = batches(native_factory)
    checkpoint = build(parent, training, tuning)
    raw = (json.dumps(checkpoint, sort_keys=True, indent=2) + "\n").encode()
    raw_sha = hashlib.sha256(raw).hexdigest()
    assert raw_sha != digest(checkpoint)
    path = tmp_path / "pretty-native4096.json"
    path.write_bytes(raw)
    loaded = subject.load_bound_checkpoint(path, training, tuning, expected_sha256=raw_sha)
    assert loaded == checkpoint
    assert train(loaded, training, tuning, max_steps=0, max_seconds=0)["checkpoint"] == checkpoint
    monkeypatch.setattr(numeric, "_restore", forbidden)
    monkeypatch.setattr(numeric, "_train", forbidden)
    with pytest.raises(subject.Native4096BoundError):
        subject.load_bound_checkpoint(path, training, tuning, expected_sha256=digest(checkpoint))
    with pytest.raises(subject.Native4096BoundError):
        subject.train_bound_decoder(loaded, training, tuning, expected_checkpoint_sha256=raw_sha)


@pytest.mark.parametrize("options", [
    {"learning_rate": True}, {"learning_rate": 0}, {"learning_rate": float("nan")},
    {"learning_rate": float("inf")}, {"learning_rate": .101},
    {"batch_size": True}, {"batch_size": 0}, {"batch_size": 33},
    {"latent_enabled": 1}, {"latent_enabled": None},
])
def test_invalid_build_scalars_precede_numerical_build(parent, native_factory, monkeypatch, options):
    training, tuning = batches(native_factory)
    monkeypatch.setattr(numeric, "_build", forbidden)
    with pytest.raises(subject.Native4096BoundError):
        subject.build_bound_checkpoint(parent, training, tuning,
            expected_parent_sha256=digest(parent), **options)


@pytest.mark.parametrize("options", [
    {"max_steps": True}, {"max_steps": -1}, {"max_steps": 10001},
    {"max_seconds": True}, {"max_seconds": -1}, {"max_seconds": 3601},
    {"max_seconds": float("nan")}, {"max_seconds": float("inf")},
])
def test_invalid_training_budgets_precede_numerical_dispatch(parent, native_factory, monkeypatch, options):
    training, tuning = batches(native_factory)
    checkpoint = build(parent, training, tuning)
    monkeypatch.setattr(numeric, "_train", forbidden)
    with pytest.raises(subject.Native4096BoundError):
        train(checkpoint, training, tuning, **options)


@pytest.mark.parametrize("damage", ["dimension", "representation", "producer", "training_index",
    "training_manifest", "tuning_manifest", "authority", "unknown_field"])
def test_rehashed_lineage_mismatches_precede_numeric_training(parent, native_factory, monkeypatch, damage):
    training, tuning = batches(native_factory)
    checkpoint = build(parent, training, tuning)
    if damage == "dimension": checkpoint["config"]["latent_dimension"] = 768
    elif damage == "representation": checkpoint["context_contract"]["representation_id"] = "fixture:other"
    elif damage == "producer": checkpoint["context_contract"]["producer_sha256"] = "f" * 64
    elif damage == "training_index": checkpoint["context_contract"]["training_index_sha256"] = tuning.binding.receipt()["context_contract"]["training_index_sha256"]
    elif damage == "training_manifest": checkpoint["training_manifest_sha256"] = digest(numerical_rows(tuning))
    elif damage == "tuning_manifest": checkpoint["tuning_manifest_sha256"] = digest([])
    elif damage == "authority": checkpoint["qualified"] = True
    else: checkpoint["caller_execution_authority"] = True
    monkeypatch.setattr(numeric, "_train", forbidden)
    with pytest.raises(subject.Native4096BoundError):
        train(checkpoint, training, tuning, max_steps=1)


def inference_inputs(native_factory):
    sources = [{"id": "new-a", "source_text": "The trustee may publish registers."},
               {"id": "new-b", "source_text": "The clerk must disclose accounts."}]
    native = native_factory(sources)
    return sources, dict(native_result=native["native"], expected_producer=deepcopy(native["producer"]),
        expected_producer_sha256=digest(native["producer"]),
        expected_native_receipt_sha256=hashlib.sha256(owner._wire(native["receipt"]) + b"\n").hexdigest())


@pytest.mark.parametrize("ablation", ["none", "zero", "rotate", "disabled"])
def test_new_source_target_free_inference_has_no_optimizer_and_preserves_state(parent, native_factory, monkeypatch, ablation):
    training, tuning = batches(native_factory)
    checkpoint = train(build(parent, training, tuning), training, tuning, max_steps=1, max_seconds=30)["checkpoint"]
    sources, options = inference_inputs(native_factory)
    before = deepcopy((checkpoint, sources, options["expected_producer"]))
    monkeypatch.setattr(torch.optim, "Adam", forbidden)
    observed = subject.decode_bound_sources(checkpoint, sources,
        expected_checkpoint_sha256=digest(checkpoint), latent_ablation=ablation, **options)
    assert observed["input_dimension"] == 4096 and len(observed["rows"]) == len(sources)
    assert observed["target_access"] is observed["teacher_forcing"] is observed["training_executed"] is False
    assert observed["model_state_unchanged"] is True
    input_binding = observed["native_input_binding"]
    assert input_binding["sources_sha256"] == digest(sources)
    assert input_binding["source_ids"] == [item["id"] for item in sources]
    assert input_binding["producer_sha256"] == options["expected_producer_sha256"]
    assert input_binding["native_receipt_sha256"] == options["expected_native_receipt_sha256"]
    assert len(input_binding["verified_observation_sha256"]) == 64
    assert input_binding["serialized_evidence_is_execution_authority"] is False
    assert all(observed[name] is False for name in span.FALSE)
    assert (checkpoint, sources, options["expected_producer"]) == before


@pytest.mark.parametrize("damage", ["source", "extra_target", "producer", "producer_pin", "receipt_pin", "checkpoint_pin", "unissued", "receipt_only"])
def test_inference_rejects_source_or_live_authority_mismatch_before_model(parent, native_factory, monkeypatch, damage):
    training, tuning = batches(native_factory)
    checkpoint = build(parent, training, tuning)
    sources, options = inference_inputs(native_factory)
    pin = digest(checkpoint)
    if damage == "source": sources[0]["source_text"] += " Changed."
    elif damage == "extra_target": sources[0]["canonical_ir"] = deepcopy(training.rows[0]["canonical_ir"])
    elif damage == "producer":
        options["expected_producer"]["model_sha256"] = "f" * 64
        options["expected_producer_sha256"] = digest(options["expected_producer"])
    elif damage == "producer_pin": options["expected_producer_sha256"] = "0" * 64
    elif damage == "receipt_pin": options["expected_native_receipt_sha256"] = "0" * 64
    elif damage == "checkpoint_pin": pin = "0" * 64
    elif damage == "unissued": options["native_result"] = owner.VerifiedForwardResult(owner._TOKEN)
    else: options["native_result"] = deepcopy(native_factory.cases[-1]["receipt"])
    monkeypatch.setattr(numeric, "_restore", forbidden)
    monkeypatch.setattr(numeric, "_decode", forbidden)
    with pytest.raises(subject.Native4096BoundError):
        subject.decode_bound_sources(checkpoint, sources, expected_checkpoint_sha256=pin, **options)


def test_existing_unbound_numerical_owner_refusals_remain_closed(parent, native_factory, monkeypatch):
    training, _ = batches(native_factory)
    numerical = numerical_rows(training)
    old = old_head.build_checkpoint(numerical, context_contract=training.binding.receipt()["context_contract"],
        source_parent=parent, **{key: parent["config"][key] for key in old_head._CONFIG_KEYS})
    monkeypatch.setattr(torch.optim, "Adam", forbidden)
    with pytest.raises(ValueError, match="trusted_native_owner_integration_required"):
        old_head.train_decoder(old, numerical, max_steps=1)
    decoder = old_head.Leanstral4096SpanDecoder(old)
    with pytest.raises(ValueError, match="trusted_native_owner_integration_required"):
        decoder.decode_formal_logic([item["source_text"] for item in numerical], [item["latent"] for item in numerical])


@pytest.mark.parametrize("identity", [{"vector_offset": 1}, {"model_sha256": "f" * 64}])
def test_fresh_binding_with_changed_native_coordinates_cannot_resume(parent, native_factory, monkeypatch, identity):
    training, tuning = batches(native_factory)
    checkpoint = build(parent, training, tuning)
    changed = make_batch(native_factory, training.rows, training.split_manifest, "training", native_options=identity)
    assert changed.binding.receipt()["status"] == "ready"
    assert changed.binding.receipt()["context_contract"] != training.binding.receipt()["context_contract"]
    monkeypatch.setattr(numeric, "_train", forbidden)
    with pytest.raises(subject.Native4096BoundError):
        train(checkpoint, changed, tuning, max_steps=1)


@pytest.mark.parametrize("damage", ["step", "shape", "nonfinite", "negative", "parent_weights"])
def test_inference_checks_retained_adam_and_parent_without_constructing_optimizer(parent, native_factory, monkeypatch, damage):
    training, tuning = batches(native_factory)
    checkpoint = train(build(parent, training, tuning), training, tuning, max_steps=1, max_seconds=30)["checkpoint"]
    moment = checkpoint["optimizer_state"]["parameters"]["latent_down.weight"]
    if damage == "step": moment["step"] += 1
    elif damage == "shape": moment["exp_avg"][0].pop()
    elif damage == "nonfinite": moment["exp_avg"][0][0] = float("nan")
    elif damage == "negative": moment["exp_avg_sq"][0][0] = -.25
    else:
        state = checkpoint["source_parent_checkpoint"]["model_state"]
        name = next(name for name in state if name.endswith("weight") and not name.startswith("latent_"))
        state[name][0][0] += .125
    sources, options = inference_inputs(native_factory)
    monkeypatch.setattr(torch.optim, "Adam", forbidden)
    if damage == "nonfinite":
        pin = "0" * 64  # canonical commitment itself is unavailable for nonfinite JSON
    else:
        pin = digest(checkpoint)
    with pytest.raises((subject.Native4096BoundError, ValueError)):
        subject.decode_bound_sources(checkpoint, sources, expected_checkpoint_sha256=pin, **options)


def test_interrupted_fsync_removes_own_leaf_and_allows_exact_retry(parent, native_factory, monkeypatch, tmp_path):
    training, tuning = batches(native_factory)
    checkpoint = build(parent, training, tuning)
    path = tmp_path / "interrupted-save.json"
    unrelated = tmp_path / "other-writer.json"
    unrelated.write_bytes(b"retained unrelated bytes\n")
    calls = []

    def interrupted(fd):
        calls.append(fd)
        raise OSError("fictional interrupted checkpoint fsync")

    with monkeypatch.context() as patch:
        patch.setattr(subject.os, "fsync", interrupted)
        with pytest.raises(OSError, match="interrupted checkpoint fsync"):
            subject.save_bound_checkpoint(checkpoint, path, training, tuning,
                expected_checkpoint_sha256=digest(checkpoint))
    assert len(calls) == 1 and not path.exists()
    assert unrelated.read_bytes() == b"retained unrelated bytes\n"
    saved = subject.save_bound_checkpoint(checkpoint, path, training, tuning,
        expected_checkpoint_sha256=digest(checkpoint))
    assert saved["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert subject.load_bound_checkpoint(path, training, tuning, expected_sha256=saved["sha256"]) == checkpoint


def test_interrupted_save_preserves_replacement_leaf_from_another_writer(parent, native_factory, monkeypatch, tmp_path):
    training, tuning = batches(native_factory)
    checkpoint = build(parent, training, tuning)
    path = tmp_path / "replaced-save.json"
    replacement = b"fictional concurrent writer bytes\n"

    def replace_then_interrupt(fd):
        # No symlink or hardlink: the replacement has a new inode while the
        # original writer's open descriptor keeps its unlinked inode alive.
        path.unlink()
        path.write_bytes(replacement)
        raise OSError("fictional replacement during checkpoint fsync")

    with monkeypatch.context() as patch:
        patch.setattr(subject.os, "fsync", replace_then_interrupt)
        with pytest.raises(OSError, match="replacement during checkpoint fsync"):
            subject.save_bound_checkpoint(checkpoint, path, training, tuning,
                expected_checkpoint_sha256=digest(checkpoint))
    assert path.read_bytes() == replacement


def test_save_never_overwrites_a_retained_checkpoint(parent, native_factory, tmp_path):
    training, tuning = batches(native_factory)
    checkpoint = build(parent, training, tuning)
    path = tmp_path / "retained.json"
    saved = subject.save_bound_checkpoint(checkpoint, path, training, tuning,
        expected_checkpoint_sha256=digest(checkpoint))
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        subject.save_bound_checkpoint(checkpoint, path, training, tuning,
            expected_checkpoint_sha256=digest(checkpoint))
    assert path.read_bytes() == before
    assert subject.load_bound_checkpoint(path, training, tuning, expected_sha256=saved["sha256"]) == checkpoint


def native_receipt_references(training, tuning=None):
    return {"training": training.binding.receipt()["native_receipt_sha256"],
            "tuning": tuning.binding.receipt()["native_receipt_sha256"] if tuning is not None else None}


@pytest.mark.parametrize("with_tuning", [False, True])
def test_provenance_keeps_initial_receipts_and_records_last_actual_update_without_authority(parent, native_factory, with_tuning):
    training, tuning = batches(native_factory)
    tuning = tuning if with_tuning else None
    initial = build(parent, training, tuning)
    initial_refs = native_receipt_references(training, tuning)
    assert initial["provenance"] == {
        "schema": "bound-native4096-input-provenance/v1", "kind": "live_bound_engineering_inputs",
        "serialized_evidence_is_execution_authority": False,
        "initial_native_receipts": initial_refs, "last_native_receipts": initial_refs}
    fresh_training, fresh_tuning = batches(native_factory)
    fresh_tuning = fresh_tuning if with_tuning else None
    fresh_refs = native_receipt_references(fresh_training, fresh_tuning)
    assert fresh_refs != initial_refs
    unchanged = train(initial, fresh_training, fresh_tuning, max_steps=0, max_seconds=0)
    assert unchanged["checkpoint"] == initial
    assert unchanged["report"]["native_receipts"] == fresh_refs
    assert unchanged["report"]["training_executed"] is False
    result = train(initial, fresh_training, fresh_tuning, max_steps=1, max_seconds=30)
    checkpoint, report = result["checkpoint"], result["report"]
    assert checkpoint["provenance"]["initial_native_receipts"] == initial_refs
    assert checkpoint["provenance"]["last_native_receipts"] == fresh_refs
    assert checkpoint["batch_contracts"] == initial["batch_contracts"]
    assert report["native_receipts"] == fresh_refs
    assert checkpoint["provenance"]["serialized_evidence_is_execution_authority"] is False
    assert report["serialized_evidence_is_execution_authority"] is False
    assert all(checkpoint[name] is report[name] is False for name in span.FALSE)
    for batch in (training, fresh_training):
        receipt = batch.binding.receipt()
        assert receipt["ordinary_receipt_is_capability"] is False
        assert receipt["resource_admission_granted"] is False
        assert receipt["training_gold_authority"] is receipt["semantic_authority"] is False


@pytest.mark.parametrize("damage", ["serialized_authority", "zero_step_last_receipt"])
def test_rehashed_provenance_cannot_promote_authority_or_invent_zero_step_updates(parent, native_factory, monkeypatch, damage):
    training, tuning = batches(native_factory)
    checkpoint = build(parent, training, tuning)
    if damage == "serialized_authority":
        checkpoint["provenance"]["serialized_evidence_is_execution_authority"] = True
    else:
        checkpoint["provenance"]["last_native_receipts"]["training"] = "f" * 64
    monkeypatch.setattr(numeric, "_train", forbidden)
    with pytest.raises(subject.Native4096BoundError):
        train(checkpoint, training, tuning, max_steps=1)


@pytest.mark.parametrize("operation,damage", [
    ("build", "scalar"), ("build", "source"),
    ("train", "scalar"), ("train", "source"),
    ("save", "source"), ("train", "revoked"),
])
def test_invalid_preflight_does_not_call_torch_importing_configuration_factory(parent, native_factory, monkeypatch, tmp_path, operation, damage):
    training, tuning = batches(native_factory)
    checkpoint = build(parent, training, tuning) if operation != "build" else None
    if damage == "source": training.rows[0]["source_text"] += " Changed before dispatch."
    elif damage == "revoked": monkeypatch.delitem(owner._ISSUED, training.native_result)
    monkeypatch.setattr(old_head, "_config", forbidden)
    with pytest.raises(subject.Native4096BoundError) as caught:
        if operation == "build":
            build(parent, training, tuning, **({"learning_rate": True} if damage == "scalar" else {}))
        elif operation == "train":
            train(checkpoint, training, tuning, **({"max_steps": -1} if damage == "scalar" else {}))
        else:
            subject.save_bound_checkpoint(checkpoint, tmp_path / "never-created-preflight.json", training, tuning,
                expected_checkpoint_sha256=digest(checkpoint))
    # Ensure the intended bad input was rejected, rather than accidentally
    # succeeding only because a later implementation-pin check saw the spy.
    assert "numerical helper changed" not in str(caught.value)
    assert not (tmp_path / "never-created-preflight.json").exists()


def plain_json_node_count(value):
    """Count the finite fixture's JSON values and object keys independently."""
    pending, total = [value], 0
    while pending:
        item = pending.pop()
        total += 1
        if type(item) is dict:
            pending.extend(item.keys())
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
    return total


def test_build_cannot_return_a_checkpoint_larger_than_public_node_contract(parent, native_factory, monkeypatch):
    training, tuning = batches(native_factory)
    admitted = build(parent, training, tuning)
    train_rows, tune_rows = numerical_rows(training), numerical_rows(tuning)
    context = deepcopy(admitted["context_contract"])
    contracts = deepcopy(admitted["batch_contracts"])
    receipts = native_receipt_references(training, tuning)
    inputs = {"parent": parent, "train": train_rows, "tune": tune_rows,
        "context": context, "batch_contracts": contracts, "native_receipts": receipts}
    before = deepcopy(inputs)
    input_nodes, output_nodes = plain_json_node_count(inputs), plain_json_node_count(admitted)
    assert input_nodes < output_nodes, (input_nodes, output_nodes)
    bound = (input_nodes + output_nodes) // 2
    assert input_nodes <= bound < output_nodes, (input_nodes, bound, output_nodes)
    monkeypatch.setattr(base, "MAX_NODES", bound)
    # These checks establish that the lowered bound admits the entire original
    # input population and rejects only the expanded serialized checkpoint.
    assert base._preflight(inputs) == span._raw(inputs)
    assert base._preflight(parent) == span._raw(parent)
    with pytest.raises(base.SourceSpanConsumerBindingError, match="node/depth bound"):
        base._preflight(admitted)
    with pytest.raises(ValueError, match="node/depth bound"):
        numeric._build(parent, train_rows, tune_rows, context_contract=context,
            batch_contracts=contracts, native_receipts=receipts, batch_size=2)
    assert inputs == before


def test_training_cannot_return_adam_state_larger_than_public_byte_contract(parent, native_factory, monkeypatch):
    training, tuning = batches(native_factory)
    initial = build(parent, training, tuning)
    train_rows, tune_rows = numerical_rows(training), numerical_rows(tuning)
    receipts = native_receipt_references(training, tuning)
    inputs = {"training": train_rows, "tuning": tune_rows, "native_receipts": receipts}
    before = deepcopy((initial, inputs))
    completed = numeric._train(initial, train_rows, tune_rows, native_receipts=receipts,
        max_steps=1, max_seconds=30)
    assert completed["report"]["optimizer_steps"] == 1
    output = completed["checkpoint"]
    assert output["optimizer_state"]["parameters"] and not initial["optimizer_state"]["parameters"]
    input_bytes = max(len(span._raw(initial)), len(span._raw(inputs)))
    output_bytes = len(span._raw(output))
    assert input_bytes < output_bytes, (input_bytes, output_bytes)
    bound = (input_bytes + output_bytes) // 2
    assert input_bytes <= bound < output_bytes, (input_bytes, bound, output_bytes)
    monkeypatch.setattr(base, "MAX_BYTES", bound)
    monkeypatch.setattr(numeric, "MAX_BYTES", bound)
    assert base._preflight(initial) == span._raw(initial)
    assert base._preflight(inputs) == span._raw(inputs)
    with pytest.raises(base.SourceSpanConsumerBindingError, match="byte bound"):
        base._preflight(output)
    with pytest.raises(ValueError, match="byte bound"):
        numeric._train(initial, train_rows, tune_rows, native_receipts=receipts,
            max_steps=1, max_seconds=30)
    assert (initial, inputs) == before


# Model-only file admission controls. This deliberately incomplete tensor fixture
# exercises the genuine metadata gates with numerical restoration replaced by an
# inert boundary. Separate retained-state cases qualify actual tensor restoration.
# These controls call no fitting, decoder initialization or native issuance API.
def inference_load_metadata_checkpoint():
    config = {"latent_enabled": True, "learning_rate": .001, "batch_size": 1,
        "seed": 1729, "hidden_size": 8, "embedding_dim": 4,
        "projection_width": 4, "residual_scale": .25}
    parent = {"schema": span.SCHEMA, "lineage_id": span.LINEAGE_ID,
        "implementation": span._implementation(),
        "config": {**config, "latent_dimension": 0, "latent_enabled": False},
        "training_manifest_sha256": "a" * 64, "training_count": 1,
        "tuning_manifest_sha256": digest([]), "tuning_count": 0,
        "model_state": {}, "optimizer_state": {},
        "progress": {"epochs_completed": 1, "row_cursor": 0, "optimizer_steps": 1},
        "parent_checkpoint_sha256": "b" * 64, **span.FALSE}
    context = {"dimension": 4096, "representation_id": owner.PROFILE,
        "producer_sha256": "c" * 64, "training_index_sha256": "d" * 64}
    contracts = {"training": {"input_sha256s": {"rows": "e" * 64,
        "split_manifest": "f" * 64, "eligibility": "1" * 64, "exposure": "2" * 64},
        "context_contract": deepcopy(context), "numerical_rows_sha256": "3" * 64}, "tuning": None}
    refs = {"training": "4" * 64, "tuning": None}
    return {"schema": numeric.SCHEMA, "lineage_id": numeric.LINEAGE_ID,
        "implementation": numeric._implementation(),
        "provenance": {"schema": "bound-native4096-input-provenance/v1",
            "kind": "live_bound_engineering_inputs", "serialized_evidence_is_execution_authority": False,
            "initial_native_receipts": deepcopy(refs), "last_native_receipts": deepcopy(refs)},
        "config": {**config, "architecture": old_head.ARCHITECTURE, "latent_dimension": 4096,
            "device": "cpu", "dtype": "float32", "torch_version": "metadata-fixture-only",
            "max_source_characters": span.MAX_SOURCE_CHARACTERS,
            "max_source_tokens": span.MAX_SOURCE_TOKENS, "max_token_bytes": span.MAX_TOKEN_BYTES,
            "tokenizer": "unicode_word_or_punctuation_exact_offsets/v1",
            "byte_alphabet": "casefold_utf8_plus1_pad0/v1",
            "initialization": "fresh_native4096_adapter_exact_zero_output/v1",
            "loss": "equal_facet_modality_presence_mean_start_end/v1"},
        "context_contract": context, "context_contract_sha256": digest(context),
        "batch_contracts": contracts, "source_parent_checkpoint": parent,
        "source_parent_checkpoint_sha256": digest(parent), "source_parent_optimizer_steps": 1,
        "initial_source_model_sha256": "5" * 64, "initial_model_state_sha256": "6" * 64,
        "training_manifest_sha256": "3" * 64, "training_count": 1,
        "tuning_manifest_sha256": digest([]), "tuning_count": 0,
        "model_state": {}, "optimizer_state": {},
        "progress": {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0},
        "parent_checkpoint_sha256": None, **span.FALSE}


def inference_load_write(path, checkpoint, *, pretty=False):
    raw = (json.dumps(checkpoint, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
           if pretty else span._raw(checkpoint) + b"\n")
    path.write_bytes(raw)
    return raw, hashlib.sha256(raw).hexdigest()


def inference_load_forbid_operations(monkeypatch):
    # These are independent prohibited boundaries, not substitutes for numerical
    # helper validation. No native issuance registry is populated by this cohort.
    def no_training_binding(*args, **kwargs):
        pytest.fail("model-only load attempted training/tuning materialization")
    def no_numerical_execution(*args, **kwargs):
        pytest.fail("model-only load attempted fit, decode or native input receiving")
    def no_optimizer(*args, **kwargs):
        pytest.fail("model-only load attempted Adam construction")
    monkeypatch.setattr(subject, "_materialize_batches", no_training_binding)
    monkeypatch.setattr(numeric, "_build", no_numerical_execution)
    monkeypatch.setattr(numeric, "_train", no_numerical_execution)
    monkeypatch.setattr(numeric, "_decode", no_numerical_execution)
    monkeypatch.setattr(binding_owner, "_receive", no_numerical_execution)
    monkeypatch.setattr(torch.optim, "Adam", no_optimizer)


@pytest.mark.parametrize("pretty", [False, True])
def test_inference_file_load_needs_no_training_binding_and_keeps_raw_pin_distinct(tmp_path, monkeypatch, pretty):
    checkpoint = inference_load_metadata_checkpoint()
    before = deepcopy(checkpoint)
    path = tmp_path / "inference-checkpoint.json"
    raw, raw_sha = inference_load_write(path, checkpoint, pretty=pretty)
    restored = []
    def inert_restore(value):
        restored.append(deepcopy(value))
        return object(), object()
    inference_load_forbid_operations(monkeypatch)
    monkeypatch.setattr(numeric, "_restore", inert_restore)
    assert raw_sha != digest(checkpoint)
    loaded = subject.load_bound_inference_checkpoint(path, expected_sha256=raw_sha)
    assert loaded == before and loaded is not checkpoint
    assert restored == [before]
    assert path.read_bytes() == raw and checkpoint == before
    assert all(loaded[key] is False for key in span.FALSE)
    assert loaded["provenance"]["serialized_evidence_is_execution_authority"] is False
    loaded["config"]["seed"] += 1
    assert path.read_bytes() == raw and checkpoint == before and restored == [before]
    with pytest.raises(subject.Native4096BoundError, match="file SHA256"):
        subject.load_bound_inference_checkpoint(path, expected_sha256=digest(checkpoint))
    assert restored == [before]


@pytest.mark.parametrize("expected", [None, True, "A" * 64, "a" * 63, "not-a-digest", "0" * 64])
def test_inference_file_load_refuses_independent_pin_before_numerical_restore(tmp_path, monkeypatch, expected):
    path = tmp_path / "wrong-pin.json"
    raw, _ = inference_load_write(path, inference_load_metadata_checkpoint())
    inference_load_forbid_operations(monkeypatch)
    monkeypatch.setattr(numeric, "_restore", forbidden)
    with pytest.raises(subject.Native4096BoundError):
        subject.load_bound_inference_checkpoint(path, expected_sha256=expected)
    assert path.read_bytes() == raw


@pytest.mark.parametrize("raw", [b'{"schema":1,"schema":2}', b'{"schema":NaN}', b'{}{}', b'[]'])
def test_inference_file_load_refuses_malformed_envelopes_before_numerical_restore(tmp_path, monkeypatch, raw):
    path = tmp_path / "malformed-inference.json"
    path.write_bytes(raw)
    inference_load_forbid_operations(monkeypatch)
    monkeypatch.setattr(numeric, "_restore", forbidden)
    with pytest.raises(subject.Native4096BoundError):
        subject.load_bound_inference_checkpoint(path, expected_sha256=hashlib.sha256(raw).hexdigest())
    assert path.read_bytes() == raw


def inference_load_damage_header(checkpoint, damage):
    if damage == "missing_field": checkpoint.pop("initial_model_state_sha256")
    elif damage == "extra_field": checkpoint["runtime_ready"] = True
    elif damage == "schema": checkpoint["schema"] = old_head.SCHEMA
    elif damage == "lineage": checkpoint["lineage_id"] = old_head.LINEAGE_ID
    elif damage == "authority": checkpoint["qualified"] = True
    elif damage == "numerical_implementation": checkpoint["implementation"]["numeric_sha256"] = "a" * 64
    elif damage == "width": checkpoint["config"]["latent_dimension"] = 768
    elif damage == "boolean_seed": checkpoint["config"]["seed"] = True
    elif damage == "extra_config": checkpoint["config"]["unsupported"] = 1
    elif damage == "device": checkpoint["config"]["device"] = "cuda"
    elif damage == "context_hash": checkpoint["context_contract_sha256"] = "a" * 64
    elif damage == "context_dimension":
        checkpoint["context_contract"]["dimension"] = 768
        checkpoint["context_contract_sha256"] = digest(checkpoint["context_contract"])
    elif damage == "parent_authority":
        checkpoint["source_parent_checkpoint"]["qualified"] = True
        checkpoint["source_parent_checkpoint_sha256"] = digest(checkpoint["source_parent_checkpoint"])
    elif damage == "parent_implementation":
        checkpoint["source_parent_checkpoint"]["implementation"]["span"] = "a" * 64
        checkpoint["source_parent_checkpoint_sha256"] = digest(checkpoint["source_parent_checkpoint"])
    elif damage == "parent_hash": checkpoint["source_parent_checkpoint_sha256"] = "a" * 64
    elif damage == "parent_steps": checkpoint["source_parent_optimizer_steps"] = 2
    elif damage == "inherited_shape": checkpoint["config"]["hidden_size"] = 16
    elif damage == "initial_hash": checkpoint["initial_model_state_sha256"] = "invalid"
    elif damage == "cursor": checkpoint["progress"]["row_cursor"] = 1
    elif damage == "zero_update_parent": checkpoint["parent_checkpoint_sha256"] = "a" * 64
    elif damage == "population": checkpoint["training_count"] = 129
    elif damage == "batch_manifest": checkpoint["batch_contracts"]["training"]["numerical_rows_sha256"] = "a" * 64
    elif damage == "tuning_contract": checkpoint["batch_contracts"]["tuning"] = deepcopy(checkpoint["batch_contracts"]["training"])
    elif damage == "saved_authority": checkpoint["provenance"]["serialized_evidence_is_execution_authority"] = True
    elif damage == "invented_receipt": checkpoint["provenance"]["last_native_receipts"]["training"] = "a" * 64
    else: raise AssertionError(damage)


@pytest.mark.parametrize("damage", ["missing_field", "extra_field", "schema", "lineage", "authority",
    "numerical_implementation", "width", "boolean_seed", "extra_config", "device", "context_hash",
    "context_dimension", "parent_authority", "parent_implementation", "parent_hash", "parent_steps",
    "inherited_shape", "initial_hash", "cursor", "zero_update_parent", "population", "batch_manifest",
    "tuning_contract", "saved_authority", "invented_receipt"])
def test_inference_file_load_rejects_rehashed_header_damage_before_numerical_restore(tmp_path, monkeypatch, damage):
    checkpoint = inference_load_metadata_checkpoint()
    inference_load_damage_header(checkpoint, damage)
    path = tmp_path / "invalid-inference-header.json"
    raw, raw_sha = inference_load_write(path, checkpoint)
    inference_load_forbid_operations(monkeypatch)
    monkeypatch.setattr(numeric, "_restore", forbidden)
    with pytest.raises(subject.Native4096BoundError) as caught:
        subject.load_bound_inference_checkpoint(path, expected_sha256=raw_sha)
    assert "numerical helper changed" not in str(caught.value)
    assert path.read_bytes() == raw


@pytest.mark.parametrize("which", ["original", "detached"])
def test_inference_file_load_rechecks_in_memory_checkpoint_after_restore(tmp_path, monkeypatch, which):
    path = tmp_path / "mutated-inference.json"
    raw, raw_sha = inference_load_write(path, inference_load_metadata_checkpoint())
    original_reader, captured, restored = subject._read, [], []
    def capture_reader(*args, **kwargs):
        value = original_reader(*args, **kwargs)
        captured.append(value)
        return value
    def mutating_restore(value):
        restored.append(True)
        target = captured[0] if which == "original" else value
        target["config"]["seed"] += 1
        return object(), object()
    inference_load_forbid_operations(monkeypatch)
    monkeypatch.setattr(subject, "_read", capture_reader)
    monkeypatch.setattr(numeric, "_restore", mutating_restore)
    with pytest.raises(subject.Native4096BoundError, match="checkpoint changed"):
        subject.load_bound_inference_checkpoint(path, expected_sha256=raw_sha)
    assert restored == [True] and path.read_bytes() == raw


@pytest.mark.parametrize("replacement", ["whitespace", "different_checkpoint"])
def test_inference_file_load_rechecks_pinned_file_after_restore(tmp_path, monkeypatch, replacement):
    checkpoint = inference_load_metadata_checkpoint()
    path = tmp_path / "changed-inference-file.json"
    raw, raw_sha = inference_load_write(path, checkpoint)
    restored = []
    def changing_restore(value):
        restored.append(True)
        if replacement == "whitespace": path.write_bytes(raw + b"\n")
        else:
            changed = deepcopy(checkpoint)
            changed["config"]["seed"] += 1
            inference_load_write(path, changed)
        return object(), object()
    inference_load_forbid_operations(monkeypatch)
    monkeypatch.setattr(numeric, "_restore", changing_restore)
    with pytest.raises(subject.Native4096BoundError, match="file SHA256"):
        subject.load_bound_inference_checkpoint(path, expected_sha256=raw_sha)
    assert restored == [True] and path.read_bytes() != raw


def test_inference_file_load_rechecks_implementation_after_restore(tmp_path, monkeypatch):
    path = tmp_path / "implementation-fence.json"
    raw, raw_sha = inference_load_write(path, inference_load_metadata_checkpoint())
    original, observations, restored = subject._implementation, [], []
    def implementation_fence():
        observations.append(True)
        if len(observations) == 2:
            raise subject.Native4096BoundError("implementation changed after restoration")
        return original()
    def inert_restore(value):
        restored.append(True)
        return object(), object()
    inference_load_forbid_operations(monkeypatch)
    monkeypatch.setattr(subject, "_implementation", implementation_fence)
    monkeypatch.setattr(numeric, "_restore", inert_restore)
    with pytest.raises(subject.Native4096BoundError, match="implementation changed after restoration"):
        subject.load_bound_inference_checkpoint(path, expected_sha256=raw_sha)
    assert observations == [True, True] and restored == [True] and path.read_bytes() == raw


def test_inference_file_load_enforces_existing_file_byte_limit_before_restore(tmp_path, monkeypatch):
    path = tmp_path / "bounded-inference.json"
    raw, raw_sha = inference_load_write(path, inference_load_metadata_checkpoint())
    inference_load_forbid_operations(monkeypatch)
    monkeypatch.setattr(subject, "MAX_BYTES", len(raw) - 1)
    monkeypatch.setattr(numeric, "_restore", forbidden)
    with pytest.raises(subject.Native4096BoundError, match="bounded single-link regular checkpoint"):
        subject.load_bound_inference_checkpoint(path, expected_sha256=raw_sha)
    assert path.read_bytes() == raw


def test_inference_file_load_preserves_numerical_restore_refusal(tmp_path, monkeypatch):
    path = tmp_path / "restore-refused.json"
    raw, raw_sha = inference_load_write(path, inference_load_metadata_checkpoint())
    inference_load_forbid_operations(monkeypatch)
    def refused_restore(value):
        raise ValueError("retained model tensor shape mismatch")
    monkeypatch.setattr(numeric, "_restore", refused_restore)
    with pytest.raises(subject.Native4096BoundError, match="retained model tensor shape mismatch"):
        subject.load_bound_inference_checkpoint(path, expected_sha256=raw_sha)
    assert path.read_bytes() == raw


def test_inference_file_load_does_not_turn_saved_receipt_into_native_decode_authority(tmp_path, monkeypatch):
    checkpoint = inference_load_metadata_checkpoint()
    producer = {"profile": owner.PROFILE, "model_sha256": "a" * 64,
        "worker_sha256": "b" * 64, "worker_source_sha256": "c" * 64,
        "owner_source_sha256": _sha_file(owner.__file__),
        "vocabulary_owner_source_sha256": _sha_file(owner.vocab.__file__),
        "library_sha256": {"/declared/native/libllama.so": "d" * 64}}
    checkpoint["context_contract"]["producer_sha256"] = digest(producer)
    checkpoint["context_contract_sha256"] = digest(checkpoint["context_contract"])
    checkpoint["batch_contracts"]["training"]["context_contract"] = deepcopy(checkpoint["context_contract"])
    path = tmp_path / "receipt-is-not-capability.json"
    raw, raw_sha = inference_load_write(path, checkpoint)
    restored = []
    def inert_restore(value):
        restored.append(True)
        return object(), object()
    monkeypatch.setattr(numeric, "_restore", inert_restore)
    monkeypatch.setattr(numeric, "_decode", forbidden)
    monkeypatch.setattr(subject, "_materialize_batches", forbidden)
    loaded = subject.load_bound_inference_checkpoint(path, expected_sha256=raw_sha)
    saved_receipt = {"schema": owner.SCHEMA, "complete": True,
        "full_forward_executed": True, "rows": [], "persisted_receipt_is_execution_authority": False}
    with pytest.raises(subject.Native4096BoundError, match="native4096 source receiving failed"):
        subject.decode_bound_sources(loaded,
            [{"id": "new-source", "source_text": "The agency must retain records."}],
            expected_checkpoint_sha256=digest(loaded), native_result=saved_receipt,
            expected_producer=producer, expected_producer_sha256=digest(producer),
            expected_native_receipt_sha256="e" * 64)
    assert restored == [True] and path.read_bytes() == raw


@pytest.mark.parametrize("which", ["original", "detached"])
def test_inference_file_load_rechecks_state_after_closing_pathlike_callback(tmp_path, monkeypatch, which):
    path = tmp_path / "closing-pathlike-fence.json"
    raw, raw_sha = inference_load_write(path, inference_load_metadata_checkpoint())
    reader, captured, restored, path_calls = subject._read, [], [], []
    def capture_reader(*args, **kwargs):
        value = reader(*args, **kwargs)
        captured.append(value)
        return value
    def inert_restore(value):
        restored.append(value)
        return object(), object()
    class ChangingPath:
        def __fspath__(self):
            path_calls.append(True)
            if len(path_calls) == 2:
                target = captured[0] if which == "original" else restored[0]
                target["config"]["seed"] += 1
            return str(path)
    inference_load_forbid_operations(monkeypatch)
    monkeypatch.setattr(subject, "_read", capture_reader)
    monkeypatch.setattr(numeric, "_restore", inert_restore)
    with pytest.raises(subject.Native4096BoundError, match="checkpoint changed"):
        subject.load_bound_inference_checkpoint(ChangingPath(), expected_sha256=raw_sha)
    assert len(path_calls) == 2 and len(restored) == 1 and path.read_bytes() == raw
