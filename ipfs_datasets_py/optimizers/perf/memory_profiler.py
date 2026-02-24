"""
Memory optimization profiler module.

Provides comprehensive memory usage tracking, hotspot detection,
garbage collection analysis, and baseline comparison capabilities.

Classes:
    MemorySnapshot: Captures memory state at a specific time
    MemoryHotspot: Represents a major memory consumer
    GCAnalyzer: Analyzes garbage collection statistics
    MemoryProfiler: Main profiling engine
    MemoryComparison: Baseline vs optimized comparison
    MemoryDelta: Memory change metrics
"""

import gc
import os
import sys
import time
import threading
import tracemalloc
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict
from enum import Enum


class MemoryUnit(Enum):
    """Memory unit constants."""
    BYTES = 1
    KB = 1024
    MB = 1024 * 1024
    GB = 1024 * 1024 * 1024


@dataclass
class MemorySnapshot:
    """Snapshot of memory state at specific point in time."""
    
    timestamp: float
    pid: int
    current_memory_mb: float
    peak_memory_mb: float
    total_allocated_mb: float
    object_counts: Dict[str, int] = field(default_factory=dict)
    largest_objects: List[Tuple[int, str]] = field(default_factory=list)  # (size_bytes, type_name)
    tracemalloc_snapshots: Optional[List[Tuple[str, int, int]]] = None  # (filename, size, count)
    gc_stats: Dict[str, Any] = field(default_factory=dict)
    
    def memory_delta(self, other: 'MemorySnapshot') -> float:
        """Calculate memory delta in MB from another snapshot."""
        return self.current_memory_mb - other.current_memory_mb
    
    def get_top_types(self, n: int = 10) -> List[Tuple[str, int]]:
        """Get top N object types by count."""
        return sorted(self.object_counts.items(), key=lambda x: x[1], reverse=True)[:n]
    
    def get_top_objects(self, n: int = 10) -> List[Tuple[int, str]]:
        """Get top N objects by size."""
        return sorted(self.largest_objects, key=lambda x: x[0], reverse=True)[:n]


@dataclass
class MemoryHotspot:
    """Represents significant memory consumer."""
    
    object_type: str
    count: int
    total_memory_bytes: int
    avg_size_bytes: float
    percentage_of_total: float
    
    @property
    def total_memory_mb(self) -> float:
        return self.total_memory_bytes / MemoryUnit.MB.value
    
    @property
    def avg_size_kb(self) -> float:
        return self.avg_size_bytes / MemoryUnit.KB.value


@dataclass
class MemoryDelta:
    """Memory change metrics between snapshots."""
    
    memory_delta_mb: float
    object_count_delta: int
    memory_change_percent: float
    hotspot_changes: Dict[str, Tuple[int, int]] = field(default_factory=dict)  # type -> (old_count, new_count)
    new_hotspots: List[str] = field(default_factory=list)
    resolved_hotspots: List[str] = field(default_factory=list)


@dataclass
class MemoryComparison:
    """Result of comparing baseline vs optimized memory usage."""
    
    baseline_snapshot: MemorySnapshot
    optimized_snapshot: MemorySnapshot
    memory_saved_mb: float
    memory_saved_percent: float
    improvement_ratio: float  # baseline / optimized
    hotspot_reduction: Dict[str, Tuple[int, int]] = field(default_factory=dict)  # type -> (before, after)
    recommendation: str = ""


class GCAnalyzer:
    """Analyzes garbage collection statistics."""
    
    def __init__(self):
        self.baseline_stats = None
        self.current_stats = None
        self._lock = threading.RLock()
    
    def set_baseline(self):
        """Set baseline GC statistics."""
        with self._lock:
            self.baseline_stats = self._get_gc_stats()
    
    def get_current_stats(self) -> Dict[str, Any]:
        """Get current garbage collection statistics."""
        with self._lock:
            return self._get_gc_stats()
    
    def get_stats_delta(self) -> Dict[str, Any]:
        """Get difference between current and baseline GC stats."""
        with self._lock:
            if self.baseline_stats is None:
                return {}
            
            current = self._get_gc_stats()
            delta = {}
            
            for gen in range(gc.get_count().__len__()):
                baseline_count = self.baseline_stats.get(f'gen_{gen}_collections', 0)
                current_count = current.get(f'gen_{gen}_collections', 0)
                delta[f'gen_{gen}_delta'] = current_count - baseline_count
            
            return delta
    
    @staticmethod
    def _get_gc_stats() -> Dict[str, Any]:
        """Collect garbage collection statistics."""
        stats = {
            'enabled': gc.isenabled(),
            'debug_flags': gc.get_debug(),
            'collection_counts': tuple(gc.get_count()),
            'threshold': gc.get_threshold(),
            'unreachable': len(gc.garbage),
        }
        
        # Per-generation stats
        for gen in range(len(gc.get_count())):
            stats[f'gen_{gen}_collections'] = gc.get_count()[gen]
        
        return stats
    
    @staticmethod
    def force_collect() -> int:
        """Force garbage collection, return collected objects count."""
        return gc.collect()


