# Completed 384D two-bank decoder replay

One 170-update fit retained complete formula reconstruction on the original,
old normative and new balanced TRAIN wording sets: each scored 48/48 paragraphs
and 180/180 rules on every measured facet. Previously exposed development wording
scored 30/48, below the archived control's 33/48. This is a successful TRAIN
retention experiment with a development regression, not a generalization or
throughput improvement. No checkpoint was promoted or granted qualification.

## Reconstruction and loss evidence

| Complete ordered paragraph reconstruction | Parent | Archived control | Archived balanced replacement | Two-bank replay |
| --- | ---: | ---: | ---: | ---: |
| Original TRAIN | 48/48 | 48/48 | 48/48 | 48/48 |
| Old normative TRAIN | 48/48 | 48/48 | 33/48 | 48/48 |
| New balanced TRAIN | 48/48 | 48/48 | 48/48 | 48/48 |
| Previously exposed v3 | 31/48 | 33/48 | 19/48 | 30/48 |

Parent figures come from archived generation evidence. The archived control is
the explicit baseline for the complete formula/site retention gate; actual
unchanged parent readouts provide its separate auxiliary-bank floors. This run
has one fresh optimizer and scheduler, not an exact Adam resume or a fresh
matched control. Bank composition and auxiliary chronology both change. The
selected and last-attempt roles share tensor SHA
`6e47fc6d5452bd0becbe4e36e60be7ee0a388d969dad68dc817123307412cea5`;
eight physical evaluation panels do not constitute independent fits.

Old-bank source-modality CE fell from 0.02081259 to 0.00529710; new-bank CE fell
from 0.01155769 to 0.000689201. Both remain 180/180 correct. The old source action
head remains 179/180, while the combined decoder reconstructs that action
correctly. The new bank already scored 720/720 source fields and 48/48 complete
formulas at the parent, so its lower CE is a confidence change.

All 5,760 reference scalar sites were visited and scored across eight panels;
17,280 full32 source, recurrent and combined distributions were retained. TRAIN
cohorts have all seven facets correct, complete EOS/cardinality/order, and zero
missing or extra rules. The v3 set has 158/180 correct modalities, 179/180 actions,
and 23 substituted rules. Its full-rule unmatched counters retain both sides of
each substitution. Relative to the archived control, three paragraphs become
wrong and none are repaired. All 22 wrong combined modalities have expected
modality `O`. Nineteen source modalities are wrong; three correct source
modalities become wrong in the combined output. These are observed arithmetic
relationships, not a causal isolation of the recurrent contribution.

The [complete comparison](evidence/dual-bank-replay-20261007/postfit-comparison.json),
[development error census](evidence/dual-bank-replay-20261007/development-error-census.json) and
[actual model formula samples](evidence/dual-bank-replay-20261007/sampled-model-formulas.json) retain the evidence.
Samples include actual generated IR and expected authored IR, without a
fabricated compiler/prover translation. The numerical retention gate passed for
both endpoint roles after unchanged checkpoint selection. v3 and sealed labels
were not fit or checkpoint selectors. All targets describe authored, previously
exposed meanings; the qualifier fields are empty and the vocabulary contains
32 tokens. This experiment does not measure natural-law semantic fidelity.

## Runtime and measured cost

The new private adapter validates two complete, distinct control13/balanced16
source inventories and their native384 caches. At update `t`, it dispatches one
six-clause full32 modality CE to bank-local ordinal `floor(t/2)`. Each bank receives
85 updates and 510 presentations, covering all 180 sources two or three times.
Four actual templates receive 255 presentations each. Authentic bank-local
receipts are nested without relabeling; aborted forwards consume no sampler
state. Counts derive from actual optimizer-committed receipts.

Original decoder/count streams remain 1,220 row presentations and 112,920 target
tokens; source-value presentations remain 12,800. The inherited used113 stream,
backward/clipping, original selection and original protected working-model copy
remain unchanged. The adapter adds no model copy. Both inherited and reconciled
reports are saved; the former single-bank template counter is retained as
inapplicable metadata rather than represented as actual dual-bank coverage.

| Owned phase | Driver wall time | Outer wall time |
| --- | ---: | ---: |
| Two-bank preflight | 32.691 s | 65.427 s |
| Training and original panels/readouts | 102.202 s | 143.809 s |
| Eight-panel source/formula observation | 29.038 s | 65.863 s |

