"""Regression coverage for packet-003760 compiler ambiguity policy pairs."""

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
    COMPILER_AMBIGUITY_PACKET_003760_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_required_adaptive_ambiguity_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
    priority_signal_free_adaptive_ambiguity_targets,
    signal_free_adaptive_ambiguity_targets,
    supports_signal_free_adaptive_ambiguity_pair,
)


def _adaptive_ranking_for_outvote(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
):
    predicted_share = min(0.999, abs(family_margin) + 0.001)
    target_share = predicted_share + family_margin
    return [
        {
            "family": predicted_family,
            "count": 1,
            "logit": 1.3,
            "share_raw": predicted_share,
            "share": predicted_share,
            "source": "logit_softmax_fallback",
        },
        {
            "family": target_family,
            "count": 1,
            "logit": 1.1,
            "share_raw": target_share,
            "share": target_share,
            "source": "logit_softmax_fallback",
        },
    ]


def _adaptive_explicit_ambiguity(
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


def test_packet_003760_family_pairs_are_registered() -> None:
    expected_pairs = (
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.FRAME.value,
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.EPISTEMIC.value,
        ),
    )

    assert COMPILER_AMBIGUITY_PACKET_003760_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in priority_signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_signal_free_adaptive_ambiguity_pair(
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


def test_compiler_exposes_packet_003760_explicit_adaptive_ambiguities() -> None:
    evidence_cases = (
        {
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.994686265938,
            "text": (
                "The Secretary is authorized to conduct research under this "
                "subchapter and provide related grants."
            ),
        },
        {
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.EPISTEMIC.value,
            "family_margin": -0.339825600891,
            "text": (
                "For purposes of this section, the report may determine whether "
                "the entity is eligible under this chapter."
            ),
        },
        {
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": -0.068474574477,
            "text": (
                "The Secretary shall administer the program for purposes of this "
                "section and in accordance with this chapter."
            ),
        },
    )

    for case in evidence_cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        predicted_family = str(case["predicted_family"])
        target_family = str(case["target_family"])
        family_margin = float(case["family_margin"])
        ranking = _adaptive_ranking_for_outvote(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )

        def _mock_adaptive_family_ranking_from_logits(_encoding, *, ranking=ranking):
            return list(ranking)

        compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

        result = compiler.compile(
            str(case["text"]),
            document_id=f"compiler-ambiguity-packet-003760-{predicted_family}",
        )
        ambiguity = _adaptive_explicit_ambiguity(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
        )

        assert ambiguity is not None, case
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert ambiguity.metadata.get("adaptive_margin_direction") == "outvoted"
        assert (
            abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin)
            <= 1e-12
        )
