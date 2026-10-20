"""Country-source rows fill a national gap only when they stay queryable laws."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.admit import (
    admit_source_law,
    fill_country_corpus,
    fill_country_parquet,
    fill_source_rows,
    national_gap_plan,
)

_SHA = "b" * 40
_ACT = (
    "Article 1 This Act applies throughout the territory.\n"
    "Article 2 The minister shall keep the register.\n"
)


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "fr-1",
        "title": "Loi exemple",
        "text": _ACT,
        "source_url": "https://example.test/fr/loi",
        "language": "fr",
        "jurisdiction": "FR",
        "country": "France",
        "metadata_json": "{}",
    }
    row.update(overrides)
    return row


def test_a_statute_from_a_country_dataset_fills_queryable_atoms() -> None:
    decision = admit_source_law(
        _row(),
        source_dataset="endomorphosis/ipfs_france_laws",
        source_revision=_SHA,
    )
    assert decision.admitted is True
    assert decision.reason == "law"
    assert len(decision.records) == 2
    assert decision.records[0]["text"].startswith("Article 1")
    assert decision.records[0]["provenance"]["article"] == "1"
    assert decision.records[1]["provenance"]["article"] == "2"
    assert "Article 2" in decision.records[1]["provenance"]["hierarchy_path"]
    assert decision.records[0]["jurisdiction"] == "FR"
    assert decision.records[0]["source_repo"] == "endomorphosis/ipfs_france_laws"
    assert "<" not in str(decision.records[0]["text"])


def test_unrelated_source_rows_are_refused_without_text() -> None:
    cases = {
        "informative": _row(
            title="Search",
            text="Home\nSearch\nContact us\nThis website uses cookies\n",
            source_url="https://example.test/search",
        ),
        "metadata": _row(
            title="Reife- und Diplomprüfung sowie Diplomprüfung in der Bildungsanstalt",
            text="Reife- und Diplomprüfung sowie Diplomprüfung in der Bildungsanstalt",
            jurisdiction="AT",
            language="de",
        ),
        "notice": _row(
            title="Newsletter mbi ceshtjet europiane",
            text="This newsletter tells readers what the assembly discussed this week.",
            metadata_json='{"document_type": "newsletter"}',
        ),
        "not_queryable": _row(title="Code civil", text="Les lois"),
        "empty": _row(text="The incident id is 42"),
        "unofficial": _row(source_official=False),
    }
    for reason, row in cases.items():
        decision = admit_source_law(
            row,
            source_dataset="endomorphosis/ipfs_france_laws",
            source_revision=_SHA,
        )
        assert decision.admitted is False
        assert decision.reason == reason
        assert decision.records == ()


def test_an_operative_provision_and_a_numbered_article_body_are_queryable() -> None:
    provision = admit_source_law(
        _row(
            text="The court shall apply this Act throughout the territory and bind every person.",
        ),
        source_dataset="endomorphosis/ipfs_france_laws",
        source_revision=_SHA,
    )
    assert provision.admitted is True
    assert provision.records[0]["text"].startswith("The court shall apply")
    numbered = admit_source_law(
        _row(
            id="art-1103",
            article_number="1103",
            title="Article 1103",
            text="Les contrats légalement formés tiennent lieu de loi à ceux qui les ont faits.",
        ),
        source_dataset="endomorphosis/ipfs_france_laws",
        source_revision=_SHA,
    )
    assert numbered.admitted is True
    assert numbered.records[0]["provenance"]["statute"] == "1103"
    assert "contrats" in str(numbered.records[0]["text"])


def test_excluded_and_municipal_sources_do_not_fill_the_national_card() -> None:
    statute = _row(
        jurisdiction="BE",
        country="Belgium",
        text=_ACT,
    )
    excluded = admit_source_law(
        statute,
        source_dataset="endomorphosis/ipfs_belgium_laws",
        source_revision=_SHA,
    )
    municipal = admit_source_law(
        _row(),
        source_dataset="endomorphosis/ipfs_france_municipal_laws",
        source_revision=_SHA,
    )
    assert excluded.reason == "excluded"
    assert excluded.records == ()
    assert municipal.reason == "not_national"
    assert municipal.records == ()


def test_a_document_id_does_not_admit_a_caption_or_a_label_table() -> None:
    article = admit_source_law(
        _row(
            id="py-115",
            title="Art. 115.",
            article_number="Art. 115.",
            official_identifier="12907",
            language="es",
            jurisdiction="PY",
            country="Paraguay",
            text=(
                "Art. 115.\n"
                "Tabacos, cigarrillos, esencias y similares.\n"
                "Los bienes que se establecen en la siguiente tabla de tributación, "
                "quedarán gravados de acuerdo con la tasa impositiva que sigue."
            ),
        ),
        source_dataset="endomorphosis/ipfs_paraguay_laws",
        source_revision=_SHA,
    )
    assert article.admitted is True
    assert article.records[0]["provenance"]["article"] == "115"
    assert article.records[0]["provenance"]["section"] == "115"
    assert article.records[0]["provenance"].get("statute") != "12907"
    caption = admit_source_law(
        _row(
            title="CAPÍTULO II",
            article_number="CAPÍTULO II",
            official_identifier="12907",
            language="es",
            jurisdiction="PY",
            text="CAPÍTULO II\nAUTORIDAD DE APLICACIÓN Y ÁMBITO DE COMPETENCIA",
        ),
        source_dataset="endomorphosis/ipfs_paraguay_laws",
        source_revision=_SHA,
    )
    assert caption.admitted is False
    assert caption.reason == "not_queryable"
    assert caption.records == ()
    table = admit_source_law(
        _row(
            title="1. Grupi ligjor 3",
            article_number="1",
            official_identifier="122679",
            language="sq",
            jurisdiction="XK",
            text=(
                "1. Grupi ligjor 3\n"
                "mbështetje ligjore\n"
                "Zyrtar për përpunimin e Profesional 2"
            ),
        ),
        source_dataset="endomorphosis/ipfs_kosovo_laws",
        source_revision=_SHA,
    )
    assert table.admitted is False
    assert table.reason == "not_queryable"
    assert table.records == ()


def test_one_leading_heading_becomes_a_query_locator() -> None:
    neni = admit_source_law(
        _row(
            title="Neni 1 Article 1 Član 1",
            article_number="Neni 1",
            official_identifier="10000",
            language="sq",
            jurisdiction="XK",
            text=(
                "Neni 1 Article 1 Član 1\n"
                "Qëllimi Purpose Svrha\n"
                "Kjo rregullore përcakton autoritetet për miratimin e medaljeve."
            ),
        ),
        source_dataset="endomorphosis/ipfs_kosovo_laws",
        source_revision=_SHA,
    )
    assert neni.admitted is True
    assert neni.records[0]["provenance"]["article"] == "1"
    assert neni.records[0]["provenance"]["section"] == "1"
    assert neni.records[0]["provenance"].get("statute") != "10000"
    assert "medaljeve" in str(neni.records[0]["text"])
    ordinance = admit_source_law(
        _row(
            title="2. Application.",
            article_number="paragraph 2",
            official_identifier="Ordinance nr. 16 of 2006",
            language="en",
            text="2. This Ordinance applies to all areas in the City.",
        ),
        source_dataset="endomorphosis/ipfs_uganda_laws",
        source_revision=_SHA,
    )
    assert ordinance.admitted is True
    assert ordinance.records[0]["provenance"]["section"] == "2"
    assert ordinance.records[0]["provenance"]["statute"] == "Ordinance nr. 16 of 2006"
    chapter = admit_source_law(
        _row(
            title="Chapter 1",
            language="en",
            text=(
                "Chapter 1\n"
                "This Act applies throughout the territory and binds every person who resides there."
            ),
        ),
        source_dataset="endomorphosis/ipfs_uganda_laws",
        source_revision=_SHA,
    )
    assert chapter.admitted is True
    assert chapter.records[0]["provenance"]["chapter"] == "1"
    thai = admit_source_law(
        _row(
            title="มาตรา ๒๒",
            article_number="22",
            language="th",
            jurisdiction="TH",
            text=(
                "มาตรา ๒๒ แห่งพระราชบัญญัติล้มละลาย พุทธศักราช ๒๔๘๓\n"
                "และบุคคลผู้เป็นหนี้ลูกหนี้หรือมีทรัพย์สินของลูกหนี้อยู่ในครอบครอง"
            ),
        ),
        source_dataset="endomorphosis/ipfs_thailand_laws",
        source_revision=_SHA,
    )
    assert thai.admitted is True
    assert thai.records[0]["provenance"]["article"] == "22"
    assert thai.records[0]["provenance"]["section"] == "22"
    mislabeled = admit_source_law(
        _row(
            title="Article 81",
            language="ar",
            jurisdiction="TN",
            text=(
                "Article 81.- Le jet de bagages et de marchandises indispensable "
                "à la sécurité de l'aéronef n'engage que la responsabilité du transporteur."
            ),
        ),
        source_dataset="endomorphosis/ipfs_tunisia_laws",
        source_revision=_SHA,
    )
    assert mislabeled.admitted is True
    assert mislabeled.records[0]["provenance"]["article"] == "81"
    assert mislabeled.records[0]["provenance"]["section"] == "81"
    listing = admit_source_law(
        _row(
            title="LISTA 08-2026 PER PUBLIKIMIN E KERKESAVE",
            official_identifier="122759",
            language="sq",
            text=(
                "Agjencia Kosovare për Krahasim dhe Verifikim të Pronës është Agjenci e pavarur.\n"
                "The Agency is an independent Agency established pursuant to Article 142."
            ),
        ),
        source_dataset="endomorphosis/ipfs_kosovo_laws",
        source_revision=_SHA,
    )
    assert listing.admitted is False
    assert listing.reason == "notice"
    assert listing.records == ()
    menu = admit_source_law(
        _row(
            title="สำนักคณะกรรมการ",
            official_identifier="สำนักคณะกรรมการ",
            language="th",
            text="กฎหมาย ช่วยเหลือ รัฐธรรมนูญ พระราชบัญญัติ ประมวลกฎหมาย สนธิสัญญา แสดงกฎหมายปัจจุบัน",
        ),
        source_dataset="endomorphosis/ipfs_thailand_laws",
        source_revision=_SHA,
    )
    assert menu.admitted is False
    assert menu.reason == "not_queryable"
    assert menu.records == ()


def test_a_local_parquet_fill_writes_only_queryable_laws(tmp_path: Path) -> None:
    source = tmp_path / "laws.parquet"
    pq.write_table(
        pa.table(
            {
                "id": ["fr-1", "site", "cap"],
                "title": ["Loi exemple", "Search", "CAPÍTULO II"],
                "body": [
                    _ACT,
                    "Home\nSearch\nContact us\nThis website uses cookies\n",
                    "CAPÍTULO II\nAUTORIDAD DE APLICACIÓN Y ÁMBITO DE COMPETENCIA",
                ],
                "language": ["fr", "fr", "es"],
                "jurisdiction": ["FR", "FR", "PY"],
                "source_url": [
                    "https://example.test/fr/loi",
                    "https://example.test/search",
                    "https://example.test/py/cap",
                ],
                "article_number": ["", "", "CAPÍTULO II"],
                "official_identifier": ["", "", "12907"],
                "source_revision": [_SHA, _SHA, _SHA],
            }
        ),
        source,
    )
    report = fill_country_parquet(
        source,
        tmp_path / "out",
        source_dataset="endomorphosis/ipfs_france_laws",
        source_revision=_SHA,
    )
    assert report["rows_read"] == 3
    assert report["atoms_written"] == 2
    assert report["atoms_with_locator"] == 2
    assert report["reasons"]["law"] == 1
    assert report["reasons"]["informative"] == 1
    assert report["reasons"]["not_queryable"] == 1
    assert report["coverage"] == "snapshot"
    written = pq.read_table(tmp_path / "out" / "france" / "part-000000.parquet")
    texts = written.column("text").to_pylist()
    assert len(texts) == 2
    assert all(text.startswith("Article ") for text in texts)
    assert "Search" not in "\n".join(texts)
    assert "CAPÍTULO" not in "\n".join(texts)
    assert set(written.column("normalizer_version").to_pylist()) == {"country-source-admit/v1"}
    assert set(written.column("admin_level").to_pylist()) == {"country"}
    provenance = json.loads(written.column("provenance")[0].as_py())
    assert provenance["document_role"] == "law"
    assert provenance["jsonld"]["@type"] == "Legislation"
    assert provenance["jsonld"]["encodingFormat"] == "text/plain"
    saved = json.loads((tmp_path / "out" / "france" / "report.json").read_text(encoding="utf-8"))
    assert saved["atoms_written"] == 2
    try:
        fill_country_parquet(
            source,
            tmp_path / "out",
            source_dataset="endomorphosis/ipfs_belgium_laws",
            source_revision=_SHA,
        )
    except ValueError as exc:
        assert str(exc) == "excluded"
    else:
        raise AssertionError("excluded source was written")
    try:
        fill_country_parquet(
            source,
            tmp_path / "out",
            source_dataset="endomorphosis/ipfs_france_municipal_laws",
            source_revision=_SHA,
        )
    except ValueError as exc:
        assert str(exc) == "not_national"
    else:
        raise AssertionError("municipal source was written")


def test_every_corpus_part_becomes_queryable_atoms(tmp_path: Path) -> None:
    first = tmp_path / "part-000000.parquet"
    second = tmp_path / "part-000001.parquet"
    _write_source(
        first,
        ["fr-1"],
        ["Loi exemple"],
        [_ACT],
        ["fr"],
        ["FR"],
    )
    _write_source(
        second,
        ["fr-2", "site"],
        ["Application", "Search"],
        [
            "The court shall apply this Act to every claim filed in the territory.",
            "Home\nSearch\nContact us\nThis website uses cookies\n",
        ],
        ["fr", "fr"],
        ["FR", "FR"],
    )
    destination = tmp_path / "out" / "france"
    destination.mkdir(parents=True)
    (destination / "part-000009.parquet").write_bytes(b"stale")
    (destination / "report.json").write_text("{}\n", encoding="utf-8")
    report = fill_country_corpus(
        [first, second],
        tmp_path / "out",
        source_dataset="endomorphosis/ipfs_france_laws",
        source_revision=_SHA,
        flush_atoms=1,
    )
    assert report["rows_read"] == 3
    assert report["atoms_written"] == 3
    assert report["atoms_with_locator"] == 2
    assert report["reasons"]["law"] == 2
    assert report["reasons"]["informative"] == 1
    assert report["corpus_complete"] is True
    assert report["source_files"] == ["part-000000.parquet", "part-000001.parquet"]
    parts = sorted(destination.glob("part-*.parquet"))
    assert [path.name for path in parts] == [
        "part-000000.parquet",
        "part-000001.parquet",
        "part-000002.parquet",
    ]
    texts = []
    for part in parts:
        texts.extend(pq.read_table(part).column("text").to_pylist())
    assert texts[0].startswith("Article 1")
    assert texts[1].startswith("Article 2")
    assert texts[2].startswith("The court shall apply")
    assert "Search" not in "\n".join(texts)
    saved = json.loads((destination / "report.json").read_text(encoding="utf-8"))
    assert saved["atoms_written"] == 3
    governorate = admit_source_law(
        _row(jurisdiction="EG", country="Egypt"),
        source_dataset="endomorphosis/ipfs_egypt_governorate_laws",
        source_revision=_SHA,
    )
    assert governorate.admitted is False
    assert governorate.reason == "not_national"
    assert governorate.records == ()
    try:
        fill_country_corpus(
            [first],
            tmp_path / "out",
            source_dataset="endomorphosis/ipfs_south_africa_provincial_laws",
            source_revision=_SHA,
        )
    except ValueError as exc:
        assert str(exc) == "not_national"
    else:
        raise AssertionError("provincial source was written")


def _write_source(
    path: Path,
    ids: list[str],
    titles: list[str],
    bodies: list[str],
    languages: list[str],
    jurisdictions: list[str],
) -> None:
    count = len(ids)
    pq.write_table(
        pa.table(
            {
                "id": ids,
                "title": titles,
                "body": bodies,
                "language": languages,
                "jurisdiction": jurisdictions,
                "source_url": ["https://example.test/fr/loi"] * count,
                "article_number": [""] * count,
                "official_identifier": [""] * count,
                "source_revision": [_SHA] * count,
            }
        ),
        path,
    )


def test_fill_keeps_only_laws_and_the_plan_names_thin_sources() -> None:
    filled = fill_source_rows(
        [
            _row(),
            _row(
                id="site",
                title="Search",
                text="Home\nSearch\nContact us\nThis website uses cookies\n",
                source_url="https://example.test/search",
            ),
        ],
        source_dataset="endomorphosis/ipfs_france_laws",
        source_revision=_SHA,
    )
    assert filled["reasons"]["law"] == 1
    assert filled["reasons"]["informative"] == 1
    assert len(filled["admitted"]) == 2
    assert all(row["provenance"]["document_role"] == "law" for row in filled["admitted"])
    plan = {row["code"]: row for row in national_gap_plan({"AE": 1, "BE": 2, "FR": 400, "ZZ": 1})}
    assert plan["AE"]["action"] == "fill"
    assert plan["AE"]["source_dataset"] == "endomorphosis/ipfs_uae_laws"
    assert plan["AE"]["reason"] == "thin_docs"
    assert plan["BE"]["action"] == "skip"
    assert plan["BE"]["reason"] == "excluded"
    assert "FR" not in plan
    assert "ZZ" not in plan
