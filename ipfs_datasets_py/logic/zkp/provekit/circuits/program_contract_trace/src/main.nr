// provekit_program_contract_trace@v1
//
// Bounded circuit for one finite program-contract check result.
//
// Constraints enforced:
//   1. circuit_version matches the pinned CIRCUIT_VERSION global.
//   2. circuit_id / public-input codec identity match pinned field constants.
//   3. Private commitment openings equal the corresponding public fields.
//   4. Public commitments used as openings are non-zero (no all-zero forgery).
//   5. trace_length equals the fixed canonical supported sequence length (8).
//   6. Active steps follow the declared supported transition table in order.
//   7. Each active step binds the matching public commitment / identity combo.
//   8. Padding slots (trace_length..MAX_TRACE_STEPS) are fully zeroed.
//
// Explicit non-claims (this circuit does NOT prove):
//   - inventory completeness
//   - translator soundness
//   - arbitrary / general function-call runtime semantics
//   - any theorem beyond the committed supported result
//
// This is not a copy of a simulated backend and does not claim general
// function-call semantics. Field encodings are SHA-256-derived BN254 scalars
// for string identities, produced by the companion Python codec.

global MAX_TRACE_STEPS: u32 = 16;
global CANONICAL_TRACE_LENGTH: u32 = 8;
global CIRCUIT_VERSION: Field = 1;

// TraceState codes (must match Python PROGRAM_CONTRACT_TRACE state table).
global STATE_INIT: Field = 0;
global STATE_FOREST_OPENED: Field = 1;
global STATE_INVENTORY_OPENED: Field = 2;
global STATE_CONTRACT_OPENED: Field = 3;
global STATE_CALL_SLICE_OPENED: Field = 4;
global STATE_ASSUMPTIONS_OPENED: Field = 5;
global STATE_VERSIONS_BOUND: Field = 6;
global STATE_RESULT_COMMITTED: Field = 7;
global STATE_TERMINAL: Field = 8;

// TraceTransitionKind codes (must match Python PROGRAM_CONTRACT_TRACE kind table).
global KIND_OPEN_FOREST: Field = 0;
global KIND_OPEN_INVENTORY: Field = 1;
global KIND_OPEN_CONTRACT: Field = 2;
global KIND_OPEN_CALL_SLICE: Field = 3;
global KIND_OPEN_ASSUMPTIONS: Field = 4;
global KIND_BIND_VERSIONS: Field = 5;
global KIND_COMMIT_RESULT: Field = 6;
global KIND_TERMINATE: Field = 7;

// Precomputed field_element_from_text("circuit:program-contract-trace@1").
global EXPECTED_CIRCUIT_ID_FIELD: Field = 16092439212026338347612513713178384059430436650712715735565896058876464335858;
// Precomputed field_element_from_text(
//   "ipfs_accelerate_py/agent-supervisor/program-analysis-zkp-public-input-codec").
global EXPECTED_CODEC_ID_FIELD: Field = 10298298841807217911225314747689038121818549793201105465890600752754809400589;
// Precomputed field_element_from_text("1") for public_input_codec_version.
global EXPECTED_CODEC_VERSION_FIELD: Field = 4858978199531284353617002670780203749743246456737726618240690169569041931081;

