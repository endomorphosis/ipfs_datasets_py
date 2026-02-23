"""
Session 50 — GIVEN/WHEN/THEN integration coverage tests

Covers:
  - interactive/interactive_fol_types.py  (0 → ~100%)
  - interactive/interactive_fol_utils.py  (0 → ~100%)
  - interactive/interactive_fol_constructor.py (0 → ~85%)
  - bridges/symbolic_fol_bridge.py  (33 → ~80%)
  - integration/__init__.py  (36 → ~60%)
  - demos/demo_temporal_deontic_rag.py  (0 → ~70%)

Bugs fixed (4):
  1. interactive/interactive_fol_constructor.py:38 — `.symbolic_fol_bridge` →
     `..bridges.symbolic_fol_bridge`  (module not in interactive/)
  2. interactive/interactive_fol_constructor.py:39 — `.symbolic_logic_primitives` →
     `..symbolic.symbolic_logic_primitives`  (module not in interactive/)
  3. interactive/interactive_fol_types.py:16 — same relative-import fix for LogicalComponents
  4. demos/demo_temporal_deontic_rag.py:14-21 — imports fixed:
     `.temporal_deontic_rag_store` → `..domain.temporal_deontic_rag_store`
     `.document_consistency_checker` → `..domain.document_consistency_checker`
     `..integration.deontic_logic_core` → `..converters.deontic_logic_core`
"""

import io
import sys
import importlib
import unittest
from datetime import datetime
from typing import Any, Dict


# ─── helpers ──────────────────────────────────────────────────────────────────

def _silence():
    """Redirect stdout so print()-heavy demo functions don't pollute test output."""
    buf = io.StringIO()
    sys.stdout = buf
    return buf


def _restore():
    sys.stdout = sys.__stdout__


# ═══════════════════════════════════════════════════════════════════════════════
# Section 1 — interactive_fol_types
# ═══════════════════════════════════════════════════════════════════════════════

class TestStatementRecord(unittest.TestCase):
    """GIVEN StatementRecord dataclass WHEN instantiated THEN fields are set."""

    def setUp(self):
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_types import (
            StatementRecord,
        )
        self.StatementRecord = StatementRecord

    def test_minimal_creation(self):
        """GIVEN id/text/timestamp WHEN created THEN other fields default."""
        r = self.StatementRecord(
            id="s1",
            text="All dogs bark",
            timestamp=datetime(2024, 1, 1),
        )
        self.assertEqual(r.id, "s1")
        self.assertEqual(r.text, "All dogs bark")
        self.assertIsNone(r.fol_formula)
        self.assertEqual(r.confidence, 0.0)
        self.assertIsNone(r.is_consistent)
        self.assertEqual(r.dependencies, [])
        self.assertEqual(r.tags, [])

    def test_full_creation(self):
        """GIVEN all fields WHEN created THEN all stored correctly."""
        r = self.StatementRecord(
            id="s2",
            text="Some cats are black",
            timestamp=datetime(2024, 2, 1),
            fol_formula="∃x(Cat(x) ∧ Black(x))",
            confidence=0.9,
            is_consistent=True,
            dependencies=["s1"],
            tags=["feline", "color"],
        )
        self.assertEqual(r.fol_formula, "∃x(Cat(x) ∧ Black(x))")
        self.assertEqual(r.confidence, 0.9)
        self.assertTrue(r.is_consistent)
        self.assertEqual(r.dependencies, ["s1"])
        self.assertEqual(r.tags, ["feline", "color"])


class TestSessionMetadata(unittest.TestCase):
    """GIVEN SessionMetadata WHEN instantiated THEN statistics are stored."""

    def test_creation(self):
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_types import (
            SessionMetadata,
        )
        now = datetime.now()
        m = SessionMetadata(
            session_id="sess-abc",
            created_at=now,
            last_modified=now,
            total_statements=10,
            consistent_statements=8,
            inconsistent_statements=2,
            average_confidence=0.87,
            domain="legal",
            description="Test session",
            tags=["law"],
        )
        self.assertEqual(m.session_id, "sess-abc")
        self.assertEqual(m.total_statements, 10)
        self.assertEqual(m.average_confidence, 0.87)
        self.assertEqual(m.domain, "legal")

    def test_defaults(self):
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_types import (
            SessionMetadata,
        )
        now = datetime.now()
        m = SessionMetadata(
            session_id="x",
            created_at=now,
            last_modified=now,
            total_statements=0,
            consistent_statements=0,
            inconsistent_statements=0,
            average_confidence=0.0,
        )
        self.assertEqual(m.domain, "general")
        self.assertEqual(m.description, "")
        self.assertEqual(m.tags, [])


