"""Regression coverage for packet-000614 adaptive compiler ambiguity margins."""

from __future__ import annotations

import os
from typing import Dict, List

import pytest

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

import ipfs_datasets_py.logic.modal.compiler as modal_compiler_module  # noqa: E402
from ipfs_datasets_py.logic.modal.compiler import (  # noqa: E402
    DeterministicModalCompiler,
    ModalCompilationResult,
    ModalCompilerConfig,
)


def _adaptive_explicit_ambiguity_from_source(
    result: ModalCompilationResult,
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
    runner_up_family: str,
) -> List[Dict[str, float | int | str]]:
    if predicted_family == target_family:
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
                "family": runner_up_family,
                "count": 0,
                "logit": 1.2,
                "share_raw": runner_up_share,
                "share": runner_up_share,
                "source": "logit_softmax_fallback",
            },
        ]

    predicted_share = (1.0 - family_margin) / 2.0
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
            "logit": 1.2,
            "share_raw": target_share,
            "share": target_share,
            "source": "logit_softmax_fallback",
        },
    ]


@pytest.mark.parametrize(
    (
        "sample_id",
        "predicted_family",
        "target_family",
        "family_margin",
        "priority",
        "runner_up_family",
    ),
    (
        (
            "us-code-16-917c-0913b5c73058e31b",
            "temporal",
            "deontic",
            -0.419325903229,
            0.569325903229,
            "frame",
        ),
        (
            "us-code-42-291j-cba22c7a590db468",
            "deontic",
            "conditional_normative",
            -0.176203515589,
            0.326203515589,
            "temporal",
        ),
        (
            "us-code-42-6304.-3b0aa5b5f96a9909",
            "temporal",
            "deontic",
            -0.32748399488,
            0.47748399488,
            "frame",
        ),
        (
            "us-code-35-187-0a14fab7795a0e51",
            "frame",
            "deontic",
            -0.416711860344,
            0.566711860344,
            "temporal",
        ),
        (
            "us-code-16-410hhh-9-4068b9508c0961e9",
            "temporal",
            "deontic",
            -0.438933952008,
            0.588933952008,
            "frame",
        ),
        (
            "us-code-3-1-5ad676979bb682b3",
            "deontic",
            "deontic",
            0.027658417342,
            0.122341582658,
            "temporal",
        ),
        (
            "us-code-5-6106-4d53ce42f7ce861d",
            "deontic",
            "deontic",
            0.085910637236,
            0.064089362764,
            "temporal",
        ),
        (
            "us-code-25-1665f-0333fcf39796ff8f",
            "deontic",
            "deontic",
            0.039552768742,
            0.110447231258,
            "temporal",
        ),
        (
            "us-code-47-757.-4cde545c3d5b5952",
            "frame",
            "conditional_normative",
            -0.40415388706,
            0.55415388706,
            "temporal",
        ),
        (
            "us-code-7-377-7ff6209555454049",
            "temporal",
            "frame",
            -0.351766688361,
            0.501766688361,
            "deontic",
        ),
        (
            "us-code-22-262s-1-17d49052e5816f6e",
            "temporal",
            "deontic",
            -0.246828388416,
            0.396828388416,
            "frame",
        ),
        (
            "us-code-50-4824.-b213a90e5a97f65a",
            "temporal",
            "deontic",
            -0.281085344843,
            0.431085344843,
            "frame",
        ),
        (
            "us-code-42-6003.-8065a6372d768590",
            "temporal",
            "temporal",
            0.016612705494,
            0.133387294506,
            "deontic",
        ),
    ),
)
def test_compiler_preserves_packet_000614_compiler_ambiguity_policy_margins(
    monkeypatch: pytest.MonkeyPatch,
    sample_id: str,
    predicted_family: str,
    target_family: str,
    family_margin: float,
    priority: float,
    runner_up_family: str,
) -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="regex")
    )
    monkeypatch.setattr(
        modal_compiler_module,
        "ranked_modal_families",
        lambda _encoding: [],
    )
    monkeypatch.setattr(
        modal_compiler_module,
        "modal_ambiguity_signals",
        lambda _encoding: {},
    )
    ranking = _adaptive_ranking_for_margin(
        predicted_family=predicted_family,
        target_family=target_family,
        family_margin=family_margin,
        runner_up_family=runner_up_family,
    )
    compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
        lambda _encoding, ranking=ranking: list(ranking)
    )

    result = compiler.compile(
        "As provided in section 3, the Secretary shall act by June 1, 2030.",
        document_id=f"compiler-ambiguity-packet-000614-{sample_id}",
    )
    ambiguity = _adaptive_explicit_ambiguity_from_source(
        result,
        predicted_family=predicted_family,
        target_family=target_family,
        predicted_family_source="adaptive_logits_fallback",
    )

    margin_direction = "contested" if family_margin > 0.0 else "outvoted"
    expected_type = (
        f"adaptive_{predicted_family}_{target_family}_{margin_direction}_margin_low"
    )
    expected_severity = "review" if margin_direction == "contested" else "requires_rule"
    assert ambiguity is not None, sample_id
    assert ambiguity.ambiguity_type == expected_type
    assert ambiguity.severity == expected_severity
    assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
    assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
    assert ambiguity.metadata.get("explicit_ambiguity_type") == expected_type
    assert (
        abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin)
        <= 1e-12
    )
    assert abs(float(ambiguity.metadata.get("priority", 0.0)) - priority) <= 1e-12
    assert abs(float(ambiguity.metadata.get("adaptive_priority", 0.0)) - priority) <= (
        1e-12
    )
