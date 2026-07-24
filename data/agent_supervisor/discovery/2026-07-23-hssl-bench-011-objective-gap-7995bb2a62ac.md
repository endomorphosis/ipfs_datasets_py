# HSSL-BENCH-011 Objective Protocol Receipt

Date: 2026-07-23
Task id: HSSL-BENCH-011
Goal id: HSSL-G010
Goal title: Freeze the benchmark protocol and safety invariants
Objective heap: `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md`
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-23-hssl-bench-011-objective-gap-7995bb2a62ac.md`
Source fingerprint: `7995bb2a62ac54aa28f40ae77f2cf670bbf322b9`
Objective marker: `HSSLEV0103C72`
Todo vector key: `00c235ec289e9418`
Merge key: `e58732b4098ed4b9`
Merge family: `objective/HSSL-G010`
Work scope: `goal_subgoal_multi_evidence_batch`

## Finding Reconciliation

The source scan found no implementation evidence for the preregistration goal.
The planning document described hypotheses, arms, metrics, trust boundaries,
leakage controls, and preliminary gates, but it explicitly left final
thresholds to the protocol goal and provided no versioned executable contract.

Protocol revision 1 now freezes that state before pilot inspection. The stale
`V00` references in the source narrative are resolved to the arm-table's
canonical `A0` baseline. The previously unspecified paired material-regression
floor is fixed at -0.01, the A0-solved regression tolerance at 0.01, and
unexplained A0 regressions at zero. The canonical protocol digest is
`a12067c4239b9628fde065db3fe10e623148c95a55891a642306e0c90dee8fa3`.

## Implementation Evidence

- `benchmarks/logic_pipeline/contracts.py` exposes the literal Python function
  `HSSLEV0103C72`, providing relevant AST evidence rather than a prose-only
  marker.
- Frozen, slotted, standard-library-only records preregister H1-H7 and their
  null; A0-A12 and S1; primary, quality, resource, and routing metrics; exact
  decision thresholds; exclusions; the failure taxonomy; holdout controls; and
  stop conditions.
- Strict parsing rejects unknown schemas, versions, keys, enum values,
  duplicate identifiers, non-finite values, relaxed safety booleans, digest
  tampering, path-like IDs, cache namespace reuse, and post-freeze mutation.
- `RunContract` requires requested and effective arm identity, binds corpus and
  configuration digests, scopes caches by run/protocol/arm/split/cold-or-warm,
  and requires frozen prompts, policy, models, and thresholds plus an audit ID
  before no-tuning holdout access.
- `OutcomeRecord` permits only an accepted native-kernel receipt to set
  `verified`. Invalid-control verification remains recordable as a fatal safety
  incident; model, legacy-router, and solver claims cannot become verified.
- Capability exclusions and infrastructure failures remain explicit
  missingness. Poor answers cannot be excluded, incomplete pairs cannot support
  a quality claim, and infrastructure failures make a gate incomplete instead
  of changing a logical denominator.
- `evaluate_candidate_gate` implements zero invalid-control tolerance, the 95%
  paired interval rule, five-point hard-case gain or one-point-near-best with a
  twenty-percent efficiency reduction, A0 regression limits, and replayable
  kernel-receipt requirements.
- `benchmarks/logic_pipeline/README.md` is the human-readable normative
  preregistration and amendment policy, tied to the same frozen digest.
- `tests/unit/benchmarks/logic_pipeline/test_contracts.py` exercises the
  complete valid protocol and adversarial safety, serialization, cache,
  pairing, holdout, missingness, materiality, and stop boundaries.
- The package initializer publicly exports the evidence symbol and default
  protocol without changing its existing deterministic smoke manifest or
  importing an optional/production component.

No child goal was added. HSSL-G011, HSSL-G012, and HSSL-G020 already provide the
smaller downstream goals for worktree safety, capability inventory, and the
immutable corpus. HSSL-G010's outputs are now complete as one cohesive contract.
The objective heap records the implementation and digest while its status
remains active for supervisor reconciliation. Generated external todo/vector
state was not edited manually, keeping the supervisor-fed backlog aligned.

## Validation

Commands:

```text
python -m pytest tests/unit/benchmarks/logic_pipeline/test_contracts.py -q
python -m pytest tests/unit/benchmarks/logic_pipeline/test_package.py -q
```

Results: passed on 2026-07-24 (`33 passed`; `16 passed`).
