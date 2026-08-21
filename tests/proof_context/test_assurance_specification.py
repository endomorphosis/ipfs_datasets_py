"""PCCE-018: datasets assurance-specification binding."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.proof_context.assurance_specification import (
    OUTCOMES,
    SPEC_INTERFACE,
    AssuranceSpecificationError,
    require_closed_outcome,
    specification_catalog,
)


def test_catalog_has_no_runtime_or_persistence_authority() -> None:
    catalog = specification_catalog()
    assert catalog["interface"] == SPEC_INTERFACE
    assert catalog["runtime_authority"] is False
    assert catalog["persistence_authority"] is False
    assert catalog["package_interface"]
    assert "omission" in catalog["outcomes"]
    assert "critical_survivor" in catalog["outcomes"]
    assert "unavailable" in catalog["outcomes"]
    assert catalog["schema_paths"]


def test_unknown_outcome_fails_closed() -> None:
    require_closed_outcome("unavailable")
    with pytest.raises(AssuranceSpecificationError):
        require_closed_outcome("passed_anyway")
    assert "human_review_required" in OUTCOMES
