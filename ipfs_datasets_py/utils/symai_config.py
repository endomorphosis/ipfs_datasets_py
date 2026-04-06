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
        "EMBEDDING_ENGINE_API_KEY": "",
        "EMBEDDING_ENGINE_MODEL": "",
        "DRAWING_ENGINE_API_KEY": "",
        "DRAWING_ENGINE_MODEL": "",
        "VISION_ENGINE_MODEL": "",
        "SEARCH_ENGINE_API_KEY": "",
        "SEARCH_ENGINE_MODEL": "",
        "OCR_ENGINE_API_KEY": "",
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
) -> Optional[Path]:
    """Ensure `symai` has a config file so `import symai` doesn't call sys.exit(1).

    SymbolicAI (`symai`) reads configuration from `${sys.prefix}/.symai/symai.config.json`
    (i.e. the active venv). If missing or incomplete, it runs a setup wizard then exits.

    This helper writes a minimal, non-interactive config.

    Returns the path written/used, or None if it couldn't be written.
    """

    if not neurosymbolic_model:
        return None

    config_dir = Path(sys.prefix) / ".symai"
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
        if not neurosymbolic_model:
            set_if_empty(
                "NEUROSYMBOLIC_ENGINE_MODEL",
                os.environ.get("IPFS_DATASETS_PY_SYMAI_NEUROSYMBOLIC_MODEL", "ipfs:default"),
            )
        if not neurosymbolic_api_key:
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
    1) Explicit SyMAI model/api-key environment configuration.
    2) Real OpenAI API key present -> use OpenAI Responses engine.
    3) Codex-backed llm_router when Codex CLI is available.

    This returns a dict with keys: model, api_key.
    """

    explicit_model = os.environ.get("NEUROSYMBOLIC_ENGINE_MODEL", "").strip()
    explicit_api_key = os.environ.get("NEUROSYMBOLIC_ENGINE_API_KEY", "").strip()
    if explicit_model:
        resolved_api_key = explicit_api_key
        if explicit_model.startswith("codex:") and not resolved_api_key:
            resolved_api_key = "codex"
        if explicit_model.startswith(("llama", "huggingface")) or resolved_api_key:
            return {
                "model": explicit_model,
                "api_key": resolved_api_key,
            }

    # 2) Real API key.
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if openai_api_key:
        return {
            # `symai` selects OpenAI Responses engine when model starts with `responses:`
            "model": os.environ.get("NEUROSYMBOLIC_ENGINE_MODEL", "responses:o3-mini"),
            "api_key": openai_api_key,
        }

    # 3) Codex CLI routing via llm_router. This is the practical default in this
    # workspace when Codex is available, but callers can disable it explicitly.
    disable_codex = os.environ.get("IPFS_DATASETS_PY_DISABLE_CODEX_FOR_SYMAI", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    explicit_codex_pref = os.environ.get("IPFS_DATASETS_PY_USE_CODEX_FOR_SYMAI", "").strip().lower()
    if disable_codex or explicit_codex_pref in {"0", "false", "no", "off"}:
        return None

    try:
        import shutil

        codex_path = shutil.which("codex")
    except Exception:
        codex_path = None

    if not codex_path:
        return None

    # Prefer the faster Spark variant by default and let callers override via env.
    codex_model = os.environ.get("IPFS_DATASETS_PY_CODEX_MODEL", "gpt-5.3-codex-spark")
    return {
        # We'll register a plugin engine that claims `neurosymbolic` when model starts with `codex:`
        "model": f"codex:{codex_model}",
        # `symai` requires non-empty API key for non-llama/huggingface models.
        # This value is not used by the Codex engine; it just prevents `symai` from exiting.
        "api_key": "codex",
    }
