.. _tutorial-proving-basics:

Proving Basics
==============

Learn the fundamentals of theorem proving with TDFOL.

Proof Strategies
----------------

TDFOL supports multiple proving strategies:

Resolution
^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL import TDFOLProver
    from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofStrategy
    
    prover = TDFOLProver(kb, strategy=ProofStrategy.RESOLUTION)
    result = prover.prove(theorem)

Natural Deduction
^^^^^^^^^^^^^^^^^

.. code-block:: python

    prover = TDFOLProver(kb, strategy=ProofStrategy.NATURAL_DEDUCTION)
    result = prover.prove(theorem)

Tableaux
^^^^^^^^

.. code-block:: python

    prover = TDFOLProver(kb, strategy=ProofStrategy.TABLEAUX)
    result = prover.prove(theorem)

Understanding Proof Results
---------------------------

.. code-block:: python

    result = prover.prove("Mortal(Socrates)")
    
    if result.is_valid:
        print(f"✓ Theorem proved!")
        print(f"Depth: {result.depth}")
        print(f"Steps: {len(result.proof_steps)}")
        print(f"Time: {result.time_elapsed:.3f}s")
        
        # Display proof tree
        print("\nProof Tree:")
        print(result.proof_tree)
    else:
        print("✗ Theorem not proved")
        if result.countermodel:
            print("Countermodel:", result.countermodel)

Common Proving Patterns
-----------------------

Modus Ponens
^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    kb.add_axiom("P")
    kb.add_axiom("P → Q")
    
    prover = TDFOLProver(kb)
    result = prover.prove("Q")  # ✓ Valid

Universal Instantiation
^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    kb.add_axiom("∀x(Person(x) → Mortal(x))")
    kb.add_axiom("Person(Socrates)")
    
    prover = TDFOLProver(kb)
    result = prover.prove("Mortal(Socrates)")  # ✓ Valid

Existential Introduction
^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    kb.add_axiom("Happy(Alice)")
    
    prover = TDFOLProver(kb)
    result = prover.prove("∃x(Happy(x))")  # ✓ Valid

See Also
--------

- :ref:`tutorial-advanced-proving` - Advanced proving techniques
- :ref:`api-prover` - Prover API reference
