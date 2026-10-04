# Source-modality supervision and strict boundary replay

The controlled 384D comparison completed six fresh fits. Auxiliary supervision
fixed the original development fit (48/48 exact per seed), but did not improve
reconstruction on the previously exposed R6 cohort. Defaults remain unchanged;
no checkpoint is promoted and no qualification or Lean admission is claimed.

[Training interface and interpretation](../../../../autoencoders/source_modality_training.md)
| [Machine-readable results](results.json) | [Archive manifest](manifest.json)

## Results

Two seeds evaluated the same 48 paragraphs, giving 96 predictions rather than
96 independent examples. All fits completed 340 updates. Baseline selected states
remain at epoch 0, with 0/96 development and exposed exact reconstruction. Their
final states have 94/96 development exact and 61/96 exposed exact. Both auxiliary
arms select their final epoch 80 states with 96/96 development exact. The final
baselines substitute `examine` for `approve` in one two-rule paragraph per seed,
violating the unchanged extra-rule nonregression gate. Reference CE and input MSE
do not block those final baseline states; the gate remains unchanged.

| Final state | Exposed exact /96 | Modality /360 | Action /360 | Full-vocabulary CE | Total fit seconds | Training presentations/s | Greedy seconds/span |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | 61 | 302 | 359 | 0.028041 | 132.717 | 36.77 | 0.00826 |
| Used113 auxiliary | 57 | 301 | 357 | 0.029101 | 130.057 | 37.52 | 0.00836 |
| Full180 auxiliary | 58 | 293 | 360 | 0.027700 | 135.910 | 35.91 | 0.00821 |

Actor, object, conditions, exceptions and temporal fields are each 360/360 in
these final states. Full180 has lower cross-entropy than Used113, but eight more
modality mistakes. The next gap is source-modality generalization, not merely
reducing aggregate token loss. No fresh holdout or convergence claim is made.

Rates count 4,880 primary paragraph presentations per arm across two seeds;
positive arms also process 4,080 auxiliary clause presentations. Fit times include
scheduled validation but exclude later control panels and exposed evaluation.
Greedy timing covers 96 exposed predictions per arm, excluding teacher-forced
scoring. Baseline/Used113/Full180 fit seconds per primary presentation are
0.02720/0.02665/0.02785. These sequential CPU fits cannot establish a speedup from
small timing differences on a shared host. One worker, bridge names `[]`, prover
flag false, metric disk cache off, cached source vectors, encoder not executed.
No bridge-on evaluate ran or legal-IR targets were produced.

One Used113/1729 batch required strict retry: 37 token steps and 296 physical
row-tokens. Original batch membership and incremental execution recovered the
collected logits within unchanged tolerances. The failed bulk graph contributed
no loss. The other three auxiliary fits did not require retry. The baseline path
remains unchanged and exactly reproduces the archived numerical baseline.

The frozen scoped suite passed 3,434 tests, with zero failures, errors or skips.
Sixteen inherited incompatible 384D setup cases remain outside this suite and
are not counted as passes. The independent comparison audit passed 496,128
checks. The earlier failed attempt and successful replay diagnosis are retained,
with separate audits of 62,718 and 106,193 checks respectively. The run released
471,061,156 durable bytes and its owned lease. Thirty live RSS samples had a
maximum of 1,502,552,064 bytes; the absolute peak was not measured. Child elapsed:
562.405s; guardian/reservation elapsed: 613.918s.

## Retained evidence

The new comparison includes 18 initial/selected/final states, six training
reports, 108 original endpoint/control panels, and all 12 exposed endpoint
predictions plus 12 score panels. Every exposed prediction was saved before the
references were opened. Selected and final endpoints are both retained.

The archive also contains frozen source/test trees, plans, authenticated bank
bindings, all auxiliary and replay logits, committed exposure counts, resource
receipts, tests, audits, outcome summarizer and publication helpers. Under
`prior-attempt/` it preserves the failed original comparison, its completed
baseline, failed positive initialization and the successful guarded diagnosis.
Those artifacts are not counted as newly completed fits. The historical trainer
actually imported by the runner is separately retained under
`historical-source/parent_extension/`; the new opt-in trainer is under `source/`.

## Verify and reconstruct

Download the ordered `archive_parts` listed in `manifest.json`. Verify each
part's byte length, offset and SHA-256, concatenate in manifest order into
`evidence.tar.xz`, and verify the full archive against `archive`. Then verify each
regular member against `members` before using it. Parts are at most 48,000,000
bytes and use xz compression. Do not infer part order from an arbitrary directory
listing.

This archive is not standalone. The manifest records authenticated predecessor
archives and Git blobs in `archive_dependencies` and `referenced_artifacts`.
Follow that chain to recover unchanged inputs. The original R6 evidence was
published at commit `1b6461e65f15635b89d04609dae01a4196cd3ea5`; this archive may
reference identical evidence from its later verified ancestor-compatible base.
`original_artifact_archive_paths` maps recorded absolute paths to archive members.
Installed libraries, hardware, verified local encoder assets and protected
parent weights remain external. No model weights were downloaded for these fits.

These private numerical JSON states omit optimizer state and are not resumable
training jobs or production checkpoints. The identity input projection is frozen;
its MSE is not learned reconstruction. The 8D linguistic teacher is unchanged,
and 768D, other IR modalities, statutory semantics and broader logic-family
coverage were not tested by this 384D authored-codec experiment. Temperature 0
and encoder/decoder limits 512 remain unchanged. Lake and external provers were
not executed. Only `lake build <Lib>` can admit the corresponding Lean artifact.
The Constitution remains unformalized, with no new `roundtrip_ok` spans.

## Publication integration

The numerical study remains bound to its original frozen dependencies. A separate
candidate based on `b11f2514a0180fdbebb4bcd878beef21885cb7db`, with the eight owned
Python changes overlaid, passed the same 3,434 scoped tests in 71.15 seconds after
a focused historical8 feature test. All three original compiler/decompiler gates
also passed, including empty-vocabulary abstention, the non-renderable 10-day
within-duration obligation with emergency exception, the prohibition, and the
minimum-duration20 threshold. No Lake build or admission is inferred.

Earlier integration attempts are retained under `validation/publication-integration/`:
a harness looked for temporal metadata on the raw rule instead of its real parser
sidecar; pytest path reporting conflicted with a deliberate no-import test; and
the initial Python-only checkout omitted legacy snapshot JSON metadata. The final
candidate contains all three exact tracked legacy manifests. Tests, model sources
and weights were not changed to repair those environment issues.

The manifest distinguishes historical numerical `source/` members from the five
reviewed incoming `publication-source/` dependencies. The full temporary candidate
checkout is excluded; exact Git provenance, retained source closure, tests and
receipts are recorded instead. The six-fit comparison was not rerun on the newer
sources. In particular, the scoped suite exercises the preserved legacy snapshot,
not the main `modal_autoencoder.py` runtime or its new lazy worker-budget helper.
Static review restricts that runtime's AST difference to
`_legal_ir_parallel_worker_count`, with unchanged signature; execution of that
new scheduling path is not certified. No additional quality or speed claim is
made from this integration check.
