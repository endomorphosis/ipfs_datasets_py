# LegalIR actor refinement with learned conditions retained, 2026-10-14

One bounded actor-refinement experiment completed and passed its technical
checks. The fixed scientific criterion failed: training raw and joint exact IR
both remain 154/168, below the required 155/168. No default decoder is promoted.

## Results

| Exposed exact-IR scope | Rows | N11 parent raw → candidate raw | N11 parent joint → candidate joint |
| --- | ---: | ---: | ---: |
| Training | 168 | 154 → 154 | 154 → 154 |
| Older authored evaluation | 72 | 48 → 50 | 51 → 53 |
| Authored development | 72 | 45 → 45 | 46 → 46 |
| Newer authored evaluation | 72 | 27 → 27 | 33 → 34 |
| Older tuning | 96 | 94 → 94 | 94 → 94 |
| Fresh tuning | 36 | 8 → 8 | 19 → 19 |
| Fresh challenge | 36 | 25 → 25 | 25 → 25 |
| Fresh development | 36 | 0 → 0 | 0 → 0 |
| Fresh test | 36 | 0 → 0 | 0 → 0 |

Independent recount found no complete-IR loss IDs in either decoding route
across all nine scored scopes. All 32 legacy permission cases remain intact.
Complete IR includes modality and all six roles. Two older authored evaluation
cases improve in both routes; one newer authored evaluation case improves in
joint decoding. These descriptive gains do not satisfy the training criterion.

The authored panels have been repeatedly exposed during engineering. They do
not establish blind generalization or statutory semantic accuracy. The eight
statutory sources remain unscored. Genuine active 8D/384D/768D latent decoding,
broader logic-family qualification, independent statutory gold, isolated
numerical reload of the published package, and `lake build legal` remain
unqualified. Latent conditioning stays disabled with 384-dimensional
placeholders, and no external embedding encoder ran.

## Fixed experiment and retained behavior

The donor is the exact trained N11 checkpoint, SHA-256
`34080a8ad491e5a351aeea0adfc6f3e29e76d0ae93c1f8a8cee3ebf536a7b9fd`.
All 42 tensors are copied. Thirty-six nonactor tensors, including every row of
the learned conditions head, remain frozen. The six actor projection, query,
and context-gate tensors contain 258 active scalars and 650 inactive scalars;
the inactive rows retain zero gradients and optimizer moments. The trained
query and gate are continued, without a fresh-zero or first-step zero-gradient
assumption.

The run uses actor cross entropy, fresh Adam at learning rate 0.001, batch size
12, seed 1729, and exactly 32 updates on the unchanged 168 training sources.
Those updates cover 384 training occurrences. Actor ranking is disabled.
Query and gate values change on all 32 updates. Trace validation authenticates
source/target joins and frozen/inactive gradient and moment flags; it does not
claim an independent live numerical gradient proof or scalar CE replay.

Before the first update, all complete saved head scores and predictions match
N11 across 632 sources. Final checks retain the modality, all four presence,
and nonactor boundary score bits across the same 632 sources. Protected score
vectors do not make every decoded nonactor role invariant under a joint
selector whose actor scores changed.

There are 1,280 actual inference forwards and 32 training forwards: 1,312 new
model forwards and 1,664 total source occurrences. Six saved parent capture
files, covering 240 rows, are reused byte-for-byte with no new comparator
forwards or updates. All 62 output files, totaling 67,956,145 bytes, were frozen
before scoring. The checkpoint is 12,230,969 bytes, SHA-256
`f421514dc02cb3542e7587767191aa99bd32551f145e0af4d01c47595d4d73c4`;
the final model-state digest is
`a1bb3158f19c7b619b7d15ee7ba4887046cc7d22eebecad7b04e8a8111ac3d42`.

The complete algorithm closure is 39 module owners plus one authenticated
supplemental attention recipe, giving 40 raw algorithm files. The actual inert
bootstrap observes 16 loaded owners and eight mandatory owners. Publication
must retain the package-relative source hierarchy so sibling attention code is
discoverable. Source completeness alone does not demonstrate numerical reload
in an isolated environment.

## Capacity refusal and reversible historical storage

The first read-only resource observation refused an exact check-to-snapshot
join before any census, reservation, child, or model. A qualified bounded
collector then matched the ledger and scheduler bytes on its first permitted
pair. The resulting native census refused capacity: observed bytes plus all
44,381,777,216 outstanding reservation bytes, the 200 MB new request, and a
200 MB future-output allowance total 145,587,894,136 bytes. This exceeds the
unchanged 145,000,000,000-byte cap by 587,894,136 bytes. Every one of the 539
historical record bodies remains exact.

A separately reviewed storage transaction selected only 27 owned, completed,
released, durable historical attempts. It excluded all failures and retained
claims, three ambiguous reuse attempts, and the N11 donor and N14 results.
The transaction preserved 1,162 opaque regular files totaling 934,325,529 bytes
in one lossless archive. Every member was hashed, fully read back, and restored
into a fresh probe before any original was removed. Exact archive and manifest
bytes were also published and independently downloaded at immutable Hub
revision `0228887c8e33cb23e9679889a9496f87140021e6`, under
`archives/20261014-owned-released-results-v1`.

