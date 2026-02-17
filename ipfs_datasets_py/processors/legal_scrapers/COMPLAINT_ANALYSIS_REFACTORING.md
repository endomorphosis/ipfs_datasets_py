# Complaint Analysis Refactoring Plan

## Analysis Summary

After examining the `complaint_analysis` folder, I've identified significant opportunities for code reuse and better integration with the Brave Legal Search system.

### Current Structure

```
complaint_analysis/ (~6,000 lines total)
├── base.py (161 lines) - Abstract base classes
├── keywords.py (368 lines) - Keyword registry system
├── legal_patterns.py (467 lines) - Legal pattern extraction
├── complaint_types.py (909 lines) - Complaint type registration
├── risk_scoring.py (179 lines) - Risk scoring
├── analyzer.py (67 lines) - Main analyzer interface
├── indexer.py (279 lines) - Document indexing
├── seed_generator.py (504 lines) - Complaint seed generation
├── decision_trees.py (929 lines) - Decision tree generation
├── prompt_templates.py (363 lines) - LLM prompt templates
├── response_parsers.py (531 lines) - Parse LLM responses
├── dei_*.py (1,071 lines) - DEI-specific implementations
└── __init__.py (173 lines) - Public API
```

## Identified Reusable Components

### ✅ Already Being Used by Brave Legal Search

1. **Keywords Registry** (`keywords.py`)
   - Used by `query_processor.py` via `get_keywords()`
   - Provides legal domain categorization
   - GOOD: Already integrated

2. **Legal Pattern Extractor** (`legal_patterns.py`)
   - Used by `query_processor.py` for legal concept extraction
   - GOOD: Already integrated

### 🔄 Potential Shared Use

3. **Base Classes** (`base.py`)
   - Abstract interfaces: `BaseLegalPatternExtractor`, `BaseKeywordRegistry`, `BaseRiskScorer`
   - OPPORTUNITY: Could be moved to a shared `legal_scrapers/common/` module

4. **Complaint Types Registry** (`complaint_types.py`)
   - 14 complaint types with keywords and patterns
   - OPPORTUNITY: Could enhance query processor's domain categorization

### 🎯 Complaint-Specific (Keep Separate)

5. **Risk Scoring** (`risk_scoring.py`, `dei_risk_scoring.py`)
   - Specific to complaint analysis workflow
   - NOT NEEDED: for search use case

6. **Analyzer** (`analyzer.py`)
   - Combines components for complaint analysis
   - NOT NEEDED: for search (we have `BraveLegalSearch` instead)

7. **Document Indexing** (`indexer.py`)
   - Hybrid vector + keyword indexing
   - NOT NEEDED: for search (covered by Brave API)

8. **Seed Generator** (`seed_generator.py`)
   - Generates synthetic complaint data
   - NOT NEEDED: for search

9. **Decision Trees** (`decision_trees.py`)
   - Question generation for complaint intake
   - NOT NEEDED: for search

10. **Prompt Templates** (`prompt_templates.py`)
    - LLM prompt engineering
    - MAYBE USEFUL: Could use for query expansion

11. **Response Parsers** (`response_parsers.py`)
    - Parse LLM responses
    - MAYBE USEFUL: Could use for query understanding

## Recommended Refactoring

### Option 1: Extract Shared Components (RECOMMENDED)

Create a new shared module structure:

```
legal_scrapers/
├── common/                          # NEW: Shared components
│   ├── __init__.py
│   ├── base.py                      # MOVED from complaint_analysis
│   ├── keywords.py                  # MOVED from complaint_analysis
│   ├── legal_patterns.py            # MOVED from complaint_analysis
│   └── complaint_types.py           # MOVED from complaint_analysis
│
├── complaint_analysis/              # Remains but imports from common
│   ├── __init__.py                  # Updated imports
│   ├── analyzer.py                  # Imports from ../common
│   ├── risk_scoring.py
│   ├── indexer.py
│   ├── seed_generator.py
│   ├── decision_trees.py
│   ├── prompt_templates.py
│   ├── response_parsers.py
│   └── dei_*.py
│
├── brave_legal_search/              # NEW: Separate module
│   ├── __init__.py
│   ├── knowledge_base_loader.py     # MOVED from legal_scrapers root
│   ├── query_processor.py           # MOVED, imports from ../common
│   ├── search_term_generator.py     # MOVED, imports from ../common
│   ├── brave_legal_search.py        # MOVED
│   └── README.md
│
├── federal_register_scraper.py
├── us_code_scraper.py
└── ...other scrapers
```

**Benefits:**
- ✅ Clear separation of concerns
- ✅ No code duplication
- ✅ Easy to maintain both systems
- ✅ Backward compatible (with updated imports)

### Option 2: Keep Current Structure with Better Imports (MINIMAL)

Keep files where they are, but improve documentation and imports:

```python
# In query_processor.py, make dependencies explicit
from ..complaint_analysis import (
    get_keywords,          # Shared keyword registry
    LegalPatternExtractor, # Shared pattern extractor
)
```

**Benefits:**
- ✅ No file moves
- ✅ Minimal changes
- ✅ Quick to implement

**Drawbacks:**
- ⚠️ Less clear what's shared vs complaint-specific
- ⚠️ Harder for future contributors to understand

### Option 3: Unified Legal Intelligence Module (AMBITIOUS)

