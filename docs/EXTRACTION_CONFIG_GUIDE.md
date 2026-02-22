# ExtractionConfig Configuration Guide

## Overview

The `ExtractionConfig` dataclass provides typed configuration for entity and relationship extraction in the GraphRAG ontology generation pipeline. It replaces untyped `Dict[str, Any]` configs with a strongly-typed interface that supports serialization, validation, and environment variable initialization.

All fields are optional with sensible defaults; `ExtractionConfig()` is always safe to instantiate.

---

## Field Reference

### `confidence_threshold` (float, default: 0.5)

**Purpose**: Minimum confidence score for entities/relationships to be retained during extraction.

**Type**: Float in range [0.0, 1.0]

**Use Cases**:
- **High threshold (0.7–0.9)**: Strict mode—only high-confidence extractions. Recommended for:
  - Critical domains (legal, financial, medical)
  - When false positives are more costly than false negatives
  - Small, curated datasets
  
- **Medium threshold (0.5–0.6)**: Balanced mode (default). Recommended for:
  - General-purpose text processing
  - Mixed-quality input documents
  - Most production workloads
  
- **Low threshold (0.2–0.4)**: Permissive mode. Recommended for:
  - Exploratory data analysis
  - Noisy/informal text (social media, chat)
  - When recall is more important than precision

**Example**:
```python
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig

# Strict extraction (legal documents)
legal_cfg = ExtractionConfig(confidence_threshold=0.8)

# Balanced extraction (default)
balanced_cfg = ExtractionConfig()  # confidence_threshold=0.5

# Permissive extraction (noisy content)
permissive_cfg = ExtractionConfig(confidence_threshold=0.3)
```

**Relationship to other fields**:
- Must be ≤ `max_confidence` (enforced by `validate()`)
- Works together with `llm_fallback_threshold` to trigger LLM fallback

---

### `max_entities` (int, default: 0)

**Purpose**: Upper bound on the number of extracted entities per run. 0 means unlimited.

**Type**: Non-negative integer

**Use Cases**:
- **0 (unlimited)**: Extract all entities found. Recommended for:
  - Knowledge base construction
  - Complete ontology mapping
  - When memory/storage is not constrained
  
- **10–50**: Few high-quality entities. Recommended for:
  - Mobile or resource-constrained environments
  - Quick summaries of documents
  - Real-time systems requiring low latency
  
- **100–500**: Medium-scale extraction. Recommended for:
  - Typical document processing pipelines
  - Balancing completeness with efficiency
  - Most production systems
  
- **500+**: Large-scale extraction. Use for:
  - Complex domain documents (contracts, scientific papers)
  - When cost of LLM calls is secondary to completeness

**Example**:
```python
# Mobile client: extract top 20 entities only
mobile_cfg = ExtractionConfig(max_entities=20)

# Server: extract all entities (no limit)
server_cfg = ExtractionConfig(max_entities=0)

# Balanced: extract up to 200 entities
balanced_cfg = ExtractionConfig(max_entities=200)
```

**Note**: When limit is reached, extraction stops. Use with `window_size` for multi-document processing.

---

### `max_relationships` (int, default: 0)

**Purpose**: Upper bound on the number of inferred relationships. 0 means unlimited.

**Type**: Non-negative integer

**Use Cases**:
- **0 (unlimited)**: Extract all relationships found. Recommended for:
  - Relationship network analysis
  - Graph-based reasoning systems
  - Knowledge graphs
  
- **5–20**: Sparse relationships. Recommended for:
  - Entity linking only (minimal relationships)
  - Fast processing
  - When relationships are secondary
  
- **20–100**: Moderate relationships. Recommended for:
  - Typical extraction pipelines
  - Balanced entity + relationship processing
  - Most production workloads
  
- **100+**: Dense relationships. Use for:
  - Complex domain documents
  - Deep graph analysis needed
  - When relationship inference cost is acceptable

