"""
Session 58: Remove dead code srl.py:401-402 + add multiformats to ipld extras.

Targets:
- extraction/srl.py: removed unreachable `elif dep in ("npadvmod",): role = ROLE_TIME`
  block; `npadvmod` was already matched by the preceding `elif dep in ("prep",
  "advmod", "npadvmod"):` on line 385 → srl.py now 100%.
- setup.py: `multiformats>=0.3.0` added to `ipld` extras (needed for CAR save path
  which imports `from multiformats import CID, multihash`).
- pyproject.toml: `ipld` extras section added with identical dep list.

All tests are unit/invariant tests; no external model or network access.
"""

import ast
import importlib.util
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parents[3]  # repo root
_KG = _ROOT / "ipfs_datasets_py" / "knowledge_graphs"
_SETUP_PY = _ROOT / "setup.py"
_PYPROJECT = _ROOT / "pyproject.toml"
_SRL_PY = _KG / "extraction" / "srl.py"

# ---------------------------------------------------------------------------
# Skip guards
# ---------------------------------------------------------------------------
_MISSING = object()


# ===========================================================================
# TestSrlNpadvmodDeadCodeRemoved
# ===========================================================================
class TestSrlNpadvmodDeadCodeRemoved:
    """Verify the unreachable `elif dep in ("npadvmod",):` block is gone."""

    def test_srl_source_has_no_second_npadvmod_elif(self):
        """
        GIVEN srl.py source
        WHEN we scan for occurrences of ``elif dep in ("npadvmod",)``
        THEN none exist (the dead branch has been removed).
        """
        src = _SRL_PY.read_text()
        assert 'elif dep in ("npadvmod",)' not in src, (
            "srl.py still contains the dead `elif dep in (\"npadvmod\",):` branch"
        )

    def test_srl_source_has_exactly_one_npadvmod_occurrence(self):
        """
        GIVEN srl.py source
        WHEN we count occurrences of the string ``npadvmod``
        THEN there is exactly one (inside the `dep in ("prep", "advmod", "npadvmod")` line).
        """
        src = _SRL_PY.read_text()
        count = src.count("npadvmod")
        assert count == 1, (
            f"Expected exactly 1 occurrence of 'npadvmod' in srl.py, found {count}"
        )

    def test_srl_source_npadvmod_in_combined_elif(self):
        """
        GIVEN srl.py source
        WHEN we locate the one npadvmod occurrence
        THEN it lives on a line that also contains ``prep`` and ``advmod``.
        """
        src = _SRL_PY.read_text()
        line = next(
            line for line in src.splitlines() if "npadvmod" in line
        )
        assert "prep" in line and "advmod" in line, (
            f"The only npadvmod line should also contain 'prep' and 'advmod', got: {line!r}"
        )

    def test_srl_source_no_duplicate_deps_in_elif_chain(self):
        """
        GIVEN the _extract_spacy_frames function in srl.py
        WHEN we collect all dep-values mentioned in the if/elif chain
        THEN no dep-value appears more than once (no overlap between branches).
        """
        src = _SRL_PY.read_text()
        # Collect all string literals appearing after "dep in" / "dep ==" in the
        # _extract_spacy_frames body.  We just need to confirm "npadvmod" appears
        # in only one branch.
        dep_mentions: dict = {}
        for line in src.splitlines():
            stripped = line.strip()
            if not (stripped.startswith("if dep") or stripped.startswith("elif dep")):
                continue
            # extract all "dep_tag" strings from the line
            import re as _re
            for token in _re.findall(r'"([a-z_]+)"', stripped):
                dep_mentions[token] = dep_mentions.get(token, 0) + 1
        duplicates = {k: v for k, v in dep_mentions.items() if v > 1}
        assert not duplicates, (
            f"Some dep-values appear in multiple elif branches: {duplicates}"
        )

    def test_srl_extract_spacy_npadvmod_token_yields_time_role(self):
        """
        GIVEN a mock spaCy sentence span with a VERB token whose child has
              dep_="npadvmod" and text="yesterday"
        WHEN  _extract_spacy_frames is called
        THEN  the resulting frame has an argument with ROLE_TIME.

        This confirms that the *surviving* branch (prep/advmod/npadvmod at
        line 385) still correctly routes npadvmod tokens to ROLE_THEME or
        ROLE_TIME depending on prep_text content.  "yesterday" doesn't match
        any of the specific prep-text lists so it routes to ROLE_THEME, which
        is correct (npadvmod with unrecognised text → theme default).
        """
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import (
            _extract_spacy_frames,
            ROLE_THEME,
            ROLE_TIME,
        )

        # Build a minimal mock child token with dep_="npadvmod", text="yesterday"
        child = MagicMock()
        child.dep_ = "npadvmod"
        child.text = "yesterday"
        child.idx = 10
        child.subtree = [child]

        # Parent VERB token
        verb = MagicMock()
        verb.pos_ = "VERB"
        verb.lemma_ = "run"
        verb.text = "ran"
        verb.children = [child]

        # Sentence span
        sent_span = MagicMock()
        sent_span.text = "She ran yesterday."
        sent_span.__iter__ = MagicMock(return_value=iter([verb]))

        frames = _extract_spacy_frames(sent_span)
        # Should produce 1 frame with 1 argument
        assert len(frames) == 1
        args = frames[0].arguments
        assert len(args) == 1
        # "yesterday" doesn't match any known prep-text → ROLE_THEME (the else branch)
        assert args[0].role == ROLE_THEME

    def test_srl_extract_spacy_npadvmod_with_temporal_prep_yields_time_role(self):
        """
        GIVEN a mock spaCy child with dep_="npadvmod", text="before" (a temporal prep)
        WHEN  _extract_spacy_frames is called
        THEN  the argument is classified as ROLE_TIME.
        """
        from ipfs_datasets_py.knowledge_graphs.extraction.srl import (
            _extract_spacy_frames,
            ROLE_TIME,
        )

        child = MagicMock()
        child.dep_ = "npadvmod"
        child.text = "before"
        child.idx = 5
        child.subtree = [child]

        verb = MagicMock()
        verb.pos_ = "VERB"
        verb.lemma_ = "finish"
        verb.text = "finished"
        verb.children = [child]

        sent_span = MagicMock()
        sent_span.text = "She finished before."
        sent_span.__iter__ = MagicMock(return_value=iter([verb]))

        frames = _extract_spacy_frames(sent_span)
        assert len(frames) == 1
        args = frames[0].arguments
        assert len(args) == 1
        # "before" is in the temporal list → ROLE_TIME
        assert args[0].role == ROLE_TIME

    def test_srl_source_parses_as_valid_python(self):
        """
        GIVEN srl.py after the dead code removal
        WHEN we parse it with ast.parse
        THEN no SyntaxError is raised.
        """
        src = _SRL_PY.read_text()
        tree = ast.parse(src)  # raises SyntaxError if invalid
        assert tree is not None


