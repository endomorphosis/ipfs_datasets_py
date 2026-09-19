"""SAWM-038 multi-view program-world projections."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.software_contracts.semantic_state.program_views import (
    ProgramViewError,
    VIEWS,
    build_program_world_view,
)


def test_distinct_views_require_privacy_and_freshness() -> None:
    view = build_program_world_view(
        {"view": "cfg", "source_cid": "bafy-src", "privacy_admitted": True}
    )
    assert view.view == "cfg"
    assert "source_change" in view.invalidators
    assert set(VIEWS) >= {"text", "ast", "cfg", "proof", "procedure"}


def test_stale_or_unadmitted_views_fail() -> None:
    with pytest.raises(ProgramViewError, match="privacy"):
        build_program_world_view(
            {"view": "text", "source_cid": "bafy-src", "privacy_admitted": False}
        )
    with pytest.raises(ProgramViewError, match="stale"):
        build_program_world_view(
            {
                "view": "text",
                "source_cid": "bafy-src",
                "privacy_admitted": True,
                "freshness": "stale",
            }
        )
