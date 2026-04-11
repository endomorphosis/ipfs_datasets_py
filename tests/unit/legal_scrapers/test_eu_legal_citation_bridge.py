from __future__ import annotations

from ipfs_datasets_py.processors.legal_scrapers import (
    build_eu_legal_reasoning_bundle,
    eu_legal_reasoning_bundle_to_dict,
    extract_eu_legal_citations,
    get_eu_jurisdiction_profiles,
)


def test_extract_eu_legal_citations_recognizes_official_eu_and_dutch_identifiers():
    text = (
        "See CELEX 32016R0679, ECLI:NL:HR:2024:123, "
        "https://eur-lex.europa.eu/eli/reg/2016/679/oj, BWBR0001854, and Artikel 6:162 BW."
    )

    citations = extract_eu_legal_citations(text, language="nl")
    schemes = {citation.scheme for citation in citations}
    uris = {citation.canonical_uri for citation in citations}

    assert {"CELEX", "ECLI", "ELI", "BWB", "NL_BW_ARTICLE"}.issubset(schemes)
    assert "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679" in uris
    assert "https://wetten.overheid.nl/BWBR0001854/" in uris


def test_build_eu_legal_reasoning_bundle_emits_multilingual_logic_and_graph_artifacts():
    text = (
        "Volgens CELEX 32016R0679 moet de lidstaat persoonsgegevens beschermen. "
        "The authority may inspect records. "
        "ECLI:NL:HR:2024:123 and BWBR0001854 remain authoritative."
    )

    bundle = build_eu_legal_reasoning_bundle(text, language="nl")
    payload = eu_legal_reasoning_bundle_to_dict(bundle)

    assert payload["citations"]
    assert payload["multilingual_normalization"]["lidstaat"] == "member_state"
    assert payload["multilingual_normalization"]["moet"] == "required"

    assert any("canonical_uri" in fact for fact in payload["frame_logic_facts"])
    assert any(formula.startswith("O(") for formula in payload["temporal_deontic_fol"])
    assert any(assertion.startswith("Initiates(") for assertion in payload["deontic_cognitive_event_calculus"])

    assert payload["deontic_graph"]["summary"]["total_rules"] >= 2
    assert payload["knowledge_graph"]["summary"]["citation_count"] >= 2
    assert any(rule["modality"] == "obligation" for rule in payload["deontic_graph"]["rules"])
    assert any(rule["modality"] == "permission" for rule in payload["deontic_graph"]["rules"])


def test_eu_member_state_profiles_cover_netherlands_germany_france_and_spain():
    profiles = get_eu_jurisdiction_profiles()

    assert {"EU", "NL", "DE", "FR", "ES"}.issubset(profiles)
    assert "BWB" in profiles["NL"]["identifier_schemes"]
    assert "DE_GG_ARTICLE" in profiles["DE"]["identifier_schemes"]
    assert "FR_CC_ARTICLE" in profiles["FR"]["identifier_schemes"]
    assert "ES_CC_ARTICLE" in profiles["ES"]["identifier_schemes"]


def test_extract_eu_legal_citations_recognizes_member_state_specific_article_patterns():
    text = (
        "Artikel 6:162 BW, Art. 1 GG, article 1240 du code civil, "
        "artículo 1902 del Código Civil, and ECLI:DE:BVerfG:2020:rk20200101."
    )

    citations = extract_eu_legal_citations(text, language="en")
    schemes = {citation.scheme for citation in citations}
    member_states = {citation.member_state for citation in citations if citation.member_state}

    assert {"NL_BW_ARTICLE", "DE_GG_ARTICLE", "FR_CC_ARTICLE", "ES_CC_ARTICLE", "ECLI"}.issubset(schemes)
    assert {"NL", "DE", "FR", "ES"}.issubset(member_states)


def test_build_eu_legal_reasoning_bundle_surfaces_active_jurisdiction_profiles_and_vocab():
    text = (
        "Art. 1 GG muss der Mitgliedstaat Rechte schützen. "
        "Article 1240 du code civil peut engager la responsabilité. "
        "Artículo 1902 del Código Civil puede imponer responsabilidad."
    )

    bundle = build_eu_legal_reasoning_bundle(text, language="en")
    payload = eu_legal_reasoning_bundle_to_dict(bundle)
    active_codes = {profile["code"] for profile in payload["jurisdiction_profiles"]}

    assert {"EU", "DE", "FR", "ES"}.issubset(active_codes)
    assert payload["multilingual_normalization"]["mitgliedstaat"] == "member_state"
    assert payload["multilingual_normalization"]["muss"] == "required"
    assert payload["multilingual_normalization"]["peut"] == "allowed"
    assert payload["multilingual_normalization"]["puede"] == "allowed"
