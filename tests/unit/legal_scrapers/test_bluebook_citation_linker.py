from __future__ import annotations

from pathlib import Path
import random
import sys
import types
import uuid

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import ipfs_datasets_py.processors.legal_scrapers.justicedao_dataset_inventory as inventory_module
import ipfs_datasets_py.processors.legal_scrapers.bluebook_citation_linker as linker_module
from tests.integration.test_bluebook_citation_linker_real_corpora import _build_federal_register_cases

from ipfs_datasets_py.processors.legal_scrapers import (
    BluebookCitationResolver,
    CitationExtractor,
    audit_bluebook_exact_anchor_guarantees_for_documents,
    audit_bluebook_citation_resolution_for_documents,
    resolve_bluebook_lookup_result_document,
    resolve_bluebook_citations_in_text,
)
from ipfs_datasets_py.processors.legal_scrapers.bluebook_citation_linker import _CORPUS_CONFIGS

try:
    from hypothesis import given, settings, strategies as st
    HYPOTHESIS_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    HYPOTHESIS_AVAILABLE = False

    def given(*args, **kwargs):
        def _decorator(func):
            return func
        return _decorator

    def settings(*args, **kwargs):
        def _decorator(func):
            return func
        return _decorator

    class _HypothesisStub:
        def __getattr__(self, name):
            def _factory(*args, **kwargs):
                return None
            return _factory

    st = _HypothesisStub()


def _build_fuzz_resolver(tmp_path):
    uscode_path = tmp_path / "uscode_fuzz.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "title": "42",
                    "section": "1983",
                    "heading": "Civil action for deprivation of rights",
                    "text": "Every person who, under color of state law, subjects any citizen...",
                    "cid": "bafyuscode1983",
                    "source_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title42-section1983",
                    "identifier": "42 U.S.C. § 1983",
                },
                {
                    "title": "18",
                    "section": "2251(a)",
                    "heading": "Sexual exploitation of children",
                    "text": "Any person who employs a minor to engage in sexually explicit conduct...",
                    "cid": "bafyuscode2251a",
                    "source_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title18-section2251",
                    "identifier": "18 U.S.C. § 2251(a)",
                },
            ]
        ),
        uscode_path,
    )

    federal_register_path = tmp_path / "federal_register_fuzz.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "volume": "90",
                    "page": "12345",
                    "name": "Sample Final Rule",
                    "agency": "Environmental Protection Agency",
                    "citation": "90 FR 12345",
                    "semantic_text": "This rule updates reporting requirements under the Clean Air Act.",
                    "cid": "bafyfr9012345",
                    "fr_page_url": "https://www.federalregister.gov/citation/90-FR-12345",
                },
                {
                    "volume": "88",
                    "page": "54321",
                    "name": "Sample Proposed Rule",
                    "agency": "Department of Transportation",
                    "citation": "88 FR 54321",
                    "semantic_text": "This proposed rule addresses carrier reporting requirements.",
                    "cid": "bafyfr8854321",
                    "fr_page_url": "https://www.federalregister.gov/citation/88-FR-54321",
                },
            ]
        ),
        federal_register_path,
    )

    state_law_path = tmp_path / "state_laws_fuzz.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "state_code": "MN",
                    "official_cite": "Minn. Stat. § 518.17",
                    "code_name": "Stat.",
                    "section_number": "518.17",
                    "section_name": "Best interests of the child",
                    "full_text": "The best interests of the child means all relevant factors...",
                    "ipfs_cid": "bafymn51817",
                    "source_url": "https://www.revisor.mn.gov/statutes/cite/518.17",
                    "statute_id": "Minn. Stat. § 518.17",
                },
                {
                    "state_code": "OR",
                    "official_cite": "Or. Rev. Stat. § 90.155",
                    "code_name": "Rev. Stat.",
                    "section_number": "90.155",
                    "section_name": "Termination notice periods",
                    "full_text": "This section governs notice periods in residential tenancy.",
                    "ipfs_cid": "bafyor90155",
                    "source_url": "https://oregon.public.law/statutes/ors_90.155",
                    "statute_id": "Or. Rev. Stat. § 90.155",
                },
                {
                    "state_code": "NY",
                    "official_cite": "N.Y. Penal Code § 125.25",
                    "code_name": "Penal Code",
                    "section_number": "125.25",
                    "section_name": "Murder in the second degree",
                    "full_text": "A person is guilty of murder in the second degree when...",
                    "ipfs_cid": "bafyny12525",
                    "source_url": "https://www.nysenate.gov/legislation/laws/PEN/125.25",
                    "statute_id": "N.Y. Penal Code § 125.25",
                },
            ]
        ),
        state_law_path,
    )

    state_admin_rules_path = tmp_path / "state_admin_rules_fuzz.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "state_code": "MN",
                    "official_cite": "Minn. Admin. Code § 1400.5010",
                    "code_name": "Admin. Code",
                    "section_number": "1400.5010",
                    "section_name": "General contested case procedure",
                    "full_text": "This rule governs general contested case procedure before the agency.",
                    "ipfs_cid": "bafymnadmin14005010",
                    "source_url": "https://www.revisor.mn.gov/rules/1400.5010/",
                    "rule_id": "Minn. Admin. Code § 1400.5010",
                },
            ]
        ),
        state_admin_rules_path,
    )

    state_court_rules_path = tmp_path / "state_court_rules_fuzz.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "state_code": "OR",
                    "official_cite": "Or. Court Rules § 5.010",
                    "code_name": "Court Rules",
                    "section_number": "5.010",
                    "section_name": "Service and filing",
                    "full_text": "This rule governs service and filing requirements in Oregon courts.",
                    "ipfs_cid": "bafyorcourtrule5010",
                    "source_url": "https://www.courts.oregon.gov/rules/Pages/5.010.aspx",
                    "rule_id": "Or. Court Rules § 5.010",
                },
            ]
        ),
        state_court_rules_path,
    )

    cap_cases_path = tmp_path / "cap_cases_fuzz.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "id": "cap_brown_v_board",
                    "title": "Brown v. Board of Education",
                    "citation": "347 U.S. 483",
                    "reporter": "U.S.",
                    "volume": "347",
                    "page": "483",
                    "cid": "bafycase347483",
                    "source_url": "https://cite.case.law/us/347/483/",
                },
                {
                    "id": "cap_roe_v_wade",
                    "title": "Roe v. Wade",
                    "citation": "410 U.S. 113",
                    "reporter": "U.S.",
                    "volume": "410",
                    "page": "113",
                    "cid": "bafycase410113",
                    "source_url": "https://cite.case.law/us/410/113/",
                },
            ]
        ),
        cap_cases_path,
    )

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={
            "us_code": [str(uscode_path)],
            "federal_register": [str(federal_register_path)],
            "state_laws": [str(state_law_path)],
            "state_admin_rules": [str(state_admin_rules_path)],
            "state_court_rules": [str(state_court_rules_path)],
            "caselaw_access_project": [str(cap_cases_path)],
        },
    )

    cases = [
        {
            "corpus_key": "us_code",
            "citation_type": "usc",
            "variants": [
                "42 U.S.C. § 1983",
                "42 USC 1983",
                "42 U.S.C. 1983",
            ],
            "expected_state": None,
            "expected_source_cid": "bafyuscode1983",
            "expected_source_title": "Civil action for deprivation of rights",
        },
        {
            "corpus_key": "us_code",
            "citation_type": "usc",
            "variants": [
                "18 U.S.C. § 2251(a)",
                "18 USC 2251(a)",
                "18 U.S.C. 2251(a)",
            ],
            "expected_state": None,
            "expected_source_cid": "bafyuscode2251a",
            "expected_source_title": "Sexual exploitation of children",
        },
        {
            "corpus_key": "federal_register",
            "citation_type": "federal_register",
            "variants": [
                "90 FR 12345",
                "90 Fed. Reg. 12345",
            ],
            "expected_state": None,
            "expected_source_cid": "bafyfr9012345",
            "expected_source_title": "Sample Final Rule",
        },
        {
            "corpus_key": "federal_register",
            "citation_type": "federal_register",
            "variants": [
                "88 FR 54321",
                "88 Fed. Reg. 54321",
            ],
            "expected_state": None,
            "expected_source_cid": "bafyfr8854321",
            "expected_source_title": "Sample Proposed Rule",
        },
        {
            "corpus_key": "state_laws",
            "citation_type": "state_statute",
            "variants": [
                "Minn. Stat. § 518.17",
                "Minn. Stat. 518.17",
            ],
            "expected_state": "MN",
            "expected_source_cid": "bafymn51817",
            "expected_source_title": "Best interests of the child",
        },
        {
            "corpus_key": "state_laws",
            "citation_type": "state_statute",
            "variants": [
                "Or. Rev. Stat. § 90.155",
                "Or. Rev. Stat. 90.155",
            ],
            "expected_state": "OR",
            "expected_source_cid": "bafyor90155",
            "expected_source_title": "Termination notice periods",
        },
        {
            "corpus_key": "state_laws",
            "citation_type": "state_statute",
            "variants": [
                "N.Y. Penal Code § 125.25",
                "N.Y. Penal Code 125.25",
            ],
            "expected_state": "NY",
            "expected_source_cid": "bafyny12525",
            "expected_source_title": "Murder in the second degree",
        },
        {
            "corpus_key": "state_admin_rules",
            "citation_type": "state_statute",
            "variants": [
                "Minn. Admin. Code § 1400.5010",
                "Minn. Admin. Code 1400.5010",
            ],
            "expected_state": "MN",
            "expected_source_cid": "bafymnadmin14005010",
            "expected_source_title": "General contested case procedure",
        },
        {
            "corpus_key": "state_court_rules",
            "citation_type": "state_statute",
            "variants": [
                "Or. Court Rules § 5.010",
                "Or. Court Rules 5.010",
            ],
            "expected_state": "OR",
            "expected_source_cid": "bafyorcourtrule5010",
            "expected_source_title": "Service and filing",
        },
        {
            "corpus_key": "caselaw_access_project",
            "citation_type": "case",
            "variants": [
                "347 U.S. 483",
                "Brown v. Board of Education, 347 U.S. 483",
            ],
            "expected_state": None,
            "expected_source_cid": "bafycase347483",
            "expected_source_title": "Brown v. Board of Education",
        },
        {
            "corpus_key": "caselaw_access_project",
            "citation_type": "case",
            "variants": [
                "410 U.S. 113",
                "Roe v. Wade, 410 U.S. 113 (1973)",
            ],
            "expected_state": None,
            "expected_source_cid": "bafycase410113",
            "expected_source_title": "Roe v. Wade",
        },
    ]
    return resolver, cases


