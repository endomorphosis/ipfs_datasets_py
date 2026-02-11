"""LLM router.

This module provides a reusable top-level entrypoint for text generation.

Design goals:
- Avoid import-time side effects.
- Allow optional hooks/providers (ipfs_accelerate_py, remote endpoints).
- Provide a local HuggingFace transformers fallback when available.

Environment variables:
- `IPFS_DATASETS_PY_LLM_PROVIDER`: force provider name (registered provider)
- `IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE`: control accelerate provider (best-effort hook)
    - unset: prefer accelerate when available
    - truthy: force-enable accelerate attempt
    - falsy (0/false/no): disable accelerate provider
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
import re
import shlex
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from html import unescape
import hashlib
import importlib
from typing import Callable, Dict, List, Optional, Protocol, Sequence, TypedDict, runtime_checkable

from .router_deps import RouterDeps, get_default_router_deps


class LLMRouterError(RuntimeError):
    """Errors raised by lightweight router helpers/providers.

    This is intentionally a RuntimeError subclass so existing call sites that
    catch RuntimeError continue to work.
    """


_P2P_TASK_PREFIX = "p2p://"


def _encode_p2p_task_id(*, peer_id: str, task_id: str) -> str:
    pid = (peer_id or "").strip()
    tid = (task_id or "").strip()
    if not pid or not tid:
        return tid
    return f"{_P2P_TASK_PREFIX}{pid}/{tid}"


def _decode_p2p_task_id(task_id: str) -> tuple[str, str] | None:
    text = str(task_id or "").strip()
    if not text.startswith(_P2P_TASK_PREFIX):
        return None
    rest = text[len(_P2P_TASK_PREFIX) :]
    if "/" not in rest:
        return None
    pid, tid = rest.split("/", 1)
    pid = pid.strip()
    tid = tid.strip()
    if not pid or not tid:
        return None
    return pid, tid


def _extract_peer_id_from_multiaddr(multiaddr: str) -> str:
    text = str(multiaddr or "").strip()
    if not text:
        return ""
    m = re.search(r"/p2p/([^/]+)$", text)
    return (m.group(1) if m else "").strip()


def submit_task(
    *,
    prompt: str,
    model_name: str = "gpt2",
    task_type: str = "text-generation",
    queue_path: Optional[str] = None,
    **kwargs: object,
) -> str:
    """Submit an LLM task to a local task queue, or to a remote peer via libp2p.

    This provides a simple multi-worker delegation mechanism.
    Workers can be run via `python -m ipfs_datasets_py.ml.accelerate_integration.worker`.
    """

    remote_peer_id = os.environ.get("IPFS_DATASETS_PY_TASK_P2P_REMOTE_PEER_ID", "").strip()
    remote_multiaddr = os.environ.get("IPFS_DATASETS_PY_TASK_P2P_REMOTE_MULTIADDR", "").strip()
    auto_discovery = os.environ.get("IPFS_DATASETS_PY_TASK_P2P_AUTO_DISCOVERY", "0").strip().lower() in {"1", "true", "yes", "on"}

    try:
        from ipfs_datasets_py.ml.accelerate_integration.task_queue import TaskQueue
    except Exception as exc:
        raise LLMRouterError("Task delegation helpers not available") from exc

    payload: Dict[str, object] = {"prompt": str(prompt or "")}
    for k in ("max_new_tokens", "max_tokens", "temperature"):
        if k in kwargs:
            payload[k] = kwargs[k]

    if remote_multiaddr or auto_discovery:
        try:
            import anyio

            from ipfs_datasets_py.ml.accelerate_integration.p2p_task_client import RemoteQueue
            from ipfs_datasets_py.ml.accelerate_integration.p2p_task_client import submit_task_with_info

            remote = RemoteQueue(peer_id=remote_peer_id or "", multiaddr=remote_multiaddr)

            async def _run() -> dict:
                return await submit_task_with_info(
                    remote=remote,
                    task_type=str(task_type),
                    model_name=str(model_name or ""),
                    payload=payload,  # type: ignore[arg-type]
                )

            info = anyio.run(_run, backend="trio")
            if isinstance(info, dict):
                tid = str(info.get("task_id") or "").strip()
                pid = str(info.get("peer_id") or "").strip() or remote_peer_id or _extract_peer_id_from_multiaddr(remote_multiaddr)
                if pid and tid:
                    return _encode_p2p_task_id(peer_id=pid, task_id=tid)
                if tid:
                    return tid
            raise RuntimeError(f"invalid_submit_response: {info}")
        except Exception as exc:
            # If the caller explicitly configured a remote multiaddr, fail loudly.
            if remote_multiaddr:
                raise LLMRouterError(f"P2P submit_task failed: {exc}") from exc
            # Auto-discovery is best-effort: fall back to local queue.
            pass

    q = TaskQueue(queue_path)
    return q.submit(task_type=str(task_type), model_name=str(model_name or ""), payload=payload)


def get_task(task_id: str, *, queue_path: Optional[str] = None) -> Optional[dict]:
    """Get task status/result from the local task queue, or from a remote peer via libp2p."""

    parsed = _decode_p2p_task_id(str(task_id))

    remote_peer_id = os.environ.get("IPFS_DATASETS_PY_TASK_P2P_REMOTE_PEER_ID", "").strip()
    remote_multiaddr = os.environ.get("IPFS_DATASETS_PY_TASK_P2P_REMOTE_MULTIADDR", "").strip()
    auto_discovery = os.environ.get("IPFS_DATASETS_PY_TASK_P2P_AUTO_DISCOVERY", "0").strip().lower() in {"1", "true", "yes", "on"}

    effective_peer_id = parsed[0] if parsed else remote_peer_id
    effective_task_id = parsed[1] if parsed else str(task_id)

    if parsed is not None or remote_multiaddr or (auto_discovery and effective_peer_id):
        try:
            import anyio

            from ipfs_datasets_py.ml.accelerate_integration.p2p_task_client import RemoteQueue
            from ipfs_datasets_py.ml.accelerate_integration.p2p_task_client import get_task as get_task_p2p

            remote = RemoteQueue(peer_id=effective_peer_id or "", multiaddr=remote_multiaddr)

            async def _run() -> Optional[dict]:
                task = await get_task_p2p(remote=remote, task_id=str(effective_task_id))
                return task if isinstance(task, dict) else None

            return anyio.run(_run, backend="trio")
        except Exception:
            return None

    try:
        from ipfs_datasets_py.ml.accelerate_integration.task_queue import TaskQueue
    except Exception:
        return None
    return TaskQueue(queue_path).get(task_id)


def wait_task(
    task_id: str,
    *,
    queue_path: Optional[str] = None,
    timeout_s: float = 60.0,
) -> Optional[dict]:
    """Wait for a task to complete.

    - Local: polls SQLite queue.
    - P2P: uses remote peer's wait RPC.
    """

    parsed = _decode_p2p_task_id(str(task_id))

    remote_peer_id = os.environ.get("IPFS_DATASETS_PY_TASK_P2P_REMOTE_PEER_ID", "").strip()
    remote_multiaddr = os.environ.get("IPFS_DATASETS_PY_TASK_P2P_REMOTE_MULTIADDR", "").strip()
    auto_discovery = os.environ.get("IPFS_DATASETS_PY_TASK_P2P_AUTO_DISCOVERY", "0").strip().lower() in {"1", "true", "yes", "on"}

    effective_peer_id = parsed[0] if parsed else remote_peer_id
    effective_task_id = parsed[1] if parsed else str(task_id)

    if parsed is not None or remote_multiaddr or (auto_discovery and effective_peer_id):
        try:
            import anyio

            from ipfs_datasets_py.ml.accelerate_integration.p2p_task_client import RemoteQueue
            from ipfs_datasets_py.ml.accelerate_integration.p2p_task_client import wait_task as wait_task_p2p

            remote = RemoteQueue(peer_id=effective_peer_id or "", multiaddr=remote_multiaddr)

            async def _run() -> Optional[dict]:
                task = await wait_task_p2p(remote=remote, task_id=str(effective_task_id), timeout_s=float(timeout_s))
                return task if isinstance(task, dict) else None

            return anyio.run(_run, backend="trio")
        except Exception:
            return None

    try:
        from ipfs_datasets_py.ml.accelerate_integration.task_queue import TaskQueue
    except Exception:
        return None

    import time

    q = TaskQueue(queue_path)
    deadline = time.time() + max(0.0, float(timeout_s))
    task = q.get(str(task_id))
    while task is not None and task.get("status") in {"queued", "running"} and time.time() < deadline:
        time.sleep(0.1)
        task = q.get(str(task_id))
    return task if isinstance(task, dict) else None


def _find_int_by_key(obj: object, key: str) -> Optional[int]:
    """Best-effort: find the first int-like value for a key anywhere in nested JSON."""

    try:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == key:
                    if isinstance(v, bool):
                        return None
                    if isinstance(v, int):
                        return v
                    if isinstance(v, str) and v.strip().isdigit():
                        return int(v.strip())
                found = _find_int_by_key(v, key)
                if isinstance(found, int):
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = _find_int_by_key(item, key)
                if isinstance(found, int):
                    return found
    except Exception:
        return None
    return None


def _extract_resets_in_seconds_from_codex_jsonl(text: str) -> Optional[int]:
    """Parse Codex --json output (JSONL) for a resets_in_seconds-like field."""

    if not isinstance(text, str) or not text.strip():
        return None
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        for candidate_key in (
            "resets_in_seconds",
            "reset_in_seconds",
            "retry_after_seconds",
            "retry_after",
        ):
            found = _find_int_by_key(obj, candidate_key)
            if isinstance(found, int) and found > 0:
                return found
    return None


def _extract_first_error_message_from_codex_jsonl(text: str) -> Optional[str]:
    """Best-effort: extract the first error message from Codex --json (JSONL) stdout."""

    if not isinstance(text, str) or not text.strip():
        return None
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("type") == "error":
            msg = obj.get("message")
            if isinstance(msg, str) and msg.strip():
                return msg.strip()
            err = obj.get("error")
            if isinstance(err, dict):
                msg2 = err.get("message")
                if isinstance(msg2, str) and msg2.strip():
                    return msg2.strip()
    return None


def _is_codex_quota_exceeded_message(msg: str) -> bool:
    """Detect errors that indicate a billing/quota hard-stop (waiting won't help)."""

    if not isinstance(msg, str) or not msg.strip():
        return False
    low = msg.lower()
    quota_markers = (
        "insufficient_quota",
        "exceeded your current quota",
        "quota has been exceeded",
        "billing",
        "hard limit",
        "billing limit",
        "check your plan and billing",
        "add a payment method",
        "your account is not active",
    )
    return any(m in low for m in quota_markers) and ("usage limit" not in low)


def _classify_codex_error_kind(*, stdout: str, stderr: str) -> Optional[str]:
    """Classify Codex failures into coarse kinds to guide retry vs fail-fast."""

    provider_msg = _extract_first_error_message_from_codex_jsonl(stdout or "")
    if provider_msg and _is_codex_quota_exceeded_message(provider_msg):
        return "quota_exceeded"

    combined = "\n".join([p for p in [provider_msg, stdout, stderr] if isinstance(p, str) and p.strip()])
    if _is_codex_quota_exceeded_message(combined):
        return "quota_exceeded"

    low = combined.lower() if isinstance(combined, str) else ""
    if "usage_limit" in low or "usage limit" in low:
        return "usage_limit"
    return None


def _extract_last_agent_message_from_codex_jsonl(text: str) -> Optional[str]:
    """Extract the most recent agent message from Codex --json (JSONL) stdout."""

    if not isinstance(text, str) or not text.strip():
        return None

    def _extract_text_from_message_like(obj: object) -> Optional[str]:
        if not isinstance(obj, dict):
            return None

        obj_type = obj.get("type")

        if obj_type in ("agent_message", "assistant_message"):
            txt = obj.get("text")
            if isinstance(txt, str) and txt.strip():
                return txt

        if obj_type == "message" and obj.get("role") == "assistant":
            content = obj.get("content")
            if isinstance(content, list):
                parts: list[str] = []
                for chunk in content:
                    if not isinstance(chunk, dict):
                        continue
                    if chunk.get("type") in ("output_text", "text"):
                        chunk_text = chunk.get("text")
                        if isinstance(chunk_text, str) and chunk_text.strip():
                            parts.append(chunk_text)
                joined = "".join(parts).strip()
                return joined if joined else None

            txt = obj.get("text")
            if isinstance(txt, str) and txt.strip():
                return txt

        return None

    last: Optional[str] = None
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue

        if isinstance(obj, dict) and obj.get("type") == "item.completed":
            item = obj.get("item")
            extracted = _extract_text_from_message_like(item)
            if isinstance(extracted, str) and extracted.strip():
                last = extracted
            continue

        if isinstance(obj, dict):
            extracted = _extract_text_from_message_like(obj.get("item"))
            if not extracted:
                extracted = _extract_text_from_message_like(obj.get("message"))
            if not extracted:
                extracted = _extract_text_from_message_like(obj)
            if isinstance(extracted, str) and extracted.strip():
                last = extracted

    return last.strip() if isinstance(last, str) and last.strip() else None


def get_accelerate_manager(
    *,
    deps: Optional[RouterDeps] = None,
    purpose: str = "llm",
    enable_distributed: bool = True,
    resources: Optional[Dict[str, object]] = None,
    ipfs_gateway: Optional[str] = None,
) -> object | None:
    """Return a cached AccelerateManager via RouterDeps.

    This is the preferred access path for accelerate integration from LLM-related
    call sites. It avoids importing `accelerate_integration` in those modules.
    """

    resolved = deps or get_default_router_deps()
    try:
        return resolved.get_accelerate_manager(
            purpose=purpose,
            enable_distributed=enable_distributed,
            resources=resources,
            ipfs_gateway=ipfs_gateway,
        )
    except Exception:
        return None


def get_accelerate_status() -> dict:
    """Best-effort accelerate status without forcing heavy imports.

    Note: This intentionally avoids importing `accelerate_integration` (or
    `ipfs_accelerate_py`) because those imports can trigger heavyweight optional
    initialization.
    """

    env_value = os.environ.get("IPFS_ACCELERATE_ENABLED", "1").lower()
    env_disabled = env_value in {"0", "false", "no", "disabled"}
    if env_disabled:
        return {"available": False, "enabled": False, "env_disabled": True, "env_var": env_value}

    try:
        import importlib.util

        backend_available = importlib.util.find_spec("ipfs_accelerate_py") is not None
    except Exception:
        backend_available = False

    return {"available": backend_available, "enabled": True, "env_disabled": False, "env_var": env_value}


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


class ChatMessage(TypedDict):
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class OpenAICompatTopLogProb:
    token: str
    logprob: float


@dataclass(frozen=True, slots=True)
class OpenAICompatLogProbsContentItem:
    top_logprobs: list[OpenAICompatTopLogProb]


@dataclass(frozen=True, slots=True)
class OpenAICompatLogProbs:
    content: list[OpenAICompatLogProbsContentItem]


@dataclass(frozen=True, slots=True)
class OpenAICompatMessage:
    content: str


@dataclass(frozen=True, slots=True)
class OpenAICompatChoice:
    message: OpenAICompatMessage
    logprobs: OpenAICompatLogProbs


@dataclass(frozen=True, slots=True)
class OpenAICompatResponse:
    choices: list[OpenAICompatChoice]


@runtime_checkable
class OpenAIChatCompletionsProvider(Protocol):
    def chat_completions(
        self,
        messages: Sequence[ChatMessage],
        *,
        model_name: Optional[str] = None,
        **kwargs: object,
    ) -> dict: ...


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


_LEADING_MARKER_RE = re.compile(r"^[\s\u2022\u25CF\u25E6\u25AA\u25AB\u2219\u00B7\*\-]+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _clean_copilot_output(text: str) -> str:
    cleaned = (text or "").strip()
    # Do not strip patch markers; they are semantically meaningful.
    if cleaned.lstrip().startswith("*** Begin Patch"):
        return cleaned.strip()
    cleaned = _LEADING_MARKER_RE.sub("", cleaned).strip()
    cleaned = unescape(cleaned)
    if "<" in cleaned and ">" in cleaned:
        cleaned = _HTML_TAG_RE.sub("", cleaned)
    return cleaned.strip()


def _clean_codex_output(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.lstrip().startswith("*** Begin Patch"):
        return cleaned.strip()
    cleaned = _LEADING_MARKER_RE.sub("", cleaned).strip()
    cleaned = unescape(cleaned)
    if "<" in cleaned and ">" in cleaned:
        cleaned = _HTML_TAG_RE.sub("", cleaned)
    return cleaned.strip()


def _clean_claude_output(text: str) -> str:
    return _clean_codex_output(text)


def _clean_gemini_output(text: str) -> str:
    return _clean_codex_output(text)


def _cli_available(command: str) -> bool:
    if not command:
        return False
    parts = shlex.split(command)
    if not parts:
        return False
    if parts[0] == "npx":
        return True
    return shutil.which(parts[0]) is not None


def _run_cli_command(
    command: str,
    prompt: str,
    *,
    timeout_seconds: float = 120.0,
    template_vars: Optional[Dict[str, str]] = None,
    label: Optional[str] = None,
) -> str:
    if not command:
        raise RuntimeError("CLI command not configured")

    rendered = command
    if template_vars:
        for key, value in template_vars.items():
            rendered = rendered.replace("{" + str(key) + "}", str(value))

    if "{prompt}" in rendered:
        rendered = rendered.replace("{prompt}", prompt)
        cmd = shlex.split(rendered)
        input_text: str | None = None
    else:
        cmd = shlex.split(rendered)
        input_text = prompt

    try:
        proc = subprocess.run(
            cmd,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
            env=os.environ.copy(),
        )
    except FileNotFoundError as exc:
        name = (label or "CLI").strip() or "CLI"
        raise LLMRouterError(f"{name} not found on PATH") from exc
    if proc.returncode != 0:
        name = (label or "CLI").strip() or "CLI"
        raise LLMRouterError(proc.stderr.strip() or f"{name} command failed")
    return (proc.stdout or "").strip()


def _get_openrouter_provider() -> Optional[LLMProvider]:
    api_key = _coalesce_env("IPFS_DATASETS_PY_OPENROUTER_API_KEY", "OPENROUTER_API_KEY")
    if not api_key:
        return None

    base_url = os.getenv("IPFS_DATASETS_PY_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")

    def _request(payload: dict, *, timeout: float) -> dict:
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
            with urllib.request.urlopen(req, timeout=timeout) as resp:
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
        if not isinstance(data, dict):
            raise RuntimeError("OpenRouter returned invalid JSON")
        return data

    class _OpenRouterProvider:
        def chat_completions(
            self,
            messages: Sequence[ChatMessage],
            *,
            model_name: Optional[str] = None,
            **kwargs: object,
        ) -> dict:
            model = (
                model_name
                or os.getenv("IPFS_DATASETS_PY_OPENROUTER_MODEL")
                or os.getenv("IPFS_DATASETS_PY_LLM_MODEL")
                or "openai/gpt-4o-mini"
            )

            max_tokens = kwargs.get("max_tokens", kwargs.get("max_new_tokens", 256))
            temperature = kwargs.get("temperature", 0.2)

            payload: dict = {
                "model": model,
                "messages": list(messages),
                "max_tokens": int(max_tokens),
                "temperature": float(temperature),
            }

            # Optional OpenAI-compatible fields.
            if "logprobs" in kwargs:
                payload["logprobs"] = bool(kwargs.get("logprobs"))
            if "top_logprobs" in kwargs and kwargs.get("top_logprobs") is not None:
                payload["top_logprobs"] = int(kwargs.get("top_logprobs"))
            if "response_format" in kwargs and kwargs.get("response_format") is not None:
                payload["response_format"] = kwargs.get("response_format")
            if "seed" in kwargs and kwargs.get("seed") is not None:
                payload["seed"] = int(kwargs.get("seed"))

            timeout = float(kwargs.get("timeout", 120))
            return _request(payload, timeout=timeout)

        def generate(self, prompt: str, *, model_name: Optional[str] = None, **kwargs: object) -> str:
            data = self.chat_completions(
                [{"role": "user", "content": prompt}],
                model_name=model_name,
                **kwargs,
            )

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
            model = (model_name or _coalesce_env("IPFS_DATASETS_PY_CODEX_CLI_MODEL", "IPFS_DATASETS_PY_CODEX_MODEL") or "gpt-5.1-codex-mini").strip()
            sandbox = (os.getenv("IPFS_DATASETS_PY_CODEX_SANDBOX", "auto") or "auto").strip()
            skip_git_repo_check = os.getenv("IPFS_DATASETS_PY_CODEX_SKIP_GIT_REPO_CHECK", "1") != "0"
            timeout = float(kwargs.get("timeout", 180))

            trace_jsonl_path = kwargs.pop("trace_jsonl_path", None)
            trace_dir = kwargs.pop("trace_dir", None)
            trace_enabled = bool(kwargs.pop("trace", False) or trace_jsonl_path or trace_dir)

            json_mode = bool(trace_enabled or kwargs.pop("json", False))

            with tempfile.NamedTemporaryFile(mode="w+", suffix=".txt", delete=False) as last_msg:
                last_msg_path = last_msg.name

            cmd: list[str] = ["codex", "exec"]
            if skip_git_repo_check:
                cmd.append("--skip-git-repo-check")
            # Some Codex CLI builds do not accept '--sandbox auto'.
            # Treat 'auto' (the default) as "don't pass the flag" so the CLI can
            # pick its own default sandbox mode.
            if sandbox and sandbox.lower() != "auto":
                cmd.extend(["--sandbox", sandbox])
            if model:
                cmd.extend(["-m", model])
            cmd.extend(["--output-last-message", last_msg_path])
            if json_mode:
                cmd.append("--json")
            cmd.append("-")

            try:
                proc = subprocess.run(
                    cmd,
                    input=str(prompt),
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=timeout,
                )
            except FileNotFoundError as exc:
                raise LLMRouterError("codex CLI not found on PATH") from exc

            try:
                with open(last_msg_path, "r", encoding="utf-8", errors="replace") as handle:
                    text_out = handle.read().strip()
            except Exception:
                text_out = ""
            finally:
                try:
                    os.unlink(last_msg_path)
                except Exception:
                    pass

            if proc.returncode == 0 or text_out:
                if json_mode and proc.stdout:
                    extracted = _extract_last_agent_message_from_codex_jsonl(proc.stdout)
                    if extracted:
                        return _clean_codex_output(extracted)
                return _clean_codex_output(text_out)

            if trace_enabled and proc.stdout and isinstance(trace_jsonl_path, str) and trace_jsonl_path.strip():
                try:
                    os.makedirs(os.path.dirname(trace_jsonl_path.strip()) or ".", exist_ok=True)
                    with open(trace_jsonl_path.strip(), "a", encoding="utf-8") as handle:
                        handle.write(proc.stdout)
                        if not proc.stdout.endswith("\n"):
                            handle.write("\n")
                except OSError:
                    pass

            kind = _classify_codex_error_kind(stdout=proc.stdout or "", stderr=proc.stderr or "")
            resets = _extract_resets_in_seconds_from_codex_jsonl(proc.stdout or "")
            if kind == "quota_exceeded":
                raise LLMRouterError("Codex quota exceeded (billing/plan hard limit)")
            if kind == "usage_limit":
                suffix = f" (resets in ~{resets}s)" if isinstance(resets, int) else ""
                raise LLMRouterError(f"Codex usage limit reached{suffix}")
            raise LLMRouterError(proc.stderr.strip() or "codex exec failed")

    return _CodexCLIProvider()


def _get_copilot_cli_provider() -> Optional[LLMProvider]:
    default_command = "npx --yes @github/copilot -p {prompt}"
    command = os.environ.get("IPFS_DATASETS_PY_COPILOT_CLI_CMD", default_command)
    if not _cli_available(command):
        return None

    class _CopilotCLIProvider:
        def generate(self, prompt: str, *, model_name: Optional[str] = None, **kwargs: object) -> str:
            model = (
                (model_name or "").strip()
                or os.getenv("IPFS_DATASETS_PY_COPILOT_CLI_MODEL", "").strip()
                or os.getenv("IPFS_DATASETS_PY_LLM_MODEL", "").strip()
                or "gpt-5-mini"
            )
            timeout = float(kwargs.get("timeout", 180))

            trace_jsonl_path = kwargs.pop("trace_jsonl_path", None)
            trace_dir = kwargs.pop("trace_dir", None)
            trace_enabled = bool(kwargs.pop("trace", False) or trace_jsonl_path or trace_dir)

            copilot_config_dir = kwargs.pop("copilot_config_dir", None)
            copilot_log_dir = kwargs.pop("copilot_log_dir", None)
            resume_session_id = kwargs.pop("resume_session_id", None)
            continue_session = bool(kwargs.pop("continue_session", False))

            needs_native = bool(
                trace_enabled
                or copilot_config_dir
                or copilot_log_dir
                or resume_session_id
                or continue_session
            )

            if not needs_native:
                return _clean_copilot_output(
                    _run_cli_command(
                        command,
                        prompt,
                        timeout_seconds=timeout,
                        template_vars={"model": model},
                        label="Copilot CLI",
                    )
                )

            if shutil.which("copilot") is None:
                raise RuntimeError(
                    "copilot CLI binary not found on PATH (required for session/tracing flags). "
                    "Install the GitHub Copilot CLI, or unset session args to use the command-template mode."
                )

            def _utc_stamp() -> str:
                return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

            share_path: Optional[str] = None
            if trace_enabled:
                share_base_dir: Optional[str] = None
                if isinstance(trace_dir, str) and trace_dir.strip():
                    share_base_dir = trace_dir.strip()
                elif isinstance(trace_jsonl_path, str) and trace_jsonl_path.strip():
                    share_base_dir = os.path.dirname(trace_jsonl_path.strip()) or "."
                if share_base_dir:
                    os.makedirs(share_base_dir, exist_ok=True)
                    share_path = os.path.join(
                        share_base_dir,
                        f"copilot_session_{_utc_stamp()}_{os.getpid()}.md",
                    )

            cmd: list[str] = [
                "copilot",
                "-s",
                "--stream",
                "off",
                "--model",
                model,
                "-p",
                str(prompt),
            ]

            if isinstance(copilot_config_dir, str) and copilot_config_dir.strip():
                cmd.extend(["--config-dir", copilot_config_dir.strip()])

            if isinstance(copilot_log_dir, str) and copilot_log_dir.strip():
                cmd.extend(["--log-dir", copilot_log_dir.strip()])
            elif trace_enabled and isinstance(trace_dir, str) and trace_dir.strip():
                cmd.extend(["--log-dir", trace_dir.strip()])

            appended_continue = False
            if isinstance(resume_session_id, str) and resume_session_id.strip():
                cmd.extend(["--resume", resume_session_id.strip()])
            elif continue_session:
                cmd.append("--continue")
                appended_continue = True

            if share_path:
                cmd.extend(["--share", share_path])

            def _run_copilot(command_list: list[str]) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    command_list,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=timeout,
                    env=os.environ.copy(),
                )

            proc = _run_copilot(cmd)
            if proc.returncode != 0 and appended_continue:
                msg = ((proc.stderr or "") or "").lower()
                retryable_continue = any(
                    s in msg
                    for s in (
                        "no session",
                        "no previous session",
                        "nothing to continue",
                        "cannot continue",
                        "could not continue",
                        "unable to continue",
                        "not found",
                    )
                )
                if retryable_continue:
                    cmd2 = [x for x in cmd if x != "--continue"]
                    proc2 = _run_copilot(cmd2)
                    if proc2.returncode == 0:
                        cmd = cmd2
                        proc = proc2

            if proc.returncode != 0:
                raise RuntimeError((proc.stderr or "").strip() or "copilot CLI failed")

            cleaned = _clean_copilot_output(proc.stdout or "")

            if trace_enabled and isinstance(trace_jsonl_path, str) and trace_jsonl_path.strip():
                record = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "provider": "copilot_cli",
                    "model": model,
                    "cmd": cmd,
                    "share_path": share_path,
                    "stdout_chars": len(proc.stdout or ""),
                    "stderr_chars": len(proc.stderr or ""),
                }
                try:
                    os.makedirs(os.path.dirname(trace_jsonl_path.strip()) or ".", exist_ok=True)
                    with open(trace_jsonl_path.strip(), "a", encoding="utf-8") as handle:
                        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                except OSError:
                    pass

            return cleaned

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
                from ipfs_datasets_py.utils.anyio_compat import AsyncContextError, fail_after, run as run_anyio

                async def _run_with_timeout() -> str:
                    with fail_after(timeout_seconds):
                        return await _run()

                return run_anyio(_run_with_timeout())
            except AsyncContextError:
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

            gemini_cmd = kwargs.pop("gemini_cmd", None)
            if isinstance(gemini_cmd, list) and gemini_cmd:
                base_cmd = [str(x) for x in gemini_cmd]
                rendered = None
            elif isinstance(gemini_cmd, str) and gemini_cmd.strip():
                rendered = gemini_cmd.strip()
                base_cmd = shlex.split(rendered)
            else:
                rendered = command
                base_cmd = shlex.split(rendered)

            def _run(cmd_list: list[str]) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    cmd_list,
                    input=str(prompt),
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=timeout,
                    env=os.environ.copy(),
                )

            try:
                proc = _run(base_cmd)
            except FileNotFoundError as exc:
                raise LLMRouterError("Gemini CLI not found on PATH") from exc

            if proc.returncode == 0:
                return _clean_gemini_output(proc.stdout or "")

            stderr = (proc.stderr or "")
            # Known failure mode when running on Node.js v18.
            node18_regex_error = ("invalid regular expression flags" in stderr.lower()) and ("node.js v18" in stderr.lower())
            if node18_regex_error:
                try:
                    proc2 = _run(base_cmd)
                except FileNotFoundError as exc:
                    raise LLMRouterError("Gemini CLI not found on PATH") from exc
                if proc2.returncode == 0:
                    return _clean_gemini_output(proc2.stdout or "")

            raise LLMRouterError(stderr.strip() or "Gemini CLI failed")

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
            return _clean_claude_output(_run_cli_command(command, prompt, timeout_seconds=timeout, label="Claude Code CLI"))

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
    enable_value = os.getenv("IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE")
    if enable_value is not None and enable_value.strip() and not _truthy(enable_value):
        return None

    # If ipfs_accelerate_py isn't installed, skip without initializing anything.
    try:
        # Best-effort support for vendored submodule layouts.
        # In this repo, ipfs_accelerate_py lives at:
        #   <submodule_root>/ipfs_accelerate_py/ipfs_accelerate_py/
        # so we need to add <submodule_root>/ipfs_accelerate_py to sys.path.
        from pathlib import Path
        import sys

        submodule_root = Path(__file__).resolve().parents[1]
        candidate = submodule_root / "ipfs_accelerate_py"
        if candidate.is_dir():
            candidate_str = str(candidate)
            if candidate_str not in sys.path:
                sys.path.insert(0, candidate_str)

        import importlib.util

        if importlib.util.find_spec("ipfs_accelerate_py") is None:
            return None
    except Exception:
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
    if key in {"mock", "dry_run", "dry-run"}:
        return _get_mock_provider()
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


