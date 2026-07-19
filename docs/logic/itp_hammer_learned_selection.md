# ITP Hammer Optional Learned Premise Selector

Status: Implemented (HAMMER-005)
Date: 2026-07-19
Module: `ipfs_datasets_py.logic.hammers.learned_selector`
Tests: `tests/unit_tests/logic/hammers/test_learned_selector.py`
Benchmark: `benchmarks/bench_itp_hammer_premise_selection.py`

Related: `docs/logic/itp_hammer_taskboard.todo.md` (the taskboard this
document is an output of), `docs/logic/itp_hammer_premise_selection.md`
(HAMMER-004, the deterministic baseline this module extends and always
falls back to), `docs/logic/itp_hammer_contract.md` (HAMMER-001, the trust
contract whose `PremiseRecord` both selectors produce).

## 1. Purpose and operating rule

HAMMER-004 established a deterministic, auditable premise-selection
baseline with no machine-learned model, embedding, or LLM involved. The
taskboard permits an *optional* learned or graph-based selector on top of
that baseline, but only under a strict operating rule:

> Keep the deterministic baseline as the default. Permit a learned or
> graph-based selector only with a pinned model digest, held-out
> recall/latency comparison, reproducible feature extraction, opt-in
> configuration, and a fallback to the baseline when the model is missing
> or fails.

Every clause of that rule is enforced in code by this module, not just
described in prose — see §3 below for how each clause maps onto a specific
type, gate, or code path.

## 2. An honest note on "learned"

This module does not ship a trained neural network, gradient-boosted tree,
or embedding model. None of the ITP hammer pipeline's existing dependencies
provide a training harness, and there is no labeled premise-relevance
dataset in this repository to train one against. Fabricating a "trained"
model with no genuine training process would be a strictly worse outcome
than being explicit about what actually exists — it would misrepresent the
selector's provenance exactly as this project's overall "no unverified proof
is ever called `verified`" philosophy forbids for solver output.

