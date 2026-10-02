# Explicit Intent action-contract training with the shared 384D reader

This opt-in path learns native IntentIR preconditions and effects from a bounded
language that states them explicitly. It reuses the shared 384-dimensional
structured decoder, cached GTE-small embeddings, and an unchanged inherited
Legal projection. A separately fitted classifier head predicts the native
contract's semantic fields. Original instruction provenance is attached only
after a complete source-agreement check; the raw prediction remains available.

Inference also supports a relocated source package without Git metadata. Its
`portable_source_pins` owner anchors each direct producer to the exact module
path inside the installed datasets package, compares loaded function code with
compiled source bytes on first use, and rejects subsequent file or function
drift. The checker itself is included in the pin population. This replaces the
Intent action runtime's dependency on importing the historical schema-Lake
checker, whose import requires a Git checkout. It does not change that historical
checker, the structured decoder, or any checkpoint bytes. These pins cover the
direct producer functions and source files, not the entire Python environment,
mutable globals, numerical model memory, or program semantics.

The earlier instruction `the agent may delete the report.` states a permission,
not a return-state contract. Its missing effects were not evidence of a decoding
error. The new codec rejects permission-only instructions instead of adding an
unstated effect. Existing paired-text and rich-modal Intent paths remain separate.

## Controlled source and native targets

An accepted instruction is:

```text
the agent must compute result; requires left > 0; ensures result = old(left) + old(right) and returned.
```

The closed language has one explicitly required computation, an explicit
precondition, and two declared effects: the return equation and the returned
observation. Preconditions are `true` or `left > k` / `right > k`, where `k` is a
bounded integer. Equations use `+`, `-`, or `*` over explicit `old(left)` and
`old(right)` references. Operand order and repetition are preserved. Names
`left`, `right`, `result`, and `returned` belong to this fixed profile; an actor
is a bounded lowercase identifier. A final period is required.

Unsupported arithmetic, missing `old(...)`, omitted requirements or effects,
extra clauses, implicit returned flags, and unsupported input names are rejected.
The profile does not infer an execution precondition from a conditional
permission. The existing rich grammar's `if guard, actor may action object`
continues to mean a guarded modal proposition.

[action_contracts.py](../../ipfs_datasets_py/logic/intent_ir/formalize/action_contracts.py)
provides the source and target codec:

```python
from ipfs_datasets_py.logic.intent_ir.formalize import action_contracts

instruction = (
    "the agent must compute result; requires left > 0; "
    "ensures result = old(left) + old(right) and returned."
)
label = action_contracts.source_to_target(instruction)  # training labels only
contract = action_contracts.target_to_contract(label)
normalized_instruction = action_contracts.contract_to_text(contract)
```

`source_to_target` is a label-generation helper. Inference obtains its candidate
from the numerical reader, then uses `audit_candidate_source` to compare that
unchanged prediction against the complete controlled source. A mismatch cannot
be repaired with the parser's answer.

The target is a native envelope `{kind: "document", document: ...}` accepted by
the existing shared validator. It contains one action and four statements:

| Native statement | Predicate | Ordered arguments |
| --- | --- | --- |
| Required goal | `compute` | actor, `result` |
| Asserted precondition | `input_gt` or `input_true` | input name and decimal threshold, or no arguments |
| Asserted equation effect | `return_equation` | `result`, old-input reference, `add`/`sub`/`mul`, old-input reference |
| Asserted returned effect | `returned` | `returned` |

Statement text is a fixed structural label; semantic values live in the typed
predicate and ordered arguments. This avoids requiring the scalar classifier
to predict an unseen combined natural-language sentence as a single class.
The `true` codec path is unit-tested separately; this training run uses only the
fixed `input_gt` target shape.

## Raw prediction and source provenance

Native IntentIR requires a nonempty source hash. The training target therefore
contains an honestly named `urn:intent-action-contract:unbound-source:v1`
reference whose hash identifies a fixed exported placeholder declaration. It
does not claim to hash an instruction. The model is not trained to predict
per-instruction SHA-256 values.