fn main(
    // Public commitments (canonical codec order from program-analysis-zkp).
    forest_commitment_field: pub Field,
    inventory_commitment_field: pub Field,
    contract_commitment_field: pub Field,
    call_slice_commitment_field: pub Field,
    assumptions_commitment_field: pub Field,
    analyzer_version_field: pub Field,
    resolver_version_field: pub Field,
    translator_version_field: pub Field,
    prover_version_field: pub Field,
    result_commitment_field: pub Field,
    circuit_id_field: pub Field,
    proving_key_id_field: pub Field,
    verifying_key_id_field: pub Field,
    ceremony_id_field: pub Field,
    public_input_codec_id_field: pub Field,
    public_input_codec_version_field: pub Field,
    // Circuit control publics.
    trace_length: pub Field,
    circuit_version: pub Field,
    // Private openings (must equal the corresponding public fields).
    open_forest_commitment: Field,
    open_inventory_commitment: Field,
    open_contract_commitment: Field,
    open_call_slice_commitment: Field,
    open_assumptions_commitment: Field,
    open_analyzer_version: Field,
    open_resolver_version: Field,
    open_translator_version: Field,
    open_prover_version: Field,
    open_result_commitment: Field,
    open_circuit_id: Field,
    open_proving_key_id: Field,
    open_verifying_key_id: Field,
    open_ceremony_id: Field,
    open_public_input_codec_id: Field,
    open_public_input_codec_version: Field,
    // Private padded step arrays (MAX_TRACE_STEPS = 16).
    step_kinds: [Field; 16],
    step_source_states: [Field; 16],
    step_target_states: [Field; 16],
    step_binding_fields: [Field; 16],
) -> pub Field {
    // Pin circuit version and key/circuit/codec identity.
    assert(circuit_version == CIRCUIT_VERSION);
    assert(circuit_id_field == EXPECTED_CIRCUIT_ID_FIELD);
    assert(public_input_codec_id_field == EXPECTED_CODEC_ID_FIELD);
    assert(public_input_codec_version_field == EXPECTED_CODEC_VERSION_FIELD);

    // Commitment openings: private witness must open every public field.
    assert(open_forest_commitment == forest_commitment_field);
    assert(open_inventory_commitment == inventory_commitment_field);
    assert(open_contract_commitment == contract_commitment_field);
    assert(open_call_slice_commitment == call_slice_commitment_field);
    assert(open_assumptions_commitment == assumptions_commitment_field);
    assert(open_analyzer_version == analyzer_version_field);
    assert(open_resolver_version == resolver_version_field);
    assert(open_translator_version == translator_version_field);
    assert(open_prover_version == prover_version_field);
    assert(open_result_commitment == result_commitment_field);
    assert(open_circuit_id == circuit_id_field);
    assert(open_proving_key_id == proving_key_id_field);
    assert(open_verifying_key_id == verifying_key_id_field);
    assert(open_ceremony_id == ceremony_id_field);
    assert(open_public_input_codec_id == public_input_codec_id_field);
    assert(open_public_input_codec_version == public_input_codec_version_field);

    // Reject zeroed/forged public commitments that would collide with padding.
    assert(forest_commitment_field != 0);
    assert(inventory_commitment_field != 0);
    assert(contract_commitment_field != 0);
    assert(call_slice_commitment_field != 0);
    assert(assumptions_commitment_field != 0);
    assert(analyzer_version_field != 0);
    assert(resolver_version_field != 0);
    assert(translator_version_field != 0);
    assert(prover_version_field != 0);
    assert(result_commitment_field != 0);
    assert(proving_key_id_field != 0);
    assert(verifying_key_id_field != 0);
    assert(ceremony_id_field != 0);

    // Exact canonical length: reject omitted steps and overflow beyond bound.
    let n: u32 = trace_length as u32;
    assert(n == CANONICAL_TRACE_LENGTH);
    assert(n > 0);
    assert(n <= MAX_TRACE_STEPS);

    // Padding slots must be fully zeroed (no padding ambiguity).
    for i in 0..16 {
        let active: bool = (i as u32) < n;
        if !active {
            assert(step_kinds[i] == 0);
            assert(step_source_states[i] == 0);
            assert(step_target_states[i] == 0);
            assert(step_binding_fields[i] == 0);
        }
    }

    // Supported deterministic transition table (fixed order; rejects reorder).
    // 0: init --open_forest--> forest_opened
    assert(step_kinds[0] == KIND_OPEN_FOREST);
    assert(step_source_states[0] == STATE_INIT);
    assert(step_target_states[0] == STATE_FOREST_OPENED);
    assert(step_binding_fields[0] == forest_commitment_field);

    // 1: forest_opened --open_inventory--> inventory_opened
    assert(step_kinds[1] == KIND_OPEN_INVENTORY);
    assert(step_source_states[1] == STATE_FOREST_OPENED);
    assert(step_target_states[1] == STATE_INVENTORY_OPENED);
    assert(step_binding_fields[1] == inventory_commitment_field);

    // 2: inventory_opened --open_contract--> contract_opened
    assert(step_kinds[2] == KIND_OPEN_CONTRACT);
    assert(step_source_states[2] == STATE_INVENTORY_OPENED);
    assert(step_target_states[2] == STATE_CONTRACT_OPENED);
    assert(step_binding_fields[2] == contract_commitment_field);

    // 3: contract_opened --open_call_slice--> call_slice_opened
    assert(step_kinds[3] == KIND_OPEN_CALL_SLICE);
    assert(step_source_states[3] == STATE_CONTRACT_OPENED);
    assert(step_target_states[3] == STATE_CALL_SLICE_OPENED);
    assert(step_binding_fields[3] == call_slice_commitment_field);

    // 4: call_slice_opened --open_assumptions--> assumptions_opened
    assert(step_kinds[4] == KIND_OPEN_ASSUMPTIONS);
    assert(step_source_states[4] == STATE_CALL_SLICE_OPENED);
    assert(step_target_states[4] == STATE_ASSUMPTIONS_OPENED);
    assert(step_binding_fields[4] == assumptions_commitment_field);

    // 5: assumptions_opened --bind_versions--> versions_bound
    let versions_binding = analyzer_version_field
        + resolver_version_field
        + translator_version_field
        + prover_version_field;
    assert(step_kinds[5] == KIND_BIND_VERSIONS);
    assert(step_source_states[5] == STATE_ASSUMPTIONS_OPENED);
    assert(step_target_states[5] == STATE_VERSIONS_BOUND);
    assert(step_binding_fields[5] == versions_binding);

    // 6: versions_bound --commit_result--> result_committed
    assert(step_kinds[6] == KIND_COMMIT_RESULT);
    assert(step_source_states[6] == STATE_VERSIONS_BOUND);
    assert(step_target_states[6] == STATE_RESULT_COMMITTED);
    assert(step_binding_fields[6] == result_commitment_field);

    // 7: result_committed --terminate--> terminal (binds key/circuit identity)
    let key_identity_binding = circuit_id_field
        + proving_key_id_field
        + verifying_key_id_field
        + ceremony_id_field;
    assert(step_kinds[7] == KIND_TERMINATE);
    assert(step_source_states[7] == STATE_RESULT_COMMITTED);
    assert(step_target_states[7] == STATE_TERMINAL);
    assert(step_binding_fields[7] == key_identity_binding);

    // Deterministic public accumulator over the statement (not an authority claim).
    forest_commitment_field
        + inventory_commitment_field
        + contract_commitment_field
        + call_slice_commitment_field
        + assumptions_commitment_field
        + result_commitment_field
        + circuit_id_field
        + proving_key_id_field
        + verifying_key_id_field
        + ceremony_id_field
        + circuit_version
        + trace_length
}
