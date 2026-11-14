"""PAAR-001: assert non-goals and report schema docs exist with required tokens."""

from __future__ import annotations

from pathlib import Path

import pytest

NON_GOALS_REL = Path("docs/operations/PAAR_NON_GOALS.md")
SCHEMAS_REL = Path("docs/architecture/paar_report_schemas.md")


def _repo_root() -> Path:
    start = Path(__file__).resolve()
    for parent in start.parents:
        if (parent / NON_GOALS_REL).is_file() and (parent / SCHEMAS_REL).is_file():
            return parent
        if (parent / "pyproject.toml").is_file() and (parent / "docs").is_dir():
            return parent
    return start.parents[5]


def _read(rel: Path) -> str:
    path = _repo_root() / rel
    assert path.is_file(), f"Missing {rel} at {path}"
    return path.read_text(encoding="utf-8")


def test_paar_non_goals_doc_exists() -> None:
    text = _read(NON_GOALS_REL)
    assert len(text.strip()) > 400
    assert "PAAR" in text


def test_paar_report_schemas_doc_exists() -> None:
    text = _read(SCHEMAS_REL)
    assert len(text.strip()) > 400


@pytest.mark.parametrize(
    "token",
    [
        "ConflictRiskReport@1",
        "ConformanceReport@1",
        "UnifiedApplicationReview@1",
        "paar.ConflictRiskReport@1",
        "paar.ConformanceReport@1",
        "paar.UnifiedApplicationReview@1",
        "unknown",
        "low",
        "medium",
        "high",
        "auto_file_blocked",
        "satisfied",
        "unsatisfied",
        "human_only",
        "ready",
        "review_required",
        "not_ready",
    ],
)
def test_schema_tokens_present(token: str) -> None:
    text = _read(SCHEMAS_REL)
    assert token in text, f"Missing schema token {token!r}"


@pytest.mark.parametrize(
    "phrase",
    [
        "Patentability conclusions are forbidden",
        "Auto Sign / Pay / Submit is forbidden",
        "Auto IDS file is forbidden",
        "fail-closed",
        "conflict risk",
        "not legal advice",
    ],
)
def test_non_goals_forbid_patentability_and_auto_file(phrase: str) -> None:
    text = _read(NON_GOALS_REL)
    assert phrase.lower() in text.lower() or phrase in text


def test_non_goals_forbid_pps_and_google_scrape() -> None:
    text = _read(NON_GOALS_REL).lower()
    assert "pps" in text or "patent public search" in text
    assert "google patents" in text
    assert "scrape" in text
    assert "forbidden" in text


def test_schemas_forbid_patentability_fields() -> None:
    text = _read(SCHEMAS_REL).lower()
    assert "patentability" in text
    assert "forbidden" in text or "never" in text
    # Must define closed risk vocabulary
    for risk in ("unknown", "low", "medium", "high"):
        assert risk in text
