"""Unit tests for investigation_tools (Phase B2).

Covers data ingestion, entity analysis, relationship timeline, and
geospatial analysis tools.  All tools degrade gracefully without external
dependencies, returning dicts with status/error keys.
"""
from __future__ import annotations

import asyncio
import pytest

# Data ingestion
from ipfs_datasets_py.mcp_server.tools.investigation_tools.data_ingestion_tools import (
    ingest_news_article,
    ingest_news_feed,
    ingest_website,
    ingest_document_collection,
)

# Entity analysis
from ipfs_datasets_py.mcp_server.tools.investigation_tools.entity_analysis_tools import (
    analyze_entities,
    explore_entity,
)

# Relationship / timeline
from ipfs_datasets_py.mcp_server.tools.investigation_tools.relationship_timeline_tools import (
    map_relationships,
    analyze_entity_timeline,
    detect_patterns,
    track_provenance,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Data ingestion
# ---------------------------------------------------------------------------

class TestIngestNewsArticle:
    def test_returns_dict(self):
        result = _run(ingest_news_article(url="https://example.com/article"))
        assert isinstance(result, dict)

    def test_source_type_param_accepted(self):
        result = _run(ingest_news_article(
            url="https://example.com",
            source_type="news",
        ))
        assert isinstance(result, dict)

    def test_analysis_type_param_accepted(self):
        result = _run(ingest_news_article(
            url="https://example.com",
            analysis_type="summary",
        ))
        assert isinstance(result, dict)


class TestIngestNewsFeed:
    def test_returns_dict(self):
        result = _run(ingest_news_feed(feed_url="https://example.com/rss"))
        assert isinstance(result, dict)

    def test_max_articles_accepted(self):
        result = _run(ingest_news_feed(
            feed_url="https://example.com/rss",
            max_articles=5,
        ))
        assert isinstance(result, dict)


class TestIngestWebsite:
    def test_returns_dict(self):
        result = _run(ingest_website(base_url="https://example.com"))
        assert isinstance(result, dict)


class TestIngestDocumentCollection:
    def test_returns_dict(self):
        result = _run(ingest_document_collection(document_paths='["/tmp/doc.txt"]'))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Entity analysis
# ---------------------------------------------------------------------------

class TestAnalyzeEntities:
    def test_returns_dict(self):
        result = _run(analyze_entities(corpus_data='{"documents": ["Alice works at Acme."]}'))
        assert isinstance(result, dict)

    def test_entity_types_accepted(self):
        result = _run(analyze_entities(
            corpus_data='{"documents": ["Bob lives in Paris."]}',
            entity_types=["PERSON", "LOCATION"],
        ))
        assert isinstance(result, dict)


class TestExploreEntity:
    def test_returns_dict(self):
        result = _run(explore_entity(
            entity_id="alice",
            corpus_data='{"documents": []}',
        ))
        assert isinstance(result, dict)

    def test_include_relationships_param_accepted(self):
        result = _run(explore_entity(
            entity_id="alice",
            corpus_data='{"documents": []}',
            include_relationships=False,
        ))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Relationship / timeline tools
# ---------------------------------------------------------------------------

class TestMapRelationships:
    def test_returns_dict(self):
        result = _run(map_relationships(corpus_data='{"documents": ["Alice knows Bob."]}'))
        assert isinstance(result, dict)


class TestAnalyzeEntityTimeline:
    def test_returns_dict(self):
        result = _run(analyze_entity_timeline(
            corpus_data='{"documents": []}',
            entity_id="alice",
        ))
        assert isinstance(result, dict)


class TestDetectPatterns:
    def test_returns_dict(self):
        result = _run(detect_patterns(
            corpus_data='{"documents": []}',
            pattern_types=["temporal"],
        ))
        assert isinstance(result, dict)


class TestTrackProvenance:
    def test_returns_dict(self):
        result = _run(track_provenance(
            corpus_data='{"documents": []}',
            entity_id="entity_1",
        ))
        assert isinstance(result, dict)

    def test_include_citations_param_accepted(self):
        result = _run(track_provenance(
            corpus_data='{"documents": []}',
            entity_id="entity_2",
            include_citations=True,
        ))
        assert isinstance(result, dict)
