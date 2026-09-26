# Legal autoformalization speed measurements — 2026-09-24

Training and inference are faster without changing compiler results or the
admission boundary. Lake (`lake build <Lib>`) remains the only Lean admit.
Nothing in these measurements is an admit; the Constitution is not formalized.

The main change is in `logic/deontic/formula_builder.py`. Its normalizers walk
more regex patterns than Python's shared regex cache retains. The initial
eight-span profile spent 98.4 of 101.5 seconds compiling regexes across the
vocabulary/compiler calls. A local LRU now retains at most 2,048 compiled
patterns. Pattern text, flags, matching order, formulas, and parser results are
unchanged. This caches regex programs, not sentences, parses, or outcomes.

`autoformal.compile_span` reuses its vocabulary extraction when the selected
clause has exactly the same text and has no existing vocabulary. Segmented
text and stored vocabularies, including empty vocabularies, retain their prior
behavior. The compiler still parses with its own measured configuration; its
empty-vocabulary abstention is unchanged. Compiler and decompiler code were
not changed for this speed work.

The US Code daemon also reuses a bridge evaluation when it already covered
every original, unbounded sample with the native evaluator and alias hook.
Bounded samples and custom evaluators retain their second pass. The supervisor
retains its base-before-bridge ordering because caching targets can affect its
base metrics. An empty bridge still reports zero targets and empty IR losses.

All wall comparisons below are unprofiled observations on the same machine.
The pre-change builder matches repository revision
`ddf6b79467b68159650df81befc288c8553df664`. Raw receipts retain source hashes.

| Scope | Samples | Before | After |
|---|---:|---:|---:|
| Vocabulary extraction, mean per Article I span | 8 | 1.5057 s | 0.02393 s |
| Separate typed compiler call, mean per span | 8 | 1.5118 s | 0.01941 s |
| Existing `compile_span` path, mean per span | 8 | 3.1213 s | 0.02322 s |
| Full Constitution compiler-only census | 231 total / 166 operative | 417.0 s (prior live run) | 3.9896 s |
| Bridge-on evaluate, total | 3 | 27.3651 s | 11.0742 s |
| Bridge-on evaluate, per sample | 3 | 9.1217 s | 3.6914 s |
| One bounded projection epoch, total | 3 | 27.9252 s | 11.4884 s |

The compiler-only census now averages 0.01727 seconds per inventory span,
or 0.02403 seconds per operative span. The eight-span benchmark times separate
vocabulary/compiler calls before its span calls, so compiled regex patterns
can already be warm. It never caches parser outputs. The full census starts
in a fresh process. No second Constitution checkpoint evaluation was started.

Both three-sample bridge comparisons use **modal_frame_logic, deontic_norms,
fol_tdfol, cec_dcec, external_prover_router**; `legal_ir_evaluate_provers=False`,
`legal_ir_parallel_workers=1`, `IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE=0`,
`use_sample_memory=False`, and `CUDA_VISIBLE_DEVICES=""`. Each begins in a fresh
process with an empty legal-IR target cache; both report three targets. Sample
construction and checkpoint loading are separate timings in the receipts.
The pinned 25,895,338-byte checkpoint retains SHA-256
`1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd`.
No weights were saved or downloaded.

Training uses one epoch, one update family, one line-search attempt, a
180-second limit, and `python_sparse_batch`. It accepts one epoch in both
runs. The same in-sample deontic IR cosine delta is +0.0007497416; the same
legal-IR view cross-entropy delta is -0.0042963490. This is not a held-out
canary. A separate phase profile measured the projection update at 0.0673 s
versus 11.1298 s for the initial target evaluation; there is no evidence here
for switching to CUDA. The core method's ordinary epoch completion returns
`stopped_reason=null`; the old one-step wrapper labeled it `projection_epoch`.

Every numeric evaluation output and training decision is identical across the
unprofiled before/after bridge runs. Elapsed time and target document hashes
are excluded from that comparison. Two fresh target captures show that the
hash variation comes solely from deontic graph `created_at` and `last_updated`
timestamps. Raw metric receipts retain the original hashes. The cProfile run
is diagnostic only: its overhead affected bridge timeout outcomes, so it is
not used as a wall baseline or an equivalence result.

The daemon reuse change by itself measured 25.7534 → 25.6973 s cold, within
timing noise. Six alternating pairs with genuine targets already warm in the
process measured median 0.2808 → 0.2247 s per three-sample evaluation, with
every output field identical. Disk cache remained disabled. This smaller
comparison isolates the redundant reconstruction pass; it is not a cold IR
compilation speed claim.

All eight vocabulary dictionaries and complete compiler results, including
result CIDs, match exactly before/after. The five-case typed pilot retains
forward **0.915** and cycle **1.000**, with identical non-timing results and
L1/L2 CIDs. The three required gates preserve obligation/prohibition,
`within_duration` non-renderability, minimum-duration quantity 20, temporal
text without duplication, and empty-vocabulary abstention.

Validation includes the new semantic gates, regex-cache eviction checks,
daemon reuse regressions, and 32 existing autoformal/Constitution/lift tests.
The broader deontic selection had **456 passed and 21 failed**. All 21 failures
reproduce with identical failure messages using the pre-change formula
builder. A broader canonical selection had **56 passed and one existing
failure**: its historical decompiler snapshot CID differs from the user's
pre-existing decompiler edits, and fails with the original builder too.
Those unrelated semantic expectations and historical snapshots were left
unchanged. Detailed test counts and commands accompany the receipts.

The original Constitution process completed with 231 bridge targets. Its
entire 231-row census matches the faster compiler-only census: 62
non-operative, 166 gaps, three inactive, zero compiled, zero `roundtrip_ok`.
There is a pre-existing measurement limitation: the runner supplies the same
`constitution` document ID for each span, so the session retains the first
clause vocabulary. This work preserves that behavior for comparability;
these census counts should not be read as fresh per-span-vocabulary coverage.
The six June daemon receipts remain bridge-off, not IR speed baselines.

Evidence: [receipt directory](evidence/legal_autoformal_speed/),
[parser comparison](evidence/legal_autoformal_speed/parser-comparison.json),
[autoencoder comparison](evidence/legal_autoformal_speed/autoencoder-comparison.json),
and [pilot comparison](evidence/legal_autoformal_speed/semantic-pilot-comparison.json).

Reproduce from `external/ipfs_datasets`, using a new output path each time:

```sh
python3 scripts/ops/legal_ir/benchmark_autoformal_speed.py --output /tmp/fresh-parser.json
python3 scripts/ops/legal_ir/benchmark_autoencoder_speed.py --mode evaluate --output /tmp/fresh-evaluate.json
python3 scripts/ops/legal_ir/benchmark_autoencoder_speed.py --mode train --output /tmp/fresh-train.json
python3 scripts/ops/legal_ir/benchmark_daemon_bridge_reuse.py --mode reuse --warm-pairs 6 --output /tmp/fresh-daemon.json
```

All measurement entry points explicitly prepend the workspace tree and check
the logic pin. Temperature, context limits, Lean admission, and the external
HACC and hallucinate_app checkouts are untouched by these changes.
