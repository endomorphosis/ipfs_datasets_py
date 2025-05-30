#!/usr/bin/env python3
"""
IPFS Datasets Linting Helper

This script assists in fixing common dataset-specific linting issues:
- DS001: Missing error handling for dataset operations
- DS002: Hardcoded IPFS hashes that should be in config
"""

import sys
import os
import re
import argparse
from pathlib import Path
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ds-lint-helper")

# Patterns for dataset operations
DATASET_OPERATIONS = [
    r'\.load_dataset\(',
    r'\.save_dataset\(',
    r'\.process_dataset\(',
    r'\.pin_to_ipfs\(',
    r'\.get_from_ipfs\(',
]

# Pattern for IPFS hashes
IPFS_HASH_PATTERN = r'(Qm[A-Za-z0-9]{44}|baf[A-Za-z0-9]+)'


def find_missing_error_handling(file_path):
    """Identify dataset operations without error handling."""
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    issues = []
    for i, line in enumerate(lines):
        line_number = i + 1
        for pattern in DATASET_OPERATIONS:
            if re.search(pattern, line):
                # Check nearby lines for error handling
                if not has_error_handling_nearby(lines, i):
                    issues.append({
                        'line': line_number,
                        'content': line.strip(),
                        'issue': 'DS001',
                        'message': 'Dataset operation without error handling'
                    })
    
    return issues


def has_error_handling_nearby(lines, line_index):
    """Check if error handling exists near the given line."""
    # Look for try/except blocks within a reasonable range
    start = max(0, line_index - 5)
    end = min(len(lines), line_index + 5)
    
    for i in range(start, end):
        if 'try:' in lines[i] or 'except' in lines[i]:
            return True
    
    return False


def find_hardcoded_hashes(file_path):
    """Identify hardcoded IPFS hashes."""
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    issues = []
    for i, line in enumerate(lines):
        line_number = i + 1
        hashes = re.findall(IPFS_HASH_PATTERN, line)
        if hashes:
            issues.append({
                'line': line_number,
                'content': line.strip(),
                'issue': 'DS002',
                'message': f'Hardcoded IPFS hash found: {hashes[0]}...',
                'hashes': hashes
            })
    
    return issues


def suggest_fix_for_DS001(issue, file_path):
    """Suggest a fix for DS001 (missing error handling)."""
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    line_idx = issue['line'] - 1
    indent = re.match(r'^(\s*)', lines[line_idx]).group(1)
    
    # Simple fix: wrap in try/except
    fix_lines = [
        f"{indent}try:\n",
        f"{indent}    {lines[line_idx].lstrip()}", 
        f"{indent}except Exception as e:\n",
        f"{indent}    logger.error(f\"Dataset operation failed: {{e}}\")\n",
        f"{indent}    # Handle error appropriately\n"
    ]
    
    return ''.join(fix_lines)


def suggest_fix_for_DS002(issue, file_path):
    """Suggest a fix for DS002 (hardcoded IPFS hash)."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    line = issue['content']
    hash_val = issue['hashes'][0]
    
    # Check if imports are needed
    config_import = "from ipfs_datasets_py.config import get_config"
    if config_import not in content:
        fix = f"# Add to imports:\n{config_import}\n\n"
    else:
        fix = ""
    
    fix += f"# Before:\n{line}\n\n# After:\n"
    
    # Generate config-based replacement
    var_name = f"IPFS_HASH_{hash_val[:6]}"
    config_var = f"config.datasets.{var_name.lower()}"
    fix += f"# Add to configuration:\n{var_name} = \"{hash_val}\"\n\n"
    fix += f"# In the code:\nconfig = get_config()\n{line.replace(hash_val, config_var)}\n"
    
    return fix


def process_file(file_path, fix=False, show_suggestions=True):
    """Process a file for dataset linting issues."""
    ds001_issues = find_missing_error_handling(file_path)
    ds002_issues = find_hardcoded_hashes(file_path)
    
    if not ds001_issues and not ds002_issues:
        logger.info(f"No issues found in {file_path}")
        return 0
    
    logger.info(f"Found {len(ds001_issues)} DS001 and {len(ds002_issues)} DS002 issues in {file_path}")
    
    # Display and fix issues
    if ds001_issues and show_suggestions:
        logger.info("DS001 issues (missing error handling):")
        for i, issue in enumerate(ds001_issues):
            logger.info(f"  {i+1}. Line {issue['line']}: {issue['content']}")
            if show_suggestions:
                suggestion = suggest_fix_for_DS001(issue, file_path)
                logger.info(f"     Suggested fix:\n{suggestion}")
    
    if ds002_issues and show_suggestions:
        logger.info("DS002 issues (hardcoded IPFS hashes):")
        for i, issue in enumerate(ds002_issues):
            logger.info(f"  {i+1}. Line {issue['line']}: {issue['content']}")
            if show_suggestions:
                suggestion = suggest_fix_for_DS002(issue, file_path)
                logger.info(f"     Suggested fix:\n{suggestion}")
    
    return len(ds001_issues) + len(ds002_issues)


def process_directory(dir_path, exclude_dirs=None, fix=False, show_suggestions=True):
    """Process all Python files in a directory."""
    if exclude_dirs is None:
        exclude_dirs = ['.git', '__pycache__', '.venv', 'node_modules']
    
    total_issues = 0
    for root, dirs, files in os.walk(dir_path):
        # Skip excluded directories
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                issues = process_file(file_path, fix, show_suggestions)
                total_issues += issues
    
    return total_issues


def main():
    """Main entrypoint."""
    parser = argparse.ArgumentParser(description="Fix dataset-specific linting issues")
    parser.add_argument("path", help="File or directory to process")
    parser.add_argument("--fix", action="store_true", help="Apply fixes (not yet implemented)")
    parser.add_argument("--no-suggestions", action="store_true", help="Don't show fix suggestions")
    
    args = parser.parse_args()
    path = Path(args.path).resolve()
    
    if not path.exists():
        logger.error(f"Path does not exist: {path}")
        return 1
    
    logger.info(f"Processing {path}")
    
    if path.is_file():
        if not path.name.endswith('.py'):
            logger.error("Can only process Python (.py) files")
            return 1
        issues = process_file(path, args.fix, not args.no_suggestions)
    else:
        issues = process_directory(path, fix=args.fix, show_suggestions=not args.no_suggestions)
    
    logger.info(f"Found {issues} total dataset linting issues")
    return 0


if __name__ == "__main__":
    sys.exit(main())
