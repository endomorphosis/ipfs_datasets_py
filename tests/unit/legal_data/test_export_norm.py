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
    main,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.schema import LEGAL_RECORD_FIELDS

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
        source / "data" / "laws-00001.parquet",
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
    assert summary["filter_counts"]["archived_robots_disallowed"] == 1
    assert summary["filter_counts"]["us_omitted"] == 1


def test_zero_kept_rows_are_not_published(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write(
        source / "data" / "laws-00001.parquet",
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
        source / "data" / "laws-00001.parquet",
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


def test_upload_ignore_patterns_cover_token_and_cache_files() -> None:
    assert "**/.cache/**" in UPLOAD_IGNORE_PATTERNS
    assert "*token*" in UPLOAD_IGNORE_PATTERNS
    assert ".env" in UPLOAD_IGNORE_PATTERNS
    assert "*.pem" in UPLOAD_IGNORE_PATTERNS