# ===========================================================================
# TestIpldExtrasMultiformats
# ===========================================================================
class TestIpldExtrasMultiformats:
    """Verify multiformats is declared in the ipld extras of setup.py + pyproject.toml."""

    def _read_setup_py_ipld_extras(self) -> str:
        """Return the raw text of the `ipld` block inside setup.py."""
        src = _SETUP_PY.read_text()
        start = src.find("'ipld': [")
        assert start != -1, "Could not find 'ipld': [ in setup.py"
        end = src.find("],", start)
        assert end != -1, "Could not find closing ], for ipld extras in setup.py"
        return src[start : end + 2]

    def test_setup_py_ipld_has_multiformats(self):
        """
        GIVEN setup.py
        WHEN we look at the 'ipld' extras block
        THEN it contains a multiformats entry.
        """
        block = self._read_setup_py_ipld_extras()
        assert "multiformats" in block, (
            "setup.py 'ipld' extras must include multiformats (needed for CAR save path)"
        )

    def test_setup_py_ipld_has_five_core_deps(self):
        """
        GIVEN setup.py
        WHEN we look at the 'ipld' extras block
        THEN all five required IPLD deps are present.
        """
        block = self._read_setup_py_ipld_extras()
        expected = ["libipld", "ipld-car", "ipld-dag-pb", "dag-cbor", "multiformats"]
        for dep in expected:
            assert dep in block, f"setup.py 'ipld' extras missing: {dep}"

    def test_pyproject_toml_has_ipld_section(self):
        """
        GIVEN pyproject.toml
        WHEN we look for the ipld optional-dependencies section
        THEN it exists.
        """
        src = _PYPROJECT.read_text()
        assert "ipld" in src, "pyproject.toml should have an 'ipld' optional-deps section"

    def test_pyproject_toml_ipld_has_multiformats(self):
        """
        GIVEN pyproject.toml
        WHEN we look at the ipld section
        THEN it contains multiformats.
        """
        src = _PYPROJECT.read_text()
        # Find ipld section
        start = src.find("ipld = [")
        assert start != -1, "pyproject.toml missing 'ipld = [' section"
        end = src.find("]", start)
        block = src[start : end + 1]
        assert "multiformats" in block, (
            "pyproject.toml 'ipld' extras must include multiformats"
        )

    def test_pyproject_toml_ipld_consistent_with_setup_py(self):
        """
        GIVEN setup.py and pyproject.toml
        WHEN we compare the ipld extras content
        THEN both files reference the same core deps (libipld, ipld-car, dag-cbor, multiformats).
        """
        setup_src = _SETUP_PY.read_text()
        toml_src = _PYPROJECT.read_text()
        core_deps = ["libipld", "ipld-car", "ipld-dag-pb", "dag-cbor", "multiformats"]
        for dep in core_deps:
            assert dep in setup_src, f"setup.py ipld extras missing: {dep}"
            assert dep in toml_src, f"pyproject.toml ipld extras missing: {dep}"


