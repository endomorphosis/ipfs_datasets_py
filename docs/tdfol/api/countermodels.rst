.. _api-countermodels:

Countermodels Module (countermodels.py)
========================================

The countermodels module extracts and visualizes countermodels for invalid formulas.

.. automodule:: ipfs_datasets_py.logic.TDFOL.countermodels
   :members:
   :undoc-members:
   :show-inheritance:

Overview
--------

When a formula cannot be proved, a countermodel demonstrates why it's invalid.
This module provides tools for:

- **Countermodel Extraction**: Automatic extraction from failed proofs
- **Model Validation**: Checking countermodel consistency
- **Visualization**: Graphical representation of countermodels

Key Classes
-----------

CountermodelExtractor
^^^^^^^^^^^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.countermodels.CountermodelExtractor
   :members:
   :undoc-members:
   :show-inheritance:

Countermodel
^^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.countermodels.Countermodel
   :members:
   :undoc-members:
   :show-inheritance:

Usage Examples
--------------

Extracting Countermodels
^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL import TDFOLProver, KnowledgeBase
    from ipfs_datasets_py.logic.TDFOL.countermodels import CountermodelExtractor
    
    kb = KnowledgeBase()
    kb.add_axiom("∃x(P(x))")
    
    prover = TDFOLProver(kb)
    result = prover.prove("∀x(P(x))")  # Invalid!
    
    if not result.is_valid:
        extractor = CountermodelExtractor()
        countermodel = extractor.extract(result.failed_tableau)
        
        print(f"Domain: {countermodel.domain}")
        print(f"Interpretation: {countermodel.interpretation}")

Validating Countermodels
^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    countermodel = extractor.extract(failed_proof)
    
    # Verify the countermodel satisfies axioms but not theorem
    if countermodel.validates_axioms(kb.axioms):
        print("Countermodel satisfies all axioms")
    
    if not countermodel.validates(theorem):
        print("Countermodel falsifies the theorem")

Visualizing Countermodels
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.countermodel_visualizer import CountermodelVisualizer
    
    visualizer = CountermodelVisualizer()
    
    # Create visualization
    visualizer.visualize(
        countermodel,
        output_file="countermodel.png",
        layout="spring",
        show_labels=True
    )

See Also
--------

- :ref:`api-prover` - Theorem proving
- :ref:`api-modal-tableaux` - Modal countermodels
