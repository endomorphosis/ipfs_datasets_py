# Source-derived finite operational states

The Security source path can derive a finite `StateTransitionIR` from an
unchanged, source-qualified scalar prediction. This closes the manual
return-state/table construction step for the existing typed source fragment.
It reuses the shared source adapter, ProgramIR, operational Lean emitter and
native TLA+ compiler. It does not use an LLM or execute the Python source.

## Inputs and supported semantics

Each row contains exactly `id`, `source_text`, `candidate_ir` and
`input_domains`. The candidate is the original `program_expression` prediction;
a mismatch or missing prediction remains an unsupported row. No AST-derived
replacement is substituted for it.

The existing v2 source contract supports one synchronous function with two
distinct `int`-annotated parameters and one `+`, `-`, `*`, `<`, `<=`, `>`, `>=`,
`==` or `!=` operation on those parameters. The return may be direct or use one
fresh temporary. Calls, branches, loops, globals, external effects and other
syntax remain unsupported. Annotations are assumptions about exact built-in
integers; they do not enforce runtime input types.

Input domains are explicit caller declarations:

```json
{
  "left": {"lower": -1, "upper": 1},
  "right": {"lower": 0, "upper": 1}
}
```

Every parameter needs one nonempty integer interval. Boolean/coerced bounds,
unknown parameters, absolute endpoints above 1,000,000, and Cartesian products
above 64 cases are rejected. The implementation enumerates the complete product;
it never samples to fit the bound.

The derived state contains the input values, an output observation and a
`returned` flag. One initial predicate leaves inputs free within their declared
intervals and initializes only the observation bookkeeping. Each generated
action has an exact input guard and updates the output and flag. Inputs are
preserved. Each action summarizes an entire scalar function call, without
claiming to model internal scheduling or local-command interleavings. Returned
states are terminal in the native action relation.

The ProgramIR evaluator initializes only parameters. It adds a fresh local only
when its assignment executes. The pending output sentinel is never treated as
an initialized source local or result slot. Original source spans, candidate
identity, exact effects, assumptions and models remain in the report.

## Kernel checks and their limits

`source_state_lean.emit_source_state_model` replays the entire derivation and
emits the existing ProgramIR `run` alongside the derived state semantics. Its
theorems check:

- every finite input case's exact return and actual local assignments;
- coverage of the complete declared parameter intervals;
- a valid initial state for every case and terminality of returned states;
- each generated native transition; and
- correspondence of every native or bounded transition with ProgramIR `run`.

The program's unused initial store slots remain universally quantified. There
are no axioms, `sorry`, or execution of the source Python in these checks.
The emitted theorem declarations are obligations until a real Lake build passes.
The build receipt then records `finite_correspondence_kernel_checked=true` only
for checked rows. A rejected row cannot disappear behind a successful subset.

Optional Java/SANY checks parse, type and level-check the exact generated TLA+
module. They do not run TLC. TLA+ specification stuttering is separate from
the nonstuttering native action relation. No liveness, security policy,
unbounded-input theorem, Python runtime equivalence or Intent-goal compliance
is inferred. Source/proof/execution authority and training qualification remain
false.

## API and command line

```python
from ipfs_datasets_py.logic.formalization.autoencoder.source_state_lake import (
    prepare_source_state_lean, build_source_state_lake, verify_source_state_lake,
)

prepared = prepare_source_state_lean(rows)
execution = build_source_state_lake(
    rows, lake_executable="/path/to/native/lake",
    java_executable="/path/to/java17", tla2tools_jar="/path/to/tla2tools.jar",
    output_directory="/fresh/evidence/directory",
)
receipt = verify_source_state_lake(execution, rows)
```

```bash
python scripts/ops/autoencoder/run_distributed_384.py source-state \
  --rows original-predictions-and-domains.json \
  --lake-executable /path/to/native/lake \
  --java-executable /path/to/java17 \
  --tla2tools-jar /path/to/tla2tools.jar \
  --output-dir /fresh/evidence/directory --result receipt.json
```

Omit tool and output-directory options to prepare without executing a checker.
Java and the JAR must be supplied together. Saved JSON is historical evidence;
live verification requires the issued in-process handle and replays the exact
source, candidate, domains, producer code and tool identities.
Producer checks include the imported native owner dependency closure and reject
changed loaded function code as well as changed files. Generated dataclass
methods, Python itself and external libraries remain outside this limited pin.

## Explicit checkpoint compatibility

The optional `source_program_runtime_384_v2.load_source_program_decoder_384_v2`
loader accepts an exact SHA-256-pinned, structured SecurityIR checkpoint. It
permits one known unrelated dependency update:
`ipfs_datasets_py.logic.ui_ux_ir.decoder`, from
`d7be6bff3a1f1464d4783567b90942258ef718bc1c2b7e02938698ed4e619e57` to
`21e8315b0054f7755512212d610d4e3f5f4ac86387f3b27edb9632fa8ca68bc3`.
Every other implementation field must match. Unknown UI revisions, Security
validator drift and numerical runtime drift are rejected.

Only a detached runtime view substitutes that dependency pin. Original artifact
bytes, weights, schemas and split manifests remain unchanged, and the original
runtime still performs its full validation, including leakage checks. The
original strict loader remains unchanged. A checkpoint already matching the
current implementation uses explicit `strict` mode without substitution.

```python
from ipfs_datasets_py.logic.formalization.autoencoder.source_program_runtime_384_v2 import (
    load_source_program_decoder_384_v2, verify_checkpoint_compatibility,
)

decoder = load_source_program_decoder_384_v2(
    checkpoint_path, expected_sha256=checkpoint_sha256,
    decoder="structured", input_view="raw",  # Or "guarded_ast_normalized".
)
metadata = decoder.describe()["checkpoint_compatibility"]
verify_checkpoint_compatibility(metadata, checkpoint_path, checkpoint_sha256)
```

Descriptions and inference results retain the same compatibility receipt,
including distinct original-artifact and runtime-view hashes. The artifact-backed
verifier reloads exact original bytes, rebuilds the view, validates it through
the original runtime, and compares the complete receipt. The separate pure
`validate_checkpoint_compatibility(receipt, expected_sha256)` checks the closed
profile and current pins without claiming artifact access. Neither form grants
proof authority or general checkpoint-migration permission. The v2 supervisor
uses this path only for structured checkpoints; sequence decoding remains strict.

## Supervisor consumption

The optional `ipfs_accelerate_py` source-program advisor consumes this
datasets-owned API after checkpoint inference. Its v2 configuration supplies
`finite_state_domains` keyed by original source IDs. It keeps original source
bytes even when the embedding input uses normalization. Optional state failures
preserve the original inference and allow planning to continue.

Code-state evidence retains code provenance. It is not rebound to the text of
an Intent instruction. Connecting an Intent action to a code function still
requires an explicit cross-source association and a model of the action's
effects; the existing constant-outcome Intent world model cannot represent
arbitrary input-dependent updates.
