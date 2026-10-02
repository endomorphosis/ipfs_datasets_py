"""One explicit non-Security pin migration, with real unchanged decoder inference."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import source_program_runtime_384_v2 as api
from ipfs_datasets_py.logic.formalization.autoencoder import source_program_runtime_384 as strict
from ipfs_datasets_py.logic.software_verification.program import ProgramExpression


TEXT = "def compute(left: int, right: int) -> int:\n    return left + right\n"


def digest(value):
    return hashlib.sha256(api.structured._raw(value)).hexdigest()


def checkpoint():
    """Authored numeric test fixture; no training/generalization claim."""
    refs = ("expr:left", "expr:right")
    target = dict(kind="program_expression", document=ProgramExpression("expr:result", "binary", "integer",
        operand_ids=refs, evaluation_order=refs, operator="+", source_ref_ids=("source",)).to_dict())
    template = deepcopy(target); template["document"]["operator"] = None
    projection = {"projection_down.weight": [[0.] * 384], "projection_down.bias": [0.],
        "projection_up.weight": [[0.] for _ in range(384)], "projection_up.bias": [0.] * 384}
    state = dict(weights=[[1., -1.], *([[0., 0.]] * 383)], bias=[0., 0.])
    implementation = api.structured._implementation()
    assert api._pin(implementation) == api.NEW_UI_SHA256
    implementation["shared_runtime"]["native"]["dependencies"][api.UI_DEPENDENCY] = api.OLD_UI_SHA256
    manifests = []
    for label in ("training", "validation"):
        manifests.append([dict(id=label, **{key: hashlib.sha256((label + key).encode()).hexdigest()
            for key in ("source_sha256", "normalized_source_sha256", "embedding_sha256", "target_sha256")})])
    return dict(schema=api.structured.SCHEMA, domain_id="security_ir", dimension=384,
        implementation=implementation,
        config=dict(ridges=[.01], embedding_provenance={"model_id": "authored-unit-vector"}),
        parent_sha256="a" * 64, parent_binding={"dimension": 384}, projection_width=1,
        projection_state=projection, projection_sha256=digest(projection),
        input_transform=dict(mean=[0.] * 384, scale=1., origin="training_projected_embeddings_only"),
        target_schema=dict(schema="fixed-typed-json-consensus/v1", shape=api.structured._shape(target),
            template=template, slots=[dict(path=["document", "operator"], classes=["+", "-"])],
            origin="training_only", whole_target_memory=False),
        head_state=state, head_sha256=digest(state), training_manifest=manifests[0], validation_manifest=manifests[1],
        training=dict(selected_ridge=.01, test_used_for_selection=False, gradient_training_used=False),
        lineage=dict(parent_encoder_frozen=True, projection_tensors_inherited_exactly=list(api.structured.PROJECTION_KEYS),
            parent_modified=False, random_parameters_used=False), **api.structured.FALSE)


@pytest.fixture
def artifact(tmp_path):
    value = checkpoint()
    path, checksum = write(tmp_path, value)
    return path, checksum, value


def write(directory, value):
    raw = api.structured._raw(value)
    checksum = hashlib.sha256(raw).hexdigest()
    path = directory / (checksum + ".json")
    path.write_bytes(raw)
    return path, checksum


def rows():
    return [dict(id="input-0", source_text=TEXT, embedding=[1.] + [0.] * 383)]


def test_known_ui_delta_loads_unchanged_weights_and_preserves_strict_loader(artifact):
    path, checksum, value = artifact
    original = path.read_bytes()
    with pytest.raises(ValueError, match="implementation pins differ"):
        strict.load_source_program_decoder_384(path, expected_sha256=checksum)
    loaded = api.load_source_program_decoder_384_v2(path, expected_sha256=checksum)
    description = loaded.describe()
    receipt = description["checkpoint_compatibility"]
    assert receipt["mode"] == "known_unrelated_ui_decoder_pin" and receipt["applied"]
    assert receipt["artifact_sha256"] == checksum == description["checkpoint_sha256"]
    assert receipt["runtime_view_sha256"] != checksum
    assert receipt["changed_pins"] == [dict(path=list(api.PIN_PATH), before=api.OLD_UI_SHA256, after=api.NEW_UI_SHA256)]
    runtime = loaded.decoder.runtime
    assert runtime.checkpoint["implementation"] == api.structured._implementation()
    for key in value:
        if key != "implementation": assert runtime.checkpoint[key] == value[key]
    inferred = loaded.infer(rows())
    assert inferred["checkpoint_compatibility"] == receipt
    assert inferred["rows"][0]["candidate_ir"]["document"]["operator"] == "+"
    assert inferred["rows"][0]["source_contract"]["status"] == "qualified"
    assert all(receipt[key] == expected for key, expected in api.UNCHANGED.items())
    assert api.verify_checkpoint_compatibility(receipt, path, checksum) == receipt
    assert api.validate_checkpoint_compatibility(receipt, checksum) == receipt
    assert path.read_bytes() == original
    # Metadata returned to callers cannot mutate the internal compatibility state.
    receipt["changed_pins"].clear()
    assert loaded.describe()["checkpoint_compatibility"]["applied"]


def test_exact_current_checkpoint_uses_strict_mode_and_same_predictions(tmp_path):
    value = checkpoint(); value["implementation"] = api.structured._implementation()
    path, checksum = write(tmp_path, value)
    compatible = api.load_source_program_decoder_384_v2(path, expected_sha256=checksum)
    original = strict.load_source_program_decoder_384(path, expected_sha256=checksum)
    report = compatible.infer(rows())
    assert report["rows"] == original.infer(rows())["rows"]
    receipt = report["checkpoint_compatibility"]
    assert receipt["mode"] == "strict" and not receipt["applied"] and receipt["changed_pins"] == []
    assert receipt["runtime_view_sha256"] == checksum


@pytest.mark.parametrize("change", ["unknown_ui", "numerical", "security", "runtime", "extra_pin", "missing_pin"])
def test_every_other_implementation_change_is_rejected(tmp_path, change):
    value = checkpoint()
    shared = value["implementation"]["shared_runtime"]
    deps = shared["native"]["dependencies"]
    if change == "unknown_ui": deps[api.UI_DEPENDENCY] = "b" * 64
    elif change == "numerical": shared["numerical"]["invented"] = "b" * 64
    elif change == "security": deps["ipfs_datasets_py.logic.security_ir.model"] = "b" * 64
    elif change == "runtime": value["implementation"]["runtime_sha256"] = "b" * 64
    elif change == "extra_pin": deps["unexpected.module"] = "b" * 64
    else: deps.pop(api.UI_DEPENDENCY)
    path, checksum = write(tmp_path, value)
    with pytest.raises(ValueError, match="pin|implementation"):
        api.load_source_program_decoder_384_v2(path, expected_sha256=checksum)


@pytest.mark.parametrize("change", ["domain", "schema", "missing_weight", "changed_weight", "changed_projection", "bad_shape", "split_leak"])
def test_compatibility_keeps_original_domain_weight_schema_and_leak_checks(tmp_path, change):
    value = checkpoint()
    if change == "domain": value["domain_id"] = "ui_ux_ir"
    elif change == "schema": value["schema"] = "unknown/v1"
    elif change == "missing_weight": value["head_state"].pop("weights")
    elif change == "changed_weight": value["head_state"]["weights"][0][0] = 99.
    elif change == "changed_projection": value["projection_state"]["projection_down.weight"][0][0] = 99.
    elif change == "bad_shape": value["target_schema"]["shape"] = {"kind": "null"}
    else: value["validation_manifest"] = deepcopy(value["training_manifest"])
    path, checksum = write(tmp_path, value)
    with pytest.raises(ValueError):
        api.load_source_program_decoder_384_v2(path, expected_sha256=checksum)


@pytest.mark.parametrize("checksum", [None, "main", "A" * 64, "a" * 63, "0" * 64])
def test_independent_exact_artifact_sha_is_required(artifact, checksum):
    path, _, _ = artifact
    with pytest.raises(ValueError):
        api.load_source_program_decoder_384_v2(path, expected_sha256=checksum)


def test_nonregular_paths_and_unknown_modes_are_rejected(artifact, tmp_path):
    path, checksum, _ = artifact
    link = tmp_path / "link.json"; link.symlink_to(path)
    with pytest.raises(ValueError, match="regular"):
        api.load_source_program_decoder_384_v2(link, expected_sha256=checksum)
    with pytest.raises(ValueError, match="structured"):
        api.load_source_program_decoder_384_v2(path, expected_sha256=checksum, decoder="sequence_v2")
    with pytest.raises(ValueError, match="input view"):
        api.load_source_program_decoder_384_v2(path, expected_sha256=checksum, input_view="unreviewed")


@pytest.mark.parametrize("change", ["extra", "artifact", "mode", "delta", "authority", "original_pin", "current_pin", "content_digest", "weights_digest"])
def test_forged_receipts_cannot_pass_independent_validation_or_artifact_replay(artifact, change):
    path, checksum, _ = artifact
    receipt = api.load_source_program_decoder_384_v2(path, expected_sha256=checksum).describe()["checkpoint_compatibility"]
    if change == "extra": receipt["trust_me"] = True
    elif change == "artifact": receipt["artifact_sha256"] = "0" * 64
    elif change == "mode": receipt["applied"] = False
    elif change == "delta": receipt["changed_pins"] = []
    elif change == "authority": receipt["proof_authority"] = True
    elif change == "original_pin": receipt["original_implementation"]["runtime_sha256"] = "0" * 64
    elif change == "current_pin": receipt["runtime_implementation"]["runtime_sha256"] = "0" * 64
    elif change == "content_digest": receipt["unchanged_content_sha256"] = "0" * 64
    else: receipt["unchanged_component_sha256"]["head_state"] = "0" * 64
    with pytest.raises(ValueError):
        api.verify_checkpoint_compatibility(receipt, path, checksum)


@pytest.mark.parametrize("view", ["raw", api.INPUT_VIEW])
def test_text_inference_preserves_compatibility_outside_normalization(artifact, monkeypatch, view):
    from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_384
    calls = []
    def embed(texts, **options):
        calls.append((texts, options))
        return [[1.] + [0.] * 383 for _ in texts]
    monkeypatch.setattr(source_embeddings_384, "embed_texts", embed)
    path, checksum, _ = artifact
    loaded = api.load_source_program_decoder_384_v2(path, expected_sha256=checksum, input_view=view)
    text = TEXT.replace("    return left + right", "    result = left + right\n    return result")
    report = loaded.infer_texts([text], snapshot_path="authored-vector-only")
    assert report["checkpoint_compatibility"] == loaded.describe()["checkpoint_compatibility"]
    assert report["input_view"] == view
    assert report["rows"][0]["source_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert report["rows"][0]["source_contract"]["status"] == "qualified"
    assert calls[0][1] == {"snapshot_path": "authored-vector-only"}
    if view == api.INPUT_VIEW:
        assert calls[0][0] == [TEXT] and report["normalization_applied_count"] == 1
        with pytest.raises(ValueError, match="infer_texts"):
            loaded.infer(rows())
    else: assert calls[0][0] == [text]


def test_inference_still_rejects_gold_target_leakage(artifact):
    path, checksum, _ = artifact
    loaded = api.load_source_program_decoder_384_v2(path, expected_sha256=checksum)
    values = rows(); values[0]["target"] = {"gold": "forbidden"}
    with pytest.raises(ValueError, match="closed"):
        loaded.infer(values)


def test_learned_head_is_used_and_source_mismatch_is_not_repaired(artifact):
    path, checksum, _ = artifact
    loaded = api.load_source_program_decoder_384_v2(path, expected_sha256=checksum)
    values = rows(); values[0]["embedding"][0] = -1.
    result = loaded.infer(values)["rows"][0]
    assert result["candidate_ir"]["document"]["operator"] == "-"
    assert result["source_contract"]["status"] == "mismatch"
    assert result["status"] == "fail_open_source_contract_mismatch"
    assert result["continue_planning"] and not result["proof_authority"]


@pytest.mark.parametrize("key", ["implementation", *api.COMPONENTS])
def test_missing_required_checkpoint_components_raise_value_error(tmp_path, key):
    value = checkpoint(); del value[key]
    path, checksum = write(tmp_path, value)
    with pytest.raises(ValueError, match="complete Security"):
        api.load_source_program_decoder_384_v2(path, expected_sha256=checksum)


@pytest.mark.parametrize("invalid", [None, False, [], "implementation", {"shared_runtime": None}])
def test_malformed_implementation_trees_raise_value_error(tmp_path, invalid):
    value = checkpoint(); value["implementation"] = invalid
    path, checksum = write(tmp_path, value)
    with pytest.raises(ValueError, match="pin tree"):
        api.load_source_program_decoder_384_v2(path, expected_sha256=checksum)


def test_known_old_pin_does_not_authorize_an_unreviewed_future_ui_revision(artifact, monkeypatch):
    path, checksum, _ = artifact
    current = api.structured._implementation()
    current["shared_runtime"]["native"]["dependencies"][api.UI_DEPENDENCY] = "f" * 64
    monkeypatch.setattr(api.structured, "_implementation", lambda: deepcopy(current))
    with pytest.raises(ValueError, match="known unrelated"):
        api.load_source_program_decoder_384_v2(path, expected_sha256=checksum)


def test_real_published_checkpoint_replays_archived_precomputed_vector_without_changed_weights():
    root = Path(os.environ.get("IR384_ARCHIVED_ARTIFACT_ROOT", "/home/barberb/lift_coding/artifacts"))
    checksum = "2ca38dfcc05536315fc3e2c0647b710b930ef4066b474061a7b4e5bfb9a258c5"
    path = root / "distributed384-20261001/run-01/security_ir/coordinator/checkpoints" / (checksum + ".json")
    archive = root / "distributed384-richer-semantics-20261001/run-01/checkpoints/security_ir/checks"
    if not path.is_file() or not archive.is_dir():
        pytest.skip("pinned published Security checkpoint and archived inference evidence unavailable; no download")
    original = path.read_bytes()
    inputs = json.loads((archive / "inference-inputs.json").read_text())
    expected = json.loads((archive / "inference.json").read_text())
    with pytest.raises(ValueError, match="implementation pins differ"):
        strict.load_source_program_decoder_384(path, expected_sha256=checksum)
    loaded = api.load_source_program_decoder_384_v2(path, expected_sha256=checksum)
    report = loaded.infer(inputs)
    assert len(report["rows"]) == len(expected) == 1
    for actual, archived in zip(report["rows"], expected):
        for key in ("candidate_ir", "predicted_classes", "projected_embedding", "head_sha256", "projection_sha256"):
            assert actual[key] == archived[key]
        assert actual["source_contract"]["status"] == "qualified"
    receipt = report["checkpoint_compatibility"]
    assert api.verify_checkpoint_compatibility(receipt, path, checksum) == receipt
    assert path.read_bytes() == original and hashlib.sha256(original).hexdigest() == checksum
    original_value = json.loads(original)
    current = loaded.decoder.runtime.checkpoint
    assert all(current[key] == original_value[key] for key in original_value if key != "implementation")
