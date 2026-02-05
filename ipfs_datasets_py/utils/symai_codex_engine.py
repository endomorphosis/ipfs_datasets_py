import os
import subprocess
import tempfile
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

        # Safety defaults for agentic behavior.
        self.sandbox = os.environ.get("IPFS_DATASETS_PY_CODEX_SANDBOX", "read-only")
        self.skip_git_repo_check = True

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

        cmd: List[str] = ["codex", "exec"]
        if self.skip_git_repo_check:
            cmd.append("--skip-git-repo-check")
        cmd.extend(["--sandbox", self.sandbox])
        if self.model:
            cmd.extend(["-m", self.model])
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

        metadata: Dict[str, Any] = {
            "raw_output": {
                "exit_code": proc.returncode,
                "stderr": proc.stderr[-4000:] if proc.stderr else "",
            }
        }

        if proc.returncode != 0 and not text_out:
            raise RuntimeError(
                f"codex exec failed (exit {proc.returncode}). stderr: {metadata['raw_output']['stderr']}"
            )

        return [text_out], metadata
