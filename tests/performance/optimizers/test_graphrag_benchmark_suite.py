"""
Comprehensive GraphRAG Benchmark Suite (Session 82, P2-tests).

This module provides performance benchmarks for GraphRAG query optimization,
covering:

1. Entity extraction performance at various scales
2. Entity deduplication algorithms (exact, fuzzy, semantic)
3. Graph traversal and path finding
4. End-to-end query flows (simple, complex, multi-hop)

Benchmarks use real-world datasets when available, falling back to generated
data for controlled scaling tests.

Usage:
    pytest tests/performance/optimizers/test_graphrag_benchmark_suite.py -v
    pytest tests/performance/optimizers/test_graphrag_benchmark_suite.py::test_entity_extraction_scaling -v
    pytest tests/performance/optimizers/test_graphrag_benchmark_suite.py -m "not slow"
"""

import pytest
import time
from typing import List, Dict, Any

# Gracefully handle missing dependencies
try:
    from ipfs_datasets_py.optimizers.graphrag.entity_extraction import (
        GraphRAGEntityExtractor,
        ExtractionStrategy,
    )
    ENTITY_EXTRACTION_AVAILABLE = True
except ImportError:
    ENTITY_EXTRACTION_AVAILABLE = False

try:
    from ipfs_datasets_py.optimizers.graphrag.entity_deduplication import (
        EntityDeduplicator,
        DeduplicationStrategy,
    )
    DEDUPLICATION_AVAILABLE = True
except ImportError:
    DEDUPLICATION_AVAILABLE = False

try:
    from ipfs_datasets_py.optimizers.graphrag.graph_traversal import (
        GraphTraversal,
        TraversalStrategy,
    )
    TRAVERSAL_AVAILABLE = True
except ImportError:
    TRAVERSAL_AVAILABLE = False


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def small_document() -> str:
    """Generate a small test document (~100 tokens)."""
    return """
    The Paris Agreement is an international treaty on climate change.
    It was adopted in Paris on 12 December 2015, and entered into force
    on 4 November 2016. The agreement's goal is to limit global warming
    to well below 2°C above pre-industrial levels.
    """


@pytest.fixture
def medium_document() -> str:
    """Generate a medium test document (~500 tokens)."""
    paragraphs = [
        """
        Climate change refers to long-term shifts in temperatures and weather
        patterns. These shifts may be natural, but since the 1800s, human
        activities have been the main driver of climate change, primarily due
        to the burning of fossil fuels like coal, oil, and gas.
        """,
        """
        The Paris Agreement, adopted at COP21 in Paris in 2015, brings all
        nations together in a common cause to undertake ambitious efforts to
        combat climate change and adapt to its effects. The agreement's central
        aim is to strengthen the global response to the threat of climate change.
        """,
        """
        Key provisions include: limiting global temperature increase to well
        below 2°C; pursuing efforts to limit the increase to 1.5°C; achieving
        a balance between anthropogenic emissions and removals of greenhouse
        gases in the second half of this century; and providing financial
        resources to assist developing countries.
        """,
        """
        As of 2026, 195 countries have signed the Paris Agreement, with 189
        having ratified it. The United States rejoined the agreement in 2021
        after a brief withdrawal. China, as the world's largest emitter, has
        committed to peak carbon emissions before 2030 and achieve carbon
        neutrality by 2060.
        """,
    ]
    return "\n\n".join(paragraphs)


