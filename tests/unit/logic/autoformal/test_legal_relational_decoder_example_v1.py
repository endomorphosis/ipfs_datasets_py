"""Authored source/target examples preserve custody and zero eligibility."""
from copy import deepcopy
import builtins
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import legal_relational_decoder_example_v1 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import legal_relational_target_codec_v1 as target_codec


def _fixture_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixtures = _fixture_module("_decoder_example_join_fixtures", "test_legal_source_typed_norm_join_v1.py")


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def example_request(embedding=None, *, exposure="exposed"):
    return {"schema": "legal-relational-decoder-example-request/v1",
            "task_id": "typed_relational_IR_reconstruction",
            "exposure_status": exposure, "embedding_reference": embedding}


def embedding_reference(value, dimension):
    source_input = value["scope_report"]["scope_request"]
    return {"dimension": dimension, "producer_id": "fixture:declared-producer",
            "profile_id": "fixture:declared-profile", "token_limit": None,
            "cache_key": "fixture:opaque-cache-key", "payload_bytes": dimension * 4,
            "payload_sha256": "a" * 64, "source_input_sha256": sha(wire(source_input))}


def arguments(value, *, request=None):
    raw = wire(example_request() if request is None else request)
    codec = target_codec.build_relational_target_codec_v1()
    join_raw = fixtures.wire(value["join_request"])
    replay = {"scope_report": value["scope_report"],
              "relational_report": value["relational_report"],
              "join_request_raw": join_raw, "expected_join_request_sha256": sha(join_raw),
              **value["kwargs"]}
    return {"example_request_raw": raw, "expected_example_request_sha256": sha(raw),
            "expected_join_report_sha256": fixtures.subject.source_typed_norm_join_sha256(fixtures.prepare(value)),
            "join_replay_inputs": replay, "codec": codec,
            "expected_codec_sha256": target_codec.relational_target_codec_sha256(codec)}


@pytest.fixture(scope="module")
def base():
    value = fixtures.case()
    return value, fixtures.prepare(value)


def prepare(value, join_report, *, request=None, changes=None):
    kwargs = arguments(value, request=request)
    if changes:
        kwargs.update(changes)
    return subject.prepare_relational_decoder_example_v1(join_report, **kwargs)


def replay(report, value, join_report, *, request=None, changes=None):
    kwargs = arguments(value, request=request)
    if changes:
        kwargs.update(changes)
    return subject.validate_relational_decoder_example_v1(report, join_report,
        expected_report_sha256=subject.relational_decoder_example_sha256(report), **kwargs)


def assert_zero_eligibility(report):
    assert report["split"] == "unassigned"
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0
    assert not any(report["authority"].values())


def test_public_import_and_report_digest_need_no_operation_owners(monkeypatch):
    module = ModuleType("_cold_relational_decoder_example_contract")
    module.__file__ = subject.__file__
    monkeypatch.setitem(sys.modules, module.__name__, module)
    original_import = builtins.__import__
    attempts = []

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"ipfs_datasets_py", "torch", "numpy", "transformers",
                                  "requests", "pyarrow", "duckdb", "cryptography"}:
            attempts.append(name)
            raise AssertionError("operation owner imported by pure example boundary")
        return original_import(name, *args, **kwargs)

    source = Path(subject.__file__).read_bytes()
    with monkeypatch.context() as context:
        context.setattr(builtins, "__import__", guarded)
        exec(compile(source, module.__file__, "exec"), module.__dict__)
        assert len(module.relational_decoder_example_sha256({"ordinary": True})) == 64
    assert attempts == []


