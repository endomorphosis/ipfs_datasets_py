# IntentIR logic projections and qualification

IntentIR can be projected into several logic families after an instruction has
been decoded into typed intent. The projectors preserve declared predicates,
modalities, workflow structure, and provenance within explicit supported subsets.
They report missing semantics alongside the generated formulas. Existing
autoencoder checkpoints continue to produce the same IntentIR; these additional
views come from deterministic, datasets-owned adapters and require no retraining.

The learned model and its development limits are documented in
[IntentIR round-trip training](intent_roundtrip_training.md). A learned candidate
still needs review or independent evidence to establish that it captures the
instruction correctly.

## Project a typed document

The main API accepts an `IntentIRDocument` or its native `intent-ir/v1` JSON
mapping. Family selection uses canonical family IDs. TLA+ is the `tla_plus`
profile of `transition_system`, so select `transition_system` to obtain it.

```python
import json
from pathlib import Path

from ipfs_datasets_py.logic.intent_ir.formalize.extended_projections import (
    project_intent_families,
    validate_intent_family_report,
)

document = json.loads(Path("intent-ir.json").read_text())
report = project_intent_families(document)  # All default families.
validate_intent_family_report(report, document)

selected = project_intent_families(
    document,
    requested_families=["dcec", "tdfol", "frame_logic", "higher_order"],
)
Path("selected-projections.json").write_text(json.dumps(selected, indent=2))
```

`project_intent_families(document, *, context=None, requested_families=None)`
performs native parsing, typed validation, and compilation in process. It makes
no provider calls, performs no training, and launches no external prover.
`validate_intent_family_report(report, document)` regenerates the projections,
context binding, and producer hashes and compares the complete report. Re-signing
a modified report does not satisfy this replay check.

The `intent-extended-projections/v1` report contains the original native target
envelope in `native_targets`, additional reports in `projections`, exact
`source_ir_sha256` and `context_sha256` bindings, producer source hashes, and
`report_sha256`. Each `intent-family-projection/v1` entry contains its generated
representation, validation observations, assumptions, and source-node-specific
`unsupported` records.

| Status | Meaning |
| --- | --- |
| `projected` | The adapter generated its declared representation without recorded omissions or failed checks. This status does not establish a theorem. |
| `partial` | A representation was generated, and omitted semantics or failed validation remain explicit. |
| `unsupported` | The adapter could not generate its supported representation from the supplied inputs. |

`all_requested_families_projected` reports only whether every projection entry
has status `projected`. It is separate from syntax-check results and program
correctness. Defaults commonly include partial or unsupported entries because
ordinary instructions do not provide observed events or executable program
semantics.

## Families and supported semantics

The default families are `dcec`, `tdfol`, `event_calculus`, `frame_logic`,
`datalog`, `horn_chc`, `transition_system`, and `higher_order`. A supported
transition-system input produces both a native state view and a TLA+ view.

| Family | Current projection | Automatic validation and limits |
| --- | --- | --- |
| `dcec` | Ground goal/assumption predicates; obligation `O`, permission `P`, prohibition `F`; intention `I` with an unambiguous action/actor binding. Explicit temporal scopes support `always`, `eventually`, and `next`. | Native DCEC parsing, operator checks, AST round trip, and no free variables. Recommendations remain unsupported; each temporal operator retains its outer scope. |
| `tdfol` | Ground goal/assumption predicates and `O`, `P`, `F` modalities. Explicit temporal scopes support `always`, `eventually`, and `next`. | Native TDFOL parsing, operator checks, AST round trip, and no free variables. The supported subset has no intention-agency operator or strict equivalent of recommendation. |
| `event_calculus` | Caller-declared `happens` occurrences and explicitly linked `initiates`/`terminates` effect laws. | Native event-calculus parse/print/parse. Actions and goals alone do not establish event occurrence or fluent truth. |
| `frame_logic` | Reified native declaration records, including modality, grounding, provenance, indexed arguments, and empty containers. | Native F-logic parse/print/parse and exact field readback; shared `ModalIRFrameLogic` triple container. It does not invoke the LegalIR text codec. |
| `datalog` | Positive ground facts describing declaration kinds and fields. Modality is data in those facts. | Native rule parse/print/parse and exact field readback. It emits no permission or execution rules. |
| `horn_chc` | The same declaration facts lowered to empty-body Horn clauses. | Native CHC lowering with exact clauses and no loss receipts. This does not synthesize verification conditions or solve them. |
| `transition_system` / `tla_plus` | Finite abstract program counter over linear workflows, explicit choice/fork/join configurations, or supplied finite data with guards and bounded retries. | Native `StateTransitionIR` validation, complete finite exploration, and TLA compilation. Guarded models expose a deadlock scan. Source-code correspondence and normative compliance remain unverified; SANY/TLC require explicit qualification. |
| `higher_order` | Lean `Prop` definitions with interpretation parameters for atoms and modalities. | Deterministic source generation. A real Lake build requires explicit qualification. Action and workflow semantics remain listed as omissions. |
| `refinement` | An explicitly supplied, source-bound native `RefinementIR` model. | Native owner validation and exact software-verification syntax-bridge round trip. Simulation obligations remain unsolved. This family is selected separately or added when default selection receives refinement evidence. |

