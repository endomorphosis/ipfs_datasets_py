"""Tests for hammer guidance artifacts consumed by Legal IR loops."""

from __future__ import annotations

import json

from ipfs_datasets_py.logic.integration.reasoning.hammer import (
    CallableHammerBackendRunner,
    HammerBackendResult,
    HammerBackendStatus,
    HammerGoal,
    HammerPremise,
    hammer_prove,
)
from ipfs_datasets_py.logic.integration.reasoning.hammer_guidance import (
    HAMMER_GUIDANCE_SCHEMA_VERSION,
    HammerGuidanceArtifact,
)


def _proved_backend():
    def _run(translation, timeout_seconds):
        return HammerBackendResult(
            backend="z3",
            status=HammerBackendStatus.PROVED,
            proved=True,
            elapsed_seconds=0.01,
            translation_format=translation.target_format,
            proof_trace="unsat",
            raw_output="unsat",
        )

    return CallableHammerBackendRunner("z3", "smt-lib", _run)


def test_hammer_guidance_artifact_sanitizes_source_text_and_marks_trusted() -> None:
    result = hammer_prove(
        HammerGoal(
            "deontic_polarity_supported(f1, operator:shall)",
            name="lir-obligation-1",
            metadata={"legal_ir_view": "deontic.ir", "logic_family": "deontic"},
        ),
        [
            HammerPremise(
                "deontic_norm_polarity_supported",
                "Deontic operators map to polarity.",
                metadata={"legal_ir_view": "deontic.ir", "logic_family": "deontic"},
            )
        ],
        backends=[_proved_backend()],
    )

    artifact = HammerGuidanceArtifact.from_hammer_result(
        result,
        candidate_metadata={
            "obligation_id": "lir-obligation-1",
            "source_span": "The agency shall provide the entire copied source span.",
            "target_metrics": ["compiler_ir_cross_entropy_loss"],
        },
    )
    payload = artifact.to_dict()
    encoded = json.dumps(payload, sort_keys=True)

    assert payload["schema_version"] == HAMMER_GUIDANCE_SCHEMA_VERSION
    assert payload["trusted"] is True
    assert payload["proved"] is True
    assert payload["backend_statuses"] == {"z3": "proved"}
    assert "entire copied source span" not in encoded
    assert payload["metadata"]["source_span_omitted"] is True
    assert "source_span_sha256" in payload["metadata"]
    assert artifact.to_leanstral_guidance_item()["accepted"] is True


def test_hammer_guidance_artifact_can_round_trip_from_dict() -> None:
    artifact = HammerGuidanceArtifact(
        guidance_id="guidance-1",
        obligation_id="obligation-1",
        trusted=False,
        legal_ir_view="modal.frame_logic",
        logic_family="modal",
        target_component="modal.frame_logic",
        goal_name="goal",
        goal_statement_hash="abc",
        proved=False,
        proof_checked=False,
        backend_statuses={"e": "unknown"},
        rejection_reasons=["unproved"],
    )

    restored = HammerGuidanceArtifact.from_dict(artifact.to_dict())

    assert restored == artifact
    assert restored.to_leanstral_guidance_item()["accepted"] is False
