"""Regression coverage for compiler_ambiguity packet-001774 margins."""

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
    COMPILER_AMBIGUITY_PACKET_001774_FAMILY_PAIRS,
    compiler_ambiguity_policy_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (  # noqa: E402
    SpaCyLegalEncoding,
)


def _ranking(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> list[dict[str, float | int | str]]:
    if predicted_family == target_family:
        predicted_share = 0.574681325805
        runner_up_share = predicted_share - family_margin
        return [
            {
                "family": predicted_family,
                "count": 0,
                "share_raw": predicted_share,
                "share": predicted_share,
                "source": "packet_001774_fixture",
            },
            {
                "family": "temporal",
                "count": 0,
                "share_raw": runner_up_share,
                "share": runner_up_share,
                "source": "packet_001774_fixture",
            },
        ]

    predicted_share = 0.55
    target_share = predicted_share + family_margin
    return [
        {
            "family": predicted_family,
            "count": 0,
            "share_raw": predicted_share,
            "share": predicted_share,
            "source": "packet_001774_fixture",
        },
        {
            "family": target_family,
            "count": 0,
            "share_raw": target_share,
            "share": target_share,
            "source": "packet_001774_fixture",
        },
    ]


def test_packet_001774_pairs_are_supported_across_compiler_ambiguity_policies() -> None:
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_001774_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_compiler_exposes_packet_001774_explicit_ambiguity_margins() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(
            parser_backend="spacy",
            modal_adaptive_family_margin=0.15,
        )
    )
    scenarios = (
        ("deontic", "temporal", -0.034780838147, "outvoted"),
        ("deontic", "deontic", 0.14936265161, "contested"),
    )

    for predicted_family, target_family, family_margin, direction in scenarios:
        ranking = _ranking(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        ambiguities = compiler._adaptive_family_margin_ambiguities(
            SpaCyLegalEncoding(
                document_id="packet-001774",
                text=(
                    "In fiscal year 2015 and subsequent fiscal years, "
                    "the Secretary shall submit a report."
                ),
                normalized_text=(
                    "in fiscal year 2015 and subsequent fiscal years, "
                    "the secretary shall submit a report."
                ),
                tokens=[],
                sentences=[],
                cues=[],
            ),
            modal_ir=ModalIRDocument(
                document_id="packet-001774",
                source="legal_text",
                normalized_text=(
                    "in fiscal year 2015 and subsequent fiscal years, "
                    "the secretary shall submit a report."
                ),
            ),
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )

        explicit_type = (
            f"adaptive_{predicted_family}_{target_family}_{direction}_margin_low"
        )
        explicit = next(
            ambiguity
            for ambiguity in ambiguities
            if ambiguity.ambiguity_type == explicit_type
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
