"""Explicit authored predicate aliases preserve originals without legal review."""

from __future__ import annotations

import builtins
import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from unittest.mock import patch

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_definition_adapter_v2 as adapter
from ipfs_datasets_py.logic.autoformal import corpus_definition_review_v2 as review
from ipfs_datasets_py.logic.autoformal import legal_official_source_custody as custody
from ipfs_datasets_py.logic.autoformal import (
    legal_source_definition_bridge_v2 as compiler,
)
from ipfs_datasets_py.logic.autoformal import legal_source_sampling as sampler
from ipfs_datasets_py.logic.autoformal import legal_statutory_context_v2 as contexts
from ipfs_datasets_py.logic.autoformal import scoped_definition_resolution as resolver
from ipfs_datasets_py.logic.integration.reasoning import legal_ir_symbols as symbols
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes, cid_for_dag_json


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False).encode()


def cid(label):
    return cid_for_dag_json({"authored-fixture": label})


def authored_definition(role, family="fol", *, same_document=False):
    section = "1" if role == "donor" or same_document else "2"
    paragraphs = {
        "donor": '(1) The term "café member" means registered.',
        "consumer": '(2) The term "eligible member" means café member or café member.',
    }
    selected = ["donor", "consumer"] if same_document else [role]
    raw = (
        '<html><head><meta charset="utf-8"></head><body>'
        f'<!-- field-start:head --><h3 class="section-head">§{section}. Authored fixture</h3>'
        "<!-- field-end:head --><!-- field-start:statute -->"
        '<p class="statutory-body">(a) In this title:</p>'
        + "".join(
            f'<p class="statutory-body-1em">{paragraphs[key]}</p>' for key in selected
        )
        + '<!-- field-end:statute --><p class="source-credit">Fictional source.</p>'
        "</body></html>"
    ).encode()
    legal_id = "usc:us:10:" + section
    url = f"https://www.govinfo.gov/content/pkg/USCODE-2024-title10/html/USCODE-2024-title10-chap1-sec{section}.htm"
    descriptor = {
        "schema": custody.DESCRIPTOR_SCHEMA,
        "legal_id": legal_id,
        "edition": 2024,
        "package_id": "USCODE-2024-title10",
        "granule_id": "USCODE-2024-title10-chap1-sec" + section,
        "url": url,
        "retrieved_at": "2026-10-15T01:00:00Z",
        "raw_sha256": sha(raw),
        "raw_bytes": len(raw),
        "http_provenance": {
            "requested_url": url,
            "final_url": url,
            "status_code": 200,
            "content_type": "text/html",
            "etag": None,
            "last_modified": None,
        },
    }
    trusted = {
        "descriptor": descriptor,
        "expected_descriptor_sha256": custody.acquisition_descriptor_sha256(descriptor),
        "expected_raw_sha256": sha(raw),
        "expected_raw_bytes": len(raw),
    }
    sampling = sampler.prepare_source_sampling(raw, **trusted)
    text = sampling["document_view_report"]["document"]["document_text"]
    by_cid = {row["record_cid"]: row for row in sampling["records"]}
    units = [by_cid[ref["record_cid"]] for ref in sampling["unit_refs"]]

    def unit_with(literal):
        return next(
            unit
            for unit in units
            if literal
            in by_cid[unit["source_occurrence_ref"]["record_cid"]]["span_text"]
        )

    def ref(unit):
        return next(
            ref
            for ref in sampling["unit_refs"]
            if ref["record_cid"] == unit["record_cid"]
        )

    head = "café member" if role == "donor" else "eligible member"
    unit = unit_with(paragraphs[role])
    occurrence = by_cid[unit["source_occurrence_ref"]["record_cid"]]

    def span(literal, *, last=False, anywhere=False):
        lower, upper = (
            (0, len(text))
            if anywhere
            else (occurrence["start_char"], occurrence["end_char"])
        )
        start = (
            text.rindex(literal, lower, upper)
            if last
            else text.index(literal, lower, upper)
        )
        return {"char_start": start, "char_end": start + len(literal), "text": literal}

    body = (
        {"op": "atom", "span": span("registered")}
        if role == "donor"
        else {
            "op": "any",
            "operands": [
                {"op": "atom", "span": span("café member")},
                {"op": "atom", "span": span("café member", last=True)},
            ],
        }
    )
    request = {
        "schema": compiler.REQUEST_SCHEMA,
        "profile": compiler.PROFILE,
        "family": family,
        "declaration": {
            "declaration_id": "authored-" + role,
            "interpretation_status": "unreviewed_caller_declaration",
            "source_version_ref": unit["source_version_ref"],
            "normalized_view_id": unit["normalized_view_id"],
            "contributor_unit_refs": [ref(unit)],
            "scope_unit_ref": ref(unit_with("In this title:")),
            "scope_span": span("In this title:", anywhere=True),
            "head": span(head),
            "definition_cue": span("means"),
            "body": body,
            "applicability": {
                "scope_kind": "title",
                "scope_id": "authored-title10",
                "jurisdiction_id": "authored-us",
                "instrument_id": "usc:us:10",
                "legal_as_of_civil_date": None,
                "source_edition": 2024,
                "source_release_id": "govinfo-markup-v2-edition:2024",
            },
        },
    }
    replay = {
        "sampling_report": sampling,
        "expected_sampling_report_sha256": sampler.source_sampling_report_sha256(
            sampling
        ),
        "raw_html": raw,
        **trusted,
    }
    report = compiler.prepare_definition_v2(request, **replay)
    request_raw, report_raw = wire(request), wire(report)
    candidate = adapter.adapt_definition_only_bytes_v2(
        report_raw,
        expected_report_sha256=sha(report_raw),
        request_raw=request_raw,
        expected_request_sha256=sha(request_raw),
        **replay,
    )
    candidate_raw = canonical_dag_json_bytes(candidate)
    sampling_raw, descriptor_raw = wire(sampling), wire(descriptor)
    original_inputs = {
        "candidate_raw": candidate_raw,
        "report_raw": report_raw,
        "request_raw": request_raw,
        "raw_html": raw,
        "sampling_report_raw": sampling_raw,
        "descriptor_raw": descriptor_raw,
    }
    pin = {
        "candidate_sha256": sha(candidate_raw),
        "candidate_cid": candidate["record_cid"],
        "graph_cid": candidate["graph"]["record_cid"],
        "request_sha256": sha(request_raw),
        "report_sha256": sha(report_raw),
        "raw_sha256": sha(raw),
        "raw_bytes": len(raw),
        "extracted_sha256": report["document_text_sha256"],
        "sampling_report_sha256": sha(sampling_raw),
        "sampling_report_full_canonical_sha256": replay[
            "expected_sampling_report_sha256"
        ],
        "descriptor_sha256": sha(descriptor_raw),
        "descriptor_full_canonical_sha256": trusted["expected_descriptor_sha256"],
    }
    packets, population = [], []
    for origin in candidate["source_occurrences"]:
        packet = contexts.build_context_packet_v2(
            sampling["document_view_report"],
            raw,
            char_start=origin["start_char"],
            char_end=origin["end_char"],
            expected_report_sha256=sampling["document_view_report_sha256"],
            **trusted,
        )
        packet_raw = wire(packet)
        packets.append(
            {
                "source_occurrence_cid": origin["record_cid"],
                "packet_raw": packet_raw,
                "dependency_requests": None,
            }
        )
        population.append(
            {
                "source_occurrence_cid": origin["record_cid"],
                "packet_sha256": sha(packet_raw),
            }
        )
    evidence = {
        "candidate_inputs": original_inputs,
        "expected_candidate_pin": pin,
        "context_inputs": packets,
        "expected_context_population": population,
    }
    preparation = review.prepare_definition_review_evidence_v2(**evidence)
    evidence["expected_preparation_cid"] = preparation["record_cid"]
    return {"candidate": candidate, "report": report, "evidence": evidence}