def _wrap_citation_text(citation_text: str, random_gen: random.Random) -> str:
    prefixes = [
        "The complaint cites ",
        "The motion relies on ",
        "Authorities include ",
        "Counsel referenced ",
        "See also ",
    ]
    suffixes = [
        " for the governing rule.",
        ", among other authorities.",
        " in support of the argument.",
        "; the court should review it carefully.",
        ".",
    ]
    return f"{random_gen.choice(prefixes)}{citation_text}{random_gen.choice(suffixes)}"


def _render_multi_citation_text(selected_cases, random_gen: random.Random) -> str:
    intro_phrases = [
        "The brief cites ",
        "Authorities include ",
        "The motion relies on ",
        "Counsel referenced ",
    ]
    separators = [", ", "; ", " and ", ", as well as "]
    wrappers = [
        lambda text: text,
        lambda text: f"({text})",
        lambda text: f"[{text}]",
        lambda text: f'"{text}"',
    ]
    outro_phrases = [
        " to support the requested relief.",
        " in support of the argument.",
        " as controlling authority.",
        ".",
    ]

    rendered = []
    for case in selected_cases:
        variant = random_gen.choice(case["variants"])
        rendered.append(
            {
                "variant": variant,
                "expected_type": case["citation_type"],
                "expected_corpus": case["corpus_key"],
                "expected_state": case["expected_state"],
                "rendered": random_gen.choice(wrappers)(variant),
            }
        )

    text = random_gen.choice(intro_phrases)
    for index, item in enumerate(rendered):
        if index:
            text += random_gen.choice(separators)
        text += item["rendered"]
    text += random_gen.choice(outro_phrases)
    return text, rendered


def _build_negative_fuzz_cases():
    return [
        "The record references 42 USCX 1983 in an internal code.",
        "The serial number is 18 U.S.CC. 2251(a).",
        "The invoice reads 90 F.RX 12345.",
        "See N.Y. Penal Coder § 125.25 for the typo case.",
        "The memo mentions Minnn. Stat. § 518.17 by mistake.",
        "Product code Or. Rev. Stats. § 90.155 is not a legal citation.",
        "This line says 88 Fed Regx 54321 in plain text.",
        "The address is 125.25 Penal Code Avenue, N.Y.",
    ]


def test_citation_extractor_extracts_bluebook_state_statute():
    extractor = CitationExtractor()
    citations = extractor.extract_citations(
        "Under Minn. Stat. § 518.17, the court must evaluate the best interests factors."
    )

    state_citations = [citation for citation in citations if citation.type == "state_statute"]
    assert len(state_citations) == 1
    assert state_citations[0].jurisdiction == "MN"
    assert state_citations[0].metadata["code_name"] == "Stat."
    assert state_citations[0].section == "518.17"


def test_citation_extractor_extracts_oregon_ors_shorthand():
    extractor = CitationExtractor()
    citations = extractor.extract_citations(
        "The petition relies on ORS 127.652 for the governing procedure."
    )

    state_citations = [citation for citation in citations if citation.type == "state_statute"]
    assert len(state_citations) == 1
    assert state_citations[0].jurisdiction == "OR"
    assert state_citations[0].metadata["code_name"] == "ORS"
    assert state_citations[0].section == "127.652"


def test_citation_extractor_extracts_bluebook_admin_and_court_rules():
    extractor = CitationExtractor()
    citations = extractor.extract_citations(
        "See Minn. Admin. Code § 1400.5010 and Or. Court Rules § 5.010 for procedure."
    )

    state_citations = [citation for citation in citations if citation.type == "state_statute"]
    assert len(state_citations) == 2
    assert state_citations[0].jurisdiction == "MN"
    assert state_citations[0].metadata["code_name"] == "Admin. Code"
    assert state_citations[0].section == "1400.5010"
    assert state_citations[1].jurisdiction == "OR"
    assert state_citations[1].metadata["code_name"] == "Court Rules"
    assert state_citations[1].section == "5.010"


def test_citation_extractor_extracts_michigan_case_reporters_and_public_law_no():
    extractor = CitationExtractor()
    citations = extractor.extract_citations(
        "Authorities include People v. Smith, 329 Mich. 683, 68 Mich. App. 272, and Pub. L. No. 117-58."
    )

    case_citations = [citation for citation in citations if citation.type == "case"]
    case_texts = {citation.text for citation in case_citations}
    assert "329 Mich. 683" in case_texts
    assert "68 Mich. App. 272" in case_texts

    by_text = {citation.text: citation for citation in case_citations}
    assert by_text["329 Mich. 683"].court == "Michigan Supreme Court"
    assert by_text["68 Mich. App. 272"].court == "Michigan Court of Appeals"

    public_law_citations = [citation for citation in citations if citation.type == "public_law"]
    assert len(public_law_citations) == 1
    assert public_law_citations[0].text == "Pub. L. No. 117-58"


def test_bluebook_citation_resolver_links_usc_and_state_law_from_local_parquet(tmp_path):
    uscode_path = tmp_path / "uscode.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "title": "42",
                    "section": "1983",
                    "heading": "Civil action for deprivation of rights",
                    "text": "Every person who, under color of state law, subjects any citizen...",
                    "cid": "bafyuscode1983",
                    "source_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title42-section1983",
                    "identifier": "42 U.S.C. § 1983",
                }
            ]
        ),
        uscode_path,
    )

    state_law_path = tmp_path / "state_laws.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "state_code": "MN",
                    "official_cite": "Minn. Stat. § 518.17",
                    "code_name": "Stat.",
                    "section_number": "518.17",
                    "section_name": "Best interests of the child",
                    "full_text": "The best interests of the child means all relevant factors...",
                    "ipfs_cid": "bafymn51817",
                    "source_url": "https://www.revisor.mn.gov/statutes/cite/518.17",
                    "statute_id": "Minn. Stat. § 518.17",
                }
            ]
        ),
        state_law_path,
    )

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={
            "us_code": [str(uscode_path)],
            "state_laws": [str(state_law_path)],
        },
    )

    links = resolve_bluebook_citations_in_text(
        "Claims may proceed under 42 U.S.C. § 1983 and Minn. Stat. § 518.17.",
        resolver=resolver,
    )

    by_type = {link.citation_type: link for link in links}
    assert by_type["usc"].matched is True
    assert by_type["usc"].corpus_key == "us_code"
    assert by_type["usc"].source_cid == "bafyuscode1983"

    assert by_type["state_statute"].matched is True
    assert by_type["state_statute"].corpus_key == "state_laws"
    assert by_type["state_statute"].source_cid == "bafymn51817"
    assert by_type["state_statute"].source_title == "Best interests of the child"
    assert "justicedao/ipfs_state_laws" in by_type["state_statute"].metadata["preferred_dataset_ids"]
    assert "STATE-MN.parquet" in by_type["state_statute"].metadata["preferred_parquet_files"]
    assert by_type["state_statute"].metadata["resolution_quality"] == "exact_anchor"
    assert by_type["state_statute"].metadata["source_provenance"]["guarantee_level"] == "exact_anchor"
    assert by_type["state_statute"].metadata["source_provenance"]["primary_citation"] == "Minn. Stat. § 518.17"
    assert by_type["state_statute"].metadata["source_provenance"]["source_row_hash"]


