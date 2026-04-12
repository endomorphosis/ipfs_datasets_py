from __future__ import annotations

import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_data.rich_docket_enrichment import RichDocumentAnalysis
from ipfs_datasets_py.processors.legal_scrapers.justicedao_dataset_inventory import (
    LegalCitationQueryStrategy,
    LegalCitationDatasetQueryPlan,
    JusticeDAORebuildRecommendation,
    JusticeDAORebuildTarget,
    build_justicedao_rebuild_plan,
    canonical_corpus_artifact_build_result_to_dict,
    CitationQueryPlan,
    canonical_corpus_index_build_result_to_dict,
    canonical_corpus_query_result_to_dict,
    DatasetConfigProfile,
    DatasetProfile,
    legal_citation_dataset_execution_result_to_dict,
    legal_citation_dataset_query_plan_to_dict,
    build_canonical_corpus_artifacts,
    build_canonical_corpus_semantic_index,
    _select_rows_for_llm_knowledge_graph,
    build_eu_country_corpus_onboarding_plan,
    build_justicedao_legal_citation_query_plan,
    derive_justicedao_legal_citation_strategies,
    execute_justicedao_legal_citation_query_plan,
    filter_dataset_profiles,
    justicedao_library_rebuild_result_to_dict,
    justicedao_rebuild_plan_to_dict,
    query_canonical_legal_corpus,
    rebuild_justicedao_dataset_library,
    render_justicedao_legal_citation_query_plan_markdown,
    render_dataset_profiles_markdown,
    render_justicedao_rebuild_plan_markdown,
    summarize_dataset_profile_coverage_by_branch,
    summarize_dataset_profiles_by_branch,
    summarize_dataset_profiles_by_country,
)
from ipfs_datasets_py.processors.retrieval import hashed_term_projection


def _profiles() -> list[DatasetProfile]:
    return [
        DatasetProfile(
            dataset_id="justicedao/american_municipal_law",
            parquet_files=[
                "american_law/data/1008538_citation.parquet",
                "american_law/data/1008538_html.parquet",
                "american_law/data/1008538_embeddings.parquet",
            ],
            top_level_paths=["american_law"],
            configs=[],
        ),
        DatasetProfile(
            dataset_id="justicedao/ipfs_state_laws",
            parquet_files=["state_laws_parquet_cid/state_laws_all_states.parquet"],
            top_level_paths=["OR", "state_laws_parquet_cid"],
            configs=[
                DatasetConfigProfile(
                    config="default",
                    split="train",
                    features=["ipfs_cid", "state_code", "source_id", "identifier", "name", "text", "jsonld"],
                )
            ],
        ),
        DatasetProfile(
            dataset_id="justicedao/ipfs_state_admin_rules",
            parquet_files=["US_ADMINISTRATIVE_RULES/parsed/parquet/state_admin_rules_cid/state_admin_rules_all_states.parquet"],
            top_level_paths=["OR", "US_ADMINISTRATIVE_RULES"],
            configs=[
                DatasetConfigProfile(
                    config="default",
                    split="train",
                    features=["ipfs_cid", "state_code", "source_id", "identifier", "name", "text", "jsonld"],
                )
            ],
        ),
        DatasetProfile(
            dataset_id="justicedao/ipfs_court_rules",
            parquet_files=["state_court_rules_parquet_cid/state_court_rules_all_states.parquet"],
            top_level_paths=["state_court_rules_parquet_cid"],
            configs=[
                DatasetConfigProfile(
                    config="default",
                    split="train",
                    features=["ipfs_cid", "state_code", "source_id", "identifier", "name", "text", "jsonld"],
                )
            ],
        ),
        DatasetProfile(
            dataset_id="justicedao/ipfs_uscode",
            parquet_files=["uscode_parquet/laws.parquet", "uscode_parquet/cid_index.parquet"],
            top_level_paths=["uscode_parquet"],
            configs=[
                DatasetConfigProfile(
                    config="default",
                    split="train",
                    features=["ipfs_cid", "title_number", "section_number"],
                )
            ],
        ),
        DatasetProfile(
            dataset_id="justicedao/ipfs_federal_register",
            parquet_files=["federal_register.parquet"],
            top_level_paths=["federal_register.parquet"],
            configs=[
                DatasetConfigProfile(
                    config="default",
                    split="train",
                    features=["cid", "source_id", "identifier", "name", "source_url", "jsonld"],
                )
            ],
        ),
        DatasetProfile(
            dataset_id="justicedao/caselaw_access_project",
            parquet_files=["cap_cases.parquet"],
            top_level_paths=["cap_cases"],
            configs=[
                DatasetConfigProfile(
                    config="default",
                    split="train",
                    features=["id", "citation", "reporter", "volume", "page", "name"],
                )
            ],
        ),
        DatasetProfile(
            dataset_id="justicedao/ipfs_netherlands_laws",
            parquet_files=["parquet/laws/train-00000-of-00001.parquet"],
            top_level_paths=["parquet"],
            configs=[
                DatasetConfigProfile(
                    config="laws",
                    split="train",
                    features=["citation", "identifier", "law_identifier", "official_identifier", "text", "metadata"],
                )
            ],
        ),
        DatasetProfile(
            dataset_id="justicedao/ipfs_netherlands_laws_bm25_index",
            parquet_files=["parquet/documents/train-00000-of-00001.parquet"],
            top_level_paths=["parquet"],
            configs=[
                DatasetConfigProfile(
                    config="documents",
                    split="train",
                    features=["citation", "law_identifier", "article_identifier", "source_cid", "text_preview"],
                )
            ],
        ),
        DatasetProfile(
            dataset_id="justicedao/ipfs_netherlands_laws_knowledge_graph",
            parquet_files=["parquet/nodes/train-00000-of-00001.parquet"],
            top_level_paths=["parquet"],
            configs=[
                DatasetConfigProfile(
                    config="nodes",
                    split="train",
                    features=["law_identifier", "article_identifier", "jsonld_id", "label", "source_cid"],
                )
            ],
        ),
    ]


def _profiles_with_germany_family() -> list[DatasetProfile]:
    return [
        *_profiles(),
        DatasetProfile(
            dataset_id="justicedao/ipfs_germany_laws",
            parquet_files=["parquet/laws/train-00000-of-00001.parquet"],
            top_level_paths=["parquet"],
            configs=[
                DatasetConfigProfile(
                    config="laws",
                    split="train",
                    features=["citation", "identifier", "law_identifier", "official_identifier", "text", "metadata"],
                )
            ],
        ),
        DatasetProfile(
            dataset_id="justicedao/ipfs_germany_laws_bm25_index",
            parquet_files=["parquet/documents/train-00000-of-00001.parquet"],
            top_level_paths=["parquet"],
            configs=[
                DatasetConfigProfile(
                    config="documents",
                    split="train",
                    features=["citation", "law_identifier", "article_identifier", "source_cid", "text_preview"],
                )
            ],
        ),
        DatasetProfile(
            dataset_id="justicedao/ipfs_germany_laws_knowledge_graph",
            parquet_files=["parquet/nodes/train-00000-of-00001.parquet"],
            top_level_paths=["parquet"],
            configs=[
                DatasetConfigProfile(
                    config="nodes",
                    split="train",
                    features=["law_identifier", "article_identifier", "jsonld_id", "label", "source_cid"],
                )
            ],
        ),
    ]


def _profiles_with_france_family() -> list[DatasetProfile]:
    return [
        *_profiles(),
        DatasetProfile(
            dataset_id="justicedao/ipfs_france_laws",
            parquet_files=["parquet/laws/train-00000-of-00001.parquet"],
            top_level_paths=["parquet"],
            configs=[
                DatasetConfigProfile(
                    config="laws",
                    split="train",
                    features=["citation", "identifier", "law_identifier", "official_identifier", "text", "metadata"],
                )
            ],
        ),
        DatasetProfile(
            dataset_id="justicedao/ipfs_france_laws_bm25_index",
            parquet_files=["parquet/documents/train-00000-of-00001.parquet"],
            top_level_paths=["parquet"],
            configs=[
                DatasetConfigProfile(
                    config="documents",
                    split="train",
                    features=["citation", "law_identifier", "article_identifier", "source_cid", "text_preview"],
                )
            ],
        ),
        DatasetProfile(
            dataset_id="justicedao/ipfs_france_laws_knowledge_graph",
            parquet_files=["parquet/nodes/train-00000-of-00001.parquet"],
            top_level_paths=["parquet"],
            configs=[
                DatasetConfigProfile(
                    config="nodes",
                    split="train",
                    features=["law_identifier", "article_identifier", "jsonld_id", "label", "source_cid"],
                )
            ],
        ),
    ]


def _profiles_with_spain_family() -> list[DatasetProfile]:
    return [
        *_profiles(),
        DatasetProfile(
            dataset_id="justicedao/ipfs_spain_laws",
            parquet_files=["parquet/laws/train-00000-of-00001.parquet"],
            top_level_paths=["parquet"],
            configs=[
                DatasetConfigProfile(
                    config="laws",
                    split="train",
                    features=["citation", "identifier", "law_identifier", "official_identifier", "text", "metadata"],
                )
            ],
        ),
        DatasetProfile(
            dataset_id="justicedao/ipfs_spain_laws_bm25_index",
            parquet_files=["parquet/documents/train-00000-of-00001.parquet"],
            top_level_paths=["parquet"],
            configs=[
                DatasetConfigProfile(
                    config="documents",
                    split="train",
                    features=["citation", "law_identifier", "article_identifier", "source_cid", "text_preview"],
                )
            ],
        ),
        DatasetProfile(
            dataset_id="justicedao/ipfs_spain_laws_knowledge_graph",
            parquet_files=["parquet/nodes/train-00000-of-00001.parquet"],
            top_level_paths=["parquet"],
            configs=[
                DatasetConfigProfile(
                    config="nodes",
                    split="train",
                    features=["law_identifier", "article_identifier", "jsonld_id", "label", "source_cid"],
                )
            ],
        ),
    ]


def test_derive_justicedao_legal_citation_strategies_covers_municipal_and_uscode_paths():
    strategies = derive_justicedao_legal_citation_strategies(_profiles())

    municipal = strategies["justicedao/american_municipal_law"]
    assert isinstance(municipal, LegalCitationQueryStrategy)
    assert municipal.support_level == "direct"
    assert municipal.query_path == "precomputed_citation_table_then_cid_join"
    assert "bluebook_citation" in municipal.citation_lookup_fields
    assert municipal.join_fields == ["cid"]

    uscode = strategies["justicedao/ipfs_uscode"]
    assert uscode.support_level == "cid_join"
    assert uscode.query_path == "usc_title_section_to_cid_then_dereference_laws_parquet"
    assert uscode.canonical_corpus_key == "us_code"
    assert uscode.legal_branch == "us"
    assert "title_number" in uscode.citation_lookup_fields
    assert "section_number" in uscode.citation_lookup_fields

    netherlands = strategies["justicedao/ipfs_netherlands_laws"]
    assert netherlands.canonical_corpus_key == "netherlands_laws"
    assert netherlands.legal_branch == "eu"
    assert netherlands.country_codes == ["NL"]


