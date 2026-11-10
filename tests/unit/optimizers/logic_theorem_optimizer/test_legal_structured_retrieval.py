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


def _reviewed_rich_case(*, query_family="query-family", query_lineage="query-component"):
    """Use the existing actual fictional source/AST/signature admission fixture."""
    import importlib.util
    from pathlib import Path
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as bound
    path = Path(__file__).with_name("test_legal_span_consumer_binding.py")
    spec = importlib.util.spec_from_file_location("_rich_context_reviewed_consumer_fixture", path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    admission_helper, admission, case, rows, options = helper.reviewed_public_consumer_case()
    queries = [{"id": "unseen-query", "source_text": "Unseen lighthouse operators may archive weather messages after a storm."}]
    manifest = helper.splits.LegalIRSplitManifest(
        examples=tuple(helper.splits.LegalIRSplitExample.from_sample({"sample_id": r["id"], "text": r["source_text"],
            "statute_family": query_family if r in queries else "example-family",
            "lineage_group_id": query_lineage if r in queries else "training-component"}) for r in [*rows, *queries]),
        assignments={r["id"]: "holdout" if r in queries else "train" for r in [*rows, *queries]},
        config_digest=helper.source_digest("fictional rich context split policy"))
    options["split_manifest"] = manifest.to_dict()
    options["expected_split_manifest_sha256"] = helper.digest(options["split_manifest"])
    binding = bound.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)
    norm = next(r for r in rows if any(u["use_unit_id"] == r["unit_id"] for u in r["canonical_ir"]["definition_uses"]))
    selections = [{"id": queries[0]["id"], "source_sha256": helper.source_digest(queries[0]["source_text"]),
                   "index_sha256": helper.digest(rows), "retrieved_ids": [norm["id"]]}]
    return helper, admission_helper, admission, case, rows, options, binding, queries, selections


def _consume_rich(case, callback, *, queries=None, selections=None, **overrides):
    helper, _, _, _, rows, options, binding, original_queries, original_selections = case
    queries = original_queries if queries is None else queries
    selections = original_selections if selections is None else selections
    return structured.consume_reviewed_contexts_v2(binding, rows,
        **{k: options[k] for k in ("split_manifest", "admission_inputs", "exposure_records")},
        query_rows=queries, retrieval_rows=selections,
        expected_query_rows_sha256=helper.digest(queries), expected_retrieval_rows_sha256=helper.digest(selections),
        consumer=callback, **overrides)


def test_rich_context_retains_full_reviewed_ast_sources_roles_and_governing_definition():
    case = _reviewed_rich_case()
    helper, _, _, _, rows, _, _, queries, selected = case
    original = copy.deepcopy(rows)
    payload = _consume_rich(case, lambda p: p)
    context = payload["rows"][0]
    exposed = {r["id"]: r for r in context["examples"]}
    norm = next(r for r in rows if r["id"] == selected[0]["retrieved_ids"][0])
    definition_id = norm["canonical_ir"]["definition_uses"][0]["definition_unit_id"]
    definition = next(r for r in rows if r["unit_id"] == definition_id)
    assert set(exposed) == {norm["id"], definition["id"]}
    for row in (norm, definition):
        assert exposed[row["id"]]["source_text"] == row["source_text"]
        assert exposed[row["id"]]["canonical_ir"] == row["canonical_ir"]
        assert exposed[row["id"]]["source_link"] == row["canonical_ir"]["source_binding"]
    assert context["source_text"] == queries[0]["source_text"]
    assert payload["binding_receipt"]["training_mask"] == payload["binding_receipt"]["evaluation_gold_mask"] == 0
    assert payload["retrieval_role"] == structured.REVIEWED_CONTEXT_ROLE
    for key in ("query_target_access", "inference_context_permission_verified", "ranking_authenticated",
                "legal_applicability_established", "training_executed", "proof_authority", "corpus_admitted"):
        assert payload[key] is False
    exposed[norm["id"]]["canonical_ir"].clear()
    assert rows == original


