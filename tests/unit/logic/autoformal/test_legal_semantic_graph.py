"""Bounded graph transport on authored HTML and explicit unreviewed ASTs."""
from copy import deepcopy
import hashlib

import pytest

from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context
from ipfs_datasets_py.logic.autoformal import legal_semantic_graph as graph

URL = "https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-sec1.htm"
RAW = '''<h3 class="section-head">&sect;1. Fictional graph fixture</h3>
<p class="statutory-body">(a) Café office must retain records if ready unless waived before T. Café office may file notice. Office means a registered office.</p>
<p class="statutory-body">(b) Another paragraph.</p>'''.encode()


def reference(role="source"):
    return {"artifact_id": "fixture-artifact:" + role,
            "artifact_sha256": hashlib.sha256(role.encode()).hexdigest(), "role": role}


@pytest.fixture
def case():
    document = context.extract_document(RAW, url=URL, edition=2024, legal_id="usc:us:10:1")
    row = document["paragraphs"][0]
    selector = context.source_selector(document, RAW, char_start=row["char_start"], char_end=row["char_end"])
    source = graph.bind_source_occurrence(document, RAW, selector=selector, document_revision="fixture-release-1")
    scope = graph.bind_scope(jurisdiction="US", instrument="10 USC 1", edition=2024,
                             applicability="fictional scope", definition_scope="section 1")
    ast = {"rules": [
        {"modality": "P", "actor": "Café office", "action": "file", "object": "notice",
         "conditions": [], "exceptions": [], "temporal": []},
        {"modality": "O", "actor": "Café office", "action": "retain", "object": "records",
         "conditions": ["b", "a", "b"], "exceptions": ["waived"], "temporal": ["T"]}]}
    return {"document": document, "source": source, "scope": scope, "ast": ast}


def kwargs(case, **extra):
    return {"profile": "canonical_rules_v1", "source": case["source"], "scope": case["scope"], **extra}


def semantic(case):
    first, second = context.exact_view_occurrences(case["document"], RAW, text="Café office")
    definition = context.exact_view_occurrences(case["document"], RAW, text="Office means a registered office")[0]
    def entity(key, kind, selector=None, definition_kind=None):
        return {"entity_key": key, "kind": kind, "label": "office", "source_selector": selector,
                "definition_kind": definition_kind, "ast_path": "/rules/0", "ambiguity": ["office or officeholder"],
                "evidence_refs": [reference("source")]}
    return {"entities": [entity("mention-1", "mention", first), entity("mention-2", "mention", second),
                entity("concept-1", "concept"), entity("concept-2", "concept"),
                entity("definition-means", "definition", definition, "means"),
                entity("definition-includes", "definition", definition, "includes")],
            "assertions": [{"assertion_key": "denotation-1", "subject_key": "mention-1", "predicate": "denotes",
                "object_keys": ["concept-1", "concept-2", "concept-1"], "ambiguity": ["declared alternatives remain open"],
                "evidence_refs": [reference("source")], "dependency_refs": [reference("definition")]}]}


def reseal(value):
    value["graph_id"] = "legal-proposed-graph:sha256:" + graph.digest({key: child for key, child in value.items() if key != "graph_id"})
    return value


def test_ordered_ast_roundtrip_preserves_rule_order_repeated_qualifiers_and_unicode(case):
    value = graph.build_graph(case["ast"], **kwargs(case))
    assert graph.graph_to_ast(value) == case["ast"]
    assert graph.graph_to_ast(value)["rules"][1]["conditions"] == ["b", "a", "b"]
    assert graph.validate_graph(value, ast=case["ast"], **kwargs(case))["ordered_ast_roundtrip_verified"]
    assert all(not flag for flag in value["authority"].values())
    assert value["original_task_acceptance"] == "preparatory_subset_only"


