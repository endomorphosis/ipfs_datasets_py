from __future__ import annotations

import dataclasses
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_evaluation_artifacts import (
    BASELINE_METRIC_NODE,
    COMPILATION_NODE,
    EMBEDDING_NODE,
    LEGAL_IR_ARTIFACT_GRAPH_KEY,
    LEGAL_IR_ARTIFACT_GRAPH_SCHEMA_VERSION,
    LEGAL_IR_ARTIFACT_NODE_ORDER,
    LegalIRArtifactGraphBuildPlan,
    LegalIRArtifactGraphBundle,
    LegalIRArtifactGraphProvenanceError,
    LegalIRArtifactGraphStore,
    LegalIRArtifactNode,
    legal_ir_evaluation_artifact_from_compilation,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_evaluation_cache import (
    LegalIREvaluationCache,
    LegalIREvaluationCacheKey,
)


def _key(*, state_hash: str = "state-a") -> LegalIREvaluationCacheKey:
    return LegalIREvaluationCacheKey(
        sample_hash="sample-sha",
        compiler_commit="compiler-sha",
        state_hash=state_hash,
        metric_schema="metric-schema-a",
        config_hash="config-sha",
    )


def _sample() -> SimpleNamespace:
    return SimpleNamespace(
        sample_id="sample-1",
        text="The agency shall provide notice within 30 days.",
        embedding_vector=[0.25, 0.75],
        embedding_model="unit-embedding",
        citation="1 USC 1",
        source="unit",
    )


def _compiled(loss: float = 0.2) -> SimpleNamespace:
    return SimpleNamespace(
        decoded_modal_text="O(provide_notice)",
        frame_candidates=["frame"],
        kg_triples=[],
        losses={
            "cross_entropy_loss": loss,
            "cosine_similarity": 0.8,
            "symbolic_validity_penalty": 0.0,
        },
        metadata={
            "legal_ir_view_families": ["deontic"],
            "llm_call_count": 0,
        },
        modal_ir=SimpleNamespace(formulas=["formula"]),
    )


def _counted_plan(counters: dict[str, int], *, sleep: float = 0.0) -> LegalIRArtifactGraphBuildPlan:
    sample = _sample()

    def bump(name: str):
        counters[name] = counters.get(name, 0) + 1

    def compile_result() -> SimpleNamespace:
        bump("compile")
        if sleep:
            time.sleep(sleep)
        return _compiled()

    return LegalIRArtifactGraphBuildPlan(
        sample=sample,
        normalize=lambda item: bump("normalize") or item.text.lower(),
        tokenize=lambda text: bump("tokenize") or text.split(),
        embed=lambda item: bump("embed") or item.embedding_vector,
        compile=compile_result,
        view_contracts=lambda _result, _item: (
            bump("view_contract")
            or {
                "contract_count": 1,
                "contract_ids": ["legal-ir-view/deontic/v1"],
                "registry_version": "unit-registry",
            }
        ),
        obligations=lambda _result, _item: (
            bump("obligation")
            or {
                "obligation_count": 1,
                "obligation_ids": ["obligation-1"],
                "obligations": [{"obligation_id": "obligation-1"}],
            }
        ),
        baseline_metrics=lambda result, _item: bump("baseline_metric") or dict(result.losses),
        producer_namespace="unit-test",
    )


def test_graph_materializes_every_required_node_once_and_reuses_across_consumers(
    tmp_path,
) -> None:
    cache = LegalIREvaluationCache(tmp_path / "cache")
    store = LegalIRArtifactGraphStore(cache)
    counters: dict[str, int] = {}
    roles = (
        "unguided",
        "guided",
        "train",
        "validation",
        "hammer",
        "leanstral",
        "promotion",
    )

    first = store.get_or_materialize(
        _key(),
        _counted_plan(counters),
        role=roles[0],
        consumers=roles,
    )
    for role in roles[1:]:
        reused = store.get_or_materialize(
            _key(),
            _counted_plan(counters),
            role=role,
            consumers=(role,),
        )
        assert reused.graph_digest == first.graph_digest

    assert tuple(first.nodes) == LEGAL_IR_ARTIFACT_NODE_ORDER
    assert first.nodes[COMPILATION_NODE].dependencies == ("tokenization",)
    assert first.nodes[EMBEDDING_NODE].payload["embedding"] == (0.25, 0.75)
    assert first.nodes[BASELINE_METRIC_NODE].payload["metrics"][
        "cross_entropy_loss"
    ] == pytest.approx(0.2)
    assert counters == {
        "baseline_metric": 1,
        "compile": 1,
        "embed": 1,
        "normalize": 1,
        "obligation": 1,
        "tokenize": 1,
        "view_contract": 1,
    }

    summary = store.summary()
    assert summary["computations"] == 1
    assert summary["avoided_graph_materializations"] == len(roles) - 1
    assert summary["avoided_node_materializations"] == (len(roles) - 1) * len(
        LEGAL_IR_ARTIFACT_NODE_ORDER
    )
    assert summary["consumer_hits"]["hammer"] >= 1
    assert summary["saved_wall_time_seconds"] >= 0.0

    fresh_store = LegalIRArtifactGraphStore(LegalIREvaluationCache(tmp_path / "cache"))
    from_disk = fresh_store.get_or_materialize(
        _key(),
        _counted_plan(counters),
        role="validation",
        consumers=("validation",),
    )
    assert from_disk.graph_digest == first.graph_digest
    assert fresh_store.summary()["cache_hits"] == 1
    assert counters["compile"] == 1


def test_concurrent_misses_are_single_flighted(tmp_path) -> None:
    store = LegalIRArtifactGraphStore(LegalIREvaluationCache(tmp_path / "cache"))
    counters: dict[str, int] = {}
    started = threading.Event()
    lock = threading.Lock()

    def plan() -> LegalIRArtifactGraphBuildPlan:
        base = _counted_plan(counters)

        def compile_once() -> SimpleNamespace:
            with lock:
                counters["compile"] = counters.get("compile", 0) + 1
            started.set()
            time.sleep(0.08)
            return _compiled()

        return dataclasses.replace(base, compile=compile_once)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(
                store.get_or_materialize,
                _key(),
                plan(),
                role=f"consumer-{index}",
                consumers=(f"consumer-{index}",),
            )
            for index in range(8)
        ]
        assert started.wait(timeout=1.0)
        bundles = [future.result(timeout=2.0) for future in futures]

    assert len({bundle.graph_digest for bundle in bundles}) == 1
    assert counters["compile"] == 1
    assert store.summary()["coalesced_waiters"] == 7
    assert store.summary()["avoided_node_materializations"] == 7 * len(LEGAL_IR_ARTIFACT_NODE_ORDER)


