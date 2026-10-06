"""Adversarial admission controls; fixture assets are inert and private.

These controls exercise the metadata boundary, not model quality. Altered
synthetic artifacts are deliberately repinned only inside the fixture lane.
"""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import contextual_legal_ir_runtime as subject
from .test_contextual_legal_ir_runtime import (
    data, loader, open_contextual, pin, prepare, repin,
)


def _unopened_options():
    pin = {"path": "/unopened-contextual-fixture.json", "bytes": 2,
           "sha256": "a" * 64}
    return dict(request={"ir_family_id": "legal_ir", "dimension": 384,
        "dimension_role": "input_embedding", "task_id": "semantic_IR_reconstruction",
        "checkpoint_sha256": pin["sha256"]}, checkpoint_pin=deepcopy(pin),
        preprocessing_pin=deepcopy(pin), donor_checkpoint_pin=deepcopy(pin),
        source_inputs_pin=deepcopy(pin), source_contexts_pin=deepcopy(pin),
        source_owner_pins={}, row_ids=["source-1"])


def _forbid_reads(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("preflight attempted a file read or numerical load")
    monkeypatch.setattr(subject, "_read", forbidden)
    monkeypatch.setattr(subject, "_numeric_owner", forbidden)


@pytest.mark.parametrize("field,value", [
    ("dimension", True), ("dimension", 384.), ("dimension", "384"),
    ("dimension", 8), ("dimension", 786), ("ir_family_id", "intent_ir"),
    ("ir_family_id", "security_ir"), ("dimension_role", "output_embedding"),
    ("task_id", "legal_text_reconstruction"), ("checkpoint_sha256", "A" * 64),
    ("checkpoint_sha256", True), ("checkpoint_sha256", "a" * 63),
])
def test_invalid_selector_types_and_separate_tasks_refuse_before_reads(monkeypatch, field, value):
    options = _unopened_options()
    options["request"][field] = value
    _forbid_reads(monkeypatch)
    with pytest.raises(ValueError, match="retained Legal384/768"):
        subject.prepare_contextual_legal_ir_runtime(**options)


@pytest.mark.parametrize("field", ["profile_id", "format_id", "output_schema_version",
                                  "target_ids", "reference", "gold_prefix", "runtime_admitted"])
def test_extra_request_fields_are_not_selectors_or_inference_inputs(monkeypatch, field):
    options = _unopened_options()
    options["request"][field] = None
    _forbid_reads(monkeypatch)
    with pytest.raises(ValueError, match="closed five-field"):
        subject.prepare_contextual_legal_ir_runtime(**options)


@pytest.mark.parametrize("value", [True, False, 0, -1, 8 * 1024 * 1024 + 1,
                                  8 * 1024 * 1024., "8388608", None])
def test_reference_byte_cap_requires_exact_bounded_integer(monkeypatch, value):
    options = _unopened_options()
    options["max_reference_bytes"] = value
    _forbid_reads(monkeypatch)
    with pytest.raises(ValueError, match="reference cap"):
        subject.prepare_contextual_legal_ir_runtime(**options)


@pytest.mark.parametrize("value", [True, False, 0, -1, 120.00001,
                                  float("nan"), float("inf"), "120", None])
def test_deadline_requires_finite_positive_bounded_number(monkeypatch, value):
    options = _unopened_options()
    options["deadline_seconds"] = value
    _forbid_reads(monkeypatch)
    with pytest.raises(ValueError, match="inference deadline"):
        subject.prepare_contextual_legal_ir_runtime(**options)


@pytest.mark.parametrize("value", [[], ["source-1"] * 2, ["source-1"] * 65,
                                  "source-1", [True], [None], [""], ["a" * 513]])
def test_selected_row_identity_bounds_and_duplicates_refuse_before_reads(monkeypatch, value):
    options = _unopened_options()
    options["row_ids"] = value
    _forbid_reads(monkeypatch)
    with pytest.raises(ValueError):
        subject.prepare_contextual_legal_ir_runtime(**options)


def test_metadata_import_and_preflight_never_attempt_ml_imports_in_fresh_process():
    repository = Path(subject.__file__).parents[4]
    script = r'''
import importlib.abc, sys
class RefuseML(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'transformers', 'numpy', 'sentence_transformers',
            'accelerate', 'datasets', 'huggingface_hub', 'safetensors'}:
            raise AssertionError('metadata attempted ML import: ' + fullname)
sys.meta_path.insert(0, RefuseML())
from ipfs_datasets_py.logic.formalization.autoencoder import contextual_legal_ir_runtime as owner
try:
    owner.prepare_contextual_legal_ir_runtime({}, checkpoint_pin={}, preprocessing_pin={},
        donor_checkpoint_pin={}, source_inputs_pin={}, source_contexts_pin={},
        source_owner_pins={}, row_ids=[])
except ValueError:
    pass
else:
    raise AssertionError('invalid metadata request was accepted')
assert not any(name.split('.')[0] in {'torch', 'transformers', 'numpy', 'sentence_transformers',
    'accelerate', 'datasets', 'huggingface_hub', 'safetensors'} for name in sys.modules)
print('metadata-only')
'''
    environment = os.environ.copy()
    environment.update(PYTHONPATH=str(repository), IPFS_DATASETS_PY_MINIMAL_IMPORTS="1",
                       HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", CUDA_VISIBLE_DEVICES="")
    completed = subprocess.run([sys.executable, "-B", "-c", script], cwd=repository,
        env=environment, capture_output=True, text=True, timeout=20, check=False)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "metadata-only"


def _reseal(data):
    """Update declared hashes, leaving semantic checks to the production API."""
    checkpoint = data["checkpoint"]
    checkpoint["weights_sha256"] = subject._digest(checkpoint["model_state"])
    shapes, _ = subject._shapes(data["dimension"])
    try:
        checkpoint["tensor_sha256"] = subject._tensor_digest(
            checkpoint["model_state"], shapes, integer_buffers=True)
    except ValueError:
        # A malformed typed tensor must reach its validator with authentic bytes.
        pass
    repin(data)


@pytest.mark.parametrize("mutation", ["missing", "extra", "ragged", "boolean_float",
    "overflow_float", "string_float", "boolean_seed", "floating_seed", "wrong_seed",
    "wrong_version", "floating_version", "frozen_projection"])
def test_authenticated_bytes_do_not_admit_invalid_state_tensors(data, loader, mutation):
    state = data["checkpoint"]["model_state"]
    if mutation == "missing":
        state.pop("ordered_clause_recurrent_version")
    elif mutation == "extra":
        state["invented.tensor"] = 0.
    elif mutation == "ragged":
        state["body.body.body.output.weight"][0].pop()
    elif mutation == "boolean_float":
        state["body.body.body.output.bias"][0] = False
    elif mutation == "overflow_float":
        state["body.body.body.output.bias"][0] = 1e39
    elif mutation == "string_float":
        state["body.body.body.output.bias"][0] = "0"
    elif mutation == "boolean_seed":
        state["head_initialization_seed"] = True
    elif mutation == "floating_seed":
        state["head_initialization_seed"] = 1729.
    elif mutation == "wrong_seed":
        state["head_initialization_seed"] = 1728
    elif mutation == "wrong_version":
        state["ordered_clause_recurrent_version"] = 2
    elif mutation == "floating_version":
        state["ordered_clause_recurrent_version"] = 1.
    else:
        state["body.body.body.projection_up.bias"][0] = .25
    _reseal(data)
    with pytest.raises(ValueError):
        open_contextual(data)
    assert loader["loads"] == loader["calls"] == []


@pytest.mark.parametrize("mutation", ["weight_digest", "tensor_digest", "codec_size",
    "codec_duplicate", "codec_special", "codec_order", "architecture_dimension",
    "checkpoint_dimension", "schema", "selected", "authority", "extra_target"])
def test_checkpoint_codec_geometry_and_declared_contracts_refuse_before_load(data, loader, mutation):
    checkpoint = data["checkpoint"]
    if mutation in {"weight_digest", "tensor_digest"}:
        checkpoint["weights_sha256" if mutation == "weight_digest" else "tensor_sha256"] = "f" * 64
    elif mutation == "codec_size":
        checkpoint["codec"]["target_vocabulary"].pop()
    elif mutation == "codec_duplicate":
        checkpoint["codec"]["target_vocabulary"][-1] = checkpoint["codec"]["target_vocabulary"][-2]
    elif mutation == "codec_special":
        checkpoint["codec"]["target_vocabulary"][0] = "<other>"
    elif mutation == "codec_order":
        vocabulary = checkpoint["codec"]["target_vocabulary"]
        vocabulary[3], vocabulary[4] = vocabulary[4], vocabulary[3]
    elif mutation == "architecture_dimension":
        checkpoint["architecture"]["dimension"] = 768
    elif mutation == "checkpoint_dimension":
        checkpoint["dimension"] = 768
    elif mutation == "schema":
        checkpoint["schema"] = "legal_ir/v1"
    elif mutation == "selected":
        checkpoint["selected"] = 1
    elif mutation == "authority":
        checkpoint["proof_authority"] = True
    else:
        checkpoint["target_ids"] = [1, 2]
    repin(data)
    with pytest.raises(ValueError):
        open_contextual(data)
    assert loader["loads"] == []


def _receipt(value):
    value.pop("receipt_sha256", None)
    value["receipt_sha256"] = subject._digest(value)


@pytest.mark.parametrize("mutation", ["input_zero", "input_underflow", "input_boolean",
    "input_wrong_width", "paragraph_buffer", "clause_buffer", "norm_underflow",
    "norm_train_scope", "norm_validation_fit", "prior_current_targets", "prior_classes"])
def test_saved_transform_and_frozen_feature_receipts_require_distinct_consistent_stages(data, loader, mutation):
    checkpoint, preprocessing = data["checkpoint"], data["preprocessing"]
    transform = checkpoint["input_transform"]
    if mutation.startswith("input_"):
        if mutation == "input_wrong_width":
            transform["mean"].pop()
        else:
            transform["scale"] = {"input_zero": 0., "input_underflow": 1e-50,
                                  "input_boolean": True}[mutation]
    elif mutation == "paragraph_buffer":
        checkpoint["model_state"]["body.source_scale"] = 2.
    elif mutation == "clause_buffer":
        checkpoint["model_state"]["clause_source_mean"][0] = .1
    elif mutation.startswith("norm_"):
        norm = preprocessing["paragraph_normalization"]
        if mutation == "norm_underflow":
            norm["scale"] = norm["fitted_training_scale"] = 1e-50
            checkpoint["model_state"]["body.source_scale"] = 1e-50
        elif mutation == "norm_train_scope":
            norm["scope"] = "all_rows"
        else:
            norm["validation_rows_used_for_fitting"] = True
        _receipt(norm)
    else:
        prior = preprocessing["count_prior"]
        if mutation == "prior_current_targets":
            prior["target_access"] = "current_reference_targets"
        else:
            prior["count_classes"][-1] = True
        _receipt(prior)
    _reseal(data)
    with pytest.raises(ValueError):
        open_contextual(data)
    assert loader["loads"] == []


@pytest.mark.parametrize("field", ["target", "target_ids", "reference", "gold_prefix", "clause_count", "labels"])
def test_cached_source_rows_refuse_current_gold_and_rule_count_inputs(data, loader, field):
    data["rows"][0][field] = [1, 2]
    repin(data)
    with pytest.raises(ValueError, match="source-only"):
        open_contextual(data)
    assert loader["loads"] == []


@pytest.mark.parametrize("mutation", ["boolean", "wrong_width", "nested", "nonunit", "overflow", "duplicate_id",
                                    "duplicate_text", "empty_text", "swapped_paragraph"])
def test_paragraph_cache_shape_values_and_source_binding(data, loader, mutation):
    row = data["rows"][0]
    if mutation == "boolean":
        row["input"][0] = True
    elif mutation == "wrong_width":
        row["input"].pop()
    elif mutation == "nested":
        row["input"][0] = [1.]
    elif mutation == "nonunit":
        row["input"][0] = .5
    elif mutation == "overflow":
        row["input"][0] = 1e39
    elif mutation == "duplicate_id":
        data["rows"][1]["id"] = row["id"]
    elif mutation == "duplicate_text":
        data["rows"][1]["source_text"] = row["source_text"]
    elif mutation == "empty_text":
        row["source_text"] = ""
    else:
        row["source_text"] = data["rows"][1]["source_text"] + " Changed."
    repin(data)
    with pytest.raises(ValueError):
        open_contextual(data)
    assert loader["loads"] == []


@pytest.mark.parametrize("mutation", ["extra_context", "missing_context", "swapped_context", "source_hash",
    "embedding_hash", "segment_text", "boolean_offset", "byte_offset", "char_offset",
    "vector_width", "vector_nonunit", "segment_count", "gold_context", "gold_segment"])
def test_clause_cache_is_bound_to_actual_source_and_complete_ordered_spans(data, loader, mutation):
    contexts = data["contexts"]
    descriptor = contexts["source:0"]
    segment = descriptor["segments"][0]
    if mutation == "extra_context":
        contexts["invented"] = deepcopy(descriptor)
    elif mutation == "missing_context":
        contexts.pop("source:1")
    elif mutation == "swapped_context":
        contexts["source:0"], contexts["source:1"] = contexts["source:1"], contexts["source:0"]
    elif mutation == "source_hash":
        descriptor["source_sha256"] = "a" * 64
    elif mutation == "embedding_hash":
        segment["embedding_sha256"] = "a" * 64
    elif mutation == "segment_text":
        segment["source_text"] += " Changed."
    elif mutation == "boolean_offset":
        segment["char_start"] = False
    elif mutation == "byte_offset":
        segment["byte_end"] += 1
    elif mutation == "char_offset":
        segment["char_end"] -= 1
    elif mutation == "vector_width":
        segment["vector"].pop()
    elif mutation == "vector_nonunit":
        segment["vector"] = [0.] * data["dimension"]
    elif mutation == "segment_count":
        descriptor["segments"] = [deepcopy(segment)] * 9
    elif mutation == "gold_context":
        descriptor["target"] = {}
    else:
        segment["target_ids"] = [1, 2]
    repin(data)
    with pytest.raises(ValueError):
        open_contextual(data)
    assert loader["loads"] == []


def test_selected_subset_rejects_unknown_rows_and_keeps_explicit_order(data, loader):
    with pytest.raises(ValueError):
        prepare(data, row_ids=["invented"])
    instance = open_contextual(data, row_ids=["source:0"])
    instance.infer_cached()
    assert [row["id"] for row in loader["calls"][0]["source_inputs"]["rows"]] == ["source:0"]
    assert set(loader["calls"][0]["source_inputs"]["contexts"]) == {"source:0"}


@pytest.mark.parametrize("mutation", ["wrong_pin", "foreign_owner", "missing_owner", "extra_owner"])
def test_source_owner_closure_refuses_drift_and_arbitrary_executable_paths(data, loader, tmp_path, mutation):
    owners = deepcopy(data["options"]["source_owner_pins"])
    name = next(iter(owners))
    if mutation == "wrong_pin":
        owners[name]["sha256"] = "f" * 64
    elif mutation == "foreign_owner":
        path = tmp_path / "foreign.py"
        path.write_text("raise AssertionError('foreign executable was imported')\n")
        owners[name] = pin(path)
    elif mutation == "missing_owner":
        owners.pop(name)
    else:
        owners["invented"] = owners[name]
    with pytest.raises(ValueError):
        open_contextual(data, source_owner_pins=owners)
    assert loader["loads"] == []


@pytest.mark.parametrize("mutation", ["content", "same_bytes_inode", "same_size_content"])
def test_closing_fence_refuses_earlier_private_file_exchange_after_later_read(data, loader, monkeypatch, mutation):
    checkpoint = Path(data["options"]["checkpoint_pin"]["path"])
    original = checkpoint.read_bytes()
    original_read = subject._read
    changed = False

    def read_and_exchange(file_pin, *args, **kwargs):
        nonlocal changed
        value = original_read(file_pin, *args, **kwargs)
        if file_pin["path"] == data["options"]["source_contexts_pin"]["path"] and not changed:
            changed = True
            if mutation == "same_bytes_inode":
                replacement = checkpoint.with_suffix(".replacement")
                replacement.write_bytes(original)
                replacement.replace(checkpoint)
            elif mutation == "same_size_content":
                checkpoint.write_bytes(original[:-1] + b" ")
            else:
                checkpoint.write_bytes(original + b" ")
        return value

    monkeypatch.setattr(subject, "_read", read_and_exchange)
    with pytest.raises(ValueError):
        open_contextual(data)
    assert changed and loader["loads"] == []


@pytest.mark.parametrize("stage", ["after_load", "after_infer", "between_calls"])
def test_rechecking_endpoint_changes_retains_honest_numerical_call_flags(data, loader, stage):
    checkpoint = Path(data["options"]["checkpoint_pin"]["path"])

    def exchange():
        replacement = checkpoint.with_suffix(".replacement")
        replacement.write_bytes(checkpoint.read_bytes())
        replacement.replace(checkpoint)

    if stage != "between_calls":
        loader[stage] = exchange
    with pytest.raises(subject.ContextualLegalRuntimeError) as caught:
        instance = open_contextual(data)
        if stage == "between_calls":
            exchange()
        instance.infer_cached()
    assert caught.value.model_load_started is True
    assert caught.value.model_load_performed is True
    assert caught.value.model_inference_started is (stage == "after_infer")
    assert caught.value.model_inference_executed is (stage == "after_infer")


@pytest.mark.parametrize("payload", [b'{"schema":1,"schema":2}', b'{"x":NaN}', b'{"x":Infinity}',
                                     b'{"x":1e9999}', b'[' * 65 + b'0' + b']' * 65])
def test_bounded_json_refuses_duplicates_nonfinite_and_excess_depth_before_load(data, loader, payload):
    path = Path(data["options"]["checkpoint_pin"]["path"])
    path.write_bytes(payload)
    data["options"]["checkpoint_pin"] = pin(path)
    data["options"]["request"]["checkpoint_sha256"] = pin(path)["sha256"]
    with pytest.raises(ValueError):
        open_contextual(data)
    assert loader["loads"] == []


@pytest.mark.parametrize("mutation", ["missing", "symlink", "parent_symlink", "dotdot", "relative",
                                    "hardlink", "fifo", "directory"])
def test_every_asset_is_existing_canonical_single_link_regular_before_any_descriptor_opens(data, loader, monkeypatch, mutation):
    options = deepcopy(data["options"])
    original = Path(options["source_inputs_pin"]["path"])
    declared = original
    if mutation == "missing":
        original.unlink()
    elif mutation == "symlink":
        declared = original.with_name("rows-alias.json")
        declared.symlink_to(original)
    elif mutation == "parent_symlink":
        alias = data["root"] / "parent-alias"
        alias.symlink_to(data["root"], target_is_directory=True)
        declared = alias / original.name
    elif mutation == "dotdot":
        sibling = data["root"] / "child"
        sibling.mkdir()
        declared = sibling / ".." / original.name
    elif mutation == "relative":
        declared = Path(original.name)
    elif mutation == "hardlink":
        os.link(original, original.with_name("same-inode.json"))
    elif mutation == "fifo":
        original.unlink()
        os.mkfifo(original)
    else:
        original.unlink()
        original.mkdir()
    options["source_inputs_pin"]["path"] = str(declared)
    opens = []

    def forbidden_open(*args, **kwargs):
        opens.append(args)
        raise AssertionError("unvalidated asset reached descriptor opening")

    monkeypatch.setattr(subject.os, "open", forbidden_open)
    with pytest.raises(ValueError):
        subject.open_contextual_legal_ir_autoencoder(**options)
    assert opens == loader["loads"] == []


@pytest.mark.parametrize("mutation", ["bool_bytes", "negative_bytes", "zero_bytes", "float_bytes",
                                    "oversized_bytes", "extra_field", "wrong_hash", "wrong_size"])
def test_declared_asset_pin_types_and_content_are_authenticated_before_load(data, loader, mutation):
    options = deepcopy(data["options"])
    declared = options["source_inputs_pin"]
    if mutation == "extra_field":
        declared["runtime_admitted"] = False
    elif mutation == "wrong_hash":
        declared["sha256"] = "f" * 64
    else:
        declared["bytes"] = {"bool_bytes": True, "negative_bytes": -1, "zero_bytes": 0,
            "float_bytes": float(declared["bytes"]), "oversized_bytes": 8*1024*1024+1,
            "wrong_size": declared["bytes"]+1}[mutation]
    with pytest.raises(ValueError):
        subject.open_contextual_legal_ir_autoencoder(**options)
    assert loader["loads"] == []


@pytest.mark.parametrize("mutation", ["context_digest", "inventory_order", "inventory_source", "dimension",
                                    "target_access", "missing_inventory"])
def test_saved_source_binding_pins_the_complete_cache_split(data, loader, mutation):
    binding = data["preprocessing"]["source_binding"]
    validation = binding["validation"]
    if mutation == "context_digest":
        validation["contexts_sha256"] = "f" * 64
    elif mutation == "inventory_order":
        validation["source_inventory"].reverse()
    elif mutation == "inventory_source":
        validation["source_inventory"][0]["source_sha256"] = "f" * 64
    elif mutation == "dimension":
        validation["dimension"] = True
    elif mutation == "target_access":
        binding["reference_labels_accessed"] = True
    else:
        validation.pop("source_inventory")
    repin(data)
    with pytest.raises(ValueError):
        open_contextual(data)
    assert loader["loads"] == []


def test_multiclause_unicode_offsets_and_order_are_validated_without_label_counts(data, loader):
    pieces = ["École keeps a record.", "公務員 preserves notice."]
    row = data["rows"][0]
    row["source_text"] = "\n\n".join(pieces)
    segments = []
    character = byte = 0
    for index, piece in enumerate(pieces):
        vector = [float(offset == index) for offset in range(data["dimension"])]
        segments.append(dict(source_text=piece, source_sha256=hashlib.sha256(piece.encode()).hexdigest(),
            embedding_sha256=subject._digest(vector), vector=vector, char_start=character,
            char_end=character+len(piece), byte_start=byte, byte_end=byte+len(piece.encode())))
        character += len(piece)+2
        byte += len(piece.encode())+2
    data["contexts"][row["id"]] = dict(source_sha256=hashlib.sha256(row["source_text"].encode()).hexdigest(),
                                         segments=segments)
    validation = data["preprocessing"]["source_binding"]["validation"]
    validation["contexts_sha256"] = subject._digest(data["contexts"])
    validation["source_inventory"] = [{"id": item["id"],
        "source_sha256": data["contexts"][item["id"]]["source_sha256"]} for item in data["rows"]]
    repin(data)
    observed = prepare(data, row_ids=[row["id"]])
    assert observed["row_receipts"][0]["source_padding_mask"] == [True, True] + [False]*6
    assert loader["loads"] == []
    assert segments[1]["byte_start"] != segments[1]["char_start"]
    segments.reverse()
    # Authenticate the changed cache receipt so literal ordering, rather than
    # only the old digest, must refuse this exchanged ordered span sequence.
    validation["contexts_sha256"] = subject._digest(data["contexts"])
    repin(data)
    with pytest.raises(ValueError, match="literal source-clause"):
        open_contextual(data)
    assert loader["loads"] == []


@pytest.mark.parametrize("stage", ["after_load", "after_infer"])
def test_loaded_numerical_owner_origin_exchange_is_detected_after_actual_call(data, loader, monkeypatch, stage):
    from ipfs_datasets_py.logic.formalization.autoencoder import contextual_legal_ir_numeric as numeric
    loader[stage] = lambda: monkeypatch.setattr(numeric, "__file__", str(data["root"] / "foreign.py"))
    with pytest.raises(subject.ContextualLegalRuntimeError) as caught:
        open_contextual(data).infer_cached()
    assert caught.value.model_load_performed is True
    assert caught.value.model_inference_started is (stage == "after_infer")
    assert caught.value.model_inference_executed is (stage == "after_infer")
    assert (caught.value.raw_candidate_report is not None) is (stage == "after_infer")


def test_parent_directory_exchange_cannot_turn_canonical_pins_into_later_aliases(data, loader):
    original = data["root"]
    moved = original.with_name(original.name + "-moved")
    exchanged = False

    def exchange_parent():
        nonlocal exchanged
        original.rename(moved)
        original.symlink_to(moved, target_is_directory=True)
        exchanged = True

    loader["after_load"] = exchange_parent
    try:
        with pytest.raises(subject.ContextualLegalRuntimeError) as caught:
            open_contextual(data)
        assert exchanged and caught.value.model_load_performed is True
        assert caught.value.model_inference_started is False
    finally:
        if exchanged:
            original.unlink()
            moved.rename(original)


def test_full_positive_metadata_fixture_remains_ml_database_and_network_free_in_fresh_process():
    repository = Path(subject.__file__).parents[4]
    script = r'''
import importlib.abc, pathlib, sys, tempfile
blocked = {'torch', 'transformers', 'numpy', 'sentence_transformers', 'accelerate',
    'datasets', 'huggingface_hub', 'safetensors', 'duckdb', 'sqlite3'}
class RefuseHeavy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            raise AssertionError('metadata attempted heavy import: ' + fullname)
def refuse_connections(event, arguments):
    if event in {'socket.connect', 'socket.connect_ex', 'socket.getaddrinfo', 'subprocess.Popen'}:
        raise AssertionError('metadata attempted network/process effect: ' + event)
sys.meta_path.insert(0, RefuseHeavy())
sys.addaudithook(refuse_connections)
from tests.unit.logic.formalization.autoencoder.test_contextual_legal_ir_runtime import make_contextual, prepare
with tempfile.TemporaryDirectory(prefix='contextual-metadata-bomb-') as location:
    fixture = make_contextual(pathlib.Path(location))
    report = prepare(fixture)
assert report['row_ids'] == ['source:1', 'source:0']
assert not report['model_load_performed'] and not report['model_inference_executed']
assert all(value is False for value in report['authority'].values())
assert not any(name.split('.')[0] in blocked for name in sys.modules)
print('complete-metadata-only')
'''
    environment = os.environ.copy()
    environment.update(PYTHONPATH=str(repository), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        IPFS_DATASETS_PY_MINIMAL_IMPORTS="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", CUDA_VISIBLE_DEVICES="")
    completed = subprocess.run([sys.executable, "-B", "-c", script], cwd=repository,
        env=environment, capture_output=True, text=True, timeout=20, check=False)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "complete-metadata-only"
