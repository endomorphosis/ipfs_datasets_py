from __future__ import annotations

import json

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


def _install_fake_live_registry(monkeypatch) -> None:
    model_manager._get_hf_inference_model_manager_cached.cache_clear()
    model_manager._load_ipfs_accelerate_model_manager_bindings.cache_clear()

    monkeypatch.setattr(
        model_manager,
        "_discover_live_hf_inference_model_specs",
        lambda model_kind=None: [
            {
                "model_id": "katanemo/Arch-Router-1.5B",
                "pipeline_tag": "text-generation",
                "model_kind": "llm",
                "description": "live llm",
                "live_discovered": True,
            },
            {
                "model_id": "facebook/bart-large-cnn",
                "pipeline_tag": "summarization",
                "model_kind": "llm",
                "description": "live summarizer",
                "live_discovered": True,
            },
            {
                "model_id": "google/pegasus-xsum",
                "pipeline_tag": "summarization",
                "model_kind": "llm",
                "description": "live pegasus",
                "live_discovered": True,
            },
            {
                "model_id": "sshleifer/distilbart-cnn-12-6",
                "pipeline_tag": "summarization",
                "model_kind": "llm",
                "description": "live distilbart",
                "live_discovered": True,
            },
            {
                "model_id": "BAAI/bge-small-en-v1.5",
                "pipeline_tag": "feature-extraction",
                "model_kind": "embedding",
                "description": "live embedding",
                "live_discovered": True,
            },
            {
                "model_id": "sentence-transformers/all-MiniLM-L6-v2",
                "pipeline_tag": "feature-extraction",
                "model_kind": "embedding",
                "description": "live sentence transformer",
                "live_discovered": True,
            },
            {
                "model_id": "thenlper/gte-small",
                "pipeline_tag": "feature-extraction",
                "model_kind": "embedding",
                "description": "live gte",
                "live_discovered": True,
            },
        ],
    )
    monkeypatch.setattr(
        model_manager,
        "_load_ipfs_accelerate_model_manager_bindings",
        lambda: model_manager._ModelManagerBindings(
            ModelManager=model_manager._CompatModelManager,
            ModelMetadata=model_manager._CompatModelMetadata,
            ModelType=model_manager._CompatModelType,
            DataType=model_manager._CompatDataType,
            IOSpec=model_manager._CompatIOSpec,
            source="compat-test",
        ),
    )


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


def test_hf_inference_models_are_registered_in_rich_model_manager(monkeypatch) -> None:
    _install_fake_live_registry(monkeypatch)
    manager = model_manager.get_hf_inference_model_manager(use_cache=False, persist=False)

    for model_id in EXPECTED_LLM_MODELS.union(EXPECTED_EMBEDDING_MODELS):
        assert manager.get_model(model_id) is not None


def test_list_hf_inference_models_supports_kind_filter(monkeypatch) -> None:
    _install_fake_live_registry(monkeypatch)

    llm_records = model_manager.list_hf_inference_models(model_kind="llm")
    emb_records = model_manager.list_hf_inference_models(model_kind="embedding")

    llm_ids = {item["model_id"] for item in llm_records}
    emb_ids = {item["model_id"] for item in emb_records}

    assert EXPECTED_LLM_MODELS.issubset(llm_ids)
    assert EXPECTED_EMBEDDING_MODELS.issubset(emb_ids)


def test_get_hf_inference_model_metadata_returns_queryable_fields(monkeypatch) -> None:
    _install_fake_live_registry(monkeypatch)

    meta = model_manager.get_hf_inference_model_metadata("BAAI/bge-small-en-v1.5")

    assert meta is not None
    assert meta["inference_provider"] == "hf-inference"
    assert meta["pipeline_tag"] == "feature-extraction"
    assert "hf_inference_api" in meta["supported_backends"]


def test_rich_model_manager_does_not_persist_by_default(monkeypatch, tmp_path) -> None:
    _install_fake_live_registry(monkeypatch)
    runtime_path = tmp_path / "hf_runtime.json"
    monkeypatch.setattr(model_manager, "_project_runtime_metadata_path", lambda: str(runtime_path))

    _ = model_manager.get_hf_inference_model_manager(use_cache=False, persist=False)

    assert not runtime_path.exists()


def test_build_hf_inference_ipld_document_contains_expected_shape(monkeypatch) -> None:
    _install_fake_live_registry(monkeypatch)
    doc = model_manager.build_hf_inference_ipld_document()

    assert doc["kind"] == "ipfs_datasets_py.hf_inference_model_registry"
    assert doc["schema_version"] == "1.0"
    assert isinstance(doc["models"], list)
    assert doc["count"] == len(doc["models"])


def test_get_hf_inference_ipld_cid_is_deterministic_for_same_data(monkeypatch) -> None:
    _install_fake_live_registry(monkeypatch)
    cid1 = model_manager.get_hf_inference_ipld_cid(model_kind="embedding")
    cid2 = model_manager.get_hf_inference_ipld_cid(model_kind="embedding")

    assert isinstance(cid1, str)
    assert cid1 == cid2


def test_publish_and_load_hf_inference_ipld_via_ipfs_backend_instance(monkeypatch) -> None:
    _install_fake_live_registry(monkeypatch)
    store = {}

    class _FakeBackend:
        def add_bytes(self, data: bytes, *, pin: bool = True) -> str:
            _ = pin
            cid = f"fakecid-{len(store) + 1}"
            store[cid] = bytes(data)
            return cid

        def cat(self, cid: str) -> bytes:
            return store[cid]

    backend = _FakeBackend()

    published = model_manager.publish_hf_inference_ipld_to_ipfs(
        model_kind="llm",
        backend_instance=backend,
    )
    assert published["status"] == "success"
    assert published["ipfs_cid"].startswith("fakecid-")
    assert isinstance(published["local_cid"], str)

    loaded = model_manager.load_hf_inference_ipld_from_ipfs(
        published["ipfs_cid"],
        backend_instance=backend,
    )
    assert loaded["kind"] == "ipfs_datasets_py.hf_inference_model_registry"
    assert loaded["model_kind"] == "llm"
    assert loaded["count"] == len(loaded["models"])


def test_load_hf_inference_ipld_rejects_wrong_document_kind() -> None:
    class _FakeBackend:
        def cat(self, cid: str) -> bytes:
            _ = cid
            return json.dumps({"kind": "other"}).encode("utf-8")

    try:
        _ = model_manager.load_hf_inference_ipld_from_ipfs("fakecid", backend_instance=_FakeBackend())
        assert False, "Expected ValueError for invalid kind"
    except ValueError:
        pass
