"""Lossless existing-proposal custody with independent source/input commitments."""
import hashlib
import json
from copy import deepcopy

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_proposed_graph_adapter as adapter
from ipfs_datasets_py.logic.autoformal import legal_semantic_graph as proposed
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context
from ipfs_datasets_py.logic.autoformal.corpus_graph_exchange import load_graph_bundle
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

TEXT = ("Café office must retain records if ready unless waived before T. "
        "Café office may file notice. Office means a registered office.")
RAW = ('<meta charset="utf-8"><h3 class="section-head">§1. Authored custody fixture</h3>'
       f'<p class="statutory-body">(a) {TEXT}</p>'
       f'<p class="statutory-body">(b) {TEXT}</p>').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def evidence(role):
    return {"artifact_id": "unresolved:" + role, "artifact_sha256": sha(role.encode()), "role": role}


def case(*, paragraph=0, edition=2024, revision="authored-release-1", semantics=True):
    url = f"https://www.govinfo.gov/content/pkg/USCODE-{edition}-title10/html/USCODE-{edition}-title10-sec1.htm"
    document = context.extract_document(RAW, url=url, edition=edition, legal_id="usc:us:10:1")
    row = document["paragraphs"][paragraph]
    selector = context.source_selector(document, RAW, char_start=row["char_start"] + 4,
                                       char_end=row["char_end"])
    source = proposed.bind_source_occurrence(document, RAW, selector=selector, document_revision=revision)
    scope = proposed.bind_scope(jurisdiction="US-federal", instrument="USCode-title10", edition=edition,
        applicability="caller-declared section-local", definition_scope="usc:us:10:1")
    ast = {"rules": [
        {"modality": "P", "actor": "Café office", "action": "file", "object": "notice",
         "conditions": [], "exceptions": [], "temporal": []},
        {"modality": "O", "actor": "Café office", "action": "retain", "object": "records",
         "conditions": ["b", "a", "b"], "exceptions": ["waived"], "temporal": ["T"]},
    ]}

    def subselector(literal):
        matches = context.exact_view_occurrences(document, RAW, text=literal)
        return next(item for item in matches
                    if selector["char_start"] <= item["char_start"] < item["char_end"] <= selector["char_end"])

    def entity(key, kind, literal=None, definition_kind=None):
        return {"entity_key": key, "kind": kind, "label": "office",
            "source_selector": subselector(literal) if literal is not None else None,
            "definition_kind": definition_kind, "ast_path": "/rules/0",
            "ambiguity": ["office or officeholder"], "evidence_refs": [evidence("source")]}

    declarations = {"entities": [entity("mention", "mention", "Café office"),
        entity("concept", "concept"),
        entity("definition", "definition", "Office means a registered office", "means")],
        "assertions": [{"assertion_key": "declared-denotation", "subject_key": "mention",
            "predicate": "denotes", "object_keys": ["concept", "concept"],
            "ambiguity": ["unresolved declaration"], "evidence_refs": [evidence("binding")],
            "dependency_refs": [evidence("definition")]}]} if semantics else None
    inputs = {"ast": ast, "profile": "canonical_rules_v1", "source": source, "scope": scope,
        "semantic_declarations": declarations, "dependency_refs": [evidence("context")],
        "evidence_refs": [evidence("source")], "scope_request": None}
    graph = proposed.build_graph(**inputs)
    raw = json.dumps(graph, ensure_ascii=False, indent=2).encode("utf-8")
    arguments = dict(expected_proposal_sha256=sha(raw), trusted_proposal_inputs=inputs,
        expected_inputs_sha256=sha(canonical_dag_json_bytes(inputs)), document=document,
        raw_html=RAW, expected_raw_sha256=sha(RAW),
        expected_extracted_sha256=sha(document["document_text"].encode("utf-8")))
    return raw, graph, arguments


def reseal(value):
    return contracts.seal_record({key: child for key, child in value.items()
                                  if key not in {"record_cid", "cid_scope"}})


def test_exact_existing_proposal_ids_order_and_ambiguity_survive():
    raw, proposal, arguments = case()
    record = adapter.adapt_proposed_graph_bytes(raw, **arguments)
    preserved = json.loads(record["proposal_record"]["proposal_json"])
    assert record["proposal_record"]["proposal_json"].encode("utf-8") == raw
    assert preserved == proposal
    assert record["ast_record"]["ast"] == arguments["trusted_proposal_inputs"]["ast"]
    assert record["ast_record"]["ast"]["rules"][1]["conditions"] == ["b", "a", "b"]
    assert [row["entity_id"] for row in preserved["entities"]] == [row["entity_id"] for row in proposal["entities"]]
    assert preserved["assertions"][0]["object_ids"][0] == preserved["assertions"][0]["object_ids"][1]
    assert preserved["entities"][2]["declaration"]["definition_kind"] == "means"
    assert record["definition_semantics_encoded"] is False
    assert record["external_references_verified"] is False
    assert record["source_authenticity_verified"] is False
    assert record["admitted"] is record["formalized"] is record["source_semantics_verified"] is False
    assert adapter.validate_proposed_graph_candidate(record, **arguments) == record


def test_transport_graph_contains_no_invented_semantic_entities_or_role_edges():
    raw, _, arguments = case()
    record = adapter.adapt_proposed_graph_bytes(raw, **arguments)
    graph = record["graph"]
    assert {node["node_type"] for node in graph["nodes"]} == {
        "source_version", "occurrence", "interpretation", "expression", "issue"}
    assert {edge["relation"] for edge in graph["edges"]} == {"HAS_SOURCE", "DERIVED_FROM"}
    assert {issue["kind"] for issue in record["issues"]} >= {
        "definition_semantics_not_encoded", "external_references_unverified",
        "context_closure_unverified", "unreviewed_semantic_proposal"}


def test_official_view_selector_maps_to_exact_corpus_unicode_geometry():
    raw, proposal, arguments = case(paragraph=1)
    record = adapter.adapt_proposed_graph_bytes(raw, **arguments)
    selector = proposal["source"]["selector"]
    occurrence = record["source_occurrence"]
    assert occurrence["span_text"] == selector["text"]
    assert (occurrence["start_char"], occurrence["end_char"]) == (selector["char_start"], selector["char_end"])
    assert (occurrence["start_utf8"], occurrence["end_utf8"]) == (
        selector["utf8_byte_start"], selector["utf8_byte_end"])
    assert occurrence["start_char"] != occurrence["start_utf8"]
    assert record["source_version"]["raw_artifact"]["sha256"] == sha(RAW)
    assert record["source_version"]["extracted_view"]["normalization_profile"] == context.NORMALIZATION_PROFILE


def test_identical_literals_remain_distinct_occurrences():
    first_raw, _, first_args = case(paragraph=0)
    second_raw, _, second_args = case(paragraph=1)
    first = adapter.adapt_proposed_graph_bytes(first_raw, **first_args)
    second = adapter.adapt_proposed_graph_bytes(second_raw, **second_args)
    assert first["source_version"] == second["source_version"]
    assert first["source_occurrence"]["span_text"] == second["source_occurrence"]["span_text"]
    assert first["source_occurrence"]["record_cid"] != second["source_occurrence"]["record_cid"]
    assert first["graph"]["record_cid"] != second["graph"]["record_cid"]


@pytest.mark.parametrize("change", [{"edition": 2025}, {"revision": "authored-release-2"}])
def test_editions_and_revisions_bind_distinct_source_custody(change):
    raw, _, arguments = case()
    other_raw, _, other_arguments = case(**change)
    first = adapter.adapt_proposed_graph_bytes(raw, **arguments)
    second = adapter.adapt_proposed_graph_bytes(other_raw, **other_arguments)
    assert first["source_version"]["record_cid"] != second["source_version"]["record_cid"]
    assert first["input_binding"]["inputs_cid"] != second["input_binding"]["inputs_cid"]
    with pytest.raises(contracts.CorpusContractError):
        adapter.validate_proposed_graph_candidate(first, **other_arguments)


@pytest.mark.parametrize("field", ["expected_proposal_sha256", "expected_inputs_sha256",
                                  "expected_raw_sha256", "expected_extracted_sha256"])
def test_every_independent_digest_is_required_and_checked(field):
    raw, _, arguments = case()
    arguments[field] = "0" * 64
    with pytest.raises(contracts.CorpusContractError):
        adapter.adapt_proposed_graph_bytes(raw, **arguments)


@pytest.mark.parametrize("damage", ["ast", "scope", "declarations", "source", "profile", "extra_inputs"])
def test_repaired_input_hash_cannot_hide_difference_from_original_proposal(damage):
    raw, _, arguments = case()
    inputs = arguments["trusted_proposal_inputs"]
    if damage == "ast":
        inputs["ast"]["rules"].reverse()
    elif damage == "scope":
        inputs["scope"] = proposed.bind_scope(jurisdiction="US-federal", instrument="USCode-title10",
            edition=2024, applicability="different scope", definition_scope="usc:us:10:1")
    elif damage == "declarations":
        inputs["semantic_declarations"]["entities"][0]["label"] = "changed label"
    elif damage == "source":
        inputs["source"]["paragraph_index"] = 99
    elif damage == "profile":
        inputs["profile"] = "invented_profile"
    else:
        inputs["ignored"] = True
    arguments["expected_inputs_sha256"] = sha(canonical_dag_json_bytes(inputs))
    with pytest.raises(contracts.CorpusContractError):
        adapter.adapt_proposed_graph_bytes(raw, **arguments)


def test_source_document_reconstruction_and_expected_binding_are_separate_checks():
    raw, _, arguments = case()
    arguments["document"]["document_text"] += "changed"
    with pytest.raises(contracts.CorpusContractError, match="regeneration"):
        adapter.adapt_proposed_graph_bytes(raw, **arguments)
    raw, _, arguments = case()
    arguments["raw_html"] = RAW + b"<!--different-->"
    arguments["expected_raw_sha256"] = sha(arguments["raw_html"])
    with pytest.raises(contracts.CorpusContractError, match="regeneration"):
        adapter.adapt_proposed_graph_bytes(raw, **arguments)


