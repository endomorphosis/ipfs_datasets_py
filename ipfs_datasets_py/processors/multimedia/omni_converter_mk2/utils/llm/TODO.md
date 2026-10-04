# LLM Module Refactoring TODO

## Overview
The current LLM module appears to be transplanted from another project focused on American Law database integration. It needs significant refactoring to work with the Omni Converter project, following the established Inversion of Control (IoC) pattern.

## High Priority Tasks

- [ ] Remove American Law database references
  - [ ] Strip out all database-specific code (DuckDB, SQLite, etc.)
  - [ ] Remove citation and legal document-specific functionality
  - [ ] Clean up unused dependencies related to law database

- [ ] Create a unified LLM interface for Omni Converter
  - [ ] Define clear resource requirements and interfaces
  - [ ] Implement composition-based design (no inheritance)
  - [ ] Support for direct text generation without RAG components
  - [ ] Implement factory function for dependency injection

- [ ] Refactor AsyncOpenAIClient 
  - [ ] Convert to use dependency injection pattern
  - [ ] Follow resources/configs pattern from other handlers
  - [ ] Remove hardcoded values and dependencies
  - [ ] Implement fail-fast approach for required resources

## Medium Priority Tasks

- [ ] Create dedicated processor modules
  - [ ] Move OpenAI client to utils/dependency_modules/
  - [ ] Create model for tiktoken tokenizer
  - [ ] Separate embedding functionality from OpenAI integration

- [ ] Update embeddings functionality
  - [ ] Convert to general-purpose document embedding
  - [ ] Remove law-specific database operations
  - [ ] Simplify embedding search to work with in-memory data
  - [ ] Make embedding dimensionality configurable

- [ ] Fix prompt loading 
  - [ ] Update to work with project's directory structure
  - [ ] Ensure compatibility with configs system
  - [ ] Support multiple prompt formats and templates

- [ ] Add integration points
  - [ ] Connect with format handlers
  - [ ] Integrate with processing pipeline
  - [ ] Add support for content extraction and summarization

- [ ] Clean up dependencies and imports
  - [ ] Match project standards for import organization
  - [ ] Remove unnecessary dependencies
  - [ ] Properly categorize standard library vs. third-party imports

- [ ] Standardize error handling
  - [ ] Implement consistent error handling patterns
  - [ ] Use project-wide logger
  - [ ] Add appropriate error types and messages

## Low Priority Tasks

- [ ] Create comprehensive tests
  - [ ] Unit tests for LLM functionality
  - [ ] Integration tests with format handlers
  - [ ] Mock tests for API calls

- [ ] Update documentation
  - [ ] Add module documentation
  - [ ] Document configuration options
  - [ ] Create usage examples
  - [ ] Update architecture diagrams

## Implementation Notes

1. Follow the established IoC pattern:
   - Take only resources and configs parameters
   - Extract specific resources in constructor (fail-fast)
   - Use composition instead of inheritance
   - Standalone functions instead of class methods where appropriate

2. Maintain backward compatibility:
   - Preserve the existing interface where possible
   - Move obsolete code to 'deprecated' folder
   - Document changes for users

3. Technical requirements:
   - Python 3.10+ for match/case syntax
   - Pydantic for data models
   - Consistent type hints throughout
   - Follow project's style guide for docstrings