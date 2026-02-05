"""Model selection config utilities."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Any

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
        "Qwen/Qwen3-1.7B-Thinker",
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
