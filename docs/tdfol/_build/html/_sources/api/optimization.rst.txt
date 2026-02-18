.. _api-optimization:

Optimization Module (tdfol_optimization.py)
============================================

The optimization module provides high-performance proving with caching, indexing, and parallel search.

.. automodule:: ipfs_datasets_py.logic.TDFOL.tdfol_optimization
   :members:
   :undoc-members:
   :show-inheritance:

Overview
--------

The optimization module includes:

- **OptimizedProver**: High-performance prover with caching
- **IndexedKnowledgeBase**: Fast axiom lookup with indexing
- **ProofCache**: Caching for repeated proof queries
- **ParallelProver**: Multi-threaded proof search

Key Classes
-----------

OptimizedProver
^^^^^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_optimization.OptimizedProver
   :members:
   :undoc-members:
   :show-inheritance:

IndexedKnowledgeBase
^^^^^^^^^^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_optimization.IndexedKnowledgeBase
   :members:
   :undoc-members:
   :show-inheritance:

ProofCache
^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_optimization.ProofCache
   :members:
   :undoc-members:
   :show-inheritance:

ParallelProver
^^^^^^^^^^^^^^

.. autoclass:: ipfs_datasets_py.logic.TDFOL.tdfol_optimization.ParallelProver
   :members:
   :undoc-members:
   :show-inheritance:

Usage Examples
--------------

Using OptimizedProver
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.tdfol_optimization import (
        OptimizedProver, IndexedKnowledgeBase
    )
    
    # Create indexed knowledge base
    kb = IndexedKnowledgeBase()
    kb.add_axiom("∀x(Person(x) → Mortal(x))")
    kb.add_axiom("Person(Socrates)")
    
    # Create optimized prover
    prover = OptimizedProver(kb, cache_size=1000)
    
    # First proof - will be computed
    result1 = prover.prove("Mortal(Socrates)")
    print(f"Time: {result1.time_elapsed:.4f}s")
    
    # Second proof - will be cached
    result2 = prover.prove("Mortal(Socrates)")
    print(f"Time (cached): {result2.time_elapsed:.4f}s")
    print(f"Cache hit: {result2.from_cache}")

Indexed Knowledge Base
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = IndexedKnowledgeBase()
    
    # Add many axioms
    for i in range(1000):
        kb.add_axiom(f"Property{i}(object{i})")
    
    # Fast predicate lookup
    axioms = kb.get_axioms_by_predicate("Property500")
    
    # Fast pattern matching
    matching = kb.find_matching_axioms("∀x(Property500(x) → ...)")
    
    print(f"Index size: {kb.index_size}")
    print(f"Predicates indexed: {len(kb.indexed_predicates)}")

Parallel Proving
^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.tdfol_optimization import ParallelProver
    
    prover = ParallelProver(kb, num_workers=4)
    
    # Prove multiple theorems in parallel
    theorems = [
        "Mortal(Socrates)",
        "∀x(Man(x) → Mortal(x))",
        "∃x(Philosopher(x))"
    ]
    
    results = prover.prove_batch(theorems)
    
    for theorem, result in zip(theorems, results):
        print(f"{theorem}: {result.is_valid} ({result.time_elapsed:.3f}s)")

Proof Caching
^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.tdfol_proof_cache import ProofCache
    
    cache = ProofCache(max_size=10000, ttl=3600)  # 1 hour TTL
    
    # Manual cache operations
    theorem = "Mortal(Socrates)"
    
    if not cache.has(theorem):
        result = prover.prove(theorem)
        cache.put(theorem, result)
    else:
        result = cache.get(theorem)
        print("Retrieved from cache!")
    
    # Cache statistics
    stats = cache.get_stats()
    print(f"Cache hits: {stats['hits']}")
    print(f"Cache misses: {stats['misses']}")
    print(f"Hit rate: {stats['hit_rate']:.2%}")

Incremental Knowledge Base Updates
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    kb = IndexedKnowledgeBase()
    prover = OptimizedProver(kb)
    
    # Add axioms incrementally
    kb.add_axiom("∀x(Person(x) → Mortal(x))")
    
    # Indices are updated automatically
    result1 = prover.prove("Person(Socrates) → Mortal(Socrates)")
    
    # Add more axioms
    kb.add_axiom("Person(Socrates)")
    
    # Cache is intelligently invalidated
    result2 = prover.prove("Mortal(Socrates)")

Performance Profiling
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler
    
    profiler = PerformanceProfiler()
    prover = OptimizedProver(kb, profiler=profiler)
    
    # Run proofs with profiling
    result = prover.prove("ComplexTheorem(x, y, z)")
    
    # Get performance report
    report = profiler.get_report()
    print(f"Total time: {report['total_time']:.4f}s")
    print(f"Cache hits: {report['cache_hits']}")
    print(f"Index lookups: {report['index_lookups']}")
    print(f"Unifications: {report['unifications']}")

Optimization Settings
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    prover = OptimizedProver(
        kb,
        cache_size=5000,              # Cache up to 5000 proofs
        index_predicates=True,         # Enable predicate indexing
        index_functions=True,          # Enable function indexing
        parallel_search=True,          # Use parallel search
        num_workers=8,                 # 8 parallel workers
        timeout=30.0,                  # 30 second timeout
        max_depth=100,                 # Max proof depth
        use_heuristics=True,          # Enable search heuristics
        aggressive_caching=True       # Cache partial results
    )

Benchmark Comparison
^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from ipfs_datasets_py.logic.TDFOL import TDFOLProver
    from ipfs_datasets_py.logic.TDFOL.tdfol_optimization import OptimizedProver
    import time
    
    # Standard prover
    standard_prover = TDFOLProver(kb)
    start = time.time()
    for i in range(100):
        standard_prover.prove(f"Property{i}(obj)")
    standard_time = time.time() - start
    
    # Optimized prover
    optimized_prover = OptimizedProver(kb)
    start = time.time()
    for i in range(100):
        optimized_prover.prove(f"Property{i}(obj)")
    optimized_time = time.time() - start
    
    speedup = standard_time / optimized_time
    print(f"Speedup: {speedup:.2f}x")

Memory Management
^^^^^^^^^^^^^^^^^

.. code-block:: python

    prover = OptimizedProver(kb)
    
    # Monitor memory usage
    print(f"Cache size: {prover.cache.size_bytes / 1024 / 1024:.2f} MB")
    print(f"Index size: {prover.kb.index_size_bytes / 1024 / 1024:.2f} MB")
    
    # Clear cache if needed
    prover.clear_cache()
    
    # Rebuild indices
    prover.rebuild_indices()

See Also
--------

- :ref:`api-prover` - Basic theorem proving
- :ref:`tutorials-optimization` - Optimization guide
- :ref:`examples-optimization` - Optimization examples
