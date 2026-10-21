"""Tiny physical plaintext fixtures through proposed graphs and corpus custody.

The original parent/cache fixture owns parsing and physical replay. These tests
add graph handoffs only; their authored declarations are not legal gold.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_parent_occurrence_adapter as parent_owner
from ipfs_datasets_py.logic.autoformal import corpus_proposed_graph_adapter as adapter
from ipfs_datasets_py.logic.autoformal import corpus_source
from ipfs_datasets_py.logic.autoformal import legal_semantic_graph as proposed
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as official_context
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes


TEXT = "雪 é e\u0301 é. "


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def helper(name):
    """Import sibling authored fixtures while using actual public owners."""
    spec = importlib.util.spec_from_file_location(
        "plaintext_graph_fixture_" + name, Path(__file__).with_name(name + ".py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reseal(record):
    return contracts.seal_record({key: deepcopy(value) for key, value in record.items()
        if key not in {"record_cid", "cid_scope"}})


def reseal_binding(source):
    source["source_binding_sha256"] = proposed.digest(
        {key: value for key, value in source.items() if key != "source_binding_sha256"})
    return source


@pytest.fixture
def literal_case(tmp_path):
    data = helper("test_corpus_parent_occurrence_adapter").case(
        tmp_path, source_text="é", parent_texts=[TEXT, TEXT])
    bundle = parent_owner.build_parent_occurrence_corpus(**data["arguments"])
    return {"data": data, "bundle": bundle,
        "records": {record["record_cid"]: record for record in bundle["records"]}}


def companions(case, kind):
    return [record for record in case["bundle"]["records"] if record["schema"] == kind]


def binding_arguments(case, companion=None):
    if companion is None:
        cid = case["bundle"]["manifest"]["populations"]["roles"]["region"][0]
        companion = case["records"][cid]
    return {"parent_bundle": case["bundle"],
        "expected_manifest_cid": case["bundle"]["manifest"]["record_cid"],
        "source_occurrence_cid": companion["source_occurrence_cid"],
        "companion_record_cid": companion["record_cid"], **case["data"]["arguments"]}


def bind(case, companion=None):
    arguments = binding_arguments(case, companion)
    bundle = arguments.pop("parent_bundle")
    return proposed.bind_parent_source_occurrence(bundle, **arguments)


def declarations(case, source):
    matches = companions(case, parent_owner.MATCH_SCHEMA)
    ids = {record["source_occurrence_cid"] for record in matches
        if record["source_version_cid"] == source["source_version"]["record_cid"]}
    occurrences = sorted((case["records"][cid] for cid in ids), key=lambda row: row["start_char"])
    assert len(occurrences) == 2
    entities = [{"entity_key": "mention-" + str(index), "kind": "mention", "label": "é",
        "source_selector": deepcopy(occurrence), "definition_kind": None,
        "ast_path": "/rules/0", "ambiguity": ["authored unresolved mention"], "evidence_refs": []}
        for index, occurrence in enumerate(occurrences)]
    entities.append({"entity_key": "concept", "kind": "concept", "label": "é",
        "source_selector": None, "definition_kind": None, "ast_path": None,
        "ambiguity": ["authored unresolved concept"], "evidence_refs": []})
    return {"entities": entities, "assertions": [{"assertion_key": "declared-denotation",
        "subject_key": "mention-0", "predicate": "denotes", "object_keys": ["concept", "concept"],
        "ambiguity": ["unreviewed declaration"], "evidence_refs": [], "dependency_refs": []}]}


def proposal_case(case, *, relational=False):
    source = bind(case)
    scope = proposed.bind_parent_scope(source=source, jurisdiction="US-federal",
        instrument="authored-parent-fixture", applicability="unresolved",
        definition_scope="unresolved")
    ast = {"rules": [
        {"modality": "P", "actor": "é", "action": "file", "object": "notice",
            "conditions": [], "exceptions": [], "temporal": []},
        {"modality": "O", "actor": "é", "action": "retain", "object": "records",
            "conditions": ["b", "a", "b"], "exceptions": ["waived"], "temporal": ["T"]}]}
    semantics = declarations(case, source)
    if relational:
        ast = helper("test_legal_relational_norm_v1").approval_request()
        semantics = None
    inputs = {"ast": ast, "profile": "relational_norm_v1" if relational else "canonical_rules_v1",
        "source": source, "scope": scope, "semantic_declarations": semantics,
        "dependency_refs": [], "evidence_refs": [], "scope_request": None}
    graph = proposed.build_graph(**inputs)
    raw = json.dumps(graph, ensure_ascii=False, indent=2).encode("utf-8")
    arguments = {"expected_proposal_sha256": sha(raw), "trusted_proposal_inputs": inputs,
        "expected_inputs_sha256": sha(canonical_dag_json_bytes(inputs)), **binding_arguments(case)}
    return raw, graph, arguments


def test_plaintext_roundtrip_retains_original_records_and_unavailable_context(literal_case, monkeypatch):
    def no_markup(*args, **kwargs):
        pytest.fail("literal parent graph must not synthesize or extract HTML")
    monkeypatch.setattr(official_context, "extract_document", no_markup)
    original_bundle = canonical_dag_json_bytes(literal_case["bundle"])
    raw, graph, arguments = proposal_case(literal_case)
    candidate = adapter.adapt_parent_proposed_graph_bytes(raw, **arguments)
    source = arguments["trusted_proposal_inputs"]["source"]
    assert source["schema"] == proposed.PARENT_SOURCE_SCHEMA
    assert source["edition"] == parent_owner.UNDECLARED_EDITION
    assert source["source_version"]["edition"] == parent_owner.UNDECLARED_EDITION
    assert source["source_version"]["raw_artifact"]["media_type"] == "text/plain"
    assert source["source_version"]["raw_artifact"]["sha256"] == sha(TEXT.encode("utf-8"))
    assert source["source_version"]["extracted_view"]["normalization_profile"] == "identity/v1"
    assert source["selector"]["span_text"] == TEXT
    assert candidate["source_version"] == source["source_version"]
    assert candidate["source_occurrence"] == source["selector"]
    assert candidate["parent_source_binding"] == source
    assert source["context"]["availability"] == "required_unavailable"
    assert source["context"]["missing_requirements"] == list(parent_owner.MISSING_CONTEXT)
    assert source["context"]["dependency_verification"] == "declaration_only"
    assert source["companion_record"]["selected_occurrence"] is None
    assert source["companion_record"]["governing_source_binding"] is None
    assert source["cache_row_record"] is None
    scope = arguments["trusted_proposal_inputs"]["scope"]
    assert scope["schema"] == proposed.PARENT_SCOPE_SCHEMA
    assert scope["edition"] == parent_owner.UNDECLARED_EDITION
    assert scope["source_version_cid"] == source["source_version"]["record_cid"]
    assert proposed.graph_to_ast(graph) == arguments["trusted_proposal_inputs"]["ast"]
    assert adapter.restore_proposed_graph_ast(candidate, **arguments) == arguments["trusted_proposal_inputs"]["ast"]
    assert candidate["proposal_record"]["proposal_json"].encode("utf-8") == raw
    assert candidate["ast_record"]["ast"]["rules"][1]["conditions"] == ["b", "a", "b"]
    assert graph["entities"][0]["entity_id"] != graph["entities"][1]["entity_id"]
    assert graph["assertions"][0]["object_ids"][0] == graph["assertions"][0]["object_ids"][1]
    assert all(flag is False for flag in graph["authority"].values())
    for key in ("admitted", "formalized", "source_semantics_verified", "source_authenticity_verified",
                "external_references_verified", "definition_semantics_encoded"):
        assert candidate[key] is False
    assert adapter.validate_parent_proposed_graph_candidate(candidate, **arguments) == candidate
    assert canonical_dag_json_bytes(literal_case["bundle"]) == original_bundle


def test_plaintext_candidate_export_and_separate_companion_restore(literal_case, tmp_path):
    from ipfs_datasets_py.logic.autoformal.corpus_graph_exchange import load_graph_bundle
    raw, _, arguments = proposal_case(literal_case)
    candidate = adapter.adapt_parent_proposed_graph_bytes(raw, **arguments)
    companion_raw = canonical_dag_json_bytes(candidate)
    path = tmp_path / "plaintext-candidate.json"
    path.write_bytes(companion_raw)
    output = tmp_path / "plaintext-graph"
    manifest = adapter.export_proposed_graph_candidate(candidate, output, **arguments)
    loaded = load_graph_bundle(output, expected_manifest_sha256=sha(canonical_dag_json_bytes(manifest)))
    retained = contracts.load_record_bytes(path.read_bytes(), expected_sha256=sha(companion_raw))
    assert loaded["snapshot"] == retained["graph"] == candidate["graph"]
    assert retained["parent_source_binding"] == candidate["parent_source_binding"]
    assert adapter.restore_proposed_graph_ast(retained, **arguments) == arguments["trusted_proposal_inputs"]["ast"]
    assert manifest["external_references_verified"] is False


def test_repeated_unicode_and_equal_text_physical_rows_keep_distinct_bindings(literal_case):
    matches = companions(literal_case, parent_owner.MATCH_SCHEMA)
    seen = {}
    for match in matches:
        seen.setdefault(match["source_occurrence_cid"], match)
    sources = [bind(literal_case, match) for match in seen.values()]
    assert len(matches) == 8 and len(sources) == 4
    assert len({source["source_version"]["record_cid"] for source in sources}) == 2
    assert len({source["source_version"]["extracted_view"]["sha256"] for source in sources}) == 1
    assert len({source["parent_record"]["source_identity"]["row_ordinal"] for source in sources}) == 2
    assert len({source["source_binding_sha256"] for source in sources}) == 4
    for version in {source["source_version"]["record_cid"] for source in sources}:
        coordinates = sorted((source["selector"]["start_char"], source["selector"]["end_char"],
            source["selector"]["start_utf8"], source["selector"]["end_utf8"])
            for source in sources if source["source_version"]["record_cid"] == version)
        assert coordinates == [(2, 3, 4, 6), (7, 8, 11, 13)]
    assert all(source["selector"]["span_text"] == "é" for source in sources)
    assert all(source["companion_record"]["selected_occurrence"] is None for source in sources)


def test_distinct_cache_rows_retain_distinct_companions_for_shared_occurrence(literal_case):
    matches = companions(literal_case, parent_owner.MATCH_SCHEMA)
    first = matches[0]
    second = next(match for match in matches if match["source_occurrence_cid"] == first["source_occurrence_cid"]
        and match["cache_row_record_cid"] != first["cache_row_record_cid"])
    left, right = bind(literal_case, first), bind(literal_case, second)
    assert left["selector"] == right["selector"]
    assert left["source_version"] == right["source_version"]
    assert left["companion_record"]["record_cid"] != right["companion_record"]["record_cid"]
    assert left["cache_row_record"]["record_cid"] != right["cache_row_record"]["record_cid"]
    assert left["cache_row_record"]["selected_occurrence"] is right["cache_row_record"]["selected_occurrence"] is None
    assert literal_case["bundle"]["manifest"]["selected_occurrence"] is None


@pytest.mark.parametrize("damage", ["manifest", "occurrence", "companion_kind", "companion_target", "raw_report_pin"])
def test_source_binding_requires_exact_original_pins_and_companion_membership(literal_case, damage):
    arguments = deepcopy(binding_arguments(literal_case))
    parent = companions(literal_case, parent_owner.PARENT_SCHEMA)[0]
    if damage == "manifest":
        arguments["expected_manifest_cid"] = parent["record_cid"]
    elif damage == "occurrence":
        arguments["source_occurrence_cid"] = parent["source_version_cid"]
    elif damage == "companion_kind":
        arguments["companion_record_cid"] = parent["record_cid"]
    elif damage == "companion_target":
        arguments["companion_record_cid"] = companions(literal_case, parent_owner.MATCH_SCHEMA)[0]["record_cid"]
    else:
        arguments["expected_report_pins"]["parent_text_views"]["raw_sha256"] = "0" * 64
    bundle = arguments.pop("parent_bundle")
    with pytest.raises(ValueError):
        proposed.bind_parent_source_occurrence(bundle, **arguments)


@pytest.mark.parametrize("original", ["parent_file", "original_report"])
def test_saved_plaintext_candidate_cannot_outlive_modified_originals(literal_case, original):
    raw, _, arguments = proposal_case(literal_case)
    candidate = adapter.adapt_parent_proposed_graph_bytes(raw, **arguments)
    if original == "parent_file":
        path = Path(arguments["replay_inputs"]["parent_text_views_inputs"]["parent_descriptor"]["local_path"])
        path.write_bytes(path.read_bytes() + b"changed owned fixture")
    else:
        arguments["report_bytes"]["parent_text_views"] += b" "
    with pytest.raises(ValueError):
        adapter.validate_parent_proposed_graph_candidate(candidate, **arguments)


def damage_binding(source, damage):
    if damage == "context":
        source["context"].update(availability="none_required", context_references=[], missing_requirements=[])
        source["context"] = reseal(source["context"])
    elif damage == "utf8":
        source["selector"]["start_utf8"] += 1
        source["selector"]["end_utf8"] += 1
        source["selector"] = reseal(source["selector"])
    elif damage == "edition":
        source["edition"] = 2024
    elif damage == "companion":
        source["companion_record"]["source_occurrence_cid"] = source["source_version"]["record_cid"]
        source["companion_record"] = reseal(source["companion_record"])
    else:
        raise AssertionError(damage)
    return reseal_binding(source)


@pytest.mark.parametrize("damage", ["context", "utf8", "edition", "companion"])
def test_resealed_source_binding_cannot_rewrite_context_geometry_edition_or_companion(literal_case, damage):
    _, _, arguments = proposal_case(literal_case)
    inputs = deepcopy(arguments["trusted_proposal_inputs"])
    damage_binding(inputs["source"], damage)
    with pytest.raises(ValueError):
        proposed.build_graph(**inputs)


@pytest.mark.parametrize("damage", ["utf8", "other_parent", "outside_bound"])
def test_entity_subselectors_bind_exact_parent_occurrence_not_literal_text(literal_case, damage):
    _, _, arguments = proposal_case(literal_case)
    inputs = deepcopy(arguments["trusted_proposal_inputs"])
    entity = inputs["semantic_declarations"]["entities"][0]
    if damage == "utf8":
        entity["source_selector"]["start_utf8"] += 1
        entity["source_selector"]["end_utf8"] += 1
        entity["source_selector"] = reseal(entity["source_selector"])
    elif damage == "other_parent":
        other = next(match for match in companions(literal_case, parent_owner.MATCH_SCHEMA)
            if match["source_version_cid"] != inputs["source"]["source_version"]["record_cid"])
        entity["source_selector"] = deepcopy(literal_case["records"][other["source_occurrence_cid"]])
    else:
        first = next(match for match in companions(literal_case, parent_owner.MATCH_SCHEMA)
            if match["source_occurrence_cid"] == entity["source_selector"]["record_cid"])
        inputs["source"] = bind(literal_case, first)
        # The second exact mention is valid in the field but outside this bound span.
    with pytest.raises(ValueError):
        proposed.build_graph(**inputs)


@pytest.mark.parametrize("damage", ["context", "companion", "authority"])
def test_resealed_candidate_cannot_promote_or_replace_parent_companions(literal_case, damage):
    raw, _, arguments = proposal_case(literal_case)
    candidate = adapter.adapt_parent_proposed_graph_bytes(raw, **arguments)
    if damage == "authority":
        candidate["admitted"] = True
    else:
        damage_binding(candidate["parent_source_binding"], damage)
    candidate = reseal(candidate)
    with pytest.raises(ValueError):
        adapter.validate_parent_proposed_graph_candidate(candidate, **arguments)


@pytest.mark.parametrize("field", ["expected_proposal_sha256", "expected_inputs_sha256"])
def test_parent_adapter_requires_independent_proposal_and_input_pins(literal_case, field):
    raw, _, arguments = proposal_case(literal_case)
    arguments[field] = "0" * 64
    with pytest.raises(ValueError):
        adapter.adapt_parent_proposed_graph_bytes(raw, **arguments)


def test_coherently_resealed_physical_row_still_requires_original_parent_replay(literal_case):
    _, _, arguments = proposal_case(literal_case)
    inputs = deepcopy(arguments["trusted_proposal_inputs"])
    source = inputs["source"]
    parent = source["parent_record"]
    assert parent["source_identity"]["row_ordinal"] == 0
    parent["source_identity"]["row_ordinal"] = 1
    parent["source_identity"]["row_group_ordinal"] = 1
    parent["source_identity_sha256"] = proposed.digest(parent["source_identity"])
    version = source["source_version"]
    version["source_id"] = "parent-literal-field:sha256:" + parent["source_identity_sha256"]
    version["provision_id"] = "physical-parent-row:1:field:text"
    source["source_version"] = version = reseal(version)
    source["document_id"] = version["source_id"]
    source["selector"]["source_version_cid"] = version["record_cid"]
    source["selector"] = occurrence = reseal(source["selector"])
    source["context"]["source_occurrence_cid"] = occurrence["record_cid"]
    source["context"]["context_references"][0]["record_cid"] = version["record_cid"]
    source["context"] = context = reseal(source["context"])
    parent["source_version_cid"] = version["record_cid"]
    source["parent_record"] = parent = reseal(parent)
    source["companion_record"].update(parent_record_cid=parent["record_cid"],
        source_version_cid=version["record_cid"], source_occurrence_cid=occurrence["record_cid"],
        context_cid=context["record_cid"])
    source["companion_record"] = reseal(source["companion_record"])
    reseal_binding(source)
    inputs["scope"] = proposed.bind_parent_scope(source=source, jurisdiction="US-federal",
        instrument="authored-parent-fixture", applicability="unresolved", definition_scope="unresolved")
    inputs["semantic_declarations"] = None
    # Structural consistency is deliberately weaker than original physical custody.
    graph = proposed.build_graph(**inputs)
    raw = json.dumps(graph, ensure_ascii=False, indent=2).encode("utf-8")
    arguments.update(expected_proposal_sha256=sha(raw), trusted_proposal_inputs=inputs,
        expected_inputs_sha256=sha(canonical_dag_json_bytes(inputs)))
    with pytest.raises(ValueError):
        adapter.adapt_parent_proposed_graph_bytes(raw, **arguments)


@pytest.mark.parametrize("limits", [{"max_records": 1}, {"max_collection_bytes": 1}, {"max_records": True}])
def test_parent_graph_binding_respects_existing_complete_population_bounds(literal_case, limits):
    arguments = binding_arguments(literal_case)
    bundle = arguments.pop("parent_bundle")
    with pytest.raises(ValueError):
        proposed.bind_parent_source_occurrence(bundle, **arguments, limits=limits)


def test_parent_scope_cannot_turn_unknown_edition_into_an_integer(literal_case):
    _, _, arguments = proposal_case(literal_case)
    inputs = deepcopy(arguments["trusted_proposal_inputs"])
    scope = inputs["scope"]
    scope["edition"] = 2024
    scope["scope_id"] = "legal-scope:sha256:" + proposed.digest(
        {key: value for key, value in scope.items() if key != "scope_id"})
    with pytest.raises(ValueError):
        proposed.build_graph(**inputs)


def test_relational_ast_uses_existing_owner_and_retains_null_semantic_source_binding(literal_case):
    raw, graph, arguments = proposal_case(literal_case, relational=True)
    expected = arguments["trusted_proposal_inputs"]["ast"]
    candidate = adapter.adapt_parent_proposed_graph_bytes(raw, **arguments)
    assert expected["source_binding"] is None
    assert proposed.graph_to_ast(graph) == expected
    assert candidate["ast_record"]["schema"] == adapter.AST_JSON_SCHEMA
    assert adapter.restore_proposed_graph_ast(candidate, **arguments) == expected
    assert candidate["source_occurrence"] == arguments["trusted_proposal_inputs"]["source"]["selector"]
    assert candidate["definition_semantics_encoded"] is False


def test_normative_scope_roundtrip_uses_literal_source_and_unavailable_context(tmp_path):
    text = "雪 é must retain é."
    data = helper("test_corpus_parent_occurrence_adapter").case(
        tmp_path, source_text="é", parent_texts=[text, text])
    bundle = parent_owner.build_parent_occurrence_corpus(**data["arguments"])
    case = {"data": data, "bundle": bundle,
        "records": {record["record_cid"]: record for record in bundle["records"]}}
    source = bind(case)
    request = {"source_text": text, "context": {"role": "required_unavailable",
        "text": "", "bindings": {}, "sha256": sha(b"")}}
    occurrences = []
    for identity, facet, symbol, literal, after in (
            ("m", "modality", "O", "must", 0), ("a", "actor", "actor", "é", 0),
            ("v", "action", "retain", "retain", 0), ("o", "object", "object", "é", 3)):
        start = text.index(literal, after)
        occurrences.append({"occurrence_id": identity, "facet": facet, "canonical_symbol": symbol,
            "anchor": {"origin": "source", "start": start, "end": start + len(literal),
                "text": literal, "offset_unit": "unicode_character_half_open"}})
    ast = {"schema": proposed.statement_scope.SCHEMA, "family": "deontic",
        "profile": proposed.statement_scope.PROFILE, "input": request,
        "input_sha256": proposed.digest(request), "occurrences": occurrences,
        "rules": [{"rule_id": "r1", "body": {"modality": "m", "actor": "a", "action": "v", "object": "o"},
            "qualifiers": {"conditions": None, "exceptions": None, "temporal": None}}],
        "statement_structure": {"op": "rule", "rule_id": "r1"}, "binders": [],
        "coverage": {"declared_status": "unassessed", "segments": []}, "unresolved": []}
    ast["content_sha256"] = proposed.digest(ast)
    inputs = {"ast": ast, "profile": "normative_scope_v1", "source": source,
        "scope": proposed.bind_parent_scope(source=source, jurisdiction="US-federal",
            instrument="authored-parent-fixture", applicability="unresolved", definition_scope="unresolved"),
        "semantic_declarations": None, "dependency_refs": [], "evidence_refs": [], "scope_request": request}
    graph = proposed.build_graph(**inputs)
    raw = json.dumps(graph, ensure_ascii=False, indent=2).encode("utf-8")
    arguments = {"expected_proposal_sha256": sha(raw), "trusted_proposal_inputs": inputs,
        "expected_inputs_sha256": sha(canonical_dag_json_bytes(inputs)), **binding_arguments(case)}
    candidate = adapter.adapt_parent_proposed_graph_bytes(raw, **arguments)
    assert proposed.graph_to_ast(graph) == ast
    assert adapter.restore_proposed_graph_ast(candidate, **arguments) == ast
    assert candidate["parent_source_binding"]["context"]["availability"] == "required_unavailable"
    wrong = deepcopy(inputs)
    wrong["scope_request"]["source_text"] += " changed"
    with pytest.raises(ValueError):
        proposed.build_graph(**wrong)
