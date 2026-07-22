import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _default_symai_config() -> Dict[str, Any]:
    # Mirrors symai.setup_wizard() defaults to avoid KeyErrors at import-time.
    return {
        "NEUROSYMBOLIC_ENGINE_API_KEY": "",
        "NEUROSYMBOLIC_ENGINE_MODEL": "",
        "SYMBOLIC_ENGINE_API_KEY": "",
        "SYMBOLIC_ENGINE": "",
        "FORMAL_ENGINE_API_KEY": "",
        "FORMAL_ENGINE": "",
        "EMBEDDING_ENGINE_API_KEY": "",
        "EMBEDDING_ENGINE_MODEL": "",
        "DRAWING_ENGINE_API_KEY": "",
        "DRAWING_ENGINE_MODEL": "",
        "VISION_ENGINE_MODEL": "",
        "SEARCH_ENGINE_API_KEY": "",
        "SEARCH_ENGINE_MODEL": "",
        "OCR_ENGINE_API_KEY": "",
        "OCR_ENGINE_MODEL": "",
        "SPEECH_TO_TEXT_ENGINE_MODEL": "",
        "SPEECH_TO_TEXT_API_KEY": "",
        "TEXT_TO_SPEECH_ENGINE_API_KEY": "",
        "TEXT_TO_SPEECH_ENGINE_MODEL": "",
        "TEXT_TO_SPEECH_ENGINE_VOICE": "",
        "INDEXING_ENGINE_API_KEY": "",
        "INDEXING_ENGINE_ENVIRONMENT": "",
        "CAPTION_ENGINE_MODEL": "",
    }


def ensure_symai_config(
    *,
    neurosymbolic_model: str,
    neurosymbolic_api_key: str,
    force: bool = False,
    apply_engine_router: bool = False,
    config_root: Optional[Path] = None,
) -> Optional[Path]:
    """Ensure `symai` has a config file so `import symai` doesn't call sys.exit(1).

    SymbolicAI (`symai`) normally reads configuration from
    `${sys.prefix}/.symai/symai.config.json` (i.e. the active venv). A caller
    may provide a writable fallback root for read-only system environments.
    If the config is missing or incomplete, SymbolicAI runs a setup wizard.

    This helper writes a minimal, non-interactive config.

    Returns the path written/used, or None if it couldn't be written.
    """

    if not neurosymbolic_model:
        return None

    config_dir = Path(config_root or sys.prefix) / ".symai"
    config_path = config_dir / "symai.config.json"

    try:
        config_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None

    existing: Dict[str, Any] = {}
    if config_path.exists() and not force:
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    config = _default_symai_config()
    config.update(existing)

    # Only overwrite neurosymbolic values if force is enabled or they are missing.
    if force or not config.get("NEUROSYMBOLIC_ENGINE_MODEL"):
        config["NEUROSYMBOLIC_ENGINE_MODEL"] = neurosymbolic_model
    if force or not config.get("NEUROSYMBOLIC_ENGINE_API_KEY"):
        config["NEUROSYMBOLIC_ENGINE_API_KEY"] = neurosymbolic_api_key

    if apply_engine_router:
        def set_if_empty(key: str, value: str) -> None:
            if force or not config.get(key):
                config[key] = value

        set_if_empty("SYMBOLIC_ENGINE", "ipfs")
        set_if_empty(
            "NEUROSYMBOLIC_ENGINE_MODEL",
            os.environ.get("IPFS_DATASETS_PY_SYMAI_NEUROSYMBOLIC_MODEL", "ipfs:default"),
        )
        set_if_empty("NEUROSYMBOLIC_ENGINE_API_KEY", "ipfs")
        set_if_empty("EMBEDDING_ENGINE_MODEL", os.environ.get("IPFS_DATASETS_PY_SYMAI_EMBEDDING_MODEL", "ipfs:default"))
        set_if_empty("SEARCH_ENGINE_MODEL", os.environ.get("IPFS_DATASETS_PY_SYMAI_SEARCH_MODEL", "ipfs:default"))
        set_if_empty("OCR_ENGINE_MODEL", os.environ.get("IPFS_DATASETS_PY_SYMAI_OCR_MODEL", "ipfs:default"))
        set_if_empty("SPEECH_TO_TEXT_ENGINE_MODEL", os.environ.get("IPFS_DATASETS_PY_SYMAI_SPEECH_TO_TEXT_MODEL", "ipfs:default"))
        set_if_empty("TEXT_TO_SPEECH_ENGINE_MODEL", os.environ.get("IPFS_DATASETS_PY_SYMAI_TEXT_TO_SPEECH_MODEL", "ipfs:default"))
        set_if_empty("DRAWING_ENGINE_MODEL", os.environ.get("IPFS_DATASETS_PY_SYMAI_DRAWING_MODEL", "ipfs:default"))
        set_if_empty("VISION_ENGINE_MODEL", os.environ.get("IPFS_DATASETS_PY_SYMAI_VISION_MODEL", "ipfs:default"))
        set_if_empty("CAPTION_ENGINE_MODEL", os.environ.get("IPFS_DATASETS_PY_SYMAI_CAPTION_MODEL", "ipfs:default"))
        set_if_empty("INDEXING_ENGINE_ENVIRONMENT", os.environ.get("IPFS_DATASETS_PY_SYMAI_INDEXING_ENV", "ipfs:default"))

    try:
        config_path.write_text(json.dumps(config, indent=4), encoding="utf-8")
    except Exception:
        return None

    return config_path


