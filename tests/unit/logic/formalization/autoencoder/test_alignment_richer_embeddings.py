"""Source-only boundaries and diagnostic receipt integrity; no encoder loads."""
import importlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

subject = importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder.alignment_richer_embeddings")
panel_owner = importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder.alignment_richer_panel")


@pytest.fixture
def inputs():
    return subject.prepare_richer_embedding_inputs(panel_owner.build_alignment_richer_panel())


def diagnostic(inputs, lane_id="native384"):
    dimension = subject.DIMENSIONS[lane_id]
    receipts = [subject._receipt(row, [1.0] + [0.0] * (dimension - 1), token_count=2)
                for row in inputs["rows"]]
    return subject._lane(inputs, lane_id, receipts,
                         subject._backend("synthetic-test-only", execution_kind="injected_fixture"),
                         status="diagnostic_fixture", model_inference_executed=False, encoder_execution_executed=False)


def test_import_prepare_validate_and_source_spans_do_not_load_optional_encoders():
    code = r"""
import importlib, importlib.abc, sys
class Reject(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'torch','spacy','transformers','sentence_transformers','safetensors'}:
            raise AssertionError('encoder import attempted: '+fullname)
sys.meta_path.insert(0,Reject())
m=importlib.import_module('ipfs_datasets_py.logic.formalization.autoencoder.alignment_richer_embeddings')
p=importlib.import_module('ipfs_datasets_py.logic.formalization.autoencoder.alignment_richer_panel')
i=m.prepare_richer_embedding_inputs(p.build_alignment_richer_panel())
m.validate_richer_embedding_inputs(i)
s,raw,b=m._native384_inputs(i)
assert len(s)==34 and len(raw)==b['bytes']
assert all(x.source.source_kind=='diagnostic' for x in s)
assert all(name not in sys.modules for name in ('torch','spacy','transformers','sentence_transformers'))
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20,
                            cwd=Path(subject.__file__).resolve().parents[4])
    assert result.returncode == 0, result.stderr


def test_all34_sources_include_context_identity_without_context_consumption(inputs):
    panel = panel_owner.build_alignment_richer_panel()
    by_input = {row["input_sha256"]: row for row in panel["rows"]}
    assert inputs["row_count"] == 34 and inputs["context_unapplied_rows"] == 2
    assert inputs["rows"] == sorted(inputs["rows"], key=lambda row: row["id"])
    for row in inputs["rows"]:
        original = by_input[row["input_sha256"]]
        assert row["source_text"] == original["source_text"]
        assert row["id"] == "sha256:" + original["input_sha256"]
        assert row["context_applied"] is False
        assert set(row) == subject._ROW_KEYS
    contexts = [row for row in inputs["rows"] if row["context_role"] == "explicit_assumptions"]
    assert len({row["source_text"] for row in contexts}) == 1
    assert len({row["id"] for row in contexts}) == 2
    assert len({row["input_sha256"] for row in contexts}) == 2
    assert len({row["source_sha256"] for row in contexts}) == 1
    serialized = json.dumps(inputs)
    assert all(row["id"] not in serialized for row in panel["rows"])
    assert all(key not in serialized for key in ('"target"', '"split"', '"expectation"', '"bindings"', '"group_id"'))
    validation = subject.validate_richer_embedding_inputs(inputs)
    assert validation["context_identity_independently_recomputed"] is False
    assert validation["qualified"] is False


def test_preparation_is_independent_of_panel_order_and_returns_fresh_rows(inputs):
    panel = panel_owner.build_alignment_richer_panel()
    panel["rows"].reverse()
    panel["integrity"] = panel_owner._integrity(panel)
    assert subject.prepare_richer_embedding_inputs(panel) == inputs
    old = inputs["rows"][0]["source_text"]
    inputs["rows"][0]["source_text"] = "edited"
    assert panel["rows"][-1]["source_text"] != "edited"
    assert old != "edited"


def test_preparation_reads_no_targets_or_label_ids_after_owner_admission(monkeypatch):
    class DoNotRead:
        def __str__(self):
            raise AssertionError("target read")
    row = {"input_sha256": "a" * 64, "source_text": "  Exact\nsource café  ",
           "source_sha256": subject._source_sha("  Exact\nsource café  "),
           "context": {"role": "none_required"}, "target": DoNotRead(), "split": DoNotRead(), "id": DoNotRead()}
    monkeypatch.setattr(panel_owner, "validate_alignment_richer_panel", lambda panel: {"status": "test_stub"})
    result = subject.prepare_richer_embedding_inputs({"rows": [row]})
    assert result["rows"][0]["source_text"] == "  Exact\nsource café  "
    assert result["rows"][0]["id"] == "sha256:" + "a" * 64


@pytest.mark.parametrize("field", ["target", "canonical_ir", "split", "prediction", "context"])
def test_closed_rows_reject_encoder_hints(inputs, field):
    inputs["rows"][0][field] = {}
    subject._seal(inputs)
    with pytest.raises(ValueError, match="unknown or missing"):
        subject.validate_richer_embedding_inputs(inputs)


@pytest.mark.parametrize("text", ["", " \n", "x\x00y", "\ud800", "x" * 65537])
def test_invalid_text_rejected_before_encoding(inputs, text):
    inputs["rows"][0]["source_text"] = text
    with pytest.raises(ValueError):
        subject.validate_richer_embedding_inputs(inputs)


@pytest.mark.parametrize("field,value", [("row_count", True), ("row_count", 34.0),
                                         ("context_unapplied_rows", 2.0), ("context_unapplied_rows", True),
                                         ("all_context_unapplied", 1), ("qualified", 0), ("proof_authority", True)])
def test_input_type_aliases_and_authority_rejected(inputs, field, value):
    inputs[field] = value
    subject._seal(inputs)
    with pytest.raises(ValueError):
        subject.validate_richer_embedding_inputs(inputs)


@pytest.mark.parametrize("mutation", ["duplicate", "unsorted", "id", "source_hash", "context", "context_applied", "payload"])
def test_input_identity_integrity_guards(inputs, mutation):
    if mutation == "duplicate":
        inputs["rows"][1] = deepcopy(inputs["rows"][0])
    elif mutation == "unsorted":
        inputs["rows"].reverse()
    elif mutation == "id":
        inputs["rows"][0]["id"] = "class-label:obligation"
    elif mutation == "source_hash":
        inputs["rows"][0]["source_sha256"] = "b" * 64
    elif mutation == "context":
        inputs["rows"][0]["context_role"] = "resolved"
    elif mutation == "context_applied":
        inputs["rows"][0]["context_applied"] = True
    else:
        inputs["payload_sha256"] = "0" * 64
    if mutation != "payload":
        subject._seal(inputs)
    with pytest.raises(ValueError):
        subject.validate_richer_embedding_inputs(inputs)


def test_native384_source_blob_spans_exact_and_reconstructable_without_temp_path(inputs):
    selected, raw, blob = subject._native384_inputs(inputs)
    assert blob == subject._source_blob(inputs)[1]
    assert len(raw) == blob["bytes"]
    assert blob["sha256"] == subject.hashlib.sha256(raw).hexdigest()
    selectors = set()
    for row, item in zip(inputs["rows"], selected, strict=True):
        assert item.text == row["source_text"]
        source = item.source
        assert raw[source.byte_start:source.byte_end].decode("utf-8") == row["source_text"]
        assert source.document_id == row["id"] and source.citation == row["id"]
        assert source.source_kind == "diagnostic" and source.normalization == "identity"
        assert source.artifact.sha256 == blob["sha256"] and source.artifact.bytes == len(raw)
        selectors.add((source.byte_start, source.byte_end))
        assert "target" not in item.to_dict()
    assert len(selectors) == 34
    contexts = [item for row, item in zip(inputs["rows"], selected, strict=True)
                if row["context_role"] == "explicit_assumptions"]
    assert contexts[0].text == contexts[1].text and contexts[0].input_id != contexts[1].input_id


@pytest.mark.parametrize("lane_id", ["legacy8", "native384", "native768"])
def test_diagnostic_fixture_has_no_native_computation_or_semantic_authority(inputs, lane_id):
    result = diagnostic(inputs, lane_id)
    validation = subject.validate_embedding_lane(result, inputs)
    assert len(result["receipts"]) == validation["embedded_count"] == 34
    assert result["dimension"] == subject.DIMENSIONS[lane_id]
    assert result["status"] == "diagnostic_fixture"
    assert all(result[key] is False for key in subject._FALSE_FIELDS)
    assert result["model_inference_executed"] is result["encoder_execution_executed"] is False
    assert validation["runtime_cryptographically_attested"] is False
    assert result["receipts"][0]["embedding_sha256"] == subject._digest(result["receipts"][0]["embedding"])


@pytest.mark.parametrize("field", [*subject._FALSE_FIELDS, "model_inference_executed", "encoder_execution_executed"])
def test_fixture_cannot_acquire_model_context_or_qualification_claims(inputs, field):
    result = diagnostic(inputs)
    result[field] = True
    subject._seal(result)
    with pytest.raises(ValueError):
        subject.validate_embedding_lane(result, inputs)


@pytest.mark.parametrize("value", [True, 1, float("nan"), float("inf"), -float("inf"), 0.1])
def test_vector_numeric_types_finiteness_and_native_float32_preservation(inputs, value):
    result = diagnostic(inputs)
    result["receipts"][0]["embedding"][0] = value
    with pytest.raises(ValueError):
        subject.validate_embedding_lane(result, inputs)


@pytest.mark.parametrize("mutation", ["zero", "width", "norm", "hash", "id", "source", "input", "context",
                                     "count", "token_bool", "extra", "root_dim", "root_dim_bool", "production_hash"])
def test_lane_receipt_dimension_hash_and_input_guards(inputs, mutation):
    result = diagnostic(inputs)
    first = result["receipts"][0]
    if mutation == "zero":
        first["embedding"] = [0.0] * 384
    elif mutation == "width":
        first["embedding"].pop()
    elif mutation == "norm":
        first["embedding"][0] = 2.0
    elif mutation == "hash":
        first["embedding_sha256"] = "c" * 64
    elif mutation in {"id", "source", "input"}:
        first[{"id": "id", "source": "source_sha256", "input": "input_sha256"}[mutation]] = "c" * 64
    elif mutation == "context":
        first["context_applied"] = True
    elif mutation == "count":
        result["receipts"].pop()
    elif mutation == "token_bool":
        first["token_count"] = True
    elif mutation == "extra":
        first["target"] = {}
    elif mutation == "root_dim":
        result["dimension"] = 384.0
    elif mutation == "root_dim_bool":
        result["dimension"] = True
    else:
        result["backend_evidence"]["production_evidence_sha256"] = "c" * 64
    subject._seal(result)
    with pytest.raises(ValueError):
        subject.validate_embedding_lane(result, inputs)


def test_output_bound_to_whole_manifest_not_just_first_source(inputs):
    result = diagnostic(inputs)
    other = deepcopy(inputs)
    other["rows"][-1]["source_text"] += " additional exact source"
    other["rows"][-1]["source_sha256"] = subject._source_sha(other["rows"][-1]["source_text"])
    subject._seal(other)
    with pytest.raises(ValueError, match="manifest"):
        subject.validate_embedding_lane(result, other)


def test_native_label_without_actual_production_evidence_fails(inputs):
    result = diagnostic(inputs)
    result["status"] = "produced"
    result["backend_evidence"]["execution_kind"] = "observed_native"
    result["model_inference_executed"] = result["encoder_execution_executed"] = True
    subject._seal(result)
    with pytest.raises(ValueError, match="production evidence"):
        subject.validate_embedding_lane(result, inputs)


def test_native384_overlength_is_explicit_no_vector_diagnostic(inputs):
    receipts = [subject._receipt(row, None, token_count=513, token_input_sha256="a" * 64,
                                 status="token_limit_exceeded") for row in inputs["rows"]]
    result = subject._lane(inputs, "native384", receipts,
                           subject._backend("synthetic-test-only", execution_kind="injected_fixture"),
                           status="diagnostic_fixture", model_inference_executed=False, encoder_execution_executed=False)
    assert subject.validate_embedding_lane(result, inputs)["embedded_count"] == 0
    assert all(row["embedding"] is row["embedding_sha256"] is None for row in result["receipts"])


@pytest.mark.parametrize("lane_id", ["legacy8", "native384", "native768"])
def test_unavailable_is_stable_zero_coverage_no_execution(inputs, lane_id):
    result = subject._unavailable(inputs, lane_id, "missing-test-profile", "declared missing asset")
    assert result["status"] == "unavailable" and result["receipts"] == []
    assert result["backend_evidence"]["execution_kind"] == "not_executed"
    assert result["model_inference_executed"] is False and result["encoder_execution_executed"] is False
    assert subject.validate_embedding_lane(result, inputs)["embedded_count"] == 0
    result["model_inference_executed"] = True
    subject._seal(result)
    with pytest.raises(ValueError, match="unavailable"):
        subject.validate_embedding_lane(result, inputs)


def test_gte384_missing_declared_snapshot_does_not_load_models(inputs, tmp_path):
    result = subject.run_gte384(inputs, tmp_path / "missing")
    assert result["status"] == "unavailable"
    assert result["backend_evidence"]["profile_id"] == subject.GTE384_PROFILE_ID


def test_gte768_missing_roots_admitted_without_tensor_import(inputs, tmp_path):
    complete = importlib.import_module(subject._AUTOENCODER + "source_embeddings_768_complete")
    assets = complete.reference._PROFILE
    manifest = Path(subject.__file__).resolve().parents[4] / "configs/autoencoders/gte_multilingual_local_assets_v1.json"
    result = subject.run_gte768(inputs, manifest_path=manifest,
                               expected_manifest_sha256=subject.hashlib.sha256(manifest.read_bytes()).hexdigest(),
                               model_directory=tmp_path / "model", code_directory=tmp_path / "code")
    assert result["status"] == "unavailable" and result["dimension"] == 768
    assert result["backend_evidence"]["profile_id"] == assets.PROFILE_ID


@pytest.mark.parametrize("api", ["run_spacy8", "run_gte384", "run_gte768"])
def test_every_producer_rejects_target_hint_before_any_backend(inputs, api):
    inputs["rows"][0]["target"] = {"rules": []}
    with pytest.raises(ValueError, match="unknown or missing"):
        if api == "run_gte768":
            subject.run_gte768(inputs, manifest_path="missing", expected_manifest_sha256="0" * 64,
                               model_directory="missing-model", code_directory="missing-code")
        else:
            getattr(subject, api)(inputs)


@pytest.mark.parametrize("batch_size", [True, 0, 17, 1.0])
def test_neural_batch_bounds_fail_before_assets(inputs, batch_size):
    with pytest.raises(ValueError, match="batch_size"):
        subject.run_gte384(inputs, batch_size=batch_size)
    with pytest.raises(ValueError, match="batch_size"):
        subject.run_gte768(inputs, manifest_path="missing", expected_manifest_sha256="0" * 64,
                           model_directory="missing-model", code_directory="missing-code", batch_size=batch_size)


def test_small_spacy_package_binding_is_recomputable_and_ignores_bytecode(tmp_path):
    root = tmp_path / "package"
    root.mkdir()
    (root / "config.cfg").write_text("local config")
    (root / "meta.json").write_text('{"version":"unit"}')
    (root / "__pycache__").mkdir()
    (root / "__pycache__/cached.pyc").write_bytes(b"not loaded")
    result = subject._package_assets(root)
    assert len(result["files"]) == 2
    assert result["files_manifest_sha256"] == subject._digest(result["files"])
    assert result == subject._package_assets(root)
    (root / "config.cfg").write_text("changed config")
    assert result["files_manifest_sha256"] != subject._package_assets(root)["files_manifest_sha256"]


@pytest.mark.parametrize("kind", ["root", "file", "directory", "large"])
def test_spacy_package_links_and_size_refused(tmp_path, kind):
    root = tmp_path / "package"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("outside bytes")
    if kind == "root":
        link = tmp_path / "linked"
        link.symlink_to(root, target_is_directory=True)
        root = link
    elif kind == "file":
        (root / "linked.json").symlink_to(outside)
    elif kind == "directory":
        (root / "linked-directory").symlink_to(tmp_path, target_is_directory=True)
    else:
        with (root / "model").open("wb") as stream:
            stream.truncate(16 * 1024 * 1024 + 1)
    with pytest.raises(ValueError):
        subject._package_assets(root)
