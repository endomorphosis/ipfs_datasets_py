"""Engineering argument-custody tests; producer seams are explicitly simulated.

The separate native-context suites exercise original-artifact joins. These
fixtures test the consumer boundary without pretending to be native inference.
"""
from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as base
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_context_binding as owner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits


def digest(value):
    return base._guard(value).sha256


def case(stage="raw384", operation="training"):
    dimension = 768 if stage == "native768" else 384
    rows = [{"id": "fictional-agency", "source_text": "The agency shall disclose records.",
        "canonical_ir": {"rules": [{"modality": "O", "actor": "agency", "action": "disclose",
            "object": "records", "conditions": [], "exceptions": [], "temporal": []}]}},
        {"id": "fictional-board", "source_text": "The board may retain notices.",
        "canonical_ir": {"rules": [{"modality": "P", "actor": "board", "action": "retain",
            "object": "notices", "conditions": [], "exceptions": [], "temporal": []}]}}]
    manifest = splits.LegalIRSplitManifest(
        examples=tuple(splits.LegalIRSplitExample.from_sample({"sample_id": r["id"], "text": r["source_text"]})
                       for r in rows), assignments={r["id"]: "train" if operation == "training" else "validation"
                                                   for r in rows}, config_digest="a" * 64).to_dict()
    eligibility, exposure, contexts = [], [], []
    for index, row in enumerate(rows):
        source_sha = hashlib.sha256(row["source_text"].encode()).hexdigest()
        exact = {"id": row["id"], "source_text_sha256": source_sha,
                 "canonical_ir_sha256": digest(row["canonical_ir"])}
        eligibility.append({**exact, "target_origin": "authored_engineering_fixture", "status": "eligible",
            "allowed_operations": [operation], "reason": "Fictional custody test; no legal gold."})
        exposure.append({**exact, "target_exposure": "declared_supervised_training" if operation == "training"
            else "declared_validation_scoring", "provenance_ref": "fixture:fictional"})
        contexts.append({"id": row["id"], "source_sha256": source_sha,
                         "context": [float(index + 1) / dimension] * dimension})
    evidence = {"stage": stage, "fixture_only": True}
    return rows, dict(expected_rows_sha256=digest(rows), split_manifest=manifest,
        expected_split_manifest_sha256=digest(manifest), eligibility_records=eligibility,
        expected_eligibility_sha256=digest(eligibility), exposure_records=exposure,
        expected_exposure_sha256=digest(exposure), operation=operation, stage=stage,
        contexts=contexts, expected_contexts_sha256=digest(contexts), context_evidence=evidence,
        expected_context_evidence_sha256=digest(evidence))


def validation(options):
    return {key: options[key] for key in ("split_manifest", "eligibility_records", "exposure_records",
                                        "contexts", "context_evidence")}


def simulated_producer(monkeypatch, rows, options):
    # Independently retained fixture copies; changing/re-hashing offered inputs
    # cannot change what the original producer reports at this explicit seam.
    expected_sources = [{"id": r["id"], "source_text": r["source_text"]} for r in rows]
    original_evidence = deepcopy(options["context_evidence"])
    result = {"contexts": deepcopy(options["contexts"]), "representation": {
        "dimension": len(options["contexts"][0]["context"]),
        "representation_id": "fixture:" + options["stage"], "producer_sha256": "b" * 64},
        "inspection": {"fixture_only": True, "source_semantics_verified": False}}
    if options["stage"] == "native768":
        result["provenance"] = {"selected_source_splits": [
            {"id": c["id"], "source_sha256": c["source_sha256"],
             "splits": ["train" if options["operation"] == "training" else "tuning"]}
            for c in options["contexts"]]}
    calls = []

    def verify(stage, sources, evidence, resolver):
        assert sources == expected_sources
        assert all(set(r) == {"id", "source_text"} for r in sources)
        if evidence != original_evidence or stage != options["stage"]:
            raise owner.SourceSpanContextBindingError("fixture original producer binding differs")
        calls.append(deepcopy(sources))
        return deepcopy(result)

    monkeypatch.setattr(owner, "_verify", verify)
    return result, calls


