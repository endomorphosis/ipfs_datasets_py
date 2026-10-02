"""IPFS Accelerate Python package.

The package root is intentionally a discovery surface, not an initialization
surface.  Optional implementations are imported only when a public attribute
is explicitly requested.  This keeps pytest plugins and other lightweight
subpackages safe to import in environments without accelerator providers.
"""

from __future__ import annotations

import importlib
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any


SKIP_CORE = os.environ.get("IPFS_ACCEL_SKIP_CORE", "0") == "1"

_UNRESOLVED = object()
_GROUP_LOCK = threading.RLock()
_GROUP_LOADING: set[str] = set()
_GROUP_RESOLVED: set[str] = set()
_GROUP_FAILED_AT: dict[str, float] = {}
_GROUP_FAILED_MODULE_STATE: dict[str, tuple[tuple[str, bool], ...]] = {}
_PUBLIC_VALUES: dict[str, Any] = {}
_PUBLIC_RESOLVED: set[str] = set()
_FAILED_GROUP_RETRY_SECONDS = 0.25


# Each entry names the implementation module and attribute.  ``None`` means
# the module itself is the historical public value.
_GROUP_MEMBERS: dict[str, dict[str, tuple[str, str | None]]] = {
    "hf_space": {
        "EndpointContract": (".hf_space_inference", "EndpointContract"),
        "SpaceRuntimeInfo": (".hf_space_inference", "SpaceRuntimeInfo"),
        "OutputBackend": (".hf_space_inference", "OutputBackend"),
        "LocalFileSystemBackend": (
            ".hf_space_inference",
            "LocalFileSystemBackend",
        ),
        "HFBucketBackend": (".hf_space_inference", "HFBucketBackend"),
        "HFBucketBackendError": (
            ".hf_space_inference",
            "HFBucketBackendError",
        ),
        "HFSpaceClient": (".hf_space_inference", "HFSpaceClient"),
        "RefreshableGradioFile": (
            ".hf_space_inference",
            "RefreshableGradioFile",
        ),
        "BatchState": (".hf_space_inference", "BatchState"),
        "BatchProcessor": (".hf_space_inference", "BatchProcessor"),
        "is_hf_space_transport_error": (
            ".hf_space_inference",
            "is_hf_space_transport_error",
        ),
        "is_retryable_hf_space_error": (
            ".hf_space_inference",
            "is_retryable_hf_space_error",
        ),
        "is_stale_gradio_file_error": (
            ".hf_space_inference",
            "is_stale_gradio_file_error",
        ),
        "normalize_api_name": (".hf_space_inference", "normalize_api_name"),
    },
    "backends": {
        "backends": (".container_backends", "backends"),
    },
    "install_depends": {
        "install_depends": (".install_depends.install_depends", None),
    },
    "core": {
        "ipfs_accelerate_py": (".ipfs_accelerate", "ipfs_accelerate_py"),
    },
    "multiformats": {
        "ipfs_multiformats_py": (
            ".ipfs_multiformats",
            "ipfs_multiformats_py",
        ),
    },
    "config": {
        "config": (".config.config", "config"),
    },
    "webnn": {
        "accelerate_with_browser": (
            ".webnn_webgpu_integration",
            "accelerate_with_browser",
        ),
        "WebNNWebGPUAccelerator": (
            ".webnn_webgpu_integration",
            "WebNNWebGPUAccelerator",
        ),
        "get_accelerator": (
            ".webnn_webgpu_integration",
            "get_accelerator",
        ),
    },
    "model_manager": {
        "ModelManager": (".model_manager", "ModelManager"),
        "get_default_model_manager": (
            ".model_manager",
            "get_default_model_manager",
        ),
    },
    "logs": {
        "get_system_logs": (".logs", "get_system_logs"),
        "SystemLogs": (".logs", "SystemLogs"),
    },
    "p2p_workflow": {
        "P2PWorkflowScheduler": (
            ".p2p_workflow_scheduler",
            "P2PWorkflowScheduler",
        ),
        "P2PTask": (".p2p_workflow_scheduler", "P2PTask"),
        "WorkflowTag": (".p2p_workflow_scheduler", "WorkflowTag"),
        "MerkleClock": (".p2p_workflow_scheduler", "MerkleClock"),
        "FibonacciHeap": (".p2p_workflow_scheduler", "FibonacciHeap"),
        "calculate_hamming_distance": (
            ".p2p_workflow_scheduler",
            "calculate_hamming_distance",
        ),
    },
    "ipfs_kit": {
        "IPFSKitStorage": (".ipfs_kit_integration", "IPFSKitStorage"),
        "get_storage": (".ipfs_kit_integration", "get_storage"),
        "reset_storage": (".ipfs_kit_integration", "reset_storage"),
        "StorageBackendConfig": (
            ".ipfs_kit_integration",
            "StorageBackendConfig",
        ),
    },
    "backend_manager": {
        "InferenceBackendManager": (
            ".inference_backend_manager",
            "InferenceBackendManager",
        ),
        "get_backend_manager": (
            ".inference_backend_manager",
            "get_backend_manager",
        ),
        "register_backend_from_config": (
            ".inference_backend_manager",
            "register_backend_from_config",
        ),
    },
    "auto_patch": {
        "auto_patch_transformers": (".auto_patch_transformers", None),
    },
    "llm_router": {
        "generate_text": (".llm_router", "generate_text"),
        "get_llm_provider": (".llm_router", "get_llm_provider"),
        "register_llm_provider": (".llm_router", "register_llm_provider"),
        "clear_llm_router_caches": (
            ".llm_router",
            "clear_llm_router_caches",
        ),
        "LLMProvider": (".llm_router", "LLMProvider"),
        "MistralVibeInstallResult": (
            ".llm_router",
            "MistralVibeInstallResult",
        ),
        "ensure_mistral_vibe": (".llm_router", "ensure_mistral_vibe"),
        "RouterDeps": (".router_deps", "RouterDeps"),
        "get_default_router_deps": (
            ".router_deps",
            "get_default_router_deps",
        ),
        "set_default_router_deps": (
            ".router_deps",
            "set_default_router_deps",
        ),
        "choose_cli_session_route": (".llm_router", "choose_cli_session_route"),
        "migrate_cli_session_route": (".llm_router", "migrate_cli_session_route"),
        "get_allocation_session": (".llm_router", "get_allocation_session"),
        "system_one": (".typesafe_inference", "system_one"),
    },
    "llm_allocation": {
        "register_api_key": (".llm_allocation", "register_api_key"),
        "list_api_key_slots": (".llm_allocation", "list_api_key_slots"),
        "bind_session_api_key": (".llm_allocation", "bind_session_api_key"),
        "select_api_key": (".llm_allocation", "select_api_key"),
        "choose_cli_route": (".llm_allocation", "choose_cli_route"),
        "migrate_cli_session": (".llm_allocation", "migrate_cli_session"),
        "resolve_session": (".llm_allocation", "resolve_session"),
        "cli_tools_status": (".llm_allocation", "cli_tools_status"),
        "render_cli_tools_status": (".llm_allocation", "render_cli_tools_status"),
        "get_allocation_store": (".llm_allocation", "get_allocation_store"),
        "resume_kwargs_for_session": (
            ".llm_allocation",
            "resume_kwargs_for_session",
        ),
        "fingerprint_api_key": (".llm_allocation", "fingerprint_api_key"),
        "select_efficient_model": (".llm_allocation", "select_efficient_model"),
        "select_efficient_route": (".llm_allocation", "select_efficient_route"),
        "discover_available_providers": (
            ".llm_allocation",
            "discover_available_providers",
        ),
        "intelligence_cost_matrix": (".llm_allocation", "intelligence_cost_matrix"),
        "populate_cli_models": (".llm_allocation", "populate_cli_models"),
        "populate_intelligence_index": (
            ".llm_allocation",
            "populate_intelligence_index",
        ),
        "populate_router_catalog": (".llm_allocation", "populate_router_catalog"),
        "populate_typesafe_models": (".llm_allocation", "populate_typesafe_models"),
        "ensure_cli_tool": (
            ".cli_runtime.installers.catalog",
            "ensure_cli_tool",
        ),
    },
    "embeddings_router": {
        "embed_texts": (".embeddings_router", "embed_texts"),
        "embed_texts_batched": (
            ".embeddings_router",
            "embed_texts_batched",
        ),
        "embed_text": (".embeddings_router", "embed_text"),
        "get_embeddings_provider": (
            ".embeddings_router",
            "get_embeddings_provider",
        ),
        "get_embedding_progress": (
            ".embeddings_router",
            "get_embedding_progress",
        ),
        "get_last_embedding_trace": (
            ".embeddings_router",
            "get_last_embedding_trace",
        ),
        "register_embeddings_provider": (
            ".embeddings_router",
            "register_embeddings_provider",
        ),
        "clear_embeddings_router_caches": (
            ".embeddings_router",
            "clear_embeddings_router_caches",
        ),
        "EmbeddingsRouterError": (
            ".embeddings_router",
            "EmbeddingsRouterError",
        ),
        "EmbeddingsProvider": (
            ".embeddings_router",
            "EmbeddingsProvider",
        ),
    },
    "multimodal_router": {
        "generate_multimodal": (
            ".multimodal_router",
            "generate_multimodal",
        ),
        "get_multimodal_provider": (
            ".multimodal_router",
            "get_multimodal_provider",
        ),
        "register_multimodal_provider": (
            ".multimodal_router",
            "register_multimodal_provider",
        ),
        "clear_multimodal_router_caches": (
            ".multimodal_router",
            "clear_multimodal_router_caches",
        ),
        "MultimodalProvider": (
            ".multimodal_router",
            "MultimodalProvider",
        ),
    },
    "voice_router": {
        "text_to_speech": (".voice_router", "text_to_speech"),
        "speech_to_text": (".voice_router", "speech_to_text"),
        "get_voice_provider": (".voice_router", "get_voice_provider"),
        "register_voice_provider": (
            ".voice_router",
            "register_voice_provider",
        ),
        "get_voice_provider_capabilities": (
            ".voice_router",
            "get_voice_provider_capabilities",
        ),
        "clear_voice_router_caches": (
            ".voice_router",
            "clear_voice_router_caches",
        ),
        "VoiceProvider": (".voice_router", "VoiceProvider"),
        "VoiceProviderCapabilities": (
            ".voice_router",
            "VoiceProviderCapabilities",
        ),
        "ProviderInfo": (".voice_router", "ProviderInfo"),
        "VOICE_TURN_CONTRACT_VERSION": (
            ".voice_router",
            "VOICE_TURN_CONTRACT_VERSION",
        ),
        "VOICE_STAGE_STATUSES": (
            ".voice_router",
            "VOICE_STAGE_STATUSES",
        ),
        "VOICE_TURN_STATUSES": (
            ".voice_router",
            "VOICE_TURN_STATUSES",
        ),
        "DEFAULT_GROUNDED_FALLBACK": (
            ".voice_router",
            "DEFAULT_GROUNDED_FALLBACK",
        ),
        "GroundingEvidence": (".voice_router", "GroundingEvidence"),
        "VoiceGroundingSource": (
            ".voice_router",
            "VoiceGroundingSource",
        ),
        "GroundedSlot": (".voice_router", "GroundedSlot"),
        "VoiceResponsePlan": (".voice_router", "VoiceResponsePlan"),
        "VoiceTemplateProvider": (
            ".voice_router",
            "VoiceTemplateProvider",
        ),
        "GraphRAGVoiceTemplateProvider": (
            ".voice_router",
            "GraphRAGVoiceTemplateProvider",
        ),
        "buildVoiceGraphRagPromptParts": (
            ".voice_router",
            "buildVoiceGraphRagPromptParts",
        ),
        "VoiceStageTrace": (".voice_router", "VoiceStageTrace"),
        "VoiceTurnRequest": (".voice_router", "VoiceTurnRequest"),
        "VoiceTurnProvenance": (
            ".voice_router",
            "VoiceTurnProvenance",
        ),
        "VoiceTurnResult": (".voice_router", "VoiceTurnResult"),
        "voice_turn_cache_key": (
            ".voice_router",
            "voice_turn_cache_key",
        ),
        "process_voice_turn": (".voice_router", "process_voice_turn"),
        "get_tts_provider": (".voice_router", "get_tts_provider"),
        "register_tts_provider": (
            ".voice_router",
            "register_tts_provider",
        ),
        "clear_tts_router_caches": (
            ".voice_router",
            "clear_tts_router_caches",
        ),
        "TTSProvider": (".voice_router", "TTSProvider"),
    },
    # Narrow proof-reuse bootstrap facade (PTR-139).  Resolved only on
    # explicit attribute access; never imports the supervisor, datasets ZK
    # stack, kit daemons, or installer machinery at package import time.
    "proof_reuse_bootstrap": {
        "AcceleratorProofReuseBootstrap": (
            ".testing.proof_reuse.lazy_dependencies",
            "AcceleratorProofReuseBootstrap",
        ),
        "ProofReuseLazyDependencyInstaller": (
            ".testing.proof_reuse.lazy_dependencies",
            "ProofReuseLazyDependencyInstaller",
        ),
        "ProofReuseCapabilityResolution": (
            ".testing.proof_reuse.lazy_dependencies",
            "ProofReuseCapabilityResolution",
        ),
        "get_proof_reuse_bootstrap": (
            ".testing.proof_reuse.lazy_dependencies",
            "get_proof_reuse_bootstrap",
        ),
    },
    "typesafe": {
        "system_one": (".typesafe_inference", "system_one"),
        "TypeSafeClient": (".typesafe_inference", "TypeSafeClient"),
        "Noul": (".typesafe_inference", "Noul"),
        "Choice": (".typesafe_inference", "Choice"),
        "Score": (".typesafe_inference", "Score"),
        "TypeSafeInferenceError": (
            ".typesafe_inference",
            "TypeSafeInferenceError",
        ),
    },
}

