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


def _reviewed_torch_source_producer_fixture(tmp_path):
    """Signed fictional heldout policy plus a real tiny Torch EOS model.

    The source-known fields come from the separately declared physical source
    records, not from row canonical_ir. EOS-biased actual head parameters make
    abstention predictable without embedding a reference answer in logits.
    The in-test guards model caller policy only; the outer owned qualification
    must separately supply real Source/native/process/storage custody.
    """
    from copy import deepcopy
    from pathlib import Path
    import json
    from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_training_worker as model_fixtures
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    consumer_helper, helper, admission, current, rows, consumer_options, evaluation_options = _producer_public_heldout_case()
    torch, backend, _ = model_fixtures._torch_reviewed_backend_fixture()
    with torch.no_grad():
        backend.model.head.weight.zero_()
        backend.model.head.bias.fill_(-1000.0)
        backend.model.head.bias[backend.tokenizer.eos_token_id] = 1000.0
    snapshot = backend.snapshot_checkpoint()
    def artifact(name, raw):
        return worker.CheckpointArtifact.from_dict(model_fixtures._complete_reviewed_artifact(tmp_path / name, raw))
    model = artifact("source-producer-model.pt", snapshot["model_state"])
    optimizer = artifact("source-producer-optimizer.pt", snapshot["optimizer_state"])
    token_asset = artifact("source-producer-tokenizer.json", worker._json_bytes({
        "fixture": "local-fixed-byte-pipeline", "pretrained": False}))
    license_asset = artifact("source-producer-license.json", worker._json_bytes({
        "fixture_only": True, "real_model_license_approval": "unprovided"}))
    declaration = current["declaration"]
    contexts = {"profile": "reviewed-source-selection-context/v2",
        "selection_context": {"schema": "caller-known-interpretation-selection/v1",
            "interpretation_id": declaration["interpretation_id"], "selection_mode": "identifier_only"},
        "rows": [{"id": "reviewed:" + unit["unit_id"], "unit_id": unit["unit_id"],
            "governing_context": deepcopy(declaration["governing_context"]),
            "source_binding": {"source_version_cid": unit["source_version"]["record_cid"],
                "occurrence_cid": unit["occurrence"]["record_cid"],
                "document_revision": unit["document_revision"]}} for unit in declaration["units"]]}
    assert [item["id"] for item in contexts["rows"]] == [row["id"] for row in rows]
    guards = {"execution": 0, "asset_policy": 0, "admission": 0}
    def no_registry(*args, **kwargs):
        pytest.fail("inference must not load a training stage/target registry")
    registry = SimpleNamespace(read_artifact=no_registry, artifact_path=no_registry)
    def execution():
        guards["execution"] += 1
    def asset_policy(policy):
        guards["asset_policy"] += 1
        assert policy["backend_identity"]["pretrained"] is False
        assert policy["training_requested"] is policy["restore_requested"] is False
        assert policy["operation"] == "heldout_evaluation"
    def fresh_admission():
        guards["admission"] += 1
        # A NEW mapping on every call tests fresh-provider closure, rather than
        # relying on mutation of the generic evaluator's older input object.
        return deepcopy(consumer_helper.reviewed_public_admission_inputs(helper, admission, current))
    runtime = worker.ReviewedDecoderRuntime(registry, backend, backend.tokenizer,
        fresh_admission, execution, asset_policy)
    factory_options = {"binding": evaluation_options["binding"], "rows": rows,
        "split_manifest": consumer_options["split_manifest"],
        "exposure_records": consumer_options["exposure_records"], "source_contexts": contexts,
        "expected_source_contexts_sha256": _producer_digest(contexts),
        "expected_admission_inputs_sha256": _producer_consumer.reviewed_admission_inputs_sha256(fresh_admission()),
        "backend_identity": backend.identity(), "assets": (model, token_asset, license_asset),
        "model_checkpoint": model, "optimizer_checkpoint": optimizer,
        "max_source_tokens": 4096, "max_output_tokens": 3, "allow_heldout_evaluation": True}
    def declarations():
        return {"encoder": {"id": "fixture:encoder-declaration-only", "sha256": "1" * 64},
            "decoder": {"id": factory_options["backend_identity"]["backend_id"],
                        "sha256": factory_options["model_checkpoint"].sha256}}
    return SimpleNamespace(worker=worker, torch=torch, backend=backend, runtime=runtime,
        options=factory_options, declarations=declarations, artifact=artifact, rows=rows,
        contexts=contexts, guards=guards, helper=helper, current=current, snapshot=snapshot)


def test_reviewed_torch_source_producer_evaluate_replays_signed_heldout_and_real_forward_without_gold(tmp_path):
    import json
    fixture = _reviewed_torch_source_producer_fixture(tmp_path)
    fixture.backend.model.dropout.train(False)
    parameter = next(fixture.backend.model.parameters())
    parameter.grad = fixture.torch.ones_like(parameter)
    original_gradient = parameter.grad
    original_gradient_values = parameter.grad.clone()
    original_modes = tuple(module.training for module in fixture.backend.model.modules())
    original_rng = fixture.torch.get_rng_state().clone()
    producer = fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    artifact = producer.evaluate(compiler_commit="fixture:current-compiler-declaration",
                                 checkpoint_declarations=fixture.declarations())
    payload = _producer_payload(artifact)
    report = artifact.to_dict()["metrics"]["complete_norm_payload"]
    observed = producer.observation()
    attached = artifact.to_dict()["metadata"]["source_generation_observation"]
    assert report["denominator"] == report["outcome_counts"]["abstained"] == 3
    assert report["metric_numerators"]["full_nine_payload_exact"] == 0
    assert payload["producer_callback_count"] == 1 and payload["producer_exception_type"] is None
    assert attached == observed
    assert payload["configuration"]["input_profile"]["profile_id"] == observed["input_profile_id"] == (
        "reviewed-decoder-source-producer/v1:" + _producer_digest(observed["input_commitment"]))
    assert len(fixture.backend.model.calls) == 3
    for call, row in zip(fixture.backend.model.calls, fixture.rows, strict=True):
        assert call["labels"] is None and call["decoder_input_ids"] == [[257]]
        source = json.loads(fixture.backend.tokenizer.decode(call["input_ids"][0][1:-1]))
        assert set(source) == {"profile", "source_text", "governing_context", "source_binding", "selection_context"}
        assert source["source_text"] == row["source_text"]
        assert "canonical_ir" not in source and "target_json" not in source
    assert observed["last_call"]["completed"] is True
    assert observed["last_call"]["entry_pair_match"] is observed["last_call"]["exit_pair_match"] is True
    assert all(item["candidate"] is None and item["generated_token_ids"] == [257, 258]
               for item in observed["last_call"]["raw_generation_outputs"])
    assert observed["last_call"]["input_receipt"]["target_access_performed"] is False
    assert observed["guard_calls"]["full_review_replay"] >= 4
    assert fixture.guards["execution"] >= 4 and fixture.guards["asset_policy"] >= 4 and fixture.guards["admission"] >= 4
    assert fixture.backend.restored_checkpoint_matches(fixture.snapshot["model_state"], fixture.snapshot["optimizer_state"]) is True
    assert tuple(module.training for module in fixture.backend.model.modules()) == original_modes
    assert parameter.grad is original_gradient and fixture.torch.equal(parameter.grad, original_gradient_values)
    assert fixture.torch.equal(fixture.torch.get_rng_state(), original_rng)
    assert fixture.backend._optimizer_steps == 0 and fixture.backend.optimizer.state_dict()["state"] == {}
    for key in ("producer_authenticity_verified", "loaded_checkpoint_identity_verified", "native_proof_verified",
                "source_fidelity_proved", "semantic_equivalence_proved", "corpus_admitted", "token_budget_enforced"):
        assert payload[key] is False
    # Public accessor and artifact metadata cannot mutate the private record.
    observed["input_commitment"]["max_output_tokens"] = 999
    attached["last_call"]["raw_generation_outputs"].clear()
    assert producer.observation()["input_commitment"]["max_output_tokens"] == 3
    assert len(producer.observation()["last_call"]["raw_generation_outputs"]) == 3


@pytest.mark.parametrize("damage", ["governing", "source_binding", "unit", "order", "selector"])
def test_reviewed_torch_source_producer_refuses_independent_context_mismatch_before_forward(tmp_path, damage):
    fixture = _reviewed_torch_source_producer_fixture(tmp_path)
    contexts = fixture.options["source_contexts"]
    if damage == "governing":
        contexts["rows"][0]["governing_context"]["governing_edition"] = "fixture:wrong-edition"
    elif damage == "source_binding":
        contexts["rows"][0]["source_binding"]["document_revision"] = "fixture:wrong-revision"
    elif damage == "unit":
        contexts["rows"][0]["unit_id"] = "fixture:wrong-unit"
    elif damage == "order":
        contexts["rows"].reverse()
    else:
        contexts["selection_context"]["interpretation_id"] = "fixture:wrong-selection"
    fixture.options["expected_source_contexts_sha256"] = _producer_digest(contexts)
    with pytest.raises(fixture.worker.TrainingJobValidationError, match="independent source context"):
        fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    assert fixture.backend.model.calls == []


def test_reviewed_torch_source_producer_refuses_wrong_already_loaded_checkpoint_without_restore(tmp_path, monkeypatch):
    fixture = _reviewed_torch_source_producer_fixture(tmp_path)
    parameter = next(fixture.backend.model.parameters())
    original = parameter.detach().clone()
    with fixture.torch.no_grad():
        parameter.add_(1.0)
    altered = fixture.backend.snapshot_checkpoint()["model_state"]
    with fixture.torch.no_grad():
        parameter.copy_(original)
    fixture.options["model_checkpoint"] = fixture.artifact("wrong-loaded-model.pt", altered)
    monkeypatch.setattr(fixture.backend, "restore_checkpoint", lambda *args: pytest.fail("inference must not restore"))
    monkeypatch.setattr(fixture.backend, "train_batch", lambda *args: pytest.fail("inference must not fit"))
    with pytest.raises(fixture.worker.TrainingJobValidationError, match="already-loaded"):
        fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    assert fixture.backend.model.calls == []
    assert fixture.backend.restored_checkpoint_matches(fixture.snapshot["model_state"], fixture.snapshot["optimizer_state"]) is True


def test_reviewed_torch_source_producer_low_level_refuses_nonempty_retrieval_without_dropping_it(tmp_path):
    fixture = _reviewed_torch_source_producer_fixture(tmp_path)
    producer = fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    arguments = tuple({"id": row["id"], "source_text": row["source_text"],
        "context": {"permitted": [], "retrieved": [{"id": "fixture:extra", "content": "must not be ignored"}]}}
        for row in fixture.rows)
    with pytest.raises(fixture.worker.TrainingJobValidationError, match="empty supplied context"):
        producer(arguments)
    assert fixture.backend.model.calls == []
    assert producer.observation()["last_call"]["completed"] is False
    assert producer.observation()["last_call"]["exit_pair_match"] is True


def test_reviewed_torch_source_producer_fresh_late_revocation_cannot_escape_evaluator_old_mapping(tmp_path, monkeypatch):
    fixture = _reviewed_torch_source_producer_fixture(tmp_path)
    producer = fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    forward = fixture.backend.model.forward
    def revoke_after_real_forward(**arguments):
        result = forward(**arguments)
        fixture.current["registry"]["keys"][0]["revoked_at_utc"] = fixture.helper.EVALUATED
        fixture.current["registry"]["revocation_generation"] += 1
        fixture.helper.reviewed_resign_v2(fixture.current)
        return result
    monkeypatch.setattr(fixture.backend.model, "forward", revoke_after_real_forward)
    with pytest.raises(fixture.worker.TrainingJobValidationError, match="admission inputs changed"):
        producer.evaluate(compiler_commit="fixture:current-compiler-declaration",
                          checkpoint_declarations=fixture.declarations())
    assert len(fixture.backend.model.calls) == 1
    assert producer.observation()["last_call"]["completed"] is False
    assert fixture.backend.restored_checkpoint_matches(fixture.snapshot["model_state"], fixture.snapshot["optimizer_state"]) is True


def test_reviewed_torch_source_producer_decoder_declaration_must_bind_actual_pair_before_forward(tmp_path):
    fixture = _reviewed_torch_source_producer_fixture(tmp_path)
    producer = fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    declared = fixture.declarations()
    declared["decoder"]["sha256"] = "f" * 64
    with pytest.raises(fixture.worker.TrainingJobValidationError, match="actual matched model checkpoint"):
        producer.evaluate(compiler_commit="fixture:compiler", checkpoint_declarations=declared)
    assert fixture.backend.model.calls == [] and producer.observation()["calls"] == 0


@pytest.fixture(scope="module")
def reviewed_normal_retention_artifacts(tmp_path_factory):
    fixture = _reviewed_torch_source_producer_fixture(tmp_path_factory.mktemp("normal-retention-pair"))
    first = fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    first_artifact = first.evaluate(compiler_commit="fixture:compiler", checkpoint_declarations=fixture.declarations())
    first_error = fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime,
        **dict(fixture.options, max_source_tokens=3)).evaluate(
            compiler_commit="fixture:compiler", checkpoint_declarations=fixture.declarations())
    # A changed real embedding leaves the deliberately EOS-only head output
    # unchanged, but must not reuse an artifact key for the original pair.
    with fixture.torch.no_grad():
        next(fixture.backend.model.parameters()).add_(0.25)
    changed = fixture.backend.snapshot_checkpoint()
    new_model = fixture.artifact("changed-source-producer-model.pt", changed["model_state"])
    new_optimizer = fixture.artifact("changed-source-producer-optimizer.pt", changed["optimizer_state"])
    fixture.options.update(model_checkpoint=new_model, optimizer_checkpoint=new_optimizer,
        assets=(new_model, *fixture.options["assets"][1:]))
    second = fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    second_artifact = second.evaluate(compiler_commit="fixture:compiler", checkpoint_declarations=fixture.declarations())
    second_error = fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime,
        **dict(fixture.options, max_source_tokens=3)).evaluate(
            compiler_commit="fixture:compiler", checkpoint_declarations=fixture.declarations())
    return {"complete": (first_artifact, second_artifact), "errors": (first_error, second_error)}


def test_reviewed_torch_source_producer_pair_change_keys_same_abstention_outputs_separately(
        reviewed_normal_retention_artifacts):
    first_artifact, second_artifact = reviewed_normal_retention_artifacts["complete"]
    assert _producer_payload(first_artifact)["producer_outputs"] == _producer_payload(second_artifact)["producer_outputs"]
    assert first_artifact.to_dict()["metadata"]["source_generation_observation"]["input_profile_id"] != (
        second_artifact.to_dict()["metadata"]["source_generation_observation"]["input_profile_id"])
    assert first_artifact.key.digest != second_artifact.key.digest


def test_reviewed_torch_source_producer_preflight_error_keeps_full_evaluator_population(tmp_path):
    fixture = _reviewed_torch_source_producer_fixture(tmp_path)
    fixture.options["max_source_tokens"] = 3
    producer = fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    artifact = producer.evaluate(compiler_commit="fixture:compiler", checkpoint_declarations=fixture.declarations())
    payload = _producer_payload(artifact)
    report = artifact.to_dict()["metrics"]["complete_norm_payload"]
    assert report["denominator"] == report["outcome_counts"]["error"] == 3
    assert payload["producer_exception_type"] == "ReviewedDecoderInputValidationError"
    assert len(payload["producer_outputs"]) == 3
    assert all(item["outcome"] == "error" and item["candidate"] is None for item in payload["producer_outputs"])
    assert fixture.backend.model.calls == []
    assert producer.observation()["last_call"]["completed"] is False
    assert producer.observation()["last_call"]["exit_pair_match"] is True


