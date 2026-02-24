# Domain-Aware Configuration Factory

## Overview

The `ExtractionConfig.for_domain()` classmethod creates optimized extraction configurations tailored to specific document domains. Instead of manually tuning parameters like `sentence_window`, users can simply specify their domain and get automatically-optimized settings backed by benchmarking data.

## Motivation

GraphRAG entity extraction performance varies significantly across different document types:

- **Legal documents**: Dense with defined obligations, parties, and specific terms
- **Technical documentation**: Sparse with specialized terminology and multi-paragraph procedures
- **Financial reports**: Structured with numerical relationships and corporate hierarchy

A universal `sentence_window` setting (which limits co-occurrence inference to entities within N sentences) doesn't optimize well for all domains. The domain-aware factory addresses this with domain-specific recommendations derived from [SENTENCE_WINDOW_BENCHMARK_REPORT.md](../docs/SENTENCE_WINDOW_BENCHMARK_REPORT.md).

## Supported Domains

| Domain | `sentence_window` | Expected Improvement | Document Characteristics |
|--------|---|---|---|
| `legal` | 2 | 7-35% | Contracts, clauses, legal argumentation; entities often co-occur near (1-2 sentences) |
| `technical` | 2 | 34% | Documentation, code comments, API specs; technical relationships are local |
| `financial`<br/>`finance` | 2 | 25% | Annual reports, earnings calls; financial metrics and relationships cluster tightly |
| Unknown / default | 0 | — | No distance limiting; all co-occurring entities considered |

## Usage

### Basic: Get domain-optimized config

```python
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig

# Create a legal-domain optimized config
legal_cfg = ExtractionConfig.for_domain("legal")
print(legal_cfg.sentence_window)  # Output: 2

# Create a technical-domain optimized config
tech_cfg = ExtractionConfig.for_domain("technical")
print(tech_cfg.sentence_window)  # Output: 2

# Unknown domain falls back to defaults (sentence_window=0)
generic_cfg = ExtractionConfig.for_domain("unknown")
print(generic_cfg.sentence_window)  # Output: 0
```

### Advanced: Override specific fields

Domain configs use standard defaults for other fields. To customize, use `dataclasses.replace()`:

```python
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
import dataclasses as dc

# Start with domain defaults
cfg = ExtractionConfig.for_domain("legal")

# Override specific field(s)
strict_cfg = dc.replace(cfg, confidence_threshold=0.8)
print(strict_cfg.sentence_window)  # Still 2 (from domain)
print(strict_cfg.confidence_threshold)  # Now 0.8 (overridden)
```

### Use case: Batch processing multiple domains

```python
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator, OntologyGenerationContext, DataType, ExtractionConfig
)

documents = {
    "legal": "A party shall indemnify...",
    "technical": "To enable DEBUG mode...",
    "financial": "Revenue increased by 15%..."
}

for domain, text in documents.items():
    cfg = ExtractionConfig.for_domain(domain)
    context = OntologyGenerationContext(
        data_source=f"{domain}.txt",
        data_type=DataType.TEXT,
        domain=domain,
        config=cfg
    )
    generator = OntologyGenerator(context)
    result = generator.generate_ontology(text)
    print(f"{domain}: {len(result['entities'])} entities extracted")
```

## Configuration Details

### All domain configs inherit these defaults:

```python
ExtractionConfig(
    confidence_threshold=0.5,      # Standard threshold
    max_entities=0,                # Unlimited (0 = no limit)
    max_relationships=0,           # Unlimited
    window_size=5,                 # Co-occurrence window (char count)
    include_properties=True,       # Include property relationships
    llm_fallback_threshold=0.0,    # No LLM fallback
    min_entity_length=2,           # Filter single-char entities
    max_confidence=1.0,            # Max confidence ceiling
    enable_parallel_inference=False,  # Parallelization disabled by default
    max_workers=4,                 # But can be enabled with up to 4 workers
)
```

Only `sentence_window` varies by domain. All other fields use standard defaults.

## Performance Impact

Based on [SENTENCE_WINDOW_BENCHMARK_REPORT.md](../docs/SENTENCE_WINDOW_BENCHMARK_REPORT.md):

**Small documents (100-200 entities)**:
- Legal domain (window=2): **-35% latency** vs. unwindowed
- Technical domain (window=2): **-31% latency**

