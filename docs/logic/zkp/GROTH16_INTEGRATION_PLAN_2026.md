# Groth16 ZKP Integration Plan 2026

**Status:** Phase 1 (Binary + Setup) ✅ Complete | Phase 2 (Python Wiring) ✅ Complete  
**Last Updated:** 2026-02-22  
**Scope:** `ipfs_datasets_py/processors/groth16_backend/` (Rust) + `ipfs_datasets_py/logic/zkp/` (Python)

---

## Executive Summary

The Groth16 Rust backend is now **fully compiled and wired** to the Python ZKP
stack.  The `cargo build --release` + trusted setup pipeline produces real
Groth16 BN254 zkSNARK proofs that are cryptographically sound.  The Python
`ZKPProver` + `ZKPToUCANBridge` stack automatically uses these real proofs when
`IPFS_DATASETS_ENABLE_GROTH16=1` is set.

---

## Architecture

```
NL Policy Text / Theorem
        │
        ▼
  ZKPProver(backend="groth16")
        │   IPFS_DATASETS_ENABLE_GROTH16=1
        │
        ▼
  Groth16Backend.generate_proof()          ← logic/zkp/backends/groth16.py
        │   ensure_setup() → auto-provisions keys if absent
        │
        ▼
  Groth16FFIBackend.generate_proof()       ← logic/zkp/backends/groth16_ffi.py
        │   subprocess: groth16 prove --input /dev/stdin ...
        │
        ▼
  [Rust binary]  groth16_backend/target/release/groth16
        │   ark-groth16 + ark-bn254 → real BN254 Groth16 proof
        │   reads artifacts/v{N}/proving_key.bin
        │
        ▼
  Groth16Proof {proof_data (JSON bytes), public_inputs, metadata}
        │
        ▼
  ZKPToUCANBridge.proof_to_caveat()        ← logic/zkp/ucan_zkp_bridge.py
        │   ZKPCapabilityEvidence {proof_hash, theorem_cid, verifier_id}
        │
        ▼
  DelegationToken(capabilities, nonce=proof_hash[:16])
        │   ucan_delegation.py / py-ucan
        │
        ▼
  Signed UCAN JWT  (DIDKeyManager.sign_delegation_token)
```

---

## Status by Phase

### Phase 1 — Rust Backend ✅ Complete

| Task | Status | Notes |
|------|--------|-------|
| Cargo.toml with ark-groth16 0.4 / ark-bn254 0.4 | ✅ | Done |
| `src/circuit.rs` — MVPCircuit (v1) + TDFOLv1DerivationCircuitV2 (v2) | ✅ | Done |
| `src/prover.rs` — Groth16 proof generation | ✅ | Done |
| `src/verifier.rs` — Groth16 proof verification | ✅ | Done |
| `src/setup.rs` — Trusted setup (generating_key / verifying_key) | ✅ | Done |
| CLI: `groth16 prove --input /dev/stdin --output /dev/stdout` | ✅ | Done |
| CLI: `groth16 verify --proof /dev/stdin` | ✅ | Done |
| CLI: `groth16 setup --version N [--seed U64]` | ✅ | Done |
| JSON wire format (schemas/witness_v1, proof_v1, error_envelope_v1) | ✅ | Done |
| Exit codes: 0=valid, 1=invalid, 2=error | ✅ | Done |
| Structured error envelope (JSON on stdout for exit=2) | ✅ | Done |
| Determinism: `--seed <u64>` forces `timestamp=0` | ✅ | Done |
| `artifacts/v1/` + `artifacts/v2/` trusted setup keys committed | ✅ | `seed=42` |
| `build.sh` convenience script | ✅ | Done |

### Phase 2 — Python Wiring ✅ Complete

| Task | Status | Notes |
|------|--------|-------|
| `groth16_ffi.Groth16Backend` subprocess wrapper | ✅ | Done |
| `groth16_ffi.Groth16Backend.setup()` — runs `groth16 setup` | ✅ | Added |
| `groth16_ffi.Groth16Backend.artifacts_exist()` | ✅ | Added |
| `groth16.Groth16Backend` gated adapter (IPFS_DATASETS_ENABLE_GROTH16) | ✅ | Done |
| `groth16.Groth16Backend.ensure_setup()` — idempotent setup | ✅ | Added |
| `groth16.Groth16Backend.binary_available()` | ✅ | Added |
| `groth16.Groth16Backend.get_backend_info()` | ✅ | Added |
| `ZKPToUCANBridge.__init__` uses real Groth16 when enabled | ✅ | Added |
| `ZKPToUCANBridge._auto_provision_setup()` — auto-runs setup | ✅ | Added |
| `ZKPToUCANBridge.GROTH16_VERIFIER_ID` constant | ✅ | Added |
| `ZKPToUCANBridge.prove_and_delegate()` — no warning when Groth16 enabled | ✅ | Fixed |
| `get_zkp_ucan_bridge(reset=True)` to force re-init after env change | ✅ | Added |
| `backends.__init__.get_backend("groth16")` works | ✅ | Existing |