def lookup_inputs(
    data, *, status="resolved", metadata_change=None, definition_change=None
):
    donor, consumer = data["donor"]["candidate"], data["consumer"]["candidate"]
    donor_id, consumer_id = (
        donor["source_version"]["source_id"],
        consumer["source_version"]["source_id"],
    )
    partitions = []
    for identity, document, candidate in (
        ("local", consumer_id, consumer),
        ("donor", donor_id, donor),
    ):
        builder = symbols.LegalIRSymbolTableBuilder(
            symbol_table_id="fixture-" + identity
        )
        scope = builder.add_document_scope(document)
        if identity == "donor" and status != "unresolved":
            definition = {
                "name": donor["term_record"]["source_literal"],
                "symbol_kind": symbols.LegalIRSymbolKind.DEFINED_TERM,
                "symbol_id": donor["term_record"]["symbol"],
                "scope_id": scope.scope_id,
                "document_id": document,
                "source_node_ids": [donor["definition_record"]["record_cid"]],
                "span_ids": donor["term_record"]["source_occurrence_cids"],
                "metadata": {"interpretation_status": "unreviewed_caller_declaration"},
            }
            if definition_change:
                definition.update(definition_change)
            builder.add_definition(**definition)
            if status == "ambiguous":
                builder.add_definition(
                    donor["term_record"]["source_literal"],
                    symbols.LegalIRSymbolKind.DEFINED_TERM,
                    symbol_id="fixture:competing-definition",
                    scope_id=scope.scope_id,
                    document_id=document,
                )
        table_raw = (
            None
            if identity == "donor" and status == "unavailable"
            else wire(builder.to_symbol_table().to_dict())
        )
        partition = {
            "partition_id": identity,
            "release_id": candidate["source_version"]["release_id"],
            "edition": int(candidate["source_version"]["edition"]),
            "document_id": document,
            "source_version_cid": candidate["source_version"]["record_cid"],
            "scope_cid": candidate["scope_record"]["record_cid"],
            "applicability_cid": cid_for_dag_json(
                candidate["scope_record"]["declared_applicability"]
            ),
            "table_raw": table_raw,
        }
        if metadata_change and identity == metadata_change[0]:
            partition.update(metadata_change[1])
        partitions.append(partition)
    registry = resolver.build_definition_lookup_registry(
        partitions,
        [
            {
                "partition_id": row["partition_id"],
                "table_sha256": (
                    None if row["table_raw"] is None else sha(row["table_raw"])
                ),
            }
            for row in partitions
        ],
    )
    binding = next(
        row
        for row in consumer["source_bindings"]
        if row["role"] == "definition_body/0000"
    )
    reference = symbols.LegalIRSymbolReference(
        reference_id="fixture:use-reference",
        name="café member",
        symbol_kind=symbols.LegalIRSymbolKind.DEFINED_TERM,
        scope_id="document:" + consumer_id,
        document_id=consumer_id,
        explicit_target_document_id=donor_id,
        explicit_scope_id="document:" + donor_id,
        source_node_ids=(consumer["definition_record"]["record_cid"],),
        span_ids=(binding["source_occurrence_cid"],),
    ).to_dict()
    query = {
        "reference": reference,
        "partition_ids": ["local", "donor"],
        "source_occurrence_cid": binding["source_occurrence_cid"],
        "interpretation_cid": consumer["report_record"]["record_cid"],
    }
    query_raw = wire(query)
    lookup = resolver.resolve_definition_lookup(registry, query_raw, sha(query_raw))
    registry_raw, lookup_raw = wire(registry), wire(lookup)
    return {
        "registry_raw": registry_raw,
        "expected_registry_sha256": sha(registry_raw),
        "expected_registry_cid": registry["record_cid"],
        "lookup_raw": lookup_raw,
        "expected_lookup_sha256": sha(lookup_raw),
        "expected_lookup_cid": lookup["record_cid"],
        "query_raw": query_raw,
        "expected_query_sha256": sha(query_raw),
    }


