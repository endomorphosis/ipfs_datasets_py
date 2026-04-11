from __future__ import annotations

from ipfs_datasets_py.processors.legal_scrapers.canonical_legal_corpora import (
    build_missing_eu_corpus_proposals,
    build_canonical_corpus_branch_map,
    build_canonical_corpus_local_root_overrides,
    get_canonical_legal_corpus,
    get_canonical_legal_corpus_for_dataset_id,
    infer_canonical_legal_corpus_for_dataset_id,
    infer_proposed_eu_corpus_for_dataset_id,
    list_canonical_legal_corpora_by_branch,
    list_canonical_legal_corpora_by_country,
)


def test_canonical_registry_includes_justice_dao_us_code_and_cap_datasets():
    us_code = get_canonical_legal_corpus("us_code")
    cap = get_canonical_legal_corpus("caselaw_access_project")

    assert us_code.hf_dataset_id == "justicedao/ipfs_uscode"
    assert us_code.parquet_dir_name == "uscode_parquet"
    assert us_code.combined_parquet_path() == "uscode_parquet/uscode.parquet"

    assert cap.hf_dataset_id == "justicedao/ipfs_caselaw_access_project"
    assert cap.combined_parquet_path() == "embeddings/ipfs_TeraflopAI___Caselaw_Access_Project.parquet"
    assert cap.combined_embeddings_path() == "embeddings/sparse_chunks.parquet"


def test_canonical_registry_can_resolve_by_hf_dataset_id_case_insensitively():
    corpus = get_canonical_legal_corpus_for_dataset_id("JUSTICEDAO/IPFS_STATE_LAWS")
    assert corpus.key == "state_laws"


def test_canonical_registry_can_infer_alias_and_sidecar_dataset_ids():
    assert infer_canonical_legal_corpus_for_dataset_id("justicedao/caselaw_access_project").key == "caselaw_access_project"
    assert infer_canonical_legal_corpus_for_dataset_id("justicedao/dedup_ipfs_caselaw_access_project").key == "caselaw_access_project"
    assert infer_canonical_legal_corpus_for_dataset_id("justicedao/american_municipal_law").key == "state_laws"
    assert infer_canonical_legal_corpus_for_dataset_id("justicedao/ipfs_france_laws_bm25_index").key == "france_laws"
    assert infer_canonical_legal_corpus_for_dataset_id("justicedao/ipfs_spain_laws_bm25_index").key == "spain_laws"
    assert infer_canonical_legal_corpus_for_dataset_id("justicedao/ipfs_germany_laws_bm25_index").key == "germany_laws"
    assert infer_canonical_legal_corpus_for_dataset_id("justicedao/ipfs_netherlands_laws_bm25_index").key == "netherlands_laws"


def test_build_canonical_corpus_local_root_overrides_supports_custom_env_names():
    env = {
        "BLUEBOOK_REAL_US_CODE_ROOT": "/datasets/uscode",
        "BLUEBOOK_REAL_STATE_LAWS_ROOT": "/datasets/state-laws",
        "IGNORED_ENV": "/tmp/nope",
    }
    overrides = build_canonical_corpus_local_root_overrides(
        env=env,
        env_var_by_corpus_key={
            "us_code": "BLUEBOOK_REAL_US_CODE_ROOT",
            "state_laws": "BLUEBOOK_REAL_STATE_LAWS_ROOT",
        },
    )

    assert overrides == {
        "us_code": "/datasets/uscode",
        "state_laws": "/datasets/state-laws",
    }


def test_canonical_legal_corpora_are_partitioned_by_us_and_eu_branch():
    us_corpora = list_canonical_legal_corpora_by_branch("us")
    eu_corpora = list_canonical_legal_corpora_by_branch("eu")

    assert any(corpus.key == "us_code" for corpus in us_corpora)
    assert any(corpus.key == "state_laws" for corpus in us_corpora)
    assert [corpus.key for corpus in eu_corpora] == ["france_laws", "germany_laws", "netherlands_laws", "spain_laws"]


def test_canonical_legal_corpora_can_be_listed_by_country_code():
    us_keys = {corpus.key for corpus in list_canonical_legal_corpora_by_country("US")}
    fr_keys = [corpus.key for corpus in list_canonical_legal_corpora_by_country("FR")]
    es_keys = [corpus.key for corpus in list_canonical_legal_corpora_by_country("ES")]
    de_keys = [corpus.key for corpus in list_canonical_legal_corpora_by_country("DE")]
    nl_keys = [corpus.key for corpus in list_canonical_legal_corpora_by_country("NL")]

    assert "caselaw_access_project" in us_keys
    assert "federal_register" in us_keys
    assert fr_keys == ["france_laws"]
    assert es_keys == ["spain_laws"]
    assert de_keys == ["germany_laws"]
    assert nl_keys == ["netherlands_laws"]


def test_canonical_corpus_branch_map_summarizes_registry():
    branch_map = build_canonical_corpus_branch_map()
    france = get_canonical_legal_corpus("france_laws")
    spain = get_canonical_legal_corpus("spain_laws")
    germany = get_canonical_legal_corpus("germany_laws")
    netherlands = get_canonical_legal_corpus("netherlands_laws")

    assert branch_map["us"]
    assert branch_map["eu"] == ["france_laws", "germany_laws", "netherlands_laws", "spain_laws"]
    assert france.legal_branch == "eu"
    assert france.country_codes == ("FR",)
    assert spain.legal_branch == "eu"
    assert spain.country_codes == ("ES",)
    assert germany.legal_branch == "eu"
    assert germany.country_codes == ("DE",)
    assert netherlands.legal_branch == "eu"
    assert netherlands.country_codes == ("NL",)


def test_build_missing_eu_corpus_proposals_covers_supported_unregistered_member_states():
    proposals = build_missing_eu_corpus_proposals()

    assert proposals == {}


def test_infer_proposed_eu_corpus_for_dataset_id_matches_base_and_sidecar_datasets():
    import pytest

    with pytest.raises(KeyError):
        infer_proposed_eu_corpus_for_dataset_id("justicedao/ipfs_spain_laws_bm25_index")


def test_build_canonical_corpus_local_root_overrides_supports_shared_data_root():
    overrides = build_canonical_corpus_local_root_overrides(
        env={
            "BLUEBOOK_REAL_DATA_ROOT": "/mirror-root",
        },
        env_var_by_corpus_key={
            "us_code": "BLUEBOOK_REAL_US_CODE_ROOT",
            "state_laws": "BLUEBOOK_REAL_STATE_LAWS_ROOT",
        },
        data_root_env_name="BLUEBOOK_REAL_DATA_ROOT",
    )

    assert overrides["us_code"].endswith("/mirror-root/uscode/uscode_parquet")
    assert overrides["state_laws"].endswith("/mirror-root/state_laws/state_laws_parquet_cid")