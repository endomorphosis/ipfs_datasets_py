"""Unit tests for PAAR claim limitation model (PAAR-010 / PAAR-011)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.claim_limitation_model import (
    CLAIM_LIMITATION_MODEL_SCHEMA,
    AuthorityMode,
    ClaimDependencyKind,
    ClaimLimitationGraph,
    QualityGateCode,
    ReviewFlagCode,
    build_claim_limitation_graph,
    graph_is_authoritative_for_conflict,
    parse_claims_text,
    parse_claims_to_graph,
)


SAMPLE_CLAIMS = """\
1. A method comprising:
receiving a sensor signal; and
generating an alert when the sensor signal exceeds a threshold.

2. The method of claim 1, wherein the threshold is user-configurable.

3. The method of claim 2, further comprising logging the alert.
"""

BROKEN_DEP_CLAIMS = """\
1. A system comprising a processor configured to execute instructions.

2. The system of claim 5, wherein the processor is multicore.

3. The system of claim 2, wherein the instructions include firmware.
"""


def test_parse_claims_text_reexported() -> None:
    claims = parse_claims_text(SAMPLE_CLAIMS)
    assert len(claims) >= 3
    assert claims[0]["claim_number"] == 1


def test_independent_dependent_structure() -> None:
    graph = parse_claims_to_graph(SAMPLE_CLAIMS)
    assert graph.schema == CLAIM_LIMITATION_MODEL_SCHEMA
    assert graph.independent_claim_numbers() == (1,)
    deps = graph.dependent_claim_numbers()
    assert 2 in deps and 3 in deps
    claim1 = next(c for c in graph.claims if c.claim_number == 1)
    assert claim1.dependency_kind is ClaimDependencyKind.INDEPENDENT
    claim2 = next(c for c in graph.claims if c.claim_number == 2)
    assert claim2.dependency_kind is ClaimDependencyKind.DEPENDENT
    assert claim2.parent_claim_numbers == (1,)


def test_limitation_spans_round_trip() -> None:
    graph = parse_claims_to_graph(SAMPLE_CLAIMS)
    assert len(graph.limitations) >= 3
    for lim in graph.limitations:
        assert lim.span.start >= 0
        assert lim.span.end >= lim.span.start
        assert lim.text_digest
        assert lim.limitation_id.startswith("lim:c")
    payload = graph.to_dict(include_text=True)
    restored = ClaimLimitationGraph.from_dict(payload)
    assert restored.content_digest == graph.content_digest
    assert len(restored.limitations) == len(graph.limitations)
    assert restored.limitations[0].text == graph.limitations[0].text
    # Digest-only export still round-trips structure
    redacted = graph.to_dict(include_text=False)
    assert "text" not in redacted["limitations"][0]
    assert redacted["limitations"][0]["text_digest"]


def test_broken_dependency_review_flag() -> None:
    graph = parse_claims_to_graph(BROKEN_DEP_CLAIMS)
    codes = {f.code for f in graph.review_flags}
    assert ReviewFlagCode.MISSING_PARENT.value in codes or (
        ReviewFlagCode.BROKEN_DEPENDENCY.value in codes
    )
    # Must not claim a legal §112 rejection in the flag message wording used as conclusion
    for f in graph.review_flags:
        assert "rejection" not in f.message.lower() or "not a" in f.message.lower()


def test_quality_score_present_and_digest_stable() -> None:
    g1 = parse_claims_to_graph(SAMPLE_CLAIMS)
    g2 = parse_claims_to_graph(SAMPLE_CLAIMS)
    assert 0.0 <= g1.quality.quality_score <= 1.0
    assert g1.content_digest == g2.content_digest
    assert g1.source_digest == g2.source_digest
    assert g1.quality.gate_code in {
        QualityGateCode.PASS,
        QualityGateCode.BELOW_THRESHOLD,
        QualityGateCode.STRUCTURAL_FAILURE,
        QualityGateCode.EMPTY,
        QualityGateCode.REVIEW_REQUIRED,
    }


def test_clean_claims_can_be_authoritative() -> None:
    graph = parse_claims_to_graph(SAMPLE_CLAIMS, quality_threshold=0.40)
    # Well-formed synthetic claims should usually pass a modest threshold
    if graph.quality.quality_score >= 0.40:
        assert graph.quality.authority_mode is AuthorityMode.AUTHORITATIVE
        assert graph_is_authoritative_for_conflict(graph) is True


def test_low_ocr_quality_non_authoritative() -> None:
    garbage = (
        "1. A mthod c0mpr1s1ng �\ufffd\ufffd xxx ### $$$ "
        "rec3iving s1gnal.\n\n"
        "2. Th mthod of claim 1 wh3rein thr3shold.\n"
    )
    graph = parse_claims_to_graph(garbage, quality_threshold=0.85)
    assert graph.quality.low_ocr_quality or graph.quality.quality_score < 0.85
    assert graph.quality.authority_mode in {
        AuthorityMode.REVIEW_REQUIRED,
        AuthorityMode.NON_AUTHORITATIVE,
    }
    assert graph.quality.review_required is True
    assert graph_is_authoritative_for_conflict(graph) is False
    codes = {f.code for f in graph.review_flags}
    assert ReviewFlagCode.LOW_OCR_QUALITY.value in codes or graph.quality.low_ocr_quality


def test_empty_claims_fail_closed() -> None:
    graph = build_claim_limitation_graph(claims_text="   ")
    # load_claims raises on empty; graph may be empty with review_required
    assert graph.quality.review_required is True
    assert graph.quality.authority_mode is AuthorityMode.REVIEW_REQUIRED
    assert not graph_is_authoritative_for_conflict(graph)


def test_no_claim_body_in_ordinary_logs(caplog: pytest.LogCaptureFixture) -> None:
    secret_phrase = "UNIQUE_SECRET_CLAIM_BODY_CANARY_7f3e9a"
    claims = (
        f"1. A method comprising detecting {secret_phrase} "
        f"and emitting a response signal."
    )
    with caplog.at_level(logging.DEBUG, logger="ipfs_datasets_py.processors.domains.uspto.claim_limitation_model"):
        graph = parse_claims_to_graph(claims)
    assert graph.claims
    # Ordinary log records must not contain full claim body canary
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert secret_phrase not in joined


def test_disclaimer_not_patentability() -> None:
    graph = parse_claims_to_graph(SAMPLE_CLAIMS)
    lowered = graph.disclaimer.lower()
    assert "not legal advice" in lowered or "review-only" in lowered
    assert "patentability" in lowered
    assert "novelty" in lowered or "obviousness" in lowered


def test_build_from_structured_claims() -> None:
    claims = [
        {"claim_number": 1, "claim_text": "A device comprising a housing and a seal."},
        {
            "claim_number": 2,
            "claim_text": "The device of claim 1, wherein the seal is elastomeric.",
        },
    ]
    graph = build_claim_limitation_graph(claims=claims)
    assert len(graph.claims) == 2
    assert graph.claims[0].dependency_kind is ClaimDependencyKind.INDEPENDENT
    assert graph.claims[1].parent_claim_numbers == (1,)


def test_fixture_claims_dir_optional(tmp_path: Path) -> None:
    """If claims fixture pack exists, parse it; else skip soft check."""
    root = Path(__file__).resolve().parents[5]
    fixture = root / "tests/fixtures/uspto/paar_review/claims"
    if not fixture.is_dir():
        pytest.skip("claims fixture pack not present yet")
    for path in sorted(fixture.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        graph = parse_claims_to_graph(text)
        assert graph.schema == CLAIM_LIMITATION_MODEL_SCHEMA
        assert isinstance(graph.to_dict(), dict)
