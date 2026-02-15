import asyncio
import ast
import os
from typing import Dict, List, Set, Optional
from dataclasses import dataclass



@dataclass
class FunctionAnalysis:
    name: str
    file_path: str
    parameters: List[str]
    return_type_hints: Optional[str]
    calls_external_functions: bool
    has_loops: bool
    has_recursion: bool
    has_async: bool
    has_api_calls: bool
    complexity_warnings: List[str]
    imported_modules: Set[str]

class FunctionAnalyzer(ast.NodeVisitor):
    def __init__(self):
        self.current_function = None
        self.function_calls = set()
        self.has_loops = False
        self.imported_modules = set()
        self.complexity_warnings = []

    def visit_FunctionDef(self, node):
        self.current_function = node.name
        # Check for recursion
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if hasattr(child.func, 'id') and child.func.id == node.name:
                    self.complexity_warnings.append("Contains recursive calls")
        
        # Visit all child nodes
        self.generic_visit(node)
        
    def visit_Import(self, node):
        for alias in node.names:
            self.imported_modules.add(alias.name)
            
    def visit_ImportFrom(self, node):
        if node.module:
            self.imported_modules.add(node.module)
            
    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            self.function_calls.add(node.func.id)

    def visit_For(self, node):
        self.has_loops = True
        self.generic_visit(node)
        
    def visit_While(self, node):
        self.has_loops = True
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self.has_async = True
        self.generic_visit(node)


def analyze_file(file_path: str) -> List[FunctionAnalysis]:
    """
    Analyzes all functions in a Python file without executing them.
    
    Args:
        file_path: Path to the Python file to analyze
        
    Returns:
        List of FunctionAnalysis objects containing static analysis results
    """
    with open(file_path, 'r') as file:
        content = file.read()
    
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        print(f"Syntax error in {file_path}: {e}")
        return []
    
    analyses = []
    
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            analyzer = FunctionAnalyzer()
            analyzer.visit(node)
            
            # Get parameter names
            params = [arg.arg for arg in node.args.args]
            
            # Get return type hints if they exist
            return_type_hint = None
            if node.returns:
                return_type_hint = ast.unparse(node.returns)
            
            # Check for potentially expensive operations
            if analyzer.has_loops:
                analyzer.complexity_warnings.append("Contains loops")
            if len(analyzer.function_calls) > 5:
                analyzer.complexity_warnings.append("High number of function calls")
            
            analysis = FunctionAnalysis(
                name=node.name,
                file_path=file_path,
                parameters=params,
                return_type_hints=return_type_hint,
                calls_external_functions=bool(analyzer.function_calls - {node.name}),
                has_loops=analyzer.has_loops,
                has_recursion="Contains recursive calls" in analyzer.complexity_warnings,
                complexity_warnings=analyzer.complexity_warnings,
                imported_modules=analyzer.imported_modules
            )
            analyses.append(analysis)
    
    return analyses