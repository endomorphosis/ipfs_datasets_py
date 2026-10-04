.. _architecture-overview:

Architecture Overview
=====================

System Design
-------------

TDFOL is designed as a modular theorem proving system with the following components:

Core Components
^^^^^^^^^^^^^^^

1. **Formula Representation** (tdfol_core.py)
   - Abstract syntax trees for formulas
   - Type system for sorts
   - Operator definitions

2. **Parser** (tdfol_parser.py)
   - Lexical analysis
   - Syntax parsing
   - Error handling

3. **Prover** (tdfol_prover.py)
   - Resolution-based proving
   - Natural deduction
   - Tableaux method

Extension Points
----------------

Custom Proof Strategies
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofStrategy
    
    class CustomStrategy(ProofStrategy):
        def prove(self, formula, kb):
            # Custom proving logic
            pass