def test_bluebook_citation_resolver_rejects_cross_state_section_collision(tmp_path):
    state_law_path = tmp_path / "state_laws_cross_state.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "state_code": "MN",
                    "official_cite": "Minn. Stat. § 90.155",
                    "code_name": "Stat.",
                    "section_number": "90.155",
                    "section_name": "Unrelated Minnesota section",
                    "full_text": "This is not the Oregon ORS section.",
                    "ipfs_cid": "bafymn90155",
                    "source_url": "https://www.revisor.mn.gov/",
                    "statute_id": "Minn. Stat. § 90.155",
                }
            ]
        ),
        state_law_path,
    )

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={"state_laws": [str(state_law_path)]},
    )

    links = resolve_bluebook_citations_in_text(
        "The filing relies on Or. Rev. Stat. § 90.155.",
        resolver=resolver,
    )

    assert len(links) == 1
    link = links[0]
    assert link.citation_type == "state_statute"
    assert link.matched is False
    assert link.source_cid in {None, ""}


def test_bluebook_citation_resolver_strict_mode_toggle_allows_non_anchor_legacy_match(tmp_path):
    uscode_path = tmp_path / "uscode_identifier_only.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "identifier": "42 U.S.C. § 1983",
                    "heading": "Civil action for deprivation of rights",
                    "text": "Every person who, under color of state law, subjects any citizen...",
                    "cid": "bafyuscode1983",
                    "source_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title42-section1983",
                }
            ]
        ),
        uscode_path,
    )

    strict_resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        require_exact_anchor=True,
        parquet_file_overrides={"us_code": [str(uscode_path)]},
    )
    strict_links = resolve_bluebook_citations_in_text(
        "Claims may proceed under 42 U.S.C. § 1983.",
        resolver=strict_resolver,
    )
    assert len(strict_links) == 1
    assert strict_links[0].matched is False

    permissive_resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        require_exact_anchor=False,
        parquet_file_overrides={"us_code": [str(uscode_path)]},
    )
    permissive_links = resolve_bluebook_citations_in_text(
        "Claims may proceed under 42 U.S.C. § 1983.",
        resolver=permissive_resolver,
    )
    assert len(permissive_links) == 1
    assert permissive_links[0].matched is True
    assert permissive_links[0].metadata["require_exact_anchor"] is False


def test_bluebook_exact_anchor_guarantee_audit_flags_case_url_fallback_non_exact():
    resolver = BluebookCitationResolver(allow_hf_fallback=False, require_exact_anchor=False)

    report = audit_bluebook_exact_anchor_guarantees_for_documents(
        [
            {
                "document_id": "doc_1",
                "title": "Case-only fallback test",
                "text": "The filing relies on 38 Mich. 90 as authority.",
            }
        ],
        resolver=resolver,
        exhaustive=False,
    )

    assert report["document_count"] == 1
    assert report["matched_citation_count"] == 1
    assert report["non_exact_match_count"] == 1
    assert report["non_exact_matches"][0]["resolution_method"] == "citation_url_fallback"


def test_bluebook_citation_resolver_surfaces_recovery_metadata_for_unmatched_state_law(tmp_path):
    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={
            "state_laws": [str(tmp_path / "missing_state_laws.parquet")],
        },
    )

    links = resolve_bluebook_citations_in_text(
        "The motion relies on Minn. Stat. § 999.999.",
        resolver=resolver,
    )

    assert len(links) == 1
    link = links[0]
    assert link.matched is False
    assert link.metadata["recovery_supported"] is True
    assert link.metadata["recovery_corpus_key"] == "state_laws"
    assert "Minn. Stat. § 999.999" in link.metadata["recovery_query"]
    assert "site:.gov" in link.metadata["recovery_query"]


def test_bluebook_citation_resolver_does_not_falsely_match_state_law_on_metadata_only(tmp_path):
    state_law_path = tmp_path / "state_laws.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "state_code": "MN",
                    "official_cite": "Minn. Stat. § 518.17",
                    "code_name": "Stat.",
                    "section_number": "518.17",
                    "section_name": "Best interests of the child",
                    "full_text": "The best interests of the child means all relevant factors...",
                    "ipfs_cid": "bafymn51817",
                    "source_url": "https://www.revisor.mn.gov/statutes/cite/518.17",
                    "statute_id": "Minn. Stat. § 518.17",
                }
            ]
        ),
        state_law_path,
    )

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={"state_laws": [str(state_law_path)]},
    )

    links = resolve_bluebook_citations_in_text(
        "The supplemental brief cites Minn. Stat. § 999.999.",
        resolver=resolver,
    )

    assert len(links) == 1
    link = links[0]
    assert link.matched is False
    assert link.matched_field in {None, ""}
    assert link.source_url in {None, ""}
    assert link.source_cid in {None, ""}
    assert link.metadata["recovery_supported"] is True


def test_bluebook_citation_resolver_matches_state_law_via_source_id_section_alias(tmp_path):
    state_law_path = tmp_path / "state_laws_source_id_only.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "state_code": "MN",
                    "source_id": "urn:state:mn:statute:Minnesota Statutes § Section-15",
                    "name": "Chief Clerk",
                    "text": "Section Section-15: Chief Clerk",
                    "ipfs_cid": "bafymnsection15",
                    "source_url": "https://www.revisor.mn.gov/statutes/cite/15",
                }
            ]
        ),
        state_law_path,
    )

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={"state_laws": [str(state_law_path)]},
    )

    links = resolve_bluebook_citations_in_text(
        "The filing relies on Minn. Stat. § 15.",
        resolver=resolver,
    )

    assert len(links) == 1
    link = links[0]
    assert link.matched is True
    assert link.corpus_key == "state_laws"
    assert link.source_cid == "bafymnsection15"
    assert link.source_title == "Chief Clerk"
    assert link.matched_field in {"source_id", "text", "state_code"}


def test_bluebook_citation_resolver_links_federal_register_from_local_parquet(tmp_path):
    fr_path = tmp_path / "federal_register.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "volume": "90",
                    "page": "12345",
                    "name": "Sample Final Rule",
                    "agency": "Environmental Protection Agency",
                    "citation": "90 FR 12345",
                    "semantic_text": "This rule updates reporting requirements under the Clean Air Act.",
                    "cid": "bafyfr9012345",
                    "fr_page_url": "https://www.federalregister.gov/citation/90-FR-12345",
                }
            ]
        ),
        fr_path,
    )

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={"federal_register": [str(fr_path)]},
    )
    links = resolve_bluebook_citations_in_text(
        "See 90 FR 12345 for the final rule notice.",
        resolver=resolver,
    )

    assert len(links) == 1
    assert links[0].matched is True
    assert links[0].corpus_key == "federal_register"
    assert links[0].source_cid == "bafyfr9012345"
    assert links[0].source_url == "https://www.federalregister.gov/citation/90-FR-12345"


def test_bluebook_citation_resolver_matches_ors_identifier_alias(tmp_path):
    state_law_path = tmp_path / "state_laws_or.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "state_code": "OR",
                    "identifier": "ORS 801.545",
                    "name": "Section 801.545",
                    "text": "Traffic crime. Traffic crime means any traffic offense that is punishable by a jail sentence.",
                    "ipfs_cid": "bafyors801545",
                    "source_url": "https://www.oregonlegislature.gov/bills_laws/ors/ors801.html#section-801.545",
                }
            ]
        ),
        state_law_path,
    )

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={"state_laws": [str(state_law_path)]},
    )

    links = resolve_bluebook_citations_in_text(
        "The filing relies on ORS 801.545.",
        resolver=resolver,
    )

    assert len(links) == 1
    link = links[0]
    assert link.matched is True
    assert link.corpus_key == "state_laws"
    assert link.source_cid == "bafyors801545"
    assert link.source_url == "https://www.oregonlegislature.gov/bills_laws/ors/ors801.html#section-801.545"


def test_bluebook_lookup_result_document_suggests_citation_for_malformed_text(tmp_path):
    state_law_path = tmp_path / "state_laws_or.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "state_code": "OR",
                    "identifier": "ORS 801.545",
                    "name": "Section 801.545",
                    "text": "Traffic crime. Traffic crime means any traffic offense that is punishable by a jail sentence.",
                    "ipfs_cid": "bafyors801545",
                    "source_url": "https://www.oregonlegislature.gov/bills_laws/ors/ors801.html#section-801.545",
                }
            ]
        ),
        state_law_path,
    )

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={"state_laws": [str(state_law_path)]},
    )

    result = resolve_bluebook_lookup_result_document(
        "The filing relies on ORSS 801.545 as authority.",
        resolver=resolver,
        state_code="OR",
        exhaustive=False,
        include_recovery=False,
    )

    assert result["citation_count"] == 0
    suggestions = result["citation_suggestions"]
    assert suggestions
    assert suggestions[0]["suggested_citation"] == "ORS 801.545"
    assert suggestions[0]["estimate_vector"]["token_overlap"] > 0
    assert suggestions[0]["confidence"] > 0


