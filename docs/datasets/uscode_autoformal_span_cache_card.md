---
configs:
  - config_name: paired_spans
    default: true
    data_files:
      - split: train
        path: autoformal/uscode/paired-v1/paired_spans/**/*.parquet
  - config_name: deferred_goals
    data_files:
      - split: train
        path: autoformal/uscode/paired-v1/goals/**/*.parquet
  - config_name: evidence_artifacts
    data_files:
      - split: train
        path: autoformal/uscode/paired-v1/artifacts/**/*.parquet
  - config_name: retained_outputs_v1
    data_files:
      - split: train
        path: autoformal/uscode/outputs/**/*.parquet
  - config_name: census_v3
    data_files:
      - split: train
        path: autoformal/uscode/census-v3/**/*.parquet
  - config_name: census_v2
    data_files:
      - split: train
        path: autoformal/uscode/census/**/*.parquet
  - config_name: supervisor_goals_v2
    data_files:
      - split: train
        path: autoformal/uscode/goals/**/*.parquet
---

# Paired US Code conversions, diagnostic census and deferred repair goals

New observations use three linked tables. Historical files remain available;
no original observations or goal packets are removed by this migration.

| Configuration | Content | Join key |
| --- | --- | --- |
| `paired_spans` (default) | Source text; raw and projected autoencoder vectors; guided and direct compiler formulas; canonical typed compiler results; comparison; provenance; Lake status | `observation_id`, `source.span_id`, `goal_ids` |
| `deferred_goals` | Disagreement, compiler failure and capability records; source/observation bindings; immutable packet/task references | `goal_id`, `observation_ids` |
| `evidence_artifacts` | Losslessly compressed complete producer receipts, source bridge documents, compiler components, original packets and tasks | `artifact_sha256` |

`uscode-paired-span-bundle/v1` manifests under
`autoformal/uscode/paired-v1/manifests/` bind all three tables by exact SHA-256,
size, row count and immutable repository paths. Read a pinned commit when
comparing runs. The `train` split is a storage label, not a training-quality gate.

```python
from datasets import load_dataset
rows = load_dataset('justicedao/uscode-autoformal-span-cache', 'paired_spans',
                    split='train', streaming=True, revision='<immutable-commit>')
for row in rows:
    print(row['source']['span_id'], row['comparison']['status'],
          row['compiler']['canonical_formal_outputs'], row['goal_ids'])
```

## What is being compared

The local legacy autoencoder emits eight-dimensional diagnostic vectors and
compiler guidance. Its input representation is `mock:stable-sha256/8`, with
no verified semantic embedding provenance. It has no learned legal formula
decoder. The explicitly labeled **autoencoder-guided compiler** converts the
original text using that learned guidance. The direct deterministic modal
compiler processes the same source without that guidance. Both native formula
collections are stored, with their exact payloads and origin labels.

Their agreement is **diagnostic, not independent validation**. The current
comparison checks exact AST sequences including metadata; it does not prove
semantic equivalence. Counts, ordering, polarity, temporal fields, conditions,
exceptions and duplicate components are not silently discarded. Missing outputs,
partial collections and incompatible representations have explicit statuses.
`complete` means the emitted collection was captured; it does not establish
that the compiler represented every legal meaning in the source.

`compiler.canonical_formal_outputs` separately retains actual typed-deontic
compiler results. Its abstentions and completeness remain visible even when
the two modal paths agree. `syntax_status=not_checked` remains explicit for
native modal ASTs that have no independently invoked syntax validator.
Bridge names are requested adapters; they are not proof that all logic
families compiled or passed their validators.

No result in this diagnostic campaign grants admission. `admitted=false`,
`formalized=false`, and Lake `not_run` stay explicit. A separate source-bound
`lake build <Lib>` receipt is the only Lean admission. The Constitution is not
formalized and must never receive `roundtrip_ok` here.

## Complete evidence and later supervisor import

Every batch archives its full original producer receipt once. Rows point into
that content-addressed artifact for bridge documents and compiler components.
It retains source text, direct/guided native documents, guidance, raw evaluation,
failures, scores, source/checkpoint hashes and execution configuration. No target
is relabeled as a learned formula. Artifact rows encode exact bytes as base64
of zlib data and record the uncompressed SHA-256 and size.

The canonical package's `logic.autoformal.paired_span_census` provides
`load_paired_census_bundle()` and `decode_artifact()` with explicit expansion
bounds and hash verification. Nested `recursive-zlib-json/v1` bridge payloads
use `optimizers.logic_theorem_optimizer.legacy_span_logic_artifacts.unpack_document`.

Goals remain dataset records with `enqueued=false`. The existing
`scripts/ops/legal_ir/import_span_cache_exchange.py` validates either new paired
bundles or historical exchange bundles. Its default is a review plan. It can
later import sealed packet/task pairs to a machine-local supervisor database;
capability gaps without such packets stay preserved descriptive deferrals.
Publishing a goal never executes it or authorizes source edits.

## Bounded processing and resume