def _get_mock_provider() -> LLMProvider:
    """Return an ultra-lightweight deterministic provider.

    This is intended for unit tests and offline environments. It avoids spawning
    external CLIs/SDKs and avoids loading local HF models.
    """

    class _MockProvider:
        def generate(self, prompt: str, *, model_name: Optional[str] = None, **_: object) -> str:
            lowered = str(prompt or "").lower()

            import re

            def _looks_like_json_contract(text: str) -> bool:
                if not text:
                    return False
                if "return a json" in text or "json object" in text:
                    return True
                # Heuristics for our contracted logic converters.
                if "foloutput" in text or "fol_formula" in text or '"fol_formula"' in text:
                    return True
                if "<output_data_model>" in text and "[[schema]]" in text:
                    return True
                # The ContractedFOLConverter prompt itself (used in symai contract pipelines).
                if "convert natural language statements into formal first-order logic" in text:
                    return True
                return False

            def _extract_output_format(text: str) -> str:
                if not text:
                    return "symbolic"

                # Prefer explicit markers used by our prompts.
                # This avoids false positives when the prompt *mentions* all formats
                # (e.g. in a "Format requirements" section).
                explicit = re.search(r"requested\s+output\s+format\s*:\s*([a-z0-9_-]+)", text)
                if explicit:
                    token = explicit.group(1).strip().lower()
                    if token in {"prolog", "tptp", "symbolic", "json"}:
                        return token

                # Also support JSON-style markers.
                json_style = re.search(r'"output[_\s-]*format"\s*:\s*"([a-z0-9_-]+)"', text)
                if json_style:
                    token = json_style.group(1).strip().lower()
                    if token in {"prolog", "tptp", "symbolic", "json"}:
                        return token

                # Fallback heuristics (keep conservative).
                if "tptp" in text or "fof(" in text:
                    return "tptp"
                if "prolog" in text:
                    return "prolog"
                if "symbolic" in text:
                    return "symbolic"
                if "json" in text:
                    return "json"
                return "symbolic"

            def _looks_like_fol_conversion_prompt(text: str) -> bool:
                if not text:
                    return False
                # Common phrasing used by our logic primitives.
                if "convert" not in text:
                    return False
                if "first-order logic" not in text and "fol" not in text:
                    return False
                if "return only" in text and "formula" in text:
                    return True
                # Also treat the ContractedFOLConverter prompt as a conversion prompt.
                if "convert natural language statements" in text and "fol" in text:
                    return True
                return False

            def _mock_fol_formula(fmt: str, text: str) -> str:
                # Keep these short, deterministic, and syntactically valid.
                cats = "cats" in text and "animals" in text
                if fmt == "prolog":
                    # Use ASCII tokens to satisfy tests that check for prolog-like syntax.
                    return "forall(X, (cat(X) -> animal(X)))." if cats else "exists(X, statement(X))."
                if fmt == "tptp":
                    return "fof(ax1, axiom, ! [X] : ( cat(X) => animal(X) ) )." if cats else "fof(ax1, axiom, ? [X] : statement(X) )."
                # symbolic/default
                return "∀x (Cat(x) → Animal(x))" if cats else "∃x Statement(x)"

            def _mock_contract_json(text: str) -> str:
                import json

                fmt = _extract_output_format(text)
                formula = _mock_fol_formula(fmt, text)
                payload = {
                    "fol_formula": formula,
                    "confidence": 0.9,
                    "logical_components": {
                        "quantifiers": ["∀" if fmt == "symbolic" else ("forall" if fmt == "prolog" else "!")],
                        "predicates": ["Cat", "Animal"],
                        "entities": ["cat", "animal"],
                        "connectives": ["→" if fmt == "symbolic" else ("->" if fmt == "prolog" else "=>")],
                    },
                    "reasoning_steps": ["mock"],
                    "validation_results": {"valid": True, "backend": "mock"},
                    "warnings": [],
                    "metadata": {"backend": "mock", "model": model_name or "mock", "output_format": fmt},
                }
                return json.dumps(payload, ensure_ascii=False)

            # SyMAI contract/type-validation prompts expect JSON.
            if _looks_like_json_contract(lowered):
                return _mock_contract_json(lowered)

            # FOL conversion prompts should yield a formula (not an extraction list).
            if _looks_like_fol_conversion_prompt(lowered):
                fmt = _extract_output_format(lowered)
                return _mock_fol_formula(fmt, lowered)

            # Heuristic outputs for common logic-tool extraction prompts.
            # Keep these checks strict to avoid accidentally matching SyMAI schema prompts.
            if "extract" in lowered and "quantifier" in lowered:
                return "all, some"
            if "extract" in lowered and "predicate" in lowered:
                return "is, are, has"
            if "extract" in lowered and "entit" in lowered:
                return "cat, animal"
            if "extract" in lowered and ("connective" in lowered or "logical connective" in lowered):
                return "and, or, not"

            if "first-order logic" in lowered or "fol" in lowered:
                # Keep output short and stable, but honor requested output format.
                fmt = _extract_output_format(lowered)
                return _mock_fol_formula(fmt, lowered)

            # Generic non-empty fallback.
            return "OK"

    return _MockProvider()


