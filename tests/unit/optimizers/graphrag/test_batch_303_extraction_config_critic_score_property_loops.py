"""Property-style randomized invariants for ExtractionConfig and CriticScore."""

from __future__ import annotations

import math
import random
import string

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import (
    CriticScore,
    DIMENSION_WEIGHTS,
)


def _rand_word(rng: random.Random, n: int = 8) -> str:
    alphabet = string.ascii_lowercase
    return "".join(rng.choice(alphabet) for _ in range(n))


def test_extraction_config_randomized_roundtrip_invariants() -> None:
    rng = random.Random(44)

    for _ in range(80):
        confidence_threshold = round(rng.uniform(0.0, 1.0), 3)
        max_confidence = round(rng.uniform(confidence_threshold, 1.0), 3)
        cfg = ExtractionConfig(
            confidence_threshold=confidence_threshold,
            max_entities=rng.randint(0, 1000),
            max_relationships=rng.randint(0, 1000),
            window_size=rng.randint(1, 12),
            sentence_window=rng.randint(0, 5),
            include_properties=bool(rng.getrandbits(1)),
            domain_vocab={_rand_word(rng, 4): [_rand_word(rng, 5), _rand_word(rng, 6)]},
            custom_rules=[(r"\b[A-Z][a-z]+\b", "Person"), (r"\bUSD\b", "Currency")],
            llm_fallback_threshold=round(rng.uniform(0.0, 1.0), 3),
            min_entity_length=rng.randint(1, 8),
            stopwords=[_rand_word(rng, 3), _rand_word(rng, 4)],
            allowed_entity_types=["Person", "Organization"],
            max_confidence=max_confidence,
            enable_parallel_inference=bool(rng.getrandbits(1)),
            max_workers=rng.randint(1, 16),
        )

        cfg.validate()
        as_dict = cfg.to_dict()

        assert ExtractionConfig.from_dict(as_dict).to_dict() == as_dict
        from_json_dict = ExtractionConfig.from_json(cfg.to_json()).to_dict()
        assert from_json_dict["custom_rules"] == [list(rule) for rule in as_dict["custom_rules"]]
        assert {
            k: v for k, v in from_json_dict.items() if k != "custom_rules"
        } == {k: v for k, v in as_dict.items() if k != "custom_rules"}
        assert cfg.clone().to_dict() == as_dict


def test_critic_score_randomized_statistical_invariants() -> None:
    rng = random.Random(45)
    weight_sum = sum(DIMENSION_WEIGHTS.values())
    assert math.isclose(weight_sum, 1.0, rel_tol=1e-9, abs_tol=1e-9)

    for _ in range(120):
        dims = [rng.random() for _ in range(6)]
        score = CriticScore(
            completeness=dims[0],
            consistency=dims[1],
            clarity=dims[2],
            granularity=dims[3],
            relationship_coherence=dims[4],
            domain_alignment=dims[5],
        )

        expected = (
            DIMENSION_WEIGHTS["completeness"] * dims[0]
            + DIMENSION_WEIGHTS["consistency"] * dims[1]
            + DIMENSION_WEIGHTS["clarity"] * dims[2]
            + DIMENSION_WEIGHTS["granularity"] * dims[3]
            + DIMENSION_WEIGHTS["relationship_coherence"] * dims[4]
            + DIMENSION_WEIGHTS["domain_alignment"] * dims[5]
        )

        assert math.isclose(score.overall, expected, rel_tol=1e-12, abs_tol=1e-12)
        assert min(dims) <= score.overall <= max(dims)
        assert len(score.to_list()) == 6
        assert CriticScore.from_dict(score.to_dict()).to_list() == score.to_list()
