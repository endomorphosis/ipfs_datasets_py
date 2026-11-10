"""Explicit operator/presence descriptors from training-only retrieved ASTs.

This deterministic 24-class histogram is not a trained autoencoder or full AST
embedding. It retains modality and condition/exception/temporal presence, and
discards role names, qualifier values, order, and scope. Only retrieved training
targets may supply those classes; query targets are rejected by the interface.
"""
from __future__ import annotations

from collections import Counter
import copy
import hashlib
import math
from pathlib import Path

from . import legal_joint_retrieval as joint

SCHEMA = "legal-structured-retrieval-context/v1"
REPRESENTATION_ID = "legal-retrieved-profile-histogram-repeat16/v1"
REPRESENTATION_ROLE = "profile_descriptor_not_trained_autoencoder"
DIMENSION = 384
PROFILE_COUNT = 24
REPETITIONS = 16
MODALITIES = ("O", "P", "F")
PROFILE_CLASSES = tuple((modality, bool(pattern & 4), bool(pattern & 2), bool(pattern & 1))
                        for modality in MODALITIES for pattern in range(8))
_FALSE = {"qualified": False, "admitted": False, "proof_authority": False,
          "semantic_correctness_verified": False, "target_access": False,
          "query_target_access": False, "teacher_forcing": False,
          "training_executed": False}
