.. _api-core:

Core Module (tdfol_core.py)
============================

The core module provides the fundamental building blocks for TDFOL formulas and knowledge bases.

.. automodule:: ipfs_datasets_py.logic.TDFOL.tdfol_core
   :members:
   :undoc-members:
   :show-inheritance:
   :special-members: __init__

Overview
--------

The core module defines:

- **Formula Classes**: Atoms, quantified formulas, compound formulas
- **Operators**: Logical, deontic, and temporal operators
- **Knowledge Base**: Storage and management of axioms and facts
- **Sorts**: Type system for first-order logic terms

Key Classes
-----------

TDFOLNode
^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_core.TDFOLNode
   :members:
   :undoc-members:
   :show-inheritance:

Formula
^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_core.Formula
   :members:
   :undoc-members:
   :show-inheritance:

Atom
^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_core.Atom
   :members:
   :undoc-members:
   :show-inheritance:

Predicate
^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_core.Predicate
   :members:
   :undoc-members:
   :show-inheritance:

Term
^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_core.Term
   :members:
   :undoc-members:
   :show-inheritance:

Variable
^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_core.Variable
   :members:
   :undoc-members:
   :show-inheritance:

Constant
^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_core.Constant
   :members:
   :undoc-members:
   :show-inheritance:

Function
^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_core.Function
   :members:
   :undoc-members:
   :show-inheritance:

CompoundFormula
^^^^^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_core.CompoundFormula
   :members:
   :undoc-members:
   :show-inheritance:

QuantifiedFormula
^^^^^^^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_core.QuantifiedFormula
   :members:
   :undoc-members:
   :show-inheritance:

ModalFormula
^^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_core.ModalFormula
   :members:
   :undoc-members:
   :show-inheritance:

DeonticFormula
^^^^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_core.DeonticFormula
   :members:
   :undoc-members:
   :show-inheritance:

TemporalFormula
^^^^^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_core.TemporalFormula
   :members:
   :undoc-members:
   :show-inheritance:

KnowledgeBase
^^^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_core.KnowledgeBase
   :members:
   :undoc-members:
   :show-inheritance:

Enumerations
------------

LogicOperator
^^^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_core.LogicOperator
   :members:
   :undoc-members:

Quantifier
^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_core.Quantifier
   :members:
   :undoc-members:

DeonticOperator
^^^^^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_core.DeonticOperator
   :members:
   :undoc-members:

TemporalOperator
^^^^^^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_core.TemporalOperator
   :members:
   :undoc-members:

Sort
^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_core.Sort
   :members:
   :undoc-members:

Usage Examples
--------------

Creating Formulas
^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
        Atom, Predicate, Variable, Constant,
        CompoundFormula, LogicOperator
    )
    
    # Create an atom: Person(Socrates)
    person_socrates = Atom(
        predicate=Predicate("Person"),
        terms=[Constant("Socrates")]
    )
    
    # Create a compound formula: Person(x) → Mortal(x)
    x = Variable("x")
    person_x = Atom(Predicate("Person"), [x])
    mortal_x = Atom(Predicate("Mortal"), [x])
    implication = CompoundFormula(
        operator=LogicOperator.IMPLIES,
        operands=[person_x, mortal_x]
    )

Using Knowledge Base
^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.tdfol_core import KnowledgeBase
    
    kb = KnowledgeBase()
    
    # Add axioms
    kb.add_axiom("∀x(Person(x) → Mortal(x))")
    kb.add_axiom("Person(Socrates)")
    
    # Query the knowledge base
    axioms = kb.get_axioms()
    facts = kb.get_facts()
    
    # Check for specific predicates
    person_facts = kb.get_facts_by_predicate("Person")

Working with Temporal Logic
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
        TemporalFormula, TemporalOperator, Atom
    )
    
    # Create: □(Safe(x)) - "Always Safe(x)"
    safe_x = Atom(Predicate("Safe"), [Variable("x")])
    always_safe = TemporalFormula(
        operator=TemporalOperator.ALWAYS,
        formula=safe_x
    )
    
    # Create: ◊(Success(y)) - "Eventually Success(y)"
    success_y = Atom(Predicate("Success"), [Variable("y")])
    eventually_success = TemporalFormula(
        operator=TemporalOperator.EVENTUALLY,
        formula=success_y
    )

Working with Deontic Logic
^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
        DeonticFormula, DeonticOperator, Atom
    )
    
    # Create: O(Report(agent)) - "It is obligatory to Report(agent)"
    report = Atom(Predicate("Report"), [Variable("agent")])
    obligation = DeonticFormula(
        operator=DeonticOperator.OBLIGATION,
        formula=report
    )
    
    # Create: P(Leave(x)) - "It is permitted to Leave(x)"
    leave = Atom(Predicate("Leave"), [Variable("x")])
    permission = DeonticFormula(
        operator=DeonticOperator.PERMISSION,
        formula=leave
    )
    
    # Create: F(Steal(x)) - "It is forbidden to Steal(x)"
    steal = Atom(Predicate("Steal"), [Variable("x")])
    prohibition = DeonticFormula(
        operator=DeonticOperator.PROHIBITION,
        formula=steal
    )

See Also
--------

- :ref:`api-parser` - Parsing TDFOL formulas from strings
- :ref:`api-prover` - Proving theorems with TDFOL
- :ref:`api-converter` - Converting between logical formats
