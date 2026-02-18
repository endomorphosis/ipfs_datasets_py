"""
Countermodel Generation and Visualization for TDFOL

This module extracts and visualizes countermodels from failed modal tableaux proofs.
When a formula is not valid, an open branch in the tableaux represents a countermodel
(a Kripke structure where the formula is false).

A countermodel consists of:
1. A set of possible worlds
2. An accessibility relation between worlds
3. A valuation function (which atoms are true in each world)
4. A designated world where the formula is false

Visualization formats:
- ASCII art for simple models
- GraphViz DOT for complex models
- JSON for programmatic access
- Human-readable descriptions
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .tdfol_core import Formula, Predicate, Variable
from .modal_tableaux import TableauxBranch, World, ModalLogicType
from .exceptions import ProofError

logger = logging.getLogger(__name__)


@dataclass
class KripkeStructure:
    """
    A Kripke structure (model) for modal logic.
    
    Consists of:
    - W: Set of possible worlds
    - R: Accessibility relation (W × W)
    - V: Valuation function (world → set of true atoms)
    - w0: Designated initial world
    """
    worlds: Set[int] = field(default_factory=set)
    accessibility: Dict[int, Set[int]] = field(default_factory=dict)
    valuation: Dict[int, Set[str]] = field(default_factory=dict)
    initial_world: int = 0
    logic_type: ModalLogicType = ModalLogicType.K
    
    def add_world(self, world_id: int) -> None:
        """Add a world to the structure."""
        self.worlds.add(world_id)
        if world_id not in self.accessibility:
            self.accessibility[world_id] = set()
        if world_id not in self.valuation:
            self.valuation[world_id] = set()
    
    def add_accessibility(self, from_world: int, to_world: int) -> None:
        """Add an accessibility relation."""
        if from_world not in self.accessibility:
            self.accessibility[from_world] = set()
        self.accessibility[from_world].add(to_world)
    
    def set_atom_true(self, world_id: int, atom: str) -> None:
        """Set an atom as true in a world."""
        if world_id not in self.valuation:
            self.valuation[world_id] = set()
        self.valuation[world_id].add(atom)
    
    def is_atom_true(self, world_id: int, atom: str) -> bool:
        """Check if an atom is true in a world."""
        return atom in self.valuation.get(world_id, set())
    
    def get_accessible_worlds(self, world_id: int) -> Set[int]:
        """Get worlds accessible from given world."""
        return self.accessibility.get(world_id, set()).copy()
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON export."""
        return {
            "worlds": list(self.worlds),
            "accessibility": {str(k): list(v) for k, v in self.accessibility.items()},
            "valuation": {str(k): list(v) for k, v in self.valuation.items()},
            "initial_world": self.initial_world,
            "logic_type": self.logic_type.value
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass
class CounterModel:
    """
    A countermodel showing why a formula is not valid.
    
    Contains:
    - The formula that failed
    - A Kripke structure where formula is false
    - Explanation of why formula fails
    """
    formula: Formula
    kripke: KripkeStructure
    explanation: List[str] = field(default_factory=list)
    
    def __str__(self) -> str:
        """Human-readable representation."""
        lines = [
            f"Countermodel for: {self.formula}",
            f"Logic: {self.kripke.logic_type.value}",
            f"Worlds: {sorted(self.kripke.worlds)}",
            f"Initial: w{self.kripke.initial_world}",
            ""
        ]
        
        # Show valuation
        lines.append("Valuation (true atoms):")
        for world_id in sorted(self.kripke.worlds):
            atoms = self.kripke.valuation.get(world_id, set())
            if atoms:
                lines.append(f"  w{world_id}: {', '.join(sorted(atoms))}")
            else:
                lines.append(f"  w{world_id}: (none)")
        
        # Show accessibility
        lines.append("")
        lines.append("Accessibility:")
        for world_id in sorted(self.kripke.worlds):
            accessible = self.kripke.accessibility.get(world_id, set())
            if accessible:
                targets = ', '.join(f"w{w}" for w in sorted(accessible))
                lines.append(f"  w{world_id} → {targets}")
        
        # Show explanation
        if self.explanation:
            lines.append("")
            lines.append("Explanation:")
            for line in self.explanation:
                lines.append(f"  {line}")
        
        return '\n'.join(lines)
    
    def to_ascii_art(self) -> str:
        """Generate ASCII art representation of countermodel."""
        lines = []
        lines.append(f"Countermodel for: {self.formula}")
        lines.append("")
        
        # Simple tree representation
        for world_id in sorted(self.kripke.worlds):
            atoms = self.kripke.valuation.get(world_id, set())
            atom_str = ', '.join(sorted(atoms)) if atoms else "∅"
            
            prefix = "→ " if world_id == self.kripke.initial_world else "  "
            lines.append(f"{prefix}w{world_id}: {{{atom_str}}}")
            
            # Show accessible worlds
            accessible = self.kripke.accessibility.get(world_id, set())
            if accessible:
                for target in sorted(accessible):
                    lines.append(f"  ├─→ w{target}")
        
        return '\n'.join(lines)
    
    def to_dot(self) -> str:
        """
        Generate GraphViz DOT format for visualization.
        
        Can be rendered with: dot -Tpng -o countermodel.png
        """
        lines = ["digraph Countermodel {"]
        lines.append(f'  label="Countermodel for {self.formula}";')
        lines.append('  labelloc="t";')
        lines.append('  node [shape=circle];')
        lines.append('')
        
        # Nodes (worlds)
        for world_id in sorted(self.kripke.worlds):
            atoms = self.kripke.valuation.get(world_id, set())
            atom_str = '\\n'.join(sorted(atoms)) if atoms else "∅"
            
            # Highlight initial world
            if world_id == self.kripke.initial_world:
                lines.append(f'  w{world_id} [label="w{world_id}\\n{atom_str}", style=filled, fillcolor=lightblue];')
            else:
                lines.append(f'  w{world_id} [label="w{world_id}\\n{atom_str}"];')
        
        lines.append('')
        
        # Edges (accessibility)
        for world_id in sorted(self.kripke.worlds):
            accessible = self.kripke.accessibility.get(world_id, set())
            for target in sorted(accessible):
                lines.append(f'  w{world_id} -> w{target};')
        
        lines.append('}')
        return '\n'.join(lines)
    
    def to_json(self, indent: int = 2) -> str:
        """Convert countermodel to JSON."""
        data = {
            "formula": str(self.formula),
            "kripke_structure": self.kripke.to_dict(),
            "explanation": self.explanation
        }
        return json.dumps(data, indent=indent)


class CounterModelExtractor:
    """
    Extract countermodels from failed tableaux proofs.
    
    When a formula is not valid (tableaux proof fails), we have an open branch.
    This branch represents a countermodel - a Kripke structure where the formula
    is false.
    """
    
    def __init__(self, logic_type: ModalLogicType = ModalLogicType.K):
        """Initialize countermodel extractor."""
        self.logic_type = logic_type
    
    def extract(self, formula: Formula, branch: TableauxBranch) -> CounterModel:
        """
        Extract a countermodel from an open tableaux branch.
        
        Args:
            formula: The formula that failed to prove
            branch: An open branch from the failed tableaux
            
        Returns:
            CounterModel showing why formula is not valid
            
        Raises:
            ProofError: If branch is closed or invalid
        """
        if branch.is_closed:
            raise ProofError(
                formula=formula,
                method="countermodel_extraction",
                reason="Cannot extract countermodel from closed branch"
            )
        
        # Build Kripke structure from branch
        kripke = KripkeStructure(logic_type=self.logic_type)
        
        # Add all worlds
        for world_id in branch.worlds.keys():
            kripke.add_world(world_id)
        
        # Add accessibility relations
        for from_world, to_worlds in branch.accessibility.items():
            for to_world in to_worlds:
                kripke.add_accessibility(from_world, to_world)
        
        # Extract valuation (which atoms are true)
        for world_id, world in branch.worlds.items():
            for formula_obj in world.formulas:
                # Extract atomic propositions
                atoms = self._extract_atoms(formula_obj, negated=False)
                for atom in atoms:
                    kripke.set_atom_true(world_id, atom)
        
        # Generate explanation
        explanation = self._generate_explanation(formula, kripke, branch)
        
        return CounterModel(
            formula=formula,
            kripke=kripke,
            explanation=explanation
        )
    
    def _extract_atoms(self, formula: Formula, negated: bool) -> Set[str]:
        """Extract atomic propositions from a formula."""
        atoms = set()
        
        if isinstance(formula, Predicate):
            # Simple predicate - use name as atom
            if not negated:
                atoms.add(formula.name)
        
        # For complex formulas, recursively extract atoms
        # This is a simplified version - full implementation would traverse formula tree
        
        return atoms
    
    def _generate_explanation(
        self,
        formula: Formula,
        kripke: KripkeStructure,
        branch: TableauxBranch
    ) -> List[str]:
        """Generate human-readable explanation of why formula fails."""
        explanation = []
        
        explanation.append(f"Formula '{formula}' is not {self.logic_type.value}-valid")
        explanation.append(f"Countermodel has {len(kripke.worlds)} world(s)")
        
        # Check initial world
        init_atoms = kripke.valuation.get(kripke.initial_world, set())
        if init_atoms:
            explanation.append(
                f"At initial world w{kripke.initial_world}: {', '.join(sorted(init_atoms))} are true"
            )
        else:
            explanation.append(f"At initial world w{kripke.initial_world}: no atoms are true")
        
        # Describe accessibility
        accessible_count = sum(len(v) for v in kripke.accessibility.values())
        explanation.append(f"Total accessibility relations: {accessible_count}")
        
        # Logic-specific properties
        if self.logic_type == ModalLogicType.T:
            explanation.append("T logic: All worlds have reflexive accessibility")
        elif self.logic_type == ModalLogicType.S4:
            explanation.append("S4 logic: Reflexive and transitive accessibility")
        elif self.logic_type == ModalLogicType.S5:
            explanation.append("S5 logic: Equivalence relation (all worlds access each other)")
        
        return explanation


def extract_countermodel(
    formula: Formula,
    branch: TableauxBranch,
    logic_type: ModalLogicType = ModalLogicType.K
) -> CounterModel:
    """
    Convenience function to extract a countermodel.
    
    Args:
        formula: The formula that failed
        branch: An open tableaux branch
        logic_type: The modal logic type
        
    Returns:
        CounterModel showing why formula is not valid
        
    Example:
        >>> from modal_tableaux import ModalTableaux, ModalLogicType
        >>> from tdfol_core import parse_tdfol
        >>> 
        >>> tableaux = ModalTableaux(logic_type=ModalLogicType.K)
        >>> formula = parse_tdfol("□P → P")  # Not valid in K
        >>> result = tableaux.prove(formula)
        >>> 
        >>> if not result.is_valid and result.open_branch:
        >>>     counter = extract_countermodel(formula, result.open_branch, ModalLogicType.K)
        >>>     print(counter.to_ascii_art())
    """
    extractor = CounterModelExtractor(logic_type=logic_type)
    return extractor.extract(formula, branch)


def visualize_countermodel(
    countermodel: CounterModel,
    format: str = "ascii"
) -> str:
    """
    Visualize a countermodel in various formats.
    
    Args:
        countermodel: The countermodel to visualize
        format: Output format ("ascii", "dot", "json")
        
    Returns:
        String representation in requested format
        
    Raises:
        ValueError: If format is not supported
    """
    if format == "ascii":
        return countermodel.to_ascii_art()
    elif format == "dot":
        return countermodel.to_dot()
    elif format == "json":
        return countermodel.to_json()
    else:
        raise ValueError(f"Unsupported format: {format}. Use 'ascii', 'dot', or 'json'")


# Convenience functions for common visualizations

def print_countermodel_ascii(countermodel: CounterModel) -> None:
    """Print countermodel as ASCII art to console."""
    print(countermodel.to_ascii_art())


def save_countermodel_dot(countermodel: CounterModel, filename: str) -> None:
    """Save countermodel as GraphViz DOT file."""
    with open(filename, 'w') as f:
        f.write(countermodel.to_dot())
    logger.info(f"Countermodel saved to {filename}")
    logger.info(f"Render with: dot -Tpng -o {filename}.png {filename}")


def save_countermodel_json(countermodel: CounterModel, filename: str) -> None:
    """Save countermodel as JSON file."""
    with open(filename, 'w') as f:
        f.write(countermodel.to_json())
    logger.info(f"Countermodel saved to {filename}")
