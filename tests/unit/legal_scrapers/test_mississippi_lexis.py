from __future__ import annotations

from dataclasses import replace

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    mississippi_lexis,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi import (
    MississippiScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.mississippi_lexis import (
    EXPECTED_ROOT_NODE_IDS,
    EXPECTED_TITLE_NUMBERS,
    PUBLIC_CONTAINER_CONFIG,
    MississippiLexisNode,
    _bind_live_nodes,
    canonical_node_digest,
    container_url_matches,
    document_disposition,
    document_page_url,
    grouped_body_acquisition_contract,
    node_from_mapping,
    parse_root_dom_rows,
    parse_title_subtree_payload,
    root_membership_error,
    toc_open_to_request,
)


def _root_rows() -> list[dict[str, str]]:
    labels = [
        mississippi_lexis.RECENT_LEGISLATION_ROOT_LABEL,
        *(f"TITLE {number} Test title" for number in EXPECTED_TITLE_NUMBERS),
    ]
    return [
        {
            "nodeid": node_id,
            "title": label,
            "level": "1",
            "nodepath": f"/ROOT/{node_id}",
            "canexpand": "true",
            "canopen": "false",
            "haschildren": "true",
        }
        for node_id, label in zip(EXPECTED_ROOT_NODE_IDS, labels, strict=True)
    ]


def _mapping(
    *,
    node_id: str,
    title: str,
    level: int,
    node_path: str,
    link_href: str = "",
    expandable: bool = False,
) -> dict[str, object]:
    return {
        "id": node_id,
        "props": {
            "nodeid": node_id,
            "linktemplatetitle": title,
            "level": level,
            "nodepath": node_path,
            "canexpand": expandable,
            "canopen": bool(link_href),
            "haschildren": expandable,
            "linkhref": link_href,
            "subscribed": True,
            "tocpricing": {
                "purchaserequired": False,
                "listprice": 0,
                "netprice": 0,
                "currencycode": "USD",
                "usagetypecode": "subscription",
                "documentstatus": "available",
            },
        },
    }


def _node(
    *,
    node_id: str,
    title: str,
    node_path: str,
    link_href: str,
) -> MississippiLexisNode:
    node = node_from_mapping(
        _mapping(
            node_id=node_id,
            title=title,
            level=2,
            node_path=node_path,
            link_href=link_href,
        )
    )
    assert node is not None
    bound = _bind_live_nodes(
        [node],
        source_url=(
            "https://advance.lexis.com/container?config="
            f"{PUBLIC_CONTAINER_CONFIG}&crid=request_1&prid=proof_1"
        ),
        observed_at="2026-08-26T12:00:00+00:00",
        receipt_sha256="a" * 64,
    )
    assert len(bound) == 1
    return bound[0]


def test_exact_root_membership_is_recent_branch_plus_50_odd_titles() -> None:
    nodes = parse_root_dom_rows(_root_rows())

    assert len(nodes) == 51
    assert root_membership_error(nodes) == ""
    assert nodes[0].is_recent_legislation_root is True
    assert tuple(node.title_number for node in nodes[1:]) == EXPECTED_TITLE_NUMBERS

    broken = list(nodes)
    broken[-1] = replace(broken[-1], title="TITLE 98 Wrong title")
    assert "ordered odd-numbered" in root_membership_error(broken)


def test_container_and_open_to_request_are_exact() -> None:
    assert container_url_matches(
        "https://advance.lexis.com/container?config="
        f"{PUBLIC_CONTAINER_CONFIG}&crid=abc_1&prid=def-2"
    )
    assert not container_url_matches(
        "https://advance.lexis.com/container?config="
        f"{PUBLIC_CONTAINER_CONFIG}&extra=1"
    )

    endpoint, body = toc_open_to_request("AAB", target_level=4)
    assert endpoint.endswith("/r/tocprovider/6gf5kkk/toc/6gf5kkk")
    assert body["props"]["action"] == "open-to"
    assert body["props"]["items"] == [
        {"fieldName": "nodeId", "value": "AAB"},
        {"fieldName": "targetLevel", "value": 4},
    ]
    with pytest.raises(ValueError, match="root node"):
        toc_open_to_request("UNKNOWN", target_level=4)


def test_subtree_parser_closes_hierarchy_and_rejects_cross_title_citation() -> None:
    parent = parse_root_dom_rows(_root_rows())[1]
    chapter = _mapping(
        node_id="CHAPTER1",
        title="Chapter 1 Test",
        level=2,
        node_path="/ROOT/AAC/CHAPTER1",
        expandable=True,
    )
    section = _mapping(
        node_id="SECTION1",
        title="§ 1-1-1. Test section.",
        level=3,
        node_path="/ROOT/AAC/CHAPTER1/SECTION1",
        link_href=(
            "/shared/document/statutes-legislation/"
            "urn:contentItem:6J6W-9RN3-RS74-T55S-00008-00"
        ),
    )

    nodes, closed, error = parse_title_subtree_payload(
        {"collections": {"nodes": [chapter, section]}},
        parent=parent,
        target_level=3,
    )

    assert error == ""
    assert len(nodes) == 2
    assert closed == (parent.node_id, "CHAPTER1")
    assert nodes[-1].section_number == "1-1-1"

    repeated_nodes, _closed, repeated_error = parse_title_subtree_payload(
        {"collections": {"nodes": [chapter, section, section]}},
        parent=parent,
        target_level=3,
    )
    assert repeated_error == ""
    assert len(repeated_nodes) == 2

    section["props"]["linktemplatetitle"] = "§ 3-1-1. Cross-title section."
    _nodes, _closed, error = parse_title_subtree_payload(
        {"collections": {"nodes": [chapter, section]}},
        parent=parent,
        target_level=3,
    )
    assert error == "statute citation crossed the requested title boundary"


def test_document_classification_handles_alphanumeric_and_future_paths() -> None:
    current = _node(
        node_id="CURRENT1",
        title="§ 75-2A-101. Short title.",
        node_path="/ROOT/ABM/CURRENT1",
        link_href=(
            "/shared/document/statutes-legislation/"
            "urn:contentItem:6J6W-9RN3-RS74-T55S-00008-00"
        ),
    )
    future = _node(
        node_id="FUTURE1",
        title="§ 75-2A-101. Short title [Effective January 1, 2027].",
        node_path="/ROOT/ABM/FUTURE1",
        link_href=(
            "/shared/document/fe/"
            "urn:contentItem:6J6W-9RM3-RS74-S1JJ-00008-00"
        ),
    )

    assert current.section_number == future.section_number == "75-2A-101"
    assert document_disposition(current) == "current_section_candidate"
    assert document_disposition(future) == "future_effectiveness_excluded"
    assert "pddocfullpath=%2Fshared%2Fdocument%2Fstatutes-legislation%2F" in (
        document_page_url(current)
    )

    unlabeled = _node(
        node_id="UNLABELED1",
        title="",
        node_path="/ROOT/ABY/UNLABELED1",
        link_href=(
            "/shared/document/statutes-legislation/"
            "urn:contentItem:65NS-RSK3-GXF6-81PF-00008-00"
        ),
    )
    assert document_disposition(unlabeled) == "untyped_current_document_residual"


def test_grouped_body_contract_keeps_residuals_and_forbids_archive_page_loops() -> None:
    unique = _node(
        node_id="UNIQUE1",
        title="§ 1-1-1. Unique.",
        node_path="/ROOT/AAC/UNIQUE1",
        link_href=(
            "/shared/document/statutes-legislation/"
            "urn:contentItem:6J6W-9RN3-RS74-T55S-00008-00"
        ),
    )
    duplicate_a = _node(
        node_id="DUPA1",
        title="§ 1-1-3. Effective until July 1, 2026.",
        node_path="/ROOT/AAC/DUPA1",
        link_href=(
            "/shared/document/statutes-legislation/"
            "urn:contentItem:6J6W-9RM3-RS74-S1JJ-00008-00"
        ),
    )
    duplicate_b = _node(
        node_id="DUPB1",
        title="§ 1-1-3. Effective July 1, 2026.",
        node_path="/ROOT/AAC/DUPB1",
        link_href=(
            "/shared/document/statutes-legislation/"
            "urn:contentItem:6J6W-9RK3-RS74-T55N-00008-00"
        ),
    )
    future = _node(
        node_id="FUTURE2",
        title="§ 1-1-5. Effective January 1, 2027.",
        node_path="/ROOT/AAC/FUTURE2",
        link_href=(
            "/shared/document/fe/"
            "urn:contentItem:6J6W-JC73-RTBG-Y02T-00008-00"
        ),
    )
    recent = _node(
        node_id="RECENT1",
        title="§ 1. Needs catchline [Effective July 1, 2026].",
        node_path="/ROOT/AAB/RECENT1",
        link_href=(
            "/shared/document/statutes-legislation/"
            "urn:contentItem:6J7Y-FXG3-RSW9-W3C1-00008-00"
        ),
    )

    contract = grouped_body_acquisition_contract(
        [unique, duplicate_a, duplicate_b, future, recent]
    )

    assert contract["source_domain"] == "advance.lexis.com"
    assert contract["request_url_count"] == 1
    assert contract["common_crawl_inventory_query_upper_bound"] == 1
    assert contract["group_warc_ranges_by_warc_filename"] is True
    assert contract["per_page_archive_inventory_loop"] is False
    assert contract["retry_residual_urls_only"] is True
    assert contract["residual_count"] == 3
    assert contract["exclusion_count"] == 1
    assert contract["full_corpus_admissible"] is False


def test_semantic_digest_ignores_live_receipt_fields() -> None:
    node = _node(
        node_id="DIGEST1",
        title="§ 1-1-1. Digest.",
        node_path="/ROOT/AAC/DIGEST1",
        link_href=(
            "/shared/document/statutes-legislation/"
            "urn:contentItem:6J6W-9RN3-RS74-T55S-00008-00"
        ),
    )
    changed_receipt = replace(node, evidence_sha256="b" * 64)

    assert canonical_node_digest([node]) == canonical_node_digest([changed_receipt])


def test_scraper_source_bundle_binds_mississippi_lexis() -> None:
    scraper = MississippiScraper("MS", "Mississippi")
    dependencies = scraper.state_law_frontier_source_dependencies()

    assert mississippi_lexis in dependencies
    with pytest.raises(RuntimeError, match="async delegated Lexis 51-root"):
        scraper.fetch_official("MS")
