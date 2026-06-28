from __future__ import annotations

from pathlib import Path


def test_netherlands_jurisdiction_is_registered_and_keeps_cli_commands():
    from ipfs_datasets_py.processors.legal_scrapers.legal_corpus import get_jurisdiction
    from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws import get_jurisdiction as get_nl

    jurisdiction = get_jurisdiction("netherlands")

    assert jurisdiction is get_jurisdiction("NL")
    assert jurisdiction is get_nl()
    assert jurisdiction.spec.slug == "netherlands"
    assert jurisdiction.spec.jurisdiction_id == "NL"
    assert "wetten.overheid.nl law document pages" in jurisdiction.spec.official_sources
    assert jurisdiction.spec.hf_repo_ids["base"] == "justicedao/ipfs_netherlands_laws"

    commands = set(jurisdiction.command_groups()["commands"])
    assert {
        "discover",
        "queue",
        "scrape",
        "resume",
        "rebuild-huggingface",
        "build-unified",
        "validate-unified",
        "verify",
        "coverage-report",
    } <= commands


def test_netherlands_components_satisfy_shared_interfaces():
    from ipfs_datasets_py.processors.legal_scrapers.legal_corpus import (
        BM25IndexBuilder,
        CIDGenerator,
        DiscoveryProvider,
        FetchProvider,
        HierarchyExtractor,
        HuggingFacePublisher,
        IntegrityValidator,
        JsonLdGraphBuilder,
        PackageBuilder,
        Parser,
        StatusClassifier,
        VectorIndexBuilder,
        get_jurisdiction,
    )

    jurisdiction = get_jurisdiction("netherlands")

    assert isinstance(jurisdiction.discovery, DiscoveryProvider)
    assert isinstance(jurisdiction.fetcher, FetchProvider)
    assert isinstance(jurisdiction.parser, Parser)
    assert isinstance(jurisdiction.hierarchy, HierarchyExtractor)
    assert isinstance(jurisdiction.status, StatusClassifier)
    assert isinstance(jurisdiction.cid, CIDGenerator)
    assert isinstance(jurisdiction.packaging, PackageBuilder)
    assert isinstance(jurisdiction.vector, VectorIndexBuilder)
    assert isinstance(jurisdiction.bm25, BM25IndexBuilder)
    assert isinstance(jurisdiction.jsonld, JsonLdGraphBuilder)
    assert isinstance(jurisdiction.publisher, HuggingFacePublisher)
    assert isinstance(jurisdiction.integrity, IntegrityValidator)


def test_status_classifier_inherits_parent_law_fields():
    from ipfs_datasets_py.processors.legal_scrapers.legal_corpus import get_jurisdiction

    jurisdiction = get_jurisdiction("netherlands")
    law = {
        "law_status": "current",
        "is_current": True,
        "valid_from": "2024-01-01",
        "valid_to": "",
        "effective_date": "2024-01-01",
        "retrieved_at": "2026-06-27T00:00:00+00:00",
        "status_source": "wetten.overheid.nl/informatie",
        "status_confidence": "high",
        "status_note": "Official status text indicates the law is current",
        "version_start_date": "2024-01-01",
        "version_end_date": "",
    }
    article = {"article_identifier": "BWBRTEST:artikel:1", "law_status": "unknown"}

    status = jurisdiction.status.classify_law(law)
    inherited = jurisdiction.status.inherit_article_status(law, article)

    assert status.law_status == "current"
    assert status.is_current is True
    assert inherited["law_status"] == "current"
    assert inherited["status_confidence"] == "high"
    assert inherited["version_start_date"] == "2024-01-01"


def test_cid_generator_adds_content_addresses_without_mutating_input():
    from ipfs_datasets_py.processors.legal_scrapers.legal_corpus import get_jurisdiction

    jurisdiction = get_jurisdiction("netherlands")
    row = {"record_type": "law", "law_identifier": "BWBRTEST", "text": "Test law text"}

    generated = list(jurisdiction.cid.assign_record_cids([row]))

    assert "cid" not in row
    assert generated[0]["cid"].startswith("b")
    assert generated[0]["content_address"] == f"ipfs://{generated[0]['cid']}"


def test_future_jurisdiction_contract_is_documented():
    doc = Path(
        "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/docs/JURISDICTION_IMPLEMENTATION.md"
    ).read_text(encoding="utf-8")

    for required in [
        "DiscoveryProvider",
        "FetchProvider",
        "Parser",
        "HierarchyExtractor",
        "StatusClassifier",
        "CIDGenerator",
        "PackageBuilder",
        "VectorIndexBuilder",
        "BM25IndexBuilder",
        "JsonLdGraphBuilder",
        "HuggingFacePublisher",
        "IntegrityValidator",
        "not legal advice",
    ]:
        assert required in doc
