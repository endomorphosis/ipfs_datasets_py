"""Focused binding controls over the existing CONTENT batch route.

Fixtures remain independently authored declarations, with target-derived
signature/role context. Fresh binder identities change declared structure but
preserve lexical alpha structure. No numerical model or legal accuracy claim.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from ipfs_datasets_py.logic.autoformal import legal_relational_batch_evaluation_v1 as owner
from ipfs_datasets_py.logic.autoformal import legal_compact_content_v1 as content
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as tokens


def _fixtures():
    path = Path(__file__).with_name("test_legal_relational_content_token_batch_evaluation_v1.py")
    spec = importlib.util.spec_from_file_location("_content_batch_binding_authored_fixtures", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


fixtures = _fixtures()
material = fixtures.material
legacy = fixtures.legacy
wire, sha, prepare, validate = fixtures.wire, fixtures.sha, fixtures.prepare, fixtures.validate
make_case = fixtures.make_case


def ledger(report):
    assert len(report["observation_ledger"]) == 1
    return report["observation_ledger"][0]


def test_real_public_decode_and_target_free_replay_preserve_existing_closed_report(material, monkeypatch):
    case = make_case(material)
    before = deepcopy(case)
    original = content.decode_prediction_v1
    calls = []
    def target_free(*args, **kwargs):
        assert len(args) == 2
        assert set(kwargs) == {"expected_content_sha256", "expected_context_sha256"}
        assert set(json.loads(args[0])) == {"schema", "tree"}
        assert set(json.loads(args[1])) == {"schema", "signature", "argument_roles"}
        calls.append((sha(args[0]), sha(args[1])))
        return original(*args, **kwargs)
    monkeypatch.setattr(content, "decode_prediction_v1", target_free)
    monkeypatch.setattr(content, "reconstruct_request_v1",
                        lambda *args, **kwargs: pytest.fail("archival identity reconstruction entered prediction"))
    report = prepare(case)
    assert case == before and validate(case, report) == report
    # Both token materialization and the batch's fresh public replay occur;
    # validation repeats the same target-free path, with no reference argument.
    assert len(calls) >= 4 and len(set(calls)) == 1
    decoded = ledger(report)["content_decoding"]
    assert decoded == fixtures.direct(case["predictions"]["rows"][0], material)
    assert decoded["prediction"]["identity_mode"] == "generated"
    assert decoded["prediction"]["request"]["source_binding"] is None
    assert decoded["prediction"]["request"]["expression"]["expression_id"] != material["request"]["expression"]["expression_id"]
    assert report["occurrences"][0]["pair_diagnostic"]["comparisons"] == {
        "exact_typed_expression_equal": False, "family_profile_equal": True,
        "signature_declarations_equal": True, "argument_roles_equal": True,
        "declared_structure_equal": False, "lexical_alpha_structure_equal": True}
    assert owner.relational_content_token_batch_evaluation_sha256(report) == sha(wire(report))
    assert "semantic_codec" not in report and "decoding_contexts" not in report
    fixtures.assert_no_authority(report)


@pytest.mark.parametrize("substitution", ["genuine_rival_prediction", "resealed_content_transport", "codec_commitment", "genuine_rival_request"])
def test_real_public_rival_cannot_replace_token_trace_or_materialized_request(material, monkeypatch, substitution):
    case = make_case(material)
    rival_request = legacy._FIXTURE._FIXTURE.approval_request(inner=True)
    projection = fixtures.project(rival_request)
    rival_raw = wire(projection["content"])
    context_raw = wire(material["context"])
    rival = tokens.decode_compact_content_tokens_v1(
        fixtures.ids_for(projection["content"], material["codec"]), context_raw,
        expected_context_sha256=sha(context_raw), codec=material["codec"],
        expected_codec_sha256=material["codec_sha256"])
    assert rival["status"] == "valid_candidate"
    assert rival["prediction"]["content"] != material["content"]
    original = tokens.decode_compact_content_tokens_v1
    def substituted(*args, **kwargs):
        result = original(*args, **kwargs)
        assert result["status"] == "valid_candidate"
        if substitution == "genuine_rival_prediction":
            result["prediction"] = deepcopy(rival["prediction"])
        elif substitution == "resealed_content_transport":
            result["generated_content_raw_utf8"] = rival_raw.decode()
            result["generated_content_hex"] = rival_raw.hex()
            result["generated_content_sha256"] = sha(rival_raw)
        elif substitution == "genuine_rival_request":
            result["prediction"]["request"] = deepcopy(rival["prediction"]["request"])
            result["prediction"]["request_sha256"] = rival["prediction"]["request_sha256"]
        else:
            result["codec_sha256"] = "0" * 64
        return result
    monkeypatch.setattr(tokens, "decode_compact_content_tokens_v1", substituted)
    with pytest.raises(owner.RelationalBatchEvaluationError):
        prepare(case)


@pytest.mark.parametrize("damage", ["token_drop", "token_size", "prediction_drop", "prediction_size"])
def test_complete_fixed_producer_population_and_actual_lengths_are_required_after_real_decode(material, monkeypatch, damage):
    case = make_case(material)
    original = tokens.decode_compact_content_tokens_v1
    def changed(*args, **kwargs):
        report = original(*args, **kwargs)
        assert report["status"] == "valid_candidate"
        target = report["prediction"] if damage.startswith("prediction") else report
        if damage.endswith("drop"):
            target["owner_pins"].pop()
        else:
            target["owner_pins"][0]["bytes"] += 1
        return report
    monkeypatch.setattr(tokens, "decode_compact_content_tokens_v1", changed)
    with pytest.raises(owner.RelationalBatchEvaluationError):
        prepare(case)


@pytest.mark.parametrize("damage", ["token_authority", "token_training", "prediction_authority", "prediction_evaluation"])
def test_token_and_prediction_authority_cannot_be_upgraded_after_genuine_public_intake(material, monkeypatch, damage):
    case = make_case(material)
    original = tokens.decode_compact_content_tokens_v1
    def changed(*args, **kwargs):
        report = original(*args, **kwargs)
        assert report["status"] == "valid_candidate"
        target = report["prediction"] if damage.startswith("prediction") else report
        if damage.endswith("authority"):
            target["authority"][next(iter(target["authority"]))] = True
        else:
            target["training_mask" if damage.endswith("training") else "evaluation_gold_mask"] = 1
        return report
    monkeypatch.setattr(tokens, "decode_compact_content_tokens_v1", changed)
    with pytest.raises(owner.RelationalBatchEvaluationError):
        prepare(case)


@pytest.mark.parametrize("damage", ["raw_ids", "request", "producer", "authority"])
def test_resealed_full_report_cannot_change_original_observations_or_binding_claims(material, damage):
    case = make_case(material)
    report = prepare(case)
    changed = deepcopy(report)
    if damage == "raw_ids": ledger(changed)["raw_observation"]["generated_ids"] = []
    elif damage == "request":
        decoded = ledger(changed)["content_decoding"]
        decoded["prediction"]["request"]["expression"]["expression_id"] = "authored:substitute"
        decoded["prediction"]["request_sha256"] = sha(wire(decoded["prediction"]["request"]))
        ledger(changed)["content_decoding_sha256"] = sha(wire(decoded))
    elif damage == "producer": changed["producer_pins"][next(iter(changed["producer_pins"]))] = "0" * 64
    else: changed["authority"]["model_executed"] = True
    assert owner.relational_content_token_batch_evaluation_sha256(changed) == sha(wire(changed))
    with pytest.raises(owner.RelationalBatchEvaluationError, match="regeneration"):
        validate(case, changed)
    assert prepare(case) == report


def test_retained_full_token_report_ids_context_and_producer_rows_are_detached(material):
    case = make_case(material)
    original = deepcopy(case)
    report = prepare(case)
    snapshot = deepcopy(report)
    case["predictions"]["rows"][0]["generated_ids"].append(999)
    case["predictions"]["rows"][0]["content_context_utf8"] = "changed caller context"
    case["predictions"]["codec"]["vocabulary"][0] = "changed caller codec"
    assert report == snapshot
    ledger(report)["raw_observation"]["generated_ids"].append(777)
    ledger(report)["content_decoding"]["prediction"]["owner_pins"][0]["bytes"] += 1
    assert 777 not in case["predictions"]["rows"][0]["generated_ids"]
    assert prepare(original) == snapshot


def test_independent_complete_report_pin_refuses_before_original_replay(material, monkeypatch):
    case = make_case(material)
    report = prepare(case)
    raw, pins = legacy.originals(case)
    monkeypatch.setattr(owner, "prepare_relational_content_token_batch_evaluation_v1",
                        lambda *args, **kwargs: pytest.fail("regenerated before independent report pin"))
    with pytest.raises(owner.RelationalBatchEvaluationError):
        owner.validate_relational_content_token_batch_evaluation_v1(report, *raw,
            expected_evaluation_sha256="0" * 64, **pins)


def test_source_fence_after_real_token_decode_is_operational_and_never_a_model_score(material, monkeypatch):
    """Alter only an observed pin after the real call; write no canonical source."""
    case = make_case(material)
    original_decode = tokens.decode_compact_content_tokens_v1
    original_sources = owner._content_sources
    armed = False
    def sources(*args, **kwargs):
        pins, snapshots = original_sources(*args, **kwargs)
        if armed:
            pins = dict(pins)
            path = next(path for path in pins if path.endswith("legal_compact_content_tokens_v1.py"))
            pins[path] = "0" * 64
        return pins, snapshots
    def decoded(*args, **kwargs):
        nonlocal armed
        report = original_decode(*args, **kwargs)
        assert report["status"] == "valid_candidate"
        armed = True
        return report
    monkeypatch.setattr(owner, "_content_sources", sources)
    monkeypatch.setattr(tokens, "decode_compact_content_tokens_v1", decoded)
    with pytest.raises(owner.RelationalBatchEvaluationError):
        prepare(case)
    assert armed


def test_existing_legacy_and_full_request_reports_do_not_change_across_content_binding_replay(material):
    old = legacy.case_for(["one"], material["request"])
    old_before = legacy.prepare(old)
    byte_case = deepcopy(old)
    codec = fixtures.byte_compact.build_relational_compact_codec_v1()
    codec_sha = fixtures.byte_compact.relational_compact_codec_sha256(codec)
    raw = wire(material["request"])
    encoded = fixtures.byte_compact.encode_relational_compact_target_v1(raw,
        expected_request_sha256=sha(raw), codec=codec, expected_codec_sha256=codec_sha)
    byte_case["predictions"] = {"schema": owner.COMPACT_PREDICTIONS_SCHEMA,
        "codec": codec, "codec_sha256": codec_sha,
        "generation": legacy.generation(sha(byte_case["population_raw"])),
        "rows": [{**byte_case["population"]["rows"][0], "status": "generated",
            "teacher_forcing": False, "target_access": False,
            "generated_ids": encoded["target_ids"], "generated_ids_sha256": sha(wire(encoded["target_ids"])),
            "reason": None}]}
    byte_raw, byte_pins = legacy.originals(byte_case)
    byte_before = owner.prepare_relational_compact_batch_evaluation_v1(*byte_raw, **byte_pins)
    core = deepcopy(owner._OPERATION_SNAPSHOTS)
    compact = deepcopy(owner._COMPACT_OPERATION_SNAPSHOTS)
    result = prepare(make_case(material))
    assert owner._OPERATION_SNAPSHOTS == core and owner._COMPACT_OPERATION_SNAPSHOTS == compact
    assert legacy.prepare(old) == old_before
    assert owner.prepare_relational_compact_batch_evaluation_v1(*byte_raw, **byte_pins) == byte_before
    assert old_before["full_selected_structure_diagnostics"]["exact_typed_expression_equal"]["matched"] == 1
    assert byte_before["full_selected_structure_diagnostics"]["exact_typed_expression_equal"]["matched"] == 1
    assert result["full_selected_structure_diagnostics"]["exact_typed_expression_equal"]["matched"] == 0
    assert result["full_selected_structure_diagnostics"]["lexical_alpha_structure_equal"]["matched"] == 1
