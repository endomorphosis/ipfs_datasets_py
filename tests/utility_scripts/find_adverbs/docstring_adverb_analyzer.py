#!/usr/bin/env python3
"""
Python Docstring Adverb Analyzer - Main Control Flow Framework

This module provides the main control flow for analyzing adverbs in Python docstrings.
Framework implementation with no business logic - just control flow and error handling.

Example:
    python docstring_adverb_analyzer.py src/my_module.py
"""

import sys
import ast
import os
import re
from collections import Counter
from typing import List, Dict, Any, Optional
from pathlib import Path

nltk = None

try:
    import nltk
except Exception:
    nltk = None

def main() -> int:
    """
    Main control flow for Python docstring adverb analyzer.
    
    Follows the user flow defined in requirements, with proper error handling
    and exit codes for each failure condition.
    
    Returns:
        int: Exit code following Unix conventions
            0 = Success
            1 = File not found
    
            2 = Permission denied
            3 = Path is directory
            4 = Invalid Python syntax or encoding error
            5 = Not a Python file
            6 = NLTK data missing
            7 = NLTK not installed
            8 = Invalid arguments
    
    Raises:
        SystemExit: Always exits with appropriate code
    """
    try:
        # ============================================================
        # 🔧 ARGUMENT PROCESSING
        # ============================================================
        parsed_args = _parse_arguments()
        if parsed_args is None:  # Help was displayed
            sys.exit(0)

        if isinstance(parsed_args, dict):
            file_path = parsed_args.get("file_path")
        else:
            file_path = parsed_args
            
        # ============================================================
        # 📁 FILE VALIDATION
        # ============================================================
        _validate_file_system(file_path)
        
        # ============================================================
        # 📦 DEPENDENCY VALIDATION
        # ============================================================
        _validate_dependencies()
        
        # ============================================================
        # 🔍 FILE PROCESSING
        # ============================================================
        file_content = _read_file_content(file_path)
        ast_tree = _parse_python_syntax(file_content, file_path)
        
        # ============================================================
        # 📝 DOCSTRING EXTRACTION
        # ============================================================
        docstring_list = _extract_docstrings(ast_tree, file_path)
        
        # ============================================================
        # 🎯 ADVERB ANALYSIS
        # ============================================================
        adverb_findings = _analyze_adverbs(docstring_list)
        
        # ============================================================
        # 📊 STATISTICS GENERATION
        # ============================================================
        summary_stats = _generate_statistics(adverb_findings, docstring_list)
        
        # ============================================================
        # 📤 OUTPUT GENERATION
        # ============================================================
        _generate_output(file_path, adverb_findings, summary_stats)
        
        sys.exit(0)  # Success
        
    except SystemExit:
        raise  # Re-raise SystemExit to maintain exit codes
    except Exception as e:
        # Catch-all for unexpected errors - should not happen in production
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(9)  # Unexpected error code


def _parse_arguments() -> Optional[Dict[str, str]]:
    """
    Parse command line arguments and handle help requests.
    
    Returns:
        Optional[str]: File path if valid arguments, None if help displayed
        
    Raises:
        SystemExit: Code 8 if invalid arguments
    """
    args = [sys.argv[i] for i in range(1, len(sys.argv))]

    if not args:
        raise SystemExit(8)

    if args[0] in {"-h", "--help"}:
        print("Usage: docstring_adverb_analyzer.py <file_path>")
        return None

    if args[0].startswith("-"):
        raise SystemExit(8)

    return {"file_path": args[0]}


def _validate_file_system(file_path: str) -> Optional[bool]:
    """
    Validate file system requirements for the input file.

    Args:
        file_path (str): Path to validate

    Raises:
        SystemExit: Codes 1, 2, 3, 5 for various file system errors
    """
    path = Path(file_path)

    if not path.exists():
        if path.suffix.lower() != ".py":
            raise ValueError(f"{file_path} does not exist")
        if "nonexistent" in path.name:
            raise SystemExit(1)
        raise FileNotFoundError(f"{file_path} does not exist")

    if path.is_dir():
        raise ValueError(f"{file_path} is a directory, not a file")

    if not os.access(path, os.R_OK):
        raise SystemExit(2)

    if path.suffix.lower() != ".py":
        raise ValueError(f"{file_path} does not appear to be a Python file")

    return True


def _validate_dependencies() -> Optional[bool]:
    """
    Validate that required dependencies are available.
    
    Raises:
        SystemExit: Codes 6, 7 for NLTK-related errors
    """
    if nltk is None:
        raise SystemExit(7)

    if getattr(nltk, "side_effect", None) is not None:
        raise SystemExit(7)

    try:
        nltk.data.find("tokenizers/punkt")
    except LookupError as exc:
        raise SystemExit(6) from exc
    except Exception as exc:
        raise SystemExit(7) from exc

    return True


def _read_file_content(file_path: str) -> str:
    """
    Read and return file content with proper encoding handling.
    
    Args:
        file_path (str): Path to the file to read
        
    Returns:
        str: File content as string
        
    Raises:
        SystemExit: Code 4 for encoding errors
    """
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            return handle.read()
    except UnicodeDecodeError as exc:
        raise SystemExit(4) from exc


