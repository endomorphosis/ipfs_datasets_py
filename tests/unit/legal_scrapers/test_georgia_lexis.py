"""Georgia's env-gated, state-designated Lexis public-access frontier."""

from __future__ import annotations

from copy import deepcopy
from inspect import signature
from urllib.parse import parse_qs, urlparse

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.georgia_lexis import (
    ADVANCE_ORIGIN,
    ENABLE_ENV,
    EXPECTED_TITLE_NUMBERS,
    PUBLIC_CONTAINER_URL,
    PUBLIC_ENTRY_URL,
    TOC_ENDPOINT_PATH,
    TOC_POD_ID,
    TOC_URN_PATH,
    GeorgiaLexisSearchHit,
    GeorgiaLexisTocNode,
    _bind_live_toc_nodes,
    _mark_live_expansion_closed,
    _parse_toc_expansion_payload,
    bootstrap_container_url_matches,
    build_section_search_url,
    classify_lexis_page,
    delegation_banner_present,
    discover_live_georgia_lexis_toc,
    document_urls_from_nodes,
    georgia_lexis_enabled,
    georgia_lexis_frontier,
    is_lexis_document_url,
    normalize_section_number,
    parse_georgia_lexis_document_html,
    parse_toc_dom_rows,
    parse_toc_payload,
    parse_toc_search_results,
    section_search_url_matches,
    toc_expand_request,
)

DELEGATION_BANNER = (
    "These online legal resources are made available for public use by the "
    "Georgia Code Revision Commission on behalf of the Georgia General Assembly "
    "through a contractual arrangement with LexisNexis, which prepares and "
    "maintains this website. Official Code of Georgia Annotated"
)


def _toc_node(
    node_id: str,
    title: str,
    *,
    level: int,
    node_path: str,
    can_expand: bool,
    has_children: bool,
    link_href: str = "",
):
    props = {
        "linktemplatetitle": title,
        "canselect": True,
        "canexpand": can_expand,
        "canopen": bool(link_href),
        "islink": bool(link_href),
        "haschildren": has_children,
        "level": level,
        "nodepath": node_path,
        "subscribed": True,
    }
    if link_href:
        props.update(
            {
                "linkhref": link_href,
                "linkaction": "toclink",
                "tocpricing": {
                    "currencycode": "USD",
                    "listprice": 0,
                    "netprice": 0,
                    "purchaserequired": False,
                    "usagetypecode": "subscription",
                    "documentstatus": "Available",
                },
            }
        )
    return {
        "id": node_id,
        "props": props,
        "data": {"selected": False, "expanded": False, "populated": False},
        "collections": {},
    }


def _section_evidence(source_url: str, section: str = "1-1-1"):
    nodes = parse_toc_payload(
        {
            "collections": {
                "tocnodes": [
                    _toc_node(
                        "AABAABAAC",
                        f"{section}. Enactment of Code.",
                        level=3,
                        node_path="/ROOT/AAB/AABAAB/AABAABAAC",
                        can_expand=False,
                        has_children=False,
                        link_href=urlparse(source_url).path,
                    )
                ]
            }
        }
    )
    return _bind_live_toc_nodes(
        nodes,
        source_url=PUBLIC_CONTAINER_URL,
        observed_at="2026-08-24T00:00:00+00:00",
        receipt_sha256="a" * 64,
    )[0]


def test_live_adapter_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENABLE_ENV, raising=False)
    assert georgia_lexis_enabled() is False
    monkeypatch.setenv(ENABLE_ENV, "1")
    assert georgia_lexis_enabled() is True


@pytest.mark.anyio
async def test_disabled_live_discovery_does_not_launch_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENABLE_ENV, raising=False)
    result = await discover_live_georgia_lexis_toc()
    assert result.status == "disabled"
    assert result.nodes == ()
    assert result.observed_at.endswith("+00:00")
    assert result.frontier["full_corpus_admissible"] is False
    assert result.to_dict()["source_authority_class"] == "unverified"


