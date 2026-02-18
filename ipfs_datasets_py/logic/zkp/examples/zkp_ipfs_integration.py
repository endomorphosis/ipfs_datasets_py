#!/usr/bin/env python3
"""
ZKP IPFS Integration Demo

This script demonstrates how to integrate ZKP proofs with IPFS storage,
including:
- Storing proofs in IPFS
- Retrieving and verifying proofs from IPFS
- Creating a verifiable proof chain
- Best practices for distributed proof systems

⚠️ EDUCATIONAL USE ONLY: Simulation for learning, not cryptographically secure.
"""

import json
import hashlib
from typing import Dict, Any, List
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver, ZKPVerifier


class MockIPFSClient:
    """Mock IPFS client for demonstration (no actual IPFS connection needed)."""
    
    def __init__(self):
        self.storage = {}  # CID -> data
    
    def add_json(self, data: dict) -> str:
        """Add JSON data and return CID."""
        json_str = json.dumps(data, sort_keys=True)
        cid = hashlib.sha256(json_str.encode()).hexdigest()[:46]  # Simulate CID
        self.storage[cid] = data
        return cid
    
    def get_json(self, cid: str) -> dict:
        """Retrieve JSON data by CID."""
        if cid not in self.storage:
            raise KeyError(f"CID not found: {cid}")
        return self.storage[cid]
    
    def pin(self, cid: str):
        """Pin CID (mock - already stored)."""
        if cid not in self.storage:
            raise KeyError(f"CID not found: {cid}")
        print(f"  Pinned: {cid}")


class ZKPIPFSBridge:
    """Bridge between ZKP proofs and IPFS storage."""
    
    def __init__(self, ipfs_client=None):
        self.ipfs = ipfs_client or MockIPFSClient()
        self.proof_chain = []
    
    def store_proof(self, proof: Dict[str, Any], verification_key: Any, 
                    metadata: Dict[str, Any] = None) -> str:
        """
        Store proof and verification key in IPFS.
        
        Args:
            proof: ZKP proof dictionary
            verification_key: Verification key for the proof
            metadata: Optional metadata (description, timestamp, etc.)
        
        Returns:
            IPFS CID of stored proof
        """
        # Package proof with verification key and metadata
        package = {
            'proof': proof,
            'verification_key': verification_key,
            'metadata': metadata or {}
        }
        
        # Store in IPFS
        cid = self.ipfs.add_json(package)
        
        # Pin to ensure persistence
        self.ipfs.pin(cid)
        
        # Track in chain
        self.proof_chain.append(cid)
        
        return cid
    
    def retrieve_proof(self, cid: str) -> Dict[str, Any]:
        """
        Retrieve proof package from IPFS.
        
        Args:
            cid: IPFS CID of the proof
        
        Returns:
            Proof package (proof + verification_key + metadata)
        """
        return self.ipfs.get_json(cid)
    
    def verify_from_ipfs(self, cid: str, expected_public_inputs: List) -> bool:
        """
        Retrieve and verify proof from IPFS.
        
        Args:
            cid: IPFS CID of the proof
            expected_public_inputs: Expected public input values
        
        Returns:
            True if proof is valid
        """
        # Retrieve proof package
        package = self.retrieve_proof(cid)
        
        # Extract components
        proof = package['proof']
        verification_key = package['verification_key']
        
        # Verify
        verifier = ZKPVerifier(verification_key)
        return verifier.verify_proof(proof, expected_public_inputs)
    
    def create_proof_chain(self, proofs_with_vks: List[tuple]) -> List[str]:
        """
        Create a chain of proofs stored in IPFS.
        
        Args:
            proofs_with_vks: List of (proof, verification_key, metadata) tuples
        
        Returns:
            List of CIDs forming the proof chain
        """
        cids = []
        for i, (proof, vk, metadata) in enumerate(proofs_with_vks):
            # Add reference to previous proof in chain
            if cids:
                metadata['previous_cid'] = cids[-1]
            metadata['chain_index'] = i
            
            cid = self.store_proof(proof, vk, metadata)
            cids.append(cid)
        
        return cids


