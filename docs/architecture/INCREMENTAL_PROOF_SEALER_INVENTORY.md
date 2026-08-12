# IncrementalProofSealer datasets inventory (IPS-002)

Static source inventory of `ipfs_datasets_py` ZK, identity, manifest,
dependency, cache, key, and baseline-reference surfaces at the receipt-tested
nested revision. This document is a companion to
`docs/architecture/incremental_proof_sealer_inventory.json`.

## Revisions

| Field | Value |
| --- | --- |
| `planning_revision` | `bd2ff6245ebe476fc744d45c7c66235c92b0e19c` |
| `inventory_worktree_parent_revision` | `78e4db9f77d6cb2960bb9dc7b3890e544b8dc6c1` |

`inventory_worktree_parent_revision` is immutable and equals the receipt-tested
datasets source revision. Final nested/outer/status commits come from supervisor
completion evidence and are not self-embedded here.

## Baseline evidence (reference only)

Operator-captured process observation only. This inventory does not restate
command lines, outcome tallies, logs, or execution claims.

| Field | Value |
| --- | --- |
| path | `artifacts/agent_supervisor/incremental_proof_sealer/baseline_receipts/datasets.json` |
| receipt_digest | `sha256:11b602d2000a3ccf2676131ee3bcab10c6515a4e855e14a3dbac87800c1d34a5` |
| required_command_ids | `datasets-zkp-focused-current`, `datasets-zkp-unit-wide-current`, `datasets-proof-cache-adapters`, `datasets-zkp-broad-safe-current` |
| evidence_origin | `operator_capture` |
| assurance | `process_observed_only` |
| nonclaim | `pytest_execution_not_cryptographically_proven` |

The protected closed suite registry and validator independently recompute suite
preimages, argv, controlled-offline environment, digests, log sizes, counts,
and incomplete-collection evidence nodes. Providers only reference the pin above.

## Inspection method

- classification_method: static source inventory
- Static scans report `surfaces_found` only; they never assert suite outcomes
- Static inspection is not pytest execution and is not cryptographic proof
- Controlled-offline capture disables Groth16/ProveKit enablement, builds,
  downloads, and auto-install; the receipt reference does not establish new
  real proving

## Explicit nonclaims

1. Test-execution certificates without signature verification are **not** signed
   receipts.
2. `TestPassStatementV1` is a Python predicate/statement protocol, **not** an
   implemented ZK aggregation circuit.
3. `proof_receipt_attestation` callback-style cryptographic attempts are
   **structural** unless a real backend actually ran.
4. Groth16 v2 proves a bounded Horn-style TDFOL derivation; that
   computation-proof axis is **distinct** from pytest-execution proof.
5. Event-DAG v3 proving/verifying-key artifacts under
   `processors/groth16_backend/artifacts/v3` are **absent**.
6. `tdfol_v1_axioms_commitment_hex_v2` is an explicit **reduced-field** BN254
   digest binding, not a full cryptographic hash commitment.
7. Outer `ZKPProof.public_inputs` metadata is not currently bound to the inner
   Groth16 public input (binding gap remains open).
8. Existing v1/v2 key files lack production-origin and allowlist evidence and
   remain test-only candidates.
9. Wallet (`wallet/proofs.py`) and PDF form certificate paths default to
   simulated backends and must not authorize production seals.

## Surface families

### CEC

| Path | Role | Classification |
| --- | --- | --- |
| `ipfs_datasets_py/logic/CEC/native/cec_zkp_integration.py` | ZKP bridge | hybrid_bridge |
| `ipfs_datasets_py/logic/CEC/native/cec_proof_cache.py` | proof cache | integrity_cache |

### TDFOL

| Path | Role | Classification |
| --- | --- | --- |
| `ipfs_datasets_py/logic/TDFOL/zkp_integration.py` | ZKP bridge (term alias `tdfol_zkp_integration.py`) | hybrid_bridge |
| `ipfs_datasets_py/logic/TDFOL/tdfol_proof_cache.py` | proof cache | integrity_cache |
| `ipfs_datasets_py/logic/zkp/legal_theorem_semantics.py` | bounded Horn derivation semantics | structural_semantics |

