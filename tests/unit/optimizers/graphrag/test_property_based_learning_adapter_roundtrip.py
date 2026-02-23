"""Property-based round-trip tests for OntologyLearningAdapter serialization.

This indirectly covers FeedbackRecord round-trips because feedback records are
embedded in the adapter's serialized state.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings, strategies as st

from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    OntologyLearningAdapter,
)


@st.composite
def feedback_entries(draw):
    score = draw(
        st.floats(
            min_value=0.0,
            max_value=1.0,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    action = st.text(
        alphabet=st.characters(whitelist_categories=("L", "Nd", "Pc")),
        min_size=1,
        max_size=20,
    )
    actions = draw(st.lists(action, min_size=0, max_size=5))
    conf = draw(
        st.one_of(
            st.none(),
            st.floats(
                min_value=0.0,
                max_value=1.0,
                allow_nan=False,
                allow_infinity=False,
            ),
        )
    )
    return score, actions, conf


class TestOntologyLearningAdapterPropertyBasedRoundTrip:
    @settings(
        max_examples=80,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        domain=st.text(
            alphabet=st.characters(whitelist_categories=("L", "Nd", "Pc")),
            min_size=1,
            max_size=12,
        ),
        base_threshold=st.floats(
            min_value=0.1,
            max_value=0.9,
            allow_nan=False,
            allow_infinity=False,
        ),
        ema_alpha=st.floats(
            min_value=0.05,
            max_value=1.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        min_samples=st.integers(min_value=1, max_value=5),
        entries=st.lists(feedback_entries(), min_size=0, max_size=12),
    )
    def test_to_dict_from_dict_round_trip_is_lossless(
        self,
        domain: str,
        base_threshold: float,
        ema_alpha: float,
        min_samples: int,
        entries,
    ):
        adapter = OntologyLearningAdapter(
            domain=domain,
            base_threshold=base_threshold,
            ema_alpha=ema_alpha,
            min_samples=min_samples,
        )

        for score, actions, conf in entries:
            adapter.apply_feedback(
                final_score=score,
                actions=[{"action": a} for a in actions],
                confidence_at_extraction=conf,
            )

        as_dict = adapter.to_dict()
        restored = OntologyLearningAdapter.from_dict(as_dict)
        assert restored.to_dict() == as_dict