@pytest.mark.parametrize("field", ["canonical_ir", "target_hint", "reference", "source_spans", "formal_embedding"])
def test_rich_query_cannot_carry_a_reference_target(field):
    case = _reviewed_rich_case()
    queries = copy.deepcopy(case[-2])
    queries[0][field] = "hidden reference"
    calls = []
    with pytest.raises(ValueError):
        _consume_rich(case, calls.append, queries=queries)
    assert calls == []


@pytest.mark.parametrize("damage", ["unknown_neighbor", "duplicate_neighbor", "source_pin", "index_pin", "extra_authority"])
def test_rich_retrieval_cannot_replace_source_index_or_neighbor_population(damage):
    case = _reviewed_rich_case()
    selected = copy.deepcopy(case[-1])
    if damage == "unknown_neighbor": selected[0]["retrieved_ids"] = ["heldout-reference"]
    elif damage == "duplicate_neighbor": selected[0]["retrieved_ids"] *= 2
    elif damage == "source_pin": selected[0]["source_sha256"] = "0" * 64
    elif damage == "index_pin": selected[0]["index_sha256"] = "0" * 64
    else: selected[0]["proof_authority"] = True
    calls = []
    with pytest.raises(ValueError):
        _consume_rich(case, calls.append, selections=selected)
    assert calls == []


def test_rich_context_refuses_whole_dispatch_instead_of_truncating_ast_or_definition():
    case = _reviewed_rich_case()
    calls = []
    with pytest.raises(ValueError, match="truncation refused"):
        _consume_rich(case, calls.append, max_context_bytes=256)
    assert calls == []


def test_rich_context_replays_current_review_revocation_before_dispatch():
    case = _reviewed_rich_case()
    helper, admission_helper, admission, original, _, options, _, _, _ = case
    original["registry"]["keys"][0]["revoked_at_utc"] = admission_helper.EVALUATED
    original["registry"]["revocation_generation"] += 1
    admission_helper.reviewed_resign_v2(original)
    options["admission_inputs"] = helper.reviewed_public_admission_inputs(admission_helper, admission, original)
    calls = []
    with pytest.raises(ValueError):
        _consume_rich(case, calls.append)
    assert calls == []


def test_rich_context_requires_complete_permitted_governing_definition():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as bound
    original = list(_reviewed_rich_case())
    helper, _, _, _, rows, options, _, _, selected = original
    norm = next(r for r in rows if r["id"] == selected[0]["retrieved_ids"][0])
    definition_id = norm["canonical_ir"]["definition_uses"][0]["definition_unit_id"]
    subset = [r for r in rows if r["unit_id"] != definition_id]
    options = dict(options, expected_rows_sha256=helper.digest(subset),
        exposure_records=[e for e in options["exposure_records"] if e["id"] in {r["id"] for r in subset}])
    options["expected_exposure_sha256"] = helper.digest(options["exposure_records"])
    binding = bound.prepare_reviewed_source_span_consumer_binding_v2(subset, **options)
    selected = copy.deepcopy(selected)
    selected[0]["index_sha256"] = helper.digest(subset)
    original[4:7] = [subset, options, binding]
    calls = []
    with pytest.raises(ValueError, match="governing definition missing"):
        _consume_rich(tuple(original), calls.append, selections=selected)
    assert calls == []


@pytest.mark.parametrize("query_family,query_lineage", [
    ("example-family", "query-component"), ("query-family", "training-component"),
])
def test_rich_context_excludes_shared_family_and_dependency_lineage(query_family, query_lineage):
    case = _reviewed_rich_case(query_family=query_family, query_lineage=query_lineage)
    calls = []
    with pytest.raises(ValueError):
        _consume_rich(case, calls.append)
    assert calls == []


@pytest.fixture(scope="module")
def rich_fixture_owners():
    """Reuse the existing reviewed-pair and current-index fictional fixtures."""
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    modules = []
    for name, path in (("_rich_pair_fixtures", root / "unit/logic/formalization/autoencoder/test_alignment_relation_mask_handoff.py"),
                       ("_rich_query_fixtures", Path(__file__).with_name("test_legal_joint_retrieval.py"))):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return tuple(modules)