def test_cache_provenance_rejects_cross_state_graphs_without_leakage(tmp_path) -> None:
    store = LegalIRArtifactGraphStore(LegalIREvaluationCache(tmp_path / "cache"))
    counters: dict[str, int] = {}
    state_a = store.get_or_materialize(_key(state_hash="state-a"), _counted_plan(counters))
    state_b = store.get_or_materialize(_key(state_hash="state-b"), _counted_plan(counters))

    assert state_a.complete_digest != state_b.complete_digest
    assert counters["compile"] == 2
    assert state_a.key.state_hash == "state-a"
    assert state_b.key.state_hash == "state-b"

    bad_nodes = dict(state_a.nodes)
    bad_nodes[COMPILATION_NODE] = LegalIRArtifactNode(
        kind=COMPILATION_NODE,
        key_digest=state_b.complete_digest,
        payload=state_a.nodes[COMPILATION_NODE].payload,
        dependencies=state_a.nodes[COMPILATION_NODE].dependencies,
    )
    with pytest.raises(LegalIRArtifactGraphProvenanceError, match="another complete digest"):
        LegalIRArtifactGraphBundle(key=state_a.key, nodes=bad_nodes)


def test_graph_round_trips_through_typed_evaluation_artifact_and_detects_tampering() -> None:
    artifact = legal_ir_evaluation_artifact_from_compilation(
        _key(),
        sample=_sample(),
        compilation_result=_compiled(),
        compiler_payload={
            "decoded_modal_text": "O(provide_notice)",
            "losses": {"cross_entropy_loss": 0.2},
            "metadata": {"legal_ir_view_families": ["deontic"]},
            "modal_formula_count": 1,
            "frame_candidate_count": 1,
            "kg_triple_count": 0,
        },
        compilation_seconds=0.01,
        metadata={"consumers": ("hammer", "leanstral")},
    )
    assert artifact.compiler_artifact["losses"]["cross_entropy_loss"] == pytest.approx(0.2)
    assert LEGAL_IR_ARTIFACT_GRAPH_KEY in artifact.compiler_artifact

    bundle = LegalIRArtifactGraphBundle.from_evaluation_artifact(artifact)
    assert bundle.schema_version == LEGAL_IR_ARTIFACT_GRAPH_SCHEMA_VERSION
    assert bundle.consumers == ("hammer", "leanstral")
    assert bundle.to_evaluation_artifact().key == artifact.key

    tampered = artifact.to_dict()
    graph = tampered["compiler_artifact"][LEGAL_IR_ARTIFACT_GRAPH_KEY]
    graph["nodes"]["tokenization"]["payload"]["token_count"] = 999
    bad_artifact = type(artifact).from_dict(tampered)
    with pytest.raises(LegalIRArtifactGraphProvenanceError, match="checksum"):
        LegalIRArtifactGraphBundle.from_evaluation_artifact(bad_artifact)


