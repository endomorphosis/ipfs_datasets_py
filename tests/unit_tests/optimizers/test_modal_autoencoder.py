import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    COMPILER_ACTIONABLE_FEATURE_GROUPS,
    AdaptiveModalAutoencoder,
)


def _sample(section: str, text: str):
    return build_us_code_sample(title="5", section=section, text=text)


def _teach_compiler_contract(autoencoder: AdaptiveModalAutoencoder, *samples) -> None:
    for sample in samples:
        for feature in autoencoder._compiler_contract_feature_keys_for(sample)[:6]:
            autoencoder.state.feature_family_logits.setdefault(feature, {})[
                "deontic"
            ] = 3.0


def test_causal_feature_attribution_reports_group_deltas_and_minimal_pairs():
    sample = _sample(
        "552",
        "The agency shall provide notice before final action.",
    )
    autoencoder = AdaptiveModalAutoencoder(feature_family_logit_scale=2.0)
    _teach_compiler_contract(autoencoder, sample)
    autoencoder.state.family_logits[sample.sample_id] = {"temporal": 100.0}

    report = autoencoder.causal_feature_attribution_for_sample(sample, top_k=5)

    assert report["sample_memory_used"] is False
    assert set(report["feature_group_ablations"]) == set(
        COMPILER_ACTIONABLE_FEATURE_GROUPS
    )
    compiler_contract = report["feature_group_ablations"]["compiler-contract"]
    assert compiler_contract["sample_memory_used"] is False
    assert compiler_contract["removed_feature_count"] > 0
    assert compiler_contract["metric_delta"][
        "compiler_ir_cross_entropy_excess_loss"
    ] > 0.0
    assert "compiler_ir_cosine_similarity" in compiler_contract["metric_delta"]
    assert "learned_view_cross_entropy_loss" in compiler_contract["metric_delta"]
    assert "decompiler_token_loss" in compiler_contract["metric_delta"]
    assert "formal_validity" in compiler_contract["metric_delta"]
    assert compiler_contract["directional_effect"]["objective_delta"] > 0.0

    assert report["legal_minimal_pair_probes"]
    pair = report["legal_minimal_pair_probes"]["compiler-contract"]
    assert pair["sample_memory_used"] is False
    assert pair["pair_sample_hash"]
    assert pair["transformation"]
    assert "compiler_ir_cross_entropy_loss" in pair["pair_metric_delta"]


def test_compiler_actionable_requires_recurrence_and_frozen_holdout():
    train_a = _sample("552", "The agency shall provide notice before final action.")
    train_b = _sample("553", "The Secretary shall issue notice before a hearing.")
    holdout = _sample("554", "The agency shall grant notice before final action.")
    autoencoder = AdaptiveModalAutoencoder(feature_family_logit_scale=2.0)
    _teach_compiler_contract(autoencoder, train_a, train_b, holdout)

    without_holdout = autoencoder.causal_feature_attribution(
        [train_a, train_b],
        min_recurrence=1.0,
    )
    assert "compiler-contract" not in without_holdout[
        "compiler_actionable_feature_groups"
    ]

    with_holdout = autoencoder.causal_feature_attribution(
        [train_a, train_b],
        frozen_holdout_samples=[holdout],
        min_recurrence=1.0,
    )

    assert with_holdout["sample_memory_used"] is False
    assert with_holdout["frozen_holdout_sample_count"] == 1
    assert "compiler-contract" in with_holdout["compiler_actionable_feature_groups"]
    compiler_contract = with_holdout["feature_group_actionability"][
        "compiler-contract"
    ]
    assert compiler_contract["recurrence_ratio"] == pytest.approx(1.0)
    assert compiler_contract["frozen_holdout_positive_count"] == 1
