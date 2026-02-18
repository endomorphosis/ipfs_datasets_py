# PHASE 3C.6: On-Chain Integration Implementation Plan

## Overview

Phase 3C.6 integrates the Groth16 zkSNARK system with Ethereum smart contracts, enabling on-chain proof verification for legal complaint submissions. This phase builds on the validated circuit constraints (3C.4) and golden vector testing (3C.5).

## Architecture

```
Application Layer (Python):
  ├── ComplianceProverClient (generate proofs locally)
  ├── EthereumProofSubmitter (submit to blockchain)
  └── ProofAuditLog (track on-chain verification)
        ↓
Network/RPCs:
  ├── Ethereum Testnet (Sepolia/Goerli)
  ├── Local Ganache (for development)
  └── Mainnet (future production)
        ↓
Smart Contract Layer (Solidity):
  ├── GrothVerifier (core verification logic)
  ├── ComplaintRegistry (proof storage & status)
  ├── VerificationOracle (off-chain result feed)
  └── GasOptimizations (efficient verification)
        ↓
Cryptographic Layer:
  ├── BN254 Curve (Ethereum native)
  ├── Groth16 Pairing Checks
  └── Field Arithmetic (Fr, Fq)
```

## Phase 3C.6 Subtasks

### 3C.6.1: Solidity Verifier Contract
**Objective:** Implement BN254-based Groth16 verifier on-chain

**Deliverables:**
- `VerificationCircuit.sol` - Core pairing verification logic
- `GrothVerifier.sol` - Wraps verifier for complaint-specific use
- Gas optimization for multiple proof verifications
- Support for batched verification

**Key Functions:**
```solidity
verify(uint256[8] calldata proof, uint256[4] calldata publicInputs) → bool
verifyBatch(uint256[] calldata proofs, uint256[][] calldata inputs) → bool[]
getVerificationCost() → uint256
```

**Design Patterns:**
- Merkle accumulator for multiple proofs
- Gas-efficient field arithmetic
- Calldata optimization for large proofs

### 3C.6.2: Smart Contract Integration
**Objective:** Create contract ecosystem for complaint proof tracking

**Components:**
- `ComplaintRegistry.sol` - Store complaint proofs and status
- `ProofAuditLog.sol` - Immutable verification history
- `AccessControl.sol` - Role-based permissions (investigator, judge, verifier)

**Key Data Structures:**
```solidity
struct ComplaintProof {
  bytes32 theoremHash;
  bytes32 axiomsCommitment;
  uint256 timestamp;
  bool verified;
  uint256 gasUsed;
}

struct VerificationRecord {
  address prover;
  uint256 blockNumber;
  bool result;
  string failureReason;
}
```

### 3C.6.3: Python/Ethereum Integration
**Objective:** Enable proof submission from Python to blockchain

**Modules:**
- `eth_contract_interface.py` - web3.py contract ABI interaction
- `proof_submission_pipeline.py` - Orchestrate proof generation → on-chain verification
- `tx_monitoring.py` - Track transaction status and confirmation
- `gas_estimator.py` - Predict costs before submission

**Workflow:**
```python
1. Generate proof locally (Phase 3C.4 Rust circuit)
2. Prepare public inputs for on-chain encoding
3. Estimate gas requirements
4. Submit transaction to testnet
5. Wait for confirmation (20 blocks)
6. Query verification result
7. Log audit trail
```

### 3C.6.4: Testnet Deployment
**Objective:** Deploy to Ethereum Sepolia/Goerli and validate

**Setup:**
- Configure contract deployment addresses
- Set up test accounts with Sepolia ETH
- Deploy verifier contract
- Create complaint registry
- Fund prover account

**Validation:**
- Submit sample proofs
- Verify on-chain computation
- Measure gas costs
- Assess throughput (proofs/block)
- Check block impact

### 3C.6.5: Integration Testing
**Objective:** End-to-end tests from proof generation to on-chain verification

**Test Suite:**
- `test_contract_deployment.py` - Deploy and initialize contracts
- `test_proof_submission.py` - Generate proof, submit, verify on-chain
- `test_batch_verification.py` - Multiple proofs in single transaction
- `test_gas_optimization.py` - Measure and validate gas efficiency
- `test_failure_cases.py` - Invalid proofs rejected on-chain
- `test_concurrent_submissions.py` - Multiple provers submitting simultaneously

**Coverage:**
- Happy path: valid proof → verified ✅
- Invalid proof: rejected on-chain ✅
- Reorg handling: proof persists across chain reorg ✅
- Gas efficiency: cost < budget ✅
- Concurrent access: no race conditions ✅

## Implementation Sequence