class MemoryProfiler:
    """Main memory profiling engine."""
    
    def __init__(self, enable_tracemalloc: bool = True):
        self.enable_tracemalloc = enable_tracemalloc
        self.snapshot_history: List[MemorySnapshot] = []
        self.baseline_snapshot: Optional[MemorySnapshot] = None
        self.gc_analyzer = GCAnalyzer()
        self._lock = threading.RLock()
        self._start_time = None
        
        if enable_tracemalloc and not tracemalloc.is_tracing():
            tracemalloc.start()
    
    def start_profiling(self):
        """Start profiling session with baseline snapshot."""
        with self._lock:
            self._start_time = time.time()
            gc.collect()
            self.gc_analyzer.set_baseline()
            self.baseline_snapshot = self._capture_snapshot()
            self.snapshot_history.clear()
            self.snapshot_history.append(self.baseline_snapshot)
    
    def snapshot(self, label: str = "") -> MemorySnapshot:
        """Capture current memory state."""
        with self._lock:
            snap = self._capture_snapshot()
            self.snapshot_history.append(snap)
            return snap
    
    def get_memory_delta(self) -> float:
        """Get memory delta in MB from baseline."""
        with self._lock:
            if self.baseline_snapshot is None:
                return 0.0
            
            current = self._capture_snapshot()
            return current.memory_delta(self.baseline_snapshot)
    
    def get_hotspots(self, top_n: int = 10) -> List[MemoryHotspot]:
        """Get top N memory hotspots by object type."""
        with self._lock:
            snapshot = self._capture_snapshot()
            hotspots = []
            
            total_memory = sum(size for size, _ in snapshot.largest_objects)
            type_aggregates: Dict[str, Tuple[int, int]] = defaultdict(lambda: (0, 0))  # (total_bytes, count)
            
            for size, obj_type in snapshot.largest_objects:
                total_bytes, count = type_aggregates[obj_type]
                type_aggregates[obj_type] = (total_bytes + size, count + 1)
            
            for obj_type, (total_bytes, count) in type_aggregates.items():
                if total_bytes == 0:
                    continue
                
                hotspot = MemoryHotspot(
                    object_type=obj_type,
                    count=count,
                    total_memory_bytes=total_bytes,
                    avg_size_bytes=total_bytes / count if count > 0 else 0,
                    percentage_of_total=(total_bytes / total_memory * 100) if total_memory > 0 else 0
                )
                hotspots.append(hotspot)
            
            return sorted(hotspots, key=lambda h: h.total_memory_bytes, reverse=True)[:top_n]
    
    def compare_snapshots(self, snap1: MemorySnapshot, snap2: MemorySnapshot) -> MemoryDelta:
        """Compare two memory snapshots and return delta."""
        with self._lock:
            memory_delta = snap2.memory_delta(snap1)
            
            type_counts_1 = snap1.get_top_types(100)
            type_counts_2 = snap2.get_top_types(100)
            
            dict_1 = dict(type_counts_1)
            dict_2 = dict(type_counts_2)
            
            object_count_delta = sum(dict_2.values()) - sum(dict_1.values())
            memory_change_percent = (memory_delta / snap1.current_memory_mb * 100) if snap1.current_memory_mb > 0 else 0
            
            hotspot_changes = {}
            for obj_type in set(dict_1.keys()) | set(dict_2.keys()):
                before = dict_1.get(obj_type, 0)
                after = dict_2.get(obj_type, 0)
                if before != after:
                    hotspot_changes[obj_type] = (before, after)
            
            new_hotspots = [t for t, (before, after) in hotspot_changes.items() if before == 0 and after > 0]
            resolved_hotspots = [t for t, (before, after) in hotspot_changes.items() if before > 0 and after == 0]
            
            return MemoryDelta(
                memory_delta_mb=memory_delta,
                object_count_delta=object_count_delta,
                memory_change_percent=memory_change_percent,
                hotspot_changes=hotspot_changes,
                new_hotspots=new_hotspots,
                resolved_hotspots=resolved_hotspots
            )
    
    def get_comparison(self, optimized_snapshot: MemorySnapshot) -> MemoryComparison:
        """Compare baseline snapshot with optimized snapshot."""
        with self._lock:
            if self.baseline_snapshot is None:
                raise ValueError("No baseline snapshot. Call start_profiling() first.")
            
            memory_saved = self.baseline_snapshot.current_memory_mb - optimized_snapshot.current_memory_mb
            saved_percent = (memory_saved / self.baseline_snapshot.current_memory_mb * 100) if self.baseline_snapshot.current_memory_mb > 0 else 0
            improvement_ratio = self.baseline_snapshot.current_memory_mb / optimized_snapshot.current_memory_mb if optimized_snapshot.current_memory_mb > 0 else 1.0
            
            # Hotspot reduction analysis
            hotspot_reduction = {}
            baseline_types = dict(self.baseline_snapshot.get_top_types(50))
            optimized_types = dict(optimized_snapshot.get_top_types(50))
            
            for obj_type in baseline_types:
                before = baseline_types.get(obj_type, 0)
                after = optimized_types.get(obj_type, 0)
                if before > after:
                    hotspot_reduction[obj_type] = (before, after)
            
            # Generate recommendation
            if saved_percent > 50:
                recommendation = f"Excellent optimization! Saved {saved_percent:.1f}%"
            elif saved_percent > 20:
                recommendation = f"Good optimization! Saved {saved_percent:.1f}%"
            elif saved_percent > 5:
                recommendation = f"Modest optimization. Saved {saved_percent:.1f}%"
            elif memory_saved > 0:
                recommendation = f"Marginal improvement. Saved {memory_saved:.2f}MB"
            else:
                recommendation = f"Optimization needed. Memory increased by {abs(memory_saved):.2f}MB"
            
            return MemoryComparison(
                baseline_snapshot=self.baseline_snapshot,
                optimized_snapshot=optimized_snapshot,
                memory_saved_mb=memory_saved,
                memory_saved_percent=saved_percent,
                improvement_ratio=improvement_ratio,
                hotspot_reduction=hotspot_reduction,
                recommendation=recommendation
            )
    
    def get_snapshothistory(self) -> List[MemorySnapshot]:
        """Get all captured snapshots."""
        with self._lock:
            return self.snapshot_history.copy()
    
    def clear_history(self):
        """Clear snapshot history but keep baseline."""
        with self._lock:
            if self.baseline_snapshot:
                self.snapshot_history = [self.baseline_snapshot]
            else:
                self.snapshot_history = []
    
    def _capture_snapshot(self) -> MemorySnapshot:
        """Capture current memory snapshot."""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            mem_info = process.memory_info()
            current_memory_mb = mem_info.rss / MemoryUnit.MB.value
            peak_memory_mb = mem_info.rss / MemoryUnit.MB.value  # Peak is equivalent to current in psutil
            total_allocated_mb = mem_info.rss / MemoryUnit.MB.value
        except (ImportError, AttributeError, OSError, RuntimeError):
            # Fallback if psutil not available
            current_memory_mb = 0.0
            peak_memory_mb = 0.0
            total_allocated_mb = 0.0
        
        # Get object type counts
        object_counts = self._get_object_counts()
        largest_objects = self._get_largest_objects()
        
        # Get tracemalloc snapshots if enabled
        tracemalloc_snapshots = None
        if self.enable_tracemalloc and tracemalloc.is_tracing():
            snapshot = tracemalloc.take_snapshot()
            top_stats = snapshot.statistics('lineno')
            tracemalloc_snapshots = [(str(stat.traceback), stat.size, stat.count) for stat in top_stats[:20]]
        
        # Get GC stats
        gc_stats = self.gc_analyzer.get_current_stats()
        
        return MemorySnapshot(
            timestamp=time.time(),
            pid=os.getpid(),
            current_memory_mb=current_memory_mb,
            peak_memory_mb=peak_memory_mb,
            total_allocated_mb=total_allocated_mb,
            object_counts=object_counts,
            largest_objects=largest_objects,
            tracemalloc_snapshots=tracemalloc_snapshots,
            gc_stats=gc_stats
        )
    
    @staticmethod
    def _get_object_counts() -> Dict[str, int]:
        """Get counts of objects by type."""
        counts = defaultdict(int)
        for obj in gc.get_objects():
            counts[type(obj).__name__] += 1
        return dict(counts)
    
    @staticmethod
    def _get_largest_objects(limit: int = 500) -> List[Tuple[int, str]]:
        """Get largest objects by size."""
        objects = []
        for obj in gc.get_objects():
            try:
                size = sys.getsizeof(obj)
                obj_type = type(obj).__name__
                objects.append((size, obj_type))
            except (TypeError, ValueError, AttributeError, OSError, RuntimeError):
                pass
        
        return sorted(objects, key=lambda x: x[0], reverse=True)[:limit]


