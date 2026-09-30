"""Streamed feature space v2. No Hub access and no legal sample worker."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features_v2 as streamed


def _descriptor() -> dict:
    return {
        "logic_family": "first_order",
        "profile": "default",
        "properties": [],
        "view_role": None,
        "representation_kind": "domain_structured_formula",
        "producer_id": "test",
    }


def _space(source_count: int, digest: str = "ab" * 32):
    projection = "intent-route/facts/v1"
    return streamed.build_streamed_feature_space(
        domain="intent_ir",
        projection_ids=[projection],
        projections={projection: _descriptor()},
        columns=[[projection, "token"]],
        training_sources=[f"{index:064x}" for index in range(source_count)],
        excluded_projection_ids=[],
        training_targets_sha256=digest,
    )


def test_minibatch_steps_are_not_epochs_and_the_source_cap_is_closed() -> None:
    assert streamed.MAX_FEATURES == 4096
    assert streamed.MAX_FEATURES is features.MAX_FEATURES
    assert streamed.SPACE_SCHEMA != features.SPACE_SCHEMA
    space = _space(1025)
    training_ids = list(space["training_sources"])
    tuning_ids = [f"{index:064x}" for index in range(20_000, 20_002)]
    width = len(space["columns"])
    result = streamed.train_streamed_projection_features(
        space,
        [[1.0] * width for _ in training_ids],
        training_ids,
        [[1.0] * width for _ in tuning_ids],
        tuning_ids,
        minibatch_size=1024,
        tuning_targets_sha256="cd" * 32,
        epochs=1,
        latent_width=2,
        learning_rate=0.02,
        max_seconds=3600,
        seed=1729,
    )
    latest = result["latest_state"]
    assert latest["completed_epochs"] == 1
    assert latest["completed_steps"] == 2
    assert latest["completed_steps"] != latest["completed_epochs"]
    assert all(moment["step"] == 2 for moment in latest["adam"])
    assert result["report"]["qualified"] is False
    assert result["report"]["embedding_revision"] == "v2"
    bounded = _space(streamed.MAX_SOURCES, "ef" * 32)
    assert len(bounded["training_sources"]) == streamed.MAX_SOURCES
    with pytest.raises(features.ProjectionFeatureError, match="source bound"):
        _space(streamed.MAX_SOURCES + 1)
    with pytest.raises(features.ProjectionFeatureError, match="unsupported feature space"):
        features.train_projection_features(None, space, [], [])
    with pytest.raises(features.ProjectionFeatureError, match="v2 training deadline exceeds its bound"):
        streamed.train_streamed_projection_features(
            space,
            [[1.0]],
            training_ids[:1],
            [[1.0]],
            tuning_ids[:1],
            minibatch_size=1,
            tuning_targets_sha256="cd" * 32,
            epochs=1,
            latent_width=2,
            max_seconds=14401,
            seed=1729,
        )
