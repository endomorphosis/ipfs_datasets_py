"""Model selection config utilities."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional
from functools import lru_cache


# Curated models that are known to be exposed via Hugging Face Inference Providers.
_HF_INFERENCE_PROVIDER_LLM_MODELS: List[str] = [
    "katanemo/Arch-Router-1.5B",
    "facebook/bart-large-cnn",
    "google/pegasus-xsum",
    "sshleifer/distilbart-cnn-12-6",
]

_HF_INFERENCE_PROVIDER_EMBEDDING_MODELS: List[str] = [
    "BAAI/bge-small-en-v1.5",
    "sentence-transformers/all-MiniLM-L6-v2",
    "thenlper/gte-small",
]

_HF_INFERENCE_PROVIDER_MODELS: List[str] = list(
    dict.fromkeys(_HF_INFERENCE_PROVIDER_LLM_MODELS + _HF_INFERENCE_PROVIDER_EMBEDDING_MODELS)
)

_DEFAULT_CONFIG: Dict[str, Any] = {
    "copilot_cli_models": [
        "gpt-5-mini",
        "gpt-5.2-codex",
        "gpt-5.2",
        "gpt-5.1-codex-max",
        "gpt-5.1-codex",
        "gpt-5.1",
        "gpt-5.1-codex-mini",
        "gpt-5",
        "gpt-4.1",
        "gemini-3-pro-preview",
        "claude-sonnet-4.5",
        "claude-haiku-4.5",
        "claude-opus-4.5",
        "claude-sonnet-4",
    ],
    "copilot_sdk_models": [
        "gpt-5-mini",
        "gpt-5.2-codex",
        "gpt-5.2",
        "gpt-5.1-codex-max",
        "gpt-5.1-codex",
        "gpt-5.1",
        "gpt-5.1-codex-mini",
        "gpt-5",
        "gpt-4.1",
        "gemini-3-pro-preview",
        "claude-sonnet-4.5",
        "claude-haiku-4.5",
        "claude-opus-4.5",
        "claude-sonnet-4",
    ],
    "hf_models": [
        *_HF_INFERENCE_PROVIDER_MODELS,
        "Qwen/Qwen3-1.7B-Thinker",
    ],
    "hf_inference_provider_llm_models": [
        *_HF_INFERENCE_PROVIDER_LLM_MODELS,
    ],
    "hf_inference_provider_embedding_models": [
        *_HF_INFERENCE_PROVIDER_EMBEDDING_MODELS,
    ],
    "hf_inference_provider_models": [
        *_HF_INFERENCE_PROVIDER_MODELS,
    ],
    "codex_models": [
        "gpt-5.2-codex",
        "gpt-5.1-codex-mini",
        "gpt-5.1-codex-max",
        "gpt-5.2",
        "gpt-5.1",
        "gpt-5.1-codex",
        "gpt-5-codex",
        "gpt-5-codex-mini",
        "gpt-5",
    ],
    "backends": [
        "codex",
        "copilot_sdk",
        "copilot_cli",
        "gemini_cli",
        "claude_code",
        "gemini_py",
        "claude_py",
        "huggingface",
        "ipfs_accelerate_py",
    ],
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_config_path() -> Path:
    override = os.environ.get("IPFS_DATASETS_PY_MODEL_CONFIG")
    if override:
        return Path(override).expanduser().resolve()
    return _project_root() / "outputs" / "model_config.json"


def load_model_config() -> Dict[str, Any]:
    path = get_config_path()
    if not path.exists():
        return json.loads(json.dumps(_DEFAULT_CONFIG))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return json.loads(json.dumps(_DEFAULT_CONFIG))
    merged = json.loads(json.dumps(_DEFAULT_CONFIG))
    for key, value in data.items():
        merged[key] = value
    return merged


def save_model_config(config: Dict[str, Any]) -> Path:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return path


def update_model_list(key: str, models: List[str]) -> Dict[str, Any]:
    config = load_model_config()
    config[key] = models
    save_model_config(config)
    return config


def _project_runtime_metadata_path() -> str:
    return str(_project_root() / "outputs" / "hf_inference_model_metadata.runtime.json")


def _build_hf_inference_model_specs() -> List[Dict[str, str]]:
    specs: List[Dict[str, str]] = []
    for model_id in _HF_INFERENCE_PROVIDER_LLM_MODELS:
        specs.append(
            {
                "model_id": model_id,
                "pipeline_tag": "text-generation",
                "model_kind": "llm",
                "description": "Curated Hugging Face Inference Providers text-generation model",
            }
        )

    for model_id in _HF_INFERENCE_PROVIDER_EMBEDDING_MODELS:
        specs.append(
            {
                "model_id": model_id,
                "pipeline_tag": "feature-extraction",
                "model_kind": "embedding",
                "description": "Curated Hugging Face Inference Providers embedding model",
            }
        )
    return specs


@lru_cache(maxsize=1)
def _get_hf_inference_model_manager_cached() -> object:
    return _create_hf_inference_model_manager(persist=False)


def _create_hf_inference_model_manager(*, persist: bool) -> object:
    """Create and seed rich model metadata manager for HF Inference providers.

    This uses the `ipfs_accelerate_py.model_manager.ModelManager` metadata graph
    when available, and intentionally defaults to non-persistent mode.
    """

    from ipfs_accelerate_py.model_manager import (  # type: ignore
        DataType,
        IOSpec,
        ModelManager,
        ModelMetadata,
        ModelType,
    )

    manager = ModelManager(
        storage_path=_project_runtime_metadata_path(),
        use_database=False,
        enable_ipfs=False,
    )

    if not persist:
        # Keep this manager query-only for selection decisions.
        manager._save_data = lambda: None  # type: ignore[attr-defined]

    for spec in _build_hf_inference_model_specs():
        model_id = spec["model_id"]
        model_kind = spec["model_kind"]
        pipeline_tag = spec["pipeline_tag"]
        is_embedding = model_kind == "embedding"

        metadata = ModelMetadata(
            model_id=model_id,
            model_name=model_id.split("/")[-1],
            model_type=ModelType.EMBEDDING_MODEL if is_embedding else ModelType.LANGUAGE_MODEL,
            architecture="transformer",
            inputs=[IOSpec(name="input", data_type=DataType.TEXT, description="Input text")],
            outputs=[
                IOSpec(
                    name="embeddings" if is_embedding else "text",
                    data_type=DataType.EMBEDDINGS if is_embedding else DataType.TEXT,
                    description="Model output",
                )
            ],
            huggingface_config={
                "inference_provider": "hf-inference",
                "pipeline_tag": pipeline_tag,
                "known_available": True,
            },
            supported_backends=["hf_inference_api", "huggingface_inference"],
            tags=["huggingface", "hf-inference", pipeline_tag, model_kind],
            source_url=f"https://huggingface.co/{model_id}",
            description=spec["description"],
        )
        manager.add_model(metadata)

    return manager


def get_hf_inference_model_manager(*, use_cache: bool = True, persist: bool = False) -> object:
    """Return a model manager populated with curated HF Inference provider models."""

    if use_cache and not persist:
        return _get_hf_inference_model_manager_cached()
    return _create_hf_inference_model_manager(persist=persist)


def list_hf_inference_models(*, model_kind: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return curated HF Inference models from rich metadata manager.

    Args:
        model_kind: Optional filter: `llm` or `embedding`.
    """

    manager = get_hf_inference_model_manager(use_cache=True, persist=False)
    results: List[Dict[str, Any]] = []

    for metadata in manager.list_models():
        hf_cfg = getattr(metadata, "huggingface_config", None) or {}
        if hf_cfg.get("inference_provider") != "hf-inference":
            continue

        tags = set(getattr(metadata, "tags", []) or [])
        kind = "embedding" if "embedding" in tags else "llm"
        if model_kind and kind != model_kind:
            continue

        results.append(
            {
                "model_id": metadata.model_id,
                "model_name": metadata.model_name,
                "model_kind": kind,
                "pipeline_tag": hf_cfg.get("pipeline_tag"),
                "supported_backends": list(getattr(metadata, "supported_backends", []) or []),
                "source_url": getattr(metadata, "source_url", None),
            }
        )

    return sorted(results, key=lambda item: item["model_id"])