def _resolve_provider_uncached(preferred: Optional[str], *, deps: RouterDeps) -> LLMProvider:
    preferred_value = (preferred or "").strip()
    if preferred_value:
        name = preferred_value.lower()
        if name in {"ipfs_accelerate_py", "accelerate"}:
            accelerate_provider = _get_accelerate_provider(deps)
            if accelerate_provider is None:
                raise LLMRouterError(
                    "Accelerate provider not available. Set IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE=1 and ensure ipfs_accelerate_py is installed/configured."
                )
            return accelerate_provider

        info = _PROVIDER_REGISTRY.get(name)
        if info is not None:
            return info.factory()

        if name == "copilot_sdk":
            builtin = _get_copilot_sdk_provider()
            if builtin is None:
                raise LLMRouterError("Copilot Python SDK not installed (optional dependency).")
            return builtin

        builtin = _builtin_provider_by_name(name)
        if builtin is not None:
            return builtin
        raise ValueError(f"Unknown LLM provider: {preferred_value}")

    forced = os.getenv("IPFS_DATASETS_PY_LLM_PROVIDER", "").strip()
    if forced:
        forced_name = forced.strip().lower()
        if forced_name in {"ipfs_accelerate_py", "accelerate"}:
            accelerate_provider = _get_accelerate_provider(deps)
            if accelerate_provider is None:
                raise LLMRouterError(
                    "Accelerate provider not available. Set IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE=1 and ensure ipfs_accelerate_py is installed/configured."
                )
            return accelerate_provider

        info = _PROVIDER_REGISTRY.get(forced_name)
        if info is not None:
            return info.factory()

        if forced_name == "copilot_sdk":
            builtin = _get_copilot_sdk_provider()
            if builtin is None:
                raise LLMRouterError("Copilot Python SDK not installed (optional dependency).")
            return builtin

        builtin = _builtin_provider_by_name(forced_name)
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


