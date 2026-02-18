.. _api-modal-tableaux:

Modal Tableaux Module (modal_tableaux.py)
==========================================

The modal tableaux module implements tableaux-based proving for modal, temporal, and deontic logics.

.. automodule:: ipfs_datasets_py.logic.TDFOL.modal_tableaux
   :members:
   :undoc-members:
   :show-inheritance:

Overview
--------

The modal tableaux module supports:

- **Modal Logic Systems**: K, T, S4, S5, and more
- **Temporal Logic**: LTL, CTL, CTL*
- **Deontic Logic**: SDL (Standard Deontic Logic)
- **Possible Worlds**: World-based semantics

Key Classes
-----------

ModalTableauxProver
^^^^^^^^^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.modal_tableaux.ModalTableauxProver
   :members:
   :undoc-members:
   :show-inheritance:

TableauxNode
^^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.modal_tableaux.TableauxNode
   :members:
   :undoc-members:
   :show-inheritance:

PossibleWorld
^^^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.modal_tableaux.PossibleWorld
   :members:
   :undoc-members:
   :show-inheritance:

Usage Examples
--------------

Proving Modal Logic K
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.modal_tableaux import ModalTableauxProver
    from ipfs_datasets_py.logic.TDFOL import KnowledgeBase
    
    kb = KnowledgeBase()
    kb.add_axiom("□(P → Q)")
    kb.add_axiom("□P")
    
    # Prove in modal logic K
    prover = ModalTableauxProver(kb, logic="K")
    result = prover.prove("□Q")
    
    if result.is_valid:
        print("Theorem is valid in K!")
        print(f"Worlds explored: {result.worlds_count}")

Proving Modal Logic S5
^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    kb.add_axiom("◊□P")
    
    prover = ModalTableauxProver(kb, logic="S5")
    result = prover.prove("□◊P")
    
    if result.is_valid:
        print("Valid in S5 (symmetric accessibility)")

Linear Temporal Logic (LTL)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    kb.add_axiom("□(Request → X(Response))")
    kb.add_axiom("Request")
    
    prover = ModalTableauxProver(kb, logic="LTL")
    result = prover.prove("X(Response)")
    
    if result.is_valid:
        print("LTL formula proved!")
        print(f"Temporal trace: {result.temporal_trace}")

Computation Tree Logic (CTL)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    kb.add_axiom("AG(Init → EF(Complete))")
    kb.add_axiom("Init")
    
    prover = ModalTableauxProver(kb, logic="CTL")
    result = prover.prove("EF(Complete)")
    
    if result.is_valid:
        print("CTL property holds!")
        print(f"Computation tree: {result.computation_tree}")

Deontic Logic (SDL)
^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    kb.add_axiom("O(Report)")
    kb.add_axiom("O(Report) → P(Report)")
    
    prover = ModalTableauxProver(kb, logic="SDL")
    result = prover.prove("P(Report)")
    
    if result.is_valid:
        print("Deontic obligation implies permission")

Multi-Modal Logic
^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    # Agent 1 knows P
    kb.add_axiom("K1(P)")
    # Agent 2 knows that Agent 1 knows P
    kb.add_axiom("K2(K1(P))")
    
    prover = ModalTableauxProver(kb, logic="multi-modal")
    result = prover.prove("K2(K1(P))")
    
    if result.is_valid:
        print("Nested knowledge proved!")

Countermodel Extraction
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    kb.add_axiom("◊P")
    
    prover = ModalTableauxProver(kb, logic="K")
    result = prover.prove("□P")  # This should fail
    
    if not result.is_valid:
        # Extract countermodel
        countermodel = result.countermodel
        print("Countermodel found:")
        print(f"Worlds: {countermodel.worlds}")
        print(f"Relations: {countermodel.relations}")
        print(f"Valuations: {countermodel.valuations}")

Accessibility Relations
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    prover = ModalTableauxProver(kb, logic="K")
    
    # Get accessibility relation
    result = prover.prove("□P → ◊P")
    
    if result.is_valid:
        # View accessibility structure
        print("Accessibility relation:")
        for world, accessible in result.accessibility.items():
            print(f"  {world} -> {accessible}")

Custom Frame Conditions
^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    # Define custom modal logic with reflexivity and transitivity
    prover = ModalTableauxProver(
        kb,
        logic="custom",
        frame_conditions={
            'reflexive': True,
            'transitive': True,
            'symmetric': False,
            'euclidean': False
        }
    )
    
    result = prover.prove("□P → P")  # Should be valid (reflexivity)

Temporal Properties
^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = KnowledgeBase()
    kb.add_axiom("□(Request → X(Process))")
    kb.add_axiom("□(Process → X(Complete))")
    kb.add_axiom("Request")
    
    prover = ModalTableauxProver(kb, logic="LTL")
    
    # Prove safety property
    result1 = prover.prove("X(X(Complete))")
    
    # Prove liveness property
    result2 = prover.prove("◊Complete")
    
    if result1.is_valid and result2.is_valid:
        print("Both safety and liveness properties hold!")

Visualization
^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.proof_tree_visualizer import ProofTreeVisualizer
    
    result = prover.prove("□(P → Q)")
    
    if result.is_valid:
        # Visualize tableaux proof
        visualizer = ProofTreeVisualizer()
        visualizer.visualize_tableaux(
            result.tableaux_tree,
            output_file="tableaux_proof.png",
            show_worlds=True
        )

See Also
--------

- :ref:`api-prover` - Basic theorem proving
- :ref:`tutorials-modal-logic` - Modal logic tutorial
- :ref:`examples-modal` - Modal logic examples