def test_bluebook_lookup_result_document_suggests_for_unmatched_citation(tmp_path):
    state_law_path = tmp_path / "state_laws_or.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "state_code": "OR",
                    "identifier": "ORS 801.545",
                    "name": "Section 801.545",
                    "text": "Traffic crime. Traffic crime means any traffic offense that is punishable by a jail sentence.",
                    "ipfs_cid": "bafyors801545",
                    "source_url": "https://www.oregonlegislature.gov/bills_laws/ors/ors801.html#section-801.545",
                }
            ]
        ),
        state_law_path,
    )

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={"state_laws": [str(state_law_path)]},
    )

    result = resolve_bluebook_lookup_result_document(
        "The filing relies on ORS 801.546 as authority.",
        resolver=resolver,
        state_code="OR",
        exhaustive=False,
        include_recovery=False,
    )

    assert result["citation_count"] == 1
    assert result["unmatched_citation_count"] == 1
    unresolved = result["unresolved_citations"][0]
    suggestions = unresolved["citation_suggestions"]
    assert suggestions
    assert suggestions[0]["suggested_citation"] == "ORS 801.545"
    assert suggestions[0]["estimate_vector"]["token_overlap"] > 0
    assert suggestions[0]["confidence"] > 0
    merged = result["citation_suggestions"]
    assert merged
    assert merged[0]["suggested_citation"] == "ORS 801.545"


def test_bluebook_citation_resolver_suggests_for_malformed_usc(tmp_path):
    uscode_path = tmp_path / "us_code.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "title": "42",
                    "section": "1983",
                    "identifier": "42 U.S.C. § 1983",
                    "heading": "Civil action for deprivation of rights",
                    "ipfs_cid": "bafyusc1983",
                    "source_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title42-section1983",
                }
            ]
        ),
        uscode_path,
    )

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={"us_code": [str(uscode_path)]},
    )

    suggestions = resolver.suggest_citations_for_text("42 USC 1983")
    assert suggestions
    assert suggestions[0]["suggested_citation"] == "42 U.S.C. § 1983"
    assert suggestions[0]["estimate_vector"]["token_overlap"] > 0
    assert suggestions[0]["confidence"] > 0


def test_bluebook_citation_resolver_suggests_for_malformed_cfr(tmp_path):
    fr_path = tmp_path / "fr_cfr.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "title": "40",
                    "section": "122.41",
                    "citation": "40 C.F.R. § 122.41",
                    "semantic_text": "Conditions applicable to all NPDES permits.",
                    "cid": "bafycfr12241",
                    "fr_page_url": "https://www.ecfr.gov/current/title-40/section-122.41",
                }
            ]
        ),
        fr_path,
    )

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={"federal_register": [str(fr_path)]},
    )

    suggestions = resolver.suggest_citations_for_text("40 CFR 122.41")
    assert suggestions
    assert suggestions[0]["suggested_citation"] == "40 C.F.R. § 122.41"
    assert suggestions[0]["estimate_vector"]["token_overlap"] > 0
    assert suggestions[0]["confidence"] > 0


def test_bluebook_citation_resolver_suggests_for_malformed_fed_reg(tmp_path):
    fr_path = tmp_path / "fr_reg.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "volume": "89",
                    "page": "12345",
                    "citation": "89 Fed. Reg. 12345",
                    "semantic_text": "Notice of proposed rulemaking.",
                    "cid": "bafyfr12345",
                    "fr_page_url": "https://www.federalregister.gov/d/2024-00000",
                }
            ]
        ),
        fr_path,
    )

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={"federal_register": [str(fr_path)]},
    )

    suggestions = resolver.suggest_citations_for_text("89 Fed Reg 12345")
    assert suggestions
    assert suggestions[0]["suggested_citation"] == "89 Fed. Reg. 12345"
    assert suggestions[0]["estimate_vector"]["token_overlap"] > 0
    assert suggestions[0]["confidence"] > 0


def test_normalize_malformed_citation_repairs_common_abbreviations():
    from ipfs_datasets_py.processors.legal_data.bluebook_citation_linker import (
        _normalize_malformed_citation,
    )

    assert _normalize_malformed_citation("ORSS 801.545") == "ORS 801.545"
    assert _normalize_malformed_citation("Cal Stat § Code 12.34") == "Cal. Stat. Code § 12.34"
    assert _normalize_malformed_citation("N.Y. Stat § 5") == "N.Y. Stat. § 5"
    assert _normalize_malformed_citation("Tex Stat § 1.01") == "Tex. Stat. § 1.01"
    assert _normalize_malformed_citation("40 CFR § 122.41") == "40 C.F.R. § 122.41"
    assert _normalize_malformed_citation("42 USC § 1983") == "42 U.S.C. § 1983"
    assert _normalize_malformed_citation("42 USC 1983") == "42 U.S.C. § 1983"
    assert _normalize_malformed_citation("Pub L 117-2") == "Pub. L. 117-2"
    assert _normalize_malformed_citation("Fed Reg 89 12345") == "Fed. Reg. 89 12345"


def test_bluebook_citation_resolver_links_admin_and_court_rules_from_local_parquet(tmp_path):
    admin_path = tmp_path / "state_admin_rules.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "state_code": "MN",
                    "official_cite": "Minn. Admin. Code § 1400.5010",
                    "code_name": "Admin. Code",
                    "section_number": "1400.5010",
                    "section_name": "General contested case procedure",
                    "full_text": "This rule governs general contested case procedure before the agency.",
                    "ipfs_cid": "bafymnadmin14005010",
                    "source_url": "https://www.revisor.mn.gov/rules/1400.5010/",
                    "rule_id": "Minn. Admin. Code § 1400.5010",
                }
            ]
        ),
        admin_path,
    )

    court_path = tmp_path / "state_court_rules.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "state_code": "OR",
                    "official_cite": "Or. Court Rules § 5.010",
                    "code_name": "Court Rules",
                    "section_number": "5.010",
                    "section_name": "Service and filing",
                    "full_text": "This rule governs service and filing requirements in Oregon courts.",
                    "ipfs_cid": "bafyorcourtrule5010",
                    "source_url": "https://www.courts.oregon.gov/rules/Pages/5.010.aspx",
                    "rule_id": "Or. Court Rules § 5.010",
                }
            ]
        ),
        court_path,
    )

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={
            "state_admin_rules": [str(admin_path)],
            "state_court_rules": [str(court_path)],
        },
    )
    links = resolve_bluebook_citations_in_text(
        "Procedure is governed by Minn. Admin. Code § 1400.5010 and Or. Court Rules § 5.010.",
        resolver=resolver,
    )

    by_text = {link.citation_text: link for link in links}
    assert by_text["Minn. Admin. Code § 1400.5010"].matched is True
    assert by_text["Minn. Admin. Code § 1400.5010"].corpus_key == "state_admin_rules"
    assert by_text["Minn. Admin. Code § 1400.5010"].source_cid == "bafymnadmin14005010"

    assert by_text["Or. Court Rules § 5.010"].matched is True
    assert by_text["Or. Court Rules § 5.010"].corpus_key == "state_court_rules"
    assert by_text["Or. Court Rules § 5.010"].source_cid == "bafyorcourtrule5010"


def test_bluebook_citation_resolver_links_case_cfr_and_public_law_from_local_parquet(tmp_path):
    cap_path = tmp_path / "cap_cases.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "id": "cap_brown_v_board",
                    "title": "Brown v. Board of Education",
                    "citation": "347 U.S. 483",
                    "reporter": "U.S.",
                    "volume": "347",
                    "page": "483",
                    "source_url": "https://cite.case.law/us/347/483/",
                }
            ]
        ),
        cap_path,
    )

    federal_register_path = tmp_path / "fr_cfr.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "title": "40",
                    "section": "122.41",
                    "citation": "40 C.F.R. § 122.41",
                    "semantic_text": "Conditions applicable to all NPDES permits.",
                    "cid": "bafycfr12241",
                    "fr_page_url": "https://www.ecfr.gov/current/title-40/section-122.41",
                }
            ]
        ),
        federal_register_path,
    )

    uscode_public_law_path = tmp_path / "uscode_public_law.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "identifier": "Pub. L. 117-2",
                    "congress": "117",
                    "law_number": "2",
                    "heading": "Infrastructure Investment and Jobs Act",
                    "cid": "bafypl1172",
                    "source_url": "https://www.congress.gov/public-laws/117th-congress",
                }
            ]
        ),
        uscode_public_law_path,
    )

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={
            "caselaw_access_project": [str(cap_path)],
            "federal_register": [str(federal_register_path)],
            "us_code": [str(uscode_public_law_path)],
        },
    )

    links = resolve_bluebook_citations_in_text(
        "See Brown v. precedent at 347 U.S. 483, 40 C.F.R. § 122.41, and Pub. L. 117-2.",
        resolver=resolver,
    )

    by_type = {link.citation_type: link for link in links}
    assert by_type["case"].matched is True
    assert by_type["case"].corpus_key == "caselaw_access_project"

    assert by_type["cfr"].matched is True
    assert by_type["cfr"].corpus_key in {"federal_register", "us_code"}

    assert by_type["public_law"].matched is True
    assert by_type["public_law"].source_cid == "bafypl1172"


