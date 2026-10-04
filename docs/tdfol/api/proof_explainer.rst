.. _api-proof-explainer:

Proof Explainer Module (proof_explainer.py)
============================================

The proof explainer module generates human-readable explanations of proofs.

.. automodule:: ipfs_datasets_py.logic.TDFOL.proof_explainer
   :members:
   :undoc-members:
   :show-inheritance:

Overview
--------

Convert formal proofs into natural language explanations suitable for:

- **Education**: Teaching logic and reasoning
- **Documentation**: Explaining system decisions
- **Debugging**: Understanding proof failures
- **Transparency**: Making AI reasoning interpretable

Key Classes
-----------

ProofExplainer
^^^^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.proof_explainer.ProofExplainer
   :members:
   :undoc-members:
   :show-inheritance:

Usage Examples
--------------

Basic Proof Explanation
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL import TDFOLProver, KnowledgeBase
    from ipfs_datasets_py.logic.TDFOL.proof_explainer import ProofExplainer
    
    kb = KnowledgeBase()
    kb.add_axiom("∀x(Person(x) → Mortal(x))")
    kb.add_axiom("Person(Socrates)")
    
    prover = TDFOLProver(kb)
    result = prover.prove("Mortal(Socrates)")
    
    if result.is_valid:
        explainer = ProofExplainer()
        explanation = explainer.explain(result)
        
        print(explanation)
        # Output:
        # "We want to prove that Mortal(Socrates).
        # From the axiom that all persons are mortal,
        # and the fact that Socrates is a person,
        # we can conclude that Socrates is mortal."

Custom Explanation Styles
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    explainer = ProofExplainer(style="formal")
    formal_explanation = explainer.explain(result)
    
    explainer = ProofExplainer(style="casual")
    casual_explanation = explainer.explain(result)
    
    explainer = ProofExplainer(style="technical")
    technical_explanation = explainer.explain(result)

Step-by-Step Explanations
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    explainer = ProofExplainer(verbose=True)
    explanation = explainer.explain_steps(result)
    
    for i, step_explanation in enumerate(explanation.steps):
        print(f"Step {i+1}: {step_explanation}")

Interactive Explanations
^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    explainer = ProofExplainer(interactive=True)
    
    # Get explanation with questions
    explanation = explainer.explain_interactive(result)
    
    # User can ask questions about the proof
    answer = explainer.ask("Why did we use universal instantiation?")
    print(answer)

See Also
--------

- :ref:`api-prover` - Theorem proving
- :ref:`tutorials-proving-basics` - Basic proving tutorial