def test_actual_public_join_replay_separates_exact_source_input_and_complete_typed_label(base):
    value, join_report = deepcopy(base)
    before = deepcopy((value, join_report))
    report = prepare(value, join_report)
    assert replay(report, value, join_report) == report
    assert report["status"] == "candidate_target_prepared"
    assert report["model_input"] == value["scope_report"]["scope_request"]
    assert set(report["model_input"]) == {"source_text", "context"}
    assert report["source_input_sha256"] == sha(wire(report["model_input"]))
    assert report["source_group_sha256"] == sha(wire(report["source_identity"]))
    label = report["label"]
    assert label["request_raw_utf8"].encode() == value["kwargs"]["relational_request_raw"]
    assert label["request_raw_sha256"] == sha(value["kwargs"]["relational_request_raw"])
    assert label["relational_report_sha256"] == value["kwargs"]["expected_relational_report_sha256"]
    assert label["encoding"]["relational_owner_report_sha256"] == label["relational_report_sha256"]
    assert label["encoding"]["producer_pins"].items() <= report["producer_pins"].items()
    assert json.loads(label["encoding"]["canonical_request_raw_utf8"])["expression"] == value["relational_report"]["typed_expression"]
    assert label["encoding"]["target_ids"] == [1, *(3 + b for b in
        label["encoding"]["canonical_request_raw_utf8"].encode()), 2]
    provenance = report["provenance"]
    for key in ("component_id", "alternative_id", "original_unresolved", "introduced_unresolved", "provenance_ledger"):
        assert provenance[key] == join_report[key]
    assert provenance["source_context_packet"] == value["scope_report"]["source_context_packet"]
    assert provenance["source_context_declaration"] == value["scope_report"]["source_records"]["context"]
    assert provenance["exposure_status"] == "exposed" and provenance["exposure_status_caller_declared"]
    assert report["embedding_reference"] is None and report["embedding_reference_declaration_only"]
    assert (value, join_report) == before
    assert_zero_eligibility(report)


@pytest.mark.parametrize("dimension", [8, 384, 768])
def test_declared_embedding_channels_do_not_change_source_group_or_authenticate_payloads(base, dimension):
    value, join_report = deepcopy(base)
    reference = embedding_reference(value, dimension)
    request = example_request(reference)
    before = deepcopy((value, join_report, request))
    original = prepare(value, join_report)
    report = prepare(value, join_report, request=request)
    assert replay(report, value, join_report, request=request) == report
    assert report["embedding_reference"] == reference
    assert report["model_input"] == original["model_input"]
    assert report["source_identity"] == original["source_identity"]
    assert report["source_group_sha256"] == original["source_group_sha256"]
    assert report["label"] == original["label"]
    assert report["embedding_reference_declaration_only"]
    for key in ("embedding_payload_verified", "embedding_producer_verified", "embedding_source_independence_verified"):
        assert report["authority"][key] is False
    assert (value, join_report, request) == before
    assert_zero_eligibility(report)


def test_alternative_typed_interpretations_share_source_input_and_physical_group(base):
    value, join_report = deepcopy(base)
    first = prepare(value, join_report)
    changed = fixtures.case(operator="O")
    changed["join_request"]["component_id"] = "fixture:alternative-component"
    changed["join_request"]["alternative_id"] = "fixture:alternative-hypothesis"
    second = prepare(changed, fixtures.prepare(changed))
    assert second["model_input"] == first["model_input"]
    assert second["source_identity"] == first["source_identity"]
    assert second["source_group_sha256"] == first["source_group_sha256"]
    assert second["label"]["encoding"]["target_ids"] != first["label"]["encoding"]["target_ids"]
    assert second["provenance"]["component_id"] != first["provenance"]["component_id"]
    assert second["provenance"]["alternative_id"] != first["provenance"]["alternative_id"]
    assert_zero_eligibility(first)
    assert_zero_eligibility(second)


