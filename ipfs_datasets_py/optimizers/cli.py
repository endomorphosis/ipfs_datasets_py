#!/usr/bin/env python3
"""Unified CLI for all optimizer types.

Provides a single entry point for accessing:
- Agentic Optimizer (code optimization with multiple methods)
- Logic Theorem Optimizer (formal verification and theorem proving)
- GraphRAG Optimizer (knowledge graph and ontology optimization)

Usage:
    python -m ipfs_datasets_py.optimizers.cli --type agentic optimize ...
    python -m ipfs_datasets_py.optimizers.cli --type logic extract ...
    python -m ipfs_datasets_py.optimizers.cli --type graphrag generate ...

For help with a specific optimizer:
    python -m ipfs_datasets_py.optimizers.cli --type agentic --help
    python -m ipfs_datasets_py.optimizers.cli --type logic --help
    python -m ipfs_datasets_py.optimizers.cli --type graphrag --help
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional


class UnifiedOptimizerCLI:
    """Unified command-line interface for all optimizers."""
    
    OPTIMIZER_TYPES = ['agentic', 'logic', 'graphrag']
    
    def __init__(self):
        """Initialize unified CLI."""
        self.parser = self._create_parser()
    
    def _create_parser(self) -> argparse.ArgumentParser:
        """Create argument parser.
        
        Returns:
            Configured ArgumentParser
        """
        parser = argparse.ArgumentParser(
            prog='optimizers',
            description='Unified CLI for IPFS Datasets Optimizers',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  # Agentic optimizer (code optimization)
  %(prog)s --type agentic optimize --method adversarial --target mycode.py
  %(prog)s --type agentic stats
  %(prog)s --type agentic config --validation-level strict
  
  # Logic theorem optimizer (formal verification)
  %(prog)s --type logic extract --input contract.txt --output theorems.json
  %(prog)s --type logic prove --theorem "A implies B" --goal "B"
  %(prog)s --type logic validate --ontology my_ontology.owl
  
  # GraphRAG optimizer (knowledge graph optimization)
  %(prog)s --type graphrag generate --input document.pdf --domain legal
  %(prog)s --type graphrag optimize --ontology my_kg.owl --cycles 5
  %(prog)s --type graphrag query --optimize --query "climate change"

For optimizer-specific help:
  %(prog)s --type agentic --help
  %(prog)s --type logic --help
  %(prog)s --type graphrag --help
  
See docs/optimizers/SELECTION_GUIDE.md for choosing the right optimizer.
""")
        
        parser.add_argument(
            '--type',
            choices=self.OPTIMIZER_TYPES,
            required=True,
            help='Optimizer type to use'
        )
        
        parser.add_argument(
            '--verbose', '-v',
            action='store_true',
            help='Enable verbose output'
        )
        
        parser.add_argument(
            '--version',
            action='store_true',
            help='Show version information'
        )
        
        return parser
    
    def run(self, args: Optional[List[str]] = None) -> int:
        """Run the CLI.
        
        Args:
            args: Command-line arguments (defaults to sys.argv[1:])
            
        Returns:
            Exit code (0 for success, non-zero for error)
        """
        # Check for version flag first
        if args and '--version' in args:
            self._show_version()
            return 0
        
        # Parse just the type to route appropriately
        # This allows --help to be passed through to the specific optimizer
        if not args or '--help' in args or '-h' in args:
            # If no args or just help, show our help
            if not args or len(args) == 0 or (len(args) == 1 and args[0] in ['--help', '-h']):
                self.parser.print_help()
                return 0
        
        # Parse known args to get the optimizer type
        parsed_args, remaining = self.parser.parse_known_args(args)
        
        # Route to appropriate optimizer CLI
        optimizer_type = parsed_args.type
        
        try:
            if optimizer_type == 'agentic':
                return self._run_agentic(remaining, parsed_args.verbose)
            elif optimizer_type == 'logic':
                return self._run_logic(remaining, parsed_args.verbose)
            elif optimizer_type == 'graphrag':
                return self._run_graphrag(remaining, parsed_args.verbose)
            else:
                print(f"Error: Unknown optimizer type: {optimizer_type}")
                return 1
        except KeyboardInterrupt:
            print("\n\nInterrupted by user")
            return 130
        except Exception as e:
            print(f"Error: {e}")
            if parsed_args.verbose:
                import traceback
                traceback.print_exc()
            return 1
    
    def _show_version(self):
        """Show version information for all optimizers."""
        print("IPFS Datasets Optimizers")
        print("=" * 50)
        
        # Agentic optimizer version
        try:
            from ipfs_datasets_py.optimizers.agentic import __version__ as agentic_version
            print(f"Agentic Optimizer:       v{agentic_version} ✓")
        except Exception:
            print("Agentic Optimizer:       Not available")
        
        # Logic theorem optimizer version
        try:
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer import __version__ as logic_version
            print(f"Logic Theorem Optimizer: v{logic_version} ✓")
        except Exception:
            print("Logic Theorem Optimizer: Not available")
        
        # GraphRAG optimizer version
        try:
            from ipfs_datasets_py.optimizers.graphrag import __version__ as graphrag_version
            print(f"GraphRAG Optimizer:      v{graphrag_version} ✓")
        except Exception:
            print("GraphRAG Optimizer:      Not available")
        
        print("=" * 50)
    
    def _run_agentic(self, args: List[str], verbose: bool) -> int:
        """Run agentic optimizer CLI.
        
        Args:
            args: Remaining command-line arguments
            verbose: Enable verbose output
            
        Returns:
            Exit code
        """
        try:
            from ipfs_datasets_py.optimizers.agentic.cli import main as agentic_main
            
            if verbose:
                print("→ Routing to Agentic Optimizer CLI\n")
            
            return agentic_main(args)
        except ImportError as e:
            print(f"Error: Agentic optimizer not available: {e}")
            print("Install with: pip install -e '.[agentic]'")
            return 1
    
    def _run_logic(self, args: List[str], verbose: bool) -> int:
        """Run logic theorem optimizer CLI.
        
        Args:
            args: Remaining command-line arguments
            verbose: Enable verbose output
            
        Returns:
            Exit code
        """
        try:
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer.cli_wrapper import (
                LogicOptimizerCLI
            )
            
            if verbose:
                print("→ Routing to Logic Theorem Optimizer CLI\n")
            
            cli = LogicOptimizerCLI()
            return cli.run(args)
        except ImportError as e:
            print(f"Error: Logic theorem optimizer not available: {e}")
            print("Install with: pip install -e '.[logic]'")
            return 1
    
    def _run_graphrag(self, args: List[str], verbose: bool) -> int:
        """Run GraphRAG optimizer CLI.
        
        Args:
            args: Remaining command-line arguments
            verbose: Enable verbose output
            
        Returns:
            Exit code
        """
        try:
            from ipfs_datasets_py.optimizers.graphrag.cli_wrapper import (
                GraphRAGOptimizerCLI
            )
            
            if verbose:
                print("→ Routing to GraphRAG Optimizer CLI\n")
            
            cli = GraphRAGOptimizerCLI()
            return cli.run(args)
        except ImportError as e:
            print(f"Error: GraphRAG optimizer not available: {e}")
            print("Install with: pip install -e '.[graphrag]'")
            return 1


def main(args: Optional[List[str]] = None) -> int:
    """Main entry point.
    
    Args:
        args: Command-line arguments (defaults to sys.argv[1:])
        
    Returns:
        Exit code
    """
    cli = UnifiedOptimizerCLI()
    return cli.run(args)


if __name__ == '__main__':
    sys.exit(main())