One resident CUDA model serves a hardware-bounded CPU compiler pool. At most
two batches overlap. Full target/report caches are disabled for this isolated
campaign; chunked compiler work checks the pinned source generation before and
after each chunk. One controller writes the local DuckDB progress queue.
Interrupted work is requeued; immutable Hub uploads use parent-commit checks.
Local batch evidence is removed only after all four remote files are verified
at the exact publication commit. Other machines can read immutable bundles and
later reimport goals; this inference campaign does not synchronize or train weights.

The five bridge adapters are `modal_frame_logic`, `deontic_norms`, `fol_tdfol`,
`cec_dcec`, and `external_prover_router`. Provers are off, disk cache is off,
sample memory is off, temperature is zero. Per-batch receipts record worker
counts, target counts and wall times. A target count of zero is not a faster
legal-IR evaluation.

## Historical schemas

The four existing configurations (`retained_outputs_v1`, `census_v3`,
`census_v2`, and `supervisor_goals_v2`) preserve previous observations and goals.
They are separate from the default paired schema. Older vector-only observations
cannot be retrospectively treated as guided conversions. Some older records
retain only target hashes; absent evidence is not reconstructed or invented.
The original dataset card is retained in the canonical source repository at
`docs/datasets/uscode_autoformal_span_cache_historical_card.md`.

## Published full reports and measured sample

Four lossless original receipts preserve 56 span observations, 45 captured
source logic documents, raw/projected vectors, three canonical compiler rules,
and all available failures, metrics and provenance. Eleven documents were
not captured by the producer limits (ten historical 4 MiB omissions and one
new 16 MiB omission); their identities and reasons remain explicit.

| Receipt | Spans | Captured documents | Full report | Manifest |
| --- | ---: | ---: | --- | --- |
| Historical | 32 | 22 | [gzip JSON](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/resolve/4f7922a2188c111e30841a08769f0f989d0b7c61/autoformal/uscode/reports/v1/reports/43a822841e7192587a190bf56381bc55cdb1249a97ff3fa0a8a876d90bd75e90.json.gz) | [hashes and inventory](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/blob/4f7922a2188c111e30841a08769f0f989d0b7c61/autoformal/uscode/reports/v1/manifests/0f2431a7c4746625fdbf693b312447f138d7ff4b820774ed4990dc334caa84ed.json) |
| Paired smoke 1 | 8 | 7 | [gzip JSON](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/resolve/48cd0a5b666a8ef6cbaf259e9f1cc94792740e8b/autoformal/uscode/reports/v1/reports/49f60d4504a5b8df4d87b0c57eca52eecebdfbcbe5e52c1b74070de960d946fc.json.gz) | [hashes and inventory](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/blob/48cd0a5b666a8ef6cbaf259e9f1cc94792740e8b/autoformal/uscode/reports/v1/manifests/376e7def7c18e0851908190de9dae6d5535eba0efd46e09d45b4fede75d36c18.json) |
| Paired smoke 2 | 8 | 8 | [gzip JSON](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/resolve/45acc122f3f9c11da46c039e057a38ab5054a699/autoformal/uscode/reports/v1/reports/5fe4185488765685d8b4449f2bfbc1fab8d56f853ef333d0bab3ef06a98e812e.json.gz) | [hashes and inventory](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/blob/45acc122f3f9c11da46c039e057a38ab5054a699/autoformal/uscode/reports/v1/manifests/93d2f5a4779f6888bdf8938607e5a8990dbf019f00cf003faa704fc2d56d40f9.json) |
| Paired smoke 3 | 8 | 8 | [gzip JSON](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/resolve/f1ff72b4b171fca4ac63a44e4f263982e9129f03/autoformal/uscode/reports/v1/reports/fae864238b8c34e19aecaada1aa650fe7d5c7828c7eb5869c1ec40ae066366f9.json.gz) | [hashes and inventory](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/blob/f1ff72b4b171fca4ac63a44e4f263982e9129f03/autoformal/uscode/reports/v1/manifests/141c0182a532d30d0beb1886dcaa7071fd65aa5441a8ee9da92e85264630b0ea.json) |

The new paired sample contains 24 spans, 15 guided formulas and 15 direct
formulas. Nine rows have diagnostic AST agreement; 15 have no formulas from
either path and do not count as agreement. Twenty-three source-bound compiler
repair goals were retained. A remote import smoke validated seven goals from
one bundle in plan-only mode; nothing was enqueued or executed.

Three batches of eight used one resident CUDA model, four CPU compiler workers
and one bridge worker. Bridge-on evaluation wall times were 19.28, 9.34 and
9.50 seconds, with eight targets in every batch. Worker wall times were 3.82,
1.99 and 2.11 seconds per span, including the two codec paths. Both large
process report caches stayed empty between batches; the disk cache and provers
were disabled. Other parser/runtime caches may warm. Sampled peak process-group
memory was 3.57 GiB. These are measured sample costs, not a matched speedup
comparison or evidence of legal qualification.

Read a downloaded gzip report with `json.loads(gzip.decompress(report_bytes))`.
Packed bridge documents additionally use the documented lossless document
unpacker. File and inner-document hashes verified for every available document;
the historical archive was also downloaded and reconstructed byte for byte.