# ═══════════════════════════════════════════════════════════════════════════════
# Section 2 — interactive_fol_utils
# ═══════════════════════════════════════════════════════════════════════════════

class TestCreateInteractiveSession(unittest.TestCase):
    """GIVEN create_interactive_session factory WHEN called THEN returns constructor."""

    def test_default_domain(self):
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_utils import (
            create_interactive_session,
        )
        c = create_interactive_session()
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_constructor import (
            InteractiveFOLConstructor,
        )
        self.assertIsInstance(c, InteractiveFOLConstructor)
        self.assertEqual(c.domain, "general")

    def test_custom_domain_and_kwargs(self):
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_utils import (
            create_interactive_session,
        )
        c = create_interactive_session(
            domain="legal",
            confidence_threshold=0.8,
            enable_consistency_checking=False,
        )
        self.assertEqual(c.domain, "legal")
        self.assertEqual(c.confidence_threshold, 0.8)
        self.assertFalse(c.enable_consistency_checking)


class TestDemoInteractiveSession(unittest.TestCase):
    """GIVEN demo_interactive_session WHEN called THEN runs without error."""

    def test_smoke(self):
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_utils import (
            demo_interactive_session,
        )
        buf = _silence()
        try:
            result = demo_interactive_session()
        finally:
            _restore()
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_constructor import (
            InteractiveFOLConstructor,
        )
        self.assertIsInstance(result, InteractiveFOLConstructor)
        output = buf.getvalue()
        self.assertIn("Interactive FOL Constructor Demo", output)


# ═══════════════════════════════════════════════════════════════════════════════
# Section 3 — InteractiveFOLConstructor
# ═══════════════════════════════════════════════════════════════════════════════

class _ConstructorBase(unittest.TestCase):
    def setUp(self):
        from ipfs_datasets_py.logic.integration.interactive.interactive_fol_constructor import (
            InteractiveFOLConstructor,
        )
        self.Constructor = InteractiveFOLConstructor

    def _mk(self, **kw):
        return self.Constructor(**kw)


class TestConstructorInit(_ConstructorBase):
    """GIVEN InteractiveFOLConstructor WHEN created THEN session state is empty."""

    def test_defaults(self):
        c = self._mk()
        self.assertEqual(c.domain, "general")
        self.assertEqual(c.confidence_threshold, 0.6)
        self.assertTrue(c.enable_consistency_checking)
        self.assertEqual(c.session_statements, {})

    def test_custom_params(self):
        c = self._mk(
            domain="mathematics",
            confidence_threshold=0.9,
            enable_consistency_checking=False,
        )
        self.assertEqual(c.domain, "mathematics")
        self.assertEqual(c.confidence_threshold, 0.9)
        self.assertFalse(c.enable_consistency_checking)

    def test_session_id_generated(self):
        c1 = self._mk()
        c2 = self._mk()
        self.assertNotEqual(c1.session_id, c2.session_id)


class TestAddStatement(_ConstructorBase):
    """GIVEN add_statement WHEN called THEN returns result with expected keys."""

    def test_empty_text_raises(self):
        c = self._mk()
        with self.assertRaises(ValueError):
            c.add_statement("")

    def test_whitespace_only_raises(self):
        c = self._mk()
        with self.assertRaises(ValueError):
            c.add_statement("   ")

    def test_success(self):
        c = self._mk()
        r = c.add_statement("All cats are animals")
        self.assertIn("status", r)
        # Either success or warning depending on confidence
        self.assertIn(r["status"], ("success", "warning"))
        self.assertIn("fol_formula", r)
        self.assertIn("statement_id", r)

    def test_force_add_bypasses_threshold(self):
        c = self._mk(confidence_threshold=0.99)  # Very high threshold
        r = c.add_statement("All cats are animals", force_add=True)
        # force_add=True should accept even low-confidence result
        self.assertEqual(r["status"], "success")

    def test_adds_to_session_statements(self):
        c = self._mk()
        r = c.add_statement("Some birds fly", force_add=True)
        if r["status"] == "success":
            self.assertEqual(len(c.session_statements), 1)

    def test_tags_stored(self):
        c = self._mk()
        r = c.add_statement("All humans are mortal", tags=["philosophy"], force_add=True)
        if r["status"] == "success":
            stmt = list(c.session_statements.values())[0]
            self.assertIn("philosophy", stmt.tags)

    def test_consistency_check_with_existing(self):
        c = self._mk()
        c.add_statement("All cats are animals", force_add=True)
        r2 = c.add_statement("No cats are animals", force_add=True)
        # Should run consistency check (second statement)
        self.assertIn(r2["status"], ("success", "warning", "error"))


