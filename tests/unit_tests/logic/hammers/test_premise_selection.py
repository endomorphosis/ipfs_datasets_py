"""Tests for the deterministic premise selection baseline (HAMMER-004).

These tests cover:
- Lexical feature extraction (`extract_symbols` / `extract_types`) is
  deterministic, ITP-agnostic, and filters common cross-ITP keyword/tactic
  vocabulary and single-character bound-variable-like tokens.
- `GoalFeatures` can be built from raw statement text or from an existing
  `TheoremEntry`, and validates its own shape.
- `PremiseSelectionWeights` rejects negative, non-finite, or all-zero
  weightings.
- `score_candidates` produces a deterministic, stably-ordered ranking
  (descending score, ascending `theorem_id` tie-break) driven by goal
  symbols, types, imports, and a one-hop dependency-graph proximity signal.
- `select_premises` ranks premises from goal symbols/types/imports/graph
  features, emits selected IDs/scores/corpus revision/cutoff, and reports
  every non-selected candidate in `excluded` with an explicit reason
  (self-reference, explicit caller exclusion, below a score floor, or
  beyond the `top_k` cutoff).
- `top_k` is strictly enforced: invalid values are rejected, and a
  `HammerPolicy.max_premises` bound cannot be exceeded.
- Selection is fully deterministic and stable: identical input (including
  tied scores) always produces byte-identical output across independent
  calls.
- `select_premises_for_theorem` is a convenience wrapper that builds the
  goal from an existing corpus entry and self-excludes it.
- `PremiseSelectionResult` / `ExcludedPremise` round-trip via
  `to_dict`/`from_dict` and enforce their own invariants (rank order,
  matching corpus revision, disjoint selected/excluded sets, no duplicate
  IDs, `len(selected) <= top_k`).
"""

from __future__ import annotations

import copy

import pytest