_GROUP_AVAILABILITY: dict[str, tuple[str, ...]] = {
    "webnn": ("webnn_webgpu_available",),
    "model_manager": ("model_manager_available",),
    "backend_manager": ("inference_backend_manager_available",),
    "llm_router": ("llm_router_available",),
    "llm_allocation": ("llm_allocation_available",),
    "embeddings_router": ("embeddings_router_available",),
    "multimodal_router": ("multimodal_router_available",),
    "voice_router": ("voice_router_available", "tts_router_available"),
}

_CORE_GROUPS = {
    "install_depends",
    "core",
    "multiformats",
    "config",
    "webnn",
    "logs",
    "p2p_workflow",
    "ipfs_kit",
    "backend_manager",
    "auto_patch",
    "llm_router",
    "llm_allocation",
    "embeddings_router",
    "multimodal_router",
    "voice_router",
}

_NAME_TO_GROUP = {
    name: group
    for group, members in _GROUP_MEMBERS.items()
    for name in members
}
_NAME_TO_GROUP.update(
    {
        name: group
        for group, names in _GROUP_AVAILABILITY.items()
        for name in names
    }
)

_GROUP_TRANSITION_MODULES: dict[str, tuple[str, ...]] = {
    "multiformats": ("multiformats",),
    "core": ("ipfs_kit_py", "ipfs_model_manager_py", "ipfs_transformers_py"),
    "ipfs_kit": ("ipfs_kit_py",),
}


