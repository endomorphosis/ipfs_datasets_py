"""Authenticated aligned handoff using synthetic donors and vector pairs.

The fixture prepares the real dual-donor bundle and existing ridge pipeline.
These are implementation checks, never multilingual encoder evidence.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest


REPOSITORY = Path(__file__).resolve().parents[5]
PATH = REPOSITORY / "scripts/ops/autoencoder/prepare_gte_aligned_decoder.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


subject = _load("gte_aligned_decoder_cli_test_subject", PATH)
old_cli = _load("gte_aligned_decoder_previous_cli", PATH.with_name("prepare_gte_alignment.py"))
reuse_fixture = _load("gte_aligned_decoder_donor_fixture",
    Path(__file__).with_name("test_gte_decoder_reuse.py"))
torch = pytest.importorskip("torch")


def _raw(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False) + "\n").encode()


def _write(path, value):
    raw = _raw(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope="module", autouse=True)
def bounded_threads():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


@pytest.fixture(scope="module")
def donor_initialization(tmp_path_factory):
    donors = reuse_fixture.donors.__wrapped__(tmp_path_factory)
    _, bundle = reuse_fixture.create(donors)
    return {"donors": donors, "bundle": bundle}


@pytest.fixture
def pipeline(tmp_path, monkeypatch, donor_initialization):
    """Build real admission outputs; disable only process-wide OS budgets."""
    original_helper = old_cli._helper
    reader = original_helper("gte_worker_contract")
    corpus = original_helper("gte_multilingual_corpus")
    calls = []

    def configure(resources):
        calls.append(deepcopy(resources))
        return {"schema": "synthetic-test-budget-receipt/v1",
            "scope": "unit_test_no_process_limits_applied", **deepcopy(resources)}

    monkeypatch.setattr(reader, "configure_cpu_process", configure)
    monkeypatch.setattr(old_cli, "_helper", lambda name:
        reader if name == "gte_worker_contract" else original_helper(name))
    aligned_original = subject._helper
    monkeypatch.setattr(subject, "_helper", lambda name:
        reader if name == "gte_worker_contract" else aligned_original(name))
    donor = donor_initialization["donors"]["primary"]
    bundle = deepcopy(donor_initialization["bundle"])
    source_root = tmp_path / "donor-source"
    inspector = reuse_fixture.primary_fixture.subject._TEACHER
    paths = {*inspector._NATIVE_MODULE_PATHS.values(), *inspector._NUMERICAL_PATHS.values(),
        "ipfs_datasets_py/logic/formalization/autoencoder/source_training_v2.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/domain_384_autoencoder.py"}
    for relative in paths:
        destination = source_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY / relative, destination)
    rows = []
    for index, split in enumerate(("train", "train", "validation")):
        vector = [0.] * 384
        vector[index] = 1.
        rows.append({"id": "synthetic-row" + str(index), "domain_id": "legal_ir",
            "document_id": "synthetic-document" + str(index), "group_id": "synthetic-group" + str(index),
            "split": split, "source_text": "authored diagnostic source " + str(index),
            "embedding": vector, "reference_target": {"reference": index},
            "target_origin": "authored", "source_language": "en", "evaluation_role": "development"})
    source_id = original_helper("gte_affine_bridge").SOURCE_REPRESENTATION_ID
    audit = corpus._AUDIT.audit_transfer_rows(rows, dimension=384, vector_space_id=source_id)
    tasks = corpus.prepare_embedding_tasks(rows, audit)
    values = {"rows_384": rows, "corpus_audit": audit, "tasks": tasks, "receipts_768": [],
        "teacher_checkpoint": donor["checkpoint"], "initialization": bundle, "donor_pins": bundle["donor_pins"]}
    config = {"schema": old_cli.CONFIG_SCHEMA, "workspace_root": str(tmp_path), "domain_id": "legal_ir",
        "max_rows": 4096, "mode": "prepare", "seed": 113, "regularization_candidates": [.01],
        "max_train_pairs": 4096, "max_validation_pairs": 4096, "teacher_repository_root": source_root.name}
    for name, value in values.items():
        path = tmp_path / (name + ".json")
        if name == "teacher_checkpoint":
            path.write_bytes(donor["path"].read_bytes())
            pin = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            pin = _write(path, value)
        config[name] = {"path": path.name, "sha256": pin}
    old_config = tmp_path / "alignment-config.json"
    _write(old_config, config)
    return SimpleNamespace(root=tmp_path, source_root=source_root, config=config, values=values,
        old_config=old_config, old_output=tmp_path / "alignment", output=tmp_path / "aligned",
        reader=reader, budget_calls=calls, corpus=corpus, bundle=bundle,
        original_helper=aligned_original)


def _prepare(pipeline, *, fitted=False, ready=False, unavailable_fit=False):
    if fitted or ready:
        receipts = []
        for index, task in enumerate(pipeline.values["tasks"]["tasks"]):
            vector = [0.] * 768
            vector[index] = 1.
            receipts.append({"schema": pipeline.corpus.RECEIPT_SCHEMA, "id": task["id"],
                "source_sha256": task["source_sha256"], "profile_id": pipeline.corpus.PROFILE_ID,
                "dimension": 768, "embedding": vector, "token_count_including_special_tokens": 3,
                "token_input_sha256": "a" * 64, "truncated": False, "normalized": True,
                "asset_manifest_sha256": "b" * 64})
        pipeline.config["receipts_768"]["sha256"] = _write(pipeline.root / "receipts_768.json", receipts)
    pipeline.config["mode"] = "fit" if fitted or unavailable_fit else "prepare"
    pin = _write(pipeline.old_config, pipeline.config)
    old_cli.run_alignment(pipeline.old_config, expected_config_sha256=pin, output_directory=pipeline.old_output)
    pipeline.budget_calls.clear()
    config = {"schema": subject.CONFIG_SCHEMA, "workspace_root": str(pipeline.root), "mode": "prepare",
        "alignment_manifest": {"path": "alignment/manifest.json",
            "sha256": hashlib.sha256((pipeline.old_output / "manifest.json").read_bytes()).hexdigest()},
        "initialization": pipeline.config["initialization"], "donor_pins": pipeline.config["donor_pins"]}
    pipeline.path = pipeline.root / "aligned-config.json"
    pipeline.config = config
    pipeline.pin = _write(pipeline.path, config)
    return pipeline


def _run(pipeline, **overrides):
    arguments = {"expected_config_sha256": pipeline.pin, "output_directory": pipeline.output}
    arguments.update(overrides)
    return subject.prepare_aligned_decoder(pipeline.path, **arguments)


def _repin_config(pipeline):
    pipeline.pin = _write(pipeline.path, pipeline.config)


def _repin_manifest(pipeline, change):
    path = pipeline.old_output / "manifest.json"
    value = json.loads(path.read_bytes())
    change(value)
    pipeline.config["alignment_manifest"]["sha256"] = _write(path, value)
    _repin_config(pipeline)


def _guard_imports(monkeypatch):
    import builtins
    real_import = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in ("torch", "numpy", "transformers", "sentence_transformers"):
            pytest.fail("unavailable handoff must stay dependency-free")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)


def test_cli_import_does_not_load_model_libraries():
    code = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('isolated_aligned_cli',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('torch','numpy','transformers','sentence_transformers'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH)], check=True)


@pytest.mark.parametrize("ready", [False, True])
def test_prepare_manifest_never_constructs_aligned_decoder(pipeline, monkeypatch, ready):
    _prepare(pipeline, ready=ready)
    retained = (pipeline.root / "initialization.json").read_bytes()
    _guard_imports(monkeypatch)
    result = _run(pipeline)
    assert result["status"] == "unavailable"
    assert result["aligned_checkpoint_count"] == 0
    assert result["numerical_model_loaded"] is False
    assert result["synthetic_gradient_probe_executed"] is False
    assert result["primary_input_boundary_fitted"] is False
    assert result["optimizer_steps"] == 0
    assert result["training_executed"] is False
    assert result["distillation_executed"] is False
    assert result["encoder_inference_executed"] is False
    assert pipeline.budget_calls == []
    assert (pipeline.root / "initialization.json").read_bytes() == retained
    assert not (pipeline.output / "aligned-student.json").exists()
    assert not (pipeline.output / "gradient-probe.json").exists()
    manifest = json.loads((pipeline.output / "manifest.json").read_bytes())
    assert manifest["completed"] is True and manifest["status"] == "unavailable"
    for entry in manifest["outputs"]:
        raw = (pipeline.output / entry["path"]).read_bytes()
        assert len(raw) == entry["bytes"]
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]


@pytest.mark.parametrize("change", ["extra", "mode", "root_relative", "missing_root",
    "ref_extra", "ref_absolute", "ref_traversal", "bad_pin"])
def test_closed_configuration_and_namespace_are_required(pipeline, change):
    _prepare(pipeline)
    config = pipeline.config
    if change == "extra": config["allow_missing_fit"] = True
    if change == "mode": config["mode"] = "fit"
    if change == "root_relative": config["workspace_root"] = "."
    if change == "missing_root": config["workspace_root"] = str(pipeline.root / "absent")
    if change == "ref_extra": config["alignment_manifest"]["trusted"] = True
    if change == "ref_absolute": config["alignment_manifest"]["path"] = str(pipeline.old_output / "manifest.json")
    if change == "ref_traversal": config["alignment_manifest"]["path"] = "../alignment/manifest.json"
    if change == "bad_pin": config["initialization"]["sha256"] = "0" * 64
    _repin_config(pipeline)
    with pytest.raises(ValueError):
        _run(pipeline)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


def test_external_configuration_pin_is_required(pipeline):
    _prepare(pipeline)
    with pytest.raises(ValueError, match="SHA256"):
        _run(pipeline, expected_config_sha256="0" * 64)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


@pytest.mark.parametrize("change", ["extra", "schema", "unfinished", "mode",
    "status", "fit_flag", "encoder_flag", "distillation_flag", "fidelity_flag", "proof_flag"])
def test_manifest_cannot_promote_unfitted_or_qualified_claims(pipeline, change):
    _prepare(pipeline)
    def edit(manifest):
        if change == "extra": manifest["trusted_fit"] = True
        if change == "schema": manifest["schema"] = "unknown/v1"
        if change == "unfinished": manifest["completed"] = False
        if change == "mode": manifest["mode"] = "fit"
        if change == "status": manifest["status"] = "fitted_unqualified"
        if change == "fit_flag": manifest["analytic_alignment_fit_executed"] = True
        if change == "encoder_flag": manifest["encoder_inference_executed"] = True
        if change == "distillation_flag": manifest["distillation_executed"] = True
        if change == "fidelity_flag": manifest["source_fidelity_qualified"] = True
        if change == "proof_flag": manifest["proof_authority"] = True
    _repin_manifest(pipeline, edit)
    with pytest.raises(ValueError):
        _run(pipeline)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


@pytest.mark.parametrize("change", ["duplicate_output", "output_traversal", "output_absolute",
    "output_pin", "output_bytes", "input_pin", "implementation_pin"])
def test_all_manifest_refs_are_authenticated_before_publication(pipeline, change):
    _prepare(pipeline)
    def edit(manifest):
        if change == "duplicate_output": manifest["outputs"].append(deepcopy(manifest["outputs"][0]))
        if change == "output_traversal": manifest["outputs"][0]["path"] = "../initialization.json"
        if change == "output_absolute": manifest["outputs"][0]["path"] = str(pipeline.root / "initialization.json")
        if change == "output_pin": manifest["outputs"][0]["sha256"] = "0" * 64
        if change == "output_bytes": manifest["outputs"][0]["bytes"] += 1
        if change == "input_pin": manifest["inputs"][0]["sha256"] = "0" * 64
        if change == "implementation_pin": manifest["implementation_files"][0]["sha256"] = "0" * 64
    _repin_manifest(pipeline, edit)
    with pytest.raises(ValueError):
        _run(pipeline)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


def _edit_output(pipeline, filename, edit):
    path = pipeline.old_output / filename
    payload = json.loads(path.read_bytes())
    edit(payload)
    pin = _write(path, payload)
    def update(manifest):
        ref = next(item for item in manifest["outputs"] if item["path"] == filename)
        ref.update(sha256=pin, bytes=path.stat().st_size)
    _repin_manifest(pipeline, update)


@pytest.mark.parametrize("filename,field,value", [
    ("summary.json", "status", "fitted_unqualified"),
    ("summary.json", "analytic_alignment_fit_executed", True),
    ("summary.json", "training_executed", True),
    ("summary.json", "pair_count", 2),
    ("initialization-binding.json", "representation_id", "counterfeit_initialized_identity"),
    ("initialization-binding.json", "original_initialization_unchanged", False),
    ("teacher-binding.json", "checkpoint_sha256", "0" * 64),
    ("teacher-binding.json", "weights_sha256", "0" * 64),
])
def test_repinning_cannot_forge_inner_alignment_bindings(pipeline, filename, field, value):
    _prepare(pipeline)
    _edit_output(pipeline, filename, lambda payload: payload.update({field: value}))
    with pytest.raises(ValueError):
        _run(pipeline)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


def test_existing_output_is_preserved(pipeline):
    _prepare(pipeline)
    pipeline.output.mkdir()
    sentinel = pipeline.output / "retained.txt"
    sentinel.write_bytes(b"retained")
    with pytest.raises(ValueError, match="fresh"):
        _run(pipeline)
    assert sentinel.read_bytes() == b"retained" and pipeline.budget_calls == []


@pytest.mark.parametrize("namespace", ["alignment", "source"])
def test_output_cannot_write_inside_input_or_source_namespace(pipeline, namespace):
    _prepare(pipeline)
    base = pipeline.old_output if namespace == "alignment" else pipeline.source_root
    with pytest.raises(ValueError):
        _run(pipeline, output_directory=base / "aligned-output")
    assert not (base / "aligned-output").exists() and pipeline.budget_calls == []


def test_output_parent_symlink_is_rejected(pipeline):
    _prepare(pipeline)
    link = pipeline.root / "alias"
    link.symlink_to(pipeline.old_output, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        _run(pipeline, output_directory=link / "aligned-output")
    assert pipeline.budget_calls == []


def test_no_fit_manifest_cannot_smuggle_a_fitted_output(pipeline):
    _prepare(pipeline)
    path = pipeline.old_output / "fitted-bridge.json"
    pin = _write(path, {"schema": "forged-fitted-bridge/v1"})
    _repin_manifest(pipeline, lambda manifest: manifest["outputs"].append(
        {"path": path.name, "bytes": path.stat().st_size, "sha256": pin}))
    with pytest.raises(ValueError):
        _run(pipeline)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


def test_fitted_manifest_publishes_authenticated_private_student_and_probe(pipeline):
    _prepare(pipeline, fitted=True)
    retained = {ref["path"]: (pipeline.root / ref["path"]).read_bytes()
        for name, ref in pipeline.config.items() if name in ("initialization", "donor_pins")}
    result = _run(pipeline)
    assert result["status"] == "constructed_unqualified"
    assert result["aligned_checkpoint_count"] == 1
    assert result["numerical_model_loaded"] is True
    assert result["synthetic_gradient_probe_executed"] is True
    assert result["primary_input_boundary_fitted"] is True
    assert result["exact_saved_reload_passed"] is True
    assert result["optimizer_steps"] == 0 and result["training_executed"] is False
    assert result["distillation_executed"] is False and result["encoder_inference_executed"] is False
    assert len(pipeline.budget_calls) == 1
    assert pipeline.budget_calls[0] == {"device": "cpu", "threads": 1, "max_rows": 1,
        "memory_limit_mib": 16384, "cpu_time_limit_seconds": 120}
    manifest = json.loads((pipeline.output / "manifest.json").read_bytes())
    assert manifest["completed"] is True and manifest["status"] == "constructed_unqualified"
    outputs = {}
    for entry in manifest["outputs"]:
        raw = (pipeline.output / entry["path"]).read_bytes()
        assert len(raw) == entry["bytes"] and hashlib.sha256(raw).hexdigest() == entry["sha256"]
        outputs[entry["path"]] = json.loads(raw)
    checkpoints = [item for item in outputs.values() if item.get("schema") == "gte-aligned-dual-decoder/v1"]
    assert len(checkpoints) == 1
    checkpoint = checkpoints[0]
    assert checkpoint["initialization"] == pipeline.bundle
    assert checkpoint["bridge"] == json.loads((pipeline.old_output / "fitted-bridge.json").read_bytes())
    assert checkpoint["donor_pins"] == pipeline.bundle["donor_pins"]
    assert checkpoint["optimizer"] == {"mode": "fresh", "state": None, "resume": False}
    inventory = checkpoint["tensor_inventory"]
    assert len(inventory) == 30
    assert sum(entry["origin"].startswith("copied_") for entry in inventory) == 26
    assert sum(entry["origin"] == "analytic_training_pair_alignment" for entry in inventory) == 2
    assert sum(entry["origin"] == "unchanged_unfitted_auxiliary_connector" for entry in inventory) == 2
    assert pipeline.bundle["primary"]["codec"] != pipeline.bundle["legacy8"]["codec"]
    probe = outputs["gradient-probe.json"]
    assert probe["status"] == "passed"
    assert probe["probe_input_origin"] == "fixed_synthetic_unit_vector_not_encoder_output"
    assert probe["auxiliary_loss_reaches_shared_primary_boundary"] is True
    assert all(group["finite"] and group["nonzero"] for group in probe["gradient_groups"].values())
    reload = probe["exact_saved_reload"]
    assert all(reload[name] is True for name in ("saved_bytes_authenticated_before_load",
        "all_state_tensors_equal", "all_output_tensors_equal", "tensor_storage_independent", "freeze_mode_equal"))
    assert set(reload["result_sha256"]) == {"primary_logits", "auxiliary_logits",
        "shared_condition", "auxiliary_latent"}
    assert all(len(pin) == 64 for pin in reload["result_sha256"].values())
    for relative, raw in retained.items():
        assert (pipeline.root / relative).read_bytes() == raw


@pytest.mark.parametrize("filename,field,value", [
    ("fit-report.json", "initialization_sha256", "0" * 64),
    ("fit-report.json", "bridge_checkpoint_sha256", "0" * 64),
    ("fit-report.json", "primary_input_boundary_fitted", False),
    ("fit-report.json", "auxiliary_connector_fitted", True),
    ("fit-report.json", "inherited_decoder_weights_unchanged", False),
    ("fit-report.json", "teacher_qualified", True),
])
def test_repinning_fit_report_cannot_bypass_real_handoff_contract(pipeline, filename, field, value):
    _prepare(pipeline, fitted=True)
    _edit_output(pipeline, filename, lambda payload: payload.update({field: value}))
    with pytest.raises(ValueError):
        _run(pipeline)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


def test_explicit_fit_parent_without_pairs_still_loads_no_model(pipeline, monkeypatch):
    _prepare(pipeline, unavailable_fit=True)
    _guard_imports(monkeypatch)
    result = _run(pipeline)
    assert result["status"] == "unavailable" and result["aligned_checkpoint_count"] == 0
    assert result["synthetic_gradient_probe_executed"] is False
    assert pipeline.budget_calls == []


def test_changed_parent_source_is_rejected_before_model_budgets(pipeline):
    _prepare(pipeline, fitted=True)
    source = next(pipeline.source_root.rglob("source_training_v2.py"))
    source.write_bytes(b"changed synthetic source closure\n")
    with pytest.raises(ValueError, match="SHA256"):
        _run(pipeline)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


def test_saved_checkpoint_corruption_prevents_completion_and_reload(pipeline, monkeypatch):
    _prepare(pipeline, fitted=True)
    original = subject._write
    def corrupt(output, name, value):
        receipt = original(output, name, value)
        if name == "aligned-student.json":
            with (output / name).open("ab") as stream:
                stream.write(b" ")
        return receipt
    monkeypatch.setattr(subject, "_write", corrupt)
    with pytest.raises(ValueError, match="SHA256"):
        _run(pipeline)
    assert (pipeline.output / "aligned-student.json").exists()
    assert not (pipeline.output / "gradient-probe.json").exists()
    assert not (pipeline.output / "manifest.json").exists()


@pytest.mark.parametrize("late", [False, True])
def test_input_drift_never_gets_a_completion_manifest(pipeline, monkeypatch, late):
    _prepare(pipeline)
    original = subject._recheck
    calls = []
    def drift(reader, receipts):
        calls.append(1)
        if len(calls) == (2 if late else 1):
            (pipeline.root / "initialization.json").write_bytes(b"{}\n")
        return original(reader, receipts)
    monkeypatch.setattr(subject, "_recheck", drift)
    with pytest.raises(ValueError, match="SHA256|changed"):
        _run(pipeline)
    assert pipeline.output.exists() is late
    assert not (pipeline.output / "manifest.json").exists()
