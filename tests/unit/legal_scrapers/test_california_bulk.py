"""Official California CAML bulk export adapter tests."""

from __future__ import annotations

import copy
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Dict

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionError,
    StateLawMultiFetchAcquisitionLedger,
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.california_bulk import (
    CA_CODES,
    LAW_SECTION_COLUMNS,
    CaliforniaBulkFrontierError,
    CaliforniaBulkProvenanceError,
    caml_to_text,
    load_california_bulk_transport_receipt,
    parse_california_bulk_zip,
    parse_california_bulk_zip_codes,
    session_zip_url,
)
from ipfs_datasets_py.utils import anyio_compat as asyncio


def _write_provenance_fixture(zip_path: Path) -> Dict[str, bytes]:
    bodies = {
        "LAB_1194.lob": (
            b"<caml:Content><p>Employees may recover all unpaid minimum wages."
            b" This sentence keeps the official source row substantive.</p></caml:Content>"
        ),
        "PEN_187.lob": (
            b"<caml:Content><p>Murder is the unlawful killing of a human being "
            b"with malice aforethought under this section.</p></caml:Content>"
        ),
    }
    table_rows = []
    for record_id, code, section, lob in (
        ("LAB1194.source", "LAB", "1194.", "LAB_1194.lob"),
        ("PEN187.source", "PEN", "187.", "PEN_187.lob"),
    ):
        columns = [""] * len(LAW_SECTION_COLUMNS)
        columns[0] = f"`{record_id}`"
        columns[1] = f"`{code}`"
        columns[2] = f"`{section}`"
        columns[6] = "`2025-01-01`"
        columns[7] = f"`version-{record_id}`"
        columns[11] = "`1`"
        columns[13] = "`Current law.`"
        columns[14] = f"`{lob}`"
        columns[15] = "`Y`"
        columns[16] = "`LEG_ESI`"
        columns[17] = "`2026-08-24 04:22:00`"
        table_rows.append("\t".join(columns))
    table_bytes = ("\n".join(table_rows) + "\n").encode()
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("LAW_SECTION_TBL.dat", table_bytes)
        for member_path, body in bodies.items():
            archive.writestr(member_path, body)
    return {"LAW_SECTION_TBL.dat": table_bytes, **bodies}


