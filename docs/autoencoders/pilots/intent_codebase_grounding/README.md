# First intent and codebase grounding pilot

Implement one bounded registration, capture, conditional-check and read-only
Intent grounding loop before scheduling an edit or training a decoder. The
pilot uses exact authored integer-offset source and reuses the existing owner
types. It exercises current versus desired behavior without presenting authored
expectations as checked evidence.

The [pilot specification](pilot_spec.json), its [closed schema](pilot_spec.schema.json)
and the [adapter contracts](adapter_contracts.json) make the next implementation
steps concrete. They extend the [repository pipeline plan](../../codebase_ir_repository_pipeline_improvement_plan.md)
and [work items](../../codebase_ir_proof_index_work_items.json). The
[inspection](../../../../../../artifacts/codebase-ir-grounding-pilot-contracts-20261002/inspection.json)
records the exact owner implementations and inherited model observations.
These files define planned acceptance cases; no repository scan, solver run,
model execution, training or operational admission has been performed.

The [B00/B01 integration and capture handoff](capture_handoff.md) now specifies
the exact native API sequence, capability-specific release gates, strict H0
source-policy boundaries, operation recovery and remaining resource gaps. Its
[contract](capture_handoff.json) preserves null runtime bindings and adds
eighteen capture/recovery cases before the later full pilot.

The [capability release sequence and executable preflight](release_sequence.md)
now binds the implementation/dependency seeds, all twelve cell inventories and
the original model/vector assets. Its saved receipt check reports backend pin
drift explicitly; matching inventory bytes do not establish runtime readiness.

## Exact source and reference contracts

Use an isolated fixture repository when the pilot runs. Register a distinct
repository/source-mode identity, enforce the selected clean-source policy and
capture the entire nonexcluded inventory. Do not point this fixture at a dirty
development checkout or substitute a selected file list for the scan population.

Both source variants contain one function, use four-space indentation, ASCII/LF
encoding and a final newline:

```python
def increment(x: int) -> int:
    return x + 1
```

The successor changes only the return literal to `2`. Each buffer is 47 bytes.
Their raw source CIDs and diagnostic SHA256 values are computed over those
authored bytes in the specification. They are source identities, not repository
snapshot, semantic-version or proof identities. H0 and H1 name future owner
observations; their actual heads and evidence are deliberately absent.

Reuse `IntegerOffsetContract("counter.py", "increment", "x", offset)` with
offsets `1` and `2`. Its three normative assumptions come from the pinned
integer-offset profile. Exact built-in integer inputs and direct sequential
invocation are declared assumptions; annotations alone do not enforce them.
The modeled arithmetic excludes resource/interruption failures. Broader Python
behavior stays outside this pilot.

## Owner types and adapter responsibilities

| Handoff | Reuse | Proposed adapter work |
| --- | --- | --- |
| Capture and live applicability | `CodebaseHead`, publication receipt, `RepositoryCodebaseIndex.observe_current` | Exact head/source-mode/ignore bindings; reobserve after retry and before consumption |
| Conditional proof history | `IntegerOffsetContract`, native compilation/check receipt, `CanonicalProofCacheKey`, `CodebaseEvidenceRecord` | Keep conditional authority and historical/current distinction; route nonterminal attempts separately |
| Transition proposal | `ProgramTransitionQuery`, `ProgramTransitionCandidate`, `RepairOperator` or `PatchSketchIR` | Bind a bounded current query and allowed proposal universe; no new native return-edit operator |
| Transition observation | `ProgramTransitionObservation` | Keep the query's H0 subject; bind H1 through `observed_cid` and a measured planned-to-actual mapping |
| Grounding and symbolic alternatives | `TypedPredicate`, `ObservedFact`, `ProducerRule`, `TaskCandidate` | Distinct current/planned-post semantic subjects; real producer/task runner contracts |
| Intent/formalization registration | Existing verified IR artifacts and `IntentConstraintAdapter` | Reviewed typed Codebase/formalization bridge and owner-derived satisfaction references |
| Independent admission | `ProgramTransitionAdmission`, supervisor decision/verification owners | Validate live evidence and policy in the operational owner; CID presence alone cannot authorize effects |
| Model branch | Existing cell/variant/run contracts and authenticated checkpoint receipts | Require compatible parents, task/basis coverage and independent evaluation; keep model availability optional for deterministic checks |

Use the existing `ProgramTransition` schema and CID owner. The repair query
requires `current_graph_cid`; derive it through an admitted graph/source mapping.
No graph root, future tree root, solver verdict or evidence CID is invented in
the planning fixture. The native repair enum has no `replace_literal` or
`rewrite_return` operation. A later edit can use a reviewed bounded CEGIS or
patch-sketch proposal with an actual registered runner.