def test_raw_html_limit_applies_before_source_owner_regeneration(monkeypatch):
    raw, _, arguments = case()
    monkeypatch.setattr(adapter, "MAX_RAW_HTML_BYTES", len(RAW) - 1)
    with pytest.raises(contracts.CorpusContractError, match="raw HTML"):
        adapter.adapt_proposed_graph_bytes(raw, **arguments)


@pytest.mark.parametrize("damage", ["proposal", "ast", "source", "input_binding", "graph", "authority", "issues"])
def test_resealing_candidate_cannot_hide_nested_or_semantic_promotion(damage):
    raw, _, arguments = case()
    record = adapter.adapt_proposed_graph_bytes(raw, **arguments)
    if damage == "proposal":
        record["proposal_record"]["proposal_graph_id"] = "invented"
        record["proposal_record"] = reseal(record["proposal_record"])
    elif damage == "ast":
        record["ast_record"]["ast"]["rules"].reverse()
        record["ast_record"] = reseal(record["ast_record"])
    elif damage == "source":
        record["source_occurrence"]["start_utf8"] += 1
        record["source_occurrence"] = reseal(record["source_occurrence"])
    elif damage == "input_binding":
        record["input_binding"]["inputs_sha256"] = "0" * 64
        record["input_binding"] = reseal(record["input_binding"])
    elif damage == "graph":
        record["graph"]["edges"] = []
        record["graph"] = reseal(record["graph"])
    elif damage == "authority":
        record["definition_semantics_encoded"] = True
    else:
        record["issues"] = []
    with pytest.raises(contracts.CorpusContractError, match="regenerated"):
        adapter.validate_proposed_graph_candidate(reseal(record), **arguments)


def test_empty_semantic_declarations_and_unresolved_external_refs_are_retained():
    raw, proposal, arguments = case(semantics=False)
    record = adapter.adapt_proposed_graph_bytes(raw, **arguments)
    preserved = json.loads(record["proposal_record"]["proposal_json"])
    assert preserved["entities"] == preserved["assertions"] == []
    assert preserved["dependency_refs"] == proposal["dependency_refs"]
    assert "external_references_unverified" in {issue["kind"] for issue in record["issues"]}
    assert record["external_references_verified"] is False


def test_existing_normative_scope_profile_preserves_occurrences_and_unresolved_meaning():
    _, _, arguments = case(semantics=False)
    inputs = arguments["trusted_proposal_inputs"]
    owner = proposed.statement_scope
    request = {"source_text": TEXT, "context": {"role": "none_required", "text": "",
                "bindings": {}, "sha256": sha(b"")}}

    def anchor(literal):
        start = TEXT.index(literal)
        return {"origin": "source", "start": start, "end": start + len(literal),
                "text": literal, "offset_unit": "unicode_character_half_open"}

    declaration = {
        "schema": owner.SCHEMA, "family": "deontic", "profile": owner.PROFILE,
        "input": request, "input_sha256": proposed.digest(request),
        "occurrences": [{"occurrence_id": identity, "facet": facet,
                         "canonical_symbol": symbol, "anchor": anchor(literal)}
            for identity, facet, symbol, literal in (
                ("m", "modality", "O", "must"), ("a", "actor", "office", "Café office"),
                ("v", "action", "retain", "retain"), ("o", "object", "records", "records"))],
        "rules": [{"rule_id": "r1", "body": {"modality": "m", "actor": "a", "action": "v", "object": "o"},
                   "qualifiers": {"conditions": None, "exceptions": None, "temporal": None}}],
        "statement_structure": {"op": "rule", "rule_id": "r1"}, "binders": [],
        "coverage": {"declared_status": "unassessed", "segments": []},
        "unresolved": [{"code": "fixture_scope_unresolved", "span": anchor("if ready"),
                        "reason": "caller retains unresolved applicability"}],
    }
    declaration["content_sha256"] = proposed.digest(declaration)
    inputs.update(ast=declaration, profile="normative_scope_v1", scope_request=request)
    proposal = proposed.build_graph(**inputs)
    raw = json.dumps(proposal, ensure_ascii=False, indent=2).encode("utf-8")
    arguments.update(expected_proposal_sha256=sha(raw),
                     expected_inputs_sha256=sha(canonical_dag_json_bytes(inputs)))
    record = adapter.adapt_proposed_graph_bytes(raw, **arguments)
    assert record["ast_record"]["ast"] == declaration
    assert record["ast_record"]["ast"]["unresolved"][0]["code"] == "fixture_scope_unresolved"
    assert adapter.validate_proposed_graph_candidate(record, **arguments) == record


def test_graph_exchange_roundtrip_preserves_envelopes_with_companion_external(tmp_path):
    raw, _, arguments = case()
    record = adapter.adapt_proposed_graph_bytes(raw, **arguments)
    bundle = tmp_path / "bundle"
    manifest = adapter.export_proposed_graph_candidate(record, bundle, **arguments)
    loaded = load_graph_bundle(bundle,
        expected_manifest_sha256=sha(canonical_dag_json_bytes(manifest)))
    assert loaded["snapshot"] == record["graph"]
    assert manifest["external_references_verified"] is False
    assert not (bundle / "candidate.json").exists()
    assert any(node["content_cid"] == record["proposal_record"]["record_cid"]
               for node in loaded["snapshot"]["nodes"])


def test_aggregate_bounds_refuse_without_truncation_and_inputs_are_detached(monkeypatch):
    raw, proposal, arguments = case()
    original_inputs = deepcopy(arguments["trusted_proposal_inputs"])
    record = adapter.adapt_proposed_graph_bytes(raw, **arguments)
    record["ast_record"]["ast"]["rules"].clear()
    assert arguments["trusted_proposal_inputs"] == original_inputs
    assert len(proposed.graph_to_ast(proposal)["rules"]) == 2
    monkeypatch.setattr(contracts, "MAX_RECORD_BYTES", len(raw) + 200)
    with pytest.raises(contracts.CorpusContractError, match="byte bound"):
        adapter.adapt_proposed_graph_bytes(raw, **arguments)


# Reuse the explicit original-input graph-v2 port and its genuine source/join
# fixtures; historical graph-v1 inputs remain a separate rejected profile.
import base64 as _coordinate_base64

from ipfs_datasets_py.logic.autoformal import legal_span_cache_intake as _coordinate_intake
from tests.unit.logic.autoformal.test_legal_span_cache_intake import (
    coordinate_join,
    coordinate_graph_v2_case,
    _supported_coordinate_graph as _custody_supported,
    _repeated_coordinate_graph as _custody_repeated,
    _prepare_coordinate_graph_v2,
    _coordinate_graph_v2_request,
    _coordinate_graph_retained_table,
    eligibility as _coordinate_eligibility,
)


_CUSTODY_FIELDS = (
    "expected_proposal_sha256", "trusted_proposal_inputs", "expected_inputs_sha256",
    "expected_raw_sha256", "expected_extracted_sha256",
)
_CUSTODY_IDENTITY = (
    "output_occurrence_ordinal", "physical_identity_sha256", "route", "ordinal",
)


def _custody_wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _custody_empty_slot(output):
    return {**{field: output[field] for field in _CUSTODY_IDENTITY},
            **dict.fromkeys(_CUSTODY_FIELDS)}


@pytest.fixture
def coordinate_corpus_case(coordinate_graph_v2_case):
    upstream = coordinate_graph_v2_case
    intake = _prepare_coordinate_graph_v2(upstream)
    intake_raw = json.dumps(intake, ensure_ascii=False, indent=2).encode("utf-8")
    request_raw = _coordinate_graph_v2_request(upstream)
    intake_inputs = {
        "request_raw": request_raw,
        "eligibility_report_raw": upstream["eligibility_raw"],
        "eligibility_request_raw": upstream["eligibility_request_raw"],
        "join_manifest_raw": upstream["join_raw"],
        "expected_request_sha256": sha(request_raw),
        "join_originals": upstream["originals"],
        "source_bindings": upstream["bindings"],
    }
    output_inputs = []
    for output in intake["output_occurrences"]:
        slot = _custody_empty_slot(output)
        if output["graph"] is not None:
            inputs = deepcopy(output["graph_request"])
            inputs.update(semantic_declarations=None, scope_request=None)
            assert set(inputs) == adapter.TRUSTED_INPUT_FIELDS
            binding = upstream["bindings"][output["physical_identity_sha256"]]
            raw_html = _coordinate_base64.b64decode(binding["raw_html_base64"], validate=True)
            slot.update(
                expected_proposal_sha256=sha(canonical_dag_json_bytes(output["graph"])),
                trusted_proposal_inputs=inputs,
                expected_inputs_sha256=sha(canonical_dag_json_bytes(inputs)),
                expected_raw_sha256=sha(raw_html),
                expected_extracted_sha256=sha(binding["document"]["document_text"].encode("utf-8")),
            )
        output_inputs.append(slot)
    return {"upstream": upstream, "intake": intake, "intake_raw": intake_raw,
            "intake_inputs": intake_inputs, "output_inputs": output_inputs}


def _custody_arguments(case, **changes):
    arguments = {
        "expected_intake_raw_sha256": sha(case["intake_raw"]),
        "expected_intake_sha256": _coordinate_intake.coordinate_source_graph_intake_sha256(case["intake"]),
        "intake_inputs": case["intake_inputs"],
        "output_inputs": case["output_inputs"],
    }
    if "expected_intake_inputs_sha256" not in changes:
        arguments["expected_intake_inputs_sha256"] = adapter.coordinate_graph_corpus_originals_sha256(case["intake_inputs"])
    if "expected_output_inputs_sha256" not in changes:
        arguments["expected_output_inputs_sha256"] = adapter.coordinate_graph_corpus_inputs_sha256(case["output_inputs"])
    arguments.update(changes)
    return arguments