### Phase 3 — Integration Tests ✅ Complete

See `tests/unit_tests/logic/zkp/test_v16_groth16_integration.py` (45+ tests).

### Phase 4 — Deferred Items

| Task | Target | Notes |
|------|--------|-------|
| Real TDFOL derivation trace wired to circuit_version=2 | v17+ | `derive_tdfol_v1_trace` path exists; needs end-to-end test |
| Groth16 circuit for multi-axiom theorem chains | v17+ | Current circuit hashes axioms list; could be per-axiom |
| EVM/on-chain verification (`eth_integration.py`) | v18+ | `contracts/GrothVerifier.sol` is ready |
| On-chain VK registry (`VKHashRegistry.sol`) | v18+ | Needs ethers.py / web3 wiring |
| `setup_artifacts.py` IPFS store integration | v18+ | Needs live IPFS node |
| ZKP proof serialization to IPFS (CIDv1) | v18+ | `onchain_pipeline.py` stub ready |
| Groth16 for multi-language NL policy (French/German/Spanish) | v19+ | NL parsers exist, axiom extraction needed |
| Real UCAN ZKP proof verification via `verify_proof()` | v17+ | Currently structural check; needs Rust verify call |
| Production key ceremony (multi-party trusted setup) | v20+ | Replace deterministic seed |
| Recursive proof aggregation (Groth16 → PLONK/Halo2) | v21+ | Research item |

---

## Quick Start

```bash
# 1. Compile the Rust binary (one time)
cd ipfs_datasets_py/processors/groth16_backend
./build.sh                    # release build + setup v1+v2

# 2. Enable in Python
export IPFS_DATASETS_ENABLE_GROTH16=1

# 3. Generate a real proof
python3 - <<'EOF'
import warnings
warnings.filterwarnings("ignore")
from ipfs_datasets_py.logic.zkp.zkp_prover import ZKPProver
prover = ZKPProver(backend="groth16")
proof = prover.generate_proof(
    theorem="Socrates is mortal",
    private_axioms=["Socrates is human", "All humans are mortal"],
)
print(f"Proof type: {proof.metadata.get('backend')}")
print(f"Proof size: {proof.size_bytes} bytes")
EOF

# 4. Bridge to UCAN
python3 - <<'EOF'
import os, warnings
os.environ["IPFS_DATASETS_ENABLE_GROTH16"] = "1"
from ipfs_datasets_py.logic.zkp.ucan_zkp_bridge import get_zkp_ucan_bridge, ZKPToUCANBridge
bridge = get_zkp_ucan_bridge(reset=True)
result = bridge.prove_and_delegate(
    theorem="P → Q",
    actor="did:key:alice",
    resource="logic/proof",
    ability="proof/invoke",
    private_axioms=["P", "P → Q"],
)
print(f"Success: {result.success}")
print(f"Verifier: {result.zkp_caveat.verifier_id}")
print(f"Warnings: {result.warnings}")
EOF
```

---

## Wire Format Reference

### Witness input (stdin to `groth16 prove`)

```json
{
  "private_axioms": ["string"],
  "theorem": "string",
  "axioms_commitment_hex": "64 hex chars",
  "theorem_hash_hex": "64 hex chars",
  "circuit_version": 1,
  "ruleset_id": "TDFOL_v1",
  "security_level": 0,
  "intermediate_steps": []
}
```

### Proof output (stdout from `groth16 prove`)

```json
{
  "schema_version": 1,
  "version": 1,
  "proof_a": "[\"0x...\", \"0x...\"]",
  "proof_b": "[[\"0x...\", \"0x...\"], [\"0x...\", \"0x...\"]]",
  "proof_c": "[\"0x...\", \"0x...\"]",
  "public_inputs": ["theorem_hash_hex", "axioms_commitment_hex", "circuit_version", "ruleset_id"],
  "timestamp": 0,
  "evm_proof": ["0x..."],
  "evm_public_inputs": ["0x..."]
}
```

### Error envelope (stdout when exit=2)