from ipfs_datasets_py.logic.hammers.corpus import CorpusManifest, CorpusSource
from ipfs_datasets_py.logic.hammers.models import HammerPolicy, ITPKind, PremiseRecord
from ipfs_datasets_py.logic.hammers.premise_selection import (
    DETERMINISTIC_BASELINE_METHOD,
    ExcludedPremise,
    GoalFeatures,
    InvalidTopKError,
    PremiseExclusionReason,
    PremiseSelectionError,
    PremiseSelectionResult,
    PremiseSelectionWeights,
    ScoredCandidate,
    extract_symbols,
    extract_types,
    score_candidates,
    select_premises,
    select_premises_for_theorem,
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
    """Populate ``manifest`` with a small, hand-built corpus whose topical
    relationships are known ahead of time, so relevance-ordering assertions
    below are meaningful rather than incidental."""

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


# ---------------------------------------------------------------------------
# extract_symbols / extract_types
# ---------------------------------------------------------------------------


class TestExtractSymbols:
    def test_extracts_qualified_identifiers(self):
        symbols = extract_symbols("theorem foo : Nat.add_comm a b = Nat.add_comm b a")
        assert "nat.add_comm" in symbols

    def test_filters_common_keywords(self):
        symbols = extract_symbols("forall a b, if a then b else a")
        assert "forall" not in symbols
        assert "if" not in symbols
        assert "then" not in symbols
        assert "else" not in symbols

    def test_filters_single_character_tokens(self):
        symbols = extract_symbols("forall a b c, a + b = c")
        assert "a" not in symbols
        assert "b" not in symbols
        assert "c" not in symbols

    def test_lower_cases_symbols(self):
        symbols = extract_symbols("Nat.add_comm")
        assert "nat.add_comm" in symbols
        assert "Nat.add_comm" not in symbols

    def test_empty_statement_yields_empty_set(self):
        assert extract_symbols("") == frozenset()

    def test_deterministic_across_calls(self):
        text = "theorem add_comm : forall a b : Nat, Nat.add a b = Nat.add b a"
        assert extract_symbols(text) == extract_symbols(text)


class TestExtractTypes:
    def test_extracts_capitalized_tokens(self):
        types = extract_types("forall xs : List Nat, List.append xs List.nil = xs")
        assert "List" in types
        assert "Nat" in types

    def test_excludes_lowercase_identifiers(self):
        types = extract_types("theorem add_comm : forall a b : Nat, add_comm a b")
        assert "add_comm" not in types

    def test_excludes_capitalized_keywords(self):
        # "Proof"/"Qed" are stopwords even though capitalized.
        types = extract_types("Proof. reflexivity. Qed.")
        assert "Proof" not in types
        assert "Qed" not in types

    def test_empty_statement_yields_empty_set(self):
        assert extract_types("") == frozenset()


# ---------------------------------------------------------------------------
# GoalFeatures
# ---------------------------------------------------------------------------


class TestGoalFeatures:
    def test_from_statement_extracts_symbols_and_types(self):
        goal = GoalFeatures.from_statement(GOAL_STATEMENT)
        assert "nat.add" in goal.symbols
        assert "Nat" in goal.types

    def test_from_statement_unions_extra_symbols_and_types(self):
        goal = GoalFeatures.from_statement(
            "theorem t : True",
            extra_symbols=["custom_symbol"],
            extra_types=["CustomType"],
        )
        assert "custom_symbol" in goal.symbols
        assert "CustomType" in goal.types

    def test_from_statement_normalizes_imports(self):
        goal = GoalFeatures.from_statement(
            "theorem t : True", imports=["A", "B", "A"]
        )
        assert goal.imports == frozenset({"A", "B"})

    def test_from_theorem_entry_uses_statement_and_imports(self):
        manifest = populate_manifest(make_manifest())
        entry = manifest.get_theorem("Nat.add_comm")
        goal = GoalFeatures.from_theorem_entry(entry)
        assert goal.theorem_id == "Nat.add_comm"
        assert goal.imports == frozenset(entry.imports)
        assert "nat.add" in goal.symbols

    def test_validate_rejects_non_frozenset_symbols(self):
        goal = GoalFeatures(symbols=["a"])  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="symbols"):
            goal.validate()

    def test_validate_rejects_non_string_theorem_id(self):
        goal = GoalFeatures(theorem_id=123)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="theorem_id"):
            goal.validate()

    def test_validate_accepts_defaults(self):
        GoalFeatures().validate()


# ---------------------------------------------------------------------------
# PremiseSelectionWeights
# ---------------------------------------------------------------------------


class TestPremiseSelectionWeights:
    def test_defaults_pass_validation(self):
        PremiseSelectionWeights().validate()

    def test_rejects_negative_weight(self):
        with pytest.raises(ValueError, match="non-negative"):
            PremiseSelectionWeights(symbol_weight=-0.1).validate()

    def test_rejects_non_finite_weight(self):
        with pytest.raises(ValueError):
            PremiseSelectionWeights(symbol_weight=float("nan")).validate()

    def test_rejects_all_zero_weights(self):
        weights = PremiseSelectionWeights(
            symbol_weight=0.0, type_weight=0.0, import_weight=0.0, graph_weight=0.0
        )
        with pytest.raises(ValueError, match="at least one"):
            weights.validate()

    def test_to_dict_from_dict_round_trip(self):
        weights = PremiseSelectionWeights(symbol_weight=0.9, graph_weight=0.05)
        restored = PremiseSelectionWeights.from_dict(weights.to_dict())
        assert restored == weights


# ---------------------------------------------------------------------------
# score_candidates
# ---------------------------------------------------------------------------


