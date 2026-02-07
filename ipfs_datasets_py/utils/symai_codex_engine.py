import json
import os
import time
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from symai.backend.base import Engine
from symai.backend.settings import SYMAI_CONFIG


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _looks_like_json_contract(prompt: str) -> bool:
    if not prompt:
        return False
    lowered = prompt.lower()
    if "return a json object" in lowered:
        return True
    # Heuristics for our contracted logic converters.
    if '"fol_formula"' in prompt or "fol_formula" in lowered:
        return True
    if "<output_data_model>" in lowered and "[[schema]]" in lowered:
        return True
    return False


def _dry_run_contract_json(prompt: str) -> str:
    # Minimal FOLOutput-like payload used by our tests/contracts.
    # If the contract expects different keys, this is still structured JSON and
    # tends to stop SyMAI from repeatedly asking for "valid JSON".
    base: Dict[str, Any] = {
        "fol_formula": "∀x (Student(x) → Studies(x))" if "student" in prompt.lower() else "∀x (Cat(x) → Animal(x))",
        "confidence": 0.9,
        "logical_components": {
            "quantifiers": ["∀"],
            "predicates": ["Student", "Studies"],
        },
        "reasoning_steps": ["dry-run"],
        "validation_results": {"syntax": "skipped"},
        "warnings": ["dry_run"],
        "metadata": {"backend": "dry_run"},
    }
    return json.dumps(base, ensure_ascii=False)


def _looks_like_ok_only_prompt(prompt: str) -> bool:
    if not prompt:
        return False
    lowered = prompt.strip().lower()
    if lowered == "ok":
        return True
    if "ok only" in lowered:
        return True
    if "reply with ok" in lowered:
        return True
    return False


class CodexExecNeurosymbolicEngine(Engine):
    """A minimal `symai` neurosymbolic engine routed via `ipfs_datasets_py.llm_router`.

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

        self.fallback_model = os.environ.get("IPFS_DATASETS_PY_CODEX_FALLBACK_MODEL", "")
        self.max_retries = int(os.environ.get("IPFS_DATASETS_PY_CODEX_MAX_RETRIES", "3"))
        self.backoff_base = float(os.environ.get("IPFS_DATASETS_PY_CODEX_BACKOFF_BASE", "1.0"))

        # Allow forcing the llm_router provider; default to codex_cli when this engine is active.
        self.provider = (os.environ.get("IPFS_DATASETS_PY_LLM_PROVIDER") or "").strip() or "codex_cli"

    def _call_llm_router(self, prompt: str, *, model_name: Optional[str]) -> str:
        # Import lazily to avoid import-time side effects.
        from ipfs_datasets_py import llm_router

        return llm_router.generate_text(
            prompt,
            model_name=model_name,
            provider=self.provider or None,
        )

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

        # Benchmark-stability mode: avoid external calls and long SyMAI validation loops.
        if _truthy(os.environ.get("IPFS_DATASETS_PY_SYMAI_ROUTER_DRY_RUN")):
            prompt_text = str(prompt)
            if _looks_like_ok_only_prompt(prompt_text):
                return ["OK"], {"backend": "dry_run"}

            # In dry-run mode, default to valid JSON unless the prompt explicitly
            # requests a plain-text response. This prevents SyMAI's contract
            # validation strategy from entering long retry loops.
            if _looks_like_json_contract(prompt_text):
                return [_dry_run_contract_json(prompt_text)], {"backend": "dry_run", "format": "json"}
            return [_dry_run_contract_json(prompt_text)], {"backend": "dry_run", "format": "json", "fallback": True}

        last_error: str = ""
        last_metadata: Dict[str, Any] = {}

        primary_model = getattr(self, "model", "") or None
        fallback_model = (getattr(self, "fallback_model", "") or "").strip() or None

        for attempt in range(max(1, int(getattr(self, "max_retries", 1)))):
            try:
                text_out = self._call_llm_router(prompt, model_name=primary_model)
                return [str(text_out).strip()], {
                    "backend": "llm_router",
                    "provider": self.provider,
                    "model": primary_model,
                }
            except Exception as exc:
                last_error = str(exc)
                last_metadata = {
                    "backend": "llm_router",
                    "provider": self.provider,
                    "model": primary_model,
                    "error": last_error,
                }

                # If the failure looks like a rate-limit/backoff error, retry.
                if not self._is_backoff_error(last_error):
                    break

                # Optional fallback model path.
                if fallback_model:
                    try:
                        text_out = self._call_llm_router(prompt, model_name=fallback_model)
                        return [str(text_out).strip()], {
                            "backend": "llm_router",
                            "provider": self.provider,
                            "model": fallback_model,
                            "fallback": True,
                        }
                    except Exception as fallback_exc:
                        last_error = str(fallback_exc)
                        last_metadata = {
                            "backend": "llm_router",
                            "provider": self.provider,
                            "model": fallback_model,
                            "fallback": True,
                            "error": last_error,
                        }

                if attempt < self.max_retries - 1:
                    time.sleep(float(getattr(self, "backoff_base", 1.0)) * (2**attempt))

        raise RuntimeError(f"llm_router generation failed after retries: {last_error}")