def _write_transport_receipt(
    zip_path: Path,
    *,
    official_url: str = "https://downloads.leginfo.legislature.ca.gov/pubinfo_2025.zip",
    content_sha256: str | None = None,
) -> Path:
    raw = zip_path.read_bytes()
    receipt_path = Path(f"{zip_path}.receipt.json")
    receipt_path.write_text(
        json.dumps(
            {
                "byte_size": len(raw),
                "content_sha256": content_sha256 or hashlib.sha256(raw).hexdigest(),
                "media_type": "application/zip",
                "official_url": official_url,
                "response_headers": {"content-length": str(len(raw))},
                "response_status": 200,
                "retrieved_at": "2026-08-24T15:41:23Z",
                "schema_version": "state-laws-large-file-transport-receipt-v1",
                "source_transport": "direct",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return receipt_path


def _official_table_row(
    *,
    source_record_id: str,
    code: str = "LAB",
    section: str = "1194.",
    body_member: str = "LAB_1194.lob",
) -> str:
    columns = [""] * len(LAW_SECTION_COLUMNS)
    columns[0] = f"`{source_record_id}`"
    columns[1] = f"`{code}`"
    columns[2] = f"`{section}`"
    columns[6] = "`2025-01-01`"
    columns[7] = f"`version-{source_record_id}`"
    columns[11] = "`1`"
    columns[13] = "`Current law.`"
    columns[14] = f"`{body_member}`"
    columns[15] = "`Y`"
    columns[16] = "`LEG_ESI`"
    columns[17] = "`2026-08-24 04:22:00`"
    return "\t".join(columns)


def _prepare_successful_frontier(
    tmp_path: Path,
    monkeypatch,
):
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.california import (
        CaliforniaScraper,
    )

    zip_path = tmp_path / "pubinfo_2025.zip"
    _write_provenance_fixture(zip_path)
    _write_transport_receipt(zip_path)
    monkeypatch.setenv("CALIFORNIA_BULK_ZIP", str(zip_path))
    monkeypatch.delenv("CALIFORNIA_BULK_ZIP_RECEIPT", raising=False)
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="CA",
        parser_name="CaliforniaScraper",
    )
    scraper = CaliforniaScraper("CA", "California")
    scraper.attach_state_law_acquisition_ledger(ledger)
    labor = scraper._scrape_official_bulk_zip(
        code_name="Labor Code",
        code_type="LAB",
        max_statutes=None,
    )
    penal = scraper._scrape_official_bulk_zip(
        code_name="Penal Code",
        code_type="PEN",
        max_statutes=None,
    )
    rows = [scraper._enrich_statute_structure(row) for row in labor + penal]
    projection = build_canonical_state_law_output_projection(
        rows,
        jurisdiction="CA",
    )
    return zip_path, ledger, scraper, rows, projection


def test_session_zip_url_is_official_downloads_host() -> None:
    url = session_zip_url("2025")
    assert url.startswith("https://downloads.leginfo.legislature.ca.gov/")
    assert url.endswith("pubinfo_2025.zip")
    assert "justia" not in url


def test_caml_fraction_is_not_concatenated() -> None:
    xml = (
        '<caml:Content xmlns:caml="urn:caml">'
        "<p>four-fifths (<caml:Fraction>"
        "<caml:Numerator>4</caml:Numerator>"
        "<caml:Denominator>5</caml:Denominator>"
        "</caml:Fraction>)</p>"
        "</caml:Content>"
    )
    text, unknown = caml_to_text(xml)
    assert "4/5" in text
    assert "(45)" not in text
    assert "caml:fraction" not in unknown


def test_parse_bulk_zip_emits_official_labor_code(tmp_path: Path) -> None:
    caml = (
        '<caml:Content xmlns:caml="urn:caml">'
        "<p>(a) Notwithstanding any agreement to the contrary, "
        "an employee may recover unpaid minimum wages.</p>"
        "</caml:Content>"
    )
    table = "id\t`LAB`\t`1194.`\t\t\t\t\t\t\t\t\t\t\t\t`LAB_1194.lob`\t\t\t`2025`"
    zip_path = tmp_path / "pubinfo_2025.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("LAW_SECTION_TBL.dat", table + "\n")
        archive.writestr("LAB_1194.lob", caml)
    rows = parse_california_bulk_zip(
        zip_path,
        code_type="LAB",
        code_name="Labor Code",
        max_statutes=4,
    )
    assert len(rows) == 1
    assert rows[0].section_number == "1194"
    assert "minimum wages" in rows[0].full_text
    assert rows[0].structured_data["source_authority_class"] == "official"
    assert rows[0].structured_data["source_kind"] == "official_california_bulk_caml"
    assert "leginfo.legislature.ca.gov" in rows[0].source_url
    assert "justia" not in rows[0].source_url


def test_parse_bulk_zip_admits_concise_complete_statute(tmp_path: Path) -> None:
    """A short official provision is not an empty or placeholder body."""

    zip_path = tmp_path / "pubinfo_2025.zip"
    table_row = _official_table_row(
        source_record_id="HSC4746.193960",
        code="HSC",
        section="4746.",
        body_member="LAW_SECTION_TBL_64764.lob",
    )
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("LAW_SECTION_TBL.dat", table_row + "\n")
        archive.writestr(
            "LAW_SECTION_TBL_64764.lob",
            (
                '<caml:Content xmlns:caml="urn:caml">'
                "<p>It may issue bonds.</p></caml:Content>"
            ),
        )

    rows = parse_california_bulk_zip(
        zip_path,
        code_type="HSC",
        code_name="Health and Safety Code",
        max_statutes=None,
    )

    assert len(rows) == 1
    assert rows[0].statute_id == "CA:HSC4746.193960"
    assert rows[0].full_text == "It may issue bonds."


def test_parse_bulk_zip_codes_reads_table_once_and_preserves_collisions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    zip_path = tmp_path / "pubinfo_2025.zip"
    table_rows = []
    bodies = {
        "LAB_1194.lob": "Employees may recover all unpaid minimum wages.",
        "PEN_187.lob": "Murder is the unlawful killing of a human being.",
        "GOV_84101_A.lob": "This conditional version governs before the operative date.",
        "GOV_84101_B.lob": "This conditional version governs after the operative date.",
        "CONS_I_1.lob": "All people are by nature free and independent.",
        "CONS_II_1.lob": "The boundaries of the State are those stated by law.",
    }
    for record_id, code, section, article, lob, effective_date, history in (
        (
            "LAB1194.source",
            "LAB",
            "1194.",
            "",
            "LAB_1194.lob",
            "2025-01-01",
            "Current labor section.",
        ),
        (
            "PEN187.source",
            "PEN",
            "187.",
            "",
            "PEN_187.lob",
            "2025-01-01",
            "Current penal section.",
        ),
        (
            "GOV84101.conditional-a",
            "GOV",
            "84101.",
            "",
            "GOV_84101_A.lob",
            "2025-01-01",
            "Operative until the condition occurs.",
        ),
        (
            "GOV84101.conditional-b",
            "GOV",
            "84101.",
            "",
            "GOV_84101_B.lob",
            "2026-01-01",
            "Operative when the condition occurs.",
        ),
        (
            "CONS-I-1.source",
            "CONS",
            "SECTION 1.",
            "I",
            "CONS_I_1.lob",
            "1974-11-05",
            "Article I history.",
        ),
        (
            "CONS-II-1.source",
            "CONS",
            "SEC. 1.",
            "II",
            "CONS_II_1.lob",
            "1879-01-01",
            "Article II history.",
        ),
    ):
        columns = [""] * 18
        columns[0] = f"`{record_id}`"
        columns[1] = f"`{code}`"
        columns[2] = f"`{section}`"
        columns[3] = "`2025`"
        columns[4] = "`1`"
        columns[5] = f"`{section.rstrip('.')}`"
        columns[6] = f"`{effective_date}`"
        columns[7] = f"`version-{record_id}`"
        columns[8] = "`division-raw`"
        columns[9] = "`title-raw`"
        columns[10] = "`part-raw`"
        columns[11] = "`chapter-raw`"
        columns[12] = f"`{article}`" if article else "NULL"
        columns[13] = f"`{history}`"
        columns[14] = f"`{lob}`"
        columns[15] = "`Y`"
        columns[16] = "`LEG_ESI`"
        columns[17] = "2026-08-24 04:22:00"
        table_rows.append("\t".join(columns))
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("LAW_SECTION_TBL.dat", "\n".join(table_rows) + "\n")
        for lob, text in bodies.items():
            archive.writestr(lob, f"<caml:Content><p>{text}</p></caml:Content>")

    original_read = zipfile.ZipFile.read
    table_reads = []

    def _counted_read(self, name, *args, **kwargs):
        if str(name).upper().endswith("LAW_SECTION_TBL.DAT"):
            table_reads.append(str(name))
        return original_read(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "read", _counted_read)
    rows_by_code = parse_california_bulk_zip_codes(
        zip_path,
        code_types=("LAB", "PEN", "GOV", "CONS", "LAB"),
        max_statutes=2,
        code_names={
            "LAB": "Labor Code",
            "PEN": "Penal Code",
            "GOV": "Government Code",
            "CONS": "California Constitution",
        },
    )

    assert table_reads == ["LAW_SECTION_TBL.dat"]
    assert list(rows_by_code) == ["LAB", "PEN", "GOV", "CONS"]
    assert {code: len(rows) for code, rows in rows_by_code.items()} == {
        "LAB": 1,
        "PEN": 1,
        "GOV": 2,
        "CONS": 2,
    }
    assert rows_by_code["CONS"][0].code_name == "California Constitution"
    assert rows_by_code["CONS"][0].structured_data["law_code"] == "CONS"
    assert rows_by_code["CONS"][0].structured_data["printed_section"] == "SECTION 1."
    assert (
        rows_by_code["CONS"][0].structured_data["source_record_id"]
        == "CONS-I-1.source"
    )
    assert [row.section_number for row in rows_by_code["CONS"]] == [
        "I § 1",
        "II § 1",
    ]
    assert len({row.statute_id for row in rows_by_code["CONS"]}) == 2
    assert "lawCode=CONS" in rows_by_code["CONS"][0].source_url

    gov_rows = rows_by_code["GOV"]
    assert [row.section_number for row in gov_rows] == ["84101", "84101"]
    assert [row.statute_id for row in gov_rows] == [
        "CA:GOV84101.conditional-a",
        "CA:GOV84101.conditional-b",
    ]
    assert gov_rows[0].structured_data["printed_cite"] == "GOV 84101."
    assert tuple(gov_rows[0].structured_data["law_section_table"]) == (
        LAW_SECTION_COLUMNS
    )
    assert gov_rows[0].structured_data["law_section_table"]["effective_date"] == (
        "2025-01-01"
    )
    assert gov_rows[1].structured_data["law_section_table"]["history"] == (
        "Operative when the condition occurs."
    )
    assert gov_rows[1].structured_data["law_section_table"]["active_flg"] == "Y"


def test_single_code_parser_delegates_to_multi_code_parser(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import california_bulk

    zip_path = tmp_path / "unused.zip"
    expected_row = object()
    calls = []

    def _fake_parse(path, **kwargs):
        calls.append((path, kwargs))
        return {"LAB": [expected_row]}

    monkeypatch.setattr(
        california_bulk,
        "parse_california_bulk_zip_codes",
        _fake_parse,
    )
    rows = california_bulk.parse_california_bulk_zip(
        zip_path,
        code_type="lab",
        code_name="Labor Code",
        max_statutes=7,
    )

    assert rows == [expected_row]
    assert calls == [
        (
            zip_path,
            {
                "code_types": ("LAB",),
                "max_statutes": 7,
                "code_names": {"LAB": "Labor Code"},
            },
        )
    ]


def test_california_scraper_caches_one_multi_code_parse_per_instance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.california import (
        CaliforniaScraper,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import california_bulk

    zip_path = tmp_path / "pubinfo_2025.zip"
    zip_path.write_bytes(b"PK\x03\x04")
    calls = []

    def _fake_parse(path, **kwargs):
        calls.append((path, kwargs))
        return {code: [] for code in kwargs["code_types"]}

    monkeypatch.setattr(california_bulk, "configured_bulk_zip_path", lambda: zip_path)
    monkeypatch.setattr(
        california_bulk,
        "parse_california_bulk_zip_codes",
        _fake_parse,
    )

    scraper = CaliforniaScraper("CA", "California")
    assert scraper._scrape_official_bulk_zip(
        code_name="Labor Code",
        code_type="LAB",
        max_statutes=5,
    ) == []
    assert scraper._scrape_official_bulk_zip(
        code_name="Penal Code",
        code_type="PEN",
        max_statutes=3,
    ) == []

    assert len(calls) == 1
    assert set(calls[0][1]["code_types"]) == set(CaliforniaScraper.CODE_TYPE_MAP.values())
    assert calls[0][1]["code_names"]["CONS"] == "California Constitution"
    assert calls[0][1]["max_statutes"] == 5

    other = CaliforniaScraper("CA", "California")
    other._scrape_official_bulk_zip(
        code_name="Labor Code",
        code_type="LAB",
        max_statutes=5,
    )
    assert len(calls) == 2


def test_california_scraper_caches_strict_parse_failure_by_bundle_digest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """One bad table pass must not reread a gigabyte archive per code family."""

    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        california_bulk,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.california import (
        CaliforniaScraper,
    )

    zip_path = tmp_path / "pubinfo_2025.zip"
    zip_path.write_bytes(b"PK\x03\x04")
    monkeypatch.setattr(california_bulk, "configured_bulk_zip_path", lambda: zip_path)
    parse_calls = []

    def _fail_parse(path, **kwargs):
        parse_calls.append((path, kwargs))
        raise CaliforniaBulkFrontierError("one deterministic unusable row")

    monkeypatch.setattr(california_bulk, "parse_california_bulk_zip_codes", _fail_parse)
    scraper = CaliforniaScraper("CA", "California")
    scraper._state_law_acquisition_ledger = object()
    monkeypatch.setattr(
        scraper,
        "_retain_official_bulk_zip_parser_input",
        lambda _path: {
            "content_sha256": "a" * 64,
            "retained_body_path": str(zip_path),
        },
    )

    for code_name, code_type in (("Labor Code", "LAB"), ("Penal Code", "PEN")):
        with pytest.raises(
            CaliforniaBulkFrontierError,
            match="one deterministic unusable row",
        ):
            scraper._scrape_official_bulk_zip(
                code_name=code_name,
                code_type=code_type,
                max_statutes=None,
            )

    assert len(parse_calls) == 1


def test_configured_bulk_preempts_constitution_html_for_cons(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        california_constitution,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
        NormalizedStatute,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.california import (
        CaliforniaScraper,
    )

    fallback_path = tmp_path / "constitution-fallback.html"
    fallback_path.write_text("fallback must not be parsed", encoding="utf-8")
    monkeypatch.setattr(
        california_constitution,
        "configured_constitution_html_path",
        lambda: fallback_path,
    )

    def _fallback_must_not_run(*_args, **_kwargs):
        raise AssertionError("bulk CONS rows must pre-empt the HTML fallback")

    monkeypatch.setattr(
        california_constitution,
        "parse_california_constitution_html",
        _fallback_must_not_run,
    )
    scraper = CaliforniaScraper("CA", "California")
    bulk_row = NormalizedStatute(
        state_code="CA",
        state_name="California",
        statute_id="CA:CONS-I-1.source",
        code_name="California Constitution",
        section_number="I § 1",
        section_name="Article I, Section 1",
        full_text="All people possess inalienable rights under this provision.",
        source_url=(
            "https://leginfo.legislature.ca.gov/faces/"
            "codes_displayText.xhtml?lawCode=CONS&article=I"
        ),
        official_cite="Cal. Const. art. I, § 1",
        structured_data={"law_code": "CONS"},
    )
    monkeypatch.setattr(
        scraper,
        "_scrape_official_bulk_zip",
        lambda **_kwargs: [bulk_row],
    )

    rows = asyncio.run(
        scraper.scrape_code(
            "California Constitution",
            "https://example.invalid",
            max_statutes=5,
        )
    )
    assert [row.statute_id for row in rows] == ["CA:CONS-I-1.source"]


def test_bulk_zip_is_retained_once_and_final_jsonld_has_ledger_coverage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.california import (
        CaliforniaScraper,
    )
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        california_bulk,
    )

    zip_path = tmp_path / "pubinfo_2025.zip"
    members = _write_provenance_fixture(zip_path)
    _write_transport_receipt(zip_path)
    bundle_digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    monkeypatch.setenv("CALIFORNIA_BULK_ZIP", str(zip_path))
    monkeypatch.delenv("CALIFORNIA_BULK_ZIP_RECEIPT", raising=False)

    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="CA",
        parser_name="CaliforniaScraper",
    )
    retain_calls = []
    original_retain = ledger.retain_parser_input_file

    def _counted_retain(**kwargs):
        retain_calls.append(kwargs)
        return original_retain(**kwargs)

    monkeypatch.setattr(ledger, "retain_parser_input_file", _counted_retain)
    parse_paths = []
    original_parse = california_bulk.parse_california_bulk_zip_codes

    def _counted_parse(path, **kwargs):
        parse_paths.append(Path(path))
        return original_parse(path, **kwargs)

    monkeypatch.setattr(
        california_bulk,
        "parse_california_bulk_zip_codes",
        _counted_parse,
    )
    scraper = CaliforniaScraper("CA", "California")
    scraper.attach_state_law_acquisition_ledger(ledger)

    labor = scraper._scrape_official_bulk_zip(
        code_name="Labor Code",
        code_type="LAB",
        max_statutes=5,
    )
    penal = scraper._scrape_official_bulk_zip(
        code_name="Penal Code",
        code_type="PEN",
        max_statutes=5,
    )
    assert len(retain_calls) == 1
    assert len(ledger.entries) == 1
    assert parse_paths == [ledger.entries[0].body_path]
    assert parse_paths[0] != zip_path
    assert [row.statute_id for row in labor + penal] == [
        "CA:LAB1194.source",
        "CA:PEN187.source",
    ]

    enriched = [
        scraper._enrich_statute_structure(row) for row in labor + penal
    ]
    jsonld_path = tmp_path / "STATE-CA.jsonld"
    jsonld_path.write_text(
        "".join(
            json.dumps(row.structured_data["jsonld"], sort_keys=True) + "\n"
            for row in enriched
        ),
        encoding="utf-8",
    )
    coverage = ledger.audit_canonical_jsonld_coverage(jsonld_path)
    assert coverage["complete"] is True
    assert coverage["covered_by_content_digest"] == 2
    assert coverage["covered_by_official_url"] == 0

    expected_transport = {
        "content_sha256": bundle_digest,
        "official_url": (
            "https://downloads.leginfo.legislature.ca.gov/pubinfo_2025.zip"
        ),
        "source_transport": "direct",
    }
    for row in enriched:
        structured = row.structured_data
        provenance = structured["jsonld"]["provenance"]
        assert structured["content_sha256"] == bundle_digest
        assert structured["transport_receipt"] == expected_transport
        assert provenance["content_sha256"] == bundle_digest
        assert provenance["source_record_id"] == structured["source_record_id"]
        assert provenance["transport_receipt"] == expected_transport
        assert provenance["source_table_row_number"] in {1, 2}
        assert provenance["source_bundle"] == {
            "byte_size": zip_path.stat().st_size,
            "content_sha256": bundle_digest,
            "media_type": "application/zip",
            "official_url": expected_transport["official_url"],
            "retrieved_at": "2026-08-24T15:41:23Z",
        }
        table_member = provenance["source_table_member"]
        assert table_member["path"] == "LAW_SECTION_TBL.dat"
        assert table_member["content_sha256"] == hashlib.sha256(
            members["LAW_SECTION_TBL.dat"]
        ).hexdigest()
        body_member = provenance["source_body_member"]
        assert body_member["content_sha256"] == hashlib.sha256(
            members[body_member["path"]]
        ).hexdigest()


def test_tampered_bulk_zip_is_rejected_before_parser_admission(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.california import (
        CaliforniaScraper,
    )

    zip_path = tmp_path / "pubinfo_2025.zip"
    _write_provenance_fixture(zip_path)
    receipt_path = _write_transport_receipt(zip_path)
    raw = bytearray(zip_path.read_bytes())
    raw[-1] ^= 1
    zip_path.write_bytes(bytes(raw))
    monkeypatch.setenv("CALIFORNIA_BULK_ZIP", str(zip_path))
    monkeypatch.setenv("CALIFORNIA_BULK_ZIP_RECEIPT", str(receipt_path))
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="CA",
        parser_name="CaliforniaScraper",
    )
    scraper = CaliforniaScraper("CA", "California")
    scraper.attach_state_law_acquisition_ledger(ledger)

    with pytest.raises(
        StateLawMultiFetchAcquisitionError,
        match="file-backed parser input lacks a verified origin receipt",
    ):
        scraper._scrape_official_bulk_zip(
            code_name="Labor Code",
            code_type="LAB",
            max_statutes=5,
        )
    assert ledger.entries == ()


def test_mismatched_bulk_receipt_official_url_is_rejected(tmp_path: Path) -> None:
    zip_path = tmp_path / "pubinfo_2025.zip"
    _write_provenance_fixture(zip_path)
    receipt_path = _write_transport_receipt(
        zip_path,
        official_url=(
            "https://downloads.leginfo.legislature.ca.gov/pubinfo_2023.zip"
        ),
    )

    with pytest.raises(
        CaliforniaBulkProvenanceError,
        match="does not identify the configured official pubinfo archive",
    ):
        load_california_bulk_transport_receipt(
            zip_path,
            receipt_path=receipt_path,
        )


def test_bulk_table_frontier_replays_and_closes_with_exact_output_parity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    zip_path, ledger, scraper, rows, projection = _prepare_successful_frontier(
        tmp_path,
        monkeypatch,
    )

    observation = scraper._california_first_bulk_inventory_observation
    inventory_path = ledger.jurisdiction_root / observation["relative_path"]
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    assert inventory["source_record_ids"] == [
        "LAB1194.source",
        "PEN187.source",
    ]
    assert inventory["source_record_count"] == 2
    assert inventory["admitted_source_record_count"] == 2
    assert inventory["unusable_rows"] == []
    assert inventory["frontier"]["closed"] is True
    assert inventory["frontier"]["bundle_closed"] is True
    assert inventory["table_member"]["path"] == "LAW_SECTION_TBL.dat"
    assert set(inventory["scope_code_families"]) == set(CA_CODES)
    assert set(inventory["code_family_counts"]) == set(CA_CODES)
    assert inventory["code_family_counts"]["LAB"]["admitted"] == 1
    assert inventory["code_family_counts"]["PEN"]["admitted"] == 1
    assert inventory["boundary_probes"]["first_source_record_id"] == (
        "LAB1194.source"
    )
    assert inventory["boundary_probes"]["last_source_record_id"] == (
        "PEN187.source"
    )

    closure_path = asyncio.run(
        scraper.produce_state_law_frontier_closure(
            canonical_output_projection=projection,
        )
    )
    assert closure_path.parent == ledger.closure_inputs_dir
    closure = json.loads(closure_path.read_text(encoding="utf-8"))
    completion = closure["completion_receipt"]
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    assert closure["official_source_url"] == (
        "https://downloads.leginfo.legislature.ca.gov/pubinfo_2025.zip"
    )
    assert closure["release_point"] == f"sha256:{digest}"
    assert closure["acquisition_path_ids"] == ["ca-leginfo"]
    assert completion["frontier"]["bundle_closed"] is True
    assert completion["frontier"]["table_row_count"] == 2
    assert completion["frontier"]["source_record_count"] == 2
    assert completion["source_frontier_inventory"]["source_record_count"] == 2
    assert completion["canonical_row_count"] == len(rows) == 2
    assert closure["replayed_frontier"] == completion["frontier"]
    assert ledger.verify_retained_frontier_closure_projection(
        projection,
        closure_input_path=closure_path,
    )[
        "canonical_row_count"
    ] == 2
    jsonld_path = tmp_path / "STATE-CA.jsonld"
    jsonld_path.write_text(
        "".join(
            json.dumps(row.structured_data["jsonld"], sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    closed = ledger.close_from_projection_file(
        closure_path,
        canonical_jsonld_path=jsonld_path,
    )
    assert closed.byte_verification.ok is True
    assert closed.frontier_verification.ok is True
    assert closed.normalized_source_receipt.admission_eligible is True


@pytest.mark.parametrize(
    ("case_name", "table_row", "members", "expected_reason"),
    [
        (
            "missing_lob",
            _official_table_row(
                source_record_id="LAB1194.missing",
                body_member="missing.lob",
            ),
            {},
            "missing_body_member",
        ),
        (
            "empty_body",
            _official_table_row(
                source_record_id="LAB1194.empty",
                body_member="empty.lob",
            ),
            {"empty.lob": b"<caml:Content><p>   </p></caml:Content>"},
            "empty_body",
        ),
        (
            "malformed_row",
            "`MALFORMED.source`\t`LAB`\t`1194.`",
            {},
            "malformed_table_row",
        ),
    ],
)
def test_bulk_table_unusable_rows_are_typed_and_fail_closed(
    tmp_path: Path,
    monkeypatch,
    case_name: str,
    table_row: str,
    members: Dict[str, bytes],
    expected_reason: str,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.california import (
        CaliforniaScraper,
    )

    zip_path = tmp_path / "pubinfo_2025.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("LAW_SECTION_TBL.dat", table_row + "\n")
        for member_path, body in members.items():
            archive.writestr(member_path, body)
    receipt_path = _write_transport_receipt(zip_path)
    monkeypatch.setenv("CALIFORNIA_BULK_ZIP", str(zip_path))
    monkeypatch.setenv("CALIFORNIA_BULK_ZIP_RECEIPT", str(receipt_path))
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / f"evidence-{case_name}",
        jurisdiction="CA",
        parser_name="CaliforniaScraper",
    )
    scraper = CaliforniaScraper("CA", "California")
    scraper.attach_state_law_acquisition_ledger(ledger)

    with pytest.raises(CaliforniaBulkFrontierError, match="unresolved records"):
        scraper._scrape_official_bulk_zip(
            code_name="Labor Code",
            code_type="LAB",
            max_statutes=None,
        )
    observation = scraper._california_first_bulk_inventory_observation
    inventory_path = ledger.jurisdiction_root / observation["relative_path"]
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    assert inventory["frontier"]["closed"] is False
    assert inventory["disposition"] == {
        "discovered": 1,
        "duplicates": 0,
        "excluded": 0,
        "failed_final": 1,
        "fetched": 0,
        "quarantined": 0,
    }
    assert inventory["unusable_row_count"] == 1
    assert inventory["unusable_rows"][0]["reason"] == expected_reason
    assert inventory["unusable_rows"][0]["disposition"] == "failed_final"
    assert len(ledger.entries) == 1
    assert not ledger.closure_input_path.exists()


def test_bulk_table_replay_inventory_mismatch_fails_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
        california_bulk,
    )

    _zip_path, _ledger, scraper, _rows, projection = (
        _prepare_successful_frontier(tmp_path, monkeypatch)
    )
    original_inventory = california_bulk.inventory_california_bulk_zip

    def _drifted_inventory(*args, **kwargs):
        inventory = copy.deepcopy(original_inventory(*args, **kwargs))
        inventory["table_member"]["content_sha256"] = "0" * 64
        inventory.pop("inventory_sha256")
        inventory["inventory_sha256"] = california_bulk._canonical_json_sha256(
            inventory
        )
        return inventory

    monkeypatch.setattr(
        california_bulk,
        "inventory_california_bulk_zip",
        _drifted_inventory,
    )
    with pytest.raises(RuntimeError, match="inventories differ"):
        asyncio.run(
            scraper.produce_state_law_frontier_closure(
                canonical_output_projection=projection,
            )
        )


def test_bulk_table_frontier_rejects_missing_canonical_source_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _zip_path, ledger, scraper, rows, _projection = _prepare_successful_frontier(
        tmp_path,
        monkeypatch,
    )
    incomplete_projection = build_canonical_state_law_output_projection(
        rows[:1],
        jurisdiction="CA",
    )

    with pytest.raises(RuntimeError, match="do not exactly match admitted"):
        asyncio.run(
            scraper.produce_state_law_frontier_closure(
                canonical_output_projection=incomplete_projection,
            )
        )
    assert not ledger.closure_input_path.exists()


def test_mutated_retained_bundle_fails_fixity_before_reinventory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _zip_path, ledger, scraper, _rows, projection = _prepare_successful_frontier(
        tmp_path,
        monkeypatch,
    )
    retained_path = ledger.entries[0].body_path
    with zipfile.ZipFile(retained_path, "w") as archive:
        archive.writestr(
            "LAW_SECTION_TBL.dat",
            _official_table_row(source_record_id="LAB1194.source") + "\n",
        )
        archive.writestr(
            "LAB_1194.lob",
            "<caml:Content><p>This mutated body remains long enough to parse."
            "</p></caml:Content>",
        )

    with pytest.raises(
        StateLawMultiFetchAcquisitionError,
        match="fixity replay",
    ):
        asyncio.run(
            scraper.produce_state_law_frontier_closure(
                canonical_output_projection=projection,
            )
        )
