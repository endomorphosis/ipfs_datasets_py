# Locating source-head and recurrent decoder errors

The October 6 diagnostic locates the current 384D/768D Legal decoder failure
before another training change. Most wrong modalities already originate in the
source head. Lower loss on the existing TRAIN wording bank did not repair them.
The positive auxiliary arm also introduced one recurrent override of a correct
source-head prediction. Neither arm is promoted.

This is a saved-checkpoint experiment on previously exposed authored examples.
It does not measure current compiler performance, fresh holdout generalization,
the protected 8D linguistic teacher, or the 4096D decoder. Widths have different
native encoders, so this is not a dimension-only ablation.

## Results and complete coverage

Four unique selected states each generated 48 paragraphs containing 180 rules.
The saved last-attempt state equals the selected tensor within each arm; it was
recorded as an alias instead of being executed as another independent endpoint.
Each panel visited and scored all 720 actor/action/modality/object sites. There
were no unavailable or unvisited reference sites.

| Width | Auxiliary weight | Source modality correct | Combined modality correct | Source correct, combined wrong | Exact paragraphs, unchanged from archived output |
| --- | --- | --- | --- | --- | --- |
| 384D | 0 | 139/180 | 139/180 | 0 | 20/48 |
| 384D | 0.05 | 137/180 | 136/180 | 1 | 19/48 |
| 768D | 0 | 178/180 | 178/180 | 0 | 46/48 |
| 768D | 0.05 | 178/180 | 178/180 | 0 | 46/48 |

Both 384D arms also have one source-head action error, retained in the combined
output. Actors and objects are 180/180 in every panel; 768D actions are 180/180.
Every generated token sequence, generation status and EOS flag equals the
archived October 4 output exactly. This experiment changes no prediction.

An independently recomputed audit checked all 2,880 generated scalar sites,
92,160 float32 component additions, full 32-token vocabulary scores, target
margins and argmax decisions. Its 66,467 checks passed, including successful
child exit, outer exit and resource release. Maximum independently recomputed
component metric difference was zero. These are fixture fidelity checks, not
proof admission or independent statutory interpretation.

The evidence is in
[the result receipt](../implementation/reports/evidence/decoder-paraphrase-modality-margins-20261006/results.json)
and [its manifest](../implementation/reports/evidence/decoder-paraphrase-modality-margins-20261006/manifest.json).
The workspace archive retains actual traces, posthoc scores, guardian receipts,
source inventories and both the superseded preparation seal and final seal.

## A concrete remaining error

For `The secretary is obligated to publish the notice.`, the authored reference
is the following restricted Legal-IR rule:

```json
{"modality":"O","actor":"secretary","action":"publish","object":"notice","conditions":[],"exceptions":[],"temporal":[]}
```

The zero arm generates the same rule with modality `P`; the positive arm uses
`F`. Both source heads already choose those wrong modalities. Syntax remains
valid, so syntax alone would miss this error.

There is also a real additive override in the positive 384D arm for
`The obligation is for the trustee to deliver the archive.` The source head
correctly prefers `O` over `P` by 0.120810509, but the recurrent component favors
`P` over `O` by 0.147081852. Their combined margin is -0.026271820, and the actual
decoder emits `P`. The zero arm emitted the correct `O`. The full trace retains
every competing token, including grammar tokens; this is not a masked O/P/F
classification or a forced correction.

The recurrent component already contains paragraph, source-clause and generated
history effects. Its uncombined argmax is often a grammar token. It is not a
standalone formula decoder, and the additive trace does not causally isolate
which recurrent feature caused an override.

## APIs and reference barrier

The owner is
`ipfs_datasets_py/logic/formalization/autoencoder/generated_scalar_observation.py`:

- `collect_source_scalar_trace` accepts closed source-only rows, exact source
  contexts, the saved codec and original TRAIN transform. A temporary readout
  hook captures recurrent logits during the unchanged greedy calls; source
  logits come from the existing state cache. It adds no forward pass or model
  copy, preserves weights/gradients/modes/RNG and removes hooks on failure.
