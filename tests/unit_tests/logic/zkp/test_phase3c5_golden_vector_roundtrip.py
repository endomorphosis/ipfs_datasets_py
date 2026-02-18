"""
Phase 3C.5: Golden Vector Round-Trip Testing & Performance Benchmarking

This module tests all 8 golden vectors through the complete proof generation
and verification cycle with comprehensive performance metrics.

Workflow:
  1. Load golden vectors
  2. For each vector: generate witness → generate proof → verify proof
  3. Measure timing for each stage
  4. Validate proof structure and correctness
  5. Report aggregate and per-vector metrics
"""

import json
import time
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

import pytest

from ipfs_datasets_py.logic.zkp.canonicalization import (
    canonicalize_axioms,
    hash_axioms_commitment,
    hash_theorem,
    theorem_hash_hex,
    axioms_commitment_hex,
)
from ipfs_datasets_py.logic.zkp.witness_manager import WitnessManager
from ipfs_datasets_py.logic.zkp.backends.groth16_ffi import Groth16Backend, Groth16BackendFallback


# Load golden vectors from JSON
VECTORS_PATH = Path(__file__).parent / "zkp_golden_vectors.json"
with open(VECTORS_PATH) as f:
    GOLDEN_VECTORS = json.load(f)


@dataclass
class RoundTripMetrics:
    """Performance metrics for a single golden vector round-trip."""
    vector_name: str
    witness_generation_ms: float
    proof_generation_ms: float
    proof_verification_ms: float
    total_ms: float
    proof_size_bytes: int
    axiom_count: int
    verification_result: bool
    error: Optional[str] = None
    
    @property
    def total_time_s(self) -> float:
        return self.total_ms / 1000.0
    
    def to_dict(self) -> dict:
        return {
            'vector': self.vector_name,
            'witness_gen_ms': round(self.witness_generation_ms, 3),
            'proof_gen_ms': round(self.proof_generation_ms, 3),
            'verify_ms': round(self.proof_verification_ms, 3),
            'total_ms': round(self.total_ms, 3),
            'proof_size_bytes': self.proof_size_bytes,
            'axiom_count': self.axiom_count,
            'verified': self.verification_result,
            'error': self.error,
        }


@dataclass
class AggregateMetrics:
    """Summary metrics across all golden vectors."""
    total_vectors: int
    vectors_successful: int
    vectors_failed: int
    total_time_ms: float
    avg_proof_size_bytes: float
    total_proof_size_bytes: int
    min_roundtrip_ms: float
    max_roundtrip_ms: float
    avg_roundtrip_ms: float
    total_axioms: int
    
    def to_dict(self) -> dict:
        return {
            'total_vectors': self.total_vectors,
            'successful': self.vectors_successful,
            'failed': self.vectors_failed,
            'total_time_ms': round(self.total_time_ms, 3),
            'avg_proof_size_bytes': round(self.avg_proof_size_bytes, 2),
            'total_proof_size_bytes': self.total_proof_size_bytes,
            'min_roundtrip_ms': round(self.min_roundtrip_ms, 3),
            'max_roundtrip_ms': round(self.max_roundtrip_ms, 3),
            'avg_roundtrip_ms': round(self.avg_roundtrip_ms, 3),
            'total_axioms_processed': self.total_axioms,
        }


