from __future__ import annotations

import hashlib

import pytest

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.illinois import (
    IllinoisScraper,
)


def _strict_parse(
    html: str,
    *,
    act_id: str = "588",
    chap_act: str = "35 ILCS 143/",
):
    return IllinoisScraper("IL", "Illinois")._parse_full_act_html(
        code_name="Illinois Compiled Statutes",
        chapter={
            "chapter_name": "REVENUE",
            "major_topic": "REGULATION",
            "url": "https://www.ilga.gov/Legislation/ILCS/Acts?ChapterID=8",
        },
        act={
            "act_id": act_id,
            "act_name": "Illinois Economic Opportunity Act.",
            "chap_act": chap_act,
            "url": (
                "https://www.ilga.gov/Legislation/ILCS/Articles?"
                f"ActID={act_id}"
            ),
        },
        full_url=(
            "https://www.ilga.gov/legislation/ILCS/details?"
            f"ActID={act_id}&ChapterID=8&SeqStart=&ChapAct=FullText"
        ),
        html=html,
        transport_receipt={
            "official_url": (
                "https://www.ilga.gov/legislation/ILCS/details?"
                f"ActID={act_id}&ChapterID=8&SeqStart=&ChapAct=FullText"
            ),
            "content_sha256": "1" * 64,
            "source_transport": "direct",
        },
        strict=True,
    )


_PENDING_CHAPTER = {
    "chapter_id": "18",
    "chapter_number": "110",
    "chapter_name": "HIGHER EDUCATION",
    "major_topic": "EDUCATION",
    "url": (
        "https://www.ilga.gov/Legislation/ILCS/Acts?"
        "ChapterID=18&ChapterNumber=110"
    ),
}
_PENDING_ACT = {
    "act_id": "4702",
    "chapter_id": "18",
    "act_name": (
        "Higher Education Student Support and Academic Freedom Act."
    ),
    "chap_act": "110 ILCS 193/",
    "url": (
        "https://www.ilga.gov/Legislation/ILCS/Articles?"
        "ActID=4702&ChapterID=18"
    ),
}
_PENDING_FULL_URL = (
    "https://www.ilga.gov/legislation/ILCS/details?"
    "ActID=4702&ChapterID=18&SeqStart=&ChapAct=FullText"
)
_PENDING_PUBLIC_ACT_URL = (
    "https://www.ilga.gov/Legislation/PublicActs/View/104-0768"
)


def _receipt(url: str, payload: bytes) -> dict[str, str]:
    return {
        "official_url": url,
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "source_transport": "direct",
    }


def _pending_public_act_payload() -> bytes:
    return b"""
    <html><body>
      <div id="billtextanchor">
        <p>Public Act 104-0768</p><p>HB4304 Enrolled</p>
        <code>Section 1.</code><code>Short title.</code>
        <code>This Act may be cited as the Higher Education Student Support
        and Academic Freedom Act.</code>
        <code>Section 5.</code><code>Legislative findings.</code>
        <code>The General Assembly finds that students benefit from free inquiry.</code>
        <code>Section 10.</code><code>Student support and academic access charter.</code>
        <code>Public institutions of higher education shall support students.</code>
        <code>Section 15.</code><code>Construction of Act.</code>
        <code>This Act shall be construed in accordance with applicable law.</code>
      </div>
      <div><span>Effective Date:</span> 1/1/2027</div>
    </body></html>
    """


def _parse_pending_public_act(
    public_act_payload: bytes,
    *,
    full_text_receipt: dict[str, str] | None = None,
    public_act_receipt: dict[str, str] | None = None,
    owned_sections_override: tuple[str, ...] | None = None,
):
    scraper = IllinoisScraper("IL", "Illinois")
    full_text_payload = b"<html><body>Official empty ILCS shell.</body></html>"
    spec = scraper._pending_ilcs_public_act_spec(
        chapter=_PENDING_CHAPTER,
        act=_PENDING_ACT,
    )
    assert spec is not None
    if owned_sections_override is not None:
        spec = {**spec, "section_numbers": owned_sections_override}
        scraper._pending_ilcs_public_act_spec = (
            lambda *, chapter, act: dict(spec)
        )
    return scraper._parse_pending_ilcs_public_act_html(
        code_name="Illinois Compiled Statutes",
        chapter=_PENDING_CHAPTER,
        act=_PENDING_ACT,
        full_url=_PENDING_FULL_URL,
        full_text_payload=full_text_payload,
        full_text_receipt=(
            full_text_receipt
            if full_text_receipt is not None
            else _receipt(_PENDING_FULL_URL, full_text_payload)
        ),
        spec=spec,
        public_act_url=_PENDING_PUBLIC_ACT_URL,
        public_act_payload=public_act_payload,
        public_act_receipt=(
            public_act_receipt
            if public_act_receipt is not None
            else _receipt(_PENDING_PUBLIC_ACT_URL, public_act_payload)
        ),
    )


