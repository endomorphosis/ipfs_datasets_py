"""PAAR-140: scan PAAR modules for forbidden patentability / auto-file patterns.

Fails if PAAR-related modules assert patentability conclusions or automate
Sign/Pay/Submit. Allow-lists existing disclaimers and negative phrases
(\"not a patentability…\", \"auto_file_blocked\", etc.).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Forbidden affirmative conclusion phrases (case-insensitive).
_FORBIDDEN_PHRASES: tuple[str, ...] = (
    "is patentable",
    "is unpatentable",
    "is novel",
    "is obvious",
    "novelty conclusion",
    "obviousness conclusion",
    "patentability conclusion",
    "no prior art exists",
    "safe to file without review",
    "will be allowed",
    "renders claim obvious",
    "anticipates claim",
)

# Patterns that suggest Sign/Pay/Submit automation (affirmative).
_FORBIDDEN_AUTOMATION_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bauto[_-]?click\b", re.I),
    re.compile(r"\bautomate(?:d)?\s+sign\b", re.I),
    re.compile(r"\bautomate(?:d)?\s+pay(?:ment)?\b", re.I),
    re.compile(r"\bautomate(?:d)?\s+submit\b", re.I),
    re.compile(r"\bsign_pay_submit\s*=\s*True\b", re.I),
    re.compile(r"\bauto_file_ids\s*=\s*True\b", re.I),
    re.compile(r"\bauto_file_blocked\s*=\s*False\b", re.I),
    re.compile(r"\bfile_ids_automatically\b", re.I),
    re.compile(r"\bsubmit_to_patent_center\s*\(", re.I),
    re.compile(r"\bclick_sign_button\b", re.I),
    re.compile(r"\bperform_payment\s*\(", re.I),
)

# Lines matching these are allow-listed (disclaimers / bans / tests of bans).
_ALLOW_LINE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bnot\b.{0,40}\bpatentab", re.I),
    re.compile(r"\bnever\b.{0,40}\bpatentab", re.I),
    re.compile(r"\bforbid", re.I),
    re.compile(r"\bnon-?goal", re.I),
    re.compile(r"\bdisclaimer\b", re.I),
    re.compile(r"\bauto_file_blocked\b", re.I),
    re.compile(r"\breview-?only\b", re.I),
    re.compile(r"\bnot legal advice\b", re.I),
    re.compile(r"\bFORBIDDEN\b"),
    re.compile(r"_FORBIDDEN"),
    re.compile(r"assert .* not in", re.I),
    re.compile(r"assert .*forbidden", re.I),
    re.compile(r"#.*(ban|forbid|never|not a)", re.I),
    re.compile(r'""".*(not a novelty|not legal advice|never asserts)', re.I | re.S),
    re.compile(r"patentability_conclusions", re.I),  # config key listing non-goal
    re.compile(r"no.patentability", re.I),
    re.compile(r"without claiming", re.I),
    re.compile(r"not a.{0,20}§112", re.I),
)


def _repo_root() -> Path:
    start = Path(__file__).resolve()
    for parent in start.parents:
        if (parent / "docs/operations/PAAR_NON_GOALS.md").is_file():
            return parent
        if (parent / "pyproject.toml").is_file() and (
            parent / "ipfs_datasets_py/processors/domains/uspto"
        ).is_dir():
            return parent
    return start.parents[3]


def _paar_scan_paths(root: Path) -> list[Path]:
    """Collect PAAR-related source modules and docs to scan."""
    paths: list[Path] = []
    candidates = [
        root / "ipfs_datasets_py/processors/domains/uspto/claim_limitation_model.py",
        root
        / "ipfs_datasets_py/processors/domains/uspto/analysis/obligation_catalog.py",
        root
        / "ipfs_datasets_py/processors/domains/uspto/analysis/obligation_catalog_seed.json",
        root / "docs/operations/PAAR_NON_GOALS.md",
        root / "docs/architecture/paar_report_schemas.md",
        root / "docs/architecture/PATENT_AUTOMATED_APPLICATION_REVIEW_PLAN.md",
        # Future PAAR modules (scan if present)
        root / "ipfs_datasets_py/processors/domains/patent/conflict_risk_engine.py",
        root / "ipfs_datasets_py/processors/domains/uspto/conflict_review_report.py",
        root / "ipfs_datasets_py/processors/domains/uspto/package_conformance_engine.py",
        root / "ipfs_datasets_py/processors/domains/uspto/review_search_orchestrator.py",
        root / "ipfs_datasets_py/processors/domains/uspto/review_orchestrator.py",
        root / "ipfs_datasets_py/processors/domains/uspto/review_scheduler.py",
    ]
    for p in candidates:
        if p.is_file():
            paths.append(p)
    # Also scan any *paar* modules under uspto/patent
    for base in (
        root / "ipfs_datasets_py/processors/domains/uspto",
        root / "ipfs_datasets_py/processors/domains/patent",
    ):
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            name = p.name.lower()
            if "paar" in name or "conflict_risk" in name or "conformance" in name:
                if p not in paths:
                    paths.append(p)
    return paths


