"""Explicit candidate assumptions connecting two V2 unary definitions.

Both original interpretations remain unchanged. A new, unreviewed unary alias
assumption connects a whole consumer predicate to one explicitly selected donor
head. A representative lookup does not establish per-occurrence applicability.
No compiler, resolver or numerical runtime is loaded by public import.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ipfs_datasets_py.utils import cid_utils
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes, cid_for_dag_json

from . import corpus_contracts as contracts
from . import corpus_graph as graph

SCHEMA = "legal-corpus-v2-definition-use-candidate/v1"
REQUEST_SCHEMA = "legal-corpus-v2-definition-use-request/v1"
PROFILE = "declared-v2-unary-definition-use-alias-assumption/v1"
BINDING_SCHEMA = "legal-corpus-v2-definition-use-binding/v1"
INTERPRETATION_SCHEMA = "legal-corpus-v2-definition-use-interpretation/v1"
AST_SCHEMA = "legal-corpus-v2-definition-use-alias-ast/v1"
PARENT_SCHEMA = "legal-corpus-parent-definition-use-candidate/v1"
PARENT_REQUEST_SCHEMA = "legal-corpus-parent-definition-use-request/v1"
PARENT_PROFILE = "declared-plaintext-parent-unary-definition-use-alias-assumption/v1"
PARENT_BINDING_SCHEMA = "legal-corpus-parent-definition-use-binding/v1"
PARENT_INTERPRETATION_SCHEMA = "legal-corpus-parent-definition-use-interpretation/v1"
PARENT_AST_SCHEMA = "legal-corpus-parent-definition-use-alias-ast/v1"
LOOKUP_COVERAGE = "representative_first_occurrence_whole_predicate_assumption"
MAX_TOTAL_INPUT_BYTES = 48 * 1024 * 1024
MAX_SOURCE_BYTES = 8_000_000
MAX_SAMPLING_BYTES = 32 * 1024 * 1024
MAX_OCCURRENCES = 256
MAX_CONTEXT_OBLIGATIONS = 1536
MAX_BODY_ROLES = 512
FALSE_FLAGS = dict.fromkeys(
    (
        "admitted",
        "formalized",
        "source_semantics_verified",
        "source_authenticity_verified",
        "applicability_verified",
        "context_closure_verified",
        "independently_reviewed",
        "proof_authority",
        "backend_executed",
        "lean_compilation_verified",
        "training_qualified",
        "training_gold_qualified",
        "model_executed",
        "learned_translation",
        "semantic_definition_binding_verified",
        "per_occurrence_lookup_verified",
        "accepted_view_eligible",
        "combined_use_review_verified",
    ),
    False,
)
PARENT_FALSE_FLAGS = {
    **FALSE_FLAGS,
    "governing_scope_verified": False,
    "governing_edition_verified": False,
    "contributor_completeness_verified": False,
}
_REQUEST_FIELDS = {
    "schema",
    "profile",
    "interpretation_status",
    "use_id",
    "consumer_symbol",
    "donor_symbol",
    "body_roles",
    "donor_partition_id",
    "local_partition_id",
}
_EVIDENCE_FIELDS = {
    "candidate_inputs",
    "expected_candidate_pin",
    "context_inputs",
    "expected_context_population",
    "expected_preparation_cid",
}
_RAW_PINS = {
    "candidate_raw": "candidate_sha256",
    "report_raw": "report_sha256",
    "request_raw": "request_sha256",
    "raw_html": "raw_sha256",
    "sampling_report_raw": "sampling_report_sha256",
    "descriptor_raw": "descriptor_sha256",
}
_CANDIDATE_PIN_FIELDS = set(_RAW_PINS.values()) | {
    "candidate_cid",
    "graph_cid",
    "raw_bytes",
    "extracted_sha256",
    "sampling_report_full_canonical_sha256",
    "descriptor_full_canonical_sha256",
}
FIELDS = {
    "profile",
    "family",
    "view",
    "interpretation_record",
    "binding_record",
    "alias_record",
    "alias_native",
    "joint_native",
    "graph",
    "context_population",
    "context_slot_ids",
    "dependency_manifest",
    "expected_artifact_ids",
    "donor_preparation_cid",
    "consumer_preparation_cid",
    "input_pins",
    "producer_pins",
    "original_interpretations_unchanged",
    "declared_native_binding_encoded",
    "review_status",
    "limitations",
    *FALSE_FLAGS,
}
PARENT_FIELDS = FIELDS | set(PARENT_FALSE_FLAGS)


def _fail(message):
    raise contracts.CorpusContractError(message)


def _need(value, message):
    if not value:
        _fail(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return _sha(canonical_dag_json_bytes(value))


def _pure_pins():
    return {
        str(path): _sha(path.read_bytes())
        for path in (
            Path(__file__).resolve(),
            Path(contracts.__file__).resolve(),
            Path(graph.__file__).resolve(),
            Path(cid_utils.__file__).resolve(),
        )
    }


_IMPORTED_PURE_PINS = _pure_pins()
_LAZY_PINS = None


def _owners():
    from . import corpus_definition_review_v2 as review
    from . import legal_family_routes as routes
    from . import legal_graph_dependencies as dependencies
    from . import scoped_definition_resolution as lookup

    return review, lookup, routes, dependencies


def _pins(owners):
    global _LAZY_PINS
    _need(_pure_pins() == _IMPORTED_PURE_PINS, "V2 use owners changed since import")
    actual = {
        str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
        for module in owners
    }
    if _LAZY_PINS is None:
        _LAZY_PINS = actual
    _need(actual == _LAZY_PINS, "V2 use lazy owners changed since first explicit use")
    return {**_IMPORTED_PURE_PINS, **actual}


def _bounded(raw, expected, maximum, label):
    _need(
        type(raw) is bytes and len(raw) <= maximum,
        "bounded original " + label + " bytes required",
    )
    contracts.require_sha256(expected, label + " SHA256")
    _need(_sha(raw) == expected, "original " + label + " hash differs")


def _preflight(evidence):
    """Check every raw commitment/budget before optional owners or parsing."""
    contracts.require_keys(evidence, _EVIDENCE_FIELDS, "V2 use evidence inputs")
    contracts.require_cid(
        evidence["expected_preparation_cid"],
        "expected preparation CID",
        codecs=("dag-json",),
    )
    inputs, pins = evidence["candidate_inputs"], evidence["expected_candidate_pin"]
    contracts.require_keys(inputs, set(_RAW_PINS), "V2 use original candidate inputs")
    pins = contracts.clone_json(pins)
    contracts.require_keys(pins, _CANDIDATE_PIN_FIELDS, "independent V2 candidate pins")
    for key in _CANDIDATE_PIN_FIELDS:
        if key in {"candidate_cid", "graph_cid"}:
            contracts.require_cid(pins[key], key, codecs=("dag-json",))
        elif key == "raw_bytes":
            contracts.require_int(pins[key], key, maximum=MAX_SOURCE_BYTES)
        else:
            contracts.require_sha256(pins[key], key)
    total = len(canonical_dag_json_bytes(pins))
    for field, commitment in _RAW_PINS.items():
        maximum = (
            MAX_SAMPLING_BYTES
            if field == "sampling_report_raw"
            else (
                MAX_SOURCE_BYTES if field == "raw_html" else contracts.MAX_RECORD_BYTES
            )
        )
        _bounded(inputs[field], pins.get(commitment), maximum, field)
        total += len(inputs[field])
    _need(pins["raw_bytes"] == len(inputs["raw_html"]), "original HTML length differs")
    contexts, population = (
        evidence["context_inputs"],
        evidence["expected_context_population"],
    )
    _need(
        type(contexts) is list
        and type(population) is list
        and len(contexts) == len(population)
        and 1 <= len(contexts) <= MAX_OCCURRENCES,
        "complete bounded context input population required",
    )
    population = contracts.clone_json(population)
    total += len(canonical_dag_json_bytes(population))
    for row, pin in zip(contexts, population, strict=True):
        contracts.require_keys(
            row,
            {"source_occurrence_cid", "packet_raw", "dependency_requests"},
            "context input",
        )
        contracts.require_keys(
            pin, {"source_occurrence_cid", "packet_sha256"}, "context pin"
        )
        contracts.require_cid(
            row["source_occurrence_cid"], "context occurrence CID", codecs=("dag-json",)
        )
        contracts.require_cid(
            pin["source_occurrence_cid"], "context population CID", codecs=("dag-json",)
        )
        _need(
            row["source_occurrence_cid"] == pin["source_occurrence_cid"],
            "context occurrence order differs",
        )
        _bounded(
            row["packet_raw"],
            pin["packet_sha256"],
            contracts.MAX_RECORD_BYTES,
            "context packet",
        )
        total += len(row["packet_raw"]) + len(
            canonical_dag_json_bytes(contracts.clone_json(row["dependency_requests"]))
        )
    return total


def _prepare(evidence, review):
    preparation = review.prepare_definition_review_evidence_v2(
        **{
            key: evidence[key]
            for key in _EVIDENCE_FIELDS - {"expected_preparation_cid"}
        }
    )
    _need(
        preparation["record_cid"] == evidence["expected_preparation_cid"],
        "independent V2 preparation CID differs",
    )
    candidate = contracts.load_record_bytes(
        evidence["candidate_inputs"]["candidate_raw"],
        expected_sha256=evidence["expected_candidate_pin"]["candidate_sha256"],
    )
    report = contracts.load_record_bytes(
        evidence["candidate_inputs"]["report_raw"],
        expected_sha256=evidence["expected_candidate_pin"]["report_sha256"],
    )
    return preparation, candidate, report


def _parent_use_preflight(evidence):
    """Reuse the parent byte preflight; count both complete logical transports.

    Shared objects or physical storage do not reduce logical input accounting.
    This imports the existing pure review preflight, never a source replay,
    signature check, model or native build. The complete replay follows later.
    """
    fields = _EVIDENCE_FIELDS | {"parent_inputs"}
    contracts.require_keys(
        evidence, fields | ({"parent_limits"} if "parent_limits" in evidence else set()),
        "parent use evidence inputs",
    )
    contracts.require_cid(evidence["expected_preparation_cid"],
                          "expected parent preparation CID", codecs=("dag-json",))
    from . import corpus_definition_review_v2 as review

    pins, population, transport = review._parent_preflight(
        evidence["candidate_inputs"], evidence["expected_candidate_pin"],
        evidence["parent_inputs"], evidence["context_inputs"],
        evidence["expected_context_population"], evidence.get("parent_limits"),
    )
    parent = evidence["parent_inputs"]
    total = sum(len(raw) for raw in evidence["candidate_inputs"].values())
    total += transport["parent_bundle"]["bytes"] + transport["replay_inputs"]["bytes"]
    total += sum(row["bytes"] for row in transport["report_bytes"].values())
    requests = []
    for row in evidence["context_inputs"]:
        request = contracts.clone_json(row["dependency_requests"])
        requests.append(request)
        total += len(row["packet_raw"]) + len(canonical_dag_json_bytes(request))
    metadata = {
        "expected_preparation_cid": evidence["expected_preparation_cid"],
        "candidate_pins": pins,
        "context_population": population,
        "transport": transport,
        "expected_report_pins": parent["expected_report_pins"],
        "parent_limits": evidence.get("parent_limits"),
        "dependency_requests": requests,
    }
    # Metadata is additionally charged even when some of its commitments also
    # occur in the raw inputs. Never deduplicate repeated endpoint originals.
    total += len(canonical_dag_json_bytes(contracts.clone_json(metadata)))
    _need(total <= MAX_TOTAL_INPUT_BYTES, "complete parent use input byte budget exceeded")
    return total, _digest(metadata)


def _prepare_parent(evidence, review):
    preparation = review.prepare_parent_definition_review_evidence_v1(
        **{key: value for key, value in evidence.items()
           if key != "expected_preparation_cid"}
    )
    _need(preparation["record_cid"] == evidence["expected_preparation_cid"],
          "independent parent preparation CID differs")
    candidate = contracts.load_record_bytes(evidence["candidate_inputs"]["candidate_raw"],
        expected_sha256=evidence["expected_candidate_pin"]["candidate_sha256"])
    report = contracts.load_record_bytes(evidence["candidate_inputs"]["report_raw"],
        expected_sha256=evidence["expected_candidate_pin"]["report_sha256"])
    return preparation, candidate, report


def _contexts(preparations):
    """Union physical geometry, retaining both ordered role populations elsewhere."""
    contexts, slots = {}, []
    for preparation in preparations:
        for occurrence, context in zip(
            preparation["source_occurrences"], preparation["contexts"], strict=True
        ):
            identity = occurrence["record_cid"]
            row = {"source_occurrence": occurrence, "context": context}
            if identity in contexts:
                _need(
                    contexts[identity] == row,
                    "shared physical context packets or requests conflict",
                )
            else:
                contexts[identity] = row
                slots.extend(item["slot_id"] for item in context["dependency_slots"])
    _need(
        len(contexts) <= MAX_OCCURRENCES
        and len(slots) <= MAX_CONTEXT_OBLIGATIONS
        and len(slots) == len(contexts) * 6
        and len(set(slots)) == len(slots),
        "complete combined context population exceeds profile or has duplicate slots",
    )
    return list(contexts.values()), slots


def _partition(row, candidate, applicability_cid):
    version = candidate["source_version"]
    _need(
        row["availability"] == "available"
        and row["document_id"] == version["source_id"]
        and row["source_version_cid"] == version["record_cid"]
        and row["release_id"] == version["release_id"]
        and str(row["edition"]) == version["edition"]
        and row["scope_cid"] == candidate["scope_record"]["record_cid"]
        and row["applicability_cid"] == applicability_cid,
        "lookup partition differs from exact candidate source, scope or applicability",
    )


def _parent_partition(row, candidate, preparation):
    """A declared lookup partition must match independently replayed originals."""
    version = candidate["source_version"]
    binding = preparation["parent_input_binding"]
    expected = {
        "document_id": version["source_id"],
        "source_version_cid": version["record_cid"],
        "release_id": version["release_id"],
        "edition": version["edition"],
        "scope_cid": candidate["scope_record"]["record_cid"],
        "preparation_cid": preparation["record_cid"],
        **{key: binding[key] for key in (
            "parent_manifest_cid", "root_source_occurrence_cid",
            "companion_record_cid", "source_binding_sha256")},
    }
    _need(row["availability"] == "available"
          and all(row[key] == value for key, value in expected.items()),
          "parent lookup partition differs from independently replayed source or preparation")


def _selected_binding(request, donor, consumer, registry, lookup, parent_preparations=None):
    _need(
        donor["record_cid"] != consumer["record_cid"]
        and donor["source_version"]["source_id"]
        != consumer["source_version"]["source_id"],
        "initial V2 use profile requires two distinct physical documents",
    )
    _need(
        donor["family"] == consumer["family"] and donor["family"] in {"fol", "tdfol"},
        "matching unary native families required",
    )
    applicability_cid = None
    if parent_preparations is None:
        applicability = donor["scope_record"]["declared_applicability"]
        _need(
            applicability == consumer["scope_record"]["declared_applicability"],
            "exact shared declared applicability required",
        )
        applicability_cid = cid_for_dag_json(applicability)
    donor_symbol = donor["term_record"]["symbol"]
    _need(
        request["donor_symbol"] == donor_symbol
        and donor_symbol
        == donor["ast_record"]["native_ast"]["formula"]["left"]["name"],
        "selected donor must be exact native definition head",
    )
    _need(
        donor["term_record"]["arity"] == 1
        and donor["term_record"]["carrier"] == "Entity",
        "unary Entity donor required",
    )
    consumer_symbol = request["consumer_symbol"]
    symbol = next(
        (
            row
            for row in consumer["symbol_record"]["symbols"]
            if row["symbol"] == consumer_symbol
        ),
        None,
    )
    _need(
        symbol is not None
        and symbol["arity"] == 1
        and consumer_symbol != consumer["term_record"]["symbol"],
        "body-only unary consumer predicate required",
    )
    body = [
        row
        for row in consumer["source_bindings"]
        if row["symbol"] == consumer_symbol
        and row["role"].startswith("definition_body/")
    ]
    _need(
        body and request["body_roles"] == [row["role"] for row in body],
        "complete ordered body predicate role population required",
    )
    _need(
        lookup["status"] == "resolved" and lookup["selected_symbol_id"] == donor_symbol,
        "all-available uniquely selected donor lookup required",
    )
    partitions = {row["partition_id"]: row for row in registry["partitions"]}
    route = [row["partition_id"] for row in lookup["partition_refs"]]
    local_id, donor_id = request["local_partition_id"], request["donor_partition_id"]
    _need(
        local_id != donor_id and route[0] == local_id and donor_id in route,
        "exact local and donor query route required",
    )
    local, target = partitions[local_id], partitions[donor_id]
    if parent_preparations is None:
        _partition(local, consumer, applicability_cid)
        _partition(target, donor, applicability_cid)
    else:
        _parent_partition(local, consumer, parent_preparations[1])
        _parent_partition(target, donor, parent_preparations[0])
    reference = lookup["reference"]
    donor_document = donor["source_version"]["source_id"]
    consumer_document = consumer["source_version"]["source_id"]
    target_scope = "document:" + donor_document
    _need(
        reference["name"] == symbol["source_literal"]
        and reference["symbol_kind"] == "defined_term"
        and reference["document_id"] == consumer_document
        and reference["scope_id"] == "document:" + consumer_document
        and reference["explicit_target_document_id"] == donor_document
        and reference["explicit_scope_id"] == target_scope
        and lookup["source_occurrence_cid"] == body[0]["source_occurrence_cid"]
        and lookup["interpretation_cid"] == consumer["report_record"]["record_cid"],
        "representative query must bind exact first use, interpretation and explicit target",
    )
    table = contracts.load_record_bytes(
        target["table_json"].encode(), expected_sha256=target["table_sha256"]
    )
    selected = [row for row in table["definitions"] if row["symbol_id"] == donor_symbol]
    _need(
        len(selected) == 1, "selected native symbol requires one exact table definition"
    )
    definition = selected[0]
    _need(
        definition["name"] == donor["term_record"]["source_literal"]
        and definition["symbol_kind"] == "defined_term"
        and definition["document_id"] == donor_document
        and definition["scope_id"] == target_scope
        and definition["source_node_ids"] == [donor["definition_record"]["record_cid"]]
        and definition["span_ids"] == donor["term_record"]["source_occurrence_cids"],
        "selected table row differs from donor head, definition, scope or physical origin",
    )
    return body, {
        "partition_id": donor_id,
        "partition_cid": target["record_cid"],
        "table_sha256": target["table_sha256"],
        "selected_row_sha256": _digest(definition),
        "source_version_cid": donor["source_version"]["record_cid"],
        "scope_record_cid": donor["scope_record"]["record_cid"],
        "definition_record_cid": donor["definition_record"]["record_cid"],
        "term_record_cid": donor["term_record"]["record_cid"],
        **({"applicability_cid": applicability_cid} if parent_preparations is None else {
            "preparation_cid": parent_preparations[0]["record_cid"],
            "source_binding_sha256": target["source_binding_sha256"],
            "scope_relation": "unreviewed_caller_declared_route",
            "applicability_verified": False,
            "governing_edition_verified": False,
        }),
    }


def _native(donor, consumer, reports, request, routes):
    from ..intent_ir.formalize.modal_projections import _ast
    from ..TDFOL import tdfol_core as t

    x = t.Variable("x")
    alias = t.QuantifiedFormula(
        t.Quantifier.FORALL,
        x,
        t.BinaryFormula(
            t.LogicOperator.IFF,
            t.Predicate(request["consumer_symbol"], (x,)),
            t.Predicate(request["donor_symbol"], (x,)),
        ),
    )
    alias_native = routes.prepare_native_fragment(
        family=donor["family"], formula=alias.to_string(), expected_ast=_ast(alias)
    )
    donor_ast, consumer_ast = (
        donor["ast_record"]["native_ast"],
        consumer["ast_record"]["native_ast"],
    )

    def conjunction(left, right):
        return {
            "node_type": "BinaryFormula",
            "operator": {"enum": "LogicOperator", "value": "∧"},
            "left": left,
            "right": right,
        }

    expected = conjunction(
        donor_ast, conjunction(consumer_ast, alias_native["native_ast"])
    )
    formula = (
        "(∧ "
        + reports[0]["native"]["formula"]
        + " (∧ "
        + reports[1]["native"]["formula"]
        + " "
        + alias_native["formula"]
        + "))"
    )
    joint = routes.prepare_native_fragment(
        family=donor["family"], formula=formula, expected_ast=expected
    )
    return alias_native, joint


def _graph(donor, consumer, interpretation, binding, alias):
    nodes, edges = {}, {}
    for original in (donor, consumer):
        for node in original["graph"]["nodes"]:
            nodes[node["record_cid"]] = node
        for edge in original["graph"]["edges"]:
            edges[edge["record_cid"]] = edge
    origins = list(
        dict.fromkeys(
            row["record_cid"]
            for original in (donor, consumer)
            for row in original["source_occurrences"]
        )
    )
    int_node = graph.build_node(
        node_type="interpretation",
        stable_id=interpretation["record_cid"],
        content_cid=interpretation["record_cid"],
        source_occurrence_cids=origins,
    )
    ast_node = graph.build_node(
        node_type="expression",
        stable_id=alias["record_cid"],
        content_cid=alias["record_cid"],
        scope_cid=consumer["scope_record"]["record_cid"],
        source_occurrence_cids=binding["body_occurrence_cids"],
        interpretation_cids=[interpretation["record_cid"]],
    )
    nodes.update({row["record_cid"]: row for row in (int_node, ast_node)})

    def endpoint(candidate):
        return next(
            row["record_cid"]
            for row in candidate["graph"]["nodes"]
            if row["content_cid"] == candidate["definition_record"]["record_cid"]
            and row["node_type"] == "definition_assertion"
        )

    for src, dst, relation in (
        (endpoint(consumer), endpoint(donor), "USES_DEFINITION"),
        (ast_node["record_cid"], int_node["record_cid"], "DERIVED_FROM"),
        (ast_node["record_cid"], endpoint(consumer), "CITES"),
        (ast_node["record_cid"], endpoint(donor), "CITES"),
    ):
        edge = graph.build_edge(
            src_cid=src,
            dst_cid=dst,
            relation=relation,
            evidence_cids=[
                binding["record_cid"],
                interpretation["record_cid"],
                binding["lookup_cid"],
            ],
        )
        edges[edge["record_cid"]] = edge
    return graph.build_graph_snapshot(list(nodes.values()), list(edges.values()))


def _dependencies(
    preparations,
    lookup_manifest,
    snapshot,
    records,
    native,
    pins,
    producers,
    dependencies,
    prefix="v2-use",
):
    artifacts, edges = {}, set()

    def add(row):
        key = row["artifact_id"]
        _need(
            key not in artifacts or artifacts[key] == row,
            "combined dependency identities conflict",
        )
        artifacts[key] = row

    def artifact(key, digest, policy=()):
        return {
            "artifact_id": key,
            "artifact_sha256": digest,
            "dependency_pins": {
                kind: list(policy) if kind == "policy" else []
                for kind in dependencies.PIN_KINDS
            },
        }

    policy = [
        {"key": prefix + "-owner:" + path, "sha256": digest}
        for path, digest in sorted(producers.items())
    ]
    add(artifact(snapshot["record_cid"], _digest(snapshot), policy))
    for preparation in preparations:
        for row in preparation["artifacts"]:
            add(row)
        add(artifact(preparation["record_cid"], _digest(preparation)))
        for edge in preparation["edges"]:
            edges.add((edge["dependent_id"], edge["dependency_id"]))
    for row in lookup_manifest["artifacts"]:
        add(row)
    edges.update(
        (row["dependent_id"], row["dependency_id"]) for row in lookup_manifest["edges"]
    )
    for row in records:
        add(artifact(row["record_cid"], _digest(row)))
    add(artifact(prefix + "-joint-native:sha256:" + _digest(native), _digest(native)))
    for label, digest in pins.items():
        add(artifact(prefix + "-input:" + label + ":sha256:" + digest, digest))
    edges.update(
        (snapshot["record_cid"], key)
        for key in artifacts
        if key != snapshot["record_cid"]
    )
    ids = list(artifacts)
    manifest = dependencies.build_dependency_manifest(
        list(artifacts.values()),
        [
            {"dependent_id": left, "dependency_id": right}
            for left, right in sorted(edges)
        ],
        expected_artifact_ids=ids,
    )
    return manifest, ids


def _prepare_definition_use(
    request_raw,
    *,
    expected_request_sha256,
    donor_evidence_inputs,
    consumer_evidence_inputs,
    registry_raw,
    expected_registry_sha256,
    expected_registry_cid,
    lookup_raw,
    expected_lookup_sha256,
    expected_lookup_cid,
    query_raw,
    expected_query_sha256,
    parent=False,
):
    """Regenerate a bounded, unreviewed cross-document unary alias component."""
    _need(_pure_pins() == _IMPORTED_PURE_PINS, "V2 use owners changed since import")
    small = (
        (request_raw, expected_request_sha256, "request"),
        (registry_raw, expected_registry_sha256, "registry"),
        (lookup_raw, expected_lookup_sha256, "lookup"),
        (query_raw, expected_query_sha256, "query"),
    )
    for raw, expected, label in small:
        _bounded(raw, expected, contracts.MAX_RECORD_BYTES, label)
    if parent:
        endpoint_preflights = (
            _parent_use_preflight(donor_evidence_inputs),
            _parent_use_preflight(consumer_evidence_inputs),
        )
        total = sum(len(row[0]) for row in small) + sum(row[0] for row in endpoint_preflights)
    else:
        total = (sum(len(row[0]) for row in small)
                 + _preflight(donor_evidence_inputs) + _preflight(consumer_evidence_inputs))
    _need(
        total <= MAX_TOTAL_INPUT_BYTES,
        "complete combined original input byte budget exceeded",
    )
    for identity in (expected_registry_cid, expected_lookup_cid):
        contracts.require_cid(identity, "independent lookup CID", codecs=("dag-json",))
    request = contracts.load_record_bytes(
        request_raw, expected_sha256=expected_request_sha256
    )
    contracts.require_keys(request, _REQUEST_FIELDS, "explicit V2 use request")
    _need(
        request["schema"] == (PARENT_REQUEST_SCHEMA if parent else REQUEST_SCHEMA)
        and request["profile"] == (PARENT_PROFILE if parent else PROFILE)
        and request["interpretation_status"] == "unreviewed_caller_declaration",
        "explicit unreviewed V2 alias request required",
    )
    for field in (
        "use_id",
        "consumer_symbol",
        "donor_symbol",
        "donor_partition_id",
        "local_partition_id",
    ):
        contracts.require_text(request[field], field, max_bytes=512)
    _need(
        type(request["body_roles"]) is list
        and 1 <= len(request["body_roles"]) <= MAX_BODY_ROLES,
        "bounded complete body roles required",
    )
    for role in request["body_roles"]:
        contracts.require_text(role, "body role", max_bytes=512)
    owners = _owners()
    producers = _pins(owners)
    review, lookup_owner, routes, dependencies = owners
    prepare_endpoint = _prepare_parent if parent else _prepare
    dp, donor, dr = prepare_endpoint(donor_evidence_inputs, review)
    cp, consumer, cr = prepare_endpoint(consumer_evidence_inputs, review)
    contexts, slots = _contexts((dp, cp))
    registry = contracts.load_record_bytes(
        registry_raw, expected_sha256=expected_registry_sha256
    )
    validate_registry = (lookup_owner.validate_parent_definition_lookup_registry_v1
                         if parent else lookup_owner.validate_definition_lookup_registry)
    registry = validate_registry(
        registry, expected_registry_cid=expected_registry_cid
    )
    lookup = contracts.load_record_bytes(
        lookup_raw, expected_sha256=expected_lookup_sha256
    )
    _need(
        lookup["record_cid"] == expected_lookup_cid,
        "independent selected lookup CID differs",
    )
    validate_lookup = (lookup_owner.validate_parent_definition_lookup_v1
                       if parent else lookup_owner.validate_definition_lookup)
    lookup = validate_lookup(
        lookup, registry, query_raw, expected_query_sha256
    )
    body, table_binding = _selected_binding(request, donor, consumer, registry, lookup,
                                           (dp, cp) if parent else None)
    alias_native, joint = _native(donor, consumer, (dr, cr), request, routes)
    interpretation = contracts.seal_record(
        {
            "schema": PARENT_INTERPRETATION_SCHEMA if parent else INTERPRETATION_SCHEMA,
            "profile": PARENT_PROFILE if parent else PROFILE,
            "request_sha256": expected_request_sha256,
            "request_json": request_raw.decode(),
            "donor_preparation_cid": dp["record_cid"],
            "consumer_preparation_cid": cp["record_cid"],
            "interpretation_status": "unreviewed_caller_declaration",
            "original_interpretations_unchanged": True,
        }
    )
    binding = contracts.seal_record(
        {
            "schema": PARENT_BINDING_SCHEMA if parent else BINDING_SCHEMA,
            "profile": PARENT_PROFILE if parent else PROFILE,
            "use_id": request["use_id"],
            "consumer_candidate_cid": consumer["record_cid"],
            "donor_candidate_cid": donor["record_cid"],
            "consumer_definition_cid": consumer["definition_record"]["record_cid"],
            "consumer_interpretation_cid": consumer["report_record"]["record_cid"],
            "donor_definition_cid": donor["definition_record"]["record_cid"],
            "consumer_symbol": request["consumer_symbol"],
            "donor_symbol": request["donor_symbol"],
            "body_roles": [row["role"] for row in body],
            "body_bindings": body,
            "body_occurrence_cids": list(
                dict.fromkeys(row["source_occurrence_cid"] for row in body)
            ),
            "lookup_cid": lookup["record_cid"],
            "registry_cid": registry["record_cid"],
            "query_sha256": expected_query_sha256,
            "lookup_source_occurrence_cid": body[0]["source_occurrence_cid"],
            "lookup_coverage": LOOKUP_COVERAGE,
            "per_occurrence_lookup_verified": False,
            "donor_table_binding": table_binding,
            "carrier": "Entity",
            "arity": 1,
            "alias_semantics": "explicit_unreviewed_unary_biconditional_assumption",
            "interpretation_cid": interpretation["record_cid"],
            "semantic_definition_binding_verified": False,
        }
    )
    alias = contracts.seal_record(
        {
            "schema": PARENT_AST_SCHEMA if parent else AST_SCHEMA,
            "family": donor["family"],
            "native_ast": alias_native["native_ast"],
            "lean_body": alias_native["lean_body"],
            "binding_cid": binding["record_cid"],
            "interpretation_cid": interpretation["record_cid"],
            "assumed_not_proved": True,
            "lean_compilation_verified": False,
        }
    )
    snapshot = _graph(donor, consumer, interpretation, binding, alias)
    build_dependencies = (lookup_owner.build_parent_definition_lookup_dependencies_v1
                          if parent else lookup_owner.build_definition_lookup_dependencies)
    lookup_manifest = build_dependencies(
        registry, [lookup], [lookup["record_cid"]]
    )
    input_pins = {label: expected for _, expected, label in small}
    manifest, ids = _dependencies(
        (dp, cp),
        lookup_manifest,
        snapshot,
        (interpretation, binding, alias),
        joint,
        input_pins,
        producers,
        dependencies,
        prefix="parent-use" if parent else "v2-use",
    )
    _need(_pins(owners) == producers, "V2 use owners changed during preparation")
    if parent:
        _need(endpoint_preflights == (
            _parent_use_preflight(donor_evidence_inputs),
            _parent_use_preflight(consumer_evidence_inputs)),
            "parent original transport changed during combined preparation")
    return contracts.seal_record(
        {
            "schema": PARENT_SCHEMA if parent else SCHEMA,
            "profile": PARENT_PROFILE if parent else PROFILE,
            "family": donor["family"],
            "view": "candidate",
            "interpretation_record": interpretation,
            "binding_record": binding,
            "alias_record": alias,
            "alias_native": alias_native,
            "joint_native": joint,
            "graph": snapshot,
            "context_population": contexts,
            "context_slot_ids": slots,
            "dependency_manifest": manifest,
            "expected_artifact_ids": ids,
            "donor_preparation_cid": dp["record_cid"],
            "consumer_preparation_cid": cp["record_cid"],
            "input_pins": input_pins,
            "producer_pins": producers,
            "original_interpretations_unchanged": True,
            "declared_native_binding_encoded": True,
            "review_status": ("parent_combined_use_review_profile_and_actual_reviews_pending"
                              if parent else "new_combined_use_review_profile_and_actual_reviews_pending"),
            "limitations": [
                ("Two distinct physical plaintext parent documents; each endpoint replays original evidence and all declared contexts. Unknown editions and scope declarations do not establish governing compatibility."
                 if parent else "Two distinct physical documents, one supplied V2 candidate per endpoint; complete tables may contain additional unreviewed declarations."),
                "A whole local predicate is aliased by an unreviewed assumption; no identity or legal implication is proved.",
                "Only the first matching physical use is the representative lookup query; all body roles and contexts remain retained.",
                "Complete supplied tables are dependencies; governing inventory and legal applicability remain unverified.",
                "Original definition reviews cannot authorize this new alias or combined graph/native interpretation.",
                "No combined-use review domain, native Lean build profile, actual statutory meaning or admission is supplied.",
            ],
            **(PARENT_FALSE_FLAGS if parent else FALSE_FLAGS),
        }
    )


def prepare_definition_use_v2(
    request_raw, *, expected_request_sha256, donor_evidence_inputs,
    consumer_evidence_inputs, registry_raw, expected_registry_sha256,
    expected_registry_cid, lookup_raw, expected_lookup_sha256, expected_lookup_cid,
    query_raw, expected_query_sha256,
):
    """Prepare the unchanged official V2 source/applicability profile."""
    return _prepare_definition_use(request_raw,
        expected_request_sha256=expected_request_sha256,
        donor_evidence_inputs=donor_evidence_inputs,
        consumer_evidence_inputs=consumer_evidence_inputs, registry_raw=registry_raw,
        expected_registry_sha256=expected_registry_sha256,
        expected_registry_cid=expected_registry_cid, lookup_raw=lookup_raw,
        expected_lookup_sha256=expected_lookup_sha256, expected_lookup_cid=expected_lookup_cid,
        query_raw=query_raw, expected_query_sha256=expected_query_sha256)


def prepare_parent_definition_use_v1(
    request_raw, *, expected_request_sha256, donor_evidence_inputs,
    consumer_evidence_inputs, registry_raw, expected_registry_sha256,
    expected_registry_cid, lookup_raw, expected_lookup_sha256, expected_lookup_cid,
    query_raw, expected_query_sha256,
):
    """Compose candidate-only unary aliases from fully replayed plaintext parents.

    Lookup nominations remain unreviewed even when lexically unique. This API
    supplies neither combined-use signatures nor a native Lean admission route.
    """
    return _prepare_definition_use(request_raw,
        expected_request_sha256=expected_request_sha256,
        donor_evidence_inputs=donor_evidence_inputs,
        consumer_evidence_inputs=consumer_evidence_inputs, registry_raw=registry_raw,
        expected_registry_sha256=expected_registry_sha256,
        expected_registry_cid=expected_registry_cid, lookup_raw=lookup_raw,
        expected_lookup_sha256=expected_lookup_sha256, expected_lookup_cid=expected_lookup_cid,
        query_raw=query_raw, expected_query_sha256=expected_query_sha256, parent=True)


def validate_parent_definition_use_candidate_v1(record, request_raw, **validation_inputs):
    """Require exact regeneration from independently pinned original parent bytes."""
    checked = contracts.validate_record(record, schema=PARENT_SCHEMA, fields=PARENT_FIELDS)
    expected = prepare_parent_definition_use_v1(request_raw, **validation_inputs)
    _need(checked == expected, "parent definition use differs from complete independent regeneration")
    return checked


def validate_definition_use_candidate_v2(record, request_raw, **validation_inputs):
    """A resealed derivative must equal replay from all original pinned inputs."""
    checked = contracts.validate_record(record, schema=SCHEMA, fields=FIELDS)
    expected = prepare_definition_use_v2(request_raw, **validation_inputs)
    _need(
        checked == expected,
        "V2 definition use differs from complete independent regeneration",
    )
    return checked


__all__ = [
    "SCHEMA",
    "REQUEST_SCHEMA",
    "PROFILE",
    "FALSE_FLAGS",
    "MAX_TOTAL_INPUT_BYTES",
    "prepare_definition_use_v2",
    "validate_definition_use_candidate_v2",
    "PARENT_SCHEMA", "PARENT_REQUEST_SCHEMA", "PARENT_PROFILE", "PARENT_FALSE_FLAGS",
    "prepare_parent_definition_use_v1", "validate_parent_definition_use_candidate_v1",
]