**Example**:
```python
# Minimal relationships (entity linking focus)
entity_only_cfg = ExtractionConfig(max_relationships=5)

# Balanced extraction
balanced_cfg = ExtractionConfig(max_relationships=50)

# Dense relationship extraction
dense_cfg = ExtractionConfig(max_relationships=200, max_entities=300)
```

**Note**: Relationship inference happens after entity extraction; limits are applied independently.

---

### `window_size` (int, default: 5)

**Purpose**: Context window size for co-occurrence-based relationship inference.

**Type**: Positive integer (must be ≥ 1)

**Use Cases**:
- **Small (2–3 tokens)**: Tight contextual coupling. Use for:
  - Direct syntactic relationships (e.g., "A owns B")
  - Avoiding spurious co-occurrence links
  - High-precision relationship inference
  
- **Medium (5–10 tokens)**: Balanced context. Recommended for:
  - General relationship inference (default: 5)
  - Capturing nearby semantic relationships
  - Most extraction tasks
  
- **Large (15–25 tokens)**: Broad context windows. Use for:
  - Capturing thematic relationships across sentences
  - Noisy text with scattered entities
  - When recall > precision for relationships

**Example**:
```python
# Tight relationship inference (direct links only)
tight_cfg = ExtractionConfig(window_size=2)

# Default balanced window
balanced_cfg = ExtractionConfig(window_size=5)

# Broad contextual inference
broad_cfg = ExtractionConfig(window_size=20)
```

**How it works**: Two entities are considered related if they co-occur within `window_size` tokens of each other. Larger windows capture more distant relationships but may introduce false positives.

---

### `include_properties` (bool, default: True)

**Purpose**: Whether to include entity property/attribute predicates in the ontology.

**Type**: Boolean

**Use Cases**:
- **True (enabled)**: Extract properties. Use for:
  - Rich entity descriptions
  - Attribute-based filtering and analysis
  - Complete ontology representation
  - Knowledge graph systems requiring properties
  
- **False (disabled)**: Skip properties. Use for:
  - Minimizing extraction overhead
  - Simple entity + relationship models
  - When properties are not needed
  - Fast/lightweight extraction

**Example**:
```python
# With properties (rich ontology)
rich_cfg = ExtractionConfig(include_properties=True)

# Without properties (lightweight)
lightweight_cfg = ExtractionConfig(include_properties=False)
```

**Note**: When disabled, entities are extracted but their descriptive properties are omitted.

---

### `min_entity_length` (int, default: 2)

**Purpose**: Minimum character length for entity text. Shorter entities are filtered out.

**Type**: Positive integer (must be ≥ 1)

**Use Cases**:
- **1–2 characters**: Allow single letters and short abbreviations.
  - Risk: High false positive rate (e.g., "I", "a", "or" recognized as entities)
  - Use when processing chemical formulas, acronyms, or symbolic notations
  
- **3–5 characters**: Filter short noise while keeping abbreviations.
  - Recommended for general text processing
  - Filters common single-character entities but keeps reasonable names
  - Default of 2 is slightly permissive
  
- **6+ characters**: Only substantial entity names.
  - Very restrictive; may miss legitimate short names
  - Use when text is noisy or entity names are known to be longer
  - Good for formal documents (contracts, regulations)

**Example**:
```python
# Allow single characters (code/formula text)
formula_cfg = ExtractionConfig(min_entity_length=1)

# Filter very short entities (balanced, default)
balanced_cfg = ExtractionConfig(min_entity_length=2)

# Only substantial names
formal_cfg = ExtractionConfig(min_entity_length=6)
```

**Interaction with `max_entity_length`**: There is a general maximum (implicit in validation), but `min_entity_length` is the explicitly configurable lower bound.

---

### `llm_fallback_threshold` (float, default: 0.0)

**Purpose**: Confidence threshold below which rule-based extraction triggers LLM fallback (if LLM backend is configured).

**Type**: Float in range [0.0, 1.0]