def test_bluebook_citation_resolver_links_cap_style_case_rows_from_local_parquet(tmp_path):
    cap_path = tmp_path / "cap_cases.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "id": "cap_long_v_sinclair",
                    "name": "John R. Long v. Robert P. Sinclair",
                    "name_abbreviation": "Long v. Sinclair",
                    "citations": "38 Mich. 90",
                    "reporter": "Michigan Reports",
                    "volume": "38",
                    "first_page": "90",
                    "source_url": "https://cite.case.law/mich/38/90/",
                }
            ]
        ),
        cap_path,
    )

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={"caselaw_access_project": [str(cap_path)]},
    )

    links = resolve_bluebook_citations_in_text(
        "The filing relies on 38 Mich. 90 as authority.",
        resolver=resolver,
    )

    assert len(links) == 1
    assert links[0].citation_type == "case"
    assert links[0].matched is True
    assert links[0].corpus_key == "caselaw_access_project"
    assert links[0].source_url == "https://cite.case.law/mich/38/90/"


def test_bluebook_citation_resolver_falls_back_to_case_url_when_case_source_query_fails():
    resolver = BluebookCitationResolver(allow_hf_fallback=False)

    links = resolve_bluebook_citations_in_text(
        "The filing relies on 38 Mich. 90 as authority.",
        resolver=resolver,
    )

    assert len(links) == 1
    assert links[0].citation_type == "case"
    assert links[0].matched is False
    assert links[0].confidence == 0.0
    assert links[0].corpus_key == "caselaw_access_project"
    assert links[0].metadata["resolution_method"] == "citation_url_fallback"
    assert links[0].metadata["resolution_quality"] == "non_exact_fallback"
    assert links[0].metadata["require_exact_anchor"] is True
    assert links[0].metadata["source_row_present"] is False
    assert links[0].source_url == "https://www.courtlistener.com/opinion/38/mich/90/"


def test_bluebook_citation_resolver_permissive_mode_keeps_case_url_fallback_as_match():
    resolver = BluebookCitationResolver(allow_hf_fallback=False, require_exact_anchor=False)

    links = resolve_bluebook_citations_in_text(
        "The filing relies on 38 Mich. 90 as authority.",
        resolver=resolver,
    )

    assert len(links) == 1
    assert links[0].citation_type == "case"
    assert links[0].matched is True
    assert links[0].confidence > 0.0
    assert links[0].metadata["resolution_method"] == "citation_url_fallback"
    assert links[0].metadata["require_exact_anchor"] is False


def test_bluebook_citation_resolver_links_public_law_no_variant_from_local_parquet(tmp_path):
    uscode_public_law_path = tmp_path / "uscode_public_law.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "identifier": "Pub. L. 117-58",
                    "congress": "117",
                    "law_number": "58",
                    "heading": "Infrastructure Investment and Jobs Act",
                    "cid": "bafypl11758",
                    "source_url": "https://www.congress.gov/public-laws/117th-congress",
                }
            ]
        ),
        uscode_public_law_path,
    )

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={"us_code": [str(uscode_public_law_path)]},
    )

    links = resolve_bluebook_citations_in_text(
        "Congress enacted Pub. L. No. 117-58 to fund infrastructure.",
        resolver=resolver,
    )

    assert len(links) == 1
    assert links[0].citation_type == "public_law"
    assert links[0].normalized_citation == "Pub. L. No. 117-58"
    assert links[0].matched is True
    assert links[0].corpus_key == "us_code"
    assert links[0].source_cid == "bafypl11758"
    assert links[0].source_title == "Infrastructure Investment and Jobs Act"


def test_bluebook_citation_resolver_prefers_primary_federal_register_hf_parquet(monkeypatch):
    listed_repo_ids = []

    def fake_list_repo_files(*, repo_id, repo_type):
        assert repo_type == "dataset"
        listed_repo_ids.append(repo_id)
        return [
            "federal_register_gte_small_metadata.parquet",
            "federal_register.parquet",
            "semantic.index",
        ]

    fake_hf_module = types.SimpleNamespace(
        list_repo_files=fake_list_repo_files,
        hf_hub_url=lambda *, repo_id, repo_type, filename: f"hf://{repo_id}/{filename}",
    )
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hf_module)

    resolver = BluebookCitationResolver(allow_hf_fallback=True)

    sources = resolver._find_hf_sources(_CORPUS_CONFIGS["federal_register"], state_code=None)

    assert listed_repo_ids == ["justicedao/ipfs_federal_register"]
    assert sources == [
        "hf://justicedao/ipfs_federal_register/federal_register.parquet",
    ]


def test_bluebook_citation_resolver_uses_inventory_to_rank_opaque_hf_parquet_names(monkeypatch):
    listed_repo_ids = []

    def fake_list_repo_files(*, repo_id, repo_type):
        assert repo_type == "dataset"
        listed_repo_ids.append(repo_id)
        return [
            "live/archive/A.parquet",
            "live/archive/B.parquet",
        ]

    fake_hf_module = types.SimpleNamespace(
        list_repo_files=fake_list_repo_files,
        hf_hub_url=lambda *, repo_id, repo_type, filename: f"hf://{repo_id}/{filename}",
    )
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hf_module)
    monkeypatch.setattr(
        inventory_module,
        "inspect_justicedao_datasets",
        lambda **kwargs: [
            inventory_module.DatasetProfile(
                dataset_id="justicedao/ipfs_federal_register",
                canonical_corpus_key="federal_register",
                legal_branch="us",
                country_codes=["US"],
                parquet_files=["live/archive/B.parquet"],
                top_level_paths=["live"],
                configs=[
                    inventory_module.DatasetConfigProfile(
                        config="default",
                        split="train",
                        query_modes=["identifier_lookup", "jsonld_lookup"],
                    )
                ],
            )
        ],
    )

    resolver = BluebookCitationResolver(allow_hf_fallback=True)

    sources = resolver._find_hf_sources(_CORPUS_CONFIGS["federal_register"], state_code=None)

    assert listed_repo_ids == ["justicedao/ipfs_federal_register"]
    assert sources == [
        "hf://justicedao/ipfs_federal_register/live/archive/B.parquet",
        "hf://justicedao/ipfs_federal_register/live/archive/A.parquet",
    ]


def test_bluebook_citation_resolver_uses_datasets_server_parquet_fallback_on_hf_429(monkeypatch):
    listed_repo_ids = []

    def fake_list_repo_files(*, repo_id, repo_type):
        assert repo_type == "dataset"
        listed_repo_ids.append(repo_id)
        raise RuntimeError("429 Too Many Requests")

    fake_hf_module = types.SimpleNamespace(
        list_repo_files=fake_list_repo_files,
        hf_hub_url=lambda *, repo_id, repo_type, filename: f"hf://{repo_id}/{filename}",
    )
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hf_module)

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "parquet_files": [
                    {
                        "dataset": "justicedao/ipfs_state_laws",
                        "config": "state_laws_embeddings",
                        "split": "train",
                        "filename": "0000.parquet",
                        "url": "https://huggingface.co/datasets/justicedao/ipfs_state_laws/resolve/refs%2Fconvert%2Fparquet/state_laws_embeddings/train/0000.parquet",
                    },
                    {
                        "dataset": "justicedao/ipfs_state_laws",
                        "config": "state_laws_canonical",
                        "split": "train",
                        "filename": "0000.parquet",
                        "url": "https://huggingface.co/datasets/justicedao/ipfs_state_laws/resolve/refs%2Fconvert%2Fparquet/state_laws_canonical/train/0000.parquet",
                    },
                ]
            }

    monkeypatch.setattr(
        "requests.get",
        lambda url, timeout=30: _Response(),
    )

    resolver = BluebookCitationResolver(allow_hf_fallback=True)

    sources = resolver._find_hf_sources(_CORPUS_CONFIGS["state_laws"], state_code="MN")

    assert listed_repo_ids == ["justicedao/ipfs_state_laws"]
    assert sources == [
        "https://huggingface.co/datasets/justicedao/ipfs_state_laws/resolve/refs%2Fconvert%2Fparquet/state_laws_canonical/train/0000.parquet",
        "https://huggingface.co/datasets/justicedao/ipfs_state_laws/resolve/refs%2Fconvert%2Fparquet/state_laws_embeddings/train/0000.parquet",
    ]


def test_build_federal_register_cases_ignores_non_bluebook_identifier(tmp_path):
    federal_register_path = tmp_path / "federal_register_sampling.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "identifier": "X94-90401",
                    "volume": "59",
                    "page": "1001",
                    "name": "Sample Rule",
                }
            ]
        ),
        federal_register_path,
    )

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={"federal_register": [str(federal_register_path)]},
    )

    cases = _build_federal_register_cases(None, resolver, sample_size=1)

    assert cases == [
        {
            "citation_text": "59 FR 1001",
            "citation_type": "federal_register",
            "corpus_key": "federal_register",
            "state_code": None,
            "source_ref": str(federal_register_path),
        }
    ]


