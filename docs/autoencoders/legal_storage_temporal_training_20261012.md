# Paired source-only temporal role contrast experiment

Two diagnostic checkpoints from attempt `temporal-role-contrast-20261012-03` are archived together. Each arm completed 32 new Adam updates from the same retained source-only parent weights. The optimizer moments were initialized afresh. These checkpoints are research artifacts; neither is selected as the default decoder.

The configured latent width is 384, with latent conditioning disabled and zero autoencoder calls. This experiment measures the source-text span decoder and saved joint selection. It does not measure genuine 8D, 384D or 768D latent decoding. Separate temporal boundary code in this release is engineering evidence and was not fitted as a model capability.

## Saved results

Exact IR counts against the frozen, authored engineering references:

| Panel | Rows | Baseline raw / joint | Control raw / joint | Contrast raw / joint |
|---|---:|---:|---:|---:|
| Older tuning | 96 | 96 / 96 | 96 / 96 | 92 / 92 |
| Fresh tuning | 36 | 0 / 0 | 0 / 7 | 8 / 19 |
| Fresh challenge | 36 | 7 / 7 | 10 / 10 | 25 / 25 |

Contrast improves the authored challenge result to 25/36, while losing four older matches: three permission-to-obligation errors and one missing temporal clause. Its eleven remaining challenge failures comprise six actor spans, three combined condition/temporal cases, one object span and one modality decision. Saved joint selection improves fresh tuning, but adds no challenge matches for either trained arm.

The reference rows and challenge sources were authored and already exposed. The eight law-source observations have no independently reviewed reference targets and yield no semantic accuracy estimate. No statutory fidelity, independent semantic holdout, statistical significance, compiler success or broader logic-family qualification is claimed. `lake build legal` was not executed.

## Training and verification

Control trains on 108 rows and contrast on 168, with 96 shared rehearsal rows, batch size 12, learning rate 0.001, clipping 5 and seed 1729. Equal update counts do not imply equal data exposure: the arms have different populations and batch schedules. This single-seed comparison does not isolate a causal curriculum effect.

The retained parent records 400 historical steps, which are provenance rather than resumed optimizer progress. Each new checkpoint records 32 fresh steps. Independent saved-result review validates all 55 result JSON files, finite checkpoint serialization, copied parent initialization and completed schedules; it replays 528 saved joint selections and verifies 504 authored score rows without model restoration or another forward pass. Numerical runtime updates are supported by the completed child reports and checkpoint progress, not independently traced gradients.

The unchanged resource guardian reports a successful, durable, released run. Sampled model-phase RSS peaked at 731,029,504 bytes under a 1,536 MiB reservation; sampling does not prove an absolute peak or a kernel memory cap. The terminal attempt occupies 25,751,059 bytes under its 200 MB storage reservation. A separately reviewed historical 4 GB reservation closeout preserved all 109 files, 16 directories and eight sibling files. No historical checkpoint was deleted or adopted.

## Reproduction and next experiments

The release contains both checkpoint JSON files, saved outputs, immutable input/source pins and the actual successful-attempt reviews. Absolute historical paths in the recipe require explicit environment binding; this archive is not a portable turnkey training installation. The full local reservation ledger and the two runtime receipts containing full owned record bodies are excluded. Their byte identities remain referenced in review metadata.

1. Separate actor-span learning from temporal presence learning. Add length-stratified actor diagnostics and legal names containing duration-like tokens. Keep absence cases so a duration inside an actor or object cannot create a temporal clause.
2. Address the three old modality regressions with balanced permission/obligation/prohibition rehearsal and matched condition/exception pairs. Report each regression alongside fresh gains; do not choose a checkpoint using the challenge results.
3. Use matched training budgets and multiple seeds to separate curriculum, loss weighting and joint-selection changes. Freeze a new untouched evaluation split before fitting. Retain both source-only and genuine latent-conditioned arms for each independently verified autoencoder width.
4. Establish an independently reviewed US Code reference set with exact source-version, provision, span, context and annotation provenance. The user-specified `justicedao/open-us-law-span-cache` and `justicedao/uscode-autoformal-span-cache` are candidate sources, not automatic gold standards. Split by statutory provision and connected cross-reference groups, not random spans.
5. Gate promotion on source-faithful actor/action/object/modal/condition/exception/temporal checks, abstention on unsupported statements, and explicit support matrices for the actual logic-module families. Family adapters must declare unsupported constructs instead of silently discarding them.
6. Run generated Lean through a pinned toolchain and the real `lake build legal` target in isolated resource-owned jobs. Record complete attempts, failures and axioms used. Compilation validates typing and syntax; reviewed semantic correspondence must be evaluated separately.

The immediate next experiment should target the named failures while preserving older behavior. Statutory and cross-family deployment remains gated on independently reviewed legal references, real latent comparisons and executed compiler checks.
