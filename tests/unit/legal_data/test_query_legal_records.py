"""Flag-first worldwide query. Unpublished jurisdictions do not fall back to US Code."""

from __future__ import annotations

import inspect

import pytest

from ipfs_datasets_py.processors.legal_data.query_legal_records import (
    LegalQueryDisabled,
    LegalQueryInputError,
    _QUERY_ID_FIELDS,
    query_legal_records,
)

_WORLD_SHA = "53a38d3ea51402640141bf1f1126d669c1277e46"


def _opened(calls: list[str]):
    def opener(repo: str) -> tuple[dict[str, object], ...]:
        calls.append(repo)
        return ({"entry_cid": "cid-1", "text": "body", "provenance": {}},)

    return opener


def test_flag_off_raises_before_resolution(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "0")
    calls: list[str] = []
    for jurisdiction in ("AQ", "ZZ", "US", "FR"):
        with pytest.raises(LegalQueryDisabled):
            query_legal_records(
                jurisdiction=jurisdiction,
                text_query="",
                corpus_opener=_opened(calls),
            )
    assert calls == []


def test_unset_flag_resolves_and_does_not_fall_back_to_us_law(monkeypatch) -> None:
    monkeypatch.delenv("LEGAL_QUERY_NORMALIZED", raising=False)
    calls: list[str] = []
    result = query_legal_records(
        jurisdiction="AQ",
        text_query="ice",
        corpus_opener=_opened(calls),
    )
    assert result.coverage == "not_published"
    assert result.records == ()
    assert result.source_repo is None
    assert calls == []


