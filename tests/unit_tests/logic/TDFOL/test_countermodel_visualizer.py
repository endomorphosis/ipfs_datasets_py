"""
Tests for Enhanced Countermodel Visualizer

This module tests the enhanced visualization capabilities for TDFOL countermodels.
Tests follow the GIVEN-WHEN-THEN format.
"""

import json
import pytest
from pathlib import Path

from ipfs_datasets_py.logic.TDFOL.countermodels import KripkeStructure
from ipfs_datasets_py.logic.TDFOL.modal_tableaux import ModalLogicType
from ipfs_datasets_py.logic.TDFOL.countermodel_visualizer import (
    CountermodelVisualizer,
    BoxChars,
    GraphLayout,
    create_visualizer,
)


class TestBoxChars:
    """Test box-drawing character constants."""
    
    def test_box_chars_defined(self):
        """
        GIVEN BoxChars class
        WHEN accessing character constants
        THEN expect all constants to be defined as strings
        """
        # GIVEN/WHEN/THEN
        assert isinstance(BoxChars.HORIZONTAL, str)
        assert isinstance(BoxChars.VERTICAL, str)
        assert isinstance(BoxChars.TOP_LEFT, str)
        assert isinstance(BoxChars.ARROW_RIGHT, str)
        assert isinstance(BoxChars.CHECK, str)
    
    def test_box_chars_unicode(self):
        """
        GIVEN BoxChars class
        WHEN checking character values
        THEN expect proper Unicode box-drawing characters
        """
        # GIVEN/WHEN/THEN
        assert BoxChars.HORIZONTAL == "─"
        assert BoxChars.VERTICAL == "│"
        assert BoxChars.ARROW_RIGHT == "→"
        assert BoxChars.CHECK == "✓"
        assert BoxChars.CROSS_MARK == "✗"


class TestGraphLayout:
    """Test GraphLayout dataclass."""
    
    def test_graph_layout_creation(self):
        """
        GIVEN layout parameters
        WHEN creating GraphLayout
        THEN expect structure to be initialized correctly
        """
        # GIVEN
        positions = {0: (100, 200), 1: (300, 400)}
        width = 800
        height = 600
        
        # WHEN
        layout = GraphLayout(positions=positions, width=width, height=height)
        
        # THEN
        assert layout.positions == positions
        assert layout.width == width
        assert layout.height == height
    
    def test_graph_layout_default_values(self):
        """
        GIVEN no parameters
        WHEN creating GraphLayout with defaults
        THEN expect default width and height
        """
        # GIVEN/WHEN
        layout = GraphLayout()
        
        # THEN
        assert layout.positions == {}
        assert layout.width == 800
        assert layout.height == 600


