from __future__ import annotations

from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    uscode_modal_daemon_runner as runner,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_metric_lineage import (
    DETERMINISTIC_COMPILER_IR_METRIC_PATH,
    LEARNED_IR_METRIC_PATH,
    LegalIRMetricCacheReuseError,
    LegalIRMetricInvariantError,
    assert_metric_path_responsiveness,
    metric_lineage_from_block,
    reject_unexplained_invariant_metrics,
    require_cache_lineage,
)


def _sample(text: str = "A person shall report a material change.") -> SimpleNamespace:
    return SimpleNamespace(
        citation="1 USC 1",
        embedding_model="unit",
        embedding_vector=[0.2, 0.8],
        sample_id="sample-1",
        section="1",
        source="unit-test",
        text=text,
        title="Title 1",
    )


def _learned_eval(
    *,
    ce: float,
    cosine_gap: float,
    predicted_deontic: float,
) -> SimpleNamespace:
    return SimpleNamespace(
        decoded_embeddings={"sample-1": [0.1, 0.9]},
        legal_ir_losses={
            "legal_ir_view_cross_entropy_loss": ce,
            "legal_ir_view_family_cross_entropy_excess_loss": max(0.0, ce - 0.1),
            "legal_ir_view_family_cosine_gap_loss": cosine_gap,
            "legal_ir_view_family_deontic_cross_entropy_excess_loss": max(
                0.0,
                ce - 0.1,
            ),
            "legal_ir_view_family_deontic_cosine_gap_loss": cosine_gap,
        },
        legal_ir_predicted_view_distribution={
            "deontic.ir": predicted_deontic,
            "modal.frame_logic": 1.0 - predicted_deontic,
        },
        legal_ir_target_count=1,
        legal_ir_target_hashes={"sample-1": "target-a"},
        legal_ir_view_distribution={"deontic.ir": 1.0},
    )


class _Codec:
    def __init__(self, *, mutation: str, ce: float, cosine: float) -> None:
        self.calls = 0
        self.config = SimpleNamespace(mutation=mutation)
        self._ce = ce
        self._cosine = cosine

    def encode(self, *_args, **_kwargs) -> SimpleNamespace:
        self.calls += 1
        return SimpleNamespace(
            decoded_modal_text="report obligation",
            frame_candidates=["deontic"],
            kg_triples=[],
            losses={
                "cosine_similarity": self._cosine,
                "cross_entropy_loss": self._ce,
                "source_copy_reward_hack_penalty": 0.0,
                "structural_text_reconstruction_loss": 0.1,
                "symbolic_validity_penalty": 0.0,
            },
            metadata={"legal_ir_view_families": ["deontic"], "llm_call_count": 0},
            modal_ir=SimpleNamespace(formulas=["Obligation(report)"]),
        )


def _compiler_block(codec: _Codec, *, compiler_commit: str = "compiler-a") -> dict:
    return runner.compiler_ir_metric_block(
        [_sample()],
        codec,
        compiler_commit=compiler_commit,
        evaluation_role="validation",
        metric_schema="metric-schema-a",
        sample_timeout_seconds=0.0,
        state_hash="deterministic-state",
    )


def test_learned_head_perturbation_moves_only_learned_metrics(monkeypatch) -> None:
    monkeypatch.setattr(runner, "_read_metric_disk_cache", lambda *_args: None)
    monkeypatch.setattr(runner, "_write_metric_disk_cache", lambda *_args: None)

    learned_before = runner.learned_ir_metric_block(
        _learned_eval(ce=0.4, cosine_gap=0.25, predicted_deontic=0.55),
        samples=[_sample()],
        state_hash="learned-head-a",
    )
    learned_after = runner.learned_ir_metric_block(
        _learned_eval(ce=0.2, cosine_gap=0.05, predicted_deontic=0.9),
        samples=[_sample()],
        state_hash="learned-head-b",
    )
    assert_metric_path_responsiveness(
        learned_before,
        learned_after,
        expected_path=LEARNED_IR_METRIC_PATH,
        moved_metric_names=("view_cross_entropy_loss", "view_cosine_similarity"),
    )

    compiler_before = _compiler_block(_Codec(mutation="same", ce=0.31, cosine=0.77))
    compiler_after = _compiler_block(_Codec(mutation="same", ce=0.31, cosine=0.77))
    assert metric_lineage_from_block(compiler_before).path == (
        DETERMINISTIC_COMPILER_IR_METRIC_PATH
    )
    assert (
        compiler_before["compiler_ir_cross_entropy_loss"]
        == compiler_after["compiler_ir_cross_entropy_loss"]
    )
    assert (
        compiler_before["compiler_ir_cosine_similarity"]
        == compiler_after["compiler_ir_cosine_similarity"]
    )