DCEC/TDFOL statement projections currently require a nonempty predicate and
between 1 and 32 arguments, with statement kind `goal` or `assumption`.
An asserted **goal** follows the native Intent compiler's convention and becomes
an intended outcome. An asserted assumption remains an atomic declaration.
DCEC intention requires exactly one action whose verb matches the predicate and
whose actor/object references match the ordered statement arguments. A goal is
never converted into an assertion that it has already been achieved.

The following additional family IDs are accepted as explicit requests, but the
aggregate currently returns `unsupported` with their missing model requirements:
`separation_logic`, `hyperproperty`, `epistemic`, `doxastic`, `concurrency`,
`session_process`, and `cryptographic_protocol`. Heap ownership, multiple traces,
knowledge/belief accessibility, interference, protocol participants, and adversary
models are not inferred from the instruction. `refinement` without its typed
context also returns an explicit unsupported result.

## Explicit context

`context` is an inert JSON object with only the namespaces `modal`, `state`, and
`structural`. Unknown fields, malformed rows, and context for an unselected
namespace's families are rejected. Select families using the API's
`requested_families` argument or repeated CLI `--family` options; do not put
`requested_families` inside aggregate context.

All IDs in the examples below must already exist in the native document. Here,
`goal` denotes a statement, `action` an action, and `source` a native `SourceRef`.
Evidence references bind records; the projector does not verify their truth.

### Temporal scope

```json
{
  "modal": {
    "temporal_bindings": [
      {"statement_id": "goal", "operator": "always", "evidence_ref": "source"}
    ]
  }
}
```

The allowed operators are `always`, `eventually`, and `next`, with at most one
binding per statement and 128 bindings total. The temporal operator wraps the
complete modal proposition: `Always(Obligation(p))`. It does not move inside the
obligation. TDFOL uses `◊` for eventuality and `F` for prohibition. DCEC emits
`always(...)`, `eventually(...)`, or `next(...)`; its native parser also accepts
`x(...)`/`X(...)` for next. Next accepts exactly one formula operand. Native AST
checks preserve `Next(Obligation(p))`, `Next(Prohibition(p))`, and
`Next(Intention(agent, p))` as distinct scoped declarations. Time instants,
durations, deadlines, and fairness are not supplied implicitly.

### Events and effects

```json
{
  "modal": {
    "event_occurrences": [
      {"action_id": "action", "time": 4, "evidence_ref": "source"}
    ],
    "effect_bindings": [
      {
        "action_id": "action",
        "statement_id": "updated",
        "kind": "initiates",
        "evidence_ref": "source"
      }
    ]
  }
}
```

Each row uses exactly the shown keys. Occurrence time is an integer from 0 to
1,000,000,000. Effect `kind` is `initiates` or `terminates`. Each list is limited
to 256 distinct rows. An effect binding additionally requires:

- An existing statement such as `updated`, with kind `effect` or `postcondition`,
  modality `asserted`, and a nonempty predicate.
- An explicit link to that statement in the action's `effect_ids`.
- An action without `precondition_ids`; guarded effect semantics require a richer
  model than this adapter supports.

Occurrences become `happens(event, time)` declarations. Effect bindings become
time-independent laws of the form `forall t:Time. initiates(event, fluent, t)` or
`terminates(...)`. The time independence is a caller-supplied premise. The
adapter neither observes an event nor supplies inertia or precondition proofs.

### Abstract workflow state

```json
{
  "state": {
    "abstraction": "abstract_intent_control_flow",
    "max_steps": 64
  }
}
```