def test_dataset_profiles_to_dict_include_legal_branch_metadata(tmp_path):
    payload = legal_citation_dataset_query_plan_to_dict(
        build_justicedao_legal_citation_query_plan("42 U.S.C. § 1983", profiles=_profiles())
    )
    assert payload["dataset_notes"]

    uscode_path = tmp_path / "uscode.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "ipfs_cid": "bafy1983",
                    "title_number": "42",
                    "section_number": "1983",
                    "identifier": "42 U.S.C. § 1983",
                    "law_name": "Civil action for deprivation of rights",
                    "text": "Every person who acts under color of state law...",
                }
            ]
        ),
        uscode_path,
    )

    profile_payload = canonical_corpus_query_result_to_dict(
        query_canonical_legal_corpus(
            "us_code",
            query_text="42 U.S.C. § 1983",
            parquet_file_overrides={"us_code": [str(uscode_path)]},
            allow_hf_fallback=False,
        )
    )
    assert profile_payload["legal_branch"] == "us"
    assert profile_payload["country_codes"] == ["US"]


def test_filter_dataset_profiles_can_select_eu_branch_and_country():
    eu_profiles = filter_dataset_profiles(_profiles(), legal_branch="eu")
    nl_profiles = filter_dataset_profiles(_profiles(), country_code="NL")
    us_profiles = filter_dataset_profiles(_profiles(), legal_branch="us")

    assert [profile.dataset_id for profile in eu_profiles] == [
        "justicedao/ipfs_netherlands_laws",
        "justicedao/ipfs_netherlands_laws_bm25_index",
        "justicedao/ipfs_netherlands_laws_knowledge_graph",
    ]
    assert [profile.dataset_id for profile in nl_profiles] == [profile.dataset_id for profile in eu_profiles]
    assert "justicedao/ipfs_uscode" in {profile.dataset_id for profile in us_profiles}


def test_summarize_dataset_profiles_by_branch_groups_us_and_eu_corpora():
    summary = summarize_dataset_profiles_by_branch(_profiles())

    assert summary["eu"]["dataset_count"] == 3
    assert summary["eu"]["country_codes"] == ["NL"]
    assert "justicedao/ipfs_netherlands_laws" in summary["eu"]["dataset_ids"]
    assert "justicedao/caselaw_access_project" in summary["us"]["dataset_ids"]
    assert "justicedao/american_municipal_law" in summary["us"]["dataset_ids"]
    assert summary["us"]["dataset_count"] >= 6
    assert "US" in summary["us"]["country_codes"]


def test_summarize_dataset_profile_coverage_by_branch_reports_missing_eu_country_support():
    summary = summarize_dataset_profile_coverage_by_branch(_profiles())

    assert summary["eu"]["covered_country_codes"] == ["NL"]
    assert summary["eu"]["missing_country_codes"] == ["DE", "ES", "FR"]
    assert summary["us"]["covered_country_codes"] == ["US"]
    assert summary["us"]["missing_country_codes"] == []


def test_build_eu_country_corpus_onboarding_plan_proposes_missing_supported_countries():
    plan = build_eu_country_corpus_onboarding_plan(_profiles())

    assert plan["NL"]["status"] == "covered"
    assert plan["NL"]["canonical_corpus_keys"] == ["netherlands_laws"]
    assert plan["DE"]["status"] == "registered"
    assert plan["DE"]["canonical_corpus_keys"] == ["germany_laws"]
    assert plan["DE"]["proposed_corpus_key"] is None
    assert plan["FR"]["status"] == "registered"
    assert plan["FR"]["canonical_corpus_keys"] == ["france_laws"]
    assert plan["FR"]["proposed_corpus_key"] is None
    assert plan["ES"]["status"] == "registered"
    assert plan["ES"]["canonical_corpus_keys"] == ["spain_laws"]
    assert plan["ES"]["proposed_corpus_key"] is None


def test_build_eu_country_corpus_onboarding_plan_marks_observed_proposed_dataset_as_in_progress():
    plan = build_eu_country_corpus_onboarding_plan(
        [
            *_profiles(),
            DatasetProfile(dataset_id="justicedao/ipfs_it_laws_bm25_index", legal_branch="eu", country_codes=["IT"]),
        ],
        expected_country_codes=["IT"],
    )

    assert plan["IT"]["status"] == "in_progress"
    assert plan["IT"]["existing_dataset_ids"] == ["justicedao/ipfs_it_laws_bm25_index"]
    assert plan["IT"]["proposed_corpus_key"] == "it_laws"


def test_render_dataset_profiles_markdown_includes_branch_summary():
    markdown = render_dataset_profiles_markdown(_profiles())

    assert "## Branch Summary" in markdown
    assert "## Country Summary" in markdown
    assert "## Coverage Summary" in markdown
    assert "## EU Country Onboarding" in markdown
    assert "EU: 3 datasets (NL)" in markdown
    assert "NL: 3 datasets (EU)" in markdown
    assert "EU: covered NL; missing DE, ES, FR" in markdown
    assert "DE: canonical registry includes germany_laws; awaiting observed datasets" in markdown
    assert "FR: canonical registry includes france_laws; awaiting observed datasets" in markdown
    assert "ES: canonical registry includes spain_laws; awaiting observed datasets" in markdown
    assert "US:" in markdown


def test_render_dataset_profiles_markdown_shows_registered_state_for_sidecar_only_canonical_eu_dataset():
    markdown = render_dataset_profiles_markdown(
        [
            DatasetProfile(dataset_id="justicedao/ipfs_spain_laws_bm25_index"),
        ]
    )

    assert "## EU Country Onboarding" in markdown
    assert "ES: canonical registry includes spain_laws; awaiting observed datasets" in markdown
    assert "Canonical corpus: spain_laws" in markdown


def test_build_justicedao_legal_citation_query_plan_routes_state_and_usc_citations():
    plan = build_justicedao_legal_citation_query_plan(
        "See Or. Rev. Stat. § 90.155 and 42 U.S.C. § 1983.",
        profiles=_profiles(),
    )

    assert len(plan.query_plans) == 2

    state_plan = next(item for item in plan.query_plans if item.citation_type == "state_statute")
    assert state_plan.candidate_datasets[0].dataset_id == "justicedao/ipfs_state_laws"
    assert state_plan.candidate_datasets[1].dataset_id == "justicedao/ipfs_state_admin_rules"

    usc_plan = next(item for item in plan.query_plans if item.citation_type == "usc")
    assert usc_plan.candidate_datasets[0].dataset_id == "justicedao/ipfs_uscode"
    assert usc_plan.normalized_citation == "42 U.S.C. § 1983"


def test_build_justicedao_legal_citation_query_plan_marks_sidecars_as_secondary():
    strategies = derive_justicedao_legal_citation_strategies(
        [
            *_profiles_with_france_family(),
            *_profiles_with_spain_family()[len(_profiles()):],
            *_profiles_with_germany_family()[len(_profiles()):],
        ]
    )
    assert strategies["justicedao/ipfs_netherlands_laws_bm25_index"].support_level == "sidecar"
    assert strategies["justicedao/ipfs_netherlands_laws_knowledge_graph"].support_level == "sidecar"
    assert strategies["justicedao/ipfs_france_laws_bm25_index"].support_level == "sidecar"
    assert strategies["justicedao/ipfs_france_laws_knowledge_graph"].support_level == "sidecar"
    assert strategies["justicedao/ipfs_spain_laws_bm25_index"].support_level == "sidecar"
    assert strategies["justicedao/ipfs_spain_laws_knowledge_graph"].support_level == "sidecar"
    assert strategies["justicedao/ipfs_germany_laws_bm25_index"].support_level == "sidecar"
    assert strategies["justicedao/ipfs_germany_laws_knowledge_graph"].support_level == "sidecar"
    assert strategies["justicedao/ipfs_netherlands_laws"].support_level == "metadata_only"
    assert strategies["justicedao/ipfs_france_laws"].support_level == "metadata_only"
    assert strategies["justicedao/ipfs_spain_laws"].support_level == "metadata_only"
    assert strategies["justicedao/ipfs_germany_laws"].support_level == "metadata_only"


def test_justicedao_legal_citation_query_plan_aliases_match_bluebook_functions(tmp_path):
    from ipfs_datasets_py.processors.legal_scrapers.justicedao_dataset_inventory import (
        bluebook_dataset_execution_result_to_dict,
        bluebook_dataset_query_plan_to_dict,
        build_justicedao_bluebook_query_plan,
        execute_justicedao_bluebook_query_plan,
        render_bluebook_dataset_query_plan_markdown,
    )

    text = "42 U.S.C. § 1983 and Art. 1 GG"
    alias_plan = build_justicedao_legal_citation_query_plan(text, profiles=_profiles())
    legacy_plan = build_justicedao_bluebook_query_plan(text, profiles=_profiles())

    assert isinstance(alias_plan, LegalCitationDatasetQueryPlan)
    assert legal_citation_dataset_query_plan_to_dict(alias_plan) == bluebook_dataset_query_plan_to_dict(legacy_plan)
    assert render_justicedao_legal_citation_query_plan_markdown(alias_plan) == render_bluebook_dataset_query_plan_markdown(legacy_plan)

    uscode_path = tmp_path / "us_code_alias.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafyuscode1983alias",
                    "citation": "42 U.S.C. § 1983",
                    "title": "42 U.S.C. § 1983",
                    "text": "Every person who, under color of law, deprives another of rights secured by the Constitution...",
                }
            ]
        ),
        uscode_path,
    )
    germany_path = tmp_path / "germany_laws_alias.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafydegg1aliasplan",
                    "law_identifier": "GG-Art-1",
                    "official_identifier": "Grundgesetz Art. 1",
                    "citation": "Art. 1 GG",
                    "title": "Grundgesetz Art. 1",
                    "text": "Die Wuerde des Menschen ist unantastbar.",
                }
            ]
        ),
        germany_path,
    )

    alias_result = execute_justicedao_legal_citation_query_plan(
        alias_plan,
        profiles=_profiles(),
        parquet_file_overrides={
            "ipfs_uscode": [str(uscode_path)],
            "germany_laws": [str(germany_path)],
        },
    )
    legacy_result = execute_justicedao_bluebook_query_plan(
        legacy_plan,
        profiles=_profiles(),
        parquet_file_overrides={
            "ipfs_uscode": [str(uscode_path)],
            "germany_laws": [str(germany_path)],
        },
    )

    assert legal_citation_dataset_execution_result_to_dict(alias_result) == bluebook_dataset_execution_result_to_dict(legacy_result)


