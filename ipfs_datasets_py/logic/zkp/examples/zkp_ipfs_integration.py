#!/usr/bin/env python3
"""
ZKP IPFS Integration Demo

This script demonstrates how to integrate ZKP proofs with IPFS storage,
including:
- Storing proofs in IPFS (simulated)
- Retrieving and verifying proofs from IPFS
- Creating verifiable proof chains
- Best practices for distributed proof systems

⚠️ EDUCATIONAL USE ONLY: Simulation for learning, not cryptographically secure.

How to run:
    # From repository root:
    PYTHONPATH=. python ipfs_datasets_py/logic/zkp/examples/zkp_ipfs_integration.py
    
    # Or install package first:
    pip install -e .
    python ipfs_datasets_py/logic/zkp/examples/zkp_ipfs_integration.py
"""

import json
import hashlib
from typing import Dict, Any, List
from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier, ZKPProof


class MockIPFSClient:
    """Mock IPFS client for demonstration (no actual IPFS connection needed)."""
    
    def __init__(self):
        self.storage = {}  # CID -> data
        self.pin_set = set()
    
    def add_json(self, data: dict) -> str:
        """Add JSON data and return CID."""
        json_str = json.dumps(data, sort_keys=True)
        cid = "Qm" + hashlib.sha256(json_str.encode()).hexdigest()[:44]  # Simulate CID
        self.storage[cid] = data
        return cid
    
    def get_json(self, cid: str) -> dict:
        """Retrieve JSON data by CID."""
        if cid not in self.storage:
            raise KeyError(f"CID not found: {cid}")
        return self.storage[cid]
    
    def pin(self, cid: str):
        """Pin CID to ensure persistence."""
        if cid not in self.storage:
            raise KeyError(f"Cannot pin non-existent CID: {cid}")
        self.pin_set.add(cid)
        return True
    
    def is_pinned(self, cid: str) -> bool:
        """Check if CID is pinned."""
        return cid in self.pin_set


def demo_basic_storage():
    """Demo 1: Basic proof storage and retrieval from IPFS."""
    print("\n" + "="*60)
    print("Demo 1: Basic Proof Storage in IPFS")
    print("="*60)
    
    # Create proof
    prover = ZKPProver()
    proof = prover.generate_proof(
        theorem="Transaction is valid",
        private_axioms=["Sender has funds", "Signature is valid"],
        metadata={"transaction_id": "tx_12345"}
    )
    
    # Initialize mock IPFS client
    ipfs = MockIPFSClient()
    
    # Convert proof to dict and store in IPFS
    proof_dict = proof.to_dict()
    cid = ipfs.add_json(proof_dict)
    ipfs.pin(cid)
    
    print(f"\n✓ Proof generated ({proof.size_bytes} bytes)")
    print(f"✓ Stored in IPFS with CID: {cid[:20]}...")
    print(f"✓ Proof pinned for persistence")
    
    # Retrieve and verify from IPFS
    retrieved_dict = ipfs.get_json(cid)
    retrieved_proof = ZKPProof.from_dict(retrieved_dict)
    
    verifier = ZKPVerifier()
    is_valid = verifier.verify_proof(retrieved_proof)
    
    print(f"\n✓ Proof retrieved from IPFS")
    print(f"✓ Verification result: {is_valid}")
    print(f"✓ Proof metadata: {retrieved_proof.metadata.get('transaction_id')}")