def test_build_federal_register_cases_extracts_citation_from_jsonld(tmp_path):
    federal_register_path = tmp_path / "federal_register_jsonld_sampling.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "identifier": "94-8025",
                    "name": "Hearing of the Judicial Conference Advisory Committee on Rules of Criminal Procedure",
                    "jsonld": (
                        '{"text":"In the Federal Register of December 21, 1993 '
                        '(58 FR 67420), a public hearing was originally scheduled."}'
                    ),
                }
            ]
        ),
        federal_register_path,
    )

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={"federal_register": [str(federal_register_path)]},
    )

    cases = _build_federal_register_cases(None, resolver, sample_size=1)

    assert cases == [
        {
            "citation_text": "58 FR 67420",
            "citation_type": "federal_register",
            "corpus_key": "federal_register",
            "state_code": None,
            "source_ref": str(federal_register_path),
        }
    ]


def test_bluebook_citation_resolver_uses_exhaustive_canonical_query_fallback(monkeypatch):
    expected_row = {
        "title": "42",
        "section": "1983",
        "heading": "Civil action for deprivation of rights",
        "identifier": "42 U.S.C. § 1983",
        "source_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title42-section1983",
        "cid": "bafyuscode1983",
        "text": "Every person who, under color of state law, subjects any citizen...",
    }

    def fake_query_canonical_legal_corpus(*args, **kwargs):
        return inventory_module.CanonicalCorpusQueryResult(
            corpus_key="us_code",
            dataset_id="justicedao/ipfs_uscode",
            mode="lexical",
            query_text=str(kwargs.get("query_text") or ""),
            parquet_file="/tmp/uscode_hydrated.parquet",
            citation_links=[],
            results=[
                {
                    "title": expected_row["heading"],
                    "score": 0.95,
                    "source_url": expected_row["source_url"],
                    "source_cid": expected_row["cid"],
                    "row": dict(expected_row),
                }
            ],
            notes=["Resolved with lexical fallback."],
        )

    monkeypatch.setattr(inventory_module, "query_canonical_legal_corpus", fake_query_canonical_legal_corpus)

    resolver = BluebookCitationResolver(allow_hf_fallback=False, parquet_file_overrides={"us_code": []})

    links = resolve_bluebook_citations_in_text(
        "The filing relies on 42 U.S.C. § 1983 as authority.",
        resolver=resolver,
        exhaustive=True,
    )

    assert len(links) == 1
    link = links[0]
    assert link.matched is True
    assert link.corpus_key == "us_code"
    assert link.source_cid == "bafyuscode1983"
    assert link.metadata["resolution_method"] == "canonical_lexical_query"
    assert link.metadata["exhaustive_query_enabled"] is True
    assert link.metadata["row"]["identifier"] == "42 U.S.C. § 1983"


def test_resolve_bluebook_lookup_result_document_returns_exhaustive_payload(monkeypatch):
    expected_row = {
        "title": "42",
        "section": "1983",
        "heading": "Civil action for deprivation of rights",
        "identifier": "42 U.S.C. § 1983",
        "source_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title42-section1983",
        "cid": "bafyuscode1983",
        "text": "Every person who, under color of state law, subjects any citizen...",
    }

    def fake_query_canonical_legal_corpus(*args, **kwargs):
        return inventory_module.CanonicalCorpusQueryResult(
            corpus_key="us_code",
            dataset_id="justicedao/ipfs_uscode",
            mode="lexical",
            query_text=str(kwargs.get("query_text") or ""),
            parquet_file="/tmp/uscode_hydrated.parquet",
            citation_links=[],
            results=[
                {
                    "title": expected_row["heading"],
                    "score": 0.95,
                    "source_url": expected_row["source_url"],
                    "source_cid": expected_row["cid"],
                    "row": dict(expected_row),
                }
            ],
            notes=["Resolved with lexical fallback."],
        )

    monkeypatch.setattr(inventory_module, "query_canonical_legal_corpus", fake_query_canonical_legal_corpus)

    resolver = BluebookCitationResolver(allow_hf_fallback=False, parquet_file_overrides={"us_code": []})

    result = resolve_bluebook_lookup_result_document(
        "The filing relies on 42 U.S.C. § 1983 as authority.",
        resolver=resolver,
        exhaustive=True,
    )

    assert result["source"] == "bluebook_lookup_result_document"
    assert result["exhaustive"] is True
    assert result["citation_count"] == 1
    assert result["matched_citation_count"] == 1
    assert result["citations"][0]["matched"] is True
    assert result["citations"][0]["metadata"]["resolution_method"] == "canonical_lexical_query"


def test_resolve_bluebook_lookup_result_document_includes_recovery_for_unmatched(monkeypatch):
    async def fake_recover_missing_legal_citation_source(**kwargs):
        return {
            "status": "tracked",
            "citation_text": kwargs["citation_text"],
            "normalized_citation": kwargs["normalized_citation"],
            "corpus_key": kwargs["corpus_key"],
            "state_code": kwargs["state_code"],
            "candidate_count": 1,
            "archived_count": 0,
            "candidates": [
                {
                    "url": "https://www.revisor.mn.gov/statutes/cite/999.999",
                    "title": "Recovered statute candidate",
                    "source_type": "current",
                    "source": "multi_engine",
                    "score": 12,
                }
            ],
            "manifest_path": "/tmp/recovery_manifest.json",
        }

    monkeypatch.setattr(
        linker_module,
        "resolve_bluebook_citations_in_text",
        resolve_bluebook_citations_in_text,
    )
    recovery_module = __import__(
        "ipfs_datasets_py.processors.legal_scrapers.legal_source_recovery",
        fromlist=["recover_missing_legal_citation_source"],
    )
    monkeypatch.setattr(
        recovery_module,
        "recover_missing_legal_citation_source",
        fake_recover_missing_legal_citation_source,
    )

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={
            "state_laws": ["/tmp/missing_state_laws.parquet"],
        },
    )

    result = resolve_bluebook_lookup_result_document(
        "The motion relies on Minn. Stat. § 999.999.",
        resolver=resolver,
        exhaustive=True,
        include_recovery=True,
        recovery_archive_top_k=0,
    )

    assert result["unmatched_citation_count"] == 1
    assert result["recovery"]["enabled"] is True
    assert result["recovery"]["attempted"] is True
    assert len(result["recovery_results"]) == 1
    assert result["recovery_results"][0]["status"] == "tracked"
    assert result["recovery_results"][0]["citation_text"] == "Minn. Stat. § 999.999"


def test_resolve_bluebook_lookup_result_document_recovers_when_hf_lookup_misses_entirely(monkeypatch):
    captured = {}

    async def fake_recover_missing_legal_citation_source(**kwargs):
        captured.update(kwargs)
        return {
            "status": "tracked_and_published",
            "citation_text": kwargs["citation_text"],
            "normalized_citation": kwargs["normalized_citation"],
            "corpus_key": kwargs["corpus_key"],
            "state_code": kwargs["state_code"],
            "candidate_count": 1,
            "archived_count": 0,
            "publish_report": {"uploaded": True},
            "candidate_files": [
                {
                    "url": "https://www.oregonlegislature.gov/bills_laws/ors/ors801.html#section-801.545",
                    "fetch_success": True,
                }
            ],
            "scraper_patch": {
                "patch_path": "/tmp/recovery.patch",
                "target_file": "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py",
            },
        }

    recovery_module = __import__(
        "ipfs_datasets_py.processors.legal_scrapers.legal_source_recovery",
        fromlist=["recover_missing_legal_citation_source"],
    )
    monkeypatch.setattr(
        recovery_module,
        "recover_missing_legal_citation_source",
        fake_recover_missing_legal_citation_source,
    )

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={"state_laws": ["/tmp/missing_state_laws.parquet"]},
    )

    result = resolve_bluebook_lookup_result_document(
        "The filing relies on ORSS 801.545 as authority.",
        resolver=resolver,
        state_code="OR",
        exhaustive=False,
        include_recovery=True,
        publish_recovery_to_hf=True,
        hf_token="hf-test-token",
        recovery_archive_top_k=0,
    )

    assert result["citation_count"] == 0
    assert result["recovery"]["attempted"] is True
    assert len(result["recovery_results"]) == 1
    assert result["recovery_results"][0]["status"] == "tracked_and_published"
    assert captured["citation_text"] == "The filing relies on ORSS 801.545 as authority."
    assert captured["corpus_key"] == "state_laws"
    assert captured["state_code"] == "OR"
    assert captured["publish_to_hf"] is True
    assert captured["hf_token"] == "hf-test-token"


def test_bluebook_citation_resolver_caches_hf_sources_per_corpus(monkeypatch):
    list_calls = []

    def fake_list_repo_files(*, repo_id, repo_type):
        assert repo_type == "dataset"
        list_calls.append(repo_id)
        return ["federal_register.parquet"]

    fake_hf_module = types.SimpleNamespace(
        list_repo_files=fake_list_repo_files,
        hf_hub_url=lambda *, repo_id, repo_type, filename: f"hf://{repo_id}/{filename}",
    )
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hf_module)

    resolver = BluebookCitationResolver(allow_hf_fallback=True)

    first = resolver._find_hf_sources(_CORPUS_CONFIGS["federal_register"], state_code=None)
    second = resolver._find_hf_sources(_CORPUS_CONFIGS["federal_register"], state_code=None)

    assert first == ["hf://justicedao/ipfs_federal_register/federal_register.parquet"]
    assert second == first
    assert list_calls == ["justicedao/ipfs_federal_register"]