def test_default_compiler_payload_uses_decoded_text_not_dataclass_repr() -> None:
    decoded = SimpleNamespace(
        text="The agency shall provide notice.",
        phrases=[SimpleNamespace(text="notice", slot="object")],
    )
    compiled = _compiled()
    compiled.decoded_modal_text = decoded

    artifact = legal_ir_evaluation_artifact_from_compilation(
        _key(),
        sample=_sample(),
        compilation_result=compiled,
    )

    assert artifact.compiler_artifact["decoded_modal_text"] == decoded.text
    assert "SimpleNamespace" not in artifact.compiler_artifact["decoded_modal_text"]


# The producer bridge controls below exercise detached fictional dictionaries.
# Admission is deliberately mocked at the same interface as the consumer's
# owning tests. They authenticate no reviewer, statute, checkpoint, or model,
# and invoke neither a decoder nor a native prover.
from copy import deepcopy
import hashlib

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    legal_ir_eval_splits as _producer_splits,
    legal_ir_evaluation_artifacts as _producer_owner,
    legal_span_consumer_binding as _producer_consumer,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.checkpoint_content_guard import (
    CheckpointContentGuard as _ProducerContentGuard,
)


def _producer_digest(value):
    return _ProducerContentGuard(value).sha256


def _producer_text_digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _producer_complete_norm():
    # Same complete nine-field representation as the semantic metric owner's
    # fictional fixture; argument order and all contextual fields are retained.
    return {
        "profile": "fictional-payload/v1",
        "typed_expression": {"root": {
            "kind": "forall", "binders": [{"name": "actor", "sort": "person"}],
            "arguments": [{"kind": "obligation", "predicate": "file",
                "arguments": ["agency", "report"], "exception": "emergency",
                "cardinality": 1, "time": "30days"}]}},
        "argument_roles": [{"symbol": "file", "roles": ["actor", "object"]}],
        "assumptions": [],
        "governing_context": {"jurisdiction": "fictional", "instrument_id": "act",
            "governing_edition": "v1", "legal_as_of_utc": "2026-01-01",
            "valid_from_utc": "2025-01-01", "valid_until_utc": "2027-01-01"},
        "interpretation_id": "fixture:one",
        "source_binding": {"source_version_cid": "source-one",
            "occurrence_cid": "span-one", "document_revision": "v1"},
        "definition_uses": [{"definition_unit_id": "definition",
            "defined_predicate": "file", "use_unit_id": "norm",
            "use_occurrence_cid": "span-one", "target_typed_paths": ["/root/arguments/0"],
            "applicability": "governing", "interpretation_id": "fixture:one", "evidence_refs": []}],
        "cross_references": [{"from_unit_id": "norm", "dependency_artifact_id": "external-one",
            "dependency_sha256": "a" * 64, "version": "v1", "evidence_refs": []}],
    }


