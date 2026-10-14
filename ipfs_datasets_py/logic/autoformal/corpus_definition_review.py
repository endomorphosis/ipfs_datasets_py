"""Replay typed native definition/norm evidence in a distinct review domain.

The candidate remains a caller interpretation in its original native profile.
Every physical source occurrence receives its own existing context packet.
Authentication delegates to the existing graph-review verifier; neither byte
custody nor signatures establish legal meaning, human identity or admission.
There is no signer, production trust registry, clock, network or backend default.
Public import does not load the review, context or native compiler owners.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from ipfs_datasets_py.utils import cid_utils
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

from . import corpus_contracts as contracts
from . import corpus_definition_norm_adapter as adapter
from . import corpus_graph, corpus_source

PREPARATION_SCHEMA = "legal-corpus-definition-review-evidence/v1"
SUBJECT_SCHEMA = "legal-corpus-definition-review-subject/v1"
CLAIM_SCHEMA = "legal-corpus-definition-review-signed-claim/v1"
ACTION = "record_definition_norm_review_evidence/v1"
AUDIENCE = "legal-autoformalization-definition-norm-review/v1"
SCHEMA = "legal-corpus-definition-review-assessment/v1"
PROFILE = "source-occurrence-complete-typed-native-definition-norm-review/v1"
MAX_CONTEXT_OCCURRENCES = 256
MAX_CONTEXT_OBLIGATIONS = 1536
MAX_INPUT_BYTES = 8 * 1024**2
INPUT_FIELDS = {"candidate_raw", "report_raw", "request_raw", "raw_html"}
POPULATION_FIELDS = {
    "candidate_sha256", "candidate_cid", "graph_cid", "request_sha256",
    "report_sha256", "raw_sha256", "extracted_sha256",
}
CONTEXT_INPUT_FIELDS = {"source_occurrence_cid", "packet_raw", "dependency_requests"}
CONTEXT_POPULATION_FIELDS = {"source_occurrence_cid", "packet_sha256"}
COMPANIONS = (
    "request_record", "report_record", "source_version", "scope_record", "symbol_record",
    "definition_record", "norm_record", "ast_record", "term_record", "input_binding",
)
FALSE_FLAGS = dict.fromkeys((
    "source_semantics_verified", "source_authenticity_verified", "context_closure_verified",
    "independently_reviewed", "admitted", "formalized", "proof_authority", "training_qualified",
    "backend_executed", "lean_compilation_verified", "human_identity_verified",
    "human_independence_verified", "external_definition_resolution_verified",
    "legal_dependency_inventory_exhaustive",
), False)
FIELDS = {
    "review_profile", "profile", "family", "candidate_pin", "graph_id", "graph_sha256",
    "ast_sha256", "scope_id", "scope_key", "companion_cids", "source_version",
    "source_occurrences", "source_bindings", "native_ast", "bound_definition_native_ast",
    "norm_native_ast", "native_ast_sha256s", "contexts", "context_slot_ids",
    "expected_context_population", "producer_pins", "native_producer_pins",
    "artifacts", "edges", "expected_artifact_ids", "hash_recipes",
    "view", "source_geometry_replayed", "context_packet_population_complete", *FALSE_FLAGS,
}
SUBJECT_FIELDS = {
    "schema", "graph_id", "graph_sha256", "ast_sha256", "scope_id", "context_slot_ids",
    "dependency_manifest_sha256", "required_dependency_ids", "dependency_artifacts",
    "graph_declared_dependency_refs", "native_binding",
}
HASH_RECIPES = {
    "candidate_request_report_html_context_input": "SHA256 of independently supplied exact bytes",
    "extracted_text": "SHA256 of exact extracted document_text encoded as UTF8",
    "sealed_companion_graph": "SHA256 of canonical DAG JSON including record_cid and cid_scope",
    "native_ast": "SHA256 of canonical DAG JSON of the intact native AST",
    "review_subject_claim_population": "existing review digest over sorted compact UTF8 JSON",
    "dependency_manifest": "existing legal_graph_dependencies manifest_sha256 recipe",
}


def _fail(message):
    raise contracts.CorpusContractError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return _sha(canonical_dag_json_bytes(value))


def _owners():
    from . import legal_graph_dependencies, legal_graph_review, legal_statutory_context

    return legal_graph_dependencies, legal_graph_review, legal_statutory_context


def _pins(owners):
    modules = (contracts, adapter, corpus_graph, corpus_source, cid_utils, *owners)
    paths = [Path(__file__).resolve(), *(Path(module.__file__).resolve() for module in modules)]
    # The existing verifier imports this relative source only when assessing a
    # signature. Pin its bytes without importing or instantiating any signer.
    paths.append(Path(owners[1].__file__).resolve().parent.parent / "profile_g.py")
    return {str(path): _sha(path.read_bytes()) for path in paths}


def _inputs(candidate_inputs, expected_candidate_pin, context_inputs, expected_context_population):
    contracts.require_keys(candidate_inputs, INPUT_FIELDS, "candidate byte inputs")
    pins = contracts.clone_json(expected_candidate_pin)
    contracts.require_keys(pins, POPULATION_FIELDS, "independent candidate pins")
    for field in POPULATION_FIELDS - {"candidate_cid", "graph_cid"}:
        contracts.require_sha256(pins[field], field)
    for field in ("candidate_cid", "graph_cid"):
        contracts.require_cid(pins[field], field, codecs=("dag-json",))
    total = 0
    for field, raw in candidate_inputs.items():
        maximum = adapter.MAX_RAW_HTML_BYTES if field == "raw_html" else contracts.MAX_RECORD_BYTES
        if type(raw) is not bytes or not 1 <= len(raw) <= maximum:
            _fail("bounded nonempty candidate bytes required")
        total += len(raw)
    if (type(context_inputs) is not list or type(expected_context_population) is not list
            or not 1 <= len(context_inputs) <= MAX_CONTEXT_OCCURRENCES
            or len(context_inputs) != len(expected_context_population)):
        _fail("complete ordered source-occurrence context population required")
    population = contracts.clone_json(expected_context_population)
    for inputs, pin in zip(context_inputs, population, strict=True):
        contracts.require_keys(inputs, CONTEXT_INPUT_FIELDS, "context byte inputs")
        contracts.require_keys(pin, CONTEXT_POPULATION_FIELDS, "independent context pins")
        contracts.require_cid(inputs["source_occurrence_cid"], "context source occurrence", codecs=("dag-json",))
        contracts.require_cid(pin["source_occurrence_cid"], "expected context source occurrence", codecs=("dag-json",))
        contracts.require_sha256(pin["packet_sha256"], "packet_sha256")
        if inputs["source_occurrence_cid"] != pin["source_occurrence_cid"]:
            _fail("context occurrence differs from independent population")
        raw = inputs["packet_raw"]
        if type(raw) is not bytes or not 1 <= len(raw) <= contracts.MAX_RECORD_BYTES:
            _fail("bounded nonempty context packet bytes required")
        total += len(raw)
    if total > MAX_INPUT_BYTES:
        _fail("aggregate input byte bound exceeded; no evidence may be omitted")
    return pins, population


def _artifact_inventory(candidate, pins, contexts, producer_pins, native_producer_pins, dependencies):
    artifacts, seen = [], set()

    def add(identity, sha256, *, policy_pins=()):
        if identity in seen:
            _fail("duplicate native review artifact identity")
        seen.add(identity)
        dependency_pins = {kind: [] for kind in dependencies.PIN_KINDS}
        dependency_pins["policy"] = list(policy_pins)
        artifacts.append({"artifact_id": identity, "artifact_sha256": sha256,
                          "dependency_pins": dependency_pins})

    graph = candidate["graph"]
    policy_pins = [
        {"key": prefix + path, "sha256": sha256}
        for prefix, values in (("review-producer:", producer_pins), ("native-producer:", native_producer_pins))
        for path, sha256 in sorted(values.items())
    ]
    add(graph["record_cid"], _digest(graph), policy_pins=policy_pins)
    add(candidate["record_cid"], pins["candidate_sha256"])
    for kind, field in (("request", "request_sha256"), ("report", "report_sha256"),
                        ("raw-html", "raw_sha256"), ("extracted-text", "extracted_sha256")):
        add(f"native-definition-review-input:{kind}:sha256:{pins[field]}", pins[field])
    for field in COMPANIONS:
        record = candidate[field]
        add(record["record_cid"], _digest(record))
    for record in (*candidate["source_occurrences"], *candidate["issues"]):
        add(record["record_cid"], _digest(record))
    for row in contexts:
        add("native-definition-review-context:" + row["source_occurrence_cid"], row["packet_sha256"])
    identities = [row["artifact_id"] for row in artifacts]
    edges = [{"dependent_id": identities[0], "dependency_id": identity} for identity in identities[1:]]
    # Reuse the actual owner to enforce all population, pin and edge bounds.
    dependencies.build_dependency_manifest(artifacts, edges, expected_artifact_ids=identities)
    return artifacts, edges, identities


def prepare_definition_review_evidence(candidate_inputs, *, expected_candidate_pin,
                                       context_inputs, expected_context_population):
    """Regenerate one complete typed candidate and all its occurrence contexts.

    Raw SHA namespaces retain original serialization; canonical companion and
    AST hashes are separately labelled. The caller supplies every independent
    pin and explicit context request. No lookup result invents semantic edges.
    """
    pins, population = _inputs(candidate_inputs, expected_candidate_pin,
                               context_inputs, expected_context_population)
    # Check every supplied raw hash before parsing or importing operation owners.
    for field, pin_field in (("candidate_raw", "candidate_sha256"), ("report_raw", "report_sha256"),
                             ("request_raw", "request_sha256"), ("raw_html", "raw_sha256")):
        if _sha(candidate_inputs[field]) != pins[pin_field]:
            _fail("candidate input differs from independently expected SHA256")
    for inputs, pin in zip(context_inputs, population, strict=True):
        if _sha(inputs["packet_raw"]) != pin["packet_sha256"]:
            _fail("context input differs from independently expected SHA256")
    owners = _owners()
    dependencies, _, contexts_owner = owners
    producer_pins = _pins(owners)
    candidate = contracts.load_record_bytes(candidate_inputs["candidate_raw"], expected_sha256=pins["candidate_sha256"])
    candidate = adapter.validate_definition_norm_candidate(
        candidate, candidate_inputs["report_raw"], expected_report_sha256=pins["report_sha256"],
        request_raw=candidate_inputs["request_raw"], expected_request_sha256=pins["request_sha256"],
        raw_html=candidate_inputs["raw_html"], expected_raw_sha256=pins["raw_sha256"],
        expected_extracted_sha256=pins["extracted_sha256"],
    )
    if candidate["record_cid"] != pins["candidate_cid"] or candidate["graph"]["record_cid"] != pins["graph_cid"]:
        _fail("candidate or graph differs from independently expected identity")
    occurrences = candidate["source_occurrences"]
    expected_ids = [row["record_cid"] for row in occurrences]
    if ([row["source_occurrence_cid"] for row in population] != expected_ids
            or len(set(expected_ids)) != len(expected_ids)):
        _fail("context population differs from every unique candidate source occurrence in order")
    request = contracts.load_record_bytes(candidate_inputs["request_raw"], expected_sha256=pins["request_sha256"])
    report = contracts.load_record_bytes(candidate_inputs["report_raw"], expected_sha256=pins["report_sha256"])
    document, raw_html = request["definition_request"]["document"], candidate_inputs["raw_html"]
    contexts, slots = [], []
    for occurrence, inputs, pin in zip(occurrences, context_inputs, population, strict=True):
        packet = contracts.load_record_bytes(inputs["packet_raw"], expected_sha256=pin["packet_sha256"])
        requests = contracts.clone_json(inputs["dependency_requests"])
        try:
            selector = contexts_owner.source_selector(document, raw_html,
                char_start=occurrence["start_char"], char_end=occurrence["end_char"])
            contexts_owner.validate_context_packet(packet, document, raw_html,
                expected_selector=selector, dependency_requests=requests)
        except (ValueError, TypeError, KeyError, IndexError, UnicodeError, RecursionError) as error:
            raise contracts.CorpusContractError("context packet failed exact source occurrence regeneration") from error
        contexts.append({"source_occurrence_cid": occurrence["record_cid"],
            "packet_sha256": pin["packet_sha256"], "packet_canonical_sha256": _digest(packet),
            "packet_id": packet["packet_id"], "selector": selector,
            "dependency_requests": requests, "dependency_slots": packet["dependency_slots"]})
        slots.extend(row["slot_id"] for row in packet["dependency_slots"])
    if (len(slots) != len(occurrences) * len(contexts_owner.DEPENDENCY_KINDS)
            or len(slots) > MAX_CONTEXT_OBLIGATIONS or len(set(slots)) != len(slots)):
        _fail("complete distinct context obligation population exceeds profile or differs")
    native_producer_pins = report["producer_pins"]
    artifacts, edges, identities = _artifact_inventory(candidate, pins, contexts, producer_pins,
                                                       native_producer_pins, dependencies)
    if _pins(owners) != producer_pins:
        _fail("native review producers changed during evidence preparation")
    ast = candidate["ast_record"]
    return contracts.seal_record({
        "schema": PREPARATION_SCHEMA, "review_profile": PROFILE,
        "profile": candidate["profile"], "family": candidate["family"], "candidate_pin": pins,
        "graph_id": candidate["graph"]["record_cid"], "graph_sha256": _digest(candidate["graph"]),
        "ast_sha256": _digest(ast["native_ast"]), "scope_id": candidate["scope_record"]["record_cid"],
        "scope_key": candidate["scope_record"]["scope_key"],
        "companion_cids": {**{field: candidate[field]["record_cid"] for field in COMPANIONS},
                           "issues": [row["record_cid"] for row in candidate["issues"]]},
        "source_version": candidate["source_version"], "source_occurrences": occurrences,
        "source_bindings": candidate["source_bindings"], "native_ast": ast["native_ast"],
        "bound_definition_native_ast": ast["bound_definition_native_ast"], "norm_native_ast": ast["norm_native_ast"],
        "native_ast_sha256s": {field: _digest(ast[field]) for field in
                              ("native_ast", "bound_definition_native_ast", "norm_native_ast")},
        "contexts": contexts, "context_slot_ids": slots, "expected_context_population": population,
        "producer_pins": producer_pins, "native_producer_pins": native_producer_pins,
        "artifacts": artifacts, "edges": edges, "expected_artifact_ids": identities,
        "hash_recipes": HASH_RECIPES, "view": "candidate", "source_geometry_replayed": True,
        "context_packet_population_complete": True, **FALSE_FLAGS,
    })


def validate_definition_review_evidence(preparation, *, candidate_inputs, expected_candidate_pin,
                                        context_inputs, expected_context_population):
    """Replay the complete evidence; a repaired seal cannot substitute meaning."""
    checked = contracts.validate_record(preparation, schema=PREPARATION_SCHEMA, fields=FIELDS)
    expected = prepare_definition_review_evidence(candidate_inputs, expected_candidate_pin=expected_candidate_pin,
        context_inputs=context_inputs, expected_context_population=expected_context_population)
    if checked != expected:
        _fail("native review evidence differs from independent regeneration")
    return checked


def _manifest_binding(preparation, manifest, required_dependency_ids, reviews):
    reachable, artifacts = reviews._closure(manifest, preparation["graph_id"], preparation["graph_sha256"])
    if type(required_dependency_ids) is not list or reviews.wire(required_dependency_ids) != reviews.wire(reachable):
        _fail("independent required dependency population differs")
    by_id = {row["artifact_id"]: row for row in manifest["artifacts"]}
    for required in preparation["artifacts"]:
        if by_id.get(required["artifact_id"]) != required or required["artifact_id"] not in reachable:
            _fail("native required artifact or producer pins omitted, changed or unreachable")
    edges = {(row["dependent_id"], row["dependency_id"]) for row in manifest["edges"]}
    if any((row["dependent_id"], row["dependency_id"]) not in edges for row in preparation["edges"]):
        _fail("native required graph dependency edge omitted")
    declared_refs = [{"origin": "/native_binding/artifacts/" + str(index), "reference": {
        "artifact_id": row["artifact_id"], "artifact_sha256": row["artifact_sha256"],
        "role": "typed-native-definition-review-evidence"}}
        for index, row in enumerate(preparation["artifacts"][1:], 1)]
    reviews._check_declared_dependencies(declared_refs, reachable, artifacts)
    return reachable, artifacts, declared_refs


def _subject(subject, manifest):
    """Private structural check after the public wrapper's source regeneration."""
    contracts.require_keys(subject, SUBJECT_FIELDS, "typed native review subject")
    if subject["schema"] != SUBJECT_SCHEMA:
        _fail("distinct typed native review subject schema required")
    preparation = contracts.validate_record(subject["native_binding"], schema=PREPARATION_SCHEMA, fields=FIELDS)
    for field in ("graph_id", "graph_sha256", "ast_sha256", "scope_id", "context_slot_ids"):
        if subject[field] != preparation[field]:
            _fail("typed native subject binding differs from complete evidence preparation")
    _, reviews, _ = _owners()
    reachable, artifacts, refs = _manifest_binding(preparation, manifest, subject["required_dependency_ids"], reviews)
    if (subject["dependency_artifacts"] != artifacts or subject["graph_declared_dependency_refs"] != refs
            or subject["dependency_manifest_sha256"] != manifest["manifest_sha256"]):
        _fail("typed native subject dependency binding differs")
    if not reachable:
        _fail("typed native dependency closure must contain its graph")


