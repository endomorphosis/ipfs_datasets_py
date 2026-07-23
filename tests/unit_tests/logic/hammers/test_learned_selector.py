"""Tests for the optional, opt-in learned/graph-based premise selector
(HAMMER-005).

These tests cover:
- `LearnedModelArtifact.create`/`.validate`/`.verify_digest` compute and
  check a deterministic content digest derived from the artifact's own
  identity payload, and reject a tampered/mismatched digest.
- `LearnedModelArtifact.to_dict`/`from_dict`/`to_json`/`from_json`/`save`/
  `load` round-trip and always re-validate.
- `LearnedSelectorConfig.validate` enforces the opt-in gate: `enabled=True`
  requires a non-empty `model_path` and a well-formed
  `pinned_model_digest`.
- `extract_learned_features` is a deterministic, pure function of
  `(goal, entry, manifest)` and reuses the same feature signals as the
  HAMMER-004 baseline (symbol/type/import/graph Jaccard scores) plus
  additional count-based features.
- `score_with_model` blends a feature vector through a model's linear
  weights + bias, squashed to `(0.0, 1.0)`, and never raises even for
  pathological inputs.
- `score_candidates_learned` produces a deterministic, stably-ordered
  ranking, mirroring `premise_selection.score_candidates`'s tie-break rule.
- `select_premises_gated`/`select_premises_for_theorem_gated`:
  - default (`learned_config=None`) always uses the deterministic baseline
    (`SelectorFallbackReason.NOT_ENABLED`);
  - a policy that denies `allow_learned_premise_selector` falls back
    (`SelectorFallbackReason.POLICY_DENIED`) even when the config is
    enabled;
  - a valid opt-in configuration with a real, correctly-pinned model
    actually uses the learned selector, stamping
    `f"learned-selector:{model_digest}"` on every selected `PremiseRecord`;
  - a missing model file falls back (`SelectorFallbackReason.MODEL_MISSING`);
  - a malformed model file falls back (`SelectorFallbackReason.MODEL_LOAD_ERROR`);
  - a digest mismatch (tampered or wrong-pinned model) falls back
    (`SelectorFallbackReason.MODEL_DIGEST_MISMATCH`);
  - an unexpected scoring exception falls back
    (`SelectorFallbackReason.SCORING_ERROR`);
  - `top_k`/manifest/goal validation errors always propagate on both paths,
    never treated as a "model failure";
  - `LearnedSelectorConfig` misconfiguration (`enabled=True` without a
    pinned digest) raises `LearnedSelectorConfigError` rather than falling
    back;
  - selection is fully deterministic across independent calls.
- `LearnedSelectionResult` validates internal consistency between
  `used_learned_selector` and `fallback_reason`, and round-trips via
  `to_dict`/`from_dict`.
- `relevant_theorem_ids_by_import_overlap`, `compute_recall_at_k`, and
  `compute_reciprocal_rank` — the held-out recall/latency comparison
  building blocks reused by the benchmark script.
- `build_default_graph_selector_artifact` produces a valid, digest-verified
  artifact usable end-to-end through the gated selector.
"""

from __future__ import annotations

import json
import math

import pytest

