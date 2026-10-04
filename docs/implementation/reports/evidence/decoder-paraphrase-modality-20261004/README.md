# Balanced paraphrase modality training evidence

## Balanced TRAIN paraphrase modality supervision (2026-10-04)

This follow-up adds modality supervision without replacing any original decoder
batch. It compares auxiliary weight 0 with 0.05 at 384D and 768D, using the same
selected R13 parents, seed 1729, fresh AdamW/scheduler, and four curriculum stages.
Only formula-decoder heads train. The semantic encoders, 8D linguistic teacher,
and existing 4096D endpoints are unchanged. This does not rerun all four widths.

The 180 authenticated R4 TRAIN clauses comprise 30 actor/action/object combinations,
three modalities, and two renderings. Each committed update selects one clause
from each modality/template stratum. Both arms execute the auxiliary forward;
the zero arm attaches no auxiliary loss graph. The positive arm adds 0.05 times
mean full-32-vocabulary modality cross-entropy. Original batches, count supervision,
action/boundary objectives, and the inherited 384D auxiliary remain unchanged.

Each fit completes 170 updates, 1,220 paragraph presentations, 112,920 valid target
tokens, and 12,800 source-value positions. Both arms observe 1,020 auxiliary clauses;
only the positive arm supervises those additional clauses. Thus this is not an
equal-supervision or equal-FLOP comparison. The zero arm must exactly replay the
archived original-only continuation, including ordinary update math and tensors.

The tables below report selected endpoints; the archive also retains every last-attempt endpoint.

| Width | Auxiliary weight | Fit seconds | Rows/s | Original development exact | Original CE | Exposed wording exact | Exposed CE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 384D | 0 | 40.964 | 29.78 | 48/48 | 0.001699422 | 20/48 | 0.030589255 |
| 384D | 0.05 | 42.164 | 28.93 | 48/48 | 0.001698302 | 19/48 | 0.028552217 |
| 768D | 0 | 50.002 | 24.40 | 48/48 | 0.001704642 | 46/48 | 0.003361466 |
| 768D | 0.05 | 50.582 | 24.12 | 48/48 | 0.001704568 | 46/48 | 0.003004750 |

The 48-source wording panel was exposed in prior experiments. Its references
are used only after all eight endpoint predictions have been saved. It cannot
select or promote a checkpoint and is not a fresh holdout. The original nine
panels run at both selected and last-attempt endpoints for all four fits.

| Width | Arm | TRAIN modality correct: parent → selected | TRAIN modality CE: parent → selected |
| --- | --- | ---: | ---: |
| 384D | paraphrase-modality-zero | 180/180 → 180/180 | 4.80199196e-05 → 2.95881081e-05 |
| 384D | paraphrase-modality-ce | 180/180 → 180/180 | 4.80199196e-05 → 4.80473656e-06 |
| 768D | paraphrase-modality-zero | 180/180 → 180/180 | 5.09461449e-05 → 3.15194383e-05 |
| 768D | paraphrase-modality-ce | 180/180 → 180/180 | 5.09461449e-05 → 7.21434076e-06 |

Both parents already classified all 180 TRAIN paraphrases correctly. These
readouts distinguish confidence changes on the training bank from reconstruction
on other wording; low training loss alone is not evidence of generalization.

At 384D, the positive arm changes exposed exact reconstruction by -1/48 and modality correctness by -3/180; token CE changes by -0.002037038. No checkpoint is promoted.

At 768D, the positive arm changes exposed exact reconstruction by +0/48 and modality correctness by +0/180; token CE changes by -0.000356716. No checkpoint is promoted.

### Remaining reconstruction gap

The 384D candidate regresses exact reconstruction despite lower CE, so it is not
a replacement for the baseline. The 768D candidate lowers CE without correcting
either remaining exact error. Training-bank confidence is therefore insufficient
for acceptance. Keep this objective opt-in and retain the zero-control checkpoints.

