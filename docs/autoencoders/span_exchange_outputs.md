# Reading autoencoder outputs, compiler results, and deferred repair goals

The dataset [`justicedao/uscode-autoformal-span-cache`](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache)
retains independent observations from the autoencoder and source compiler,
alongside portable goals for later review by an `ipfs_accelerate_py` supervisor.
An exchange manifest binds its census and goals by exact hashes. An uploaded
row, a target formula, or a compiler text round trip grants no Lake admission.

| Repository files | Contents | Schema |
| --- | --- | --- |
| `autoformal/uscode/census/<agent>/*.parquet` | Historical complete observations, mostly inside `input_json` | census v2 |
| `autoformal/uscode/census-v3/<agent>/*.parquet` | Complete observations plus explicit compiler and AE columns | census v3 |
| `autoformal/uscode/goals/<agent>/*.parquet` | Bound repair packets and training goals, including acceptance criteria | goal export v2 |
| `autoformal/uscode/exchanges/<agent>/*.manifest.json` | Exact census/goal file hashes, row counts, and identities | exchange v2 or v3 |
| `autoformal/uscode/outputs/<agent>/*.parquet` | Queryable derived views of already retained observations | output index v1 |
| `autoformal/uscode/outputs/<agent>/*.manifest.json` | Derived table hash and pinned source closure | output index v1 |

`source_span_id`, `source_text_sha256`, and `census_sha256` connect the tables.
Different model or compiler revisions may produce distinct observations of the
same source span. Preserve all observations; do not overwrite by span ID alone.
The census hash identifies the observation referenced by each deferred goal.

## Reading the evidence

The legacy CUDA model produces vectors and feature scores. Its raw decoder
and target-conditioned safety projection have separate columns. Empty
`autoencoder_text` and `autoencoder_compiled` fields indicate that the model did
not emit those forms. Its eight-dimensional diagnostic vectors have no verified
semantic encoder provenance. Their reconstruction scores are diagnostic metrics.

The source compiler's formulas are in `compiler_rules_json`, with every retained
component in `compiler_components_json` and the complete original compiler
observation in `input_json`. `compilation_complete` distinguishes full results
from partial component evidence. A rule may be useful for repair even when the
whole span abstains. The derived output table also exposes `compiler_rule_count`,
`compiler_status`, `compiler_reason`, `compiler_decompiled`, and
`compiler_result_json`.

The full source-derived bridge target, when captured by the producer, is in
`logic_target_observation_json`. It is a target artifact, not a model-generated
formula or an external proof. `bridge_names_json` reports adapters invoked;
`observed_logic_views_json` records view names and `observed_logic_families_json`
records explicitly declared family metadata. Adapter selection does not imply
that every named logic family passed its syntax validator. Older censuses that
contain only target hashes cannot recover missing bridge documents through
indexing. Their derived `logic_target_availability` is `not_recorded_in_source`.

Newly captured documents can use `document_encoding=recursive-zlib-json/v1`.
This is lossless storage: large view payloads, view metadata, and top-level
frame-logic triples are compressed while compact formulas stay queryable.
Each compressed field carries its uncompressed byte count and SHA-256 digest.
The observation's original document hash still refers to the complete restored
document. Decode with the bounded verification helper rather than unbounded
manual decompression:

```python
import json
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legacy_span_logic_artifacts import (
    DOCUMENT_ENCODING, unpack_document,
)

observation = json.loads(row["logic_target_observation_json"])
document = observation.get("document") if observation else None
if document is not None and observation.get("document_encoding") == DOCUMENT_ENCODING:
    document = unpack_document(document, max_decoded_bytes=16 * 1024 * 1024)
```

Run this from the canonical checkout with its root first on `PYTHONPATH`.
`unpack_document` verifies lengths, digests, and the aggregate decoded document
bound. The indexer preserves the packed observation exactly; it does not expand
graphs during indexing or invent documents missing from historical exports.

Every original input and its producer provenance remains in `input_json` and
`comparison_provenance_json`. Missing observations stay missing. Compiler output
does not become autoencoder output; target-conditioned scores do not become raw
decoder scores. `admitted` and `formalized` remain false in these exports.

For a locally downloaded output parquet:

```python
import duckdb

connection = duckdb.connect(":memory:")
print(connection.execute("""
    SELECT source_span_id, compiler_status, compiler_rule_count,
           compiler_rules_json, autoencoder_raw_embedding,
           autoencoder_raw_reconstruction_loss, goal_references_json
    FROM read_parquet(?)
    WHERE compiler_rule_count > 0
""", ["outputs-<sha256>.parquet"]).fetchall())
```

