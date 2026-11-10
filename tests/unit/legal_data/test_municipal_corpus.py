"""Municipal collector gate, locators, and citation form."""

from __future__ import annotations

from ipfs_datasets_py.processors.legal_scrapers.municipal_law_database_scrapers.hub.parquet_writer import (
    format_bluebook,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.municipal_corpus import (
    admit_municipal_row,
    collect_municipal_row,
    municipal_place_status,
)

_ORDINANCE = (
    "Title 1 Administration\n"
    "Chapter 1 General\n"
    "Section 1.01 The city shall keep the peace.\n"
    "(a) This duty is continuous.\n"
    "Section 1.02 The council shall meet monthly.\n"
)


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "authority": "Hamilton",
        "jurisdiction": "US-OH",
        "doc_type": "ordinance",
        "language": "en",
        "source_official": True,
        "source_url": "https://www.cityofhamilton.us/code",
        "text": _ORDINANCE,
        "citation_year": "2020",
        "entry_cid": "hamilton-code",
    }
    row.update(overrides)
    return row


def test_chrome_blog_and_title_shell_produce_no_atom_text() -> None:
    breadcrumb = _row(
        doc_type="ordinance",
        text="Home\nSearch\nContact us\nThis website uses cookies\n",
        title="Search",
    )
    website = _row(
        doc_type="website",
        text="Home\nSearch\nContact us\nThis website uses cookies\n",
        title="Search",
    )
    blog = _row(
        doc_type="blog",
        text="The mayor shall post a weekend blog about the festival.",
        source_url="https://www.cityofhamilton.us/blog",
    )
    newsletter = _row(
        doc_type="newsletter",
        text="Subscribe to the city newsletter for event announcements.",
    )
    shell = _row(
        title="Hamilton municipal organization chart",
        text="Hamilton municipal organization chart",
    )
    directory = _row(
        authority="Ventura",
        source_url="https://www.citydirectory.us/ventura",
        text=_ORDINANCE,
    )
    for row, reason in (
        (breadcrumb, "site_chrome"),
        (website, "site_type"),
        (blog, "site_type"),
        (newsletter, "site_type"),
        (shell, "title_shell"),
        (directory, "unrelated_host"),
    ):
        decision = collect_municipal_row(row)
        assert decision.accept is False
        assert decision.reason == reason
        admission = admit_municipal_row(row)
        assert admission.atoms == ()
        assert admission.reason == reason


def test_two_sections_keep_the_parenthetical_on_the_first() -> None:
    admission = admit_municipal_row(_row())
    assert admission.reason == "law"
    assert len(admission.atoms) == 2
    first, second = admission.atoms
    assert first["provenance"]["section"] == "1.01"
    assert first["provenance"]["subsection"] == "a"
    assert "continuous" in str(first["text"])
    assert second["text"].startswith("Section 1.02")
    assert "(a)" not in str(second["text"])
    assert first["provenance"]["document_role"] == "law"
    assert second["provenance"]["document_role"] == "law"


def test_us_year_is_bluebook_and_a_missing_year_is_an_analog() -> None:
    dated = admit_municipal_row(_row())
    expected = format_bluebook("Hamilton", "Ohio", "1.01", "2020", "Municipal Code")
    assert dated.atoms[0]["citation"] == expected
    assert dated.atoms[0]["bluebook_citation"] == expected
    assert dated.atoms[0]["provenance"]["citation_form"] == "bluebook"
    second = format_bluebook("Hamilton", "Ohio", "1.02", "2020", "Municipal Code")
    assert dated.atoms[1]["citation"] == second
    assert dated.atoms[1]["bluebook_citation"] == second
    assert dated.atoms[1]["provenance"]["section"] == "1.02"
    assert dated.atoms[1]["provenance"]["citation_form"] == "bluebook"
    undated = admit_municipal_row(_row(citation_year=""))
    bare = format_bluebook("Hamilton", "Ohio", "1.01", "", "Municipal Code")
    assert undated.atoms[0]["citation"] == bare
    assert "(" not in str(undated.atoms[0]["citation"])
    assert undated.atoms[0]["bluebook_citation"] is None
    assert undated.atoms[0]["provenance"]["citation_form"] == "analog"
    county = admit_municipal_row(
        _row(
            authority="Ventura County",
            source_url="https://www.venturacounty.us/code",
            jurisdiction="US-CA",
        )
    )
    assert county.atoms[0]["citation"] == format_bluebook(
        "Ventura County", "Cal.", "1.01", "2020", "County Code"
    )
    assert county.atoms[0]["provenance"]["citation_form"] == "bluebook"