def demo_basic_storage():
    """Demo 1: Basic proof storage and retrieval."""
    print("\n" + "="*60)
    print("Demo 1: Basic Proof Storage in IPFS")
    print("="*60)
    
    # Create proof
    circuit = BooleanCircuit()
    w1, w2, w3 = [circuit.add_wire() for _ in range(3)]
    circuit.add_gate('AND', [w1, w2], w3)
    circuit.set_private_input(w1)
    circuit.set_private_input(w2)
    circuit.set_public_input(w3)
    
    prover = ZKPProver(circuit)
    witness = {w1: True, w2: True}
    proof = prover.generate_proof(witness, [True])
    vk = prover.get_verification_key()
    
    # Store in IPFS
    bridge = ZKPIPFSBridge()
    metadata = {
        'description': 'AND gate proof',
        'circuit_type': 'boolean',
        'timestamp': '2026-02-18T00:00:00Z'
    }
    cid = bridge.store_proof(proof, vk, metadata)
    
    print(f"\n✓ Proof stored in IPFS")
    print(f"  CID: {cid}")
    print(f"  Metadata: {metadata['description']}")
    
    # Retrieve and verify
    is_valid = bridge.verify_from_ipfs(cid, expected_public_inputs=[True])
    
    print(f"\n✓ Proof retrieved from IPFS")
    print(f"✓ Verification result: {is_valid}")


def demo_proof_chain():
    """Demo 2: Create a chain of proofs."""
    print("\n" + "="*60)
    print("Demo 2: Proof Chain in IPFS")
    print("="*60)
    
    # Create multiple related proofs
    circuit = BooleanCircuit()
    w1, w2, w3 = [circuit.add_wire() for _ in range(3)]
    circuit.add_gate('AND', [w1, w2], w3)
    circuit.set_private_input(w1)
    circuit.set_private_input(w2)
    circuit.set_public_input(w3)
    
    prover = ZKPProver(circuit)
    vk = prover.get_verification_key()
    
    # Generate 5 proofs in sequence
    proofs_with_vks = []
    for i in range(5):
        witness = {w1: True, w2: i % 2 == 0}
        expected = [i % 2 == 0]
        proof = prover.generate_proof(witness, expected)
        
        metadata = {
            'description': f'Proof #{i+1} in chain',
            'step': i + 1
        }
        proofs_with_vks.append((proof, vk, metadata))
    
    # Create chain in IPFS
    bridge = ZKPIPFSBridge()
    chain_cids = bridge.create_proof_chain(proofs_with_vks)
    
    print(f"\n✓ Created proof chain with {len(chain_cids)} proofs")
    for i, cid in enumerate(chain_cids):
        print(f"  Proof {i+1}: {cid}")
    
    # Verify chain integrity
    print(f"\n✓ Verifying chain integrity...")
    for i, cid in enumerate(chain_cids):
        package = bridge.retrieve_proof(cid)
        metadata = package['metadata']
        
        # Check chain index
        assert metadata['chain_index'] == i, f"Chain index mismatch at {i}"
        
        # Check previous reference (except first)
        if i > 0:
            assert metadata['previous_cid'] == chain_cids[i-1], f"Chain broken at {i}"
        
        print(f"  ✓ Proof {i+1} chain link verified")
    
    print(f"\n✓ Complete chain verified!")


def demo_distributed_verification():
    """Demo 3: Distributed proof verification."""
    print("\n" + "="*60)
    print("Demo 3: Distributed Proof Verification")
    print("="*60)
    
    # Prover generates proof
    print("\n[Prover] Generating proof...")
    circuit = BooleanCircuit()
    w1, w2, w3 = [circuit.add_wire() for _ in range(3)]
    circuit.add_gate('OR', [w1, w2], w3)
    circuit.set_private_input(w1)
    circuit.set_private_input(w2)
    circuit.set_public_input(w3)
    
    prover = ZKPProver(circuit)
    witness = {w1: True, w2: False}
    proof = prover.generate_proof(witness, [True])
    vk = prover.get_verification_key()
    
    # Prover stores in IPFS
    bridge = ZKPIPFSBridge()
    cid = bridge.store_proof(proof, vk, {'prover': 'Alice'})
    print(f"  Stored at CID: {cid}")
    
    # Share CID with verifiers (Bob and Charlie)
    print(f"\n[Prover] Sharing CID with verifiers: {cid}")
    
    # Bob verifies
    print("\n[Verifier Bob] Retrieving and verifying...")
    bob_bridge = ZKPIPFSBridge(bridge.ipfs)  # Same IPFS network
    bob_valid = bob_bridge.verify_from_ipfs(cid, [True])
    print(f"  Bob's verification: {'✓ Valid' if bob_valid else '✗ Invalid'}")
    
    # Charlie verifies
    print("\n[Verifier Charlie] Retrieving and verifying...")
    charlie_bridge = ZKPIPFSBridge(bridge.ipfs)  # Same IPFS network
    charlie_valid = charlie_bridge.verify_from_ipfs(cid, [True])
    print(f"  Charlie's verification: {'✓ Valid' if charlie_valid else '✗ Invalid'}")
    
    print(f"\n✓ Distributed verification complete")
    print(f"✓ Multiple verifiers independently confirmed proof")


