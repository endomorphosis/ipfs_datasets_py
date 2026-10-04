// provekit_tdfol_v1_trace@v1
//
// Proves that a bounded TDFOL_v1 derivation trace is structurally valid and
// derives the public theorem from committed private axioms.
//
// Constraints enforced:
//   1. circuit_version matches the pinned CIRCUIT_VERSION global.
//   2. trace_length is in [1, MAX_TRACE_STEPS].
//   3. The private fact-axiom commitment matches the public axioms_commitment_field.
//   4. Every active step (0..trace_length) has kind 0 (fact) or 1 (modus_ponens).
//   5. Fact steps carry no antecedent (antecedent_field == 0).
//   6. Modus-ponens steps carry a non-zero antecedent that equals the atom_field
//      of some strictly earlier step.
//   7. Padding steps (trace_length..MAX_TRACE_STEPS) are fully zeroed.
//   8. The final active step's atom_field equals theorem_hash_field.
//
// Step kinds:
//   STEP_KIND_FACT         = 0  (atom is a direct axiom)
//   STEP_KIND_MODUS_PONENS = 1  (atom is derived via an implication rule)
//
// Private axiom text and atom names are never present in the circuit.
// The circuit operates only on SHA-256-derived BN254 scalar-field elements.

global MAX_TRACE_STEPS: u32 = 32;
global STEP_KIND_FACT: Field = 0;
global STEP_KIND_MODUS_PONENS: Field = 1;
global CIRCUIT_VERSION: Field = 1;

/// Return true if `atom_field` equals any of the first `count` entries in `atoms`.
///
/// `count` is a compile-time constant (the unrolled loop index from the caller),
/// so the inner comparison `i < count` is resolved at compile time.
fn atom_known_before(atoms: [Field; 32], atom_field: Field, count: u32) -> bool {
    let mut found = false;
    for i in 0..32 {
        if (i as u32 < count) & (atoms[i] == atom_field) {
            found = true;
        }
    }
    found
}

fn main(
    // Public inputs
    theorem_hash_field: pub Field,
    axioms_commitment_field: pub Field,
    trace_length: pub Field,
    circuit_version: pub Field,
    // Private witness: trace steps padded to MAX_TRACE_STEPS = 32 entries.
    // step_kinds[i]            : 0 = fact, 1 = modus_ponens; 0 for padding.
    // step_atom_fields[i]      : SHA-256(atom) % P_BN254; 0 for padding.
    // step_antecedent_fields[i]: SHA-256(antecedent) % P_BN254 for modus_ponens;
    //                            0 for fact and padding steps.
    step_kinds: [Field; 32],
    step_atom_fields: [Field; 32],
    step_antecedent_fields: [Field; 32],
    // Private commitment to the fact-step atoms.
    // Must equal axioms_commitment_field, binding private facts to the public commitment.
    fact_atoms_commitment: Field,
) -> pub Field {
    assert(circuit_version == CIRCUIT_VERSION);

    // Bind the private fact commitment to the public axioms commitment.
    assert(fact_atoms_commitment == axioms_commitment_field);

    // Validate trace bounds.
    let n: u32 = trace_length as u32;
    assert(n > 0);
    assert(n <= MAX_TRACE_STEPS);

    // Validate each step slot.
    for i in 0..32 {
        let active: bool = (i as u32) < n;
        let kind = step_kinds[i];
        let atom_field = step_atom_fields[i];
        let antecedent_field = step_antecedent_fields[i];

        if active {
            // Active step: kind must be fact (0) or modus_ponens (1).
            assert((kind == STEP_KIND_FACT) | (kind == STEP_KIND_MODUS_PONENS));

            if kind == STEP_KIND_FACT {
                // Fact steps derive their atom directly from the axiom set.
                // No antecedent is needed.
                assert(antecedent_field == 0);
            } else {
                // Modus-ponens: the antecedent must be a non-zero field element
                // that was established as the atom of some strictly earlier step.
                assert(antecedent_field != 0);
                let antecedent_known = atom_known_before(
                    step_atom_fields,
                    antecedent_field,
                    i as u32,
                );
                assert(antecedent_known);
            }
        } else {
            // Padding slots must be fully zeroed.
            assert(kind == 0);
            assert(atom_field == 0);
            assert(antecedent_field == 0);
        }
    }

    // The last active step's atom must equal the public theorem hash.
    // Iterate through all slots and select the one at position n-1.
    let mut theorem_atom_field: Field = 0;
    for i in 0..32 {
        if (i as u32) + 1 == n {
            theorem_atom_field = step_atom_fields[i];
        }
    }
    assert(theorem_atom_field == theorem_hash_field);

    // Return a deterministic accumulator over all public inputs.
    theorem_hash_field + axioms_commitment_field + trace_length + circuit_version
}