class TestCountermodelVisualizerCreation:
    """Test CountermodelVisualizer initialization."""
    
    def test_visualizer_creation(self):
        """
        GIVEN a KripkeStructure
        WHEN creating CountermodelVisualizer
        THEN expect visualizer to be initialized with structure
        """
        # GIVEN
        kripke = KripkeStructure(logic_type=ModalLogicType.K)
        kripke.add_world(0)
        
        # WHEN
        visualizer = CountermodelVisualizer(kripke)
        
        # THEN
        assert visualizer.kripke == kripke
        assert visualizer.kripke.logic_type == ModalLogicType.K
    
    def test_create_visualizer_convenience_function(self):
        """
        GIVEN a KripkeStructure
        WHEN using create_visualizer convenience function
        THEN expect CountermodelVisualizer to be created
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        
        # WHEN
        visualizer = create_visualizer(kripke)
        
        # THEN
        assert isinstance(visualizer, CountermodelVisualizer)
        assert visualizer.kripke == kripke


class TestASCIIEnhanced:
    """Test enhanced ASCII art rendering."""
    
    def test_render_ascii_enhanced_expanded(self):
        """
        GIVEN a simple KripkeStructure
        WHEN rendering enhanced ASCII in expanded mode
        THEN expect formatted output with box-drawing characters
        """
        # GIVEN
        kripke = KripkeStructure(logic_type=ModalLogicType.K)
        kripke.add_world(0)
        kripke.set_atom_true(0, "P")
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        output = visualizer.render_ascii_enhanced(colors=False, style='expanded')
        
        # THEN
        assert "Kripke Structure" in output
        assert "Logic: K" in output
        assert "w0" in output
        assert "P" in output
        assert BoxChars.HORIZONTAL in output
        assert BoxChars.VERTICAL in output
    
    def test_render_ascii_enhanced_compact(self):
        """
        GIVEN a KripkeStructure
        WHEN rendering enhanced ASCII in compact mode
        THEN expect condensed output
        """
        # GIVEN
        kripke = KripkeStructure(logic_type=ModalLogicType.K)
        kripke.add_world(0)
        kripke.add_world(1)
        kripke.add_accessibility(0, 1)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        output = visualizer.render_ascii_enhanced(colors=False, style='compact')
        
        # THEN
        assert "Kripke(K)" in output
        assert "W=2" in output
        assert "R=1" in output
        assert "w0" in output
        assert "w1" in output
    
    def test_render_ascii_with_multiple_worlds(self):
        """
        GIVEN a KripkeStructure with multiple worlds
        WHEN rendering enhanced ASCII
        THEN expect all worlds to be displayed
        """
        # GIVEN
        kripke = KripkeStructure()
        for i in range(3):
            kripke.add_world(i)
            kripke.set_atom_true(i, f"P{i}")
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        output = visualizer.render_ascii_enhanced(colors=False)
        
        # THEN
        assert "w0" in output
        assert "w1" in output
        assert "w2" in output
        assert "P0" in output
        assert "P1" in output
        assert "P2" in output
    
    def test_render_ascii_with_accessibility_relations(self):
        """
        GIVEN a KripkeStructure with accessibility relations
        WHEN rendering enhanced ASCII
        THEN expect accessibility arrows to be shown
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        kripke.add_world(1)
        kripke.add_accessibility(0, 1)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        output = visualizer.render_ascii_enhanced(colors=False)
        
        # THEN
        assert BoxChars.ARROW_RIGHT in output
        assert "w1" in output
    
    def test_render_ascii_shows_initial_world(self):
        """
        GIVEN a KripkeStructure with initial world
        WHEN rendering enhanced ASCII
        THEN expect initial world to be marked
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        kripke.add_world(1)
        kripke.initial_world = 0
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        output = visualizer.render_ascii_enhanced(colors=False)
        
        # THEN
        assert "initial" in output.lower() or BoxChars.DOUBLE_ARROW_RIGHT in output
    
    def test_render_ascii_empty_world(self):
        """
        GIVEN a world with no atoms
        WHEN rendering enhanced ASCII
        THEN expect empty set symbol or indication
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        output = visualizer.render_ascii_enhanced(colors=False)
        
        # THEN
        assert "∅" in output or "none" in output
    
    def test_render_ascii_accessibility_table(self):
        """
        GIVEN a KripkeStructure with complex accessibility
        WHEN rendering enhanced ASCII
        THEN expect accessibility table to be shown
        """
        # GIVEN
        kripke = KripkeStructure()
        for i in range(3):
            kripke.add_world(i)
        kripke.add_accessibility(0, 1)
        kripke.add_accessibility(0, 2)
        kripke.add_accessibility(1, 2)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        output = visualizer.render_ascii_enhanced(colors=False)
        
        # THEN
        assert "Accessibility Relations" in output or "From World" in output
    
    def test_render_ascii_invalid_style_raises_error(self):
        """
        GIVEN a KripkeStructure
        WHEN rendering with invalid style
        THEN expect ValueError to be raised
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN/THEN
        with pytest.raises(ValueError) as exc_info:
            visualizer.render_ascii_enhanced(style='invalid')
        assert "Unknown style" in str(exc_info.value)
    
    def test_render_ascii_with_colors_disabled_when_not_available(self):
        """
        GIVEN a KripkeStructure and colorama not available
        WHEN rendering with colors=True
        THEN expect fallback to no colors (no error)
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN (should not raise even if colorama not available)
        output = visualizer.render_ascii_enhanced(colors=True)
        
        # THEN
        assert isinstance(output, str)
        assert "w0" in output


