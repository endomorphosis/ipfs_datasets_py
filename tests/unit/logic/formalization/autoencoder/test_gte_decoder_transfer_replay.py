"""Original-input replay on synthetic donors; no 768D encoder or KD training."""
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
PATH = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_transfer_replay.py"


def read_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


subject = read_module("gte_decoder_transfer_replay_subject", PATH)
reuse_fixture = read_module("gte_transfer_replay_donor_fixture",
                            Path(__file__).with_name("test_gte_decoder_reuse.py"))
torch = pytest.importorskip("torch")


@pytest.fixture(scope="module", autouse=True)
def single_thread():
    before = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(before)


@pytest.fixture(scope="module")
def inputs(tmp_path_factory):
    """Byte-admitted synthetic donors and a strict single-row replay batch.

    Full original-archive admission is tested in the batch and CLI suites. This
    fixture constructs a declared batch directly to isolate numerical behavior.
    """
    donors = reuse_fixture.donors.__wrapped__(tmp_path_factory)
    batch_contract = subject._helper("gte_decoder_transfer_batch")
    reference = {"rules": [{"modality": "O", "actor": "agency", "action": "submit", "object": "reports",
                            "conditions": [], "exceptions": [], "temporal": []}]}
    primary = deepcopy(donors["primary"]["checkpoint"])
    primary["codec"] = {"schema": "typed-json-lexical/v1", "target_vocabulary":
        ["<pad>", "<bos>", "<eos>"] + sorted(set(batch_contract._json_tokens(reference)))}
    shapes = reuse_fixture.subject._PRIMARY._TEACHER._INVENTORY._sequence_shapes(primary, 384)
    generator = torch.Generator().manual_seed(177)
    primary["model_state"] = {name: (torch.randn(shape, generator=generator) * .05).tolist()
                              for name, shape in shapes.items()}
    primary["weights_sha256"] = subject.digest(primary["model_state"])
    primary_path = donors["primary"]["path"]
    primary_path.write_bytes(subject._raw(primary))
    donors["primary"].update(checkpoint=primary, sha256=hashlib.sha256(primary_path.read_bytes()).hexdigest())
    model, initialization = reuse_fixture.create(donors)
    heads = {}
    for name, nested, available, width, origin, vector in (
        ("primary384", "primary", 180, 384, "original_cached_384d_training_input", [1.] + [0.] * 383),
        ("legacy8", "legacy8", 2, 8, "reconstructed_original_raw8_training_latent", [.02, -.1] + [0.] * 6)):
        row = {"id": "synthetic-" + name, "source_text": "The agency shall submit reports."}
        vocabulary = initialization[nested]["codec"]["target_vocabulary"]
        selected = batch_contract._batch_row(row, vector, reference, vocabulary, name)
        heads[name] = {"input_dimension": width, "codec_sha256": subject.digest(initialization[nested]["codec"]),
            "target_vocabulary": vocabulary, "available_row_count": available, "selected_row_count": 1,
            "rows": [selected], "input_origin": origin, "original_training_manifest_sha256":
                subject.digest(primary["training_manifest"]) if width == 384 else donors["legacy"]["training_manifest_sha256"],
            "selected_rows_sha256": subject.digest([selected])}
    batch = {"schema": batch_contract.SCHEMA, "initialization_representation_id": initialization["representation_id"],
        "donor_pins": initialization["donor_pins"], "max_rows_per_head": 1, "heads": heads, **batch_contract.FLAGS}
    batch["batch_sha256"] = subject.digest(batch)
    batch_contract.inspect_decoder_transfer_batch(batch, initialization, expected_donor_pins=initialization["donor_pins"])
    return {"initialization": initialization, "batch": batch, "pins": initialization["donor_pins"],
            "primary": primary, "legacy8": donors["legacy"], "donors": donors, "original_student": model}


def export(inputs):
    return subject.export_decoder_transfer_batch(inputs["initialization"], inputs["batch"],
        expected_donor_pins=inputs["pins"], primary_checkpoint=inputs["primary"], legacy8_checkpoint=inputs["legacy8"])


def inspect(receipt, inputs):
    return subject.inspect_decoder_transfer_replay(receipt, inputs["batch"],
        initialization=inputs["initialization"], expected_donor_pins=inputs["pins"])


@pytest.fixture(scope="module")
def replay(inputs):
    return export(inputs)


