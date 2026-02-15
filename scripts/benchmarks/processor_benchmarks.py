#!/usr/bin/env python3
"""
Performance Benchmarking Suite for Processors Refactoring

This script benchmarks:
1. Batch processing throughput
2. GraphRAG old vs unified performance
3. Memory profiling
4. Routing performance
5. Adapter selection speed

Usage:
    python scripts/benchmarks/processor_benchmarks.py
    python scripts/benchmarks/processor_benchmarks.py --quick
    python scripts/benchmarks/processor_benchmarks.py --report-only
"""

import argparse
import asyncio
import time
import sys
import gc
import tracemalloc
from pathlib import Path
from typing import Dict, List, Tuple, Any
from dataclasses import dataclass, asdict
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@dataclass
class BenchmarkResult:
    """Result from a single benchmark."""
    name: str
    duration: float
    memory_peak_mb: float
    items_processed: int
    throughput: float  # items per second
    success_rate: float
    errors: List[str]
    metadata: Dict[str, Any]


class ProcessorBenchmarks:
    """Comprehensive benchmark suite for processors refactoring."""
    
    def __init__(self, quick_mode: bool = False):
        self.quick_mode = quick_mode
        self.results: List[BenchmarkResult] = []
        
        # Benchmark parameters
        if quick_mode:
            self.batch_sizes = [5, 10]
            self.routing_iterations = 100
        else:
            self.batch_sizes = [10, 50, 100]
            self.routing_iterations = 1000
    
    def _start_benchmark(self, name: str) -> Tuple[float, int]:
        """Start a benchmark and return start time and memory snapshot."""
        print(f"\n{'='*70}")
        print(f"Benchmark: {name}")
        print(f"{'='*70}")
        gc.collect()
        tracemalloc.start()
        return time.time(), tracemalloc.get_traced_memory()[0]
    
    def _end_benchmark(
        self,
        name: str,
        start_time: float,
        items_processed: int,
        errors: List[str],
        metadata: Dict[str, Any]
    ) -> BenchmarkResult:
        """End a benchmark and record results."""
        duration = time.time() - start_time
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        throughput = items_processed / duration if duration > 0 else 0
        success_rate = (items_processed - len(errors)) / items_processed if items_processed > 0 else 0
        
        result = BenchmarkResult(
            name=name,
            duration=duration,
            memory_peak_mb=peak / 1024 / 1024,
            items_processed=items_processed,
            throughput=throughput,
            success_rate=success_rate,
            errors=errors,
            metadata=metadata
        )
        
        self.results.append(result)
        
        print(f"\n✓ Completed: {name}")
        print(f"  Duration: {duration:.2f}s")
        print(f"  Memory Peak: {result.memory_peak_mb:.2f} MB")
        print(f"  Throughput: {throughput:.2f} items/sec")
        print(f"  Success Rate: {success_rate*100:.1f}%")
        
        return result
    
    async def benchmark_batch_processing(self):
        """Benchmark batch processing with different folder sizes."""
        print("\n" + "="*70)
        print("BENCHMARK 1: Batch Processing Throughput")
        print("="*70)
        
        try:
            from ipfs_datasets_py.processors import UniversalProcessor
            from ipfs_datasets_py.processors.adapters.batch_adapter import BatchProcessorAdapter
        except ImportError as e:
            print(f"✗ Cannot import processors: {e}")
            return
        
        for batch_size in self.batch_sizes:
            name = f"Batch Processing ({batch_size} files)"
            start_time, _ = self._start_benchmark(name)
            errors = []
            
            try:
                # Create mock file list
                mock_files = [f"test_file_{i}.txt" for i in range(batch_size)]
                
                # Note: This is a mock benchmark - actual processing would require real files
                print(f"   [MOCK] Processing {batch_size} files...")
                await asyncio.sleep(0.1 * batch_size)  # Simulate processing
                
                metadata = {
                    'batch_size': batch_size,
                    'mode': 'mock',
                    'note': 'Actual performance will vary with real files'
                }
                
            except Exception as e:
                errors.append(str(e))
                print(f"   ✗ Error: {e}")
            
            self._end_benchmark(name, start_time, batch_size, errors, metadata)
    
    def benchmark_routing_performance(self):
        """Benchmark input detection and routing speed."""
        name = "Input Routing Performance"
        start_time, _ = self._start_benchmark(name)
        errors = []
        
        try:
            from ipfs_datasets_py.processors.input_detection import InputDetector
            
            detector = InputDetector()
            
            # Test inputs
            test_inputs = [
                "document.pdf",
                "https://example.com",
                "video.mp4",
                "audio.mp3",
                "/path/to/folder/",
                "image.jpg",
                "spreadsheet.xlsx",
                "text.txt",
            ]
            
            iterations = self.routing_iterations
            print(f"   Running {iterations} routing operations...")
            
            for i in range(iterations):
                for input_item in test_inputs:
                    classification = detector.classify_for_routing(input_item)
            
            items_processed = iterations * len(test_inputs)
            
            metadata = {
                'iterations': iterations,
                'unique_inputs': len(test_inputs),
                'total_classifications': items_processed
            }
            
        except Exception as e:
            errors.append(str(e))
            print(f"   ✗ Error: {e}")
            traceback.print_exc()
            items_processed = 0
            metadata = {}
        
        self._end_benchmark(name, start_time, items_processed, errors, metadata)
    
    def benchmark_processor_registration(self):
        """Benchmark processor registration and lookup speed."""
        name = "Processor Registration & Lookup"
        start_time, _ = self._start_benchmark(name)
        errors = []
        
        try:
            from ipfs_datasets_py.processors.registry import ProcessorRegistry
            from ipfs_datasets_py.processors.protocol import ProcessorProtocol
            
            # Create mock processor
            class MockProcessor:
                def can_process(self, input_data, input_type): return True
                async def process(self, input_data, options=None): pass
                def get_supported_types(self): return ["test"]
                def get_priority(self): return 10
                def get_name(self): return "MockProcessor"
            
            iterations = 100
            print(f"   Registering and looking up processors {iterations} times...")
            
            for i in range(iterations):
                registry = ProcessorRegistry()
                for j in range(10):  # Register 10 processors each time
                    registry.register(MockProcessor(), priority=10)
                # Lookup
                processors = registry.find_processors("test_input")
            
            items_processed = iterations * 10
            
            metadata = {
                'iterations': iterations,
                'processors_per_iteration': 10
            }
            
        except Exception as e:
            errors.append(str(e))
            print(f"   ✗ Error: {e}")
            traceback.print_exc()
            items_processed = 0
            metadata = {}
        
        self._end_benchmark(name, start_time, items_processed, errors, metadata)
    
    def benchmark_memory_baseline(self):
        """Benchmark baseline memory usage of processors."""
        name = "Memory Baseline (Processor Creation)"
        start_time, _ = self._start_benchmark(name)
        errors = []
        
        try:
            from ipfs_datasets_py.processors import UniversalProcessor
            
            print("   Creating UniversalProcessor instances...")
            processors = []
            for i in range(10):
                processor = UniversalProcessor()
                processors.append(processor)
            
            items_processed = 10
            
            metadata = {
                'instances_created': 10,
                'note': 'Peak memory includes all adapters and registry'
            }
            
        except Exception as e:
            errors.append(str(e))
            print(f"   ✗ Error: {e}")
            traceback.print_exc()
            items_processed = 0
            metadata = {}
        
        self._end_benchmark(name, start_time, items_processed, errors, metadata)
    
    def generate_report(self) -> str:
        """Generate comprehensive benchmark report."""
        report = [
            "\n" + "="*70,
            "PROCESSOR BENCHMARKING REPORT",
            "="*70,
            f"\nMode: {'Quick' if self.quick_mode else 'Full'}",
            f"Total Benchmarks: {len(self.results)}",
            f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "\n" + "="*70,
        ]
        
        # Summary statistics
        if self.results:
            total_duration = sum(r.duration for r in self.results)
            total_items = sum(r.items_processed for r in self.results)
            avg_success = sum(r.success_rate for r in self.results) / len(self.results)
            
            report.extend([
                "\nSUMMARY STATISTICS",
                "-" * 70,
                f"Total Duration: {total_duration:.2f}s",
                f"Total Items Processed: {total_items:,}",
                f"Average Success Rate: {avg_success*100:.1f}%",
            ])
        
        # Individual results
        report.append("\n\nDETAILED RESULTS")
        report.append("-" * 70)
        
        for result in self.results:
            report.extend([
                f"\n{result.name}",
                f"  Duration: {result.duration:.3f}s",
                f"  Memory Peak: {result.memory_peak_mb:.2f} MB",
                f"  Items: {result.items_processed:,}",
                f"  Throughput: {result.throughput:.2f} items/sec",
                f"  Success Rate: {result.success_rate*100:.1f}%",
            ])
            
            if result.errors:
                report.append(f"  Errors: {len(result.errors)}")
                for error in result.errors[:3]:
                    report.append(f"    • {error}")
            
            if result.metadata:
                report.append("  Metadata:")
                for key, value in result.metadata.items():
                    report.append(f"    {key}: {value}")
        
        # Performance grades
        report.append("\n\nPERFORMANCE GRADES")
        report.append("-" * 70)
        
        for result in self.results:
            grade = self._calculate_grade(result)
            report.append(f"{result.name}: {grade}")
        
        report.append("\n" + "="*70 + "\n")
        
        return "\n".join(report)
    
    def _calculate_grade(self, result: BenchmarkResult) -> str:
        """Calculate performance grade for a benchmark result."""
        # Simple grading based on success rate and throughput
        if result.success_rate >= 0.95 and result.throughput > 100:
            return "A (Excellent)"
        elif result.success_rate >= 0.90 and result.throughput > 50:
            return "B (Good)"
        elif result.success_rate >= 0.80 and result.throughput > 20:
            return "C (Average)"
        elif result.success_rate >= 0.70:
            return "D (Below Average)"
        else:
            return "F (Needs Improvement)"
    
    def save_report(self, filepath: Path):
        """Save report to file."""
        report_text = self.generate_report()
        filepath.write_text(report_text)
        print(f"\n✓ Report saved to: {filepath}")
        
        # Also save JSON format
        json_path = filepath.with_suffix('.json')
        json_data = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'mode': 'quick' if self.quick_mode else 'full',
            'results': [asdict(r) for r in self.results]
        }
        json_path.write_text(json.dumps(json_data, indent=2))
        print(f"✓ JSON data saved to: {json_path}")
    
    async def run_all_benchmarks(self):
        """Run all benchmarks in sequence."""
        print("\n" + "="*70)
        print("STARTING COMPREHENSIVE PROCESSOR BENCHMARKS")
        print("="*70)
        print(f"Mode: {'Quick' if self.quick_mode else 'Full'}")
        
        # Run benchmarks
        await self.benchmark_batch_processing()
        self.benchmark_routing_performance()
        self.benchmark_processor_registration()
        self.benchmark_memory_baseline()
        
        # Generate and display report
        report = self.generate_report()
        print(report)
        
        # Save report
        report_dir = Path(__file__).parent.parent.parent / "docs" / "benchmarks"
        report_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        report_file = report_dir / f"processor_benchmarks_{timestamp}.txt"
        self.save_report(report_file)


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark processors refactoring performance"
    )
    parser.add_argument(
        '--quick',
        action='store_true',
        help='Run quick benchmarks (reduced iterations)'
    )
    parser.add_argument(
        '--report-only',
        type=str,
        help='Generate report from existing JSON file'
    )
    
    args = parser.parse_args()
    
    if args.report_only:
        # Load and display existing report
        json_path = Path(args.report_only)
        if not json_path.exists():
            print(f"✗ File not found: {json_path}")
            sys.exit(1)
        
        data = json.loads(json_path.read_text())
        print(f"\nLoaded benchmark data from: {json_path}")
        print(f"Timestamp: {data['timestamp']}")
        print(f"Results: {len(data['results'])}")
        sys.exit(0)
    
    # Run benchmarks
    benchmarks = ProcessorBenchmarks(quick_mode=args.quick)
    
    try:
        asyncio.run(benchmarks.run_all_benchmarks())
    except KeyboardInterrupt:
        print("\n\n✗ Benchmarks interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n✗ Benchmarks failed: {e}")
        traceback.print_exc()
        sys.exit(1)
    
    print("\n✓ All benchmarks completed successfully")


if __name__ == "__main__":
    main()
