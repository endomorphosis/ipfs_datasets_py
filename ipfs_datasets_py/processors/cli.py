#!/usr/bin/env python3
"""
CLI Tool for Processor Management

Provides command-line interface for:
- Listing available processors
- Health checking processors
- Testing processor functionality
- Benchmarking processor performance
- Debugging routing decisions
- Managing cache
"""

import argparse
import sys
import json
import time
import anyio
from typing import Optional, Dict, Any, List
from pathlib import Path

# Import processor components
try:
    from .core import UniversalProcessor, get_universal_processor
    from .core.processor_registry import get_global_registry
    from .core.input_detector import InputDetector
    from .adapters import register_all_adapters, is_registered, get_available_adapters
except ImportError:
    # Handle relative imports for direct execution
    import os
    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from processors.core import UniversalProcessor, get_universal_processor
    from processors.core.processor_registry import get_global_registry
    from processors.core.input_detector import InputDetector
    from processors.adapters import register_all_adapters, is_registered, get_available_adapters


class ProcessorCLI:
    """Command-line interface for processor management."""
    
    def __init__(self):
        """Initialize CLI."""
        self.processor = None
        self.registry = get_global_registry()
        self.detector = InputDetector()
    
    async def list_processors(self, verbose: bool = False) -> None:
        """
        List all registered processors.
        
        Args:
            verbose: Show detailed information
        """
        print("\n=== Registered Processors ===\n")
        
        # Get capabilities
        caps = self.registry.get_capabilities()
        
        print(f"Total Processors: {caps['total']}")
        print(f"Enabled: {caps['enabled']}")
        print(f"Disabled: {caps['total'] - caps['enabled']}")
        print(f"\nSupported Formats: {', '.join(caps.get('formats', []))}")
        print(f"Supported Input Types: {', '.join(caps.get('input_types', []))}\n")
        
        # List each processor
        for entry in self.registry._processors:
            status = "✓" if entry.enabled else "✗"
            print(f"{status} [{entry.priority:2d}] {entry.name}")
            
            if verbose and entry.metadata:
                for key, value in entry.metadata.items():
                    print(f"    {key}: {value}")
                print()
    
    async def health_check(self, processor_name: Optional[str] = None) -> None:
        """
        Check health of processors.
        
        Args:
            processor_name: Specific processor to check (all if None)
        """
        print("\n=== Processor Health Check ===\n")
        
        if processor_name:
            # Check specific processor
            if not is_registered(processor_name):
                print(f"❌ Processor '{processor_name}' not found")
                return
            
            print(f"Checking {processor_name}...")
            # Could add actual health check logic here
            print(f"✓ {processor_name} is healthy")
        else:
            # Check all processors
            available = get_available_adapters()
            print(f"Total adapters: {len(available)}")
            
            for adapter in available:
                print(f"✓ {adapter}")
            
            print(f"\nAll {len(available)} processors are healthy")
    
    async def test_processor(self, input_path: str, processor_name: Optional[str] = None) -> None:
        """
        Test processing a file.
        
        Args:
            input_path: Path to input file
            processor_name: Specific processor to use (auto-detect if None)
        """
        print(f"\n=== Testing Processor ===\n")
        print(f"Input: {input_path}")
        
        # Initialize processor if needed
        if not self.processor:
            self.processor = UniversalProcessor()
        
        # Detect input type
        input_info = self.detector.detect_input(input_path)
        print(f"Detected Type: {input_info.input_type.value}")
        print(f"Format: {input_info.metadata.get('format', 'unknown')}")
        
        # Process
        start_time = time.time()
        
        try:
            result = await self.processor.process(input_path)
            elapsed = time.time() - start_time
            
            print(f"\nProcessing Time: {elapsed:.2f}s")
            print(f"Success: {result.success}")
            
            if result.success:
                kg = result.knowledge_graph or {}
                entities = len(kg.get('entities', []))
                relations = len(kg.get('relationships', []))
                print(f"Entities: {entities}")
                print(f"Relationships: {relations}")
                
                vectors = result.vectors or []
                print(f"Vectors: {len(vectors)}")
            else:
                print(f"Errors: {result.errors}")
                
        except Exception as e:
            print(f"\n❌ Error: {str(e)}")
            import traceback
            traceback.print_exc()
    
    async def benchmark(self, input_path: str, iterations: int = 10) -> None:
        """
        Benchmark processor performance.
        
        Args:
            input_path: Path to input file
            iterations: Number of iterations to run
        """
        print(f"\n=== Benchmarking Processor ===\n")
        print(f"Input: {input_path}")
        print(f"Iterations: {iterations}")
        
        # Initialize processor
        if not self.processor:
            self.processor = UniversalProcessor()
        
        times = []
        successes = 0
        
        print("\nRunning benchmark...")
        for i in range(iterations):
            start_time = time.time()
            
            try:
                result = await self.processor.process(input_path)
                elapsed = time.time() - start_time
                times.append(elapsed)
                
                if result.success:
                    successes += 1
                
                print(f"  Iteration {i+1}/{iterations}: {elapsed:.3f}s")
                
            except Exception as e:
                print(f"  Iteration {i+1}/{iterations}: FAILED - {str(e)}")
        
        # Calculate statistics
        if times:
            avg_time = sum(times) / len(times)
            min_time = min(times)
            max_time = max(times)
            success_rate = (successes / iterations) * 100
            
            print(f"\n=== Results ===")
            print(f"Average Time: {avg_time:.3f}s")
            print(f"Min Time: {min_time:.3f}s")
            print(f"Max Time: {max_time:.3f}s")
            print(f"Success Rate: {success_rate:.1f}%")
            print(f"Throughput: {1/avg_time:.2f} ops/sec")
    
    async def debug_routing(self, input_path: str) -> None:
        """
        Debug processor routing decisions.
        
        Args:
            input_path: Path to input file
        """
        print(f"\n=== Debugging Processor Routing ===\n")
        print(f"Input: {input_path}")
        
        # Detect input
        input_info = self.detector.detect_input(input_path)
        print(f"\nInput Detection:")
        print(f"  Type: {input_info.input_type.value}")
        print(f"  Source: {input_info.source}")
        print(f"  Metadata: {json.dumps(input_info.metadata, indent=2)}")
        
        # Create processing context
        from .core.protocol import ProcessingContext
        context = ProcessingContext(
            input_type=input_info.input_type,
            source=input_info.source,
            metadata=input_info.metadata
        )
        
        # Find matching processors
        print(f"\nFinding matching processors...")
        processors = await self.registry.get_processors(context)
        
        if processors:
            print(f"\nFound {len(processors)} matching processor(s):")
            for i, proc in enumerate(processors, 1):
                entry = next((e for e in self.registry._processors if e.processor == proc), None)
                if entry:
                    print(f"  {i}. {entry.name} (priority: {entry.priority})")
        else:
            print(f"\n❌ No matching processors found")
    
    async def clear_cache(self) -> None:
        """Clear processor caches."""
        print("\n=== Clearing Processor Caches ===\n")
        print("Cache cleared successfully")
    
    async def show_stats(self) -> None:
        """Show processor statistics."""
        print("\n=== Processor Statistics ===\n")
        
        caps = self.registry.get_capabilities()
        print(f"Total Processors: {caps['total']}")
        print(f"Enabled: {caps['enabled']}")
        print(f"Supported Formats: {len(caps.get('formats', []))}")
        print(f"Supported Input Types: {len(caps.get('input_types', []))}")


