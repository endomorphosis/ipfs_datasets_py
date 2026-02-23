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
        
        The term of employment begins on January 1, 2024 and continues until terminated by either
        party. Either party may terminate this agreement with 30 days written notice. The Employee
        agrees to comply with all company policies and maintain confidentiality of proprietary
        information. The Employer provides benefits including health insurance, 401(k) matching,
        and 20 days of paid time off annually.
        
        This agreement is governed by the laws of California. Both parties have read and understood
        the terms and agree to be bound by them. Signed on December 15, 2023.
        """
    
    @pytest.fixture
    def large_text(self):
        """Large document (500+ words)."""
        return """
        MASTER SERVICES AGREEMENT
        
        This Master Services Agreement ("Agreement") is entered into as of January 1, 2024
        ("Effective Date") by and between Acme Corporation, a Delaware corporation with its
        principal place of business at 123 Main Street, San Francisco, CA 94102 ("Company"),
        and TechServices Inc., a California corporation with its principal place of business
        at 456 Oak Avenue, Palo Alto, CA 94301 ("Vendor").
        
        RECITALS
        
        WHEREAS, Company desires to engage Vendor to provide certain professional services;
        and WHEREAS, Vendor is willing to provide such services subject to the terms and
        conditions set forth herein; NOW, THEREFORE, in consideration of the mutual covenants
        and agreements set forth herein, the parties agree as follows:
        
        1. SERVICES
        
        Vendor shall provide software development, consulting, and technical support services
        ("Services") as detailed in one or more Statements of Work ("SOW"). Each SOW shall
        specify the scope, deliverables, timeline, and fees for the Services. The parties
        shall execute each SOW in writing, and each SOW shall incorporate the terms of this
        Agreement by reference.
        
        2. TERM AND TERMINATION
        
        This Agreement shall commence on the Effective Date and continue for an initial term
        of twelve (12) months, unless earlier terminated as provided herein. The Agreement
        shall automatically renew for successive one-year periods unless either party provides
        written notice of non-renewal at least sixty (60) days prior to the end of the then-current
        term. Either party may terminate this Agreement or any SOW for convenience upon thirty
        (30) days prior written notice to the other party. Either party may terminate this
        Agreement immediately upon written notice if the other party materially breaches any
        provision and fails to cure such breach within fifteen (15) days of receiving written
        notice thereof.
        
        3. FEES AND PAYMENT
        
        Company shall pay Vendor the fees specified in each SOW. Unless otherwise stated in
        the SOW, Vendor shall invoice Company monthly for Services performed during the
        preceding month. Company shall pay all undisputed invoices within thirty (30) days
        of receipt. Late payments shall accrue interest at the rate of 1.5% per month or the
        maximum rate permitted by law, whichever is less. Company shall reimburse Vendor for
        reasonable, pre-approved expenses incurred in performing the Services.
        
        4. INTELLECTUAL PROPERTY
        
        All work product, deliverables, and intellectual property created by Vendor in performing
        the Services ("Work Product") shall be deemed works made for hire and shall be the
        exclusive property of Company. To the extent any Work Product is not deemed a work made
        for hire, Vendor hereby assigns all right, title, and interest in such Work Product to
        Company. Vendor retains ownership of any pre-existing intellectual property and grants
        Company a non-exclusive license to use such intellectual property solely in connection
        with the Work Product.
        """
    
    def test_benchmark_extract_entities_small(self, benchmark, generator, context, small_text):
        """Benchmark entity extraction on small document."""
        result = benchmark(generator.extract_entities, small_text, context)
        assert len(result.entities) > 0
    
    def test_benchmark_extract_entities_medium(self, benchmark, generator, context, medium_text):
        """Benchmark entity extraction on medium document."""
        result = benchmark(generator.extract_entities, medium_text, context)
        assert len(result.entities) > 0
    
    def test_benchmark_extract_entities_large(self, benchmark, generator, context, large_text):
        """Benchmark entity extraction on large document."""
        result = benchmark(generator.extract_entities, large_text, context)
        assert len(result.entities) > 0
    
    def test_benchmark_infer_relationships(self, benchmark, generator, context, medium_text):
        """Benchmark relationship inference (extraction includes inference)."""
        result = benchmark(generator.extract_entities, medium_text, context)
        assert len(result.relationships) >= 0  # May be 0 or more depending on text
    
    def test_benchmark_entity_deduplication(self, benchmark, generator):
        """Benchmark entity deduplication on result with duplicates."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            Entity, EntityExtractionResult, Relationship
        )
        
        # Create result with duplicate entities
        entities = [
            Entity(id="e1", text="Alice Smith", type="Person", confidence=0.9, properties={}),
            Entity(id="e2", text="alice smith", type="Person", confidence=0.8, properties={}),  # duplicate
            Entity(id="e3", text="Acme Corp", type="Organization", confidence=0.95, properties={}),
            Entity(id="e4", text="Bob Jones", type="Person", confidence=0.85, properties={}),
            Entity(id="e5", text="ACME CORP", type="Organization", confidence=0.9, properties={}),  # duplicate
        ]
        relationships = []
        result = EntityExtractionResult(
            entities=entities, relationships=relationships,
            confidence=0.85, metadata={}, errors=[]
        )
        
        deduped = benchmark(generator.deduplicate_entities, result)
        assert len(deduped.entities) < len(result.entities)


