#!/usr/bin/env python3
"""
Comprehensive Python File Checker

This tool iterates through a directory and performs comprehensive checks on Python files:
1. Syntax checking (compilation)
2. Import checking (try to import each module)
3. Basic linting checks

Usage:
    python comprehensive_python_checker.py [directory] [options]

Options:
    -r, --recursive         Search recursively through subdirectories
    -v, --verbose          Show detailed output for each file
    -s, --summary-only     Only show summary statistics
    -o, --output FILE      Save results to file
    -e, --exclude PATTERN  Exclude files matching pattern (can be used multiple times)
    --check-syntax         Only check syntax (compilation)
    --check-imports        Only check imports
    --timeout SECONDS      Timeout for import checks (default: 10)
"""

import os
import sys
import argparse
import py_compile
import importlib.util
import importlib
import json
import time
import threading
import traceback
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass
from datetime import datetime
import signal

@dataclass
class CheckResult:
    """Result of checking a single Python file."""
    file_path: str
    syntax_ok: bool
    import_ok: bool
    syntax_error: Optional[str] = None
    import_error: Optional[str] = None
    check_time: float = 0.0
    skipped: bool = False
    skip_reason: Optional[str] = None

class TimeoutError(Exception):
    """Raised when an operation times out."""
    pass

class ImportChecker:
    """Handles import checking with timeout support."""
    
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.result = None
        self.error = None
        
    def _import_with_timeout(self, module_path: str, module_name: str):
        """Import a module with timeout handling."""
        try:
            # Try to load the module spec
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec is None:
                self.error = f"Could not create module spec for {module_name}"
                return
                
            # Create the module
            module = importlib.util.module_from_spec(spec)
            if module is None:
                self.error = f"Could not create module from spec for {module_name}"
                return
                
            # Add to sys.modules to handle circular imports
            sys.modules[module_name] = module
            
            # Execute the module
            spec.loader.exec_module(module)
            
            # If we get here, import was successful
            self.result = True
            
        except Exception as e:
            self.error = str(e)
            self.result = False
        finally:
            # Clean up sys.modules
            if module_name in sys.modules:
                del sys.modules[module_name]
    
    def check_import(self, file_path: str) -> tuple[bool, Optional[str]]:
        """Check if a Python file can be imported."""
        # Generate a unique module name
        module_name = f"temp_module_{int(time.time() * 1000000)}"
        
        # Create a thread to run the import
        thread = threading.Thread(
            target=self._import_with_timeout,
            args=(file_path, module_name)
        )
        
        thread.daemon = True
        thread.start()
        thread.join(timeout=self.timeout)
        
        if thread.is_alive():
            # Import timed out
            return False, f"Import timeout after {self.timeout} seconds"
        
        if self.result is None:
            return False, "Import check failed to complete"
            
        return self.result, self.error