### F-logic

| Path | Role | Classification |
| --- | --- | --- |
| `ipfs_datasets_py/logic/flogic/flogic_zkp_integration.py` | ZKP bridge | hybrid_bridge |
| `ipfs_datasets_py/logic/flogic/flogic_proof_cache.py` | proof cache | integrity_cache |

### Event-DAG v3

| Path | Role | Classification |
| --- | --- | --- |
| `ipfs_datasets_py/mcp_server/event_dag_zkp.py` | Profile F compaction ZK | real_backend_candidate_with_absent_v3_artifacts |
| `ipfs_datasets_py/mcp_server/event_dag.py` | hash-commitment fallback | integrity_only_non_zk |
| `ipfs_datasets_py/mcp_server/dag_compaction.py` | orchestration | structural |
| `ipfs_datasets_py/processors/groth16_backend/artifacts/v3` | key artifacts | **absent** |

### ProveKit FFI

| Path | Role | Classification |
| --- | --- | --- |
| `ipfs_datasets_py/logic/zkp/backends/provekit_ffi.py` | FFI wrapper | real_backend_candidate_fail_closed |
| `ipfs_datasets_py/logic/zkp/backends/provekit.py` | backend entrypoint | real_backend_candidate_fail_closed |
| `ipfs_datasets_py/logic/zkp/provekit/cache.py` | public payload/cache keys | integrity_cache |
| `ipfs_datasets_py/logic/zkp/provekit/circuits/*` | Noir circuit packages | circuit_source_present |

### Wallet / PDF simulated paths

| Path | Role | Classification |
| --- | --- | --- |
| `ipfs_datasets_py/wallet/proofs.py` | wallet proof backends | simulated |
| `tests/integration/test_pdf_form_agent.py` | form completion certificate | simulated |
| `tests/contract/processors/wallets/test_worldcoin_differential.py` | wallet contract surface | contract_surface |

### Backends and API

| Path | Role | Classification |
| --- | --- | --- |
| `ipfs_datasets_py/logic/zkp/backends/simulated.py` | demo backend | simulated |
| `ipfs_datasets_py/logic/zkp/backends/groth16.py` | opt-in Groth16 entry (`ensure_setup`) | real_backend_candidate_opt_in |
| `ipfs_datasets_py/logic/zkp/backends/groth16_ffi.py` | Rust CLI FFI | real_backend_candidate |
| `ipfs_datasets_py/logic/zkp/backends/__init__.py` | lazy registry | structural |
| `ipfs_datasets_py/logic/zkp/zkp_prover.py` | high-level prover | mixed |
| `ipfs_datasets_py/logic/zkp/zkp_verifier.py` | high-level verifier | mixed |

### Identity, manifests, canonicalization

| Path | Role | Classification |
| --- | --- | --- |
| `ipfs_datasets_py/logic/zkp/canonicalization.py` | text/axiom commitments; reduced-field v2 binding | integrity_commitment |
| `ipfs_datasets_py/logic/zkp/statement.py` | statement/witness formats | structural |
| `ipfs_datasets_py/logic/zkp/circuits.py` | circuit helpers / attestation views | mixed_structural_and_real_targets |
| `ipfs_datasets_py/logic/zkp/vk_registry.py` | VK hash registry | integrity_only |
| `ipfs_datasets_py/logic/common/proof_cache.py` | unified CID proof cache | integrity_cache |
| `ipfs_datasets_py/logic/proof_corpus` | attested envelope store/policy | integrity_and_policy |

### Test execution and attestation

| Path | Role | Classification |
| --- | --- | --- |
| `ipfs_datasets_py/logic/zkp/test_execution_certificate.py` | certificate conformance | structural_integrity (unsigned without signature verification) |
| `ipfs_datasets_py/logic/zkp/statements/test_pass.py` | `TestPassStatementV1` | predicate_only (not a ZK circuit) |
| `ipfs_datasets_py/logic/zkp/provekit/test_pass_circuit.py` | circuit binding | structural_binding |
| `ipfs_datasets_py/logic/bridge/proof_receipt_attestation.py` | receipt attestation | structural_unless_real_backend |

