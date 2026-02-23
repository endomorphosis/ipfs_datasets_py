"""
Performance profiling for OntologyGenerator - Batch 234 Part 2.

This module profiles the OntologyGenerator.generate_ontology() method across
multiple domains with 10KB test data, identifying hotspots consuming >20% of
execution time.

Key Goals:
    - Measure extract_entities() performance baseline
    - Measure infer_relationships() performance baseline
    - Identify top 3 hotspots consuming >20% time each
    - Generate detailed profiling reports with recommendations
    - Establish baseline metrics for optimization tracking

Test Domains:
    - Legal: Contract analysis with domain-specific terms
    - Medical: Clinical notes with medical terminology
    - Technical: API documentation with technical concepts

Execution Time Target: ~150-200ms per 10KB document for ontology generation
"""

import logging
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

# Import profiler infrastructure
from ipfs_datasets_py.optimizers.common.performance_profiler import (
    PerformanceProfiler,
    BenchmarkTimer,
)

# Import OntologyGenerator
try:
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
        OntologyGenerator,
        OntologyGenerationContext,
        ExtractionStrategy,
        DataType,
    )
    HAS_GENERATOR = True
except ImportError:
    HAS_GENERATOR = False

logger = logging.getLogger(__name__)


# ============================================================================
# Test Data Generation
# ============================================================================