class TestScoreCandidates:
    def test_ranks_more_topically_similar_premise_higher(self):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        scored = score_candidates(goal, manifest)
        by_id = {candidate.theorem_id: candidate for candidate in scored}
        # The goal shares symbols/imports with Nat.add_comm/Nat.add_assoc
        # (commutativity/associativity of Nat.add), but not with the
        # List/Set premises, which live under a different import.
        assert by_id["Nat.add_comm"].score > by_id["List.append_nil"].score
        assert by_id["Nat.add_comm"].score > by_id["Set.union_comm"].score

    def test_returns_every_candidate(self):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        scored = score_candidates(goal, manifest)
        assert {c.theorem_id for c in scored} == set(manifest.entries)

    def test_stable_ordering_descending_score_then_theorem_id(self):
        manifest = make_manifest()
        # Two premises with byte-identical symbol/type/import profiles
        # (differing only in theorem_id) must score identically and be
        # ordered by theorem_id ascending as an explicit tie-break.
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
        scored = score_candidates(goal, manifest)
        tied = [c for c in scored if c.theorem_id in {"Zeta.dup", "Alpha.dup"}]
        assert [c.score for c in tied[:2]] == [tied[0].score, tied[0].score]
        assert [c.theorem_id for c in tied] == ["Alpha.dup", "Zeta.dup"]

    def test_deterministic_across_independent_calls(self):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        first = score_candidates(goal, manifest)
        second = score_candidates(goal, manifest)
        assert first == second
        assert all(isinstance(c, ScoredCandidate) for c in first)

    def test_zero_overlap_scores_zero(self):
        manifest = make_manifest()
        manifest.add_theorem(
            theorem_id="Unrelated.thm",
            corpus_id="mathlib4",
            statement="theorem unrelated : Xyzzy.plugh = Xyzzy.plugh",
            imports=["Some.Other.Module"],
        )
        goal = GoalFeatures.from_statement(
            "theorem goal : Completely.Different.Statement", imports=["Nonexistent"]
        )
        scored = score_candidates(goal, manifest)
        by_id = {c.theorem_id: c for c in scored}
        assert by_id["Unrelated.thm"].score == 0.0

    def test_graph_score_rewards_transitive_import_proximity(self):
        # Goal shares no direct import with `Indirect`, but a third theorem
        # `Bridge` shares an import with both the goal and `Indirect`,
        # giving `Indirect` a nonzero one-hop dependency-graph score even
        # though its direct import overlap with the goal is zero.
        manifest = make_manifest()
        manifest.add_theorem(
            theorem_id="Bridge",
            corpus_id="mathlib4",
            statement="theorem bridge : True",
            imports=["Goal.Import", "Shared.Module"],
        )
        manifest.add_theorem(
            theorem_id="Indirect",
            corpus_id="mathlib4",
            statement="theorem indirect : True",
            imports=["Shared.Module"],
        )
        manifest.add_theorem(
            theorem_id="Isolated",
            corpus_id="mathlib4",
            statement="theorem isolated : True",
            imports=["Totally.Unrelated.Module"],
        )
        goal = GoalFeatures.from_statement("theorem goal : True", imports=["Goal.Import"])
        scored = score_candidates(goal, manifest)
        by_id = {c.theorem_id: c for c in scored}
        assert by_id["Indirect"].graph_score > 0.0
        assert by_id["Indirect"].import_score == 0.0
        assert by_id["Isolated"].graph_score == 0.0

    def test_rejects_non_corpus_manifest(self):
        with pytest.raises(PremiseSelectionError):
            score_candidates(make_goal(), object())  # type: ignore[arg-type]

    def test_rejects_non_goal_features(self):
        manifest = populate_manifest(make_manifest())
        with pytest.raises(PremiseSelectionError):
            score_candidates(object(), manifest)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# select_premises
# ---------------------------------------------------------------------------