@pytest.mark.parametrize("stage", owner.STAGES)
@pytest.mark.parametrize("operation", ["training", "hparam_selection"])
def test_exact_whole_batch_is_detached_and_no_authority_is_promoted(monkeypatch, stage, operation):
    rows, options = case(stage, operation)
    original = deepcopy((rows, options))
    _, verification_calls = simulated_producer(monkeypatch, rows, options)
    binding = owner.prepare_source_span_context_binding(rows, **options)
    receipt = binding.receipt()
    assert receipt["status"] == "ready" and receipt["row_count"] == 2
    assert receipt["ready_row_count"] == 2 and receipt["rows_discarded"] == 0
    assert receipt["latent_dimension"] == (768 if stage == "native768" else 384)
    assert receipt["context_stage"] == stage
    for key in ("semantic_authority", "training_gold_authority", "evaluation_gold_authority",
                "training_executed", "context_computation_reexecuted", "runtime_cryptographically_attested"):
        assert receipt[key] is False
    calls = []
    marker = object()

    def consume(received):
        calls.append(deepcopy(received))
        received[0]["latent"].clear()
        received.reverse()
        return marker

    assert owner.consume_source_span_context_binding(binding, rows, **validation(options), consumer=consume) is marker
    expected = [{**r, "latent": c["context"]} for r, c in zip(rows, options["contexts"])]
    assert calls == [expected]
    assert len(verification_calls) == 2  # Preparation and consumption both reopen evidence.
    receipt.clear()
    assert binding.receipt()["status"] == "ready"
    assert (rows, options) == original


@pytest.mark.parametrize("damage", ["vector", "swap_vectors", "order", "missing", "extra", "id", "source",
                                      "dimension", "bool", "nonfinite", "overflow"])
def test_rehashed_bad_contexts_never_reach_callback(monkeypatch, damage):
    rows, options = case()
    simulated_producer(monkeypatch, rows, options)
    contexts = options["contexts"]
    if damage == "vector": contexts[0]["context"][0] += .25
    elif damage == "swap_vectors": contexts[0]["context"], contexts[1]["context"] = contexts[1]["context"], contexts[0]["context"]
    elif damage == "order": contexts.reverse()
    elif damage == "missing": contexts.pop()
    elif damage == "extra": contexts.append(deepcopy(contexts[0]))
    elif damage == "id": contexts[0]["id"] = "other"
    elif damage == "source": contexts[0]["source_sha256"] = "f" * 64
    elif damage == "dimension": contexts[0]["context"].pop()
    elif damage == "bool": contexts[0]["context"][0] = True
    elif damage == "nonfinite": contexts[0]["context"][0] = float("nan")
    else: contexts[0]["context"][0] = 1e100
    if damage != "nonfinite": options["expected_contexts_sha256"] = digest(contexts)
    with pytest.raises(owner.SourceSpanContextBindingError):
        owner.prepare_source_span_context_binding(rows, **options)


@pytest.mark.parametrize("damage", ["contexts", "evidence", "source", "target", "eligibility", "split"])
def test_retained_binding_rejects_argument_mutation(monkeypatch, damage):
    rows, options = case()
    simulated_producer(monkeypatch, rows, options)
    binding = owner.prepare_source_span_context_binding(rows, **options)
    if damage == "contexts": options["contexts"][0]["context"][0] = .5
    elif damage == "evidence": options["context_evidence"]["stage"] = "trained384"
    elif damage == "source": rows[0]["source_text"] += " changed"
    elif damage == "target": rows[0]["canonical_ir"]["rules"][0]["modality"] = "F"
    elif damage == "eligibility": options["eligibility_records"][0]["status"] = "ineligible"
    else: options["split_manifest"]["assignments"][rows[0]["id"]] = "holdout"
    calls = []
    with pytest.raises(owner.SourceSpanContextBindingError):
        owner.consume_source_span_context_binding(binding, rows, **validation(options), consumer=calls.append)
    assert calls == []


