"""AccelerateManager — dispatches text-generation inference across multiple backends.

Priority order for text-generation tasks:
  1. ipfs_accelerate_py HF inference (if installed; ``allow_local_fallback=False`` so gpt2
     never silently substitutes for an unavailable model)
  2. libp2p p2p_task_queue (requires ``ipfs_accelerate_py.p2p_tasks``; activated when a
     remote multiaddr is configured or discovered via the announce file)
  3. HTTP peer endpoints from ``IPFS_DATASETS_PY_LLM_P2P_ENDPOINTS``

If all three fail, ``RuntimeError`` is raised so that the upstream ``llm_router`` fallback
chain (codex_cli → copilot_cli → hf_inference_api → …) takes over.

Environment variables
---------------------
IPFS_DATASETS_PY_LLM_P2P_ENDPOINTS
    Comma- or newline-separated HTTP base URLs of remote inference peers.
    Each URL is tried with ``POST <url>/generate`` and ``POST <url>/api/generate``
    (Ollama-compatible) in order.  Example::

        IPFS_DATASETS_PY_LLM_P2P_ENDPOINTS=http://192.168.1.10:11434,http://10.0.0.2:8080

IPFS_ACCELERATE_PY_TASK_P2P_REMOTE_MULTIADDR / IPFS_DATASETS_PY_TASK_P2P_REMOTE_MULTIADDR
    libp2p multiaddr of a remote task-queue peer.

IPFS_ACCELERATE_PY_TASK_P2P_REMOTE_PEER_ID / IPFS_DATASETS_PY_TASK_P2P_REMOTE_PEER_ID
    Optional peer-ID hint when the multiaddr does not include ``/p2p/<id>``.

IPFS_ACCELERATE_PY_TASK_P2P_ANNOUNCE_FILE / IPFS_DATASETS_PY_TASK_P2P_ANNOUNCE_FILE
    Path to a JSON announce file written by a local task-queue service.
    Defaults checked: ``~/.cache/ipfs_accelerate_py/task_p2p_announce.json``
    and ``~/.cache/ipfs_datasets_py/task_p2p_announce.json``.

IPFS_DATASETS_PY_ACCELERATE_TIMEOUT
    HTTP and task-queue timeout in seconds (default: 30).

IPFS_DATASETS_PY_TASK_QUEUE_WAIT_TIMEOUT_S / IPFS_ACCELERATE_PY_TASK_QUEUE_WAIT_TIMEOUT_S
    Override wait timeout for the libp2p task queue specifically.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ipfs_accelerate_py import
# ---------------------------------------------------------------------------

def _ensure_ipfs_accelerate_py_on_syspath() -> None:
    """Best-effort: walk up from this file and add the first ``ipfs_accelerate_py``
    *parent* directory found to ``sys.path`` so that the package is importable."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "ipfs_accelerate_py"
        # Only add non-empty directories to avoid masking a real install with an
        # empty submodule checkout.
        if candidate.is_dir() and any(candidate.iterdir()):
            candidate_str = str(parent)  # add the PARENT so `import ipfs_accelerate_py` works
            if candidate_str not in sys.path:
                sys.path.insert(0, candidate_str)
            return


try:
    _ensure_ipfs_accelerate_py_on_syspath()
    from ipfs_accelerate_py import llm_router as _accel_llm_router  # type: ignore[import]
    ACCELERATE_AVAILABLE = True
    ACCELERATE_IMPORT_ERROR: Optional[str] = None
except Exception as _exc:
    logger.debug("ipfs_accelerate_py not available: %s", _exc)
    _accel_llm_router = None
    ACCELERATE_AVAILABLE = False
    ACCELERATE_IMPORT_ERROR = str(_exc)


# ---------------------------------------------------------------------------
# P2P peer discovery helpers
# ---------------------------------------------------------------------------

def _p2p_timeout() -> float:
    raw = (
        os.environ.get("IPFS_DATASETS_PY_ACCELERATE_TIMEOUT")
        or os.environ.get("IPFS_DATASETS_PY_TASK_QUEUE_WAIT_TIMEOUT_S")
        or os.environ.get("IPFS_ACCELERATE_PY_TASK_QUEUE_WAIT_TIMEOUT_S")
        or "30"
    )
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 30.0


def _http_peer_endpoints() -> List[str]:
    raw = os.environ.get("IPFS_DATASETS_PY_LLM_P2P_ENDPOINTS", "").strip()
    if not raw:
        return []
    endpoints = []
    for part in raw.replace("\n", ",").split(","):
        url = part.strip().rstrip("/")
        if url:
            endpoints.append(url)
    return endpoints