def test_mention_concept_definition_and_ordered_relationship_identities_are_distinct(case):
    declarations = semantic(case)
    value = graph.build_graph(case["ast"], **kwargs(case, semantic_declarations=declarations,
        dependency_refs=[reference("definition")], evidence_refs=[reference("source")]))
    entities = value["entities"]
    assert len({entity["entity_id"] for entity in entities}) == 6
    assert entities[0]["identity"]["occurrence_id"] != entities[1]["identity"]["occurrence_id"]
    assert entities[4]["identity"]["definition_kind"] == "means"
    assert entities[5]["identity"]["definition_kind"] == "includes"
    assert value["assertions"][0]["object_ids"] == [entities[2]["entity_id"], entities[3]["entity_id"], entities[2]["entity_id"]]
    assert value["assertions"][0]["declaration"]["ambiguity"] == declarations["assertions"][0]["ambiguity"]
    assert graph.graph_to_ast(value) == case["ast"]
    assert all(entity["accepted"] is False for entity in entities)


def test_labels_do_not_define_identity_and_new_revision_scope_isolates_concepts(case):
    original = semantic(case)
    first = graph.build_graph(case["ast"], **kwargs(case, semantic_declarations=original))
    renamed = deepcopy(original)
    renamed["entities"][2]["label"] = "a different display label"
    second = graph.build_graph(case["ast"], **kwargs(case, semantic_declarations=renamed))
    assert first["entities"][2]["entity_id"] == second["entities"][2]["entity_id"]
    assert first["graph_id"] != second["graph_id"]
    alternate = deepcopy(case)
    alternate["source"] = graph.bind_source_occurrence(case["document"], RAW,
        selector=case["source"]["selector"], document_revision="fixture-release-2")
    third = graph.build_graph(case["ast"], **kwargs(alternate, semantic_declarations=original))
    assert first["entities"][2]["entity_id"] != third["entities"][2]["entity_id"]
    alternate["scope"] = graph.bind_scope(jurisdiction="US", instrument="10 USC 1", edition=2024,
        applicability="different applicability", definition_scope="section 1")
    fourth = graph.build_graph(case["ast"], **kwargs(alternate, semantic_declarations=original))
    assert third["entities"][2]["entity_id"] != fourth["entities"][2]["entity_id"]


@pytest.mark.parametrize("damage", ["edge_order", "dangling", "cycle", "node", "orphan", "authority", "extra", "entity_acceptance", "seed"])
def test_resealed_graph_rejects_structure_identity_and_authority_corruption(case, damage):
    value = graph.build_graph(case["ast"], **kwargs(case, semantic_declarations=semantic(case)))
    if damage == "edge_order": value["edges"][0]["ordinal"] = 999
    elif damage == "dangling": value["edges"][0]["child_id"] = "unknown"
    elif damage == "cycle": value["edges"][0]["child_id"] = value["root_node_id"]
    elif damage == "node": value["nodes"][0]["data"] = {"keys": []}
    elif damage == "orphan": value["nodes"].append(deepcopy(value["nodes"][0]))
    elif damage == "authority": value["authority"]["accepted"] = True
    elif damage == "extra": value["sealed"] = True
    elif damage == "entity_acceptance": value["entities"][0]["accepted"] = True
    else: value["scope"] = graph.bind_scope(jurisdiction="US", instrument="10 USC 1", edition=2024,
        applicability="changed scope without rebuilding nodes", definition_scope="section 1")
    reseal(value)
    with pytest.raises(ValueError): graph.graph_to_ast(value)


def test_external_expected_ast_and_semantic_inputs_prevent_retargeting(case):
    value = graph.build_graph(case["ast"], **kwargs(case, semantic_declarations=semantic(case)))
    changed = deepcopy(case["ast"])
    changed["rules"].reverse()
    with pytest.raises(ValueError, match="externally expected AST"):
        graph.validate_graph(value, ast=changed, **kwargs(case))
    with pytest.raises(ValueError, match="proposal inputs"):
        graph.validate_graph(value, ast=case["ast"], **kwargs(case))