def _rich_consumer_inputs(owner, case):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    _, admission, _ = structured._rich_owners()
    args, inputs = owner.reviewed_mask_arguments_v2(case)
    current = structured._rich_owners()[0].compile_reviewed_train_relation_masks_v2(*args, **inputs)
    indexed = {}
    for endpoint in current["formal_endpoints"]:
        indexed.setdefault(endpoint["admission_id"], {}).setdefault(endpoint["unit_id"], endpoint)
    result = {}
    for identity, endpoints in indexed.items():
        entry = inputs["preparation_inputs"]["endpoint_admissions"][identity]
        report, _ = structured._rich_current_assessment(identity, entry, inputs, admission)
        units = {unit["unit_id"]: unit for unit in report["units"]}
        rows = [{"id": endpoint["split_sample_id"], "unit_id": unit_id,
            "source_text": units[unit_id]["source_text"], "canonical_ir": copy.deepcopy(units[unit_id]["canonical_ir"])}
            for unit_id, endpoint in endpoints.items()]
        exposures = [{"id": row["id"], "source_text_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
            "canonical_ir_sha256": consumer._guard(row["canonical_ir"]).sha256,
            "target_exposure": "declared_supervised_training",
            "provenance_ref": "fictional fixture only: reviewed TRAIN example custody; no decoder-context permission"}
            for row in rows]
        result[identity] = {"rows": rows, "expected_rows_sha256": consumer._guard(rows).sha256,
            "exposure_records": exposures, "expected_exposure_sha256": consumer._guard(exposures).sha256,
            "allow_fictional_fixture": True}
    return result


@pytest.fixture(scope="module")
def rich_case(rich_fixture_owners):
    torch = pytest.importorskip("torch")
    owner, query_owner = rich_fixture_owners
    original = owner.fixtures.reviewed_pair_fixture_v2()
    case, query, lane, expected = query_owner._reviewed_structural_query_fixture(owner, original)
    args, inputs = owner.reviewed_mask_arguments_v2(case)
    original_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        trained = structured.joint.train_reviewed_retriever(*args, **inputs, steps=1, joint_dimension=8)
    finally:
        torch.set_num_threads(original_threads)
    checkpoint = trained["checkpoint"]
    model = structured.joint.ReviewedLegalJointRetriever(checkpoint,
        expected_checkpoint_sha256=structured.joint.checkpoint_digest(checkpoint))
    return owner, case, query, lane, expected, model


def _rich_call_arguments(value):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    owner, case, query, lane, expected, model = value
    args, inputs = owner.reviewed_mask_arguments_v2(case)
    excluded = {query["id"]: []}
    inputs.update(query_source_lane=lane, expected_query_lane_bindings=expected,
        expected_query_split=splits.HOLDOUT_SPLIT, forbidden_reference_formal_sha256s=excluded,
        expected_forbidden_reference_sha256=structured.joint.checkpoint_digest(excluded), top_k=2, mode="raw")
    return (model, [query], *args), {"retrieval_inputs": inputs,
        "example_consumer_inputs": _rich_consumer_inputs(owner, case)}


@pytest.fixture(scope="module")
def rich_case_arguments(rich_case):
    # Prepare the unchanged authored input population once. Product admission
    # and revocation replay still execute independently in every tested call.
    return _rich_call_arguments(rich_case)


@pytest.fixture
def rich_call_arguments(rich_case_arguments):
    args, inputs = rich_case_arguments
    # The model was already module-scoped; every mutable query, review input
    # and offered example remains isolated for each adversarial case.
    return (args[0], *copy.deepcopy(args[1:])), copy.deepcopy(inputs)