def _producer_reviewed_case(monkeypatch, *, count=1, change=None, context_partition=None):
    """Adapt consumer reviewed_case for hparam selection with complete targets."""
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as admission

    rows = [{"id": f"fictional-reviewed-{index}", "unit_id": f"fixture:provision-{index}",
        "source_text": f"Fictional provision {index}: the agency must file a report unless an emergency applies.",
        "canonical_ir": _producer_complete_norm()} for index in range(count)]
    if change == "source":
        rows[0]["source_text"] += " Fictional source revision."
    elif change == "target":
        rows[0]["canonical_ir"]["interpretation_id"] = "fixture:revised"
    report = {"schema": "legal-reviewed-norm-admission-assessment/v2",
        "profile": "complete-reviewed-norm-admission/v2", "declaration_sha256": "d" * 64,
        "provenance_kind": "fictional_fixture", "semantic_use_eligible": True,
        "permitted_uses": ["hparam_selection"], "blockers": [],
        "producer_pins": {"fixture:admission": "a" * 64},
        "training_mask": 0, "evaluation_gold_mask": 0,
        "units": [{"unit_id": row["unit_id"], "source_text": row["source_text"],
            "occurrence_cid": f"fixture:occurrence:{row['unit_id']}",
            "canonical_ir": deepcopy(row["canonical_ir"]),
            "argument_roles": deepcopy(row["canonical_ir"]["argument_roles"]),
            "relational_profile": "fixture:opaque-typed-contract"} for row in rows]}
    replays = []

    def assess(**inputs):
        replays.append(deepcopy(inputs))
        result = deepcopy(inputs["test_report"])
        if inputs.get("current_revoked"):
            result["semantic_use_eligible"] = False
            result["blockers"] = ["current_reviewer_key_revoked"]
        if inputs.get("current_dependency_changed"):
            raise ValueError("current dependency digest differs")
        return result

    fake = SimpleNamespace(norm=admission.norm, assess_reviewed_norm_admission_v2=assess,
        norm_content_adjudication_sha256=admission.norm_content_adjudication_sha256)
    monkeypatch.setattr(_producer_consumer, "_reviewed_admission_owner", lambda: fake)
    replay = {"expected_preparation_sha256": "e" * 64,
        "expected_registry_sha256": "b" * 64, "expected_policy_sha256": "c" * 64,
        "source_inputs": [{"raw_bytes": b"fictional exact UTF8 source\x00"}],
        "relational_inputs": [{"request_raw": b'{"complete":"typed"}'}],
        "at_time_utc": "2026-11-08T08:00:00Z", "test_report": report}
    exposure = [{"id": row["id"], "source_text_sha256": _producer_text_digest(row["source_text"]),
        "canonical_ir_sha256": _producer_digest(row["canonical_ir"]),
        "target_exposure": "declared_validation_scoring",
        "provenance_ref": "fixture:isolated-consumer-interface"} for row in rows]
    split_examples = [_producer_splits.LegalIRSplitExample.from_sample(
        {"sample_id": row["id"], "text": row["source_text"]}) for row in rows]
    assignments = {row["id"]: "validation" for row in rows}
    if context_partition is not None:
        split_examples.append(_producer_splits.LegalIRSplitExample.from_sample(
            {"sample_id": "fictional-context", "text": "Unrelated fictional training example."}))
        assignments["fictional-context"] = context_partition
    manifest = _producer_splits.LegalIRSplitManifest(
        examples=tuple(split_examples), assignments=assignments,
        config_digest=_producer_text_digest("fictional fixed consumer policy"),
    ).to_dict()
    options = {"expected_rows_sha256": _producer_digest(rows), "split_manifest": manifest,
        "expected_split_manifest_sha256": _producer_digest(manifest), "admission_inputs": replay,
        "expected_admission_inputs_sha256": _producer_consumer.reviewed_admission_inputs_sha256(replay),
        "exposure_records": exposure, "expected_exposure_sha256": _producer_digest(exposure),
        "operation": "hparam_selection", "allow_fictional_fixture": True}
    binding = _producer_consumer.prepare_reviewed_source_span_consumer_binding_v2(rows, **options)
    assert binding.receipt()["status"] == "ready"
    return binding, rows, options, replays


def _producer_bridge_options(case):
    binding, rows, options, _ = case
    return {"binding": binding, "rows": rows,
        "split_manifest": options["split_manifest"], "admission_inputs": options["admission_inputs"],
        "exposure_records": options["exposure_records"], "compiler_commit": "fictional-compiler-commit",
        "input_profile": {"profile_id": "fictional-source-only/v1", "max_source_tokens": 128,
            "max_context_tokens": 256, "max_output_tokens": 1024},
        "checkpoint_declarations": {"encoder": {"id": "fixture:encoder", "sha256": "1" * 64},
            "decoder": {"id": "fixture:decoder", "sha256": "2" * 64}},
        "permitted_context": [], "retrieved_examples": {row["id"]: [] for row in rows}}


def _producer_exact_outputs(rows):
    return [{"id": row["id"], "outcome": "complete", "candidate": deepcopy(row["canonical_ir"])}
            for row in rows]


def _producer_evaluate(options, producer):
    return _producer_owner.evaluate_reviewed_source_span_producer_artifact(**options, producer=producer)


def _producer_payload(artifact):
    return artifact.to_dict()["compiler_artifact"]["reviewed_source_span_producer_evaluation"]