def test_justicedao_legal_citation_strategy_aliases_match_bluebook_functions():
    from ipfs_datasets_py.processors.legal_scrapers.justicedao_dataset_inventory import (
        derive_justicedao_bluebook_strategies,
    )

    alias_strategies = derive_justicedao_legal_citation_strategies(_profiles_with_germany_family())
    legacy_strategies = derive_justicedao_bluebook_strategies(_profiles_with_germany_family())

    assert alias_strategies == legacy_strategies
    assert isinstance(alias_strategies["justicedao/ipfs_germany_laws"], LegalCitationQueryStrategy)


def test_derive_justicedao_legal_citation_strategies_can_classify_france_laws_when_observed():
    strategies = derive_justicedao_legal_citation_strategies(_profiles_with_france_family())

    france = strategies["justicedao/ipfs_france_laws"]
    assert france.support_level == "metadata_only"
    assert france.canonical_corpus_key == "france_laws"
    assert france.legal_branch == "eu"
    assert france.country_codes == ["FR"]

    france_bm25 = strategies["justicedao/ipfs_france_laws_bm25_index"]
    assert france_bm25.support_level == "sidecar"
    assert france_bm25.canonical_corpus_key == "france_laws"
    assert france_bm25.legal_branch == "eu"
    assert france_bm25.country_codes == ["FR"]

    france_graph = strategies["justicedao/ipfs_france_laws_knowledge_graph"]
    assert france_graph.support_level == "sidecar"
    assert france_graph.canonical_corpus_key == "france_laws"
    assert france_graph.legal_branch == "eu"
    assert france_graph.country_codes == ["FR"]


def test_derive_justicedao_legal_citation_strategies_can_classify_spain_laws_when_observed():
    strategies = derive_justicedao_legal_citation_strategies(_profiles_with_spain_family())

    spain = strategies["justicedao/ipfs_spain_laws"]
    assert spain.support_level == "metadata_only"
    assert spain.canonical_corpus_key == "spain_laws"
    assert spain.legal_branch == "eu"
    assert spain.country_codes == ["ES"]

    spain_bm25 = strategies["justicedao/ipfs_spain_laws_bm25_index"]
    assert spain_bm25.support_level == "sidecar"
    assert spain_bm25.canonical_corpus_key == "spain_laws"
    assert spain_bm25.legal_branch == "eu"
    assert spain_bm25.country_codes == ["ES"]

    spain_graph = strategies["justicedao/ipfs_spain_laws_knowledge_graph"]
    assert spain_graph.support_level == "sidecar"
    assert spain_graph.canonical_corpus_key == "spain_laws"
    assert spain_graph.legal_branch == "eu"
    assert spain_graph.country_codes == ["ES"]


def test_build_eu_country_corpus_onboarding_plan_keeps_sidecar_only_canonical_observation_registered():
    plan = build_eu_country_corpus_onboarding_plan(
        [
            *_profiles(),
            DatasetProfile(dataset_id="justicedao/ipfs_spain_laws_bm25_index"),
        ]
    )

    assert plan["ES"]["status"] == "registered"
    assert plan["ES"]["existing_dataset_ids"] == ["justicedao/ipfs_spain_laws_bm25_index"]
    assert plan["ES"]["canonical_corpus_keys"] == ["spain_laws"]


def test_derive_justicedao_legal_citation_strategies_can_classify_germany_laws_when_observed():
    strategies = derive_justicedao_legal_citation_strategies(_profiles_with_germany_family())

    germany = strategies["justicedao/ipfs_germany_laws"]
    assert germany.support_level == "metadata_only"
    assert germany.canonical_corpus_key == "germany_laws"
    assert germany.legal_branch == "eu"
    assert germany.country_codes == ["DE"]

    germany_bm25 = strategies["justicedao/ipfs_germany_laws_bm25_index"]
    assert germany_bm25.support_level == "sidecar"
    assert germany_bm25.canonical_corpus_key == "germany_laws"
    assert germany_bm25.legal_branch == "eu"
    assert germany_bm25.country_codes == ["DE"]

    germany_graph = strategies["justicedao/ipfs_germany_laws_knowledge_graph"]
    assert germany_graph.support_level == "sidecar"
    assert germany_graph.canonical_corpus_key == "germany_laws"
    assert germany_graph.legal_branch == "eu"
    assert germany_graph.country_codes == ["DE"]


def test_legal_citation_query_plan_renderers_include_dataset_guidance():
    plan = build_justicedao_legal_citation_query_plan(
        "347 U.S. 483 and 90 FR 12345",
        profiles=_profiles(),
    )
    payload = legal_citation_dataset_query_plan_to_dict(plan)
    markdown = render_justicedao_legal_citation_query_plan_markdown(plan)

    assert payload["query_plans"]
    assert "JusticeDAO Legal Citation Query Plan" in markdown
    assert "justicedao/caselaw_access_project" in markdown
    assert "justicedao/ipfs_federal_register" in markdown


def test_build_justicedao_legal_citation_query_plan_includes_eu_member_state_citations():
    profiles = [
        *_profiles_with_spain_family(),
        *_profiles_with_germany_family()[len(_profiles()):],
    ]

    plan = build_justicedao_legal_citation_query_plan(
        "Art. 1 GG and Articulo 1902 del Codigo Civil.",
        profiles=profiles,
    )

    eu_types = {item.citation_type for item in plan.query_plans}
    assert "eu_de_gg_article" in eu_types
    assert "eu_es_cc_article" in eu_types

    germany_plan = next(item for item in plan.query_plans if item.citation_type == "eu_de_gg_article")
    spain_plan = next(item for item in plan.query_plans if item.citation_type == "eu_es_cc_article")
    assert germany_plan.candidate_datasets[0].dataset_id == "justicedao/ipfs_germany_laws"
    assert spain_plan.candidate_datasets[0].dataset_id == "justicedao/ipfs_spain_laws"


def test_execute_justicedao_legal_citation_query_plan_matches_state_laws_and_uscode(tmp_path):
    state_laws_path = tmp_path / "state_laws.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "ipfs_cid": "bafyor90155",
                    "state_code": "OR",
                    "source_id": "https://oregon.public.law/statutes/ors_90.155",
                    "identifier": "Or. Rev. Stat. § 90.155",
                    "name": "Termination notice periods",
                    "text": "This section governs notice periods in residential tenancy.",
                    "jsonld": "{}",
                }
            ]
        ),
        state_laws_path,
    )

    uscode_index_path = tmp_path / "uscode_index.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "ipfs_cid": "bafyuscode1983",
                    "title_number": "42",
                    "section_number": "1983",
                }
            ]
        ),
        uscode_index_path,
    )

    plan = build_justicedao_legal_citation_query_plan(
        "See Or. Rev. Stat. § 90.155 and 42 U.S.C. § 1983.",
        profiles=_profiles(),
    )
    result = execute_justicedao_legal_citation_query_plan(
        plan,
        profiles=_profiles(),
        parquet_file_overrides={
            "justicedao/ipfs_state_laws": [str(state_laws_path)],
            "justicedao/ipfs_uscode": [str(uscode_index_path)],
        },
    )

    payload = legal_citation_dataset_execution_result_to_dict(result)
    assert len(payload["execution_results"]) == 2

    state_result = next(item for item in payload["execution_results"] if item["citation_type"] == "state_statute")
    assert state_result["matches"][0]["dataset_id"] == "justicedao/ipfs_state_laws"
    assert state_result["matches"][0]["rows"][0]["identifier"] == "Or. Rev. Stat. § 90.155"

    usc_result = next(item for item in payload["execution_results"] if item["citation_type"] == "usc")
    assert usc_result["matches"][0]["dataset_id"] == "justicedao/ipfs_uscode"
    assert usc_result["matches"][0]["rows"][0]["section_number"] == "1983"


def test_execute_justicedao_legal_citation_query_plan_matches_eu_member_state_citations(tmp_path):
    germany_path = tmp_path / "germany_laws.parquet"
    spain_path = tmp_path / "spain_laws.parquet"

    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafydegg1",
                    "law_identifier": "GG-Art-1",
                    "official_identifier": "Grundgesetz Art. 1",
                    "citation": "Art. 1 GG",
                    "title": "Grundgesetz Art. 1",
                    "text": "Die Wuerde des Menschen ist unantastbar.",
                    "summary": "Artikel 1 des Grundgesetzes schuetzt die Menschenwuerde.",
                }
            ]
        ),
        germany_path,
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafyescc1902",
                    "law_identifier": "CC-Articulo-1902",
                    "official_identifier": "Codigo Civil art. 1902",
                    "citation": "Articulo 1902 del Codigo Civil",
                    "title": "Codigo Civil art. 1902",
                    "text": "El que por accion u omision causa dano a otro interviniendo culpa o negligencia esta obligado a reparar el dano causado.",
                    "summary": "Responsabilidad extracontractual del Codigo Civil.",
                }
            ]
        ),
        spain_path,
    )

    profiles = [
        *_profiles_with_spain_family(),
        *_profiles_with_germany_family()[len(_profiles()):],
    ]
    plan = build_justicedao_legal_citation_query_plan(
        "Art. 1 GG and Articulo 1902 del Codigo Civil.",
        profiles=profiles,
    )
    result = execute_justicedao_legal_citation_query_plan(
        plan,
        profiles=profiles,
        parquet_file_overrides={
            "justicedao/ipfs_germany_laws": [str(germany_path)],
            "justicedao/ipfs_spain_laws": [str(spain_path)],
        },
    )

    payload = legal_citation_dataset_execution_result_to_dict(result)
    germany_result = next(item for item in payload["execution_results"] if item["citation_type"] == "eu_de_gg_article")
    spain_result = next(item for item in payload["execution_results"] if item["citation_type"] == "eu_es_cc_article")
    assert germany_result["matches"][0]["dataset_id"] == "justicedao/ipfs_germany_laws"
    assert germany_result["matches"][0]["rows"][0]["law_identifier"] == "GG-Art-1"
    assert spain_result["matches"][0]["dataset_id"] == "justicedao/ipfs_spain_laws"
    assert spain_result["matches"][0]["rows"][0]["law_identifier"] == "CC-Articulo-1902"