Instead, `build_default_graph_selector_artifact()` produces a fixed,
hand-authored *linear* combination of graph/lexical overlap features (a
legitimate "graph-based selector" under the taskboard's own wording),
wrapped in exactly the content-addressed, pinned-digest, fallback-gated
artifact format a genuinely trained model would use. `LearnedModelArtifact`
places no constraint on where its `weights` mapping comes from — a future
model only needs to populate that mapping (and declare its own
`feature_version`); none of the gating, fallback, or benchmark machinery in
this module needs to change to accommodate a real trained model later.

## 3. How the operating rule is enforced

| Requirement | Enforcement |
| --- | --- |
| Deterministic baseline stays the default | `select_premises_gated()` calls `premise_selection.select_premises()` immediately whenever `learned_config` is omitted or `learned_config.enabled=False` — no model loading, no feature extraction beyond the baseline's own. |
| Pinned model digest | `LearnedModelArtifact.model_digest` is a derived SHA-256 digest of the artifact's own identity payload (`compute_model_digest`); `LearnedSelectorConfig.pinned_model_digest` must be declared before a caller can enable the selector at all (`LearnedSelectorConfig.validate()`), and the *actually loaded* artifact's digest is compared against it before it is trusted to score anything. |
| Held-out recall/latency comparison | `relevant_theorem_ids_by_import_overlap`, `compute_recall_at_k`, and `compute_reciprocal_rank` are the reusable metrics; `benchmarks/bench_itp_hammer_premise_selection.py` runs the full held-out comparison over a fixture corpus and persists a JSON report. |
| Reproducible feature extraction | `extract_learned_features(goal, entry, manifest)` is a pure function — no randomness, network access, or wall-clock dependence — built from the same deterministic building blocks (`extract_symbols`/`extract_types`/one-hop import expansion) the HAMMER-004 baseline already uses. |
| Opt-in configuration | `LearnedSelectorConfig.enabled` (default `False`) *and* `HammerPolicy.allow_learned_premise_selector` (default `False`, defined in HAMMER-001's `models.py`) must both be `True`, or the baseline runs. |
| Fallback when the model is missing or fails | `select_premises_gated()` never raises due to a missing file, a malformed artifact, a digest mismatch, or an unexpected scoring exception — see §5's `SelectorFallbackReason` states. |

## 4. Reproducible feature extraction

`extract_learned_features(goal, entry, manifest, *, expanded_goal_imports=None)`
returns a dict keyed by `LEARNED_FEATURE_NAMES`:

- `symbol_score`, `type_score`, `import_score`, `graph_score` — identical in
  meaning to HAMMER-004's four Jaccard components (reusing
  `premise_selection.extract_symbols`/`extract_types` and the same one-hop
  dependency-graph expansion), so the learned selector's signal is a strict
  superset of the baseline's.
- `goal_symbol_count`, `candidate_symbol_count`, `shared_symbol_count`,
  `candidate_import_count`, `one_hop_neighbor_count` — additional
  count-based features a linear model can use to, e.g., penalize
  candidates with a very large unrelated symbol vocabulary even when their
  Jaccard overlap looks superficially similar.

`LEARNED_FEATURE_VERSION` (`"learned-selector-features-v1"`) is stamped on
every `LearnedModelArtifact`; a model trained (or, today, hand-authored)
against one feature version must not be silently scored against an
incompatible future version — the artifact declares its own
`feature_names`/`feature_version` explicitly rather than trusting the
module's current defaults.

## 5. `LearnedModelArtifact`: pinned, content-addressed model records

```python
from ipfs_datasets_py.logic.hammers.learned_selector import LearnedModelArtifact

artifact = LearnedModelArtifact.create(
    model_id="graph-selector-default-v1",
    weights={"symbol_score": 3.2, "type_score": 1.0, "import_score": 1.2, "graph_score": 0.8},
    bias=-1.6,
)
artifact.model_digest  # "sha256:...", derived from (model_id, feature_version,
                        # feature_names, weights, bias) -- never independently set
artifact.save("model.json")
loaded = LearnedModelArtifact.load("model.json")  # re-validates + re-checks the digest
```

`score_with_model(artifact, features)` computes
`sigmoid(bias + sum(weight[f] * feature[f] for f in feature_names))`,
clamped before exponentiating so a pathological weight/feature product can
never raise `OverflowError` — the model's output is always a finite float in
`(0.0, 1.0)`, comparable in scale to the baseline's Jaccard-based scores.

`LearnedModelArtifact.verify_digest()` recomputes the digest from the
artifact's current fields and raises `ModelDigestMismatchError` if it does
not match `model_digest` — this is what detects a tampered-with or
corrupted model file, and it runs automatically inside `validate()` (called
by both `create()` and `load()`).

## 6. `LearnedSelectorConfig`: the opt-in switch

```python
from ipfs_datasets_py.logic.hammers.learned_selector import LearnedSelectorConfig
from ipfs_datasets_py.logic.hammers.models import HammerPolicy

config = LearnedSelectorConfig(
    enabled=True,
    model_path="data/logic/itp_hammer/premise_selector_model.json",
    pinned_model_digest="sha256:...",  # required when enabled=True
)
policy = HammerPolicy(allow_learned_premise_selector=True)  # the run-level gate
```

`LearnedSelectorConfig` is deliberately a *separate* switch from
`HammerPolicy.allow_learned_premise_selector`: the config is what a caller
who wants to try the learned selector supplies; the policy is what an
operator controlling a specific hammer run permits. Both must be `True` for
`select_premises_gated()` to even attempt loading a model — a caller cannot
unilaterally override an operator's policy by supplying `enabled=True`.

**Security caveat on pinning.** `pinned_model_digest` is only a meaningful
trust anchor when it comes from a source *independent* of the model file
itself (e.g. a value checked into a signed release manifest, or hard-coded
in an operator's deployment config) — pinning a digest you just read out of
the same file you are about to load only detects accidental corruption in
transit, not a maliciously substituted file authored to match its own
(different) content. `benchmarks/bench_itp_hammer_premise_selection.py`
does the latter (reads the pinned digest from the fixture artifact itself)
purely for benchmark reproducibility with no separately-provisioned trust
anchor to draw from; real deployments should pin independently.

`LearnedSelectorConfig.validate()` (called at the top of
`select_premises_gated()`) raises `LearnedSelectorConfigError` — not a
fallback — when `enabled=True` but `model_path`/`pinned_model_digest` are
missing or malformed: an operator enabling the selector without pinning a
digest is a configuration mistake that must be surfaced immediately, not
silently downgraded to a fallback.

## 7. `select_premises_gated`: the fallback-gated entry point

```python
from ipfs_datasets_py.logic.hammers.learned_selector import select_premises_gated

outcome = select_premises_gated(
    manifest, goal, top_k=16, policy=policy, learned_config=config,
)
outcome.used_learned_selector   # True only if every gate below passed
outcome.fallback_reason         # SelectorFallbackReason.NONE when used_learned_selector
outcome.selection                # a standard PremiseSelectionResult either way
outcome.selection.selected[0].selection_method  # "learned-selector:sha256:..." or
                                                  # "deterministic-baseline"
```

Gates, checked in order, each falling back to
`premise_selection.select_premises()` (the exact HAMMER-004 baseline
function) rather than raising:

1. **`SelectorFallbackReason.NOT_ENABLED`** — `learned_config` omitted or
   `enabled=False`.
2. **`SelectorFallbackReason.POLICY_DENIED`** — a supplied `policy` has
   `allow_learned_premise_selector=False`.
3. **`SelectorFallbackReason.MODEL_MISSING`** — `model_path` does not exist
   on disk (`FileNotFoundError` from `LearnedModelArtifact.load`).
4. **`SelectorFallbackReason.MODEL_LOAD_ERROR`** — the file exists but is
   not well-formed JSON, or fails `LearnedModelArtifact` field validation.
5. **`SelectorFallbackReason.MODEL_DIGEST_MISMATCH`** — the artifact's own
   `verify_digest()` fails (tampered/corrupted file), or its `model_digest`
   does not equal `LearnedSelectorConfig.pinned_model_digest` (an
   unexpected — even if internally self-consistent — model was
   substituted).
6. **`SelectorFallbackReason.SCORING_ERROR`** — scoring candidates raised
   any unexpected exception (a malformed weight, a `TheoremEntry` that
   fails feature extraction, ...).

Only when every gate is satisfied does `used_learned_selector=True` come
back, with `fallback_reason=SelectorFallbackReason.NONE` and every selected
`PremiseRecord.selection_method` stamped
`f"learned-selector:{model_digest}"` — the pinned model digest is always
part of the audit trail on every selected premise, not just on the
top-level result.

`top_k`/manifest/goal validation errors (`InvalidTopKError`,
`PremiseSelectionError`) are **not** treated as "model failure" on either
path — they are genuine caller errors and always propagate, exactly as they
do from the plain HAMMER-004 baseline.

`select_premises_for_theorem_gated(manifest, theorem_id, ...)` is the
learned-selector analogue of HAMMER-004's
`select_premises_for_theorem`: it builds the goal from an existing corpus
entry and self-excludes it, the shape used for held-out evaluation.

## 8. Held-out recall/latency comparison methodology

`benchmarks/bench_itp_hammer_premise_selection.py` implements the
comparison this module's acceptance criterion requires:

1. Load a fixture corpus (`tests/fixtures/logic/hammers/premise_selection_corpus.json`)
   into a `CorpusManifest`.
2. Load the pinned fixture model
   (`tests/fixtures/logic/hammers/learned_selector_model.json`, produced by
   `build_default_graph_selector_artifact()`).
3. For every theorem `T` in the corpus, held out one at a time:
   - Compute the proxy "relevant" set via
     `relevant_theorem_ids_by_import_overlap(manifest, T)` — every *other*
     corpus theorem sharing at least one import/module with `T`. The
     corpus manifest (HAMMER-003) does not record an explicit
     theorem-to-theorem dependency graph, only each theorem's own imports,
     so shared-import proximity is the same reproducible, ground-truth-free
     proxy HAMMER-004's own documentation already describes for held-out
     evaluation.
   - Run `premise_selection.select_premises_for_theorem` (baseline) and
     `learned_selector.select_premises_for_theorem_gated` (learned, opted
     in), timing each call.
   - Score both selectors' `selected` premise-id lists against the relevant
     set with `compute_recall_at_k` and `compute_reciprocal_rank`.
4. Aggregate mean recall@k, mean reciprocal rank, and latency percentiles
   for both selectors, plus a fallback count/rate for the learned path.
5. Run an explicit **fallback smoke test**: point a gated call at a
   nonexistent model path and assert (recording the result, not raising)
   that it falls back to the baseline with
   `SelectorFallbackReason.MODEL_MISSING`.

Usage:

```bash
PYTHONPATH=. python benchmarks/bench_itp_hammer_premise_selection.py \
    --fixture tests/fixtures/logic/hammers \
    --out data/logic/itp_hammer/premise-selection-benchmark.json
```

The script exits non-zero if the fallback smoke test does not pass — a
regression in the fallback path is treated as a hard benchmark failure, not
just a footnote in the report.

## 9. `LearnedSelectionResult`: the outcome record

Every `select_premises_gated`/`select_premises_for_theorem_gated` call
returns a `LearnedSelectionResult`:

- `selection` — the actual, independently-valid `PremiseSelectionResult`
  (from whichever selector actually ran).
- `used_learned_selector` / `fallback_reason` — mutually consistent by
  construction (`validate()` rejects `used_learned_selector=True` paired
  with a non-`NONE` reason, and vice versa).
- `model_id` / `model_digest` / `feature_version` — populated only when the
  learned selector actually ran.
- `latency_ms` — wall-clock latency of whichever selector actually produced
  `selection`.

`to_dict()`/`from_dict()` follow the same JSON-compatible conventions as
every other HAMMER-00x record; `from_dict` always re-validates before
returning.

## 10. Non-goals of this module

- It does not train, fine-tune, or otherwise fit any model from data — see
  §2. `build_default_graph_selector_artifact()` is a fixed, hand-authored
  weighting, honestly documented as such.
- It does not change HAMMER-004's `premise_selection.py` in any way; every
  gate, fallback, and finalization path in this module is implemented
  independently (reusing only its already-tested, deterministic feature
  extractors), so the deterministic baseline's own behavior and test suite
  are completely unaffected by this module's existence.
- It does not use an LLM to propose premise rankings — that capability is
  governed separately by `HammerPolicy.allow_llm_premise_ranking` and is out
  of scope for this module.
- It does not itself decide whether a candidate proof attempt succeeds —
  premise selection (learned or baseline) only narrows the candidate pool
  handed to translation (HAMMER-007) and the solver portfolio (HAMMER-008).
