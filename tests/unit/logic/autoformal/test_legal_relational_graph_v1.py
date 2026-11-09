"""Transport authored relational declarations without conferring legal meaning.

The HTML, interpretations, roles, and review identities are engineering fixtures.
Neither a nominated source paragraph nor exact AST custody establishes that the
declaration correctly interprets the source, or that any law has been proved.
"""

from copy import deepcopy
from functools import lru_cache
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_proposed_graph_adapter as adapter
from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
from ipfs_datasets_py.logic.autoformal import legal_graph_review as review
from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational
from ipfs_datasets_py.logic.autoformal import legal_semantic_graph as graph
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes, cid_for_dag_json


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@lru_cache(maxsize=3)
def helper(name):
    spec = importlib.util.spec_from_file_location(
        "authored_relational_graph_" + name, Path(__file__).with_name(name + ".py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def relational_helper():
    return helper("test_legal_relational_norm_v1")


def case(request=None, **source_changes):
    """Reuse the existing fictional two-paragraph source and exact source pins."""
    _, _, arguments = helper("test_corpus_proposed_graph_adapter").case(
        semantics=False, **source_changes)
    inputs = arguments["trusted_proposal_inputs"]
    inputs.update(ast=relational_helper().approval_request() if request is None else request,
                  profile="relational_norm_v1", scope_request=None)
    proposal = graph.build_graph(**inputs)
    raw = json.dumps(proposal, ensure_ascii=False, indent=2).encode("utf-8")
    arguments.update(expected_proposal_sha256=sha(raw),
                     expected_inputs_sha256=sha(canonical_dag_json_bytes(inputs)))
    return raw, proposal, arguments


def reseal(proposal):
    proposal["graph_id"] = "legal-proposed-graph:sha256:" + graph.digest(
        {key: value for key, value in proposal.items() if key != "graph_id"})
    return proposal


def assert_no_authority(proposal):
    assert proposal["status"] == "proposed_unreviewed"
    assert proposal["original_task_acceptance"] == "preparatory_subset_only"
    assert proposal["authority"] == graph.FALSE_AUTHORITY
    assert all(value is False for value in proposal["authority"].values())
    assert proposal.get("norm_interpretation_ready", False) is False


def test_complete_typed_request_roundtrips_without_relabeling_or_authority():
    request = relational_helper().approval_request()
    original = deepcopy(request)
    _, proposal, arguments = case(request)
    decoded = graph.graph_to_ast(proposal)
    assert decoded == original and request == original
    assert decoded["expression"] == original["expression"]
    assert decoded["argument_roles"] == original["argument_roles"]
    assert decoded["source_binding"] is None
    assert proposal["ast_sha256"] == graph.digest(original)
    assert proposal["ast_sha256"] != graph.digest(original["expression"])
    assert proposal["scope_request"] is None
    assert proposal["entities"] == proposal["assertions"] == []
    assert len(proposal["edges"]) == len(proposal["nodes"]) - 1
    assert len({row["path"] for row in proposal["nodes"]}) == len(proposal["nodes"])
    validation = graph.validate_graph(proposal, **arguments["trusted_proposal_inputs"])
    assert validation["ordered_ast_roundtrip_verified"] is True
    assert validation["authority"] == graph.FALSE_AUTHORITY
    assert_no_authority(proposal)
    request["argument_roles"][0]["roles"].reverse()
    assert graph.graph_to_ast(proposal) == original


def test_profile_calls_existing_public_relational_preparer_with_complete_request(monkeypatch):
    original = relational.prepare_relational_norm_v1
    observed = []

    def checked(raw, *, expected_request_sha256):
        assert expected_request_sha256 == sha(raw)
        observed.append(json.loads(raw))
        result = original(raw, expected_request_sha256=expected_request_sha256)
        assert result["source_bound"] is False
        assert result["native_build_executed"] is False
        return result

    monkeypatch.setattr(relational, "prepare_relational_norm_v1", checked)
    request = relational_helper().approval_request()
    _, proposal, _ = case(request)
    assert graph.graph_to_ast(proposal) == request
    assert observed and all(value == request for value in observed)


def variants(change):
    fixtures = relational_helper()
    if change == "role_labels":
        left = fixtures.approval_request()
        right = deepcopy(left)
        right["argument_roles"][0]["roles"].reverse()
        assert left["expression"] == right["expression"]
        return left, right
    if change == "argument_order":
        return fixtures.role_request(), fixtures.role_request(swapped=True)
    if change == "direction":
        return fixtures.role_request(), fixtures.role_request(reversed_direction=True)
    if change in {"obligation", "prohibition"}:
        return fixtures.approval_request(), fixtures.approval_request(
            operator="O" if change == "obligation" else "F")
    if change == "guard_location":
        return fixtures.approval_request(sufficient=True), fixtures.approval_request(inner=True)
    if change == "implication_direction":
        return fixtures.approval_request(), fixtures.approval_request(sufficient=True)
    if change == "quantifier_order":
        def quantified(order):
            builder = fixtures.Builder()
            return fixtures.request_for(builder, builder.atom("Match", "actor", "recipient"),
                [("Match", ("actor", "recipient"))], order)
        return (quantified([("actor", "forall"), ("recipient", "exists")]),
                quantified([("recipient", "exists"), ("actor", "forall")]))

    def conditions(reverse):
        builder = fixtures.Builder()
        guards = [builder.atom("Ready", "actor"), builder.atom("Licensed", "actor")]
        if reverse:
            guards.reverse()
        body = builder.binary("implies", builder.binary("and", *guards),
                              builder.modal("O", builder.atom("File", "actor")))
        return fixtures.request_for(builder, body,
            [("Ready", ("subject",)), ("Licensed", ("subject",)), ("File", ("actor",))],
            [("actor", "forall")])
    return conditions(False), conditions(True)


@pytest.mark.parametrize("change", ["role_labels", "argument_order", "direction", "obligation",
    "prohibition", "guard_location", "implication_direction", "quantifier_order", "condition_order"])
def test_ordered_logic_and_declared_roles_are_distinct_complete_graph_identities(change):
    left, right = variants(change)
    _, first, original_inputs = case(left)
    _, second, _ = case(right)
    assert graph.graph_to_ast(first) == left and graph.graph_to_ast(second) == right
    assert first["source"] == second["source"] and first["scope"] == second["scope"]
    assert first["ast_sha256"] != second["ast_sha256"]
    assert first["tree_seed_sha256"] != second["tree_seed_sha256"]
    assert first["graph_id"] != second["graph_id"]
    with pytest.raises(ValueError, match="externally expected AST"):
        graph.validate_graph(second, **original_inputs["trusted_proposal_inputs"])
    assert_no_authority(first)
    assert_no_authority(second)


@pytest.mark.parametrize("change", [{"paragraph": 1}, {"revision": "fictional-second-release"}, {"edition": 2025}])
def test_source_occurrence_revision_and_edition_have_separate_pins(change):
    _, first, original_inputs = case()
    _, second, _ = case(**change)
    assert graph.graph_to_ast(first) == graph.graph_to_ast(second)
    assert first["ast_sha256"] == second["ast_sha256"]
    assert first["source"]["source_binding_sha256"] != second["source"]["source_binding_sha256"]
    assert first["tree_seed_sha256"] != second["tree_seed_sha256"]
    assert first["graph_id"] != second["graph_id"]
    with pytest.raises(ValueError):
        graph.validate_graph(second, **original_inputs["trusted_proposal_inputs"])


def test_nominated_source_still_requires_one_exact_paragraph():
    _, _, arguments = case()
    document, raw = arguments["document"], arguments["raw_html"]
    selector = context.source_selector(document, raw,
        char_start=document["paragraphs"][0]["char_start"],
        char_end=document["paragraphs"][1]["char_end"])
    with pytest.raises(ValueError, match="one exact paragraph"):
        graph.bind_source_occurrence(document, raw, selector=selector,
                                     document_revision="fictional-release")


@pytest.mark.parametrize("damage", ["missing_roles", "unknown_role_symbol", "non_null_source",
                                    "unknown_request_field", "unsupported_extension"])
def test_relational_grammar_is_not_bypassed_by_generic_graph_transport(damage):
    fixtures = relational_helper()
    request = fixtures.approval_request()
    if damage == "missing_roles":
        request["argument_roles"].pop()
    elif damage == "unknown_role_symbol":
        request["argument_roles"][0]["symbol"] = "Undeclared"
    elif damage == "non_null_source":
        request["source_binding"] = {"invented": True}
    elif damage == "unknown_request_field":
        request["norm_interpretation_ready"] = True
    else:
        implication = request["expression"]["root"]["arguments"][0]["arguments"][0]["arguments"][0]
        implication["arguments"][0]["extension"]["payload_schema"] = "invented.modal/v1"
        request = fixtures.reseal_expression(request)
    with pytest.raises(ValueError):
        case(request)


@pytest.mark.parametrize("scope_request", [{}, {"source_text": "invented extra interpretation"}])
def test_relational_profile_refuses_separately_injected_scope_request(scope_request):
    _, _, arguments = case()
    inputs = deepcopy(arguments["trusted_proposal_inputs"])
    inputs["scope_request"] = scope_request
    with pytest.raises(ValueError):
        graph.build_graph(**inputs)


@pytest.mark.parametrize("profile", ["invented_relational_profile", "canonical_rules_v1"])
def test_relational_request_needs_its_explicit_profile(profile):
    _, _, arguments = case()
    inputs = deepcopy(arguments["trusted_proposal_inputs"])
    inputs["profile"] = profile
    with pytest.raises(ValueError):
        graph.build_graph(**inputs)


@pytest.mark.parametrize("damage", ["authority", "ordered_edge", "ast_digest", "profile"])
def test_repaired_outer_graph_hash_cannot_hide_invalid_inner_transport(damage):
    _, proposal, _ = case()
    if damage == "authority":
        proposal["authority"]["source_semantics_verified"] = True
    elif damage == "ordered_edge":
        proposal["edges"][0]["ordinal"] += 1
    elif damage == "ast_digest":
        proposal["ast_sha256"] = graph.digest(relational_helper().approval_request()["expression"])
    else:
        proposal["profile"] = "canonical_rules_v1"
    with pytest.raises(ValueError):
        graph.graph_to_ast(reseal(proposal))


def test_corpus_adapter_retains_full_request_and_only_custody_relationships():
    raw, proposal, arguments = case()
    record = adapter.adapt_proposed_graph_bytes(raw, **arguments)
    assert record["proposal_record"]["proposal_json"].encode("utf-8") == raw
    assert json.loads(record["proposal_record"]["proposal_json"]) == proposal
    request = arguments["trusted_proposal_inputs"]["ast"]
    ast_record = record["ast_record"]
    assert ast_record["schema"] == adapter.AST_JSON_SCHEMA
    assert "ast" not in ast_record
    assert ast_record["ast_json"].encode("utf-8") == canonical_dag_json_bytes(request)
    assert ast_record["ast_sha256"] == sha(canonical_dag_json_bytes(request))
    assert ast_record["ast_cid"] == cid_for_dag_json(request)
    assert adapter.restore_proposed_graph_ast(record, **arguments) == request
    assert record["ast_record"]["profile"] == "relational_norm_v1"
    assert record["ast_record"]["projection_status"] == "ordered_ast_custody_only"
    assert {edge["relation"] for edge in record["graph"]["edges"]} == {"HAS_SOURCE", "DERIVED_FROM"}
    assert {node["node_type"] for node in record["graph"]["nodes"]} == {
        "source_version", "occurrence", "interpretation", "expression", "issue"}
    assert record["source_occurrence"]["span_text"] == proposal["source"]["selector"]["text"]
    assert record["view"] == "candidate"
    for flag in ("admitted", "formalized", "source_semantics_verified", "source_authenticity_verified",
                 "external_references_verified", "definition_semantics_encoded"):
        assert record[flag] is False
    assert adapter.validate_proposed_graph_candidate(record, **arguments) == record


def test_resealed_alternate_declaration_cannot_replace_original_adapter_commitments():
    raw, _, arguments = case()
    alternate, _, _ = case(relational_helper().approval_request(operator="F"))
    assert sha(alternate) != sha(raw)
    with pytest.raises(ValueError):
        adapter.adapt_proposed_graph_bytes(alternate, **arguments)
    arguments["expected_proposal_sha256"] = sha(alternate)
    with pytest.raises(ValueError):
        adapter.adapt_proposed_graph_bytes(alternate, **arguments)


def test_corpus_graph_exchange_preserves_exact_candidate_envelopes(tmp_path):
    pytest.importorskip("pyarrow")
    from ipfs_datasets_py.logic.autoformal.corpus_graph_exchange import load_graph_bundle

    raw, _, arguments = case()
    record = adapter.adapt_proposed_graph_bytes(raw, **arguments)
    companion_path = tmp_path / "relational-candidate.json"
    companion_bytes = canonical_dag_json_bytes(record)
    companion_path.write_bytes(companion_bytes)
    output = tmp_path / "relational-graph-bundle"
    manifest = adapter.export_proposed_graph_candidate(record, output, **arguments)
    loaded = load_graph_bundle(output, expected_manifest_sha256=sha(canonical_dag_json_bytes(manifest)))
    assert loaded["snapshot"] == record["graph"]
    assert manifest["external_references_verified"] is False
    assert not (output / "candidate.json").exists()
    assert any(node["content_cid"] == record["ast_record"]["record_cid"]
               for node in loaded["snapshot"]["nodes"])
    retained = contracts.load_record_bytes(companion_path.read_bytes(), expected_sha256=sha(companion_bytes))
    assert retained["graph"] == loaded["snapshot"]
    assert adapter.restore_proposed_graph_ast(retained, **arguments) == arguments["trusted_proposal_inputs"]["ast"]
    assert retained["proposal_record"]["proposal_json"].encode("utf-8") == raw


def reseal_custody(record):
    return contracts.seal_record({key: value for key, value in record.items()
                                  if key not in {"record_cid", "cid_scope"}})


@pytest.mark.parametrize("damage", ["ast_json", "ast_sha256", "ast_cid", "schema",
                                    "noncanonical_json", "repaired_alternate_request"])
def test_resealed_v2_ast_companion_cannot_substitute_full_original_request(damage):
    raw, _, arguments = case()
    record = adapter.adapt_proposed_graph_bytes(raw, **arguments)
    ast_record = record["ast_record"]
    alternate = deepcopy(arguments["trusted_proposal_inputs"]["ast"])
    alternate["argument_roles"][0]["roles"].reverse()
    if damage == "ast_json":
        ast_record["ast_json"] = canonical_dag_json_bytes(alternate).decode("utf-8")
    elif damage == "ast_sha256":
        ast_record["ast_sha256"] = "0" * 64
    elif damage == "ast_cid":
        ast_record["ast_cid"] = cid_for_dag_json(alternate)
    elif damage == "schema":
        ast_record["schema"] = adapter.AST_SCHEMA
    elif damage == "noncanonical_json":
        ast_record["ast_json"] = json.dumps(arguments["trusted_proposal_inputs"]["ast"], indent=2)
        ast_record["ast_sha256"] = sha(ast_record["ast_json"].encode("utf-8"))
    else:
        ast_record["ast_json"] = canonical_dag_json_bytes(alternate).decode("utf-8")
        ast_record["ast_sha256"] = sha(ast_record["ast_json"].encode("utf-8"))
        ast_record["ast_cid"] = cid_for_dag_json(alternate)
    record["ast_record"] = reseal_custody(ast_record)
    forged = reseal_custody(record)
    with pytest.raises(ValueError):
        adapter.restore_proposed_graph_ast(forged, **arguments)


@pytest.mark.parametrize("damage", ["expected_pin", "repinned_alternate_inputs"])
def test_ast_restoration_requires_independent_original_proposal_inputs(damage):
    raw, _, arguments = case()
    record = adapter.adapt_proposed_graph_bytes(raw, **arguments)
    if damage == "expected_pin":
        arguments["expected_inputs_sha256"] = "0" * 64
    else:
        inputs = deepcopy(arguments["trusted_proposal_inputs"])
        inputs["ast"]["argument_roles"][0]["roles"].reverse()
        arguments.update(trusted_proposal_inputs=inputs,
                         expected_inputs_sha256=sha(canonical_dag_json_bytes(inputs)))
    with pytest.raises(ValueError):
        adapter.restore_proposed_graph_ast(record, **arguments)


def test_existing_flat_profile_keeps_exact_v1_ast_custody_shape_and_detached_restore():
    raw, _, arguments = helper("test_corpus_proposed_graph_adapter").case(semantics=False)
    record = adapter.adapt_proposed_graph_bytes(raw, **arguments)
    original = deepcopy(arguments["trusted_proposal_inputs"]["ast"])
    expected = contracts.seal_record({"schema": adapter.AST_SCHEMA, "ast": original,
        "ast_cid": cid_for_dag_json(original), "profile": "canonical_rules_v1",
        "source_occurrence_cid": record["source_occurrence"]["record_cid"],
        "projection_status": "ordered_ast_custody_only", "source_semantics_verified": False})
    assert canonical_dag_json_bytes(record["ast_record"]) == canonical_dag_json_bytes(expected)
    assert "ast_json" not in record["ast_record"] and "ast_sha256" not in record["ast_record"]
    restored = adapter.restore_proposed_graph_ast(record, **arguments)
    assert restored == original
    restored["rules"].clear()
    assert record["ast_record"]["ast"] == original
    assert arguments["trusted_proposal_inputs"]["ast"] == original


def test_generic_signed_review_binds_full_request_without_conferring_norm_interpretation():
    fixtures = helper("test_legal_graph_review")
    data = fixtures.case.__wrapped__()
    original_graph = data["graph"]
    request = relational_helper().approval_request()
    proposal = graph.build_graph(request, profile="relational_norm_v1",
        source=original_graph["source"], scope=original_graph["scope"], scope_request=None)
    artifacts = deepcopy(data["manifest"]["artifacts"])
    edges = deepcopy(data["manifest"]["edges"])
    for artifact in artifacts:
        if artifact["artifact_id"] == original_graph["graph_id"]:
            artifact.update(artifact_id=proposal["graph_id"], artifact_sha256=review.digest(proposal))
    for edge in edges:
        if edge["dependent_id"] == original_graph["graph_id"]:
            edge["dependent_id"] = proposal["graph_id"]
    manifest = dependencies.build_dependency_manifest(artifacts, edges,
        expected_artifact_ids=[item["artifact_id"] for item in artifacts])
    builder = deepcopy(data["builder"])
    builder.update(expected_graph_sha256=review.digest(proposal),
                   expected_manifest_sha256=manifest["manifest_sha256"],
                   required_dependency_ids=[proposal["graph_id"], "fixture:definition", "fixture:authority"])
    subject = review.build_review_subject(proposal, data["packet"], manifest, **builder)
    assert subject["ast_sha256"] == graph.digest(request)
    assert subject["ast_sha256"] != graph.digest(request["expression"])
    assert subject["graph_sha256"] == graph.digest(proposal)
    assert len(subject["context_slot_ids"]) == 6
    assert subject["context_slot_ids"] == data["subject"]["context_slot_ids"]
    for claim in data["reviews"]:
        claim["subject"] = deepcopy(subject)
        claim["interpretation"].update(reviewed_graph_sha256=graph.digest(proposal),
                                      reviewed_ast_sha256=graph.digest(request))
    data.update(graph=proposal, manifest=manifest, builder=builder, subject=subject)
    data["observed_artifacts"].pop(original_graph["graph_id"])
    data["observed_artifacts"][proposal["graph_id"]] = graph.digest(proposal)
    data["registry"]["mode"] = data["policy"]["mode"] = "external_pinned_trust"
    fixtures.refresh(data)
    report = fixtures.assess(data)
    assert report["authenticated_evidence_count"] == 2
    assert report["review_prerequisites_satisfied_under_selected_trust"] is True
    assert report["accepted_view_eligible"] is False
    assert report.get("norm_interpretation_ready", False) is False
    assert all(report[flag] is False for flag in review.FALSE_AUTHORITY)
    assert_no_authority(proposal)
