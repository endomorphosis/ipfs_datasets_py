"""Context transport, scope and native evidence linkage without encoder loads."""
import importlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

subject = importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder.alignment_context_embeddings")
owner = importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder.alignment_richer_embeddings")
panel_owner = importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder.alignment_richer_panel")


@pytest.fixture
def inputs():
    return subject.prepare_context_embedding_inputs(panel_owner.build_alignment_richer_panel())


def diagnostic(inputs, lane_id="native384"):
    transport = subject.prepare_context_transport(inputs)
    width = owner.DIMENSIONS[lane_id]
    receipts = [owner._receipt(row, [1.0] + [0.0] * (width - 1), token_count=2) for row in transport["rows"]]
    inner = owner._lane(transport, lane_id, receipts,
                        owner._backend("synthetic-test-only", execution_kind="injected_fixture"),
                        status="diagnostic_fixture", encoder_execution_executed=False, model_inference_executed=False)
    return subject._wrap_context_lane(inputs, inner)


def by_original(inputs):
    groups = {}
    for row in inputs["rows"]:
        groups.setdefault(row["original_input_sha256"], {})[row["arm_id"]] = row
    return groups


def test_import_preparation_and_validation_do_not_load_optional_encoders():
    code = r"""
import importlib, importlib.abc, sys
class Reject(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'torch','spacy','transformers','sentence_transformers','safetensors'}:
            raise AssertionError('encoder import attempted: '+fullname)
sys.meta_path.insert(0,Reject())
c=importlib.import_module('ipfs_datasets_py.logic.formalization.autoencoder.alignment_context_embeddings')
p=importlib.import_module('ipfs_datasets_py.logic.formalization.autoencoder.alignment_richer_panel')
i=c.prepare_context_embedding_inputs(p.build_alignment_richer_panel())
c.validate_context_embedding_inputs(i)
t=c.prepare_context_transport(i)
assert len(t['rows'])==68
assert all(name not in sys.modules for name in ('torch','spacy','transformers','sentence_transformers'))
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20,
                            cwd=Path(subject.__file__).resolve().parents[4])
    assert result.returncode == 0, result.stderr


def test_34_originals_68_role_marked_rows_preserve_exact_source_and_context(inputs):
    originals = {row["input_sha256"]: row for row in panel_owner.build_alignment_richer_panel()["rows"]}
    assert inputs["original_row_count"] == 34 and inputs["row_count"] == 68
    assert inputs["context_forwarded_rows"] == 2
    assert inputs["rows"] == sorted(inputs["rows"], key=lambda row: row["id"])
    for row in inputs["rows"]:
        original = originals[row["original_input_sha256"]]
        assert row["source_text"] == original["source_text"]
        assert row["source_sha256"] == original["source_sha256"]
        assert row["context"] == original["context"]
        assert row["original_input_sha256"] == subject._original_input_sha(row)
        assert row["context_semantics_applied"] is False
        forwarded = row["arm_id"] == "declared_context" and original["context"]["role"] == "explicit_assumptions"
        literal = {"schema": "role-marked-source-context/v1", "source": {"role": "source", "text": original["source_text"]},
                   "assumptions": {"role": "declared_assumptions", "text": original["context"]["text"] if forwarded else "",
                                   "bindings": original["context"]["bindings"] if forwarded else {}}}
        assert row["encoder_text"] == json.dumps(literal, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        assert row["encoder_text_sha256"] == subject._text_sha(row["encoder_text"])
        assert row["context_forwarded"] is forwarded
        assert row["id"] == row["transport_id"] == "sha256:" + row["transport_input_sha256"]
        assert row["transport_input_sha256"] == subject._transport_sha(row)
        assert all(key not in json.loads(row["encoder_text"]) for key in
                   ("arm_id", "id", "input_sha256", "split", "target", "expectation"))
    validation = subject.validate_context_embedding_inputs(inputs)
    assert validation["original_input_identity_recomputed"] is True
    assert validation["context_semantics_applied"] is validation["qualified"] is False


def test_no_context_arms_have_identical_model_text_but_distinct_transport_identities(inputs):
    groups = by_original(inputs)
    no_context = [group for group in groups.values() if group["declared_context"]["context"]["role"] == "none_required"]
    assert len(no_context) == 32
    for group in no_context:
        frame, full = (group[arm] for arm in subject.ARMS)
        assert frame["encoder_text"] == full["encoder_text"]
        assert frame["encoder_text_sha256"] == full["encoder_text_sha256"]
        assert frame["id"] != full["id"]
        assert frame["context_forwarded"] is full["context_forwarded"] is False


def test_same_source_context_pair_has_common_formatting_control_and_distinct_declared_inputs(inputs):
    contextual = [group for group in by_original(inputs).values()
                  if group["declared_context"]["context"]["role"] == "explicit_assumptions"]
    assert len(contextual) == 2
    frames = [group["source_frame_only"] for group in contextual]
    declared = [group["declared_context"] for group in contextual]
    assert len({row["source_text"] for row in frames + declared}) == 1
    assert len({row["encoder_text"] for row in frames}) == 1
    assert len({row["encoder_text"] for row in declared}) == 2
    assert len({row["id"] for row in frames + declared}) == 4
    for frame, full in zip(frames, declared, strict=True):
        assert json.loads(frame["encoder_text"])["assumptions"] == {"role": "declared_assumptions", "text": "", "bindings": {}}
        assert full["encoder_text"] != frame["encoder_text"]
        assert full["context_forwarded"] is True and frame["context_forwarded"] is False
        assert json.loads(full["encoder_text"])["assumptions"]["bindings"] == full["context"]["bindings"]


def test_preparation_is_order_independent_and_context_is_not_aliased(inputs):
    panel = panel_owner.build_alignment_richer_panel()
    panel["rows"].reverse()
    panel["integrity"] = panel_owner._integrity(panel)
    assert subject.prepare_context_embedding_inputs(panel) == inputs
    group = next(group for group in by_original(inputs).values() if group["declared_context"]["context_forwarded"])
    frame, full = (group[arm] for arm in subject.ARMS)
    full["context"]["text"] = "edited"
    assert frame["context"]["text"] != "edited"
    assert all(row["context"]["text"] != "edited" for row in panel["rows"])


def test_only_input_fields_are_read_after_panel_owner_admission(monkeypatch):
    class Forbidden:
        def __str__(self):
            raise AssertionError("label read after input admission")
    panel = panel_owner.build_alignment_richer_panel()
    for row in panel["rows"]:
        for key in ("target", "target_sha256", "expectation", "split", "id", "group_id", "qualifier_vocabulary"):
            row[key] = Forbidden()
    monkeypatch.setattr(panel_owner, "validate_alignment_richer_panel", lambda value: {"status": "test_stub"})
    result = subject.prepare_context_embedding_inputs(panel)
    assert len(result["rows"]) == 68
    serialized = json.dumps(result)
    assert all('"' + key + '"' not in serialized for key in ("target", "split", "expectation", "group_id", "qualifier_vocabulary"))


def test_transport_is_valid_frozen_compatibility_schema_for_rendered_text_only(inputs):
    transport = subject.prepare_context_transport(inputs)
    owner.validate_richer_embedding_inputs(transport)
    assert transport["row_count"] == 68 and transport["context_unapplied_rows"] == 0
    for row, inner in zip(inputs["rows"], transport["rows"], strict=True):
        assert inner["id"] == row["transport_id"]
        assert inner["input_sha256"] == row["transport_input_sha256"]
        assert inner["source_text"] == row["encoder_text"]
        assert inner["source_sha256"] == row["encoder_text_sha256"]
        assert inner["context_role"] == "none_required" and inner["context_applied"] is False
        assert inner["source_sha256"] != row["source_sha256"]


@pytest.mark.parametrize("field,value", [("row_count", 68.0), ("original_row_count", True), ("context_forwarded_rows", 2.0),
                                         *[(field, True) for field in subject._FALSE_FIELDS], ("qualified", 0)])
def test_input_counts_and_scope_cannot_use_numeric_aliases(inputs, field, value):
    inputs[field] = value
    subject._seal(inputs)
    with pytest.raises(ValueError):
        subject.validate_context_embedding_inputs(inputs)


@pytest.mark.parametrize("field", ["target", "split", "expectation", "canonical_ir", "vocabulary", "prediction"])
def test_closed_inputs_and_rows_reject_label_hints(inputs, field):
    for record in (inputs, inputs["rows"][0]):
        record[field] = {}
        subject._seal(inputs)
        with pytest.raises(ValueError, match="closed"):
            subject.validate_context_embedding_inputs(inputs)
        del record[field]


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "unsorted", "arm", "domain", "logic", "source_sha",
                                     "original_sha", "encoder_sha", "rendering", "transport_sha", "transport_id", "id",
                                     "forwarded", "forwarded_alias", "resolved", "payload", "context_role", "context_sha",
                                     "binding_kind", "binding_extra", "empty_binding", "context_nul", "source_nul"])
def test_input_binding_rendering_and_context_admission(inputs, mutation):
    row = next(row for row in inputs["rows"] if row["context_forwarded"])
    if mutation == "duplicate":
        inputs["rows"][1] = deepcopy(inputs["rows"][0])
    elif mutation == "missing":
        inputs["rows"].pop()
    elif mutation == "unsorted":
        inputs["rows"].reverse()
    elif mutation == "arm":
        row["arm_id"] = "automatic_context"
    elif mutation == "domain":
        row["domain_id"] = "Security"
    elif mutation == "logic":
        row["logic_family"] = "fol"
    elif mutation in {"source_sha", "original_sha", "encoder_sha", "transport_sha"}:
        row[{"source_sha": "source_sha256", "original_sha": "original_input_sha256", "encoder_sha": "encoder_text_sha256",
             "transport_sha": "transport_input_sha256"}[mutation]] = "0" * 64
    elif mutation in {"transport_id", "id"}:
        row[mutation] = "sha256:" + "0" * 64
    elif mutation == "rendering":
        row["encoder_text"] += " "
        row["encoder_text_sha256"] = subject._text_sha(row["encoder_text"])
    elif mutation in {"forwarded", "forwarded_alias", "resolved"}:
        row["context_semantics_applied" if mutation == "resolved" else "context_forwarded"] = 1 if mutation == "forwarded_alias" else mutation == "resolved"
    elif mutation == "payload":
        inputs["payload_sha256"] = "0" * 64
    elif mutation == "context_role":
        row["context"]["role"] = "interpreted"
    elif mutation == "context_sha":
        row["context"]["sha256"] = "0" * 64
    elif mutation in {"binding_kind", "binding_extra"}:
        binding = next(iter(row["context"]["bindings"].values()))
        binding["kind" if mutation == "binding_kind" else "target"] = "generated" if mutation == "binding_kind" else {}
    elif mutation == "empty_binding":
        row["context"]["bindings"] = {}
    elif mutation == "context_nul":
        row["context"]["text"] += "\x00"
    else:
        row["source_text"] += "\x00"
    if mutation != "payload":
        subject._seal(inputs)
    with pytest.raises(ValueError):
        subject.validate_context_embedding_inputs(inputs)


@pytest.mark.parametrize("text", ["", " \n", "\ud800", "x" * 65537])
def test_invalid_or_oversized_text_is_rejected_before_production(inputs, text):
    inputs["rows"][0]["source_text"] = text
    with pytest.raises(ValueError):
        subject.validate_context_embedding_inputs(inputs)


@pytest.mark.parametrize("lane_id", subject.DIMENSIONS)
def test_truthful_diagnostic_lane_retains_inner_receipts_without_native_claims(inputs, lane_id):
    result = diagnostic(inputs, lane_id)
    validation = subject.validate_context_embedding_lane(result, inputs)
    assert result["dimension"] == subject.DIMENSIONS[lane_id]
    assert result["status"] == validation["production_status"] == "diagnostic_fixture"
    assert validation["receipt_count"] == validation["embedded_count"] == 68
    assert result["encoder_execution_executed"] is result["model_inference_executed"] is False
    assert all(result[field] is False for field in subject._FALSE_FIELDS)
    for row, outer, inner in zip(inputs["rows"], result["receipts"], result["transport_lane"]["receipts"], strict=True):
        assert outer["original_input_sha256"] == row["original_input_sha256"]
        assert outer["source_sha256"] == row["source_sha256"]
        assert inner["source_sha256"] == row["encoder_text_sha256"]
        assert outer["embedding"] == inner["embedding"] and outer["embedding_sha256"] == inner["embedding_sha256"]
        assert outer["representation_profile_id"].endswith("arm=" + row["arm_id"])
        assert outer["context_semantics_applied"] is False


@pytest.mark.parametrize("lane_id", subject.DIMENSIONS)
def test_unavailable_native_lane_remains_explicit_and_nonexecuted(inputs, lane_id):
    transport = subject.prepare_context_transport(inputs)
    native = owner._unavailable(transport, lane_id, "synthetic-unavailable-test", "test dependency unavailable")
    original = deepcopy(native)
    result = subject._wrap_context_lane(inputs, native)
    assert native == original and result["transport_lane"] == original
    assert result["status"] == "unavailable" and result["receipts"] == []
    assert result["encoder_execution_executed"] is result["model_inference_executed"] is False
    assert subject.validate_context_embedding_lane(result, inputs)["embedded_count"] == 0


def test_run_forwards_all68_literal_texts_once_and_preserves_producer_evidence(inputs, monkeypatch):
    calls = []
    def producer(transport, **options):
        calls.append((deepcopy(transport), options))
        width = 384
        receipts = [owner._receipt(row, [1.0] + [0.0] * (width - 1), token_count=2) for row in transport["rows"]]
        return owner._lane(transport, "native384", receipts,
                           owner._backend("synthetic-test-only", execution_kind="injected_fixture"),
                           status="diagnostic_fixture", encoder_execution_executed=False, model_inference_executed=False)
    monkeypatch.setattr(owner, "run_gte384", producer)
    result = subject.run_context_lane(inputs, "native384", snapshot_path="/diagnostic/no-model", batch_size=1)
    assert len(calls) == 1 and len(calls[0][0]["rows"]) == 68
    assert calls[0][0] == subject.prepare_context_transport(inputs)
    assert calls[0][1] == {"snapshot_path": "/diagnostic/no-model", "batch_size": 1}
    assert result["status"] == "diagnostic_fixture" and result["model_inference_executed"] is False


@pytest.mark.parametrize("field", [*subject._FALSE_FIELDS, "encoder_execution_executed", "model_inference_executed"])
def test_context_fixture_cannot_promote_execution_or_authority(inputs, field):
    result = diagnostic(inputs)
    result[field] = True
    subject._seal(result)
    with pytest.raises(ValueError):
        subject.validate_context_embedding_lane(result, inputs)


@pytest.mark.parametrize("mutation", ["dimension_bool", "dimension", "count", "vector", "vector_hash", "input",
                                     "arm", "context", "rendered_sha", "transport_manifest", "native_hash", "top_extra",
                                     "receipt_extra", "profile", "status", "scope_alias"])
def test_outer_and_inner_receipt_tampering_is_rejected_after_resealing(inputs, mutation):
    result = diagnostic(inputs)
    row = result["receipts"][0]
    if mutation in {"dimension_bool", "dimension"}:
        result["dimension"] = True if mutation == "dimension_bool" else 512
    elif mutation == "count":
        result["receipts"].pop()
    elif mutation == "vector":
        row["embedding"][0] = 0.0
    elif mutation == "vector_hash":
        row["embedding_sha256"] = "0" * 64
    elif mutation == "input":
        row["original_input_sha256"] = "0" * 64
    elif mutation == "arm":
        row["arm_id"] = "source_only"
    elif mutation == "context":
        row["context_forwarded"] = not row["context_forwarded"]
    elif mutation == "rendered_sha":
        row["encoder_text_sha256"] = "0" * 64
    elif mutation == "transport_manifest":
        result["transport_inputs"]["rows"][0]["source_text"] = "changed"
        owner._seal(result["transport_inputs"])
    elif mutation == "native_hash":
        result["transport_lane"]["payload_sha256"] = "0" * 64
    elif mutation == "top_extra":
        result["target"] = {}
    elif mutation == "receipt_extra":
        row["target"] = {}
    elif mutation == "profile":
        result["context_profile_id"] = owner.INPUT_RECIPE
    elif mutation == "status":
        result["status"] = "produced"
    else:
        result["qualified"] = 0
    subject._seal(result)
    with pytest.raises(ValueError):
        subject.validate_context_embedding_lane(result, inputs)


@pytest.mark.parametrize("lane_id", [None, True, 384, "leanstral", "native512"])
def test_invalid_lane_ids_fail_without_encoder_calls(inputs, lane_id):
    with pytest.raises(ValueError):
        subject.run_context_lane(inputs, lane_id)


@pytest.mark.parametrize("hint", ["target", "split", "context", "predicted_facets", "compiler", "provider"])
def test_run_accepts_only_native_producer_options(inputs, hint):
    with pytest.raises(ValueError, match="options"):
        subject.run_context_lane(inputs, "native384", **{hint: {}})


def test_nonfinite_and_cyclic_inputs_fail_as_value_error(inputs):
    inputs["forged"] = float("inf")
    with pytest.raises(ValueError):
        subject.validate_context_embedding_inputs(inputs)
    inputs["forged"] = inputs
    with pytest.raises(ValueError):
        subject.validate_context_embedding_inputs(inputs)
