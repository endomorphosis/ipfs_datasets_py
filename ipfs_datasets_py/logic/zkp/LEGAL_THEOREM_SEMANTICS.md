# Legal Theorem Semantics (P7)

This document defines a minimal, deterministic meaning for when a “legal theorem holds” in the ZKP module.

It is intentionally narrow: its purpose is to provide an *unambiguous* semantics that can be unit-tested (P7.1) and later compiled to an arithmetic circuit (P7.2).

## Ruleset: `TDFOL_v1` (MVP fragment)

Despite the name, the current `TDFOL_v1` implementation is a conservative **propositional Horn fragment**.

### Syntax

Atoms are identifiers matching:

- `[A-Za-z][A-Za-z0-9_]*`

Axioms are either:

- Fact: `P`
- Implication: `P -> Q`

A theorem is a single atom:

- `Q`

### Semantics (“holds”)

Let `known` be the set of atoms known to be true.

1. Initialize `known` with all fact axioms.
2. Repeatedly apply **modus ponens** until reaching a fixpoint:
   - if `P` is in `known` and there is an axiom `P -> Q`, then add `Q` to `known`.
3. The theorem holds iff the theorem atom is in `known` at fixpoint.

This is deterministic and terminating.

### Example

Axioms:

- `P`
- `P -> Q`

Theorem:

- `Q`

Result:

- `Q` holds (derivable by one step of modus ponens).

## Implementation

Reference implementation:

- `logic/zkp/legal_theorem_semantics.py`

Unit tests:

- `tests/unit_tests/logic/zkp/test_legal_theorem_semantics.py`

## Non-goals (for now)

This does not yet implement:

- Full first-order logic (quantifiers, terms, unification)
- Proof objects / derivation traces
- `CEC_v1` semantics
- Compilation to R1CS (tracked in P7.2)
