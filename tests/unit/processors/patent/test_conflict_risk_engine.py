"""Unit tests for PAAR conflict risk engine (PAAR-020 / PAAR-021)."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.processors.domains.patent.conflict_risk_engine import (
    CONFLICT_RISK_REPORT_SCHEMA,
    DEFAULT_REQUIRED_CORPORA,
    REVIEW_ONLY_CONFLICT_RISK_DISCLAIMER,
    ConflictRiskReport,
    CoverageGap,
    RiskLevel,
    RiskMethod,
    aggregate_matter_risk,
    lexical_overlap,
    max_risk,
    overlap_to_risk,
    required_unsearched_gaps,
    score_conflict_risk,
    score_limitation_hit_cell,
    score_from_distinguishability_matrix,
)
from ipfs_datasets_py.processors.domains.uspto.claim_limitation_model import (
    parse_claims_to_graph,
)


SAMPLE_CLAIMS = """\
1. A method comprising:
receiving a sensor signal from a multi-axis accelerometer; and
generating an alert when the sensor signal exceeds a configurable threshold.

2. The method of claim 1, wherein the threshold is user-configurable.
"""


def test_risk_vocabulary_closed_set() -> None:
    assert {r.value for r in RiskLevel} == {"unknown", "low", "medium", "high"}


def test_lexical_high_overlap_scores_high() -> None:
    lim = "receiving a sensor signal from a multi-axis accelerometer"
    hit = (
        "The device includes receiving a sensor signal from a multi-axis "
        "accelerometer mounted on the housing."
    )
    cell = score_limitation_hit_cell(
        limitation_id="lim:c1-1",
        claim_number=1,
        limitation_text=lim,
        hit_id="hit-1",
        hit_text=hit,
    )
    assert cell.risk in {RiskLevel.HIGH, RiskLevel.MEDIUM}
    assert cell.method is RiskMethod.LEXICAL
    assert cell.limitation_quote
    assert cell.hit_quote
    assert cell.lexical_overlap > 0.2
    assert "patentab" not in cell.notes.lower() or "not" in cell.notes.lower()


def test_lexical_unrelated_scores_low() -> None:
    cell = score_limitation_hit_cell(
        limitation_id="lim:c1-1",
        claim_number=1,
        limitation_text="receiving a sensor signal from a multi-axis accelerometer",
        hit_id="hit-2",
        hit_text="A bicycle chain lubrication system with a drip reservoir.",
    )
    assert cell.risk is RiskLevel.LOW
    assert cell.method is RiskMethod.LEXICAL


def test_empty_hit_text_unknown() -> None:
    cell = score_limitation_hit_cell(
        limitation_id="lim:c1-1",
        claim_number=1,
        limitation_text="receiving a sensor signal",
        hit_id="hit-empty",
        hit_text="",
    )
    assert cell.risk is RiskLevel.UNKNOWN


def test_score_conflict_risk_from_limitations_and_hits() -> None:
    graph = parse_claims_to_graph(SAMPLE_CLAIMS)
    report = score_conflict_risk(
        application_number="16000001",
        claim_graph=graph,
        hits=[
            {
                "hit_id": "US9999999",
                "text": (
                    "receiving a sensor signal from a multi-axis accelerometer "
                    "and generating an alert when the sensor signal exceeds a "
                    "configurable threshold"
                ),
            },
            {
                "hit_id": "US1111111",
                "text": "A garden hose nozzle with adjustable spray patterns.",
            },
        ],
        coverage_gaps=[],  # no gaps → low allowed
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert report.schema == CONFLICT_RISK_REPORT_SCHEMA
    assert report.auto_file_blocked is True
    assert len(report.cells) >= 2
    assert report.content_digest
    assert len(report.content_digest) == 64
    assert report.matter_risk in {
        RiskLevel.LOW,
        RiskLevel.MEDIUM,
        RiskLevel.HIGH,
        RiskLevel.UNKNOWN,
    }
    # At least one high/medium from overlapping hit
    risks = {c.risk for c in report.cells}
    assert RiskLevel.HIGH in risks or RiskLevel.MEDIUM in risks
    payload = report.to_dict()
    assert payload["auto_file_blocked"] is True
    lower = json.dumps(payload).lower()
    # Affirmative conclusions forbidden; negative disclaimer framing allowed.
    for phrase in (
        "is patentable",
        "is novel",
        "is obvious",
        "no prior art exists",
    ):
        assert phrase not in lower
    assert "not a patentability conclusion" in lower or "not" in lower


def test_deterministic_digest() -> None:
    kwargs = dict(
        application_number="16000001",
        limitations=[
            {
                "limitation_id": "lim:c1-1",
                "claim_number": 1,
                "text": "detecting a temperature above a threshold",
            }
        ],
        hits=[{"hit_id": "H1", "text": "detecting a temperature above a threshold value"}],
        coverage_gaps=[],
        generated_at_utc="2026-08-06T00:00:00Z",
        report_id="crr:test:fixed",
    )
    r1 = score_conflict_risk(**kwargs)
    r2 = score_conflict_risk(**kwargs)
    assert r1.content_digest == r2.content_digest
    restored = ConflictRiskReport.from_dict(r1.to_dict())
    assert restored.content_digest == r1.content_digest


def test_coverage_penalty_blocks_aggregate_low() -> None:
    cells_report = score_conflict_risk(
        application_number="16000002",
        limitations=[
            {
                "limitation_id": "lim:c1-1",
                "claim_number": 1,
                "text": "a bicycle chain lubrication system",
            }
        ],
        hits=[{"hit_id": "H2", "text": "unrelated quantum cryptography protocol"}],
        coverage_gaps=[
            CoverageGap(
                kind="foreign_patent",
                status="unsearched",
                corpus="foreign_patents",
                required=True,
            ),
            CoverageGap(
                kind="npl", status="unsearched", corpus="npl", required=True
            ),
        ],
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    # Cells may be low, but matter cannot be low with required gaps
    assert cells_report.matter_risk is not RiskLevel.LOW
    assert cells_report.coverage_penalty_applied is True
    assert cells_report.matter_risk in {RiskLevel.MEDIUM, RiskLevel.UNKNOWN, RiskLevel.HIGH}


def test_coverage_penalty_waived_with_acceptance_package() -> None:
    report = score_conflict_risk(
        application_number="16000003",
        limitations=[
            {
                "limitation_id": "lim:c1-1",
                "claim_number": 1,
                "text": "a bicycle chain lubrication system",
            }
        ],
        hits=[{"hit_id": "H3", "text": "unrelated quantum cryptography protocol"}],
        coverage_gaps=[
            {"kind": "foreign_patent", "status": "unsearched", "corpus": "foreign_patents"},
            {"kind": "npl", "status": "unsearched", "corpus": "npl"},
        ],
        acceptance_package={
            "accepted": True,
            "acknowledger_id": "counsel:alice",
        },
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert report.coverage_penalty_applied is False
    assert report.matter_risk is RiskLevel.LOW


def test_aggregate_max_risk() -> None:
    assert max_risk(RiskLevel.LOW, RiskLevel.HIGH) is RiskLevel.HIGH
    assert max_risk(RiskLevel.UNKNOWN, RiskLevel.MEDIUM) is RiskLevel.MEDIUM
    assert max_risk(RiskLevel.UNKNOWN) is RiskLevel.UNKNOWN


def test_aggregate_matter_risk_unit() -> None:
    from ipfs_datasets_py.processors.domains.patent.conflict_risk_engine import (
        ConflictRiskCell,
    )

    low_cell = ConflictRiskCell(
        cell_id="c1",
        limitation_id="l1",
        claim_number=1,
        hit_id="h1",
        risk=RiskLevel.LOW,
        method=RiskMethod.LEXICAL,
        confidence=0.5,
        limitation_quote="a",
        hit_quote="b",
    )
    matter, penalty = aggregate_matter_risk(
        [low_cell],
        [
            CoverageGap(
                kind="foreign_patent",
                status="unsearched",
                corpus="foreign_patents",
            )
        ],
        required_corpora=DEFAULT_REQUIRED_CORPORA,
    )
    assert penalty is True
    assert matter is RiskLevel.MEDIUM


def test_required_unsearched_gaps() -> None:
    gaps = required_unsearched_gaps(
        [
            CoverageGap(kind="foreign_patent", status="unsearched", corpus="foreign_patents"),
            CoverageGap(kind="us_patents", status="searched", corpus="us_patents"),
            CoverageGap(kind="npl", status="unsearched", corpus="npl"),
        ]
    )
    corpora = {g.corpus for g in gaps}
    assert "foreign_patents" in corpora
    assert "npl" in corpora
    assert "us_patents" not in corpora


def test_overlap_thresholds() -> None:
    assert overlap_to_risk(0.9) is RiskLevel.HIGH
    assert overlap_to_risk(0.4) is RiskLevel.MEDIUM
    assert overlap_to_risk(0.1) is RiskLevel.LOW
    assert overlap_to_risk(0.0) is RiskLevel.LOW


def test_disclaimer_present() -> None:
    lower = REVIEW_ONLY_CONFLICT_RISK_DISCLAIMER.lower()
    assert "not" in lower and "patentability" in lower
    assert "not legal advice" in lower


def test_no_hits_matter_unknown() -> None:
    report = score_conflict_risk(
        application_number="16000004",
        limitations=[
            {"limitation_id": "lim:c1-1", "claim_number": 1, "text": "a widget"}
        ],
        hits=[],
        coverage_gaps=[],
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert report.matter_risk is RiskLevel.UNKNOWN
    assert report.cells == ()


def test_from_distinguishability_matrix() -> None:
    matrix = {
        "schema": "patlaw-distinguishability-matrix-v1",
        "documents": [
            {
                "document_id": "D1",
                "excerpt_preview": "sensor signal multi-axis accelerometer threshold",
            }
        ],
        "drafting_hints": [
            {
                "limitation_id": "lim:c1-1",
                "claim_number": 1,
                "candidate_text": "sensor signal multi-axis accelerometer threshold",
            }
        ],
        "cells": [
            {
                "limitation_id": "lim:c1-1",
                "claim_number": 1,
                "document_id": "D1",
                "lexical_overlap": 0.8,
                "shared_tokens": ["sensor", "signal", "accelerometer"],
            }
        ],
    }
    report = score_from_distinguishability_matrix(
        matrix,
        application_number="16000005",
        coverage_gaps=[],  # allow low/high without penalty for this unit check
        generated_at_utc="2026-08-06T00:00:00Z",
    )
    assert report.cells
    assert report.cells[0].risk in {RiskLevel.HIGH, RiskLevel.MEDIUM}
    assert report.cells[0].method is RiskMethod.LEXICAL


def test_phrase_ban_in_method_tags() -> None:
    cell = score_limitation_hit_cell(
        limitation_id="lim:x",
        claim_number=1,
        limitation_text="alpha beta gamma delta",
        hit_id="h",
        hit_text="alpha beta gamma delta epsilon",
    )
    d = cell.to_dict()
    assert d["method"] == "lexical"
    assert d["risk"] in {"unknown", "low", "medium", "high"}
    assert "patentable" not in json.dumps(d).lower()


def test_lexical_overlap_helper() -> None:
    ratio, shared = lexical_overlap(
        "configurable threshold sensor", "sensor threshold detector"
    )
    assert ratio > 0
    assert "sensor" in shared or "threshold" in shared
