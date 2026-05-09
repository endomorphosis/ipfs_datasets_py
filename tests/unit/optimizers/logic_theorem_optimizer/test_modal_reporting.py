"""Tests for modal parser reports."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderBaseline
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_prover_router import ModalProverRouter
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import ModalSystem
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_reporting import build_modal_parser_report


def test_modal_parser_report_summarizes_samples_losses_and_provers() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice and a hearing before a final order.",
    )
    autoencoder = ModalAutoencoderBaseline().evaluate([sample])
    prover_results = [
        ModalProverRouter().route(formula=None, system=ModalSystem.S5),
        ModalProverRouter().route(formula=None, system=ModalSystem.KD45),
    ]

    report = build_modal_parser_report(
        samples=[sample],
        autoencoder=autoencoder,
        prover_results=prover_results,
        expected_frames={sample.sample_id: sample.selected_frame or ""},
    )

    payload = report.to_dict()
    rendered = report.to_markdown()

    assert payload["sample_count"] == 1
    assert payload["frame_top1_accuracy"] == 1.0
    assert payload["reconstruction_loss"] == 0.0
    assert payload["prover_availability"]["available"] == 1
    assert payload["prover_availability"]["unavailable"] == 1
    assert "Modal Parser Report" in rendered
