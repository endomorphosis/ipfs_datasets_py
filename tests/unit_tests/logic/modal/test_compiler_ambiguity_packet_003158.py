"""Regression coverage for packet-003158 frame/conditional ambiguity policy."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, Sequence

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.logic.modal.compiler import (  # noqa: E402
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (  # noqa: E402
    ModalIRDocument,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_AMBIGUITY_PACKET_003158_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (  # noqa: E402
    SpaCyLegalEncoding,
)


def _signal_free_ranking(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> List[Dict[str, Any]]:
    predicted_share = abs(float(family_margin))
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
            "logit": 1.2,
            "share_raw": 0.0,
            "share": 0.0,
            "source": "logit_softmax_fallback",
        },
    ]


def _matching_explicit_ambiguity(
    *,
    ambiguities: Sequence[ModalCompilationAmbiguity],
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> ModalCompilationAmbiguity | None:
    for ambiguity in ambiguities:
        if not ambiguity.ambiguity_type.startswith("adaptive_"):
            continue
        if ambiguity.ambiguity_type == "adaptive_family_margin_low":
            continue
        metadata: Mapping[str, Any] = ambiguity.metadata
        if metadata.get("adaptive_predicted_family_source") != "adaptive_logits":
            continue
        if metadata.get("predicted_family") != predicted_family:
            continue
        if metadata.get("target_family") != target_family:
            continue
        if abs(float(metadata.get("family_margin_raw", 0.0)) - family_margin) > 1e-12:
            continue
        return ambiguity
    return None


def test_packet_003158_pair_is_registered_across_ambiguity_policies() -> None:
    predicted_family = ModalLogicFamily.FRAME.value
    target_family = ModalLogicFamily.CONDITIONAL_NORMATIVE.value

    assert COMPILER_AMBIGUITY_PACKET_003158_FAMILY_PAIRS == (
        (predicted_family, target_family),
    )
    assert target_family in compiler_ambiguity_policy_targets(predicted_family)
    assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
    assert is_compiler_required_adaptive_ambiguity_pair(
        predicted_family,
        target_family,
    )
    assert is_signal_free_adaptive_ambiguity_pair(predicted_family, target_family)
    assert is_priority_signal_free_adaptive_ambiguity_pair(
        predicted_family,
        target_family,
    )
    assert supports_signal_free_adaptive_ambiguity_pair(
        predicted_family,
        target_family,
    )


def test_compiler_exposes_packet_003158_signal_free_adaptive_ambiguities() -> None:
    predicted_family = ModalLogicFamily.FRAME.value
    target_family = ModalLogicFamily.CONDITIONAL_NORMATIVE.value
    evidence_margins = (-0.327303573273, -0.296748400059)
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )
    encoding = SpaCyLegalEncoding(
        document_id="compiler-ambiguity-packet-003158",
        text="Secs. 1 to 5 - Repealed.",
        normalized_text="secs. 1 to 5 - repealed.",
        tokens=[],
        sentences=[],
        cues=[],
    )
    modal_ir = ModalIRDocument(
        document_id=encoding.document_id,
        source=encoding.source,
        normalized_text=encoding.normalized_text,
    )

    for family_margin in evidence_margins:
        ranking = _signal_free_ranking(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )
        family_shares = {
            str(candidate["family"]): float(candidate["share_raw"])
            for candidate in ranking
        }
        ambiguities = compiler._adaptive_family_margin_ambiguities(
            encoding,
            modal_ir=modal_ir,
            ranking=ranking,
            family_shares=family_shares,
            predicted_family_source="adaptive_logits",
        )
        ambiguity = _matching_explicit_ambiguity(
            ambiguities=ambiguities,
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )

        assert ambiguity is not None, [item.to_dict() for item in ambiguities]
        assert ambiguity.ambiguity_type == (
            "adaptive_frame_conditional_normative_outvoted_margin_low"
        )
        assert ambiguity.severity == "requires_rule"
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == (
            "compiler_ambiguity"
        )
        assert ambiguity.metadata.get("signal_free_pair_policy_applied") is True
        assert ambiguity.metadata.get("adaptive_margin_direction") == "outvoted"
