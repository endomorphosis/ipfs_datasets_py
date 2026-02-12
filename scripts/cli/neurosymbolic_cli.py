#!/usr/bin/env python3
"""
Neurosymbolic Reasoner CLI

Command-line interface for the neurosymbolic reasoning system.

Usage:
    neurosymbolic-cli --help
    neurosymbolic-cli capabilities
    neurosymbolic-cli prove --axiom "P" --axiom "P -> Q" --goal "Q"
    neurosymbolic-cli parse --format tdfol "P -> Q"
    neurosymbolic-cli interactive
"""

import argparse
import sys
import logging
from typing import List

# Configure logging
logging.basicConfig(level=logging.WARNING)


def setup_parser() -> argparse.ArgumentParser:
    """Setup command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Neurosymbolic Reasoning CLI",
        epilog="For more information, see examples/neurosymbolic/README.md"
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Capabilities command
    subparsers.add_parser(
        'capabilities',
        help='Show system capabilities'
    )
    
    # Prove command
    prove_parser = subparsers.add_parser(
        'prove',
        help='Prove a theorem'
    )
    prove_parser.add_argument(
        '--axiom',
        action='append',
        dest='axioms',
        help='Add an axiom (can be used multiple times)'
    )
    prove_parser.add_argument(
        '--goal',
        required=True,
        help='Goal formula to prove'
    )
    prove_parser.add_argument(
        '--timeout',
        type=int,
        default=5000,
        help='Timeout in milliseconds (default: 5000)'
    )
    prove_parser.add_argument(
        '--format',
        choices=['auto', 'tdfol', 'dcec', 'nl'],
        default='auto',
        help='Input format (default: auto)'
    )
    
    # Parse command
    parse_parser = subparsers.add_parser(
        'parse',
        help='Parse a formula'
    )
    parse_parser.add_argument(
        'formula',
        help='Formula to parse'
    )
    parse_parser.add_argument(
        '--format',
        choices=['auto', 'tdfol', 'dcec', 'nl'],
        default='auto',
        help='Input format (default: auto)'
    )
    
    # Explain command
    explain_parser = subparsers.add_parser(
        'explain',
        help='Explain a formula in natural language'
    )
    explain_parser.add_argument(
        'formula',
        help='Formula to explain'
    )
    explain_parser.add_argument(
        '--format',
        choices=['auto', 'tdfol', 'dcec'],
        default='auto',
        help='Input format (default: auto)'
    )
    
    # Interactive command
    subparsers.add_parser(
        'interactive',
        help='Start interactive REPL'
    )
    
    # Version command
    subparsers.add_parser(
        'version',
        help='Show version information'
    )
    
    return parser


def command_capabilities():
    """Show system capabilities."""
    from ipfs_datasets_py.logic.integration import NeurosymbolicReasoner
    
    print("Neurosymbolic Reasoning System Capabilities")
    print("=" * 60)
    
    reasoner = NeurosymbolicReasoner()
    caps = reasoner.get_capabilities()
    
    print(f"\nInference Rules:")
    print(f"  TDFOL rules:     {caps['tdfol_rules']}")
    print(f"  CEC rules:       {caps['cec_rules']}")
    print(f"  Total rules:     {caps['total_inference_rules']}")
    
    print(f"\nModal Logic Provers:")
    for prover in caps['modal_provers']:
        print(f"  - {prover}")
    
    print(f"\nFeatures:")
    print(f"  ShadowProver:    {'✓' if caps['shadowprover_available'] else '✗'}")
    print(f"  Grammar:         {'✓' if caps['grammar_available'] else '✗'}")
    print(f"  Natural Language: {'✓' if caps['natural_language'] else '✗'}")
    
    print("\n" + "=" * 60)


def command_prove(axioms: List[str], goal: str, timeout: int, format: str):
    """Prove a theorem."""
    from ipfs_datasets_py.logic.integration import NeurosymbolicReasoner
    
    print("Theorem Proving")
    print("=" * 60)
    
    # Create reasoner
    reasoner = NeurosymbolicReasoner()
    
    # Add axioms
    print("\nAxioms:")
    if axioms:
        for axiom in axioms:
            reasoner.add_knowledge(axiom)
            print(f"  ✓ {axiom}")
    else:
        print("  (none)")
    
    # Parse goal
    print(f"\nGoal: {goal}")
    
    # Attempt proof
    print(f"\nAttempting proof (timeout: {timeout}ms)...")
    goal_formula = reasoner.parse(goal, format=format)
    
    if not goal_formula:
        print(f"✗ Error: Could not parse goal '{goal}'")
        return 1
    
    result = reasoner.prove(goal_formula, timeout_ms=timeout)
    
    # Display result
    print("\nResult:")
    print(f"  Status:  {result.status.value}")
    print(f"  Method:  {result.method}")
    print(f"  Time:    {result.time_ms:.2f}ms")
    
    if result.proof_steps:
        print(f"  Steps:   {len(result.proof_steps)}")
    
    if result.is_proved():
        print(f"\n✓ PROVED!")
        return 0
    else:
        print(f"\n✗ Not proved")
        if result.message:
            print(f"  Reason: {result.message}")
        return 1


def command_parse(formula: str, format: str):
    """Parse a formula."""
    from ipfs_datasets_py.logic.integration import NeurosymbolicReasoner
    
    print("Formula Parsing")
    print("=" * 60)
    
    reasoner = NeurosymbolicReasoner()
    
    print(f"\nInput:  {formula}")
    print(f"Format: {format}")
    
    parsed = reasoner.parse(formula, format=format)
    
    if parsed:
        print(f"\n✓ Parsed successfully!")
        print(f"  Result: {parsed.to_string()}")
        return 0
    else:
        print(f"\n✗ Parsing failed")
        return 1


def command_explain(formula: str, format: str):
    """Explain a formula in natural language."""
    from ipfs_datasets_py.logic.integration import NeurosymbolicReasoner
    
    print("Formula Explanation")
    print("=" * 60)
    
    reasoner = NeurosymbolicReasoner()
    
    print(f"\nFormula: {formula}")
    
    # Parse formula
    parsed = reasoner.parse(formula, format=format)
    
    if not parsed:
        print(f"\n✗ Error: Could not parse formula")
        return 1
    
    # Explain
    explanation = reasoner.explain(parsed)
    
    print(f"\nExplanation:")
    print(f"  {explanation}")
    
    return 0


def command_interactive():
    """Start interactive REPL."""
    from ipfs_datasets_py.logic.integration import NeurosymbolicReasoner
    
    print("Neurosymbolic Reasoning Interactive REPL")
    print("=" * 60)
    print("Commands:")
    print("  add <formula>      - Add formula to knowledge base")
    print("  prove <formula>    - Prove a formula")
    print("  parse <formula>    - Parse and display formula")
    print("  explain <formula>  - Explain formula in natural language")
    print("  caps               - Show capabilities")
    print("  clear              - Clear knowledge base")
    print("  help               - Show this help")
    print("  quit/exit          - Exit REPL")
    print("=" * 60)
    
    reasoner = NeurosymbolicReasoner()
    
    while True:
        try:
            line = input("\n> ").strip()
            
            if not line:
                continue
            
            if line in ['quit', 'exit']:
                print("Goodbye!")
                break
            
            if line == 'help':
                print("\nCommands: add, prove, parse, explain, caps, clear, help, quit")
                continue
            
            if line == 'caps':
                caps = reasoner.get_capabilities()
                print(f"\nTotal inference rules: {caps['total_inference_rules']}")
                continue
            
            if line == 'clear':
                reasoner = NeurosymbolicReasoner()
                print("\n✓ Knowledge base cleared")
                continue
            
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                print("✗ Invalid command. Type 'help' for usage.")
                continue
            
            cmd, arg = parts
            
            if cmd == 'add':
                reasoner.add_knowledge(arg)
                print(f"✓ Added: {arg}")
            
            elif cmd == 'prove':
                formula = reasoner.parse(arg)
                if formula:
                    result = reasoner.prove(formula, timeout_ms=5000)
                    print(f"Status: {result.status.value}")
                    print(f"Method: {result.method}")
                    print(f"Time: {result.time_ms:.2f}ms")
                    if result.is_proved():
                        print("✓ PROVED")
                    else:
                        print("✗ Not proved")
                else:
                    print("✗ Could not parse formula")
            
            elif cmd == 'parse':
                formula = reasoner.parse(arg)
                if formula:
                    print(f"✓ {formula.to_string()}")
                else:
                    print("✗ Parsing failed")
            
            elif cmd == 'explain':
                formula = reasoner.parse(arg)
                if formula:
                    explanation = reasoner.explain(formula)
                    print(f"→ {explanation}")
                else:
                    print("✗ Could not parse formula")
            
            else:
                print(f"✗ Unknown command: {cmd}")
        
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except EOFError:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"✗ Error: {e}")


def command_version():
    """Show version information."""
    print("Neurosymbolic Reasoning System")
    print("Version: 1.0")
    print("All critical gaps resolved")
    print()
    print("Components:")
    print("  - TDFOL Module (40 inference rules)")
    print("  - CEC Integration (87 inference rules)")
    print("  - ShadowProver (5 modal logic provers)")
    print("  - Grammar Engine (NL processing)")
    print()
    print("For more information:")
    print("  https://github.com/endomorphosis/ipfs_datasets_py")


def main():
    """Main entry point."""
    parser = setup_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    try:
        if args.command == 'capabilities':
            command_capabilities()
            return 0
        
        elif args.command == 'prove':
            return command_prove(
                args.axioms or [],
                args.goal,
                args.timeout,
                args.format
            )
        
        elif args.command == 'parse':
            return command_parse(args.formula, args.format)
        
        elif args.command == 'explain':
            return command_explain(args.formula, args.format)
        
        elif args.command == 'interactive':
            command_interactive()
            return 0
        
        elif args.command == 'version':
            command_version()
            return 0
        
        else:
            print(f"Unknown command: {args.command}")
            return 1
    
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
