from __future__ import annotations

from ipfs_datasets_py.optimizers.common.batch_strategy_recommender import (
    BatchStrategyRecommender,
    OntologyRef,
    StrategyRecommendation,
)


def test_recommend_strategies_batch_records_per_item_failures(monkeypatch):
    recommender = BatchStrategyRecommender()

    def _fake_recommend_for_single(ontology_ref, strategy_type=None, max_alternatives=3):
        if ontology_ref.ontology_id == "bad":
            raise RuntimeError("recommendation failed")
        return StrategyRecommendation(
            ontology_id=ontology_ref.ontology_id,
            strategy_type="split_entity",
            recommendation={"type": "split_entity"},
            confidence=0.8,
        )

    monkeypatch.setattr(BatchStrategyRecommender, "_recommend_for_single", staticmethod(_fake_recommend_for_single))

    ontologies = [
        OntologyRef(ontology_id="ok-1", data={"entities": [], "relationships": []}),
        OntologyRef(ontology_id="bad", data={"entities": [], "relationships": []}),
        OntologyRef(ontology_id="ok-2", data={"entities": [], "relationships": []}),
    ]

    recommendations, summary = recommender.recommend_strategies_batch(ontologies)

    assert len(recommendations) == 2
    assert summary.total_processed == 3
    assert summary.successful == 2
    assert summary.failed == 1
    assert summary.skipped == 0


def test_recommend_strategies_batch_applies_confidence_threshold(monkeypatch):
    recommender = BatchStrategyRecommender()

    def _fake_recommend_for_single(ontology_ref, strategy_type=None, max_alternatives=3):
        confidence = 0.3 if ontology_ref.ontology_id == "low" else 0.9
        return StrategyRecommendation(
            ontology_id=ontology_ref.ontology_id,
            strategy_type="split_entity",
            recommendation={"type": "split_entity"},
            confidence=confidence,
        )

    monkeypatch.setattr(BatchStrategyRecommender, "_recommend_for_single", staticmethod(_fake_recommend_for_single))

    ontologies = [
        OntologyRef(ontology_id="low", data={"entities": [], "relationships": []}),
        OntologyRef(ontology_id="high", data={"entities": [], "relationships": []}),
    ]

    recommendations, summary = recommender.recommend_strategies_batch(
        ontologies,
        confidence_threshold=0.5,
    )

    assert [r.ontology_id for r in recommendations] == ["high"]
    assert summary.successful == 1
    assert summary.failed == 0
    assert summary.skipped == 1