def fixture(owner, family="fol", *, same_document=False, consumer_family=None):
    donor = authored_definition("donor", family, same_document=same_document)
    consumer = authored_definition(
        "consumer", consumer_family or family, same_document=same_document
    )
    body = [
        row
        for row in consumer["candidate"]["source_bindings"]
        if row["role"].startswith("definition_body/")
    ]
    request = {
        "schema": owner.REQUEST_SCHEMA,
        "profile": owner.PROFILE,
        "interpretation_status": "unreviewed_caller_declaration",
        "use_id": "fixture:explicit-use",
        "consumer_symbol": body[0]["symbol"],
        "donor_symbol": donor["candidate"]["term_record"]["symbol"],
        "body_roles": [row["role"] for row in body],
        "donor_partition_id": "donor",
        "local_partition_id": "local",
    }
    data = {"donor": donor, "consumer": consumer, "request": request}
    data["lookup_inputs"] = lookup_inputs(data)
    return data


def arguments(data):
    raw = wire(data["request"])
    return raw, {
        "expected_request_sha256": sha(raw),
        "donor_evidence_inputs": data["donor"]["evidence"],
        "consumer_evidence_inputs": data["consumer"]["evidence"],
        **data["lookup_inputs"],
    }


def prepare(owner, data):
    raw, kwargs = arguments(data)
    return owner.prepare_definition_use_v2(raw, **kwargs)


