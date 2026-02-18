.. _tutorial-formula-syntax:

Formula Syntax Guide
====================

This guide covers the complete syntax for TDFOL formulas.

Basic Syntax Elements
---------------------

Atoms
^^^^^

Atoms are the basic building blocks:

.. code-block:: text

    Person(Socrates)
    Loves(Alice, Bob)
    Temperature(room, 72)

Syntax: ``Predicate(term1, term2, ...)``

Variables and Constants
^^^^^^^^^^^^^^^^^^^^^^^

- **Variables**: Lowercase or with prefix (``x``, ``y``, ``?var``)
- **Constants**: Capitalized (``Socrates``, ``Alice``, ``Object123``)

.. code-block:: python

    # Variables
    "∀x(Person(x) → Mortal(x))"
    
    # Constants
    "Person(Socrates)"
    "Loves(Alice, Bob)"

Logical Operators
-----------------

Conjunction (AND)
^^^^^^^^^^^^^^^^^

Symbol: ``∧`` (or ``&``, ``AND``)

.. code-block:: python

    "P ∧ Q"
    "Person(x) ∧ Mortal(x)"
    "Tall(Alice) ∧ Smart(Alice) ∧ Kind(Alice)"

Disjunction (OR)
^^^^^^^^^^^^^^^^

Symbol: ``∨`` (or ``|``, ``OR``)

.. code-block:: python

    "P ∨ Q"
    "Rain(today) ∨ Snow(today)"

Negation (NOT)
^^^^^^^^^^^^^^

Symbol: ``¬`` (or ``~``, ``NOT``, ``!``)

.. code-block:: python

    "¬P"
    "¬Person(x)"
    "¬(P ∧ Q)"

Implication
^^^^^^^^^^^

Symbol: ``→`` (or ``->``, ``IMPLIES``, ``⇒``)

.. code-block:: python

    "P → Q"
    "Person(x) → Mortal(x)"
    "Rain(today) → Wet(ground)"

Bi-Implication (IFF)
^^^^^^^^^^^^^^^^^^^^

Symbol: ``↔`` (or ``<->``, ``IFF``, ``⇔``)

.. code-block:: python

    "P ↔ Q"
    "Triangle(x) ↔ ThreeSides(x)"

Quantifiers
-----------

Universal Quantifier (∀)
^^^^^^^^^^^^^^^^^^^^^^^^^

Symbol: ``∀`` (or ``forall``, ``ALL``)

.. code-block:: python

    "∀x(Person(x) → Mortal(x))"
    "∀x∀y(Parent(x, y) → Ancestor(x, y))"

Existential Quantifier (∃)
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Symbol: ``∃`` (or ``exists``, ``SOME``)

.. code-block:: python

    "∃x(Person(x) ∧ Happy(x))"
    "∃x∃y(Loves(x, y))"

Temporal Operators
------------------

Always (□)
^^^^^^^^^^

Symbol: ``□`` (or ``G``, ``ALWAYS``)

"Always" or "Globally" - true at all future times

.. code-block:: python

    "□(Safe(system))"
    "□(Request → Response)"

Eventually (◊)
^^^^^^^^^^^^^^

Symbol: ``◊`` (or ``F``, ``EVENTUALLY``)

"Eventually" or "Finally" - true at some future time

.. code-block:: python

    "◊(Complete(task))"
    "◊(Success)"

Next (X)
^^^^^^^^

Symbol: ``X`` (or ``NEXT``)

"Next" - true at the next time step

.. code-block:: python

    "X(Response)"
    "Request → X(Process)"

Until (U)
^^^^^^^^^

Symbol: ``U`` (or ``UNTIL``)

"Until" - first formula holds until second becomes true

.. code-block:: python

    "Processing U Complete"
    "Waiting U Ready"

Since (S)
^^^^^^^^^

Symbol: ``S`` (or ``SINCE``)

"Since" - first formula has been true since second was true

.. code-block:: python

    "Active S Started"

Deontic Operators
-----------------

Obligation (O)
^^^^^^^^^^^^^^

Symbol: ``O`` (or ``OBLIGATORY``)

"It is obligatory that..."