_RETRIEVAL_REQUIRED = {"id", "source_sha256", "retrieved_ids", "weights", "index_sha256"}
_RETRIEVAL_ALLOWED = _RETRIEVAL_REQUIRED | {
    "context", "context_sha256", "scores", "checkpoint_sha256", "mode", "excluded_same_family",
    "eligible_rows", "index_scope", "context_dimension", "training_target_exemplars_accessed", *_FALSE}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _capture_implementation():
    return {"scope": "listed_files_only",
            "structured_retrieval_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "retrieval_dependencies": joint._implementation()}


_IMPLEMENTATION_AT_IMPORT = _capture_implementation()


def implementation_pin():
    """Return the current producer/dependency identity, rejecting source drift."""
    current = _capture_implementation()
    _require(current == _IMPLEMENTATION_AT_IMPORT, "structured retrieval implementation changed since import")
    return copy.deepcopy(current)


def profile_id(canonical_ir):
    """Classify a training AST: 8*modality(O,P,F) + 4*C + 2*E + T."""
    rule = joint.codec._rule(canonical_ir)
    return (8 * MODALITIES.index(rule["modality"]) + 4 * bool(rule["conditions"])
            + 2 * bool(rule["exceptions"]) + bool(rule["temporal"]))


def _probabilities(values, length, name):
    _require(type(values) in (list, tuple) and len(values) == length, name + " dimension differs")
    _require(all(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1
                 for value in values), name + " must contain finite probabilities")
    total = math.fsum(values)
    _require(abs(total - 1) <= 1e-6, name + " must sum to one")
    # Native retrieval weights are float32; remove only their small sum error.
    return [float(value) / total for value in values]


def profile_context(probabilities):
    """Embed a 24-class probability vector into 384D without changing its norm.

    Each probability occupies sixteen consecutive coordinates, each divided by
    sqrt(16)=4. Thus ||context||_2 = ||probabilities||_2 <= 1, up to rounding.
    """
    probabilities = _probabilities(probabilities, PROFILE_COUNT, "profile distribution")
    return [probability / 4 for probability in probabilities for _ in range(REPETITIONS)]


def _context_distribution(context):
    _require(type(context) in (list, tuple) and len(context) == DIMENSION,
             "structured context must contain 384 values")
    _require(all(type(value) in (float, int) and math.isfinite(value) for value in context),
             "structured context must contain finite values")
    probabilities = []
    for start in range(0, DIMENSION, REPETITIONS):
        block = context[start:start + REPETITIONS]
        _require(all(value == block[0] for value in block), "structured context repetition layout differs")
        probabilities.append(block[0] * 4)
    return _probabilities(probabilities, PROFILE_COUNT, "structured context distribution")


def cyclic_modality_context(context, shift=1):
    """Cycle only O/P/F class mass; leave each qualifier-presence bit unchanged.

    This target-free intervention changes supplied evidence and is not a
    semantics-preserving rewrite of a legal rule. Positive shift maps O->P->F.
    """
    _require(type(shift) is int and shift in (0, 1, 2), "modality shift must be 0, 1, or 2")
    original = _context_distribution(context)
    flipped = [0.] * PROFILE_COUNT
    for index, probability in enumerate(original):
        flipped[((index // 8 + shift) % 3) * 8 + index % 8] = probability
    return profile_context(flipped)


def _source_hash(query):
    return hashlib.sha256(query["source_text"].encode("utf-8")).hexdigest()


def build_contexts(training_index, query_rows, retrieval_rows):
    """Use only retrieved TRAIN target profiles; source-bound queries lack gold.

    Native dense retrieval records or their documented minimal id/hash/neighbor/
    weight/index projection are accepted. Every neighbor is independently
    checked against the index and the query's family, id, and source text.
    """
    pins = implementation_pin()
    training = joint._training_rows(training_index)
    queries = joint._queries(query_rows)
    _require(type(retrieval_rows) in (list, tuple) and len(retrieval_rows) == len(queries),
             "retrieval/query coverage differs")
    index_sha256 = joint.checkpoint_digest(training)
    known = {row["id"]: row for row in training}
    profiles = {identifier: profile_id(row["canonical_ir"]) for identifier, row in known.items()}
    result = []
    for query, retrieved in zip(queries, retrieval_rows):
        _require(type(retrieved) is dict and _RETRIEVAL_REQUIRED <= set(retrieved)
                 and set(retrieved) <= _RETRIEVAL_ALLOWED, "unsupported retrieval record fields")
        source_sha256 = _source_hash(query)
        _require(retrieved["id"] == query["id"] and retrieved["source_sha256"] == source_sha256,
                 "retrieval/query source identity differs")
        _require(retrieved["index_sha256"] == index_sha256, "retrieval training index digest differs")
        for key in _FALSE:
            if key in retrieved:
                _require(retrieved[key] is False, "retrieval record claims forbidden authority or target access")
        if "excluded_same_family" in retrieved:
            _require(retrieved["excluded_same_family"] is True, "retrieval did not exclude same family")
        neighbors = retrieved["retrieved_ids"]
        _require(type(neighbors) is list and 1 <= len(neighbors) <= 16
                 and all(type(identifier) is str for identifier in neighbors)
                 and len(set(neighbors)) == len(neighbors), "invalid or duplicate retrieved ids")
        weights = _probabilities(retrieved["weights"], len(neighbors), "retrieval weights")
        _require(all(weight > 0 for weight in weights), "retrieval weights must be positive")
        query_source_key = " ".join(query["source_text"].casefold().split())
        neighbor_profiles = []
        for identifier in neighbors:
            _require(identifier in known, "retrieved id is outside the training index")
            row = known[identifier]
            _require(row["id"] != query["id"] and row["source_sha256"] != source_sha256
                     and " ".join(row["source_text"].casefold().split()) != query_source_key,
                     "retrieved neighbor shares query identity or source")
            _require(row["family_group"] != query["family_group"], "retrieved neighbor shares query family")
            neighbor_profiles.append(profiles[identifier])
        distribution = [math.fsum(weight for weight, found in zip(weights, neighbor_profiles) if found == index)
                        for index in range(PROFILE_COUNT)]
        context = profile_context(distribution)
        result.append({"id": query["id"], "source_sha256": source_sha256,
            "query_family_group": query["family_group"], "context": context,
            "context_sha256": joint.checkpoint_digest(context), "context_dimension": DIMENSION,
            "profile_distribution": _context_distribution(context),
            "neighbor_profile_ids": neighbor_profiles, "retrieved_ids": list(neighbors),
            "weights": weights, "original_retrieval_weights": list(retrieved["weights"]),
            "weight_normalization": "divide_by_mass_within_1e-6_of_one",
            "index_sha256": index_sha256, "training_index_sha256": index_sha256,
            "retrieval_checkpoint_sha256": retrieved.get("checkpoint_sha256"),
            "retrieval_mode": retrieved.get("mode"),
            "retrieval_record_sha256": joint.checkpoint_digest(retrieved),
            "representation_id": REPRESENTATION_ID, "representation_role": REPRESENTATION_ROLE,
            "producer_sha256": joint.checkpoint_digest(pins),
            "training_target_exemplars_accessed": True, "query_target_values_embedded": False,
            "index_scope": "caller_supplied_training_rows_only", **_FALSE})
    _require(pins == implementation_pin(), "structured implementation changed during context construction")
    return {"schema": SCHEMA, "rows": result, "index_sha256": index_sha256,
            "training_index_sha256": index_sha256, "representation_id": REPRESENTATION_ID,
            "representation_role": REPRESENTATION_ROLE, "implementation": pins,
            "producer_sha256": joint.checkpoint_digest(pins),
            "profile_class_order": [list(profile) for profile in PROFILE_CLASSES],
            "training_target_exemplars_accessed": True, **_FALSE}


def permute_contexts_across_families(query_rows, context_rows):
    """Deterministic bijection moving contexts to a different query family.

    Caller-visible id/source hashes always refer to the receiving source.
    Donor identities separately record where context and retrieval metadata came
    from. No target labels enter this operation. Fewer than two families, or a
    majority family, cannot admit a complete permutation and are rejected.
    Source/id hashes scramble order inside family blocks so repeated template
    suffixes do not systematically align equivalent evidence across families.
    """
    queries = joint._queries(query_rows)
    _require(type(context_rows) in (list, tuple) and len(context_rows) == len(queries),
             "permutation context/query coverage differs")
    for query, record in zip(queries, context_rows):
        _require(type(record) is dict and {"id", "source_sha256", "context", "context_sha256"} <= set(record),
                 "permutation requires bound context records")
        _require(record["id"] == query["id"] and record["source_sha256"] == _source_hash(query),
                 "permutation query/source binding differs")
        if "query_family_group" in record:
            _require(record["query_family_group"] == query["family_group"], "context/query family differs")
        _require(joint.checkpoint_digest(record["context"]) == record["context_sha256"],
                 "permutation context digest differs")
        context = record["context"]
        _require(type(context) is list and len(context) == DIMENSION
                 and all(type(value) in (int, float) and math.isfinite(value) for value in context),
                 "permutation requires finite 384D contexts")
        _require(not any(key in record for key in ("canonical_ir", "source_spans", "formal_embedding")),
                 "permutation context must exclude query target fields")
        for key in ("query_target_access", "target_access", "teacher_forcing"):
            if key in record:
                _require(record[key] is False, "permutation context claims query target access")
    counts = Counter(query["family_group"] for query in queries)
    shift = max(counts.values())
    _require(len(queries) >= 2 and shift * 2 <= len(queries),
             "cross-family permutation impossible with a majority family")
    order = sorted(range(len(queries)), key=lambda index: (
        queries[index]["family_group"], joint.checkpoint_digest([
            "cross-family-permutation-source-order/v1", queries[index]["id"], _source_hash(queries[index])]),
        queries[index]["id"]))
    donors = {receiver: order[(position + shift) % len(order)] for position, receiver in enumerate(order)}
    _require(len(set(donors.values())) == len(queries), "permutation must use each donor once")
    result = []
    for receiver, query in enumerate(queries):
        donor_index = donors[receiver]
        donor = queries[donor_index]
        _require(query["family_group"] != donor["family_group"], "permutation failed family exclusion")
        record = copy.deepcopy(context_rows[donor_index])
        record.update(id=query["id"], source_sha256=_source_hash(query), query_family_group=query["family_group"],
            donor_query_id=donor["id"], donor_source_sha256=_source_hash(donor),
            donor_family_group=donor["family_group"],
            donor_context_sha256=context_rows[donor_index]["context_sha256"],
            receiver_original_context_sha256=context_rows[receiver]["context_sha256"],
            intervention="cross_family_context_permutation",
            context_provenance="donor_query_training_retrieval; receiving_source_remains_original")
        result.append(record)
    return result


# This complete-example profile is separate from the 384D histogram baseline.
REVIEWED_CONTEXT_SCHEMA = "legal-reviewed-retrieval-context/v2"
REVIEWED_CONTEXT_ROLE = "structural_examples_not_controlling_authorities"
MAX_REVIEWED_CONTEXT_BYTES = 1024 * 1024


def reviewed_context_inputs_sha256(value):
    """Use the existing consumer's bounded canonical JSON commitment recipe."""
    from . import legal_span_consumer_binding as binding_owner
    return binding_owner._guard(value).sha256


def consume_reviewed_contexts_v2(binding, training_rows, *, split_manifest,
        admission_inputs, exposure_records, query_rows, retrieval_rows,
        expected_query_rows_sha256, expected_retrieval_rows_sha256,
        consumer, max_context_bytes=262144):
    """Dispatch full source/typed-AST examples through present review replay.

    The supplied binding must authorize TRAIN targets via the existing reviewed
    consumer. Queries contain only enrolled source IDs and text. Selection order
    is caller-supplied, not an authenticated ranking. Governing definitions are
    expanded from that same reviewed training component; no query target enters
    the interface. Every exposed example passes source/family/lineage exclusion.

    This is an opt-in callback-argument contract, not a capability controlling
    all process reads or certification of inference-context permission. Review,
    split and exposure declarations keep their original authority and limits.
    No model, numerical projection, training, Lean or statutory truth is proved.
    Contexts are never truncated to a byte budget: the whole dispatch refuses.
    """
    import json
    from . import legal_span_consumer_binding as bound
    _require(type(binding) is bound.ReviewedSourceSpanConsumerBinding,
             "existing complete reviewed consumer binding required")
    _require(binding.receipt()["operation"] == "training",
             "rich example index requires a training binding")
    _require(callable(consumer), "explicit rich-context consumer required")
    _require(type(max_context_bytes) is int and 1 <= max_context_bytes <= MAX_REVIEWED_CONTEXT_BYTES,
             "bounded complete context byte allowance required")
    pins = implementation_pin()
    bound._sha256(expected_query_rows_sha256, "expected query rows SHA256")
    bound._sha256(expected_retrieval_rows_sha256, "expected retrieval rows SHA256")
    originals = (query_rows, retrieval_rows)
    copies = json.loads(bound._preflight(list(originals)))
    queries, retrieval = copies
    guards = tuple(bound._guard(v, h) for v, h in zip(copies,
        (expected_query_rows_sha256, expected_retrieval_rows_sha256)))
    _require(type(queries) is list and 1 <= len(queries) <= 32
             and type(retrieval) is list and len(retrieval) == len(queries),
             "complete bounded query and retrieval populations required")
    manifest, examples = bound._manifest(split_manifest, bound._guard(split_manifest))
    try:
        bound.splits.require_legal_ir_split_guard(manifest)
    except bound.splits.LegalIRSplitError as error:
        raise ValueError("rich context split leakage blocks dispatch") from error
    seen = set()
    for query in queries:
        bound._closed(query, {"id", "source_text"}, "target-free rich query")
        bound._text(query["id"], "rich query ID", 512)
        bound._text(query["source_text"], "rich query source", 65536)
        _require(query["id"] not in seen, "unique rich query IDs required")
        seen.add(query["id"])
        enrolled = examples.get(query["id"])
        _require(enrolled is not None and enrolled.content_hash == bound.splits._content_hash(query["source_text"]),
                 "query source differs from enrolled split source")

    def construct(rows):
        # Only the existing consumer supplies these detached, revalidated rows.
        index_sha = bound._guard(rows).sha256
        known = {row["id"]: row for row in rows}
        units = {row["unit_id"]: row for row in rows}
        result = []
        for query, selected in zip(queries, retrieval):
            bound._closed(selected, {"id", "source_sha256", "index_sha256", "retrieved_ids"},
                          "rich retrieval selection")
            source_sha = hashlib.sha256(query["source_text"].encode("utf-8")).hexdigest()
            _require(selected["id"] == query["id"] and selected["source_sha256"] == source_sha
                     and selected["index_sha256"] == index_sha,
                     "rich retrieval source or complete training index differs")
            ids = selected["retrieved_ids"]
            _require(type(ids) is list and 1 <= len(ids) <= 16
                     and all(type(key) is str and key in known for key in ids)
                     and len(set(ids)) == len(ids), "distinct training-only retrieved IDs required")
            queue, exposed, expanded = list(ids), [], set()
            while queue:
                key = queue.pop(0)
                if key in expanded:
                    continue
                expanded.add(key)
                row = known[key]
                enrolled = examples[key]
                query_example = examples[query["id"]]
                _require(key != query["id"] and enrolled.content_hash != query_example.content_hash,
                         "rich example shares query identity or source")
                for field in ("statute_family", "lineage_group_id", "amendment_key", "near_duplicate_key", "source_span_key"):
                    left, right = getattr(enrolled, field), getattr(query_example, field)
                    _require(not (left and left == right), "rich example shares query " + field)
                _require(not set(enrolled.citation_clusters).intersection(query_example.citation_clusters)
                         and not set(enrolled.sibling_keys).intersection(query_example.sibling_keys),
                         "rich example shares query citation or dependency group")
                ir = row["canonical_ir"]
                for use in ir["definition_uses"]:
                    if use["use_unit_id"] == row["unit_id"]:
                        definition = units.get(use["definition_unit_id"])
                        _require(definition is not None, "complete governing definition missing from permitted training rows")
                        queue.append(definition["id"])
                exposed.append({"id": key, "unit_id": row["unit_id"],
                    "source_text": row["source_text"], "canonical_ir": row["canonical_ir"],
                    "source_link": ir["source_binding"],
                    "selection_role": "retrieved_example" if key in ids else "governing_definition_of_training_example"})
            context = {"id": query["id"], "source_sha256": source_sha,
                "source_text": query["source_text"], "retrieved_ids": list(ids), "examples": exposed,
                "index_sha256": index_sha, "selection_sha256": bound._guard(selected).sha256,
                "selection_origin": "caller_supplied_ordered_selection",
                "retrieval_role": REVIEWED_CONTEXT_ROLE,
                "query_target_access": False, "teacher_forcing": False}
            context["context_sha256"] = bound._guard(context).sha256
            raw = bound._preflight(context)
            _require(len(raw) <= max_context_bytes, "complete rich context exceeds byte allowance; truncation refused")
            result.append(context)
        receipt = bound.validate_reviewed_source_span_consumer_binding_v2(binding, training_rows,
            split_manifest=split_manifest, admission_inputs=admission_inputs, exposure_records=exposure_records)
        _require(receipt["status"] == "ready", "present reviewed training admission is blocked")
        for guard, value, label in zip(guards, originals, ("queries", "retrieval selections")):
            bound._check(guard, value, label)
        _require(pins == implementation_pin(), "rich-context implementation changed during construction")
        payload = {"schema": REVIEWED_CONTEXT_SCHEMA, "rows": result,
            "training_index_sha256": index_sha, "binding_receipt": receipt,
            "implementation": pins, "retrieval_role": REVIEWED_CONTEXT_ROLE,
            "examples_are_complete": True, "query_target_access": False,
            "inference_context_permission_verified": False, "ranking_authenticated": False,
            "legal_applicability_established": False, "training_executed": False,
            "proof_authority": False, "corpus_admitted": False}
        return consumer(json.loads(bound._preflight(payload)))

    return bound.consume_reviewed_source_span_binding_v2(binding, training_rows,
        split_manifest=split_manifest, admission_inputs=admission_inputs,
        exposure_records=exposure_records, consumer=construct)


RICH_SCHEMA = "legal-reviewed-full-example-context-candidate/v1"
RICH_PROFILE = "complete-reviewed-training-examples/v1"
RICH_MAX_BYTES = joint.MAX_BYTES  # Same existing16MiB bound, independent of numerical-input checks.
_RICH_CONSUMER_FIELDS = {"rows", "expected_rows_sha256", "exposure_records",
                         "expected_exposure_sha256", "allow_fictional_fixture"}
_RICH_FALSE = {"decoder_context_admitted": False, "arbitrary_context_permission": False,
    "proof_authority": False, "kernel_checked": False, "corpus_admitted": False,
    "legal_applicability_verified": False, "controlling_authority_selected": False,
    "heldout_evaluation_performed": False, "training_executed": False,
    "query_target_access": False, "inference_reference_content_forwarded": False,
    "governing_definition_bodies_supplied": False, "proof_dependency_bodies_supplied": False}


def _rich_owners():
    from . import legal_span_consumer_binding as consumer
    _, handoff, _, admission = joint._reviewed_owners()
    _require(callable(getattr(consumer, "prepare_reviewed_source_span_consumer_binding_v2", None)),
             "the existing complete reviewed source-span consumer v2 is required")
    return handoff, admission, consumer


def _rich_implementation():
    handoff, admission, consumer = _rich_owners()
    return {"structured_owner": implementation_pin(), "reviewed_retrieval": joint._reviewed_implementation(),
            "complete_example_owners": {str(Path(owner.__file__).resolve()):
                hashlib.sha256(Path(owner.__file__).read_bytes()).hexdigest()
                for owner in (handoff, admission, consumer)}}


def _rich_profile_identity(identity, expected_sha256):
    if identity is None:
        _require(expected_sha256 is None, "an absent context identity cannot have a supplied digest")
        return None
    _require(type(identity) is dict and set(identity) == {"decoder_profile_sha256", "kernel_profile_sha256"},
             "only opaque decoder/kernel profile identity commitments are accepted")
    _require(all(value is None or type(value) is str and joint._SHA.fullmatch(value)
                 for value in identity.values()), "context profile commitments must be SHA256 values or absent")
    _require(type(expected_sha256) is str and joint.checkpoint_digest(identity) == expected_sha256,
             "independently pinned context profile identity differs")
    return copy.deepcopy(identity)


def _rich_current_assessment(identity, entry, inputs, admission):
    observations = inputs["current_endpoint_observations"][identity]
    arguments = dict(entry["kwargs"], at_time_utc=inputs["at_time_utc"],
        observed_artifact_sha256s=observations["observed_artifact_sha256s"],
        observed_pins=observations["observed_pins"])
    report = admission.assess_reviewed_norm_admission_v2(*entry["args"], **arguments)
    # The canonical consumer takes the same full replay as keyword arguments.
    _require(type(entry["args"]) is list and len(entry["args"]) == 4,
             "exact original complete admission arguments required")
    arguments.update(zip(("preparation", "registry", "policy", "reviews"), entry["args"]))
    return report, arguments



def _rich_bounded_candidate(value):
    _require(len(joint._raw(value)) <= RICH_MAX_BYTES, "complete rich candidate byte budget exceeded")
    return value


def _rich_charge_candidate(budget, value, *, overhead=0):
    # Charge serialized selected material before deep-copying it into any query
    # result. The final complete wire check independently enforces the limit.
    budget[0] += len(joint._raw(value)) + overhead
    _require(budget[0] <= RICH_MAX_BYTES, "complete rich candidate byte budget exceeded before selected copy")


def build_reviewed_rich_context_candidates(retriever, query_rows, preparation, registry, policy, reviews, *,
        retrieval_inputs, example_consumer_inputs, context_profile_identity=None,
        expected_context_profile_identity_sha256=None):
    """Retain complete selected TRAIN examples under existing review custody.

    This is a candidate artifact, not permission to feed targets into a decoder.
    The v2 consumer independently binds every offered TRAIN source/IR row and
    explicit exposure declaration. Current-index ranking, query exclusions and
    current legal reviews are replayed. Optional profile hashes are commitments
    only. No query target, full source document, sibling norm, governing-definition
    body or proof body is forwarded. The dense v1 context contract is unchanged.
    Caller-owned model/resource admission remains necessary for ranking.
    """
    _require(type(retriever) is joint.ReviewedLegalJointRetriever,
             "the canonical reviewed current-index retriever is required")
    handoff, admission, consumer = _rich_owners()
    original = dict(query_rows=query_rows, preparation=preparation, registry=registry, policy=policy,
        reviews=reviews, retrieval_inputs=retrieval_inputs, example_consumer_inputs=example_consumer_inputs,
        context_profile_identity=context_profile_identity,
        expected_context_profile_identity_sha256=expected_context_profile_identity_sha256)
    frozen, input_sha256 = admission.norm._snapshot(original)
    _require(type(frozen["retrieval_inputs"]) is dict, "complete current retrieval inputs required")
    implementation = _rich_implementation()
    identity = _rich_profile_identity(frozen["context_profile_identity"],
                                     frozen["expected_context_profile_identity_sha256"])
    inputs = frozen["retrieval_inputs"]
    replay_fields = ("expected_preparation_sha256", "preparation_inputs", "expected_registry_sha256",
        "expected_policy_sha256", "expected_reviews_sha256", "at_time_utc", "observed_artifact_sha256s",
        "observed_pins", "evidence_artifacts", "current_endpoint_observations")
    replay = {key: inputs[key] for key in replay_fields}
    args = tuple(frozen[key] for key in ("preparation", "registry", "policy", "reviews"))
    current = handoff.compile_reviewed_train_relation_masks_v2(*args, **replay)
    current_sha256 = joint.checkpoint_digest(current)
    common = dict(schema=RICH_SCHEMA, profile=RICH_PROFILE, status="candidate_only",
        representation_role="complete_selected_source_and_typed_ast_examples",
        input_sha256=input_sha256, implementation=implementation,
        current_index_handoff_sha256=current_sha256, context_profile_identity=identity,
        context_profile_identity_scope="opaque_identity_commitment_only_no_permission_or_compatibility_claim",
        example_scope="existing_complete_reviewed_TRAIN_consumer_arguments_only",
        context_policy_status="no_existing_full_ast_inference_context_permission_contract",
        decoder_integration_status="unavailable_P5_context_profile_remains_none",
        original_raw_source_documents_forwarded=False,
        source_byte_scope="exact_selected_extracted_span_UTF8_only",
        supplemental_context_status="governing_definition_and_proof_bodies_unavailable_refs_only",
        model_use_and_resource_admission_scope="caller_owned_not_validated_here", **_RICH_FALSE)
    if current.get("reviewed_objective_mask_ready") is not True:
        return _rich_bounded_candidate({**common, "status": "abstained_current_index_unavailable", "rows": [],
            "candidate_count": 0, "abstention_count": len(frozen["query_rows"]),
            "blockers": current.get("objective_blockers", []), "model_forward_executed": False})
    endpoints = current["formal_endpoints"]
    by_admission = {}
    for endpoint in endpoints:
        by_admission.setdefault(endpoint["admission_id"], {}).setdefault(endpoint["unit_id"], []).append(endpoint)
    offered = frozen["example_consumer_inputs"]
    _require(type(offered) is dict and set(offered) == set(by_admission),
             "exact complete formal-index admission population required")
    original_admissions = inputs["preparation_inputs"]["endpoint_admissions"]
    material, bindings, blockers = {}, {}, []
    for admission_id, index_units in by_admission.items():
        entry = original_admissions[admission_id]
        report, admission_inputs = _rich_current_assessment(admission_id, entry, inputs, admission)
        _require(admission.norm_content_adjudication_sha256(report)
                 == current["current_endpoint_assessment_sha256s"][admission_id],
                 "current full-unit assessment differs from current index")
        supplied = offered[admission_id]
        _require(type(supplied) is dict and set(supplied) == _RICH_CONSUMER_FIELDS,
                 "exact existing reviewed-consumer row/exposure inputs required")
        rows = supplied["rows"]
        _require(type(rows) is list and {row["unit_id"] for row in rows} == set(index_units)
                 and len(rows) == len(index_units), "one complete row per current formal-index unit required")
        for row in rows:
            aliases = index_units[row["unit_id"]]
            _require(any(row["id"] == endpoint["split_sample_id"] for endpoint in aliases),
                     "consumer row must use an actual TRAIN endpoint split identity")
        binding = consumer.prepare_reviewed_source_span_consumer_binding_v2(rows,
            expected_rows_sha256=supplied["expected_rows_sha256"],
            split_manifest=inputs["preparation_inputs"]["split_manifest"],
            expected_split_manifest_sha256=inputs["preparation_inputs"]["expected_split_manifest_sha256"],
            admission_inputs=admission_inputs,
            expected_admission_inputs_sha256=consumer.reviewed_admission_inputs_sha256(admission_inputs),
            exposure_records=supplied["exposure_records"],
            expected_exposure_sha256=supplied["expected_exposure_sha256"], operation="training",
            allow_fictional_fixture=supplied["allow_fictional_fixture"])
        receipt = consumer.validate_reviewed_source_span_consumer_binding_v2(binding, rows,
            split_manifest=inputs["preparation_inputs"]["split_manifest"],
            admission_inputs=admission_inputs, exposure_records=supplied["exposure_records"])
        if receipt["status"] != "ready":
            blockers.append({"admission_id": admission_id, "reason": "complete_TRAIN_example_binding_unavailable",
                             "details": receipt["blockers"]})
        if "formalization" not in report["permitted_uses"]:
            blockers.append({"admission_id": admission_id, "reason": "formalization_use_not_explicitly_reviewed"})
        units = {unit["unit_id"]: unit for unit in report["units"]}
        declared_units = {unit["unit_id"]: unit for unit in entry["kwargs"]["preparation_inputs"]["declaration"]["units"]}
        for unit_id in index_units:
            unit, declared = units[unit_id], declared_units[unit_id]
            utf8 = unit["source_text"].encode("utf-8")
            material[(admission_id, unit_id)] = {"unit_id": unit_id, "unit_kind": unit["kind"], "admission_id": admission_id,
                "source_text": unit["source_text"], "source_utf8_hex": utf8.hex(),
                "source_sha256": hashlib.sha256(utf8).hexdigest(),
                "canonical_ir": copy.deepcopy(unit["canonical_ir"]),
                "canonical_ir_sha256": joint.checkpoint_digest(unit["canonical_ir"]),
                "argument_roles": copy.deepcopy(unit["argument_roles"]),
                "relational_profile": unit["relational_profile"],
                "source_version": copy.deepcopy(declared["source_version"]),
                "source_occurrence": copy.deepcopy(declared["occurrence"]),
                "document_revision": declared["document_revision"],
                "source_artifact_id": declared["source_artifact_id"], "ir_artifact_id": declared["ir_artifact_id"],
                "source_correspondence_coverage": copy.deepcopy(declared["coverage"]),
                "reviewed_declaration_sha256": report["declaration_sha256"],
                "current_admission_assessment_sha256": admission.norm_content_adjudication_sha256(report),
                "TRAIN_consumer_receipt_sha256": joint.checkpoint_digest(receipt),
                "TRAIN_consumer_custody": {
                    "schema": receipt["schema"], "profile": receipt["profile"], "operation": receipt["operation"],
                    "status": receipt["status"], "scope": "selected_row_identity_only_no_exposure_prose",
                    "row_identity_sha256": joint.checkpoint_digest({key: next(
                        row for row in receipt["rows"] if row["unit_id"] == unit_id)[key]
                        for key in ("id", "unit_id", "occurrence_cid", "source_text_sha256", "canonical_ir_sha256")}),
                    "exposure_kind": next(row for row in receipt["rows"] if row["unit_id"] == unit_id)["exposure"]["target_exposure"],
                    "provenance_ref_sha256": hashlib.sha256(next(row for row in receipt["rows"]
                        if row["unit_id"] == unit_id)["exposure"]["provenance_ref"].encode("utf-8")).hexdigest()},
                "reviewed_semantic_uses": copy.deepcopy(report["permitted_uses"]),
                "provenance_kind": report["provenance_kind"],
                "training_mask": report["training_mask"], "evaluation_gold_mask": 0}
        bindings[admission_id] = (binding, rows, admission_inputs, supplied["exposure_records"])
    if blockers:
        return _rich_bounded_candidate({**common, "status": "abstained_example_custody_unavailable", "rows": [],
            "candidate_count": 0, "abstention_count": len(frozen["query_rows"]),
            "blockers": blockers, "model_forward_executed": False})
    retrieval = retriever.retrieve(frozen["query_rows"], *args, **inputs)
    _require(retrieval["current_index_handoff_sha256"] == current_sha256,
             "ranking used another current index")
    endpoint_map = {endpoint["id"]: endpoint for endpoint in endpoints}
    result_rows = []
    budget = [len(joint._raw(common)) + 1024]  # Top-level completion fields and delimiters.
    _require(budget[0] <= RICH_MAX_BYTES, "complete rich candidate byte budget exceeded")
    for row in retrieval["rows"]:
        if row["status"] != "retrieved":
            abstention = {"id": row["id"], "status": "abstained", "examples": [],
                "abstention_reasons": row.get("abstention_reasons", []), "query_target_access": False}
            _rich_charge_candidate(budget, abstention, overhead=2)
            result_rows.append(abstention)
            continue
        examples, groups = [], {}
        row_identity = {"id": row["id"], "status": "candidate_only", "source_sha256": row["source_sha256"],
            "split_sample_id": row["split_sample_id"], "source_exposure_group": row["source_exposure_group"],
            "query_input_sha256": row["query_input_sha256"], "examples": [],
            "abstention_reasons": [], "query_target_access": False}
        _rich_charge_candidate(budget, row_identity, overhead=128)
        _require(len(row["retrieved_endpoint_refs"]) == len(row["retrieved_ids"]) == len(row["weights"]),
                 "complete ordered selected endpoint identities and weights required")
        for endpoint, endpoint_id, weight in zip(row["retrieved_endpoint_refs"], row["retrieved_ids"], row["weights"], strict=True):
            _require(endpoint == endpoint_map[endpoint_id] and endpoint["split"] == "train",
                     "selected full example differs from independently replayed TRAIN endpoint")
            key = (endpoint["admission_id"], endpoint["unit_id"])
            _rich_charge_candidate(budget, endpoint, overhead=64)
            _rich_charge_candidate(budget, weight, overhead=2)
            if key not in groups:
                _rich_charge_candidate(budget, material[key], overhead=96)
                example = copy.deepcopy(material[key])
                _require(example["source_sha256"] == endpoint["source_sha256"], "selected complete source differs")
                example["selected_endpoint_refs"], example["ranking_weights"] = [], []
                groups[key] = example
                examples.append(example)
            groups[key]["selected_endpoint_refs"].append(copy.deepcopy(endpoint))
            groups[key]["ranking_weights"].append(weight)
        result_rows.append({**row_identity, "examples": examples,
            "distinct_source_unit_count": len(examples), "selected_representation_count": len(row["retrieved_ids"])})
    after = handoff.compile_reviewed_train_relation_masks_v2(*args, **replay)
    _require(joint.checkpoint_digest(after) == current_sha256, "current admission changed while building full examples")
    for binding, rows, admission_inputs, exposure_records in bindings.values():
        checked = consumer.validate_reviewed_source_span_consumer_binding_v2(binding, rows,
            split_manifest=inputs["preparation_inputs"]["split_manifest"], admission_inputs=admission_inputs,
            exposure_records=exposure_records)
        _require(checked["status"] == "ready", "complete TRAIN example custody changed during construction")
    _require(admission.norm._snapshot(original)[1] == input_sha256
             and admission.norm._snapshot(frozen)[1] == input_sha256,
             "complete rich candidate inputs changed during construction")
    _require(_rich_implementation() == implementation, "full-example implementation changed during construction")
    return _rich_bounded_candidate({**common, "rows": result_rows, "blockers": [],
        "retrieval_result_sha256": joint.checkpoint_digest(retrieval),
        "checkpoint_sha256": retrieval["checkpoint_sha256"],
        "candidate_count": sum(row["status"] == "candidate_only" for row in result_rows),
        "abstention_count": sum(row["status"] == "abstained" for row in result_rows),
        "model_forward_executed": retrieval["model_forward_executed"]})


def validate_reviewed_rich_context_candidates(candidate, *args, expected_candidate_sha256, **kwargs):
    """Recompute complete current custody and ranking; never trust ready flags.

    Validation qualifies this candidate profile only. It provides no permission
    for any decoder, no proof of the current query and no legal applicability
    judgment. Model/resource permission for replay remains caller owned.
    """
    _require(type(candidate) is dict and joint.checkpoint_digest(candidate) == expected_candidate_sha256,
             "independently pinned full-example candidate differs")
    before = joint.checkpoint_digest(candidate)
    replayed = build_reviewed_rich_context_candidates(*args, **kwargs)
    _require(joint._raw(candidate) == joint._raw(replayed), "full-example candidate differs from fresh replay")
    _require(joint.checkpoint_digest(candidate) == before, "candidate changed during full replay")
    return copy.deepcopy(replayed)
