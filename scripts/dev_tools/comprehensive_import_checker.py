#!/usr/bin/env python3
"""
Comprehensive Python Import Checker

A command line tool that checks both compilation AND import errors in Python files.
This tool goes beyond syntax checking to detect:
- Circular imports
- Missing class/function definitions
- Import resolution failures
- Module initialization issues

Usage:
    python comprehensive_import_checker.py [directory/file] [options]
"""

import os
import sys
import argparse
import ast
import importlib.util
import importlib
import json
import time
import threading
import traceback
import tempfile
import shutil
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Set, Any
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import signal
import subprocess
from contextlib import contextmanager
import py_compile


@dataclass
class CheckResult:
    """Result of checking a single Python file."""
    file_path: str
    syntax_ok: bool
    import_ok: bool
    syntax_error: Optional[str] = None
    import_error: Optional[str] = None
    import_timeout: bool = False
    circular_import: bool = False
    missing_dependencies: List[str] = None
    check_time: float = 0.0
    skipped: bool = False
    skip_reason: Optional[str] = None
    
    def __post_init__(self):
        if self.missing_dependencies is None:
            self.missing_dependencies = []


class ImportTimeoutError(Exception):
    """Raised when an import operation times out."""
    pass


class IsolatedImportChecker:
    """Handles import checking in isolated processes to avoid contamination."""
    
    def __init__(self, timeout: int = 15, verbose: bool = False):
        self.timeout = timeout
        self.verbose = verbose
        self.logger = logging.getLogger(__name__)
        
    def check_import_in_subprocess(self, file_path: str, module_name: str) -> Tuple[bool, Optional[str], bool, List[str]]:
        """
        Check if a Python file can be imported in a subprocess.
        
        Returns:
            Tuple of (success, error_message, is_circular_import, missing_dependencies)
        """
        # Get absolute path
        abs_file_path = os.path.abspath(file_path)
        
        # Create a temporary script to test the import
        test_script = f'''
import sys
import os
import importlib.util
import traceback
import json

def test_import():
    try:
        # Use absolute path
        file_path = r"{abs_file_path}"
        module_name = "{module_name}"
        
        # Verify file exists
        if not os.path.exists(file_path):
            return False, f"File not found: {{file_path}}", False, []
        
        # Get the directory containing the file
        module_dir = os.path.dirname(file_path)
        if module_dir not in sys.path:
            sys.path.insert(0, module_dir)
        
        # Also add parent directories to handle relative imports
        parent_dir = os.path.dirname(module_dir)
        if parent_dir and parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        
        # Load the module spec
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None:
            return False, "Could not create module spec", False, []
        
        # Create the module
        module = importlib.util.module_from_spec(spec)
        if module is None:
            return False, "Could not create module from spec", False, []
        
        # Add to sys.modules temporarily
        original_modules = sys.modules.copy()
        sys.modules[module_name] = module
        
        try:
            # Execute the module - this is where import errors occur
            spec.loader.exec_module(module)
            return True, None, False, []
        except Exception as e:
            error_msg = str(e)
            is_circular = "circular import" in error_msg.lower() or "partially initialized module" in error_msg.lower()
            
            # Try to extract missing dependencies
            missing_deps = []
            if "No module named" in error_msg:
                import re
                matches = re.findall(r"No module named '([^']+)'", error_msg)
                missing_deps.extend(matches)
            
            return False, error_msg, is_circular, missing_deps
        finally:
            # Clean up sys.modules
            sys.modules.clear()
            sys.modules.update(original_modules)
            
    except Exception as e:
        return False, f"Unexpected error: {{str(e)}}", False, []

if __name__ == "__main__":
    result = test_import()
    print(json.dumps(result))
'''
        
        try:
            # Run the test script in a subprocess
            result = subprocess.run(
                [sys.executable, '-c', test_script],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=os.path.dirname(file_path) if os.path.dirname(file_path) else '.'
            )
            
            if result.returncode == 0:
                try:
                    success, error_msg, is_circular, missing_deps = json.loads(result.stdout.strip())
                    return success, error_msg, is_circular, missing_deps
                except json.JSONDecodeError:
                    return False, f"Failed to parse subprocess output: {result.stdout}", False, []
            else:
                return False, f"Subprocess failed: {result.stderr}", False, []
                
        except subprocess.TimeoutExpired:
            return False, f"Import timeout after {self.timeout} seconds", False, []
        except Exception as e:
            return False, f"Subprocess error: {str(e)}", False, []


