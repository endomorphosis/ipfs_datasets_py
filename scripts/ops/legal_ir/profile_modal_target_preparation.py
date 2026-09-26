#!/usr/bin/env python3
"""Extend the frozen cold-target profiler with optional --modal-detail phases.

Without --modal-detail the original phase boundaries remain unchanged. With
it, coarse modal codec calls and document-level serialization are observed.
The codec's original lazy import/constructor remains inside adapter._codec;
codec hooks are installed only after that first original call returns. No
codec, encoder, ontology, graph, or target is reused across samples.

This is diagnostic instrumentation, including method replacement in memory.
It cannot establish native qualification or historical speed parity. Target
timeouts and partial failure reports retain the frozen base harness policy.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import functools
from pathlib import Path
import sys
import time

import profile_cold_target_preparation as base


BASE_SHA = "bc3e19730caa378d8c5ffe375a7170a04143c485d4d8bcaca983f9160fc50bc1"
DETAIL_PHASES = (
    "modal_codec_acquire", "modal_codec_encode", "modal_compile", "modal_attach_frames",
    "modal_clause_enrichment", "modal_spacy_encode", "modal_embedding_decode", "modal_frame_rank",
    "modal_flogic_triples", "modal_flogic_ontology", "modal_graph_projection", "modal_ontology_export",
    "modal_document_decode", "modal_frame_audit", "modal_structural_embedding", "modal_flogic_evaluate",
    "modal_ir_envelope", "modal_document_to_dict", "modal_document_hash", "modal_graph_to_dict",
)


class ModalPhaseObserver(base.PhaseObserver):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.modal_hook_bindings = []
        self.modal_codec_hooks_installed = False
        self.modal_hooks_restored = False
        self.modal_hook_install_seconds = 0.0

    def to_dict(self):
        return {**super().to_dict(), "modal_detail": {
            "hook_bindings": self.modal_hook_bindings,
            "codec_hooks_installed": self.modal_codec_hooks_installed,
            "hooks_restored": self.modal_hooks_restored,
            "hook_install_seconds": self.modal_hook_install_seconds,
            "install_scope": "after the first unchanged adapter._codec call; outside modal_codec_acquire timing",
            "serialization_scope": "document/graph methods only, no per-formula/node/triple hooks",
            "native_method_identity_preserved": False,
            "identity_guard_review": "LegalIRTrainingTarget.to_dict guard is untouched; no ModalIRDocument method identity guard found in inspected bridge/codec/snapshot paths",
            "lifecycle": "original per-sample adapter/codec/encoder/ontology construction retained",
        }}


@contextmanager
def modal_instrument(observer):
    # Importing this small adapter module does not import its lazy modal codec.
    # The codec (and optional spaCy runtime) still loads in the original _codec.
    from ipfs_datasets_py.logic.bridge import modal_frame_logic

    replacements = []

    def wrap(owner, name, phase, detail=None):
        original = getattr(owner, name)

        @functools.wraps(original)
        def wrapped(*args, **kwargs):
            label = detail(args, kwargs) if detail else name
            with observer.phase(phase, label):
                return original(*args, **kwargs)

        replacements.append((owner, name, original))
        setattr(owner, name, wrapped)
        observer.modal_hook_bindings.append({
            "phase": phase, "callable": original.__module__ + "." + original.__qualname__,
        })

    def install_codec_hooks():
        if observer.modal_codec_hooks_installed:
            return
        started = time.perf_counter()
        codec = sys.modules["ipfs_datasets_py.logic.modal.codec"]
        kg_bridge = sys.modules["ipfs_datasets_py.logic.modal.kg_bridge"]
        bindings = [
            (codec.DeterministicModalLogicCodec, "encode", "modal_codec_encode"),
            (codec.DeterministicModalLogicCodec, "_compile_modal_ir", "modal_compile"),
            (codec.DeterministicModalLogicCodec, "_attach_frame_logic", "modal_attach_frames"),
            (codec.DeterministicModalLogicCodec, "_evaluate_flogic", "modal_flogic_evaluate"),
            (codec.SpaCyLegalEncoder, "encode", "modal_spacy_encode"),
            (codec.SpaCyModalDecoder, "decode_embedding", "modal_embedding_decode"),
            (codec.BM25FrameSelector, "rank", "modal_frame_rank"),
            (codec, "_enrich_modal_ir_formula_clauses", "modal_clause_enrichment"),
            (codec, "modal_ir_to_flogic_triples", "modal_flogic_triples"),
            (codec, "flogic_triples_to_ontology", "modal_flogic_ontology"),
            (codec, "flogic_triples_to_graph_data", "modal_graph_projection"),
            (codec, "flogic_ontology_to_dict", "modal_ontology_export"),
            (codec, "decode_modal_ir_document", "modal_document_decode"),
            (codec, "_frame_ontology_audit_feature_keys", "modal_frame_audit"),
            (codec, "_frame_ontology_audit_terms", "modal_frame_audit"),
            (codec, "_frame_ontology_audit_triples", "modal_frame_audit"),
            (codec, "_decoded_structural_feature_embedding", "modal_structural_embedding"),
            (codec.ModalIRDocument, "to_dict", "modal_document_to_dict"),
            (codec.ModalIRDocument, "canonical_hash", "modal_document_hash"),
            (kg_bridge.GraphData, "to_dict", "modal_graph_to_dict"),
        ]
        # Fail clearly if a source update removed a boundary. No alternative
        # implementation or broad recursive profiler is silently substituted.
        for owner, name, _ in bindings:
            if not callable(getattr(owner, name)):
                raise TypeError("modal profile boundary is not callable: " + name)
        for owner, name, phase in bindings:
            wrap(owner, name, phase)
        observer.modal_codec_hooks_installed = True
        observer.modal_hook_install_seconds += time.perf_counter() - started

    adapter = modal_frame_logic.ModalFrameLogicBridgeAdapter
    original_acquire = adapter._codec

    @functools.wraps(original_acquire)
    def acquire(*args, **kwargs):
        with observer.phase("modal_codec_acquire", "_codec"):
            codec = original_acquire(*args, **kwargs)
        install_codec_hooks()
        return codec

    try:
        replacements.append((adapter, "_codec", original_acquire))
        adapter._codec = acquire
        observer.modal_hook_bindings.append({
            "phase": "modal_codec_acquire",
            "callable": original_acquire.__module__ + "." + original_acquire.__qualname__,
        })
        wrap(adapter, "_ir_document_from_codec_result", "modal_ir_envelope")
        yield
    finally:
        for owner, name, original in reversed(replacements):
            setattr(owner, name, original)
        observer.modal_hooks_restored = True


@contextmanager
def extension(enabled):
    """Restore all base-harness bindings, including on a rejected diagnostic."""
    if base.sha(base.__file__) != BASE_SHA:
        raise ValueError("frozen coarse profile harness changed")
    script_sha = base.sha(__file__)
    original_run, original_instrument = base.run, base.instrument
    original_phases, original_observer = base.PHASES, base.PhaseObserver

    @contextmanager
    def detailed_instrument(observer):
        with original_instrument(observer), modal_instrument(observer):
            yield

    def run(args, result):
        result["schema"] = "modal-detail-target-preparation-phase-profile-v1"
        result["modal_detail_enabled"] = enabled
        result["profile_extension"] = {
            "path": str(Path(__file__).resolve()), "sha256": script_sha,
            "base_harness_path": str(Path(base.__file__).resolve()), "base_harness_sha256": BASE_SHA,
            "coarse_phase_default_unchanged": not enabled,
            "adapter_module_import_scope": "adapter module imported before observation; lazy codec import and construction remain timed",
            "additional_phase_names": list(DETAIL_PHASES) if enabled else [],
        }
        try:
            original_run(args, result)
            if enabled:
                detail = result["observations"]["modal_detail"]
                if not detail["codec_hooks_installed"] or not detail["hooks_restored"]:
                    raise ValueError("modal detail instrumentation did not install/restore all boundaries")
            if base.sha(__file__) != script_sha:
                raise ValueError("modal profile extension changed during diagnostic")
        finally:
            result["profile_extension"]["source_unchanged"] = base.sha(__file__) == script_sha

    try:
        base.run = run
        if enabled:
            base.PHASES = (*original_phases, *DETAIL_PHASES)
            base.PhaseObserver = ModalPhaseObserver
            base.instrument = detailed_instrument
        yield
    finally:
        base.run, base.instrument = original_run, original_instrument
        base.PHASES, base.PhaseObserver = original_phases, original_observer


def main():
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--modal-detail", action="store_true")
    extra, remaining = parser.parse_known_args()
    original_argv = sys.argv
    try:
        if "--help" in remaining or "-h" in remaining:
            print(__doc__ + "\nThe remaining arguments are provided by the frozen base harness:\n")
        sys.argv = [sys.argv[0], *remaining]
        with extension(extra.modal_detail):
            return base.main()
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    raise SystemExit(main())
