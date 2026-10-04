"""Fail-closed source preflight around a native dimensional decoder stub."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.legal_ir import canonical_span_decoder as subject

SOURCE = "The clerk must record evidence."
OWNER_FALSE = {
    "qualified": False, "admitted": False, "formalized": False,
    "roundtrip_ok": False, "proof_authority": False,
    "semantic_correctness_verified": False, "promotion_performed": False,
    "publication_performed": False,
}
WRAPPER_FALSE = (
    "target_access", "teacher_forcing", "training_executed", "context_applied",
    "source_fidelity_established", "qualified", "proof_authority", "accepted",
)


def digest(value, *, ascii=True):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=ascii,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def source_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def request(identity="first", source=SOURCE, context="", required=False):
    return {"id": identity, "source_text": source, "context_text": context,
            "requires_context_resolution": required}


def reseal(record):
    record["content_sha256"] = digest(
        {key: value for key, value in record.items() if key != "content_sha256"},
        ascii=False,
    )
    return record


class DecoderStub:
    """Exercise the public owner's receipt contract without loading a model."""

    def __init__(self, dimension=8, *, enabled=True, mutation=None, exception=None,
                 decoded=False):
        self.checkpoint = {
            "lineage_id": "native_dimensional_source_span_v1",
            "config": {"latent_dimension": dimension, "latent_enabled": enabled},
            "source_parent_checkpoint_sha256": "1" * 64,
            "context_contract_sha256": "2" * 64,
            "model_state": {"probe.weight": [[0.125, -0.25]]},
        }
        self.checkpoint_sha256 = digest(self.checkpoint)
        self.calls = []
        self.last_result = None
        self.mutation = mutation
        self.exception = exception
        self.decoded = decoded

    def decode_formal_logic(self, texts, latents=None, *, latent_ablation="none"):
        self.calls.append((copy.deepcopy(texts), copy.deepcopy(latents), latent_ablation))
        if self.exception is not None:
            raise self.exception
        dimension = self.checkpoint["config"]["latent_dimension"]
        vectors = latents if dimension else [[] for _ in texts]
        rows = [self._row(text, vector, latent_ablation) for text, vector in
                zip(texts, vectors, strict=True)]
        count = sum(row["status"] == "decoded" for row in rows)
        result = {
            "schema": "native-dimensional-source-span-inference/v1",
            "lineage_id": self.checkpoint["lineage_id"],
            "checkpoint_sha256": self.checkpoint_sha256,
            "source_parent_checkpoint_sha256": self.checkpoint["source_parent_checkpoint_sha256"],
            "context_contract_sha256": self.checkpoint["context_contract_sha256"],
            "input_dimension": dimension, "rows": rows, "decoded_count": count,
            "status": "decoded" if count == len(rows) else "partial" if count else "abstained",
            "latent_ablation": latent_ablation, "target_access": False,
            "teacher_forcing": False, "training_executed": False,
            "model_state_unchanged": True, **OWNER_FALSE,
        }
        if self.mutation is not None:
            self.mutation(result)
        self.last_result = result
        return result

    def _row(self, text, vector, control):
        result = {
            "source_sha256": source_hash(text), "latent_sha256": digest(vector),
            "status": "abstained", "canonical_ir": None, "formal_outputs": [],
            "formula_text": None, "teacher_forcing": False, "target_access": False,
            "training_executed": False, "source_input_conditioned": True,
            "learned_formula_generation": True, "sample_memory_used": False,
            "family_syntax_checked": False,
            "latent_input_enabled": (control != "disabled"
                                     and self.checkpoint["config"]["latent_enabled"]
                                     and bool(vector)),
            "reason": "nonfinite_decoder_scores", **OWNER_FALSE,
        }
        if not self.decoded:
            return result
        assert text == SOURCE
        rule = {"actor": "clerk", "modality": "O", "action": "record",
                "object": "evidence", "conditions": [], "exceptions": [], "temporal": []}
        canonical_ir = {"rules": [rule]}
        display = json.dumps(canonical_ir, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"))
        positions = (("The", 0, 3), ("clerk", 4, 9), ("must", 10, 14),
                     ("record", 15, 21), ("evidence", 22, 30), (".", 30, 31))
        tokens = [{"text": word, "start": left, "end": right}
                  for word, left, right in positions]
        facets = {}
        for name, index in (("actor", 1), ("action", 3), ("object", 4),
                            ("conditions", None), ("exceptions", None), ("temporal", None)):
            present = index is not None
            optional = name not in ("actor", "action")
            facets[name] = {
                "present": present, "presence_logit_margin": 1.0 if optional else None,
                "token_start": index, "token_end_inclusive": index,
                "char_start": None if index is None else tokens[index]["start"],
                "char_end": None if index is None else tokens[index]["end"],
                "text": None if index is None else tokens[index]["text"],
                "span_logit_margin": 1.0 if present else None,
            }
        return {**result, "status": "decoded", "reason": None,
                "canonical_ir": canonical_ir, "formula_text": display,
                "minimum_decision_logit_margin": 1.0,
                "span_diagnostics": {"tokens": tokens, "facets": facets,
                                     "modality_logits": [2.0, 0.0, -1.0]},
                "family_syntax_checked": True,
                "syntax_scope": "single_canonical_deontic_rule_with_one_copied_span_per_facet",
                "formal_outputs": [{"family": "deontic", "format": "typed-deontic-rule/v1",
                    "payload": copy.deepcopy(rule), "formula_text": display,
                    "formula_text_role": "display_only_full_ast_is_authoritative",
                    "origin": "learned_source_span_formula_decoder", **OWNER_FALSE}]}


def vectors(count, dimension=8):
    return [[float(index + 1)] * dimension for index in range(count)]


def test_unassessed_source_reaches_owner_without_gaining_semantic_authority():
    decoder = DecoderStub(decoded=True)
    requests, latents = [request()], vectors(1)
    result = subject.decode_with_preflight(decoder, requests, latents)
    assert decoder.calls == [([SOURCE], latents, "none")]
    assert result["decoder_call_count"] == result["decoder_completion_count"] == 1
    assert result["rows"][0]["preflight"]["outcome"] == "unassessed"
    assert result["rows"][0]["decoder_row"]["status"] == "decoded"
    assert result["rows"][0]["decoder_row"]["canonical_ir"]["rules"][0]["actor"] == "clerk"
    assert all(result[field] is False for field in WRAPPER_FALSE)
    assert subject.validate_preflight_decoding(result, requests, latents) == result
    assert len(decoder.calls) == 1


@pytest.mark.parametrize("blocked", [
    request(source="Every clerk must record evidence."),
    request(source="The clerk need not record evidence."),
    request(context="The clerk refers to the custodian."),
    request(required=True),
    request(source="The clerk must record evidence tomorrow."),
    request(source="The clerk must record " + "a " * 257 + "."),
    request(source="The clerk must record " + "a" * 2049 + "."),
])
def test_blocked_source_context_and_encoding_never_reach_decoder(blocked):
    decoder = DecoderStub()
    result = subject.decode_with_preflight(decoder, [blocked], vectors(1))
    assert decoder.calls == []
    assert result["eligible_count"] == result["decoder_call_count"] == 0
    assert result["backend_result"] is None and result["rows"][0]["decoder_row"] is None
    assert all(result[field] is False for field in WRAPPER_FALSE)
    assert subject.validate_preflight_decoding(result, [blocked], vectors(1)) == result


def test_original_full_rotation_uses_blocked_donors_before_filtering():
    requests = [request("blocked", source="Every clerk must record evidence."),
                request("kept"), request("context", context="Actor is the custodian.")]
    latents = vectors(3)
    decoder = DecoderStub()
    result = subject.decode_with_preflight(decoder, requests, latents, latent_ablation="rotate")
    assert decoder.calls == [([SOURCE], [latents[2]], "none")]
    assert result["submitted_positions"] == [1]
    assert result["owner_control"] == "none" and result["requested_control"] == "rotate"
    assert [row["latent_donor_id"] for row in result["rows"]] == ["kept", "context", "blocked"]
    assert [row["latent_donor_position"] for row in result["rows"]] == [1, 2, 0]
    assert result["rows"][1]["effective_latent_sha256"] == digest(latents[2])
    assert subject.validate_preflight_decoding(result, requests, latents) == result


@pytest.mark.parametrize("control,owner_control,expected,enabled", [
    ("none", "none", [1.0] * 8, True),
    ("zero", "none", [0.0] * 8, True),
    ("disabled", "disabled", [1.0] * 8, False),
])
def test_zero_preserves_branch_while_disabled_preserves_input(control, owner_control, expected, enabled):
    decoder = DecoderStub()
    requests, latents = [request()], vectors(1)
    result = subject.decode_with_preflight(decoder, requests, latents, latent_ablation=control)
    assert decoder.calls == [([SOURCE], [expected], owner_control)]
    assert result["rows"][0]["latent_input_enabled"] is enabled
    assert result["rows"][0]["effective_latent_sha256"] == digest(expected)
    assert subject.validate_preflight_decoding(result, requests, latents) == result


@pytest.mark.parametrize("bad_vector", [[float("nan")] * 8, [float("inf")] * 8,
    [True] * 8, ["1"] * 8, [1.0] * 7, [3.5e38] * 8, None])
def test_invalid_blocked_vectors_are_rejected_before_any_model_call(bad_vector):
    decoder = DecoderStub()
    requests = [request(source="Every clerk must record evidence."), request("eligible")]
    with pytest.raises(ValueError):
        subject.decode_with_preflight(decoder, requests, [bad_vector, [1.0] * 8])
    assert decoder.calls == []


@pytest.mark.parametrize("dimension", [0, 8, 384, 768])
def test_native_dimensions_are_preserved_without_padding_or_projection(dimension):
    decoder = DecoderStub(dimension=dimension)
    latents = vectors(1, dimension) if dimension else None
    result = subject.decode_with_preflight(decoder, [request()], latents)
    assert decoder.calls == [([SOURCE], latents, "none")]
    assert result["decoder_metadata"]["input_dimension"] == dimension
    assert result["rows"][0]["latent_input_enabled"] is bool(dimension)
    assert subject.validate_preflight_decoding(result, [request()], latents) == result


def test_checkpoint_disabled_adapter_cannot_report_enabled_input():
    decoder = DecoderStub(enabled=False)
    result = subject.decode_with_preflight(decoder, [request()], vectors(1))
    assert result["rows"][0]["latent_input_enabled"] is False
    assert result["rows"][0]["decoder_row"]["latent_input_enabled"] is False


def change_decoded_modality(result):
    row = result["rows"][0]
    row["canonical_ir"]["rules"][0]["modality"] = "F"
    display = json.dumps(row["canonical_ir"], ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    row["formula_text"] = display
    row["formal_outputs"][0].update(
        payload=copy.deepcopy(row["canonical_ir"]["rules"][0]), formula_text=display)


@pytest.mark.parametrize("mutation", [
    change_decoded_modality,
    lambda result: result["rows"][0]["span_diagnostics"].update(modality_logits=[2.0, 2.0, 0.0]),
    lambda result: result["rows"][0].update(minimum_decision_logit_margin=0.5),
    lambda result: result["rows"][0]["span_diagnostics"]["facets"]["actor"].update(char_start=0),
    lambda result: result["rows"][0]["canonical_ir"]["rules"][0].update(actor="officer"),
    lambda result: result["rows"][0]["formal_outputs"][0]["payload"].update(action="retain"),
    lambda result: result["rows"][0]["formal_outputs"][0].update(proof_authority=True),
    lambda result: result["rows"][0].update(formula_text="O(record(evidence))"),
])
def test_decoded_ast_display_diagnostics_and_formal_payload_must_agree(mutation):
    decoder = DecoderStub(decoded=True, mutation=mutation)
    with pytest.raises(ValueError):
        subject.decode_with_preflight(decoder, [request()], vectors(1))
    assert len(decoder.calls) == 1


@pytest.mark.parametrize("change", [
    lambda checkpoint: checkpoint["config"].update(latent_dimension=16),
    lambda checkpoint: checkpoint["config"].update(latent_dimension=True),
    lambda checkpoint: checkpoint["config"].update(latent_enabled=1),
    lambda checkpoint: checkpoint.update(lineage_id="other_decoder"),
])
def test_invalid_checkpoint_metadata_is_rejected_before_invocation(change):
    decoder = DecoderStub()
    change(decoder.checkpoint)
    decoder.checkpoint_sha256 = digest(decoder.checkpoint)
    with pytest.raises(ValueError):
        subject.decode_with_preflight(decoder, [request()], vectors(1))
    assert decoder.calls == []


def test_changed_checkpoint_content_cannot_reuse_a_stale_digest():
    decoder = DecoderStub()
    decoder.checkpoint["model_state"]["probe.weight"][0][0] = 0.75
    with pytest.raises(ValueError, match="checkpoint content binding"):
        subject.decode_with_preflight(decoder, [request()], vectors(1))
    assert decoder.calls == []


def test_metadata_change_during_invocation_fails_closed():
    decoder = DecoderStub()

    def modify_checkpoint(result):
        decoder.checkpoint["model_state"]["probe.weight"][0][0] = 0.75
        decoder.checkpoint_sha256 = digest(decoder.checkpoint)

    decoder.mutation = modify_checkpoint
    with pytest.raises(ValueError, match="metadata changed"):
        subject.decode_with_preflight(decoder, [request()], vectors(1))
    assert len(decoder.calls) == 1


@pytest.mark.parametrize("mutation", [
    lambda result: result["rows"].pop(),
    lambda result: result["rows"].reverse(),
    lambda result: result["rows"].append(copy.deepcopy(result["rows"][0])),
    lambda result: result["rows"][0].update(source_sha256="0" * 64),
    lambda result: result["rows"][0].update(latent_sha256="0" * 64),
    lambda result: result.update(checkpoint_sha256="0" * 64),
    lambda result: result.update(source_parent_checkpoint_sha256="0" * 64),
    lambda result: result.update(context_contract_sha256="0" * 64),
    lambda result: result.update(input_dimension=True),
    lambda result: result.update(model_state_unchanged=False),
    lambda result: result.update(latent_ablation="rotate"),
    lambda result: result.update(decoded_count=1),
    lambda result: result.update(target_access=True),
    lambda result: result.update(teacher_forcing=True),
    lambda result: result.update(qualified=0),
    lambda result: result["rows"][0].update(latent_input_enabled=False),
    lambda result: result["rows"][0].update(proof_authority=True),
    lambda result: result["rows"][0].update(source_input_conditioned=False),
    lambda result: result["rows"][0].update(hidden_target="oracle"),
])
def test_malformed_backend_joins_and_authority_fail_closed(mutation):
    decoder = DecoderStub(mutation=mutation)
    requests = [request(), request("second", "The clerk must retain evidence.")]
    with pytest.raises(ValueError):
        subject.decode_with_preflight(decoder, requests, vectors(2))
    assert len(decoder.calls) == 1


@pytest.mark.parametrize("exception,category", [
    (ImportError("private environment path"), "ImportError"),
    (OSError("private runtime detail"), "OSError"),
    (TimeoutError("private deadline"), "OSError"),
    (RuntimeError("private model detail"), "RuntimeError"),
])
def test_operational_unavailability_is_explicit_and_does_not_expose_exception_text(exception, category):
    decoder = DecoderStub(exception=exception)
    requests, latents = [request()], vectors(1)
    result = subject.decode_with_preflight(decoder, requests, latents)
    assert len(decoder.calls) == result["decoder_call_count"] == 1
    assert result["decoder_completion_count"] == 0 and result["backend_result"] is None
    assert result["backend_exception_type"] == category
    assert result["rows"][0]["decoder_row"] is None
    assert "private" not in json.dumps(result)
    assert all(result[field] is False for field in WRAPPER_FALSE)
    assert subject.validate_preflight_decoding(result, requests, latents) == result


@pytest.mark.parametrize("exception", [ValueError("contract"), TypeError("contract"),
                                       AssertionError("invariant")])
def test_contract_errors_propagate_instead_of_becoming_unavailable(exception):
    decoder = DecoderStub(exception=exception)
    with pytest.raises(type(exception), match=str(exception)):
        subject.decode_with_preflight(decoder, [request()], vectors(1))
    assert len(decoder.calls) == 1


@pytest.mark.parametrize("field", ["canonical_ir", "target", "row_kind",
                                  "expected_outcome", "vocabulary"])
def test_hidden_evaluation_channels_are_rejected_before_model_call(field):
    decoder = DecoderStub()
    supplied = request()
    supplied[field] = "oracle"
    with pytest.raises(ValueError):
        subject.decode_with_preflight(decoder, [supplied], vectors(1))
    with pytest.raises(TypeError):
        subject.decode_with_preflight(decoder, [request()], vectors(1), **{field: "oracle"})
    assert decoder.calls == []


@pytest.mark.parametrize("requests,latents,control", [
    ([], [], "none"),
    ([request(), request()], vectors(2), "none"),
    ([request()] * 129, vectors(129), "none"),
    ([request()], vectors(1), "rotate"),
    ([request()], vectors(1), "unknown"),
    ([request()], None, "none"),
    ([request()], vectors(2), "none"),
    ([request(source="\ud800")], vectors(1), "none"),
    ([request(context="\ud800")], vectors(1), "none"),
    ([request(required=1)], vectors(1), "none"),
])
def test_invalid_request_panel_is_rejected_without_model_execution(requests, latents, control):
    decoder = DecoderStub()
    with pytest.raises(ValueError):
        subject.decode_with_preflight(decoder, requests, latents, latent_ablation=control)
    assert decoder.calls == []


@pytest.mark.parametrize("mutation", [
    lambda result: result["rows"][0].update(position=1),
    lambda result: result["rows"][0].update(id="other"),
    lambda result: result["rows"][0].update(source_sha256="0" * 64),
    lambda result: result["rows"][0].update(context_sha256="0" * 64),
    lambda result: result["rows"][0].update(request_sha256="0" * 64),
    lambda result: result["rows"][0].update(original_latent_sha256="0" * 64),
    lambda result: result["rows"][0].update(effective_latent_sha256="0" * 64),
    lambda result: result["rows"][0].update(latent_donor_id="other"),
    lambda result: result["rows"][0].update(latent_donor_position=1),
    lambda result: result["rows"][0].update(submitted_position=1),
    lambda result: result.update(submitted_positions=[]),
    lambda result: result.update(eligible_count=0),
    lambda result: result.update(decoder_call_count=0),
    lambda result: result["decoder_metadata"].update(checkpoint_sha256="0" * 64),
    lambda result: result["decoder_metadata"].update(context_contract_sha256="0" * 64),
    lambda result: result["decoder_metadata"].update(source_parent_checkpoint_sha256="0" * 64),
    lambda result: result["rows"][0]["preflight"].update(outcome="unsupported_profile"),
    lambda result: result["rows"][0]["preflight"]["context"].update(applied=True),
    lambda result: result.update(accepted=True),
    lambda result: result.update(source_fidelity_established=True),
    lambda result: result.update(hidden_target="oracle"),
])
def test_resealed_receipt_inconsistency_is_rejected_without_model_replay(mutation):
    decoder = DecoderStub()
    requests, latents = [request()], vectors(1)
    result = subject.decode_with_preflight(decoder, requests, latents)
    mutation(result)
    with pytest.raises(ValueError):
        subject.validate_preflight_decoding(reseal(result), requests, latents)
    assert len(decoder.calls) == 1


@pytest.mark.parametrize("changed", [
    request(source="The clerk must retain evidence."),
    request(context="Resolve this explicit context."),
    request(required=True),
    request(identity="changed"),
])
def test_validation_binds_exact_external_request(changed):
    decoder = DecoderStub()
    result = subject.decode_with_preflight(decoder, [request()], vectors(1))
    with pytest.raises(ValueError):
        subject.validate_preflight_decoding(result, [changed], vectors(1))
    assert len(decoder.calls) == 1


def test_validation_binds_exact_external_vectors():
    decoder = DecoderStub()
    result = subject.decode_with_preflight(decoder, [request()], vectors(1))
    with pytest.raises(ValueError):
        subject.validate_preflight_decoding(result, [request()], [[2.0] * 8])
    assert len(decoder.calls) == 1


def test_caller_inputs_and_decoder_receipts_are_detached():
    decoder = DecoderStub()
    requests, latents = [request()], vectors(1)
    original_requests, original_latents = copy.deepcopy(requests), copy.deepcopy(latents)
    result = subject.decode_with_preflight(decoder, requests, latents)
    replayed = subject.validate_preflight_decoding(result, requests, latents)
    assert requests == original_requests and latents == original_latents
    assert replayed == result and replayed is not result
    assert replayed["rows"] is not result["rows"]
    assert result["backend_result"] is not decoder.last_result
    assert result["rows"][0]["decoder_row"] is not result["backend_result"]["rows"][0]
    decoder.last_result["rows"][0]["reason"] = "caller mutation"
    assert result["backend_result"]["rows"][0]["reason"] == "nonfinite_decoder_scores"
    result["rows"][0]["decoder_row"]["reason"] = "second mutation"
    assert replayed["rows"][0]["decoder_row"]["reason"] == "nonfinite_decoder_scores"


def test_import_and_source_preflight_do_not_load_a_numeric_backend():
    code = """
import hashlib
import json
import sys
from types import SimpleNamespace
from ipfs_datasets_py.logic.legal_ir.canonical_span_decoder import decode_with_preflight
assert 'torch' not in sys.modules
checkpoint = {'lineage_id': 'native_dimensional_source_span_v1',
              'config': {'latent_dimension': 8, 'latent_enabled': True},
              'source_parent_checkpoint_sha256': '1' * 64,
              'context_contract_sha256': '2' * 64, 'model_state': {'weight': [0.25]}}
sha = hashlib.sha256(json.dumps(checkpoint, sort_keys=True, separators=(',', ':'),
                               ensure_ascii=True).encode()).hexdigest()
def forbidden(*args, **kwargs):
    raise AssertionError('blocked source invoked model')
decoder = SimpleNamespace(checkpoint=checkpoint, checkpoint_sha256=sha,
                          decode_formal_logic=forbidden)
result = decode_with_preflight(decoder, [{'id': 'blocked',
    'source_text': 'Every clerk must record evidence.', 'context_text': '',
    'requires_context_resolution': False}], [[1.0] * 8])
assert result['eligible_count'] == result['decoder_call_count'] == 0
assert 'torch' not in sys.modules
"""
    completed = subprocess.run([sys.executable, "-c", code], check=False,
                               capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