def test_import_is_dependency_free():
    program = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('isolated_replay',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('torch','transformers','numpy','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", program, str(PATH)], check=True)


def test_saved_replay_inspection_is_dependency_free(inputs, replay, tmp_path):
    paths = [tmp_path / name for name in ("replay.json", "batch.json", "initialization.json", "pins.json")]
    for path, payload in zip(paths, (replay, inputs["batch"], inputs["initialization"], inputs["pins"])):
        path.write_text(json.dumps(payload))
    program = """import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('isolated_replay_inspection',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
payloads=[json.loads(open(path).read()) for path in sys.argv[2:]]
report=module.inspect_decoder_transfer_replay(payloads[0],payloads[1],initialization=payloads[2],expected_donor_pins=payloads[3])
assert report['total_rows']==2 and report['production_kd_eligible'] is False
assert not any(name in sys.modules for name in ('torch','transformers','numpy','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", program, str(PATH), *map(str, paths)], check=True)


def test_original_input_replay_preserves_both_heads_and_keeps_production_kd_disabled(inputs, replay):
    report = inspect(replay, inputs)
    assert report["row_counts"] == {"primary384": 1, "legacy8": 1}
    assert report["execution_authenticated"] is False
    assert replay["status"] == "behavior_preserved_unqualified"
    assert replay["input_adapter_exercised"] is replay["auxiliary_connector_exercised"] is False
    assert replay["native768_inputs_used"] is False
    assert replay["training_executed"] is replay["distillation_executed"] is False
    assert replay["teacher_qualified"] is replay["production_kd_eligible"] is False
    assert replay["optimizer_steps"] == 0
    for name, head in replay["heads"].items():
        selected = inputs["batch"]["heads"][name]["rows"][0]
        row = head["rows"][0]
        assert head["selected_row_count"] == 1 and head["prefix_policy"] == "reference_prefix"
        assert head["distribution"] == "raw" and head["logits_detached"] is True
        assert row["prefix_ids"] == selected["token_ids"][:-1]
        assert row["next_token_ids"] == selected["token_ids"][1:]
        assert all(row["reference_token_mask"]) and not any(row["kd_token_mask"])
        assert head["diagnostic_kl_temperature"] == 2.
        assert head["diagnostic_kl_t2"] == row["diagnostic_kl_t2"] == 0.
        assert head["exact_projected"] is head["exact_condition"] is head["exact_logits"] is True
        assert head["max_logit_error"] == head["max_projected_error"] == head["max_condition_error"] == 0.
    assert replay["heads"]["primary384"]["vocabulary_size"] != replay["heads"]["legacy8"]["vocabulary_size"]


def test_primary_logits_and_full_condition_use_original_transform_exactly_once(inputs, replay):
    student = inputs["original_student"].primary
    row = inputs["batch"]["heads"]["primary384"]["rows"][0]
    raw = torch.tensor([row["input_vector"]], dtype=torch.float32)
    prefix = torch.tensor([row["prefix_ids"]], dtype=torch.int64)
    transform = inputs["primary"]["input_transform"]
    with torch.no_grad():
        normalized = (raw - torch.tensor(transform["mean"])) / transform["scale"]
        projected = normalized + student.projection_up(torch.tanh(student.projection_down(normalized)))
        condition = torch.tanh(student.condition(projected))
        outputs, _ = student.decoder(student.target_embedding(prefix), condition.unsqueeze(0))
        logits = student.output(outputs)
    record = replay["heads"]["primary384"]["rows"][0]
    assert record["teacher_logits"] == logits.squeeze(0).tolist()
    assert record["teacher_projected_sha256"] == subject.digest(projected.squeeze(0).tolist())
    assert record["teacher_condition_sha256"] == subject.digest(condition.squeeze(0).tolist())
    double_normalized = (normalized - torch.tensor(transform["mean"])) / transform["scale"]
    with torch.no_grad():
        wrong_projected = student.project(double_normalized)
    assert record["teacher_projected_sha256"] != subject.digest(wrong_projected.squeeze(0).tolist())


def test_legacy_logits_use_original_raw_latent_not_sample_target_or_decoded_vector(inputs, replay):
    row = inputs["batch"]["heads"]["legacy8"]["rows"][0]
    student = inputs["original_student"].legacy8
    with torch.no_grad():
        latent = torch.tensor([row["input_vector"]], dtype=torch.float32)
        projected, logits = student(latent, torch.tensor([row["prefix_ids"]], dtype=torch.int64))
        condition = student.start(projected).squeeze(0)
    record = replay["heads"]["legacy8"]["rows"][0]
    assert record["teacher_logits"] == logits.squeeze(0).tolist()
    assert record["teacher_projected_sha256"] == subject.digest(projected.squeeze(0).tolist())
    assert record["teacher_condition_sha256"] == subject.digest(condition.squeeze(0).tolist())
    assert record["input_sha256"] == subject.digest(row["input_vector"])


def test_models_have_all_26_exact_private_tensors_and_no_gradient_buffers(inputs, monkeypatch):
    original_check = subject._private_body_check
    observations = []
    def capture(torch_module, student, primary, legacy, initialization):
        original_check(torch_module, student, primary, legacy, initialization)
        observations.append((student, primary, legacy))
    monkeypatch.setattr(subject, "_private_body_check", capture)
    export(inputs)
    assert len(observations) == 2
    for student, primary, legacy in observations:
        assert all(parameter.grad is None for model in (student, primary, legacy) for parameter in model.parameters())
        for copied, original in ((student.primary, primary), (student.legacy8, legacy)):
            for name, value in original.state_dict().items():
                assert torch.equal(value, copied.state_dict()[name])
                assert value.untyped_storage().data_ptr() != copied.state_dict()[name].untyped_storage().data_ptr()


def test_export_does_not_use_new_interfaces_or_any_optimizer(inputs, monkeypatch):
    helper = subject._helper
    reuse = helper("gte_decoder_reuse")
    def private_load(*args, **kwargs):
        model = reuse.load_dual_decoder(*args, **kwargs)
        def forbidden(*args, **kwargs):
            pytest.fail("decoder replay cannot exercise a new interface")
        model.forward = forbidden
        model.primary.condition_from_input = forbidden
        model.primary.input_adapter.forward = forbidden
        model.auxiliary_connector.forward = forbidden
        return model
    replacement = SimpleNamespace(_PRIMARY=reuse._PRIMARY, _LEGACY=reuse._LEGACY, load_dual_decoder=private_load)
    monkeypatch.setattr(subject, "_helper", lambda name: replacement if name == "gte_decoder_reuse" else helper(name))
    monkeypatch.setattr(torch.optim, "Adam", lambda *args, **kwargs: pytest.fail("no optimizer permitted"))
    receipt = export(inputs)
    assert receipt["status"] == "behavior_preserved_unqualified"


def test_process_rng_threads_grad_mode_and_original_artifacts_are_preserved(inputs):
    before_inputs = deepcopy({key: inputs[key] for key in ("initialization", "batch", "pins", "primary", "legacy8")})
    files = (inputs["donors"]["primary"]["path"], inputs["donors"]["legacy_path"])
    before_files = [path.read_bytes() for path in files]
    before_state = {name: value.clone() for name, value in inputs["original_student"].state_dict().items()}
    prior_threads = torch.get_num_threads()
    torch.set_num_threads(2)
    try:
        before_rng = torch.get_rng_state().clone()
        with torch.no_grad():
            first = export(inputs)
            assert not torch.is_grad_enabled()
        second = export(inputs)
        assert first == second
        assert torch.get_num_threads() == 2 and torch.equal(before_rng, torch.get_rng_state())
    finally:
        torch.set_num_threads(prior_threads)
    assert before_inputs == {key: inputs[key] for key in before_inputs}
    assert [path.read_bytes() for path in files] == before_files
    assert all(torch.equal(value, before_state[name]) for name, value in inputs["original_student"].state_dict().items())


@pytest.mark.parametrize("mutation", ("copied_weight", "copied_logits", "original_load_failure"))
def test_execution_drift_or_failure_is_rejected_and_process_state_restored(inputs, monkeypatch, mutation):
    original_helper = subject._helper
    reuse = original_helper("gte_decoder_reuse")
    def changed_load(*args, **kwargs):
        model = reuse.load_dual_decoder(*args, **kwargs)
        if mutation == "copied_weight":
            model.primary.projection_up.bias.add_(.1)
        else:
            original_decode = model.primary.decode_from_condition
            model.primary.decode_from_condition = lambda *args, **kwargs: original_decode(*args, **kwargs) + .1
        return model
    replacement = SimpleNamespace(_PRIMARY=reuse._PRIMARY, _LEGACY=reuse._LEGACY, load_dual_decoder=changed_load)
    monkeypatch.setattr(subject, "_helper", lambda name:
        replacement if name == "gte_decoder_reuse" else original_helper(name))
    if mutation == "original_load_failure":
        def fail(*args, **kwargs):
            torch.rand(11)
            raise RuntimeError("original model failed")
        monkeypatch.setattr(subject, "_original_primary_model", fail)
    prior_threads = torch.get_num_threads()
    torch.set_num_threads(2)
    before_rng = torch.get_rng_state().clone()
    try:
        with pytest.raises((ValueError, RuntimeError)):
            export(inputs)
        assert torch.get_num_threads() == 2 and torch.equal(before_rng, torch.get_rng_state())
    finally:
        torch.set_num_threads(prior_threads)


def test_original_donor_changes_and_oversized_logit_requests_fail_before_torch(inputs, monkeypatch):
    import builtins
    original_import = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.split(".")[0] == "torch":
            pytest.fail("invalid replay admission imported Torch")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    changed = dict(inputs, primary=deepcopy(inputs["primary"]))
    changed["primary"]["model_state"]["output.bias"][0] += 1.
    with pytest.raises(ValueError):
        export(changed)
    monkeypatch.setattr(subject, "MAX_LOGIT_ELEMENTS", 0)
    with pytest.raises(ValueError, match="before model loading"):
        export(inputs)


@pytest.mark.parametrize("field", sorted(subject.FLAGS))
def test_flags_cannot_claim_kd_training_or_native_input_execution(inputs, replay, field):
    changed = deepcopy(replay)
    changed[field] = not changed[field]
    with pytest.raises(ValueError):
        inspect(changed, inputs)


@pytest.mark.parametrize("mutation", ("wrong_row_id", "source_hash", "input_hash", "prefix", "target",
    "kd_mask", "reference_mask", "logit_digest", "logit_steps", "logit_vocabulary", "nonfinite",
    "rounded_float64", "logit_max_error", "diagnostic_kl", "exact_condition", "head_count",
    "codec", "teacher_pin", "extra_field", "optimizer_steps_bool"))
def test_exported_distribution_and_prefix_bindings_are_checked(inputs, replay, mutation):
    changed = deepcopy(replay)
    head = changed["heads"]["primary384"]
    row = head["rows"][0]
    if mutation == "wrong_row_id": row["id"] = "changed"
    elif mutation == "source_hash": row["source_sha256"] = "0" * 64
    elif mutation == "input_hash": row["input_sha256"] = "0" * 64
    elif mutation == "prefix": row["prefix_ids"][0] = 3
    elif mutation == "target": row["next_token_ids"][0] = 3
    elif mutation == "kd_mask": row["kd_token_mask"][0] = True
    elif mutation == "reference_mask": row["reference_token_mask"][0] = False
    elif mutation == "logit_digest": row["teacher_logits"][0][0] += 1.
    elif mutation == "logit_steps": row["teacher_logits"].pop()
    elif mutation == "logit_vocabulary": row["teacher_logits"][0].pop()
    elif mutation == "nonfinite": row["teacher_logits"][0][0] = float("nan")
    elif mutation == "rounded_float64":
        row["teacher_logits"][0][0] = .1
        row["teacher_logits_sha256"] = subject.digest(row["teacher_logits"])
    elif mutation == "logit_max_error": row["max_logit_error"] = .1
    elif mutation == "diagnostic_kl": row["diagnostic_kl_t2"] = .1
    elif mutation == "exact_condition": row["exact_condition"] = False
    elif mutation == "head_count": head["selected_row_count"] = 0
    elif mutation == "codec": head["codec_sha256"] = "0" * 64
    elif mutation == "teacher_pin": head["teacher_checkpoint_sha256"] = "0" * 64
    elif mutation == "extra_field": changed["unknown"] = True
    else: changed["optimizer_steps"] = False
    with pytest.raises(ValueError):
        inspect(changed, inputs)


def test_replay_inspector_enforces_the_serialized_output_bound(inputs, replay, monkeypatch):
    monkeypatch.setattr(subject, "MAX_OUTPUT_BYTES", 1)
    with pytest.raises(ValueError, match="16 MiB"):
        inspect(replay, inputs)


def test_exported_rows_and_masks_are_independent_of_caller_batch(inputs):
    receipt = export(inputs)
    before = deepcopy(inputs["batch"])
    row = receipt["heads"]["primary384"]["rows"][0]
    row["prefix_ids"][0] = 99
    row["teacher_logits"][0][0] = 99.
    assert inputs["batch"] == before
