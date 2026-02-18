"""
TDFOL Formula Dependency Graph - Analyze and visualize formula dependencies

This module provides comprehensive dependency analysis for TDFOL formulas:

1. Dependency Extraction:
   - Extract formula dependencies from proofs
   - Identify which formulas are used to derive others
   - Handle different proof types (forward, backward, tableaux)
   - Support for axioms, theorems, and derived formulas

2. DAG Construction:
   - Build Directed Acyclic Graph from dependencies
   - Nodes represent formulas
   - Edges represent inference relationships
   - Detect and handle circular dependencies
   - Compute topological ordering
   - Identify critical paths (shortest proof chains)

3. GraphViz Visualization:
   - Export to DOT format
   - Node styling by formula type (axiom, theorem, derived)
   - Edge labels showing inference rules used
   - Highlight critical paths in different color
   - Cluster related formulas
   - Support for large graphs with good layout

4. Analysis Features:
   - Find shortest proof paths between formulas
   - Identify unused axioms
   - Detect redundant formulas
   - Export in multiple formats (DOT, JSON, adjacency matrix)

Phase 11 Task 11.2 - Production-ready dependency analysis module
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .tdfol_core import Formula, TDFOLKnowledgeBase
from .tdfol_prover import ProofResult, ProofStatus, ProofStep

logger = logging.getLogger(__name__)

# Try to import optional dependencies
try:
    import graphviz
    HAS_GRAPHVIZ = True
except ImportError:
    HAS_GRAPHVIZ = False
    logger.debug("graphviz not available, DOT export only")


# ============================================================================
# Types and Enumerations
# ============================================================================


class FormulaType(Enum):
    """Type of formula in the dependency graph."""
    
    AXIOM = "axiom"           # Given axiom
    THEOREM = "theorem"       # Proved theorem
    DERIVED = "derived"       # Derived formula
    PREMISE = "premise"       # Premise/assumption
    GOAL = "goal"             # Goal formula
    LEMMA = "lemma"           # Intermediate lemma


class DependencyType(Enum):
    """Type of dependency relationship."""
    
    DIRECT = "direct"         # Direct inference
    TRANSITIVE = "transitive" # Transitive dependency
    SUPPORT = "support"       # Supporting formula


# ============================================================================
# Graph Node and Edge
# ============================================================================


@dataclass
class DependencyNode:
    """Node in the dependency graph representing a formula."""
    
    formula: Formula
    node_type: FormulaType
    name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __hash__(self) -> int:
        """Hash based on formula for use in sets/dicts."""
        return hash(self.formula)
    
    def __eq__(self, other: object) -> bool:
        """Equality based on formula."""
        if not isinstance(other, DependencyNode):
            return False
        return self.formula == other.formula
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "formula": str(self.formula),
            "type": self.node_type.value,
            "name": self.name,
            "metadata": self.metadata
        }


@dataclass
class DependencyEdge:
    """Edge in the dependency graph representing an inference step."""
    
    source: DependencyNode
    target: DependencyNode
    rule_name: Optional[str] = None
    justification: str = ""
    edge_type: DependencyType = DependencyType.DIRECT
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __hash__(self) -> int:
        """Hash based on source and target."""
        return hash((self.source, self.target))
    
    def __eq__(self, other: object) -> bool:
        """Equality based on source and target."""
        if not isinstance(other, DependencyEdge):
            return False
        return self.source == other.source and self.target == other.target
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "source": str(self.source.formula),
            "target": str(self.target.formula),
            "rule": self.rule_name,
            "justification": self.justification,
            "type": self.edge_type.value,
            "metadata": self.metadata
        }


# ============================================================================
# Circular Dependency Detection
# ============================================================================


class CircularDependencyError(Exception):
    """Raised when a circular dependency is detected."""
    
    def __init__(self, cycle: List[Formula], message: str = ""):
        self.cycle = cycle
        self.message = message or f"Circular dependency detected: {' -> '.join(str(f) for f in cycle)}"
        super().__init__(self.message)


# ============================================================================
# Formula Dependency Graph
# ============================================================================


class FormulaDependencyGraph:
    """
    Comprehensive dependency analysis for TDFOL formulas.
    
    Tracks dependencies between formulas and provides analysis capabilities:
    - Dependency extraction from proofs
    - DAG construction and validation
    - Critical path identification
    - GraphViz visualization
    - Multiple export formats
    
    Examples:
        >>> # From a proof result
        >>> graph = FormulaDependencyGraph(proof_result=result)
        >>> graph.export_dot("proof_deps.dot")
        
        >>> # From knowledge base
        >>> graph = FormulaDependencyGraph(kb=knowledge_base)
        >>> unused = graph.find_unused_axioms()
        
        >>> # Build incrementally
        >>> graph = FormulaDependencyGraph()
        >>> graph.add_formula(conclusion, [premise1, premise2], "ModusPonens")
        >>> path = graph.find_critical_path(axiom, theorem)
    """
    
    def __init__(
        self,
        proof_result: Optional[ProofResult] = None,
        kb: Optional[TDFOLKnowledgeBase] = None
    ):
        """
        Initialize dependency graph.
        
        Args:
            proof_result: Optional proof result to extract dependencies from
            kb: Optional knowledge base to initialize with axioms/theorems
        """
        self.nodes: Dict[Formula, DependencyNode] = {}
        self.edges: Set[DependencyEdge] = set()
        self.adjacency: Dict[Formula, Set[Formula]] = defaultdict(set)
        self.reverse_adjacency: Dict[Formula, Set[Formula]] = defaultdict(set)
        self._topological_order: Optional[List[Formula]] = None
        
        # Initialize from knowledge base if provided
        if kb is not None:
            self._init_from_kb(kb)
        
        # Add proof if provided
        if proof_result is not None:
            self.add_proof(proof_result)
    
    def _init_from_kb(self, kb: TDFOLKnowledgeBase) -> None:
        """Initialize nodes from knowledge base."""
        # Add axioms
        for axiom in kb.axioms:
            node = DependencyNode(
                formula=axiom,
                node_type=FormulaType.AXIOM
            )
            self.nodes[axiom] = node
        
        # Add theorems
        for theorem in kb.theorems:
            node = DependencyNode(
                formula=theorem,
                node_type=FormulaType.THEOREM
            )
            self.nodes[theorem] = node
        
        # Add definitions
        for name, formula in kb.definitions.items():
            node = DependencyNode(
                formula=formula,
                node_type=FormulaType.DERIVED,
                name=name
            )
            self.nodes[formula] = node
    
    def add_proof(self, proof_result: ProofResult) -> None:
        """
        Add dependencies from a proof result.
        
        Extracts dependency relationships from proof steps and adds them to the graph.
        
        Args:
            proof_result: Proof result containing steps to analyze
        """
        if not proof_result.is_proved():
            logger.warning(f"Adding unproved formula: {proof_result.formula}")
        
        # Add goal formula if not already present
        if proof_result.formula not in self.nodes:
            node = DependencyNode(
                formula=proof_result.formula,
                node_type=FormulaType.GOAL,
                metadata={
                    "status": proof_result.status.value,
                    "method": proof_result.method,
                    "time_ms": proof_result.time_ms
                }
            )
            self.nodes[proof_result.formula] = node
        
        # Process each proof step
        for step in proof_result.proof_steps:
            self.add_formula(
                formula=step.formula,
                depends_on=step.premises,
                rule=step.rule_name or "unknown",
                justification=step.justification
            )
    
    def add_formula(
        self,
        formula: Formula,
        depends_on: List[Formula],
        rule: str,
        justification: str = "",
        node_type: FormulaType = FormulaType.DERIVED
    ) -> None:
        """
        Add a formula with its dependencies.
        
        Args:
            formula: The derived formula
            depends_on: List of formulas this formula depends on
            rule: Name of the inference rule used
            justification: Optional justification text
            node_type: Type of the formula node
        """
        # Add target node if not present
        if formula not in self.nodes:
            self.nodes[formula] = DependencyNode(
                formula=formula,
                node_type=node_type
            )
        
        # Add edges from dependencies
        for premise in depends_on:
            # Add premise node if not present
            if premise not in self.nodes:
                self.nodes[premise] = DependencyNode(
                    formula=premise,
                    node_type=FormulaType.PREMISE
                )
            
            # Create edge from premise to conclusion
            edge = DependencyEdge(
                source=self.nodes[premise],
                target=self.nodes[formula],
                rule_name=rule,
                justification=justification,
                edge_type=DependencyType.DIRECT
            )
            
            self.edges.add(edge)
            self.adjacency[premise].add(formula)
            self.reverse_adjacency[formula].add(premise)
        
        # Invalidate cached topological order
        self._topological_order = None
    
    def get_dependencies(self, formula: Formula) -> List[Formula]:
        """
        Get direct dependencies of a formula (formulas it depends on).
        
        Args:
            formula: Formula to get dependencies for
            
        Returns:
            List of formulas that this formula directly depends on
        """
        return list(self.reverse_adjacency.get(formula, set()))
    
    def get_dependents(self, formula: Formula) -> List[Formula]:
        """
        Get formulas that depend on this formula.
        
        Args:
            formula: Formula to get dependents for
            
        Returns:
            List of formulas that directly depend on this formula
        """
        return list(self.adjacency.get(formula, set()))
    
    def get_all_dependencies(self, formula: Formula) -> Set[Formula]:
        """
        Get all transitive dependencies of a formula.
        
        Args:
            formula: Formula to get all dependencies for
            
        Returns:
            Set of all formulas (direct and transitive) that this formula depends on
        """
        visited = set()
        to_visit = deque([formula])
        
        while to_visit:
            current = to_visit.popleft()
            if current in visited:
                continue
            visited.add(current)
            
            # Add all direct dependencies
            for dep in self.get_dependencies(current):
                if dep not in visited:
                    to_visit.append(dep)
        
        # Remove the formula itself
        visited.discard(formula)
        return visited
    
    def get_all_dependents(self, formula: Formula) -> Set[Formula]:
        """
        Get all formulas that transitively depend on this formula.
        
        Args:
            formula: Formula to get all dependents for
            
        Returns:
            Set of all formulas (direct and transitive) that depend on this formula
        """
        visited = set()
        to_visit = deque([formula])
        
        while to_visit:
            current = to_visit.popleft()
            if current in visited:
                continue
            visited.add(current)
            
            # Add all direct dependents
            for dep in self.get_dependents(current):
                if dep not in visited:
                    to_visit.append(dep)
        
        # Remove the formula itself
        visited.discard(formula)
        return visited
    
    def detect_cycles(self) -> List[List[Formula]]:
        """
        Detect circular dependencies in the graph.
        
        Returns:
            List of cycles found, each cycle is a list of formulas
        """
        cycles = []
        visited = set()
        rec_stack = set()
        path = []
        
        def dfs(formula: Formula) -> bool:
            """DFS to detect cycles."""
            visited.add(formula)
            rec_stack.add(formula)
            path.append(formula)
            
            for dependent in self.get_dependents(formula):
                if dependent not in visited:
                    if dfs(dependent):
                        return True
                elif dependent in rec_stack:
                    # Found a cycle
                    cycle_start = path.index(dependent)
                    cycle = path[cycle_start:] + [dependent]
                    cycles.append(cycle)
                    return True
            
            path.pop()
            rec_stack.remove(formula)
            return False
        
        # Check all nodes
        for formula in self.nodes:
            if formula not in visited:
                dfs(formula)
        
        return cycles
    
    def topological_sort(self) -> List[Formula]:
        """
        Compute topological ordering of formulas.
        
        Returns:
            List of formulas in topological order (dependencies before dependents)
            
        Raises:
            CircularDependencyError: If circular dependencies are detected
        """
        if self._topological_order is not None:
            return self._topological_order
        
        # Check for cycles first
        cycles = self.detect_cycles()
        if cycles:
            raise CircularDependencyError(cycles[0])
        
        # Compute in-degree for each node
        in_degree = {formula: 0 for formula in self.nodes}
        for formula in self.nodes:
            for dependent in self.get_dependents(formula):
                in_degree[dependent] += 1
        
        # Initialize queue with nodes that have no dependencies
        queue = deque([f for f, deg in in_degree.items() if deg == 0])
        result = []
        
        while queue:
            formula = queue.popleft()
            result.append(formula)
            
            # Reduce in-degree for all dependents
            for dependent in self.get_dependents(formula):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)
        
        # Cache result
        self._topological_order = result
        return result
    
    def find_critical_path(
        self,
        start: Formula,
        end: Formula
    ) -> Optional[List[Formula]]:
        """
        Find the shortest proof path between two formulas.
        
        Uses BFS to find the shortest dependency path from start to end.
        
        Args:
            start: Starting formula (typically an axiom)
            end: Target formula (typically a theorem)
            
        Returns:
            List of formulas forming the shortest path, or None if no path exists
        """
        if start not in self.nodes or end not in self.nodes:
            return None
        
        # BFS to find shortest path
        queue = deque([(start, [start])])
        visited = {start}
        
        while queue:
            current, path = queue.popleft()
            
            if current == end:
                return path
            
            for dependent in self.get_dependents(current):
                if dependent not in visited:
                    visited.add(dependent)
                    queue.append((dependent, path + [dependent]))
        
        return None
    
    def find_all_paths(
        self,
        start: Formula,
        end: Formula,
        max_length: Optional[int] = None
    ) -> List[List[Formula]]:
        """
        Find all paths between two formulas.
        
        Args:
            start: Starting formula
            end: Target formula
            max_length: Optional maximum path length
            
        Returns:
            List of all paths (each path is a list of formulas)
        """
        if start not in self.nodes or end not in self.nodes:
            return []
        
        all_paths = []
        
        def dfs(current: Formula, path: List[Formula], visited: Set[Formula]):
            """DFS to find all paths."""
            if max_length and len(path) > max_length:
                return
            
            if current == end:
                all_paths.append(path.copy())
                return
            
            for dependent in self.get_dependents(current):
                if dependent not in visited:
                    visited.add(dependent)
                    path.append(dependent)
                    dfs(dependent, path, visited)
                    path.pop()
                    visited.remove(dependent)
        
        dfs(start, [start], {start})
        return all_paths
    
    def find_unused_axioms(self) -> List[Formula]:
        """
        Find axioms that are not used in any derivations.
        
        Returns:
            List of axioms that have no dependents
        """
        unused = []
        for formula, node in self.nodes.items():
            if node.node_type == FormulaType.AXIOM:
                if not self.get_dependents(formula):
                    unused.append(formula)
        return unused
    
    def find_redundant_formulas(self) -> List[Tuple[Formula, Formula]]:
        """
        Find pairs of formulas where one can be derived from the other.
        
        Returns:
            List of (formula1, formula2) tuples where formula1 depends on formula2
        """
        redundant = []
        formulas = list(self.nodes.keys())
        
        for i, f1 in enumerate(formulas):
            for f2 in formulas[i+1:]:
                # Check if f1 depends on f2
                if f2 in self.get_all_dependencies(f1):
                    redundant.append((f1, f2))
                # Check if f2 depends on f1
                elif f1 in self.get_all_dependencies(f2):
                    redundant.append((f2, f1))
        
        return redundant
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about the dependency graph.
        
        Returns:
            Dictionary containing graph statistics
        """
        node_types = defaultdict(int)
        for node in self.nodes.values():
            node_types[node.node_type.value] += 1
        
        edge_types = defaultdict(int)
        for edge in self.edges:
            edge_types[edge.edge_type.value] += 1
        
        return {
            "num_nodes": len(self.nodes),
            "num_edges": len(self.edges),
            "node_types": dict(node_types),
            "edge_types": dict(edge_types),
            "has_cycles": len(self.detect_cycles()) > 0,
            "num_axioms": node_types[FormulaType.AXIOM.value],
            "num_theorems": node_types[FormulaType.THEOREM.value],
            "num_derived": node_types[FormulaType.DERIVED.value]
        }
    
    # ========================================================================
    # Export Methods
    # ========================================================================
    
    def export_dot(
        self,
        output_path: Union[str, Path],
        highlight_path: Optional[List[Formula]] = None,
        include_labels: bool = True,
        cluster_by_type: bool = True
    ) -> None:
        """
        Export graph to GraphViz DOT format.
        
        Args:
            output_path: Path to save DOT file
            highlight_path: Optional path to highlight in different color
            include_labels: Whether to include rule labels on edges
            cluster_by_type: Whether to cluster nodes by type
        """
        output_path = Path(output_path)
        
        # Build DOT content
        lines = ["digraph DependencyGraph {"]
        lines.append("  rankdir=TB;")
        lines.append("  node [shape=box, style=rounded];")
        lines.append("")
        
        # Define node styles
        node_styles = {
            FormulaType.AXIOM: 'fillcolor=lightblue, style="rounded,filled"',
            FormulaType.THEOREM: 'fillcolor=lightgreen, style="rounded,filled"',
            FormulaType.DERIVED: 'fillcolor=lightyellow, style="rounded,filled"',
            FormulaType.PREMISE: 'fillcolor=lightgray, style="rounded,filled"',
            FormulaType.GOAL: 'fillcolor=gold, style="rounded,filled"',
            FormulaType.LEMMA: 'fillcolor=lightcyan, style="rounded,filled"'
        }
        
        # Create highlight set
        highlight_set = set(highlight_path) if highlight_path else set()
        
        # Group nodes by type if clustering
        if cluster_by_type:
            type_groups = defaultdict(list)
            for formula, node in self.nodes.items():
                type_groups[node.node_type].append((formula, node))
            
            for node_type, nodes in type_groups.items():
                lines.append(f'  subgraph cluster_{node_type.value} {{')
                lines.append(f'    label="{node_type.value.capitalize()}";')
                lines.append('    style=dashed;')
                lines.append('    color=gray;')
                
                for formula, node in nodes:
                    node_id = f'n{id(formula)}'
                    label = node.name if node.name else str(formula)
                    style = node_styles[node.node_type]
                    
                    if formula in highlight_set:
                        style += ', penwidth=3, color=red'
                    
                    lines.append(f'    {node_id} [label="{label}", {style}];')
                
                lines.append('  }')
                lines.append('')
        else:
            # Add nodes without clustering
            for formula, node in self.nodes.items():
                node_id = f'n{id(formula)}'
                label = node.name if node.name else str(formula)
                style = node_styles[node.node_type]
                
                if formula in highlight_set:
                    style += ', penwidth=3, color=red'
                
                lines.append(f'  {node_id} [label="{label}", {style}];')
            lines.append('')
        
        # Add edges
        for edge in self.edges:
            source_id = f'n{id(edge.source.formula)}'
            target_id = f'n{id(edge.target.formula)}'
            
            edge_attrs = []
            if include_labels and edge.rule_name:
                edge_attrs.append(f'label="{edge.rule_name}"')
            
            # Highlight edges in critical path
            if (edge.source.formula in highlight_set and 
                edge.target.formula in highlight_set):
                edge_attrs.append('color=red, penwidth=2')
            
            attrs_str = ', '.join(edge_attrs)
            if attrs_str:
                lines.append(f'  {source_id} -> {target_id} [{attrs_str}];')
            else:
                lines.append(f'  {source_id} -> {target_id};')
        
        lines.append("}")
        
        # Write to file
        output_path.write_text('\n'.join(lines))
        logger.info(f"Exported DOT to {output_path}")
        
        # Try to render if graphviz is available
        if HAS_GRAPHVIZ:
            try:
                src = graphviz.Source('\n'.join(lines))
                src.render(output_path.stem, directory=output_path.parent, 
                          format='svg', cleanup=True)
                logger.info(f"Rendered SVG to {output_path.with_suffix('.svg')}")
            except Exception as e:
                logger.warning(f"Could not render graph: {e}")
    
    def to_json(self) -> Dict[str, Any]:
        """
        Export graph to JSON format.
        
        Returns:
            Dictionary representation suitable for JSON serialization
        """
        nodes_list = [
            {
                "id": str(formula),
                **node.to_dict()
            }
            for formula, node in self.nodes.items()
        ]
        
        edges_list = [
            {
                "source": str(edge.source.formula),
                "target": str(edge.target.formula),
                **edge.to_dict()
            }
            for edge in self.edges
        ]
        
        return {
            "nodes": nodes_list,
            "edges": edges_list,
            "statistics": self.get_statistics()
        }
    
    def export_json(self, output_path: Union[str, Path]) -> None:
        """
        Export graph to JSON file.
        
        Args:
            output_path: Path to save JSON file
        """
        output_path = Path(output_path)
        data = self.to_json()
        
        output_path.write_text(json.dumps(data, indent=2))
        logger.info(f"Exported JSON to {output_path}")
    
    def to_adjacency_matrix(self) -> Tuple[List[Formula], List[List[int]]]:
        """
        Export graph as adjacency matrix.
        
        Returns:
            Tuple of (formula_list, adjacency_matrix) where matrix[i][j] = 1
            if there is an edge from formula_list[i] to formula_list[j]
        """
        formulas = list(self.nodes.keys())
        n = len(formulas)
        matrix = [[0] * n for _ in range(n)]
        
        formula_to_idx = {f: i for i, f in enumerate(formulas)}
        
        for edge in self.edges:
            i = formula_to_idx[edge.source.formula]
            j = formula_to_idx[edge.target.formula]
            matrix[i][j] = 1
        
        return formulas, matrix
    
    def export_adjacency_matrix(self, output_path: Union[str, Path]) -> None:
        """
        Export adjacency matrix to CSV file.
        
        Args:
            output_path: Path to save CSV file
        """
        output_path = Path(output_path)
        formulas, matrix = self.to_adjacency_matrix()
        
        lines = ["," + ",".join(f'"{f}"' for f in formulas)]
        for i, row in enumerate(matrix):
            lines.append(f'"{formulas[i]}",' + ",".join(str(x) for x in row))
        
        output_path.write_text('\n'.join(lines))
        logger.info(f"Exported adjacency matrix to {output_path}")


