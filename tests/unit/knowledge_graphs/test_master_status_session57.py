"""
Session 57: Cover visualization.py plotly ImportError except block (lines 29-31)
and document the scipy/matplotlib/plotly dep additions to setup.py.

Targets:
- lineage/visualization.py:29-31  (plotly ImportError except → PLOTLY_AVAILABLE=False, go=None)
- setup.py: scipy>=1.7.0, matplotlib>=3.5.0, plotly>=5.9.0 now in knowledge_graphs extras
- requirements.txt: scipy, matplotlib, plotly added

All module reloads are isolated: sys.modules is restored after each test.
"""

import sys
import importlib
import importlib.util
import pytest

# Sentinel — distinct from None (which is a valid sys.modules value)
_MISSING = object()

_plotly_available = bool(importlib.util.find_spec("plotly"))
_skip_no_plotly = pytest.mark.skipif(
    not _plotly_available, reason="plotly not installed"
)
_matplotlib_available = bool(importlib.util.find_spec("matplotlib"))
_skip_no_matplotlib = pytest.mark.skipif(
    not _matplotlib_available, reason="matplotlib not installed"
)
_scipy_available = bool(importlib.util.find_spec("scipy"))
_skip_no_scipy = pytest.mark.skipif(
    not _scipy_available, reason="scipy not installed"
)


# ---------------------------------------------------------------------------
# Helpers (shared pattern from session 52)
# ---------------------------------------------------------------------------

def _reload_with_absent_dep(module_name: str, absent_deps: list) -> object:
    """
    Reload *module_name* with each dep in *absent_deps* blocked as None in
    sys.modules (causing ``import dep`` to raise ImportError).  Always
    restores sys.modules and parent package attribute afterwards.
    """
    saved: dict = {}

    for dep in absent_deps:
        saved[dep] = sys.modules.pop(dep, _MISSING)
        sys.modules[dep] = None  # type: ignore[assignment]

    saved_mod = sys.modules.pop(module_name, _MISSING)

    parent_name, _, leaf = module_name.rpartition(".")
    parent_pkg = sys.modules.get(parent_name)
    saved_pkg_attr = getattr(parent_pkg, leaf, _MISSING) if parent_pkg and leaf else _MISSING

    try:
        fresh = importlib.import_module(module_name)
    finally:
        # Restore blocked deps
        for dep, old in saved.items():
            if old is _MISSING:
                sys.modules.pop(dep, None)
            else:
                sys.modules[dep] = old  # type: ignore[assignment]

        # Restore the module itself
        if saved_mod is _MISSING:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = saved_mod  # type: ignore[assignment]

        # Restore parent package attribute
        if parent_pkg and leaf:
            if saved_pkg_attr is _MISSING:
                try:
                    delattr(parent_pkg, leaf)
                except AttributeError:
                    pass
            else:
                setattr(parent_pkg, leaf, saved_pkg_attr)

    return fresh


# ---------------------------------------------------------------------------
# visualization.py lines 29-31: plotly ImportError except block
# ---------------------------------------------------------------------------