@pytest.mark.parametrize("reason", ["ineligible", "holdout", "reviewed_origin"])
def test_native_context_does_not_bypass_existing_policy(monkeypatch, reason):
    rows, options = case()
    simulated_producer(monkeypatch, rows, options)
    if reason == "holdout":
        manifest = splits.LegalIRSplitManifest.from_mapping(options["split_manifest"])
        manifest.assignments[rows[0]["id"]] = "holdout"
        options["split_manifest"] = manifest.to_dict()
        options["expected_split_manifest_sha256"] = digest(options["split_manifest"])
    else:
        options["eligibility_records"][0]["status" if reason == "ineligible" else "target_origin"] = reason
        options["expected_eligibility_sha256"] = digest(options["eligibility_records"])
    if reason == "reviewed_origin":
        with pytest.raises(owner.SourceSpanContextBindingError, match="target_origin"):
            owner.prepare_source_span_context_binding(rows, **options)
        return
    binding = owner.prepare_source_span_context_binding(rows, **options)
    assert binding.receipt()["row_count"] == 2 and binding.receipt()["rows_discarded"] == 0
    calls = []
    with pytest.raises(owner.SourceSpanContextBindingError) as error:
        owner.consume_source_span_context_binding(binding, rows, **validation(options), consumer=calls.append)
    assert error.value.receipt["status"] == "blocked" and calls == []


def test_changed_original_producer_result_is_rejected_at_consumption(monkeypatch):
    rows, options = case()
    result, _ = simulated_producer(monkeypatch, rows, options)
    binding = owner.prepare_source_span_context_binding(rows, **options)
    result["contexts"][0]["context"][0] = .5
    with pytest.raises(owner.SourceSpanContextBindingError, match="verification"):
        owner.consume_source_span_context_binding(binding, rows, **validation(options), consumer=lambda _: pytest.fail("called"))


def test_resolver_or_verifier_cannot_mutate_originals_during_validation(monkeypatch):
    rows, options = case()
    simulated_producer(monkeypatch, rows, options)
    binding = owner.prepare_source_span_context_binding(rows, **options)
    previous = owner._verify

    def malicious(*args):
        result = previous(*args)
        options["contexts"][0]["context"][0] = .75
        return result

    monkeypatch.setattr(owner, "_verify", malicious)
    with pytest.raises(owner.SourceSpanContextBindingError, match="contexts"):
        owner.consume_source_span_context_binding(binding, rows, **validation(options), consumer=lambda _: pytest.fail("called"))


def test_callback_exception_is_not_retried(monkeypatch):
    rows, options = case()
    simulated_producer(monkeypatch, rows, options)
    binding = owner.prepare_source_span_context_binding(rows, **options)
    calls = []
    def fail(received):
        calls.append(received)
        raise RuntimeError("consumer failure")
    with pytest.raises(RuntimeError, match="consumer failure"):
        owner.consume_source_span_context_binding(binding, rows, **validation(options), consumer=fail)
    assert len(calls) == 1


@pytest.mark.parametrize("field", ["expected_contexts_sha256", "expected_context_evidence_sha256"])
def test_independent_expected_context_hash_required(monkeypatch, field):
    rows, options = case()
    simulated_producer(monkeypatch, rows, options)
    options[field] = "0" * 64
    with pytest.raises(owner.SourceSpanContextBindingError):
        owner.prepare_source_span_context_binding(rows, **options)


def test_closed_context_schema_rejects_target_fields(monkeypatch):
    rows, options = case()
    simulated_producer(monkeypatch, rows, options)
    options["contexts"][0]["canonical_ir"] = rows[0]["canonical_ir"]
    options["expected_contexts_sha256"] = digest(options["contexts"])
    with pytest.raises(owner.SourceSpanContextBindingError, match="closed"):
        owner.prepare_source_span_context_binding(rows, **options)


@pytest.mark.parametrize("original", [["challenge"], ["oov"], ["tuning"], ["train", "oov"]])
def test_original_producer_cohort_cannot_be_relabeled_as_training(monkeypatch, original):
    rows, options = case("native768")
    result, _ = simulated_producer(monkeypatch, rows, options)
    result["provenance"]["selected_source_splits"][0]["splits"] = original
    binding = owner.prepare_source_span_context_binding(rows, **options)
    receipt = binding.receipt()
    assert receipt["status"] == "blocked" and receipt["blocked_row_count"] == 1
    assert receipt["rows_discarded"] == 0 and receipt["row_count"] == 2
    assert receipt["rows"][0]["blockers"][0]["reason"] == "original_native_source_split_disallows_operation"
    calls = []
    with pytest.raises(owner.SourceSpanContextBindingError):
        owner.consume_source_span_context_binding(binding, rows, **validation(options), consumer=calls.append)
    assert not calls
