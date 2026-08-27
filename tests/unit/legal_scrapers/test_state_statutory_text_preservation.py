"""Regression coverage for complete state statutory-body preservation."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alabama_section import (
    parse_alabama_section_payload,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.indiana import (
    IndianaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_york_openleg import (
    parse_new_york_law_tree,
)

SCRAPER_ROOT = (
    Path(__file__).resolve().parents[3]
    / "ipfs_datasets_py"
    / "processors"
    / "legal_scrapers"
    / "state_scrapers"
)
_BOUND_ARGUMENT_NAMES = {"char_limit", "max_chars", "max_length", "text_limit"}


def _is_full_text_target(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "full_text"
    if isinstance(node, ast.Attribute):
        return node.attr == "full_text"
    if isinstance(node, ast.Subscript):
        key = node.slice
        return isinstance(key, ast.Constant) and key.value == "full_text"
    return False


def _numeric_slice(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Slice)
        and isinstance(node.slice.upper, ast.Constant)
        and isinstance(node.slice.upper.value, int)
    )


def _bounded_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    return any(
        keyword.arg in _BOUND_ARGUMENT_NAMES
        and isinstance(keyword.value, ast.Constant)
        and isinstance(keyword.value.value, int)
        for keyword in node.keywords
    )


def _full_text_values(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "full_text":
                    yield node.lineno, keyword.value
        elif isinstance(node, ast.Assign):
            if any(_is_full_text_target(target) for target in node.targets):
                yield node.lineno, node.value
        elif isinstance(node, ast.AnnAssign) and _is_full_text_target(node.target):
            yield node.lineno, node.value
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "full_text":
                    yield node.lineno, value


def _truncated_full_text_findings(source: str) -> list[int]:
    tree = ast.parse(source)
    findings: list[int] = []
    for line_number, value in _full_text_values(tree):
        if any(
            _numeric_slice(child) or _bounded_call(child) for child in ast.walk(value)
        ):
            findings.append(line_number)
    return sorted(findings)


def test_all_state_scrapers_forbid_numeric_full_text_truncation() -> None:
    findings: list[str] = []
    for path in sorted(SCRAPER_ROOT.glob("*.py")):
        for line_number in _truncated_full_text_findings(
            path.read_text(encoding="utf-8")
        ):
            findings.append(f"{path.name}:{line_number}")

    assert findings == []


def test_static_guard_detects_direct_and_helper_based_truncation() -> None:
    source = """
def unsafe(body, extractor):
    first = NormalizedStatute(full_text=body[:14000])
    full_text = extractor(body, max_chars=24000)
    record = {"full_text": normalize(body[:16000])}
    return first, full_text, record
"""

    assert _truncated_full_text_findings(source) == [3, 4, 5]


@pytest.mark.parametrize("parser_kind", ["alabama", "new_york"])
def test_normalized_statute_preserves_body_beyond_24k(parser_kind: str) -> None:
    body = "A complete statutory command remains part of the enacted law. " * 700
    assert len(body) > 24_000

    if parser_kind == "alabama":
        statute = parse_alabama_section_payload(
            {
                "displayId": "1-1-1",
                "title": "Complete statutory text",
                "content": f"<p>{body}</p>",
            }
        )
        assert statute is not None
    else:
        statutes = parse_new_york_law_tree(
            {
                "info": {"lawId": "TST", "name": "Test Law"},
                "documents": {
                    "docType": "SECTION",
                    "docLevelId": "1",
                    "locationId": "1",
                    "title": "Complete statutory text",
                    "text": body,
                },
            }
        )
        assert len(statutes) == 1
        statute = statutes[0]

    assert statute.full_text is not None
    assert len(statute.full_text) > 24_000
    assert statute.full_text.endswith("enacted law. ".strip())


def test_pdf_body_extractor_is_uncapped_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import indiana

    body = "BEGIN " + ("statutory-body " * 2_500) + "END"
    monkeypatch.setattr(
        indiana.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=body.encode()),
    )

    extracted = IndianaScraper("IN", "Indiana")._extract_pdf_text(b"%PDF-test")

    assert len(extracted) > 24_000
    assert extracted.endswith("END")
