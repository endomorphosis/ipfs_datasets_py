"""Load the Hugging Face token for Hub reads and writes. Never print it."""

from __future__ import annotations

import json
from pathlib import Path

TOKEN_PATH = Path(
    "/home/box/agent-data/connector-secrets/67930c3f-c94b-445b-a5bc-01d3fc1135c1/huggingface.json"
)

_cached: str | None = None
_configured = False


def load_token() -> str:
    global _cached
    if _cached:
        return _cached
    payload = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    token = payload.get("token")
    if not token or not isinstance(token, str):
        raise RuntimeError("Hugging Face token missing from connector secret")
    _cached = token
    return token


def configure_hf() -> None:
    """Install the token for huggingface_hub / HF_TOKEN without printing it.

    Prefer in-process HfApi(token=...) and huggingface_hub.login so the token
    is not added to the process argv. HF_TOKEN is set in this interpreter only.
    """
    global _configured
    if _configured:
        return
    import contextlib
    import io
    import os

    from huggingface_hub import login

    token = load_token()
    # Interpreter env only; do not export from a shell wrapper (shows in `ps e`).
    os.environ["HF_TOKEN"] = token
    os.environ["HUGGING_FACE_HUB_TOKEN"] = token
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        login(token=token, add_to_git_credential=False)
    _configured = True