Create a comprehensive legal intelligence module:

```
legal_scrapers/
├── legal_intelligence/             # NEW: Unified module
│   ├── __init__.py
│   ├── base/                       # Base classes
│   ├── knowledge/                  # Knowledge base & entities
│   ├── patterns/                   # Legal pattern extraction
│   ├── keywords/                   # Keyword management
│   ├── query/                      # Query processing
│   ├── search/                     # Search integration
│   └── analysis/                   # Complaint analysis
│
└── ...scrapers
```

**Benefits:**
- ✅ Clean architecture
- ✅ Everything organized logically
- ✅ Easier to add new features

**Drawbacks:**
- ⚠️ Major refactoring effort
- ⚠️ Risk of breaking changes
- ⚠️ More testing required

## Immediate Recommendations

### Phase 1: Improve Current Integration (1-2 hours)

1. **Document the shared components** in complaint_analysis README
   ```markdown
   ## Shared Components
   
   These components are also used by Brave Legal Search:
   - `keywords.py` - Keyword registry (get_keywords, register_keywords)
   - `legal_patterns.py` - Legal pattern extraction
   - `base.py` - Abstract interfaces
   ```

2. **Add explicit imports** in query_processor.py with comments
   ```python
   # Shared components from complaint_analysis
   from ..complaint_analysis import (
       get_keywords,          # Domain-specific keywords
       LegalPatternExtractor, # Extract legal terms
   )
   ```

3. **Create a shared components guide** (`SHARED_COMPONENTS.md`)

### Phase 2: Extract Common Module (4-6 hours)

1. Create `legal_scrapers/common/` directory
2. Move shared components:
   - `base.py`
   - `keywords.py`
   - `legal_patterns.py`
   - `complaint_types.py`
3. Update imports in both modules
4. Add deprecation notices in old locations
5. Update all tests

### Phase 3: Enhanced Query Processing (2-3 hours)

Use complaint_types registry to improve query categorization:

```python
# In query_processor.py
from ..common.complaint_types import get_registered_types

def _categorize_legal_domain(self, query: str) -> List[str]:
    """Enhanced categorization using complaint_types registry."""
    # Use all 14 registered complaint types for better categorization
    all_types = get_registered_types()
    # ... enhanced logic
```

## Code Reuse Opportunities

### Immediate (Already Happening)

- ✅ Keyword registry for domain categorization
- ✅ Legal pattern extraction for concept identification

### Short Term (Easy Wins)

1. **Complaint Types for Query Categorization**
   ```python
   # query_processor.py can use all 14 complaint types
   from ..complaint_analysis.complaint_types import get_registered_types
   
   # Get better categorization
   domains = self._match_to_complaint_types(query, get_registered_types())
   ```

2. **Prompt Templates for Query Expansion**
   ```python
   # Could use prompt_templates.py to expand queries
   from ..complaint_analysis.prompt_templates import PromptTemplate
   
   # Generate expanded queries
   expanded = PromptTemplate.expand_legal_query(query)
   ```

3. **Response Parsers for Entity Extraction**
   ```python
   # Could use EntityParser for better entity extraction
   from ..complaint_analysis.response_parsers import EntityParser
   
   # Parse entities from complex queries
   entities = EntityParser.parse(query)
   ```

### Long Term (Future Enhancements)

1. **Unified Search & Analysis Pipeline**
   - Search for relevant docs with BraveLegalSearch
   - Analyze found docs with ComplaintAnalyzer
   - Generate risk reports

2. **Knowledge Graph Integration**
   - Use complaint_analysis patterns to build legal knowledge graph
   - Enhance search with graph traversal

3. **Multi-Modal Legal Intelligence**
   - Combine search, analysis, and decision trees
   - Full legal workflow automation

## Implementation Priority

### High Priority (Do Now)
1. ✅ Document shared components in README
2. ✅ Add explicit import comments
3. ✅ Create SHARED_COMPONENTS.md guide

### Medium Priority (Next Sprint)
1. 🔄 Extract common/ module
2. 🔄 Update imports and tests
3. 🔄 Enhance query categorization with complaint_types

### Low Priority (Future)
1. ⏳ Unified legal intelligence module
2. ⏳ Multi-modal pipeline
3. ⏳ Knowledge graph integration

## Backward Compatibility

All refactoring must maintain backward compatibility:

```python
# Old code still works
from complaint_analysis import get_keywords, LegalPatternExtractor

# New code also works
from legal_scrapers.common import get_keywords, LegalPatternExtractor

# Complaint analysis imports from common but re-exports
from complaint_analysis import get_keywords  # Still works via re-export
```

## Testing Strategy

For each refactoring phase:

1. ✅ Run existing complaint_analysis tests
2. ✅ Run existing brave_legal_search tests  
3. ✅ Add integration tests for shared components
4. ✅ Verify backward compatibility

## Conclusion

**RECOMMENDED APPROACH: Option 1 (Extract Shared Components)**

This provides the best balance of:
- Clear code organization
- Maintainability
- Backward compatibility
- Future extensibility

**IMMEDIATE ACTION: Phase 1 (Document Shared Components)**

This requires minimal effort and immediately improves code clarity.

---

**Next Steps:**
1. Get approval for refactoring approach
2. Implement Phase 1 documentation improvements
3. Schedule Phase 2 for next sprint
4. Plan Phase 3 enhancements