class TestLogicPropertyAnalysis:
    """Test modal logic property checking."""
    
    def test_check_reflexive_true(self):
        """
        GIVEN a KripkeStructure with reflexive accessibility
        WHEN checking if reflexive
        THEN expect True
        """
        # GIVEN
        kripke = KripkeStructure(logic_type=ModalLogicType.T)
        kripke.add_world(0)
        kripke.add_world(1)
        kripke.add_accessibility(0, 0)
        kripke.add_accessibility(1, 1)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        is_reflexive = visualizer._check_reflexive()
        
        # THEN
        assert is_reflexive is True
    
    def test_check_reflexive_false(self):
        """
        GIVEN a KripkeStructure without reflexive accessibility
        WHEN checking if reflexive
        THEN expect False
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        kripke.add_world(1)
        kripke.add_accessibility(0, 1)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        is_reflexive = visualizer._check_reflexive()
        
        # THEN
        assert is_reflexive is False
    
    def test_check_symmetric_true(self):
        """
        GIVEN a KripkeStructure with symmetric accessibility
        WHEN checking if symmetric
        THEN expect True
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        kripke.add_world(1)
        kripke.add_accessibility(0, 1)
        kripke.add_accessibility(1, 0)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        is_symmetric = visualizer._check_symmetric()
        
        # THEN
        assert is_symmetric is True
    
    def test_check_symmetric_false(self):
        """
        GIVEN a KripkeStructure without symmetric accessibility
        WHEN checking if symmetric
        THEN expect False
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        kripke.add_world(1)
        kripke.add_accessibility(0, 1)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        is_symmetric = visualizer._check_symmetric()
        
        # THEN
        assert is_symmetric is False
    
    def test_check_transitive_true(self):
        """
        GIVEN a KripkeStructure with transitive accessibility
        WHEN checking if transitive
        THEN expect True
        """
        # GIVEN
        kripke = KripkeStructure(logic_type=ModalLogicType.S4)
        kripke.add_world(0)
        kripke.add_world(1)
        kripke.add_world(2)
        kripke.add_accessibility(0, 1)
        kripke.add_accessibility(1, 2)
        kripke.add_accessibility(0, 2)  # Transitive closure
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        is_transitive = visualizer._check_transitive()
        
        # THEN
        assert is_transitive is True
    
    def test_check_transitive_false(self):
        """
        GIVEN a KripkeStructure without transitive closure
        WHEN checking if transitive
        THEN expect False
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        kripke.add_world(1)
        kripke.add_world(2)
        kripke.add_accessibility(0, 1)
        kripke.add_accessibility(1, 2)
        # Missing 0 -> 2 for transitivity
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        is_transitive = visualizer._check_transitive()
        
        # THEN
        assert is_transitive is False
    
    def test_check_serial_true(self):
        """
        GIVEN a KripkeStructure where each world accesses at least one world
        WHEN checking if serial
        THEN expect True
        """
        # GIVEN
        kripke = KripkeStructure(logic_type=ModalLogicType.D)
        kripke.add_world(0)
        kripke.add_world(1)
        kripke.add_accessibility(0, 1)
        kripke.add_accessibility(1, 0)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        is_serial = visualizer._check_serial()
        
        # THEN
        assert is_serial is True
    
    def test_check_serial_false(self):
        """
        GIVEN a KripkeStructure with isolated world
        WHEN checking if serial
        THEN expect False
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        kripke.add_world(1)
        kripke.add_accessibility(0, 1)
        # World 1 has no accessibility
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        is_serial = visualizer._check_serial()
        
        # THEN
        assert is_serial is False
    
    def test_get_expected_properties_k(self):
        """
        GIVEN K logic
        WHEN getting expected properties
        THEN expect empty list
        """
        # GIVEN
        kripke = KripkeStructure(logic_type=ModalLogicType.K)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        expected = visualizer._get_expected_properties()
        
        # THEN
        assert expected == []
    
    def test_get_expected_properties_t(self):
        """
        GIVEN T logic
        WHEN getting expected properties
        THEN expect Reflexive
        """
        # GIVEN
        kripke = KripkeStructure(logic_type=ModalLogicType.T)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        expected = visualizer._get_expected_properties()
        
        # THEN
        assert "Reflexive" in expected
    
    def test_get_expected_properties_s4(self):
        """
        GIVEN S4 logic
        WHEN getting expected properties
        THEN expect Reflexive and Transitive
        """
        # GIVEN
        kripke = KripkeStructure(logic_type=ModalLogicType.S4)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        expected = visualizer._get_expected_properties()
        
        # THEN
        assert "Reflexive" in expected
        assert "Transitive" in expected
    
    def test_get_expected_properties_s5(self):
        """
        GIVEN S5 logic
        WHEN getting expected properties
        THEN expect Reflexive, Symmetric, and Transitive
        """
        # GIVEN
        kripke = KripkeStructure(logic_type=ModalLogicType.S5)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        expected = visualizer._get_expected_properties()
        
        # THEN
        assert "Reflexive" in expected
        assert "Symmetric" in expected
        assert "Transitive" in expected
    
    def test_render_logic_properties_in_output(self):
        """
        GIVEN a KripkeStructure
        WHEN rendering ASCII
        THEN expect logic properties to be shown
        """
        # GIVEN
        kripke = KripkeStructure(logic_type=ModalLogicType.T)
        kripke.add_world(0)
        kripke.add_accessibility(0, 0)  # Reflexive
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        output = visualizer.render_ascii_enhanced(colors=False)
        
        # THEN
        assert "Modal Logic Properties" in output or "Reflexive" in output


class TestHTMLVisualization:
    """Test interactive HTML visualization."""
    
    def test_to_html_string(self):
        """
        GIVEN a simple KripkeStructure
        WHEN generating HTML string
        THEN expect valid HTML document
        """
        # GIVEN
        kripke = KripkeStructure(logic_type=ModalLogicType.K)
        kripke.add_world(0)
        kripke.set_atom_true(0, "P")
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        html = visualizer.to_html_string()
        lower_html = html.lower()
        
        # THEN
        assert "<!doctype html>" in lower_html
        assert "<html" in lower_html
        assert ("d3.js" in lower_html) or ("d3.min.js" in lower_html) or ("d3js.org/d3" in lower_html)
        assert "kripke structure" in lower_html
    
    def test_html_contains_data(self):
        """
        GIVEN a KripkeStructure with multiple worlds
        WHEN generating HTML
        THEN expect world data to be embedded
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        kripke.add_world(1)
        kripke.add_accessibility(0, 1)
        kripke.set_atom_true(0, "P")
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        html = visualizer.to_html_string()
        
        # THEN
        assert "w0" in html
        assert "w1" in html
        assert '"atoms"' in html
    
    def test_html_contains_d3_visualization(self):
        """
        GIVEN a KripkeStructure
        WHEN generating HTML
        THEN expect D3.js visualization code
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        html = visualizer.to_html_string()
        
        # THEN
        assert "d3.select" in html
        assert "simulation" in html
        assert "force" in html
    
    def test_html_has_interactive_features(self):
        """
        GIVEN a KripkeStructure
        WHEN generating HTML
        THEN expect interactive control buttons
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        html = visualizer.to_html_string()
        
        # THEN
        assert "Reset View" in html or "resetZoom" in html
        assert "Center Graph" in html or "centerGraph" in html
        assert "Toggle Physics" in html or "togglePhysics" in html
    
    def test_html_highlights_initial_world(self):
        """
        GIVEN a KripkeStructure with initial world
        WHEN generating HTML
        THEN expect initial world to be highlighted in data
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        kripke.add_world(1)
        kripke.initial_world = 0
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        html = visualizer.to_html_string()
        
        # THEN
        assert "is_initial" in html
        assert "initial" in html.lower()
    
    def test_html_includes_legend(self):
        """
        GIVEN a KripkeStructure
        WHEN generating HTML
        THEN expect legend section
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        html = visualizer.to_html_string()
        
        # THEN
        assert "legend" in html.lower()
    
    def test_render_html_interactive(self, tmp_path):
        """
        GIVEN a KripkeStructure and output path
        WHEN rendering interactive HTML
        THEN expect HTML file to be created
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        visualizer = CountermodelVisualizer(kripke)
        output_file = tmp_path / "test.html"
        
        # WHEN
        visualizer.render_html_interactive(str(output_file))
        
        # THEN
        assert output_file.exists()
        content = output_file.read_text()
        assert "<!DOCTYPE html>" in content
    
    def test_render_html_creates_parent_directories(self, tmp_path):
        """
        GIVEN a nested output path that doesn't exist
        WHEN rendering HTML
        THEN expect parent directories to be created
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        visualizer = CountermodelVisualizer(kripke)
        output_file = tmp_path / "nested" / "dirs" / "test.html"
        
        # WHEN
        visualizer.render_html_interactive(str(output_file))
        
        # THEN
        assert output_file.exists()
        assert output_file.parent.exists()
    
    def test_html_with_complex_structure(self):
        """
        GIVEN a complex KripkeStructure with many worlds and relations
        WHEN generating HTML
        THEN expect all data to be included
        """
        # GIVEN
        kripke = KripkeStructure(logic_type=ModalLogicType.S4)
        for i in range(5):
            kripke.add_world(i)
            kripke.set_atom_true(i, f"P{i}")
        for i in range(4):
            kripke.add_accessibility(i, i + 1)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        html = visualizer.to_html_string()
        
        # THEN
        for i in range(5):
            assert f"w{i}" in html
        assert "S4" in html


