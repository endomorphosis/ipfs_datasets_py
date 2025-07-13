#!/usr/bin/env python3
"""
Class Extractor Script

This script extracts individual classes from a Python file and saves each class
to a separate file named after the class.

Usage:
    python class_extractor.py input_file.py [output_directory]
"""

import ast
import os
import sys
from typing import List, Dict, Optional, Tuple
import argparse
from pathlib import Path


class ClassExtractor:
    """
    Extracts classes from Python source files and saves them to separate files.
    
    This class uses Python's AST (Abstract Syntax Tree) module to parse source code,
    identify class definitions, and extract them along with their dependencies.
    """
    
    def __init__(self, input_file: str, output_dir: Optional[str] = None):
        """
        Initialize the ClassExtractor.
        
        Args:
            input_file (str): Path to the input Python file
            output_dir (Optional[str]): Directory to save extracted classes.
                                      Defaults to same directory as input file.
        
        Raises:
            FileNotFoundError: If input_file does not exist
            ValueError: If input_file is not a Python file
        """
        if not input_file or input_file.strip() == "":
            raise ValueError("invalid file path")
        
        if os.path.isdir(input_file):
            raise ValueError("expected file, not directory")
        
        if not os.path.exists(input_file):
            raise FileNotFoundError(f"File not found: {input_file}")
        
        if not input_file.endswith('.py'):
            raise ValueError("not a Python file")
        
        self.input_file = os.path.abspath(input_file)
        
        if output_dir is None:
            self.output_dir = os.path.dirname(self.input_file)
        else:
            self.output_dir = output_dir

    def extract_classes(self) -> Dict[str, Path]:
        """
        Extract all classes from the input file and save them to separate files.
        
        Returns:
            Dict[str, Path]: Dictionary mapping class names to their file paths
            
        Raises:
            ValueError: If no classes found in the input file
        """
        # Read and parse the file
        with open(self.input_file, 'r', encoding='utf-8') as f:
            source_code = f.read()
        
        try:
            tree = ast.parse(source_code)
        except SyntaxError as e:
            raise SyntaxError(f"Syntax error in {self.input_file}: {e}")
        
        # Find all classes
        classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Only get top-level classes (not nested)
                if self._is_top_level_class(node, tree):
                    classes.append(node)
        
        if not classes:
            raise ValueError("no classes found")
        
        # Ensure output directory exists
        os.makedirs(self.output_dir, exist_ok=True)
        
        result = {}
        
        for class_node in classes:
            class_name = class_node.name
            extracted_code = self._extract_class_with_dependencies(class_node, tree, source_code)
            
            # Write to file
            output_file = Path(self.output_dir) / f"{class_name}.py"
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(extracted_code)
            
            result[class_name] = output_file
        
        return result
    
    def _is_top_level_class(self, class_node: ast.ClassDef, tree: ast.AST) -> bool:
        """Check if a class is a top-level class (not nested inside another class)."""
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node != class_node:
                for child in ast.walk(node):
                    if child == class_node:
                        return False
        return True
    
    def _extract_class_with_dependencies(self, class_node: ast.ClassDef, tree: ast.AST, source_code: str) -> str:
        """Extract a class along with its dependencies."""
        lines = source_code.split('\n')
        
        # Get all top-level nodes
        top_level_nodes = tree.body
        
        # Collect imports
        imports = []
        for node in top_level_nodes:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.append(self._get_node_source(node, lines))
        
        # Collect constants and functions that might be dependencies
        dependencies = []
        class_names_in_file = {n.name for n in top_level_nodes if isinstance(n, ast.ClassDef)}
        
        for node in top_level_nodes:
            if isinstance(node, ast.FunctionDef):
                dependencies.append(self._get_node_source(node, lines))
            elif isinstance(node, ast.Assign):
                # Global constants
                dependencies.append(self._get_node_source(node, lines))
            elif isinstance(node, ast.ClassDef) and node != class_node:
                # Check if this class is a base class
                if self._is_base_class(node.name, class_node):
                    dependencies.append(self._get_node_source(node, lines))
        
        # Get the main class
        class_source = self._get_node_source(class_node, lines)
        
        # Combine everything
        parts = []
        
        if imports:
            parts.extend(imports)
            parts.append("")  # Empty line after imports
        
        if dependencies:
            parts.extend(dependencies)
            parts.append("")  # Empty line before class
        
        parts.append(class_source)
        
        return '\n'.join(parts)
    
    def _is_base_class(self, potential_base: str, class_node: ast.ClassDef) -> bool:
        """Check if a class is a base class of the given class node."""
        for base in class_node.bases:
            if isinstance(base, ast.Name) and base.id == potential_base:
                return True
        return False
    
    def _get_node_source(self, node: ast.AST, lines: List[str]) -> str:
        """Extract the source code for a given AST node."""
        start_line = node.lineno - 1  # AST line numbers are 1-based
        
        if hasattr(node, 'end_lineno') and node.end_lineno:
            end_line = node.end_lineno
        else:
            # For older Python versions or nodes without end_lineno
            end_line = self._find_node_end(node, lines, start_line)
        
        # Handle decorators
        if hasattr(node, 'decorator_list') and node.decorator_list:
            first_decorator = node.decorator_list[0]
            start_line = first_decorator.lineno - 1
        
        return '\n'.join(lines[start_line:end_line])
    
    def _find_node_end(self, node: ast.AST, lines: List[str], start_line: int) -> int:
        """Find the end line of a node by looking at indentation."""
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            # For classes and functions, find where indentation returns to base level
            base_indent = len(lines[start_line]) - len(lines[start_line].lstrip())
            
            for i in range(start_line + 1, len(lines)):
                line = lines[i]
                if line.strip() == "":  # Skip empty lines
                    continue
                
                current_indent = len(line) - len(line.lstrip())
                if current_indent <= base_indent:
                    return i
            
            return len(lines)
        else:
            # For simple statements, usually just one line
            return start_line + 1


def main():
    """
    Main function to run the class extractor from command line.
    """
    parser = argparse.ArgumentParser(
        description="Extract classes from a Python file into separate files"
    )
    parser.add_argument(
        "input_file", 
        help="Path to the input Python file"
    )
    parser.add_argument(
        "-o", "--output-dir", 
        help="Output directory for extracted class files (default: same as input file)"
    )
    parser.add_argument(
        "-v", "--verbose", 
        action="store_true", 
        help="Enable verbose output"
    )
    
    args = parser.parse_args()
    
    try:
        extractor = ClassExtractor(args.input_file, args.output_dir)
        created_files = extractor.extract_classes()
        
        if args.verbose:
            print(f"Successfully extracted {len(created_files)} classes from {args.input_file}")
            for class_name, filepath in created_files.items():
                print(f"  {class_name} -> {filepath}")
        else:
            print(f"Extracted {len(created_files)} classes to {extractor.output_dir}")
            
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
