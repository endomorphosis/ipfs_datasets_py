# Paired span CUDA smoke — 2026-09-30

Three native batches processed **24 U.S. Code spans and 24 legal-IR targets**.
They retained 24 raw decoder observations, one canonical compiler rule, and
15 formulas on each side of the direct-versus-guided modal comparison. The
paired census records nine diagnostic agreements and 15 cases where neither
path emitted a formula. It exports 23 deferred compiler-repair packets for
later supervisor ingestion. These observations performed no training, syntax
qualification, external proof evaluation, or Lake admission.

The [machine-readable evidence](../implementation/reports/evidence/paired-span-smoke-20260930.json)
contains all batch IDs, exact source texts and hashes, checkpoint identity,
producer hashes, configuration, cache counters, periodic memory observations,
and publication receipts. The [campaign runbook](legacy_cuda_span_campaign.md)
describes the inference contract; the receipt is authoritative for this run's
actual settings.

| Batch | ID | Spans / targets | Bridge-on evaluation | Worker wall time / span | Whole-batch residence |
| --- | --- | --- | --- | --- | --- |
| 1 | `2ad3ea5cb72544a6a2765c5cd4f0a73b` | 8 / 8 | 19.2815 s | 3.8218 s | 32.4680 s |
| 2 | `40deac30da45428682f552c5a47b8520` | 8 / 8 | 9.3420 s | 1.9937 s | 47.4921 s |
| 3 | `1cf1539e4de64e20a06231720b06d8dc` | 8 / 8 | 9.4979 s | 2.1142 s | 33.4857 s |

All batches ran `modal_frame_logic`, `deontic_norms`, `fol_tdfol`, `cec_dcec`,
and `external_prover_router`, with prover evaluation disabled, disk metric
caching disabled, one target worker, and one adapter worker. Bridge-on time
includes target preparation and artifact capture. Worker time also includes
guided compiler observation and producer-source guards. CPU prefetch overlaps
batch residence, so those residence times must not be added together as elapsed
campaign time. CUDA readiness was recorded at 18:39:38 UTC; the final batch
completed at 18:40:45 UTC, before the separate publication phase.

One persistent CUDA model served four compiler processes using two-span chunks.
The capacity planner allowed two batches in flight inside the existing
12,288 MiB reservation. Both the process target cache and the native multiview
report cache remained at **zero entries before and after every batch**. Each
batch generated eight native targets with zero cache hits and zero timeout
fallbacks. The first batch loaded bridge modules; subsequent batches reused
the process. This is a cold-target measurement, not a claim that every process
cache was cold. The first evaluation recorded 494 CUDA kernel events.

Across 27 periodic observations, the largest owner-plus-process-group RSS was
**3,834,368,000 bytes (3.571 GiB)**. Sampling began after CUDA readiness and
therefore does not establish the startup high-water mark. Three small batches
also do not establish a long-running RSS plateau. No matched previous-version
experiment was run, so this report claims no speedup or memory-reduction ratio.

The full reports preserve **23 of 24 target documents**. One source span
(`uscode-span-13cea0f9cc059201958094227a93bbc7141127122ed480353d8c8a9adf134c93`)
produced an 18,678,464-byte document and retains its hash and
`document_exceeds_16mib_decoded_bound` reason. Its complete document was not
exported. Every available document's recorded hash was verified during report
publication. Bridge view names describe captured artifacts; their presence is
not a syntax or semantic qualification result.

The local checkpoint was the immutable 398,209,746-byte legacy state with SHA256
`7236de26bd3d7f8414ffa04805f1b6e8a8849f9e0103cec6edb4985b911658be`.
The canonical compiler, decompiler and parser loaded from
`/home/barberb/lift_coding/external/ipfs_datasets/ipfs_datasets_py`; all native
observations share producer SHA256
`15e73447e9a5a7b222836d89a088c33e9bdf422429a0a89afeff9ecab1977729`.
Before/after source guards passed. Temperature remained zero, sample memory
was disabled, and no weights were downloaded or updated.

The input representation remains the legacy eight-dimensional
`mock:stable-sha256` diagnostic. Guided formulas come from a deterministic
compiler influenced by the model and source-derived targets; they are not an
independent learned symbolic decoder. Many sampled inputs are citation or
editorial fragments such as `L.`, `Pub.`, and `Subsec.`. The canonical compiler
reported 21 `no_parser_elements` abstentions and two unsupported-semantics
abstentions alongside its single rule. A diagnostic agreement does not show
that the underlying legal proposition is correct. `admitted`, `formalized`
and `semantic_qualified` remain false; Lake status is `not_run`.

All three complete producer receipts were published losslessly as compressed
JSON, with their original bytes and hashes retained in the manifests:
[batch 1](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/commit/48cd0a5b666a8ef6cbaf259e9f1cc94792740e8b),
[batch 2](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/commit/45acc122f3f9c11da46c039e057a38ab5054a699),
and [batch 3](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/commit/f1ff72b4b171fca4ac63a44e4f263982e9129f03).
The [paired tables, artifacts and deferred goals](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/tree/35326d1e55ece45c13900a23b2d8059a84818006/autoformal/uscode/paired-v1)
were separately published and verified before local cleanup. No goals were
enqueued into a supervisor.

The focused validation suite passed **227 tests**, with zero failures, errors
or skips (7.458 seconds recorded by the JUnit suite). This covers implementation
contracts; the native smoke supplies the measured execution evidence above.
