#!/usr/bin/env python3
"""
Class Extractor Script

This script extracts individual classes from a Python file and saves each class
to a separate file named after the class.

Usage:
    python class_extractor.py input_file.py [output_directory]

Author: Generated Script
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
        self.input_file = Path(input_file)
        if not self.input_file.exists():
            raise FileNotFoundError(f"Input file not found: {input_file}")
        
        if self.input_file.suffix != '.py':
            raise ValueError(f"Input file must be a Python file (.py): {input_file}")
        
        self.output_dir = Path(output_dir) if output_dir else self.input_file.parent
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Store the parsed AST and source lines
        self.tree: Optional[ast.AST] = None
        self.source_lines: List[str] = []
        
    def _read_source_file(self) -> str:
        """
        Read the source file and return its contents.
        
        Returns:
            str: Contents of the source file
            
        Raises:
            IOError: If file cannot be read
        """
        try:
            with open(self.input_file, 'r', encoding='utf-8') as f:
                content = f.read()
                self.source_lines = content.splitlines()
                return content
        except IOError as e:
            raise IOError(f"Cannot read file {self.input_file}: {e}")
    
    def _parse_ast(self, source_code: str) -> ast.AST:
        """
        Parse the source code into an AST.
        
        Args:
            source_code (str): Python source code
            
        Returns:
            ast.AST: Parsed abstract syntax tree
            
        Raises:
            SyntaxError: If source code has syntax errors
        """
        try:
            return ast.parse(source_code, filename=str(self.input_file))
        except SyntaxError as e:
            raise SyntaxError(f"Syntax error in {self.input_file}: {e}")
    
    def _extract_imports(self) -> List[str]:
        """
        Extract all import statements from the source file.
        
        Returns:
            List[str]: List of import statement strings
        """
        imports = []
        
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                import_line = f"import {', '.join(alias.name for alias in node.names)}"
                imports.append(import_line)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                names = ', '.join(alias.name for alias in node.names)
                level = '.' * node.level if node.level else ''
                import_line = f"from {level}{module} import {names}"
                imports.append(import_line)
        
        return imports
    
    def _get_class_source(self, class_node: ast.ClassDef) -> str:
        """
        Extract the source code for a specific class.
        
        Args:
            class_node (ast.ClassDef): AST node representing the class
            
        Returns:
            str: Source code of the class
        """
        # Get line numbers (AST uses 1-based indexing)
        start_line = class_node.lineno - 1
        end_line = class_node.end_lineno if class_node.end_lineno else start_line + 1
        
        # Extract the class source lines
        class_lines = self.source_lines[start_line:end_line]
        
        return '\n'.join(class_lines)
    
    def _find_classes(self) -> List[ast.ClassDef]:
        """
        Find all class definitions in the AST.
        
        Returns:
            List[ast.ClassDef]: List of class definition nodes
        """
        classes = []
        
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef):
                # Only get top-level classes (not nested classes)
                # Check if the class is at module level
                for parent in ast.walk(self.tree):
                    if hasattr(parent, 'body') and node in parent.body:
                        if isinstance(parent, ast.Module):
                            classes.append(node)
                        break
        
        return classes
    
    def _create_class_file(self, class_node: ast.ClassDef, imports: List[str]) -> str:
        """
        Create the content for a class file.
        
        Args:
            class_node (ast.ClassDef): The class to extract
            imports (List[str]): Import statements to include
            
        Returns:
            str: Complete file content for the class
        """
        # File header
        header = f'"""\n{class_node.name} class extracted from {self.input_file.name}\n"""\n\n'
        
        # Imports
        imports_section = '\n'.join(imports) + '\n\n' if imports else ''
        
        # Class source
        class_source = self._get_class_source(class_node)
        
        return header + imports_section + class_source
    
    def _write_class_file(self, class_name: str, content: str) -> Path:
        """
        Write class content to a file.
        
        Args:
            class_name (str): Name of the class
            content (str): File content
            
        Returns:
            Path: Path to the created file
            
        Raises:
            IOError: If file cannot be written
        """
        filename = f"{class_name}.py"
        filepath = self.output_dir / filename
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            return filepath
        except IOError as e:
            raise IOError(f"Cannot write file {filepath}: {e}")
    
    def extract_classes(self) -> Dict[str, Path]:
        """
        Extract all classes from the input file and save them to separate files.
        
        Returns:
            Dict[str, Path]: Dictionary mapping class names to their file paths
            
        Raises:
            ValueError: If no classes found in the input file
        """
        # Read and parse the source file
        source_code = self._read_source_file()
        self.tree = self._parse_ast(source_code)
        
        # Extract imports and classes
        imports = self._extract_imports()
        classes = self._find_classes()
        
        if not classes:
            raise ValueError(f"No classes found in {self.input_file}")
        
        # Create files for each class
        created_files = {}
        
        for class_node in classes:
            class_name = class_node.name
            content = self._create_class_file(class_node, imports)
            filepath = self._write_class_file(class_name, content)
            created_files[class_name] = filepath
        
        return created_files


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