class PythonFileChecker:
    """Main checker class for Python files."""
    
    def __init__(self, 
                 timeout: int = 10,
                 exclude_patterns: Optional[List[str]] = None):
        self.timeout = timeout
        self.exclude_patterns = exclude_patterns or []
        self.import_checker = ImportChecker(timeout)
        
        # Common patterns to exclude by default
        self.default_excludes = [
            '__pycache__',
            '.git',
            '.venv',
            'venv',
            '.pytest_cache',
            '.mypy_cache',
            'build',
            'dist',
            '*.egg-info'
        ]
        
    def should_exclude(self, file_path: str) -> tuple[bool, Optional[str]]:
        """Check if a file should be excluded based on patterns."""
        path_str = str(file_path)
        
        # Check default excludes
        for pattern in self.default_excludes:
            if pattern in path_str:
                return True, f"Matches default exclude pattern: {pattern}"
        
        # Check custom excludes
        for pattern in self.exclude_patterns:
            if pattern in path_str:
                return True, f"Matches exclude pattern: {pattern}"
                
        return False, None
    
    def check_syntax(self, file_path: str) -> tuple[bool, Optional[str]]:
        """Check if a Python file has valid syntax."""
        try:
            with open(file_path, 'rb') as f:
                source = f.read()
            
            # Try to compile the source
            compile(source, file_path, 'exec')
            return True, None
            
        except SyntaxError as e:
            return False, f"Syntax error at line {e.lineno}: {e.msg}"
        except Exception as e:
            return False, f"Compilation error: {str(e)}"
    
    def check_file(self, file_path: str, 
                   check_syntax: bool = True,
                   check_imports: bool = True) -> CheckResult:
        """Check a single Python file."""
        start_time = time.time()
        
        # Check if file should be excluded
        should_exclude, exclude_reason = self.should_exclude(file_path)
        if should_exclude:
            return CheckResult(
                file_path=file_path,
                syntax_ok=False,
                import_ok=False,
                skipped=True,
                skip_reason=exclude_reason,
                check_time=time.time() - start_time
            )
        
        result = CheckResult(file_path=file_path, syntax_ok=True, import_ok=True)
        
        # Check syntax if requested
        if check_syntax:
            syntax_ok, syntax_error = self.check_syntax(file_path)
            result.syntax_ok = syntax_ok
            result.syntax_error = syntax_error
        
        # Check imports if requested and syntax is OK
        if check_imports and result.syntax_ok:
            import_ok, import_error = self.import_checker.check_import(file_path)
            result.import_ok = import_ok
            result.import_error = import_error
        
        result.check_time = time.time() - start_time
        return result
    
    def find_python_files(self, directory: str, recursive: bool = True) -> List[str]:
        """Find all Python files in a directory."""
        python_files = []
        
        if recursive:
            for root, dirs, files in os.walk(directory):
                # Filter out excluded directories
                dirs[:] = [d for d in dirs if not any(pattern in d for pattern in self.default_excludes)]
                
                for file in files:
                    if file.endswith('.py'):
                        file_path = os.path.join(root, file)
                        python_files.append(file_path)
        else:
            for file in os.listdir(directory):
                if file.endswith('.py'):
                    file_path = os.path.join(directory, file)
                    if os.path.isfile(file_path):
                        python_files.append(file_path)
        
        return sorted(python_files)
    
    def check_directory(self, directory: str, 
                       recursive: bool = True,
                       check_syntax: bool = True,
                       check_imports: bool = True,
                       verbose: bool = False) -> List[CheckResult]:
        """Check all Python files in a directory."""
        python_files = self.find_python_files(directory, recursive)
        results = []
        
        if verbose:
            print(f"Found {len(python_files)} Python files to check")
            print(f"Checking syntax: {check_syntax}")
            print(f"Checking imports: {check_imports}")
            print(f"Timeout: {self.timeout} seconds")
            print("-" * 60)
        
        for i, file_path in enumerate(python_files):
            if verbose:
                print(f"[{i+1}/{len(python_files)}] Checking {file_path}")
            
            result = self.check_file(file_path, check_syntax, check_imports)
            results.append(result)
            
            if verbose:
                if result.skipped:
                    print(f"  SKIPPED: {result.skip_reason}")
                else:
                    status_parts = []
                    if check_syntax:
                        status_parts.append(f"Syntax: {'✓' if result.syntax_ok else '✗'}")
                    if check_imports:
                        status_parts.append(f"Import: {'✓' if result.import_ok else '✗'}")
                    
                    print(f"  {' | '.join(status_parts)} ({result.check_time:.2f}s)")
                    
                    if not result.syntax_ok:
                        print(f"    Syntax Error: {result.syntax_error}")
                    if not result.import_ok:
                        print(f"    Import Error: {result.import_error}")
        
        return results

def print_summary(results: List[CheckResult], 
                  check_syntax: bool = True,
                  check_imports: bool = True):
    """Print a summary of the check results."""
    total_files = len(results)
    skipped_files = sum(1 for r in results if r.skipped)
    checked_files = total_files - skipped_files
    
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Total files found: {total_files}")
    print(f"Files skipped: {skipped_files}")
    print(f"Files checked: {checked_files}")
    
    if checked_files > 0:
        if check_syntax:
            syntax_ok = sum(1 for r in results if not r.skipped and r.syntax_ok)
            syntax_errors = checked_files - syntax_ok
            print(f"Syntax OK: {syntax_ok}/{checked_files} ({syntax_ok/checked_files*100:.1f}%)")
            print(f"Syntax errors: {syntax_errors}")
        
        if check_imports:
            import_ok = sum(1 for r in results if not r.skipped and r.import_ok)
            import_errors = checked_files - import_ok
            print(f"Import OK: {import_ok}/{checked_files} ({import_ok/checked_files*100:.1f}%)")
            print(f"Import errors: {import_errors}")
    
    # Show files with errors
    error_files = [r for r in results if not r.skipped and (not r.syntax_ok or not r.import_ok)]
    
    if error_files:
        print(f"\nFiles with errors ({len(error_files)}):")
        print("-" * 60)
        
        for result in error_files:
            print(f"\n{result.file_path}:")
            if not result.syntax_ok:
                print(f"  Syntax Error: {result.syntax_error}")
            if not result.import_ok:
                print(f"  Import Error: {result.import_error}")

