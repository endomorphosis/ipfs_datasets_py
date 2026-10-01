# Paired US Code conversions and deferred compiler work

The canonical export contains three typed Parquet tables and one immutable
manifest per bounded inference batch. It records the source, the direct
compiler output, either a captured learned formula or autoencoder-guided compiler output, their comparison,
and deferred supervisor goals. New paired exports do not require a parallel
legacy census export. Historical census, progress and retained-output files are
preserved as historical evidence.

The destination is
[`justicedao/uscode-autoformal-span-cache`](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache).
Use an immutable Hub commit when sampling, comparing or importing records.

## What the two conversion paths mean

The legacy CUDA autoencoder reconstructs eight-dimensional vectors from
`mock:stable-sha256` inputs. Its historical checkpoint has no verified semantic
embedding provenance and does not independently decode legal formulas.

The enabled guided route uses that resident model's measured guidance in the
deterministic modal compiler. The comparison runs the same codec on the same
source, identifier and source embedding twice: once without learned guidance
and once with it. Both emitted formula collections are retained verbatim.
The original sample parser document is retained separately in the full
producer receipt; it is not substituted for the codec's unguided baseline.
This provides a diagnostic comparison of two conversion paths through the
same codec. It does not turn the compiler into an independent learned symbolic
decoder. If the guidance uses source-derived target distributions,
`target_conditioned` records that fact.

The typed deontic canonical compiler also runs independently. Its complete
rule list, partial compilation status, decompiled text and failure reason are
retained. A successful direct modal conversion can coexist with a canonical
compiler abstention; the abstention still generates repair work.

None of these observations runs training, changes a checkpoint, executes a
supervisor goal, proves a proposition or grants legal admission. Only the
separate source-bound `lake build <Lib>` path can admit. The Constitution is
not formalized and is never marked `roundtrip_ok` by this export.

## Tables and paths

New schema identifiers are `uscode-paired-span-census/v2` and
`uscode-paired-span-bundle/v2`. Version 1 bundles remain readable with their
original strict AST comparison. They are not rewritten or silently promoted
to the additional version 2 comparison contract. New paths are:

| Table or manifest | Repository path |
| --- | --- |
| Paired observations | `autoformal/uscode/paired-v2/paired_spans/<agent>/*.parquet` |
| Deferred goals | `autoformal/uscode/paired-v2/goals/<agent>/*.parquet` |
| Evidence artifacts | `autoformal/uscode/paired-v2/artifacts/<agent>/*.parquet` |
| Exact bundle manifest | `autoformal/uscode/paired-v2/manifests/<agent>/*.json` |

The manifest binds each table's exact filename, SHA-256, byte size and row
count. `exporter_sha256` separately identifies the exporter source file, so a
later schema restaging does not masquerade as new native inference. Table
filenames include both the bundle identity and table identity.
Thus two batches with identical empty goal tables do not share a local file
that publication cleanup could remove prematurely.

`paired_spans` has one row per source observation. These nested columns are
the primary reading interface:

| Column | Contents |
| --- | --- |
| `source` | Full text, span ID, text SHA-256, legal ID, source revision and Constitution flag |
| `autoencoder` | Model identity, actual raw/projected vectors and metrics, formal candidate outputs, source binding, candidate completeness, and the exact learned-capture artifact reference when present |
| `compiler` | Direct formal candidates, canonical typed rules, canonical status/reason, decompiled text, component evidence |
| `comparison` | Status, raw AST equality, validated canonical-core equality, comparison scope, independence, emitted-formula coverage, counts and differing positions |
| `provenance` | Code/model identities, batch/agent identity, timing and bridge configuration |
| `lake` | `not_run` with no receipt or admission in this campaign |
| `goal_ids` | References to deferred goals |
| `source_target_artifact_sha256` | Reference to the original source-derived target evidence |
| `observation_id` | Hash of the complete observation before goal backreferences |