def test_reviewed_producer_bridge_supplies_source_only_once_and_scores_all_complete_targets(monkeypatch):
    case = _producer_reviewed_case(monkeypatch, count=2)
    options = _producer_bridge_options(case)
    original = deepcopy((case[1], case[2]))
    calls = []

    def producer(arguments):
        calls.append(deepcopy(arguments))
        assert type(arguments) is tuple and len(arguments) == 2
        assert all(set(row) == {"id", "source_text", "context"} for row in arguments)
        assert all(row["context"] == {"permitted": [], "retrieved": []} for row in arguments)
        return _producer_exact_outputs(case[1])

    artifact = _producer_evaluate(options, producer)
    payload = _producer_payload(artifact)
    report = artifact.to_dict()["metrics"]["complete_norm_payload"]
    assert len(calls) == payload["producer_callback_count"] == 1
    assert len(case[3]) >= 4  # preparation, validation, dispatch, post-dispatch replay
    assert payload["reference_population"] == case[1]
    assert payload["producer_outputs"] == _producer_exact_outputs(case[1])
    assert report["denominator"] == 2 and report["metric_numerators"]["full_nine_payload_exact"] == 2
    assert payload["admission_before"]["training_mask"] == payload["admission_after"]["evaluation_gold_mask"] == 0
    for field in ("producer_authenticity_verified", "loaded_checkpoint_identity_verified",
                  "native_proof_verified", "source_fidelity_proved", "semantic_equivalence_proved",
                  "corpus_admitted", "token_budget_enforced"):
        assert payload[field] is False
    assert payload["formal_checks_status"] == "not_performed"
    assert payload["actual_toolchain_identity_verified"] is False
    assert payload["accepted_semantic_count"] is None
    assert payload["artifact_observation_scope"] == "historical_at_callback_time"
    assert payload["cache_retrieval_replays_admission"] is False
    assert payload["current_review_replay_required_for_later_eligibility"] is True
    costs = payload["compute_and_cost"]
    assert costs["status"] == "callback_and_comparison_wall_clock_only"
    assert all(costs[field] is None for field in ("training_compute", "model_cpu_compute",
        "model_gpu_compute", "inference_tokens", "total_monetary_cost",
        "cost_per_correctly_accepted_formalization"))
    assert artifact.compilation_seconds == artifact.embedding_seconds == 0
    assert (case[1], case[2]) == original
    # Returned snapshots are detached; mutating them cannot change the artifact.
    payload["producer_outputs"][0]["candidate"]["interpretation_id"] = "fixture:tampered-snapshot"
    assert _producer_payload(artifact)["producer_outputs"] == _producer_exact_outputs(case[1])


@pytest.mark.parametrize("change", ["source", "target"])
def test_reviewed_producer_bridge_sample_key_binds_complete_rows(monkeypatch, change):
    original = _producer_reviewed_case(monkeypatch)
    baseline = _producer_evaluate(_producer_bridge_options(original),
        lambda _arguments: _producer_exact_outputs(original[1]))
    changed = _producer_reviewed_case(monkeypatch, change=change)
    candidate = _producer_evaluate(_producer_bridge_options(changed),
        lambda _arguments: _producer_exact_outputs(changed[1]))
    assert candidate.key.sample_hash != baseline.key.sample_hash
    assert candidate.key.digest != baseline.key.digest


@pytest.mark.parametrize("change", ["profile", "checkpoint", "context", "retrieval", "retrieval_order"])
def test_reviewed_producer_bridge_configuration_key_changes_with_declared_inputs(monkeypatch, change):
    case = _producer_reviewed_case(monkeypatch, context_partition="train")
    options = _producer_bridge_options(case)
    first = {"id": "fictional-context", "content": "Fictional training explanation A."}
    second = {"id": "fictional-context", "content": "Fictional training explanation B."}
    options["retrieved_examples"][case[1][0]["id"]] = [deepcopy(first), deepcopy(second)]
    baseline = _producer_evaluate(options, lambda _arguments: _producer_exact_outputs(case[1]))
    if change == "profile":
        options["input_profile"]["max_output_tokens"] += 1
    elif change == "checkpoint":
        options["checkpoint_declarations"]["decoder"]["sha256"] = "3" * 64
    elif change == "context":
        options["permitted_context"] = [first]
    elif change == "retrieval":
        options["retrieved_examples"][case[1][0]["id"]][0]["content"] += " Changed."
    else:
        options["retrieved_examples"][case[1][0]["id"]].reverse()
    candidate = _producer_evaluate(options, lambda _arguments: _producer_exact_outputs(case[1]))
    assert candidate.key.sample_hash == baseline.key.sample_hash
    assert candidate.key.config_hash != baseline.key.config_hash
    assert candidate.key.digest != baseline.key.digest