def get_hf_inference_model_metadata(model_id: str) -> Optional[Dict[str, Any]]:
    """Return a single model metadata record from the rich HF model manager."""

    manager = get_hf_inference_model_manager(use_cache=True, persist=False)
    metadata = manager.get_model(model_id)
    if metadata is None:
        return None
    hf_cfg = getattr(metadata, "huggingface_config", None) or {}
    return {
        "model_id": metadata.model_id,
        "model_name": metadata.model_name,
        "model_type": getattr(getattr(metadata, "model_type", None), "value", str(getattr(metadata, "model_type", ""))),
        "pipeline_tag": hf_cfg.get("pipeline_tag"),
        "inference_provider": hf_cfg.get("inference_provider"),
        "supported_backends": list(getattr(metadata, "supported_backends", []) or []),
        "tags": list(getattr(metadata, "tags", []) or []),
        "source_url": getattr(metadata, "source_url", None),
        "description": getattr(metadata, "description", ""),
    }


def build_hf_inference_ipld_document(
    *,
    model_kind: Optional[str] = None,
    include_generated_at: bool = True,
) -> Dict[str, Any]:
    """Build an IPLD-friendly model registry document for HF Inference models.

    The returned object is deterministic JSON-compatible data and can be stored
    in IPFS as raw bytes or an IPLD block.
    """

    records = list_hf_inference_models(model_kind=model_kind)
    doc = {
        "kind": "ipfs_datasets_py.hf_inference_model_registry",
        "schema_version": "1.0",
        "model_kind": model_kind,
        "models": records,
        "count": len(records),
    }
    if include_generated_at:
        doc["generated_at"] = datetime.now(timezone.utc).isoformat()
    return doc


