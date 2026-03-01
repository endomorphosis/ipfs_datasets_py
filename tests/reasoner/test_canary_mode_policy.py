from __future__ import annotations

from ipfs_datasets_py.processors.legal_data.reasoner.shadow_mode import build_canary_mode_decision


def _audit(*, shadow_ready: bool, failure_count: int) -> dict:
    return {
        "summary": {
            "shadow_ready": shadow_ready,
            "failure_count": failure_count,
            "check_count": 7,
        }
    }


def test_canary_mode_low_risk_requires_shadow_ready_by_default() -> None:
    decision = build_canary_mode_decision(_audit(shadow_ready=False, failure_count=1), risk_level="low")
    assert decision["route"] == "baseline"
    assert decision["hybrid_enabled"] is False
    assert decision["proof_audit_required"] is True


def test_canary_mode_low_risk_can_override_shadow_ready_requirement() -> None:
    decision = build_canary_mode_decision(
        _audit(shadow_ready=False, failure_count=1),
        risk_level="low",
        require_shadow_ready=False,
    )
    assert decision["route"] == "hybrid"
    assert decision["hybrid_enabled"] is True
    assert decision["proof_audit_sample_size"] == 10


def test_canary_mode_medium_and_high_risk_policy() -> None:
    medium_pass = build_canary_mode_decision(_audit(shadow_ready=True, failure_count=0), risk_level="medium")
    medium_fail = build_canary_mode_decision(_audit(shadow_ready=False, failure_count=1), risk_level="medium")
    high = build_canary_mode_decision(_audit(shadow_ready=True, failure_count=0), risk_level="high")

    assert medium_pass["route"] == "hybrid"
    assert medium_fail["route"] == "baseline"
    assert high["route"] == "baseline"