```json
{"error": {"schema_version": 1, "code": "INTERNAL", "message": "..."}}
```

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `IPFS_DATASETS_ENABLE_GROTH16` | `""` (disabled) | Enable real Groth16 proofs (`1`/`true`/`yes`) |
| `IPFS_DATASETS_GROTH16_BINARY` | auto-detect | Path to compiled binary |
| `GROTH16_BINARY` | auto-detect | Fallback binary path |
| `GROTH16_BACKEND_DETERMINISTIC` | `""` | Force `timestamp=0` in Rust CLI |

---

## Binary Search Paths (Python auto-detection)

1. `$IPFS_DATASETS_GROTH16_BINARY` (env override)
2. `$GROTH16_BINARY` (env override)
3. `<pkg_root>/processors/groth16_backend/target/release/groth16` (canonical)
4. `<repo_root>/processors/groth16_backend/target/release/groth16` (alternate)
5. `<repo_root>/../groth16_backend/target/release/groth16` (legacy)
6. `~/.cargo/bin/groth16` (installed globally)

---

## Security Considerations

1. **Trusted setup seed `42`** — The committed `artifacts/v1/` and `artifacts/v2/`
   keys were generated with `--seed 42`.  This is **not a production ceremony**.
   For production use, run a multi-party trusted setup (MPC) ceremony and commit
   the new keys with attestation.

2. **Axiom privacy** — Private axioms are hashed before sending to the Rust binary
   via the Python canonicalization layer.  The Rust process receives only the
   commitment hash, not the raw axioms.

3. **Binary authenticity** — Verify the binary SHA-256 before deployment in
   production.  Consider signing the release binary with a DID key from
   `DIDKeyManager`.

4. **Proof freshness** — UCAN tokens include `expiry`; ZKP caveats do not
   currently include a timestamp.  Add `valid_after` + `valid_until` fields to
   `ZKPCapabilityEvidence` in a future session.

5. **Fail-closed default** — `IPFS_DATASETS_ENABLE_GROTH16` defaults to disabled
   to prevent accidental use of the simulated backend in production systems that
   expect real proofs.

---

## Module Map

```
processors/groth16_backend/
├── Cargo.toml                     ark-groth16 0.4, ark-bn254 0.4
├── build.sh                       Build + setup convenience script
├── RUST_SETUP.md                  Detailed Rust install guide
├── WIRE_FORMAT.md                 Authoritative JSON wire format spec
├── IMPROVEMENT_TODO.md            Remaining Rust-side tasks
├── src/
│   ├── main.rs                    CLI: prove / verify / setup / export-solidity
│   ├── lib.rs                     Public: prove() + verify() + setup()
│   ├── circuit.rs                 MVPCircuit (v1) + TDFOLv1DerivationCircuitV2 (v2)
│   ├── prover.rs                  Groth16Prover with BN254
│   ├── verifier.rs                Groth16Verifier with BN254
│   ├── setup.rs                   Trusted parameter generation
│   └── domain.rs                  Domain separation helpers
├── schemas/
│   ├── witness_v1.schema.json
│   ├── proof_v1.schema.json
│   └── error_envelope_v1.schema.json
└── artifacts/
    ├── v1/ proving_key.bin + verifying_key.bin   (seed=42, test-only)
    └── v2/ proving_key.bin + verifying_key.bin   (seed=42, test-only)

logic/zkp/
├── __init__.py                    ZKPProof, ZKPError, lazy exports
├── backends/
│   ├── __init__.py                get_backend(), ZKBackend protocol
│   ├── backend_protocol.py        backward-compat re-export
│   ├── groth16.py                 Gated adapter (IPFS_DATASETS_ENABLE_GROTH16)
│   ├── groth16_ffi.py             Subprocess wrapper + setup() + artifacts_exist()
│   └── simulated.py              Default demo backend
├── zkp_prover.py                  ZKPProver (delegates to backend)
├── zkp_verifier.py                ZKPVerifier (delegates to backend)
├── ucan_zkp_bridge.py             ZKPToUCANBridge (real Groth16 + UCAN)
├── canonicalization.py            Deterministic theorem/axiom hashing
├── circuits.py                    ZKPCircuit + MVPCircuit Python wrappers
├── witness_manager.py             Witness generation + validation
├── statement.py                   Statement + Witness dataclasses
├── legal_theorem_semantics.py     TDFOL_v1 axiom/theorem parsing
├── setup_artifacts.py             IPFS artifact storage helpers
├── vk_registry.py                 Verifying key registry
├── onchain_pipeline.py            EVM/on-chain pipeline stub
├── eth_integration.py             Ethereum integration helpers
├── eth_contract_artifacts.py      Contract ABI/bytecode
├── eth_vk_registry_payloads.py    VK registry payloads
├── evm_harness.py                 EVM execution harness
└── evm_public_inputs.py           EVM public input helpers
```