def _messages_to_prompt(messages: Sequence[ChatMessage]) -> str:
    return "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in list(messages))


def _parse_openai_compat_response(data: dict) -> OpenAICompatResponse:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("Chat completions response missing choices")

    first = choices[0]
    if not isinstance(first, dict):
        raise RuntimeError("Chat completions response invalid choice")

    msg = first.get("message")
    content = ""
    if isinstance(msg, dict) and isinstance(msg.get("content"), str):
        content = msg.get("content", "")
    elif isinstance(first.get("text"), str):
        content = str(first.get("text") or "")

    # Best-effort logprobs extraction.
    logprobs_obj = first.get("logprobs")
    top_logprobs: list[OpenAICompatTopLogProb] = []
    try:
        if isinstance(logprobs_obj, dict):
            content_items = logprobs_obj.get("content")
            if isinstance(content_items, list) and content_items:
                item0 = content_items[0]
                if isinstance(item0, dict):
                    raw_top = item0.get("top_logprobs")
                    if isinstance(raw_top, list):
                        for entry in raw_top:
                            if not isinstance(entry, dict):
                                continue
                            token = entry.get("token")
                            logprob = entry.get("logprob")
                            if isinstance(token, str) and isinstance(logprob, (int, float)):
                                top_logprobs.append(OpenAICompatTopLogProb(token=token, logprob=float(logprob)))
    except Exception:
        top_logprobs = []

    return OpenAICompatResponse(
        choices=[
            OpenAICompatChoice(
                message=OpenAICompatMessage(content=str(content).strip()),
                logprobs=OpenAICompatLogProbs(content=[OpenAICompatLogProbsContentItem(top_logprobs=top_logprobs)]),
            )
        ]
    )