def test_reviewed_producer_bridge_known_training_context_reaches_callback_in_declared_order(monkeypatch):
    case = _producer_reviewed_case(monkeypatch, context_partition="train")
    options = _producer_bridge_options(case)
    options["permitted_context"] = [{"id": "fictional-context", "content": "Fictional shared context."}]
    options["retrieved_examples"][case[1][0]["id"]] = [
        {"id": "fictional-context", "content": "First fictional example."},
        {"id": "fictional-context", "content": "Second fictional example."}]
    seen = []

    def producer(arguments):
        seen.append(deepcopy(arguments))
        assert arguments[0]["context"]["permitted"] == options["permitted_context"]
        assert arguments[0]["context"]["retrieved"] == options["retrieved_examples"][case[1][0]["id"]]
        return _producer_exact_outputs(case[1])

    artifact = _producer_evaluate(options, producer)
    assert len(seen) == 1
    assert _producer_payload(artifact)["context_authority_scope"] == "training_split_eligibility_declaration_only"


@pytest.mark.parametrize("damage", ["unknown_id", "heldout_id", "target_id", "target_unit", "target_subtree",
                                    "target_expression", "unknown_retrieval", "retrieval_population"])
def test_reviewed_producer_bridge_refuses_unapproved_or_target_bearing_context_before_dispatch(monkeypatch, damage):
    case = _producer_reviewed_case(monkeypatch,
        context_partition="holdout" if damage == "heldout_id" else "train")
    options = _producer_bridge_options(case)
    record = {"id": "fictional-context", "content": "Unrelated fictional material."}
    if damage == "unknown_id": record["id"] = "unknown-context"
    elif damage == "target_id": record["id"] = case[1][0]["id"]
    elif damage == "target_unit": record["content"] = case[1][0]["unit_id"]
    elif damage == "target_subtree": record["content"] = deepcopy(case[1][0]["canonical_ir"])
    elif damage == "target_expression": record["content"] = deepcopy(case[1][0]["canonical_ir"]["typed_expression"])
    if damage == "unknown_retrieval":
        options["retrieved_examples"][case[1][0]["id"]] = [{"id": "unknown", "content": "Unrelated."}]
    elif damage == "retrieval_population":
        options["retrieved_examples"] = {}
    else:
        options["permitted_context"] = [record]
    calls = []
    with pytest.raises(ValueError):
        _producer_evaluate(options, lambda arguments: calls.append(arguments))
    assert calls == []


@pytest.mark.parametrize("damage", ["source", "target", "profile", "checkpoint", "context", "revocation", "dependency"])
def test_reviewed_producer_bridge_revalidates_inputs_and_admission_after_callback(monkeypatch, damage):
    case = _producer_reviewed_case(monkeypatch)
    options = _producer_bridge_options(case)
    calls = []

    def producer(arguments):
        calls.append(arguments)
        outputs = _producer_exact_outputs(case[1])
        if damage == "source": case[1][0]["source_text"] += " Changed during callback."
        elif damage == "target": case[1][0]["canonical_ir"]["interpretation_id"] = "fixture:changed"
        elif damage == "profile": options["input_profile"]["max_output_tokens"] += 1
        elif damage == "checkpoint": options["checkpoint_declarations"]["encoder"]["sha256"] = "f" * 64
        elif damage == "context": options["permitted_context"].append({"id": "unknown", "content": "Changed."})
        elif damage == "revocation": options["admission_inputs"]["current_revoked"] = True
        else: options["admission_inputs"]["current_dependency_changed"] = True
        return outputs

    with pytest.raises(ValueError):
        _producer_evaluate(options, producer)
    assert len(calls) == 1 and len(case[3]) >= 3
    if damage not in ("source", "target"):
        assert len(case[3]) >= 4


def test_reviewed_producer_bridge_refuses_mutated_detached_arguments_without_mutating_sources(monkeypatch):
    case = _producer_reviewed_case(monkeypatch)
    options = _producer_bridge_options(case)
    original = deepcopy((case[1], case[2]))

    def producer(arguments):
        arguments[0]["source_text"] += " Changed detached argument."
        return _producer_exact_outputs(case[1])

    with pytest.raises(ValueError, match="mutated its detached arguments"):
        _producer_evaluate(options, producer)
    assert (case[1], case[2]) == original


@pytest.mark.parametrize("damage", ["missing", "duplicate", "reversed", "extra", "metric_override", "authority"])
def test_reviewed_producer_bridge_rejects_nonexact_outcome_population_or_asserted_scores(monkeypatch, damage):
    case = _producer_reviewed_case(monkeypatch, count=2)
    options = _producer_bridge_options(case)

    def producer(_arguments):
        outputs = _producer_exact_outputs(case[1])
        if damage == "missing": outputs.pop()
        elif damage == "duplicate": outputs[1] = deepcopy(outputs[0])
        elif damage == "reversed": outputs.reverse()
        elif damage == "extra": outputs.append(deepcopy(outputs[0]))
        elif damage == "metric_override": outputs[0]["structural_equivalence"] = 1.0
        else: outputs[0]["native_proof_verified"] = True
        return outputs

    with pytest.raises(ValueError):
        _producer_evaluate(options, producer)


