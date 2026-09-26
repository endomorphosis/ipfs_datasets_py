"""The daemon may reuse a bridge pass only when it evaluated full samples."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as model
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_todo_daemon as daemon
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner


@pytest.fixture(scope="module")
def samples():
    return [
        build_us_code_sample(title="gate", section=str(index), text=text)
        for index, text in enumerate(
            (
                "Company A shall submit backup report within 10 days unless emergency.",
                "The agency shall not disclose records.",
                "The officer shall retain the file for at least 20 days.",
            )
        )
    ]


@pytest.fixture
def target_calls(monkeypatch):
    """Use fixed targets to isolate evaluation reuse from bridge generation."""
    calls = []

    def target_items(rows, *, bridge_names=(), **kwargs):
        calls.append((list(rows), tuple(bridge_names), dict(kwargs)))
        if not bridge_names:
            return []
        return [
            (
                row.sample_id,
                SimpleNamespace(
                    losses={"bridge_loss": 0.4},
                    view_distribution={"deontic.ir": 0.8, "TDFOL.prover": 0.2},
                    document=SimpleNamespace(canonical_hash=lambda: "test-target-hash"),
                ),
            )
            for row in rows
        ]

    monkeypatch.setattr(model, "_legal_ir_target_items", target_items)
    return calls


def _evaluate(autoencoder, samples, *, bridge_names=("deontic_norms",), memory=False, cap=0):
    return runner.evaluate_autoencoder_with_bounded_metric_bridges(
        autoencoder,
        samples,
        legal_ir_bridge_names=bridge_names,
        legal_ir_evaluate_provers=False,
        legal_ir_parallel_workers=1,
        max_bridge_sample_text_chars=cap,
        use_sample_memory=memory,
    )


def _original_two_pass(autoencoder, samples, *, memory):
    bridge = autoencoder.evaluate(
        samples,
        legal_ir_bridge_names=("deontic_norms",),
        legal_ir_evaluate_provers=False,
        legal_ir_parallel_workers=1,
        use_sample_memory=memory,
    )
    autoencoder.alias_cached_legal_ir_targets(samples, samples)
    base = autoencoder.evaluate(samples, legal_ir_bridge_names=(), use_sample_memory=memory)
    return replace(
        base,
        legal_ir_target_count=bridge.legal_ir_target_count,
        legal_ir_losses=bridge.legal_ir_losses,
        legal_ir_predicted_view_distribution=bridge.legal_ir_predicted_view_distribution,
        legal_ir_target_hashes=bridge.legal_ir_target_hashes,
        legal_ir_grammar_rejection_reasons=bridge.legal_ir_grammar_rejection_reasons,
        legal_ir_view_distribution=bridge.legal_ir_view_distribution,
        legal_ir_view_family_metrics=bridge.legal_ir_view_family_metrics,
    )


@pytest.mark.parametrize("memory", [False, True])
@pytest.mark.parametrize("cap", [0, 200])
def test_full_sample_bridge_reuse_matches_all_two_pass_metrics(samples, target_calls, memory, cap):
    state = model.ModalAutoencoderTrainingState(
        decoded_embeddings={sample.sample_id: [0.25] * 8 for sample in samples},
        family_logits={sample.sample_id: {"deontic": 0.6} for sample in samples},
        legal_ir_view_logits={"deontic.ir": 0.7, "TDFOL.prover": 0.3},
        legal_ir_view_embedding_weights={"deontic.ir": [0.1] * 8},
        legal_ir_view_family_logits={"deontic.ir": {"deontic": 0.4}},
    )
    reference = model.AdaptiveModalAutoencoder(state=deepcopy(state))
    optimized = model.AdaptiveModalAutoencoder(state=deepcopy(state))
    expected = _original_two_pass(reference, samples, memory=memory)
    target_calls.clear()

    result = _evaluate(optimized, samples, memory=memory, cap=cap)

    assert result.to_dict() == expected.to_dict()
    assert result.legal_ir_target_count == len(samples)
    assert [call[1] for call in target_calls] == [("deontic_norms",)]
    assert target_calls[0][2]["evaluate_provers"] is False
    assert target_calls[0][2]["parallel_workers"] == 1
    assert optimized.state.to_dict() == state.to_dict()
    assert optimized._legal_ir_view_target_cache == reference._legal_ir_view_target_cache
    assert optimized._legal_ir_loss_target_cache == reference._legal_ir_loss_target_cache
    # Reuse does not leave stale feature selections for the next evaluation.
    assert optimized.evaluate(samples, use_sample_memory=memory) == reference.evaluate(
        samples, use_sample_memory=memory
    )


@pytest.mark.parametrize("bridge_names", [(), ("deontic_norms",)])
def test_bridge_off_and_empty_inputs_remain_truthful(samples, target_calls, bridge_names):
    rows = samples if not bridge_names else []
    result = _evaluate(model.AdaptiveModalAutoencoder(), rows, bridge_names=bridge_names)

    assert result.sample_count == len(rows)
    assert result.legal_ir_target_count == 0
    assert result.legal_ir_losses == {}
    assert not any(call[1] for call in target_calls)


def test_overridden_evaluator_retains_two_pass_adapter_contract(samples, target_calls):
    autoencoder = model.AdaptiveModalAutoencoder()
    native_evaluate = autoencoder.evaluate
    passes = []

    def evaluate(rows, **kwargs):
        result = native_evaluate(rows, **kwargs)
        passes.append(tuple(kwargs.get("legal_ir_bridge_names", ())))
        return replace(result, reconstruction_loss=float(len(passes)))

    autoencoder.evaluate = evaluate
    result = _evaluate(autoencoder, samples)

    assert passes == [("deontic_norms",), ()]
    assert result.reconstruction_loss == 2.0
    assert result.legal_ir_target_count == len(samples)


def test_custom_alias_hook_preserves_following_reconstruction_pass(samples, target_calls):
    autoencoder = model.AdaptiveModalAutoencoder()
    native_alias = autoencoder.alias_cached_legal_ir_targets

    def alias(rows, evaluated_rows):
        native_alias(rows, evaluated_rows)
        autoencoder.state.decoded_embeddings[samples[0].sample_id] = [0.125] * 8

    autoencoder.alias_cached_legal_ir_targets = alias
    result = _evaluate(autoencoder, samples, memory=True)

    assert [call[1] for call in target_calls] == [("deontic_norms",), ()]
    assert result.decoded_embeddings[samples[0].sample_id] == [0.125] * 8


def test_bounded_samples_keep_full_text_reconstruction_and_target_aliases(samples, target_calls):
    long_sample = replace(samples[0], text=" ".join([samples[0].text] * 5))
    rows = [long_sample, samples[1]]
    autoencoder = model.AdaptiveModalAutoencoder()

    result = _evaluate(autoencoder, rows, cap=80)

    assert len(target_calls) == 2
    bounded_rows, bridges, _ = target_calls[0]
    full_rows, base_bridges, _ = target_calls[1]
    assert bridges == ("deontic_norms",)
    assert base_bridges == ()
    assert len(bounded_rows[0].text) <= 80
    assert bounded_rows[0].sample_id != long_sample.sample_id
    assert full_rows == rows
    assert result.legal_ir_target_count == len(rows)
    assert set(result.decoded_embeddings) == {row.sample_id for row in rows}
    assert autoencoder._legal_ir_view_target_cache[long_sample.sample_id] == (
        autoencoder._legal_ir_view_target_cache[bounded_rows[0].sample_id]
    )
    repeated = autoencoder.evaluate(rows, legal_ir_bridge_names=(), use_sample_memory=False)
    assert result.decoded_embeddings == repeated.decoded_embeddings
    assert result.cross_entropy_loss == repeated.cross_entropy_loss


def test_supervisor_keeps_base_before_prefix_bridge(samples, target_calls):
    supervisor = SimpleNamespace(
        bridge_names=("deontic_norms",),
        bridge_metric_max_samples=1,
        bridge_evaluate_provers=False,
        bridge_parallel_workers=1,
    )
    result = daemon.ModalTodoSupervisor._autoencoder_evaluation(
        supervisor, model.AdaptiveModalAutoencoder(), samples, use_sample_memory=False
    )

    assert [call[1] for call in target_calls] == [(), ("deontic_norms",)]
    assert target_calls[0][0] == samples
    assert target_calls[1][0] == samples[:1]
    assert result.sample_count == len(samples)
    assert result.legal_ir_target_count == 1
