# Complaint Analysis Module

An extensible framework for analyzing legal complaints across different domains.

## Overview

The `complaint_analysis` module (formerly `hacc_integration`) provides a flexible, registry-based system for analyzing complaints. It's designed to be extended with new complaint types without modifying the core code.

## Key Features

✅ **Extensible Taxonomies** - Register new keyword sets for any complaint type  
✅ **Pluggable Risk Scoring** - Customize risk assessment per domain  
✅ **Registry Pattern** - Add new complaint types programmatically  
✅ **Multiple Complaint Types** - Housing, employment, civil rights, consumer, healthcare, DEI, and more  
✅ **DEI Taxonomy** - Comprehensive Diversity, Equity, and Inclusion complaint analysis (formerly hacc_integration)  
✅ **Backward Compatible** - Works with existing code

## Supported Complaint Types

The module includes built-in support for 14 complaint types:

- **DEI (Diversity, Equity, Inclusion)** - Discrimination, harassment, civil rights violations across domains
- **Housing** - Fair housing, tenant rights, housing discrimination
- **Employment** - Workplace discrimination, wrongful termination, EEOC complaints
- **Civil Rights** - Constitutional rights, police misconduct, voting rights
- **Consumer** - Fraud, deceptive practices, consumer protection
- **Healthcare** - Medical malpractice, HIPAA violations, patient rights
- **Free Speech** - First Amendment, censorship, content moderation
- **Immigration** - Visa issues, deportation, asylum claims
- **Family Law** - Divorce, custody, domestic violence
- **Criminal Defense** - Constitutional violations, due process, wrongful conviction
- **Tax Law** - IRS disputes, tax penalties, collection actions
- **Intellectual Property** - Patent, trademark, copyright infringement
- **Environmental Law** - Pollution, EPA violations, environmental hazards
- **Probate** - Estate disputes, will contests, trust administration, guardianship

## Quick Start

```python
from complaint_analysis import ComplaintAnalyzer

# Analyze a housing complaint
analyzer = ComplaintAnalyzer(complaint_type='housing')
result = analyzer.analyze(complaint_text)

print(f"Risk: {result['risk_level']}")
print(f"Categories: {result['categories']}")
print(f"Legal provisions found: {result['legal_provisions']['provision_count']}")
```

## Extending with New Complaint Types

### Example: Adding Environmental Complaints

```python
from complaint_analysis import register_keywords, register_legal_terms

# Register keywords
register_keywords('complaint', [
    'pollution', 'contamination', 'toxic waste',
    'environmental hazard', 'clean air act',
    'clean water act', 'epa', 'superfund',
], complaint_type='environmental')

# Register legal patterns
register_legal_terms('environmental', [
    r'\b(clean air act)\b',
    r'\b(clean water act)\b',
    r'\b(cercla|superfund)\b',
    r'\b(epa|environmental protection agency)\b',
    r'\b(hazardous waste)\b',
])

# Now use it
from complaint_analysis import ComplaintAnalyzer
analyzer = ComplaintAnalyzer(complaint_type='environmental')
result = analyzer.analyze(text)
```

### Example: Custom Risk Scorer

```python
from complaint_analysis import BaseRiskScorer

class EnvironmentalRiskScorer(BaseRiskScorer):
    """Custom risk scorer for environmental complaints."""
    
    def __init__(self):
        self.risk_levels = ['low', 'medium', 'high', 'critical', 'catastrophic']
    
    def calculate_risk(self, text, legal_provisions=None, **kwargs):
        # Custom logic for environmental risks
        score = 0
        factors = []
        
        if 'superfund site' in text.lower():
            score = 4  # Catastrophic
            factors.append('Superfund site identified')
        elif 'epa violation' in text.lower():
            score = 3  # Critical
            factors.append('EPA violation')
        # ... more logic
        
        return {
            'score': score,
            'level': self.risk_levels[score],
            'factors': factors,
            'recommendations': self._get_recommendations(score)
        }
    
    def get_risk_levels(self):
        return self.risk_levels
    
    def is_actionable(self, text, threshold=0.5):
        result = self.calculate_risk(text)
        normalized = result['score'] / (len(self.risk_levels) - 1)
        return normalized >= threshold
```

## Built-in Complaint Types

The module includes comprehensive taxonomies for 14 different practice areas:

### Housing
Keywords: fair housing, Section 8, landlord, tenant, eviction, reasonable accommodation, etc.

### Employment  
Keywords: Title VII, EEOC, workplace discrimination, wrongful termination, etc.

### Civil Rights
Keywords: police brutality, first amendment, voting rights, equal protection, etc.

### Consumer
Keywords: fraud, deceptive practices, false advertising, FTC, consumer protection, etc.

### Healthcare
Keywords: medical malpractice, HIPAA, patient rights, EMTALA, informed consent, etc.

### Free Speech / Censorship
Keywords: First Amendment, content moderation, censorship, prior restraint, public forum, etc.

### Immigration
Keywords: visa, asylum, deportation, USCIS, ICE, green card, naturalization, etc.

### Family Law
Keywords: divorce, child custody, child support, alimony, domestic violence, adoption, etc.

### Criminal Defense
Keywords: Miranda rights, Fourth Amendment, due process, illegal search, habeas corpus, etc.

### Tax Law
Keywords: IRS, tax audit, tax court, tax penalty, innocent spouse, offer in compromise, etc.

### Intellectual Property
Keywords: patent, trademark, copyright, fair use, DMCA, trade secret, infringement, etc.

### Environmental Law
Keywords: EPA, Clean Air Act, Clean Water Act, CERCLA, pollution, contamination, etc.

### Probate
Keywords: estate, will, probate court, executor, beneficiary, trust, guardianship, intestate succession, etc.

## Architecture

