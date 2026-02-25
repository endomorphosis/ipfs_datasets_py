#!/usr/bin/env python
"""Comprehensive GraphRAG benchmark suite orchestrator.

Runs all GraphRAG benchmarks in sequence and generates a unified performance report
comparing results against baselines and historical data.

Features:
- Runs all extraction, critique, validation, and end-to-end benchmarks
- Aggregates results into unified JSON/Markdown reports
- Compares against baseline performance (warns on regressions)
- Tracks historical performance trends
- Supports CI/CD integration (exit code 1 on regression)

Usage:
    # Run all benchmarks
    python benchmarks/bench_graphrag_suite.py
    
    # Run specific benchmark categories
    python benchmarks/bench_graphrag_suite.py --categories extraction,validation
    
    # Update baseline (after verifying performance improvement)
    python benchmarks/bench_graphrag_suite.py --update-baseline
    
    # CI mode (fail on regression)
    python benchmarks/bench_graphrag_suite.py --ci
"""

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class BenchmarkResult:
    """Result from a single benchmark run."""
    
    name: str
    category: str
    status: str  # "passed", "failed", "skipped"
    execution_time_s: float
    metrics: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class SuiteResult:
    """Result from full benchmark suite run."""
    
    timestamp: str
    total_benchmarks: int
    passed: int
    failed: int
    skipped: int
    total_time_s: float
    benchmarks: List[BenchmarkResult] = field(default_factory=list)
    regressions: List[str] = field(default_factory=list)
    improvements: List[str] = field(default_factory=list)


