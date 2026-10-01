# Source inventory, live training readiness and parallel proof checks

This path joins exact source identities to the existing strict native-projection
trainer and the shared proof-resource scheduler. It separates three questions:

1. Are the required local source artifacts present and intact?
2. Do the original typed inputs have live, matching native validation evidence?
3. Does numerical training improve the selected objective and independent tests?

An available file answers only the first question. A source decoder and an IR
feature reconstruction head also have different training requirements. Nothing
here turns authored fixtures, weak labels, a solver verdict or a stored receipt
into a reviewed source-language target. The Constitution remains unformalized.

For the checked solver capability routes and optional independent decoder-block
optimizer, see [family routing and refinement](family_routing_and_refinement.md).

## Public entry points

| Owner | Entry point | Purpose |
| --- | --- | --- |
| `scripts/ops/autoencoder/audit_source_training_inventory.py` | `--spec PATH --output PATH` | Bounded local artifact inventory; no source content is copied into the report |
| `logic.formalization.autoencoder.training_readiness` | `audit_source_corpus` | Existing four-domain transfer contract, split/quarantine audit and native target-shape diagnostics |
| Same | `prepare_validated_projection_corpus` | Exact source/group/target joins to live projection observations |
| Same | `validate_prepared_projection_corpus` | Replay original inputs and both split gates |
| Same | `train_prepared_projection_corpus` | Invoke the existing optimized strict v5 structural trainer after replay |
| `logic.formalization.autoencoder.parallel_projection_checks` | `run_parallel_projection_checks` | Native Lake jobs and optional Hammer solver diagnostics sharing a host-local scheduler |

These are additive APIs. Existing checkpoint formats, the preserved 8D linguistic
lineage, 384D source decoders, default trainers and qualification policies are
unchanged. This adapter does not connect DuckDB or Hugging Face publication,
dispatch work to other machines, or perform a distributed checkpoint merge.

## Inventory actual source artifacts

The inventory accepts explicit paths; it does not recursively discover files,
follow references inside them or import a model. The spec has a closed schema:

```json
{
  "schema": "source-training-inventory-spec/v1",
  "artifacts": [{
    "artifact_id": "legal-training-rows",
    "domain_id": "legal_ir",
    "path": "/absolute/path/to/training.jsonl",
    "format": "jsonl",
    "declared_role": "rows",
    "declared_source_kind": "real_source",
    "record_fields": ["/source_text", "/embedding", "/reference_target"]
  }]
}
```

For JSON objects, supply `records_pointer` for the desired array, such as
`/training_samples`. An empty pointer selects a top-level array. `opaque` hashes
an artifact without decoding records. Optional `expected_sha256` is checked
against observed bytes. Declared source kind and role remain caller assertions;
field-presence counts do not verify the contents or relationships.

JSONL is scanned incrementally. Ordinary JSON is materialized within explicit
file, byte, node and depth bounds. Defaults limit individual JSON to 32 MiB and
total observed input to 256 MiB. The caller may choose documented bounded CLI
overrides; the effective limits are recorded. Oversized, changed, malformed,
missing or digest-mismatched artifacts remain visible rather than becoming
empty successful datasets. No data is truncated to create a training row.

```bash
python scripts/ops/autoencoder/audit_source_training_inventory.py \
  --spec /absolute/path/to/inventory-spec.json \
  --output /absolute/path/to/new-inventory.json
```

For source-decoder readiness, `audit_source_corpus` uses the existing
`gte_transfer_corpus.ROW_FIELDS` contract: source, document, group, split,
embedding, reference target, target origin, language and evaluation role.
It preserves duplicate/conflicting labels and cross-split quarantine decisions.
Native target-shape checks add useful diagnostics, but no currently accepted
argument supplies authenticated embedding production, reviewed context or the
exact target-to-live-projection evidence join. The report therefore explicitly
grants **zero source-decoder-ready rows**. This is an inventory boundary, not a
replacement training authorization API. Use existing verified source/embedding
owners to supply evidence before adding a future eligibility issuer.

## Prepare native targets and run parallel checks

Prepare each native v7 report using its original typed source inputs. Source
inputs may include explicit interpretation declarations; retaining them does
not establish their truth. Existing context preparation can retain unresolved
slots or provisional values. The new adapter never fills reviews automatically.

```python
from ipfs_datasets_py.logic.formalization.autoencoder.parallel_projection_checks import (
    NativeProjectionJob, PortfolioDiagnosticJob, run_parallel_projection_checks,
)

checked = run_parallel_projection_checks(
    [NativeProjectionJob("legal-0", report, source_inputs,
                         applicability_review=explicit_source_reviews)],
    portfolio_jobs=[PortfolioDiagnosticJob(
        "legal-propositional", "legal-0",
        "legal_ir/native_formula/propositional/v3",
        solver_names=("z3", "cvc5"),
    )],
    max_workers=2,
    lake_executable=installed_lake,
    output_directory=fresh_output_directory,
    java_executable=installed_java,
    tla2tools_jar=installed_tla2tools,
)
observation = checked["jobs"][0]["observation"]
```

The default is the existing `GlobalResourceScheduler` with its conservative
proof-host policy and shared state path. Native checks reserve validation-lane
CPU, memory and child-process capacity. Hammer's `SolverPortfolio` uses the same
scheduler, with a parent envelope and solver child leases. Worker count is
capped by requested parallelism and the resource envelope; live pressure may
delay or reject a lease. A failed job stays in the receipt. Do not create one
private scheduler state per worker, which would defeat shared accounting.