```
complaint_analysis/
├── base.py                    # Abstract base classes
├── legal_patterns.py          # Legal term extraction with registry
├── keywords.py                # Keyword management with registry
├── risk_scoring.py            # Risk assessment
├── indexer.py                 # Hybrid document indexing
├── analyzer.py                # Unified analysis interface
├── complaint_types.py         # Complaint type registration
└── __init__.py                # Public API

Key Classes:
- BaseLegalPatternExtractor    # Extend for custom pattern extraction
- BaseKeywordRegistry          # Extend for custom keyword management  
- BaseRiskScorer               # Extend for custom risk models
- LegalPatternExtractor        # Default implementation
- KeywordRegistry              # Registry-based keyword manager
- ComplaintRiskScorer          # Default risk scorer
- ComplaintAnalyzer            # High-level interface
```

## Registry Pattern

The module uses a registry pattern for extensibility:

```python
# Global registries
LEGAL_TERMS_REGISTRY = {}  # {category: [patterns]}
_global_keyword_registry   # KeywordRegistry instance

# Register items
register_legal_terms('category_name', patterns_list)
register_keywords('category_name', keywords_list, complaint_type='optional')

# Retrieve items
get_legal_terms('category_name')
get_keywords('category_name', complaint_type='optional')
get_type_specific_keywords('category_name', 'complaint_type')  # Type-specific only
```

## API Reference

### Main Classes

**ComplaintAnalyzer(complaint_type=None)**
- High-level interface combining all components
- `analyze(text, metadata=None)` - Complete analysis

**LegalPatternExtractor(categories=None, custom_patterns=None)**
- Extract legal provisions from text
- Alias: `ComplaintLegalPatternExtractor` (backward compatibility)
- `extract_provisions(text)` - Find legal terms
- `extract_citations(text)` - Find legal citations
- `categorize_complaint_type(text)` - Categorize complaint

**KeywordRegistry()**
- Manage keywords by category and type
- `register_keywords(category, keywords, complaint_type=None)`
- `get_keywords(category, complaint_type=None)` - Get all keywords (global + type-specific)
- `get_type_specific_keywords(category, complaint_type)` - Get only type-specific keywords
- `get_complaint_types()` - List registered types

**ComplaintRiskScorer()**
- Calculate risk scores
- Alias: `RiskScorer` (backward compatibility)
- `calculate_risk(text, legal_provisions=None)` - Risk assessment
- `is_actionable(text, threshold=2)` - Check if actionable

### Helper Functions

**register_keywords(category, keywords, complaint_type=None)** - Register keywords in global registry  
**get_keywords(category, complaint_type=None)** - Get keywords (global + type-specific if type specified)  
**get_type_specific_keywords(category, complaint_type)** - Get only type-specific keywords (no global)  
**register_legal_terms(category, patterns)** - Register legal term regex patterns  
**get_legal_terms(category=None)** - Get legal term patterns

### Registration Functions

**register_housing_complaint()** - Register housing keywords/patterns  
**register_employment_complaint()** - Register employment keywords/patterns  
**register_civil_rights_complaint()** - Register civil rights keywords/patterns  
**register_consumer_complaint()** - Register consumer keywords/patterns  
**register_healthcare_complaint()** - Register healthcare keywords/patterns  
**register_free_speech_complaint()** - Register free speech/censorship keywords/patterns  
**register_immigration_complaint()** - Register immigration law keywords/patterns  
**register_family_law_complaint()** - Register family law keywords/patterns  
**register_criminal_defense_complaint()** - Register criminal defense keywords/patterns  
**register_tax_law_complaint()** - Register tax law keywords/patterns  
**register_intellectual_property_complaint()** - Register IP law keywords/patterns  
**register_environmental_law_complaint()** - Register environmental law keywords/patterns  
**register_probate_complaint()** - Register probate law keywords/patterns  
**get_registered_types()** - List all registered complaint types

## Migration from hacc_integration

The module is backward compatible:

```python
# Old way (still works - backward compatibility alias)
from complaint_analysis import ComplaintLegalPatternExtractor
extractor = ComplaintLegalPatternExtractor()

# New way (recommended)
from complaint_analysis import LegalPatternExtractor
extractor = LegalPatternExtractor()

# Old constants (still available)
from complaint_analysis import COMPLAINT_KEYWORDS

# New way (recommended - more flexible)
from complaint_analysis import get_keywords
keywords = get_keywords('complaint', complaint_type='housing')
```

## Advanced Features

### Type-Specific Keywords

To avoid false positives when tagging documents, use `get_type_specific_keywords()` to get only complaint-type-specific keywords (excluding global keywords):

```python
from complaint_analysis import get_keywords, get_type_specific_keywords

# Get all keywords (global + housing-specific)
all_housing = get_keywords('complaint', complaint_type='housing')
# Returns: ['discrimination', 'harassment', ..., 'fair housing', 'Section 8', ...]

# Get only housing-specific keywords (no global)
housing_only = get_type_specific_keywords('complaint', 'housing')
# Returns: ['fair housing', 'Section 8', 'landlord', 'tenant', ...]

# This is useful for applicability tagging to avoid false positives
# e.g., "discrimination" appears in all types, but "fair housing" is specific to housing
```

## Testing

```bash
# Test the module
python3 -c "from complaint_analysis import ComplaintAnalyzer; \
    analyzer = ComplaintAnalyzer('housing'); \
    print('✓ Module works!')"

# Run tests
pytest tests/test_complaint_analysis.py -v
```

## Examples

See `docs/COMPLAINT_ANALYSIS_EXAMPLES.md` for comprehensive examples.

## Version

Current version: 2.0.0 (extensible architecture)
Previous version: 1.0.0 (hacc_integration)

## License

See main repository LICENSE file.
