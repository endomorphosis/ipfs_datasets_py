"""Regression coverage for packet-000594 compiler ambiguity policy pairs."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.logic.modal.compiler import (  # noqa: E402
    DeterministicModalCompiler,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (  # noqa: E402
    ModalIRDocument,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_AMBIGUITY_PACKET_000594_FAMILY_PAIRS,
    compiler_ambiguity_policy_targets,
    compiler_required_adaptive_ambiguity_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    priority_signal_free_adaptive_ambiguity_targets,
    signal_free_adaptive_ambiguity_targets,
    supports_signal_free_adaptive_ambiguity_pair,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (  # noqa: E402
    SpaCyLegalEncoding,
)


def _adaptive_ranking_for_margin(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> list[dict[str, float | int | str]]:
    if predicted_family == target_family:
        runner_up_family = "deontic" if predicted_family != "deontic" else "frame"
        predicted_share = (1.0 + family_margin) / 2.0
        runner_up_share = predicted_share - family_margin
        return [
            {
                "family": predicted_family,
                "count": 0,
                "logit": 1.3,
                "share_raw": predicted_share,
                "share": predicted_share,
                "source": "packet_000594_fixture",
            },
            {
                "family": runner_up_family,
                "count": 0,
                "logit": 1.1,
                "share_raw": runner_up_share,
                "share": runner_up_share,
                "source": "packet_000594_fixture",
            },
        ]

    predicted_share = 0.7
    target_share = predicted_share + family_margin
    if target_share <= 0.0:
        predicted_share = min(0.99, abs(family_margin) + 0.05)
        target_share = predicted_share + family_margin
    return [
        {
            "family": predicted_family,
            "count": 0,
            "logit": 1.3,
            "share_raw": predicted_share,
            "share": predicted_share,
            "source": "packet_000594_fixture",
        },
        {
            "family": target_family,
            "count": 0,
            "logit": 1.1,
            "share_raw": target_share,
            "share": target_share,
            "source": "packet_000594_fixture",
        },
    ]


def test_packet_000594_pairs_are_registered_across_ambiguity_policies() -> None:
    expected_pairs = (
        ("frame", "conditional_normative"),
        ("frame", "deontic"),
        ("temporal", "deontic"),
        ("deontic", "deontic"),
        ("frame", "frame"),
    )
    assert COMPILER_AMBIGUITY_PACKET_000594_FAMILY_PAIRS == expected_pairs

    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in priority_signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in signal_free_adaptive_ambiguity_targets(predicted_family)


def test_compiler_surfaces_packet_000594_explicit_adaptive_ambiguities() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(modal_adaptive_family_margin=0.15)
    )
    scenarios = (
        ("frame", "conditional_normative", -0.397073496715),
        ("temporal", "deontic", -0.163376681172),
        ("frame", "deontic", -0.076027958193),
        ("deontic", "deontic", 0.094979996689),
        ("frame", "frame", 0.083494653433),
    )

    for predicted_family, target_family, family_margin in scenarios:
        ranking = _adaptive_ranking_for_margin(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )
        ambiguities = compiler._adaptive_family_margin_ambiguities(
            SpaCyLegalEncoding(
                document_id="packet-000594",
                text="Synthetic packet-000594 modal-family evidence.",
                normalized_text="Synthetic packet-000594 modal-family evidence.",
                tokens=[],
                sentences=[],
                cues=[],
            ),
            modal_ir=ModalIRDocument(
                document_id="packet-000594",
                source="legal_text",
                normalized_text="Synthetic packet-000594 modal-family evidence.",
            ),
            ranking=ranking,
            family_shares={
                str(candidate["family"]): float(candidate["share_raw"])
                for candidate in ranking
            },
            predicted_family_source="adaptive_logits",
        )
        direction = "outvoted" if family_margin <= 0.0 else "contested"
        expected_type = (
            f"adaptive_{predicted_family}_{target_family}_{direction}_margin_low"
        )
        explicit = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == expected_type
        )

        assert explicit.metadata["is_explicit_adaptive_ambiguity"] is True
        assert explicit.metadata["is_compiler_ambiguity_bundle_pair"] is True
        assert explicit.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
        assert explicit.metadata["adaptive_policy_pair"] == (
            f"{predicted_family}->{target_family}"
        )
        assert abs(
            float(explicit.metadata["family_margin_raw"]) - family_margin
        ) <= 1e-12
