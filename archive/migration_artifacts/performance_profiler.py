#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Performance Profiler for Development Tools

This tool helps measure and optimize the performance of development tools.
It provides timing information and optimization recommendations.
"""

import sys
import time
import traceback
import statistics
from pathlib import Path
from typing import Dict, List, Any, Callable, Optional
import cProfile
import pstats
import io
import json
import datetime

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

class ToolProfiler:
    """Profiles the performance of development tools."""

    def __init__(self, output_dir: Optional[str] = None):
        """Initialize the profiler.

        Args:
            output_dir: Optional directory to save profiling results
        """
        self.output_dir = Path(output_dir) if output_dir else Path(__file__).parent / "profiling_results"
        self.output_dir.mkdir(exist_ok=True, parents=True)
        self.results = {}

    def profile_tool(self, tool_func: Callable, tool_name: str, *args, **kwargs) -> Dict[str, Any]:
        """Profile a single tool function.

        Args:
            tool_func: The tool function to profile
            tool_name: Name of the tool
            *args, **kwargs: Arguments to pass to the tool function

        Returns:
            Dictionary with profiling results
        """
        print(f"Profiling {tool_name}...")

        # Basic timing
        start_time = time.time()

        # Use cProfile for detailed profiling
        pr = cProfile.Profile()
        pr.enable()

        try:
            result = tool_func(*args, **kwargs)
            success = True
        except Exception as e:
            result = f"Error: {str(e)}"
            traceback.print_exc()
            success = False
        finally:
            pr.disable()

        end_time = time.time()
        duration = end_time - start_time

        # Process cProfile results
        s = io.StringIO()
        ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
        ps.print_stats(10)  # Top 10 functions by time

        # Extract function stats
        profile_text = s.getvalue()

        # Store results
        profile_result = {
            'tool_name': tool_name,
            'duration': duration,
            'timestamp': datetime.datetime.now().isoformat(),
            'success': success,
            'profile_summary': profile_text,
            'args': str(args),
            'kwargs': str(kwargs),
        }

        # Save to output directory
        timestamp = int(time.time())
        profile_file = self.output_dir / f"{tool_name}_{timestamp}.json"
        with open(profile_file, 'w') as f:
            # We need to convert the profile text separately as it's not JSON serializable
            result_copy = profile_result.copy()
            result_copy['profile_summary'] = str(result_copy['profile_summary'])
            json.dump(result_copy, f, indent=2)

        if tool_name not in self.results:
            self.results[tool_name] = []
        self.results[tool_name].append(profile_result)

        return profile_result

    def benchmark_tool(self, tool_func: Callable, tool_name: str, repeat: int = 3, *args, **kwargs) -> Dict[str, Any]:
        """Benchmark a tool by running it multiple times.

        Args:
            tool_func: The tool function to benchmark
            tool_name: Name of the tool
            repeat: Number of times to run the benchmark
            *args, **kwargs: Arguments to pass to the tool function

        Returns:
            Dictionary with benchmark results
        """
        print(f"Benchmarking {tool_name} ({repeat} runs)...")
        times = []

        for i in range(repeat):
            print(f"  Run {i+1}/{repeat}...")
            start_time = time.time()
            try:
                tool_func(*args, **kwargs)
                end_time = time.time()
                times.append(end_time - start_time)
            except Exception as e:
                print(f"  Error in run {i+1}: {e}")

        if not times:
            return {'tool_name': tool_name, 'error': 'All benchmark runs failed'}

        result = {
            'tool_name': tool_name,
            'runs': repeat,
            'successful_runs': len(times),
            'min_time': min(times),
            'max_time': max(times),
            'mean_time': statistics.mean(times),
            'median_time': statistics.median(times),
            'std_dev': statistics.stdev(times) if len(times) > 1 else 0
        }

        # Save benchmark results
        timestamp = int(time.time())
        benchmark_file = self.output_dir / f"{tool_name}_benchmark_{timestamp}.json"
        with open(benchmark_file, 'w') as f:
            json.dump(result, f, indent=2)

        return result

    def analyze_results(self) -> Dict[str, Any]:
        """Analyze profiling results and provide optimization recommendations.

        Returns:
            Dictionary with analysis and recommendations
        """
        analysis = {}

        for tool_name, runs in self.results.items():
            if not runs:
                continue

            durations = [run['duration'] for run in runs if run['success']]
            if not durations:
                analysis[tool_name] = {
                    'status': 'No successful runs',
                    'recommendations': ['Fix errors before optimization']
                }
                continue

            avg_duration = sum(durations) / len(durations)

            # Simple analysis based on execution time
            status = 'good' if avg_duration < 1.0 else 'slow' if avg_duration < 5.0 else 'very slow'
            recommendations = []

            if status == 'slow' or status == 'very slow':
                # Analyze profile data for slow functions
                slow_funcs = []
                for run in runs:
                    if 'profile_summary' in run:
                        # Simple string parsing of profile output
                        for line in run['profile_summary'].split('\n'):
                            if 'cumtime' in line and not line.startswith('   ncalls'):
                                parts = line.strip().split()
                                if len(parts) >= 6:
                                    func_name = ' '.join(parts[5:])
                                    if func_name not in slow_funcs:
                                        slow_funcs.append(func_name)

                if slow_funcs:
                    recommendations.append(f"Consider optimizing these slow functions: {', '.join(slow_funcs[:3])}")

                recommendations.append("Consider adding caching for repeated operations")
                recommendations.append("Review algorithms for complexity improvements")

            analysis[tool_name] = {
                'status': status,
                'average_duration': avg_duration,
                'min_duration': min(durations),
                'max_duration': max(durations),
                'num_runs': len(durations),
                'recommendations': recommendations
            }

        # Save analysis
        timestamp = int(time.time())
        analysis_file = self.output_dir / f"performance_analysis_{timestamp}.json"
        with open(analysis_file, 'w') as f:
            json.dump(analysis, f, indent=2)

        return analysis


def profile_development_tools():
    """Profile all development tools."""
    print("=" * 50)
    print("Development Tools Performance Profiler")
    print("=" * 50)

    # Import development tools
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools import (
            test_generator,
            codebase_search,
            documentation_generator,
            lint_python_codebase,
            run_comprehensive_tests
        )
        print("✅ Development tools imported successfully")
    except Exception as e:
        print(f"❌ Error importing development tools: {e}")
        return False

    profiler = ToolProfiler(output_dir="profiling_results")

    # Profile codebase_search
    profiler.profile_tool(
        codebase_search,
        "codebase_search",
        pattern="import",
        path=".",
        max_depth=2,
        format="text"
    )

    # Profile documentation_generator
    profiler.profile_tool(
        documentation_generator,
        "documentation_generator",
        file_path="vscode_integration_test.py",
        output_format="markdown"
    )

    # Profile lint_python_codebase
    profiler.profile_tool(
        lint_python_codebase,
        "lint_python_codebase",
        path="vscode_integration_test.py"
    )

    # Profile test_generator
    profiler.profile_tool(
        test_generator,
        "test_generator",
        file_path="vscode_integration_test.py",
        test_framework="pytest"
    )

    # Performance analysis
    analysis = profiler.analyze_results()

    # Print summary
    print("\n" + "=" * 50)
    print("Performance Analysis Summary")
    print("=" * 50)

    for tool_name, tool_analysis in analysis.items():
        status_emoji = "✅" if tool_analysis['status'] == 'good' else "⚠️" if tool_analysis['status'] == 'slow' else "❌"
        print(f"\n{status_emoji} {tool_name}:")
        print(f"  Status: {tool_analysis['status']}")
        print(f"  Average duration: {tool_analysis['average_duration']:.2f}s")

        if tool_analysis['recommendations']:
            print("  Recommendations:")
            for rec in tool_analysis['recommendations']:
                print(f"  - {rec}")

    print("\n✅ Performance profiling complete!")
    print(f"Detailed results saved to: {profiler.output_dir}")

    return True

if __name__ == "__main__":
    success = profile_development_tools()
    sys.exit(0 if success else 1)
