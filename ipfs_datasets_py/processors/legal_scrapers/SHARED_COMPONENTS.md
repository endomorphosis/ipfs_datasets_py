# Shared Components in Legal Scrapers

This document explains which components in the `legal_scrapers` module are shared between different systems and how to use them properly.

## Overview

The `legal_scrapers` module contains several shared components that are used by multiple subsystems:

1. **Complaint Analysis** - Analyzes legal complaints for risk and categorization
2. **Brave Legal Search** - Natural language search for legal rules and regulations
3. **Legal Scrapers** - Various scrapers for federal, state, and municipal legal data

## Shared Components

### 1. Keyword Registry (`complaint_analysis/keywords.py`)

**Used by:** Complaint Analysis, Brave Legal Search (query_processor.py)

**Purpose:** Manages keywords by category and complaint type for domain categorization.

**Key Functions:**
```python
from ipfs_datasets_py.processors.legal_scrapers.complaint_analysis import (
    get_keywords,
    register_keywords,
    get_type_specific_keywords
)

# Get keywords for a category
keywords = get_keywords('complaint', complaint_type='housing')

# Register new keywords
register_keywords('complaint', ['new', 'keywords'], complaint_type='custom')

# Get only type-specific keywords (no global)
specific = get_type_specific_keywords('complaint', 'housing')
```

**Architecture:**
- Registry-based system
- Supports global keywords (all types) and type-specific keywords
- 14 built-in complaint types (housing, employment, civil_rights, etc.)

### 2. Legal Pattern Extractor (`complaint_analysis/legal_patterns.py`)

**Used by:** Complaint Analysis, Brave Legal Search (query_processor.py)

**Purpose:** Extracts legal provisions, citations, and concepts from text using regex patterns.

**Key Classes:**
```python
from ipfs_datasets_py.processors.legal_scrapers.complaint_analysis import (
    LegalPatternExtractor,
    register_legal_terms,
    get_legal_terms
)

# Extract legal provisions
extractor = LegalPatternExtractor()
provisions = extractor.extract_provisions(text)
citations = extractor.extract_citations(text)
categories = extractor.categorize_complaint_type(text)

# Register custom patterns
register_legal_terms('custom_category', [
    r'\b(pattern1)\b',
    r'\b(pattern2)\b'
])
```

**Features:**
- Regex-based pattern matching
- Legal citation extraction
- Automatic complaint categorization
- Extensible via pattern registration

### 3. Base Classes (`complaint_analysis/base.py`)

**Used by:** Complaint Analysis (internal), Brave Legal Search (indirectly)

**Purpose:** Abstract base classes for extending the system with new functionality.

**Key Classes:**
```python
from ipfs_datasets_py.processors.legal_scrapers.complaint_analysis.base import (
    BaseLegalPatternExtractor,
    BaseKeywordRegistry,
    BaseRiskScorer
)

# Extend for custom implementations
class CustomExtractor(BaseLegalPatternExtractor):
    def extract_provisions(self, text):
        # Custom logic
        pass
```

**Use Cases:**
- Creating custom legal pattern extractors
- Implementing custom keyword registries
- Building custom risk scoring models

### 4. Complaint Types (`complaint_analysis/complaint_types.py`)

**Used by:** Complaint Analysis, Brave Legal Search (query_processor.py - potential)

**Purpose:** Registration functions for 14 built-in complaint types with their keywords and patterns.

**Key Functions:**
```python
from ipfs_datasets_py.processors.legal_scrapers.complaint_analysis import (
    register_housing_complaint,
    register_employment_complaint,
    register_civil_rights_complaint,
    # ... 11 more types
    get_registered_types
)

# Get all registered types
types = get_registered_types()
# Returns: ['housing', 'employment', 'civil_rights', 'consumer', ...]

# Register a specific type
register_consumer_complaint()
```

**Registered Types:**
1. Housing
2. Employment
3. Civil Rights
4. Consumer
5. Healthcare
6. Free Speech
7. Immigration
8. Family Law
9. Criminal Defense
10. Tax Law
11. Intellectual Property
12. Environmental Law
13. Probate
14. DEI (Diversity, Equity, Inclusion)

## Component Dependencies

