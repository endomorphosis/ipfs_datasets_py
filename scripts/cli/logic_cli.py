#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CEC Logic CLI Commands

Provides command-line interface for CEC logic operations including parsing,
proving, and analysis with multi-language support.
"""

import argparse
import sys
import json
from typing import Dict, Any, Optional, List


def format_output(result: Dict[str, Any], format_type: str = "text") -> str:
    """
    Format result for output.
    
    Args:
        result: Result dictionary from tool execution
        format_type: Output format (text/json/compact)
    
    Returns:
        Formatted string
    """
    if format_type == "json":
        return json.dumps(result, indent=2)
    elif format_type == "compact":
        return json.dumps(result)
    else:  # text
        lines = []
        if result.get('success'):
            lines.append("✅ Success")
        else:
            lines.append("❌ Failed")
        
        # Format based on result type
        if 'formula' in result:
            lines.append(f"Formula: {result['formula']}")
        if 'proved' in result:
            status = "Proved" if result['proved'] else "Not proved"
            lines.append(f"Status: {status}")
        if 'complexity' in result:
            lines.append(f"Complexity: {result['complexity']}")
        if 'error' in result:
            lines.append(f"Error: {result['error']}")
        
        return "\n".join(lines)


def parse_command(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Execute parse command.
    
    Args:
        args: Parsed command-line arguments
    
    Returns:
        Result dictionary
    """
    try:
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import parse_dcec
        
        result = parse_dcec(
            text=args.text,
            language=args.language,
            domain=args.domain if hasattr(args, 'domain') else None
        )
        
        return result
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def prove_command(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Execute prove command.
    
    Args:
        args: Parsed command-line arguments
    
    Returns:
        Result dictionary
    """
    try:
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_prove_tool import prove_dcec
        
        axioms = args.axioms.split(',') if hasattr(args, 'axioms') and args.axioms else None
        
        result = prove_dcec(
            goal=args.goal,
            axioms=axioms,
            strategy=args.strategy if hasattr(args, 'strategy') else "auto",
            timeout=args.timeout if hasattr(args, 'timeout') else 30
        )
        
        return result
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def analyze_command(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Execute analyze command.
    
    Args:
        args: Parsed command-line arguments
    
    Returns:
        Result dictionary
    """
    try:
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import analyze_formula
        
        result = analyze_formula(formula=args.formula)
        
        return result
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def profile_command(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Execute profile command.
    
    Args:
        args: Parsed command-line arguments
    
    Returns:
        Result dictionary
    """
    try:
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import profile_operation
        
        result = profile_operation(
            operation=args.operation,
            formula=args.formula,
            iterations=args.iterations if hasattr(args, 'iterations') else 1
        )
        
        return result
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def translate_command(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Execute translate command.
    
    Args:
        args: Parsed command-line arguments
    
    Returns:
        Result dictionary
    """
    try:
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import translate_dcec
        
        result = translate_dcec(
            formula=args.formula,
            target_format=args.format if hasattr(args, 'format') else "tptp"
        )
        
        return result
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def validate_command(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Execute validate command.
    
    Args:
        args: Parsed command-line arguments
    
    Returns:
        Result dictionary
    """
    try:
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import validate_formula
        
        result = validate_formula(formula=args.formula)
        
        return result
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for logic commands."""
    parser = argparse.ArgumentParser(
        prog='ipfs-datasets logic',
        description='CEC Logic Operations CLI'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Parse command
    parse_parser = subparsers.add_parser('parse', help='Parse natural language to DCEC formula')
    parse_parser.add_argument('text', help='Text to parse')
    parse_parser.add_argument('--language', '-l', default='en', 
                             help='Language code (en/es/fr/de/auto)')
    parse_parser.add_argument('--domain', '-d', 
                             help='Domain vocabulary (legal/medical/technical)')
    parse_parser.add_argument('--format', '-f', default='text',
                             choices=['text', 'json', 'compact'],
                             help='Output format')
    
    # Prove command
    prove_parser = subparsers.add_parser('prove', help='Prove a theorem')
    prove_parser.add_argument('goal', help='Goal formula to prove')
    prove_parser.add_argument('--axioms', '-a', help='Comma-separated axioms')
    prove_parser.add_argument('--strategy', '-s', default='auto',
                             choices=['auto', 'z3', 'vampire', 'e_prover'],
                             help='Prover strategy')
    prove_parser.add_argument('--timeout', '-t', type=int, default=30,
                             help='Timeout in seconds')
    prove_parser.add_argument('--format', '-f', default='text',
                             choices=['text', 'json', 'compact'],
                             help='Output format')
    
    # Analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Analyze formula complexity')
    analyze_parser.add_argument('formula', help='Formula to analyze')
    analyze_parser.add_argument('--format', '-f', default='text',
                               choices=['text', 'json', 'compact'],
                               help='Output format')
    
    # Profile command
    profile_parser = subparsers.add_parser('profile', help='Profile operation performance')
    profile_parser.add_argument('operation', choices=['parse', 'prove', 'analyze'],
                               help='Operation to profile')
    profile_parser.add_argument('formula', help='Formula to use')
    profile_parser.add_argument('--iterations', '-i', type=int, default=10,
                               help='Number of iterations')
    profile_parser.add_argument('--format', '-f', default='text',
                               choices=['text', 'json', 'compact'],
                               help='Output format')
    
    # Translate command
    translate_parser = subparsers.add_parser('translate', help='Translate formula to another format')
    translate_parser.add_argument('formula', help='Formula to translate')
    translate_parser.add_argument('--format', '-f', default='tptp',
                                 choices=['tptp', 'z3', 'json'],
                                 help='Target format')
    translate_parser.add_argument('--output-format', '-o', default='text',
                                 choices=['text', 'json', 'compact'],
                                 help='Output format')
    
    # Validate command
    validate_parser = subparsers.add_parser('validate', help='Validate formula syntax')
    validate_parser.add_argument('formula', help='Formula to validate')
    validate_parser.add_argument('--format', '-f', default='text',
                                choices=['text', 'json', 'compact'],
                                help='Output format')
    
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """
    Main entry point for logic CLI.
    
    Args:
        argv: Command-line arguments (defaults to sys.argv[1:])
    
    Returns:
        Exit code (0 for success, 1 for error)
    """
    parser = create_parser()
    args = parser.parse_args(argv)
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Execute command
    command_map = {
        'parse': parse_command,
        'prove': prove_command,
        'analyze': analyze_command,
        'profile': profile_command,
        'translate': translate_command,
        'validate': validate_command
    }
    
    command_func = command_map.get(args.command)
    if not command_func:
        print(f"Error: Unknown command '{args.command}'", file=sys.stderr)
        return 1
    
    try:
        result = command_func(args)
        output_format = getattr(args, 'output_format', None) or getattr(args, 'format', 'text')
        print(format_output(result, output_format))
        return 0 if result.get('success', False) else 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
