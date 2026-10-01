# Distributed 384d native projection integration — 2026-10-01

Validated implementation: [`34352be1`](https://github.com/endomorphosis/ipfs_datasets_py/commit/34352be1fec864758db6f49dfcd5c98e30b8d970).
This run exercises unchanged merged checkpoints from the
[previous local/Hub training round](../distributed-384-local-hub-20261001/README.md)
and the additive [projection workflow](../../../../autoencoders/distributed_384_projection_context.md).

The original wiring used older adapters without a portable context input. The
new bridge accepts exact source/candidate-bound declarations and reaches the
v7 native owners. It preserves Security program provenance during Lean lowering,
removes retired Intent facts from active coverage, exposes auxiliary dependency
coverage, and distinguishes native syntax/type checks from complete semantics.
The reviewed-pair importer checks source/target and embedding identities and
keeps connected source families, including the same record across revisions,
out of opposing training/validation splits.

## Actual checkpoint predictions

One explicitly selected tuning row per domain was inferred from the existing
merged checkpoint using only ID, source text, and its previously computed GTE
embedding. The same unchanged prediction was checked without context and with
eight caller-authored formula declarations. Security also received an explicit
authored CodeUnit, retaining its source-derived program projection.

| Domain | Supported selected families, candidate only | With declared context | Native projection checks with context |
| --- | ---: | ---: | ---: |
| Intent | 5/8 | 8/8 | 19/19 |
| Security | 1/9 | 9/9 | 9/9 |
| UI/UX | 1/8 | 8/8 | 9/9 |
| Legal | 1/8 | 8/8 | 9/9 |

Checks used real Lean 4.34.1 `lake build`; generated TLA+ additionally passed
SANY using Java 17. The eight formula families are first-order, deontic,
temporal, temporal-deontic first-order, cognitive event calculus, deontic
cognitive event calculus, frame logic, and propositional logic.

Intent's auxiliary control-flow state is explicitly partial. Its syntax checks
pass, but `all_auxiliary_families_supported` and
`all_requested_dependencies_supported` remain false. The other three selected
profiles have complete declared dependency coverage. This is coverage of supplied
fragments, not complete target or source semantics.

**The additional formulas are caller declarations, not checkpoint predictions.**
This comparison measures adapter access and native compilation. It does not
measure improved learned reconstruction, new held-out accuracy, or a natural
CVE/SkillCenter corpus benchmark. No weights were trained or changed.

## Separately authored native models

These controls exercise wider models that the current narrow checkpoints do not
emit. They are recorded separately from model inference.

| Control | Requested family coverage | Native checks | Result |
| --- | ---: | ---: | --- |
| Security, all declared families | 12/16 | 15/19; SANY 1/1 | Four unsupported emitters retained |
| Security, explicitly supported scope | 12/12 | 15/15; SANY 1/1 | Pass |
| Guarded Intent, maximal profile | 11/16 | 23/23; SANY 1/1 | Missing/partial families retained |
| Guarded Intent, explicitly supported scope | 11/11 | 18/18; SANY 1/1 | Pass |
| Matched UI with confirmation, maximal profile | 9/11 | 15/15; SANY 1/1 | Missing families retained |
| Matched UI, explicitly supported scope | 9/9 | 15/15; SANY 1/1 | Pass |
| Intent with false precondition | Incomplete | 19/23 | Four guarded projections blocked |

The Security native projections for **authorization, concurrency, cryptographic
protocol, and refinement still lack semantics-preserving Lean emitters**. They
are reported, not filtered from the maximal result. Intent's maximal profile
also retains partial DCEC/TDFOL/higher-order views and absent authorization and
refinement models. UI's maximal profile lacks program and authorization models.

Reviewed, correctly paired natural source/IR targets remain necessary before
training richer decoder schemas. Weak structural targets, vulnerability labels,
and manually supplied generic formulas are not substitutes. All proof authority,
admission, source-fidelity, and promotion flags remain false.

## Tests and artifacts

The logs record 494 passing regression cases (three skips), 59 final projection
cases, 36 reviewed-export cases, 13 final qualification/CLI cases, and 105 checks
against the concurrently published readiness/parallel-prover modules. Eleven
qualification cases occur in both the regression run and final targeted rerun;
counting them once gives **696 distinct passing tests, three skips**.

- [Results and complete artifact hashes](results.json)
- [Native sources, contexts, reports, Lean files, receipts, and reproduction scripts](evidence.tar.gz)
- [Immutable Hugging Face publication references](hub-references.json)
- [Projection tests](projections.log), [qualification/CLI tests](qualification.log),
  [reviewed export tests](paired-export.log), [regressions](regressions.log),
  [readiness integration](upstream-integration.log)

The archive contains `checkpoints-run-03`, `security-authored/run-02`, and
`intent-ui-authored/run-04`. Reproduction scripts require the pinned repository
checkout, the previous round's inputs/checkpoints, and explicit installed tool
paths. Use a fresh output directory. The local earlier diagnostic runs are
preserved separately; the final archive uses Java 17 and stable producer files.

Each Publicus model repository received an append-only
`training/structured384/<plan_id>/projection-checks/<manifest_sha>/` artifact.
Every manifest and archive was downloaded at its returned immutable Hub commit
and SHA-verified. The manifest links the exact existing checkpoint publication.
Published weights, inference defaults, and completed numerical round contracts
were not replaced.
