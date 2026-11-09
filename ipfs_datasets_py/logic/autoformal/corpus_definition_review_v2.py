"""Complete V2 definition-only review custody using the existing verifier.

Source geometry, original byte commitments and a fixed signing domain are
replayed before authentication. No signer, registry, clock or network default is
provided. Authentication supplies evidence under selected keys, not legal truth
or semantic, training or Lean admission. Public import loads no operation owner.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ipfs_datasets_py.utils import cid_utils
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

from . import corpus_contracts as contracts
from . import corpus_definition_adapter_v2 as adapter
from . import corpus_graph, corpus_source

PREPARATION_SCHEMA = "legal-corpus-v2-definition-review-evidence/v1"
SUBJECT_SCHEMA = "legal-corpus-v2-definition-review-subject/v1"
CLAIM_SCHEMA = "legal-corpus-v2-definition-review-signed-claim/v1"
ACTION = "record_v2_definition_review_evidence/v1"
AUDIENCE = "legal-autoformalization-v2-definition-review/v1"
SCHEMA = "legal-corpus-v2-definition-review-assessment/v1"
PROFILE = "complete-v2-occurrence-typed-definition-only-review/v1"
MAX_CONTEXT_OCCURRENCES = 256
MAX_CONTEXT_OBLIGATIONS = 1536
MAX_SAMPLING_BYTES = 32 * 1024**2
MAX_RAW_BYTES = 8_000_000
MAX_INPUT_BYTES = 48 * 1024**2
INPUT_FIELDS = {
    "candidate_raw",
    "report_raw",
    "request_raw",
    "raw_html",
    "sampling_report_raw",
    "descriptor_raw",
}
POPULATION_FIELDS = {
    "candidate_sha256",
    "candidate_cid",
    "graph_cid",
    "request_sha256",
    "report_sha256",
    "raw_sha256",
    "raw_bytes",
    "extracted_sha256",
    "sampling_report_sha256",
    "sampling_report_full_canonical_sha256",
    "descriptor_sha256",
    "descriptor_full_canonical_sha256",
}
CONTEXT_INPUT_FIELDS = {"source_occurrence_cid", "packet_raw", "dependency_requests"}
CONTEXT_POPULATION_FIELDS = {"source_occurrence_cid", "packet_sha256"}
COMPANIONS = (
    "request_record",
    "report_record",
    "source_version",
    "scope_record",
    "symbol_record",
    "definition_record",
    "ast_record",
    "term_record",
    "input_binding",
)
FALSE_FLAGS = dict.fromkeys(
    (
        "source_semantics_verified",
        "source_authenticity_verified",
        "context_closure_verified",
        "applicability_semantics_verified",
        "independently_reviewed",
        "admitted",
        "formalized",
        "proof_authority",
        "training_qualified",
        "training_gold_qualified",
        "backend_executed",
        "lean_compilation_verified",
        "human_identity_verified",
        "human_independence_verified",
        "external_definition_resolution_verified",
        "legal_dependency_inventory_exhaustive",
    ),
    False,
)
FIELDS = {
    "review_profile",
    "profile",
    "family",
    "candidate_pin",
    "graph_id",
    "graph_sha256",
    "ast_sha256",
    "scope_id",
    "scope_key",
    "companion_cids",
    "source_version",
    "source_occurrences",
    "source_bindings",
    "native_ast",
    "contexts",
    "context_slot_ids",
    "expected_context_population",
    "producer_pins",
    "native_producer_pins",
    "artifacts",
    "edges",
    "expected_artifact_ids",
    "hash_recipes",
    "view",
    "source_geometry_replayed",
    "context_packet_population_complete",
    *FALSE_FLAGS,
}
SUBJECT_FIELDS = {
    "schema",
    "graph_id",
    "graph_sha256",
    "ast_sha256",
    "scope_id",
    "context_slot_ids",
    "dependency_manifest_sha256",
    "required_dependency_ids",
    "dependency_artifacts",
    "graph_declared_dependency_refs",
    "native_binding",
}
HASH_RECIPES = {
    "original_inputs_and_context_packets": "SHA256 of independently pinned exact original bytes",
    "sampling_report_and_descriptor_full_canonical": "SHA256 of complete canonical JSON including internal digests",
    "sealed_companion_graph_and_native_AST": "SHA256 of canonical DAG JSON; record envelopes include record_cid/cid_scope",
    "review_subject_claim_population": "existing verifier sorted compact UTF8 JSON digest",
    "dependency_manifest": "existing legal_graph_dependencies manifest_sha256 recipe",
}


def _fail(message):
    raise contracts.CorpusContractError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return _sha(canonical_dag_json_bytes(value))


def _pure_pins():
    return {
        str(path): _sha(path.read_bytes())
        for path in (
            Path(__file__).resolve(),
            *(
                Path(module.__file__).resolve()
                for module in (
                    contracts,
                    adapter,
                    corpus_graph,
                    corpus_source,
                    cid_utils,
                )
            ),
        )
    }


_IMPORTED_PURE_PINS = _pure_pins()
_OPERATION_PINS = None


def _owners():
    from . import (
        legal_graph_dependencies,
        legal_graph_review,
        legal_statutory_context_v2,
    )

    return legal_graph_dependencies, legal_graph_review, legal_statutory_context_v2


def _pins(owners):
    global _OPERATION_PINS
    result = _pure_pins()
    if result != _IMPORTED_PURE_PINS:
        _fail("V2 review pure owners changed since import")
    extra = {
        str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
        for module in owners
    }
    extra.update(owners[2].producer_pins())
    signature_owner = Path(owners[1].__file__).resolve().parent.parent / "profile_g.py"
    extra[str(signature_owner)] = _sha(signature_owner.read_bytes())
    if _OPERATION_PINS is None:
        _OPERATION_PINS = dict(extra)
    elif extra != _OPERATION_PINS:
        _fail("V2 review operation owners changed since first use")
    return result | extra


def _inputs(
    candidate_inputs,
    expected_candidate_pin,
    context_inputs,
    expected_context_population,
):
    contracts.require_keys(candidate_inputs, INPUT_FIELDS, "V2 original byte inputs")
    pins = contracts.clone_json(expected_candidate_pin)
    contracts.require_keys(pins, POPULATION_FIELDS, "independent V2 candidate pins")
    for field in POPULATION_FIELDS - {"candidate_cid", "graph_cid", "raw_bytes"}:
        contracts.require_sha256(pins[field], field)
    for field in ("candidate_cid", "graph_cid"):
        contracts.require_cid(pins[field], field, codecs=("dag-json",))
    contracts.require_int(
        pins["raw_bytes"],
        "independent raw byte length",
        minimum=1,
        maximum=MAX_RAW_BYTES,
    )
    total = 0
    for field, raw in candidate_inputs.items():
        maximum = (
            MAX_SAMPLING_BYTES
            if field == "sampling_report_raw"
            else (MAX_RAW_BYTES if field == "raw_html" else contracts.MAX_RECORD_BYTES)
        )
        if type(raw) is not bytes or not 1 <= len(raw) <= maximum:
            _fail("bounded nonempty V2 original bytes required")
        total += len(raw)
    if len(candidate_inputs["raw_html"]) != pins["raw_bytes"]:
        _fail("raw HTML length differs from independent commitment")
    if (
        type(context_inputs) is not list
        or type(expected_context_population) is not list
        or not 1 <= len(context_inputs) <= MAX_CONTEXT_OCCURRENCES
        or len(context_inputs) != len(expected_context_population)
    ):
        _fail("complete ordered V2 physical-occurrence context population required")
    population = contracts.clone_json(expected_context_population)
    for inputs, pin in zip(context_inputs, population, strict=True):
        contracts.require_keys(inputs, CONTEXT_INPUT_FIELDS, "V2 context byte inputs")
        contracts.require_keys(
            pin, CONTEXT_POPULATION_FIELDS, "independent V2 context pin"
        )
        for value in (inputs["source_occurrence_cid"], pin["source_occurrence_cid"]):
            contracts.require_cid(value, "V2 physical occurrence", codecs=("dag-json",))
        contracts.require_sha256(
            pin["packet_sha256"], "context packet transport SHA256"
        )
        if inputs["source_occurrence_cid"] != pin["source_occurrence_cid"]:
            _fail("V2 context occurrence differs from independent population")
        raw = inputs["packet_raw"]
        if type(raw) is not bytes or not 1 <= len(raw) <= contracts.MAX_RECORD_BYTES:
            _fail("bounded nonempty V2 context packet bytes required")
        requests = contracts.clone_json(inputs["dependency_requests"])
        total += len(raw) + len(canonical_dag_json_bytes(requests))
    if total > MAX_INPUT_BYTES:
        _fail("aggregate V2 original input byte bound exceeded; truncation refused")
    return pins, population


def _large_source_json(raw, expected_sha256):
    """Load a separately bounded complete sampler transport, never a sealed row."""
    if (
        type(raw) is not bytes
        or not 1 <= len(raw) <= MAX_SAMPLING_BYTES
        or _sha(raw) != expected_sha256
    ):
        _fail("complete sampling transport differs from independent bound/hash")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                _fail("duplicate complete sampling JSON key")
            result[key] = value
        return result

    def constant(_):
        _fail("finite complete sampling JSON required")

    try:
        result = json.loads(
            raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=constant
        )
    except (ValueError, UnicodeError, RecursionError) as error:
        raise contracts.CorpusContractError(
            "bounded complete sampling JSON required"
        ) from error
    if type(result) is not dict:
        _fail("complete sampling JSON object required")
    return result


def _artifact_inventory(
    candidate, pins, contexts, producer_pins, native_pins, dependencies
):
    artifacts, seen = [], set()

    def add(identity, sha256, policy_pins=()):
        if identity in seen:
            _fail("duplicate V2 review dependency identity")
        seen.add(identity)
        policy = {kind: [] for kind in dependencies.PIN_KINDS}
        policy["policy"] = list(policy_pins)
        artifacts.append(
            {
                "artifact_id": identity,
                "artifact_sha256": sha256,
                "dependency_pins": policy,
            }
        )

    policy_pins = [
        {"key": prefix + path, "sha256": value}
        for prefix, source in (
            ("v2-review:", producer_pins),
            ("native-definition:", native_pins),
        )
        for path, value in sorted(source.items())
    ]
    add(candidate["graph"]["record_cid"], _digest(candidate["graph"]), policy_pins)
    add(candidate["record_cid"], pins["candidate_sha256"])
    for label, field in (
        ("request-bytes", "request_sha256"),
        ("report-bytes", "report_sha256"),
        ("raw-html", "raw_sha256"),
        ("extracted-text", "extracted_sha256"),
        ("sampling-bytes", "sampling_report_sha256"),
        ("sampling-canonical", "sampling_report_full_canonical_sha256"),
        ("descriptor-bytes", "descriptor_sha256"),
        ("descriptor-canonical", "descriptor_full_canonical_sha256"),
    ):
        add(
            "v2-definition-review-input:" + label + ":sha256:" + pins[field],
            pins[field],
        )
    for field in COMPANIONS:
        record = candidate[field]
        add(record["record_cid"], _digest(record))
    for record in (
        *candidate["source_occurrences"],
        *candidate["context_declarations"],
        *candidate["issues"],
    ):
        add(record["record_cid"], _digest(record))
    for row in contexts:
        add(
            "v2-definition-review-context:" + row["source_occurrence_cid"],
            row["packet_sha256"],
        )
    identities = [row["artifact_id"] for row in artifacts]
    edges = [
        {"dependent_id": identities[0], "dependency_id": identity}
        for identity in identities[1:]
    ]
    dependencies.build_dependency_manifest(
        artifacts, edges, expected_artifact_ids=identities
    )
    return artifacts, edges, identities


def _preflight(
    candidate_inputs,
    expected_candidate_pin,
    context_inputs,
    expected_context_population,
):
    pins, population = _inputs(
        candidate_inputs,
        expected_candidate_pin,
        context_inputs,
        expected_context_population,
    )
    for field, pin_field in (
        ("candidate_raw", "candidate_sha256"),
        ("report_raw", "report_sha256"),
        ("request_raw", "request_sha256"),
        ("raw_html", "raw_sha256"),
        ("sampling_report_raw", "sampling_report_sha256"),
        ("descriptor_raw", "descriptor_sha256"),
    ):
        if _sha(candidate_inputs[field]) != pins[pin_field]:
            _fail(
                "V2 original input differs from independently expected transport SHA256"
            )
    for inputs, pin in zip(context_inputs, population, strict=True):
        if _sha(inputs["packet_raw"]) != pin["packet_sha256"]:
            _fail("V2 context differs from independently expected transport SHA256")
    if _pure_pins() != _IMPORTED_PURE_PINS:
        _fail("V2 review pure owners changed since import")
    return pins, population


def prepare_definition_review_evidence_v2(
    candidate_inputs,
    *,
    expected_candidate_pin,
    context_inputs,
    expected_context_population,
):
    """Replay the complete V2 candidate and each distinct physical context."""
    pins, population = _preflight(
        candidate_inputs,
        expected_candidate_pin,
        context_inputs,
        expected_context_population,
    )
    candidate = contracts.load_record_bytes(
        candidate_inputs["candidate_raw"], expected_sha256=pins["candidate_sha256"]
    )
    sampling = _large_source_json(
        candidate_inputs["sampling_report_raw"], pins["sampling_report_sha256"]
    )
    descriptor = contracts.load_record_bytes(
        candidate_inputs["descriptor_raw"], expected_sha256=pins["descriptor_sha256"]
    )
    report = contracts.load_record_bytes(
        candidate_inputs["report_raw"], expected_sha256=pins["report_sha256"]
    )
    try:
        view_limits = sampling["document_view_report"]["limits"]
        sampling_limits = sampling["limits"]
        compiler_limits = report["limits"]
    except (KeyError, TypeError) as error:
        raise contracts.CorpusContractError(
            "original V2 source/compiler limit declarations required"
        ) from error
    candidate = adapter.validate_definition_only_candidate_v2(
        candidate,
        candidate_inputs["report_raw"],
        expected_report_sha256=pins["report_sha256"],
        request_raw=candidate_inputs["request_raw"],
        expected_request_sha256=pins["request_sha256"],
        sampling_report=sampling,
        expected_sampling_report_sha256=pins["sampling_report_full_canonical_sha256"],
        raw_html=candidate_inputs["raw_html"],
        descriptor=descriptor,
        expected_descriptor_sha256=pins["descriptor_full_canonical_sha256"],
        expected_raw_sha256=pins["raw_sha256"],
        expected_raw_bytes=pins["raw_bytes"],
        view_limits=view_limits,
        sampling_limits=sampling_limits,
        limits=compiler_limits,
    )
    if (
        candidate["record_cid"] != pins["candidate_cid"]
        or candidate["graph"]["record_cid"] != pins["graph_cid"]
        or candidate["source_version"]["extracted_view"]["sha256"]
        != pins["extracted_sha256"]
    ):
        _fail("V2 candidate, graph or extracted view differs from independent identity")
    occurrences = candidate["source_occurrences"]
    identities = [row["record_cid"] for row in occurrences]
    if [row["source_occurrence_cid"] for row in population] != identities or len(
        set(identities)
    ) != len(identities):
        _fail(
            "V2 context population must cover every unique source occurrence in order"
        )
    owners = _owners()
    dependencies, _, context_owner = owners
    producers = _pins(owners)
    view_report = sampling["document_view_report"]
    trusted = {
        "expected_report_sha256": sampling["document_view_report_sha256"],
        "descriptor": descriptor,
        "expected_descriptor_sha256": pins["descriptor_full_canonical_sha256"],
        "expected_raw_sha256": pins["raw_sha256"],
        "expected_raw_bytes": pins["raw_bytes"],
        "limits": view_limits,
    }
    contexts, slots = [], []
    for occurrence, inputs, pin in zip(
        occurrences, context_inputs, population, strict=True
    ):
        packet = contracts.load_record_bytes(
            inputs["packet_raw"], expected_sha256=pin["packet_sha256"]
        )
        requests = contracts.clone_json(inputs["dependency_requests"])
        try:
            selection = context_owner.source_selector_v2(
                view_report,
                candidate_inputs["raw_html"],
                char_start=occurrence["start_char"],
                char_end=occurrence["end_char"],
                **trusted,
            )
            if (
                selection["utf8_byte_start"] != occurrence["start_utf8"]
                or selection["utf8_byte_end"] != occurrence["end_utf8"]
                or selection["text"] != occurrence["span_text"]
            ):
                _fail("V2 physical occurrence and selector geometry differ")
            context_owner.validate_context_packet_v2(
                packet,
                view_report,
                candidate_inputs["raw_html"],
                expected_selector=selection,
                dependency_requests=requests,
                **trusted,
            )
        except (
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            UnicodeError,
            RecursionError,
        ) as error:
            raise contracts.CorpusContractError(
                "V2 context packet failed exact occurrence regeneration"
            ) from error
        contexts.append(
            {
                "source_occurrence_cid": occurrence["record_cid"],
                "packet_sha256": pin["packet_sha256"],
                "packet_canonical_sha256": _digest(packet),
                "packet_id": packet["packet_id"],
                "selector": selection,
                "source_view_binding": packet["source_view_binding"],
                "dependency_requests": requests,
                "dependency_slots": packet["dependency_slots"],
            }
        )
        slots.extend(row["slot_id"] for row in packet["dependency_slots"])
    if (
        len(slots) != len(occurrences) * len(context_owner.DEPENDENCY_KINDS)
        or len(slots) > MAX_CONTEXT_OBLIGATIONS
        or len(set(slots)) != len(slots)
    ):
        _fail(
            "complete distinct V2 context obligation population differs or exceeds profile"
        )
    artifacts, edges, artifact_ids = _artifact_inventory(
        candidate, pins, contexts, producers, report["producer_pins"], dependencies
    )
    if _pins(owners) != producers:
        _fail("V2 review owners changed during preparation")
    return contracts.seal_record(
        {
            "schema": PREPARATION_SCHEMA,
            "review_profile": PROFILE,
            "profile": candidate["profile"],
            "family": candidate["family"],
            "candidate_pin": pins,
            "graph_id": pins["graph_cid"],
            "graph_sha256": _digest(candidate["graph"]),
            "ast_sha256": _digest(candidate["ast_record"]["native_ast"]),
            "scope_id": candidate["scope_record"]["record_cid"],
            "scope_key": candidate["scope_record"]["scope_key"],
            "companion_cids": {
                **{field: candidate[field]["record_cid"] for field in COMPANIONS},
                "context_declarations": [
                    row["record_cid"] for row in candidate["context_declarations"]
                ],
                "issues": [row["record_cid"] for row in candidate["issues"]],
            },
            "source_version": candidate["source_version"],
            "source_occurrences": occurrences,
            "source_bindings": candidate["source_bindings"],
            "native_ast": candidate["ast_record"]["native_ast"],
            "contexts": contexts,
            "context_slot_ids": slots,
            "expected_context_population": population,
            "producer_pins": producers,
            "native_producer_pins": report["producer_pins"],
            "artifacts": artifacts,
            "edges": edges,
            "expected_artifact_ids": artifact_ids,
            "hash_recipes": HASH_RECIPES,
            "view": "candidate",
            "source_geometry_replayed": True,
            "context_packet_population_complete": True,
            **FALSE_FLAGS,
        }
    )


def validate_definition_review_evidence_v2(
    preparation,
    *,
    candidate_inputs,
    expected_candidate_pin,
    context_inputs,
    expected_context_population,
):
    checked = contracts.validate_record(
        preparation, schema=PREPARATION_SCHEMA, fields=FIELDS
    )
    expected = prepare_definition_review_evidence_v2(
        candidate_inputs,
        expected_candidate_pin=expected_candidate_pin,
        context_inputs=context_inputs,
        expected_context_population=expected_context_population,
    )
    if checked != expected:
        _fail("V2 review evidence differs from independent regeneration")
    return checked


def _manifest_binding(preparation, manifest, required_dependency_ids, owner):
    reachable, artifacts = owner._closure(
        manifest, preparation["graph_id"], preparation["graph_sha256"]
    )
    if type(required_dependency_ids) is not list or owner.wire(
        required_dependency_ids
    ) != owner.wire(reachable):
        _fail("independent V2 required dependency population differs")
    by_id = {row["artifact_id"]: row for row in manifest["artifacts"]}
    for row in preparation["artifacts"]:
        if by_id.get(row["artifact_id"]) != row or row["artifact_id"] not in reachable:
            _fail(
                "V2 required artifact or producer pin omitted, changed or unreachable"
            )
    edges = {(row["dependent_id"], row["dependency_id"]) for row in manifest["edges"]}
    if any(
        (row["dependent_id"], row["dependency_id"]) not in edges
        for row in preparation["edges"]
    ):
        _fail("V2 required graph dependency edge omitted")
    refs = [
        {
            "origin": "/native_binding/artifacts/" + str(index),
            "reference": {
                "artifact_id": row["artifact_id"],
                "artifact_sha256": row["artifact_sha256"],
                "role": "complete-v2-definition-review-evidence",
            },
        }
        for index, row in enumerate(preparation["artifacts"][1:], 1)
    ]
    owner._check_declared_dependencies(refs, reachable, artifacts)
    return reachable, artifacts, refs


def _subject(subject, manifest):
    contracts.require_keys(subject, SUBJECT_FIELDS, "V2 definition review subject")
    if subject["schema"] != SUBJECT_SCHEMA:
        _fail("distinct V2 definition-only subject required")
    preparation = contracts.validate_record(
        subject["native_binding"], schema=PREPARATION_SCHEMA, fields=FIELDS
    )
    for field in (
        "graph_id",
        "graph_sha256",
        "ast_sha256",
        "scope_id",
        "context_slot_ids",
    ):
        if subject[field] != preparation[field]:
            _fail("V2 subject differs from complete evidence binding")
    _, owner, _ = _owners()
    reachable, artifacts, refs = _manifest_binding(
        preparation, manifest, subject["required_dependency_ids"], owner
    )
    if (
        not reachable
        or subject["dependency_artifacts"] != artifacts
        or subject["graph_declared_dependency_refs"] != refs
        or subject["dependency_manifest_sha256"] != manifest["manifest_sha256"]
    ):
        _fail("V2 subject dependency binding differs")


def build_definition_review_subject_v2(
    preparation,
    dependency_manifest,
    *,
    candidate_inputs,
    expected_candidate_pin,
    context_inputs,
    expected_context_population,
    expected_manifest_sha256,
    required_dependency_ids,
):
    checked = validate_definition_review_evidence_v2(
        preparation,
        candidate_inputs=candidate_inputs,
        expected_candidate_pin=expected_candidate_pin,
        context_inputs=context_inputs,
        expected_context_population=expected_context_population,
    )
    dependencies, owner, _ = _owners()
    manifest = dependencies.validate_dependency_manifest(
        dependency_manifest, expected_manifest_sha256=expected_manifest_sha256
    )
    reachable, artifacts, refs = _manifest_binding(
        checked, manifest, required_dependency_ids, owner
    )
    subject = {
        "schema": SUBJECT_SCHEMA,
        **{
            field: checked[field]
            for field in (
                "graph_id",
                "graph_sha256",
                "ast_sha256",
                "scope_id",
                "context_slot_ids",
            )
        },
        "dependency_manifest_sha256": expected_manifest_sha256,
        "required_dependency_ids": reachable,
        "dependency_artifacts": artifacts,
        "graph_declared_dependency_refs": refs,
        "native_binding": checked,
    }
    _subject(subject, manifest)
    return contracts.clone_json(subject)


def assess_definition_reviews_v2(
    subject,
    registry,
    policy,
    reviews,
    dependency_manifest,
    *,
    candidate_inputs,
    expected_candidate_pin,
    context_inputs,
    expected_context_population,
    expected_subject_sha256,
    expected_registry_sha256,
    expected_policy_sha256,
    expected_reviews_sha256,
    expected_manifest_sha256,
    at_time_utc,
    observed_artifact_sha256s,
    observed_pins,
    evidence_artifacts,
):
    """Replay the V2 subject, then delegate exact fixed-domain authentication."""
    _preflight(
        candidate_inputs,
        expected_candidate_pin,
        context_inputs,
        expected_context_population,
    )
    owners = _owners()
    producers = _pins(owners)
    checked = contracts.clone_json(subject)
    contracts.require_keys(checked, SUBJECT_FIELDS, "V2 definition review subject")
    expected = build_definition_review_subject_v2(
        checked["native_binding"],
        dependency_manifest,
        candidate_inputs=candidate_inputs,
        expected_candidate_pin=expected_candidate_pin,
        context_inputs=context_inputs,
        expected_context_population=expected_context_population,
        expected_manifest_sha256=expected_manifest_sha256,
        required_dependency_ids=checked["required_dependency_ids"],
    )
    if checked != expected or checked["native_binding"]["producer_pins"] != producers:
        _fail("V2 subject or producer bindings differ from independent regeneration")
    if _pins(owners) != producers:
        _fail("V2 review producers changed before authentication")
    _, owner, _ = owners
    domain = owner._ReviewDomain(
        SUBJECT_SCHEMA,
        CLAIM_SCHEMA,
        ACTION,
        AUDIENCE,
        SCHEMA,
        _subject,
        MAX_CONTEXT_OBLIGATIONS,
    )
    result = owner._assess_reviews(
        checked,
        registry,
        policy,
        reviews,
        dependency_manifest,
        domain=domain,
        expected_subject_sha256=expected_subject_sha256,
        expected_registry_sha256=expected_registry_sha256,
        expected_policy_sha256=expected_policy_sha256,
        expected_reviews_sha256=expected_reviews_sha256,
        expected_manifest_sha256=expected_manifest_sha256,
        at_time_utc=at_time_utc,
        observed_artifact_sha256s=observed_artifact_sha256s,
        observed_pins=observed_pins,
        evidence_artifacts=evidence_artifacts,
    )
    preparation = checked["native_binding"]
    body = {key: value for key, value in result.items() if key != "assessment_sha256"}
    body.update(
        {
            "review_profile": PROFILE,
            "native_profile": preparation["profile"],
            "native_family": preparation["family"],
            "candidate_cid": preparation["candidate_pin"]["candidate_cid"],
            "candidate_sha256": preparation["candidate_pin"]["candidate_sha256"],
            "graph_cid": preparation["candidate_pin"]["graph_cid"],
            "preparation_cid": preparation["record_cid"],
            **{
                field + "_cid": preparation["companion_cids"][field]
                for field in ("source_version", "definition_record", "ast_record")
            },
            "original_input_binding": preparation["candidate_pin"],
            "context_population_sha256": _digest(
                preparation["expected_context_population"]
            ),
            "signature_owner_source_pinned": True,
            "cryptographic_distribution_authenticated": False,
            **FALSE_FLAGS,
        }
    )
    report = {**body, "assessment_sha256": owner.digest(body)}
    owner.wire(report)
    if _pins(owners) != producers:
        _fail("V2 review producers changed during authentication")
    return report


def validate_definition_review_assessment_v2(report, *args, **kwargs):
    expected = assess_definition_reviews_v2(*args, **kwargs)
    _, owner, _ = _owners()
    if owner.wire(report) != owner.wire(expected):
        _fail("V2 review assessment differs from exact regeneration")
    return expected


__all__ = [
    "prepare_definition_review_evidence_v2",
    "validate_definition_review_evidence_v2",
    "build_definition_review_subject_v2",
    "assess_definition_reviews_v2",
    "validate_definition_review_assessment_v2",
]


# A separate fixed domain for complete literal-parent custody. The official V2
# APIs above retain their source transport, schemas and signing domain.
PARENT_PREPARATION_SCHEMA = "legal-corpus-parent-definition-review-evidence/v1"
PARENT_SUBJECT_SCHEMA = "legal-corpus-parent-definition-review-subject/v1"
PARENT_CLAIM_SCHEMA = "legal-corpus-parent-definition-review-signed-claim/v1"
PARENT_ACTION = "record_parent_definition_review_evidence/v1"
PARENT_AUDIENCE = "legal-autoformalization-parent-definition-review/v1"
PARENT_SCHEMA = "legal-corpus-parent-definition-review-assessment/v1"
PARENT_PROFILE = "complete-parent-occurrence-typed-definition-only-review/v1"
PARENT_INPUT_FIELDS = {"candidate_raw", "report_raw", "request_raw"}
PARENT_REPLAY_FIELDS = {
    "parent_bundle", "expected_manifest_cid", "source_occurrence_cid",
    "companion_record_cid", "report_bytes", "expected_report_pins", "replay_inputs",
}
PARENT_POPULATION_FIELDS = {
    "candidate_sha256", "candidate_cid", "graph_cid", "request_sha256",
    "report_sha256", "parent_manifest_cid", "source_binding_sha256",
    "root_source_occurrence_cid", "companion_record_cid", "source_version_cid",
    "extracted_sha256",
}
PARENT_FALSE_FLAGS = {
    **FALSE_FLAGS, "contributor_completeness_verified": False,
    "governing_scope_verified": False, "source_region_roles_verified": False,
}
PARENT_FIELDS = FIELDS | {
    "parent_source_binding", "parent_input_binding", *PARENT_FALSE_FLAGS,
}
PARENT_HASH_RECIPES = {
    "original_inputs_and_context_packets": HASH_RECIPES[
        "original_inputs_and_context_packets"],
    "sealed_companion_graph_and_native_AST": HASH_RECIPES[
        "sealed_companion_graph_and_native_AST"],
    "review_subject_claim_population": HASH_RECIPES["review_subject_claim_population"],
    "dependency_manifest": HASH_RECIPES["dependency_manifest"],
    "parent_transport": "SHA256 of complete bounded canonical parent JSON and exact original report bytes",
    "parent_source_binding": "existing legal_semantic_graph source_binding_sha256 recipe",
}
_PARENT_OPERATION_PINS = None


def _parent_pins(owners):
    global _PARENT_OPERATION_PINS
    result = _pure_pins()
    if result != _IMPORTED_PURE_PINS:
        _fail("parent review pure owners changed since import")
    extra = {
        str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
        for module in owners
    }
    extra.update(owners[2].producer_pins())
    extra.update(owners[2].parent_context_producer_pins())
    from . import corpus_parent_occurrence_adapter as parent
    from . import legal_source_definition_bridge_v2 as definition_owner

    # Reuse each operation's actual source-pin closure, including the complete
    # physical replay chain and native Boolean lowering. Report-supplied hashes
    # alone never establish which implementation is executing this operation.
    extra.update(parent._pins(parent._owners()))
    extra.update(definition_owner.parent_definition_producer_pins())
    signature_owner = Path(owners[1].__file__).resolve().parent.parent / "profile_g.py"
    extra[str(signature_owner)] = _sha(signature_owner.read_bytes())
    if _PARENT_OPERATION_PINS is None:
        _PARENT_OPERATION_PINS = dict(extra)
    elif extra != _PARENT_OPERATION_PINS:
        _fail("parent review operation owners changed since first use")
    return result | extra


def _parent_preflight(candidate_inputs, expected_candidate_pin, parent_inputs,
                      context_inputs, expected_context_population, parent_limits):
    """Bound complete public inputs before any original physical-parent replay."""
    contracts.require_keys(candidate_inputs, PARENT_INPUT_FIELDS, "parent original bytes")
    contracts.require_keys(parent_inputs, PARENT_REPLAY_FIELDS, "parent replay inputs")
    pins = contracts.clone_json(expected_candidate_pin)
    contracts.require_keys(pins, PARENT_POPULATION_FIELDS, "independent parent candidate pins")
    for key, value in pins.items():
        if key.endswith("_cid"):
            contracts.require_cid(value, key, codecs=("dag-json",))
        else:
            contracts.require_sha256(value, key)
    total = 0
    for key in PARENT_INPUT_FIELDS:
        raw = candidate_inputs[key]
        if type(raw) is not bytes or not 0 < len(raw) <= contracts.MAX_RECORD_BYTES:
            _fail("bounded nonempty parent candidate/report/request bytes required")
        if _sha(raw) != pins[key.removesuffix("_raw") + "_sha256"]:
            _fail("parent original bytes differ from independent SHA256")
        total += len(raw)
    if (type(context_inputs) is not list or type(expected_context_population) is not list
            or not 1 <= len(context_inputs) <= MAX_CONTEXT_OCCURRENCES
            or len(context_inputs) != len(expected_context_population)):
        _fail("complete bounded ordered parent context population required")
    population = contracts.clone_json(expected_context_population)
    for inputs, pin in zip(context_inputs, population, strict=True):
        contracts.require_keys(inputs, CONTEXT_INPUT_FIELDS, "parent context byte inputs")
        contracts.require_keys(pin, CONTEXT_POPULATION_FIELDS, "parent context pin")
        contracts.require_cid(pin["source_occurrence_cid"], "parent occurrence", codecs=("dag-json",))
        contracts.require_sha256(pin["packet_sha256"], "parent packet SHA256")
        if inputs["source_occurrence_cid"] != pin["source_occurrence_cid"]:
            _fail("parent context differs from independently pinned occurrence")
        raw = inputs["packet_raw"]
        if type(raw) is not bytes or not 0 < len(raw) <= contracts.MAX_RECORD_BYTES:
            _fail("bounded nonempty parent context packet bytes required")
        if _sha(raw) != pin["packet_sha256"]:
            _fail("parent context differs from independent packet SHA256")
        requests = contracts.clone_json(inputs["dependency_requests"])
        total += len(raw) + len(canonical_dag_json_bytes(requests))
        if total > MAX_INPUT_BYTES:
            _fail("aggregate parent review byte bound exceeded; truncation refused")
    for field, pin in (("expected_manifest_cid", "parent_manifest_cid"),
                       ("source_occurrence_cid", "root_source_occurrence_cid"),
                       ("companion_record_cid", "companion_record_cid")):
        if parent_inputs[field] != pins[pin]:
            _fail("parent root, manifest or companion differs from independent identity")
    if _pure_pins() != _IMPORTED_PURE_PINS:
        _fail("parent review pure owners changed since import")

    # Reuse the complete parent's finite JSON walker and lower-only limits. No
    # decoder or physical owner is invoked here; originals remain required later.
    from . import corpus_parent_occurrence_adapter as parent

    bounds = parent._limits(parent_limits)
    reports = parent_inputs["report_bytes"]
    contracts.require_keys(reports, parent.REPORT_KEYS, "complete parent report bytes")
    report_pins = contracts.clone_json(parent_inputs["expected_report_pins"])
    contracts.require_keys(report_pins, parent.REPORT_KEYS, "complete parent report pins")
    report_bindings = {}
    report_total = 0
    for key in parent.REPORT_KEYS:
        contracts.require_keys(report_pins[key], {"raw_sha256", "canonical_sha256"}, "parent report hashes")
        for field in ("raw_sha256", "canonical_sha256"):
            contracts.require_sha256(report_pins[key][field], field)
        raw = reports[key]
        if type(raw) is not bytes or not 0 < len(raw) <= bounds["max_report_bytes"]:
            _fail("complete parent report exceeds bounded original bytes")
        actual = _sha(raw)
        if actual != report_pins[key]["raw_sha256"]:
            _fail("parent report differs from independently pinned original bytes")
        report_bindings[key] = {"sha256": actual, "bytes": len(raw)}
        report_total += len(raw)
    total += report_total
    residual = min(MAX_INPUT_BYTES - total, bounds["max_total_input_bytes"] - report_total)
    if residual <= 0:
        _fail("complete parent input byte bound exceeded before serialization")
    replay_raw = parent._plain(parent_inputs["replay_inputs"], min(bounds["max_replay_bytes"], residual))
    total += len(replay_raw)
    if total >= MAX_INPUT_BYTES:
        _fail("aggregate parent review byte bound exceeded before collection")
    bundle_raw = parent._plain(parent_inputs["parent_bundle"],
                               min(bounds["max_collection_bytes"], MAX_INPUT_BYTES - total))
    total += len(bundle_raw)
    pins_raw = canonical_dag_json_bytes(report_pins)
    if total + len(pins_raw) > MAX_INPUT_BYTES:
        _fail("aggregate parent review byte bound exceeded; truncation refused")
    binding = {
        "parent_manifest_cid": pins["parent_manifest_cid"],
        "root_source_occurrence_cid": pins["root_source_occurrence_cid"],
        "companion_record_cid": pins["companion_record_cid"],
        "source_binding_sha256": pins["source_binding_sha256"],
        "parent_bundle": {"sha256": _sha(bundle_raw), "bytes": len(bundle_raw)},
        "replay_inputs": {"sha256": _sha(replay_raw), "bytes": len(replay_raw)},
        "report_bytes": report_bindings,
        "expected_report_pins_sha256": _sha(pins_raw),
        "parent_limits": bounds,
    }
    return pins, population, contracts.clone_json(binding)


def _parent_artifact_inventory(candidate, pins, parent_inputs, transport,
                               contexts, producer_pins, native_pins, dependencies):
    artifacts, seen = [], {}

    def add(identity, sha256, policy_pins=()):
        # Shared records retain their identity once; physical occurrences with
        # equal text have distinct CIDs and must never collapse by text hash.
        if identity in seen:
            if seen[identity] != sha256 or policy_pins:
                _fail("conflicting parent review dependency identity")
            return
        seen[identity] = sha256
        policy = {kind: [] for kind in dependencies.PIN_KINDS}
        policy["policy"] = list(policy_pins)
        artifacts.append({"artifact_id": identity, "artifact_sha256": sha256,
                          "dependency_pins": policy})

    policy_pins = [
        {"key": prefix + path, "sha256": value}
        for prefix, source in (("parent-review:", producer_pins),
                               ("native-definition:", native_pins))
        for path, value in sorted(source.items())
    ]
    add(candidate["graph"]["record_cid"], _digest(candidate["graph"]), policy_pins)
    add(candidate["record_cid"], pins["candidate_sha256"])
    for label, field in (("request-bytes", "request_sha256"),
                         ("report-bytes", "report_sha256"),
                         ("extracted-text", "extracted_sha256")):
        add("parent-definition-review-input:" + label + ":sha256:" + pins[field], pins[field])
    for label, digest in (("source-binding", pins["source_binding_sha256"]),
                           ("complete-parent-transport", _digest(transport))):
        add("parent-definition-review-input:" + label + ":sha256:" + digest, digest)
    manifest = parent_inputs["parent_bundle"]["manifest"]
    add(manifest["record_cid"], _digest(manifest))
    for key, pin in transport["report_bytes"].items():
        add("parent-definition-review-input:" + key + ":sha256:" + pin["sha256"], pin["sha256"])
    for field in COMPANIONS:
        record = candidate[field]
        add(record["record_cid"], _digest(record))
    for record in (*candidate["source_occurrences"], *candidate["context_declarations"],
                   *candidate["issues"]):
        add(record["record_cid"], _digest(record))
    binding = candidate["parent_source_binding"]
    for field in ("parent_record", "companion_record", "cache_row_record", "context", "selector"):
        record = binding[field]
        if record is not None:
            add(record["record_cid"], _digest(record))
    for row in contexts:
        add("parent-definition-review-context:" + row["source_occurrence_cid"], row["packet_sha256"])
    identities = [row["artifact_id"] for row in artifacts]
    edges = [{"dependent_id": identities[0], "dependency_id": identity}
             for identity in identities[1:]]
    dependencies.build_dependency_manifest(artifacts, edges, expected_artifact_ids=identities)
    return artifacts, edges, identities


def prepare_parent_definition_review_evidence_v1(
    candidate_inputs, *, expected_candidate_pin, parent_inputs, context_inputs,
    expected_context_population, parent_limits=None,
):
    """Replay complete literal-parent custody and all declared physical contexts.

    Complete candidate population is not statutory contributor completeness.
    This preparation grants no human, semantic, training or Lean authority.
    """
    pins, population, transport = _parent_preflight(candidate_inputs,
        expected_candidate_pin, parent_inputs, context_inputs,
        expected_context_population, parent_limits)
    candidate = contracts.load_record_bytes(candidate_inputs["candidate_raw"],
        expected_sha256=pins["candidate_sha256"])
    report = contracts.load_record_bytes(candidate_inputs["report_raw"],
        expected_sha256=pins["report_sha256"])
    if type(report.get("limits")) is not dict:
        _fail("original parent definition compiler limits required")
    owners = _owners()
    producers = _parent_pins(owners)
    candidate = adapter.validate_parent_definition_only_candidate_v1(
        candidate, candidate_inputs["report_raw"],
        expected_report_sha256=pins["report_sha256"],
        request_raw=candidate_inputs["request_raw"], expected_request_sha256=pins["request_sha256"],
        **parent_inputs, parent_limits=parent_limits, limits=report["limits"])
    binding = candidate["parent_source_binding"]
    if (candidate["record_cid"] != pins["candidate_cid"]
            or candidate["graph"]["record_cid"] != pins["graph_cid"]
            or candidate["source_version"]["record_cid"] != pins["source_version_cid"]
            or candidate["source_version"]["extracted_view"]["sha256"] != pins["extracted_sha256"]
            or binding["source_binding_sha256"] != pins["source_binding_sha256"]
            or binding["parent_manifest_cid"] != pins["parent_manifest_cid"]
            or binding["selector"]["record_cid"] != pins["root_source_occurrence_cid"]
            or binding["companion_record"]["record_cid"] != pins["companion_record_cid"]):
        _fail("parent candidate, root binding or source version differs from independent identity")
    occurrences = candidate["source_occurrences"]
    identities = [row["record_cid"] for row in occurrences]
    if ([row["source_occurrence_cid"] for row in population] != identities
            or len(set(identities)) != len(identities)):
        _fail("parent context population must cover every unique source occurrence in order")
    dependencies, _, context_owner = owners
    contexts, slots = [], []
    for occurrence, inputs, pin in zip(occurrences, context_inputs, population, strict=True):
        packet = contracts.load_record_bytes(inputs["packet_raw"], expected_sha256=pin["packet_sha256"])
        requests = contracts.clone_json(inputs["dependency_requests"])
        try:
            context_owner.validate_parent_context_packet_v1(packet,
                **parent_inputs, selected_occurrence=occurrence,
                expected_selected_occurrence_cid=occurrence["record_cid"],
                expected_source_binding_sha256=pins["source_binding_sha256"],
                dependency_requests=requests, parent_limits=parent_limits)
        except (ValueError, TypeError, KeyError, IndexError, UnicodeError, RecursionError) as error:
            raise contracts.CorpusContractError(
                "parent context packet failed complete original occurrence regeneration") from error
        contexts.append({
            "source_occurrence_cid": occurrence["record_cid"],
            "packet_sha256": pin["packet_sha256"],
            "packet_canonical_sha256": _digest(packet),
            "packet_id": packet["packet_id"], "selector": occurrence,
            "source_view_binding": packet["source_view_binding"],
            "dependency_requests": requests, "dependency_slots": packet["dependency_slots"],
        })
        slots.extend(row["slot_id"] for row in packet["dependency_slots"])
    if (len(slots) != len(occurrences) * len(context_owner.DEPENDENCY_KINDS)
            or len(slots) > MAX_CONTEXT_OBLIGATIONS or len(set(slots)) != len(slots)):
        _fail("complete distinct parent context obligation population differs or exceeds profile")
    artifacts, edges, artifact_ids = _parent_artifact_inventory(candidate, pins,
        parent_inputs, transport, contexts, producers, report["producer_pins"], dependencies)
    if (_parent_pins(owners) != producers or _parent_preflight(candidate_inputs,
            expected_candidate_pin, parent_inputs, context_inputs,
            expected_context_population, parent_limits) != (pins, population, transport)):
        _fail("parent review producers or original transport changed during preparation")
    return contracts.seal_record({
        "schema": PARENT_PREPARATION_SCHEMA, "review_profile": PARENT_PROFILE,
        "profile": candidate["profile"], "family": candidate["family"],
        "candidate_pin": pins, "graph_id": pins["graph_cid"],
        "graph_sha256": _digest(candidate["graph"]),
        "ast_sha256": _digest(candidate["ast_record"]["native_ast"]),
        "scope_id": candidate["scope_record"]["record_cid"],
        "scope_key": candidate["scope_record"]["scope_key"],
        "companion_cids": {
            **{field: candidate[field]["record_cid"] for field in COMPANIONS},
            "context_declarations": [row["record_cid"] for row in candidate["context_declarations"]],
            "issues": [row["record_cid"] for row in candidate["issues"]],
        },
        "source_version": candidate["source_version"], "source_occurrences": occurrences,
        "source_bindings": candidate["source_bindings"],
        "native_ast": candidate["ast_record"]["native_ast"],
        "parent_source_binding": binding, "parent_input_binding": transport,
        "contexts": contexts, "context_slot_ids": slots,
        "expected_context_population": population, "producer_pins": producers,
        "native_producer_pins": report["producer_pins"], "artifacts": artifacts,
        "edges": edges, "expected_artifact_ids": artifact_ids,
        "hash_recipes": PARENT_HASH_RECIPES, "view": "candidate",
        "source_geometry_replayed": True, "context_packet_population_complete": True,
        **PARENT_FALSE_FLAGS,
    })


def validate_parent_definition_review_evidence_v1(
    preparation, *, candidate_inputs, expected_candidate_pin, parent_inputs,
    context_inputs, expected_context_population, parent_limits=None,
):
    checked = contracts.validate_record(preparation, schema=PARENT_PREPARATION_SCHEMA,
                                        fields=PARENT_FIELDS)
    expected = prepare_parent_definition_review_evidence_v1(candidate_inputs,
        expected_candidate_pin=expected_candidate_pin, parent_inputs=parent_inputs,
        context_inputs=context_inputs, expected_context_population=expected_context_population,
        parent_limits=parent_limits)
    if checked != expected:
        _fail("parent review evidence differs from independent regeneration")
    return checked


def _parent_manifest_binding(preparation, manifest, required_dependency_ids, owner):
    # Reuse the established complete dependency-closure check. Only the signed
    # descriptive role changes; no official V2 transport is introduced.
    reachable, artifacts, refs = _manifest_binding(preparation, manifest,
                                                   required_dependency_ids, owner)
    refs = [{**row, "reference": {**row["reference"],
             "role": "complete-parent-definition-review-evidence"}} for row in refs]
    owner._check_declared_dependencies(refs, reachable, artifacts)
    return reachable, artifacts, refs


def _parent_subject(subject, manifest):
    contracts.require_keys(subject, SUBJECT_FIELDS, "parent definition review subject")
    if subject["schema"] != PARENT_SUBJECT_SCHEMA:
        _fail("distinct parent definition-only review subject required")
    preparation = contracts.validate_record(subject["native_binding"],
        schema=PARENT_PREPARATION_SCHEMA, fields=PARENT_FIELDS)
    if preparation["review_profile"] != PARENT_PROFILE:
        _fail("distinct parent definition review evidence profile required")
    for field in ("graph_id", "graph_sha256", "ast_sha256", "scope_id", "context_slot_ids"):
        if subject[field] != preparation[field]:
            _fail("parent subject differs from complete evidence binding")
    _, owner, _ = _owners()
    reachable, artifacts, refs = _parent_manifest_binding(preparation, manifest,
        subject["required_dependency_ids"], owner)
    if (not reachable or subject["dependency_artifacts"] != artifacts
            or subject["graph_declared_dependency_refs"] != refs
            or subject["dependency_manifest_sha256"] != manifest["manifest_sha256"]):
        _fail("parent subject dependency binding differs")


def build_parent_definition_review_subject_v1(
    preparation, dependency_manifest, *, candidate_inputs, expected_candidate_pin,
    parent_inputs, context_inputs, expected_context_population,
    expected_manifest_sha256, required_dependency_ids, parent_limits=None,
):
    owners = _owners()
    producers = _parent_pins(owners)
    dependencies, owner, _ = owners
    # Bound manifest/closure before expensive physical replay as well as before
    # handing them to the existing dependency owner.
    owner.wire(dependency_manifest)
    owner.wire(required_dependency_ids)
    manifest = dependencies.validate_dependency_manifest(dependency_manifest,
        expected_manifest_sha256=expected_manifest_sha256)
    checked = validate_parent_definition_review_evidence_v1(preparation,
        candidate_inputs=candidate_inputs, expected_candidate_pin=expected_candidate_pin,
        parent_inputs=parent_inputs, context_inputs=context_inputs,
        expected_context_population=expected_context_population, parent_limits=parent_limits)
    reachable, artifacts, refs = _parent_manifest_binding(checked, manifest,
        required_dependency_ids, owner)
    subject = {"schema": PARENT_SUBJECT_SCHEMA,
        **{field: checked[field] for field in
            ("graph_id", "graph_sha256", "ast_sha256", "scope_id", "context_slot_ids")},
        "dependency_manifest_sha256": expected_manifest_sha256,
        "required_dependency_ids": reachable, "dependency_artifacts": artifacts,
        "graph_declared_dependency_refs": refs, "native_binding": checked}
    _parent_subject(subject, manifest)
    if _parent_pins(owners) != producers:
        _fail("parent review producers changed during subject construction")
    return contracts.clone_json(subject)


def assess_parent_definition_reviews_v1(
    subject, registry, policy, reviews, dependency_manifest, *, candidate_inputs,
    expected_candidate_pin, parent_inputs, context_inputs, expected_context_population,
    expected_subject_sha256, expected_registry_sha256, expected_policy_sha256,
    expected_reviews_sha256, expected_manifest_sha256, at_time_utc,
    observed_artifact_sha256s, observed_pins, evidence_artifacts, parent_limits=None,
):
    """Replay original plaintext custody, then use the fixed existing verifier."""
    before = _parent_preflight(candidate_inputs, expected_candidate_pin, parent_inputs,
        context_inputs, expected_context_population, parent_limits)
    owners = _owners()
    producers = _parent_pins(owners)
    _, owner, _ = owners
    checked = contracts.clone_json(subject)
    contracts.require_keys(checked, SUBJECT_FIELDS, "parent definition review subject")
    if type(reviews) is not list or len(reviews) > owner.MAX_REVIEWS:
        _fail("bounded complete parent review population required")
    if type(evidence_artifacts) is not dict or len(evidence_artifacts) > owner.MAX_EVIDENCE:
        _fail("bounded complete parent context evidence map required")
    total = 0
    for value in (checked, registry, policy, reviews, dependency_manifest,
                  observed_artifact_sha256s, observed_pins):
        total += len(owner.wire(value))
        if total > owner.MAX_BYTES:
            _fail("aggregate parent assessment input byte bound exceeded")
    for identity, raw in evidence_artifacts.items():
        owner.wire(identity)
        if type(raw) is not bytes or not 0 < len(raw) <= owner.MAX_BYTES:
            _fail("bounded immutable parent context evidence bytes required")
        total += len(raw)
        if total > owner.MAX_BYTES:
            _fail("aggregate parent assessment evidence byte bound exceeded")
    expected = build_parent_definition_review_subject_v1(checked["native_binding"],
        dependency_manifest, candidate_inputs=candidate_inputs,
        expected_candidate_pin=expected_candidate_pin, parent_inputs=parent_inputs,
        context_inputs=context_inputs, expected_context_population=expected_context_population,
        expected_manifest_sha256=expected_manifest_sha256,
        required_dependency_ids=checked["required_dependency_ids"], parent_limits=parent_limits)
    if checked != expected or checked["native_binding"]["producer_pins"] != producers:
        _fail("parent subject or producer bindings differ from independent regeneration")
    if _parent_pins(owners) != producers:
        _fail("parent review producers changed before authentication")
    domain = owner._ReviewDomain(PARENT_SUBJECT_SCHEMA, PARENT_CLAIM_SCHEMA,
        PARENT_ACTION, PARENT_AUDIENCE, PARENT_SCHEMA, _parent_subject, MAX_CONTEXT_OBLIGATIONS)
    result = owner._assess_reviews(checked, registry, policy, reviews, dependency_manifest,
        domain=domain, expected_subject_sha256=expected_subject_sha256,
        expected_registry_sha256=expected_registry_sha256,
        expected_policy_sha256=expected_policy_sha256,
        expected_reviews_sha256=expected_reviews_sha256,
        expected_manifest_sha256=expected_manifest_sha256, at_time_utc=at_time_utc,
        observed_artifact_sha256s=observed_artifact_sha256s, observed_pins=observed_pins,
        evidence_artifacts=evidence_artifacts)
    preparation = checked["native_binding"]
    body = {key: value for key, value in result.items() if key != "assessment_sha256"}
    body.update({"review_profile": PARENT_PROFILE,
        "native_profile": preparation["profile"], "native_family": preparation["family"],
        "candidate_cid": preparation["candidate_pin"]["candidate_cid"],
        "candidate_sha256": preparation["candidate_pin"]["candidate_sha256"],
        "graph_cid": preparation["candidate_pin"]["graph_cid"],
        "preparation_cid": preparation["record_cid"],
        **{field + "_cid": preparation["companion_cids"][field]
           for field in ("source_version", "definition_record", "ast_record")},
        "original_input_binding": preparation["candidate_pin"],
        "parent_input_binding": preparation["parent_input_binding"],
        "context_population_sha256": _digest(preparation["expected_context_population"]),
        "signature_owner_source_pinned": True,
        "cryptographic_distribution_authenticated": False, **PARENT_FALSE_FLAGS})
    report = {**body, "assessment_sha256": owner.digest(body)}
    owner.wire(report)
    if (_parent_pins(owners) != producers or _parent_preflight(candidate_inputs,
            expected_candidate_pin, parent_inputs, context_inputs,
            expected_context_population, parent_limits) != before):
        _fail("parent review producers or original transport changed during authentication")
    return report


def validate_parent_definition_review_assessment_v1(report, *args, **kwargs):
    _, owner, _ = _owners()
    owner.wire(report)
    expected = assess_parent_definition_reviews_v1(*args, **kwargs)
    if owner.wire(report) != owner.wire(expected):
        _fail("parent review assessment differs from exact regeneration")
    return expected


__all__ += [
    "prepare_parent_definition_review_evidence_v1",
    "validate_parent_definition_review_evidence_v1",
    "build_parent_definition_review_subject_v1",
    "assess_parent_definition_reviews_v1",
    "validate_parent_definition_review_assessment_v1",
]
