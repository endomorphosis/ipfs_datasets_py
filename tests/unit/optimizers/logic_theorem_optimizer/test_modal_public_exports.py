"""Public export smoke tests for deterministic modal parser components."""

from __future__ import annotations

import ipfs_datasets_py.optimizers.logic_theorem_optimizer as lto
import ipfs_datasets_py.optimizers.logic as legacy_logic


def test_modal_parser_components_are_publicly_exported() -> None:
    assert lto.ModalLogicFamily.DEONTIC.value == "deontic"
    assert lto.DEFAULT_MODAL_REGISTRY.get_profile("deontic").system.value == "D"
    assert lto.LegalModalParser().parse("The agency must act.").formulas
    assert lto.BM25FrameSelector(lto.DEFAULT_LEGAL_FRAME_FIXTURE).rank("agency notice")
    assert lto.stable_mock_embedding("sample")
    assert lto.HF_USCODE_DATASET_ID == "justicedao/ipfs_uscode"
    assert lto.USCODE_LAWS_PARQUET == "uscode_parquet/laws.parquet"
    assert lto.SpaCyModalCodec(encoder=lto.SpaCyLegalEncoder(model_name="missing_model")).encode_sample(
        lto.build_us_code_sample(title="5", section="552", text="The agency must act.")
    ).cues
    codec_result = lto.DeterministicModalLogicCodec(
        lto.ModalLogicCodecConfig(parser_backend="spacy")
    ).encode("The agency must provide notice.")
    assert codec_result.selected_frame == "administrative_notice_hearing"
    compiled = lto.DeterministicModalCompiler(
        lto.ModalCompilerConfig(parser_backend="regex")
    ).compile("The agency must provide notice.")
    decoded = lto.decode_modal_ir_document(compiled.modal_ir)
    assert decoded.phrases
    assert lto.decoded_modal_phrase_slot_text_map(decoded)["operator"] == ["obligatory"]
    assert callable(lto.synthesis_hints_from_autoencoder_introspection)
    assert lto.AutoencoderIntrospection
    assert lto.modal_formula_to_text(codec_result.modal_ir.formulas[0])
    assert lto.modal_text_token_similarity("agency must act", "agency must act") == 1.0
    assert lto.ModalAutoencoderBaseline().evaluate([]).sample_count == 0
    assert lto.AdaptiveModalAutoencoder().evaluate([]).sample_count == 0
    assert lto.ModalAutoencoderTrainingState().to_dict()["applied_todo_ids"] == []
    assert lto.ModalOptimizerPolicy().role_for(
        action="improve_modal_family_classifier",
        loss_name="cross_entropy_loss",
    ) == "autoencoder_sgd"
    assert lto.ModalProgramSynthesisTodoGenerator
    assert lto.ModalProverRouter().route(formula=None, system=lto.ModalSystem.S5).status == lto.ModalProverStatus.AVAILABLE
    assert lto.build_modal_parser_report(samples=[]).sample_count == 0
    assert lto.ModalTodoSupervisor().claim_next_batch(worker_id="worker", max_items=2) == []
    runner_args = lto.build_uscode_modal_daemon_arg_parser().parse_args(
        [
            "--run-id",
            "public-export-smoke",
            "--warm-start-run-id",
            "previous-run",
            "--warm-start-state",
            "previous.state.json",
        ]
    )
    assert runner_args.run_id == "public-export-smoke"
    assert runner_args.warm_start_run_id == ["previous-run"]
    assert runner_args.warm_start_state == ["previous.state.json"]
    assert callable(lto.run_guarded_uscode_modal_daemon)


def test_modal_daemon_components_are_exported_from_logic_namespace() -> None:
    assert legacy_logic.AdaptiveModalAutoencoder().evaluate([]).sample_count == 0
    assert legacy_logic.DeterministicModalLogicCodec(
        legacy_logic.ModalLogicCodecConfig(parser_backend="spacy")
    ).encode("The agency must provide notice.").selected_frame == "administrative_notice_hearing"
    assert legacy_logic.decode_modal_ir_document(
        legacy_logic.DeterministicModalCompiler().compile("The agency must act.").modal_ir
    ).phrases
    assert callable(legacy_logic.synthesis_hints_from_autoencoder_introspection)
    assert legacy_logic.modal_text_token_similarity("agency must act", "agency may act") < 1.0
    assert legacy_logic.ModalAutoencoderTrainingState().to_dict()["applied_todo_ids"] == []
    assert legacy_logic.ModalOptimizerPolicy().role_for(
        action="add_deterministic_parser_rule",
        loss_name="parser_formula_count",
    ) == "program_synthesis"
    assert legacy_logic.ModalProgramSynthesisTodoGenerator
    assert legacy_logic.ModalTodoSupervisor().claim_next_batch(worker_id="worker", max_items=2) == []
    assert legacy_logic.build_uscode_modal_daemon_arg_parser().parse_args(
        ["--run-id", "logic-namespace-smoke"]
    ).run_id == "logic-namespace-smoke"
    assert callable(legacy_logic.run_guarded_uscode_modal_daemon)
