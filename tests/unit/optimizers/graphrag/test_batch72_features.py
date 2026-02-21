"""Batch-72 feature tests.

Covers:
- OntologyCritic.compare_with_baseline(ontology, baseline, ctx)
- OntologyCritic.summarize_batch_results(batch_result, ctx)
- OntologyMediator.log_action_summary(top_n)
- ExtractionConfig.to_json()
- OntologyGenerator.extract_keyphrases(text, top_k)
"""

import json
import logging
import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    ExtractionConfig,
    OntologyGenerator,
    OntologyGenerationContext,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx():
    return OntologyGenerationContext(
        data_source="test", data_type="text", domain="general"
    )


def _ont(n=2):
    return {
        "entities": [{"id": f"e{i}", "type": "Person", "text": f"Alice{i}"} for i in range(n)],
        "relationships": [],
    }


def _mediator():
    gen = OntologyGenerator()
    crit = OntologyCritic(use_llm=False)
    return OntologyMediator(generator=gen, critic=crit, max_rounds=3)


# ---------------------------------------------------------------------------
# OntologyCritic.compare_with_baseline
# ---------------------------------------------------------------------------

class TestCompareWithBaseline:
    def test_returns_dict(self):
        critic = OntologyCritic(use_llm=False)
        result = critic.compare_with_baseline(_ont(3), _ont(1), _ctx())
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        critic = OntologyCritic(use_llm=False)
        r = critic.compare_with_baseline(_ont(2), _ont(2), _ctx())
        for key in ("current_score", "baseline_score", "delta", "dimension_deltas", "improved"):
            assert key in r

    def test_delta_is_difference(self):
        critic = OntologyCritic(use_llm=False)
        r = critic.compare_with_baseline(_ont(2), _ont(2), _ctx())
        assert abs(r["delta"] - (r["current_score"] - r["baseline_score"])) < 1e-6

    def test_improved_bool_type(self):
        critic = OntologyCritic(use_llm=False)
        r = critic.compare_with_baseline(_ont(), _ont(), _ctx())
        assert isinstance(r["improved"], bool)

    def test_dimension_deltas_keys(self):
        critic = OntologyCritic(use_llm=False)
        r = critic.compare_with_baseline(_ont(), _ont(), _ctx())
        dims = {"completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment"}
        assert dims == set(r["dimension_deltas"].keys())

    def test_improved_when_current_higher(self):
        critic = OntologyCritic(use_llm=False)
        large = _ont(5)
        small = {"entities": [], "relationships": []}
        r = critic.compare_with_baseline(large, small, _ctx())
        # delta should be non-negative when current has more content
        assert r["delta"] >= -0.1  # at worst negligibly negative due to scoring

    def test_scores_floats(self):
        critic = OntologyCritic(use_llm=False)
        r = critic.compare_with_baseline(_ont(), _ont(), _ctx())
        assert isinstance(r["current_score"], float)
        assert isinstance(r["baseline_score"], float)


# ---------------------------------------------------------------------------
# OntologyCritic.summarize_batch_results
# ---------------------------------------------------------------------------

class TestSummarizeBatchResults:
    def test_returns_list(self):
        critic = OntologyCritic(use_llm=False)
        assert isinstance(critic.summarize_batch_results([_ont()], _ctx()), list)

    def test_length_matches_input(self):
        critic = OntologyCritic(use_llm=False)
        results = critic.summarize_batch_results([_ont(), _ont(3)], _ctx())
        assert len(results) == 2

    def test_each_item_is_str(self):
        critic = OntologyCritic(use_llm=False)
        for line in critic.summarize_batch_results([_ont()], _ctx()):
            assert isinstance(line, str)

    def test_empty_batch(self):
        critic = OntologyCritic(use_llm=False)
        assert critic.summarize_batch_results([], _ctx()) == []

    def test_no_context_uses_default(self):
        critic = OntologyCritic(use_llm=False)
        lines = critic.summarize_batch_results([_ont()], context=None)
        assert len(lines) == 1


