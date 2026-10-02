# Complete repository pages and bounded resident inference

This opt-in local profile projects the complete native CodebaseIR source/AST
inventory into deterministic pages, preserves dirty overlays and native global
static dependency resolution, and runs source-conditioned 384D inference over
bounded page groups. It reuses the existing source catalog, immutable source CAS,
autoencoder registry, feature artifacts, GTE model cache, and resource scheduler.
It introduces no source/model/proof head and performs no model promotion.

The existing complete capture is still required first. Initial dirty capture
and AST extraction remain a bounded whole-generation operation (at most 256
entries); these new pages do not make that initial operation resumable. The
separate [committed-source stager](CODEBASE_PAGED_STAGING.md) performs actual
resumable source/AST extraction for clean committed inventories. These two
profiles must not be presented as a unified arbitrarily large dirty scanner.

## Owner interfaces

`codebase_repository_shards.prepare_repository_shards` requires an exact current
`CodebaseHead` and its verified scan-policy receipt. It publishes source/AST
pages and a global edge projection in the existing source CAS after native live
source and ignore/configuration fences. Each page contains every admitted
ordinal, path, raw source key, source/entry/AST CID, parse status and disposition.
Opaque, oversized, unsupported-language and failed-parse entries remain visible.
No learned score selects or removes entries. Workspace, artifact, vendor and
cache exclusions are inherited from the exact frozen policy receipt.

`load_repository_shards` reconstructs the whole bounded population from the
native policy/source/AST owners on every read. `read_repository_shard` accepts a
root-bound position cursor. That cursor is a position, not evidence that parsing,
inference, proof or work completion happened. Historical roots remain readable;
a cursor from another root cannot be used to continue a changed snapshot.

Global dependency pages retain the existing `RepositoryScanner` edge records
and complete semantic-state CID. They label resolved cross-page, within-page,
repository-global, and unresolved/external relations. They do not infer new
whole-program semantics. Actual cold and incremental native captures were
compared: source/AST page CIDs, structural manifest and global edges agree.

`codebase_resident_inference.run_resident_inference_pages` consumes that source
root plus a verified existing `codebase_prior_384` registry version and exact
local GTE asset snapshot. It executes up to 16 pages in one isolated CPU child,
then stores executed page runs and feature microbatches through the existing
registry operations and CAS. Its immutable cursor represents a replayed
contiguous executed prefix. Exact retry reads the native operation and immutable
artifacts; a fresh file-backed process can reconstruct the cursor without model
calls. A changed source generation, model descriptor, asset identity, producer,
page population or forged prefix refuses continuation.

The model stays resident **within one bounded child invocation**, including up
to 16 pages. It is not kept alive across resumed API calls. `mode="cold_per_page"`
is the explicit comparison control. `batch_size` is separately bound in the
inference key. Every encode call must return exactly one finite 384D vector per
eligible source. Feature vectors keep the existing four-field source/assets
shape and registry artifact ownership. Source text exceeding 32,768 characters
or 512 GTE tokens receives an explicit deferred disposition; it is not truncated.

Outputs are unverified source-conditioned candidates. All proof, execution,
completion, publication and source-runtime-equivalence authority flags remain
false, even when the learned decoder reconstructs syntactically valid IR.

## Acquisition and watcher controls

`codebase_git_batch.read_repository_source_page` is an opt-in source-page reader.
It acquires unchanged captured UTF-8 Git objects in one bounded `cat-file
--batch` process, checks each ordered object/type/size header, raw source CID,
Git object digest and exact EOF, then reobserves current source/policy. Dirty
captured entries come from their exact existing source CAS. Opaque entries
remain explicit and have no acquired body. The complete page is returned in
all three modes: `batch`, `per_blob` (performance control), and `cas`.

The existing initial native scanner is unchanged and does not automatically use
this batch reader. Its process count measures object reads only; complete
before/after source fences still perform their native Git work. Git replacement
objects, optional locks, fsmonitor, hooks and lazy fetching are disabled for
object acquisition. The executable and decoder/process producers are pinned.

`codebase_repository_watch.watch_repository_shards` reuses `RepositoryWatch`
with bounded full-inventory scans and a bounded coalescing notification list.
A notification requests a fresh complete capture and normal admission; it
cannot narrow the population, publish a source head or authorize parser/model
or proof work. Cancellation drains the watcher before releasing the lease.
The stop bound is cooperative: an active native Git call has its existing
timeout, so the overall duration is not a hard process-wide wall-clock limit.

## Declared limits and admission

| Component | Supported bound |
| --- | --- |
| Complete dirty/native inventory | 256 entries, 64 KiB per source |
| Source/AST page | 16 entries, 1 MiB metadata |
| Global static edges | 16,384, explicit unresolved frontiers |
| Resident child | 16 pages, at most 16 model rows per page |
| Model batch size | 1–16 |
| Model input | 32,768 characters and 512 GTE tokens, no truncation |
| Native model protocol | 32 MiB input/output |
| Git batch | 16 objects, 1 MiB body population, 2 MiB protocol |
| Git decoder address space | Existing fixed 128 MiB profile |
| Watcher | At most 32 scans, 16 retained notifications, 30 seconds requested lifetime |

Native model children use one CPU thread, offline assets, `CUDA_VISIBLE_DEVICES`
disabled, the actual shared resource owner and sampled process-tree RSS limits.
The sampler can overshoot between measurements. A parent with insufficient
memory refuses the child before source/model access. Source parsing and watcher
work use cooperative owner deadlines; this is not a cgroup memory/isolation
claim. DuckDB connection memory, threads and temporary-space policy remain the
native caller's responsibility.

This machine's GB10 exposes unknown dedicated-memory capacity to the current
native inventory. CUDA remains explicitly unqualified and is rejected before
owner access. The existing CPU feature trainer is unchanged. No GPU speedup or
CUDA capacity was fabricated to satisfy a benchmark.

## Measurements and remaining qualification

Retained component evidence is in
[`evidence/codebase-repository-shards-20261002`](evidence/codebase-repository-shards-20261002/qualification.json).
Actual GTE and checkpoint inference preserved identical decoded rows between
resident and cold-per-page modes. One local observation measured 2.240 seconds
with one model load versus 3.190 seconds with four loads; peak RSS was about
1.015 GB and 1.040 GB respectively. One Git page measured 20 ms with one object
process versus 84 ms with four. A separate four-source page measured 2.562
seconds at model batch size 1 and 2.292 seconds at batch size 4, with the same
closed decoded choices; each batch profile independently addresses its floating
point feature artifacts. These measurements exclude complete owner
preparation/replay where stated, and concurrent host load was uncontrolled.
They are neither repeated-run throughput distributions nor Terminal-Bench
performance results.

Source/Git/watcher correctness controls use the foundation's explicitly injected
host sampler while exercising real Git, filesystem, DuckDB and CAS owners.
Actual model children and the parent-budget refusal use the default live
datasets resource owner. A newly admitted full supervisor envelope remains a
separate qualification; the host's disk/CPU admission policies have refused
recent attempts and were not weakened for these component tests.

Larger dirty initial capture, extraction/inference joined into one large-source
pipeline, larger-scale incremental I/O, repeated timing distributions, live
pressure distributions and compatible CUDA inference remain outside this
qualified profile. Whole bounded source history is still replayed on lookup.
Completing a page inventory alone never establishes formalization or proof
coverage, planning completeness, supervisor success, or task completion.