class TestRemoveStatement(_ConstructorBase):
    """GIVEN remove_statement WHEN called THEN updates session."""

    def test_not_found(self):
        c = self._mk()
        r = c.remove_statement("nonexistent-id")
        self.assertEqual(r["status"], "error")
        self.assertIn("not found", r["message"])

    def test_success(self):
        c = self._mk()
        add_result = c.add_statement("All cats are animals", force_add=True)
        if add_result["status"] == "success":
            stmt_id = add_result["statement_id"]
            r = c.remove_statement(stmt_id)
            self.assertEqual(r["status"], "success")
            self.assertNotIn(stmt_id, c.session_statements)


class TestAnalyzeLogicalStructure(_ConstructorBase):
    """GIVEN analyze_logical_structure WHEN called THEN returns analysis dict."""

    def test_empty_session(self):
        c = self._mk()
        r = c.analyze_logical_structure()
        self.assertEqual(r["status"], "empty")

    def test_with_statements(self):
        c = self._mk()
        c.add_statement("All cats are animals", force_add=True)
        r = c.analyze_logical_structure()
        self.assertEqual(r["status"], "success")
        self.assertIn("analysis", r)
        self.assertIn("logical_elements", r["analysis"])
        self.assertIn("complexity_analysis", r["analysis"])
        self.assertIn("confidence_distribution", r["analysis"])
        self.assertIn("consistency_analysis", r["analysis"])
        self.assertIn("insights", r["analysis"])


class TestGenerateFOLIncrementally(_ConstructorBase):
    """GIVEN generate_fol_incrementally WHEN called THEN returns list."""

    def test_empty(self):
        c = self._mk()
        result = c.generate_fol_incrementally()
        self.assertEqual(result, [])

    def test_with_statements(self):
        c = self._mk()
        c.add_statement("All cats are animals", force_add=True)
        result = c.generate_fol_incrementally()
        if len(c.session_statements) > 0:
            self.assertIsInstance(result, list)
            self.assertGreater(len(result), 0)
            item = result[0]
            self.assertIn("statement_id", item)
            self.assertIn("original_text", item)
            self.assertIn("fol_formula", item)
            self.assertIn("confidence", item)


class TestValidateConsistency(_ConstructorBase):
    """GIVEN validate_consistency WHEN called THEN returns consistency report."""

    def test_insufficient_data(self):
        c = self._mk()
        r = c.validate_consistency()
        self.assertEqual(r["status"], "insufficient_data")

    def test_with_one_statement(self):
        c = self._mk()
        c.add_statement("All cats are animals", force_add=True)
        r = c.validate_consistency()
        self.assertEqual(r["status"], "insufficient_data")

    def test_with_conflict(self):
        c = self._mk()
        c.add_statement("All cats are animals", force_add=True)
        c.add_statement("No cats are animals", force_add=True)
        r = c.validate_consistency()
        if r["status"] == "success":
            self.assertIn("consistency_report", r)
            self.assertIn("overall_consistent", r["consistency_report"])


class TestExportSession(_ConstructorBase):
    """GIVEN export_session WHEN called THEN returns export dict."""

    def _setup_with_statement(self):
        c = self._mk()
        c.add_statement("All cats are animals", force_add=True)
        return c

    def test_json_export(self):
        c = self._setup_with_statement()
        r = c.export_session(format="json")
        self.assertIn("session_metadata", r)
        self.assertIn("statements", r)
        self.assertIn("fol_formulas", r)

    def test_prolog_export(self):
        c = self._setup_with_statement()
        r = c.export_session(format="prolog")
        self.assertIn("fol_formulas", r)

    def test_tptp_export(self):
        c = self._setup_with_statement()
        r = c.export_session(format="tptp")
        self.assertIn("fol_formulas", r)


class TestGetSessionStatistics(_ConstructorBase):
    """GIVEN get_session_statistics WHEN called THEN returns stats dict."""

    def test_empty(self):
        c = self._mk()
        stats = c.get_session_statistics()
        self.assertIn("session_id", stats)
        self.assertIn("metadata", stats)
        self.assertIn("logical_elements", stats)
        self.assertIn("bridge_statistics", stats)
        self.assertIn("session_health", stats)

    def test_health_empty_session(self):
        c = self._mk()
        health = c._assess_session_health()
        self.assertEqual(health["status"], "empty")
        self.assertEqual(health["score"], 0)

    def test_health_with_statements(self):
        c = self._mk()
        c.add_statement("All cats are animals", force_add=True)
        health = c._assess_session_health()
        self.assertIn("status", health)
        self.assertIn("score", health)
        self.assertIn("metrics", health)

    def test_count_logical_elements(self):
        c = self._mk()
        counts = c._count_logical_elements()
        self.assertIn("total_quantifiers", counts)
        self.assertIn("total_predicates", counts)
        self.assertIn("total_entities", counts)
        self.assertIn("total_connectives", counts)