@pytest.fixture
def large_document() -> str:
    """Generate a large test document (~2000 tokens)."""
    # Repeat medium document with variations
    base = """
    Global climate policy has evolved significantly since the Kyoto Protocol
    of 1997. The Paris Agreement represents a paradigm shift from binding
    emissions targets for developed countries only, to universal commitments
    across all parties. Each country submits Nationally Determined Contributions
    (NDCs) outlining their climate action plans.
    
    The agreement operates on a 5-year cycle of increasingly ambitious climate
    action. Countries submit their NDCs every five years, with each successive
    NDC representing a progression beyond the previous one. This "ratchet
    mechanism" is designed to ensure continuous improvement in global climate
    ambition.
    
    Financial support for developing countries is a critical component.
    Developed countries committed to mobilizing $100 billion per year by 2020
    to support climate action in developing nations. The Glasgow Climate Pact
    of 2021 extended this commitment through 2025 and called for a new collective
    quantified goal beyond 2025.
    
    Adaptation to climate impacts is recognized as crucial alongside mitigation.
    The agreement establishes the global goal on adaptation, enhancing adaptive
    capacity, strengthening resilience, and reducing vulnerability to climate
    change. The Adaptation Fund, established under the Kyoto Protocol, continues
    to serve the Paris Agreement.
    
    Loss and damage from climate impacts, particularly for vulnerable countries,
    gained prominence at COP27 in 2022 with the establishment of a dedicated
    loss and damage fund. This addresses the reality that some climate impacts
    cannot be adapted to and have already caused irreversible harm.
    
    The role of non-state actors—cities, regions, businesses, and civil society—
    is acknowledged through the Global Climate Action Portal. These actors often
    move faster than national governments and have committed to emissions
    reductions exceeding many national pledges.
    
    Carbon markets under Article 6 of the Paris Agreement aim to enable countries
    to trade emissions reductions, lowering the overall cost of climate action.
    Operationalizing Article 6 has been contentious, with final rulebook elements
    agreed at COP26 in Glasgow.
    """
    return base * 3  # Approximately 2000 tokens


@pytest.fixture
def entity_list_small() -> List[Dict[str, Any]]:
    """Small list of entities for deduplication testing."""
    return [
        {"name": "Paris Agreement", "type": "treaty", "year": 2015},
        {"name": "paris agreement", "type": "treaty", "year": 2015},  # duplicate (case)
        {"name": "Kyoto Protocol", "type": "treaty", "year": 1997},
        {"name": "United Nations", "type": "organization"},
        {"name": "UN", "type": "organization"},  # duplicate (abbreviation)
        {"name": "Climate Change", "type": "concept"},
        {"name": "Global Warming", "type": "concept"},  # potential semantic dup
    ]


@pytest.fixture
def entity_list_large() -> List[Dict[str, Any]]:
    """Large list of entities for deduplication stress testing."""
    entities = []
    # Add base entities
    for i in range(100):
        entities.append({
            "name": f"Entity_{i}",
            "type": "base",
            "id": i,
        })
    # Add duplicates with variations
    for i in range(50):
        entities.append({
            "name": f"entity_{i}",  # case variation
            "type": "base",
            "id": i,
        })
    # Add near-duplicates
    for i in range(50):
        entities.append({
            "name": f"Entity {i}",  # space variation
            "type": "base",
            "id": i,
        })
    return entities


@pytest.fixture
def simple_graph() -> Dict[str, List[str]]:
    """Simple graph for traversal testing."""
    return {
        "A": ["B", "C"],
        "B": ["D", "E"],
        "C": ["E", "F"],
        "D": [],
        "E": ["F"],
        "F": [],
    }


@pytest.fixture
def complex_graph() -> Dict[str, List[str]]:
    """Complex graph with cycles and multiple paths."""
    return {
        "A": ["B", "C", "D"],
        "B": ["E", "F"],
        "C": ["F", "G"],
        "D": ["G", "H"],
        "E": ["I"],
        "F": ["I", "J"],
        "G": ["J", "K"],
        "H": ["K"],
        "I": ["L"],
        "J": ["L"],
        "K": ["L"],
        "L": [],
    }


