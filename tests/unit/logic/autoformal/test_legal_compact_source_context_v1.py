"""Authored lexical context nominations, never statutory meanings or gold.

These tests use real compact-context and token owners. Catalogs are explicitly
authored fixtures; exact textual matches establish only byte-level nominations.
No model, training, provider, solver, or Lean execution is part of this suite.
"""
from copy import deepcopy
import hashlib
import inspect
import json
import re
import unicodedata

import pytest

from ipfs_datasets_py.logic.autoformal import legal_compact_source_context_v1 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as tokens
from ipfs_datasets_py.logic.syntax_core import signatures


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def catalog(entries=None):
    """Independent authored vocabulary; no expected formula is consulted."""
    entries = entries or [("Retain", ("holder", "record"), ("retain",)),
        ("Inspect", ("inspector", "record"), ("inspect",)),
        ("Approve", ("approver", "request"), ("approve",))]
    obj = signatures.LogicSort("Object")
    signature = signatures.LogicSignature("authored-source-catalog", family="tdfol",
        profile="tdfol_default", sorts=(obj,), symbols=tuple(
            signatures.declare_predicate(name, (obj,) * len(roles)) for name, roles, _ in entries))
    return {"schema": "legal-compact-source-catalog/v1", "signature": signature.to_dict(),
        "argument_roles": [{"symbol": name, "roles": list(roles)} for name, roles, _ in entries],
        "aliases": [{"symbol": name, "forms": list(forms)} for name, _, forms in entries]}


def prepare(source, declared=None):
    raw = source.encode("utf-8") if isinstance(source, str) else source
    encoded = wire(catalog() if declared is None else declared)
    return subject.prepare_source_context_v1(raw, encoded,
        expected_source_sha256=sha(raw), expected_catalog_sha256=sha(encoded))


def no_authority(report):
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert report["origin"] == "caller_supplied_unverified"
    assert report["masks"] == {"semantic": 0, "training": 0, "inference_permission": 0}
    assert all(type(value) is int for value in report["masks"].values())
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0


def framed_ids(content, codec):
    """Independent JSON lexical spelling, with no expected target at inference."""
    text = wire(content).decode("utf-8")
    pieces = re.findall(r'"(?:[^"\\]|\\.)*"|0|[1-9][0-9]*|[{}\[\],:]', text)
    assert "".join(pieces) == text
    table = {token: index for index, token in enumerate(codec["vocabulary"])}
    return [codec["bos_id"], *(table[piece] for piece in pieces), codec["eos_id"]]


def one_predicate_content(index=0, letter="P"):
    return {"schema": "legal-relational-compact-content/v1", "tree": ["forall", 0,
        ["forall", 1, ["extension", letter, ["predicate", index, [["variable", 0], ["variable", 1]]]]]]}


def test_source_nomination_emits_usable_context_with_complete_authored_evidence(tmp_path):
    source = b"An auditor may inspect records."
    declared = catalog()
    original = deepcopy(declared)
    report = prepare(source, declared)
    assert report["schema"] == "legal-compact-source-context/v1" and report["status"] == "nominated"
    assert report["source_sha256"] == sha(source) and report["catalog_sha256"] == sha(wire(declared))
    assert report["source_geometry"] == {"encoding": "UTF-8", "byte_length": len(source),
        "character_length": len(source.decode())}
    assert report["catalog_symbol_count"] == report["catalog_form_count"] == 3
    assert report["selected_symbols"] == report["matched_symbols"] == ["Inspect"]
    assert report["excluded_symbols"] == ["Retain", "Approve"]
    assert report["index_mapping"] == [{"symbol": "Inspect", "catalog_index": 1, "selected_index": 0}]
    assert report["aliases"] == declared["aliases"] and declared == original
    assert report["ambiguities"] == []
    assert report["matching_policy"] == {
        "case_sensitive": True,
        "normalization": "none",
        "word_characters": "Unicode categories L,N,M,Pc and U+200C,U+200D",
        "unicode_database_version": unicodedata.unidata_version,
        "left_boundary": "required when the alias begins with a word character",
        "right_boundary": "required when the alias ends with a word character",
        "overlapping_occurrences": "preserve all",
        "match_order": "start_byte,end_byte,form",
        "ambiguity": "observed identical form assigned to multiple predicates",
    }
    no_authority(report)
    context = report["context"]
    assert [item["name"] for item in context["signature"]["symbols"]] == ["Inspect"]
    assert context["argument_roles"] == [{"symbol": "Inspect", "roles": ["inspector", "record"]}]
    context_raw = wire(context)
    assert report["context_sha256"] == sha(context_raw)
    codec = tokens.build_compact_content_token_codec_v1()
    codec_sha = tokens.compact_content_token_codec_sha256(codec)
    options = {"expected_context_sha256": sha(context_raw), "codec": codec, "expected_codec_sha256": codec_sha}
    prefix = tokens.compact_content_allowed_token_ids_v1([], context_raw, **options)
    assert prefix["status"] == "empty" and prefix["allowed_token_ids"] == [codec["bos_id"]]
    # This formula is separately authored to test the emitted context. It is
    # never an input to the source nomination, and is not a learned prediction.
    formula = one_predicate_content()
    ids = framed_ids(formula, codec)
    decoded = tokens.decode_compact_content_tokens_v1(ids, context_raw, **options)
    assert decoded["status"] == "valid_candidate"
    assert decoded["prediction"]["request"]["argument_roles"] == context["argument_roles"]
    assert decoded["prediction"]["request"]["source_binding"] is None
    assert decoded["prediction"]["identity_mode"] == "generated"
    assert all(value is False for value in decoded["authority"].values())
    assert decoded["training_mask"] == decoded["evaluation_gold_mask"] == 0
    root = tmp_path / "authored-source-context"
    root.mkdir()
    (root / "source.txt").write_bytes(source)
    for name, value in (("catalog.json", declared), ("report.json", report), ("context.json", context),
            ("codec.json", codec), ("prefix.json", prefix), ("formula.json", formula),
            ("generated-ids.json", ids), ("decoded.json", decoded),
            ("scope.json", {"sources": "authored engineering fixture", "formula": "separately authored decoder control",
                "model_executed": False, "statutory_meaning_verified": False, "training_executed": False,
                "inference_permission_verified": False, "held_out_accuracy_measured": False})):
        (root / name).write_bytes(wire(value) + b"\n")


