# US Code rollout: authenticated continuation and next processing gates

The source-only rollout continues the same archived-target generation from an
authenticated byte-identical clone of the reviewed October 11 result. Phase 02
stopped successfully after its bounded 4,096-page window: **209,740 cumulative
source observations**, **24,110 exact archived target joins**, and **185,630
outside-target observations**. Independent actual-result review passed **22
checks with zero findings**. The complete source scan, native autoencoder pilots
and learned reconstruction remain outstanding.

This follows the [comprehensive all-span plan](https://github.com/endomorphosis/lift_coding/blob/4bad33cb1d1f63d3f3011c96f1e19f186163dd24/implementation_plan/docs/68-uscode-all-span-processing-plan-2026-10-07.md),
the [original intake findings](https://github.com/endomorphosis/lift_coding/blob/c7a9e8d6725a110f6bd3b299acbb3ab434870fce/implementation_plan/docs/69-uscode-span-intake-progress-2026-10-07.md)
and the reviewed [first archived continuation](../uscode-span-continuation-20261011/PROGRESS.md).

## Scope and measured continuation

The fixed source generation remains
`justicedao/uscode-autoformal-span-cache@765176c6db79ba65c1697c21dead43666350b730`
with 443,904 distinct archived span IDs plus one metadata row, joined against the
existing original US Code Parquet. Source, progress, old seed, seven execution
owners and 64-span / 4,194,304-byte page profile stay pinned. Cloning adds custody
evidence rather than changing extraction or rewriting previous target rows.

| Measurement | Reviewed parent | Phase 02 cumulative result | Phase 02 addition |
| --- | ---: | --- | --- |
| Observed source occurrences | 24,191 | 209,740 | 185,549 |
| Persisted exact archived target joins | 2,806 | 24,110 | 21,304 |
| Outside-target aggregate occurrences | 21,385 | 185,630 | 164,245 |
| Archived IDs awaiting source scanning | 441,098 | 419,794 | 21,304 reconciled |
| First uncommitted section/span cursor | 199:64 | 2308:0 | — |
| All-occurrence and outside-target digests | Frozen parent receipt | Frozen phase 02 report | Ordered extensions |
| Kernel process-lifetime maximum RSS | 864,636,928 bytes | 754,864,128 bytes | Separate process measurement |
| Guardian finalization inventory | 4,009,757 bytes | 11,706,588 bytes | Separate attempt footprints |

Cumulative snapshots include the inherited prefix and cannot be summed. The new
window is final cumulative accounting minus authenticated parent accounting.
Independent review compared all 2,806 inherited target rows and 21,304 new target
rows, replayed the 185,549 new observations with a different 37-span page limit,
and reproduced both ordered digest extensions. Distinct archived IDs, physical
source occurrences, matched targets and metadata remain separate denominators.
The first uncommitted cursor is `(2308,0)`, no WAL remains, and both
`complete_source_scan` and `complete_all_source_occurrence_inventory` remain false.
The all-occurrence digest is
`552b68c530029b755630b81d0ab607c4d2e56bf9b6ebff1a8c30fa81b4722f89`;
the outside-target digest is
`bda5bc085682c994ba60aa3a439f22cd69a00670965b5719ca75e2c0b8c62b38`.

This path persists archived-target occurrences. Outside-target sources receive
aggregate counts, length cohorts, ordered digests and bounded examples; their
complete identities are not stored. A completed source scan would therefore
still not establish a complete all-source identity inventory. Outside-target
sources are not automatically missing work, new text or duplicate records.
Historical extraction hashes normalized sentence bytes; original raw UTF-8 stays
in the unchanged source artifact. Citation fallback retains historical ordinals
with explicit nonstatutory provenance.

## Custody and operating envelope

Clone support is additive: stopped WAL-free parent custody, caller-supplied exact
database/manifest/report hashes, current source/code/seed/profile checks,
read-only durable state verification and byte-identical copies. Each copy is
bounded to its pinned length. A complete fsynced clone and custody receipt become
runnable only through Linux no-replace directory publication. Refused staging
is removed; a later controller refusal preserves a legitimate clone and its
committed cursor. The frozen parent and original assets remain unchanged.

The clone implementation passed **108 integrated controls** and **16 independent
source-review checks** with zero findings. The run plan selected at most **4,096
new pages**, or 262,144 candidates at the 64-span ceiling; shorter section pages
lower that count. It requests one CPU/child slot, **1,536 MiB outer admission**,
a **768 MB DuckDB setting**, **240,000,000-byte controller output cap**,
**256,000,000-byte reservation**, **134,217,728-byte clone cap** and 1,200-second
deadline. Admission remains cooperative and polled. DuckDB's setting does not
bound the whole Python/Arrow process; kernel maximum RSS is a process-lifetime
self high-water mark, not an isolated-stage or process-group peak. The new OS
child reported **737,172 KiB = 754,864,128 bytes** maximum RSS. The guardian's
129.275-second elapsed observation includes admission/usage overhead and is not
pure scanner runtime. No process-rate extrapolation establishes full-corpus fit.

The final database is **11,546,624 bytes**, up **7,602,176 bytes** from the frozen
parent. `output_bytes_before_report=11,564,594` covers controller output before
its final report and excludes guardian files. Guardian finalization measured
**11,706,588 attempt bytes**; the subsequent 4,391-byte `resources-final.json`
and 777 later bytes bring the stopped attempt to **11,711,756 bytes**.
The owned process group stopped, its reservation and lease were released, and no
cleanup error or reservation overflow was reported. These measurements support
sizing another bounded window, not a whole-source or all-native-vector promise.

Readiness passed 13 checks. Its projected 1,024-section sample found no section
above the existing 8 MiB bound; the largest measured section was 280,479 UTF-8
bytes. This sample does not establish corpus maxima, token lengths or worst-case
output fit. The last fresh named-root census showed approximately 860 MB headroom
under the existing **145,000,000,000-byte cap**, preserving 98 foreign claims.
The earlier approximate 42.7 MB growth estimate used old target density and
whole-database cost; the measured 7.6 MB database increment replaces it for this
window. Final guardian accounting recorded **143,302,101,991 charged bytes**,
or **1,697,898,009 bytes headroom** under the same cap. Fresh accounting is still
required before the next reservation; source density and allocation costs vary.

Evidence: [run plan](run-plan.json), [readiness](review/readiness.json),
[clone review](review/clone-implementation-review.json),
[controls](review/archive-clone-integrated-controls.xml),
[actual-result acceptance](review/rollout-results-review.json) and
[concurrent survey](review/concurrent-survey-update.json).
The stopped attempt is `uscode-span-rollout-20261011/archived-reconciliation-02`.
Counts and resource claims above come from its frozen report/manifest and guardian
receipts; this documentation did not inspect its database while active.
The independent actual-result receipt authenticates the stopped result;
publication remains a separate step.

## Reused research and model boundaries

Current integration preserves incoming Unicode source-binding, raw-source
retention and numerical structural frontend work. The published
[casewise retention trial](https://github.com/endomorphosis/ipfs_datasets_py/blob/b4002de1e73d295e222cd7258bd07e4784a6b928/docs/implementation/legal_scope_retention_gate_pilot_20261011.md)
performed 480 optimizer updates but rejected every fitted endpoint for newly
introduced negative case IDs. The selector retained the frozen parent with zero
selected updates. This source-only contextual64/ordered-byte support-residual
task is separate from native GTE latent reconstruction; its scores do not select
a LegalIR semantic decoder teacher. Reuse the casewise retention gate and saved
findings rather than repeating the rejected objectives.

A parallel native-cache session already owns the additive
`arbitrary_native_source_cache.py` and `arbitrary_native_legal_ir_runtime.py`
interfaces. Its surveyed eight-source pilot is data-only, without targets or
native cache/token/representation qualification. Coordinate with that owner and
review its implementation before integration; do not duplicate it or infer a
completed numerical pilot from untracked source files. Preserve the established
48-paragraph / 216-vector normative replay as a separate fixed control.

LegalIR, CodebaseIR, SecurityIR and IntentIR follow separate inventory,
database/catalog and model repository namespaces, with planned parallel
8D, 384D and 768D paths. This matrix is the namespace and compatibility contract;
qualified checkpoints, storage cells and arbitrary runtimes remain per-cell
deliverables. This rollout creates no new model availability or qualification.
Family, dimension role, schema/version, decoder task, codec/profile,
encoder/context and checkpoint hashes determine compatibility.
An 8D mock diagnostic is not an authenticated learned teacher; a 384D receipt
cannot be relabelled or padded into a native 768D receipt. The actual retained
768D producer remains limited to 512 input tokens despite the base model's
8,192-token capacity, with separate 512-token/eight-clause output geometry and
32-value vocabulary constraints.

Existing dual-donor 768D preparation remains reusable: **26 copied decoder
tensors / 27,142 parameters**, initialized but unaligned, with zero preparation
optimizer steps. That genuine initialization is separate from qualified teacher
output distillation. Use authenticated saved donor tensors and original
transformations; learned 8D/384D teacher quality, exposure separation, alignment
and fresh retention/fidelity acceptance are still required before promotion.

## Next work and acceptance gates

| Stage | Deliverable and acceptance |
| --- | --- |
| Publish accepted phase 02 | The owned group is stopped, artifacts frozen and claim released. Independent clone/parent/source/seed custody, cumulative cursor/target/digest replay and cleanup review passed 22 checks with zero findings. Publish the accepted receipts and preserve incoming source and supervisor history. Keep observed elapsed time separate from future per-stage scanner throughput. |
| Complete archived reconciliation | Continue fresh authenticated clones in measured bounded windows. Every archived row needs an exact source mapping or explicit final unresolved disposition. Overflows refuse without advancing the cursor; retries are bounded and changed source/code/profile creates a new generation. |
| Establish full-source identity coverage | Implement a separate versioned immutable occurrence-shard layout, preserving physical occurrences and historical aliases. Aggregate-only outside-target accounting is insufficient. Measure compressed identity bytes per occurrence, source/target density, largest sections, stage latency and publication costs before reserving the complete scan. |
| Reuse native-cache owner | Pass source-only cache/producers preflight, exact source/context/vector and checkpoint bindings, genuine tokenizer counts, output codec/qualifier/clause representability and input/output bounds before invoking any model. Missing cache, incompatible producer, unsupported schema/task, fallback, overflow and context-needed sources keep explicit dispositions. |
| Eligible numerical pilot | Run declared 8/128/1,024-source cohorts only after compatibility controls and resource admission, retaining fixed replay behavior and fresh source-only confirmation. Teacher-qualified 8D/384D transfers may warm the existing 768D state; preserve per-family/schema/task checkpoint attribution. |
| Reconstruction and proofs | Evaluate learned semantic IR, learned text, lossless raw-source/offset/residual routes and reviewed legal meaning independently. Proof entries require source/context/model/compiler/checker dependency bindings and actual checker receipts; a parser, transport match or compilation is not proof or learned reconstruction. |

Each new phase must account for retained predecessors, staging, database/WAL,
spill, logs and receipts. Maintain one active continuation and one staged clone
at a time. As a proposed default rollout gate, keep newly retained campaign bytes
plus planned staging within the present 256 MB envelope; a larger aggregate
campaign budget requires measured fit under the unchanged 145 GB global cap.
This is a planning bound, not a new reservation or permission to delete files.
All frozen parents and original source/model assets remain retained. Do not
release foreign claims or infer evictable bytes from a model score.

Before another clone, perform fresh named-root accounting and check the measured
sum of every retained campaign database/shard against the next admitted window.
If a flat database or cumulative clone chain no longer fits, pause expansion and
review bounded immutable shards with hashed manifests and verified publication;
do not silently raise caps, prune historical assets or create a full new vector
mirror. Storage, source reconciliation and native training remain separately
attributable stages.