The `formal_outputs` lists contain a family, representation format, exact
native payload in `payload_json`, payload hash, producer origin, conditioning,
independence and syntax status. JSON is confined to variable formal ASTs; the
source, metrics, comparison and provenance have typed Arrow fields.

When the guided route is enabled:

- `autoencoder.formal_outputs` contains the guided compiler candidates.
- `compiler.formal_outputs` contains the same codec's unguided modal candidates.
- `compiler.canonical_formal_outputs` contains all actual typed deontic rules.
- `compiler.complete` concerns the captured direct candidate collection.
- `compiler.canonical_complete` separately records canonical compilation.

`compiler.status` and `compiler.reason` describe the canonical compiler.
They must not be interpreted as the status of the separate modal candidates.
`complete` means the recorded producer emitted its complete formula
collection. It is not a claim that every meaning in the legal text was
captured; `comparison.coverage_scope` makes that limit explicit.

## Comparison semantics

| Status | Meaning |
| --- | --- |
| `diagnostic_agree` | The direct and guided raw formal AST sequences match exactly |
| `diagnostic_disagree` | Comparable direct and guided raw AST sequences differ |
| `agree` / `disagree` | Reserved for a source-bound independent symbolic decoder with syntax evidence |
| `autoencoder_unavailable` | Only the direct/canonical side emitted formal output |
| `compiler_unavailable` | Only the model-side path emitted formal output |
| `both_unavailable` | Neither path emitted formal output |
| `partial` | One captured formula collection is incomplete or unbound |
| `incomparable` | Representations or required independence/binding evidence differ |

Guided comparison always has `independent=false`. Native modal dataclasses
currently provide serialization without a separate syntax validator, so
their records retain `syntax_status=not_checked`. A diagnostic match does not
assert syntax qualification, semantic equivalence or independent agreement.

`agrees` and `raw_agrees` retain the original exact AST comparison: object key
order is irrelevant; list order, duplicate components and every payload field
remain significant. `canonical_core_agrees` adds a separate, restricted view.
It may omit only the compiler's exact three-key `temporal_records` sidecar when
kind, integer quantity and unit are already redundantly encoded in the
unchanged canonical rule. For example, `within 20 days` may have a sidecar
with `temporal_kind=within_duration`, `quantity=20`, and `value="20 days"`.
A minimum-duration record is redundant only when `at least 20 days` occurs
in the temporal atom, or the same duration atom is paired with the exact
object suffix `for at least 20 days`. Unknown fields, dates, anchors, mismatched
quantities or order, and unrecognized record forms are never discarded.

`difference_kind=validated_temporal_metadata_only` leaves raw disagreement
visible but does not create a semantic repair packet. Actor, modality,
conditions, exceptions, temporal atoms and unknown fields remain compared
exactly. `canonical_core_agrees` means equality of this restricted
representation, **not semantic equivalence or qualification**. A lost
`unless emergency` remains a disagreement and creates deferred review work.

For the learned legal path only, comparison recognizes the runtime's
`family=deontic`, `format=typed-deontic-rule/v1` as the canonical compiler's
`typed_deontic` representation. The native family, origin and full AST remain
unchanged in retained outputs and the original capture.

Unavailable and incomparable records have `agrees=null`. Source bridge targets
never substitute for a model-generated formula. Family distributions and
reconstruction metrics remain observations under their own fields.

A source-bound guided capture can legitimately emit no native formulas. Its
autoencoder status is `guided_no_formulas`; it does not create a missing-decoder
capability goal. If the direct route emitted formulas for that span, the gap
creates a source-bound repair packet while the comparison remains unavailable.
An incomplete or unbound guided capture is `guided_unavailable`. Historical
vector-only observations with no guided route retain their separate decoder
capability gap.

## Capture the independent learned legal decoder

