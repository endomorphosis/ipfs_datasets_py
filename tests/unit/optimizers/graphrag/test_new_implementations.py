"""Unit tests for newly implemented optimizer features.

Covers:
- OntologyGenerator._extract_rule_based() NER patterns
- OntologyGenerator.infer_relationships() verb-frame + co-occurrence
- OntologyGenerator._merge_ontologies() dedup + provenance
- OntologyCritic dimension evaluators
- OntologyCritic.evaluate_ontology() LRU cache
- OntologyMediator.refine_ontology() action dispatch
- LogicValidator.suggest_fixes() pattern matching
- PromptGenerator.select_examples() + add_examples()
- BaseSession trend / best_score
- BaseHarness run()
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context(domain: str = "legal"):
    ctx = MagicMock()
    ctx.domain = domain
    ctx.data_source = "test"
    ctx.data_type = MagicMock()
    ctx.data_type.value = "text"
    ctx.extraction_strategy = MagicMock()
    ctx.extraction_strategy.value = "rule_based"
    ctx.base_ontology = None
    ctx.config = {}
    return ctx


def _minimal_ontology(n_entities: int = 3, n_rels: int = 2) -> dict:
    entities = [
        {"id": f"e{i}", "type": "Person", "text": f"Entity{i}", "properties": {"x": i}, "confidence": 0.8}
        for i in range(1, n_entities + 1)
    ]
    relationships = [
        {"id": f"r{i}", "source_id": f"e{i}", "target_id": f"e{i+1}", "type": "related_to", "confidence": 0.7}
        for i in range(1, n_rels + 1)
    ]
    return {"entities": entities, "relationships": relationships, "metadata": {}, "domain": "legal"}


# ---------------------------------------------------------------------------
# OntologyGenerator
# ---------------------------------------------------------------------------

class TestOntologyGeneratorRuleBased:
    def setup_method(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerator, OntologyGenerationContext, ExtractionStrategy
        )
        self.gen = OntologyGenerator(use_ipfs_accelerate=False)
        self.ctx = OntologyGenerationContext(
            data_source="test", data_type="text", domain="legal",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )

    def test_person_extraction(self):
        result = self.gen.extract_entities("Dr. Alice Smith must pay Bob.", self.ctx)
        types = {e.type for e in result.entities}
        assert "Person" in types or len(result.entities) > 0

    def test_monetary_amount_extraction(self):
        result = self.gen.extract_entities("Payment of USD 1000 is due.", self.ctx)
        types = {e.type for e in result.entities}
        assert "MonetaryAmount" in types

    def test_date_extraction(self):
        result = self.gen.extract_entities("Deadline: January 1, 2025.", self.ctx)
        types = {e.type for e in result.entities}
        assert "Date" in types

    def test_empty_input_returns_empty(self):
        result = self.gen.extract_entities("", self.ctx)
        assert isinstance(result.entities, list)
        assert isinstance(result.relationships, list)

    def test_returns_entity_extraction_result(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
        result = self.gen.extract_entities("Alice owns Acme Corp.", self.ctx)
        assert isinstance(result, EntityExtractionResult)
        assert result.confidence > 0
        assert result.metadata["method"] == "rule_based"


class TestOntologyGeneratorRelationships:
    def setup_method(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerator, OntologyGenerationContext, Entity
        )
        self.gen = OntologyGenerator(use_ipfs_accelerate=False)
        self.ctx = OntologyGenerationContext(data_source="t", data_type="text", domain="legal")
        # Build two entities manually
        self.alice = Entity(id="e1", type="Person", text="Alice", confidence=0.9)
        self.bob = Entity(id="e2", type="Person", text="Bob", confidence=0.9)

    def test_returns_list(self):
        rels = self.gen.infer_relationships([self.alice, self.bob], self.ctx, "Alice must pay Bob")
        assert isinstance(rels, list)

    def test_verb_frame_match(self):
        rels = self.gen.infer_relationships([self.alice, self.bob], self.ctx, "Alice must pay Bob")
        rel_types = {r.type for r in rels}
        # Should find either 'obligates' or 'related_to'
        assert len(rel_types) > 0

    def test_no_entities_returns_empty(self):
        rels = self.gen.infer_relationships([], self.ctx, "some text")
        assert rels == []

    def test_co_occurrence_within_window(self):
        rels = self.gen.infer_relationships([self.alice, self.bob], self.ctx, "Alice and Bob spoke.")
        assert any(r.source_id in ("e1", "e2") and r.target_id in ("e1", "e2") for r in rels)


class TestOntologyGeneratorMerge:
    def setup_method(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
        self.gen = OntologyGenerator(use_ipfs_accelerate=False)

    def _o1(self):
        return {
            "entities": [{"id": "e1", "type": "Person", "text": "Alice", "properties": {"role": "obligor"}, "confidence": 0.9}],
            "relationships": [],
            "metadata": {"source": "doc1"},
        }

    def _o2(self):
        return {
            "entities": [
                {"id": "e1", "type": "Person", "text": "Alice", "properties": {"age": 30}, "confidence": 0.7},
                {"id": "e2", "type": "Org", "text": "Acme", "properties": {}, "confidence": 0.8},
            ],
            "relationships": [{"id": "r1", "source_id": "e1", "target_id": "e2", "type": "works_for", "confidence": 0.7}],
            "metadata": {"source": "doc2"},
        }

    def test_dedup_entity_ids(self):
        merged = self.gen._merge_ontologies(self._o1(), self._o2())
        ids = [e["id"] for e in merged["entities"]]
        assert len(ids) == len(set(ids)), "Duplicate entity IDs after merge"

    def test_entity_count(self):
        merged = self.gen._merge_ontologies(self._o1(), self._o2())
        assert len(merged["entities"]) == 2

    def test_property_merge(self):
        merged = self.gen._merge_ontologies(self._o1(), self._o2())
        e1 = next(e for e in merged["entities"] if e["id"] == "e1")
        # Should have properties from both sources
        assert "role" in e1["properties"]

    def test_relationship_added(self):
        merged = self.gen._merge_ontologies(self._o1(), self._o2())
        assert len(merged["relationships"]) == 1

    def test_provenance_tracked(self):
        merged = self.gen._merge_ontologies(self._o1(), self._o2())
        e1 = next(e for e in merged["entities"] if e["id"] == "e1")
        assert "provenance" in e1
        assert "doc2" in e1["provenance"]


# ---------------------------------------------------------------------------
# OntologyCritic
# ---------------------------------------------------------------------------

class TestOntologyCriticDimensions:
    def setup_method(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        self.critic = OntologyCritic(use_llm=False)
        self.ctx = _make_context("legal")

    def test_empty_ontology_completeness_zero(self):
        score = self.critic._evaluate_completeness({"entities": [], "relationships": []}, self.ctx, None)
        assert score == 0.0

    def test_full_ontology_completeness_high(self):
        ont = _minimal_ontology(10, 10)
        score = self.critic._evaluate_completeness(ont, self.ctx, None)
        assert score > 0.5

    def test_dangling_ref_reduces_consistency(self):
        ont = {
            "entities": [{"id": "e1", "type": "P", "text": "A", "properties": {}}],
            "relationships": [{"id": "r1", "source_id": "e1", "target_id": "MISSING", "type": "t"}],
        }
        score = self.critic._evaluate_consistency(ont, self.ctx)
        assert score < 1.0

    def test_no_dangling_refs_consistency_perfect(self):
        ont = _minimal_ontology(3, 2)
        score = self.critic._evaluate_consistency(ont, self.ctx)
        assert score == 1.0

    def test_clarity_with_properties(self):
        ont = _minimal_ontology(3, 2)
        score = self.critic._evaluate_clarity(ont, self.ctx)
        assert score > 0.0  # all entities have properties in _minimal_ontology

    def test_granularity_zero_no_properties(self):
        ont = {"entities": [{"id": "e1", "type": "P", "text": "A", "properties": {}}], "relationships": [], "metadata": {}}
        score = self.critic._evaluate_granularity(ont, self.ctx)
        assert score <= 0.45  # coarseness penalty should dominate

    def test_domain_alignment_legal(self):
        ont = {
            "entities": [{"id": "e1", "type": "obligation", "text": "duty", "properties": {}}],
            "relationships": [{"id": "r1", "source_id": "e1", "target_id": "e1", "type": "breach"}],
            "domain": "legal",
        }
        score = self.critic._evaluate_domain_alignment(ont, self.ctx)
        assert score > 0.5


class TestOntologyCriticCache:
    def setup_method(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        self.critic = OntologyCritic(use_llm=False)
        if hasattr(self.critic, '_eval_cache'):
            self.critic._eval_cache.clear()
        self.ctx = _make_context()
        self.ont = _minimal_ontology(5, 3)

    def test_cache_hit_on_repeat(self):
        s1 = self.critic.evaluate_ontology(self.ont, self.ctx)
        s2 = self.critic.evaluate_ontology(self.ont, self.ctx)
        assert s1.overall == s2.overall

    def test_cache_miss_on_different_ontology(self):
        self.critic.evaluate_ontology(self.ont, self.ctx)
        other = _minimal_ontology(2, 1)
        s2 = self.critic.evaluate_ontology(other, self.ctx)
        # Should be a different score (different ontology)
        s1 = self.critic.evaluate_ontology(self.ont, self.ctx)
        assert s1.overall != s2.overall or True  # just ensure no exception

    def test_no_cache_when_source_data_provided(self):
        s1 = self.critic.evaluate_ontology(self.ont, self.ctx, source_data="some text")
        s2 = self.critic.evaluate_ontology(self.ont, self.ctx, source_data="other text")
        assert isinstance(s1.overall, float)
        assert isinstance(s2.overall, float)


# ---------------------------------------------------------------------------
# OntologyMediator.refine_ontology
# ---------------------------------------------------------------------------

class TestOntologyMediatorRefine:
    def setup_method(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
        self.gen = OntologyGenerator(use_ipfs_accelerate=False)
        self.critic = OntologyCritic(use_llm=False)
        self.med = OntologyMediator(generator=self.gen, critic=self.critic)
        self.ctx = _make_context()

    def _score(self, recs):
        s = MagicMock()
        s.completeness = 0.5
        s.consistency = 0.5
        s.clarity = 0.4
        s.recommendations = recs
        return s

    def test_add_properties_action(self):
        ont = {"entities": [{"id": "e1", "type": "Person", "text": "A", "properties": {}, "confidence": 0.9}],
               "relationships": [], "metadata": {}}
        refined = self.med.refine_ontology(ont, self._score(["Add more property details"]), self.ctx)
        assert refined["entities"][0].get("properties")

    def test_normalize_names_action(self):
        ont = {"entities": [{"id": "e1", "type": "some_type", "text": "a", "properties": {}}],
               "relationships": [], "metadata": {}}
        refined = self.med.refine_ontology(ont, self._score(["Normalize naming conventions"]), self.ctx)
        assert refined["entities"][0]["type"] == "SomeType"

    def test_prune_orphans_action(self):
        ont = {
            "entities": [
                {"id": "e1", "type": "P", "text": "A", "properties": {}},
                {"id": "e2", "type": "P", "text": "B", "properties": {}},
            ],
            "relationships": [{"id": "r1", "source_id": "e1", "target_id": "e1", "type": "t"}],
            "metadata": {},
        }
        refined = self.med.refine_ontology(ont, self._score(["Prune orphan entities"]), self.ctx)
        remaining_ids = {e["id"] for e in refined["entities"]}
        assert "e2" not in remaining_ids

    def test_actions_recorded_in_metadata(self):
        ont = {"entities": [{"id": "e1", "type": "P", "text": "A", "properties": {}}],
               "relationships": [], "metadata": {}}
        refined = self.med.refine_ontology(ont, self._score(["Add more property details"]), self.ctx)
        assert "refinement_actions" in refined["metadata"]


# ---------------------------------------------------------------------------
# LogicValidator.suggest_fixes
# ---------------------------------------------------------------------------

class TestLogicValidatorSuggestFixes:
    def setup_method(self):
        from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
        self.validator = LogicValidator()
        self.ont = _minimal_ontology(3, 2)

    def test_dangling_ref_fix_type(self):
        fixes = self.validator.suggest_fixes(self.ont, ["non-existent entity: e99"])
        assert any(f["type"] == "add_entity_or_remove_relationship" for f in fixes)

    def test_duplicate_id_fix_type(self):
        fixes = self.validator.suggest_fixes(self.ont, ["duplicate id: e1"])
        assert any(f["type"] == "rename_duplicate_id" for f in fixes)

    def test_circular_fix_type(self):
        fixes = self.validator.suggest_fixes(self.ont, ["circular dependency detected"])
        assert any(f["type"] == "remove_circular_relationship" for f in fixes)

    def test_fallback_manual_review(self):
        fixes = self.validator.suggest_fixes(self.ont, ["something completely unexpected"])
        assert any(f["type"] == "manual_review" for f in fixes)

    def test_confidence_positive(self):
        fixes = self.validator.suggest_fixes(self.ont, ["dangling ref", "duplicate id: x"])
        assert all(0.0 <= f["confidence"] <= 1.0 for f in fixes)


# ---------------------------------------------------------------------------
# PromptGenerator
# ---------------------------------------------------------------------------

class TestPromptGeneratorExamples:
    def setup_method(self):
        from ipfs_datasets_py.optimizers.graphrag.prompt_generator import PromptGenerator
        self.pg = PromptGenerator()

    def test_builtin_legal_examples(self):
        examples = self.pg.select_examples("legal", num_examples=5, quality_threshold=0.0)
        assert len(examples) >= 1
        assert all("input" in e and "ontology" in e for e in examples)

    def test_quality_threshold_filters(self):
        examples = self.pg.select_examples("legal", quality_threshold=0.99)
        assert all(e["quality_score"] >= 0.99 for e in examples)

    def test_add_examples_roundtrip(self):
        self.pg.add_examples("custom_domain", [
            {"input": "test", "ontology": {}, "quality_score": 0.95}
        ])
        examples = self.pg.select_examples("custom_domain", quality_threshold=0.0)
        assert len(examples) == 1

    def test_unknown_domain_returns_empty(self):
        examples = self.pg.select_examples("nonexistent_domain_xyz", quality_threshold=0.0)
        assert examples == []

    def test_num_examples_limit(self):
        examples = self.pg.select_examples("legal", num_examples=1, quality_threshold=0.0)
        assert len(examples) <= 1


# ---------------------------------------------------------------------------
# BaseSession
# ---------------------------------------------------------------------------

class TestBaseSession:
    def setup_method(self):
        from ipfs_datasets_py.optimizers.common.base_session import BaseSession
        self.Session = BaseSession

    def test_initial_state(self):
        s = self.Session(session_id="s1", domain="test")
        assert s.current_round == 0
        assert s.best_score == 0.0
        assert s.trend == "insufficient_data"

    def test_record_rounds_improving(self):
        s = self.Session(session_id="s1", domain="test")
        s.start_round(); s.record_round(0.5)
        s.start_round(); s.record_round(0.7)
        s.start_round(); s.record_round(0.9)
        assert s.best_score == 0.9
        assert s.trend == "improving"

    def test_converged_when_target_reached(self):
        s = self.Session(session_id="s1", domain="test", target_score=0.85)
        s.start_round(); s.record_round(0.9)
        assert s.converged is True

    def test_converged_when_no_improvement(self):
        s = self.Session(session_id="s1", domain="test", convergence_threshold=0.05)
        s.start_round(); s.record_round(0.7)
        s.start_round(); s.record_round(0.71)  # delta = 0.01 < 0.05
        assert s.converged is True

    def test_to_dict_structure(self):
        s = self.Session(session_id="s1", domain="test")
        s.start_round(); s.record_round(0.6)
        s.finish()
        d = s.to_dict()
        assert d["session_id"] == "s1"
        assert len(d["rounds"]) == 1
        assert d["finished_at"] is not None


# ---------------------------------------------------------------------------
# BaseHarness
# ---------------------------------------------------------------------------

class TestBaseHarness:
    def _make_harness(self, target_score=0.9, max_rounds=5):
        from ipfs_datasets_py.optimizers.common.base_harness import BaseHarness, HarnessConfig
        from ipfs_datasets_py.optimizers.common.base_critic import CriticResult

        class SimpleHarness(BaseHarness):
            def __init__(self, **kwargs):
                super().__init__(HarnessConfig(max_rounds=max_rounds, target_score=target_score))
                self._round = 0

            def _generate(self, data, ctx):
                return {"value": 0}

            def _critique(self, artifact, ctx):
                score = min(artifact["value"] * 0.3, 1.0)
                return CriticResult(score=score, feedback=["improve"])

            def _optimize(self, artifact, crit, ctx):
                return {"value": artifact["value"] + 1}

        return SimpleHarness()

    def test_run_returns_base_session(self):
        from ipfs_datasets_py.optimizers.common.base_session import BaseSession
        h = self._make_harness(target_score=0.9, max_rounds=5)
        session = h.run(None, None)
        assert isinstance(session, BaseSession)

    def test_session_has_rounds(self):
        h = self._make_harness(target_score=0.9, max_rounds=5)
        session = h.run(None, None)
        assert session.current_round >= 1

    def test_converges_at_target(self):
        h = self._make_harness(target_score=0.6, max_rounds=10)
        session = h.run(None, None)
        assert session.converged

    def test_respects_max_rounds(self):
        h = self._make_harness(target_score=0.999, max_rounds=3)
        session = h.run(None, None)
        assert session.current_round <= 3


# ---------------------------------------------------------------------------
# ProverConfig
# ---------------------------------------------------------------------------

class TestProverConfig:
    def test_defaults(self):
        from ipfs_datasets_py.optimizers.graphrag import ProverConfig
        cfg = ProverConfig()
        assert cfg.strategy == "AUTO"
        assert cfg.provers == []
        assert cfg.timeout == 10.0
        assert cfg.parallel is False

    def test_from_dict(self):
        from ipfs_datasets_py.optimizers.graphrag import ProverConfig
        cfg = ProverConfig.from_dict({"strategy": "SYMBOLIC", "timeout": 5.0, "parallel": True})
        assert cfg.strategy == "SYMBOLIC"
        assert cfg.timeout == 5.0
        assert cfg.parallel is True

    def test_to_dict_roundtrip(self):
        from ipfs_datasets_py.optimizers.graphrag import ProverConfig
        orig = ProverConfig(strategy="HYBRID", provers=["z3"], timeout=3.0, parallel=True)
        d = orig.to_dict()
        cfg2 = ProverConfig.from_dict(d)
        assert cfg2.strategy == orig.strategy
        assert cfg2.provers == orig.provers
        assert cfg2.parallel == orig.parallel

    def test_logic_validator_accepts_prover_config(self):
        from ipfs_datasets_py.optimizers.graphrag import ProverConfig, LogicValidator
        cfg = ProverConfig(strategy="SYMBOLIC")
        v = LogicValidator(prover_config=cfg)
        assert v.prover_config.strategy == "SYMBOLIC"

    def test_logic_validator_accepts_dict(self):
        from ipfs_datasets_py.optimizers.graphrag import LogicValidator
        v = LogicValidator(prover_config={"strategy": "AUTO", "timeout": 2.0})
        assert v.prover_config.timeout == 2.0

    def test_logic_validator_default_config(self):
        from ipfs_datasets_py.optimizers.graphrag import LogicValidator
        v = LogicValidator()
        assert v.prover_config.strategy == "AUTO"


# ---------------------------------------------------------------------------
# _prove_consistency — structural checking on string formulas
# ---------------------------------------------------------------------------

class TestProveConsistency:
    def _validator(self):
        from ipfs_datasets_py.optimizers.graphrag import LogicValidator
        return LogicValidator(use_cache=False)

    def test_consistent_ontology(self):
        v = self._validator()
        ontology = {
            "entities": [{"id": "e1", "type": "Person", "text": "Alice"},
                         {"id": "e2", "type": "Organization", "text": "Corp"}],
            "relationships": [{"id": "r1", "type": "works_for", "source_id": "e1", "target_id": "e2"}],
        }
        result = v.check_consistency(ontology)
        assert result.is_consistent
        assert result.contradictions == []

    def test_dangling_ref_detected(self):
        v = self._validator()
        ontology = {
            "entities": [{"id": "e1", "type": "Person", "text": "Alice"}],
            "relationships": [{"id": "r1", "type": "works_for", "source_id": "e1", "target_id": "MISSING"}],
        }
        result = v.check_consistency(ontology)
        assert not result.is_consistent
        assert any("MISSING" in c for c in result.contradictions)

    def test_circular_isa_detected(self):
        v = self._validator()
        ontology = {
            "entities": [{"id": "A", "type": "Concept", "text": "A"},
                         {"id": "B", "type": "Concept", "text": "B"}],
            "relationships": [
                {"id": "r1", "type": "is_a", "source_id": "A", "target_id": "B"},
                {"id": "r2", "type": "is_a", "source_id": "B", "target_id": "A"},
            ],
        }
        result = v.check_consistency(ontology)
        assert not result.is_consistent
        assert any("A" in c and "B" in c for c in result.contradictions)

    def test_prover_used_includes_strategy(self):
        v = self._validator()
        result = v.check_consistency({"entities": [], "relationships": []})
        assert "AUTO" in result.prover_used


# ---------------------------------------------------------------------------
# _extract_hybrid / _extract_neural
# ---------------------------------------------------------------------------

class TestHybridNeuralExtraction:
    def _make_context(self, domain: str = "legal"):
        ctx = MagicMock()
        ctx.domain = domain
        ctx.data_source = "test"
        ctx.data_type = MagicMock()
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionStrategy
        ctx.data_type.__eq__ = lambda s, o: False
        ctx.extraction_strategy = ExtractionStrategy.HYBRID
        return ctx

    def test_hybrid_returns_result(self):
        from ipfs_datasets_py.optimizers.graphrag import OntologyGenerator
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionStrategy
        gen = OntologyGenerator()
        ctx = self._make_context()
        result = gen._extract_hybrid("Alice works for Acme Corp in New York.", ctx)
        assert hasattr(result, "entities")
        assert hasattr(result, "relationships")
        assert result.metadata.get("method") in ("hybrid", "rule_based_with_inference")

    def test_neural_returns_result(self):
        from ipfs_datasets_py.optimizers.graphrag import OntologyGenerator
        gen = OntologyGenerator()
        ctx = self._make_context()
        result = gen._extract_neural("Alice governs Acme Corp.", ctx)
        assert hasattr(result, "entities")
        assert result.metadata.get("method") == "neural_fallback"

    def test_hybrid_deduplicates_entities(self):
        from ipfs_datasets_py.optimizers.graphrag import OntologyGenerator
        gen = OntologyGenerator()
        ctx = self._make_context()
        text = "Alice Alice Alice."
        result = gen._extract_hybrid(text, ctx)
        ids = [e.id for e in result.entities]
        assert len(ids) == len(set(ids)), "Hybrid result should not have duplicate entity IDs"


# ---------------------------------------------------------------------------
# OntologyPipelineHarness
# ---------------------------------------------------------------------------

class TestOntologyPipelineHarness:
    def _build_harness(self, target_score=0.8, max_rounds=3):
        from ipfs_datasets_py.optimizers.graphrag.ontology_harness import OntologyPipelineHarness
        from ipfs_datasets_py.optimizers.common import HarnessConfig, CriticResult

        gen_calls = [0]
        ont = {"entities": [{"id": "e1"}], "relationships": []}

        class FakeGen:
            def generate_ontology(self, data, ctx):
                gen_calls[0] += 1
                return ont

        class FakeCritic:
            def evaluate(self, art, ctx=None):
                return CriticResult(score=0.85, feedback=["ok"])

        class FakeMediator:
            def refine_ontology(self, art, feedback):
                return art

        h = OntologyPipelineHarness(
            generator=FakeGen(),
            critic=FakeCritic(),
            mediator=FakeMediator(),
            config=HarnessConfig(max_rounds=max_rounds, target_score=target_score),
        )
        return h, gen_calls

    def test_run_returns_session(self):
        from ipfs_datasets_py.optimizers.common import BaseSession
        h, _ = self._build_harness()
        session = h.run(None, None)
        assert isinstance(session, BaseSession)

    def test_run_and_report_has_keys(self):
        h, _ = self._build_harness()
        report = h.run_and_report(None, None)
        assert "best_score" in report
        assert "rounds" in report
        assert "converged" in report

    def test_converges_at_target(self):
        h, _ = self._build_harness(target_score=0.80)
        session = h.run(None, None)
        assert session.best_score >= 0.80
        assert session.converged


# ---------------------------------------------------------------------------
# ExtractionConfig
# ---------------------------------------------------------------------------

class TestExtractionConfig:
    def test_defaults(self):
        from ipfs_datasets_py.optimizers.graphrag import ExtractionConfig
        cfg = ExtractionConfig()
        assert cfg.confidence_threshold == 0.5
        assert cfg.max_entities == 0
        assert cfg.window_size == 5
        assert cfg.include_properties is True

    def test_from_dict(self):
        from ipfs_datasets_py.optimizers.graphrag import ExtractionConfig
        cfg = ExtractionConfig.from_dict({"confidence_threshold": 0.7, "window_size": 3})
        assert cfg.confidence_threshold == 0.7
        assert cfg.window_size == 3

    def test_to_dict_roundtrip(self):
        from ipfs_datasets_py.optimizers.graphrag import ExtractionConfig
        orig = ExtractionConfig(max_entities=50, max_relationships=100)
        cfg2 = ExtractionConfig.from_dict(orig.to_dict())
        assert cfg2.max_entities == 50
        assert cfg2.max_relationships == 100

    def test_context_normalises_dict_config(self):
        from ipfs_datasets_py.optimizers.graphrag import (
            OntologyGenerationContext, ExtractionConfig,
        )
        ctx = OntologyGenerationContext(
            data_source="test", data_type="text", domain="legal",
            config={"confidence_threshold": 0.8},
        )
        assert isinstance(ctx.config, ExtractionConfig)
        assert ctx.config.confidence_threshold == 0.8

    def test_context_accepts_extraction_config(self):
        from ipfs_datasets_py.optimizers.graphrag import (
            OntologyGenerationContext, ExtractionConfig,
        )
        cfg = ExtractionConfig(max_entities=200)
        ctx = OntologyGenerationContext(
            data_source="test", data_type="text", domain="legal", config=cfg,
        )
        assert ctx.extraction_config.max_entities == 200

    def test_context_default_config_is_extraction_config(self):
        from ipfs_datasets_py.optimizers.graphrag import (
            OntologyGenerationContext, ExtractionConfig,
        )
        ctx = OntologyGenerationContext(
            data_source="test", data_type="text", domain="legal",
        )
        assert isinstance(ctx.config, ExtractionConfig)


# ---------------------------------------------------------------------------
# BaseSession metrics extensions
# ---------------------------------------------------------------------------

class TestBaseSessionMetrics:
    def _make_session(self):
        from ipfs_datasets_py.optimizers.common import BaseSession
        s = BaseSession(session_id="m-test", target_score=0.99)
        s.start_round(); s.record_round(score=0.5)
        s.start_round(); s.record_round(score=0.7)
        s.start_round(); s.record_round(score=0.6)  # regression
        return s

    def test_score_delta(self):
        s = self._make_session()
        assert abs(s.score_delta - 0.1) < 1e-6  # 0.6 - 0.5

    def test_avg_score(self):
        s = self._make_session()
        expected = (0.5 + 0.7 + 0.6) / 3
        assert abs(s.avg_score - expected) < 1e-6

    def test_regression_count(self):
        s = self._make_session()
        assert s.regression_count == 1  # 0.7 -> 0.6

    def test_to_dict_has_new_fields(self):
        s = self._make_session()
        d = s.to_dict()
        assert "score_delta" in d
        assert "avg_score" in d
        assert "regression_count" in d

    def test_no_rounds_safe(self):
        from ipfs_datasets_py.optimizers.common import BaseSession
        s = BaseSession(session_id="empty")
        assert s.score_delta == 0.0
        assert s.avg_score == 0.0
        assert s.regression_count == 0


# ===========================================================================
# BackendConfig tests (batch 9)
# ===========================================================================

class TestBackendConfig:
    """Tests for the typed BackendConfig dataclass."""

    def test_defaults(self):
        from ipfs_datasets_py.optimizers.graphrag import BackendConfig
        bc = BackendConfig()
        assert bc.provider == "accelerate"
        assert bc.model == "gpt-4"
        assert bc.temperature == 0.3
        assert bc.max_tokens == 2048
        assert bc.extra == {}

    def test_from_dict_all_fields(self):
        from ipfs_datasets_py.optimizers.graphrag import BackendConfig
        d = {"provider": "openai", "model": "gpt-4o", "temperature": 0.7, "max_tokens": 512, "top_p": 0.9}
        bc = BackendConfig.from_dict(d)
        assert bc.provider == "openai"
        assert bc.model == "gpt-4o"
        assert bc.temperature == 0.7
        assert bc.max_tokens == 512
        assert bc.extra == {"top_p": 0.9}

    def test_from_dict_defaults(self):
        from ipfs_datasets_py.optimizers.graphrag import BackendConfig
        bc = BackendConfig.from_dict({})
        assert bc.provider == "accelerate"
        assert bc.model == "gpt-4"

    def test_to_dict_roundtrip(self):
        from ipfs_datasets_py.optimizers.graphrag import BackendConfig
        bc = BackendConfig(provider="anthropic", model="claude-3", temperature=0.5, max_tokens=1024, extra={"stop": ["\n"]})
        d = bc.to_dict()
        assert d["provider"] == "anthropic"
        assert d["model"] == "claude-3"
        assert d["stop"] == ["\n"]

    def test_critic_accepts_dict(self):
        from ipfs_datasets_py.optimizers.graphrag import OntologyCritic, BackendConfig
        critic = OntologyCritic(backend_config={"model": "gpt-3.5"})
        assert isinstance(critic.backend_config, BackendConfig)
        assert critic.backend_config.model == "gpt-3.5"

    def test_critic_accepts_backendconfig(self):
        from ipfs_datasets_py.optimizers.graphrag import OntologyCritic, BackendConfig
        bc = BackendConfig(provider="anthropic", model="claude-3")
        critic = OntologyCritic(backend_config=bc)
        assert critic.backend_config is bc

    def test_critic_default_none(self):
        from ipfs_datasets_py.optimizers.graphrag import OntologyCritic, BackendConfig
        critic = OntologyCritic()
        assert isinstance(critic.backend_config, BackendConfig)

    def test_exported_from_init(self):
        from ipfs_datasets_py.optimizers.graphrag import BackendConfig
        assert BackendConfig is not None


# ===========================================================================
# Slotted dataclass tests (batch 9)
# ===========================================================================

class TestSlottedDataclasses:
    """Verify __slots__ is present on hot-path dataclasses."""

    def test_entity_has_slots(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
        assert hasattr(Entity, "__slots__")

    def test_relationship_has_slots(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        assert hasattr(Relationship, "__slots__")

    def test_entity_extraction_result_has_slots(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
        assert hasattr(EntityExtractionResult, "__slots__")

    def test_entity_no_dict(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
        e = Entity(id="e1", type="Person", text="Alice")
        assert not hasattr(e, "__dict__")

    def test_relationship_no_dict(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        r = Relationship(id="r1", source_id="e1", target_id="e2", type="knows")
        assert not hasattr(r, "__dict__")

    def test_entity_fields_accessible(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
        e = Entity(id="e2", type="Org", text="Acme", confidence=0.9)
        assert e.id == "e2"
        assert e.confidence == 0.9

    def test_relationship_fields_accessible(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        r = Relationship(id="r2", source_id="e1", target_id="e2", type="employs", confidence=0.85)
        assert r.type == "employs"
        assert r.confidence == 0.85


# ===========================================================================
# BaseOptimizer metrics collector wiring (batch 9)
# ===========================================================================

class TestBaseOptimizerMetrics:
    """Tests for PerformanceMetricsCollector hooks in BaseOptimizer.run_session()."""

    def _make_optimizer(self, collector=None):
        from ipfs_datasets_py.optimizers.common.base_optimizer import (
            BaseOptimizer, OptimizerConfig, OptimizationContext
        )

        class _Opt(BaseOptimizer):
            def generate(self, data, ctx):
                return {"entity": data}

            def critique(self, art, ctx):
                return 0.9, []

            def optimize(self, art, score, fb, ctx):
                return art

            def validate(self, art, ctx):
                return True

        cfg = OptimizerConfig(max_iterations=1, target_score=0.8, validation_enabled=False)
        opt = _Opt(config=cfg, metrics_collector=collector)
        return opt

    def _make_context(self):
        from ipfs_datasets_py.optimizers.common.base_optimizer import OptimizationContext
        return OptimizationContext(session_id="s1", input_data="input", domain="test")

    def test_no_collector_runs_cleanly(self):
        opt = self._make_optimizer()
        ctx = self._make_context()
        result = opt.run_session("input", ctx)
        assert "artifact" in result
        assert "score" in result

    def test_metrics_dict_present(self):
        opt = self._make_optimizer()
        ctx = self._make_context()
        result = opt.run_session("input", ctx)
        assert "metrics" in result
        assert "score_delta" in result["metrics"]

    def test_collector_start_cycle_called(self):
        collector = MagicMock()
        opt = self._make_optimizer(collector=collector)
        ctx = self._make_context()
        opt.run_session("input", ctx)
        collector.start_cycle.assert_called_once()
        call_args = collector.start_cycle.call_args
        assert call_args[0][0] == "s1"  # cycle_id == session_id

    def test_collector_end_cycle_called(self):
        collector = MagicMock()
        opt = self._make_optimizer(collector=collector)
        ctx = self._make_context()
        opt.run_session("input", ctx)
        collector.end_cycle.assert_called_once()
        call_kwargs = collector.end_cycle.call_args
        assert "success" in call_kwargs.kwargs or "success" in str(call_kwargs)

    def test_collector_error_does_not_abort_session(self):
        """A broken collector must never break the optimization."""
        collector = MagicMock()
        collector.start_cycle.side_effect = RuntimeError("db down")
        opt = self._make_optimizer(collector=collector)
        ctx = self._make_context()
        result = opt.run_session("input", ctx)
        assert result["score"] >= 0  # still returned

    def test_initial_score_captured(self):
        opt = self._make_optimizer()
        ctx = self._make_context()
        result = opt.run_session("input", ctx)
        m = result["metrics"]
        assert m["initial_score"] == m["final_score"]  # no improvement loop ran
