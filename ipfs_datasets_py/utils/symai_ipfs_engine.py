"""IPFS-backed SyMAI engine router.

Routes SyMAI engine calls through ipfs_accelerate_py when available, otherwise
falls back to local HuggingFace transformers, Gemini CLI, or Claude CLI.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import hashlib
import importlib.util
from pathlib import Path
from copy import deepcopy
from typing import Any, Dict, List, Tuple

from symai.backend.base import Engine
from symai.backend.settings import SYMAI_CONFIG

try:
    from ipfs_datasets_py.embeddings_router import embed_texts
except Exception:
    embed_texts = None

try:
    from ipfs_datasets_py.utils.gemini_cli import GeminiCLI
except Exception:
    GeminiCLI = None

try:
    from ipfs_datasets_py.utils.claude_cli import ClaudeCLI
except Exception:
    ClaudeCLI = None


_ENGINE_MODEL_KEYS = {
    "embedding": "EMBEDDING_ENGINE_MODEL",
    "search": "SEARCH_ENGINE_MODEL",
    "ocr": "OCR_ENGINE_MODEL",
    "speech_to_text": "SPEECH_TO_TEXT_ENGINE_MODEL",
    "text_to_speech": "TEXT_TO_SPEECH_ENGINE_MODEL",
    "drawing": "DRAWING_ENGINE_MODEL",
    "vision": "VISION_ENGINE_MODEL",
    "caption": "CAPTION_ENGINE_MODEL",
    "indexing": "INDEXING_ENGINE_ENVIRONMENT",
}


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _dry_run_enabled() -> bool:
    return _truthy(os.environ.get("IPFS_DATASETS_PY_SYMAI_ROUTER_DRY_RUN"))


def _dry_run_json_object(prompt: str) -> str:
    lowered = str(prompt or "").lower()
    fol_formula = "∀x (Student(x) → Studies(x))" if "student" in lowered else "∀x (Cat(x) → Animal(x))"
    payload: Dict[str, Any] = {
        "fol_formula": fol_formula,
        "confidence": 0.9,
        "logical_components": {
            "quantifiers": ["∀"],
            "predicates": ["Student", "Studies"] if "student" in lowered else ["Cat", "Animal"],
        },
        "reasoning_steps": ["dry-run"],
        "validation_results": {"syntax": "skipped"},
        "warnings": ["dry_run"],
        "metadata": {"backend": "dry_run"},
    }
    return json.dumps(payload, ensure_ascii=False)


def _symai_cache_enabled() -> bool:
    value = os.environ.get("IPFS_DATASETS_PY_SYMAI_ROUTER_CACHE")
    if value is None:
        # Default to enabled in benchmark contexts (determinism + speed), off otherwise.
        return _truthy(os.environ.get("IPFS_DATASETS_PY_BENCHMARK"))
    return str(value).strip() != "0"


def _symai_cache_key_strategy() -> str:
    """Return request-cache key strategy.

    - "cid" (default): CIDv1 derived from request payload
    - "sha256": compact deterministic sha256 key
    """

    return os.environ.get("IPFS_DATASETS_PY_SYMAI_CACHE_KEY", "cid").strip().lower() or "cid"


def _symai_cache_cid_base() -> str:
    return os.environ.get("IPFS_DATASETS_PY_SYMAI_CACHE_CID_BASE", "base32").strip() or "base32"


def _symai_backend_policy() -> str:
    value = os.environ.get("IPFS_DATASETS_PY_SYMAI_BACKEND")
    if value is None:
        value = os.environ.get("IPFS_DATASETS_PY_SYMAI_BACKENDS")
    return (value or "auto").strip() or "auto"


def _backend_capabilities_fingerprint() -> Dict[str, Any]:
    """Best-effort backend availability snapshot.

    This is included in cache keys to avoid cross-machine mismatches when
    different machines have different available backends.
    """

    return {
        "ipfs_accelerate_py": importlib.util.find_spec("ipfs_accelerate_py") is not None,
        "copilot_sdk": importlib.util.find_spec("copilot") is not None,
        "gemini_cli": _cli_available(os.environ.get("IPFS_DATASETS_PY_GEMINI_CLI_CMD", "npx @google/gemini-cli")),
        "claude_code": _cli_available(os.environ.get("IPFS_DATASETS_PY_CLAUDE_CODE_CLI_CMD", "claude")),
        "copilot_cli": _cli_available(os.environ.get("IPFS_DATASETS_PY_COPILOT_CLI_CMD", "copilot")),
        "transformers": importlib.util.find_spec("transformers") is not None,
        "torch": importlib.util.find_spec("torch") is not None,
    }


def _symai_request_cache_key(
    *,
    engine_id: str,
    mode: str,
    model_name: str,
    prompt: str,
    wants_json: bool,
) -> str:
    payload: Dict[str, Any] = {
        "v": 1,
        "kind": "symai_ipfs_engine",
        "engine_id": str(engine_id or ""),
        "mode": str(mode or ""),
        "model": str(model_name or ""),
        "prompt": str(prompt or ""),
        "wants_json": bool(wants_json),
        "backend_policy": _symai_backend_policy(),
        "backend_caps": _backend_capabilities_fingerprint(),
        "max_tokens": os.environ.get("IPFS_DATASETS_PY_SYMAI_MAX_TOKENS", ""),
        "hf_model": os.environ.get("IPFS_DATASETS_PY_SYMAI_HF_MODEL", ""),
        "copilot_sdk_model": os.environ.get("IPFS_DATASETS_PY_COPILOT_SDK_MODEL", ""),
    }

    strategy = _symai_cache_key_strategy()
    if strategy == "sha256":
        try:
            from ipfs_datasets_py.utils.cid_utils import canonical_json_bytes

            digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        except Exception:
            digest = hashlib.sha256(repr(sorted(payload.items())).encode("utf-8")).hexdigest()
        return f"symai:{digest}"

    # Default: CID (CIDv1, sha2-256, raw) derived from the request payload.
    try:
        from ipfs_datasets_py.utils.cid_utils import cid_for_obj

        return cid_for_obj(payload, base=_symai_cache_cid_base())
    except Exception:
        # Fallback: still deterministic and content-addressed, but not a multiformats CID.
        try:
            from ipfs_datasets_py.utils.cid_utils import canonical_json_bytes

            digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        except Exception:
            digest = hashlib.sha256(repr(sorted(payload.items())).encode("utf-8")).hexdigest()
        return f"symai:{digest}"


def _get_symai_router_deps():
    """Return RouterDeps, best-effort wiring a remote cache when opted in."""

    try:
        from ipfs_datasets_py.router_deps import get_default_router_deps

        deps = get_default_router_deps()
    except Exception:
        return None

    # If a remote cache is already injected, use it.
    if getattr(deps, "remote_cache", None) is not None:
        return deps

    # Opt-in auto-wiring (kept conservative to avoid import-time side effects).
    enable = _truthy(os.environ.get("IPFS_DATASETS_PY_SYMAI_REMOTE_CACHE")) or _truthy(
        os.environ.get("IPFS_DATASETS_PY_REMOTE_CACHE_NETWORK")
    )
    if not enable:
        return deps

    try:
        from ipfs_datasets_py.caching.router_remote_cache import make_ipfs_remote_cache

        # If opted in, prefer the libp2p task-service remote cache.
        try:
            from ipfs_datasets_py.caching.router_remote_cache import make_p2p_task_remote_cache

            p2p_remote = make_p2p_task_remote_cache()
            if p2p_remote is not None:
                deps.remote_cache = p2p_remote
                return deps
        except Exception:
            pass

        deps.remote_cache = make_ipfs_remote_cache(deps=deps)
    except Exception:
        deps.remote_cache = None
    return deps


def _wants_json_response(argument, prompt: str) -> bool:
    response_format = getattr(argument.prop, "response_format", None)
    if response_format is None:
        payload = getattr(argument.prop, "payload", None)
        if isinstance(payload, dict):
            response_format = payload.get("response_format")

    if isinstance(response_format, dict) and response_format.get("type") == "json_object":
        return True

    lowered = str(prompt or "").lower()
    return any(token in lowered for token in ["return a json object", "valid json object", "<output_data_model>", "[[schema]]"])


def _router_enabled() -> bool:
    return _truthy(os.environ.get("IPFS_DATASETS_PY_USE_SYMAI_ENGINE_ROUTER"))


def _codex_routing_enabled() -> bool:
    return _truthy(os.environ.get("IPFS_DATASETS_PY_USE_CODEX_FOR_SYMAI"))


def _use_router(model_value: str | None) -> bool:
    if not model_value:
        return False
    return str(model_value).startswith("ipfs:")


def _extract_model(model_value: str | None) -> str:
    if not model_value:
        return ""
    model_str = str(model_value)
    if model_str.startswith("ipfs:"):
        return model_str[len("ipfs:") :]
    return model_str


def _parse_backend_list(value: str | None) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _preferred_backends() -> List[str]:
    value = os.environ.get("IPFS_DATASETS_PY_SYMAI_BACKEND")
    if not value:
        value = os.environ.get("IPFS_DATASETS_PY_SYMAI_BACKENDS")
    if not value:
        return []
    if value.strip().lower() in {"auto", "default"}:
        return []
    return _parse_backend_list(value)


def _configure_neurosymbolic_router() -> None:
    if not _router_enabled() or _codex_routing_enabled():
        return

    router_model = os.environ.get("IPFS_DATASETS_PY_SYMAI_NEUROSYMBOLIC_MODEL", "ipfs:default")
    current_env_model = os.environ.get("NEUROSYMBOLIC_ENGINE_MODEL", "")
    if not current_env_model or current_env_model.startswith("codex:"):
        os.environ["NEUROSYMBOLIC_ENGINE_MODEL"] = router_model
    if not os.environ.get("NEUROSYMBOLIC_ENGINE_API_KEY"):
        os.environ["NEUROSYMBOLIC_ENGINE_API_KEY"] = "ipfs"

    current_model = SYMAI_CONFIG.get("NEUROSYMBOLIC_ENGINE_MODEL")
    if not isinstance(current_model, str):
        SYMAI_CONFIG["NEUROSYMBOLIC_ENGINE_MODEL"] = os.environ["NEUROSYMBOLIC_ENGINE_MODEL"]
    elif current_model.startswith("codex:"):
        SYMAI_CONFIG["NEUROSYMBOLIC_ENGINE_MODEL"] = os.environ["NEUROSYMBOLIC_ENGINE_MODEL"]
    elif not current_model.startswith("ipfs:"):
        SYMAI_CONFIG["NEUROSYMBOLIC_ENGINE_MODEL"] = os.environ["NEUROSYMBOLIC_ENGINE_MODEL"]
    if not SYMAI_CONFIG.get("NEUROSYMBOLIC_ENGINE_API_KEY"):
        SYMAI_CONFIG["NEUROSYMBOLIC_ENGINE_API_KEY"] = os.environ["NEUROSYMBOLIC_ENGINE_API_KEY"]


def _hf_generate(prompt: str, model_name: str) -> str:
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except Exception as exc:
        raise RuntimeError("transformers/torch not available for HF fallback") from exc

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(model_name)
    model.to(device)
    model.eval()

    inputs = tokenizer(prompt, return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}
    max_new_tokens = int(os.environ.get("IPFS_DATASETS_PY_SYMAI_MAX_TOKENS", "256"))

    with torch.no_grad():
        output = model.generate(**inputs, max_new_tokens=max_new_tokens)
    decoded = tokenizer.decode(output[0], skip_special_tokens=True)
    if decoded.startswith(prompt):
        return decoded[len(prompt):].lstrip()
    return decoded


def _gemini_generate(prompt: str) -> str:
    if GeminiCLI is None:
        raise RuntimeError("Gemini CLI support not available")
    client = GeminiCLI()
    result = client.execute(["generate", prompt], capture_output=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Gemini CLI failed")
    return (result.stdout or "").strip()


def _claude_generate(prompt: str) -> str:
    if ClaudeCLI is None:
        raise RuntimeError("Claude CLI support not available")
    client = ClaudeCLI()
    result = client.execute(["chat", prompt], capture_output=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Claude CLI failed")
    return (result.stdout or "").strip()


def _cli_available(command: str) -> bool:
    if not command:
        return False
    parts = shlex.split(command)
    if not parts:
        return False
    if parts[0] == "npx":
        return True
    return shutil.which(parts[0]) is not None


def _local_bin_paths() -> List[str]:
    project_root = Path(
        os.getenv("IPFS_DATASETS_PROJECT_ROOT", str(Path(__file__).resolve().parents[1]))
    ).resolve()
    bin_dir = Path(os.getenv("IPFS_DATASETS_LOCAL_BIN", str(project_root / "bin"))).resolve()
    npm_prefix = Path(os.getenv("IPFS_DATASETS_NPM_PREFIX", str(bin_dir / ".deps" / "npm"))).resolve()
    npm_bin = npm_prefix / "bin"
    return [str(bin_dir), str(npm_bin)]


def _resolve_copilot_cli_path() -> str | None:
    env_path = os.environ.get("COPILOT_CLI_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    for base_path in _local_bin_paths():
        candidate = Path(base_path) / "copilot"
        if candidate.exists():
            return str(candidate)

    resolved = shutil.which("copilot")
    if resolved:
        return resolved
    return None


def _run_cli_command(command: str, prompt: str) -> str:
    if not command:
        raise RuntimeError("CLI command not configured")
    if "{prompt}" in command:
        rendered = command.replace("{prompt}", prompt)
        cmd = shlex.split(rendered)
    else:
        cmd = shlex.split(command)
        cmd.append(prompt)
    env = os.environ.copy()
    local_paths = [p for p in _local_bin_paths() if p]
    if local_paths:
        current_path = env.get("PATH", "")
        env["PATH"] = os.pathsep.join(local_paths + [current_path])
    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "CLI command failed")
    return (proc.stdout or "").strip()


def _gemini_cli_generate(prompt: str) -> str:
    command = os.environ.get("IPFS_DATASETS_PY_GEMINI_CLI_CMD", "npx @google/gemini-cli")
    return _run_cli_command(command, prompt)


def _copilot_cli_generate(prompt: str) -> str:
    command = os.environ.get(
        "IPFS_DATASETS_PY_COPILOT_CLI_CMD",
        "npx --yes @github/copilot -p",
    )
    return _run_cli_command(command, prompt)


def _claude_code_generate(prompt: str) -> str:
    command = os.environ.get("IPFS_DATASETS_PY_CLAUDE_CODE_CLI_CMD", "claude")
    return _run_cli_command(command, prompt)


def _copilot_sdk_generate(prompt: str) -> str:
    try:
        import copilot  # type: ignore
    except Exception as exc:
        raise RuntimeError("copilot-sdk not available") from exc

    cli_path = _resolve_copilot_cli_path()
    if cli_path:
        os.environ["COPILOT_CLI_PATH"] = cli_path
    model = os.environ.get("IPFS_DATASETS_PY_COPILOT_SDK_MODEL", "").strip()
    timeout_seconds = float(os.environ.get("IPFS_DATASETS_PY_COPILOT_SDK_TIMEOUT", "120"))

    async def _run() -> str:
        options = {}
        if cli_path:
            options["cli_path"] = cli_path
        client = copilot.CopilotClient(options or None)
        await client.start()
        if model:
            session = await client.create_session({"model": model})
        else:
            session = await client.create_session()
        try:
            from ipfs_datasets_py.utils.anyio_compat import fail_after

            try:
                with fail_after(timeout_seconds):
                    event = await session.send_and_wait({"prompt": prompt})
            except TimeoutError as exc:
                raise RuntimeError(
                    f"copilot_sdk timeout after {timeout_seconds:.1f}s waiting for session.idle"
                ) from exc
            if event and getattr(event, "data", None) is not None:
                content = getattr(event.data, "content", None)
                if content is not None:
                    return str(content)
            return ""
        finally:
            await session.destroy()
            await client.stop()

    try:
        from ipfs_datasets_py.utils.anyio_compat import AsyncContextError, run as run_anyio

        return run_anyio(_run())
    except AsyncContextError:
        raise RuntimeError("copilot-sdk requires a non-running event loop context")


def _generate_text(prompt: str, model_name: str) -> Tuple[str, Dict[str, Any]]:
    metadata: Dict[str, Any] = {"backend": "llm_router", "errors": []}

    # NOTE:
    # Historically this router cascaded across multiple CLIs/SDKs (Copilot SDK, Gemini CLI,
    # Claude Code, HuggingFace local) which can be expensive and can explode memory when
    # SymbolicAI issues many `.query()` calls in tight loops (as in integration tests).
    #
    # We now route ALL SyMAI generation through the single top-level
    # `ipfs_datasets_py.llm_router.generate_text` path so provider selection, caching,
    # and dependency injection are centralized.

    if _dry_run_enabled():
        # Preserve existing dry-run behavior for deterministic/offline operation.
        if _wants_json_response(None, str(prompt)):
            return [_dry_run_json_object(str(prompt))][0], {"backend": "dry_run", "format": "json"}
        return "OK", {"backend": "dry_run"}

    try:
        from ipfs_datasets_py import llm_router

        deps = _get_symai_router_deps()
        provider = os.environ.get("IPFS_DATASETS_PY_LLM_PROVIDER") or None
        text = llm_router.generate_text(
            str(prompt),
            model_name=model_name or None,
            provider=provider,
            deps=deps,
        )
        return str(text), metadata
    except Exception as exc:
        metadata["errors"].append(str(exc))
        raise RuntimeError("SyMAI llm_router generation failed: " + "; ".join(metadata["errors"]))


class IPFSSyMAIEngine(Engine):
    """SyMAI engine router for non-neurosymbolic engines."""

    def __init__(self, engine_id: str, model_key: str, mode: str = "text") -> None:
        super().__init__()
        self.config = deepcopy(SYMAI_CONFIG)
        self.engine_id = engine_id
        self.model_key = model_key
        self.mode = mode
        if self.id() != engine_id:
            return
        self.model = _extract_model(self.config.get(model_key, ""))

    def id(self) -> str:
        model_value = self.config.get(self.model_key)
        if _use_router(model_value):
            return self.engine_id
        return super().id()

    def prepare(self, argument):
        if getattr(argument.prop, "raw_input", False):
            argument.prop.prepared_input = str(argument.prop.processed_input)
            return

        parts: List[str] = []

        response_format = getattr(argument.prop, "response_format", None)
        if response_format is None:
            payload = getattr(argument.prop, "payload", None)
            if isinstance(payload, dict):
                response_format = payload.get("response_format")

        prompt = getattr(argument.prop, "prompt", None)
        if prompt:
            parts.append(str(prompt).strip())

        processed = getattr(argument.prop, "processed_input", "")
        if processed:
            parts.append(str(processed))

        if isinstance(response_format, dict) and response_format.get("type") == "json_object":
            parts.append("\n\nIMPORTANT: Return only a valid JSON object. Do not include extra text.")
        else:
            parts.append(
                "\n\nIMPORTANT: Return only the final answer text. Do not run commands. Do not describe steps."
            )

        argument.prop.prepared_input = "\n\n".join([p for p in parts if p])

    def forward(self, argument) -> Tuple[List[str], Dict[str, Any]]:
        prompt = argument.prop.prepared_input

        wants_json = False
        try:
            wants_json = _wants_json_response(argument, str(prompt))
        except Exception:
            wants_json = False

        cache_key: str | None = None
        deps = None
        if self.mode != "embedding" and _symai_cache_enabled():
            cache_key = _symai_request_cache_key(
                engine_id=self.engine_id,
                mode=self.mode,
                model_name=getattr(self, "model", "") or "",
                prompt=str(prompt or ""),
                wants_json=wants_json,
            )
            deps = _get_symai_router_deps()
            getter = getattr(deps, "get_cached_or_remote", None) if deps is not None else None
            if callable(getter):
                cached = getter(cache_key)
            else:
                cached = None

            if isinstance(cached, dict) and "text" in cached:
                metadata = dict(cached.get("metadata") or {})
                if metadata.get("backend") not in (None, "", "cache"):
                    metadata.setdefault("cached_backend", metadata.get("backend"))
                metadata["backend"] = "cache"
                metadata["cache"] = "hit"
                metadata["cache_key"] = cache_key
                return [str(cached.get("text") or "")], metadata

        if _dry_run_enabled():
            if self.mode == "embedding":
                return [json.dumps([0.0, 0.0, 0.0])], {"backend": "dry_run"}
            if _wants_json_response(argument, str(prompt)):
                return [_dry_run_json_object(str(prompt))], {"backend": "dry_run", "format": "json"}
            return ["OK"], {"backend": "dry_run"}

        if self.mode == "embedding":
            if embed_texts is None:
                raise RuntimeError("Embedding adapter not available")
            embeddings = embed_texts([prompt])
            return [json.dumps(embeddings[0])], {"backend": "embedding_adapter"}

        text, metadata = _generate_text(prompt, self.model)
        if cache_key and deps is not None:
            setter = getattr(deps, "set_cached_and_remote", None)
            if callable(setter):
                setter(
                    cache_key,
                    {
                        "text": text,
                        "metadata": metadata,
                        "engine_id": self.engine_id,
                        "mode": self.mode,
                        "model": getattr(self, "model", "") or "",
                        "format": "json" if wants_json else "text",
                    },
                )
        if cache_key:
            metadata = dict(metadata or {})
            metadata["cache"] = "miss"
            metadata["cache_key"] = cache_key
        return [text], metadata


class IPFSSyMAISymbolicEngine(IPFSSyMAIEngine):
    """SyMAI symbolic engine router (SYMBOLIC_ENGINE)."""

    def id(self) -> str:
        if self.config.get("SYMBOLIC_ENGINE") == "ipfs":
            return self.engine_id
        return super().id()


class IPFSSyMAINeurosymbolicEngine(IPFSSyMAIEngine):
    """SyMAI neurosymbolic engine router (NEUROSYMBOLIC_ENGINE_MODEL)."""
    def __init__(self, engine_id: str, model_key: str, mode: str = "text") -> None:
        super().__init__(engine_id, model_key, mode=mode)
        if not hasattr(self, "model"):
            self.model = _extract_model(self.config.get(model_key, ""))


def register_ipfs_symai_engines() -> None:
    try:
        from symai.functional import EngineRepository
    except Exception:
        return

    _configure_neurosymbolic_router()

    EngineRepository.register(
        "symbolic",
        IPFSSyMAISymbolicEngine("symbolic", "SYMBOLIC_ENGINE"),
        allow_engine_override=True,
    )
    EngineRepository.register(
        "neurosymbolic",
        IPFSSyMAINeurosymbolicEngine("neurosymbolic", "NEUROSYMBOLIC_ENGINE_MODEL"),
        allow_engine_override=True,
    )
    EngineRepository.register(
        "ipfs",
        IPFSSyMAISymbolicEngine("ipfs", "SYMBOLIC_ENGINE"),
        allow_engine_override=True,
    )
    EngineRepository.register(
        "embedding",
        IPFSSyMAIEngine("embedding", "EMBEDDING_ENGINE_MODEL", mode="embedding"),
        allow_engine_override=True,
    )
    EngineRepository.register(
        "search",
        IPFSSyMAIEngine("search", "SEARCH_ENGINE_MODEL"),
        allow_engine_override=True,
    )
    EngineRepository.register(
        "ocr",
        IPFSSyMAIEngine("ocr", "OCR_ENGINE_MODEL"),
        allow_engine_override=True,
    )
    EngineRepository.register(
        "speech_to_text",
        IPFSSyMAIEngine("speech_to_text", "SPEECH_TO_TEXT_ENGINE_MODEL"),
        allow_engine_override=True,
    )
    EngineRepository.register(
        "text_to_speech",
        IPFSSyMAIEngine("text_to_speech", "TEXT_TO_SPEECH_ENGINE_MODEL"),
        allow_engine_override=True,
    )
    EngineRepository.register(
        "drawing",
        IPFSSyMAIEngine("drawing", "DRAWING_ENGINE_MODEL"),
        allow_engine_override=True,
    )
    EngineRepository.register(
        "vision",
        IPFSSyMAIEngine("vision", "VISION_ENGINE_MODEL"),
        allow_engine_override=True,
    )
    EngineRepository.register(
        "caption",
        IPFSSyMAIEngine("caption", "CAPTION_ENGINE_MODEL"),
        allow_engine_override=True,
    )
    EngineRepository.register(
        "indexing",
        IPFSSyMAIEngine("indexing", "INDEXING_ENGINE_ENVIRONMENT"),
        allow_engine_override=True,
    )