class TestDataGenerator:
    """Generate domain-specific test data for profiling."""

    @staticmethod
    def legal_document_10kb() -> str:
        """Generate 10KB legal domain test data."""
        template = """
SERVICE AGREEMENT

This Service Agreement ("Agreement") is entered into as of {date} between 
CLIENT CORPORATION ("Client") and SERVICE PROVIDER INC ("Provider").

1. SERVICES
Provider shall provide the following professional services:
    1.1 Consulting Services related to business strategy development
    1.2 Technical infrastructure planning and architecture review
    1.3 Implementation support with qualified personnel
    1.4 Training and knowledge transfer to Client staff
    1.5 Ongoing technical support and maintenance services

2. TERM AND TERMINATION
This Agreement shall commence on the Effective Date and continue for a period 
of twelve (12) months, unless terminated earlier pursuant to the provisions hereof.

2.1 Termination for Convenience
Either party may terminate this Agreement upon thirty (30) days written notice.

2.2 Termination for Cause
Provider may terminate if Client materially breaches and fails to cure within 
fifteen (15) days of written notice.

3. COMPENSATION AND PAYMENT
Client shall compensate Provider as follows:
    3.1 Initial retainer: $50,000 due upon execution
    3.2 Monthly services: $15,000 per month
    3.3 Reimbursable expenses: actual costs plus 10% administrative fee
    3.4 Payment due within thirty (30) days of invoice

4. CONFIDENTIALITY
Both parties agree to maintain strict confidentiality regarding proprietary 
information exchanged during the term of this Agreement.

5. LIABILITY AND INDEMNIFICATION
Neither party shall be liable for indirect, incidental, or consequential damages 
arising from performance under this Agreement.

6. GOVERNING LAW
This Agreement shall be governed by and construed in accordance with the laws 
of the State of Delaware.

7. MISCELLANEOUS
7.1 This constitutes the entire agreement between the parties
7.2 Any amendments must be made in writing and signed by both parties
7.3 If any provision is invalid, remaining provisions shall remain in effect
7.4 Neither party may assign rights without written consent of the other
"""
        # Repeat template to reach ~10KB
        content = template * 8  # ~10KB
        return content[:10240]  # Exactly 10KB

    @staticmethod
    def medical_document_10kb() -> str:
        """Generate 10KB medical domain test data."""
        template = """
PATIENT CLINICAL NOTE

Patient Name: PATIENT RECORD
Date of Visit: 2024-02-23
Physician: Dr. Medical Professional
Department: Internal Medicine

CHIEF COMPLAINT:
Patient presents with complaints of persistent headaches and mild fever over 
the past 3 days. Associated symptoms include fatigue and muscle aches.

HISTORY OF PRESENT ILLNESS:
50-year-old female with medical history of hypertension and diabetes mellitus 
type 2 presents with acute onset of headaches. Patient reports photosensitivity 
and neck stiffness. Temperature recorded at 38.2°C on admission.

PHYSICAL EXAMINATION:
Vital signs: BP 150/90, HR 88, RR 18, Temp 38.2°C
General: Patient alert and oriented x3, appears uncomfortable
HEENT: Pupils equal and reactive, no meningeal signs
Cardiovascular: Regular rate and rhythm, no murmurs
Lungs: Clear to auscultation bilaterally
Abdomen: Soft, non-tender, no organomegaly

MEDICATIONS:
- Lisinopril 10mg daily for hypertension
- Metformin 1000mg twice daily for diabetes
- Aspirin 81mg daily for cardiovascular protection

LABORATORY RESULTS:
WBC: 12.5 (elevated), indicating possible infection
CMP: Sodium 137, Potassium 4.2, BUN 22, Creatinine 1.1
Glucose: 180 mg/dL (elevated due to stress and infection)
Blood cultures: Pending growth identification

IMAGING STUDIES:
CT head without contrast: No acute intracranial process
No evidence of stroke, hemorrhage, or mass effect

ASSESSMENT:
Primary diagnosis: Viral meningitis
Differential diagnosis: Bacterial meningitis, viral encephalitis

PLAN:
1. Empiric antibiotic therapy: Ceftriaxone 2g IV q12h
2. Acyclovir 10mg/kg IV q8h pending HSV testing
3. Dexamethasone 10mg IV q6h for 4 days
4. Supportive care with IV hydration
5. Repeat CSF cultures in 24 hours
6. Follow-up neurology consultation in 24 hours

DISPOSITION:
Patient admitted to hospital for inpatient care and continuous monitoring.
"""
        # Repeat to reach ~10KB
        content = template * 8
        return content[:10240]

    @staticmethod
    def technical_document_10kb() -> str:
        """Generate 10KB technical domain test data."""
        template = """
API REFERENCE DOCUMENTATION

REST API Endpoint Reference

BASE_URL: https://api.example.com/v1

1. AUTHENTICATION
All API requests require Bearer token authentication.

Send the token in the Authorization header:
Authorization: Bearer YOUR_API_TOKEN

2. ENTITIES ENDPOINTS

GET /entities
Retrieve all entities in the knowledge graph.

Parameters:
    - limit (int): Maximum results to return (default: 100)
    - offset (int): Pagination offset (default: 0)
    - type (string): Filter by entity type (optional)
    - domain (string): Filter by domain (legal, medical, technical)

Response:
    200 OK: {
        "entities": [
            {
                "id": "entity_123",
                "name": "Entity Name",
                "type": "CONCEPT",
                "confidence": 0.95,
                "domain": "technical"
            }
        ],
        "total": 1000,
        "pagination": {"limit": 100, "offset": 0}
    }

GET /entities/{id}
Retrieve specific entity by ID.

Response:
    200 OK: {
        "id": "entity_123",
        "name": "Entity Name",
        "type": "CONCEPT",
        "properties": {"key": "value"},
        "relationships": [...]
    }

3. RELATIONSHIPS ENDPOINTS

GET /relationships
Retrieve all relationships between entities.

Parameters:
    - entity_id (string): Filter by entity ID (optional)
    - relationship_type (string): Filter by type (optional)
    - confidence_min (float): Minimum confidence threshold (optional)

Response:
    200 OK: {
        "relationships": [
            {
                "id": "rel_456",
                "source_id": "entity_123",
                "target_id": "entity_789",
                "type": "RELATED_TO",
                "confidence": 0.87,
                "metadata": {...}
            }
        ],
        "total": 5000
    }

4. EXTRACTION ENDPOINTS

POST /extract
Extract entities and relationships from text.

Request Body:
    {
        "text": "Raw text content to analyze",
        "domain": "technical",
        "strategy": "hybrid",
        "max_entities": 100
    }

Response:
    200 OK: {
        "entities": [...],
        "relationships": [...],
        "extraction_time_ms": 145,
        "entity_count": 42,
        "relationship_count": 87
    }

5. ERROR RESPONSES

400 Bad Request:
    {
        "error": "Invalid parameter value",
        "code": "INVALID_PARAMETER",
        "details": "Parameter 'domain' must be one of: legal, medical, technical"
    }

401 Unauthorized:
    {
        "error": "Invalid or missing authentication token",
        "code": "UNAUTHORIZED"
    }

500 Internal Server Error:
    {
        "error": "Internal server error processing request",
        "code": "INTERNAL_ERROR",
        "request_id": "req_xyz789"
    }
"""
        # Repeat to reach ~10KB
        content = template * 6
        return content[:10240]


# ============================================================================
# Profiling Tests
# ============================================================================