class TestOntologyCriticBenchmarks:
    """Benchmarks for OntologyCritic evaluation operations."""
    
    @pytest.fixture
    def critic(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        return OntologyCritic()
    
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
    
    def _make_ontology(self, num_entities: int, num_relationships: int) -> Dict[str, Any]:
        """Create a synthetic ontology for benchmarking."""
        entities = [
            {
                "id": f"e{i}",
                "text": f"Entity{i}",
                "type": ["Person", "Organization", "Location"][i % 3],
                "confidence": 0.8 + (i % 10) * 0.02,
                "properties": {"prop1": f"value{i}"},
            }
            for i in range(num_entities)
        ]
        
        relationships = [
            {
                "id": f"r{i}",
                "source_id": f"e{i % num_entities}",
                "target_id": f"e{(i + 1) % num_entities}",
                "type": ["works_for", "located_in", "part_of"][i % 3],
                "confidence": 0.7 + (i % 10) * 0.02,
            }
            for i in range(num_relationships)
        ]
        
        return {"entities": entities, "relationships": relationships}
    
    def test_benchmark_evaluate_small_ontology(self, benchmark, critic, context):
        """Benchmark evaluation of small ontology (10 entities, 5 relationships)."""
        ontology = self._make_ontology(10, 5)
        score = benchmark(critic.evaluate_ontology, ontology, context)
        assert 0.0 <= score.overall <= 1.0
    
    def test_benchmark_evaluate_medium_ontology(self, benchmark, critic, context):
        """Benchmark evaluation of medium ontology (50 entities, 75 relationships)."""
        ontology = self._make_ontology(50, 75)
        score = benchmark(critic.evaluate_ontology, ontology, context)
        assert 0.0 <= score.overall <= 1.0
    
    def test_benchmark_evaluate_large_ontology(self, benchmark, critic, context):
        """Benchmark evaluation of large ontology (200 entities, 500 relationships)."""
        ontology = self._make_ontology(200, 500)
        score = benchmark(critic.evaluate_ontology, ontology, context)
        assert 0.0 <= score.overall <= 1.0
    
    def test_benchmark_evaluate_batch(self, benchmark, critic, context):
        """Benchmark batch evaluation of multiple ontologies."""
        ontologies = [self._make_ontology(20, 30) for _ in range(10)]
        
        result = benchmark(critic.evaluate_batch, ontologies, context)
        assert result["count"] == 10
        assert "mean_overall" in result


class TestSerializationBenchmarks:
    """Benchmarks for serialization/deserialization operations."""
    
    @pytest.fixture
    def large_result(self):
        """Create a large EntityExtractionResult for benchmarking."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            Entity, EntityExtractionResult, Relationship
        )
        
        entities = [
            Entity(
                id=f"e{i}",
                text=f"Entity {i}",
                type=["Person", "Organization", "Location", "Event"][i % 4],
                confidence=0.7 + (i % 30) * 0.01,
                properties={"key1": f"value{i}", "key2": i * 10},
                source_span=(i * 10, i * 10 + 15) if i % 2 == 0 else None,
            )
            for i in range(100)
        ]
        
        relationships = [
            Relationship(
                id=f"r{i}",
                source_id=f"e{i}",
                target_id=f"e{(i + 1) % 100}",
                type=["works_for", "located_in", "part_of", "causes"][i % 4],
                confidence=0.6 + (i % 40) * 0.01,
                direction="forward",
                properties={"weight": i * 0.1},
            )
            for i in range(150)
        ]
        
        return EntityExtractionResult(
            entities=entities,
            relationships=relationships,
            confidence=0.82,
            metadata={"source": "benchmark", "version": "1.0"},
            errors=[],
        )
    
    def test_benchmark_to_dict(self, benchmark, large_result):
        """Benchmark EntityExtractionResult.to_dict()."""
        result = benchmark(large_result.to_dict)
        assert isinstance(result, dict)
        assert "entities" in result
    
    def test_benchmark_to_json(self, benchmark, large_result):
        """Benchmark EntityExtractionResult.to_json()."""
        result = benchmark(large_result.to_json)
        assert isinstance(result, str)
        assert len(result) > 0
    
    def test_benchmark_from_dict(self, benchmark, large_result):
        """Benchmark EntityExtractionResult.from_dict()."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
        
        as_dict = large_result.to_dict()
        restored = benchmark(EntityExtractionResult.from_dict, as_dict)
        assert len(restored.entities) == len(large_result.entities)
    
    def test_benchmark_entity_to_dict(self, benchmark):
        """Benchmark Entity.to_dict() serialization."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
        
        entity = Entity(
            id="test123",
            text="Alice Smith",
            type="Person",
            confidence=0.95,
            properties={"age": 30, "dept": "Engineering", "title": "Senior Engineer"},
            source_span=(10, 21),
        )
        
        result = benchmark(entity.to_dict)
        assert result["id"] == "test123"
    
    def test_benchmark_relationship_to_dict(self, benchmark):
        """Benchmark Relationship.to_dict() serialization."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        
        rel = Relationship(
            id="rel123",
            source_id="e1",
            target_id="e2",
            type="works_for",
            confidence=0.87,
            direction="forward",
            properties={"since": "2020", "role": "manager"},
        )
        
        result = benchmark(rel.to_dict)
        assert result["id"] == "rel123"
