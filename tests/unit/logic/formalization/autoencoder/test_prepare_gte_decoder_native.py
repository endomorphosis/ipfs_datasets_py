"""Cache-first native admission from a genuine synthetic transfer parent.

The fixture's model and receipts are synthetic. Parent publication, cached joins
and ready native gradients execute their real implementations; only process
resource limits are replaced. Previously published parent files stay immutable.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


REPOSITORY = Path(__file__).resolve().parents[5]
PATH = REPOSITORY / "scripts/ops/autoencoder/prepare_gte_decoder_native.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


subject = _load("gte_decoder_native_cli_test_subject", PATH)
torch = pytest.importorskip("torch")


def _raw(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False) + "\n").encode()


def _write(path, value):
    raw = _raw(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope="module", autouse=True)
def bounded_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def parent(tmp_path_factory):
    builder = _load("gte_native_cli_fixture",
        Path(__file__).with_name("test_gte_decoder_native_batch.py"))
    synthetic = builder.decoder_native_fixture(tmp_path_factory)
    transfer = _load("gte_native_cli_parent_fixture",
        Path(__file__).with_name("test_prepare_gte_decoder_transfer.py"))
    transfer_builder = _load("gte_native_cli_transfer_builder",
        Path(__file__).with_name("test_gte_decoder_transfer_batch.py"))
    root = tmp_path_factory.mktemp("native_transfer_parent")
    with pytest.MonkeyPatch.context() as patch:
        pipeline = transfer.pipeline.__wrapped__(root, patch, (transfer_builder, synthetic))
        result = transfer._run(pipeline)
    assert result["status"] == "behavior_preserved_unqualified"
    manifest = json.loads((pipeline.output / "manifest.json").read_bytes())
    bound = [Path(ref["path"]) for ref in [*manifest["inputs"], *manifest["implementation_files"]]]
    bound += [pipeline.output / ref["path"] for ref in manifest["outputs"]]
    bound.append(pipeline.output / "manifest.json")
    original = {path: path.read_bytes() for path in bound}
    return SimpleNamespace(builder=builder, synthetic=synthetic, pipeline=pipeline,
        manifest=manifest, original=original)


@pytest.fixture
def pipeline(tmp_path, monkeypatch, parent):
    incoming = tmp_path / "inputs"
    incoming.mkdir()
    paths = {"parent_manifest": parent.pipeline.output / "manifest.json",
        **{name: parent.pipeline.paths[name] for name in (
            "initialization", "donor_pins", "primary_training_archive", "legacy8_inputs")},
        "batch": parent.pipeline.output / "batch.json", "replay": parent.pipeline.output / "replay.json",
        "primary_validation_archive": incoming / "validation.json", "receipts_768": incoming / "cache.json"}
    _write(paths["primary_validation_archive"], parent.synthetic.primary_validation_archive)
    _write(paths["receipts_768"], [])
    # The real repository and pytest's /tmp inputs have this common ancestor.
    # Every reference remains relative, byte-pinned and individually admitted.
    workspace = Path("/")
    config = {"schema": subject.SCHEMA, "workspace_root": str(workspace), "mode": "prepare",
        "expected_asset_manifest_sha256": parent.synthetic.asset_manifest_sha256}
    for name, path in paths.items():
        config[name] = {"path": str(path.relative_to(workspace)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    path = incoming / "config.json"
    pin = _write(path, config)
    reader = subject._helper("gte_worker_contract")
    original_helper = subject._helper
    budget_calls = []
    def configure(resources):
        resources = reader._resources(resources)
        budget_calls.append(deepcopy(resources))
        return {"schema": "synthetic-test-resource-receipt/v1",
            "scope": "unit_test_no_process_limits_applied", **resources}
    monkeypatch.setattr(reader, "configure_cpu_process", configure)
    monkeypatch.setattr(subject, "_helper", lambda name:
        reader if name == "gte_worker_contract" else original_helper(name))
    result = SimpleNamespace(root=tmp_path, incoming=incoming, workspace=workspace,
        path=path, pin=pin, config=config, paths=paths, output=tmp_path / "output",
        reader=reader, original_helper=original_helper, budget_calls=budget_calls, parent=parent)
    yield result
    assert all(path.read_bytes() == raw for path, raw in parent.original.items())


def _run(pipeline, **changes):
    args = {"expected_config_sha256": pipeline.pin, "output_directory": pipeline.output}
    args.update(changes)
    return subject.prepare_decoder_native(pipeline.path, **args)


def _repin(pipeline):
    pipeline.pin = _write(pipeline.path, pipeline.config)


def _replace(pipeline, name, value):
    pipeline.config[name]["sha256"] = _write(pipeline.paths[name], value)
    _repin(pipeline)


def _cache(pipeline, kind):
    fixture = pipeline.parent.synthetic
    if kind == "selected": value = fixture.receipts_768
    elif kind == "partial": value = fixture.receipts_768[:1]
    elif kind == "all":
        value = [pipeline.parent.builder.receipt(task, index)
            for index, task in enumerate(fixture.empty_plan["task_manifest"]["tasks"])]
    else: value = []
    _replace(pipeline, "receipts_768", value)


def _forbid_numerical_imports(monkeypatch):
    import builtins
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in ("torch", "numpy", "transformers", "sentence_transformers"):
            pytest.fail("cache preparation must not load numerical or encoder libraries")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)


def _assert_publication(pipeline, result, *, probe=False):
    manifest_path = pipeline.output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest["completed"] is True and manifest["status"] == result["status"]
    assert manifest["saved_native_batch_authenticated_and_reinspected"] is True
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == result["manifest_sha256"]
    names = {"native-batch.json", "tasks.json", "missing-tasks.json", "receipts.json",
        "inspection.json", "summary.json"}
    if probe: names |= {"resources.json", "probe.json"}
    assert {ref["path"] for ref in manifest["outputs"]} == names
    for ref in [*manifest["inputs"], *manifest["parent_closure"],
                *manifest["implementation_files"], *manifest["outputs"]]:
        path = Path(ref["path"])
        raw = (path if path.is_absolute() else pipeline.output / path).read_bytes()
        assert len(raw) == ref["bytes"] and hashlib.sha256(raw).hexdigest() == ref["sha256"]
    assert result["optimizer_steps"] == 0
    assert result["original_decoder_initialization_unchanged"] is True
    assert result["existing_assets_and_embeddings_reused"] is True
    assert result["old_embeddings_regenerated"] is False
    for flag in subject.FALSE_FLAGS: assert result[flag] is False


def test_cli_import_has_no_model_dependencies():
    code = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('isolated_native_cli',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('torch','numpy','transformers','sentence_transformers','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH)], check=True)


@pytest.mark.parametrize("mode", ["prepare", "probe"])
def test_empty_cache_is_explicitly_unavailable_without_torch_or_a_model(pipeline, monkeypatch, mode):
    pipeline.config["mode"] = mode
    _repin(pipeline)
    _forbid_numerical_imports(monkeypatch)
    result = _run(pipeline)
    assert result["status"] == "unavailable"
    assert result["selected_row_count"] == result["missing_row_count"] == 18
    assert result["ready_row_count"] == result["cached_receipt_count"] == 0
    assert result["task_count"] == result["missing_task_count"] == 242
    assert result["native_gradient_probe_executed"] is False
    assert result["native768_inputs_used"] is False and pipeline.budget_calls == []
    _assert_publication(pipeline, result)
    tasks = json.loads((pipeline.output / "tasks.json").read_bytes())
    assert all(set(task) == {"id", "source_text", "source_sha256", "metadata"} for task in tasks["tasks"])
    assert not (pipeline.output / "probe.json").exists()


@pytest.mark.parametrize("cache", ["selected", "all"])
def test_ready_prepare_only_reuses_receipts_without_numerical_execution(pipeline, monkeypatch, cache):
    _cache(pipeline, cache)
    before = pipeline.paths["receipts_768"].read_bytes()
    _forbid_numerical_imports(monkeypatch)
    result = _run(pipeline)
    assert result["status"] == "ready" and result["ready_row_count"] == 18
    assert result["cached_receipt_count"] == (18 if cache == "selected" else 242)
    assert result["missing_task_count"] == (224 if cache == "selected" else 0)
    assert result["full_task_cache_status"] == ("partial" if cache == "selected" else "ready")
    assert result["native_gradient_probe_executed"] is False and pipeline.budget_calls == []
    assert pipeline.paths["receipts_768"].read_bytes() == before
    _assert_publication(pipeline, result)


def test_partial_cache_never_probes_or_changes_the_selected_cohort(pipeline, monkeypatch):
    pipeline.config["mode"] = "probe"
    _cache(pipeline, "partial")
    _forbid_numerical_imports(monkeypatch)
    result = _run(pipeline)
    assert result["status"] == "partial"
    assert result["selected_row_count"] == 18 and result["ready_row_count"] == 1
    assert result["missing_row_count"] == 17 and result["missing_task_count"] == 241
    assert result["native_gradient_probe_executed"] is False and pipeline.budget_calls == []
    _assert_publication(pipeline, result)


def test_ready_probe_reaches_only_four_interfaces_and_preserves_all_learned_heads(pipeline):
    pipeline.config["mode"] = "probe"
    _cache(pipeline, "selected")
    rng = torch.get_rng_state().clone()
    result = _run(pipeline)
    assert result["status"] == "ready"
    assert result["native_gradient_probe_executed"] is True and result["native768_inputs_used"] is True
    assert torch.equal(rng, torch.get_rng_state())
    assert pipeline.budget_calls == [{"device": "cpu", "threads": 1, "max_rows": 128,
        "memory_limit_mib": 16384, "cpu_time_limit_seconds": 120}]
    _assert_publication(pipeline, result, probe=True)
    probe = json.loads((pipeline.output / "probe.json").read_bytes())
    assert probe["status"] == "reference_objective_probed_unqualified"
    assert probe["objective"] == "reference_cross_entropy" and probe["logits_combined"] is False
    assert probe["heads"]["primary384"]["row_count"] == 16
    assert probe["heads"]["legacy8"]["row_count"] == 2
    assert probe["heads"]["primary384"]["codec_sha256"] != probe["heads"]["legacy8"]["codec_sha256"]
    assert probe["inherited_tensor_count"] == 26 and probe["inherited_gradients_absent"] is True
    assert probe["all_26_inherited_tensors_unchanged"] is True and probe["whole_model_state_unchanged"] is True
    assert probe["model_state_sha256_before"] == probe["model_state_sha256_after"]
    assert set(probe["interface_gradients"]) == {"primary.input_adapter.weight", "primary.input_adapter.bias",
        "auxiliary_connector.weight", "auxiliary_connector.bias"}
    assert all(item["finite"] and item["nonzero"] for item in probe["interface_gradients"].values())
    assert probe["optimizer_steps"] == 0 and probe["distillation_executed"] is False


def test_repinned_cross_split_group_conflict_blocks_rows_without_replacement(pipeline, monkeypatch):
    archive = deepcopy(pipeline.parent.synthetic.primary_validation_archive)
    archive["rows"][0]["group_id"] = pipeline.parent.synthetic.primary_archive["rows"][0]["group_id"]
    _replace(pipeline, "primary_validation_archive", archive)
    _forbid_numerical_imports(monkeypatch)
    result = _run(pipeline)
    assert result["selected_row_count"] == 18 and result["quarantined_row_count"] == 1
    plan = json.loads((pipeline.output / "native-batch.json").read_bytes())
    assert plan["audit"]["quarantined_row_count"] == 2
    assert plan["heads"]["primary384"]["selected_row_count"] == 16
    assert plan["heads"]["primary384"]["quarantined_rows"][0]["id"] == "training:000"
    assert result["native_gradient_probe_executed"] is False and pipeline.budget_calls == []


@pytest.mark.parametrize("change", ["extra", "mode", "relative_root", "missing_root",
    "asset_bool", "asset_invalid", "ref_extra", "ref_absolute", "ref_traversal"])
def test_closed_config_and_explicit_native_identity_are_required(pipeline, change):
    config = pipeline.config
    if change == "extra": config["allow_missing_receipts"] = True
    if change == "mode": config["mode"] = "train"
    if change == "relative_root": config["workspace_root"] = "."
    if change == "missing_root": config["workspace_root"] = str(pipeline.root / "absent")
    if change == "asset_bool": config["expected_asset_manifest_sha256"] = True
    if change == "asset_invalid": config["expected_asset_manifest_sha256"] = "A" * 64
    if change == "ref_extra": config["receipts_768"]["trusted"] = True
    if change == "ref_absolute": config["receipts_768"]["path"] = str(pipeline.paths["receipts_768"])
    if change == "ref_traversal": config["receipts_768"]["path"] = "../cache.json"
    _repin(pipeline)
    with pytest.raises(ValueError): _run(pipeline)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


@pytest.mark.parametrize("name", subject.REFERENCES)
def test_all_original_and_new_inputs_require_file_pins(pipeline, name):
    pipeline.config[name]["sha256"] = "0" * 64
    _repin(pipeline)
    with pytest.raises(ValueError, match="SHA256"): _run(pipeline)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


def test_external_config_pin_is_required(pipeline):
    with pytest.raises(ValueError, match="SHA256"): _run(pipeline, expected_config_sha256="0" * 64)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


@pytest.mark.parametrize("kwargs", [{"threads": True}, {"threads": 2},
    {"memory_limit_mib": 255}, {"cpu_time_limit_seconds": True}])
def test_strict_resource_limits_apply_even_without_a_ready_cache(pipeline, kwargs):
    with pytest.raises(ValueError): _run(pipeline, **kwargs)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


@pytest.mark.parametrize("change", ["qualified", "optimizer_bool", "source_hash", "missing_output", "duplicate_source"])
def test_repinned_parent_manifest_cannot_forge_a_closed_handoff(pipeline, change):
    value = deepcopy(pipeline.parent.manifest)
    if change == "qualified": value["teacher_qualified"] = True
    if change == "optimizer_bool": value["optimizer_steps"] = False
    if change == "source_hash": value["inputs"][0]["sha256"] = "0" * 64
    if change == "missing_output": value["outputs"].pop()
    if change == "duplicate_source": value["inputs"].append(deepcopy(value["inputs"][0]))
    path = pipeline.parent.pipeline.output / (pipeline.root.name + "-manifest-copy.json")
    pin = _write(path, value)
    pipeline.config["parent_manifest"] = {"path": str(path.relative_to(pipeline.workspace)), "sha256": pin}
    _repin(pipeline)
    with pytest.raises(ValueError): _run(pipeline)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


def test_identical_initialization_copy_still_requires_original_parent_membership(pipeline):
    copy = pipeline.incoming / "initialization-copy.json"
    copy.write_bytes(pipeline.paths["initialization"].read_bytes())
    pipeline.config["initialization"]["path"] = str(copy.relative_to(pipeline.workspace))
    _repin(pipeline)
    with pytest.raises(ValueError, match="parent"): _run(pipeline)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


@pytest.mark.parametrize("change", ["profile", "source", "width", "asset", "duplicate"])
def test_native_receipt_content_is_validated_after_its_file_pin(pipeline, change):
    value = deepcopy(pipeline.parent.synthetic.receipts_768)
    if change == "profile": value[0]["profile_id"] = "thenlper/gte-small"
    if change == "source": value[0]["source_sha256"] = "0" * 64
    if change == "width": value[0]["embedding"].pop()
    if change == "asset": value[0]["asset_manifest_sha256"] = "c" * 64
    if change == "duplicate": value.append(deepcopy(value[0]))
    _replace(pipeline, "receipts_768", value)
    with pytest.raises(ValueError): _run(pipeline)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


@pytest.mark.parametrize("namespace", ["inputs", "parent", "primary_source", "legacy_source", "repository"])
def test_output_cannot_enter_a_prior_input_or_source_archive(pipeline, namespace):
    roots = {"inputs": pipeline.incoming, "parent": pipeline.parent.pipeline.output,
        "primary_source": pipeline.parent.pipeline.roots["teacher384_repository_root"],
        "legacy_source": pipeline.parent.pipeline.roots["legacy8_implementation_root"],
        "repository": REPOSITORY}
    output = roots[namespace] / "native-child-never-created"
    with pytest.raises(ValueError, match="namespace"): _run(pipeline, output_directory=output)
    assert not output.exists() and pipeline.budget_calls == []


def test_existing_output_and_symlink_namespaces_are_preserved(pipeline):
    pipeline.output.mkdir()
    sentinel = pipeline.output / "retained.txt"
    sentinel.write_bytes(b"retained")
    with pytest.raises(ValueError, match="fresh"): _run(pipeline)
    assert sentinel.read_bytes() == b"retained"
    alias = pipeline.root / "alias"
    alias.symlink_to(pipeline.output, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"): _run(pipeline, output_directory=alias / "child")
    assert pipeline.budget_calls == []


@pytest.mark.parametrize("filename,change", [("native-batch.json", "count"),
    ("probe.json", "state"), ("probe.json", "qualification")])
def test_correctly_pinned_saved_contracts_are_reinspected_before_completion(pipeline, monkeypatch, filename, change):
    if filename == "probe.json":
        pipeline.config["mode"] = "probe"
        _cache(pipeline, "selected")
    original = subject._write
    def corrupt(directory, name, value):
        if name == filename:
            value = deepcopy(value)
            if change == "count": value["ready_row_count"] += 1
            if change == "state": value["model_state_sha256_after"] = "0" * 64
            if change == "qualification": value["teacher_qualified"] = True
        return original(directory, name, value)
    monkeypatch.setattr(subject, "_write", corrupt)
    with pytest.raises(ValueError): _run(pipeline)
    assert (pipeline.output / filename).exists() and not (pipeline.output / "manifest.json").exists()


def test_output_byte_corruption_prevents_completion(pipeline, monkeypatch):
    original = subject._write
    def corrupt(directory, name, value):
        receipt = original(directory, name, value)
        if name == "tasks.json":
            with (Path(directory) / name).open("ab") as stream: stream.write(b" ")
        return receipt
    monkeypatch.setattr(subject, "_write", corrupt)
    with pytest.raises(ValueError, match="changed"): _run(pipeline)
    assert not (pipeline.output / "manifest.json").exists()


def test_cache_drift_during_publication_leaves_no_completion_manifest(pipeline, monkeypatch):
    original = subject._write
    def drift(directory, name, value):
        receipt = original(directory, name, value)
        if name == "native-batch.json":
            with pipeline.paths["receipts_768"].open("ab") as stream: stream.write(b" ")
        return receipt
    monkeypatch.setattr(subject, "_write", drift)
    with pytest.raises(ValueError, match="changed"): _run(pipeline)
    assert (pipeline.output / "native-batch.json").exists()
    assert not (pipeline.output / "manifest.json").exists()
