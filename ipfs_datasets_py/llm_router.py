"""LLM router.

This module provides a reusable top-level entrypoint for text generation.

Design goals:
- Avoid import-time side effects.
- Allow optional hooks/providers (ipfs_accelerate_py, remote endpoints).
- Provide a local HuggingFace transformers fallback when available.

Environment variables:
- `IPFS_DATASETS_PY_LLM_PROVIDER`: force provider name (registered provider)
- `IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE`: allow accelerate provider (best-effort hook)
- `IPFS_DATASETS_PY_LLM_MODEL`: default HF model name for local fallback

Additional optional providers (opt-in by selecting provider):
- `openrouter`: OpenRouter chat completions
    - `OPENROUTER_API_KEY` or `IPFS_DATASETS_PY_OPENROUTER_API_KEY`
    - `IPFS_DATASETS_PY_OPENROUTER_MODEL` (default model)
    - `IPFS_DATASETS_PY_OPENROUTER_BASE_URL` (default: https://openrouter.ai/api/v1)
- `codex_cli`: OpenAI Codex CLI via `codex exec`
    - `IPFS_DATASETS_PY_CODEX_CLI_MODEL` / `IPFS_DATASETS_PY_CODEX_MODEL`
- `copilot_cli`: GitHub Copilot CLI via command template
    - `IPFS_DATASETS_PY_COPILOT_CLI_CMD` (supports `{prompt}` placeholder)
- `copilot_sdk`: Python `copilot` SDK (if installed)
    - `IPFS_DATASETS_PY_COPILOT_SDK_MODEL`, `IPFS_DATASETS_PY_COPILOT_SDK_TIMEOUT`
- `gemini_cli`: Gemini CLI via `npx @google/gemini-cli`
    - `IPFS_DATASETS_PY_GEMINI_CLI_CMD` (supports `{prompt}` placeholder)
- `gemini_py`: Python wrapper in `ipfs_datasets_py.utils.gemini_cli.GeminiCLI`
- `claude_code`: Claude Code CLI command
    - `IPFS_DATASETS_PY_CLAUDE_CODE_CLI_CMD` (supports `{prompt}` placeholder)
- `claude_py`: Python wrapper in `ipfs_datasets_py.utils.claude_cli.ClaudeCLI`
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import importlib
from typing import Callable, Dict, Optional, Protocol, runtime_checkable

from .router_deps import RouterDeps, get_default_router_deps


def _resolve_transformers_module(*, deps: Optional[RouterDeps] = None, module_override: object | None = None) -> object | None:
    """Resolve the transformers module with optional RouterDeps injection/caching."""

    if module_override is not None:
        if deps is not None:
            deps.set_cached("pip::transformers", module_override)
        return module_override

    if deps is not None:
        cached = deps.get_cached("pip::transformers")
        if cached is not None:
            return cached

    try:
        module = importlib.import_module("transformers")
    except Exception:
        return None

    if deps is not None:
        deps.set_cached("pip::transformers", module)
    return module


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _cache_enabled() -> bool:
    return os.environ.get("IPFS_DATASETS_PY_ROUTER_CACHE", "1").strip() != "0"


def _response_cache_enabled() -> bool:
    # Default to enabled in benchmark contexts (determinism + speed), off otherwise.
    value = os.environ.get("IPFS_DATASETS_PY_ROUTER_RESPONSE_CACHE")
    if value is None:
        return _truthy(os.environ.get("IPFS_DATASETS_PY_BENCHMARK"))
    return str(value).strip() != "0"


def _response_cache_key_strategy() -> str:
    """Return the response-cache key strategy.

    - "sha256" (default): compact deterministic string key
    - "cid": content-addressed CID (sha2-256, CIDv1) for the request payload
    """

    return os.environ.get("IPFS_DATASETS_PY_ROUTER_CACHE_KEY", "sha256").strip().lower() or "sha256"


def _response_cache_cid_base() -> str:
    return os.environ.get("IPFS_DATASETS_PY_ROUTER_CACHE_CID_BASE", "base32").strip() or "base32"


def _stable_kwargs_digest(kwargs: Dict[str, object]) -> str:
    if not kwargs:
        return ""
    try:
        payload = json.dumps(kwargs, sort_keys=True, default=repr, ensure_ascii=False)
    except Exception:
        payload = repr(sorted(kwargs.items(), key=lambda x: str(x[0])))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _effective_model_key(*, provider_key: str, model_name: Optional[str], kwargs: Dict[str, object]) -> str:
    """Best-effort model identifier for caching.

    Callers are inconsistent about whether they pass the model via ``model_name``
    or via kwargs (e.g. ``model=...``). Some providers also use env defaults.
    Cache keys should include the effective model to avoid cross-model collisions.
    """

    direct = (model_name or "").strip()
    if direct:
        return direct

    for key in ("model", "model_name", "model_id"):
        try:
            value = kwargs.get(key)
        except Exception:
            value = None
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text

    pk = (provider_key or "auto").strip().lower()
    if pk == "openrouter":
        return (
            os.getenv("IPFS_DATASETS_PY_OPENROUTER_MODEL")
            or os.getenv("IPFS_DATASETS_PY_LLM_MODEL")
            or "openai/gpt-4o-mini"
        ).strip()
    if pk in {"codex", "codex_cli"}:
        return (
            _coalesce_env("IPFS_DATASETS_PY_CODEX_CLI_MODEL", "IPFS_DATASETS_PY_CODEX_MODEL")
            or "gpt-5.1-codex-mini"
        ).strip()
    if pk == "copilot_sdk":
        return (os.environ.get("IPFS_DATASETS_PY_COPILOT_SDK_MODEL", "") or "").strip()
    if pk in {"hf", "huggingface", "local_hf"}:
        return (os.getenv("IPFS_DATASETS_PY_LLM_MODEL", "gpt2") or "gpt2").strip()

    # Provider unknown/auto: include the most common default.
    return (os.getenv("IPFS_DATASETS_PY_LLM_MODEL", "") or "").strip()


def _response_cache_key(*, provider: Optional[str], model_name: Optional[str], prompt: str, kwargs: Dict[str, object]) -> str:
    provider_key = (provider or "auto").strip().lower()
    model_key = _effective_model_key(provider_key=provider_key, model_name=model_name, kwargs=kwargs)

    strategy = _response_cache_key_strategy()
    if strategy == "cid":
        from .utils.cid_utils import cid_for_obj

        payload = {
            "type": "llm_response",
            "provider": provider_key,
            "model": model_key,
            "prompt": prompt or "",
            "kwargs": kwargs or {},
        }
        cid = cid_for_obj(payload, base=_response_cache_cid_base())
        return f"llm_response_cid::{cid}"

    prompt_digest = hashlib.sha256((prompt or "").encode("utf-8")).hexdigest()[:16]
    kw_digest = _stable_kwargs_digest(kwargs)
    return f"llm_response::{provider_key}::{model_key}::{prompt_digest}::{kw_digest}"


@runtime_checkable
class LLMProvider(Protocol):
    def generate(self, prompt: str, *, model_name: Optional[str] = None, **kwargs: object) -> str: ...


ProviderFactory = Callable[[], LLMProvider]


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    factory: ProviderFactory


_PROVIDER_REGISTRY: Dict[str, ProviderInfo] = {}


def register_llm_provider(name: str, factory: ProviderFactory) -> None:
    if not name or not name.strip():
        raise ValueError("Provider name must be non-empty")
    _PROVIDER_REGISTRY[name] = ProviderInfo(name=name, factory=factory)


def _coalesce_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _cli_available(command: str) -> bool:
    if not command:
        return False
    parts = shlex.split(command)
    if not parts:
        return False
    if parts[0] == "npx":
        return True
    return shutil.which(parts[0]) is not None


def _run_cli_command(command: str, prompt: str, *, timeout_seconds: float = 120.0) -> str:
    if not command:
        raise RuntimeError("CLI command not configured")

    if "{prompt}" in command:
        rendered = command.replace("{prompt}", prompt)
        cmd = shlex.split(rendered)
        input_text: str | None = None
    else:
        cmd = shlex.split(command)
        input_text = prompt

    proc = subprocess.run(
        cmd,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
        env=os.environ.copy(),
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "CLI command failed")
    return (proc.stdout or "").strip()


def _get_openrouter_provider() -> Optional[LLMProvider]:
    api_key = _coalesce_env("IPFS_DATASETS_PY_OPENROUTER_API_KEY", "OPENROUTER_API_KEY")
    if not api_key:
        return None

    base_url = os.getenv("IPFS_DATASETS_PY_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")

    class _OpenRouterProvider:
        def generate(self, prompt: str, *, model_name: Optional[str] = None, **kwargs: object) -> str:
            model = (
                model_name
                or os.getenv("IPFS_DATASETS_PY_OPENROUTER_MODEL")
                or os.getenv("IPFS_DATASETS_PY_LLM_MODEL")
                or "openai/gpt-4o-mini"
            )

            max_tokens = kwargs.get("max_tokens", kwargs.get("max_new_tokens", 256))
            temperature = kwargs.get("temperature", 0.2)

            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": int(max_tokens),
                "temperature": float(temperature),
            }

            req = urllib.request.Request(
                f"{base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    **({"HTTP-Referer": os.getenv("OPENROUTER_HTTP_REFERER")} if os.getenv("OPENROUTER_HTTP_REFERER") else {}),
                    **({"X-Title": os.getenv("OPENROUTER_APP_TITLE")} if os.getenv("OPENROUTER_APP_TITLE") else {}),
                },
            )

            try:
                with urllib.request.urlopen(req, timeout=float(kwargs.get("timeout", 120))) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
                raise RuntimeError(f"OpenRouter HTTP {exc.code}: {detail or exc.reason}") from exc
            except Exception as exc:
                raise RuntimeError(f"OpenRouter request failed: {exc}") from exc

            try:
                data = json.loads(raw)
            except Exception as exc:
                raise RuntimeError("OpenRouter returned invalid JSON") from exc

            choices = data.get("choices")
            if isinstance(choices, list) and choices:
                msg = choices[0].get("message") if isinstance(choices[0], dict) else None
                if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                    return msg["content"].strip()
                delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
                if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                    return delta["content"].strip()
                text = choices[0].get("text") if isinstance(choices[0], dict) else None
                if isinstance(text, str):
                    return text.strip()
            raise RuntimeError("OpenRouter response missing choices")

    return _OpenRouterProvider()


def _get_codex_cli_provider() -> Optional[LLMProvider]:
    if not shutil.which("codex"):
        return None

    class _CodexCLIProvider:
        def generate(self, prompt: str, *, model_name: Optional[str] = None, **kwargs: object) -> str:
            model = model_name or _coalesce_env("IPFS_DATASETS_PY_CODEX_CLI_MODEL", "IPFS_DATASETS_PY_CODEX_MODEL")
            if not model:
                model = "gpt-5.1-codex-mini"

            sandbox = os.getenv("IPFS_DATASETS_PY_CODEX_SANDBOX", "read-only")
            skip_git_repo_check = os.getenv("IPFS_DATASETS_PY_CODEX_SKIP_GIT_REPO_CHECK", "1") != "0"

            with tempfile.NamedTemporaryFile(mode="w+", suffix=".txt", delete=False) as last_msg:
                last_msg_path = last_msg.name

            cmd: list[str] = ["codex", "exec"]
            if skip_git_repo_check:
                cmd.append("--skip-git-repo-check")
            cmd.extend(["--sandbox", sandbox])
            cmd.extend(["-m", model])
            cmd.extend(["--output-last-message", last_msg_path])
            cmd.append("-")

            try:
                proc = subprocess.run(
                    cmd,
                    input=str(prompt),
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=float(kwargs.get("timeout", 180)),
                )
            except FileNotFoundError as exc:
                raise RuntimeError("codex CLI not found on PATH") from exc

            try:
                with open(last_msg_path, "r", encoding="utf-8", errors="replace") as handle:
                    text_out = handle.read().strip()
            except Exception:
                text_out = ""

            if proc.returncode == 0 or text_out:
                return text_out
            raise RuntimeError(proc.stderr.strip() or "codex exec failed")

    return _CodexCLIProvider()


def _get_copilot_cli_provider() -> Optional[LLMProvider]:
    command = os.environ.get("IPFS_DATASETS_PY_COPILOT_CLI_CMD", "npx --yes @github/copilot -p {prompt}")
    if not _cli_available(command):
        return None

    class _CopilotCLIProvider:
        def generate(self, prompt: str, *, model_name: Optional[str] = None, **kwargs: object) -> str:
            _ = model_name
            timeout = float(kwargs.get("timeout", 180))
            return _run_cli_command(command, prompt, timeout_seconds=timeout)

    return _CopilotCLIProvider()


def _get_copilot_sdk_provider() -> Optional[LLMProvider]:
    try:
        import copilot  # type: ignore
    except Exception:
        return None

    class _CopilotSDKProvider:
        def generate(self, prompt: str, *, model_name: Optional[str] = None, **kwargs: object) -> str:
            _ = model_name
            model = os.environ.get("IPFS_DATASETS_PY_COPILOT_SDK_MODEL", "").strip()
            timeout_seconds = float(os.environ.get("IPFS_DATASETS_PY_COPILOT_SDK_TIMEOUT", "120"))

            async def _run() -> str:
                options = {}
                client = copilot.CopilotClient(options or None)
                await client.start()
                if model:
                    session = await client.create_session({"model": model})
                else:
                    session = await client.create_session()
                try:
                    event = await session.send_and_wait({"prompt": prompt})
                    if event and getattr(event, "data", None) is not None:
                        content = getattr(event.data, "content", None)
                        if content is not None:
                            return str(content)
                    return ""
                finally:
                    await session.destroy()
                    await client.stop()

            try:
                import asyncio

                asyncio.get_running_loop()
            except RuntimeError:
                return __import__("asyncio").run(__import__("asyncio").wait_for(_run(), timeout=timeout_seconds))

            raise RuntimeError("copilot-sdk requires a non-running event loop context")

    return _CopilotSDKProvider()


def _get_gemini_cli_provider() -> Optional[LLMProvider]:
    command = os.environ.get("IPFS_DATASETS_PY_GEMINI_CLI_CMD", "npx @google/gemini-cli {prompt}")
    if not _cli_available(command):
        return None

    class _GeminiCLIProvider:
        def generate(self, prompt: str, *, model_name: Optional[str] = None, **kwargs: object) -> str:
            _ = model_name
            timeout = float(kwargs.get("timeout", 180))
            return _run_cli_command(command, prompt, timeout_seconds=timeout)

    return _GeminiCLIProvider()


def _get_gemini_py_provider() -> Optional[LLMProvider]:
    try:
        from ipfs_datasets_py.utils.gemini_cli import GeminiCLI
    except Exception:
        return None

    class _GeminiPyProvider:
        def generate(self, prompt: str, *, model_name: Optional[str] = None, **kwargs: object) -> str:
            _ = model_name
            client = GeminiCLI(use_accelerate=_truthy(os.getenv("IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE")))
            timeout = int(float(kwargs.get("timeout", 180)))
            result = client.execute(["generate", prompt], capture_output=True, timeout=timeout)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "Gemini (python wrapper) failed")
            return (result.stdout or "").strip()

    return _GeminiPyProvider()


def _get_claude_code_provider() -> Optional[LLMProvider]:
    command = os.environ.get("IPFS_DATASETS_PY_CLAUDE_CODE_CLI_CMD", "claude {prompt}")
    if not _cli_available(command):
        return None

    class _ClaudeCodeProvider:
        def generate(self, prompt: str, *, model_name: Optional[str] = None, **kwargs: object) -> str:
            _ = model_name
            timeout = float(kwargs.get("timeout", 180))
            return _run_cli_command(command, prompt, timeout_seconds=timeout)

    return _ClaudeCodeProvider()


def _get_claude_py_provider() -> Optional[LLMProvider]:
    try:
        from ipfs_datasets_py.utils.claude_cli import ClaudeCLI
    except Exception:
        return None

    class _ClaudePyProvider:
        def generate(self, prompt: str, *, model_name: Optional[str] = None, **kwargs: object) -> str:
            _ = model_name
            client = ClaudeCLI(use_accelerate=_truthy(os.getenv("IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE")))
            timeout = int(float(kwargs.get("timeout", 180)))
            result = client.execute(["chat", prompt], capture_output=True, timeout=timeout)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "Claude (python wrapper) failed")
            return (result.stdout or "").strip()

    return _ClaudePyProvider()


def _get_accelerate_provider(deps: RouterDeps) -> Optional[LLMProvider]:
    if not _truthy(os.getenv("IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE")):
        return None

    try:
        manager = deps.get_accelerate_manager(
            purpose="llm_router",
            enable_distributed=True,
            resources={"purpose": "llm_router"},
        )
        if manager is None:
            return None

        class _AccelerateLLMProvider:
            def generate(self, prompt: str, *, model_name: Optional[str] = None, **kwargs: object) -> str:
                # Best-effort hook: if accelerate cannot produce an answer, raise so
                # the router can fall back.
                payload = {"prompt": prompt, **kwargs}
                result = manager.run_inference(
                    model_name or os.getenv("IPFS_DATASETS_PY_LLM_MODEL", ""),
                    payload,
                    task_type="text-generation",
                )
                text = result.get("text")
                if isinstance(text, str) and text:
                    return text
                raise RuntimeError("ipfs_accelerate_py provider did not return generated text")

        return _AccelerateLLMProvider()
    except Exception:
        return None


def _provider_cache_key() -> tuple:
    # Include only env vars that change provider resolution.
    return (
        os.getenv("IPFS_DATASETS_PY_LLM_PROVIDER", "").strip(),
        os.getenv("IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE", "").strip(),
        os.getenv("IPFS_DATASETS_PY_OPENROUTER_API_KEY", "").strip(),
        os.getenv("OPENROUTER_API_KEY", "").strip(),
        os.getenv("IPFS_DATASETS_PY_OPENROUTER_MODEL", "").strip(),
        os.getenv("IPFS_DATASETS_PY_OPENROUTER_BASE_URL", "").strip(),
        os.getenv("IPFS_DATASETS_PY_CODEX_CLI_MODEL", "").strip(),
        os.getenv("IPFS_DATASETS_PY_CODEX_MODEL", "").strip(),
        os.getenv("IPFS_DATASETS_PY_COPILOT_CLI_CMD", "").strip(),
        os.getenv("IPFS_DATASETS_PY_GEMINI_CLI_CMD", "").strip(),
        os.getenv("IPFS_DATASETS_PY_CLAUDE_CODE_CLI_CMD", "").strip(),
    )


def _deps_provider_cache_key(preferred: Optional[str], cache_key: tuple) -> str:
    digest = hashlib.sha256(repr(cache_key).encode("utf-8")).hexdigest()[:16]
    return f"llm_provider::{(preferred or '').strip().lower()}::{digest}"


@lru_cache(maxsize=32)
def _resolve_provider_cached(preferred: Optional[str], cache_key: tuple) -> LLMProvider:
    _ = cache_key
    # Use default deps here; custom deps are handled in get_llm_provider.
    return _resolve_provider_uncached(preferred, deps=get_default_router_deps())


def _get_local_hf_provider(*, deps: Optional[RouterDeps] = None) -> Optional[LLMProvider]:
    transformers = _resolve_transformers_module(deps=deps)
    if transformers is None:
        return None

    pipeline = getattr(transformers, "pipeline", None)
    if pipeline is None:
        return None

    class _LocalHFProvider:
        def __init__(self) -> None:
            self._pipelines: Dict[str, object] = {}

        def generate(self, prompt: str, *, model_name: Optional[str] = None, **kwargs: object) -> str:
            model = model_name or os.getenv("IPFS_DATASETS_PY_LLM_MODEL", "gpt2")
            pipe = self._pipelines.get(model)
            if pipe is None:
                pipe = pipeline("text-generation", model=model)
                self._pipelines[model] = pipe

            max_new_tokens = int(kwargs.pop("max_new_tokens", kwargs.pop("max_tokens", 128)))
            out = pipe(prompt, max_new_tokens=max_new_tokens)
            if isinstance(out, list) and out:
                item = out[0]
                if isinstance(item, dict) and isinstance(item.get("generated_text"), str):
                    return item["generated_text"]
            return str(out)

    return _LocalHFProvider()


def _builtin_provider_by_name(name: str) -> Optional[LLMProvider]:
    key = (name or "").strip().lower()
    if not key:
        return None
    if key == "openrouter":
        return _get_openrouter_provider()
    if key in {"codex", "codex_cli"}:
        return _get_codex_cli_provider()
    if key in {"copilot_cli"}:
        return _get_copilot_cli_provider()
    if key in {"copilot_sdk"}:
        return _get_copilot_sdk_provider()
    if key in {"gemini_cli"}:
        return _get_gemini_cli_provider()
    if key in {"gemini_py"}:
        return _get_gemini_py_provider()
    if key in {"claude_code"}:
        return _get_claude_code_provider()
    if key in {"claude", "claude_py"}:
        return _get_claude_py_provider()
    if key in {"hf", "huggingface", "local_hf"}:
        return _get_local_hf_provider(deps=get_default_router_deps())
    return None


def _resolve_provider_uncached(preferred: Optional[str], *, deps: RouterDeps) -> LLMProvider:
    if preferred:
        info = _PROVIDER_REGISTRY.get(preferred)
        if info is not None:
            return info.factory()
        builtin = _builtin_provider_by_name(preferred)
        if builtin is not None:
            return builtin
        raise ValueError(f"Unknown LLM provider: {preferred}")

    forced = os.getenv("IPFS_DATASETS_PY_LLM_PROVIDER", "").strip()
    if forced:
        info = _PROVIDER_REGISTRY.get(forced)
        if info is not None:
            return info.factory()
        builtin = _builtin_provider_by_name(forced)
        if builtin is not None:
            return builtin
        raise ValueError(f"Unknown LLM provider: {forced}")

    accelerate_provider = _get_accelerate_provider(deps)
    if accelerate_provider is not None:
        return accelerate_provider

    # Try common optional CLI/API providers if available.
    for name in ["openrouter", "codex_cli", "copilot_cli", "gemini_cli", "claude_code", "claude_py", "gemini_py", "copilot_sdk"]:
        candidate = _builtin_provider_by_name(name)
        if candidate is not None:
            return candidate

    local_hf = _get_local_hf_provider(deps=deps)
    if local_hf is not None:
        return local_hf

    raise RuntimeError(
        "No LLM provider available. Install `transformers` or register a custom provider."
    )


def get_llm_provider(
    provider: Optional[str] = None,
    *,
    deps: Optional[RouterDeps] = None,
    use_cache: Optional[bool] = None,
) -> LLMProvider:
    """Resolve an LLM provider with optional dependency injection.

    - If ``deps`` is provided, the router will reuse injected/cached dependencies
      (e.g., AccelerateManager) stored on that object.
    - If caching is enabled, provider instances are reused in-process to avoid
      repeated initialization cascades.
    """

    resolved_deps = deps or get_default_router_deps()
    cache_ok = _cache_enabled() if use_cache is None else bool(use_cache)

    if not cache_ok:
        return _resolve_provider_uncached(provider, deps=resolved_deps)

    # If a deps container was explicitly provided, cache the provider instance on it.
    # This preserves per-provider internal caches (e.g., HF pipelines) and prevents
    # repeated initialization across call sites and repos.
    if deps is not None:
        cache_key = _provider_cache_key()
        deps_key = _deps_provider_cache_key(provider, cache_key)
        cached = resolved_deps.get_cached(deps_key)
        if cached is not None:
            return cached
        return resolved_deps.set_cached(deps_key, _resolve_provider_uncached(provider, deps=resolved_deps))

    # Process-global caching path.
    return _resolve_provider_cached(provider, _provider_cache_key())


def generate_text(
    prompt: str,
    *,
    model_name: Optional[str] = None,
    provider: Optional[str] = None,
    provider_instance: Optional[LLMProvider] = None,
    deps: Optional[RouterDeps] = None,
    **kwargs: object,
) -> str:
    """Generate text from an LLM."""

    resolved_deps = deps or get_default_router_deps()
    if _response_cache_enabled():
        try:
            cache_key = _response_cache_key(provider=provider, model_name=model_name, prompt=prompt, kwargs=dict(kwargs))
            getter = getattr(resolved_deps, "get_cached_or_remote", None)
            cached = getter(cache_key) if callable(getter) else resolved_deps.get_cached(cache_key)
            if isinstance(cached, str):
                return cached
        except Exception:
            pass

    backend = provider_instance or get_llm_provider(provider, deps=resolved_deps)
    try:
        result = backend.generate(prompt, model_name=model_name, **kwargs)
        if _response_cache_enabled():
            try:
                cache_key = _response_cache_key(provider=provider, model_name=model_name, prompt=prompt, kwargs=dict(kwargs))
                setter = getattr(resolved_deps, "set_cached_and_remote", None)
                if callable(setter):
                    setter(cache_key, str(result))
                else:
                    resolved_deps.set_cached(cache_key, str(result))
            except Exception:
                pass
        return result
    except Exception:
        # If a specific model was requested but isn't available for this provider,
        # retry with the provider's default model before other fallbacks.
        if model_name is not None:
            try:
                result = backend.generate(prompt, model_name=None, **kwargs)
                if _response_cache_enabled():
                    try:
                        cache_key = _response_cache_key(provider=provider, model_name=None, prompt=prompt, kwargs=dict(kwargs))
                        setter = getattr(resolved_deps, "set_cached_and_remote", None)
                        if callable(setter):
                            setter(cache_key, str(result))
                        else:
                            resolved_deps.set_cached(cache_key, str(result))
                    except Exception:
                        pass
                return result
            except Exception:
                pass

        # Fall back to local HF provider if optional provider fails.
        if provider is None:
            local_hf = _get_local_hf_provider(deps=resolved_deps)
            if local_hf is not None and backend is not local_hf:
                try:
                    result = local_hf.generate(prompt, model_name=model_name, **kwargs)
                    if _response_cache_enabled():
                        try:
                            cache_key = _response_cache_key(provider=provider, model_name=model_name, prompt=prompt, kwargs=dict(kwargs))
                            setter = getattr(resolved_deps, "set_cached_and_remote", None)
                            if callable(setter):
                                setter(cache_key, str(result))
                            else:
                                resolved_deps.set_cached(cache_key, str(result))
                        except Exception:
                            pass
                    return result
                except Exception:
                    if model_name is not None:
                        result = local_hf.generate(prompt, model_name=None, **kwargs)
                        if _response_cache_enabled():
                            try:
                                cache_key = _response_cache_key(provider=provider, model_name=None, prompt=prompt, kwargs=dict(kwargs))
                                setter = getattr(resolved_deps, "set_cached_and_remote", None)
                                if callable(setter):
                                    setter(cache_key, str(result))
                                else:
                                    resolved_deps.set_cached(cache_key, str(result))
                            except Exception:
                                pass
                        return result
        raise


def clear_llm_router_caches() -> None:
    """Clear internal provider caches (useful for tests)."""

    _resolve_provider_cached.cache_clear()
