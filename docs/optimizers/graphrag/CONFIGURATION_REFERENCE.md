# ExtractionConfig Complete Reference Guide

**Definitive reference for all ExtractionConfig fields and their behavior.**

**Last Updated:** 2026-02-23  
**Coverage:** All 12 ExtractionConfig fields + detailed examples + performance implications

---

## Quick Setup

```python
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig, OntologyGenerator

# Default (balanced)
config = ExtractionConfig()

# Strict (high precision)
config = ExtractionConfig(
    confidence_threshold=0.85,
    max_entities=500,
    window_size=150
)

# Lenient (high recall)
config = ExtractionConfig(
    confidence_threshold=0.40,
    max_entities=5000,
    window_size=500,
    llm_fallback_threshold=0.50
)

# Medical domain
config = ExtractionConfig(
    domain_vocab={
        "Symptom": ["fever", "cough", "dyspnea"],
        "Medication": ["metformin", "lisinopril"],
        "Test": ["HbA1c", "CBC", "CT"]
    }
)

generator = OntologyGenerator()
result = generator.generate(text, extraction_config=config)
```

---

## Complete Field Reference

### 1. confidence_threshold (float)
**Default:** 0.5  
**Range:** [0.0, 1.0]  
**Type:** Quality threshold

Minimum confidence score required to keep an extracted entity.

**Interpretation:**
```
0.0–0.3  → Very lenient; includes uncertain/weak extractions
0.3–0.5  → Lenient; balanced discovery mode
0.5–0.7  → Balanced; standard production setting
0.7–0.9  → Strict; high-precision, fewer entities
0.9–1.0  → Very strict; only obvious/high-confidence entities
```

**Performance:**
- Lower threshold → More entities extracted, slower processing
- Higher threshold → Fewer entities, faster, more precise

**Common usage:**
```python
# Exploratory: find all possible entities
lenient = ExtractionConfig(confidence_threshold=0.4)

# Production: balanced
balanced = ExtractionConfig(confidence_threshold=0.65)

# Legal/financial: high precision required
strict = ExtractionConfig(confidence_threshold=0.85)
```

**Impact on results:**
| Threshold | Expected Entities | Quality | Use Case |
|-----------|------------------|---------|----------|
| 0.3 | ++++ | Low | Exploration, research |
| 0.5 | +++ | Medium | General purpose |
| 0.7 | ++ | High | Critical data |
| 0.9 | + | Very High | Audits, compliance |

---

### 2. max_entities (int)
**Default:** 0 (unlimited)  
**Range:** [0, ∞)  
**Type:** Output limiter

Maximum number of entities to extract. Prevents runaway extraction on large documents.

**Behavior:**
- `0` → Extract all entities passing `confidence_threshold`
- `100` → Return only top 100 entities by confidence score
- `1000` → Cap at 1000 entities

**When to use:**
- `0` (unlimited) → Small documents, exploratory work
- `100–500` → Medium documents, production systems
- `1000+` → Very large documents, when relationship inference is key

**Performance:**
- Setting a limit slightly improves memory usage on large texts
- More useful for relationship inference (see `max_relationships`)

**Example:**
```python
# Small document: unlimited
config = ExtractionConfig(max_entities=0)

# Large document: cap at 1000
config = ExtractionConfig(max_entities=1000, max_relationships=500)

# Streaming/API use: cap aggressively
config = ExtractionConfig(max_entities=100, max_relationships=50)
```

---

### 3. max_relationships (int)
**Default:** 0 (unlimited)  
**Range:** [0, ∞)  
**Type:** Output limiter

Maximum number of relationships to infer between entities.

**Why limit?**
- Relationship inference is O(n²) with entity count
- Uncapped: 1000 entities → up to 1M relationships (memory expensive)
- Capped: Keeps only top N by confidence score

**Behavior:**
- `0` → Infer all possible relationships
- `100` → Keep top 100 relationships by confidence
- `500` → Cap at 500 relationship pairs

**Common patterns:**
```python
# Exploratory: unlimited
config = ExtractionConfig(max_relationships=0)

# Standard: roughly 1 relationship per 2–3 entities
config = ExtractionConfig(max_entities=500, max_relationships=200)

# Knowledge graph: dense inference
config = ExtractionConfig(max_entities=1000, max_relationships=2000)

# Streaming/API: minimal
config = ExtractionConfig(max_relationships=50)
```

**Relationship count formula (rule of thumb):**
```
Estimated relationships ≈ (num_entities²) / window_size
For 500 entities, window_size=150 → ~1700 potential relationships
```

