.. _api-visualization:

Visualization Modules
=====================

TDFOL provides comprehensive visualization tools for proofs, countermodels, and performance analysis.

Proof Tree Visualizer
---------------------

.. automodule:: ipfs_datasets_py.logic.TDFOL.proof_tree_visualizer
   :members:
   :undoc-members:
   :show-inheritance:

Countermodel Visualizer
-----------------------

.. automodule:: ipfs_datasets_py.logic.TDFOL.countermodel_visualizer
   :members:
   :undoc-members:
   :show-inheritance:

Formula Dependency Graph
------------------------

.. automodule:: ipfs_datasets_py.logic.TDFOL.formula_dependency_graph
   :members:
   :undoc-members:
   :show-inheritance:

Performance Dashboard
---------------------

.. automodule:: ipfs_datasets_py.logic.TDFOL.performance_dashboard
   :members:
   :undoc-members:
   :show-inheritance:

Usage Examples
--------------

Visualizing Proof Trees
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL import TDFOLProver, KnowledgeBase
    from ipfs_datasets_py.logic.TDFOL.proof_tree_visualizer import ProofTreeVisualizer
    
    kb = KnowledgeBase()
    kb.add_axiom("∀x(Person(x) → Mortal(x))")
    kb.add_axiom("Person(Socrates)")
    
    prover = TDFOLProver(kb)
    result = prover.prove("Mortal(Socrates)")
    
    if result.is_valid:
        visualizer = ProofTreeVisualizer()
        visualizer.visualize(
            result.proof_tree,
            output_file="proof_tree.png",
            layout="hierarchical",
            show_rules=True,
            color_scheme="default"
        )

Visualizing Countermodels
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.countermodel_visualizer import CountermodelVisualizer
    
    visualizer = CountermodelVisualizer()
    
    # Visualize countermodel
    visualizer.visualize(
        countermodel,
        output_file="countermodel.png",
        layout="spring",
        show_world_labels=True,
        show_valuations=True
    )

Formula Dependency Graphs
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.formula_dependency_graph import FormulaDependencyGraph
    
    graph = FormulaDependencyGraph(kb)
    
    # Build dependency graph
    graph.build()
    
    # Visualize dependencies
    graph.visualize(
        output_file="dependencies.png",
        highlight_cycles=True,
        show_weights=True
    )
    
    # Analyze dependencies
    critical_formulas = graph.get_critical_formulas()
    cycles = graph.find_cycles()

Performance Dashboard
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.performance_dashboard import PerformanceDashboard
    
    dashboard = PerformanceDashboard()
    
    # Run benchmarks
    results = []
    for theorem in test_theorems:
        result = prover.prove(theorem)
        results.append(result)
    
    # Generate dashboard
    dashboard.generate(
        results,
        output_file="performance_dashboard.html",
        include_graphs=True,
        include_statistics=True
    )
    
    # Open in browser
    dashboard.open_in_browser()

Interactive Visualization
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.proof_tree_visualizer import ProofTreeVisualizer
    
    visualizer = ProofTreeVisualizer(interactive=True)
    
    # Create interactive visualization
    visualizer.visualize_interactive(
        result.proof_tree,
        output_file="proof_interactive.html",
        enable_zoom=True,
        enable_pan=True,
        enable_node_click=True
    )

Custom Styling
^^^^^^^^^^^^^^

.. code-block:: python

    visualizer = ProofTreeVisualizer()
    
    # Define custom style
    style = {
        'node_color': '#3498db',
        'edge_color': '#2c3e50',
        'font_family': 'Arial',
        'font_size': 12,
        'node_shape': 'box',
        'arrow_style': '->'
    }
    
    visualizer.visualize(
        proof_tree,
        output_file="proof_custom.png",
        style=style
    )

See Also
--------

- :ref:`tutorials-visualization` - Visualization tutorial
- :ref:`examples-visualization` - More visualization examples