def get_hf_inference_ipld_cid(
    *,
    model_kind: Optional[str] = None,
    base: str = "base32",
    codec: str = "raw",
    mh_type: str = "sha2-256",
) -> str:
    """Compute a deterministic CID for the current HF inference IPLD document."""

    from ipfs_datasets_py.utils.cid_utils import cid_for_obj

    doc = build_hf_inference_ipld_document(model_kind=model_kind, include_generated_at=False)
    return cid_for_obj(doc, base=base, codec=codec, mh_type=mh_type)


def publish_hf_inference_ipld_to_ipfs(
    *,
    model_kind: Optional[str] = None,
    pin: bool = True,
    backend: Optional[str] = None,
    backend_instance: Optional[object] = None,
) -> Dict[str, Any]:
    """Publish HF inference model registry IPLD document to IPFS.

    Returns publication metadata including locally computed CID and backend CID.
    """

    from ipfs_datasets_py.ipfs_backend_router import add_bytes
    from ipfs_datasets_py.utils.cid_utils import canonical_json_bytes, cid_for_bytes

    doc = build_hf_inference_ipld_document(model_kind=model_kind)
    payload = canonical_json_bytes(doc)
    local_cid = cid_for_bytes(payload)
    ipfs_cid = add_bytes(payload, pin=pin, backend=backend, backend_instance=backend_instance)

    return {
        "status": "success",
        "local_cid": local_cid,
        "ipfs_cid": ipfs_cid,
        "bytes": len(payload),
        "model_kind": model_kind,
        "count": doc.get("count", 0),
    }


def load_hf_inference_ipld_from_ipfs(
    cid: str,
    *,
    backend: Optional[str] = None,
    backend_instance: Optional[object] = None,
) -> Dict[str, Any]:
    """Load and validate an HF inference model registry IPLD document from IPFS."""

    from ipfs_datasets_py.ipfs_backend_router import cat

    raw = cat(cid, backend=backend, backend_instance=backend_instance)
    doc = json.loads(raw.decode("utf-8"))
    if not isinstance(doc, dict) or doc.get("kind") != "ipfs_datasets_py.hf_inference_model_registry":
        raise ValueError("IPFS object is not an HF inference model registry IPLD document")
    return doc
