"""Typed profiles, norm-preserving context and target-free interventions."""
import copy
import hashlib
import importlib
import math
import random

import pytest

structured = importlib.import_module(
    "ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_structured_retrieval")


def training():
    result = []
    for group in ("alpha", "beta"):
        for index, (modality, condition, exception, temporal) in enumerate(structured.PROFILE_CLASSES):
            rule = {"modality": modality, "actor": group, "action": "file", "object": "records",
                    "conditions": ["eligible"] if condition else [],
                    "exceptions": ["exempt"] if exception else [],
                    "temporal": ["within 30 days"] if temporal else []}
            source = (f"{group} {modality} file records" + (" if eligible" if condition else "")
                      + (" unless exempt" if exception else "") + (" within 30 days" if temporal else "") + ".")
            result.append({"id": f"{group}-{index}", "source_text": source,
                "source_sha256": hashlib.sha256(source.encode()).hexdigest(), "family_group": group,
                "embedding": [float(i == index) for i in range(384)],
                "formal_embedding": [float(i == index + 32) for i in range(384)],
                "canonical_ir": {"rules": [rule]}})
    return result


def query(identifier="query", family="heldout"):
    return {"id": identifier, "source_text": f"The {identifier} body shall file records.",
            "family_group": family, "embedding": [1.] + [0.] * 383}


def retrieved(query_row, index=None, ids=None, weights=None):
    index = training() if index is None else index
    return {"id": query_row["id"],
            "source_sha256": hashlib.sha256(query_row["source_text"].encode()).hexdigest(),
            "retrieved_ids": ids or ["alpha-0", "alpha-8", "beta-23"],
            "weights": [.2, .3, .5] if weights is None else weights,
            "index_sha256": structured.joint.checkpoint_digest(index)}


def build(index=None, query_row=None, retrieval=None):
    index = training() if index is None else index
    query_row = query() if query_row is None else query_row
    retrieval = retrieved(query_row, index) if retrieval is None else retrieval
    return structured.build_contexts(index, [query_row], [retrieval])


