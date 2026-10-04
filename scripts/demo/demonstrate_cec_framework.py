#!/usr/bin/env python3
"""
Demonstration of the CEC (Cognitive Event Calculus) Framework.

This script demonstrates the key features of the neurosymbolic CEC framework,
including natural language conversion, knowledge management, and theorem proving.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from ipfs_datasets_py.logic.CEC import (
    CECFramework,
    FrameworkConfig,
    ReasoningMode
)


def print_section(title):
    """Print a formatted section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")


def demo_basic_usage():
    """Demonstrate basic framework usage."""
    print_section("Basic Framework Usage")
    
    # Create and initialize framework
    print("1. Creating CEC Framework...")
    framework = CECFramework()
    print(f"   Framework created: {framework}")
    
    print("\n2. Initializing components...")
    init_results = framework.initialize()
    print(f"   Initialization results:")
    for component, status in init_results.items():
        status_str = "✓ Available" if status else "✗ Unavailable"
        print(f"   - {component}: {status_str}")
    
    return framework


def demo_reasoning(framework):
    """Demonstrate reasoning capabilities."""
    print_section("Reasoning Capabilities")
    
    # Test natural language reasoning
    statements = [
        "The agent must fulfill their obligation",
        "The agent has permission to act",
        "The agent believes the goal is achievable"
    ]
    
    print("Processing natural language statements:")
    for i, statement in enumerate(statements, 1):
        print(f"\n{i}. Input: '{statement}'")
        task = framework.reason_about(statement, prove=False)
        print(f"   Success: {task.success}")
        if task.dcec_formula:
            print(f"   DCEC Formula: {task.dcec_formula}")
        if task.error_message:
            print(f"   Note: {task.error_message}")


def demo_knowledge_base(framework):
    """Demonstrate knowledge base management."""
    print_section("Knowledge Base Management")
    
    knowledge_items = [
        "rule1: obligation implies intent",
        "rule2: permission allows action",
        "rule3: belief affects decision"
    ]
    
    print("Adding knowledge to the framework:")
    for item in knowledge_items:
        result = framework.add_knowledge(item)
        status = "✓ Added" if result else "✗ Failed"
        print(f"   {status}: {item}")


def demo_batch_processing(framework):
    """Demonstrate batch processing."""
    print_section("Batch Processing")
    
    batch_statements = [
        "Agent A must cooperate with Agent B",
        "Agent B has the right to refuse",
        "The system ensures fairness"
    ]
    
    print(f"Processing {len(batch_statements)} statements in batch...")
    tasks = framework.batch_reason(batch_statements, prove=False)
    
    print("\nResults:")
    for i, task in enumerate(tasks, 1):
        print(f"   {i}. {task.natural_language}")
        print(f"      Success: {task.success}")


def demo_temporal_reasoning():
    """Demonstrate temporal reasoning mode."""
    print_section("Temporal Reasoning Mode")
    
    # Create framework with temporal reasoning
    config = FrameworkConfig(reasoning_mode=ReasoningMode.TEMPORAL)
    temporal_framework = CECFramework(config)
    temporal_framework.initialize()
    
    print("Temporal reasoning examples:")
    temporal_statements = [
        "Eventually the agent will complete the task",
        "The obligation holds at time T",
        "After action X, state Y is true"
    ]
    
    for statement in temporal_statements:
        print(f"\n   Input: '{statement}'")
        task = temporal_framework.reason_about(statement, prove=False)
        print(f"   Processed: {task.success or 'attempted'}")


def demo_statistics(framework):
    """Demonstrate statistics collection."""
    print_section("Framework Statistics")
    
    stats = framework.get_statistics()
    
    print("Framework statistics:")
    print(f"   Initialized: {stats.get('initialized', False)}")
    print(f"   Total reasoning tasks: {stats.get('reasoning_tasks', 0)}")
    print(f"   Successful tasks: {stats.get('successful_tasks', 0)}")
    
    if 'dcec' in stats:
        print(f"\n   DCEC Library:")
        print(f"   - Statements: {stats['dcec'].get('statements', 0)}")
    
    if 'talos' in stats:
        print(f"\n   Talos Prover:")
        print(f"   - Total attempts: {stats['talos'].get('total_attempts', 0)}")
    
    if 'eng_dcec' in stats:
        print(f"\n   Eng-DCEC Converter:")
        print(f"   - Total conversions: {stats['eng_dcec'].get('total_conversions', 0)}")


def demo_configuration():
    """Demonstrate configuration options."""
    print_section("Configuration Options")
    
    print("Example configurations:\n")
    
    print("1. Minimal configuration (only DCEC):")
    config1 = FrameworkConfig(
        use_dcec=True,
        use_talos=False,
        use_eng_dcec=False,
        use_shadow_prover=False
    )
    print(f"   DCEC: {config1.use_dcec}, Talos: {config1.use_talos}")
    print(f"   Eng-DCEC: {config1.use_eng_dcec}, ShadowProver: {config1.use_shadow_prover}")
    
    print("\n2. Full configuration with temporal reasoning:")
    config2 = FrameworkConfig(
        use_dcec=True,
        use_talos=True,
        use_eng_dcec=True,
        use_shadow_prover=True,
        reasoning_mode=ReasoningMode.TEMPORAL,
        gf_server_url="http://localhost:41296"
    )
    print(f"   All components enabled")
    print(f"   Reasoning mode: {config2.reasoning_mode.value}")
    print(f"   GF Server: {config2.gf_server_url}")
    
    print("\n3. Hybrid reasoning configuration:")
    config3 = FrameworkConfig(
        reasoning_mode=ReasoningMode.HYBRID
    )
    print(f"   Reasoning mode: {config3.reasoning_mode.value}")
    print(f"   Combines simultaneous and temporal reasoning")


def main():
    """Main demonstration function."""
    print("\n" + "╔" + "═" * 68 + "╗")
    print("║" + " " * 8 + "CEC Framework - Demonstration Script" + " " * 24 + "║")
    print("║" + " " * 8 + "Neurosymbolic Cognitive Event Calculus" + " " * 22 + "║")
    print("╚" + "═" * 68 + "╝")
    
    try:
        # Run demonstrations
        framework = demo_basic_usage()
        demo_configuration()
        demo_reasoning(framework)
        demo_knowledge_base(framework)
        demo_batch_processing(framework)
        demo_temporal_reasoning()
        demo_statistics(framework)
        
        # Summary
        print_section("Summary")
        print("The CEC Framework provides:")
        print("   ✓ Unified neurosymbolic reasoning API")
        print("   ✓ Natural language to formal logic conversion")
        print("   ✓ Automated theorem proving")
        print("   ✓ Multiple reasoning modes (simultaneous, temporal, hybrid)")
        print("   ✓ Graceful degradation when components unavailable")
        print("   ✓ Comprehensive statistics and error handling")
        
        print("\nDemonstration completed successfully!")
        print("\nNote: Some components may be unavailable due to dependencies.")
        print("The framework uses graceful fallback mode in such cases.\n")
        
    except Exception as e:
        print(f"\n❌ Error during demonstration: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