def test_reviewed_producer_bridge_keeps_noncomplete_and_malformed_outputs_in_denominator(monkeypatch):
    case = _producer_reviewed_case(monkeypatch, count=7)
    options = _producer_bridge_options(case)

    def producer(_arguments):
        outputs = _producer_exact_outputs(case[1])
        for output, status in zip(outputs[1:6], ("incomplete", "abstained", "unsupported", "invalid", "error")):
            output.update(outcome=status, candidate=None)
        outputs[-1]["candidate"].pop("typed_expression")
        return outputs

    artifact = _producer_evaluate(options, producer)
    report = artifact.to_dict()["metrics"]["complete_norm_payload"]
    assert report["denominator"] == report["metric_denominators"]["full_nine_payload_exact"] == 7
    assert report["metric_numerators"]["full_nine_payload_exact"] == 1
    assert report["rates"]["full_nine_payload_exact"] == pytest.approx(1 / 7)
    assert report["outcome_counts"] == {"complete": 2, "incomplete": 1, "abstained": 1,
        "unsupported": 1, "invalid": 1, "error": 1}


def test_reviewed_producer_bridge_callback_failure_counts_every_case_as_error(monkeypatch):
    case = _producer_reviewed_case(monkeypatch, count=2)
    options = _producer_bridge_options(case)

    def producer(_arguments):
        raise RuntimeError("Fictional producer failure; no model execution.")

    artifact = _producer_evaluate(options, producer)
    report = artifact.to_dict()["metrics"]["complete_norm_payload"]
    assert report["denominator"] == 2 and report["outcome_counts"]["error"] == 2
    assert report["metric_numerators"]["full_nine_payload_exact"] == 0
    assert _producer_payload(artifact)["producer_exception_type"] == "RuntimeError"


# Unlike the isolated mocked-admission cases above, these controls use the
# existing public source/typed-AST/dependency/signature fixture through its
# owning test helper. Signatures belong to fictional fixture identities; this
# is a software integration control, not actual statutory or model evidence.
def _producer_public_heldout_case():
    import importlib.util
    from pathlib import Path

    # Resolve only the owning test beside this file. Qualification must capture
    # this exact helper and its admission fixtures; no /tmp or artifact imports.
    helper_path = Path(__file__).resolve().with_name("test_legal_span_consumer_binding.py")
    spec = importlib.util.spec_from_file_location("_producer_public_consumer_fixture", helper_path)
    assert spec is not None and spec.loader is not None
    consumer_helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(consumer_helper)
    helper, admission, current, rows, consumer_options = consumer_helper.reviewed_public_heldout_case()
    binding = _producer_consumer.prepare_reviewed_source_span_consumer_binding_v2(rows, **consumer_options)
    assert binding.receipt()["status"] == "ready"
    options = _producer_bridge_options((binding, rows, consumer_options, None))
    options["allow_heldout_evaluation"] = True
    return consumer_helper, helper, admission, current, rows, consumer_options, options


