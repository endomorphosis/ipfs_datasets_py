"""
Dependency Chain Analyzer for Software Engineering Dashboard.

This module provides tools to analyze software dependency chains and detect issues.
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


def analyze_dependency_chain(
    dependencies: Dict[str, List[str]],
    detect_cycles: bool = True,
    calculate_depth: bool = True
) -> Dict[str, Any]:
    """
    Analyze dependency chains to detect cycles, calculate depths, and identify issues.
    
    Analyzes a dependency graph to find circular dependencies, calculate
    dependency depths, and identify potential issues in the dependency chain.
    
    Args:
        dependencies: Dictionary mapping package names to lists of their dependencies
            Example: {"packageA": ["packageB", "packageC"], "packageB": ["packageC"]}
        detect_cycles: Whether to detect circular dependencies
        calculate_depth: Whether to calculate dependency depths
        
    Returns:
        Dictionary containing dependency analysis with keys:
        - total_packages: Total number of packages
        - cycles: List of detected circular dependencies
        - max_depth: Maximum dependency depth
        - depth_distribution: Distribution of packages by depth
        - isolated_packages: Packages with no dependencies
        - most_depended_on: Packages that are most depended upon
        - analyzed_at: Timestamp of analysis
        
    Example:
        >>> deps = {"A": ["B"], "B": ["C"], "C": ["A"]}  # Circular dependency
        >>> result = analyze_dependency_chain(deps)
        >>> print(f"Found {len(result['cycles'])} cycles")
    """
    try:
        result = {
            "success": True,
            "total_packages": len(dependencies),
            "cycles": [],
            "max_depth": 0,
            "depth_distribution": {},
            "isolated_packages": [],
            "most_depended_on": [],
            "analyzed_at": datetime.utcnow().isoformat()
        }
        
        # Find isolated packages (no dependencies)
        for package, deps in dependencies.items():
            if not deps or len(deps) == 0:
                result["isolated_packages"].append(package)
        
        # Find most depended-on packages
        dependency_counts = {}
        for package, deps in dependencies.items():
            for dep in deps:
                dependency_counts[dep] = dependency_counts.get(dep, 0) + 1
        
        # Sort by dependency count
        sorted_deps = sorted(dependency_counts.items(), key=lambda x: x[1], reverse=True)
        result["most_depended_on"] = [
            {"package": pkg, "count": count}
            for pkg, count in sorted_deps[:10]
        ]
        
        if detect_cycles:
            # Detect circular dependencies using DFS
            visited = set()
            rec_stack = set()
            cycles_found = []
            
            def dfs_cycle(node: str, path: List[str]) -> None:
                visited.add(node)
                rec_stack.add(node)
                path.append(node)
                
                for dep in dependencies.get(node, []):
                    if dep not in visited:
                        dfs_cycle(dep, path.copy())
                    elif dep in rec_stack:
                        # Found a cycle
                        cycle_start = path.index(dep)
                        cycle = path[cycle_start:] + [dep]
                        if cycle not in cycles_found:
                            cycles_found.append(cycle)
                
                rec_stack.remove(node)
            
            for package in dependencies:
                if package not in visited:
                    dfs_cycle(package, [])
            
            result["cycles"] = [
                {
                    "cycle": cycle,
                    "length": len(cycle) - 1
                }
                for cycle in cycles_found
            ]
        
        if calculate_depth:
            # Calculate dependency depths
            depths = {}
            
            def calculate_depth_recursive(package: str, visited: Set[str]) -> int:
                if package in depths:
                    return depths[package]
                
                if package in visited:
                    # Circular dependency, return large value
                    return 100
                
                visited.add(package)
                
                deps = dependencies.get(package, [])
                if not deps:
                    depths[package] = 0
                    return 0
                
                max_dep_depth = 0
                for dep in deps:
                    dep_depth = calculate_depth_recursive(dep, visited.copy())
                    max_dep_depth = max(max_dep_depth, dep_depth)
                
                depths[package] = max_dep_depth + 1
                return depths[package]
            
            for package in dependencies:
                if package not in depths:
                    calculate_depth_recursive(package, set())
            
            # Calculate max depth and distribution
            if depths:
                result["max_depth"] = max(depths.values())
                
                for depth in range(result["max_depth"] + 1):
                    packages_at_depth = [pkg for pkg, d in depths.items() if d == depth]
                    result["depth_distribution"][str(depth)] = len(packages_at_depth)
        
        return result
        
    except Exception as e:
        logger.error(f"Error analyzing dependency chain: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def parse_package_json_dependencies(package_json_content: str) -> Dict[str, List[str]]:
    """
    Parse package.json to extract dependency information.
    
    Parses a package.json file and extracts dependencies and devDependencies
    into a format suitable for analyze_dependency_chain.
    
    Args:
        package_json_content: Content of package.json file
        
    Returns:
        Dictionary mapping package names to their dependencies
        
    Example:
        >>> with open('package.json') as f:
        ...     content = f.read()
        >>> deps = parse_package_json_dependencies(content)
        >>> result = analyze_dependency_chain(deps)
    """
    try:
        data = json.loads(package_json_content)
        
        dependencies = {}
        package_name = data.get("name", "unknown")
        
        # Combine dependencies and devDependencies
        all_deps = []
        if "dependencies" in data:
            all_deps.extend(data["dependencies"].keys())
        if "devDependencies" in data:
            all_deps.extend(data["devDependencies"].keys())
        
        dependencies[package_name] = all_deps
        
        return dependencies
        
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in package.json: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error parsing package.json: {e}")
        return {}


def parse_requirements_txt(requirements_content: str) -> Dict[str, List[str]]:
    """
    Parse requirements.txt to extract Python dependency information.
    
    Parses a requirements.txt file and extracts package names.
    Note: This doesn't capture transitive dependencies automatically.
    
    Args:
        requirements_content: Content of requirements.txt file
        
    Returns:
        Dictionary with project dependencies
        
    Example:
        >>> with open('requirements.txt') as f:
        ...     content = f.read()
        >>> deps = parse_requirements_txt(content)
    """
    try:
        dependencies = {"project": []}
        
        for line in requirements_content.split('\n'):
            line = line.strip()
            
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            
            # Extract package name (before ==, >=, etc.)
            match = re.match(r'([a-zA-Z0-9_-]+)', line)
            if match:
                package_name = match.group(1)
                dependencies["project"].append(package_name)
        
        return dependencies
        
    except Exception as e:
        logger.error(f"Error parsing requirements.txt: {e}")
        return {}


def suggest_dependency_improvements(analysis_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Suggest improvements based on dependency analysis.
    
    Analyzes dependency chain results and provides actionable recommendations
    for improving dependency management.
    
    Args:
        analysis_result: Result from analyze_dependency_chain
        
    Returns:
        Dictionary containing improvement suggestions
        
    Example:
        >>> deps = {"A": ["B"], "B": ["C"], "C": ["A"]}
        >>> analysis = analyze_dependency_chain(deps)
        >>> suggestions = suggest_dependency_improvements(analysis)
        >>> for s in suggestions['suggestions']:
        ...     print(s['recommendation'])
    """
    try:
        suggestions = {
            "success": True,
            "suggestions": [],
            "priority": "medium"
        }
        
        if not analysis_result.get("success"):
            return {
                "success": False,
                "error": "Invalid analysis result provided"
            }
        
        # Check for cycles
        cycles = analysis_result.get("cycles", [])
        if cycles:
            suggestions["priority"] = "high"
            suggestions["suggestions"].append({
                "severity": "high",
                "issue": f"Found {len(cycles)} circular dependencies",
                "recommendation": "Break circular dependencies by refactoring or using dependency injection",
                "affected_packages": [c["cycle"] for c in cycles]
            })
        
        # Check dependency depth
        max_depth = analysis_result.get("max_depth", 0)
        if max_depth > 10:
            suggestions["suggestions"].append({
                "severity": "medium",
                "issue": f"Deep dependency chain detected (depth: {max_depth})",
                "recommendation": "Consider flattening dependency structure or using dependency bundling",
                "details": f"Maximum depth is {max_depth}, recommended < 10"
            })
        
        # Check for highly coupled packages
        most_depended = analysis_result.get("most_depended_on", [])
        if most_depended and most_depended[0].get("count", 0) > 20:
            suggestions["suggestions"].append({
                "severity": "medium",
                "issue": f"High coupling detected: '{most_depended[0]['package']}' is depended upon by {most_depended[0]['count']} packages",
                "recommendation": "Consider splitting this package into smaller, more focused modules",
                "package": most_depended[0]["package"]
            })
        
        # Check for too many isolated packages
        isolated = analysis_result.get("isolated_packages", [])
        if len(isolated) > 10:
            suggestions["suggestions"].append({
                "severity": "low",
                "issue": f"Many isolated packages ({len(isolated)}) detected",
                "recommendation": "Consider consolidating small utility packages",
                "count": len(isolated)
            })
        
        if not suggestions["suggestions"]:
            suggestions["suggestions"].append({
                "severity": "info",
                "issue": "No major issues detected",
                "recommendation": "Dependency chain looks healthy"
            })
        
        return suggestions
        
    except Exception as e:
        logger.error(f"Error generating suggestions: {e}")
        return {
            "success": False,
            "error": str(e)
        }