Predictions can select or parameterize a bounded candidate; they cannot become
observations. A `ProgramTransitionObservation` keeps the original query subject
even when it references measured successor content. A planned-post predicate is
a separate planner semantic subject, then maps to an observed H1 version.
Changing only `predicate_id` is insufficient because the compiler semantic key
uses predicate type, subject and object.

Keep conditional-profile evidence and structural observations distinct from
unrestricted runtime facts. The proposed grounding owner must validate scope,
assumptions and authority before constructing a current `ObservedFact`; this
pack provides no automatic authoritative-fact or supervisor-proof conversion.

`ProgramTransitionAdmission` checks typed bindings and declared evidence; it
does not execute or authenticate a checker/observer. Its mutation, completion
and equivalence flags remain false. Operational authority stays with the
supervisor's independently validated evidence, policy and effect-time checks.

## Expected first pilot sequence

1. Materialize and capture H0 through its owners. Validate current source and
   ignore policy before using the native subject and formalization artifacts.
2. Check both reference offsets. Expected results are conditional `proved` for
   offset1 and `refuted` for offset2, with both fresh native solvers agreeing.
3. Publish eligible terminal receipts to the historical evidence index. Build
   read-only Intent grounding for the desired offset2 claim. Preserve the false
   current claim and a separate planned-post goal.
4. Verify typed roots, source correspondence and authority in the grounding
   owner. Unknown facts produce a separate observation/review request rather
   than an invented true fact or automatic compiler task.
5. Stop at the first milestone with source-bound read-only grounding. A later
   admitted producer may edit and capture H1, run actual checks/tests, map the
   desired subject to H1 and establish the permitted post-state outcome.

Missing models do not block this deterministic milestone. Missing solvers,
unknowns, timeouts, disagreement, unsupported grammar, cancellation and racing
source edits do not yield eligible terminal proof records. The current
`CodebaseEvidenceIndex` accepts only `proved` and `refuted` under its closed
conditional profile. Preserve other outcomes in a proposed attempt journal or
reviewed owner extension; map raised stale/cancellation failures explicitly.

A historical exact lookup can authenticate a saved receipt without running a
solver or observing the checkout. A current use needs fresh applicability and
native checks under the existing profile. A same-head history hit or cold
restart is not a solver-bypass result. Restoring H0 bytes after H1 creates a new
generation and does not revive the old H0 head.

## Inherited model availability for this fixture

The saved source8 parent and child are authentic structural checkpoints with
53 input features and an internal latent width of 8. Their registered cohort
is `train.py`, `tune.py` and `canary.py` with fixed roles. They are not an
admitted decoder for the new `counter.py` fixture or an independent raw-source
teacher. Keep their bytes available as donors and historical diagnostics.

The parent's program tuning coverage already reports one unknown atom. The
child reports one unknown program atom on current training and tuning, with
zero on original-root training replay. Numerical projection omits unknown
atoms. Retain those measurements; this pilot requires reviewed basis/cohort
migration and new coverage qualification before that model branch can train
or claim complete reconstruction. Low feature loss cannot supply the missing
semantic coverage.

Distinguish three different identities: raw source-content SHA256 for exposure,
`DomainTargetEnvelope.source_digest` over its schema/binding/contracts, and
the complete vector/input-profile cache identity. Original-root replay enters
ordinary source8 fitting; intermediate ancestors remain an exposure ledger.
FedAvg diagnostic replay/reset-Adam and source384 ridge fitting keep separate
policies. The single-argument offset fixture does not satisfy source384's narrow
two-operand cohort contract. No existing native Codebase768 head is asserted.

The other IR families and dimension cells retain their original inventories,
databases/repository mappings and assets. This Codebase/Intent pilot does not
relabel a Legal or Security model as its own qualified decoder.

## Acceptance evidence and implementation order

The specification includes positive and negative cases for reference contracts,
state keys, typed roots, live observers, proof-index status admission, replay,
unavailable inputs and model coverage. Every expected result stays separate from
an actual result. A future run resolves the null runtime handles in a new
immutable owner-bound manifest, preserving this authored specification. Its
receipts must pass identity, source, authority and currentness checks before use.

Start with C00/C01 integration and exact capture, then C04/C05 native subjects
and conditional evidence, C07/C17 read-only grounding and typed registration.
Complete the reviewed producer catalog and live observer checks through C10
before an effectful H0-to-H1 repair. C08/C09 corpus and model coverage work runs
separately. Wider models, lake delivery and Hub publication remain independent.

Success requires actual captures, fresh checks, eligible historical records and
a current grounded desired claim with explicit limitations. Authored fixtures,
schema validation and hashes alone establish none of those runtime outcomes.
