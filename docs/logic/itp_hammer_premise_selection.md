# ITP Hammer Deterministic Premise Selection Baseline

Status: Implemented (HAMMER-004)
Date: 2026-07-19
Module: `ipfs_datasets_py.logic.hammers.premise_selection`
Tests: `tests/unit_tests/logic/hammers/test_premise_selection.py`

Related: `docs/logic/itp_hammer_taskboard.todo.md` (the taskboard this
document is an output of), `docs/logic/itp_hammer_contract.md` (HAMMER-001,
the trust contract whose `PremiseRecord` this module produces),
`docs/logic/itp_hammer_corpus.md` (HAMMER-003, the content-addressed corpus
manifest this module selects premises from).

## 1. Purpose

Before any translation or solver portfolio stage can run, the hammer
pipeline needs a bounded, auditable, *reproducible* answer to "which
premises from the corpus are relevant to this goal?" This document
specifies the deterministic baseline selector that answers that question
without any machine-learned model, embedding, or LLM: given a goal's
symbols, types, and imports (and, optionally, its own corpus identity), it
ranks every candidate premise in a `CorpusManifest` (HAMMER-003) by a
purely computed, finite score, enforces a bounded `top_k` cutoff, and
reports every candidate that was *not* selected alongside an explicit
reason.

This baseline is deliberately the trust floor for premise selection in the
hammer pipeline. HAMMER-005 later adds an *optional*, opt-in learned or
graph-based selector, but it must always be able to fall back to this
module when a pinned model is missing or fails, and its own quality must be
benchmarked against this baseline's held-out recall.

## 2. Why determinism is a first-class requirement

Two independent runs of `select_premises` against the same
`(manifest, goal, weights, top_k, ...)` input must produce byte-identical
output — same selected premises, in the same order, with the same scores,
and the same excluded set, modulo only the wall-clock
`PremiseSelectionResult.created_at` timestamp. Concretely:

- No feature extraction step depends on external randomness, network
  access, wall-clock time, hash-seed-dependent iteration order, or
  file-system enumeration order.