**Use Cases**:
- **0.0 (disabled, default)**: Rule-based extraction only. Use for:
  - Cost-sensitive deployments
  - Deterministic, reproducible extraction
  - Fast extraction (no LLM latency)
  - When rule-based patterns are sufficient
  
- **0.5–0.7**: Moderate fallback. Use for:
  - Hybrid extraction (rule-based + LLM backup)
  - When rule-based coverage is ~70% but fallback improves recall
  - General production use with per-request LLM budget
  
- **0.9+**: Aggressive fallback. Use for:
  - Small, high-importance documents
  - When LLM quality is critical
  - Unlimited LLM budget
  - When rule-based extraction is unreliable

**Example**:
```python
# Rule-based only (no LLM fallback)
rule_only_cfg = ExtractionConfig(llm_fallback_threshold=0.0)

# Hybrid: LLM fallback when confidence < 0.6
hybrid_cfg = ExtractionConfig(llm_fallback_threshold=0.6)

# Aggressive: LLM for almost everything (high cost)
aggressive_cfg = ExtractionConfig(llm_fallback_threshold=0.95)
```

**Prerequisites**:
- `OntologyGenerator` must be initialized with an `llm_backend` (e.g., OpenAI)
- Fallback is attempted only if LLM backend is available
- If LLM is unavailable, rule-based extraction is returned regardless of threshold

---

### `stopwords` (List[str], default: empty list)

**Purpose**: List of entity texts that should be filtered out (case-insensitive).

**Type**: List of strings

**Use Cases**:
- **Common words**: Filter grammatical artifacts.
  ```python
  stopwords=["the", "and", "or", "is", "a", "an"]
  ```
  
- **Domain-specific noise**: Filter frequent non-entities.
  ```python
  stopwords=["said", "said the", "according to"]  # for news text
  ```
  
- **Pronouns and articles**: Remove when they're not meaningful.
  ```python
  stopwords=["he", "she", "it", "they", "we", "this", "that"]
  ```

**Example**:
```python
# News article processing
news_cfg = ExtractionConfig(
    stopwords=["said", "told", "according to", "the", "and", "or"]
)

# Technical documentation
tech_cfg = ExtractionConfig(
    stopwords=["the", "a", "an", "is", "was", "etc"]
)

# No stopwords (keep everything)
no_stopwords_cfg = ExtractionConfig(stopwords=[])
```

**Note**: Matching is case-insensitive; "The" matches stopword "the".

---

### `allowed_entity_types` (List[str], default: empty list)

**Purpose**: Whitelist of entity types; empty list allows all types.

**Type**: List of strings (entity type names)

**Use Cases**:
- **Empty (default)**: No filtering; all entity types allowed.
  
- **Legal domain**:
  ```python
  allowed_entity_types=["Person", "Organization", "Contract", "Date", "Amount"]
  ```
  
- **Medical domain**:
  ```python
  allowed_entity_types=["Disease", "Medication", "Symptom", "Dosage"]
  ```
  
- **Financial domain**:
  ```python
  allowed_entity_types=["Company", "Security", "Price", "Portfolio"]
  ```

**Example**:
```python
# Only persons and organizations
narrow_cfg = ExtractionConfig(
    allowed_entity_types=["Person", "Organization"]
)

# All legal document types
legal_cfg = ExtractionConfig(
    allowed_entity_types=["Person", "Organization", "Contract", "Law", "Amount", "Date"]
)

# No type filtering
open_cfg = ExtractionConfig(allowed_entity_types=[])
```

**Note**: If a non-empty list is provided, only entities matching one of those types are kept.

---

### `max_confidence` (float, default: 1.0)

**Purpose**: Upper bound on entity confidence scores. Scores are clamped to [0.0, max_confidence].

**Type**: Float in range (0.0, 1.0]

**Use Cases**:
- **1.0 (default)**: No clamping; keep original confidence values.
  