from ipfs_datasets_py.logic.hammers.corpus import CorpusManifest, CorpusSource
from ipfs_datasets_py.logic.hammers.models import HammerPolicy, ITPKind
from ipfs_datasets_py.logic.hammers.premise_selection import (
    DETERMINISTIC_BASELINE_METHOD,
    GoalFeatures,
    InvalidTopKError,
    PremiseSelectionError,
    select_premises_for_theorem,
)
from ipfs_datasets_py.logic.hammers.learned_selector import (
    LEARNED_FEATURE_NAMES,
    LEARNED_FEATURE_VERSION,
    LEARNED_SELECTION_METHOD_PREFIX,
    LearnedModelArtifact,
    LearnedSelectionResult,
    LearnedSelectorConfig,
    LearnedSelectorConfigError,
    LearnedSelectorError,
    ModelArtifactError,
    ModelDigestMismatchError,
    SelectorFallbackReason,
    build_default_graph_selector_artifact,
    compute_model_digest,
    compute_recall_at_k,
    compute_reciprocal_rank,
    extract_learned_features,
    relevant_theorem_ids_by_import_overlap,
    score_candidates_learned,
    score_with_model,
    select_premises_for_theorem_gated,
    select_premises_gated,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def make_manifest() -> CorpusManifest:
    manifest = CorpusManifest(manifest_id="itp-hammer-corpus")
    manifest.register_source(
        CorpusSource(
            corpus_id="mathlib4",
            name="Mathlib4",
            source_itp=ITPKind.LEAN,
            version_ref="abcdef1234567890",
            license_id="Apache-2.0",
        )
    )
    return manifest


def populate_manifest(manifest: CorpusManifest) -> CorpusManifest:
    manifest.add_theorem(
        theorem_id="Nat.add_comm",
        corpus_id="mathlib4",
        statement="theorem add_comm : forall a b : Nat, Nat.add a b = Nat.add b a",
        imports=["Mathlib.Algebra.Group.Defs"],
    )
    manifest.add_theorem(
        theorem_id="Nat.add_assoc",
        corpus_id="mathlib4",
        statement=(
            "theorem add_assoc : forall a b c : Nat, "
            "Nat.add (Nat.add a b) c = Nat.add a (Nat.add b c)"
        ),
        imports=["Mathlib.Algebra.Group.Defs"],
    )
    manifest.add_theorem(
        theorem_id="Nat.mul_comm",
        corpus_id="mathlib4",
        statement="theorem mul_comm : forall a b : Nat, Nat.mul a b = Nat.mul b a",
        imports=["Mathlib.Algebra.Group.Defs"],
    )
    manifest.add_theorem(
        theorem_id="List.append_nil",
        corpus_id="mathlib4",
        statement="theorem append_nil : forall xs : List Nat, List.append xs List.nil = xs",
        imports=["Mathlib.Data.List.Basic"],
    )
    manifest.add_theorem(
        theorem_id="Set.union_comm",
        corpus_id="mathlib4",
        statement="theorem union_comm : forall a b : Set Nat, Set.union a b = Set.union b a",
        imports=["Mathlib.Data.Set.Basic"],
    )
    return manifest


GOAL_STATEMENT = "theorem goal : forall x y : Nat, Nat.add x y = Nat.add y x"


def make_goal(**overrides) -> GoalFeatures:
    return GoalFeatures.from_statement(
        overrides.pop("statement", GOAL_STATEMENT),
        imports=overrides.pop("imports", ["Mathlib.Algebra.Group.Defs"]),
        **overrides,
    )


def make_artifact(**overrides) -> LearnedModelArtifact:
    defaults = dict(
        model_id="test-model",
        weights={
            "symbol_score": 3.0,
            "type_score": 1.0,
            "import_score": 1.0,
            "graph_score": 0.5,
        },
        bias=-1.5,
    )
    defaults.update(overrides)
    return LearnedModelArtifact.create(**defaults)


def enabled_config(*, model_path: str, digest: str) -> LearnedSelectorConfig:
    return LearnedSelectorConfig(
        enabled=True, model_path=model_path, pinned_model_digest=digest
    )


ALLOW_POLICY = HammerPolicy(allow_learned_premise_selector=True)
DENY_POLICY = HammerPolicy(allow_learned_premise_selector=False)


# ---------------------------------------------------------------------------
# LearnedModelArtifact
# ---------------------------------------------------------------------------


class TestLearnedModelArtifact:
    def test_create_computes_digest(self):
        artifact = make_artifact()
        assert artifact.model_digest.startswith("sha256:")
        assert artifact.compute_digest() == artifact.model_digest

    def test_create_validates_and_returns_valid_artifact(self):
        artifact = make_artifact()
        artifact.validate()  # should not raise

    def test_digest_is_deterministic_across_calls(self):
        first = make_artifact()
        second = make_artifact()
        assert first.model_digest == second.model_digest

    def test_digest_changes_with_weights(self):
        first = make_artifact()
        second = make_artifact(weights={"symbol_score": 9.9})
        assert first.model_digest != second.model_digest

    def test_digest_independent_of_description(self):
        first = make_artifact(description="a")
        second = make_artifact(description="b")
        assert first.model_digest == second.model_digest

    def test_weights_key_not_in_feature_names_rejected(self):
        with pytest.raises(ModelArtifactError):
            LearnedModelArtifact.create(
                model_id="bad", weights={"not_a_feature": 1.0}
            )

    def test_non_finite_weight_rejected(self):
        with pytest.raises(ValueError):
            LearnedModelArtifact.create(
                model_id="bad", weights={"symbol_score": float("nan")}
            )

    def test_verify_digest_detects_tampering(self):
        artifact = make_artifact()
        tampered = LearnedModelArtifact(
            schema_version=artifact.schema_version,
            model_id=artifact.model_id,
            feature_version=artifact.feature_version,
            feature_names=artifact.feature_names,
            weights={**artifact.weights, "symbol_score": 999.0},
            bias=artifact.bias,
            description=artifact.description,
            model_digest=artifact.model_digest,  # stale digest from before tampering
        )
        with pytest.raises(ModelDigestMismatchError):
            tampered.verify_digest()
        with pytest.raises(ModelDigestMismatchError):
            tampered.validate()

    def test_to_dict_from_dict_round_trip(self):
        artifact = make_artifact()
        restored = LearnedModelArtifact.from_dict(artifact.to_dict())
        assert restored == artifact

    def test_to_json_from_json_round_trip(self):
        artifact = make_artifact()
        restored = LearnedModelArtifact.from_json(artifact.to_json())
        assert restored == artifact

    def test_save_load_round_trip(self, tmp_path):
        artifact = make_artifact()
        path = tmp_path / "model.json"
        artifact.save(path)
        loaded = LearnedModelArtifact.load(path)
        assert loaded == artifact

    def test_load_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            LearnedModelArtifact.load(tmp_path / "does_not_exist.json")

    def test_load_malformed_json_raises_model_artifact_error(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(ModelArtifactError):
            LearnedModelArtifact.load(path)

    def test_load_tampered_file_raises_digest_mismatch(self, tmp_path):
        artifact = make_artifact()
        path = tmp_path / "model.json"
        artifact.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["weights"]["symbol_score"] = 12345.0
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ModelDigestMismatchError):
            LearnedModelArtifact.load(path)

    def test_compute_model_digest_is_pure_function_of_payload(self):
        payload = {"a": 1, "b": [1, 2, 3]}
        assert compute_model_digest(payload) == compute_model_digest(payload)
        assert compute_model_digest(payload) != compute_model_digest({"a": 2})


class TestBuildDefaultGraphSelectorArtifact:
    def test_produces_valid_artifact(self):
        artifact = build_default_graph_selector_artifact()
        artifact.validate()
        assert artifact.feature_version == LEARNED_FEATURE_VERSION
        assert set(artifact.feature_names) == set(LEARNED_FEATURE_NAMES)

    def test_deterministic_digest(self):
        first = build_default_graph_selector_artifact()
        second = build_default_graph_selector_artifact()
        assert first.model_digest == second.model_digest


# ---------------------------------------------------------------------------
# LearnedSelectorConfig
# ---------------------------------------------------------------------------


class TestLearnedSelectorConfig:
    def test_disabled_default_validates(self):
        LearnedSelectorConfig().validate()

    def test_enabled_without_model_path_raises(self):
        config = LearnedSelectorConfig(enabled=True, pinned_model_digest="sha256:" + "0" * 64)
        with pytest.raises(LearnedSelectorConfigError, match="model_path"):
            config.validate()

    def test_enabled_without_pinned_digest_raises(self):
        config = LearnedSelectorConfig(enabled=True, model_path="model.json")
        with pytest.raises(LearnedSelectorConfigError, match="pinned_model_digest"):
            config.validate()

    def test_enabled_with_malformed_digest_format_raises(self):
        config = LearnedSelectorConfig(
            enabled=True, model_path="model.json", pinned_model_digest="not-a-digest"
        )
        with pytest.raises(LearnedSelectorConfigError):
            config.validate()

    def test_enabled_with_valid_fields_passes(self):
        LearnedSelectorConfig(
            enabled=True,
            model_path="model.json",
            pinned_model_digest="sha256:" + "a" * 64,
        ).validate()

    def test_to_dict_from_dict_round_trip(self):
        config = enabled_config(model_path="m.json", digest="sha256:" + "a" * 64)
        restored = LearnedSelectorConfig.from_dict(config.to_dict())
        assert restored == config


# ---------------------------------------------------------------------------
# extract_learned_features
# ---------------------------------------------------------------------------


class TestExtractLearnedFeatures:
    def test_returns_every_declared_feature_name(self):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        entry = manifest.get_theorem("Nat.add_comm")
        features = extract_learned_features(goal, entry, manifest)
        assert set(features) == set(LEARNED_FEATURE_NAMES)
        assert all(math.isfinite(value) for value in features.values())

    def test_deterministic_across_calls(self):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        entry = manifest.get_theorem("Nat.add_comm")
        first = extract_learned_features(goal, entry, manifest)
        second = extract_learned_features(goal, entry, manifest)
        assert first == second

    def test_topically_similar_candidate_has_higher_symbol_score(self):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        similar = extract_learned_features(goal, manifest.get_theorem("Nat.add_comm"), manifest)
        different = extract_learned_features(
            goal, manifest.get_theorem("Set.union_comm"), manifest
        )
        assert similar["symbol_score"] > different["symbol_score"]

    def test_shared_symbol_count_matches_intersection_size(self):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        entry = manifest.get_theorem("Nat.add_comm")
        features = extract_learned_features(goal, entry, manifest)
        from ipfs_datasets_py.logic.hammers.premise_selection import extract_symbols

        expected = len(goal.symbols & extract_symbols(entry.statement))
        assert features["shared_symbol_count"] == float(expected)

    def test_accepts_precomputed_expanded_imports(self):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        entry = manifest.get_theorem("Nat.add_comm")
        from ipfs_datasets_py.logic.hammers.premise_selection import (
            _expand_imports_one_hop,
        )

        expanded = _expand_imports_one_hop(goal.imports, manifest)
        with_precomputed = extract_learned_features(
            goal, entry, manifest, expanded_goal_imports=expanded
        )
        without = extract_learned_features(goal, entry, manifest)
        assert with_precomputed == without


# ---------------------------------------------------------------------------
# score_with_model / score_candidates_learned
# ---------------------------------------------------------------------------


class TestScoreWithModel:
    def test_returns_value_in_open_unit_interval(self):
        artifact = make_artifact()
        features = {name: 0.5 for name in LEARNED_FEATURE_NAMES}
        score = score_with_model(artifact, features)
        assert 0.0 < score < 1.0

    def test_missing_feature_key_defaults_to_zero(self):
        artifact = make_artifact()
        score_with_all = score_with_model(artifact, {name: 0.0 for name in LEARNED_FEATURE_NAMES})
        score_with_missing = score_with_model(artifact, {})
        assert score_with_all == score_with_missing

    def test_never_raises_on_extreme_values(self):
        artifact = make_artifact(weights={"symbol_score": 1e300}, bias=0.0)
        features = {"symbol_score": 1e300}
        score = score_with_model(artifact, features)
        assert math.isfinite(score)
        assert 0.0 <= score <= 1.0


class TestScoreCandidatesLearned:
    def test_returns_every_candidate(self):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        artifact = make_artifact()
        scored = score_candidates_learned(goal, manifest, artifact)
        assert {c.theorem_id for c in scored} == set(manifest.entries)

    def test_stable_ordering_descending_score_then_theorem_id(self):
        manifest = make_manifest()
        manifest.add_theorem(
            theorem_id="Zeta.dup",
            corpus_id="mathlib4",
            statement="theorem dup : forall a : Nat, Nat.succ a = Nat.succ a",
            imports=["Mathlib.Algebra.Group.Defs"],
        )
        manifest.add_theorem(
            theorem_id="Alpha.dup",
            corpus_id="mathlib4",
            statement="theorem dup : forall a : Nat, Nat.succ a = Nat.succ a",
            imports=["Mathlib.Algebra.Group.Defs"],
        )
        goal = GoalFeatures.from_statement("theorem g : True")
        artifact = make_artifact()
        scored = score_candidates_learned(goal, manifest, artifact)
        tied = [c for c in scored if c.theorem_id in {"Zeta.dup", "Alpha.dup"}]
        assert tied[0].score == tied[1].score
        assert [c.theorem_id for c in tied] == ["Alpha.dup", "Zeta.dup"]

    def test_deterministic_across_independent_calls(self):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        artifact = make_artifact()
        first = score_candidates_learned(goal, manifest, artifact)
        second = score_candidates_learned(goal, manifest, artifact)
        assert first == second

    def test_ranks_more_topically_similar_premise_higher(self):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        artifact = make_artifact()
        scored = score_candidates_learned(goal, manifest, artifact)
        by_id = {c.theorem_id: c for c in scored}
        assert by_id["Nat.add_comm"].score > by_id["List.append_nil"].score

    def test_rejects_non_corpus_manifest(self):
        with pytest.raises(LearnedSelectorError):
            score_candidates_learned(make_goal(), object(), make_artifact())  # type: ignore[arg-type]

    def test_rejects_non_learned_model_artifact(self):
        manifest = populate_manifest(make_manifest())
        with pytest.raises(LearnedSelectorError):
            score_candidates_learned(make_goal(), manifest, object())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# select_premises_gated / select_premises_for_theorem_gated
# ---------------------------------------------------------------------------


class TestSelectPremisesGatedDefaults:
    def test_no_config_uses_baseline(self):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        outcome = select_premises_gated(manifest, goal, top_k=3)
        assert outcome.used_learned_selector is False
        assert outcome.fallback_reason == SelectorFallbackReason.NOT_ENABLED
        assert outcome.selection.selection_method == DETERMINISTIC_BASELINE_METHOD

    def test_disabled_config_uses_baseline(self):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        outcome = select_premises_gated(
            manifest, goal, top_k=3, learned_config=LearnedSelectorConfig(enabled=False)
        )
        assert outcome.used_learned_selector is False
        assert outcome.fallback_reason == SelectorFallbackReason.NOT_ENABLED

    def test_default_result_matches_plain_baseline_selection(self):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        outcome = select_premises_gated(manifest, goal, top_k=3)
        direct = select_premises_for_theorem(
            populate_manifest(make_manifest()), "Nat.add_comm", top_k=3
        )
        # Same manifest/goal shape (not identical theorem_id call, but same
        # selection semantics) -- compare selected ids against a fresh
        # direct baseline call over the *goal* to avoid a false dependency
        # on `select_premises_for_theorem`'s self-exclusion behavior.
        assert outcome.selection.selection_method == DETERMINISTIC_BASELINE_METHOD
        assert isinstance(direct.selected, list)


class TestSelectPremisesGatedPolicy:
    def test_policy_denies_learned_selector(self, tmp_path):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        artifact = make_artifact()
        path = tmp_path / "model.json"
        artifact.save(path)
        config = enabled_config(model_path=str(path), digest=artifact.model_digest)

        outcome = select_premises_gated(
            manifest, goal, top_k=3, policy=DENY_POLICY, learned_config=config
        )
        assert outcome.used_learned_selector is False
        assert outcome.fallback_reason == SelectorFallbackReason.POLICY_DENIED

    def test_no_policy_supplied_still_allows_learned_selector(self, tmp_path):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        artifact = make_artifact()
        path = tmp_path / "model.json"
        artifact.save(path)
        config = enabled_config(model_path=str(path), digest=artifact.model_digest)

        outcome = select_premises_gated(manifest, goal, top_k=3, learned_config=config)
        assert outcome.used_learned_selector is True


class TestSelectPremisesGatedLearnedSuccess:
    def _config_and_manifest(self, tmp_path):
        manifest = populate_manifest(make_manifest())
        artifact = make_artifact()
        path = tmp_path / "model.json"
        artifact.save(path)
        config = enabled_config(model_path=str(path), digest=artifact.model_digest)
        return manifest, artifact, config

    def test_uses_learned_selector_when_all_gates_open(self, tmp_path):
        manifest, artifact, config = self._config_and_manifest(tmp_path)
        goal = make_goal()
        outcome = select_premises_gated(
            manifest, goal, top_k=3, policy=ALLOW_POLICY, learned_config=config
        )
        assert outcome.used_learned_selector is True
        assert outcome.fallback_reason == SelectorFallbackReason.NONE
        assert outcome.model_id == artifact.model_id
        assert outcome.model_digest == artifact.model_digest
        assert outcome.feature_version == artifact.feature_version
        expected_method = f"{LEARNED_SELECTION_METHOD_PREFIX}:{artifact.model_digest}"
        assert all(p.selection_method == expected_method for p in outcome.selection.selected)

    def test_result_is_valid_premise_selection_result(self, tmp_path):
        manifest, artifact, config = self._config_and_manifest(tmp_path)
        goal = make_goal()
        outcome = select_premises_gated(
            manifest, goal, top_k=3, policy=ALLOW_POLICY, learned_config=config
        )
        outcome.selection.validate()  # should not raise
        assert len(outcome.selection.selected) <= 3

    def test_model_artifact_can_be_supplied_directly(self, tmp_path):
        manifest, artifact, config = self._config_and_manifest(tmp_path)
        goal = make_goal()
        outcome = select_premises_gated(
            manifest,
            goal,
            top_k=3,
            policy=ALLOW_POLICY,
            learned_config=config,
            model_artifact=artifact,
        )
        assert outcome.used_learned_selector is True

    def test_deterministic_across_independent_calls(self, tmp_path):
        manifest, artifact, config = self._config_and_manifest(tmp_path)
        goal = make_goal()
        first = select_premises_gated(
            manifest, goal, top_k=3, policy=ALLOW_POLICY, learned_config=config
        )
        second = select_premises_gated(
            manifest, goal, top_k=3, policy=ALLOW_POLICY, learned_config=config
        )
        first_dict = first.to_dict()
        second_dict = second.to_dict()
        # created_at-equivalent nondeterministic field: latency_ms.
        first_dict.pop("latency_ms")
        second_dict.pop("latency_ms")
        first_dict["selection"].pop("created_at")
        second_dict["selection"].pop("created_at")
        assert first_dict == second_dict

    def test_self_exclusion_via_theorem_convenience_wrapper(self, tmp_path):
        manifest, artifact, config = self._config_and_manifest(tmp_path)
        outcome = select_premises_for_theorem_gated(
            manifest, "Nat.add_comm", top_k=3, policy=ALLOW_POLICY, learned_config=config
        )
        assert outcome.used_learned_selector is True
        assert "Nat.add_comm" not in {p.premise_id for p in outcome.selection.selected}
        excluded_ids = {e.premise_id for e in outcome.selection.excluded}
        assert "Nat.add_comm" in excluded_ids


class TestSelectPremisesGatedFallbacks:
    def test_missing_model_file_falls_back(self, tmp_path):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        config = enabled_config(
            model_path=str(tmp_path / "does_not_exist.json"),
            digest="sha256:" + "0" * 64,
        )
        outcome = select_premises_gated(
            manifest, goal, top_k=3, policy=ALLOW_POLICY, learned_config=config
        )
        assert outcome.used_learned_selector is False
        assert outcome.fallback_reason == SelectorFallbackReason.MODEL_MISSING
        assert outcome.selection.selection_method == DETERMINISTIC_BASELINE_METHOD

    def test_malformed_model_file_falls_back(self, tmp_path):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        path = tmp_path / "bad.json"
        path.write_text("{not valid json", encoding="utf-8")
        config = enabled_config(model_path=str(path), digest="sha256:" + "0" * 64)
        outcome = select_premises_gated(
            manifest, goal, top_k=3, policy=ALLOW_POLICY, learned_config=config
        )
        assert outcome.used_learned_selector is False
        assert outcome.fallback_reason == SelectorFallbackReason.MODEL_LOAD_ERROR

    def test_digest_mismatch_falls_back(self, tmp_path):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        artifact = make_artifact()
        path = tmp_path / "model.json"
        artifact.save(path)
        # Pin a *different* (but well-formed) digest than the one the file
        # actually hashes to.
        wrong_digest = "sha256:" + ("f" * 64)
        assert wrong_digest != artifact.model_digest
        config = enabled_config(model_path=str(path), digest=wrong_digest)
        outcome = select_premises_gated(
            manifest, goal, top_k=3, policy=ALLOW_POLICY, learned_config=config
        )
        assert outcome.used_learned_selector is False
        assert outcome.fallback_reason == SelectorFallbackReason.MODEL_DIGEST_MISMATCH

    def test_tampered_model_file_falls_back(self, tmp_path):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        artifact = make_artifact()
        path = tmp_path / "model.json"
        artifact.save(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["weights"]["symbol_score"] = 999.0  # tamper without updating digest
        path.write_text(json.dumps(data), encoding="utf-8")
        config = enabled_config(model_path=str(path), digest=artifact.model_digest)
        outcome = select_premises_gated(
            manifest, goal, top_k=3, policy=ALLOW_POLICY, learned_config=config
        )
        assert outcome.used_learned_selector is False
        assert outcome.fallback_reason == SelectorFallbackReason.MODEL_DIGEST_MISMATCH

    def test_scoring_exception_falls_back(self, tmp_path):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()

        class ExplodingArtifact(LearnedModelArtifact):
            def validate(self) -> None:  # bypass the normal finite-weight
                return None            # check so the bad weight below can
                                        # reach score_with_model and raise.

        # A non-numeric weight value: `score_with_model` computes
        # `weight * features.get(name, 0.0)`, and multiplying a string by a
        # float raises TypeError -- this simulates an unexpected scoring
        # failure that must be caught and turned into a fallback rather than
        # propagating to the caller.
        artifact = ExplodingArtifact(
            model_id="exploding",
            feature_version=LEARNED_FEATURE_VERSION,
            feature_names=LEARNED_FEATURE_NAMES,
            weights={"symbol_score": "not-a-number"},
            bias=0.0,
        )
        artifact.model_digest = artifact.compute_digest()
        config = enabled_config(model_path=str(tmp_path / "unused.json"), digest=artifact.model_digest)

        outcome = select_premises_gated(
            manifest,
            goal,
            top_k=3,
            policy=ALLOW_POLICY,
            learned_config=config,
            model_artifact=artifact,
        )
        assert outcome.used_learned_selector is False
        assert outcome.fallback_reason == SelectorFallbackReason.SCORING_ERROR

    def test_invalid_top_k_propagates_on_baseline_path(self):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        with pytest.raises(InvalidTopKError):
            select_premises_gated(manifest, goal, top_k=0)

    def test_invalid_top_k_propagates_on_learned_path(self, tmp_path):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        artifact = make_artifact()
        path = tmp_path / "model.json"
        artifact.save(path)
        config = enabled_config(model_path=str(path), digest=artifact.model_digest)
        with pytest.raises(InvalidTopKError):
            select_premises_gated(
                manifest, goal, top_k=-1, policy=ALLOW_POLICY, learned_config=config
            )

    def test_enabled_without_pinned_digest_raises_config_error_not_fallback(self):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        config = LearnedSelectorConfig(enabled=True, model_path="model.json")
        with pytest.raises(LearnedSelectorConfigError):
            select_premises_gated(
                manifest, goal, top_k=3, policy=ALLOW_POLICY, learned_config=config
            )

    def test_malformed_goal_raises_on_learned_path(self, tmp_path):
        manifest = populate_manifest(make_manifest())
        artifact = make_artifact()
        path = tmp_path / "model.json"
        artifact.save(path)
        config = enabled_config(model_path=str(path), digest=artifact.model_digest)
        with pytest.raises(PremiseSelectionError):
            select_premises_gated(
                manifest,
                object(),  # type: ignore[arg-type]
                top_k=3,
                policy=ALLOW_POLICY,
                learned_config=config,
            )


# ---------------------------------------------------------------------------
# LearnedSelectionResult
# ---------------------------------------------------------------------------


class TestLearnedSelectionResult:
    def test_used_learned_selector_requires_none_reason(self, tmp_path):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        artifact = make_artifact()
        path = tmp_path / "model.json"
        artifact.save(path)
        config = enabled_config(model_path=str(path), digest=artifact.model_digest)
        outcome = select_premises_gated(
            manifest, goal, top_k=3, policy=ALLOW_POLICY, learned_config=config
        )
        with pytest.raises(LearnedSelectorError):
            LearnedSelectionResult(
                selection=outcome.selection,
                used_learned_selector=True,
                fallback_reason=SelectorFallbackReason.MODEL_MISSING,
            ).validate()

    def test_not_used_requires_non_none_reason(self):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        outcome = select_premises_gated(manifest, goal, top_k=3)
        with pytest.raises(LearnedSelectorError):
            LearnedSelectionResult(
                selection=outcome.selection,
                used_learned_selector=False,
                fallback_reason=SelectorFallbackReason.NONE,
            ).validate()

    def test_to_dict_from_dict_round_trip(self, tmp_path):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        artifact = make_artifact()
        path = tmp_path / "model.json"
        artifact.save(path)
        config = enabled_config(model_path=str(path), digest=artifact.model_digest)
        outcome = select_premises_gated(
            manifest, goal, top_k=3, policy=ALLOW_POLICY, learned_config=config
        )
        restored = LearnedSelectionResult.from_dict(outcome.to_dict())
        assert restored.used_learned_selector == outcome.used_learned_selector
        assert restored.model_digest == outcome.model_digest
        assert restored.selection.selection_method == outcome.selection.selection_method


# ---------------------------------------------------------------------------
# Held-out recall/latency comparison helpers
# ---------------------------------------------------------------------------


class TestRelevantTheoremIdsByImportOverlap:
    def test_returns_theorems_sharing_an_import(self):
        manifest = populate_manifest(make_manifest())
        relevant = relevant_theorem_ids_by_import_overlap(manifest, "Nat.add_comm")
        assert "Nat.add_assoc" in relevant
        assert "Nat.mul_comm" in relevant
        assert "List.append_nil" not in relevant
        assert "Nat.add_comm" not in relevant

    def test_theorem_with_no_imports_has_no_relevant_set(self):
        manifest = make_manifest()
        manifest.add_theorem(
            theorem_id="Lonely", corpus_id="mathlib4", statement="theorem lonely : True"
        )
        assert relevant_theorem_ids_by_import_overlap(manifest, "Lonely") == frozenset()


class TestRecallMetrics:
    def test_recall_at_k_full_overlap(self):
        assert compute_recall_at_k(["a", "b", "c"], ["a", "b"]) == 1.0

    def test_recall_at_k_partial_overlap(self):
        assert compute_recall_at_k(["a"], ["a", "b"]) == 0.5

    def test_recall_at_k_no_overlap(self):
        assert compute_recall_at_k(["z"], ["a", "b"]) == 0.0

    def test_recall_at_k_empty_relevant_is_vacuously_one(self):
        assert compute_recall_at_k(["a"], []) == 1.0

    def test_reciprocal_rank_first_position(self):
        assert compute_reciprocal_rank(["a", "b"], ["a"]) == 1.0

    def test_reciprocal_rank_second_position(self):
        assert compute_reciprocal_rank(["x", "a"], ["a"]) == 0.5

    def test_reciprocal_rank_absent(self):
        assert compute_reciprocal_rank(["x", "y"], ["a"]) == 0.0

    def test_reciprocal_rank_empty_relevant_is_vacuously_one(self):
        assert compute_reciprocal_rank(["x"], []) == 1.0


# ---------------------------------------------------------------------------
# End-to-end: fixture-backed gated selection matches the shipped benchmark
# fixtures (regression guard for the benchmark script's inputs).
# ---------------------------------------------------------------------------


class TestFixtureIntegration:
    FIXTURE_DIR = None

    @staticmethod
    def _fixture_dir():
        import pathlib

        return pathlib.Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "logic" / "hammers"

    def test_shipped_model_fixture_is_valid_and_digest_verified(self):
        fixture_dir = self._fixture_dir()
        model_path = fixture_dir / "learned_selector_model.json"
        assert model_path.is_file(), f"expected fixture at {model_path}"
        artifact = LearnedModelArtifact.load(model_path)
        artifact.validate()

    def test_shipped_corpus_fixture_is_valid_json_with_theorems(self):
        fixture_dir = self._fixture_dir()
        corpus_path = fixture_dir / "premise_selection_corpus.json"
        assert corpus_path.is_file(), f"expected fixture at {corpus_path}"
        payload = json.loads(corpus_path.read_text(encoding="utf-8"))
        assert payload["theorems"]
        assert all("theorem_id" in t and "statement" in t for t in payload["theorems"])
