"""Explicit plaintext definition declarations retain physical source custody.

Fixtures are authored interpretations, not reviewed law. The existing parent
fixture owns parsing/replay and the existing V2 oracle evaluates native ASTs.
"""
from copy import deepcopy
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_definition_adapter_v2 as adapter
from ipfs_datasets_py.logic.autoformal import corpus_parent_occurrence_adapter as parent_owner
from ipfs_datasets_py.logic.autoformal import legal_semantic_graph as graph
from ipfs_datasets_py.logic.autoformal import legal_source_definition_bridge_v2 as bridge
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as official_context
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes, cid_for_bytes


TEXT = ("雪 In this section:\nThe term café filer means registered and either active or not exempt.\n"
        "registered café filer.")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False).encode("utf-8")


def helper(name):
    spec = importlib.util.spec_from_file_location(
        "plaintext_definition_fixture_" + name, Path(__file__).with_name(name + ".py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reseal(record):
    return contracts.seal_record({key: deepcopy(value) for key, value in record.items()
        if key not in {"record_cid", "cid_scope"}})


def span(text, literal, *, last=False):
    start = text.rindex(literal) if last else text.index(literal)
    return {"char_start": start, "char_end": start + len(literal), "text": literal}


def interval(text, start, end):
    return {"char_start": start, "char_end": end, "text": text[start:end]}


@pytest.fixture
def parent_case(tmp_path):
    helpers = helper("test_plaintext_graph_custody")
    data = helpers.helper("test_corpus_parent_occurrence_adapter").case(
        tmp_path, source_text="registered", parent_texts=[TEXT, TEXT])
    bundle = parent_owner.build_parent_occurrence_corpus(**data["arguments"])
    return {"data": data, "bundle": bundle,
        "records": {record["record_cid"]: record for record in bundle["records"]},
        "helpers": helpers}


def case(parent, *, family="fol", parent_index=0):
    cid = parent["bundle"]["manifest"]["populations"]["roles"]["region"][parent_index]
    companion = parent["records"][cid]
    inputs = parent["helpers"].binding_arguments(parent, companion)
    bound = parent["helpers"].bind(parent, companion)
    scope = graph.bind_parent_scope(source=bound, jurisdiction="declared-US-federal",
        instrument="authored-parent-fixture", applicability="unreviewed caller scope",
        definition_scope="unreviewed literal section declaration")
    start, end = TEXT.index("The term"), TEXT.index(".\n") + 1
    request = {"schema": bridge.PARENT_REQUEST_SCHEMA, "profile": bridge.PARENT_PROFILE,
        "family": family, "declaration": {
            "declaration_id": "authored-cafe-definition",
            "interpretation_status": "unreviewed_caller_declaration",
            "source_binding_sha256": bound["source_binding_sha256"],
            "scope": scope, "scope_kind": "section", "scope_span": span(TEXT, "In this section:"),
            "contributor_spans": [interval(TEXT, start, end)],
            "head": span(TEXT, "café filer"), "definition_cue": span(TEXT, "means"),
            "body": {"op": "all", "operands": [
                {"op": "atom", "span": span(TEXT, "registered")},
                {"op": "any", "operands": [
                    {"op": "atom", "span": span(TEXT, "active")},
                    {"op": "not", "operand": {"op": "atom", "span": span(TEXT, "exempt")}}]}]}}}
    return request, inputs


def prepare(parent, **options):
    request, inputs = case(parent, **options)
    return bridge.prepare_parent_definition_v1(request, **inputs), request, inputs


def adapt(report, request, inputs):
    report_raw, request_raw = wire(report), wire(request)
    arguments = {"expected_report_sha256": sha(report_raw), "request_raw": request_raw,
        "expected_request_sha256": sha(request_raw), **inputs}
    candidate = adapter.adapt_parent_definition_only_bytes_v1(report_raw, **arguments)
    return candidate, report_raw, arguments


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_literal_definition_preserves_native_ast_and_unknown_context_without_html(parent_case, monkeypatch, family):
    def no_markup(*args, **kwargs):
        pytest.fail("plaintext definition must not synthesize or extract HTML")
    monkeypatch.setattr(official_context, "extract_document", no_markup)
    original = canonical_dag_json_bytes(parent_case["bundle"])
    report, request, inputs = prepare(parent_case, family=family)
    assert report["schema"] == bridge.PARENT_SCHEMA
    ast = report["native_ast"]
    assert ast["quantifier"]["value"] == "∀"
    assert ast["formula"]["operator"]["value"] == "↔"
    assert ast["formula"]["right"]["operator"]["value"] == "∧"
    assert ast["formula"]["right"]["right"]["operator"]["value"] == "∨"
    assert report["native"]["exact_native_ast_roundtrip"] is True
    assert "∀ v0 : Entity" in report["lean_body"]
    assert report["contributor_completeness_verified"] is False
    assert report["contributor_spans"] == request["declaration"]["contributor_spans"]
    assert report["source_version"]["edition"] == parent_owner.UNDECLARED_EDITION
    assert report["source_version"]["raw_artifact"]["media_type"] == "text/plain"
    assert report["source_version"]["raw_artifact"]["sha256"] == sha(TEXT.encode())
    assert report["source_version"]["extracted_view"]["normalization_profile"] == "identity/v1"
    assert report["parent_source_binding"]["selector"]["span_text"] == TEXT
    assert all(value is False for value in report["authority"].values())
    assert not {"normalized_view_id", "scope_unit_ref", "contributor_unit_refs"} & report.keys()
    assert bridge.validate_parent_definition_v1(report, request, **inputs)
    candidate, report_raw, arguments = adapt(report, request, inputs)
    assert candidate["schema"] == adapter.PARENT_SCHEMA
    assert candidate["source_version"] == report["source_version"]
    assert candidate["source_occurrences"] == report["source_occurrences"]
    assert candidate["parent_source_binding"] == report["parent_source_binding"]
    assert candidate["ast_record"]["native_ast"] == ast
    assert candidate["scope_record"]["schema"] == adapter.PARENT_SCOPE_SCHEMA
    assert not {"normalized_view_id", "scope_unit_ref", "contributor_unit_refs"} & candidate["scope_record"].keys()
    assert candidate["contributor_completeness_verified"] is False
    assert all(candidate[field] is False for field in adapter.FALSE_FLAGS)
    assert all(context["availability"] == "required_unavailable" and
        context["missing_requirements"] == list(parent_owner.MISSING_CONTEXT)
        for context in candidate["context_declarations"])
    relations = {edge["relation"] for edge in candidate["graph"]["edges"]}
    assert "DEFINES" in relations
    assert not {"APPLIES_WITHIN", "USES_DEFINITION"} & relations
    assert not {"norm", "norm_ast", "norm_record"} & candidate.keys()
    assert adapter.validate_parent_definition_only_candidate_v1(candidate, report_raw, **arguments) == candidate
    assert canonical_dag_json_bytes(parent_case["bundle"]) == original


def test_two_entity_boolean_oracle_detects_existential_and_one_way_weakening(parent_case):
    evaluate = helper("test_legal_source_definition_bridge_v2").evaluate
    report, _, _ = prepare(parent_case)
    names = {row["source_literal"]: row["symbol"] for row in report["symbols"]}
    witnesses = {"existential": 0, "one_way": 0, "or_instead_of_and": 0}
    for bits in itertools.product((False, True), repeat=8):
        valuations = {name: bits[2 * i:2 * i + 2]
            for i, name in enumerate(("café filer", "registered", "active", "exempt"))}
        values = {names[name]: value for name, value in valuations.items()}
        expected = all(valuations["café filer"][i] == (valuations["registered"][i]
            and (valuations["active"][i] or not valuations["exempt"][i])) for i in (0, 1))
        assert evaluate(report["native_ast"], values) == expected
        for name in witnesses:
            mutant = deepcopy(report["native_ast"])
            if name == "existential":
                mutant["quantifier"]["value"] = "∃"
            elif name == "one_way":
                mutant["formula"]["operator"]["value"] = "→"
            else:
                mutant["formula"]["right"]["operator"]["value"] = "∨"
            witnesses[name] += evaluate(mutant, values) != expected
    assert all(count > 0 for count in witnesses.values())


def test_export_keeps_exact_graph_and_full_definition_companion(parent_case, tmp_path):
    from ipfs_datasets_py.logic.autoformal.corpus_graph_exchange import load_graph_bundle
    report, request, inputs = prepare(parent_case)
    candidate, report_raw, arguments = adapt(report, request, inputs)
    output = tmp_path / "plaintext-definition-graph"
    manifest = adapter.export_parent_definition_only_candidate_v1(candidate, output,
        report_raw=report_raw, **arguments)
    loaded = load_graph_bundle(output, expected_manifest_sha256=sha(canonical_dag_json_bytes(manifest)))
    assert loaded["snapshot"] == candidate["graph"]
    raw = canonical_dag_json_bytes(candidate)
    path = tmp_path / "definition-companion.json"
    path.write_bytes(raw)
    retained = contracts.load_record_bytes(path.read_bytes(), expected_sha256=sha(raw))
    assert retained["ast_record"]["native_ast"] == report["native_ast"]
    assert retained["parent_source_binding"] == report["parent_source_binding"]
    assert adapter.validate_parent_definition_only_candidate_v1(retained, report_raw, **arguments) == candidate
    assert manifest["external_references_verified"] is False


def test_equal_literal_fields_at_different_physical_rows_keep_definition_namespaces_distinct(parent_case):
    first, _, _ = prepare(parent_case, parent_index=0)
    second, _, _ = prepare(parent_case, parent_index=1)
    assert first["source_version"]["extracted_view"]["sha256"] == second["source_version"]["extracted_view"]["sha256"]
    assert first["source_version"]["record_cid"] != second["source_version"]["record_cid"]
    assert first["parent_source_binding"]["parent_record"]["record_cid"] != second["parent_source_binding"]["parent_record"]["record_cid"]
    assert first["scope_key"] != second["scope_key"]
    assert first["native_ast"]["formula"]["left"]["name"] != second["native_ast"]["formula"]["left"]["name"]
    assert first["source_version"]["edition"] == second["source_version"]["edition"] == parent_owner.UNDECLARED_EDITION


def test_repeated_unicode_body_retains_physical_occurrences_and_ordered_roles(parent_case):
    request, inputs = case(parent_case)
    declaration = request["declaration"]
    declaration["contributor_spans"].append(interval(TEXT, TEXT.rindex("registered"), len(TEXT)))
    declaration["body"] = {"op": "any", "operands": [
        {"op": "atom", "span": span(TEXT, "registered")},
        {"op": "atom", "span": span(TEXT, "registered", last=True)}]}
    report = bridge.prepare_parent_definition_v1(request, **inputs)
    bindings = {row["role"]: row for row in report["source_bindings"]}
    first, second = (bindings[f"definition_body/{index:04d}"] for index in (0, 1))
    assert first["source_occurrence_cid"] != second["source_occurrence_cid"]
    assert first["symbol"] == second["symbol"]
    occurrences = {row["record_cid"]: row for row in report["source_occurrences"]}
    head = occurrences[bindings["definition_head"]["source_occurrence_cid"]]
    assert head["span_text"] == "café filer"
    assert head["end_utf8"] - head["start_utf8"] > head["end_char"] - head["start_char"]
    assert occurrences[first["source_occurrence_cid"]]["start_char"] < occurrences[second["source_occurrence_cid"]]["start_char"]
    assert report["contributor_completeness_verified"] is False


def test_cross_line_atom_preserves_exact_lf_when_contributor_union_covers_it(parent_case):
    request, inputs = case(parent_case)
    declaration = request["declaration"]
    split = TEXT.index(".\n") + 1
    declaration["contributor_spans"] = [interval(TEXT, TEXT.index("The term"), split),
        interval(TEXT, split, len(TEXT))]
    atom = interval(TEXT, TEXT.index("registered"), TEXT.rindex("registered") + len("registered"))
    declaration["body"] = {"op": "atom", "span": atom}
    report = bridge.prepare_parent_definition_v1(request, **inputs)
    binding = next(row for row in report["source_bindings"] if row["role"] == "definition_body/0000")
    occurrence = next(row for row in report["source_occurrences"] if row["record_cid"] == binding["source_occurrence_cid"])
    assert occurrence["span_text"] == atom["text"] and "\n" in occurrence["span_text"]
    assert occurrence["span_sha256"] == sha(atom["text"].encode())


@pytest.mark.parametrize("damage", ["unordered", "overlap", "uncovered_gap", "cue", "self_reference",
    "edition", "operator", "scope_kind", "shifted_span"])
def test_unsupported_or_inconsistent_plaintext_declarations_refuse_without_repair(parent_case, damage):
    request, inputs = case(parent_case)
    declaration = request["declaration"]
    first = declaration["contributor_spans"][0]
    if damage in {"unordered", "uncovered_gap"}:
        declaration["contributor_spans"].append(interval(TEXT, TEXT.rindex("registered"), len(TEXT)))
        if damage == "unordered":
            declaration["contributor_spans"].reverse()
        else:
            declaration["body"] = {"op": "atom", "span": interval(TEXT,
                TEXT.index("registered"), TEXT.rindex("registered") + len("registered"))}
    elif damage == "overlap":
        declaration["contributor_spans"].append(interval(TEXT, first["char_start"] + 1, first["char_end"]))
    elif damage == "cue":
        declaration["definition_cue"] = span(TEXT, "registered")
    elif damage == "self_reference":
        declaration["contributor_spans"] = [interval(TEXT, first["char_start"], len(TEXT))]
        declaration["body"] = {"op": "atom", "span": span(TEXT, "café filer", last=True)}
    elif damage == "edition":
        scope = declaration["scope"]
        scope["edition"] = 2024
        scope["scope_id"] = "legal-scope:sha256:" + graph.digest(
            {key: value for key, value in scope.items() if key != "scope_id"})
    elif damage == "operator":
        declaration["body"]["op"] = "xor"
    elif damage == "scope_kind":
        declaration["scope_kind"] = "title"
    else:
        declaration["head"]["char_start"] += 1
        declaration["head"]["char_end"] += 1
    with pytest.raises(ValueError):
        bridge.prepare_parent_definition_v1(request, **inputs)


@pytest.mark.parametrize("field", ["expected_report_sha256", "expected_request_sha256",
    "expected_manifest_cid", "parent_report_pin"])
def test_plaintext_definition_adapter_requires_independent_input_commitments(parent_case, field):
    report, request, inputs = prepare(parent_case)
    report_raw, request_raw = wire(report), wire(request)
    arguments = {"expected_report_sha256": sha(report_raw), "request_raw": request_raw,
        "expected_request_sha256": sha(request_raw), **deepcopy(inputs)}
    if field == "expected_manifest_cid":
        arguments[field] = report["source_version"]["record_cid"]
    elif field == "parent_report_pin":
        arguments["expected_report_pins"]["parent_text_views"]["raw_sha256"] = "0" * 64
    else:
        arguments[field] = "0" * 64
    with pytest.raises(ValueError):
        adapter.adapt_parent_definition_only_bytes_v1(report_raw, **arguments)


@pytest.mark.parametrize("damage", ["native", "contributors", "authority"])
def test_resealed_report_does_not_replace_original_declaration_or_authority(parent_case, damage):
    report, request, inputs = prepare(parent_case)
    if damage == "native":
        report["native_ast"]["formula"]["operator"]["value"] = "→"
    elif damage == "contributors":
        report["contributor_spans"] = []
    else:
        report["authority"]["source_semantics_verified"] = True
    report["report_sha256"] = bridge.digest({key: value for key, value in report.items() if key != "report_sha256"})
    with pytest.raises(ValueError):
        bridge.validate_parent_definition_v1(report, request, **inputs)
    if damage == "native":
        # adapt() supplies correct independent hashes of these exact transport
        # bytes; the public error must report refusal from original-bound replay.
        with pytest.raises(contracts.CorpusContractError, match="parent definition replay refused"):
            adapt(report, request, inputs)


@pytest.mark.parametrize("damage", ["scope", "context", "authority"])
def test_resealed_candidate_cannot_grant_scope_context_or_admission(parent_case, damage):
    report, request, inputs = prepare(parent_case)
    candidate, report_raw, arguments = adapt(report, request, inputs)
    if damage == "scope":
        candidate["scope_record"]["applicability_verified"] = True
        candidate["scope_record"] = reseal(candidate["scope_record"])
    elif damage == "context":
        context = candidate["context_declarations"][0]
        context.update(availability="none_required", missing_requirements=[], context_references=[])
        candidate["context_declarations"][0] = reseal(context)
    else:
        candidate["admitted"] = True
    candidate = reseal(candidate)
    with pytest.raises(ValueError):
        adapter.validate_parent_definition_only_candidate_v1(candidate, report_raw, **arguments)


def test_retained_definition_requires_unchanged_original_parent_bytes(parent_case):
    report, request, inputs = prepare(parent_case)
    candidate, report_raw, arguments = adapt(report, request, inputs)
    path = Path(inputs["replay_inputs"]["parent_text_views_inputs"]["parent_descriptor"]["local_path"])
    path.write_bytes(path.read_bytes() + b"changed owned fixture")
    with pytest.raises(ValueError):
        adapter.validate_parent_definition_only_candidate_v1(candidate, report_raw, **arguments)


def test_fragment_root_cannot_claim_complete_literal_field(parent_case):
    request, _ = case(parent_case)
    match = next(record for record in parent_case["bundle"]["records"]
        if record["schema"] == parent_owner.MATCH_SCHEMA)
    inputs = parent_case["helpers"].binding_arguments(parent_case, match)
    bound = parent_case["helpers"].bind(parent_case, match)
    request["declaration"]["source_binding_sha256"] = bound["source_binding_sha256"]
    with pytest.raises(ValueError):
        bridge.prepare_parent_definition_v1(request, **inputs)


def test_whole_field_length_does_not_substitute_for_original_literal_hash(parent_case, monkeypatch):
    request, inputs = case(parent_case)
    bound = deepcopy(parent_case["helpers"].bind(parent_case))
    occurrence = bound["selector"]
    changed = occurrence["span_text"].replace("雪", "山", 1)
    assert len(changed) == len(TEXT) and len(changed.encode()) == len(TEXT.encode())
    occurrence.update(span_text=changed, span_sha256=sha(changed.encode()), span_cid=cid_for_bytes(changed.encode()))
    bound["selector"] = occurrence = reseal(occurrence)
    bound["context"]["source_occurrence_cid"] = occurrence["record_cid"]
    bound["context"] = context = reseal(bound["context"])
    bound["companion_record"].update(source_occurrence_cid=occurrence["record_cid"], context_cid=context["record_cid"])
    bound["companion_record"] = reseal(bound["companion_record"])
    parent_case["helpers"].reseal_binding(bound)
    request["declaration"]["source_binding_sha256"] = bound["source_binding_sha256"]
    # Fault injection: all occurrence/crosslink seals agree, but the version's
    # independent full-field hash still identifies the original literal bytes.
    monkeypatch.setattr(graph, "bind_parent_source_occurrence", lambda *args, **kwargs: deepcopy(bound))
    with pytest.raises(ValueError):
        bridge.prepare_parent_definition_v1(request, **inputs)


def test_parent_candidate_is_not_an_official_v2_definition_review_subject(parent_case):
    report, request, inputs = prepare(parent_case)
    candidate, report_raw, arguments = adapt(report, request, inputs)
    assert candidate["schema"] != adapter.SCHEMA
    with pytest.raises(ValueError):
        adapter.validate_definition_only_candidate_v2(candidate, report_raw, **arguments)


@pytest.mark.parametrize("bound", ["contributors", "expression", "parent_population"])
def test_lowered_complete_definition_and_parent_bounds_refuse_without_truncation(parent_case, bound):
    request, inputs = case(parent_case)
    if bound == "contributors":
        request["declaration"]["contributor_spans"].append(interval(TEXT, TEXT.rindex("registered"), len(TEXT)))
        inputs["limits"] = {"max_contributors": 1}
    elif bound == "expression":
        inputs["limits"] = {"max_expression_nodes": 1}
    else:
        inputs["parent_limits"] = {"max_records": 1}
    with pytest.raises(ValueError):
        bridge.prepare_parent_definition_v1(request, **inputs)
