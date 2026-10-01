# Reviewed source pairs for distributed 384d training

`distributed_384.paired_export.export_reviewed_pairs` converts an explicitly
reviewed source/native-IR pair manifest and a separately bound embedding manifest
into the six-field rows used by the distributed trainer. It performs no model
calls, training, source execution, or publication. The default parent is the
domain's pinned published checkpoint; `base_path` can select another compatible
structured checkpoint.

The current SkillCenter feature export contains native structural weak targets.
The CVEFixes corpus adapter contains classification-only audit/CWE/polarity
targets and omits source code bodies from its portable derivatives. Neither
export is a reviewed instruction/code-to-native-IR training set. This importer
rejects those formats; it does not manufacture formal targets from their labels.

## Pair manifest

The top-level object has exactly these fields:

```json
{
  "schema": "ir384-reviewed-source-pairs/v1",
  "domain_id": "intent_ir",
  "source_descriptor": {
    "schema": "ir384-corpus-source/v1",
    "description": "Describe the source snapshot, pair review, and permitted use.",
    "redistribution_allowed": false
  },
  "rows": []
}
```

Each row has exactly `id`, `split`, `source_text`, `target`, `source_identity`, and
`review`. `split` is explicitly `train` or `validation`. `target` is the actual
native target accepted by the domain and the parent's frozen schema/vocabulary.
The importer neither rewrites targets nor extends the parent's classes.

`source_identity` has exactly these fields:

| Field | Meaning |
| --- | --- |
| `source_uri` | The source document or upstream repository location. |
| `source_revision` | An immutable 40-character lowercase revision. |
| `record_id` | The source row, function, clause, or document identity. |
| `leakage_family_ids` | One to 64 explicit family identities that must remain in one split. |

Use repository/package families for related code or skill versions, and shared
document/clause families where appropriate for legal text. Keep families stable
across source revisions. All variants and vulnerable/fixed pairs from the same
family must remain together. A row can declare several families; grouping takes
their transitive closure. The importer also connects identical source records
(including the same URI/record identity across different revisions),
exact or case/whitespace-normalized text, and numerically equal vectors before
auditing the explicit splits. It rejects a component spanning both splits. It
cannot discover undeclared semantic paraphrases.

`review` has exactly these fields:

```json
{
  "schema": "ir384-source-native-review/v1",
  "decision": "accepted",
  "scope": "source_to_native_ir",
  "reviewer": "Identity of the person or review process",
  "rationale": "Explain why this source supports this particular native target.",
  "source_sha256": "SHA256 of the exact UTF-8 source_text",
  "target_sha256": "Canonical JSON SHA256 of target",
  "source_identity_sha256": "Canonical JSON SHA256 of source_identity"
}
```

These are declared reviews, not authenticated signatures or independently proved
semantic equivalence. A successful import means that the supplied declaration
matches the exact source, target, and provenance. It does not elevate that
declaration to a proof or certify the labels as gold.

Use `distributed_384.contracts.digest(value)` for canonical JSON hashes. It uses
UTF-8 JSON with sorted keys, compact separators, `ensure_ascii=False`, and no
trailing newline. Use `hashlib.sha256(text.encode("utf-8")).hexdigest()` for text.

## Embedding manifest

The second file has exactly `schema`, `provenance`, and `rows`, with schema
`ir384-source-embeddings/v1`. Its rows have exactly:

| Field | Meaning |
| --- | --- |
| `id` | An existing pair identity, appearing exactly once. |
| `source_sha256` | SHA256 of that pair's exact source text. |
| `embedding_sha256` | Canonical JSON SHA256 of the following vector. |
| `embedding` | Exactly 384 finite numbers. |

`provenance` records the actual embedding process. It must match the parent's
`config.embedding_provenance` for model identity, immutable revision, dimension,
normalization, dtype, pinned assets, and every other semantic pipeline setting.
The importer ignores only run telemetry: device, batch size, row count, timing,
throughput, and maximum observed token count. Both sides must declare
`truncated: false`; normalized vectors are also checked for unit L2 length.
Asset hashes are compared with the parent, but this import does not rerun the
embedding model or verify that the submitted vectors were computed by it.

Do not copy a parent's provenance onto vectors produced by another model. New
embedding computation needs its own source-bound evidence and must preserve the
same tokenizer, pooling, normalization, and model assets. The published GTE
parents include the pooling and tokenizer configurations in their asset pins.

## Export and prepare

```bash
python scripts/ops/autoencoder/run_distributed_384.py export-pairs \
  --domain intent_ir --pairs reviewed-pairs.json --embeddings embeddings.json \
  --output-dir work/reviewed-export --result work/reviewed-export-result.json
```

```python
from pathlib import Path
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import (
    contracts, paired_export, runner,
)

exported = paired_export.export_reviewed_pairs(
    "intent_ir", Path("reviewed-pairs.json"), Path("embeddings.json"),
    Path("work/reviewed-export"),
)
prepared = runner.prepare_round(
    "intent_ir", exported["training_path"], exported["validation_path"],
    Path("work/round"),
    source_descriptor=contracts.read_json(exported["source_path"]),
    base_path=exported["base_path"],
)
```

The export includes immutable `training.json`, `validation.json`, `source.json`,
and `audit.json`. The audit retains exact input/parent identities, review
declarations, row bindings, conservative group membership, and embedding pipeline
identity. Identical retries are allowed. Changed inputs require a fresh output
directory. The bounds are 2,048 training and 4,096 validation rows; test/canary
partitions cannot be silently reassigned to either fitting split.

An out-of-vocabulary target requires a separate schema/training workflow. Adding
this importer does not remove that limit, change the Legal parent, or qualify a
missing logic-family projection.
