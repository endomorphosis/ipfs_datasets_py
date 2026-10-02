# Bounded scalar operator proposals

[source_scalar_repair.py](../../ipfs_datasets_py/logic/formalization/autoencoder/security/source_scalar_repair.py)
connects an existing live [Intent/code effect refutation](intent_code_effects.md)
to two inert source proposals. It changes only the single arithmetic operator
token to the other members of `+`, `-`, and `*`. It preserves operand order and
every other byte, including supported comments, whitespace and parentheses.

This is a deterministic proposal stage. It does not execute source, write
files, call a model, construct a replacement candidate IR, or establish that
either proposal repairs the contract. Instruction meaning and finite input
domains remain the explicit declarations supplied to the original gate.

## API

```python
from ipfs_datasets_py.logic.formalization.autoencoder.intent_code_effects_lake import (
    build_intent_code_effects_lake,
)
from ipfs_datasets_py.logic.formalization.autoencoder.security.source_scalar_repair import (
    prepare_scalar_operator_repair,
    verify_scalar_operator_repair,
)

# rows is the complete original gate batch: exact instruction, unchanged Intent
# and Security candidates, code source, explicit domains, and associations.
execution = build_intent_code_effects_lake(
    rows, lake_executable="/absolute/path/to/lake", timeout_seconds=60,
)
report = prepare_scalar_operator_repair(execution, rows, row_id=rows[0]["id"])
verify_scalar_operator_repair(report, execution, rows, row_id=rows[0]["id"])
```

The selected row must have a successful live kernel check of a **refutation**,
at least one enabled input, and counterexample case indices. The function
replays the issued handle against the entire unchanged batch, then requalifies
the original source and its unchanged prediction through the existing
[source binding owner](../../ipfs_datasets_py/logic/formalization/autoencoder/security/source_program_binding_384_v2.py).
The supported arithmetic source is one plain function with two explicitly
annotated integer parameters, both used as operands, returning directly or
through one fresh local variable. Existing mathematical-integer assumptions
and source-qualification limits remain in the report.

The `security-source-scalar-operator-repair/v1` result retains:

- `original_row`, its digest, and the original complete batch digest;
- separate instruction, Intent candidate, source, Security candidate, domain,
  association, live receipt and generated Lean digests;
- the original source qualification and checked counterexample indices;
- two `proposals`, each with exact original/proposed source digests,
  `source_text`, `operator_before`, `operator_after`, and byte-bound
  `token_edit` and `expression_edit` records.

`expression_edit` spans the complete binary expression so a consumer can use
the existing ProgramWorld exact-byte operator and independently require its
output to equal `source_text`. Repeated matching text may make that operator
abstain; the proposal is never permission to replace arbitrary occurrences.

## Rejection and acceptance boundaries

Saved receipt JSON, unissued handles, unavailable checking tools, stale rows,
changed sources/candidates/domains/associations, and a missing selected row
raise `ValueError`. Satisfaction and no-enabled-input results also reject:
neither supplies a nonvacuous repair counterexample. An otherwise qualified,
live-refuted comparison returns `status="unsupported"` and an empty proposal
list because this repair grammar covers arithmetic operators only. Unknown
Python constructs and Unicode outside the existing ASCII source profile are
not normalized into the supported fragment.

For arithmetic, `status="proposed"` always retains both alternatives. An
operator-only edit cannot fix reversed subtraction by swapping operands.
`repair_succeeded`, `proposed_repairs_checked`, and authority flags remain
false, even if a separate consumer later checks one of the proposed sources.
The verifier repeats the original live binding and deterministic proposal
derivation; it does not check the new sources or accept an archived handle.

The supervisor's separate `scalar_repair_advisor` invokes the existing
ProgramWorld operator, obtains fresh Security inference for each budgeted
proposal, rebuilds the explicit Intent association, and obtains a new live
Lake result. Source disagreements and exhausted or ambiguous alternatives
remain visible. Native owner admission, allocated-worktree materialization,
public validation, publication and task completion are additional boundaries;
the datasets proposal report grants none of them. No existing checkpoint or
training target is rewritten.

## Validation and remaining scope

The focused [37-test suite](../../tests/unit/logic/formalization/autoencoder/test_security_source_scalar_repair.py)
passed with actual Lake. It covers all three operators in direct and temporary
forms, byte preservation, stale and forged evidence, unavailable tooling,
unsupported sources, comparison abstention, and exact proposal replay. Its
14-row original population and four subsequent proposal checks use explicitly
authored candidates. The later checks distinguish a satisfied subtraction
proposal from the remaining refuted candidates, including both alternatives
for reversed subtraction. These tests do not measure learned reconstruction.

The separate `ipfs_accelerate_py` qualification driver
`benchmarks/agent_supervisor/container_coding/native_scalar_supervision.py`
consumes real Intent384 and Security384 checkpoints and exercises native
daemon validation and publication of one independently authored scalar task.
Its run artifacts, rather than this unit-test count, establish the observed
model and lifecycle outcomes. It is not a Terminal Bench score, general goal
decomposition, a LegalIR/UI/UX constraint integration, or whole-program proof.

The current native proof gate still requires a Git checkout through its
existing workspace pin. The portable Intent numerical loader does not remove
that separate proof-path limitation. No compatibility bypass is introduced by
this proposal API.