def test_builds_scoped_official_toc_section_search_url() -> None:
    assert PUBLIC_CONTAINER_URL.startswith(f"{ADVANCE_ORIGIN}/container?config=")
    url = build_section_search_url("42-8-34.1")
    query = parse_qs(urlparse(url).query)
    assert url.startswith(f"{ADVANCE_ORIGIN}/container?")
    assert query["pdtocfullpath"] == [TOC_URN_PATH]
    assert query["pdtocsearchterm"] == ["42-8-34.1"]
    assert query["pdtocsearchoption"] == ["docsonly"]
    assert section_search_url_matches(url, "42-8-34.1") is True
    assert section_search_url_matches(url, "16-1-1") is False


def test_exact_source_scope_rejects_config_port_userinfo_and_fragment() -> None:
    assert bootstrap_container_url_matches(PUBLIC_CONTAINER_URL) is True
    assert (
        bootstrap_container_url_matches(
            f"{PUBLIC_CONTAINER_URL}&crid=request-id&prid=product-id"
        )
        is True
    )
    assert bootstrap_container_url_matches(
        PUBLIC_CONTAINER_URL.replace("config=", "config=x")
    ) is (False)
    assert bootstrap_container_url_matches(
        PUBLIC_CONTAINER_URL.replace(".com", ".com:443")
    ) is (False)
    assert bootstrap_container_url_matches(
        PUBLIC_CONTAINER_URL.replace("https://", "https://u@")
    ) is (False)
    assert bootstrap_container_url_matches(f"{PUBLIC_CONTAINER_URL}#fragment") is False

    search_url = build_section_search_url("1-1-1")
    assert section_search_url_matches(search_url, "1-1-1") is True
    assert section_search_url_matches(
        search_url.replace("config=", "config=x"), "1-1-1"
    ) is (False)
    assert (
        section_search_url_matches(
            search_url.replace("pdtocsearchoption=docsonly", "pdtocsearchoption=all"),
            "1-1-1",
        )
        is False
    )
    assert section_search_url_matches(f"{search_url}#fragment", "1-1-1") is False

    document_path = (
        "/shared/document/statutes-legislation/"
        "urn:contentItem:6348-FR61-DYB7-W4B4-00008-00"
    )
    assert is_lexis_document_url(f"{ADVANCE_ORIGIN}{document_path}") is True
    assert (
        is_lexis_document_url(f"https://advance.lexis.com:443{document_path}") is False
    )
    assert is_lexis_document_url(f"{ADVANCE_ORIGIN}{document_path}#fragment") is False


