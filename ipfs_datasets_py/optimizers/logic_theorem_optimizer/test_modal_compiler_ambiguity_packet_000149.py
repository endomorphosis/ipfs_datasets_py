"""Packet-000149 regressions for modal compiler ambiguity policy margins."""

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
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


_PACKET_000149_FAMILY_PAIRS = (
    ("deontic", "temporal"),
    ("temporal", "deontic"),
    ("conditional_normative", "deontic"),
    ("conditional_normative", "temporal"),
    ("deontic", "conditional_normative"),
    ("deontic", "deontic"),
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
        if (
            ambiguity.metadata.get("adaptive_predicted_family_source")
            != predicted_family_source
        ):
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
        resolved_runner_up_family = runner_up_family or "temporal"
        if resolved_runner_up_family == predicted_family:
            resolved_runner_up_family = "frame"
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


def test_packet_000149_policy_pairs_are_registered_across_compiler_ambiguity_policies() -> None:
    for predicted_family, target_family in _PACKET_000149_FAMILY_PAIRS:
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


def test_compiler_preserves_packet_000149_compiler_ambiguity_policy_margins() -> None:
    evidence_cases = (
        {
            "sample_id": "us-code-19-134-644ca84f03e20dcc",
            "predicted_family": "deontic",
            "target_family": "temporal",
            "family_margin": -0.534117632862,
            "priority": 0.684117632862,
            "severity": "requires_rule",
            "expected_type": "adaptive_deontic_temporal_outvoted_margin_low",
            "text": "The Secretary shall act by June 1, 2030.",
        },
        {
            "sample_id": "us-code-30-49e-00f97575fa6d0eaf",
            "predicted_family": "temporal",
            "target_family": "deontic",
            "family_margin": -0.595185254172,
            "priority": 0.745185254172,
            "severity": "requires_rule",
            "expected_type": "adaptive_temporal_deontic_outvoted_margin_low",
            "text": "Within 30 days, the Secretary shall submit the report.",
        },
        {
            "sample_id": "us-code-49-5902.-175e87e3ae6047a1",
            "predicted_family": "conditional_normative",
            "target_family": "deontic",
            "family_margin": -0.032714240754,
            "priority": 0.182714240754,
            "severity": "requires_rule",
            "expected_type": "adaptive_conditional_normative_deontic_outvoted_margin_low",
            "text": "Subject to section 3, the Secretary shall act.",
        },
        {
            "sample_id": "us-code-48-2127.-e55f82ccab948ec4",
            "predicted_family": "deontic",
            "target_family": "conditional_normative",
            "family_margin": -0.076279315968,
            "priority": 0.226279315968,
            "severity": "requires_rule",
            "expected_type": "adaptive_deontic_conditional_normative_outvoted_margin_low",
            "text": "The Board shall submit a budget subject to subsection (b).",
        },
        {
            "sample_id": "us-code-45-718.-e310dc7cf1fbce18",
            "predicted_family": "conditional_normative",
            "target_family": "temporal",
            "family_margin": -0.490724535602,
            "priority": 0.640724535602,
            "severity": "requires_rule",
            "expected_type": "adaptive_conditional_normative_temporal_outvoted_margin_low",
            "text": "As provided in section 5, the annual report is due by June 1.",
        },
        {
            "sample_id": "us-code-36-154710-cacf024a06bfaf21",
            "predicted_family": "deontic",
            "target_family": "deontic",
            "family_margin": 0.093734336927,
            "priority": 0.056265663073,
            "severity": "review",
            "expected_type": "adaptive_deontic_deontic_contested_margin_low",
            "runner_up_family": "temporal",
            "text": "The Secretary shall continue in office until a successor is chosen.",
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
            str(case["text"]),
            document_id=f"compiler-ambiguity-packet-000149-{case['sample_id']}",
        )
        ambiguity = _adaptive_explicit_ambiguity_from_source(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
            predicted_family_source="adaptive_logits",
        )
        assert ambiguity is not None, case["sample_id"]
        assert ambiguity.ambiguity_type == case["expected_type"]
        assert ambiguity.severity == case["severity"]
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
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