class ComprehensiveImportChecker:
    """Main checker class that combines syntax and import checking."""
    
    def __init__(self, 
                 timeout: int = 15,
                 exclude_patterns: Optional[List[str]] = None,
                 max_workers: int = 4,
                 verbose: bool = False):
        self.timeout = timeout
        self.exclude_patterns = exclude_patterns or []
        self.max_workers = max_workers
        self.verbose = verbose
        
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
            '*.egg-info',
            '.tox',
            'node_modules'
        ]
        
        # Setup logging
        logging.basicConfig(
            level=logging.DEBUG if verbose else logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        # Import checker
        self.import_checker = IsolatedImportChecker(timeout, verbose)
        
    def should_exclude(self, file_path: str) -> Tuple[bool, Optional[str]]:
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
    
    def check_syntax(self, file_path: str) -> Tuple[bool, Optional[str]]:
        """Check if a Python file has valid syntax."""
        try:
            with open(file_path, 'rb') as f:
                source = f.read()
            
            # Try to compile the source
            compile(source, file_path, 'exec')
            return True, None
            
        except SyntaxError as e:
            return False, f"Syntax error at line {e.lineno}: {e.msg}"
        except UnicodeDecodeError as e:
            return False, f"Unicode decode error: {str(e)}"
        except Exception as e:
            return False, f"Compilation error: {str(e)}"
    
    def check_file(self, file_path: str, 
                   check_syntax: bool = True,
                   check_imports: bool = True) -> CheckResult:
        """Check a single Python file for both syntax and import errors."""
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
            # Generate a unique module name to avoid conflicts
            module_name = f"test_module_{int(time.time() * 1000000)}"
            
            import_ok, import_error, is_circular, missing_deps = self.import_checker.check_import_in_subprocess(
                file_path, module_name
            )
            
            result.import_ok = import_ok
            result.import_error = import_error
            result.circular_import = is_circular
            result.missing_dependencies = missing_deps
            
            if import_error and "timeout" in import_error.lower():
                result.import_timeout = True
        
        result.check_time = time.time() - start_time
        return result
    
    def find_python_files(self, path: str, recursive: bool = True) -> List[str]:
        """Find all Python files in a directory or return single file."""
        if os.path.isfile(path):
            if path.endswith('.py'):
                return [path]
            else:
                return []
        
        python_files = []
        
        if recursive:
            for root, dirs, files in os.walk(path):
                # Filter out excluded directories
                dirs[:] = [d for d in dirs if not any(pattern in d for pattern in self.default_excludes)]
                
                for file in files:
                    if file.endswith('.py'):
                        file_path = os.path.join(root, file)
                        python_files.append(file_path)
        else:
            for file in os.listdir(path):
                if file.endswith('.py'):
                    file_path = os.path.join(path, file)
                    if os.path.isfile(file_path):
                        python_files.append(file_path)
        
        return sorted(python_files)
    
    def check_directory(self, path: str, 
                       recursive: bool = True,
                       check_syntax: bool = True,
                       check_imports: bool = True) -> List[CheckResult]:
        """Check all Python files in a directory or single file."""
        python_files = self.find_python_files(path, recursive)
        
        if not python_files:
            self.logger.warning(f"No Python files found in {path}")
            return []
        
        results = []
        
        self.logger.info(f"Found {len(python_files)} Python files to check")
        self.logger.info(f"Checking syntax: {check_syntax}")
        self.logger.info(f"Checking imports: {check_imports}")
        self.logger.info(f"Timeout: {self.timeout} seconds")
        self.logger.info(f"Max workers: {self.max_workers}")
        
        if self.verbose:
            print("-" * 80)
        
        # Use ThreadPoolExecutor for parallel processing
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_file = {
                executor.submit(self.check_file, file_path, check_syntax, check_imports): file_path
                for file_path in python_files
            }
            
            # Collect results
            for i, future in enumerate(as_completed(future_to_file)):
                file_path = future_to_file[future]
                try:
                    result = future.result()
                    results.append(result)
                    
                    if self.verbose:
                        progress = f"[{i+1}/{len(python_files)}]"
                        print(f"{progress} {file_path}")
                        
                        if result.skipped:
                            print(f"  SKIPPED: {result.skip_reason}")
                        else:
                            status_parts = []
                            if check_syntax:
                                status_parts.append(f"Syntax: {'✓' if result.syntax_ok else '✗'}")
                            if check_imports:
                                status_parts.append(f"Import: {'✓' if result.import_ok else '✗'}")
                            
                            print(f"  {' | '.join(status_parts)} ({result.check_time:.2f}s)")
                            
                            if not result.syntax_ok and result.syntax_error:
                                print(f"    Syntax Error: {result.syntax_error}")
                            if not result.import_ok and result.import_error:
                                print(f"    Import Error: {result.import_error}")
                                if result.circular_import:
                                    print(f"    ⚠️  Circular import detected!")
                                if result.missing_dependencies:
                                    print(f"    Missing dependencies: {', '.join(result.missing_dependencies)}")
                
                except Exception as e:
                    self.logger.error(f"Error checking {file_path}: {str(e)}")
                    results.append(CheckResult(
                        file_path=file_path,
                        syntax_ok=False,
                        import_ok=False,
                        syntax_error=f"Check failed: {str(e)}",
                        check_time=0.0
                    ))
        
        return results


def print_summary(results: List[CheckResult], 
                  check_syntax: bool = True,
                  check_imports: bool = True):
    """Print a comprehensive summary of the check results."""
    total_files = len(results)
    skipped_files = sum(1 for r in results if r.skipped)
    checked_files = total_files - skipped_files
    
    print(f"\n{'='*80}")
    print(f"COMPREHENSIVE IMPORT CHECK SUMMARY")
    print(f"{'='*80}")
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
            circular_imports = sum(1 for r in results if not r.skipped and r.circular_import)
            timeouts = sum(1 for r in results if not r.skipped and r.import_timeout)
            
            print(f"Import OK: {import_ok}/{checked_files} ({import_ok/checked_files*100:.1f}%)")
            print(f"Import errors: {import_errors}")
            print(f"Circular imports: {circular_imports}")
            print(f"Import timeouts: {timeouts}")
    
    # Show detailed error breakdown
    error_files = [r for r in results if not r.skipped and (not r.syntax_ok or not r.import_ok)]
    
    if error_files:
        print(f"\nFILES WITH ERRORS ({len(error_files)}):")
        print("-" * 80)
        
        # Group by error type
        syntax_errors = [r for r in error_files if not r.syntax_ok]
        import_errors = [r for r in error_files if not r.import_ok]
        circular_imports = [r for r in error_files if r.circular_import]
        
        if syntax_errors:
            print(f"\nSYNTAX ERRORS ({len(syntax_errors)}):")
            for result in syntax_errors:
                print(f"  ✗ {result.file_path}")
                print(f"    Error: {result.syntax_error}")
        
        if import_errors:
            print(f"\nIMPORT ERRORS ({len(import_errors)}):")
            for result in import_errors:
                print(f"  ✗ {result.file_path}")
                print(f"    Error: {result.import_error}")
                if result.missing_dependencies:
                    print(f"    Missing: {', '.join(result.missing_dependencies)}")
        
        if circular_imports:
            print(f"\nCIRCULAR IMPORTS ({len(circular_imports)}):")
            for result in circular_imports:
                print(f"  🔄 {result.file_path}")
                print(f"    Error: {result.import_error}")
    
    # Show most common missing dependencies
    all_missing = []
    for result in results:
        if result.missing_dependencies:
            all_missing.extend(result.missing_dependencies)
    
    if all_missing:
        from collections import Counter
        common_missing = Counter(all_missing).most_common(10)
        print(f"\nMOST COMMON MISSING DEPENDENCIES:")
        for dep, count in common_missing:
            print(f"  {dep}: {count} files")


def save_results(results: List[CheckResult], output_path: str):
    """Save results to a JSON file."""
    data = {
        "timestamp": time.time(),
        "total_files": len(results),
        "results": [asdict(r) for r in results]
    }
    
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"\nResults saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Comprehensive Python import checker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s /path/to/project                    # Check all .py files recursively
  %(prog)s single_file.py                      # Check a single file
  %(prog)s . --exclude "*test*" "__pycache__"  # Exclude test files and cache
  %(prog)s . --syntax-only                     # Only check syntax
  %(prog)s . --imports-only                    # Only check imports
  %(prog)s . --timeout 30                      # Set import timeout to 30 seconds
  %(prog)s . --max-workers 8                   # Use 8 parallel workers
  %(prog)s . --output results.json             # Save results to JSON file
        """
    )
    
    parser.add_argument(
        'path',
        nargs='?',
        default='.',
        help='Directory or file to check (default: current directory)'
    )
    
    parser.add_argument(
        '-r', '--recursive',
        action='store_true',
        default=True,
        help='Search recursively through subdirectories (default: True)'
    )
    
    parser.add_argument(
        '--no-recursive',
        action='store_true',
        help='Do not search recursively'
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
        '--syntax-only',
        action='store_true',
        help='Only check syntax (compilation)'
    )
    
    parser.add_argument(
        '--imports-only',
        action='store_true',
        help='Only check imports'
    )
    
    parser.add_argument(
        '--timeout',
        type=int,
        default=15,
        help='Timeout for import checks in seconds (default: 15)'
    )
    
    parser.add_argument(
        '--max-workers',
        type=int,
        default=4,
        help='Maximum number of parallel workers (default: 4)'
    )
    
    args = parser.parse_args()
    
    # Handle recursive flag
    recursive = args.recursive and not args.no_recursive
    
    # Determine what to check
    if args.syntax_only and args.imports_only:
        print("Error: Cannot specify both --syntax-only and --imports-only")
        sys.exit(1)
    
    check_syntax = not args.imports_only
    check_imports = not args.syntax_only
    
    # Validate path
    if not os.path.exists(args.path):
        print(f"Error: Path '{args.path}' does not exist")
        sys.exit(1)
    
    # Create checker
    checker = ComprehensiveImportChecker(
        timeout=args.timeout,
        exclude_patterns=args.exclude,
        max_workers=args.max_workers,
        verbose=args.verbose and not args.summary_only
    )
    
    # Run checks
    try:
        results = checker.check_directory(
            path=args.path,
            recursive=recursive,
            check_syntax=check_syntax,
            check_imports=check_imports
        )
        
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
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