- **0.95**: Prevent over-confident scores. Use for:
  - Avoiding artificially high confidence from rule-based patterns
  - Encouraging skepticism in downstream systems
  - When confidence calibration is important
  
- **0.75–0.85**: Moderate clamping. Use for:
  - Reducing false sense of certainty
  - Encouraging ensemble or multi-method validation
  - Conservative confidence assessment

**Example**:
```python
# No clamping (default)
unclamped_cfg = ExtractionConfig(max_confidence=1.0)

# Moderate clamping (cap at 0.8)
clamped_cfg = ExtractionConfig(max_confidence=0.8)

# Conservative (cap at 0.7)
conservative_cfg = ExtractionConfig(max_confidence=0.7)
```

**Relationship to `confidence_threshold`**: 
- `confidence_threshold` filters out low-confidence entities
- `max_confidence` caps high-confidence scores
- Example: `confidence_threshold=0.5, max_confidence=0.8` keeps entities in range [0.5, 0.8]

---

### `domain_vocab` (Dict[str, List[str]], default: empty dict)

**Purpose**: Domain-specific vocabulary for entity typing. Maps entity type names to lists of representative terms.

**Type**: Dictionary with string keys (entity types) and list-of-string values (example terms)

**Use Cases**:
- **Legal domain**:
  ```python
  domain_vocab={
      "Contract": ["agreement", "contract", "deed", "terms"],
      "Party": ["plaintiff", "defendant", "buyer", "seller"],
      "Obligation": ["shall pay", "must deliver", "agrees to"]
  }
  ```
  
- **Medical domain**:
  ```python
  domain_vocab={
      "Disease": ["diabetes", "flu", "hypertension", "cancer"],
      "Medication": ["aspirin", "insulin", "ibuprofen"],
      "Symptom": ["fever", "cough", "nausea", "bleeding"]
  }
  ```
  
- **Financial domain**:
  ```python
  domain_vocab={
      "Stock": ["AAPL", "MSFT", "Tesla", "Apple Inc."],
      "Metric": ["earnings", "revenue", "EBITDA", "P/E ratio"]
  }
  ```

**Example**:
```python
legal_cfg = ExtractionConfig(
    domain_vocab={
        "Person": ["plaintiff", "defendant", "judge", "witness"],
        "Organization": ["court", "firm", "corporation"],
        "Document": ["contract", "agreement", "deed"]
    }
)
```

**How it's used**: Vocabulary terms are used as hints for entity type classification during extraction. This improves type assignment accuracy in specialized domains.

---

### `custom_rules` (List[tuple], default: empty list)

**Purpose**: Pluggable rule sets for pattern-based entity extraction. List of (regex_pattern, entity_type) tuples.

**Type**: List of tuples: `(str_regex_pattern, str_entity_type)`

**Use Cases**:
- **Email addresses**:
  ```python
  custom_rules=[
      (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', 'Email')
  ]
  ```
  
- **Phone numbers**:
  ```python
  custom_rules=[
      (r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', 'PhoneNumber'),
      (r'\+\d{1,3}\s?\d{1,14}\b', 'PhoneNumber')
  ]
  ```
  
- **URLs**:
  ```python
  custom_rules=[
      (r'https?://\S+', 'URL')
  ]
  ```
  
- **Currency amounts**:
  ```python
  custom_rules=[
      (r'\$\d+(?:,\d{3})*(?:\.\d{2})?', 'Amount'),
      (r'£\d+(?:,\d{3})*(?:\.\d{2})?', 'Amount')
  ]
  ```
  
- **Legal citation format**:
  ```python
  custom_rules=[
      (r'\d+\s[A-Z][.a-z.]+\s\d+', 'LegalCitation'),  # "123 U.S.C. 456"
  ]
  ```