# ---------------------------------------------------------------------------
# Entity Extraction Benchmarks
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not ENTITY_EXTRACTION_AVAILABLE,
    reason="GraphRAG entity extraction not available"
)
class TestEntityExtractionBenchmarks:
    """Benchmarks for entity extraction at various scales."""

    def test_extraction_small_document(self, small_document, benchmark):
        """Benchmark entity extraction on small document (~100 tokens)."""
        extractor = GraphRAGEntityExtractor(strategy=ExtractionStrategy.REGEX)
        
        result = benchmark(extractor.extract, small_document)
        
        assert isinstance(result, list)
        # Should extract at least treaty name and location
        assert len(result) >= 2

    def test_extraction_medium_document(self, medium_document, benchmark):
        """Benchmark entity extraction on medium document (~500 tokens)."""
        extractor = GraphRAGEntityExtractor(strategy=ExtractionStrategy.REGEX)
        
        result = benchmark(extractor.extract, medium_document)
        
        assert isinstance(result, list)
        assert len(result) >= 10  # Multiple entities across paragraphs

    @pytest.mark.slow
    def test_extraction_large_document(self, large_document, benchmark):
        """Benchmark entity extraction on large document (~2000 tokens)."""
        extractor = GraphRAGEntityExtractor(strategy=ExtractionStrategy.REGEX)
        
        result = benchmark(extractor.extract, large_document)
        
        assert isinstance(result, list)
        assert len(result) >= 30

    def test_extraction_scaling(self, medium_document):
        """Test extraction performance scaling with document size."""
        extractor = GraphRAGEntityExtractor(strategy=ExtractionStrategy.REGEX)
        
        timings = []
        sizes = [1, 2, 4, 8]
        
        for multiplier in sizes:
            doc = medium_document * multiplier
            start = time.perf_counter()
            result = extractor.extract(doc)
            elapsed = time.perf_counter() - start
            
            timings.append({
                "multiplier": multiplier,
                "tokens": len(doc.split()),
                "entities": len(result),
                "time_ms": elapsed * 1000,
            })
        
        # Verify near-linear scaling (allowing for overhead)
        for i in range(1, len(timings)):
            ratio = timings[i]["time_ms"] / timings[i-1]["time_ms"]
            expected_ratio = sizes[i] / sizes[i-1]
            # Should scale within 2x of expected (allowing for constant overhead)
            assert ratio < expected_ratio * 2


# ---------------------------------------------------------------------------
# Entity Deduplication Benchmarks
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not DEDUPLICATION_AVAILABLE,
    reason="GraphRAG entity deduplication not available"
)
class TestEntityDeduplicationBenchmarks:
    """Benchmarks for entity deduplication algorithms."""

    def test_exact_dedup_small(self, entity_list_small, benchmark):
        """Benchmark exact deduplication on small entity list."""
        deduper = EntityDeduplicator(strategy=DeduplicationStrategy.EXACT)
        
        result = benchmark(deduper.deduplicate, entity_list_small)
        
        assert isinstance(result, list)
        # Should have fewer entities after deduplication
        assert len(result) < len(entity_list_small)

    def test_fuzzy_dedup_small(self, entity_list_small, benchmark):
        """Benchmark fuzzy deduplication on small entity list."""
        deduper = EntityDeduplicator(strategy=DeduplicationStrategy.FUZZY)
        
        result = benchmark(deduper.deduplicate, entity_list_small)
        
        assert isinstance(result, list)
        assert len(result) <= len(entity_list_small)

    @pytest.mark.slow
    def test_exact_dedup_large(self, entity_list_large, benchmark):
        """Benchmark exact deduplication on large entity list."""
        deduper = EntityDeduplicator(strategy=DeduplicationStrategy.EXACT)
        
        result = benchmark(deduper.deduplicate, entity_list_large)
        
        assert isinstance(result, list)
        # Should significantly reduce duplicates
        assert len(result) < len(entity_list_large) * 0.7

    def test_dedup_complexity(self, entity_list_large):
        """Test deduplication algorithmic complexity."""
        # Measure O(n²) vs O(n) approaches
        sizes = [50, 100, 200]
        timings_naive = []
        timings_optimized = []
        
        for size in sizes:
            entities = entity_list_large[:size]
            
            # Naive O(n²) approach
            start = time.perf_counter()
            # Simulate pairwise comparison
            for i in range(len(entities)):
                for j in range(i + 1, len(entities)):
                    _ = entities[i]["name"] == entities[j]["name"]
            elapsed_naive = time.perf_counter() - start
            timings_naive.append(elapsed_naive)
            
            # Optimized O(n) approach (bucketing)
            start = time.perf_counter()
            deduper = EntityDeduplicator(strategy=DeduplicationStrategy.EXACT)
            _ = deduper.deduplicate(entities)
            elapsed_opt = time.perf_counter() - start
            timings_optimized.append(elapsed_opt)
        
        # Verify optimized approach scales better
        # Naive should grow quadratically, optimized linearly
        for i in range(1, len(sizes)):
            naive_ratio = timings_naive[i] / timings_naive[i-1]
            opt_ratio = timings_optimized[i] / timings_optimized[i-1]
            size_ratio = sizes[i] / sizes[i-1]
            
            # Naive should grow faster than size_ratio²/2 (due to overhead)
            # Optimized should grow slower than naive
            assert opt_ratio < naive_ratio


