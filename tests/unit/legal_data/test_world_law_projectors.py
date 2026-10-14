"""Sealed one-row projections into legal-record/v1. No Hub download."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.processors.legal_scrapers.world_law.load_sharded_laws import (
    load_sharded_laws,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.project_american_municipal_row import (
    project_american_municipal_row,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.project_html_municipal_row import (
    project_html_municipal_row,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.project_world_v11_row import (
    project_world_v11_row,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.schema import LEGAL_RECORD_FIELDS

_SHA = "a" * 40


def _html_row(country: str) -> dict[str, object]:
    return {
        "cid": "bafy-html",
        "jurisdiction_id": "place-1",
        "jurisdiction_name": "Halifax",
        "country": country,
        "doc_id": "doc-1",
        "regeling_id": "reg-1",
        "regeling_work_id": "work-1",
        "doc_order": 1,
        "title": None,
        "structural_path": "bylaw/1",
        "node_label": "section",
        "html_title": '<div class="chunk-title">Far North</div>',
        "html": "<html><body>secret</body></html>",
        "text": "Bylaw text",
        "source_url": "https://example.test/bylaw",
        "xml_url": None,
        "date_effective": "2022-01-03",
        "date_modified": "2022-02-01",
        "retrieved": "2026-10-13",
    }


def test_html_municipal_keeps_a_row_without_source_policy() -> None:
    record = project_html_municipal_row(
        _html_row("Canada"),
        source_repo="endomorphosis/ipfs_canada_municipal_laws",
        source_revision=_SHA,
    )
    assert record is not None
    assert list(record) == list(LEGAL_RECORD_FIELDS)
    assert record["jurisdiction"] == "CA"
    assert record["title"] == "Far North"
    assert record["effective_date"] == "2022-01-03"
    assert record["authority"] == "Halifax"
    assert record["text"] == "Bylaw text"
    assert "<" not in str(record["title"])
    assert "<html" not in str(record["text"]).casefold()
    assert "html" not in record
    assert record["normalizer_version"] == "html-municipal-scraper/v1+legal-record/v1"
    assert record["provenance"]["source_policy"] is None
    assert record["provenance"]["content_complete"] is True
    assert record["provenance"]["regeling_id"] == "reg-1"


@pytest.mark.parametrize(
    ("country", "expected"),
    [
        ("NZ", "NZ"),
        ("BE", "BE"),
        ("ID", "ID"),
        ("PT", "PT"),
        ("new zealand", "NZ"),
    ],
)
def test_html_country_fold(country: str, expected: str) -> None:
    record = project_html_municipal_row(
        _html_row(country),
        source_repo="endomorphosis/ipfs_example_municipal_laws",
        source_revision=_SHA,
    )
    assert record is not None
    assert record["jurisdiction"] == expected


def test_html_unknown_country_is_dropped() -> None:
    assert (
        project_html_municipal_row(
            _html_row("Narnia"),
            source_repo="endomorphosis/ipfs_example_municipal_laws",
            source_revision=_SHA,
        )
        is None
    )


def test_american_municipal_text_stays_null() -> None:
    record = project_american_municipal_row(
        {
            "cid": "bafy-us",
            "doc_id": "d1",
            "doc_order": 3,
            "html_title": "<b>City code</b>",
            "html": "<html><body>do not copy</body></html>",
        },
        source_repo="endomorphosis/american_municipal_law",
        source_revision=_SHA,
    )
    assert record["jurisdiction"] == "US"
    assert record["admin_level"] == "us-municipal"
    assert record["instrument_type"] == "ordinance"
    assert record["title"] == "City code"
    assert record["text"] is None
    assert record["content_sha256"] is None
    assert record["provenance"]["content_complete"] is False
    assert "html" not in record
    assert record["normalizer_version"] == "american-municipal-html/v1+legal-record/v1"


def _world_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "cid": "bafy-world",
        "country_code": "FR",
        "doc_type": "statute",
        "title_native": "Code civil",
        "number": "Art. 1",
        "text": "Les lois",
        "content_complete": True,
        "source_policy": None,
        "source_official": True,
        "source_url": "https://example.test/fr",
        "language": "fr",
    }
    row.update(overrides)
    return row


def test_world_projector_drops_archived_and_unofficial_rows() -> None:
    kept = project_world_v11_row(
        _world_row(),
        source_repo="endomorphosis/world_national_law",
        source_revision=_SHA,
    )
    assert kept is not None
    assert kept["text"] == "Les lois"
    assert kept["citation"] == "Art. 1"
    assert kept["bluebook_citation"] is None
    assert kept["normalizer_version"] == "world-law/v1.1.0+legal-record/v1"
    assert "html" not in kept

    archived = project_world_v11_row(
        _world_row(source_policy="archived_robots_disallowed"),
        source_repo="endomorphosis/world_national_law",
        source_revision=_SHA,
    )
    unofficial = project_world_v11_row(
        _world_row(source_official=False),
        source_repo="endomorphosis/world_national_law",
        source_revision=_SHA,
    )
    omitted = project_world_v11_row(
        _world_row(country_code="US"),
        source_repo="endomorphosis/world_national_law",
        source_revision=_SHA,
        drop_us=True,
    )
    assert archived is None
    assert unofficial is None
    assert omitted is None


def test_world_incomplete_text_is_null() -> None:
    record = project_world_v11_row(
        _world_row(content_complete=False, text="<html><body>hidden</body></html>"),
        source_repo="endomorphosis/world_national_law",
        source_revision=_SHA,
    )
    assert record is not None
    assert record["text"] is None
    assert record["provenance"]["content_complete"] is False


def test_load_sharded_laws_writes_laws_and_rejects_a_short_revision(tmp_path: Path) -> None:
    source = tmp_path / "source"
    data = source / "data"
    data.mkdir(parents=True)
    pq.write_table(pa.table({"id": ["a"], "text": ["one"]}), data / "laws-00001.parquet")
    pq.write_table(pa.table({"id": ["b"], "text": ["two"]}), data / "laws-00002.parquet")
    pq.write_table(pa.table({"id": ["html"], "text": ["skip"]}), data / "laws-00003_html.parquet")
    pq.write_table(pa.table({"article": ["1"]}), data / "articles-00001.parquet")
    with pytest.raises(ValueError):
        load_sharded_laws(
            source,
            tmp_path / "bad",
            slug="spain_municipal",
            source_dataset="endomorphosis/ipfs_spain_municipal_laws",
            source_revision="not-a-sha",
        )
    dest = tmp_path / "packed"
    written = load_sharded_laws(
        source,
        dest,
        slug="spain_municipal",
        source_dataset="endomorphosis/ipfs_spain_municipal_laws",
        source_revision=_SHA,
    )
    laws = pq.read_table(written["laws"])
    assert laws.column("id").to_pylist() == ["a", "b"]
    assert Path(written["articles"]).is_file()
    meta = json.loads((dest / "pack_meta.json").read_text(encoding="utf-8"))
    assert meta["source_revision"] == _SHA
    assert meta["slug"] == "spain_municipal"