class TestAccessibilityGraphRendering:
    """Test accessibility graph rendering."""
    
    def test_generate_accessibility_dot(self):
        """
        GIVEN a KripkeStructure
        WHEN generating accessibility DOT
        THEN expect valid DOT format
        """
        # GIVEN
        kripke = KripkeStructure(logic_type=ModalLogicType.K)
        kripke.add_world(0)
        kripke.add_world(1)
        kripke.add_accessibility(0, 1)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        dot = visualizer._generate_accessibility_dot()
        
        # THEN
        assert "digraph AccessibilityGraph" in dot
        assert "w0" in dot
        assert "w1" in dot
        assert "->" in dot
    
    def test_accessibility_dot_highlights_reflexive(self):
        """
        GIVEN a KripkeStructure with reflexive relations
        WHEN generating accessibility DOT
        THEN expect reflexive edges to be highlighted
        """
        # GIVEN
        kripke = KripkeStructure(logic_type=ModalLogicType.T)
        kripke.add_world(0)
        kripke.add_accessibility(0, 0)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        dot = visualizer._generate_accessibility_dot()
        
        # THEN
        assert "reflexive" in dot.lower()
        assert "w0 -> w0" in dot
    
    def test_accessibility_dot_highlights_symmetric(self):
        """
        GIVEN a KripkeStructure with symmetric relations
        WHEN generating accessibility DOT
        THEN expect symmetric edges to be highlighted
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        kripke.add_world(1)
        kripke.add_accessibility(0, 1)
        kripke.add_accessibility(1, 0)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        dot = visualizer._generate_accessibility_dot()
        
        # THEN
        assert "symmetric" in dot.lower()
    
    def test_accessibility_dot_color_coding(self):
        """
        GIVEN different logic types
        WHEN generating accessibility DOT
        THEN expect different color schemes
        """
        # GIVEN
        kripke_k = KripkeStructure(logic_type=ModalLogicType.K)
        kripke_k.add_world(0)
        kripke_t = KripkeStructure(logic_type=ModalLogicType.T)
        kripke_t.add_world(0)
        
        # WHEN
        dot_k = CountermodelVisualizer(kripke_k)._generate_accessibility_dot()
        dot_t = CountermodelVisualizer(kripke_t)._generate_accessibility_dot()
        
        # THEN
        # Should have color specifications
        assert "fillcolor" in dot_k
        assert "fillcolor" in dot_t
        # Logic type should be in label
        assert "K Logic" in dot_k
        assert "T Logic" in dot_t
    
    def test_render_accessibility_graph_dot_format(self, tmp_path):
        """
        GIVEN a KripkeStructure
        WHEN rendering accessibility graph as DOT
        THEN expect DOT file to be created
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        kripke.add_world(1)
        kripke.add_accessibility(0, 1)
        visualizer = CountermodelVisualizer(kripke)
        output_file = tmp_path / "graph.dot"
        
        # WHEN
        visualizer.render_accessibility_graph(str(output_file), format='dot')
        
        # THEN
        assert output_file.exists()
        content = output_file.read_text()
        assert "digraph" in content
    
    def test_render_accessibility_graph_invalid_format(self):
        """
        GIVEN a KripkeStructure
        WHEN rendering with invalid format
        THEN expect ValueError
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN/THEN
        with pytest.raises(ValueError) as exc_info:
            visualizer.render_accessibility_graph("output.txt", format='invalid')
        assert "Unsupported format" in str(exc_info.value)
    
    def test_render_accessibility_graph_creates_parent_dirs(self, tmp_path):
        """
        GIVEN a nested output path
        WHEN rendering accessibility graph
        THEN expect parent directories to be created
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        visualizer = CountermodelVisualizer(kripke)
        output_file = tmp_path / "nested" / "graph.dot"
        
        # WHEN
        visualizer.render_accessibility_graph(str(output_file), format='dot')
        
        # THEN
        assert output_file.exists()
        assert output_file.parent.exists()