def _unavailable_ipfs_accelerate_py(*args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError(
        "IPFS Accelerate core is not available (missing dependencies) or "
        "disabled. Set IPFS_ACCEL_SKIP_CORE=0 and install core dependencies "
        "to enable."
    )


_unavailable_ipfs_accelerate_py.__name__ = "ipfs_accelerate_py"
_unavailable_ipfs_accelerate_py.__qualname__ = "ipfs_accelerate_py"


def _publish_public_value(name: str, value: Any) -> None:
    _PUBLIC_VALUES[name] = value
    _PUBLIC_RESOLVED.add(name)
    globals()[name] = value
    export_map = globals().get("export")
    if isinstance(export_map, dict) and dict.__contains__(export_map, name):
        dict.__setitem__(export_map, name, value)


def _group_module_state(group: str) -> tuple[tuple[str, bool], ...]:
    names = {
        f"{__name__}{module_name}"
        for module_name, _ in _GROUP_MEMBERS[group].values()
    }
    names.update(_GROUP_TRANSITION_MODULES.get(group, ()))
    return tuple(
        (name, name in sys.modules)
        for name in sorted(names)
    )


def _failed_group_retry_ready(group: str) -> bool:
    previous_state = _GROUP_FAILED_MODULE_STATE.get(group, ())
    if _group_module_state(group) != previous_state:
        # An authorized installer/importer changed process capabilities.
        return True
    failed_at = _GROUP_FAILED_AT.get(group, 0.0)
    return time.monotonic() - failed_at >= _FAILED_GROUP_RETRY_SECONDS


def _resolve_group(group: str) -> None:
    """Resolve and cache one optional public group exactly once."""

    with _GROUP_LOCK:
        if group in _GROUP_RESOLVED:
            return
        if group in _GROUP_LOADING:
            # A provider importing its own package root must not recurse.
            return
        if group in _GROUP_FAILED_AT and not _failed_group_retry_ready(group):
            return
        _GROUP_LOADING.add(group)
        members = _GROUP_MEMBERS[group]
        enabled = not (SKIP_CORE and group in _CORE_GROUPS)
        values: dict[str, Any] = {}
        available = False
        try:
            if enabled:
                loaded_modules: dict[str, ModuleType] = {}
                for name, (module_name, attribute_name) in members.items():
                    module = loaded_modules.get(module_name)
                    if module is None:
                        module = importlib.import_module(
                            f"{__name__}{module_name}"
                        )
                        loaded_modules[module_name] = module
                    values[name] = (
                        module
                        if attribute_name is None
                        else getattr(module, attribute_name)
                    )
                available = True
        except Exception:
            values.clear()
            available = False
        finally:
            for name in members:
                value = values.get(name)
                if name == "ipfs_accelerate_py" and value is None:
                    value = _unavailable_ipfs_accelerate_py
                _publish_public_value(name, value)
            for name in _GROUP_AVAILABILITY.get(group, ()):
                _publish_public_value(name, available)
            if available or not enabled:
                _GROUP_RESOLVED.add(group)
                _GROUP_FAILED_AT.pop(group, None)
                _GROUP_FAILED_MODULE_STATE.pop(group, None)
            else:
                _GROUP_FAILED_AT[group] = time.monotonic()
                _GROUP_FAILED_MODULE_STATE[group] = _group_module_state(group)
            _GROUP_LOADING.discard(group)


def _resolve_public(name: str) -> Any:
    group = _NAME_TO_GROUP.get(name)
    if group is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if group in _GROUP_FAILED_AT and _failed_group_retry_ready(group):
        _resolve_group(group)
    if name in _PUBLIC_RESOLVED:
        return _PUBLIC_VALUES[name]
    _resolve_group(group)
    return _PUBLIC_VALUES.get(name)


def refresh_optional_exports(*names: str) -> dict[str, Any]:
    """Retry failed optional imports after a controlled capability change.

    This is deliberately outside ``__all__`` and the historical ``export``
    manifest.  Lazy installers may call it after changing import availability;
    ordinary callers get bounded automatic retries on explicit access.
    """

    requested = tuple(names)
    groups = {
        _NAME_TO_GROUP[name]
        for name in requested
        if name in _NAME_TO_GROUP
    }
    if not requested:
        groups = set(_GROUP_FAILED_AT)
    with _GROUP_LOCK:
        for group in groups:
            if SKIP_CORE and group in _CORE_GROUPS:
                continue
            _GROUP_RESOLVED.discard(group)
            _GROUP_FAILED_AT.pop(group, None)
            _GROUP_FAILED_MODULE_STATE.pop(group, None)
            for public_name in (
                *tuple(_GROUP_MEMBERS[group]),
                *_GROUP_AVAILABILITY.get(group, ()),
            ):
                _PUBLIC_VALUES.pop(public_name, None)
                _PUBLIC_RESOLVED.discard(public_name)
                globals().pop(public_name, None)
                export_map = globals().get("export")
                if (
                    isinstance(export_map, dict)
                    and dict.__contains__(export_map, public_name)
                ):
                    dict.__setitem__(export_map, public_name, None)
    return {
        name: _resolve_public(name)
        for name in requested
        if name in _NAME_TO_GROUP
    }


_global_instance: Any = None
_instance_lock = threading.Lock()


def get_instance(**kwargs: Any) -> Any:
    """Get or create the process-wide accelerator with optional injections."""

    global _global_instance
    constructor = _resolve_public("ipfs_accelerate_py")
    if constructor is _unavailable_ipfs_accelerate_py:
        return constructor(**kwargs)
    with _instance_lock:
        if _global_instance is None:
            _global_instance = constructor(**kwargs)
        elif kwargs:
            for key, value in kwargs.items():
                try:
                    setattr(_global_instance, key, value)
                except Exception:
                    pass
    return _global_instance


def cli_main(*args: Any, **kwargs: Any) -> Any:
    """Load the command-line implementation only when invoked."""

    from .cli_entry import main

    return main(*args, **kwargs)


_PUBLIC_VALUES["get_instance"] = get_instance
_PUBLIC_RESOLVED.add("get_instance")
if not SKIP_CORE:
    _PUBLIC_VALUES["cli_main"] = cli_main
    _PUBLIC_RESOLVED.add("cli_main")


# ``worker`` retains its historical synchronized module-valued contract.  It
# is the only compatibility surface that intentionally exposes a module-like
# raw snapshot through ``dict(export)``.
_WORKER_UNRESOLVED = object()
_worker_export_value: Any = None if SKIP_CORE else _WORKER_UNRESOLVED
_worker_loading = False
_worker_loader_thread_id: int | None = None
_worker_condition = threading.Condition()


class _LazyWorkerSnapshot(ModuleType):
    def __getattr__(self, name: str) -> Any:
        resolved = _load_legacy_worker()
        if resolved is None:
            raise AttributeError(
                "legacy worker is unavailable because optional dependencies "
                "could not be imported"
            )
        return getattr(resolved, name)

    def __dir__(self) -> list[str]:
        resolved = _load_legacy_worker()
        return [] if resolved is None else dir(resolved)


_worker_snapshot = _LazyWorkerSnapshot(
    f"{__name__}.worker",
    "Lazy compatibility view of the legacy worker module.",
)


def _load_legacy_worker() -> Any:
    global _worker_export_value, _worker_loading, _worker_loader_thread_id

    current_thread_id = threading.get_ident()
    with _worker_condition:
        if _worker_export_value is not _WORKER_UNRESOLVED:
            return _worker_export_value
        if _worker_loading and _worker_loader_thread_id == current_thread_id:
            return globals().get("worker")
        while _worker_loading:
            _worker_condition.wait()
            if _worker_export_value is not _WORKER_UNRESOLVED:
                return _worker_export_value
        _worker_loading = True
        _worker_loader_thread_id = current_thread_id
    try:
        try:
            resolved = importlib.import_module(f"{__name__}.worker.worker")
        except Exception:
            resolved = None
        with _worker_condition:
            _worker_export_value = resolved
            globals()["worker"] = resolved
            export_map = globals().get("export")
            if isinstance(export_map, dict):
                dict.__setitem__(export_map, "worker", resolved)
            return resolved
    finally:
        with _worker_condition:
            _worker_loading = False
            _worker_loader_thread_id = None
            _worker_condition.notify_all()


class _LazyRootExport(dict[str, Any]):
    """Dictionary-compatible root export manifest with exact lazy values."""

    def __getitem__(self, key: str) -> Any:
        if key == "worker":
            with _worker_condition:
                if not dict.__contains__(self, key):
                    raise KeyError(key)
                stored = dict.__getitem__(self, key)
                if stored is not _worker_snapshot:
                    return stored
            return _load_legacy_worker()
        if key in _NAME_TO_GROUP and dict.__contains__(self, key):
            return _resolve_public(key)
        return dict.__getitem__(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        if key == "worker":
            setattr(sys.modules[__name__], "worker", value)
            return
        if key in _NAME_TO_GROUP:
            _publish_public_value(key, value)
            return
        dict.__setitem__(self, key, value)

    def __delitem__(self, key: str) -> None:
        global _worker_export_value
        if key != "worker":
            dict.__delitem__(self, key)
            return
        with _worker_condition:
            while (
                _worker_loading
                and _worker_loader_thread_id != threading.get_ident()
            ):
                _worker_condition.wait()
            if not dict.__contains__(self, key):
                raise KeyError(key)
            _worker_export_value = None if SKIP_CORE else _WORKER_UNRESOLVED
            globals().pop("worker", None)
            dict.__delitem__(self, key)
            _worker_condition.notify_all()

    def get(self, key: str, default: Any = None) -> Any:
        if key in self:
            return self[key]
        return default

    def setdefault(self, key: str, default: Any = None) -> Any:
        if key == "worker":
            with _worker_condition:
                if dict.__contains__(self, key):
                    return dict.__getitem__(self, key)
                self[key] = default
                return default
        if dict.__contains__(self, key):
            return self[key]
        self[key] = default
        return default

    def update(self, *args: Any, **kwargs: Any) -> None:
        staged: dict[str, Any] = {}
        dict.update(staged, *args, **kwargs)
        for key, value in staged.items():
            self[key] = value

    def __ior__(self, other: Any) -> "_LazyRootExport":
        self.update(other)
        return self

    def pop(self, key: str, *default: Any) -> Any:
        if len(default) > 1:
            raise TypeError(
                f"pop expected at most 2 arguments, got {1 + len(default)}"
            )
        if not dict.__contains__(self, key):
            if default:
                return default[0]
            raise KeyError(key)
        value = (
            dict.__getitem__(self, key)
            if key == "worker"
            else self[key]
        )
        self.__delitem__(key)
        return value

    def popitem(self) -> tuple[str, Any]:
        if not self:
            raise KeyError("popitem(): dictionary is empty")
        key = next(reversed(self))
        return key, self.pop(key)

    def clear(self) -> None:
        global _worker_export_value
        with _worker_condition:
            while (
                _worker_loading
                and _worker_loader_thread_id != threading.get_ident()
            ):
                _worker_condition.wait()
            had_worker = dict.__contains__(self, "worker")
            dict.clear(self)
            if had_worker:
                _worker_export_value = (
                    None if SKIP_CORE else _WORKER_UNRESOLVED
                )
                globals().pop("worker", None)
            _worker_condition.notify_all()

    def items(self) -> Any:
        for key in tuple(dict.keys(self)):
            if key == "worker" or key in _NAME_TO_GROUP:
                self[key]
        return dict.items(self)

    def values(self) -> Any:
        self.items()
        return dict.values(self)

    def copy(self) -> dict[str, Any]:
        self.items()
        return dict.copy(self)


_BASE_EXPORT_NAMES = (
    "backends",
    "config",
    "install_depends",
    "ipfs_accelerate_py",
    "worker",
    "ipfs_multiformats_py",
    "get_instance",
    "accelerate_with_browser",
    "WebNNWebGPUAccelerator",
    "get_accelerator",
    "webnn_webgpu_available",
    "ModelManager",
    "get_default_model_manager",
    "model_manager_available",
    "EndpointContract",
    "SpaceRuntimeInfo",
    "OutputBackend",
    "LocalFileSystemBackend",
    "HFBucketBackend",
    "HFBucketBackendError",
    "HFSpaceClient",
    "RefreshableGradioFile",
    "BatchState",
    "BatchProcessor",
    "is_hf_space_transport_error",
    "is_retryable_hf_space_error",
    "is_stale_gradio_file_error",
    "normalize_api_name",
)

_CORE_EXPORT_NAMES = (
    "cli_main",
    "get_system_logs",
    "SystemLogs",
    "P2PWorkflowScheduler",
    "P2PTask",
    "WorkflowTag",
    "MerkleClock",
    "FibonacciHeap",
    "calculate_hamming_distance",
    "IPFSKitStorage",
    "get_storage",
    "reset_storage",
    "StorageBackendConfig",
    "InferenceBackendManager",
    "get_backend_manager",
    "register_backend_from_config",
    "auto_patch_transformers",
    "generate_text",
    "get_llm_provider",
    "register_llm_provider",
    "clear_llm_router_caches",
    "LLMProvider",
    "MistralVibeInstallResult",
    "ensure_mistral_vibe",
    "RouterDeps",
    "get_default_router_deps",
    "set_default_router_deps",
    "cli_tools_status",
    "render_cli_tools_status",
    "choose_cli_session_route",
    "migrate_cli_session_route",
    "get_allocation_session",
    "register_api_key",
    "list_api_key_slots",
    "bind_session_api_key",
    "select_api_key",
    "choose_cli_route",
    "migrate_cli_session",
    "resolve_session",
    "get_allocation_store",
    "resume_kwargs_for_session",
    "fingerprint_api_key",
    "ensure_cli_tool",
    "select_efficient_model",
    "select_efficient_route",
    "discover_available_providers",
    "intelligence_cost_matrix",
    "populate_cli_models",
    "populate_intelligence_index",
    "populate_router_catalog",
    "populate_typesafe_models",
    "system_one",
    "TypeSafeClient",
    "Noul",
    "Choice",
    "Score",
    "TypeSafeInferenceError",
    "embed_texts",
    "embed_texts_batched",
    "embed_text",
    "get_embeddings_provider",
    "get_embedding_progress",
    "get_last_embedding_trace",
    "register_embeddings_provider",
    "clear_embeddings_router_caches",
    "EmbeddingsRouterError",
    "EmbeddingsProvider",
    "generate_multimodal",
    "get_multimodal_provider",
    "register_multimodal_provider",
    "clear_multimodal_router_caches",
    "MultimodalProvider",
    "text_to_speech",
    "speech_to_text",
    "get_voice_provider",
    "register_voice_provider",
    "get_voice_provider_capabilities",
    "clear_voice_router_caches",
    "VoiceProvider",
    "VoiceProviderCapabilities",
    "ProviderInfo",
    "VOICE_TURN_CONTRACT_VERSION",
    "VOICE_STAGE_STATUSES",
    "VOICE_TURN_STATUSES",
    "DEFAULT_GROUNDED_FALLBACK",
    "GroundingEvidence",
    "VoiceGroundingSource",
    "GroundedSlot",
    "VoiceResponsePlan",
    "VoiceTemplateProvider",
    "GraphRAGVoiceTemplateProvider",
    "buildVoiceGraphRagPromptParts",
    "VoiceStageTrace",
    "VoiceTurnRequest",
    "VoiceTurnProvenance",
    "VoiceTurnResult",
    "voice_turn_cache_key",
    "process_voice_turn",
    "get_tts_provider",
    "register_tts_provider",
    "clear_tts_router_caches",
    "TTSProvider",
)


def _initial_export_value(name: str) -> Any:
    if name == "worker":
        return None if SKIP_CORE else _worker_snapshot
    if name in _PUBLIC_RESOLVED:
        return _PUBLIC_VALUES[name]
    # A falsey raw slot cannot masquerade as an available optional provider.
    return None


_export_names = (
    _BASE_EXPORT_NAMES
    if SKIP_CORE
    else _BASE_EXPORT_NAMES + _CORE_EXPORT_NAMES
)
export = _LazyRootExport(
    {name: _initial_export_value(name) for name in _export_names}
)


__all__ = [
    "ipfs_accelerate_py",
    "get_instance",
    "backends",
    "config",
    "install_depends",
    "worker",
    "ipfs_multiformats_py",
    "accelerate_with_browser",
    "WebNNWebGPUAccelerator",
    "get_accelerator",
    "webnn_webgpu_available",
    "ModelManager",
    "get_default_model_manager",
    "model_manager_available",
    "SpaceRuntimeInfo",
    "EndpointContract",
    "OutputBackend",
    "LocalFileSystemBackend",
    "HFBucketBackend",
    "HFBucketBackendError",
    "HFSpaceClient",
    "RefreshableGradioFile",
    "BatchState",
    "BatchProcessor",
    "is_hf_space_transport_error",
    "is_retryable_hf_space_error",
    "is_stale_gradio_file_error",
    "normalize_api_name",
    "cli_main",
    "get_system_logs",
    "SystemLogs",
    "P2PWorkflowScheduler",
    "P2PTask",
    "WorkflowTag",
    "MerkleClock",
    "FibonacciHeap",
    "calculate_hamming_distance",
    "IPFSKitStorage",
    "get_storage",
    "reset_storage",
    "StorageBackendConfig",
    "InferenceBackendManager",
    "get_backend_manager",
    "register_backend_from_config",
    "inference_backend_manager_available",
    "auto_patch_transformers",
    "generate_text",
    "get_llm_provider",
    "register_llm_provider",
    "clear_llm_router_caches",
    "LLMProvider",
    "RouterDeps",
    "MistralVibeInstallResult",
    "ensure_mistral_vibe",
    "get_default_router_deps",
    "set_default_router_deps",
    "cli_tools_status",
    "render_cli_tools_status",
    "choose_cli_session_route",
    "migrate_cli_session_route",
    "get_allocation_session",
    "register_api_key",
    "list_api_key_slots",
    "bind_session_api_key",
    "select_api_key",
    "choose_cli_route",
    "migrate_cli_session",
    "resolve_session",
    "get_allocation_store",
    "resume_kwargs_for_session",
    "fingerprint_api_key",
    "ensure_cli_tool",
    "select_efficient_model",
    "select_efficient_route",
    "discover_available_providers",
    "intelligence_cost_matrix",
    "populate_cli_models",
    "populate_intelligence_index",
    "populate_router_catalog",
    "populate_typesafe_models",
    "system_one",
    "TypeSafeClient",
    "Noul",
    "Choice",
    "Score",
    "TypeSafeInferenceError",
    "llm_router_available",
    "llm_allocation_available",
    "embed_texts",
    "embed_texts_batched",
    "embed_text",
    "get_embeddings_provider",
    "get_embedding_progress",
    "get_last_embedding_trace",
    "register_embeddings_provider",
    "clear_embeddings_router_caches",
    "EmbeddingsRouterError",
    "EmbeddingsProvider",
    "embeddings_router_available",
    "generate_multimodal",
    "get_multimodal_provider",
    "register_multimodal_provider",
    "clear_multimodal_router_caches",
    "MultimodalProvider",
    "multimodal_router_available",
    "text_to_speech",
    "get_tts_provider",
    "register_tts_provider",
    "clear_tts_router_caches",
    "TTSProvider",
    "tts_router_available",
    "speech_to_text",
    "get_voice_provider",
    "register_voice_provider",
    "get_voice_provider_capabilities",
    "clear_voice_router_caches",
    "VoiceProvider",
    "voice_router_available",
    "VoiceProviderCapabilities",
    "ProviderInfo",
    "VOICE_TURN_CONTRACT_VERSION",
    "VOICE_STAGE_STATUSES",
    "VOICE_TURN_STATUSES",
    "DEFAULT_GROUNDED_FALLBACK",
    "GroundingEvidence",
    "VoiceGroundingSource",
    "GroundedSlot",
    "VoiceResponsePlan",
    "VoiceTemplateProvider",
    "GraphRAGVoiceTemplateProvider",
    "buildVoiceGraphRagPromptParts",
    "VoiceStageTrace",
    "VoiceTurnRequest",
    "VoiceTurnProvenance",
    "VoiceTurnResult",
    "voice_turn_cache_key",
    "process_voice_turn",
]


# Narrow proof-reuse bootstrap names are intentionally *not* part of the
# historical ``export`` / ``__all__`` accelerator surface.  They remain
# available through lazy ``__getattr__`` so direct-node zero-config code can
# request them without pulling the rest of the package.
_PROOF_REUSE_BOOTSTRAP_EXPORTS = frozenset(_GROUP_MEMBERS["proof_reuse_bootstrap"])


def __getattr__(name: str) -> Any:
    if name == "worker":
        return _load_legacy_worker()
    if name in _NAME_TO_GROUP:
        return _resolve_public(name)
    if name == "cli_main" and SKIP_CORE:
        return None
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class _IPFSAccelerateModule(ModuleType):
    """Keep the lazy root worker canonical across subpackage import order."""

    def __getattribute__(self, name: str) -> Any:
        if name == "worker":
            namespace = ModuleType.__getattribute__(self, "__dict__")
            return namespace["_load_legacy_worker"]()
        namespace = ModuleType.__getattribute__(self, "__dict__")
        # Prefer an already-imported submodule over a lazy public export so
        # dotted monkeypatch paths and sandbox workers can walk the package.
        try:
            return ModuleType.__getattribute__(self, name)
        except AttributeError:
            pass
        if name in namespace.get("_NAME_TO_GROUP", ()):
            return namespace["_resolve_public"](name)
        module_name = str(namespace.get("__name__") or "")
        loaded = sys.modules.get(f"{module_name}.{name}" if module_name else name)
        if loaded is not None and loaded is not self:
            ModuleType.__setattr__(self, name, loaded)
            return loaded
        raise AttributeError(
            f"module {module_name!r} has no attribute {name!r}"
        )

    def __setattr__(self, name: str, value: Any) -> None:
        if name != "worker":
            ModuleType.__setattr__(self, name, value)
            return
        namespace = ModuleType.__getattribute__(self, "__dict__")
        if (
            isinstance(value, ModuleType)
            and value.__name__ == f"{namespace['__name__']}.worker"
        ):
            ModuleType.__setattr__(self, name, value)
            return
        condition = namespace["_worker_condition"]
        with condition:
            while (
                namespace["_worker_loading"]
                and namespace["_worker_loader_thread_id"]
                != threading.get_ident()
            ):
                condition.wait()
            namespace["_worker_export_value"] = value
            ModuleType.__setattr__(self, name, value)
            export_map = namespace.get("export")
            if isinstance(export_map, dict):
                dict.__setitem__(export_map, "worker", value)
            condition.notify_all()

    def __delattr__(self, name: str) -> None:
        if name != "worker":
            ModuleType.__delattr__(self, name)
            return
        namespace = ModuleType.__getattribute__(self, "__dict__")
        condition = namespace["_worker_condition"]
        with condition:
            while namespace["_worker_loading"]:
                condition.wait()
            namespace["_worker_export_value"] = (
                None
                if namespace["SKIP_CORE"]
                else namespace["_WORKER_UNRESOLVED"]
            )
            namespace.pop("worker", None)
            export_map = namespace.get("export")
            if isinstance(export_map, dict):
                dict.__setitem__(
                    export_map,
                    "worker",
                    None
                    if namespace["SKIP_CORE"]
                    else namespace["_worker_snapshot"],
                )
            condition.notify_all()

    def __dir__(self) -> list[str]:
        namespace = ModuleType.__getattribute__(self, "__dict__")
        return sorted(set(namespace).union(namespace.get("__all__", ())))


sys.modules[__name__].__class__ = _IPFSAccelerateModule

# Packaging pin — must match pyproject.toml / setup.py (documentation-gates).
_PACKAGING_VERSION = "0.0.45"
__version__ = _PACKAGING_VERSION