def test_deterministic_compiler_mutation_moves_only_compiler_metrics(monkeypatch) -> None:
    monkeypatch.setattr(runner, "_read_metric_disk_cache", lambda *_args: None)
    monkeypatch.setattr(runner, "_write_metric_disk_cache", lambda *_args: None)

    compiler_before = _compiler_block(
        _Codec(mutation="baseline", ce=0.45, cosine=0.52),
        compiler_commit="compiler-before",
    )
    compiler_after = _compiler_block(
        _Codec(mutation="deterministic-rule", ce=0.18, cosine=0.84),
        compiler_commit="compiler-after",
    )
    assert_metric_path_responsiveness(
        compiler_before,
        compiler_after,
        expected_path=DETERMINISTIC_COMPILER_IR_METRIC_PATH,
        moved_metric_names=(
            "compiler_ir_cross_entropy_loss",
            "compiler_ir_cosine_similarity",
        ),
    )

    learned_before = runner.learned_ir_metric_block(
        _learned_eval(ce=0.4, cosine_gap=0.2, predicted_deontic=0.7),
        samples=[_sample()],
        state_hash="learned-stable",
    )
    learned_after = runner.learned_ir_metric_block(
        _learned_eval(ce=0.4, cosine_gap=0.2, predicted_deontic=0.7),
        samples=[_sample()],
        state_hash="learned-stable",
    )
    assert learned_before["view_cross_entropy_loss"] == learned_after["view_cross_entropy_loss"]
    assert (
        metric_lineage_from_block(learned_before).digest
        == metric_lineage_from_block(learned_after).digest
    )


def test_unexplained_invariant_metrics_across_material_states_are_rejected() -> None:
    before = runner.learned_ir_metric_block(
        _learned_eval(ce=0.3, cosine_gap=0.1, predicted_deontic=0.8),
        samples=[_sample()],
        state_hash="state-a",
    )
    invariant_after = runner.learned_ir_metric_block(
        _learned_eval(ce=0.3, cosine_gap=0.1, predicted_deontic=0.8),
        samples=[_sample()],
        state_hash="state-b",
    )

    with pytest.raises(LegalIRMetricInvariantError):
        reject_unexplained_invariant_metrics(
            before,
            invariant_after,
            metric_names=("view_cross_entropy_loss", "view_cosine_similarity"),
        )

    explained = dict(invariant_after)
    explained["metric_invariance_explanation"] = "deadband accepted by canary"
    reject_unexplained_invariant_metrics(
        before,
        explained,
        metric_names=("view_cross_entropy_loss", "view_cosine_similarity"),
    )


def test_stale_or_cross_path_cache_reuse_is_prevented(monkeypatch) -> None:
    learned_cached = runner.learned_ir_metric_block(
        _learned_eval(ce=0.3, cosine_gap=0.1, predicted_deontic=0.8),
        samples=[_sample()],
        state_hash="learned-cache",
    )
    expected_compiler = _compiler_block(_Codec(mutation="expected", ce=0.2, cosine=0.8))

    with pytest.raises(LegalIRMetricCacheReuseError):
        require_cache_lineage(learned_cached, metric_lineage_from_block(expected_compiler))

    stale_reads = []

    def stale_read(kind: str, key: str):
        stale_reads.append((kind, key))
        return learned_cached

    codec = _Codec(mutation="fresh", ce=0.22, cosine=0.82)
    monkeypatch.setattr(runner, "_read_metric_disk_cache", stale_read)
    monkeypatch.setattr(runner, "_write_metric_disk_cache", lambda *_args: None)

    recomputed = _compiler_block(codec)

    assert stale_reads
    assert codec.calls == 1
    assert recomputed["persistent_cache_hit"] is False
    assert metric_lineage_from_block(recomputed).path == (DETERMINISTIC_COMPILER_IR_METRIC_PATH)