class MemoryOptimizer:
    """Provides optimization recommendations based on memory profiles."""
    
    @staticmethod
    def analyze_hotspots(hotspots: List[MemoryHotspot], threshold_percent: float = 5.0) -> Dict[str, str]:
        """Analyze hotspots and provide recommendations."""
        recommendations = {}
        
        for hotspot in hotspots:
            if hotspot.percentage_of_total < threshold_percent:
                break
            
            obj_type = hotspot.object_type
            
            if obj_type == 'dict':
                recommendations[obj_type] = "Consider using __slots__ or alternative data structures"
            elif obj_type == 'list':
                recommendations[obj_type] = "Pre-allocate lists if size is known, or use generators"
            elif obj_type == 'str':
                recommendations[obj_type] = "Consider interning strings or using arrays for bulk data"
            elif obj_type in ('tuple', 'frozenset'):
                recommendations[obj_type] = "These are immutable; check for duplicates via interning"
            elif obj_type == 'DataFrame':
                recommendations[obj_type] = "Use categorical data types, sparse formats, or chunking"
            elif obj_type == 'ndarray':
                recommendations[obj_type] = "Use appropriate dtypes and consider memory-mapped arrays"
            else:
                recommendations[obj_type] = f"Profile {obj_type} instances for optimization opportunities"
        
        return recommendations