Both shown values are defaults. The abstraction name is fixed; `max_steps` is
an integer from 1 to 256. Without the optional `workflow` field, the input must
contain 1–64 actions in one complete acyclic chain, exactly one entry and terminal
action, and only unguarded `NEXT` edges. It must fit the step budget. Branching,
merging, retry, parallelism, conditional edges, disconnected actions, and action
preconditions produce unsupported results in this default mode.

The generated state is an abstract graph position. Advancing it does not mean
that code ran or that a goal was satisfied. The model has an explicit terminal
self-loop and a step-budget self-loop. Qualification checks `TypeOK` and bounded
abstract deadlock freedom; the adapter excludes the native compiler's liveness
property from this qualification configuration.

### Explicit choices and fork/join workflows

The optional `state.workflow` object enables a bounded token model. It binds the
exact native document digest and a known source reference. All shown keys are
required; an unused group list is empty. This example declares an exclusive
choice between two existing `NEXT` edges:

```python
from ipfs_datasets_py.logic.intent_ir.formalize.projection_contracts import source_ir_sha256

context = {
    "state": {
        "max_steps": 16,
        "workflow": {
            "semantics": "finite_single_use_token_flow",
            "source_ir_sha256": source_ir_sha256(document),
            "evidence_ref": "source",
            "choices": [{
                "source_action_id": "choose",
                "edge_ids": ["choose_left", "choose_right"],
                "semantics": "exclusive_nondeterministic",
                "evidence_ref": "source",
            }],
            "fork_joins": [],
        },
    },
}
```

A choice must enumerate every outgoing edge of its source action, with 2–8
unique `NEXT` edges and distinct targets. The model explores one selected branch
per run; it does not establish a condition's truth. Each listed edge must carry
the group's evidence reference in its native `source_ref_ids`.

For parallel branches, use a `fork_joins` entry with exactly these keys:

```json
{
  "fork_action_id": "fork",
  "join_action_id": "join",
  "parallel_edge_ids": ["fork_left", "fork_right"],
  "join_edge_ids": ["left_join", "right_join"],
  "semantics": "all_branches_then_join",
  "evidence_ref": "source"
}
```

The parallel edges must be all outgoing `PARALLEL` edges of the fork. The join
edges must be all incoming `JOIN` edges of the barrier, with matching branch
counts of 2–4. Every edge must carry the group's evidence reference. Branch
interiors must be disjoint linear chains; nested control inside a branch is
unsupported. Completing the fork activates every branch. The join becomes active
only after all declared branch tails complete. Concurrent actions are explored
as interleavings of atomic action labels, without shared-memory or fairness
semantics. This does not implement the separate `concurrency` logic family.

The complete graph must be acyclic, with one entry and one terminal action and
every action on a path between them. Guarded edges, outcome/retry edges, and
action preconditions remain unsupported. Limits are 16 actions, 64 edges, 16
choice groups, 16 fork/join groups, 128 reachable configurations, and 120
transitions including terminal self-loops. Every reachable execution must fit
`max_steps`. Exceeding a bound rejects the entire state projection; no partial
state exploration is presented as complete.

The generated `pc` now names a complete active/completed token configuration.
The native state payload retains `token_graph`, and the projection retains a
`configuration_map` and source action/edge mappings. Modeling assumptions remain
unverified, and state/TLA reports retain status `partial` because statement
meaning, action effects, and normative compliance are not encoded. SANY/TLC
qualification checks only the explicitly generated finite abstract model.

### Guarded state and bounded retries

Select `context.state.workflow.semantics = "finite_guarded_state_flow"` for
explicit data-dependent control. This is a separate mode from the single-use
fork/join model. It supports `NEXT`, `CONDITIONAL`, and counter-bounded `RETRY`
edges with one current action, one entry, and one terminal action. Outcome-labeled
edges and parallel control remain unsupported in this mode.

The closed workflow object has these fields:

| Field | Required contents |
| --- | --- |
| `semantics` | `finite_guarded_state_flow` |
| `source_ir_sha256`, `evidence_ref` | Exact native IR digest and a known native source reference |
| `variables` | Rows with `variable_id`, `kind`, `domain`, `initial_values`, `evidence_ref` |
| `predicate_bindings` | Rows with `statement_id`, `expression`, `evidence_ref`, covering exactly the guards and preconditions used by the workflow |
| `action_updates` | One row per action with `action_id`, `outcomes`, `evidence_ref`; each outcome contains `values` and `evidence_ref` |
| `retry_bounds` | One row per `RETRY` edge with `edge_id`, `max_traversals`, `evidence_ref` |