def evaluate(node, values, env=None):
    env = {} if env is None else env
    kind = node["node_type"]
    if kind == "Predicate":
        return values[node["name"]][env[node["arguments"][0]["name"]]]
    if kind == "QuantifiedFormula":
        assert node["quantifier"]["value"] == "∀"
        return all(
            evaluate(node["formula"], values, env | {node["variable"]["name"]: entity})
            for entity in (0, 1)
        )
    if kind == "UnaryFormula":
        assert node["operator"]["value"] == "¬"
        return not evaluate(node["formula"], values, env)
    left, right = evaluate(node["left"], values, env), evaluate(
        node["right"], values, env
    )
    return {"∧": left and right, "∨": left or right, "↔": left == right}[
        node["operator"]["value"]
    ]


@pytest.fixture(scope="module")
def owner():
    from ipfs_datasets_py.logic.autoformal import corpus_definition_use_v2

    return corpus_definition_use_v2


@pytest.fixture(scope="module")
def base(owner):
    return fixture(owner)


@pytest.fixture
def case(base):
    return deepcopy(base)


@pytest.mark.parametrize("family", ["fol", "tdfol"])
def test_explicit_whole_predicate_alias_preserves_originals_and_closed_graph(
    owner, family
):
    import itertools

    data = fixture(owner, family)
    originals = deepcopy([data[key]["candidate"] for key in ("donor", "consumer")])
    record = prepare(owner, data)
    assert [data[key]["candidate"] for key in ("donor", "consumer")] == originals
    donor_ast, consumer_ast = [
        row["definition_record"]["native_ast"] for row in originals
    ]
    alias = record["alias_native"]["native_ast"]
    expected_alias = deepcopy(donor_ast)
    expected_alias["formula"]["left"]["name"] = data["request"]["consumer_symbol"]
    expected_alias["formula"]["right"] = deepcopy(donor_ast["formula"]["left"])
    assert alias == expected_alias

    def conjuncts(node):
        if node["node_type"] == "BinaryFormula" and node["operator"]["value"] == "∧":
            return conjuncts(node["left"]) + conjuncts(node["right"])
        return [node]

    assert conjuncts(record["joint_native"]["native_ast"]) == [
        donor_ast,
        consumer_ast,
        alias,
    ]
    binding = record["binding_record"]
    assert binding["body_roles"] == ["definition_body/0000", "definition_body/0001"]
    body_origins = [
        row["source_occurrence_cid"]
        for row in originals[1]["source_bindings"]
        if row["role"].startswith("definition_body/")
    ]
    assert len(set(body_origins)) == 2
    assert binding["body_occurrence_cids"] == body_origins
    assert (
        binding["lookup_coverage"]
        == "representative_first_occurrence_whole_predicate_assumption"
    )
    assert binding["per_occurrence_lookup_verified"] is False
    nodes = {node["record_cid"]: node for node in record["graph"]["nodes"]}
    uses = [
        edge
        for edge in record["graph"]["edges"]
        if edge["relation"] == "USES_DEFINITION"
    ]
    assert len(uses) == 1
    assert (
        nodes[uses[0]["src_cid"]]["content_cid"]
        == originals[1]["definition_record"]["record_cid"]
    )
    assert (
        nodes[uses[0]["dst_cid"]]["content_cid"]
        == originals[0]["definition_record"]["record_cid"]
    )
    assert binding["record_cid"] in uses[0]["evidence_cids"]
    assert data["lookup_inputs"]["expected_lookup_cid"] in uses[0]["evidence_cids"]
    assert not any(node["node_type"] == "norm_assertion" for node in nodes.values())
    assert all(
        edge["src_cid"] in nodes and edge["dst_cid"] in nodes
        for edge in record["graph"]["edges"]
    )
    assert all(record[key] is False for key in owner.FALSE_FLAGS)
    count = sum(len(item["source_occurrences"]) for item in originals)
    assert len(record["context_population"]) == count
    assert (
        len(record["context_slot_ids"])
        == len(set(record["context_slot_ids"]))
        == count * 6
    )
    names = [
        originals[0]["term_record"]["symbol"],
        data["donor"]["report"]["symbol_occurrences"][1]["symbol"],
        originals[1]["term_record"]["symbol"],
        data["request"]["consumer_symbol"],
    ]
    assert len(set(names)) == 4
    for bits in itertools.product((False, True), repeat=8):
        values = {name: bits[2 * i : 2 * i + 2] for i, name in enumerate(names)}
        expected = all(
            len({values[name][entity] for name in names}) == 1 for entity in (0, 1)
        )
        assert evaluate(record["joint_native"]["native_ast"], values) == expected
    raw, kwargs = arguments(data)
    assert owner.validate_definition_use_candidate_v2(record, raw, **kwargs) == record


