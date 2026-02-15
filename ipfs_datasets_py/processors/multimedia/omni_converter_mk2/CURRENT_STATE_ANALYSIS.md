# Current State Analysis - Omni Converter mk2

## Architecture Intent
Each module exports a single factory function that constructs one object. Dependencies flow upward through factory injection.

## Module Status

### ✅ Working Modules (Singletons)
- [ ] configs - Exports pydantic model
- [ ] logger - Exports logger instance  
- [ ] dependencies - Exports dependency container
- [ ] external_programs - Exports program registry
- [ ] types - Exports type definitions
- [ ] supported_formats - Exports format registry

### 🔄 In Transition (Core)
- [ ] core - Should export pipeline factory
- [ ] text_normalizer - Status unknown
- [ ] output_formatter - Status unknown
- [ ] file_validator - Status unknown
- [ ] content_extractor - Most complex, has 4 processor types

### ❌ Broken/Unknown
- [ ] processors (by_ability, by_mime_type, dependency_modules, fallbacks)
- [ ] handlers - Mixed with old inheritance patterns
- [ ] utils - Status unknown
- [ ] monitors - Status unknown
- [ ] batch_processor - Status unknown
- [ ] interfaces - Partially working

## Anti-Patterns Found
1. Inheritance-based design mixed with composition
2. Tests that pass when they shouldn't
3. Dead code that looks active
4. Multiple architectural patterns coexisting

## Next Steps
1. Pick ONE vertical slice to fix first
2. Write proper red-green-refactor tests
3. Delete dead code ruthlessly
4. Standardize on factory pattern