Variables use `boolean`, `integer`, or `enumeration` kinds and explicit finite
domains. Initial values must be nonempty subsets of those domains. Types are
strict: Boolean `true` is not integer `1`. Native `StateSchema` and
`StateValuation` checks validate the supplied data; the adapter also enforces
the exact declared domain subsets.

For example, a guard binding can map a native asserted guard statement to a
Boolean comparison:

```json
{
  "statement_id": "ready_guard",
  "expression": {"op": "eq", "variable_id": "ready", "value": true},
  "evidence_ref": "source"
}
```

Expressions are closed objects: `literal` uses a Boolean `value`; `eq` and `ne`
use `variable_id` and an exactly typed domain `value`; `not` uses `arg`; `and`
and `or` use 2–8 `args`. Nesting is bounded. They are interpreted as data,
without evaluating Python, source code, or natural-language predicates. Normative
statements cannot supply state truth. A predicate binding's evidence reference
must belong to its statement; action and retry evidence must belong to the
corresponding action or edge.

Every action needs explicit outcomes, including an identity outcome with
`"values": {}` when no data changes. One outcome is selected nondeterministically.
Constant assignments within it happen simultaneously, and omitted variables
retain their values. Preconditions are evaluated before the update; edge guards
are evaluated afterward. Enabled outgoing edges are exclusive nondeterministic
choices, with no implicit priority.

Retry limits are integers from 1 to 8 and count traversals of each retry edge
across the complete execution. Exhaustion disables that edge. It does not mark
the task complete or choose an exit. A false precondition or lack of enabled
outgoing edges remains an explicit nonterminal deadlock. The finite scan reports
those configurations even though the representation itself is valid.

The model enumerates the Cartesian product of all declared initial values and
every reachable successor. It uses a synthetic initial selection and separate
action/routing phases; all count toward `state.max_steps`. Limits are 16 actions,
64 edges, 6 variables, 8 values per domain, 32 initial valuations, 128
configurations, and 120 transitions. Exceeding a limit or supplying too short a
step budget rejects the whole projection rather than returning a truncated graph.
All non-retry control edges must form an acyclic graph.

The generated TLA+ qualification adds `NoAbstractDeadlock` to `TypeOK` and TLC's
deadlock check. This invariant excludes the enumerated deadlock configurations,
including those reached exactly at the step cutoff. Valid models may pass;
models with reachable deadlocks deliberately return failed checks and retain
counterexample output. The premise-to-code correspondence is still unverified.

The supervisor's bounded summary includes `abstract_state_diagnostics` for this
mode: scan status, deadlock count, initial valuation count, complete exploration,
and `premises_verified: false`. These are properties of the supplied abstract
model, not evidence that code executed or that a goal was achieved.

### Refinement model

The structural context accepts exactly `refinement_evidence`, whose keys are
`source_ir_sha256` and `document`. Compute the digest using the helper below; it
is the bare 64-character digest, without a `sha256:` prefix.

```python
import json
from pathlib import Path

from ipfs_datasets_py.logic.intent_ir.formalize.extended_projections import project_intent_families
from ipfs_datasets_py.logic.intent_ir.formalize.projection_contracts import source_ir_sha256
from ipfs_datasets_py.logic.software_verification.refinement import RefinementIR

document = json.loads(Path("intent-ir.json").read_text())
model = RefinementIR.from_dict(json.loads(Path("refinement-model.json").read_text()))
context = {
    "structural": {
        "refinement_evidence": {
            "source_ir_sha256": source_ir_sha256(document),
            "document": model.to_dict(),
        }
    }
}
report = project_intent_families(
    document, context=context, requested_families=["refinement"]
)
Path("refinement-context.json").write_text(json.dumps(context, indent=2))
```

The native model must contain abstract and concrete systems with valid references.
A complete projection also requires explicit simulation relations, obligations,
and boundedness declarations. Missing declarations remain partial; they are not
filled in. The digest binds this model's association with the exact IntentIR; it
does not establish that the association is semantically correct. The native
bridge's local `simulation` profile is recorded inside the payload, while the
top-level globally registered profile is left unset.

A small authored flag/counter example appears in
[`test_structural_projections.py`](../tests/unit/logic/intent_ir/formalize/test_structural_projections.py),
in `_refinement()`. It includes a forward simulation, explicit state pairs,
a two-step bound, and an undischarged simulation obligation.

