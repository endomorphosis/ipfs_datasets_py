"""Optional learned-guidance observations from the deterministic modal compiler.

The caller owns the live autoencoder and chooses whether to enable this path.
This module does not load weights, train, contact providers, or invoke Lake.
Its formulas are compiler outputs influenced by learned guidance, never an
independent learned decoder. Source-derived target distributions may also
condition guidance and are disclosed separately.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import inspect
import json
from pathlib import Path
import time
from typing import Any

SCHEMA = "legacy-autoencoder-guided-compiler/v1"
MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
MAX_GUIDANCE_BYTES = 2 * 1024 * 1024


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def _formal_outputs(document: dict[str, Any], *, origin: str,
                    target_conditioned: bool) -> list[dict[str, Any]]:
    """Retain the native AST verbatim; IDs/metadata can affect raw equality.

    ModalIR dataclasses provide serialization but no syntax validation API.
    These observations therefore explicitly leave syntax unchecked. Nothing
    here establishes semantic equivalence or selects a preferred producer.
    """
    if type(document) is not dict or type(document.get("formulas")) is not list:
        raise ValueError("guided codec returned no serializable modal formula collection")
    outputs = []
    for formula in document["formulas"]:
        if type(formula) is not dict or not isinstance(formula.get("operator"), Mapping):
            raise ValueError("guided codec returned a malformed modal formula payload")
        outputs.append({"family": formula["operator"].get("family"),
            "format": "modal-ir-formula/v1", "payload": formula,
            "origin": origin, "independent": False, "target_conditioned": target_conditioned,
            "syntax_status": "not_checked"})
    return outputs


def _codec():
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.logic.modal.codec import DeterministicModalLogicCodec, ModalLogicCodecConfig
    require_workspace_logic_tree()
    root = Path(__file__).resolve().parents[2]
    if root not in Path(inspect.getfile(DeterministicModalLogicCodec)).resolve().parents:
        raise RuntimeError("guided compiler imported outside the canonical tree")
    # The codec still attaches its native frame triples. Expensive FLogic
    # scoring is unnecessary for a candidate capture and confers no syntax
    # or proof authority. No external prover is requested.
    return DeterministicModalLogicCodec(ModalLogicCodecConfig(use_flogic=False))


class GuidedLegacyCompiler:
    """Keep one deterministic codec beside a caller-owned immutable model.

    Use this from the model-owning worker, after bridge evaluation and before
    clearing the model's per-sample target caches. Calls must be serialized by
    that owner; model guidance and codec internals use mutable caches.
    """

    def __init__(self, model: Any, *, top_k: int = 8,
                 model_identity: Mapping[str, Any] | None = None) -> None:
        if type(top_k) is not int or not 1 <= top_k <= 32:
            raise ValueError("guided compiler top_k must be an integer from 1 to 32")
        if not callable(getattr(model, "compiler_guidance_for_sample", None)):
            raise TypeError("caller-owned autoencoder must provide compiler guidance")
        self.model = model
        self.top_k = top_k
        self.model_identity = (json.loads(_json_bytes(dict(model_identity)))
                               if model_identity is not None else None)
        self.codec = None

    def observe(self, sample: Any) -> dict[str, Any]:
        """Return one observation or a bounded explicit failure for this span."""
        started = time.perf_counter()
        try:
            return self._observe(sample)
        except Exception as error:
            return {"schema": SCHEMA, "origin": "autoencoder_guided_compiler",
                "kind": "diagnostic_guided_conversion", "status": "error",
                "sample_id": getattr(sample, "sample_id", None),
                "independent": False, "source_derived": True,
                "learned_formula_generation": False, "target_conditioned": None,
                "use_sample_memory": False, "training_executed": False,
                "error_type": type(error).__name__,
                "comparison_scope": "exact_raw_ast_diagnostic",
                "direct_formal_outputs": [], "model_formal_outputs": [], "guided_formal_outputs": [], "formulas": [],
                "admitted": False, "formalized": False, "semantic_qualified": False,
                "syntax_status": "not_checked", "lake": {"status": "not_run", "admitted": False},
                "timings": {"elapsed_seconds": time.perf_counter() - started}}

    def _observe(self, sample: Any) -> dict[str, Any]:
        """Capture actual modal formulas without treating guidance as decoding.

        Oversized complete artifacts are reported with their hash and
        size; their content is never silently truncated.
        """
        started = time.perf_counter()
        text = getattr(sample, "text", None)
        sample_id = getattr(sample, "sample_id", None)
        if type(text) is not str or not text or len(text) > 16384:
            raise ValueError("guided compiler requires one bounded nonempty source span")
        if type(sample_id) is not str or not sample_id:
            raise ValueError("guided compiler requires an exact sample identity")
        guidance = self.model.compiler_guidance_for_sample(
            sample, use_sample_memory=False, include_causal_attribution=False,
            top_k=self.top_k,
        )
        if not isinstance(guidance, Mapping):
            raise TypeError("compiler guidance must be a mapping")
        if guidance.get("sample_id") != sample_id or guidance.get("sample_memory_used") is not False:
            raise ValueError("guidance must bind the sample without sample memory")
        guidance_bytes = _json_bytes(dict(guidance))
        target_conditioned = bool(guidance.get("legal_ir_target_view_distribution"))
        base = {
            "schema": SCHEMA, "origin": "autoencoder_guided_compiler",
            "kind": "diagnostic_guided_conversion", "sample_id": sample_id,
            "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "independent": False, "source_derived": True,
            "learned_formula_generation": False, "target_conditioned": target_conditioned,
            "target_conditioning_basis": "legal_ir_target_view_distribution_nonempty",
            "use_sample_memory": False, "training_executed": False,
            "admitted": False, "formalized": False, "semantic_qualified": False,
            "syntax_status": "not_checked", "lake": {"status": "not_run", "admitted": False},
            "configuration": {"top_k": self.top_k, "include_causal_attribution": False,
                              "evaluate_flogic": False, "evaluate_provers": False},
            "guidance_sha256": hashlib.sha256(guidance_bytes).hexdigest(),
            "guidance_bytes": len(guidance_bytes),
            "comparison_scope": "exact_raw_ast_diagnostic",
            "comparison_notes": "Verbatim modal AST equality includes provenance and metadata; not semantic equivalence.",
            "direct_origin": "deterministic_codec",
            "comparison_baseline": "same_codec_without_guidance",
        }
        guidance_seconds = time.perf_counter() - started
        if len(guidance_bytes) > MAX_GUIDANCE_BYTES:
            return {**base, "status": "deferred_guidance_size", "formulas": [],
                    "direct_formal_outputs": [], "model_formal_outputs": [], "guided_formal_outputs": [],
                    "timings": {"guidance_seconds": guidance_seconds,
                                "elapsed_seconds": time.perf_counter() - started}}
        if self.codec is None:
            self.codec = _codec()
        compiled_at = time.perf_counter()
        codec_arguments = dict(document_id=sample_id, citation=getattr(sample, "citation", None),
            source=getattr(sample, "source", "us_code"),
            source_embedding=sample.embedding_vector)
        direct_result = self.codec.encode(text, **codec_arguments, compiler_guidance=None)
        direct_compiler_seconds = time.perf_counter() - compiled_at
        guided_started = time.perf_counter()
        result = self.codec.encode(text, **codec_arguments, compiler_guidance=guidance)
        guided_compiler_seconds = time.perf_counter() - guided_started
        document = result.modal_ir.to_dict()
        document_bytes = _json_bytes(document)
        direct_document = direct_result.modal_ir.to_dict()
        direct_bytes = _json_bytes(direct_document)
        source_parser_document = sample.modal_ir.to_dict()
        source_parser_bytes = _json_bytes(source_parser_document)
        if type(document) is not dict or type(document.get("formulas")) is not list:
            raise ValueError("guided codec returned no serializable modal formula collection")
        if type(direct_document) is not dict or type(direct_document.get("formulas")) is not list:
            raise ValueError("unguided codec returned no serializable modal formula collection")
        captured = len(document_bytes) + len(direct_bytes) + len(source_parser_bytes) <= MAX_DOCUMENT_BYTES
        # Do not infer TDFOL/DCEC coverage from bridge names or guidance
        # distributions. Family names come solely from emitted operators.
        formulas = _formal_outputs(document, origin="autoencoder_guided_compiler",
                                   target_conditioned=target_conditioned) if captured else []
        direct_formulas = _formal_outputs(direct_document, origin="deterministic_codec",
                                          target_conditioned=False) if captured else []
        provenance = {"source_text_sha256": base["source_sha256"], "complete": captured,
            "syntax_status": "not_checked", "comparison_scope": "exact_raw_ast_diagnostic",
            "completeness_scope": "emitted_native_formula_collection",
            "independent": False, "model_identity": self.model_identity,
            "checkpoint_sha256": (self.model_identity.get("sha256")
                                  if self.model_identity is not None else None)}
        answer = {**base, "status": "captured" if captured else "deferred_document_size",
            "guidance": json.loads(guidance_bytes),
            "document_sha256": hashlib.sha256(document_bytes).hexdigest(),
            "document_bytes": len(document_bytes), "formula_count": len(document["formulas"]),
            "direct_document_sha256": hashlib.sha256(direct_bytes).hexdigest(),
            "direct_document_bytes": len(direct_bytes),
            "source_parser_document_sha256": hashlib.sha256(source_parser_bytes).hexdigest(),
            "source_parser_document_bytes": len(source_parser_bytes),
            "direct_formula_count": len(direct_document["formulas"]),
            "direct_formal_outputs": direct_formulas, "guided_formal_outputs": formulas,
            "model_formal_outputs": formulas,
            "direct_formal_output_provenance": {**provenance, "origin": "deterministic_codec",
                "target_conditioned": False, "model_identity": None, "checkpoint_sha256": None},
            "model_formal_output_provenance": {**provenance, "origin": "autoencoder_guided_compiler",
                "target_conditioned": target_conditioned},
            "formulas": formulas, "decompiled_text": result.decoded_text if captured else None,
            "direct_decompiled_text": direct_result.decoded_text if captured else None,
            "timings": {"guidance_seconds": guidance_seconds,
                        "direct_compiler_seconds": direct_compiler_seconds,
                        "guided_compiler_seconds": guided_compiler_seconds,
                        "compiler_seconds": time.perf_counter() - compiled_at,
                        "elapsed_seconds": time.perf_counter() - started}}
        if captured:
            answer["document"] = document
            answer["direct_document"] = direct_document
            answer["source_parser_document"] = source_parser_document
        return json.loads(_json_bytes(answer))


__all__ = ["GuidedLegacyCompiler", "SCHEMA"]