def build_definition_review_subject(preparation, dependency_manifest, *, candidate_inputs,
        expected_candidate_pin, context_inputs, expected_context_population,
        expected_manifest_sha256, required_dependency_ids):
    """Bind a complete native evidence preparation to a declared dependency generation."""
    checked = validate_definition_review_evidence(preparation, candidate_inputs=candidate_inputs,
        expected_candidate_pin=expected_candidate_pin, context_inputs=context_inputs,
        expected_context_population=expected_context_population)
    dependencies, reviews, _ = _owners()
    manifest = dependencies.validate_dependency_manifest(dependency_manifest,
        expected_manifest_sha256=expected_manifest_sha256)
    reachable, artifacts, refs = _manifest_binding(checked, manifest, required_dependency_ids, reviews)
    subject = {"schema": SUBJECT_SCHEMA,
        **{field: checked[field] for field in ("graph_id", "graph_sha256", "ast_sha256", "scope_id", "context_slot_ids")},
        "dependency_manifest_sha256": expected_manifest_sha256, "required_dependency_ids": reachable,
        "dependency_artifacts": artifacts, "graph_declared_dependency_refs": refs, "native_binding": checked}
    _subject(subject, manifest)
    return contracts.clone_json(subject)


def assess_definition_reviews(subject, registry, policy, reviews, dependency_manifest, *,
        candidate_inputs, expected_candidate_pin, context_inputs, expected_context_population,
        expected_subject_sha256, expected_registry_sha256, expected_policy_sha256,
        expected_reviews_sha256, expected_manifest_sha256, at_time_utc,
        observed_artifact_sha256s, observed_pins, evidence_artifacts):
    """Replay native custody, then delegate authentication without admission."""
    owners = _owners()
    producer_pins = _pins(owners)
    checked = contracts.clone_json(subject)
    contracts.require_keys(checked, SUBJECT_FIELDS, "typed native review subject")
    expected = build_definition_review_subject(checked["native_binding"], dependency_manifest,
        candidate_inputs=candidate_inputs, expected_candidate_pin=expected_candidate_pin,
        context_inputs=context_inputs, expected_context_population=expected_context_population,
        expected_manifest_sha256=expected_manifest_sha256,
        required_dependency_ids=checked["required_dependency_ids"])
    if checked != expected:
        _fail("typed native review subject differs from independent regeneration")
    if (checked["native_binding"]["producer_pins"] != producer_pins
            or _pins(owners) != producer_pins):
        _fail("native review producers changed before authentication")
    _, owner, _ = owners
    domain = owner._ReviewDomain(SUBJECT_SCHEMA, CLAIM_SCHEMA, ACTION, AUDIENCE, SCHEMA,
                                 _subject, MAX_CONTEXT_OBLIGATIONS)
    result = owner._assess_reviews(checked, registry, policy, reviews, dependency_manifest, domain=domain,
        expected_subject_sha256=expected_subject_sha256, expected_registry_sha256=expected_registry_sha256,
        expected_policy_sha256=expected_policy_sha256, expected_reviews_sha256=expected_reviews_sha256,
        expected_manifest_sha256=expected_manifest_sha256, at_time_utc=at_time_utc,
        observed_artifact_sha256s=observed_artifact_sha256s, observed_pins=observed_pins,
        evidence_artifacts=evidence_artifacts)
    preparation = checked["native_binding"]
    pins, companions = preparation["candidate_pin"], preparation["companion_cids"]
    body = {key: value for key, value in result.items() if key != "assessment_sha256"}
    body.update({
        "review_profile": PROFILE, "native_profile": preparation["profile"],
        "native_family": preparation["family"], "candidate_cid": pins["candidate_cid"],
        "candidate_sha256": pins["candidate_sha256"], "graph_cid": pins["graph_cid"],
        "preparation_cid": preparation["record_cid"],
        **{field + "_cid": companions[field] for field in
           ("source_version", "definition_record", "norm_record", "ast_record")},
        "original_input_sha256s": {field: pins[field] for field in
                                  ("candidate_sha256", "request_sha256", "report_sha256",
                                   "raw_sha256", "extracted_sha256")},
        "context_population_sha256": _digest(preparation["expected_context_population"]),
        "signature_owner_source_pinned": True,
        "cryptographic_distribution_authenticated": False, **FALSE_FLAGS,
    })
    report = {**body, "assessment_sha256": owner.digest(body)}
    owner.wire(report)
    if _pins(owners) != producer_pins:
        _fail("native review producers changed during authentication")
    return report


def validate_definition_review_assessment(report, *args, **kwargs):
    """Regenerate the complete native assessment under all independent inputs."""
    expected = assess_definition_reviews(*args, **kwargs)
    _, owner, _ = _owners()
    if owner.wire(report) != owner.wire(expected):
        _fail("typed native review assessment differs from exact regeneration")
    return expected


__all__ = [
    "prepare_definition_review_evidence", "validate_definition_review_evidence",
    "build_definition_review_subject", "assess_definition_reviews",
    "validate_definition_review_assessment",
]