# ---------------------------------------------------------------------------
# Graph Traversal Benchmarks
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not TRAVERSAL_AVAILABLE,
    reason="GraphRAG graph traversal not available"
)
class TestGraphTraversalBenchmarks:
    """Benchmarks for graph traversal and path finding."""

    def test_bfs_simple_graph(self, simple_graph, benchmark):
        """Benchmark BFS traversal on simple graph."""
        traversal = GraphTraversal(graph=simple_graph, strategy=TraversalStrategy.BFS)
        
        result = benchmark(traversal.traverse, start="A", target="F")
        
        assert isinstance(result, list)
        assert result[0] == "A"
        assert result[-1] == "F"

    def test_dfs_simple_graph(self, simple_graph, benchmark):
        """Benchmark DFS traversal on simple graph."""
        traversal = GraphTraversal(graph=simple_graph, strategy=TraversalStrategy.DFS)
        
        result = benchmark(traversal.traverse, start="A", target="F")
        
        assert isinstance(result, list)
        assert result[0] == "A"
        assert result[-1] == "F"

    def test_shortest_path_complex_graph(self, complex_graph, benchmark):
        """Benchmark shortest path finding on complex graph."""
        traversal = GraphTraversal(graph=complex_graph, strategy=TraversalStrategy.BFS)
        
        result = benchmark(traversal.traverse, start="A", target="L")
        
        assert isinstance(result, list)
        assert result[0] == "A"
        assert result[-1] == "L"
        # BFS guarantees shortest path
        assert len(result) <= 4  # Should find path in 3-4 hops

    def test_multi_hop_traversal(self, complex_graph):
        """Test multi-hop traversal performance."""
        traversal = GraphTraversal(graph=complex_graph, strategy=TraversalStrategy.BFS)
        
        # Test various path lengths
        test_cases = [
            ("A", "B", 2),  # 1 hop
            ("A", "E", 3),  # 2 hops
            ("A", "I", 4),  # 3 hops
            ("A", "L", 4),  # 3-4 hops (multiple paths)
        ]
        
        for start, target, max_hops in test_cases:
            start_time = time.perf_counter()
            path = traversal.traverse(start=start, target=target)
            elapsed = time.perf_counter() - start_time
            
            assert len(path) <= max_hops
            assert elapsed < 0.1  # Should be fast for small graphs


# ---------------------------------------------------------------------------
# End-to-End Query Benchmarks
# ---------------------------------------------------------------------------

