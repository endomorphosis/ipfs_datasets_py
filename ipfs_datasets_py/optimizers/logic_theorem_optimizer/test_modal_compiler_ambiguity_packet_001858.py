"""Regression coverage for packet-001858 compiler ambiguity evidence margins."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationResult,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    ModalLogicFamily,
)


def _adaptive_explicit_ambiguity(
    result: ModalCompilationResult,
    *,
    predicted_family: str,
    target_family: str,
) -> object | None:
    expected_type = (
        f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
    )
    for ambiguity in result.ambiguities:
        if (
            ambiguity.ambiguity_type == expected_type
            and ambiguity.metadata.get("adaptive_predicted_family_source")
            in {"adaptive_logits", "adaptive_logits_fallback"}
            and ambiguity.metadata.get("predicted_family") == predicted_family
            and ambiguity.metadata.get("target_family") == target_family
        ):
            return ambiguity
    return None


@pytest.mark.parametrize(
    ("sample_id", "predicted_family", "target_family", "expected_margin", "expected_priority"),
    (
        (
            "us-code-42-7296.-46513acf2f9e7180",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.896586131543,
            1.046586131543,
        ),
        (
            "us-code-33-530-a655e18205d29ca4",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.FRAME.value,
            -0.634610908086,
            0.784610908086,
        ),
    ),
)
def test_compiler_preserves_packet_001858_compiler_ambiguity_policy_pair_margins(
    monkeypatch: pytest.MonkeyPatch,
    sample_id: str,
    predicted_family: str,
    target_family: str,
    expected_margin: float,
    expected_priority: float,
) -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _: {},
    )

    predicted_share = 0.70
    target_share = predicted_share + expected_margin

    def _mock_adaptive_family_ranking_from_logits(_encoding):
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
        "Ambiguity evidence.",
        document_id=f"compiler-ambiguity-packet-001858-{sample_id}",
    )

    ambiguity = _adaptive_explicit_ambiguity(
        result,
        predicted_family=predicted_family,
        target_family=target_family,
    )
    assert ambiguity is not None, sample_id
    assert ambiguity.severity == "requires_rule"
    assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
    assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
    assert (
        abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - expected_margin)
        <= 1e-12
    )
    assert (
        abs(float(ambiguity.metadata.get("priority", 0.0)) - expected_priority)
        <= 1e-12
    )
    assert (
        abs(
            float(ambiguity.metadata.get("adaptive_priority", 0.0))
            - expected_priority
        )
        <= 1e-12
    )