`bind_candidate_source(instruction, raw_candidate)` preserves the raw envelope
and first performs exact controlled-source agreement. On agreement, it creates
a separate bound envelope by replacing only `/document/sources/0` with the
original instruction's hash and span. All action and statement fields remain
byte-equivalent under canonical serialization. Disagreement returns no bound
candidate. Both candidate identities and the binding operation are reported.

`verify_bound_candidate` replays the entire report against the original raw
candidate. `verify_bound_candidate_source` checks an already bound envelope and
returns its reconstructed raw profile for comparison. The latter validates
source/profile agreement; by itself it does not authenticate numerical model
origin.

## Training and composition holdout

Run the additive trainer with a fresh output directory and exact parent hash:

```bash
CUDA_VISIBLE_DEVICES='' python scripts/ops/autoencoder/train_intent_action_contracts_384.py \
  --parent /path/to/original-legal-384-checkpoint.json \
  --parent-sha256 969461ab82a2806e54ad33ba242a1eb62d032fa1b3cfc808b77c66dcc965aa62 \
  --snapshot-path /path/to/pinned-gte-small-snapshot \
  --output /path/to/fresh-intent-contract-run
```

The [trainer](../../scripts/ops/autoencoder/train_intent_action_contracts_384.py)
generates 144 authored compositions from six actors, two operand orders, four
thresholds, and three operators. Seed `42017` fixes the split: **96 training,
24 validation, and 24 test** compositions. The lexical values and grammar are
deliberately shared across partitions. These are unseen combinations of familiar
values, not unseen vocabulary, independently reviewed natural-language labels,
SkillCenter coverage, or a sealed external benchmark.

Training reuses
[structured_source_ridge_path_384.py](../../ipfs_datasets_py/logic/formalization/autoencoder/structured_source_ridge_path_384.py)
and its existing grouped split checks. Only training rows fit the scalar class
schema and head; validation selects among ridge values `0.0001`, `0.001`, `0.01`,
and `0.1`. The checkpoint is written and sealed before test text, labels, or
embeddings are materialized. Test rows cannot fit the weights or select the
ridge value. The report retains every prediction, including invalid outputs and
the two weight/input ablations.

The completed CPU development run produced:

| Test condition | Exact native targets | Native-valid semantic variable-leaf accuracy |
| --- | ---: | ---: |
| Trained classifier and correct embeddings | 24/24 | 100% |
| Zero classifier head | 0/24 | 29.17% |
| Shuffled input embeddings | 0/24 | 34.03% |

All 24 actual predictions also passed the separate complete source-agreement
check. The resulting checkpoint SHA-256 is
`4f3fd17ea2d908fe36c57a444517f3cc0a983cab26f0f67f2e32371e25def3cd`.
The original parent SHA-256 is
`969461ab82a2806e54ad33ba242a1eb62d032fa1b3cfc808b77c66dcc965aa62`;
its artifact and inherited projection remain unchanged.

Observed fit time was **0.2546 seconds**, with **5.5805 seconds** for the complete
training/evaluation script. These are CPU correctness-run timings. They do not
establish a comparative throughput improvement and exclude later supervisor or
Lean checks. The inherited embedding projection is frozen: this experiment
trains a semantic readout, not improved embedding reconstruction.

## Inference and explicit association with code

[intent_action_runtime_384.py](../../ipfs_datasets_py/logic/formalization/autoencoder/intent_action_runtime_384.py)
loads an explicitly selected checkpoint and cached embedding assets:

```python
from ipfs_datasets_py.logic.formalization.autoencoder.intent_action_runtime_384 import (
    prepare_intent_action_inference, verify_intent_action_inference,
)

options = {
    "checkpoint_path": "/path/to/checkpoint.json",
    "expected_sha256": "4f3fd17ea2d908fe36c57a444517f3cc0a983cab26f0f67f2e32371e25def3cd",
    "snapshot_path": "/path/to/pinned-gte-small-snapshot",
}
report = prepare_intent_action_inference(instruction, **options)
checked = verify_intent_action_inference(report, instruction, **options)
```