One saved 384D example is: “The secretary is obligated to publish the notice.”
The authored target is obligation `O`, the baseline emits permission `P`, and the
candidate emits prohibition `F`; actor/action/object remain secretary/publish/notice.
Another example changes a correctly decoded obligation for a trustee into
permission while retaining the second clause. These are semantic errors even
though the generated structures are syntactically valid. The independent style
review retains complete source text, targets, and both decoded rule structures.

The next experiment should prepare broader TRAIN-only normative wording and
separate fresh evaluation material before fitting, then measure modality margins
and exact rule reconstruction by wording family. Preserve ordinary decoder work
and the exact zero replay control. Do not increase a saturated auxiliary merely
because its training CE falls, and do not relabel the exposed v3 panel as fresh.
This is a proposed follow-up; no further fit or encoder execution was performed.

### Timing and resource scope

Two widths run concurrently with one reserved CPU and 1,536 MiB per width; arms
run sequentially within a width. Fit timing includes the training call and its
validation/selection work. It excludes process startup, admission, outer artifact
checks, and the separate observer. Shared-host measurements are not an isolated
repeated throughput benchmark. Source vectors are warm authenticated caches;
the semantic encoder does not execute. Generation temperature is 0 and encoder
context/decoder output limits remain 512. Bridge names are `[]`, external prover
evaluation is false, and the legal-IR metric disk cache is disabled. No bridge-on
evaluate timing or legal-IR speedup is claimed. Observer milliseconds per span
measure generation and scoring only; they exclude endpoint restoration, source
authentication, artifact persistence, and guardian overhead. They are not
end-to-end inference latency.

| Width | Arm | Observer generation ms/span | Generation + scoring ms/span |
| --- | --- | ---: | ---: |
| 384D | paraphrase-modality-zero | 7.678 | 15.138 |
| 384D | paraphrase-modality-ce | 7.712 | 15.085 |
| 768D | paraphrase-modality-zero | 9.273 | 18.147 |
| 768D | paraphrase-modality-ce | 9.364 | 20.740 |

Two initial training admissions failed before any child launched because the
persisted scheduler configuration did not match the strict adapter. The exact
failed configuration bytes were not captured; its cause is unestablished. Later
read-only observations matched both successful preflights, so the unchanged guard
was retried under fresh `training-384-r2` and `training-768-r2` names. Both initial
400 MB claims and failure receipts remain retained; no scheduler reset, foreign
lease cleanup, or cap relaxation was performed. Successful retry resources and
observer resources must be released before publication.

### Validation and evidence

The implementation has 232 passing focused tests, with no skips. These include
published-default numerical replay, zero-weight gradient/RNG parity, ordinary
stream preservation, complete provenance and exclusion checks, immutable caches,
deadline abort handling, and the observer barrier. Independent reviews verify
the source freeze, both preflights, saved updates/readouts, and publication scope.

The numerical dependency is the explicitly frozen local `validation-source-r2`
tree plus manifest-bound extensions. It is not an HACC import or a measurement
of the current canonical compiler. External model assets are authenticated but
not copied into the public evidence archive. All full predictions, loss reports,
states, guards, test receipts, failed attempts, and source identities are retained.
The archive links to the previous TRAIN-mixture evidence for transitive inputs.

See [the complete results and archive](results.json).

This is restricted authored-rule reconstruction. The corpus has empty qualifiers,
so it does not establish temporal/exception/condition coverage, all-family fidelity,
statutory formalization, convergence, or a global minimum. No Lake build runs here;
only an actual `lake build <Lib>` may grant Lean admission. The Constitution remains
unformalized. Every qualification, admission, and promotion flag remains false.


The split gzip tar parts in `manifest.json` concatenate in listed order. Verify each SHA-256, the combined archive hash, and all member hashes before extraction. No pretrained encoder weights or native backend binaries are bundled.