```
Step 1: Solidity Contract Development
  1a. Implement BN254 pair verification
  1b. Implement Groth16 verification algorithm
  1c. Optimize for Ethereum gas
  
Step 2: Python Integration Layer
  2a. Create eth_contract_interface.py
  2b. Implement proof_submission_pipeline.py
  2c. Add transaction monitoring
  
Step 3: Testnet Deployment
  3a. Deploy to Sepolia
  3b. Initialize contract state
  3c. Fund test accounts
  
Step 4: Integration Testing
  4a. Unit tests for Solidity functions
  4b. Integration tests for full pipeline
  4c. Gas optimization validation
  
Step 5: Documentation & Handoff
  5a. Contract ABI documentation
  5b. Deployment procedure guide
  5c. Cost estimation tables
```

## Technical Details

### Groth16 On-Chain Format

**Public Inputs (4 field elements):**
```
[0]: theorem_hash               (256-bit)
[1]: axioms_commitment         (256-bit)
[2]: circuit_version           (8-bit in 256)
[3]: ruleset_authority         (160-bit address)

Total: ~1KB when encoded on-chain
```

**Proof Components:**
```
A ∈ G1 (2 field elements)
B ∈ G2 (4 field elements)
C ∈ G1 (2 field elements)
Total: 8 field elements = 256 bytes

Encoded for contract:
  proof_data = (A.x, A.y, B.x, B.y, B.y_im, C.x, C.y)
  + gas-efficient packing
```

### Gas Cost Estimation

**Current estimates (Ethereum mainnet):**
- Verifier deployment: ~2.5M gas (~$200 @ 20 gwei)
- Single proof verification: ~200K gas (~$16 @ 20 gwei)
- Batch verification (10 proofs): ~250K total (~$1.60 per proof)

**Optimization targets:**
- Use precompiled pairing checks (0x08) on mainnet
- Implement Merkle accumulator for batching
- Compress proofs with point compression
- Lazy evaluation of second pairing

### Security Considerations

1. **Proof Replay Protection**
   - Include nonce in proof generation
   - Verify proof not already submitted
   - Timestamp-based expiration (24 hours)

2. **Invalid Proof Handling**
   - Silent failure (return false, no revert)
   - Emit event for off-chain monitoring
   - No information leakage about why proof failed

3. **Contract Upgrade Path**
   - Use proxy pattern for verifier
   - Separate proof registry (immutable)
   - Version field in public inputs

4. **Access Control**
   - Only authorized provers can submit
   - Registry owner can freeze submission
   - Judge can appeal/override verification

## Success Criteria

✅ Solidity verifier compiles without warnings
✅ All gas optimizations applied
✅ Python integration layer tested
✅ Testnet deployment documented
✅ 100+ proofs verified on testnet
✅ Gas costs within budget
✅ Full integration test coverage
✅ Zero security vulnerabilities (audit-ready)

## Deliverables Checklist

- [ ] `GrothVerifier.sol` (main verifier contract)
- [ ] `ComplaintRegistry.sol` (proof storage)
- [ ] `ProofAuditLog.sol` (verification history)
- [ ] `eth_contract_interface.py` (web3 integration)
- [ ] `proof_submission_pipeline.py` (orchestration)
- [ ] Testnet deployment guide
- [ ] Integration test suite
- [ ] Cost estimation report
- [ ] ABI documentation
- [ ] Deployment checklist

## Timeline & Milestones

**Estimated duration:** 4-6 hours (if solidity templates available)

**Milestones:**
1. Contracts compile & deploy locally (Ganache)
2. Python integration layer complete
3. Testnet deployment (Sepolia)
4. 50 proofs verified successfully
5. Integration test suite passing
6. Gas optimization complete
7. Documentation finalized
8. Ready for auditing

---

## Resources & References

### Groth16 Verifier Resources
- [Circom & SnarkJS Verifier Template](https://github.com/iden3/snarkjs)
- [Ethereum BN254 Precompiles](https://eips.ethereum.org/EIPS/eip-197)
- [Groth16 Spec](https://eprint.iacr.org/2016/260)

### Solidity Best Practices
- [OpenZeppelin Contracts](https://github.com/OpenZeppelin/openzeppelin-contracts)
- [Gas Optimization Tips](https://docs.soliditylang.org/en/latest/gas-optimization.html)

### Testnet Resources
- [Sepolia Faucet](https://www.alchemy.com/faucets/ethereum-sepolia)
- [Goerli Faucet](https://goerlifaucet.com/)

---

**Phase 3C.6 Start Date:** 2026-02-18  
**Target Completion:** 2026-02-18 (same session if sufficient time)  
**Overall Phase 3C Completion Target:** 100% (all 6 substeps)
