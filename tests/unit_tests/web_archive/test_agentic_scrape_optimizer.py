#!/usr/bin/env python3

from ipfs_datasets_py.processors.web_archiving.agentic_scrape_optimizer import (
    AgenticExtractionConfig,
    AgenticScrapeOptimizer,
)


def test_agentic_optimizer_cleans_boilerplate() -> None:
    optimizer = AgenticScrapeOptimizer()
    text = """
    Privacy Policy
    Sign in
    Indiana Code Title 35 Criminal Law
    Section 35-42-1 homicide.
    """

    cleaned = optimizer.clean_text(text)

    assert "Privacy Policy" not in cleaned
    assert "Sign in" not in cleaned
    assert "Indiana Code" in cleaned


def test_agentic_optimizer_extracts_entities_with_optimizer_patterns() -> None:
    optimizer = AgenticScrapeOptimizer(
        AgenticExtractionConfig(domain="legal", allowed_entity_types=["LegalReference", "Date"])
    )
    parsed = optimizer.transform(
        url="https://example.com/law",
        text="Article 3 and Section 15 were amended on 12/15/2024.",
    )

    assert parsed.cleaned_text
    assert len(parsed.entities) >= 1
    assert any(ent.get("type") in {"LegalReference", "Date"} for ent in parsed.entities)


def test_agentic_optimizer_pdf_parse_failure_is_safe() -> None:
    optimizer = AgenticScrapeOptimizer()

    text = optimizer.extract_pdf_text(b"not-a-real-pdf")

    assert text == ""


def test_agentic_optimizer_rank_links_prefers_target_and_pdf() -> None:
    optimizer = AgenticScrapeOptimizer()
    links = [
        {"url": "https://example.com/about", "text": "About"},
        {"url": "https://example.com/statutes/title-35.pdf", "text": "Title 35 PDF"},
        {"url": "https://example.com/contact", "text": "Contact"},
    ]

    ranked = optimizer.rank_links(links, target_terms=["title", "statutes"])

    assert ranked[0]["url"].endswith("title-35.pdf")


def test_agentic_optimizer_extracts_structured_fields() -> None:
    optimizer = AgenticScrapeOptimizer(AgenticExtractionConfig(domain="legal"))
    parsed = optimizer.transform(
        url="https://example.com/uscode",
        text=(
            "TITLE 35 CRIMES\n"
            "Section 35-42-1 Homicide\n"
            "18 U.S.C. 924 applies here.\n"
            "Effective date: 12/15/2024\n"
            "Civil penalty is $5,000.00\n"
        ),
    )

    sf = parsed.structured_fields
    assert "TITLE 35 CRIMES" in sf["section_headers"]
    assert "12/15/2024" in sf["dates"]
    assert any("18 U.S.C." in c for c in sf["legal_citations"])
    assert any("35-42-1" in s for s in sf["statute_identifiers"])
    assert "$5,000.00" in sf["monetary_amounts"]
