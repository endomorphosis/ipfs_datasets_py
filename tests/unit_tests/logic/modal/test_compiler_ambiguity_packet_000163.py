"""Regression coverage for packet-000163 compiler ambiguity policy pairs."""

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
    COMPILER_AMBIGUITY_PACKET_000163_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    is_compiler_ambiguity_policy_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def _adaptive_ranking_for_margin(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
):
    predicted_share = 0.7
    target_share = predicted_share + family_margin
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


def test_packet_000163_family_pairs_are_registered() -> None:
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_000163_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_compiler_preserves_packet_000163_explicit_ambiguity_policy_pairs() -> None:
    evidence_cases = (
        {
            "sample_id": "us-code-31-5115-7ce43b3c36ceb277",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": -0.661875858292,
            "text": (
                "United States currency notes shall be issued under this section "
                "within the authority of the Secretary."
            ),
        },
        {
            "sample_id": "us-code-15-1199-768607b95c168102",
            "predicted_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.111358353933,
            "text": (
                "If the Commission determines that a person violates this section, "
                "the person shall comply with the order."
            ),
        },
        {
            "sample_id": "us-code-30-24-ca9fb7a95ddb4f73",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.450949818893,
            "text": (
                "Proof of citizenship shall be made under regulations prescribed "
                "for mineral lands."
            ),
        },
        {
            "sample_id": "us-code-45-797m.-3c6a8930dbf835c3",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.265584743477,
            "text": (
                "Any dispute with respect to interpretation under this subchapter "
                "may be submitted if the parties agree."
            ),
        },
        {
            "sample_id": "us-code-16-4412-1d586cde28403027",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.EPISTEMIC.value,
            "family_margin": -0.175597063344,
            "text": (
                "The findings under this chapter determine whether the program may "
                "continue."
            ),
        },
        {
            "sample_id": "us-code-26-1021-8fd2a2f6811ff75e",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.221784868084,
            "text": (
                "After the disposition occurs, the taxpayer shall recognize gain "
                "as provided in this part."
            ),
        },
        {
            "sample_id": "us-code-30-1308a-b5cb6f4cb8397723",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.208720843419,
            "text": (
                "Under this section, the report shall be filed after the inspection "
                "is completed."
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
        ranking = _adaptive_ranking_for_margin(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )

        def _mock_adaptive_family_ranking_from_logits(_encoding, *, ranking=ranking):
            return list(ranking)

        compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

        result = compiler.compile(
            str(case["text"]),
            document_id=f"compiler-ambiguity-packet-000163-{case['sample_id']}",
        )
        ambiguity = _adaptive_explicit_ambiguity(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
        )
        assert ambiguity is not None, case["sample_id"]
        assert (
            ambiguity.ambiguity_type
            == f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        assert ambiguity.severity == "requires_rule"
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert ambiguity.metadata.get("adaptive_margin_direction") == "outvoted"
        assert (
            abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin)
            <= 1e-12
        )