def chat_completions_create(
    *,
    messages: Sequence[ChatMessage],
    model: Optional[str] = None,
    provider: Optional[str] = None,
    provider_instance: Optional[LLMProvider] = None,
    deps: Optional[RouterDeps] = None,
    **kwargs: object,
) -> OpenAICompatResponse:
    """OpenAI-compatible chat completions API via the router.

    Returns a small response object that supports attribute access compatible with
    common OpenAI usage patterns: `response.choices[0].message.content` and
    `response.choices[0].logprobs.content[0].top_logprobs`.

    Notes:
    - Not all providers support logprobs; when unavailable, `top_logprobs` is empty.
    """

    resolved_deps = deps or get_default_router_deps()
    backend = provider_instance or get_llm_provider(provider, deps=resolved_deps)

    # Prefer native chat completions when the provider supports it.
    if isinstance(backend, OpenAIChatCompletionsProvider):
        data = backend.chat_completions(messages, model_name=model, **kwargs)
        return _parse_openai_compat_response(data)

    # Fallback: flatten messages into a single prompt.
    prompt = _messages_to_prompt(messages)
    text = backend.generate(prompt, model_name=model, **kwargs)
    return OpenAICompatResponse(
        choices=[
            OpenAICompatChoice(
                message=OpenAICompatMessage(content=str(text).strip()),
                logprobs=OpenAICompatLogProbs(content=[OpenAICompatLogProbsContentItem(top_logprobs=[])]),
            )
        ]
    )


