"""Model selection config utilities."""

from __future__ import annotations

import importlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
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
_HF_INFERENCE_PROVIDER_LLM_PIPELINE_TAGS = ("text-generation", "text2text-generation", "summarization")
_HF_INFERENCE_PROVIDER_EMBEDDING_PIPELINE_TAGS = ("feature-extraction",)

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


class _CompatModelType(Enum):
    LANGUAGE_MODEL = "language_model"
    EMBEDDING_MODEL = "embedding_model"


class _CompatDataType(Enum):
    TEXT = "text"
    EMBEDDINGS = "embeddings"


@dataclass
class _CompatIOSpec:
    name: str
    data_type: _CompatDataType
    description: str = ""


@dataclass
class _CompatModelMetadata:
    model_id: str
    model_name: str
    model_type: _CompatModelType
    architecture: str
    inputs: List[_CompatIOSpec]
    outputs: List[_CompatIOSpec]
    huggingface_config: Optional[Dict[str, Any]] = None
    inference_code_location: Optional[str] = None
    supported_backends: Optional[List[str]] = None
    hardware_requirements: Optional[Dict[str, Any]] = None
    performance_metrics: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    source_url: Optional[str] = None
    license: Optional[str] = None
    description: str = ""
    model_card: Optional[str] = None
    repository_structure: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.supported_backends is None:
            self.supported_backends = []
        if self.tags is None:
            self.tags = []
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
        if self.updated_at is None:
            self.updated_at = datetime.now(timezone.utc)