def test_rich_candidate_retains_complete_typed_ast_roles_source_edition_and_review_refs(rich_call_arguments):
    args, inputs = rich_call_arguments
    before = copy.deepcopy(inputs)
    result = structured.build_reviewed_rich_context_candidates(*args, **inputs)
    assert inputs == before and result["status"] == "candidate_only"
    assert result["candidate_count"] == 1 and not result["abstention_count"]
    assert result["profile"] == structured.RICH_PROFILE
    assert not result["decoder_context_admitted"] and not result["arbitrary_context_permission"]
    assert result["decoder_integration_status"] == "unavailable_P5_context_profile_remains_none"
    examples = result["rows"][0]["examples"]
    assert examples and result["rows"][0]["distinct_source_unit_count"] == len(examples)
    for example in examples:
        assert bytes.fromhex(example["source_utf8_hex"]).decode("utf-8") == example["source_text"]
        assert hashlib.sha256(bytes.fromhex(example["source_utf8_hex"])).hexdigest() == example["source_sha256"]
        identity = example["admission_id"]
        original_row = next(row for row in inputs["example_consumer_inputs"][identity]["rows"]
                            if row["unit_id"] == example["unit_id"])
        assert example["canonical_ir"] == original_row["canonical_ir"]
        assert example["unit_kind"] in ("norm", "definition")
        assert example["argument_roles"] == example["canonical_ir"]["argument_roles"]
        assert example["canonical_ir"]["typed_expression"]["root"]
        assert example["canonical_ir"]["definition_uses"]
        assert example["canonical_ir"]["governing_context"]["governing_edition"] == "fictional-edition-1"
        assert example["source_occurrence"]["record_cid"] == example["canonical_ir"]["source_binding"]["occurrence_cid"]
        assert example["source_version"]["record_cid"] == example["canonical_ir"]["source_binding"]["source_version_cid"]
        assert example["TRAIN_consumer_custody"]["status"] == "ready"
        assert len(example["TRAIN_consumer_receipt_sha256"]) == 64
        assert "TRAIN_consumer_receipt" not in example
        assert example["training_mask"] == example["evaluation_gold_mask"] == 0
        assert "raw_bytes" not in example and "embedding" not in example
    assert not result["governing_definition_bodies_supplied"] and not result["proof_dependency_bodies_supplied"]
    assert not any(result[key] for key in ("proof_authority", "kernel_checked", "corpus_admitted", "training_executed"))


def test_rich_candidate_replay_validates_current_rows_not_just_digest_or_flags(rich_call_arguments):
    args, inputs = rich_call_arguments
    candidate = structured.build_reviewed_rich_context_candidates(*args, **inputs)
    replay = structured.validate_reviewed_rich_context_candidates(candidate, *args,
        expected_candidate_sha256=structured.joint.checkpoint_digest(candidate), **inputs)
    assert replay == candidate and replay is not candidate


@pytest.mark.parametrize("damage", ["actor_role", "typed_ast", "source_bytes", "source_revision", "definition_use", "query_source", "decoder_authority"])
def test_rich_candidate_forged_content_fails_independent_full_replay(rich_call_arguments, damage):
    args, inputs = rich_call_arguments
    candidate = structured.build_reviewed_rich_context_candidates(*args, **inputs)
    example = candidate["rows"][0]["examples"][0]
    if damage == "actor_role": example["argument_roles"][0]["roles"][0] = "unreviewed_actor"
    elif damage == "typed_ast": example["canonical_ir"]["typed_expression"]["root"]["kind"] = "false"
    elif damage == "source_bytes": example["source_utf8_hex"] = b"Different source".hex()
    elif damage == "source_revision": example["document_revision"] = "fictional-new-unreviewed-revision"
    elif damage == "definition_use": example["canonical_ir"]["definition_uses"] = []
    elif damage == "query_source": candidate["rows"][0]["source_sha256"] = "f" * 64
    else: candidate["decoder_context_admitted"] = True
    with pytest.raises(ValueError, match="fresh replay"):
        structured.validate_reviewed_rich_context_candidates(candidate, *args,
            expected_candidate_sha256=structured.joint.checkpoint_digest(candidate), **inputs)


@pytest.mark.parametrize("damage", ["unknown_exposure", "missing_training_unit", "foreign_unit", "changed_typed_target", "fixture_without_opt_in"])
def test_rich_candidate_requires_existing_complete_TRAIN_consumer_custody(rich_call_arguments, damage):
    args, inputs = rich_call_arguments
    offered = copy.deepcopy(inputs["example_consumer_inputs"])
    entry = next(iter(offered.values()))
    if damage == "unknown_exposure":
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
        entry["exposure_records"][0]["target_exposure"] = "unknown"
        entry["expected_exposure_sha256"] = consumer._guard(entry["exposure_records"]).sha256
    elif damage == "missing_training_unit": entry["rows"] = []
    elif damage == "foreign_unit": entry["rows"][0]["unit_id"] = "query:gold-target"
    elif damage == "changed_typed_target": entry["rows"][0]["canonical_ir"]["typed_expression"]["root"]["kind"] = "false"
    else: entry["allow_fictional_fixture"] = False
    inputs["example_consumer_inputs"] = offered
    if damage in ("unknown_exposure", "fixture_without_opt_in"):
        result = structured.build_reviewed_rich_context_candidates(*args, **inputs)
        assert result["status"] == "abstained_example_custody_unavailable"
        assert not result["rows"] and not result["model_forward_executed"]
    else:
        with pytest.raises(ValueError):
            structured.build_reviewed_rich_context_candidates(*args, **inputs)