def get_openai_compat_async_client(
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    deps: Optional[RouterDeps] = None,
):
    """Return an object shaped like `openai.AsyncOpenAI()` for chat completions.

    This is intentionally minimal: it only provides `.chat.completions.create(...)`.
    """

    import anyio

    resolved_deps = deps
    default_model = model

    class _ChatCompletions:
        async def create(self, *, messages: list[dict[str, str]], model: str, **kwargs: object) -> OpenAICompatResponse:
            effective_model = default_model or model

            def _run_sync() -> OpenAICompatResponse:
                return chat_completions_create(
                    messages=messages,  # type: ignore[arg-type]
                    model=effective_model,
                    provider=provider,
                    deps=resolved_deps,
                    **kwargs,
                )

            return await anyio.to_thread.run_sync(_run_sync)

    class _Chat:
        def __init__(self) -> None:
            self.completions = _ChatCompletions()

    class _Client:
        def __init__(self) -> None:
            self.chat = _Chat()

    return _Client()


def get_llm_interface(
    *,
    model_name: Optional[str] = None,
    provider: Optional[str] = None,
    deps: Optional[RouterDeps] = None,
    **config_kwargs: object,
):
    """Return an `LLMInterface` backed by this router.

    This is a convenience bridge for the richer GraphRAG/validation tooling in
    `ipfs_datasets_py.llm`.

    The returned interface supports:
    - `generate()` returning `{text, usage, ...}`
    - `generate_with_structured_output()` (best-effort JSON + schema validation)
    - embeddings via the optional embedding adapter
    """

    # Lazy import to keep llm_router lightweight.
    from ipfs_datasets_py.ml.llm.llm_interface import LLMConfig
    from ipfs_datasets_py.ml.llm.llm_router_interface import RoutedLLMInterface

    cfg_model = model_name or os.getenv("IPFS_DATASETS_PY_LLM_MODEL") or "mock-llm"
    config = LLMConfig(model_name=str(cfg_model), **{k: v for k, v in config_kwargs.items()})
    return RoutedLLMInterface(config, provider=provider, deps=deps)