def _prepare_coordinate_corpus(case, **changes):
    return adapter.prepare_coordinate_graph_corpus_v1(case["intake_raw"],
                                                       **_custody_arguments(case, **changes))


def _validate_coordinate_corpus(case, report, **changes):
    offered = json.loads(report) if type(report) is bytes else report
    arguments = _custody_arguments(case)
    arguments.update(expected_report_sha256=adapter.coordinate_graph_corpus_sha256(offered))
    arguments.update(changes)
    return adapter.validate_coordinate_graph_corpus_v1(report, case["intake_raw"], **arguments)


def _export_coordinate_corpus(case, report, ordinal, directory, **changes):
    arguments = _custody_arguments(case)
    arguments.update(expected_report_sha256=adapter.coordinate_graph_corpus_sha256(report))
    arguments.update(changes)
    return adapter.export_coordinate_graph_corpus_output_v1(
        report, ordinal, directory, case["intake_raw"], **arguments)


def _assert_coordinate_corpus_unreviewed(report):
    for value in (report, *report["output_occurrences"]):
        assert all(type(flag) is bool and flag is False for flag in value["authority"].values())
        for field in ("training_mask", "evaluation_gold_mask", "source_binding_mask"):
            assert type(value[field]) is int and value[field] == 0
        assert value["selected_occurrence"] is None
    for output in report["output_occurrences"]:
        assert output["consumer_eligible"] is False
        assert output["coordinate_to_graph_source_correspondence"] == "unverified_no_independent_crosswalk"
        assert output["entity_binding"] == "unavailable_semantic_companions_not_supplied"
        candidate = output["candidate"]
        if candidate is not None:
            assert candidate["view"] == "candidate"
            assert candidate["admitted"] is candidate["formalized"] is False
            assert candidate["source_semantics_verified"] is False
            assert candidate["source_authenticity_verified"] is False
            assert candidate["definition_semantics_encoded"] is False


@_custody_supported
@pytest.mark.parametrize("offered", ["object", "bytes"])
def test_coordinate_corpus_genuine_owners_preserve_complete_custody_and_ast(
    coordinate_corpus_case, monkeypatch, offered,
):
    case = coordinate_corpus_case
    genuine_intake = _coordinate_intake.validate_coordinate_source_graph_intake_v2
    genuine_adapt = adapter.adapt_proposed_graph_bytes
    genuine_validate = adapter.validate_proposed_graph_candidate
    calls = {"intake": [], "adapt": [], "candidate_validation": []}

    def observe_intake(*args, **kwargs):
        result = genuine_intake(*args, **kwargs)
        calls["intake"].append(result["request_sha256"])
        return result

    def observe_adapt(*args, **kwargs):
        result = genuine_adapt(*args, **kwargs)
        calls["adapt"].append(result["record_cid"])
        return result

    def observe_candidate(*args, **kwargs):
        result = genuine_validate(*args, **kwargs)
        calls["candidate_validation"].append(result["record_cid"])
        return result

    monkeypatch.setattr(_coordinate_intake, "validate_coordinate_source_graph_intake_v2", observe_intake)
    monkeypatch.setattr(adapter, "adapt_proposed_graph_bytes", observe_adapt)
    monkeypatch.setattr(adapter, "validate_proposed_graph_candidate", observe_candidate)
    originals = deepcopy(case["intake_inputs"])
    slots = deepcopy(case["output_inputs"])
    report = _prepare_coordinate_corpus(case)
    assert report["schema"] == "legal-coordinate-graph-corpus/v1"
    assert report["source_compatibility_profile"] == "original-input-coordinate-graph-v2-corpus-custody/v1"
    assert report["intake_report_raw_utf8"].encode("utf-8") == case["intake_raw"]
    assert report["physical_rows"] == case["intake"]["physical_rows"]
    assert report["row_references"] == case["intake"]["row_references"]
    assert report["counts"] == {"physical_rows": 1, "row_references": 1,
        "output_occurrences": 2, "candidate_outputs": 2, "unresolved_outputs": 0}
    assert len(calls["intake"]) == 2
    assert len(calls["candidate_validation"]) == 2 and len(calls["adapt"]) >= 4
    for index, output in enumerate(report["output_occurrences"]):
        upstream = case["intake"]["output_occurrences"][index]
        assert {key: output[key] for key in _CUSTODY_IDENTITY} == {
            key: upstream[key] for key in _CUSTODY_IDENTITY}
        assert output["intake_output"] == upstream
        assert output["disposition"] == "candidate_corpus_custody"
        candidate = output["candidate"]
        assert json.loads(candidate["proposal_record"]["proposal_json"]) == upstream["graph"]
        assert candidate["proposal_record"]["proposal_json"].encode("utf-8") == canonical_dag_json_bytes(upstream["graph"])
        assert candidate["ast_record"]["ast"] == upstream["graph_request"]["ast"]
        assert proposed.graph_to_ast(upstream["graph"]) == candidate["ast_record"]["ast"]
        assert output["intake_output"]["source_coordinate_span_index"] == 1
        assert "intake_report_raw_utf8" not in output and "intake_report_raw_utf8" not in candidate
    assert case["intake_inputs"] == originals and case["output_inputs"] == slots
    value = _custody_wire(report) if offered == "bytes" else report
    assert _validate_coordinate_corpus(case, value) == report
    assert len(calls["intake"]) == 4
    _assert_coordinate_corpus_unreviewed(report)


@_custody_repeated
def test_coordinate_corpus_repeated_text_and_routes_keep_distinct_occurrences(coordinate_corpus_case):
    case = coordinate_corpus_case
    report = _prepare_coordinate_corpus(case)
    outputs = report["output_occurrences"]
    assert len(outputs) == 4
    assert [row["output_occurrence_ordinal"] for row in outputs] == [0, 1, 2, 3]
    assert [row["intake_output"]["source_coordinate_span_index"] for row in outputs] == [1, 1, 3, 3]
    assert [row["intake_output"]["eligibility_output"] for row in outputs] == [
        row["eligibility_output"] for row in case["intake"]["output_occurrences"]]
    assert len({row["physical_identity_sha256"] for row in outputs}) == 2
    assert len({row["candidate"]["source_occurrence"]["record_cid"] for row in outputs}) == 2
    assert [row["route"] for row in outputs] == ["compiler.formal_outputs",
        "compiler.canonical_formal_outputs", "compiler.formal_outputs", "compiler.canonical_formal_outputs"]
    assert _validate_coordinate_corpus(case, report) == report
    _assert_coordinate_corpus_unreviewed(report)


@_custody_supported
def test_coordinate_corpus_export_uses_existing_writer_and_loadable_graph_bundle(
    coordinate_corpus_case, monkeypatch, tmp_path,
):
    case = coordinate_corpus_case
    report = _prepare_coordinate_corpus(case)
    genuine_export = adapter.export_proposed_graph_candidate
    calls = []

    def observe_export(*args, **kwargs):
        result = genuine_export(*args, **kwargs)
        calls.append(result)
        return result

    monkeypatch.setattr(adapter, "export_proposed_graph_candidate", observe_export)
    destination = tmp_path / "coordinate-corpus-output"
    receipt = _export_coordinate_corpus(case, report, 1, destination)
    selected = report["output_occurrences"][1]
    assert receipt["schema"] == "legal-coordinate-graph-corpus-output-export/v1"
    assert receipt["corpus_report_sha256"] == adapter.coordinate_graph_corpus_sha256(report)
    assert {field: receipt[field] for field in _CUSTODY_IDENTITY} == {
        field: selected[field] for field in _CUSTODY_IDENTITY}
    assert receipt["candidate_record_cid"] == selected["candidate"]["record_cid"]
    assert calls == [receipt["graph_manifest"]]
    assert receipt["graph_manifest_sha256"] == sha(canonical_dag_json_bytes(receipt["graph_manifest"]))
    loaded = load_graph_bundle(destination, expected_manifest_sha256=receipt["graph_manifest_sha256"])
    assert loaded["snapshot"] == selected["candidate"]["graph"]
    assert receipt["snapshot_cid"] == selected["candidate"]["graph"]["record_cid"]
    assert receipt["delegated_writer_readback_performed"] is True
    assert receipt["full_candidate_retained_separately_required"] is True
    assert not (destination / "candidate.json").exists()
    assert all(flag is False for flag in receipt["authority"].values())
    for field in ("training_mask", "evaluation_gold_mask", "source_binding_mask"):
        assert type(receipt[field]) is int and receipt[field] == 0
    assert receipt["selected_occurrence"] is None


def test_coordinate_corpus_upstream_unsupported_slots_remain_complete_and_unexportable(
    coordinate_corpus_case, tmp_path,
):
    case = coordinate_corpus_case
    assert case["intake"]["output_occurrences"]
    assert all(row["graph"] is None for row in case["intake"]["output_occurrences"])
    report = _prepare_coordinate_corpus(case)
    assert [row["intake_output"] for row in report["output_occurrences"]] == case["intake"]["output_occurrences"]
    assert all(row["candidate"] is None and row["disposition"] == "unresolved"
               and any(issue["code"] == "upstream_graph_unresolved" for issue in row["custody_issues"])
               for row in report["output_occurrences"])
    with pytest.raises(ValueError):
        _export_coordinate_corpus(case, report, 0, tmp_path / "refused-unsupported")
    assert not (tmp_path / "refused-unsupported").exists()
    _assert_coordinate_corpus_unreviewed(report)