def test_rich_candidate_current_revocation_abstains_without_forwarding_historical_examples(rich_case):
    # Reuse the actual fixture trust-root rotation/resigning owner.
    owner, original, query, lane, expected, model = rich_case
    case = owner.reviewed_pair_clone_v2(original)
    case["registry"]["keys"][0]["revoked_at_utc"] = case["at_time_utc"]
    owner.reviewed_pair_resign_v2(case)
    args, inputs = _rich_call_arguments((owner, case, query, lane, expected, model))
    result = structured.build_reviewed_rich_context_candidates(*args, **inputs)
    assert result["status"] == "abstained_current_index_unavailable"
    assert not result["rows"] and not result["model_forward_executed"]


def test_rich_candidate_opaque_profile_commitments_confer_no_permission_or_compatibility(rich_call_arguments):
    args, inputs = rich_call_arguments
    identity = {"decoder_profile_sha256": "a" * 64, "kernel_profile_sha256": "b" * 64}
    result = structured.build_reviewed_rich_context_candidates(*args, **inputs,
        context_profile_identity=identity, expected_context_profile_identity_sha256=structured.joint.checkpoint_digest(identity))
    assert result["context_profile_identity"] == identity
    assert "no_permission_or_compatibility_claim" in result["context_profile_identity_scope"]
    assert not result["kernel_checked"] and not result["decoder_context_admitted"]
    with pytest.raises(ValueError, match="only opaque"):
        structured.build_reviewed_rich_context_candidates(*args, **inputs,
            context_profile_identity={**identity, "expected_proposition": "secret target"},
            expected_context_profile_identity_sha256="c" * 64)


def test_rich_candidate_opaque_reference_aliases_are_excluded_before_full_targets_are_forwarded(rich_call_arguments):
    args, inputs = rich_call_arguments
    current = structured._rich_owners()[0].compile_reviewed_train_relation_masks_v2(*args[2:],
        **{key: value for key, value in inputs["retrieval_inputs"].items() if key in (
            "expected_preparation_sha256", "preparation_inputs", "expected_registry_sha256", "expected_policy_sha256",
            "expected_reviews_sha256", "at_time_utc", "observed_artifact_sha256s", "observed_pins", "evidence_artifacts", "current_endpoint_observations")})
    excluded = {args[1][0]["id"]: [current["formal_endpoints"][0]["formal_view_sha256"]]}
    inputs["retrieval_inputs"].update(forbidden_reference_formal_sha256s=excluded,
        expected_forbidden_reference_sha256=structured.joint.checkpoint_digest(excluded), top_k=1)
    result = structured.build_reviewed_rich_context_candidates(*args, **inputs)
    for example in result["rows"][0]["examples"]:
        assert all(ref["formal_view_sha256"] not in excluded[args[1][0]["id"]]
                   for ref in example["selected_endpoint_refs"])


def test_rich_candidate_keeps_histogram_and_dense_vector_contract_separate(rich_call_arguments):
    args, inputs = rich_call_arguments
    result = structured.build_reviewed_rich_context_candidates(*args, **inputs)
    assert result["schema"] != structured.SCHEMA
    assert structured.DIMENSION == 384 and len(structured.PROFILE_CLASSES) == 24
    assert "context" not in result["rows"][0] and "context_dimension" not in result
    with pytest.raises(ValueError):
        structured._context_distribution(result)