def test_reviewed_producer_bridge_public_signed_fictional_heldout_component_positive():
    _, _, _, current, rows, _, options = _producer_public_heldout_case()
    originals = deepcopy(rows)
    calls = []
    # The authored outputs deliberately test custody only. They do not model a
    # source-conditioned decoder and prove no unseen-task generalization.
    expected_outputs = _producer_exact_outputs(rows)

    def producer(arguments):
        calls.append(deepcopy(arguments))
        assert type(arguments) is tuple and len(arguments) == len(rows) == 3
        assert [item["id"] for item in arguments] == [row["id"] for row in rows]
        assert all(set(item) == {"id", "source_text", "context"} for item in arguments)
        assert all(item["context"] == {"permitted": [], "retrieved": []} for item in arguments)
        return deepcopy(expected_outputs)

    artifact = _producer_evaluate(options, producer)
    payload = _producer_payload(artifact)
    report = artifact.to_dict()["metrics"]["complete_norm_payload"]
    before, after = payload["admission_before"], payload["admission_after"]
    heldout = payload["heldout_evaluation"]
    assert len(calls) == payload["producer_callback_count"] == 1
    assert report["denominator"] == report["metric_numerators"]["full_nine_payload_exact"] == 3
    assert before["operation"] == after["operation"] == "heldout_evaluation"
    assert before["semantic_admission_replayed"] is after["semantic_admission_replayed"] is True
    assert before["semantic_use_eligible"] is after["semantic_use_eligible"] is True
    assert before["provenance_kind"] == after["provenance_kind"] == "fictional_fixture"
    assert before["training_mask"] == after["training_mask"] == 0
    assert before["evaluation_gold_mask"] == after["evaluation_gold_mask"] == 0
    assert heldout == before["heldout_evaluation"] == after["heldout_evaluation"]
    assert heldout["purpose"] == _producer_consumer.REVIEWED_HELDOUT_PURPOSE
    assert heldout["dependency_group"]["required_dependency_ids"] == current["preparation"]["subject"]["required_dependency_ids"]
    assert heldout["dependency_group"]["dependency_manifest_sha256"] == current["manifest"]["manifest_sha256"]
    assert heldout["dependency_group_sha256"] == _producer_digest(heldout["dependency_group"])
    assert heldout["training_example_ids"] == heldout["retrieved_example_ids"] == []
    assert len(current["declaration"]["definition_uses"]) == 2
    assert payload["configuration"]["profile"] == "reviewed-source-span-producer-heldout/v1"
    assert payload["configuration"]["operation"] == "heldout_evaluation"
    assert payload["configuration"]["heldout_evaluation"] == heldout
    assert payload["empty_context_enforced_at_argument_boundary"] is True
    assert payload["context_authority_scope"] == "empty_supplied_context_at_callback_argument_boundary"
    for field in ("producer_authenticity_verified", "loaded_checkpoint_identity_verified",
                  "native_proof_verified", "actual_toolchain_identity_verified", "source_fidelity_proved",
                  "semantic_equivalence_proved", "corpus_admitted", "external_training_exposure_verified",
                  "model_pretraining_exposure_verified", "heldout_generalization_established"):
        assert payload[field] is False
    assert payload["accepted_semantic_count"] is None
    assert rows == originals


@pytest.mark.parametrize("opt_in", [None, False, 1])
def test_reviewed_producer_bridge_public_heldout_requires_separate_explicit_boolean_opt_in(opt_in):
    _, _, _, _, _, _, options = _producer_public_heldout_case()
    if opt_in is None:
        options.pop("allow_heldout_evaluation")
    else:
        options["allow_heldout_evaluation"] = opt_in
    calls = []
    with pytest.raises(ValueError):
        _producer_evaluate(options, lambda arguments: calls.append(arguments))
    assert calls == []


@pytest.mark.parametrize("field", ["permitted_context", "retrieved_examples"])
def test_reviewed_producer_bridge_public_heldout_forbids_nonempty_supplied_context(field):
    _, _, _, _, rows, _, options = _producer_public_heldout_case()
    record = {"id": "fictional-external-example", "content": "Unrelated fictional material."}
    if field == "permitted_context":
        options[field] = [record]
    else:
        options[field][rows[0]["id"]] = [record]
    calls = []
    with pytest.raises(ValueError, match="empty"):
        _producer_evaluate(options, lambda arguments: calls.append(arguments))
    assert calls == []


def test_reviewed_producer_bridge_public_heldout_revocation_after_callback_rejects_old_ready_evidence():
    consumer_helper, helper, admission, current, rows, _, options = _producer_public_heldout_case()
    calls = []

    def producer(arguments):
        calls.append(deepcopy(arguments))
        current["registry"]["keys"][0]["revoked_at_utc"] = helper.EVALUATED
        current["registry"]["revocation_generation"] += 1
        helper.reviewed_resign_v2(current)
        updated = consumer_helper.reviewed_public_admission_inputs(helper, admission, current)
        # Mutate the exact replay object currently held by the bridge, rather
        # than replacing only this test's options pointer.
        options["admission_inputs"].clear()
        options["admission_inputs"].update(updated)
        return _producer_exact_outputs(rows)

    with pytest.raises(_producer_consumer.SourceSpanConsumerBindingError):
        _producer_evaluate(options, producer)
    assert len(calls) == 1


def test_reviewed_producer_bridge_public_heldout_frozen_split_change_after_callback_is_refused():
    _, _, _, _, rows, _, options = _producer_public_heldout_case()
    calls = []

    def producer(arguments):
        calls.append(deepcopy(arguments))
        options["split_manifest"]["config_digest"] = "0" * 64
        return _producer_exact_outputs(rows)

    with pytest.raises(_producer_consumer.SourceSpanConsumerBindingError):
        _producer_evaluate(options, producer)
    assert len(calls) == 1