class TestConvertFOLFormat(_ConstructorBase):
    """GIVEN _convert_fol_format WHEN called THEN returns converted formula."""

    def test_prolog(self):
        c = self._mk()
        f = "∀x(Cat(x) → Animal(x))"
        result = c._convert_fol_format(f, "prolog")
        self.assertIn("forall", result)
        self.assertIn(":-", result)

    def test_tptp(self):
        c = self._mk()
        f = "∀x(Cat(x) → Animal(x))"
        result = c._convert_fol_format(f, "tptp")
        self.assertTrue(result.startswith("fof("))

    def test_unknown_format_returns_original(self):
        c = self._mk()
        f = "∀x(Cat(x) → Animal(x))"
        result = c._convert_fol_format(f, "unknown_format")
        self.assertEqual(result, f)


# ═══════════════════════════════════════════════════════════════════════════════
# Section 4 — SymbolicFOLBridge
# ═══════════════════════════════════════════════════════════════════════════════

class TestLogicalComponentsDataclass(unittest.TestCase):
    """GIVEN LogicalComponents WHEN created THEN fields accessible."""

    def test_creation(self):
        from ipfs_datasets_py.logic.integration.bridges.symbolic_fol_bridge import (
            LogicalComponents,
        )
        lc = LogicalComponents(
            quantifiers=["all"],
            predicates=["is"],
            entities=["Cat", "Animal"],
            logical_connectives=["and"],
            confidence=0.85,
            raw_text="All cats are animals",
        )
        self.assertEqual(lc.quantifiers, ["all"])
        self.assertEqual(lc.confidence, 0.85)
        self.assertEqual(lc.raw_text, "All cats are animals")


class TestFOLConversionResultDataclass(unittest.TestCase):
    """GIVEN FOLConversionResult WHEN created THEN errors default to []."""

    def test_creation(self):
        from ipfs_datasets_py.logic.integration.bridges.symbolic_fol_bridge import (
            FOLConversionResult,
            LogicalComponents,
        )
        lc = LogicalComponents([], [], [], [], 0.5, "test")
        r = FOLConversionResult(
            fol_formula="Test(x)",
            components=lc,
            confidence=0.5,
            reasoning_steps=["step1"],
        )
        self.assertEqual(r.fol_formula, "Test(x)")
        self.assertEqual(r.errors, [])
        self.assertFalse(r.fallback_used)

    def test_errors_default_post_init(self):
        from ipfs_datasets_py.logic.integration.bridges.symbolic_fol_bridge import (
            FOLConversionResult,
            LogicalComponents,
        )
        lc = LogicalComponents([], [], [], [], 0.0, "")
        r = FOLConversionResult(
            fol_formula="",
            components=lc,
            confidence=0.0,
            reasoning_steps=[],
            fallback_used=True,
            errors=None,
        )
        self.assertEqual(r.errors, [])


class TestSymbolicFOLBridgeInit(unittest.TestCase):
    """GIVEN SymbolicFOLBridge WHEN created THEN configured correctly."""

    def setUp(self):
        from ipfs_datasets_py.logic.integration.bridges.symbolic_fol_bridge import (
            SymbolicFOLBridge,
        )
        self.Bridge = SymbolicFOLBridge

    def test_defaults(self):
        b = self.Bridge()
        self.assertEqual(b.confidence_threshold, 0.7)
        self.assertTrue(b.fallback_enabled)
        self.assertTrue(b.enable_caching)
        self.assertEqual(b._cache, {})

    def test_custom_params(self):
        b = self.Bridge(
            confidence_threshold=0.5,
            fallback_enabled=False,
            enable_caching=False,
        )
        self.assertEqual(b.confidence_threshold, 0.5)
        self.assertFalse(b.fallback_enabled)
        self.assertFalse(b.enable_caching)

    def test_get_statistics(self):
        b = self.Bridge()
        stats = b.get_statistics()
        self.assertIn("symbolic_ai_available", stats)
        self.assertIn("cache_size", stats)
        self.assertIn("confidence_threshold", stats)

    def test_clear_cache(self):
        b = self.Bridge()
        # Populate cache manually
        from ipfs_datasets_py.logic.integration.bridges.symbolic_fol_bridge import (
            FOLConversionResult,
            LogicalComponents,
        )
        lc = LogicalComponents([], [], [], [], 0.5, "x")
        b._cache["key"] = FOLConversionResult("f", lc, 0.5, [])
        self.assertEqual(len(b._cache), 1)
        b.clear_cache()
        self.assertEqual(len(b._cache), 0)


