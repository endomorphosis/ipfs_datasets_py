"""Focused State Laws historical-baseline/publication-parent role tests."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data.state_laws_publication_policy import (
    HISTORICAL_BASELINE_REVISION,
    PUBLICATION_PARENT_REVISION,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    PREVIOUS_PUBLIC_PIN as RELEASE_HISTORICAL_BASELINE_REVISION,
)
from scripts.ops.legal_data import audit_state_laws_post_publication as audit
from scripts.ops.legal_data import canary_state_laws_hf_release as canary
from scripts.ops.legal_data import check_state_laws_public_release as check
from scripts.ops.legal_data import publish_state_laws_hf_release as publish
from scripts.ops.legal_data import rehearse_state_laws_release_rollback as rollback
from scripts.ops.legal_data import seal_state_laws_prepublication as seal
from scripts.ops.legal_data import stage_state_laws_hf_release as stage


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RELEASE_POLICY_PATH = REPOSITORY_ROOT / (
    "data/agent_supervisor/legal_corpora_reindex/bundles/release_policy.json"
)
STATE_REPO = "justicedao/ipfs_state_laws"
FEDERAL_REPO = "justicedao/ipfs_federal_register"
FEDERAL_PARENT = "720668ae016cc400916dda884c9005e03618edfa"


def test_policy_keeps_historical_baseline_separate_from_publication_parent() -> None:
    assert RELEASE_HISTORICAL_BASELINE_REVISION == HISTORICAL_BASELINE_REVISION
    assert HISTORICAL_BASELINE_REVISION == (
        "42f0546acc7c6cd55627eaf51fb820d5613b9021"
    )
    assert PUBLICATION_PARENT_REVISION == (
        "78cba0ed86c3971a7b90620c6df167af8a1a6fb2"
    )
    assert HISTORICAL_BASELINE_REVISION != PUBLICATION_PARENT_REVISION

    policy = json.loads(RELEASE_POLICY_PATH.read_text(encoding="utf-8"))
    assert policy["baseline_revisions"] == {
        STATE_REPO: HISTORICAL_BASELINE_REVISION,
        FEDERAL_REPO: FEDERAL_PARENT,
    }
    assert policy["publication_parent_revisions"] == {
        STATE_REPO: PUBLICATION_PARENT_REVISION,
        FEDERAL_REPO: FEDERAL_PARENT,
    }
    assert policy["publication_authorization"]["authorized_operations"] == [
        "additive_staging_upload",
        "additive_main_upload",
    ]
    assert policy["publication_authorization"]["deletion_allowed"] is False
    assert policy["publication_authorization"]["history_rewrite_allowed"] is False


def test_operational_state_consumers_use_current_public_parent() -> None:
    assert stage.DEFAULT_BASE_PIN == PUBLICATION_PARENT_REVISION
    assert seal.PREVIOUS_PUBLIC_PIN == PUBLICATION_PARENT_REVISION
    assert publish.PREVIOUS_PUBLIC_PIN == PUBLICATION_PARENT_REVISION
    assert publish.PRODUCTION_REVISION == PUBLICATION_PARENT_REVISION
    assert canary.DEFAULT_BASE_PIN == PUBLICATION_PARENT_REVISION
    assert check.PREVIOUS_PUBLIC_PIN == PUBLICATION_PARENT_REVISION
    assert rollback.PREVIOUS_PUBLIC_PIN == PUBLICATION_PARENT_REVISION
    assert rollback.ROLLBACK_TARGET == PUBLICATION_PARENT_REVISION
    assert rollback.HISTORICAL_BASELINE_REVISION == HISTORICAL_BASELINE_REVISION
    assert audit.PRODUCTION_REVISION == PUBLICATION_PARENT_REVISION
