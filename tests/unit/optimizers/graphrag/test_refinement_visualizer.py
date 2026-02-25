"""Tests for refinement visualization tools.

Tests cover decision tree generation, score progression charts,
strategy comparison matrices, and summary report generation.
"""

import json
import pytest
from pathlib import Path
from typing import Any, Dict

from ipfs_datasets_py.optimizers.graphrag.refinement_visualizer import (
    RefinementVisualizer,
    RefinementNode,
    visualize_refinement_cycle,
    HAS_GRAPHVIZ,
    HAS_MATPLOTLIB,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def output_dir(tmp_path) -> Path:
    """Create temporary output directory for visualizations."""
    return tmp_path / "viz_output"


@pytest.fixture
def visualizer(output_dir: Path) -> RefinementVisualizer:
    """Create visualizer instance."""
    return RefinementVisualizer(output_dir=output_dir)


@pytest.fixture
def sample_strategy() -> Dict[str, Any]:
    """Sample refinement strategy dict."""
    return {
        "action": "add_missing_properties",
        "priority": "high",
        "rationale": "Clarity score is low. Many entities lack properties.",
        "estimated_impact": 0.12,
        "affected_entity_count": 15,
        "alternative_actions": ["normalize_names", "split_entity"],
    }


@pytest.fixture
def sample_mediator_state() -> Dict[str, Any]:
    """Sample mediator state with refinement history."""
    return {
        "refinement_history": [
            {"round": 1, "description": "add_missing_properties", "strategy": {"priority": "high", "estimated_impact": 0.12}},
            {"round": 2, "description": "merge_duplicates", "strategy": {"priority": "medium", "estimated_impact": 0.10}},
            {"round": 3, "description": "normalize_names", "strategy": {"priority": "low", "estimated_impact": 0.05}},
        ],
        "critic_scores": [
            type('CriticScore', (), {"overall": 0.65})(),
            type('CriticScore', (), {"overall": 0.72})(),
            type('CriticScore', (), {"overall": 0.78})(),
            type('CriticScore', (), {"overall": 0.82})(),
        ],
    }


# =============================================================================
# Test Cases: RefinementNode
# =============================================================================


class TestRefinementNode:
    """Test RefinementNode dataclass."""
    
    def test_node_creation(self):
        """Test creating a refinement node."""
        node = RefinementNode(
            round_number=1,
            action="add_properties",
            score_before=0.65,
            score_after=0.72,
            rationale="Low clarity score",
            priority="high",
        )
        assert node.round_number == 1
        assert node.action == "add_properties"
        assert node.score_before == 0.65
        assert node.score_after == 0.72
    
    def test_node_to_dict(self):
        """Test converting node to dictionary."""
        node = RefinementNode(
            round_number=2,
            action="merge_duplicates",
            score_before=0.70,
            score_after=0.75,
            priority="medium",
        )
        data = node.to_dict()
        assert data["round"] == 2
        assert data["action"] == "merge_duplicates"
        assert data["score_before"] == 0.70
        assert data["score_after"] == 0.75
    
    def test_node_minimal(self):
        """Test node with only required fields."""
        node = RefinementNode(
            round_number=1,
            action="test_action",
            score_before=0.50,
        )
        assert node.score_after is None
        assert node.rationale == ""
        assert node.estimated_impact == 0.0


# =============================================================================
# Test Cases: Visualizer Initialization
# =============================================================================


class TestVisualizerInitialization:
    """Test visualizer initialization and setup."""
    
    def test_init_with_output_dir(self, output_dir: Path):
        """Test initialization with custom output directory."""
        viz = RefinementVisualizer(output_dir=output_dir)
        assert viz.output_dir == output_dir
        assert viz.output_dir.exists()
    
    def test_init_without_output_dir(self):
        """Test initialization with default output directory."""
        viz = RefinementVisualizer()
        assert viz.output_dir == Path.cwd()
    
    def test_init_creates_output_dir(self, tmp_path: Path):
        """Test that output directory is created if it doesn't exist."""
        new_dir = tmp_path / "new_viz_dir"
        assert not new_dir.exists()
        viz = RefinementVisualizer(output_dir=new_dir)
        assert new_dir.exists()
    
    def test_empty_nodes_on_init(self, visualizer: RefinementVisualizer):
        """Test that visualizer starts with no recorded nodes."""
        assert len(visualizer._nodes) == 0


# =============================================================================
# Test Cases: Recording Refinement Rounds
# =============================================================================


class TestRecordingRounds:
    """Test recording refinement rounds."""
    
    def test_add_simple_round(self, visualizer: RefinementVisualizer):
        """Test adding a simple refinement round."""
        visualizer.add_refinement_round(
            round_number=1,
            action="add_properties",
            score_before=0.65,
            score_after=0.72,
        )
        assert len(visualizer._nodes) == 1
        assert visualizer._nodes[0].round_number == 1
        assert visualizer._nodes[0].action == "add_properties"
    
    def test_add_round_with_strategy(self, visualizer: RefinementVisualizer, sample_strategy: Dict[str, Any]):
        """Test adding round with full strategy dict."""
        visualizer.add_refinement_round(
            round_number=1,
            action="add_properties",
            score_before=0.65,
            score_after=0.72,
            strategy=sample_strategy,
        )
        node = visualizer._nodes[0]
        assert node.rationale == sample_strategy["rationale"]
        assert node.priority == sample_strategy["priority"]
        assert node.estimated_impact == sample_strategy["estimated_impact"]
    
    def test_add_multiple_rounds(self, visualizer: RefinementVisualizer):
        """Test adding multiple refinement rounds."""
        visualizer.add_refinement_round(1, "add_properties", 0.65, 0.72)
        visualizer.add_refinement_round(2, "merge_duplicates", 0.72, 0.78)
        visualizer.add_refinement_round(3, "normalize_names", 0.78, 0.82)
        
        assert len(visualizer._nodes) == 3
        assert visualizer._nodes[0].action == "add_properties"
        assert visualizer._nodes[1].action == "merge_duplicates"
        assert visualizer._nodes[2].action == "normalize_names"
    
    def test_add_round_without_score_after(self, visualizer: RefinementVisualizer):
        """Test adding round without score_after (in-progress)."""
        visualizer.add_refinement_round(
            round_number=1,
            action="add_properties",
            score_before=0.65,
        )
        assert visualizer._nodes[0].score_after is None


# =============================================================================
# Test Cases: Decision Tree Generation
# =============================================================================


class TestDecisionTreeGeneration:
    """Test decision tree visualization."""
    
    @pytest.mark.skipif(not HAS_GRAPHVIZ, reason="graphviz not installed")
    def test_generate_tree_simple(self, visualizer: RefinementVisualizer):
        """Test generating basic decision tree."""
        visualizer.add_refinement_round(1, "add_properties", 0.65, 0.72)
        visualizer.add_refinement_round(2, "merge_duplicates", 0.72, 0.78)
        
        path = visualizer.generate_decision_tree(format="png")
        assert path is not None
        assert path.exists()
        assert path.suffix == ".png"
    
    @pytest.mark.skipif(not HAS_GRAPHVIZ, reason="graphviz not installed")
    def test_generate_tree_formats(self, visualizer: RefinementVisualizer):
        """Test generating tree in different formats."""
        visualizer.add_refinement_round(1, "add_properties", 0.65, 0.72)
        
        for fmt in ['png', 'svg', 'pdf']:
            path = visualizer.generate_decision_tree(filename=f"tree_{fmt}", format=fmt)
            assert path is not None
            assert path.suffix == f".{fmt}"
    
    @pytest.mark.skipif(not HAS_GRAPHVIZ, reason="graphviz not installed")
    def test_generate_tree_options(self, visualizer: RefinementVisualizer, sample_strategy: Dict[str, Any]):
        """Test tree generation with various options."""
        visualizer.add_refinement_round(1, "add_properties", 0.65, 0.72, sample_strategy)
        
        # With scores and impact
        path1 = visualizer.generate_decision_tree(show_scores=True, show_impact=True)
        assert path1 is not None
        
        # Without scores
        path2 = visualizer.generate_decision_tree(filename="tree_no_scores", show_scores=False)
        assert path2 is not None
    
    def test_generate_tree_without_graphviz(self, visualizer: RefinementVisualizer, monkeypatch):
        """Test graceful failure when graphviz not available."""
        visualizer.add_refinement_round(1, "add_properties", 0.65, 0.72)
        
        # Temporarily disable graphviz
        import ipfs_datasets_py.optimizers.graphrag.refinement_visualizer as viz_module
        original = viz_module.HAS_GRAPHVIZ
        monkeypatch.setattr(viz_module, "HAS_GRAPHVIZ", False)
        
        path = visualizer.generate_decision_tree()
        assert path is None
        
        # Restore
        monkeypatch.setattr(viz_module, "HAS_GRAPHVIZ", original)
    
    def test_generate_tree_empty_nodes(self, visualizer: RefinementVisualizer):
        """Test tree generation with no recorded nodes."""
        path = visualizer.generate_decision_tree()
        # Should return None or handle gracefully
        assert path is None


# =============================================================================
# Test Cases: Score Progression Chart
# =============================================================================


class TestScoreProgressionChart:
    """Test score progression visualization."""
    
    @pytest.mark.skipif(not HAS_MATPLOTLIB, reason="matplotlib not installed")
    def test_generate_chart_simple(self, visualizer: RefinementVisualizer):
        """Test generating basic score chart."""
        visualizer.add_refinement_round(1, "add_properties", 0.65, 0.72)
        visualizer.add_refinement_round(2, "merge_duplicates", 0.72, 0.78)
        
        path = visualizer.generate_score_progression_chart(format="png")
        assert path is not None
        assert path.exists()
        assert path.suffix == ".png"
    
    @pytest.mark.skipif(not HAS_MATPLOTLIB, reason="matplotlib not installed")
    def test_generate_chart_formats(self, visualizer: RefinementVisualizer):
        """Test chart in different formats."""
        visualizer.add_refinement_round(1, "add_properties", 0.65, 0.72)
        
        for fmt in ['png', 'svg', 'pdf']:
            path = visualizer.generate_score_progression_chart(filename=f"chart_{fmt}", format=fmt)
            assert path is not None
            assert path.suffix == f".{fmt}"
    
    def test_generate_chart_without_matplotlib(self, visualizer: RefinementVisualizer, monkeypatch):
        """Test graceful failure when matplotlib not available."""
        visualizer.add_refinement_round(1, "add_properties", 0.65, 0.72)
        
        # Temporarily disable matplotlib
        import ipfs_datasets_py.optimizers.graphrag.refinement_visualizer as viz_module
        original = viz_module.HAS_MATPLOTLIB
        monkeypatch.setattr(viz_module, "HAS_MATPLOTLIB", False)
        
        path = visualizer.generate_score_progression_chart()
        assert path is None
        
        # Restore
        monkeypatch.setattr(viz_module, "HAS_MATPLOTLIB", original)
    
    def test_generate_chart_empty_nodes(self, visualizer: RefinementVisualizer):
        """Test chart generation with no nodes."""
        path = visualizer.generate_score_progression_chart()
        assert path is None


# =============================================================================
# Test Cases: Strategy Comparison Matrix
# =============================================================================


class TestStrategyComparisonMatrix:
    """Test strategy comparison visualization."""
    
    @pytest.mark.skipif(not HAS_MATPLOTLIB, reason="matplotlib not installed")
    def test_generate_matrix(self, visualizer: RefinementVisualizer):
        """Test generating strategy comparison matrix."""
        strategies = [
            {"action": "add_properties", "priority": "high", "estimated_impact": 0.15},
            {"action": "merge_duplicates", "priority": "medium", "estimated_impact": 0.10},
            {"action": "normalize_names", "priority": "low", "estimated_impact": 0.05},
        ]
        
        path = visualizer.generate_strategy_comparison_matrix(strategies)
        assert path is not None
        assert path.exists()
        assert path.suffix == ".png"
    
    @pytest.mark.skipif(not HAS_MATPLOTLIB, reason="matplotlib not installed")
    def test_generate_matrix_formats(self, visualizer: RefinementVisualizer):
        """Test matrix in different formats."""
        strategies = [
            {"action": "add_properties", "priority": "high", "estimated_impact": 0.15},
        ]
        
        for fmt in ['png', 'svg', 'pdf']:
            path = visualizer.generate_strategy_comparison_matrix(strategies, filename=f"matrix_{fmt}", format=fmt)
            assert path is not None
            assert path.suffix == f".{fmt}"
    
    def test_generate_matrix_empty_strategies(self, visualizer: RefinementVisualizer):
        """Test matrix with no strategies."""
        path = visualizer.generate_strategy_comparison_matrix([])
        assert path is None


# =============================================================================
# Test Cases: Summary Report
# =============================================================================


class TestSummaryReport:
    """Test summary report generation."""
    
    def test_generate_report_simple(self, visualizer: RefinementVisualizer, output_dir: Path):
        """Test generating basic summary report."""
        visualizer.add_refinement_round(1, "add_properties", 0.65, 0.72)
        visualizer.add_refinement_round(2, "merge_duplicates", 0.72, 0.78)
        
        path = visualizer.generate_summary_report()
        assert path.exists()
        assert path.suffix == ".json"
        
        # Verify content
        with open(path) as f:
            report = json.load(f)
        
        assert report["total_rounds"] == 2
        assert len(report["refinement_tree"]) == 2
        assert "score_improvement" in report
        assert "actions_summary" in report
    
    def test_report_score_improvement(self, visualizer: RefinementVisualizer):
        """Test score improvement calculation in report."""
        visualizer.add_refinement_round(1, "add_properties", 0.65, 0.72)
        visualizer.add_refinement_round(2, "merge_duplicates", 0.72, 0.78)
        
        path = visualizer.generate_summary_report()
        with open(path) as f:
            report = json.load(f)
        
        improvement = report["score_improvement"]
        assert improvement["initial"] == 0.65
        assert improvement["final"] == 0.78
        assert improvement["delta"] == pytest.approx(0.13, abs=0.01)
    
    def test_report_actions_summary(self, visualizer: RefinementVisualizer):
        """Test action frequency summary in report."""
        visualizer.add_refinement_round(1, "add_properties", 0.65, 0.70)
        visualizer.add_refinement_round(2, "add_properties", 0.70, 0.75)
        visualizer.add_refinement_round(3, "merge_duplicates", 0.75, 0.80)
        
        path = visualizer.generate_summary_report()
        with open(path) as f:
            report = json.load(f)
        
        actions = report["actions_summary"]
        assert actions["add_properties"] == 2
        assert actions["merge_duplicates"] == 1
    
    def test_report_empty_rounds(self, visualizer: RefinementVisualizer):
        """Test report generation with no rounds."""
        path = visualizer.generate_summary_report()
        with open(path) as f:
            report = json.load(f)
        
        assert report["total_rounds"] == 0
        assert len(report["refinement_tree"]) == 0


# =============================================================================
# Test Cases: Utility Methods
# =============================================================================


class TestUtilityMethods:
    """Test visualizer utility methods."""
    
    def test_clear_nodes(self, visualizer: RefinementVisualizer):
        """Test clearing all recorded nodes."""
        visualizer.add_refinement_round(1, "add_properties", 0.65, 0.72)
        visualizer.add_refinement_round(2, "merge_duplicates", 0.72, 0.78)
        assert len(visualizer._nodes) == 2
        
        visualizer.clear()
        assert len(visualizer._nodes) == 0
    
    def test_calculate_score_improvement_empty(self, visualizer: RefinementVisualizer):
        """Test score improvement with no rounds."""
        improvement = visualizer._calculate_score_improvement()
        assert improvement["initial"] == 0.0
        assert improvement["final"] == 0.0
        assert improvement["delta"] == 0.0
    
    def test_summarize_actions(self, visualizer: RefinementVisualizer):
        """Test action summarization."""
        visualizer.add_refinement_round(1, "action_a", 0.65, 0.70)
        visualizer.add_refinement_round(2, "action_b", 0.70, 0.75)
        visualizer.add_refinement_round(3, "action_a", 0.75, 0.80)
        
        summary = visualizer._summarize_actions()
        assert summary["action_a"] == 2
        assert summary["action_b"] == 1


# =============================================================================
# Test Cases: Integration
# =============================================================================


class TestIntegrationVisualization:
    """Test high-level integration scenarios."""
    
    def test_visualize_refinement_cycle(self, sample_mediator_state: Dict[str, Any], output_dir: Path):
        """Test visualizing complete refinement cycle."""
        outputs = visualize_refinement_cycle(
            sample_mediator_state,
            output_dir=output_dir,
            formats=['json'],
        )
        
        assert 'report' in outputs
        assert outputs['report'].exists()
    
    @pytest.mark.skipif(not (HAS_GRAPHVIZ and HAS_MATPLOTLIB), reason="graphviz or matplotlib not installed")
    def test_visualize_all_formats(self, sample_mediator_state: Dict[str, Any], output_dir: Path):
        """Test generating all visualization formats."""
        outputs = visualize_refinement_cycle(
            sample_mediator_state,
            output_dir=output_dir,
            formats=['png', 'json'],
        )
        
        assert 'tree' in outputs
        assert 'chart' in outputs
        assert 'report' in outputs
    
    def test_visualize_empty_state(self, output_dir: Path):
        """Test visualizing empty mediator state."""
        empty_state = {
            "refinement_history": [],
            "critic_scores": [],
        }
        
        outputs = visualize_refinement_cycle(empty_state, output_dir=output_dir, formats=['json'])
        assert 'report' in outputs


# =============================================================================
# Test Cases: Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_add_round_negative_score(self, visualizer: RefinementVisualizer):
        """Test adding round with negative score (invalid but handled)."""
        visualizer.add_refinement_round(1, "test", -0.1, 0.0)
        assert visualizer._nodes[0].score_before == -0.1
    
    def test_add_round_score_above_one(self, visualizer: RefinementVisualizer):
        """Test adding round with score > 1.0."""
        visualizer.add_refinement_round(1, "test", 1.2, 1.5)
        assert visualizer._nodes[0].score_before == 1.2
    
    def test_generate_tree_single_round(self, visualizer: RefinementVisualizer):
        """Test tree generation with just one round."""
        visualizer.add_refinement_round(1, "add_properties", 0.65, 0.72)
        
        if HAS_GRAPHVIZ:
            path = visualizer.generate_decision_tree()
            assert path is not None
    
    def test_unicode_action_names(self, visualizer: RefinementVisualizer):
        """Test handling Unicode in action names."""
        visualizer.add_refinement_round(1, "添加_属性", 0.65, 0.72)
        assert visualizer._nodes[0].action == "添加_属性"
        
        path = visualizer.generate_summary_report()
        with open(path) as f:
            report = json.load(f)
        assert report["refinement_tree"][0]["action"] == "添加_属性"