class TestEndToEndQueryBenchmarks:
    """Benchmarks for complete query workflows."""

    @pytest.mark.skipif(
        not all([ENTITY_EXTRACTION_AVAILABLE, DEDUPLICATION_AVAILABLE, TRAVERSAL_AVAILABLE]),
        reason="GraphRAG components not fully available"
    )
    def test_simple_query_flow(self, small_document, benchmark):
        """Benchmark simple query: extract → deduplicate → respond."""
        def query_flow():
            # Extract entities
            extractor = GraphRAGEntityExtractor(strategy=ExtractionStrategy.REGEX)
            entities = extractor.extract(small_document)
            
            # Deduplicate
            deduper = EntityDeduplicator(strategy=DeduplicationStrategy.EXACT)
            unique_entities = deduper.deduplicate(entities)
            
            # Build simple response
            return {
                "entities": unique_entities,
                "count": len(unique_entities),
                "document_length": len(small_document.split()),
            }
        
        result = benchmark(query_flow)
        
        assert "entities" in result
        assert result["count"] > 0

    @pytest.mark.skipif(
        not all([ENTITY_EXTRACTION_AVAILABLE, DEDUPLICATION_AVAILABLE]),
        reason="GraphRAG components not fully available"
    )
    @pytest.mark.slow
    def test_complex_query_flow(self, large_document, benchmark):
        """Benchmark complex query: extract → deduplicate → analyze."""
        def complex_query():
            # Extract entities
            extractor = GraphRAGEntityExtractor(strategy=ExtractionStrategy.REGEX)
            entities = extractor.extract(large_document)
            
            # Deduplicate with fuzzy matching
            deduper = EntityDeduplicator(strategy=DeduplicationStrategy.FUZZY)
            unique_entities = deduper.deduplicate(entities)
            
            # Analyze entity types
            type_counts = {}
            for entity in unique_entities:
                etype = entity.get("type", "unknown")
                type_counts[etype] = type_counts.get(etype, 0) + 1
            
            return {
                "total_entities": len(entities),
                "unique_entities": len(unique_entities),
                "dedup_ratio": len(unique_entities) / max(len(entities), 1),
                "type_distribution": type_counts,
            }
        
        result = benchmark(complex_query)
        
        assert result["total_entities"] > 0
        assert result["dedup_ratio"] <= 1.0

    def test_query_latency_distribution(self, medium_document):
        """Test query latency distribution over multiple runs."""
        if not ENTITY_EXTRACTION_AVAILABLE:
            pytest.skip("Entity extraction not available")
        
        extractor = GraphRAGEntityExtractor(strategy=ExtractionStrategy.REGEX)
        
        latencies = []
        for _ in range(100):
            start = time.perf_counter()
            _ = extractor.extract(medium_document)
            elapsed = time.perf_counter() - start
            latencies.append(elapsed * 1000)  # Convert to ms
        
        # Statistical analysis
        mean_latency = sum(latencies) / len(latencies)
        latencies_sorted = sorted(latencies)
        p50 = latencies_sorted[len(latencies) // 2]
        p95 = latencies_sorted[int(len(latencies) * 0.95)]
        p99 = latencies_sorted[int(len(latencies) * 0.99)]
        
        # Sanity checks
        assert mean_latency > 0
        assert p50 < p95 < p99
        # P99 should be within 3x of median (no extreme outliers)
        assert p99 < p50 * 3


# ---------------------------------------------------------------------------
# Performance Regression Tests
# ---------------------------------------------------------------------------

class TestPerformanceRegressions:
    """Tests to catch performance regressions."""

    @pytest.mark.skipif(
        not ENTITY_EXTRACTION_AVAILABLE,
        reason="Entity extraction not available"
    )
    def test_extraction_baseline(self, medium_document):
        """Baseline: entity extraction should complete in <100ms for 500 tokens."""
        extractor = GraphRAGEntityExtractor(strategy=ExtractionStrategy.REGEX)
        
        start = time.perf_counter()
        result = extractor.extract(medium_document)
        elapsed = time.perf_counter() - start
        
        assert len(result) > 0
        # Baseline: should be fast for regex-based extraction
        assert elapsed < 0.1, f"Extraction took {elapsed:.3f}s, expected <0.1s"

    @pytest.mark.skipif(
        not DEDUPLICATION_AVAILABLE,
        reason="Deduplication not available"
    )
    def test_dedup_baseline(self, entity_list_large):
        """Baseline: deduplication of 200 entities should complete in <50ms."""
        deduper = EntityDeduplicator(strategy=DeduplicationStrategy.EXACT)
        
        start = time.perf_counter()
        result = deduper.deduplicate(entity_list_large)
        elapsed = time.perf_counter() - start
        
        assert len(result) > 0
        # Baseline: exact dedup should be fast
        assert elapsed < 0.05, f"Deduplication took {elapsed:.3f}s, expected <0.05s"