The numerical fit call took 43.473 s, or 28.063 original row presentations/s.
Cached greedy generation took approximately 9–12 ms per paragraph. These timings
exclude semantic encoding, current canonical compiler, bridge-on legal IR and
provers. Settings: CPU1/worker1, batch8, temperature0, context/output512,
bridge names `[]`, prover flag false, metric disk cache false. Source vectors were
already cached; OS cache state was uncontrolled. This is not a cold legal-IR
speed measurement. The earlier archived single-bank fits took about 38 s;
different auxiliary chronology and this one trial do not establish a speed gain.

All phases used fresh locked admission under the existing 145 GB named-root cap.
Largest sampled training RSS was 1,198,592,000 bytes, below 1,536 MiB; this is not
a measured peak. Training retained 131,347,683 bytes under its 400 MB reservation.
Preflight/evaluation each used a 100 MB reservation. Every owned lease was
durably released and its process group ended. Final evaluation accounting was
143,549,691,872 bytes. No cap increase was required.

## Entrypoints and provenance

- [Runtime explanation](https://github.com/endomorphosis/lift_coding/blob/main/artifacts/autoencoder-dual-bank-replay-20261007/runtime/README.md),
  [frozen driver](https://github.com/endomorphosis/lift_coding/blob/main/artifacts/autoencoder-dual-bank-replay-20261007/runtime/experiment-source/scripts/ops/autoencoder/benchmark_dual_bank_replay.py),
  [adapter](https://github.com/endomorphosis/lift_coding/blob/main/artifacts/autoencoder-dual-bank-replay-20261007/runtime/experiment-source/dual_bank_runtime_adapter.py) and
  [phase profiles](https://github.com/endomorphosis/lift_coding/blob/main/artifacts/autoencoder-dual-bank-replay-20261007/runtime/phase-profiles.json) describe inference and training.
- [Evaluation writer](https://github.com/endomorphosis/lift_coding/blob/main/artifacts/autoencoder-dual-bank-replay-20261007/evaluation/source/evaluate_dual_bank_replay.py) runs
  source-only greedy generation and same-pass readouts, then scores complete
  formulas. All eight prediction panels are fsynced before this writer parses
  explicit v3 references; inherited TRAIN/validation metadata was already known.
- [Comparison protocol](https://github.com/endomorphosis/lift_coding/blob/main/artifacts/autoencoder-dual-bank-replay-20261007/predeclared-protocol.json), three guardian readiness
  reviews and three actual-output audits pin inputs and numerical source owners.
  Model work was performed only through owned `run_guardian.py` phases. Completed
  attempts are immutable; reproduction requires fresh attempts and reviewed
  manifests, never execution of an old receipt as a launch authorization.
- [Concurrent main progress](https://github.com/endomorphosis/lift_coding/blob/main/artifacts/autoencoder-dual-bank-replay-20261007/pipeline/concurrent-main-progress.json) records
  the separately published dual-bank adapter/probe, trigger-readout experiment
  and finite scheduling work. Their source and evidence remain on main. This
  frozen numerical run does not replace those independently reviewed paths.

The original paragraph384 vectors retain caller-byte authentication without
producer receipts. Normative/new384 vectors retain their verified local producer
evidence. Numerical/schema owners come from the explicitly declared historical
snapshot; schema validation is not current canonical parsing/compilation. No
canonical parser/compiler/decompiler repair, encoder call, native-family check
or Lake build was performed. Compiler-facing admission must use the workspace
logic tree and its tree-pin guard. Only a real `lake build <Lib>` can admit Lean.
The Constitution remains unformalized. The 8D teacher and 768D/4096D paths were
not changed. No weights were downloaded, registered, promoted or uploaded.

The evidence archive retains full new owned-phase reports, predictions, logits,
source and review history, with hashes. Checkpoint tensor bodies remain local
immutable references. Some saved observations contain cached/normalized vectors;
the archive is not vector-free. Historical input-owner/cache custody is supplied
by the previous balanced-wording evidence archive and complete dependency maps.

## Next training gap

Retaining both TRAIN banks solves the bank-replacement regression but does not
solve the exposed development wording. The next ablation should separately control auxiliary
chronology, inspect original versus paraphrase action supervision, and test a
declared TRAIN-only distribution-preservation or contrastive objective against
an equal-budget control. Previously exposed v3 remains development evidence;
new independent semantic material is needed before a generalization claim.
Profile changed training work before choosing an acceleration backend. Longer
spans and other dimensions need their own lineage recipes, compatible decoders,
logic-family checks and Lake evidence; this384 diagnostic cannot qualify them.