def test_coordinate_corpus_upstream_unresolved_output_refuses_supplied_foreign_custody(
    coordinate_corpus_case, monkeypatch,
):
    _, proposal, original_arguments = case(semantics=False)
    observed = coordinate_corpus_case
    assert all(row["graph"] is None for row in observed["intake"]["output_occurrences"])
    slot = observed["output_inputs"][0]
    slot.update({field: deepcopy(original_arguments[field]) for field in _CUSTODY_FIELDS})
    slot["expected_proposal_sha256"] = sha(canonical_dag_json_bytes(proposal))
    monkeypatch.setattr(adapter, "adapt_proposed_graph_bytes",
                        lambda *args, **kwargs: pytest.fail("unresolved upstream output reached candidate adapter"))
    with pytest.raises(ValueError):
        _prepare_coordinate_corpus(observed)


@_custody_supported
def test_coordinate_corpus_missing_custody_inputs_keep_supported_outputs_unresolved(coordinate_corpus_case):
    case = coordinate_corpus_case
    case["output_inputs"] = [_custody_empty_slot(row) for row in case["intake"]["output_occurrences"]]
    report = _prepare_coordinate_corpus(case)
    assert report["counts"]["candidate_outputs"] == 0
    assert report["counts"]["unresolved_outputs"] == 2
    assert all(row["candidate"] is None and row["intake_output"]["graph"] is not None
               and any(issue["code"] == "custody_inputs_not_supplied" for issue in row["custody_issues"])
               for row in report["output_occurrences"])
    _assert_coordinate_corpus_unreviewed(report)


@_custody_supported
@pytest.mark.parametrize("field", ["expected_proposal_sha256", "trusted_proposal_inputs",
    "expected_inputs_sha256", "expected_raw_sha256", "expected_extracted_sha256"])
def test_coordinate_corpus_partial_supplied_custody_refuses_instead_of_skipping(coordinate_corpus_case, field):
    case = coordinate_corpus_case
    case["output_inputs"][0][field] = None
    with pytest.raises(ValueError):
        _prepare_coordinate_corpus(case, expected_output_inputs_sha256=sha(_custody_wire(case["output_inputs"])))


@_custody_supported
@pytest.mark.parametrize("pin", ["expected_intake_raw_sha256", "expected_intake_sha256",
    "expected_intake_inputs_sha256", "expected_output_inputs_sha256"])
def test_coordinate_corpus_independent_input_pins_are_required(coordinate_corpus_case, pin):
    with pytest.raises(ValueError):
        _prepare_coordinate_corpus(coordinate_corpus_case, **{pin: "0" * 64})


@_custody_supported
@pytest.mark.parametrize("substitution", ["raw_as_canonical", "canonical_as_raw"])
def test_coordinate_corpus_raw_and_canonical_intake_pins_are_distinct(coordinate_corpus_case, substitution):
    case = coordinate_corpus_case
    raw_pin = sha(case["intake_raw"])
    canonical_pin = _coordinate_intake.coordinate_source_graph_intake_sha256(case["intake"])
    assert raw_pin != canonical_pin
    changes = ({"expected_intake_sha256": raw_pin} if substitution == "raw_as_canonical"
               else {"expected_intake_raw_sha256": canonical_pin})
    with pytest.raises(ValueError):
        _prepare_coordinate_corpus(case, **changes)


@_custody_repeated
@pytest.mark.parametrize("damage", ["drop", "reorder", "identity", "boolean_ordinal"])
def test_coordinate_corpus_recommitted_sidecars_require_complete_ordered_population(coordinate_corpus_case, damage):
    case = coordinate_corpus_case
    if damage == "drop":
        case["output_inputs"].pop()
    elif damage == "reorder":
        case["output_inputs"].reverse()
    elif damage == "identity":
        case["output_inputs"][0]["physical_identity_sha256"] = "0" * 64
    else:
        case["output_inputs"][0]["output_occurrence_ordinal"] = True
    with pytest.raises(ValueError):
        _prepare_coordinate_corpus(case, expected_output_inputs_sha256=sha(_custody_wire(case["output_inputs"])))


@_custody_supported
@pytest.mark.parametrize("field", ["expected_proposal_sha256", "expected_inputs_sha256",
                                  "expected_raw_sha256", "expected_extracted_sha256"])
def test_coordinate_corpus_recommitted_sidecar_cannot_substitute_original_adapter_pins(coordinate_corpus_case, field):
    case = coordinate_corpus_case
    case["output_inputs"][0][field] = "0" * 64
    with pytest.raises(ValueError):
        _prepare_coordinate_corpus(case)


@_custody_supported
def test_coordinate_corpus_explicit_profile_refuses_historical_graph_v1(
    coordinate_corpus_case, monkeypatch,
):
    case = coordinate_corpus_case
    case["intake"]["schema"] = "legal-coordinate-source-graph-intake/v1"
    case["intake"]["source_compatibility_profile"] = "paired-coordinate-source-graph-intake/v1"
    case["intake_raw"] = _custody_wire(case["intake"])
    monkeypatch.setattr(_coordinate_intake, "validate_coordinate_source_graph_intake_v2",
                        lambda *args, **kwargs: pytest.fail("historical graph profile reached original-input validator"))
    with pytest.raises(ValueError):
        _prepare_coordinate_corpus(case)


@_custody_supported
def test_coordinate_corpus_retained_eligibility_cannot_replace_original_replay_ancestry(
    coordinate_corpus_case, monkeypatch,
):
    case = coordinate_corpus_case
    inputs = case["intake_inputs"]
    request = json.loads(inputs["eligibility_request_raw"])
    request["schema"] = _coordinate_eligibility.RETAINED_REQUEST_SCHEMA_V1
    request.pop("join_originals_sha256")
    request["source_compatibility_profile"] = _coordinate_eligibility.RETAINED_PROFILE_V1
    request_raw = _custody_wire(request)
    retained = _coordinate_eligibility.prepare_retained_source_span_target_eligibility_v1(
        request_raw, inputs["join_manifest_raw"], expected_request_sha256=sha(request_raw))
    assert retained["upstream_reexecution_performed"] is False
    retained_raw = json.dumps(retained, ensure_ascii=False, indent=2).encode("utf-8")
    graph_request = json.loads(inputs["request_raw"])
    graph_request.update(eligibility_report_raw_sha256=sha(retained_raw),
        eligibility_report_sha256=_coordinate_eligibility.source_span_target_eligibility_sha256(retained),
        eligibility_request_sha256=sha(request_raw))
    inputs.update(request_raw=_custody_wire(graph_request), eligibility_request_raw=request_raw,
                  eligibility_report_raw=retained_raw)
    inputs["expected_request_sha256"] = sha(inputs["request_raw"])
    case["intake"].update(request=graph_request, request_raw_utf8=inputs["request_raw"].decode("utf-8"),
        request_sha256=inputs["expected_request_sha256"], eligibility_report_raw_utf8=retained_raw.decode("utf-8"))
    case["intake"]["eligibility_report_reference"].update(report_artifact_sha256=sha(retained_raw),
        report_sha256=_coordinate_eligibility.source_span_target_eligibility_sha256(retained),
        report_bytes=len(retained_raw))
    case["intake_raw"] = _custody_wire(case["intake"])
    monkeypatch.setattr(proposed, "build_graph",
                        lambda *args, **kwargs: pytest.fail("retained eligibility reached semantic graph builder"))
    with pytest.raises(ValueError):
        _prepare_coordinate_corpus(case)


@_custody_supported
@pytest.mark.parametrize("damage", ["ast", "scope"])
def test_coordinate_corpus_recommitted_trusted_inputs_cannot_replace_replayed_graph(coordinate_corpus_case, damage):
    case = coordinate_corpus_case
    slot = case["output_inputs"][0]
    inputs = slot["trusted_proposal_inputs"]
    if damage == "ast":
        inputs["ast"]["rules"][0]["actor"] = "different proposed actor"
    else:
        scope = inputs["scope"]
        inputs["scope"] = proposed.bind_scope(jurisdiction=scope["jurisdiction"],
            instrument=scope["instrument"], edition=scope["edition"],
            applicability="different caller-declared applicability", definition_scope=scope["definition_scope"])
    slot["expected_inputs_sha256"] = sha(canonical_dag_json_bytes(inputs))
    with pytest.raises(ValueError):
        _prepare_coordinate_corpus(case)


@_custody_repeated
@pytest.mark.parametrize("damage", ["drop_output", "reorder_references", "mask", "candidate"])
def test_coordinate_corpus_rehashed_report_requires_complete_original_regeneration(coordinate_corpus_case, damage):
    case = coordinate_corpus_case
    report = _prepare_coordinate_corpus(case)
    if damage == "drop_output":
        report["output_occurrences"].pop()
    elif damage == "reorder_references":
        report["row_references"].reverse()
    elif damage == "mask":
        report["training_mask"] = True
    else:
        candidate = report["output_occurrences"][0]["candidate"]
        candidate["ast_record"]["ast"]["rules"][0]["actor"] = "different actor"
        candidate["ast_record"] = reseal(candidate["ast_record"])
        report["output_occurrences"][0]["candidate"] = reseal(candidate)
    with pytest.raises(ValueError):
        _validate_coordinate_corpus(case, report)


@_custody_supported
@pytest.mark.parametrize("damage", ["source_binding", "output_sidecar", "delegated_candidate"])
def test_coordinate_corpus_mutation_during_genuine_adapter_is_refused(coordinate_corpus_case, monkeypatch, damage):
    case = coordinate_corpus_case
    genuine = adapter.adapt_proposed_graph_bytes
    calls = []

    def mutate_after_genuine(*args, **kwargs):
        candidate = genuine(*args, **kwargs)
        calls.append(candidate["record_cid"])
        if len(calls) == 1:
            if damage == "source_binding":
                next(iter(case["intake_inputs"]["source_bindings"].values()))["context_observation"]["status"] = "changed"
            elif damage == "output_sidecar":
                case["output_inputs"][0]["trusted_proposal_inputs"]["ast"]["rules"][0]["actor"] = "changed"
            else:
                candidate["ast_record"]["ast"]["rules"][0]["actor"] = "changed after real adaptation"
                candidate["ast_record"] = reseal(candidate["ast_record"])
                candidate = reseal(candidate)
        return candidate

    monkeypatch.setattr(adapter, "adapt_proposed_graph_bytes", mutate_after_genuine)
    with pytest.raises(ValueError):
        _prepare_coordinate_corpus(case)
    assert calls


