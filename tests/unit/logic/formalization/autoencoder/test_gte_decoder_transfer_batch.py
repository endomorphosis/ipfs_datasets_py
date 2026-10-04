"""Original-cache decoder prefix admission; all numerical donors are synthetic."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[5]
PATH = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_transfer_batch.py"


def read_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


subject = read_module("gte_decoder_transfer_batch_test_subject", PATH)


def decoder_transfer_fixture(tmp_path_factory):
    """Construct real closed synthetic checkpoints, archives, initialization and batch."""
    torch = pytest.importorskip("torch")
    previous_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        primary_fixture = read_module("gte_transfer_primary_fixture", Path(__file__).with_name("test_gte_decoder_warm_start.py"))
        legacy_fixture = read_module("gte_transfer_legacy_fixture", Path(__file__).with_name("test_gte_legacy8_decoder_donor.py"))
        primary = primary_fixture.donor.__wrapped__(tmp_path_factory)
        primary_checkpoint = deepcopy(primary["checkpoint"])
        def reference(object_name):
            return {"rules": [{"modality": "O", "actor": "agency", "action": "submit", "object": object_name,
                               "conditions": [], "exceptions": [], "temporal": []}]}
        vocabulary = ["<pad>", "<bos>", "<eos>", *sorted(set(subject._json_tokens(reference("reports"))
                                                                + subject._json_tokens(reference("notices"))))]
        primary_checkpoint["codec"] = {"schema": "typed-json-lexical/v1", "target_vocabulary": vocabulary}
        generator = torch.Generator().manual_seed(157)
        shapes = subject._TEACHER._INVENTORY._sequence_shapes(primary_checkpoint, 384)
        primary_checkpoint["model_state"] = {name: (torch.randn(shape, generator=generator) * .05).tolist()
                                               for name, shape in shapes.items()}
        primary_checkpoint["weights_sha256"] = subject.digest(primary_checkpoint["model_state"])
        rows, manifest = [], []
        for index in range(180):
            vector = [0.] * 384
            vector[index] = 1.
            text = "Synthetic independent source " + str(index)
            target = reference("reports" if index % 2 == 0 else "notices")
            row = {"embedding": vector, "embedding_sha256": subject.digest(vector),
                "embedding_token_ids_sha256": "a" * 64, "group_id": "group:" + str(index),
                "id": "training:" + str(index).zfill(3), "proof_authority": False,
                "reference_metadata": {"origin": "synthetic-authored-fixture"}, "source_semantics_verified": False,
                "source_sha256": hashlib.sha256(text.encode()).hexdigest(), "source_text": text,
                "split": "train", "target": target, "wording_style": 0}
            rows.append(row)
            manifest.append({"id": row["id"], "source_sha256": row["source_sha256"],
                "normalized_source_sha256": hashlib.sha256(text.casefold().encode()).hexdigest(),
                "embedding_sha256": row["embedding_sha256"], "target_sha256": subject.digest(target)})
        primary_checkpoint["training_manifest"] = manifest
        primary_archive = {"rows": rows, "source_embeddings": deepcopy(primary_checkpoint["config"]["embedding_provenance"])}
        primary_path = primary["path"]
        primary_path.write_bytes(subject._raw(primary_checkpoint))
        primary_pin = hashlib.sha256(primary_path.read_bytes()).hexdigest()
        legacy = legacy_fixture.checkpoint()
        legacy["codec"]["target_vocabulary"].append(json.dumps(["atom", "object", "notices"], separators=(",", ":")))
        legacy["codec"]["target_vocabulary"][13:] = sorted(legacy["codec"]["target_vocabulary"][13:])
        legacy_shapes = subject._LEGACY._shapes(legacy["config"], len(legacy["codec"]["target_vocabulary"]))
        legacy["model_state"] = {name: (torch.randn(shape, generator=generator) * .05).tolist()
                                  for name, shape in legacy_shapes.items()}
        legacy["optimizer_state"]["parameters"] = {name: {"step": 1,
            "exp_avg": torch.zeros(shape).tolist(), "exp_avg_sq": (torch.ones(shape) * .001).tolist()}
            for name, shape in legacy_shapes.items()}
        legacy["implementation"]["files"] = {name: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                                              for name, path in subject._LEGACY._SOURCE_PATHS.items()}
        legacy_inputs, training, inference_rows = [], [], []
        for index, object_name in enumerate(("reports", "notices")):
            text = "The agency shall submit " + object_name + "."
            vector = [(i % 7 - 3) / 7 * (1 if index == 0 else -1) for i in range(8)]
            latent = []
            for i in range(0, 8, 2):
                latent.extend([.02 * vector[i] + .1 * vector[i + 1], .02 * vector[i + 1] - .1 * vector[i]])
            target = reference(object_name)
            cached = {"citation": "authored-fixture", "embedding_model": "test:explicit-synthetic-vector-not-semantic",
                "embedding_vector": vector, "frame_candidates": [], "losses": {}, "normalized_text": text,
                "parser_trace": {}, "sample_id": object_name, "section": "1", "selected_frame": None,
                "source": "us_code", "text": text, "title": "0", "modal_ir": {"document_id": object_name,
                    "normalized_text": text, "formulas": [{"operator": {"symbol": "O"},
                        "predicate": {"name": "submit", "arguments": ["agency", object_name]},
                        "conditions": [], "exceptions": []}]}}
            legacy_inputs.append(cached)
            training.append({"id": object_name, "source_text": text, "latent": latent,
                             "embedding": vector, "canonical_ir": target})
            observed = {name: False for name in subject._INFERENCE_ROW_FIELDS}
            observed.update({"id": object_name, "canonical_ir": target, "formal_outputs": [], "formula_text": object_name,
                "generated_token_ids": subject._encode(target, legacy["codec"]["target_vocabulary"], "legacy8"),
                "latent_sha256": subject.digest(latent), "minimum_decision_logit_margin": .1,
                "projection_id": "typed_deontic_rule_v1", "reason": None,
                "source_sha256": hashlib.sha256(text.encode()).hexdigest(), "status": "decoded",
                "syntax_scope": "synthetic-reference-fixture", "temperature": 0,
                "latent_input_conditioned": True, "learned_formula_generation": True})
            inference_rows.append(observed)
        legacy["training_manifest_sha256"] = subject.digest(training)
        tuning = [{**row, "id": "tuning-" + row["id"], "source_text": row["source_text"].replace("shall", "must")}
                  for row in training]
        legacy["tuning_manifest_sha256"] = subject.digest(tuning)
        directory = tmp_path_factory.mktemp("transfer_legacy")
        legacy_path, legacy_pin = legacy_fixture.write(directory, legacy)
        _, initialization = subject._REUSE.create_dual_decoder(primary_path, legacy_path,
            expected_teacher384_sha256=primary_pin, expected_legacy8_sha256=legacy_pin,
            repository_root=ROOT, legacy_implementation_root=ROOT)
        inference = {name: False for name in subject._INFERENCE_FIELDS}
        inference.update({"schema": "modal-latent-formula-inference/v1", "status": "decoded",
            "binding": deepcopy(legacy["binding"]), "checkpoint_sha256": legacy_pin, "decoded_count": 2,
            "decoded_embeddings": {row["id"]: row["latent"] for row in training}, "decoded_formulas_generated": True,
            "joint_profile": {"profile": "modal-latent-joint-formula/v1"}, "latent_input_conditioned": True,
            "learned_formula_generation": True, "reconstruction_loss": .1,
            "reconstruction_scope": "synthetic-reference-fixture", "rows": inference_rows})
        fixture = SimpleNamespace(initialization=initialization, primary_checkpoint=primary_checkpoint,
            primary_archive=primary_archive, legacy8_checkpoint=legacy, legacy8_inputs=legacy_inputs,
            legacy8_inference=inference, donor_pins=initialization["donor_pins"], primary_path=primary_path,
            legacy8_path=legacy_path, training=training)
        fixture.batch = prepare(fixture)
        return fixture
    finally:
        torch.set_num_threads(previous_threads)


transfer_fixture = decoder_transfer_fixture


def prepare(fixture, **changes):
    args = {"initialization": fixture.initialization, "expected_donor_pins": fixture.donor_pins,
        "primary_checkpoint": fixture.primary_checkpoint, "primary_archive": fixture.primary_archive,
        "legacy8_checkpoint": fixture.legacy8_checkpoint, "legacy8_inputs": fixture.legacy8_inputs,
        "legacy8_inference": fixture.legacy8_inference}
    args.update(changes)
    return subject.prepare_decoder_transfer_batch(**args)


@pytest.fixture(scope="module")
def fixture(tmp_path_factory):
    return decoder_transfer_fixture(tmp_path_factory)


def inspect(fixture, batch=None):
    return subject.inspect_decoder_transfer_batch(batch or fixture.batch, fixture.initialization,
                                                  expected_donor_pins=fixture.donor_pins)


def resign(batch):
    for head in batch["heads"].values():
        for row in head["rows"]:
            row["row_sha256"] = subject.digest({key: value for key, value in row.items() if key != "row_sha256"})
        head["selected_rows_sha256"] = subject.digest(head["rows"])
    batch["batch_sha256"] = subject.digest({key: value for key, value in batch.items() if key != "batch_sha256"})


def test_import_and_complete_preparation_are_dependency_free(fixture, tmp_path):
    payload = {key: getattr(fixture, key) for key in ("initialization", "primary_checkpoint", "primary_archive",
        "legacy8_checkpoint", "legacy8_inputs", "legacy8_inference")}
    payload["expected_donor_pins"] = fixture.donor_pins
    path = tmp_path / "input.json"
    path.write_text(json.dumps(payload))
    code = """import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('isolated_transfer',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
payload=json.load(open(sys.argv[2]));result=module.prepare_decoder_transfer_batch(**payload)
module.inspect_decoder_transfer_batch(result,payload['initialization'],expected_donor_pins=payload['expected_donor_pins'])
assert not any(name in sys.modules for name in ('torch','numpy','transformers','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH), str(path)], check=True)


def test_complete_archives_admitted_before_sorted_bounded_selection(fixture):
    result = fixture.batch
    assert inspect(fixture)["status"] == "prepared_unqualified"
    assert result["heads"]["primary384"]["available_row_count"] == 180
    assert result["heads"]["primary384"]["selected_row_count"] == 16
    assert result["heads"]["legacy8"]["available_row_count"] == 2
    assert result["heads"]["legacy8"]["selected_row_count"] == 2
    assert [row["id"] for row in result["heads"]["legacy8"]["rows"]] == ["notices", "reports"]
    for head in result["heads"].values():
        for row in head["rows"]:
            assert all(row["reference_token_mask"])
            assert not any(row["kd_token_mask"])
            assert row["prefix_ids"] == row["token_ids"][:-1]
            assert row["next_token_ids"] == row["token_ids"][1:]
    assert result["teacher_qualified"] is False and result["production_kd_eligible"] is False
    assert result["training_executed"] is False and result["distillation_executed"] is False


def test_recovered_legacy8_inputs_match_both_exact_original_manifests(fixture):
    selected = {row["id"]: row for row in fixture.batch["heads"]["legacy8"]["rows"]}
    for original in fixture.training:
        assert selected[original["id"]]["input_vector"] == original["latent"]
        assert selected[original["id"]]["input_sha256"] == subject.digest(original["latent"])
        assert len(selected[original["id"]]["prefix_ids"]) == 15
    assert fixture.batch["heads"]["legacy8"]["original_training_manifest_sha256"] == fixture.legacy8_checkpoint["training_manifest_sha256"]


def test_preparation_and_returned_vectors_do_not_alias_inputs(fixture):
    original = deepcopy(fixture.primary_archive)
    batch = prepare(fixture)
    batch["heads"]["primary384"]["rows"][0]["input_vector"][0] += 1.
    assert fixture.primary_archive == original


@pytest.mark.parametrize("limit", [0, 65, True, -1, 1.5])
def test_bounded_integer_selection_required(fixture, limit):
    with pytest.raises(ValueError):
        prepare(fixture, max_rows_per_head=limit)


@pytest.mark.parametrize("limit", [1, 16, 64])
def test_allowed_limits_apply_independently_to_heads(fixture, limit):
    batch = prepare(fixture, max_rows_per_head=limit)
    assert batch["heads"]["primary384"]["selected_row_count"] == limit
    assert batch["heads"]["legacy8"]["selected_row_count"] == min(limit, 2)
    assert inspect(fixture, batch)["selected_rows"]["primary384"] == limit


@pytest.mark.parametrize("change", ["last_source", "last_vector", "last_target", "last_split", "row_count",
    "duplicate_id", "provenance", "target_oov", "nan", "extra_row_field", "token_digest"])
def test_unselected_primary_rows_are_checked_before_bounded_selection(fixture, change):
    archive = deepcopy(fixture.primary_archive)
    row = archive["rows"][-1]
    if change == "last_source": row["source_text"] += "changed"
    if change == "last_vector": row["embedding"][0] += .1
    if change == "last_target": row["target"]["rules"][0]["object"] = "notices" if row["target"]["rules"][0]["object"] == "reports" else "reports"
    if change == "last_split": row["split"] = "validation"
    if change == "row_count": archive["rows"].pop()
    if change == "duplicate_id": row["id"] = archive["rows"][0]["id"]
    if change == "provenance": archive["source_embeddings"]["normalized"] = 1
    if change == "target_oov": row["target"]["rules"][0]["actor"] = "unknown"
    if change == "nan": row["embedding"][0] = float("nan")
    if change == "extra_row_field": row["teacher_qualified"] = True
    if change == "token_digest": row["embedding_token_ids_sha256"] = "missing"
    with pytest.raises(ValueError):
        prepare(fixture, primary_archive=archive, max_rows_per_head=1)


@pytest.mark.parametrize("change", ["profile", "source", "vector", "alias", "source_binding", "reference",
    "infer_binding", "infer_checkpoint", "infer_latent", "infer_source", "infer_reference", "infer_tokens",
    "duplicate", "tuning_manifest", "training_manifest", "cached_row_count"])
def test_legacy8_raw_cache_and_complete_original_binding_required(fixture, change):
    inputs, inference, legacy = deepcopy(fixture.legacy8_inputs), deepcopy(fixture.legacy8_inference), deepcopy(fixture.legacy8_checkpoint)
    if change == "profile": inputs[0]["embedding_model"] = "legacy-linguistic-features-8d/v1"
    if change == "source": inputs[0]["text"] += "changed"
    if change == "vector": inputs[0]["embedding_vector"][0] += .1
    if change == "alias": inputs[0]["latent"] = inputs[0].pop("embedding_vector")
    if change == "source_binding": inputs[0]["modal_ir"]["document_id"] = "different"
    if change == "reference": inputs[0]["modal_ir"]["formulas"][0]["predicate"]["arguments"][1] = "notices"
    if change == "infer_binding": inference["binding"]["core_sha256"] = "0" * 64
    if change == "infer_checkpoint": inference["checkpoint_sha256"] = "0" * 64
    if change == "infer_latent": inference["rows"][0]["latent_sha256"] = "0" * 64
    if change == "infer_source": inference["rows"][0]["source_sha256"] = "0" * 64
    if change == "infer_reference": inference["rows"][0]["canonical_ir"]["rules"][0]["object"] = "notices"
    if change == "infer_tokens": inference["rows"][0]["generated_token_ids"][1] = 2
    if change == "duplicate": inference["rows"][1]["id"] = inference["rows"][0]["id"]
    if change == "tuning_manifest": legacy["tuning_manifest_sha256"] = "0" * 64
    if change == "training_manifest": legacy["training_manifest_sha256"] = "0" * 64
    if change == "cached_row_count": inputs.pop()
    with pytest.raises(ValueError):
        prepare(fixture, legacy8_inputs=inputs, legacy8_inference=inference, legacy8_checkpoint=legacy)


@pytest.mark.parametrize("branch", ["primary", "legacy"])
def test_original_weights_cannot_be_changed_even_with_recomputed_local_digest(fixture, branch):
    if branch == "primary":
        primary = deepcopy(fixture.primary_checkpoint)
        primary["model_state"]["output.bias"][0] += 1.
        primary["weights_sha256"] = subject.digest(primary["model_state"])
        with pytest.raises(ValueError): prepare(fixture, primary_checkpoint=primary)
    else:
        legacy = deepcopy(fixture.legacy8_checkpoint)
        legacy["model_state"]["output.bias"][0] += 1.
        with pytest.raises(ValueError): prepare(fixture, legacy8_checkpoint=legacy)


@pytest.mark.parametrize("change", ["extra", "claim", "counts", "codec", "input_origin", "input_dimension",
    "input", "prefix", "prefix_bool", "next", "reference", "reference_mask", "kd_mask", "token_bool", "order", "digest", "manifest"])
def test_independent_batch_inspector_rejects_resigned_tampering(fixture, change):
    batch = deepcopy(fixture.batch)
    head = batch["heads"]["primary384"]
    row = head["rows"][0]
    if change == "extra": batch["supervision_approved"] = True
    if change == "claim": batch["production_kd_eligible"] = True
    if change == "counts": head["selected_row_count"] += 1
    if change == "codec": head["codec_sha256"] = "0" * 64
    if change == "input_origin": head["input_origin"] = "new_gte_multilingual_embedding"
    if change == "input_dimension": head["input_dimension"] = 768
    if change == "input": row["input_vector"][0] += .1
    if change == "prefix": row["prefix_ids"][1] = 2
    if change == "prefix_bool": row["prefix_ids"][0] = True
    if change == "next": row["next_token_ids"][1] = 2
    if change == "reference": row["reference_sha256"] = "0" * 64
    if change == "reference_mask": row["reference_token_mask"][0] = 1
    if change == "kd_mask": row["kd_token_mask"][0] = True
    if change == "token_bool": row["token_ids"][1] = True
    if change == "order": head["rows"].reverse()
    if change == "manifest": head["original_training_manifest_sha256"] = "truncated"
    resign(batch)
    if change == "digest": batch["batch_sha256"] = "0" * 64
    with pytest.raises(ValueError): inspect(fixture, batch)
