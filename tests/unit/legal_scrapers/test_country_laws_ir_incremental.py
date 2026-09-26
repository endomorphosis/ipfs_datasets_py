"""CID-keyed incremental country-laws GraphRAG rebuild (endomorphosis → justicedao)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.catalog import (
    EXCLUDED_SLUGS,
    get_country,
    merge_country_rows,
    persist_catalog,
    target_repo,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.incremental import (
    BuildMode,
    RebuildKind,
    diff_corpus,
    embeddings_from_vector_table,
    plan_rebuild,
    source_fingerprint,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.normalize import build_corpus
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.raw_package import (
    instruments_to_frames,
    merge_articles,
    merge_laws,
    package_instruments,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.vectors import (
    DIMENSION,
    assemble_embeddings,
)


def _laws(*rows: dict) -> pd.DataFrame:
    frame = pd.DataFrame(list(rows))
    if "article_count" not in frame.columns:
        frame["article_count"] = 0
    return frame


def _articles(*rows: dict) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(
            columns=["id", "law_id", "title", "text", "article_number", "metadata_json"]
        )
    return pd.DataFrame(list(rows))


def _source_meta(revision: str = "rev-a", extra: dict | None = None) -> dict:
    meta = {
        "source_dataset": "endomorphosis/ipfs_fixture_laws",
        "source_revision": revision,
        "laws_sha256": f"laws-{revision}",
        "articles_sha256": f"arts-{revision}",
        "schema_surprises": [],
    }
    if extra:
        meta.update(extra)
    return meta


def _corpus_for(*titles: str, revision: str = "rev-a") -> pd.DataFrame:
    laws = _laws(
        *[
            {
                "id": f"law-{i}",
                "title": title,
                "text": f"Body text for {title}. " * 8,
                "jurisdiction": "Fixture",
                "country": "Fixture",
                "language": "en",
                "source_url": f"https://example.test/{i}",
                "license": "cc0",
                "eli": "",
                "identifier": f"law-{i}",
                "official_identifier": f"LAW-{i}",
                "source_type": "official",
                "law_status": "in_force",
                "metadata_json": "{}",
            }
            for i, title in enumerate(titles, start=1)
        ]
    )
    corpus, _report = build_corpus(laws, _articles(), _source_meta(revision))
    return corpus


def test_catalog_targets_justicedao_and_endomorphosis_source() -> None:
    germany = get_country("germany")
    assert germany["repo"] == "endomorphosis/ipfs_germany_laws"
    assert target_repo("germany") == "justicedao/ipfs_germany_laws_ir"
    inferred = get_country("endomorphosis/ipfs_oman_laws")
    assert inferred["slug"] == "oman"
    assert inferred["indexable"] is True
    assert "portugal" in EXCLUDED_SLUGS


def test_catalog_merge_fills_hub_gaps_without_overriding_exclusions() -> None:
    baseline = [
        {
            "slug": "malta",
            "repo": "endomorphosis/ipfs_malta_laws",
            "indexable": True,
        },
        {
            "slug": "belgium",
            "repo": "endomorphosis/ipfs_belgium_laws",
            "indexable": False,
        },
    ]
    extra = [
        {
            "slug": "belgium",
            "repo": "endomorphosis/ipfs_belgium_laws",
            "indexable": True,
        },
        {
            "slug": "serbia",
            "repo": "endomorphosis/ipfs_serbia_laws",
            "indexable": True,
        },
    ]
    merged = merge_country_rows(baseline, extra)
    by_slug = {row["slug"]: row for row in merged}
    assert by_slug["belgium"]["indexable"] is False
    assert by_slug["serbia"]["repo"] == "endomorphosis/ipfs_serbia_laws"


def test_persist_catalog_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COUNTRY_LAWS_IR_ROOT", str(tmp_path))
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir import catalog as catalog_mod

    path = persist_catalog(
        [{"slug": "oman", "repo": "endomorphosis/ipfs_oman_laws", "indexable": True}],
        path=tmp_path / "catalog_cache.json",
    )
    assert path.is_file()
    loaded = catalog_mod.load_cached_countries()
    # load_cached_countries reads COUNTRY_LAWS_IR_ROOT/catalog_cache.json
    cached = json.loads(path.read_text(encoding="utf-8"))
    assert cached["countries"][0]["slug"] == "oman"
    assert isinstance(loaded, list)


def test_heading_language_profile_rejects_latin_split_of_arabic() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.profiles import (
        latin_split_allowed,
        score_heading_languages,
    )
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.structure import (
        split_structured_units,
    )
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.verify import (
        check_heading_language,
    )

    assert latin_split_allowed("fr") is True
    assert latin_split_allowed("ar") is False
    assert split_structured_units("Article 1 Foo\nArticle 2 Bar", language="ar") == []
    arabic = "مادة 1 التعاريف. المحكمة تعني محكمة.\nمادة 2 الإجراءات. تنعقد المحكمة علنا."
    ar_units = split_structured_units(arabic, language="ar")
    assert len(ar_units) >= 2
    chinese = "第一条 定义。法院是指依法独立行使审判权的国家机关。\n第二条 程序。人民法院公开审理案件并宣告判决。"
    zh_units = split_structured_units(chinese, language="zh")
    assert len(zh_units) >= 2
    ru = (
        "Статья 1 Понятия. Суд означает судебный орган по настоящему закону.\n"
        "Статья 2 Процедура. Суд рассматривает дело открыто."
    )
    ru_units = split_structured_units(ru, language="ru")
    assert len(ru_units) >= 2
    sq = (
        "Neni 1 Përkufizime. Gjykata është organ gjyqësor sipas këtij ligji.\n"
        "Neni 2 Procedura. Gjykata shqyrton çështjen publikisht."
    )
    sq_units = split_structured_units(sq, language="sq")
    assert len(sq_units) >= 2
    ko = "제1조 정의. 법원은 재판기관을 말한다. 제2조 절차. 법원은 공개로 심리한다."
    ko_units = split_structured_units(ko, language="ko")
    assert len(ko_units) >= 2
    idn = (
        "Pasal 1 Pengertian. Pengadilan adalah lembaga peradilan menurut undang-undang ini.\n"
        "Pasal 2 Tata cara. Pengadilan memeriksa perkara secara terbuka."
    )
    id_units = split_structured_units(idn, language="id")
    assert len(id_units) >= 2
    fr_er = (
        "Art. 1er Objet. La présente loi fixe les règles applicables.\n"
        "Art. 2 Champ. Elle s'applique sur tout le territoire national."
    )
    fr_units = split_structured_units(fr_er, language="fr")
    assert len(fr_units) >= 2
    counts = score_heading_languages("Chapter 2\nTitle 1")
    assert counts["en"] >= 1
    verdict = check_heading_language(
        None,
        {
            "document_language_majority": "ar",
            "heading_language_majority": "en",
            "heading_language_counts": {"en": 12},
            "unit": "structured",
        },
    )
    assert verdict.passed is False
    assert verdict.severity == "fail"


def test_reconstruct_empty_parent_from_articles_sparse_coverage() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.normalize import (
        build_corpus,
    )
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.reconstruct import (
        article_sort_key,
        expected_glue_from_children,
        glue_piece,
    )

    assert article_sort_key("2", "a") < article_sort_key("10", "b")
    assert article_sort_key("٢", "a")[1] == (2,)

    laws = _laws(
        {
            "id": "law-1",
            "title": "Empty Parent Act",
            "text": "",
            "jurisdiction": "Fixture",
            "country": "Fixture",
            "language": "en",
            "source_url": "https://example.test/1",
            "license": "cc0",
            "eli": "",
            "identifier": "law-1",
            "official_identifier": "LAW-1",
            "source_type": "official",
            "law_status": "in_force",
            "metadata_json": "{}",
        }
    )
    # 3 articles vs 1 law → coverage 3.0, not sparse. Also test sparse: 1 law + 1 article
    # would be coverage 1. Use 3 articles anyway.
    articles = _articles(
        {
            "id": "art-10",
            "law_id": "law-1",
            "title": "Article 10",
            "text": "<p>Tenth body.&nbsp;More text so the article exceeds forty characters.</p>",
            "article_number": "10",
            "metadata_json": "{}",
        },
        {
            "id": "art-2",
            "law_id": "law-1",
            "title": "Article 2",
            "text": "Second body text for the act, long enough to pass the short-body verifier.",
            "article_number": "2",
            "metadata_json": "{}",
        },
        {
            "id": "art-3",
            "law_id": "law-1",
            "title": "Article 3",
            "text": "Third body text for the act, long enough to pass the short-body verifier.",
            "article_number": "3",
            "metadata_json": "{}",
        },
    )
    corpus, report = build_corpus(laws, articles, _source_meta("rev-a"))
    laws_out = corpus[corpus["record_type"] == "law"]
    kids = corpus[corpus["record_type"] == "article"]
    assert len(laws_out) == 1
    assert len(kids) == 3
    assert bool(laws_out.iloc[0]["reconstructed_from_articles"]) is True
    assert report["n_empty_parents_with_articles_not_reconstructed"] == 0
    assert report["verification"]["admitted"] is True
    # 2 before 10
    assert list(kids["article_number"]) == ["2", "3", "10"]
    expected = expected_glue_from_children(
        [
            {
                "id": r.source_id,
                "title": r.article_title,
                "article_number": r.article_number,
                "body": r.body,
            }
            for r in kids.itertuples(index=False)
        ]
    )
    assert laws_out.iloc[0]["body"] == expected
    assert "Tenth body." in laws_out.iloc[0]["body"]
    assert "<p>" not in laws_out.iloc[0]["body"]


def test_reconstruct_prefix_never_holds_over_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir import reconstruct as rec
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.cidutil import sha256_hex

    monkeypatch.setattr(rec, "RECONSTRUCT_MAX_PARENT_CHARS", 40)
    children = [
        {"id": "a", "title": "A", "article_number": "1", "body": "x" * 30},
        {"id": "b", "title": "B", "article_number": "2", "body": "y" * 30},
    ]
    out = rec.reconstruct_parent(
        slug="fixture",
        parent_body="",
        parent_title="Act",
        children=children,
        running_extra_bytes=0,
        sha256_hex=sha256_hex,
    )
    assert out.reconstruction_truncated is True
    assert len(out.body) <= 40
    assert out.reconstructed_from_articles is True


def test_assign_citation_bluebook_when_known_else_official_only() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.citations import (
        assign_citation,
        normalize_cite_key,
    )

    mt = assign_citation(
        official_identifier="Cap. 9",
        article_number="3",
        record_type="article",
        country="Malta",
        slug="malta",
        year="2023",
    )
    assert mt.citation_status == "official_only"
    assert mt.bluebook_citation == ""
    assert "Cap. 9" in mt.official_citation

    usa = assign_citation(
        instrument_title="42",
        section_number="1983",
        record_type="section",
        slug="usa",
        year="2023",
    )
    assert usa.citation_status == "bluebook"
    assert "§ 1983" in usa.bluebook_citation

    unknown = assign_citation(
        official_identifier="Act 12/2019",
        country="Eritrea",
        slug="eritrea",
    )
    assert unknown.citation_status == "official_only"
    assert unknown.bluebook_citation == ""
    assert unknown.official_citation == "Act 12/2019"
    assert normalize_cite_key("Or. Rev. Stat. § 1.010") == normalize_cite_key("or rev stat s 1 010")


def test_corpus_rows_include_citation_fields() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.normalize import (
        build_corpus,
    )

    laws = _laws(
        {
            "id": "law-1",
            "title": "Courts Act",
            "text": "The Courts Act body text for citation. " * 8,
            "jurisdiction": "Malta",
            "country": "Malta",
            "language": "en",
            "source_url": "https://example.test/1",
            "license": "cc0",
            "eli": "",
            "identifier": "Cap. 9",
            "official_identifier": "Cap. 9",
            "source_type": "official",
            "law_status": "in_force",
            "metadata_json": "{}",
        }
    )
    corpus, _report = build_corpus(laws, _articles(), _source_meta("rev-a"))
    assert "official_citation" in corpus.columns
    assert "cite_key" in corpus.columns
    assert str(corpus["official_citation"].iloc[0])
    assert corpus["citation_status"].iloc[0] in {"bluebook", "official_only"}


def test_normalize_keeps_parent_law_when_articles_exist() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.normalize import (
        build_corpus,
    )

    laws = _laws(
        {
            "id": "law-1",
            "title": "Courts Act",
            "text": "The Courts Act. Article 1 Definitions. Article 2 Procedure.",
            "jurisdiction": "Fixture",
            "country": "Fixture",
            "language": "en",
            "source_url": "https://example.test/1",
            "license": "cc0",
            "eli": "",
            "identifier": "law-1",
            "official_identifier": "LAW-1",
            "source_type": "official",
            "law_status": "in_force",
            "metadata_json": "{}",
        }
    )
    articles = _articles(
        {
            "id": "art-1",
            "law_id": "law-1",
            "title": "Article 1",
            "text": "Article 1 Definitions. Court means a court of record.",
            "article_number": "1",
            "metadata_json": "{}",
        },
        {
            "id": "art-2",
            "law_id": "law-1",
            "title": "Article 2",
            "text": "Article 2 Procedure. The court shall sit in public.",
            "article_number": "2",
            "metadata_json": "{}",
        },
    )
    corpus, report = build_corpus(laws, articles, _source_meta("rev-a"))
    assert report["n_law_rows"] == 1
    assert report["n_child_rows"] == 2
    assert report["unit"] == "law+article"
    assert report["verification"]["admitted"] is True
    assert "parent_laws" not in report["verification"]["failed_ids"]


def test_verifiers_admit_structured_corpus_and_reject_html() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.normalize import (
        build_corpus,
    )
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.verify import (
        verify_normalized_corpus,
    )

    laws = _laws(
        {
            "id": "law-1",
            "title": "Courts Act",
            "text": (
                "Article 1 Definitions. Court means a court of record.\n"
                "Article 2 Procedure. The court shall sit in public."
            ),
            "jurisdiction": "Fixture",
            "country": "Fixture",
            "language": "en",
            "source_url": "https://example.test/1",
            "license": "cc0",
            "eli": "",
            "identifier": "law-1",
            "official_identifier": "LAW-1",
            "source_type": "official",
            "law_status": "in_force",
            "metadata_json": "{}",
        }
    )
    corpus, report = build_corpus(laws, _articles(), _source_meta("rev-a"))
    verdict = report["verification"]
    assert verdict["admitted"] is True
    assert "html_residual" not in verdict["failed_ids"]
    assert verdict["blocks_graphrag"] is False

    dirty = corpus.copy()
    dirty.loc[0, "body"] = "<html><nav>Menu</nav><div>not stripped</div></html>"
    blocked = verify_normalized_corpus(dirty, report, slug="fixture")
    assert blocked["admitted"] is False
    assert "html_residual" in blocked["failed_ids"]


def test_exclusive_cover_includes_preamble_and_keeps_body_spans() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.structure import (
        check_exclusive_cover,
        segment_exclusive,
        split_structured_units,
    )

    oregonish = (
        "Preamble words.\n"
        "TITLE 1 Administration\n"
        "CHAPTER 1 Courts\n"
        "SECTION 1.010 Definitions. (1) Court means a circuit court. (2) Judge means a judge of the court.\n"
        "SECTION 1.020 Application. This chapter applies to all circuit courts."
    )
    internal = segment_exclusive(oregonish)
    assert check_exclusive_cover(oregonish, internal)
    assert internal[0].kind == "preamble"
    assert all(u.body == oregonish[u.char_start : u.char_end] for u in internal)
    retrieval = split_structured_units(oregonish)
    assert [u.kind for u in retrieval] == ["section", "section"]
    assert any(u.section_number.startswith("1.010") or "1.010" in u.section_number for u in retrieval)

    short = "TITLE 1 Only\nCHAPTER 2 Still only headings here."
    assert split_structured_units(short) == []
    assert check_exclusive_cover(short, segment_exclusive(short))

    sec = "SECTION 552(a) Records. A person may request records.\nSECTION 552(b) Exemptions. This does not apply to secrets."
    units = split_structured_units(sec)
    assert any("552(a)" in u.section_number for u in units)

    chinese = "前言。第一条 定义。法院是指依法独立行使审判权的国家机关。第二条 程序。人民法院公开审理案件并宣告判决。"
    zh_int = segment_exclusive(chinese, language="zh")
    assert check_exclusive_cover(chinese, zh_int)
    assert zh_int[0].kind == "preamble"


def test_structure_strips_html_and_splits_oregon_style_headings() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.structure import (
        normalize_legal_text,
        split_structured_units,
    )

    html = "<html><nav>Menu</nav><p>Article 1 Definitions. (1) Person means a human.</p></html>"
    assert "Menu" not in normalize_legal_text(html)
    assert "Article 1" in normalize_legal_text(html)

    oregonish = (
        "TITLE 1 Administration\n"
        "CHAPTER 1 Courts\n"
        "SECTION 1.010 Definitions. (1) Court means a circuit court. (2) Judge means a judge of the court.\n"
        "SECTION 1.020 Application. This chapter applies to all circuit courts."
    )
    units = split_structured_units(oregonish)
    kinds = [u.kind for u in units]
    assert kinds.count("section") >= 2
    first_section = next(u for u in units if u.kind == "section")
    assert first_section.title_number == "1"
    assert first_section.chapter_number == "1"
    assert "1" in first_section.subsections or "2" in first_section.subsections
    assert "Title 1" in first_section.hierarchy_path

    french = (
        "TITRE I Dispositions générales\n"
        "Article 1 Objet. La présente loi fixe les règles.\n"
        "Article 2 Champ d'application. Elle s'applique sur tout le territoire."
    )
    arts = split_structured_units(french)
    assert [u.kind for u in arts] == ["article", "article"]
    assert arts[0].title_number == "I"

    blob = "This instrument has no numbered articles or sections at all, just a preamble."
    assert split_structured_units(blob) == []


def test_multilingual_heading_syntaxes_and_chrome() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.profiles import (
        score_heading_languages,
    )
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.structure import (
        check_exclusive_cover,
        normalize_legal_text,
        segment_exclusive,
        split_structured_units,
    )

    def _split(text: str, language: str = "") -> list[str]:
        units = split_structured_units(text, language=language)
        assert check_exclusive_cover(text, segment_exclusive(text, language=language))
        return [u.number for u in units]

    bosnian = (
        "Član 1. Sud je organ sudske vlasti prema ovom zakonu i odlučuje.\n"
        "Član 12. Postupak pred sudom je javan osim ako zakon ne odredi drukčije."
    )
    assert _split(bosnian, "hr") == ["1", "12"]

    slovenian = (
        "Člen 1 Sodišče je organ sodne veje oblasti po tem zakonu.\n"
        "Člen 2 Postopek pred sodiščem je javen, razen če zakon določa drugače."
    )
    assert _split(slovenian, "sl") == ["1", "2"]
    sl_counts = score_heading_languages(slovenian)
    assert sl_counts["sl"] >= 1
    assert "hr" not in sl_counts

    finnish = (
        "1 § Konkurssiin asettamista koskeva asia pannaan vireille kirjallisella hakemuksella tuomioistuimessa.\n"
        "1 a § Konkurssiin asettamista koskevan asian käsittelee se tuomioistuin, jonka tuomiopiirissä velallinen asuu."
    )
    fi_nums = _split(finnish, "fi")
    assert "1" in fi_nums and "1 a" in fi_nums

    icelandic = (
        "1. gr. Dómstólar dæma í málum samkvæmt lögum þessum og stjórnarskrá.\n"
        "2. gr. Þinghöld skulu vera opinber nema lög kveði á um annað."
    )
    assert _split(icelandic, "is") == ["1", "2"]

    hungarian = (
        "13. § A társadalmi szervezet legfelsőbb szervének hatáskörébe tartozik a döntés.\n"
        "14. § A társadalmi szervezet működése felett az ügyészség a törvényességi felügyeletet gyakorolja."
    )
    assert _split(hungarian, "hu") == ["13", "14"]

    bulgarian = (
        "Чл. 1. Създава Съвет по прилагане на актуализираната стратегия за реформа.\n"
        "Чл. 10. За всяко заседание на Съвета се изготвя протокол, в който се отразяват решенията."
    )
    assert _split(bulgarian, "bg") == ["1", "10"]

    swiss = (
        "Art. 1 Die Würde des Menschen ist zu achten und zu schützen.\n"
        "Art. 2 Die Schweizerische Eidgenossenschaft schützt die Freiheit und die Rechte des Volkes."
    )
    assert _split(swiss, "de") == ["1", "2"]

    turkish = (
        "Madde 1 – (Değişik: 6/3/2007) Bu kanunun amacı yargı bağımsızlığını güvence altına almaktır.\n"
        "Ek Madde 1 – (Ek: 6/3/2007-5595/3) Geçici hükümler saklı kalmak üzere uygulanır."
    )
    tr_nums = _split(turkish, "tr")
    assert "1" in tr_nums
    assert len(tr_nums) >= 2

    arabic = "المادة الأولى المحكمة جهة قضائية مستقلة وفق هذا القانون.\nالمادة 40من الإجراءات تنعقد المحكمة علنا إلا إذا قرر القانون خلاف ذلك."
    ar_units = split_structured_units(arabic, language="ar")
    assert len(ar_units) >= 2

    egypt = "مادة ()1 المحكمة جهة قضائية مستقلة وفق أحكام هذا القانون.\nمادة ()10 تنعقد المحكمة علنا وتصدر أحكامها مسببة."
    assert len(split_structured_units(egypt, language="ar")) >= 2

    georgian = "მუხლი 1 სასამართლო არის სასამართლო ხელისუფლების ორგანო.\nმუხლი 2 საქმის განხილვა საჯაროა, თუ კანონი სხვა რამეს არ ითვალისწინებს."
    assert len(split_structured_units(georgian, language="ka")) >= 2

    armenian = "Հոդված 1. Դատարանը դատական իշխանության մարմին է սույն օրենքով.\nՀոդված 2. Դատավարությունը հրապարակային է, եթե օրենքը այլ բան չի սահմանում."
    assert len(split_structured_units(armenian, language="hy")) >= 2

    amharic = "አንቀጽ ፬ ተተክቷል፦ ፍርድ ቤቱ በዚህ አዋጅ መሠረት የዳኝነት አካል ነው።\nአንቀጽ ፯ ተተክቷል፦ የፍርድ ሂደቱ በግልጽ ይካሄዳል በሕግ ካልተደነገገ በስተቀር።"
    assert len(split_structured_units(amharic, language="am")) >= 2

    chrome = (
        "Početna stranica\n"
        "Vsebina Uradnega lista | Uradni list\n"
        "The incident ID is 0xDEAD.\n"
        "Article 1 Definitions. Court means a court of record under this Act.\n"
        "Article 2 Procedure. The court shall sit in public except as provided."
    )
    cleaned = normalize_legal_text(chrome)
    assert "Početna" not in cleaned
    assert "Vsebina" not in cleaned
    assert "incident ID" not in cleaned
    assert "Article 1" in cleaned
    bom = normalize_legal_text("\ufeffArticle 1 Object. The present Act sets the applicable rules.\nArticle 2 Scope. It applies throughout the national territory.")
    assert not bom.startswith("\ufeff")
    assert split_structured_units(bom, language="en")[0].number == "1"

    clan_gov = "Član Vlade kome je pitanje upućeno odgovara u skladu s poslovnikom."
    assert split_structured_units(clan_gov, language="hr") == []

    spanish = (
        "ARTICULO 1o.- Ordénase la publicación del texto oficial de la presente ley en el boletín.\n"
        "ARTICULO 10.- En el interior de la República se aplican las mismas disposiciones vigentes."
    )
    assert _split(spanish, "es") == ["1o", "10"]

    persian = (
        "ماده1ـ تعاریف دادگاه به معنای مرجع قضایی صالح طبق این قانون است و استقلال دارد.\n"
        "ماده27ـ چنانچه دانشجو در حین تحصیل مرتکب تخلف علمی شود رسیدگی طبق این ماده است."
    )
    assert len(split_structured_units(persian, language="fa")) >= 2

    lao = (
        "ມາດຕາ 1 ຈຸດປະສົງ ຂອງລັດຖະບັນຍັດນີ້ແມ່ນເພື່ອປົກປ້ອງສິດທິພົນລະເຮືອນ.\n"
        "ມາດຕາ 10 ເຂດຍຸດທະສາດການທະຫານ ຖືກກໍານົດໄວ້ໃນລັດຖະບັນຍັດສະບັບນີ້."
    )
    assert len(split_structured_units(lao, language="lo")) >= 2

    uzbek = (
        "1-модда. Фуқаролик қонунчилигининг асосий негизлари суд мустақиллигини белгилайди.\n"
        "2-модда. Фуқаролик қонунчилиги билан тартибга солинадиган муносабатлар очиқ кўрилади."
    )
    assert _split(uzbek, "uz") == ["1", "2"]

    mongolian = (
        "2 дугаар зүйл.Өршөөл үзүүлэх тухай хууль тогтоомжийг энэ хуулиар зохицуулна.\n"
        "3 дугаар зүйл.Хууль үйлчлэх цаг, хугацааг энэ зүйлд заасны дагуу тогтооно."
    )
    assert _split(mongolian, "mn") == ["2", "3"]

    azeri = (
        "Maddə 1. Qanunun müəyyən etdiyi qaydalar məhkəmənin müstəqilliyini təmin edir.\n"
        "Maddə 10. Hüquqi dövlətin ümumi prinsipləri bu qanunda təsbit olunur."
    )
    assert _split(azeri, "az") == ["1", "10"]

    hebrew = (
        ".14מטרת הקרן תהיה לרכז את האמצעים הכספיים ללחימה בזיהום מים לפי פקודה זו.\n"
        ".15כספי הקרן ייועדו למטרותיה בלבד ויוצאו לפי הוראות שר הפנים בלבד."
    )
    assert len(split_structured_units(hebrew, language="he")) >= 2

    commonwealth = (
        "1. Short title and commencement : (1) This Order may be cited as the Board Order.\n"
        "10. Account and Audit: (1) The accounts of the incomes and expenditures shall be audited."
    )
    cw_nums = _split(commonwealth, "en")
    assert "1" in cw_nums and "10" in cw_nums

    compacted = (
        "Article 1 Definitions. Court means a court of record under this Act. "
        "Article 2 Procedure. The court shall sit in public except as this Act provides."
    )
    assert _split(compacted, "en") == ["1", "2"]

    korean_range = (
        "제1조(시행일) 이 법은 공포한 날부터 시행한다. 다만 부칙은 따로 정할 수 있다.\n"
        "제2조 부터 제5조까지 생략\n"
        "제6조(벌칙) 이 법을 위반한 자는 벌금에 처한다. 법원은 공개로 심리한다."
    )
    ko_nums = [u.number for u in split_structured_units(korean_range, language="ko")]
    assert any("1" in n for n in ko_nums)
    assert any("6" in n for n in ko_nums)
    assert not any(n.endswith("5조") or n == "제5조" for n in ko_nums)

    french_code = (
        "Art. L. 111-1 La présente partie fixe les règles applicables sur le territoire.\n"
        "Art. R. 123-4 Les modalités d'application sont précisées par décret en Conseil d'État."
    )
    assert _split(french_code, "fr") == ["L. 111-1", "R. 123-4"]

    uae = (
        "Article (1) The Union is an independent sovereign State.\n"
        "Article (2) The Union exercises sovereignty over the territory and territorial waters."
    )
    assert _split(uae, "en") == ["1", "2"]

    philippines = (
        "ARTICLE I National Territory. The national territory comprises the Philippine archipelago.\n"
        "ARTICLE II Declaration of Principles. The Philippines is a democratic and republican State."
    )
    assert _split(philippines, "en") == ["I", "II"]

    saudi = (
        "المادة الحادية عشرة تختص المحكمة بالنظر في المنازعات الناشئة عن تطبيق هذا النظام.\n"
        "المادة الثانية عشرة تنشر الأحكام القضائية وفق ما تحدده اللائحة التنفيذية."
    )
    assert len(split_structured_units(saudi, language="ar")) >= 2

    qatar_bis = (
        "مادة 2 مكرر يجوز إعادة تمديد المدة المنصوص عليها في المادة السابقة بموافقة النائب.\n"
        "مادة (3) تسري أحكام هذا القانون على جميع الأشخاص الاعتبارية العامة والخاصة."
    )
    assert len(split_structured_units(qatar_bis, language="ar")) >= 2

    cite_only = (
        "Article 1 of this Agreement who are declared undesirable shall leave the territory.\n"
        "Article 10 for the entry into force of the Agreement shall apply mutatis mutandis."
    )
    assert split_structured_units(cite_only, language="en") == []

    portal = normalize_legal_text(
        "Al Meezan - Qatary Legal Portal | Legislations | Decree No. 1\n"
        "المادة 1 المحكمة جهة قضائية مستقلة وفق هذا القانون وتصدر أحكامها مسببة."
    )
    assert "Al Meezan" not in portal
    assert "المادة 1" in portal

    georgia_en = (
        "Article 1 - Purpose and scope of the procedures for child protection cases.\n"
        "Article 10 - Registration of children placed in specialised child care institutions."
    )
    assert len(split_structured_units(georgia_en, language="ka")) >= 2

    malay = (
        "Seksyen 1. Tajuk ringkas. Akta ini boleh disebut sebagai Akta Semakan Undang-Undang 1968.\n"
        "Seksyen 10. (1) Suatu undang-undang semakan yang mengandungi pindaan hendaklah dikuatkuasakan."
    )
    assert _split(malay, "ms") == ["1", "10"]

    kazakh = (
        "1-бап. Осы Кодексте пайдаланылатын негізгі ұғымдар сот билігінің тәуелсіздігін білдіреді.\n"
        "2-бап. Әкімшілік құқық бұзушылық туралы заңнаманың міндеттері осы бапта айқындалады."
    )
    assert _split(kazakh, "kk") == ["1", "2"]

    portuguese = (
        "Artigo n.º 1.º A presente lei estabelece as regras aplicáveis em todo o território nacional.\n"
        "Artigo n.º 2.º O disposto na presente lei aplica-se às pessoas singulares e colectivas."
    )
    assert _split(portuguese, "pt") == ["1", "2"]

    german_short = (
        "§ 1 Ausgabe durch die Deutsche Bundesbank im gesamten Bundesgebiet.\n"
        "§ 10 Errichtung der Stiftung mit Sitz in Frankfurt am Main nach diesem Gesetz."
    )
    assert _split(german_short, "de") == ["1", "10"]

    irish = (
        "Airteagal 1. Is é seo an phríomhaidhm atá leis an Acht seo ar fud an Stáit.\n"
        "Airteagal 2. Tá feidhm ag an Acht seo ar fud an Stáit agus na ndlínsí eile."
    )
    assert _split(irish, "ga") == ["1", "2"]

    somali = (
        "Qodob 1. Maxkamaddu waa hay'ad garsoor oo madax-bannaan sida uu qabo sharcigan.\n"
        "Qodob 2. Dacwadaha maxkamadda waa in ay noqdaan kuwo dadweyne ah sida sharciga."
    )
    assert _split(somali, "so") == ["1", "2"]

    urdu = (
        "دفعہ 1 عدالت ایک آزاد ادارہ ہے اس قانون کے تحت اور اپنے فیصلے صادر کرتی ہے۔\n"
        "دفعہ 2 مقدمے کی کارروائی علانیہ ہو گی جب تک قانون منع نہ کرے۔"
    )
    assert len(split_structured_units(urdu, language="ur")) >= 2

    kyrgyz = (
        "1-берене. Сот бийлигинин көз карандысыздыгы ушул мыйзам менен белгиленет.\n"
        "2-берене. Иштерди сот ачык түрдө карай тургандыгы ушул беренеде жазылат."
    )
    assert _split(kyrgyz, "ky") == ["1", "2"]

    belarusian = (
        "Артыкул 1. Суд з'яўляецца органам судовай улады паводле гэтага закона.\n"
        "Артыкул 2. Разгляд спраў у судзе адбываецца адкрыта, калі закон не прадугледжвае іншае."
    )
    assert _split(belarusian, "be") == ["1", "2"]

    year_titles = (
        "1902. Amendment Ordinance of the Cape Colony railway superannuation funds.\n"
        "1903. Indemnity Ordinance relating to martial law proclamations in the colony."
    )
    assert split_structured_units(year_titles, language="en") == []

    french_numero = normalize_legal_text(
        "Art. n° 1 Objet. La présente loi fixe les règles applicables sur tout le territoire.\n"
        "Art. nr. 2 Champ. Elle s'applique sur tout le territoire national sans exception."
    )
    assert _split(french_numero, "fr") == ["1", "2"]

    french_cite = (
        "Article 1 Objet. La présente loi fixe les règles applicables sur tout le territoire.\n"
        "Art. 2 de la loi n° 65-51 du 19 juillet 1965 s'applique aux contrats en cours de validité.\n"
        "Article 3 Champ. Elle s'applique sur tout le territoire national sans exception aucune."
    )
    assert _split(french_cite, "fr") == ["1", "3"]

    chinese_range = (
        "第一条 定义。法院是指依法独立行使审判权的国家机关。\n"
        "第二条至第五条 省略\n"
        "第六条 程序。人民法院公开审理案件并宣告判决。"
    )
    zh_nums = [u.number for u in split_structured_units(chinese_range, language="zh")]
    assert "1" in zh_nums
    assert "6" in zh_nums
    assert "2" not in zh_nums and "5" not in zh_nums

    larticle = (
        "L'article 1 Objet. La présente loi fixe les règles applicables sur tout le territoire.\n"
        "L'article 2 Champ. Elle s'applique sur tout le territoire national sans exception."
    )
    assert _split(larticle, "fr") == ["1", "2"]

    premier = (
        "Article premier Objet. La présente loi fixe les règles applicables sur tout le territoire national.\n"
        "Article 2 Champ. Elle s'applique sur tout le territoire national sans exception aucune."
    )
    assert _split(premier, "fr")[0] == "premier"
    assert "2" in _split(premier, "fr")

    larticolo = (
        "L'articolo 1 Definizioni. Il tribunale è organo giurisdizionale indipendente secondo questa legge.\n"
        "L'articolo 2 Procedura. Il tribunale giudica in udienza pubblica salvo diversa disposizione."
    )
    assert _split(larticolo, "it") == ["1", "2"]

    primero = (
        "Artículo primero Objeto. La presente ley fija las reglas aplicables en todo el territorio nacional.\n"
        "Artículo 2 Ámbito. Se aplica en todo el territorio nacional sin excepción alguna."
    )
    assert _split(primero, "es")[0] == "primero"

    qodobka = (
        "Qodobka 1aad Maxkamaddu waa hay'ad garsoor oo madax-bannaan sida uu qabo sharcigan.\n"
        "Qodobka 2aad Dacwadaha maxkamadda waa in ay noqdaan kuwo dadweyne ah sida sharciga."
    )
    assert len(split_structured_units(qodobka, language="so")) >= 2

    thai_digits = (
        "มาตรา ๑ ศาลเป็นองค์กรตุลาการตามพระราชบัญญัตินี้และมีความเป็นอิสระในการพิจารณาพิพากษา\n"
        "มาตรา ๒ การพิจารณาคดีให้กระทำโดยเปิดเผยเว้นแต่กฎหมายจะบัญญัติไว้เป็นอย่างอื่น"
    )
    assert _split(thai_digits, "th") == ["1", "2"]

    pasal_ayat = (
        "Pasal 1 Pengertian. Pengadilan adalah lembaga peradilan menurut undang-undang ini dan independen.\n"
        "Ayat (1) Pengadilan memeriksa perkara secara terbuka untuk umum kecuali ditentukan lain."
    )
    pasal_nums = _split(pasal_ayat, "id")
    assert pasal_nums[0] == "1"

    khoan = (
        "Khoản 1. Phạm vi điều chỉnh của luật này được quy định như sau đây cho toàn quốc.\n"
        "Khoản 2. Đối tượng áp dụng bao gồm cơ quan, tổ chức, cá nhân liên quan đến luật này."
    )
    assert _split(khoan, "vi") == ["1", "2"]

    ja_kou = (
        "第一項 この法律は、裁判所の独立を保障することを目的とする。公開の法廷で行う。\n"
        "第二項 裁判は公開の法廷で行う。ただし法律に特別の定めがある場合はこの限りでない。"
    )
    assert _split(ja_kou, "ja") == ["1", "2"]

    ko_hang = (
        "제1항 이 법은 법원의 독립을 보장함을 목적으로 한다. 공개로 심리한다.\n"
        "제2항 이 법에서 사용하는 용어의 뜻은 다음과 같다. 법원은 공개로 심리한다."
    )
    assert _split(ko_hang, "ko") == ["1", "2"]

    zh_kuan = (
        "第一款 为了保障妇女的合法权益，促进男女平等和妇女全面发展，制定本法。\n"
        "第二款 妇女在政治、经济、文化、社会和家庭生活等各方面享有平等权利。"
    )
    assert _split(zh_kuan, "zh") == ["1", "2"]

    th_wara = (
        "วรรค ๑ ศาลเป็นองค์กรตุลาการตามพระราชบัญญัตินี้และมีความเป็นอิสระในการพิจารณาพิพากษา\n"
        "วรรค ๒ การพิจารณาคดีให้กระทำโดยเปิดเผยเว้นแต่กฎหมายจะบัญญัติไว้เป็นอย่างอื่น"
    )
    assert _split(th_wara, "th") == ["1", "2"]

    ar_faqra = (
        "الفقرة 1 المحكمة جهة قضائية مستقلة وفق هذا القانون وتصدر أحكامها مسببة وفق أحكامه.\n"
        "الفقرة 2 تنعقد المحكمة علنا وتصدر أحكامها مسببة إلا إذا قرر القانون خلاف ذلك."
    )
    assert _split(ar_faqra, "ar") == ["1", "2"]

    rules = (
        "Rule 1 Short title. These Rules may be cited as the Court of Appeal Rules 2020 of the Realm.\n"
        "Rule 10 Interpretation. In these Rules court means the Court of Appeal established by the Act."
    )
    assert _split(rules, "en") == ["1", "10"]

    regs = (
        "Regulation 1 Citation. These Regulations may be cited as the Customs Import Regulations 2018.\n"
        "Regulation 2 Interpretation. In these Regulations Board means the Board established under the Act."
    )
    assert _split(regs, "en") == ["1", "2"]

    sched = (
        "Schedule 1 Offences. The offences listed in this Schedule are indictable offences under this Act.\n"
        "Schedule 2 Penalties. The penalties listed in this Schedule apply to the offences in Schedule 1."
    )
    assert _split(sched, "en") == ["1", "2"]

    order = (
        "Order 1 Citation. This Order may be cited as the Emergency Powers Order 2020 of the Realm.\n"
        "Order 2 Interpretation. In this Order Minister means the Minister responsible for home affairs."
    )
    assert _split(order, "en") == ["1", "2"]

    kidogo = (
        "Kifungu kidogo (1) Mahakama ni chombo huru cha mahakama chini ya sheria hii na itasikiliza hadharani.\n"
        "Kifungu kidogo (2) Kesi zitasikilizwa hadharani isipokuwa sheria itoe vinginevyo katika kifungu hiki."
    )
    assert _split(kidogo, "sw") == ["1", "2"]

    act_no = (
        "No. 1 of 2020 Short title. This Act may be cited as the Finance Act 2020 of the Realm.\n"
        "No. 2 of 2020 Interpretation. In this Act Minister means the Minister of Finance."
    )
    assert split_structured_units(act_no, language="en") == []

    annex = (
        "Annex 1 Definitions. Court means a court of record under this Act and includes a tribunal.\n"
        "Annex 2 Procedure. The court shall sit in public except as this Act otherwise provides."
    )
    assert _split(annex, "en") == ["1", "2"]

    annexe_fr = (
        "Annexe 1 Objet. La présente loi fixe les règles applicables sur tout le territoire national.\n"
        "Annexe 2 Champ. Elle s'applique sur tout le territoire national sans exception aucune."
    )
    assert _split(annexe_fr, "fr") == ["1", "2"]

    anlage = (
        "Anlage 1 Begriffsbestimmungen. Das Gericht ist ein unabhängiges Organ nach diesem Gesetz.\n"
        "Anlage 2 Verfahren. Die Verhandlung ist öffentlich, soweit das Gesetz nichts anderes bestimmt."
    )
    assert _split(anlage, "de") == ["1", "2"]

    anexo = (
        "Anexo I A presente lei estabelece as regras aplicáveis em todo o território nacional.\n"
        "Anexo II O disposto na presente lei aplica-se às pessoas singulares e colectivas."
    )
    assert _split(anexo, "pt") == ["I", "II"]

    livre = (
        "Livre I Dispositions générales. La présente loi fixe les règles applicables sur tout le territoire.\n"
        "Livre II Dispositions pénales. Les infractions sont punies conformément au code pénal en vigueur."
    )
    lv = split_structured_units(livre, language="fr")
    assert [u.kind for u in lv] == ["part", "part"]
    assert [u.number for u in lv] == ["I", "II"]

    subsection = (
        "Subsection 1 Definitions. Court means a court of record under this Act and includes a tribunal.\n"
        "Subsection 2 Procedure. The court shall sit in public except as this Act otherwise provides."
    )
    assert _split(subsection, "en") == ["1", "2"]

    recital = (
        "Recital (1) The Union is founded on the values of respect for human dignity and of freedom.\n"
        "Recital (2) The Member States have agreed to the following provisions of this Regulation."
    )
    assert _split(recital, "en") == ["1", "2"]

    vu_cite = (
        "Vu l'article 1 de la Constitution;\n"
        "Vu l'article 2 de la loi n° 65-51 du 19 juillet 1965;"
    )
    assert split_structured_units(vu_cite, language="fr") == []

    ordinance = (
        "Ordinance 1 Short title. This Ordinance may be cited as the Public Health Ordinance 2019.\n"
        "Ordinance 2 Interpretation. In this Ordinance Board means the Board established under section 3."
    )
    assert _split(ordinance, "en") == ["1", "2"]

    bylaw = (
        "By-law 1 Short title. These By-laws may be cited as the Market By-laws 2018 of the City.\n"
        "By-law 2 Interpretation. In these By-laws Council means the municipal council of the city."
    )
    assert _split(bylaw, "en") == ["1", "2"]

    decreto = (
        "Decreto 1 Objeto. La presente ley fija las reglas aplicables en todo el territorio nacional.\n"
        "Decreto 2 Ámbito. Se aplica en todo el territorio nacional a las personas físicas y jurídicas."
    )
    assert _split(decreto, "es") == ["1", "2"]

    punto = (
        "Punto 1. La presente ley fija las reglas aplicables en todo el territorio nacional sin excepción.\n"
        "Punto 2. Se aplica en todo el territorio nacional a las personas físicas y jurídicas."
    )
    assert _split(punto, "es") == ["1", "2"]

    directive = (
        "Directive 1 Citation. This Directive may be cited as the Data Protection Directive 2016.\n"
        "Directive 2 Scope. This Directive applies to the processing of personal data in the Union."
    )
    assert _split(directive, "en") == ["1", "2"]

    subpara = (
        "Sub-paragraph (1) This Act may be cited as the Interpretation Act 2020 of the Realm.\n"
        "Sub-paragraph (2) In this Act court means a court of record under this Act."
    )
    assert _split(subpara, "en") == ["1", "2"]

    proclamation = (
        "Proclamation 1 Citation. This Proclamation may be cited as the Emergency Proclamation 2020.\n"
        "Proclamation 2 Scope. This Proclamation applies throughout the national territory of the State."
    )
    assert _split(proclamation, "en") == ["1", "2"]

    circular = (
        "Circular 1 Purpose. This Circular sets out the procedures applicable to all public officers.\n"
        "Circular 2 Application. This Circular applies to all ministries and departments of government."
    )
    assert _split(circular, "en") == ["1", "2"]

    aviso = (
        "Aviso 1 Objeto. El presente aviso fija las reglas aplicables en todo el territorio nacional.\n"
        "Aviso 2 Ámbito. Se aplica en todo el territorio nacional a las personas físicas y jurídicas."
    )
    assert _split(aviso, "es") == ["1", "2"]

    bekannt = (
        "Bekanntmachung 1 Zweck. Diese Bekanntmachung enthält die im gesamten Bundesgebiet geltenden Regeln.\n"
        "Bekanntmachung 2 Verfahren. Die Verhandlung ist öffentlich, soweit das Gesetz nichts anderes bestimmt."
    )
    assert _split(bekannt, "de") == ["1", "2"]

    paragraph = (
        "Paragraph 1 Definitions. Court means a court of record under this Act and includes a tribunal.\n"
        "Paragraph 2 Procedure. The court shall sit in public except as this Act otherwise provides."
    )
    assert _split(paragraph, "en") == ["1", "2"]

    clan_ascii = (
        "Clan 1. Sud je organ sudske vlasti prema ovom zakonu i odlučuje neovisno u postupku.\n"
        "Clan 12. Postupak pred sudom je javan osim ako zakon ne odredi drukčije u ovom članku."
    )
    assert _split(clan_ascii, "hr") == ["1", "12"]

    ordin = (
        "ORDIN 1 Prezenta lege stabilește regulile aplicabile pe întreg teritoriul național.\n"
        "ORDIN 2 Dispozițiile prezentei legi se aplică persoanelor fizice și juridice."
    )
    assert _split(ordin, "ro") == ["1", "2"]

    url_chrome = normalize_legal_text("https://www.example.gov/laws/act-1\nArticle 1 Object. The present Act sets the applicable rules.\nArticle 2 Scope. It applies throughout the national territory.")
    assert "https://" not in url_chrome
    assert "Article 1" in url_chrome

    qarar = (
        "قرار 1 المحكمة جهة قضائية مستقلة وفق هذا القانون وتصدر أحكامها مسببة وفق أحكامه.\n"
        "قرار 12 تنعقد المحكمة علنا وتصدر أحكامها مسببة إلا إذا قرر القانون خلاف ذلك."
    )
    assert _split(qarar, "ar") == ["1", "12"]

    compacted_art = "Art. 10 Art. 11"
    compacted_nums = [
        u.number
        for u in segment_exclusive(compacted_art, language="fr")
        if u.kind == "article"
    ]
    assert compacted_nums == ["10", "11"]

    dashy = normalize_legal_text("Art.\u00a01\u2014 Objet. La présente loi fixe les règles.\nArt. 2 Champ. Elle s'applique partout.")
    assert "\u00a0" not in dashy and "\u2014" not in dashy
    assert _split(dashy, "fr") == ["1", "2"]

    decree = (
        "Decree 1 Citation. This Decree may be cited as the Public Health Decree 2019 of the State.\n"
        "Decree 2 Scope. This Decree applies throughout the national territory of the State."
    )
    assert _split(decree, "en") == ["1", "2"]

    gazette_hdr = normalize_legal_text(
        "STATUTORY INSTRUMENTS\n"
        "الجريدة الرسمية\n"
        "Skip to main content Home Mail\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "STATUTORY" not in gazette_hdr
    assert "الجريدة" not in gazette_hdr
    assert "Skip to main content" not in gazette_hdr
    assert _split(gazette_hdr, "en") == ["1", "2"]

    exec_order = (
        "Executive Order 1 Citation. This Executive Order may be cited as the Emergency Powers Order 2020.\n"
        "Executive Order 2 Scope. This Order applies throughout the national territory of the State."
    )
    assert _split(exec_order, "en") == ["1", "2"]

    pres_decree = (
        "Presidential Decree 1 Citation. This Decree may be cited as the Public Health Decree 2019.\n"
        "Presidential Decree 2 Scope. This Decree applies throughout the national territory of the State."
    )
    assert _split(pres_decree, "en") == ["1", "2"]

    og = normalize_legal_text(
        "Official Gazette\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "Official Gazette" not in og
    assert _split(og, "en") == ["1", "2"]

    jo = normalize_legal_text(
        "Journal officiel\n"
        "Bundesgesetzblatt\n"
        "Diário da República\n"
        "官報\n"
        "ราชกิจจานุเบกษา\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "Journal officiel" not in jo
    assert "Bundesgesetzblatt" not in jo
    assert "Diário da República" not in jo
    assert "官報" not in jo
    assert "ราชกิจจานุเบกษา" not in jo
    cite = normalize_legal_text(
        "Journal officiel n° 12 du 1er janvier 2020 portant loi relative aux tribunaux.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "Journal officiel nr. 12" in cite
    assert _split(jo, "en") == ["1", "2"]

    latam = normalize_legal_text(
        "Gaceta Oficial\n"
        "Diário Oficial da União\n"
        "Narodne novine\n"
        "Magyar Közlöny\n"
        "Federal Negarit Gazette\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "Gaceta Oficial" not in latam
    assert "Diário Oficial" not in latam
    assert "Narodne novine" not in latam
    assert "Magyar Közlöny" not in latam
    assert "Negarit" not in latam
    assert _split(latam, "en") == ["1", "2"]

    gaz = normalize_legal_text(
        "The Uganda Gazette\n"
        "Bulletin Officiel\n"
        "Warta Kerajaan\n"
        "الوقائع المصرية\n"
        "Công báo\n"
        "El Peruano\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "Uganda Gazette" not in gaz
    assert "Bulletin Officiel" not in gaz
    assert "Warta Kerajaan" not in gaz
    assert "الوقائع" not in gaz
    assert "Công báo" not in gaz
    assert "El Peruano" not in gaz
    assert _split(gaz, "en") == ["1", "2"]
    gaz_cite = normalize_legal_text(
        "Published in the Kenya Gazette on 1 January 2020 as a special issue.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "Kenya Gazette" in gaz_cite

    besluit = (
        "Besluit 1 Begripsbepalingen. De rechter is een onafhankelijk orgaan volgens deze wet.\n"
        "Besluit 2 Procedure. De behandeling is openbaar tenzij de wet anders bepaalt in bijzondere gevallen."
    )
    assert _split(besluit, "nl") == ["1", "2"]

    ordonnanta = (
        "ORDONANŢĂ 1 Prezenta lege stabilește regulile aplicabile pe întreg teritoriul național.\n"
        "ORDONANȚĂ 2 Dispozițiile prezentei legi se aplică persoanelor fizice și juridice."
    )
    assert _split(ordonnanta, "ro") == ["1", "2"]

    regeling = (
        "Regeling 1 Begripsbepalingen. De rechter is een onafhankelijk orgaan volgens deze wet.\n"
        "Regeling 2 Procedure. De behandeling is openbaar tenzij de wet anders bepaalt in bijzondere gevallen."
    )
    assert _split(regeling, "nl") == ["1", "2"]

    odluka = (
        "Odluka 1 Opće odredbe. Sud je organ sudske vlasti prema ovom zakonu i odlučuje neovisno.\n"
        "Odluka 2 Postupak. Postupak pred sudom je javan osim ako zakon ne odredi drukčije."
    )
    assert _split(odluka, "hr") == ["1", "2"]

    hotarare = (
        "HOTĂRÂRE 1 Prezenta lege stabilește regulile aplicabile pe întreg teritoriul național.\n"
        "HOTĂRÂRE 2 Dispozițiile prezentei legi se aplică persoanelor fizice și juridice."
    )
    assert _split(hotarare, "ro") == ["1", "2"]

    resolucao = (
        "Resolução 1 A presente lei estabelece as regras aplicáveis em todo o território nacional.\n"
        "Portaria 2 O disposto na presente lei aplica-se às pessoas singulares e colectivas."
    )
    assert _split(resolucao, "pt") == ["1", "2"]

    ukaz = (
        "Указ 1 Суд является органом судебной власти в соответствии с настоящим законом и независим.\n"
        "Указ 2 Разбирательство в суде является открытым, если законом не предусмотрено иное."
    )
    assert _split(ukaz, "ru") == ["1", "2"]

    marsum = (
        "مرسوم 1 المحكمة جهة قضائية مستقلة وفق هذا القانون وتصدر أحكامها مسببة وفق أحكامه.\n"
        "مرسوم 2 تنعقد المحكمة علنا وتصدر أحكامها مسببة إلا إذا قرر القانون خلاف ذلك."
    )
    assert _split(marsum, "ar") == ["1", "2"]

    decreto_lei = (
        "Decreto-Lei 1 A presente lei estabelece as regras aplicáveis em todo o território nacional.\n"
        "Decreto-Lei 2 O disposto na presente lei aplica-se às pessoas singulares e colectivas."
    )
    assert _split(decreto_lei, "pt") == ["1", "2"]

    deliberacao = (
        "Deliberação 1 A presente lei estabelece as regras aplicáveis em todo o território nacional.\n"
        "Deliberação 2 O disposto na presente lei aplica-se às pessoas singulares e colectivas."
    )
    assert _split(deliberacao, "pt") == ["1", "2"]

    kodeks = (
        "Kodeks 1 Przepisy ogólne. Sąd jest organem władzy sądowniczej zgodnie z niniejszą ustawą.\n"
        "Kodeks 2 Postępowanie. Rozprawa przed sądem jest jawna, chyba że ustawa stanowi inaczej."
    )
    kd = split_structured_units(kodeks, language="pl")
    assert [u.number for u in kd] == ["1", "2"]

    ordonnance = (
        "Ordonnance 1 Objet. La présente loi fixe les règles applicables sur tout le territoire national.\n"
        "Règlement 2 Champ. Elle s'applique sur tout le territoire national sans exception aucune."
    )
    assert _split(ordonnance, "fr") == ["1", "2"]

    decret_loi = (
        "Décret-loi 1 Objet. La présente loi fixe les règles applicables sur tout le territoire national.\n"
        "Décision 2 Champ. Elle s'applique sur tout le territoire national sans exception aucune."
    )
    assert _split(decret_loi, "fr") == ["1", "2"]

    verordnung = (
        "Verordnung 1 Zweck. Dieses Gesetz enthält die im gesamten Bundesgebiet geltenden Regeln.\n"
        "Erlass 2 Verfahren. Die Verhandlung ist öffentlich, soweit das Gesetz nichts anderes bestimmt."
    )
    assert _split(verordnung, "de") == ["1", "2"]

    accent_fold = (
        "Árticle 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Séctión 2 Scope. It applies throughout the national territory without exception."
    )
    assert _split(accent_fold, "en") == ["1", "2"]

    greek_tonos = (
        "Άρθρο 1 Ορισμοί. Το δικαστήριο είναι ανεξάρτητο δικαστικό όργανο σύμφωνα με τον παρόντα νόμο.\n"
        "Άρθρο 2 Διαδικασία. Το δικαστήριο συνεδριάζει δημόσια εκτός αν ο νόμος ορίζει διαφορετικά."
    )
    assert _split(greek_tonos, "el") == ["1", "2"]

    hyphen_join = normalize_legal_text(
        "Article 1 Object. The present Act sets the appli-\ncable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "appli-cable" not in hyphen_join
    assert "applicable" in hyphen_join
    assert _split(hyphen_join, "en") == ["1", "2"]

    bidi_ar = (
        "\u200fالمادة\u200e 1 المحكمة جهة قضائية مستقلة وفق هذا القانون وتصدر أحكامها مسببة.\n"
        "\u200fالمادة\u200e 2 تنعقد المحكمة علنا إلا إذا قرر القانون خلاف ذلك."
    )
    bidi_clean = normalize_legal_text(bidi_ar)
    assert "\u200f" not in bidi_clean and "\u200e" not in bidi_clean
    assert _split(bidi_clean, "ar") == ["1", "2"]

    tashkeel = (
        "الْمَادَّةُ 1 المحكمة جهة قضائية مستقلة وفق هذا القانون وتصدر أحكامها مسببة.\n"
        "الْمَادَّةُ 2 تنعقد المحكمة علنا إلا إذا قرر القانون خلاف ذلك."
    )
    tash_clean = normalize_legal_text(tashkeel)
    assert "\u064e" not in tash_clean
    assert _split(tash_clean, "ar") == ["1", "2"]

    blanks = normalize_legal_text(
        "Article 1 Object. The present Act sets the applicable rules on ____ the territory.\n"
        "Article 2 Scope .......... It applies throughout the national territory without exception."
    )
    assert "____" not in blanks
    assert "........" not in blanks
    assert _split(blanks, "en") == ["1", "2"]

    toc = normalize_legal_text(
        "Page 1 of 12\n"
        "Table of contents\n"
        "Inhaltsverzeichnis\n"
        "목차\n"
        "- 3 -\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "Page 1" not in toc
    assert "Table of contents" not in toc
    assert "Inhaltsverzeichnis" not in toc
    assert "목차" not in toc
    assert "- 3 -" not in toc
    assert _split(toc, "en") == ["1", "2"]

    running = normalize_legal_text(
        "Act 8 of 2018 Page 3\n"
        "Page 4 Act 8 of 2018\n"
        "l Page 1\n"
        "Section Page\n"
        "Ми використовуємо cookies, щоб забезпечити роботу авторизованих користувачів.\n"
        "Продовжуючи відвідування сайту, Ви погоджуєтесь на використання cookies та Політики конфіденційності\n"
        "Subscribe to our newsletter\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "Page 3" not in running
    assert "Page 4" not in running
    assert "cookies" not in running.lower()
    assert "newsletter" not in running.lower()
    assert _split(running, "en") == ["1", "2"]

    oath = normalize_legal_text(
        "The Auditor General shall take and subscribe to the prescribed oaths before assuming office.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "subscribe to the prescribed oaths" in oath
    assert _split(oath, "en") == ["1", "2"]

    footer = normalize_legal_text(
        "www.example.gov/laws\n"
        "Downloaded from www.example.gov on 1 January 2020\n"
        "p. 12\n"
        "стр. 8\n"
        "Email: info@example.gov\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "www.example.gov" not in footer
    assert "Downloaded from" not in footer
    assert "p. 12" not in footer
    assert "стр. 8" not in footer
    assert "info@example.gov" not in footer
    assert _split(footer, "en") == ["1", "2"]

    bom16 = normalize_legal_text(
        "ÿþArticle 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert not bom16.startswith("ÿþ")
    assert _split(bom16, "en") == ["1", "2"]

    artigo_no = (
        "Artigo n.o 1 A presente lei estabelece as regras aplicáveis em todo o território nacional.\n"
        "Artigo n.o 2 O disposto na presente lei aplica-se às pessoas singulares e colectivas."
    )
    assert _split(normalize_legal_text(artigo_no), "pt") == ["1", "2"]

    trad_zh = (
        "第一條 為保障人民之權利，促進社會之福祉，特制定本法。\n"
        "第十二條 本法之主管機關為司法院，並監督各級法院。"
    )
    assert _split(trad_zh, "zh") == ["1", "12"]

    spaced_zh = (
        "第 1 條 為保障人民之權利，促進社會之福祉，特制定本法。\n"
        "第 2 條 本法之主管機關為司法院。"
    )
    assert _split(spaced_zh, "zh") == ["1", "2"]

    circled = (
        "① この法律は、裁判所の独立を保障することを目的とする。公開の法廷で行う。\n"
        "② 裁判は公開の法廷で行う。ただし法律に特別の定めがある場合はこの限りでない。"
    )
    assert _split(circled, "ja") == ["1", "2"]

    zh_enum = (
        "一、为了保障妇女的合法权益，促进男女平等和妇女全面发展，制定本法。\n"
        "二、妇女在政治、经济、文化、社会和家庭生活等各方面享有平等权利。"
    )
    assert _split(zh_enum, "zh") == ["1", "2"]

    black_circled = (
        "❶ この法律は、裁判所の独立を保障することを目的とする。公開の法廷で行う。\n"
        "❷ 裁判は公開の法廷で行う。ただし法律に特別の定めがある場合はこの限りでない。"
    )
    assert _split(black_circled, "ja") == ["1", "2"]

    zh_paren = (
        "（一）为了保障妇女的合法权益，促进男女平等和妇女全面发展，制定本法。\n"
        "（二）妇女在政治、经济、文化、社会和家庭生活等各方面享有平等权利。"
    )
    assert _split(zh_paren, "zh") == ["1", "2"]

    ko_ga = (
        "가. 이 법은 법원의 독립을 보장함을 목적으로 한다. 공개로 심리한다.\n"
        "나. 이 법에서 사용하는 용어의 뜻은 다음과 같다. 법원은 공개로 심리한다."
    )
    assert _split(ko_ga, "ko") == ["1", "2"]

    zh_digit_enum = (
        "1、为了保障妇女的合法权益，促进男女平等和妇女全面发展，制定本法。\n"
        "2、妇女在政治、经济、文化、社会和家庭生活等各方面享有平等权利。"
    )
    assert _split(zh_digit_enum, "zh") == ["1", "2"]

    ar_abjad = (
        "أ- المحكمة جهة قضائية مستقلة وفق هذا القانون وتصدر أحكامها مسببة وفق أحكامه.\n"
        "ب- تنعقد المحكمة علنا وتصدر أحكامها مسببة إلا إذا قرر القانون خلاف ذلك."
    )
    assert _split(ar_abjad, "ar") == ["1", "2"]

    he_alef = (
        "א. בית המשפט הוא רשות שופטת עצמאית לפי חוק זה וישפוט בפומבי לפי הוראות החוק.\n"
        "ב. הדיון בבית המשפט יהיה פומבי זולת אם נקבע אחרת בחוק זה במפורש."
    )
    assert _split(he_alef, "he") == ["1", "2"]

    hi_enum = (
        "१. न्यायालय इस अधिनियम के अधीन स्वतंत्र न्यायिक अंग है और खुली अदालत में सुनवाई करता है।\n"
        "२. न्यायालय लोक रूप से मामलों की सुनवाई करेगा जब तक कि कानून अन्यथा न कहे।"
    )
    assert _split(hi_enum, "hi") == ["1", "2"]

    ru_ab = (
        "а) Суд является органом судебной власти в соответствии с настоящим законом и независим.\n"
        "б) Разбирательство в суде является открытым, если законом не предусмотрено иное."
    )
    assert _split(ru_ab, "ru") == ["1", "2"]

    el_ab = (
        "α) Το δικαστήριο είναι ανεξάρτητο δικαστικό όργανο σύμφωνα με τον παρόντα νόμο.\n"
        "β) Το δικαστήριο συνεδριάζει δημόσια εκτός αν ο νόμος ορίζει διαφορετικά."
    )
    assert _split(el_ab, "el") == ["1", "2"]

    latin_ab = (
        "a) Court means a court of record under this Act and includes a tribunal of competent jurisdiction.\n"
        "b) The court shall sit in public except as this Act otherwise provides in writing."
    )
    assert _split(latin_ab, "en") == ["1", "2"]

    latin_paren = (
        "(a) Court means a court of record under this Act and includes a tribunal of competent jurisdiction.\n"
        "(b) The court shall sit in public except as this Act otherwise provides in writing."
    )
    assert _split(latin_paren, "en") == ["1", "2"]

    latin_roman = (
        "i. Court means a court of record under this Act and includes a tribunal of competent jurisdiction.\n"
        "ii. The court shall sit in public except as this Act otherwise provides in writing."
    )
    assert _split(latin_roman, "en") == ["1", "2"]

    num_paren = (
        "1) Court means a court of record under this Act and includes a tribunal of competent jurisdiction.\n"
        "2) The court shall sit in public except as this Act otherwise provides in writing."
    )
    assert _split(num_paren, "en") == ["1", "2"]

    num_wrap = (
        "(1) Court means a court of record under this Act and includes a tribunal of competent jurisdiction.\n"
        "(2) The court shall sit in public except as this Act otherwise provides in writing."
    )
    assert _split(num_wrap, "en") == ["1", "2"]

    num_ord = (
        "1° Il tribunale è organo giurisdizionale indipendente secondo questa legge e giudica in pubblico.\n"
        "2° Il tribunale giudica in udienza pubblica salvo diversa disposizione di legge."
    )
    assert _split(num_ord, "it") == ["1", "2"]

    num_dotdash = (
        "1.- La presente ley fija las reglas aplicables en todo el territorio nacional sin excepción.\n"
        "2.- Se aplica en todo el territorio nacional a las personas físicas y jurídicas."
    )
    assert _split(num_dotdash, "es") == ["1", "2"]

    fw_jp = normalize_legal_text(
        "１）この法律は、裁判所の独立を保障することを目的とする。公開の法廷で行う。\n"
        "２）裁判は公開の法廷で行う。ただし法律に特別の定めがある場合はこの限りでない。"
    )
    assert _split(fw_jp, "ja") == ["1", "2"]

    colon_list = (
        "1: Court means a court of record under this Act and includes a tribunal of competent jurisdiction.\n"
        "2: The court shall sit in public except as this Act otherwise provides in writing."
    )
    assert _split(colon_list, "en") == ["1", "2"]

    bullets = (
        "• Court means a court of record under this Act and includes a tribunal of competent jurisdiction.\n"
        "• The court shall sit in public except as this Act otherwise provides in writing."
    )
    assert _split(bullets, "en") == ["1", "2"]

    dash_num = normalize_legal_text(
        "– 1 Court means a court of record under this Act and includes a tribunal of competent jurisdiction.\n"
        "– 2 The court shall sit in public except as this Act otherwise provides in writing."
    )
    assert _split(dash_num, "en") == ["1", "2"]

    stars = (
        "* Court means a court of record under this Act and includes a tribunal of competent jurisdiction.\n"
        "* The court shall sit in public except as this Act otherwise provides in writing."
    )
    assert _split(stars, "en") == ["1", "2"]

    in_this_act = (
        "1. In this Act court means a court of record under this Act and includes a tribunal.\n"
        "2. In this Act Board means the Board established by section 3 of this Act."
    )
    assert _split(in_this_act, "en") == ["1", "2"]

    au_short = (
        "1 Short title This Act may be cited as the Acts Interpretation Act 1901 of the Commonwealth.\n"
        "11 Acts may be altered etc. in same session of the Parliament of the Commonwealth."
    )
    assert "1" in _split(au_short, "en") and "11" in _split(au_short, "en")

    glued_sub = (
        "105. (1) Subject to the provision of this section the national court shall sit in public.\n"
        "118. (1) Any reference in this Chapter to the national interpretation shall apply."
    )
    assert _split(glued_sub, "en") == ["105", "118"]

    bn_danda = (
        "১। আদালত এই আইনের অধীন একটি স্বাধীন বিচারিক অঙ্গ এবং জনসমক্ষে শুনানি করে।\n"
        "২। আদালত জনসমক্ষে মামলার শুনানি করিবে যদি না আইন অন্যথা বলে।"
    )
    assert _split(bn_danda, "bn") == ["1", "2"]

    guillemet = (
        "« Article 1 » Objet. La présente loi fixe les règles applicables sur tout le territoire national.\n"
        "« Article 2 » Champ. Elle s'applique sur tout le territoire national sans exception aucune."
    )
    assert _split(guillemet, "fr") == ["1", "2"]

    ocr_junk = normalize_legal_text(
        "105. (1) Subject to the provision of this section, the ~$P$;;Z: national court shall sit in public.\n"
        "118. (1) Any reference in this Chapter to the national interpretation shall apply."
    )
    assert "~$" not in ocr_junk
    assert _split(ocr_junk, "en") == ["105", "118"]

    md_bold = normalize_legal_text(
        "**Article 1** Definitions. Court means a court of record under this Act and includes a tribunal.\n"
        "__Article 2__ Procedure. The court shall sit in public except as this Act otherwise provides."
    )
    assert "**" not in md_bold and "__Article" not in md_bold
    assert _split(md_bold, "en") == ["1", "2"]

    angle_q = (
        "‹Article 1› Definitions. Court means a court of record under this Act and includes a tribunal.\n"
        "‹Article 2› Procedure. The court shall sit in public except as this Act otherwise provides."
    )
    assert _split(angle_q, "en") == ["1", "2"]

    wiki = normalize_legal_text(
        "'''Article 1''' Definitions. Court means a court of record under this Act and includes a tribunal.\n"
        "== Article 2 ==\n"
        "Procedure. The court shall sit in public except as this Act otherwise provides."
    )
    assert "'''" not in wiki
    assert "==" not in wiki
    assert _split(wiki, "en") == ["1", "2"]

    controls = normalize_legal_text(
        "Article 1 Object.\x07 The present Act sets the applicable\ufffd rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "\x07" not in controls and "\ufffd" not in controls
    assert _split(controls, "en") == ["1", "2"]

    cyprus_issue = normalize_legal_text(
        "Αριθμός 2822\n"
        "Αρ. 212/2014.\n"
        "Aριθμός 2823\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "Αριθμός" not in cyprus_issue
    assert "Αρ. 212" not in cyprus_issue
    assert "Aριθμός" not in cyprus_issue
    assert _split(cyprus_issue, "en") == ["1", "2"]

    issue_no = normalize_legal_text(
        "Nº 2822\n"
        "Broj 1631\n"
        "Número 2822\n"
        "№ 12\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "2822" not in issue_no.split("Article")[0]
    assert "Broj" not in issue_no
    assert "№ 12" not in issue_no
    assert _split(issue_no, "en") == ["1", "2"]
    keep_act = normalize_legal_text(
        "No. 1 of 2020 Short title. This Act may be cited as the Finance Act 2020 of the Realm.\n"
        "No. 2 of 2020 Interpretation. In this Act Minister means the Minister of Finance."
    )
    assert "No. 1 of 2020" in keep_act or "nr. 1 of 2020" in keep_act.lower()

    dates = normalize_legal_text(
        "Copyright © 2020\n"
        "12/01/2020\n"
        "1 January 2020\n"
        "End of document\n"
        "---\n"
        "Done at Brussels, 12 January 2020.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "Copyright" not in dates
    assert "12/01/2020" not in dates
    assert "1 January 2020" not in dates.split("Done")[0]
    assert "End of document" not in dates
    assert "---" not in dates.split("Article")[0]
    assert "Done at Brussels" in dates
    assert _split(dates, "en") == ["1", "2"]

    seals = normalize_legal_text(
        "L.S.\n"
        "[SEAL]\n"
        "God Save the King\n"
        "Published\n"
        "Given under my hand this 12th day of January 2020.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "L.S." not in seals
    assert "[SEAL]" not in seals
    assert "God Save the King" not in seals
    assert "Published" not in seals.split("Given")[0]
    assert "Given under my hand" in seals
    assert _split(seals, "en") == ["1", "2"]

    hebrew_perek = (
        "פרק א' :פרשנות ותחולה בית המשפט הוא רשות שופטת עצמאית לפי חוק זה וישפוט בפומבי.\n"
        "פרק ב' :ביצוע הדיון בבית המשפט יהיה פומבי זולת אם נקבע אחרת בחוק זה."
    )
    assert _split(hebrew_perek, "he") == ["1", "2"]

    hebrew_siman = (
        "סימן א' :פנקסי שמן בית המשפט הוא רשות שופטת עצמאית לפי חוק זה וישפוט בפומבי.\n"
        "סימן ב' :מפקחים הדיון בבית המשפט יהיה פומבי זולת אם נקבע אחרת בחוק זה."
    )
    assert _split(hebrew_siman, "he") == ["1", "2"]

    ar_mulhaq = (
        "ملحق 1 المحكمة جهة قضائية مستقلة وفق هذا القانون وتصدر أحكامها مسببة وفق أحكامه.\n"
        "ملحق 2 تنعقد المحكمة علنا وتصدر أحكامها مسببة إلا إذا قرر القانون خلاف ذلك."
    )
    assert _split(ar_mulhaq, "ar") == ["1", "2"]

    ar_mulhaq_ocr = (
        "ملحق رقم )(5 المحكمة جهة قضائية مستقلة وفق هذا القانون وتصدر أحكامها مسببة وفق أحكامه.\n"
        "ملحق رقم )(13 تنعقد المحكمة علنا وتصدر أحكامها مسببة إلا إذا قرر القانون خلاف ذلك."
    )
    assert _split(ar_mulhaq_ocr, "ar") == ["5", "13"]

    hebrew_dot = (
        ".1מטרת החוק היא להסדיר את פעולת בתי המשפט בישראל באופן עצמאי ופומבי לפי חוק זה.\n"
        ".2הדיון בבית המשפט יהיה פומבי זולת אם נקבע אחרת בחוק זה במפורש."
    )
    assert _split(hebrew_dot, "he") == ["1", "2"]

    hebrew_seif_letter = (
        "סעיף א' בית המשפט הוא רשות שופטת עצמאית לפי חוק זה וישפוט בפומבי בכל עת.\n"
        "סעיף ב' הדיון בבית המשפט יהיה פומבי זולת אם נקבע אחרת בחוק זה במפורש."
    )
    assert _split(hebrew_seif_letter, "he") == ["1", "2"]

    hebrew_tosefet = (
        "תוספת ראשונה הטפסים המצורפים לחוק זה הם חלק בלתי נפרד ממנו ויש למלאם במלואם כנדרש.\n"
        "תוספת שניה רשימת העבירות המנויות להלן תחול על הליכים לפי חוק זה במפורש."
    )
    assert _split(hebrew_tosefet, "he") == ["1", "2"]

    hebrew_helek = (
        "חלק א' הוראות כלליות בית המשפט הוא רשות שופטת עצמאית לפי חוק זה וישפוט בפומבי.\n"
        "חלק ב' סדרי דין הדיון בבית המשפט יהיה פומבי זולת אם נקבע אחרת בחוק זה במפורש."
    )
    assert _split(hebrew_helek, "he") == ["1", "2"]

    ar_dash = (
        "المادة -1- تختص المحكمة بالنظر في المنازعات الناشئة عن تطبيق هذا القانون وفق أحكامه.\n"
        "المادة -7- ينفذ هذا القانون من تاريخ نشره في الجريدة الرسمية وفق أحكامه."
    )
    assert _split(ar_dash, "ar") == ["1", "7"]

    ar_rtl_paren = (
        "مادة )1( تختص المحكمة بالنظر في المنازعات الناشئة عن تطبيق هذا القانون وفق أحكامه.\n"
        "مادة )2( تنعقد المحكمة علنا وتصدر أحكامها مسببة إلا إذا قرر القانون خلاف ذلك."
    )
    assert _split(ar_rtl_paren, "ar") == ["1", "2"]

    ar_bab = (
        "الباب الأول أحكام عامة تختص المحكمة بالنظر في المنازعات الناشئة عن تطبيق هذا القانون وفق أحكامه.\n"
        "الباب الثاني الإجراءات تنعقد المحكمة علنا وتصدر أحكامها مسببة وفق أحكام هذا القانون."
    )
    assert _split(ar_bab, "ar") == ["1", "2"]

    pua = normalize_legal_text(
        "\ue031\ue02f junk\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert not any(0xE000 <= ord(ch) <= 0xF8FF for ch in pua)
    assert _split(pua, "en") == ["1", "2"]

    cid = normalize_legal_text(
        "D(cid:17)(cid:8)*(cid:14) junk\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "(cid:" not in cid
    assert _split(cid, "en") == ["1", "2"]

    thai_kho = (
        "ข้อ ๑ อัตราดอกเบี้ยเงินกู้กำหนดไว้ดังนี้และให้ใช้บังคับทั่วราชอาณาจักรตามกฎหมายนี้\n"
        "ข้อ ๒ การชำระดอกเบี้ยให้เป็นไปตามหลักเกณฑ์ที่ธนาคารแห่งประเทศไทยกำหนดไว้"
    )
    assert "ข้อ" in normalize_legal_text(thai_kho)
    assert _split(thai_kho, "th") == ["1", "2"]

    amharic = (
        "አንቀጽ ፬ ተተክቷል ። ፍርድ ቤቱ የዳኝነት ሥልጣን አካል ነው በዚህ አዋጅ መሠረት በግልጽ ይፈርዳል።\n"
        "አንቀጽ ፴፩ ተጨምሮ ነባሮቹ አንቀጾች የፍርድ ሂደት በግልጽ ይካሄዳል በዚህ አዋጅ በተደነገገው መሠረት።"
    )
    assert _split(amharic, "am") == ["4", "31"]

    romanian_hot = (
        "HOTĂRÎRE Nr. 267 din 14 martie 1990 privind acordarea unor drepturi personalului din industrie pe tot teritoriul.\n"
        "HOTĂRÎRE nr. 273 din 15 martie 1990 privind pregătirea recensămîntului populaţiei pe tot teritoriul."
    )
    assert _split(romanian_hot, "ro") == ["267", "273"]

    greek_kef = (
        "Κεφάλαιο 1 Γενικές διατάξεις. Το δικαστήριο είναι ανεξάρτητο όργανο κατά τον παρόντα νόμο και δικάζει δημοσίως.\n"
        "Κεφάλαιο 2 Διαδικασία. Η διαδικασία ενώπιον του δικαστηρίου είναι δημόσια εκτός αν ο νόμος ορίζει διαφορετικά."
    )
    assert _split(greek_kef, "el") == ["1", "2"]

    viet_chuong = (
        "Chương 1 Những quy định chung. Tòa án là cơ quan xét xử độc lập theo luật này và xét xử công khai.\n"
        "Chương 2 Thủ tục. Việc xét xử của tòa án được tiến hành công khai trừ trường hợp luật định rõ."
    )
    assert _split(viet_chuong, "vi") == ["1", "2"]

    fa_tabsereh = (
        "تبصره 1 دادگاه مرجع قضایی مستقل طبق این قانون است و احکام خود را مستدل صادر میکند در همه موارد.\n"
        "تبصره 2 رسیدگی در دادگاه علنی است مگر آنکه قانون ترتیب دیگری مقرر کرده باشد به طور صریح."
    )
    assert _split(fa_tabsereh, "fa") == ["1", "2"]

    viet_cite = (
        "Điều 1. Phạm vi điều chỉnh. Luật này quy định về thú y trên toàn lãnh thổ quốc gia và các vùng biển.\n"
        "Điều 27 của Luật này.\n"
        "Điều 2. Đối tượng áp dụng. Tổ chức, cá nhân trong nước và nước ngoài phải tuân thủ luật này."
    )
    assert _split(viet_cite, "vi") == ["1", "2"]

    ua_hyphen = (
        "Стаття 1. Визначення термінів. Цей Закон визначає засади захисту прав споживачів на всій території.\n"
        "Стаття 1-1. Сфера дії цього Закону поширюється на всіх споживачів без винятку на території держави."
    )
    assert _split(ua_hyphen, "uk") == ["1", "1-1"]

    id_bab = (
        "Bab I Ketentuan Umum. Pengadilan adalah lembaga yudisial yang mandiri berdasarkan undang-undang ini dan bersidang secara terbuka.\n"
        "Bab II Tata Cara. Sidang pengadilan bersifat terbuka kecuali undang-undang menentukan lain secara tegas."
    )
    assert [u.kind for u in split_structured_units(id_bab, language="id")] == ["chapter", "chapter"]
    assert _split(id_bab, "id") == ["I", "II"]

    ms_bahagian = (
        "Bahagian I Permulaan. Mahkamah ialah organ kehakiman yang bebas di bawah Akta ini dan bersidang secara terbuka.\n"
        "Bahagian II Tatacara. Mahkamah mendengar kes secara terbuka kecuali Akta ini memperuntukkan sebaliknya."
    )
    assert [u.kind for u in split_structured_units(ms_bahagian, language="ms")] == ["part", "part"]
    assert _split(ms_bahagian, "ms") == ["I", "II"]

    lt_straipsnis = (
        "1 straipsnis. Teismas yra nepriklausoma teisminė institucija pagal šį įstatymą ir nagrinėja bylas viešai visoje valstybėje.\n"
        "2 straipsnis. Teismo posėdžiai yra vieši, jeigu įstatymas nenustato kitaip šioje nuostatoje aiškiai."
    )
    assert _split(lt_straipsnis, "lt") == ["1", "2"]

    zh_zhang = (
        "第一章 总则 为了保障公民的合法权益，促进社会公平正义，根据宪法，制定本法并公布施行。\n"
        "第二章 权利 公民依法享有各项权利并履行相应义务，本法自公布之日起施行于全国。"
    )
    assert [u.kind for u in split_structured_units(zh_zhang, language="zh")] == ["chapter", "chapter"]
    assert _split(zh_zhang, "zh") == ["1", "2"]

    ko_jang = (
        "제1장 총칙 이 법은 법원의 독립을 보장함을 목적으로 한다. 재판은 공개된 법정에서 한다.\n"
        "제2장 절차 재판은 공개된 법정에서 한다. 다만 법률에 특별한 규정이 있는 경우에는 그러하지 아니하다."
    )
    assert _split(ko_jang, "ko") == ["1", "2"]

    ar_kitab = (
        "الكتاب الأول أحكام عامة تختص المحكمة بالنظر في المنازعات الناشئة عن تطبيق هذا القانون وفق أحكامه.\n"
        "الكتاب الثاني الإجراءات تنعقد المحكمة علنا وتصدر أحكامها مسببة وفق أحكام هذا القانون."
    )
    assert _split(ar_kitab, "ar") == ["1", "2"]

    el_meros = (
        "Μέρος 1 Γενικές διατάξεις. Το δικαστήριο είναι ανεξάρτητο όργανο κατά τον παρόντα νόμο και δικάζει δημοσίως.\n"
        "Μέρος 2 Διαδικασία. Η διαδικασία ενώπιον του δικαστηρίου είναι δημόσια εκτός αν ο νόμος ορίζει διαφορετικά."
    )
    assert _split(el_meros, "el") == ["1", "2"]

    ru_razdel = (
        "Раздел I Общие положения. Суд является органом судебной власти согласно настоящему закону и рассматривает дела открыто.\n"
        "Раздел II Производство. Разбирательство в суде открытое, если законом не установлено иное прямо."
    )
    assert _split(ru_razdel, "ru") == ["I", "II"]

    ta_pirivu = (
        "பிரிவு 1 நீதிமன்றம் இச்சட்டத்தின் கீழ் ஒரு சுயாதீன நீதித்துறை அமைப்பாகும் மற்றும் பொதுவில் அமர்ந்திருக்கும்.\n"
        "பிரிவு 2 நீதிமன்றம் வழக்குகளை பொதுவில் விசாரிக்கும் இச்சட்டம் வேறுவிதமாகக் கூறாவிடில் வெளிப்படையாக."
    )
    assert _split(ta_pirivu, "ta") == ["1", "2"]

    fa_band = (
        "بند 1 دادگاه مرجع قضایی مستقل طبق این قانون است و احکام خود را مستدل صادر میکند در همه موارد.\n"
        "بند 2 رسیدگی در دادگاه علنی است مگر آنکه قانون ترتیب دیگری مقرر کرده باشد به طور صریح."
    )
    assert _split(fa_band, "fa") == ["1", "2"]

    neni_slash = (
        "Neni 109/7 Fusha e zbatimit. Gjykata është organ i pavarur gjyqësor sipas këtij ligji dhe gjykon në seancë publike.\n"
        "Neni 109/8 Procedura. Seanca gjyqësore është publike përveçse kur ligji parashikon ndryshe në mënyrë të shprehur."
    )
    assert _split(neni_slash, "sq") == ["109/7", "109/8"]

    seksyen_a = (
        "Seksyen 14a Tafsiran. Mahkamah ialah organ kehakiman yang bebas di bawah Akta ini dan bersidang secara terbuka.\n"
        "Seksyen 14b Tatacara. Mahkamah mendengar kes secara terbuka kecuali Akta ini memperuntukkan sebaliknya."
    )
    assert _split(seksyen_a, "ms") == ["14a", "14b"]

    da_stk = (
        "§ 1. Ejeren har ret til udstykning efter loven på hele territoriet uden undtagelse i denne bestemmelse.\n"
        "Stk. 2. Sager anlægges ved den behæftede ejendoms værneting efter loven herom i denne sag."
    )
    assert _split(da_stk, "da") == ["1", "2"]

    id_bagian = (
        "Bagian I Ketentuan Umum. Pengadilan adalah lembaga yudisial yang mandiri berdasarkan undang-undang ini dan bersidang secara terbuka.\n"
        "Bagian II Tata Cara. Sidang pengadilan bersifat terbuka kecuali undang-undang menentukan lain secara tegas."
    )
    assert _split(id_bagian, "id") == ["I", "II"]

    ht_atik = (
        "Atik 1 Tribinal la se yon ògàn jidisyè endepandan selon lwa sa a epi li chita an piblik selon dwa.\n"
        "Atik 2 Tribinal la tande ka yo an piblik sof si lwa sa a prevwa yon lòt jan klèman."
    )
    assert _split(ht_atik, "ht") == ["1", "2"]

    eu_art = (
        "1. artikulua. Auzitegia lege honen arabera organo judizial independentea da eta jendaurrean epaitzen du lurralde osoan.\n"
        "2. artikulua. Prozedura jendaurrekoa da, legeak bestelakorik xedatzen ez badu berariaz xedapen honetan."
    )
    assert _split(eu_art, "eu") == ["1", "2"]

    mn_zuil = (
        "1 дүгээр зүйл. Шүүх нь энэ хуулийн дагуу хараат бус шүүх эрх мэдлийн байгууллага бөгөөд нээлттэй хуралдана.\n"
        "2 дугаар зүйл. Шүүх хуралдаан нээлттэй байна, хуульд өөрөөр заагаагүй бол энэ заалтын дагуу."
    )
    assert _split(mn_zuil, "mn") == ["1", "2"]

    he_katan = (
        "סעיף קטן (א) בית המשפט הוא רשות שופטת עצמאית לפי חוק זה וישפוט בפומבי בכל עת לפי דין.\n"
        "סעיף קטן (ב) הדיון בבית המשפט יהיה פומבי זולת אם נקבע אחרת בחוק זה במפורש."
    )
    assert _split(he_katan, "he") == ["1", "2"]

    zh_bian = (
        "第一编 总则 为了保障公民的合法权益，促进社会公平正义，根据宪法，制定本法并公布施行于全国。\n"
        "第二编 分则 公民依法享有各项权利并履行相应义务，本法自公布之日起施行于全境。"
    )
    assert _split(zh_bian, "zh") == ["1", "2"]

    gu_kalam = (
        "કલમ 1 ન્યાયાલય આ અધિનિયમ હેઠળ એક સ્વતંત્ર ન્યાયિક અંગ છે અને જાહેરમાં બેસે છે સમગ્ર રાજ્યમાં.\n"
        "કલમ 2 ન્યાયાલય કેસો જાહેરમાં સાંભળે છે સિવાય કે આ અધિનિયમ અન્યથા જોગવાઈ કરે તેમ સ્પષ્ટપણે."
    )
    assert _split(gu_kalam, "gu") == ["1", "2"]

    it_capo = (
        "Capo I Disposizioni generali. Il tribunale è organo giudiziario indipendente ai sensi della presente legge e giudica in udienza pubblica.\n"
        "Capo II Procedimento. L'udienza è pubblica salvo che la legge disponga altrimenti in modo espresso."
    )
    assert _split(it_capo, "it") == ["I", "II"]

    pl_dzial = (
        "Dział I Przepisy ogólne. Sąd jest organem władzy sądowniczej zgodnie z niniejszą ustawą i orzeka na rozprawie jawnej.\n"
        "Dział II Postępowanie. Rozprawa jest jawna, chyba że ustawa stanowi inaczej w sposób wyraźny."
    )
    assert _split(pl_dzial, "pl") == ["I", "II"]

    sv_kap = (
        "1 kap. Allmänna bestämmelser. Domstolen är ett oberoende rättskipande organ enligt denna lag och förhandlar offentligt.\n"
        "2 kap. Förfarandet. Förhandlingen är offentlig om inte lagen föreskriver något annat uttryckligen."
    )
    assert _split(sv_kap, "sv") == ["1", "2"]

    fi_luku = (
        "1 luku Yleiset säännökset. Tuomioistuin on tämän lain mukaan riippumaton lainkäyttöelin ja käsittelee asiat julkisesti.\n"
        "2 luku Menettely. Käsittely on julkinen, jollei laissa toisin säädetä nimenomaisesti tässä pykälässä."
    )
    assert _split(fi_luku, "fi") == ["1", "2"]

    ro_titlul = (
        "Titlul I Dispoziții generale. Instanța este organ judiciar independent potrivit prezentei legi și judecă în ședință publică.\n"
        "Titlul II Procedura. Ședința este publică, dacă legea nu prevede altfel în mod expres."
    )
    assert _split(ro_titlul, "ro") == ["I", "II"]

    es_libro = (
        "Libro I Disposiciones generales. El tribunal es un órgano judicial independiente conforme a esta ley y celebra vistas públicas.\n"
        "Libro II Procedimiento. El procedimiento es público salvo disposición legal en contrario expresa."
    )
    assert _split(es_libro, "es") == ["I", "II"]

    ka_tavi = (
        "თავი I ზოგადი დებულებები. სასამართლო ამ კანონის შესაბამისად დამოუკიდებელი სასამართლო ორგანოა და საქმეს განიხილავს საჯაროდ.\n"
        "თავი II წარმოება. სასამართლო სხდომა საჯაროა, თუ კანონი სხვაგვარად არ ითვალისწინებს პირდაპირ."
    )
    assert _split(ka_tavi, "ka") == ["I", "II"]

    am_mearaf = (
        "ምዕራፍ ፩ አጠቃላይ ድንጋጌዎች ፍርድ ቤቱ በዚህ አዋጅ መሠረት ነፃ የዳኝነት አካል ነው እና በግልጽ ይፈርዳል በሕግ መሠረት።\n"
        "ምዕራፍ ፪ ሥነ ሥርዓት የፍርድ ሂደት በግልጽ ይካሄዳል በዚህ አዋጅ በተደነገገው መሠረት በግልጽ በሙሉ።"
    )
    assert _split(am_mearaf, "am") == ["1", "2"]

    km_chom = (
        "ជំពូក ១ បទប្បញ្ញត្តិទូទៅ តុលាការគឺជាស្ថាប័នតុលាការឯករាជ្យតាមច្បាប់នេះ និងជំនុំជម្រះជាសាធារណៈ។\n"
        "ជំពូក ២ នីតិវិធី ការជំនុំជម្រះរបស់តុលាការធ្វើឡើងជាសាធារណៈ លើកលែងតែច្បាប់មានចែងផ្សេង។"
    )
    assert _split(km_chom, "km") == ["1", "2"]

    sq_kreu = (
        "Kreu I Dispozita të përgjithshme. Gjykata është organ i pavarur gjyqësor sipas këtij ligji dhe gjykon në seancë publike.\n"
        "Kreu II Procedura. Seanca gjyqësore është publike përveçse kur ligji parashikon ndryshe në mënyrë të shprehur."
    )
    assert _split(sq_kreu, "sq") == ["I", "II"]

    hu_fejezet = (
        "I. Fejezet Általános rendelkezések. A bíróság e törvény szerint független igazságszolgáltatási szerv és nyilvánosan tárgyal.\n"
        "II. Fejezet Eljárás. A tárgyalás nyilvános, ha e törvény eltérően nem rendelkezik kifejezetten."
    )
    assert _split(hu_fejezet, "hu") == ["I", "II"]

    tr_bolum = (
        "Bölüm 1 Genel hükümler. Mahkeme bu kanuna göre bağımsız bir yargı organıdır ve duruşmaları aleni yapar.\n"
        "Bölüm 2 Yargılama. Duruşmalar kanunda aksi öngörülmedikçe alenidir ve gerekçeli karar verilir."
    )
    assert _split(tr_bolum, "tr") == ["1", "2"]

    et_peatukk = (
        "1. peatükk Üldsätted. Kohus on sõltumatu õigusemõistmise organ käesoleva seaduse alusel ja arutab asiat avalikult.\n"
        "2. peatükk Menetlus. Kohtuistungid on avalikud, kui seadus ei sätesta teisiti käesolevas sättes."
    )
    assert _split(et_peatukk, "et") == ["1", "2"]

    kk_tarau = (
        "1-тарау. Жалпы ережелер. Сот осы заңға сәйкес тәуелсіз сот органы болып табылады және істерді жария қарайды.\n"
        "2-тарау. Іс жүргізу. Сот отырысы заңда өзгеше көзделмесе жария өткізіледі осы бапқа сәйкес."
    )
    assert [u.kind for u in split_structured_units(kk_tarau, language="kk")] == ["chapter", "chapter"]
    assert _split(kk_tarau, "kk") == ["1", "2"]

    uz_bob = (
        "1-bob. Umumiy qoidalar. Sud ushbu qonunga muvofiq mustaqil sud organidir va ishlarni oshkora ko‘rib chiqadi.\n"
        "2-bob. Ish yuritish. Sud majlisi qonunda boshqacha nazarda tutilmagan bo‘lsa oshkora o‘tkaziladi."
    )
    assert _split(uz_bob, "uz") == ["1", "2"]

    hi_adhyay = (
        "अध्याय 1 सामान्य प्रावधान न्यायालय इस अधिनियम के अधीन एक स्वतंत्र न्यायिक अंग है और खुले में बैठता है।\n"
        "अध्याय 2 प्रक्रिया न्यायालय मामलों को खुले में सुनता है जब तक कि इस अधिनियम में अन्यथा उपबंध न हो।"
    )
    assert _split(hi_adhyay, "hi") == ["1", "2"]

    fa_fasl = (
        "فصل 1 مقررات عمومی دادگاه مرجع قضایی مستقل طبق این قانون است و احکام خود را مستدل صادر میکند در همه موارد.\n"
        "فصل 2 دادرسی رسیدگی در دادگاه علنی است مگر آنکه قانون ترتیب دیگری مقرر کرده باشد به طور صریح."
    )
    assert _split(fa_fasl, "fa") == ["1", "2"]

    zh_jie = (
        "第一节 一般规定 为了保障公民的合法权益，促进社会公平正义，根据宪法，制定本法并公布施行于全国。\n"
        "第二节 程序 公民依法享有各项权利并履行相应义务，本法自公布之日起施行于全境。"
    )
    assert _split(zh_jie, "zh") == ["1", "2"]

    el_titlos = (
        "Τίτλος 1 Γενικές διατάξεις. Το δικαστήριο είναι ανεξάρτητο όργανο κατά τον παρόντα νόμο και δικάζει δημοσίως.\n"
        "Τίτλος 2 Διαδικασία. Η διαδικασία ενώπιον του δικαστηρίου είναι δημόσια εκτός αν ο νόμος ορίζει διαφορετικά."
    )
    assert _split(el_titlos, "el") == ["1", "2"]

    nb_kapittel = (
        "Kapittel 1 Alminnelige bestemmelser. Retten er et uavhengig organ etter denne loven og behandler saker offentlig.\n"
        "Kapittel 2 Saksbehandling. Forhandlingene er offentlige med mindre loven bestemmer noe annet uttrykkelig."
    )
    assert _split(nb_kapittel, "nb") == ["1", "2"]

    ne_pari = (
        "परिच्छेद १ सामान्य व्यवस्था अदालत यस ऐन बमोजिम स्वतन्त्र न्यायिक अंग हो र खुला रुपमा बस्दछ सम्पूर्ण राज्यमा।\n"
        "परिच्छेद २ कार्यविधि अदालत मुद्दा खुला रुपमा सुन्दछ यस ऐनमा अन्यथा व्यवस्था नगरेसम्म स्पष्ट रुपमा।"
    )
    assert _split(ne_pari, "ne") == ["1", "2"]

    ha_sashe = (
        "Sashe na 1 Tanadi na gaba ɗaya. Kotun ita ce hukumar shari'a mai zaman kanta a karkashin wannan doka kuma tana zaune a fili.\n"
        "Sashe na 2 Hanya. Kotun tana sauraron karar a fili sai dai idan wannan doka ta tanadi wani hali a fili."
    )
    assert _split(ha_sashe, "ha") == ["1", "2"]

    mi_wahanga = (
        "Wāhanga 1 Ngā whakaritenga whānui. Ko te kōti he rōpū whakawā motuhake i raro i tēnei Ture ā ka noho tūmatanui.\n"
        "Wāhanga 2 Tukanga. Ka whakarongo te kōti i ngā keehi i te tūmatanui ki te kore tēnei Ture e whakarato rerekē."
    )
    assert _split(mi_wahanga, "mi") == ["1", "2"]

    ris = normalize_legal_text(
        "Bundesrecht konsolidiert www.ris.bka.gv.at Seite 2 von 2\n"
        "{\\rtf1\\ansi junk\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "ris.bka.gv.at" not in ris.lower()
    assert "rtf1" not in ris.lower()
    assert _split(ris, "en") == ["1", "2"]

    to_kupu = (
        "Kupu 1 Fakamahino. Ko e fakamaau ko ha sino fakamaau tau'ataina 'i he lao ni pea 'oku ne nofo fakapule'anga.\n"
        "Kupu 2 Founga. 'Oku fanongoa 'a e fakamaau ki he ngaahi keisi 'i he kakai kotoa kapau 'oku 'ikai ha me'a kehe."
    )
    assert _split(to_kupu, "to") == ["1", "2"]

    fj_wase = (
        "Wase 1 Na lawa vakalawa. Na mataveilewai e dua na tabana vakataki koya ni lewa e na vuku ni lawa oqo ka dabe vakaiyalayala.\n"
        "Wase 2 Na ivakarau. E na vakarorogo na mataveilewai ki na veikeisi e na rai ni lewe ni vanua kevaka e sega ni vakarautaka na lawa oqo."
    )
    assert _split(fj_wase, "fj") == ["1", "2"]

    tpi_hap = (
        "Hap 1 Ol tok i go pas. Kot em i wanpela independent judicial organ aninit long dispela lo na em i sindaun long ai bilong pablik.\n"
        "Hap 2 Rot bilong kot. Kot i harim ol keis long ai bilong pablik sapos dispela lo i no tok narapela kain long wanpela kliapela rot."
    )
    assert _split(tpi_hap, "tpi") == ["1", "2"]

    fo_kap = (
        "Kapittul 1 Almenn áseting. Dómstólurin er ein sjálvstøðugur rættarstovnur eftir hesi lóg og dømir alment í øllum landinum.\n"
        "Kapittul 2 Málsviðgerð. Tinghald skulu vera almenn um lógin ikki ásetur nakað annað berliga í hesi grein."
    )
    assert _split(fo_kap, "fo") == ["1", "2"]

    rw_ingingo = (
        "Ingingo ya 1 Itegeko rusange. Urukiko ni ishami ry'ubucamanza rwigenga uko itegeko riri n'urwicaye mu ruhame.\n"
        "Ingingo ya 2 Uburyo. Urukiko rurumva imanza mu ruhame keretse iri tegeko rihaye ubundi buryo mu buryo busobanutse."
    )
    assert _split(rw_ingingo, "rw") == ["1", "2"]

    zu_isigaba = (
        "Isigaba 1 Izinhlinzeko ezijwayelekile. Inkantolo iyisigaba sokwahlulela esizimele ngaphansi kwalo Mthetho futhi ihlala obala.\n"
        "Isigaba 2 Inqubo. Inkantolo ilalela amacala obala ngaphandle kokuthi lo Mthetho uhlinzeka ngenye indlela ngokucacile."
    )
    assert _split(zu_isigaba, "zu") == ["1", "2"]

    ky_bolum = (
        "1-бөлүм. Жалпы жоболор. Сот ушул мыйзамга ылайык көз каранды эмес сот органы болуп саналат жана иштерди ачык карайат.\n"
        "2-бөлүм. Иш жүргүзүү. Сот отуруму мыйзамда башкача каралбаса ачык өткөрүлөт ушул беренеге ылайык."
    )
    assert [u.kind for u in split_structured_units(ky_bolum, language="ky")] == ["chapter", "chapter"]
    assert _split(ky_bolum, "ky") == ["1", "2"]

    ps_mada = (
        "ماده ۱ محکمه د دې قانون له مخې یو خپلواک عدلي ارګان دی او په عام محضر کې ناسته کوي په ټول هېواد کې.\n"
        "ماده ۲ محکمه قضیې په عام محضر کې اوري پرته له دې چې دا قانون بل ډول وټاکي په څرګند ډول."
    )
    assert _split(ps_mada, "ps") == ["1", "2"]

    nbsp = normalize_legal_text(
        "Article&nbsp;1 Object. The present Act sets the applicable rules on the territory without exception.\n"
        "Article&nbsp;2 Scope. It applies throughout the national territory without exception of any kind."
    )
    assert "&nbsp;" not in nbsp
    assert _split(nbsp, "en") == ["1", "2"]

    yo_abala = (
        "Abala 1 Awọn ilana gbogbogbo. Ile-ejo je eya idajo ominira labe Ofin yii ati pe o joko ni gbangba kaakiri orile-ede.\n"
        "Abala 2 Ilana. Ile-ejo ngbo awọn ọran ni gbangba ayafi ti Ofin yii ba pese ni ọna miiran ni kedere."
    )
    assert _split(yo_abala, "yo") == ["1", "2"]

    ig_nkeji = (
        "Nkeji 1 Iwu izugbe. Uloikpe bu ngalaba ikpe nke nwere onwe ya n'okpuru Iwu a ma o nodu ala n'ihu oha n'obodo nile.\n"
        "Nkeji 2 Usoro. Uloikpe na-ege ikpe n'ihu oha beluso ma Iwu a nyere n'uzo ozo n'uzo doro anya."
    )
    assert _split(ig_nkeji, "ig") == ["1", "2"]

    ne_dafa = (
        "दफा १ अदालत यस ऐन बमोजिम स्वतन्त्र न्यायिक अंग हो र खुला रुपमा बस्दछ सम्पूर्ण राज्यमा स्पष्ट रुपमा।\n"
        "दफा २ अदालत मुद्दा खुला रुपमा सुन्दछ यस ऐनमा अन्यथा व्यवस्था नगरेसम्म स्पष्ट रुपमा।"
    )
    assert _split(ne_dafa, "ne") == ["1", "2"]

    ti_anka = (
        "ዓንቀጽ 1 ሕጊ ሓፈሻዊ። ቤት ፍርዲ ብዚ ሕጊ መሰረት ናጻ ናይ ፍርዲ ኣካል እዩን ብግህድ ይቕመጥ ኣብ ሕጊ መሰረት።\n"
        "ዓንቀጽ 2 ኣገባብ። ቤት ፍርዲ ጉዳያት ብግህድ ይሰምዕ እንተዘይኮይኑ እዚ ሕጊ ብኻልእ ኣገባብ ብግልጺ ዘቆመ ኣብዚ ዓንቀጽ።"
    )
    assert _split(ti_anka, "ti") == ["1", "2"]

    bm_sariya = (
        "Sariya 1 Sariya jumen. Kiere ye kiere ka jatebo yeremahoro ye nin sariya kono ani a sigira kene kan senkolo bee la.\n"
        "Sariya 2 Kecogo. Kiere be kow men kene kan fo nin sariya ye sira were jira a nyena a kene kan."
    )
    assert _split(bm_sariya, "bm") == ["1", "2"]

    ak_ahyede = (
        "Ahyɛde 1 Mmara a eko so. Asennibea ye atentrenee bo a ewo ahofadi wo mmara yi ase na ete wo oman no nyinaa anim.\n"
        "Ahyɛde 2 Kwan. Asennibea tie nsem wo oman no anim gye se mmara yi kyere kwan foforo pefee wo saa mmara yi mu."
    )
    assert _split(ak_ahyede, "ak") == ["1", "2"]

    si_digits = (
        "වගන්තිය ෧ අධිකරණය මෙම පනත යටතේ ස්වාධීන අධිකරණ අංගයක් වන අතර ප්‍රසිද්ධියේ රැස්වෙයි නීතියට අනුව.\n"
        "වගන්තිය ෨ අධිකරණය නඩු ප්‍රසිද්ධියේ අසයි මෙම පනත වෙනත් ලෙස නියම නොකළහොත් පැහැදිලිව."
    )
    assert _split(si_digits, "si") == ["1", "2"]

    ar_page = normalize_legal_text(
        "الصفحة 12\n"
        "اجلريدة\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "الصفحة" not in ar_page
    assert "جريدة" not in ar_page
    oman_issue = normalize_legal_text(
        "اجلريدة الر سمية العدد ()1446\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "العدد" not in oman_issue

    gazettes = normalize_legal_text(
        "العدد\n"
        "الوقائع العراقية - العدد 4110\n"
        "Journal Officiel.\n"
        "تصدر عن وزارة العدل الإدارة العامة للتشريع شعبة الجريدة الرسمية\n"
        "The Gazette Published by Authority - issue No. 1837\n"
        "يعمل بهذا القرار من تاريخ اعتماده وينشر في الجريدة الرسمية.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "الوقائع العراقية" not in gazettes
    assert "Journal Officiel." not in gazettes
    assert "شعبة الجريدة الرسمية" not in gazettes
    assert "ينشر في الجريدة الرسمية" in gazettes

    namibia = normalize_legal_text(
        "No.3361 Government Gazette 29 December 2004 3\n"
        "Supplement to the Sierra Leone Gazette Extraordinary Vol. CXLIX, No. 83\n"
        "A party may amend or supplement the claim or defense during the proceedings under this Act.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "Government Gazette" not in namibia
    assert "Sierra Leone Gazette" not in namibia
    assert "supplement the claim" in namibia

    edition = normalize_legal_text(
        "2008 Revised Edition Page 3\n"
        "REPRINT\n"
        "Revised Edition as at 31 August 2024\n"
        "[This is the version of this document as it was at 31 December 2014.]\n"
        "4. Appointment to be gazetted under this Act throughout the territory.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "Revised Edition" not in edition
    assert "REPRINT" not in edition
    assert "version of this document" not in edition
    assert "gazetted" in edition

    mojibake_n = normalize_legal_text(
        "Ley NÂo 3450 / APRUEBA LA ENMIENDA.\n"
        "Artigo 2o Âmbito. O presente diploma aplica-se em todo o territorio nacional sem excecao.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "NÂo" not in mojibake_n
    assert "nr." in mojibake_n
    assert "Âmbito" in mojibake_n
    para = normalize_legal_text(
        "Â§ 1 Toto ustanovenie ur\u010duje pravidlo, ktor\u00e9 plat\u00ed na celom \u00fazem\u00ed.\n"
        "caf\u00c3\u00a9 remains the ordinary word for coffee in this illustration of the Act.\n"
        "Â§ 2 \u010eal\u0161ie ustanovenie ur\u010duje dopl\u0148uj\u00face pravidlo na celom \u00fazem\u00ed."
    )
    assert "Â§" not in para
    assert "§ 1" in para and "§ 2" in para
    assert "caf\u00e9" in para
    assert _split(para, "sk") == ["1", "2"]

    ley_no = normalize_legal_text(
        "Ley No 3448 / APRUEBA EL ACUERDO.\n"
        "There is no exception to this rule in the territory."
    )
    assert "nr. 3448" in ley_no
    assert "no exception" in ley_no

    resol = (
        "PRIMERO: Declarar clausurada la primera fase del periodo anual de sesiones del Congreso en todo el territorio.\n"
        "SEGUNDO: El Pleno del Congreso de la Republica se reunira si fuere convocado por la Junta Directiva."
    )
    assert _split(resol, "es") == ["1", "2"]

    it_ord = (
        "Articolo primo. Il tribunale e organo giudiziario indipendente ai sensi della presente legge e giudica in udienza pubblica.\n"
        "Articolo secondo. L'udienza e pubblica salvo che la legge disponga altrimenti in modo espresso."
    )
    assert _split(it_ord, "it") == ["primo", "secondo"]

    de_ord = (
        "Erstens: Das Gericht ist ein unabhangiges Organ der Rechtsprechung nach diesem Gesetz und verhandelt offentlich.\n"
        "Zweitens: Die Verhandlung ist offentlich, soweit das Gesetz nichts anderes bestimmt ausdrucklich."
    )
    assert _split(de_ord, "de") == ["1", "2"]

    fr_ord = (
        "Premièrement: La presente loi fixe les regles applicables sur tout le territoire national sans exception.\n"
        "Deuxièmement: Elle s'applique sur tout le territoire national sans exception aucune dans tous les cas."
    )
    assert _split(fr_ord, "fr") == ["1", "2"]

    parliament = normalize_legal_text(
        "FOURTH PARLIAMENT OF THE SECOND REPUBLIC FOURTH PARLIAMENT OF THE SECOND REPUBLIC\n"
        "THIRD MEETING OF PARLIAMENT\n"
        "PARLIAMENT BUILDING\n"
        "تفاصيل النظام\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "PARLIAMENT" not in parliament
    assert "تفاصيل" not in parliament
    assert _split(parliament, "en") == ["1", "2"]

    ar_point = (
        "أولا /الضبط القانوني : تختص المحكمة بالنظر في المنازعات الناشئة عن تطبيق هذا القانون وفق أحكامه.\n"
        "ثانيا /الإجراءات : تنعقد المحكمة علنا وتصدر أحكامها مسببة إلا إذا قرر القانون خلاف ذلك."
    )
    assert _split(ar_point, "ar") == ["1", "2"]

    part_hyphen = (
        "PART III-CONTROL OF EDUCATION The Minister shall be responsible for the control of education under this Act throughout the territory.\n"
        "PART V-FINANCIAL PROVISIONS The funds of the Agency shall consist of moneys appropriated by Parliament for the purposes of this Act."
    )
    assert _split(part_hyphen, "en") == ["III", "V"]

    so_aad = (
        "Qodobka 90-aad. Xarafka (f) ee Dastuurka waxay qeexaysaa xadka madaxbannaanida maxkamadda si cad.\n"
        "Qodobka 91-aad. Maxkamaddu waa hay'ad madax-bannaan sida uu qabo sharcigan oo dhan."
    )
    assert _split(so_aad, "so") == ["90-aad", "91-aad"]

    so_glued = (
        "Qodobka 90-aadxarafka(f) ee Dastuurka waxay qeexaysaa xadka madaxbannaanida maxkamadda si cad.\n"
        "Qodobka 91-aad. Maxkamaddu waa hay'ad madax-bannaan sida uu qabo sharcigan oo dhan."
    )
    assert _split(so_glued, "so") == ["90-aad", "91-aad"]
    assert "xarafka" not in _split(so_glued, "so")[0]

    clerk = normalize_legal_text(
        "OAU DRIVE, TOWER HILL\n"
        "OFFICE OF THE CLERK OF PARLIAMENT\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "TOWER HILL" not in clerk
    assert "CLERK OF PARLIAMENT" not in clerk

    saudi = normalize_legal_text(
        "مجموعة الأنظمة السعودية\n"
        "المجلد السابع\n"
        "أنظمة المواصلات والاتصالات\n"
        "Seventh Folder\n"
        "This Law includes:\n"
        "تاريخ الإصدار\n"
        "1423/01/01 ه الموافق : 15/03/2002 م\n"
        "البريد الإلكتروني\n"
        "- اختر -\n"
        "بسم الله الرحمن الرحيم\n"
        "إن مجلس الوزراء\n"
        "خطأ لغوي\n"
        "خطأ في مادة\n"
        "يتضمن النظام ما يلي :\n"
        "1423 ه\n"
        "عدد مرات التصفح4813\n"
        "نبذة عن النظام\n"
        "المادة - اختر - مادة 1 تختص المحكمة بالنظر في المنازعات الناشئة عن تطبيق هذا القانون وفق أحكامه.\n"
        "مادة 2 تنعقد المحكمة علنا وتصدر أحكامها مسببة إلا إذا قرر القانون خلاف ذلك.\n"
        "طباعة\n"
        "الإنجليزية (English)"
    )
    assert "التصفح" not in saudi
    assert "المجلد" not in saudi
    assert "اختر" not in saudi
    assert "بسم الله" in saudi
    assert "خطأ لغوي" not in saudi
    assert "يتضمن النظام" not in saudi
    assert "مجلس الوزراء" in saudi

    toc = normalize_legal_text(
        "ARRANGEMENT OF SECTIONS\n"
        "LAWS OF BRUNEI\n"
        "ÍNDICE LEGISLATIVO\n"
        "قائمة احملتويات\n"
        "Laws of Brunei require the consent of the Sultan before publication of this Act.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "ARRANGEMENT OF SECTIONS" not in toc
    assert "ARRANGEMENT OF PROVISIONS" not in normalize_legal_text(
        "ARRANGEMENT OF PROVISIONS\nArrangement of Sections CAP. 38.05 Currency Act\n" + toc
    )
    assert "Currency Act" not in normalize_legal_text("Arrangement of Sections CAP. 38.05 Currency Act\nArticle 1 x.")
    assert "LAWS OF BRUNEI\n" not in toc and not toc.startswith("LAWS OF BRUNEI")
    assert "Laws of Brunei require" in toc

    series = normalize_legal_text(
        "LAWS OF SOUTH SUDAN\n"
        "Printed by the Ministry of Justice\n"
        "REPUBLIC OF SEYCHELLES SUPPLEMENT TO OFFICIAL GAZETTE ACT\n"
        "Ҳужжатга таклиф юборишАудиони тинглашҲужжат элементидан ҳавола олиш\n"
        "Laws of Brunei require the consent of the Sultan before publication of this Act.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "SOUTH SUDAN" not in series
    assert "Printed by" not in series
    assert "OFFICIAL GAZETTE" not in series
    assert "тинглаш" not in series
    assert "Laws of Brunei require" in series

    blanks = normalize_legal_text(
        "ACTS SUPPLEMENT\n"
        "No. of 2012.\n"
        "[Član ...\n"
        "No. 22 of 2012 remains the short title of this Act throughout the territory.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "ACTS SUPPLEMENT" not in blanks
    supp = normalize_legal_text(
        "SUPPLEMENT No.5\n"
        "SUPPLEMENT nr. 1 10th February 2009\n"
        "102. A party may amend or supplement the claim or defense during the proceedings under this Act.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "SUPPLEMENT" not in supp
    assert "supplement the claim" in supp

    urls = normalize_legal_text(
        "http://www.matsne.gov.ge 47023000022035014216\n"
        "www.centralbank.org.ls December 2016 • Research Bulletin • 16\n"
        "at www.ppcc.gov.lr\n"
        "The register is published at www.example.com for public inspection under this Act.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "matsne" not in urls
    assert "Research Bulletin" not in urls
    assert "ppcc.gov.lr" not in urls
    assert "www.example.com" in urls

    marks = normalize_legal_text(
        "© £RTICLE 16,- Toute deliberation politique est interdite au corps judiciaire sur tout le territoire.\n"
        "©S CONGRESS: RECEIVED\n"
        "Palikir, Pohnpei FM 96941\n"
        "18.1 The copyright in all drawings, documents, and other materials shall remain vested in the author.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert not marks.splitlines()[0].startswith("©")
    assert "deliberation politique" in marks
    assert "CONGRESS" not in marks
    assert "Pohnpei" not in marks
    assert "copyright in all drawings" in marks
    assert _split(marks, "en") == ["1", "2"]

    stamps = normalize_legal_text(
        " © Crown Copyright 2014\n"
        "Copying/unauthorised distribution strictly prohibited.\n"
        "Revision Date: 31 Dec 2020\n"
        "Printed under Authority by\n"
        "The Regional Law Revision Centre Inc.\n"
        "Continued on next page....\n"
        "ST. CHRISTOPHER AND NEVIS\n"
        "LAWS OF TURKS &\n"
        "4 CAP. 1.01 Constitution CAICOS ISLANDS\n"
        "AND NEVIS Supreme Court Order, etc.) CAP. 1.01 1\n"
        "Page: 7 Date: 8/8/2021 Time: 23:39:1\n"
        "bwpageid:: 287::\n"
        "bwservice::0::\n"
        "287 Service 0\n"
        "Job: (unknown)/ron_book/allvols/2021_vol7a/RON.ARA\n"
        "LAWS OF THE REPUBLIC OF NAURU s3\n"
        "Back to Page One\n"
        "PDF Download\n"
        "Word Download\n"
        "Login with Facebook\n"
        "Login with Google\n"
        "View\n"
        "Print\n"
        "E-mail\n"
        "Last updated on 17 Aug 2019\n"
        "FSM Congress\n"
        "Speakers Office\n"
        "contactcenter@almeezan.qa\n"
        "Add New Section\n"
        "1/07/1954 Corresponding to 01/11/1373 HijriPage from: 2423\n"
        "Privacy Statement\n"
        "Terms of Use\n"
        "Rate this website\n"
        "Feedback via REACH\n"
        "[18\n"
        "Singapore Statutes Online is provided by the Legislation Division.\n"
        "This reprint is authorised by the Attorney General and published under the Legislation Act\n"
        "CÔNG BÁO/Số 861 + 862/Ngày 25-7-2015 19\n"
        "Thời gian ký: 07.08.2015 11:37:25 +07:00\n"
        "LexUZ шарҳи\n"
        "[ОКОЗ:\n"
        "1.03.00.00.00 Фуқаролик қонунчилиги\n"
        "Issue: 2, Amendment: 0 204 22 October 2015\n"
        "Troubleshoot faulty system.\n"
        "PRESIDENTIAL COMM. NO.QZ-ZS]\n"
        "June 25, 2024 a\n"
        "2 Accident Compensation Act 1989\n"
        "Accident Compensation Act 1989 3\n"
        "CONSTITUCIÓN POLÍTICA DEL PERÚ 9\n"
        "10 Edición del Congreso de la República\n"
        "nr. 19 ] Public Procurement and Asset Disposal Act [ 2015\n"
        "Official Gazette nr. 01 of 01/01/2018\n"
        "+----------+-----------+\n"
        "×\n"
        "The laws of Brunei apply under s 4 of this Act throughout the territory.\n"
        "2. Amendment of section 5 of Cap. 122A\n"
        "Phone: +1 202 555 0100 is the number appointed under this section for service of notices.\n"
        "Login with the credentials issued under this section remains the method of access.\n"
        "Last updated on the register, the entry shall stand until the Minister directs otherwise.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    for gone in (
        "Crown Copyright",
        "unauthorised distribution",
        "Revision Date",
        "Printed under Authority",
        "Law Revision Centre",
        "next page",
        "CHRISTOPHER",
        "TURKS",
        "CAP. 1.01",
        "bwpageid",
        "bwservice",
        "ron_book",
        "NAURU",
        "Back to Page",
        "PDF Download",
        "Facebook",
        "Google",
        "Last updated on 17",
        "Speakers Office",
        "FSM Congress",
        "almeezan",
        "Add New Section",
        "HijriPage",
        "Privacy Statement",
        "Terms of Use",
        "REACH",
        "Statutes Online",
        "reprint is authorised",
        "CÔNG BÁO",
        "Thời gian ký",
        "LexUZ",
        "ОКОЗ",
        "1.03.00.00.00",
        "Amendment: 0",
        "PRESIDENTIAL COMM",
        "June 25, 2024",
        "Accident Compensation",
        "PERÚ",
        "Edición del Congreso",
        "Public Procurement",
        "Official Gazette nr.",
        "+----------+",
    ):
        assert gone not in stamps, gone
    assert "Troubleshoot faulty system" in stamps
    assert "laws of Brunei apply under s 4" in stamps
    assert "Cap. 122A" in stamps
    assert "Phone: +1 202 555 0100" in stamps
    assert "Login with the credentials" in stamps
    assert "Last updated on the register" in stamps
    assert not any(line.strip() in {"View", "Print", "E-mail"} for line in stamps.splitlines())
    assert not any(line.strip() in {"×", "[18", "287 Service 0"} for line in stamps.splitlines())
    assert _split(stamps, "en") == ["1", "2"]

    heads = normalize_legal_text(
        "Code civil 33/138\n"
        "www.Droit-Afrique.com Comores\n"
        "Last updated 10 May 2026\n"
        "INDEX\n"
        "Ministry/Programme/Subhead Page\n"
        "15-12243 37/104\n"
        "8/104 15-12243\n"
        "S/RES/2231 (2015)\n"
        "AB 2017, no. 32\n"
        "Grondslag: .\n"
        "رقم الهاتف: 0096824342357\n"
        "+ع\n"
        "|\n"
        "+\n"
        "Luxembourg. - Imprimerie V. Bück.\n"
        "National Parks and Wildlife Act, 1991 (Chapter 201) Zambia\n"
        "TRUJILLO DENTRO DE LA HISTORIA 375\n"
        "374 ISMAEL HERRAIZ\n"
        "100 GENERAL PROVISIONS\n"
        "prévues par le Code civil ; dans ce cas, la pension alimentaire reste due.\n"
        "Grondslag: artikel 5 van deze wet blijft van toepassing op deze handeling.\n"
        "Periode: 1981 - heden.\n"
        "Resolution S/RES/2231 (2015) remains in force under this Act.\n"
        "en Ciudad Trujillo, Distrito de Santo Domingo, a los diecisiete dias del mes.\n"
        "L'imprimerie est réglementée par la présente loi sur tout le territoire.\n"
        "The register is published at www.example.com for public inspection under this Act.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    for gone in (
        "33/138",
        "Droit-Afrique",
        "Last updated 10",
        "Subhead Page",
        "15-12243",
        "8/104",
        "S/RES/2231 (2015)\n",
        "AB 2017",
        "Grondslag: .",
        "رقم الهاتف",
        "+ع",
        "Imprimerie",
        "(Chapter 201)",
        "DENTRO DE LA HISTORIA",
        "ISMAEL HERRAIZ",
    ):
        assert gone not in heads, gone
    assert "100 GENERAL PROVISIONS" in heads
    assert "Code civil" in heads
    assert "artikel 5" in heads
    assert "Periode: 1981" in heads
    assert "remains in force" in heads
    assert "Ciudad Trujillo" in heads
    assert "imprimerie est réglementée" in heads
    assert "www.example.com" in heads
    assert not any(line.strip() in {"|", "+", "INDEX"} for line in heads.splitlines())
    assert _split(heads, "en") == ["1", "2"]

    banners = normalize_legal_text(
        "By Laws.Africa and contributors. Licensed under CC-BY. Share widely and freely. 175\n"
        "Companies Act Malawi\n"
        "B.L.R.O. 2/2023\n"
        "6 CAP. 104 Brunei Economic Development Board\n"
        "Brunei Economic Development Board CAP. 104 15\n"
        "Pages Authorised\n"
        "Current Authorised Pages\n"
        "(inclusive) by LRO.\n"
        "2 Chap. 18:50 Aliens Restriction\n"
        "~~\n"
        "- ~~\n"
        "The court in Malawi shall apply this Act throughout the territory.\n"
        "2. Amendment of section 5 of Cap. 122A\n"
        "2 Cap. 122 is amended by this Act and the new text shall apply.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    for gone in (
        "Laws.Africa",
        "Share widely",
        "Companies Act Malawi",
        "B.L.R.O.",
        "CAP. 104",
        "Pages Authorised",
        "Authorised Pages",
        "by LRO",
        "Chap. 18:50",
        "~~",
    ):
        assert gone not in banners, gone
    assert "court in Malawi shall" in banners
    assert "Cap. 122A" in banners
    assert "Cap. 122 is amended" in banners
    assert _split(banners, "en") == ["1", "2"]

    runners = normalize_legal_text(
        "There is no copyright on the legislative content of this document.\n"
        "This PDF copy is licensed under a Creative Commons Attribution 4.0 License (CC BY 4.0). Share widely and freely.\n"
        "Zambia Police Act, 1965 (Chapter 107)\n"
        "Act 10 Child Act 2008\n"
        "THE CHILD ACT, 2008\n"
        "Issue 6.00 Page 329 of 507 7 May 2025\n"
        "Issue: 5.00 160 19 August 2021\n"
        "Maldivian Civil Aviation Regulations MCAR-Air Operations\n"
        "Code Général des Impôts - Edition officielle mise à jour 2023/DGID\n"
        "CODE GENERAL DES IMPOTS 2017\n"
        "10.11.1993 - 31.12.1993\n"
        "•\n"
        "·\n"
        "ΕΦΗΜΕΡΙΣΤΗΣ ΚΥΒΕΡΝΗΣΕΩΣ (ΤΕΥΧΟΣ ΠΡΩΤΟ)\n"
        "Τεύχος A' 11/26.01.2021 ΕΦΗΜΕΡΙ∆Α TΗΣ ΚΥΒΕΡΝΗΣΕΩΣ 323\n"
        "Η πράξη δημοσιεύεται στην Εφημερίδα της Κυβερνήσεως και ισχύει από την επομένη.\n"
        "The rate from 10.11.1993 - 31.12.1993 applies under this Act throughout the territory.\n"
        "The court shall hear the application under this Act before the registrar.\n"
        "SPA manoeuvres in the autopilot engagement remain a required exercise under this Part.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    for gone in (
        "legislative content",
        "Share widely",
        "CC BY",
        "(Chapter 107)",
        "Act 10 Child Act",
        "Page 329",
        "Issue: 5.00",
        "Edition officielle",
        "CODE GENERAL DES IMPOTS 2017",
        "10.11.1993 - 31.12.1993\n",
        "ΕΦΗΜΕΡΙΣ",
        "ΕΦΗΜΕΡΙ",
    ):
        assert gone not in runners, gone
    assert "THE CHILD ACT, 2008" in runners
    assert "MCAR-Air Operations" in runners
    assert "δημοσιεύεται στην Εφημερίδα" in runners
    assert "rate from 10.11.1993" in runners
    assert "hear the application" in runners
    assert "autopilot engagement" in runners
    assert not any(line.strip() in {"•", "·"} for line in runners.splitlines())
    assert _split(runners, "en") == ["1", "2"]

    exports = normalize_legal_text(
        "Sistema Integrado de Gestao de Finanças Publicas (SIGFiP) 1/2\n"
        "Editado por:MAMADU IAIA BARI Editado em: Dimanche 22 Mars 2009 19:23:2\n"
        "PROPOSTA DE PREVISÃO ORÇAMENTAL\n"
        "Implementação do SIGFIP (Sistema Integrado de Gestão das Finanças Públicas). Este sistema permite uma melhor gestão.\n"
        "2962 ΕΠΙΣΗΜΗ ΕΦΗΜΕΡΙΔΑ ΤΗΣ 6ης ΙΟΥΝΙΟΥ 2014\n"
        "ΤΜΗΜΑ B\n"
        "Issue 14\n"
        "Power to 30. The Commission may from time to time make rules or regulations under this Act.\n"
        "Regulation on determination and publication of tariff rates for the prescribed services under this Act.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    for gone in (
        "SIGFiP) 1/2",
        "Editado por",
        "ΕΠΙΣΗΜΗ ΕΦΗΜΕΡΙΔΑ",
        "Issue 14",
    ):
        assert gone not in exports, gone
    assert "PREVISÃO ORÇAMENTAL" in exports
    assert "Implementação do SIGFIP" in exports
    assert "ΤΜΗΜΑ B" in exports
    assert "make rules or regulations" in exports
    assert "tariff rates" in exports
    assert _split(exports, "en") == ["1", "2"]

    feet = normalize_legal_text(
        "1|Page\n"
        "10 | Page\n"
        "Page | 3\n"
        "Printed on the Orders of Government\n"
        "_-__THINTED AT THE DEPARTMENT OF GOVERNMENT PRINTING, SRI LANKA\n"
        "TO BE PURCHASED AT THE GOVT. PUBLICATIONS BUREAU, COLOMBO\n"
        "Published as a Supplement to Part II of the Gazette of the Democratic\n"
        "Socialist Republic of Sri Lanka of January 11, 1980\n"
        "[Certified on 10th January, 1980]\n"
        "ACT, No. 1 OF 1980\n"
        "“Financial institution” has the meaning assigned to it in the Banking Act, 2012, and also includes a microfinance institution.\n"
        "The Department of Government Printing shall print this Act and distribute it under section 4.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    for gone in (
        "1|Page",
        "10 | Page",
        "Page | 3",
        "Orders of Government",
        "THINTED",
        "GOVERNMENT PRINTING",
        "PUBLICATIONS BUREAU",
    ):
        assert gone not in feet, gone
    assert "Published as a Supplement" in feet
    assert "Socialist Republic of Sri Lanka" in feet
    assert "Certified on 10th January" in feet
    assert "nr. 1 OF 1980" in feet
    assert "Banking Act, 2012" in feet
    assert "shall print this Act" in feet
    assert _split(feet, "en") == ["1", "2"]

    ui = normalize_legal_text(
        "{{ page.url }}\n"
        "Lap tetejére\n"
        "Megnyitottak\n"
        "Jogszabálykereső\n"
        "Page 30 1988 Revised Edition\n"
        "Printed on the Orders of Government .\n"
        "Utorak, 30. 12. 2014. SLUŽBENI GLASNIK BiH Broj 103 - Stranica 9\n"
        "BOSNE I HERCEGOVINE\n"
        "736 737\n"
        "12 13\n"
        "Job: (unknown)/ron/allvols/serv5/RON.DISASTER\n"
        "Na temelju ovog zakona sud odlučuje u ovom predmetu na cijelom teritoriju.\n"
        "The sum 736 737 is payable under this Act throughout the territory.\n"
        "Published as a Supplement to Part II of the Gazette of the Democratic Socialist Republic.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    for gone in (
        "page.url",
        "tetejére",
        "Megnyitottak",
        "Jogszabálykereső",
        "Revised Edition",
        "Orders of Government",
        "SLUŽBENI GLASNIK",
        "RON.DISASTER",
    ):
        assert gone not in ui, gone
    qod = normalize_legal_text(
        "Qodobka!1aad:!!\n"
        "Erayada qodobkan waxay khuseeyaan dhammaan dhulka qaranka inta uu sharcigu jiro."
    )
    assert qod.splitlines()[0] == "Qodobka 1aad:"
    assert not any(line.strip() == "736 737" for line in ui.splitlines())
    assert "12 13" in ui
    assert "Na temelju ovog zakona" in ui
    assert "sum 736 737 is payable" in ui
    assert "Published as a Supplement" in ui
    assert "ovog zakona sud odlučuje" in ui
    assert _split(ui, "en") == ["1", "2"]

    stamps2 = normalize_legal_text(
        "[The next page is 62,001]\n"
        "[The next page is 200,801]\n"
        "Service 0 61,802\n"
        "{\n"
        "}\n"
        "Food Act CAP 28.08 Section 1\n"
        "Food Act CAP 28.08 Arrangement of Sections\n"
        "Public Roads Act (Chapter 69:02) Malawi\n"
        "[Act 20 of 2017 wef 06/10/2017]\n"
        "Chapter 28.08\n"
        "FOOD ACT\n"
        "The court in Malawi shall apply the Public Roads Act throughout the territory.\n"
        "2. Amendment of section 5 of Cap. 122A\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    for gone in (
        "next page is",
        "61,802",
        "CAP 28.08 Section 1",
        "Arrangement of Sections",
        "(Chapter 69:02)",
        "wef 06/10/2017",
    ):
        assert gone not in stamps2, gone
    assert not any(line.strip() in {"{", "}"} for line in stamps2.splitlines())
    assert "Chapter 28.08" in stamps2
    assert "FOOD ACT" in stamps2
    assert "court in Malawi shall" in stamps2
    assert "Cap. 122A" in stamps2
    assert _split(stamps2, "en") == ["1", "2"]

    gaz = normalize_legal_text(
        "ARRANGEMENT OF SECTIONS.\n"
        "I SÉRIE - NÚMERO 3\n"
        "II SÉRIE - NÚMERO 04 Sexta-Feira, 10 de Novembro de 2017\n"
        "1 Quarta-Feira, 12 de Março de 2025 Página 258\n"
        "Série I, N.° 20 Página 229\n"
        "Série I, nr. 11 Quarta-Feira, 12 de Março de 2025 Página 258\n"
        "Quarta-Feira, 12 de Maio de 2010 Série I, nr. 18\n"
        "2 )مذكرة تفسيرية أكتوبر 2001\n"
        "- 1- )لائحة تنفيذية لقانون الجمارك لدول مجلس التعاون(\n"
        "(\n"
        "São datas oficiais, e a Quarta-Feira de Cinzas continua a ser feriado nacional.\n"
        "Buxheti i sigurimeve shoqërore për vitin 2018 2018 është: 40 milionë.\n"
        "16 dicembre\n"
        "Nigeria Tax Administration Act, 2025 2025 nr. 5 A 259\n"
        "A 258 2025 nr. 5 Nigeria Tax Administration Act, 2025\n"
        "NIGERIA TAX ADMINISTRATION ACT, 2025\n"
        "considerata la Dichiarazione Universale dei Diritti dell’uomo, proclamata il 10 dicembre 1948;\n"
        "parties may explore settlement under the Nigeria Tax Administration Act.\n"
        "1. Interpretation. This Act applies throughout the territory.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    for gone in (
        "ARRANGEMENT OF SECTIONS",
        "SÉRIE",
        "Sexta-Feira",
        "Página",
        "12 de Maio de 2010",
        "مذكرة تفسيرية",
        "لائحة تنفيذية",
        "16 dicembre",
        "A 259",
        "A 258",
    ):
        assert gone not in gaz, gone
    assert "NIGERIA TAX ADMINISTRATION ACT, 2025" in gaz
    assert "II série - número 3 do diário" in normalize_legal_text(
        "A resolução publica-se na II série - número 3 do diário e vigora em todo o território.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "Quarta-Feira de Cinzas" in gaz
    assert "Na segunda página da Série I, nr. 18" in normalize_legal_text(
        "Na segunda página da Série I, nr. 18 onde se lê o texto adequado para o problema.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "2018 është" in gaz
    assert "2018 2018" not in gaz
    assert not any(line.strip() == "(" for line in gaz.splitlines())
    assert "10 dicembre 1948" in gaz
    assert "Nigeria Tax Administration Act." in gaz
    assert "Interpretation" in gaz
    assert _split(gaz, "en") == ["1", "2"]

    sites = normalize_legal_text(
        "constituteproject.org PDF generated: 04 Oct 2013, 19:44\n"
        "Eritrea 1997 Page 3\n"
        "الصفحة .27\n"
        "[State/Territory]\n"
        "\\\n"
        "ديسمبر ،2003الصفحة 40\n"
        "In the High Court of Justice\n"
        "املادة 1 يسري هذا الحكم على كامل الإقليم الوطني دون استثناء في التطبيق.\n"
        "املادة 2 يسري هذا الحكم الآخر على كامل الإقليم الوطني دون استثناء في التطبيق.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    for gone in (
        "constituteproject",
        "PDF generated",
        "Eritrea 1997",
        "الصفحة .27",
        "State/Territory",
    ):
        assert gone not in sites, gone
    assert not any(line.strip() == "\\" for line in sites.splitlines())
    assert "2003الصفحة 40" in sites
    assert "High Court of Justice" in sites
    assert _split(sites, "ar") == ["1", "2"]

    pages = normalize_legal_text(
        "3 of 5\n"
        "5 of 5\n"
        "=\n"
        "DIRECTION GENERALE ADJOINTE DES IMPOTS\n"
        "ET DES DOMAINES\n"
        "PUBLIC LAW No. 23-84\n"
        "Figure 1: Marking of break-in points\n"
        "are marked as shown in Figure 1.\n"
        "La demande est déposée à la Direction Générale des Impôts et des Domaines au cours du mois.\n"
        "section 3 of the Act applies throughout the territory without exception.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert not any(line.strip() in {"3 of 5", "5 of 5", "="} for line in pages.splitlines())
    assert "ET DES DOMAINES" not in pages
    assert "ADJOINTE DES IMPOTS" not in pages
    assert "PUBLIC LAW nr. 23-84" in pages
    assert "Figure 1: Marking" in pages
    assert "shown in Figure 1" in pages
    assert "et des Domaines au cours" in pages
    assert "section 3 of the Act" in pages
    assert _split(pages, "en") == ["1", "2"]

    africa = normalize_legal_text(
        "Code de sécurité sociale 14/18\n"
        "www.Droit-Afrique.com Burkina Faso\n"
        "»\n"
        "RIO: 3\n"
        "BSD: 52\n"
        "et limites que les salaires pour le paiement des cotisations restent dus.\n"
        "RIO: rapport institutioneel onderzoek\n"
        "Waardering: B 1\n"
        "Periode: 1965-\n"
        "(»Narodne novine«, broj 55/96)\n"
        "The register is published at www.example.com for public inspection under this Act.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    for gone in ("14/18", "Droit-Afrique", "RIO: 3", "BSD: 52"):
        assert gone not in africa, gone
    assert not any(line.strip() == "»" for line in africa.splitlines())
    assert "salaires pour le paiement" in africa
    assert "rapport institutioneel onderzoek" in africa
    assert "Waardering: B 1" in africa
    assert "Periode: 1965-" in africa
    assert "Narodne novine" in africa
    assert "www.example.com" in africa
    assert _split(africa, "en") == ["1", "2"]

    marks = normalize_legal_text(
        "http://www.matsne.gov.ge 220.010.000.04.001\n"
        "<!-- page:1 -->\n"
        "# Journal Officiel de la République Tunisienne\n"
        "[...]\n"
        "* ®\n"
        "საზოგადოებრივი კვების ობიექტის საიდენტიფიკაციო ნომერი განისაზღვრება ამ კანონით.\n"
        "publié au Journal Officiel de la République Tunisienne et entre en vigueur.\n"
        "Duas fotografias, tipo passe, devem acompanhar o pedido nos termos deste artigo.\n"
        "The register is published at https://example.com for public inspection under this Act.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    for gone in ("matsne", "page:1", "Journal Officiel de la République Tunisienne\n", "[...]"):
        assert gone not in marks, gone
    assert not any(line.strip() in {"* ®", "*®"} for line in marks.splitlines())
    assert "საიდენტიფიკაციო" in marks
    assert "publié au Journal Officiel" in marks
    assert "Duas fotografias" in marks
    assert "https://example.com" in marks
    assert _split(marks, "en") == ["1", "2"]

    heads = normalize_legal_text(
        "Journal Officiel - Banque des Données Juridiques - 2014\n"
        "## Appui à l'inclusion financière et économique\n"
        "∞\n"
        "∞∞ ∞\n"
        "∞ 10\n"
        "Cabezas de freno sin bocado, la docena. 8\n"
        "publié au Journal Officiel et entre en vigueur sur tout le territoire.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "Banque des Données" not in heads
    assert "Appui à l'inclusion financière" in heads
    assert not heads.lstrip().startswith("#")
    assert not any(line.strip() in {"∞", "∞∞ ∞"} for line in heads.splitlines())
    assert "∞ 10" in heads
    assert "Cabezas de freno" in heads
    assert "publié au Journal Officiel" in heads
    assert _split(heads, "en") == ["1", "2"]
    assert _split(urls, "en") == ["1", "2"]
    assert _split(supp, "en") == ["1", "2"]
    assert "No. of 2012" not in blanks
    assert "Član" not in blanks
    assert "nr. 22 of 2012" in blanks

    vanuatu = normalize_legal_text(
        "REPUBLIC OF VANUATU\n"
        "BILL FOR THE\n"
        "ACT NO. OF 2024\n"
        "SAINT VINCENT AND THE GRENADINES\n"
        "The Republic of Vanuatu shall apply this Act throughout the territory.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert not any(line.strip() == "REPUBLIC OF VANUATU" for line in vanuatu.splitlines())
    assert "BILL FOR THE" not in vanuatu
    assert "ACT NO. OF 2024" not in vanuatu
    assert "GRENADINES" not in vanuatu
    assert "Republic of Vanuatu shall" in vanuatu

    more_heads = normalize_legal_text(
        "THE REPUBLIC OF SIERRA LEONE\n"
        "Federal Republic of somalia\n"
        "Democratic People's Republic of Korea\n"
        "(yes ) Republic of Palau\n"
        "ARRANGEMENT OF REGULATIONS\n"
        "CONTENTS\n"
        "The Republic of Fiji is a sovereign democratic State founded on the values of this Act.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "SIERRA LEONE" not in more_heads
    assert "somalia" not in more_heads.lower()
    assert "People's Republic" not in more_heads
    assert "Palau" not in more_heads
    assert "REGULATIONS" not in more_heads
    assert "CONTENTS" not in more_heads
    assert "Republic of Fiji is a sovereign" in more_heads

    sey = normalize_legal_text(
        "[28th October 2024] Constitution of the Republic of Seychelles 261\n"
        "[4th July 2025] Constitution of the Republic of Seychelles 214\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "28th October" not in sey
    assert "[20th January, 1992]" not in normalize_legal_text("[20th January, 1992]\n" + sey)
    assert "CAP. 40.24" not in normalize_legal_text("CAP. 40.24\nCopyright Act CAP. 40.24 Section 1\n" + sey)
    assert "Cap. 122A" in normalize_legal_text("2. Amendment of section 5 of Cap. 122A\n" + sey)
    pages = normalize_legal_text(
        "78\n"
        "1799\n"
        "7....\n"
        "၃\n"
        "1/3\n"
        "//\n"
        "i\n"
        "BANKRUPTCY AND INSOLVENCY\n"
        "v\n"
        "Dear President Simina:\n"
        "Gazette.\n"
        "A notice shall be published in the Gazette before the appointment takes effect.\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert not any(line.strip() in {"78", "1799", "7", "၃", "1/3", "//", "i", "v", "Gazette."} for line in pages.splitlines())
    assert "BANKRUPTCY AND INSOLVENCY" in pages
    listed = normalize_legal_text(
        "1.\nheritage resources;\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "1." in listed.splitlines()
    assert "Dear President Simina:" in pages
    assert "published in the Gazette" in pages
    assert _split(pages, "en") == ["1", "2"]
    assert "Seychelles 214" not in sey
    assert _split(sey, "en") == ["1", "2"]
    assert _split(more_heads, "en") == ["1", "2"]
    assert _split(vanuatu, "en") == ["1", "2"]
    assert _split(blanks, "en") == ["1", "2"]
    assert _split(series, "en") == ["1", "2"]

    bahamas = normalize_legal_text(
        "..\n"
        "SECTION\n"
        "1. Short title.\n"
        "[Original Service 2001] STATUTE LAW OF THE BAHAMAS\n"
        "GAMING [CH.388 - 3\n"
        "التاريخ:\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "STATUTE LAW OF THE BAHAMAS" not in bahamas
    assert "CH.388" not in bahamas
    assert "التاريخ" not in bahamas
    assert "Short title" in bahamas

    islands = normalize_legal_text(
        "Republic of the Marshall Islands\n"
        "Jepilpilin Ke Ejukaan\n"
        "Олдинги таҳрирга қаранг.\n"
        "Explanatory Note\n"
        ". ( 1 )\n"
        "يونيو 2018\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "Marshall Islands" not in islands
    assert "Jepilpilin" not in islands

    running = normalize_legal_text(
        "เลม ๑๔๐ ตอนพิเศษ ๒๕๔ ง ราชกิจจานุเบกษา ๑๑ ตุลาคม ๒๕๖๖\n"
        "اطلاق نسخة جديدة من الميزان\n"
        "[25/2010 wef 22/10/2010]\n"
        "[22/2000]\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "ราชกิจจานุเบกษา" not in running
    assert "الميزان" not in running
    assert "wef" not in running
    assert "[22/2000]" not in running
    assert _split(running, "en") == ["1", "2"]
    assert "таҳрирга" not in islands
    assert "Explanatory Note" not in islands
    assert "يونيو" not in islands
    assert _split(islands, "en") == ["1", "2"]

    cs_letter = (
        "§ 18 a). Soud je organem soudni moci podle tohoto zakona a jedna verejne na celem uzemi statu bez vyjimky.\n"
        "§ 18 b). Jednani soudu je verejne, nestanovi-li zakon jinak vyrazne v tomto ustanoveni."
    )
    assert _split(cs_letter, "cs") == ["18 a", "18 b"]

    sabor = normalize_legal_text(
        "ZASTUPNIČKI DOM HRVATSKOGA SABORA\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "SABORA" not in sabor
    assert _split(sabor, "en") == ["1", "2"]
    assert _split(bahamas, "en") == ["1", "2"]
    assert "ÍNDICE LEGISLATIVO" not in toc
    assert "قائمة" not in toc
    assert _split(toc, "en") == ["1", "2"]
    assert "اختر" not in saudi
    assert "طباعة" not in saudi
    assert _split(saudi, "ar") == ["1", "2"]
    assert _split(clerk, "en") == ["1", "2"]
    assert _split(edition, "en") == ["1", "2"]
    assert _split(namibia, "en") == ["1", "2"]
    assert _split(gazettes, "en") == ["1", "2"]
    assert _split(oman_issue, "en") == ["1", "2"]
    assert _split(ar_page, "en") == ["1", "2"]

    oman_nav = normalize_legal_text(
        "التشريعات | وزارة العدل و الشؤون القانونية\n"
        "Page Not Found - Singapore Statutes Online\n"
        "No 26022 Gaceta Oficial Digital, viernes 18 de abril de 2008 1\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "وزارة العدل" not in oman_nav
    assert "page not found" not in oman_nav.lower()
    assert "gaceta oficial" not in oman_nav.lower()
    assert _split(oman_nav, "en") == ["1", "2"]

    notfound = normalize_legal_text(
        "404 Not Found\n"
        "cs@mjla.gov.om\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "404" not in notfound
    assert "@mjla" not in notfound
    assert _split(notfound, "en") == ["1", "2"]

    nic_unico = (
        "CAPITULO UNICO Disposiciones generales. El tribunal es un organo judicial independiente conforme a esta ley y celebra vistas publicas.\n"
        "CAPITULO II Procedimiento. El procedimiento es publico salvo disposicion legal en contrario expresa en esta norma."
    )
    assert _split(nic_unico, "es") == ["UNICO", "II"]

    br_pennad = (
        "Pennad 1 Dispoziciou hollek. Al lez-varn zo un organ lezennel dizalc'h hervez al lezenn-man hag a azezh en un doare foran.\n"
        "Pennad 2 Prosedur. Al lez-varn a selaou an aferiou en un doare foran nemet ma vez gwelet en un doare all gant al lezenn-man."
    )
    assert _split(br_pennad, "br") == ["1", "2"]

    kri_sek = (
        "Sekshon 1 Jeneral rul dem. Di kot na wan independent judicial organ onda dis Akt en i sidon na poblik.\n"
        "Sekshon 2 Prosidyua. Di kot de yeri kes dem na poblik leke dis Akt no pree oda kain we kliya."
    )
    assert _split(kri_sek, "kri") == ["1", "2"]

    es_decimal = (
        "ARTÍCULO 123.1. El término de prescripción se suspende en los casos previstos por esta ley en todo el territorio nacional.\n"
        "ARTÍCULO 123.2. El procedimiento es público salvo disposición legal en contrario expresa en esta norma."
    )
    assert _split(es_decimal, "es") == ["123.1", "123.2"]

    en_prin = (
        "Section 1 of the principal Act is amended as set out in the Schedule to this Act for the whole territory.\n"
        "Section 2 Scope. It applies throughout the national territory without exception of any kind whatsoever.\n"
        "Section 3 Application. The Act binds the Government and applies in every part of the national territory."
    )
    assert _split(en_prin, "en") == ["2", "3"]

    ug_madda = (
        "ماددا 1 سوت مەھكىمىسى بۇ قانۇن بويىچە مۇستەقىل سوت ئورگىنى بولۇپ، ئاشكارا ئولتۇرىدۇ پۈتۈن دۆلەتتە.\n"
        "ماددا 2 سوت ئىشلىرىنى ئاشكارا ئاڭلايدۇ، بۇ قانۇندا باشقىچە بەلگىلەنمىگەن تەقدىردە روشەن قىلىپ."
    )
    assert _split(ug_madda, "ug") == ["1", "2"]

    kw_erth = (
        "Erthygel 1 Disposyansow ollgemmyn. An vreuslys yw organ breusydh anserghek yn-dann an Lagha ma hag a esedh yn somen.\n"
        "Erthygel 2 Prosedur. An vreuslys a wra goslowes kesow yn somen marnas an Lagha ma a bourve yn fordh arall yn kler."
    )
    assert _split(kw_erth, "kw") == ["1", "2"]

    tet_artigu = (
        "Artigu 1 Dispozisaun jeral. Tribunal ne'e organ judisial independente tuir Lei ida-ne'e no tuur iha publiku iha rai laran tomak.\n"
        "Artigu 2 Prosedimentu. Tribunal rona kazu sira iha publiku salvu Lei ida-ne'e fo dalan seluk ho klar iha norma ida-ne'e."
    )
    assert _split(tet_artigu, "tet") == ["1", "2"]

    haw_pauku = (
        "Paukū 1 Na rula maamau. He lala hooholo kuokoa ka aha hookolokolo malalo o keia Kanawai a noho akea ia ma ka aina holo'oko'a.\n"
        "Paukū 2 Ke kainoa. E hoolohe ka aha i na hihia ma ke akea ke ole keia Kanawai e hoonohonoho i kekahi ala e ae."
    )
    assert _split(haw_pauku, "haw") == ["1", "2"]

    es_numeral = (
        "Artículo 1. El tribunal es un órgano judicial independiente conforme a esta ley y celebra vistas públicas en todo el territorio.\n"
        "Numeral 2. El procedimiento es público salvo disposición legal en contrario expresa en esta norma."
    )
    assert _split(es_numeral, "es") == ["1", "2"]

    it_capoverso = (
        "Articolo 1. Il tribunale è organo giudiziario indipendente ai sensi della presente legge e giudica in udienza pubblica.\n"
        "Capoverso 2. L'udienza è pubblica salvo che la legge disponga altrimenti in modo espresso."
    )
    assert _split(it_capoverso, "it") == ["1", "2"]

    thereof = (
        "SECTION 6 THEREOF, TO EXTEND THE LAPSE DATE OF CERTAIN AUTHORIZATIONS UNDER THIS ACT FOR THE WHOLE TERRITORY.\n"
        "Section 2 Scope. It applies throughout the national territory without exception of any kind whatsoever.\n"
        "Section 3 Application. The Act binds the Government and applies in every part of the national territory."
    )
    assert _split(thereof, "en") == ["2", "3"]

    ordinance = (
        "Section 90 of this Ordinance shall apply throughout the national territory without exception of any kind.\n"
        "Section 2 Scope. It applies throughout the national territory without exception of any kind whatsoever.\n"
        "Section 3 Application. The Act binds the Government and applies in every part of the national territory."
    )
    assert _split(ordinance, "en") == ["2", "3"]

    denied = normalize_legal_text(
        "Access Denied\n"
        "Forbidden\n"
        "Public Notification\n"
        "Article 1 Object. The present Act sets the applicable rules on the territory.\n"
        "Article 2 Scope. It applies throughout the national territory without exception."
    )
    assert "access denied" not in denied.lower()
    assert "forbidden" not in denied.lower()
    assert "public notification" not in denied.lower()
    assert _split(denied, "en") == ["1", "2"]

    spaced = normalize_legal_text(
        "A R T Í C U L O 86.- Resolucion. El tribunal es un organo judicial independiente conforme a esta ley y celebra vistas publicas.\n"
        "A R T Í C U L O 91.- Procedimiento. El procedimiento es publico salvo disposicion legal en contrario expresa en esta norma."
    )
    assert "ARTÍCULO" in spaced or "ARTICULO" in spaced
    assert _split(spaced, "es") == ["86", "91"]

    glued = (
        "Article16 Les depenses du comite sont constituees par les frais de fonctionnement prevus par la presente loi sur tout le territoire.\n"
        "Article17 Les recettes du comite sont constituees par les ressources affectees par la presente loi sur tout le territoire."
    )
    assert _split(glued, "fr") == ["16", "17"]

    schedules = (
        "SCHEDULE 2 Miscellaneous Fees. The fees payable under this Act are set out in this schedule for the whole territory without exception.\n"
        "SCHEDULE 3 Forms. The forms prescribed under this Act are set out in this schedule for the whole territory."
    )
    assert _split(schedules, "en") == ["2", "3"]

    forms = (
        "Form 1 Application. An application under this Act shall be in the prescribed form for the whole territory without exception.\n"
        "Form 2 Notice. A notice under this Act shall be in the prescribed form for the whole territory without exception."
    )
    assert _split(forms, "en") == ["1", "2"]

    not_headings = (
        "Normal procedure does not apply as a heading in this sentence about ordinary process at all.\n"
        "The annexed schedule is not a heading in this sentence about the annexed documents either.\n"
        "DECISIONS of the committee are recorded in the minutes of the sitting for the whole territory.\n"
        "Satzung 1 ist kein Gliederungspunkt in diesem langen Satz über die Satzung der Gesellschaft.\n"
        "Command 1 of the unit is not a legal heading in this long sentence about military command.\n"
        "Regulations 1 of the minister are not a heading in this long sentence about regulations.\n"
        "Avisos 1 de tempestade nao sao um titulo neste longo texto sobre avisos meteorologicos.\n"
        "Punkte 1 der Tagesordnung sind kein Gliederungspunkt in diesem langen Satz über Punkte.\n"
        "Reglements 1 du ministre ne sont pas un titre dans cette longue phrase sur les reglements.\n"
        "Decrees 1 of the president are not a heading in this long sentence about decrees.\n"
        "Paragraphs 1 of the report are not a heading in this long sentence about paragraphs.\n"
        "Sections 1 of the act are not a heading in this long sentence about sections of the statute.\n"
        "Ordinances 1 of the city are not a heading in this long sentence about city ordinances."
    )

    paragraphs = (
        "Paragraph 1 The court is an independent judicial organ under this Act and shall sit in public according to law.\n"
        "Paragraph 2 The court hears cases in public except as otherwise provided by this Act in express terms."
    )
    assert _split(paragraphs, "en") == ["1", "2"]

    not_letter = (
        "Il decreto sono valide per sei mesi a decorrere dalla data indicata nella presente legge su tutto il territorio.\n"
        "This section shall have effect from such date, not earlier than the commencement of this Act in the territory."
    )
    assert split_structured_units(not_letter, language="en") == []

    schedule_a = (
        "SCHEDULE A Fees. The fees payable under this Act are set out in this schedule for the whole territory without exception.\n"
        "SCHEDULE B Forms. The forms prescribed under this Act are set out in this schedule for the whole territory."
    )
    assert _split(schedule_a, "en") == ["A", "B"]

    titre = (
        "TITRE I Dispositions generales. La presente loi fixe les regles applicables sur tout le territoire national sans exception.\n"
        "TITRE II Dispositions penales. Les infractions sont punies conformement au code penal en vigueur sur tout le territoire."
    )
    assert _split(titre, "fr") == ["I", "II"]

    ocr_l = (
        "TITRE l 531,613,945 chiffres sans valeur juridique dans cet instrument sur tout le territoire national.\n"
        "TITRE II Dispositions penales. Les infractions sont punies conformement au code penal en vigueur sur tout le territoire."
    )
    assert "l" not in _split(ocr_l, "fr")

    decreto_n = (
        "Decreto N” 6.217, con Rango, Valor y Fuerza de Ley Organica de la Administracion Publica en todo el territorio nacional.\n"
        "Decreto N* 5.999, con Rango, Valor y Fuerza de Ley Organica del Despacho en todo el territorio nacional."
    )
    assert _split(decreto_n, "es") == ["6.217", "5.999"]

    xref = (
        "subsection (l)(b) is determined by application of the following formula under this Act throughout the territory.\n"
        "paragraph (i) or have been registered in accordance with this Act throughout the national territory."
    )
    assert split_structured_units(xref, language="en") == []

    not_articles = (
        "Articoli 1 della legge non sono un titolo in questa lunga frase sugli articoli del codice civile.\n"
        "Maddeler 1 bu kanunun maddeleri bu uzun cumlede bir baslik degildir kanun metninde hic."
    )
    assert split_structured_units(not_articles, language="en") == []

    madde = (
        "Madde 1 Mahkeme bu kanuna gore bagimsiz bir yargi organidir ve durusmalari aleni yapar butun ulkede.\n"
        "Madde 2 Durusmalar kanunda aksi ongorulmedikce alenidir ve gerekceli karar verilir acikca."
    )
    assert _split(madde, "tr") == ["1", "2"]
    assert split_structured_units(not_headings, language="en") == []

    norma = (
        "NORMA 1 Oficial. El tribunal es un organo judicial independiente conforme a esta ley y celebra vistas publicas.\n"
        "NORMA 2 Procedimiento. El procedimiento es publico salvo disposicion legal en contrario expresa en esta norma."
    )
    assert _split(norma, "es") == ["1", "2"]

    saudi_ord = (
        "المادة الأولى تختص المحكمة بالنظر في المنازعات الناشئة عن تطبيق هذا النظام وفق أحكامه.\n"
        "المادة التاسعة تنشر الأحكام القضائية وفق ما تحدده اللائحة التنفيذية لهذا النظام."
    )
    assert _split(saudi_ord, "ar") == ["1", "9"]

    japanese_kanji = (
        "第一条 この法律は、裁判所の独立を保障することを目的とする。公開の法廷で裁判を行う。\n"
        "第十二条 裁判は公開の法廷で行う。ただし法律に特別の定めがある場合はこの限りでない。"
    )
    assert _split(japanese_kanji, "ja") == ["1", "12"]

    annexe = (
        "Article Annexe Les définitions figurent en annexe de la présente loi et s'appliquent sur tout le territoire.\n"
        "Article 2 Champ. Elle s'applique sur tout le territoire national sans exception aucune."
    )
    nums = _split(annexe, "fr")
    assert nums[0].casefold() == "annexe" and "2" in nums

    danish_inner = (
        "§ 1. Ejeren af en fast ejendom har under iagttagelse af nedenstående bestemmelser ret til udstykning.\n"
        "§ 2. De i § 1 omhandlede sager anlægges ved den behæftede ejendoms værneting efter loven."
    )
    assert _split(danish_inner, "da") == ["1", "2"]

    arabic_21 = (
        "المادة الحادية والعشرون تختص المحكمة بالنظر في المنازعات الناشئة عن تطبيق هذا النظام وفق أحكامه.\n"
        "المادة الثانية والعشرون تنشر الأحكام القضائية وفق ما تحدده اللائحة التنفيذية لهذا النظام."
    )
    assert _split(arabic_21, "ar") == ["21", "22"]

    chinese_hundred = (
        "第一百条 为了保障公民的合法权益，促进社会公平正义，制定本法并公布施行。\n"
        "第二百条 本法自公布之日起施行。最高人民法院负责解释有关审判工作。"
    )
    assert _split(chinese_hundred, "zh") == ["100", "200"]

    dari_ord = (
        "ماده پنجم پادشاه بايد از تبعه افغانستان بوده و مسلمان باشد طبق اين قانون.\n"
        "ماده دوازدهم آزادی بیان در حدود احکام این قانون تامین میگردد و سانسور ممنوع است."
    )
    assert _split(dari_ord, "fa") == ["5", "12"]

    dari_en = (
        "ARTICLE 1: Should a property be required by the Government for the public welfare, compensation shall be paid.\n"
        "ARTICLE 10: Expenses concerning the evaluation experts shall be paid by the appropriating authority."
    )
    assert _split(dari_en, "fa") == ["1", "10"]

    cameroon = (
        "CHAPITRE 01 - PRESIDENCE DE LA REPUBLIQUE crédits ouverts pour l'exercice budgétaire en cours.\n"
        "CHAPITRE 08 - MINISTERE DE LA JUSTICE crédits ouverts pour l'exercice budgétaire en cours."
    )
    ch_units = split_structured_units(cameroon, language="fr")
    assert [u.kind for u in ch_units] == ["chapter", "chapter"]
    assert [u.number for u in ch_units] == ["01", "08"]

    titre_ier = (
        "Titre Ier Dispositions générales. La présente loi fixe les règles applicables sur tout le territoire.\n"
        "Titre II Dispositions pénales. Les infractions sont punies conformément au code pénal."
    )
    assert [u.number for u in split_structured_units(titre_ier, language="fr")] == ["Ier", "II"]

    disposicion = (
        "Disposición adicional primera. Las referencias a la legislación vigente se entenderán hechas a las normas que las sustituyan.\n"
        "Disposición transitoria única. Los procedimientos iniciados con anterioridad se tramitarán conforme a la normativa precedente."
    )
    disp_nums = [u.number.casefold() for u in split_structured_units(disposicion, language="es")]
    assert "primera" in disp_nums and "única" in disp_nums

    paragraphe = (
        "Paragraphe 1 Objet. La présente loi fixe les règles applicables sur tout le territoire.\n"
        "Paragraphe 2 Champ. Elle s'applique sur tout le territoire national sans exception."
    )
    assert _split(paragraphe, "fr") == ["1", "2"]

    poglavlje = (
        "Poglavlje 1 Opće odredbe. Sud je organ sudske vlasti prema ovom zakonu i odlučuje neovisno.\n"
        "Poglavlje 2 Postupak. Postupak pred sudom je javan osim ako zakon ne odredi drukčije."
    )
    pg = split_structured_units(poglavlje, language="hr")
    assert [u.kind for u in pg] == ["chapter", "chapter"]
    assert [u.number for u in pg] == ["1", "2"]

    sec_plain = (
        "Sec 1 Short title. This Act may be cited as the Board of Review Act 2019 of the Realm.\n"
        "Sec 2 Interpretation. In this Act Board means the Board established by section 3."
    )
    assert _split(sec_plain, "en") == ["1", "2"]

    parrafo = (
        "Párrafo 1. La presente ley fija las reglas aplicables en todo el territorio nacional sin excepción.\n"
        "Párrafo 2. Se aplica en todo el territorio nacional a las personas físicas y jurídicas."
    )
    assert _split(parrafo, "es") == ["1", "2"]

    ustawa = (
        "ust. 1. Sąd jest organem władzy sądowniczej zgodnie z niniejszą ustawą i orzeka niezależnie.\n"
        "ust. 2. Rozprawa przed sądem jest jawna, chyba że ustawa stanowi inaczej."
    )
    assert _split(ustawa, "pl") == ["1", "2"]

    kapitola = (
        "Kapitola 1 Účel. Soud je orgánem soudní moci podle tohoto zákona a rozhoduje nezávisle.\n"
        "Kapitola 2 Řízení. Řízení před soudem je veřejné, pokud zákon nestanoví jinak."
    )
    kap = split_structured_units(kapitola, language="cs")
    assert [u.kind for u in kap] == ["chapter", "chapter"]
    assert [u.number for u in kap] == ["1", "2"]

    momentti = (
        "1 momentti. Tuomioistuin on tämän lain mukainen riippumaton tuomioistuin ja käsittelee asiat julkisesti.\n"
        "2 momentti. Käsittely on julkinen, jollei laissa toisin säädetä tässä pykälässä."
    )
    assert _split(momentti, "fi") == ["1", "2"]

    thai_page = normalize_legal_text("หนา ๔๐")
    assert thai_page == ""


def test_lexicon_article_tokens_round_trip_split() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.profiles import HEADING_LEXICON
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.structure import (
        split_structured_units,
    )

    failed: list[str] = []
    checked = 0
    for token, hits in HEADING_LEXICON.items():
        langs = {lg for kind, lg in hits if kind in {"article", "section"} and lg != "und"}
        if len(token) < 2 or not langs:
            continue
        lang = next(iter(langs))
        blob = (
            f"{token} 1 Definitions. The court is an independent judicial organ under this Act and shall sit in public.\n"
            f"{token} 2 Procedure. The court hears cases in public except as otherwise provided by this Act."
        )
        units = split_structured_units(blob, language=lang)
        nums = [u.number for u in units]
        checked += 1
        if len(units) < 2 or not any(n in {"1", "1."} or str(n).endswith("1") for n in nums):
            failed.append(f"{token!r} lang={lang} nums={nums}")
    assert checked >= 50
    assert failed == []


def test_normalize_splits_unstructured_law_body_when_headings_exist() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.normalize import (
        build_corpus,
    )

    laws = _laws(
        {
            "id": "law-1",
            "title": "Courts Act",
            "text": (
                "Article 1 Definitions. Court means a court of record.\n"
                "Article 2 Procedure. The court shall sit in public."
            ),
            "jurisdiction": "Fixture",
            "country": "Fixture",
            "language": "en",
            "source_url": "https://example.test/1",
            "license": "cc0",
            "eli": "",
            "identifier": "law-1",
            "official_identifier": "LAW-1",
            "source_type": "official",
            "law_status": "in_force",
            "metadata_json": "{}",
        }
    )
    corpus, report = build_corpus(laws, _articles(), _source_meta("rev-a"))
    assert report["unit"] in {"structured", "law+structured"}
    assert int((corpus["record_type"] == "law").sum()) == 1
    assert int(corpus["record_type"].isin(["article", "section"]).sum()) == 2
    assert "Article 1" in corpus["hierarchy_path"].iloc[0] or corpus["article_number"].iloc[0]


def test_normalize_is_cid_stable_across_identical_bodies() -> None:
    first = _corpus_for("Customs Act", "Ports Act", revision="rev-a")
    second = _corpus_for("Customs Act", "Ports Act", revision="rev-b")
    assert first["entry_cid"].tolist() == second["entry_cid"].tolist()
    assert first["body_sha256"].tolist() == second["body_sha256"].tolist()


def test_bm25_rows_skip_documents_with_no_searchable_tokens() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.sparse import (
        corpus_to_bm25_rows,
    )

    corpus = _corpus_for("Customs Act", "!!!")
    # Force an empty-token body/title on the second row.
    corpus.loc[1, "title"] = "..."
    corpus.loc[1, "body"] = ""
    rows = corpus_to_bm25_rows(corpus)
    assert len(rows) == 1
    assert rows[0]["document_index"] == 0


def test_sparse_export_uses_shared_hf_graphrag_parquet_builders(
    tmp_path: Path,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.sparse import (
        export_sparse_graphrag,
    )

    corpus = _corpus_for("Customs Act", "Aviation Act")
    report = export_sparse_graphrag(corpus, tmp_path)
    assert report["sqlite"] is False
    assert report["engine"] == "hf_graphrag"
    assert list((tmp_path / "data" / "bm25" / "documents").glob("*.parquet"))
    assert list((tmp_path / "data" / "bm25" / "postings").glob("*.parquet"))
    assert list((tmp_path / "data" / "graph" / "nodes").glob("*.parquet"))
    assert list(tmp_path.rglob("*.sqlite")) == []
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.duckdb_store import (
        bm25_search,
        graph_neighbors,
    )

    (tmp_path / "manifest.json").write_text(
        json.dumps({"bm25": (report.get("bm25") or {}).get("bm25") or {"average_document_length": 8.0}}),
        encoding="utf-8",
    )
    hits = bm25_search(tmp_path, "customs")
    assert hits
    assert hits[0]["entry_cid"]
    neighbors = graph_neighbors(tmp_path, hits[0]["entry_cid"], direction="both")
    assert isinstance(neighbors, list)


def test_duckdb_neighbors_write_parquet_not_sqlite(tmp_path: Path) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.spill import (
        iter_neighbor_shards,
        neighbors_via_duckdb,
    )

    corpus = _corpus_for("Customs Act", "Aviation Act", "Ports Harbour Act")
    corpus_path = tmp_path / "corpus.parquet"
    corpus.to_parquet(corpus_path, index=False)
    spill = tmp_path / "spill"
    shards = neighbors_via_duckdb(corpus_path, spill, len(corpus), k=2)
    assert shards
    assert all(path.suffix == ".parquet" for path in shards)
    assert list(spill.glob("*.sqlite")) == []
    assert (spill / "neighbors.duckdb").is_file()
    parts = list(iter_neighbor_shards(spill))
    assert parts
    _start, neigh = parts[0]
    assert isinstance(neigh, list)


def test_duckdb_bm25_reads_parquet_shards(tmp_path: Path) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.bm25 import build_index
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.duckdb_store import (
        bm25_search,
        materialize_corpus_duckdb,
    )
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.parquet_io import (
        write_parquet,
    )

    corpus = _corpus_for("Customs Act", "Aviation Ports Act")
    index = build_index(corpus)
    docs_dir = tmp_path / "data" / "bm25" / "documents"
    posts_dir = tmp_path / "data" / "bm25" / "postings"
    docs_dir.mkdir(parents=True)
    posts_dir.mkdir(parents=True)
    write_parquet(docs_dir / "part-000000.parquet", index["documents"])
    write_parquet(posts_dir / "part-000000.parquet", index["postings"])
    (tmp_path / "manifest.json").write_text(
        json.dumps({"bm25": index["stats"]}), encoding="utf-8"
    )
    hits = bm25_search(tmp_path, "customs")
    assert hits
    assert hits[0]["entry_cid"]
    assert "customs" in str(hits[0]["title"]).lower() or hits[0]["score"] > 0
    corpus_path = tmp_path / "data" / "corpus" / "part-000000.parquet"
    corpus_path.parent.mkdir(parents=True, exist_ok=True)
    write_parquet(corpus_path, corpus[["document_index", "entry_cid", "title", "body"]])
    db = materialize_corpus_duckdb(corpus_path, tmp_path / "corpus.duckdb")
    assert db.is_file()


def test_dataset_card_yaml_front_matter_is_parseable(tmp_path: Path) -> None:
    import yaml
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.package import (
        _write_readme,
    )
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.upload import (
        ensure_dataset_card,
    )

    (tmp_path / "data" / "graph" / "adjacency" / "out").mkdir(parents=True)
    (tmp_path / "data" / "graph" / "adjacency" / "in").mkdir(parents=True)
    _write_readme(
        tmp_path,
        {"slug": "korea", "name": "Korea (ROK)"},
        {"source_dataset": "endomorphosis/ipfs_korea_laws", "source_revision": "abc"},
        {"n_laws": 3, "n_articles": 9, "corpus_rows": 12, "bm25_terms": 1, "bm25_postings": 1, "graph_nodes": 1, "graph_edges": 1, "vector_rows": 12},
        {},
        {},
        {"dimension": 384, "model_name": "thenlper/gte-small", "status": "embedded"},
        "justicedao/ipfs_korea_laws_ir",
        normalization_report={"document_language_majority": "ko", "language_breakdown": {"ko": 12}},
    )
    text = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert text.startswith("---")
    meta = yaml.safe_load(text.split("---", 2)[1])
    assert meta["pretty_name"] == "Korea (ROK) laws IR (CID-keyed GraphRAG)"
    assert meta["language"] == ["ko"]
    assert "text-retrieval" in meta["task_categories"]
    paths = [c["data_files"][0]["path"] for c in meta["configs"]]
    assert "data/graph/adjacency/out/*.parquet" in paths
    assert "data/graph/adjacency/in/*.parquet" in paths
    assert not any("outgoing" in p or "incoming" in p for p in paths)

    stub = tmp_path / "other"
    stub.mkdir()
    (stub / "manifest.json").write_text(
        json.dumps(
            {
                "country": {"slug": "fixture", "name": "Fixture"},
                "dataset_repo_id": "justicedao/ipfs_fixture_laws_ir",
                "source": {"source_dataset": "endomorphosis/ipfs_fixture_laws", "source_revision": "rev"},
                "counts": {"corpus_rows": 2, "n_laws": 1, "n_articles": 1},
                "bm25": {},
                "graph": {},
                "vector": {"dimension": 384, "model_name": "thenlper/gte-small"},
            }
        ),
        encoding="utf-8",
    )
    (stub / "README.md").write_text("# justicedao/ipfs_fixture_laws_ir\n\nFixture laws IR release.\n", encoding="utf-8")
    ensure_dataset_card(stub)
    repaired = (stub / "README.md").read_text(encoding="utf-8")
    assert repaired.startswith("---")
    assert yaml.safe_load(repaired.split("---", 2)[1])["pretty_name"].startswith("Fixture")


def test_corpus_delta_to_dict_is_compact_by_default() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.incremental import (
        CorpusDelta,
    )

    delta = CorpusDelta(
        added_cids=tuple(f"add-{i}" for i in range(20)),
        removed_cids=("rm-1",),
        unchanged_cids=("keep-1", "keep-2"),
        prior_count=3,
        current_count=21,
        changed_ratio=0.9,
    )
    compact = delta.to_dict()
    assert compact["n_added"] == 20
    assert "added_cids" not in compact
    assert compact["added_cids_sample"] == [f"add-{i}" for i in range(8)]
    full = delta.to_dict(include_cids=True)
    assert len(full["added_cids"]) == 20


def test_fetch_hub_prior_returns_none_when_repo_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from huggingface_hub.errors import RepositoryNotFoundError

    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.incremental import (
        fetch_hub_prior,
    )

    def _boom(*_args, **_kwargs):
        raise RepositoryNotFoundError("missing")

    monkeypatch.setattr("huggingface_hub.snapshot_download", _boom)
    assert fetch_hub_prior("not_a_country", dest=tmp_path / "prior") is None


def test_prior_dir_prefers_local_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir import build as build_mod

    local = tmp_path / "ipfs_fixture_laws_ir"
    local.mkdir()
    (local / "manifest.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(build_mod, "RELEASES", tmp_path)
    got = build_mod._prior_dir_for("fixture", local, None, fetch_hub=False)
    assert got == local


def test_diff_corpus_detects_added_and_removed_cids() -> None:
    prior = _corpus_for("Customs Act", "Ports Act")
    current = _corpus_for("Customs Act", "Aviation Act")
    delta = diff_corpus(prior, current)
    assert delta.n_unchanged == 1
    assert delta.n_added == 1
    assert delta.n_removed == 1
    assert 0.0 < delta.changed_ratio < 1.0
    assert delta.equivalent_to_full is False


def test_plan_rebuild_does_not_skip_stub_vectors_when_source_matches() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.incremental import (
        PriorRelease,
        RebuildKind,
        plan_rebuild,
    )

    corpus = _corpus_for("Customs Act")
    source = _source_meta("rev-a")
    prior = PriorRelease(
        directory=Path("/tmp/unused"),
        manifest={
            "dataset_revision": "rev-a",
            "input_sha256": {
                "laws.parquet": "laws-rev-a",
                "articles.parquet": "arts-rev-a",
            },
            "vector": {"status": "stub"},
        },
        corpus=corpus,
    )
    plan = plan_rebuild(mode="auto", source_meta=source, prior=prior, current_corpus=corpus)
    assert plan.kind is RebuildKind.DELTA_REFRESH
    assert plan.skip_build is False


def test_title_shell_article_copies_the_parent_span_until_the_next_heading() -> None:
    parent = (
        "Advisory Council Procedure Rules for Belize\n"
        "The Council shall hear every appeal lodged under this rule.\n"
        "Public Service Regulations for the Constitution\n"
        "The Commission shall keep a register of every officer."
    )
    laws = _laws(
        {
            "id": "law-1",
            "title": "Belize Constitution Subsidiary Rules",
            "text": parent,
            "jurisdiction": "Belize",
            "country": "Belize",
            "language": "en",
            "source_url": "https://example.test/bz",
            "license": "cc0",
            "metadata_json": "{}",
        }
    )
    articles = _articles(
        {
            "id": "a1",
            "law_id": "law-1",
            "title": "Advisory Council Procedure Rules for Belize",
            "text": "Advisory Council Procedure Rules for Belize",
            "article_number": "1",
            "metadata_json": "{}",
        },
        {
            "id": "a2",
            "law_id": "law-1",
            "title": "Public Service Regulations for the Constitution",
            "text": "Public Service Regulations for the Constitution",
            "article_number": "2",
            "metadata_json": "{}",
        },
    )
    corpus, report = build_corpus(laws, articles, _source_meta("rev-a"))
    by_source = {row.source_id: row.body for row in corpus.itertuples(index=False)}
    assert "shall hear every appeal" in by_source["a1"]
    assert "shall keep a register" in by_source["a2"]
    assert "shall hear every appeal" not in by_source["a2"]
    assert int((corpus["record_type"] == "law").sum()) == 1
    assert report["n_law_rows"] == 1
    assert "The Council shall hear every appeal" in parent


def test_thin_article_rows_are_replaced_from_the_parent_law() -> None:
    sections = [
        (
            "Article 1",
            "The court shall apply this Act throughout the territory and bind every person.",
        ),
        (
            "Article 2",
            "The Minister shall appoint the roads authority by notice in the Gazette.",
        ),
        (
            "Article 3",
            "The authority shall maintain every public road in a safe condition.",
        ),
        (
            "Article 4",
            "A person who damages a public road commits an offence under this Act.",
        ),
    ]
    parent = "\n\n".join(f"{heading}\n{body}" for heading, body in sections)
    laws = _laws(
        {
            "id": "law-thin",
            "title": "Public Roads Act",
            "text": parent,
            "jurisdiction": "Fixture",
            "country": "Fixture",
            "language": "en",
            "source_url": "https://example.test/roads",
            "license": "cc0",
            "metadata_json": "{}",
        },
        {
            "id": "law-rich",
            "title": "Ports Act",
            "text": "Article 1\n" + ("The harbour master shall keep the register of ships. " * 12),
            "jurisdiction": "Fixture",
            "country": "Fixture",
            "language": "en",
            "source_url": "https://example.test/ports",
            "license": "cc0",
            "metadata_json": "{}",
        },
    )
    articles = _articles(
        *[
            {
                "id": f"toc-{number}",
                "law_id": "law-thin",
                "title": heading,
                "text": heading,
                "article_number": str(number),
                "metadata_json": "{}",
            }
            for number, (heading, _body) in enumerate(sections, start=1)
        ],
        {
            "id": "ports-1",
            "law_id": "law-rich",
            "title": "Article 1",
            "text": "The harbour master shall keep the register of ships. " * 12,
            "article_number": "1",
            "metadata_json": "{}",
        },
    )
    corpus, report = build_corpus(laws, articles, _source_meta("rev-a"))
    thin_kids = corpus[corpus["instrument_id"] == "law-thin"]
    thin_kids = thin_kids[thin_kids["record_type"] != "law"]
    joined = "\n".join(thin_kids["body"].astype(str))
    assert "shall apply this Act" in joined
    assert "shall appoint the roads authority" in joined
    assert "commits an offence" in joined
    assert "toc-1" not in set(thin_kids["source_id"])
    assert report["n_thin_instruments_replaced"] == 1
    ports = corpus.loc[corpus["source_id"] == "ports-1", "body"].iloc[0]
    assert "harbour master" in ports
    assert int((corpus["record_type"] == "law").sum()) == 2


def test_childless_law_is_split_when_the_country_has_other_articles() -> None:
    bare = (
        "Article 1\n"
        "The court shall apply this Act throughout the territory and bind every person. "
        "The obligation applies in every district and binds every public authority.\n\n"
        "Article 2\n"
        "The Minister shall appoint the roads authority by notice in the Gazette. "
        "The notice shall state the roads for which the authority is responsible."
    )
    laws = _laws(
        {
            "id": "law-bare",
            "title": "Public Roads Act",
            "text": bare,
            "jurisdiction": "Fixture",
            "country": "Fixture",
            "language": "en",
            "source_url": "https://example.test/bare",
            "license": "cc0",
            "metadata_json": "{}",
        },
        {
            "id": "law-rich",
            "title": "Ports Act",
            "text": "Article 1\n" + ("The harbour master shall keep the register of ships. " * 8),
            "jurisdiction": "Fixture",
            "country": "Fixture",
            "language": "en",
            "source_url": "https://example.test/ports",
            "license": "cc0",
            "metadata_json": "{}",
        },
    )
    articles = _articles(
        {
            "id": "ports-1",
            "law_id": "law-rich",
            "title": "Article 1",
            "text": "The harbour master shall keep the register of ships. " * 8,
            "article_number": "1",
            "metadata_json": "{}",
        }
    )
    corpus, report = build_corpus(laws, articles, _source_meta("rev-a"))
    bare_kids = corpus[(corpus["instrument_id"] == "law-bare") & (corpus["record_type"] != "law")]
    joined = "\n".join(bare_kids["body"].astype(str))
    assert "shall apply this Act" in joined
    assert "shall appoint the roads authority" in joined
    assert len(bare_kids) >= 2
    assert report["n_thin_instruments_replaced"] == 1
    assert "harbour master" in corpus.loc[corpus["source_id"] == "ports-1", "body"].iloc[0]


def test_a_law_titled_article_is_a_law_and_a_newsletter_is_not() -> None:
    laws = _laws(
        {
            "id": "law-article-name",
            "title": "Article 6 Loi relative aux routes publiques",
            "text": "The court shall apply this Act throughout the territory and bind every person.",
            "jurisdiction": "Fixture",
            "country": "Fixture",
            "language": "en",
            "source_url": "https://example.test/art6",
            "license": "cc0",
            "metadata_json": json.dumps({"document_type": "statute", "record_type": "law"}),
        },
        {
            "id": "news-1",
            "title": "Newsletter mbi ceshtjet europiane",
            "text": "This newsletter tells readers what the assembly discussed this week.",
            "jurisdiction": "Fixture",
            "country": "Fixture",
            "language": "sq",
            "source_url": "https://example.test/news",
            "license": "cc0",
            "metadata_json": json.dumps({"document_type": "newsletter", "record_type": "newsletter"}),
        },
    )
    corpus, _report = build_corpus(laws, _articles(), _source_meta("rev-a"))
    kinds = dict(zip(corpus["instrument_id"], corpus["record_type"]))
    assert kinds["law-article-name"] == "law"
    assert kinds["news-1"] == "notice"


def test_short_heading_is_not_replaced_from_the_parent() -> None:
    laws = _laws(
        {
            "id": "law-1",
            "title": "Gazette Act",
            "text": "Article 1\nThe Minister shall publish the order.\nArticle 2\nThis Act binds the Crown.",
            "jurisdiction": "Fixture",
            "country": "Fixture",
            "language": "en",
            "source_url": "https://example.test/g",
            "license": "cc0",
            "metadata_json": "{}",
        }
    )
    articles = _articles(
        {
            "id": "a1",
            "law_id": "law-1",
            "title": "Article 1",
            "text": "Article 1",
            "article_number": "1",
            "metadata_json": "{}",
        }
    )
    corpus, _report = build_corpus(laws, articles, _source_meta("rev-a"))
    body = corpus.loc[corpus["source_id"] == "a1", "body"].iloc[0]
    assert body == "Article 1"
    assert "shall publish" not in body


def test_plan_rebuild_skips_matching_source_fingerprint() -> None:
    corpus = _corpus_for("Customs Act")
    source = _source_meta("rev-a")
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.incremental import (
        PriorRelease,
    )

    prior = PriorRelease(
        directory=Path("/tmp/unused"),
        manifest={
            "dataset_revision": "rev-a",
            "input_sha256": {
                "laws.parquet": "laws-rev-a",
                "articles.parquet": "arts-rev-a",
            },
        },
        corpus=corpus,
    )
    plan = plan_rebuild(mode="auto", source_meta=source, prior=prior, current_corpus=corpus)
    assert plan.kind is RebuildKind.UNCHANGED
    assert plan.skip_build is True
    assert plan.equivalent_to_full is False
    assert plan.reuse_embeddings is True


def test_compare_normalized_reindexes_only_changed_rows() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.incremental import (
        PriorRelease,
    )

    prior_corpus = _corpus_for("Customs Act", "Ports Act")
    same = _corpus_for("Customs Act", "Ports Act")
    changed = _corpus_for("Customs Act", "Aviation Act")
    source = _source_meta("rev-a")
    prior = PriorRelease(
        directory=Path("/tmp/unused"),
        manifest={
            "dataset_revision": "rev-a",
            "input_sha256": {
                "laws.parquet": "laws-rev-a",
                "articles.parquet": "arts-rev-a",
            },
        },
        corpus=prior_corpus,
    )
    untouched = plan_rebuild(
        mode="auto",
        source_meta=source,
        prior=prior,
        current_corpus=same,
        compare_normalized=True,
    )
    assert untouched.kind is RebuildKind.UNCHANGED
    assert untouched.skip_build is True
    assert untouched.delta is not None
    assert untouched.delta.n_added == 0
    moved = plan_rebuild(
        mode="auto",
        source_meta=source,
        prior=prior,
        current_corpus=changed,
        compare_normalized=True,
    )
    assert moved.kind is RebuildKind.DELTA_REFRESH
    assert moved.skip_build is False
    assert moved.reuse_embeddings is True
    assert moved.delta is not None
    assert moved.delta.n_added == 1
    assert moved.delta.n_unchanged == 1


def test_plan_rebuild_delta_reuses_embeddings_when_source_changes() -> None:
    prior_corpus = _corpus_for("Customs Act", "Ports Act", revision="rev-a")
    current = _corpus_for("Customs Act", "Aviation Act", revision="rev-b")
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.incremental import (
        PriorRelease,
    )

    prior = PriorRelease(
        directory=Path("/tmp/unused"),
        manifest={
            "dataset_revision": "rev-a",
            "input_sha256": {
                "laws.parquet": "laws-rev-a",
                "articles.parquet": "arts-rev-a",
            },
        },
        corpus=prior_corpus,
    )
    plan = plan_rebuild(
        mode=BuildMode.AUTO,
        source_meta=_source_meta("rev-b"),
        prior=prior,
        current_corpus=current,
    )
    assert plan.kind is RebuildKind.DELTA_REFRESH
    assert plan.skip_build is False
    assert plan.reuse_embeddings is True
    assert plan.equivalent_to_full is False
    assert plan.delta is not None
    assert plan.delta.n_added == 1
    assert plan.delta.n_removed == 1


def test_plan_rebuild_full_when_no_prior() -> None:
    current = _corpus_for("Customs Act")
    plan = plan_rebuild(mode="auto", source_meta=_source_meta("rev-a"), prior=None, current_corpus=current)
    assert plan.kind is RebuildKind.FULL_REBUILD
    assert plan.equivalent_to_full is True
    assert plan.reuse_embeddings is False


def test_select_device_prefers_cuda_when_available() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.vectors import (
        select_device,
    )

    device, fallback = select_device("cuda")
    assert device in {"cuda", "cpu"}
    if device == "cpu":
        assert fallback is True
    auto, auto_fallback = select_device("auto")
    assert auto in {"cuda", "cpu"}


def test_assemble_embeddings_does_not_reuse_zero_stub_vectors() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.vectors import (
        DIMENSION,
        assemble_embeddings,
    )

    corpus = _corpus_for("Customs Act")
    cid = corpus["entry_cid"].iloc[0]
    stub = {cid: [0.0] * DIMENSION}
    _matrix, report = assemble_embeddings(corpus, stub, encode_missing=False)
    assert report["n_reused"] == 0
    assert report["n_missing"] == 1
    assert report["status"] == "incomplete"


def test_assemble_embeddings_reuses_unchanged_cids_without_encoder() -> None:
    corpus = _corpus_for("Customs Act", "Ports Act")
    fake = {
        cid: np.full(DIMENSION, float(i + 1), dtype=np.float32).tolist()
        for i, cid in enumerate(corpus["entry_cid"].tolist())
    }
    matrix, report = assemble_embeddings(corpus, fake, encode_missing=False)
    assert report["n_reused"] == 2
    assert report["n_missing"] == 0
    assert report["status"] == "reused"
    assert matrix.shape == (2, DIMENSION)
    np.testing.assert_allclose(np.linalg.norm(matrix, axis=1), 1.0, rtol=1e-5)


def test_assemble_embeddings_marks_new_cids_incomplete_without_encoder() -> None:
    prior = _corpus_for("Customs Act")
    current = _corpus_for("Customs Act", "Aviation Act")
    fake = {
        prior["entry_cid"].iloc[0]: np.ones(DIMENSION, dtype=np.float32).tolist(),
    }
    matrix, report = assemble_embeddings(current, fake, encode_missing=False)
    assert report["n_reused"] == 1
    assert report["n_missing"] == 1
    assert report["status"] == "incomplete"
    assert matrix.shape == (2, DIMENSION)


def test_embeddings_from_vector_table_skips_stub_nulls() -> None:
    frame = pd.DataFrame(
        {
            "entry_cid": ["bafkreiabc", "bafkreidef"],
            "embedding": [None, [0.1] * DIMENSION],
        }
    )
    by_cid = embeddings_from_vector_table(frame)
    assert "bafkreiabc" not in by_cid
    assert len(by_cid["bafkreidef"]) == DIMENSION


def test_source_fingerprint_changes_with_parquet_digest() -> None:
    a = source_fingerprint(_source_meta("rev-a"))
    b = source_fingerprint(_source_meta("rev-a", extra={"laws_sha256": "changed"}))
    assert a != b


def test_raw_package_merges_new_instruments(tmp_path: Path) -> None:
    first = tmp_path / "instruments"
    first.mkdir()
    (first / "a.json").write_text(
        json.dumps(
            {
                "id": "law-a",
                "title": "Customs Act",
                "text": "Official customs body. " * 20,
                "source_url": "https://example.test/a",
                "source_type": "official",
                "jurisdiction": "Fixture",
                "country": "Fixture",
                "language": "en",
                "license": "cc0",
                "law_status": "in_force",
                "identifier": "law-a",
                "retrieved_at": "2026-01-01T00:00:00Z",
                "documents": [
                    {
                        "id": "art-a-1",
                        "title": "Article 1",
                        "text": "Definitions and scope.",
                        "article_number": "1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "pack"
    meta = package_instruments(
        instruments_dir=first,
        out=out,
        slug="fixture",
        source_dataset="endomorphosis/ipfs_fixture_laws",
    )
    assert meta["n_laws"] == 1
    assert meta["n_articles"] == 1
    assert (out / "data" / "laws.parquet").is_file()
    assert (out / "pack_meta.json").is_file()

    second = tmp_path / "instruments2"
    second.mkdir()
    (second / "b.json").write_text(
        json.dumps(
            {
                "id": "law-b",
                "title": "Aviation Act",
                "text": "Official aviation body. " * 20,
                "source_url": "https://example.test/b",
                "jurisdiction": "Fixture",
                "country": "Fixture",
                "language": "en",
                "retrieved_at": "2026-02-01T00:00:00Z",
                "documents": [],
            }
        ),
        encoding="utf-8",
    )
    meta2 = package_instruments(
        instruments_dir=second,
        out=out,
        slug="fixture",
        source_dataset="endomorphosis/ipfs_fixture_laws",
        prior_pack=out,
    )
    assert meta2["n_laws"] == 2
    laws = pd.read_parquet(out / "data" / "laws.parquet")
    assert set(laws["id"]) == {"law-a", "law-b"}


def test_merge_laws_prefers_newer_retrieved_at() -> None:
    prior = pd.DataFrame(
        [
            {
                "id": "law-a",
                "title": "Old title",
                "text": "old body " * 20,
                "retrieved_at": "2026-01-01T00:00:00Z",
            }
        ]
    )
    incoming = pd.DataFrame(
        [
            {
                "id": "law-a",
                "title": "New title",
                "text": "new body " * 20,
                "retrieved_at": "2026-03-01T00:00:00Z",
            }
        ]
    )
    merged = merge_laws(prior, incoming)
    assert list(merged["title"]) == ["New title"]
    arts = merge_articles(
        pd.DataFrame([{"id": "art-1", "law_id": "law-a", "title": "A", "text": "x"}]),
        pd.DataFrame([{"id": "art-1", "law_id": "law-a", "title": "B", "text": "y"}]),
    )
    assert list(arts["title"]) == ["B"]


def test_instruments_drop_short_bodies_instead_of_inventing_text(tmp_path: Path) -> None:
    folder = tmp_path / "instruments"
    folder.mkdir()
    (folder / "short.json").write_text(
        json.dumps({"id": "x", "title": "Too short", "text": "hi"}),
        encoding="utf-8",
    )
    laws, _arts, report = instruments_to_frames(folder)
    assert laws.empty
    assert report["skipped_short_or_empty"] == 1
    assert report["never_invented_legal_text"] is True


def test_upload_rejects_protected_justicedao_repos(tmp_path: Path) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.upload import (
        UploadError,
        upload_release,
    )

    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(UploadError, match="protected"):
        upload_release(tmp_path, "justicedao/ipfs_state_laws")


def test_upload_rejects_non_justicedao_repo(tmp_path: Path) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.upload import (
        UploadError,
        upload_release,
    )

    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(UploadError, match="justicedao"):
        upload_release(tmp_path, "endomorphosis/ipfs_malta_laws_ir")


def test_load_local_source_allows_missing_articles_parquet(tmp_path: Path) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.normalize import (
        build_corpus,
        load_local_source,
    )

    pack = tmp_path / "pack"
    (pack / "data").mkdir(parents=True)
    laws = _laws(
        {
            "id": "law-1",
            "title": "Gazette Act",
            "text": "Official gazette body. " * 20,
            "jurisdiction": "Fixture",
            "country": "Fixture",
            "language": "en",
            "source_url": "https://example.test/1",
            "license": "cc0",
            "eli": "",
            "identifier": "law-1",
            "official_identifier": "LAW-1",
            "source_type": "official",
            "law_status": "in_force",
            "metadata_json": "{}",
        }
    )
    laws.to_parquet(pack / "data" / "laws.parquet", index=False)
    loaded_laws, loaded_arts, meta = load_local_source(pack)
    assert len(loaded_laws) == 1
    assert loaded_arts.empty
    assert meta["articles_path"] is None
    corpus, report = build_corpus(loaded_laws, loaded_arts, meta)
    assert report["unit"] == "law"
    assert len(corpus) == 1


def test_recursive_clusters_splits_identical_vectors_without_recursion() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.vectors import (
        DIMENSION,
        _recursive_clusters,
    )

    x = np.ones((9000, DIMENSION), dtype=np.float32)
    clusters = _recursive_clusters(x, max_size=4096)
    assert sum(len(c) for c in clusters) == 9000
    assert all(len(c) <= 4096 for c in clusters)
    assert len(clusters) >= 2


def test_classify_gap_detects_missing_stale_and_incomplete() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.coverage import (
        classify_gap,
    )

    missing = classify_gap(ir_files=None)
    assert missing["status"] == "missing"
    assert missing["rebuild"] is True

    unpublished = classify_gap(
        ir_files=None,
        local_only=True,
        source_revision="abc",
        local_source_revision="abc",
    )
    assert unpublished["status"] == "unpublished"
    assert unpublished["rebuild"] is False
    assert unpublished["publish"] is True

    stale = classify_gap(
        source_revision="new",
        ir_source_revision="old",
        ir_files=["manifest.json", "data/corpus/part-000000.parquet", "data/bm25/x", "data/graph/y"],
        ir_corpus_rows=10,
    )
    assert stale["status"] == "stale"
    assert "stale_source_revision" in stale["issues"]

    incomplete = classify_gap(
        ir_files=["manifest.json"],
        ir_corpus_rows=0,
        source_revision="abc",
        ir_source_revision="abc",
    )
    assert incomplete["status"] == "incomplete"
    assert "ir_missing_corpus" in incomplete["issues"]
    assert "ir_empty_corpus" in incomplete["issues"]

    stub = classify_gap(
        source_revision="abc",
        ir_source_revision="abc",
        ir_files=["manifest.json", "data/corpus/a", "data/bm25/b", "data/graph/c"],
        ir_corpus_rows=12,
        vector_status="stub",
    )
    assert stub["status"] == "stub_vectors"
    assert stub["rebuild"] is True

    current = classify_gap(
        source_revision="abc",
        ir_source_revision="abc",
        ir_files=["manifest.json", "data/corpus/a", "data/bm25/b", "data/graph/c"],
        ir_corpus_rows=12,
        vector_status="embedded",
    )
    assert current["status"] == "current"
    assert current["rebuild"] is False
    assert current["publish"] is False


def test_coverage_canonical_slug_collapses_alias_spellings() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.coverage import (
        canonical_slug,
    )

    assert canonical_slug("northkorea") == "northkorea"
    assert canonical_slug("north_korea") == "northkorea"
    assert canonical_slug("papua_new_guinea") == "papuanewguinea"


def test_cli_help_exposes_incremental_commands() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(["build", "--help"])
    assert exc.value.code == 0
    with pytest.raises(SystemExit) as help_exc:
        main(["reindex", "--help"])
    assert help_exc.value.code == 0


def test_build_country_skips_unchanged_local_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir import build as build_mod

    monkeypatch.setattr(build_mod, "ROOT", tmp_path)
    monkeypatch.setattr(build_mod, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(build_mod, "RELEASES", tmp_path / "releases")
    monkeypatch.setattr(build_mod, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(build_mod, "PROGRESS", tmp_path / "progress.jsonl")
    (tmp_path / "cache").mkdir()
    (tmp_path / "releases").mkdir()
    (tmp_path / "reports").mkdir()

    pack = tmp_path / "pack"
    laws = _laws(
        {
            "id": "law-1",
            "title": "Customs Act",
            "text": "Official customs body text. " * 20,
            "jurisdiction": "Fixture",
            "country": "Fixture",
            "language": "en",
            "source_url": "https://example.test/1",
            "license": "cc0",
            "eli": "",
            "identifier": "law-1",
            "official_identifier": "LAW-1",
            "source_type": "official",
            "law_status": "in_force",
            "metadata_json": "{}",
            "article_count": 0,
        }
    )
    articles = _articles()
    (pack / "data").mkdir(parents=True)
    laws.to_parquet(pack / "data" / "laws.parquet", index=False)
    articles.to_parquet(pack / "data" / "articles.parquet", index=False)
    (pack / "pack_meta.json").write_text(
        json.dumps(
            {
                "slug": "fixture",
                "repo": "endomorphosis/ipfs_fixture_laws",
                "source_dataset": "endomorphosis/ipfs_fixture_laws",
                "source_revision": "rev-local-1",
                "indexable": True,
                "name": "Fixture",
            }
        ),
        encoding="utf-8",
    )

    first = build_mod.build_country(
        str(pack),
        out=tmp_path / "releases" / "ipfs_fixture_laws_ir",
        skip_vectors=True,
        mode="auto",
        fetch_hub_prior_ir=False,
    )
    assert first["skipped"] is False
    assert first["target_hub_id"] == "justicedao/ipfs_fixture_laws_ir"
    assert (tmp_path / "releases" / "ipfs_fixture_laws_ir" / "manifest.json").is_file()

    second = build_mod.build_country(
        str(pack),
        out=tmp_path / "releases" / "ipfs_fixture_laws_ir",
        skip_vectors=True,
        mode="auto",
        fetch_hub_prior_ir=False,
    )
    assert second["skipped"] is True
    assert second["incremental"]["kind"] == "unchanged"

    extra = _laws(
        {
            "id": "law-1",
            "title": "Customs Act",
            "text": "Official customs body text. " * 20,
            "jurisdiction": "Fixture",
            "country": "Fixture",
            "language": "en",
            "source_url": "https://example.test/1",
            "license": "cc0",
            "eli": "",
            "identifier": "law-1",
            "official_identifier": "LAW-1",
            "source_type": "official",
            "law_status": "in_force",
            "metadata_json": "{}",
            "article_count": 0,
        },
        {
            "id": "law-2",
            "title": "Aviation Act",
            "text": "Official aviation body text. " * 20,
            "jurisdiction": "Fixture",
            "country": "Fixture",
            "language": "en",
            "source_url": "https://example.test/2",
            "license": "cc0",
            "eli": "",
            "identifier": "law-2",
            "official_identifier": "LAW-2",
            "source_type": "official",
            "law_status": "in_force",
            "metadata_json": "{}",
            "article_count": 0,
        },
    )
    extra.to_parquet(pack / "data" / "laws.parquet", index=False)
    (pack / "pack_meta.json").write_text(
        json.dumps(
            {
                "slug": "fixture",
                "repo": "endomorphosis/ipfs_fixture_laws",
                "source_dataset": "endomorphosis/ipfs_fixture_laws",
                "source_revision": "rev-local-2",
                "indexable": True,
                "name": "Fixture",
            }
        ),
        encoding="utf-8",
    )
    third = build_mod.build_country(
        str(pack),
        out=tmp_path / "releases" / "ipfs_fixture_laws_ir",
        skip_vectors=True,
        mode="auto",
        fetch_hub_prior_ir=False,
    )
    assert third["skipped"] is False
    assert third["incremental"]["kind"] == "delta_refresh"
    assert third["incremental"]["delta"]["n_added"] == 1
    assert third["counts"]["corpus_rows"] == 2