def _reviewed_torch_rich_hparam_fixture(tmp_path, monkeypatch, architecture="encoder_decoder", *,
        shared_family=False, bad_exposure=False, oversized=False, same_predicates=False,
        nested_query_identity=False, heldout=False, nested_heldout_identity=None, shared_provision=False,
        shared_revision=False, physical_model_factory=None):
    """Independent signed fictional TRAIN/query components and actual local HF.

    Fixture policy callbacks are engineering declarations only. The selected
    complete TRAIN definition is deliberately named before tokenization; no
    dynamically shortened example or query target is used to fit a budget.
    Actual outer Source/native/process/storage custody belongs to qualification.
    """
    import importlib.util
    import json
    from pathlib import Path
    from copy import deepcopy
    from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_training_worker as models
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as admission
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer

    operation = "heldout_evaluation" if heldout else "hparam_selection"
    query_partition = "holdout" if heldout else "validation"
    context_profile = "reviewed-rich-TRAIN-context-heldout/v1" if heldout else "reviewed-rich-TRAIN-context-hparam/v1"

    def owning_fixture(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    helper = owning_fixture("_rich_hparam_original_signed_fixture",
        Path(__file__).parents[2] / "logic/autoformal/test_legal_norm_content_adjudication_v1.py")
    consumer_helper = owning_fixture("_rich_hparam_original_consumer_fixture",
        Path(__file__).with_name("test_legal_span_consumer_binding.py"))
    train_texts = ["TRAIN instrument: TCoveredOfficer denotes an individual appointed by the TRAIN Board.",
        "Under TRAIN, TCoveredOfficer must file the annual TRAIN report except when TExcused applies.",
        "TRAIN grants TCoveredOfficer permission to inspect the TRAIN register."]
    if oversized:
        train_texts[0] += " Fictional complete source annotation " + "x" * 20000
    query_prefix = "T" if same_predicates else "Q"
    query_texts = ["QUERY interpretation defines " + query_prefix + "CoveredOfficer as a separately appointed officer for QUERY business.",
        "Every " + query_prefix + "CoveredOfficer shall submit a QUERY report unless the QUERY panel provides an express excuse.",
        "QUERY law allows each " + query_prefix + "CoveredOfficer to examine another register."]
    source_namespace = {"governing_instrument_id": "fixture:grouped-instrument",
                        "definition_provision_id": "fixture:grouped-instrument/definition" if shared_provision else None}
    common_revision = "fixture:common-document-revision" if shared_revision else None
    query_case = helper.reviewed_norm_fixture_v2(admission, fixture_namespace="q",
        source_texts=query_texts, permitted_uses=["formalization", operation],
        predicate_prefix=query_prefix, document_revision=common_revision, **(source_namespace if heldout else {}))
    query_unit = query_case["declaration"]["units"][0]
    query_target = query_case["preparation"]["units"][0]["canonical_ir"]
    identities = {"ir_artifact": query_unit["ir_artifact_id"],
        "component": query_case["declaration"]["component_id"],
        "target_digest": "sha256:" + _producer_digest(query_target),
        "source_version": query_unit["source_version"]["record_cid"]}
    document_revision = ("reviewed:fixture:q/unit-1" if nested_query_identity
                         else identities.get(nested_heldout_identity, common_revision))
    train_case = helper.reviewed_norm_fixture_v2(admission, fixture_namespace="t",
        source_texts=train_texts, permitted_uses=["formalization", "training"], predicate_prefix="T",
        document_revision=document_revision, **(source_namespace if heldout else {}))
    assert train_case["declaration"]["permitted_uses"] == ["formalization", "training"]
    assert query_case["declaration"]["permitted_uses"] == ["formalization", operation]
    assert train_case["declaration"]["interpretation_id"] != query_case["declaration"]["interpretation_id"]

    def rows(case):
        return [{"id": "reviewed:" + row["unit_id"], "unit_id": row["unit_id"],
            "source_text": row["source_text"], "canonical_ir": deepcopy(row["canonical_ir"])}
            for row in case["preparation"]["units"]]

    train_rows, query_rows = rows(train_case), rows(query_case)
    examples = []
    for partition, population in (("train", train_rows), (query_partition, query_rows)):
        group = "fictional-overlap" if shared_family else "fictional-" + partition
        for row in population:
            examples.append(_producer_splits.LegalIRSplitExample.from_sample({
                "sample_id": row["id"], "text": row["source_text"], "statute_family": group,
                "lineage_group_id": "independent-" + partition, "amendment_group": "amendment-" + partition,
                "source_document_id": row["unit_id"], "span_start": 0, "span_end": len(row["source_text"]),
                "sibling_keys": ["siblings-" + partition]}))
    # Derive source near-duplicate groups through the canonical owner instead
    # of trusting a caller-chosen key or ignoring textual overlap.
    duplicate_groups = _producer_splits._near_duplicate_clusters(examples,
        _producer_splits.LegalIREvalSplitConfig().near_duplicate_jaccard_threshold)
    examples = [example.with_near_duplicate_key(duplicate_groups.get(example.sample_id, example.content_hash))
                for example in examples]
    manifest = _producer_splits.LegalIRSplitManifest(examples=tuple(examples),
        assignments={row["id"]: partition for partition, population in (
            ("train", train_rows), (query_partition, query_rows)) for row in population},
        config_digest=_producer_text_digest("fictional independently reviewed rich "
                                           + ("heldout" if heldout else "hparam") + " split")).to_dict()

    def exposure(population, operation):
        exposures = {"training": "declared_supervised_training", "hparam_selection": "declared_validation_scoring",
            "heldout_evaluation": consumer.REVIEWED_HELDOUT_EXPOSURE}
        return [{"id": row["id"], "source_text_sha256": _producer_text_digest(row["source_text"]),
            "canonical_ir_sha256": _producer_digest(row["canonical_ir"]),
            "target_exposure": exposures[operation],
            "provenance_ref": "fixture:independent-signed-" + operation} for row in population]

    train_exposure, query_exposure = exposure(train_rows, "training"), exposure(query_rows, operation)
    if bad_exposure:
        train_exposure[0]["target_exposure"] = "unknown"

    def replay(case):
        return deepcopy(consumer_helper.reviewed_public_admission_inputs(helper, admission, case))

    def bind(population, records, case, operation):
        current = replay(case)
        return consumer.prepare_reviewed_source_span_consumer_binding_v2(population,
            expected_rows_sha256=_producer_digest(population), split_manifest=manifest,
            expected_split_manifest_sha256=_producer_digest(manifest), admission_inputs=current,
            expected_admission_inputs_sha256=consumer.reviewed_admission_inputs_sha256(current),
            exposure_records=records, expected_exposure_sha256=_producer_digest(records),
            operation=operation, allow_fictional_fixture=True,
            allow_heldout_evaluation=operation == "heldout_evaluation",
            heldout_evaluation_purpose=("frozen-single-component-with-reviewed-TRAIN-context/v1"
                                        if operation == "heldout_evaluation" else None))

    query_binding = bind(query_rows, query_exposure, query_case, operation)
    train_binding = bind(train_rows, train_exposure, train_case, "training")
    if not shared_family:
        assert query_binding.receipt()["status"] == "ready"
    if not shared_family and not bad_exposure:
        assert train_binding.receipt()["status"] == "ready"
    definition_id = next(unit["unit_id"] for unit in train_case["declaration"]["units"]
                         if unit["kind"] == "definition")
    definition = next(row for row in train_rows if row["unit_id"] == definition_id)
    queries = [{"id": row["id"], "source_text": row["source_text"]} for row in query_rows]
    selections = [{"id": row["id"], "source_sha256": _producer_text_digest(row["source_text"]),
        "index_sha256": _producer_digest(train_rows), "retrieved_ids": [definition["id"]]} for row in query_rows]
    declaration = query_case["declaration"]
    contexts = {"profile": "reviewed-source-selection-context/v2",
        "selection_context": {"schema": "caller-known-interpretation-selection/v1",
            "interpretation_id": declaration["interpretation_id"], "selection_mode": "identifier_only"},
        "rows": [{"id": "reviewed:" + unit["unit_id"], "unit_id": unit["unit_id"],
            "governing_context": deepcopy(declaration["governing_context"]),
            "source_binding": {"source_version_cid": unit["source_version"]["record_cid"],
                "occurrence_cid": unit["occurrence"]["record_cid"],
                "document_revision": unit["document_revision"]}} for unit in declaration["units"]]}
    state = {"revoked": False, "revoke_after_forward": False, "policy_error": None,
        "query_revoked": False, "revoke_query_in_context_policy": False}
    checks = {"context_policy": 0, "provider": 0}

    def fresh_context_inputs():
        checks["provider"] += 1
        current = replay(train_case)
        if state["revoked"]:
            # A NEW current mapping, without copying or fabricating a new
            # permission signature. Revoked trust cannot reuse the old digest.
            current["registry"]["keys"][0]["revoked_at_utc"] = helper.EVALUATED
            current["registry"]["revocation_generation"] += 1
            current["expected_registry_sha256"] = helper.auth.digest(current["registry"])
        return {"binding": train_binding, "training_rows": deepcopy(train_rows),
            "split_manifest": deepcopy(manifest), "admission_inputs": current,
            "exposure_records": deepcopy(train_exposure), "query_rows": deepcopy(queries),
            "retrieval_rows": deepcopy(selections)}

    def fresh_query_inputs():
        current = replay(query_case)
        if state["query_revoked"]:
            # Replace the present QUERY mapping without changing declarations
            # or making new signatures. Its original authorization is revoked.
            current["registry"]["keys"][0]["revoked_at_utc"] = helper.EVALUATED
            current["registry"]["revocation_generation"] += 1
            current["expected_registry_sha256"] = helper.auth.digest(current["registry"])
        return current

    def context_digest(value):
        return _producer_digest({"schema": "reviewed-decoder-rich-context-inputs/v1",
            "profile": context_profile,
            "binding_receipt_sha256": _producer_digest(value["binding"].receipt()),
            "training_rows_sha256": _producer_digest(value["training_rows"]),
            "split_manifest_sha256": _producer_digest(value["split_manifest"]),
            "admission_inputs_sha256": consumer.reviewed_admission_inputs_sha256(value["admission_inputs"]),
            "exposure_records_sha256": _producer_digest(value["exposure_records"]),
            "query_rows_sha256": _producer_digest(value["query_rows"]),
            "retrieval_rows_sha256": _producer_digest(value["retrieval_rows"])})

    def context_policy(policy):
        checks["context_policy"] += 1
        assert policy["context_profile"] == context_profile
        assert policy["operation"] == operation
        assert policy["training_requested"] is False and policy["heldout_requested"] is heldout
        assert policy["max_context_tokens"] == 4096 and policy["max_context_bytes"] == 16384
        if state["revoke_query_in_context_policy"]:
            state["query_revoked"] = True
        if state["policy_error"] is not None:
            raise state["policy_error"]
        return None

    # This optional tokenizer has fixed schema/JSON BPE merges only. It is not
    # fitted to either component. Complete definition content is never sliced.
    if physical_model_factory is None:
        model = models._reviewed_local_loader_hf_fixture(tmp_path, architecture,
            admission_provider=fresh_query_inputs, max_sequence_tokens=4096,
            fixed_json_schema_subwords=True)
        models._reviewed_local_loader_no_remote_or_training(monkeypatch, model)
        if heldout:
            # The heldout producer endpoint accepts an already-loaded pair. Keep
            # local-loader restoration and dependency pins in their owning tests.
            runtime = worker.ReviewedDecoderRuntime(registry=model.options["registry"], backend=model.backend,
                tokenizer=model.backend.tokenizer, current_admission_provider=fresh_query_inputs,
                execution_guard=model.options["execution_guard"], asset_policy_guard=model.options["asset_policy_guard"])
            loaded = None
        else:
            runtime, loaded = worker.load_local_reviewed_decoder_runtime(**model.options)
        forwards = []
        def observe_forward(module, arguments, keywords, result):
            # Observation-only hook returns None; no logits, args or outputs change.
            forwards.append({"input_ids": keywords["input_ids"].detach().cpu().tolist(),
                "labels": keywords.get("labels"),
                "decoder_input_ids": None if keywords.get("decoder_input_ids") is None
                                     else keywords["decoder_input_ids"].detach().cpu().tolist()})
            if state["revoke_after_forward"]:
                state["revoked"] = True
            return None
        hook = runtime.backend.model.register_forward_hook(observe_forward, with_kwargs=True)
    else:
        # Physical CLI checks execute the actual model in the original child;
        # the parent needs only genuine asset descriptors and review providers.
        assert heldout and callable(physical_model_factory)
        model = physical_model_factory(tmp_path, architecture, admission_provider=fresh_query_inputs,
            max_sequence_tokens=4096, fixed_json_schema_subwords=True)
        runtime = SimpleNamespace(current_admission_provider=fresh_query_inputs)
        loaded, forwards, hook = None, [], None
    options = {"binding": query_binding, "rows": query_rows, "split_manifest": manifest,
        "exposure_records": query_exposure, "source_contexts": contexts,
        "expected_source_contexts_sha256": _producer_digest(contexts),
        "expected_admission_inputs_sha256": consumer.reviewed_admission_inputs_sha256(fresh_query_inputs()),
        "backend_identity": model.options["expected_backend_identity"],
        "assets": tuple(model.options[key] for key in ("recipe_artifact", "model_config_artifact",
            "tokenizer_artifact", "license_artifact")),
        "model_checkpoint": model.options["model_checkpoint"],
        "optimizer_checkpoint": model.options["optimizer_checkpoint"],
        "max_source_tokens": 4096, "max_output_tokens": 3,
        "allow_heldout_evaluation": heldout, "context_profile": context_profile,
        "current_context_inputs_provider": fresh_context_inputs,
        "expected_context_inputs_sha256": context_digest(fresh_context_inputs()),
        "context_policy_guard": context_policy}
    declarations = {"encoder": {"id": "fixture:encoder-declaration-only", "sha256": "1" * 64},
        "decoder": {"id": options["backend_identity"]["backend_id"],
                    "sha256": options["model_checkpoint"].sha256}}
    return SimpleNamespace(worker=worker, model=model, runtime=runtime, loaded=loaded, options=options,
        declarations=declarations, rows=query_rows, training_rows=train_rows, definition=definition,
        contexts=contexts, state=state, checks=checks, forwards=forwards, hook=hook,
        provider=fresh_context_inputs, context_digest=context_digest, bind=bind,
        train_case=train_case, query_case=query_case, train_exposure=train_exposure,
        selections=selections, manifest=manifest)


def test_reviewed_torch_context_factory_signed_heldout_rich_TRAIN_forward(tmp_path, monkeypatch):
    import json

    fixture = _reviewed_torch_rich_hparam_fixture(tmp_path, monkeypatch, heldout=True, shared_revision=True)
    train, query = (case["declaration"]["units"][0] for case in (fixture.train_case, fixture.query_case))
    assert train["document_revision"] == query["document_revision"]
    assert train["source_version"]["provision_id"] != query["source_version"]["provision_id"]
    producer = fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    result = producer.evaluate(compiler_commit="fixture:frozen-heldout-rich-TRAIN",
                               checkpoint_declarations=fixture.declarations)
    payload, observed = _producer_payload(result), producer.observation()
    metrics = result.to_dict()["metrics"]["complete_norm_payload"]
    assert metrics["denominator"] == metrics["outcome_counts"]["abstained"] == len(fixture.rows) == 3
    assert metrics["metric_numerators"]["full_nine_payload_exact"] == 0
    assert len(fixture.forwards) == 3 and payload["producer_exception_type"] is None
    for call, row in zip(fixture.forwards, fixture.rows, strict=True):
        assert call["labels"] is None and call["decoder_input_ids"] == [[257]]
        source = json.loads(fixture.runtime.backend.tokenizer.decode(call["input_ids"][0][1:-1]))
        assert source["source_text"] == row["source_text"]
        assert set(source) == {"profile", "source_text", "governing_context", "source_binding", "selection_context", "context"}
        retrieved = source["context"]["retrieved"]
        assert len(retrieved) == 1 and retrieved[0]["id"] == fixture.definition["id"]
        assert retrieved[0]["content"]["canonical_ir"] == fixture.definition["canonical_ir"]
        assert retrieved[0]["content"]["source_link"] == fixture.definition["canonical_ir"]["source_binding"]
        assert retrieved[0]["content"]["canonical_ir"] != row["canonical_ir"]
    assert payload["configuration"]["profile"] == "reviewed-source-span-producer-heldout-rich-TRAIN/v1"
    assert payload["heldout_evaluation"]["training_example_ids"] == sorted(row["id"] for row in fixture.training_rows)
    assert payload["configuration"]["rich_training_context"]["retrieved_example_ids"] == [fixture.definition["id"]]
    assert observed["context"]["heldout_context_supported"] is True
    assert observed["last_call"]["entry_pair_match"] is observed["last_call"]["exit_pair_match"] is True
    assert payload["heldout_generalization_established"] is payload["model_pretraining_exposure_verified"] is False


@pytest.mark.parametrize("damage, diagnostic", [
    ("dependency", "heldout and TRAIN share a reviewed dependency"),
    ("provision_revision", "heldout and TRAIN share a reviewed statutory provision identity"),
    ("nested_query_id", "heldout reference identity in rich producer context"),
    ("ir_artifact", "heldout reference identity in rich producer context"),
    ("component", "heldout reference identity in rich producer context"),
    ("target_digest", "heldout reference identity in rich producer context"),
    ("source_version", "heldout reference identity in rich producer context"),
])
def test_reviewed_torch_context_factory_heldout_refuses_signed_leakage(tmp_path, monkeypatch, damage, diagnostic):
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_structured_retrieval as structured

    fixture = _reviewed_torch_rich_hparam_fixture(tmp_path, monkeypatch, heldout=True,
        same_predicates=damage == "dependency", nested_query_identity=damage == "nested_query_id",
        nested_heldout_identity=damage, shared_provision=damage == "provision_revision")
    assert fixture.options["binding"].receipt()["status"] == fixture.provider()["binding"].receipt()["status"] == "ready"
    assert _producer_splits.require_legal_ir_split_guard(fixture.manifest).passed
    if damage == "provision_revision":
        train, query = (case["declaration"]["units"][0] for case in (fixture.train_case, fixture.query_case))
        assert train["source_version"]["provision_id"] == query["source_version"]["provision_id"]
        assert train["source_version"]["record_cid"] != query["source_version"]["record_cid"]
        assert train["source_version"]["raw_artifact"]["sha256"] != query["source_version"]["raw_artifact"]["sha256"]
        assert train["occurrence"]["record_cid"] != query["occurrence"]["record_cid"]
        assert train["document_revision"] != query["document_revision"]
    monkeypatch.setattr(inputs, "prepare_reviewed_decoder_context_generation_inputs",
        lambda *args, **kwargs: pytest.fail("heldout leakage reached tokenizer"))
    with pytest.raises(ValueError, match=diagnostic):
        fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    assert fixture.forwards == []
    value = fixture.provider()
    selection_digests = dict(expected_query_rows_sha256=_producer_digest(value["query_rows"]),
        expected_retrieval_rows_sha256=_producer_digest(value["retrieval_rows"]))
    offered = structured.consume_reviewed_contexts_v2(**value, **selection_digests, consumer=lambda payload: payload)
    retrieval = {row["id"]: [{"id": example["id"], "content": example} for example in row["examples"]]
                 for row in offered["rows"]}
    with pytest.raises(ValueError, match=diagnostic):
        _producer_evaluate(dict(binding=fixture.options["binding"], rows=fixture.rows, split_manifest=fixture.manifest,
            admission_inputs=fixture.runtime.current_admission_provider(), exposure_records=fixture.options["exposure_records"],
            compiler_commit="fixture:heldout-reference-leak", input_profile={"profile_id": "fictional:rich", "max_source_tokens": 4096,
                "max_context_tokens": 4096, "max_output_tokens": 3}, checkpoint_declarations=fixture.declarations,
            permitted_context=[], retrieved_examples=retrieval, allow_heldout_evaluation=True,
            reviewed_training_context=value, context_policy_guard=lambda receipt: None),
            lambda offered: pytest.fail("heldout reference leak reached evaluator callback"))
    with pytest.raises(TypeError, match="heldout_evaluation"):
        structured.consume_reviewed_contexts_v2(**value, **selection_digests, consumer=lambda payload: payload,
            heldout_evaluation=fixture.options["binding"].receipt()["heldout_evaluation"])


def test_reviewed_torch_context_factory_heldout_requires_live_policy_and_rechecks_training(tmp_path, monkeypatch):
    fixture = _reviewed_torch_rich_hparam_fixture(tmp_path, monkeypatch, heldout=True)
    denied = PermissionError("fictional heldout context use denied")
    fixture.state["policy_error"] = denied
    with pytest.raises(PermissionError) as caught:
        fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    assert caught.value is denied and fixture.forwards == []

    fixture.state["policy_error"] = None
    producer = fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    fixture.state["revoke_after_forward"] = True
    with pytest.raises(fixture.worker.TrainingJobValidationError, match="fresh TRAIN context provider differs"):
        producer.evaluate(compiler_commit="fixture:TRAIN-revocation-during-heldout",
                          checkpoint_declarations=fixture.declarations)
    assert len(fixture.forwards) == 1
    assert producer.observation()["last_call"]["completed"] is False


@pytest.mark.parametrize("architecture", ["encoder_decoder", "causal_lm"])
def test_reviewed_torch_context_factory_real_local_hf_hparam_rich_TRAIN_forward(tmp_path, monkeypatch, architecture):
    import json
    fixture = _reviewed_torch_rich_hparam_fixture(tmp_path, monkeypatch, architecture)
    backend = fixture.runtime.backend
    parameter = next(backend.model.parameters())
    parameter.grad = fixture.model.torch.ones_like(parameter)
    gradient, saved_gradient = parameter.grad, parameter.grad.clone()
    backend.model.train(False)
    next(module for name, module in backend.model.named_modules() if name).train(True)
    original_modes = tuple(module.training for module in backend.model.modules())
    original_rng = fixture.model.torch.get_rng_state().clone()
    producer = fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    result = producer.evaluate(compiler_commit="fixture:rich-TRAIN-hparam",
                              checkpoint_declarations=fixture.declarations)
    observed, payload = producer.observation(), _producer_payload(result)
    metrics = result.to_dict()["metrics"]["complete_norm_payload"]
    assert metrics["denominator"] == metrics["outcome_counts"]["abstained"] == 3
    assert metrics["metric_numerators"]["full_nine_payload_exact"] == 0
    assert len(fixture.forwards) == 3
    for call, row in zip(fixture.forwards, fixture.rows, strict=True):
        assert call["labels"] is None
        ids = call["input_ids"][0]
        if architecture == "encoder_decoder":
            assert call["decoder_input_ids"] == [[257]]
            source_ids = ids[1:-1]
        else:
            assert call["decoder_input_ids"] is None and ids[-1] == 257
            source_ids = ids[1:-2]
        source = json.loads(backend.tokenizer.decode(source_ids))
        assert source["source_text"] == row["source_text"]
        assert source["profile"] == "reviewed-source-with-training-context/v1"
        assert source["context"]["permitted"] == []
        records = source["context"]["retrieved"]
        assert len(records) == 1 and records[0]["id"] == fixture.definition["id"]
        assert set(records[0]["content"]) == {"id", "unit_id", "source_text", "canonical_ir", "source_link", "selection_role"}
        assert records[0]["content"]["canonical_ir"] == fixture.definition["canonical_ir"]
        assert records[0]["content"]["source_text"] == fixture.definition["source_text"]
        assert records[0]["content"]["canonical_ir"] != row["canonical_ir"]
        assert "target_json" not in source and "labels" not in source
    receipt = observed["last_call"]["input_receipt"]
    assert receipt["max_context_tokens"] == 4096 and receipt["max_context_bytes"] == 16384
    assert all(item["context_tokens_including_bos_eos"] <= 4096 for item in receipt["row_commitments"])
    assert observed["context"]["full_replays"] >= 4 and fixture.checks["context_policy"] >= 4
    assert observed["last_call"]["entry_pair_match"] is observed["last_call"]["exit_pair_match"] is True
    assert all(row["generated_token_ids"] == [257, 0] for row in observed["last_call"]["raw_generation_outputs"])
    assert backend.restored_checkpoint_matches(fixture.model.checkpoint["model_state"],
                                               fixture.model.checkpoint["optimizer_state"]) is True
    assert backend._optimizer_steps == 1
    assert parameter.grad is gradient and fixture.model.torch.equal(parameter.grad, saved_gradient)
    assert fixture.model.torch.equal(fixture.model.torch.get_rng_state(), original_rng)
    assert tuple(module.training for module in backend.model.modules()) == original_modes
    assert payload["configuration"]["operation"] == "hparam_selection"
    assert payload["configuration"]["input_profile"]["profile_id"] == observed["input_profile_id"]
    assert observed["input_profile_id"].startswith("reviewed-decoder-rich-TRAIN-producer/v1:")
    assert payload["producer_exception_type"] is None
    for key in ("producer_authenticity_verified", "loaded_checkpoint_identity_verified", "native_proof_verified",
                "source_fidelity_proved", "semantic_equivalence_proved", "corpus_admitted", "token_budget_enforced"):
        assert payload[key] is False


def test_reviewed_torch_context_factory_context_policy_denial_precedes_tokenization(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
    fixture = _reviewed_torch_rich_hparam_fixture(tmp_path, monkeypatch)
    class ContextDenied(RuntimeError):
        pass
    original = ContextDenied("fictional context permission denied by caller")
    fixture.state["policy_error"] = original
    monkeypatch.setattr(inputs, "prepare_reviewed_decoder_context_generation_inputs",
        lambda *args, **kwargs: pytest.fail("denied context reached tokenizer/preparer"))
    with pytest.raises(ContextDenied) as caught:
        fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    assert caught.value is original and fixture.forwards == []


@pytest.mark.parametrize("when", ["before_tokenization", "after_real_forward"])
def test_reviewed_torch_context_factory_fresh_TRAIN_revocation_refuses_before_or_after_forward(tmp_path, monkeypatch, when):
    fixture = _reviewed_torch_rich_hparam_fixture(tmp_path, monkeypatch)
    producer = fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    fixture.state["revoked" if when == "before_tokenization" else "revoke_after_forward"] = True
    rng = fixture.model.torch.get_rng_state().clone()
    with pytest.raises(fixture.worker.TrainingJobValidationError, match="fresh TRAIN context provider"):
        producer.evaluate(compiler_commit="fixture:current-rich-revocation",
                          checkpoint_declarations=fixture.declarations)
    assert len(fixture.forwards) == (1 if when == "after_real_forward" else 0)
    assert fixture.runtime.backend.restored_checkpoint_matches(fixture.model.checkpoint["model_state"],
        fixture.model.checkpoint["optimizer_state"]) is True
    assert fixture.model.torch.equal(fixture.model.torch.get_rng_state(), rng)


def test_reviewed_torch_context_factory_family_split_overlap_never_reaches_tokenizer(tmp_path, monkeypatch):
    fixture = _reviewed_torch_rich_hparam_fixture(tmp_path, monkeypatch, shared_family=True)
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
    monkeypatch.setattr(inputs, "prepare_reviewed_decoder_context_generation_inputs",
        lambda *args, **kwargs: pytest.fail("family-overlap context reached tokenizer/preparer"))
    with pytest.raises(ValueError, match=r"^rich example shares query statute_family$") as caught:
        fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    assert type(caught.value) is ValueError
    assert fixture.forwards == []


def test_reviewed_torch_context_factory_TRAIN_exposure_is_replayed(tmp_path, monkeypatch):
    fixture = _reviewed_torch_rich_hparam_fixture(tmp_path, monkeypatch, bad_exposure=True)
    with pytest.raises(_producer_consumer.SourceSpanConsumerBindingError):
        fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    assert fixture.forwards == []


def test_reviewed_torch_context_factory_complete_oversized_context_never_truncates(tmp_path, monkeypatch):
    fixture = _reviewed_torch_rich_hparam_fixture(tmp_path, monkeypatch, oversized=True)
    with pytest.raises(ValueError, match="complete rich context exceeds byte allowance"):
        fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    assert fixture.forwards == []
    assert len(fixture.definition["source_text"]) > 20000


def test_reviewed_torch_context_factory_missing_governing_definition_is_not_dropped(tmp_path, monkeypatch):
    fixture = _reviewed_torch_rich_hparam_fixture(tmp_path, monkeypatch)
    original_provider = fixture.provider
    norm = next(row for row in fixture.training_rows if any(use["use_unit_id"] == row["unit_id"]
                for use in row["canonical_ir"]["definition_uses"]))
    selected_exposure = [row for row in fixture.train_exposure if row["id"] == norm["id"]]
    incomplete_binding = fixture.bind([norm], selected_exposure, fixture.train_case, "training")
    assert incomplete_binding.receipt()["status"] == "ready"
    def incomplete():
        value = original_provider()
        value["training_rows"] = [norm]
        value["binding"] = incomplete_binding
        value["exposure_records"] = selected_exposure
        for selected in value["retrieval_rows"]:
            selected["index_sha256"] = _producer_digest([norm])
            selected["retrieved_ids"] = [norm["id"]]
        return value
    fixture.options.update(current_context_inputs_provider=incomplete,
        expected_context_inputs_sha256=fixture.context_digest(incomplete()))
    with pytest.raises(ValueError, match="complete governing definition missing"):
        fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    assert fixture.forwards == []


@pytest.mark.parametrize("damage", ["extra_field", "query_source", "index", "split", "expected_digest"])
def test_reviewed_torch_context_factory_current_provider_binding_is_exact(tmp_path, monkeypatch, damage):
    fixture = _reviewed_torch_rich_hparam_fixture(tmp_path, monkeypatch)
    original = fixture.provider
    def changed():
        value = original()
        if damage == "extra_field":
            value["permission_granted"] = True
        elif damage == "query_source":
            value["query_rows"][0]["source_text"] += " altered"
        elif damage == "index":
            value["retrieval_rows"][0]["index_sha256"] = "0" * 64
        elif damage == "split":
            value["split_manifest"]["config_digest"] = "0" * 64
        return value
    fixture.options["current_context_inputs_provider"] = changed
    if damage == "expected_digest":
        fixture.options["expected_context_inputs_sha256"] = "0" * 64
    with pytest.raises(fixture.worker.TrainingJobValidationError):
        fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    assert fixture.forwards == []


@pytest.mark.parametrize("damage", ["old_heldout", "missing_profile"])
def test_reviewed_torch_context_factory_source_only_and_old_heldout_profiles_remain_closed(tmp_path, monkeypatch, damage):
    fixture = _reviewed_torch_rich_hparam_fixture(tmp_path, monkeypatch)
    fixture.options["allow_heldout_evaluation"] = damage == "old_heldout"
    if damage == "missing_profile":
        fixture.options["context_profile"] = None
    with pytest.raises(fixture.worker.TrainingJobValidationError):
        fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    assert fixture.forwards == []


def test_reviewed_torch_context_factory_cache_identity_binds_rich_selection(tmp_path, monkeypatch):
    fixture = _reviewed_torch_rich_hparam_fixture(tmp_path, monkeypatch)
    first = fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    norm = next(row for row in fixture.training_rows if any(use["use_unit_id"] == row["unit_id"]
                for use in row["canonical_ir"]["definition_uses"]))
    for selection in fixture.selections:
        selection["retrieved_ids"] = [norm["id"]]
    fixture.options["expected_context_inputs_sha256"] = fixture.context_digest(fixture.provider())
    second = fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    assert first.input_profile_id != second.input_profile_id
    assert first.observation()["context"]["context_records_sha256"] != second.observation()["context"]["context_records_sha256"]
    # This constructs a commitment only. No assertion says the larger norm+
    # definition context fits the fixed token budget or has been evaluated.
    assert fixture.forwards == []


def test_reviewed_torch_context_factory_target_subtree_screen_precedes_builder(tmp_path, monkeypatch):
    fixture = _reviewed_torch_rich_hparam_fixture(tmp_path, monkeypatch, same_predicates=True)
    with pytest.raises(fixture.worker.TrainingJobValidationError, match="query target subtree"):
        fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    assert fixture.forwards == []


def test_reviewed_torch_context_factory_nested_query_ID_is_screened_after_complete_TRAIN_replay(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_structured_retrieval as structured
    fixture = _reviewed_torch_rich_hparam_fixture(tmp_path, monkeypatch, nested_query_identity=True)
    query_id = "reviewed:fixture:q/unit-1"
    assert query_id == fixture.rows[0]["id"]
    value = fixture.provider()
    # Prove this is accepted signed TRAIN content, not a synthetic rejected
    # mapping or a field inserted into an already-signed artifact.
    payload = structured.consume_reviewed_contexts_v2(value["binding"], value["training_rows"],
        split_manifest=value["split_manifest"], admission_inputs=value["admission_inputs"],
        exposure_records=value["exposure_records"], query_rows=value["query_rows"],
        retrieval_rows=value["retrieval_rows"],
        expected_query_rows_sha256=_producer_digest(value["query_rows"]),
        expected_retrieval_rows_sha256=_producer_digest(value["retrieval_rows"]),
        consumer=lambda complete: complete, max_context_bytes=16384)
    assert payload["binding_receipt"]["status"] == "ready"
    assert payload["binding_receipt"]["operation"] == "training"
    assert len(payload["rows"]) == len(fixture.rows) == 3
    for row in payload["rows"]:
        assert len(row["examples"]) == 1
        example = row["examples"][0]
        assert example["id"] == fixture.definition["id"]
        assert example["canonical_ir"]["source_binding"]["document_revision"] == query_id
    monkeypatch.setattr(inputs, "prepare_reviewed_decoder_context_generation_inputs",
        lambda *args, **kwargs: pytest.fail("nested query ID reached context preparer/tokenizer"))
    with pytest.raises(fixture.worker.TrainingJobValidationError, match="query target ID in rich producer context"):
        fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    assert fixture.forwards == []


def test_reviewed_torch_context_factory_context_policy_cannot_revoke_QUERY_and_reuse_cached_admission(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
    fixture = _reviewed_torch_rich_hparam_fixture(tmp_path, monkeypatch)
    baseline = fixture.options["expected_admission_inputs_sha256"]
    assert _producer_consumer.reviewed_admission_inputs_sha256(
        fixture.runtime.current_admission_provider()) == baseline
    fixture.state["revoke_query_in_context_policy"] = True
    monkeypatch.setattr(inputs, "prepare_reviewed_decoder_context_generation_inputs",
        lambda *args, **kwargs: pytest.fail("late QUERY revocation reached context preparer/tokenizer"))
    with pytest.raises(fixture.worker.TrainingJobValidationError, match="^current producer admission inputs changed after context policy$"):
        fixture.worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    assert fixture.checks["context_policy"] >= 1 and fixture.state["query_revoked"] is True
    current = fixture.runtime.current_admission_provider()
    assert current["registry"]["keys"][0]["revoked_at_utc"] is not None
    assert _producer_consumer.reviewed_admission_inputs_sha256(current) != baseline
    assert fixture.forwards == []


@pytest.fixture(scope="module")
def reviewed_retention_artifacts():
    _, _, _, _, rows, _, options = _producer_public_heldout_case()
    exact = _producer_exact_outputs(rows)
    abstain = lambda row: {"id": row["id"], "outcome": "abstained", "candidate": None}
    incomplete = {"id": rows[1]["id"], "outcome": "incomplete", "candidate": None}
    prior = _producer_evaluate(options, lambda _: [exact[0], exact[1], abstain(rows[2])])
    candidate_options = dict(options, checkpoint_declarations=dict(options["checkpoint_declarations"],
        decoder={"id": "fixture:after", "sha256": "3" * 64}))
    candidate = _producer_evaluate(candidate_options, lambda _: [exact[0], incomplete, exact[2]])
    zero = _producer_evaluate(options, lambda _: [abstain(row) for row in rows])
    return prior, candidate, zero


def _compare_reviewed_retention(before, after, **pins):
    return _producer_owner.compare_reviewed_source_span_retention(before, after, **{
        "expected_before_sha256": _producer_digest(before.to_dict()),
        "expected_after_sha256": _producer_digest(after.to_dict()), **pins})


def test_reviewed_retention_reports_retained_lost_and_gained_on_same_frozen_panel(reviewed_retention_artifacts):
    before, after, _ = reviewed_retention_artifacts
    report = _compare_reviewed_retention(before, after)
    assert report["denominator"] == 3
    assert report["baseline_exact"] == report["after_exact"] == 2
    assert report["counts"] == {"retained": 1, "lost": 1, "gained": 1, "still_incorrect": 0}
    assert report["retention_rate"] == 0.5
    assert [case["status"] for case in report["cases"]] == ["retained", "lost", "gained"]
    assert report["before_outcome_counts"]["abstained"] == report["after_outcome_counts"]["incomplete"] == 1
    assert report["before_decoder"] != report["after_decoder"]
    assert all(report[field] is False for field in ("current_admission_replayed", "loaded_checkpoint_identity_verified",
                                                    "heldout_generalization_established", "proof_authority"))


def test_reviewed_retention_has_no_rate_when_baseline_has_no_exact_cases(reviewed_retention_artifacts):
    _, after, zero = reviewed_retention_artifacts
    report = _compare_reviewed_retention(zero, after)
    assert report["denominator"] == 3 and report["baseline_exact"] == 0 and report["after_exact"] == 2
    assert report["retention_rate"] is None
    assert report["counts"] == {"retained": 0, "lost": 0, "gained": 2, "still_incorrect": 1}
    assert report["before_outcome_counts"]["abstained"] == 3


@pytest.mark.parametrize("damage", ("source", "split", "retrieval", "budget"))
def test_reviewed_retention_rejects_incomparable_observations_before_scoring(
        reviewed_retention_artifacts, damage, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics

    before, after, _ = reviewed_retention_artifacts
    offered = after.to_dict()
    payload = offered["compiler_artifact"]["reviewed_source_span_producer_evaluation"]
    config = payload["configuration"]
    if damage == "source":
        payload["reference_population"][0]["source_text"] = "Different independently pinned fictional text."
        payload["producer_arguments"][0]["source_text"] = payload["reference_population"][0]["source_text"]
    elif damage == "split":
        config["input_sha256s"]["split_manifest"] = "a" * 64
    elif damage == "retrieval":
        config["retrieved_examples"][payload["reference_population"][0]["id"]] = [{"id": "foreign"}]
    else:
        config["input_profile"]["max_output_tokens"] += 1
    offered["metadata"]["content_sha256"] = _producer_digest(payload)
    changed = type(after).from_dict(offered)
    monkeypatch.setattr(legal_ir_semantic_metrics, "evaluate_complete_norm_payloads",
        lambda *_: pytest.fail("incomparable panel reached comparison scoring"))
    with pytest.raises(ValueError, match="retention observations differ|retention requires identical source-only|"
                                        "retention references differ"):
        _compare_reviewed_retention(before, changed)


def test_reviewed_retention_rejects_tampered_scores_even_after_resealing(reviewed_retention_artifacts):
    before, after, _ = reviewed_retention_artifacts
    offered = after.to_dict()
    payload = offered["compiler_artifact"]["reviewed_source_span_producer_evaluation"]
    payload["comparison"]["metric_numerators"]["full_nine_payload_exact"] = 3
    offered["metrics"]["complete_norm_payload"] = deepcopy(payload["comparison"])
    offered["metadata"]["content_sha256"] = _producer_digest(payload)
    with pytest.raises(ValueError, match="stored retention scores differ from complete rescoring"):
        _compare_reviewed_retention(before, type(after).from_dict(offered))


def test_reviewed_retention_requires_independent_full_artifact_pins(reviewed_retention_artifacts):
    before, after, _ = reviewed_retention_artifacts
    with pytest.raises(ValueError, match="independent retention artifact commitment differs"):
        _compare_reviewed_retention(before, after, expected_before_sha256=before.key.digest)


def _reseal_reviewed_retention(artifact, offered):
    """Rebuild ordinary checksums to exercise contract checks beyond corruption."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_semantic_metrics import (
        COMPLETE_NORM_PAYLOAD_METRICS_SCHEMA,
    )

    payload = offered["compiler_artifact"]["reviewed_source_span_producer_evaluation"]
    config = payload["configuration"]
    for field in ("producer_arguments", "producer_outputs", "admission_before", "admission_after"):
        config[field + "_sha256"] = _producer_digest(payload[field])
    offered["key"] = LegalIREvaluationCacheKey.for_sample({"rows": payload["reference_population"]},
        compiler_commit=payload["declared_compiler_identity"],
        state_hash=_producer_digest(config["checkpoint_declarations"]),
        metric_schema=COMPLETE_NORM_PAYLOAD_METRICS_SCHEMA, configuration=config).to_dict()
    offered["metadata"]["content_sha256"] = _producer_digest(payload)
    return type(artifact).from_dict(offered)


@pytest.mark.parametrize("damage", ("encoder", "compiler", "admission", "dependency", "source_budget",
                                    "context_budget", "unknown_configuration", "reference_order"))
def test_reviewed_retention_rejects_resealed_changes_to_other_frozen_inputs(
        reviewed_retention_artifacts, damage, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics

    before, after, _ = reviewed_retention_artifacts
    offered = after.to_dict()
    payload = offered["compiler_artifact"]["reviewed_source_span_producer_evaluation"]
    config = payload["configuration"]
    if damage == "encoder":
        config["checkpoint_declarations"]["encoder"]["sha256"] = "a" * 64
    elif damage == "compiler":
        payload["declared_compiler_identity"] = "fictional:other-compiler"
    elif damage == "admission":
        payload["admission_after"]["observation_scope"] = "changed fictional admission observation"
    elif damage == "dependency":
        heldout = config["heldout_evaluation"]
        heldout["dependency_group"]["dependency_manifest_sha256"] = "a" * 64
        heldout["dependency_group_sha256"] = _producer_digest(heldout["dependency_group"])
        payload["heldout_evaluation"] = deepcopy(heldout)
    elif damage in ("source_budget", "context_budget"):
        config["input_profile"]["max_" + damage.split("_")[0] + "_tokens"] += 1
    elif damage == "unknown_configuration":
        config["unbound_selection_policy"] = "fixture:changed-policy"
    else:
        payload["reference_population"].reverse()
        payload["producer_arguments"].reverse()
        payload["producer_outputs"].reverse()
    changed = _reseal_reviewed_retention(after, offered)
    monkeypatch.setattr(legal_ir_semantic_metrics, "evaluate_complete_norm_payloads",
        lambda *_: pytest.fail("incomparable panel reached comparison scoring"))
    with pytest.raises(ValueError, match="retention observations differ|retention references differ|"
                                        "closed source-only retention configuration required"):
        _compare_reviewed_retention(before, changed)


def test_reviewed_retention_rejects_two_matching_partial_panels(reviewed_retention_artifacts, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics

    panels = []
    for artifact in reviewed_retention_artifacts[:2]:
        offered = artifact.to_dict()
        payload = offered["compiler_artifact"]["reviewed_source_span_producer_evaluation"]
        config = payload["configuration"]
        for field in ("reference_population", "producer_arguments", "producer_outputs"):
            payload[field].pop()
        config["retrieved_examples"].pop(reviewed_retention_artifacts[0].to_dict()[
            "compiler_artifact"]["reviewed_source_span_producer_evaluation"]["reference_population"][-1]["id"])
        config["input_sha256s"]["rows"] = _producer_digest(payload["reference_population"])
        for field in ("admission_before", "admission_after"):
            payload[field]["input_sha256s"]["rows"] = config["input_sha256s"]["rows"]
        panels.append(_reseal_reviewed_retention(artifact, offered))
    monkeypatch.setattr(legal_ir_semantic_metrics, "evaluate_complete_norm_payloads",
        lambda *_: pytest.fail("partial component reached comparison scoring"))
    with pytest.raises(ValueError, match="retention references differ from the complete admitted dependency component"):
        _compare_reviewed_retention(*panels)


@pytest.mark.parametrize("outcome", ("incomplete", "abstained", "unsupported", "invalid", "error", "malformed"))
def test_reviewed_retention_counts_every_failed_candidate_as_lost(reviewed_retention_artifacts, outcome):
    _, _, _, _, rows, _, options = _producer_public_heldout_case()
    before = _producer_evaluate(options, lambda _: _producer_exact_outputs(rows))
    options["checkpoint_declarations"]["decoder"] = {"id": "fixture:after-all-failures", "sha256": "4" * 64}
    outputs = _producer_exact_outputs(rows)
    for output in outputs:
        if outcome == "malformed":
            output["candidate"].pop("typed_expression")
        else:
            # Even an otherwise exact payload earns zero for an error status.
            output["outcome"] = outcome
    after = _producer_evaluate(options, lambda _: outputs)
    report = _compare_reviewed_retention(before, after)
    assert report["denominator"] == report["baseline_exact"] == 3
    assert report["after_exact"] == 0 and report["retention_rate"] == 0.0
    assert report["counts"] == {"retained": 0, "lost": 3, "gained": 0, "still_incorrect": 0}
    metrics = report["after_complete_norm_scores"]
    assert set(metrics["metric_denominators"].values()) == {3}
    assert set(metrics["metric_numerators"].values()) == {0}
    assert metrics["malformed_complete_candidate_count"] == (3 if outcome == "malformed" else 0)
    assert metrics["outcome_counts"]["complete" if outcome == "malformed" else outcome] == 3


@pytest.mark.parametrize("damage", ("source_digest", "target_digest", "ready_count", "exposure"))
def test_reviewed_retention_rechecks_both_pinned_observed_admission_rows(
        reviewed_retention_artifacts, damage, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics

    panels = []
    for artifact in reviewed_retention_artifacts[:2]:
        offered = artifact.to_dict()
        payload = offered["compiler_artifact"]["reviewed_source_span_producer_evaluation"]
        for field in ("admission_before", "admission_after"):
            admission = payload[field]
            if damage == "ready_count":
                admission["ready_row_count"] -= 1
            elif damage == "exposure":
                admission["rows"][0]["exposure"]["target_exposure"] = "declared_supervised_training"
            else:
                admission["rows"][0]["source_text_sha256" if damage == "source_digest"
                                     else "canonical_ir_sha256"] = "a" * 64
        panels.append(_reseal_reviewed_retention(artifact, offered))
    monkeypatch.setattr(legal_ir_semantic_metrics, "evaluate_complete_norm_payloads",
        lambda *_: pytest.fail("inconsistent admission reached comparison scoring"))
    with pytest.raises(ValueError, match="retention artifact differs from its observed heldout admission|"
                                        "retention references differ from observed reviewed admission rows"):
        _compare_reviewed_retention(*panels)


@pytest.mark.parametrize("signal", ("kernel_or_deterministic_trusted", "verified_counterexample"))
def test_reviewed_retention_proof_feedback_cannot_relabel_wrong_interpretation(signal):
    _, _, _, _, rows, _, options = _producer_public_heldout_case()
    before = _producer_evaluate(options, lambda _: _producer_exact_outputs(rows))
    options["checkpoint_declarations"]["decoder"] = {"id": "fixture:wrong-interpretation", "sha256": "5" * 64}
    outputs = _producer_exact_outputs(rows)
    for output in outputs:
        output["candidate"]["interpretation_id"] += ":different-interpretation"
    after = _producer_evaluate(options, lambda _: outputs)
    offered = after.to_dict()
    payload = offered["compiler_artifact"]["reviewed_source_span_producer_evaluation"]
    payload["native_proof_verified"] = signal == "kernel_or_deterministic_trusted"
    payload["proof_feedback"] = {"training_label": signal}
    report = _compare_reviewed_retention(before, _reseal_reviewed_retention(after, offered))
    assert report["denominator"] == report["counts"]["lost"] == 3
    assert report["after_exact"] == 0 and report["proof_authority"] is False
    assert report["after_complete_norm_scores"]["legal_admission_or_proof_authority"] is False
    assert report["after_complete_norm_scores"]["metric_numerators"]["interpretation_identity_exact"] == 0


@pytest.mark.parametrize("case", ("complete", "errors"))
def test_reviewed_retention_accepts_real_source_producer_checkpoint_change(reviewed_normal_retention_artifacts, case):
    before, after = reviewed_normal_retention_artifacts[case]
    report = _compare_reviewed_retention(before, after)
    assert report["producer_route"] == "normal_source_producer"
    assert report["denominator"] == report["counts"]["still_incorrect"] == 3
    assert report["baseline_exact"] == report["after_exact"] == 0 and report["retention_rate"] is None
    left, right = report["before_source_generation"], report["after_source_generation"]
    assert left["input_commitment_sha256"] != right["input_commitment_sha256"]
    assert left["checkpoint_pair"]["model_checkpoint"]["sha256"] != right["checkpoint_pair"]["model_checkpoint"]["sha256"]
    assert left["fixed_commitment"] == right["fixed_commitment"]
    assert left["input_receipt"] == right["input_receipt"]
    if case == "complete":
        assert report["before_outcome_counts"]["abstained"] == report["after_outcome_counts"]["abstained"] == 3
        assert left["input_receipt"]["target_access_performed"] is False
    else:
        assert report["before_outcome_counts"]["error"] == report["after_outcome_counts"]["error"] == 3
        assert left["input_receipt"] is None


def _recommit_normal_retention(artifact, offered):
    metadata = offered["metadata"]
    observed = metadata["source_generation_observation"]
    digest = _producer_digest(observed["input_commitment"])
    metadata["source_generation_input_commitment_sha256"] = observed["input_commitment_sha256"] = digest
    profile_id = "reviewed-decoder-source-producer/v1:" + digest
    observed["input_profile_id"] = profile_id
    offered["compiler_artifact"]["reviewed_source_span_producer_evaluation"]["configuration"]["input_profile"]["profile_id"] = profile_id
    return _reseal_reviewed_retention(artifact, offered)


@pytest.mark.parametrize("damage", ("commitment_hash", "derived_profile", "missing_observation", "model_declaration", "checkpoint_asset_alias",
    "producer_code", "fixed_asset", "backend_identity", "tokenizer", "source_wire", "generation_output"))
def test_reviewed_retention_normal_route_replays_commitments_and_freezes_other_inputs(
        reviewed_normal_retention_artifacts, damage, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics

    before, after = reviewed_normal_retention_artifacts["complete"]
    offered = after.to_dict()
    metadata = offered["metadata"]
    observed = metadata["source_generation_observation"]
    committed = observed["input_commitment"]
    config = offered["compiler_artifact"]["reviewed_source_span_producer_evaluation"]["configuration"]
    if damage == "commitment_hash":
        metadata["source_generation_input_commitment_sha256"] = "f" * 64
    elif damage == "derived_profile":
        config["input_profile"]["profile_id"] = "fixture:unbound-derived-profile"
    elif damage == "missing_observation":
        metadata.pop("source_generation_observation")
        metadata.pop("source_generation_input_commitment_sha256")
    elif damage == "model_declaration":
        config["checkpoint_declarations"]["decoder"]["sha256"] = "f" * 64
    elif damage == "checkpoint_asset_alias":
        committed["assets"][0]["sha256"] = "f" * 64
    elif damage == "producer_code":
        committed["source_sha256"]["worker"] = committed["backend_identity"]["implementation_sha256"] = "f" * 64
    elif damage == "fixed_asset":
        committed["assets"][-1]["sha256"] = "f" * 64
    elif damage == "backend_identity":
        committed["backend_identity"]["backend_id"] += ":different-tokenizer-or-recipe"
        config["checkpoint_declarations"]["decoder"]["id"] = committed["backend_identity"]["backend_id"]
    elif damage == "tokenizer":
        observed["last_call"]["input_receipt"]["tokenizer_contract"]["pipeline_sha256"] = "f" * 64
    elif damage == "source_wire":
        observed["last_call"]["input_receipt"]["row_commitments"][0]["source_wire_sha256"] = "f" * 64
    else:
        observed["last_call"]["raw_generation_outputs"][0]["outcome"] = "unsupported"
    changed = (_reseal_reviewed_retention(after, offered) if damage in
        ("commitment_hash", "derived_profile", "missing_observation") else _recommit_normal_retention(after, offered))
    monkeypatch.setattr(legal_ir_semantic_metrics, "evaluate_complete_norm_payloads",
        lambda *_: pytest.fail("incomparable normal producer reached scoring"))
    with pytest.raises(ValueError, match="normal retention"):
        _compare_reviewed_retention(before, changed)


def test_reviewed_retention_generic_callback_cannot_change_literal_profile(reviewed_retention_artifacts, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics

    before, after, _ = reviewed_retention_artifacts
    offered = after.to_dict()
    offered["compiler_artifact"]["reviewed_source_span_producer_evaluation"]["configuration"]["input_profile"]["profile_id"] += ":changed"
    changed = _reseal_reviewed_retention(after, offered)
    monkeypatch.setattr(legal_ir_semantic_metrics, "evaluate_complete_norm_payloads",
        lambda *_: pytest.fail("changed generic callback profile reached scoring"))
    with pytest.raises(ValueError, match="retention observations differ"):
        _compare_reviewed_retention(before, changed)



def _producer_public_mixed_case(*, operation="heldout_evaluation"):
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_span_consumer_binding as consumer_helper
    helper, admission, current, rows, consumer_options = consumer_helper.reviewed_public_mixed_consumer_case(operation=operation)
    binding = _producer_consumer.prepare_reviewed_source_span_consumer_binding_v3(rows, **consumer_options)
    assert binding.receipt()["status"] == "ready"
    options = _producer_bridge_options((binding, rows, consumer_options, None))
    if operation == "heldout_evaluation":
        options["allow_heldout_evaluation"] = True
    return consumer_helper, helper, admission, current, rows, consumer_options, options


@pytest.mark.parametrize("operation", ["hparam_selection", "heldout_evaluation"])
def test_reviewed_producer_v3_genuine_mixed_component_uses_existing_full_nine_evaluator(operation):
    _, helper, _, current, rows, _, options = _producer_public_mixed_case(operation=operation)
    original = deepcopy(rows)
    calls = []
    def producer(arguments):
        calls.append(deepcopy(arguments))
        assert [value["id"] for value in arguments] == [row["id"] for row in rows]
        assert all(set(value) == {"id", "source_text", "context"} for value in arguments)
        assert all(value["context"] == {"permitted": [], "retrieved": []} for value in arguments)
        # Known authored outputs exercise custody/metrics, not decoder quality.
        return _producer_exact_outputs(rows)
    artifact = _producer_evaluate(options, producer)
    payload = _producer_payload(artifact)
    metric = artifact.to_dict()["metrics"]["complete_norm_payload"]
    before, after = payload["admission_before"], payload["admission_after"]
    assert len(calls) == payload["producer_callback_count"] == 1
    assert before["schema"] == after["schema"] == _producer_consumer.REVIEWED_V3_SCHEMA
    assert before["profile"] == after["profile"] == _producer_consumer.REVIEWED_V3_PROFILE
    assert before["operation"] == after["operation"] == operation
    assert before["training_mask"] == after["training_mask"] == before["evaluation_gold_mask"] == after["evaluation_gold_mask"] == 0
    assert metric["denominator"] == metric["outcome_counts"]["complete"] == metric["metric_numerators"]["full_nine_payload_exact"] == 3
    assert payload["reference_population"] == original == rows
    assert rows[2]["canonical_ir"]["profile"] == helper.relational.MIXED_PROFILE
    assert all(len(row["canonical_ir"]) == 9 for row in rows)
    assert payload["producer_exception_type"] is None
    assert all(payload[key] is False for key in ("producer_authenticity_verified", "loaded_checkpoint_identity_verified",
        "native_proof_verified", "source_fidelity_proved", "semantic_equivalence_proved", "corpus_admitted"))
    helper.assert_signatures_valid(current)


@pytest.mark.parametrize("damage", ["revoked", "source_bytes", "ordered_roles", "typed_ast", "contract_tag", "detached_arguments"])
@pytest.mark.parametrize("raises", [False, True], ids=["return", "producer-error"])
def test_reviewed_producer_v3_checks_every_callback_exit_against_current_mapping_and_rows(damage, raises):
    consumer_helper, helper, admission, current, rows, consumer_options, options = _producer_public_mixed_case()
    calls = []
    def producer(arguments):
        calls.append(True)
        if damage == "revoked":
            current["registry"]["keys"][0]["revoked_at_utc"] = helper.fixture.EVALUATED
            current["registry"]["revocation_generation"] += 1
            helper.fixture.reviewed_resign_v2(current)
            helper.assert_signatures_valid(current)
            replay = consumer_helper.reviewed_public_admission_inputs(helper.fixture, admission, current)
            consumer_options["admission_inputs"].clear()
            consumer_options["admission_inputs"].update(replay)
        elif damage == "source_bytes":
            unit = current["declaration"]["units"][2]["unit_id"]
            consumer_options["admission_inputs"]["preparation_inputs"]["source_inputs"][unit]["raw_bytes"] += b" changed"
        elif damage == "ordered_roles":
            rows[2]["canonical_ir"]["argument_roles"][-1]["roles"].reverse()
        elif damage == "typed_ast":
            rows[2]["canonical_ir"]["typed_expression"]["root"]["kind"] = "exists"
        elif damage == "contract_tag":
            object.__setattr__(options["binding"], "_admission_version", "v2")
        else:
            arguments[0]["source_text"] += " changed"
        if raises:
            raise RuntimeError("producer failed after changing an input")
        return _producer_exact_outputs(rows)
    with pytest.raises(ValueError):
        _producer_evaluate(options, producer)
    assert calls == [True]


def test_reviewed_producer_v3_unmodified_producer_failure_retains_complete_denominator():
    _, _, _, _, rows, _, options = _producer_public_mixed_case()
    calls = []
    def failed(_):
        calls.append(True)
        raise RuntimeError("fictional producer failed with unchanged custody")
    artifact = _producer_evaluate(options, failed)
    metric = artifact.to_dict()["metrics"]["complete_norm_payload"]
    assert calls == [True]
    assert metric["denominator"] == metric["outcome_counts"]["error"] == len(rows) == 3
    assert metric["metric_numerators"]["full_nine_payload_exact"] == 0
    assert _producer_payload(artifact)["producer_exception_type"] == "RuntimeError"


def test_reviewed_producer_v3_requires_prepared_binding_and_refuses_rich_context_before_dispatch():
    _, _, _, _, _, _, options = _producer_public_mixed_case()
    calls = []
    options["binding"] = {"schema": _producer_consumer.REVIEWED_V3_SCHEMA,
                          "owner": "untrusted.arbitrary.importer", "status": "ready"}
    with pytest.raises(_producer_consumer.SourceSpanConsumerBindingError, match="prepared reviewed consumer"):
        _producer_evaluate(options, calls.append)
    assert calls == []
    _, _, _, _, _, _, options = _producer_public_mixed_case()
    options["reviewed_training_context"] = {}
    options["context_policy_guard"] = lambda _policy: calls.append("policy")
    with pytest.raises(ValueError):
        _producer_evaluate(options, calls.append)
    assert calls == []


@pytest.fixture(scope="module")
def reviewed_mixed_normal_retention_artifacts(tmp_path_factory):
    import json
    from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_training_worker as models
    fixture = models._reviewed_mixed_source_producer_fixture(tmp_path_factory.mktemp("mixed-normal-retention-pair"))
    first = models.worker.make_reviewed_decoder_source_producer_v3(fixture.runtime, **fixture.options)
    before = first.evaluate(compiler_commit="fixture:mixed-retention", checkpoint_declarations=fixture.declarations())
    before_error = models.worker.make_reviewed_decoder_source_producer_v3(fixture.runtime,
        **dict(fixture.options, max_source_tokens=3)).evaluate(
            compiler_commit="fixture:mixed-retention", checkpoint_declarations=fixture.declarations())
    with fixture.local.torch.no_grad():
        next(fixture.local.backend.model.parameters()).add_(0.25)
        next(iter(fixture.local.backend.optimizer.state.values()))["exp_avg"].add_(0.125)
    changed = fixture.local.backend.snapshot_checkpoint()
    new_model = fixture.local.artifact("changed-v3-model.pt", changed["model_state"])
    new_optimizer = fixture.local.artifact("changed-v3-optimizer.pt", changed["optimizer_state"])
    fixture.options.update(model_checkpoint=new_model, optimizer_checkpoint=new_optimizer)
    second = models.worker.make_reviewed_decoder_source_producer_v3(fixture.runtime, **fixture.options)
    after = second.evaluate(compiler_commit="fixture:mixed-retention", checkpoint_declarations=fixture.declarations())
    after_error = models.worker.make_reviewed_decoder_source_producer_v3(fixture.runtime,
        **dict(fixture.options, max_source_tokens=3)).evaluate(
            compiler_commit="fixture:mixed-retention", checkpoint_declarations=fixture.declarations())
    directory = tmp_path_factory.mktemp("mixed-retention-artifacts")
    for name, artifact in (("before", before), ("after", after), ("before-error", before_error), ("after-error", after_error)):
        (directory / (name + ".json")).write_text(json.dumps(artifact.to_dict(), sort_keys=True, indent=2) + "\n")
    return {"complete": (before, after), "errors": (before_error, after_error),
            "mixed_profile": fixture.helper.relational.MIXED_PROFILE}


@pytest.mark.parametrize("case", ["complete", "errors"])
def test_reviewed_mixed_retention_accepts_actual_v3_changed_checkpoint_pair(reviewed_mixed_normal_retention_artifacts, case):
    before, after = reviewed_mixed_normal_retention_artifacts[case]
    assert _producer_payload(before)["producer_outputs"] == _producer_payload(after)["producer_outputs"]
    assert before.key.digest != after.key.digest
    report = _compare_reviewed_retention(before, after)
    assert report["producer_route"] == "normal_source_producer"
    assert report["denominator"] == report["counts"]["still_incorrect"] == 3
    assert report["counts"] == {"retained": 0, "lost": 0, "gained": 0, "still_incorrect": 3}
    assert report["baseline_exact"] == report["after_exact"] == 0 and report["retention_rate"] is None
    assert report["current_admission_replayed"] is report["loaded_checkpoint_identity_verified"] is report["proof_authority"] is False
    left, right = report["before_source_generation"], report["after_source_generation"]
    assert left["fixed_commitment"] == right["fixed_commitment"]
    assert left["fixed_commitment"]["schema"] == "reviewed-decoder-source-producer-policy/v2"
    assert left["fixed_commitment"]["admission_profile"] == "complete-reviewed-mixed-sort-norm-admission/v3"
    assert left["input_receipt"] == right["input_receipt"]
    for role in ("model_checkpoint", "optimizer_checkpoint"):
        assert left["checkpoint_pair"][role]["sha256"] != right["checkpoint_pair"][role]["sha256"]
    for artifact in (before, after):
        payload = _producer_payload(artifact)
        assert all(len(row["canonical_ir"]) == 9 for row in payload["reference_population"])
        assert payload["reference_population"][2]["canonical_ir"]["profile"] == reviewed_mixed_normal_retention_artifacts["mixed_profile"]
        assert payload["admission_before"]["training_mask"] == payload["admission_after"]["evaluation_gold_mask"] == 0
    outcome = "abstained" if case == "complete" else "error"
    assert report["before_outcome_counts"][outcome] == report["after_outcome_counts"][outcome] == 3
    assert set(report["before_complete_norm_scores"]["metric_denominators"].values()) == {3}
    assert set(report["after_complete_norm_scores"]["metric_denominators"].values()) == {3}
    assert set(report["before_complete_norm_scores"]["metric_numerators"].values()) == {0}
    assert set(report["after_complete_norm_scores"]["metric_numerators"].values()) == {0}
    if case == "complete":
        assert left["input_receipt"]["target_access_performed"] is False
    else:
        assert left["input_receipt"] is None


def _recommit_mixed_retention(artifact, offered, *, prefix="reviewed-decoder-source-producer/v2:"):
    observed = offered["metadata"]["source_generation_observation"]
    digest = _producer_digest(observed["input_commitment"])
    observed["input_commitment_sha256"] = offered["metadata"]["source_generation_input_commitment_sha256"] = digest
    observed["input_profile_id"] = prefix + digest
    offered["compiler_artifact"]["reviewed_source_span_producer_evaluation"]["configuration"]["input_profile"]["profile_id"] = prefix + digest
    return _reseal_reviewed_retention(artifact, offered)


@pytest.mark.parametrize("damage", ["observation-schema", "policy-schema", "observation-profile", "missing-observation-profile",
    "policy-profile", "missing-policy-profile", "before-consumer-schema", "after-consumer-profile",
    "missing-observation", "v1-commitment-swap", "downgrade-to-v1", "unknown-normal-version",
    "checkpoint-alias", "producer-source", "source-wire", "generation-output", "fictional-mask", "heldout-purpose", "typed-role"])
def test_reviewed_mixed_retention_rejects_resealed_domain_swaps_and_frozen_input_changes(
        reviewed_mixed_normal_retention_artifacts, reviewed_normal_retention_artifacts, damage, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics
    before, after = reviewed_mixed_normal_retention_artifacts["complete"]
    offered = after.to_dict()
    payload = offered["compiler_artifact"]["reviewed_source_span_producer_evaluation"]
    config = payload["configuration"]
    observed = offered["metadata"]["source_generation_observation"]
    commitment = observed["input_commitment"]
    prefix = "reviewed-decoder-source-producer/v2:"
    if damage == "observation-schema":
        observed["schema"] = "reviewed-decoder-source-producer-observation/v1"
    elif damage == "policy-schema":
        commitment["schema"] = "reviewed-decoder-source-producer-policy/v1"
    elif damage == "observation-profile":
        observed["admission_profile"] = "complete-reviewed-norm-admission/v2"
    elif damage == "missing-observation-profile":
        observed.pop("admission_profile")
    elif damage == "policy-profile":
        commitment["admission_profile"] = "complete-reviewed-norm-admission/v2"
    elif damage == "missing-policy-profile":
        commitment.pop("admission_profile")
    elif damage == "before-consumer-schema":
        payload["admission_before"]["schema"] = _producer_consumer.REVIEWED_SCHEMA
    elif damage == "after-consumer-profile":
        payload["admission_after"]["profile"] = _producer_consumer.REVIEWED_PROFILE
    elif damage == "missing-observation":
        offered["metadata"].pop("source_generation_observation")
        offered["metadata"].pop("source_generation_input_commitment_sha256")
    elif damage == "v1-commitment-swap":
        old = reviewed_normal_retention_artifacts["complete"][1].to_dict()
        observed["input_commitment"] = old["metadata"]["source_generation_observation"]["input_commitment"]
    elif damage == "downgrade-to-v1":
        observed["schema"] = "reviewed-decoder-source-producer-observation/v1"
        observed.pop("admission_profile")
        commitment["schema"] = "reviewed-decoder-source-producer-policy/v1"
        commitment.pop("admission_profile")
        prefix = "reviewed-decoder-source-producer/v1:"
    elif damage == "unknown-normal-version":
        prefix = "reviewed-decoder-source-producer/v3:"
    elif damage == "checkpoint-alias":
        commitment["optimizer_checkpoint"] = deepcopy(commitment["model_checkpoint"])
    elif damage == "producer-source":
        commitment["source_sha256"]["worker"] = commitment["backend_identity"]["implementation_sha256"] = "f" * 64
    elif damage == "source-wire":
        observed["last_call"]["input_receipt"]["row_commitments"][0]["source_wire_sha256"] = "f" * 64
    elif damage == "generation-output":
        observed["last_call"]["raw_generation_outputs"][0]["outcome"] = "unsupported"
    elif damage == "fictional-mask":
        payload["admission_after"]["training_mask"] = 1
    elif damage == "heldout-purpose":
        config["heldout_evaluation"]["purpose"] = "declared_model_selection"
    else:
        payload["reference_population"][2]["canonical_ir"]["argument_roles"] = []
    changed = (_reseal_reviewed_retention(after, offered) if damage == "missing-observation" else
               _recommit_mixed_retention(after, offered, prefix=prefix))
    monkeypatch.setattr(legal_ir_semantic_metrics, "evaluate_complete_norm_payloads",
        lambda *_: pytest.fail("incomparable V3 source-producer panel reached retention scoring"))
    with pytest.raises(ValueError, match="normal retention|retention requires|retention references|retention observations"):
        _compare_reviewed_retention(before, changed)


def test_reviewed_mixed_retention_cannot_hide_both_normal_observations_as_a_generic_equal_profile(
        reviewed_mixed_normal_retention_artifacts, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics
    panels = []
    before, after = reviewed_mixed_normal_retention_artifacts["complete"]
    for artifact in (before, after):
        offered = artifact.to_dict()
        offered["metadata"].pop("source_generation_observation")
        offered["metadata"].pop("source_generation_input_commitment_sha256")
        offered["compiler_artifact"]["reviewed_source_span_producer_evaluation"]["configuration"]["input_profile"]["profile_id"] = "reviewed-decoder-source-producer/v2:" + "a" * 64
        panels.append(_reseal_reviewed_retention(artifact, offered))
    monkeypatch.setattr(legal_ir_semantic_metrics, "evaluate_complete_norm_payloads",
        lambda *_: pytest.fail("missing normal V3 observations fell through generic equal-profile scoring"))
    with pytest.raises(ValueError, match="normal retention"):
        _compare_reviewed_retention(*panels)


def test_reviewed_mixed_retention_full_v1_label_swap_keeps_v3_receipts_out_of_v2_domain(
        reviewed_mixed_normal_retention_artifacts, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics
    panels = []
    for artifact in reviewed_mixed_normal_retention_artifacts["complete"]:
        offered = artifact.to_dict()
        observed = offered["metadata"]["source_generation_observation"]
        observed["schema"] = "reviewed-decoder-source-producer-observation/v1"
        observed.pop("admission_profile")
        observed["input_commitment"]["schema"] = "reviewed-decoder-source-producer-policy/v1"
        observed["input_commitment"].pop("admission_profile")
        panels.append(_recommit_mixed_retention(artifact, offered, prefix="reviewed-decoder-source-producer/v1:"))
    monkeypatch.setattr(legal_ir_semantic_metrics, "evaluate_complete_norm_payloads",
        lambda *_: pytest.fail("V3 admission relabelled as the normal V1/V2 source-producer domain"))
    with pytest.raises(ValueError, match="normal retention source-producer admission domain"):
        _compare_reviewed_retention(*panels)



def _rich_v3_heldout_case(*, shared_provision=False, version="v3", shared_source_identity=False,
        defer_heldout_check=False):
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_span_consumer_binding as ch
    from tests.unit.logic.autoformal import test_legal_reviewed_norm_admission_v3 as mixed
    from ipfs_datasets_py.logic.autoformal import legal_reviewed_norm_admission_v3 as admission
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_structured_retrieval as structured
    if version == "v2": admission = mixed.legacy
    purpose = ("frozen-single-mixed-sort-component-with-reviewed-TRAIN-context/v1" if version == "v3"
               else ch.owner.REVIEWED_HELDOUT_CONTEXT_PURPOSE)
    populations, replays, exposures, components = {}, {}, {}, {}
    for partition, prefix, operation in [("train", "T", "training"), ("holdout", "Q", "heldout_evaluation")]:
        texts = (["TRAIN defines covered officers by appointment to its independent coastal board.",
                  "TRAIN officers must send annual notices except when the coastal board excuses them.",
                  "TRAIN grants officers permission to inspect a register with a supervisor at an event and time."]
                 if partition == "train" else
                 ["QUERY establishes a covered officer through appointment by its separate inland council.",
                  "QUERY requires a covered officer to submit monthly statements unless an inland exemption applies.",
                  "QUERY permits covered officers to inspect records with supervisors at the designated event and time."])
        source_bindings = None
        if shared_source_identity and partition == "holdout":
            from ipfs_datasets_py.logic.autoformal import corpus_source
            source_bindings = {}
            for index, text in enumerate(texts):
                train_source = components["train"]["declaration"]["units"][index]["source_version"]
                identity = {key: train_source[key] for key in ("source_id", "release_id", "edition", "provision_id")}
                raw = text.encode("utf-8")
                source = corpus_source.build_source_version(**identity, raw_bytes=raw,
                    expected_raw_sha256=ch.source_digest(text), extracted_text=text,
                    expected_extracted_sha256=ch.source_digest(text), extraction_profile="identity/v1",
                    normalization_profile="identity/v1", media_type="text/plain")
                occurrence = corpus_source.build_source_occurrence(source,
                    expected_raw_sha256=ch.source_digest(text), extracted_text=text,
                    expected_extracted_sha256=ch.source_digest(text), start_char=0, end_char=len(text),
                    start_utf8=0, end_utf8=len(raw))
                unit_id = "fixture:rich-mixed-" + prefix.lower() + "/unit-" + str(index + 1)
                source_bindings[unit_id] = dict(source_version=source, occurrence=occurrence,
                    raw_bytes=raw, extracted_text=text)
        case = mixed.fixture.reviewed_norm_fixture_v2(mixed.legacy, fixture_namespace="rich-mixed-"+prefix.lower(),
            source_texts=texts, predicate_prefix=prefix, permitted_uses=["formalization", operation],
            source_bindings=source_bindings,
            **(dict(governing_instrument_id="fixture:common-instrument",
                    definition_provision_id="fixture:common-instrument/definition") if shared_provision else {}))
        if version == "v3":
            case["declaration"]["schema"] = admission.REVIEWED_DECLARATION_SCHEMA
            for unit in case["declaration"]["units"]: unit["relational_profile"] = mixed.relational.PROFILE
            mixed.set_mixed_ir(case)
            unit = case["declaration"]["units"][2]
            entry = case["relational_inputs"][unit["unit_id"]]
            import json
            request = json.loads(entry["request_raw"])
            def rename(value):
                if type(value) is str:
                    return prefix+value if value in ("CoveredOfficer", "InspectsRegisterAt") else value
                if type(value) is list: return [rename(item) for item in value]
                if type(value) is dict: return {key: rename(item) for key,item in value.items()}
                return value
            request = rename(request)
            request["expression"].pop("content_digest")
            request["expression"] = mixed.ast.TypedExpression.from_dict(request["expression"]).to_dict()
            raw = mixed.fixture.wire(request);pin = mixed.fixture.sha(raw)
            report = mixed.relational.prepare_mixed_relational_norm_v1(raw, expected_request_sha256=pin)
            unit["relational_request_sha256"] = pin
            case["relational_inputs"][unit["unit_id"]] = dict(request_raw=raw,report=report,
                expected_report_sha256=mixed.relational.mixed_relational_norm_report_sha256(report))
            case["preparation"] = mixed.prepare(admission, case)
            mixed.refresh_signed_reviews(case, admission)
        mixed.assert_signatures_valid(case)
        rows = [dict(id="reviewed:"+u["unit_id"],unit_id=u["unit_id"],source_text=u["source_text"],
                     canonical_ir=deepcopy(u["canonical_ir"])) for u in case["preparation"]["units"]]
        populations[partition] = rows
        replays[partition] = ch.reviewed_public_admission_inputs(mixed.fixture, admission, case)
        exposures[partition] = [dict(id=r["id"],source_text_sha256=ch.source_digest(r["source_text"]),
            canonical_ir_sha256=ch.digest(r["canonical_ir"]),
            target_exposure=("declared_supervised_training" if partition=="train" else ch.owner.REVIEWED_HELDOUT_EXPOSURE),
            provenance_ref="fixture:independent-mixed-rich-"+partition) for r in rows]
        components[partition] = case
    manifest = ch.splits.LegalIRSplitManifest(examples=tuple(ch.splits.LegalIRSplitExample.from_sample(
        dict(sample_id=r["id"],text=r["source_text"],statute_family="fictional-"+part,lineage_group_id="component-"+part))
        for part,rows in populations.items() for r in rows),
        assignments={r["id"]:part for part,rows in populations.items() for r in rows},
        config_digest=ch.source_digest("fictional reviewed mixed rich heldout split")).to_dict()
    bindings={}
    for part,rows in populations.items():
        bindings[part] = getattr(ch.owner,"prepare_reviewed_source_span_consumer_binding_"+version)(rows,
            expected_rows_sha256=ch.digest(rows),split_manifest=manifest,expected_split_manifest_sha256=ch.digest(manifest),
            admission_inputs=replays[part],expected_admission_inputs_sha256=ch.owner.reviewed_admission_inputs_sha256(replays[part]),
            exposure_records=exposures[part],expected_exposure_sha256=ch.digest(exposures[part]),
            operation="training" if part=="train" else "heldout_evaluation",allow_fictional_fixture=True,
            allow_heldout_evaluation=part=="holdout",heldout_evaluation_purpose=purpose if part=="holdout" else None)
        assert bindings[part].receipt()["status"] == "ready"
    train,query=populations["train"],populations["holdout"]
    inputs=dict(binding=bindings["train"],training_rows=train,split_manifest=manifest,
        admission_inputs=replays["train"],exposure_records=exposures["train"],
        query_rows=[dict(id=r["id"],source_text=r["source_text"]) for r in query],
        retrieval_rows=[dict(id=r["id"],source_sha256=ch.source_digest(r["source_text"]),
            index_sha256=ch.digest(train),retrieved_ids=[train[2]["id"]]) for r in query])
    payload=structured._consume_reviewed_contexts(**inputs,expected_query_rows_sha256=ch.digest(inputs["query_rows"]),
        expected_retrieval_rows_sha256=ch.digest(inputs["retrieval_rows"]),consumer=lambda x:x,
        # Adversarial evaluator cases may offer ordinary reviewed TRAIN context
        # before its heldout check. The actual evaluator must independently
        # reject that offer before invoking any producer.
        heldout_evaluation=(None if defer_heldout_check else bindings["holdout"].receipt()["heldout_evaluation"]),
        _admission_version=version)
    options=_producer_bridge_options((bindings["holdout"],query,dict(split_manifest=manifest,
        admission_inputs=replays["holdout"],exposure_records=exposures["holdout"]),None))
    options.update(allow_heldout_evaluation=True,reviewed_training_context=inputs,
        retrieved_examples={r["id"]:[dict(id=e["id"],content=e) for e in r["examples"]] for r in payload["rows"]},
        context_policy_guard=lambda _:None)
    return ch,options,populations,replays,components


def test_rich_v3_heldout_complete_mixed_context_reaches_existing_producer_without_reference_targets():
    _,options,populations,_,_=_rich_v3_heldout_case()
    calls=[]
    def producer(arguments):
        calls.append(deepcopy(arguments))
        assert all(set(r)=={"id","source_text","context"} for r in arguments)
        for row in arguments:
            examples=row["context"]["retrieved"]
            assert len(examples)==2
            assert {e["id"] for e in examples}=={r["id"] for r in (populations["train"][0],populations["train"][2])}
            assert all(e["id"] not in {r["id"] for r in populations["holdout"]} for e in examples)
            for example in examples:
                expected=next(r for r in populations["train"] if r["id"]==example["id"])
                assert example["content"]["canonical_ir"]==expected["canonical_ir"]
                assert example["content"]["source_text"]==expected["source_text"]
        return [dict(id=r["id"],outcome="abstained",candidate=None) for r in arguments]
    artifact=_producer_evaluate(options,producer)
    payload=_producer_payload(artifact)
    assert len(calls)==1
    assert payload["configuration"]["heldout_evaluation"]["inference_context_profile"] == "reviewed-mixed-sort-rich-TRAIN-context-heldout/v1"
    assert artifact.to_dict()["metrics"]["complete_norm_payload"]["denominator"]==3
    assert payload["corpus_admitted"] is payload["heldout_generalization_established"] is False


@pytest.mark.parametrize("damage", ["train_revoked","query_revoked","selection","policy"])
def test_rich_v3_heldout_rechecks_current_review_selection_and_policy_before_dispatch(damage):
    _,options,_,replays,_=_rich_v3_heldout_case()
    if damage.endswith("revoked"):
        part="train" if damage=="train_revoked" else "holdout"
        replays[part]["registry"]["keys"][0]["revoked_at_utc"]="2026-01-01T00:00:00Z"
    elif damage=="selection": options["reviewed_training_context"]["retrieval_rows"][0]["retrieved_ids"].clear()
    else:
        def deny(_): raise PermissionError("explicit fictional context denial")
        options["context_policy_guard"]=deny
    calls=[]
    with pytest.raises((ValueError,PermissionError)):
        _producer_evaluate(options,lambda args:calls.append(args))
    assert calls==[]


@pytest.mark.parametrize("damage", ["train_revoked","query_revoked","selection"])
def test_rich_v3_heldout_rechecks_both_components_after_producer_callback(damage):
    _,options,_,replays,_=_rich_v3_heldout_case()
    def producer(arguments):
        if damage.endswith("revoked"):
            part="train" if damage=="train_revoked" else "holdout"
            replays[part]["registry"]["keys"][0]["revoked_at_utc"]="2026-01-01T00:00:00Z"
        else: options["reviewed_training_context"]["retrieval_rows"][0]["retrieved_ids"].clear()
        return [dict(id=r["id"],outcome="abstained",candidate=None) for r in arguments]
    with pytest.raises(ValueError): _producer_evaluate(options,producer)


def test_rich_v3_heldout_shared_definition_provision_is_rejected_independently_of_split_labels():
    with pytest.raises(ValueError,match="share a reviewed"):
        _rich_v3_heldout_case(shared_provision=True)


def test_rich_v3_heldout_cannot_relabel_a_v2_training_binding():
    ch,options,_,_,_=_rich_v3_heldout_case()
    _,_,_,rows,consumer_options=ch.reviewed_public_consumer_case()
    old=ch.owner.prepare_reviewed_source_span_consumer_binding_v2(rows,**consumer_options)
    options["reviewed_training_context"]["binding"]=old
    calls=[]
    with pytest.raises(ValueError,match="contract"):
        _producer_evaluate(options,lambda args:calls.append(args))
    assert calls==[]


def test_rich_v3_heldout_preserves_the_original_v2_rich_context_domain():
    _,options,_,_,_=_rich_v3_heldout_case(version="v2")
    result=_producer_evaluate(options,lambda args:[dict(id=r["id"],outcome="abstained",candidate=None) for r in args])
    payload=_producer_payload(result)
    assert payload["configuration"]["heldout_evaluation"]["inference_context_profile"]=="reviewed-rich-TRAIN-context-heldout/v1"
    assert result.to_dict()["metrics"]["complete_norm_payload"]["denominator"]==3


@pytest.fixture(scope="module", params=["v2", "v3"])
def reviewed_source_group_distinct_case(request):
    return request.param, _rich_v3_heldout_case(version=request.param)


def test_reviewed_rich_heldout_source_identity_is_bound_to_current_declaration(reviewed_source_group_distinct_case):
    version, (ch, options, populations, replays, components) = reviewed_source_group_distinct_case
    heldout = options["binding"].receipt()["heldout_evaluation"]
    declarations = {unit["unit_id"]: unit for unit in components["holdout"]["declaration"]["units"]}
    for unit in heldout["dependency_group"]["source_units"]:
        source = declarations[unit["unit_id"]]["source_version"]
        assert unit["source_identity"] == {key: source[key] for key in
            ("source_id", "release_id", "edition", "provision_id")}
        assert unit["source_extracted_sha256"] == source["extracted_view"]["sha256"]
    calls = []
    def producer(arguments):
        calls.append(deepcopy(arguments))
        return [dict(id=row["id"], outcome="incomplete", candidate=None) for row in arguments]
    artifact = _producer_evaluate(options, producer)
    assert len(calls) == 1 and len(calls[0]) == 3
    assert artifact.to_dict()["metrics"]["complete_norm_payload"]["denominator"] == 3
    assert _producer_payload(artifact)["heldout_generalization_established"] is False


@pytest.mark.parametrize("version", ["v2", "v3"])
def test_reviewed_rich_heldout_shared_source_identity_rejects_before_actual_producer(version):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_structured_retrieval as structured
    ch, options, populations, replays, components = _rich_v3_heldout_case(
        version=version, shared_source_identity=True, defer_heldout_check=True)
    context = options["reviewed_training_context"]
    assert options["binding"].receipt()["status"] == context["binding"].receipt()["status"] == "ready"
    assert ch.splits.require_legal_ir_split_guard(context["split_manifest"]).passed
    assert components["train"]["declaration"]["governing_context"]["instrument_id"] != components["holdout"]["declaration"]["governing_context"]["instrument_id"]
    for train, query in zip(components["train"]["declaration"]["units"], components["holdout"]["declaration"]["units"], strict=True):
        left, right = train["source_version"], query["source_version"]
        assert all(left[key] == right[key] for key in ("source_id", "release_id", "edition", "provision_id"))
        assert left["raw_artifact"]["sha256"] != right["raw_artifact"]["sha256"]
        assert left["extracted_view"]["sha256"] != right["extracted_view"]["sha256"]
        assert train["document_revision"] != query["document_revision"]
    diagnostic = "heldout and TRAIN share a reviewed declared legal source identity"
    heldout = options["binding"].receipt()["heldout_evaluation"]
    with pytest.raises(ValueError, match=diagnostic):
        structured._require_disjoint_heldout_review(heldout, context["admission_inputs"],
            context["training_rows"], context["query_rows"],
            ch.splits.LegalIRSplitManifest.from_mapping(context["split_manifest"]), _admission_version=version)
    calls = []
    with pytest.raises(ValueError, match=diagnostic):
        _producer_evaluate(options, lambda arguments: calls.append(arguments))
    assert calls == []


@pytest.mark.parametrize("damage", ["missing_identity", "identity_type", "extra_identity_field",
    "missing_identity_field", "identity_bool", "identity_blank", "identity_nul", "identity_invalid_utf8",
    "identity_oversized", "missing_view", "view_bool", "view_uppercase"])
def test_reviewed_rich_heldout_rehashed_missing_or_malformed_source_identity_fails_closed(
        reviewed_source_group_distinct_case, damage):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_structured_retrieval as structured
    version, (ch, options, _, _, _) = reviewed_source_group_distinct_case
    context = options["reviewed_training_context"]
    heldout = options["binding"].receipt()["heldout_evaluation"]
    unit = heldout["dependency_group"]["source_units"][0]
    if damage == "missing_identity": unit.pop("source_identity")
    elif damage == "identity_type": unit["source_identity"] = list(unit["source_identity"].values())
    elif damage == "extra_identity_field": unit["source_identity"]["document_revision"] = "artifact-label"
    elif damage == "missing_identity_field": unit["source_identity"].pop("release_id")
    elif damage == "identity_bool": unit["source_identity"]["source_id"] = True
    elif damage == "identity_blank": unit["source_identity"]["edition"] = "  "
    elif damage == "identity_nul": unit["source_identity"]["provision_id"] = "fixture:\x00"
    elif damage == "identity_invalid_utf8": unit["source_identity"]["source_id"] = "\ud800"
    elif damage == "identity_oversized": unit["source_identity"]["source_id"] = "x" * 4097
    elif damage == "missing_view": unit.pop("source_extracted_sha256")
    elif damage == "view_bool": unit["source_extracted_sha256"] = False
    else: unit["source_extracted_sha256"] = unit["source_extracted_sha256"].upper()
    # Rehashing the offered receipt cannot restore the omitted source boundary.
    # The invalid-Unicode case refuses even at the existing canonical hash gate.
    with pytest.raises(ValueError, match="declared source identity|heldout source|heldout extracted view|JSON"):
        heldout["dependency_group_sha256"] = ch.digest(heldout["dependency_group"])
        structured._require_disjoint_heldout_review(heldout, context["admission_inputs"],
            context["training_rows"], context["query_rows"],
            ch.splits.LegalIRSplitManifest.from_mapping(context["split_manifest"]), _admission_version=version)


@pytest.mark.parametrize("version", ["v2", "v3"])
def test_reviewed_rich_heldout_original_provision_guard_precedes_source_identity_check(version):
    _, options, _, _, _ = _rich_v3_heldout_case(
        version=version, shared_provision=True, defer_heldout_check=True)
    calls = []
    with pytest.raises(ValueError, match="heldout and TRAIN share a reviewed statutory provision identity"):
        _producer_evaluate(options, lambda arguments: calls.append(arguments))
    assert calls == []


def _ranked_mixed_context_join(mode, *, capture=None):
    from tests.unit.logic.formalization.autoencoder import test_alignment_relation_mask_handoff as pairs
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_lane_bundle as lanes
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_structured_retrieval as structured
    import torch
    helper, options, populations, replays, components = _rich_v3_heldout_case()
    context = options["reviewed_training_context"]
    case = pairs.fixtures.reviewed_pair_fixture_v3(include_definition=True,
        reviewed_norm_case=components["train"], shared_split_manifest=context["split_manifest"],
        sample_ids_by_unit={r["unit_id"]:r["id"] for r in populations["train"]})
    args, inputs = pairs.reviewed_mask_arguments_v2(case)
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        trained = structured.joint.train_reviewed_retriever_v3(*args, **inputs, steps=1, joint_dimension=8)
        checkpoint_sha = structured.joint.checkpoint_digest(trained["checkpoint"])
        model = structured.joint.ReviewedLegalJointRetriever(trained["checkpoint"], expected_checkpoint_sha256=checkpoint_sha)
        queries = [{"id":r["id"],"split_sample_id":r["id"],"source_text":r["source_text"]} for r in populations["holdout"]]
        profile = deepcopy(inputs["preparation_inputs"]["source_lane"]["profile"])
        bindings, rows = [], []
        vector = [1.0] + [0.0]*383
        for query in queries:
            request = {"source_text":query["source_text"],"context":{"role":"none_required","text":"","bindings":{},"sha256":hashlib.sha256(b"").hexdigest()}}
            binding = {"id":query["id"],"input_sha256":lanes._digest(request),
                "encoder_text_sha256":hashlib.sha256(query["source_text"].encode()).hexdigest(),
                "status":"available","reason":None,"vector_sha256":lanes._digest(vector),
                "upstream_vector_sha256":None,"token_receipt_sha256":None}
            bindings.append(binding)
            rows.append({**binding,"input":request,"encoder_text":query["source_text"],"vector":list(vector),
                "producer_row_sha256":lanes._digest(binding)})
        role = pairs.fixtures.role
        producer = role(lanes.PRODUCER_SCHEMA,profile_sha256=lanes._digest(profile),rows=bindings,
            artifact_binding={"path":"never-opened-fictional-query-vectors.json","bytes":1,"sha256":"e"*64})
        lane = role(lanes.SCHEMA,profile=profile,producer_receipt=producer,rows=rows)
        expected = {"profile_sha256":lanes._digest(profile),"producer_receipt_sha256":lanes._digest(producer),
            "inputs":[{"id":r["id"],"input_sha256":r["input_sha256"]} for r in bindings]}
        forbidden = {r["id"]:[] for r in queries}
        inputs.update(query_source_lane=lane,expected_query_lane_bindings=expected,expected_query_split="holdout",
            forbidden_reference_formal_sha256s=forbidden,
            expected_forbidden_reference_sha256=structured.joint.checkpoint_digest(forbidden),top_k=4,mode="joint")
        from tests.unit.optimizers.logic_theorem_optimizer import test_legal_structured_retrieval as rich
        offered = rich._rich_consumer_inputs(pairs,case,version="v3")
        prepared = structured.prepare_reviewed_ranked_training_context_v3(model,queries,*args,
            retrieval_inputs=inputs,example_consumer_inputs=offered)
        context = prepared["context_inputs"]
        complete = structured._consume_reviewed_contexts(**context,
            expected_query_rows_sha256=structured.reviewed_context_inputs_sha256(context["query_rows"]),
            expected_retrieval_rows_sha256=structured.reviewed_context_inputs_sha256(context["retrieval_rows"]),
            consumer=lambda value:value,heldout_evaluation=options["binding"].receipt()["heldout_evaluation"],_admission_version="v3")
        options["reviewed_training_context"] = context
        options["retrieved_examples"] = {r["id"]:[{"id":e["id"],"content":e} for e in r["examples"]] for r in complete["rows"]}
        options["checkpoint_declarations"]["encoder"] = {"id":"fictional:actual-reviewed-joint-projection","sha256":checkpoint_sha}
        provenance = prepared["selection_provenance"]
        assert provenance["checkpoint_sha256"] == checkpoint_sha
        assert provenance["decoder_context_admitted"] is False
        calls = []
        def callback(arguments):
            calls.append(deepcopy(arguments))
            assert len(arguments)==3
            for row in arguments:
                assert set(row)=={"id","source_text","context"}
                examples = row["context"]["retrieved"]
                assert len(examples)==3
                assert {e["id"] for e in examples} == {r["id"] for r in populations["train"]}
                for e in examples:
                    original = next(r for r in populations["train"] if r["id"]==e["id"])
                    assert e["content"]["canonical_ir"]==original["canonical_ir"]
                    assert e["content"]["source_text"]==original["source_text"]
            return [{"id":row["id"],"outcome":"abstained","candidate":None} for row in arguments]
        if mode=="train-revoked":
            context["admission_inputs"]["registry"]["keys"][0]["revoked_at_utc"]="2026-01-01T00:00:00Z"
        elif mode=="query-revoked":
            options["admission_inputs"]["registry"]["keys"][0]["revoked_at_utc"]="2026-01-01T00:00:00Z"
        elif mode=="policy-denied":
            def deny(_):raise PermissionError("independent ranked-context policy denied")
            options["context_policy_guard"] = deny
        if mode!="healthy":
            with pytest.raises((ValueError,PermissionError)):_producer_evaluate(options,callback)
            assert calls==[]
        else:
            artifact = _producer_evaluate(options,callback)
            payload = _producer_payload(artifact)
            assert len(calls)==1
            assert payload["configuration"]["checkpoint_declarations"]["encoder"]["sha256"]==checkpoint_sha
            assert artifact.to_dict()["metrics"]["complete_norm_payload"]["denominator"]==3
            assert payload["corpus_admitted"] is payload["heldout_generalization_established"] is False
        assert structured.joint.checkpoint_digest(model.checkpoint)==checkpoint_sha
        if capture is not None:
            assert mode == "healthy"
            capture({"projection_checkpoint":deepcopy(model.checkpoint),
                "producer_artifact":artifact.to_dict(), "ranking_provenance":deepcopy(provenance)})
    finally:
        torch.set_num_threads(previous)


@pytest.mark.parametrize("mode", ["healthy", "train-revoked", "query-revoked", "policy-denied"])
def test_ranked_mixed_context_joins_existing_heldout_producer_with_independent_review(mode):
    _ranked_mixed_context_join(mode)


def test_ranked_mixed_context_retains_exact_projection_producer_and_selection(tmp_path):
    import json
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_joint_retrieval as joint
    retained = []
    _ranked_mixed_context_join("healthy", capture=lambda value:retained.append(deepcopy(value)))
    assert len(retained) == 1
    actual = retained[0]
    raw = {name:json.dumps(value,sort_keys=True,ensure_ascii=True,allow_nan=False).encode("utf-8")
           for name,value in actual.items()}
    assert sum(len(value) for value in raw.values()) < 800*1024
    for name,value in raw.items():
        path = tmp_path/(name+".json")
        path.write_bytes(value)
        assert json.loads(path.read_bytes()) == actual[name]
    checkpoint = json.loads((tmp_path/"projection_checkpoint.json").read_bytes())
    digest = joint.checkpoint_digest(checkpoint)
    restored = joint.ReviewedLegalJointRetriever(checkpoint,expected_checkpoint_sha256=digest)
    assert restored.checkpoint == checkpoint
    provenance = json.loads((tmp_path/"ranking_provenance.json").read_bytes())
    assert provenance["checkpoint_sha256"] == digest
    artifact = json.loads((tmp_path/"producer_artifact.json").read_bytes())
    payload = artifact["compiler_artifact"]["reviewed_source_span_producer_evaluation"]
    assert payload["configuration"]["checkpoint_declarations"]["encoder"]["sha256"] == digest
    assert payload["producer_authenticity_verified"] is payload["loaded_checkpoint_identity_verified"] is False
    assert payload["corpus_admitted"] is payload["heldout_generalization_established"] is False
    assert artifact["metrics"]["complete_norm_payload"]["denominator"] == 3


@pytest.mark.parametrize("fixture_name", ("reviewed_normal_retention_artifacts",
                                         "reviewed_mixed_normal_retention_artifacts"))
@pytest.mark.parametrize("damage", ("eos_token_id", "max_source_tokens", "record_count", "proof_authority"))
def test_reviewed_retention_rejects_json_type_aliases_in_frozen_tokenized_receipts(
        request, fixture_name, damage, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics

    before, after = request.getfixturevalue(fixture_name)["complete"]
    offered = after.to_dict()
    receipt = offered["metadata"]["source_generation_observation"]["last_call"]["input_receipt"]
    if damage == "eos_token_id":
        token_id = receipt["tokenizer_contract"][damage]
        assert type(token_id) is int
        receipt["tokenizer_contract"][damage] = False if token_id == 0 else float(token_id)
    elif damage == "proof_authority":
        assert receipt[damage] is False
        receipt[damage] = 0
    else:
        assert type(receipt[damage]) is int
        receipt[damage] = float(receipt[damage])
    original = after.to_dict()["metadata"]["source_generation_observation"]["last_call"]["input_receipt"]
    assert original == receipt and _producer_digest(original) != _producer_digest(receipt)
    changed = type(after).from_dict(offered)
    monkeypatch.setattr(legal_ir_semantic_metrics, "evaluate_complete_norm_payloads",
        lambda *_: pytest.fail("typed frozen input mismatch reached retention scoring"))
    with pytest.raises(ValueError, match="normal retention observations differ in frozen producer inputs or tokenized source"):
        _compare_reviewed_retention(before, changed)


@pytest.mark.parametrize("field", ("max_source_tokens", "max_output_tokens"))
def test_reviewed_mixed_retention_rejects_json_type_aliases_after_consistent_recommit(
        reviewed_mixed_normal_retention_artifacts, field, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics

    before, after = reviewed_mixed_normal_retention_artifacts["complete"]
    offered = after.to_dict()
    commitment = offered["metadata"]["source_generation_observation"]["input_commitment"]
    assert type(commitment[field]) is int
    commitment[field] = float(commitment[field])
    changed = _recommit_mixed_retention(after, offered)
    assert changed.metadata["source_generation_input_commitment_sha256"] != after.metadata["source_generation_input_commitment_sha256"]
    monkeypatch.setattr(legal_ir_semantic_metrics, "evaluate_complete_norm_payloads",
        lambda *_: pytest.fail("typed recommitted producer input mismatch reached retention scoring"))
    with pytest.raises(ValueError, match="normal retention observations differ in frozen producer inputs or tokenized source"):
        _compare_reviewed_retention(before, changed)


@pytest.mark.parametrize("fixture_name", ("reviewed_retention_artifacts", "reviewed_normal_retention_artifacts",
                                         "reviewed_mixed_normal_retention_artifacts"))
def test_reviewed_retention_ignores_object_key_order_for_frozen_json(request, fixture_name):
    fixture = request.getfixturevalue(fixture_name)
    before, after = fixture[:2] if fixture_name == "reviewed_retention_artifacts" else fixture["complete"]

    def reverse_objects(value):
        if type(value) is dict:
            return {key: reverse_objects(value[key]) for key in reversed(value)}
        if type(value) is list:
            return [reverse_objects(item) for item in value]
        return value

    reordered = type(after).from_dict(reverse_objects(after.to_dict()))
    assert _producer_digest(reordered.to_dict()) == _producer_digest(after.to_dict())
    assert _compare_reviewed_retention(before, reordered) == _compare_reviewed_retention(before, after)


def test_reviewed_retention_keeps_changed_outputs_and_checkpoint_as_variables(reviewed_retention_artifacts):
    before, after, _ = reviewed_retention_artifacts
    assert _producer_payload(before)["producer_outputs"] != _producer_payload(after)["producer_outputs"]
    assert before.key.state_hash != after.key.state_hash
    report = _compare_reviewed_retention(before, after)
    assert report["counts"] == {"retained": 1, "lost": 1, "gained": 1, "still_incorrect": 0}
    assert report["proof_authority"] is False


# Explicit generation-policy retention integration. These are fictional native
# engineering fixtures, with no pretrained, statutory, or learning-gain claim.
@pytest.fixture(scope="module")
def reviewed_profiled_retention_artifacts(tmp_path_factory):
    import json
    from copy import deepcopy
    from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_training_worker as models
    directory = tmp_path_factory.mktemp("profiled-retention-pair")
    fixture = models._reviewed_profiled_source_fixture(directory)
    policy = models._reviewed_profiled_generation_policy()

    def declarations():
        return {"encoder": fixture.base.declarations()["encoder"],
            "decoder": {"id": fixture.options["backend_identity"]["backend_id"],
                "sha256": fixture.options["model_checkpoint"].sha256}}

    def evaluate(*, preflight_error=False):
        options = dict(fixture.options)
        if preflight_error:
            options["max_source_tokens"] = 3
        producer = models.worker.make_reviewed_decoder_source_producer_v3(
            fixture.runtime, **options, generation_policy=deepcopy(policy))
        artifact = producer.evaluate(compiler_commit="fixture:profiled-retention", checkpoint_declarations=declarations())
        observed = artifact.to_dict()["metadata"]["source_generation_observation"]
        assert observed["schema"] == "reviewed-decoder-source-producer-observation/v3"
        assert observed["input_profile_id"].startswith("reviewed-decoder-profiled-producer/v1:")
        assert observed["input_commitment"]["schema"] == "reviewed-decoder-source-producer-policy/v3"
        assert observed["input_commitment"]["generation_policy"] == policy
        assert observed["calls"] == 1
        assert observed["last_call"]["entry_pair_match"] is observed["last_call"]["exit_pair_match"] is True
        assert observed["last_call"]["completed"] is (not preflight_error)
        assert artifact.to_dict()["metrics"]["complete_norm_payload"]["denominator"] == 3
        return artifact

    before, before_error = evaluate(), evaluate(preflight_error=True)
    with fixture.native.torch.no_grad():
        next(fixture.backend.model.parameters()).add_(0.25)
    changed = fixture.backend.snapshot_checkpoint()
    for role,filename in (("model_checkpoint","changed-profiled-model.pt"),
                          ("optimizer_checkpoint","changed-profiled-optimizer.pt")):
        raw = changed["model_state" if role=="model_checkpoint" else "optimizer_state"]
        fixture.options[role] = models.worker.CheckpointArtifact.from_dict(
            models._complete_reviewed_artifact(directory/filename,raw))
    after, after_error = evaluate(), evaluate(preflight_error=True)
    records = tmp_path_factory.mktemp("profiled-retention-artifacts")
    for name,artifact in (("before",before),("after",after),("before-error",before_error),("after-error",after_error)):
        (records/(name+".json")).write_text(json.dumps(artifact.to_dict(),sort_keys=True,indent=2)+"\n")
    return {"normal":(before,after),"errors":(before_error,after_error),"generation_policy":policy}


def _recommit_profiled_retention(artifact, offered, *, prefix="reviewed-decoder-profiled-producer/v1:"):
    observed = offered["metadata"]["source_generation_observation"]
    digest = _producer_digest(observed["input_commitment"])
    observed["input_commitment_sha256"] = offered["metadata"]["source_generation_input_commitment_sha256"] = digest
    observed["input_profile_id"] = prefix+digest
    offered["compiler_artifact"]["reviewed_source_span_producer_evaluation"]["configuration"]["input_profile"]["profile_id"] = prefix+digest
    return _reseal_reviewed_retention(artifact,offered)


@pytest.mark.parametrize("case",("normal","errors"))
def test_reviewed_profiled_retention_accepts_genuine_factory_checkpoint_pair(reviewed_profiled_retention_artifacts,case):
    before,after = reviewed_profiled_retention_artifacts[case]
    # RED must reach the existing unsupported-profile guard from genuinely
    # generated V3 artifacts, rather than relabeling an old T5 observation.
    report = _compare_reviewed_retention(before,after)
    assert report["producer_route"] == "normal_source_producer"
    assert report["denominator"] == report["counts"]["still_incorrect"] == 3
    assert report["baseline_exact"] == report["after_exact"] == 0 and report["retention_rate"] is None
    left,right = report["before_source_generation"],report["after_source_generation"]
    assert left["fixed_commitment"] == right["fixed_commitment"]
    assert left["fixed_commitment"]["schema"] == "reviewed-decoder-source-producer-policy/v3"
    assert left["fixed_commitment"]["generation_policy"] == reviewed_profiled_retention_artifacts["generation_policy"]
    assert left["checkpoint_pair"]["model_checkpoint"]["sha256"] != right["checkpoint_pair"]["model_checkpoint"]["sha256"]
    assert left["checkpoint_pair"]["optimizer_checkpoint"]["path"] != right["checkpoint_pair"]["optimizer_checkpoint"]["path"]
    assert left["input_receipt"] == right["input_receipt"]
    assert all(report[key] is False for key in ("current_admission_replayed","loaded_checkpoint_identity_verified","proof_authority"))
    if case=="normal":
        assert left["input_receipt"]["target_access_performed"] is False
    else:
        assert left["input_receipt"] is None
        assert report["before_outcome_counts"]["error"] == report["after_outcome_counts"]["error"] == 3
    assert set(report["before_complete_norm_scores"]["metric_denominators"].values()) == {3}
    assert set(report["after_complete_norm_scores"]["metric_denominators"].values()) == {3}


@pytest.mark.parametrize("damage",("commitment-schema","observation-schema","missing-policy","generation-policy-schema",
    "cache-profile","conditioning-profile","seconds-bool","seconds-zero","seconds-negative","seconds-string",
    "seconds-overflow","extra-generation-field","rich-context-fields","admission-profile"))
def test_reviewed_profiled_retention_rejects_same_resealed_invalid_policy_before_scoring(
        reviewed_profiled_retention_artifacts,damage,monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics
    panels = []
    for artifact in reviewed_profiled_retention_artifacts["normal"]:
        offered = artifact.to_dict()
        observed = offered["metadata"]["source_generation_observation"]
        commitment = observed["input_commitment"]
        policy = commitment["generation_policy"]
        if damage=="commitment-schema": commitment["schema"]="reviewed-decoder-source-producer-policy/v2"
        elif damage=="observation-schema": observed["schema"]="reviewed-decoder-source-producer-observation/v2"
        elif damage=="missing-policy": del commitment["generation_policy"]
        elif damage=="generation-policy-schema": policy["schema"]="unknown-generation-policy/v1"
        elif damage=="cache-profile": policy["generation_profile"]="full-prefix/v1"
        elif damage=="conditioning-profile": policy["conditioning_profile"]="raw-source-bos/v1"
        elif damage=="seconds-bool": policy["max_generation_seconds"]=True
        elif damage=="seconds-zero": policy["max_generation_seconds"]=0
        elif damage=="seconds-negative": policy["max_generation_seconds"]=-1
        elif damage=="seconds-string": policy["max_generation_seconds"]="1.0"
        elif damage=="seconds-overflow": policy["max_generation_seconds"]=10**1000
        elif damage=="extra-generation-field": policy["caller_answer_prefix"]="forbidden"
        elif damage=="rich-context-fields":
            commitment.update(context_profile="reviewed-complete-TRAIN-context/v1",supplied_context_supported="complete_replayed_TRAIN_rich_examples")
        else:
            observed["admission_profile"]=commitment["admission_profile"]="different-admission-profile"
        panels.append(_recommit_profiled_retention(artifact,offered))
    monkeypatch.setattr(legal_ir_semantic_metrics,"evaluate_complete_norm_payloads",
        lambda *_:pytest.fail("same resealed invalid profiled policy reached retention scoring"))
    expected = ("normal retention requires the complete observed source generation" if damage=="observation-schema" else
        "normal retention source-producer admission domain differs" if damage=="admission-profile" else
        "normal retention source-generation commitment or derived profile differs" if damage in
            ("commitment-schema","missing-policy","rich-context-fields") else
        "normal retention profiled generation policy differs")
    with pytest.raises(ValueError,match=expected):
        _compare_reviewed_retention(*panels)


@pytest.mark.parametrize("damage",("seconds-changed","seconds-integer-alias","source-budget","output-budget",
    "source-code","fixed-asset","tokenizer","source-wire","generation-output","checkpoint-alias"))
def test_reviewed_profiled_retention_rejects_changed_frozen_inputs_after_recommit(
        reviewed_profiled_retention_artifacts,damage,monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics
    before,after = reviewed_profiled_retention_artifacts["normal"]
    offered = after.to_dict()
    observed = offered["metadata"]["source_generation_observation"]
    commitment = observed["input_commitment"]
    if damage=="seconds-changed": commitment["generation_policy"]["max_generation_seconds"]=2.0
    elif damage=="seconds-integer-alias": commitment["generation_policy"]["max_generation_seconds"]=1
    elif damage in ("source-budget","output-budget"):
        commitment["max_source_tokens" if damage=="source-budget" else "max_output_tokens"]+=1
    elif damage=="source-code":
        commitment["source_sha256"]["worker"]=commitment["backend_identity"]["implementation_sha256"]="f"*64
    elif damage=="fixed-asset": commitment["assets"][-1]["sha256"]="f"*64
    elif damage=="tokenizer": observed["last_call"]["input_receipt"]["tokenizer_contract"]["pipeline_sha256"]="f"*64
    elif damage=="source-wire": observed["last_call"]["input_receipt"]["row_commitments"][0]["source_wire_sha256"]="f"*64
    elif damage=="generation-output": observed["last_call"]["raw_generation_outputs"][0]["outcome"]="unsupported"
    else: commitment["assets"][0]={**commitment["model_checkpoint"],"sha256":"f"*64}
    changed = _recommit_profiled_retention(after,offered)
    monkeypatch.setattr(legal_ir_semantic_metrics,"evaluate_complete_norm_payloads",
        lambda *_:pytest.fail("changed profiled producer inputs reached retention scoring"))
    expected = ("normal retention producer policy differs from evaluator inputs" if damage in("source-budget","output-budget") else
        "normal retention outputs differ from observed generation" if damage=="generation-output" else
        "normal retention asset conflicts with checkpoint identity" if damage=="checkpoint-alias" else
        "normal retention observations differ in frozen producer inputs or tokenized source")
    with pytest.raises(ValueError,match=expected):
        _compare_reviewed_retention(before,changed)


@pytest.mark.parametrize("damage",("derived-profile","commitment-hash","missing-observation","downgrade-prefix"))
def test_reviewed_profiled_retention_rejects_observation_commitment_and_route_swaps(
        reviewed_profiled_retention_artifacts,damage,monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics
    before,after = reviewed_profiled_retention_artifacts["normal"]
    offered = after.to_dict()
    if damage=="derived-profile":
        offered["compiler_artifact"]["reviewed_source_span_producer_evaluation"]["configuration"]["input_profile"]["profile_id"]+="changed"
    elif damage=="commitment-hash": offered["metadata"]["source_generation_input_commitment_sha256"]="f"*64
    elif damage=="missing-observation": del offered["metadata"]["source_generation_observation"]
    changed = (_recommit_profiled_retention(after,offered,prefix="reviewed-decoder-source-producer/v2:")
        if damage=="downgrade-prefix" else _reseal_reviewed_retention(after,offered))
    monkeypatch.setattr(legal_ir_semantic_metrics,"evaluate_complete_norm_payloads",
        lambda *_:pytest.fail("swapped profiled observation reached retention scoring"))
    expected = ("normal retention requires the complete observed source generation" if damage in("missing-observation","downgrade-prefix") else
        "normal retention source-generation commitment or derived profile differs")
    with pytest.raises(ValueError,match=expected):
        _compare_reviewed_retention(before,changed)


@pytest.mark.parametrize("case",("normal","errors"))
def test_reviewed_profiled_retention_accepts_reordered_policy_object_keys(reviewed_profiled_retention_artifacts,case):
    before,after = reviewed_profiled_retention_artifacts[case]
    def reverse(value):
        if type(value) is dict:return {key:reverse(value[key])for key in reversed(value)}
        if type(value) is list:return [reverse(item)for item in value]
        return value
    reordered = type(after).from_dict(reverse(after.to_dict()))
    assert _producer_digest(reordered.to_dict()) == _producer_digest(after.to_dict())
    assert _compare_reviewed_retention(before,reordered) == _compare_reviewed_retention(before,after)


@pytest.mark.parametrize("seconds",(float("nan"),float("inf"),float("-inf")),ids=("nan","positive-infinity","negative-infinity"))
def test_reviewed_profiled_retention_nonfinite_policy_cannot_form_an_ordinary_artifact(
        reviewed_profiled_retention_artifacts,seconds):
    # This is an upstream ordinary-JSON rejection, not comparer/policy credit.
    _,after = reviewed_profiled_retention_artifacts["normal"]
    offered = after.to_dict()
    offered["metadata"]["source_generation_observation"]["input_commitment"]["generation_policy"]["max_generation_seconds"]=seconds
    with pytest.raises(ValueError,match="Out of range float values|non-finite|nonfinite|finite"):
        _recommit_profiled_retention(after,offered)


def test_reviewed_profiled_retention_metadata_comparison_does_not_import_numeric_worker(
        reviewed_profiled_retention_artifacts,monkeypatch):
    import builtins
    before,after = reviewed_profiled_retention_artifacts["normal"]
    original = builtins.__import__
    def metadata_only(name,*args,**kwargs):
        if name.split(".",1)[0] in("torch","transformers","tokenizers") or name.endswith("autoencoder_training_worker"):
            pytest.fail("retention metadata comparison imported numerical worker/runtime")
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,"__import__",metadata_only)
    assert _compare_reviewed_retention(before,after)["denominator"] == 3


# Explicit Qwen2 source-only retention. Tiny actual native models and fictional
# reviewed sources test software contracts; they establish no pretrained gain.
@pytest.fixture(scope="module")
def reviewed_Qwen2_retention_artifacts(tmp_path_factory):
    import json
    from copy import deepcopy
    from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_training_worker as models
    directory = tmp_path_factory.mktemp("qwen2-retention-pair")
    fixture = models._reviewed_profiled_source_fixture(directory, model_profile="builtin-qwen2-bfloat16/v1")
    policy = models._reviewed_Qwen2_generation_policy()
    witnesses = []

    def declarations():
        return {"encoder": fixture.base.declarations()["encoder"],
            "decoder": {"id": fixture.options["backend_identity"]["backend_id"],
                "sha256": fixture.options["model_checkpoint"].sha256}}

    def evaluate(*, preflight_error=False):
        options = dict(fixture.options)
        if preflight_error:
            options["max_source_tokens"] = 3
        producer = models.worker.make_reviewed_decoder_source_producer_v3(
            fixture.runtime, **options, generation_policy=deepcopy(policy))
        forwards = []
        def native_forward(model, args, kwargs):
            assert "labels" not in kwargs
            forwards.append({"input_tokens": int(kwargs["input_ids"].shape[1]), "labels_present": False})
        hook = fixture.backend.model.register_forward_pre_hook(native_forward, with_kwargs=True)
        try:
            artifact = producer.evaluate(compiler_commit="fixture:Qwen2-retention", checkpoint_declarations=declarations())
        finally:
            hook.remove()
        observed = artifact.to_dict()["metadata"]["source_generation_observation"]
        assert observed["schema"] == "reviewed-decoder-source-producer-observation/v4"
        assert observed["input_profile_id"].startswith("reviewed-decoder-qwen2-profiled-producer/v1:")
        assert observed["input_commitment"]["schema"] == "reviewed-decoder-source-producer-policy/v4"
        assert observed["input_commitment"]["runtime_profile"] == "builtin-qwen2-bfloat16/v1"
        assert observed["input_commitment"]["generation_policy"] == policy
        assert observed["calls"] == 1
        call = observed["last_call"]
        assert call["entry_pair_match"] is call["exit_pair_match"] is True
        assert call["completed"] is (not preflight_error)
        assert artifact.to_dict()["metrics"]["complete_norm_payload"]["denominator"] == 3
        if preflight_error:
            assert forwards == [] and call["raw_generation_outputs"] is None and call["input_receipt"] is None
        else:
            outputs = call["raw_generation_outputs"]
            assert len(outputs) == 3 and all(len(row["generated_token_ids"]) >= 2 for row in outputs)
            assert len(forwards) == sum(len(row["generated_token_ids"]) - 1 for row in outputs)
            assert call["input_receipt"]["schema"] == "reviewed-decoder-generation-input-receipt/v1"
        witnesses.append({"preflight_error": preflight_error, "forwards": forwards,
            "observation": observed, "fictional_fixture_only": True, "legal_or_pretrained_quality": False})
        return artifact

    before, before_error = evaluate(), evaluate(preflight_error=True)
    with fixture.native.torch.no_grad():
        next(fixture.backend.model.parameters()).add_(0.25)
    changed = fixture.backend.snapshot_checkpoint()
    for role, filename in (("model_checkpoint", "changed-qwen2-model.pt"),
                           ("optimizer_checkpoint", "changed-qwen2-optimizer.pt")):
        raw = changed["model_state" if role == "model_checkpoint" else "optimizer_state"]
        fixture.options[role] = models.worker.CheckpointArtifact.from_dict(
            models._complete_reviewed_artifact(directory / filename, raw))
    after, after_error = evaluate(), evaluate(preflight_error=True)
    for name, artifact in (("before", before), ("after", after),
                           ("before-error", before_error), ("after-error", after_error)):
        (directory / (name + ".json")).write_text(json.dumps(artifact.to_dict(), sort_keys=True, indent=2) + "\n")
    (directory / "native-forward-witnesses.json").write_text(json.dumps(witnesses, sort_keys=True, indent=2) + "\n")
    return {"normal": (before, after), "errors": (before_error, after_error), "generation_policy": policy}


def _recommit_Qwen2_retention(artifact, offered, *, prefix="reviewed-decoder-qwen2-profiled-producer/v1:"):
    return _recommit_profiled_retention(artifact, offered, prefix=prefix)


@pytest.mark.parametrize("case", ("normal", "errors"))
def test_reviewed_Qwen2_retention_accepts_genuine_factory_checkpoint_pair(reviewed_Qwen2_retention_artifacts, case):
    # The fixture preserves genuine Qwen2 v4 observations and both
    # healthy and preflight-error outcomes across the checkpoint change.
    before, after = reviewed_Qwen2_retention_artifacts[case]
    report = _compare_reviewed_retention(before, after)
    assert report["producer_route"] == "normal_source_producer"
    assert report["denominator"] == report["counts"]["still_incorrect"] == 3
    assert report["baseline_exact"] == report["after_exact"] == 0 and report["retention_rate"] is None
    left, right = report["before_source_generation"], report["after_source_generation"]
    assert left["fixed_commitment"] == right["fixed_commitment"]
    assert left["fixed_commitment"]["schema"] == "reviewed-decoder-source-producer-policy/v4"
    assert left["fixed_commitment"]["runtime_profile"] == "builtin-qwen2-bfloat16/v1"
    assert left["fixed_commitment"]["generation_policy"] == reviewed_Qwen2_retention_artifacts["generation_policy"]
    assert left["checkpoint_pair"]["model_checkpoint"]["sha256"] != right["checkpoint_pair"]["model_checkpoint"]["sha256"]
    assert left["checkpoint_pair"]["optimizer_checkpoint"]["path"] != right["checkpoint_pair"]["optimizer_checkpoint"]["path"]
    assert left["input_receipt"] == right["input_receipt"]
    assert all(report[key] is False for key in ("current_admission_replayed", "loaded_checkpoint_identity_verified", "proof_authority"))
    if case == "normal":
        assert left["input_receipt"]["target_access_performed"] is False
    else:
        assert left["input_receipt"] is None
        assert report["before_outcome_counts"]["error"] == report["after_outcome_counts"]["error"] == 3
    assert set(report["before_complete_norm_scores"]["metric_denominators"].values()) == {3}
    assert set(report["after_complete_norm_scores"]["metric_denominators"].values()) == {3}


@pytest.mark.parametrize("damage", ("observation-schema", "commitment-schema", "runtime-missing", "runtime-wrong",
    "runtime-type", "extra-commitment", "policy-schema", "cache", "conditioning", "context-missing", "context-wrong",
    "context-type", "policy-extra", "seconds-bool", "seconds-zero", "seconds-string", "seconds-overflow", "rich-fields"))
def test_reviewed_Qwen2_retention_rejects_resealed_invalid_contract_before_scoring(
        reviewed_Qwen2_retention_artifacts, damage, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics
    panels = []
    for artifact in reviewed_Qwen2_retention_artifacts["normal"]:
        offered = artifact.to_dict(); observed = offered["metadata"]["source_generation_observation"]
        commitment = observed["input_commitment"]; policy = commitment["generation_policy"]
        if damage == "observation-schema": observed["schema"] = "reviewed-decoder-source-producer-observation/v3"
        elif damage == "commitment-schema": commitment["schema"] = "reviewed-decoder-source-producer-policy/v3"
        elif damage == "runtime-missing": commitment.pop("runtime_profile")
        elif damage == "runtime-wrong": commitment["runtime_profile"] = "builtin-llama-bfloat16/v1"
        elif damage == "runtime-type": commitment["runtime_profile"] = True
        elif damage == "extra-commitment": commitment["caller_answer"] = "forbidden"
        elif damage == "policy-schema": policy["schema"] = "reviewed-decoder-generation-policy/v1"
        elif damage == "cache": policy["generation_profile"] = "builtin-llama-dynamic-kv/v1"
        elif damage == "conditioning": policy["conditioning_profile"] = "chatml-complete-legal-ir/v1"
        elif damage == "context-missing": policy.pop("context_budget_profile")
        elif damage == "context-wrong": policy["context_budget_profile"] = "unknown"
        elif damage == "context-type": policy["context_budget_profile"] = 8192
        elif damage == "policy-extra": policy["query_target"] = "forbidden"
        elif damage == "seconds-bool": policy["max_generation_seconds"] = True
        elif damage == "seconds-zero": policy["max_generation_seconds"] = 0
        elif damage == "seconds-string": policy["max_generation_seconds"] = "1.0"
        elif damage == "seconds-overflow": policy["max_generation_seconds"] = 10**1000
        else: commitment.update(context_profile="reviewed-complete-TRAIN-context/v1", supplied_context_supported="complete_replayed_TRAIN_rich_examples")
        panels.append(_recommit_Qwen2_retention(artifact, offered))
    monkeypatch.setattr(legal_ir_semantic_metrics, "evaluate_complete_norm_payloads", lambda *_: pytest.fail("invalid Qwen2 contract reached scorer"))
    with pytest.raises(ValueError, match="normal retention"):
        _compare_reviewed_retention(*panels)


@pytest.mark.parametrize("damage", ("seconds", "seconds-json-type", "source-budget", "output-budget", "source-code", "tokenizer", "source-wire", "receipt-json-type"))
def test_reviewed_Qwen2_retention_freezes_inputs_and_tokenized_receipt(
        reviewed_Qwen2_retention_artifacts, damage, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics
    before, after = reviewed_Qwen2_retention_artifacts["normal"]
    offered = after.to_dict(); observed = offered["metadata"]["source_generation_observation"]
    commitment = observed["input_commitment"]; receipt = observed["last_call"]["input_receipt"]
    if damage == "seconds": commitment["generation_policy"]["max_generation_seconds"] = 2.0
    elif damage == "seconds-json-type": commitment["generation_policy"]["max_generation_seconds"] = 1
    elif damage in ("source-budget", "output-budget"): commitment["max_source_tokens" if damage == "source-budget" else "max_output_tokens"] += 1
    elif damage == "source-code": commitment["source_sha256"]["worker"] = commitment["backend_identity"]["implementation_sha256"] = "f" * 64
    elif damage == "tokenizer": receipt["tokenizer_contract"]["pipeline_sha256"] = "f" * 64
    elif damage == "source-wire": receipt["row_commitments"][0]["source_wire_sha256"] = "f" * 64
    else: receipt["record_count"] = float(receipt["record_count"])
    changed = _recommit_Qwen2_retention(after, offered)
    monkeypatch.setattr(legal_ir_semantic_metrics, "evaluate_complete_norm_payloads", lambda *_: pytest.fail("changed Qwen2 frozen input reached scorer"))
    with pytest.raises(ValueError, match="normal retention"):
        _compare_reviewed_retention(before, changed)


@pytest.mark.parametrize("damage", ("Llama-prefix", "v2-prefix", "missing-observation", "both-stripped"))
def test_reviewed_Qwen2_retention_refuses_downgrades_and_missing_observations(
        reviewed_Qwen2_retention_artifacts, damage, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics
    panels = []
    for artifact in reviewed_Qwen2_retention_artifacts["normal"]:
        offered = artifact.to_dict()
        if damage in ("Llama-prefix", "v2-prefix"):
            prefix = "reviewed-decoder-profiled-producer/v1:" if damage == "Llama-prefix" else "reviewed-decoder-source-producer/v2:"
            changed = _recommit_Qwen2_retention(artifact, offered, prefix=prefix)
        else:
            offered["metadata"].pop("source_generation_observation")
            if damage == "both-stripped": offered["metadata"].pop("source_generation_input_commitment_sha256")
            changed = _reseal_reviewed_retention(artifact, offered)
        panels.append(changed)
    monkeypatch.setattr(legal_ir_semantic_metrics, "evaluate_complete_norm_payloads", lambda *_: pytest.fail("Qwen2 downgrade reached scorer"))
    with pytest.raises(ValueError, match="normal retention"):
        _compare_reviewed_retention(*panels)


def test_reviewed_Qwen2_retention_metadata_only_and_object_key_order(reviewed_Qwen2_retention_artifacts, monkeypatch):
    import builtins
    before, after = reviewed_Qwen2_retention_artifacts["normal"]
    def reverse(value):
        if type(value) is dict: return {key: reverse(value[key]) for key in reversed(value)}
        if type(value) is list: return [reverse(item) for item in value]
        return value
    reordered = type(after).from_dict(reverse(after.to_dict()))
    original = builtins.__import__
    def metadata_only(name, *args, **kwargs):
        if name.split(".", 1)[0] in ("torch", "transformers", "tokenizers") or name.endswith("autoencoder_training_worker"):
            pytest.fail("Qwen2 retention imported numerical owner")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", metadata_only)
    assert _producer_digest(reordered.to_dict()) == _producer_digest(after.to_dict())
    assert _compare_reviewed_retention(before, reordered) == _compare_reviewed_retention(before, after)


@pytest.mark.parametrize("mixed", [False, True])
def test_reviewed_producer_typed_structure_opt_in_binds_reports_and_cache(mixed):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics as metrics
    _, options, populations, _, _ = _rich_v3_heldout_case()
    rows = populations["holdout"];calls = []
    def producer(arguments):
        calls.append(deepcopy(arguments))
        assert all(set(row) == {"id", "source_text", "context"} for row in arguments)
        outputs = _producer_exact_outputs(rows)  # Scripted fixture, never model-quality evidence.
        if mixed:
            outputs[1]["candidate"]["typed_expression"]["content_digest"] = "0" * 64
            outputs[2].update(candidate=None, outcome="incomplete")
        return outputs
    legacy = _producer_evaluate(options, producer)
    artifact = _producer_owner.evaluate_reviewed_source_span_producer_artifact(
        **options, producer=producer, typed_structure_profile=metrics.CANONICAL_TYPED_STRUCTURE_PROFILE)
    payload = _producer_payload(artifact);report = artifact.to_dict()["metrics"]["canonical_typed_structure"]
    assert len(calls) == 2 and calls[0] == calls[1]
    assert legacy.key != artifact.key
    assert "canonical_typed_structure" not in legacy.to_dict()["metrics"]
    assert _producer_payload(legacy)["formal_checks_status"] == "not_performed"
    assert report == payload["typed_structure_comparison"] and report["denominator"] == 3
    assert report["counts"] == ({"canonical_formula": 1, "invalid_complete": 1, "not_checked": 1} if mixed
        else {"canonical_formula": 3, "invalid_complete": 0, "not_checked": 0})
    assert payload["formal_checks_status"] == "canonical_typed_structure_only_no_native_proof"
    assert payload["native_proof_verified"] is payload["source_fidelity_proved"] is payload["corpus_admitted"] is False
    assert payload["accepted_semantic_count"] is None
    assert payload["configuration"]["typed_structure_profile"] == metrics.CANONICAL_TYPED_STRUCTURE_PROFILE
    assert legacy.to_dict()["metrics"]["complete_norm_payload"] == artifact.to_dict()["metrics"]["complete_norm_payload"]


@pytest.mark.parametrize("profile", [False, 1, {}, "unknown"])
def test_reviewed_producer_typed_structure_invalid_profile_refuses_before_callback(monkeypatch, profile):
    case = _producer_reviewed_case(monkeypatch);options = _producer_bridge_options(case)
    with pytest.raises(ValueError, match="typed-structure profile"):
        _producer_owner.evaluate_reviewed_source_span_producer_artifact(**options,
            typed_structure_profile=profile, producer=lambda _: pytest.fail("invalid audit profile dispatched"))


def test_reviewed_producer_typed_structure_references_check_before_callback(monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics as metrics
    # This legacy isolated-admission fixture intentionally has only a root-kind
    # sketch. Its existing exact-payload path remains valid within that scope.
    case = _producer_reviewed_case(monkeypatch);options = _producer_bridge_options(case)
    with pytest.raises(ValueError, match="reference"):
        _producer_owner.evaluate_reviewed_source_span_producer_artifact(**options,
            typed_structure_profile=metrics.CANONICAL_TYPED_STRUCTURE_PROFILE,
            producer=lambda _: pytest.fail("noncanonical reference dispatched"))


def _candidate_audit_fixture():
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as candidate_owner
    _, options, populations, _, components = _rich_v3_heldout_case()
    declaration = components['holdout']['declaration']
    # Known facts originate in source declarations and caller selection, never
    # in reference targets or generated candidates. These are fictional inputs.
    known = {'reviewed:' + unit['unit_id']: {
        'known_source_binding': {'source_version_cid': unit['source_version']['record_cid'],
            'occurrence_cid': unit['occurrence']['record_cid'], 'document_revision': unit['document_revision']},
        'known_governing_context': deepcopy(declaration['governing_context']),
        'known_selection_context': {'schema': candidate_owner.CANDIDATE_SELECTION_SCHEMA,
            'selection_mode': 'identifier_only', 'interpretation_id': declaration['interpretation_id']}}
        for unit in declaration['units']}
    return options, populations['holdout'], known, candidate_owner.CANDIDATE_SYNTAX_PROFILE_V2


@pytest.mark.parametrize('mixed', [False, True])
def test_reviewed_producer_complete_candidate_audit_binds_source_selection_and_cache(mixed):
    options, rows, known, profile = _candidate_audit_fixture()
    calls = []
    def producer(arguments):
        calls.append(deepcopy(arguments))
        assert all(set(row) == {'id', 'source_text', 'context'} for row in arguments)
        outputs = _producer_exact_outputs(rows)  # Scripted software fixture only.
        if mixed:
            outputs[1]['candidate']['source_binding']['document_revision'] = 'fixture:wrong-revision'
            outputs[2].update(candidate=None, outcome='incomplete')
        return outputs
    legacy = _producer_evaluate(options, producer)
    artifact = _producer_owner.evaluate_reviewed_source_span_producer_artifact(**options, producer=producer,
        candidate_syntax_profile=profile, known_candidate_inputs=known)
    payload = _producer_payload(artifact)
    report = artifact.to_dict()['metrics']['complete_candidate_syntax']
    assert report == payload['candidate_syntax_comparison']
    assert report['denominator'] == 3
    assert report['counts'] == ({'syntax_validated_unreviewed': 1, 'invalid_complete': 1,
        'unsupported_complete': 0, 'not_checked': 1} if mixed else {'syntax_validated_unreviewed': 2,
        'invalid_complete': 0, 'unsupported_complete': 1, 'not_checked': 0})
    assert report['reference_counts'] == {'syntax_validated_unreviewed': 2, 'unsupported': 1}
    assert report['known_inputs_sha256'] == _producer_digest(known)
    assert report['legal_admission_or_proof_authority'] is report['semantic_selection_supported'] is False
    assert report['training_mask'] == report['evaluation_gold_mask'] == 0
    assert calls[0] == calls[1] and legacy.key != artifact.key
    assert 'complete_candidate_syntax' not in legacy.to_dict()['metrics']
    assert payload['configuration']['candidate_syntax_profile'] == profile
    assert payload['configuration']['known_candidate_inputs_sha256'] == _producer_digest(known)
    assert payload['formal_checks_status'] == 'complete_candidate_syntax_only_no_native_proof'
    assert payload['native_proof_verified'] is payload['source_fidelity_proved'] is payload['corpus_admitted'] is False
    assert legacy.to_dict()['metrics']['complete_norm_payload'] == artifact.to_dict()['metrics']['complete_norm_payload']


@pytest.mark.parametrize('damage', ['profile', 'missing', 'extra', 'selection', 'source', 'context', 'extra-fact'])
def test_reviewed_producer_complete_candidate_audit_preflights_independent_facts(damage):
    options, rows, known, profile = _candidate_audit_fixture()
    if damage == 'profile': profile = 'unknown'
    elif damage == 'missing': known.pop(rows[0]['id'])
    elif damage == 'extra': known['unexpected'] = deepcopy(known[rows[0]['id']])
    elif damage == 'selection': known[rows[0]['id']]['known_selection_context']['interpretation_id'] = 'fixture:wrong-selection'
    elif damage == 'source': known[rows[0]['id']]['known_source_binding']['document_revision'] = 'fixture:wrong-revision'
    elif damage == 'context': known[rows[0]['id']]['known_governing_context']['governing_edition'] = 'fixture:wrong-edition'
    else: known[rows[0]['id']]['reference_target'] = rows[0]['canonical_ir']
    with pytest.raises(ValueError):
        _producer_owner.evaluate_reviewed_source_span_producer_artifact(**options,
            candidate_syntax_profile=profile, known_candidate_inputs=known,
            producer=lambda _: pytest.fail('invalid known facts reached producer'))


@pytest.mark.parametrize('which', ['profile-only', 'facts-only'])
def test_reviewed_producer_complete_candidate_audit_requires_explicit_pair(which):
    options, _, known, profile = _candidate_audit_fixture()
    with pytest.raises(ValueError):
        _producer_owner.evaluate_reviewed_source_span_producer_artifact(**options,
            **({'candidate_syntax_profile': profile} if which == 'profile-only' else {'known_candidate_inputs': known}),
            producer=lambda _: pytest.fail('partial audit request dispatched'))


def test_reviewed_producer_complete_candidate_audit_detects_callback_fact_mutation():
    options, rows, known, profile = _candidate_audit_fixture()
    def producer(_):
        known[rows[0]['id']]['known_selection_context']['interpretation_id'] = 'fixture:mutated-during-callback'
        return _producer_exact_outputs(rows)
    with pytest.raises(ValueError, match='changed during callback'):
        _producer_owner.evaluate_reviewed_source_span_producer_artifact(**options, producer=producer,
            candidate_syntax_profile=profile, known_candidate_inputs=known)


@pytest.mark.parametrize('outcome', ['incomplete', 'unsupported', 'invalid', 'abstained', 'error'])
def test_reviewed_producer_complete_candidate_audit_preserves_noncomplete_denominators(outcome):
    options, rows, known, profile = _candidate_audit_fixture()
    def producer(_):
        return [dict(id=row['id'], outcome=outcome, candidate=None) for row in rows]
    artifact = _producer_owner.evaluate_reviewed_source_span_producer_artifact(**options, producer=producer,
        candidate_syntax_profile=profile, known_candidate_inputs=known)
    report = artifact.to_dict()['metrics']['complete_candidate_syntax']
    assert report['denominator'] == report['counts']['not_checked'] == 3
    assert report['syntax_validated_rate'] == 0
    assert [row['outcome'] for row in report['cases']] == [outcome] * 3


def test_reviewed_producer_complete_candidate_audit_combines_with_typed_structure():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics as metrics
    options, rows, known, profile = _candidate_audit_fixture()
    artifact = _producer_owner.evaluate_reviewed_source_span_producer_artifact(**options,
        producer=lambda _: _producer_exact_outputs(rows), candidate_syntax_profile=profile,
        known_candidate_inputs=known, typed_structure_profile=metrics.CANONICAL_TYPED_STRUCTURE_PROFILE)
    reports = artifact.to_dict()['metrics'];payload = _producer_payload(artifact)
    assert reports['canonical_typed_structure']['counts']['canonical_formula'] == 3
    assert reports['complete_candidate_syntax']['counts']['syntax_validated_unreviewed'] == 2
    assert reports['complete_candidate_syntax']['counts']['unsupported_complete'] == 1
    assert payload['formal_checks_status'] == 'canonical_typed_and_complete_candidate_syntax_only_no_native_proof'
    assert reports['complete_candidate_syntax']['schema'] in artifact.key.metric_schema
    assert reports['canonical_typed_structure']['schema'] in artifact.key.metric_schema


def test_reviewed_producer_complete_candidate_audit_keeps_callback_errors():
    options, _, known, profile = _candidate_audit_fixture()
    def producer(_):
        raise RuntimeError('fictional callback failure')
    artifact = _producer_owner.evaluate_reviewed_source_span_producer_artifact(**options, producer=producer,
        candidate_syntax_profile=profile, known_candidate_inputs=known)
    assert artifact.to_dict()['metrics']['complete_candidate_syntax']['counts']['not_checked'] == 3
    assert _producer_payload(artifact)['producer_exception_type'] == 'RuntimeError'


def test_reviewed_producer_mixed_candidate_v3_explicit_scope_has_distinct_cache():
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as candidate_owner
    options, rows, known, old_profile = _candidate_audit_fixture()
    def producer(_): return _producer_exact_outputs(rows)
    old = _producer_owner.evaluate_reviewed_source_span_producer_artifact(**options, producer=producer,
        candidate_syntax_profile=old_profile, known_candidate_inputs=known)
    new = _producer_owner.evaluate_reviewed_source_span_producer_artifact(**options, producer=producer,
        candidate_syntax_profile=candidate_owner.CANDIDATE_SYNTAX_PROFILE_V3, known_candidate_inputs=known)
    left = old.to_dict()['metrics']['complete_candidate_syntax']
    right = new.to_dict()['metrics']['complete_candidate_syntax']
    assert left['counts']['unsupported_complete'] == left['reference_counts']['unsupported'] == 1
    assert right['counts'] == {'syntax_validated_unreviewed': 3, 'unsupported_complete': 0,
        'invalid_complete': 0, 'not_checked': 0}
    assert right['reference_counts'] == {'syntax_validated_unreviewed': 3, 'unsupported': 0}
    assert right['denominator'] == 3 and right['profile'] == candidate_owner.CANDIDATE_SYNTAX_PROFILE_V3
    assert old.key != new.key
    assert right['semantic_use_eligible'] is right['legal_admission_or_proof_authority'] is False
    assert right['training_mask'] == right['evaluation_gold_mask'] == 0
    assert old.to_dict()['metrics']['complete_norm_payload'] == new.to_dict()['metrics']['complete_norm_payload']


@pytest.mark.parametrize('damage', ['missing-role', 'unknown-profile', 'wrong-selection'])
def test_reviewed_producer_mixed_candidate_v3_preserves_invalid_or_unsupported_outputs(damage):
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as candidate_owner
    options, rows, known, _ = _candidate_audit_fixture()
    def producer(_):
        outputs = _producer_exact_outputs(rows); candidate = outputs[2]['candidate']
        if damage == 'missing-role': candidate['argument_roles'][1]['roles'].pop()
        elif damage == 'unknown-profile': candidate['profile'] = 'unrecognized-many-sorted/v999'
        else: candidate['interpretation_id'] = 'fixture:unselected-candidate'
        return outputs
    artifact = _producer_owner.evaluate_reviewed_source_span_producer_artifact(**options, producer=producer,
        candidate_syntax_profile=candidate_owner.CANDIDATE_SYNTAX_PROFILE_V3, known_candidate_inputs=known)
    report = artifact.to_dict()['metrics']['complete_candidate_syntax']
    assert report['denominator'] == 3 and report['counts']['syntax_validated_unreviewed'] == 2
    assert report['counts']['unsupported_complete' if damage == 'unknown-profile' else 'invalid_complete'] == 1
    assert report['candidate_repaired'] is False


def test_reviewed_producer_mixed_candidate_v3_syntax_does_not_award_role_fidelity():
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as candidate_owner
    options, rows, known, _ = _candidate_audit_fixture()
    def producer(_):
        outputs = _producer_exact_outputs(rows)
        roles = outputs[2]['candidate']['argument_roles'][1]['roles']
        roles[0], roles[1] = roles[1], roles[0]
        return outputs
    artifact = _producer_owner.evaluate_reviewed_source_span_producer_artifact(**options, producer=producer,
        candidate_syntax_profile=candidate_owner.CANDIDATE_SYNTAX_PROFILE_V3, known_candidate_inputs=known)
    reports = artifact.to_dict()['metrics']
    assert reports['complete_candidate_syntax']['counts']['syntax_validated_unreviewed'] == 3
    assert reports['complete_norm_payload']['metric_numerators']['ordered_argument_roles_exact'] == 2
    assert reports['complete_candidate_syntax']['source_fidelity_proved'] is False


def test_reviewed_producer_mixed_candidate_v3_preflights_caller_selection():
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1 as candidate_owner
    options, rows, known, _ = _candidate_audit_fixture()
    known[rows[2]['id']]['known_selection_context']['interpretation_id'] = 'fixture:different-caller-choice'
    with pytest.raises(ValueError, match='differs'):
        _producer_owner.evaluate_reviewed_source_span_producer_artifact(**options,
            candidate_syntax_profile=candidate_owner.CANDIDATE_SYNTAX_PROFILE_V3, known_candidate_inputs=known,
            producer=lambda _: pytest.fail('mismatched caller facts reached producer'))