def test_flag_on_unknown_codes_are_empty(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    calls: list[str] = []
    for jurisdiction in ("AQ", "ZZ"):
        result = query_legal_records(
            jurisdiction=jurisdiction,
            text_query="",
            citation="",
            corpus_opener=_opened(calls),
        )
        assert result.schema_version == "legal-query/v1"
        assert result.record_schema == "legal-record/v1"
        assert result.jurisdiction == jurisdiction
        assert result.coverage == "not_published"
        assert result.records == ()
        assert result.source_repo is None
        assert not hasattr(result, "error")
    assert calls == []


def test_us_statute_without_admin_level_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    calls: list[str] = []
    with pytest.raises(LegalQueryInputError) as raised:
        query_legal_records(
            jurisdiction="US",
            text_query="title 18",
            instrument_type="statute",
            corpus_opener=_opened(calls),
        )
    assert raised.value.code == "admin_level_required"
    assert calls == []


def test_uk_and_cw_name_the_catalog_slug(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    uk = query_legal_records(jurisdiction="uk", text_query="theft")
    gb = query_legal_records(jurisdiction="GB", text_query="theft")
    assert uk.jurisdiction == gb.jurisdiction == "GB"
    assert uk.source_repo == gb.source_repo == "justicedao/ipfs_uk_laws_ir"
    assert uk.coverage == "snapshot"
    cw = query_legal_records(jurisdiction="CW", text_query="tax")
    assert cw.jurisdiction == "CW"
    assert cw.source_repo == "justicedao/ipfs_curacao_laws_ir"


def test_stale_france_does_not_open_world_until_the_pin_is_readable(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.query_legal_records.pin_readable",
        lambda _repo: False,
    )
    calls: list[str] = []
    closed = query_legal_records(
        jurisdiction="FR",
        text_query="code civil",
        gap_status="stale",
        corpus_opener=_opened(calls),
    )
    assert closed.coverage == "not_published"
    assert closed.records == ()
    assert closed.source_repo is None
    assert calls == []

    stale = query_legal_records(
        jurisdiction="france",
        text_query="code civil",
        gap_status="stale",
        allow_stale=True,
        corpus_opener=_opened(calls),
    )
    assert stale.jurisdiction == "FR"
    assert stale.coverage == "stale_pin"
    assert stale.source_repo == "justicedao/ipfs_france_laws_ir"
    assert calls == ["justicedao/ipfs_france_laws_ir"]


def test_readable_world_pin_returns_partial_with_revision(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")

    def readable(repo: str) -> bool:
        return repo.split("/", 1)[-1] == "world_national_law"

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.query_legal_records.pin_readable",
        readable,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.query_legal_records.pin_revision",
        lambda repo: _WORLD_SHA if repo.endswith("world_national_law") else None,
    )
    calls: list[str] = []
    result = query_legal_records(
        jurisdiction="FR",
        text_query="code civil",
        gap_status="stale",
        corpus_opener=_opened(calls),
    )
    assert result.coverage == "partial"
    assert result.source_repo == "justicedao/world_national_law"
    assert result.source_revision == _WORLD_SHA
    assert calls == ["justicedao/world_national_law"]
    assert result.records[0]["provenance"]["fallback_from"] == "stale"
    current = query_legal_records(
        jurisdiction="FR",
        text_query="code civil",
        gap_status="current",
        corpus_opener=_opened(calls),
    )
    assert current.coverage == "current"
    assert current.source_repo == "justicedao/ipfs_france_laws_ir"
    assert calls[-1] == "justicedao/ipfs_france_laws_ir"


def test_admin_level_repo_is_not_replaced_by_instrument(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    federal = query_legal_records(
        jurisdiction="US",
        text_query="title 18",
        admin_level="us-federal",
        instrument_type="register",
    )
    assert federal.source_repo == "justicedao/ipfs_uscode"
    assert federal.coverage == "current"
    state = query_legal_records(
        jurisdiction="US",
        text_query="penal",
        admin_level="us-state",
        instrument_type="case",
    )
    assert state.source_repo == "justicedao/ipfs_state_laws"
    assert state.coverage == "current"
    patent_state = query_legal_records(
        jurisdiction="US",
        text_query="claim",
        admin_level="us-federal",
        instrument_type="patent",
    )
    assert patent_state.source_repo == "justicedao/ipfs_uscode"


def test_instrument_without_admin_level_selects_its_repo(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    register = query_legal_records(
        jurisdiction="US",
        text_query="notice",
        instrument_type="register",
    )
    assert register.source_repo == "justicedao/federal-register-full-graphrag-v20260810"
    assert register.coverage == "current"
    case = query_legal_records(
        jurisdiction="US",
        text_query="brown",
        instrument_type="case",
    )
    assert case.source_repo == "justicedao/ipfs_caselaw_access_project"
    assert case.coverage == "snapshot"
    patent = query_legal_records(
        jurisdiction="US",
        text_query="claim",
        instrument_type="patent",
    )
    assert patent.source_repo == "justicedao/patent-legal-ir-graphrag"
    assert patent.coverage == "current"


def test_query_id_is_stable_for_the_same_request(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    first = query_legal_records(jurisdiction="FR", text_query="code", citation="art 1")
    second = query_legal_records(jurisdiction="FR", text_query="code", citation="art 1")
    changed = query_legal_records(jurisdiction="FR", text_query="code", citation="art 2")
    assert first.query_id == second.query_id
    assert len(first.query_id) == 64
    assert changed.query_id != first.query_id


def test_empty_known_query_is_an_input_error(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "0")
    with pytest.raises(LegalQueryDisabled):
        query_legal_records(jurisdiction="FR", text_query="", citation="")
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    with pytest.raises(LegalQueryInputError) as raised:
        query_legal_records(jurisdiction="FR", text_query="  ", citation="")
    assert raised.value.code == "query_required"


def test_excluded_national_queries_are_not_published(monkeypatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.catalog import (
        EXCLUDED_SLUGS,
    )

    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    assert "ghana" in EXCLUDED_SLUGS
    calls: list[str] = []
    for jurisdiction in ("GH", "ghana", "BE", "PT", "LT"):
        result = query_legal_records(
            jurisdiction=jurisdiction,
            text_query="code",
            gap_status="stale",
            allow_stale=True,
            corpus_opener=_opened(calls),
        )
        assert result.coverage == "not_published"
        assert result.source_repo is None
        assert result.records == ()
        assert result.jurisdiction in {"GH", "BE", "PT", "LT"}
    assert calls == []
    municipal = query_legal_records(jurisdiction="belgium_municipal", text_query="bylaw")
    assert municipal.jurisdiction == "BE"
    assert municipal.source_repo == "justicedao/ipfs_belgium_municipal_laws_ir"


def test_subdivision_code_is_not_the_parent_statute(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    result = query_legal_records(jurisdiction="US-CA", text_query="civil")
    assert result.jurisdiction == "US-CA"
    assert result.coverage == "not_published"
    assert result.source_repo is None
    assert result.records == ()


def test_missing_municipal_slug_does_not_invent_a_repo(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    closed = query_legal_records(
        jurisdiction="CL",
        text_query="ordenanza",
        admin_level="municipality",
    )
    assert closed.coverage == "not_published"
    assert closed.source_repo is None
    named = query_legal_records(jurisdiction="chile_municipal", text_query="ordenanza")
    assert named.coverage == "not_published"
    assert named.source_repo is None
    hungary = query_legal_records(jurisdiction="hungary_municipal", text_query="rendelet")
    assert hungary.source_repo is None
    spain = query_legal_records(jurisdiction="spain_municipal", text_query="ordenanza")
    assert spain.jurisdiction == "ES"
    assert spain.source_repo == "justicedao/ipfs_spain_municipal_laws_ir"


_MATCH = "a" * 40
_OTHER = "b" * 40


def test_alias_sha_selects_one_spelling(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    alias_only = query_legal_records(
        jurisdiction="PG",
        text_query="land",
        alias_revisions={
            "papua_new_guinea": (_MATCH, _MATCH),
            "papuanewguinea": (_OTHER, _MATCH),
        },
    )
    assert alias_only.jurisdiction == "PG"
    assert alias_only.source_repo == "justicedao/ipfs_papua_new_guinea_laws_ir"
    neither = query_legal_records(
        jurisdiction="papua_new_guinea",
        text_query="land",
        alias_revisions={
            "papua_new_guinea": (_OTHER, _MATCH),
            "papuanewguinea": (_MATCH, _OTHER),
        },
    )
    assert neither.jurisdiction == "PG"
    assert neither.source_repo == "justicedao/ipfs_papuanewguinea_laws_ir"
    both = query_legal_records(
        jurisdiction="papua_new_guinea",
        text_query="land",
        alias_revisions={
            "papua_new_guinea": (_MATCH, _MATCH),
            "papuanewguinea": (_MATCH, _MATCH),
        },
    )
    assert both.source_repo == "justicedao/ipfs_papuanewguinea_laws_ir"
    unset = query_legal_records(jurisdiction="PG", text_query="land")
    assert unset.source_repo == "justicedao/ipfs_papuanewguinea_laws_ir"


def test_client_location_does_not_change_the_result(monkeypatch) -> None:
    banned = {"location", "ip", "locale", "timezone", "accept_language", "client_country"}
    assert banned.isdisjoint(inspect.signature(query_legal_records).parameters)
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    monkeypatch.setenv("TZ", "Pacific/Auckland")
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")
    monkeypatch.setenv("LC_ALL", "fr_FR.UTF-8")
    monkeypatch.setenv("CLIENT_COUNTRY", "NZ")
    france = query_legal_records(jurisdiction="FR", text_query="code")
    antarctica = query_legal_records(jurisdiction="AQ", text_query="")
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    monkeypatch.setenv("LANG", "ja_JP.UTF-8")
    monkeypatch.setenv("LC_ALL", "ja_JP.UTF-8")
    monkeypatch.setenv("CLIENT_COUNTRY", "US")
    france_again = query_legal_records(jurisdiction="FR", text_query="code")
    antarctica_again = query_legal_records(jurisdiction="AQ", text_query="")
    assert france.query_id == france_again.query_id
    assert france.coverage == france_again.coverage == "snapshot"
    assert france.source_repo == france_again.source_repo == "justicedao/ipfs_france_laws_ir"
    assert antarctica.query_id == antarctica_again.query_id
    assert antarctica.coverage == antarctica_again.coverage == "not_published"
    assert antarctica.source_repo is None and antarctica_again.source_repo is None
    subdivision = query_legal_records(jurisdiction="US-CA", text_query="civil")
    assert subdivision.coverage == "not_published"
    assert subdivision.source_repo is None
    excluded = query_legal_records(
        jurisdiction="GH",
        text_query="code",
        gap_status="stale",
        allow_stale=True,
    )
    assert excluded.coverage == "not_published"
    assert excluded.source_repo is None
    vectors = query_legal_records(
        jurisdiction="FR",
        text_query="code",
        gap_status="stub_vectors",
    )
    assert vectors.coverage == "stub_vectors"
    assert vectors.source_repo == "justicedao/ipfs_france_laws_ir"
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "0")
    with pytest.raises(LegalQueryDisabled):
        query_legal_records(jurisdiction="ZZ", text_query="")


_ARTICLES = (
    "Article 1 Alpha provision applies.\n"
    "Article 2 Beta provision applies."
)


def _article_opener(calls: list[str]):
    def opener(repo: str) -> tuple[dict[str, object], ...]:
        calls.append(repo)
        return (
            {
                "entry_cid": "parent",
                "text": _ARTICLES,
                "citation": "Code civil",
                "title": "Code civil",
                "jurisdiction": "FR",
                "language": "fr",
                "provenance": {},
            },
        )

    return opener


def test_representation_does_not_change_the_query_id(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    calls: list[str] = []
    opener = _article_opener(calls)
    record = query_legal_records(
        jurisdiction="FR",
        text_query="code",
        corpus_opener=opener,
        representation="record",
    )
    jsonld = query_legal_records(
        jurisdiction="FR",
        text_query="code",
        corpus_opener=opener,
        representation="jsonld",
    )
    text = query_legal_records(
        jurisdiction="FR",
        text_query="code",
        corpus_opener=opener,
        representation="text",
    )
    assert record.query_id == jsonld.query_id == text.query_id
    assert "representation" not in _QUERY_ID_FIELDS
    assert len(record.records) == 1
    assert record.records[0]["entry_cid"] == "parent"
    assert record.records[0]["text"] == _ARTICLES
    assert len(jsonld.records) == 2
    assert len(text.records) == 2
    assert all(row["@type"] == "Legislation" for row in jsonld.records)
    assert all(row["@context"] == "https://schema.org" for row in jsonld.records)
    assert "dateModified" not in jsonld.records[0]
    assert text.records[0]["text"].startswith("Article 1")
    assert text.records[1]["text"].startswith("Article 2")
    assert text.records[0]["entry_cid"] != text.records[1]["entry_cid"]
    assert text.records[0]["entry_cid"] != "parent"
    assert text.records[0]["locator"]["statute"] == "Code civil"
    assert text.records[0]["locator"]["section"] == "1"
    assert text.records[0]["atomic"] is True
    assert calls


def test_invalid_representation_is_rejected_before_the_opener(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "0")
    calls: list[str] = []
    with pytest.raises(LegalQueryDisabled):
        query_legal_records(
            jurisdiction="FR",
            text_query="code",
            representation="html",
            corpus_opener=_opened(calls),
        )
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    with pytest.raises(LegalQueryInputError) as raised:
        query_legal_records(
            jurisdiction="FR",
            text_query="code",
            representation="html",
            corpus_opener=_opened(calls),
        )
    assert raised.value.code == "representation"
    assert calls == []


def _structured_opener(calls: list[str]):
    def opener(repo: str) -> tuple[dict[str, object], ...]:
        calls.append(repo)
        return (
            {
                "entry_cid": "parent",
                "text": _ARTICLES,
                "citation": "Code civil",
                "title": "Code civil",
                "jurisdiction": "FR",
                "language": "fr",
                "provenance": {},
            },
            {
                "entry_cid": "ordinance",
                "text": "The city may seek an injunction.",
                "title": "Title 15 Chapter 2 Sec. 15-40. - Injunction.",
                "citation": "Sec. 15-40",
                "jurisdiction": "US",
                "language": "en",
                "provenance": {
                    "title": "15",
                    "chapter": "2",
                    "section": "15-40",
                    "subsection": "a, b",
                },
            },
        )

    return opener


def _property(document: dict[str, object], property_id: str) -> str | None:
    raw = document.get("additionalProperty")
    if not isinstance(raw, list):
        return None
    for item in raw:
        if isinstance(item, dict) and item.get("propertyID") == property_id:
            value = item.get("value")
            return value if isinstance(value, str) else None
    return None


def test_locator_filters_are_ignored_until_the_flag_is_on(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "0")
    calls: list[str] = []
    with pytest.raises(LegalQueryDisabled):
        query_legal_records(
            jurisdiction="FR",
            text_query="code",
            section="1",
            corpus_opener=_structured_opener(calls),
        )
    assert calls == []


def test_section_query_returns_jsonld_for_that_section_only(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    calls: list[str] = []
    plain = query_legal_records(
        jurisdiction="FR",
        text_query="code",
        corpus_opener=_structured_opener(calls),
    )
    selected = query_legal_records(
        jurisdiction="FR",
        text_query="code",
        section="1",
        representation="jsonld",
        corpus_opener=_structured_opener(calls),
    )
    assert selected.query_id != plain.query_id
    assert len(selected.records) == 1
    document = selected.records[0]
    assert document["@type"] == "Legislation"
    assert document["@context"] == "https://schema.org"
    assert document["encodingFormat"] == "text/plain"
    assert str(document["text"]).startswith("Article 1")
    assert _property(document, "section") == "1"
    assert _property(document, "subsection") is None
    assert "dateModified" not in document


def test_title_chapter_and_subsection_select_the_ordinance(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    calls: list[str] = []
    opener = _structured_opener(calls)
    matched = query_legal_records(
        jurisdiction="FR",
        text_query="code",
        title="15",
        chapter="2",
        section="15-40",
        subsection="a",
        representation="jsonld",
        corpus_opener=opener,
    )
    assert len(matched.records) == 1
    document = matched.records[0]
    assert _property(document, "title") == "15"
    assert _property(document, "chapter") == "2"
    assert _property(document, "section") == "15-40"
    assert _property(document, "subsection") == "a, b"
    assert document["text"] == "The city may seek an injunction."
    missed = query_legal_records(
        jurisdiction="FR",
        text_query="code",
        title="Code civil",
        corpus_opener=opener,
    )
    assert missed.records == ()
    other = query_legal_records(
        jurisdiction="FR",
        text_query="code",
        subsection="c",
        corpus_opener=opener,
    )
    assert other.records == ()


def test_omitted_locators_keep_the_query_id(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    bare = query_legal_records(jurisdiction="FR", text_query="code", citation="art 1")
    blank = query_legal_records(
        jurisdiction="FR",
        text_query="code",
        citation="art 1",
        title="  ",
        chapter="",
        section=None,
        subsection="",
    )
    assert bare.query_id == blank.query_id
    numbered = query_legal_records(
        jurisdiction="FR",
        text_query="code",
        citation="art 1",
        section="1",
    )
    assert numbered.query_id != bare.query_id


def test_a_non_string_locator_is_rejected_after_the_flag(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "0")
    calls: list[str] = []
    with pytest.raises(LegalQueryDisabled):
        query_legal_records(
            jurisdiction="FR",
            text_query="code",
            section=1,  # type: ignore[arg-type]
            corpus_opener=_opened(calls),
        )
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    with pytest.raises(LegalQueryInputError) as raised:
        query_legal_records(
            jurisdiction="FR",
            text_query="code",
            section=1,  # type: ignore[arg-type]
            corpus_opener=_opened(calls),
        )
    assert raised.value.code == "section"
    assert calls == []


_MUNICIPAL_PIN = "c" * 40


def _open_american_municipal(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")

    def readable(repo: str) -> bool:
        return repo == "american_municipal_law_norm"

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.query_legal_records.pin_readable",
        readable,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.query_legal_records.pin_revision",
        lambda repo: _MUNICIPAL_PIN if repo == "american_municipal_law_norm" else None,
    )


def _municipal_rows() -> tuple[dict[str, object], ...]:
    return (
        {
            "authority": "City of Hamilton",
            "jurisdiction": "US-OH",
            "effective_date": "1999-05-01",
            "text": "Hamilton Ohio ordinance.",
            "citation": "Hamilton, Ohio",
            "entry_cid": "oh",
            "language": "en",
            "provenance": {"title": "1", "chapter": "2", "section": "1.02.010", "subsection": "a"},
        },
        {
            "authority": "City of Hamilton",
            "jurisdiction": "US-AL",
            "effective_date": "2010-01-01",
            "text": "Hamilton Alabama ordinance.",
            "citation": "Hamilton, Ala.",
            "entry_cid": "al",
            "language": "en",
            "provenance": {"section": "1"},
        },
        {
            "authority": "Ventura",
            "jurisdiction": "US-CA",
            "effective_date": "2001-06-15",
            "text": "Ventura city ordinance.",
            "citation": "Ventura, Cal.",
            "entry_cid": "ven",
            "language": "en",
            "provenance": {
                "title": "6",
                "chapter": "6.04",
                "section": "6.04.010",
                "subsection": "a",
            },
        },
        {
            "authority": "Ventura County",
            "jurisdiction": "US-CA",
            "effective_date": "2004-03-01",
            "text": "Ventura County ordinance.",
            "citation": "Ventura County, Cal.",
            "entry_cid": "county",
            "language": "en",
            "provenance": {"section": "100"},
        },
        {
            "authority": "City of Ventura",
            "jurisdiction": "US-IA",
            "effective_date": "1990-01-01",
            "text": "Ventura Iowa ordinance.",
            "citation": "City of Ventura, Iowa",
            "entry_cid": "ia",
            "language": "en",
            "provenance": {"section": "1"},
        },
    )


def _municipal_opener(calls: list[str]):
    def opener(repo: str) -> tuple[dict[str, object], ...]:
        calls.append(repo)
        return _municipal_rows()

    return opener


def test_place_name_selects_ventura_city_not_the_county(monkeypatch) -> None:
    _open_american_municipal(monkeypatch)
    calls: list[str] = []
    result = query_legal_records(
        jurisdiction="US",
        place="Ventura",
        corpus_opener=_municipal_opener(calls),
    )
    assert calls == ["justicedao/american_municipal_law_norm"]
    assert result.coverage == "current"
    assert result.jurisdiction == "US"
    assert result.place_name == "Ventura"
    assert result.place_state == "CA"
    assert result.place_latitude == "34.26778"
    assert result.place_longitude == "-119.254206"
    assert result.place_ambiguous is False
    assert result.territory_name is None
    assert [row["entry_cid"] for row in result.records] == ["ven"]
    assert result.county_name == "Ventura County"
    assert result.county_state == "CA"
    assert [row["entry_cid"] for row in result.county_records] == ["county"]
    shown = query_legal_records(
        jurisdiction="US",
        place="Ventura",
        representation="jsonld",
        corpus_opener=_municipal_opener(calls),
    )
    assert shown.records[0]["@type"] == "Legislation"
    assert shown.county_records[0]["@type"] == "Legislation"
    assert _property(shown.records[0], "authority") == "Ventura"
    assert _property(shown.county_records[0], "authority") == "Ventura County"
    county = query_legal_records(
        jurisdiction="US",
        place="Ventura County",
        corpus_opener=_municipal_opener(calls),
    )
    assert county.place_name == "Ventura County"
    assert county.place_state is None
    assert county.place_latitude is None
    assert [row["entry_cid"] for row in county.records] == ["county"]
    iowa = query_legal_records(
        jurisdiction="US",
        place="City of Ventura",
        corpus_opener=_municipal_opener(calls),
    )
    assert iowa.place_state == "IA"
    assert [row["entry_cid"] for row in iowa.records] == ["ia"]
    assert iowa.county_name == "Cerro Gordo County"
    assert iowa.county_state == "IA"
    assert iowa.county_records == ()


def test_ambiguous_place_needs_a_state_or_a_coordinate(monkeypatch) -> None:
    _open_american_municipal(monkeypatch)
    calls: list[str] = []
    with pytest.raises(LegalQueryInputError) as raised:
        query_legal_records(
            jurisdiction="US",
            place="City of Hamilton",
            corpus_opener=_municipal_opener(calls),
        )
    assert raised.value.code == "ambiguous_place"
    assert calls == []
    ohio = query_legal_records(
        jurisdiction="US",
        place="Hamilton, Ohio",
        corpus_opener=_municipal_opener(calls),
    )
    assert ohio.place_name == "City of Hamilton"
    assert ohio.place_state == "OH"
    assert [row["entry_cid"] for row in ohio.records] == ["oh"]
    pointed = query_legal_records(
        jurisdiction="US",
        place="City of Hamilton",
        latitude="39.395833333333",
        longitude="-84.565",
        corpus_opener=_municipal_opener(calls),
    )
    assert pointed.place_state == "OH"
    assert [row["entry_cid"] for row in pointed.records] == ["oh"]


def test_coordinates_select_the_nearest_city_and_do_not_switch_names(monkeypatch) -> None:
    _open_american_municipal(monkeypatch)
    calls: list[str] = []
    nearest = query_legal_records(
        jurisdiction="US",
        latitude="39.40",
        longitude="-84.565",
        corpus_opener=_municipal_opener(calls),
    )
    assert nearest.place_name == "City of Hamilton"
    assert nearest.place_state == "OH"
    assert [row["entry_cid"] for row in nearest.records] == ["oh"]
    ocean = query_legal_records(
        jurisdiction="US",
        latitude="0",
        longitude="0",
        corpus_opener=_municipal_opener(calls),
    )
    assert ocean.records == ()
    assert ocean.place_name is None
    assert ocean.place_ambiguous is False
    assert ocean.county_name is None
    assert ocean.county_records == ()
    assert ocean.territory_name is None
    assert ocean.coverage == "current"
    mismatch = query_legal_records(
        jurisdiction="US",
        place="Ventura",
        latitude="39.395833333333",
        longitude="-84.565",
        corpus_opener=_municipal_opener(calls),
    )
    assert mismatch.records == ()
    assert mismatch.place_name is None
    assert calls == ["justicedao/american_municipal_law_norm"]


def test_section_and_date_select_one_ordinance(monkeypatch) -> None:
    _open_american_municipal(monkeypatch)
    calls: list[str] = []
    selected = query_legal_records(
        jurisdiction="US",
        place="Ventura",
        title="6",
        chapter="6.04",
        section="6.04.010",
        subsection="a",
        as_of="2001-06-15",
        representation="jsonld",
        corpus_opener=_municipal_opener(calls),
    )
    assert len(selected.records) == 1
    document = selected.records[0]
    assert document["@type"] == "Legislation"
    assert document["legislationDate"] == "2001-06-15"
    assert document["legislationJurisdiction"] == "US-CA"
    assert _property(document, "section") == "6.04.010"
    assert "dateModified" not in document
    later = query_legal_records(
        jurisdiction="US",
        place="Hamilton, Ohio",
        as_of="1990-01-01",
        corpus_opener=_municipal_opener(calls),
    )
    assert later.records == ()
    earlier = query_legal_records(
        jurisdiction="US",
        place="Hamilton, OH",
        as_of="1999-05-01",
        corpus_opener=_municipal_opener(calls),
    )
    assert [row["entry_cid"] for row in earlier.records] == ["oh"]


def test_locator_or_date_can_be_the_whole_query(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    calls: list[str] = []
    selected = query_legal_records(
        jurisdiction="FR",
        section="1",
        representation="jsonld",
        corpus_opener=_structured_opener(calls),
    )
    assert len(selected.records) == 1
    assert _property(selected.records[0], "section") == "1"
    dated = query_legal_records(
        jurisdiction="FR",
        as_of="2020-01-01",
        corpus_opener=_structured_opener(calls),
    )
    assert dated.records == ()
    assert calls == ["justicedao/ipfs_france_laws_ir", "justicedao/ipfs_france_laws_ir"]


def test_place_arguments_do_not_change_an_omitted_query_id(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    bare = query_legal_records(jurisdiction="FR", text_query="code", citation="art 1")
    blank = query_legal_records(
        jurisdiction="FR",
        text_query="code",
        citation="art 1",
        place="  ",
        latitude=None,
        longitude=None,
        as_of="",
    )
    assert bare.query_id == blank.query_id
    dated = query_legal_records(
        jurisdiction="FR",
        text_query="code",
        citation="art 1",
        as_of="2020-01-01",
    )
    assert dated.query_id != bare.query_id


def test_coordinates_do_not_open_another_country_or_a_state_route(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    calls: list[str] = []
    with pytest.raises(LegalQueryInputError) as raised:
        query_legal_records(
            jurisdiction="FR",
            text_query="code",
            latitude="48.8",
            longitude="2.3",
            corpus_opener=_opened(calls),
        )
    assert raised.value.code == "coordinates"
    assert calls == []
    subdivision = query_legal_records(
        jurisdiction="US-CA",
        place="Ventura",
        latitude="34.26778",
        longitude="-119.254206",
        corpus_opener=_opened(calls),
    )
    assert subdivision.coverage == "not_published"
    assert subdivision.records == ()
    assert subdivision.county_name is None
    assert subdivision.county_records == ()
    assert subdivision.source_repo is None
    assert calls == []
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "0")
    with pytest.raises(LegalQueryDisabled):
        query_legal_records(
            jurisdiction="US",
            place="Ventura",
            latitude="34.26778",
            longitude="-119.254206",
            corpus_opener=_opened(calls),
        )
    assert calls == []


def test_bad_place_date_and_coordinates_are_rejected(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "0")
    with pytest.raises(LegalQueryDisabled):
        query_legal_records(jurisdiction="US", place=1, as_of="2020-01-01")  # type: ignore[arg-type]
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    with pytest.raises(LegalQueryInputError) as place_error:
        query_legal_records(jurisdiction="US", place=1)  # type: ignore[arg-type]
    assert place_error.value.code == "place"
    with pytest.raises(LegalQueryInputError) as date_error:
        query_legal_records(jurisdiction="FR", text_query="code", as_of="2020-1-1")
    assert date_error.value.code == "as_of"
    with pytest.raises(LegalQueryInputError) as pair_error:
        query_legal_records(jurisdiction="US", latitude="34.2", longitude=None)
    assert pair_error.value.code == "coordinates"
    with pytest.raises(LegalQueryInputError) as latitude_error:
        query_legal_records(
            jurisdiction="US",
            latitude=34.2,  # type: ignore[arg-type]
            longitude="-119.2",
        )
    assert latitude_error.value.code == "latitude"


def test_place_and_date_reject_a_row_before_text_expansion(monkeypatch) -> None:
    _open_american_municipal(monkeypatch)
    expanded: list[str] = []

    def expand(row: dict[str, object]) -> list[dict[str, object]]:
        expanded.append(str(row.get("entry_cid")))
        return [row]

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.world_law.atomic_corpus.expand_legal_record",
        expand,
    )
    calls: list[str] = []

    def opener(repo: str) -> tuple[dict[str, object], ...]:
        calls.append(repo)
        return (
            {
                "entry_cid": "other",
                "authority": "City of Blue Ash",
                "jurisdiction": "US-OH",
                "effective_date": "2020-11-03",
                "text": "x" * 1000,
                "provenance": {"section": "3.11"},
            },
            {
                "entry_cid": "hit",
                "authority": "City of Hamilton",
                "jurisdiction": "US-OH",
                "effective_date": "2020-11-03",
                "text": "Hamilton section.",
                "provenance": {"section": "3.11"},
            },
            {
                "entry_cid": "later",
                "authority": "City of Hamilton",
                "jurisdiction": "US-OH",
                "effective_date": "2021-01-01",
                "text": "later",
                "provenance": {"section": "3.11"},
            },
        )

    result = query_legal_records(
        jurisdiction="US",
        place="Hamilton, Ohio",
        section="3.11",
        as_of="2020-11-03",
        corpus_opener=opener,
    )
    assert [row["entry_cid"] for row in result.records] == ["hit"]
    assert expanded == ["hit"]
    assert calls == ["justicedao/american_municipal_law_norm"]


def test_omitted_retrieval_keeps_the_query_id(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    bare = query_legal_records(jurisdiction="FR", text_query="code", citation="art 1")
    blank = query_legal_records(
        jurisdiction="FR",
        text_query="code",
        citation="art 1",
        retrieval="  ",
    )
    assert bare.query_id == blank.query_id
    keyword = query_legal_records(
        jurisdiction="FR",
        text_query="code",
        citation="art 1",
        retrieval="keyword",
    )
    assert keyword.query_id != bare.query_id
    assert keyword.records == ()


def test_retrieval_requires_a_known_mode_and_query_text(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    with pytest.raises(LegalQueryInputError) as mode_error:
        query_legal_records(jurisdiction="FR", text_query="code", retrieval="bm25")
    assert mode_error.value.code == "retrieval"
    with pytest.raises(LegalQueryInputError) as text_error:
        query_legal_records(jurisdiction="FR", retrieval="vector")
    assert text_error.value.code == "text_query"
    with pytest.raises(LegalQueryInputError) as admin_error:
        query_legal_records(
            jurisdiction="US",
            text_query="zoning",
            retrieval="keyword",
        )
    assert admin_error.value.code == "admin_level_required"


def test_keyword_and_vector_stay_inside_the_resolved_city(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_QUERY_NORMALIZED", "1")
    zoning = {
        "entry_cid": "zoning",
        "authority": "City of Hamilton",
        "jurisdiction": "US-OH",
        "text": "A zoning variance requires a public hearing before the board.",
        "citation": "Hamilton Zoning Code",
        "provenance": {"section": "11.2"},
    }
    dogs = {
        "entry_cid": "dogs",
        "authority": "City of Hamilton",
        "jurisdiction": "US-OH",
        "text": "Dogs must be licensed by the city clerk each calendar year.",
        "citation": "Hamilton Animal Code",
        "provenance": {"section": "4.1"},
    }
    other = {
        "entry_cid": "other",
        "authority": "City of Blue Ash",
        "jurisdiction": "US-OH",
        "text": "A zoning variance requires a public hearing before the board.",
        "citation": "Blue Ash Zoning Code",
        "provenance": {"section": "11.2"},
    }

    def opener(repo: str) -> tuple[dict[str, object], ...]:
        assert repo == "justicedao/american_municipal_law_norm"
        return (other, dogs, zoning)

    keyword = query_legal_records(
        jurisdiction="US",
        place="Hamilton, Ohio",
        text_query="zoning variance",
        retrieval="keyword",
        corpus_opener=opener,
    )
    assert keyword.source_repo == "justicedao/american_municipal_law_norm"
    assert keyword.source_revision == "df0c0c405bf59cb948d1269dea29767a4712fb81"
    assert keyword.place_name == "City of Hamilton"
    assert keyword.place_state == "OH"
    assert [row["entry_cid"] for row in keyword.records] == ["zoning"]
    assert keyword.records[0]["provenance"]["section"] == "11.2"
    vector = query_legal_records(
        jurisdiction="US",
        place="Hamilton, Ohio",
        text_query="zoning variance spacecraft",
        retrieval="vector",
        corpus_opener=opener,
    )
    assert vector.records[0]["entry_cid"] == "zoning"
    assert {row["authority"] for row in vector.records} == {"City of Hamilton"}
    rejected = query_legal_records(
        jurisdiction="US",
        place="Hamilton, Ohio",
        text_query="zoning variance spacecraft",
        retrieval="keyword",
        corpus_opener=opener,
    )
    assert rejected.records == ()
