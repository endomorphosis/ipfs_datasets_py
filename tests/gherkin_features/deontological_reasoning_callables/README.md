# Deontological Reasoning Callables Gherkin Test Specifications

This directory contains Gherkin feature files for each callable method in the deontological reasoning classes from `ipfs_datasets_py/deontological_reasoning.py`.

## Purpose

These Gherkin files provide behavioral specifications for deontological reasoning functionality used in legal and ethical analysis. Each file explicitly tests a single callable method and uses concrete scenarios with minimal adverbs and adjectives.

## Files

| File | Callable | Description |
|------|----------|-------------|
| `deontic_extractor_init.feature` | `DeonticExtractor.__init__()` | Initialize deontic statement extractor |
| `extract_statements.feature` | `DeonticExtractor.extract_statements()` | Extract deontic statements from text |
| `detect_conflicts.feature` | `ConflictDetector.detect_conflicts()` | Detect conflicts between deontic statements |
| `deontological_reasoning_engine_init.feature` | `DeontologicalReasoningEngine.__init__()` | Initialize deontological reasoning engine |
| `analyze_corpus_for_deontic_conflicts.feature` | `DeontologicalReasoningEngine.analyze_corpus_for_deontic_conflicts()` | Analyze document corpus for deontic conflicts |
| `query_deontic_statements.feature` | `DeontologicalReasoningEngine.query_deontic_statements()` | Query extracted deontic statements by criteria |
| `query_conflicts.feature` | `DeontologicalReasoningEngine.query_conflicts()` | Query detected conflicts by criteria |

## Deontological Reasoning Overview

Deontological reasoning implements deontic logic frameworks to detect conflicts between what entities can/cannot, should/should not, must/must not do or be. The system provides:

- **Deontic Modalities**: Obligations, permissions, prohibitions, conditionals, exceptions
- **Statement Extraction**: Pattern-based extraction from unstructured text
- **Conflict Detection**: Identifies contradictions between deontic statements
- **Entity Analysis**: Per-entity conflict reports and recommendations
- **Query System**: Flexible querying of statements and conflicts

## Deontic Modalities

- **OBLIGATION**: Mandatory requirements (must, shall, required to)
- **PERMISSION**: Allowed actions (may, can, allowed to)
- **PROHIBITION**: Forbidden actions (must not, cannot, forbidden to)
- **CONDITIONAL**: Context-dependent obligations (if/then statements)
- **EXCEPTION**: Rules with exceptions (unless, except when)

## Conflict Types

- **DIRECT_CONTRADICTION**: X must do A, X must not do A
- **PERMISSION_PROHIBITION**: X can do A, X cannot do A
- **OBLIGATION_PROHIBITION**: X must do A, X must not do A
- **CONDITIONAL_CONFLICT**: If P then X must A, If P then X must not A
- **JURISDICTIONAL**: Conflicts between different legal jurisdictions
- **TEMPORAL**: Conflicts arising from rules changing over time
- **HIERARCHICAL**: Conflicts between different levels of authority

## Test Coverage

Each callable has multiple scenarios covering:
- Initialization and setup
- Successful operations with typical inputs
- Edge cases (empty inputs, missing data)
- Multiple modality types and conflict types
- Query filtering and criteria matching
- Error conditions and validation

## Usage

These Gherkin files serve as:
1. **Specification**: Precise behavioral requirements for each callable
2. **Test templates**: Basis for implementing actual test code
3. **Documentation**: Human-readable descriptions of functionality

To implement tests from these specifications:
1. Use a Gherkin test framework (e.g., pytest-bdd, behave)
2. Create step definitions matching the Given/When/Then steps
3. Implement fixtures for Background setup
4. Run tests to verify deontological reasoning implementation

## Notes

- Each feature file explicitly mentions the callable it tests in the title
- Scenarios use concrete values (e.g., "citizens must pay taxes") rather than abstract descriptions
- Steps avoid unnecessary adverbs and adjectives
- Error scenarios test Exception and ValueError conditions
- Async methods are tested with appropriate async/await patterns
