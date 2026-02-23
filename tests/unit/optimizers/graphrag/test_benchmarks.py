"""Performance benchmark tests for GraphRAG optimizer components.

Uses pytest-benchmark to track performance of critical operations over time.
Run with: pytest tests/unit/optimizers/graphrag/test_benchmarks.py --benchmark-only

These benchmarks help detect performance regressions in:
- Entity extraction
- Relationship inference
- Ontology evaluation
- Serialization operations
"""
from __future__ import annotations

import pytest
from typing import Any, Dict


class TestOntologyGeneratorBenchmarks:
    """Benchmarks for OntologyGenerator operations."""
    
    @pytest.fixture
    def generator(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
        return OntologyGenerator(use_ipfs_accelerate=False)
    
    @pytest.fixture
    def context(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerationContext, DataType, ExtractionStrategy,
        )
        return OntologyGenerationContext(
            data_source="benchmark",
            data_type=DataType.TEXT,
            domain="legal",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )
    
    @pytest.fixture
    def small_text(self):
        """Small document (50 words)."""
        return """
        Alice Smith works at Acme Corporation in New York. Bob Johnson is the CEO.
        The company was founded in 2010 and specializes in software development.
        Carol Williams manages the engineering team. The office is located at 123 Main Street.
        """
    
    @pytest.fixture
    def medium_text(self):
        """Medium document (200 words)."""
        return """
        This Employment Agreement is entered into between Acme Corporation (the "Employer")
        and John Smith (the "Employee") on January 1, 2024. The Employee shall be employed
        as a Senior Software Engineer in the Engineering Department. The Employer agrees to
        pay the Employee an annual salary of $150,000, payable in bi-weekly installments.
        
        The Employee's duties include designing, developing, and maintaining software applications,
        participating in code reviews, and collaborating with cross-functional teams. The Employee
        reports to Jane Doe, VP of Engineering, and works closely with the Product Management team.
        