# Joint modal decoder validation — 2026-10-01

Both the 8D and 384D legal facades now have a trainable formula head attached to
their raw model representation. One training call optimizes formula token
cross-entropy and embedding reconstruction together, with measured formula
gradients into the new residual projection. The original sparse core remains
frozen; its historical snapshot and archived checkpoints were not rewritten.

**776 tests passed in 119.41 seconds**, with no failures, errors or skips, in
an isolated checkout of implementation commit
`66b7f30c592fac7191524f8ba4d19250336c9a3d`. The
[evidence manifest](../implementation/reports/evidence/modal-joint-20261001/manifest.json)
retains the release JUnit/output, authored smoke, exact formulas, source identities,
generated Lean projects/build logs and reproduction harness. It excludes weights.

The [operating guide](modal_joint_formula_training.md) documents activation,
training inputs, sidecar checkpoints, resume and inference. The
[historical investigation](historical_modal_decoder_research.md) documents why
the old spaCy/IR and vector reconstruction paths did not constitute an attached
learned formula decoder.

## Actual smoke

Each lineage used a fresh empty numerical core and a separate fresh learned
projection/head. Each trained on two authored examples for 250 optimizer steps,
with two reworded examples as observational tuning inputs. Embeddings were
explicitly synthetic. This tests wiring and reconstruction, not generalization,
semantic embeddings, archived checkpoint quality or conversion of federal law.

| Observation | Legacy 8D | Current 384D |
| --- | --- | --- |
| Formula token CE before → after | 2.96049 → 0.00106011 | 2.85867 → 0.000987620 |
| Projected embedding MSE before → after | 0.173304 → 0.000004236 | 0.155085 → 0.000051023 |
| Maximum formula-to-projection gradient norm | 0.09509 | 0.14428 |
| Training wall time | 1.950 s | 1.930 s |
| Inference wall time per authored span | 0.01643 s | 0.04698 s |
| Exact generated training-target ASTs | 2/2 | 2/2 |
| Actual decoded schema Lake builds | 2/2 passed | 2/2 passed |
| Fresh-process head reload | Exact inference match | Exact inference match |

The formulas included `O(submit(agency, reports))` and
`O(submit(agency, notices))`, generated from neural logits with no compiler or
target fallback. Both parameter groups changed and both numerical cores stayed
unchanged. The overall smoke took 13.62 seconds, including four actual
`lake build DecoderSchema` checks and fresh-process reloads. The saved head
files were 128,924 and 748,121 bytes; these sizes exclude the frozen core.

An initial 120-step 8D test still emitted the same object for both inputs. The
250-step fixture passed the unchanged exact-AST criterion. Low loss alone is
therefore not treated as a successful formula reconstruction or admission.

These runs used CPU, one Torch thread, temperature zero, no downloads, no
external provers, no sample memory and no Hub uploads. Bridge names were empty,
worker count was one, metric disk caching was disabled and
`legal_ir_target_count` was zero. No bridge-on evaluation ran: these timings
cannot be compared with the earlier five-bridge legal-IR measurements.
Per-span timings cover the small loaded fixture and exclude cold process/model
initialization. They are not measurements of a full archived checkpoint.

The separate smoke ran in the canonical working tree, whose unrelated parser
and core edits are recorded by hash. The implementation files matched the
tested commit. The 776-case release run used that exact clean commit separately;
the evidence does not equate the two source trees.

## Boundaries verified

The tests check exact Adam and partial-epoch resume; source/target identity;
cross-width and same-width legacy-profile rejection; missing decoder targets;
unaltered stored checkpoints; unknown vocabulary; tied or empty output heads;
and inference without target encoding, training or compiler calls. The default
attached inference path and vector reconstruction use the same learned
projection. Unconfigured historical numerical behavior remains available.

Review uncovered an old feature path that inspected per-sample logit keys even
with `use_sample_memory=False`. The new raw readout uses a private shallow view
with both memory tables excluded and fresh derived caches. It neither copies
the large sparse weight dictionaries nor swaps/mutates the caller's state.
Negative tests preserve poisoned owner memory while verifying unchanged outputs.

Lake checks bind the actual generated IR to the exact head, core, serialized
modal input and separately retained source string. Modified weights, input,
observations or purported build receipts fail closed. All four smoke builds
typechecked structural schemas; they did not prove source meaning or establish
`lake build Legal` admission.

## Remaining scope

The first attached head supports one canonical typed deontic rule within its
training vocabulary. It does not yet supply all eight required logic families,
source-only text understanding, or semantic qualification. Parser-derived
features remain part of the core input. Formula gradients train the new
projection and decoder, not the historical Python sparse tables. Intent,
Security and UI/UX retain their separate native projection/head implementations.

The joint profile requires explicit formula targets to activate; existing
services and fleet jobs were not silently switched. Its new sidecar schema
still needs explicit fleet/Hub transport integration. The known held-out
exception failure of the separate source-conditioned legal model is unchanged.
All qualification/admission flags remain false. The Constitution remains
unformalized.