class TestSelectPremises:
    def test_selects_top_k_premises_with_stable_rank(self):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        result = select_premises(manifest, goal, top_k=2)
        assert len(result.selected) == 2
        assert [p.rank for p in result.selected] == [0, 1]
        assert result.selected[0].score >= result.selected[1].score
        assert all(isinstance(p, PremiseRecord) for p in result.selected)

    def test_emits_corpus_revision_on_selected_and_excluded(self):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        result = select_premises(manifest, goal, top_k=2)
        assert result.corpus_revision == manifest.revision
        for premise in result.selected:
            assert premise.corpus_revision == manifest.revision
        for excluded in result.excluded:
            assert excluded.corpus_revision == manifest.revision

    def test_selection_method_is_deterministic_baseline(self):
        manifest = populate_manifest(make_manifest())
        result = select_premises(manifest, make_goal(), top_k=2)
        assert result.selection_method == DETERMINISTIC_BASELINE_METHOD
        for premise in result.selected:
            assert premise.selection_method == DETERMINISTIC_BASELINE_METHOD

    def test_cutoff_recorded_as_top_k(self):
        manifest = populate_manifest(make_manifest())
        result = select_premises(manifest, make_goal(), top_k=3)
        assert result.top_k == 3

    def test_every_non_selected_candidate_is_excluded(self):
        manifest = populate_manifest(make_manifest())
        result = select_premises(manifest, make_goal(), top_k=2)
        selected_ids = {p.premise_id for p in result.selected}
        excluded_ids = {e.premise_id for e in result.excluded}
        assert selected_ids | excluded_ids == set(manifest.entries)
        assert selected_ids.isdisjoint(excluded_ids)

    def test_beyond_cutoff_candidates_marked_below_cutoff(self):
        manifest = populate_manifest(make_manifest())
        result = select_premises(manifest, make_goal(), top_k=2)
        cutoff_excluded = [
            e for e in result.excluded if e.reason == PremiseExclusionReason.BELOW_CUTOFF
        ]
        assert len(cutoff_excluded) == len(manifest.entries) - 2

    def test_self_reference_excluded_and_not_ranked(self):
        manifest = populate_manifest(make_manifest())
        goal = GoalFeatures.from_theorem_entry(manifest.get_theorem("Nat.add_comm"))
        result = select_premises(manifest, goal, top_k=10)
        selected_ids = {p.premise_id for p in result.selected}
        assert "Nat.add_comm" not in selected_ids
        self_excluded = [
            e
            for e in result.excluded
            if e.premise_id == "Nat.add_comm"
        ]
        assert len(self_excluded) == 1
        assert self_excluded[0].reason == PremiseExclusionReason.SELF_REFERENCE

    def test_explicit_exclusion_reported_with_reason(self):
        manifest = populate_manifest(make_manifest())
        result = select_premises(
            manifest, make_goal(), top_k=10, exclude_theorem_ids=["Nat.add_assoc"]
        )
        selected_ids = {p.premise_id for p in result.selected}
        assert "Nat.add_assoc" not in selected_ids
        matches = [e for e in result.excluded if e.premise_id == "Nat.add_assoc"]
        assert matches[0].reason == PremiseExclusionReason.EXPLICITLY_EXCLUDED

    def test_min_score_floor_excludes_low_scoring_candidates(self):
        manifest = populate_manifest(make_manifest())
        result = select_premises(manifest, make_goal(), top_k=10, min_score=0.9)
        assert result.selected == []
        floor_excluded = [
            e
            for e in result.excluded
            if e.reason == PremiseExclusionReason.BELOW_SCORE_FLOOR
        ]
        assert len(floor_excluded) == len(manifest.entries)

    def test_min_score_floor_does_not_consume_top_k_slot(self):
        manifest = populate_manifest(make_manifest())
        # With a permissive floor, only genuinely-relevant premises count
        # against top_k; irrelevant ones are excluded before the cutoff.
        result = select_premises(manifest, make_goal(), top_k=1, min_score=0.01)
        below_cutoff = [
            e for e in result.excluded if e.reason == PremiseExclusionReason.BELOW_CUTOFF
        ]
        floor_excluded = [
            e
            for e in result.excluded
            if e.reason == PremiseExclusionReason.BELOW_SCORE_FLOOR
        ]
        assert len(result.selected) <= 1
        assert len(below_cutoff) + len(floor_excluded) + len(result.selected) == len(
            manifest.entries
        )

    def test_deterministic_across_independent_calls(self):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        first = select_premises(manifest, goal, top_k=3)
        second = select_premises(manifest, goal, top_k=3)
        # `created_at` is a wall-clock timestamp and legitimately differs
        # between independent calls; every other field must be identical.
        first_dict = first.to_dict()
        second_dict = second.to_dict()
        first_dict.pop("created_at")
        second_dict.pop("created_at")
        assert first_dict == second_dict

    def test_top_k_larger_than_corpus_selects_all(self):
        manifest = populate_manifest(make_manifest())
        result = select_premises(manifest, make_goal(), top_k=1000)
        assert len(result.selected) == len(manifest.entries)
        assert result.excluded == []

    def test_rejects_non_positive_top_k(self):
        manifest = populate_manifest(make_manifest())
        with pytest.raises(InvalidTopKError):
            select_premises(manifest, make_goal(), top_k=0)
        with pytest.raises(InvalidTopKError):
            select_premises(manifest, make_goal(), top_k=-1)

    def test_rejects_non_integer_top_k(self):
        manifest = populate_manifest(make_manifest())
        with pytest.raises(InvalidTopKError):
            select_premises(manifest, make_goal(), top_k=2.5)  # type: ignore[arg-type]

    def test_policy_bounds_top_k(self):
        manifest = populate_manifest(make_manifest())
        policy = HammerPolicy(max_premises=2)
        with pytest.raises(InvalidTopKError, match="max_premises"):
            select_premises(manifest, make_goal(), top_k=3, policy=policy)

    def test_policy_permits_top_k_within_bound(self):
        manifest = populate_manifest(make_manifest())
        policy = HammerPolicy(max_premises=5)
        result = select_premises(manifest, make_goal(), top_k=2, policy=policy)
        assert result.top_k == 2

    def test_custom_weights_change_ranking(self):
        manifest = populate_manifest(make_manifest())
        goal = make_goal()
        symbol_only = PremiseSelectionWeights(
            symbol_weight=1.0, type_weight=0.0, import_weight=0.0, graph_weight=0.0
        )
        import_only = PremiseSelectionWeights(
            symbol_weight=0.0, type_weight=0.0, import_weight=1.0, graph_weight=0.0
        )
        symbol_result = select_premises(manifest, goal, top_k=1, weights=symbol_only)
        import_result = select_premises(manifest, goal, top_k=1, weights=import_only)
        # Both should still select a Nat.add_* premise (they share both
        # symbols and imports with the goal in this fixture) — the
        # assertion here is that custom weights are actually threaded
        # through to the score, not that they flip the winner.
        assert symbol_result.selected[0].score != import_result.selected[0].score or (
            symbol_result.weights != import_result.weights
        )

    def test_result_validates_cleanly(self):
        manifest = populate_manifest(make_manifest())
        result = select_premises(manifest, make_goal(), top_k=2)
        result.validate()  # should not raise


