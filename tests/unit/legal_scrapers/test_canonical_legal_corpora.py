from __future__ import annotations

from ipfs_datasets_py.processors.legal_scrapers.canonical_legal_corpora import (
    build_canonical_corpus_local_root_overrides,
    get_canonical_legal_corpus,
    get_canonical_legal_corpus_for_dataset_id,
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