**Example**:
```python
finance_cfg = ExtractionConfig(
    custom_rules=[
        (r'\$\d+(?:,\d{3})*(?:\.\d{2})?', 'Amount'),
        (r'\b[A-Z]{1,5}\b', 'Ticker'),
        (r'\b\d{4}-\d{2}-\d{2}\b', 'Date')
    ]
)
```

**Warning**: Regex patterns are applied in order; first match wins. More specific patterns should come first.

---

## Complete Configuration Examples

### Example 1: Legal Document Processing

```python
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    ExtractionConfig, OntologyGenerator, OntologyGenerationContext
)

legal_config = ExtractionConfig(
    # High confidence threshold for legal accuracy
    confidence_threshold=0.75,
    max_entities=200,
    max_relationships=150,
    
    # Fine-grained relationship detection
    window_size=8,
    
    # Include rich entity descriptions
    include_properties=True,
    
    # Minimum reasonable entity name length
    min_entity_length=3,
    
    # Hybrid mode: LLM fallback for edge cases
    llm_fallback_threshold=0.65,
    
    # Filter common stop words
    stopwords=["the", "and", "or", "is", "a", "an", "by", "of"],
    
    # Only extract legal entity types
    allowed_entity_types=[
        "Person", "Organization", "Document", 
        "Law", "Court", "Amount", "Date"
    ],
    
    # Domain vocabulary for legal terms
    domain_vocab={
        "Document": ["contract", "agreement", "deed", "will", "tort"],
        "Party": ["plaintiff", "defendant", "claimant", "respondent"],
        "Obligation": ["obligation", "duty", "right", "liability"]
    },
    
    # Custom rules for legal citations
    custom_rules=[
        (r'\d+\s[U.S.C|F.Supp|Fed|Cal]\D*\s\d+', 'LegalCitation'),
        (r'\$\d+(?:,\d{3})*(?:\.\d{2})?', 'Amount')
    ],
    
    # Conservative confidence calibration
    max_confidence=0.95
)

# Use in pipeline
generator = OntologyGenerator()
context = OntologyGenerationContext(
    domain="legal",
    data_source="contract",
    data_type="text",
    config=legal_config
)
result = generator.extract_entities("Your legal text here...", context)
```

### Example 2: Social Media / Noisy Text

```python
social_config = ExtractionConfig(
    # Lower threshold for noisy user-generated content
    confidence_threshold=0.35,
    max_entities=50,
    max_relationships=30,
    
    # Shorter window (tight relationships only)
    window_size=3,
    
    # Skip properties for speed
    include_properties=False,
    
    # Allow very short names (usernames, hashtags)
    min_entity_length=1,
    
    # Disable LLM fallback (cost/speed)
    llm_fallback_threshold=0.0,
    
    # Heavy stopwords list for noisy text
    stopwords=[
        "the", "a", "an", "is", "are", "was", "were",
        "i", "me", "my", "you", "your", "he", "she", "it",
        "lol", "omg", "hey", "yeah", "like", "so", "just"
    ],
    
    # No type filtering (broad extraction)
    allowed_entity_types=[],
    
    # Simple extraction (no custom rules)
    custom_rules=[],
    
    # More trust in confidence scores
    max_confidence=1.0
)
```

### Example 3: Real-Time / Resource-Constrained

```python
realtime_config = ExtractionConfig(
    # Reasonable confidence threshold
    confidence_threshold=0.5,
    max_entities=20,        # Keep small for latency
    max_relationships=10,
    
    window_size=5,
    include_properties=False,  # Skip for speed
    min_entity_length=2,
    llm_fallback_threshold=0.0,  # No LLM (too slow)
    
    # Minimal stopwords
    stopwords=["the", "and", "or"],
    
    # Liberal type acceptance
    allowed_entity_types=[],
    
    # No custom rules (too expensive to evaluate)
    custom_rules=[],
    
    max_confidence=1.0
)
```

### Example 4: Medical/Scientific Text