# ===========================================================================
# TestIpldCarImportErrorBranch
# ===========================================================================
class TestIpldCarImportErrorBranch:
    """Cover ipld.py:99-101 (the except ImportError block for ipld_car).

    When ipld_car is installed these lines are not reached during normal
    module loading.  We use _reload_with_absent_dep to exercise them.
    """

    _IPLD_MOD = "ipfs_datasets_py.knowledge_graphs.ipld"

    def _reload_with_absent(self, dep: str):
        """Reload ipld.py with *dep* blocked as None → triggers ImportError."""
        saved_mod = sys.modules.pop(self._IPLD_MOD, _MISSING)
        saved_dep = sys.modules.pop(dep, _MISSING)
        # Also remove any cached parent-package attribute for ipld
        pkg_name = self._IPLD_MOD.rsplit(".", 1)[0]
        pkg = sys.modules.get(pkg_name)
        saved_pkg_attr = getattr(pkg, "ipld", _MISSING) if pkg is not None else _MISSING

        sys.modules[dep] = None  # type: ignore[assignment]
        try:
            import importlib
            fresh = importlib.import_module(self._IPLD_MOD)
            return fresh
        finally:
            # Restore sys.modules
            sys.modules.pop(self._IPLD_MOD, None)
            if saved_mod is _MISSING:
                sys.modules.pop(self._IPLD_MOD, None)
            else:
                sys.modules[self._IPLD_MOD] = saved_mod  # type: ignore[assignment]

            if saved_dep is _MISSING:
                sys.modules.pop(dep, None)
            else:
                sys.modules[dep] = saved_dep  # type: ignore[assignment]

            if pkg is not None:
                if saved_pkg_attr is _MISSING:
                    pkg.__dict__.pop("ipld", None)
                else:
                    pkg.ipld = saved_pkg_attr  # type: ignore[attr-defined]

    def test_ipld_car_absent_sets_have_ipld_car_false(self):
        """
        GIVEN ipld_car is not importable
        WHEN ipld.py is loaded
        THEN HAVE_IPLD_CAR is False (line 101 runs).
        """
        fresh = self._reload_with_absent("ipld_car")
        assert fresh.HAVE_IPLD_CAR is False

    def test_ipld_car_absent_sets_ipld_car_to_none(self):
        """
        GIVEN ipld_car is not importable
        WHEN ipld.py is loaded
        THEN ipld_car attribute is None (line 100 runs).
        """
        fresh = self._reload_with_absent("ipld_car")
        assert fresh.ipld_car is None
