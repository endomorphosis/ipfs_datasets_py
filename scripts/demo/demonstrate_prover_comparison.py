#!/usr/bin/env python3
"""Multi-Prover Comparison Example.

This example demonstrates comparing results from different theorem provers:
- TDFOL symbolic prover
- SMT provers (Z3, CVC5)
- Neural prover (SymbolicAI)

Shows performance benchmarking and result comparison.
"""

import sys
import time
from pathlib import Path
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ipfs_datasets_py.logic.TDFOL import parse_tdfol, TDFOLProver
from ipfs_datasets_py.logic.external_provers import prover_router


def print_section(title: str):
    """Print formatted section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")


def test_formula_set() -> List[str]:
    """Get test formulas for comparison."""
    return [
        "P",  # Simple atom
        "P -> P",  # Tautology
        "P & Q -> P",  # Simplification
        "P -> Q, Q -> R => P -> R",  # Transitivity
        "(P -> Q) & P => Q",  # Modus ponens
        "~(P & ~P)",  # Law of non-contradiction
        "P | ~P",  # Law of excluded middle
        "O(P) -> P",  # Deontic D axiom
        "O(P) & O(Q) => O(P & Q)",  # Deontic aggregation
        "P(P) => ~F(P)",  # Permission/prohibition
    ]


def benchmark_prover(prover_name: str, prover_func, formulas: List[str]) -> Dict[str, Any]:
    """Benchmark a single prover."""
    results = {
        "name": prover_name,
        "total_time": 0.0,
        "successful": 0,
        "failed": 0,
        "skipped": 0,
        "individual_times": [],
    }

    for formula in formulas:
        start = time.time()
        try:
            result = prover_func(formula)
            elapsed = time.time() - start

            results["individual_times"].append(elapsed)
            results["total_time"] += elapsed

            if result:
                results["successful"] += 1
            else:
                results["failed"] += 1

        except Exception as e:
            elapsed = time.time() - start
            results["individual_times"].append(elapsed)
            results["total_time"] += elapsed
            results["skipped"] += 1

    return results


def demonstrate_multi_prover_comparison():
    """Demonstrate comparison between different provers."""
    print_section("MULTI-PROVER COMPARISON - PERFORMANCE BENCHMARKING")

    formulas = test_formula_set()

    print(f"Testing {len(formulas)} formulas across multiple provers...\n")

    # Display test formulas
    print("Test Formulas:")
    for i, formula in enumerate(formulas, 1):
        print(f"  {i}. {formula}")

    # Test 1: TDFOL Symbolic Prover
    print_section("Prover 1: TDFOL Symbolic Prover")

    tdfol_prover = TDFOLProver()

    def prove_with_tdfol(formula_str: str):
        """Prove using TDFOL."""
        try:
            formula = parse_tdfol(
                formula_str.split("=>")[0].strip() if "=>" in formula_str else formula_str
            )
            result = tdfol_prover.prove(formula)
            return result.proven
        except Exception:
            return False

    tdfol_results = benchmark_prover("TDFOL", prove_with_tdfol, formulas)

    print(f"✓ TDFOL Prover tested")
    print(f"  • Successful: {tdfol_results['successful']}/{len(formulas)}")
    print(f"  • Failed: {tdfol_results['failed']}")
    print(f"  • Skipped: {tdfol_results['skipped']}")
    print(f"  • Total time: {tdfol_results['total_time']:.3f}s")
    print(f"  • Average time: {tdfol_results['total_time'] / len(formulas):.4f}s")

    # Test 2: Prover Router (auto-selects best prover)
    print_section("Prover 2: Prover Router (Auto-Selection)")

    router = prover_router.ProverRouter()

    def prove_with_router(formula_str: str):
        """Prove using router."""
        try:
            result = router.prove(formula_str)
            return result
        except Exception:
            return False

    router_results = benchmark_prover("Router", prove_with_router, formulas)

    print(f"✓ Prover Router tested")
    print(f"  • Successful: {router_results['successful']}/{len(formulas)}")
    print(f"  • Failed: {router_results['failed']}")
    print(f"  • Skipped: {router_results['skipped']}")
    print(f"  • Total time: {router_results['total_time']:.3f}s")
    print(f"  • Average time: {router_results['total_time'] / len(formulas):.4f}s")

    # Test 3: Z3 SMT Prover (if available)
    print_section("Prover 3: Z3 SMT Prover")

    try:
        from ipfs_datasets_py.logic.external_provers.smt import z3_prover_bridge

        z3_bridge = z3_prover_bridge.Z3ProverBridge()

        def prove_with_z3(formula_str: str):
            """Prove using Z3."""
            try:
                result = z3_bridge.prove(formula_str)
                return result
            except Exception:
                return False

        z3_results = benchmark_prover("Z3", prove_with_z3, formulas)

        print(f"✓ Z3 Prover tested")
        print(f"  • Successful: {z3_results['successful']}/{len(formulas)}")
        print(f"  • Failed: {z3_results['failed']}")
        print(f"  • Skipped: {z3_results['skipped']}")
        print(f"  • Total time: {z3_results['total_time']:.3f}s")
        print(f"  • Average time: {z3_results['total_time'] / len(formulas):.4f}s")

    except Exception as e:
        print(f"⚠ Z3 not available: {e}")
        z3_results = None

    # Test 4: CVC5 SMT Prover (if available)
    print_section("Prover 4: CVC5 SMT Prover")

    try:
        from ipfs_datasets_py.logic.external_provers.smt import cvc5_prover_bridge

        cvc5_bridge = cvc5_prover_bridge.CVC5ProverBridge()

        def prove_with_cvc5(formula_str: str):
            """Prove using CVC5."""
            try:
                result = cvc5_bridge.prove(formula_str)
                return result
            except Exception:
                return False

        cvc5_results = benchmark_prover("CVC5", prove_with_cvc5, formulas)

        print(f"✓ CVC5 Prover tested")
        print(f"  • Successful: {cvc5_results['successful']}/{len(formulas)}")
        print(f"  • Failed: {cvc5_results['failed']}")
        print(f"  • Skipped: {cvc5_results['skipped']}")
        print(f"  • Total time: {cvc5_results['total_time']:.3f}s")
        print(f"  • Average time: {cvc5_results['total_time'] / len(formulas):.4f}s")

    except Exception as e:
        print(f"⚠ CVC5 not available: {e}")
        cvc5_results = None

    # Comparison Summary
    print_section("COMPARISON SUMMARY")

    all_results = [tdfol_results, router_results]

    if z3_results:
        all_results.append(z3_results)
    if cvc5_results:
        all_results.append(cvc5_results)

    print("Performance Comparison:")
    print(f"{'Prover':<15} {'Success Rate':<15} {'Avg Time':<15} {'Total Time':<15}")
    print("-" * 60)

    for result in all_results:
        success_rate = f"{result['successful']}/{len(formulas)}"
        avg_time = f"{result['total_time'] / len(formulas):.4f}s"
        total_time = f"{result['total_time']:.3f}s"

        print(f"{result['name']:<15} {success_rate:<15} {avg_time:<15} {total_time:<15}")

    # Fastest prover
    fastest = min(all_results, key=lambda x: x["total_time"])
    print(f"\n🏆 Fastest: {fastest['name']} ({fastest['total_time']:.3f}s total)")

    # Most successful prover
    most_successful = max(all_results, key=lambda x: x["successful"])
    print(
        f"🎯 Most Successful: {most_successful['name']} ({most_successful['successful']}/{len(formulas)})"
    )

    # Best overall (weighted score)
    print("\n📊 Overall Rankings:")
    for result in sorted(
        all_results, key=lambda x: (x["successful"], -x["total_time"]), reverse=True
    ):
        score = (result["successful"] / len(formulas)) * 100
        print(f"  {result['name']}: {score:.1f}% success, {result['total_time']:.3f}s")

    print_section("ANALYSIS COMPLETE")

    print("Key Findings:")
    print("  1. Different provers have different strengths")
    print("  2. Prover router can auto-select optimal prover")
    print("  3. Performance varies by formula complexity")
    print("  4. Multiple provers provide verification redundancy")

    return all_results


def main():
    """Run multi-prover comparison."""
    try:
        results = demonstrate_multi_prover_comparison()

        print("\n" + "=" * 70)
        print("  SUCCESS: Multi-Prover Comparison Complete")
        print("=" * 70)

        return 0

    except Exception as e:
        print(f"\n✗ Error during comparison: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
