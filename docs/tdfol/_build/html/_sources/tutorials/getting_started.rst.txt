.. _tutorial-getting-started:

Getting Started with TDFOL
===========================

Welcome to TDFOL! This tutorial will help you get started with temporal, deontic, and first-order logic reasoning.

What is TDFOL?
--------------

TDFOL combines three powerful logical systems:

1. **First-Order Logic (FOL)**: Reason about objects, properties, and relations
2. **Temporal Logic**: Reason about time and sequences
3. **Deontic Logic**: Reason about obligations, permissions, and prohibitions

Installation
------------

TDFOL is part of the IPFS Datasets Python package:

.. code-block:: bash

    pip install ipfs-datasets-py
    
    # Or install from source
    git clone https://github.com/ipfs-datasets/ipfs_datasets_py.git
    cd ipfs_datasets_py
    pip install -e .

Quick Start
-----------

Let's prove a simple theorem:

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL import TDFOLProver, KnowledgeBase
    
    # Create a knowledge base
    kb = KnowledgeBase()
    kb.add_axiom("∀x(Person(x) → Mortal(x))")
    kb.add_axiom("Person(Socrates)")
    
    # Create a prover
    prover = TDFOLProver(kb)
    
    # Prove a theorem
    result = prover.prove("Mortal(Socrates)")
    
    if result.is_valid:
        print("✓ Proof found!")
        print(f"  Steps: {len(result.proof_steps)}")
        print(f"  Time: {result.time_elapsed:.3f}s")
    else:
        print("✗ Proof not found")

Understanding the Result
------------------------

The `ProofResult` object contains:

- **is_valid**: Whether the theorem was proved
- **proof_steps**: List of steps in the proof
- **proof_tree**: Tree structure of the proof
- **time_elapsed**: Time taken to find the proof

.. code-block:: python

    if result.is_valid:
        # Print each proof step
        for i, step in enumerate(result.proof_steps):
            print(f"Step {i+1}: {step.rule}")
            print(f"  Formula: {step.formula}")
            print(f"  Justification: {step.justification}")

Exploring Formula Types
-----------------------

First-Order Logic
^^^^^^^^^^^^^^^^^

.. code-block:: python

    # Universal quantification
    kb.add_axiom("∀x(Dog(x) → Animal(x))")
    
    # Existential quantification
    kb.add_axiom("∃x(Dog(x) ∧ Friendly(x))")
    
    # Relations
    kb.add_axiom("∀x∀y(Parent(x, y) → Ancestor(x, y))")

Temporal Logic
^^^^^^^^^^^^^^

.. code-block:: python

    # Always (□)
    kb.add_axiom("□(Safe(system))")
    
    # Eventually (◊)
    kb.add_axiom("◊(Complete(task))")
    
    # Next (X)
    kb.add_axiom("Request(user) → X(Response(server))")

Deontic Logic
^^^^^^^^^^^^^

.. code-block:: python

    # Obligation (O)
    kb.add_axiom("O(Report(employee))")
    
    # Permission (P)
    kb.add_axiom("P(Leave(employee))")
    
    # Prohibition (F)
    kb.add_axiom("F(Steal(person))")

Next Steps
----------

- :ref:`tutorial-formula-syntax` - Learn the complete formula syntax
- :ref:`tutorial-proving-basics` - Deep dive into theorem proving
- :ref:`examples-basic` - See more examples

Common Patterns
---------------

Pattern 1: All/Some Reasoning
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    kb.add_axiom("∀x(Student(x) → Person(x))")
    kb.add_axiom("∀x(Person(x) → Mortal(x))")
    kb.add_axiom("Student(Alice)")
    
    prover = TDFOLProver(kb)
    result = prover.prove("Mortal(Alice)")  # ✓ Valid

Pattern 2: Temporal Sequences
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    kb.add_axiom("□(Request → X(Process))")
    kb.add_axiom("□(Process → X(Complete))")
    kb.add_axiom("Request")
    
    prover = TDFOLProver(kb)
    result = prover.prove("X(X(Complete))")  # ✓ Valid

Pattern 3: Obligations and Permissions
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    kb.add_axiom("∀x(Employee(x) → O(Report(x)))")
    kb.add_axiom("O(Report(Alice))")
    kb.add_axiom("Employee(Alice)")
    
    prover = TDFOLProver(kb)
    result = prover.prove("O(Report(Alice))")  # ✓ Valid

Troubleshooting
---------------

Proof Not Found?
^^^^^^^^^^^^^^^^

If your proof isn't found:

1. Check axiom syntax
2. Verify the theorem is actually valid
3. Increase the timeout
4. Try a different proof strategy

.. code-block:: python

    # Increase timeout
    prover = TDFOLProver(kb, timeout=30.0)
    
    # Try different strategy
    from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofStrategy
    prover = TDFOLProver(kb, strategy=ProofStrategy.TABLEAUX)

Performance Issues?
^^^^^^^^^^^^^^^^^^^

For large knowledge bases:

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.tdfol_optimization import OptimizedProver
    
    prover = OptimizedProver(kb, cache_size=1000)
    result = prover.prove(theorem)

Resources
---------

- **API Documentation**: :ref:`api-reference`
- **Examples**: :ref:`examples`
- **GitHub**: https://github.com/ipfs-datasets/ipfs_datasets_py
- **Issues**: https://github.com/ipfs-datasets/ipfs_datasets_py/issues
