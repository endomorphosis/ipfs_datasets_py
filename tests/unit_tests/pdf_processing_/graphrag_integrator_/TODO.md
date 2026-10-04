# GraphRAG Integrator Unit Tests - TODO

## CRITICAL ISSUES - IMMEDIATE ATTENTION REQUIRED

### _extract_entities_from_text Implementation Problems (URGENT)
**Status**: Currently failing - regex patterns fundamentally flawed

#### Core Issues Identified:
- [ ] **MAJOR**: Person regex pattern over-matches organization names
  - Pattern: `r'\b(?:Dr\.|Mr\.|Ms\.|Mrs\.)?\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b'`
  - Problem: Matches "Apple Inc.", "Microsoft Corporation" as persons
  - Impact: Causes test failures in organization entity extraction

- [ ] **MAJOR**: Negative lookahead pattern fails for organization exclusion  
  - Pattern: `(?!\s+(?:Inc\.|Corp\.|LLC|University))`
  - Problem: Doesn't account for periods after suffixes, word boundaries
  - Impact: Cannot properly exclude organizations from person matches

- [ ] **MAJOR**: Pattern processing order conflicts
  - Problem: Person patterns processed before organization patterns
  - Impact: Organizations get captured as persons, overlap removal prevents re-classification
  - Solution: Need to reorder patterns or improve conflict resolution

- [ ] **MEDIUM**: Organization patterns too restrictive
  - Current: Only matches specific suffixes (Inc., Corp., LLC, University)
  - Missing: Plain organization names like "Apple", "Google", "Harvard"
  - Impact: Many valid organizations not detected

- [ ] **MEDIUM**: Missing input validation
  - Problem: No type checking for text/chunk_id parameters
  - Expected: Tests expect TypeError for None inputs
  - Impact: Test failures for edge cases

- [ ] **MINOR**: Property name inconsistency
  - Expected: `extraction_method: 'regex_pattern_matching'`
  - Actual: Different property names in implementation
  - Impact: Test assertion failures

#### Recommended Solutions:
1. **Immediate**: Implement proper input validation with type checking
2. **High Priority**: Redesign person regex to exclude organizations reliably
3. **High Priority**: Reorder pattern processing (organizations first)
4. **Medium Priority**: Expand organization pattern vocabulary
5. **Long Term**: Consider replacing regex with proper NER library (spaCy, NLTK)

#### Root Cause Analysis:
The fundamental issue is attempting Named Entity Recognition (NER) with simple regex patterns. NER is inherently complex and requires:
- Extensive dictionaries and gazeteers
- Contextual analysis
- Machine learning models
- Sophisticated rule engines

Basic regex patterns are insufficient for reliable entity extraction in real-world text.

## Implementation Tasks

### High Priority - Core Test Implementation
- [ ] Implement TestGraphRAGIntegratorInitialization with mock IPLDStorage
- [ ] Implement TestGraphRAGIntegratorIntegrateDocument with complex workflow mocking
- [ ] Implement TestGraphRAGIntegratorQueryGraph with entity matching and filtering logic
- [ ] Implement TestGraphRAGIntegratorGetEntityNeighborhood with NetworkX graph traversal
- [ ] Set up proper mock fixtures for LLMDocument, Entity, Relationship, and KnowledgeGraph classes

### Medium Priority - Entity and Relationship Extraction
- [ ] Implement TestGraphRAGIntegratorExtractEntitiesFromChunks with entity consolidation logic
- [ ] Implement TestGraphRAGIntegratorExtractEntitiesFromText with regex pattern testing
- [ ] Implement TestGraphRAGIntegratorExtractRelationships with relationship coordination
- [ ] Implement TestGraphRAGIntegratorExtractChunkRelationships with co-occurrence testing
- [ ] Implement TestGraphRAGIntegratorExtractCrossChunkRelationships with narrative sequence logic

### Medium Priority - Graph Processing
- [ ] Implement TestGraphRAGIntegratorCreateNetworkXGraph with NetworkX DiGraph testing
- [ ] Implement TestGraphRAGIntegratorMergeIntoGlobalGraph with graph composition
- [ ] Implement TestGraphRAGIntegratorDiscoverCrossDocumentRelationships with entity linking
- [ ] Implement TestGraphRAGIntegratorFindSimilarEntities with similarity matching
- [ ] Implement TestGraphRAGIntegratorCalculateTextSimilarity with Jaccard coefficient

### Low Priority - Utilities and Storage
- [ ] Implement TestGraphRAGIntegratorInferRelationshipType with keyword matching
- [ ] Implement TestGraphRAGIntegratorFindChunkSequences with page grouping logic
- [ ] Implement TestGraphRAGIntegratorStoreKnowledgeGraphIpld with IPLD storage mocking

### Testing Infrastructure
- [ ] Create comprehensive mock factories for all data classes
- [ ] Set up test data generators for realistic entity and relationship scenarios
- [ ] Implement test utilities for NetworkX graph validation
- [ ] Create fixtures for complex knowledge graph structures
- [ ] Set up async test harness for all async methods

### Test Data and Fixtures
- [ ] Create sample LLMDocument instances with realistic content
- [ ] Generate test entities with various types (person, organization, location, etc.)
- [ ] Create test relationships with different types and confidence scores
- [ ] Build sample chunk sequences for cross-chunk relationship testing
- [ ] Prepare test cases for edge conditions (empty inputs, malformed data)

### Validation and Quality
- [ ] Add property-based testing for similarity calculations
- [ ] Implement performance benchmarks for large graph operations
- [ ] Add integration tests with real IPLD storage
- [ ] Create end-to-end tests with complete document processing pipeline
- [ ] Set up test coverage reporting and quality gates

### Documentation
- [ ] Document test patterns and conventions used
- [ ] Create testing guide for contributors
- [ ] Add examples of how to extend tests for new features
- [ ] Document mock usage patterns and best practices