def choose_symai_neurosymbolic_engine() -> Optional[Dict[str, str]]:
    """Best-effort choice of a `symai` neurosymbolic engine.

    Preference order:
    1) Real OpenAI API key present -> use OpenAI Responses engine.
    2) If enabled and `codex` is available -> route via `codex exec`.

    This returns a dict with keys: model, api_key.
    """

    # 1) Real API key.
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if openai_api_key:
        return {
            # `symai` selects OpenAI Responses engine when model starts with `responses:`
            "model": os.environ.get("NEUROSYMBOLIC_ENGINE_MODEL", "responses:o3-mini"),
            "api_key": openai_api_key,
        }

    # 2) Codex CLI routing (explicit opt-in).
    use_codex = os.environ.get("IPFS_DATASETS_PY_USE_CODEX_FOR_SYMAI", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not use_codex:
        return None

    try:
        import shutil

        codex_path = shutil.which("codex")
    except Exception:
        codex_path = None

    if not codex_path:
        return None

    # Under many Codex (ChatGPT/OAuth) logins, only certain model IDs are supported.
    # We have empirically validated `gpt-5.2-codex` works in this environment, while
    # some `*-chat-latest` / `*-pro` variants can be rejected.
    codex_model = os.environ.get("IPFS_DATASETS_PY_CODEX_MODEL", "gpt-5.2-codex")
    return {
        # We'll register a plugin engine that claims `neurosymbolic` when model starts with `codex:`
        "model": f"codex:{codex_model}",
        # `symai` requires non-empty API key for non-llama/huggingface models.
        # This value is not used by the Codex engine; it just prevents `symai` from exiting.
        "api_key": "codex",
    }


def _writable_symai_config_root() -> Optional[Path]:
    """Return a writable root compatible with SymbolicAI's config manager.

    System Python installations commonly expose a read-only ``sys.prefix``.
    SymbolicAI nevertheless creates ``<prefix>/.symai`` during import, so use
    the user's home as a deterministic fallback rather than failing imports
    with ``PermissionError``.
    """

    configured_root = str(
        os.environ.get("IPFS_DATASETS_PY_SYMAI_CONFIG_ROOT") or ""
    ).strip()
    candidates = [Path(configured_root)] if configured_root else []
    candidates.extend((Path(sys.prefix), Path.home()))

    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.expanduser()
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            (candidate / ".symai").mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        return candidate
    return None


def ensure_symai_config_for_import(*, force: bool = False) -> Optional[Path]:
    """Prepare and, when necessary, safely initialize SymbolicAI.

    ``symai`` creates its environment config directory before considering its
    writable home-directory fallback.  When ``sys.prefix`` is read-only, load
    it once under the selected writable root and immediately restore the real
    interpreter prefix.  Subsequent imports reuse the initialized module and
    do not mutate global interpreter paths.
    """

    config_root = _writable_symai_config_root()
    if config_root is None:
        return None

    chosen_engine = choose_symai_neurosymbolic_engine() or {}
    config_path = ensure_symai_config(
        neurosymbolic_model=str(
            chosen_engine.get("model")
            or os.environ.get("NEUROSYMBOLIC_ENGINE_MODEL")
            or os.environ.get("IPFS_DATASETS_PY_SYMAI_NEUROSYMBOLIC_MODEL")
            or "ipfs:default"
        ),
        neurosymbolic_api_key=str(
            chosen_engine.get("api_key")
            or os.environ.get("NEUROSYMBOLIC_ENGINE_API_KEY")
            or os.environ.get("IPFS_DATASETS_PY_SYMAI_NEUROSYMBOLIC_API_KEY")
            or "ipfs"
        ),
        force=force,
        apply_engine_router=True,
        config_root=config_root,
    )
    if config_path is None:
        return None

    original_prefix = sys.prefix
    if config_root != Path(original_prefix) and "symai" not in sys.modules:
        try:
            sys.prefix = str(config_root)
            importlib.import_module("symai")
        finally:
            sys.prefix = original_prefix
    return config_path