# ============================================================================
# Convenience Functions
# ============================================================================


def analyze_proof_dependencies(
    proof_result: ProofResult,
    output_dir: Optional[Path] = None
) -> FormulaDependencyGraph:
    """
    Analyze dependencies in a proof and optionally export visualizations.
    
    Args:
        proof_result: Proof result to analyze
        output_dir: Optional directory to save visualizations
        
    Returns:
        FormulaDependencyGraph with the proof dependencies
    """
    graph = FormulaDependencyGraph(proof_result=proof_result)
    
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        graph.export_dot(output_dir / "dependencies.dot")
        graph.export_json(output_dir / "dependencies.json")
        graph.export_adjacency_matrix(output_dir / "dependencies.csv")
        
        logger.info(f"Exported visualizations to {output_dir}")
    
    return graph


def find_proof_chain(
    start: Formula,
    end: Formula,
    kb: TDFOLKnowledgeBase,
    proof_results: List[ProofResult]
) -> Optional[List[Formula]]:
    """
    Find the shortest proof chain from start to end formula.
    
    Args:
        start: Starting formula
        end: Target formula
        kb: Knowledge base
        proof_results: List of proof results to analyze
        
    Returns:
        Shortest proof chain, or None if no chain exists
    """
    graph = FormulaDependencyGraph(kb=kb)
    
    for result in proof_results:
        graph.add_proof(result)
    
    return graph.find_critical_path(start, end)