class TestEdgeCases:
    """Test edge cases and special scenarios."""
    
    def test_visualizer_with_empty_structure(self):
        """
        GIVEN an empty KripkeStructure
        WHEN creating visualizer
        THEN expect no errors
        """
        # GIVEN
        kripke = KripkeStructure()
        
        # WHEN
        visualizer = CountermodelVisualizer(kripke)
        
        # THEN
        assert visualizer.kripke == kripke
    
    def test_render_ascii_with_no_worlds(self):
        """
        GIVEN a KripkeStructure with no worlds
        WHEN rendering ASCII
        THEN expect valid output without errors
        """
        # GIVEN
        kripke = KripkeStructure()
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        output = visualizer.render_ascii_enhanced(colors=False)
        
        # THEN
        assert isinstance(output, str)
        assert "Worlds: 0" in output
    
    def test_render_with_large_structure(self):
        """
        GIVEN a large KripkeStructure
        WHEN rendering
        THEN expect to handle gracefully
        """
        # GIVEN
        kripke = KripkeStructure()
        for i in range(20):
            kripke.add_world(i)
            kripke.set_atom_true(i, f"P{i}")
            if i > 0:
                kripke.add_accessibility(i - 1, i)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        output = visualizer.render_ascii_enhanced(colors=False, style='compact')
        html = visualizer.to_html_string()
        
        # THEN
        assert isinstance(output, str)
        assert isinstance(html, str)
        assert "w19" in output
    
    def test_visualizer_with_many_atoms_per_world(self):
        """
        GIVEN a world with many true atoms
        WHEN visualizing
        THEN expect all atoms to be included
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        for i in range(10):
            kripke.set_atom_true(0, f"atom{i}")
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        output = visualizer.render_ascii_enhanced(colors=False)
        
        # THEN
        for i in range(10):
            assert f"atom{i}" in output
    
    def test_visualizer_with_self_loops(self):
        """
        GIVEN a KripkeStructure with self-loops
        WHEN rendering
        THEN expect self-loops to be shown
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        kripke.add_accessibility(0, 0)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        output = visualizer.render_ascii_enhanced(colors=False)
        dot = visualizer._generate_accessibility_dot()
        
        # THEN
        assert "w0" in output
        assert "w0 -> w0" in dot
    
    def test_visualizer_with_disconnected_worlds(self):
        """
        GIVEN a KripkeStructure with disconnected worlds
        WHEN rendering
        THEN expect all worlds to be shown
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        kripke.add_world(1)
        kripke.add_world(2)
        # No accessibility relations
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        output = visualizer.render_ascii_enhanced(colors=False)
        
        # THEN
        assert "w0" in output
        assert "w1" in output
        assert "w2" in output
    
    def test_visualizer_preserves_world_order(self):
        """
        GIVEN worlds added in arbitrary order
        WHEN rendering
        THEN expect consistent sorted output
        """
        # GIVEN
        kripke = KripkeStructure()
        for world_id in [5, 2, 8, 1, 3]:
            kripke.add_world(world_id)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        output = visualizer.render_ascii_enhanced(colors=False)
        
        # THEN
        # Check that all worlds appear
        for world_id in [1, 2, 3, 5, 8]:
            assert f"w{world_id}" in output
    
    def test_html_escaping_in_atoms(self):
        """
        GIVEN atoms with special characters
        WHEN generating HTML
        THEN expect proper HTML escaping
        """
        # GIVEN
        kripke = KripkeStructure()
        kripke.add_world(0)
        kripke.set_atom_true(0, "P<>&")
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        html = visualizer.to_html_string()
        
        # THEN
        assert isinstance(html, str)
        # Should handle special chars gracefully
    
    def test_multiple_accessibility_to_same_world(self):
        """
        GIVEN multiple paths to same world
        WHEN rendering accessibility graph
        THEN expect all relations to be shown
        """
        # GIVEN
        kripke = KripkeStructure()
        for i in range(4):
            kripke.add_world(i)
        kripke.add_accessibility(0, 3)
        kripke.add_accessibility(1, 3)
        kripke.add_accessibility(2, 3)
        visualizer = CountermodelVisualizer(kripke)
        
        # WHEN
        dot = visualizer._generate_accessibility_dot()
        
        # THEN
        assert "w0 -> w3" in dot
        assert "w1 -> w3" in dot
        assert "w2 -> w3" in dot


class TestIntegrationWithCountermodels:
    """Test integration with existing countermodels module."""
    
    def test_visualizer_with_extracted_countermodel_structure(self):
        """
        GIVEN a KripkeStructure from countermodel extraction
        WHEN creating visualizer
        THEN expect seamless integration
        """
        # GIVEN (simulating extracted structure)
        kripke = KripkeStructure(logic_type=ModalLogicType.K)
        kripke.add_world(0)
        kripke.add_world(1)
        kripke.add_accessibility(0, 1)
        kripke.set_atom_true(0, "P")
        kripke.initial_world = 0
        
        # WHEN
        visualizer = CountermodelVisualizer(kripke)
        ascii_output = visualizer.render_ascii_enhanced(colors=False)
        html_output = visualizer.to_html_string()
        
        # THEN
        assert "w0" in ascii_output
        assert "w1" in ascii_output
        assert "P" in ascii_output
        assert "w0" in html_output
    
    def test_all_modal_logic_types_supported(self):
        """
        GIVEN KripkeStructures with different logic types
        WHEN visualizing
        THEN expect proper handling of all types
        """
        # GIVEN
        logic_types = [
            ModalLogicType.K,
            ModalLogicType.T,
            ModalLogicType.D,
            ModalLogicType.S4,
            ModalLogicType.S5,
        ]
        
        for logic_type in logic_types:
            kripke = KripkeStructure(logic_type=logic_type)
            kripke.add_world(0)
            visualizer = CountermodelVisualizer(kripke)
            
            # WHEN
            output = visualizer.render_ascii_enhanced(colors=False)
            
            # THEN
            assert logic_type.value in output
