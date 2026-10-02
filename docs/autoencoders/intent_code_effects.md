# Explicit Intent-to-code effect contracts

This adapter connects a selected native Intent action to a bounded scalar code
function through an explicit interpretation. It keeps the original instruction,
Intent prediction, code source and Security prediction separate. It does not
rewrite either prediction or infer which function implements an instruction.

The supported code fragment is the same as
[source-derived finite states](source_derived_finite_states.md): two integer
parameters, one arithmetic or comparison operation, and a direct return or one
fresh temporary. Input intervals cover every combination, with at most 64 cases.

## Declaring the interpretation

`intent_code_effects.intent_code_effect_requirements` accepts the original
instruction and Intent candidate, original code and Security candidate, and
explicit parameter intervals. It exposes the native action/statement IDs,
state-variable types, source references and content hashes. These requirements
help a caller build an association; they do not supply a policy or equation.

The association selects one existing native action and binds all of its
preconditions and asserted EFFECT or POSTCONDITION statements. An action without
such effects cannot establish an effect contract. Other actions and statements
remain unselected and visible; this is not whole-instruction verification.

Expressions use the existing typed ProgramIR carrier and renderer. Explicit
symbol bindings map its four typed symbols to the two inputs, output observation
and returned flag. Preconditions refer to the initial state. Postconditions can
use the final state and `old(...)` expressions over the initial state. Integer
arithmetic, comparisons, Boolean operations and conditionals therefore express
input-dependent effects such as `result = old(left) + old(right)`.
`old(result)` denotes the observation model's initial output sentinel (zero or
false). Unused source-program store fields remain universally quantified in the
inherited operational proof.

The carrier retains the exact code SourceRefs. IntentIR uses a different
SourceRef type, so the original Intent references remain separately preserved
with the original document and its evidence bindings. No conversion substitutes
instruction provenance for code provenance. Full instruction, candidate,
document, code, state-model and association hashes bind the interpretation.

## Three checked outcomes

The adapter evaluates every case using typed IR data, without executing Python
source. Every precondition and effect result stays in the report, including
cases where preconditions are false.

* `satisfied`: at least one case enables the action, and every enabled case
  satisfies every declared effect.
* `refuted`: an enabled case violates an effect. The report retains the concrete
  initial state, code result and failed condition.
* `no_enabled_cases`: every precondition is false within the declared bounds.
  This does not count as satisfaction.

The Lean emitter replays the full association and includes the existing native
ProgramIR/state correspondence proofs. It checks the individual expression
evaluations and emits either a universal bounded contract theorem with an
enabled witness, a concrete counterexample and refutation, or a no-enabled-input
theorem. It preserves the actual return and local assignment semantics.

Preparing declarations does not run Lean. A successful Lake build can validate
any of the three outcomes. Consequently `all_candidates_checked` and
`finite_effects_kernel_checked` must not be interpreted as satisfaction. Only
`bounded_effects_satisfied` identifies a checked, nonvacuously satisfied contract.
Failed or unsupported rows remain in the batch denominator.

## API and CLI

Each input row has exactly these fields:

```text
id, intent_source_text, intent_candidate_ir,
code_source_text, code_candidate_ir, input_domains, association
```

```python
from ipfs_datasets_py.logic.formalization.autoencoder.intent_code_effects_lake import (
    prepare_intent_code_effects_lean,
    build_intent_code_effects_lake,
    verify_intent_code_effects_lake,
)

prepared = prepare_intent_code_effects_lean(rows)
execution = build_intent_code_effects_lake(
    rows,
    lake_executable="/path/to/native/lake",
    output_directory="/fresh/evidence/directory",
)
receipt = verify_intent_code_effects_lake(execution, rows)
```

```bash
python scripts/ops/autoencoder/run_distributed_384.py intent-code-effects \
  --rows explicit-contracts.json \
  --lake-executable /path/to/native/lake \
  --output-dir /fresh/evidence/directory --result receipt.json
```

Without Lake selection the CLI only prepares declarations. Verification requires
the original issued in-process handle, exact input replay and unchanged producer
and tool identities. Saved JSON is historical evidence. The limited producer
pin excludes Python, external dependencies and generated methods; binary pins
do not cover complete toolchain libraries.

## Supervisor use and limits

The optional supervisor consumer validates existing learned Intent advice against
the exact instruction and joins Security inference through its original source
bindings. It never substitutes the task title for the instruction, repairs a
candidate, or treats supplied inference metadata as fresh numerical execution.
Its task-context hook consumes newly prepared Security advice and rechecks the
existing source and task revision before returning.

An explicit association remains a caller-authored interpretation. These proofs
do not establish that natural-language meaning is correct, that Python runtime
inputs meet the declared integer assumptions, that a security policy holds, or
that the task is complete. Source, proof, execution and completion authority
remain false. Missing learned effects, unavailable tools or invalid associations
fail open for planning while preserving independently valid original advice.

Multi-action workflow composition, branches, calls and unbounded inputs remain
outside this initial contract. No training, checkpoint promotion or benchmark
performance improvement follows from successful compilation.
