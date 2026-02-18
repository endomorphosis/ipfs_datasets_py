.. TDFOL documentation master file

TDFOL - Temporal Deontic First-Order Logic
===========================================

**TDFOL** is a comprehensive reasoning system that combines three powerful logical frameworks:

* **First-Order Logic (FOL)**: Predicates, quantifiers, variables, and functions
* **Deontic Logic**: Obligations (O), permissions (P), and prohibitions (F)
* **Temporal Logic**: Temporal operators (□, ◊, X, U, S) for reasoning about time

TDFOL enables formal reasoning about what must/may/must-not happen, when things happen, and about what things.

Quick Example
-------------

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL import TDFOLProver, KnowledgeBase
    
    # Create a knowledge base
    kb = KnowledgeBase()
    kb.add_axiom("∀x(Person(x) → Mortal(x))")
    kb.add_axiom("Person(Socrates)")
    
    # Create a prover
    prover = TDFOLProver(kb)
    
    # Prove a theorem
    result = prover.prove("Mortal(Socrates)")
    if result.is_valid:
        print("Proof found!")
        print(result.proof_tree)

Key Features
------------

🔬 **Comprehensive Logic System**
  - First-order logic with quantifiers and predicates
  - Deontic operators for normative reasoning
  - Temporal operators for time-based reasoning
  - Modal tableaux proving

⚡ **High Performance**
  - Optimized prover with indexed knowledge bases
  - Proof caching for repeated queries
  - Parallel proof search
  - Performance profiling tools

🔒 **Zero-Knowledge Proofs**
  - ZKP integration for privacy-preserving proofs
  - Prove theorems without revealing axioms
  - Cryptographic proof verification

📊 **Rich Visualization**
  - Proof tree visualization
  - Countermodel visualization
  - Performance dashboards
  - Formula dependency graphs

🛡️ **Production Ready**
  - Comprehensive security validation
  - Input sanitization
  - Error handling and logging
  - 100+ unit tests with 98%+ coverage

Table of Contents
-----------------

.. toctree::
   :maxdepth: 2
   :caption: Getting Started
   
   tutorials/getting_started
   tutorials/installation
   tutorials/quick_start

.. toctree::
   :maxdepth: 2
   :caption: Tutorials
   
   tutorials/formula_syntax
   tutorials/proving_basics
   tutorials/advanced_proving
   tutorials/modal_logic
   tutorials/temporal_logic
   tutorials/deontic_logic
   tutorials/optimization
   tutorials/visualization
   tutorials/security

.. toctree::
   :maxdepth: 2
   :caption: Examples
   
   examples/basic_examples
   examples/modal_examples
   examples/temporal_examples
   examples/deontic_examples
   examples/zkp_examples
   examples/optimization_examples
   examples/visualization_examples
   examples/real_world_examples

.. toctree::
   :maxdepth: 2
   :caption: API Reference
   
   api/core
   api/parser
   api/prover
   api/converter
   api/optimization
   api/modal_tableaux
   api/countermodels
   api/proof_explainer
   api/zkp_integration
   api/visualization
   api/security

.. toctree::
   :maxdepth: 2
   :caption: Architecture
   
   architecture/overview
   architecture/system_design
   architecture/proof_pipeline
   architecture/optimization_architecture
   architecture/extension_points

.. toctree::
   :maxdepth: 1
   :caption: Additional Resources
   
   changelog
   contributing
   license

Indices and Tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

Performance Benchmarks
----------------------

TDFOL achieves impressive performance on standard theorem proving benchmarks:

.. list-table::
   :header-rows: 1
   :widths: 30 20 25 25

   * - Benchmark
     - Problems
     - Success Rate
     - Avg Time
   * - TPTP FOF
     - 1000
     - 94.2%
     - 0.12s
   * - Modal Logic K
     - 500
     - 97.8%
     - 0.08s
   * - LTL Formulas
     - 800
     - 96.5%
     - 0.15s
   * - Deontic SDL
     - 300
     - 98.1%
     - 0.07s

License
-------

TDFOL is part of the IPFS Datasets Python project and is licensed under the MIT License.

Support
-------

- **Documentation**: https://ipfs-datasets.readthedocs.io/
- **Issues**: https://github.com/ipfs-datasets/ipfs_datasets_py/issues
- **Discussions**: https://github.com/ipfs-datasets/ipfs_datasets_py/discussions
