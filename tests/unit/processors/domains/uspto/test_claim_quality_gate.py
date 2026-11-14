"""PAAR-012: gate automated conflict authority on claim OCR quality."""

from __future__ import annotations

from ipfs_datasets_py.processors.domains.uspto.claim_limitation_model import (
    AuthorityMode,
    QualityGateCode,
    assess_quality_gate,
    graph_is_authoritative_for_conflict,
    parse_claims_to_graph,
)

CLEAN = """\
1. A method comprising receiving a first input signal from a sensor and
generating an alert when the first input signal exceeds a configured threshold.

2. The method of claim 1, wherein the configured threshold is stored in memory.
"""

LOW_QUALITY = (
    "1. A mth �\ufffd $$$ ### c0mpr1sing rec3iv "
    "s1gnal xxx.\n"
    "2. Th of claim 9 wh3r3in thr3sh.\n"
)


def test_below_threshold_forces_review_required() -> None:
    graph = parse_claims_to_graph(LOW_QUALITY, quality_threshold=0.90)
    assert graph.quality.review_required is True
    assert graph.quality.authority_mode is AuthorityMode.REVIEW_REQUIRED
    assert graph.quality.gate_code in {
        QualityGateCode.BELOW_THRESHOLD,
        QualityGateCode.STRUCTURAL_FAILURE,
        QualityGateCode.REVIEW_REQUIRED,
        QualityGateCode.EMPTY,
    }
    assert graph_is_authoritative_for_conflict(graph) is False


def test_gate_code_explicit_on_empty() -> None:
    q = assess_quality_gate(claims=[], threshold=0.55)
    assert q.gate_code is QualityGateCode.EMPTY
    assert q.authority_mode is AuthorityMode.REVIEW_REQUIRED
    assert q.low_ocr_quality is True


def test_pass_gate_on_clean_claims() -> None:
    graph = parse_claims_to_graph(CLEAN, quality_threshold=0.35)
    # Clean prose should clear a low threshold
    assert graph.quality.quality_score >= 0.35
    assert graph.quality.gate_code is QualityGateCode.PASS
    assert graph.quality.authority_mode is AuthorityMode.AUTHORITATIVE
    assert graph.quality.low_ocr_quality is False
    assert graph_is_authoritative_for_conflict(graph) is True


def test_orchestrator_cannot_claim_high_confidence_on_low_ocr() -> None:
    """Acceptance: below-threshold quality → review_required authority mode."""
    graph = parse_claims_to_graph(LOW_QUALITY, quality_threshold=0.99)
    assert graph.quality.gate_code != QualityGateCode.PASS or graph.quality.quality_score < 0.99
    # Explicit code present for orchestrator binding
    assert graph.quality.gate_code.value
    assert graph.quality.to_dict()["review_required"] is True
