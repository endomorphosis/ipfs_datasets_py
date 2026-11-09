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
