.. _api-prover:

Prover Module (tdfol_prover.py)
================================

The prover module implements theorem proving algorithms for TDFOL formulas.

.. automodule:: ipfs_datasets_py.logic.TDFOL.tdfol_prover
   :members:
   :undoc-members:
   :show-inheritance:

Overview
--------

The prover module provides:

- **TDFOLProver**: Main theorem proving engine
- **ProofResult**: Structured proof results with metadata
- **ProofStep**: Individual steps in a proof
- **Resolution**: Resolution-based theorem proving
- **Natural Deduction**: Natural deduction proof system

Key Classes
-----------

TDFOLProver
^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_prover.TDFOLProver
   :members:
   :undoc-members:
   :show-inheritance:

ProofResult
^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_prover.ProofResult
   :members:
   :undoc-members:
   :show-inheritance:

ProofStep
^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_prover.ProofStep
   :members:
   :undoc-members:
   :show-inheritance:

ProofStrategy
^^^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_prover.ProofStrategy
   :members:
   :undoc-members:
   :show-inheritance:

Usage Examples
--------------

Basic Theorem Proving
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL import TDFOLProver, KnowledgeBase
    
    # Create knowledge base with axioms
    kb = KnowledgeBase()
    kb.add_axiom("∀x(Person(x) → Mortal(x))")
    kb.add_axiom("Person(Socrates)")
    
    # Create prover
    prover = TDFOLProver(kb)
    
    # Prove a theorem
    result = prover.prove("Mortal(Socrates)")
    
    if result.is_valid:
        print("Proof found!")
        print(f"Proof steps: {len(result.proof_steps)}")
        print(f"Time taken: {result.time_elapsed:.3f}s")
        
        # Display proof tree
        for step in result.proof_steps:
            print(f"{step.rule}: {step.formula}")

Proving with Timeout
^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL import TDFOLProver
    
    prover = TDFOLProver(kb, timeout=5.0)  # 5 second timeout
    
    try:
        result = prover.prove("ComplexFormula(x, y, z)")
        if result.is_valid:
            print("Proof found within timeout!")
    except TimeoutError:
        print("Proof search timed out")

Using Different Proof Strategies
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.tdfol_prover import (
        TDFOLProver, ProofStrategy
    )
    
    # Resolution-based proving
    prover_resolution = TDFOLProver(
        kb, 
        strategy=ProofStrategy.RESOLUTION
    )
    result1 = prover_resolution.prove(theorem)
    
    # Tableaux-based proving
    prover_tableaux = TDFOLProver(
        kb,
        strategy=ProofStrategy.TABLEAUX
    )
    result2 = prover_tableaux.prove(theorem)
    
    # Natural deduction
    prover_nd = TDFOLProver(
        kb,
        strategy=ProofStrategy.NATURAL_DEDUCTION
    )
    result3 = prover_nd.prove(theorem)

Analyzing Proof Results
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    result = prover.prove("∀x(P(x) → Q(x))")
    
    if result.is_valid:
        # Get proof statistics
        print(f"Proof depth: {result.depth}")
        print(f"Number of steps: {len(result.proof_steps)}")
        print(f"Rules used: {result.rules_used}")
        print(f"Time elapsed: {result.time_elapsed:.4f}s")
        
        # Get the proof tree as a string
        print(result.proof_tree)
        
        # Export proof in various formats
        latex_proof = result.to_latex()
        json_proof = result.to_json()
        dot_graph = result.to_dot()

Batch Proving
^^^^^^^^^^^^^

.. code-block:: python

    theorems = [
        "Mortal(Socrates)",
        "∀x(Man(x) → Mortal(x))",
        "∃x(Philosopher(x) ∧ Greek(x))"
    ]
    
    results = []
    for theorem in theorems:
        result = prover.prove(theorem)
        results.append({
            'theorem': theorem,
            'valid': result.is_valid,
            'time': result.time_elapsed
        })
    
    # Print summary
    valid_count = sum(1 for r in results if r['valid'])
    print(f"Proved {valid_count}/{len(theorems)} theorems")

Proving Modal Formulas
^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL import TDFOLProver, KnowledgeBase
    
    kb = KnowledgeBase()
    kb.add_axiom("□(Safe(x) → ◊Action(x))")
    kb.add_axiom("Safe(agent1)")
    
    prover = TDFOLProver(kb, modal_logic="K")
    result = prover.prove("◊Action(agent1)")
    
    if result.is_valid:
        print("Modal proof found!")
        print(result.modal_worlds)  # Show possible worlds used

Proving Temporal Formulas
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    kb.add_axiom("□(Request(x) → X(Response(x)))")
    kb.add_axiom("Request(req1)")
    
    prover = TDFOLProver(kb, temporal_logic="LTL")
    result = prover.prove("X(Response(req1))")
    
    if result.is_valid:
        print("Temporal proof found!")
        print(result.temporal_trace)  # Show temporal sequence

Proving Deontic Formulas
^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    kb.add_axiom("∀x(Employee(x) → O(Report(x)))")
    kb.add_axiom("Employee(Alice)")
    
    prover = TDFOLProver(kb, deontic_logic="SDL")
    result = prover.prove("O(Report(Alice))")
    
    if result.is_valid:
        print("Deontic obligation proved!")
        print(result.deontic_obligations)

Interactive Proving
^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    prover = TDFOLProver(kb, interactive=True)
    
    # Start an interactive proof session
    session = prover.start_session("∀x(P(x) → Q(x))")
    
    # Apply rules step by step
    session.apply_rule("universal_instantiation", {"var": "x", "term": "a"})
    session.apply_rule("modus_ponens", {"premises": ["P(a)", "P(a) → Q(a)"]})
    
    # Check if proof is complete
    if session.is_complete():
        result = session.get_result()
        print("Interactive proof completed!")

Proof Debugging
^^^^^^^^^^^^^^^

.. code-block:: python

    prover = TDFOLProver(kb, debug=True, verbose=True)
    
    result = prover.prove("ComplexTheorem(x, y)")
    
    if not result.is_valid:
        # Analyze why proof failed
        print("Proof failed. Debug info:")
        print(f"Attempted strategies: {result.attempted_strategies}")
        print(f"Explored nodes: {result.nodes_explored}")
        print(f"Dead ends: {result.dead_ends}")
        
        # Get countermodel if available
        if result.countermodel:
            print("Countermodel found:")
            print(result.countermodel)

See Also
--------

- :ref:`api-optimization` - Optimized proving with caching and indexing
- :ref:`api-modal-tableaux` - Modal logic tableaux proving
- :ref:`api-proof-explainer` - Human-readable proof explanations