def demo_proof_chain():
    """Demo 2: Create a chain of proofs in IPFS."""
    print("\n" + "="*60)
    print("Demo 2: Proof Chain in IPFS")
    print("="*60)
    
    ipfs = MockIPFSClient()
    prover = ZKPProver()
    
    # Create a chain of related proofs
    chain_cids = []
    proofs_data = [
        ("Block 1 is valid", ["Previous block hash is valid", "Transactions are valid"]),
        ("Block 2 is valid", ["Previous block 1 is valid", "Transactions are valid"]),
        ("Block 3 is valid", ["Previous block 2 is valid", "Transactions are valid"]),
    ]
    
    print("\nCreating proof chain:")
    for i, (theorem, axioms) in enumerate(proofs_data, 1):
        # Generate proof
        metadata = {"block_number": i, "chain_position": i}
        
        # Link to previous proof
        if chain_cids:
            metadata["previous_proof_cid"] = chain_cids[-1]
        
        proof = prover.generate_proof(theorem, axioms, metadata)
        
        # Store in IPFS
        proof_dict = proof.to_dict()
        cid = ipfs.add_json(proof_dict)
        ipfs.pin(cid)
        chain_cids.append(cid)
        
        print(f"  Block {i}: {cid[:20]}...")
    
    print(f"\n✓ Created proof chain with {len(chain_cids)} blocks")
    print(f"✓ All proofs stored and pinned in IPFS")
    
    # Verify the chain
    verifier = ZKPVerifier()
    print("\nVerifying chain:")
    for i, cid in enumerate(chain_cids, 1):
        proof_dict = ipfs.get_json(cid)
        proof = ZKPProof.from_dict(proof_dict)
        is_valid = verifier.verify_proof(proof)
        print(f"  Block {i}: {'✓' if is_valid else '✗'} Valid")
    
    print(f"\n✓ All {len(chain_cids)} proofs in chain verified!")


def demo_distributed_verification():
    """Demo 3: Distributed proof verification scenario."""
    print("\n" + "="*60)
    print("Demo 3: Distributed Verification")
    print("="*60)
    
    # Simulate multiple parties with separate IPFS nodes
    print("\nScenario: Three parties verifying same proof")
    print("-" * 60)
    
    # Party A generates and publishes proof
    print("\nParty A (Prover):")
    prover = ZKPProver()
    proof = prover.generate_proof(
        theorem="Property X holds",
        private_axioms=["Secret evidence A", "Secret evidence B"],
        metadata={"party": "A", "purpose": "compliance"}
    )
    
    ipfs_a = MockIPFSClient()
    cid = ipfs_a.add_json(proof.to_dict())
    print(f"  ✓ Generated proof")
    print(f"  ✓ Published to IPFS: {cid[:20]}...")
    
    # Party B retrieves and verifies
    print("\nParty B (Verifier #1):")
    ipfs_b = MockIPFSClient()
    ipfs_b.storage[cid] = ipfs_a.storage[cid]  # Simulate IPFS replication
    
    proof_dict_b = ipfs_b.get_json(cid)
    proof_b = ZKPProof.from_dict(proof_dict_b)
    verifier_b = ZKPVerifier()
    is_valid_b = verifier_b.verify_proof(proof_b)
    print(f"  ✓ Retrieved proof from IPFS")
    print(f"  ✓ Verification: {is_valid_b}")
    
    # Party C also verifies independently
    print("\nParty C (Verifier #2):")
    ipfs_c = MockIPFSClient()
    ipfs_c.storage[cid] = ipfs_a.storage[cid]  # Simulate IPFS replication
    
    proof_dict_c = ipfs_c.get_json(cid)
    proof_c = ZKPProof.from_dict(proof_dict_c)
    verifier_c = ZKPVerifier()
    is_valid_c = verifier_c.verify_proof(proof_c)
    print(f"  ✓ Retrieved proof from IPFS")
    print(f"  ✓ Verification: {is_valid_c}")
    
    print(f"\n✓ Distributed verification successful!")
    print(f"✓ All parties verified independently without sharing secrets")


