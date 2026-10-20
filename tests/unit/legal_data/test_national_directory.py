"""A finished national corpus lists like a code and cites in Bluebook form."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.national_directory import (
    index_national_laws,
    write_national_directory,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.schema import LEGAL_RECORD_FIELDS

_SHA = "a" * 64


def _record(**overrides: object) -> dict[str, object]:
    provenance = {"document_role": "law"}
    supplied = overrides.pop("provenance", None)
    if isinstance(supplied, dict):
        provenance.update(supplied)
    row: dict[str, object] = {field: None for field in LEGAL_RECORD_FIELDS}
    row.update(
        {
            "jurisdiction": "US",
            "admin_level": "country",
            "instrument_type": "statute",
            "title": "United States Code",
            "text": "Every person who, under color of any statute, subjects another.",
            "content_sha256": _SHA,
            "entry_cid": "us-1983",
            "provenance": provenance,
        }
    )
    row.update(overrides)
    return row


def test_a_code_lists_bluebook_cites_and_names_the_missing_section() -> None:
    sections = ["1981", "1983", "1984", "1985"]
    rows = [
        _record(
            entry_cid=f"us-{number}",
            provenance={"section": number, "title": "42"},
        )
        for number in sections
    ]
    rows.append(
        _record(
            entry_cid="fr-1240",
            jurisdiction="FR",
            title="Code civil",
            text="Tout fait quelconque de l'homme, qui cause à autrui un dommage.",
            provenance={"article": "1240", "section": "1240", "title": "I"},
        )
    )
    rows.append(
        _record(
            entry_cid="de-433",
            jurisdiction="DE",
            title="Bürgerliches Gesetzbuch",
            text="Durch den Kaufvertrag wird der Verkäufer einer Sache verpflichtet.",
            provenance={"section": "433", "title": ""},
        )
    )
    rows.append(
        _record(
            entry_cid="mc-220",
            jurisdiction="MC",
            title="Code de procédure civile",
            text="L'opposition devra, à peine de nullité, être notifiée dans la huitaine.",
            provenance={"article": "220", "section": "220", "title": "VII"},
        )
    )
    rows.append(
        _record(
            entry_cid="eu-5",
            jurisdiction="EU",
            title="Regulation (EU) 2016/679",
            text="Personal data shall be processed lawfully, fairly and in a transparent manner.",
            provenance={"article": "5", "section": "5"},
        )
    )
    index = index_national_laws(rows)
    by_id = {entry.entry_cid: entry for entry in index.entries}
    assert by_id["us-1983"].citation == "42 U.S.C. § 1983"
    assert by_id["us-1983"].citation_form == "bluebook"
    assert by_id["us-1983"].path == "United States Code / Title 42 / Section 1983"
    assert by_id["fr-1240"].citation == "C. civ. art. 1240"
    assert by_id["fr-1240"].citation_form == "bluebook"
    assert by_id["fr-1240"].path == "Code civil / Title I / Article 1240"
    assert by_id["de-433"].citation == "BGB § 433"
    assert by_id["mc-220"].citation == "Monaco, Code de procédure civile, tit. VII, art. 220"
    assert by_id["mc-220"].citation_form == "bluebook_analog"
    assert by_id["eu-5"].citation == "Regulation (EU) 2016/679, art. 5"
    assert by_id["eu-5"].citation_form == "bluebook_analog"
    assert index.gaps == [
        {
            "jurisdiction": "US",
            "instrument": "United States Code",
            "part": "",
            "book": "",
            "title": "42",
            "chapter": "",
            "unit": "section",
            "missing": [1982],
        }
    ]


def test_sparse_numbers_and_unfit_rows_stay_out_of_the_listing() -> None:
    sparse = [
        _record(entry_cid=f"sparse-{number}", provenance={"section": number, "title": "1"})
        for number in ("1", "50", "100", "150")
    ]
    unfit = [
        _record(entry_cid="empty", text="  "),
        _record(entry_cid="state", jurisdiction="US-OH"),
        _record(entry_cid="page", provenance={"document_role": "informative", "section": "1"}),
        _record(entry_cid="loose", provenance={"document_role": "law"}),
    ]
    kept = _record(
        bluebook_citation="Minn. Stat. § 518.17",
        entry_cid="kept",
        provenance={"title": "42", "section": "1983"},
    )
    index = index_national_laws([*sparse, *unfit, kept])
    assert index.gaps == []
    assert {entry.entry_cid for entry in index.entries} == {
        "sparse-1",
        "sparse-50",
        "sparse-100",
        "sparse-150",
        "kept",
    }
    assert next(entry for entry in index.entries if entry.entry_cid == "kept").citation == (
        "Minn. Stat. § 518.17"
    )
    reasons = {row["entry_cid"]: row["reason"] for row in index.schema_problems}
    assert reasons["empty"] == "empty_text"
    assert reasons["state"] == "bad_jurisdiction"
    assert reasons["page"] == "not_law"
    assert index.unplaced == [
        {
            "entry_cid": "loose",
            "jurisdiction": "US",
            "instrument": "United States Code",
            "reason": "no_locator",
        }
    ]


def test_headings_left_in_the_text_fill_the_code_listing() -> None:
    civil = _record(
        entry_cid="civ-220",
        jurisdiction="FR",
        title="",
        text=(
            "CODE CIVIL\n"
            "(Décrété le 21 décembre 1880)\n"
            "Livre - I DES PERSONNES\n"
            "Titre - VI DU DIVORCE\n"
            "220 .-\n"
            "L'opposition devra, à peine de nullité, être notifiée dans la huitaine.\n"
            "Elle vise l'article 215 du même code.\n"
        ),
        provenance={"document_role": "law"},
    )
    procedure = _record(
        entry_cid="proc-527",
        jurisdiction="MC",
        title="Article",
        text=(
            "CODE DE PROCÉDURE CIVILE\n"
            "Partie - PARTIE I PROCÉDURE DEVANT LES TRIBUNAUX\n"
            "Livre - IV DE L'EXÉCUTION\n"
            "Titre - IV DES SAISIES-EXÉCUTIONS\n"
            "Article 527 .-\n"
            "Les saisies sont poursuivies devant le tribunal.\n"
        ),
        provenance={"document_role": "law"},
    )
    section = _record(
        entry_cid="uk-2",
        jurisdiction="GB",
        title="Section 2",
        text="2 1 A council for a county may make byelaws for the good rule of its area.",
        provenance={"document_role": "law", "section": "9"},
    )
    notes = _record(
        entry_cid="notes",
        title="Notes",
        text=(
            "The court shall apply this Act to every claim filed in the territory.\n"
            "article 215 is a cross reference in the same sentence.\n"
            "216 East Main Street shall remain a public road.\n"
        ),
        provenance={"document_role": "law"},
    )
    pants = _record(
        entry_cid="pants",
        title="Notes",
        text="1. pantsuit continues without a separate heading.\nThe tailor shall finish the hem of the garment.",
        provenance={"document_role": "law"},
    )
    holes = [
        _record(
            entry_cid=f"hole-{number}",
            jurisdiction="FR",
            title="",
            text=(
                "CODE CIVIL\n"
                "Titre - I DES PERSONNES\n"
                f"{number} .-\n"
                "Le texte de l'article demeure applicable aux personnes concernées.\n"
            ),
            provenance={"document_role": "law"},
        )
        for number in (1, 2, 4, 5)
    ]
    annex = _record(
        entry_cid="annex",
        jurisdiction="MC",
        title="",
        text=(
            "Article A-147 .-\n"
            "À l'appui de la déclaration, les entreprises doivent déclarer le rapport provisoire.\n"
        ),
        provenance={"document_role": "law"},
    )
    index = index_national_laws([civil, procedure, section, notes, pants, annex, *holes])
    by_id = {entry.entry_cid: entry for entry in index.entries}
    assert "notes" not in by_id
    assert "pants" not in by_id
    assert by_id["civ-220"].citation == "C. civ. art. 220"
    assert by_id["civ-220"].citation_form == "bluebook"
    assert by_id["civ-220"].book == "I"
    assert by_id["civ-220"].title == "VI"
    assert by_id["civ-220"].path == "CODE CIVIL / Book I / Title VI / Article 220"
    assert by_id["proc-527"].citation == (
        "Monaco, CODE DE PROCÉDURE CIVILE, pt. I, bk. IV, tit. IV, art. 527"
    )
    assert by_id["annex"].article == "A-147"
    assert by_id["uk-2"].section == "9"
    assert by_id["uk-2"].citation == "United Kingdom, § 9"
    assert any(
        row["instrument"] == "CODE CIVIL" and row["missing"] == [3] and row["unit"] == "article"
        for row in index.gaps
    )
    assert {row["entry_cid"] for row in index.unplaced} == {"notes", "pants"}


def test_an_amending_loi_keeps_its_own_name() -> None:
    loi = _record(
        entry_cid="loi-8",
        jurisdiction="MC",
        title="article 8 de la loi nr. 1.423 du 2 décembre 2015",
        text=(
            "article 8 de la loi nr. 1.423 du 2 décembre 2015\n"
            "Les dispositions entrent en vigueur le lendemain de la publication.\n"
        ),
        provenance={"document_role": "law"},
    )
    ordonnance = _record(
        entry_cid="ord-2",
        jurisdiction="MC",
        title="article 2, II de l'ordonnance nr. 4.714 du 10 février 2014",
        text="Le taux s'applique aux opérations réalisées sur le territoire.",
        provenance={"document_role": "law"},
    )
    quoted = _record(
        entry_cid="quoted",
        jurisdiction="MC",
        title="",
        text=(
            "Article 415 .-\n"
            "Seront punis de l'amende prévue au chiffre 1 de l'article 29.\n"
            "article 8 de la loi nr. 1.423 du 2 décembre 2015 demeure applicable.\n"
        ),
        provenance={"document_role": "law", "article": "415", "section": "415"},
    )
    index = index_national_laws([loi, ordonnance, quoted])
    by_id = {entry.entry_cid: entry for entry in index.entries}
    assert by_id["loi-8"].instrument == "loi nr. 1.423 du 2 décembre 2015"
    assert by_id["loi-8"].article == "8"
    assert by_id["loi-8"].citation == "Monaco, loi nr. 1.423 du 2 décembre 2015, art. 8"
    assert by_id["ord-2"].instrument == "ordonnance nr. 4.714 du 10 février 2014"
    assert by_id["ord-2"].article == "2"
    assert by_id["quoted"].article == "415"
    assert by_id["quoted"].instrument == "Monaco"
    assert "1.423" not in by_id["quoted"].citation


def test_a_finished_folder_writes_the_directory_beside_the_corpus(tmp_path: Path) -> None:
    source = tmp_path / "france"
    source.mkdir()
    row = _record(
        entry_cid="fr-1",
        jurisdiction="FR",
        title="Code civil",
        provenance={"article": "1", "section": "1"},
    )
    row["provenance"] = json.dumps(row["provenance"], ensure_ascii=False)
    schema = pa.schema([pa.field(name, pa.string()) for name in LEGAL_RECORD_FIELDS])
    columns = {
        name: [row.get(name) if isinstance(row.get(name), str) else None]
        for name in LEGAL_RECORD_FIELDS
    }
    pq.write_table(pa.table(columns, schema=schema), source / "part-000000.parquet")
    report = write_national_directory(source, tmp_path / "directory")
    assert report["listed"] == 1
    assert report["bluebook"] == 1
    assert report["schema_problems"] == 0
    assert report["order"] == "code"
    saved = json.loads((tmp_path / "directory" / "directory.jsonl").read_text(encoding="utf-8"))
    assert saved["citation"] == "C. civ. art. 1"
    assert saved["path"] == "Code civil / Article 1"
    assert "Tout" not in (tmp_path / "directory" / "directory.jsonl").read_text(encoding="utf-8")
    assert json.loads((tmp_path / "directory" / "report.json").read_text(encoding="utf-8"))["listed"] == 1