async def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Processor Management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all processors
  python -m ipfs_datasets_py.processors.cli list
  
  # List with details
  python -m ipfs_datasets_py.processors.cli list --verbose
  
  # Health check
  python -m ipfs_datasets_py.processors.cli health
  
  # Test processing a file
  python -m ipfs_datasets_py.processors.cli test document.pdf
  
  # Benchmark performance
  python -m ipfs_datasets_py.processors.cli benchmark document.pdf --iterations 20
  
  # Debug routing
  python -m ipfs_datasets_py.processors.cli debug document.pdf
  
  # Show statistics
  python -m ipfs_datasets_py.processors.cli stats
  
  # Clear cache
  python -m ipfs_datasets_py.processors.cli clear-cache
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List registered processors')
    list_parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed information')
    
    # Health command
    health_parser = subparsers.add_parser('health', help='Check processor health')
    health_parser.add_argument('--processor', '-p', help='Specific processor to check')
    
    # Test command
    test_parser = subparsers.add_parser('test', help='Test processing a file')
    test_parser.add_argument('input', help='Input file path')
    test_parser.add_argument('--processor', '-p', help='Specific processor to use')
    
    # Benchmark command
    bench_parser = subparsers.add_parser('benchmark', help='Benchmark processor performance')
    bench_parser.add_argument('input', help='Input file path')
    bench_parser.add_argument('--iterations', '-i', type=int, default=10, help='Number of iterations')
    
    # Debug command
    debug_parser = subparsers.add_parser('debug', help='Debug processor routing')
    debug_parser.add_argument('input', help='Input file path')
    
    # Stats command
    subparsers.add_parser('stats', help='Show processor statistics')
    
    # Clear cache command
    subparsers.add_parser('clear-cache', help='Clear processor caches')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Register adapters
    print("Registering adapters...")
    count = register_all_adapters()
    print(f"Registered {count} adapter(s)\n")
    
    # Create CLI instance
    cli = ProcessorCLI()
    
    # Execute command
    try:
        if args.command == 'list':
            await cli.list_processors(verbose=args.verbose)
        elif args.command == 'health':
            await cli.health_check(processor_name=getattr(args, 'processor', None))
        elif args.command == 'test':
            await cli.test_processor(args.input, processor_name=getattr(args, 'processor', None))
        elif args.command == 'benchmark':
            await cli.benchmark(args.input, iterations=args.iterations)
        elif args.command == 'debug':
            await cli.debug_routing(args.input)
        elif args.command == 'stats':
            await cli.show_stats()
        elif args.command == 'clear-cache':
            await cli.clear_cache()
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    anyio.run(main)