---

### 4. window_size (int)
**Default:** 5  
**Range:** [1, 1000]  
**Type:** Co-occurrence parameter

Sentence/word distance window for inferring relationships between entities.

**Interpretation:**
- `5` (default) → Entities within 5 words of each other are related
- `50` → Up to 50 words apart (approximately 1–2 sentences)
- `150` → Larger co-occurrence window, catches distant relationships
- `500` → Very large; entire paragraph scope

**Impact:**
```
Smaller window (5–50)
  ✓ Fewer false positive relationships
  ✓ Faster inference
  ✗ Misses valid distant relationships

Larger window (150–500)
  ✓ Catches more distant relationships
  ✓ Better for multi-sentence explanations
  ✗ More false positives, slower
```

**Domain recommendations:**
```python
# Legal documents: long sentence structure, specific language
legal = ExtractionConfig(window_size=250)

# Medical notes: co-location of symptoms and treatments
medical = ExtractionConfig(window_size=150)

# Social media: short references, tight coupling
social = ExtractionConfig(window_size=50)

# General text: balanced
general = ExtractionConfig(window_size=100)

# Strict requirement inference: very local context
strict = ExtractionConfig(window_size=30)
```

---

### 5. min_entity_length (int)
**Default:** 2  
**Range:** [1, ∞)  
**Type:** Filter

Minimum character length for entity text. Shorter entities are discarded.

**Common use:**
```python
# Allow single characters (rare)
config = ExtractionConfig(min_entity_length=1)

# Default: filter single chars
config = ExtractionConfig(min_entity_length=2)  # "a" filtered, "to" kept

# Stricter: minimum 3 chars
config = ExtractionConfig(min_entity_length=3)  # "Dr" filtered

# Very strict: minimum 5 chars
config = ExtractionConfig(min_entity_length=5)  # "John" filtered, "Johnson" kept
```

**Impact:**
- `1` → All entities kept (may include noise)
- `2` → Filter single chars; standard
- `5` → Only substantial entity names/phrases

---

### 6. stopwords (List[str])
**Default:** [] (empty)  
**Type:** Filter

Custom list of terms to exclude from entity text.

**Use case:** Remove common words that pollute entity lists.

**Example:**
```python
# Medical domain: remove common jargon
medical_config = ExtractionConfig(
    domain_vocab={...},
    stopwords=[
        "patient", "hospital", "treatment", "medication", "symptom",
        "physician", "clinical", "case", "report"
    ]
)

# Legal domain
legal_config = ExtractionConfig(
    stopwords=[
        "plaintiff", "defendant", "court", "agreement", "party",
        "section", "article", "hereby", "whereas"
    ]
)

# General: remove noise words
general_config = ExtractionConfig(
    stopwords=["thing", "something", "etc", "and", "or"]
)
```

**Behavior:**
- Case-insensitive matching
- Removes word if it CONTAINS a stopword (substring match)
- Applied after extraction

---

### 7. allowed_entity_types (List[str])
**Default:** [] (allow all types)  
**Type:** Filter

Whitelist of entity types to keep. Non-matching types are discarded.

**Valid entity types:**
```
Person              Individual or named person
Organization        Companies, institutions, groups
Location            Geographic places, regions
Date                Temporal references
Time                Time-of-day references
Duration            Time periods, intervals
Money               Monetary amounts, prices
Concept             Abstract ideas, technical terms
Obligation          Legal duties, requirements (legal domain)
% Additional domain-specific types available
```

**Example:**
```python
# Only people and organizations
business_config = ExtractionConfig(
    allowed_entity_types=["Person", "Organization", "Location"]
)

# Legal domain: focus on key entity types
legal_config = ExtractionConfig(
    allowed_entity_types=[
        "Person", "Organization", "Location", 
        "Date", "Obligation", "Money"
    ]
)

# Financial domain
financial_config = ExtractionConfig(
    allowed_entity_types=["Organization", "Person", "Money", "Date"]
)
```

**Impact:**
- Reduces noise from irrelevant entity types
- Can speed up downstream processing (fewer entities to validate)
- Creates domain-focused ontologies

---

### 8. domain_vocab (Dict[str, List[str]])
**Default:** {} (empty)  
**Type:** Knowledge injection

Domain-specific vocabulary mapping entity types to curated term lists.

**Purpose:**
- Provides "seed knowledge" to boost recognition of domain-specific entities
- Terms in lists are recognized with higher confidence for their type
- Works with both rule-based and LLM-based extraction

