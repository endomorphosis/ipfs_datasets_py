from __future__ import annotations

import anyio

from ipfs_datasets_py.processors.legal_scrapers import (
    build_default_eu_lookup_handlers,
    build_eu_legal_reasoning_bundle,
    build_eu_legal_citation_lookup_plan,
    build_eu_legal_resolution_bundle,
    eu_legal_citation_lookup_plan_to_dict,
    execute_eu_legal_citation_lookup_plan,
    eu_legal_citation_lookup_result_to_dict,
    eu_legal_reasoning_bundle_to_dict,
    eu_legal_resolution_bundle_to_dict,
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


def test_build_eu_legal_citation_lookup_plan_includes_member_state_handlers():
    text = "Artikel 6:162 BW, Art. 1 GG, article 1240 du code civil, articulo 1902 del Codigo Civil, and CELEX 32016R0679."
    plan = build_eu_legal_citation_lookup_plan(text, language="nl")
    payload = eu_legal_citation_lookup_plan_to_dict(plan)

    handler_keys = {action["handler_key"] for action in payload["actions"]}
    dataset_ids = {action["dataset_id"] for action in payload["actions"]}

    assert "netherlands_laws" in handler_keys
    assert "germany_laws" in handler_keys
    assert "france_laws" in handler_keys
    assert "spain_laws" in handler_keys
    assert "eurlex_registry" in handler_keys
    assert "netherlands_laws" in dataset_ids
    assert "germany_laws" in dataset_ids
    assert "france_laws" in dataset_ids
    assert "spain_laws" in dataset_ids
    assert "eurlex" in dataset_ids


def test_execute_eu_legal_citation_lookup_plan_uses_registered_handlers():
    text = "ECLI:NL:HR:2024:123 and BWBR0001854."
    plan = build_eu_legal_citation_lookup_plan(text, language="nl")

    def handler(action):
        return {"hits": [{"query": action.query_text, "dataset": action.dataset_id}]}

    async def _run():
        return await execute_eu_legal_citation_lookup_plan(
            plan,
            lookup_handlers={
                "netherlands_laws": handler,
                "ecli_registry": handler,
            },
        )

    result = anyio.run(_run)
    payload = eu_legal_citation_lookup_result_to_dict(result)

    assert payload["executed_actions"]
    assert all(action["executed"] is True for action in payload["executed_actions"])
    assert any(hit["dataset"] == "netherlands_laws" for action in payload["executed_actions"] for hit in action["results"]["hits"])


def test_default_lookup_handlers_call_netherlands_backend(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api

    async def _fake_search(parameters, *, tool_version="1.0.0"):
        return {
            "results": [{"id": "nl_doc", "query": parameters.get("query_text")}],
            "query": parameters.get("query_text"),
        }

    monkeypatch.setattr(legal_dataset_api, "search_netherlands_law_corpus_from_parameters", _fake_search)

    plan = build_eu_legal_citation_lookup_plan("BWBR0001854", language="nl")
    handlers = build_default_eu_lookup_handlers()

    async def _run():
        return await execute_eu_legal_citation_lookup_plan(plan, lookup_handlers=handlers)

    result = anyio.run(_run)
    payload = eu_legal_citation_lookup_result_to_dict(result)

    assert payload["executed_actions"]
    assert any(
        action["dataset_id"] == "netherlands_laws"
        and action["results"]["results"][0]["id"] == "nl_doc"
        for action in payload["executed_actions"]
    )


def test_default_lookup_handlers_call_canonical_corpus_backend_for_france_germany_and_spain(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import justicedao_dataset_inventory

    def _fake_query_canonical_legal_corpus(dataset_id, *, query_text, **kwargs):
        return {
            "resolved": True,
            "dataset_id": dataset_id,
            "query_text": query_text,
            "results": [{"row": {"law_identifier": f"{dataset_id}:{query_text}"}}],
        }

    def _fake_canonical_corpus_query_result_to_dict(result):
        return result

    monkeypatch.setattr(
        justicedao_dataset_inventory,
        "query_canonical_legal_corpus",
        _fake_query_canonical_legal_corpus,
    )
    monkeypatch.setattr(
        justicedao_dataset_inventory,
        "canonical_corpus_query_result_to_dict",
        _fake_canonical_corpus_query_result_to_dict,
    )

    plan = build_eu_legal_citation_lookup_plan(
        "Art. 1 GG, article 1240 du code civil, and articulo 1902 del Codigo Civil.",
        language="en",
    )
    handlers = build_default_eu_lookup_handlers()

    async def _run():
        return await execute_eu_legal_citation_lookup_plan(plan, lookup_handlers=handlers)

    result = anyio.run(_run)
    payload = eu_legal_citation_lookup_result_to_dict(result)

    executed = {action["dataset_id"]: action for action in payload["executed_actions"]}
    assert executed["germany_laws"]["executed"] is True
    assert executed["france_laws"]["executed"] is True
    assert executed["spain_laws"]["executed"] is True
    assert executed["germany_laws"]["results"]["resolved"] is True
    assert executed["france_laws"]["results"]["resolved"] is True
    assert executed["spain_laws"]["results"]["resolved"] is True


def test_default_lookup_handlers_fetch_eurlex_metadata(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import eu_legal_citation_bridge

    def _fake_fetch(url, *, timeout=10.0):
        return {"resolved": True, "url": url, "status_code": 200, "title": "GDPR"}

    monkeypatch.setattr(eu_legal_citation_bridge, "_fetch_eurlex_metadata", _fake_fetch)

    plan = build_eu_legal_citation_lookup_plan("CELEX 32016R0679", language="en")
    handlers = build_default_eu_lookup_handlers()

    async def _run():
        return await execute_eu_legal_citation_lookup_plan(plan, lookup_handlers=handlers)

    result = anyio.run(_run)
    payload = eu_legal_citation_lookup_result_to_dict(result)

    assert any(
        action["handler_key"] == "eurlex_registry"
        and action["results"]["title"] == "GDPR"
        for action in payload["executed_actions"]
    )


def test_default_lookup_handlers_return_structured_ecli_metadata():
    plan = build_eu_legal_citation_lookup_plan("ECLI:NL:HR:2024:123", language="en")
    handlers = build_default_eu_lookup_handlers()

    async def _run():
        return await execute_eu_legal_citation_lookup_plan(plan, lookup_handlers=handlers)

    result = anyio.run(_run)
    payload = eu_legal_citation_lookup_result_to_dict(result)

    assert any(
        action["handler_key"] == "ecli_registry"
        and action["results"]["resolved"] is False
        and action["results"]["canonical_uri"].startswith("ecli:")
        for action in payload["executed_actions"]
    )


def test_build_eu_legal_resolution_bundle_executes_default_handlers(monkeypatch):
    from ipfs_datasets_py.processors.legal_scrapers import eu_legal_citation_bridge

    def _fake_fetch(url, *, timeout=10.0, label="http"):
        return {"resolved": True, "url": url, "status_code": 200, "title": "GDPR", "handler": label}

    monkeypatch.setattr(eu_legal_citation_bridge, "_fetch_url_metadata", _fake_fetch)
    monkeypatch.setattr(eu_legal_citation_bridge, "_fetch_eurlex_metadata", _fake_fetch)

    async def _run():
        return await build_eu_legal_resolution_bundle(
            "CELEX 32016R0679 and ECLI:NL:HR:2024:123",
            language="en",
            execute_lookup=True,
        )

    bundle = anyio.run(_run)
    payload = eu_legal_resolution_bundle_to_dict(bundle)

    assert payload["lookup_result"] is not None
    assert any(
        action["handler_key"] == "eurlex_registry" and action["results"]["resolved"] is True
        for action in payload["lookup_result"]["executed_actions"]
    )
