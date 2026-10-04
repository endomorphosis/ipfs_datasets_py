"""
TDFOL P2P Distributed Proving Layer

This package provides P2P distributed proving capabilities for TDFOL using:
- IPFS for distributed proof storage and caching
- TaskQueue (MCP++) for distributed task execution
- Docker-based worker nodes for parallel proving

Modules:
- ipfs_proof_storage: IPFS-based proof caching
- distributed_prover: TaskQueue-based distributed proving
- p2p_knowledge_base: Distributed knowledge base management

Architecture:
    Client → DistributedProver → TaskQueue.submit()
        ↓
    Worker Node (Docker) → TDFOLProver.prove()
        ↓
    IPFSProofStorage.store_proof() → CID
        ↓
    Data backplane (ipfs_kit_py)
        ↓
    Client ← IPFSProofStorage.retrieve_proof(cid)

Author: Phase 13 Week 2 Implementation
Date: 2026-02-18
"""

__all__ = [
    "IPFSProofStorage",
    "DistributedProver",
    "P2PKnowledgeBase",
]
