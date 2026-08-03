"""PATLAW-072: compact offline USPTO application-analysis replay fixtures."""

from __future__ import annotations

from .generators import (
    REPLAY_FIXTURE_DIR,
    REPLAY_MANIFEST_PATH,
    USPTO_FIXTURE_ROOT,
    ReplayBinding,
    ReplayPipelineResult,
    build_private_replay_pipeline,
    build_public_replay_pipeline,
    fixed_id_factory,
    load_replay_manifest,
    load_recipe,
    materialize_private_bundle,
    materialize_public_bundle,
    materialize_unknown_bundle,
    network_guard,
    sticky_odp_client,
)

__all__ = [
    "REPLAY_FIXTURE_DIR",
    "REPLAY_MANIFEST_PATH",
    "USPTO_FIXTURE_ROOT",
    "ReplayBinding",
    "ReplayPipelineResult",
    "build_private_replay_pipeline",
    "build_public_replay_pipeline",
    "fixed_id_factory",
    "load_replay_manifest",
    "load_recipe",
    "materialize_private_bundle",
    "materialize_public_bundle",
    "materialize_unknown_bundle",
    "network_guard",
    "sticky_odp_client",
]