@pytest.mark.anyio
async def test_full_act_segments_only_citations_owned_by_current_act(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = """
    <html><body>
      <code>(35 ILCS 505/1)</code>
      <code>Sec. 1. Current-act section one contains enough official legal text
      and refers to (35 ILCS 105/3-41) without turning that cross-reference
      into a separate statute record.</code>
      <code>(35 ILCS 505/2)</code>
      <code>Sec. 2. Current-act section two also contains enough official legal
      text to pass the strict parser threshold.</code>
    </body></html>
    """

    async def _full_act_url(self: IllinoisScraper, _url: str) -> str:
        return "https://www.ilga.gov/legislation/ILCS/details?ActID=610"

    async def _fetch_html(
        self: IllinoisScraper,
        _url: str,
        timeout_seconds: int = 20,
    ) -> str:
        del timeout_seconds
        return html

    monkeypatch.setattr(IllinoisScraper, "_full_act_url", _full_act_url)
    monkeypatch.setattr(IllinoisScraper, "_fetch_official_il_html", _fetch_html)

    rows = await IllinoisScraper("IL", "Illinois")._parse_full_act(
        code_name="Illinois Compiled Statutes",
        chapter={
            "chapter_name": "REVENUE",
            "major_topic": "GOVERNMENT",
            "url": "https://www.ilga.gov/Legislation/ILCS/Acts?ChapterNumber=35",
        },
        act={
            "act_id": "610",
            "act_name": "Motor Fuel Tax Law.",
            "chap_act": "35 ILCS 505/",
            "url": "https://www.ilga.gov/Legislation/ILCS/Articles?ActID=610",
        },
    )

    assert [row.official_cite for row in rows] == [
        "35 ILCS 505/1",
        "35 ILCS 505/2",
    ]
    assert "35 ILCS 105/3-41" in rows[0].full_text
    assert all(row.structured_data["chap_act"] == "35 ILCS 505/" for row in rows)


def test_duplicate_official_marker_uses_distinct_adjacent_section_heading() -> None:
    rows = _strict_parse(
        """
        <html><body>
          <div align="justify">
            <code>(35 ILCS 143/5-15)</code>
            <code>Sec. 5-15. First official amendatory provision.</code>
          </div>
          <div align="justify">
            <code>(35 ILCS 143/5-15)</code>
            <code>Sec. 15-15. Second official amendatory provision.</code>
          </div>
        </body></html>
        """
    )

    assert [row.official_cite for row in rows] == [
        "35 ILCS 143/5-15",
        "35 ILCS 143/15-15",
    ]
    assert "citation_identity_correction" not in rows[0].structured_data
    assert rows[1].structured_data["citation_identity_correction"] == {
        "official_citation_marker": "35 ILCS 143/5-15",
        "adjacent_section_heading": "15-15",
        "reason": (
            "duplicate_official_citation_marker_with_distinct_"
            "adjacent_section_heading"
        ),
    }


def test_noncolliding_marker_identity_is_not_rewritten_from_heading() -> None:
    rows = _strict_parse(
        """
        <html><body>
          <div align="justify">
            <code>(35 ILCS 143/5-15)</code>
            <code>Sec. 15-15. A lone mismatched heading is not enough to rewrite
            the official citation marker.</code>
          </div>
        </body></html>
        """
    )

    assert [row.official_cite for row in rows] == ["35 ILCS 143/5-15"]
    assert "citation_identity_correction" not in rows[0].structured_data


@pytest.mark.parametrize(
    "second_heading",
    [
        "Sec. 5-15. The repeated marker and heading are substantively duplicate.",
        "Article 15-15. A non-Section label cannot repair identity.",
        "Preface. Sec. 15-15. A non-adjacent heading cannot repair identity.",
    ],
)
def test_duplicate_marker_without_distinct_adjacent_section_heading_fails_closed(
    second_heading: str,
) -> None:
    with pytest.raises(RuntimeError, match="repeats section identity"):
        _strict_parse(
            f"""
            <html><body>
              <div align="justify">
                <code>(35 ILCS 143/5-15)</code>
                <code>Sec. 5-15. First official amendatory provision.</code>
              </div>
              <div align="justify">
                <code>(35 ILCS 143/5-15)</code>
                <code>{second_heading}</code>
              </div>
            </body></html>
            """
        )


def test_official_section_blocks_do_not_segment_inline_same_act_citations() -> None:
    rows = _strict_parse(
        """
        <html><body>
          <div align="justify">
            <code>(35 ILCS 200/15-175)</code>
            <code>Sec. 15-175. General homestead exemption. The official lease
            form refers to the Property Tax Code (35 ILCS 200/15-175). The
            remainder of the operative section must stay in this same row.</code>
          </div>
          <div align="justify">
            <code>(35 ILCS 200/15-176)</code>
            <code>(from Ch. 120, par. 500)</code>
            <code>Sec. 15-176. Alternative general homestead exemption.</code>
          </div>
        </body></html>
        """,
        act_id="596",
        chap_act="35 ILCS 200/",
    )

    assert [row.official_cite for row in rows] == [
        "35 ILCS 200/15-175",
        "35 ILCS 200/15-176",
    ]
    assert rows[0].full_text.count("(35 ILCS 200/15-175)") == 2
    assert "remainder of the operative section" in rows[0].full_text


def test_strict_parser_rejects_owned_citation_without_official_block_boundary() -> None:
    with pytest.raises(
        RuntimeError,
        match="no source-delimited section block",
    ):
        _strict_parse(
            """
            <html><body>
              <p>Quoted form text (35 ILCS 143/5-15). It is not an official
              section heading even if later prose says Sec. 5-15.</p>
            </body></html>
            """
        )


def test_parenthetical_section_identity_is_preserved_from_official_marker() -> None:
    rows = _strict_parse(
        """
        <html><body>
          <div align="justify">
            <code>(35 ILCS 143/1(Art.III))</code>
            <code>(from Ch. 120, par. 1)</code>
            <code>Sec. 1(Art.III). Exact qualified official section.</code>
          </div>
        </body></html>
        """
    )

    assert [row.official_cite for row in rows] == [
        "35 ILCS 143/1(Art.III)"
    ]


def test_pending_ilcs_public_act_requires_exact_dual_provenance() -> None:
    payload = _pending_public_act_payload()
    rows = _parse_pending_public_act(payload)

    assert [row.official_cite for row in rows] == [
        "110 ILCS 193/1",
        "110 ILCS 193/5",
        "110 ILCS 193/10",
        "110 ILCS 193/15",
    ]
    assert len({row.statute_id for row in rows}) == 4
    assert all(row.source_url == _PENDING_PUBLIC_ACT_URL for row in rows)
    assert all(
        row.structured_data["pending_ilcs_compilation"] is True
        and row.structured_data["public_act_number"] == "104-0768"
        and row.structured_data["bill_number"] == "HB4304"
        and row.structured_data["effective_date"] == "2027-01-01"
        and row.structured_data["transport_receipt"]["official_url"]
        == _PENDING_PUBLIC_ACT_URL
        and row.structured_data["ilcs_fulltext_transport_receipt"][
            "official_url"
        ]
        == _PENDING_FULL_URL
        for row in rows
    )


@pytest.mark.parametrize(
    ("original", "drift", "message"),
    [
        (b"Public Act 104-0768", b"Public Act 104-0769", "header identity"),
        (b"HB4304 Enrolled", b"HB4305 Enrolled", "header identity"),
        (
            b"Academic Freedom Act.",
            b"Academic License Act.",
            "short-title identity",
        ),
        (b"Section 10.", b"Section 11.", "section frontier drift"),
        (b"1/1/2027", b"1/2/2027", "effective-date identity"),
    ],
)
def test_pending_ilcs_public_act_identity_drift_fails_closed(
    original: bytes,
    drift: bytes,
    message: str,
) -> None:
    payload = _pending_public_act_payload().replace(original, drift)
    with pytest.raises(RuntimeError, match=message):
        _parse_pending_public_act(payload)


@pytest.mark.parametrize("receipt_label", ["full_text", "public_act"])
def test_pending_ilcs_public_act_receipt_digest_drift_fails_closed(
    receipt_label: str,
) -> None:
    payload = _pending_public_act_payload()
    kwargs = {
        f"{receipt_label}_receipt": {
            "official_url": (
                _PENDING_FULL_URL
                if receipt_label == "full_text"
                else _PENDING_PUBLIC_ACT_URL
            ),
            "content_sha256": "0" * 64,
            "source_transport": "direct",
        }
    }
    label = "ILCS FullText" if receipt_label == "full_text" else "Public Act"
    with pytest.raises(RuntimeError, match=rf"{label} receipt identity drift"):
        _parse_pending_public_act(payload, **kwargs)


def _kidney_public_act_payload() -> bytes:
    return b"""
    <html><body>
      <div id="billtextanchor">
        <p>Public Act 104-0728</p><p>SB3445 Enrolled</p>
        <code>Section 1.</code><code>Short title.</code>
        <code>This Act may be cited as the Kidney Disease Treatment
        Delegation Act.</code>
        <code>Section 2.</code><code>Purpose.</code>
        <code>This Act safeguards individuals seeking kidney treatments.</code>
        <code>Section 5.</code><code>Definitions.</code>
        <code>Definitions for this Act are established.</code>
        <code>Section 10.</code><code>Regulation of delegation.</code>
        <code>Delegation in kidney disease treatment centers is regulated.</code>
        <code>Section 15.</code><code>Rulemaking.</code>
        <code>The Department is authorized to adopt rules.</code>
        <code>Section 20.</code><code>The Nurse Practice Act is amended.</code>
        <code>This amendatory section is not part of the new Act.</code>
        <code>Section 99.</code><code>Effective date.</code>
        <code>This Act takes effect upon becoming law.</code>
      </div>
      <div><span>Effective Date:</span> 7/31/2026</div>
    </body></html>
    """


def _parse_kidney_public_act(payload: bytes):
    scraper = IllinoisScraper("IL", "Illinois")
    chapter = {
        "chapter_id": "24",
        "chapter_number": "225",
        "chapter_name": "PROFESSIONS, OCCUPATIONS, AND BUSINESS OPERATIONS",
        "major_topic": "REGULATION",
        "url": (
            "https://www.ilga.gov/Legislation/ILCS/Acts?"
            "ChapterID=24&ChapterNumber=225"
        ),
    }
    act = {
        "act_id": "4698",
        "chapter_id": "24",
        "act_name": "Kidney Disease Treatment Delegation Act.",
        "chap_act": "225 ILCS 66/",
        "url": (
            "https://www.ilga.gov/Legislation/ILCS/Articles?"
            "ActID=4698&ChapterID=24"
        ),
    }
    full_url = (
        "https://www.ilga.gov/legislation/ILCS/details?"
        "ActID=4698&ChapterID=24&SeqStart=&ChapAct=FullText"
    )
    public_act_url = (
        "https://www.ilga.gov/Legislation/PublicActs/View/104-0728"
    )
    full_payload = b"<html><body>Official empty ILCS shell.</body></html>"
    spec = scraper._pending_ilcs_public_act_spec(chapter=chapter, act=act)
    assert spec is not None
    return scraper._parse_pending_ilcs_public_act_html(
        code_name="Illinois Compiled Statutes",
        chapter=chapter,
        act=act,
        full_url=full_url,
        full_text_payload=full_payload,
        full_text_receipt=_receipt(full_url, full_payload),
        spec=spec,
        public_act_url=public_act_url,
        public_act_payload=payload,
        public_act_receipt=_receipt(public_act_url, payload),
    )


def test_pending_new_act_stops_before_public_act_amendatory_sections() -> None:
    rows = _parse_kidney_public_act(_kidney_public_act_payload())

    assert [row.official_cite for row in rows] == [
        "225 ILCS 66/1",
        "225 ILCS 66/2",
        "225 ILCS 66/5",
        "225 ILCS 66/10",
        "225 ILCS 66/15",
    ]
    assert all("Nurse Practice Act is amended" not in row.full_text for row in rows)
    assert all(
        row.structured_data["public_act_section_frontier"]
        == ["1", "2", "5", "10", "15", "20", "99"]
        for row in rows
    )


def test_pending_new_act_amendatory_boundary_drift_fails_closed() -> None:
    payload = _kidney_public_act_payload().replace(
        b"Section 20.",
        b"Section 21.",
    )
    with pytest.raises(RuntimeError, match="section frontier drift"):
        _parse_kidney_public_act(payload)


def test_pending_new_act_owned_frontier_must_prefix_observed_sections() -> None:
    with pytest.raises(RuntimeError, match="owned section frontier drift"):
        _parse_pending_public_act(
            _pending_public_act_payload(),
            owned_sections_override=("5", "10", "15"),
        )


def test_language_equality_mapping_excludes_session_effective_date() -> None:
    scraper = IllinoisScraper("IL", "Illinois")
    spec = scraper._pending_ilcs_public_act_spec(
        chapter={"chapter_id": "32", "chapter_number": "325"},
        act={
            "act_id": "4695",
            "chapter_id": "32",
            "act_name": (
                "Language Equality Acquisition for Deaf, Hard of Hearing, "
                "or DeafBlind Children Act."
            ),
            "chap_act": "325 ILCS 43/",
        },
    )

    assert spec is not None
    assert spec["public_act_number"] == "104-0658"
    assert spec["bill_number"] == "HB1783"
    assert spec["effective_date"] == "2026-07-30"
    assert spec["section_numbers"] == (
        "1",
        "5",
        "10",
        "15",
        "20",
        "25",
        "30",
        "35",
        "40",
        "90",
    )
    assert spec["public_act_section_numbers"] == (
        *spec["section_numbers"],
        "99",
    )


_RETAINED_PENDING_ACT_CASES = (
    {
        "chapter_id": "32",
        "chapter_number": "325",
        "act_id": "4695",
        "chap_act": "325 ILCS 43/",
        "act_name": (
            "Language Equality Acquisition for Deaf, Hard of Hearing, "
            "or DeafBlind Children Act."
        ),
        "public_act_number": "104-0658",
        "bill_number": "HB1783",
        "effective_date": "2026-07-30",
        "sections": ("1", "5", "10", "15", "20", "25", "30", "35", "40", "90"),
        "frontier": ("1", "5", "10", "15", "20", "25", "30", "35", "40", "90", "99"),
    },
    {
        "chapter_id": "32",
        "chapter_number": "325",
        "act_id": "4696",
        "chap_act": "325 ILCS 66/",
        "act_name": "Children's Online Social Media Safety Act.",
        "public_act_number": "104-0664",
        "bill_number": "HB5511",
        "effective_date": "2028-01-01",
        "sections": ("1", "5", "10", "15", "20", "25", "97"),
        "frontier": ("1", "5", "10", "15", "20", "25", "97", "99"),
    },
    {
        "chapter_id": "35",
        "chapter_number": "410",
        "act_id": "4700",
        "chap_act": "410 ILCS 660/",
        "act_name": "Patient Access to Pharmacy Protection Act.",
        "public_act_number": "104-0758",
        "bill_number": "HB2371",
        "effective_date": "2026-08-07",
        "sections": (
            "1",
            "5",
            "10",
            "15",
            "20",
            "25",
            "30",
            "35",
            "40",
            "45",
            "97",
        ),
        "frontier": (
            "1",
            "5",
            "10",
            "15",
            "20",
            "25",
            "30",
            "35",
            "40",
            "45",
            "97",
            "99",
        ),
    },
    {
        "chapter_id": "35",
        "chapter_number": "410",
        "act_id": "4701",
        "chap_act": "410 ILCS 665/",
        "act_name": "340B Transparency, Reporting, and Accountability Act.",
        "public_act_number": "104-0769",
        "bill_number": "HB4327",
        "effective_date": "2026-08-07",
        "sections": ("1", "5", "10", "15", "20", "95"),
        "frontier": ("1", "5", "10", "15", "20", "95", "900", "905", "999"),
    },
    {
        "chapter_id": "55",
        "chapter_number": "730",
        "act_id": "4699",
        "chap_act": "730 ILCS 230/",
        "act_name": (
            "Equitable Access to Education, Employment, and Training for "
            "Incarcerated Individuals with Disabilities Act."
        ),
        "public_act_number": "104-0757",
        "bill_number": "HB1810",
        "effective_date": "2026-08-07",
        "sections": ("1", "5", "10", "15", "20", "25", "30", "35"),
        "frontier": ("1", "5", "10", "15", "20", "25", "30", "35", "99"),
    },
    {
        "chapter_id": "59",
        "chapter_number": "750",
        "act_id": "4703",
        "chap_act": "750 ILCS 63/",
        "act_name": "Family Justice Centers Act.",
        "public_act_number": "104-0780",
        "bill_number": "HB4949",
        "effective_date": "2027-01-01",
        "sections": ("1", "5", "10", "15"),
        "frontier": ("1", "5", "10", "15"),
    },
    {
        "chapter_id": "67",
        "chapter_number": "815",
        "act_id": "4697",
        "chap_act": "815 ILCS 404/",
        "act_name": "Retail Cash Payment Act.",
        "public_act_number": "104-0665",
        "bill_number": "HB4592",
        "effective_date": "2028-01-01",
        "sections": ("1", "5", "10", "15", "20", "25"),
        "frontier": ("1", "5", "10", "15", "20", "25", "99"),
    },
    {
        "chapter_id": "67",
        "chapter_number": "815",
        "act_id": "4694",
        "chap_act": "815 ILCS 450/",
        "act_name": "Service Appointment Fairness Act.",
        "public_act_number": "104-0656",
        "bill_number": "SB3066",
        "effective_date": "2027-01-01",
        "sections": ("1", "5", "10", "15"),
        "frontier": ("1", "5", "10", "15", "90"),
    },
)


@pytest.mark.parametrize("case", _RETAINED_PENDING_ACT_CASES)
def test_retained_pending_public_act_mappings_are_exact_and_dual_provenance(
    case: dict[str, object],
) -> None:
    scraper = IllinoisScraper("IL", "Illinois")
    chapter_id = str(case["chapter_id"])
    chapter_number = str(case["chapter_number"])
    act_id = str(case["act_id"])
    chap_act = str(case["chap_act"])
    act_name = str(case["act_name"])
    public_act_number = str(case["public_act_number"])
    bill_number = str(case["bill_number"])
    effective_date = str(case["effective_date"])
    sections = tuple(str(value) for value in case["sections"])
    frontier = tuple(str(value) for value in case["frontier"])
    chapter = {
        "chapter_id": chapter_id,
        "chapter_number": chapter_number,
        "chapter_name": "RETAINED OFFICIAL CHAPTER",
        "major_topic": "RETAINED OFFICIAL TOPIC",
        "url": (
            "https://www.ilga.gov/Legislation/ILCS/Acts?"
            f"ChapterID={chapter_id}&ChapterNumber={chapter_number}"
        ),
    }
    act = {
        "act_id": act_id,
        "chapter_id": chapter_id,
        "act_name": act_name,
        "chap_act": chap_act,
        "url": (
            "https://www.ilga.gov/Legislation/ILCS/Articles?"
            f"ActID={act_id}&ChapterID={chapter_id}"
        ),
    }
    full_url = (
        "https://www.ilga.gov/legislation/ILCS/details?"
        f"ActID={act_id}&ChapterID={chapter_id}&SeqStart=&ChapAct=FullText"
    )
    public_act_url = (
        "https://www.ilga.gov/Legislation/PublicActs/View/"
        f"{public_act_number}"
    )
    section_nodes: list[str] = []
    for position, section in enumerate(frontier):
        section_nodes.append(f"<code>Section {section}.</code>")
        if position == 0:
            section_nodes.extend(
                (
                    "<code>Short title.</code>",
                    f"<code>This Act may be cited as the {act_name}</code>",
                )
            )
        else:
            section_nodes.extend(
                (
                    f"<code>Provision {section}.</code>",
                    f"<code>Exact official text for Section {section}.</code>",
                )
            )
    year, month, day = effective_date.split("-")
    public_act_payload = (
        "<html><body><div id=\"billtextanchor\">"
        f"<p>Public Act {public_act_number}</p>"
        f"<p>{bill_number} Enrolled</p>"
        f"{''.join(section_nodes)}"
        "</div>"
        f"<div><span>Effective Date:</span> {int(month)}/{int(day)}/{year}</div>"
        "</body></html>"
    ).encode()
    full_payload = b"<html><body>Exact retained empty ILCS shell.</body></html>"
    spec = scraper._pending_ilcs_public_act_spec(chapter=chapter, act=act)

    assert spec is not None
    assert spec["public_act_number"] == public_act_number
    assert spec["bill_number"] == bill_number
    assert spec["effective_date"] == effective_date
    assert spec["section_numbers"] == sections
    assert spec["public_act_section_numbers"] == frontier
    rows = scraper._parse_pending_ilcs_public_act_html(
        code_name="Illinois Compiled Statutes",
        chapter=chapter,
        act=act,
        full_url=full_url,
        full_text_payload=full_payload,
        full_text_receipt=_receipt(full_url, full_payload),
        spec=spec,
        public_act_url=public_act_url,
        public_act_payload=public_act_payload,
        public_act_receipt=_receipt(public_act_url, public_act_payload),
    )

    citation_prefix = chap_act.rstrip("/")
    assert [row.official_cite for row in rows] == [
        f"{citation_prefix}/{section}" for section in sections
    ]
    assert all(
        row.source_url == public_act_url
        and row.structured_data["transport_receipt"]["official_url"]
        == public_act_url
        and row.structured_data["ilcs_fulltext_transport_receipt"][
            "official_url"
        ]
        == full_url
        and row.structured_data["public_act_section_frontier"]
        == list(frontier)
        for row in rows
    )
    trailing_sections = set(frontier) - set(sections)
    assert all(
        all(
            f"Section {section}." not in row.full_text
            for section in trailing_sections
        )
        for row in rows
    )


_LARGE_PENDING_CHAPTER = {
    "chapter_id": "68",
    "chapter_number": "820",
    "chapter_name": "EMPLOYMENT",
    "major_topic": "BUSINESS AND EMPLOYMENT",
    "url": (
        "https://www.ilga.gov/Legislation/ILCS/Acts?"
        "ChapterID=68&ChapterNumber=820"
    ),
}
_LARGE_PENDING_ACT = {
    "act_id": "4704",
    "chapter_id": "68",
    "act_name": "Transportation Network Driver Labor Relations Act.",
    "chap_act": "820 ILCS 14/",
    "url": (
        "https://www.ilga.gov/Legislation/ILCS/Articles?"
        "ActID=4704&ChapterID=68"
    ),
}
_LARGE_PENDING_FULL_URL = (
    "https://www.ilga.gov/legislation/ILCS/details?"
    "ActID=4704&ChapterID=68&SeqStart=&ChapAct=FullText"
)
_LARGE_PENDING_LANDING_URL = (
    "https://www.ilga.gov/Legislation/PublicActs/View/104-0788"
)
_LARGE_PENDING_DOCUMENT_URL = (
    "https://www.ilga.gov/documents/legislation/PublicActs/104/104-0788.htm"
)


def _large_pending_public_act_payloads() -> tuple[bytes, bytes]:
    scraper = IllinoisScraper("IL", "Illinois")
    spec = scraper._pending_ilcs_public_act_spec(
        chapter=_LARGE_PENDING_CHAPTER,
        act=_LARGE_PENDING_ACT,
    )
    assert spec is not None
    rows = []
    for position, section in enumerate(spec["public_act_section_numbers"]):
        title = (
            "Short title."
            if position == 0
            else f"Exact provision {section}."
        )
        body = (
            "This Act may be cited as the Transportation Network Driver "
            "Labor Relations Act."
            if position == 0
            else f"Official operative Public Act text for Section {section}."
        )
        rows.append(
            "<tr><td><code>&#160;&#160;&#160;&#160;</code>"
            f"<code>Section {section}.</code>"
            f"<code>{title}</code><code>{body}</code></td></tr>"
        )
        if section == "10":
            rows.append(
                "<tr><td><code>Section 8.</code></td></tr>"
                "<tr><td><code>Inline cross-reference continuation only.</code>"
                "</td></tr>"
            )
    document = (
        "<html><body><p>Public Act 104-0788</p><p>HB5090 Enrolled</p>"
        f"<table>{''.join(rows)}</table></body></html>"
    ).encode()
    landing = (
        "<html><body><h1>Public Act 104-0788</h1>"
        '<div id="billtextanchor">The full text is too large for display. '
        '<a href="/documents/legislation/PublicActs/104/104-0788.htm">'
        "click here</a></div><div>Effective Date: 8/7/2026</div>"
        "</body></html>"
    ).encode()
    return landing, document


def _parse_large_pending_public_act(
    *,
    landing: bytes | None = None,
    document: bytes | None = None,
):
    scraper = IllinoisScraper("IL", "Illinois")
    spec = scraper._pending_ilcs_public_act_spec(
        chapter=_LARGE_PENDING_CHAPTER,
        act=_LARGE_PENDING_ACT,
    )
    assert spec is not None
    default_landing, default_document = _large_pending_public_act_payloads()
    landing = default_landing if landing is None else landing
    document = default_document if document is None else document
    full_payload = b"<html><body>Exact retained empty ILCS shell.</body></html>"
    return scraper._parse_pending_ilcs_public_act_html(
        code_name="Illinois Compiled Statutes",
        chapter=_LARGE_PENDING_CHAPTER,
        act=_LARGE_PENDING_ACT,
        full_url=_LARGE_PENDING_FULL_URL,
        full_text_payload=full_payload,
        full_text_receipt=_receipt(_LARGE_PENDING_FULL_URL, full_payload),
        spec=spec,
        public_act_url=_LARGE_PENDING_DOCUMENT_URL,
        public_act_payload=document,
        public_act_receipt=_receipt(_LARGE_PENDING_DOCUMENT_URL, document),
        public_act_landing_url=_LARGE_PENDING_LANDING_URL,
        public_act_landing_payload=landing,
        public_act_landing_receipt=_receipt(
            _LARGE_PENDING_LANDING_URL, landing
        ),
    )


def test_large_pending_public_act_uses_linked_document_and_ignores_inline_markers() -> None:
    rows = _parse_large_pending_public_act()

    assert [row.official_cite for row in rows] == [
        f"820 ILCS 14/{section}"
        for section in (
            "1",
            "2",
            "3",
            "4",
            "4.5",
            "5",
            "6",
            "7",
            "8",
            "9",
            "10",
            "11",
            "12",
            "13",
            "14",
            "15",
            "16",
            "17",
            "18",
        )
    ]
    assert sum(row.official_cite.endswith("/8") for row in rows) == 1
    assert all("Section 900." not in row.full_text for row in rows)
    assert all(
        row.source_url == _LARGE_PENDING_DOCUMENT_URL
        and row.structured_data["transport_receipt"]["official_url"]
        == _LARGE_PENDING_DOCUMENT_URL
        and row.structured_data["public_act_landing_transport_receipt"][
            "official_url"
        ]
        == _LARGE_PENDING_LANDING_URL
        and row.structured_data["ilcs_fulltext_transport_receipt"][
            "official_url"
        ]
        == _LARGE_PENDING_FULL_URL
        for row in rows
    )


@pytest.mark.parametrize(
    ("target", "replacement", "message"),
    [
        (
            b"/documents/legislation/PublicActs/104/104-0788.htm",
            b"/documents/legislation/PublicActs/104/104-0787.htm",
            "landing identity drift",
        ),
        (b"Section 18.", b"Section 19.", "section frontier drift"),
    ],
)
def test_large_pending_public_act_fails_closed_on_source_drift(
    target: bytes,
    replacement: bytes,
    message: str,
) -> None:
    landing, document = _large_pending_public_act_payloads()
    if target in landing:
        landing = landing.replace(target, replacement, 1)
    else:
        document = document.replace(target, replacement, 1)

    with pytest.raises(RuntimeError, match=message):
        _parse_large_pending_public_act(
            landing=landing,
            document=document,
        )
