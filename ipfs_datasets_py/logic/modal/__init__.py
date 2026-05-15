"""Deterministic modal logic encoder, IR, decoder, and frame-logic helpers."""

from __future__ import annotations

from .compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilationResult,
    ModalCompilerConfig,
)
from .codec import (
    DeterministicModalLogicCodec,
    ModalLogicCodecConfig,
    ModalLogicCodecResult,
    decode_modal_ir_text,
    modal_ir_to_flogic_triples,
    target_family_distribution_for_modal_ir,
    target_family_for_modal_ir,
)
from .decompiler import (
    DecodedModalPhrase,
    DecodedModalText,
    decode_modal_ir_document,
    decoded_modal_phrase_slot_text_map,
    modal_formula_to_text,
    modal_text_token_similarity,
)
from .synthesis import (
    ModalProgramSynthesisHint,
    synthesis_hints_from_autoencoder_introspection,
    synthesis_hints_from_autoencoder_introspections,
)

__all__ = [
    "DecodedModalPhrase",
    "DecodedModalText",
    "DeterministicModalCompiler",
    "DeterministicModalLogicCodec",
    "ModalCompilationAmbiguity",
    "ModalCompilationResult",
    "ModalCompilerConfig",
    "ModalLogicCodecConfig",
    "ModalLogicCodecResult",
    "ModalProgramSynthesisHint",
    "decode_modal_ir_document",
    "decode_modal_ir_text",
    "decoded_modal_phrase_slot_text_map",
    "modal_formula_to_text",
    "modal_text_token_similarity",
    "modal_ir_to_flogic_triples",
    "synthesis_hints_from_autoencoder_introspection",
    "synthesis_hints_from_autoencoder_introspections",
    "target_family_distribution_for_modal_ir",
    "target_family_for_modal_ir",
]
