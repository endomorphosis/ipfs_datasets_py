from __future__ import annotations

import random

import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_scrapers import (
    BluebookCitationResolver,
    CitationExtractor,
    resolve_bluebook_citations_in_text,
)


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

    resolver = BluebookCitationResolver(
        allow_hf_fallback=False,
        parquet_file_overrides={
            "us_code": [str(uscode_path)],
            "federal_register": [str(federal_register_path)],
            "state_laws": [str(state_law_path)],
            "state_admin_rules": [str(state_admin_rules_path)],
            "state_court_rules": [str(state_court_rules_path)],
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
        },
        {
            "corpus_key": "federal_register",
            "citation_type": "federal_register",
            "variants": [
                "90 FR 12345",
                "90 Fed. Reg. 12345",
            ],
            "expected_state": None,
        },
        {
            "corpus_key": "federal_register",
            "citation_type": "federal_register",
            "variants": [
                "88 FR 54321",
                "88 Fed. Reg. 54321",
            ],
            "expected_state": None,
        },
        {
            "corpus_key": "state_laws",
            "citation_type": "state_statute",
            "variants": [
                "Minn. Stat. § 518.17",
                "Minn. Stat. 518.17",
            ],
            "expected_state": "MN",
        },
        {
            "corpus_key": "state_laws",
            "citation_type": "state_statute",
            "variants": [
                "Or. Rev. Stat. § 90.155",
                "Or. Rev. Stat. 90.155",
            ],
            "expected_state": "OR",
        },
        {
            "corpus_key": "state_laws",
            "citation_type": "state_statute",
            "variants": [
                "N.Y. Penal Code § 125.25",
                "N.Y. Penal Code 125.25",
            ],
            "expected_state": "NY",
        },
        {
            "corpus_key": "state_admin_rules",
            "citation_type": "state_statute",
            "variants": [
                "Minn. Admin. Code § 1400.5010",
                "Minn. Admin. Code 1400.5010",
            ],
            "expected_state": "MN",
        },
        {
            "corpus_key": "state_court_rules",
            "citation_type": "state_statute",
            "variants": [
                "Or. Court Rules § 5.010",
                "Or. Court Rules 5.010",
            ],
            "expected_state": "OR",
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