def test_identical_text_at_two_real_physical_occurrences_has_distinct_group():
    source = fixtures.source_case(duplicate=True)
    left_source, right_source = deepcopy(source), deepcopy(source)
    left_source["unit"], right_source["unit"] = source["units"][0], source["units"][1]
    left, right = fixtures.case(source=left_source), fixtures.case(source=right_source)
    first, second = prepare(left, fixtures.prepare(left)), prepare(right, fixtures.prepare(right))
    assert first["model_input"] == second["model_input"]
    assert first["source_identity"]["raw_html_sha256"] == second["source_identity"]["raw_html_sha256"]
    assert first["source_identity"]["span_sha256"] == second["source_identity"]["span_sha256"]
    assert first["source_identity"]["start_char"] != second["source_identity"]["start_char"]
    assert first["source_group_sha256"] != second["source_group_sha256"]


def test_pending_source_retains_original_context_and_manufactures_no_label():
    value = fixtures.case(source_only=True)
    join_report = fixtures.prepare(value)
    report = prepare(value, join_report, request=example_request(exposure="unknown"))
    assert replay(report, value, join_report, request=example_request(exposure="unknown")) == report
    assert report["status"] == "source_only_pending_target" and report["label"] is None
    assert report["model_input"] == value["scope_report"]["scope_request"]
    assert report["provenance"]["original_unresolved"] == join_report["original_unresolved"]
    assert report["provenance"]["introduced_unresolved"] == []
    assert report["provenance"]["provenance_ledger"] == []
    assert report["provenance"]["exposure_status"] == "unknown"
    assert_zero_eligibility(report)


@pytest.mark.parametrize("damage", ["dimension", "bool_dimension", "source_input", "token_limit", "payload_bytes", "payload_path"])
def test_embedding_reference_is_closed_dimension_checked_and_source_bound(base, damage, monkeypatch):
    value, join_report = deepcopy(base)
    reference = embedding_reference(value, 384)
    if damage == "dimension": reference["dimension"] = 786
    elif damage == "bool_dimension": reference["dimension"] = True
    elif damage == "source_input": reference["source_input_sha256"] = "0" * 64
    elif damage == "token_limit": reference["token_limit"] = True
    elif damage == "payload_bytes": reference["payload_bytes"] = 0
    else: reference["path"] = "/not/an/embedding/payload"
    kwargs = arguments(value, request=example_request(reference))
    if damage != "source_input":
        monkeypatch.setattr(subject, "_owners", lambda: pytest.fail("owner loaded before malformed reference refusal"))
    with pytest.raises(ValueError): subject.prepare_relational_decoder_example_v1(join_report, **kwargs)


@pytest.mark.parametrize("damage", ["example_pin", "join_pin", "codec_pin", "duplicate_json", "heldout_claim", "request_extra", "missing_replay", "raw_html", "raw_bytecount"])
def test_closed_inputs_and_original_commitments_refuse_before_owner_import(base, damage, monkeypatch):
    value, join_report = deepcopy(base)
    kwargs = arguments(value)
    if damage == "example_pin": kwargs["expected_example_request_sha256"] = "0" * 64
    elif damage == "join_pin": kwargs["expected_join_report_sha256"] = "0" * 64
    elif damage == "codec_pin": kwargs["expected_codec_sha256"] = "0" * 64
    elif damage == "duplicate_json":
        kwargs["example_request_raw"] = b'{"schema":1,"schema":2}'
        kwargs["expected_example_request_sha256"] = sha(kwargs["example_request_raw"])
    elif damage in ("heldout_claim", "request_extra"):
        request = example_request(exposure="held_out") if damage == "heldout_claim" else {**example_request(), "target": {"accepted": True}}
        kwargs["example_request_raw"] = wire(request)
        kwargs["expected_example_request_sha256"] = sha(kwargs["example_request_raw"])
    elif damage == "missing_replay": kwargs["join_replay_inputs"].pop("scope_replay_inputs")
    elif damage == "raw_html": kwargs["join_replay_inputs"]["scope_replay_inputs"]["raw_html"] += b" "
    else: kwargs["join_replay_inputs"]["scope_replay_inputs"]["expected_raw_bytes"] += 1
    monkeypatch.setattr(subject, "_owners", lambda: pytest.fail("owner loaded before failed closed preflight"))
    with pytest.raises(ValueError): subject.prepare_relational_decoder_example_v1(join_report, **kwargs)


