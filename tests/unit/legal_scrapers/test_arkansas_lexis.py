"""Arkansas's state-designated, inventory-only Lexis TOC adapter."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from urllib.parse import urlparse

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (
    AdmissionRequest,
    CatalogSchemaError,
    DomainConstraintError,
    evaluate_admission,
    get_official_source_catalog,
    load_official_source_catalog,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas import (
    ArkansasDelegatedCorpusBlockedError,
    ArkansasScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.arkansas_lexis import (
    ADVANCE_ORIGIN,
    ENABLE_ENV,
    EXPECTED_TITLE_NUMBERS,
    OFFICIAL_REFERRER,
    PUBLIC_CONTAINER_URL,
    PUBLIC_ENTRY_URL,
    TOC_ENDPOINT_PATH,
    TOC_POD_ID,
    ArkansasLexisInventory,
    ArkansasLexisNode,
    _bind_live_nodes,
    _discover_exhaustive_title_subtrees,
    container_url_matches,
    dataclass_replace_closed,
    discover_live_inventory,
    enabled,
    is_document_path,
    node_from_mapping,
    parse_expansion_payload,
    parse_root_dom_rows,
    parse_title_subtree_payload,
    reconcile_current_statute_variants,
    toc_expand_request,
    toc_open_to_request,
    variant_decision_sha256,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
)

OBSERVED_AT = "2026-08-24T02:00:00+00:00"
ROOT_SHA256 = "a" * 64
SECTION_PATH = (
    "/shared/document/statutes-legislation/urn:contentItem:4WVC-V220-R03K-21P9-00008-00"
)


def _raw_node(
    node_id: str,
    title: str,
    *,
    level: int,
    node_path: str,
    can_expand: bool = False,
    has_children: bool = False,
    link_href: str = "",
) -> dict[str, object]:
    props: dict[str, object] = {
        "linktemplatetitle": title,
        "level": level,
        "nodepath": node_path,
        "canexpand": can_expand,
        "canopen": bool(link_href),
        "haschildren": has_children,
        "subscribed": True,
    }
    if link_href:
        props.update(
            {
                "linkhref": link_href,
                "tocpricing": {
                    "currencycode": "USD",
                    "listprice": 0.0,
                    "netprice": 0.0,
                    "purchaserequired": False,
                    "usagetypecode": "subscription",
                    "documentstatus": "Available",
                },
            }
        )
    return {"id": node_id, "props": props, "collections": {}}


def _root_rows() -> list[dict[str, str]]:
    return [
        {
            "nodeid": f"AR{number:02d}",
            "title": f"Title {number} Fixture title",
            "level": "1",
            "nodepath": f"/ROOT/AR{number:02d}",
            "canexpand": "false",
            "canopen": "false",
            "haschildren": "true",
        }
        for number in range(1, 29)
    ]


def _bind(
    nodes: list[ArkansasLexisNode], receipt_sha256: str = ROOT_SHA256
) -> list[ArkansasLexisNode]:
    return _bind_live_nodes(
        nodes,
        source_url=PUBLIC_CONTAINER_URL,
        observed_at=OBSERVED_AT,
        receipt_sha256=receipt_sha256,
    )


def test_live_inventory_is_env_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENABLE_ENV, raising=False)
    assert enabled() is False
    monkeypatch.setenv(ENABLE_ENV, "yes")
    assert enabled() is True


@pytest.mark.anyio
async def test_disabled_inventory_does_not_admit_fixture_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENABLE_ENV, raising=False)
    result = await discover_live_inventory()
    assert result.status == "disabled"
    assert result.nodes == ()
    assert result.frontier["title_inventory_closed"] is False
    assert result.frontier["frontier_closed"] is False
    assert result.to_dict()["source_authority_class"] == "unverified"


@pytest.mark.anyio
async def test_arkansas_normalization_does_not_truncate_long_enacted_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enacted_text = (
        "This enacted clause remains part of the Arkansas Code and must be retained. "
        * 300
    ) + " END-OF-ENACTED-SECTION"
    html = f"""
    <html><body><main>
      <h1>1-1-101 — Long enacted section</h1>
      <div id="codes-content">
        <p>{enacted_text}</p>
        <h2>History</h2><p>Publisher history must be removed.</p>
      </div>
    </main></body></html>
    """.encode()

    async def _fake_direct(self, url: str, timeout_seconds: int = 8):
        return html

    async def _fake_justia(self, url: str, timeout_seconds: int = 18):
        return html

    monkeypatch.setattr(ArkansasScraper, "_fetch_direct_html", _fake_direct)
    monkeypatch.setattr(ArkansasScraper, "_fetch_justia_html", _fake_justia)
    scraper = ArkansasScraper("AR", "Arkansas")

    official = await scraper._build_official_statute(
        code_name="Arkansas Code",
        section_url="https://www.arkleg.state.ar.us/ArkansasCode/1-1-101/",
        section_number="1-1-101",
    )
    recovery = await scraper._build_justia_statute(
        code_name="Arkansas Code",
        section_url=(
            "https://law.justia.com/codes/arkansas/title-1/chapter-1/section-1-1-101/"
        ),
        fallback_number="fixture",
    )
    assert official is not None
    assert recovery is not None
    assert len(official.full_text or "") > 14_000
    assert len(recovery.full_text or "") > 14_000
    assert "END-OF-ENACTED-SECTION" in (official.full_text or "")
    assert "END-OF-ENACTED-SECTION" in (recovery.full_text or "")
    assert "Publisher history" not in (recovery.full_text or "")


@pytest.mark.anyio
async def test_full_corpus_refuses_secondary_rows_when_official_frontier_is_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _row(section: str, source_url: str) -> NormalizedStatute:
        return NormalizedStatute(
            state_code="AR",
            state_name="Arkansas",
            statute_id=f"AR-{section}",
            code_name="Arkansas Code",
            section_number=section,
            section_name=f"Section {section}",
            full_text=(f"Enacted Arkansas section {section}. " * 20),
            source_url=source_url,
        )

    official = _row(
        "1-1-101",
        "https://www.arkleg.state.ar.us/ArkansasCode/1-1-101/",
    )
    async def _partial_official(self, code_name: str, code_url: str, max_statutes=None):
        return [official]

    async def _recovery(self, code_name: str, max_statutes=None):
        raise AssertionError("secondary rows must not close an official frontier")

    async def _probe(self, *, code_name: str):
        return {
            "schema_version": "arkansas-delegated-body-probe/v1",
            "disposition": "delegated_body_access_blocked",
            "delegation_verified": True,
            "frontier": {
                "title_inventory_closed": True,
                "statute_locator_count": 1,
            },
            "body_probes": [],
            "secondary_recovery_admitted": False,
        }

    monkeypatch.setenv("STATE_SCRAPER_FULL_CORPUS", "1")
    monkeypatch.setattr(
        ArkansasScraper, "_scrape_official_arkansas_code", _partial_official
    )
    monkeypatch.setattr(ArkansasScraper, "_scrape_justia_titles", _recovery)
    monkeypatch.setattr(ArkansasScraper, "_probe_delegated_arkansas_code", _probe)
    scraper = ArkansasScraper("AR", "Arkansas")
    with pytest.raises(
        ArkansasDelegatedCorpusBlockedError,
        match="delegated_body_access_blocked",
    ) as exc_info:
        await scraper.scrape_code(
            "Arkansas Code",
            "https://www.arkleg.state.ar.us/ArkansasLaw/",
            max_statutes=None,
        )
    assert exc_info.value.evidence["secondary_recovery_admitted"] is False


def test_exact_container_scope_allows_only_single_bounded_request_ids() -> None:
    assert container_url_matches(PUBLIC_CONTAINER_URL) is True
    observed = f"{PUBLIC_CONTAINER_URL}&crid=request-1&prid=product_2"
    assert container_url_matches(observed) is True

    rejected = [
        PUBLIC_CONTAINER_URL.replace("config=", "config=x"),
        f"{PUBLIC_CONTAINER_URL}&unknown=1",
        f"{PUBLIC_CONTAINER_URL}&crid=",
        f"{PUBLIC_CONTAINER_URL}&crid=one&crid=two",
        f"{PUBLIC_CONTAINER_URL}&crid=request%20id",
        f"{PUBLIC_CONTAINER_URL}#fragment",
        PUBLIC_CONTAINER_URL.replace("https://", "http://"),
        PUBLIC_CONTAINER_URL.replace(".com", ".com:443"),
        PUBLIC_CONTAINER_URL.replace("https://", "https://user@"),
        PUBLIC_CONTAINER_URL.replace(
            "advance.lexis.com", "advance.lexis.com.evil.test"
        ),
        "https://[invalid/container?config=x",
    ]
    assert all(not container_url_matches(value) for value in rejected)


def test_catalog_scopes_exact_delegated_lexis_path_to_inventory_only() -> None:
    catalog = get_official_source_catalog()
    arkansas_path = catalog.get("AR").acquisition_paths[0]
    delegated = arkansas_path.delegated_inventory
    assert delegated is not None
    assert delegated.delegating_authority_url == OFFICIAL_REFERRER
    assert delegated.public_entry_url == PUBLIC_ENTRY_URL
    assert delegated.container_url == PUBLIC_CONTAINER_URL
    assert delegated.authority_scope == "toc_inventory_only"
    assert delegated.body_admissible is False
    assert delegated.full_corpus_admissible is False
    assert "advance.lexis.com" not in arkansas_path.allowed_domains

    # The nested inventory delegation does not broaden the parent official
    # path's document-body admission domains.
    with pytest.raises(DomainConstraintError):
        evaluate_admission(
            AdmissionRequest(
                postal_code="AR",
                acquisition_path_ids=(arkansas_path.path_id,),
                source_url=PUBLIC_CONTAINER_URL,
            ),
            catalog=catalog,
        )

    payload = catalog.to_dict()
    arkansas = next(
        row for row in payload["jurisdictions"] if row["postal_code"] == "AR"
    )
    arkansas["acquisition_paths"][0]["delegated_inventory"]["body_admissible"] = True
    with pytest.raises(CatalogSchemaError):
        load_official_source_catalog(payload=payload)


def test_document_locator_scope_rejects_modified_or_malformed_paths() -> None:
    assert is_document_path(SECTION_PATH) is True
    assert is_document_path(f"{ADVANCE_ORIGIN}{SECTION_PATH}") is True
    assert is_document_path(f"{SECTION_PATH}?context=copy") is False
    assert is_document_path(f"{SECTION_PATH}#fragment") is False
    assert is_document_path(f"https://advance.lexis.com:443{SECTION_PATH}") is False
    assert is_document_path(f"https://user@advance.lexis.com{SECTION_PATH}") is False
    assert is_document_path(SECTION_PATH.replace("4WVC-", "4WV-")) is False
    assert (
        is_document_path(SECTION_PATH.replace("statutes-legislation", "cases")) is False
    )
    assert is_document_path("https://[invalid/shared/document") is False


def test_toc_expansion_request_is_fixed_to_the_live_pod() -> None:
    endpoint, body = toc_expand_request("AABAAB")
    assert endpoint == f"{ADVANCE_ORIGIN}{TOC_ENDPOINT_PATH}"
    assert body == {
        "id": TOC_POD_ID,
        "props": {
            "action": "expand",
            "items": [{"fieldName": "nodeId", "value": "AABAAB"}],
        },
    }
    with pytest.raises(ValueError):
        toc_expand_request("../shared/document")


def test_toc_open_to_request_uses_only_exact_node_and_advertised_level() -> None:
    endpoint, body = toc_open_to_request("AAB", target_level=4)
    assert endpoint == f"{ADVANCE_ORIGIN}{TOC_ENDPOINT_PATH}"
    assert body == {
        "id": TOC_POD_ID,
        "props": {
            "action": "open-to",
            "items": [
                {"fieldName": "nodeId", "value": "AAB"},
                {"fieldName": "targetLevel", "value": 4},
            ],
        },
    }
    for node_id, target_level in (
        ("../AAB", 4),
        ("AAB", True),
        ("AAB", 1),
        ("AAB", 13),
        ("AAB", "deepest"),
    ):
        with pytest.raises(ValueError):
            toc_open_to_request(node_id, target_level=target_level)


def test_parses_exact_28_title_roots_without_claiming_live_authority() -> None:
    nodes = parse_root_dom_rows(_root_rows())
    assert len(nodes) == 28
    assert tuple(node.title_number for node in nodes) == EXPECTED_TITLE_NUMBERS
    assert all(node.evidence_verified is False for node in nodes)
    assert all(
        node.to_dict()["source_authority_class"] == "unverified" for node in nodes
    )

    malformed = _root_rows()
    malformed[0]["nodepath"] = "/ROOT/WRONG"
    malformed.append(deepcopy(malformed[1]))
    assert len(parse_root_dom_rows(malformed)) == 27


def test_section_locator_requires_statute_heading_and_explicit_free_availability() -> (
    None
):
    section = node_from_mapping(
        _raw_node(
            "AABAABAAC",
            "1-1-101. Extension of western boundary line.",
            level=3,
            node_path="/ROOT/AAB/AABAAB/AABAABAAC",
            link_href=SECTION_PATH,
        )
    )
    note = node_from_mapping(
        _raw_node(
            "AABAABAAB",
            "Tit. 1, Ch. 1 Note",
            level=3,
            node_path="/ROOT/AAB/AABAAB/AABAABAAB",
            link_href=SECTION_PATH.replace("21P9", "X0HX"),
        )
    )
    assert section is not None
    assert section.section_number == "1-1-101"
    assert section.public_document_available is True
    assert section.is_statute_locator is True
    assert section.evidence_verified is False
    assert note is not None
    assert note.public_document_available is True
    assert note.section_number is None
    assert note.is_statute_locator is False


def test_locator_classification_fails_closed_on_incomplete_or_ambiguous_fields() -> (
    None
):
    raw = _raw_node(
        "AABAABAAC",
        "1-1-101. Extension of western boundary line.",
        level=3,
        node_path="/ROOT/AAB/AABAAB/AABAABAAC",
        link_href=SECTION_PATH,
    )
    missing_pricing = deepcopy(raw)
    missing_pricing["props"].pop("tocpricing")
    unknown_purchase = deepcopy(raw)
    unknown_purchase["props"]["tocpricing"]["purchaserequired"] = "unknown"
    nonzero_price = deepcopy(raw)
    nonzero_price["props"]["tocpricing"]["netprice"] = 0.01
    out_of_range_title = deepcopy(raw)
    out_of_range_title["props"]["linktemplatetitle"] = "29-1-101. Not Arkansas Code."

    for candidate in (missing_pricing, unknown_purchase, nonzero_price):
        node = node_from_mapping(candidate)
        assert node is not None
        assert node.public_document_available is False
        assert node.is_statute_locator is False
    node = node_from_mapping(out_of_range_title)
    assert node is not None
    assert node.section_number is None
    assert node.is_statute_locator is False

    conflicting_id = deepcopy(raw)
    conflicting_id["props"]["nodeid"] = "DIFFERENT"
    assert node_from_mapping(conflicting_id) is None
    modified_link = deepcopy(raw)
    modified_link["props"]["linkhref"] = f"{SECTION_PATH}?context=copy"
    assert node_from_mapping(modified_link) is None


def test_expansion_parser_requires_live_parent_and_exact_direct_child_collection() -> (
    None
):
    raw_parent = _raw_node(
        "AAB",
        "Title 1 General Provisions",
        level=1,
        node_path="/ROOT/AAB",
        can_expand=True,
        has_children=True,
    )
    parent = node_from_mapping(raw_parent)
    assert parent is not None
    child = _raw_node(
        "AABAAB",
        "Chapter 1 General Provisions",
        level=2,
        node_path="/ROOT/AAB/AABAAB",
        can_expand=True,
        has_children=True,
    )
    payload = {
        "props": {},
        "collections": {
            "toccontainer": {"collections": {"tocnodes": [child]}},
        },
    }
    assert "verified" in parse_expansion_payload(payload, parent=parent)[1]

    parent = _bind([parent])[0]
    children, error = parse_expansion_payload(payload, parent=parent)
    assert error == ""
    assert [node.node_id for node in children] == ["AABAAB"]
    assert children[0].evidence_verified is False

    wrong_branch = deepcopy(child)
    wrong_branch["props"]["nodepath"] = "/ROOT/AAC/AABAAB"
    duplicate = deepcopy(payload)
    duplicate["collections"]["toccontainer"]["collections"]["tocnodes"] = [
        child,
        child,
    ]
    wrong = deepcopy(payload)
    wrong["collections"]["toccontainer"]["collections"]["tocnodes"] = [wrong_branch]
    assert parse_expansion_payload(duplicate, parent=parent)[0] == []
    assert parse_expansion_payload(wrong, parent=parent)[0] == []
    assert (
        parse_expansion_payload({"collections": {"tocnodes": [child]}}, parent=parent)[
            0
        ]
        == []
    )
    assert (
        parse_expansion_payload(
            {"collections": {"toccontainer": {"collections": {"tocnodes": []}}}},
            parent=parent,
        )[0]
        == []
    )


def test_deepest_title_subtree_closes_only_an_exact_owned_hierarchy() -> None:
    parent = _bind(
        parse_root_dom_rows(
            [
                {
                    **_root_rows()[0],
                    "nodeid": "AAB",
                    "nodepath": "/ROOT/AAB",
                }
            ]
        )
    )[0]
    chapter = _raw_node(
        "AABAAB",
        "Chapter 1 General Provisions",
        level=2,
        node_path="/ROOT/AAB/AABAAB",
        can_expand=True,
        has_children=True,
    )
    section = _raw_node(
        "AABAABAAC",
        "1-1-101. Extension of western boundary line.",
        level=3,
        node_path="/ROOT/AAB/AABAAB/AABAABAAC",
        link_href=SECTION_PATH,
    )
    payload = {
        "id": "toccontainer",
        "props": {"iscanada": False, "isdtaandoop": False},
        "collections": {
            "toccontainer": {
                "collections": {
                    "tocnodes": [
                        {
                            **chapter,
                            "collections": {"tocnodes": [section]},
                        }
                    ]
                }
            }
        }
    }

    nodes, closed_ids, error = parse_title_subtree_payload(
        payload,
        parent=parent,
        target_level=3,
    )

    assert error == ""
    assert [node.node_id for node in nodes] == ["AABAAB", "AABAABAAC"]
    assert closed_ids == ("AAB", "AABAAB")


def test_deepest_title_subtree_types_variants_and_rejects_drift() -> None:
    parent = _bind(
        parse_root_dom_rows(
            [
                {
                    **_root_rows()[0],
                    "nodeid": "AAB",
                    "nodepath": "/ROOT/AAB",
                }
            ]
        )
    )[0]
    chapter = _raw_node(
        "AABAAB",
        "Chapter 1 General Provisions",
        level=2,
        node_path="/ROOT/AAB/AABAAB",
        can_expand=True,
        has_children=True,
    )
    owned = _raw_node(
        "AABAABAAC",
        "1-1-101. Owned section.",
        level=3,
        node_path="/ROOT/AAB/AABAAB/AABAABAAC",
        link_href=SECTION_PATH,
    )

    def _payload(*nodes):
        return {
            "collections": {
                "toccontainer": {"collections": {"tocnodes": list(nodes)}}
            }
        }

    cross_title = deepcopy(owned)
    cross_title["id"] = "AABAABAAD"
    cross_title["props"]["nodepath"] = "/ROOT/AAB/AABAAB/AABAABAAD"
    cross_title["props"]["linktemplatetitle"] = "2-1-101. Foreign section."
    duplicate_cite = deepcopy(owned)
    duplicate_cite["id"] = "AABAABAAE"
    duplicate_cite["props"]["nodepath"] = "/ROOT/AAB/AABAAB/AABAABAAE"
    duplicate_cite["props"]["linkhref"] = SECTION_PATH.replace("21P9", "X0HX")
    duplicate_cite["props"]["linktemplatetitle"] = (
        "1-1-101. Owned section. [Effective September 1, 2026.]"
    )
    repeated_locator = deepcopy(duplicate_cite)
    repeated_locator["props"]["linkhref"] = SECTION_PATH
    other_chapter = _raw_node(
        "AABAAC",
        "Chapter 2 Other Provisions",
        level=2,
        node_path="/ROOT/AAB/AABAAC",
        can_expand=True,
        has_children=True,
    )
    cross_parent_variant = deepcopy(duplicate_cite)
    cross_parent_variant["id"] = "AABAACAAB"
    cross_parent_variant["props"]["nodepath"] = "/ROOT/AAB/AABAAC/AABAACAAB"
    broken_parent = deepcopy(owned)
    broken_parent["props"]["nodepath"] = "/ROOT/AAB/MISSING/AABAABAAC"

    nodes, closed_ids, error = parse_title_subtree_payload(
        _payload(
            {
                **chapter,
                "collections": {"tocnodes": [owned, duplicate_cite]},
            }
        ),
        parent=parent,
        target_level=3,
    )
    assert error == ""
    assert len(nodes) == 3
    assert closed_ids == ("AAB", "AABAAB")

    cases = [
        (_payload({**chapter, "collections": {"tocnodes": [cross_title]}}), "crossed"),
        (
            _payload(
                {
                    **chapter,
                    "collections": {"tocnodes": [owned, repeated_locator]},
                }
            ),
            "reuses an official document locator",
        ),
        (
            _payload(
                {**chapter, "collections": {"tocnodes": [owned]}},
                {
                    **other_chapter,
                    "collections": {"tocnodes": [cross_parent_variant]},
                },
            ),
            "repeats across different hierarchies",
        ),
        (_payload(broken_parent), "immediate parent"),
        (_payload(chapter), "has no direct child"),
        (
            _payload(
                {
                    "id": "AABAAB",
                    "props": {
                        "nodepath": "/ROOT/AAB/AABAAB",
                        "level": 2,
                        "canexpand": True,
                    },
                }
            ),
            "malformed",
        ),
    ]
    for payload, expected in cases:
        nodes, closed_ids, error = parse_title_subtree_payload(
            payload,
            parent=parent,
            target_level=3,
        )
        assert nodes == []
        assert closed_ids == ()
        assert expected in error


def test_unlabeled_documents_are_typed_only_in_exact_title_28_probate_tail() -> None:
    title_28 = _bind(
        parse_root_dom_rows(
            [
                {
                    **_root_rows()[27],
                    "nodeid": "ABC",
                    "nodepath": "/ROOT/ABC",
                }
            ]
        )
    )[0]
    appendix = _raw_node(
        "ABCAAG",
        "Title 28 — Appendix Administrative Order Number 12 — Official Probate Forms",
        level=2,
        node_path="/ROOT/ABC/ABCAAG",
        can_expand=True,
        has_children=True,
        link_href=SECTION_PATH.replace("21P9", "21P8"),
    )
    unlabeled = _raw_node(
        "ABCAAGAAE",
        "",
        level=3,
        node_path="/ROOT/ABC/ABCAAG/ABCAAGAAE",
        link_href=SECTION_PATH,
    )
    payload = {
        "collections": {
            "toccontainer": {
                "collections": {
                    "tocnodes": [
                        {**appendix, "collections": {"tocnodes": [unlabeled]}}
                    ]
                }
            }
        }
    }

    nodes, closed_ids, error = parse_title_subtree_payload(
        payload,
        parent=title_28,
        target_level=3,
    )
    assert error == ""
    assert closed_ids == ("ABC", "ABCAAG")
    assert (
        nodes[0].document_disposition
        == "nonstatutory_probate_forms_appendix_root"
    )
    assert nodes[-1].title == ""
    assert (
        nodes[-1].document_disposition
        == "nonstatutory_unlabeled_probate_form"
    )
    assert nodes[-1].is_statute_locator is False

    ordinary_title = _bind(
        parse_root_dom_rows(
            [
                {
                    **_root_rows()[0],
                    "nodeid": "AAB",
                    "nodepath": "/ROOT/AAB",
                }
            ]
        )
    )[0]
    drifted = deepcopy(payload)
    drifted_appendix = drifted["collections"]["toccontainer"]["collections"][
        "tocnodes"
    ][0]
    drifted_appendix["id"] = "AABAAG"
    drifted_appendix["props"]["nodepath"] = "/ROOT/AAB/AABAAG"
    drifted_leaf = drifted_appendix["collections"]["tocnodes"][0]
    drifted_leaf["id"] = "AABAAGAAE"
    drifted_leaf["props"]["nodepath"] = "/ROOT/AAB/AABAAG/AABAAGAAE"
    nodes, closed_ids, error = parse_title_subtree_payload(
        drifted,
        parent=ordinary_title,
        target_level=3,
    )
    assert nodes == []
    assert closed_ids == ()
    assert "outside the exact probate-forms tail" in error


def test_section_locator_accepts_exact_missing_period_without_range_drift() -> None:
    exact = node_from_mapping(
        _raw_node(
            "AARAADAAEAAIAAH",
            "17-82-707 Malpractice insurance.",
            level=5,
            node_path="/ROOT/AAR/AARAAD/AARAADAAE/AARAADAAEAAI/AARAADAAEAAIAAH",
            link_href=SECTION_PATH,
        )
    )
    assert exact is not None
    assert exact.section_number == "17-82-707"

    for title in (
        "17-82-707 — 17-82-709. [Repealed.]",
        "17-82-707, 17-82-709. [Reserved.]",
        "17-82-707 [Repealed.]",
        "17-82-707 — Navigation",
        "17-82-707",
    ):
        drift = node_from_mapping(
            _raw_node(
                "AARAADAAEAAIAAJ",
                title,
                level=5,
                node_path=(
                    "/ROOT/AAR/AARAAD/AARAADAAE/AARAADAAEAAI/"
                    "AARAADAAEAAIAAJ"
                ),
                link_href=SECTION_PATH.replace("21P9", "21PA"),
            )
        )
        assert drift is not None
        assert drift.section_number is None


def test_nonstatutory_documents_are_source_typed_and_unknown_labels_fail() -> None:
    title_2 = _bind(
        parse_root_dom_rows(
            [
                {
                    **_root_rows()[1],
                    "nodeid": "AAC",
                    "nodepath": "/ROOT/AAC",
                }
            ]
        )
    )[0]
    chapter = _raw_node(
        "AACAAC",
        "Chapter 19 Fertilizers",
        level=2,
        node_path="/ROOT/AAC/AACAAC",
        can_expand=True,
        has_children=True,
    )
    subchapter = _raw_node(
        "AACAACAAF",
        "Subchapter 5 — Natural Organic Fertilizers [Repealed.]",
        level=3,
        node_path="/ROOT/AAC/AACAAC/AACAACAAF",
        can_expand=True,
        has_children=True,
    )
    note = _raw_node(
        "AACAACAAFAAB",
        "Tit. 2, Ch. 19, Subch. 5 Note",
        level=4,
        node_path="/ROOT/AAC/AACAAC/AACAACAAF/AACAACAAFAAB",
        link_href=SECTION_PATH,
    )
    source_typo = _raw_node(
        "AACAACAAFAAC",
        "2-19-501 — 5-19-503. [Repealed.]",
        level=4,
        node_path="/ROOT/AAC/AACAAC/AACAACAAF/AACAACAAFAAC",
        link_href=SECTION_PATH.replace("21P9", "21PA"),
    )
    reserved = _raw_node(
        "AACAAD",
        "Chapter 99 General Provisions [Reserved.]",
        level=2,
        node_path="/ROOT/AAC/AACAAD",
        link_href=SECTION_PATH.replace("21P9", "21PB"),
    )

    def _payload(last_title: str | None = None):
        local_note = deepcopy(note)
        if last_title is not None:
            local_note["props"]["linktemplatetitle"] = last_title
        return {
            "collections": {
                "toccontainer": {
                    "collections": {
                        "tocnodes": [
                            {
                                **chapter,
                                "collections": {
                                    "tocnodes": [
                                        {
                                            **subchapter,
                                            "collections": {
                                                "tocnodes": [
                                                    local_note,
                                                    source_typo,
                                                ]
                                            },
                                        }
                                    ]
                                },
                            },
                            reserved,
                        ]
                    }
                }
            }
        }

    nodes, closed_ids, error = parse_title_subtree_payload(
        _payload(),
        parent=title_2,
        target_level=4,
    )
    assert error == ""
    assert closed_ids == ("AAC", "AACAAC", "AACAACAAF")
    dispositions = {
        node.node_id: node.document_disposition
        for node in nodes
        if node.public_document_available
    }
    assert dispositions == {
        "AACAACAAFAAB": "nonstatutory_editorial_note",
        "AACAACAAFAAC": (
            "nonstatutory_citation_collection_repealed_"
            "cross_title_source_label"
        ),
        "AACAAD": "nonstatutory_reserved_chapter",
    }

    nodes, closed_ids, error = parse_title_subtree_payload(
        _payload("Unclassified publisher navigation"),
        parent=title_2,
        target_level=4,
    )
    assert nodes == []
    assert closed_ids == ()
    assert "untyped source label" in error

    nodes, closed_ids, error = parse_title_subtree_payload(
        _payload("Tit. 3, Ch. 19, Subch. 5 Note"),
        parent=title_2,
        target_level=4,
    )
    assert nodes == []
    assert closed_ids == ()
    assert "untyped source label" in error


def _verified_variant_node(
    node_id: str,
    section_number: str,
    heading_suffix: str,
    *,
    ordinal: int,
) -> ArkansasLexisNode:
    node = node_from_mapping(
        _raw_node(
            node_id,
            f"{section_number}. {heading_suffix}",
            level=3,
            node_path=f"/ROOT/AAB/AABAAB/{node_id}",
            link_href=SECTION_PATH.replace("21P9", f"{ordinal:04X}"),
        )
    )
    assert node is not None
    return _bind([node], receipt_sha256=f"{ordinal:064x}")[0]


def test_current_variant_reconciliation_is_temporal_and_order_independent() -> None:
    nodes = [
        _verified_variant_node(
            "AABAABAAC",
            "1-1-101",
            "Old. [Effective until September 1, 2026.]",
            ordinal=1,
        ),
        _verified_variant_node(
            "AABAABAAD",
            "1-1-101",
            "New. [Effective September 1, 2026.]",
            ordinal=2,
        ),
        _verified_variant_node(
            "AABAABAAE",
            "1-1-102",
            "Old. [Effective for tax years beginning before January 1, 2026.]",
            ordinal=3,
        ),
        _verified_variant_node(
            "AABAABAAF",
            "1-1-102",
            (
                "Later. [Effective for tax years beginning on or after "
                "January 1, 2023, but before January 1, 2026.]"
            ),
            ordinal=4,
        ),
        _verified_variant_node(
            "AABAABAAG",
            "1-1-103",
            "Text. [Effective until tax years beginning on or after January 1, 2026.]",
            ordinal=5,
        ),
        _verified_variant_node(
            "AABAABAAH",
            "1-1-103",
            (
                "[Repealed effective for tax years beginning on and after "
                "January 1, 2026.]"
            ),
            ordinal=6,
        ),
    ]

    decisions = reconcile_current_statute_variants(nodes, observed_at=OBSERVED_AT)
    assert [decision.section_number for decision in decisions] == [
        "1-1-101",
        "1-1-102",
        "1-1-103",
    ]
    assert decisions[0].disposition == "selected_current_locator"
    assert decisions[0].selected_node_id == "AABAABAAC"
    assert decisions[1].disposition == "no_current_locator"
    assert decisions[2].disposition == "selected_current_locator"
    assert decisions[2].selected_node_id == "AABAABAAH"
    reversed_decisions = reconcile_current_statute_variants(
        reversed(nodes), observed_at=OBSERVED_AT
    )
    assert reversed_decisions == decisions
    assert variant_decision_sha256(reversed_decisions) == variant_decision_sha256(
        decisions
    )


def test_current_variant_reconciliation_fails_closed_on_ambiguous_labels() -> None:
    cases = (
        (
            "1-1-104",
            "Old. [Effective until contingency in Acts 2025, No. 1 is met.]",
            "New. [Effective if contingency in Acts 2025, No. 1 is met.]",
            "source_contingency_not_date_resolved",
        ),
        (
            "1-1-105",
            "Old text.",
            "New text.",
            "overlapping_active_source_intervals",
        ),
        (
            "1-1-106",
            "Old text.",
            "[Repealed.]",
            "undated_terminal_and_alternate_locator",
        ),
        (
            "1-1-107",
            "Old. [Effective for tax years beginning before January 1, 2026.]",
            (
                "Typo. [Effective for tax years beginning on or after "
                "January 1, 2026, but before Januay 1, 2026.]"
            ),
            "malformed_or_unknown_temporal_label",
        ),
    )
    nodes: list[ArkansasLexisNode] = []
    expected: dict[str, str] = {}
    for index, (section, first, second, reason) in enumerate(cases, start=20):
        nodes.extend(
            (
                _verified_variant_node(
                    f"AABAAB{index:03d}A",
                    section,
                    first,
                    ordinal=index * 2,
                ),
                _verified_variant_node(
                    f"AABAAB{index:03d}B",
                    section,
                    second,
                    ordinal=index * 2 + 1,
                ),
            )
        )
        expected[section] = reason

    decisions = reconcile_current_statute_variants(nodes, observed_at=OBSERVED_AT)
    assert {decision.section_number: decision.reason for decision in decisions} == (
        expected
    )
    assert all(decision.disposition == "unresolved" for decision in decisions)


@pytest.mark.anyio
async def test_exhaustive_title_path_uses_one_aligned_open_to_request_per_title() -> (
    None
):
    roots = _bind(parse_root_dom_rows(_root_rows()))
    dom_rows = [
        {**row, "targetlevels": ["2"]} for row in _root_rows()
    ]

    class _Page:
        def __init__(self) -> None:
            self.requests: list[dict[str, object]] = []

        async def evaluate(self, _script, request):
            body = request["patchBody"]
            self.requests.append(body)
            node_id = body["props"]["items"][0]["value"]
            child_id = f"{node_id}AAB"
            child = _raw_node(
                child_id,
                "Chapter 1 Fixture",
                level=2,
                node_path=f"/ROOT/{node_id}/{child_id}",
            )
            return {
                "status": 200,
                "contentType": "application/json",
                "text": json.dumps(
                    {
                        "collections": {
                            "toccontainer": {
                                "collections": {"tocnodes": [child]}
                            }
                        }
                    }
                ),
            }

    page = _Page()
    nodes_by_id = {node.node_id: node for node in roots}
    expanded: list[str] = []
    response_hashes: list[tuple[str, str]] = []
    response_paths: list[tuple[str, str]] = []
    error = await _discover_exhaustive_title_subtrees(
        page=page,
        dom_rows=dom_rows,
        bound_root_nodes=roots,
        nodes_by_id=nodes_by_id,
        expanded=expanded,
        response_hashes=response_hashes,
        response_paths=response_paths,
        retry_count=1,
        delay=0,
        source_url=PUBLIC_CONTAINER_URL,
        observed_at=OBSERVED_AT,
        evidence_root=None,
    )

    assert error == ""
    assert len(page.requests) == 28
    assert len(nodes_by_id) == 56
    assert expanded == [node.node_id for node in roots]
    assert len(response_hashes) == 28
    assert response_paths == []
    assert all(
        request["props"]["action"] == "open-to" for request in page.requests
    )


def test_successful_expansion_closure_is_bound_to_its_exact_response_hash() -> None:
    parent = node_from_mapping(
        _raw_node(
            "AAB",
            "Title 1 General Provisions",
            level=1,
            node_path="/ROOT/AAB",
            can_expand=True,
            has_children=True,
        )
    )
    assert parent is not None
    assert dataclass_replace_closed(parent, evidence_sha256="b" * 64) is None
    parent = _bind([parent])[0]
    assert dataclass_replace_closed(parent, evidence_sha256="invalid") is None
    closed = dataclass_replace_closed(parent, evidence_sha256="b" * 64)
    assert closed is not None
    assert closed.expansion_closed is True
    assert closed.evidence_verified is True
    assert closed.evidence_sha256 == "b" * 64


def test_title_and_toc_closure_require_live_evidence_and_exact_expansion_receipts() -> (
    None
):
    unverified_roots = parse_root_dom_rows(_root_rows())
    unverified = ArkansasLexisInventory(
        status="complete",
        final_url=PUBLIC_CONTAINER_URL,
        observed_at=OBSERVED_AT,
        delegation_verified=True,
        nodes=tuple(unverified_roots),
        expanded_node_ids=(),
        diagnostics=(),
        root_rendered_sha256=ROOT_SHA256,
    )
    assert unverified.frontier["title_inventory_closed"] is False
    assert unverified.frontier["toc_frontier_closed"] is False

    verified_roots = _bind(unverified_roots)
    partial = ArkansasLexisInventory(
        status="partial_toc",
        final_url=PUBLIC_CONTAINER_URL,
        observed_at=OBSERVED_AT,
        delegation_verified=True,
        nodes=tuple(verified_roots),
        expanded_node_ids=(),
        diagnostics=("bounded fixture",),
        root_rendered_sha256=ROOT_SHA256,
    )
    assert partial.frontier["title_inventory_closed"] is True
    assert len(partial.frontier["unresolved_expandable_node_ids"]) == 28
    assert partial.frontier["toc_frontier_closed"] is False
    assert partial.frontier["frontier_closed"] is False

    closed_roots: list[ArkansasLexisNode] = []
    receipts: list[tuple[str, str]] = []
    for index, node in enumerate(verified_roots, start=1):
        response_hash = f"{index:064x}"
        closed = dataclass_replace_closed(node, evidence_sha256=response_hash)
        assert closed is not None
        closed_roots.append(closed)
        receipts.append((node.node_id, response_hash))
    complete = ArkansasLexisInventory(
        status="complete",
        final_url=PUBLIC_CONTAINER_URL,
        observed_at=OBSERVED_AT,
        delegation_verified=True,
        nodes=tuple(closed_roots),
        expanded_node_ids=tuple(node.node_id for node in closed_roots),
        diagnostics=(),
        root_rendered_sha256=ROOT_SHA256,
        expansion_response_sha256=tuple(receipts),
    )
    assert complete.frontier["expansion_receipts_valid"] is True
    assert complete.frontier["toc_frontier_closed"] is True
    assert complete.frontier["body_frontier_closed"] is False
    assert complete.frontier["frontier_closed"] is False
    assert complete.frontier["full_corpus_admissible"] is False

    tampered = ArkansasLexisInventory(
        **{
            **complete.__dict__,
            "expansion_response_sha256": tuple(receipts[:-1]),
        }
    )
    assert tampered.frontier["expansion_receipts_valid"] is False
    assert tampered.frontier["toc_frontier_closed"] is False


def test_inventory_write_preserves_receipt_but_never_claims_body_admission(
    tmp_path,
) -> None:
    nodes = _bind(parse_root_dom_rows(_root_rows()))
    inventory = ArkansasLexisInventory(
        status="partial_toc",
        final_url=PUBLIC_CONTAINER_URL,
        observed_at=OBSERVED_AT,
        delegation_verified=True,
        nodes=tuple(nodes),
        expanded_node_ids=(),
        diagnostics=("title-only fixture",),
        root_rendered_sha256=ROOT_SHA256,
    )
    output = inventory.write(tmp_path / "arkansas_toc.json")
    written = json.loads(output.read_text())
    assert written["source_authority_class"] == "official"
    assert written["nodes"][0]["evidence_verified"] is True
    assert written["frontier"]["title_inventory_closed"] is True
    assert written["frontier"]["body_frontier_closed"] is False
    assert written["frontier"]["full_corpus_admissible"] is False


@pytest.mark.anyio
async def test_opt_in_bounded_live_toc_smoke() -> None:
    if os.getenv("ARKANSAS_LEXIS_LIVE_SMOKE") != "1":
        pytest.skip("set ARKANSAS_LEXIS_LIVE_SMOKE=1 for bounded public TOC smoke")
    result = await discover_live_inventory(
        max_expansions=1,
        retries=1,
        request_delay_seconds=0,
        timeout_ms=45_000,
        require_enabled=False,
    )
    assert result.status == "partial_toc"
    assert container_url_matches(result.final_url)
    assert result.delegation_verified is True
    assert result.frontier["discovered_title_count"] == 28
    assert tuple(result.frontier["discovered_title_numbers"]) == EXPECTED_TITLE_NUMBERS
    assert result.frontier["title_inventory_closed"] is True
    assert result.frontier["expanded_node_count"] == 1
    assert result.frontier["toc_frontier_closed"] is False
    assert result.frontier["body_frontier_closed"] is False
    assert result.frontier["full_corpus_admissible"] is False
    assert urlparse(result.final_url).hostname == "advance.lexis.com"
