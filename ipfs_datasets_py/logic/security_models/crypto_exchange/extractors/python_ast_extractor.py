"""Python AST extractor for seed security models."""

from __future__ import annotations

import ast
from typing import Any


class PythonASTExtractor:
    """Extract lightweight symbol metadata from Python source."""

    def extract_from_source(self, source: str) -> dict[str, Any]:
        tree = ast.parse(source)
        return {
            'functions': sorted(node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)),
            'classes': sorted(node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)),
        }