def demo_proof_metadata():
    """Demo 4: Rich metadata with proofs."""
    print("\n" + "="*60)
    print("Demo 4: Proof Metadata and Search")
    print("="*60)
    
    # Create proofs with rich metadata
    circuit = BooleanCircuit()
    w1, w2, w3 = [circuit.add_wire() for _ in range(3)]
    circuit.add_gate('AND', [w1, w2], w3)
    circuit.set_private_input(w1)
    circuit.set_private_input(w2)
    circuit.set_public_input(w3)
    
    prover = ZKPProver(circuit)
    vk = prover.get_verification_key()
    bridge = ZKPIPFSBridge()
    
    # Store proofs with different metadata
    proof_database = []
    for i in range(3):
        witness = {w1: True, w2: True}
        proof = prover.generate_proof(witness, [True])
        
        metadata = {
            'prover': f'User{i+1}',
            'purpose': ['compliance', 'audit', 'verification'][i],
            'timestamp': f'2026-02-18T{i:02d}:00:00Z',
            'tags': ['important', 'reviewed'] if i == 1 else ['standard']
        }
        
        cid = bridge.store_proof(proof, vk, metadata)
        proof_database.append((cid, metadata))
    
    print(f"\n✓ Stored {len(proof_database)} proofs with metadata")
    
    # Search by metadata
    print(f"\nSearching for proofs with 'compliance' purpose:")
    for cid, metadata in proof_database:
        if metadata['purpose'] == 'compliance':
            print(f"  Found: {cid}")
            print(f"    Prover: {metadata['prover']}")
            print(f"    Time: {metadata['timestamp']}")
    
    print(f"\nSearching for proofs with 'reviewed' tag:")
    for cid, metadata in proof_database:
        if 'reviewed' in metadata['tags']:
            print(f"  Found: {cid}")
            print(f"    Prover: {metadata['prover']}")
            print(f"    Purpose: {metadata['purpose']}")


def demo_best_practices():
    """Demo 5: Best practices for ZKP+IPFS."""
    print("\n" + "="*60)
    print("Demo 5: Best Practices")
    print("="*60)
    
    print("\n✓ Best Practices for ZKP + IPFS Integration:")
    print("\n1. Always include verification key with proof")
    print("   • Enables anyone to verify")
    print("   • No trust in storage layer needed")
    
    print("\n2. Add rich metadata")
    print("   • Prover identity")
    print("   • Timestamp")
    print("   • Purpose/context")
    print("   • Tags for searchability")
    
    print("\n3. Use proof chains for related proofs")
    print("   • Link proofs with CID references")
    print("   • Maintain verifiable history")
    print("   • Enable audit trails")
    
    print("\n4. Pin important proofs")
    print("   • Ensure availability")
    print("   • Prevent garbage collection")
    print("   • Use pinning services for critical proofs")
    
    print("\n5. Verify locally before trusting")
    print("   • Don't trust IPFS content blindly")
    print("   • Always verify proof after retrieval")
    print("   • Check metadata matches expectations")


def main():
    """Run all IPFS integration demos."""
    print("\n" + "="*60)
    print("ZKP + IPFS INTEGRATION DEMO")
    print("="*60)
    print("\n⚠️  WARNING: Educational simulation only!")
    print("   • ZKP module is not cryptographically secure")
    print("   • Using mock IPFS (no actual IPFS connection)")
    print("   • For demonstration purposes only")
    
    # Run demos
    demo_basic_storage()
    demo_proof_chain()
    demo_distributed_verification()
    demo_proof_metadata()
    demo_best_practices()
    
    print("\n" + "="*60)
    print("IPFS Integration Demos Complete!")
    print("="*60)
    print("\nKey takeaways:")
    print("  • ZKP proofs can be stored immutably in IPFS")
    print("  • Verification keys enable trustless verification")
    print("  • Proof chains create verifiable audit trails")
    print("  • Rich metadata enables search and organization")
    print("  • Best practices ensure reliability")
    
    print("\nFor production:")
    print("  • Use real IPFS client (ipfshttpclient)")
    print("  • Use real cryptographic ZKP library")
    print("  • See PRODUCTION_UPGRADE_PATH.md")
    print("  • Consider pinning services (Pinata, Web3.Storage)")


if __name__ == '__main__':
    main()