@pytest.mark.parametrize(
    "damage", ["omit_role", "reverse_roles", "head_as_body", "wrong_donor"]
)
def test_explicit_mapping_covers_one_complete_body_predicate_and_exact_donor_head(
    owner, case, damage
):
    if damage == "omit_role":
        case["request"]["body_roles"].pop()
    elif damage == "reverse_roles":
        case["request"]["body_roles"].reverse()
    elif damage == "head_as_body":
        case["request"]["consumer_symbol"] = case["consumer"]["candidate"][
            "term_record"
        ]["symbol"]
    else:
        case["request"]["donor_symbol"] = case["consumer"]["candidate"]["term_record"][
            "symbol"
        ]
    with pytest.raises(ValueError):
        prepare(owner, case)


@pytest.mark.parametrize("status", ["unavailable", "ambiguous", "unresolved"])
def test_complete_lookup_routes_cannot_promote_unavailable_competing_or_negative_results(
    owner, case, status
):
    case["lookup_inputs"] = lookup_inputs(case, status=status)
    assert json.loads(case["lookup_inputs"]["lookup_raw"])["selected_symbol_id"] is None
    with pytest.raises(ValueError):
        prepare(owner, case)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_version_cid", cid("foreign-source")),
        ("scope_cid", cid("foreign-scope")),
    ],
)
def test_pinned_partition_source_metadata_must_match_original_candidate(
    owner, case, field, value
):
    case["lookup_inputs"] = lookup_inputs(
        case, metadata_change=("donor", {field: value})
    )
    with pytest.raises(ValueError):
        prepare(owner, case)


@pytest.mark.parametrize(
    "field,value",
    [
        ("release_id", "foreign-release"),
        ("edition", 2025),
        ("applicability_cid", cid("foreign-applicability")),
    ],
)
def test_self_consistent_lookup_metadata_cannot_override_candidate_release_or_applicability(
    owner, case, field, value
):
    # Both partitions agree, so the existing resolver may legitimately resolve;
    # the new source-to-native bridge must still compare the actual candidates.
    args = lookup_inputs(case)
    registry = json.loads(args["registry_raw"])
    for partition in registry["partitions"]:
        partition[field] = value
        replacement = contracts.seal_record(
            {k: v for k, v in partition.items() if k not in {"record_cid", "cid_scope"}}
        )
        partition.clear()
        partition.update(replacement)
    registry = contracts.seal_record(
        {k: v for k, v in registry.items() if k not in {"record_cid", "cid_scope"}}
    )
    query = args["query_raw"]
    lookup = resolver.resolve_definition_lookup(registry, query, sha(query))
    registry_raw, lookup_raw = wire(registry), wire(lookup)
    case["lookup_inputs"] = args | {
        "registry_raw": registry_raw,
        "expected_registry_sha256": sha(registry_raw),
        "expected_registry_cid": registry["record_cid"],
        "lookup_raw": lookup_raw,
        "expected_lookup_sha256": sha(lookup_raw),
        "expected_lookup_cid": lookup["record_cid"],
    }
    with pytest.raises(ValueError):
        prepare(owner, case)


