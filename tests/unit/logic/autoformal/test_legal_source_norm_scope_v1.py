"""Fictional scope custody and ambiguity tests; no legal target or review."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from ipfs_datasets_py.logic.autoformal import legal_source_norm_scope_v1 as subject
from ipfs_datasets_py.logic.autoformal import legal_source_sampling as sampler
from ipfs_datasets_py.logic.autoformal import legal_official_source_custody as custody
from ipfs_datasets_py.logic.autoformal.corpus_contracts import seal_record
from ipfs_datasets_py.logic.legal_ir import canonical_statement_scope as scope

_spec = importlib.util.spec_from_file_location(
    "_norm_scope_sampling_fixture", Path(__file__).with_name("test_legal_source_sampling.py"))
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def reference(record):
    return {"schema": record["schema"], "record_cid": record["record_cid"],
            "sha256": digest(record)}


def seal(declaration):
    declaration["content_sha256"] = digest(
        {key: value for key, value in declaration.items() if key != "content_sha256"})
    return declaration


def anchor(text, start, end):
    return {"origin": "source", "start": start, "end": end, "text": text[start:end],
            "offset_unit": "unicode_character_half_open"}


def case(*, duplicate=False, edition=2024, semantic_status="partial"):
    text = "Clérk may retain café records only with approval."
    paragraph = '<p class="statutory-body">' + text + "</p>"
    raw = _fixture.fixture(statute=paragraph * (2 if duplicate else 1), notes="")
    args = _fixture.inputs(raw)
    if edition != 2024:
        descriptor = args["descriptor"]
        descriptor["edition"] = edition
        for field in ("package_id", "granule_id", "url"):
            descriptor[field] = descriptor[field].replace("2024", str(edition))
        for field in ("requested_url", "final_url"):
            descriptor["http_provenance"][field] = descriptor["url"]
        args["expected_descriptor_sha256"] = custody.acquisition_descriptor_sha256(descriptor)
    report = sampler.prepare_source_sampling(raw, **args)
    units = [row for row in report["records"]
             if row["schema"] == sampler.UNIT_SCHEMA and row["candidate_input"]]
    request = {"source_text": text,
               "context": {"role": "required_unavailable", "text": "", "bindings": {},
                           "sha256": hashlib.sha256(b"").hexdigest()}}
    occurrences = []
    for identity, facet, literal, symbol in (
        ("actor", "actor", "Clérk", "Clérk"),
        ("modal", "modality", "may", "P"),
        ("action", "action", "retain", "retain"),
        ("object", "object", "café records", "café records"),
    ):
        start = text.index(literal)
        occurrences.append({"occurrence_id": identity, "facet": facet,
                            "canonical_symbol": symbol,
                            "anchor": anchor(text, start, start + len(literal))})
    issue_start = text.index("only with")
    declaration = {
        "schema": scope.SCHEMA, "family": "deontic", "profile": scope.PROFILE,
        "input": deepcopy(request), "input_sha256": digest(request),
        "occurrences": occurrences,
        "rules": [{"rule_id": "r1",
                   "body": {"actor": "actor", "modality": "modal", "action": "action", "object": "object"},
                   "qualifiers": {"conditions": None, "exceptions": None, "temporal": None}}],
        "statement_structure": {"op": "rule", "rule_id": "r1"}, "binders": [],
        "coverage": {"declared_status": semantic_status, "segments": [{
            "span": anchor(text, 0, len(text)), "disposition": "unresolved", "rule_ids": ["r1"],
            "occurrence_ids": [row["occurrence_id"] for row in occurrences],
            "reason": "Full fictional source retained; legal meaning remains unreviewed."}]},
        "unresolved": [{"code": "approval_necessity_unresolved",
                        "span": anchor(text, issue_start, len(text) - 1),
                        "reason": "No implication direction or sufficiency is decided."}],
    }
    return {"raw": raw, "sampling": report, "args": args, "request": request,
            "declaration": seal(declaration), "units": units, "unit": units[0]}


def preparation_inputs(value):
    request_raw, declaration_raw = wire(value["request"]), wire(value["declaration"])
    inputs = {
        "expected_sampling_report_sha256": sampler.source_sampling_report_sha256(value["sampling"]),
        "selected_unit_ref": reference(value["unit"]),
        "expected_scope_request_sha256": hashlib.sha256(request_raw).hexdigest(),
        "expected_scope_declaration_sha256": hashlib.sha256(declaration_raw).hexdigest(),
        **deepcopy(value["args"]),
    }
    return request_raw, declaration_raw, inputs


def prepare(value):
    request_raw, declaration_raw, inputs = preparation_inputs(value)
    return subject.prepare_sampled_norm_scope_v1(
        value["sampling"], value["raw"], request_raw, declaration_raw, **inputs)


def validate(report, value):
    request_raw, declaration_raw, inputs = preparation_inputs(value)
    return subject.validate_sampled_norm_scope_v1(
        report, value["sampling"], value["raw"], request_raw, declaration_raw,
        expected_report_sha256=subject.sampled_norm_scope_report_sha256(report), **inputs)


def refresh(value):
    declaration = value["declaration"]
    declaration["input"] = deepcopy(value["request"])
    declaration["input_sha256"] = digest(value["request"])
    seal(declaration)


def test_cold_public_import_loads_no_production_or_numerical_owner():
    script = r'''
import importlib.util, json, sys
blocked = ("ipfs_datasets_py", "multiformats", "cryptography", "torch", "numpy", "requests", "transformers", "pyarrow")
attempts = []
class Deny:
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == item or fullname.startswith(item + ".") for item in blocked):
            attempts.append(fullname)
            raise AssertionError(fullname)
sys.meta_path.insert(0, Deny())
spec = importlib.util.spec_from_file_location("_cold_norm_scope", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert not attempts
assert len(module.__all__) == 3
print(json.dumps({"operation_owner_import_attempts": attempts}))
'''
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", script, subject.__file__],
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"operation_owner_import_attempts": []}


@pytest.mark.parametrize("status", ["partial", "unassessed"])
def test_whole_source_transport_preserves_unreviewed_meaning_and_blocks_legacy_routes(status):
    value = case(semantic_status=status)
    report = prepare(value)
    receipt = validate(report, value)
    assert receipt["status"] == "validated_source_scope_transport_only"
    assert report["scope_request"] == value["request"]
    assert report["scope_declaration"] == value["declaration"]
    assert report["scope_bridge_view"]["payload"] == value["declaration"]
    assert report["scope_bridge_view"]["name"] == "statement_scope_v1"
    bridge_contract_owner = Path(scope.__file__).with_name("canonical_contracts.py").resolve()
    assert report["producer_pins"][str(bridge_contract_owner)] == hashlib.sha256(
        bridge_contract_owner.read_bytes()).hexdigest()
    assert report["source_records"]["unit"] == value["unit"]
    assert report["source_selector"]["text"] == value["request"]["source_text"]
    assert report["literal_accounting_complete"] is True
    assert report["declared_semantic_coverage"] == status
    assert report["original_context_preserved"] is True
    assert report["external_context_nominations_applied"] is False
    assert len(report["source_context_packet"]["dependency_slots"]) == 6
    assert all(row["status"] == "unavailable"
               for row in report["flat_compatibility"]["profiles"].values())
    assert report["flat_compatibility"]["byte_encoding_capacity"]["checked"] is False
    assert report["scope_bridge_validation"]["typed_bridge_created"] is False
    assert report["scope_bridge_validation"]["domain_logic_slice_projected"] is False
    for field in ("formal_norm_ast", "lowered_ir", "graph", "accepted_lookup", "governing_definition_use"):
        assert report[field] is None
    assert all(flag is False for flag in report["authority"].values())
    assert all(flag is False for flag in receipt["authority"].values())
    assert all(type(mask) is int and mask == 0 for mask in report["masks"].values())
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0
    assert report["model_calls"] == report["training_calls"] == report["native_processes"] == 0
    assert any("passive grammatical subject" in line for line in report["limitations"])
    assert any("not exhaustive" in line for line in report["limitations"])


def test_every_anchor_maps_unicode_locally_to_exact_original_document_utf8():
    value = case()
    report = prepare(value)
    text = value["sampling"]["document_view_report"]["document"]["document_text"]
    base = report["source_selector"]["char_start"]
    assert len(report["anchor_mappings"]) == 6  # Four roles, full accounting, one unresolved span.
    for row in report["anchor_mappings"]:
        local, mapped = row["local_anchor"], row["document_selector"]
        assert mapped["char_start"] == base + local["start"]
        assert mapped["char_end"] == base + local["end"]
        assert text[mapped["char_start"]:mapped["char_end"]] == local["text"]
        assert mapped["utf8_byte_start"] == len(text[:mapped["char_start"]].encode("utf-8"))
        assert mapped["utf8_byte_end"] == len(text[:mapped["char_end"]].encode("utf-8"))
    obj = next(row for row in report["anchor_mappings"] if row["declaration_path"] == "/occurrences/3/anchor")
    assert obj["document_selector"]["utf8_byte_start"] != obj["document_selector"]["char_start"]
    assert "/coverage/segments/0/span" in {row["declaration_path"] for row in report["anchor_mappings"]}
    assert "/unresolved/0/span" in {row["declaration_path"] for row in report["anchor_mappings"]}


def test_inputs_and_detached_output_cannot_mutate_each_other():
    value = case()
    before = deepcopy(value)
    report = prepare(value)
    assert value == before
    report["scope_request"]["source_text"] = "changed export"
    report["source_records"]["unit"]["ordinal"] = 999
    assert value == before
    assert prepare(value)["scope_declaration"] == before["declaration"]


def test_same_text_at_different_occurrences_is_not_an_interchangeable_selected_unit():
    value = case(duplicate=True)
    first = prepare(value)
    value["unit"] = value["units"][1]
    second = prepare(value)
    assert first["source_selector"]["text"] == second["source_selector"]["text"]
    assert first["source_selector"]["occurrence_id"] != second["source_selector"]["occurrence_id"]
    assert first["source_records"]["source_occurrence"]["record_cid"] != second["source_records"]["source_occurrence"]["record_cid"]
    with pytest.raises(ValueError, match="authoritative regeneration"):
        validate(first, value)


def test_same_raw_text_in_a_different_declared_edition_does_not_substitute():
    original, changed = case(), case(edition=2023)
    report = prepare(original)
    assert original["raw"] == changed["raw"]
    assert original["unit"]["source_version_ref"] != changed["unit"]["source_version_ref"]
    with pytest.raises(ValueError, match="authoritative regeneration"):
        validate(report, changed)
    request_raw, declaration_raw, inputs = preparation_inputs(changed)
    inputs["selected_unit_ref"] = reference(original["unit"])
    with pytest.raises(ValueError, match="unit reference absent"):
        subject.prepare_sampled_norm_scope_v1(
            changed["sampling"], changed["raw"], request_raw, declaration_raw, **inputs)


@pytest.mark.parametrize("damage", ["suffix", "leading_gap", "middle_gap", "complete", "missing_issues", "context", "context_text", "anchor_geometry", "bool_anchor", "orphan_anchor"])
def test_repaired_caller_hashes_do_not_qualify_incomplete_or_forged_scope(damage):
    value = case()
    declaration = value["declaration"]
    text = value["request"]["source_text"]
    segment = declaration["coverage"]["segments"][0]
    if damage == "suffix":
        segment["span"] = anchor(text, 0, len(text) - 1)
    elif damage == "leading_gap":
        segment["span"] = anchor(text, 1, len(text))
        segment["occurrence_ids"] = []
    elif damage == "middle_gap":
        segment["span"] = anchor(text, 0, 5)
        segment["occurrence_ids"] = ["actor"]
        tail = deepcopy(segment)
        tail["span"] = anchor(text, 6, len(text))
        tail["occurrence_ids"] = ["modal", "action", "object"]
        declaration["coverage"]["segments"].append(tail)
    elif damage == "complete":
        declaration["coverage"]["declared_status"] = "complete"
    elif damage == "missing_issues":
        declaration["unresolved"] = []
    elif damage == "context":
        value["request"]["context"]["role"] = "none_required"
    elif damage == "context_text":
        value["request"]["context"].update(role="declared_context", text="Nomination is not applied context.",
            sha256=hashlib.sha256(b"Nomination is not applied context.").hexdigest())
    elif damage == "anchor_geometry":
        declaration["occurrences"][0]["anchor"]["end"] += 1
    elif damage == "bool_anchor":
        declaration["occurrences"][0]["anchor"]["start"] = False
    elif damage == "orphan_anchor":
        declaration["occurrences"].append(deepcopy(declaration["occurrences"][0]))
        declaration["occurrences"][-1]["occurrence_id"] = "unattached"
    refresh(value)
    with pytest.raises(ValueError):
        prepare(value)


def test_shortening_source_request_and_resealing_all_caller_checksums_is_refused():
    value = case()
    value["request"]["source_text"] = "Clérk may retain café records"
    text = value["request"]["source_text"]
    value["declaration"]["coverage"]["segments"][0]["span"] = anchor(text, 0, len(text))
    value["declaration"]["unresolved"][0]["span"] = anchor(text, 0, len(text))
    refresh(value)
    with pytest.raises(ValueError, match="complete selected source paragraph"):
        prepare(value)


def test_literal_accounting_accepts_mixed_dispositions_and_overlap_without_semantic_promotion():
    value = case()
    declaration = value["declaration"]
    text = value["request"]["source_text"]
    cut = text.index("only with")
    declaration["coverage"]["segments"] = [
        {"span": anchor(text, 0, cut), "disposition": "represented", "rule_ids": ["r1"],
         "occurrence_ids": [row["occurrence_id"] for row in declaration["occurrences"]],
         "reason": "Lexical role proposals alone; no verified semantics."},
        {"span": anchor(text, cut, len(text)), "disposition": "unresolved", "rule_ids": [],
         "occurrence_ids": [], "reason": "Approval relation remains unresolved."},
        {"span": anchor(text, cut - 1, cut + 3), "disposition": "unsupported", "rule_ids": [],
         "occurrence_ids": [], "reason": "An overlapping issue span need not form a partition."},
    ]
    refresh(value)
    report = prepare(value)
    assert report["literal_accounting_complete"] is True
    assert report["declared_semantic_coverage"] == "partial"
    assert report["scope_declaration"]["coverage"] == declaration["coverage"]
    assert report["authority"]["formal_norm_semantics_encoded"] is False


@pytest.mark.parametrize("replacement", [0, True, {"ordinal": 2}, {"schema": sampler.UNIT_SCHEMA, "record_cid": "not-a-cid", "sha256": "0" * 64}])
def test_ordinal_or_invented_reference_is_not_a_selected_sealed_unit(replacement):
    value = case()
    request_raw, declaration_raw, inputs = preparation_inputs(value)
    inputs["selected_unit_ref"] = replacement
    with pytest.raises(ValueError):
        subject.prepare_sampled_norm_scope_v1(
            value["sampling"], value["raw"], request_raw, declaration_raw, **inputs)


def test_control_unit_cannot_be_promoted_to_a_complete_statute_paragraph():
    value = case()
    control = next(row for row in value["sampling"]["records"]
                   if row["schema"] == sampler.UNIT_SCHEMA and not row["candidate_input"])
    value["unit"] = control
    with pytest.raises(ValueError, match="candidate statute paragraph"):
        prepare(value)


@pytest.mark.parametrize("damage", ["geometry", "ordinal", "context", "population"])
def test_repaired_sampling_pin_cannot_replace_complete_source_regeneration(damage):
    value = case()
    report = value["sampling"]
    index = next(i for i, row in enumerate(report["records"])
                 if row["record_cid"] == value["unit"]["source_occurrence_ref"]["record_cid"])
    if damage == "geometry":
        record = deepcopy(report["records"][index])
        record["start_utf8"] += 1
        record["end_utf8"] += 1
        report["records"][index] = seal_record(
            {k: v for k, v in record.items() if k not in {"record_cid", "cid_scope"}})
    elif damage == "ordinal":
        index = next(i for i, row in enumerate(report["records"])
                     if row["record_cid"] == value["unit"]["record_cid"])
        record = deepcopy(report["records"][index])
        record["ordinal"] += 1
        report["records"][index] = seal_record(
            {k: v for k, v in record.items() if k not in {"record_cid", "cid_scope"}})
    elif damage == "context":
        index = next(i for i, row in enumerate(report["records"])
                     if row["record_cid"] == value["unit"]["context_ref"]["record_cid"])
        record = deepcopy(report["records"][index])
        record["missing_requirements"].pop()
        report["records"][index] = seal_record(
            {k: v for k, v in record.items() if k not in {"record_cid", "cid_scope"}})
    else:
        report["unit_refs"].reverse()
    report["sampling_report_sha256"] = digest(
        {k: v for k, v in report.items() if k != "sampling_report_sha256"})
    with pytest.raises(ValueError, match="independently pinned source regeneration"):
        prepare(value)


@pytest.mark.parametrize("damage", ["duplicate", "nested_duplicate", "nan", "oversize", "bad_utf8", "hash", "not_bytes", "nonordinary_report"])
def test_invalid_input_bytes_or_json_are_refused_before_operation_owner_imports(damage):
    value = case()
    request_raw, declaration_raw, inputs = preparation_inputs(value)
    if damage == "duplicate":
        request_raw = b'{"source_text":"first","source_text":"second"}'
    elif damage == "nested_duplicate":
        declaration_raw = b'{"input":{"source_text":"a","source_text":"b"}}'
    elif damage == "nan":
        request_raw = b'{"source_text":NaN}'
    elif damage == "oversize":
        request_raw = b" " * (subject.MAX_SCOPE_BYTES + 1)
    elif damage == "bad_utf8":
        request_raw = b'{"source_text":"\xff"}'
    elif damage == "not_bytes":
        request_raw = request_raw.decode("utf-8")
    elif damage == "nonordinary_report":
        value["sampling"]["authority"] = object()
    if type(request_raw) is bytes:
        inputs["expected_scope_request_sha256"] = hashlib.sha256(request_raw).hexdigest()
    inputs["expected_scope_declaration_sha256"] = hashlib.sha256(declaration_raw).hexdigest()
    if damage == "hash":
        inputs["expected_scope_request_sha256"] = "0" * 64
    with patch.object(subject, "_owners", side_effect=AssertionError("operation owner loaded")):
        with pytest.raises(ValueError):
            subject.prepare_sampled_norm_scope_v1(
                value["sampling"], value["raw"], request_raw, declaration_raw, **inputs)


@pytest.mark.parametrize("damage", ["raw_hash", "raw_count", "descriptor_hash", "extra_replay_key", "missing_replay_key", "sampling_hash"])
def test_external_source_and_sampler_pins_are_checked_before_operation_owner_imports(damage):
    value = case()
    request_raw, declaration_raw, inputs = preparation_inputs(value)
    if damage == "raw_hash":
        inputs["expected_raw_sha256"] = "0" * 64
    elif damage == "raw_count":
        inputs["expected_raw_bytes"] = len(value["raw"]) + 1
    elif damage == "descriptor_hash":
        inputs["expected_descriptor_sha256"] = "0" * 64
    elif damage == "extra_replay_key":
        inputs["loader_callback"] = "not accepted"
    elif damage == "missing_replay_key":
        del inputs["descriptor"]
    elif damage == "sampling_hash":
        inputs["expected_sampling_report_sha256"] = "0" * 64
    with patch.object(subject, "_owners", side_effect=AssertionError("operation owner loaded")):
        with pytest.raises(ValueError):
            subject.prepare_sampled_norm_scope_v1(
                value["sampling"], value["raw"], request_raw, declaration_raw, **inputs)


@pytest.mark.parametrize("damage", ["authority", "masks", "source_geometry", "role_mapping", "issue", "lowered_ir", "bridge_view"])
def test_repaired_output_hash_does_not_authorize_tampered_output(damage):
    value = case()
    report = prepare(value)
    if damage == "authority":
        report["authority"]["source_semantics_verified"] = True
    elif damage == "masks":
        report["masks"]["strong_semantic_fit"] = 1
    elif damage == "source_geometry":
        report["source_selector"]["utf8_byte_start"] += 1
    elif damage == "role_mapping":
        report["anchor_mappings"][0]["document_selector"]["char_start"] += 1
    elif damage == "issue":
        report["scope_declaration"]["unresolved"] = []
    elif damage == "lowered_ir":
        report["lowered_ir"] = {"rules": []}
    elif damage == "bridge_view":
        report["scope_bridge_view"]["payload_cid"] = value["unit"]["record_cid"]
    report["report_sha256"] = digest({k: v for k, v in report.items() if k != "report_sha256"})
    with pytest.raises(ValueError, match="authoritative regeneration"):
        validate(report, value)


def test_raw_caller_byte_hashes_remain_distinct_from_canonical_declaration_hashes():
    value = case()
    request_raw, declaration_raw, inputs = preparation_inputs(value)
    request_raw = b" \n" + request_raw + b"\n"
    declaration_raw = json.dumps(value["declaration"], indent=2, ensure_ascii=False).encode("utf-8")
    inputs["expected_scope_request_sha256"] = hashlib.sha256(request_raw).hexdigest()
    inputs["expected_scope_declaration_sha256"] = hashlib.sha256(declaration_raw).hexdigest()
    report = subject.prepare_sampled_norm_scope_v1(
        value["sampling"], value["raw"], request_raw, declaration_raw, **inputs)
    assert report["input_pins"]["scope_request_raw_sha256"] != report["input_pins"]["scope_request_canonical_sha256"]
    assert report["input_pins"]["scope_declaration_raw_sha256"] != report["input_pins"]["scope_declaration_canonical_sha256"]
    assert report["scope_declaration"] == value["declaration"]