def test_execute_justicedao_legal_citation_query_plan_matches_municipal_citation_table(tmp_path):
    municipal_citation_path = tmp_path / "municipal_citation.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "bluebook_citation": "Buncombe, N.C., Chapter 10",
                    "cid": "bafymuni1",
                    "title": "Chapter 10 - Buildings and Building Regulations",
                    "chapter": "Chapter 10 - BUILDINGS AND BUILDING REGULATIONS",
                    "place_name": "Buncombe",
                    "bluebook_state_code": "N.C.",
                }
            ]
        ),
        municipal_citation_path,
    )

    strategies = derive_justicedao_legal_citation_strategies(_profiles())
    plan = LegalCitationDatasetQueryPlan(
        input_text="See Buncombe, N.C., Chapter 10.",
        citations=[{"text": "Buncombe, N.C., Chapter 10", "type": "state_statute"}],
        query_plans=[
            CitationQueryPlan(
                citation_text="Buncombe, N.C., Chapter 10",
                citation_type="state_statute",
                normalized_citation="Buncombe, N.C., Chapter 10",
                candidate_datasets=[strategies["justicedao/american_municipal_law"]],
                notes=[],
            )
        ],
        dataset_notes=[],
    )
    result = execute_justicedao_legal_citation_query_plan(
        plan,
        profiles=_profiles(),
        parquet_file_overrides={
            "justicedao/american_municipal_law": [str(municipal_citation_path)],
        },
    )

    payload = legal_citation_dataset_execution_result_to_dict(result)
    state_result = next(item for item in payload["execution_results"] if item["citation_type"] == "state_statute")
    assert state_result["matches"]
    assert state_result["matches"][0]["dataset_id"] == "justicedao/american_municipal_law"
    assert state_result["matches"][0]["rows"][0]["place_name"] == "Buncombe"


def test_execute_justicedao_legal_citation_query_plan_can_use_canonical_semantic_sidecar(tmp_path):
    state_laws_path = tmp_path / "STATE-MN.parquet"
    embeddings_path = tmp_path / "STATE-MN_embeddings.parquet"
    semantic_text = "Minn. Stat. § 518.17 best interests of the child custody factors"
    embedding = hashed_term_projection(semantic_text, dimension=16)

    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "ipfs_cid": "bafymn51817",
                    "state_code": "MN",
                    "name": "Best interests of the child",
                    "text": "The best interests of the child means all relevant factors must be considered.",
                    "jsonld": "{}",
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
                    "state_code": "MN",
                    "semantic_text": semantic_text,
                    "embedding_model": "local-test",
                    "embedding": embedding,
                }
            ]
        ),
        embeddings_path,
    )

    plan = build_justicedao_legal_citation_query_plan(
        "See Minn. Stat. § 518.17.",
        profiles=_profiles(),
    )
    result = execute_justicedao_legal_citation_query_plan(
        plan,
        profiles=_profiles(),
        parquet_file_overrides={
            "justicedao/ipfs_state_laws": [str(state_laws_path), str(embeddings_path)],
        },
    )

    payload = legal_citation_dataset_execution_result_to_dict(result)
    state_result = next(item for item in payload["execution_results"] if item["citation_type"] == "state_statute")
    assert state_result["matches"]
    assert state_result["matches"][0]["dataset_id"] == "justicedao/ipfs_state_laws"
    assert state_result["matches"][0]["rows"][0]["name"] == "Best interests of the child"


def test_summarize_dataset_profiles_by_country_groups_country_scoped_corpora():
    summary = summarize_dataset_profiles_by_country(_profiles())

    assert summary["NL"]["dataset_count"] == 3
    assert summary["NL"]["legal_branches"] == ["eu"]
    assert "justicedao/ipfs_netherlands_laws" in summary["NL"]["dataset_ids"]
    assert summary["US"]["dataset_count"] >= 6
    assert "us" in summary["US"]["legal_branches"]


def test_summarize_dataset_profiles_by_country_uses_unspecified_bucket_when_missing_country_codes():
    summary = summarize_dataset_profiles_by_country(
        [
            DatasetProfile(
                dataset_id="justicedao/custom_unknown_dataset",
                legal_branch="eu",
                parquet_files=["parquet/unknown.parquet"],
                top_level_paths=["parquet"],
                configs=[],
            )
        ]
    )

    assert summary["UNSPECIFIED"]["dataset_count"] == 1
    assert summary["UNSPECIFIED"]["legal_branches"] == ["eu"]