# Fictional cache metadata only; no new source, proof or admission authority.
def _malformed_metric_cache_lineage_fixture():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_metric_lineage import (
        DETERMINISTIC_COMPILER_IR_METRIC_PATH, LegalIRMetricLineage,
    )

    return LegalIRMetricLineage(
        path=DETERMINISTIC_COMPILER_IR_METRIC_PATH,
        sample_hashes=("fictional-sample-content",),
        state_hash="fictional-state", compiler_commit="fictional-compiler",
        metric_schema="fictional-metric-schema", target_hash="fictional-target",
        cache_namespace="compiler_ir_metric_block", cache_key="fictional-cache-key",
        config_hash="fictional-config",
    )


@pytest.mark.parametrize("field,value", [
    ("schema_version", "obsolete-metric-lineage-schema"),
    ("config_hash", ""),
    ("config_hash", "invalid\nidentity"),
    ("sample_hashes", 17),
], ids=["stale-schema", "empty-identity", "newline-identity", "noniterable-hashes"])
def test_malformed_metric_lineage_is_a_cache_miss(field, value):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_metric_lineage import (
        metric_lineage_matches_block,
    )

    expected = _malformed_metric_cache_lineage_fixture()
    wire = expected.to_dict()
    wire[field] = value
    assert metric_lineage_matches_block({"metric_lineage": wire}, expected) is False


@pytest.mark.parametrize("field,value", [
    ("schema_version", "obsolete-metric-lineage-schema"),
    ("config_hash", ""),
    ("config_hash", "invalid\nidentity"),
    ("sample_hashes", 17),
], ids=["stale-schema", "empty-identity", "newline-identity", "noniterable-hashes"])
def test_malformed_metric_lineage_uses_typed_cache_reuse_error(field, value):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_metric_lineage import (
        LegalIRMetricCacheReuseError, require_cache_lineage,
    )

    expected = _malformed_metric_cache_lineage_fixture()
    wire = expected.to_dict()
    wire[field] = value
    with pytest.raises(LegalIRMetricCacheReuseError):
        require_cache_lineage({"metric_lineage": wire}, expected)


def test_valid_metric_lineage_remains_reusable():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_metric_lineage import (
        metric_lineage_matches_block, require_cache_lineage,
    )

    expected = _malformed_metric_cache_lineage_fixture()
    block = {"metric_lineage": expected.to_dict()}
    assert metric_lineage_matches_block(block, expected) is True
    assert require_cache_lineage(block, expected) is None


def test_metric_lineage_constructor_still_rejects_stale_schema():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_metric_lineage import (
        LegalIRMetricLineage,
    )

    wire = _malformed_metric_cache_lineage_fixture().to_dict()
    wire["schema_version"] = "obsolete-metric-lineage-schema"
    with pytest.raises(ValueError, match="schema version is stale"):
        LegalIRMetricLineage.from_mapping(wire)


def test_metric_lineage_matcher_preserves_unexpected_programming_errors():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_metric_lineage import (
        metric_lineage_matches_block,
    )

    class BrokenMapping(dict):
        def get(self, *_args, **_kwargs):
            raise RuntimeError("fictional mapping implementation fault")

    with pytest.raises(RuntimeError, match="mapping implementation fault"):
        metric_lineage_matches_block(BrokenMapping(), _malformed_metric_cache_lineage_fixture())


@pytest.mark.parametrize("field,value", [
    ("schema_version", "obsolete-metric-lineage-schema"),
    ("config_hash", ""),
    ("config_hash", "invalid\nidentity"),
    ("sample_hashes", 17),
], ids=["stale-schema", "empty-identity", "newline-identity", "noniterable-hashes"])
def test_malformed_persistent_metric_lineage_recomputes_with_existing_codec(monkeypatch, field, value):
    # Reuse the existing fake disk boundary and _Codec fixture; lineage parsing
    # and the full compiler metric/recomputation path remain the real owners.
    monkeypatch.setattr(runner, "_read_metric_disk_cache", lambda *_args: None)
    monkeypatch.setattr(runner, "_write_metric_disk_cache", lambda *_args: None)
    cached = _compiler_block(_Codec(mutation="same", ce=0.22, cosine=0.82))
    cached["metric_lineage"][field] = value
    reads = []

    def malformed_read(kind, key):
        reads.append((kind, key))
        return cached if kind == "compiler_ir_metric_block" else None

    monkeypatch.setattr(runner, "_read_metric_disk_cache", malformed_read)
    codec = _Codec(mutation="same", ce=0.22, cosine=0.82)
    recomputed = _compiler_block(codec)
    assert reads
    assert codec.calls == 1
    assert recomputed["persistent_cache_hit"] is False
    assert metric_lineage_from_block(recomputed).path == DETERMINISTIC_COMPILER_IR_METRIC_PATH
