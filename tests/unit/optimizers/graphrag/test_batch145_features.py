"""Batch-145 feature tests.

Methods under test:
  - OntologyCritic.dimension_covariance(scores, dim_a, dim_b)
  - LogicValidator.unreachable_entities(ontology, source)
  - OntologyLearningAdapter.feedback_zscore(value)
"""
import pytest


# ---------------------------------------------------------------------------
# OntologyCritic.dimension_covariance
# ---------------------------------------------------------------------------

def _make_score(**kwargs):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    defaults = dict(
        completeness=0.5, consistency=0.5, clarity=0.5,
        granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
    )
    defaults.update(kwargs)
    return CriticScore(**defaults)


class TestDimensionCovariance:
    def setup_method(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        self.critic = OntologyCritic(use_llm=False)

    @pytest.mark.parametrize(
        "scores,dim_a,dim_b,predicate",
        [
            ([], "completeness", "clarity", lambda cov: cov == pytest.approx(0.0)),
            ([_make_score()], "completeness", "clarity", lambda cov: cov == pytest.approx(0.0)),
            # both dimensions move together
            (
                [_make_score(completeness=0.2, consistency=0.2), _make_score(completeness=0.8, consistency=0.8)],
                "completeness",
                "consistency",
                lambda cov: cov > 0,
            ),
            (
                [_make_score(completeness=0.2, consistency=0.8), _make_score(completeness=0.8, consistency=0.2)],
                "completeness",
                "consistency",
                lambda cov: cov < 0,
            ),
            (
                [_make_score(completeness=0.5, consistency=0.5), _make_score(completeness=0.5, consistency=0.7)],
                "completeness",
                "consistency",
                lambda cov: cov == pytest.approx(0.0),
            ),
        ],
    )
    def test_dimension_covariance_scenarios(self, scores, dim_a, dim_b, predicate):
        assert predicate(self.critic.dimension_covariance(scores, dim_a, dim_b))

    def test_invalid_dim_raises(self):
        s = _make_score()
        with pytest.raises(AttributeError):
            self.critic.dimension_covariance([s, s], "completeness", "nonexistent_dim")


# ---------------------------------------------------------------------------
# LogicValidator.unreachable_entities
# ---------------------------------------------------------------------------

def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


class TestUnreachableEntities:
    @pytest.mark.parametrize(
        "ontology,source,predicate",
        [
            ({}, "A", lambda result: result == []),
            (
                {
                    "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
                    "relationships": [{"subject_id": "A", "object_id": "B"}, {"subject_id": "A", "object_id": "C"}],
                },
                "A",
                lambda result: result == [],
            ),
            (
                {"entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}], "relationships": [{"subject_id": "A", "object_id": "B"}]},
                "A",
                lambda result: "C" in result,
            ),
            (
                {"entities": [{"id": "A"}, {"id": "B"}], "relationships": []},
                "A",
                lambda result: "A" not in result,
            ),
            (
                {
                    "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
                    # B->A, not A->B
                    "relationships": [{"subject_id": "B", "object_id": "A"}],
                },
                "A",
                lambda result: "B" in result and "C" in result,
            ),
        ],
    )
    def test_unreachable_entities_scenarios(self, ontology, source, predicate):
        v = _make_validator()
        assert predicate(v.unreachable_entities(ontology, source))

    def test_returns_sorted_list(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "Z"}, {"id": "M"}, {"id": "A"}],
            "relationships": [],
        }
        result = v.unreachable_entities(ont, "X")  # source not in entities
        assert result == sorted(result)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_zscore
# ---------------------------------------------------------------------------

def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(a, score):
    from unittest.mock import MagicMock
    r = MagicMock()
    r.final_score = score
    a._feedback.append(r)


class TestFeedbackZscore:
    @pytest.mark.parametrize(
        "feedback_scores,value,predicate",
        [
            ([], 0.5, lambda z: z == pytest.approx(0.0)),
            ([0.5], 0.5, lambda z: z == pytest.approx(0.0)),
            ([0.5, 0.5], 0.5, lambda z: z == pytest.approx(0.0)),
            ([0.0, 1.0], 0.5, lambda z: z == pytest.approx(0.0)),
            ([0.0, 0.5, 1.0], 0.9, lambda z: z > 0.0),
            ([0.0, 0.5, 1.0], 0.1, lambda z: z < 0.0),
        ],
    )
    def test_feedback_zscore_scenarios(self, feedback_scores, value, predicate):
        a = _make_adapter()
        for s in feedback_scores:
            _push_feedback(a, s)
        assert predicate(a.feedback_zscore(value))