def test_query_canonical_legal_corpus_prefers_exact_citation_resolution(tmp_path):
    uscode_path = tmp_path / "laws.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "ipfs_cid": "bafy1983",
                    "title_number": "42",
                    "section_number": "1983",
                    "law_name": "Civil action for deprivation of rights",
                    "source_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title42-section1983",
                    "text": "Every person who, under color of state law, deprives another of rights...",
                    "identifier": "42 U.S.C. § 1983",
                }
            ]
        ),
        uscode_path,
    )

    result = query_canonical_legal_corpus(
        "us_code",
        query_text="42 U.S.C. § 1983",
        parquet_file_overrides={"us_code": [str(uscode_path)]},
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["mode"] == "exact"
    assert payload["citation_links"][0]["matched"] is True
    assert payload["results"][0]["source_cid"] == "bafy1983"


def test_query_canonical_legal_corpus_can_lexically_query_state_law_rows(tmp_path):
    state_path = tmp_path / "STATE-MN.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "ipfs_cid": "bafymn51817",
                    "state_code": "MN",
                    "source_id": "urn:state:mn:statute:518.17",
                    "identifier": "Minn. Stat. § 518.17",
                    "name": "Best interests of the child",
                    "text": "The best interests of the child means all relevant factors must be considered.",
                    "jsonld": '{"identifier":"Minn. Stat. § 518.17"}',
                }
            ]
        ),
        state_path,
    )

    result = query_canonical_legal_corpus(
        "state_laws",
        query_text="best interests of the child",
        state_code="MN",
        mode="lexical",
        parquet_file_overrides={"state_laws": [str(state_path)]},
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["mode"] == "lexical"
    assert payload["results"]
    assert payload["results"][0]["row"]["identifier"] == "Minn. Stat. § 518.17"


def test_query_canonical_legal_corpus_can_use_embeddings_sidecar(tmp_path):
    state_path = tmp_path / "STATE-MN.parquet"
    embeddings_path = tmp_path / "STATE-MN_embeddings.parquet"
    semantic_text = "Section 518.17 best interests of the child custody factors"
    embedding = hashed_term_projection(semantic_text, dimension=16)

    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "ipfs_cid": "bafymn51817",
                    "state_code": "MN",
                    "source_id": "urn:state:mn:statute:518.17",
                    "identifier": "Minn. Stat. § 518.17",
                    "name": "Best interests of the child",
                    "text": "The best interests of the child means all relevant factors must be considered.",
                    "jsonld": '{"identifier":"Minn. Stat. § 518.17"}',
                }
            ]
        ),
        state_path,
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "ipfs_cid": "bafymn51817",
                    "state_code": "MN",
                    "semantic_text": semantic_text,
                    "embedding_model": "local-test",
                    "embedding": embedding,
                }
            ]
        ),
        embeddings_path,
    )

    result = query_canonical_legal_corpus(
        "state_laws",
        query_text="custody best interests factors",
        state_code="MN",
        mode="semantic",
        parquet_file_overrides={"state_laws": [str(state_path), str(embeddings_path)]},
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["mode"] == "semantic"
    assert payload["embeddings_file"].endswith("STATE-MN_embeddings.parquet")
    assert payload["results"][0]["row"]["identifier"] == "Minn. Stat. § 518.17"


def test_query_canonical_legal_corpus_can_use_faiss_sidecar(tmp_path):
    faiss = pytest.importorskip("faiss")
    np = pytest.importorskip("numpy")
    if not hasattr(faiss, "read_index") or not hasattr(faiss, "write_index"):
        pytest.skip("faiss bindings without index constructors are not usable in this environment")

    federal_path = tmp_path / "federal_register.parquet"
    metadata_path = tmp_path / "federal_register_gte_small_metadata.parquet"
    index_path = tmp_path / "federal_register_gte_small.faiss"

    semantic_text = "Environmental Protection Agency notice clean air reporting"
    embedding = hashed_term_projection(semantic_text, dimension=16)

    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "cid": "bagufr1",
                    "source_id": "urn:federal-register:doc:EPA-123",
                    "identifier": "EPA-123",
                    "name": "Environmental Protection Agency Notice",
                    "legislation_type": "notice",
                    "date_published": "2026-01-01",
                    "agency": "Environmental Protection Agency",
                    "source_url": "https://federalregister.gov/d/EPA-123",
                    "jsonld": "{}",
                }
            ]
        ),
        federal_path,
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "vector_id": 0,
                    "cid": "bagufr1",
                    "identifier": "EPA-123",
                    "name": "Environmental Protection Agency Notice",
                    "agency": "Environmental Protection Agency",
                    "legislation_type": "notice",
                    "date_published": "2026-01-01",
                    "semantic_text": semantic_text,
                }
            ]
        ),
        metadata_path,
    )

    vectors = np.asarray([embedding], dtype="float32")
    if hasattr(faiss, "IndexFlatIP"):
        index = faiss.IndexFlatIP(16)
    elif hasattr(faiss, "IndexFlatL2"):
        index = faiss.IndexFlatL2(16)
    elif hasattr(faiss, "index_factory"):
        index = faiss.index_factory(16, "Flat", getattr(faiss, "METRIC_INNER_PRODUCT", 0))
    else:
        pytest.skip("faiss index constructors are unavailable in this environment")
    index.add(vectors)
    faiss.write_index(index, str(index_path))

    result = query_canonical_legal_corpus(
        "federal_register",
        query_text="environmental protection agency notice",
        mode="semantic",
        parquet_file_overrides={
            "federal_register": [str(federal_path), str(metadata_path), str(index_path)]
        },
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["mode"] == "semantic_faiss"
    assert payload["results"]
    assert payload["results"][0]["row"]["identifier"] == "EPA-123"


def test_query_canonical_legal_corpus_can_query_netherlands_as_eu_branch(tmp_path):
    laws_path = tmp_path / "netherlands_laws.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafynlburgerlijk",
                    "law_identifier": "BWBR0002656",
                    "official_identifier": "Burgerlijk Wetboek Boek 1",
                    "citation": "Burgerlijk Wetboek Boek 1",
                    "title": "Burgerlijk Wetboek Boek 1",
                    "text": "Het Burgerlijk Wetboek Boek 1 bevat regels over personen- en familierecht.",
                    "summary": "Nederlandse civielrechtelijke basiswet.",
                }
            ]
        ),
        laws_path,
    )

    result = query_canonical_legal_corpus(
        "netherlands_laws",
        query_text="Burgerlijk Wetboek Boek 1",
        mode="lexical",
        parquet_file_overrides={"netherlands_laws": [str(laws_path)]},
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["legal_branch"] == "eu"
    assert payload["country_codes"] == ["NL"]
    assert payload["mode"] == "lexical"
    assert payload["results"]
    assert payload["results"][0]["row"]["law_identifier"] == "BWBR0002656"


def test_query_canonical_legal_corpus_can_query_france_as_eu_branch(tmp_path):
    laws_path = tmp_path / "france_laws.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafyfrcodecivil",
                    "law_identifier": "CC-Art-1240",
                    "official_identifier": "Code civil art. 1240",
                    "citation": "article 1240 du code civil",
                    "title": "Code civil art. 1240",
                    "text": "Tout fait quelconque de l'homme, qui cause a autrui un dommage, oblige celui par la faute duquel il est arrive a le reparer.",
                    "summary": "Disposition du Code civil relative a la responsabilite civile.",
                }
            ]
        ),
        laws_path,
    )

    result = query_canonical_legal_corpus(
        "france_laws",
        query_text="article 1240 du code civil",
        parquet_file_overrides={"france_laws": [str(laws_path)]},
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["legal_branch"] == "eu"
    assert payload["country_codes"] == ["FR"]
    assert payload["mode"] == "exact"
    assert payload["citation_links"][0]["matched"] is True
    assert payload["results"]
    assert payload["results"][0]["row"]["law_identifier"] == "CC-Art-1240"


def test_query_canonical_legal_corpus_can_query_france_short_form_as_eu_branch(tmp_path):
    laws_path = tmp_path / "france_laws_short_form.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafyfrcodecivil16",
                    "law_identifier": "CC-Art-16",
                    "official_identifier": "Code civil art. 16",
                    "citation": "Art. 16 Code civil",
                    "title": "Code civil art. 16",
                    "text": "La loi assure la primaute de la personne, interdit toute atteinte a la dignite de celle-ci et garantit le respect de l'etre humain des le commencement de sa vie.",
                    "summary": "Disposition du Code civil relative a la primaute de la personne.",
                }
            ]
        ),
        laws_path,
    )

    result = query_canonical_legal_corpus(
        "france_laws",
        query_text="Art. 16 Code civil",
        parquet_file_overrides={"france_laws": [str(laws_path)]},
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["legal_branch"] == "eu"
    assert payload["country_codes"] == ["FR"]
    assert payload["mode"] == "exact"
    assert payload["citation_links"][0]["matched"] is True
    assert payload["results"]
    assert payload["results"][0]["row"]["law_identifier"] == "CC-Art-16"


def test_query_canonical_legal_corpus_can_query_spain_as_eu_branch(tmp_path):
    laws_path = tmp_path / "spain_laws.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafyescodigocivil",
                    "law_identifier": "CC-Articulo-14",
                    "official_identifier": "Codigo Civil art. 14",
                    "citation": "Articulo 14 del Codigo Civil",
                    "title": "Codigo Civil art. 14",
                    "text": "Las leyes entraran en vigor segun lo dispuesto en el Codigo Civil.",
                    "summary": "Disposicion del Codigo Civil sobre vigencia y aplicacion de las leyes.",
                }
            ]
        ),
        laws_path,
    )

    result = query_canonical_legal_corpus(
        "spain_laws",
        query_text="Articulo 14 del Codigo Civil",
        parquet_file_overrides={"spain_laws": [str(laws_path)]},
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["legal_branch"] == "eu"
    assert payload["country_codes"] == ["ES"]
    assert payload["mode"] == "exact"
    assert payload["citation_links"][0]["matched"] is True
    assert payload["results"]
    assert payload["results"][0]["row"]["law_identifier"] == "CC-Articulo-14"


def test_query_canonical_legal_corpus_can_query_spain_short_form_as_eu_branch(tmp_path):
    laws_path = tmp_path / "spain_laws_short_form.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafyescodigocivil14",
                    "law_identifier": "CC-Art-14",
                    "official_identifier": "Codigo Civil art. 14",
                    "citation": "Art. 14 Codigo Civil",
                    "title": "Codigo Civil art. 14",
                    "text": "Las leyes entraran en vigor segun lo dispuesto en el Codigo Civil.",
                    "summary": "Disposicion del Codigo Civil sobre vigencia y aplicacion de las leyes.",
                }
            ]
        ),
        laws_path,
    )

    result = query_canonical_legal_corpus(
        "spain_laws",
        query_text="Art. 14 Codigo Civil",
        parquet_file_overrides={"spain_laws": [str(laws_path)]},
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["legal_branch"] == "eu"
    assert payload["country_codes"] == ["ES"]
    assert payload["mode"] == "exact"
    assert payload["citation_links"][0]["matched"] is True
    assert payload["results"]
    assert payload["results"][0]["row"]["law_identifier"] == "CC-Art-14"


def test_query_canonical_legal_corpus_can_query_germany_as_eu_branch(tmp_path):
    laws_path = tmp_path / "germany_laws.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafydegg1",
                    "law_identifier": "GG-Art-1",
                    "official_identifier": "Grundgesetz Art. 1",
                    "citation": "Art. 1 GG",
                    "title": "Grundgesetz Art. 1",
                    "text": "Die Würde des Menschen ist unantastbar.",
                    "summary": "Artikel 1 des Grundgesetzes schützt die Menschenwürde.",
                }
            ]
        ),
        laws_path,
    )

    result = query_canonical_legal_corpus(
        "germany_laws",
        query_text="Art. 1 GG",
        parquet_file_overrides={"germany_laws": [str(laws_path)]},
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["legal_branch"] == "eu"
    assert payload["country_codes"] == ["DE"]
    assert payload["mode"] == "exact"
    assert payload["citation_links"][0]["matched"] is True
    assert payload["results"]
    assert payload["results"][0]["row"]["law_identifier"] == "GG-Art-1"


def test_query_canonical_legal_corpus_can_query_germany_grundgesetz_variant_as_eu_branch(tmp_path):
    laws_path = tmp_path / "germany_laws_grundgesetz.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafydegg1grundgesetz",
                    "law_identifier": "GG-Art-1-Grundgesetz",
                    "official_identifier": "Grundgesetz Art. 1",
                    "citation": "Grundgesetz Art. 1",
                    "title": "Grundgesetz Art. 1",
                    "text": "Die Wuerde des Menschen ist unantastbar.",
                    "summary": "Artikel 1 des Grundgesetzes schuetzt die Menschenwuerde.",
                }
            ]
        ),
        laws_path,
    )

    result = query_canonical_legal_corpus(
        "germany_laws",
        query_text="Grundgesetz Art. 1",
        parquet_file_overrides={"germany_laws": [str(laws_path)]},
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["legal_branch"] == "eu"
    assert payload["country_codes"] == ["DE"]
    assert payload["mode"] == "exact"
    assert payload["citation_links"][0]["matched"] is True
    assert payload["results"]
    assert payload["results"][0]["row"]["law_identifier"] == "GG-Art-1-Grundgesetz"


def test_query_canonical_legal_corpus_can_query_germany_genitive_grundgesetz_variant_as_eu_branch(tmp_path):
    laws_path = tmp_path / "germany_laws_grundgesetz_genitive.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafydegg1grundgesetzgenitive",
                    "law_identifier": "GG-Art-1-Grundgesetzes",
                    "official_identifier": "Artikel 1 des Grundgesetzes",
                    "citation": "Art. 1 des Grundgesetzes",
                    "title": "Artikel 1 des Grundgesetzes",
                    "text": "Die Wuerde des Menschen ist unantastbar.",
                    "summary": "Artikel 1 des Grundgesetzes schuetzt die Menschenwuerde.",
                }
            ]
        ),
        laws_path,
    )

    result = query_canonical_legal_corpus(
        "germany_laws",
        query_text="Art. 1 des Grundgesetzes",
        parquet_file_overrides={"germany_laws": [str(laws_path)]},
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["legal_branch"] == "eu"
    assert payload["country_codes"] == ["DE"]
    assert payload["mode"] == "exact"
    assert payload["citation_links"][0]["matched"] is True
    assert payload["results"]
    assert payload["results"][0]["row"]["law_identifier"] == "GG-Art-1-Grundgesetzes"


def test_query_canonical_legal_corpus_can_query_germany_paragraph_variant_as_eu_branch(tmp_path):
    laws_path = tmp_path / "germany_laws_paragraph.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafydegg1abs1",
                    "law_identifier": "GG-Art-1-Abs-1",
                    "official_identifier": "Artikel 1 Absatz 1 GG",
                    "citation": "Art. 1 Abs. 1 GG",
                    "title": "Artikel 1 Absatz 1 GG",
                    "text": "Die Wuerde des Menschen ist unantastbar.",
                    "summary": "Artikel 1 Absatz 1 des Grundgesetzes schuetzt die Menschenwuerde.",
                }
            ]
        ),
        laws_path,
    )

    result = query_canonical_legal_corpus(
        "germany_laws",
        query_text="Art. 1 Abs. 1 GG",
        parquet_file_overrides={"germany_laws": [str(laws_path)]},
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["legal_branch"] == "eu"
    assert payload["country_codes"] == ["DE"]
    assert payload["mode"] == "exact"
    assert payload["citation_links"][0]["matched"] is True
    assert payload["results"]
    assert payload["results"][0]["row"]["law_identifier"] == "GG-Art-1-Abs-1"


def test_query_canonical_legal_corpus_can_query_germany_paragraph_genitive_variant_as_eu_branch(tmp_path):
    laws_path = tmp_path / "germany_laws_paragraph_genitive.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafydegg1abs1genitive",
                    "law_identifier": "GG-Art-1-Abs-1-Grundgesetzes",
                    "official_identifier": "Artikel 1 Absatz 1 des Grundgesetzes",
                    "citation": "Art. 1 Abs. 1 des Grundgesetzes",
                    "title": "Artikel 1 Absatz 1 des Grundgesetzes",
                    "text": "Die Wuerde des Menschen ist unantastbar.",
                    "summary": "Artikel 1 Absatz 1 des Grundgesetzes schuetzt die Menschenwuerde.",
                }
            ]
        ),
        laws_path,
    )

    result = query_canonical_legal_corpus(
        "germany_laws",
        query_text="Art. 1 Abs. 1 des Grundgesetzes",
        parquet_file_overrides={"germany_laws": [str(laws_path)]},
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["legal_branch"] == "eu"
    assert payload["country_codes"] == ["DE"]
    assert payload["mode"] == "exact"
    assert payload["citation_links"][0]["matched"] is True
    assert payload["results"]
    assert payload["results"][0]["row"]["law_identifier"] == "GG-Art-1-Abs-1-Grundgesetzes"


def test_query_canonical_legal_corpus_can_query_germany_roman_paragraph_variant_as_eu_branch(tmp_path):
    laws_path = tmp_path / "germany_laws_paragraph_roman.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafydegg1roman",
                    "law_identifier": "GG-Art-1-I",
                    "official_identifier": "Artikel 1 Absatz 1 GG",
                    "citation": "Art. 1 I GG",
                    "title": "Artikel 1 Absatz 1 GG",
                    "text": "Die Wuerde des Menschen ist unantastbar.",
                    "summary": "Artikel 1 Absatz 1 des Grundgesetzes schuetzt die Menschenwuerde.",
                }
            ]
        ),
        laws_path,
    )

    result = query_canonical_legal_corpus(
        "germany_laws",
        query_text="Art. 1 I GG",
        parquet_file_overrides={"germany_laws": [str(laws_path)]},
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["legal_branch"] == "eu"
    assert payload["country_codes"] == ["DE"]
    assert payload["mode"] == "exact"
    assert payload["citation_links"][0]["matched"] is True
    assert payload["results"]
    assert payload["results"][0]["row"]["law_identifier"] == "GG-Art-1-I"


def test_query_canonical_legal_corpus_can_query_germany_roman_paragraph_genitive_gg_variant_as_eu_branch(tmp_path):
    laws_path = tmp_path / "germany_laws_paragraph_roman_genitive_gg.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafydegg1romangenitivegg",
                    "law_identifier": "GG-Art-1-I-des-GG",
                    "official_identifier": "Artikel 1 Absatz 1 GG",
                    "citation": "Art. 1 I des GG",
                    "title": "Artikel 1 Absatz 1 GG",
                    "text": "Die Wuerde des Menschen ist unantastbar.",
                    "summary": "Artikel 1 Absatz 1 des Grundgesetzes schuetzt die Menschenwuerde.",
                }
            ]
        ),
        laws_path,
    )

    result = query_canonical_legal_corpus(
        "germany_laws",
        query_text="Art. 1 I des GG",
        parquet_file_overrides={"germany_laws": [str(laws_path)]},
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["legal_branch"] == "eu"
    assert payload["country_codes"] == ["DE"]
    assert payload["mode"] == "exact"
    assert payload["citation_links"][0]["matched"] is True
    assert payload["results"]
    assert payload["results"][0]["row"]["law_identifier"] == "GG-Art-1-I-des-GG"


def test_query_canonical_legal_corpus_can_query_germany_artikel_absatz_genitive_gg_variant_as_eu_branch(tmp_path):
    laws_path = tmp_path / "germany_laws_paragraph_fullword_genitive_gg.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafydegg1absatzgenitivegg",
                    "law_identifier": "GG-Artikel-1-Absatz-1-des-GG",
                    "official_identifier": "Artikel 1 Absatz 1 des GG",
                    "citation": "Art. 1 Abs. 1 des GG",
                    "title": "Artikel 1 Absatz 1 des GG",
                    "text": "Die Wuerde des Menschen ist unantastbar.",
                    "summary": "Artikel 1 Absatz 1 des Grundgesetzes schuetzt die Menschenwuerde.",
                }
            ]
        ),
        laws_path,
    )

    result = query_canonical_legal_corpus(
        "germany_laws",
        query_text="Artikel 1 Absatz 1 des GG",
        parquet_file_overrides={"germany_laws": [str(laws_path)]},
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["legal_branch"] == "eu"
    assert payload["country_codes"] == ["DE"]
    assert payload["mode"] == "exact"
    assert payload["citation_links"][0]["matched"] is True
    assert payload["results"]
    assert payload["results"][0]["row"]["law_identifier"] == "GG-Artikel-1-Absatz-1-des-GG"


def test_query_canonical_legal_corpus_can_query_germany_artikel_absatz_genitive_grundgesetz_variant_as_eu_branch(tmp_path):
    laws_path = tmp_path / "germany_laws_paragraph_fullword_genitive_grundgesetz.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafydegg1absatzgrundgesetzes",
                    "law_identifier": "GG-Artikel-1-Absatz-1-des-Grundgesetzes",
                    "official_identifier": "Artikel 1 Absatz 1 des Grundgesetzes",
                    "citation": "Art. 1 Abs. 1 des Grundgesetzes",
                    "title": "Artikel 1 Absatz 1 des Grundgesetzes",
                    "text": "Die Wuerde des Menschen ist unantastbar.",
                    "summary": "Artikel 1 Absatz 1 des Grundgesetzes schuetzt die Menschenwuerde.",
                }
            ]
        ),
        laws_path,
    )

    result = query_canonical_legal_corpus(
        "germany_laws",
        query_text="Artikel 1 Absatz 1 des Grundgesetzes",
        parquet_file_overrides={"germany_laws": [str(laws_path)]},
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["legal_branch"] == "eu"
    assert payload["country_codes"] == ["DE"]
    assert payload["mode"] == "exact"
    assert payload["citation_links"][0]["matched"] is True
    assert payload["results"]
    assert payload["results"][0]["row"]["law_identifier"] == "GG-Artikel-1-Absatz-1-des-Grundgesetzes"


def test_query_canonical_legal_corpus_can_query_reversed_germany_artikel_absatz_genitive_gg_variant_as_eu_branch(tmp_path):
    laws_path = tmp_path / "germany_laws_reversed_paragraph_fullword_genitive_gg.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafydeggreversedabsatzgenitivegg",
                    "law_identifier": "GG-Grundgesetz-Artikel-1-Absatz-1-des-GG",
                    "official_identifier": "Grundgesetz Artikel 1 Absatz 1 des GG",
                    "citation": "Grundgesetz Artikel 1 Absatz 1 des GG",
                    "title": "Grundgesetz Artikel 1 Absatz 1 des GG",
                    "text": "Die Wuerde des Menschen ist unantastbar.",
                    "summary": "Artikel 1 Absatz 1 des Grundgesetzes schuetzt die Menschenwuerde.",
                }
            ]
        ),
        laws_path,
    )

    result = query_canonical_legal_corpus(
        "germany_laws",
        query_text="Grundgesetz Artikel 1 Absatz 1 des GG",
        parquet_file_overrides={"germany_laws": [str(laws_path)]},
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["legal_branch"] == "eu"
    assert payload["country_codes"] == ["DE"]
    assert payload["mode"] == "exact"
    assert payload["citation_links"][0]["matched"] is True
    assert payload["results"]
    assert payload["results"][0]["row"]["law_identifier"] == "GG-Grundgesetz-Artikel-1-Absatz-1-des-GG"


def test_query_canonical_legal_corpus_can_query_reversed_germany_artikel_absatz_genitive_grundgesetz_variant_as_eu_branch(tmp_path):
    laws_path = tmp_path / "germany_laws_reversed_paragraph_fullword_genitive_grundgesetz.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafydeggreversedabsatzgrundgesetzes",
                    "law_identifier": "GG-Grundgesetz-Artikel-1-Absatz-1-des-Grundgesetzes",
                    "official_identifier": "Grundgesetz Artikel 1 Absatz 1 des Grundgesetzes",
                    "citation": "Grundgesetz Artikel 1 Absatz 1 des Grundgesetzes",
                    "title": "Grundgesetz Artikel 1 Absatz 1 des Grundgesetzes",
                    "text": "Die Wuerde des Menschen ist unantastbar.",
                    "summary": "Artikel 1 Absatz 1 des Grundgesetzes schuetzt die Menschenwuerde.",
                }
            ]
        ),
        laws_path,
    )

    result = query_canonical_legal_corpus(
        "germany_laws",
        query_text="Grundgesetz Artikel 1 Absatz 1 des Grundgesetzes",
        parquet_file_overrides={"germany_laws": [str(laws_path)]},
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["legal_branch"] == "eu"
    assert payload["country_codes"] == ["DE"]
    assert payload["mode"] == "exact"
    assert payload["citation_links"][0]["matched"] is True
    assert payload["results"]
    assert payload["results"][0]["row"]["law_identifier"] == "GG-Grundgesetz-Artikel-1-Absatz-1-des-Grundgesetzes"


def test_query_canonical_legal_corpus_can_query_reversed_germany_artikel_absatz_variant_as_eu_branch(tmp_path):
    laws_path = tmp_path / "germany_laws_reversed_paragraph_fullword.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafydeggreversedabsatzplain",
                    "law_identifier": "GG-Grundgesetz-Artikel-1-Absatz-1",
                    "official_identifier": "Grundgesetz Artikel 1 Absatz 1",
                    "citation": "Grundgesetz Artikel 1 Absatz 1",
                    "title": "Grundgesetz Artikel 1 Absatz 1",
                    "text": "Die Wuerde des Menschen ist unantastbar.",
                    "summary": "Artikel 1 Absatz 1 des Grundgesetzes schuetzt die Menschenwuerde.",
                }
            ]
        ),
        laws_path,
    )

    result = query_canonical_legal_corpus(
        "germany_laws",
        query_text="Grundgesetz Artikel 1 Absatz 1",
        parquet_file_overrides={"germany_laws": [str(laws_path)]},
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["legal_branch"] == "eu"
    assert payload["country_codes"] == ["DE"]
    assert payload["mode"] == "exact"
    assert payload["citation_links"][0]["matched"] is True
    assert payload["results"]
    assert payload["results"][0]["row"]["law_identifier"] == "GG-Grundgesetz-Artikel-1-Absatz-1"


def test_query_canonical_legal_corpus_can_query_reversed_germany_roman_paragraph_variant_as_eu_branch(tmp_path):
    laws_path = tmp_path / "germany_laws_paragraph_roman_reversed.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "source_cid": "bafydegg1romanreversed",
                    "law_identifier": "GG-Grundgesetz-Art-1-I",
                    "official_identifier": "Grundgesetz Art. 1 I",
                    "citation": "Grundgesetz Art. 1 I",
                    "title": "Grundgesetz Art. 1 I",
                    "text": "Die Wuerde des Menschen ist unantastbar.",
                    "summary": "Artikel 1 Absatz 1 des Grundgesetzes schuetzt die Menschenwuerde.",
                }
            ]
        ),
        laws_path,
    )

    result = query_canonical_legal_corpus(
        "germany_laws",
        query_text="Grundgesetz Art. 1 I",
        parquet_file_overrides={"germany_laws": [str(laws_path)]},
        allow_hf_fallback=False,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["legal_branch"] == "eu"
    assert payload["country_codes"] == ["DE"]
    assert payload["mode"] == "exact"
    assert payload["citation_links"][0]["matched"] is True
    assert payload["results"]
    assert payload["results"][0]["row"]["law_identifier"] == "GG-Grundgesetz-Art-1-I"


def test_query_canonical_legal_corpus_can_use_inventory_profile_when_remote_path_misses_templates(tmp_path, monkeypatch):
    state_path = tmp_path / "STATE-MN-live.parquet"
    remote_path = "exports/live/legal/STATE-MN-live.parquet"

    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "ipfs_cid": "bafymn51817",
                    "state_code": "MN",
                    "source_id": "urn:state:mn:statute:518.17",
                    "identifier": "Minn. Stat. § 518.17",
                    "name": "Best interests of the child",
                    "text": "The best interests of the child means all relevant factors must be considered.",
                    "jsonld": '{"identifier":"Minn. Stat. § 518.17"}',
                }
            ]
        ),
        state_path,
    )

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.justicedao_dataset_inventory._list_repo_files_cached",
        lambda repo_id: [remote_path],
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.justicedao_dataset_inventory._download_hf_dataset_file",
        lambda repo_id, filename: str(state_path) if filename == remote_path else "",
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.justicedao_dataset_inventory.inspect_justicedao_datasets",
        lambda **kwargs: [
            DatasetProfile(
                dataset_id="justicedao/ipfs_state_laws",
                canonical_corpus_key="state_laws",
                legal_branch="us",
                country_codes=["US"],
                parquet_files=[remote_path],
                top_level_paths=["exports"],
                configs=[
                    DatasetConfigProfile(
                        config="state_laws_canonical",
                        split="train",
                        features=["ipfs_cid", "state_code", "source_id", "identifier", "name", "text", "jsonld"],
                        query_modes=["identifier_lookup", "jsonld_lookup"],
                    )
                ],
            )
        ],
    )

    result = query_canonical_legal_corpus(
        "state_laws",
        query_text="best interests of the child",
        state_code="MN",
        mode="lexical",
        allow_hf_fallback=True,
    )

    payload = canonical_corpus_query_result_to_dict(result)
    assert payload["mode"] == "lexical"
    assert payload["parquet_file"] == str(state_path)
    assert payload["results"]
    assert payload["results"][0]["row"]["identifier"] == "Minn. Stat. § 518.17"


