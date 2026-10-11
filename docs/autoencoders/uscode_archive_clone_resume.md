# Authenticated archive-generation continuation

`scripts/ops/legal_ir/resume_uscode_archive.py` clones an authenticated stopped
`uscode-archived-target-reconciliation/v1` generation into a fresh owned attempt
before invoking the existing controller unchanged. The frozen parent remains
read-only. This additive clone operator does not change the seven manifest-pinned
execution owners, generation identity, source assets or model weights.

The CLI accepts all existing reconciliation arguments unchanged, plus
`--parent-directory`, literal file SHA-256 pins
`--expected-parent-database-sha256`, `--expected-parent-manifest-sha256` and
`--expected-parent-report-sha256`, and `--max-clone-bytes` (default 134,217,728).
The expected manifest pin is the file's byte hash, distinct from its canonical
JSON generation digest. Obtain all three pins from the prior immutable reviewed
result, not a freshly overwritten or unreviewed report.

The parent must have regular canonical files, an existing writer lock and no
unreconciled WAL. A shared nonblocking lock refuses an active writer. Custody
checks authenticate parent bytes, current execution-owner hashes, original
source/progress bytes and revisions, seed snapshot and paging profile. Read-only
queries verify durable cursor/accounting/report agreement, physical target
counts/dispositions, archive denominators and source extent. There is no spill
into the frozen parent directory.

The destination must be absent and its canonical owned attempt directory must
already exist. Destinations inside the parent are refused. Complete copies of
the database, manifest and report plus a `clone-custody.json` receipt are staged,
rehash-verified and synced. All staged file bytes, including custody evidence,
count toward the clone cap and controller output cap. Linux
`renameat2(RENAME_NOREPLACE)` atomically publishes the directory and refuses even
a competing empty destination. No unsafe rename fallback is used. Unsupported
platforms or missing kernel/libc support refuse publication.
Each copy writes at most its authenticated pinned length and checks for one
excess byte. Unexpected source growth cannot overrun the staged byte budget even
when an external writer disregards the cooperative lock.

The receipt records parent file pins, exact cursor/counts/digests, cloned
generation digest, clone module/CLI hashes, copy budget and publication method.
The database and manifest copies are byte-identical. The initial copied report
represents inherited parent state and resource measurements; it is not a new run
measurement. The controller replaces it only after continuation produces its own
durable report.

Interrupted or refused staging is removed before publication and cannot appear
as a runnable destination. Once publication succeeds, a later controller refusal
preserves the legitimate clone and its last committed cursor. Do not repeat clone
creation into that directory; investigate and resume the existing generation
under its original pins and a separately admitted owner. The old parent is never
modified, removed or evicted by this operator.

Runtime `--max-pages`, `--memory-mb` and `--storage-max-bytes` may vary after fresh
admission; original source/code/seed/page profile values must stay fixed. A
generation change requires a new lineage rather than an altered old manifest.
The helper acquires no resource claim itself. Its outer guardian must charge
staging plus retained outputs, enforce the owned process-group budget and record
durable cleanup. A clone cap is a storage bound, not a memory limit or proof that
the next full window fits.

For continuation of the reviewed October 11 result, use the prior
`archived-reconciliation-01/results` as parent, copy into a fresh admitted
`archived-reconciliation-02/results`, preserve its 64-span / 4,194,304-byte page
profile, and begin with the measured bounded page count selected by the resource
owner. The copied first-uncommitted cursor remains `(199,64)` until the unchanged
controller commits new source pages. Original 2,806 target rows and all-source
accounting/digests remain present without rewriting them.

This is still an archived-target inventory. Outside-target sources have aggregate
counts/digests and bounded examples rather than a complete identity inventory.
No model, tokenizer, new embedding, training, semantic reconstruction or formal
proof runs as part of cloning; subsequent native pilots retain their separate
family/dimension/schema/task/producer/checkpoint eligibility gates.