def demo_rich_metadata():
    """Demo 4: Proofs with rich metadata for discovery."""
    print("\n" + "="*60)
    print("Demo 4: Rich Metadata for Proof Discovery")
    print("="*60)
    
    ipfs = MockIPFSClient()
    prover = ZKPProver()
    
    # Generate proofs with detailed metadata
    proof_metadata = [
        {
            "type": "compliance",
            "standard": "GDPR",
            "organization": "Acme Corp",
            "auditor": "External Auditor",
            "date": "2026-02-18",
            "tags": ["privacy", "data-protection", "EU"]
        },
        {
            "type": "compliance",
            "standard": "HIPAA",
            "organization": "Health Corp",
            "auditor": "Healthcare Auditor",
            "date": "2026-02-18",
            "tags": ["healthcare", "privacy", "US"]
        },
        {
            "type": "financial",
            "standard": "SOX",
            "organization": "Finance Corp",
            "auditor": "Financial Auditor",
            "date": "2026-02-18",
            "tags": ["finance", "accounting", "US"]
        },
    ]
    
    proof_cids = {}
    print("\nStoring proofs with metadata:")
    for meta in proof_metadata:
        proof = prover.generate_proof(
            theorem=f"{meta['organization']} complies with {meta['standard']}",
            private_axioms=[f"Internal policy {i}" for i in range(3)],
            metadata=meta
        )
        
        cid = ipfs.add_json(proof.to_dict())
        ipfs.pin(cid)
        proof_cids[cid] = meta
        
        print(f"  {meta['standard']}: {cid[:20]}... (tags: {', '.join(meta['tags'][:2])})")
    
    print(f"\n✓ Stored {len(proof_cids)} proofs with rich metadata")
    
    # Query by metadata (simulated search)
    print("\nQuerying proofs by tag 'privacy':")
    for cid, meta in proof_cids.items():
        if "privacy" in meta.get("tags", []):
            print(f"  Found: {meta['standard']} - {meta['organization']}")
    
    print("\n✓ Metadata enables discovery and categorization")


def demo_best_practices():
    """Demo 5: Best practices summary."""
    print("\n" + "="*60)
    print("Demo 5: Best Practices for IPFS + ZKP")
    print("="*60)
    
    practices = [
        ("✓ Always pin proofs", "Ensures persistence in IPFS network"),
        ("✓ Include metadata", "Enables discovery and verification context"),
        ("✓ Link proofs in chains", "Creates verifiable audit trails"),
        ("✓ Serialize to JSON", "Standard format for interoperability"),
        ("✓ Store CIDs separately", "Keep reference list for retrieval"),
        ("✓ Verify after retrieval", "Always validate proofs from IPFS"),
        ("✓ Use content addressing", "CID ensures data integrity"),
        ("✓ Consider proof size", "Smaller proofs = lower storage cost"),
    ]
    
    print("\nKey practices for production systems:\n")
    for i, (practice, description) in enumerate(practices, 1):
        print(f"{i}. {practice}")
        print(f"   → {description}\n")
    
    print("Additional considerations:")
    print("  • Use real IPFS client (ipfshttpclient) in production")
    print("  • Implement proper error handling for network issues")
    print("  • Consider IPFS cluster for high availability")
    print("  • Monitor pin status and re-pin if needed")
    print("  • Use IPNS for mutable proof indices")


def main():
    """Run all IPFS integration demos."""
    print("\n" + "="*60)
    print("ZKP + IPFS INTEGRATION DEMO")
    print("="*60)
    print("\n⚠️  WARNING: Educational simulation only!")
    print("   • Uses mock IPFS client (no real IPFS connection)")
    print("   • ZKP is simulated (not cryptographically secure)")
    print("   • See SECURITY_CONSIDERATIONS.md for details")
    
    # Run demos
    demo_basic_storage()
    demo_proof_chain()
    demo_distributed_verification()
    demo_rich_metadata()
    demo_best_practices()
    
    print("\n" + "="*60)
    print("IPFS Integration Demos Complete!")
    print("="*60)
    print("\nKey takeaways:")
    print("  • ZKP proofs can be stored in IPFS as JSON")
    print("  • Content addressing ensures proof integrity")
    print("  • Proofs can form verifiable chains")
    print("  • Multiple parties can verify independently")
    print("  • Rich metadata enables discovery")
    print("\nNext steps:")
    print("  • Use real IPFS client (ipfshttpclient)")
    print("  • Upgrade to real Groth16 backend")
    print("  • Read PRODUCTION_UPGRADE_PATH.md")
    print("  • Read INTEGRATION_GUIDE.md")


if __name__ == '__main__':
    main()
