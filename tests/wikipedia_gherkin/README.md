# Wikipedia Gherkin Feature Files

This directory contains Gherkin feature files for all Wikipedia-related callables in the IPFS Datasets Python project.

## Overview

Each Gherkin file explicitly mentions the callable it describes and uses concrete scenarios with minimal adverbs and adjectives, following best practices for behavior-driven development (BDD).

## Files

### Classes from `ipfs_datasets_py.wikipedia_rag_optimizer`

1. **WikipediaRelationshipWeightCalculator.feature** - Tests for relationship weight calculation and prioritization
2. **WikipediaCategoryHierarchyManager.feature** - Tests for category hierarchy management and depth calculation
3. **WikipediaEntityImportanceCalculator.feature** - Tests for entity importance scoring and ranking
4. **WikipediaQueryExpander.feature** - Tests for query expansion with topics and categories
5. **WikipediaPathOptimizer.feature** - Tests for graph traversal path optimization
6. **WikipediaRAGQueryOptimizer.feature** - Tests for Wikipedia-specific RAG query optimization
7. **WikipediaGraphRAGQueryRewriter.feature** - Tests for query rewriting with pattern detection
8. **WikipediaGraphRAGBudgetManager.feature** - Tests for resource budget allocation
9. **UnifiedWikipediaGraphRAGQueryOptimizer.feature** - Tests for unified optimization pipeline

### Classes from `ipfs_datasets_py.wikipedia_x.index`

10. **WikipediaProcessor.feature** - Tests for Wikipedia dataset processing
11. **WikipediaConfig.feature** - Tests for Wikipedia configuration dataclass
12. **test_ipfs_datasets_py.feature** - Tests for legacy compatibility class

### Utility Functions from `ipfs_datasets_py.wikipedia_rag_optimizer`

13. **detect_graph_type.feature** - Tests for graph type detection
14. **create_appropriate_optimizer.feature** - Tests for optimizer factory function
15. **optimize_wikipedia_query.feature** - Tests for main query optimization entry point

## Usage

These Gherkin files can be used with:
- **behave** - Python BDD framework
- **pytest-bdd** - pytest plugin for BDD
- Manual test implementation based on scenarios

## Scenario Style

All scenarios follow these principles:
- Concrete and specific test cases
- Minimal use of adverbs and adjectives
- Clear Given-When-Then structure
- Explicit callable identification in feature description

## Example

```gherkin
Feature: WikipediaRelationshipWeightCalculator
  This feature file describes the WikipediaRelationshipWeightCalculator callable
  from ipfs_datasets_py.wikipedia_rag_optimizer module.

  Scenario: Get weight for known relationship type
    When get_relationship_weight is called with subclass_of
    Then the returned weight is 1.5
```