def test_build_canonical_corpus_semantic_index_writes_embeddings_sidecar(tmp_path):
    state_path = tmp_path / "STATE-MN.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "ipfs_cid": "bafymn51817",
                    "state_code": "MN",
                    "source_id": "urn:state:mn:statute:518.17",
                    "identifier": "Minn. Stat. § 518.17",
                    "name": "Best interests of the child",
                    "text": "The best interests of the child means all relevant factors must be considered.",
                    "jsonld": '{"identifier":"Minn. Stat. § 518.17"}',
                }
            ]
        ),
        state_path,
    )

    result = canonical_corpus_index_build_result_to_dict(
        build_canonical_corpus_semantic_index(
            "state_laws",
            canonical_parquet_path=str(state_path),
            state_code="MN",
            build_faiss=False,
        )
    )

    assert result["row_count"] == 1
    assert result["join_field"] == "ipfs_cid"
    assert result["embeddings_parquet_path"].endswith("STATE-MN_embeddings.parquet")

    embeddings_rows = pq.read_table(result["embeddings_parquet_path"]).to_pylist()
    assert embeddings_rows[0]["ipfs_cid"] == "bafymn51817"
    assert embeddings_rows[0]["state_code"] == "MN"
    assert embeddings_rows[0]["semantic_text"]
    assert embeddings_rows[0]["embedding"]