.. code-block:: python

    "O(Report(employee))"
    "O(∀x(Driver(x) → License(x)))"

Permission (P)
^^^^^^^^^^^^^^

Symbol: ``P`` (or ``PERMITTED``)

"It is permitted that..."

.. code-block:: python

    "P(Leave(employee))"
    "P(Enter(visitor))"

Prohibition (F)
^^^^^^^^^^^^^^^

Symbol: ``F`` (or ``FORBIDDEN``)

"It is forbidden that..."

.. code-block:: python

    "F(Steal(person))"
    "F(Smoke(building))"

Complex Formulas
----------------

Nested Quantifiers
^^^^^^^^^^^^^^^^^^

.. code-block:: python

    "∀x∃y(Parent(x, y))"  # Everyone has a parent
    "∃x∀y(Loves(x, y))"   # Someone loves everyone

Mixed Operators
^^^^^^^^^^^^^^^

.. code-block:: python

    # Temporal + Deontic
    "□(O(Report(employee)))"
    
    # FOL + Temporal
    "∀x(Request(x) → ◊Response(x))"
    
    # All three
    "∀x(Employee(x) → □(O(Report(x))))"

Precedence Rules
^^^^^^^^^^^^^^^^

From highest to lowest precedence:

1. Negation (``¬``)
2. Temporal/Modal operators (``□``, ``◊``, ``X``)
3. Deontic operators (``O``, ``P``, ``F``)
4. Conjunction (``∧``)
5. Disjunction (``∨``)
6. Implication (``→``)
7. Bi-implication (``↔``)
8. Quantifiers (``∀``, ``∃``)

Use parentheses for clarity:

.. code-block:: python

    # Without parentheses (relies on precedence)
    "¬P ∧ Q → R"
    
    # With parentheses (explicit)
    "((¬P) ∧ Q) → R"

ASCII Syntax
------------

For environments that don't support Unicode:

.. code-block:: python

    # Logical operators
    "P AND Q"           # Instead of P ∧ Q
    "P OR Q"            # Instead of P ∨ Q
    "NOT P"             # Instead of ¬P
    "P IMPLIES Q"       # Instead of P → Q
    "P IFF Q"           # Instead of P ↔ Q
    
    # Quantifiers
    "forall x P(x)"     # Instead of ∀x P(x)
    "exists x P(x)"     # Instead of ∃x P(x)
    
    # Temporal
    "G(P)"              # Instead of □(P)
    "F(P)"              # Instead of ◊(P)
    "X(P)"              # Next
    "P U Q"             # Until
    
    # Deontic
    "O(P)"              # Obligation
    "P(P)"              # Permission
    "F(P)"              # Forbidden

Parsing Examples
----------------

The parser accepts various formats:

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.tdfol_parser import TDFOLParser
    
    parser = TDFOLParser()
    
    # Unicode symbols
    f1 = parser.parse("∀x(P(x) → Q(x))")
    
    # ASCII-friendly
    f2 = parser.parse("forall x (P(x) IMPLIES Q(x))")
    
    # Mixed
    f3 = parser.parse("∀x(P(x) -> Q(x))")
    
    # All three are equivalent!
    assert f1 == f2 == f3

Common Patterns
---------------

Implication Chains
^^^^^^^^^^^^^^^^^^

.. code-block:: python

    "A → B → C"  # Equivalent to A → (B → C)

Universal Implications
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    "∀x(Person(x) → Mortal(x))"

Existential Conjunctions
^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    "∃x(Person(x) ∧ Happy(x))"

Temporal Safety Properties
^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    "□(Request → ◊Response)"  # Every request eventually gets response
    "□(Error → X(Handle))"     # Every error is handled next

Deontic Rules
^^^^^^^^^^^^^

.. code-block:: python

    "∀x(Employee(x) → O(Report(x)))"      # All employees must report
    "∀x(Visitor(x) → P(Enter(x)))"        # All visitors may enter
    "∀x(Criminal(x) → F(Vote(x)))"        # Criminals forbidden to vote

See Also
--------

- :ref:`api-parser` - Parser API documentation
- :ref:`api-core` - Formula data structures
- :ref:`examples-basic` - Basic usage examples