The `source_conditioned_formula_v1` lineage has an actual source-only decoder.
Use its installed runtime adapter rather than relabeling compiler outputs:

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_runtime_registry import open_runtime
from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
from ipfs_datasets_py.logic.autoformal.paired_span_census import (
    capture_learned_formula_observations, build_paired_census,
    write_paired_census_bundle,
)

runtime = open_runtime("legal_ir", "source_conditioned_formula_v1",
    checkpoint="local/checkpoint.json", expected_sha256=checkpoint_sha256)
sources = [{"source_span_id": "span-1", "text": "The agency shall not disclose records."}]
captures = capture_learned_formula_observations(runtime, sources)
session = AutoformalSession()
observations = [{**source,
    "compiler_result": compile_span(session, source["text"], source["source_span_id"]),
    "learned_formula_observation": capture}
    for source, capture in zip(sources, captures)]
bundle = build_paired_census(observations, model_identity=captures[0]["model_identity"],
    code_identity=producer_code_identity)
written = write_paired_census_bundle(bundle, "outbox/learned")
```

The capture accepts exactly source IDs and text, invokes the cached installed
runtime, and records its checkpoint hash and limited runtime-file hashes.
Each bounded observation retains the exact single-source inference receipt:
native AST, canonical IR, display-only formula, generation token IDs, source
hash, syntax scope, abstention reason and explicit no-target/no-training flags.
No compiler target is passed to inference. Source compilation runs separately.
The capture performs no training, download, upload, schema Lake build or
admission, and never creates missing vector metrics. Load a DuckDB version
through `load_version` when the checkpoint is registered; the capture API
accepts the same resulting `LearnedFormulaRuntime`.

The original receipt lives in an artifact with kind
`learned_formula_observation`. `autoencoder.learned_formula_capture_verified`
records successful contract/binding validation, with its artifact pointer in
`autoencoder.learned_formula_observation_artifact_sha256`. It does not mean
that the formula is legally correct, that a remote producer was authenticated,
or that every dependency was captured. Self-addressed hashes detect corrupt
or inconsistent records; they are not signed execution attestations. Historical
imports validate retained hashes without demanding today's runtime-file hashes.

Successful generation has status `learned_decoded`; a real decoder abstention
has status `learned_abstained`, not a fictitious missing-decoder capability.
Neither generation nor comparison grants qualification. Syntax evidence here
covers only the canonical seven-field rule schema and decoder grammar; it
does not assert the full logic-family floor. In particular, a schema-correct
formula can still drop an exception, as the retained 11/12 legal E2E sample
demonstrates. Lake and family semantic gates stay separate.

Use one cached runtime per model-owning worker and bound `sources` to at most
128 rows. Captures invoke each source individually so a batch receipt is not
duplicated into every exported row. This adapter does not change the running
legacy campaign or introduce native-decoder fleet/weight synchronization.

## Query the census

For a local mirror of the published tables, DuckDB can query nested fields
without unpacking large artifacts:

```sql
SELECT comparison.status, count(*) AS observations
FROM read_parquet('autoformal/uscode/paired-v2/paired_spans/**/*.parquet')
GROUP BY comparison.status
ORDER BY observations DESC;

SELECT source.span_id, source.text, compiler.status, compiler.reason,
       compiler.canonical_complete, comparison.status, goal_ids
FROM read_parquet('autoformal/uscode/paired-v2/paired_spans/**/*.parquet')
WHERE NOT compiler.canonical_complete
LIMIT 20;

SELECT source.span_id,
       autoencoder.formal_outputs AS guided_outputs,
       compiler.formal_outputs AS direct_outputs,
       compiler.canonical_formal_outputs AS typed_rules
