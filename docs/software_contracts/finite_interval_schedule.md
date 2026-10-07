# Finite integer interval schedules

The shared operator lives in
`ipfs_datasets_py.logic.software_contracts.finite_interval_schedule`. It compiles
explicit finite scheduling constraints into QF_LIA for resource-admitted Z3,
then checks a proposed assignment independently using an endpoint sweep. It
establishes feasibility of one finite witness. It does not establish optimality,
prose alignment, kernel proof or permission to execute or publish anything.

## Input and output

The source is an exact UTF-8 JSON object with schema
`finite-interval-schedule-input@1`. For example:

```json
{
  "schema": "finite-interval-schedule-input@1",
  "horizon_start": 0,
  "horizon_end": 6,
  "resources": [
    {"id": "worker", "capacity": 1, "availability": [[0, 6]]}
  ],
  "jobs": [
    {"id": "a", "resource": "worker", "duration": 3, "release": 0, "deadline": 6, "demand": 1},
    {"id": "b", "resource": "worker", "duration": 3, "release": 0, "deadline": 6, "demand": 1}
  ]
}
```

A feasible witness is:

```json
{
  "schema": "finite-interval-schedule-witness@1",
  "assignments": [
    {"id": "a", "start": 0, "end": 3},
    {"id": "b", "start": 3, "end": 6}
  ]
}
```

Assignments must contain every job exactly once in input order. Times are
abstract nonnegative integer ticks, with half-open intervals `[start, end)`.
Each job has one resource and must fit wholly inside one explicit availability
window. Touching windows are allowed, but cannot be implicitly merged for a
job that crosses their boundary. Capacity is the sum of active demands, not
merely a pairwise overlap restriction.

Unknown fields, duplicate JSON keys, duplicate identifiers, Boolean or floating
numbers, missing windows and unknown resources are refused. Windows must be
ascending and disjoint. Durations, demands and capacities are positive. Fixed
bounds are 32 jobs, 16 resources, 16 windows per resource, integer magnitude
1,000,000,000, JSON depth five and 262,144 bytes per document. Inconsistent finite
constraints can produce an observed UNSAT result; this is not an independently
checked proof of impossibility.

## API and evidence

```python
from ipfs_datasets_py.logic.software_contracts.finite_interval_schedule import (
    FiniteIntervalScheduleContract, solve_finite_interval_schedule,
    check_finite_interval_schedule, verify_finite_schedule_check,
)

contract = FiniteIntervalScheduleContract()
result = solve_finite_interval_schedule(input_bytes, contract)
if result["status"] == "sat":
    receipt = check_finite_interval_schedule(input_bytes, result["output_bytes"], contract)
    verify_finite_schedule_check(receipt, input_bytes=input_bytes,
                                output_bytes=result["output_bytes"], contract=contract)
```

`compile_finite_interval_schedule` exposes pure compilation. SMT symbols are
generated internally; source identifiers are never interpolated into code.
The admitted transport owns bounded processes and a shared resource reservation.
Its fixed limits include a five-second operation deadline, 256 MiB memory,
65,536 output bytes and one million solver steps. Existing scheduler,
parent-lease and cancellation arguments are supported.

Only independently checked SAT carries output bytes. UNSAT, unknown, timeout,
unavailable, cancelled and error have no candidate. The model parser accepts
exactly the expected nullary integer assignments. The checker does not consult
the solver: it replays identity, duration, release/deadline, availability and
capacity, processing ends before starts at equal ticks.

Receipts bind exact source/output bytes, policy and checker source identities.
They have `evidence_kind=finite_schedule_check`, `kernel_checked=false` and
false execution/publication/completion authority. Verification recomputes the
receipt. Checker provenance names the directly hashed modules; it does not
transitively attest the Python runtime or all dependencies. The consumer must
pin its loaded source and still perform its own admission and publication checks.

UTC conversion, ICS, recurrence, preemption, resource alternatives, priorities,
optimization and automatic interpretation of instructions remain unsupported.
The supervisor consumes this module through its signed reviewed Intent contract;
no autoencoder checkpoint or legal-IR weights are changed by this operator.