Native worker leases are reservations, **not hard aggregate RSS/thread limits
inside Lake**. Existing native subprocess owners retain their time, output and
workspace limits. Limits apply per native subprocess step, solver attempt and
lease wait; no batch-wide deadline is claimed. Results retain actual scheduling
intervals and resource telemetry, so requested parallelism is not mistaken for
observed concurrency.

The optional diagnostic currently handles explicit **propositional** projections.
It reparses the projection's printed formula, checks the exact native AST and
uses the existing typed Hammer translator. Unsupported fragments fail explicitly.
Z3/CVC5 then run through the real portfolio. For the SMT route, the formula is
asserted: `sat` means satisfiable, not valid or proved. These diagnostics cannot
replace any native projection check, applicability review, capability floor or
actual `lake build <Lib>`. All emitted native projections still go through their
existing owners; this diagnostic does not add solver translations for every
logic family.

## Bind a corpus and fit the structural head

Every row has exactly `id`, `document_id`, `group_id`, `split`, `source_inputs`
and `observation`. Only `train` and `validation` are admitted to this API.
Validation selects updates and is tuning data. Test/canary payloads are excluded.

```python
from ipfs_datasets_py.logic.formalization.autoencoder.training_readiness import (
    prepare_validated_projection_corpus, train_prepared_projection_corpus,
)

corpus = prepare_validated_projection_corpus("legal_ir", rows)
manifest = corpus.to_dict()  # Save this detached audit report alongside results.
trained = train_prepared_projection_corpus(
    corpus, output_dir=fresh_checkpoint_directory,
    epochs=12, patience=12, latent_width=8, minibatch_size=2,
    max_seconds=60,
)
```

The owner binds canonical source bytes, complete native SourceRef, all projection
targets and original report identity. IDs, declared document/group identities,
exact/normalized sources and native source identities cannot cross train/tuning
splits. This conservative check does not discover semantic paraphrases or prove
the caller's group assignments. UI source-text overrides cannot substitute for
the canonical UI input row.

Prepared handles are process-local. Original typed inputs and live validation
objects must remain available and unmodified. A serialized manifest or native
receipt cannot reopen the gate. Both splits retain all existing strict checks;
missing reviews or capability-floor evidence remain blockers. Training replays
the corpus before and after the unchanged prepared numerical implementation.
The result includes its manifest identity. No checkpoint is promoted here.

## End-to-end diagnostic

```bash
PYTHONPATH="$PWD" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python scripts/ops/autoencoder/smoke_training_readiness_parallel.py \
  --output /absolute/path/to/fresh-smoke \
  --lake /path/to/installed/lake \
  --java-executable /path/to/installed/java \
  --tla2tools-jar /path/to/installed/tla2tools.jar \
  --workers 2 --epochs 12
```

The smoke uses three authored sources per domain: two training and one tuning.
Explicit fixture-only scope reviews do not apply to corpus sources. It runs
native checks for all four modality libraries, requires both requested solvers
for each domain's propositional diagnostic, prepares four live corpus handles,
fits four structural heads and checks tuning loss coverage. It records every
epoch's tuning objective and selected epoch. A selected epoch of zero remains a
calibration/initialization result, not a claim that gradient steps improved it.
It also verifies that detached receipts cannot authorize training.

These examples do not establish natural-source fidelity, held-out convergence
or a global minimum. Production work still needs verified per-domain source
supervision, context closure, complete applicable projections and newly sealed
real-source evaluation groups.

## Recorded validation

The frozen export of commit `4f8819460c7d4fcc08cb9e00b070f8c3ad6e905f`
plus these additive files passed **105 tests**. The integrated diagnostic ran
with two effective workers and observed two overlapping native jobs. It passed
**12 actual Lake builds** (`LegalIR`, `IntentIR`, `SecurityIR`, `UIUXIR`),
**198 emitted projection checks**, **nine SANY checks**, and **eight actual
Z3/CVC5 executions**. All SMT verdicts were `sat`; no source theorem was proved.
The parallel checks took **83.536 seconds**; complete preparation, validation,
four sequential structural fits and inference took **175.250 seconds**.
These are workflow wall times, not a controlled speedup or bridge-on evaluation.
The source tree was an explicit frozen export of the canonical workspace tree;
the editable HACC parser was not used.

All four structural fits completed twelve optimizer steps with the existing
training gates. Every selected epoch remained zero: Legal and Intent retained
small decoder-calibration improvements; Security and UI retained initialization.
Later aggregate improvements for some domains still regressed individual
families and were rejected by the unchanged selection rule. This run proves
the integration works, not that all objectives are converging.

The separate artifact inventory read twelve explicit artifacts (50,041,352
bytes) in **0.74 seconds**, peaking at **274,024 KiB RSS**. The large Intent span
JSON exceeded the default node limit; retained attempts precede the successful
explicit two-million-node limit. This is bounded JSON inspection, not a
zero-copy path or per-training-worker memory measurement.

Existing train/tuning rows were also joined to the source-decoder audit:
eight Legal rows, twelve weak public-source Intent pairs, and 480 authored
rows each for Security and UI. Intent/Security/UI native target shapes passed;
Legal's diagnostic supplied no formal labels. All remained unready through
this new audit because it lacks the verified producer/context/live-projection
joins; this does not assert that no supporting evidence exists elsewhere.
No source decoder was trained on those audited rows.

See the [results and retained evidence](../implementation/reports/evidence/training-readiness-parallel-20261001/results.json)
for input hashes, source snapshots, per-family rejection diagnosis, actual
commands, failed inventory attempts, resource telemetry and native receipts.