def test_signature_and_argument_role_order_survive_alias_and_role_row_permutations():
    declared = catalog()
    declared["aliases"].reverse()
    declared["argument_roles"].reverse()
    declared["argument_roles"][2]["roles"] = ["record", "holder"]
    report = prepare("inspect then retain", declared)
    assert report["selected_symbols"] == ["Retain", "Inspect"]
    assert report["index_mapping"] == [{"symbol": "Retain", "catalog_index": 0, "selected_index": 0},
        {"symbol": "Inspect", "catalog_index": 1, "selected_index": 1}]
    assert report["aliases"] == declared["aliases"]
    assert report["context"]["argument_roles"] == [
        {"symbol": "Inspect", "roles": ["inspector", "record"]},
        {"symbol": "Retain", "roles": ["record", "holder"]},
    ]
    assert [item["name"] for item in report["context"]["signature"]["symbols"]] == ["Retain", "Inspect"]
    no_authority(report)


def test_multiple_selected_predicates_still_require_all_predicates_in_decoded_content():
    report = prepare("retain and inspect")
    raw = wire(report["context"])
    codec = tokens.build_compact_content_token_codec_v1()
    decoded = tokens.decode_compact_content_tokens_v1(framed_ids(one_predicate_content(index=1), codec), raw,
        expected_context_sha256=sha(raw), codec=codec, expected_codec_sha256=tokens.compact_content_token_codec_sha256(codec))
    assert decoded["status"] == "rejected" and decoded["prediction"] is None
    assert report["selected_symbols"] == ["Retain", "Inspect"]


def test_unicode_matches_retain_exact_character_and_utf8_coordinates():
    text = "Élodie 🦊 inspect café; inspect."
    declared = catalog([("Inspect", ("inspector", "record"), ("inspect", "café"))])
    report = prepare(text, declared)
    assert report["status"] == "nominated" and len(report["matches"]) == 3
    expected = [(match.start(), match.end(), match.group()) for match in re.finditer("inspect|café", text)]
    actual = sorted((item["start_char"], item["end_char"], item["form"]) for item in report["matches"])
    assert actual == expected
    raw = text.encode("utf-8")
    for item in report["matches"]:
        assert item["symbols"] == ["Inspect"]
        assert item["start_byte"] == len(text[:item["start_char"]].encode("utf-8"))
        assert item["end_byte"] == len(text[:item["end_char"]].encode("utf-8"))
        assert raw[item["start_byte"]:item["end_byte"]] == item["form"].encode("utf-8")
        assert text[item["start_char"]:item["end_char"]] == item["form"]


def test_exact_case_sensitive_word_boundaries_do_not_stem_or_match_word_interior():
    text = "inspects INSPECT reinspect _inspect inspect_2 éinspect inspecté (inspect) inspect–inspect"
    report = prepare(text)
    starts = [match.start() for match in re.finditer(r"(?<!\w)inspect(?!\w)", text)]
    assert len(starts) == 3
    assert sorted(item["start_char"] for item in report["matches"]) == starts
    assert {item["form"] for item in report["matches"]} == {"inspect"}