```
Brave Legal Search
├── Uses: keywords.py (get_keywords)
├── Uses: legal_patterns.py (LegalPatternExtractor)
└── Potential: complaint_types.py (for enhanced categorization)

Complaint Analysis
├── Defines: keywords.py
├── Defines: legal_patterns.py
├── Defines: base.py
├── Defines: complaint_types.py
└── Uses all of the above internally

Legal Scrapers
└── Container for both systems
```

## Best Practices

### 1. Import from the Public API

Always import from the public API, not internal modules:

```python
# ✅ GOOD
from ipfs_datasets_py.processors.legal_scrapers.complaint_analysis import get_keywords

# ❌ BAD
from ipfs_datasets_py.processors.legal_scrapers.complaint_analysis.keywords import get_keywords
```

### 2. Check Availability

The complaint_analysis module may not be available in all environments:

```python
try:
    from ipfs_datasets_py.processors.legal_scrapers.complaint_analysis import get_keywords
    HAVE_COMPLAINT_ANALYSIS = True
except ImportError:
    HAVE_COMPLAINT_ANALYSIS = False
    
if HAVE_COMPLAINT_ANALYSIS:
    keywords = get_keywords('complaint', complaint_type='housing')
```

### 3. Extend, Don't Modify

When adding new functionality, extend existing components rather than modifying them:

```python
# ✅ GOOD: Register new keywords
register_keywords('complaint', ['custom1', 'custom2'], complaint_type='custom')

# ❌ BAD: Modify internal registry directly
# (internal implementation may change)
```

### 4. Use Type-Specific Keywords When Needed

To avoid false positives in categorization, use type-specific keywords:

```python
# Get all keywords (global + type-specific)
all_keywords = get_keywords('complaint', complaint_type='housing')

# Get only type-specific keywords (more precise)
specific_keywords = get_type_specific_keywords('complaint', 'housing')
```

## Integration Examples

### Example 1: Query Categorization

```python
from ipfs_datasets_py.processors.legal_scrapers.complaint_analysis import (
    get_keywords,
    get_registered_types
)

def categorize_query(query: str) -> list:
    """Categorize a query into legal domains."""
    categories = []
    query_lower = query.lower()
    
    # Check all registered types
    for complaint_type in get_registered_types():
        keywords = get_keywords('complaint', complaint_type=complaint_type)
        matches = sum(1 for kw in keywords if kw.lower() in query_lower)
        if matches >= 2:  # Threshold
            categories.append(complaint_type)
    
    return categories
```

### Example 2: Legal Concept Extraction

```python
from ipfs_datasets_py.processors.legal_scrapers.complaint_analysis import (
    LegalPatternExtractor
)

def extract_legal_concepts(text: str) -> dict:
    """Extract legal concepts from text."""
    extractor = LegalPatternExtractor()
    
    return {
        'provisions': extractor.extract_provisions(text),
        'citations': extractor.extract_citations(text),
        'categories': extractor.categorize_complaint_type(text)
    }
```

### Example 3: Custom Legal Pattern

```python
from ipfs_datasets_py.processors.legal_scrapers.complaint_analysis import (
    register_legal_terms,
    LegalPatternExtractor
)

# Register custom patterns
register_legal_terms('crypto_law', [
    r'\b(cryptocurrency|crypto)\b',
    r'\b(blockchain)\b',
    r'\b(smart contract)\b',
    r'\b(defi|decentralized finance)\b',
])

# Use with extractor
extractor = LegalPatternExtractor(categories=['crypto_law'])
provisions = extractor.extract_provisions(crypto_text)
```

## Future Plans

### Short Term
- Document all shared components in README files
- Add explicit comments in code about shared usage
- Create integration tests for shared components

### Medium Term
- Extract shared components to `legal_scrapers/common/` module
- Create unified import paths
- Maintain backward compatibility

### Long Term
- Build unified legal intelligence module
- Create knowledge graph integration
- Multi-modal legal workflow automation

## Contributing

When modifying shared components:

1. **Test both systems** - Run tests for both Complaint Analysis and Brave Legal Search
2. **Maintain backward compatibility** - Don't break existing APIs
3. **Document changes** - Update this guide and relevant READMEs
4. **Add tests** - Include integration tests for shared usage

## Questions?

- Check the component's source code for detailed documentation
- Review existing usage in `query_processor.py` (Brave Legal Search)
- Review existing usage in `analyzer.py` (Complaint Analysis)
- See `COMPLAINT_ANALYSIS_REFACTORING.md` for refactoring plans

---

**Last Updated:** February 2026
**Maintainer:** Legal Scrapers Team