- `score_scalar_trace` validates the completed authenticated trace before
  applying reference labels. It reports full-vocabulary CE, margins and argmax
  separately for source, recurrent and combined components. It returns no
  differentiable training loss. Source/rule alignment is an authored positional
  fixture contract.

The new entrypoint is
`scripts/ops/autoencoder/diagnose_paraphrase_modality_margins.py`. Its driver
fsyncs each trace and its directory entries, verifies all four durable traces
and exact archived greedy parity, then loads the exposed v3 reference JSON.
Inherited setup reads older metadata; it is not globally reference blind.
Source rows contain only `id`, `source_text` and `input`; reference target counts
and prefixes are not provided to generation. All 32 logits remain visible.

The 73 pure runner tests cover cold import, altered inputs/states/predictions,
missing panels, authority flags, durability, deadlines and the label barrier.
The numerical observer itself is unchanged from the previously tested owner.

## Reproducing the local observation

The completed local run is
`workspace/test-logs/decoder-paraphrase-modality-margins-r2-20261006`.
`diagnostic-manifest.json` binds 1,178 inputs and 11 extensions. The reviewed
wrapper invokes the frozen runner under the existing disk/resource owner,
shared-scheduler configuration and owned-lease watchdog. It does not reset or
replace foreign leases. Completed output and attempt names are immutable.

For a new run, prepare a fresh sealed directory and attempt from the same
authenticated input closure, complete independent readiness review, and invoke
its `run_guardian.py`. Do not substitute another checkpoint or run the live
package by changing `PYTHONPATH`. The historical numerical dependency tree is
explicit; the current pinned compiler tree is not exercised by this diagnostic.
The public archive excludes model assets, private checkpoint tensors and the
full predecessor source trees, so its evidence alone is not a portable model
installation. Existing local assets and authenticated saved inputs are required.

Policy: temperature 0; encoder context and decoder output limit 512; batch 8;
one CPU worker; CUDA disabled; bridge names `[]`; prover evaluation false;
metric disk cache disabled; warm authenticated source-vector caches. No encoder
forward or weight download occurred. This cannot be reported as a cold compiler
or bridge-on Legal-IR speed measurement.

Trace generation took 0.527/0.530 seconds per 48-paragraph 384D panel and
0.678/0.670 seconds per 768D panel, approximately 0.0110/0.0141 seconds per
paragraph. Posthoc scoring added 0.218/0.332 seconds per panel. Entire driver
wall time was 25.252 seconds; guardian wall time was 67.006 seconds, including
admission/accounting/finalization. These scopes must remain separate.
The released run retained 9,690,794 bytes within its 100 MB reservation. The
campaign cap remained 145 GB, with 141,066,115,047 bytes charged at finalization.

## Next training slice and reuse

The existing R4 head is already correct on all 180 TRAIN modality examples.
Making those predictions more confident is insufficient. The next specified
comparison expands TRAIN wording while preserving the original 90 rule
identities, complete roles, original batches and full-vocabulary loss. Freeze
two new balanced normative strata, provenance/exclusions, native preparation,
zero/positive controls and a prospective development seal before fitting.
Keep the current v3 cohort exposed and out of TRAIN. The workspace
`artifacts/autoencoder-next-gap-20261006/data/next-wording-training-spec.md`
contains the concrete rendering, packing, cache, loss and resource contract.
This specification has not yet been executed.

The other agents' 64-source corpus has reusable native 384D/768D caches, but its
formal reviews remain pending and every semantic mask is zero. Its richer
symbols and qualifiers exceed this 32-token decoder. Use those caches for
source-feature diagnostics under their own producer profiles; do not invent
formal labels or simplify their targets to fit the current head.

No compiler/decompiler, logic-family projection, solver or Lake build ran here.
Only an applicable successful `lake build <Lib>` grants Lean admission. Source
fidelity and applicable family checks remain separate requirements. No
Constitution span is formalized or marked `roundtrip_ok` by this work.
