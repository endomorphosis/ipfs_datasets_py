"""Process-local bootstrap hooks for benchmark subprocesses.

Python automatically imports `sitecustomize` (if present on `sys.path`) after
initializing `site`. We keep this file intentionally inert by default.

Enable with:
  - IPFS_DATASETS_PY_SYMAI_SITEBOOT=1

This is primarily used by the temporal/deontic benchmark runner so that SyMAI
engine registration happens inside the spawned test process (not the parent).
"""

from __future__ import annotations

import os


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _bootstrap_symai_engines() -> None:
    # Keep imports local and best-effort.
    try:
        import symai  # noqa: F401
        from symai.functional import EngineRepository
    except Exception:
        return

    # If Codex routing is enabled (or codex:* model is set), register the codex neurosymbolic engine.
    use_codex = _truthy(os.environ.get("IPFS_DATASETS_PY_USE_CODEX_FOR_SYMAI"))
    model_value = os.environ.get("NEUROSYMBOLIC_ENGINE_MODEL", "")
    if str(model_value).startswith("codex:"):
        use_codex = True

    if use_codex:
        try:
            from ipfs_datasets_py.utils.symai_codex_engine import CodexExecNeurosymbolicEngine

            EngineRepository.register(
                "neurosymbolic",
                CodexExecNeurosymbolicEngine(),
                allow_engine_override=True,
            )
        except Exception:
            # Never fail import due to bootstrap issues.
            return

    # Always attempt to register the IPFS engine suite when requested.
    if _truthy(os.environ.get("IPFS_DATASETS_PY_USE_SYMAI_ENGINE_ROUTER")):
        try:
            from ipfs_datasets_py.utils.symai_ipfs_engine import register_ipfs_symai_engines

            register_ipfs_symai_engines()
        except Exception:
            return


if _truthy(os.environ.get("IPFS_DATASETS_PY_SYMAI_SITEBOOT")):
    _bootstrap_symai_engines()
