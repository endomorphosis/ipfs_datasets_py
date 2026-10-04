.. _api-zkp-integration:

Zero-Knowledge Proof Integration (zkp_integration.py)
======================================================

The ZKP integration module enables privacy-preserving theorem proving.

.. automodule:: ipfs_datasets_py.logic.TDFOL.zkp_integration
   :members:
   :undoc-members:
   :show-inheritance:

Overview
--------

Zero-knowledge proofs allow proving theorems without revealing:

- **Axioms**: Keep knowledge base private
- **Proof Steps**: Hide reasoning process  
- **Intermediate Results**: Protect sensitive data

The module supports:

- **ZK-SNARK**: Succinct non-interactive proofs
- **ZK-STARK**: Transparent proofs without trusted setup
- **Bulletproofs**: Efficient range proofs

Key Classes
-----------

ZKProver
^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.zkp_integration.ZKProver
   :members:
   :undoc-members:
   :show-inheritance:

ZKProof
^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.zkp_integration.ZKProof
   :members:
   :undoc-members:
   :show-inheritance:

Usage Examples
--------------

Creating a ZK Proof
^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.zkp_integration import ZKProver
    from ipfs_datasets_py.logic.TDFOL import KnowledgeBase
    
    # Private knowledge base
    kb = KnowledgeBase()
    kb.add_axiom("∀x(Employee(x) → Access(x, Database))")
    kb.add_axiom("Employee(Alice)")
    
    # Create ZK prover
    zk_prover = ZKProver(kb, proof_system="groth16")
    
    # Generate zero-knowledge proof
    theorem = "Access(Alice, Database)"
    zk_proof = zk_prover.prove(theorem)
    
    print(f"Proof size: {len(zk_proof.proof_bytes)} bytes")
    print(f"Public inputs: {zk_proof.public_inputs}")

Verifying a ZK Proof
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    # Verifier doesn't need the knowledge base
    from ipfs_datasets_py.logic.TDFOL.zkp_integration import ZKVerifier
    
    verifier = ZKVerifier(proof_system="groth16")
    
    is_valid = verifier.verify(
        proof=zk_proof,
        theorem="Access(Alice, Database)",
        public_key=zk_prover.public_key
    )
    
    if is_valid:
        print("Proof verified! Theorem is valid.")
        print("(But we learned nothing about the axioms)")

Using ZK-STARKs
^^^^^^^^^^^^^^^

.. code-block:: python

    # Transparent proofs (no trusted setup)
    zk_prover = ZKProver(kb, proof_system="stark")
    
    zk_proof = zk_prover.prove(theorem)
    
    # Verification without setup ceremony
    verifier = ZKVerifier(proof_system="stark")
    is_valid = verifier.verify(zk_proof, theorem)

Batch ZK Proving
^^^^^^^^^^^^^^^^

.. code-block:: python

    theorems = [
        "Access(Alice, Database)",
        "Access(Bob, Database)",
        "Access(Carol, Database)"
    ]
    
    # Generate batch proof (more efficient)
    batch_proof = zk_prover.prove_batch(theorems)
    
    # Verify batch
    is_valid = verifier.verify_batch(batch_proof, theorems)

See Also
--------

- :ref:`api-prover` - Standard theorem proving
- :ref:`examples-zkp` - Zero-knowledge proof examples
- :ref:`tutorials-security` - Security best practices