@_custody_supported
def test_coordinate_corpus_primary_error_keeps_secondary_genuine_closing_failure(coordinate_corpus_case, monkeypatch):
    case = coordinate_corpus_case
    genuine = adapter.adapt_proposed_graph_bytes
    primary = RuntimeError("authored corpus adaptation primary failure")
    calls = []

    def fail_after_genuine(*args, **kwargs):
        candidate = genuine(*args, **kwargs)
        calls.append(candidate["record_cid"])
        path = _coordinate_graph_retained_table(case["upstream"])
        path.write_bytes(path.read_bytes() + b"changed after genuine corpus adaptation")
        raise primary

    monkeypatch.setattr(adapter, "adapt_proposed_graph_bytes", fail_after_genuine)
    with pytest.raises(RuntimeError, match="authored corpus adaptation primary failure") as observed:
        _prepare_coordinate_corpus(case)
    assert observed.value is primary and calls
    assert any("closing" in note or "custody" in note for note in getattr(primary, "__notes__", ()))


@_custody_supported
@pytest.mark.parametrize("ordinal", [True, -1, 2], ids=["boolean", "negative", "out_of_range"])
def test_coordinate_corpus_export_requires_exact_resolved_output_ordinal(coordinate_corpus_case, monkeypatch, tmp_path, ordinal):
    case = coordinate_corpus_case
    report = _prepare_coordinate_corpus(case)
    monkeypatch.setattr(adapter, "export_proposed_graph_candidate",
                        lambda *args, **kwargs: pytest.fail("invalid ordinal reached graph writer"))
    destination = tmp_path / "refused-ordinal"
    with pytest.raises(ValueError):
        _export_coordinate_corpus(case, report, ordinal, destination)
    assert not destination.exists()


@_custody_supported
def test_coordinate_corpus_export_closing_drift_refuses_receipt_and_retains_written_bundle(
    coordinate_corpus_case, monkeypatch, tmp_path,
):
    case = coordinate_corpus_case
    report = _prepare_coordinate_corpus(case)
    genuine = adapter.export_proposed_graph_candidate
    calls = []

    def mutate_after_export(*args, **kwargs):
        result = genuine(*args, **kwargs)
        calls.append(result)
        path = _coordinate_graph_retained_table(case["upstream"])
        path.write_bytes(path.read_bytes() + b"changed after genuine graph export")
        return result

    monkeypatch.setattr(adapter, "export_proposed_graph_candidate", mutate_after_export)
    destination = tmp_path / "written-but-unqualified"
    with pytest.raises(ValueError):
        _export_coordinate_corpus(case, report, 0, destination)
    assert calls and destination.is_dir()
    retained = load_graph_bundle(destination,
        expected_manifest_sha256=sha(canonical_dag_json_bytes(calls[0])))
    assert retained["snapshot"] == report["output_occurrences"][0]["candidate"]["graph"]


@_custody_supported
def test_coordinate_corpus_validator_fences_offered_report_after_genuine_delegate(coordinate_corpus_case, monkeypatch):
    case = coordinate_corpus_case
    report = _prepare_coordinate_corpus(case)
    genuine = adapter.adapt_proposed_graph_bytes
    calls = []

    def mutate_offered(*args, **kwargs):
        result = genuine(*args, **kwargs)
        calls.append(result["record_cid"])
        report["output_occurrences"][0]["training_mask"] = 1
        return result

    monkeypatch.setattr(adapter, "adapt_proposed_graph_bytes", mutate_offered)
    with pytest.raises(ValueError):
        _validate_coordinate_corpus(case, report)
    assert calls


# The explicit wire port reuses the genuine graph-v3/eligibility-v4/join-v3
# owners and the existing candidate adapter and physical bundle writer.
from tests.unit.logic.autoformal.test_legal_span_cache_intake import (
    wire_coordinate_join,
    wire_original_replay_v4,
    wire_graph_v3_case,
    _wire_graph_v3_request,
    _prepare_wire_graph_v3,
)


_WIRE_CORPUS_SCHEMA = "legal-coordinate-graph-corpus/v2"
_WIRE_CORPUS_EXPORT_SCHEMA = "legal-coordinate-graph-corpus-output-export/v2"
_WIRE_CORPUS_PROFILE = "original-input-wire-coordinate-graph-v3-corpus-custody/v1"
_WIRE_CORPUS_METADATA = "hf-default-parquet-envelope/v1"
_WIRE_CORPUS_BUNDLE_FILES = {"manifest.json", "snapshot.json", "nodes.parquet", "edges.parquet"}


