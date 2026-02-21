"""
Dependency Analysis Engine — canonical package module.

Business logic extracted from mcp_server/tools/software_engineering_tools/dependency_chain_analyzer.py.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


def analyze_dependency_chain(
    dependencies: Dict[str, List[str]],
    detect_cycles: bool = True,
    calculate_depth: bool = True,
) -> Dict[str, Any]:
    """Analyze dependency chains to detect cycles, calculate depths, and identify issues."""
    try:
        result: Dict[str, Any] = {
            "success": True,
            "total_packages": len(dependencies),
            "cycles": [],
            "max_depth": 0,
            "depth_distribution": {},
            "isolated_packages": [],
            "most_depended_on": [],
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

        result["isolated_packages"] = [
            pkg for pkg, deps in dependencies.items() if not deps
        ]

        dependency_counts: Dict[str, int] = {}
        for deps in dependencies.values():
            for dep in deps:
                dependency_counts[dep] = dependency_counts.get(dep, 0) + 1

        sorted_deps = sorted(dependency_counts.items(), key=lambda x: x[1], reverse=True)
        result["most_depended_on"] = [
            {"package": pkg, "count": count} for pkg, count in sorted_deps[:10]
        ]

        if detect_cycles:
            visited: Set[str] = set()
            rec_stack: Set[str] = set()
            cycles_found: List[List[str]] = []

            def dfs_cycle(node: str, path: List[str]) -> None:
                visited.add(node)
                rec_stack.add(node)
                path.append(node)
                for dep in dependencies.get(node, []):
                    if dep not in visited:
                        dfs_cycle(dep, path.copy())
                    elif dep in rec_stack:
                        cycle_start = path.index(dep)
                        cycle = path[cycle_start:] + [dep]
                        if cycle not in cycles_found:
                            cycles_found.append(cycle)
                rec_stack.remove(node)

            for package in dependencies:
                if package not in visited:
                    dfs_cycle(package, [])

            result["cycles"] = [
                {"cycle": cycle, "length": len(cycle) - 1} for cycle in cycles_found
            ]

        if calculate_depth:
            depths: Dict[str, int] = {}

            def calc_depth(package: str, vis: Set[str]) -> int:
                if package in depths:
                    return depths[package]
                if package in vis:
                    return 100
                vis.add(package)
                deps = dependencies.get(package, [])
                if not deps:
                    depths[package] = 0
                    return 0
                max_dep = max(calc_depth(d, vis.copy()) for d in deps)
                depths[package] = max_dep + 1
                return depths[package]

            for package in dependencies:
                if package not in depths:
                    calc_depth(package, set())

            if depths:
                result["max_depth"] = max(depths.values())
                for depth in range(result["max_depth"] + 1):
                    result["depth_distribution"][str(depth)] = sum(
                        1 for d in depths.values() if d == depth
                    )

        return result

    except Exception as e:
        logger.error("Error analyzing dependency chain: %s", e)
        return {"success": False, "error": str(e)}


def parse_package_json_dependencies(package_json_content: str) -> Dict[str, List[str]]:
    """Parse package.json to extract dependency information."""
    try:
        data = json.loads(package_json_content)
        all_deps: List[str] = []
        for key in ("dependencies", "devDependencies"):
            all_deps.extend(data.get(key, {}).keys())
        return {data.get("name", "unknown"): all_deps}
    except (json.JSONDecodeError, Exception) as e:
        logger.error("Error parsing package.json: %s", e)
        return {}


def parse_requirements_txt(requirements_content: str) -> Dict[str, List[str]]:
    """Parse requirements.txt to extract Python dependency information."""
    try:
        packages: List[str] = []
        for line in requirements_content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r"([a-zA-Z0-9_-]+)", line)
            if match:
                packages.append(match.group(1))
        return {"project": packages}
    except Exception as e:
        logger.error("Error parsing requirements.txt: %s", e)
        return {}


def suggest_dependency_improvements(analysis_result: Dict[str, Any]) -> Dict[str, Any]:
    """Suggest improvements based on dependency analysis."""
    try:
        if not analysis_result.get("success"):
            return {"success": False, "error": "Invalid analysis result provided"}

        suggestions: List[Dict[str, Any]] = []
        priority = "medium"

        cycles = analysis_result.get("cycles", [])
        if cycles:
            priority = "high"
            suggestions.append({
                "severity": "high",
                "issue": f"Found {len(cycles)} circular dependencies",
                "recommendation": (
                    "Break circular dependencies by refactoring or using dependency injection"
                ),
                "affected_packages": [c["cycle"] for c in cycles],
            })

        max_depth = analysis_result.get("max_depth", 0)
        if max_depth > 10:
            suggestions.append({
                "severity": "medium",
                "issue": f"Deep dependency chain detected (depth: {max_depth})",
                "recommendation": (
                    "Consider flattening dependency structure or using dependency bundling"
                ),
                "details": f"Maximum depth is {max_depth}, recommended < 10",
            })

        most_depended = analysis_result.get("most_depended_on", [])
        if most_depended and most_depended[0].get("count", 0) > 20:
            suggestions.append({
                "severity": "medium",
                "issue": (
                    f"High coupling detected: '{most_depended[0]['package']}' is depended "
                    f"upon by {most_depended[0]['count']} packages"
                ),
                "recommendation": (
                    "Consider splitting this package into smaller, more focused modules"
                ),
                "package": most_depended[0]["package"],
            })

        isolated = analysis_result.get("isolated_packages", [])
        if len(isolated) > 10:
            suggestions.append({
                "severity": "low",
                "issue": f"Many isolated packages ({len(isolated)}) detected",
                "recommendation": "Consider consolidating small utility packages",
                "count": len(isolated),
            })

        if not suggestions:
            suggestions.append({
                "severity": "info",
                "issue": "No major issues detected",
                "recommendation": "Dependency chain looks healthy",
            })

        return {"success": True, "suggestions": suggestions, "priority": priority}

    except Exception as e:
        logger.error("Error generating suggestions: %s", e)
        return {"success": False, "error": str(e)}
