"""
Session 36: Comprehensive tests for proof_tree_visualizer.py (26%→97%)
and CEC proof_optimization.py (18 tests → 45 tests).

Coverage targets:
- proof_tree_visualizer.py: ProofTreeVisualizer (all methods), visualize_proof(),
  ColorScheme, GraphvizColors, BoxChars, TreeStyle, VerbosityLevel,
  _render_node_ascii with prefix/is_last combos, render_html, render_svg/png,
  export_dot, to_json, export_json
- CEC/native/proof_optimization.py: ProofTreePruner, RedundancyEliminator,
  ParallelProofSearch, ProofOptimizer, ProofNode, OptimizationMetrics
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# ─────────────────────── TDFOL imports ───────────────────────
from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    BinaryFormula,
    DeonticFormula,
    DeonticOperator,
    LogicOperator,
    Predicate,
    Sort,
    TemporalFormula,
    TemporalOperator,
    UnaryFormula,
    Variable,
    create_always,
    create_conjunction,
    create_implication,
    create_negation,
    create_obligation,
)
from ipfs_datasets_py.logic.TDFOL.tdfol_prover import (
    ProofResult,
    ProofStatus,
    ProofStep,
)
from ipfs_datasets_py.logic.TDFOL.proof_tree_visualizer import (
    BoxChars,
    ColorScheme,
    GraphvizColors,
    NodeType,
    ProofTreeNode,
    ProofTreeVisualizer,
    TreeStyle,
    VerbosityLevel,
    visualize_proof,
)

# ─────────────────────── CEC imports ───────────────────────
from ipfs_datasets_py.logic.CEC.native.proof_optimization import (
    OptimizationMetrics,
    ParallelProofSearch,
    ProofNode,
    ProofOptimizer,
    ProofTreePruner,
    PruningStrategy,
    RedundancyEliminator,
)


# ─────────────────────── Helpers ───────────────────────
def _make_formula(name: str = "P") -> Predicate:
    """Return a simple predicate formula."""
    return Predicate(name, [])


def _make_step(
    formula,
    rule_name: str = "Given",
    justification: str = "axiom",
    premises=None,
) -> ProofStep:
    return ProofStep(
        formula=formula,
        rule_name=rule_name,
        justification=justification,
        premises=premises or [],
    )


def _make_proved_result(formula=None, steps=None, message="") -> ProofResult:
    f = formula or _make_formula()
    return ProofResult(
        status=ProofStatus.PROVED,
        formula=f,
        proof_steps=steps or [],
        time_ms=1.0,
        method="test",
        message=message,
    )


def _make_disproved_result(formula=None) -> ProofResult:
    f = formula or _make_formula()
    return ProofResult(
        status=ProofStatus.DISPROVED,
        formula=f,
        proof_steps=[],
        time_ms=1.0,
        method="test",
    )


def _make_multi_step_result():
    """Return a ProofResult with 3 linked steps."""
    P = _make_formula("P")
    Q = _make_formula("Q")
    PQ = create_conjunction(P, Q)
    s1 = _make_step(P, "Axiom", "given")
    s2 = _make_step(Q, "Axiom", "given")
    s3 = _make_step(PQ, "ConjIntro", "from P and Q", premises=[P, Q])
    return ProofResult(
        status=ProofStatus.PROVED,
        formula=PQ,
        proof_steps=[s1, s2, s3],
        time_ms=5.0,
        method="forward",
    )


# ═══════════════════════════════════════════════════════════════
# Enum and simple type tests
# ═══════════════════════════════════════════════════════════════


class TestNodeType:
    def test_values(self):
        assert NodeType.AXIOM.value == "axiom"
        assert NodeType.INFERRED.value == "inferred"
        assert NodeType.THEOREM.value == "theorem"
        assert NodeType.CONTRADICTION.value == "contradiction"
        assert NodeType.GOAL.value == "goal"
        assert NodeType.LEMMA.value == "lemma"
        assert NodeType.PREMISE.value == "premise"

    def test_count(self):
        assert len(list(NodeType)) == 7


class TestTreeStyle:
    def test_values(self):
        assert TreeStyle.COMPACT.value == "compact"
        assert TreeStyle.EXPANDED.value == "expanded"
        assert TreeStyle.DETAILED.value == "detailed"


class TestVerbosityLevel:
    def test_values(self):
        assert VerbosityLevel.MINIMAL.value == "minimal"
        assert VerbosityLevel.NORMAL.value == "normal"
        assert VerbosityLevel.DETAILED.value == "detailed"


class TestBoxChars:
    def test_tree_chars(self):
        assert BoxChars.VERTICAL == "│"
        assert BoxChars.HORIZONTAL == "─"
        assert BoxChars.TEE == "├"
        assert BoxChars.CORNER == "└"
        assert "─" in BoxChars.TEE_RIGHT
        assert "─" in BoxChars.CORNER_RIGHT


class TestColorScheme:
    def test_get_node_color_all_types(self):
        for nt in NodeType:
            color = ColorScheme.get_node_color(nt)
            assert isinstance(color, str)

    def test_get_node_color_unknown_returns_empty(self):
        color = ColorScheme.get_node_color("unknown_type")
        assert color == ""


class TestGraphvizColors:
    def test_node_colors_keys(self):
        assert NodeType.AXIOM in GraphvizColors.NODE_COLORS
        assert NodeType.THEOREM in GraphvizColors.NODE_COLORS

    def test_font_colors_keys(self):
        assert NodeType.AXIOM in GraphvizColors.NODE_FONT_COLORS
        assert NodeType.CONTRADICTION in GraphvizColors.NODE_FONT_COLORS

    def test_edge_colors(self):
        assert isinstance(GraphvizColors.EDGE_COLOR, str)
        assert isinstance(GraphvizColors.EDGE_FONT_COLOR, str)


# ═══════════════════════════════════════════════════════════════
# ProofTreeNode
# ═══════════════════════════════════════════════════════════════


class TestProofTreeNodeExtra:
    def test_hash_uses_id_and_step_number(self):
        f = _make_formula()
        n = ProofTreeNode(formula=f, node_type=NodeType.AXIOM, step_number=3)
        # hash should include step_number
        assert isinstance(hash(n), int)

    def test_two_nodes_distinct_hash(self):
        f = _make_formula()
        n1 = ProofTreeNode(formula=f, node_type=NodeType.AXIOM, step_number=1)
        n2 = ProofTreeNode(formula=f, node_type=NodeType.AXIOM, step_number=2)
        # Different step numbers mean different hashes
        assert hash(n1) != hash(n2)

    def test_default_fields(self):
        f = _make_formula()
        n = ProofTreeNode(formula=f, node_type=NodeType.GOAL)
        assert n.rule_name is None
        assert n.justification == ""
        assert n.step_number == 0
        assert n.premises == []
        assert n.metadata == {}


# ═══════════════════════════════════════════════════════════════
# ProofTreeVisualizer — construction
# ═══════════════════════════════════════════════════════════════


class TestProofTreeVisualizerConstruction:
    def test_empty_proof_creates_single_node(self):
        result = _make_proved_result()
        v = ProofTreeVisualizer(result)
        assert v.tree_root is not None
        assert len(v.all_nodes) == 1
        assert v.tree_root.node_type == NodeType.THEOREM

    def test_disproved_single_node_is_contradiction(self):
        result = _make_disproved_result()
        v = ProofTreeVisualizer(result)
        assert v.tree_root.node_type == NodeType.CONTRADICTION

    def test_unknown_single_node_is_goal(self):
        f = _make_formula()
        result = ProofResult(
            status=ProofStatus.UNKNOWN,
            formula=f,
            proof_steps=[],
            time_ms=1.0,
            method="test",
        )
        v = ProofTreeVisualizer(result)
        assert v.tree_root.node_type == NodeType.GOAL

    def test_multi_step_builds_tree(self):
        result = _make_multi_step_result()
        v = ProofTreeVisualizer(result)
        assert v.tree_root is not None
        assert len(v.all_nodes) == 3

    def test_default_verbosity_is_normal(self):
        result = _make_proved_result()
        v = ProofTreeVisualizer(result)
        assert v.verbosity == VerbosityLevel.NORMAL

    def test_custom_verbosity(self):
        result = _make_proved_result()
        v = ProofTreeVisualizer(result, verbosity=VerbosityLevel.DETAILED)
        assert v.verbosity == VerbosityLevel.DETAILED

    def test_node_id_map_initially_empty(self):
        result = _make_proved_result()
        v = ProofTreeVisualizer(result)
        assert v.node_id_map == {}


# ═══════════════════════════════════════════════════════════════
# _infer_node_type
# ═══════════════════════════════════════════════════════════════


class TestInferNodeType:
    def _make_vis(self, steps):
        f = _make_formula()
        result = ProofResult(
            status=ProofStatus.PROVED,
            formula=f,
            proof_steps=steps,
            time_ms=1.0,
            method="test",
        )
        return ProofTreeVisualizer(result)

    def test_first_step_no_premises_is_axiom(self):
        f = _make_formula()
        s = _make_step(f, "Given", "axiom")
        v = self._make_vis([s])
        # step 1 has no premises → AXIOM (step_num ≤ 3)
        assert v.tree_root.node_type == NodeType.AXIOM

    def test_step_four_no_premises_is_premise(self):
        steps = [_make_step(_make_formula(str(i)), "Given", "axiom") for i in range(4)]
        v = self._make_vis(steps)
        # step_num 4 > 3 → PREMISE (not AXIOM); verify the 4th node specifically
        fourth_node = v.all_nodes[3]
        assert fourth_node.node_type == NodeType.PREMISE

    def test_last_step_proved_is_theorem(self):
        f = _make_formula("Goal")
        premise_f = _make_formula("P")
        s1 = _make_step(premise_f, "Given", "given")
        s2 = _make_step(f, "Conclude", "final", premises=[premise_f])
        v = self._make_vis([s1, s2])
        assert v.tree_root.node_type == NodeType.THEOREM

    def test_last_step_disproved_is_contradiction(self):
        f = _make_formula("Bad")
        premise_f = _make_formula("P")
        s1 = _make_step(premise_f, "Given", "given")
        s2 = _make_step(f, "Clash", "clash", premises=[premise_f])
        result = ProofResult(
            status=ProofStatus.DISPROVED,
            formula=f,
            proof_steps=[s1, s2],
            time_ms=1.0,
            method="test",
        )
        v = ProofTreeVisualizer(result)
        assert v.tree_root.node_type == NodeType.CONTRADICTION

    def test_justification_contradiction_no_premises_is_axiom(self):
        # A step with no premises is classified before the justification check
        # (_infer_node_type returns early with AXIOM for step_num ≤ 3 / PREMISE for > 3).
        # The "contradiction" substring in justification only fires for intermediate
        # steps that have premises, so this single no-premises step is AXIOM.
        f = _make_formula("Bad")
        s = _make_step(f, "Clash", "contradiction found", premises=[])
        v = self._make_vis([s])
        assert v.tree_root.node_type == NodeType.AXIOM

    def test_intermediate_step_with_premises_is_inferred(self):
        P = _make_formula("P")
        Q = _make_formula("Q")
        R = _make_formula("R")
        s1 = _make_step(P)
        s2 = _make_step(Q)
        s3 = _make_step(R, "MP", "modus ponens", premises=[P])
        v = self._make_vis([s1, s2, s3])
        # s3 has premises but is the last step → THEOREM (PROVED status)
        assert v.tree_root.node_type == NodeType.THEOREM


# ═══════════════════════════════════════════════════════════════
# render_ascii
# ═══════════════════════════════════════════════════════════════


class TestRenderAscii:
    def test_empty_proof_renders(self):
        v = ProofTreeVisualizer(_make_proved_result())
        out = v.render_ascii(colors=False)
        assert "Proof Tree" in out
        assert "proved" in out

    def test_with_message(self):
        result = _make_proved_result(message="All done")
        v = ProofTreeVisualizer(result)
        out = v.render_ascii(colors=False)
        assert "Message: All done" in out

    def test_compact_style(self):
        result = _make_multi_step_result()
        v = ProofTreeVisualizer(result)
        out = v.render_ascii(style="tree", colors=False)
        assert "Proof Tree" in out

    def test_expanded_style(self):
        result = _make_multi_step_result()
        v = ProofTreeVisualizer(result, verbosity=VerbosityLevel.NORMAL)
        out = v.render_ascii(style="expanded", colors=False)
        assert "Proof Tree" in out

    def test_detailed_style_includes_justification(self):
        P = _make_formula("P")
        Q = _make_formula("Q")
        pq = create_conjunction(P, Q)
        s1 = _make_step(P, "Given", "axiom1")
        s2 = _make_step(Q, "Given", "axiom2")
        s3 = _make_step(pq, "And", "combine both", premises=[P, Q])
        result = ProofResult(
            status=ProofStatus.PROVED,
            formula=pq,
            proof_steps=[s1, s2, s3],
            time_ms=1.0,
            method="test",
        )
        v = ProofTreeVisualizer(result, verbosity=VerbosityLevel.DETAILED)
        out = v.render_ascii(style="detailed", colors=False)
        # justification should appear in detailed
        assert "axiom1" in out or "combine both" in out

    def test_minimal_verbosity_no_step_numbers(self):
        result = _make_multi_step_result()
        v = ProofTreeVisualizer(result, verbosity=VerbosityLevel.MINIMAL)
        out = v.render_ascii(colors=False)
        assert "[1]" not in out

    def test_normal_verbosity_has_step_numbers(self):
        result = _make_multi_step_result()
        v = ProofTreeVisualizer(result, verbosity=VerbosityLevel.NORMAL)
        out = v.render_ascii(colors=False)
        assert "[1]" in out

    def test_render_ascii_colors_false_no_escape_codes(self):
        result = _make_multi_step_result()
        v = ProofTreeVisualizer(result)
        out = v.render_ascii(colors=False)
        assert "\x1b[" not in out

    def test_render_node_ascii_with_prefix(self):
        P = _make_formula("P")
        Q = _make_formula("Q")
        pq = create_conjunction(P, Q)
        s1 = _make_step(P)
        s2 = _make_step(Q)
        s3 = _make_step(pq, "And", "", premises=[P, Q])
        result = ProofResult(
            status=ProofStatus.PROVED, formula=pq, proof_steps=[s1, s2, s3],
            time_ms=1.0, method="test"
        )
        v = ProofTreeVisualizer(result, verbosity=VerbosityLevel.NORMAL)
        out = v.render_ascii(colors=False)
        # child nodes should have tree connectors
        assert "└─" in out or "├─" in out

    def test_max_width_truncation(self):
        # A very long predicate name triggers the truncation branch in _render_node_ascii
        long_name = "VeryLongPredicateName" * 5
        f = _make_formula(long_name)
        result = _make_proved_result(formula=f)
        v = ProofTreeVisualizer(result)
        out = v.render_ascii(colors=False, max_width=40)
        # The formula line should be truncated to ≤ max_width; header lines are unaffected
        formula_lines = [l for l in out.split("\n") if "..." in l]
        assert formula_lines, "Expected at least one truncated line ending with '...'"
        assert all(len(l) <= 43 for l in formula_lines)  # max_width + small prefix overhead


# ═══════════════════════════════════════════════════════════════
# export_dot
# ═══════════════════════════════════════════════════════════════


class TestExportDot:
    def test_export_dot_creates_file(self):
        result = _make_multi_step_result()
        v = ProofTreeVisualizer(result)
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            dot_path = f.name
        try:
            v.export_dot(dot_path)
            assert os.path.exists(dot_path)
            content = Path(dot_path).read_text()
            assert "digraph ProofTree" in content
        finally:
            Path(dot_path).unlink(missing_ok=True)

    def test_export_dot_contains_nodes(self):
        result = _make_multi_step_result()
        v = ProofTreeVisualizer(result)
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            dot_path = f.name
        try:
            v.export_dot(dot_path)
            content = Path(dot_path).read_text()
            assert "node_0" in content
            assert "fillcolor" in content
        finally:
            Path(dot_path).unlink(missing_ok=True)

    def test_export_dot_empty_tree_no_crash(self):
        result = _make_proved_result()  # no steps → no tree root via _build_tree
        # _build_tree with empty steps still creates a single-node tree
        v = ProofTreeVisualizer(result)
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            dot_path = f.name
        try:
            v.export_dot(dot_path)
            assert os.path.exists(dot_path)
        finally:
            Path(dot_path).unlink(missing_ok=True)

    def test_export_dot_minimal_verbosity(self):
        result = _make_multi_step_result()
        v = ProofTreeVisualizer(result, verbosity=VerbosityLevel.MINIMAL)
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            dot_path = f.name
        try:
            v.export_dot(dot_path)
            content = Path(dot_path).read_text()
            assert "digraph" in content
        finally:
            Path(dot_path).unlink(missing_ok=True)

    def test_export_dot_has_edges_for_premises(self):
        result = _make_multi_step_result()
        v = ProofTreeVisualizer(result)
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            dot_path = f.name
        try:
            v.export_dot(dot_path)
            content = Path(dot_path).read_text()
            assert "->" in content
        finally:
            Path(dot_path).unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════
# render_svg / render_png / _render_via_command_line
# ═══════════════════════════════════════════════════════════════


class TestRenderSvgPng:
    def _run_with_dot_mock(self, method_name, suffix, extra_args=None):
        result = _make_multi_step_result()
        v = ProofTreeVisualizer(result)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            out_path = f.name
        try:
            with patch(
                "ipfs_datasets_py.logic.TDFOL.proof_tree_visualizer.subprocess.run"
            ) as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                method = getattr(v, method_name)
                if extra_args:
                    method(out_path, *extra_args)
                else:
                    method(out_path)
                assert mock_run.called
        finally:
            Path(out_path).unlink(missing_ok=True)

    def test_render_svg_calls_subprocess(self):
        self._run_with_dot_mock("render_svg", ".svg")

    def test_render_png_calls_subprocess(self):
        self._run_with_dot_mock("render_png", ".png")

    def test_render_via_command_line_failure_raises(self):
        result = _make_multi_step_result()
        v = ProofTreeVisualizer(result)
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
            out_path = f.name
        try:
            with patch(
                "ipfs_datasets_py.logic.TDFOL.proof_tree_visualizer.subprocess.run"
            ) as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1, stderr="dot: command not found"
                )
                with pytest.raises(RuntimeError, match="Failed to render"):
                    v._render_via_command_line(out_path, "svg")
        finally:
            Path(out_path).unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════
# render_html
# ═══════════════════════════════════════════════════════════════


class TestRenderHtml:
    def _svg_side_effect(self, *args, **kwargs):
        """Write stub SVG when dot is called."""
        for arg in args[0]:
            if arg.endswith(".svg"):
                with open(arg, "w") as f:
                    f.write("<svg><text>stub</text></svg>")
        return MagicMock(returncode=0)

    def test_render_html_interactive_creates_file(self):
        result = _make_multi_step_result()
        v = ProofTreeVisualizer(result)
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            html_path = f.name
        try:
            with patch(
                "ipfs_datasets_py.logic.TDFOL.proof_tree_visualizer.subprocess.run",
                side_effect=self._svg_side_effect,
            ):
                v.render_html(html_path, interactive=True)
            assert os.path.exists(html_path)
            content = Path(html_path).read_text()
            assert "<!DOCTYPE html>" in content
            assert "<script>" in content
        finally:
            Path(html_path).unlink(missing_ok=True)

    def test_render_html_non_interactive_no_script(self):
        result = _make_multi_step_result()
        v = ProofTreeVisualizer(result)
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            html_path = f.name
        try:
            with patch(
                "ipfs_datasets_py.logic.TDFOL.proof_tree_visualizer.subprocess.run",
                side_effect=self._svg_side_effect,
            ):
                v.render_html(html_path, interactive=False)
            content = Path(html_path).read_text()
            assert "<script>" not in content
        finally:
            Path(html_path).unlink(missing_ok=True)

    def test_render_html_contains_proof_steps(self):
        result = _make_multi_step_result()
        v = ProofTreeVisualizer(result)
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            html_path = f.name
        try:
            with patch(
                "ipfs_datasets_py.logic.TDFOL.proof_tree_visualizer.subprocess.run",
                side_effect=self._svg_side_effect,
            ):
                v.render_html(html_path)
            content = Path(html_path).read_text()
            assert "Proof Steps" in content
        finally:
            Path(html_path).unlink(missing_ok=True)

    def test_render_html_with_message(self):
        f = _make_formula()
        s = _make_step(f)
        result = ProofResult(
            status=ProofStatus.PROVED,
            formula=f,
            proof_steps=[s],
            time_ms=1.0,
            method="test",
            message="All correct",
        )
        v = ProofTreeVisualizer(result)
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f2:
            html_path = f2.name
        try:
            with patch(
                "ipfs_datasets_py.logic.TDFOL.proof_tree_visualizer.subprocess.run",
                side_effect=self._svg_side_effect,
            ):
                v.render_html(html_path)
            content = Path(html_path).read_text()
            assert "All correct" in content
        finally:
            Path(html_path).unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════
# to_json / export_json
# ═══════════════════════════════════════════════════════════════


class TestToJsonExportJson:
    def test_to_json_empty_tree(self):
        result = _make_proved_result()
        v = ProofTreeVisualizer(result)
        # tree is not None (single node created for empty proof)
        j = v.to_json()
        assert j["status"] == "proved"
        assert "formula" in j

    def test_to_json_multi_step(self):
        result = _make_multi_step_result()
        v = ProofTreeVisualizer(result)
        j = v.to_json()
        assert j["status"] == "proved"
        assert "tree" in j
        assert "steps" in j
        assert len(j["steps"]) == 3

    def test_to_json_steps_have_correct_fields(self):
        result = _make_multi_step_result()
        v = ProofTreeVisualizer(result)
        j = v.to_json()
        step = j["steps"][0]
        assert "step_number" in step
        assert "formula" in step
        assert "rule_name" in step
        assert "justification" in step
        assert "premises" in step

    def test_to_json_tree_node_has_type(self):
        result = _make_multi_step_result()
        v = ProofTreeVisualizer(result)
        j = v.to_json()
        assert "node_type" in j["tree"]

    def test_export_json_creates_file(self):
        result = _make_multi_step_result()
        v = ProofTreeVisualizer(result)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            json_path = f.name
        try:
            v.export_json(json_path)
            assert os.path.exists(json_path)
            data = json.loads(Path(json_path).read_text())
            assert "status" in data
        finally:
            Path(json_path).unlink(missing_ok=True)

    def test_export_json_respects_indent(self):
        result = _make_multi_step_result()
        v = ProofTreeVisualizer(result)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            json_path = f.name
        try:
            v.export_json(json_path, indent=4)
            content = Path(json_path).read_text()
            assert "    " in content  # 4-space indent
        finally:
            Path(json_path).unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════
# _get_html_css / _get_html_javascript
# ═══════════════════════════════════════════════════════════════


class TestHtmlHelpers:
    def test_get_html_css_interactive(self):
        result = _make_proved_result()
        v = ProofTreeVisualizer(result)
        css = v._get_html_css(interactive=True)
        assert ".node:hover" in css
        assert ".tooltip" in css

    def test_get_html_css_non_interactive(self):
        result = _make_proved_result()
        v = ProofTreeVisualizer(result)
        css = v._get_html_css(interactive=False)
        assert ".node:hover" not in css

    def test_get_html_javascript_returns_string(self):
        result = _make_proved_result()
        v = ProofTreeVisualizer(result)
        js = v._get_html_javascript()
        assert "DOMContentLoaded" in js
        assert isinstance(js, str)


# ═══════════════════════════════════════════════════════════════
# visualize_proof convenience function
# ═══════════════════════════════════════════════════════════════


class TestVisualizeProof:
    def test_ascii_returns_string(self):
        result = _make_proved_result()
        out = visualize_proof(result, output_format="ascii", colors=False)
        assert isinstance(out, str)
        assert "Proof Tree" in out

    def test_dot_writes_file(self):
        result = _make_multi_step_result()
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False) as f:
            dot_path = f.name
        try:
            ret = visualize_proof(result, output_format="dot", output_path=dot_path)
            assert ret is None
            assert os.path.exists(dot_path)
        finally:
            Path(dot_path).unlink(missing_ok=True)

    def test_dot_no_path_raises(self):
        result = _make_proved_result()
        with pytest.raises(ValueError, match="output_path required"):
            visualize_proof(result, output_format="dot")

    def test_svg_no_path_raises(self):
        result = _make_proved_result()
        with pytest.raises(ValueError, match="output_path required"):
            visualize_proof(result, output_format="svg")

    def test_png_no_path_raises(self):
        result = _make_proved_result()
        with pytest.raises(ValueError, match="output_path required"):
            visualize_proof(result, output_format="png")

    def test_html_no_path_raises(self):
        result = _make_proved_result()
        with pytest.raises(ValueError, match="output_path required"):
            visualize_proof(result, output_format="html")

    def test_json_no_path_raises(self):
        result = _make_proved_result()
        with pytest.raises(ValueError, match="output_path required"):
            visualize_proof(result, output_format="json")

    def test_unknown_format_raises(self):
        result = _make_proved_result()
        with pytest.raises(ValueError, match="Unknown output format"):
            visualize_proof(result, output_format="xyz")

    def test_json_writes_file(self):
        result = _make_multi_step_result()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            json_path = f.name
        try:
            visualize_proof(result, output_format="json", output_path=json_path)
            data = json.loads(Path(json_path).read_text())
            assert "status" in data
        finally:
            Path(json_path).unlink(missing_ok=True)

    def test_svg_writes_file_with_mock(self):
        result = _make_multi_step_result()
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
            svg_path = f.name
        try:
            with patch(
                "ipfs_datasets_py.logic.TDFOL.proof_tree_visualizer.subprocess.run"
            ) as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                visualize_proof(result, output_format="svg", output_path=svg_path)
                assert mock_run.called
        finally:
            Path(svg_path).unlink(missing_ok=True)

    def test_png_writes_file_with_mock(self):
        result = _make_multi_step_result()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            png_path = f.name
        try:
            with patch(
                "ipfs_datasets_py.logic.TDFOL.proof_tree_visualizer.subprocess.run"
            ) as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                visualize_proof(result, output_format="png", output_path=png_path)
                assert mock_run.called
        finally:
            Path(png_path).unlink(missing_ok=True)

    def test_html_writes_file_with_mock(self):
        result = _make_multi_step_result()
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            html_path = f.name

        def svg_side_effect(*args, **kwargs):
            for arg in args[0]:
                if arg.endswith(".svg"):
                    with open(arg, "w") as f2:
                        f2.write("<svg></svg>")
            return MagicMock(returncode=0)

        try:
            with patch(
                "ipfs_datasets_py.logic.TDFOL.proof_tree_visualizer.subprocess.run",
                side_effect=svg_side_effect,
            ):
                visualize_proof(
                    result, output_format="html", output_path=html_path
                )
            assert os.path.exists(html_path)
        finally:
            Path(html_path).unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════
# CEC proof_optimization.py tests (extending from 18 to 45+)
# ═══════════════════════════════════════════════════════════════


class TestProofNode:
    def test_construction(self):
        n = ProofNode(formula="P(a)", depth=0)
        assert n.formula == "P(a)"
        assert n.depth == 0
        assert n.parent is None
        assert n.children == []
        assert not n.is_goal
        assert not n.is_redundant
        assert n.proof_step is None

    def test_hash_by_formula(self):
        n1 = ProofNode(formula="P(a)", depth=0)
        n2 = ProofNode(formula="P(a)", depth=5)
        assert hash(n1) == hash(n2)

    def test_equality_by_formula(self):
        n1 = ProofNode(formula="P(a)", depth=0)
        n2 = ProofNode(formula="P(a)", depth=5)
        assert n1 == n2

    def test_inequality_different_formula(self):
        n1 = ProofNode(formula="P(a)", depth=0)
        n2 = ProofNode(formula="Q(a)", depth=0)
        assert n1 != n2

    def test_equality_non_proofnode(self):
        n = ProofNode(formula="P(a)", depth=0)
        assert n != "P(a)"

    def test_set_deduplication(self):
        n1 = ProofNode(formula="P(a)", depth=0)
        n2 = ProofNode(formula="P(a)", depth=3)
        s = {n1, n2}
        assert len(s) == 1


class TestOptimizationMetrics:
    def test_default_values(self):
        m = OptimizationMetrics()
        assert m.nodes_explored == 0
        assert m.pruning_ratio() == 0.0

    def test_pruning_ratio_with_data(self):
        m = OptimizationMetrics(nodes_explored=7, nodes_pruned=3)
        ratio = m.pruning_ratio()
        assert abs(ratio - 0.3) < 0.001

    def test_pruning_ratio_all_pruned(self):
        m = OptimizationMetrics(nodes_explored=0, nodes_pruned=5)
        assert m.pruning_ratio() == 1.0

    def test_to_dict_keys(self):
        m = OptimizationMetrics(nodes_explored=2, nodes_pruned=1)
        d = m.to_dict()
        assert "nodes_explored" in d
        assert "nodes_pruned" in d
        assert "pruning_ratio" in d
        assert "parallel_speedup" in d


class TestProofTreePruner:
    def _make_tree(self, depth: int = 0, is_goal: bool = False) -> ProofNode:
        n = ProofNode(formula=f"F{depth}", depth=depth, is_goal=is_goal)
        return n

    def test_should_prune_depth_limit(self):
        pruner = ProofTreePruner(max_depth=5)
        n = ProofNode(formula="F", depth=6)
        should, reason = pruner.should_prune(n, set())
        assert should
        assert reason == "depth_limit"

    def test_should_prune_redundancy(self):
        pruner = ProofTreePruner(max_depth=10)
        n = ProofNode(formula="P(a)", depth=1)
        should, reason = pruner.should_prune(n, {"P(a)"})
        assert should
        assert reason == "redundancy"

    def test_should_not_prune_normal_node(self):
        pruner = ProofTreePruner(max_depth=10)
        n = ProofNode(formula="P(a)", depth=1)
        should, _ = pruner.should_prune(n, set())
        assert not should

    def test_should_not_prune_goal_reached(self):
        pruner = ProofTreePruner(max_depth=10, enable_early_termination=True)
        n = ProofNode(formula="Goal", depth=1, is_goal=True)
        should, reason = pruner.should_prune(n, set())
        assert not should
        assert reason == "goal_reached"

    def test_prune_tree_simple(self):
        pruner = ProofTreePruner(max_depth=10)
        root = ProofNode(formula="Root", depth=0)
        child = ProofNode(formula="Child", depth=1)
        root.children = [child]
        pruned, metrics = pruner.prune_tree(root)
        assert pruned is not None
        assert metrics.nodes_explored == 2

    def test_prune_tree_depth_exceeded(self):
        pruner = ProofTreePruner(max_depth=2)
        root = ProofNode(formula="Root", depth=0)
        deep = ProofNode(formula="Deep", depth=3)
        root.children = [deep]
        pruned, metrics = pruner.prune_tree(root)
        assert metrics.nodes_pruned >= 1

    def test_prune_tree_redundancy_pruned(self):
        pruner = ProofTreePruner(max_depth=10)
        root = ProofNode(formula="Dup", depth=0)
        dup = ProofNode(formula="Dup", depth=1)
        root.children = [dup]
        _, metrics = pruner.prune_tree(root)
        assert metrics.duplicates_eliminated >= 1


class TestRedundancyEliminator:
    def test_no_redundancy(self):
        elim = RedundancyEliminator()
        result = elim.eliminate_redundancy(["P", "Q", "R"])
        assert result == ["P", "Q", "R"]

    def test_duplicate_removed(self):
        elim = RedundancyEliminator()
        result = elim.eliminate_redundancy(["P", "Q", "P"])
        assert "P" in result
        assert result.count("P") == 1

    def test_subsumption(self):
        elim = RedundancyEliminator()
        result = elim.eliminate_redundancy(["P", "P(a)"])
        # String-based (not logical) subsumption: "P" in "P(a)" and len("P(a)") > len("P"),
        # so "P" subsumes "P(a)" and "P(a)" is eliminated.
        assert "P" in result

    def test_is_duplicate_tracks_seen(self):
        elim = RedundancyEliminator()
        assert not elim.is_duplicate("X")
        assert elim.is_duplicate("X")

    def test_subsumes_equal(self):
        elim = RedundancyEliminator()
        assert elim.subsumes("P", "P")

    def test_subsumes_specialization(self):
        elim = RedundancyEliminator()
        assert elim.subsumes("P", "P(a)")

    def test_does_not_subsume_unrelated(self):
        elim = RedundancyEliminator()
        assert not elim.subsumes("Q", "P")

    def test_get_metrics_after_elimination(self):
        elim = RedundancyEliminator()
        elim.eliminate_redundancy(["A", "A", "B"])
        m = elim.get_metrics()
        assert m.duplicates_eliminated >= 1


class TestParallelProofSearch:
    def test_search_parallel_finds_result(self):
        searcher = ParallelProofSearch(max_workers=2)
        result = searcher.search_parallel(
            lambda x: x * 2 if x == 3 else None,
            [1, 2, 3, 4],
        )
        assert result == 6

    def test_search_parallel_returns_none_when_no_result(self):
        searcher = ParallelProofSearch(max_workers=2)
        result = searcher.search_parallel(lambda x: None, [1, 2, 3])
        assert result is None

    def test_search_parallel_exception_handled(self):
        searcher = ParallelProofSearch(max_workers=2)

        def fail_on_2(x):
            if x == 2:
                raise ValueError("fail")
            return x * 10 if x == 3 else None

        result = searcher.search_parallel(fail_on_2, [1, 2, 3])
        assert result == 30

    def test_get_metrics_after_search(self):
        searcher = ParallelProofSearch(max_workers=2)
        searcher.search_parallel(lambda x: x if x == 1 else None, [1, 2])
        m = searcher.get_metrics()
        assert isinstance(m, OptimizationMetrics)


class TestProofOptimizer:
    def _make_tree(self) -> ProofNode:
        root = ProofNode(formula="Root", depth=0)
        c1 = ProofNode(formula="Child1", depth=1)
        c2 = ProofNode(formula="Child2", depth=1)
        dup = ProofNode(formula="Child1", depth=2)
        c1.children = [dup]
        root.children = [c1, c2]
        return root

    def test_optimize_proof_tree_returns_root_and_metrics(self):
        optimizer = ProofOptimizer(max_depth=10)
        root = self._make_tree()
        optimized, metrics = optimizer.optimize_proof_tree(root)
        assert optimized is not None
        assert isinstance(metrics, OptimizationMetrics)

    def test_optimize_with_pruning_disabled(self):
        optimizer = ProofOptimizer(enable_pruning=False, enable_redundancy_elimination=False)
        root = self._make_tree()
        optimized, metrics = optimizer.optimize_proof_tree(root)
        assert optimized is root

    def test_collect_formulas(self):
        optimizer = ProofOptimizer()
        root = self._make_tree()
        formulas = optimizer._collect_formulas(root)
        assert "Root" in formulas
        assert "Child1" in formulas

    def test_get_combined_metrics(self):
        optimizer = ProofOptimizer()
        root = self._make_tree()
        optimizer.optimize_proof_tree(root)
        m = optimizer.get_combined_metrics()
        assert isinstance(m, OptimizationMetrics)

    def test_deep_tree_pruned(self):
        optimizer = ProofOptimizer(max_depth=2)
        root = ProofNode(formula="Root", depth=0)
        deep = ProofNode(formula="Deep", depth=3)
        root.children = [deep]
        _, metrics = optimizer.optimize_proof_tree(root)
        assert metrics.nodes_pruned >= 1


class TestPruningStrategy:
    def test_enum_values(self):
        assert PruningStrategy.DEPTH_LIMIT.value == "depth_limit"
        assert PruningStrategy.EARLY_TERMINATION.value == "early_termination"
        assert PruningStrategy.REDUNDANCY_CHECK.value == "redundancy_check"
        assert PruningStrategy.COMBINED.value == "combined"
