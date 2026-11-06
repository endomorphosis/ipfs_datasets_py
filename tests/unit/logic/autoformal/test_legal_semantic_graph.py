"""Bounded graph transport on authored HTML and explicit unreviewed ASTs."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

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


# Retained authored candidates are portable test inputs, not reviewed law.
# These exact raw bytes retain the original A/B requests and remain unselected.
_SECTION7346_RAW_REQUESTS = {
    'de_re_list': r'''{"argument_roles":[{"roles":["actor"],"symbol":"Secretary"},{"roles":["list"],"symbol":"RetiredList"},{"roles":["actor","maintained_list"],"symbol":"Maintain"},{"roles":["person"],"symbol":"Retired"},{"roles":["person"],"symbol":"WarrantOfficer"},{"roles":["person"],"symbol":"OfArmy"},{"roles":["name","bearer"],"symbol":"NameOf"},{"roles":["container","entry"],"symbol":"Contains"}],"expression":{"content_digest":"d57ce780433ba2fda8ae5e6ff32c091ee1bfa581b9fccf7f4c5f14db5d1a9dcb","expression_id":"authored:7346c:de_re_list:expression","family":{"interface":"LogicIdentityNamespaces@1","namespace":"family","schema_version":"logic-identity-namespaces/v1","value":"tdfol","version":"1.0.0"},"interface":"TypedExpression@1","metadata":{},"profile":{"interface":"LogicIdentityNamespaces@1","namespace":"profile","schema_version":"logic-identity-namespaces/v1","value":"tdfol_default","version":"1.0.0"},"root":{"arguments":[{"arguments":[{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_re_list:n28","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"secretary"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"authored:7346c:de_re_list:n29","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"Secretary"},{"arguments":[{"arguments":[{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_re_list:n24","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"list"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"authored:7346c:de_re_list:n25","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"RetiredList"},{"arguments":[],"binders":[],"extension":{"children":[{"arguments":[{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_re_list:n19","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"secretary"},{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_re_list:n20","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"list"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"authored:7346c:de_re_list:n21","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"Maintain"},{"arguments":[{"arguments":[{"arguments":[{"arguments":[{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_re_list:n1","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"person"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"authored:7346c:de_re_list:n2","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"Retired"},{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_re_list:n3","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"person"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"authored:7346c:de_re_list:n4","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"WarrantOfficer"}],"binders":[],"kind":"and","metadata":{},"node_id":"authored:7346c:de_re_list:n5","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""},{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_re_list:n6","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"person"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"authored:7346c:de_re_list:n7","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"OfArmy"}],"binders":[],"kind":"and","metadata":{},"node_id":"authored:7346c:de_re_list:n8","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""},{"arguments":[{"arguments":[{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_re_list:n9","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"name"},{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_re_list:n10","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"person"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"authored:7346c:de_re_list:n11","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"NameOf"},{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_re_list:n12","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"list"},{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_re_list:n13","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"name"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"authored:7346c:de_re_list:n14","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"Contains"}],"binders":[],"kind":"and","metadata":{},"node_id":"authored:7346c:de_re_list:n15","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[{"name":"name","schema_version":"syntax-binder/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}}],"kind":"exists","metadata":{},"node_id":"authored:7346c:de_re_list:n16","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[],"kind":"implies","metadata":{},"node_id":"authored:7346c:de_re_list:n17","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[{"name":"person","schema_version":"syntax-binder/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}}],"kind":"forall","metadata":{},"node_id":"authored:7346c:de_re_list:n18","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[],"kind":"and","metadata":{},"node_id":"authored:7346c:de_re_list:n22","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"family":{"interface":"LogicIdentityNamespaces@1","namespace":"family","schema_version":"logic-identity-namespaces/v1","value":"tdfol","version":"1.0.0"},"features":["legacy.classic_letter","legacy.obligation"],"interface":"LogicExtensionNode@1","metadata":{},"node_id":"authored:7346c:de_re_list:n23:ext","payload":{"kind":"obligation","letter":"O","resolution":"deontic","schema_version":"legacy.deontic/v1"},"payload_schema":"legacy.deontic/v1","profile":{"interface":"LogicIdentityNamespaces@1","namespace":"profile","schema_version":"logic-identity-namespaces/v1","value":"tdfol_default","version":"1.0.0"},"schema_version":"syntax-logic-extension-node/v1"},"kind":"extension","metadata":{},"node_id":"authored:7346c:de_re_list:n23","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[],"kind":"and","metadata":{},"node_id":"authored:7346c:de_re_list:n26","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[{"name":"list","schema_version":"syntax-binder/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}}],"kind":"exists","metadata":{},"node_id":"authored:7346c:de_re_list:n27","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[],"kind":"implies","metadata":{},"node_id":"authored:7346c:de_re_list:n30","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[{"name":"secretary","schema_version":"syntax-binder/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}}],"kind":"forall","metadata":{},"node_id":"authored:7346c:de_re_list:n31","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""},"schema_version":"syntax-typed-expression/v1","signature":{"family":{"interface":"LogicIdentityNamespaces@1","namespace":"family","schema_version":"logic-identity-namespaces/v1","value":"tdfol","version":"1.0.0"},"features":[],"interface":"LogicSignature@1","metadata":{},"profile":{"interface":"LogicIdentityNamespaces@1","namespace":"profile","schema_version":"logic-identity-namespaces/v1","value":"tdfol_default","version":"1.0.0"},"schema_version":"syntax-logic-signature/v1","signature_id":"authored:7346c:de_re_list:signature","sorts":[{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"symbols":[{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Secretary","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"RetiredList","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Maintain","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Retired","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"WarrantOfficer","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"OfArmy","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"NameOf","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Contains","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"}]}},"interpretation_status":"authored_unreviewed_declaration","schema":"legal-relational-norm-request/v1","source_binding":null}
'''.encode('utf-8'),
    'de_dicto_list': r'''{"argument_roles":[{"roles":["actor"],"symbol":"Secretary"},{"roles":["list"],"symbol":"RetiredList"},{"roles":["actor","maintained_list"],"symbol":"Maintain"},{"roles":["person"],"symbol":"Retired"},{"roles":["person"],"symbol":"WarrantOfficer"},{"roles":["person"],"symbol":"OfArmy"},{"roles":["name","bearer"],"symbol":"NameOf"},{"roles":["container","entry"],"symbol":"Contains"}],"expression":{"content_digest":"9c0e8370c743b11b2345358a15004d5137f1b37dcd3b8f3455f1d37e338756fd","expression_id":"authored:7346c:de_dicto_list:expression","family":{"interface":"LogicIdentityNamespaces@1","namespace":"family","schema_version":"logic-identity-namespaces/v1","value":"tdfol","version":"1.0.0"},"interface":"TypedExpression@1","metadata":{},"profile":{"interface":"LogicIdentityNamespaces@1","namespace":"profile","schema_version":"logic-identity-namespaces/v1","value":"tdfol_default","version":"1.0.0"},"root":{"arguments":[{"arguments":[{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_dicto_list:n28","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"secretary"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"authored:7346c:de_dicto_list:n29","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"Secretary"},{"arguments":[],"binders":[],"extension":{"children":[{"arguments":[{"arguments":[{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_dicto_list:n19","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"list"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"authored:7346c:de_dicto_list:n20","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"RetiredList"},{"arguments":[{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_dicto_list:n21","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"secretary"},{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_dicto_list:n22","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"list"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"authored:7346c:de_dicto_list:n23","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"Maintain"},{"arguments":[{"arguments":[{"arguments":[{"arguments":[{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_dicto_list:n1","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"person"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"authored:7346c:de_dicto_list:n2","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"Retired"},{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_dicto_list:n3","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"person"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"authored:7346c:de_dicto_list:n4","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"WarrantOfficer"}],"binders":[],"kind":"and","metadata":{},"node_id":"authored:7346c:de_dicto_list:n5","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""},{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_dicto_list:n6","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"person"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"authored:7346c:de_dicto_list:n7","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"OfArmy"}],"binders":[],"kind":"and","metadata":{},"node_id":"authored:7346c:de_dicto_list:n8","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""},{"arguments":[{"arguments":[{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_dicto_list:n9","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"name"},{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_dicto_list:n10","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"person"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"authored:7346c:de_dicto_list:n11","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"NameOf"},{"arguments":[{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_dicto_list:n12","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"list"},{"arguments":[],"binders":[],"kind":"variable","metadata":{},"node_id":"authored:7346c:de_dicto_list:n13","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},"symbol":"name"}],"binders":[],"kind":"predicate","metadata":{},"node_id":"authored:7346c:de_dicto_list:n14","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":"Contains"}],"binders":[],"kind":"and","metadata":{},"node_id":"authored:7346c:de_dicto_list:n15","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[{"name":"name","schema_version":"syntax-binder/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}}],"kind":"exists","metadata":{},"node_id":"authored:7346c:de_dicto_list:n16","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[],"kind":"implies","metadata":{},"node_id":"authored:7346c:de_dicto_list:n17","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[{"name":"person","schema_version":"syntax-binder/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}}],"kind":"forall","metadata":{},"node_id":"authored:7346c:de_dicto_list:n18","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[],"kind":"and","metadata":{},"node_id":"authored:7346c:de_dicto_list:n24","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[],"kind":"and","metadata":{},"node_id":"authored:7346c:de_dicto_list:n25","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[{"name":"list","schema_version":"syntax-binder/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}}],"kind":"exists","metadata":{},"node_id":"authored:7346c:de_dicto_list:n26","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"family":{"interface":"LogicIdentityNamespaces@1","namespace":"family","schema_version":"logic-identity-namespaces/v1","value":"tdfol","version":"1.0.0"},"features":["legacy.classic_letter","legacy.obligation"],"interface":"LogicExtensionNode@1","metadata":{},"node_id":"authored:7346c:de_dicto_list:n27:ext","payload":{"kind":"obligation","letter":"O","resolution":"deontic","schema_version":"legacy.deontic/v1"},"payload_schema":"legacy.deontic/v1","profile":{"interface":"LogicIdentityNamespaces@1","namespace":"profile","schema_version":"logic-identity-namespaces/v1","value":"tdfol_default","version":"1.0.0"},"schema_version":"syntax-logic-extension-node/v1"},"kind":"extension","metadata":{},"node_id":"authored:7346c:de_dicto_list:n27","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[],"kind":"implies","metadata":{},"node_id":"authored:7346c:de_dicto_list:n30","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""}],"binders":[{"name":"secretary","schema_version":"syntax-binder/v1","sort":{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}}],"kind":"forall","metadata":{},"node_id":"authored:7346c:de_dicto_list:n31","schema_version":"syntax-logic-node/v1","sort":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"symbol":""},"schema_version":"syntax-typed-expression/v1","signature":{"family":{"interface":"LogicIdentityNamespaces@1","namespace":"family","schema_version":"logic-identity-namespaces/v1","value":"tdfol","version":"1.0.0"},"features":[],"interface":"LogicSignature@1","metadata":{},"profile":{"interface":"LogicIdentityNamespaces@1","namespace":"profile","schema_version":"logic-identity-namespaces/v1","value":"tdfol_default","version":"1.0.0"},"schema_version":"syntax-logic-signature/v1","signature_id":"authored:7346c:de_dicto_list:signature","sorts":[{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"symbols":[{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Secretary","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"RetiredList","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Maintain","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Retired","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"WarrantOfficer","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"OfArmy","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"NameOf","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Contains","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"}]}},"interpretation_status":"authored_unreviewed_declaration","schema":"legal-relational-norm-request/v1","source_binding":null}
'''.encode('utf-8'),
}


def _graph_depth_fixture(filename):
    spec = importlib.util.spec_from_file_location(
        "_semantic_graph_depth_" + Path(filename).stem, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json_tree_depth(value):
    children = value.values() if type(value) is dict else value if type(value) is list else ()
    return max((_json_tree_depth(child) + 1 for child in children), default=0)


@pytest.fixture(scope="module")
def parent_graph_case(tmp_path_factory):
    # Reuse the existing genuine physical-parent fixture; the candidate ASTs
    # below do not assert that this authored fixture is their statutory source.
    fixture = _graph_depth_fixture("test_legal_source_norm_scope_v1.py")
    value = fixture.parent_case(tmp_path_factory.mktemp("semantic-graph-depth-parent"))
    source = value["source"]
    scope = graph.bind_parent_scope(source=source, jurisdiction="unresolved", instrument="unresolved",
        applicability="unresolved", definition_scope="unresolved")
    return {"source": source, "scope": scope}


@pytest.mark.parametrize("alternative,expected_raw_sha256", [
    ("de_re_list", "c144d6c030c0adc48e7c91d3d51661a34738044e63c23db964523dc90304db8a"),
    ("de_dicto_list", "8584889c9d458e8d3c8b293153a5f0b74a4e48ef5927b4053a17a0af3cdceed3"),
])
def test_parent_relational_graph_preserves_unchanged_depth27_candidate(parent_graph_case, alternative,
                                                                      expected_raw_sha256):
    raw = _SECTION7346_RAW_REQUESTS[alternative]
    assert hashlib.sha256(raw).hexdigest() == expected_raw_sha256
    request = json.loads(raw)
    original = deepcopy(request)
    assert _json_tree_depth(request) == 27 and request["source_binding"] is None
    arguments = dict(profile="relational_norm_v1", **parent_graph_case)
    value = graph.build_graph(request, **arguments)
    decoded = graph.graph_to_ast(value)
    verified = graph.validate_graph(value, ast=request, **arguments)
    assert decoded == original == request
    assert decoded["expression"] == original["expression"]
    assert decoded["argument_roles"] == original["argument_roles"]
    assert decoded["source_binding"] is None
    assert not any(value["authority"].values()) and value["status"] == "proposed_unreviewed"
    assert value["entities"] == value["assertions"] == []
    assert value["source"]["schema"] == graph.PARENT_SOURCE_SCHEMA
    assert value["source"]["edition"] == parent_graph_case["source"]["edition"]
    assert verified["ordered_ast_roundtrip_verified"] and not any(verified["authority"].values())


def _relational_depth_request(depth):
    fixture = _graph_depth_fixture("test_legal_relational_norm_v1.py")
    # Both unary and modal nesting are needed to exercise either JSON-depth
    # parity while using only the existing valid variables-only typed fragment.
    for modal in (False, True):
        for nesting in range(18):
            builder = fixture.Builder()
            body = builder.atom("Retain", "actor", "object")
            for _ in range(nesting):
                body = fixture.ast.mk_not(builder.nid(), body)
            if modal:
                body = builder.modal("O", body)
            request = fixture.request_for(builder, body, [("Retain", ("actor", "object"))],
                [("actor", "forall"), ("object", "forall")])
            if _json_tree_depth(request) == depth:
                return request
    raise AssertionError("existing typed builders did not supply the requested depth")


def test_relational_graph_accepts_exact_depth32_and_refuses33(parent_graph_case):
    arguments = dict(profile="relational_norm_v1", **parent_graph_case)
    request = _relational_depth_request(32)
    assert _json_tree_depth(request) == 32
    value = graph.build_graph(request, **arguments)
    assert graph.graph_to_ast(value) == request
    assert graph.validate_graph(value, ast=request, **arguments)["ordered_ast_roundtrip_verified"]
    excessive = _relational_depth_request(33)
    assert _json_tree_depth(excessive) == 33
    with pytest.raises(ValueError, match="bound"):
        graph.build_graph(excessive, **arguments)


def _nested_graph_json(depth):
    value = 0
    for _ in range(depth):
        value = [value]
    return value


@pytest.mark.parametrize("profile", ["canonical_rules_v1", "normative_scope_v1"])
def test_legacy_profile_tree_limit_remains24(case, monkeypatch, profile):
    ast = _nested_graph_json(25)
    assert _json_tree_depth(ast) == 25
    # Isolate transport-depth admission from the legacy AST shape validators.
    # Genuine typed validation remains active in the relational tests above.
    observed = []
    monkeypatch.setattr(graph, "_validate_ast", lambda *args: observed.append(args[1]))
    with pytest.raises(ValueError, match="ordered AST graph bound"):
        graph.build_graph(ast, profile=profile, source=case["source"], scope=case["scope"])
    assert observed == [profile]
    with pytest.raises(ValueError, match="ordered AST graph bound"):
        graph._tree(ast, "0" * 64)


@pytest.mark.parametrize("profile,depth", [
    ("canonical_rules_v1", 25), ("normative_scope_v1", 25), ("relational_norm_v1", 33),
    ("mixed_relational_norm_v1", 49),
])
def test_resealed_known_nodes_cannot_exceed_selected_profile_decode_limit(case, profile, depth):
    value = graph.build_graph(case["ast"], **kwargs(case))
    ast = _nested_graph_json(depth)
    # Model an attacker who supplies all node, edge, seed and outer identities
    # correctly. Depth must still be checked before any AST semantic validation.
    value["profile"] = profile
    raw = json.dumps(ast, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    value["ast_sha256"] = hashlib.sha256(raw).hexdigest()
    value["tree_seed_sha256"] = graph.digest({"profile": profile, "ast_sha256": value["ast_sha256"],
        "source_binding_sha256": value["source"]["source_binding_sha256"],
        "scope_id": value["scope"]["scope_id"]})
    value["root_node_id"], value["nodes"], value["edges"] = graph._tree(
        ast, value["tree_seed_sha256"], maximum_depth=depth)
    value["entities"] = value["assertions"] = []
    reseal(value)
    with pytest.raises(ValueError, match="unknown/cyclic/deep AST reference"):
        graph.graph_to_ast(value)


@pytest.mark.parametrize("entry", ["build", "decode"])
def test_unknown_graph_profile_is_rejected_before_depth_selection(case, entry):
    if entry == "build":
        with pytest.raises(ValueError, match="unsupported graph AST profile"):
            graph.build_graph(case["ast"], profile="unknown", source=case["source"], scope=case["scope"])
    else:
        value = graph.build_graph(case["ast"], **kwargs(case))
        value["profile"] = "unknown"
        reseal(value)
        with pytest.raises(ValueError, match="unsupported graph AST profile"):
            graph.graph_to_ast(value)


@pytest.fixture(scope="module")
def mixed_graph_requests():
    # Reuse the retained packet at its existing owner; do not generate another
    # candidate or repeat the original projection/native qualification campaign.
    fixture = _graph_depth_fixture("test_legal_relational_norm_v1.py")
    raw = (Path(__file__).parents[4] / fixture._MIXED_RETAINED_PACKET).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == fixture._MIXED_RETAINED_PACKET_SHA
    packet = json.loads(raw)
    assert packet["selected_interpretation"] is packet["governing_definition_use"] is None
    requests = []
    for alternative in packet["alternatives"]:
        requests.append({"schema": fixture.bridge.MIXED_REQUEST_SCHEMA,
            "profile": fixture.bridge.MIXED_PROFILE,
            "interpretation_status": "authored_unreviewed_declaration",
            "expression": deepcopy(alternative["typed_expression"]),
            "argument_roles": deepcopy(alternative["argument_roles"]), "source_binding": None})
    return fixture, requests


@pytest.fixture(scope="module")
def mixed_graph_request(mixed_graph_requests):
    fixture, _ = mixed_graph_requests
    event, time = (fixture.signatures.LogicSort(name) for name in ("EventFrame", "TimeFrame"))
    builder = fixture.Builder()
    member = fixture.ast.mk_predicate(builder.nid(), "Member", [
        fixture.ast.mk_variable(builder.nid(), name, sort)
        for name, sort in (("actor", fixture.OBJECT), ("event", event), ("moment", time))])
    equality = fixture.ast.mk_equality(builder.nid(),
        fixture.ast.mk_variable(builder.nid(), "actor", fixture.OBJECT),
        fixture.ast.mk_variable(builder.nid(), "witness", fixture.OBJECT))
    body = fixture.ast.mk_and(builder.nid(), member, equality)
    body = fixture.ast.mk_exists(builder.nid(), [fixture.ast.Binder("witness", fixture.OBJECT)], body)
    for name, sort in (("moment", time), ("event", event), ("actor", fixture.OBJECT)):
        body = fixture.ast.mk_forall(builder.nid(), [fixture.ast.Binder(name, sort)], body)
    signature = fixture.signatures.LogicSignature("fixture:mixed-graph", family="tdfol", profile="tdfol_default",
        sorts=(fixture.OBJECT, event, time),
        symbols=(fixture.signatures.declare_predicate("Member", (fixture.OBJECT, event, time)),))
    expression = fixture.ast.TypedExpression("fixture:mixed-graph-expression", body, signature)
    return {"schema": fixture.bridge.MIXED_REQUEST_SCHEMA, "profile": fixture.bridge.MIXED_PROFILE,
        "interpretation_status": "authored_unreviewed_declaration", "expression": expression.to_dict(),
        "argument_roles": [{"symbol": "Member", "roles": ["actor", "event", "moment"]}], "source_binding": None}


def test_mixed_graph_roundtrips_complete_authored_request_without_source_promotion(
        case, mixed_graph_requests, mixed_graph_request):
    fixture, _ = mixed_graph_requests
    request = mixed_graph_request
    original = deepcopy(request)
    raw = fixture.wire(request)
    # This source is explicitly fictional; the association is not legal review.
    arguments = dict(profile="mixed_relational_norm_v1", source=case["source"], scope=case["scope"])
    value = graph.build_graph(request, **arguments)
    restored = graph.graph_to_ast(value)
    validated = graph.validate_graph(value, ast=original, **arguments)
    assert restored == request == original and fixture.wire(restored) == raw
    assert value["ast_sha256"] == hashlib.sha256(raw).hexdigest()
    assert restored["source_binding"] is None and value["source"] == case["source"]
    nodes = list(fixture._mixed_typed_nodes(restored["expression"]["root"]))
    assert sum(node["kind"] == "equality" for _, node in nodes) == 1
    binders = [binder for _, node in nodes for binder in node["binders"]]
    assert [binder["name"] for binder in binders] == ["actor", "event", "moment", "witness"]
    assert [binder["sort"]["name"] for binder in binders] == ["Object", "EventFrame", "TimeFrame", "Object"]
    assert value["entities"] == value["assertions"] == []
    assert value["status"] == "proposed_unreviewed" and not any(value["authority"].values())
    assert validated["ordered_ast_roundtrip_verified"] and not any(validated["authority"].values())
    assert value["original_task_acceptance"] == "preparatory_subset_only"


@pytest.mark.parametrize("ordinal,expected_depth,request_sha256", [
    (0, 45, "957b2011acde34b7fda85d8661061622160316605b03324a7b52c94cc17b6bc7"),
    (1, 42, "20017c7e69b094173ac62810c3c4d146401829f23d9e5d0626260f2227757c58"),
])
def test_complete_retained_mixed_requests_roundtrip_with_selected_output_budget(
        case, mixed_graph_requests, ordinal, expected_depth, request_sha256):
    fixture, requests = mixed_graph_requests
    request = requests[ordinal]
    original = deepcopy(request)
    assert hashlib.sha256(fixture.wire(request)).hexdigest() == request_sha256
    assert _json_tree_depth(request) == expected_depth
    # Only this opt-in output contract allows the complete larger tree. The
    # source association is an explicit fixture nomination, not legal meaning.
    arguments = dict(profile="mixed_relational_norm_v1", source=case["source"], scope=case["scope"])
    value = graph.build_graph(request, **arguments)
    restored = graph.graph_to_ast(value)
    checked = graph.validate_graph(value, ast=original, **arguments)
    assert fixture.wire(restored) == fixture.wire(original) and request == original
    assert restored["source_binding"] is None and restored["argument_roles"] == original["argument_roles"]
    assert len(restored["argument_roles"]) == 10
    nodes = list(fixture._mixed_typed_nodes(restored["expression"]["root"]))
    assert len(nodes) == 98 and sum(node["kind"] == "equality" for _, node in nodes) == 6
    binders = [binder for _, node in nodes for binder in node["binders"]]
    assert len(binders) == 12
    assert [binder["sort"]["name"] for binder in binders[:2]] == ["EventFrame", "TimeFrame"]
    assert graph.MAX_BYTES < len(fixture.wire(value)) <= graph.MIXED_RELATIONAL_MAX_BYTES
    assert checked["ordered_ast_roundtrip_verified"] and not any(checked["authority"].values())
    assert value["entities"] == value["assertions"] == [] and not any(value["authority"].values())
    with pytest.raises(ValueError, match="graph byte bound exceeded; no truncation"):
        graph.wire(value)


def test_mixed_graph_preserves_role_list_order_and_separates_independent_input_identity(
        case, mixed_graph_request):
    first = deepcopy(mixed_graph_request)
    second = deepcopy(first)
    second["argument_roles"].reverse()
    second["argument_roles"][0]["roles"].reverse()
    arguments = dict(profile="mixed_relational_norm_v1", source=case["source"], scope=case["scope"])
    a = graph.build_graph(first, **arguments)
    b = graph.build_graph(second, **arguments)
    assert graph.graph_to_ast(b) == second and graph.graph_to_ast(a) == first
    assert a["ast_sha256"] != b["ast_sha256"] and a["graph_id"] != b["graph_id"]
    with pytest.raises(ValueError, match="externally expected AST"):
        graph.validate_graph(b, ast=first, **arguments)


@pytest.mark.parametrize("damage", ["missing_source", "missing_scope", "source_revision",
                                  "scope_identity", "edition", "scope_request"])
def test_mixed_graph_requires_independent_source_and_scope_commitments(case, mixed_graph_request, damage):
    request = mixed_graph_request
    arguments = dict(profile="mixed_relational_norm_v1", source=case["source"], scope=case["scope"])
    value = graph.build_graph(request, **arguments)
    if damage == "missing_source": arguments["source"] = None
    elif damage == "missing_scope": arguments["scope"] = None
    elif damage == "source_revision":
        arguments["source"] = graph.bind_source_occurrence(case["document"], RAW,
            selector=case["source"]["selector"], document_revision="different-explicit-fixture-revision")
    elif damage in ("scope_identity", "edition"):
        arguments["scope"] = graph.bind_scope(jurisdiction="US", instrument="10 USC 1",
            edition=2025 if damage == "edition" else 2024,
            applicability="changed explicit fixture scope", definition_scope="section 1")
    else: arguments["scope_request"] = {"undeclared": "context"}
    with pytest.raises(ValueError):
        graph.validate_graph(value, ast=request, **arguments)
    assert request["source_binding"] is None


@pytest.mark.parametrize("damage", ["cross_sort_equality", "unknown_sort", "missing_role", "source_binding"])
def test_mixed_graph_reuses_strict_codec_refusals_without_repair(case, mixed_graph_requests, damage):
    fixture, requests = mixed_graph_requests
    request = deepcopy(requests[0])
    if damage == "cross_sort_equality":
        equality = next(node for _, node in fixture._mixed_typed_nodes(request["expression"]["root"])
                        if node["kind"] == "equality")
        equality["arguments"][1]["symbol"] = "event"
        equality["arguments"][1]["sort"] = deepcopy(request["expression"]["signature"]["sorts"][2])
        fixture._mixed_reseal_expression(request)
    elif damage == "unknown_sort":
        request["expression"]["signature"]["sorts"].append(fixture.signatures.LogicSort("CivilDate").to_dict())
        fixture._mixed_reseal_expression(request)
    elif damage == "missing_role": request["argument_roles"].pop()
    else: request["source_binding"] = {"invented": "source"}
    before = deepcopy(request)
    with pytest.raises(ValueError):
        graph.build_graph(request, profile="mixed_relational_norm_v1", source=case["source"], scope=case["scope"])
    assert request == before


def test_mixed_profile_is_explicit_and_does_not_widen_object_codec(case, mixed_graph_requests):
    _, requests = mixed_graph_requests
    with pytest.raises(ValueError):
        graph.build_graph(requests[0], profile="relational_norm_v1", source=case["source"], scope=case["scope"])
    assert graph._profile_depth_limit("relational_norm_v1") == 32
    assert graph._profile_depth_limit("canonical_rules_v1") == 24
    assert graph._profile_depth_limit("normative_scope_v1") == 24
    with pytest.raises(ValueError, match="bound"):
        graph.wire(_nested_graph_json(33))


def test_mixed_profile_depth_is_bounded_and_shared_node_byte_limits_are_unchanged(case, monkeypatch):
    # Isolate graph transport bounds; genuine mixed codec tests above retain its
    # strict validation. No valid typed input is manufactured by this fixture.
    monkeypatch.setattr(graph, "_validate_ast", lambda *args: None)
    arguments = dict(profile="mixed_relational_norm_v1", source=case["source"], scope=case["scope"])
    accepted = _nested_graph_json(48)
    assert graph.graph_to_ast(graph.build_graph(accepted, **arguments)) == accepted
    with pytest.raises(ValueError, match="bound"):
        graph.build_graph(_nested_graph_json(49), **arguments)
    assert graph.MAX_NODES == 4096 and graph.MAX_BYTES == 1024 * 1024


@pytest.mark.parametrize("profile,byte_limit", [
    ("canonical_rules_v1", 1024 * 1024), ("normative_scope_v1", 1024 * 1024),
    ("relational_norm_v1", 1024 * 1024), ("mixed_relational_norm_v1", 2 * 1024 * 1024),
])
def test_selected_output_byte_boundary_is_exact_and_does_not_change_default(profile, byte_limit):
    assert graph._profile_output_limit(profile) == byte_limit
    # A JSON string has exactly two quote bytes. No escaping or elision occurs.
    assert len(graph._graph_wire("x" * (byte_limit - 2), profile)) == byte_limit
    with pytest.raises(ValueError, match="graph byte bound exceeded; no truncation"):
        graph._graph_wire("x" * (byte_limit - 1), profile)
    assert len(graph.wire("x" * (graph.MAX_BYTES - 2))) == graph.MAX_BYTES
    with pytest.raises(ValueError, match="graph byte bound exceeded; no truncation"):
        graph.wire("x" * (graph.MAX_BYTES - 1))


@pytest.mark.parametrize("overflow", [False, True])
def test_complete_mixed_graph_final_envelope_byte_boundary(case, mixed_graph_requests, overflow):
    fixture, requests = mixed_graph_requests
    request = requests[0]
    refs = [reference() for _ in range(graph.MAX_REFS)]
    arguments = dict(profile="mixed_relational_norm_v1", source=case["source"], scope=case["scope"],
                     evidence_refs=refs)
    initial = graph.build_graph(request, **arguments)
    remaining = graph.MIXED_RELATIONAL_MAX_BYTES - len(fixture.wire(initial)) + int(overflow)
    # Populate existing bounded evidence metadata, not additional graph nodes.
    # Every individual string keeps its existing4096-character limit.
    for row in refs:
        for key in ("artifact_id", "role"):
            added = min(remaining, 4096 - len(row[key]))
            row[key] += "x" * added
            remaining -= added
    assert remaining == 0
    if overflow:
        with pytest.raises(ValueError, match="graph byte bound exceeded; no truncation"):
            graph.build_graph(request, **arguments)
    else:
        value = graph.build_graph(request, **arguments)
        assert len(fixture.wire(value)) == graph.MIXED_RELATIONAL_MAX_BYTES
        assert graph.graph_to_ast(value) == request
        assert graph.validate_graph(value, ast=request, **arguments)["ordered_ast_roundtrip_verified"]
