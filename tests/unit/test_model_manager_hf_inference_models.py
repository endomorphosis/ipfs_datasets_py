from __future__ import annotations

from ipfs_datasets_py.utils import model_manager


EXPECTED_LLM_MODELS = {
    "katanemo/Arch-Router-1.5B",
    "facebook/bart-large-cnn",
    "google/pegasus-xsum",
    "sshleifer/distilbart-cnn-12-6",
}

EXPECTED_EMBEDDING_MODELS = {
    "BAAI/bge-small-en-v1.5",
    "sentence-transformers/all-MiniLM-L6-v2",
    "thenlper/gte-small",
}


def test_default_config_includes_hf_inference_provider_model_lists() -> None:
    cfg = model_manager._DEFAULT_CONFIG

    llm = set(cfg["hf_inference_provider_llm_models"])
    emb = set(cfg["hf_inference_provider_embedding_models"])
    combined = set(cfg["hf_inference_provider_models"])
    hf_models = set(cfg["hf_models"])

    assert EXPECTED_LLM_MODELS.issubset(llm)
    assert EXPECTED_EMBEDDING_MODELS.issubset(emb)
    assert EXPECTED_LLM_MODELS.issubset(combined)
    assert EXPECTED_EMBEDDING_MODELS.issubset(combined)
    assert combined.issubset(hf_models)


def test_load_model_config_keeps_hf_inference_provider_defaults_when_no_file(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "missing_model_config.json"
    monkeypatch.setenv("IPFS_DATASETS_PY_MODEL_CONFIG", str(config_path))

    cfg = model_manager.load_model_config()

    llm = set(cfg["hf_inference_provider_llm_models"])
    emb = set(cfg["hf_inference_provider_embedding_models"])
    combined = set(cfg["hf_inference_provider_models"])

    assert EXPECTED_LLM_MODELS.issubset(llm)
    assert EXPECTED_EMBEDDING_MODELS.issubset(emb)
    assert EXPECTED_LLM_MODELS.union(EXPECTED_EMBEDDING_MODELS).issubset(combined)


def test_hf_inference_models_are_registered_in_rich_model_manager() -> None:
    model_manager._get_hf_inference_model_manager_cached.cache_clear()
    manager = model_manager.get_hf_inference_model_manager(use_cache=False, persist=False)

    for model_id in EXPECTED_LLM_MODELS.union(EXPECTED_EMBEDDING_MODELS):
        assert manager.get_model(model_id) is not None


def test_list_hf_inference_models_supports_kind_filter() -> None:
    model_manager._get_hf_inference_model_manager_cached.cache_clear()

    llm_records = model_manager.list_hf_inference_models(model_kind="llm")
    emb_records = model_manager.list_hf_inference_models(model_kind="embedding")

    llm_ids = {item["model_id"] for item in llm_records}
    emb_ids = {item["model_id"] for item in emb_records}

    assert EXPECTED_LLM_MODELS.issubset(llm_ids)
    assert EXPECTED_EMBEDDING_MODELS.issubset(emb_ids)


def test_get_hf_inference_model_metadata_returns_queryable_fields() -> None:
    model_manager._get_hf_inference_model_manager_cached.cache_clear()

    meta = model_manager.get_hf_inference_model_metadata("BAAI/bge-small-en-v1.5")

    assert meta is not None
    assert meta["inference_provider"] == "hf-inference"
    assert meta["pipeline_tag"] == "feature-extraction"
    assert "hf_inference_api" in meta["supported_backends"]


def test_rich_model_manager_does_not_persist_by_default(monkeypatch, tmp_path) -> None:
    runtime_path = tmp_path / "hf_runtime.json"
    model_manager._get_hf_inference_model_manager_cached.cache_clear()
    monkeypatch.setattr(model_manager, "_project_runtime_metadata_path", lambda: str(runtime_path))

    _ = model_manager.get_hf_inference_model_manager(use_cache=False, persist=False)

    assert not runtime_path.exists()