def _p2p_remote_multiaddr() -> str:
    return (
        os.environ.get("IPFS_ACCELERATE_PY_TASK_P2P_REMOTE_MULTIADDR")
        or os.environ.get("IPFS_DATASETS_PY_TASK_P2P_REMOTE_MULTIADDR")
        or ""
    ).strip()


def _p2p_remote_peer_id() -> str:
    return (
        os.environ.get("IPFS_ACCELERATE_PY_TASK_P2P_REMOTE_PEER_ID")
        or os.environ.get("IPFS_DATASETS_PY_TASK_P2P_REMOTE_PEER_ID")
        or ""
    ).strip()


def _read_task_p2p_announce() -> Optional[Dict[str, Any]]:
    """Load the announce JSON written by a local task-queue service.

    Searches (in order):
    1. ``IPFS_ACCELERATE_PY_TASK_P2P_ANNOUNCE_FILE`` / ``IPFS_DATASETS_PY_TASK_P2P_ANNOUNCE_FILE`` env var
    2. ``<IPFS_ACCELERATE_PY_STATE_DIR>/task_p2p_announce.json`` if set
    3. ``~/ipfs_accelerate_py/state/task_p2p_announce.json`` (default worker state dir)
    4. ``~/.cache/ipfs_accelerate_py/task_p2p_announce.json``
    5. ``~/.cache/ipfs_datasets_py/task_p2p_announce.json``
    """
    raw = (
        os.environ.get("IPFS_ACCELERATE_PY_TASK_P2P_ANNOUNCE_FILE")
        or os.environ.get("IPFS_DATASETS_PY_TASK_P2P_ANNOUNCE_FILE")
    )
    if raw is not None and str(raw).strip().lower() in {"0", "false", "no", "off"}:
        return None
    home = os.path.expanduser("~")
    cache_root = os.environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")
    state_dir = (
        os.environ.get("IPFS_ACCELERATE_PY_STATE_DIR")
        or os.environ.get("IPFS_DATASETS_PY_STATE_DIR")
        or ""
    ).strip()
    candidates: List[str] = []
    if raw:
        candidates.append(raw.strip())
    if state_dir:
        candidates.append(os.path.join(state_dir, "task_p2p_announce.json"))
    candidates += [
        os.path.join(home, "ipfs_accelerate_py", "state", "task_p2p_announce.json"),
        os.path.join(home, "ipfs_datasets_py", "state", "task_p2p_announce.json"),
        os.path.join(cache_root, "ipfs_accelerate_py", "task_p2p_announce.json"),
        os.path.join(cache_root, "ipfs_datasets_py", "task_p2p_announce.json"),
    ]
    for path in candidates:
        try:
            if not path or not os.path.exists(path):
                continue
            text = open(path, encoding="utf-8").read().strip()
            if not text:
                continue
            info = json.loads(text)
            if isinstance(info, dict) and "/p2p/" in str(info.get("multiaddr", "")):
                logger.debug("Found p2p announce at %s: peer=%s", path, info.get("peer_id", "?"))
                return info
        except Exception:
            continue
    return None


def _extract_text(obj: Any) -> Optional[str]:
    """Recursively pull generated text from an API response object."""
    if isinstance(obj, str) and obj.strip():
        return obj.strip()
    if isinstance(obj, dict):
        for key in ("text", "generated_text", "output_text", "completion", "content", "response"):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        for key in ("result", "data", "output", "payload"):
            nested = _extract_text(obj.get(key))
            if nested:
                return nested
        choices = obj.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message")
                if isinstance(msg, dict):
                    c = msg.get("content")
                    if isinstance(c, str) and c.strip():
                        return c.strip()
                t = first.get("text")
                if isinstance(t, str) and t.strip():
                    return t.strip()
    if isinstance(obj, list):
        for item in obj:
            nested = _extract_text(item)
            if nested:
                return nested
    return None


