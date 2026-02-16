"""
Architecture validation tests for processors.

Ensures the 5-layer architecture boundaries are maintained:
1. CORE - depends on nothing
2. INFRASTRUCTURE - depends only on CORE
3. ADAPTERS - depends on CORE + SPECIALIZED
4. SPECIALIZED - depends on CORE + INFRASTRUCTURE
5. DOMAINS - depends on CORE + SPECIALIZED + INFRASTRUCTURE
"""

import ast
from pathlib import Path
import pytest


def get_imports(file_path: Path) -> set[str]:
    """
    Extract all imports from a Python file.
    
    Args:
        file_path: Path to Python file
        
    Returns:
        Set of module names imported
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        tree = ast.parse(content)
    except (SyntaxError, FileNotFoundError):
        return set()
    
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    
    return imports


def get_processor_files(layer: str) -> list[Path]:
    """
    Get all Python files in a processor layer.
    
    Args:
        layer: Layer name (core, infrastructure, adapters, specialized, domains)
        
    Returns:
        List of Python file paths
    """
    base_path = Path("ipfs_datasets_py/processors")
    layer_path = base_path / layer
    
    if not layer_path.exists():
        return []
    
    files = []
    for py_file in layer_path.rglob("*.py"):
        # Skip __init__.py and test files
        if py_file.name == "__init__.py" or "test" in py_file.name:
            continue
        files.append(py_file)
    
    return files


def check_forbidden_imports(file_path: Path, forbidden_layers: list[str]) -> list[str]:
    """
    Check if file imports from forbidden layers.
    
    Args:
        file_path: Path to Python file
        forbidden_layers: List of forbidden layer names
        
    Returns:
        List of violations (import statements that violate rules)
    """
    imports = get_imports(file_path)
    violations = []
    
    for imp in imports:
        for forbidden_layer in forbidden_layers:
            # Check if import contains forbidden layer path
            if f".processors.{forbidden_layer}." in imp or f".processors.{forbidden_layer}" in imp:
                violations.append(f"Imports from {forbidden_layer}: {imp}")
    
    return violations


@pytest.mark.architecture
def test_core_no_internal_dependencies():
    """
    Core layer should not import from any other internal layers.
    
    RULE: CORE depends on nothing (only stdlib, anyio, typing, external libs)
    """
    core_files = get_processor_files("core")
    forbidden_layers = ["adapters", "specialized", "domains", "infrastructure"]
    
    violations = {}
    for py_file in core_files:
        file_violations = check_forbidden_imports(py_file, forbidden_layers)
        if file_violations:
            violations[py_file.name] = file_violations
    
    if violations:
        msg = "\n".join([
            f"{file}: {', '.join(viols)}"
            for file, viols in violations.items()
        ])
        pytest.fail(
            f"Core layer has forbidden imports:\n{msg}\n\n"
            "RULE: Core should only import stdlib, anyio, typing, and external libraries."
        )


@pytest.mark.architecture
def test_infrastructure_only_depends_on_core():
    """
    Infrastructure layer should only import from core.
    
    RULE: INFRASTRUCTURE depends only on CORE
    """
    infra_files = get_processor_files("infrastructure")
    forbidden_layers = ["adapters", "specialized", "domains"]
    
    violations = {}
    for py_file in infra_files:
        file_violations = check_forbidden_imports(py_file, forbidden_layers)
        if file_violations:
            violations[py_file.name] = file_violations
    
    if violations:
        msg = "\n".join([
            f"{file}: {', '.join(viols)}"
            for file, viols in violations.items()
        ])
        pytest.fail(
            f"Infrastructure layer has forbidden imports:\n{msg}\n\n"
            "RULE: Infrastructure should only import from core layer."
        )


@pytest.mark.architecture  
def test_adapters_only_depend_on_core_and_specialized():
    """
    Adapters layer should only import from core and specialized.
    
    RULE: ADAPTERS depend on CORE + SPECIALIZED
    """
    adapter_files = get_processor_files("adapters")
    forbidden_layers = ["domains"]  # Can use specialized but not domains
    
    violations = {}
    for py_file in adapter_files:
        file_violations = check_forbidden_imports(py_file, forbidden_layers)
        if file_violations:
            violations[py_file.name] = file_violations
    
    if violations:
        msg = "\n".join([
            f"{file}: {', '.join(viols)}"
            for file, viols in violations.items()
        ])
        pytest.fail(
            f"Adapters layer has forbidden imports:\n{msg}\n\n"
            "RULE: Adapters should only import from core and specialized layers."
        )


@pytest.mark.architecture
def test_architecture_layers_exist():
    """
    Verify all 5 architecture layers exist.
    """
    base_path = Path("ipfs_datasets_py/processors")
    
    required_layers = ["core", "infrastructure", "adapters", "specialized", "domains"]
    
    for layer in required_layers:
        layer_path = base_path / layer
        assert layer_path.exists(), f"Layer '{layer}' does not exist at {layer_path}"
        assert layer_path.is_dir(), f"Layer '{layer}' is not a directory"


if __name__ == "__main__":
    # Allow running tests directly
    pytest.main([__file__, "-v", "-m", "architecture"])
