"""Golden-file tests for domain-specific ontology generation.

To refresh fixtures, run:
    PYTHONPATH=ipfs_datasets_py python ipfs_datasets_py/tests/fixtures/optimizers/graphrag/generate_golden_fixtures.py
"""

import json
from pathlib import Path

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    ExtractionConfig,
    ExtractionStrategy,
)


FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "optimizers" / "graphrag"


def _normalize(ontology):
    entities = ontology.get("entities", [])
    id_to_entity = {e.get("id"): e for e in entities}
    norm_entities = [
        {
            "text": e.get("text"),
            "type": e.get("type"),
        }
        for e in entities
    ]
    norm_entities.sort(key=lambda e: (e.get("type") or "", e.get("text") or ""))

    relationships = ontology.get("relationships", [])
    norm_relationships = []
    for rel in relationships:
        src = id_to_entity.get(rel.get("source_id"), {})
        tgt = id_to_entity.get(rel.get("target_id"), {})
        norm_relationships.append(
            {
                "source_text": src.get("text"),
                "target_text": tgt.get("text"),
                "type": rel.get("type"),
            }
        )
    norm_relationships.sort(
        key=lambda r: (
            r.get("type") or "",
            r.get("source_text") or "",
            r.get("target_text") or "",
        )
    )
    return {
        "entities": norm_entities,
        "relationships": norm_relationships,
    }


def _load_fixture(name):
    path = FIXTURE_DIR / f"golden_{name}.json"
    payload = json.loads(path.read_text())
    return payload


def _run_case(payload):
    generator = OntologyGenerator()
    context = OntologyGenerationContext(
        data_source=f"golden-{payload['name']}",
        data_type="text",
        domain=payload["domain"],
        extraction_strategy=ExtractionStrategy.RULE_BASED,
        config=ExtractionConfig(confidence_threshold=0.0, llm_fallback_threshold=0.0),
    )
    ontology = generator.generate_ontology(payload["text"], context)
    return _normalize(ontology)


def test_golden_contracts():
    payload = _load_fixture("contracts")
    assert _run_case(payload) == payload["normalized"]


def test_golden_hr():
    payload = _load_fixture("hr")
    assert _run_case(payload) == payload["normalized"]


def test_golden_healthcare():
    payload = _load_fixture("healthcare")
    assert _run_case(payload) == payload["normalized"]


def test_golden_technical():
    payload = _load_fixture("technical")
    assert _run_case(payload) == payload["normalized"]
