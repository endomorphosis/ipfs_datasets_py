"""Tests for spaCy-based modal encoder / IR / decoder workflows."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_todo_daemon import ModalTodoSupervisor
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (
    SpaCyLegalEncoder,
    SpaCyModalCodec,
    SpaCyModalDecoder,
    SpaCyModalIRCompiler,
    ranked_modal_families,
)

pytest.importorskip("spacy")


def test_spacy_encoder_compiles_modal_ir_without_downloaded_model() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "The agency must make records promptly available to any person.",
        document_id="sample-5-552",
        citation="5 U.S.C. 552",
        source="us_code",
    )

    modal_ir = SpaCyModalIRCompiler().compile(encoding)

    assert encoding.used_fallback_model is True
    assert encoding.tokens
    assert encoding.cues[0].family == "deontic"
    assert modal_ir.metadata["llm_call_count"] == 0
    assert modal_ir.formulas[0].operator.family == "deontic"
    assert "records" in modal_ir.formulas[0].predicate.name


def test_spacy_compiler_extracts_condition_and_exception_slots() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    encoding = encoder.encode(
        "If the application is complete, the agency must issue written notice unless waived.",
        document_id="sample-condition-exception",
    )

    modal_ir = SpaCyModalIRCompiler().compile(encoding)
    deontic_formula = next(
        formula for formula in modal_ir.formulas if formula.operator.family == "deontic"
    )

    assert "if the application is complete" in deontic_formula.conditions
    assert "unless waived" in deontic_formula.exceptions


def test_spacy_compiler_replays_uscode_editorial_status_zero_formula_cases() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-2-117j-0f405de004ab24ed",
            "2 U.S.C. 117j",
            "\u00a7117j. Omitted.",
        ),
        (
            "us-code-7-450-759794f8a1f6176f",
            "7 U.S.C. 450",
            "\u00a7450. Omitted.",
        ),
        (
            "us-code-8-71-ba23a2579e9f7282",
            "8 U.S.C. 71",
            "\u00a771. Omitted.",
        ),
    ]

    for document_id, citation, text in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_editorial_status_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_editorial_status_heading_v1"
        assert fallback.metadata["status_keyword"] == "omitted"
        assert fallback.provenance.citation == citation


def test_spacy_compiler_replays_uscode_declarative_statement_zero_formula_cases() -> None:
    encoder = SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
    compiler = SpaCyModalIRCompiler()
    cases = [
        (
            "us-code-22-2688-83d45528085ab9e0",
            "22 U.S.C. 2688",
            (
                "U.S.C. Title 22 - FOREIGN RELATIONS AND INTERCOURSE 22 U.S.C. "
                "United States Code, 2024 Edition Title 22 - FOREIGN RELATIONS "
                "AND INTERCOURSE CHAPTER 38 - DEPARTMENT OF STATE Sec. 2688 - "
                "Ambassadors; criteria regarding selection and confirmation From the "
                "U.S. Government Publishing Office, www.gpo.gov \u00a72688. Ambassadors; "
                "criteria regarding selection and confirmation It is the sense of "
                "the Congress that the position of United States ambassador to a "
                "foreign country should be accorded to men and women possessing "
                "clearly demonstrated competence to perform ambassadorial duties. "
                "No individual should be accorded the position of United States "
                "ambassador to a foreign country primarily because of financial "
                "contributions to political campaigns. (Aug. 1, 1956, ch. 841, "
                "title I, \u00a718, as added Pub. L. 94\u2013141, title I, \u00a7104, Nov. 29, "
                "1975, 89 Stat. 757; renumbered title I, Pub. L. 97\u2013241, title II, "
                "\u00a7202(a), Aug. 24, 1982, 96 Stat. 282.)"
            ),
            "sense_of_congress",
        ),
        (
            "us-code-7-7311-017c4d8b52982ca1",
            "7 U.S.C. 7311",
            (
                "U.S.C. Title 7 - AGRICULTURE 7 U.S.C. United States Code, 2024 "
                "Edition Title 7 - AGRICULTURE CHAPTER 100 - AGRICULTURAL MARKET "
                "TRANSITION SUBCHAPTER VII - COMMISSION ON 21st CENTURY PRODUCTION "
                "AGRICULTURE Sec. 7311 - Establishment From the U.S. Government "
                "Publishing Office, www.gpo.gov \u00a77311. Establishment There is "
                "established a commission to be known as the \"Commission on 21st "
                "Century Production Agriculture\" (in this subchapter referred to as "
                "the \"Commission\"). (Pub. L. 104\u2013127, title I, \u00a7181, Apr. 4, "
                "1996, 110 Stat. 938.)"
            ),
            "establishment_clause",
        ),
        (
            "us-code-15-2402-7e27f5e59f9ba39e",
            "15 U.S.C. 2402",
            (
                "U.S.C. Title 15 - COMMERCE AND TRADE 15 U.S.C. United States "
                "Code, 2024 Edition Title 15 - COMMERCE AND TRADE CHAPTER 51 - "
                "NATIONAL PRODUCTIVITY AND QUALITY OF WORKING LIFE SUBCHAPTER I - "
                "FINDINGS, PURPOSE, AND POLICY; DEFINITIONS Sec. 2402 - "
                "Congressional statement of purpose From the U.S. Government "
                "Publishing Office, www.gpo.gov \u00a72402. Congressional statement of "
                "purpose It is the purpose of this chapter\u2014 (1) to establish a "
                "national policy which will encourage productivity growth "
                "consistent with needs of the economy, the natural environment, "
                "and the needs, rights, and best interests of management, the "
                "work force, and consumers; and (2) to establish as an independent "
                "establishment of the executive branch a National Center for "
                "Productivity and Quality of Working Life to focus, coordinate, "
                "and promote efforts to improve the rate of productivity growth. "
                "(Pub. L. 94\u2013136, title I, \u00a7102, Nov. 28, 1975, 89 Stat. 734.)"
            ),
            "purpose_clause",
        ),
    ]

    for document_id, citation, text, statement_hint in cases:
        encoding = encoder.encode(
            text,
            document_id=document_id,
            citation=citation,
            source="us_code",
        )
        modal_ir = compiler.compile(encoding)

        assert modal_ir.formulas
        fallback = modal_ir.formulas[-1]
        assert fallback.operator.family == "frame"
        assert fallback.metadata["cue"] == "__uscode_declarative_statement_fallback__"
        assert fallback.metadata["fallback_rule"] == "uscode_declarative_statement_v1"
        assert fallback.metadata["statement_hint"] == statement_hint
        assert fallback.provenance.citation == citation


def test_spacy_decoder_vector_and_family_logits_are_deterministic() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must make records promptly available.",
    )

    first = codec.decode_sample_embedding(sample, dimensions=6)
    second = codec.decode_sample_embedding(sample, dimensions=6)
    logits = codec.family_logits_for_sample(sample, modal_families=("deontic", "temporal", "hybrid"))

    assert first == second
    assert len(first) == 6
    assert any(value != 0.0 for value in first)
    assert logits["deontic"] > logits["temporal"]


def test_spacy_codec_exposes_text_features_without_sample_ids() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must make records promptly available.",
    )

    features = codec.feature_keys_for_sample(sample)

    assert features
    assert any(feature.startswith("cue:deontic") for feature in features)
    assert all(sample.sample_id not in feature for feature in features)


def test_spacy_codec_ranks_modal_families_from_cues() -> None:
    codec = SpaCyModalCodec(
        encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model"),
        decoder=SpaCyModalDecoder(),
    )
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall provide notice within 30 days.",
    )

    ranking = ranked_modal_families(codec.encode_sample(sample))

    assert ranking
    assert ranking[0]["family"] in {"deontic", "temporal"}
    assert ranking[0]["count"] >= 1
    assert abs(sum(item["share"] for item in ranking) - 1.0) <= 1e-6


def test_spacy_codec_lowers_initial_family_cross_entropy() -> None:
    sample = build_us_code_sample(
        title="42",
        section="1983",
        text="A person may bring an action when rights are deprived under color of law.",
    )
    plain = AdaptiveModalAutoencoder()
    spacy = AdaptiveModalAutoencoder(
        feature_codec=SpaCyModalCodec(
            encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
        )
    )

    plain_eval = plain.evaluate([sample])
    spacy_eval = spacy.evaluate([sample])

    assert spacy_eval.cross_entropy_loss < plain_eval.cross_entropy_loss


def test_supervisor_with_spacy_codec_improves_loss_and_cosine() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must make records promptly available to any person.",
        embedding_vector=[0.1, 0.2, 0.3, 0.4],
    )
    autoencoder = AdaptiveModalAutoencoder(
        feature_codec=SpaCyModalCodec(
            encoder=SpaCyLegalEncoder(model_name="definitely_missing_legal_model")
        )
    )
    supervisor = ModalTodoSupervisor()
    before = autoencoder.evaluate([sample])

    run = supervisor.optimize(
        [sample],
        autoencoder=autoencoder,
        max_iterations=2,
        max_items=4,
        learning_rate=0.5,
    )

    assert run.final_evaluation.cross_entropy_loss < before.cross_entropy_loss
    assert run.final_evaluation.reconstruction_loss < before.reconstruction_loss
    assert run.final_evaluation.embedding_cosine_similarity > before.embedding_cosine_similarity
    assert supervisor.queue.status_counts()["completed"] >= 2