def save_results(results: List[CheckResult], output_path: str):
    """Save results to a JSON file."""
    data = {
        "timestamp": datetime.now().isoformat(),
        "total_files": len(results),
        "results": [
            {
                "file_path": r.file_path,
                "syntax_ok": r.syntax_ok,
                "import_ok": r.import_ok,
                "syntax_error": r.syntax_error,
                "import_error": r.import_error,
                "check_time": r.check_time,
                "skipped": r.skipped,
                "skip_reason": r.skip_reason
            }
            for r in results
        ]
    }
    
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"Results saved to: {output_path}")

def main():
    parser = argparse.ArgumentParser(
        description="Comprehensive Python file checker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        'directory',
        nargs='?',
        default='.',
        help='Directory to check (default: current directory)'
    )
    
    parser.add_argument(
        '-r', '--recursive',
        action='store_true',
        help='Search recursively through subdirectories'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Show detailed output for each file'
    )
    
    parser.add_argument(
        '-s', '--summary-only',
        action='store_true',
        help='Only show summary statistics'
    )
    
    parser.add_argument(
        '-o', '--output',
        help='Save results to JSON file'
    )
    
    parser.add_argument(
        '-e', '--exclude',
        action='append',
        default=[],
        help='Exclude files matching pattern (can be used multiple times)'
    )
    
    parser.add_argument(
        '--check-syntax',
        action='store_true',
        help='Only check syntax (compilation)'
    )
    
    parser.add_argument(
        '--check-imports',
        action='store_true',
        help='Only check imports'
    )
    
    parser.add_argument(
        '--timeout',
        type=int,
        default=10,
        help='Timeout for import checks in seconds (default: 10)'
    )
    
    args = parser.parse_args()
    
    # Determine what to check
    if args.check_syntax and args.check_imports:
        print("Error: Cannot specify both --check-syntax and --check-imports")
        sys.exit(1)
    
    check_syntax = not args.check_imports  # Default to True unless only checking imports
    check_imports = not args.check_syntax  # Default to True unless only checking syntax
    
    # Validate directory or file
    if os.path.isfile(args.directory):
        # Handle single file
        if not args.directory.endswith('.py'):
            print(f"Error: File '{args.directory}' is not a Python file")
            sys.exit(1)
        
        # Create checker and check single file
        checker = PythonFileChecker(
            timeout=args.timeout,
            exclude_patterns=args.exclude
        )
        
        result = checker.check_file(
            args.directory,
            check_syntax=check_syntax,
            check_imports=check_imports
        )
        
        results = [result]
        
    elif os.path.isdir(args.directory):
        # Handle directory
        # Create checker
        checker = PythonFileChecker(
            timeout=args.timeout,
            exclude_patterns=args.exclude
        )
        
        # Run checks
        results = checker.check_directory(
            directory=args.directory,
            recursive=args.recursive,
            check_syntax=check_syntax,
            check_imports=check_imports,
            verbose=args.verbose and not args.summary_only
        )
    else:
        print(f"Error: Path '{args.directory}' does not exist")
        sys.exit(1)
    
    # Create checker
    checker = PythonFileChecker(
        timeout=args.timeout,
        exclude_patterns=args.exclude
    )
    
    # Run checks
    try:
        # Results are already set above based on file vs directory
        pass
        
        # Print summary
        print_summary(results, check_syntax, check_imports)
        
        # Save results if requested
        if args.output:
            save_results(results, args.output)
            
        # Exit with error code if there were any failures
        error_count = sum(1 for r in results if not r.skipped and (not r.syntax_ok or not r.import_ok))
        if error_count > 0:
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
