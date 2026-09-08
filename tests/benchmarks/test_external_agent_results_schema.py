"""EAAEF-152: results schema forbids simulated-as-live claims."""

from __future__ import annotations

from pathlib import Path

DOC = Path(__file__).resolve().parents[2] / "docs/benchmarks/external_agent_fabric_results.md"


def test_results_doc_forbids_simulated_live_evidence() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert "not** live evidence" in text or "not live evidence" in text.lower()
    assert "actual" in text.lower()