**Format:**
```python
{
    "EntityType": ["term1", "term2", "term3"],
    "Another Type": ["concept_a", "concept_b"]
}
```

**Examples:**

```python
# Medical domain
medical_vocab = {
    "Symptom": ["fever", "cough", "fatigue", "dyspnea", "chest pain"],
    "Medication": ["metformin", "lisinopril", "atorvastatin", "aspirin"],
    "Disease": ["diabetes", "hypertension", "asthma", "CHF", "COPD"],
    "MedicalTest": ["HbA1c", "CBC", "CT scan", "MRI", "echocardiogram"],
    "Dosage": ["100mg", "5ml", "once daily", "BID"]
}
config = ExtractionConfig(domain_vocab=medical_vocab)

# Legal domain
legal_vocab = {
    "LegalParty": ["plaintiff", "defendant", "respondent", "claimant"],
    "LegalDuty": ["indemnify", "warranty", "covenant", "obligation"],
    "LegalDocument": ["contract", "agreement", "lease", "deed"],
    "Damages": ["monetary damages", "injunctive relief", "specific performance"]
}
config = ExtractionConfig(domain_vocab=legal_vocab)

# Technical domain
tech_vocab = {
    "Protocol": ["HTTP", "REST", "MQTT", "WebSocket", "gRPC"],
    "Language": ["Python", "JavaScript", "Go", "Rust", "TypeScript"],
    "Framework": ["Django", "FastAPI", "Flask", "Spring Boot"],
    "Database": ["PostgreSQL", "MongoDB", "Redis", "Elasticsearch"]
}
config = ExtractionConfig(domain_vocab=tech_vocab)
```

**Integration:**
- Terms that match `domain_vocab[type]` are recognized as that type with boost
- Exact and substring matching supported
- Case-insensitive

---

### 9. custom_rules (List[tuple])
**Default:** [] (empty)  
**Type:** Pattern injection

Custom regex patterns for domain-specific entities. Format: `[(pattern, type), ...]`

**Use case:** Catch domain-specific patterns not covered by default rules.

**Examples:**

```python
# Financial domain: stock tickers and ticker symbols
config = ExtractionConfig(
    custom_rules=[
        (r"\b[A-Z]{1,5}\b(?=\s+stock)", "StockTicker"),  # "AAPL stock"
        (r"\$[A-Z]{1,5}", "StockSymbol"),  # "$MSFT"
        (r"\$[\d,]+(?:\.\d{2})?", "Currency"),  # "$1,234.56"
    ]
)

# Legal domain: case citations
config = ExtractionConfig(
    custom_rules=[
        (r"\d+\s+F\.(?:Supp\.?|2d)\s+\d+", "CaseCitation"),  # "123 F.2d 456"
        (r"\d+\s+U\.S\.C\.\s+§\s+\d+", "StatuteReference"),  # "18 U.S.C. § 1001"
        (r"\bPlaintiff|Defendant\b", "LegalParty"),
    ]
)

# Medical domain: diagnostic codes
config = ExtractionConfig(
    custom_rules=[
        (r"\bICD-10:\s+[A-Z]\d{2}\.\d+", "DiagnosticCode"),  # "ICD-10: E11.9"
        (r"\bCPT:\s+\d{5}[A-Z]?", "ProcedureCode"),  # "CPT: 99213"
    ]
)
```

**Pattern matching:**
- Applied AFTER standard extraction
- Can augment or override default patterns
- First match wins (order matters)

---

### 10. llm_fallback_threshold (float)
**Default:** 0.0 (disabled)  
**Range:** [0.0, 1.0]  
**Type:** Strategy selector

If rule-based extraction confidence falls below this, attempt LLM-based extraction.

**Behavior:**
- `0.0` (default) → Never use LLM fallback
- `0.3` → Use LLM if rules yield avg confidence < 0.3
- `0.5` → Use LLM if avg confidence < 0.5 (roughly always)
- `1.0` → Always use LLM

**Requirements:**
- Requires `ipfs_accelerate_py` installed
- Requires API key (OpenAI/Claude/local LLM configured)
- Can increase latency and cost

**Use cases:**
```python
# Cost-sensitive: rules only
config = ExtractionConfig(llm_fallback_threshold=0.0)

# Hybrid: rules first, LLM fallback for uncertain cases
config = ExtractionConfig(llm_fallback_threshold=0.6)

# Accuracy-first: always use LLM
config = ExtractionConfig(llm_fallback_threshold=1.0)

# Recovery strategy: rules + LLM if needed
config = ExtractionConfig(
    llm_fallback_threshold=0.50,
    confidence_threshold=0.60
)
```