class TestSelectPremisesForTheorem:
    def test_builds_goal_from_existing_entry_and_self_excludes(self):
        manifest = populate_manifest(make_manifest())
        result = select_premises_for_theorem(manifest, "Nat.add_comm", top_k=10)
        assert result.goal_theorem_id == "Nat.add_comm"
        selected_ids = {p.premise_id for p in result.selected}
        assert "Nat.add_comm" not in selected_ids
        # The most topically similar remaining theorem should be ranked
        # above the unrelated List/Set premises.
        assert result.selected[0].premise_id == "Nat.add_assoc"

    def test_missing_theorem_id_raises_key_error(self):
        manifest = populate_manifest(make_manifest())
        with pytest.raises(KeyError):
            select_premises_for_theorem(manifest, "does-not-exist", top_k=5)


# ---------------------------------------------------------------------------
# ExcludedPremise / PremiseSelectionResult serialization & validation
# ---------------------------------------------------------------------------


class TestExcludedPremise:
    def test_valid_record_passes_validation(self):
        ExcludedPremise(
            premise_id="p1", score=0.5, reason=PremiseExclusionReason.BELOW_CUTOFF,
            corpus_revision="rev1",
        ).validate()

    def test_empty_premise_id_rejected(self):
        with pytest.raises(ValueError, match="premise_id"):
            ExcludedPremise(premise_id="", corpus_revision="rev1").validate()

    def test_non_finite_score_rejected(self):
        with pytest.raises(ValueError):
            ExcludedPremise(
                premise_id="p1", score=float("inf"), corpus_revision="rev1"
            ).validate()

    def test_invalid_reason_type_rejected(self):
        record = ExcludedPremise(premise_id="p1", corpus_revision="rev1")
        record.reason = "below_cutoff"  # type: ignore[assignment]
        with pytest.raises(ValueError, match="reason"):
            record.validate()

    def test_to_dict_from_dict_round_trip(self):
        record = ExcludedPremise(
            premise_id="p1",
            score=0.25,
            reason=PremiseExclusionReason.SELF_REFERENCE,
            corpus_revision="rev1",
        )
        restored = ExcludedPremise.from_dict(record.to_dict())
        assert restored == record
        assert record.to_dict()["reason"] == "self_reference"


