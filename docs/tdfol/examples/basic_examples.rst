.. _examples-basic:

Basic Examples
==============

Simple Proofs
-------------

Example 1: Syllogism
^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL import TDFOLProver, KnowledgeBase
    
    kb = KnowledgeBase()
    kb.add_axiom("∀x(Person(x) → Mortal(x))")
    kb.add_axiom("Person(Socrates)")
    
    prover = TDFOLProver(kb)
    result = prover.prove("Mortal(Socrates)")
    
    print(f"Valid: {result.is_valid}")

Example 2: Transitive Relations
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    kb.add_axiom("∀x∀y∀z((Ancestor(x,y) ∧ Ancestor(y,z)) → Ancestor(x,z))")
    kb.add_axiom("Ancestor(Alice, Bob)")
    kb.add_axiom("Ancestor(Bob, Carol)")
    
    prover = TDFOLProver(kb)
    result = prover.prove("Ancestor(Alice, Carol)")
    
    print(f"Valid: {result.is_valid}")

Example 3: Properties
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    kb.add_axiom("∀x(Dog(x) → Animal(x))")
    kb.add_axiom("∀x(Animal(x) → LivingThing(x))")
    kb.add_axiom("Dog(Fido)")
    
    prover = TDFOLProver(kb)
    result = prover.prove("LivingThing(Fido)")
    
    print(f"Valid: {result.is_valid}")

Temporal Examples
-----------------

Example 4: Always True
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    kb.add_axiom("□(Safe(system))")
    
    prover = TDFOLProver(kb)
    result = prover.prove("Safe(system)")
    
    print(f"Valid: {result.is_valid}")

Example 5: Eventually
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    kb.add_axiom("□(Request → ◊Response)")
    kb.add_axiom("Request")
    
    prover = TDFOLProver(kb)
    result = prover.prove("◊Response")
    
    print(f"Valid: {result.is_valid}")

Deontic Examples
----------------

Example 6: Obligations
^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    kb.add_axiom("∀x(Employee(x) → O(Report(x)))")
    kb.add_axiom("Employee(Alice)")
    
    prover = TDFOLProver(kb)
    result = prover.prove("O(Report(Alice))")
    
    print(f"Valid: {result.is_valid}")

Example 7: Permissions
^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    kb.add_axiom("O(P) → P(P)")  # Obligations imply permissions
    kb.add_axiom("O(Report(Bob))")
    
    prover = TDFOLProver(kb)
    result = prover.prove("P(Report(Bob))")
    
    print(f"Valid: {result.is_valid}")

Complete Examples
-----------------

Example 8: Employee System
^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    
    # Rules
    kb.add_axiom("∀x(Employee(x) → Person(x))")
    kb.add_axiom("∀x(Manager(x) → Employee(x))")
    kb.add_axiom("∀x(Employee(x) → O(Report(x)))")
    kb.add_axiom("∀x(Manager(x) → O(Review(x)))")
    
    # Facts
    kb.add_axiom("Manager(Alice)")
    
    prover = TDFOLProver(kb)
    
    # Test various theorems
    tests = [
        "Person(Alice)",
        "Employee(Alice)",
        "O(Report(Alice))",
        "O(Review(Alice))"
    ]
    
    for theorem in tests:
        result = prover.prove(theorem)
        print(f"{theorem}: {'✓' if result.is_valid else '✗'}")

Example 9: Safety System
^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    
    # Temporal safety properties
    kb.add_axiom("□(Error → X(Handle))")
    kb.add_axiom("□(Handle → X(Resolved))")
    kb.add_axiom("Error")
    
    prover = TDFOLProver(kb)
    
    # Prove properties
    assert prover.prove("X(Handle)").is_valid
    assert prover.prove("X(X(Resolved))").is_valid

Example 10: Legal System
^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    
    # Legal rules
    kb.add_axiom("∀x(Citizen(x) → P(Vote(x)))")        # Citizens may vote
    kb.add_axiom("∀x(Minor(x) → F(Vote(x)))")          # Minors forbidden
    kb.add_axiom("∀x(Citizen(x) → O(PayTaxes(x)))")   # Citizens must pay taxes
    
    # Facts
    kb.add_axiom("Citizen(Bob)")
    kb.add_axiom("¬Minor(Bob)")
    
    prover = TDFOLProver(kb)
    
    # Test legal conclusions
    assert prover.prove("P(Vote(Bob))").is_valid
    assert prover.prove("O(PayTaxes(Bob))").is_valid

See Also
--------

- :ref:`tutorial-getting-started` - Getting started guide
- :ref:`examples-modal` - Modal logic examples
- :ref:`examples-temporal` - Temporal logic examples