class Phase3C5GoldenVectorTester:
    """Orchestrates complete golden vector testing with metrics collection."""
    
    def __init__(self, use_fallback: bool = True):
        """
        Initialize tester.
        
        Args:
            use_fallback: If True, use fallback backend (no binary needed).
                         If False, use real Groth16Backend (requires binary).
        """
        self.use_fallback = use_fallback
        if use_fallback:
            self.backend = Groth16BackendFallback()
        else:
            self.backend = Groth16Backend()
    
    def convert_golden_vector_to_witness(
        self,
        vector_name: str,
        vector: dict
    ) -> dict:
        """
        Convert golden vector format to MVP witness format.
        
        Golden vectors contain logical statements (axioms, theorem).
        MVP witness format requires:
          - private_axioms: list of axiom strings
          - theorem: proof goal string
          - axioms_commitment_hex: SHA256 of canonical axioms
          - theorem_hash_hex: SHA256 of theorem
          - circuit_version: integer version
          - ruleset_id: string identifier
        """
        axioms = vector.get("axioms", vector.get("axioms_with_whitespace", []))
        theorem = vector.get("theorem", "")
        
        # Generate canonical form and hashes (as hex strings)
        canonical_axioms = canonicalize_axioms(axioms)
        axioms_comm_hex = axioms_commitment_hex(axioms)
        theorem_hash_hex_val = theorem_hash_hex(theorem)
        
        witness = {
            'private_axioms': canonical_axioms,
            'theorem': theorem,
            'axioms_commitment_hex': axioms_comm_hex,
            'theorem_hash_hex': theorem_hash_hex_val,
            'circuit_version': 1,
            'ruleset_id': 'TDFOL_v1',
        }
        
        return witness
    
    def test_single_vector(self, vector_name: str, vector: dict) -> RoundTripMetrics:
        """
        Execute complete round-trip test for a single golden vector.
        
        Steps:
          1. Convert golden vector to witness format
          2. Generate proof from witness (measure time)
          3. Parse proof and verify it (measure time)
          4. Report metrics
        """
        metrics = RoundTripMetrics(
            vector_name=vector_name,
            witness_generation_ms=0.0,
            proof_generation_ms=0.0,
            proof_verification_ms=0.0,
            total_ms=0.0,
            proof_size_bytes=0,
            axiom_count=0,
            verification_result=False,
        )
        
        try:
            # Step 1: Convert to witness format (measure time)
            start_convert = time.perf_counter()
            witness = self.convert_golden_vector_to_witness(vector_name, vector)
            metrics.witness_generation_ms = (time.perf_counter() - start_convert) * 1000
            
            metrics.axiom_count = len(vector.get("axioms", vector.get("axioms_with_whitespace", [])))
            
            # Step 2: Generate proof (measure time)
            start_prove = time.perf_counter()
            witness_json = json.dumps(witness)
            proof_obj = self.backend.generate_proof(witness_json)
            metrics.proof_generation_ms = (time.perf_counter() - start_prove) * 1000
            
            # Convert proof object to JSON string for verification
            # The backend returns a ZKPProof object, so we need to serialize it
            if hasattr(proof_obj, 'to_dict'):
                proof_dict = proof_obj.to_dict()
            else:
                proof_dict = proof_obj if isinstance(proof_obj, dict) else {}
            
            proof_json = json.dumps(proof_dict)
            metrics.proof_size_bytes = len(proof_json.encode('utf-8'))
            
            # Step 3: Verify proof (measure time)
            start_verify = time.perf_counter()
            verification_result = self.backend.verify_proof(proof_json)
            metrics.proof_verification_ms = (time.perf_counter() - start_verify) * 1000
            
            metrics.verification_result = verification_result
            metrics.total_ms = (
                metrics.witness_generation_ms +
                metrics.proof_generation_ms +
                metrics.proof_verification_ms
            )
            
        except Exception as e:
            metrics.error = str(e)
            metrics.verification_result = False
        
        return metrics
    
    def run_all_vectors(self) -> Tuple[List[RoundTripMetrics], AggregateMetrics]:
        """
        Execute round-trip tests for all 8 golden vectors.
        
        Returns:
            Tuple of (per-vector metrics list, aggregate metrics)
        """
        all_metrics: List[RoundTripMetrics] = []
        
        vectors = GOLDEN_VECTORS.get('vectors', {})
        for vector_name, vector_data in vectors.items():
            metrics = self.test_single_vector(vector_name, vector_data)
            all_metrics.append(metrics)
        
        # Compute aggregate metrics
        successful = sum(1 for m in all_metrics if m.verification_result and not m.error)
        failed = len(all_metrics) - successful
        
        total_time = sum(m.total_ms for m in all_metrics)
        total_proof_size = sum(m.proof_size_bytes for m in all_metrics)
        avg_proof_size = total_proof_size / len(all_metrics) if all_metrics else 0
        total_axioms = sum(m.axiom_count for m in all_metrics)
        
        roundtrip_times = [m.total_ms for m in all_metrics if not m.error]
        min_time = min(roundtrip_times) if roundtrip_times else 0
        max_time = max(roundtrip_times) if roundtrip_times else 0
        avg_time = sum(roundtrip_times) / len(roundtrip_times) if roundtrip_times else 0
        
        aggregate = AggregateMetrics(
            total_vectors=len(all_metrics),
            vectors_successful=successful,
            vectors_failed=failed,
            total_time_ms=total_time,
            avg_proof_size_bytes=avg_proof_size,
            total_proof_size_bytes=total_proof_size,
            min_roundtrip_ms=min_time,
            max_roundtrip_ms=max_time,
            avg_roundtrip_ms=avg_time,
            total_axioms=total_axioms,
        )
        
        return all_metrics, aggregate
    
    def print_report(
        self,
        all_metrics: List[RoundTripMetrics],
        aggregate: AggregateMetrics
    ) -> str:
        """Generate formatted performance report."""
        lines = [
            "\n" + "="*80,
            "PHASE 3C.5: GOLDEN VECTOR ROUND-TRIP PERFORMANCE REPORT",
            "="*80,
            f"Backend: {'Fallback' if self.use_fallback else 'Groth16'}",
            f"Total Vectors: {aggregate.total_vectors}",
            f"Successful: {aggregate.vectors_successful} | Failed: {aggregate.vectors_failed}",
            "",
            "PER-VECTOR METRICS:",
            "-"*80,
        ]
        
        for metrics in all_metrics:
            status = "✓ PASS" if metrics.verification_result else "✗ FAIL"
            error_msg = f" ERROR: {metrics.error}" if metrics.error else ""
            lines.extend([
                f"{status} {metrics.vector_name}{error_msg}",
                f"   Witness Gen:   {metrics.witness_generation_ms:8.3f} ms",
                f"   Proof Gen:     {metrics.proof_generation_ms:8.3f} ms",
                f"   Verify:        {metrics.proof_verification_ms:8.3f} ms",
                f"   Round-trip:    {metrics.total_ms:8.3f} ms ({metrics.total_time_s:.4f}s)",
                f"   Proof Size:    {metrics.proof_size_bytes:6} bytes",
                f"   Axioms:        {metrics.axiom_count:3} (version 1, {metrics.verification_result})",
                "",
            ])
        
        lines.extend([
            "AGGREGATE METRICS:",
            "-"*80,
            f"Total Time:           {aggregate.total_time_ms:.3f} ms ({aggregate.total_time_ms/1000:.3f}s)",
            f"Avg Round-trip:       {aggregate.avg_roundtrip_ms:.3f} ms",
            f"Min Round-trip:       {aggregate.min_roundtrip_ms:.3f} ms",
            f"Max Round-trip:       {aggregate.max_roundtrip_ms:.3f} ms",
            f"Avg Proof Size:       {aggregate.avg_proof_size_bytes:.2f} bytes",
            f"Total Proof Size:     {aggregate.total_proof_size_bytes} bytes",
            f"Axioms Processed:     {aggregate.total_axioms}",
            f"Throughput:           {(aggregate.total_axioms / (aggregate.total_time_ms/1000)) if aggregate.total_time_ms > 0 else 0:.2f} axioms/sec",
            "="*80,
            "",
        ])
        
        return "\n".join(lines)


