"""Simple single-agent optimization example.

This example demonstrates how to use the agentic optimizer to optimize
a single Python file using the test-driven optimization method.
"""

from pathlib import Path
from ipfs_datasets_py.optimizers.agentic import (
    TestDrivenOptimizer,
    OptimizationTask,
    ChangeControlMethod,
)


def main():
    """Run single-agent optimization example."""
    print("=" * 60)
    print("Single-Agent Optimization Example")
    print("=" * 60)
    
    # Configure target file
    target_file = Path("ipfs_datasets_py/cache.py")
    
    if not target_file.exists():
        print(f"Error: Target file not found: {target_file}")
        return 1
    
    print(f"\nTarget file: {target_file}")
    print(f"Optimization method: Test-Driven Development")
    
    # Create optimization task
    task = OptimizationTask(
        task_id="example-simple-001",
        description="Optimize cache implementation for better performance",
        target_files=[target_file],
        priority=75,
        constraints={
            "min_performance_improvement": 0.1,  # 10% minimum
            "max_test_coverage_drop": 0.0,  # No coverage drop
            "preserve_api": True,  # Keep existing API
        },
    )
    
    print(f"\nTask ID: {task.task_id}")
    print(f"Priority: {task.priority}")
    print(f"Constraints: {len(task.constraints)} defined")
    
    # Create optimizer
    # Note: In production, you would pass an actual LLM router here
    print("\nCreating optimizer...")
    print("Note: This example requires an LLM router to be configured")
    print("      Please configure the LLM router before running")
    
    # Example configuration (would be actual LLM router in production)
    """
    from ipfs_datasets_py.llm_router import LLMRouter
    
    llm_router = LLMRouter(
        providers=["openai", "anthropic"],
        default_provider="openai",
        api_keys={
            "openai": os.getenv("OPENAI_API_KEY"),
            "anthropic": os.getenv("ANTHROPIC_API_KEY"),
        },
    )
    
    optimizer = TestDrivenOptimizer(
        agent_id="simple-agent-001",
        llm_router=llm_router,
        change_control=ChangeControlMethod.PATCH,
    )
    
    print("\nRunning optimization...")
    result = optimizer.optimize(task)
    
    print("\n" + "=" * 60)
    print("Optimization Results")
    print("=" * 60)
    print(f"Success: {result.success}")
    print(f"Changes: {result.changes}")
    print(f"Execution time: {result.execution_time:.2f}s")
    
    if result.patch_path:
        print(f"Patch saved to: {result.patch_path}")
    
    if result.patch_cid:
        print(f"IPFS CID: {result.patch_cid}")
    
    print(f"\nValidation:")
    print(f"  Passed: {result.validation.passed}")
    print(f"  Errors: {len(result.validation.errors)}")
    print(f"  Warnings: {len(result.validation.warnings)}")
    
    if result.metrics:
        print(f"\nMetrics:")
        for key, value in result.metrics.items():
            print(f"  {key}: {value}")
    
    return 0 if result.success else 1
    """
    
    print("\nExample configuration shown above.")
    print("Please adapt for your environment.")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
