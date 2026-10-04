# Core Module Changelog

All notable changes to the core processing module will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.1.0] - 2025-05-27 - Core IoC Architecture Implementation

### Added
- **Complete core/factory.py implementation** following IoC pattern
  - Factory functions for all core components (detector, validator, extractor, normalizer, formatter)
  - Centralized component creation with dependency injection
  - Global processing_pipeline instance creation
  - Follows exact 5-step pattern from format_handlers/factory.py
- **Enhanced core/__init__.py** with simplified exports
  - Now only exports processing_pipeline from factory
  - Removed all direct imports and broken global instances
  - Updated implementation status to reflect IoC completion

### Changed
- **Refactored ContentExtractor** to follow IoC pattern
  - Added resources and configs parameters to constructor
  - Moved registry dependency to resources dictionary
  - Implemented fail-fast dependency checking
- **Refactored OutputFormatter** to follow IoC pattern
  - Added resources and configs parameters to constructor
  - Moved NormalizedContent dependency to resources dictionary
  - Added configurable default format from configs
- **Refactored TextNormalizer** to follow IoC pattern
  - Added resources and configs parameters to constructor
  - Maintained existing normalizer functionality with IoC structure
- **Completed FileFormatDetector** implementation
  - Fixed incomplete _init_format_extensions method
  - Now properly initializes format extensions from constants

### Technical Details
- All core components now follow exact IoC pattern from CLAUDE.md
- Factory functions use proper dependency injection with resources dictionary
- Fail-fast approach implemented for missing dependencies
- Circular dependencies resolved by removing direct imports
- Only processing_pipeline exported from core module

### Updated
- **Enhanced FileValidator** IoC implementation (2025-05-27)
  - Removed direct file_format_detector import for complete dependency injection
  - Added file_format_detector as injected resource dependency
  - Updated all format detection method calls to use injected dependency
  - Enhanced factory.py to properly create and inject file_format_detector
  - Removed obsolete make_validator() function

### Status
- ✅ **IoC ARCHITECTURE COMPLETE** for all core components
- ✅ **FULL DEPENDENCY INJECTION** implemented across all core components
- ⚠️ **processing_pipeline.py IoC updates deferred** per instruction
- ⚠️ **REQUIRES TESTING** before integration with main application

## [3.0.0-dev] - 2025-05-27 - Current State

### Current Implementation
- **ProcessingPipeline**: Orchestrates file conversion with sequential processing stages
- **FileFormatDetector**: Detects file formats using MIME types and extensions
- **ContentExtractor**: Extracts content using format handlers from registry
- **TextNormalizer**: Normalizes text with configurable normalizers
- **OutputFormatter**: Formats content in txt, json, and markdown formats
- **ProcessingResult**: Tracks processing results as dataclass
- **ValidationResult**: Pydantic model for validation results
- **FileValidator**: Validates files for processing with configurable rules

### Issues Identified
- **Inconsistent IoC pattern** - some components follow IoC, others don't
- **Direct instantiation** in several components breaks dependency injection
- **Circular imports** between core and other modules
- **Missing factory.py** - no centralized component creation
- **Broken __init__.py** - references undefined variables and creates broken global instances

### Technical Debt
- file_format_detector.py has incomplete _init_format_extensions method
- processing_pipeline.py had typo in to_dict() method (fixed)
- content_extractor.py uses direct registry instantiation
- output_formatter.py and text_normalizer.py don't follow IoC pattern