class TestVisualizationPlotlyImportError:
    """
    GIVEN plotly is unavailable
    WHEN lineage/visualization.py is (re-)imported
    THEN PLOTLY_AVAILABLE is False and go is None
    (exercises lines 29-31 of visualization.py)
    """

    def test_plotly_unavailable_sets_flag_false(self):
        """
        GIVEN plotly.graph_objects blocked in sys.modules
        WHEN visualization module is reloaded
        THEN PLOTLY_AVAILABLE attribute is False.
        """
        VIZ_MODULE = "ipfs_datasets_py.knowledge_graphs.lineage.visualization"
        fresh = _reload_with_absent_dep(
            VIZ_MODULE,
            absent_deps=["plotly", "plotly.graph_objects"],
        )
        assert fresh.PLOTLY_AVAILABLE is False, (
            "PLOTLY_AVAILABLE must be False when plotly.graph_objects is not importable"
        )

    def test_plotly_unavailable_sets_go_none(self):
        """
        GIVEN plotly.graph_objects blocked in sys.modules
        WHEN visualization module is reloaded
        THEN go attribute is None.
        """
        VIZ_MODULE = "ipfs_datasets_py.knowledge_graphs.lineage.visualization"
        fresh = _reload_with_absent_dep(
            VIZ_MODULE,
            absent_deps=["plotly", "plotly.graph_objects"],
        )
        assert fresh.go is None, (
            "go must be None when plotly is not importable"
        )

    def test_plotly_unavailable_render_raises(self):
        """
        GIVEN plotly unavailable
        WHEN render_plotly() is called
        THEN ImportError is raised.
        """
        VIZ_MODULE = "ipfs_datasets_py.knowledge_graphs.lineage.visualization"
        fresh = _reload_with_absent_dep(
            VIZ_MODULE,
            absent_deps=["plotly", "plotly.graph_objects"],
        )
        # Need a LineageGraph instance; import from the already-loaded module
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageTracker
        t = LineageTracker()
        vis_cls = fresh.LineageVisualizer
        v = vis_cls(t.graph)
        with pytest.raises(ImportError, match="Plotly"):
            v.render_plotly()

    @_skip_no_plotly
    def test_plotly_available_sets_flag_true(self):
        """
        GIVEN plotly is installed in this environment
        WHEN visualization module is imported normally
        THEN PLOTLY_AVAILABLE is True.
        """
        import ipfs_datasets_py.knowledge_graphs.lineage.visualization as viz_mod
        assert viz_mod.PLOTLY_AVAILABLE is True

    @_skip_no_plotly
    def test_plotly_available_go_is_not_none(self):
        """
        GIVEN plotly is installed
        WHEN visualization module is imported normally
        THEN go is the plotly.graph_objects module.
        """
        import ipfs_datasets_py.knowledge_graphs.lineage.visualization as viz_mod
        assert viz_mod.go is not None

    @_skip_no_plotly
    def test_render_plotly_returns_html(self):
        """
        GIVEN plotly is installed and a populated LineageTracker
        WHEN render_plotly() is called without output_path
        THEN an HTML string is returned.
        """
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageTracker
        import ipfs_datasets_py.knowledge_graphs.lineage.visualization as viz_mod
        import plotly.graph_objects as real_go
        # Ensure viz_mod uses the real plotly module (not a stale mock from session38
        # test_render_plotly_ghost_node_gets_gray_color which sets viz_mod.go=MagicMock()
        # and never restores it)
        saved_go = viz_mod.go
        viz_mod.go = real_go
        try:
            t = LineageTracker()
            t.track_transformation(
                transformation_id="t1",
                operation_type="join",
                inputs=[{"dataset_id": "ds1", "field": "id"}],
                outputs=[{"dataset_id": "ds2", "field": "joined_id"}],
            )
            v = viz_mod.LineageVisualizer(t.graph)
            html = v.render_plotly()
            assert isinstance(html, str)
            assert len(html) > 100
        finally:
            viz_mod.go = saved_go

    @_skip_no_plotly
    def test_render_plotly_saves_to_file(self, tmp_path):
        """
        GIVEN plotly is installed
        WHEN render_plotly(output_path=...) is called
        THEN file is created and None is returned.
        """
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageTracker
        import ipfs_datasets_py.knowledge_graphs.lineage.visualization as viz_mod
        import plotly.graph_objects as real_go
        # Ensure viz_mod uses the real plotly module (not a stale mock from session38
        # test_render_plotly_ghost_node_gets_gray_color which sets viz_mod.go=MagicMock()
        # and never restores it)
        saved_go = viz_mod.go
        viz_mod.go = real_go
        try:
            t = LineageTracker()
            t.track_transformation(
                transformation_id="t2",
                operation_type="filter",
                inputs=[{"dataset_id": "src", "field": "value"}],
                outputs=[{"dataset_id": "dst", "field": "value"}],
            )
            v = viz_mod.LineageVisualizer(t.graph)
            out = tmp_path / "lineage.html"
            result = v.render_plotly(output_path=str(out))
            assert result is None
            assert out.exists()
            assert out.stat().st_size > 0
        finally:
            viz_mod.go = saved_go


# ---------------------------------------------------------------------------
# setup.py: scipy/matplotlib/plotly added to knowledge_graphs extras
# ---------------------------------------------------------------------------