## Export and run qualification

Run these commands from the `ipfs_datasets` repository root in an environment
with its Python dependencies installed. Every command needs a fresh output
directory; the CLI refuses to overwrite an existing directory.

Export the default views from an existing typed document:

```bash
PYTHONPATH=. python scripts/validation/qualify_intent_projections.py \
  --intent-ir /absolute/path/to/intent-ir.json \
  --output /absolute/path/to/new-projection-export
```

To select families or use one of the context objects above:

```bash
PYTHONPATH=. python scripts/validation/qualify_intent_projections.py \
  --intent-ir /absolute/path/to/intent-ir.json \
  --context /absolute/path/to/modal-context.json \
  --family dcec --family tdfol --family event_calculus \
  --output /absolute/path/to/new-modal-export
```

For a real Lean syntax/type check, select an already installed Lake executable
and its matching toolchain. This example uses Lean 4.34.1:

```bash
PYTHONPATH=. python scripts/validation/qualify_intent_projections.py \
  --intent-ir /absolute/path/to/intent-ir.json \
  --family higher_order --check-lean \
  --lake-executable "$HOME/.elan/toolchains/leanprover--lean4---v4.34.1/bin/lake" \
  --lean-toolchain leanprover/lean4:v4.34.1 \
  --timeout-seconds 30 \
  --output /absolute/path/to/new-lean-check
```

Lake builds the exact regenerated `IntentProjection.lean` in a bounded temporary
project without external package dependencies or downloads. Its definitions use
uninterpreted modality operators. A successful build establishes syntax/types;
it does not discharge source-intent or program-correctness obligations.

For TLA+, supply a local TLA tools JAR and available Java executable:

```bash
PYTHONPATH=. python scripts/validation/qualify_intent_projections.py \
  --intent-ir /absolute/path/to/intent-ir.json \
  --family transition_system \
  --check-tla --model-check \
  --tla-jar /absolute/path/to/tla2tools.jar \
  --java-executable java --timeout-seconds 30 \
  --output /absolute/path/to/new-tla-check
```

`--check-tla` runs SANY parsing/semantic checks. `--model-check` runs SANY and then
bounded TLC, even without `--check-tla`. Both require `--tla-jar`. Each external
invocation is bounded by `--timeout-seconds`, an integer from 1 to 60, default 30.
No checker is launched by the ordinary projection API. External qualification
regenerates and compares the exact source before executing a tool.

The CLI also accepts an instruction and an explicitly selected existing model:

```bash
PYTHONPATH=. python scripts/validation/qualify_intent_projections.py \
  --instruction-file /absolute/path/to/instruction.txt \
  --checkpoint-descriptor /absolute/path/to/descriptor.json \
  --output /absolute/path/to/new-learned-projection-export
```

`--instruction-file` and `--intent-ir` are mutually exclusive. Typed input does
not accept `--checkpoint-descriptor`. Instruction input is limited to 65,536
bytes and requires the descriptor. If inference yields no usable candidate,
the CLI returns 2 with `no_ir_candidate` and `continue_planning: true`.

Each successful export writes `intent-ir.json`, `projections.json`,
`syntax-checks.json`, and `qualification.json`. Learned input also writes
`inference.json` and a canonical, bounded `projection-request.json`. That request
binds the exact instruction, learned IR, checkpoint, context, and selected
families. Pass the exported request directly to the `ipfs_accelerate_py`
`terminal_deployment build` command using
`--intent-projection-request /absolute/path/to/projection-request.json`, with the
same instruction and checkpoint. Supported Lean and TLA views additionally export their source
files, including the TLA qualification configuration. The qualification summary
lists file sizes/hashes, projection dispositions, and external-check statuses.

Exit code 0 means export completed and any requested external checks passed.
An export without requested external checks may still contain partial or
unsupported projections. Exit code 2 means a requested check did not pass or
no learned candidate was available; invalid arguments also return nonzero.
Requesting a checker while excluding its family produces `family_not_selected`
and exit code 2. Existing output directories and invalid contexts are rejected.
When a requested checker fails or is unavailable after export, the output
directory still contains the projections and its check receipt for inspection.

## Optional preplanning and authority

For default extensions around checkpoint inference, use:

