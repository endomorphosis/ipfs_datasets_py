"""Public export smoke tests for deterministic modal parser components."""

from __future__ import annotations

import ipfs_datasets_py.optimizers.logic_theorem_optimizer as lto


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
    assert lto.ModalAutoencoderBaseline().evaluate([]).sample_count == 0
    assert lto.AdaptiveModalAutoencoder().evaluate([]).sample_count == 0
    assert lto.ModalAutoencoderTrainingState().to_dict()["applied_todo_ids"] == []
    assert lto.ModalProverRouter().route(formula=None, system=lto.ModalSystem.S5).status == lto.ModalProverStatus.AVAILABLE
    assert lto.build_modal_parser_report(samples=[]).sample_count == 0
    assert lto.ModalTodoSupervisor().claim_next_batch(worker_id="worker", max_items=2) == []
