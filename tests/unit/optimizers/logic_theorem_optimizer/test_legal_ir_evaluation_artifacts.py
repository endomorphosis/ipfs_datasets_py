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
        normalize=lambda item: (bump("normalize") or item.text.lower()),
        tokenize=lambda text: (bump("tokenize") or text.split()),
        embed=lambda item: (bump("embed") or item.embedding_vector),
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
        baseline_metrics=lambda result, _item: (
            bump("baseline_metric") or dict(result.losses)
        ),
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
    assert store.summary()["avoided_node_materializations"] == 7 * len(
        LEGAL_IR_ARTIFACT_NODE_ORDER
    )


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