```python
from ipfs_datasets_py.logic.intent_ir.formalize.extended_preplanning import (
    prepare_extended_intent_instruction,
    validate_extended_intent_report,
)

advice = prepare_extended_intent_instruction(instruction, checkpoint_descriptor)
validate_extended_intent_report(
    advice, instruction=instruction, checkpoint_descriptor=checkpoint_descriptor
)
```

The `intent-instruction-extended-roundtrip/v1` envelope retains the original
source-bound inference, its base report hash, and the added projections. A
successful base candidate receives `extension_status` of
`projected_with_explicit_frontiers`. An ordinary optional projector failure
becomes `fail_open_projection_error`; the independently replayable base candidate
and original instruction remain available. Missing or unusable checkpoints
retain the base fail-open behavior.

The wrapper also limits the complete advisory report to 262,144 bytes in the
consumer's ASCII JSON encoding, including its final digest. An oversized optional
extension is omitted with `ProjectionReportBudgetExceeded` in the recorded gap;
the independently replayable base candidate and valid selected request remain.
This does not increase the consumer's report or planner-summary limits. Standalone
projection exports retain their separate, larger bounded contract.

For an explicit modeling context, first obtain the exact learned candidate and
construct an `intent-projection-request/v1` request. The request binds the original
instruction bytes, the candidate IR, and the selected checkpoint manifest digest.
A second inference must reproduce that candidate before the context is used:

```python
from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip import prepare_roundtrip_intent_instruction
from ipfs_datasets_py.logic.intent_ir.formalize.projection_request import make_intent_projection_request

base = prepare_roundtrip_intent_instruction(instruction, checkpoint_descriptor)
if base["status"] != "semantic_candidate_advice":
    raise ValueError("No learned candidate is available for a bound projection request")

request = make_intent_projection_request(
    instruction,
    base["candidate_intent_ir"],
    checkpoint_sha256=base["checkpoint_sha256"],
    requested_families=["dcec", "tdfol"],
    context={"modal": {"temporal_bindings": [
        {"statement_id": "goal", "operator": "next", "evidence_ref": "source"}
    ]}},
)
advice = prepare_extended_intent_instruction(
    instruction, checkpoint_descriptor, projection_request=request
)
validate_extended_intent_report(
    advice, instruction=instruction, checkpoint_descriptor=checkpoint_descriptor
)
```

This produces `intent-instruction-extended-roundtrip/v2` advice when base inference
succeeds. The v2 envelope embeds the selected `projection_request`; default calls
continue producing v1 advice. Requests are closed JSON objects bounded to 65,536
canonical bytes, with `schema`, `instruction_sha256`, `source_ir_sha256`,
`checkpoint_sha256`, `context`, `requested_families`, and `request_sha256` fields.
Use `requested_families=None` for default family selection. Request digests bind
content and do not establish truth or authorization. Complete context validation
occurs in the selected projectors.

An invalid or mismatched request preserves independently valid base advice with
`extension_status: fail_open_projection_error` and no added formulas. A request
is never used to replace the learned document or original instruction. Successful
v2 replay checks the embedded request and regenerates its projections. Persisted
consumers must retain the expected sidecar digest to bind the caller's selection;
self-consistent report replay alone is not authentication of that selection.

The `ipfs_accelerate_py` consumer accepts this inert request through
`prepare_intent_advice(projection_request=request, ...)`. Its file transport uses
`projection_request_path` together with `projection_request_sha256`, the SHA-256
of the exact file bytes. This file digest is distinct from the request's internal
canonical `request_sha256`. Select either the in-memory request or the pinned
file, not both. The consumer's planner summary includes the selected request
digest and projection statuses; this path launches no external provers.

The current development checkpoint decodes one actor/action/object/modality
clause. Its frozen frontend accepts at most 48 whitespace-delimited words and
4,096 characters; longer instructions fail open before numerical inference.
It does not predict guarded workflows, retries, or their data bindings. Such
models currently require typed inputs and explicit premises. Increasing projection
coverage alone does not establish learned performance on full benchmark prompts.

Reports carry `authority: unverified_candidate_only`. Proof, execution,
completion, and omission authority are false, as is `source_semantics_verified`. Numerical
reconstruction, native parsing, Lean compilation, and bounded TLC each provide
their own limited evidence. None establishes that the neural decoder understood
the instruction, that arbitrary code satisfies it, or that SecurityIR, LegalIR,
and UI/UX constraints have been combined into a discharged proof. These views
can inform planning while independent admission and verification remain in force.