def test_bluebook_citation_resolver_filters_cid_index_sidecars_from_overrides(tmp_path):
    primary_path = tmp_path / "uscode.parquet"
    cid_index_path = tmp_path / "cid_index.parquet"
    for path in (primary_path, cid_index_path):
        pq.write_table(pa.Table.from_pylist([{"title": "42", "section": "1983"}]), path)

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={"us_code": [str(cid_index_path), str(primary_path)]},
    )

    sources = list(resolver._iter_corpus_sources("us_code", state_code=None))

    assert sources == [str(primary_path)]


def test_bluebook_citation_resolver_uses_caselaw_hf_alias_when_primary_repo_has_no_parquet(monkeypatch):
    listed_repo_ids = []

    def fake_list_repo_files(*, repo_id, repo_type):
        assert repo_type == "dataset"
        listed_repo_ids.append(repo_id)
        if repo_id == "justicedao/ipfs_caselaw_access_project":
            return ["embeddings/readme.md", "embeddings/index.faiss"]
        if repo_id == "justicedao/dedup_ipfs_caselaw_access_project":
            return [
                "repaired_parquet_batch_20260228/cases.parquet",
                "repaired_parquet_batch_20260228/metadata.parquet",
            ]
        raise AssertionError(f"unexpected repo id {repo_id}")

    fake_hf_module = types.SimpleNamespace(
        list_repo_files=fake_list_repo_files,
        hf_hub_url=lambda *, repo_id, repo_type, filename: f"hf://{repo_id}/{filename}",
    )
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hf_module)
    monkeypatch.setattr(linker_module, "_dataset_server_parquet_records", lambda dataset_id: [])

    resolver = BluebookCitationResolver(allow_hf_fallback=True)

    sources = resolver._find_hf_sources(_CORPUS_CONFIGS["caselaw_access_project"], state_code=None)

    assert listed_repo_ids == [
        "justicedao/ipfs_caselaw_access_project",
        "justicedao/dedup_ipfs_caselaw_access_project",
    ]
    assert sources == [
        "hf://justicedao/dedup_ipfs_caselaw_access_project/repaired_parquet_batch_20260228/cases.parquet",
        "hf://justicedao/dedup_ipfs_caselaw_access_project/repaired_parquet_batch_20260228/metadata.parquet",
    ]


def test_bluebook_citation_resolver_filters_embeddings_directory_parquet_from_hf_sources(monkeypatch):
    def fake_list_repo_files(*, repo_id, repo_type):
        assert repo_type == "dataset"
        assert repo_id == "justicedao/ipfs_caselaw_access_project"
        return [
            "embeddings/ipfs_TeraflopAI___Caselaw_Access_Project.parquet",
            "cases/cap_cases.parquet",
        ]

    fake_hf_module = types.SimpleNamespace(
        list_repo_files=fake_list_repo_files,
        hf_hub_url=lambda *, repo_id, repo_type, filename: f"hf://{repo_id}/{filename}",
    )
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hf_module)

    resolver = BluebookCitationResolver(allow_hf_fallback=True)

    sources = resolver._find_hf_sources(_CORPUS_CONFIGS["caselaw_access_project"], state_code=None)

    assert sources == [
        "hf://justicedao/ipfs_caselaw_access_project/cases/cap_cases.parquet",
    ]


def test_bluebook_citation_resolver_prefers_repaired_caselaw_shards_over_deduplicated_monolith(monkeypatch):
    def fake_list_repo_files(*, repo_id, repo_type):
        assert repo_type == "dataset"
        assert repo_id == "justicedao/ipfs_caselaw_access_project"
        return [
            "deduplicated_ipfs_TeraflopAI___Caselaw_Access_Project.parquet",
            "repaired_parquet_batch_20260228/part-1.parquet",
            "repaired_parquet_batch_20260228/part-0.parquet",
        ]

    fake_hf_module = types.SimpleNamespace(
        list_repo_files=fake_list_repo_files,
        hf_hub_url=lambda *, repo_id, repo_type, filename: f"hf://{repo_id}/{filename}",
    )
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hf_module)

    resolver = BluebookCitationResolver(allow_hf_fallback=True)

    sources = resolver._find_hf_sources(_CORPUS_CONFIGS["caselaw_access_project"], state_code=None)

    assert sources[:3] == [
        "hf://justicedao/ipfs_caselaw_access_project/repaired_parquet_batch_20260228/part-0.parquet",
        "hf://justicedao/ipfs_caselaw_access_project/repaired_parquet_batch_20260228/part-1.parquet",
        "hf://justicedao/ipfs_caselaw_access_project/deduplicated_ipfs_TeraflopAI___Caselaw_Access_Project.parquet",
    ]


def test_bluebook_citation_resolver_uses_dataset_server_parquet_when_repo_tree_only_has_embeddings(monkeypatch):
    def fake_list_repo_files(*, repo_id, repo_type):
        assert repo_type == "dataset"
        assert repo_id == "justicedao/ipfs_caselaw_access_project"
        return [
            "embeddings/ipfs_TeraflopAI___Caselaw_Access_Project.parquet",
            "embeddings/sparse_chunks.parquet",
        ]

    fake_hf_module = types.SimpleNamespace(
        list_repo_files=fake_list_repo_files,
        hf_hub_url=lambda *, repo_id, repo_type, filename: f"hf://{repo_id}/{filename}",
    )
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hf_module)
    monkeypatch.setattr(
        linker_module,
        "_dataset_server_parquet_records",
        lambda dataset_id: [
            {
                "dataset": dataset_id,
                "config": "default",
                "split": "train",
                "filename": "0001.parquet",
                "url": f"https://example.test/{dataset_id}/0001.parquet",
            },
            {
                "dataset": dataset_id,
                "config": "default",
                "split": "train",
                "filename": "0000.parquet",
                "url": f"https://example.test/{dataset_id}/0000.parquet",
            },
        ],
    )

    resolver = BluebookCitationResolver(allow_hf_fallback=True)

    sources = resolver._find_hf_sources(_CORPUS_CONFIGS["caselaw_access_project"], state_code=None)

    assert sources == [
        "https://example.test/justicedao/ipfs_caselaw_access_project/0000.parquet",
        "https://example.test/justicedao/ipfs_caselaw_access_project/0001.parquet",
    ]


def test_bluebook_citation_resolver_ignores_embeddings_sidecars_in_override_sources(tmp_path):
    state_laws_path = tmp_path / "STATE-MN.parquet"
    embeddings_path = tmp_path / "STATE-MN_embeddings.parquet"
    metadata_path = tmp_path / "STATE-MN_metadata.parquet"

    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "state_code": "MN",
                    "official_cite": "Minn. Stat. § 518.17",
                    "section_name": "Best interests of the child",
                    "ipfs_cid": "bafymn51817",
                }
            ]
        ),
        state_laws_path,
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "ipfs_cid": "bafymn51817",
                    "semantic_text": "Minn. Stat. § 518.17 best interests of the child custody factors",
                }
            ]
        ),
        embeddings_path,
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "ipfs_cid": "bafymn51817",
                    "source_url": "https://example.test/metadata",
                }
            ]
        ),
        metadata_path,
    )

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={
            "state_laws": [str(state_laws_path), str(embeddings_path), str(metadata_path), str(tmp_path / "index.faiss")],
        },
    )

    sources = resolver._iter_corpus_sources("state_laws", state_code="MN")

    assert sources == [str(state_laws_path)]


def test_corpus_configs_include_france_spain_and_germany_laws_scaffolds():
    france = _CORPUS_CONFIGS["france_laws"]
    spain = _CORPUS_CONFIGS["spain_laws"]
    config = _CORPUS_CONFIGS["germany_laws"]

    assert france.dataset_id == "justicedao/ipfs_france_laws"
    assert "france_laws.parquet" in france.preferred_parquet_names
    assert "parquet/laws/" in france.preferred_path_substrings
    assert spain.dataset_id == "justicedao/ipfs_spain_laws"
    assert "spain_laws.parquet" in spain.preferred_parquet_names
    assert "parquet/laws/" in spain.preferred_path_substrings
    assert config.dataset_id == "justicedao/ipfs_germany_laws"
    assert "germany_laws.parquet" in config.preferred_parquet_names
    assert "parquet/laws/" in config.preferred_path_substrings