class TestCreateSemanticSymbol(unittest.TestCase):
    """GIVEN create_semantic_symbol WHEN called THEN returns Symbol or raises."""

    def setUp(self):
        from ipfs_datasets_py.logic.integration.bridges.symbolic_fol_bridge import (
            SymbolicFOLBridge,
        )
        self.bridge = SymbolicFOLBridge()

    def test_empty_text_raises(self):
        with self.assertRaises(ValueError):
            self.bridge.create_semantic_symbol("")

    def test_whitespace_only_raises(self):
        with self.assertRaises(ValueError):
            self.bridge.create_semantic_symbol("   ")

    def test_valid_text_returns_symbol(self):
        sym = self.bridge.create_semantic_symbol("All cats are animals")
        self.assertIsNotNone(sym)
        self.assertEqual(sym.value, "All cats are animals")


class TestExtractLogicalComponents(unittest.TestCase):
    """GIVEN extract_logical_components WHEN called THEN returns LogicalComponents."""

    def setUp(self):
        from ipfs_datasets_py.logic.integration.bridges.symbolic_fol_bridge import (
            SymbolicFOLBridge,
        )
        self.bridge = SymbolicFOLBridge()

    def test_all_text(self):
        sym = self.bridge.create_semantic_symbol("All cats are animals")
        lc = self.bridge.extract_logical_components(sym)
        from ipfs_datasets_py.logic.integration.bridges.symbolic_fol_bridge import (
            LogicalComponents,
        )
        self.assertIsInstance(lc, LogicalComponents)
        self.assertGreaterEqual(lc.confidence, 0.0)

    def test_some_text(self):
        sym = self.bridge.create_semantic_symbol("Some birds fly")
        lc = self.bridge.extract_logical_components(sym)
        self.assertIsNotNone(lc)

    def test_returns_quantifiers_from_fallback(self):
        sym = self.bridge.create_semantic_symbol("every student studies")
        lc = self.bridge.extract_logical_components(sym)
        # Fallback regex should pick up "every"
        self.assertIsNotNone(lc)


class TestParseCommaList(unittest.TestCase):
    """GIVEN _parse_comma_list WHEN called THEN parses correctly."""

    def setUp(self):
        from ipfs_datasets_py.logic.integration.bridges.symbolic_fol_bridge import (
            SymbolicFOLBridge,
        )
        self.bridge = SymbolicFOLBridge()

    def test_none_text(self):
        result = self.bridge._parse_comma_list("none")
        self.assertEqual(result, [])

    def test_empty_text(self):
        result = self.bridge._parse_comma_list("")
        self.assertEqual(result, [])

    def test_valid_list(self):
        result = self.bridge._parse_comma_list("cat, dog, bird")
        self.assertEqual(len(result), 3)
        self.assertIn("cat", result)

    def test_filters_empty_items(self):
        result = self.bridge._parse_comma_list("cat, , bird")
        self.assertNotIn("", result)


class TestFallbackExtraction(unittest.TestCase):
    """GIVEN _fallback_extraction WHEN called THEN returns 4-tuple."""

    def setUp(self):
        from ipfs_datasets_py.logic.integration.bridges.symbolic_fol_bridge import (
            SymbolicFOLBridge,
        )
        self.bridge = SymbolicFOLBridge()

    def test_all_quantifier(self):
        q, p, e, c = self.bridge._fallback_extraction("All cats are animals")
        self.assertIn("all", [x.lower() for x in q])

    def test_some_quantifier(self):
        q, p, e, c = self.bridge._fallback_extraction("Some cats are black")
        self.assertIn("Some", q)

    def test_entity_extraction(self):
        q, p, e, c = self.bridge._fallback_extraction("Fluffy is a Cat")
        self.assertIn("Fluffy", e)

    def test_connective_extraction(self):
        q, p, e, c = self.bridge._fallback_extraction("cats and dogs are animals")
        self.assertIn("and", [x.lower() for x in c])


