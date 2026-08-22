"""EAAEF-023: imported history vs reconstructed truth."""

from __future__ import annotations

from ipfs_datasets_py.analysis.agent_history_reconciliation import classify, reconcile


def test_classifies_present_stale_missing_and_history_only() -> None:
    report = reconcile(
        [
            {
                "path": "a.py",
                "referenced_id": "sha256:" + "a" * 64,
                "reconstructed_id": "sha256:" + "a" * 64,
                "in_export": True,
            },
            {
                "path": "b.py",
                "referenced_id": "sha256:" + "b" * 64,
                "reconstructed_id": "sha256:" + "c" * 64,
                "in_export": True,
            },
            {
                "path": "gone.py",
                "referenced_id": "sha256:" + "d" * 64,
                "reconstructed_id": "",
                "in_export": False,
            },
            {
                "path": "only-in-session.py",
                "referenced_id": "sha256:" + "e" * 64,
                "reconstructed_id": "",
                "in_export": True,
            },
        ]
    )
    kinds = [item["classification"] for item in report["items"]]
    assert kinds == ["present", "stale", "missing", "history_only"]
    assert report["counts"]["present"] == 1
    assert classify(referenced_id="x", reconstructed_id="x", in_export=True) == "present"
