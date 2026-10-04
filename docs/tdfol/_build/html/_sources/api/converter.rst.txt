.. _api-converter:

Converter Module (tdfol_converter.py)
======================================

The converter module provides utilities for converting TDFOL formulas to and from various logical formats.

.. automodule:: ipfs_datasets_py.logic.TDFOL.tdfol_converter
   :members:
   :undoc-members:
   :show-inheritance:

Overview
--------

The converter module supports:

- **Format Conversion**: Convert between TDFOL and other logic formats
- **Export**: Export to TPTP, SMT-LIB, Coq, Isabelle
- **Import**: Import from standard theorem prover formats
- **Normalization**: Convert formulas to normal forms (CNF, DNF, NNF)

Key Classes
-----------

TDFOLConverter
^^^^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_converter.TDFOLConverter
   :members:
   :undoc-members:
   :show-inheritance:

Usage Examples
--------------

Converting to TPTP Format
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL import TDFOLConverter, TDFOLParser
    
    parser = TDFOLParser()
    converter = TDFOLConverter()
    
    # Parse a TDFOL formula
    formula = parser.parse("∀x(Person(x) → Mortal(x))")
    
    # Convert to TPTP format
    tptp_formula = converter.to_tptp(formula)
    print(tptp_formula)
    # Output: fof(axiom1, axiom, ![X]: (person(X) => mortal(X))).

Converting to SMT-LIB Format
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    formula = parser.parse("∀x(P(x) → Q(x))")
    
    smtlib = converter.to_smtlib(formula)
    print(smtlib)
    # Output: (forall ((x Int)) (=> (P x) (Q x)))

Converting to Coq
^^^^^^^^^^^^^^^^^

.. code-block:: python

    formula = parser.parse("∀x(Person(x) → Mortal(x))")
    
    coq_code = converter.to_coq(formula)
    print(coq_code)
    # Output: forall x, Person x -> Mortal x.

Converting to Isabelle/HOL
^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    formula = parser.parse("∀x∃y(Loves(x, y))")
    
    isabelle_code = converter.to_isabelle(formula)
    print(isabelle_code)
    # Output: ∀x. ∃y. Loves x y

Converting to LaTeX
^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    formula = parser.parse("∀x(P(x) → ◊Q(x))")
    
    latex = converter.to_latex(formula)
    print(latex)
    # Output: \forall x (P(x) \rightarrow \Diamond Q(x))

Converting to Python Code
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    formula = parser.parse("∀x(P(x) ∧ Q(x))")
    
    python_code = converter.to_python(formula)
    print(python_code)
    # Output: all(P(x) and Q(x) for x in domain)

Normal Form Conversions
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    formula = parser.parse("¬(P ∧ Q) ∨ R")
    
    # Convert to Negation Normal Form (NNF)
    nnf = converter.to_nnf(formula)
    print(f"NNF: {nnf.to_string()}")
    # Output: (¬P ∨ ¬Q) ∨ R
    
    # Convert to Conjunctive Normal Form (CNF)
    cnf = converter.to_cnf(formula)
    print(f"CNF: {cnf.to_string()}")
    
    # Convert to Disjunctive Normal Form (DNF)
    dnf = converter.to_dnf(formula)
    print(f"DNF: {dnf.to_string()}")

Skolemization
^^^^^^^^^^^^^

.. code-block:: python

    formula = parser.parse("∀x∃y(P(x, y))")
    
    # Skolemize existential quantifiers
    skolemized = converter.skolemize(formula)
    print(f"Skolemized: {skolemized.to_string()}")
    # Output: ∀x(P(x, f_sk1(x)))

Converting from External Formats
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    # Import from TPTP
    tptp_str = "fof(axiom1, axiom, ![X]: (person(X) => mortal(X)))."
    formula = converter.from_tptp(tptp_str)
    
    # Import from SMT-LIB
    smtlib_str = "(forall ((x Int)) (=> (P x) (Q x)))"
    formula = converter.from_smtlib(smtlib_str)

Batch Conversion
^^^^^^^^^^^^^^^^

.. code-block:: python

    formulas = [
        parser.parse("∀x(P(x) → Q(x))"),
        parser.parse("∃y(R(y) ∧ S(y))"),
        parser.parse("□(A → B)")
    ]
    
    # Convert all to TPTP
    tptp_formulas = converter.batch_to_tptp(formulas)
    
    for i, tptp in enumerate(tptp_formulas):
        print(f"Formula {i+1}: {tptp}")

Exporting Knowledge Bases
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL import KnowledgeBase
    
    kb = KnowledgeBase()
    kb.add_axiom("∀x(Person(x) → Mortal(x))")
    kb.add_axiom("Person(Socrates)")
    
    # Export entire KB to TPTP
    tptp_kb = converter.kb_to_tptp(kb)
    
    with open('knowledge_base.p', 'w') as f:
        f.write(tptp_kb)
    
    # Export to Coq
    coq_kb = converter.kb_to_coq(kb)
    
    with open('knowledge_base.v', 'w') as f:
        f.write(coq_kb)

Custom Conversions
^^^^^^^^^^^^^^^^^^

.. code-block:: python

    # Define custom conversion rules
    converter = TDFOLConverter()
    
    converter.add_custom_rule(
        operator='→',
        tptp='$impl',
        smtlib='=>',
        coq='->',
        latex='\\rightarrow'
    )
    
    formula = parser.parse("P → Q")
    tptp = converter.to_tptp(formula)

Simplification
^^^^^^^^^^^^^^

.. code-block:: python

    formula = parser.parse("(P ∧ True) ∨ (False ∧ Q)")
    
    # Simplify formula
    simplified = converter.simplify(formula)
    print(f"Simplified: {simplified.to_string()}")
    # Output: P

Prenex Normal Form
^^^^^^^^^^^^^^^^^^

.. code-block:: python

    formula = parser.parse("∀x(P(x)) ∧ ∃y(Q(y))")
    
    # Convert to prenex normal form
    prenex = converter.to_prenex(formula)
    print(f"Prenex: {prenex.to_string()}")
    # Output: ∀x∃y(P(x) ∧ Q(y))

See Also
--------

- :ref:`api-parser` - Parsing TDFOL formulas
- :ref:`api-prover` - Proving with converted formulas
- :ref:`examples-conversion` - More conversion examples