def test_a_foreign_ordinance_is_an_analog_and_not_a_us_code() -> None:
    admission = admit_municipal_row(
        _row(
            authority="Lyon",
            jurisdiction="FR",
            source_url="https://www.ville-lyon.fr/code",
            citation_year="2020",
        )
    )
    cite = str(admission.atoms[0]["citation"])
    assert admission.atoms[0]["bluebook_citation"] is None
    assert admission.atoms[0]["provenance"]["citation_form"] == "analog"
    assert cite == "Lyon, France, ordinance 1.01"
    assert admission.atoms[0]["provenance"]["section"] == "1.01"
    assert admission.atoms[0]["provenance"]["subsection"] == "a"
    assert "Ohio" not in cite
    assert "U.S.C." not in cite


def test_instrument_preposition_o_is_not_a_section() -> None:
    admission = admit_municipal_row(
        _row(
            authority="Novo Sarajevo",
            jurisdiction="BA",
            doc_type="decision",
            language="bs",
            source_url="https://www.sarajevo.ba/odluka",
            text=(
                "Odluka o spomenicima od značaja za grad.\n"
                "Section 1 The council shall protect monuments throughout the city.\n"
                "Section 2 The clerk shall record every decision of the council.\n"
            ),
        )
    )
    assert admission.reason == "law"
    assert [atom["provenance"].get("section") for atom in admission.atoms] == ["1", "2"]
    assert all(not str(atom["citation"]).endswith(" o") for atom in admission.atoms)

    bylaw = admit_municipal_row(
        _row(
            authority="City of Hobart",
            jurisdiction="AU",
            doc_type="ordinance",
            language="en",
            source_url="https://www.hobartcity.com.au/bylaw",
            text=(
                "BY-LAW No. o 2020\n"
                "Section 1 The city shall prohibit single-use plastics in municipal facilities.\n"
                "Section 2 The clerk shall enforce this by-law throughout the city.\n"
            ),
        )
    )
    assert [atom["provenance"].get("section") for atom in bylaw.atoms] == ["1", "2"]

    lettered = admit_municipal_row(
        _row(
            text=(
                "Section A The city shall state the purpose of this code for every department.\n"
                "Section B The council shall adopt the fees for the following year.\n"
            ),
        )
    )
    assert [atom["provenance"].get("section") for atom in lettered.atoms] == ["A", "B"]


def test_a_titled_recital_keeps_the_instrument_and_not_a_section() -> None:
    title = "Decreto nº 10.873, de 22 de dezembro de 2025"
    recital = (
        "CONSIDERANDO o disposto no art. 35, § 3o da Lei 7.429 de 30 de setembro de 2025, "
        "em atendimento ao § 14 do art. 166 da Constituição.\n"
    )
    row = _row(
        authority="Montenegro",
        jurisdiction="BR",
        doc_type="regulation",
        language="pt",
        title=title,
        source_url="https://sapl.montenegro.rs.leg.br/norma/6477",
        text=recital,
    )
    alone = admit_municipal_row(row)
    assert alone.reason == "law"
    assert len(alone.atoms) == 1
    atom = alone.atoms[0]
    assert not atom["provenance"].get("section")
    assert atom["provenance"]["heading_instrument"] == title
    assert atom["provenance"]["heading_placement"] == "enabling_instrument"
    assert atom["citation"] == f"Montenegro, Brazil, {title}"

    joined = admit_municipal_row(
        _row(
            **{
                **row,
                "text": (
                    recital
                    + "Art. 1 O município fica autorizado a executar o programa municipal.\n"
                    + "Art. 2 Esta lei entra em vigor na data de sua publicação oficial.\n"
                ),
            }
        )
    )
    placed = [item for item in joined.atoms if item["provenance"].get("heading_placement")]
    numbered = [item for item in joined.atoms if not item["provenance"].get("heading_placement")]
    assert len(placed) == 1
    assert placed[0]["provenance"]["heading_placement"] == "enabling_instrument"
    assert not placed[0]["provenance"].get("section")
    assert [item["provenance"].get("article") for item in numbered] == ["1", "2"]
    assert all(not str(item["citation"]).endswith(" o") for item in joined.atoms)

    page = admit_municipal_row(
        _row(
            authority="Breza",
            jurisdiction="BA",
            title="1010",
            language="bs",
            source_url="https://breza.gov.ba/file/sluzbeni-glasnik/1010",
            text=recital,
        )
    )
    assert page.atoms == ()
    assert page.reason == "not_queryable"


def test_a_place_with_no_atoms_is_a_coverage_gap() -> None:
    assert municipal_place_status(resolved=True, admitted=0, refused=0) == "coverage_gap"
    assert municipal_place_status(resolved=True, admitted=0, refused=2) == "not_a_law"
    assert municipal_place_status(resolved=True, admitted=1, refused=0) == "law"
    assert municipal_place_status(resolved=False, admitted=0, refused=0) == "unknown_place"