FROM read_parquet('autoformal/uscode/paired-v2/paired_spans/**/*.parquet')
WHERE comparison.status = 'diagnostic_disagree'
LIMIT 5;
```

Inspect counts separately: processed observations, emitted formal candidates,
canonical successful/partial/abstained spans, comparison statuses, deferred
goals and Lake admissions are different measures.

## Evidence artifacts and supervisor goals

The artifact table has `artifact_sha256`, `kind`, `encoding`,
`decoded_bytes`, and a compressed binary `payload`. Its `zlib-json/v1`
encoding is bounded and verified before use. The complete original producer
receipt is archived once per batch. Source bridge documents and compiler
components refer to their paths inside that receipt; they are not copied into
every paired row or goal. Queryable vectors and formal candidates are exposed
directly so routine census work does not decompress the receipt.

The goals table exposes `goal_id`, `record_kind`, `issue`, `work_kind`,
`status`, source and observation IDs, producer identities, and exact
packet/task hashes. Native portable packet and task JSON live in separate
artifact records; goal rows refer to those records by hash.

Actual compiler failures generate the existing sealed repair packets.
Formal discrepancies generate review work with both outputs and the
comparison scope retained. A guided disagreement does not declare the
compiler wrong or adopt the guided result as truth. Existing edit scopes,
regression tests, acceptance conditions and Lake requirements are preserved.

If a checkpoint lacks symbolic output, capability work is deduplicated by
model identity and decoder contract. A capability goal can appear in several
batches with the same `goal_id`; combine its observation references rather
than opening a new identical task for each span. Descriptive capability/review
rows are not executable native tasks. All export rows remain deferred and
`enqueued=false`.

Read a verified local bundle from the canonical checkout:

```python
import json
from ipfs_datasets_py.logic.autoformal.paired_span_census import (
    decode_artifact,
    load_paired_census_bundle,
)

bundle = load_paired_census_bundle('outbox/manifest-<fingerprint>.json')
rows = bundle['paired_spans']
portable_rows = bundle['portable_goal_rows']
original_receipt = bundle['original_receipt']

for artifact in bundle['artifacts']:
    if artifact['kind'] == 'supervisor_packet':
        packet = json.loads(decode_artifact(artifact))
        print(packet['row']['source_span_id'], packet['row']['reason'])
```

Within a captured `guided_compiler_observation`, `direct_document` is the
same codec's unguided result, `document` is its guided result, and
`source_parser_document` is the earlier sample parser result. Each has its
own recorded hash and byte count. The baseline marker is
`comparison_baseline=same_codec_without_guidance`.

`original_receipt` may itself contain legacy packed bridge documents using
`recursive-zlib-json/v1`. Use the existing
`legacy_span_logic_artifacts.unpack_document` helper if the full nested bridge
document is needed; these two compression layers have different contracts.

The loader validates hashes, typed schemas, bounded decompression, source
closure, reciprocal goal references, packet/task identities, approved native
scope and the exact source/model/code binding. It supports both four files
placed together and a downloaded repository directory layout.

Plan a later supervisor import with the existing command:

```bash
PYTHONPATH="$PWD" python scripts/ops/legal_ir/import_span_cache_exchange.py \
  --manifest path/to/manifest-<fingerprint>.json \
  --output workspace/test-logs/paired-import-plan
