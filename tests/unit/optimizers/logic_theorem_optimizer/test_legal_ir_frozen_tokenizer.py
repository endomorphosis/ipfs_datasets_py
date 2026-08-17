"""Frozen LegalIR tokenizer and token-class tests for PGIR-030."""

from __future__ import annotations

import hashlib
import json

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_grammar_decoder import (
    LEGAL_IR_TOKEN_CLASSES,
    FrozenVocabularyMutationError,
    LegalIRFrozenTokenizer,
    LegalIRGrammarDecoder,
    UnknownFrozenTokenError,
)


def _deontic_ir() -> dict:
    return {
        "family": "deontic",
        "rules": [
            {
                "modality": "obligation",
                "subject": "agency",
                "action": "provide_notice",
            }
        ],
    }


def test_canonical_tokenizer_is_frozen_and_content_addressed() -> None:
    first = LegalIRFrozenTokenizer.canonical()
    second = LegalIRFrozenTokenizer.canonical()

    assert first.frozen is True
    assert first.vocabulary_cid == second.vocabulary_cid
    assert first.vocabulary_sha256.startswith("sha256:")
    assert first.to_dict()["unknown_token_behavior"] == "fail_closed"
    assert first.to_dict()["mutation_policy"] == "supersede_never_overwrite"
    assert tuple(first.to_dict()["token_classes"]) == LEGAL_IR_TOKEN_CLASSES


def test_canonical_vocabulary_cid_matches_manifest_digest() -> None:
    tokenizer = LegalIRFrozenTokenizer.canonical()
    digest = hashlib.sha256(
        json.dumps(
            tokenizer.vocabulary_manifest(),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    assert tokenizer.vocabulary_cid == f"sha256:{digest}"
    assert tokenizer.vocabulary_cid == (
        "sha256:8782ea363f422557c7a1f62442fe376fb6586f90a679bebb4ba60824de425c1b"
    )
    assert tokenizer.vocabulary_size == 143


def test_source_surface_encoding_never_contains_raw_source() -> None:
    tokenizer = LegalIRFrozenTokenizer.canonical()
    source = "The agency shall provide notice before the hearing and preserve the record."
    surface = tokenizer.encode_source_surface(source)
    pieces = tokenizer.decode_ids(surface.token_ids)

    assert source not in pieces
    assert "shall" not in pieces
    assert surface.source_surface_separated is True
    assert surface.source_surface_token_count >= 1
    assert all(piece in {"<bos>", "<eos>", "<source_ref>"} for piece in pieces)


def test_grammar_decoder_encodes_validated_structured_output() -> None:
    decoder = LegalIRGrammarDecoder()
    encoding = decoder.encode_structured_output(_deontic_ir(), family="deontic")

    assert encoding.accepted is True
    assert encoding.family == "deontic"
    assert encoding.token_class_histogram()["operator"] >= 1
    assert decoder.frozen_tokenizer().vocabulary_cid == encoding.vocabulary_cid


def test_unknown_closed_operator_fails_closed() -> None:
    tokenizer = LegalIRFrozenTokenizer.canonical()
    with pytest.raises(UnknownFrozenTokenError):
        tokenizer.encode_canonical(
            {
                "family": "tdfol",
                "formulas": [{"quantifier": "most", "predicate": "Holds", "arguments": ["x"]}],
            }
        )


def test_frozen_vocabulary_rejects_in_place_growth() -> None:
    tokenizer = LegalIRFrozenTokenizer.canonical()
    with pytest.raises(FrozenVocabularyMutationError):
        tokenizer.add_token("brand_new_family", "family")


def test_canonical_path_rejects_source_surface_tokens() -> None:
    tokenizer = LegalIRFrozenTokenizer.canonical()
    source = "The agency shall provide notice before the hearing."
    encoding = tokenizer.encode_canonical(_deontic_ir(), source_text=source)
    pieces = tokenizer.decode_ids(encoding.token_ids)

    assert source not in pieces
    assert encoding.source_surface_separated is True
    assert encoding.source_surface_token_count == 0
    assert all(tokenizer.token_class_for_id(token_id) != "source_surface" for token_id in encoding.token_ids)