@pytest.fixture
def wire_corpus_v2_case(wire_graph_v3_case):
    upstream = wire_graph_v3_case
    intake = _prepare_wire_graph_v3(upstream)
    request_raw = _wire_graph_v3_request(upstream)
    intake_inputs = {
        "request_raw": request_raw,
        "eligibility_report_raw": upstream["eligibility_raw"],
        "eligibility_request_raw": upstream["eligibility_request_raw"],
        "join_manifest_raw": upstream["join_raw"],
        "expected_request_sha256": sha(request_raw),
        "join_originals": upstream["originals"],
        "source_bindings": upstream["bindings"],
    }
    slots = []
    for output in intake["output_occurrences"]:
        slot = _custody_empty_slot(output)
        if output["graph"] is not None:
            inputs = deepcopy(output["graph_request"])
            inputs.update(semantic_declarations=None, scope_request=None)
            assert set(inputs) == adapter.TRUSTED_INPUT_FIELDS
            binding = upstream["bindings"][output["physical_identity_sha256"]]
            raw_html = _coordinate_base64.b64decode(binding["raw_html_base64"], validate=True)
            slot.update(expected_proposal_sha256=sha(canonical_dag_json_bytes(output["graph"])),
                trusted_proposal_inputs=inputs,
                expected_inputs_sha256=sha(canonical_dag_json_bytes(inputs)),
                expected_raw_sha256=sha(raw_html),
                expected_extracted_sha256=sha(binding["document"]["document_text"].encode("utf-8")))
        slots.append(slot)
    return {"upstream": upstream, "intake": intake,
        "intake_raw": (json.dumps(intake, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        "intake_inputs": intake_inputs, "output_inputs": slots}


def _prepare_wire_corpus_v2(case, **changes):
    return adapter.prepare_coordinate_graph_corpus_v2(case["intake_raw"],
        **_custody_arguments(case, **changes))


def _validate_wire_corpus_v2(case, report, **changes):
    value = json.loads(report) if type(report) is bytes else report
    arguments = _custody_arguments(case)
    arguments["expected_report_sha256"] = adapter.coordinate_graph_corpus_sha256(value)
    arguments.update(changes)
    return adapter.validate_coordinate_graph_corpus_v2(report, case["intake_raw"], **arguments)


def _export_wire_corpus_v2(case, report, ordinal, directory, **changes):
    arguments = _custody_arguments(case)
    arguments["expected_report_sha256"] = adapter.coordinate_graph_corpus_sha256(report)
    arguments.update(changes)
    return adapter.export_coordinate_graph_corpus_output_v2(
        report, ordinal, directory, case["intake_raw"], **arguments)


def _wire_corpus_original_drift(case):
    case["intake_inputs"]["join_originals"]["source_metadata_bytes"]["README.md"] += b"authored corpus metadata drift"


def _assert_wire_corpus_unreviewed(report):
    _assert_coordinate_corpus_unreviewed(report)
    assert report["schema"] == _WIRE_CORPUS_SCHEMA
    assert report["source_compatibility_profile"] == _WIRE_CORPUS_PROFILE
    assert report["metadata_profile"] == _WIRE_CORPUS_METADATA
    assert report["consumer_eligible"] is False and report["atomic_snapshot_verified"] is False
    assert report["coordinate_to_graph_source_correspondence"] == "unverified_no_independent_crosswalk"
    assert report["current_source_release_correspondence"] == "unverified_no_independent_crosswalk"

    def check(value):
        if type(value) is dict:
            for key, item in value.items():
                if key.endswith("_mask"):
                    assert type(item) is int and item == 0
                elif key == "field_masks":
                    assert type(item) is dict and all(type(mask) is int and mask == 0 for mask in item.values())
                elif key == "authority":
                    assert type(item) is dict and all(type(flag) is bool and flag is False for flag in item.values())
                check(item)
        elif type(value) is list:
            for item in value:
                check(item)

    check(report)


@_custody_supported
@pytest.mark.parametrize("offered", ["object", "bytes"])
def test_wire_corpus_v2_genuine_owners_preserve_canonical_graph_typed_ast_and_raw_carrier(
    wire_corpus_v2_case, monkeypatch, offered,
):
    case = wire_corpus_v2_case
    genuine_graph = _coordinate_intake.validate_coordinate_source_graph_intake_v3
    genuine_adapt = adapter.adapt_proposed_graph_bytes
    genuine_candidate = adapter.validate_proposed_graph_candidate
    calls = {"graph": [], "adapt": [], "candidate": []}

    def graph(*args, **kwargs):
        result = genuine_graph(*args, **kwargs)
        calls["graph"].append(result)
        return result

    def adapt(*args, **kwargs):
        result = genuine_adapt(*args, **kwargs)
        calls["adapt"].append(result)
        return result

    def candidate(*args, **kwargs):
        result = genuine_candidate(*args, **kwargs)
        calls["candidate"].append(result)
        return result

    monkeypatch.setattr(_coordinate_intake, "validate_coordinate_source_graph_intake_v3", graph)
    monkeypatch.setattr(adapter, "adapt_proposed_graph_bytes", adapt)
    monkeypatch.setattr(adapter, "validate_proposed_graph_candidate", candidate)
    before = deepcopy(case["intake_inputs"]), deepcopy(case["output_inputs"])
    report = _prepare_wire_corpus_v2(case)
    assert len(calls["graph"]) == 2 and len(calls["candidate"]) == 2
    assert len(calls["adapt"]) >= 4
    assert report["counts"] == {"physical_rows": 1, "row_references": 1,
        "output_occurrences": 2, "candidate_outputs": 2, "unresolved_outputs": 0}
    assert report["source_metadata_intake_sha256"] == case["upstream"]["joined"]["source_metadata_intake_sha256"]
    assert report["physical_rows"] == case["intake"]["physical_rows"]
    assert report["row_references"] == case["intake"]["row_references"]
    assert report["intake_report_raw_utf8"].encode("utf-8") == case["intake_raw"]
    raw_intake = json.loads(report["intake_report_raw_utf8"])
    assert raw_intake["eligibility_report_raw_utf8"].encode("utf-8") == case["upstream"]["eligibility_raw"]
    retained_eligibility = json.loads(raw_intake["eligibility_report_raw_utf8"])
    assert retained_eligibility["join_manifest_raw_utf8"].encode("utf-8") == case["upstream"]["join_raw"]
    retained_join = json.loads(retained_eligibility["join_manifest_raw_utf8"])
    assert retained_join["paired_bundles"][0]["payload_intake"]["source_coordinates"] == \
        case["upstream"]["joined"]["paired_bundles"][0]["payload_intake"]["source_coordinates"]
    for output, original in zip(report["output_occurrences"], case["intake"]["output_occurrences"]):
        assert output["intake_output"] == original
        assert {field: output[field] for field in _CUSTODY_IDENTITY} == {
            field: original[field] for field in _CUSTODY_IDENTITY}
        stored = output["candidate"]
        assert stored["proposal_record"]["proposal_json"].encode("utf-8") == canonical_dag_json_bytes(original["graph"])
        assert json.loads(stored["proposal_record"]["proposal_json"]) == original["graph"]
        assert stored["ast_record"]["ast"] == original["graph_request"]["ast"] == proposed.graph_to_ast(original["graph"])
        assert stored["ast_record"]["ast"] == original["eligibility_output"]["canonical_ir"]
        assert "intake_report_raw_utf8" not in output and "intake_report_raw_utf8" not in stored
    assert (case["intake_inputs"], case["output_inputs"]) == before
    assert _validate_wire_corpus_v2(case, _custody_wire(report) if offered == "bytes" else report) == report
    assert len(calls["graph"]) == 4
    _assert_wire_corpus_unreviewed(report)


@_custody_repeated
def test_wire_corpus_v2_repeated_equal_text_keeps_physical_routes_and_raw_output_slots(wire_corpus_v2_case):
    case = wire_corpus_v2_case
    report = _prepare_wire_corpus_v2(case)
    outputs = report["output_occurrences"]
    assert len(report["physical_rows"]) == len(report["row_references"]) == 2
    assert report["physical_rows"][0]["source_text"] == report["physical_rows"][1]["source_text"]
    assert len(outputs) == len(case["output_inputs"]) == 4
    assert [row["output_occurrence_ordinal"] for row in outputs] == [0, 1, 2, 3]
    assert [row["intake_output"]["source_coordinate_span_index"] for row in outputs] == [1, 1, 3, 3]
    assert len({row["physical_identity_sha256"] for row in outputs}) == 2
    assert len({row["candidate"]["source_occurrence"]["record_cid"] for row in outputs}) == 2
    assert [row["route"] for row in outputs] == ["compiler.formal_outputs", "compiler.canonical_formal_outputs"] * 2
    assert [row["intake_output"] for row in outputs] == case["intake"]["output_occurrences"]
    assert [row["intake_output"]["eligibility_output"] for row in outputs] == case["upstream"]["eligibility"]["output_occurrences"]
    assert _validate_wire_corpus_v2(case, report) == report
    _assert_wire_corpus_unreviewed(report)


def test_wire_corpus_v2_unsupported_outputs_keep_every_slot_and_refuse_export(wire_corpus_v2_case, tmp_path):
    case = wire_corpus_v2_case
    assert case["intake"]["output_occurrences"]
    assert all(row["graph"] is None for row in case["intake"]["output_occurrences"])
    report = _prepare_wire_corpus_v2(case)
    assert [row["intake_output"] for row in report["output_occurrences"]] == case["intake"]["output_occurrences"]
    assert len(report["output_occurrences"]) == len(case["output_inputs"])
    assert all(row["candidate"] is None and row["disposition"] == "unresolved"
        and row["custody_issues"] == [{"code": "upstream_graph_unresolved"}]
        for row in report["output_occurrences"])
    assert all(all(slot[field] is None for field in _CUSTODY_FIELDS) for slot in case["output_inputs"])
    destination = tmp_path / "wire-corpus-unsupported"
    with pytest.raises(ValueError):
        _export_wire_corpus_v2(case, report, 0, destination)
    assert not destination.exists()
    _assert_wire_corpus_unreviewed(report)


@_custody_supported
def test_wire_corpus_v2_export_uses_real_writer_readback_and_four_graph_validations(
    wire_corpus_v2_case, monkeypatch, tmp_path,
):
    case = wire_corpus_v2_case
    report = _prepare_wire_corpus_v2(case)
    genuine_export = adapter.export_proposed_graph_candidate
    genuine_graph = _coordinate_intake.validate_coordinate_source_graph_intake_v3
    exports, graphs = [], []

    def export(*args, **kwargs):
        result = genuine_export(*args, **kwargs)
        exports.append(result)
        return result

    def graph(*args, **kwargs):
        result = genuine_graph(*args, **kwargs)
        graphs.append(result)
        return result

    monkeypatch.setattr(adapter, "export_proposed_graph_candidate", export)
    monkeypatch.setattr(_coordinate_intake, "validate_coordinate_source_graph_intake_v3", graph)
    destination = tmp_path / "wire-corpus-output"
    receipt = _export_wire_corpus_v2(case, report, 1, destination)
    selected = report["output_occurrences"][1]
    assert len(graphs) == 4 and exports == [receipt["graph_manifest"]]
    assert receipt["schema"] == _WIRE_CORPUS_EXPORT_SCHEMA
    assert receipt["source_compatibility_profile"] == _WIRE_CORPUS_PROFILE
    assert receipt["metadata_profile"] == _WIRE_CORPUS_METADATA
    assert receipt["source_metadata_intake_sha256"] == report["source_metadata_intake_sha256"]
    assert receipt["corpus_report_sha256"] == adapter.coordinate_graph_corpus_sha256(report)
    assert {field: receipt[field] for field in _CUSTODY_IDENTITY} == {field: selected[field] for field in _CUSTODY_IDENTITY}
    assert receipt["candidate_record_cid"] == selected["candidate"]["record_cid"]
    assert receipt["graph_manifest_sha256"] == sha(canonical_dag_json_bytes(receipt["graph_manifest"]))
    loaded = load_graph_bundle(destination, expected_manifest_sha256=receipt["graph_manifest_sha256"])
    assert loaded["snapshot"] == selected["candidate"]["graph"]
    assert {path.name for path in destination.iterdir()} == _WIRE_CORPUS_BUNDLE_FILES
    assert receipt["snapshot_cid"] == selected["candidate"]["graph"]["record_cid"]
    assert receipt["delegated_writer_readback_performed"] is True
    assert receipt["full_candidate_retained_separately_required"] is True
    assert receipt["selected_occurrence"] is None and receipt["atomic_snapshot_verified"] is False
    assert receipt["consumer_eligible"] is False
    assert receipt["coordinate_to_graph_source_correspondence"] == "unverified_no_independent_crosswalk"
    assert all(type(flag) is bool and flag is False for flag in receipt["authority"].values())
    for field in ("training_mask", "evaluation_gold_mask", "source_binding_mask"):
        assert type(receipt[field]) is int and receipt[field] == 0


@_custody_supported
@pytest.mark.parametrize("route", ["old-v2-into-new-v2", "wire-v3-into-old-v1"])
def test_wire_corpus_v2_and_old_v1_refuse_genuine_foreign_graph_routes(request, coordinate_join, monkeypatch, route):
    case = request.getfixturevalue("coordinate_corpus_case" if route == "old-v2-into-new-v2" else "wire_corpus_v2_case")
    monkeypatch.setattr(adapter, "adapt_proposed_graph_bytes",
        lambda *args, **kwargs: pytest.fail("foreign graph route reached corpus candidate adapter"))
    with pytest.raises(ValueError):
        (_prepare_wire_corpus_v2 if route == "old-v2-into-new-v2" else _prepare_coordinate_corpus)(case)


@_custody_supported
@pytest.mark.parametrize("axis", ["metadata_profile", "source_metadata_intake_sha256"])
def test_wire_corpus_v2_resealed_metadata_axes_cannot_replace_genuine_ancestry(wire_corpus_v2_case, monkeypatch, axis):
    case = wire_corpus_v2_case
    case["intake"][axis] = "foreign-wire-profile" if axis == "metadata_profile" else "0" * 64
    case["intake_raw"] = _custody_wire(case["intake"])
    monkeypatch.setattr(adapter, "adapt_proposed_graph_bytes",
        lambda *args, **kwargs: pytest.fail("resealed metadata reached corpus candidate adapter"))
    with pytest.raises(ValueError):
        _prepare_wire_corpus_v2(case)


@_custody_supported
@pytest.mark.parametrize("pin", ["expected_intake_raw_sha256", "expected_intake_sha256",
    "expected_intake_inputs_sha256", "expected_output_inputs_sha256"])
def test_wire_corpus_v2_checks_all_four_independent_pins(wire_corpus_v2_case, pin):
    with pytest.raises(ValueError):
        _prepare_wire_corpus_v2(wire_corpus_v2_case, **{pin: "0" * 64})


@_custody_repeated
@pytest.mark.parametrize("damage", ["drop", "reorder", "identity", "boolean_ordinal"])
def test_wire_corpus_v2_recommitted_slots_require_exact_complete_ordered_population(wire_corpus_v2_case, damage):
    case = wire_corpus_v2_case
    if damage == "drop":
        case["output_inputs"].pop()
    elif damage == "reorder":
        case["output_inputs"].reverse()
    elif damage == "identity":
        case["output_inputs"][0]["physical_identity_sha256"] = "0" * 64
    else:
        case["output_inputs"][0]["output_occurrence_ordinal"] = True
    with pytest.raises(ValueError):
        _prepare_wire_corpus_v2(case, expected_output_inputs_sha256=sha(_custody_wire(case["output_inputs"])))


@_custody_repeated
@pytest.mark.parametrize("damage", ["reference", "mask", "candidate"])
def test_wire_corpus_v2_rehashed_report_requires_genuine_complete_regeneration(wire_corpus_v2_case, damage):
    case = wire_corpus_v2_case
    report = _prepare_wire_corpus_v2(case)
    if damage == "reference":
        report["row_references"].reverse()
    elif damage == "mask":
        report["output_occurrences"][0]["training_mask"] = True
    else:
        candidate = report["output_occurrences"][0]["candidate"]
        candidate["ast_record"]["ast"]["rules"][0]["actor"] = "resealed foreign actor"
        candidate["ast_record"] = reseal(candidate["ast_record"])
        report["output_occurrences"][0]["candidate"] = reseal(candidate)
    with pytest.raises(ValueError):
        _validate_wire_corpus_v2(case, report)


@_custody_supported
@pytest.mark.parametrize("damage", ["metadata_original", "source_binding", "output_slot", "producer", "physical_table"])
def test_wire_corpus_v2_late_mutation_during_genuine_adapter_is_refused(wire_corpus_v2_case, monkeypatch, damage):
    case = wire_corpus_v2_case
    genuine = adapter.adapt_proposed_graph_bytes
    calls, changed = [], []

    def mutate(*args, **kwargs):
        candidate = genuine(*args, **kwargs)
        calls.append(candidate)
        if not changed:
            changed.append(damage)
            if damage == "metadata_original":
                _wire_corpus_original_drift(case)
            elif damage == "source_binding":
                next(iter(case["intake_inputs"]["source_bindings"].values()))["context_observation"]["status"] = "late changed"
            elif damage == "output_slot":
                case["output_inputs"][0]["trusted_proposal_inputs"]["ast"]["rules"][0]["actor"] = "late changed"
            elif damage == "producer":
                monkeypatch.setattr(_coordinate_intake, "validate_coordinate_source_graph_intake_v3",
                    lambda *args, **kwargs: pytest.fail("changed producer callback was invoked"))
            else:
                path = _coordinate_graph_retained_table(case["upstream"])
                path.write_bytes(path.read_bytes() + b"changed during genuine corpus adaptation")
        return candidate

    monkeypatch.setattr(adapter, "adapt_proposed_graph_bytes", mutate)
    with pytest.raises(ValueError):
        _prepare_wire_corpus_v2(case)
    assert calls and changed == [damage]


@_custody_supported
def test_wire_corpus_v2_primary_error_retains_observed_genuine_closing_failure(wire_corpus_v2_case, monkeypatch):
    case = wire_corpus_v2_case
    genuine_adapt = adapter.adapt_proposed_graph_bytes
    genuine_graph = _coordinate_intake.validate_coordinate_source_graph_intake_v3
    primary = RuntimeError("authored wire corpus adaptation primary failure")
    attempts, failures, candidates = [], [], []

    def graph(*args, **kwargs):
        attempts.append(True)
        try:
            return genuine_graph(*args, **kwargs)
        except BaseException as error:
            failures.append(error)
            raise

    def fail(*args, **kwargs):
        candidate = genuine_adapt(*args, **kwargs)
        candidates.append(candidate)
        path = _coordinate_graph_retained_table(case["upstream"])
        path.write_bytes(path.read_bytes() + b"authored closing failure after real candidate")
        raise primary

    monkeypatch.setattr(_coordinate_intake, "validate_coordinate_source_graph_intake_v3", graph)
    monkeypatch.setattr(adapter, "adapt_proposed_graph_bytes", fail)
    with pytest.raises(RuntimeError, match="authored wire corpus adaptation primary failure") as observed:
        _prepare_wire_corpus_v2(case)
    assert observed.value is primary and candidates
    assert len(attempts) == 2 and len(failures) == 1
    detail = type(failures[0]).__name__ + ": " + str(failures[0])[:512]
    assert any(detail in note for note in getattr(primary, "__notes__", ()))


@_custody_supported
def test_wire_corpus_v2_opening_graph_return_stays_guarded_after_genuine_closing(wire_corpus_v2_case, monkeypatch):
    case = wire_corpus_v2_case
    genuine = _coordinate_intake.validate_coordinate_source_graph_intake_v3
    returned, changed = [], []

    def mutate(*args, **kwargs):
        result = genuine(*args, **kwargs)
        returned.append(result)
        if len(returned) == 2:
            returned[0]["output_occurrences"][0]["training_mask"] = 1
            changed.append(True)
        return result

    monkeypatch.setattr(_coordinate_intake, "validate_coordinate_source_graph_intake_v3", mutate)
    with pytest.raises(ValueError):
        _prepare_wire_corpus_v2(case)
    assert changed == [True] and len(returned) == 2


@_custody_supported
@pytest.mark.parametrize("returned_kind", ["adapter", "checked"])
def test_wire_corpus_v2_genuine_candidate_return_stays_guarded_after_genuine_closing(wire_corpus_v2_case, monkeypatch, returned_kind):
    case = wire_corpus_v2_case
    genuine_adapt = adapter.adapt_proposed_graph_bytes
    genuine_validate = adapter.validate_proposed_graph_candidate
    genuine_graph = _coordinate_intake.validate_coordinate_source_graph_intake_v3
    candidates, checked, graphs, changed = [], [], [], []

    def adapt(*args, **kwargs):
        result = genuine_adapt(*args, **kwargs)
        candidates.append(result)
        return result

    def validate(*args, **kwargs):
        result = genuine_validate(*args, **kwargs)
        checked.append(result)
        return result

    def graph(*args, **kwargs):
        result = genuine_graph(*args, **kwargs)
        graphs.append(result)
        if len(graphs) == 2:
            assert candidates and checked and candidates[0] is not checked[0]
            held = candidates if returned_kind == "adapter" else checked
            held[0]["ast_record"]["ast"]["rules"][0]["actor"] = "changed held genuine " + returned_kind
            changed.append(True)
        return result

    monkeypatch.setattr(adapter, "adapt_proposed_graph_bytes", adapt)
    monkeypatch.setattr(adapter, "validate_proposed_graph_candidate", validate)
    monkeypatch.setattr(_coordinate_intake, "validate_coordinate_source_graph_intake_v3", graph)
    with pytest.raises(ValueError):
        _prepare_wire_corpus_v2(case)
    assert changed == [True] and len(graphs) == 2


@_custody_supported
def test_wire_corpus_v2_validator_keeps_offered_report_guarded_during_genuine_adapter(wire_corpus_v2_case, monkeypatch):
    case = wire_corpus_v2_case
    report = _prepare_wire_corpus_v2(case)
    genuine = adapter.adapt_proposed_graph_bytes
    reached = []

    def mutate(*args, **kwargs):
        result = genuine(*args, **kwargs)
        report["output_occurrences"][0]["source_binding_mask"] = 1
        reached.append(True)
        return result

    monkeypatch.setattr(adapter, "adapt_proposed_graph_bytes", mutate)
    with pytest.raises(ValueError):
        _validate_wire_corpus_v2(case, report)
    assert reached


@_custody_supported
@pytest.mark.parametrize("damage", ["originals", "slots"])
def test_wire_corpus_v2_outer_validator_keeps_inputs_after_genuine_inner_prepare(wire_corpus_v2_case, monkeypatch, damage):
    case = wire_corpus_v2_case
    report = _prepare_wire_corpus_v2(case)
    genuine = adapter._prepare_coordinate_graph_corpus
    changed = []

    def mutate(*args, **kwargs):
        result = genuine(*args, **kwargs)
        assert kwargs["profile_version"] == 2
        if damage == "originals":
            _wire_corpus_original_drift(case)
        else:
            case["output_inputs"][0]["trusted_proposal_inputs"]["ast"]["rules"][0]["actor"] = "changed after real inner prepare"
        changed.append(True)
        return result

    monkeypatch.setattr(adapter, "_prepare_coordinate_graph_corpus", mutate)
    with pytest.raises(ValueError):
        _validate_wire_corpus_v2(case, report)
    assert changed == [True]


@_custody_supported
def test_wire_corpus_v2_outer_parsed_intake_cannot_nominate_a_foreign_file(wire_corpus_v2_case, monkeypatch):
    case = wire_corpus_v2_case
    report = _prepare_wire_corpus_v2(case)
    genuine_read = adapter._corpus_read
    genuine_prepare = adapter._prepare_coordinate_graph_corpus
    genuine_plan = adapter._corpus_wire_physical_plan
    parsed, changed, plans = [], [], []
    sentinel = "unselected/outer-wire-corpus-validator.parquet"

    def read(*args, **kwargs):
        result = genuine_read(*args, **kwargs)
        if len(args) > 2 and args[2] == "coordinate graph intake":
            parsed.append(result)
        return result

    def mutate(*args, **kwargs):
        result = genuine_prepare(*args, **kwargs)
        assert kwargs["profile_version"] == 2 and len(parsed) >= 2
        eligibility = json.loads(parsed[0]["eligibility_report_raw_utf8"])
        joined = json.loads(eligibility["join_manifest_raw_utf8"])
        joined["span_inventory"]["manifests"][0]["manifest"]["tables"]["paired_spans"]["path_in_repo"] = sentinel
        eligibility["join_manifest_raw_utf8"] = _custody_wire(joined).decode("utf-8")
        parsed[0]["eligibility_report_raw_utf8"] = _custody_wire(eligibility).decode("utf-8")
        changed.append(True)
        return result

    def plan(*args, **kwargs):
        assert not changed, "mutated outer parsed intake reached physical file nomination"
        plans.append(True)
        return genuine_plan(*args, **kwargs)

    monkeypatch.setattr(adapter, "_corpus_read", read)
    monkeypatch.setattr(adapter, "_prepare_coordinate_graph_corpus", mutate)
    monkeypatch.setattr(adapter, "_corpus_wire_physical_plan", plan)
    with pytest.raises(ValueError):
        _validate_wire_corpus_v2(case, report)
    assert changed == [True] and plans


@_custody_supported
@pytest.mark.parametrize("damage", ["originals", "detached_report"])
def test_wire_corpus_v2_postclosing_serialization_keeps_originals_and_detached_return_guarded(wire_corpus_v2_case, monkeypatch, damage):
    case = wire_corpus_v2_case
    genuine_graph = _coordinate_intake.validate_coordinate_source_graph_intake_v3
    genuine_read, genuine_wire = adapter._corpus_read, adapter._corpus_wire
    graphs, detached, changed = [], [], []

    def graph(*args, **kwargs):
        result = genuine_graph(*args, **kwargs)
        graphs.append(result)
        return result

    def read(*args, **kwargs):
        result = genuine_read(*args, **kwargs)
        if type(result) is dict and result.get("schema") == _WIRE_CORPUS_SCHEMA:
            detached.append(result)
        return result

    def wire(value, *args, **kwargs):
        raw = genuine_wire(value, *args, **kwargs)
        eligible = type(value) is dict and value.get("schema") == _WIRE_CORPUS_SCHEMA
        if damage == "detached_report":
            eligible = eligible and any(value is item for item in detached)
        if len(graphs) == 2 and eligible and not changed:
            if damage == "originals":
                _wire_corpus_original_drift(case)
            else:
                value["counts"]["candidate_outputs"] += 1
            changed.append(True)
        return raw

    monkeypatch.setattr(_coordinate_intake, "validate_coordinate_source_graph_intake_v3", graph)
    monkeypatch.setattr(adapter, "_corpus_read", read)
    monkeypatch.setattr(adapter, "_corpus_wire", wire)
    with pytest.raises(ValueError):
        _prepare_wire_corpus_v2(case)
    assert changed == [True] and len(graphs) == 2
    if damage == "detached_report":
        assert detached


@_custody_supported
@pytest.mark.parametrize("ordinal", [True, -1, 2], ids=["boolean", "negative", "out_of_range"])
def test_wire_corpus_v2_export_requires_plain_in_range_resolved_ordinal(wire_corpus_v2_case, monkeypatch, tmp_path, ordinal):
    case = wire_corpus_v2_case
    report = _prepare_wire_corpus_v2(case)
    monkeypatch.setattr(adapter, "export_proposed_graph_candidate",
        lambda *args, **kwargs: pytest.fail("invalid wire ordinal reached real graph writer"))
    destination = tmp_path / "refused-wire-ordinal"
    with pytest.raises(ValueError):
        _export_wire_corpus_v2(case, report, ordinal, destination)
    assert not destination.exists()


@_custody_supported
def test_wire_corpus_v2_real_writer_closing_drift_retains_four_unqualified_files(wire_corpus_v2_case, monkeypatch, tmp_path):
    case = wire_corpus_v2_case
    report = _prepare_wire_corpus_v2(case)
    genuine = adapter.export_proposed_graph_candidate
    exports = []

    def mutate(*args, **kwargs):
        result = genuine(*args, **kwargs)
        exports.append(result)
        path = _coordinate_graph_retained_table(case["upstream"])
        path.write_bytes(path.read_bytes() + b"changed after real wire graph writer")
        return result

    monkeypatch.setattr(adapter, "export_proposed_graph_candidate", mutate)
    destination = tmp_path / "written-wire-but-unqualified"
    with pytest.raises(ValueError):
        _export_wire_corpus_v2(case, report, 0, destination)
    assert len(exports) == 1 and {path.name for path in destination.iterdir()} == _WIRE_CORPUS_BUNDLE_FILES
    retained = load_graph_bundle(destination, expected_manifest_sha256=sha(canonical_dag_json_bytes(exports[0])))
    assert retained["snapshot"] == report["output_occurrences"][0]["candidate"]["graph"]


@_custody_supported
@pytest.mark.parametrize("damage", ["offered_report", "physical_bundle"])
def test_wire_corpus_v2_postwriter_report_or_bundle_drift_refuses_receipt_without_repair(wire_corpus_v2_case, monkeypatch, tmp_path, damage):
    case = wire_corpus_v2_case
    report = _prepare_wire_corpus_v2(case)
    genuine = adapter.export_proposed_graph_candidate
    destination = tmp_path / "wire-export-late-drift"
    changed, written = [], []

    def mutate(*args, **kwargs):
        result = genuine(*args, **kwargs)
        written.append(result)
        if damage == "offered_report":
            report["output_occurrences"][0]["training_mask"] = 1
        else:
            path = destination / "edges.parquet"
            path.write_bytes(path.read_bytes() + b"authored late bundle drift")
            changed.append(path.read_bytes())
        return result

    monkeypatch.setattr(adapter, "export_proposed_graph_candidate", mutate)
    with pytest.raises(ValueError):
        _export_wire_corpus_v2(case, report, 0, destination)
    assert len(written) == 1 and {path.name for path in destination.iterdir()} == _WIRE_CORPUS_BUNDLE_FILES
    if damage == "physical_bundle":
        assert changed == [(destination / "edges.parquet").read_bytes()]
    else:
        retained = load_graph_bundle(destination, expected_manifest_sha256=sha(canonical_dag_json_bytes(written[0])))
        assert retained["snapshot"] == report["output_occurrences"][0]["candidate"]["graph"]


@_custody_supported
@pytest.mark.parametrize("returned_kind", ["writer_manifest", "loader_readback"])
def test_wire_corpus_v2_genuine_export_returns_stay_guarded_after_genuine_closing(
    wire_corpus_v2_case, monkeypatch, tmp_path, returned_kind,
):
    case = wire_corpus_v2_case
    report = _prepare_wire_corpus_v2(case)
    genuine_export = adapter.export_proposed_graph_candidate
    genuine_witness = adapter._corpus_wire_export_witness
    genuine_graph = _coordinate_intake.validate_coordinate_source_graph_intake_v3
    manifests, manifest_pins, readbacks, graphs, changed = [], [], [], [], []

    def export(*args, **kwargs):
        result = genuine_export(*args, **kwargs)
        manifests.append(result)
        manifest_pins.append(sha(canonical_dag_json_bytes(result)))
        return result

    def witness(*args, **kwargs):
        result = genuine_witness(*args, **kwargs)
        readbacks.append(result[1])
        return result

    def graph(*args, **kwargs):
        result = genuine_graph(*args, **kwargs)
        graphs.append(result)
        if len(graphs) == 4:
            assert manifests and readbacks
            if returned_kind == "writer_manifest":
                manifests[0]["snapshot_cid"] = "changed held genuine writer return"
            else:
                readbacks[0]["snapshot"]["record_cid"] = "changed held genuine loader return"
            changed.append(returned_kind)
        return result

    monkeypatch.setattr(adapter, "export_proposed_graph_candidate", export)
    monkeypatch.setattr(adapter, "_corpus_wire_export_witness", witness)
    monkeypatch.setattr(_coordinate_intake, "validate_coordinate_source_graph_intake_v3", graph)
    destination = tmp_path / "wire-held-export-return"
    with pytest.raises(ValueError):
        _export_wire_corpus_v2(case, report, 0, destination)
    assert changed == [returned_kind] and len(graphs) == 4
    assert {path.name for path in destination.iterdir()} == _WIRE_CORPUS_BUNDLE_FILES
    # Return-object tampering leaves the genuine physical writer output intact.
    retained = load_graph_bundle(destination, expected_manifest_sha256=manifest_pins[0])
    assert retained["snapshot"] == report["output_occurrences"][0]["candidate"]["graph"]


@_custody_supported
def test_wire_corpus_v2_final_receipt_serialization_keeps_original_inputs_guarded(wire_corpus_v2_case, monkeypatch, tmp_path):
    case = wire_corpus_v2_case
    report = _prepare_wire_corpus_v2(case)
    genuine_graph = _coordinate_intake.validate_coordinate_source_graph_intake_v3
    genuine_wire = adapter._corpus_wire
    graphs, changed = [], []

    def graph(*args, **kwargs):
        result = genuine_graph(*args, **kwargs)
        graphs.append(result)
        return result

    def wire(value, *args, **kwargs):
        raw = genuine_wire(value, *args, **kwargs)
        if len(graphs) == 4 and not changed and type(value) is dict and value.get("schema") == _WIRE_CORPUS_EXPORT_SCHEMA:
            _wire_corpus_original_drift(case)
            changed.append(True)
        return raw

    monkeypatch.setattr(_coordinate_intake, "validate_coordinate_source_graph_intake_v3", graph)
    monkeypatch.setattr(adapter, "_corpus_wire", wire)
    destination = tmp_path / "wire-receipt-final-drift"
    with pytest.raises(ValueError):
        _export_wire_corpus_v2(case, report, 0, destination)
    assert changed == [True] and len(graphs) == 4
    assert {path.name for path in destination.iterdir()} == _WIRE_CORPUS_BUNDLE_FILES
