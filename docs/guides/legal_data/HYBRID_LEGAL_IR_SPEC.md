# Hybrid Legal IR Spec

This document defines a practical hybrid legal knowledge representation system that combines:
- F-logic style typed frames,
- first-order conditions,
- deontic operators (`O`, `P`, `F`),
- temporal constraints,
- DCEC/Event Calculus style dynamics.

## Design Principles

1. Frames are first-class and typed (`action`, `event`, `state`).
2. Deontic operators wrap frame references, not raw predicate argument lists.
3. Temporal constraints are independent objects attached via references.
4. Canonical IDs are deterministic to support composability and dedup.
5. One IR compiles to both DCEC-like formulas and temporal deontic FOL.

## Core Object Model

- `Entity(id, type_name, attrs)`
- `ActionFrame(id, roles, verb, attrs)`
- `EventFrame(id, roles, event_type, attrs)`
- `StateFrame(id, roles, state_type, attrs)`
- `TemporalConstraint(id, expr, relation, ...)`
- `Norm(id, op, target_frame_ref, activation, exceptions, temporal_ref, ...)`
- `Condition` trees (`atom`, `and`, `or`, `not`, `exists`, `forall`)

Implementation file:
- `src/municipal_scrape_workspace/hybrid_legal_ir.py`

## Reference Grammar (near-EBNF)

```ebnf
NormDecl         ::= "Norm(" "id=" ID "," "op=" ("O"|"P"|"F") ","
                     "target=" FrameRef ","
                     "activation=" ConditionExpr ","
                     "exceptions=" ConditionList ","
                     "temporalRef=" TempRef ")"

FrameDecl        ::= ActionFrame | EventFrame | StateFrame
ActionFrame      ::= "ActionFrame(" "id=" ID "," "roles={...}" "," "verb=" ID ")"
EventFrame       ::= "EventFrame("  "id=" ID "," "roles={...}" "," "eventType=" ID ")"
StateFrame       ::= "StateFrame("  "id=" ID "," "roles={...}" "," "stateType=" ID ")"

TemporalDecl     ::= "Temporal(" "id=" ID "," TempExpr "," "relation=" TempRel ")"
TempExpr         ::= "point(t)" | "interval(t1,t2)" | "deadline(duration,anchor)" | "window(duration,anchor)"
```

## Translation Pipeline

1. Parser (`parse_cnl_sentence`):
- Controlled-NL sentence -> `LegalIR` with one norm and one target frame.
- Handles modality cues (`shall/must/may` + negation).
- Handles condition and exception tails (`if`, `when`, `unless`, `except as to`).
- Lifts temporal phrases (`within N days/hours`) into `TemporalConstraint`.

2. Normalizer (`normalize_ir`):
- Canonical role names (`subject -> agent`, `object -> patient`).
- Verb/action lexical normalization.
- Stable IDs and dedup-friendly structure.

3. Compiler A (`compile_to_dcec`):
- Emits EC-style formulas using `HoldsAt(...)` and deontic wrappers over frame refs.

4. Compiler B (`compile_to_temporal_deontic_fol`):
- Emits `forall t` temporal deontic formulas with guarded activation.

5. Back-translation (`generate_cnl`):
- Deterministic CNL output with stable clause ordering.

## Reasoning API Surface (recommended)

- `ingest_ir(ir)` -> validation report
- `add_event(event_ref, t)`
- `add_fact(atom, t)`
- `query_active_norms(entity_ref, t)`
- `query_permitted(entity_ref, frame_ref, t)`
- `check_compliance(trace)`
- `explain(goal)`

## Proof Obligations

- Type soundness: all slot refs resolve and satisfy declared type constraints.
- Modal discipline: `O/P/F` always point to frame refs.
- Temporal consistency: no contradictory temporal guard sets.
- Exception precedence: exceptions defeat activation where defined.
- Conflict analysis: detect `O(phi)` and `F(phi)` simultaneously active without priority.
- Compilation consistency: DCEC and TDFOL outputs preserve IR-level activation semantics.

## Semantic Fidelity Evaluation

Use IR-aware and embedding-aware checks together:

1. Generate canonical CNL from source IR.
2. Compile + decode to CNL.
3. Compute cosine similarity with `ir_semantic_roundtrip_score`.
4. Measure slot retention (agent/patient/verb/modality/temporal/exception).
5. Gate acceptance with both semantic and structural thresholds.

Suggested thresholds:
- cosine >= 0.95
- slot retention >= 0.98
- zero proof-obligation violations

## Minimal Usage Example

```python
from municipal_scrape_workspace.hybrid_legal_ir import (
    parse_cnl_sentence,
    normalize_ir,
    compile_to_dcec,
    compile_to_temporal_deontic_fol,
    generate_cnl,
)

s = "The Congress may at any time by law make or alter such regulations, except as to the places of chusing Senators."
ir = normalize_ir(parse_cnl_sentence(s, jurisdiction="us/federal"))

print("DCEC:")
for f in compile_to_dcec(ir):
    print(" ", f)

print("TDFOL:")
for f in compile_to_temporal_deontic_fol(ir):
    print(" ", f)

norm = next(iter(ir.norms.values()))
print("Roundtrip CNL:", generate_cnl(norm, ir))
```
