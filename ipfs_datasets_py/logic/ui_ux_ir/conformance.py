"""Cross-language UI/UX IR conformance harness (UIR-062).

Loads golden vectors, verifies Python decode/canonicalize parity, and exposes
a language-neutral report structure for TypeScript consumers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from .canonicalize import canonicalize_ui_ir, ui_ir_sha256
from .decoder import UIIRDecodeError, decode_ui_ir
from .schema import UIIRValidationError

UIIR_CROSS_LANGUAGE_PARITY_INTERFACE: Final = "UIIRCrossLanguageParity@1"
CONFORMANCE_SCHEMA_VERSION: Final = "ui-ux-ir-conformance/v1"

DEFAULT_GOLDEN_RELATIVE: Final = Path("tests/fixtures/ui_ux_ir/v1/golden_vectors.json")


@dataclass(frozen=True, slots=True)
class VectorResult:
    vector_id: str
    kind: str
    passed: bool
    detail: str = ""
    canonical_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_sha256": self.canonical_sha256,
            "detail": self.detail,
            "kind": self.kind,
            "passed": self.passed,
            "vector_id": self.vector_id,
        }


@dataclass(frozen=True, slots=True)
class ConformanceReport:
    passed: bool
    results: tuple[VectorResult, ...]
    interface: str = UIIR_CROSS_LANGUAGE_PARITY_INTERFACE
    schema_version: str = CONFORMANCE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface": self.interface,
            "passed": self.passed,
            "results": [r.to_dict() for r in self.results],
            "schema_version": self.schema_version,
        }


def load_golden_vectors(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "vectors" not in data:
        raise UIIRValidationError("golden vectors must be an object with 'vectors'")
    return data


def evaluate_vector(vector: Mapping[str, Any]) -> VectorResult:
    vid = str(vector.get("id") or "")
    kind = str(vector.get("kind") or "")
    if not vid or not kind:
        return VectorResult(vid or "?", kind or "?", False, "missing id/kind")

    if kind == "valid_document":
        document = vector.get("document")
        if not isinstance(document, Mapping):
            return VectorResult(vid, kind, False, "document missing")
        try:
            decoded = decode_ui_ir(document)
            digest = ui_ir_sha256(decoded)
            canon = canonicalize_ui_ir(decoded)
        except (UIIRDecodeError, UIIRValidationError) as exc:
            return VectorResult(vid, kind, False, f"decode/canonicalize failed: {exc}")
        expected = str(vector.get("canonical_sha256") or "")
        if expected and digest != expected:
            return VectorResult(
                vid,
                kind,
                False,
                f"digest mismatch expected={expected} actual={digest}",
                canonical_sha256=digest,
            )
        expected_len = vector.get("canonical_utf8_length")
        if expected_len is not None and int(expected_len) != len(canon):
            return VectorResult(
                vid,
                kind,
                False,
                f"canonical length mismatch expected={expected_len} actual={len(canon)}",
                canonical_sha256=digest,
            )
        return VectorResult(vid, kind, True, "ok", canonical_sha256=digest)

    if kind == "invalid_document":
        document = vector.get("document")
        if not isinstance(document, Mapping):
            return VectorResult(vid, kind, False, "document missing")
        try:
            decode_ui_ir(document)
            return VectorResult(vid, kind, False, "expected decode failure")
        except (UIIRDecodeError, UIIRValidationError):
            return VectorResult(vid, kind, True, "failed closed as expected")

    if kind == "decision":
        payload = vector.get("payload") or {}
        semantic = vector.get("semantic") or {}
        if payload.get("can_execute") is True and payload.get("outcome") != "allow":
            return VectorResult(vid, kind, False, "non-allow cannot set can_execute")
        if semantic.get("can_execute") is False and payload.get("can_execute") is True:
            return VectorResult(vid, kind, False, "semantic can_execute mismatch")
        if "outcome" in semantic and payload.get("outcome") != semantic.get("outcome"):
            return VectorResult(vid, kind, False, "outcome mismatch")
        return VectorResult(vid, kind, True, "decision vector ok")

    if kind == "receipt":
        payload = vector.get("payload") or {}
        semantic = vector.get("semantic") or {}
        if semantic.get("has_invocation") is False and payload.get("has_invocation") is True:
            return VectorResult(vid, kind, False, "receipt must not claim invocation")
        if "outcome" in semantic and payload.get("outcome") != semantic.get("outcome"):
            return VectorResult(vid, kind, False, "receipt outcome mismatch")
        return VectorResult(vid, kind, True, "receipt vector ok")

    return VectorResult(vid, kind, False, f"unknown vector kind {kind!r}")


def run_conformance(path: str | Path) -> ConformanceReport:
    data = load_golden_vectors(path)
    results = tuple(evaluate_vector(v) for v in data.get("vectors", []))
    return ConformanceReport(passed=all(r.passed for r in results), results=results)


def default_golden_path(repo_root: str | Path | None = None) -> Path:
    if repo_root is None:
        # external/ipfs_datasets root: .../ipfs_datasets_py/logic/ui_ux_ir/conformance.py
        # -> parents[3] is package root when installed as source tree.
        here = Path(__file__).resolve()
        # .../ipfs_datasets_py/logic/ui_ux_ir/conformance.py -> 4 parents to package root
        candidate = here.parents[3] / DEFAULT_GOLDEN_RELATIVE
        if candidate.is_file():
            return candidate
        return Path(DEFAULT_GOLDEN_RELATIVE)
    return Path(repo_root) / DEFAULT_GOLDEN_RELATIVE
