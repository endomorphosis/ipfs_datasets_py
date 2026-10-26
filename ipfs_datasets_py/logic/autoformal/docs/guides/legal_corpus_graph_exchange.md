# Candidate Legal corpus graph exchange

This additive v1 profile exports and validates a bounded local candidate graph.
It preserves complete sealed node/edge records and explicit graph endpoints.
It is a graph interchange format, not a complete statutory or Lean corpus
release. Validation establishes local record/file integrity; it does not
authenticate source provenance, review legal interpretation, resolve external
references, run a model, compile Lean, or publish to Hugging Face.

The source, qualification and graph contracts remain separate. Use
`corpus_source` to bind exact raw/extracted identities and extracted-view
coordinates. Use the current review/interpretation owners to qualify meaning.
A graph node's content/source/interpretation CIDs are preserved references:
their presence alone does not authenticate the referenced records.
Losslessness applies to graph envelopes. Source records, producer-specific
formal payloads and review receipts addressed by those CIDs remain external;
retain the companion candidate records when exchanging those payloads.

## Format and supported profile

The API owners are `logic/autoformal/corpus_graph.py` and
`logic/autoformal/corpus_graph_exchange.py` under `ipfs_datasets_py/`.

| File | Content |
| --- | --- |
| `snapshot.json` | Exact canonical DAG-JSON sealed `legal-corpus-candidate-graph/v1` snapshot |
| `nodes.parquet` | Readable node projections plus each complete canonical node record |
| `edges.parquet` | Readable endpoint/relation/ordinal projections plus each complete canonical edge record |
| `manifest.json` | Sealed `legal-corpus-graph-bundle/v1` manifest binding all three files by SHA256, size and row count |

The manifest records `snapshot_cid`, `node_count`, `edge_count` and
`format_profile=candidate-graph-parquet-with-canonical-records/v1`. Its own
external SHA256 is supplied by the caller and is not a self-included field.
The manifest and snapshot retain `view=candidate`, `admitted=false`,
`formalized=false` and `source_semantics_verified=false`; the bundle also
records `external_references_verified=false`.

V1 requires every edge endpoint in the same snapshot. External imports are
unsupported. It validates the current node/relation profile, ordered role
positions, duplicate records and mutually exclusive interpretation boundaries.
Repeated role arguments remain distinct through their explicit ordinals.
It does not infer scope, merge equivalent terms, complete missing graph
relationships or substitute omitted records. Unsupported or malformed inputs
fail rather than being skipped.
Source-only snapshots are permitted. This phase does not project the varying
cached `typed-deontic-rule/v1` payloads into a unified typed rule/definition
schema or automatically promote them into semantic assertion nodes.

The common record envelope currently bounds canonical snapshots to 1 MiB,
25,000 JSON nodes and depth20. Graph limits are 4,096 nodes and8,192 edges;
the aggregate record bound may be reached earlier. Partitioning larger corpora
requires a separately specified profile and explicit dependency accounting.
Parquet exchange requires the optional `pyarrow` dependency. Missing dependencies
produce an explicit failure; no network installation or model loading occurs.

## Python API

```python
from ipfs_datasets_py.logic.autoformal.corpus_graph_exchange import (
    load_graph_bundle,
    write_graph_bundle,
)

manifest = write_graph_bundle(sealed_snapshot, output_directory)
loaded = load_graph_bundle(
    output_directory,
    expected_manifest_sha256=independently_expected_manifest_sha256,
)
assert loaded["snapshot"]["record_cid"] == sealed_snapshot["record_cid"]
```

The writer requires a new output directory and refuses overwrite. Keep incomplete
failed attempts distinct from a successfully validated bundle. The loader checks
the exact manifest, payload files, projections, row counts and reconstructed
snapshot; it returns `{"manifest": ..., "snapshot": ...}`. Neither API promotes
candidate assertions or verifies separately referenced semantic/source evidence.

## Command line

Use an installed package or an explicitly qualified package path. There are no
runtime `sys.path` modifications. These commands perform local file operations:

```bash
IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 python -m scripts.ops.legal_ir.validate_uscode_corpus_release export \
  --snapshot /absolute/path/snapshot.json \
  --snapshot-sha256 EXPECTED_SNAPSHOT_SHA256 \
  --output /absolute/path/new-bundle

IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 python -m scripts.ops.legal_ir.validate_uscode_corpus_release validate \
  --bundle /absolute/path/new-bundle \
  --manifest-sha256 EXPECTED_MANIFEST_SHA256
```

Direct script execution is also supported when public package imports are
qualified by the environment:

```bash
IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 PYTHONPATH=/absolute/path/ipfs_datasets_py_checkout \
  python /absolute/path/ipfs_datasets_py_checkout/scripts/ops/legal_ir/validate_uscode_corpus_release.py \
  validate --bundle /absolute/path/new-bundle --manifest-sha256 EXPECTED_MANIFEST_SHA256
```

Replace uppercase placeholders with digests from the source-intake or release
custody boundary. Hashing arbitrary local input and passing that same hash proves
only its local identity; it does not establish source authenticity.

Export verifies an independently expected snapshot SHA256 before parsing and
graph validation. It reads a bounded regular file without following final or
parent-component symlinks, writes the new bundle, then performs a complete
readback with the computed manifest digest. Validation requires the expected
manifest SHA256 and performs the same bundle integrity checks. This snapshot
path profile requires directory descriptors and `O_NOFOLLOW` support.

Each invocation writes one JSON receipt to stdout. Successful validation/export
returns exit0 with `snapshot_cid`, `manifest_cid`, `manifest_sha256`, `node_count`
and `edge_count`. Errors return nonzero with `status=error`, an error type and
message. `--help` returns a JSON usage receipt. All receipts explicitly retain
false admission/formalization, source-authenticity, semantic and proof flags.
They qualify only the candidate graph v1 local-integrity profile.

## Extension boundary

This exchange does not replace the existing span cache, entity-cache inventory,
definition/norm composition, review recorder or Lake owners. It supplies an
additive reconstructable candidate graph view. A future coherent corpus release
must separately bind exact span/entity dataset revisions, reviewed semantic
artifacts, resolved definition dependencies, generated Lean modules, toolchain
and actual compilation/theorem receipts. No such release is claimed by v1.
