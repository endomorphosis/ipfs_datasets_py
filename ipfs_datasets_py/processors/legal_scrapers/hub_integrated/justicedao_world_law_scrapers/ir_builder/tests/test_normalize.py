"""Normalizer + CID tests. Never invents legal text."""

from __future__ import annotations

import pandas as pd
import pytest

from country_laws_ir.cidutil import cid_of_json, cid_v1_raw_sha256
from country_laws_ir.graph import _facet_cid, build_graph
from country_laws_ir.normalize import build_corpus, normalize_text
from country_laws_ir.tokenize import tokenize


def _laws(*rows):
    return pd.DataFrame(list(rows))


def _articles(*rows):
    if not rows:
        return pd.DataFrame(
            columns=["law_id", "id", "title", "text", "source_url", "document_number", "article_number", "record_type", "metadata_json"]
        )
    return pd.DataFrame(list(rows))


def _meta(n_laws=1, n_articles=0):
    return {
        "source_dataset": "endomorphosis/ipfs_test_laws",
        "source_revision": "abc123",
        "laws_sha256": "00",
        "articles_sha256": "11",
        "n_laws_source": n_laws,
        "n_articles_source": n_articles,
        "schema_surprises": [],
    }


def test_normalize_text_nfkc_and_whitespace():
    assert normalize_text("A \r\n\r\n  B") == "A B"
    # combining acute on e composes under NFKC
    assert normalize_text("Cafe\u0301") == "Café"


def test_drop_empty_body_and_count():
    laws = _laws(
        {"id": "x-1", "title": "Act One", "text": "Body of the act.", "jurisdiction": "MT", "language": "en"},
        {"id": "x-2", "title": "Empty", "text": "   ", "jurisdiction": "MT", "language": "en"},
    )
    df, report = build_corpus(laws, _articles(), _meta(n_laws=2))
    assert report["drops"]["empty_body"] == 1
    assert report["n_out"] == 1
    assert report["n_dropped_total"] == 1
    assert df.iloc[0]["instrument_id"] == "x-1"
    assert df.iloc[0]["record_type"] == "law"
    assert "body" in df.columns and df.iloc[0]["body"] == "Body of the act."


def test_prefer_articles_when_present():
    laws = _laws(
        {"id": "x-1", "title": "Parent Act", "text": "Whole statute text", "jurisdiction": "MT", "language": "en", "eli": "https://example.test/eli/1"},
    )
    articles = _articles(
        {"id": "x-1-art-1", "law_id": "x-1", "title": "Article 1", "text": "Citable article body.", "article_number": "1", "source_url": "", "metadata_json": ""},
        {"id": "x-1-art-empty", "law_id": "x-1", "title": "Article 2", "text": "", "article_number": "2", "source_url": "", "metadata_json": ""},
    )
    df, report = build_corpus(laws, articles, _meta(n_laws=1, n_articles=2))
    assert report["unit"] == "article"
    assert report["drops"]["empty_body"] == 1
    assert report["n_out"] == 1
    assert df.iloc[0]["record_type"] == "article"
    assert df.iloc[0]["article_number"] == "1"
    assert report["language_breakdown"] == {"en": 1}


def test_cid_deterministic_and_bafk_prefix():
    a = cid_of_json({"schema": "country-laws-entry/v1", "k": "v"})
    b = cid_of_json({"k": "v", "schema": "country-laws-entry/v1"})
    assert a == b
    assert a.startswith("bafk")
    raw = cid_v1_raw_sha256(b"hello")
    assert raw.startswith("bafk")
    assert cid_v1_raw_sha256(b"hello") == raw


def test_facet_cid_stable():
    assert _facet_cid("jurisdiction", "MT") == _facet_cid("jurisdiction", "MT")
    assert _facet_cid("jurisdiction", "MT") != _facet_cid("language", "en")
    assert _facet_cid("jurisdiction", "MT").startswith("bafk")


def test_article_of_edge():
    laws = _laws(
        {"id": "x-1", "title": "Parent Act", "text": "Whole", "jurisdiction": "MT", "language": "en", "source_type": "legislation_mt", "law_status": "current"},
    )
    articles = _articles(
        {"id": "a1", "law_id": "x-1", "title": "Art 1", "text": "Hello statute.", "article_number": "1", "source_url": "", "metadata_json": ""},
    )
    df, _ = build_corpus(laws, articles, _meta(n_laws=1, n_articles=1))
    graph = build_graph(df, neighbors=[[] for _ in range(len(df))])
    types = set(graph["edges"]["edge_type"].tolist())
    assert "ARTICLE_OF" in types
    assert "HAS_JURISDICTION" in types
    assert "HAS_LANGUAGE" in types
    art_cid = df.iloc[0]["entry_cid"]
    art_edges = graph["edges"][(graph["edges"]["edge_type"] == "ARTICLE_OF") & (graph["edges"]["source_cid"] == art_cid)]
    assert len(art_edges) == 1


def test_tokenizer_fts5_style():
    assert tokenize("Constitution — Malta") == ["constitution", "malta"]


def test_sparse_articles_fall_back_to_laws():
    """Estonia-style: 2 articles vs many laws must index law-level units."""
    laws = _laws(
        *[
            {
                "id": f"x-{i}",
                "title": f"Act {i}",
                "text": f"Body of act {i}.",
                "jurisdiction": "EE",
                "language": "et",
            }
            for i in range(20)
        ]
    )
    articles = _articles(
        {"id": "x-0-art-1", "law_id": "x-0", "title": "Art 1", "text": "Tiny article.", "article_number": "1", "source_url": "", "metadata_json": ""},
    )
    df, report = build_corpus(laws, articles, _meta(n_laws=20, n_articles=1))
    assert report["unit"] == "law"
    assert report["sparse_article_fallback"] is True
    assert report["n_out"] == 20
    assert (df["record_type"] == "law").all()
    assert report["quality_flags"]["sparse_article_fallback"] is True
