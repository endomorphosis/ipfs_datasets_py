"""Regression evidence for non-vacuous semantic-quality eligibility."""

from __future__ import annotations

import pytest

from benchmarks.logic_pipeline import pilot_reassessment


def _zero_quality() -> dict[str, dict[str, object]]:
    return {
        variant_id: {
            "representative_variant_id": representative,
            "observation_count": 40,
            "rate": 0.0,
            "complete": True,
            "validator_receipt_set_sha256": "a" * 64,
        }
        for variant_id, representative in (
            pilot_reassessment._FRONTEND_REPRESENTATIVE.items()
        )
    }


def _published_observations() -> list[dict[str, object]]:
    matrix = pilot_reassessment.validate_reassessment_matrix(
        repository_root=pilot_reassessment.REPOSITORY_ROOT,
        run_id=pilot_reassessment.PILOT_REASSESSMENT_RUN_ID,
        output_root=pilot_reassessment._PUBLISHED_LAYOUT.matrix_root,
        snapshot_path=(
            pilot_reassessment._PUBLISHED_LAYOUT.matrix_snapshot
        ),
    )
    return pilot_reassessment._result_observations(
        pilot_reassessment.REPOSITORY_ROOT,
        matrix,
        matrix_index=pilot_reassessment._PUBLISHED_LAYOUT.matrix_index,
        run_id=pilot_reassessment.PILOT_REASSESSMENT_RUN_ID,
    )


def test_complete_all_zero_semantic_quality_is_hard_ineligible() -> None:
    candidates, _ = pilot_reassessment._candidate_metrics(
        _published_observations(),
        semantic_quality=_zero_quality(),
    )

    assert all(candidate["eligible"] is False for candidate in candidates)
    assert all(
        "no independently validated semantic-quality success"
        in candidate["ineligibility_reasons"]
        for candidate in candidates
    )
    assert (
        pilot_reassessment._pareto(candidates)[
            "eligible_nondominated_candidate_ids"
        ]
        == []
    )


def test_builder_keeps_holdout_sealed_for_complete_all_zero_quality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quality = _zero_quality()

    def zero_semantic_evidence(
        *_args: object, **_kwargs: object
    ) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
        return quality, {
            "kind": "test-calibrated-zero-semantic-receipts",
            "path": "test-only",
            "schema": "test.semantic-receipts.v1",
            "bytes_sha256": "b" * 64,
            "semantic_sha256": "c" * 64,
            "run_id": pilot_reassessment.PILOT_REASSESSMENT_RUN_ID,
            "source_validated": True,
            "semantic_quality_observation_count": 240,
            "semantic_quality_rate": 0.0,
        }

    monkeypatch.setattr(
        pilot_reassessment,
        "_semantic_quality_evidence",
        zero_semantic_evidence,
    )

    report = pilot_reassessment.build_pilot_reassessment_report()

    assert report["shortlist"]["selected_variant_ids"] == []
    assert report["holdout"]["authorized"] is False
    assert report["holdout"]["authorization_sha256"] is None
    assert report["decision"]["holdout_authorized"] is False
    assert any(
        item["priority"] == 4
        and item["scope"] == list(pilot_reassessment._CANDIDATE_IDS)
        and "semantic reconstruction" in item["action"]
        for item in report["remediation"]
    )
