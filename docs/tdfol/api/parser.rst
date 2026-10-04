.. _api-parser:

Parser Module (tdfol_parser.py)
================================

The parser module converts string representations of TDFOL formulas into structured formula objects.

.. automodule:: ipfs_datasets_py.logic.TDFOL.tdfol_parser
   :members:
   :undoc-members:
   :show-inheritance:

Overview
--------

The parser module provides:

- **TDFOLParser**: Main parser for TDFOL formula strings
- **Lexer**: Tokenization of formula strings
- **Syntax validation**: Checking formula well-formedness
- **Error reporting**: Detailed syntax error messages

Key Classes
-----------

TDFOLParser
^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_parser.TDFOLParser
   :members:
   :undoc-members:
   :show-inheritance:

Lexer
^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_parser.Lexer
   :members:
   :undoc-members:
   :show-inheritance:

Token
^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_parser.Token
   :members:
   :undoc-members:
   :show-inheritance:

Usage Examples
--------------

Basic Parsing
^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.tdfol_parser import TDFOLParser
    
    parser = TDFOLParser()
    
    # Parse a simple formula
    formula = parser.parse("Person(Socrates)")
    print(formula.to_string())
    
    # Parse a complex formula
    formula = parser.parse("∀x(Person(x) → Mortal(x))")
    print(f"Formula type: {type(formula).__name__}")

Parsing Different Formula Types
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    parser = TDFOLParser()
    
    # First-order logic
    fol_formula = parser.parse("∀x∃y(Loves(x, y))")
    
    # Propositional logic
    prop_formula = parser.parse("(P ∧ Q) → R")
    
    # Modal logic
    modal_formula = parser.parse("□(P → ◊Q)")
    
    # Temporal logic
    temporal_formula = parser.parse("□(Request → X(Response))")
    
    # Deontic logic
    deontic_formula = parser.parse("O(Report) ∧ P(Leave)")

Error Handling
^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.tdfol_parser import (
        TDFOLParser, ParseError
    )
    
    parser = TDFOLParser()
    
    try:
        # This will fail - unbalanced parentheses
        formula = parser.parse("∀x(Person(x) → Mortal(x)")
    except ParseError as e:
        print(f"Parse error: {e.message}")
        print(f"Position: {e.position}")
        print(f"Context: {e.context}")

Parsing with Validation
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    parser = TDFOLParser(strict=True, validate=True)
    
    # Parse with strict validation
    formula = parser.parse("∀x(P(x) → Q(x))")
    
    # Check if formula is well-formed
    if parser.is_well_formed(formula):
        print("Formula is well-formed")
    
    # Get formula metadata
    metadata = parser.get_metadata(formula)
    print(f"Free variables: {metadata['free_vars']}")
    print(f"Bound variables: {metadata['bound_vars']}")
    print(f"Predicates: {metadata['predicates']}")

Batch Parsing
^^^^^^^^^^^^^

.. code-block:: python

    formulas_str = [
        "Person(Socrates)",
        "∀x(Man(x) → Mortal(x))",
        "□(P → Q)",
        "O(Report) ∧ F(Steal)"
    ]
    
    parser = TDFOLParser()
    formulas = []
    
    for formula_str in formulas_str:
        try:
            formula = parser.parse(formula_str)
            formulas.append(formula)
        except ParseError as e:
            print(f"Failed to parse '{formula_str}': {e}")

Custom Syntax
^^^^^^^^^^^^^

.. code-block:: python

    # Use ASCII-friendly operators
    parser = TDFOLParser(use_ascii=True)
    
    formula = parser.parse("forall x (Person(x) -> Mortal(x))")
    # Equivalent to: ∀x(Person(x) → Mortal(x))
    
    # Custom operator aliases
    parser = TDFOLParser(aliases={
        'AND': '∧',
        'OR': '∨',
        'NOT': '¬',
        'IMPLIES': '→'
    })
    
    formula = parser.parse("P AND Q IMPLIES R")

Parsing from Files
^^^^^^^^^^^^^^^^^^

.. code-block:: python

    parser = TDFOLParser()
    
    # Parse formulas from a file
    with open('axioms.tdfol', 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                try:
                    formula = parser.parse(line)
                    print(f"Parsed: {formula.to_string()}")
                except ParseError as e:
                    print(f"Error in line: {line}\n{e}")

Pretty Printing
^^^^^^^^^^^^^^^

.. code-block:: python

    parser = TDFOLParser()
    formula = parser.parse("∀x(Person(x) → ∃y(Parent(y, x) ∧ Loves(y, x)))")
    
    # Pretty print with indentation
    print(formula.to_string(pretty=True, indent=2))
    
    # Output:
    # ∀x(
    #   Person(x) → 
    #   ∃y(
    #     Parent(y, x) ∧ 
    #     Loves(y, x)
    #   )
    # )

Formula Analysis
^^^^^^^^^^^^^^^^

.. code-block:: python

    parser = TDFOLParser()
    formula = parser.parse("∀x∃y(P(x, y) → Q(y))")
    
    # Analyze formula structure
    analysis = parser.analyze(formula)
    
    print(f"Depth: {analysis['depth']}")
    print(f"Operators: {analysis['operators']}")
    print(f"Quantifiers: {analysis['quantifiers']}")
    print(f"Variables: {analysis['variables']}")
    print(f"Predicates: {analysis['predicates']}")
    print(f"Complexity: {analysis['complexity']}")

Incremental Parsing
^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    parser = TDFOLParser(incremental=True)
    
    # Parse formula incrementally
    parser.start()
    parser.add_token("∀")
    parser.add_token("x")
    parser.add_token("(")
    parser.add_token("P")
    parser.add_token("(")
    parser.add_token("x")
    parser.add_token(")")
    parser.add_token(")")
    
    formula = parser.finish()
    print(formula.to_string())

See Also
--------

- :ref:`api-core` - Formula data structures
- :ref:`api-converter` - Converting between formula formats
- :ref:`tutorials-formula-syntax` - Complete formula syntax guide