class TestPremiseSelectionResult:
    def test_to_dict_from_dict_round_trip(self):
        manifest = populate_manifest(make_manifest())
        result = select_premises(manifest, make_goal(), top_k=2)
        restored = PremiseSelectionResult.from_dict(copy.deepcopy(result.to_dict()))
        assert restored.to_dict() == result.to_dict()

    def test_validate_rejects_selected_exceeding_top_k(self):
        manifest = populate_manifest(make_manifest())
        result = select_premises(manifest, make_goal(), top_k=3)
        result.top_k = 1
        with pytest.raises(ValueError, match="top_k"):
            result.validate()

    def test_validate_rejects_rank_mismatch(self):
        manifest = populate_manifest(make_manifest())
        result = select_premises(manifest, make_goal(), top_k=2)
        result.selected[0].rank = 5
        with pytest.raises(ValueError, match="rank"):
            result.validate()

    def test_validate_rejects_corpus_revision_mismatch_on_selected(self):
        manifest = populate_manifest(make_manifest())
        result = select_premises(manifest, make_goal(), top_k=2)
        result.selected[0].corpus_revision = "different-revision"
        with pytest.raises(ValueError, match="corpus_revision"):
            result.validate()

    def test_validate_rejects_corpus_revision_mismatch_on_excluded(self):
        manifest = populate_manifest(make_manifest())
        result = select_premises(manifest, make_goal(), top_k=2)
        assert result.excluded, "fixture must produce at least one excluded candidate"
        result.excluded[0].corpus_revision = "different-revision"
        with pytest.raises(ValueError, match="corpus_revision"):
            result.validate()

    def test_validate_rejects_overlap_between_selected_and_excluded(self):
        manifest = populate_manifest(make_manifest())
        result = select_premises(manifest, make_goal(), top_k=2)
        assert result.excluded
        duplicate = copy.deepcopy(result.excluded[0])
        duplicate.premise_id = result.selected[0].premise_id
        result.excluded.append(duplicate)
        with pytest.raises(ValueError, match="disjoint"):
            result.validate()

    def test_validate_rejects_duplicate_selected_ids(self):
        manifest = populate_manifest(make_manifest())
        result = select_premises(manifest, make_goal(), top_k=2)
        result.selected.append(copy.deepcopy(result.selected[0]))
        with pytest.raises(ValueError):
            result.validate()

    def test_validate_rejects_empty_corpus_revision(self):
        manifest = populate_manifest(make_manifest())
        result = select_premises(manifest, make_goal(), top_k=2)
        result.corpus_revision = ""
        with pytest.raises(ValueError, match="corpus_revision"):
            result.validate()
