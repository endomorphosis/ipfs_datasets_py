# Pinned US Code span-cache coverage survey

Survey snapshot: [`justicedao/uscode-autoformal-span-cache@765176c6db79ba65c1697c21dead43666350b730`](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache/tree/765176c6db79ba65c1697c21dead43666350b730). This is a read-only planning survey. It downloaded bounded metadata, two small original Parquet samples, and partial-file HTTP ranges; it did not download the corpus, execute models, enqueue goals, alter databases, or publish anything.

## Scope and denominators

The pinned Hub inventory contains **6,016 files / 4,870,101,925 bytes**. Dataset Viewer exposes eight configurations and 76,397 records in total, but that is a sum of overlapping observation, goal, and artifact tables. It is not a unique-span count. Its configured Parquet files occupy 2,753,002,877 bytes; roughly 2.117 GB of other files are outside that view, including queue, modal parser, checkpoint, and feature-training evidence.

| Universe | Verified or reported count | Interpretation |
| --- | ---: | --- |
| Original resume checkpoint | 443,905 rows | Independently read original pinned footer |
| Queue `record_kind=span` | 443,904 records | Independently scanned inexpensive columns with 185,570 Range bytes; uniqueness of IDs not yet scanned |
| Queue metadata | 1 row | Not a legal span |
| Archived queue status | 22,379 sealed; 421,525 gap | Historical operational state, not present inference completion or proof admission |
| Existing source Parquet | 60,077 section records | Reused local 374,277,662-byte source; complete SHA-256 verified as `4d26df1e3814279e4b4df3af0e454b4f64fc89a81879db926989862b6ad7d8b8` |
| Paired-v1 | 4,888 observations | All 611 bundle manifests verified against complete table-path inventory |
| Paired-v1 goals | 4,740 goal records | Descriptive deferred goals, not execution authority |
| Paired-v1 artifacts | 10,091 artifact records | Evidence records, not source spans |
| Census v2 / v3 | Viewer 26,952 / 1,184 | Converted-view counts; independent original-file count/ID joins still required |
| Retained outputs / formula text | Viewer 32 / 372 | Historical observations / repeated formula occurrences; do not add as new spans |
| Supervisor goals v2 | Viewer 28,138 | Goals, not spans |
| Modal parser namespace | Producer reports 443,904 parsed rows and 639,347 formula occurrences | Twelve worker manifests and 120 materialized JSONL shards; independent complete row/ID census still required |

The queue metadata reports `documents=60068` and `pending_count=3820263`. These are legacy producer counters. The latter must not become a remaining-unique-span denominator. The difference between 60,068 processed documents and 60,077 source rows should be investigated during source hydration; this survey did not establish why those nine rows differ.

The modal namespace is not one of the eight Dataset Viewer configs. Its 133 files occupy 1,218,995,078 bytes. Individual JSONL shards range from 2,573,178 to 14,950,423 bytes. All manifests retain `qualified=false`, `admitted=false`, and `formalized=false`; the parser's reported coverage must not overwrite earlier queue status or qualify any semantics.

## Closed-manifest coverage and schema migration

The 611 paired manifests are all `uscode-paired-span-bundle/v1`, under `autoformal/uscode/paired-v1/manifests/legacy-cuda-census/`. Every manifest's three table paths exists at the pinned commit, with the exact declared byte count and LFS SHA-256. Conversely, every one of the 1,833 materialized paired/goals/artifacts Parquet paths belongs to exactly one manifest. Table totals are:

- Paired observations: 26,259,160 bytes / 4,888 rows.
- Goals: 7,342,668 bytes / 4,740 rows.
- Evidence artifacts: 1,896,349,436 bytes / 10,091 rows.

This is a manifest closure check; the survey did not expand or read all table bodies. Content-addressed filenames have no intrinsic temporal ordering, so no individual hash should be called the latest run without a producer/publication receipt.

There are **no paired-v2 files** in this snapshot. The current local canonical `paired_span_census.py` declares v2 census and bundle schemas, including learned-formula capture and source binding. New learned 384D/768D observations therefore require explicit v2 exports preserving their own source, model, task, and schema identities. Existing v1 observations must remain immutable.

## Representation and qualification

The pinned README identifies existing paired data as a legacy **`mock:stable-sha256/8` diagnostic representation**, with no verified semantic embedding provenance and no learned legal-formula decoder. A sampled original paired row independently confirms `embedding_model=mock:stable-sha256`, `semantic_embeddings=false`, and a `legacy-mock-diagnostic` model identity. Its formulas are guided/direct source compiler outputs. Agreement between those related paths is diagnostic, not independent legal validation.

The readable formula audit is a separate 56-observation audit: 45 captured documents, 11 unavailable documents, 372 formula occurrences, and 328 fallback formula occurrences. Its manifest explicitly sets learned formula generation, independent validation, training qualification, and admission to false. Retain exact formula strings, duplicates, source pointers, omission reasons, and fallback flags. Syntax success or a nonempty output must not establish a correct/gold target.

The dataset card metadata has no `license` field. This is an observed metadata gap, not a conclusion about legal rights. The processing inventory should capture the source dataset and derived-asset rights/publishing policies explicitly.

## Exact first census to implement

1. Freeze the source-cache commit above, the source dataset revision `5016b86a273ce5e4ffd066c5ae9f5fe494dd417e`, source byte hash, inventory files, producer code identities, and run configuration. Prefer the existing local verified source and previously generated assets over downloading/regenerating them.
2. Scan original Parquet/JSONL files by projection or streaming. Count record kinds separately; materialize source identity columns, not all compressed evidence artifacts. Authenticate complete downloaded files where needed; a footer/range receipt does not authenticate the entire file body.
3. Establish `source_span_id` uniqueness and source-text hash agreement within each source generation. Preserve repeated observations of one source with different model/code/run/task identities. Quarantine same-ID/different-source conflicts. Never deduplicate by legal citation or text hash alone: different source CIDs can share both.
4. Rehydrate queue spans from the existing source using the documented **historical 64-valid-document ordinal groups**. Those groups are independent of current batch size. Reproduce CID, citation, release, sentence splitting, ordinal, text hash, and span ID. Require exact ledger joins; preserve unmatched inputs as source-resolution gaps.
5. Join paired v1, historical censuses, retained outputs, modal records, and goals to the canonical source inventory. Record namespace/run-specific observed coverage, materialized evidence coverage, and missing source/outputs without converting legacy operational flags into current authority.
6. Produce an immutable census manifest and queries for distinct canonical source keys; conflict counts; spans with verified source text; spans with authentic 8D/384D/768D assets; task-specific decoder eligibility; source/IR/token-length coverage; and explicit deferred reasons. This establishes the full processing denominator before the fleet runs.
7. Reuse embeddings only when source bytes, span/window identity, encoder revision, tokenizer/preprocessing, truncation policy, dimensionality, normalization, dtype, and embedding bytes agree. Mock 8D vectors cannot serve as cached GTE 384D or 768D vectors. Retain the old vectors and diagnostic outputs as separate evidence.

Receipts: `metadata-survey.json`, `manifest-closure-survey.json`, `original-schema-samples.json`, `progress-record-scope.json`, and `existing-source-parquet-survey.json`. Bounded original metadata copies are under `pinned-metadata/`.
