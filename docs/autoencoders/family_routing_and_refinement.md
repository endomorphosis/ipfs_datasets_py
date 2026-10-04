# Family-aware solver routing and decoder refinement

Use the checked portfolio entrypoint for native, family-tagged projections.
Solver input format alone does not establish support for the source semantics.
Use the optional decoder-block strategy when shared encoder updates prevent
otherwise useful family improvements from passing the nonregression gate.
Neither change relaxes the native training gates or creates Lean admission.

## Solver routing

`logic.hammers.semantic_routing.prepare_family_portfolio` requires an explicit
logic family, AST format, printed formula, native AST and solver names. It:

1. Checks the actual AST against a bounded, implemented lowering profile.
2. Reparses the printed formula and requires exact AST equality.
3. Intersects each solver's catalog capability, fragment, operation and property
   with the implemented lowering.
4. Requires a complete typed translation without outstanding obligations.

`run_family_portfolio` repeats those checks immediately before execution. The
parallel autoencoder projection runner now uses this entrypoint. Unsupported
families and operators fail before executable discovery or resource acquisition.
There is no fallback that treats temporal, deontic or cognitive operators as
uninterpreted Boolean atoms.

The initial checked lowering is deliberately bounded:

| Source fragment | Solver | Operation | Meaning of result |
| --- | --- | --- | --- |
| Binder-free propositional shared AST | Z3, CVC5 | Assert formula; check satisfiability | SAT is satisfiability, not validity |
| Same fragment, embedded as zero-arity classical predicates | Vampire, E | Submit conjecture | Untrusted validity candidate; no kernel reconstruction |
| Other families, binders, predicate arguments or modal operators | None through this lowering | Explicitly unsupported | Existing native owners still run their required checks |

The route receipt records capability and producer hashes, the precise operation,
translation and fragment. Mixed operations cannot cancel each other as a common
conclusive result. They never become one success vote. Catalog declarations for
DCEC or TDFOL do not establish that this entrypoint implements their lowering.
Adding a route requires an executable semantics-preserving translation, fragment
checks, explicit result interpretation and positive/negative tests.

An explicitly requested unsupported diagnostic rejects batch preflight; it does
not silently fall back to another solver or count as a successful native check.
The standalone source guard pins its direct owners, not the entire transitive
renderer dependency graph. Exact generated translation bytes are retained and
replayed before execution; preserve the frozen runtime for reproducible evidence.

Raw `SolverPortfolio` remains a low-level translation transport. The MCP
`hammer_run_candidate` API also accepts raw serialized translations without a
source-family AST; it remains untrusted and is not covered by this new semantic
gate. Do not use that API as a family qualification boundary. Native Lake/SANY
checks, capability floors and applicability reviews remain independent. Only
actual `lake build <Lib>` is Lean build evidence.

## Decoder-block refinement

The strict v5 structural trainer accepts `refinement_strategy="decoder_blocks"`.
The default remains `"joint_adam"` for an explicit comparison and compatibility
with callers. `train_prepared_projection_corpus` forwards this option unchanged:

```python
trained = train_prepared_projection_corpus(
    live_corpus,
    output_dir=fresh_checkpoint_directory,
    refinement_strategy="decoder_blocks",
    epochs=24, patience=24, latent_width=4,
    learning_rate=0.001, minibatch_size=2, max_seconds=120,
)
```

Both strategies use training-only SVD initialization and ridge calibration, the
same masked macro-family reconstruction objective, denoising, gradient clipping
and warmup/cosine learning-rate schedule. All emitted projections contribute to
the loss; no difficult family is removed to improve throughput or acceptance.

The optional strategy freezes the shared encoder and optimizes only decoder
weights and biases. Clean training and tuning latents are cached. Corrupted
denoising inputs are encoded anew. Adam's candidate parameters and momentum
continue between epochs; accepted selections do not reset the trajectory.
Tuning selects complete decoder blocks belonging to each logic family. Since
the encoder is unchanged, retaining an improving family's blocks cannot alter
another family's prediction. Every selected family must meet the original
nonregression tolerance. Incomplete or late epochs cannot change the selected
checkpoint. The deadline includes initialization, calibration and refinement.

This trades shared-representation learning for independently selectable decoder
improvements. It is useful for diagnosing blocked updates, not a guarantee of a
global optimum. Training gradients never use tuning rows; tuning selects weights
and therefore is not an independent holdout. Reports retain all family losses,
rejected candidate regressions, selected epoch per family and wall times.

## Scope and reproducibility

These are four-tensor native **structural feature heads**. They do not train or
qualify the preserved 8D linguistic decoder or the 384D source-language decoder.
Input projections passing Lake does not establish that reconstructed features
decode into correct formulas. The Constitution remains unformalized.