### Setup / key generation and key identity

| Path | Role | Classification |
| --- | --- | --- |
| `ipfs_datasets_py/logic/zkp/backends/groth16.py#ensure_setup` | idempotent key provisioning | setup_key_generation_surface |
| `ipfs_datasets_py/logic/zkp/setup_artifacts.py` | IPFS pk/vk CID helpers | integrity_transport |
| `ipfs_datasets_py/processors/groth16_backend/src/setup.rs` | Rust setup; emits exact `proving_key_sha256_hex` / `verifying_key_sha256_hex` / `vk_hash_hex` | setup_key_generation_surface |
| `ipfs_datasets_py/processors/groth16_backend/artifacts/v1/{proving,verifying}_key.bin` | keys on disk | test_only_key_candidate |
| `ipfs_datasets_py/processors/groth16_backend/artifacts/v2/{proving,verifying}_key.bin` | keys on disk | test_only_key_candidate |
| `ipfs_datasets_py/processors/groth16_backend/artifacts/v3` | Event-DAG keys | **absent** |

Key provenance: no production-origin or allowlist evidence is present for the
checked-in v1/v2 artifacts. Exact identity surfaces are the setup manifest
digest fields and the on-disk versioned paths above.

### Circuit version axes

| Version | Declared claim | Artifacts | Notes |
| --- | --- | --- | --- |
| Groth16 v1 | nonzero public commitment / knowledge_of_axioms | `artifacts/v1` present | bounded declared computation only; not a pytest-execution proof axis |
| Groth16 v2 | bounded TDFOL_v1 Horn derivation | `artifacts/v2` present | reduced-field axiom commitment; computation-proof axis distinct from pytest-execution proof |
| Event-DAG v3 | event digests → Merkle root + count | `artifacts/v3` **absent** | public root is Fr-reduced; archive compares full root bytes |

## Focused tests (repository-relative)

### Focused unit (`tests/unit/logic/zkp/`)

- `tests/unit/logic/zkp/test_eth_transaction_guard.py`
- `tests/unit/logic/zkp/test_legal_constraint_attestation.py`
- `tests/unit/logic/zkp/test_program_contract_trace.py`
- `tests/unit/logic/zkp/test_test_execution_certificate.py`
- `tests/unit/logic/zkp/test_test_pass_statement.py`

### Unit-wide (`tests/unit_tests/logic/zkp/`)

