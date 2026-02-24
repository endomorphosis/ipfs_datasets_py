"""Generate golden fixtures for rule-based ontology extraction tests."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    ExtractionConfig,
    ExtractionStrategy,
)


FIXTURE_DIR = Path(__file__).resolve().parent


def normalize(ontology: dict) -> dict:
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


def build_fixture(name: str, domain: str, text: str) -> dict:
    generator = OntologyGenerator()
    context = OntologyGenerationContext(
        data_source=f"golden-{name}",
        data_type="text",
        domain=domain,
        extraction_strategy=ExtractionStrategy.RULE_BASED,
        config=ExtractionConfig(confidence_threshold=0.0, llm_fallback_threshold=0.0),
    )
    ontology = generator.generate_ontology(text, context)
    return {
        "name": name,
        "domain": domain,
        "text": text,
        "normalized": normalize(ontology),
    }


def main() -> None:
    cases = {
        "contracts": {
            "domain": "legal",
            "text": (
                "The plaintiff agreed to the arbitration clause in Section 12.3. "
                "The defendant accepted the warranty and indemnification terms."
            ),
        },
        "hr": {
            "domain": "general",
            "text": (
                "Employee Alice joined Acme Corp as HR manager. "
                "Benefits include health insurance and PTO."
            ),
        },
        "healthcare": {
            "domain": "medical",
            "text": (
                "The patient reported symptoms of a disorder. "
                "The physician prescribed 5 mg dosage."
            ),
        },
        "technical": {
            "domain": "technical",
            "text": (
                "The API exposes a REST endpoint returning JSON. "
                "Service version v2.3.1 runs in a container."
            ),
        },
    }

    for name, case in cases.items():
        payload = build_fixture(name, case["domain"], case["text"])
        out_path = FIXTURE_DIR / f"golden_{name}.json"
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