@pytest.mark.parametrize(
    "change",
    [
        {"source_node_ids": [cid("foreign-definition")]},
        {"span_ids": [cid("foreign-head")]},
        {"name": "CAFÉ MEMBER"},
        {
            "metadata": {
                "selected_native_symbol": "invented",
                "source_semantics_verified": True,
            }
        },
    ],
)
def test_selected_table_declaration_requires_exact_native_definition_and_head_sources(
    owner, case, change
):
    if "metadata" in change:
        # A fake selected native ID in metadata cannot repair a foreign symbol ID.
        change = change | {"symbol_id": "fixture:foreign-native-symbol"}
    case["lookup_inputs"] = lookup_inputs(case, definition_change=change)
    with pytest.raises(ValueError):
        prepare(owner, case)


@pytest.mark.parametrize(
    "damage", ["second_occurrence", "interpretation", "literal", "target_scope", "kind"]
)
def test_resolved_query_still_requires_exact_representative_source_and_native_route(
    owner, case, damage
):
    args = case["lookup_inputs"]
    registry = json.loads(args["registry_raw"])
    query = json.loads(args["query_raw"])
    if damage == "second_occurrence":
        query["source_occurrence_cid"] = next(
            row["source_occurrence_cid"]
            for row in case["consumer"]["candidate"]["source_bindings"]
            if row["role"] == "definition_body/0001"
        )
    elif damage == "interpretation":
        query["interpretation_cid"] = case["donor"]["candidate"]["report_record"][
            "record_cid"
        ]
    elif damage == "literal":
        query["reference"]["name"] = "CAFÉ MEMBER"
        query["reference"]["normalized_name"] = symbols.normalize_legal_symbol_name(
            query["reference"]["name"]
        )
    elif damage == "target_scope":
        query["reference"]["explicit_scope_id"] = ""
    else:
        query["reference"]["symbol_kind"] = "unknown"
    query_raw = wire(query)
    lookup = resolver.resolve_definition_lookup(registry, query_raw, sha(query_raw))
    assert lookup["status"] == "resolved"
    assert lookup["selected_symbol_id"] == case["request"]["donor_symbol"]
    lookup_raw = wire(lookup)
    case["lookup_inputs"] = args | {
        "query_raw": query_raw,
        "expected_query_sha256": sha(query_raw),
        "lookup_raw": lookup_raw,
        "expected_lookup_sha256": sha(lookup_raw),
        "expected_lookup_cid": lookup["record_cid"],
    }
    with pytest.raises(ValueError):
        prepare(owner, case)


@pytest.mark.parametrize(
    "damage", ["same_document", "different_family", "same_candidate"]
)
def test_bounded_profile_refuses_unsupported_document_family_or_self_binding(
    owner, case, damage
):
    if damage == "same_document":
        case = fixture(owner, same_document=True)
    elif damage == "different_family":
        case = fixture(owner, consumer_family="tdfol")
    else:
        case["donor"]["evidence"] = deepcopy(case["consumer"]["evidence"])
    with pytest.raises(ValueError):
        prepare(owner, case)


@pytest.mark.parametrize(
    "damage",
    ["preparation_cid", "omitted_context", "context_transport", "original_ast"],
)
def test_original_candidates_preparations_and_complete_contexts_are_replayed(
    owner, case, damage
):
    evidence = case["consumer"]["evidence"]
    if damage == "preparation_cid":
        evidence["expected_preparation_cid"] = cid("foreign-preparation")
    elif damage == "omitted_context":
        evidence["context_inputs"].pop()
        evidence["expected_context_population"].pop()
    elif damage == "context_transport":
        evidence["context_inputs"][0]["packet_raw"] += b" "
    else:
        record = json.loads(evidence["candidate_inputs"]["candidate_raw"])
        record["ast_record"]["native_ast"]["formula"]["operator"]["value"] = "→"
        record["ast_record"] = contracts.seal_record(
            {
                k: v
                for k, v in record["ast_record"].items()
                if k not in {"record_cid", "cid_scope"}
            }
        )
        record = contracts.seal_record(
            {k: v for k, v in record.items() if k not in {"record_cid", "cid_scope"}}
        )
        raw = canonical_dag_json_bytes(record)
        evidence["candidate_inputs"]["candidate_raw"] = raw
        evidence["expected_candidate_pin"].update(
            candidate_sha256=sha(raw), candidate_cid=record["record_cid"]
        )
    with pytest.raises(ValueError):
        prepare(owner, case)


