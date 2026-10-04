Quick Start
===========

See :ref:`tutorial-getting-started` for a comprehensive quick start guide.

5-Minute Tutorial
-----------------

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL import TDFOLProver, KnowledgeBase
    
    # 1. Create knowledge base
    kb = KnowledgeBase()
    kb.add_axiom("∀x(Person(x) → Mortal(x))")
    kb.add_axiom("Person(Socrates)")
    
    # 2. Create prover
    prover = TDFOLProver(kb)
    
    # 3. Prove theorem
    result = prover.prove("Mortal(Socrates)")
    print(f"Valid: {result.is_valid}")