- `tests/unit_tests/logic/zkp/test_backend_selection.py`
- `tests/unit_tests/logic/zkp/test_canonicalization.py`
- `tests/unit_tests/logic/zkp/test_circuit_version_policy.py`
- `tests/unit_tests/logic/zkp/test_eth_contract_artifacts.py`
- `tests/unit_tests/logic/zkp/test_eth_vk_registry_payloads.py`
- `tests/unit_tests/logic/zkp/test_evm_harness.py`
- `tests/unit_tests/logic/zkp/test_evm_public_inputs.py`
- `tests/unit_tests/logic/zkp/test_groth16_backend_entrypoint_seed.py`
- `tests/unit_tests/logic/zkp/test_groth16_backend_ffi.py`
- `tests/unit_tests/logic/zkp/test_groth16_wire_vectors.py`
- `tests/unit_tests/logic/zkp/test_legal_theorem_semantics.py`
- `tests/unit_tests/logic/zkp/test_mpc_ceremony.py`
- `tests/unit_tests/logic/zkp/test_onchain_pipeline.py`
- `tests/unit_tests/logic/zkp/test_phase3c5_golden_vector_roundtrip.py`
- `tests/unit_tests/logic/zkp/test_provekit_artifacts.py`
- `tests/unit_tests/logic/zkp/test_provekit_attestation_envelope.py`
- `tests/unit_tests/logic/zkp/test_provekit_backend.py`
- `tests/unit_tests/logic/zkp/test_provekit_cache_ipfs_payloads.py`
- `tests/unit_tests/logic/zkp/test_provekit_cli_wrapper.py`
- `tests/unit_tests/logic/zkp/test_provekit_ffi_wrapper.py`
- `tests/unit_tests/logic/zkp/test_provekit_golden_vectors.py`
- `tests/unit_tests/logic/zkp/test_provekit_hybrid_provers.py`
- `tests/unit_tests/logic/zkp/test_provekit_knowledge_of_axioms_circuit.py`
- `tests/unit_tests/logic/zkp/test_provekit_properties.py`
- `tests/unit_tests/logic/zkp/test_provekit_public_inputs.py`
- `tests/unit_tests/logic/zkp/test_provekit_recursive_export_contract.py`
- `tests/unit_tests/logic/zkp/test_provekit_tdfol_trace_circuit.py`
- `tests/unit_tests/logic/zkp/test_provekit_tdfol_trace_schema.py`
- `tests/unit_tests/logic/zkp/test_provekit_witness_no_leak.py`
- `tests/unit_tests/logic/zkp/test_provekit_zkp_attestation_bridge.py`
- `tests/unit_tests/logic/zkp/test_setup_artifacts_ipfs.py`
- `tests/unit_tests/logic/zkp/test_tdfol_v1_derivation_circuit.py`
- `tests/unit_tests/logic/zkp/test_vk_registry.py`
- `tests/unit_tests/logic/zkp/test_witness_manager.py`
- `tests/unit_tests/logic/zkp/test_zkp_edge_cases.py`
- `tests/unit_tests/logic/zkp/test_zkp_golden_vectors.py`
- `tests/unit_tests/logic/zkp/test_zkp_integration.py`
- `tests/unit_tests/logic/zkp/test_zkp_module.py`
- `tests/unit_tests/logic/zkp/test_zkp_performance.py`
- `tests/unit_tests/logic/zkp/test_zkp_properties.py`

### Cache adapters

- `tests/unit_tests/logic/CEC/native/test_cec_zkp_integration.py`
- `tests/unit_tests/logic/CEC/native/test_cec_proof_cache.py`
- `tests/unit_tests/logic/TDFOL/test_tdfol_proof_cache.py`
- `tests/unit/logic/test_flogic_cache_zkp.py`
- `tests/unit/logic/test_flogic_integration.py`
- `tests/unit/logic/test_flogic_semantic_cid.py`

### Integration / MCP / wallet / PDF

- `tests/integration/test_provekit_zkp.py`
- `tests/integration/test_groth16_local_evm_verification.py`
- `tests/integration/logic/test_proof_receipt_attestation.py`
- `tests/mcp/unit/test_mcplusplus_spec_session50.py`
- `tests/mcp/integration/test_profile_f_ceremony_p2p.py`
- `tests/mcp/integration/test_profile_d_policy_p2p.py`
- `tests/contract/processors/wallets/test_worldcoin_differential.py`
- `tests/integration/test_pdf_form_agent.py`

## Environment gates observed in source

- `IPFS_DATASETS_ENABLE_GROTH16`
- `IPFS_DATASETS_PY_AUTO_GROTH16_BUILD`
- `IPFS_DATASETS_RUN_GROTH16_EVM`
- `IPFS_DATASETS_RUN_PROVEKIT_TESTS`
- `IPFS_DATASETS_GROTH16_BINARY`
- `IPFS_DATASETS_EVENT_DAG_GROTH16_ARTIFACTS`
- `IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS`
- `GROTH16_BACKEND_ARTIFACTS_ROOT`
- `GROTH16_BACKEND_DETERMINISTIC`

## Ownership candidates

Datasets remains the semantic authority for proof evidence classes, proof-unit
and status enums, identity/manifest/dependency schemas, invalidation rules, and
the canonical commitment codec. Proposed package for incremental sealing:

`ipfs_datasets_py.logic.zkp.incremental_sealing`

Kit retains storage/WAL/CAS authority; accelerate retains proving orchestration
and scheduling. This inventory does not invent a second proof-cache authority
outside datasets semantics.

## Machine-readable companion

See `incremental_proof_sealer_inventory.json` in this directory for the full
classification list with `surfaces_found` counts and the exact
`baseline_evidence` reference-only projection.
