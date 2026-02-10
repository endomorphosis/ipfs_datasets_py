"""Router-backed implementation of the `LLMInterface`.

This module bridges the lightweight `ipfs_datasets_py.llm_router` (string-in/string-out)
with the richer GraphRAG-facing `LLMInterface` API (metadata, structured output,
embeddings, token counting).

Design goals:
- Lazy imports: keep import-time side effects minimal.
- Keep defaults conservative: if the router isn't usable, callers can still use
  `MockLLMInterface`.
- Provide a best-effort `generate_with_structured_output` with JSON extraction,
  schema validation, and repair prompts.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .llm_interface import LLMConfig, LLMInterface

# Optional numpy with graceful fallback (mirrors llm_interface.py pattern)
try:
    import numpy as np  # type: ignore

    HAVE_NUMPY = True
except Exception:  # pragma: no cover
    HAVE_NUMPY = False

    class _MockNumpy:  # minimal subset
        @staticmethod
        def array(x):
            return list(x) if hasattr(x, "__iter__") else [x]

        @staticmethod
        def vstack(xs):
            out: list = []
            for x in xs:
                out.extend(list(x))
            return out

        class random:  # noqa: N801
            class RandomState:
                def __init__(self, seed: int):
                    self._seed = seed

                def rand(self, n: int):
                    # Deterministic pseudo-random-ish numbers without importing random.
                    # Not high quality; only for fallback behavior.
                    vals = []
                    x = (self._seed % 2147483647) or 1
                    for _ in range(n):
                        x = (x * 48271) % 2147483647
                        vals.append((x % 10000) / 10000.0)
                    return vals

        @staticmethod
        def linalg_norm(x):
            # very small subset
            s = 0.0
            for v in x:
                try:
                    s += float(v) * float(v)
                except Exception:
                    pass
            return s ** 0.5

    np = _MockNumpy()  # type: ignore


try:
    from ..utils.embedding_adapter import embed_text as adapter_embed_text
    from ..utils.embedding_adapter import embed_texts as adapter_embed_texts
except Exception:  # pragma: no cover
    adapter_embed_text = None
    adapter_embed_texts = None


_JSON_BLOCK_RE = re.compile(r"```json\s*([\s\S]*?)\s*```", re.IGNORECASE)
_CODE_BLOCK_RE = re.compile(r"```\s*([\s\S]*?)\s*```", re.IGNORECASE)


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _extract_json(text: str) -> Any:
    """Best-effort extraction of a JSON object/array from model output."""

    if not isinstance(text, str):
        raise ValueError("Expected string output")

    m = _JSON_BLOCK_RE.search(text)
    if m:
        return json.loads(m.group(1))

    # Fallback: any fenced code block
    m = _CODE_BLOCK_RE.search(text)
    if m:
        candidate = m.group(1).strip()
        return json.loads(candidate)

    # Fallback: attempt to find the outermost JSON object/array.
    s = text.strip()
    # Find first '{' or '[' and last matching '}' or ']'.
    start_obj = s.find("{")
    start_arr = s.find("[")
    if start_obj == -1 and start_arr == -1:
        return json.loads(s)

    if start_obj == -1:
        start = start_arr
        end = s.rfind("]")
    elif start_arr == -1:
        start = start_obj
        end = s.rfind("}")
    else:
        start = min(start_obj, start_arr)
        end = max(s.rfind("}"), s.rfind("]"))

    if end <= start:
        return json.loads(s)

    candidate = s[start : end + 1]
    return json.loads(candidate)


def _jsonschema_validate(data: Any, schema: Dict[str, Any]) -> List[str]:
    """Return a list of validation errors (empty means valid)."""

    try:
        import jsonschema  # type: ignore

        errors = list(jsonschema.Draft7Validator(schema).iter_errors(data))
        return [str(e) for e in errors]
    except Exception:
        # If jsonschema isn't present/working, skip strict validation.
        return []


@dataclass
class RoutedLLMOptions:
    provider: Optional[str] = None
    deps: Any | None = None


class RoutedLLMInterface(LLMInterface):
    """`LLMInterface` backed by `ipfs_datasets_py.llm_router`."""

    def __init__(
        self,
        config: Optional[LLMConfig] = None,
        *,
        provider: Optional[str] = None,
        deps: Any | None = None,
    ):
        super().__init__(config or LLMConfig())
        self._provider = provider
        self._deps = deps

        self._word_pattern = re.compile(r"\b\w+\b")
        self._use_embedding_adapter = _truthy(os.getenv("IPFS_DATASETS_PY_USE_EMBEDDING_ADAPTER"))

    def generate(self, prompt: str, **kwargs: Any) -> Dict[str, Any]:
        from ipfs_datasets_py import llm_router

        start = time.time()

        model_name = kwargs.pop("model_name", None)
        if model_name is None:
            # Respect config.model_name unless it's the mock default.
            cfg = (self.config.model_name or "").strip()
            if cfg and not cfg.startswith("mock-"):
                model_name = cfg

        text = llm_router.generate_text(
            str(prompt),
            model_name=model_name,
            provider=self._provider,
            deps=self._deps,
            **kwargs,
        )

        elapsed = time.time() - start
        return {
            "text": str(text),
            "usage": {
                "prompt_tokens": self.count_tokens(str(prompt)),
                "completion_tokens": self.count_tokens(str(text)),
                "total_tokens": self.count_tokens(str(prompt)) + self.count_tokens(str(text)),
            },
            "model": (model_name or self.config.model_name or "").strip(),
            "provider": (self._provider or os.getenv("IPFS_DATASETS_PY_LLM_PROVIDER") or "auto").strip(),
            "id": f"router-{uuid.uuid4()}",
            "created": int(time.time()),
            "latency": elapsed,
        }

    def generate_with_structured_output(
        self,
        prompt: str,
        output_schema: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        schema_str = json.dumps(output_schema, indent=2, ensure_ascii=False)

        base_prompt = (
            "Return ONLY valid JSON that conforms to this JSON Schema. "
            "Do not include markdown fences or any other text.\n\n"
            f"JSON SCHEMA:\n{schema_str}\n\n"
            f"PROMPT:\n{prompt}\n\n"
            "JSON:"  # keep it anchored
        )

        # First attempt
        response = self.generate(base_prompt, **kwargs)
        text = str(response.get("text", ""))

        last_errors: List[str] = []
        last_data: Any = None

        for attempt in range(int(kwargs.pop("max_repair_attempts", 2)) + 1):
            try:
                data = _extract_json(text)
                last_data = data
                errors = _jsonschema_validate(data, output_schema)
                if errors:
                    last_errors = errors
                    raise ValueError("Schema validation failed")

                if not isinstance(data, dict):
                    # GraphRAG expects dict outputs.
                    raise ValueError("Structured output must be a JSON object")

                return data
            except Exception:
                if attempt >= 2:
                    break

                # Repair prompt with concrete errors.
                err_text = "\n".join(last_errors) if last_errors else "Invalid JSON or schema mismatch"
                repair_prompt = (
                    "Fix the following output so it becomes ONLY valid JSON matching the schema. "
                    "Return ONLY the fixed JSON.\n\n"
                    f"JSON SCHEMA:\n{schema_str}\n\n"
                    f"ERRORS:\n{err_text}\n\n"
                    f"CURRENT OUTPUT:\n{text}\n\n"
                    "FIXED JSON:"  # anchor
                )
                response = self.generate(repair_prompt, **kwargs)
                text = str(response.get("text", ""))

        raise ValueError(
            "Failed to generate structured output as valid JSON for the provided schema."
        )

    def embed_text(self, text: str):
        if self._use_embedding_adapter and adapter_embed_text is not None:
            try:
                emb = adapter_embed_text(text)
                return np.array(emb)
            except Exception:
                pass

        # Deterministic fallback embeddings
        dims = int(getattr(self.config, "embedding_dimensions", 768) or 768)
        seed = hash(text) % 10000
        rs = np.random.RandomState(int(seed))
        vec = rs.rand(dims)
        try:
            norm = float(np.linalg.norm(vec))
            if norm:
                return vec / norm
        except Exception:
            pass
        return vec

    def embed_batch(self, texts: List[str]):
        if self._use_embedding_adapter and adapter_embed_texts is not None:
            try:
                embs = adapter_embed_texts(texts)
                return np.array(embs)
            except Exception:
                pass

        embs = [self.embed_text(t) for t in texts]
        try:
            return np.vstack(embs)
        except Exception:
            return np.array(embs)

    def tokenize(self, text: str) -> List[int]:
        # Minimal tokenization: stable word hashing.
        words = self._word_pattern.findall(str(text).lower())
        return [abs(hash(w)) % 100000 for w in words]

    def count_tokens(self, text: str) -> int:
        # Rough estimate: 1 token ~= 0.75 words
        words = self._word_pattern.findall(str(text))
        return max(1, int(len(words) * 1.2)) if words else 0