**Medium documents (300-500 entities)**:
- Financial domain (window=2): **-25% latency**
- Technical domain (window=2): **-34% latency**

**Large documents (1000+ entities)**:
- Window=2 typically saves **7-34%** depending on domain

### Why window_size defaults to 0 for unknown domains

Without domain-specific knowledge, co-occurrence inference within all sentence distances is safer (higher recall). The `sentence_window=2` default is only applied to domains where benchmarking confirms the benefit exceeds recall risk.

## Thread Safety & Serialization

Domain configs are fully serializable and thread-safe:

```python
cfg = ExtractionConfig.for_domain("legal")

# Serialize to dict / JSON / YAML
cfg_dict = cfg.to_dict()
cfg_json = cfg.to_json()

# Roundtrip and compare
cfg_restored = ExtractionConfig.from_json(cfg_json)
assert cfg_restored == cfg  # True
assert cfg_restored.sentence_window == 2  # Domain setting preserved

# Use with parallel inference (ThreadPoolExecutor-safe)
parallel_cfg = dc.replace(cfg, enable_parallel_inference=True, max_workers=4)
```

## Integration with Other Features

### Type prefiltering (P1)

Domain configs work seamlessly with type prefiltering:

```python
cfg = ExtractionConfig.for_domain("legal")
# Type impossible pairs (Date-Date, Location-Location) still filtered
# + Sentence-window limiting also applied
# = ~40-50% combined improvement
```

### Parallel inference (P3)

Domain configs can enable parallelization:

```python
cfg = ExtractionConfig.for_domain("technical")
cfg_parallel = dc.replace(cfg, enable_parallel_inference=True, max_workers=8)
# sentence_window=2 (from domain) + parallel processing (from override)
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "How do I know if my domain is supported?" | Check the [Supported Domains](#supported-domains) table above or use `ExtractionConfig.for_domain()` with your domain name—unknown domains safely fall back to defaults. |
| "I want more aggressive window limiting than window=2" | Override: `dc.replace(ExtractionConfig.for_domain("legal"), sentence_window=1)` |
| "My domain is close to legal but not exactly 'legal'" | Use the closest match or experiment with manual window tuning on a small sample. |
| "Performance didn't improve as expected" | Verify `sentence_window` is set correctly via `config.sentence_window`. Benchmark with your actual documents; improvement varies by corpus structure. |
| "I need different configs for sub-domains (US law vs EU law)" | Use base domain ("legal") then override specific thresholds. Future version may add sub-domain support. |

## Related Documentation

- [SENTENCE_WINDOW_BENCHMARK_REPORT.md](../docs/SENTENCE_WINDOW_BENCHMARK_REPORT.md): Detailed benchmark methodology and results (14 measurements across 3 domains)
- [CONFIGURATION_REFERENCE.md](../docs/CONFIGURATION_REFERENCE.md): Complete field-by-field ExtractionConfig guide
- [OPTIMIZERS_QUICK_START.md](../docs/OPTIMIZERS_QUICK_START.md): Quick-start examples with P1/P2/P3 optimizations

## API Reference

### `ExtractionConfig.for_domain(domain: str) -> ExtractionConfig`

**Parameters:**
- `domain` (str, case-insensitive): Domain name. Supported: "legal", "technical", "financial"/"finance", "general"/"default". Unknown domains use defaults.

**Returns:**
- `ExtractionConfig` instance with domain-optimized `sentence_window` and standard defaults for all other fields.

**Example:**
```python
cfg = ExtractionConfig.for_domain("legal")
```

## Test Coverage

31 comprehensive tests in `tests/unit_tests/optimizers/graphrag/test_domain_aware_config.py`:
- Domain-specific sentence_window values (legal, technical, financial)
- Case-insensitive and whitespace-tolerant domain names
- Fallback behavior for unknown domains
- Field preservation (defaults unchanged except sentence_window)
- Serialization roundtrips (dict, JSON)
- Integration with merge(), copy(), diff() methods
- Edge cases (empty string, numeric, unicode, very long domain names)
- Performance documentation validation

All 31 tests pass.

---

**Last updated:** 2026-02-23  
**Created:** 2026-02-23  
**Author:** GraphRAG Optimization Task Group
