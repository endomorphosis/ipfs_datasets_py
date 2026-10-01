# Native projections for distributed 384d checkpoint predictions

The additive `project` command replays a completed training round's merged
checkpoint on its validation inputs and passes the unchanged predictions to the
shared v7 native family adapters. It leaves the round's numerical recipe,
DuckDB journal, checkpoint, and published defaults unchanged. It supplies only
`id`, `source_text`, and `embedding` to inference; target labels do not enter
inference or replace predictions.

For richer native models, see [explicit typed interpretations and Intent world
bindings](explicit_native_interpretations.md). These supply declared semantics
for the unchanged prediction and are retained separately from learned output.

```bash
python scripts/ops/autoencoder/run_distributed_384.py project \
  --round-dir work/security-round-001 \
  --checkpoint work/security-round-001/checkpoints/CHECKPOINT_SHA.json \
  --output-dir work/security-projections-001 \
  --contexts work/security-contexts.json \
  --require-family program --require-family first_order \
  --lake-executable /absolute/toolchain/bin/lake \
  --result work/security-projections-001-result.json
```

Use a fresh output directory for each invocation. Omit `--contexts` for a
candidate-only report. Omit `--lake-executable` for preparation only; that does
not count as a build. Repeat `--row-id` to select a bounded subset of validation
examples. The result records both selected and total row counts. These are
tuning predictions, not a new held-out test or evidence of improved training.

## Source- and candidate-bound declarations

Some projections require information absent from a narrow decoded candidate:
an explicit CodeUnit polarity, a workflow state interpretation, a UI event
model, or typed referents in a formula. Context adds such declarations without
changing the candidate. Construct each envelope with the shared helper:

```python
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import contracts
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.projection_context_contract import bind_context
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.qualification import CONTEXTS_SCHEMA

# prediction is obtained from Runtime(checkpoint).infer(source_only_rows).
context = bind_context(domain, prediction["candidate_ir"], source_text, inputs)
batch = {
    "schema": CONTEXTS_SCHEMA,
    "plan_id": plan["plan_id"],
    "checkpoint_sha256": checkpoint_file_sha256,
    "rows": [{"id": prediction["id"], "context": context}],
    **contracts.FALSE,
}
contracts.write_json("work/security-contexts.json", batch)
```

The envelope binds domain, exact UTF-8 source bytes, candidate, and context
hashes. The batch also binds checkpoint bytes and plan identity. Stale,
duplicate, foreign-row, and authority-granting declarations are rejected
before native execution. Changing a context requires a new envelope and run.
Source identity is not a certificate that an interpretation matches the source.

Supported `inputs` keys depend on the domain:

| Domain | Explicit context inputs |
| --- | --- |
| Intent | `rich_slot_context` or `projection_context` (exclusive), `guarded_effect_bindings`, `supplemental_inputs`, `formula_inputs` |
| Security | Required `code_unit`, optional `typed_inputs`, `supplemental_inputs`, `formula_inputs` |
| Legal | `supplemental_inputs`, `formula_inputs` |
| UI/UX | `ui_training_row`, `ui_confirmation_inputs`, `supplemental_inputs`, `formula_inputs` |

Supplemental and Security typed inputs are lists of `{kind, document}` with a
closed whitelist of native model kinds. All nested documents are parsed by
their native owners and must carry the same source binding. UI rows must contain
the exact decoded semantic component, including provenance and bindings; an
ID-only match is insufficient. Legal rule qualifiers remain part of the decoded
rule and cannot be replaced by an unrelated modal interpretation.

For scalar Security expressions, the CodeUnit must state `vulnerable` or `fixed`
polarity explicitly and bind the exact code body. The bridge replays the
source/candidate program check and changes only the source reference to the
CodeUnit. The additive native lowering verifies that reversible join and retains
its audit metadata in the generated Lean artifact. It does not strip metadata
to make a build succeed. Without a CodeUnit, only the existing source-program
check can run; broader Security views remain unavailable.

## Logic families and native checks

`formula_inputs` is a list of `{requirement_id, formula}`. The eight native
formula routes are:

| Requirement ID | Family |
| --- | --- |
| `FOL` | `first_order` |
| `DFOL` | `deontic` |
| `TFOL` | `temporal` |
| `TDFOL` | `tdfol` |
| `CEC` | `event_calculus` |
| `DCEC` | `dcec` |
| `frame_logic` | `frame_logic` |
| `propositional` | `propositional` |

These are caller-supplied formulas, not formulas inferred from prose by the
checkpoint. Other adapters consume their native typed models: programs,
contracts, transition systems, TLA+, temporal specifications, heap models,
hyperproperties, authorization policies, and additional cataloged families.
`projections_v2.family_catalog(domain)` exposes the 40-family inventory and
adapter availability. Availability does not establish applicability, a valid
interpretation, or complete semantic coverage.

The [supplemental native Lean routes](native_supplemental_lean.md) document the
closed authorization, concurrency, cryptographic protocol, and refinement
fragments, their explicit blockers, replay checks, and resource limits.

The CLI exposes this inventory with `projection-families --domain security_ir`.
The older `profiles` command retains the frozen numerical training profile's
requirements; its defaults differ from the newer projection command's defaults.

Intent requests retain semantic dependencies. An obligation is never counted
as an asserted fact after native reclassification. Actual workflow temporal
views retain their state projection; purely declarative temporal formulas do
not acquire a fictitious workflow dependency. Requested and auxiliary families
are reported separately. Empty namespaces do not count as coverage. Every
emitted view in a family must lower successfully: a simple additional formula
cannot hide an uninterpreted rule or incomplete state model.

`auxiliary_family_coverage` records each dependency's completeness.
`all_requested_dependencies_supported` combines requested and auxiliary
coverage. `all_requested_native_checks_passed` concerns syntax and types only;
it can be true for an explicitly partial state abstraction whose coverage
remains incomplete. Neither result establishes full source semantics.

Lake executes the emitted Lean module. TLA+ artifacts additionally require the
real SANY parser; provide `--java-executable /path/to/java` and
`--tla2tools-jar /path/to/tla2tools.jar`. Missing or failing required syntax
checks remain blockers even when Lean compiles. A live issued execution handle
is replayed against the exact source, candidate, native report, producer files,
and backend checks. Serialized receipts preserve history, not live authority.

The report distinguishes supported lowerings, actual backend execution, and
complete requested checks. All admission, promotion, proof-authority, full
target-semantics, and source-fidelity flags remain false. Compilation establishes
syntax and types for the declared fragment; it does not prove that the source
program meets the user's intent.

## Training richer targets

Use the [reviewed pair importer](reviewed_384_pair_exports.md) before preparing
a new training round. It binds native targets to reviewed source records,
checks embedding provenance against the parent, and preserves connected leakage
groups. Raw spans, CVE classifications, and weak SkillCenter structural targets
do not substitute for reviewed source-to-native-IR pairs. New structures beyond
the parent's frozen schema require a separate schema/training workflow.

Context-backed adapter coverage and improved learned reconstruction are separate
measurements. Neither context injection nor a successful Lake build changes
the model's training coverage.
