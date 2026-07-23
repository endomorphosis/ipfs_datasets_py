"""Packet-000431 regressions for compiler ambiguity policy evidence margins."""

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
    COMPILER_AMBIGUITY_PACKET_000431_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_required_adaptive_ambiguity_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def _adaptive_explicit_ambiguity_from_source(
    result,
    *,
    predicted_family: str,
    target_family: str,
    predicted_family_source: str,
):
    for ambiguity in result.ambiguities:
        if not ambiguity.ambiguity_type.startswith("adaptive_"):
            continue
        if ambiguity.ambiguity_type == "adaptive_family_margin_low":
            continue
        if ambiguity.metadata.get("adaptive_predicted_family_source") != predicted_family_source:
            continue
        if ambiguity.metadata.get("predicted_family") != predicted_family:
            continue
        if ambiguity.metadata.get("target_family") != target_family:
            continue
        return ambiguity
    return None


def _adaptive_ranking_for_margin(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
    runner_up_family: str | None = None,
):
    if predicted_family == target_family:
        resolved_runner_up_family = runner_up_family or ModalLogicFamily.TEMPORAL.value
        if resolved_runner_up_family == predicted_family:
            resolved_runner_up_family = ModalLogicFamily.FRAME.value
        predicted_share = (1.0 + family_margin) / 2.0
        runner_up_share = predicted_share - family_margin
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
                "family": resolved_runner_up_family,
                "count": 0,
                "logit": 1.2,
                "share_raw": runner_up_share,
                "share": runner_up_share,
                "source": "logit_softmax_fallback",
            },
        ]

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


def test_modal_registry_packet_000431_policy_pairs_are_supported() -> None:
    expected_pairs = {
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.CONDITIONAL_NORMATIVE.value),
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.FRAME.value),
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.TEMPORAL.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.FRAME.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.TEMPORAL.value),
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.CONDITIONAL_NORMATIVE.value),
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.FRAME.value),
    }

    assert set(COMPILER_AMBIGUITY_PACKET_000431_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_compiler_preserves_packet_000431_compiler_ambiguity_policy_margins(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.ranked_modal_families",
        lambda _encoding: [],
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.compiler.modal_ambiguity_signals",
        lambda _encoding: {},
    )

    evidence_cases = (
        {
            "sample_id": "us-code-33-52-c33afc9278749afd",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.441566650969,
            "priority": 0.591566650969,
        },
        {
            "sample_id": "us-code-22-8221-192e8058a17276b6",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.210917529255,
            "priority": 0.360917529255,
        },
        {
            "sample_id": "us-code-7-2279f-b8d33d8498907c51",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": -0.329925936699,
            "priority": 0.479925936699,
        },
        {
            "sample_id": "us-code-16-715-f3d4f4f2776596ab",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.037532236427,
            "priority": 0.187532236427,
        },
        {
            "sample_id": "us-code-33-58-84b26703acd87752",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.039389954367,
            "priority": 0.189389954367,
        },
        {
            "sample_id": "us-code-16-2514-ecf8ad71d86ec814",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": 0.090238107625,
            "priority": 0.059761892375,
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
        },
        {
            "sample_id": "us-code-46-51311.-6984e07723d58fbe",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": 0.072580509991,
            "priority": 0.077419490009,
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
        },
        {
            "sample_id": "us-code-25-2011-61dc84359d982002",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": 0.10785051488,
            "priority": 0.04214948512,
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
        },
        {
            "sample_id": "us-code-25-1300j-5-baeda08258bb22df",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.328789656925,
            "priority": 0.478789656925,
        },
        {
            "sample_id": "us-code-3-8-8703e49dcc6e7e9c",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": 0.13949180022,
            "priority": 0.01050819978,
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
        },
        {
            "sample_id": "us-code-26-5414-c7b48692bb8d04e7",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": 0.111292613281,
            "priority": 0.038707386719,
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
        },
        {
            "sample_id": "us-code-10-908-c7ea8201c8abb439",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.344333958025,
            "priority": 0.494333958025,
        },
        {
            "sample_id": "us-code-28-1497-bbb6be63a2818eb6",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": -0.060317234675,
            "priority": 0.210317234675,
        },
        {
            "sample_id": "us-code-33-574a-0dfe7fdc7e73e510",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.070653233171,
            "priority": 0.220653233171,
        },
        {
            "sample_id": "us-code-33-512-0df9f6cf956f4a5f",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.460395336355,
            "priority": 0.610395336355,
        },
    )

    for case in evidence_cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        predicted_family = str(case["predicted_family"])
        target_family = str(case["target_family"])
        family_margin = float(case["family_margin"])
        expected_priority = float(case["priority"])
        ranking = _adaptive_ranking_for_margin(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
            runner_up_family=(
                str(case["runner_up_family"])
                if case.get("runner_up_family") is not None
                else None
            ),
        )

        def _mock_adaptive_family_ranking_from_logits(_encoding, *, ranking=ranking):
            return list(ranking)

        compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

        result = compiler.compile(
            "Synthetic legal ambiguity evidence for packet 000431.",
            document_id=f"compiler-ambiguity-packet-000431-{case['sample_id']}",
        )
        ambiguity = _adaptive_explicit_ambiguity_from_source(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
            predicted_family_source="adaptive_logits_fallback",
        )
        assert ambiguity is not None, case["sample_id"]

        expected_margin_direction = (
            "contested" if family_margin > 0.0 else "outvoted"
        )
        expected_type = (
            f"adaptive_{predicted_family}_{target_family}_"
            f"{expected_margin_direction}_margin_low"
        )
        expected_severity = "review" if family_margin > 0.0 else "requires_rule"

        assert ambiguity.ambiguity_type == expected_type
        assert ambiguity.severity == expected_severity
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_compiler_required_policy_pair") is True
        assert (
            abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin)
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
