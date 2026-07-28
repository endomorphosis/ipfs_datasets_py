# Plateau Codex Packet Contract (PLAT-020)

**Interface:** `PlateauCodexPacket@1`  
**Schema:** `ipfs-datasets.semantic-roundtrip-plateau-codex-packet.v1`  
**Module:** `benchmarks.semantic_roundtrip.plateau_codex_packet`  
**Evidence:** `PLATEV020PKT`  
**Depends on:** `StructuralAdmission@1`, `CanonicalFieldChange`

## Purpose

The plateau-break program improves the **deterministic** production path
(`typed_deontic → IR → deterministic realizer`) by feeding residual forensics
and offline teachers through structural provers into **Codex packets** that the
agent supervisor can implement.

This contract defines the sealed packet shape that:

1. Binds the locked baseline L1 (digest + IR).
2. References residual catalog facets that motivated the work.
3. Carries teacher proposals (non-authoritative).
4. Embeds structural admission receipts (Hammer/cvc5/Lean).
5. Mints `proof_obligation` IDs from reject/timeout/error.
6. Declares `predicted_files` and `validation_commands` for supervisor gates.
7. Sets `implementable` fail-closed from admission disposition.

Proof pass is **never** end-to-end semantic loss and never grants
`semantic_authority`.

## Doctrine (packet in the loop)

```text
Teachers (offline)
  spaCy diagnostics | AE residuals | Leanstral (± SyMAI) patches
        │
        ▼
Provers (deterministic)
  Hammer / cvc5 / Lean
  accept | reject | timeout/error fail-closed
  proof_obligation IDs for failed constraints
        │
        ▼
PlateauCodexPacket@1
  baseline L1 digest, residual refs, proposals,
  admission receipts, proof obligations,
  predicted files, validation commands, implementable
        │
        ▼
Agent supervisor (PLAT-070 materializer)
  implementable=true  → lease edit task on det. compiler/realizer
  implementable=false → obligation-only notes (no silent merge)
  merge only after structural re-admit + pytest + pilot re-score
```

## Sealed packet fields

| Field | Role |
| --- | --- |
| `packet_id` | Stable packet identity within a board/wave |
| `packet_digest` | SHA-256 of canonical JSON **without** the digest field |
| `baseline_l1` / `baseline_l1_digest` | Locked det. plateau L1 + content digest |
| `baseline_arm_id` | Default: `typed_deontic__no_guidance__no_repair__not_applicable__deterministic` |
| `baseline_e2e` | Sealed plateau mean (≈ `0.088333333`) for reference |
| `residual_refs` | Case×facet residual pointers (`PlateauResidualRef@1`) |
| `proposals` | Teacher proposals (`PlateauTeacherProposal@1`) |
| `admission_receipts` | Structural admission projections (`PlateauAdmissionReceipt@1`) |
| `proof_obligations` / `proof_obligation_ids` | Obligations from non-accept gates |
| `admitted_field_changes` | Authorized ΔL1 as `CanonicalFieldChange` only |
| `predicted_files` | Repo-relative det. compiler/realizer/test/docs paths |
| `validation_commands` | Commands the supervisor must re-run before merge |
| `implementable` | Edit authority boolean (fail-closed) |
| `semantic_authority` | Always `false` on the packet and prover receipts |

### Implementable authority (normative)

| Admission disposition | `implementable` | Supervisor effect |
| --- | :---: | --- |
| `accepted` (with nonempty admitted field changes) | `true` | Materialize edit task; apply predicted files |
| `validator_reject` | `false` | Obligation-only; retain prior L1; no merge of candidate |
| `timeout` | `false` | Fail-closed; same as non-implementable |
| `error` | `false` | Fail-closed; same as non-implementable |
| `not_applicable` | `false` | No candidate; no edit authority |

Attempting to construct a packet with `implementable=true` when no admission is
`accepted` raises `PlateauCodexPacketError`.

### Prover / teacher non-authority

- Every `ProverCheckReceipt` and `PlateauAdmissionReceipt` forces
  `semantic_authority=false`.
- Teacher proposals also force `semantic_authority=false`.
- Structural admission already encodes
  `proof_pass_is_not_end_to_end_loss=true`; packet receipts preserve that.

## Structural constraints (declared)

Inherited from selective repair / structural admission:

- `non_vacuous_candidate`
- `rule_cardinality_preserved`
- `untriggered_projection_preserved`

Failed constraints mint `ProofObligation` rows with stable
`obligation_id` values under `proof_obligation_ids`.

## Predicted files surface

Predicted edit paths must stay inside:

- `benchmarks/semantic_roundtrip/constructors/`
- `benchmarks/semantic_roundtrip/realizers/`
- `benchmarks/semantic_roundtrip/` (narrow contract modules when needed)
- `tests/unit/benchmarks/semantic_roundtrip/`
- `docs/benchmarks/`