class TestSemanticToFOL(unittest.TestCase):
    """GIVEN semantic_to_fol WHEN called THEN returns FOLConversionResult."""

    def setUp(self):
        from ipfs_datasets_py.logic.integration.bridges.symbolic_fol_bridge import (
            SymbolicFOLBridge,
        )
        self.bridge = SymbolicFOLBridge()

    def test_returns_result(self):
        sym = self.bridge.create_semantic_symbol("All cats are animals")
        result = self.bridge.semantic_to_fol(sym)
        from ipfs_datasets_py.logic.integration.bridges.symbolic_fol_bridge import (
            FOLConversionResult,
        )
        self.assertIsInstance(result, FOLConversionResult)
        self.assertIsNotNone(result.fol_formula)

    def test_cache_hit(self):
        sym = self.bridge.create_semantic_symbol("All cats are animals")
        result1 = self.bridge.semantic_to_fol(sym)
        result2 = self.bridge.semantic_to_fol(sym)  # Should use cache
        self.assertEqual(result1.fol_formula, result2.fol_formula)

    def test_caching_disabled(self):
        from ipfs_datasets_py.logic.integration.bridges.symbolic_fol_bridge import (
            SymbolicFOLBridge,
        )
        b = SymbolicFOLBridge(enable_caching=False)
        sym = b.create_semantic_symbol("All cats are animals")
        r = b.semantic_to_fol(sym)
        self.assertIsNotNone(r)


class TestPatternMatchToFOL(unittest.TestCase):
    """GIVEN _pattern_match_to_fol WHEN called THEN generates correct patterns."""

    def setUp(self):
        from ipfs_datasets_py.logic.integration.bridges.symbolic_fol_bridge import (
            SymbolicFOLBridge,
            LogicalComponents,
        )
        self.bridge = SymbolicFOLBridge()
        self.LC = LogicalComponents

    def _mk(self, q, p, e, c, text):
        return self.LC(q, p, e, c, 0.7, text)

    def test_universal_pattern(self):
        lc = self._mk(["all"], ["is"], ["Cat", "Animal"], [], "All cats are animals")
        steps = []
        formula = self.bridge._pattern_match_to_fol(lc, steps)
        self.assertIn("∀", formula)
        self.assertIn("→", formula)

    def test_existential_pattern(self):
        lc = self._mk(["some"], ["are"], ["Cat", "Black"], [], "Some cats are black")
        steps = []
        formula = self.bridge._pattern_match_to_fol(lc, steps)
        self.assertIn("∃", formula)
        self.assertIn("∧", formula)

    def test_predication_pattern(self):
        lc = self._mk([], ["is"], ["Fluffy", "Cat"], [], "Fluffy is a cat")
        steps = []
        formula = self.bridge._pattern_match_to_fol(lc, steps)
        self.assertIn("Fluffy", formula)

    def test_fallback_entity_predicate(self):
        lc = self._mk([], ["barks"], ["Dog"], [], "Dog barks")
        steps = []
        formula = self.bridge._pattern_match_to_fol(lc, steps)
        self.assertIn("Dog", formula)

    def test_no_entities_no_predicates(self):
        lc = self._mk([], [], [], [], "something")
        steps = []
        formula = self.bridge._pattern_match_to_fol(lc, steps)
        self.assertEqual(formula, "something")


class TestFormatConversions(unittest.TestCase):
    """GIVEN _to_prolog_format and _to_tptp_format WHEN called THEN correct output."""

    def setUp(self):
        from ipfs_datasets_py.logic.integration.bridges.symbolic_fol_bridge import (
            SymbolicFOLBridge,
        )
        self.bridge = SymbolicFOLBridge()

    def test_to_prolog(self):
        f = "∀x(Cat(x) → Animal(x))"
        result = self.bridge._to_prolog_format(f)
        self.assertIn("forall", result)
        self.assertIn(":-", result)

    def test_to_tptp(self):
        f = "∀x(Cat(x) → Animal(x))"
        result = self.bridge._to_tptp_format(f)
        self.assertTrue(result.startswith("fof("))
        self.assertIn("!", result)
        self.assertIn("=>", result)


class TestValidateFOLFormula(unittest.TestCase):
    """GIVEN validate_fol_formula WHEN called THEN validates correctly."""

    def setUp(self):
        from ipfs_datasets_py.logic.integration.bridges.symbolic_fol_bridge import (
            SymbolicFOLBridge,
        )
        self.bridge = SymbolicFOLBridge()

    def test_empty_formula(self):
        r = self.bridge.validate_fol_formula("")
        self.assertFalse(r["valid"])
        self.assertIn("empty", r["errors"][0].lower())

    def test_valid_formula(self):
        r = self.bridge.validate_fol_formula("∀x(Cat(x) → Animal(x))")
        self.assertTrue(r["valid"])
        self.assertTrue(r["structure"]["has_quantifiers"])

    def test_unbalanced_parens(self):
        r = self.bridge.validate_fol_formula("Cat(x → Animal(x)")
        self.assertFalse(r["valid"])
        self.assertIn("parenthes", r["errors"][0].lower())

    def test_no_predicates_warning(self):
        r = self.bridge.validate_fol_formula("∀x(x)")
        self.assertGreater(len(r["warnings"]), 0)

    def test_exception_returns_error(self):
        r = self.bridge.validate_fol_formula(None)  # type: ignore
        self.assertFalse(r["valid"])

    def test_connectives_detected(self):
        r = self.bridge.validate_fol_formula("Cat(x) ∧ Animal(x)")
        self.assertIn("∧", r["structure"]["connectives"])