def test_a_cookie_page_and_an_error_title_get_no_locator() -> None:
    cookie = _row(
        authority="Emirate of Abu Dhabi",
        jurisdiction="AE",
        title="Request Rejected",
        language="en",
        source_url="https://www.abudhabi.gov.ae/en/cookies-and-policy",
        text=(
            "The requested URL was rejected. Please consult with your administrator. "
            "Your support ID is 4411024356707273632."
        ),
    )
    decision = collect_municipal_row(cookie)
    assert decision.accept is False
    assert decision.reason == "site_page"
    assert admit_municipal_row(cookie).atoms == ()

    denied = _row(
        title="Access Denied",
        source_url="https://www.ville-lyon.fr/code",
        text="The city shall keep this gate closed to the public network.",
    )
    assert collect_municipal_row(denied).reason == "site_page"

    news = _row(
        authority="Abu Dhabi Police",
        jurisdiction="AE",
        title="Abu-Dhabi-Police-Discuss-Regulation-Mechanisms-for-Internet-Cafes",
        source_url="https://www.adpolice.gov.ae/Media-Center/News/2021/06/19/Abu-Dhabi-Police-Discuss-Regulation",
        text="The police discussed regulation mechanisms for internet cafes with partner agencies.",
    )
    assert collect_municipal_row(news).reason == "site_page"
    assert admit_municipal_row(news).atoms == ()


def test_a_title_article_is_kept_when_the_body_has_no_second_heading() -> None:
    admission = admit_municipal_row(
        _row(
            authority="Lyon",
            jurisdiction="FR",
            language="fr",
            title="Article 5 License records",
            source_url="https://www.ville-lyon.fr/code",
            citation_year="",
            text="The city shall keep a record of every license it issues to a resident.",
        )
    )
    assert admission.reason == "law"
    atom = admission.atoms[0]
    assert atom["provenance"].get("section") == "5"
    assert atom["provenance"].get("article") == "5"
    assert "5" in str(atom["citation"])


def test_a_page_id_title_is_still_not_a_section() -> None:
    admission = admit_municipal_row(
        _row(
            authority="Breza",
            jurisdiction="BA",
            title="1010",
            language="bs",
            source_url="https://breza.gov.ba/file/sluzbeni-glasnik/1010",
            text=(
                "CONSIDERANDO o disposto no art. 35 da Lei 7.429, "
                "em atendimento ao art. 166 da Constituição do município."
            ),
        )
    )
    assert admission.atoms == ()
    assert admission.reason == "not_queryable"


def test_a_joined_cjk_article_mark_is_split_and_a_citation_is_not() -> None:
    text = (
        "第 1 條 本自治條例依公民投票法第二十九條規定制定之，市府應執行之。 "
        "第 2 條 臺中市公民投票適用事項如下，市府應公告之。 "
        "第 3 條 市民年滿二十歲者，得為提案人，市府應登記之。"
    )
    admission = admit_municipal_row(
        _row(
            authority="Taichung",
            jurisdiction="TW",
            language="zh-Hant",
            title="臺中市公民投票自治條例",
            source_url="https://law.taichung.gov.tw/LawContent.aspx?id=FL038728",
            citation_year="",
            text=text,
        )
    )
    assert admission.reason == "law"
    numbers = [atom["provenance"].get("article") for atom in admission.atoms]
    assert numbers == ["1", "2", "3"]
    assert all(atom["provenance"].get("section") != "29" for atom in admission.atoms)
    assert "第二十九條" in str(admission.atoms[0]["text"])
    assert all(str(atom["citation"]).endswith(number) for atom, number in zip(admission.atoms, numbers))


def test_a_bare_cjk_enumeration_starts_at_one() -> None:
    text = (
        "一 臺中市政府為加強管理，特訂定本要點，市府應公告之。 "
        "二 凡須借用場地者，得申請使用之，市府應登記之。 "
        "三 使用時間由本所定之，市府應公布之。"
    )
    admission = admit_municipal_row(
        _row(
            authority="Taichung",
            jurisdiction="TW",
            language="zh-Hant",
            title="臺中市場地使用管理要點",
            source_url="https://law.taichung.gov.tw/LawContent.aspx?id=FL000001",
            citation_year="",
            text=text,
        )
    )
    assert [atom["provenance"].get("section") for atom in admission.atoms] == ["1", "2", "3"]


