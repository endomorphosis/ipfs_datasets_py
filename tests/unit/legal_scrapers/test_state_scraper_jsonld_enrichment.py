import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
    StatuteMetadata,
)
from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import (
    _compute_coverage_summary,
    _filter_strict_full_text_statutes,
    _trim_scraped_statutes_to_max,
    _write_state_jsonld_files,
)


class _DummyStateScraper(BaseStateScraper):
    def get_base_url(self) -> str:
        return "https://example.gov"

    def get_code_list(self):
        return []

    async def scrape_code(self, code_name: str, code_url: str):
        return []


def test_enrich_statute_structure_includes_uscode_style_fields():
    scraper = _DummyStateScraper("XY", "Example State")

    statute = NormalizedStatute(
        state_code="XY",
        state_name="Example State",
        statute_id="Code § 10-1",
        code_name="Example Code",
        title_number="10",
        title_name="General Provisions",
        chapter_number="1",
        chapter_name="Definitions",
        section_number="10-1",
        section_name="Definitions",
        full_text=(
            "Section 10-1: General definitions and scope. "
            "(a) This chapter applies to all agencies. "
            "(1) Agency means any executive office. "
            "(A) Includes boards and commissions. "
            "See 42 U.S.C. 1983 and Pub. L. 117-58, 135 Stat. 429."
        ),
        source_url="https://example.gov/code/10-1",
        metadata=StatuteMetadata(enacted_year="2025"),
    )

    enriched = scraper._enrich_statute_structure(statute)
    structured = enriched.structured_data

    assert isinstance(structured.get("preamble"), str)
    assert structured.get("preamble")
    assert isinstance(structured.get("subsections"), list)
    assert len(structured.get("subsections")) > 0

    citations = structured.get("citations")
    assert isinstance(citations, dict)
    assert citations.get("usc_citations")
    assert citations.get("public_laws")
    assert citations.get("statutes_at_large")

    jsonld = structured.get("jsonld")
    assert isinstance(jsonld, dict)
    assert jsonld.get("@type") == "Legislation"
    assert jsonld.get("preamble") == structured.get("preamble")
    assert jsonld.get("subsections") == structured.get("subsections")
    assert isinstance(jsonld.get("chapter"), dict)


def test_write_state_jsonld_files_emits_per_state_jsonld(tmp_path: Path):
    payload = {
        "@context": {"@vocab": "https://schema.org/"},
        "@type": "Legislation",
        "@id": "urn:state:xy:statute:Code-10-1",
        "name": "Definitions",
    }
    scraped_statutes = [
        {
            "state_code": "XY",
            "statutes": [
                {
                    "statute_id": "Code § 10-1",
                    "structured_data": {"jsonld": payload},
                }
            ],
        }
    ]

    files = _write_state_jsonld_files(scraped_statutes, tmp_path)

    assert len(files) == 1
    out_path = Path(files[0])
    assert out_path.exists()

    lines = out_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    doc = json.loads(lines[0])
    assert doc.get("@type") == "Legislation"
    assert doc.get("@id") == payload["@id"]


def test_filter_strict_full_text_statutes_removes_short_records():
    good = NormalizedStatute(
        state_code="XY",
        state_name="Example State",
        statute_id="Code § 11-1",
        full_text="A" * 500,
        source_url="https://example.gov/11-1",
    )
    bad = NormalizedStatute(
        state_code="XY",
        state_name="Example State",
        statute_id="Code § 11-2",
        full_text="Too short",
        source_url="https://example.gov/11-2",
    )

    kept, removed = _filter_strict_full_text_statutes([good, bad], min_full_text_chars=300)

    assert removed == 1
    assert len(kept) == 1
    assert kept[0].statute_id == "Code § 11-1"


def test_trim_scraped_statutes_to_max_truncates_in_state_order():
    scraped = [
        {
            "state_code": "AA",
            "statutes": [
                {"section_number": "1", "section_name": "Section 1", "full_text": "A" * 500},
                {"section_number": "2", "section_name": "Section 2", "full_text": "B" * 500},
            ],
        },
        {
            "state_code": "BB",
            "statutes": [
                {"section_number": "1", "section_name": "Section 1", "full_text": "C" * 500},
            ],
        },
    ]

    trimmed, total = _trim_scraped_statutes_to_max(scraped, max_statutes=2)

    assert total == 2
    assert len(trimmed) == 1
    assert trimmed[0]["state_code"] == "AA"
    assert len(trimmed[0]["statutes"]) == 2


def test_compute_coverage_summary_detects_zero_and_missing_states():
    selected_states = ["AA", "BB", "CC"]
    scraped_statutes = [
        {"state_code": "AA", "statutes": [{"section_number": "1"}]},
        {"state_code": "BB", "statutes": [], "error": "failed"},
    ]

    summary = _compute_coverage_summary(
        selected_states=selected_states,
        scraped_statutes=scraped_statutes,
        errors=["BB failed"],
    )

    assert summary["states_targeted"] == 3
    assert summary["states_returned"] == 2
    assert summary["states_with_nonzero_statutes"] == 1
    assert summary["zero_statute_states"] == ["BB"]
    assert summary["error_states"] == ["BB"]
    assert summary["missing_states"] == ["CC"]
    assert summary["coverage_gap_states"] == ["BB", "CC"]
    assert summary["full_coverage"] is False