def test_bluebook_citation_resolver_randomized_supported_citation_coverage(tmp_path):
    resolver, cases = _build_fuzz_resolver(tmp_path)
    random_gen = random.Random(20260411)
    trial_count = 250
    matched_count = 0
    failures = []

    for _ in range(trial_count):
        case = random_gen.choice(cases)
        citation_text = random_gen.choice(case["variants"])
        text = _wrap_citation_text(citation_text, random_gen)
        links = resolve_bluebook_citations_in_text(text, resolver=resolver)

        success = False
        if len(links) == 1:
            link = links[0]
            success = (
                link.matched is True
                and link.corpus_key == case["corpus_key"]
                and link.citation_type == case["citation_type"]
                and (
                    case["expected_state"] is None
                    or str(link.metadata.get("state_code") or "") == case["expected_state"]
                )
            )
        if success:
            matched_count += 1
        elif len(failures) < 12:
            failures.append(
                {
                    "citation_text": citation_text,
                    "text": text,
                    "links": [
                        {
                            "citation_type": link.citation_type,
                            "matched": link.matched,
                            "corpus_key": link.corpus_key,
                            "state_code": link.metadata.get("state_code"),
                        }
                        for link in links
                    ],
                }
            )

    coverage = matched_count / trial_count
    assert coverage >= 0.95, failures


def test_bluebook_citation_resolver_randomized_specific_source_retrieval_contract(tmp_path):
    resolver, cases = _build_fuzz_resolver(tmp_path)
    random_gen = random.Random(20260413)
    trial_count = 180
    exact_retrieval_count = 0
    failures = []

    for _ in range(trial_count):
        case = random_gen.choice(cases)
        citation_text = random_gen.choice(case["variants"])
        text = _wrap_citation_text(citation_text, random_gen)
        links = resolve_bluebook_citations_in_text(text, resolver=resolver)

        success = False
        if len(links) == 1:
            link = links[0]
            success = (
                link.matched is True
                and link.corpus_key == case["corpus_key"]
                and link.citation_type == case["citation_type"]
                and link.source_cid == case["expected_source_cid"]
                and link.source_title == case["expected_source_title"]
                and (
                    case["expected_state"] is None
                    or str(link.metadata.get("state_code") or "") == case["expected_state"]
                )
            )

        if success:
            exact_retrieval_count += 1
        elif len(failures) < 12:
            failures.append(
                {
                    "citation_text": citation_text,
                    "text": text,
                    "expected": {
                        "corpus_key": case["corpus_key"],
                        "citation_type": case["citation_type"],
                        "state_code": case["expected_state"],
                        "source_cid": case["expected_source_cid"],
                        "source_title": case["expected_source_title"],
                    },
                    "links": [
                        {
                            "citation_type": link.citation_type,
                            "matched": link.matched,
                            "corpus_key": link.corpus_key,
                            "state_code": link.metadata.get("state_code"),
                            "source_cid": link.source_cid,
                            "source_title": link.source_title,
                        }
                        for link in links
                    ],
                }
            )

    coverage = exact_retrieval_count / trial_count
    assert coverage >= 0.95, failures


def test_bluebook_citation_resolver_randomized_multi_citation_coverage(tmp_path):
    resolver, cases = _build_fuzz_resolver(tmp_path)
    random_gen = random.Random(20260412)
    trial_count = 150
    exact_match_count = 0
    failures = []

    for _ in range(trial_count):
        selected_cases = random_gen.sample(cases, k=random_gen.randint(2, 4))
        text, rendered = _render_multi_citation_text(selected_cases, random_gen)
        links = resolve_bluebook_citations_in_text(text, resolver=resolver)

        expected = sorted(
            (
                item["expected_type"],
                item["expected_corpus"],
                item["expected_state"] or "",
            )
            for item in rendered
        )
        actual = sorted(
            (
                link.citation_type,
                link.corpus_key or "",
                str(link.metadata.get("state_code") or ""),
            )
            for link in links
            if link.matched
        )

        if actual == expected and len(links) == len(rendered):
            exact_match_count += 1
        elif len(failures) < 10:
            failures.append(
                {
                    "text": text,
                    "expected": expected,
                    "actual": actual,
                    "raw_links": [
                        {
                            "citation_text": link.citation_text,
                            "citation_type": link.citation_type,
                            "matched": link.matched,
                            "corpus_key": link.corpus_key,
                            "state_code": link.metadata.get("state_code"),
                        }
                        for link in links
                    ],
                }
            )

    coverage = exact_match_count / trial_count
    assert coverage >= 0.9, failures


def test_bluebook_citation_resolver_adversarial_negative_strings_do_not_match(tmp_path):
    resolver, _ = _build_fuzz_resolver(tmp_path)
    failures = []

    for text in _build_negative_fuzz_cases():
        links = resolve_bluebook_citations_in_text(text, resolver=resolver)
        if links and len(failures) < 10:
            failures.append(
                {
                    "text": text,
                    "links": [
                        {
                            "citation_text": link.citation_text,
                            "citation_type": link.citation_type,
                            "matched": link.matched,
                            "corpus_key": link.corpus_key,
                        }
                        for link in links
                    ],
                }
            )

    assert not failures, failures


def test_bluebook_citation_resolution_audit_reports_document_level_coverage(tmp_path):
    resolver, _ = _build_fuzz_resolver(tmp_path)

    report = audit_bluebook_citation_resolution_for_documents(
        [
            {
                "document_id": "doc_1",
                "title": "Motion",
                "text": "The motion relies on 42 U.S.C. § 1983 and 90 FR 12345.",
            },
            {
                "document_id": "doc_2",
                "title": "Memorandum",
                "text": "See Minn. Stat. § 518.17 and Or. Court Rules § 5.010.",
            },
            {
                "document_id": "doc_3",
                "title": "Supplement",
                "text": "The brief cites Minn. Stat. § 999.999 and 18 U.S.C. § 2251(a).",
            },
        ],
        resolver=resolver,
    )

    assert report["document_count"] == 3
    assert report["citation_count"] == 6
    assert report["matched_citation_count"] == 5
    assert report["unmatched_citation_count"] == 1
    assert report["fully_resolved_document_count"] == 2
    assert report["documents_with_citations"] == 3

    by_id = {item["document_id"]: item for item in report["documents"]}
    assert by_id["doc_1"]["all_citations_resolved"] is True
    assert by_id["doc_2"]["all_citations_resolved"] is True
    assert by_id["doc_3"]["all_citations_resolved"] is False
    assert by_id["doc_3"]["unmatched_citation_count"] == 1
    unresolved = report["unresolved_documents"][0]["unmatched_citations"][0]
    assert unresolved["citation_text"] == "Minn. Stat. § 999.999"
    assert unresolved["metadata"]["source_row_present"] is False
    assert unresolved["metadata"]["recovery_supported"] is True


@pytest.mark.skipif(not HYPOTHESIS_AVAILABLE, reason="hypothesis not installed")
@given(
    payload=st.binary(min_size=1, max_size=4096),
    chunk_sizes=st.lists(st.integers(min_value=1, max_value=257), min_size=1, max_size=32),
)
@settings(max_examples=40)
def test_bluebook_citation_resolver_materialize_remote_parquet_preserves_downloaded_bytes(
    payload,
    chunk_sizes,
):
    resolver = BluebookCitationResolver(allow_hf_fallback=True)
    source_ref = f"https://example.test/bluebook/{uuid.uuid4().hex}.parquet"
    request_calls = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=1024 * 1024):
            del chunk_size
            offset = 0
            size_index = 0
            while offset < len(payload):
                step = chunk_sizes[size_index % len(chunk_sizes)]
                size_index += 1
                next_offset = min(len(payload), offset + step)
                yield payload[offset:next_offset]
                offset = next_offset

    def fake_get(url, stream=True, timeout=120):
        request_calls.append((url, stream, timeout))
        assert stream is True
        assert timeout == 120
        return _Response()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("requests.get", fake_get)

        first_path = resolver._materialize_remote_parquet(source_ref)
        assert first_path is not None
        assert Path(first_path).read_bytes() == payload
        assert request_calls == [(source_ref, True, 120)]

        second_path = resolver._materialize_remote_parquet(source_ref)
        assert second_path == first_path
        assert Path(second_path).read_bytes() == payload
        assert request_calls == [(source_ref, True, 120)]


@pytest.mark.skipif(not HYPOTHESIS_AVAILABLE, reason="hypothesis not installed")
@given(
    names=st.lists(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("Ll", "Lu", "Nd"),
                whitelist_characters=("/._-"),
            ),
            min_size=1,
            max_size=48,
        ),
        min_size=1,
        max_size=16,
    )
)
@settings(max_examples=50)
def test_bluebook_citation_resolver_iter_corpus_sources_filters_only_direct_sources(names):
    normalized_names = []
    for name in names:
        candidate = name.strip().strip("/")
        if not candidate:
            continue
        if not candidate.endswith((".parquet", ".faiss", ".index")):
            candidate = f"{candidate}.parquet"
        normalized_names.append(candidate)

    if not normalized_names:
        normalized_names = ["uscode.parquet"]

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={"us_code": normalized_names},
    )

    expected = [
        item
        for item in [str(path) for path in normalized_names]
        if linker_module._is_direct_citation_source(item)
    ]

    assert resolver._iter_corpus_sources("us_code", state_code=None) == expected