def test_an_annex_number_comes_from_anexa_not_from_the_parent_act() -> None:
    kept = admit_municipal_row(
        _row(
            authority="Roman",
            jurisdiction="RO",
            language="ro",
            title="Anexa",
            source_url="https://primariaroman.ro/wp-content/uploads/ConsLoc/HCL/2012/anexa.pdf",
            citation_year="",
            text=(
                "Anexa nr. 1 la H.C.L. nr. 45 din 25.04.2012\n\n"
                "Consiliul local aprobă tabelul de identificare a autovehiculelor municipiului."
            ),
        )
    )
    assert kept.reason == "law"
    assert kept.atoms[0]["provenance"].get("section") == "Anexa 1"
    assert kept.atoms[0]["provenance"].get("section") != "45"

    table = admit_municipal_row(
        _row(
            authority="Roman",
            jurisdiction="RO",
            language="ro",
            title="Anexa",
            source_url="https://primariaroman.ro/wp-content/uploads/ConsLoc/HCL/2012/bare.pdf",
            citation_year="",
            text="40\n\nDATE DE IDENTIFICARE AUTOVEHICUL\n\nNumărul de înmatriculare al municipiului.",
        )
    )
    assert table.atoms == ()
    assert table.reason == "not_queryable"


def test_a_japanese_ordinance_title_is_the_instrument_when_no_article_is_printed() -> None:
    admission = admit_municipal_row(
        _row(
            authority="Mito",
            jurisdiction="JP",
            language="ja",
            title="水戸市立性病診療所使用料条例廃止条例",
            source_url="https://kre002.legal-square.com/HAS-Shohin/jsp/SVDocumentView",
            citation_year="",
            text="○水戸市立性病診療所使用料条例廃止条例 この条例は、公布の日から施行する。市は旧使用料を徴収しない。",
        )
    )
    assert admission.reason == "law"
    atom = admission.atoms[0]
    assert not atom["provenance"].get("section")
    assert atom["provenance"].get("heading_instrument") == "水戸市立性病診療所使用料条例廃止条例"
    assert atom["provenance"].get("heading_status") == "instrument_only"


def test_a_date_on_the_first_line_is_not_the_section_of_a_numbered_act() -> None:
    admission = admit_municipal_row(
        _row(
            authority="El Chalten",
            jurisdiction="AR",
            language="es",
            title="Resolución N° 360/HCDCh/2023 – Pase a archivo",
            source_url="https://www.elchalten.gob.ar/hcd/360",
            citation_year="",
            text=(
                "20 de diciembre del 2023\n"
                "El Honorable Concejo Deliberante resuelve el pase a archivo del expediente.\n"
                "Descargar PDF\n"
            ),
        )
    )
    assert admission.reason == "law"
    assert len(admission.atoms) == 1
    atom = admission.atoms[0]
    assert atom["provenance"].get("section") != "20"
    assert "360" in str(atom.get("citation"))
    assert atom["provenance"].get("heading_status") == "instrument_only"


def test_a_list_of_ordinances_without_a_number_stays_unlocated() -> None:
    admission = admit_municipal_row(
        _row(
            authority="Tres de Febrero",
            jurisdiction="AR",
            language="es",
            title="Decretos y Ordenanzas – Municipalidad Tres de Febrero",
            source_url="https://www.tresdefebrero.gov.ar/decretos",
            citation_year="",
            text="3 septiembre, 2026 Leer más sobre decretos y ordenanzas del municipio.",
        )
    )
    assert admission.atoms == ()


def test_a_dutch_compound_verordening_is_cited_by_its_title() -> None:
    admission = admit_municipal_row(
        _row(
            authority="Deventer",
            jurisdiction="NL",
            language="nl",
            title="Intrekking Brandbeveiligingsverordening 2012, gemeente Deventer",
            source_url="https://zoek.officielebekendmakingen.nl/gmb-2020-6069.html",
            citation_year="",
            text=(
                "6 december 2019\n"
                "De raad van de gemeente Deventer besluit de Brandbeveiligingsverordening 2012 in te trekken."
            ),
        )
    )
    assert admission.reason == "law"
    atom = admission.atoms[0]
    assert atom["provenance"].get("section") != "6"
    assert "Brandbeveiligingsverordening" in str(atom.get("citation"))


def test_a_homepage_without_an_instrument_name_is_not_cited() -> None:
    admission = admit_municipal_row(
        _row(
            authority="Skole",
            jurisdiction="UA",
            language="uk",
            title="Сколівська міська рада - вітаємо на офіційному вебсайті",
            source_url="https://skole-rada.gov.ua/",
            citation_year="",
            text=(
                "Від проєктних планів до реальних змін: у Сколе триває модернізація системи водопостачання "
                "у межах міжнародного проєкту для міста."
            ),
        )
    )
    assert admission.atoms == ()


def test_municipal_codes_is_not_a_collector_host() -> None:
    decision = collect_municipal_row(
        _row(source_url="https://bakersfield.municipal.codes/")
    )
    assert decision.accept is False
    assert decision.reason == "no_collector"