def test_literal_metacharacters_and_overlapping_alias_occurrences_are_preserved():
    declared = catalog([("Inspect", ("inspector", "record"), ("a+b", "a a")),
        ("Retain", ("holder", "record"), ("a a a",))])
    text = "aab a+b a a a"
    report = prepare(text, declared)
    observed = {(item["form"], item["start_char"], item["end_char"]) for item in report["matches"]}
    assert observed == {("a+b", 4, 7), ("a a", 8, 11), ("a a", 10, 13), ("a a a", 8, 13)}
    assert report["selected_symbols"] == ["Inspect", "Retain"] and report["ambiguities"] == []


def test_combining_marks_are_not_normalized_and_do_prevent_partial_word_matches():
    declared = catalog([("Inspect", ("inspector", "record"), ("café",))])
    report = prepare("cafe\u0301", declared)
    assert report["status"] == "unavailable" and report["matches"] == []
    declared["aliases"][0]["forms"] = ["cafe"]
    report = prepare("cafe\u0301", declared)
    assert report["status"] == "unavailable" and report["matches"] == []
    declared["aliases"][0]["forms"] = ["cafe\u0301"]
    report = prepare("cafe\u0301", declared)
    assert report["status"] == "nominated"
    assert [(item["start_char"], item["end_char"], item["start_byte"], item["end_byte"])
        for item in report["matches"]] == [(0, 5, 0, 6)]
    no_authority(report)


def test_marks_connectors_and_join_controls_block_matches_on_both_sides():
    # These marks and controls are not all recognized by Python regex \w.
    # The source bridge declares them continuations and keeps literal bytes.
    for continuation in ("\u0301", "\u093e", "\u20dd", "\u203f", "\u200c", "\u200d"):
        report = prepare(continuation + "inspect inspect" + continuation)
        assert report["status"] == "unavailable" and report["matches"] == [], repr(continuation)
        no_authority(report)


def test_shared_observed_form_is_ambiguous_and_no_favorable_subset_is_selected():
    declared = catalog([("Retain", ("holder", "record"), ("act", "retain")),
        ("Inspect", ("inspector", "record"), ("act", "inspect"))])
    report = prepare("inspect, act, act", declared)
    assert report["status"] == "ambiguous"
    assert report["matched_symbols"] == ["Retain", "Inspect"]
    assert report["ambiguities"] == [{"form": "act", "symbols": ["Retain", "Inspect"]}]
    assert len(report["matches"]) == 3
    assert [item["symbols"] for item in report["matches"] if item["form"] == "act"] == [
        ["Retain", "Inspect"], ["Retain", "Inspect"]]
    assert report["context"] is None and report["context_sha256"] is None
    assert report["selected_symbols"] == report["index_mapping"] == []
    assert report["excluded_symbols"] == ["Retain", "Inspect"]
    no_authority(report)


def test_shared_unobserved_form_does_not_block_an_unambiguous_match():
    declared = catalog([("Retain", ("holder", "record"), ("act", "retain")),
        ("Inspect", ("inspector", "record"), ("act", "inspect"))])
    report = prepare("inspect", declared)
    assert report["status"] == "nominated" and report["selected_symbols"] == ["Inspect"]
    assert report["ambiguities"] == []


def test_no_match_retains_catalog_without_inventing_context():
    declared = catalog()
    report = prepare("There is no matching vocabulary here.", declared)
    assert report["status"] == "unavailable"
    assert report["context"] is None and report["context_sha256"] is None
    assert report["selected_symbols"] == report["matched_symbols"] == report["matches"] == []
    assert report["excluded_symbols"] == ["Retain", "Inspect", "Approve"]
    assert report["aliases"] == declared["aliases"]
    no_authority(report)


def test_full_catalog_is_validated_even_when_invalid_predicate_has_no_source_match():
    declared = catalog()
    declared["signature"]["symbols"][0]["metadata"] = {"unreviewed": True}
    with pytest.raises(ValueError):
        prepare("inspect", declared)
    with pytest.raises(ValueError):
        prepare("nothing matches", declared)


def test_preparation_and_replay_are_detached_deterministic_and_bound_to_original_bytes():
    source, encoded = b"inspect", wire(catalog())
    options = {"expected_source_sha256": sha(source), "expected_catalog_sha256": sha(encoded)}
    report = subject.prepare_source_context_v1(source, encoded, **options)
    original = deepcopy(report)
    replayed = subject.validate_source_context_v1(report, source, encoded,
        expected_report_sha256=subject.source_context_sha256(report), **options)
    assert replayed == report == original and replayed is not report
    assert subject.source_context_sha256(report) == sha(wire(report))
    replayed["matches"].clear()
    assert report == original


