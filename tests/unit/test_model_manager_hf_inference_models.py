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