**Cost-benefit:**
| Threshold | LLM Cost | Quality | Latency |
|-----------|----------|---------|---------|
| 0.0 | None | Medium | Fast |
| 0.5 | Moderate | High | Moderate |
| 1.0 | High | Very High | Slow |

---

### 11. max_confidence (float)
**Default:** 1.0  
**Range:** (0.0, 1.0]  
**Type:** Calibration

Upper bound for entity confidence scores. Scores above this are clamped.

**Use case:** Calibrate confidence scores across domains or models.

**Example:**
```python
# Conservative: cap all confidences at 0.9
# (no entity can score 0.95 or 1.0)
conservative = ExtractionConfig(
    confidence_threshold=0.5,
    max_confidence=0.90
)

# Very conservative: cap at 0.8
pessimistic = ExtractionConfig(max_confidence=0.8)

# Default: no capping
optimistic = ExtractionConfig(max_confidence=1.0)
```

---

### 12. include_properties (bool)
**Default:** True  
**Type:** Feature toggle

Whether to extract and include entity properties/attributes.

**Properties examples:**
- `Person: [age, birthdate, occupation, location]`
- `Organization: [founded_year, headquarters, revenue]`
- `Project: [status, budget, deadline]`

**Impact:**
```python
# Rich extraction: entities + properties
rich = ExtractionConfig(include_properties=True)
result = generator.generate("John Smith, age 45, CEO at Acme Corp")
# → Entity(text="John Smith", type="Person", 
#         properties={"age": "45", "title": "CEO", "employer": "Acme Corp"})

# Minimal extraction: entities only
minimal = ExtractionConfig(include_properties=False)
result = generator.generate("John Smith, age 45, CEO at Acme Corp")
# → Entity(text="John Smith", type="Person", properties={})
```

**Use cases:**
- `True` → Knowledge graphs, semantic search, detailed ontologies
- `False` → Fast extraction, minimal storage, relationship focus

---

## Configuration Recipes

### Pattern 1: Production Balanced
```python
config = ExtractionConfig(
    confidence_threshold=0.65,
    max_entities=1000,
    max_relationships=300,
    window_size=150,
    min_entity_length=2,
    max_confidence=0.95,
    include_properties=True
)
```

### Pattern 2: Legal/Compliance (High Precision)
```python
config = ExtractionConfig(
    confidence_threshold=0.85,
    max_entities=500,
    max_relationships=150,
    window_size=250,
    allowed_entity_types=["Person", "Organization", "Date", "Money", "Obligation"],
    domain_vocab={
        "LegalParty": ["plaintiff", "defendant"],
        "Obligation": ["shall", "must", "required"]
    },
    min_entity_length=3,
    stopwords=["hereby", "whereas", "aforementioned"],
    llm_fallback_threshold=0.7,
    max_confidence=0.9
)
```

### Pattern 3: Medical (Domain-Focused)
```python
config = ExtractionConfig(
    confidence_threshold=0.70,
    max_entities=2000,
    max_relationships=800,
    window_size=200,
    allowed_entity_types=["Person", "Symptom", "Medication", "Disease", "Test"],
    domain_vocab={
        "Symptom": ["fever", "cough", "dyspnea"],
        "Medication": ["metformin", "lisinopril"],
        "Disease": ["diabetes", "hypertension"]
    },
    include_properties=True,
    llm_fallback_threshold=0.6
)
```

### Pattern 4: Exploratory/Research
```python
config = ExtractionConfig(
    confidence_threshold=0.40,
    max_entities=5000,
    max_relationships=2000,
    window_size=500,
    min_entity_length=1,
    llm_fallback_threshold=0.50,
    include_properties=True
)
```

### Pattern 5: Streaming/API (Minimal)
```python
config = ExtractionConfig(
    confidence_threshold=0.75,
    max_entities=100,
    max_relationships=50,
    window_size=100,
    min_entity_length=2,
    include_properties=False,
    llm_fallback_threshold=0.0
)
```

---

## Field Interactions & Side Effects

### Confidence vs. Entity Count
```python
# Trade-off visualization
High threshold (0.9) + unlimited entities → Few very confident entities
Low threshold (0.4) + capped entities (100) → Top 100 least-confident entities
```