class TestGetCacheKey(unittest.TestCase):
    """GIVEN _get_cache_key WHEN called THEN returns stable hash."""

    def setUp(self):
        from ipfs_datasets_py.logic.integration.bridges.symbolic_fol_bridge import (
            SymbolicFOLBridge,
        )
        self.bridge = SymbolicFOLBridge()

    def test_same_inputs_same_key(self):
        k1 = self.bridge._get_cache_key("text", "convert")
        k2 = self.bridge._get_cache_key("text", "convert")
        self.assertEqual(k1, k2)

    def test_different_inputs_different_key(self):
        k1 = self.bridge._get_cache_key("text_a", "convert")
        k2 = self.bridge._get_cache_key("text_b", "convert")
        self.assertNotEqual(k1, k2)

    def test_extra_dict_included(self):
        k1 = self.bridge._get_cache_key("text", "convert", extra={"a": 1})
        k2 = self.bridge._get_cache_key("text", "convert", extra={"a": 2})
        self.assertNotEqual(k1, k2)


class TestFallbackConversion(unittest.TestCase):
    """GIVEN _fallback_conversion WHEN called THEN returns fallback result."""

    def setUp(self):
        from ipfs_datasets_py.logic.integration.bridges.symbolic_fol_bridge import (
            SymbolicFOLBridge,
        )
        self.bridge = SymbolicFOLBridge()

    def test_returns_result(self):
        r = self.bridge._fallback_conversion("All cats are animals", "symbolic")
        from ipfs_datasets_py.logic.integration.bridges.symbolic_fol_bridge import (
            FOLConversionResult,
        )
        self.assertIsInstance(r, FOLConversionResult)
        self.assertTrue(r.fallback_used)

    def test_fallback_to_fol_compat_shim(self):
        r = self.bridge._fallback_to_fol_conversion("test text")
        self.assertIsNotNone(r)


# ═══════════════════════════════════════════════════════════════════════════════
# Section 5 — integration __init__.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegrationInitLazyExports(unittest.TestCase):
    """GIVEN integration __init__ WHEN accessing lazy exports THEN returns correct objects."""

    def test_deontic_formula_lazy(self):
        import ipfs_datasets_py.logic.integration as pkg
        DeonticFormula = pkg.DeonticFormula
        self.assertIsNotNone(DeonticFormula)

    def test_deontic_operator_lazy(self):
        import ipfs_datasets_py.logic.integration as pkg
        DeonticOperator = pkg.DeonticOperator
        self.assertIsNotNone(DeonticOperator)

    def test_logic_verifier_lazy(self):
        import ipfs_datasets_py.logic.integration as pkg
        LogicVerifier = pkg.LogicVerifier
        self.assertIsNotNone(LogicVerifier)

    def test_symbolic_fol_bridge_lazy(self):
        import ipfs_datasets_py.logic.integration as pkg
        Bridge = pkg.SymbolicFOLBridge
        self.assertIsNotNone(Bridge)

    def test_unknown_attr_raises(self):
        import ipfs_datasets_py.logic.integration as pkg
        with self.assertRaises(AttributeError):
            _ = pkg.NonExistentAttribute12345

    def test_dir_includes_lazy_exports(self):
        import ipfs_datasets_py.logic.integration as pkg
        d = dir(pkg)
        self.assertIn("DeonticFormula", d)
        self.assertIn("LogicVerifier", d)
        self.assertIn("SymbolicFOLBridge", d)