This query uses a private in-memory database. It does not open the running
campaign's DuckDB queue. A saved output manifest gives the exact original
source revision and paths for its census, goals, and exchange manifest.

## Exposing historical v2 observations without inference

Run from the canonical `external/ipfs_datasets` checkout:

```bash
PYTHONPATH="$PWD" HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=1 \
python3 scripts/ops/legal_ir/index_span_exchange_outputs.py \
  --revision d09589f6cea1b2712251e1df140289a744517af3 \
  --manifest-in-repo autoformal/uscode/exchanges/legacy-cuda-census/exchange-76fa6d46ab0c13b05e3db3c18fa23ab44ad23e616e9566c292c84849b906704b.manifest.json \
  --output-dir workspace/test-logs/span-output-index-example
```

The command defaults to local preparation. Add `--upload` to append the verified
derived table and manifest to the same dataset. Existing source census/goals and
the progress ledger remain unchanged. The indexer performs no model loading,
weight download, inference, training, compiler execution, Lake execution, or
supervisor import. The index's `inference_executed=false` and
`training_executed=false` describe the indexing operation; the retained producer
observation separately records what originally ran.

Use repeatable `--manifest-in-repo` for up to 64 explicit manifests at the same
immutable revision. For an already downloaded sealed exchange, use repeatable
`--manifest` instead. Source revision is still required. Local-only staging
does not prove the files exist in that remote commit; upload verifies the exact
remote source closure before accepting those references.

Each manifest is processed separately. Defaults cap compressed input, decoded
input, and cumulative output to 64 MiB each, and census/goal tables to 1,000 rows
per artifact. These limits can be lowered with `--max-bytes`,
`--max-decoded-bytes`, `--max-output-bytes`, and `--max-rows`. The implementation
checks decoded expansion before accepting rows and keeps only one input bundle
in memory. Use a fresh output directory per bounded job and account for its
retained outputs in storage planning; the CLI does not reserve campaign storage.
Temporary dataset downloads are removed between manifests.

Source hashes and schema are checked before extraction. Upload verifies source
objects at the pinned commit, rejects conflicting immutable output paths, uses
the current Hub commit as a compare-and-swap parent, and verifies the resulting
objects. A concurrent writer can make the CAS fail; rerun the same command.
Identical retained output is idempotent. Do not infer publication from a local
parquet: the returned `publication.commit_sha` is the publication receipt.

## Dataset viewer configuration

Add these configurations to the existing dataset card's YAML front matter,
preserving its other metadata and configurations. Add a configuration when at
least one corresponding file is published. Separate schemas must have separate
configurations; avoid a repository-wide parquet glob.

```yaml
configs:
  - config_name: census_v2
    data_files:
      - split: train
        path: autoformal/uscode/census/**/*.parquet
  - config_name: census_v3
    data_files:
      - split: train
        path: autoformal/uscode/census-v3/**/*.parquet
  - config_name: supervisor_goals_v2
    data_files:
      - split: train
        path: autoformal/uscode/goals/**/*.parquet
  - config_name: retained_outputs_v1
    data_files:
      - split: train
        path: autoformal/uscode/outputs/**/*.parquet
```

`train` is a dataset split label, not a claim that the rows are qualified
training examples. Hugging Face supports separate configurations and globbed
data-file paths in dataset cards; see its
[manual configuration documentation](https://huggingface.co/docs/hub/datasets-manual-configuration).
Once configured, load only the desired table:

```python
from datasets import load_dataset

rows = load_dataset(
    "justicedao/uscode-autoformal-span-cache",
    "retained_outputs_v1",
    split="train",
    revision="<immutable-published-commit>",
    streaming=True,
)
```

The derived table indexes observations; it does not replace a full census or
goals dataset, and it does not implicitly combine duplicate observations across
different source manifests.

## Importing deferred supervisor work later

`goal_references_json` lists task IDs and packet/task hashes for the row's census
identity. Follow `source_goals_path` at `source_revision` to the full
`packet_json` and `task_json`, including source context, observed failures,
repair scope, and original acceptance requirements. These are exported work
items with `handoff_status=dataset`, `enqueued=false`, and no execution authority.

Use [`import_span_cache_exchange.py`](../../scripts/ops/legal_ir/import_span_cache_exchange.py)
with the original exchange manifest to validate or prepare a later import.
Its default is planning only. An explicit native import creates review-only,
blocked work in that machine's supervisor database. Exported shell commands
never automatically become validation commands. The output index itself cannot
enqueue, claim, execute, or mark any goal complete.

Compiler fixes must preserve the pinned-tree parser contract, existing temporal
and exception gates, empty-vocabulary abstention, and source-locked Lake
admission. The Constitution remains unformalized.