class GraphRAGBenchmarkSuite:
    """Comprehensive benchmark suite orchestrator."""
    
    # Benchmark definitions: (filename, category, description)
    BENCHMARKS = [
        # Extraction benchmarks
        ("bench_ontology_extraction_baseline.py", "extraction",
         "Baseline extraction performance across token sizes"),
        ("bench_ontology_generator_extract_entities_10k.py", "extraction",
         "10k-token entity extraction performance"),
        ("bench_extraction_strategy_performance.py", "extraction",
         "Extraction strategy comparison (rule-based vs LLM fallback)"),
        
        # Relationship inference benchmarks
        ("bench_infer_relationships_scaling.py", "relationships",
         "Relationship inference scaling with entity count"),
        ("bench_relationship_type_confidence_scoring.py", "relationships",
         "Relationship type confidence scoring performance"),
        
        # Validation benchmarks
        ("bench_logic_validator_validate_ontology.py", "validation",
         "Logic validator performance on synthetic ontologies"),
        
        # Generator benchmarks
        ("bench_ontology_generator_generate.py", "generator",
         "Full generator pipeline performance"),
        ("bench_ontology_generator_rule_based.py", "generator",
         "Rule-based generator performance"),
        
        # Query optimization benchmarks
        ("bench_query_validation_cache_key.py", "query",
         "Query validation cache key generation performance"),
        ("bench_query_optimizer_under_load.py", "query",
         "Query optimizer performance under load"),
        
        # End-to-end benchmarks
        ("bench_end_to_end_pipeline_performance.py", "end_to_end",
         "Complete pipeline performance (generation → critique → refinement)"),
    ]
    
    def __init__(
        self,
        benchmark_dir: Path,
        results_dir: Path,
        baseline_path: Optional[Path] = None,
        ci_mode: bool = False,
    ):
        """Initialize benchmark suite.
        
        Args:
            benchmark_dir: Directory containing benchmark scripts
            results_dir: Directory to write results
            baseline_path: Path to baseline performance data
            ci_mode: Whether to fail on regressions
        """
        self.benchmark_dir = benchmark_dir
        self.results_dir = results_dir
        self.baseline_path = baseline_path or (results_dir / "baseline.json")
        self.ci_mode = ci_mode
        
        self.results_dir.mkdir(parents=True, exist_ok=True)
    
    def run_benchmark(self, filename: str, category: str, description: str) -> BenchmarkResult:
        """Run a single benchmark and return result.
        
        Args:
            filename: Benchmark script filename
            category: Benchmark category
            description: Benchmark description
            
        Returns:
            BenchmarkResult with execution metrics
        """
        print(f"\n{'='*70}")
        print(f"Running: {filename}")
        print(f"Category: {category}")
        print(f"Description: {description}")
        print(f"{'='*70}\n")
        
        script_path = self.benchmark_dir / filename
        
        if not script_path.exists():
            print(f"⚠️  Benchmark script not found: {script_path}")
            return BenchmarkResult(
                name=filename,
                category=category,
                status="skipped",
                execution_time_s=0,
                error=f"Script not found: {script_path}",
            )
        
        start_time = time.time()
        
        try:
            result = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )
            
            execution_time = time.time() - start_time
            
            if result.returncode == 0:
                print(f"✓ {filename} completed in {execution_time:.2f}s")
                return BenchmarkResult(
                    name=filename,
                    category=category,
                    status="passed",
                    execution_time_s=execution_time,
                    metrics=self._extract_metrics(result.stdout),
                )
            else:
                print(f"✗ {filename} failed with exit code {result.returncode}")
                print(f"STDERR: {result.stderr[:200]}")
                return BenchmarkResult(
                    name=filename,
                    category=category,
                    status="failed",
                    execution_time_s=execution_time,
                    error=result.stderr[:500],
                )
        
        except subprocess.TimeoutExpired:
            execution_time = time.time() - start_time
            print(f"✗ {filename} timed out after {execution_time:.2f}s")
            return BenchmarkResult(
                name=filename,
                category=category,
                status="failed",
                execution_time_s=execution_time,
                error="Benchmark timed out (>300s)",
            )
        
        except Exception as e:
            execution_time = time.time() - start_time
            print(f"✗ {filename} raised exception: {e}")
            return BenchmarkResult(
                name=filename,
                category=category,
                status="failed",
                execution_time_s=execution_time,
                error=str(e),
            )
    
    def _extract_metrics(self, stdout: str) -> Dict[str, Any]:
        """Extract metrics from benchmark stdout.
        
        Looks for JSON blocks or key-value pairs in output.
        """
        metrics = {}
        
        # Try to find JSON output
        try:
            # Look for last JSON block in output
            for line in reversed(stdout.split('\n')):
                if line.strip().startswith('{'):
                    metrics = json.loads(line)
                    break
        except (json.JSONDecodeError, ValueError):
            pass
        
        # Extract simple metrics (e.g., "Latency: 123.45ms")
        for line in stdout.split('\n'):
            if ':' in line:
                parts = line.split(':', 1)
                if len(parts) == 2:
                    key = parts[0].strip().lower().replace(' ', '_')
                    value_str = parts[1].strip()
                    
                    # Try to parse number
                    try:
                        if 'ms' in value_str:
                            value = float(value_str.replace('ms', ''))
                            metrics[f"{key}_ms"] = value
                        elif 's' in value_str and 'ms' not in value_str:
                            value = float(value_str.replace('s', ''))
                            metrics[f"{key}_s"] = value
                        else:
                            value = float(value_str)
                            metrics[key] = value
                    except ValueError:
                        pass
        
        return metrics
    
    def run_suite(self, categories: Optional[List[str]] = None) -> SuiteResult:
        """Run full benchmark suite or specific categories.
        
        Args:
            categories: Optional list of categories to run (default: all)
            
        Returns:
            SuiteResult with aggregated metrics
        """
        suite_start = time.time()
        results = []
        
        for filename, category, description in self.BENCHMARKS:
            if categories and category not in categories:
                print(f"Skipping {filename} (category {category} not in filter)")
                continue
            
            result = self.run_benchmark(filename, category, description)
            results.append(result)
        
        suite_time = time.time() - suite_start
        
        passed = sum(1 for r in results if r.status == "passed")
        failed = sum(1 for r in results if r.status == "failed")
        skipped = sum(1 for r in results if r.status == "skipped")
        
        suite_result = SuiteResult(
            timestamp=datetime.now().isoformat(),
            total_benchmarks=len(results),
            passed=passed,
            failed=failed,
            skipped=skipped,
            total_time_s=suite_time,
            benchmarks=results,
        )
        
        # Compare against baseline if available
        if self.baseline_path.exists():
            baseline = self._load_baseline()
            suite_result.regressions, suite_result.improvements = self._compare_to_baseline(
                results, baseline
            )
        
        return suite_result
    
    def _load_baseline(self) -> Dict[str, Any]:
        """Load baseline performance data."""
        try:
            with open(self.baseline_path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Warning: Could not load baseline from {self.baseline_path}: {e}")
            return {}
    
    def _compare_to_baseline(
        self,
        results: List[BenchmarkResult],
        baseline: Dict[str, Any],
    ) -> tuple[List[str], List[str]]:
        """Compare results to baseline and identify regressions/improvements.
        
        Returns:
            (regressions, improvements) - lists of benchmark names
        """
        regressions = []
        improvements = []
        
        baseline_benchmarks = {b["name"]: b for b in baseline.get("benchmarks", [])}
        
        for result in results:
            if result.status != "passed":
                continue
            
            baseline_result = baseline_benchmarks.get(result.name)
            if not baseline_result:
                continue
            
            # Compare execution time (>10% slower = regression)
            baseline_time = baseline_result.get("execution_time_s", 0)
            if baseline_time > 0:
                time_delta = (result.execution_time_s - baseline_time) / baseline_time
                
                if time_delta > 0.10:  # 10% slower
                    regressions.append(
                        f"{result.name}: {time_delta*100:.1f}% slower "
                        f"({result.execution_time_s:.2f}s vs {baseline_time:.2f}s baseline)"
                    )
                elif time_delta < -0.10:  # 10% faster
                    improvements.append(
                        f"{result.name}: {-time_delta*100:.1f}% faster "
                        f"({result.execution_time_s:.2f}s vs {baseline_time:.2f}s baseline)"
                    )
        
        return regressions, improvements
    
    def save_results(self, suite_result: SuiteResult, output_prefix: str = "suite") -> None:
        """Save suite results to JSON and Markdown files.
        
        Args:
            suite_result: Suite result to save
            output_prefix: Filename prefix (default: "suite")
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save JSON
        json_path = self.results_dir / f"{output_prefix}_{timestamp}.json"
        with open(json_path, "w") as f:
            json.dump(asdict(suite_result), f, indent=2, default=str)
        
        print(f"\n✓ JSON results saved to: {json_path}")
        
        # Save Markdown report
        md_path = self.results_dir / f"{output_prefix}_{timestamp}.md"
        with open(md_path, "w") as f:
            f.write(self._generate_markdown_report(suite_result))
        
        print(f"✓ Markdown report saved to: {md_path}")
        
        # Also save as "latest"
        latest_json = self.results_dir / f"{output_prefix}_latest.json"
        latest_md = self.results_dir / f"{output_prefix}_latest.md"
        
        with open(latest_json, "w") as f:
            json.dump(asdict(suite_result), f, indent=2, default=str)
        
        with open(latest_md, "w") as f:
            f.write(self._generate_markdown_report(suite_result))
        
        print(f"✓ Latest results saved to: {latest_json}, {latest_md}")
    
    def _generate_markdown_report(self, suite_result: SuiteResult) -> str:
        """Generate Markdown report from suite result."""
        lines = [
            "# GraphRAG Benchmark Suite Report",
            "",
            f"**Timestamp:** {suite_result.timestamp}  ",
            f"**Total Benchmarks:** {suite_result.total_benchmarks}  ",
            f"**Passed:** {suite_result.passed}  ",
            f"**Failed:** {suite_result.failed}  ",
            f"**Skipped:** {suite_result.skipped}  ",
            f"**Total Time:** {suite_result.total_time_s:.2f}s  ",
            "",
        ]
        
        if suite_result.regressions:
            lines.extend([
                "## ⚠️ Performance Regressions",
                "",
            ])
            for regression in suite_result.regressions:
                lines.append(f"- {regression}")
            lines.append("")
        
        if suite_result.improvements:
            lines.extend([
                "## ✨ Performance Improvements",
                "",
            ])
            for improvement in suite_result.improvements:
                lines.append(f"- {improvement}")
            lines.append("")
        
        # Results by category
        by_category = {}
        for result in suite_result.benchmarks:
            by_category.setdefault(result.category, []).append(result)
        
        for category, results in sorted(by_category.items()):
            lines.extend([
                f"## {category.title()} Benchmarks",
                "",
                "| Benchmark | Status | Time (s) |",
                "|-----------|--------|----------|",
            ])
            
            for result in results:
                status_emoji = {
                    "passed": "✓",
                    "failed": "✗",
                    "skipped": "⊘",
                }.get(result.status, "?")
                
                lines.append(
                    f"| {result.name} | {status_emoji} {result.status} | "
                    f"{result.execution_time_s:.2f} |"
                )
            
            lines.append("")
        
        return "\n".join(lines)
    
    def update_baseline(self, suite_result: SuiteResult) -> None:
        """Update baseline with current suite results.
        
        Args:
            suite_result: Suite result to use as new baseline
        """
        with open(self.baseline_path, "w") as f:
            json.dump(asdict(suite_result), f, indent=2, default=str)
        
        print(f"\n✓ Baseline updated: {self.baseline_path}")


def main():
    parser = argparse.ArgumentParser(description="Run GraphRAG benchmark suite")
    parser.add_argument(
        "--categories",
        help="Comma-separated list of categories to run (extraction,relationships,validation,generator,query,end_to_end)",
        default=None,
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Update baseline with current results (use after verifying improvements)",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: exit with code 1 if any regressions detected",
    )
    parser.add_argument(
        "--benchmark-dir",
        type=Path,
        default=Path(__file__).parent,
        help="Directory containing benchmark scripts",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path(__file__).parent / "results",
        help="Directory to write results",
    )
    
    args = parser.parse_args()
    
    categories = args.categories.split(",") if args.categories else None
    
    suite = GraphRAGBenchmarkSuite(
        benchmark_dir=args.benchmark_dir,
        results_dir=args.results_dir,
        ci_mode=args.ci,
    )
    
    print("=" * 70)
    print("GraphRAG Benchmark Suite")
    print("=" * 70)
    print(f"Benchmark dir: {args.benchmark_dir}")
    print(f"Results dir: {args.results_dir}")
    if categories:
        print(f"Categories: {', '.join(categories)}")
    print()
    
    # Run suite
    suite_result = suite.run_suite(categories=categories)
    
    # Save results
    suite.save_results(suite_result)
    
    # Update baseline if requested
    if args.update_baseline:
        suite.update_baseline(suite_result)
    
    # Print summary
    print("\n" + "=" * 70)
    print("SUITE SUMMARY")
    print("=" * 70)
    print(f"Total: {suite_result.total_benchmarks}")
    print(f"Passed: {suite_result.passed}")
    print(f"Failed: {suite_result.failed}")
    print(f"Skipped: {suite_result.skipped}")
    print(f"Total time: {suite_result.total_time_s:.2f}s")
    
    if suite_result.regressions:
        print(f"\n⚠️  {len(suite_result.regressions)} performance regression(s) detected:")
        for regression in suite_result.regressions:
            print(f"  - {regression}")
    
    if suite_result.improvements:
        print(f"\n✨ {len(suite_result.improvements)} performance improvement(s) detected:")
        for improvement in suite_result.improvements:
            print(f"  - {improvement}")
    
    # Exit code logic
    if suite_result.failed > 0:
        print("\n✗ Some benchmarks failed")
        sys.exit(1)
    
    if args.ci and suite_result.regressions:
        print("\n✗ CI mode: Performance regressions detected")
        sys.exit(1)
    
    print("\n✓ All benchmarks passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