@pytest.mark.parametrize(
    "field",
    [
        "expected_registry_sha256",
        "expected_registry_cid",
        "expected_lookup_sha256",
        "expected_lookup_cid",
        "expected_query_sha256",
    ],
)
def test_every_independent_lookup_and_registry_identity_is_required(owner, case, field):
    case["lookup_inputs"][field] = (
        cid("foreign") if field.endswith("_cid") else "0" * 64
    )
    with pytest.raises(ValueError):
        prepare(owner, case)


@pytest.mark.parametrize("damage", ["alias_ast", "graph_endpoint", "false_authority"])
def test_resealed_use_candidate_cannot_promote_or_replace_bound_native_and_graph_content(
    owner, case, damage
):
    record = prepare(owner, case)
    if damage == "alias_ast":
        record["alias_native"]["native_ast"]["formula"]["operator"]["value"] = "→"
    elif damage == "graph_endpoint":
        next(
            edge
            for edge in record["graph"]["edges"]
            if edge["relation"] == "USES_DEFINITION"
        )["dst_cid"] = record["binding_record"]["record_cid"]
        record["graph"] = contracts.seal_record(
            {
                k: v
                for k, v in record["graph"].items()
                if k not in {"record_cid", "cid_scope"}
            }
        )
    else:
        record["admitted"] = True
    record = contracts.seal_record(
        {k: v for k, v in record.items() if k not in {"record_cid", "cid_scope"}}
    )
    raw, kwargs = arguments(case)
    with pytest.raises(ValueError):
        owner.validate_definition_use_candidate_v2(record, raw, **kwargs)


@pytest.mark.parametrize("damage", ["request", "aggregate"])
def test_input_bounds_precede_native_resolver_and_review_operation_imports(
    owner, case, damage
):
    raw, kwargs = arguments(case)
    if damage == "request":
        raw = b" " * (contracts.MAX_RECORD_BYTES + 1)
        kwargs["expected_request_sha256"] = sha(raw)
    else:
        for role in ("donor_evidence_inputs", "consumer_evidence_inputs"):
            large = b" " * (25 * 1024 * 1024)
            kwargs[role]["candidate_inputs"]["sampling_report_raw"] = large
            kwargs[role]["expected_candidate_pin"]["sampling_report_sha256"] = sha(
                large
            )
    original_import = builtins.__import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        blocked = {
            "legal_family_routes",
            "scoped_definition_resolution",
            "corpus_definition_review_v2",
        }
        if name.rsplit(".", 1)[-1] in blocked or blocked.intersection(fromlist or ()):
            raise AssertionError(
                "operation owner loaded before complete input budget check"
            )
        return original_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", guarded):
        with pytest.raises(ValueError):
            owner.prepare_definition_use_v2(raw, **kwargs)


@pytest.mark.parametrize("damage", ["candidate_pin", "population", "occurrence_cid"])
def test_evidence_metadata_is_bounded_and_typed_before_operation_owner_imports(
    owner, case, damage
):
    raw, kwargs = arguments(case)
    evidence = kwargs["consumer_evidence_inputs"]
    if damage == "candidate_pin":
        evidence["expected_candidate_pin"]["extracted_sha256"] = "x" * (
            contracts.MAX_RECORD_BYTES + 1
        )
    else:
        value = (
            "x" * (contracts.MAX_RECORD_BYTES + 1)
            if damage == "population"
            else "not-a-cid"
        )
        evidence["context_inputs"][0]["source_occurrence_cid"] = value
        evidence["expected_context_population"][0]["source_occurrence_cid"] = value
    original_import = builtins.__import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        blocked = {
            "legal_family_routes",
            "scoped_definition_resolution",
            "corpus_definition_review_v2",
        }
        if name.rsplit(".", 1)[-1] in blocked or blocked.intersection(fromlist or ()):
            raise AssertionError(
                "operation owner loaded before evidence metadata checks"
            )
        return original_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", guarded):
        with pytest.raises(ValueError):
            owner.prepare_definition_use_v2(raw, **kwargs)


def test_import_remains_inert_without_native_resolver_or_review_owners():
    script = """
import importlib,sys
module=importlib.import_module('ipfs_datasets_py.logic.autoformal.corpus_definition_use_v2')
for name in ('legal_family_routes','scoped_definition_resolution','corpus_definition_review_v2'):
    assert 'ipfs_datasets_py.logic.autoformal.'+name not in sys.modules,name
assert callable(module.prepare_definition_use_v2)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr
