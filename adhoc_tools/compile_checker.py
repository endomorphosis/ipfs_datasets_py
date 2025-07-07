#!/usr/bin/env python3
"""
Python File Compilation Checker

A command line tool that iterates through a directory and tries to compile every Python file,
reporting syntax errors and compilation issues.
"""

import os
import sys
import argparse
import py_compile
import ast
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import json
import time
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging


@dataclass
class CompilationResult:
    """Result of compiling a single Python file."""
    file_path: str
    success: bool
    error_message: Optional[str] = None
    error_type: Optional[str] = None
    line_number: Optional[int] = None
    column_number: Optional[int] = None
    compile_time: float = 0.0


class PythonCompileChecker:
    """Main class for checking Python file compilation."""
    
    def __init__(self, directory: str, exclude_patterns: Optional[List[str]] = None,
                 include_patterns: Optional[List[str]] = None, recursive: bool = True,
                 max_workers: int = 4, verbose: bool = False):
        """
        Initialize the Python compile checker.
        
        Args:
            directory: Root directory to scan for Python files
            exclude_patterns: List of glob patterns to exclude (e.g., ['*test*', '__pycache__'])
            include_patterns: List of glob patterns to include (defaults to ['*.py'])
            recursive: Whether to scan subdirectories recursively
            max_workers: Maximum number of threads for parallel compilation
            verbose: Whether to enable verbose logging
        """
        self.directory = Path(directory).resolve()
        self.exclude_patterns = exclude_patterns or ['__pycache__', '*.pyc', '.git', '.venv', 'venv']
        self.include_patterns = include_patterns or ['*.py']
        self.recursive = recursive
        self.max_workers = max_workers
        self.verbose = verbose
        
        # Setup logging
        logging.basicConfig(
            level=logging.DEBUG if verbose else logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        # Results storage
        self.results: List[CompilationResult] = []
        
    def find_python_files(self) -> List[Path]:
        """
        Find all Python files in the directory based on patterns.
        
        Returns:
            List of Path objects for Python files to check
        """
        python_files = []
        
        if self.recursive:
            pattern = '**/*.py'
        else:
            pattern = '*.py'
            
        # Find all Python files
        for py_file in self.directory.glob(pattern):
            if py_file.is_file():
                # Check if file should be excluded
                should_exclude = False
                for exclude_pattern in self.exclude_patterns:
                    if py_file.match(exclude_pattern) or exclude_pattern in str(py_file):
                        should_exclude = True
                        break
                
                if not should_exclude:
                    python_files.append(py_file)
        
        self.logger.info(f"Found {len(python_files)} Python files to check")
        return python_files
    
    def compile_file(self, file_path: Path) -> CompilationResult:
        """
        Attempt to compile a single Python file.
        
        Args:
            file_path: Path to the Python file to compile
            
        Returns:
            CompilationResult object with compilation details
        """
        start_time = time.time()
        
        try:
            # First try to parse with AST for syntax checking
            with open(file_path, 'r', encoding='utf-8') as f:
                source_code = f.read()
            
            # Parse with AST to catch syntax errors
            try:
                ast.parse(source_code, filename=str(file_path))
            except SyntaxError as e:
                return CompilationResult(
                    file_path=str(file_path),
                    success=False,
                    error_message=str(e),
                    error_type='SyntaxError',
                    line_number=e.lineno,
                    column_number=e.offset,
                    compile_time=time.time() - start_time
                )
            
            # Try to compile with py_compile for bytecode generation
            try:
                py_compile.compile(file_path, doraise=True)
            except py_compile.PyCompileError as e:
                return CompilationResult(
                    file_path=str(file_path),
                    success=False,
                    error_message=str(e),
                    error_type='PyCompileError',
                    compile_time=time.time() - start_time
                )
            
            # If we get here, compilation was successful
            return CompilationResult(
                file_path=str(file_path),
                success=True,
                compile_time=time.time() - start_time
            )
            
        except UnicodeDecodeError as e:
            return CompilationResult(
                file_path=str(file_path),
                success=False,
                error_message=f"Unicode decode error: {str(e)}",
                error_type='UnicodeDecodeError',
                compile_time=time.time() - start_time
            )
        except Exception as e:
            return CompilationResult(
                file_path=str(file_path),
                success=False,
                error_message=f"Unexpected error: {str(e)}",
                error_type=type(e).__name__,
                compile_time=time.time() - start_time
            )
    
    def check_all_files(self) -> Dict[str, any]:
        """
        Check compilation of all Python files in the directory.
        
        Returns:
            Dictionary with compilation results and statistics
        """
        python_files = self.find_python_files()
        
        if not python_files:
            self.logger.warning("No Python files found to check")
            return {
                'total_files': 0,
                'successful': 0,
                'failed': 0,
                'results': [],
                'summary': "No Python files found"
            }
        
        self.logger.info(f"Starting compilation check for {len(python_files)} files")
        
        # Use ThreadPoolExecutor for parallel compilation
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all compilation tasks
            future_to_file = {
                executor.submit(self.compile_file, py_file): py_file 
                for py_file in python_files
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_file):
                file_path = future_to_file[future]
                try:
                    result = future.result()
                    self.results.append(result)
                    
                    if self.verbose:
                        if result.success:
                            self.logger.info(f"✓ {result.file_path} - OK ({result.compile_time:.3f}s)")
                        else:
                            self.logger.error(f"✗ {result.file_path} - {result.error_type}: {result.error_message}")
                            
                except Exception as e:
                    self.logger.error(f"Failed to process {file_path}: {str(e)}")
                    self.results.append(CompilationResult(
                        file_path=str(file_path),
                        success=False,
                        error_message=f"Processing error: {str(e)}",
                        error_type='ProcessingError'
                    ))
        
        # Calculate statistics
        total_files = len(self.results)
        successful = sum(1 for r in self.results if r.success)
        failed = total_files - successful
        
        # Sort results by file path for consistent output
        self.results.sort(key=lambda x: x.file_path)
        
        return {
            'total_files': total_files,
            'successful': successful,
            'failed': failed,
            'success_rate': (successful / total_files * 100) if total_files > 0 else 0,
            'results': self.results,
            'summary': f"Checked {total_files} files: {successful} successful, {failed} failed"
        }
    
    def print_summary(self, check_results: Dict[str, any]) -> None:
        """Print a summary of compilation results."""
        print("\n" + "="*60)
        print("PYTHON COMPILATION CHECK SUMMARY")
        print("="*60)
        
        print(f"Directory: {self.directory}")
        print(f"Total files checked: {check_results['total_files']}")
        print(f"Successful compilations: {check_results['successful']}")
        print(f"Failed compilations: {check_results['failed']}")
        print(f"Success rate: {check_results['success_rate']:.1f}%")
        
        # Show failed files
        failed_results = [r for r in check_results['results'] if not r.success]
        if failed_results:
            print(f"\nFAILED FILES ({len(failed_results)}):")
            print("-" * 60)
            for result in failed_results:
                print(f"✗ {result.file_path}")
                print(f"  Error: {result.error_type}: {result.error_message}")
                if result.line_number:
                    print(f"  Line: {result.line_number}" + 
                          (f", Column: {result.column_number}" if result.column_number else ""))
                print()
        
        # Show timing stats
        if check_results['results']:
            compile_times = [r.compile_time for r in check_results['results']]
            avg_time = sum(compile_times) / len(compile_times)
            max_time = max(compile_times)
            print(f"\nTIMING STATISTICS:")
            print(f"Average compile time: {avg_time:.3f}s")
            print(f"Maximum compile time: {max_time:.3f}s")
            print(f"Total time: {sum(compile_times):.3f}s")
    
    def save_results(self, output_file: str, format: str = 'json') -> None:
        """
        Save compilation results to a file.
        
        Args:
            output_file: Path to output file
            format: Output format ('json' or 'csv')
        """
        if not self.results:
            self.logger.warning("No results to save")
            return
        
        if format.lower() == 'json':
            # Convert results to JSON-serializable format
            json_results = []
            for result in self.results:
                json_results.append({
                    'file_path': result.file_path,
                    'success': result.success,
                    'error_message': result.error_message,
                    'error_type': result.error_type,
                    'line_number': result.line_number,
                    'column_number': result.column_number,
                    'compile_time': result.compile_time
                })
            
            with open(output_file, 'w') as f:
                json.dump({
                    'directory': str(self.directory),
                    'timestamp': time.time(),
                    'results': json_results
                }, f, indent=2)
                
        elif format.lower() == 'csv':
            import csv
            with open(output_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['file_path', 'success', 'error_type', 'error_message', 
                               'line_number', 'column_number', 'compile_time'])
                for result in self.results:
                    writer.writerow([
                        result.file_path, result.success, result.error_type,
                        result.error_message, result.line_number, 
                        result.column_number, result.compile_time
                    ])
        
        self.logger.info(f"Results saved to {output_file}")


def main():
    """Main entry point for the command line tool."""
    parser = argparse.ArgumentParser(
        description="Check compilation of Python files in a directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s /path/to/project                    # Check all .py files recursively
  %(prog)s . --exclude "*test*" "__pycache__"  # Exclude test files and cache
  %(prog)s src --no-recursive                  # Check only direct files in src/
  %(prog)s . --output results.json             # Save results to JSON file
  %(prog)s . --max-workers 8 --verbose         # Use 8 threads with verbose output
        """
    )
    
    parser.add_argument(
        'path',
        help='Directory or file to scan for Python files'
    )
    
    parser.add_argument(
        '--exclude',
        nargs='*',
        default=['__pycache__', '*.pyc', '.git', '.venv', 'venv'],
        help='Patterns to exclude (default: __pycache__ *.pyc .git .venv venv)'
    )
    
    parser.add_argument(
        '--include',
        nargs='*',
        default=['*.py'],
        help='Patterns to include (default: *.py)'
    )
    
    parser.add_argument(
        '--no-recursive',
        action='store_true',
        help='Don\'t scan subdirectories recursively'
    )
    
    parser.add_argument(
        '--max-workers',
        type=int,
        default=4,
        help='Maximum number of parallel workers (default: 4)'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose output'
    )
    
    parser.add_argument(
        '--output', '-o',
        help='Output file to save results (JSON or CSV based on extension)'
    )
    
    parser.add_argument(
        '--format',
        choices=['json', 'csv'],
        default='json',
        help='Output format when saving results (default: json)'
    )
    
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Suppress summary output (useful for automation)'
    )
    
    args = parser.parse_args()
    
    # Validate path
    if not os.path.exists(args.path):
        print(f"Error: Path '{args.path}' does not exist", file=sys.stderr)
        sys.exit(1)
    
    if os.path.isfile(args.path):
        if not args.path.endswith('.py'):
            print(f"Error: '{args.path}' is not a Python file", file=sys.stderr)
            sys.exit(1)
        # For single file, create a temporary checker that handles just that file
        directory = os.path.dirname(args.path)
        filename = os.path.basename(args.path)
        checker = PythonCompileChecker(
            directory=directory,
            exclude_patterns=args.exclude,
            include_patterns=[filename],  # Only include this specific file
            recursive=False,
            max_workers=1,
            verbose=args.verbose
        )
    elif os.path.isdir(args.path):
        # Create checker instance for directory
        checker = PythonCompileChecker(
            directory=args.path,
            exclude_patterns=args.exclude,
            include_patterns=args.include,
            recursive=not args.no_recursive,
            max_workers=args.max_workers,
            verbose=args.verbose
        )
    else:
        print(f"Error: '{args.path}' is not a valid file or directory", file=sys.stderr)
        sys.exit(1)
    
    # Run compilation check
    try:
        results = checker.check_all_files()
        
        # Print summary unless quiet mode
        if not args.quiet:
            checker.print_summary(results)
        
        # Save results if output file specified
        if args.output:
            # Determine format from file extension if not specified
            if args.format == 'json' and args.output.lower().endswith('.csv'):
                format_to_use = 'csv'
            elif args.format == 'csv' and args.output.lower().endswith('.json'):
                format_to_use = 'json'
            else:
                format_to_use = args.format
            
            checker.save_results(args.output, format_to_use)
        
        # Exit with appropriate code
        if results['failed'] > 0:
            sys.exit(1)
        else:
            sys.exit(0)
            
    except KeyboardInterrupt:
        print("\nOperation cancelled by user", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
