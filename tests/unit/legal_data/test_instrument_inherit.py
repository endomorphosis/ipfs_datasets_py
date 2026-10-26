"""A code name moves only inside the source law that already contains it."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.admit import (
    _fill_row,
    admit_source_law,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.instrument_inherit import (
    inheritance_plan,
    refine_assembled_corpus,
    refine_atom,
    replacement_title,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.national_directory import (
    index_national_laws,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.schema import LEGAL_RECORD_FIELDS

_SHA = "c" * 40
_PROVISION = (
    "L'opposition devra, à peine de nullité, être notifiée dans la huitaine."
)


def test_one_code_name_fills_a_blank_sibling_and_stops_at_a_loi() -> None:
    rows = [
        {"law_id": "civil", "body": "CODE CIVIL\nLivre - I DES PERSONNES\nTitre - VI DU DIVORCE\n"},
        {"law_id": "civil", "body": "Article 220 .-\n" + _PROVISION + "\n"},
        {
            "law_id": "civil",
            "body": "article 8 de la loi nr. 1.423 du 2 décembre 2015\n" + _PROVISION + "\n",
        },
        {"law_id": "split", "body": "CODE CIVIL\nArticle 1 .-\n" + _PROVISION + "\n"},
        {"law_id": "split", "body": "CODE PÉNAL\nArticle 2 .-\n" + _PROVISION + "\n"},
        {"law_id": "news", "body": "Actualités juridiques\nArticle 1er : La requête est rejetée.\n"},
    ]
    plan = inheritance_plan(rows)
    assert set(plan) == {"civil"}
    code, headings = plan["civil"]
    assert code == "CODE CIVIL"
    assert headings["book"] == "I"
    assert headings["title"] == "VI"
    assert "split" not in plan
    assert replacement_title("", _PROVISION, code) == "CODE CIVIL"
    assert replacement_title("Article 220 .-", _PROVISION, code) == "CODE CIVIL"
    assert replacement_title("9. Non-compliance", _PROVISION, code) is None
    assert replacement_title("Actualités juridiques", _PROVISION, code) is None
    assert (
        replacement_title("article 8 de la loi nr. 1.423 du 2 décembre 2015", _PROVISION, code)
        is None
    )
    assert replacement_title("CODE DE LA ROUTE > Article 4", _PROVISION, code) is None
    assert replacement_title("CODE CIVIL > Article 1707", "Article 1707 .-\n" + _PROVISION, code) == (
        "CODE CIVIL"
    )

    statute = "Article 220 .-\n" + _PROVISION
    blank = {
        "entry_cid": "art-220",
        "jurisdiction": "MC",
        "admin_level": "country",
        "instrument_type": "statute",
        "title": "",
        "text": statute,
        "content_sha256": "ab" * 32,
        "provenance": {
            "document_role": "law",
            "article": "220",
            "section": "220",
            "jsonld": {"@type": "Legislation", "text": statute, "encodingFormat": "text/plain"},
        },
    }
    refined = refine_atom(blank, law_code=code, headings=headings)
    assert refined["text"] == statute
    assert refined["text"] is blank["text"]
    assert refined["title"] == "CODE CIVIL"
    assert refined["content_sha256"] == blank["content_sha256"]
    assert refined["provenance"]["section"] == "220"
    assert refined["provenance"]["book"] == "I"
    assert refined["provenance"]["title"] == "VI"
    assert refined["provenance"]["jsonld"]["text"] == statute
    assert refined["provenance"]["jsonld"]["name"] == "CODE CIVIL"
    assert blank["provenance"]["jsonld"].get("name") is None
    listed = index_national_laws([refined])
    assert listed.entries[0].citation == "Monaco, CODE CIVIL, bk. I, tit. VI, art. 220"
    assert listed.report()["weak_instrument"] == 0

    loi = dict(blank)
    loi["entry_cid"] = "loi-8"
    loi["title"] = "article 8 de la loi nr. 1.423 du 2 décembre 2015"
    kept = refine_atom(loi, law_code=code, headings=headings)
    assert kept["title"] == loi["title"]
    assert kept["text"] == statute
    assert "book" not in kept["provenance"]


def test_a_finished_folder_is_refined_beside_the_fill(tmp_path: Path) -> None:
    source = tmp_path / "source"
    assembled = tmp_path / "assembled"
    source.mkdir()
    assembled.mkdir()
    rows = [
        _source("law-1", "parent", "", "CODE CIVIL\nLivre - I DES PERSONNES\nTitre - VI DU DIVORCE\n"),
        _source("law-1", "child", "", "Article 220 .-\n" + _PROVISION + "\n"),
        _source(
            "law-1",
            "caption",
            "CODE CIVIL > Article 1707",
            "Article 1707 .-\nLe mandataire est responsable du dommage causé par sa faute.\n",
        ),
        _source(
            "law-2",
            "loi",
            "article 8 de la loi nr. 1.423 du 2 décembre 2015",
            "article 8 de la loi nr. 1.423 du 2 décembre 2015\n"
            "Les dispositions entrent en vigueur le lendemain de la publication.\n",
        ),
    ]
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, source / "part-000000.parquet")
    atoms = []
    for row in rows:
        decision = admit_source_law(
            _fill_row(row),
            source_dataset="endomorphosis/ipfs_monaco_laws",
            source_revision=_SHA,
        )
        if not decision.admitted:
            continue
        for atom in decision.records:
            encoded = {field: None for field in LEGAL_RECORD_FIELDS}
            provenance = dict(atom["provenance"])
            provenance["jsonld"] = {"@type": "Legislation", "text": atom["text"]}
            encoded.update(
                {
                    "jurisdiction": atom["jurisdiction"],
                    "admin_level": "country",
                    "instrument_type": "statute",
                    "title": atom["title"],
                    "text": atom["text"],
                    "language": "fr",
                    "content_sha256": "cd" * 32,
                    "entry_cid": atom["entry_cid"],
                    "provenance": json.dumps(provenance, ensure_ascii=False),
                }
            )
            atoms.append(encoded)
    assert atoms
    schema = pa.schema([pa.field(name, pa.string()) for name in LEGAL_RECORD_FIELDS])
    columns = {
        name: [atom.get(name) if isinstance(atom.get(name), str) else None for atom in atoms]
        for name in LEGAL_RECORD_FIELDS
    }
    pq.write_table(pa.table(columns, schema=schema), assembled / "part-000000.parquet")
    (assembled / "report.json").write_text(
        json.dumps(
            {
                "corpus_complete": True,
                "normalizer_version": "country-source-admit/v1",
            }
        ),
        encoding="utf-8",
    )
    dest = tmp_path / "refined"
    summary = refine_assembled_corpus(
        [source / "part-000000.parquet"],
        assembled,
        dest,
        source_dataset="endomorphosis/ipfs_monaco_laws",
        source_revision=_SHA,
    )
    assert summary["written"] is True
    assert summary["titles_filled"] >= 1
    saved = pq.read_table(dest / "part-000000.parquet").to_pylist()
    original = {atom["entry_cid"]: atom for atom in atoms}
    assert len(saved) == len(atoms)
    for row in saved:
        before = original[row["entry_cid"]]
        assert row["text"] == before["text"]
        assert row["content_sha256"] == before["content_sha256"]
        assert json.loads(row["provenance"])["jsonld"]["text"] == before["text"]
    by_text = {row["text"]: row for row in saved}
    child = by_text["Article 220 .-\n" + _PROVISION]
    assert child["title"] == "CODE CIVIL"
    child_provenance = json.loads(child["provenance"])
    assert child_provenance["book"] == "I"
    assert child_provenance["title"] == "VI"
    assert child_provenance["section"]
    assert child_provenance["jsonld"]["name"] == "CODE CIVIL"
    caption = next(row for row in saved if row["text"].startswith("Article 1707"))
    assert caption["title"] == "CODE CIVIL"
    assert caption["text"].startswith("Article 1707 .-")
    loi = next(row for row in saved if "1.423" in row["text"])
    assert loi["title"] == "article 8 de la loi nr. 1.423 du 2 décembre 2015"
    assert (assembled / "part-000000.parquet").read_bytes()
    assert not (assembled / "refine_report.json").exists()


def test_an_unfinished_fill_is_left_untouched(tmp_path: Path) -> None:
    assembled = tmp_path / "assembled"
    assembled.mkdir()
    (assembled / "report.json").write_text("{}\n", encoding="utf-8")
    try:
        refine_assembled_corpus(
            [],
            assembled,
            tmp_path / "refined",
            source_dataset="endomorphosis/ipfs_monaco_laws",
            source_revision=_SHA,
        )
    except ValueError as exc:
        assert str(exc) == "assembled"
    else:
        raise AssertionError("assembled")
    assert not (tmp_path / "refined").exists()


def _source(law_id: str, entry: str, title: str, body: str) -> dict[str, str]:
    return {
        "law_id": law_id,
        "entry_cid": entry,
        "title": title,
        "body": body,
        "language": "fr",
        "jurisdiction": "MC",
        "country": "Monaco",
        "source_revision": _SHA,
    }
