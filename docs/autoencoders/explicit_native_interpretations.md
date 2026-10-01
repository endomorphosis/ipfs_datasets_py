# Explicit interpretations for richer native models

The candidate projection path accepts typed interpretation evidence for
concurrency, refinement, and cryptographic protocol models. It also exposes the
existing guarded Intent world model through a validated binding API and CLI.
The original prediction, source text and native model remain unchanged.

These inputs resolve missing declared-model semantics. They do not infer a
world model from source text or establish correspondence with executable code.
A false interpreted claim can have a valid formal projection and a concrete
counterexample.

## Security interpretations

Add `supplemental_interpretations` to the inputs of a bound projection context:

```python
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.projection_context_contract import bind_context
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.projections_v2 import prepare_candidate_projection

inputs["supplemental_interpretations"] = [
    {"kind": "concurrency", "interpretation": concurrency_interpretation},
    {"kind": "refinement", "interpretation": refinement_interpretation},
    {"kind": "protocol", "interpretation": protocol_interpretation},
]
context = bind_context("security_ir", candidate, source_text, inputs)
prepared = prepare_candidate_projection(
    "security_ir", candidate, source_text, context=context,
    required_families=["concurrency", "refinement", "cryptographic_protocol"],
)
```

Every interpretation contains `native_document_sha256`, the digest of the
unchanged model's canonical JSON, and an emitter-owned closed schema. Use
`distributed_384.contracts.digest` for sorted, compact, UTF-8 canonical JSON.
Each kind is unique and must correspond to an active native projection.
Absent models, unrequested views, wrong domains and different model hashes are
rejected.

The frozen native v7 projector receives its original source-input contract.
The candidate gate separately validates and retains the interpretation, its
digest and the unchanged native report. Preparation, actual Lake execution,
and live-handle verification bind every interpretation. A receipt for one
interpretation cannot verify another, even if both compile. Archived receipts
remain historical evidence. The gate schema is
`distributed-384-candidate-native-lake/v3`.

Missing interpretation evidence preserves the earlier blocker. An additional
supported view cannot hide an unsupported view in the same family.

### Concurrency

The explicit route reuses ProgramIR expression DAGs and its existing typed
renderer for integer/Boolean state. Native variables bind bijectively to typed
symbols. Each step has an explicit guard and simultaneous update, with exact
write-frame coverage and checked reads. Unwritten fields are preserved.

Prose fields require exact statement bindings. Those bindings establish the
identity of the caller's interpretation, not prose equivalence. Native actors,
atomic membership, fairness, interference, rely/guarantee and schedule scopes
are retained. Channels and sessions have separate declared operational models;
the native IR has no field linking them to component steps. Multi-step atomic
regions and unknown semantic attributes remain unsupported.

### Refinement

Symbolic refinement declares typed stores for the original labelled graphs.
State predicate text must parse to exactly the supplied expression DAG; an
unrelated Boolean expression cannot replace `n >= 2`. Each edge needs an
explicit before/after relation because an action label is not an assignment.
Initial witnesses are checked by Lean.

Simulation quantifies over typed stores with explicit schedule/matching bounds.
Trailing silent prefixes consume matching budget. The native convention is
retained: forward simulation is abstract-leading. Leading silent steps, opaque
coupled-data predicates, unknown attributes and unbounded claims remain
unsupported. Simulation and obligation definitions are not asserted true.

### Protocol equivalence

`protocol-static-frame-interpretation/v1` explicitly selects
`static_observation_vectors` for every native equivalence claim ID, retaining
the original left/right vectors. Lean quantifies over all finite typed observer
recipes and compares both evaluation success and equality observations.
Constructor/destructor access follows declared adversary capabilities and the
supported free/symmetric algebra.

A bounded witness search may find a distinguishing observation. Generated Lean
checks that witness and refutes the interpreted static claim. No witness is an
inconclusive result. Conditional knowledge cutpoints, other algebra and
role-process equivalence require additional semantics. Static frames do not
manufacture missing role processes.

## Intent world-state bindings

`world_model_requirements(candidate, source_text)` in
`distributed_384.intent_world_model` returns the exact native document hash,
source references, statements, actions and control edges. Use those IDs with
`bind_intent_world_model(candidate, source_text, world_model)`.

The closed `distributed-384-intent-world-model/v1` model contains
`native_document_sha256`, `evidence_ref`, `variables`, `predicate_bindings`,
`action_updates`, `retry_bounds`, `effect_bindings`, and `max_steps`. Domains,
initial values, guards and every action outcome are explicit. Existing guarded
workflow and effect-checking code validates them. Required goals cannot become
asserted state facts. False effects and deadlocks remain counterexamples.

```bash
python scripts/ops/autoencoder/run_distributed_384.py intent-world \
  --candidate candidate.json --source-text instruction.txt

python scripts/ops/autoencoder/run_distributed_384.py intent-world \
  --candidate candidate.json --source-text instruction.txt \
  --world-model world-model.json --additional-inputs other-inputs.json \
  --result bound-context.json
```

`--additional-inputs` is optional. It preserves other declarations and cannot
overwrite an existing world interpretation. The result is one bound context;
the existing checkpoint `project --contexts` command consumes the
checkpoint/plan/row-bound batch envelope in the
[projection-context workflow](distributed_384_projection_context.md).

## Training and evidence scope

Interpretations are caller declarations, not decoder output or teacher targets.
Historical numerical plans, DuckDB journals, weights and published default pins
remain unchanged. Projection coverage is separate from source-semantic
fidelity, proof authority, admission and promotion. Reviewed source/IR pairs and
a separate reconstruction study are needed to measure learned improvements.