- Feature sets (`GoalFeatures.symbols`/`.types`/`.imports`, and every
  candidate's corresponding sets) are plain Python `frozenset`s, and every
  candidate is drawn from `CorpusManifest.iter_theorems()`, which is
  already sorted by `theorem_id`.
- Final ranking is sorted explicitly by `(-score, theorem_id)` — descending
  score, then ascending `theorem_id` as a tie-break — so candidates with
  numerically identical scores (a common occurrence when two premises share
  an identical feature profile) still resolve to one specific, stable
  order rather than depending on Python's stable-sort input order alone.

This determinism is what makes "stable ordering for identical input" (the
taskboard's acceptance requirement) a property that can be asserted in a
unit test rather than merely observed to usually hold.

## 3. Feature extraction: symbols, types, imports

The selector never parses Lean/Coq/Isabelle syntax — it uses the same
intentionally simple, ITP-agnostic philosophy as
`corpus.normalize_statement`:

- **`extract_symbols(statement)`** tokenizes on a shared cross-ITP
  identifier pattern (a leading letter/underscore, followed by
  letters/digits/underscores/dots for qualified names such as
  `Nat.add_comm`, with an optional trailing `'`), drops a curated list of
  keyword/tactic vocabulary shared across Lean4, Coq/Rocq, and
  Isabelle/HOL (`forall`, `theorem`, `by`, `Proof`, `Qed`, `datatype`, ...),
  and drops single-character tokens (a cheap heuristic proxy for bound
  variables like `a`, `b`, `n`, which carry essentially no topical signal).
  The remaining tokens are lower-cased and returned as a `frozenset` — the
  goal's **symbols** feature.
- **`extract_types(statement)`** reuses the same tokenization and stopword
  filter, but instead keeps tokens whose *first character is uppercase*
  (before lower-casing), on the heuristic that Lean/Coq/Isabelle
  conventionally capitalize type and sort names (`Nat`, `List`, `Prop`,
  `Set`) while functions, lemma names, and bound variables are
  lower-case — the goal's **types** feature. This is a lexical heuristic,
  not a type checker.
- **imports** are simply the goal's declared module/theory/file
  dependencies (the same shape as `TheoremEntry.imports`), normalized to a
  `frozenset`.

Both extractors are pure functions of their input string: identical text
always yields an identical `frozenset`.

## 4. The one-hop dependency-graph feature

Direct symbol/type/import overlap between a goal and a candidate premise is
a strong signal, but it misses premises that are topically close *via* a
shared intermediate theorem — e.g. a lemma that itself imports both the
goal's module and the candidate's module, even though the goal and
candidate share no import directly. `_expand_imports_one_hop` computes this:
starting from the goal's direct imports, it unions in *every* import of
*every* corpus theorem that shares at least one import with the goal — a
single, bounded hop over the corpus's theorem/import bipartite graph (not a
full transitive closure, keeping the computation `O(#theorems)` and the
signal local). Each candidate's **graph score** is then the Jaccard overlap
between the candidate's own imports and this one-hop-expanded set, giving a
nonzero score to candidates that are only *transitively* related to the
goal.

```python
# Goal imports "Goal.Import"; `Bridge` imports both "Goal.Import" and
# "Shared.Module"; `Indirect` only imports "Shared.Module" and therefore has
# zero *direct* import overlap with the goal, but a positive graph_score.
manifest.add_theorem(theorem_id="Bridge", corpus_id="mathlib4",
                      statement="...", imports=["Goal.Import", "Shared.Module"])
manifest.add_theorem(theorem_id="Indirect", corpus_id="mathlib4",
                      statement="...", imports=["Shared.Module"])
```

## 5. Scoring and weights

Each candidate's total score is a weighted sum of four `[0.0, 1.0]`
Jaccard-similarity components (`ScoredCandidate`):

| Component | Meaning | Default weight |
| --- | --- | --- |
| `symbol_score` | Jaccard overlap of goal vs. candidate content symbols | 0.45 |
| `type_score` | Jaccard overlap of goal vs. candidate type-like tokens | 0.20 |
| `import_score` | Jaccard overlap of goal vs. candidate direct imports | 0.20 |
| `graph_score` | Jaccard overlap of candidate imports vs. one-hop-expanded goal imports (§4) | 0.15 |

`PremiseSelectionWeights` validates that every weight is finite and
non-negative and that at least one is strictly positive (an all-zero
weighting, which would score every candidate `0.0`, is rejected rather than
silently accepted). Callers may override the defaults per call — e.g. a
symbol-only or import-only weighting — without touching the module's
built-in defaults.

`score_candidates(goal, manifest, weights=..., candidates=...)` is the
lower-level entry point that returns every candidate's full
`ScoredCandidate` breakdown in stable rank order; `select_premises` builds
on top of it.

## 6. Selection, cutoff, and exclusion reasons

`select_premises(manifest, goal, *, top_k, policy=None, weights=None,
exclude_theorem_ids=None, min_score=None, candidates=None)` is the
top-level entry point. It:

1. Enforces `top_k`: it must be a positive integer, and — the "bounded
   `top_k`" requirement — if a `HammerPolicy` is supplied, `top_k` must not
   exceed `policy.max_premises`. Either violation raises `InvalidTopKError`
   *before* any scoring happens; `top_k` is never silently clamped.
2. Scores every candidate via `score_candidates`.
3. Removes the goal's own `theorem_id` from the ranking pool if present
   (`PremiseExclusionReason.SELF_REFERENCE`) — a goal can never select
   itself as a premise.
4. Removes any `theorem_id` in the caller's `exclude_theorem_ids`
   (`PremiseExclusionReason.EXPLICITLY_EXCLUDED`) — e.g. premises a prior
   attempt already tried.
5. If `min_score` is given, removes candidates scoring strictly below it
   (`PremiseExclusionReason.BELOW_SCORE_FLOOR`) *before* the `top_k` cutoff
   is applied, so an irrelevant candidate never consumes a selection slot.
6. Takes the first `top_k` of what remains as `selected`; everything past
   the cutoff is excluded with `PremiseExclusionReason.BELOW_CUTOFF`.

Every candidate that enters the process ends up in exactly one of
`selected` or `excluded` — `selected_ids | excluded_ids` always equals the
full candidate pool, and the two sets are always disjoint (enforced by
`PremiseSelectionResult.validate`). This is what "emit selected IDs, scores,
corpus revision, cutoff, and excluded candidates" means operationally:
nothing a candidate's score is computed for ever silently disappears from
the result.

```python
result = select_premises(manifest, goal, top_k=16, policy=policy)
result.corpus_revision   # == manifest.revision
result.top_k             # == 16 (the enforced cutoff)
result.selected          # List[PremiseRecord], rank 0..len-1, descending score
result.excluded          # List[ExcludedPremise], each with a `.reason`
```

## 7. `PremiseSelectionResult` and its invariants

`PremiseSelectionResult` ties everything together and validates:

- `corpus_revision` is non-empty and equals the corpus manifest revision
  every `selected`/`excluded` entry was drawn from — every entry in both
  lists must carry that same `corpus_revision`, or validation fails.
- `len(selected) <= top_k` — the enforced cutoff is never exceeded.
- Each `selected[i].rank == i` — 0-indexed, contiguous rank order matching
  list position (no gaps, no reordering after the fact).
- No duplicate `premise_id` within `selected`, none within `excluded`, and
  the two sets are disjoint.

Every selected premise is a standard HAMMER-001
`~ipfs_datasets_py.logic.hammers.models.PremiseRecord`, with
`selection_method` stamped as `DETERMINISTIC_BASELINE_METHOD =
"deterministic-baseline"` (the same string
`PremiseRecord.selection_method` defaults to) and `content_digest` copied
from the corpus entry's own derived digest — so a selected premise's
provenance is traceable all the way back to HAMMER-003's content
addressing.

`PremiseSelectionResult`/`ExcludedPremise` both expose `to_dict()`/
`from_dict()` for JSON-compatible (de)serialization, following the same
conventions as the HAMMER-001/HAMMER-003 records; `from_dict` always
re-validates before returning.

## 8. Convenience: `select_premises_for_theorem`

`select_premises_for_theorem(manifest, theorem_id, *, top_k, ...)` builds
the goal directly from an existing corpus entry
(`GoalFeatures.from_theorem_entry`) and automatically self-excludes it —
the typical shape of a held-out evaluation ("given every *other* theorem
currently in the corpus, which would the baseline select as premises for
proving `theorem_id`?"), and the shape HAMMER-005's benchmark harness is
expected to reuse for baseline-vs-learned recall comparisons.

## 9. Non-goals of this module

This module ranks and selects premises only. It does not:

- Translate premises to TPTP/SMT-LIB — that is HAMMER-007.
- Run any external solver — that is HAMMER-008.
- Use any machine-learned model, embedding, or LLM — an *optional*,
  opt-in learned/graph-based selector that must fall back to this
  deterministic baseline is HAMMER-005.
- Parse or type-check Lean/Coq/Isabelle syntax — `extract_symbols`/
  `extract_types` are lexical heuristics over raw statement text, exactly
  like `corpus.normalize_statement`.