### Window_size + max_relationships
```python
# Large window + large relationship cap → Potential performance issue
config = ExtractionConfig(
    window_size=500,
    max_entities=5000,
    max_relationships=0  # Unlimited!
)
# Potential output: thousands of relationships

# Balanced
config = ExtractionConfig(
    window_size=150,
    max_entities=1000,
    max_relationships=500  # Reasonable cap
)
```

### LLM Fallback Latency
```python
#Fast: rules only
config = ExtractionConfig(llm_fallback_threshold=0.0)
# Latency: <100ms per document

# Slow: LLM on uncertain results
config = ExtractionConfig(llm_fallback_threshold=0.6)
# Latency: 300–2000ms per document (depends on model)

# Slowest: always LLM
config = ExtractionConfig(llm_fallback_threshold=1.0)
# Latency: 500–5000ms per document
```

---

## Validation Rules

```python
config = ExtractionConfig(...)
config.validate()  # Raises ValueError if any field violates:

# ✓ confidence_threshold ∈ [0.0, 1.0]
# ✓ max_entities ≥ 0
# ✓ max_relationships ≥ 0
# ✓ window_size ≥ 1
# ✓ min_entity_length ≥ 1
# ✓ max_confidence ∈ (0.0, 1.0]
# ✓ llm_fallback_threshold ∈ [0.0, 1.0]
```

---

## Loading Configuration

### From Python
```python
config = ExtractionConfig(
    confidence_threshold=0.75,
    max_entities=500
)
```

### From Dictionary
```python
config_dict = {
    "confidence_threshold": 0.75,
    "max_entities": 500
}
config = ExtractionConfig.from_dict(config_dict)
```

### From Environment Variables
```bash
export EXTRACTION_CONFIDENCE_THRESHOLD=0.75
export EXTRACTION_MAX_ENTITIES=500
```

```python
config = ExtractionConfig.from_env(prefix="EXTRACTION_")
```

### From YAML
```yaml
# config.yaml
confidence_threshold: 0.75
max_entities: 500
max_relationships: 200
window_size: 150
```

```python
import yaml
with open("config.yaml") as f:
    config_dict = yaml.safe_load(f)
config = ExtractionConfig.from_dict(config_dict)
```

---

## Troubleshooting

| Problem | Likely Cause | Solution |
|---------|--------------|----------|
| Too few entities extracted | `confidence_threshold` too high | Lower to 0.5–0.7 |
| Too many low-quality entities | `confidence_threshold` too low | Raise to 0.7–0.8 |
| Extraction takes too long | High `max_entities` + `window_size` | Reduce both; enable `max_relationships` cap |
| Missing domain-specific terms | No `domain_vocab` or `custom_rules` | Add vocabulary or patterns for your domain |
| Wrong entity types included | `allowed_entity_types` not set | Whitelist only needed types |
| Relationships not inferred | `window_size` too small | Increase to 100–200 |
| Too many false-positive relationships | Large `window_size` + large `max_relationships` | Reduce `window_size` to 50–100 |
| Properties not extracted | `include_properties=False` | Set to `True` |
| LLM fallback not triggering | `llm_fallback_threshold=0.0` | Set to 0.5–0.7 for fallback |
| Extraction inconsistent across runs | Check for non-deterministic components | Use fixed `max_entities` and `max_relationships` |

---

## Best Practices

1. **Start with defaults** — `ExtractionConfig()` is reasonable for most cases
2. **Adjust `confidence_threshold` first** — Controls precision/recall trade-off
3. **Set `max_entities` for production** — Prevents runaway extraction on unknown text sizes
4. **Use `domain_vocab` for domain specificity** — Better than generic extraction
5. **Cap `max_relationships`** — Usually max ≈ 0.5 × max_entities
6. **Test `window_size` empirically** — Domain-dependent (150 is good baseline)
7. **Use `stopwords` sparingly** — Only remove truly noisy terms
8. **Enable LLM fallback cautiously** — Adds latency and cost
9. **Validate before production** — Call `config.validate()` on all configs
10. **Monitor extraction metrics** — Track entities/relationships per document for anomalies

---

## See Also

- [QUICKSTART.md](./QUICKSTART.md) — Get started in 5 minutes
- [EXTRACTION_CONFIG_GUIDE.md](./EXTRACTION_CONFIG_GUIDE.md) — Original guide (legacy)
- [OntologyGenerator API Reference](./API_REFERENCE_GRAPHRAG.md) — Full class documentation
- [README.md](./README.md) — Architecture overview