def test_all_24_profiles_have_documented_modality_and_presence_order():
    for index, row in enumerate(training()[:24]):
        assert structured.profile_id(row["canonical_ir"]) == index
        profile = structured.PROFILE_CLASSES[index]
        assert structured.MODALITIES[index // 8] == profile[0]
        assert [bool(index & bit) for bit in (4, 2, 1)] == list(profile[1:])
        distribution = [float(i == index) for i in range(24)]
        context = structured.profile_context(distribution)
        assert context[index * 16:(index + 1) * 16] == [.25] * 16
        assert math.fsum(value * value for value in context) == 1.
        assert sum(value != 0 for value in context) == 16


def test_weighted_descriptor_has_training_provenance_and_preserves_distribution_norm():
    report = build()
    result = report["rows"][0]
    assert result["neighbor_profile_ids"] == [0, 8, 23]
    assert result["profile_distribution"][0] == pytest.approx(.2)
    assert result["profile_distribution"][8] == pytest.approx(.3)
    assert result["profile_distribution"][23] == pytest.approx(.5)
    assert math.fsum(value * value for value in result["context"]) == pytest.approx(.2**2 + .3**2 + .5**2)
    assert result["context_sha256"] == structured.joint.checkpoint_digest(result["context"])
    assert result["index_sha256"] == structured.joint.checkpoint_digest(training())
    assert result["representation_role"] == "profile_descriptor_not_trained_autoencoder"
    assert report["training_target_exemplars_accessed"] and not report["query_target_access"]
    assert not result["query_target_values_embedded"] and not result["teacher_forcing"]
    assert "canonical_ir" not in result and "formal_embedding" not in result


def test_descriptor_is_invariant_to_lexical_values_and_unmodified_inputs():
    index = training()
    original = copy.deepcopy(index)
    before = build(index)["rows"][0]
    changed = copy.deepcopy(index)
    for row in changed:
        rule = row["canonical_ir"]["rules"][0]
        rule["actor"] = "new " + rule["actor"]
        rule["action"] = "inspect"
        rule["object"] = "licenses"
        for field in ("conditions", "exceptions", "temporal"):
            rule[field] = ["different " + value for value in rule[field]]
        row["formal_embedding"] = list(reversed(row["formal_embedding"]))
    after = build(changed)["rows"][0]
    assert before["context"] == after["context"]
    assert before["index_sha256"] != after["index_sha256"]
    assert index == original


def test_probability_norm_and_float32_weight_mass_are_bounded():
    generator = random.Random(17)
    for _ in range(30):
        values = [generator.random() for _ in range(24)]
        total = math.fsum(values)
        probabilities = [value / total for value in values]
        context = structured.profile_context(probabilities)
        assert math.fsum(value * value for value in context) <= 1 + 1e-15
        assert math.fsum(value * value for value in context) == pytest.approx(math.fsum(value**2 for value in probabilities))
    q = query()
    row = retrieved(q, weights=[.3333333432674408] * 3)
    context = build(query_row=q, retrieval=row)["rows"][0]
    assert context["original_retrieval_weights"] == row["weights"]
    assert math.fsum(context["weights"]) == pytest.approx(1)


def test_native_retriever_records_are_accepted_without_query_reference_access():
    torch = pytest.importorskip("torch")
    before_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        index = training()
        checkpoint = structured.joint.train_retriever(index, steps=0, joint_dimension=8)["checkpoint"]
        retriever = structured.joint.LegalJointRetriever(index, checkpoint)
        q = query()
        native = retriever.retrieve([q], mode="raw", top_k=3)["rows"]
        result = structured.build_contexts(index, [q], native)["rows"][0]
        known = {row["id"]: row for row in index}
        assert result["neighbor_profile_ids"] == [structured.profile_id(known[identifier]["canonical_ir"])
                                                   for identifier in native[0]["retrieved_ids"]]
        assert result["retrieval_checkpoint_sha256"] == native[0]["checkpoint_sha256"]
        assert result["retrieval_record_sha256"] == structured.joint.checkpoint_digest(native[0])
    finally:
        torch.set_num_threads(before_threads)


@pytest.mark.parametrize("field", ["canonical_ir", "formal_embedding", "source_spans", "target_hint"])
def test_query_target_injection_is_rejected(field):
    q = {**query(), field: "forbidden"}
    with pytest.raises(ValueError, match="target-free"):
        build(query_row=q)


@pytest.mark.parametrize("change", ["nontrain", "duplicate", "same_family", "same_id", "same_source", "source_hash", "index_hash", "target_claim", "metadata_target"])
def test_untrusted_retrieval_neighbor_and_identity_claims_are_checked(change):
    index = training()
    q = query()
    row = retrieved(q, index)
    if change == "nontrain":
        row["retrieved_ids"][0] = "heldout-label"
    elif change == "duplicate":
        row["retrieved_ids"][1] = row["retrieved_ids"][0]
    elif change == "same_family":
        q["family_group"] = "alpha"
    elif change == "same_id":
        q["id"] = "alpha-0"
        row["id"] = q["id"]
    elif change == "same_source":
        q["source_text"] = index[0]["source_text"].upper()
        row["source_sha256"] = hashlib.sha256(q["source_text"].encode()).hexdigest()
    elif change == "source_hash":
        row["source_sha256"] = "0" * 64
    elif change == "index_hash":
        row["index_sha256"] = "0" * 64
    elif change == "target_claim":
        row["query_target_access"] = True
    else:
        row["canonical_ir"] = index[0]["canonical_ir"]
    with pytest.raises(ValueError):
        build(index=index, query_row=q, retrieval=row)


@pytest.mark.parametrize("weights", [[0., .5, .5], [-.1, .6, .5], [float("nan"), .5, .5], [.1, .1, .1], [True, 0., 0.], [.5, .5]])
def test_malformed_retrieval_weights_are_rejected(weights):
    q = query()
    with pytest.raises(ValueError):
        build(query_row=q, retrieval=retrieved(q, weights=weights))


def test_cyclic_modality_intervention_preserves_qualifier_pattern_and_norm():
    for index in range(24):
        original = structured.profile_context([float(i == index) for i in range(24)])
        flipped = structured.cyclic_modality_context(original)
        expected = ((index // 8 + 1) % 3) * 8 + index % 8
        assert structured._context_distribution(flipped)[expected] == 1
        assert structured.cyclic_modality_context(flipped, shift=2) == original
        assert math.fsum(value * value for value in flipped) == 1
    mixed = build()["rows"][0]["context"]
    original = structured._context_distribution(mixed)
    flipped = structured._context_distribution(structured.cyclic_modality_context(mixed))
    for pattern in range(8):
        assert sum(original[pattern + 8 * mode] for mode in range(3)) == pytest.approx(
            sum(flipped[pattern + 8 * mode] for mode in range(3)))
    broken = mixed[:]
    broken[0] += .001
    with pytest.raises(ValueError, match="layout"):
        structured.cyclic_modality_context(broken)
    with pytest.raises(ValueError, match="shift"):
        structured.cyclic_modality_context(mixed, shift=True)


def contexts_for_queries(queries):
    result = []
    for index, q in enumerate(queries):
        context = structured.profile_context([float(i == index) for i in range(24)])
        result.append({"id": q["id"], "source_sha256": hashlib.sha256(q["source_text"].encode()).hexdigest(),
            "query_family_group": q["family_group"], "context": context,
            "context_sha256": structured.joint.checkpoint_digest(context), "target_access": False})
    return result


def test_cross_family_permutation_is_bijective_and_keeps_receiving_source_binding():
    queries = [query(str(index), family) for index, family in enumerate(["a", "a", "b", "b", "c", "c"])]
    contexts = contexts_for_queries(queries)
    original = copy.deepcopy(contexts)
    result = structured.permute_contexts_across_families(queries, contexts)
    by_id = {q["id"]: record for q, record in zip(queries, contexts)}
    assert {row["donor_query_id"] for row in result} == set(by_id)
    for receiver, record in zip(queries, result):
        donor_record = by_id[record["donor_query_id"]]
        assert record["id"] == receiver["id"]
        assert record["source_sha256"] == hashlib.sha256(receiver["source_text"].encode()).hexdigest()
        assert record["donor_family_group"] != receiver["family_group"]
        assert record["context"] == donor_record["context"]
        assert record["context_sha256"] == record["donor_context_sha256"] == donor_record["context_sha256"]
        assert record["donor_source_sha256"] == donor_record["source_sha256"]
        assert record["intervention"] == "cross_family_context_permutation"
    reverse = structured.permute_contexts_across_families(list(reversed(queries)), list(reversed(contexts)))
    assert result == list(reversed(reverse))
    assert contexts == original


def test_permutation_rejects_impossible_family_distribution_and_unbound_contexts():
    queries = [query(str(index), family) for index, family in enumerate(["a", "a", "b"])]
    with pytest.raises(ValueError, match="majority"):
        structured.permute_contexts_across_families(queries, contexts_for_queries(queries))
    queries = [query("0", "a"), query("1", "b")]
    contexts = contexts_for_queries(queries)
    contexts[0]["context"][0] += .01
    with pytest.raises(ValueError, match="digest"):
        structured.permute_contexts_across_families(queries, contexts)
    contexts = contexts_for_queries(queries)
    contexts[0]["canonical_ir"] = training()[0]["canonical_ir"]
    with pytest.raises(ValueError, match="target fields"):
        structured.permute_contexts_across_families(queries, contexts)


def test_permutation_accepts_signed_dense_vectors_without_profile_assumptions():
    queries = [query("0", "a"), query("1", "b")]
    contexts = contexts_for_queries(queries)
    for index, record in enumerate(contexts):
        record["context"] = [math.sin(index + position) / 20 for position in range(384)]
        record["context_sha256"] = structured.joint.checkpoint_digest(record["context"])
    result = structured.permute_contexts_across_families(queries, contexts)
    assert result[0]["context"] == contexts[1]["context"]
    assert result[1]["context"] == contexts[0]["context"]


def test_hashed_order_breaks_repeated_template_alignment_across_families():
    queries = [query(f"{family}-template-{pattern}", family)
               for family in ("a", "b", "c") for pattern in range(8)]
    contexts = contexts_for_queries(queries)
    for index, record in enumerate(contexts):
        # Equal template suffixes have equal descriptors in all three families.
        record["context"] = structured.profile_context([float(profile == index % 8) for profile in range(24)])
        record["context_sha256"] = structured.joint.checkpoint_digest(record["context"])
    result = structured.permute_contexts_across_families(queries, contexts)
    assert any(before["context"] != after["context"] for before, after in zip(contexts, result))
    assert all(query["family_group"] != after["donor_family_group"] for query, after in zip(queries, result))