Absolute paths, `..` traversal, and unrelated trees are rejected.

Default predicted files for det. compiler work:

```text
benchmarks/semantic_roundtrip/constructors/typed_deontic.py
tests/unit/benchmarks/semantic_roundtrip/
```

## Validation commands

Default commands re-check structural admission and this packet contract:

```bash
PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_structural_admission.py -q
PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py -q
```

Edit waves (PLAT-08x) add pilot re-score commands; the materializer may extend
`validation_commands` but must not drop structural re-admission.

## Supervisor consumption

### Materializer (PLAT-070)

Input: one or more sealed `PlateauCodexPacket@1` dicts (or CIDs of those
payloads).

For each packet:

1. **Verify** `packet_digest` matches recomputed content address.
2. **Branch on `implementable`:**
   - `true` → emit a supervisor task with:
     - title/body referencing `packet_id` + `packet_digest`
     - `predicted_files` as the allowed edit surface
     - `validation_commands` as the validation gate
     - admitted field changes as the intended ΔL1 rationale
     - residual refs + proposal ids as provenance
   - `false` → emit an **obligation-only** note/task:
     - list `proof_obligation_ids`
     - do **not** authorize merge of a candidate L1 or silent production change
3. **Never** treat prover pass alone as promotion evidence.

### Merge gate

The daemon merges only after:

1. Structural admission re-run still accepts the intended repair (or the
   deterministic code change is independently validated).
2. Packet-declared `validation_commands` pass.
3. Pilot re-score does not regress mean e2e above the pre-wave baseline
   (PLAT-090 owns the promotion decision).

### What the supervisor must not do

- Mark reject/timeout/error packets implementable.
- Expand `predicted_files` to optional runtime teachers (spaCy/Leanstral/AE)
  as production constructors.
- Claim semantic authority from Hammer/cvc5/Lean receipts.
- Rewrite the immutable 2026-07-27 replacement promotion report.

## Public API surface

| Symbol | Role |
| --- | --- |
| `PlateauCodexPacket` | Sealed packet record + `to_dict` / `from_dict` / digest |
| `ResidualRef` | Residual catalog pointer |
| `TeacherProposal` | Non-authoritative teacher patch proposal |
| `PlateauAdmissionReceipt` | Serial projection of `StructuralAdmissionResult` |
| `ProverCheckReceipt` | Single tool check; `semantic_authority=false` |
| `ProofObligation` | Obligation minted from non-accept disposition |
| `build_plateau_codex_packet` | Builder from residuals + proposals + admissions |
| `build_packet_from_proposal_admission` | Single-proposal convenience builder |
| `mint_proof_obligations` | Obligation minting helper |
| `baseline_l1_digest` | Stable L1 content digest |
| `disposition_is_implementable` | Disposition → edit authority predicate |

## Example (accepted path)

```python
from benchmarks.semantic_roundtrip.plateau_codex_packet import (
    ResidualRef,
    TeacherProposal,
    build_packet_from_proposal_admission,
)
from benchmarks.semantic_roundtrip.structural_admission import (
    admit_hybrid_repair,
    StructuralAdmissionGate,
)

admission = admit_hybrid_repair(
    prior_l1,
    candidate_l1,
    gate=gate,
    allowed_field_paths=("rules[0].object",),
)
packet = build_packet_from_proposal_admission(
    packet_id="pkt-legal-object-1",
    baseline_l1=prior_l1,
    residual_ref=ResidualRef(
        residual_id="resid-legal-object",
        case_id="legal_doc_1",
        field_paths=("rules[0].object",),
        facet="object",
    ),
    proposal=TeacherProposal(
        proposal_id="prop-leanstral-1",
        teacher="leanstral",
        residual_ref_ids=("resid-legal-object",),
        allowed_field_paths=("rules[0].object",),
        candidate_l1=candidate_l1,
    ),
    admission=admission,
)
assert packet.implementable is True
assert packet.to_dict()["semantic_authority"] is False
```

## Validation

```bash
PYTHONPATH=. python -m pytest \
  tests/unit/benchmarks/semantic_roundtrip/test_plateau_codex_packet.py -q
```

## Related artifacts

- Plan: `docs/benchmarks/semantic_roundtrip_plateau_break_plan.md`
- Objectives: `docs/implementation/plans/semantic_roundtrip_plateau_break.objectives.md`
- Taskboard: `docs/implementation/plans/semantic_roundtrip_plateau_break.taskboard.todo.md`
- Structural admission: `benchmarks/semantic_roundtrip/structural_admission.py`
- Downstream materializer goal: PLAT-G070 / PLAT-070