@pytest.mark.parametrize("damage", ["source_report", "relational_report", "join_provenance"])
def test_resealed_inputs_cannot_replace_original_public_replay(base, damage):
    value, join_report = deepcopy(base)
    kwargs = arguments(value)
    if damage == "source_report":
        kwargs["join_replay_inputs"]["scope_report"]["scope_request"]["source_text"] += " invented"
        kwargs["join_replay_inputs"]["expected_scope_report_sha256"] = fixtures.source_scope.sampled_norm_scope_report_sha256(value["scope_report"])
    elif damage == "relational_report":
        value["relational_report"]["argument_roles"][0]["roles"].reverse()
        kwargs["join_replay_inputs"]["expected_relational_report_sha256"] = fixtures.relational.relational_norm_report_sha256(value["relational_report"])
    else:
        join_report["provenance_ledger"].pop()
        kwargs["expected_join_report_sha256"] = fixtures.subject.source_typed_norm_join_sha256(join_report)
    with pytest.raises(ValueError): subject.prepare_relational_decoder_example_v1(join_report, **kwargs)


@pytest.mark.parametrize("damage", ["target_in_input", "source_text", "label", "source_group", "authority", "mask", "split", "encoding_producer_pin"])
def test_resealed_example_rejects_target_leakage_substituted_labels_and_promotion(base, damage):
    value, join_report = deepcopy(base)
    report = prepare(value, join_report)
    if damage == "target_in_input": report["model_input"]["target"] = deepcopy(report["label"])
    elif damage == "source_text": report["model_input"]["source_text"] += " invented"
    elif damage == "label": report["label"]["encoding"]["target_ids"][1] = 3 + ord("[")
    elif damage == "source_group": report["source_group_sha256"] = "0" * 64
    elif damage == "authority": report["authority"]["training_qualified"] = True
    elif damage == "mask": report["training_mask"] = 1
    elif damage == "split": report["split"] = "test"
    else:
        path = next(path for path in report["label"]["encoding"]["producer_pins"]
                    if path.endswith("/logic/syntax_core/codec.py"))
        assert path not in join_report["producer_pins"]
        report["producer_pins"].pop(path)
    with pytest.raises(ValueError): replay(report, value, join_report)


def test_encoding_callback_cannot_replace_the_replayed_relational_report_identity(base, monkeypatch):
    value, join_report = deepcopy(base)
    kwargs = arguments(value)
    original = target_codec.encode_relational_target_v1
    observed = []

    def changed(*args, **options):
        encoding = original(*args, **options)
        assert encoding["relational_owner_report_sha256"] == value["kwargs"]["expected_relational_report_sha256"]
        observed.append(encoding["relational_owner_report_sha256"])
        encoding["relational_owner_report_sha256"] = "0" * 64
        return encoding

    monkeypatch.setattr(target_codec, "encode_relational_target_v1", changed)
    with pytest.raises(ValueError):
        subject.prepare_relational_decoder_example_v1(join_report, **kwargs)
    assert observed == [value["kwargs"]["expected_relational_report_sha256"]]


def test_owner_callback_mutation_of_original_source_is_refused_after_replay(base, monkeypatch):
    value, join_report = deepcopy(base)
    kwargs = arguments(value)
    original = fixtures.subject.validate_source_typed_norm_join_v1

    def changed(*args, **options):
        result = original(*args, **options)
        value["scope_report"]["scope_request"]["source_text"] += " mutation after owner replay"
        return result

    monkeypatch.setattr(fixtures.subject, "validate_source_typed_norm_join_v1", changed)
    with pytest.raises(ValueError, match="inputs changed"):
        subject.prepare_relational_decoder_example_v1(join_report, **kwargs)