@pytest.mark.parametrize("field", ["span", "role", "authority"])
def test_resealed_report_changes_cannot_replace_original_bound_regeneration(field):
    source, encoded = b"inspect", wire(catalog())
    report = subject.prepare_source_context_v1(source, encoded,
        expected_source_sha256=sha(source), expected_catalog_sha256=sha(encoded))
    if field == "span":
        report["matches"][0]["start_byte"] += 1
    elif field == "role":
        report["context"]["argument_roles"][0]["roles"].reverse()
    else:
        report["authority"][next(iter(report["authority"]))] = True
    with pytest.raises(ValueError):
        subject.validate_source_context_v1(report, source, encoded,
            expected_report_sha256=sha(wire(report)),
            expected_source_sha256=sha(source), expected_catalog_sha256=sha(encoded))


@pytest.mark.parametrize("pin", ["source", "catalog"])
def test_independent_raw_input_hash_mismatch_is_rejected(pin):
    source, encoded = b"inspect", wire(catalog())
    with pytest.raises(ValueError):
        subject.prepare_source_context_v1(source, encoded,
            expected_source_sha256="0" * 64 if pin == "source" else sha(source),
            expected_catalog_sha256="0" * 64 if pin == "catalog" else sha(encoded))


@pytest.mark.parametrize("change", ["duplicate_alias_row", "missing_alias_row", "unknown_symbol",
    "duplicate_form", "empty_forms", "whitespace_form", "missing_role_row", "wrong_arity", "extra_target"])
def test_catalog_shape_refusals_preserve_complete_typed_contract(change):
    declared = catalog()
    if change == "duplicate_alias_row":
        declared["aliases"].append(deepcopy(declared["aliases"][0]))
    elif change == "missing_alias_row":
        declared["aliases"].pop()
    elif change == "unknown_symbol":
        declared["aliases"][0]["symbol"] = "Unknown"
    elif change == "duplicate_form":
        declared["aliases"][0]["forms"] = ["retain", "retain"]
    elif change == "empty_forms":
        declared["aliases"][0]["forms"] = []
    elif change == "whitespace_form":
        declared["aliases"][0]["forms"] = [" \t\u00a0"]
    elif change == "missing_role_row":
        declared["argument_roles"].pop()
    elif change == "wrong_arity":
        declared["argument_roles"][0]["roles"] = ["holder"]
    else:
        declared["expected_formula"] = one_predicate_content()
    with pytest.raises(ValueError):
        prepare("inspect", declared)


@pytest.mark.parametrize("raw", [b"", b"\xff", b"x" * 65537, "inspect", bytearray(b"inspect")])
def test_source_transport_refuses_empty_invalid_oversized_and_nonimmutable_inputs(raw):
    encoded = wire(catalog())
    expected = sha(raw) if isinstance(raw, (bytes, bytearray)) else "0" * 64
    with pytest.raises(ValueError):
        subject.prepare_source_context_v1(raw, encoded,
            expected_source_sha256=expected, expected_catalog_sha256=sha(encoded))


@pytest.mark.parametrize("kind", ["duplicate_json_key", "nonfinite", "extra_bytes", "nonbytes"])
def test_catalog_transport_refuses_unsafe_json_and_bytes(kind):
    raw = wire(catalog())
    if kind == "duplicate_json_key":
        raw = raw[:-1] + b',"schema":"legal-compact-source-catalog/v1"}'
    elif kind == "nonfinite":
        raw = raw[:-1] + b',"extra":NaN}'
    elif kind == "extra_bytes":
        raw += b" {}"
    else:
        raw = bytearray(raw)
    with pytest.raises(ValueError):
        subject.prepare_source_context_v1(b"inspect", raw,
            expected_source_sha256=sha(b"inspect"), expected_catalog_sha256=sha(raw))


def test_complete_form_and_match_bounds_refuse_without_truncating():
    too_many_forms = catalog([("Inspect", ("inspector", "record"), tuple("alias" + str(index) for index in range(257)))])
    with pytest.raises(ValueError):
        prepare("inspect", too_many_forms)
    declared = catalog([("Inspect", ("inspector", "record"), ("a",))])
    source = "a " * 4097
    assert len(source.encode()) < 65536
    with pytest.raises(ValueError):
        prepare(source, declared)


def test_public_preparation_api_has_no_target_or_prediction_input():
    assert list(inspect.signature(subject.prepare_source_context_v1).parameters) == [
        "source_raw", "catalog_raw", "expected_source_sha256", "expected_catalog_sha256"]
