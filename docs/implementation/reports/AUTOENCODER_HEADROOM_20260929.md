# Campaign headroom and native retry

The operator authorized more headroom after the parallel smoke was blocked by
the campaign accounting cap. The cap is now **85,000,000,000 bytes**, increased
from 80,000,000,000. This is a campaign limit, not a filesystem quota.

The fresh migration census counted 49,263,988,111 bytes of files plus
30,715,000,000 bytes of outstanding reservations. Increasing the cap leaves
**5,021,011,889 bytes of headroom**, sufficient for the unchanged 300 MB smoke
reservation and a margin for temporary-file growth. The filesystem had
171,450,126,336 bytes free at that census.

The lock-held migration changed only the ledger's top-level limit. All 185
existing reservation records retain the same content digest, including failed
attempts and historical accounting. No checkpoints, evidence, temporary outputs
or retained claims were deleted. Per-worker bounds and all qualification
thresholds remain unchanged. An old-cap ledger still fails closed until an
explicit migration; merely updating the code does not rewrite another machine's
ledger.

The resource and recovery tests pass: **87 tests in 5.80 seconds**, including
explicit migration from an 80 GB ledger while preserving its history. The
successor smoke controller also passes seven tests.

The earlier shared-target artifact is preserved. Fresh target preparation is
required because full producer provenance includes the changed resource module
and an independently edited software-contract module. The successor uses the
same six training and two tuning samples with verified local 384-dimensional
embeddings, all five bridges, provers disabled, metric disk cache disabled, one
target worker, and sample memory disabled. No weights are downloaded. The
independent canary remains untouched until a fully qualified immutable selection.

Only a successful source-locked `lake build Legal` is a Lean admission. A target,
training improvement, syntax check, text cycle or persisted patch has no proof
authority. The Constitution remains unformalized. The prior
[readiness report](AUTOENCODER_TRAINING_READINESS_20260929.md) explains the known
source/IR/Lean qualification gaps separately from this storage blocker.

## Native retry observations

Fresh preparation completed all eight targets with no timeout or partial report.
Cold target generation took **117.100 seconds, or 14.638 seconds per span**;
the supervised preparation took **144.825 seconds**. The exact bridges were
`modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec` and
`external_prover_router`. Provers were false, metric disk cache was zero, target
workers one, and sample memory false. OS cache warmth was uncontrolled.

Storage admission then succeeded for two native workers. Their receipts record
the following diagnostic observations:

| Observation | Fixed rate | Productive policy |
| --- | ---: | ---: |
| Accepted epochs | 1 | 1 |
| Training call, seconds | 17.243 | 18.774 |
| Training call per training span, seconds | 2.874 | 3.129 |
| Complete worker wall time, seconds | 37.648 | 40.468 |
| Complete worker time per training span, seconds | 6.275 | 6.745 |
| Verified sparse update, bytes | 15,370,309 | 15,370,319 |
| Initial bridge-on evaluation, two spans/targets, seconds | 1.751 | 1.826 |
| Training-prime bridge-on evaluation, six spans/targets, seconds | 8.582 | 9.377 |
| Two proposal evaluations, two spans/targets each, seconds | 1.438 / 1.494 | 1.557 / 1.531 |

The enclosing dispatch completed both workers in 44.746 seconds. Each used six
training and two repeated tuning spans, `python_sparse_batch`, one epoch and two
line-search attempts. Both selected the structural decoder proposal at effective
learning rate 0.175. The five bridges and flags above apply to every listed
bridge-on evaluate. Evaluations reused verified shared targets, generated no new
targets and had no timeout fallback; they are not cold compiler timings. The IR
worker request was one, with zero generation workers needed for shared targets.
The owner verified sparse replay and compacted each candidate to the same
4,667,467-byte full checkpoint. This proves a persistence operation, not admission.

These are **unsealed observations from an invalidated attempt**, not a passing
smoke or a certified speed comparison. Another process changed
`logic/software_verification/source_adapters.py` during qualification, and the
whole-package source guard stopped the stage before its completion seal. A later
edit to `logic/software_verification/pipeline.py` also prevents reuse against the
current source. Core parser/compiler/decompiler hashes and the protected
restart12 checkpoint did not change. The guard was not bypassed or narrowed.

Both candidates passed the existing metric and local tuning-split checks, but
failed the semantic, family-coverage and Lake gates on all eight real-law rows.
Sixty-six clause projections per candidate parsed across the six logic families;
that does not establish source coverage or aggregate family qualification.
**No actual Lake build ran**: real-law clauses failed source-roundtrip checks
before invocation, and the source-guard failure preceded the separate fixture
phase. The independent canary was not evaluated. No promotion, Hub upload or
eight-hour run occurred.

The raw decoder cosine on the two tuning spans improved from 0.196116 to
0.242829; raw reconstruction loss moved from 0.002527083 to 0.002502733. The
reported post-projection cosine of 1.0 and zero reconstruction loss use the
existing input-dependent safety projection. They do not demonstrate independent
formalization quality or a global minimum. IR view cross-entropy remained
1.589026915. All acceptance arithmetic and thresholds stayed unchanged.

After verifying the owner and child groups had exited and fsyncing the complete
34-file inventory, explicit reconciliation released only this new failed
attempt's 300 MB claim. Its 104,500,056 bytes of artifacts remain charged and
preserved. All original 185 records are still unchanged. The fresh closeout
census leaves **5,320,313,170 bytes of headroom**.

The next validation needs a stable package-source window plus the source/IR/Lean
repairs described in the prior readiness report. More storage alone cannot make
these candidates qualified. Publication preserves existing main-branch logic
changes; native observations bind the canonical working tree's recorded hashes,
not an exact clean-main benchmark.

Portable evidence: [manifest](evidence/autoencoder-headroom-20260929/manifest.json).