@pytest.mark.parametrize("value", ["", "0-1-1", "54-1-1", "16", "16-1", "../../16-1-1"])
def test_rejects_unbounded_or_invalid_section_search_values(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_section_number(value)


def test_toc_expand_request_is_bounded_to_live_pod() -> None:
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
        toc_expand_request("../document")


def test_classifies_delegated_toc_and_access_blocks_fail_closed() -> None:
    assert delegation_banner_present(DELEGATION_BANNER) is True
    assert (
        classify_lexis_page(DELEGATION_BANNER, final_url=PUBLIC_CONTAINER_URL)
        == "official_toc"
    )
    assert classify_lexis_page(DELEGATION_BANNER, final_url=PUBLIC_ENTRY_URL) == (
        "unexpected_source"
    )
    assert (
        classify_lexis_page("Let's confirm you are human CAPTCHA") == "blocked_captcha"
    )
    assert classify_lexis_page("RobotValidation") == "blocked_robot_validation"
    assert (
        classify_lexis_page(
            "Sign in to continue",
            final_url="https://signin.lexisnexis.com/lnaccess/app/signin",
        )
        == "blocked_sign_in"
    )
    assert classify_lexis_page(
        "LNDOMENV Browser redirect to the intended destination"
    ) == ("session_bootstrap")
    assert (
        classify_lexis_page("I Agree to these terms and conditions")
        == "consent_required"
    )


def test_parses_exact_toc_search_hit_as_truncated_discovery_evidence_only() -> None:
    html = """
    <html><head><title>Results for: 1-1-1</title></head><body>
      <ol>
        <li data-id="sr0" class="row_sr0 usview">
          <input data-position="1"
            data-docid="urn:contentItem:6348-FR61-DYB7-W4B4-00008-00">
          <h2 class="doc-title"><a href="#" data-action="title">
            1-1-1. Enactment of Code.
          </a></h2>
          <div class="metadata">
            <span>GA - Official Code of Georgia Annotated</span>
            <span>O.C.G.A. § 1-1-1</span>
          </div>
          <article>
            <p class="min vis">TITLE 1 General Provisions &gt; CHAPTER 1 General Provisions</p>
            <p class="min">(a) The statutory portion of the codification of Georgia laws
              prepared by the Code Revision Commission shall have the effect of statutes
              enacted by the General Assembly of Georgia. The following matter ...</p>
            <p><a data-action="publichitsteaser">... O.C.G.A. § 1-1-1 Georgia ...</a></p>
          </article>
        </li>
      </ol>
    </body></html>
    """
    assert classify_lexis_page(html) == "toc_search_excerpt"
    search_url = build_section_search_url("1-1-1")
    hits = parse_toc_search_results(
        html,
        expected_section="1-1-1",
        source_url=search_url,
    )
    assert len(hits) == 1
    hit = hits[0]
    assert hit.section_number == "1-1-1"
    assert hit.document_urn == "urn:contentItem:6348-FR61-DYB7-W4B4-00008-00"
    assert hit.document_url.endswith(
        "/shared/document/statutes-legislation/"
        "urn:contentItem:6348-FR61-DYB7-W4B4-00008-00"
    )
    assert hit.truncated is True
    assert hit.to_dict()["body_admissible"] is False
    assert hit.to_dict()["source_authority_class"] == "unverified"
    assert (
        parse_toc_search_results(
            html,
            expected_section="16-1-1",
            source_url=search_url,
        )
        == []
    )
    assert (
        parse_georgia_lexis_document_html(
            html,
            source_url=hit.document_url,
            expected_section="1-1-1",
            discovery_evidence=hit,
        )
        is None
    )


def test_parses_nested_title_chapter_and_zero_price_section_leaf() -> None:
    leaf_path = (
        "/shared/document/statutes-legislation/"
        "urn:contentItem:6348-FR61-DYB7-W4B4-00008-00"
    )
    payload = {
        "props": {"component": "toc"},
        "collections": {
            "toccontainer": {
                "id": "toccontainer",
                "props": {},
                "collections": {
                    "tocnodes": [
                        _toc_node(
                            "AAB",
                            "TITLE 1 General Provisions (Chs. 1 — 5)",
                            level=1,
                            node_path="/ROOT/AAB",
                            can_expand=True,
                            has_children=True,
                        ),
                        _toc_node(
                            "AABAAB",
                            "CHAPTER 1 General Provisions (§§ 1-1-1 — 1-1-11)",
                            level=2,
                            node_path="/ROOT/AAB/AABAAB",
                            can_expand=True,
                            has_children=True,
                        ),
                        _toc_node(
                            "AABAABAAC",
                            "1-1-1. Enactment of Code.",
                            level=3,
                            node_path="/ROOT/AAB/AABAAB/AABAABAAC",
                            can_expand=False,
                            has_children=False,
                            link_href=leaf_path,
                        ),
                    ]
                },
            }
        },
    }
    nodes = parse_toc_payload(payload)
    assert [node.node_id for node in nodes] == ["AAB", "AABAAB", "AABAABAAC"]
    assert nodes[0].title_number == "1"
    assert nodes[1].chapter_number == "1"
    assert nodes[2].section_number == "1-1-1"
    assert nodes[2].public_document_available is True
    assert document_urls_from_nodes(nodes) == []
    verified_nodes = _bind_live_toc_nodes(
        nodes,
        source_url=PUBLIC_CONTAINER_URL,
        observed_at="2026-08-24T00:00:00+00:00",
        receipt_sha256="b" * 64,
    )
    assert document_urls_from_nodes(verified_nodes) == [f"{ADVANCE_ORIGIN}{leaf_path}"]


def test_parses_expandable_chapter_below_an_official_grouping_layer() -> None:
    node = _toc_node(
        "ABKAAFAAB",
        "CHAPTER 80 General Provisions (§§ 36-80-1 — 36-80-31)",
        level=3,
        node_path="/ROOT/ABK/ABKAAF/ABKAAFAAB",
        can_expand=True,
        has_children=True,
    )

    parsed = parse_toc_payload(node)

    assert len(parsed) == 1
    assert parsed[0].chapter_number == "80"
    assert parsed[0].link_href == ""


def test_redesignated_section_range_is_structural_not_a_duplicate_section() -> None:
    node = _toc_node(
        "AAMAAFAAZ",
        "12-3-710 through 12-3-715. Redesignated.",
        level=3,
        node_path="/ROOT/AAM/AAMAAF/AAMAAFAAZ",
        can_expand=False,
        has_children=False,
        link_href=(
            "/shared/document/statutes-legislation/"
            "urn:contentItem:6JT3-CVH3-S4WF-31V1-00008-00"
        ),
    )

    parsed = parse_toc_payload(node)

    assert len(parsed) == 1
    assert parsed[0].section_number is None


def test_public_document_availability_requires_complete_explicit_zero_pricing() -> None:
    leaf_path = (
        "/shared/document/statutes-legislation/"
        "urn:contentItem:6348-FR61-DYB7-W4B4-00008-00"
    )
    raw = _toc_node(
        "AABAABAAC",
        "1-1-1. Enactment of Code.",
        level=3,
        node_path="/ROOT/AAB/AABAAB/AABAABAAC",
        can_expand=False,
        has_children=False,
        link_href=leaf_path,
    )
    assert parse_toc_payload(raw)[0].public_document_available is True

    missing_pricing = deepcopy(raw)
    missing_pricing["props"].pop("tocpricing")
    assert parse_toc_payload(missing_pricing)[0].public_document_available is False

    nonzero_price = deepcopy(raw)
    nonzero_price["props"]["tocpricing"]["listprice"] = 1
    assert parse_toc_payload(nonzero_price)[0].public_document_available is False

    missing_status = deepcopy(raw)
    missing_status["props"]["tocpricing"].pop("documentstatus")
    assert parse_toc_payload(missing_status)[0].public_document_available is False


def test_expansion_closure_requires_exact_collection_direct_ancestry_and_levels() -> (
    None
):
    parent_raw = _toc_node(
        "AAB",
        "TITLE 1 General Provisions",
        level=1,
        node_path="/ROOT/AAB",
        can_expand=True,
        has_children=True,
    )
    parent = _bind_live_toc_nodes(
        parse_toc_payload(parent_raw),
        source_url=PUBLIC_CONTAINER_URL,
        observed_at="2026-08-24T00:00:00+00:00",
        receipt_sha256="d" * 64,
    )[0]
    child = _toc_node(
        "AABAAB",
        "CHAPTER 1 General Provisions",
        level=2,
        node_path="/ROOT/AAB/AABAAB",
        can_expand=True,
        has_children=True,
    )
    payload = {
        "props": {},
        "collections": {
            "toccontainer": {
                "collections": {"tocnodes": [child]},
            }
        },
    }
    children, error = _parse_toc_expansion_payload(payload, parent=parent)
    assert error == ""
    assert [node.node_id for node in children] == ["AABAAB"]
    closed_parent = _mark_live_expansion_closed(parent)
    assert closed_parent is not None
    assert closed_parent.expansion_closed is True
    assert (
        georgia_lexis_frontier(
            [closed_parent],
            expanded_node_ids=["AAB"],
            delegation_verified=True,
        )["unresolved_expandable_node_ids"]
        == []
    )

    unrelated = _toc_node(
        "AACAAB",
        "CHAPTER 1 Wrong title",
        level=2,
        node_path="/ROOT/AAC/AACAAB",
        can_expand=True,
        has_children=True,
    )
    bad_payload = deepcopy(payload)
    bad_payload["collections"]["toccontainer"]["collections"]["tocnodes"] = [
        child,
        unrelated,
    ]
    assert _parse_toc_expansion_payload(bad_payload, parent=parent)[0] == []
    assert (
        "outside the requested branch"
        in _parse_toc_expansion_payload(
            bad_payload,
            parent=parent,
        )[1]
    )
    assert (
        _parse_toc_expansion_payload(
            {"collections": {"tocnodes": [child]}}, parent=parent
        )[0]
        == []
    )


def test_dom_title_inventory_proves_only_title_closure() -> None:
    rows = [
        {
            "data-nodeid": f"AA{number:02d}",
            "data-title": f"TITLE {number} Fixture title",
            "data-level": "1",
            "data-nodepath": f"/ROOT/AA{number:02d}",
            "data-canexpand": "true",
            "data-haschildren": "true",
            "aria-expanded": "false",
        }
        for number in range(1, 54)
    ]
    nodes = parse_toc_dom_rows(rows)
    assert (
        georgia_lexis_frontier(nodes, delegation_verified=True)[
            "title_inventory_closed"
        ]
        is False
    )
    verified_nodes = _bind_live_toc_nodes(
        nodes,
        source_url=PUBLIC_CONTAINER_URL,
        observed_at="2026-08-24T00:00:00+00:00",
        receipt_sha256="c" * 64,
    )
    frontier = georgia_lexis_frontier(verified_nodes, delegation_verified=True)
    assert tuple(frontier["discovered_title_numbers"]) == EXPECTED_TITLE_NUMBERS
    assert frontier["title_inventory_closed"] is True
    assert len(frontier["unresolved_expandable_node_ids"]) == 53
    assert frontier["body_frontier_closed"] is False
    assert frontier["frontier_closed"] is False
    assert frontier["full_corpus_admissible"] is False


def test_title_inventory_requires_delegation_and_exact_53() -> None:
    rows = [
        {
            "nodeid": f"AA{number:02d}",
            "title": f"TITLE {number} Fixture title",
            "level": "1",
            "nodepath": f"/ROOT/AA{number:02d}",
            "canexpand": "true",
            "haschildren": "true",
        }
        for number in range(1, 53)
    ]
    nodes = parse_toc_dom_rows(rows)
    assert georgia_lexis_frontier(nodes, delegation_verified=True)[
        "missing_title_numbers"
    ] == ["53"]
    assert (
        georgia_lexis_frontier(nodes, delegation_verified=True)[
            "title_inventory_closed"
        ]
        is False
    )
    complete_nodes = parse_toc_dom_rows(
        rows
        + [
            {
                "nodeid": "AA53",
                "title": "TITLE 53 Fixture title",
                "level": "1",
                "nodepath": "/ROOT/AA53",
                "canexpand": "true",
                "haschildren": "true",
            }
        ]
    )
    assert georgia_lexis_frontier(complete_nodes)["title_inventory_closed"] is False


def test_title_inventory_rejects_synthetic_nonroot_and_unverified_nodes() -> None:
    synthetic = [
        GeorgiaLexisTocNode(
            node_id=f"ZZ{number:02d}",
            title=f"TITLE {number} synthetic nested heading",
            level=9,
            node_path=f"/OTHER/ZZ{number:02d}",
            can_expand=False,
            can_open=False,
            has_children=False,
            expanded=False,
            populated=False,
            link_href="",
            subscribed=None,
            purchase_required=None,
            list_price=None,
            net_price=None,
        )
        for number in range(1, 54)
    ]
    frontier = georgia_lexis_frontier(synthetic, delegation_verified=True)
    assert frontier["discovered_title_count"] == 0
    assert frontier["title_inventory_closed"] is False

    root_rows = [
        {
            "nodeid": f"AA{number:02d}",
            "title": f"TITLE {number} unverified fixture",
            "level": "1",
            "nodepath": f"/ROOT/AA{number:02d}",
            "canexpand": "true",
            "haschildren": "true",
        }
        for number in range(1, 54)
    ]
    unverified_roots = parse_toc_dom_rows(root_rows)
    assert (
        georgia_lexis_frontier(
            unverified_roots,
            delegation_verified=True,
        )["title_inventory_closed"]
        is False
    )


def test_locator_receipt_cannot_authorize_caller_supplied_document_html() -> None:
    source_url = (
        "https://advance.lexis.com/shared/document/statutes-legislation/"
        "urn:contentItem:6348-FR61-DYB7-W4B4-00008-00"
    )
    html = """
    <html><body>
      <nav>Search All Documents</nav>
      <main data-document-content>
        <h1>1-1-1. Enactment of Code.</h1>
        <p>The statutory laws of this state are codified and enacted as provided
        in this Code, and the statutory portion controls as the law of Georgia.</p>
        <h2>HISTORY: Ga. L. editorial and publisher annotation</h2>
        <p>Publisher annotation that must not be admitted.</p>
      </main>
    </body></html>
    """
    assert (
        parse_georgia_lexis_document_html(
            html,
            source_url=source_url,
            expected_section="1-1-1",
            discovery_evidence=_section_evidence(source_url),
        )
        is None
    )
    mutated_html = html.replace(
        "statutory portion controls as the law of Georgia",
        "fabricated caller-controlled text must never be admitted",
    )
    assert (
        parse_georgia_lexis_document_html(
            mutated_html,
            source_url=source_url,
            expected_section="1-1-1",
            discovery_evidence=_section_evidence(source_url),
        )
        is None
    )


def test_document_parser_rejects_shells_mismatch_and_unscoped_urls() -> None:
    good_url = (
        "https://advance.lexis.com/shared/document/statutes-legislation/"
        "urn:contentItem:6348-FR61-DYB7-W4B4-00008-00"
    )
    html = """
    <main><h1>1-1-1. Enactment of Code.</h1>
    <p>This is enough statutory text to pass the bounded parser minimum safely.</p></main>
    """
    assert is_lexis_document_url(good_url) is True
    assert (
        parse_georgia_lexis_document_html(
            "<html>RobotValidation</html>",
            source_url=good_url,
            expected_section="1-1-1",
            discovery_evidence=_section_evidence(good_url),
        )
        is None
    )
    assert (
        parse_georgia_lexis_document_html(
            html,
            source_url=good_url,
            expected_section="16-1-1",
            discovery_evidence=_section_evidence(good_url),
        )
        is None
    )
    assert (
        parse_georgia_lexis_document_html(
            html,
            source_url="https://law.justia.com/codes/georgia/section-1-1-1",
            expected_section="1-1-1",
            discovery_evidence=_section_evidence(good_url),
        )
        is None
    )
    assert (
        parse_georgia_lexis_document_html(
            html,
            source_url=good_url,
            expected_section="1-1-1",
            discovery_evidence=None,
        )
        is None
    )


def test_raw_synthetic_evidence_cannot_authorize_an_official_body() -> None:
    assert "_evidence_capability" not in signature(GeorgiaLexisTocNode).parameters
    assert "_evidence_capability" not in signature(GeorgiaLexisSearchHit).parameters
    good_url = (
        "https://advance.lexis.com/shared/document/statutes-legislation/"
        "urn:contentItem:6348-FR61-DYB7-W4B4-00008-00"
    )
    raw_node = parse_toc_payload(
        _toc_node(
            "AABAABAAC",
            "1-1-1. Synthetic section.",
            level=3,
            node_path="/ROOT/AAB/AABAAB/AABAABAAC",
            can_expand=False,
            has_children=False,
            link_href=urlparse(good_url).path,
        )
    )[0]
    assert raw_node.evidence_verified is False
    assert raw_node.to_dict()["source_authority_class"] == "unverified"
    html = """
    <main><h1>1-1-1. Synthetic section.</h1>
    <p>Fabricated statutory text long enough to satisfy the parser length threshold.</p></main>
    """
    assert (
        parse_georgia_lexis_document_html(
            html,
            source_url=good_url,
            expected_section="1-1-1",
            discovery_evidence=raw_node,
        )
        is None
    )


def test_search_parser_rejects_wrong_code_metadata_even_on_scoped_url() -> None:
    html = """
    <li data-id="sr0">
      <input data-docid="urn:contentItem:6348-FR61-DYB7-W4B4-00008-00">
      <h2 class="doc-title">1-1-1. Wrong jurisdiction.</h2>
      <div class="metadata"><span>NY - New York Code</span><span>N.Y. Law § 1</span></div>
      <article><p>TITLE 1 New York</p><p>Not Georgia text ...</p></article>
    </li>
    """
    assert (
        parse_toc_search_results(
            html,
            expected_section="1-1-1",
            source_url=build_section_search_url("1-1-1"),
        )
        == []
    )


def test_document_parser_requires_exact_document_page_classification() -> None:
    good_url = (
        "https://advance.lexis.com/shared/document/statutes-legislation/"
        "urn:contentItem:6348-FR61-DYB7-W4B4-00008-00"
    )
    shell = f"""
    <main>{DELEGATION_BANNER}<h1>1-1-1. Enactment of Code.</h1>
    <p>This shell includes enough text but is not classified as a statute document.</p></main>
    """
    assert (
        parse_georgia_lexis_document_html(
            shell,
            source_url=good_url,
            expected_section="1-1-1",
            discovery_evidence=_section_evidence(good_url),
        )
        is None
    )