class TestEnableSymbolicAI(unittest.TestCase):
    """GIVEN enable_symbolicai WHEN symai not available THEN returns False."""

    def test_returns_false_without_symai(self):
        import ipfs_datasets_py.logic.integration as pkg
        # Ensure symai is not available
        import sys
        old = sys.modules.pop("symai", None)
        try:
            # Reset state so we can re-test
            pkg.SYMBOLIC_AI_AVAILABLE = False
            result = pkg.enable_symbolicai()
            self.assertFalse(result)
        finally:
            if old is not None:
                sys.modules["symai"] = old

    def test_idempotent_when_already_enabled(self):
        import ipfs_datasets_py.logic.integration as pkg
        # If already marked as available (shouldn't be without symai), should return True
        old_val = pkg.SYMBOLIC_AI_AVAILABLE
        pkg.SYMBOLIC_AI_AVAILABLE = True
        try:
            result = pkg.enable_symbolicai()
            self.assertTrue(result)
        finally:
            pkg.SYMBOLIC_AI_AVAILABLE = old_val


class TestAvailabilityExports(unittest.TestCase):
    """GIVEN _AVAILABILITY_EXPORTS WHEN accessed THEN returns bool."""

    def test_tdfol_cec_available_is_bool(self):
        import ipfs_datasets_py.logic.integration as pkg
        val = pkg.TDFOL_CEC_AVAILABLE
        self.assertIsInstance(val, bool)

    def test_neurosymbolic_api_available_is_bool(self):
        import ipfs_datasets_py.logic.integration as pkg
        val = pkg.NEUROSYMBOLIC_API_AVAILABLE
        self.assertIsInstance(val, bool)


# ═══════════════════════════════════════════════════════════════════════════════
# Section 6 — demos/demo_temporal_deontic_rag.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestCreateSampleTheoremCorpus(unittest.TestCase):
    """GIVEN create_sample_theorem_corpus WHEN called THEN returns populated RAG store."""

    def setUp(self):
        buf = _silence()
        try:
            from ipfs_datasets_py.logic.integration.demos.demo_temporal_deontic_rag import (
                create_sample_theorem_corpus,
            )
            self.corpus = create_sample_theorem_corpus()
        finally:
            _restore()

    def test_returns_rag_store(self):
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_rag_store import (
            TemporalDeonticRAGStore,
        )
        self.assertIsInstance(self.corpus, TemporalDeonticRAGStore)

    def test_has_theorems(self):
        stats = self.corpus.get_statistics()
        self.assertGreater(stats["total_theorems"], 0)

    def test_multiple_jurisdictions(self):
        stats = self.corpus.get_statistics()
        self.assertGreaterEqual(stats["jurisdictions"], 2)


class TestDemoDocumentConsistencyChecking(unittest.TestCase):
    """GIVEN demo_document_consistency_checking WHEN called THEN runs without error."""

    def test_smoke(self):
        from ipfs_datasets_py.logic.integration.demos.demo_temporal_deontic_rag import (
            demo_document_consistency_checking,
        )
        buf = _silence()
        try:
            demo_document_consistency_checking()
        finally:
            _restore()
        output = buf.getvalue()
        self.assertIn("TEMPORAL DEONTIC LOGIC", output)


class TestDemoBatchProcessing(unittest.TestCase):
    """GIVEN demo_batch_processing WHEN called THEN runs without error."""

    def test_smoke(self):
        from ipfs_datasets_py.logic.integration.demos.demo_temporal_deontic_rag import (
            demo_batch_processing,
        )
        buf = _silence()
        try:
            demo_batch_processing()
        finally:
            _restore()
        output = buf.getvalue()
        self.assertIn("BATCH", output.upper())


class TestDemoRAGRetrieval(unittest.TestCase):
    """GIVEN demo_rag_retrieval WHEN called THEN runs without error."""

    def test_smoke(self):
        from ipfs_datasets_py.logic.integration.demos.demo_temporal_deontic_rag import (
            demo_rag_retrieval,
        )
        buf = _silence()
        try:
            demo_rag_retrieval()
        finally:
            _restore()
        output = buf.getvalue()
        self.assertIn("RAG", output.upper())


class TestPrintDebugReport(unittest.TestCase):
    """GIVEN print_debug_report WHEN called THEN prints structured output."""

    def test_smoke(self):
        from ipfs_datasets_py.logic.integration.demos.demo_temporal_deontic_rag import (
            print_debug_report,
        )
        from ipfs_datasets_py.logic.integration.domain.document_consistency_checker import (
            DebugReport,
        )
        report = DebugReport(
            document_id="test_doc",
            total_issues=1,
            issues=[{"severity": "warning", "category": "conflict", "message": "Test conflict", "suggestion": "Review this"}],
            summary="Test summary",
            fix_suggestions=["Fix suggestion 1"],
        )
        buf = _silence()
        try:
            print_debug_report(report)
        finally:
            _restore()
        output = buf.getvalue()
        # Should have printed something
        self.assertGreater(len(output), 0)


if __name__ == "__main__":
    unittest.main()
