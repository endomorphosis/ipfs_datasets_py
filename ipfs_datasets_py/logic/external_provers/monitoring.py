"""
Monitoring and Observability for Neurosymbolic Reasoning

This module provides monitoring, metrics, and observability tools for the
neurosymbolic reasoning system including:

- Performance metrics collection
- Prover usage statistics
- Cache hit/miss tracking
- Error rate monitoring
- Latency percentiles
- Resource usage tracking

Usage:
    >>> from ipfs_datasets_py.logic.external_provers.monitoring import Monitor
    >>> monitor = Monitor()
    >>> 
    >>> with monitor.track_proof("z3"):
    ...     result = prover.prove(formula)
    >>> 
    >>> stats = monitor.get_stats()
    >>> print(f"Average latency: {stats['avg_latency_ms']:.2f}ms")
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from collections import defaultdict
import time
import threading
from contextlib import contextmanager


@dataclass
class ProofMetrics:
    """Metrics for a single proof attempt."""
    prover_name: str
    formula_str: str
    start_time: float
    end_time: float
    success: bool
    cached: bool
    error: Optional[str] = None
    
    @property
    def latency_ms(self) -> float:
        """Latency in milliseconds."""
        return (self.end_time - self.start_time) * 1000


class Monitor:
    """Monitor for neurosymbolic reasoning system.
    
    Collects metrics, tracks performance, and provides observability
    into the reasoning system.
    
    Attributes:
        enabled: Whether monitoring is enabled
        metrics: List of collected metrics
        lock: Thread lock for safe concurrent access
    """
    
    def __init__(self, enabled: bool = True):
        """Initialize monitor.
        
        Args:
            enabled: Whether to enable monitoring
        """
        self.enabled = enabled
        self.metrics: List[ProofMetrics] = []
        self.lock = threading.RLock()
        
        # Counters
        self._proof_count = defaultdict(int)
        self._success_count = defaultdict(int)
        self._cache_hits = defaultdict(int)
        self._cache_misses = defaultdict(int)
        self._error_count = defaultdict(int)
    
    @contextmanager
    def track_proof(
        self,
        prover_name: str,
        formula_str: str = "",
        cached: bool = False
    ):
        """Context manager to track a proof attempt.
        
        Args:
            prover_name: Name of prover
            formula_str: Formula being proved
            cached: Whether result was cached
            
        Usage:
            >>> with monitor.track_proof("z3", "P -> Q"):
            ...     result = prover.prove(formula)
        """
        if not self.enabled:
            yield
            return
        
        start_time = time.time()
        success = False
        error = None
        
        try:
            yield
            success = True
        except Exception as e:
            error = str(e)
            raise
        finally:
            end_time = time.time()
            
            metric = ProofMetrics(
                prover_name=prover_name,
                formula_str=formula_str,
                start_time=start_time,
                end_time=end_time,
                success=success,
                cached=cached,
                error=error
            )
            
            with self.lock:
                self.metrics.append(metric)
                self._proof_count[prover_name] += 1
                
                if success:
                    self._success_count[prover_name] += 1
                else:
                    self._error_count[prover_name] += 1
                
                if cached:
                    self._cache_hits[prover_name] += 1
                else:
                    self._cache_misses[prover_name] += 1
    
    def record_proof(
        self,
        prover_name: str,
        formula_str: str,
        latency_ms: float,
        success: bool,
        cached: bool = False,
        error: Optional[str] = None
    ):
        """Record a proof attempt manually.
        
        Args:
            prover_name: Name of prover
            formula_str: Formula being proved
            latency_ms: Latency in milliseconds
            success: Whether proof succeeded
            cached: Whether result was cached
            error: Error message if failed
        """
        if not self.enabled:
            return
        
        now = time.time()
        metric = ProofMetrics(
            prover_name=prover_name,
            formula_str=formula_str,
            start_time=now - (latency_ms / 1000),
            end_time=now,
            success=success,
            cached=cached,
            error=error
        )
        
        with self.lock:
            self.metrics.append(metric)
            self._proof_count[prover_name] += 1
            
            if success:
                self._success_count[prover_name] += 1
            else:
                self._error_count[prover_name] += 1
            
            if cached:
                self._cache_hits[prover_name] += 1
            else:
                self._cache_misses[prover_name] += 1
    
    def get_stats(self, prover_name: Optional[str] = None) -> Dict:
        """Get statistics.
        
        Args:
            prover_name: Optional prover name to filter by
            
        Returns:
            Dictionary with statistics
        """
        with self.lock:
            if prover_name:
                metrics = [m for m in self.metrics if m.prover_name == prover_name]
            else:
                metrics = self.metrics
            
            if not metrics:
                return {
                    'total_proofs': 0,
                    'success_rate': 0.0,
                    'cache_hit_rate': 0.0,
                    'avg_latency_ms': 0.0,
                    'p50_latency_ms': 0.0,
                    'p95_latency_ms': 0.0,
                    'p99_latency_ms': 0.0,
                }
            
            # Calculate statistics
            total = len(metrics)
            successes = sum(1 for m in metrics if m.success)
            cached = sum(1 for m in metrics if m.cached)
            
            latencies = sorted([m.latency_ms for m in metrics])
            avg_latency = sum(latencies) / len(latencies)
            
            p50_idx = int(len(latencies) * 0.50)
            p95_idx = int(len(latencies) * 0.95)
            p99_idx = int(len(latencies) * 0.99)
            
            return {
                'total_proofs': total,
                'success_count': successes,
                'failure_count': total - successes,
                'success_rate': successes / total if total > 0 else 0.0,
                'cache_hits': cached,
                'cache_misses': total - cached,
                'cache_hit_rate': cached / total if total > 0 else 0.0,
                'avg_latency_ms': avg_latency,
                'min_latency_ms': latencies[0],
                'max_latency_ms': latencies[-1],
                'p50_latency_ms': latencies[p50_idx] if len(latencies) > p50_idx else 0.0,
                'p95_latency_ms': latencies[p95_idx] if len(latencies) > p95_idx else 0.0,
                'p99_latency_ms': latencies[p99_idx] if len(latencies) > p99_idx else 0.0,
            }
    
    def get_prover_stats(self) -> Dict[str, Dict]:
        """Get per-prover statistics.
        
        Returns:
            Dictionary mapping prover names to their statistics
        """
        with self.lock:
            provers = set(m.prover_name for m in self.metrics)
            return {
                prover: self.get_stats(prover)
                for prover in provers
            }
    
    def print_summary(self):
        """Print a summary of collected metrics."""
        with self.lock:
            if not self.metrics:
                print("No metrics collected")
                return
            
            print("=" * 70)
            print("MONITORING SUMMARY")
            print("=" * 70)
            print()
            
            # Overall stats
            overall = self.get_stats()
            print("Overall Statistics:")
            print(f"  Total proofs: {overall['total_proofs']}")
            print(f"  Success rate: {overall['success_rate']:.1%}")
            print(f"  Cache hit rate: {overall['cache_hit_rate']:.1%}")
            print(f"  Avg latency: {overall['avg_latency_ms']:.2f}ms")
            print(f"  P50 latency: {overall['p50_latency_ms']:.2f}ms")
            print(f"  P95 latency: {overall['p95_latency_ms']:.2f}ms")
            print(f"  P99 latency: {overall['p99_latency_ms']:.2f}ms")
            print()
            
            # Per-prover stats
            prover_stats = self.get_prover_stats()
            if prover_stats:
                print("Per-Prover Statistics:")
                for prover, stats in prover_stats.items():
                    print(f"\n  {prover}:")
                    print(f"    Proofs: {stats['total_proofs']}")
                    print(f"    Success: {stats['success_rate']:.1%}")
                    print(f"    Cache hits: {stats['cache_hit_rate']:.1%}")
                    print(f"    Avg latency: {stats['avg_latency_ms']:.2f}ms")
            
            print()
            print("=" * 70)
    
    def reset(self):
        """Reset all metrics."""
        with self.lock:
            self.metrics.clear()
            self._proof_count.clear()
            self._success_count.clear()
            self._cache_hits.clear()
            self._cache_misses.clear()
            self._error_count.clear()


# Global monitor instance
_global_monitor: Optional[Monitor] = None


def get_global_monitor(enabled: bool = True) -> Monitor:
    """Get or create global monitor instance.
    
    Args:
        enabled: Whether to enable monitoring
        
    Returns:
        Global Monitor instance
    """
    global _global_monitor
    
    if _global_monitor is None:
        _global_monitor = Monitor(enabled=enabled)
    
    return _global_monitor


__all__ = [
    'Monitor',
    'ProofMetrics',
    'get_global_monitor',
]
