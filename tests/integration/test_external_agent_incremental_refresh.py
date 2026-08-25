"""EAAEF-101: incremental invalidation and reuse receipts."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.analysis.external_agent_incremental_refresh import refresh, RefreshError


def test_refresh_emits_invalidations_and_reuse() -> None:
    report = refresh(changed_paths=("a.py", "a.py"), indexes=("ast", "tests"))
    assert report["invalidations"] == ["a.py"]
    assert "bm25" in report["reuse"]
    with pytest.raises(RefreshError):
        refresh(changed_paths=(), indexes=("nope",))
