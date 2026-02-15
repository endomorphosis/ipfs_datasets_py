# TODO: Format Handlers Refactoring

This document tracks the tasks and issues related to implementing Inversion of Control (IoC) via Dependency Injection for format handlers.

## IMPORTANT: File Preservation Policy

**NEVER DELETE ANY FILES** during this refactoring. According to project guidelines, once a feature has been implemented, it must never be removed, even if it causes test failures. Instead:

- Move obsolete or unessential files to a 'deprecated' folder
- Maintain backward compatibility with existing code
- Adapt tests to match new functionality rather than removing features

## Completed Tasks

### IoC Architecture Implementation
- [x] **Complete IoC refactoring with dependency injection pattern**
  - [x] Implement standardized processor pattern across ALL processors
  - [x] Create centralized factory system in factory.py
  - [x] Establish "types determine processors" principle
  - [x] Fix circular references in constants.py
  - [x] Clean up and simplify make_processor function
  - [x] Implement multi-dependency fallback system

### Processor Architecture
- [x] **Establish two-tier processor system**
  - [x] Ability processors (image_processor, text_processor, video_processor, ocr_processor)
  - [x] MIME-type specific processors (xlsx_processor, pdf_processor, html_processor, etc.)
  - [x] Hierarchical delegation (specific → ability → dependency modules)

### Factory System
- [x] **Standardize ALL processors to follow exact pattern**:
  1. Check `Constants.PROCESSOR_AVAILABLE`
  2. Create `processor_resources` dictionary
  3. Optional resource modifications
  4. Call `make_processor()` with unpacked resources
  5. Store in `processors[processor_name]`

### Dependency Management
- [x] **Create isolated dependency modules**
  - [x] Format: `dependency_modules/_library_processor.py`
  - [x] Contains raw functions using third-party libraries
  - [x] Automatic mocking when dependencies unavailable
  - [x] Multi-dependency fallback (e.g., openpyxl → pandas for XLSX)

### Constants System
- [x] **Centralize all availability checking**
  - [x] Library availability properties (PIL_AVAILABLE, OPENPYXL_AVAILABLE)
  - [x] Processor availability properties (IMAGE_PROCESSOR_AVAILABLE)
  - [x] Format sets (SUPPORTED_XLSX_FORMATS)
  - [x] Use @_classproperty for class-level properties

### Documentation
- [x] **Create comprehensive architecture documentation**
  - [x] Document IoC pattern and dependency injection
  - [x] Explain processor hierarchy and delegation
  - [x] Document factory system and standardized patterns
  - [x] Create ARCHITECTURE.md with complete system overview

## Remaining Tasks

### Handler Refactoring (In Progress)
- [x] **Refactor image_handler.py to follow text_handler.py template**
  - [x] Convert to framework class with IoC pattern
  - [x] Remove hardcoded dependencies and use injection
  - [x] Add factory function following naming convention
- [x] **Refactor audio_handler.py to follow text_handler.py template**
  - [x] Convert to framework class with IoC pattern
  - [x] Remove hardcoded dependencies and use injection
  - [x] Add factory function following naming convention
- [ ] **Refactor video_handler.py to follow text_handler.py template**
  - [ ] Convert to framework class with IoC pattern
  - [ ] Remove hardcoded dependencies and use injection
  - [ ] Add factory function following naming convention
- [ ] **Refactor application_handler.py to follow text_handler.py template**
  - [ ] Convert to framework class with IoC pattern
  - [ ] Remove hardcoded dependencies and use injection
  - [ ] Add factory function following naming convention

### Template Tool Development (Current)
- [x] Created processor template generation tool
  - [x] Built `make_processor_from_template.py` CLI tool
  - [x] Added `dependency_module_template.py.jinja` template
  - [x] Created schema validation system
  - [x] Added code cleanup and formatting functions
- [x] Created DuckDB processor schema
  - [x] JSON schema for database file processing with DuckDB
  - [x] Functions: extract_metadata, extract_text, process_database, get_version
- [ ] **Fix template indentation issues** (PRIORITY)
  - [ ] Resolve "return outside function" syntax errors
  - [ ] Improve function body indentation handling
  - [ ] Test generated processors for syntax validity
- [ ] Complete DuckDB processor implementation
  - [ ] Generate error-free processor file
  - [ ] Test with actual database files
  - [ ] Integrate into processor factory

### System Integration
- [ ] Update main.py and other modules to use the new registry
  - [ ] Replace global format_registry with factory-created instance
  - [ ] Update imports to use new modules

- [ ] Create comprehensive tests for the refactored code
  - [ ] Test the unified handler implementation
  - [ ] Test all handlers with the new pattern
  - [ ] Test the registry with dependency-injected handlers
  - [ ] Test integration with the processing pipeline

- [ ] Update documentation to reflect the new architecture
  - [ ] Document the IoC pattern and dependency injection approach
  - [ ] Update handler documentation to reflect the new pattern
  - [ ] Create diagrams illustrating the new architecture
  - [ ] Document the preservation strategy for obsolete files

- [ ] Move all availability constants from factory.py to constants.py
  - [ ] Consolidate all processor availability checks in one location
  - [ ] Update imports in factory.py to use constants from constants.py
  - [ ] Ensure consistent naming convention for availability flags

## Implementation Notes

1. All handlers should follow the pattern established in `refactored_audio_handler.py`:
   - No inheritance (use composition)
   - Class methods converted to standalone functions
   - Factory function for creation with dependencies
   - Resources passed explicitly, not imported

2. The BaseFormatHandler class in unified_handler.py now:
   - Takes only resources and configs parameters
   - Extracts specific resources in the constructor (fail-fast)
   - Passes file_path and format to processors via options dictionary

3. New code organization:
   - Main handler logic in unified_handler.py
   - Format-specific processors in separate modules
   - Factory functions in factory.py
   - Constants in constants.py

4. Technical requirements:
   - Python 3.10+ for match/case syntax
   - Pydantic for data models
   - Consistent type hints throughout