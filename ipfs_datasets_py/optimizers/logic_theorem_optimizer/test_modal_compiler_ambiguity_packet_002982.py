"""Packet 002982 regressions for compiler ambiguity policy coverage."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.logic.modal.compiler import (  # noqa: E402
    DeterministicModalCompiler,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    ModalLogicFamily,
    compiler_required_adaptive_ambiguity_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
)


def _adaptive_explicit_ambiguity_from_adaptive_logits(
    result,
    *,
    predicted_family: str,
    target_family: str,
):
    for ambiguity in result.ambiguities:
        if not ambiguity.ambiguity_type.startswith("adaptive_"):
            continue
        if ambiguity.ambiguity_type == "adaptive_family_margin_low":
            continue
        if ambiguity.metadata.get("adaptive_predicted_family_source") != "adaptive_logits":
            continue
        if ambiguity.metadata.get("predicted_family") != predicted_family:
            continue
        if ambiguity.metadata.get("target_family") != target_family:
            continue
        return ambiguity
    return None


def test_modal_registry_packet_002982_family_pairs_are_in_compiler_ambiguity_policy() -> None:
    policy_pairs = (
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.CONDITIONAL_NORMATIVE.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.TEMPORAL.value),
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.CONDITIONAL_NORMATIVE.value),
        (ModalLogicFamily.CONDITIONAL_NORMATIVE.value, ModalLogicFamily.FRAME.value),
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.DEONTIC.value),
    )

    for predicted_family, target_family in policy_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)


def test_modal_registry_packet_002982_marks_conditional_to_frame_as_compiler_required() -> None:
    required_targets = compiler_required_adaptive_ambiguity_targets(
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value
    )
    assert ModalLogicFamily.FRAME.value in required_targets
    assert is_compiler_required_adaptive_ambiguity_pair(
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    )


def test_compiler_preserves_packet_002982_compiler_ambiguity_evidence_margins() -> None:
    cases = (
        {
            "sample_id": "us-code-25-1728-2cb0b5c09b753f93",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.925773252309,
            "priority": 1.075773252309,
        },
        {
            "sample_id": "us-code-26-612-bf01de561f726714",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.310097711398,
            "priority": 0.460097711398,
        },
        {
            "sample_id": "us-code-46-8105.-f80aaea904cbb54c",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.823068294259,
            "priority": 0.973068294259,
        },
        {
            "sample_id": "us-code-54-304110.-ad752a12f0563e42",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.883459204598,
            "priority": 1.033459204598,
        },
        {
            "sample_id": "us-code-18-1793-27994cce0e96b1f8",
            "predicted_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": -0.318807124892,
            "priority": 0.468807124892,
        },
        {
            "sample_id": "us-code-33-894f-07af79989f205a94",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.547780514781,
            "priority": 0.697780514781,
        },
    )

    for case in cases:
        predicted_family = str(case["predicted_family"])
        target_family = str(case["target_family"])
        expected_margin = float(case["family_margin"])
        expected_priority = float(case["priority"])
        predicted_share = abs(expected_margin)
        target_share = predicted_share + expected_margin

        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )

        def _mock_adaptive_family_ranking_from_logits(
            _encoding,
            *,
            predicted_family: str = predicted_family,
            target_family: str = target_family,
            predicted_share: float = predicted_share,
            target_share: float = target_share,
        ):
            return [
                {
                    "family": predicted_family,
                    "count": 0,
                    "logit": 1.3,
                    "share_raw": predicted_share,
                    "share": predicted_share,
                    "source": "logit_softmax_fallback",
                },
                {
                    "family": target_family,
                    "count": 0,
                    "logit": 1.1,
                    "share_raw": target_share,
                    "share": target_share,
                    "source": "logit_softmax_fallback",
                },
            ]

        compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

        result = compiler.compile(
            "As provided in section 3, the Secretary shall act by June 1, 2030.",
            document_id=f"compiler-ambiguity-packet-002982-{case['sample_id']}",
        )

        ambiguity = _adaptive_explicit_ambiguity_from_adaptive_logits(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
        )
        assert ambiguity is not None, case["sample_id"]
        assert ambiguity.ambiguity_type == (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        assert ambiguity.severity == "requires_rule"
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_compiler_required_policy_pair") is True
        assert (
            abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - expected_margin)
            <= 1e-12
        )
        assert (
            abs(float(ambiguity.metadata.get("priority", 0.0)) - expected_priority)
            <= 1e-12
        )
        assert (
            abs(float(ambiguity.metadata.get("adaptive_priority", 0.0)) - expected_priority)
            <= 1e-12
        )
