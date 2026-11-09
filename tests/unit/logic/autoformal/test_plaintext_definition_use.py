"""Literal-parent alias candidates preserve custody without governing authority.

The source is authored fiction. Existing parent/context/review fixtures and
actual public owners build every input; no signing, model or Lean execution is
needed. A source-bound declaration is not a reviewed interpretation of law.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_definition_review_v2 as review
from ipfs_datasets_py.logic.autoformal import corpus_definition_use_v2 as owner
from ipfs_datasets_py.logic.autoformal import corpus_parent_occurrence_adapter as parents
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as markup
from ipfs_datasets_py.logic.autoformal import scoped_definition_resolution as resolver
from ipfs_datasets_py.logic.integration.reasoning import legal_ir_symbols as symbols
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes, cid_for_dag_json


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def cid(label):
    return cid_for_dag_json({"parent-use-authored-fixture": label})


def helper(name):
    path = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location("parent_use_fixture_" + name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def fixtures():
    existing = helper("test_plaintext_definition_review")
    original = existing.fixtures.__wrapped__()
    definition = original.definition
    # A private fixture module owns this authored text. Product sources and the
    # retained fixture files are unchanged. The tail supplies two real uses.
    definition.TEXT = definition.TEXT.replace(
        "registered café filer.", "registered café filer or café filer.")
    original_case = definition.case

    def declared_case(parent, *, family="fol", parent_index=0):
        request, inputs = original_case(parent, family=family, parent_index=parent_index)
        if parent_index == 1:
            declaration = request["declaration"]
            declaration["declaration_id"] = "authored-consumer-filer"
            # Both aliases are explicit unreviewed declarations. The consumer
            # head is the literal substring before means; its two body uses
            # occur after means inside the separately declared tail range.
            declaration["head"] = definition.span(definition.TEXT, "filer")
            tail = definition.TEXT.index("registered café filer")
            first = definition.TEXT.index("café filer", tail)
            second = definition.TEXT.index("café filer", first + 1)
            declaration["body"] = {"op": "any", "operands": [
                {"op": "atom", "span": definition.interval(
                    definition.TEXT, start, start + len("café filer"))}
                for start in (first, second)]}
        return request, inputs

    supplied = SimpleNamespace(**{**vars(definition), "case": declared_case})
    return SimpleNamespace(existing=existing, definition=definition,
        supplied=SimpleNamespace(definition=supplied, context=original.context))


def endpoint(fixtures, parent, *, family, index):
    case = fixtures.existing.make_case(fixtures.supplied, parent,
        family=family, parent_index=index)
    evidence = case["arguments"]
    preparation = review.prepare_parent_definition_review_evidence_v1(**evidence)
    evidence = deepcopy(evidence)
    evidence["expected_preparation_cid"] = preparation["record_cid"]
    return {"candidate": case["record"], "report": case["report"],
            "evidence": evidence, "preparation": preparation}


def lookup_inputs(data, *, status="resolved", partition_change=None, table_change=None):
    donor, consumer = (data[key]["candidate"] for key in ("donor", "consumer"))
    donor_id, consumer_id = (row["source_version"]["source_id"] for row in (donor, consumer))
    partitions = []
    for identity, document, item in (("local", consumer_id, data["consumer"]),
                                     ("donor", donor_id, data["donor"])):
        candidate, preparation = item["candidate"], item["preparation"]
        builder = symbols.LegalIRSymbolTableBuilder(symbol_table_id="parent-use:" + identity)
        scope = builder.add_document_scope(document)
        if identity == "donor" and status != "unresolved":
            declaration = dict(name=donor["term_record"]["source_literal"],
                symbol_kind=symbols.LegalIRSymbolKind.DEFINED_TERM,
                symbol_id=donor["term_record"]["symbol"], scope_id=scope.scope_id,
                document_id=document, source_node_ids=[donor["definition_record"]["record_cid"]],
                span_ids=donor["term_record"]["source_occurrence_cids"],
                metadata={"interpretation_status": "unreviewed_caller_declaration"})
            if table_change:
                declaration.update(table_change)
            builder.add_definition(**declaration)
            if status == "ambiguous":
                builder.add_definition(donor["term_record"]["source_literal"],
                    symbols.LegalIRSymbolKind.DEFINED_TERM,
                    symbol_id="parent-use:competing-donor", scope_id=scope.scope_id,
                    document_id=document)
        table = None if identity == "donor" and status == "unavailable" else wire(builder.to_symbol_table().to_dict())
        pins = item["evidence"]["expected_candidate_pin"]
        partition = dict(partition_id=identity, release_id=candidate["source_version"]["release_id"],
            edition=candidate["source_version"]["edition"], document_id=document,
            source_version_cid=candidate["source_version"]["record_cid"],
            scope_cid=candidate["scope_record"]["record_cid"],
            preparation_cid=preparation["record_cid"],
            parent_manifest_cid=pins["parent_manifest_cid"],
            root_source_occurrence_cid=pins["root_source_occurrence_cid"],
            companion_record_cid=pins["companion_record_cid"],
            source_binding_sha256=pins["source_binding_sha256"], table_raw=table)
        if partition_change and identity == partition_change[0]:
            partition.update(partition_change[1])
        partitions.append(partition)
    registry = resolver.build_parent_definition_lookup_registry_v1(partitions,
        [dict(partition_id=row["partition_id"], table_sha256=None if row["table_raw"] is None
              else sha(row["table_raw"])) for row in partitions])
    body = next(row for row in consumer["source_bindings"] if row["role"] == "definition_body/0000")
    reference = symbols.LegalIRSymbolReference(reference_id="parent-use:reference",
        name=donor["term_record"]["source_literal"], symbol_kind=symbols.LegalIRSymbolKind.DEFINED_TERM,
        scope_id="document:" + consumer_id, document_id=consumer_id,
        explicit_target_document_id=donor_id, explicit_scope_id="document:" + donor_id,
        source_node_ids=(consumer["definition_record"]["record_cid"],),
        span_ids=(body["source_occurrence_cid"],)).to_dict()
    query_raw = wire(dict(reference=reference, partition_ids=["local", "donor"],
        source_occurrence_cid=body["source_occurrence_cid"],
        interpretation_cid=consumer["report_record"]["record_cid"]))
    lookup = resolver.resolve_parent_definition_lookup_v1(registry, query_raw, sha(query_raw))
    registry_raw, lookup_raw = wire(registry), wire(lookup)
    return dict(registry_raw=registry_raw, expected_registry_sha256=sha(registry_raw),
        expected_registry_cid=registry["record_cid"], lookup_raw=lookup_raw,
        expected_lookup_sha256=sha(lookup_raw), expected_lookup_cid=lookup["record_cid"],
        query_raw=query_raw, expected_query_sha256=sha(query_raw))


def make_case(fixtures, path, *, family="fol"):
    parent = fixtures.definition.parent_case.__wrapped__(path)
    donor, consumer = [endpoint(fixtures, parent, family=family, index=i) for i in (0, 1)]
    body = [row for row in consumer["candidate"]["source_bindings"]
            if row["role"].startswith("definition_body/")]
    request = dict(schema=owner.PARENT_REQUEST_SCHEMA, profile=owner.PARENT_PROFILE,
        interpretation_status="unreviewed_caller_declaration", use_id="authored-parent-use",
        consumer_symbol=body[0]["symbol"], donor_symbol=donor["candidate"]["term_record"]["symbol"],
        body_roles=[row["role"] for row in body], donor_partition_id="donor", local_partition_id="local")
    data = dict(donor=donor, consumer=consumer, request=request)
    data["lookup_inputs"] = lookup_inputs(data)
    return data


@pytest.fixture(scope="module")
def base_case(fixtures, tmp_path_factory):
    return make_case(fixtures, tmp_path_factory.mktemp("parent-use-originals", numbered=False))


@pytest.fixture
def case(base_case):
    return deepcopy(base_case)


def arguments(data):
    raw = wire(data["request"])
    return raw, dict(expected_request_sha256=sha(raw),
        donor_evidence_inputs=data["donor"]["evidence"],
        consumer_evidence_inputs=data["consumer"]["evidence"], **data["lookup_inputs"])


def prepare(data):
    raw, kwargs = arguments(data)
    return owner.prepare_parent_definition_use_v1(raw, **kwargs)


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_parent_alias_preserves_actual_sources_contexts_and_closed_graph(fixtures, tmp_path, family, monkeypatch):
    def no_markup(*args, **kwargs):
        pytest.fail("literal-parent use must not extract or synthesize markup")
    monkeypatch.setattr(markup, "extract_document", no_markup)
    data = make_case(fixtures, tmp_path, family=family)
    before = deepcopy(data)
    result = prepare(data)
    assert data == before
    assert result["schema"] == owner.PARENT_SCHEMA != owner.SCHEMA
    assert result["profile"] == owner.PARENT_PROFILE and result["family"] == family
    assert result["view"] == "candidate"
    for key in (*owner.FALSE_FLAGS, "governing_scope_verified", "governing_edition_verified",
                "contributor_completeness_verified"):
        assert result[key] is False
    donor, consumer = (data[key]["candidate"] for key in ("donor", "consumer"))
    assert donor["source_version"]["record_cid"] != consumer["source_version"]["record_cid"]
    assert donor["source_version"]["edition"] == consumer["source_version"]["edition"] == parents.UNDECLARED_EDITION
    binding = result["binding_record"]
    assert binding["body_roles"] == ["definition_body/0000", "definition_body/0001"]
    origins = [row["source_occurrence_cid"] for row in consumer["source_bindings"]
               if row["role"].startswith("definition_body/")]
    assert len(set(origins)) == 2 and binding["body_occurrence_cids"] == origins
    assert binding["per_occurrence_lookup_verified"] is False
    assert binding["lookup_coverage"] == owner.LOOKUP_COVERAGE
    alias = result["alias_native"]["native_ast"]
    expected = deepcopy(donor["ast_record"]["native_ast"])
    expected["formula"]["left"]["name"] = data["request"]["consumer_symbol"]
    expected["formula"]["right"] = deepcopy(donor["ast_record"]["native_ast"]["formula"]["left"])
    assert alias == expected
    joint = result["joint_native"]["native_ast"]
    assert joint["left"] == donor["ast_record"]["native_ast"]
    assert joint["right"]["left"] == consumer["ast_record"]["native_ast"]
    assert joint["right"]["right"] == alias
    assert result["alias_record"]["assumed_not_proved"] is True
    nodes = {node["record_cid"]: node for node in result["graph"]["nodes"]}
    assert all(edge["src_cid"] in nodes and edge["dst_cid"] in nodes for edge in result["graph"]["edges"])
    uses = [edge for edge in result["graph"]["edges"] if edge["relation"] == "USES_DEFINITION"]
    assert len(uses) == 1
    assert nodes[uses[0]["src_cid"]]["content_cid"] == consumer["definition_record"]["record_cid"]
    assert nodes[uses[0]["dst_cid"]]["content_cid"] == donor["definition_record"]["record_cid"]
    assert not any(node["node_type"] == "norm_assertion" for node in nodes.values())
    contexts = [row for key in ("donor", "consumer") for row in data[key]["preparation"]["contexts"]]
    population = [dict(source_occurrence=occurrence, context=context)
        for key in ("donor", "consumer")
        for occurrence, context in zip(data[key]["preparation"]["source_occurrences"],
                                       data[key]["preparation"]["contexts"], strict=True)]
    assert result["context_population"] == population
    slots = [slot["slot_id"] for row in contexts for slot in row["dependency_slots"]]
    assert result["context_slot_ids"] == slots and len(set(slots)) == len(slots)
    assert all(slot["open"] for row in contexts for slot in row["dependency_slots"])
    for candidate in (donor, consumer):
        for occurrence in candidate["source_occurrences"]:
            text = fixtures.definition.TEXT
            assert occurrence["span_text"] == text[occurrence["start_char"]:occurrence["end_char"]]
            assert occurrence["start_utf8"] == len(text[:occurrence["start_char"]].encode())
            assert occurrence["end_utf8"] == len(text[:occurrence["end_char"]].encode())
    raw, kwargs = arguments(data)
    assert owner.validate_parent_definition_use_candidate_v1(result, raw, **kwargs) == result


def test_parent_preparation_replays_both_original_endpoint_owners(case, monkeypatch):
    original, calls = parents.validate_parent_occurrence_corpus, []
    def observed(bundle, **kwargs):
        calls.append(bundle["manifest"]["record_cid"])
        return original(bundle, **kwargs)
    monkeypatch.setattr(parents, "validate_parent_occurrence_corpus", observed)
    prepare(case)
    expected = {case[key]["evidence"]["parent_inputs"]["expected_manifest_cid"] for key in ("donor", "consumer")}
    assert set(calls) == expected and len(calls) >= 2


@pytest.mark.parametrize("field", ["expected_preparation_cid", "source_binding_sha256", "source_version_cid"])
def test_independent_parent_preparation_and_original_pins_are_required(case, field):
    evidence = case["donor"]["evidence"]
    if field == "expected_preparation_cid":
        evidence[field] = cid("wrong-preparation")
    else:
        evidence["expected_candidate_pin"][field] = "0" * 64 if field.endswith("sha256") else cid("wrong-source")
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("damage", ["omit", "reverse"])
def test_explicit_alias_requires_every_ordered_body_role(case, damage):
    roles = case["request"]["body_roles"]
    roles.pop() if damage == "omit" else roles.reverse()
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("field", ["preparation_cid", "companion_record_cid", "scope_cid"])
def test_self_consistent_parent_registry_cannot_override_endpoint_custody(case, field):
    case["lookup_inputs"] = lookup_inputs(case, partition_change=("donor", {field: cid("foreign-" + field)}))
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("status", ["unavailable", "ambiguous", "unresolved"])
def test_parent_lookup_preserves_nonpositive_outcomes_without_candidate_promotion(case, status):
    case["lookup_inputs"] = lookup_inputs(case, status=status)
    assert json.loads(case["lookup_inputs"]["lookup_raw"])["selected_symbol_id"] is None
    with pytest.raises(ValueError):
        prepare(case)


def test_donor_table_must_bind_the_actual_definition_and_head_occurrences(case):
    case["lookup_inputs"] = lookup_inputs(case, table_change={"span_ids": [cid("foreign-head")]})
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("damage", ["raw_candidate", "context_bytes", "context_population"])
def test_saved_candidate_and_context_inputs_remain_bound_to_original_evidence(case, damage):
    evidence = case["consumer"]["evidence"]
    if damage == "raw_candidate":
        evidence["candidate_inputs"]["candidate_raw"] += b" "
    elif damage == "context_bytes":
        evidence["context_inputs"][0]["packet_raw"] += b" "
    else:
        evidence["context_inputs"].pop()
        evidence["expected_context_population"].pop()
    with pytest.raises(ValueError):
        prepare(case)


def test_changed_physical_parent_cannot_be_hidden_by_saved_candidate_and_lookup(fixtures, tmp_path):
    data = make_case(fixtures, tmp_path)
    descriptor = data["donor"]["evidence"]["parent_inputs"]["replay_inputs"]["parent_text_views_inputs"]["parent_descriptor"]
    path = Path(descriptor["local_path"])
    path.write_bytes(path.read_bytes() + b"\nchanged authored source")
    with pytest.raises(ValueError):
        prepare(data)


@pytest.mark.parametrize("edition", [2024, "2024"])
def test_unknown_parent_edition_is_not_relabelled_as_governing_edition(case, edition):
    with pytest.raises(ValueError):
        case["lookup_inputs"] = lookup_inputs(case, partition_change=("donor", {"edition": edition}))
        prepare(case)


def test_resealed_candidate_cannot_claim_governing_or_accepted_authority(case):
    result = prepare(case)
    result["governing_scope_verified"] = True
    result = contracts.seal_record({key: value for key, value in result.items()
                                    if key not in {"record_cid", "cid_scope"}})
    raw, kwargs = arguments(case)
    with pytest.raises(ValueError):
        owner.validate_parent_definition_use_candidate_v1(result, raw, **kwargs)


def test_complete_parent_byte_budget_refuses_before_operation_owner_dispatch(case, monkeypatch):
    def no_dispatch():
        pytest.fail("combined byte bound must precede operation-owner dispatch")
    monkeypatch.setattr(owner, "MAX_TOTAL_INPUT_BYTES", 1)
    monkeypatch.setattr(owner, "_owners", no_dispatch)
    with pytest.raises(ValueError, match="byte budget exceeded"):
        prepare(case)


def test_during_generation_transport_mutation_cannot_escape_final_preflight(case, monkeypatch):
    original = owner._native
    def mutate_after_native(*args, **kwargs):
        result = original(*args, **kwargs)
        # This changes a bounded caller-owned input, not a source file. Full
        # physical replay occurred during endpoint preparation; the final
        # comparison promises transport consistency, not an atomic disk view.
        case["consumer"]["evidence"]["context_inputs"][0]["dependency_requests"] = []
        return result
    monkeypatch.setattr(owner, "_native", mutate_after_native)
    with pytest.raises(ValueError, match="parent original transport changed"):
        prepare(case)


def test_official_profile_cannot_accept_a_parent_candidate_or_parent_request(case):
    candidate = prepare(case)
    raw, kwargs = arguments(case)
    with pytest.raises(ValueError):
        owner.validate_definition_use_candidate_v2(candidate, raw, **kwargs)
    with pytest.raises(ValueError):
        owner.prepare_definition_use_v2(raw, **kwargs)
