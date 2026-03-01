from __future__ import annotations

from ipfs_datasets_py.processors.legal_data.reasoner.optimizer_policy import build_optimizer_chain_plan


def _decision(accepted: bool) -> dict:
    return {
        "summary": {
            "accepted": accepted,
            "check_count": 3,
            "failure_count": 0 if accepted else 2,
        },
        "checks": [
            {"type": "modality_floor", "modality": "deontic", "passed": accepted},
            {"type": "modality_floor", "modality": "fol", "passed": accepted},
        ],
    }


def test_optimizer_chain_plan_enables_both_stages_when_policy_accepted() -> None:
    plan = build_optimizer_chain_plan(_decision(True))

    assert plan["summary"]["post_parse_enabled"] is True
    assert plan["summary"]["post_compile_enabled"] is True
    assert plan["env"]["ENABLE_POST_PARSE_OPTIMIZERS"] == "1"
    assert plan["env"]["ENABLE_POST_COMPILE_OPTIMIZERS"] == "1"


def test_optimizer_chain_plan_disables_post_compile_when_policy_rejected() -> None:
    plan = build_optimizer_chain_plan(_decision(False))

    assert plan["summary"]["post_parse_enabled"] is True
    assert plan["summary"]["post_compile_enabled"] is False
    assert plan["notes"]["reason"] == "policy_rejected_post_compile_disabled"
    assert plan["env"]["ENABLE_POST_COMPILE_OPTIMIZERS"] == "0"