def test_build_canonical_corpus_artifacts_writes_cid_bm25_and_knowledge_graph(tmp_path):
    state_path = tmp_path / "STATE-MN.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "state_code": "MN",
                    "source_id": "urn:state:mn:statute:518.17",
                    "identifier": "Minn. Stat. § 518.17",
                    "name": "Best interests of the child",
                    "text": "Section 518.17 requires considering the best interests of the child.",
                    "jsonld": '{"identifier":"Minn. Stat. § 518.17"}',
                }
            ]
        ),
        state_path,
    )

    result = canonical_corpus_artifact_build_result_to_dict(
        build_canonical_corpus_artifacts(
            "state_laws",
            canonical_parquet_path=str(state_path),
            state_code="MN",
            build_faiss=False,
        )
    )

    assert result["missing_join_values_filled"] == 1
    assert result["cid_index_path"].endswith("STATE-MN_cid_index.parquet")
    assert result["bm25_documents_path"].endswith("STATE-MN_bm25.parquet")
    assert result["knowledge_graph_entities_path"].endswith("STATE-MN_knowledge_graph_entities.parquet")
    assert result["knowledge_graph_relationships_path"].endswith("STATE-MN_knowledge_graph_relationships.parquet")
    assert result["semantic_index"]["embeddings_parquet_path"].endswith("STATE-MN_embeddings.parquet")

    canonical_rows = pq.read_table(result["updated_canonical_parquet_path"]).to_pylist()
    assert canonical_rows[0]["ipfs_cid"]

    cid_rows = pq.read_table(result["cid_index_path"]).to_pylist()
    assert cid_rows[0]["ipfs_cid"] == canonical_rows[0]["ipfs_cid"]
    assert cid_rows[0]["identifier"] == "Minn. Stat. § 518.17"

    bm25_rows = pq.read_table(result["bm25_documents_path"]).to_pylist()
    assert bm25_rows[0]["document_id"] == canonical_rows[0]["ipfs_cid"]

    kg_entities = pq.read_table(result["knowledge_graph_entities_path"]).to_pylist()
    kg_relationships = pq.read_table(result["knowledge_graph_relationships_path"]).to_pylist()
    assert any(entity["type"] == "legal_document" for entity in kg_entities)
    assert any(rel["type"] == "IDENTIFIED_BY" for rel in kg_relationships)


def test_rebuild_justicedao_dataset_library_can_use_local_overrides(tmp_path):
    state_path = tmp_path / "STATE-MN.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "ipfs_cid": "bafymn51817",
                    "state_code": "MN",
                    "source_id": "urn:state:mn:statute:518.17",
                    "identifier": "Minn. Stat. § 518.17",
                    "name": "Best interests of the child",
                    "text": "Section 518.17 requires considering the best interests of the child.",
                    "jsonld": '{"identifier":"Minn. Stat. § 518.17"}',
                }
            ]
        ),
        state_path,
    )

    result = justicedao_library_rebuild_result_to_dict(
        rebuild_justicedao_dataset_library(
            corpus_keys=["state_laws"],
            state_codes=["MN"],
            parquet_file_overrides={"state_laws": [str(state_path)]},
            allow_hf_download=False,
            build_faiss=False,
            max_files_per_corpus=1,
        )
    )

    assert result["success_count"] == 1
    assert result["failure_count"] == 0
    artifact = result["artifact_results"][0]
    assert artifact["corpus_key"] == "state_laws"
    assert artifact["row_count"] == 1
    assert artifact["cid_index_path"].endswith("STATE-MN_cid_index.parquet")


def test_build_canonical_corpus_artifacts_can_merge_llm_knowledge_graph_enrichment(tmp_path, monkeypatch):
    state_path = tmp_path / "STATE-MN.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "ipfs_cid": "bafymn51817",
                    "state_code": "MN",
                    "source_id": "urn:state:mn:statute:518.17",
                    "identifier": "Minn. Stat. § 518.17",
                    "name": "Best interests of the child",
                    "text": "The court shall consider the best interests of the child.",
                    "jsonld": '{"identifier":"Minn. Stat. § 518.17"}',
                }
            ]
        ),
        state_path,
    )

    def _fake_analysis(**_: object) -> RichDocumentAnalysis:
        return RichDocumentAnalysis(
            classification={"label": "statute", "backend": "llm_router"},
            entities=[{"id": "actor:court", "label": "Court", "type": "legal_actor"}],
            relationships=[{"source": "bafymn51817", "target": "actor:court", "type": "MENTIONS_ACTOR"}],
            deontic_statements=[],
            events=[],
            frames=[],
            propositions=[],
            temporal_formulas=[],
            dcec_formulas=[],
            summary="The statute directs the court to evaluate best interests.",
            provenance={"backend": "llm_router", "provider": "openai", "model_name": "gpt-test"},
        )

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.rich_docket_enrichment.analyze_document_with_routers",
        _fake_analysis,
    )

    result = canonical_corpus_artifact_build_result_to_dict(
        build_canonical_corpus_artifacts(
            "state_laws",
            canonical_parquet_path=str(state_path),
            state_code="MN",
            build_faiss=False,
            enable_llm_kg_enrichment=True,
            llm_max_rows=1,
            llm_max_chars=512,
            llm_provider="openai",
            llm_model_name="gpt-test",
        )
    )

    kg_entities = pq.read_table(result["knowledge_graph_entities_path"]).to_pylist()
    kg_relationships = pq.read_table(result["knowledge_graph_relationships_path"]).to_pylist()
    assert any(entity["id"] == "actor:court" for entity in kg_entities)
    assert any(rel["type"] == "MENTIONS_ACTOR" for rel in kg_relationships)
    assert result["llm_knowledge_graph_summary"]["analyzed_document_count"] == 1
    assert result["llm_knowledge_graph_summary"]["providers"] == ["openai"]
    assert result["llm_knowledge_graph_summary"]["model_names"] == ["gpt-test"]
    assert result["llm_knowledge_graph_summary"]["sampled_rows"][0]["document_id"] == "bafymn51817"


def test_build_canonical_corpus_artifacts_records_llm_failure_diagnostics(tmp_path, monkeypatch):
    state_path = tmp_path / "STATE-MN.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "ipfs_cid": "bafymnfail",
                    "state_code": "MN",
                    "source_id": "urn:state:mn:statute:test",
                    "identifier": "Minn. Stat. § test",
                    "name": "Failure sample",
                    "text": "The court shall issue an order.",
                    "jsonld": '{"identifier":"Minn. Stat. § test"}',
                }
            ]
        ),
        state_path,
    )

    def _fake_failure(**_: object):
        return None, {
            "status": "no_semantic_payload",
            "provider_name": "local",
            "model_name": "tiny-test",
            "raw_response_preview": '{"classification":{"label":"other"}}',
        }

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.rich_docket_enrichment.analyze_document_with_routers",
        _fake_failure,
    )

    result = canonical_corpus_artifact_build_result_to_dict(
        build_canonical_corpus_artifacts(
            "state_laws",
            canonical_parquet_path=str(state_path),
            state_code="MN",
            build_faiss=False,
            enable_llm_kg_enrichment=True,
            llm_max_rows=1,
        )
    )

    failure = result["llm_knowledge_graph_summary"]["failed_samples"][0]
    assert failure["document_id"] == "bafymnfail"
    assert failure["status"] == "no_semantic_payload"
    assert failure["provider_name"] == "local"
    assert failure["model_name"] == "tiny-test"


def test_select_rows_for_llm_knowledge_graph_prefers_substantive_legal_text():
    selected = _select_rows_for_llm_knowledge_graph(
        [
            {
                "ipfs_cid": "thin",
                "name": "Short heading",
                "text": "Index.",
            },
            {
                "ipfs_cid": "rich",
                "name": "Jurisdiction and remedies",
                "text": (
                    "The court shall have jurisdiction over the action. "
                    "This section defines remedies, penalties, and required procedures."
                ),
            },
        ],
        corpus_key=None,
        title_fields=["name"],
        text_fields=["text"],
        max_rows=1,
    )

    assert len(selected) == 1
    assert selected[0]["ipfs_cid"] == "rich"


def test_select_rows_for_llm_knowledge_graph_penalizes_reference_titles():
    selected = _select_rows_for_llm_knowledge_graph(
        [
            {
                "ipfs_cid": "glossary",
                "name": "Glossary of Legislative Terms",
                "text": "A very long glossary entry " * 200,
            },
            {
                "ipfs_cid": "statute",
                "name": "Child custody factors",
                "text": "The court shall consider statutory factors and required procedures.",
            },
        ],
        corpus_key=None,
        title_fields=["name"],
        text_fields=["text"],
        max_rows=1,
    )

    assert len(selected) == 1
    assert selected[0]["ipfs_cid"] == "statute"


