"""Visualization tools for ontology refinement decision trees and cycles.

This module provides visualization capabilities for understanding and
diagnosing refinement processes:

- Decision tree visualization for strategy selection logic
- Refinement cycle progression charts (scores over rounds)
- Strategy comparison matrices
- Visual exports (PNG, SVG, DOT formats)

Requires optional dependencies: graphviz, matplotlib
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json

from ipfs_datasets_py.optimizers.common.path_validator import (
    validate_output_path,
)

try:
    import graphviz
    HAS_GRAPHVIZ = True
except ImportError:
    HAS_GRAPHVIZ = False

try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


logger = logging.getLogger(__name__)


@dataclass
class RefinementNode:
    """A node in the refinement decision tree."""
    
    round_number: int
    action: str
    score_before: float
    score_after: Optional[float] = None
    rationale: str = ""
    priority: str = "medium"
    estimated_impact: float = 0.0
    affected_entities: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert node to dictionary."""
        return {
            "round": self.round_number,
            "action": self.action,
            "score_before": self.score_before,
            "score_after": self.score_after,
            "rationale": self.rationale,
            "priority": self.priority,
            "estimated_impact": self.estimated_impact,
            "affected_entities": self.affected_entities,
        }


class RefinementVisualizer:
    """Visualize refinement decision trees and progression."""
    
    def __init__(self, output_dir: Optional[Path] = None):
        """
        Initialize visualizer.
        
        Args:
            output_dir: Directory for saving visualizations.
                If None, uses current directory.
        """
        self.output_dir = Path(output_dir) if output_dir else Path.cwd()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._nodes: List[RefinementNode] = []
        
        if not HAS_GRAPHVIZ:
            logger.warning("graphviz not installed. Decision tree visualization disabled.")
        if not HAS_MATPLOTLIB:
            logger.warning("matplotlib not installed. Chart visualization disabled.")
    
    def add_refinement_round(
        self,
        round_number: int,
        action: str,
        score_before: float,
        score_after: Optional[float] = None,
        strategy: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record a refinement round for visualization.
        
        Args:
            round_number: Round index (1-based).
            action: Action name that was applied.
            score_before: Overall score before refinement.
            score_after: Overall score after refinement (if available).
            strategy: Full strategy dict from suggest_refinement_strategy()
                (optional, provides rationale/priority/impact).
        """
        node = RefinementNode(
            round_number=round_number,
            action=action,
            score_before=score_before,
            score_after=score_after,
            rationale=strategy.get("rationale", "") if strategy else "",
            priority=strategy.get("priority", "medium") if strategy else "medium",
            estimated_impact=strategy.get("estimated_impact", 0.0) if strategy else 0.0,
            affected_entities=strategy.get("affected_entity_count", 0) if strategy else 0,
        )
        self._nodes.append(node)
        logger.debug(f"Recorded refinement round {round_number}: {action} ({score_before:.2f} → {score_after or 'pending'})")
    
    def generate_decision_tree(
        self,
        filename: str = "refinement_tree",
        format: str = "png",
        show_scores: bool = True,
        show_impact: bool = True,
    ) -> Optional[Path]:
        """
        Generate decision tree diagram of refinement progression.
        
        Creates a graphviz digraph showing the sequence of refinement actions,
        score progression, and decision rationale.
        
        Args:
            filename: Output filename (without extension).
            format: Output format ('png', 'svg', 'pdf', 'dot').
            show_scores: Include score changes in labels.
            show_impact: Include estimated impact in labels.
        
        Returns:
            Path to generated file, or None if graphviz unavailable.
        
        Example:
            >>> viz = RefinementVisualizer()
            >>> viz.add_refinement_round(1, "add_missing_properties", 0.65, 0.72)
            >>> path = viz.generate_decision_tree()
        """
        if not HAS_GRAPHVIZ:
            logger.error("graphviz not installed, cannot generate decision tree")
            return None
        
        if not self._nodes:
            logger.warning("No refinement rounds recorded, cannot generate tree")
            return None
        
        dot = graphviz.Digraph(comment="Refinement Decision Tree")
        dot.attr(rankdir="TB")  # Top-to-bottom layout
        dot.attr("node", shape="box", style="rounded,filled", fillcolor="lightblue")
        
        # Add initial state node
        dot.node("initial", f"Initial Ontology\nScore: {self._nodes[0].score_before:.2f}")
        
        # Add refinement nodes
        for i, node in enumerate(self._nodes):
            node_id = f"round_{node.round_number}"
            
            # Build label
            label_parts = [f"Round {node.round_number}: {node.action}"]
            if show_scores and node.score_after is not None:
                delta = node.score_after - node.score_before
                label_parts.append(f"Score: {node.score_before:.2f} → {node.score_after:.2f} ({delta:+.2f})")
            if show_impact:
                label_parts.append(f"Est. Impact: {node.estimated_impact:.2f}")
            if node.priority:
                label_parts.append(f"Priority: {node.priority}")
            if node.affected_entities > 0:
                label_parts.append(f"Affected: {node.affected_entities} entities")
            
            label = "\\n".join(label_parts)
            
            # Color by priority
            if node.priority == "high":
                fillcolor = "lightcoral"
            elif node.priority == "critical":
                fillcolor = "red"
            elif node.priority == "low":
                fillcolor = "lightgreen"
            else:
                fillcolor = "lightyellow"
            
            dot.node(node_id, label, fillcolor=fillcolor)
            
            # Connect to previous node
            if i == 0:
                dot.edge("initial", node_id)
            else:
                prev_node_id = f"round_{self._nodes[i - 1].round_number}"
                dot.edge(prev_node_id, node_id)
        
        # Render
        output_path = self.output_dir / filename
        dot.render(filename=str(output_path), format=format, cleanup=True)
        
        final_path = output_path.with_suffix(f".{format}")
        logger.info(f"Decision tree saved to {final_path}")
        return final_path
    
    def generate_score_progression_chart(
        self,
        filename: str = "score_progression",
        format: str = "png",
        dimensions: Optional[List[str]] = None,
    ) -> Optional[Path]:
        """
        Generate line chart showing score progression over refinement rounds.
        
        Args:
            filename: Output filename (without extension).
            format: Output format ('png', 'svg', 'pdf').
            dimensions: Score dimensions to plot (e.g., ['overall', 'completeness']).
                If None, plots only overall scores.
        
        Returns:
            Path to generated chart, or None if matplotlib unavailable.
        
        Example:
            >>> viz = RefinementVisualizer()
            >>> viz.add_refinement_round(1, "add_properties", 0.65, 0.72)
            >>> viz.add_refinement_round(2, "merge_duplicates", 0.72, 0.78)
            >>> path = viz.generate_score_progression_chart()
        """
        if not HAS_MATPLOTLIB:
            logger.error("matplotlib not installed, cannot generate chart")
            return None
        
        if not self._nodes:
            logger.warning("No refinement rounds recorded, cannot generate chart")
            return None
        
        # Extract scores
        rounds = [0] + [node.round_number for node in self._nodes]
        scores_before = [self._nodes[0].score_before]
        scores_after = []
        
        for node in self._nodes:
            if node.score_after is not None:
                scores_after.append(node.score_after)
        
        # Create figure
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Plot overall score progression
        if scores_after:
            all_scores = scores_before + scores_after
            ax.plot(rounds[:len(all_scores)], all_scores, marker='o', linewidth=2, label='Overall Score')
        
        # Annotations for actions
        for i, node in enumerate(self._nodes):
            if node.score_after is not None:
                ax.annotate(
                    node.action.replace("_", " ").title(),
                    xy=(node.round_number, node.score_after),
                    xytext=(10, 10),
                    textcoords='offset points',
                    fontsize=9,
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.5),
                    arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'),
                )
        
        ax.set_xlabel("Refinement Round", fontsize=12)
        ax.set_ylabel("Score", fontsize=12)
        ax.set_title("Ontology Refinement Score Progression", fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='lower right')
        ax.set_ylim(0, 1.0)
        
        # Save
        output_path = self.output_dir / f"{filename}.{format}"
        fig.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        
        logger.info(f"Score progression chart saved to {output_path}")
        return output_path
    
    def generate_strategy_comparison_matrix(
        self,
        strategies: List[Dict[str, Any]],
        filename: str = "strategy_comparison",
        format: str = "png",
    ) -> Optional[Path]:
        """
        Generate comparison matrix of alternative refinement strategies.
        
        Shows estimated impact vs. priority for different strategy options,
        helping visualize trade-offs between available actions.
        
        Args:
            strategies: List of strategy dicts (from suggest_refinement_strategy).
            filename: Output filename (without extension).
            format: Output format ('png', 'svg', 'pdf').
        
        Returns:
            Path to generated matrix, or None if matplotlib unavailable.
        
        Example:
            >>> strategy1 = {"action": "add_properties", "priority": "high", "estimated_impact": 0.15}
            >>> strategy2 = {"action": "merge_duplicates", "priority": "medium", "estimated_impact": 0.10}
            >>> viz.generate_strategy_comparison_matrix([strategy1, strategy2])
        """
        if not HAS_MATPLOTLIB:
            logger.error("matplotlib not installed, cannot generate matrix")
            return None
        
        if not strategies:
            logger.warning("No strategies provided, cannot generate matrix")
            return None
        
        # Extract data
        actions = [s.get("action", "unknown") for s in strategies]
        impacts = [s.get("estimated_impact", 0.0) for s in strategies]
        priorities = [s.get("priority", "medium") for s in strategies]
        
        # Map priorities to numeric values for visualization
        priority_map = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        priority_values = [priority_map.get(p, 2) for p in priorities]
        
        # Create scatter plot
        fig, ax = plt.subplots(figsize=(10, 8))
        
        colors = {4: 'red', 3: 'orange', 2: 'yellow', 1: 'green'}
        for action, impact, priority_val in zip(actions, impacts, priority_values):
            ax.scatter(impact, priority_val, s=200, c=colors.get(priority_val, 'gray'), alpha=0.6, edgecolors='black')
            ax.text(impact, priority_val, action.replace("_", " ").title(), fontsize=9, ha='center', va='center')
        
        ax.set_xlabel("Estimated Impact", fontsize=12)
        ax.set_ylabel("Priority", fontsize=12)
        ax.set_yticks([1, 2, 3, 4])
        ax.set_yticklabels(["Low", "Medium", "High", "Critical"])
        ax.set_title("Refinement Strategy Comparison", fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)
        ax.set_xlim(0, max(impacts) * 1.2 if impacts else 0.2)
        
        # Save
        output_path = self.output_dir / f"{filename}.{format}"
        fig.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        
        logger.info(f"Strategy comparison matrix saved to {output_path}")
        return output_path
    
    def generate_summary_report(
        self,
        filename: str = "refinement_report.json",
    ) -> Path:
        """
        Generate JSON summary report of refinement session.
        
        Args:
            filename: Output filename (must end with .json).
        
        Returns:
            Path to generated report.
        
        Example:
            >>> viz = RefinementVisualizer()
            >>> # ... add rounds ...
            >>> report_path = viz.generate_summary_report()
        """
        report = {
            "total_rounds": len(self._nodes),
            "refinement_tree": [node.to_dict() for node in self._nodes],
            "score_improvement": self._calculate_score_improvement(),
            "actions_summary": self._summarize_actions(),
        }
        
        # Validate output path
        output_path = self.output_dir / filename
        base_dir = output_path.parent if output_path.is_absolute() else None
        safe_path = validate_output_path(str(output_path), allow_overwrite=True, base_dir=base_dir)
        
        with open(safe_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"Summary report saved to {safe_path}")
        return Path(safe_path)
    
    def _calculate_score_improvement(self) -> Dict[str, float]:
        """Calculate aggregate score improvement metrics."""
        if not self._nodes:
            return {"initial": 0.0, "final": 0.0, "delta": 0.0}
        
        initial_score = self._nodes[0].score_before
        final_score = self._nodes[-1].score_after if self._nodes[-1].score_after is not None else initial_score
        
        return {
            "initial": initial_score,
            "final": final_score,
            "delta": final_score - initial_score,
        }
    
    def _summarize_actions(self) -> Dict[str, int]:
        """Count occurrences of each action type."""
        action_counts = {}
        for node in self._nodes:
            action_counts[node.action] = action_counts.get(node.action, 0) + 1
        return action_counts
    
    def clear(self) -> None:
        """Clear all recorded refinement nodes."""
        self._nodes.clear()
        logger.debug("Cleared all refinement nodes")


def visualize_refinement_cycle(
    mediator_state: Dict[str, Any],
    output_dir: Optional[Path] = None,
    formats: Optional[List[str]] = None,
) -> Dict[str, Path]:
    """
    Convenience function to visualize a complete refinement cycle.
    
    Generates decision tree, score progression chart, and summary report
    from a MediatorState (or compatible dict).
    
    Args:
        mediator_state: Dict with keys:
            - 'refinement_history': List of refinement rounds
            - 'critic_scores': List of CriticScore objects
        output_dir: Directory for outputs (default: current directory).
        formats: List of output formats (default: ['png', 'json']).
    
    Returns:
        Dict mapping visualization type to output path:
        {'tree': Path, 'chart': Path, 'report': Path}
    
    Example:
        >>> state = mediator.run_refinement_cycle(text, context)
        >>> paths = visualize_refinement_cycle(state)
        >>> print(f"Tree: {paths['tree']}")
        >>> print(f"Chart: {paths['chart']}")
    """
    formats = formats or ['png', 'json']
    viz = RefinementVisualizer(output_dir=output_dir)
    
    # Extract refinement history
    history = mediator_state.get("refinement_history", [])
    critic_scores = mediator_state.get("critic_scores", [])
    
    # Record each round
    for i, round_entry in enumerate(history):
        round_num = round_entry.get("round", i + 1)
        action = round_entry.get("description", "unknown")
        
        # Get scores
        score_before = critic_scores[i - 1].overall if i > 0 and i - 1 < len(critic_scores) else 0.5
        score_after = critic_scores[i].overall if i < len(critic_scores) else None
        
        strategy = round_entry.get("strategy")
        
        viz.add_refinement_round(
            round_number=round_num,
            action=action,
            score_before=score_before,
            score_after=score_after,
            strategy=strategy,
        )
    
    # Generate visualizations
    outputs = {}
    
    for fmt in formats:
        if fmt in ['png', 'svg', 'pdf', 'dot']:
            tree_path = viz.generate_decision_tree(format=fmt)
            if tree_path:
                outputs['tree'] = tree_path
            
            if fmt in ['png', 'svg', 'pdf']:
                chart_path = viz.generate_score_progression_chart(format=fmt)
                if chart_path:
                    outputs['chart'] = chart_path
        
        elif fmt == 'json':
            report_path = viz.generate_summary_report()
            outputs['report'] = report_path
    
    return outputs
