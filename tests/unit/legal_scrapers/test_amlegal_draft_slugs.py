"""Slug handling in the AmLegal Hub scraper (case-sensitive client slugs)."""

from ipfs_datasets_py.processors.legal_scrapers.municipal_law_database_scrapers.hub import amlegal_draft as A


def test_parse_amlegal_url_preserves_case_by_default():
    url = "https://codelibrary.amlegal.com/codes/HudsonNC/latest/overview"
    assert A.parse_amlegal_url(url) == "HudsonNC"
    assert A.parse_amlegal_url(url, preserve_case=False) == "hudsonnc"
    assert A.parse_amlegal_url("https://example.com/") is None


def test_slug_candidates_are_ordered_and_unique():
    cands = A._slug_candidates("Man_WV")
    assert cands[0] == "Man_WV"
    assert "manwv" in cands
    assert len(cands) == len(set(cands))


def test_resolve_amlegal_client_tries_underscore_free_slug(monkeypatch):
    seen = []

    def fake_get(url, sleep=0.0, **_kw):
        seen.append(url)
        return {"id": 1, "slug": "manwv"} if "/clients/manwv/" in url else {}

    monkeypatch.setattr(A, "polite_get_json", fake_get)
    slug, client = A.resolve_amlegal_client("https://codelibrary.amlegal.com/codes/man_wv/latest/x", sleep=0)
    assert slug == "manwv" and client["id"] == 1
    assert A.resolve_amlegal_client("not a url!", sleep=0) == (None, {})