def test_rich_candidate_alias_representations_do_not_duplicate_units_or_forward_sibling_definition_bodies(rich_call_arguments):
    args, inputs = rich_call_arguments
    inputs["retrieval_inputs"]["top_k"] = 3
    result = structured.build_reviewed_rich_context_candidates(*args, **inputs)
    row = result["rows"][0]
    assert row["selected_representation_count"] == 3
    assert row["distinct_source_unit_count"] == len(row["examples"]) == 2
    assert len({(item["admission_id"], item["unit_id"]) for item in row["examples"]}) == 2
    assert sum(len(item["selected_endpoint_refs"]) for item in row["examples"]) == 3
    for item in row["examples"]:
        definition_ids = {use["definition_unit_id"] for use in item["canonical_ir"]["definition_uses"]}
        assert item["unit_id"] not in definition_ids
        assert "definition_bodies" not in item and "component_units" not in item


@pytest.mark.parametrize("target", ["selected", "unselected_sibling_or_reference"])
def test_rich_candidate_never_forwards_exposure_provenance_prose(rich_call_arguments, target):
    import json
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    args, inputs = rich_call_arguments
    inputs["retrieval_inputs"]["top_k"] = 1
    baseline = structured.build_reviewed_rich_context_candidates(*args, **inputs)
    selected = {(item["admission_id"], item["unit_id"])
                for item in baseline["rows"][0]["examples"]}
    offered = copy.deepcopy(inputs["example_consumer_inputs"])
    found = False
    sentinel = "Fictional hidden sibling/reference target body: never forward this exposure-note prose."
    for admission_id, entry in offered.items():
        for row, exposure in zip(entry["rows"], entry["exposure_records"], strict=True):
            if ((admission_id, row["unit_id"]) in selected) == (target == "selected"):
                exposure["provenance_ref"] = sentinel
                found = True
        entry["expected_exposure_sha256"] = consumer._guard(entry["exposure_records"]).sha256
    assert found
    inputs["example_consumer_inputs"] = offered
    candidate = structured.build_reviewed_rich_context_candidates(*args, **inputs)
    assert candidate["candidate_count"] == 1 and sentinel not in json.dumps(candidate, sort_keys=True)
    assert candidate["rows"][0]["examples"][0]["canonical_ir"] == baseline["rows"][0]["examples"][0]["canonical_ir"]
    for item in candidate["rows"][0]["examples"]:
        assert set(item["TRAIN_consumer_custody"]) == {
            "schema", "profile", "operation", "status", "scope", "row_identity_sha256", "exposure_kind", "provenance_ref_sha256"}


def test_rich_candidate_bounds_complete_output_before_selected_body_expansion(rich_call_arguments, monkeypatch):
    args, inputs = rich_call_arguments
    inputs["retrieval_inputs"]["top_k"] = 1
    one = structured.build_reviewed_rich_context_candidates(*args, **inputs)
    inputs["retrieval_inputs"]["top_k"] = 3
    three = structured.build_reviewed_rich_context_candidates(*args, **inputs)
    one_size, three_size = (len(structured.joint._raw(value)) for value in (one, three))
    assert three_size > one_size and three["rows"][0]["distinct_source_unit_count"] == 2
    before = copy.deepcopy(inputs)
    # Existing small fictional units exercise the expansion limit; no large
    # allocation, output cropping, shortened AST or dropped source clause.
    monkeypatch.setattr(structured, "RICH_MAX_BYTES", (one_size + three_size) // 2)
    with pytest.raises(ValueError, match="candidate byte budget exceeded before selected copy"):
        structured.build_reviewed_rich_context_candidates(*args, **inputs)
    assert inputs == before


def test_rich_candidate_complete_final_wire_bound_is_independent_of_precopy_accounting(rich_call_arguments, monkeypatch):
    args, inputs = rich_call_arguments
    baseline = structured.build_reviewed_rich_context_candidates(*args, **inputs)
    # An independently enforced final limit still refuses if the preparatory
    # accounting path is impaired. The full result is never returned truncated.
    monkeypatch.setattr(structured, "_rich_charge_candidate", lambda *args, **kwargs: None)
    monkeypatch.setattr(structured, "RICH_MAX_BYTES", len(structured.joint._raw(baseline)) - 1)
    with pytest.raises(ValueError, match="candidate byte budget exceeded"):
        structured.build_reviewed_rich_context_candidates(*args, **inputs)