class _CompatModelManager:
    def __init__(self, storage_path: str | None = None, use_database: bool | None = None, enable_ipfs: bool | None = None):
        _ = (storage_path, use_database, enable_ipfs)
        self.models: Dict[str, _CompatModelMetadata] = {}

    def add_model(self, metadata: _CompatModelMetadata) -> bool:
        self.models[metadata.model_id] = metadata
        return True

    def get_model(self, model_id: str) -> Optional[_CompatModelMetadata]:
        return self.models.get(model_id)

    def list_models(
        self,
        model_type: Optional[_CompatModelType] = None,
        architecture: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[_CompatModelMetadata]:
        results: List[_CompatModelMetadata] = []
        for metadata in self.models.values():
            if model_type is not None and metadata.model_type != model_type:
                continue
            if architecture is not None and metadata.architecture != architecture:
                continue
            if tags and not all(tag in (metadata.tags or []) for tag in tags):
                continue
            results.append(metadata)
        return results

    def close(self) -> None:
        return None


@dataclass(frozen=True)
class _ModelManagerBindings:
    ModelManager: Any
    ModelMetadata: Any
    ModelType: Any
    DataType: Any
    IOSpec: Any
    source: str


def _candidate_ipfs_accelerate_repo_roots() -> List[Path]:
    roots: List[Path] = []
    override = os.environ.get("IPFS_ACCELERATE_PY_REPO_ROOT")
    if override:
        roots.append(Path(override).expanduser())

    project_root = _project_root()
    roots.append(project_root.parent / "ipfs_accelerate_py")
    roots.append(Path.home() / "ipfs_accelerate_py")

    for parent in project_root.parents:
        roots.append(parent / "ipfs_accelerate_py")

    unique: List[Path] = []
    seen: set[str] = set()
    for root in roots:
        marker = str(root.resolve()) if root.exists() else str(root)
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(root)
    return unique


def _clear_ipfs_accelerate_modules() -> None:
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            sys.modules.pop(name, None)


@lru_cache(maxsize=1)
def _load_ipfs_accelerate_model_manager_bindings() -> _ModelManagerBindings:
    try:
        module = importlib.import_module("ipfs_accelerate_py.model_manager")
        return _ModelManagerBindings(
            ModelManager=getattr(module, "ModelManager"),
            ModelMetadata=getattr(module, "ModelMetadata"),
            ModelType=getattr(module, "ModelType"),
            DataType=getattr(module, "DataType"),
            IOSpec=getattr(module, "IOSpec"),
            source="import",
        )
    except Exception:
        pass

    for repo_root in _candidate_ipfs_accelerate_repo_roots():
        model_manager_path = repo_root / "ipfs_accelerate_py" / "model_manager.py"
        if not model_manager_path.is_file():
            continue
        try:
            repo_text = str(repo_root.resolve())
            if repo_text not in sys.path:
                sys.path.insert(0, repo_text)
            _clear_ipfs_accelerate_modules()
            module = importlib.import_module("ipfs_accelerate_py.model_manager")
            return _ModelManagerBindings(
                ModelManager=getattr(module, "ModelManager"),
                ModelMetadata=getattr(module, "ModelMetadata"),
                ModelType=getattr(module, "ModelType"),
                DataType=getattr(module, "DataType"),
                IOSpec=getattr(module, "IOSpec"),
                source=repo_text,
            )
        except Exception:
            continue

    return _ModelManagerBindings(
        ModelManager=_CompatModelManager,
        ModelMetadata=_CompatModelMetadata,
        ModelType=_CompatModelType,
        DataType=_CompatDataType,
        IOSpec=_CompatIOSpec,
        source="compat",
    )


def _resolve_hf_api_token() -> str:
    for name in (
        "IPFS_DATASETS_PY_HF_API_TOKEN",
        "HUGGINGFACEHUB_API_TOKEN",
        "HUGGINGFACE_API_TOKEN",
        "HF_TOKEN",
    ):
        value = os.getenv(name, "").strip()
        if value:
            return value
    try:
        hub = importlib.import_module("huggingface_hub")
        getter = getattr(hub, "get_token", None)
        if callable(getter):
            return str(getter() or "").strip()
    except Exception:
        pass
    return ""


def _hf_inference_discovery_limit() -> int:
    raw = os.getenv("IPFS_DATASETS_PY_HF_INFERENCE_DISCOVERY_LIMIT", "20")
    try:
        return max(1, int(raw))
    except Exception:
        return 20


def _discover_live_hf_inference_model_specs(*, model_kind: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        hub = importlib.import_module("huggingface_hub")
        api_cls = getattr(hub, "HfApi", None)
        if api_cls is None:
            return []
    except Exception:
        return []

    api = api_cls()
    token = _resolve_hf_api_token() or None
    limit = _hf_inference_discovery_limit()
    specs: Dict[str, Dict[str, Any]] = {}
    discovery_plan: List[tuple[str, str]] = []

    if model_kind in (None, "llm"):
        for pipeline_tag in _HF_INFERENCE_PROVIDER_LLM_PIPELINE_TAGS:
            discovery_plan.append(("llm", pipeline_tag))
    if model_kind in (None, "embedding"):
        for pipeline_tag in _HF_INFERENCE_PROVIDER_EMBEDDING_PIPELINE_TAGS:
            discovery_plan.append(("embedding", pipeline_tag))

    for kind, pipeline_tag in discovery_plan:
        try:
            models = api.list_models(
                inference_provider="hf-inference",
                pipeline_tag=pipeline_tag,
                limit=limit,
                token=token,
            )
        except Exception:
            continue

        for item in models:
            model_id = str(getattr(item, "id", "") or "").strip()
            if not model_id or model_id in specs:
                continue
            tags = list(getattr(item, "tags", None) or [])
            card_data = getattr(item, "cardData", None)
            if not isinstance(card_data, dict):
                card_data = {}
            library_name = getattr(item, "library_name", None) or card_data.get("library_name")
            specs[model_id] = {
                "model_id": model_id,
                "pipeline_tag": pipeline_tag,
                "model_kind": kind,
                "library_name": library_name,
                "tags": tags,
                "description": f"Live Hugging Face Inference Providers {pipeline_tag} model discovered via HfApi.list_models",
                "live_discovered": True,
            }

    return sorted(specs.values(), key=lambda item: item["model_id"])


def _build_hf_model_metadata(spec: Dict[str, Any], *, bindings: _ModelManagerBindings) -> Any:
    model_id = str(spec["model_id"])
    model_kind = str(spec.get("model_kind") or "llm")
    pipeline_tag = str(spec.get("pipeline_tag") or ("feature-extraction" if model_kind == "embedding" else "text-generation"))
    architecture = str(spec.get("architecture") or ("sentence-transformer" if model_kind == "embedding" else "transformer"))
    inputs = [bindings.IOSpec(name="input", data_type=bindings.DataType.TEXT, description="Input text")]
    outputs = [
        bindings.IOSpec(
            name="embeddings" if model_kind == "embedding" else "text",
            data_type=bindings.DataType.EMBEDDINGS if model_kind == "embedding" else bindings.DataType.TEXT,
            description="Model output",
        )
    ]
    tags = list(
        dict.fromkeys(
            [
                "huggingface",
                "hf-inference",
                pipeline_tag,
                model_kind,
                *(spec.get("tags") or []),
                *(["live-discovered"] if spec.get("live_discovered") else []),
            ]
        )
    )

    return bindings.ModelMetadata(
        model_id=model_id,
        model_name=model_id.split("/")[-1],
        model_type=bindings.ModelType.EMBEDDING_MODEL if model_kind == "embedding" else bindings.ModelType.LANGUAGE_MODEL,
        architecture=architecture,
        inputs=inputs,
        outputs=outputs,
        huggingface_config={
            "inference_provider": "hf-inference",
            "pipeline_tag": pipeline_tag,
            "known_available": True,
            "live_discovered": bool(spec.get("live_discovered")),
            **({"library_name": spec.get("library_name")} if spec.get("library_name") else {}),
        },
        supported_backends=["hf_inference_api", "huggingface_inference"],
        tags=tags,
        source_url=f"https://huggingface.co/{model_id}",
        description=str(spec.get("description") or "Hugging Face inference model"),
    )


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
    """Create and seed a rich model metadata manager for live HF Inference providers."""

    bindings = _load_ipfs_accelerate_model_manager_bindings()

    manager = bindings.ModelManager(
        storage_path=_project_runtime_metadata_path(),
        use_database=False,
        enable_ipfs=False,
    )

    if not persist and hasattr(manager, "_save_data"):
        # Keep this manager query-only for selection decisions.
        manager._save_data = lambda: None  # type: ignore[attr-defined]

    specs = _discover_live_hf_inference_model_specs()
    if not specs:
        specs = _build_hf_inference_model_specs()

    for spec in specs:
        metadata = _build_hf_model_metadata(spec, bindings=bindings)
        manager.add_model(metadata)

    return manager


def get_hf_inference_model_manager(*, use_cache: bool = True, persist: bool = False) -> object:
    """Return a model manager populated from live HF Inference discovery when available."""

    if use_cache and not persist:
        return _get_hf_inference_model_manager_cached()
    return _create_hf_inference_model_manager(persist=persist)


def list_hf_inference_models(*, model_kind: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return live-discovered HF Inference models from the rich metadata manager.

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