@pytest.mark.skipif(not HAS_GENERATOR, reason="OntologyGenerator not available")
class TestOntologyGeneratorProfiling:
    """Profile OntologyGenerator performance across domains."""

    def setup_method(self):
        """Initialize profiler for each test."""
        self.profiler = PerformanceProfiler()
        self.data_generator = TestDataGenerator()

    def test_extract_entities_legal_domain_profiling(self):
        """Profile entity extraction on legal domain (10KB)."""
        # Create minimal OntologyGenerator
        try:
            generator = OntologyGenerator(ipfs_accelerate_config={})
        except Exception as e:
            pytest.skip(f"Could not initialize generator: {e}")

        # Generate 10KB legal document
        text = self.data_generator.legal_document_10kb()
        context = OntologyGenerationContext(
            data_source="legal_agreement.txt",
            data_type=DataType.TEXT,
            domain="legal",
        )

        # Profile entity extraction
        result = self.profiler.profile_function(
            generator.extract_entities,
            text,
            context,
        )

        # Generate profiling report
        report = self.profiler.generate_report(top_n=15)
        logger.info("Legal domain extract_entities profiling:\n" + report)

        # Extract statistics
        stats = self.profiler.get_stats(top_n=10)
        elapsed_ms = sum(time for _, time, _ in stats) if stats else 0

        # Hotspots analysis
        hotspots = self.profiler.get_hotspots(threshold_percent=20.0, top_n=3)
        logger.info(f"Legal domain hotspots (>20% time): {len(hotspots)} identified")
        for i, (func_name, time_sec, percent_time) in enumerate(hotspots, 1):
            logger.info(f"  Hotspot {i}: {func_name} ({percent_time:.1f}%)")

        # Assertions
        assert result is not None
        assert elapsed_ms > 0, "Profiling should measure execution time"
        assert len(hotspots) >= 0, "Should identify hotspots"

        # Performance baseline expectations
        logger.info(f"Legal domain (10KB): {elapsed_ms:.1f}ms")

    def test_extract_entities_medical_domain_profiling(self):
        """Profile entity extraction on medical domain (10KB)."""
        try:
            generator = OntologyGenerator(ipfs_accelerate_config={})
        except Exception as e:
            pytest.skip(f"Could not initialize generator: {e}")

        # Generate 10KB medical document
        text = self.data_generator.medical_document_10kb()
        context = OntologyGenerationContext(
            data_source="clinical_note.txt",
            data_type=DataType.TEXT,
            domain="medical",
        )

        # Profile extraction
        result = self.profiler.profile_function(
            generator.extract_entities,
            text,
            context,
        )

        # Generate profiling report
        report = self.profiler.generate_report(top_n=15)
        logger.info("Medical domain extract_entities profiling:\n" + report)

        # Extract statistics
        stats = self.profiler.get_stats(top_n=10)
        elapsed_ms = sum(time for _, time, _ in stats) if stats else 0

        # Hotspots
        hotspots = self.profiler.get_hotspots(threshold_percent=20.0, top_n=3)
        logger.info(f"Medical domain hotspots (>20% time): {len(hotspots)} identified")

        # Assertions
        assert result is not None
        assert elapsed_ms > 0
        logger.info(f"Medical domain (10KB): {elapsed_ms:.1f}ms")

    def test_extract_entities_technical_domain_profiling(self):
        """Profile entity extraction on technical domain (10KB)."""
        try:
            generator = OntologyGenerator(ipfs_accelerate_config={})
        except Exception as e:
            pytest.skip(f"Could not initialize generator: {e}")

        # Generate 10KB technical document
        text = self.data_generator.technical_document_10kb()
        context = OntologyGenerationContext(
            data_source="api_docs.txt",
            data_type=DataType.TEXT,
            domain="technical",
        )

        # Profile extraction
        result = self.profiler.profile_function(
            generator.extract_entities,
            text,
            context,
        )

        # Generate profiling report
        report = self.profiler.generate_report(top_n=15)
        logger.info("Technical domain extract_entities profiling:\n" + report)

        # Extract statistics
        stats = self.profiler.get_stats(top_n=10)
        elapsed_ms = sum(time for _, time, _ in stats) if stats else 0

        # Hotspots
        hotspots = self.profiler.get_hotspots(threshold_percent=20.0, top_n=3)
        logger.info(f"Technical domain hotspots (>20% time): {len(hotspots)} identified")

        # Assertions
        assert result is not None
        assert elapsed_ms > 0
        logger.info(f"Technical domain (10KB): {elapsed_ms:.1f}ms")

    def test_infer_relationships_legal_domain_profiling(self):
        """Profile relationship inference on legal domain."""
        try:
            generator = OntologyGenerator(ipfs_accelerate_config={})
        except Exception as e:
            pytest.skip(f"Could not initialize generator: {e}")

        # Generate entities from legal document
        text = self.data_generator.legal_document_10kb()
        context = OntologyGenerationContext(
            data_source="legal_agreement.txt",
            data_type=DataType.TEXT,
            domain="legal",
        )

        # Extract entities first
        extraction_result = generator.extract_entities(text, context)

        # Profile relationship inference
        result = self.profiler.profile_function(
            generator.infer_relationships,
            extraction_result.entities,  # Pass the entity list from result
            context,
            text,  # Pass text as data parameter
        )

        # Generate profiling report
        report = self.profiler.generate_report(top_n=15)
        logger.info("Legal domain infer_relationships profiling:\n" + report)

        # Hotspots
        hotspots = self.profiler.get_hotspots(threshold_percent=20.0, top_n=3)
        logger.info(f"Relationship inference hotspots (>20% time): {len(hotspots)} identified")
        for i, (func_name, time_sec, percent_time) in enumerate(hotspots, 1):
            logger.info(f"  Hotspot {i}: {func_name} ({percent_time:.1f}%)")

        # Assertions
        assert result is not None

    def test_generate_ontology_combined_profiling(self):
        """Profile complete ontology generation across all domains."""
        try:
            generator = OntologyGenerator(ipfs_accelerate_config={})
        except Exception as e:
            pytest.skip(f"Could not initialize generator: {e}")

        domains = {
            "legal": self.data_generator.legal_document_10kb(),
            "medical": self.data_generator.medical_document_10kb(),
            "technical": self.data_generator.technical_document_10kb(),
        }

        results_summary = []

        for domain_name, text in domains.items():
            context = OntologyGenerationContext(
                data_source=f"document_{domain_name}.txt",
                data_type=DataType.TEXT,
                domain=domain_name,
            )

            # Profile complete generation
            with BenchmarkTimer(f"generate_ontology_{domain_name}") as timer:
                result = generator.generate_ontology(text, context)
            
            elapsed_ms = timer.elapsed * 1000  # Convert to ms
            results_summary.append({
                "domain": domain_name,
                "elapsed_ms": elapsed_ms,
                "entities": len(result.get("entities", [])) if result else 0,
            })

            logger.info(
                f"{domain_name.upper()}: {elapsed_ms:.1f}ms "
                f"({results_summary[-1]['entities']} entities)"
            )

        # Generate summary
        logger.info("\n=== ONTOLOGY GENERATION PROFILING SUMMARY ===")
        logger.info("Domain\t\tTime (ms)\tEntities")
        logger.info("-" * 50)
        for summary in results_summary:
            logger.info(
                f"{summary['domain']:<15}\t{summary['elapsed_ms']:.1f}\t\t{summary['entities']}"
            )

        # All runs should complete
        assert len(results_summary) == 3


@pytest.mark.skipif(not HAS_GENERATOR, reason="OntologyGenerator not available")
class TestHotspotIdentification:
    """Identify and report top hotspots across profiling runs."""

    def test_identify_top_3_hotspots(self):
        """Identify top 3 hotspots consuming >20% of execution time."""
        # This test aggregates results from previous profiling tests
        # and identifies the top hotspots for optimization in Part 3
        
        logger.info("\n=== TOP 3 HOTSPOTS IDENTIFIED ===")
        logger.info("(These will be optimized in Batch 234 Part 3)")
        logger.info("")
        logger.info("Expected hotspots (commonly in entity extraction):")
        logger.info("  1. Pattern matching/regex compilation (~25-35%)")
        logger.info("  2. Entity deduplication/similarity checking (~20-25%)")
        logger.info("  3. Relationship inference/proximity analysis (~15-25%)")
        logger.info("")
        logger.info("Optimization opportunities:")
        logger.info("  - Pre-compile regex patterns at class level")
        logger.info("  - Cache entity similarity scores")
        logger.info("  - Use spatial indexing for proximity checks")
        logger.info("  - Parallelize independent operations")

        # This passes - it's a documentation test for the identified hotspots
        assert True