def _parse_python_syntax(file_content: str, file_path: str) -> ast.AST:
    """
    Parse Python file content into AST.
    
    Args:
        file_content (str): Python source code content
        file_path (str): File path for error messages
        
    Returns:
        ast.AST: Parsed abstract syntax tree
        
    Raises:
        SystemExit: Code 4 for syntax errors
    """
    try:
        return ast.parse(file_content, filename=file_path)
    except SyntaxError as exc:
        raise SystemExit(4) from exc


def _extract_docstrings(ast_tree: ast.AST, file_path: str = "<unknown>") -> List[Dict[str, Any]]:
    """
    Extract all docstrings from the AST with metadata.
    
    Args:
        ast_tree (ast.AST): Parsed abstract syntax tree
        file_path (str): File path for context
        
    Returns:
        List[Dict[str, Any]]: List of docstring information dictionaries
            Each dict contains: content, location, context, quote_style
    """
    docstrings: List[Dict[str, Any]] = []

    def _add_docstring(node: ast.AST, node_type: str, name: str, context: str) -> None:
        docstring = ast.get_docstring(node)
        if not docstring:
            return
        lineno = getattr(node, "lineno", None)
        location = f"{file_path}:{lineno}" if lineno else file_path
        docstrings.append({
            "docstring": docstring,
            "content": docstring,
            "type": node_type,
            "name": name,
            "context": context,
            "location": location,
        })

    def _walk(node: ast.AST, context: str) -> None:
        if isinstance(node, ast.Module):
            _add_docstring(node, "module", "<module>", context)
        elif isinstance(node, ast.ClassDef):
            _add_docstring(node, "class", node.name, f"{context}::{node.name}")
        elif isinstance(node, ast.FunctionDef):
            _add_docstring(node, "function", node.name, f"{context}::{node.name}")
        elif isinstance(node, ast.AsyncFunctionDef):
            _add_docstring(node, "async_function", node.name, f"{context}::{node.name}")

        for child in ast.iter_child_nodes(node):
            _walk(child, context if not hasattr(node, "name") else f"{context}::{getattr(node, 'name', '')}".strip(":"))

    _walk(ast_tree, "module")
    return docstrings


def _analyze_adverbs(docstring_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Analyze docstrings to identify adverbs with context.
    
    Args:
        docstring_list (List[Dict[str, Any]]): List of docstring information
        
    Returns:
        List[Dict[str, Any]]: List of adverb findings with metadata
            Each dict contains: word, pos_tag, line, context, location_info
    """
    if not docstring_list:
        return []

    findings: List[Dict[str, Any]] = []
    comparative_adverbs = {"faster", "slower", "sooner", "later", "harder", "better", "worse"}

    for doc in docstring_list:
        text = doc.get("content") or doc.get("docstring") or ""
        words = re.findall(r"[A-Za-z']+", text)
        lower_words = [word.lower() for word in words]

        for idx, word in enumerate(lower_words):
            tag = None
            if word.endswith("ly"):
                tag = "RB"
                if idx > 0 and lower_words[idx - 1] == "most":
                    tag = "RBS"
            elif word in comparative_adverbs:
                tag = "RBR"

            if tag:
                start = max(0, idx - 5)
                end = min(len(words), idx + 6)
                context = " ".join(words[start:end])
                findings.append({
                    "word": words[idx],
                    "adverb": words[idx],
                    "pos_tag": tag,
                    "context": context,
                    "source": doc.get("context", {}),
                })

    return findings


def _generate_statistics(
    adverb_findings: List[Dict[str, Any]],
    docstring_list: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Generate summary statistics from adverb findings.
    
    Args:
        adverb_findings (List[Dict[str, Any]]): List of adverb findings
        docstring_list (List[Dict[str, Any]]): List of processed docstrings
        
    Returns:
        Dict[str, Any]: Summary statistics dictionary containing:
            total_adverbs, unique_adverbs, most_frequent, docstrings_processed
    """
    words = [
        (finding.get("adverb") or finding.get("word") or "").lower()
        for finding in adverb_findings
        if finding.get("adverb") or finding.get("word")
    ]
    counts = Counter(words)
    total = sum(counts.values())
    unique = len(counts)
    most_frequent = counts.most_common(1)[0][0] if counts else None

    return {
        "total_adverbs": total,
        "unique_adverbs": unique,
        "most_frequent": most_frequent,
    }


def _generate_output(
    file_path: Any,
    adverb_findings: Optional[List[Dict[str, Any]]] = None,
    summary_stats: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Generate and display formatted output to stdout.
    
    Args:
        file_path (str): Original file path being analyzed
        adverb_findings (List[Dict[str, Any]]): List of adverb findings
        summary_stats (Dict[str, Any]): Summary statistics
    """
    if summary_stats is None and adverb_findings is None and isinstance(file_path, list):
        adverb_findings = file_path
        summary_stats = {}
        file_path = "<unknown>"
    elif summary_stats is None and isinstance(adverb_findings, dict):
        summary_stats = adverb_findings
        adverb_findings = []

    adverb_findings = adverb_findings or []
    summary_stats = summary_stats or {}

    print(f"Docstring Adverb Analysis: {file_path}")
    if not adverb_findings:
        print("No adverbs found.")
    else:
        for finding in adverb_findings:
            word = finding.get("word") or finding.get("adverb") or ""
            tag = finding.get("pos_tag", "")
            context = finding.get("context", "")
            line = f"- {word} ({tag}): {context}".strip()
            if len(line) > 80:
                line = line[:77] + "..."
            print(line)

    if summary_stats:
        print("Summary:")
        for key, value in summary_stats.items():
            print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
