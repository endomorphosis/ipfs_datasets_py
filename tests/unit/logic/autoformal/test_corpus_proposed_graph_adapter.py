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
