"""Local legal-record/v1 export. No token read and no Hub client."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.__main__ import main as country_main
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.upload import (
    UPLOAD_IGNORE_PATTERNS,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.export_norm import (
    ExportRefused,
    ExportUploadBlocked,
    _write_parts,
    choose_export_command,
    destination_repo,
    export_norm,
    is_world_v11_shard,
    main,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.schema import (
    LEGAL_RECORD_FIELDS,
    WORLD_V11_COLUMNS,
)

_SHA = "53a38d3ea51402640141bf1f1126d669c1277e46"
_MODULE = (
    Path(__file__).resolve().parents[3]
    / "ipfs_datasets_py"
    / "processors"
    / "legal_scrapers"
    / "world_law"
    / "export_norm.py"
)


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def test_one_command_per_layout() -> None:
    assert choose_export_command("guam", ["data/laws.parquet"]) == "reindex"
    assert choose_export_command("czech_municipal", ["data/laws.parquet"]) == "reindex"
    assert choose_export_command("estonia_municipal", ["data/laws.parquet"]) == "reindex"
    assert (
        choose_export_command("spain_municipal", ["data/laws-00001.parquet"])
        == "load_sharded_laws"
    )
    assert (
        choose_export_command(
            "canada_municipal",
            ["data/halifax_html.parquet"],
        )
        == "export_norm_html"
    )
    assert choose_export_command("chile_municipal", []) == "not_published"
    with pytest.raises(ExportRefused):
        choose_export_command(
            "belgium_municipal",
            ["data/laws-00001.parquet"],
        )


def test_destinations_skip_the_april_repo_and_protected_pins() -> None:
    assert destination_repo("american") == "justicedao/american_municipal_law_norm"
    assert destination_repo("html", "new_zealand_municipal") == (
        "justicedao/ipfs_new_zealand_municipal_laws_norm"
    )
    assert destination_repo("world-national") == "justicedao/world_national_law"
    assert "justicedao/american_municipal_law" != destination_repo("american")


def test_html_export_writes_a_local_tree_without_html(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write(
        source / "data" / "halifax_html.parquet",
        [
            {
                "cid": "bafy",
                "jurisdiction_name": "Halifax",
                "country": "Canada",
                "html_title": '<div class="chunk-title">Far North</div>',
                "html": "<html><body>secret</body></html>",
                "text": "Bylaw text",
                "date_effective": "2022-01-03",
                "source_url": "https://example.test/bylaw",
            }
        ],
    )
    dest = tmp_path / "out"
    summary = export_norm(
        source,
        dest,
        family="html",
        slug="canada_municipal",
        source_dataset="endomorphosis/ipfs_canada_municipal_laws",
        source_revision=_SHA,
    )
    table = pq.read_table(dest / "data" / "laws.parquet")
    assert "html" not in table.column_names
    assert table.column("jurisdiction").to_pylist() == ["CA"]
    assert table.column("text").to_pylist() == ["Bylaw text"]
    assert "<" not in table.column("title").to_pylist()[0]
    manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["destination_repo"] == "justicedao/ipfs_canada_municipal_laws_norm"
    assert manifest["coverage"] == "snapshot"
    assert summary["rows_kept"] == 1
    assert not (dest / ".cache").exists()


def test_world_export_drops_archived_and_us_rows(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write(
        source / "data" / "iso_FR_html.parquet",
        [
            {
                "cid": "keep",
                "country_code": "FR",
                "doc_type": "statute",
                "title_native": "Code civil",
                "text": "Les lois",
                "content_complete": True,
                "source_policy": None,
                "source_official": True,
            },
            {
                "cid": "drop-policy",
                "country_code": "FR",
                "doc_type": "statute",
                "title_native": "Hidden",
                "text": "hidden",
                "source_policy": "archived_robots_disallowed",
                "source_official": True,
                "content_complete": True,
            },
            {
                "cid": "drop-us",
                "country_code": "US",
                "doc_type": "statute",
                "title_native": "Code",
                "text": "usc",
                "source_policy": None,
                "source_official": True,
                "content_complete": True,
            },
        ],
    )
    dest = tmp_path / "out"
    summary = export_norm(
        source,
        dest,
        family="world-national",
        source_dataset="endomorphosis/world_national_law",
        source_revision=_SHA,
        gap_status="stale",
    )
    table = pq.read_table(dest / "data" / "laws.parquet")
    assert table.column("entry_cid").to_pylist() == ["keep"]
    provenance = json.loads(table.column("provenance").to_pylist()[0])
    assert provenance["query_default"] is True
    assert provenance["atomic"] is True
    assert summary["filter_counts"]["archived_robots_disallowed"] == 1
    assert summary["filter_counts"]["us_omitted"] == 1


def test_zero_kept_rows_are_not_published(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write(
        source / "data" / "iso_US_html.parquet",
        [{"cid": "us", "country_code": "US", "text": "usc", "content_complete": True, "source_official": True}],
    )
    summary = export_norm(
        source,
        tmp_path / "out",
        family="world-national",
        source_dataset="endomorphosis/world_national_law",
        source_revision=_SHA,
    )
    assert summary["rows_kept"] == 0
    assert summary["coverage"] == "not_published"
    assert not (tmp_path / "out" / "data" / "laws.parquet").exists()


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write(
        source / "data" / "row_html.parquet",
        [{"cid": "1", "country": "NZ", "html_title": "Far North", "text": "bylaw"}],
    )
    dest = tmp_path / "out"
    summary = export_norm(
        source,
        dest,
        family="html",
        slug="new_zealand_municipal",
        source_dataset="endomorphosis/ipfs_new_zealand_municipal_laws",
        source_revision=_SHA,
        dry_run=True,
    )
    assert summary["rows_kept"] == 1
    assert not dest.exists()


def test_upload_flag_does_not_construct_a_client(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "secret-token-value")
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ExportUploadBlocked):
        main(
            [
                "--family",
                "american",
                "--source",
                str(source),
                "--out",
                str(tmp_path / "out"),
                "--revision",
                _SHA,
                "--source-dataset",
                "endomorphosis/american_municipal_law",
                "--upload",
            ]
        )
    text = _MODULE.read_text(encoding="utf-8")
    assert ".cache/huggingface" not in text
    assert "upload_folder" not in text
    assert "upload_large_folder" not in text
    assert "secret-token-value" not in text


def test_token_file_env_is_refused(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HF_TOKEN_FILE", str(tmp_path / "missing-token"))
    source = tmp_path / "source"
    _write(source / "data" / "row.parquet", [{"cid": "1", "html_title": "City", "html": "<b>x</b>"}])
    with pytest.raises(ExportRefused, match="HF_TOKEN_FILE"):
        export_norm(
            source,
            tmp_path / "out",
            family="american",
            source_dataset="endomorphosis/american_municipal_law",
            source_revision=_SHA,
        )


def test_american_export_keeps_html_and_skips_citation(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write(
        source / "1085809_html.parquet",
        [
            {
                "cid": "ord-1",
                "doc_id": "1085809",
                "doc_order": 1,
                "html_title": '<div class="chunk-title">Sec. 15-40. - Injunction.</div>',
                "html": "<p>The city may seek an injunction against the violation.</p>",
            }
        ],
    )
    _write(
        source / "1085809_citation.parquet",
        [{"bluebook_cid": "cite-1", "cid": "cite-1", "title": "Not an ordinance"}],
    )
    _write(
        source / "notes.parquet",
        [{"cid": "notes", "html_title": "Notes", "html": "<p>no</p>"}],
    )
    dest = tmp_path / "out"
    summary = export_norm(
        source,
        dest,
        family="american",
        source_dataset="endomorphosis/american_municipal_law",
        source_revision=_SHA,
    )
    table = pq.read_table(dest / "data" / "laws.parquet")
    assert table.column("entry_cid").to_pylist() == ["ord-1"]
    assert table.column("text").to_pylist() == [
        "The city may seek an injunction against the violation."
    ]
    provenance = json.loads(table.column("provenance").to_pylist()[0])
    assert provenance["section"] == "15-40"
    assert provenance["content_complete"] is True
    assert "<" not in table.column("text").to_pylist()[0]
    assert table.column("jurisdiction").to_pylist() == ["US-OH"]
    assert table.column("authority").to_pylist() == ["City of Hamilton"]
    assert table.column("citation").to_pylist() == [
        "City of Hamilton, Ohio, Municipal Code, § 15-40"
    ]
    assert table.column("published_date").to_pylist() == [None]
    assert table.column("admin_level").to_pylist() == ["us-municipal"]
    assert table.column("normalizer_version").to_pylist() == [
        "american-municipal-html/v4+legal-record/v1"
    ]
    assert provenance["jsonld"]["@type"] == "Legislation"
    assert provenance["jsonld"]["legislationJurisdiction"] == "US-OH"
    assert "html" not in table.column_names
    assert summary["rows_kept"] == 1
    assert summary["destination_repo"] == "justicedao/american_municipal_law_norm"
    manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["coverage"] == "snapshot"
    assert manifest["rows_kept"] == 1
    assert manifest["normalizer_version"] == "american-municipal-html/v4+legal-record/v1"


def test_american_export_joins_place_metadata_and_keeps_one_row_per_chunk(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _write(
        source / "1085809_html.parquet",
        [
            {
                "cid": "sec-186",
                "doc_id": "186.04",
                "doc_order": 5,
                "html_title": "186.04 GROUNDS NOT COVERED UNDER CHAPTER 180",
                "html": (
                    "<p>The grounds are limited.</p>"
                    "<p>(Ord. 98-6-61. Passed 6-24-98.)</p>"
                    '<a href="/codes/hamilton/latest/hamilton_oh/0-0-0-23807">section</a>'
                ),
            },
            {
                "cid": "ch-186",
                "doc_id": "186",
                "doc_order": 2,
                "html_title": "CHAPTER 186 GENERAL PROVISIONS",
                "html": '<div class="chunk-content"></div>',
            },
        ],
    )
    _write(
        source / "1085809_citation.parquet",
        [{"bluebook_cid": "cite-1", "cid": "cite-1", "title": "Not an ordinance", "year": "1961"}],
    )
    meta = source / "american_law" / "data" / "metadata" / "1085809.json"
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(
        json.dumps(
            {
                "place_name": "City of Hamilton",
                "state_code": "OH",
                "total_sections": 2,
                "last_updated": 1789723139977,
            }
        ),
        encoding="utf-8",
    )
    dest = tmp_path / "out"
    summary = export_norm(
        source,
        dest,
        family="american",
        source_dataset="endomorphosis/american_municipal_law",
        source_revision=_SHA,
    )
    table = pq.read_table(dest / "data" / "laws.parquet")
    assert table.column("entry_cid").to_pylist() == ["ch-186", "sec-186"]
    assert summary["rows_kept"] == 2
    assert table.column("jurisdiction").to_pylist() == ["US-OH", "US-OH"]
    assert table.column("authority").to_pylist() == ["City of Hamilton", "City of Hamilton"]
    assert table.column("language").to_pylist() == ["en", "en"]
    assert table.column("published_date").to_pylist() == [None, None]
    assert table.column("effective_date").to_pylist() == [None, "1998-06-24"]
    assert table.column("source_url").to_pylist()[1] == (
        "https://library.municode.com/codes/hamilton/latest/hamilton_oh/0-0-0-23807"
    )
    section = json.loads(table.column("provenance").to_pylist()[1])
    assert section["chapter"] == "186"
    assert section["section"] == "186.04"
    assert section["passage_dates"] == ["1998-06-24"]
    document = section["jsonld"]
    assert document["@context"] == "https://schema.org"
    assert document["@type"] == "Legislation"
    assert document["legislationJurisdiction"] == "US-OH"
    assert document["legislationDate"] == "1998-06-24"
    assert document["inLanguage"] == "en"
    assert "§ 186.04" in document["legislationIdentifier"]
    assert "(1998)" in document["legislationIdentifier"]
    assert "1961" not in document["legislationIdentifier"]
    assert "datePublished" not in document
    assert "dateModified" not in document
    assert "<" not in table.column("text").to_pylist()[1]
    encoded = table.column("provenance").to_pylist()[1]
    assert "1789723139977" not in encoded
    _assert_no_floats(json.loads(encoded))


def test_american_export_inherits_headings_and_recovers_one_title_place(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _write(
        source / "ely_html.parquet",
        [
            {
                "cid": "banner",
                "doc_id": "banner",
                "doc_order": 1,
                "html_title": "City Code - City of Ely, MN",
                "html": "<div></div>",
            },
            {
                "cid": "title",
                "doc_id": "title",
                "doc_order": 2,
                "html_title": "Title 1 General",
                "html": "<div></div>",
            },
            {
                "cid": "chapter",
                "doc_id": "chapter",
                "doc_order": 3,
                "html_title": "Chapter 1 Animals",
                "html": "<div></div>",
            },
            {
                "cid": "article",
                "doc_id": "article",
                "doc_order": 4,
                "html_title": "Article III Dogs",
                "html": "<div></div>",
            },
            {
                "cid": "part",
                "doc_id": "part",
                "doc_order": 5,
                "html_title": "Part 1 Licenses",
                "html": "<div></div>",
            },
            {
                "cid": "section",
                "doc_id": "section",
                "doc_order": 6,
                "html_title": "Sec. 2-1. Licenses.",
                "html": "<p>A license is required.</p>",
            },
            {
                "cid": "next-chapter",
                "doc_id": "next-chapter",
                "doc_order": 7,
                "html_title": "Chapter 2 Nuisances",
                "html": "<div></div>",
            },
            {
                "cid": "noise",
                "doc_id": "noise",
                "doc_order": 8,
                "html_title": "Sec. 2-2. Noise.",
                "html": "<p>Quiet hours apply.</p>",
            },
        ],
    )
    _write(
        source / "rules_html.parquet",
        [
            {
                "cid": "ely-banner",
                "doc_id": "ely-banner",
                "doc_order": 1,
                "html_title": "City Code - City of Ely, MN",
                "html": "<div></div>",
            },
            {
                "cid": "rules-chapter",
                "doc_id": "rules-chapter",
                "doc_order": 2,
                "html_title": "Chapter 101 General",
                "html": "<div></div>",
            },
            {
                "cid": "rules",
                "doc_id": "rules",
                "doc_order": 3,
                "html_title": "101.03 RULES OF CONSTRUCTION.",
                "html": (
                    "<p>Chapter 180 does not apply.</p>"
                    "<p>Section 6103 of the Revised Code is adopted.</p>"
                    "<p>(a) Words are plain.</p>"
                ),
            },
        ],
    )
    _write(
        source / "toc_html.parquet",
        [
            {
                "cid": "toc-banner",
                "doc_id": "toc-banner",
                "doc_order": 1,
                "html_title": "City Code - City of Ely, MN",
                "html": "<div></div>",
            },
            {
                "cid": "toc-article",
                "doc_id": "toc-article",
                "doc_order": 2,
                "html_title": "Article XXIII Subdivisions",
                "html": "<div></div>",
            },
            {
                "cid": "toc",
                "doc_id": "toc",
                "doc_order": 3,
                "html_title": "TITLE ONE - Subdivision Regulations",
                "html": "<p>Chapter 1105 Street design.</p><p>Chapter 1121 Lots.</p>",
            },
        ],
    )
    _write(
        source / "wendell_html.parquet",
        [
            {
                "cid": "wendell",
                "doc_id": "wendell",
                "doc_order": 1,
                "html_title": "Ordinances | City of Wendell",
                "html": "<p>Object moved.</p>",
            }
        ],
    )
    _write(
        source / "hamilton_html.parquet",
        [
            {
                "cid": "ham",
                "doc_id": "ham",
                "doc_order": 1,
                "html_title": "City of Ely, MN",
                "html": "<p>The metadata place wins.</p>",
            }
        ],
    )
    _write(
        source / "2395220_html.parquet",
        [
            {
                "cid": "nyc",
                "doc_id": "nyc",
                "doc_order": 1,
                "html_title": "City of Ely, MN",
                "html": "<p>The file stem is the New York GNIS id.</p>",
            }
        ],
    )
    _write(
        source / "colma_html.parquet",
        [
            {
                "cid": "colma",
                "doc_id": "colma",
                "doc_order": 1,
                "html_title": "Ordinances",
                "html": (
                    "<link rel='canonical' href='https://www.colma.ca.gov/municipal-code'>"
                    "<a href='https://municipal.codes/WA/RCW/35.21'>RCW</a>"
                    "<p>Parking rules.</p>"
                ),
            }
        ],
    )
    _write(
        source / "tacoma_html.parquet",
        [
            {
                "cid": "tacoma",
                "doc_id": "tacoma",
                "doc_order": 1,
                "html_title": "Ordinances",
                "html": "<link rel='canonical' href='https://www.cityoftacoma.org/code'>",
            }
        ],
    )
    meta = source / "american_law" / "metadata" / "hamilton.json"
    meta.parent.mkdir(parents=True)
    meta.write_text(
        json.dumps({"place_name": "City of Hamilton", "state_code": "OH", "last_updated": 1789723139977}),
        encoding="utf-8",
    )
    dest = tmp_path / "out"
    export_norm(
        source,
        dest,
        family="american",
        source_dataset="endomorphosis/american_municipal_law",
        source_revision=_SHA,
    )
    table = pq.read_table(dest / "data" / "laws.parquet")
    by_cid = {
        cid: json.loads(raw)
        for cid, raw in zip(table.column("entry_cid").to_pylist(), table.column("provenance").to_pylist())
    }
    jurisdictions = dict(zip(table.column("entry_cid").to_pylist(), table.column("jurisdiction").to_pylist()))
    authorities = dict(zip(table.column("entry_cid").to_pylist(), table.column("authority").to_pylist()))
    section = by_cid["section"]
    assert section["title"] == "1"
    assert section["chapter"] == "1"
    assert section["article"] == "III"
    assert section["part"] == "1"
    assert section["section"] == "2-1"
    assert "statute" not in section or section["statute"] != "III"
    properties = {
        item["propertyID"]: item["value"] for item in section["jsonld"]["additionalProperty"]
    }
    assert properties["article"] == "III"
    assert properties["chapter"] == "1"
    assert jurisdictions["section"] == "US-MN"
    assert authorities["section"] == "City of Ely"
    noise = by_cid["noise"]
    assert noise["title"] == "1"
    assert noise["chapter"] == "2"
    assert noise["section"] == "2-2"
    assert "article" not in noise
    assert "part" not in noise
    assert jurisdictions["wendell"] is None
    assert authorities["wendell"] is None
    assert jurisdictions["ham"] == "US-OH"
    assert authorities["ham"] == "City of Hamilton"
    assert jurisdictions["colma"] == "US-CA"
    assert authorities["colma"] == "Colma"
    assert jurisdictions["nyc"] == "US-NY"
    assert authorities["nyc"] == "City of New York"
    assert jurisdictions["tacoma"] is None
    assert authorities["tacoma"] is None
    assert all("1789723139977" not in raw for raw in table.column("provenance").to_pylist())
    rules = [prov for prov in by_cid.values() if prov.get("doc_id") == "rules"]
    assert rules
    assert {prov.get("section") for prov in rules} == {"101.03"}
    assert {prov.get("chapter") for prov in rules} == {"101"}
    assert {prov.get("hierarchy_path") for prov in rules} == {
        "Chapter 101 / Section 101.03"
    }
    for prov in rules:
        properties = {
            item["propertyID"]: item["value"] for item in prov["jsonld"]["additionalProperty"]
        }
        assert properties["section"] == "101.03"
        assert properties["chapter"] == "101"
        assert properties["hierarchy_path"] == "Chapter 101 / Section 101.03"
    chapter_only = next(prov for prov in by_cid.values() if prov.get("doc_id") == "rules-chapter")
    assert chapter_only.get("chapter") == "101"
    assert "section" not in chapter_only
    assert chapter_only.get("hierarchy_path") == "Chapter 101"
    toc = [prov for prov in by_cid.values() if prov.get("doc_id") == "toc"]
    assert toc
    assert all(prov.get("title") == "ONE" for prov in toc)
    assert all(prov.get("article") == "XXIII" for prov in toc)
    assert all("chapter" not in prov for prov in toc)
    assert {prov.get("hierarchy_path") for prov in toc} == {"Article XXIII / Title ONE"}


def _assert_no_floats(value: object) -> None:
    if isinstance(value, float):
        raise AssertionError(value)
    if isinstance(value, dict):
        for item in value.values():
            _assert_no_floats(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_floats(item)


def test_pack_shards_writes_laws_and_refuses_html_slugs(tmp_path: Path, capsys) -> None:
    source = tmp_path / "source"
    _write(source / "data" / "laws-00001.parquet", [{"id": "a", "text": "one"}])
    _write(source / "data" / "laws-00002_html.parquet", [{"id": "h", "text": "skip"}])
    out = tmp_path / "packed"
    code = country_main(
        [
            "pack-shards",
            "--source",
            str(source),
            "--out",
            str(out),
            "--slug",
            "spain_municipal",
            "--revision",
            _SHA,
        ]
    )
    assert code == 0
    assert pq.read_table(out / "data" / "laws.parquet").column("id").to_pylist() == ["a"]
    html_source = tmp_path / "html"
    _write(html_source / "data" / "city_html.parquet", [{"cid": "1", "country": "BE", "text": "x"}])
    refused = country_main(
        [
            "pack-shards",
            "--source",
            str(html_source),
            "--out",
            str(tmp_path / "nope"),
            "--slug",
            "belgium_municipal",
            "--revision",
            _SHA,
        ]
    )
    assert refused == 2
    assert "pack-shards" in capsys.readouterr().out


def test_parquet_keeps_a_column_missing_from_the_first_row(tmp_path: Path) -> None:
    first = {name: None for name in LEGAL_RECORD_FIELDS}
    second = dict(first)
    second["citation"] = "Art. 1"
    del first["citation"]
    written = _write_parts([first, second], tmp_path / "out", 10)
    table = pq.read_table(written[0])
    assert "citation" in table.column_names
    assert table.column("citation").to_pylist() == [None, "Art. 1"]
    assert list(table.column_names) == list(LEGAL_RECORD_FIELDS)


def test_chile_and_hungary_card_configs_print_zero_as_not_published(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    _write(
        source / "data" / "iso_FR_html.parquet",
        [
            {
                "cid": "fr",
                "country_code": "FR",
                "doc_type": "ordinance",
                "title_native": "Arrete",
                "text": "texte",
                "content_complete": True,
                "source_official": True,
            }
        ],
    )
    summary = export_norm(
        source,
        tmp_path / "out",
        family="world-municipal",
        source_dataset="endomorphosis/world_municipal_law",
        source_revision=_SHA,
        dry_run=True,
    )
    counts = summary["card_config_counts"]
    assert counts["CL"] == {
        "rows_kept": 0,
        "coverage": "not_published",
        "provenance_table": False,
    }
    assert counts["HU"]["rows_kept"] == 0
    assert counts["HU"]["coverage"] == "not_published"
    assert summary["rows_kept"] == 1
    assert not (tmp_path / "out").exists()
    code = main(
        [
            "--family",
            "world-municipal",
            "--source",
            str(source),
            "--out",
            str(tmp_path / "printed"),
            "--revision",
            _SHA,
            "--source-dataset",
            "endomorphosis/world_municipal_law",
            "--dry-run",
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert '"CL"' in printed
    assert '"HU"' in printed
    assert "not_published" in printed


def test_world_export_admin_level_follows_the_family(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write(
        source / "data" / "iso_ES_html.parquet",
        [
            {
                "cid": "es",
                "country_code": "ES",
                "doc_type": "ordinance",
                "title_native": "Ordenanza",
                "text": "texto",
                "content_complete": True,
                "source_official": True,
            }
        ],
    )
    municipal = tmp_path / "municipal"
    export_norm(
        source,
        municipal,
        family="world-municipal",
        source_dataset="endomorphosis/world_municipal_law",
        source_revision=_SHA,
    )
    national = tmp_path / "national"
    export_norm(
        source,
        national,
        family="world-national",
        source_dataset="endomorphosis/world_national_law",
        source_revision=_SHA,
    )
    municipal_level = pq.read_table(municipal / "data" / "laws.parquet").column("admin_level").to_pylist()
    national_level = pq.read_table(national / "data" / "laws.parquet").column("admin_level").to_pylist()
    assert municipal_level == ["municipality"]
    assert national_level == ["country"]


def _ae_statute() -> dict[str, object]:
    row = {name: None for name in WORLD_V11_COLUMNS}
    row.update(
        {
            "cid": "ae-1",
            "country_code": "AE",
            "doc_type": "statute",
            "title_native": "Law",
            "text": "statute text",
            "content_complete": None,
            "source_policy": None,
            "source_official": None,
        }
    )
    return row


def test_world_export_reads_html_shards_and_ignores_places(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write(source / "world_law" / "data" / "AE" / "iso_AE_html.parquet", [_ae_statute()])
    _write(
        source / "world_law" / "places.parquet",
        [{"place_id": "p1", "name": "Abu Dhabi", "country_code": "AE"}],
    )
    summary = export_norm(
        source,
        tmp_path / "out",
        family="world-national",
        source_dataset="endomorphosis/world_national_law",
        source_revision=_SHA,
    )
    table = pq.read_table(tmp_path / "out" / "data" / "laws.parquet")
    assert summary["rows_kept"] == 1
    assert table.column("jurisdiction").to_pylist() == ["AE"]
    assert table.column("entry_cid").to_pylist() == ["ae-1"]
    assert "html" not in table.column_names
    assert is_world_v11_shard("iso_AE_html.parquet")
    assert not is_world_v11_shard("places.parquet")
    assert not is_world_v11_shard("articles-00001.parquet")


def test_world_export_refuses_a_places_only_directory(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write(source / "world_law" / "places.parquet", [{"place_id": "p1", "name": "Abu Dhabi"}])
    with pytest.raises(ExportRefused, match="world-law shard"):
        export_norm(
            source,
            tmp_path / "out",
            family="world-municipal",
            source_dataset="endomorphosis/world_municipal_law",
            source_revision=_SHA,
        )


def test_html_null_text_does_not_abort_the_family(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write(
        source / "data" / "halifax_html.parquet",
        [
            {
                "cid": "null-text",
                "country": "Canada",
                "html_title": "Empty",
                "text": None,
                "html": None,
            },
            {
                "cid": "kept",
                "country": "Canada",
                "html_title": "Far North",
                "text": "Bylaw text",
                "html": "<p>other</p>",
            },
        ],
    )
    summary = export_norm(
        source,
        tmp_path / "out",
        family="html",
        slug="canada_municipal",
        source_dataset="endomorphosis/ipfs_canada_municipal_laws",
        source_revision=_SHA,
    )
    table = pq.read_table(tmp_path / "out" / "data" / "laws.parquet")
    assert summary["rows_kept"] == 2
    assert table.column("text").to_pylist() == [None, "Bylaw text"]
    provenance = [json.loads(value) for value in table.column("provenance").to_pylist()]
    assert provenance[0]["content_complete"] is False
    assert provenance[0]["atomic"] is False
    assert provenance[1]["content_complete"] is True
    assert provenance[1]["atomic"] is True


def test_upload_ignore_patterns_cover_token_and_cache_files() -> None:
    assert "**/.cache/**" in UPLOAD_IGNORE_PATTERNS
    assert "*token*" in UPLOAD_IGNORE_PATTERNS
    assert ".env" in UPLOAD_IGNORE_PATTERNS
    assert "*.pem" in UPLOAD_IGNORE_PATTERNS


def test_world_export_splits_articles_and_drops_chrome(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write(
        source / "data" / "iso_FR_html.parquet",
        [
            {
                "cid": "parent",
                "country_code": "FR",
                "doc_type": "statute",
                "number": "Code civil",
                "title_native": "Code civil",
                "language": "fr",
                "text": (
                    "Article 1 Alpha provision applies.\n"
                    "Article 2 Beta provision applies."
                ),
                "content_complete": True,
                "source_official": True,
            },
            {
                "cid": "chrome",
                "country_code": "FR",
                "doc_type": "statute",
                "title_native": "Banner",
                "text": "The incident id is 42",
                "content_complete": True,
                "source_official": True,
            },
        ],
    )
    summary = export_norm(
        source,
        tmp_path / "out",
        family="world-national",
        source_dataset="endomorphosis/world_national_law",
        source_revision=_SHA,
    )
    table = pq.read_table(tmp_path / "out" / "data" / "laws.parquet")
    texts = table.column("text").to_pylist()
    cids = table.column("entry_cid").to_pylist()
    assert summary["rows_kept"] == 2
    assert summary["filter_counts"]["not_atomic"] == 1
    assert texts[0].startswith("Article 1")
    assert texts[1].startswith("Article 2")
    assert cids[0] != cids[1]
    assert "parent" not in cids
    assert "chrome" not in cids
    provenance = [json.loads(value) for value in table.column("provenance").to_pylist()]
    assert provenance[0]["atomic"] is True
    assert provenance[0]["statute"] == "Code civil"
    assert provenance[0]["section"] == "1"
    assert provenance[1]["section"] == "2"
    assert all(isinstance(value, (str, bool, type(None))) for row in provenance for value in row.values())