def _line_allowed(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if any(r.search(line) for r in _ALLOW_LINE_RES):
        return True
    lower = line.lower()
    # Markdown / doc enumeration of forbidden examples (bullets, backticks, tables).
    if stripped.startswith(("*", "-", "|", "`")) and any(
        p in lower for p in _FORBIDDEN_PHRASES
    ):
        return True
    if "forbidden" in lower or "do **not**" in lower or "do not emit" in lower:
        return True
    # Negative framing near forbidden phrase
    if any(
        neg in lower
        for neg in (
            "never ",
            "not ",
            "forbid",
            "must not",
            "do not",
            "don't",
            "without ",
            "no ",
            "blocked",
            "ban",
            "not a ",
            "not an ",
        )
    ) and any(p in lower for p in _FORBIDDEN_PHRASES):
        return True
    return False


def _scan_file(path: Path) -> list[str]:
    """Return violation descriptions for a file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    violations: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if _line_allowed(line):
            continue
        lower = line.lower()
        for phrase in _FORBIDDEN_PHRASES:
            if phrase in lower:
                violations.append(f"{path}:{lineno}: forbidden phrase {phrase!r}: {line.strip()[:160]}")
        for cre in _FORBIDDEN_AUTOMATION_RES:
            if cre.search(line):
                violations.append(
                    f"{path}:{lineno}: forbidden automation pattern {cre.pattern!r}: {line.strip()[:160]}"
                )
    return violations


def test_paar_modules_have_no_patentability_conclusions() -> None:
    root = _repo_root()
    paths = _paar_scan_paths(root)
    assert paths, "expected at least one PAAR module/doc to scan"
    # Ensure core Wave 1 modules are present
    names = {p.name for p in paths}
    assert "claim_limitation_model.py" in names or any(
        "claim_limitation" in p.name for p in paths
    )
    all_violations: list[str] = []
    for path in paths:
        all_violations.extend(_scan_file(path))
    assert not all_violations, "PAAR non-goal violations:\n" + "\n".join(all_violations)


def test_paar_non_goals_doc_lists_forbiddens() -> None:
    root = _repo_root()
    doc = root / "docs/operations/PAAR_NON_GOALS.md"
    assert doc.is_file()
    text = doc.read_text(encoding="utf-8").lower()
    assert "patentability conclusions are forbidden" in text
    assert "auto sign" in text and "pay" in text and "submit" in text
    assert "auto ids file is forbidden" in text


def test_claim_model_disclaimer_blocks_patentability_language() -> None:
    from ipfs_datasets_py.processors.domains.uspto.claim_limitation_model import (
        REVIEW_ONLY_CLAIM_MODEL_DISCLAIMER,
        parse_claims_to_graph,
    )

    lower = REVIEW_ONLY_CLAIM_MODEL_DISCLAIMER.lower()
    assert "not" in lower and "patentability" in lower
    graph = parse_claims_to_graph(
        "1. A method comprising detecting a signal and emitting an alert."
    )
    payload = json_dumps_lower(graph.to_dict(include_text=False))
    for phrase in ("is patentable", "is novel", "is obvious", "no prior art exists"):
        assert phrase not in payload


def json_dumps_lower(obj: object) -> str:
    import json

    return json.dumps(obj, default=str).lower()


def test_obligation_catalog_auto_file_blocked_framing() -> None:
    from ipfs_datasets_py.processors.domains.uspto.analysis.obligation_catalog import (
        load_seed_catalog,
    )

    catalog = load_seed_catalog()
    blob = json_dumps_lower(catalog.to_dict())
    assert "auto_file_blocked" in blob or "human_process" in blob
    for phrase in ("is patentable", "file_ids_automatically", "click_sign_button"):
        assert phrase not in blob
    # Fees / IDS obligations must not enable payment automation
    assert "automate payment" not in blob
    assert "perform_payment(" not in blob
