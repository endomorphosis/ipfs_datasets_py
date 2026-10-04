# Hybrid Law Reasoner Architecture

This document specifies an executable reasoner architecture for the hybrid law IR.

## Workflow Diagram

```mermaid
flowchart TD
    A[IR KB Loader\nframes, norms, temporal constraints, definitions] --> B[Index Builder\nid maps + role/temporal indexes]
    B --> C[Dual Compilation]
    C --> C1[DCEC / Dynamic Deontic Program]
    C --> C2[Temporal FOL Program]

    Q[Query + Time Context] --> P[Query Planner]
    S[World State / Event Trace] --> P

    P --> T[Temporal Solver]
    T --> TF[Temporal Facts\n(deadline, interval, overdue)]
    TF --> D[DCEC Compliance Solver]
    P --> D

    D --> R[Result Object\ncompliance/violations/conflicts]
    T --> L[Proof Logger]
    D --> L
    L --> G[Proof Graph Store\nproof_id => DAG]

    G --> E[Explain Layer]
    E --> N[IR -> NL Reconstruction\n(generate_cnl + provenance)]
```

## Query Handling Pseudocode

```python
def handle_query(query, time_context):
    q = normalize(query, time_context)
    kb_slice = index.select(q)

    temporal_facts, temporal_proof = temporal_solver.solve(
        program=kb_slice.temporal_fol,
        state=current_state,
        time_context=q.time_context,
    )

    dcec_result, dcec_proof = dcec_solver.evaluate(
        program=kb_slice.dcec,
        state=current_state,
        temporal_facts=temporal_facts,
        goal=q.goal,
    )

    proof = merge_proofs(temporal_proof, dcec_proof)
    proof_id = proof_store.save(proof)

    return {
        "answer": dcec_result.answer,
        "status": dcec_result.status,
        "proof_id": proof_id,
        "support": dcec_result.support,
    }
```

## API Signatures

```python
def check_compliance(query: dict, time_context: dict) -> dict: ...
def find_violations(state: dict, time_range: tuple[str, str]) -> dict: ...
def explain_proof(proof_id: str, format: str = "nl") -> dict: ...
```

## Proof Logging Contract

Each proof step must include:
- `step_id`, `rule_id`, `premises`, `conclusion`
- `ir_refs`: references to norm/frame/temporal IDs
- `provenance`: source path + source_id + optional source span

Proof objects are reconstructable into natural language using the IR -> NL generator (`generate_cnl`).
