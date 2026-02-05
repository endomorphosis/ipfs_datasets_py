import os
import subprocess
import tempfile
import time
from copy import deepcopy
from typing import Any, Dict, List, Tuple

from symai.backend.base import Engine
from symai.backend.settings import SYMAI_CONFIG


class CodexExecNeurosymbolicEngine(Engine):
    """A minimal `symai` neurosymbolic engine that delegates to `codex exec`.

    This is intentionally simple: it aims to support the subset of SymbolicAI
    usage in this repo (prompt -> text). It does not attempt to implement full
    OpenAI tool-calling parity.
    """

    def __init__(self):
        super().__init__()
        self.config = deepcopy(SYMAI_CONFIG)
        if self.id() != "neurosymbolic":
            return

        # Strip `codex:` prefix.
        raw_model = self.config.get("NEUROSYMBOLIC_ENGINE_MODEL", "")
        self.model = raw_model[len("codex:") :] if raw_model.startswith("codex:") else raw_model

        self.fallback_model = os.environ.get("IPFS_DATASETS_PY_CODEX_FALLBACK_MODEL", "gpt-5.1-codex-mini")
        self.max_retries = int(os.environ.get("IPFS_DATASETS_PY_CODEX_MAX_RETRIES", "3"))
        self.backoff_base = float(os.environ.get("IPFS_DATASETS_PY_CODEX_BACKOFF_BASE", "1.0"))

        # Safety defaults for agentic behavior.
        self.sandbox = os.environ.get("IPFS_DATASETS_PY_CODEX_SANDBOX", "read-only")
        self.skip_git_repo_check = True

    def _is_backoff_error(self, stderr: str) -> bool:
        if not stderr:
            return False
        lowered = stderr.lower()
        return any(token in lowered for token in ["429", "too many requests", "rate limit", "usage_limit"]) 

    def _is_unsupported_model(self, stderr: str) -> bool:
        if not stderr:
            return False
        lowered = stderr.lower()
        return "not supported" in lowered

    def id(self) -> str:
        model = self.config.get("NEUROSYMBOLIC_ENGINE_MODEL")
        if isinstance(model, str) and model.startswith("codex:"):
            return "neurosymbolic"
        return super().id()

    def prepare(self, argument):
        # `symai` expects `prepared_input` to be set.
        if getattr(argument.prop, "raw_input", False):
            argument.prop.prepared_input = str(argument.prop.processed_input)
            return

        parts: List[str] = []

        prompt = getattr(argument.prop, "prompt", None)
        if prompt:
            parts.append(str(prompt).strip())

        instance = getattr(argument.prop, "instance", None)
        global_context = getattr(instance, "global_context", None)
        if global_context and isinstance(global_context, tuple) and len(global_context) == 2:
            static_ctxt, dyn_ctxt = global_context
            static_ctxt = (static_ctxt or "").strip()
            dyn_ctxt = (dyn_ctxt or "").strip()
            if static_ctxt:
                parts.append(f"<STATIC CONTEXT>\n{static_ctxt}")
            if dyn_ctxt:
                parts.append(f"<DYNAMIC CONTEXT>\n{dyn_ctxt}")

        payload = getattr(argument.prop, "payload", None)
        if payload:
            parts.append(f"<ADDITIONAL CONTEXT>\n{payload}")

        processed = getattr(argument.prop, "processed_input", "")
        if processed:
            parts.append(str(processed))

        parts.append(
            "\n\nIMPORTANT: Return only the final answer text. Do not run commands. Do not describe steps."
        )

        argument.prop.prepared_input = "\n\n".join([p for p in parts if p])

    def forward(self, argument) -> Tuple[List[str], Dict[str, Any]]:
        prompt = argument.prop.prepared_input

        with tempfile.NamedTemporaryFile(mode="w+", suffix=".txt", delete=False) as last_msg:
            last_msg_path = last_msg.name

        last_metadata: Dict[str, Any] = {}
        last_error: str = ""
        fallback_enabled = bool(self.fallback_model)

        for attempt in range(self.max_retries):
            primary_model = self.model
            if not primary_model:
                break

            cmd: List[str] = ["codex", "exec"]
            if self.skip_git_repo_check:
                cmd.append("--skip-git-repo-check")
            cmd.extend(["--sandbox", self.sandbox])
            cmd.extend(["-m", primary_model])
            cmd.extend(["--output-last-message", last_msg_path])
            cmd.append("-")

            try:
                proc = subprocess.run(
                    cmd,
                    input=str(prompt),
                    text=True,
                    capture_output=True,
                    check=False,
                )
            except FileNotFoundError as e:
                raise RuntimeError("codex CLI not found on PATH") from e

            try:
                with open(last_msg_path, "r", encoding="utf-8", errors="replace") as f:
                    text_out = f.read().strip()
            except Exception:
                text_out = ""

            last_metadata = {
                "raw_output": {
                    "exit_code": proc.returncode,
                    "stderr": proc.stderr[-4000:] if proc.stderr else "",
                }
            }

            if proc.returncode == 0 or text_out:
                return [text_out], last_metadata

            last_error = last_metadata["raw_output"].get("stderr", "")
            if not self._is_backoff_error(last_error):
                break

            if fallback_enabled:
                cmd = ["codex", "exec"]
                if self.skip_git_repo_check:
                    cmd.append("--skip-git-repo-check")
                cmd.extend(["--sandbox", self.sandbox])
                cmd.extend(["-m", self.fallback_model])
                cmd.extend(["--output-last-message", last_msg_path])
                cmd.append("-")

                try:
                    proc = subprocess.run(
                        cmd,
                        input=str(prompt),
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                except FileNotFoundError as e:
                    raise RuntimeError("codex CLI not found on PATH") from e

                try:
                    with open(last_msg_path, "r", encoding="utf-8", errors="replace") as f:
                        text_out = f.read().strip()
                except Exception:
                    text_out = ""

                last_metadata = {
                    "raw_output": {
                        "exit_code": proc.returncode,
                        "stderr": proc.stderr[-4000:] if proc.stderr else "",
                    }
                }

                if proc.returncode == 0 or text_out:
                    return [text_out], last_metadata

                last_error = last_metadata["raw_output"].get("stderr", "")
                if self._is_unsupported_model(last_error):
                    fallback_enabled = False

            if attempt < self.max_retries - 1:
                time.sleep(self.backoff_base * (2 ** attempt))

        raise RuntimeError(
            f"codex exec failed after retries. stderr: {last_error}"
        )