```

The default validates and plans. Explicit `--materialize` additionally needs
the intended supervisor database and accelerate root; it creates review-only
work using the existing native adapter. Dataset export never starts that work.
Remote planning accepts `--manifest-in-repo` and a pinned `--revision`.

## Running and measuring

`scripts/ops/legal_ir/run_legacy_span_cuda.py` defaults to paired publication.
`--guided-compiler` enables the measured guided conversion. `--upload` enables
Hub publication; `--max-batches 0` has no overall campaign batch limit. Use the
existing managed campaign service and resource ledger instead of launching
another copy against its live DuckDB.

One process owns the immutable CUDA model. A bounded CPU compiler pool and a
limited prefetched batch overlap source compilation with model work. The
capacity planner uses available CPU/RAM, process limits and current process
usage to choose safe work. A separate CUDA memory guard checks the model
owner's device budget. Worker count and batch size remain capped; model
weights are not copied into every CPU worker. The queue has one DuckDB writer.

Publication commits the manifest and its three tables atomically with a Hub
parent-commit check. The campaign verifies exact remote hashes and complete
original-receipt retention before removing local evidence. A failed upload or
verification retains the local outbox for retry and resume. Existing old
staged exchanges can finish publication through their historical path.

Report measured wall time per span and per bridge-on evaluation together with
sample count, all bridge names, prover flag, cache flag and worker count.
Include guided conversion time, actual CUDA execution, parent/group RSS and
publication backlog when assessing capacity. Do not describe a zero-target
evaluation as a faster legal-IR run. Do not sum overlapping batch residence
times to estimate campaign throughput; use completed-span counter differences
over wall time.

## Reusing these observations for a new architecture

The paired tables and archived full reports retain the source text/hash,
candidate formulas, canonical compiler failures, guidance, raw decoder
metrics, model checkpoint identity, producer-source hash and bridge settings.
A new trainer can derive examples from these records without rerunning the
legacy model. The original receipt retains details that do not belong in
the primary typed table, including model configuration and per-sample bridge
measurements.

The current labels are diagnostic teacher candidates. Before training or
comparing a new architecture:

1. Pin the dataset commit and retain each manifest and its verified closure.
   Keep checkpoint identity, code identity, source revision and candidate
   origin with every derived training row.
2. Derive train/validation/test assignments by legal document and source
   lineage, keeping repeated spans and their candidate versions together.
   The export currently does not assign these splits. A storage split named
   `train` is not a held-out qualification claim.
3. Generate the new architecture's verified semantic embeddings under an
   explicit encoder/version contract. Legacy mock vectors are not semantic
   inputs or benchmarks for a different embedding dimension.
4. Keep direct, guided, source-derived target and canonical rule outputs as
   separate teachers. Preserve `target_conditioned` so a target-assisted
   candidate cannot be scored as independent generalization against that
   same target.
5. Treat partial, unavailable and syntax-unchecked records explicitly.
   Do not silently turn abstentions into negative legal statements, replace
   missing outputs with source text, or label a guided disagreement as proof
   that one producer is wrong.
6. Measure the new family-specific syntax checks, text round trips and
   held-out reconstruction quality separately. Obtain new source-bound Lake
   receipts for admissions; these diagnostic exports contain none.

The receipt records a hash of the producer source tree. For executable
reproduction, also retain the corresponding immutable Git commit or source
snapshot in the campaign's release provenance; a tree-content hash alone is
not a checkout command. Preserve access to the exact existing checkpoint
artifact by its hash when replaying the legacy producer. Reading this dataset
does not download that checkpoint or require it to interpret emitted labels.

## Entry points and tests

- Schema, comparator, native goal adapter and bounded writer/loader:
  `ipfs_datasets_py/logic/autoformal/paired_span_census.py`.
- Actual source-only learned runtime capture and offline retained-evidence validation:
  `ipfs_datasets_py/logic/autoformal/learned_formula_observation.py`.
- Guided compiler observations:
  `ipfs_datasets_py/optimizers/logic_theorem_optimizer/legacy_span_guided_compiler.py`.
- Capacity planning:
  `ipfs_datasets_py/optimizers/logic_theorem_optimizer/legacy_span_capacity.py`.
- Publication and verified receipt preservation:
  `ipfs_datasets_py/optimizers/logic_theorem_optimizer/paired_span_publication.py`.
- Managed runner: `scripts/ops/legal_ir/run_legacy_span_cuda.py`.
- Later import: `scripts/ops/legal_ir/import_span_cache_exchange.py`.
- Comparator, source binding, goal compatibility and artifact retention tests:
  `tests/unit/logic/test_paired_span_census.py`.

Always prepend this canonical repository to `PYTHONPATH`. A bare import can
otherwise resolve to the HACC editable install and use a different parser.
The workspace tree guard remains mandatory. No model download, Mathlib import,
context increase or temperature change is part of this workflow.