Strict artifacts pin numerical and native producer implementations, now including
the refinement module. An older artifact with different producer hashes does
not load under the changed current producer; retain its original frozen runtime.
No archived checkpoint is rewritten or silently migrated.

The composition benchmark prepares training and tuning targets first, freezes
all baseline/candidate checkpoints and settings, then prepares and evaluates the
held-out targets. It reports atom retention and unknown-feature coverage: the
existing 4,096-feature cap is not a claim to reconstruct every structural atom.
The authored panel tests structural generalization, not natural-language fidelity.
See the recorded comparison alongside this guide for its measured outcome.

Run the fixed comparison from the selected source tree with installed tools:

```bash
PYTHONPATH="$PWD" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python scripts/ops/autoencoder/benchmark_validated_family_convergence.py \
  --output /absolute/path/to/fresh-comparison \
  --lake /path/to/installed/lake \
  --java-executable /path/to/installed/java \
  --tla2tools-jar /path/to/installed/tla2tools.jar \
  --workers 4
```

The runner uses the existing shared proof scheduler. Numerical fits are sequential
and single-threaded to avoid changing process-wide Torch thread settings during
concurrent fits. It requests six training, two tuning and two held-out authored
compositions per domain, two seeds, 24 epochs and both strategies. Each run needs
a fresh output directory. Once exposed, this panel's heldout results are reusable
regression evidence, not a newly sealed evaluation for later tuning decisions.
This is not a legal-IR bridge-on evaluate timing.

## Recorded comparison: 2026-10-01

The frozen export of `493911c2b89cbe2747c2a09ee887a30f8f2b66af` plus
this change passed 161 focused tests. The fixed comparison completed in
1,048.79 seconds with 40 actual Lake builds across LegalIR, IntentIR, SecurityIR
and UIUXIR; 660 emitted projection checks; and eight actual Z3/CVC5 SAT
diagnostics. Every compared checkpoint was sealed before heldout target
generation. No settings changed after test exposure and no model was promoted.

Mean retained-feature heldout objectives across the two fixed seeds:

| Domain | Joint Adam | Decoder blocks | Reduction | Decoder selected epochs |
| --- | ---: | ---: | ---: | --- |
| Legal | 0.001799562 | 0.001794814 | 0.264% | 9, 5 |
| Intent | 0.000811152 | 0.000808162 | 0.369% | 4, 13 |
| Security | 0.001420574 | 0.001411486 | 0.640% | 10, 10 |
| UI/UX | 0.001153930 | 0.001149092 | 0.419% | 5, 10 |

All eight baseline runs selected epoch zero. Each run executed 24 epochs and
72 minibatch steps. Decoder blocks accepted later updates under the unchanged
tuning-family gates. This establishes useful numerical refinement on this
authored panel, not convergence of either source-language autoencoder lineage.

Seed averages conceal some regressions. Against its paired baseline, Legal seed
1729 regressed DCEC, deontic, event calculus, first-order and temporal losses;
Intent seed 1729 regressed propositional loss. The other six candidate runs had
no family regression against their paired baselines. Compared with original SVD
initialization, mean propositional loss still regressed for Legal and Intent;
Security also regressed frame-logic and propositional loss. UI had no such mean
regression. No all-family heldout convergence or qualification is established.

| Domain | Available training atoms | Retained atoms | Known heldout atom occurrences |
| --- | ---: | ---: | ---: |
| Legal | 2,227 | 2,227 | 97.41% |
| Intent | 27,009 | 4,096 | 15.09% |
| Security | 3,777 | 3,777 | 97.49% |
| UI/UX | 7,337 | 4,096 | 56.42% |

The unchanged feature cap is particularly restrictive for Intent and UI. Every
emitted projection has a loss, but those losses cover retained features only.
The next experiment needs richer semantic feature coverage and newly sealed
evaluation groups before using its result to judge complete reconstruction.

Median full fit times (baseline → candidate) were Legal 23.54 → 23.37 seconds,
Intent 32.00 → 32.42, Security 25.05 → 25.12, and UI 27.49 → 25.11. The first
baseline had optimizer warm-up overhead. Across 16 fits, numerical refinement
totaled only 5.62 seconds out of 428.19 seconds of full fitting. Native validation
plus result rechecks took 389.69 seconds for development and 95.00 seconds for
heldout. Target preparation took 20.81 seconds. These observations do not support
a general throughput improvement claim; live source/evidence replays dominate.

Exact source snapshots, seed-level family regressions, feature coverage, native
receipts, solver routes and timings are retained in
[the evidence bundle](../implementation/reports/evidence/family-routing-convergence-20261001/results.json).
Generated diagnostic weights remain local and are identified by hashes in that
bundle; archived checkpoints were not modified.
