# GraphRAG Ontology Generator — Quick Start (5 minutes)

**New to GraphRAG? Start here.** This guide shows you how to generate your first knowledge graph ontology in under 5 minutes.

## Install & Setup

```bash
cd ipfs_datasets_py/
pip install -e .
```

## Example 1: Generate an Ontology from Text (Simplest)

```python
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator, OntologyGenerationContext, ExtractionStrategy

# Define what you want to extract
context = OntologyGenerationContext(
    data_source="medical_records",
    data_type="clinical_text",
    extraction_strategy=ExtractionStrategy.RULE_BASED,  # Start simple
)

# Create the generator
gen = OntologyGenerator(context)

# Extract ontology from your text
text = """
John Smith, a 45-year-old male patient, was diagnosed with Type 2 Diabetes in 2015.
He is currently on Metformin 500mg twice daily. His recent HbA1c reading was 6.8%.
The patient works as a software engineer in San Francisco.
"""

result = gen.generate(text)

# What you get
print(f"✅ Found {len(result.entities)} entities")
print(f"✅ Found {len(result.relationships)} relationships")
print(f"✅ Confidence: {result.metrics.get('avg_confidence', 'N/A')}")

# Inspect the ontology
for entity in result.entities[:3]:
    print(f"  - {entity['name']} ({entity['type']})")
```

**What just happened:**
- Generator extracted **entities** (people, places, concepts) from text
- Generator inferred **relationships** between entities (who works for whom, takes what medication)
- Generator assigned **confidence scores** to each extraction

---

## Example 2: Evaluate & Refine (Get Better Results)

```python
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic

# Evaluate quality
critic = OntologyCritic(backend="openai")  # or "claude", "llama"
score = critic.evaluate(result)

print(f"Completeness: {score.completeness:.2f}/100")
print(f"Consistency:  {score.consistency:.2f}/100")
print(f"Clarity:      {score.clarity:.2f}/100")
print(f"Overall:      {score.overall:.2f}/100")

# Get recommendations
if score.recommendations:
    print("\n📝 Recommendations:")
    for rec in score.recommendations[:3]:
        print(f"  - {rec}")
```

**What just happened:**
- Critic evaluated the ontology across 5 dimensions
- Critic provided actionable improvement recommendations
- You now know where to focus refinement

---

## Example 3: Full Optimization Loop (Best Results)

```python
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_session import OntologySession

# Create a session that does: generate → evaluate → refine → validate
session = OntologySession(
    data_source="medical_records",
    data_type="clinical_text",
    max_iterations=3,  # 3 refinement cycles
    confidence_threshold=0.7,  # Keep only high-confidence extractions
)

# Run the full pipeline
refined_ontology = session.run(text)

# What you get
print(f"✅ Final ontology: {len(refined_ontology.entities)} entities, {len(refined_ontology.relationships)} relationships")
print(f"✅ Iterations: {session.total_iterations}")
print(f"✅ Final score: {session.final_score:.2f}/100")

# Inspect improvements
if session.improvement_score:
    print(f"✅ Quality improved by {session.improvement_score:.1f}%")
```

**Why use OntologySession?**
- Automatically refines poor extractions
- Validates consistency (no circular definitions, no orphaned entities)
- Iterates until quality plateaus or max rounds reached
- Returns a production-ready ontology

---

## Example 4: Domain-Specific Extraction (Legal, Medical, Scientific)

```python
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig

# Define domain-specific rules
config = ExtractionConfig(
    domain="legal",  # or "medical", "scientific", "general"
    confidence_threshold=0.65,
    max_entities=100,
    extraction_context="complaint_analysis",  # e.g., "contract_review", "patent_search"
)

context = OntologyGenerationContext(
    data_source="legal_documents",
    data_type="complaint_text",
    extraction_config=config,
)

gen = OntologyGenerator(context)

legal_text = """
The plaintiff alleges that the defendant breached the services agreement dated January 2020.
Specifically, the defendant failed to deliver key deliverables by the agreed deadline,
resulting in damages estimated at $50,000.
"""

result = gen.generate(legal_text)

print(f"Legal entities extracted: {[e['name'] for e in result.entities]}")
print(f"Key relations: {[(r['source'], r['type'], r['target']) for r in result.relationships]}")
```

**Domain strategies:**
- **legal:** Contracts, parties, dates, obligations, damages
- **medical:** Patients, conditions, treatments, dates, measurements
- **scientific:** Entities (proteins, compounds), relationships (interacts_with, regulates)
- **general:** People, organizations, locations, all relationship types

---

## Example 5: Batch Processing (Multiple Documents)

```python
from ipfs_datasets_py.optimizers.graphrag.ontology_harness import OntologyPipelineHarness

texts = [
    "John has diabetes diagnosed in 2015...",
    "Jane has hypertension treated with lisinopril...",
    "Bob works at Acme Corp in NYC...",
]

harness = OntologyPipelineHarness(
    data_source="medical_records",
    batch_size=3,
    num_workers=4,  # Parallel processing
)

results = harness.run_and_report(texts)

print(f"✅ Processed {len(results)} documents")
for doc_result in results:
    print(f"  - {len(doc_result.entities)} entities, {len(doc_result.relationships)} relationships")
```

**Performance tip:** Use `num_workers=4` (default) for CPU-bound extraction on modern hardware.

---

## Common Patterns

### Extract only high-confidence results
```python
config = ExtractionConfig(confidence_threshold=0.8)
result = gen.generate(text, config=config)
# Only extractions with confidence ≥ 0.8 included
```

### Get relationship types explained
```python
for rel in result.relationships:
    print(f"{rel['source']} --[{rel['type']}]--> {rel['target']} (confidence: {rel['confidence']:.2f})")
```

### Validate extracted entities before using
```python
valid_entities = [e for e in result.entities if e['confidence'] > 0.7 and len(e['name']) > 2]
```

### Export to JSON for downstream tools
```python
import json
with open("ontology.json", "w") as f:
    json.dump(result.to_dict(), f, indent=2)
```

---

## Next Steps

- **Advanced:** See [EXTRACTION_CONFIG_GUIDE.md](./docs/EXTRACTION_CONFIG_GUIDE.md) for full configuration options
- **Architecture:** See [README.md](./README.md) for component overview
- **Validation:** See [logic_validator.py](./logic_validator.py) for consistency checking
- **Optimization:** See [ontology_optimizer.py](./ontology_optimizer.py) for SGD-based refinement cycles

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ImportError: No module named 'ipfs_accelerate_py'` | Install with `pip install ipfs-accelerate-py` or use RULE_BASED strategy (no LLM required) |
| Too many low-confidence extractions | Increase `confidence_threshold` in `ExtractionConfig` |
| Missing relationships | Use `ExtractionStrategy.HYBRID` or `LLM_BASED` instead of `RULE_BASED` |
| OOM on large texts | Use `extract_with_context_windows()` with sliding windows |
| Slow batch processing | Increase `num_workers` in `OntologyPipelineHarness` (>4 if CPU count > 4) |

---

**Questions?** Check [COMMON_PITFALLS.md](../COMMON_PITFALLS.md) for known issues and solutions.  
**Ready to contribute?** See [TODO.md](../TODO.md) for open improvements.
