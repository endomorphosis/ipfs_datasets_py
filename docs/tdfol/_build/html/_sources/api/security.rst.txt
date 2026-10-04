.. _api-security:

Security Module (security_validator.py)
========================================

The security module provides comprehensive security validation for TDFOL operations.

.. automodule:: ipfs_datasets_py.logic.TDFOL.security_validator
   :members:
   :undoc-members:
   :show-inheritance:

Overview
--------

The security module ensures:

- **Input Validation**: Sanitize formula inputs
- **Resource Limits**: Prevent DoS attacks
- **Access Control**: Manage permissions
- **Audit Logging**: Track security events

Key Classes
-----------

SecurityValidator
^^^^^^^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.security_validator.SecurityValidator
   :members:
   :undoc-members:
   :show-inheritance:

Usage Examples
--------------

Validating Inputs
^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.security_validator import SecurityValidator
    
    validator = SecurityValidator()
    
    # Validate formula string
    formula_str = "∀x(Person(x) → Mortal(x))"
    
    if validator.validate_formula_string(formula_str):
        # Safe to parse
        formula = parser.parse(formula_str)
    else:
        print("Invalid or unsafe formula!")

Resource Limits
^^^^^^^^^^^^^^^

.. code-block:: python

    validator = SecurityValidator(
        max_formula_depth=100,
        max_formula_length=10000,
        max_kb_size=100000,
        max_proof_time=30.0
    )
    
    # Check formula complexity
    if validator.check_complexity(formula):
        result = prover.prove(formula)

Secure Proving
^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL import TDFOLProver
    
    # Prover with security validation
    prover = TDFOLProver(
        kb,
        validator=validator,
        enforce_limits=True
    )
    
    try:
        result = prover.prove(theorem)
    except SecurityError as e:
        print(f"Security violation: {e}")

See Also
--------

- :ref:`tutorials-security` - Security best practices
- :ref:`examples-security` - Security examples
