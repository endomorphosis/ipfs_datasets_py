"""The finished crosswalk matches the reviewed 219 national slugs."""

from __future__ import annotations

from pathlib import Path

from ipfs_datasets_py.processors.legal_data.iso_slug_crosswalk import (
    codes_in_crosswalk,
    national_slug,
    resolve_jurisdiction,
)
from ipfs_datasets_py.processors.legal_data.query_legal_records import (
    query_legal_records,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.coverage import (
    ALIAS_TO_CANONICAL,
)

_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "legal_data"
    / "national_ipfs_laws_slugs.txt"
)


def _published_slugs() -> set[str]:
    return {line.strip() for line in _FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()}


def test_crosswalk_matches_the_reviewed_national_slugs() -> None:
    published = _published_slugs()
    assert len(published) == 219
    mapped = {national_slug(code) for code in codes_in_crosswalk()}
    mapped.discard(None)
    assert mapped | set(ALIAS_TO_CANONICAL) == published
    assert "AQ" not in codes_in_crosswalk()
    assert "ZZ" not in codes_in_crosswalk()
    assert national_slug("AQ") is None
    assert national_slug("ZZ") is None
    assert "curaçao" not in mapped
    assert "curacao" in mapped


def test_named_codes_keep_the_override_table(monkeypatch) -> None:
    expected = {
        "FR": "france",
        "GB": "uk",
        "ES": "spain",
        "AE": "uae",
        "CZ": "czechia",
        "KR": "korea",
        "NZ": "newzealand",
        "CW": "curacao",
        "XK": "kosovo",
        "EU": "eu",
    }
    for code, slug in expected.items():
        assert national_slug(code) == slug
    uk = resolve_jurisdiction("uk")
    gb = resolve_jurisdiction("GB")
    assert uk is not None and gb is not None
    assert uk.echo == gb.echo == "GB"
    assert uk.slug == gb.slug == "uk"
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    by_slug = query_legal_records(jurisdiction="uk", text_query="theft")
    by_code = query_legal_records(jurisdiction="GB", text_query="theft")
    assert by_slug.jurisdiction == by_code.jurisdiction == "GB"
    assert by_slug.source_repo == by_code.source_repo == "justicedao/ipfs_uk_laws_ir"
