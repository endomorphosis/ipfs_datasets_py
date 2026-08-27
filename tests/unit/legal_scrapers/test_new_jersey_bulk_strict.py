"""Strict prospective provenance and exact-frontier tests for New Jersey."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
    build_canonical_state_law_output_projection,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import base_scraper
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_jersey import (
    NewJerseyScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.new_jersey_bulk import (
    OFFICIAL_ZIP_URL,
    NewJerseyBulkFrontierError,
    looks_like_zip_bytes,
    parse_new_jersey_bulk_zip_bytes,
)

RTF = r"""{\rtf1\ansi
\pard\s2 TITLE 2C THE NEW JERSEY CODE OF CRIMINAL JUSTICE
\pard\s3 2C:11-3. Murder.
\pard A person is guilty of murder if the actor purposely causes death.
\pard\s3 2C:11-4. Manslaughter.
\pard Criminal homicide is manslaughter when it is committed recklessly.
\pard\s3 2C:11-5. Repealed.
\pard Repealed by L.2020, c.1.
}"""


def _zip_bytes(rtf: str = RTF, *, second_rtf: bool = False) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("STATUTES.RTF", rtf)
        archive.writestr("README.txt", "Official New Jersey Permanent Statutes")
        if second_rtf:
            archive.writestr("copy/STATUTES.RTF", rtf)
    return buffer.getvalue()


def test_zip_member_and_section_disposition_algebra_is_exact() -> None:
    payload = _zip_bytes()
    observed: list[dict] = []
    digest = hashlib.sha256(payload).hexdigest()
    rows = parse_new_jersey_bulk_zip_bytes(
        payload,
        bundle_provenance={
            "byte_size": len(payload),
            "content_sha256": digest,
            "media_type": "application/zip",
            "official_url": OFFICIAL_ZIP_URL,
            "retrieved_at": "2026-08-25T12:00:00+00:00",
            "transport_receipt": {
                "content_sha256": digest,
                "official_url": OFFICIAL_ZIP_URL,
                "source_transport": "direct",
            },
        },
        inventory_observer=lambda value: observed.append(dict(value)),
        fail_on_unusable=True,
    )

    assert [row.section_number for row in rows] == ["2C:11-3", "2C:11-4"]
    inventory = observed[0]
    assert inventory["archive_member_paths"] == ["README.txt", "STATUTES.RTF"]
    assert inventory["rtf_member"]["path"] == "STATUTES.RTF"
    assert inventory["rtf_member"]["content_sha256"] == hashlib.sha256(
        RTF.encode("cp1252")
    ).hexdigest()
    assert inventory["disposition"] == {
        "discovered": 3,
        "duplicates": 0,
        "excluded": 1,
        "failed_final": 0,
        "fetched": 2,
        "quarantined": 0,
    }
    assert inventory["excluded_source_record_ids"] == ["2C:11-5"]
    assert inventory["frontier"]["algebra_closed"] is True
    assert inventory["frontier"]["closed"] is True
    assert rows[0].structured_data["source_bundle"]["content_sha256"] == digest
    assert rows[0].structured_data["source_member"] == inventory["rtf_member"]


def test_ambiguous_rtf_members_and_duplicate_sections_fail_closed() -> None:
    ambiguous = _zip_bytes(second_rtf=True)
    assert looks_like_zip_bytes(ambiguous) is False
    with pytest.raises(NewJerseyBulkFrontierError, match="exact STATUTES.RTF"):
        parse_new_jersey_bulk_zip_bytes(
            ambiguous,
            fail_on_unusable=True,
        )

    duplicate_rtf = RTF.replace(
        "\\pard\\s3 2C:11-5. Repealed.",
        "\\pard\\s3 2C:11-4. Duplicate.\n\\pard Duplicate text.",
    )
    with pytest.raises(
        NewJerseyBulkFrontierError,
        match="unresolved records or a capped frontier",
    ):
        parse_new_jersey_bulk_zip_bytes(
            _zip_bytes(duplicate_rtf),
            fail_on_unusable=True,
        )


def test_source_shaped_repairs_and_typed_terminal_notices_close() -> None:
    rtf = r"""{\rtf1\ansi
\pard\s2 TITLE TEST
\pard\s3 14:8-22(1). First saved act paragraph.
\pard First parenthetical statute body remains operative.
\pard\s3 14:8-22(2). Second saved act paragraph.
\pard Second parenthetical statute body remains operative.
\pard\s3 9-3A-7 Responsibilities, duties of commissioner.
\pard The commissioner shall administer the department.
\pard\s3 C.52:16A-132 Reimbursement of members.
\pard Members are entitled to reimbursement of necessary expenses.
\pard\s3 52:9H 34 Findings, declarations.
\pard The Legislature finds and declares an economic public interest.
\pard\s3 App.A:3-1. Definitions
\pard Federal Government means the United States of America.
\pard\s3 18A:62-55 Collection of demographic information.
\pard\s3 1. Institutions shall collect the information. L.2017, c.268, s.1. 18A:62-56 Number of credits required.
\pard Institutions shall require one hundred twenty credit hours.
\pard\s3 45:8B-92 Practice of applied behavior analysis.
\pard\s3
\pard The practice affects public safety and welfare.
\pard\s3 5:12-173.23 to 5:12-173.26 has been reallocated to 5:12-163.3 to 5:12-163.6
\pard\s3 54:4-2.52 Repealed
\pard The following statutes are hereby repealed for a specified tax year.
\pard\s3 26:2H-12.2. Repealed by L.2005, c.83, s.20.
\pard\s3 46:30B-54. Blank
\pard L.1989, c.58, s.1.
}"""
    observed: list[dict] = []
    rows = parse_new_jersey_bulk_zip_bytes(
        _zip_bytes(rtf),
        bundle_provenance={
            "byte_size": 1,
            "content_sha256": "a" * 64,
            "media_type": "application/zip",
            "official_url": OFFICIAL_ZIP_URL,
            "retrieved_at": "2026-08-25T12:00:00+00:00",
        },
        inventory_observer=lambda value: observed.append(dict(value)),
        fail_on_unusable=True,
    )

    assert [row.section_number for row in rows] == [
        "14:8-22(1)",
        "14:8-22(2)",
        "9:3A-7",
        "52:16A-132",
        "52:9H-34",
        "App.A:3-1",
        "18A:62-55",
        "18A:62-56",
        "45:8B-92",
        "54:4-2.52",
    ]
    inventory = observed[0]
    assert inventory["disposition"] == {
        "discovered": 13,
        "duplicates": 0,
        "excluded": 3,
        "failed_final": 0,
        "fetched": 10,
        "quarantined": 0,
    }
    assert inventory["excluded_reason_counts"] == {
        "blank_placeholder": 1,
        "reallocation_notice": 1,
        "terminal_repealed_notice": 1,
    }
    assert inventory["admitted_record_kind_counts"] == {
        "appendix_a_statute": 1,
        "statute": 9,
    }
    assert inventory["frontier"]["closed"] is True


def test_saved_law_variant_and_exact_duplicate_are_source_bound() -> None:
    rtf = r"""{\rtf1\ansi
\pard\s2 TITLE 18A EDUCATION
\pard\s3 18A:6-32. Pension rights saved.
\pard The modern section summary remains operative law.
\pard\s3 18A:6-32 1943, c. 187 (C. 18:5-50.14 to C. 18:5-50.16 incl.)
\pard The complete saved act text remains operative law.
\pard\s3 2C:11-3. Murder.
\pard A person is guilty of murder if the actor purposely causes death.
\pard\s3 2C:11-3. Murder.
\pard A person is guilty of murder if the actor purposely causes death.
}"""
    observed: list[dict] = []
    rows = parse_new_jersey_bulk_zip_bytes(
        _zip_bytes(rtf),
        bundle_provenance={
            "byte_size": 1,
            "content_sha256": "b" * 64,
            "media_type": "application/zip",
            "official_url": OFFICIAL_ZIP_URL,
            "retrieved_at": "2026-08-25T12:00:00+00:00",
        },
        inventory_observer=lambda value: observed.append(dict(value)),
        fail_on_unusable=True,
    )

    assert [row.section_number for row in rows] == [
        "18A:6-32",
        "18A:6-32~saved-law~1943-c-187",
        "2C:11-3",
    ]
    inventory = observed[0]
    assert inventory["disposition"] == {
        "discovered": 4,
        "duplicates": 1,
        "excluded": 1,
        "failed_final": 0,
        "fetched": 3,
        "quarantined": 0,
    }
    assert inventory["duplicate_classification"] == {
        "divergent_source_record_variants": 0,
        "exact_duplicate_source_records": 1,
    }
    assert inventory["excluded_reason_counts"] == {
        "exact_duplicate_source_record": 1,
    }
    assert inventory["frontier"]["closed"] is True


def test_capped_bulk_parse_cannot_claim_strict_frontier_closure() -> None:
    with pytest.raises(NewJerseyBulkFrontierError, match="capped frontier"):
        parse_new_jersey_bulk_zip_bytes(
            _zip_bytes(),
            max_statutes=1,
            fail_on_unusable=True,
        )


def test_prospective_fetch_replay_and_canonical_identity_parity_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _zip_bytes()
    requested: list[str] = []

    def _official_response(**kwargs):
        requested.append(str(kwargs["url"]))
        return base_scraper._StateLawHttpResponse(
            status_code=200,
            final_url=OFFICIAL_ZIP_URL,
            body=payload,
            media_type="application/zip",
        )

    monkeypatch.setattr(base_scraper, "_state_law_http_request", _official_response)
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="NJ",
        parser_name="NewJerseyScraper",
    )
    scraper = NewJerseyScraper("NJ", "New Jersey")
    scraper.attach_state_law_acquisition_ledger(ledger)

    rows = asyncio.run(
        scraper._scrape_official_bulk_zip(
            code_name="New Jersey Statutes",
            max_statutes=None,
        )
    )
    assert requested == [OFFICIAL_ZIP_URL]
    assert len(ledger.entries) == 1
    assert [row.section_number for row in rows] == ["2C:11-3", "2C:11-4"]

    replay_ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="NJ",
        parser_name="NewJerseyScraper",
    )
    replay_scraper = NewJerseyScraper("NJ", "New Jersey")
    replay_scraper.attach_state_law_acquisition_ledger(replay_ledger)
    monkeypatch.setenv(
        NewJerseyScraper.BULK_RETAINED_SHA256_ENV,
        hashlib.sha256(payload).hexdigest(),
    )

    async def _network_forbidden(*_args, **_kwargs):
        raise AssertionError("digest-pinned replay must not enter a fetch path")

    monkeypatch.setattr(
        replay_scraper,
        "_fetch_parser_input_with_transport",
        _network_forbidden,
    )
    replayed_rows = asyncio.run(
        replay_scraper._scrape_official_bulk_zip(
            code_name="New Jersey Statutes",
            max_statutes=None,
        )
    )
    assert [row.section_number for row in replayed_rows] == [
        "2C:11-3",
        "2C:11-4",
    ]
    assert requested == [OFFICIAL_ZIP_URL]

    rows = [scraper._enrich_statute_structure(row) for row in rows]
    assert rows[0].structured_data["jsonld"]["provenance"][
        "source_record_id"
    ] == "2C:11-3"
    projection = build_canonical_state_law_output_projection(
        rows,
        jurisdiction="NJ",
    )

    closure_path = asyncio.run(
        scraper.produce_state_law_frontier_closure(
            canonical_output_projection=projection,
        )
    )
    closure = json.loads(closure_path.read_text(encoding="utf-8"))
    assert closure["official_source_url"] == OFFICIAL_ZIP_URL
    assert closure["acquisition_path_ids"] == ["nj-lis-statutes"]
    assert closure["completion_receipt"]["disposition"] == {
        "discovered": 3,
        "duplicates": 0,
        "excluded": 1,
        "failed_final": 0,
        "fetched": 2,
        "quarantined": 0,
    }
    assert closure["completion_receipt"]["frontier"]["closed"] is True
    assert closure["replayed_frontier"] == closure["completion_receipt"][
        "frontier"
    ]
    assert requested == [OFFICIAL_ZIP_URL]
    jsonld_path = tmp_path / "STATE-NJ.jsonld"
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


def test_missing_canonical_section_fails_zip_output_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _zip_bytes()

    def _official_response(**_kwargs):
        return base_scraper._StateLawHttpResponse(
            status_code=200,
            final_url=OFFICIAL_ZIP_URL,
            body=payload,
            media_type="application/zip",
        )

    monkeypatch.setattr(base_scraper, "_state_law_http_request", _official_response)
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="NJ",
        parser_name="NewJerseyScraper",
    )
    scraper = NewJerseyScraper("NJ", "New Jersey")
    scraper.attach_state_law_acquisition_ledger(ledger)
    rows = asyncio.run(
        scraper._scrape_official_bulk_zip(
            code_name="New Jersey Statutes",
            max_statutes=None,
        )
    )
    rows = [scraper._enrich_statute_structure(row) for row in rows]
    projection = build_canonical_state_law_output_projection(
        rows[:1],
        jurisdiction="NJ",
    )

    with pytest.raises(RuntimeError, match="do not exactly match"):
        asyncio.run(
            scraper.produce_state_law_frontier_closure(
                canonical_output_projection=projection,
            )
        )


def test_opt_in_retained_official_zip_has_exact_closed_algebra() -> None:
    from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import (
        _filter_strict_full_text_statutes,
    )

    retained_path = str(
        os.getenv("NEW_JERSEY_BULK_TEST_RETAINED_ZIP") or ""
    ).strip()
    if not retained_path:
        pytest.skip("set NEW_JERSEY_BULK_TEST_RETAINED_ZIP for retained replay")
    path = Path(retained_path)
    if path.is_symlink() or not path.is_file():
        pytest.fail("retained New Jersey test ZIP must be a regular file")
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    assert digest == (
        "65d965acddd759cf1381301873dbcfebfc3eff624f096d776c99308fa1beecf0"
    )

    observed: list[dict] = []
    rows = parse_new_jersey_bulk_zip_bytes(
        payload,
        bundle_provenance={
            "byte_size": len(payload),
            "content_sha256": digest,
            "media_type": "application/zip",
            "official_url": OFFICIAL_ZIP_URL,
            "retrieved_at": "2026-08-25T17:51:25.994000Z",
        },
        inventory_observer=lambda value: observed.append(dict(value)),
        fail_on_unusable=True,
    )
    inventory = observed[0]

    assert inventory["disposition"] == {
        "discovered": 56_292,
        "duplicates": 0,
        "excluded": 11,
        "failed_final": 0,
        "fetched": 56_281,
        "quarantined": 0,
    }
    assert inventory["admitted_record_kind_counts"] == {
        "appendix_a_statute": 260,
        "saved_law_variant": 15,
        "statute": 56_006,
    }
    assert inventory["excluded_reason_counts"] == {
        "blank_placeholder": 2,
        "reallocation_notice": 8,
        "terminal_repealed_notice": 1,
    }
    assert inventory["duplicate_classification"] == {
        "divergent_source_record_variants": 0,
        "exact_duplicate_source_records": 0,
    }
    corrected = {
        row["source_record_id"]
        for row in inventory["identity_resolution_rows"]
        if row["reason"] == "source_bound_divergent_header_correction"
    }
    assert corrected == {
        "18A:33-27.3",
        "34:15C-10.5",
        "45:15-16.53",
        "49:3-89",
        "52:17B-194.21",
    }
    assert inventory["frontier"]["closed"] is True

    # The shared strict-text gate must not reinterpret the official parser's
    # colon-delimited section identities as navigation merely because their
    # operative text uses the word "calendar".  These are the exact 27 rows
    # that the pre-fix ``[.\-]`` identity signal removed from this pinned ZIP.
    kept, removed = _filter_strict_full_text_statutes(
        rows,
        min_full_text_chars=1,
    )
    assert removed == 0
    assert len(kept) == 56_281
    calendar_false_positive_ids = {
        "2A:19-8",
        "2A:33-8",
        "2A:37-4",
        "14A:2-5",
        "16:12-8",
        "18A:6-42",
        "18A:22-15",
        "18A:27-3",
        "18A:72A-21",
        "18A:74-11",
        "26:3-35",
        "26:4-120",
        "27:7-42",
        "34:15-93",
        "36:2-22",
        "40:62-103",
        "40:75-42",
        "43:13-23",
        "44:1-159",
        "44:4-121",
        "44:4-122",
        "44:4-127",
        "48:3-22",
        "54:4-56",
        "54:16-3",
        "54:16-4",
        "54:16-5",
    }
    assert len(calendar_false_positive_ids) == 27
    rows_by_id = {row.section_number: row for row in rows}
    assert all(
        "calendar"
        in (
            f"{rows_by_id[section_id].section_name} "
            f"{rows_by_id[section_id].full_text}"
        ).lower()
        and len(rows_by_id[section_id].full_text.strip()) < 1_200
        for section_id in calendar_false_positive_ids
    )