@pytest.mark.parametrize("damage", ["bytes", "duplicate", "unknown_target", "definition_operator", "path", "reference"])
def test_semantic_declarations_require_exact_occurrences_refs_and_distinct_definition_kinds(case, damage):
    declarations = semantic(case)
    if damage == "bytes": declarations["entities"][0]["source_selector"]["utf8_byte_start"] += 1
    elif damage == "duplicate": declarations["entities"][1]["source_selector"] = declarations["entities"][0]["source_selector"]
    elif damage == "unknown_target": declarations["assertions"][0]["object_keys"] = ["absent"]
    elif damage == "definition_operator": declarations["entities"][4]["definition_kind"] = "iff"
    elif damage == "path": declarations["entities"][0]["ast_path"] = "/rules/00"
    else: declarations["entities"][0]["evidence_refs"][0]["artifact_sha256"] = "not-a-digest"
    with pytest.raises(ValueError): graph.build_graph(case["ast"], **kwargs(case, semantic_declarations=declarations))


def test_source_selector_cannot_cross_paragraphs_or_claim_a_different_edition(case):
    document = case["document"]
    selector = context.source_selector(document, RAW, char_start=0, char_end=len(document["document_text"]))
    with pytest.raises(ValueError, match="paragraph occurrence"):
        graph.bind_source_occurrence(document, RAW, selector=selector, document_revision="fixture-release-1")
    changed = deepcopy(case)
    changed["scope"] = graph.bind_scope(jurisdiction="US", instrument="10 USC 1", edition=2025,
        applicability="fictional scope", definition_scope="section 1")
    with pytest.raises(ValueError, match="edition"):
        graph.build_graph(case["ast"], **kwargs(changed))


def test_scope_ast_uses_existing_occurrence_and_ordered_attachment_contract(case):
    source = case["source"]["selector"]["text"]
    request = {"source_text": source, "context": {"role": "none_required", "text": "", "bindings": {},
                                                "sha256": hashlib.sha256(b"").hexdigest()}}
    def occurrence(identity, facet, symbol, literal):
        start = source.index(literal)
        return {"occurrence_id": identity, "facet": facet, "canonical_symbol": symbol,
            "anchor": {"origin": "source", "start": start, "end": start + len(literal), "text": literal,
                       "offset_unit": "unicode_character_half_open"}}
    declaration = {"schema": graph.statement_scope.SCHEMA, "family": "deontic", "profile": graph.statement_scope.PROFILE,
        "input": request, "input_sha256": graph.digest(request),
        "occurrences": [occurrence("m", "modality", "O", "must"), occurrence("a", "actor", "office", "Café office"),
                        occurrence("v", "action", "retain", "retain"), occurrence("o", "object", "records", "records")],
        "rules": [{"rule_id": "r1", "body": {"modality": "m", "actor": "a", "action": "v", "object": "o"},
                   "qualifiers": {"conditions": None, "exceptions": None, "temporal": None}}],
        "statement_structure": {"op": "rule", "rule_id": "r1"}, "binders": [],
        "coverage": {"declared_status": "unassessed", "segments": []}, "unresolved": []}
    declaration["content_sha256"] = graph.digest(declaration)
    value = graph.build_graph(declaration, profile="normative_scope_v1", source=case["source"], scope=case["scope"],
                              scope_request=request)
    assert graph.graph_to_ast(value) == declaration
    assert value["authority"]["source_semantics_verified"] is False
    wrong = deepcopy(request); wrong["source_text"] += " changed"
    with pytest.raises(ValueError):
        graph.build_graph(declaration, profile="normative_scope_v1", source=case["source"], scope=case["scope"], scope_request=wrong)


def test_bounds_refuse_without_truncation_and_caller_mutation_is_detached(case, monkeypatch):
    ast = deepcopy(case["ast"])
    value = graph.build_graph(ast, **kwargs(case))
    ast["rules"].clear()
    assert len(graph.graph_to_ast(value)["rules"]) == 2
    monkeypatch.setattr(graph, "MAX_NODES", 5)
    with pytest.raises(ValueError, match="bound"):
        graph.build_graph(case["ast"], **kwargs(case))