def test_select_rows_for_llm_knowledge_graph_penalizes_state_laws_navigation_content():
    selected = _select_rows_for_llm_knowledge_graph(
        [
            {
                "ipfs_cid": "nav",
                "identifier": "",
                "source_id": "urn:state:ak:statute:Alaska Statutes § Section-31",
                "name": "Statutes",
                "text": "home senate house bills & laws media center publications get started This page is no longer used please use www.akleg.gov Search 34th Legislature(2025-2026)",
            },
            {
                "ipfs_cid": "body",
                "identifier": "Alaska Stat. § 12.55.005",
                "source_id": "urn:state:ak:statute:12.55.005",
                "name": "Sentencing criteria",
                "text": "The court shall consider the seriousness of the defendant's conduct and the prior criminal history when imposing sentence.",
            },
        ],
        corpus_key="state_laws",
        title_fields=["name", "identifier"],
        text_fields=["text", "identifier"],
        max_rows=1,
    )

    assert len(selected) == 1
    assert selected[0]["ipfs_cid"] == "body"


def test_build_canonical_corpus_artifacts_reports_degraded_state_laws_quality(tmp_path):
    state_path = tmp_path / "STATE-AK.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "ipfs_cid": "nav1",
                    "identifier": "",
                    "source_id": "urn:state:ak:statute:Alaska Statutes § Section-31",
                    "name": "Statutes",
                    "text": "home senate house bills & laws media center publications get started This page is no longer used please use www.akleg.gov Search 34th Legislature(2025-2026)",
                },
                {
                    "ipfs_cid": "nav2",
                    "identifier": "",
                    "source_id": "urn:state:ak:statute:Alaska Statutes § Section-35",
                    "name": "Journals",
                    "text": "Home 34th Legislature(2025 - 2026) 33rd Legislature(2023 - 2024)",
                },
                {
                    "ipfs_cid": "body",
                    "identifier": "Alaska Stat. § 12.55.005",
                    "source_id": "urn:state:ak:statute:12.55.005",
                    "name": "Sentencing criteria",
                    "text": "The court shall consider the seriousness of the defendant's conduct.",
                },
            ]
        ),
        state_path,
    )

    result = canonical_corpus_artifact_build_result_to_dict(
        build_canonical_corpus_artifacts(
            "state_laws",
            canonical_parquet_path=str(state_path),
            state_code="AK",
            build_faiss=False,
        )
    )

    quality = result["corpus_quality_summary"]
    assert quality["status"] == "degraded"
    assert "navigation_like_content_dominates" in quality["issues"]
    assert quality["navigation_like_row_count"] == 2
    recommendation = result["recovery_recommendation"]
    assert recommendation["recommended_action"] == "recover_source_rows"
    assert recommendation["dataset_id"] == "justicedao/ipfs_state_laws"
    assert recommendation["state_code"] == "AK"
    assert "statutes" in recommendation["recovery_query"].lower()
    draft = result["recovery_manifest_draft"]
    assert draft["manifest_path"].endswith("recovery_manifest.json")
    assert draft["promotion_preview"]["hf_dataset_id"] == "justicedao/ipfs_state_laws"
    assert draft["promotion_preview"]["state_code"] == "AK"


def test_build_canonical_corpus_artifacts_can_execute_degraded_recovery(tmp_path, monkeypatch):
    state_path = tmp_path / "STATE-AK.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "ipfs_cid": "nav1",
                    "identifier": "",
                    "source_id": "urn:state:ak:statute:Alaska Statutes § Section-31",
                    "name": "Statutes",
                    "text": "home senate house bills & laws media center publications get started This page is no longer used please use www.akleg.gov Search 34th Legislature(2025-2026)",
                }
            ]
        ),
        state_path,
    )

    async def _fake_recover_missing_legal_citation_source(**kwargs):
        return {
            "status": "tracked",
            "citation_text": kwargs.get("citation_text"),
            "corpus_key": kwargs.get("corpus_key"),
            "state_code": kwargs.get("state_code"),
            "candidate_count": 0,
            "archived_count": 0,
        }

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.justicedao_dataset_inventory.recover_missing_legal_citation_source",
        _fake_recover_missing_legal_citation_source,
    )

    result = canonical_corpus_artifact_build_result_to_dict(
        build_canonical_corpus_artifacts(
            "state_laws",
            canonical_parquet_path=str(state_path),
            state_code="AK",
            build_faiss=False,
            execute_recovery_for_degraded_corpora=True,
            recovery_max_candidates=2,
            recovery_archive_top_k=0,
        )
    )

    recovery_execution = result["recovery_execution"]
    assert recovery_execution["status"] == "tracked"
    assert recovery_execution["corpus_key"] == "state_laws"
    assert recovery_execution["state_code"] == "AK"


def test_build_justicedao_rebuild_plan_batches_targets_from_profiles():
    profiles = [
        DatasetProfile(
            dataset_id="justicedao/ipfs_state_laws",
            canonical_corpus_key="state_laws",
            legal_branch="us",
            country_codes=["US"],
            parquet_files=["state_laws_parquet_cid/STATE-OR.parquet", "state_laws_parquet_cid/STATE-WA.parquet"],
            top_level_paths=["state_laws_parquet_cid"],
            configs=[],
        ),
        DatasetProfile(
            dataset_id="justicedao/ipfs_uscode",
            canonical_corpus_key="us_code",
            legal_branch="us",
            country_codes=["US"],
            parquet_files=["uscode_parquet/laws.parquet"],
            top_level_paths=["uscode_parquet"],
            configs=[],
        ),
        DatasetProfile(
            dataset_id="justicedao/ipfs_federal_register",
            canonical_corpus_key="federal_register",
            legal_branch="us",
            country_codes=["US"],
            parquet_files=["federal_register.parquet"],
            top_level_paths=["federal_register.parquet"],
            configs=[],
        ),
    ]
    plan = build_justicedao_rebuild_plan(
        profiles=profiles,
        corpus_keys=["state_laws", "us_code", "federal_register"],
        state_codes=["OR"],
        batch_size=2,
        max_files_per_corpus=2,
    )

    targets = plan.targets
    assert targets
    assert any(isinstance(item, JusticeDAORebuildTarget) for item in targets)
    assert any(item.corpus_key == "us_code" for item in targets)
    assert any(item.corpus_key == "federal_register" for item in targets)
    assert any(item.corpus_key == "state_laws" and item.state_code == "OR" for item in targets)
    assert len(plan.batches) >= 1
    assert sum(len(batch) for batch in plan.batches) == len(plan.targets)
    assert plan.recommendations == []


def test_build_justicedao_rebuild_plan_can_include_observed_germany_laws_targets():
    profiles = [
        DatasetProfile(
            dataset_id="justicedao/ipfs_germany_laws",
            canonical_corpus_key="germany_laws",
            legal_branch="eu",
            country_codes=["DE"],
            parquet_files=["parquet/laws/train-00000-of-00001.parquet"],
            top_level_paths=["parquet"],
            configs=[],
        )
    ]

    plan = build_justicedao_rebuild_plan(
        profiles=profiles,
        corpus_keys=["germany_laws"],
        batch_size=1,
    )

    assert len(plan.targets) == 1
    assert plan.targets[0].corpus_key == "germany_laws"
    assert plan.targets[0].dataset_id == "justicedao/ipfs_germany_laws"
    assert plan.targets[0].parquet_path == "parquet/laws/train-00000-of-00001.parquet"
    assert plan.recommendations == []


def test_build_justicedao_rebuild_plan_can_include_observed_france_laws_targets():
    profiles = [
        DatasetProfile(
            dataset_id="justicedao/ipfs_france_laws",
            canonical_corpus_key="france_laws",
            legal_branch="eu",
            country_codes=["FR"],
            parquet_files=["parquet/laws/train-00000-of-00001.parquet"],
            top_level_paths=["parquet"],
            configs=[],
        )
    ]

    plan = build_justicedao_rebuild_plan(
        profiles=profiles,
        corpus_keys=["france_laws"],
        batch_size=1,
    )

    assert len(plan.targets) == 1
    assert plan.targets[0].corpus_key == "france_laws"
    assert plan.targets[0].dataset_id == "justicedao/ipfs_france_laws"
    assert plan.targets[0].parquet_path == "parquet/laws/train-00000-of-00001.parquet"
    assert plan.recommendations == []


def test_build_justicedao_rebuild_plan_can_include_observed_spain_laws_targets():
    profiles = [
        DatasetProfile(
            dataset_id="justicedao/ipfs_spain_laws",
            canonical_corpus_key="spain_laws",
            legal_branch="eu",
            country_codes=["ES"],
            parquet_files=["parquet/laws/train-00000-of-00001.parquet"],
            top_level_paths=["parquet"],
            configs=[],
        )
    ]

    plan = build_justicedao_rebuild_plan(
        profiles=profiles,
        corpus_keys=["spain_laws"],
        batch_size=1,
    )

    assert len(plan.targets) == 1
    assert plan.targets[0].corpus_key == "spain_laws"
    assert plan.targets[0].dataset_id == "justicedao/ipfs_spain_laws"
    assert plan.targets[0].parquet_path == "parquet/laws/train-00000-of-00001.parquet"
    assert plan.recommendations == []


def test_build_justicedao_rebuild_plan_includes_eu_onboarding_recommendations_when_not_corpus_scoped():
    plan = build_justicedao_rebuild_plan(
        profiles=_profiles(),
        batch_size=2,
    )

    assert any(isinstance(item, JusticeDAORebuildRecommendation) for item in plan.recommendations)
    reasons = {item.country_code: item.reason for item in plan.recommendations}
    statuses = {item.country_code: item.status for item in plan.recommendations}
    assert reasons["DE"] == "canonical_registered_but_unobserved"
    assert statuses["DE"] == "registered"
    assert reasons["FR"] == "canonical_registered_but_unobserved"
    assert statuses["FR"] == "registered"
    assert reasons["ES"] == "canonical_registered_but_unobserved"
    assert statuses["ES"] == "registered"

    payload = justicedao_rebuild_plan_to_dict(plan)
    assert payload["recommendation_count"] == len(plan.recommendations)
    assert any(item["country_code"] == "DE" for item in payload["recommendations"])
    assert any(item["country_code"] == "FR" for item in payload["recommendations"])
    assert any(item["country_code"] == "ES" for item in payload["recommendations"])


def test_render_justicedao_rebuild_plan_markdown_includes_targets_batches_and_recommendations():
    plan = build_justicedao_rebuild_plan(
        profiles=_profiles(),
        batch_size=2,
    )

    markdown = render_justicedao_rebuild_plan_markdown(plan)

    assert "# JusticeDAO Rebuild Plan" in markdown
    assert "## Rebuild Targets" in markdown
    assert "## Batches" in markdown
    assert "## Recommendations" in markdown
    assert "DE: canonical registry includes germany_laws; awaiting observed datasets" in markdown
    assert "FR: canonical registry includes france_laws; awaiting observed datasets" in markdown
    assert "ES: canonical registry includes spain_laws; awaiting observed datasets" in markdown