The verifier repeats numerical inference and source binding. Missing assets,
unsupported sources, invalid predictions, and source disagreements fail open.
Only `source_supported_action_contract` exposes a bound native document.
The report checks direct module files and loaded functions through the existing
owner guard. This excludes transitive dependencies, numerical model memory,
Python and complete toolchain libraries; it is not a full environment capsule.

For a published experimental version, pass its exact reference to
[intent_action_hub_384.py](../../ipfs_datasets_py/logic/formalization/autoencoder/intent_action_hub_384.py):

```python
from ipfs_datasets_py.logic.formalization.autoencoder.intent_action_hub_384 import (
    resolve_intent_action_checkpoint,
)

# reference is the published intent-action-384-hub-reference/v1 JSON, containing
# the repository, full commit revision, versioned path and checkpoint SHA-256.
options = resolve_intent_action_checkpoint(reference, local_files_only=False)
report = prepare_intent_action_inference(instruction, **options)
```

The resolver defaults to `local_files_only=True`; the example explicitly permits
downloading the selected version. It checks both the containing manifest and
checkpoint bytes at the same immutable revision, then returns local numerical
loader options. It changes no default checkpoint or model registry. The same
path and hash can be supplied to the supervisor configuration below.

The [association builder](../../ipfs_datasets_py/logic/formalization/autoencoder/intent_action_association.py)
then requires a caller-supplied mapping between the two Intent roles and the
code's actual parameter names:

```python
from ipfs_datasets_py.logic.formalization.autoencoder.intent_action_association import (
    build_intent_action_association,
)

association = build_intent_action_association(
    instruction, report["binding"]["bound_candidate"],
    code_source, unchanged_security_candidate, explicit_input_domains,
    action_id="action",
    input_parameter_mapping={"left": "capacity", "right": "threshold"},
)
```

The caller supplies `code_source`, the unchanged Security prediction, and finite
integer domains. The builder checks a bijection onto the code's two parameters.
It lowers the explicit contract's predicates into existing typed ProgramIR
expressions; it does not search for an implementation or change a formula to
match code results. `result` and `returned` designate return observations.
The existing [Intent/code effect gate](intent_code_effects.md) preserves all
finite cases and distinguishes satisfaction, checked refutation, and no enabled
cases. A successfully compiled counterexample is not contract satisfaction.

## Supervisor selection and remaining scope

The additive supervisor `intent_384_advisor.prepare_intent_384_advice` accepts an
explicit `supervisor-intent-action-384-config/v1` object:

```json
{
  "schema": "supervisor-intent-action-384-config/v1",
  "checkpoint_path": "/path/to/checkpoint.json",
  "checkpoint_sha256": "4f3fd17ea2d908fe36c57a444517f3cc0a983cab26f0f67f2e32371e25def3cd",
  "embedding_snapshot_path": "/path/to/pinned-gte-small-snapshot"
}
```

It preserves the raw prediction and provenance-bound candidate separately and
independently replays the datasets inference report. The optional effect advisor
recognizes this distinct advice schema. Callers explicitly provide the original
instruction, selected advice, code association and domains; a task title cannot
stand in for that association. The prior paired-text advisor and default model
selection are not replaced.

Final integration test counts and the 24-contract live Lean replay belong in the
completed evidence report. The training summary itself reports `lake_executed`
as false and does not claim a kernel result.

Remaining work includes arbitrary SkillCenter prose, additional contract
constructors, code with branches or loops, and independently evaluated source
semantics. This path does not combine LegalIR or UI/UX constraints, authorize
repairs, prove complete goal/workflow satisfaction, or run a full supervisor
daemon or Terminal Bench evaluation. No default checkpoint promotion is implied.