class TestSetupPyScipy:
    """
    Verify that scipy, matplotlib, and plotly are declared in setup.py
    knowledge_graphs extras (added in session 57).
    """

    @staticmethod
    def _read_setup_py() -> str:
        import pathlib
        root = pathlib.Path(__file__).resolve()
        for _ in range(10):
            candidate = root / "setup.py"
            if candidate.exists():
                return candidate.read_text()
            root = root.parent
        raise FileNotFoundError("setup.py not found")

    def test_scipy_in_knowledge_graphs_extras(self):
        """
        GIVEN setup.py knowledge_graphs extras
        WHEN read as text
        THEN scipy version constraint is present.
        """
        text = self._read_setup_py()
        # Find the knowledge_graphs extras block
        kg_start = text.find("'knowledge_graphs'")
        assert kg_start != -1
        # Find the closing ']' after 'knowledge_graphs'
        kg_block_end = text.find("],", kg_start)
        kg_block = text[kg_start:kg_block_end]
        assert "scipy" in kg_block, (
            "scipy must be in knowledge_graphs extras (enables kamada_kawai_layout)"
        )

    def test_matplotlib_in_knowledge_graphs_extras(self):
        """
        GIVEN setup.py knowledge_graphs extras
        WHEN read as text
        THEN matplotlib version constraint is present.
        """
        text = self._read_setup_py()
        kg_start = text.find("'knowledge_graphs'")
        assert kg_start != -1
        kg_block_end = text.find("],", kg_start)
        kg_block = text[kg_start:kg_block_end]
        assert "matplotlib" in kg_block, (
            "matplotlib must be in knowledge_graphs extras (enables render_networkx)"
        )

    def test_plotly_in_knowledge_graphs_extras(self):
        """
        GIVEN setup.py knowledge_graphs extras
        WHEN read as text
        THEN plotly version constraint is present.
        """
        text = self._read_setup_py()
        kg_start = text.find("'knowledge_graphs'")
        assert kg_start != -1
        kg_block_end = text.find("],", kg_start)
        kg_block = text[kg_start:kg_block_end]
        assert "plotly" in kg_block, (
            "plotly must be in knowledge_graphs extras (enables render_plotly)"
        )


# ---------------------------------------------------------------------------
# Verify scipy enables hierarchical (kamada_kawai) layout in render_networkx
# ---------------------------------------------------------------------------

class TestVisualizationHierarchicalLayout:
    """
    Confirm the scipy-dependent kamada_kawai_layout branch is reachable
    (line 116 in visualization.py) when scipy is available.
    """

    @_skip_no_scipy
    @_skip_no_matplotlib
    def test_hierarchical_layout_returns_bytes(self):
        """
        GIVEN scipy and matplotlib are installed
        WHEN render_networkx(layout='hierarchical') is called
        THEN PNG bytes are returned (non-empty).
        """
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageTracker
        import ipfs_datasets_py.knowledge_graphs.lineage.visualization as viz_mod

        t = LineageTracker()
        t.track_transformation(
            transformation_id="h1",
            operation_type="aggregate",
            inputs=[{"dataset_id": "raw", "field": "x"}],
            outputs=[{"dataset_id": "agg", "field": "x_sum"}],
        )
        v = viz_mod.LineageVisualizer(t.graph)
        result = v.render_networkx(layout="hierarchical")
        assert isinstance(result, bytes)
        assert len(result) > 0

    @_skip_no_scipy
    @_skip_no_matplotlib
    def test_hierarchical_layout_produces_valid_png(self):
        """
        GIVEN scipy and matplotlib are installed
        WHEN render_networkx(layout='hierarchical') is called
        THEN result starts with PNG magic bytes.
        """
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageTracker
        import ipfs_datasets_py.knowledge_graphs.lineage.visualization as viz_mod

        t = LineageTracker()
        t.track_transformation(
            transformation_id="h2",
            operation_type="filter",
            inputs=[{"dataset_id": "full", "field": "col"}],
            outputs=[{"dataset_id": "filtered", "field": "col"}],
        )
        v = viz_mod.LineageVisualizer(t.graph)
        result = v.render_networkx(layout="hierarchical")
        # PNG magic bytes: \x89PNG
        assert result[:4] == b"\x89PNG", "Result should be a valid PNG file"