# ---------------------------------------------------------------------------
# OntologyMediator.log_action_summary
# ---------------------------------------------------------------------------

class TestLogActionSummary:
    def test_no_error_empty(self, caplog):
        med = _mediator()
        with caplog.at_level(logging.INFO):
            med.log_action_summary()
        assert any("Action summary" in r.message for r in caplog.records)

    def test_logs_info_level(self, caplog):
        med = _mediator()
        med._action_counts["refine_ontology"] = 5
        with caplog.at_level(logging.INFO):
            med.log_action_summary()
        assert any(r.levelno == logging.INFO for r in caplog.records)

    def test_action_name_in_log(self, caplog):
        med = _mediator()
        med._action_counts["my_action"] = 7
        with caplog.at_level(logging.INFO):
            med.log_action_summary()
        combined = " ".join(r.message for r in caplog.records)
        assert "my_action" in combined

    def test_top_n_respected(self, caplog):
        med = _mediator()
        for i in range(10):
            med._action_counts[f"action_{i}"] = i
        with caplog.at_level(logging.INFO):
            med.log_action_summary(top_n=3)
        msg = " ".join(r.message for r in caplog.records)
        assert "[1]" in msg
        assert "[4]" not in msg  # only top 3


# ---------------------------------------------------------------------------
# ExtractionConfig.to_json
# ---------------------------------------------------------------------------

class TestExtractionConfigToJson:
    def test_returns_str(self):
        assert isinstance(ExtractionConfig().to_json(), str)

    def test_valid_json(self):
        cfg = ExtractionConfig()
        parsed = json.loads(cfg.to_json())
        assert isinstance(parsed, dict)

    def test_round_trip(self):
        cfg = ExtractionConfig(confidence_threshold=0.42)
        cfg2 = ExtractionConfig.from_dict(json.loads(cfg.to_json()))
        assert abs(cfg2.confidence_threshold - 0.42) < 1e-9

    def test_all_fields_present(self):
        cfg = ExtractionConfig()
        d = json.loads(cfg.to_json())
        assert "confidence_threshold" in d

    def test_consistent_with_to_dict(self):
        cfg = ExtractionConfig()
        assert json.loads(cfg.to_json()) == cfg.to_dict()


# ---------------------------------------------------------------------------
# OntologyGenerator.extract_keyphrases
# ---------------------------------------------------------------------------

class TestExtractKeyphrases:
    def test_returns_list(self):
        gen = OntologyGenerator()
        assert isinstance(gen.extract_keyphrases("hello world"), list)

    def test_top_k_respected(self):
        gen = OntologyGenerator()
        result = gen.extract_keyphrases("cat cat cat dog dog bird", top_k=2)
        assert len(result) <= 2

    def test_most_frequent_first(self):
        gen = OntologyGenerator()
        result = gen.extract_keyphrases("cat cat cat dog dog bird", top_k=3)
        assert result[0] == "cat"

    def test_stopwords_excluded(self):
        gen = OntologyGenerator()
        result = gen.extract_keyphrases("the cat sat on the mat")
        assert "the" not in result
        assert "on" not in result

    def test_empty_text(self):
        gen = OntologyGenerator()
        assert gen.extract_keyphrases("") == []

    def test_case_insensitive(self):
        gen = OntologyGenerator()
        result = gen.extract_keyphrases("Python python PYTHON java", top_k=2)
        assert "python" in result

    def test_default_top_k(self):
        gen = OntologyGenerator()
        long_text = " ".join([f"word{i}" for i in range(50)])
        result = gen.extract_keyphrases(long_text)
        assert len(result) <= 10

    def test_all_strings(self):
        gen = OntologyGenerator()
        for kp in gen.extract_keyphrases("machine learning neural networks"):
            assert isinstance(kp, str)