The durable archive remains inside the same counted root and is 149,504,694
bytes. Its restoration manifest is 801,434 bytes and its progress journal is
341,530 bytes. The measured net apparent-size saving is 783,677,871 bytes.
This exceeds the explicit conservative 750,000,000-byte minimum; the earlier
800 MB target remains false. Original directories and command/runtime/terminal
metadata remain, and the temporary quarantine is empty. Original result paths
are intentionally archived; no original-inode or continuous-path-availability
claim is made. The standalone restore tool defaults to verification and only
restores a selected attempt into fresh staging. Restoring counted original
paths requires a new capacity qualification.

No foreign cleanup, reservation release, cap change, model codec change, or
claim-debit adjustment occurred. Capacity recovery cannot be attributed solely
to this archive: externally owned pytest data also fell by about 3.94 GB between
qualified observations. The independent 783,677,871-byte local saving is the
measured phase contribution.

## Bounded execution and closure

The fresh qualified post-archive baseline conserves all 539 prior record
bodies and charges the same outstanding total. Observed bytes, all claims, the
200 MB request, and the extra 200 MB future-output bound total 140,860,054,081
bytes, leaving 4,139,945,919 bytes under the cap. The four named physical counted
roots and the shared 4 CPU / 9,830 MiB / four-child scheduler configuration stay
unchanged. Admission still rechecks actual capacity and occupancy atomically.

The run requests two CPUs, 1,536 MiB RSS, one child, 200 MB owned storage, and a
300-second wall bound. Guardian and child both exit zero; artifacts are durable
and the owned reservation is released. The terminal audit conserves all 539
historical bodies and observes 540 records: 439 released and 101 retained. The
N7 failed reservation remains retained and fully charged; the previously
reconciled N8 reservation remains released. Full outstanding charges stay
44,381,777,216 bytes.

The owned final storage charge is 68,182,937 bytes. The audit records 116 RSS
samples with a sampled group peak of 792,186,880 bytes and a 119.109-second model
phase. These are sampled observations, not an absolute memory peak or a kernel
memory limit. The owned scheduler lease is absent at the copied terminal
observation. Foreign occupancy is permitted; global idle is never assumed.

## Publication and next experiment

The source publication is based on incoming main
`802c8f32c8b3d3058271e23c69e93f37b39f43fb`, after preserving the original
reviewed two-file model/test draft and checking all 40 algorithm raw identities.
Incoming source tree entries, ten gitlinks, and four symlinks are preserved.
The owned root checkout advances to incoming main
`51774875d8e42deb4d378aa4d9dbf3ec8329969f`, preserving other-agent work and
all incoming root gitlinks, including SwissKnife. Final integration must use
the actual latest merge parents. Canonical HEAD and index files stay unchanged.

Only public sources, receipts, derived analysis/recount, and this report enter
the Git evidence capsule. Raw weights, result payload trees, the 149 MB archive,
private endpoint copies, private stderr, downloads, and Git metadata are
excluded. The same report bytes are retained in source and root report 126.
The model release is verified at
[immutable Hub revision 1622817](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/1622817fd804ff5333fce7dc8d04433e4acef2e4/releases/20261014-actor-refinement-v1),
under `releases/20261014-actor-refinement-v1`. All 198 files, totaling
77,331,365 bytes, passed fresh forced immutable Hub CLI raw-byte readback and
independent review. The final 5,646-path repository preserves every one of the
5,448 original identities and adds the exact 198 payload files. No default
decoder changes. Git integration remains separately subject to exact-head and
actual-merge review.

The original publisher halted after creating chunk 2: the committed
`.gitattributes` acquired one 129-byte LFS rule for the new checkpoint. All
26 created payload files matched their original bytes, and the other 5,447
original identities stayed exact. The failed invariant and original receipts
remain preserved. A separately qualified correction at revision
`8635d1d2ae8b617d5b15bd3da0c683b8f57125c1` restored the exact baseline
attributes and verified all 5,448 originals plus those 26 payload identities.
Only the five uncreated original chunks, 3 through 7, then resumed; chunks 1
and 2 were not reuploaded. Every remaining commit retained the complete prior
identity map. This protocol includes one prior-file correction and is not
represented as an uninterrupted additions-only publication.

Restoring baseline attributes removes the release-specific LFS rule. The
checkpoint remains identified as an LFS object in Hub metadata. Fresh forced
Hub CLI downloads verify all 198 original payload hashes, including the exact
12,230,969-byte opaque checkpoint. The immutable release can be retrieved with:

```sh
hf download Publicus/legal-ir-autoencoder --revision 1622817fd804ff5333fce7dc8d04433e4acef2e4 --include 'releases/20261014-actor-refinement-v1/*' --local-dir actor-refinement-readback --force-download
```

Automatic Git LFS clone materialization and isolated numerical reload remain
unqualified. A future binary tensor export under an existing LFS-matched
extension could avoid a per-checkpoint attributes addition, but would require
separate exact tensor/optimizer-state and 632-head roundtrip qualification.
This phase performs no such conversion; the JSON checkpoint stays unchanged.

The count of training actor mismatches remains 12. A later fixed experiment
could combine the learned contextual actor features with the existing filtered
actor ranking loss, which has coefficient 0.25 and margin 1. Such a continuation
must use training-only authenticated negative domains, keep the learned
conditions head and other protected routes frozen, and retain the same complete
IR checks. It is a proposal only. No implementation, further training, heldout negative
mining, checkpoint selection or promotion has been performed as part of this
proposal.