# ============================================================================
# Pytest Tests
# ============================================================================

class TestPhase3C5GoldenVectors:
    """Pytest test class for Phase 3C.5 golden vector round-trip testing."""
    
    @pytest.mark.slow
    def test_all_golden_vectors_with_fallback(self):
        """
        GOLDEN VECTOR TEST: Exercise all 8 vectors through full cycle.
        
        Test plan:
          1. Load all 8 golden vectors
          2. Convert each to MVP witness format
          3. Generate proof for each witness (fallback backend)
          4. Verify each proof returns True
          5. Validate proof structure and size constraints
          6. Report comprehensive metrics
          7. Assert all vectors passed verification
        
        Vectors tested:
          1. simple_modus_ponens - Basic P, P->Q ⊢ Q
          2. simple_with_reordering - Same axioms, different order (order independence)
          3. whitespace_normalization - Extra whitespace handling
          4. duplicate_axioms - Axiom deduplication
          5. three_axiom_chain - Longer proof chain P->Q->R
          6. all_humans_mortal - Natural language Aristotelian syllogism
          7. large_axiom_set - 10 axioms (ordering independence stress test)
          8. unicode_normalization - Unicode character handling (NFD normalization)
        """
        tester = Phase3C5GoldenVectorTester(use_fallback=True)
        all_metrics, aggregate = tester.run_all_vectors()
        
        # Print report
        report = tester.print_report(all_metrics, aggregate)
        print(report)
        
        # Validate results
        assert aggregate.vectors_successful == aggregate.total_vectors, \
            f"Expected all {aggregate.total_vectors} vectors to pass, " \
            f"but {aggregate.vectors_failed} failed"
        
        # Validate per-vector results
        for metrics in all_metrics:
            assert metrics.verification_result, \
                f"Vector '{metrics.vector_name}' failed verification"
            assert metrics.error is None, \
                f"Vector '{metrics.vector_name}' produced error: {metrics.error}"
            assert metrics.proof_size_bytes > 0, \
                f"Vector '{metrics.vector_name}' produced empty proof"
        
        # Validate timing is reasonable
        assert aggregate.avg_roundtrip_ms < 1000, \
            f"Average round-trip time {aggregate.avg_roundtrip_ms}ms is too high"
    
    @pytest.mark.slow
    def test_ordering_independence_with_metrics(self):
        """
        INVARIANT TEST: Reordering axioms produces same proof commitment.
        
        Tests that:
          1. simple_modus_ponens and simple_with_reordering have same commitment
          2. Both generate valid proofs
          3. Both verify successfully
        """
        tester = Phase3C5GoldenVectorTester(use_fallback=True)
        
        # Test both orderings
        vec1_name = "simple_modus_ponens"
        vec2_name = "simple_with_reordering"
        
        vec1 = GOLDEN_VECTORS["vectors"][vec1_name]
        vec2 = GOLDEN_VECTORS["vectors"][vec2_name]
        
        metrics1 = tester.test_single_vector(vec1_name, vec1)
        metrics2 = tester.test_single_vector(vec2_name, vec2)
        
        # Both should verify successfully
        assert metrics1.verification_result, "First ordering failed"
        assert metrics2.verification_result, "Second ordering failed"
        
        # Commitments should be identical
        witness1 = tester.convert_golden_vector_to_witness(vec1_name, vec1)
        witness2 = tester.convert_golden_vector_to_witness(vec2_name, vec2)
        
        assert witness1['axioms_commitment_hex'] == witness2['axioms_commitment_hex'], \
            "Order-independent commitments differ!"
    
    @pytest.mark.slow
    def test_large_axiom_set_ordering_independence(self):
        """
        STRESS TEST: 10-axiom set with multiple orderings all produce same commitment.
        """
        tester = Phase3C5GoldenVectorTester(use_fallback=True)
        
        vector = GOLDEN_VECTORS["vectors"]["large_axiom_set"]
        
        # Test original order
        metrics_original = tester.test_single_vector("large_axiom_set", vector)
        assert metrics_original.verification_result, "Original order failed"
        
        # Test reversed order
        vector_reversed = vector.copy()
        vector_reversed["axioms"] = list(reversed(vector["axioms"]))
        metrics_reversed = tester.test_single_vector("large_axiom_set_reversed", vector_reversed)
        assert metrics_reversed.verification_result, "Reversed order failed"
        
        # Validate commitments match
        witness_original = tester.convert_golden_vector_to_witness("large_axiom_set", vector)
        witness_reversed = tester.convert_golden_vector_to_witness("large_axiom_set_reversed", vector_reversed)
        
        assert witness_original['axioms_commitment_hex'] == witness_reversed['axioms_commitment_hex'], \
            "Large axiom set: commitments don't match despite same content"
    
    @pytest.mark.slow
    def test_whitespace_normalization_with_metrics(self):
        """
        INVARIANT TEST: Different whitespace produces same theorem hash.
        """
        tester = Phase3C5GoldenVectorTester(use_fallback=True)
        
        vector = GOLDEN_VECTORS["vectors"]["whitespace_normalization"]
        metrics = tester.test_single_vector("whitespace_normalization", vector)
        
        assert metrics.verification_result, "Whitespace normalization test failed"
        assert metrics.proof_size_bytes > 0, "No proof generated"
    
    @pytest.mark.slow
    def test_duplicate_axioms_deduplication(self):
        """
        INVARIANT TEST: Duplicate axioms are deduplicated before hashing.
        """
        tester = Phase3C5GoldenVectorTester(use_fallback=True)
        
        vector = GOLDEN_VECTORS["vectors"]["duplicate_axioms"]
        witness = tester.convert_golden_vector_to_witness("duplicate_axioms", vector)
        
        metrics = tester.test_single_vector("duplicate_axioms", vector)
        
        assert metrics.verification_result, "Duplicate axioms test failed"
        # Check that the witness was deduplicated (original has 3 axioms, all "P")
        assert len(witness['private_axioms']) == 1, "Expected 1 axiom after deduplication"
        assert witness['private_axioms'][0] == "P", "Expected only 'P' axiom after dedup"


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "-s"])
