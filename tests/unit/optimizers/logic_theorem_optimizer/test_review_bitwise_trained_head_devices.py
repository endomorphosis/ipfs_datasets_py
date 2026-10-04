"""Authored ordinary-archive controls; no tensor/model/encoder execution."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

PACKAGE = Path(__file__).absolute().parents[4]
WORKSPACE = PACKAGE.parent.parent
READER = PACKAGE / "benchmarks/review_bitwise_trained_head_devices.py"
ARTIFACTS = WORKSPACE / "artifacts/codebase_ir_terminal_bench"
FAILED01 = ARTIFACTS / "bitwise-trained-head-device-qualification-20261004-01"
FAILED02 = ARTIFACTS / "bitwise-trained-head-device-qualification-20261004-02"
QUALIFIED = ARTIFACTS / "bitwise-trained-head-device-qualification-20261004-04"
QUALIFIED_SHA = "d178edbced905e3b55d36a067f8f797aa9a95a612f80162e6aaf6c64f9f26f79"

spec = importlib.util.spec_from_file_location("_trained_head_archive_reader_controls", READER)
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _dump(path, value):
    path.chmod(0o600)
    path.write_bytes(_wire(value))
    path.chmod(0o444)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_archive(tmp_path, source=FAILED02):
    target = tmp_path / "archive"
    shutil.copytree(source, target)
    result = json.loads((target / "result.json").read_bytes())
    def relocate(value):
        if type(value) is dict:
            for name, item in value.items():
                if name == "path" and type(item) is str and item.startswith(str(source) + "/"):
                    value[name] = str(target) + item[len(str(source)):]
                else:
                    relocate(item)
        elif type(value) is list:
            for item in value:
                relocate(item)
    relocate(result)
    for path in target.glob("*-raw-paired-timings.json"):
        timings = json.loads(path.read_bytes())
        relocate(timings)
        _dump(path, timings)
        _replace_pin(result, path)
    result["evidence_bytes_except_result"] = sum(pin["bytes"] for pin in result["evidence_files_except_result"])
    _dump(target / "result.json", result)
    return target, result


def _replace_pin(value, path):
    raw = path.read_bytes()
    if type(value) is dict:
        if set(value) == {"path", "bytes", "sha256"} and value["path"] == str(path):
            value.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        else:
            for item in value.values():
                _replace_pin(item, path)
    elif type(value) is list:
        for item in value:
            _replace_pin(item, path)


def _repin(root, result, path):
    _replace_pin(result, path)
    result["evidence_bytes_except_result"] = sum(pin["bytes"] for pin in result["evidence_files_except_result"])
    _dump(root / "result.json", result)


def _audit(root):
    return reader.audit(root, _sha(root / "result.json"))


def _refused(root):
    report = _audit(root)
    assert report["qualified"] is False
    assert report["closed_artifacts_consistent"] is False
    assert report["error"] is not None
    return report


@pytest.mark.parametrize("source", [FAILED01, FAILED02])
def test_real_safely_closed_partial_archive_is_consistent_without_qualification(source):
    report = _audit(source)
    assert report["closed_artifacts_consistent"] is True
    assert report["qualified"] is False
    assert report["producer_refusal"] is not None
    assert report["constructor_count_scope"] == "completed_lane_constructor_returns_only_failed_attempts_not_claimed"
    assert report["current_sources_verified"] is False
    assert report["check_current_sources"] is False
    assert report["current_source_pins"] == []
    assert report["retained_python_executed"] is False
    assert report["tensor_library_imported"] is False


def test_real_full_archive_joins_every_return_projection_logit_and_result_anchor():
    report = reader.audit(QUALIFIED, QUALIFIED_SHA, check_current_sources=True)
    assert report["closed_artifacts_consistent"] is report["qualified"] is True
    assert report["coverage"] == {"public_reports": 240, "paired_timed_reports": 216,
        "formula_projections": 160, "span_four_logit_snapshots": 12, "adam_constructor_calls": 8}
    assert len(report["retained_pins"]) == 697
    assert report["check_current_sources"] is True
    assert len(report["current_source_pins"]) == 24
    native = json.loads((QUALIFIED / "result.json").read_bytes())
    assert report["current_source_pins"] == [pin["current"] for pin in native["source_pins"]]
    result_pins = [pin for pin in report["retained_pins"] if Path(pin["path"]).name == "result.json"]
    assert result_pins == [report["result_pin"]]
    assert result_pins[0]["sha256"] == report["expected_result_sha256"] == QUALIFIED_SHA
    assert report["universal_speedup_claimed"] is False
    assert all(ratio < 1 for family in report["families"].values()
               for ratio in family["median_original_over_bitwise_ratios"].values())


def test_explicit_current_source_verification_refuses_historical_changed_source():
    report = reader.audit(FAILED02, _sha(FAILED02 / "result.json"), check_current_sources=True)
    assert report["closed_artifacts_consistent"] is False
    assert "current" in report["error"]["detail"]


@pytest.mark.parametrize("bad", ["", "1" * 63, "F" * 64, False, "0" * 64])
def test_external_result_anchor_is_required_and_exact(bad):
    report = reader.audit(FAILED01, bad)
    assert report["closed_artifacts_consistent"] is False


def test_duplicate_json_keys_refused_even_with_new_external_digest(tmp_path):
    root, result = _copy_archive(tmp_path, FAILED01)
    path = root / "result.json"
    raw = path.read_bytes()
    path.chmod(0o600)
    path.write_bytes(b'{"qualified":false,' + raw[1:])
    _refused(root)


def test_unmanifested_ordinary_file_refused(tmp_path):
    root, _ = _copy_archive(tmp_path, FAILED01)
    (root / "unaccounted.json").write_bytes(b"{}")
    _refused(root)


@pytest.mark.parametrize("kind", ["hardlink", "symlink", "changed_bytes"])
def test_ordinary_file_custody_refuses_links_and_unpinned_changes(tmp_path, kind):
    root, result = _copy_archive(tmp_path, FAILED01)
    path = Path(result["evidence_files_except_result"][0]["path"])
    if kind == "hardlink":
        os.link(path, root / "duplicate.py")
    elif kind == "symlink":
        path.unlink()
        path.symlink_to(READER)
    else:
        path.chmod(0o600)
        path.write_bytes(path.read_bytes() + b"\n# changed\n")
    _refused(root)


@pytest.mark.parametrize("mutation", ["duplicate_manifest", "bytes_total", "root_release", "gpu_baseline", "authority", "boolean_counter"])
def test_result_metadata_cannot_expand_archive_authority_or_skip_closure(tmp_path, mutation):
    root, result = _copy_archive(tmp_path, FAILED01)
    if mutation == "duplicate_manifest":
        result["evidence_files_except_result"].append(deepcopy(result["evidence_files_except_result"][0]))
    elif mutation == "bytes_total":
        result["evidence_bytes_except_result"] += 1
    elif mutation == "root_release":
        result["root_release_observed"] = False
    elif mutation == "gpu_baseline":
        result["gpu_allocated_before_owned_sessions_bytes"] = 1
    elif mutation == "authority":
        result["fresh_encoder_execution_qualified"] = True
    else:
        result["encoder_calls"] = False
    _dump(root / "result.json", result)
    _refused(root)


def test_fixed_fixture_bytes_cannot_be_changed_by_self_repinning(tmp_path):
    root, result = _copy_archive(tmp_path, FAILED01)
    pin = next(pin for pin in result["fixture_pins"] if pin["role"] == "formula8_checkpoint")
    path = Path(pin["retained_copy"]["path"])
    checkpoint = json.loads(path.read_bytes())
    checkpoint["progress"]["optimizer_steps"] += 1
    _dump(path, checkpoint)
    _repin(root, result, path)
    new = pin["retained_copy"]
    for current in [pin["current"], *result["currentness_after"]]:
        if current["path"] == pin["current"]["path"]:
            current.update(bytes=new["bytes"], sha256=new["sha256"])
    _dump(root / "result.json", result)
    assert "fixed" in _refused(root)["error"]["detail"]


@pytest.mark.parametrize("mutation", ["duplicate_child", "constructor_total", "input_target", "numeric_projection", "canonical_projection", "public_authority", "zero_timing"])
def test_partial_return_joins_detect_authored_corruption(tmp_path, mutation):
    root, result = _copy_archive(tmp_path)
    family = result["families"]["formula8"]
    if mutation == "duplicate_child":
        a, b = result["owned_children"][:2]
        b["lease_id"] = b["admission"]["lease_id"] = a["lease_id"]
    elif mutation == "constructor_total":
        result["optimizer_constructor_calls"] += 1
    elif mutation == "input_target":
        path = Path(family["inputs"]["path"])
        inputs = json.loads(path.read_bytes())
        inputs["rows"][0]["canonical_ir"] = {"target": True}
        _dump(path, inputs)
        _repin(root, result, path)
    else:
        observation = family["lanes"]["bitwise_cpu_opt_out"]["counts"]["1"]
        if mutation == "numeric_projection":
            path = Path(observation["projected_vectors"]["path"])
            vectors = json.loads(path.read_bytes())
            vectors[0][-1] += 0.25
            _dump(path, vectors)
            _repin(root, result, path)
        elif mutation == "canonical_projection":
            path = Path(observation["canonical_projection"]["path"])
            canonical = json.loads(path.read_bytes())
            canonical["rows"][0]["source_sha256"] = "0" * 64
            _dump(path, canonical)
            _repin(root, result, path)
        elif mutation == "public_authority":
            path = Path(observation["result"]["path"])
            report = json.loads(path.read_bytes())
            report["proof_authority"] = True
            _dump(path, report)
            _repin(root, result, path)
        else:
            observation["elapsed_seconds"] = 0.0
    _dump(root / "result.json", result)
    _refused(root)


def test_partial_incomplete_trial_is_pinned_without_promoting_timing_claims(tmp_path):
    root, result = _copy_archive(tmp_path)
    source_pin = result["families"]["formula8"]["lanes"]["original_cpu_reference"]["counts"]["1"]["result"]
    path = root / "formula8-1-pair00-original_cuda-result.json"
    path.write_bytes(Path(source_pin["path"]).read_bytes())
    path.chmod(0o444)
    pin = {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha(path)}
    result["evidence_files_except_result"].append(pin)
    result["evidence_bytes_except_result"] += pin["bytes"]
    _dump(root / "result.json", result)
    report = _audit(root)
    assert report["closed_artifacts_consistent"] is True
    assert report["qualified"] is False
    assert report["unjoined_failed_partial_evidence"][0]["pin"] == pin
    assert report["coverage"]["paired_timed_reports"] == 0


@pytest.mark.parametrize("corruption", ["missing_tail", "changed_tail", "nonfinite", "boolean", "nested_shape"])
def test_complete_numeric_comparison_covers_tail_shape_finiteness_and_types(corruption):
    left = [[float(index) / 1000 for index in range(384)] for _ in range(3)]
    right = deepcopy(left)
    if corruption == "missing_tail":
        right[-1].pop()
    elif corruption == "changed_tail":
        right[-1][-1] += 0.1
    elif corruption == "nonfinite":
        right[-1][-1] = float("inf")
    elif corruption == "boolean":
        right[-1][-1] = False
    else:
        right[-1][-1] = [right[-1][-1]]
    with pytest.raises(ValueError):
        reader._numeric(left, right)


class PlainArchive:
    def __init__(self, value):
        self.stored = value
        self.root = Path("/ordinary-test-archive")
        self.result = {"hardware": {"device_index": 0}}
    def value(self, pin):
        return deepcopy(self.stored)


def _span_fixture():
    row = {"modality": [[0., 0., 0.]], "presence": [[[0., 0.] for _ in range(4)]],
        "start": [[[0.] * 3 for _ in range(6)]], "end": [[[0.] * 3 for _ in range(6)]]}
    scope = {"scope": "separate_checked_private_four_logit_forward_outside_public_timing",
        "coverage": "one_snapshot_per_lane_per_count", "entry_and_exit_owned_checks": True, "singletons": True,
        "observations": [{"rows": 1, "source_tokens": [3], "native_input_dimension": 768,
            "output_dtype": "float32", "gru_executed": True, "input_device": "cpu",
            "output_devices": {name: "cpu" for name in reader.OUTPUTS}}]}
    return [row], {"complete_four_logits": {"path": "/ordinary-test-archive/span768-original_cpu_reference-1-logits.json"},
                   "numeric_snapshot_scope": scope}


def test_complete_four_head_snapshot_accepts_bounded_float32_content_scope():
    rows, observation = _span_fixture()
    assert reader._span_numeric(PlainArchive(rows), observation, 1, [3], label="original_cpu_reference",
                                stem="span768-original_cpu_reference-1") == rows


@pytest.mark.parametrize("head", reader.OUTPUTS)
def test_complete_four_head_snapshot_refuses_any_missing_head(head):
    rows, observation = _span_fixture()
    del rows[0][head]
    with pytest.raises(ValueError):
        reader._span_numeric(PlainArchive(rows), observation, 1, [3], label="original_cpu_reference",
                             stem="span768-original_cpu_reference-1")


@pytest.mark.parametrize("mutation", ["end_tail", "source_width", "rows", "cuda_scope", "wrong_device", "nonboolean_singletons", "float64_value"])
def test_four_logits_join_source_width_device_and_strict_gru_scope(mutation):
    rows, observation = _span_fixture()
    lengths = [3]
    label, stem = "original_cpu_reference", "span768-original_cpu_reference-1"
    if mutation == "end_tail":
        rows[0]["end"][0][-1].pop()
    elif mutation == "source_width":
        lengths = [2]
    elif mutation == "rows":
        observation["numeric_snapshot_scope"]["observations"][0]["rows"] = 2
    elif mutation == "cuda_scope":
        label, stem = "original_cuda", "span768-original_cuda-1"
        observation["complete_four_logits"]["path"] = "/ordinary-test-archive/" + stem + "-logits.json"
        observation["numeric_snapshot_scope"]["singletons"] = False
        forward = observation["numeric_snapshot_scope"]["observations"][0]
        forward["input_device"] = "cuda:0"
        forward["output_devices"] = {name: "cuda:0" for name in reader.OUTPUTS}
        forward["gru_precision"] = {"profile_id": "native-768-source-span-device-strict-cuda-float32/v2",
            "scoped_cudnn": True, "effective_policy": {"cudnn": {"allow_tf32": True}},
            "synchronized_before_restore": True, "ambient_flags_restored": True}
    elif mutation == "wrong_device":
        observation["numeric_snapshot_scope"]["observations"][0]["input_device"] = "cuda:0"
    elif mutation == "nonboolean_singletons":
        observation["numeric_snapshot_scope"]["singletons"] = 1
    else:
        rows[0]["end"][0][-1][-1] = 0.1
    with pytest.raises(ValueError):
        reader._span_numeric(PlainArchive(rows), observation, 1, lengths, label=label, stem=stem)


def test_reader_source_has_no_model_import_or_retained_execution():
    import ast
    tree = ast.parse(READER.read_bytes())
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    names = {name.name.split(".")[0] for node in imports if isinstance(node, ast.Import) for name in node.names}
    names.update(node.module.split(".")[0] for node in imports if isinstance(node, ast.ImportFrom))
    assert not names & {"torch", "numpy", "ipfs_datasets_py", "importlib", "runpy", "pickle"}
    dangerous = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec", "compile", "__import__"}]
    assert dangerous == []


@pytest.mark.parametrize("text", [b'{"ignored":1e999}', b'{"nested":[{"ignored":-1e999}]}', b'{"ignored":Infinity}'])
def test_all_json_numbers_are_finite_even_in_ignored_fields(text):
    with pytest.raises(ValueError):
        reader._json(text)


@pytest.mark.parametrize("mutation", ["binding", "source_hash", "latent_hash", "row_id", "nested_authority",
    "source_provenance", "inherited_provenance", "checkpoint_guard", "scheduler_source", "native_provenance",
    "anchor_sha", "anchor_bytes", "guard_schema", "guard_tensor_count", "lease_id", "float64_projection"])
def test_independent_checkpoint_input_profile_anchor_and_lease_joins(tmp_path, mutation):
    root, result = _copy_archive(tmp_path)
    observation = result["families"]["formula8"]["lanes"]["bitwise_cpu_opt_out"]["counts"]["1"]
    path = Path(observation["result"]["path"])
    report = json.loads(path.read_bytes())
    profile = report["inference_implementation"]
    if mutation == "binding":
        report["binding"]["core_sha256"] = "0" * 64
    elif mutation in ("source_hash", "latent_hash", "row_id"):
        name = {"source_hash": "source_sha256", "latent_hash": "latent_sha256", "row_id": "id"}[mutation]
        report["rows"][0][name] = "0" * 64
    elif mutation == "nested_authority":
        report["rows"][0]["formal_outputs"][0]["proof_authority"] = True
    elif mutation == "source_provenance":
        profile["source_sha256"] = "0" * 64
    elif mutation == "inherited_provenance":
        profile["inherited_device_implementation"]["parent"]["source_sha256"] = "0" * 64
    elif mutation == "checkpoint_guard":
        profile["checkpoint_guard_source_sha256"] = "0" * 64
    elif mutation == "scheduler_source":
        profile["resource_scheduler_source_sha256"] = "0" * 64
    elif mutation == "native_provenance":
        profile["native_checkpoint_implementation"]["files"]["modal_latent_formula.py"] = "0" * 64
    elif mutation == "anchor_sha":
        profile["reference_byte_currentness"]["anchor_sha256"] = "0" * 64
    elif mutation == "anchor_bytes":
        profile["reference_byte_currentness"]["reference_bytes"] -= 4
    elif mutation == "guard_schema":
        profile["owned_tensor_currentness"]["schema"] = "unqualified/v0"
    elif mutation == "guard_tensor_count":
        profile["owned_tensor_currentness"]["tensor_count"] += 1
    elif mutation == "lease_id":
        profile["resource_lease"]["lease_id"] = "unowned"
    else:
        path = Path(observation["projected_vectors"]["path"])
        report = json.loads(path.read_bytes())
        report[0][-1] += 1e-10
    _dump(path, report)
    _repin(root, result, path)
    _refused(root)


def test_coordinated_cpu_and_all_lane_source_hash_tampering_still_refuses_exact_inputs(tmp_path):
    root, result = _copy_archive(tmp_path)
    for path in root.glob("formula8-*-result.json"):
        report = json.loads(path.read_bytes())
        for row in report["rows"]:
            row["source_sha256"] = "0" * 64
        _dump(path, report)
        _repin(root, result, path)
        canonical = path.with_name(path.name.replace("-result.json", "-canonical.json"))
        _dump(canonical, reader._decisions(report, "formula"))
        _repin(root, result, canonical)
    report = _refused(root)
    assert "exact reconstructed input" in report["error"]["detail"]


def test_coordinated_trial_alias_and_coherent_raw_timing_repin_cannot_claim_240_returns(tmp_path):
    root, result = _copy_archive(tmp_path, QUALIFIED)
    count = result["families"]["formula8"]["counts"]["1"]
    first = count["trials"][0]["observations"]["original_cuda"]
    for trial in count["trials"][1:]:
        actual = trial["observations"]["original_cuda"]
        for name in ("result", "canonical_projection", "projected_vectors"):
            actual[name] = deepcopy(first[name])
    raw_path = Path(count["raw_timing_evidence"]["path"])
    _dump(raw_path, {name: count[name] for name in ("trials", "samples_seconds", "median_seconds")})
    _repin(root, result, raw_path)
    report = _refused(root)
    assert "unique exact public-return filename" in report["error"]["detail"]


def test_bounded_inventory_refuses_an_unknown_empty_directory(tmp_path):
    root, _ = _copy_archive(tmp_path, FAILED01)
    (root / "unbounded-descendants").mkdir()
    report = _refused(root)
    assert "directory" in report["error"]["detail"]


@pytest.mark.parametrize("mutation", ["allocation_float_zero", "lease_boolean_zero", "allocated_gpu", "child_family"])
def test_plain_resource_zeros_and_exact_owned_child_families(tmp_path, mutation):
    root, result = _copy_archive(tmp_path)
    if mutation == "allocation_float_zero":
        result["resources_after"]["allocated"]["cpu_slots"] = 0.0
    elif mutation == "lease_boolean_zero":
        result["resources_after"]["active_child_lease_count"] = False
    elif mutation == "allocated_gpu":
        result["resources_after"]["allocated_gpu_memory_mb"] = 1
    else:
        result["owned_children"][0]["family"] = "unknown"
    _dump(root / "result.json", result)
    _refused(root)


def test_zeroed_coherent_four_head_panel_cannot_match_unchanged_public_decisions():
    report = json.loads((QUALIFIED / "span768-original_cpu_reference-1-result.json").read_bytes())
    text = "Lark must retain books."
    width = len(reader._tokens(text))
    zero = {"modality": [[0.] * 3], "presence": [[[0., 0.] for _ in range(4)]],
        "start": [[[0.] * width for _ in range(6)]], "end": [[[0.] * width for _ in range(6)]]}
    with pytest.raises(ValueError):
        reader._span_join(report, [reader._span_decision(text, zero)])


@pytest.mark.parametrize("value", [0.1, True, 0, float("inf")])
def test_float32_exact_representability_and_plain_float_type(value):
    with pytest.raises((ValueError, OverflowError)):
        reader._float32(value)
