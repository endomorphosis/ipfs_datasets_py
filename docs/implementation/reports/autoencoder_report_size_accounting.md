# Exact report-size accounting without repeated string serialization

Implementation, 2026-09-25. A bounded codec optimization follows the
[historical hydration profile](autoencoder_report_hydration_profile.md).
It preserves report bytes, native object sharing, derived targets and all
existing validation limits. The Constitution remains unformalized; only
`lake build <Lib>` is a Lean admit.

## Change and safety boundary

The [report codec](../../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_report_bundle.py)
previously serialized fixed node framing and repeated scalar strings every
time it computed expanded-tree byte lengths. Framing lengths now come from
the same JSON encoder once per fixed kind. Each encoding or decoding call
also owns a private exact-string-length memo. It retains at most 4,096 entries
and 1 MiB of summed encoded string bytes; strings longer than 4,096 characters
bypass it. These are cache bounds, not an RSS guarantee. Misses, overflow and
all non-string scalars retain the original encoder path. No source strings
are cached globally and no garbage-collection policy changes.

Every occurrence still contributes its complete expanded size, including
repeated graph or string references. Depth, native class/field checks,
reference validation, 64 MiB shard limits, 256 MiB expanded-graph/selection
limits and target validation remain unchanged. Float precision, signed zero,
container order, aliases, v1/v2 compatibility and v3 wire format are unchanged.
Producer identity still includes the changed file; old bundles do not become
eligible for current training merely because their bytes decode exactly.

The original source is archived at SHA-256
`0e86cccef95373ed19329fd27b77a7fda106bcb6e5561f17c63e66f429c17059`;
the optimized source is
`16ae5547afff84d6fc98447b73d33e66c30affff603bf733651fd7c995979b18`.

## Same-artifact comparison

The [comparison receipt](evidence/autoencoder_control_plane_plan/report-size-accounting-comparison-20260925.json)
records four fresh offline processes in original/optimized/optimized/original
order, all decoding the same historical report for
`us-code-22-4021a-fce42ca5c6a35f9d`. Each child retains a 180-second limit and
there were no retries. The original codec loads under a diagnostic module
alias; the canonical production module is never replaced. Native classes and
other critical decoder dependencies match the artifact's historical producer.

Each process first verifies that the ordinary current daemon session rejects
the artifact with `report configuration/provenance mismatch`. Only subsequent
low-level forensic decoding receives the recorded historical configuration.
No target generation, model/checkpoint load, bridge evaluation or training runs.
The historical artifact has all five bridges: `modal_frame_logic`,
`deontic_norms`, `fol_tdfol`, `cec_dcec`, `external_prover_router`; its prover
flag is false, bridge workers one and metric disk cache zero. These describe
the recorded producer, not a new bridge-on evaluation.

| Operation, one report/span | Original pair A | Optimized pair A | Original pair B | Optimized pair B | Original median | Optimized median |
|---|---:|---:|---:|---:|---:|---:|
| Verified selection, seconds | 5.8894 | 4.7040 | 5.7673 | 4.6539 | 5.8283 | 4.6790 |
| Reencoding, seconds | 4.6557 | 3.5270 | 4.5908 | 3.4686 | 4.6232 | 3.4978 |

Median verified selection decreases by 19.72%; reencoding decreases by 24.34%
on this one selected report. Both counterbalanced pairs improve. These are
unprofiled operation times, excluding imports, guards, memory observations and
independent integrity audits. Bundle opening is recorded separately, at about
0.04–0.05 seconds. Guard reads precede timing, so this is not cold filesystem
I/O; OS caches and host contention remain uncontrolled. The original arm's
additional module import occurs before timers and its allocation/GC state is
recorded. All four runs retain the normal GC policy and matching post-operation
collection counts.

The encoded report is exactly 63,159,922 bytes and its old-codec target is
64,868,307 bytes in every arm. Exact wire hashes, target hashes, all native
fields/types/order/compound aliases and the shared report/target document pass.
Exactly one shard is decoded per arm. Package sources, archived code, common
descriptor, source artifact and protected restart12 checkpoint pass the guards.
The complete four-process comparison including audits takes 62.291 seconds.

Peak RSS through encoding is 934,380–935,312 KiB for the original code and
929,332–929,400 KiB for the optimized code. This small observed difference is
not a general memory-scaling result. Full report graphs remain much larger in
memory than compressed artifacts; Arrow numeric weights do not remove that
graph cost.

## Regression and end-to-end qualification

The [combined regression receipt](../../../workspace/test-logs/federal-corpus-audits/report-size-accounting-20260925/combined-receipt.json)
records 396 passing checks in 21.98 pytest seconds, with all 7,720 package files
unchanged during the run and the protected checkpoint hash intact. Sixty new
checks compare a separately frozen original arithmetic function, including
exact bounds/errors, reference amplification, Unicode/control/surrogate strings,
scalar distinctions, cache overflow and per-operation lifetime after normal GC.
They also compare native v1–v3 wire and target bytes. Existing codec, session,
preparation, daemon handoff, observation, required semantic gates and pilot
checks remain in the combined run.

The broader historical daemon suite's known six-versus-seven bridge-name
assertion and the separately documented actor-import fallback defect are not
fixed by this codec change. This is not a claim that every repository test passes.

The [fresh native r4 attempt](evidence/autoencoder_control_plane_plan/daemon-shared-report-native-20260925-r4.json)
stopped during preparation when another process changed
`logic/autoformal/repair_context.py`. All six native reports returned all five
bridges without reported adapter failures/timeouts, but the producer guard
rejected publication. No bundle was published, neither daemon arm ran, and
there is no bridge-on evaluation wall time for this attempt. Parent elapsed
time was 100.772 seconds, including the 98.764-second failed preparation child;
these invalidated observations are not a speed baseline. The failure is retained
without retry and the guard remains intact.

The [source-drift audit](../../../workspace/test-logs/federal-corpus-audits/daemon-report-handoff-20260925/native-r4/source-drift-audit.json)
identifies only `repair_context.py` relative to that attempt's package inventory;
the six archived source snapshots and protected checkpoint stayed intact.
The [semantic recheck](../../../workspace/test-logs/federal-corpus-audits/report-size-accounting-20260925/semantic-after-external-drift-receipt.json)
then passed all 31 required gate/pilot checks against the changed tree with no
further source drift during the check. The earlier codec comparison was fully
source-stable and remains a valid same-artifact result.

A complete cold/shared native comparison still requires stable producer sources
through preparation, both daemon arms and graph audits. Until that qualifies,
these codec savings must not be presented as end-to-end training speed, a
held-out improvement, a production corpus integration or a formalization admit.