class AccelerateManager:
    """Coordinates distributed AI compute across ipfs_accelerate_py and libp2p peers.

    Text-generation backends are tried in this order:

    1. **ipfs_accelerate_py** — uses the ``hf`` provider with ``allow_local_fallback=False``
       so gpt2 is never silently loaded as a substitute.
    2. **libp2p task-queue** — submits the prompt to a remote
       ``ipfs_accelerate_py.p2p_tasks`` worker discovered via multiaddr or announce file.
    3. **HTTP peer endpoints** — POSTs to each URL in
       ``IPFS_DATASETS_PY_LLM_P2P_ENDPOINTS`` using the Ollama / HuggingFace
       text-generation API format.

    If all backends fail, ``RuntimeError`` is raised so that the upstream
    ``llm_router`` fallback chain (codex_cli → copilot_cli → hf_inference_api → …)
    can take over.
    """

    def __init__(
        self,
        resources: Optional[Dict[str, Any]] = None,
        ipfs_gateway: Optional[str] = None,
        enable_distributed: bool = True,
    ) -> None:
        self.resources = resources or {}
        self.ipfs_gateway = ipfs_gateway
        self.enable_distributed = enable_distributed
        self._accelerate_available = bool(ACCELERATE_AVAILABLE and _accel_llm_router is not None)

        if self._accelerate_available:
            logger.info("AccelerateManager: ipfs_accelerate_py.llm_router available")
        else:
            logger.info(
                "AccelerateManager: ipfs_accelerate_py unavailable%s",
                f" ({ACCELERATE_IMPORT_ERROR})" if ACCELERATE_IMPORT_ERROR else "",
            )

    def is_available(self) -> bool:
        """Return True if *any* backend — local, peer, or llm_router provider — is reachable."""
        b = self.get_available_backends()
        return bool(b.get("any_available"))

    def get_available_backends(self) -> Dict[str, Any]:
        """Return a dict describing every configured backend (without probing).

        Keys
        ----
        ipfs_accelerate_py
            True if the local ipfs_accelerate_py HF backend is importable.
        p2p_task_queue
            True + ``p2p_task_queue_multiaddr`` if a peer is configured.
        http_peers
            List of configured HTTP endpoint base URLs.
        llm_router_providers
            List of provider names in the llm_router fallback chain that are
            *configured* (binary on PATH or API key present).
        any_available
            Convenience bool — True when at least one backend is configured.
        """
        backends: Dict[str, Any] = {}

        backends["ipfs_accelerate_py"] = self._accelerate_available

        multiaddr = _p2p_remote_multiaddr()
        peer_id = _p2p_remote_peer_id()
        if not multiaddr:
            announce = _read_task_p2p_announce()
            if announce:
                multiaddr = str(announce.get("multiaddr") or "").strip()
                peer_id = peer_id or str(announce.get("peer_id") or "").strip()
        backends["p2p_task_queue"] = bool(multiaddr)
        if multiaddr:
            backends["p2p_task_queue_multiaddr"] = multiaddr
            if peer_id:
                backends["p2p_task_queue_peer_id"] = peer_id

        http_peers = _http_peer_endpoints()
        backends["http_peers"] = http_peers

        available_providers: List[str] = []
        try:
            from ipfs_datasets_py import llm_router as _lr
            for name in getattr(_lr, "_UNPINNED_OPTIONAL_PROVIDER_ORDER", []):
                try:
                    if _lr._builtin_provider_by_name(name) is not None:
                        available_providers.append(name)
                except Exception:
                    continue
        except Exception:
            pass
        backends["llm_router_providers"] = available_providers

        backends["any_available"] = bool(
            self._accelerate_available or multiaddr or http_peers or available_providers
        )
        return backends

    def health_check(self, *, timeout: float = 8.0) -> Dict[str, Any]:
        """Probe every backend and return a live health report.

        Unlike ``get_available_backends()``, this method actually tests each
        backend — running ``--version`` for CLI tools, hitting lightweight API
        endpoints for API-key providers, and calling ``get_capabilities`` for
        p2p peers.

        Returns a dict with one entry per backend name.  Each entry has:

        ``status``  – ``"ok"`` | ``"unavailable"`` | ``"error"``
        ``detail``  – human-readable string explaining the status

        A top-level ``summary`` key lists all healthy backends and is also
        logged at INFO level.
        """
        import shlex
        import shutil
        import subprocess

        report: Dict[str, Any] = {}

        # --- ipfs_accelerate_py -------------------------------------------
        if self._accelerate_available:
            report["ipfs_accelerate_py"] = {"status": "ok", "detail": "importable"}
        else:
            report["ipfs_accelerate_py"] = {
                "status": "unavailable",
                "detail": ACCELERATE_IMPORT_ERROR or "not installed",
            }

        # --- libp2p p2p_task_queue ----------------------------------------
        multiaddr = _p2p_remote_multiaddr()
        peer_id = _p2p_remote_peer_id()
        if not multiaddr:
            announce = _read_task_p2p_announce()
            if announce:
                multiaddr = str(announce.get("multiaddr") or "").strip()
                peer_id = peer_id or str(announce.get("peer_id") or "").strip()
        if multiaddr:
            try:
                from ipfs_datasets_py.ml.accelerate_integration.p2p_task_client import (
                    RemoteQueue,
                    get_capabilities_sync,
                )
                caps = get_capabilities_sync(
                    remote=RemoteQueue(peer_id=peer_id, multiaddr=multiaddr),
                    timeout_s=timeout,
                )
                report["p2p_task_queue"] = {
                    "status": "ok",
                    "detail": f"peer {multiaddr} responded",
                    "multiaddr": multiaddr,
                    "capabilities": caps,
                }
            except Exception as exc:
                report["p2p_task_queue"] = {
                    "status": "error",
                    "detail": f"peer {multiaddr} unreachable: {exc}",
                    "multiaddr": multiaddr,
                }
        else:
            report["p2p_task_queue"] = {
                "status": "unavailable",
                "detail": "no multiaddr configured (set IPFS_ACCELERATE_PY_TASK_P2P_REMOTE_MULTIADDR)",
            }

        # --- HTTP peer endpoints ------------------------------------------
        http_peers = _http_peer_endpoints()
        peer_results: List[Dict[str, Any]] = []
        for base_url in http_peers:
            ok = False
            for probe in ("/health", "/api/tags", "/api/version", "/"):
                url = base_url + probe
                req = urllib.request.Request(url, method="GET",
                                             headers={"Accept": "application/json"})
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        resp.read()
                    peer_results.append({"url": base_url, "status": "ok",
                                         "detail": f"responded at {probe}"})
                    ok = True
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code < 500:
                        peer_results.append({"url": base_url, "status": "ok",
                                             "detail": f"HTTP {exc.code} at {probe}"})
                        ok = True
                        break
                except Exception:
                    continue
            if not ok:
                peer_results.append({"url": base_url, "status": "error",
                                     "detail": "no probe path responded"})
        report["http_peers"] = peer_results if http_peers else {
            "status": "unavailable",
            "detail": "none configured (set IPFS_DATASETS_PY_LLM_P2P_ENDPOINTS)",
        }

        # --- llm_router providers -----------------------------------------
        # Each entry may have:
        #   type          "cli" | "npx" | "key"
        #   cmd           binary name (cli)
        #   pkg           npm package (npx)
        #   version_arg   arg to pass for version check
        #   required_env  list of env vars — at least one must be set (OR credential_files must match)
        #   credential_files list of paths — at least one must exist (alternative to required_env)
        #   env           list of env vars holding the API key (key type)
        #   ping          URL to ping with the API key (key type)
        #   auth_header / auth_prefix  for ping request (key type)
        _home = os.path.expanduser("~")
        _PROVIDER_CHECKS: Dict[str, Dict[str, Any]] = {
            "codex_cli": {
                "type": "cli",
                "cmd": os.getenv("IPFS_DATASETS_PY_CODEX_CLI_BIN", "codex"),
                "version_arg": "--version",
                # codex stores its own auth in ~/.codex/auth.json; falls back to OPENAI_API_KEY
                "required_env": ["OPENAI_API_KEY", "OPENAI_KEY", "OPENAI_TOKEN", "IPFS_DATASETS_PY_OPENAI_API_KEY"],
                "credential_files": [os.path.join(_home, ".codex", "auth.json")],
            },
            "copilot_cli": {
                "type": "npx",
                "pkg": "@github/copilot",
                "version_arg": "--version",
                # copilot uses gh OAuth stored in ~/.config/gh/hosts.yml
                "required_env": ["GITHUB_TOKEN", "GH_TOKEN", "COPILOT_TOKEN"],
                "credential_files": [
                    os.path.join(_home, ".config", "gh", "hosts.yml"),
                    os.path.join(_home, ".config", "github-copilot", "hosts.json"),
                ],
            },
            "openai": {
                "type": "key",
                "env": ["OPENAI_API_KEY", "OPENAI_KEY", "OPENAI_TOKEN", "IPFS_DATASETS_PY_OPENAI_API_KEY"],
                "ping": os.getenv("IPFS_DATASETS_PY_OPENAI_BASE_URL", "https://api.openai.com/v1") + "/models",
                "auth_header": "Authorization",
                "auth_prefix": "Bearer ",
            },
            "hf_inference_api": {
                "type": "key",
                "env": ["HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "IPFS_DATASETS_PY_HF_API_TOKEN"],
                "ping": "https://huggingface.co/api/whoami",
                "auth_header": "Authorization",
                "auth_prefix": "Bearer ",
            },
            "openrouter": {
                "type": "key",
                "env": ["OPENROUTER_API_KEY", "IPFS_DATASETS_PY_OPENROUTER_API_KEY"],
                "ping": "https://openrouter.ai/api/v1/models",
                "auth_header": "Authorization",
                "auth_prefix": "Bearer ",
            },
            "gemini_cli": {
                "type": "npx",
                "pkg": "@google/gemini-cli",
                "version_arg": "--version",
                # gemini-cli requires a Google API key or OAuth via ~/.gemini/
                "required_env": ["GEMINI_API_KEY", "GOOGLE_API_KEY", "IPFS_DATASETS_PY_GEMINI_API_KEY"],
                "credential_files": [
                    os.path.join(_home, ".gemini", "credentials.json"),
                    os.path.join(_home, ".gemini", "oauth_creds.json"),
                    os.path.join(_home, ".config", "gemini", "credentials.json"),
                ],
            },
            "claude_code": {
                "type": "cli",
                "cmd": "claude",
                "version_arg": "--version",
                "required_env": ["ANTHROPIC_API_KEY", "IPFS_DATASETS_PY_ANTHROPIC_API_KEY"],
                "credential_files": [
                    os.path.join(_home, ".claude", "credentials.json"),
                    os.path.join(_home, ".config", "claude", "credentials.json"),
                ],
            },
            "claude_py": {
                "type": "key",
                "env": ["ANTHROPIC_API_KEY", "IPFS_DATASETS_PY_ANTHROPIC_API_KEY"],
            },
            "gemini_py": {
                "type": "key",
                "env": ["GOOGLE_API_KEY", "GEMINI_API_KEY", "IPFS_DATASETS_PY_GEMINI_API_KEY"],
            },
            "copilot_sdk": {
                "type": "key",
                "env": ["GITHUB_TOKEN", "GH_TOKEN", "COPILOT_TOKEN", "IPFS_DATASETS_PY_GITHUB_TOKEN"],
                "credential_files": [
                    os.path.join(_home, ".config", "gh", "hosts.yml"),
                ],
            },
        }

        def _has_credentials(check: Dict[str, Any]) -> tuple[bool, str]:
            """Return (ok, detail) for env-var or credential-file credential check."""
            required_env: List[str] = check.get("required_env", [])
            cred_files: List[str] = check.get("credential_files", [])
            if not required_env and not cred_files:
                return True, ""
            # Check env vars
            found_env = next((e for e in required_env if os.environ.get(e)), None)
            if found_env:
                return True, f"credentials via {found_env}"
            # Check credential files
            found_file = next((f for f in cred_files if os.path.isfile(f)), None)
            if found_file:
                return True, f"credentials at {os.path.basename(found_file)}"
            env_names = ", ".join(required_env) if required_env else ""
            file_names = ", ".join(os.path.basename(f) for f in cred_files) if cred_files else ""
            missing = " or ".join(filter(None, [env_names, file_names]))
            return False, f"no credentials ({missing})"

        provider_report: Dict[str, Dict[str, Any]] = {}
        try:
            from ipfs_datasets_py import llm_router as _lr
            provider_order = getattr(_lr, "_UNPINNED_OPTIONAL_PROVIDER_ORDER", list(_PROVIDER_CHECKS))
        except Exception:
            provider_order = list(_PROVIDER_CHECKS)

        for name in provider_order:
            check = _PROVIDER_CHECKS.get(name, {})
            kind = check.get("type", "unknown")

            if kind == "cli":
                cmd = str(check.get("cmd", name))
                binary = shutil.which(cmd)
                if not binary:
                    provider_report[name] = {"status": "unavailable", "detail": f"{cmd!r} not on PATH"}
                    continue
                cred_ok, cred_detail = _has_credentials(check)
                if not cred_ok:
                    provider_report[name] = {"status": "unavailable", "detail": cred_detail}
                    continue
                try:
                    version_arg = str(check.get("version_arg", "--version"))
                    proc = subprocess.run(
                        [binary, version_arg],
                        capture_output=True, text=True, timeout=timeout, check=False,
                    )
                    version = (proc.stdout or proc.stderr or "").strip().splitlines()[0]
                    detail = version or "responded to --version"
                    if cred_detail:
                        detail += f"; {cred_detail}"
                    provider_report[name] = {"status": "ok", "detail": detail}
                except Exception as exc:
                    detail = f"binary found; {cred_detail}" if cred_detail else f"binary found ({exc})"
                    provider_report[name] = {"status": "ok", "detail": detail}

            elif kind == "npx":
                pkg = str(check.get("pkg", ""))
                version_arg = str(check.get("version_arg", "--version"))
                cred_ok, cred_detail = _has_credentials(check)
                if not cred_ok:
                    provider_report[name] = {"status": "unavailable", "detail": cred_detail}
                    continue
                try:
                    proc = subprocess.run(
                        ["npx", "--yes", pkg, version_arg],
                        capture_output=True, text=True, timeout=timeout, check=False,
                    )
                    version = (proc.stdout or proc.stderr or "").strip().splitlines()[0]
                    if proc.returncode == 0 or version:
                        detail = version or "npx ok"
                        if cred_detail:
                            detail += f"; {cred_detail}"
                        provider_report[name] = {"status": "ok", "detail": detail}
                    else:
                        provider_report[name] = {"status": "error", "detail": f"npx {pkg} exit {proc.returncode}"}
                except Exception as exc:
                    provider_report[name] = {"status": "error", "detail": str(exc)}

            elif kind == "key":
                envs: List[str] = check.get("env", [])
                cred_files: List[str] = check.get("credential_files", [])
                api_key = next((os.environ.get(e) for e in envs if os.environ.get(e)), None)
                cred_file = next((f for f in cred_files if os.path.isfile(f)), None) if not api_key else None
                if not api_key and not cred_file:
                    env_names = ", ".join(envs)
                    provider_report[name] = {"status": "unavailable",
                                             "detail": f"no API key ({env_names})"}
                    continue
                cred_source = f"credentials via {next(e for e in envs if os.environ.get(e))}" if api_key else f"credentials at {os.path.basename(cred_file)}"  # type: ignore[arg-type]
                ping = str(check.get("ping", ""))
                if ping and api_key:
                    auth_header = str(check.get("auth_header", "Authorization"))
                    auth_prefix = str(check.get("auth_prefix", "Bearer "))
                    req = urllib.request.Request(ping, method="GET",
                                                 headers={auth_header: auth_prefix + api_key,
                                                          "Accept": "application/json"})
                    try:
                        with urllib.request.urlopen(req, timeout=timeout) as resp:
                            body = json.loads(resp.read().decode())
                        # Surface useful info from whoami / models endpoints
                        detail = (str(body.get("name") or body.get("id") or cred_source)
                                  if isinstance(body, dict) else cred_source)
                        provider_report[name] = {"status": "ok", "detail": detail}
                    except urllib.error.HTTPError as exc:
                        if exc.code == 401:
                            provider_report[name] = {"status": "error", "detail": "API key rejected (401)"}
                        elif exc.code == 403:
                            provider_report[name] = {"status": "error", "detail": "API key forbidden (403)"}
                        else:
                            provider_report[name] = {"status": "ok",
                                                     "detail": f"{cred_source}; ping returned HTTP {exc.code}"}
                    except Exception as exc:
                        provider_report[name] = {"status": "ok",
                                                 "detail": f"{cred_source}; ping failed ({exc})"}
                else:
                    provider_report[name] = {"status": "ok", "detail": cred_source}

            else:
                # Fallback: just check if llm_router returns a provider object
                try:
                    from ipfs_datasets_py import llm_router as _lr
                    p = _lr._builtin_provider_by_name(name)
                    if p is not None:
                        provider_report[name] = {"status": "ok", "detail": "provider object available"}
                    else:
                        provider_report[name] = {"status": "unavailable", "detail": "not configured"}
                except Exception as exc:
                    provider_report[name] = {"status": "error", "detail": str(exc)}

        report["llm_router_providers"] = provider_report

        # --- Summary ------------------------------------------------------
        healthy: List[str] = []
        if report["ipfs_accelerate_py"]["status"] == "ok":
            healthy.append("ipfs_accelerate_py")
        if isinstance(report.get("p2p_task_queue"), dict) and report["p2p_task_queue"].get("status") == "ok":
            healthy.append("p2p_task_queue")
        for p in peer_results:
            if p.get("status") == "ok":
                healthy.append(f"http_peer:{p['url']}")
        for pname, pinfo in provider_report.items():
            if pinfo.get("status") == "ok":
                healthy.append(pname)

        summary = f"Available backends: {', '.join(healthy)}" if healthy else "No backends available"
        report["summary"] = summary
        report["any_available"] = bool(healthy)

        logger.info("AccelerateManager health_check: %s", summary)
        return report

    # ------------------------------------------------------------------
    # Public inference entry point
    # ------------------------------------------------------------------

    def run_inference(
        self,
        model_name: str,
        input_data: Any,
        task_type: Optional[str] = None,
        hardware: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Run inference, trying backends in priority order.

        Args:
            model_name: Model identifier (e.g. ``"gpt-5.5"`` or ``"meta-llama/Llama-3-8B"``).
            input_data: Either a ``{"prompt": "..."}`` dict or a raw prompt string.
            task_type: Task descriptor — generation variants are handled here;
                       anything else raises immediately so llm_router can route it.
            hardware: Preferred hardware hint (passed to ipfs_accelerate_py when available).
            **kwargs: Extra kwargs forwarded to each backend attempt.

        Returns:
            ``{"status": "success", "backend": "<name>", "model": "...", "text": "..."}``

        Raises:
            RuntimeError: when all backends fail.
        """
        _ = hardware
        normalized_task = (task_type or "").strip().lower()

        _GENERATION_TASKS = {
            "text-generation", "text_generation", "generation", "generate", "completion",
        }
        if normalized_task not in _GENERATION_TASKS:
            raise RuntimeError(
                f"AccelerateManager: unsupported task type {task_type!r} for {model_name}; "
                "delegating to llm_router"
            )

        if isinstance(input_data, dict) and "prompt" in input_data:
            prompt = str(input_data.get("prompt") or "")
        else:
            prompt = str(input_data)

        errors: List[str] = []

        # 1. ipfs_accelerate_py HF inference
        if self._accelerate_available and _accel_llm_router is not None:
            try:
                result = self._try_ipfs_accelerate(model_name, prompt, **kwargs)
                if result:
                    return result
            except Exception as exc:
                errors.append(f"ipfs_accelerate_py: {exc}")
                logger.debug("ipfs_accelerate_py backend failed: %s", exc)

        # 2. libp2p p2p_task_queue
        try:
            result = self._try_p2p_task_queue(model_name, prompt, **kwargs)
            if result:
                return result
        except Exception as exc:
            errors.append(f"p2p_task_queue: {exc}")
            logger.debug("p2p_task_queue backend failed: %s", exc)

        # 3. HTTP peer endpoints
        try:
            result = self._try_http_peers(model_name, prompt, **kwargs)
            if result:
                return result
        except Exception as exc:
            errors.append(f"http_peers: {exc}")
            logger.debug("http_peers backend failed: %s", exc)

        raise RuntimeError(
            f"AccelerateManager: all backends failed for {model_name!r}. "
            f"Errors: {'; '.join(errors) or 'none attempted'}. "
            "Delegating to llm_router fallback chain."
        )

    # ------------------------------------------------------------------
    # Backend: ipfs_accelerate_py HF inference
    # ------------------------------------------------------------------

    def _try_ipfs_accelerate(
        self, model_name: str, prompt: str, **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        """Try ipfs_accelerate_py's HF inference provider.

        Passes ``allow_local_fallback=False`` to prevent silent gpt2 substitution.
        """
        assert _accel_llm_router is not None  # checked by caller
        accel_kwargs = dict(kwargs)
        accel_kwargs.setdefault("allow_local_fallback", False)
        text = _accel_llm_router.generate_text(
            prompt,
            provider="hf",
            model_name=model_name,
            **accel_kwargs,
        )
        if not text or not str(text).strip():
            raise RuntimeError(f"ipfs_accelerate_py returned empty text for {model_name!r}")
        return {"status": "success", "backend": "ipfs_accelerate_py", "model": model_name, "text": str(text)}

    # ------------------------------------------------------------------
    # Backend: libp2p p2p_task_queue
    # ------------------------------------------------------------------

    def _try_p2p_task_queue(
        self, model_name: str, prompt: str, **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        """Submit the prompt to a remote libp2p task-queue worker.

        Requires ``ipfs_accelerate_py.p2p_tasks`` to be installed and either:
          - ``IPFS_ACCELERATE_PY_TASK_P2P_REMOTE_MULTIADDR`` set, OR
          - a valid announce file present at the default location
            (``~/ipfs_accelerate_py/state/task_p2p_announce.json`` etc).
        """
        multiaddr = _p2p_remote_multiaddr()
        peer_id = _p2p_remote_peer_id()
        if not multiaddr:
            announce = _read_task_p2p_announce()
            if announce:
                multiaddr = str(announce.get("multiaddr") or "").strip()
                peer_id = peer_id or str(announce.get("peer_id") or "").strip()

        if not multiaddr:
            return None  # no peer configured — skip silently

        timeout = _p2p_timeout()
        max_new_tokens = int(kwargs.get("max_new_tokens") or kwargs.get("max_tokens") or 512)

        try:
            from ipfs_datasets_py.ml.accelerate_integration.p2p_task_client import (
                RemoteQueue,
                submit_task_with_info,
                wait_task,
            )
        except ImportError as exc:
            raise RuntimeError(f"p2p_task_client not available: {exc}") from exc

        remote = RemoteQueue(peer_id=peer_id, multiaddr=multiaddr)
        payload: Dict[str, Any] = {"prompt": prompt, "max_new_tokens": max_new_tokens}
        for k in ("temperature", "top_p", "top_k", "repetition_penalty"):
            if k in kwargs:
                payload[k] = kwargs[k]

        logger.info("AccelerateManager: submitting p2p task to %s", multiaddr)

        async def _run() -> Optional[str]:
            info = await submit_task_with_info(
                remote=remote,
                task_type="text-generation",
                model_name=model_name,
                payload=payload,
            )
            task_id = info.get("task_id") or ""
            if not task_id:
                logger.warning("p2p_task_queue: no task_id in response: %s", info)
                return None
            logger.debug("p2p task submitted: id=%s via %s", task_id, multiaddr)
            result = await wait_task(remote=remote, task_id=task_id, timeout_s=timeout)
            if result is None:
                return None
            return _extract_text(result)

        # The libp2p client internals use trio nurseries directly, so we must
        # run under trio.run() — not anyio.run(..., backend="trio").
        try:
            import trio as _trio
            text = _trio.run(_run)
        except ImportError:
            try:
                import anyio as _anyio
                text = _anyio.run(_run, backend="trio")
            except Exception as exc:
                raise RuntimeError(f"Cannot run async p2p task (no trio/anyio): {exc}") from exc

        if not text:
            raise RuntimeError(f"p2p_task_queue peer {multiaddr!r} returned no text for {model_name!r}")
        logger.info("AccelerateManager: p2p_task_queue served %s via %s", model_name, multiaddr)
        return {"status": "success", "backend": "p2p_task_queue", "model": model_name, "text": text, "peer": multiaddr}

    # ------------------------------------------------------------------
    # Backend: HTTP peer endpoints
    # ------------------------------------------------------------------

    def _try_http_peers(
        self, model_name: str, prompt: str, **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        """POST the prompt to each HTTP endpoint in ``IPFS_DATASETS_PY_LLM_P2P_ENDPOINTS``.

        Tries ``POST <base_url>/generate`` first (HuggingFace TGI / custom servers)
        then ``POST <base_url>/api/generate`` (Ollama).
        Request body: ``{"model": "...", "prompt": "...", "stream": false, ...}``.
        """
        endpoints = _http_peer_endpoints()
        if not endpoints:
            return None

        timeout = _p2p_timeout()
        max_new_tokens = int(kwargs.get("max_new_tokens") or kwargs.get("max_tokens") or 512)
        body: Dict[str, Any] = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "max_new_tokens": max_new_tokens,
            "parameters": {"max_new_tokens": max_new_tokens},
        }
        for k in ("temperature", "top_p", "top_k"):
            if k in kwargs:
                body[k] = kwargs[k]
                body.setdefault("parameters", {})[k] = kwargs[k]  # type: ignore[index]

        data = json.dumps(body).encode()
        last_error: Optional[Exception] = None

        for base_url in endpoints:
            for path in ("/generate", "/api/generate", "/v1/completions"):
                url = base_url + path
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        raw = resp.read()
                    obj = json.loads(raw.decode())
                    text = _extract_text(obj)
                    if text:
                        logger.info("AccelerateManager: HTTP peer %s served %s", base_url, model_name)
                        return {
                            "status": "success",
                            "backend": "http_peer",
                            "model": model_name,
                            "text": text,
                            "peer": base_url,
                        }
                except urllib.error.HTTPError as exc:
                    last_error = exc
                    if exc.code == 404:
                        continue  # try next path
                    logger.debug("HTTP peer %s%s → HTTP %s", base_url, path, exc.code)
                    break  # other errors: skip this endpoint
                except Exception as exc:
                    last_error = exc
                    logger.debug("HTTP peer %s%s failed: %s", base_url, path, exc)
                    break

        if last_error is not None:
            raise RuntimeError(f"All HTTP peers failed for {model_name!r}: {last_error}")
        return None

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_available_hardware(self) -> List[str]:
        """Return available hardware backends."""
        hardware = ["cpu"]
        try:
            import torch
            if torch.cuda.is_available():
                hardware.append("cuda")
        except ImportError:
            pass
        return hardware

    def get_status(self) -> Dict[str, Any]:
        """Return manager status and capability summary."""
        multiaddr = _p2p_remote_multiaddr()
        announce = None if multiaddr else _read_task_p2p_announce()
        p2p_configured = bool(multiaddr or (announce and announce.get("multiaddr")))
        http_peers = _http_peer_endpoints()

        return {
            "accelerate_available": ACCELERATE_AVAILABLE,
            "accelerate_initialized": self._accelerate_available,
            "accelerate_import_error": ACCELERATE_IMPORT_ERROR,
            "distributed_enabled": self.enable_distributed,
            "ipfs_gateway": self.ipfs_gateway,
            "available_hardware": self.get_available_hardware(),
            "p2p_task_queue_configured": p2p_configured,
            "p2p_remote_multiaddr": multiaddr or (announce or {}).get("multiaddr"),
            "http_peer_endpoints": http_peers,
            "http_peer_count": len(http_peers),
        }