```python
medical_config = ExtractionConfig(
    confidence_threshold=0.6,
    max_entities=150,
    max_relationships=120,
    
    window_size=10,  # Longer for thematic relationships
    include_properties=True,   # Include medication properties, dosages
    min_entity_length=2,
    
    llm_fallback_threshold=0.7,  # Fallback for ambiguous terms
    
    stopwords=["the", "and", "or", "in", "of", "to", "for"],
    
    allowed_entity_types=[
        "Disease", "Symptom", "Medication", "Treatment",
        "Dosage", "TimeFrame", "BodyPart", "TestResult"
    ],
    
    domain_vocab={
        "Disease": ["diabetes", "hypertension", "asthma", "COPD"],
        "Medication": ["aspirin", "lisinopril", "metformin"],
        "Symptom": ["fever", "chest pain", "shortness of breath"]
    },
    
    custom_rules=[
        (r'\d+\s?(mg|g|ml|units?)\b', 'Dosage'),
        (r'\d{1,2}-\d{1,2}\s?(?:year|month|week)s?\s?old', 'Age')
    ],
    
    max_confidence=0.95  # Conservative for medical accuracy
)
```

---

## Validation & Error Handling

All ExtractionConfig instances validate their state when `validate()` is called:

```python
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig

cfg = ExtractionConfig(confidence_threshold=1.5)  # Invalid!

try:
    cfg.validate()
except ValueError as e:
    print(f"Validation error: {e}")
    # Output: "Validation error: confidence_threshold must be in [0, 1]; got 1.5"
```

**Automatic validation** is performed during extraction pipeline execution. Callers can also validate explicitly before use.

---

## Serialization & Environment Variables

### Loading from Dictionary (Legacy)

```python
config_dict = {
    "confidence_threshold": 0.8,
    "max_entities": 100,
    "max_relationships": 50
}

cfg = ExtractionConfig.from_dict(config_dict)
```

### Loading from Environment Variables

```python
import os

# Set environment variables
os.environ["EXTRACTION_CONFIDENCE_THRESHOLD"] = "0.8"
os.environ["EXTRACTION_MAX_ENTITIES"] = "100"
os.environ["EXTRACTION_MAX_RELATIONSHIPS"] = "50"

# Load from environment
cfg = ExtractionConfig.from_env(prefix="EXTRACTION_")
```

### Serializing to Dictionary

```python
cfg = ExtractionConfig(confidence_threshold=0.8)
dict_repr = cfg.to_dict()
print(dict_repr)
# Output: {'confidence_threshold': 0.8, 'max_entities': 0, ...}
```

---

## Best Practices

1. **Start with defaults**: `ExtractionConfig()` is a safe, reasonable starting point.

2. **Validate early**: Call `cfg.validate()` during initialization, not in production.

3. **Domain-specific tuning**: Use `domain_vocab`, `custom_rules`, and `allowed_entity_types` to tailor extraction to your domain.

4. **Confidence calibration**: Adjust `confidence_threshold` and `max_confidence` based on downstream use cases.

5. **Document your choices**: Comment why you chose specific thresholds or limits for your domain.

6. **Test incrementally**: Change one parameter at a time and measure impact (precision/recall/latency).

```python
# Example: Incremental tuning
configs_to_test = [
    ExtractionConfig(confidence_threshold=0.5),
    ExtractionConfig(confidence_threshold=0.6),
    ExtractionConfig(confidence_threshold=0.7),
    ExtractionConfig(confidence_threshold=0.8),
]

for cfg in configs_to_test:
    results = evaluate(cfg, test_corpus)
    print(f"Threshold {cfg.confidence_threshold}: "
          f"Precision={results.precision:.2f}, "
          f"Recall={results.recall:.2f}")
```

---

## See Also

- [OntologyGenerator](./ONTOLOGY_GENERATOR.md) — Main extraction class
- [ExtractionConfig validation tests](../tests/unit/optimizers/graphrag/test_extraction_config_validation.py)
- [Example end-to-end pipeline](./EXAMPLES.md)
