# Changelog

All notable changes to the Omni-Converter project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.2.0-dev] - 2025-05-28 - Handler Refactoring to IoC Framework Classes (IN PROGRESS)

### Added
- **Handler refactoring to IoC framework classes** following text_handler.py template
  - All handlers being converted from create_handler() pattern to proper IoC classes
  - Standardized constructor: `__init__(self, resources: dict[str, Callable], configs: Configs)`
  - Fail-fast dependency extraction in constructors with explicit KeyError on missing resources
  - Factory functions following `create_[type]_handler()` naming convention
- **Format extension constants consolidation** in extractors/constants.py
  - Moved all hardcoded format_extensions from handlers to centralized constants
  - Added *_HANDLER_FORMAT_EXTENSIONS for each handler type
  - Centralized processing configuration constants (replaced magic numbers)

### Changed
- **Refactored image_handler.py to IoC framework class** ✅ COMPLETED
  - Converted from create_handler() pattern to ImageHandler class
  - Added proper dependency injection with fail-fast behavior
  - Delegates to image_processor, svg_processor, ocr_processor via injected resources
  - Removed all hardcoded format extensions and direct imports
- **Refactored audio_handler.py to IoC framework class** ✅ COMPLETED  
  - Converted from create_handler() pattern to AudioHandler class
  - Added proper dependency injection with fail-fast behavior
  - Delegates to audio_processor and transcription_processor
  - Support for conditional transcription via options
- **text_handler.py established as canonical template**
  - Framework class with orchestration logic only
  - No library-specific code in handler classes
  - All processing delegated to injected processors via `processor(file_path, options)`

### Completed
- [x] **Refactored video_handler.py to IoC framework class** ✅ COMPLETED
  - Converted from make_handler() pattern to VideoHandler class
  - Updated factory function to create_video_handler() naming convention
  - Added proper dependency injection with fail-fast behavior
  - Delegates to video_processor and transcription_processor
- [x] **Refactored application_handler.py to IoC framework class** ✅ COMPLETED
  - Converted from create_handler() pattern to ApplicationHandler class
  - Added proper dependency injection with fail-fast behavior
  - Delegates to pdf_processor, json_processor, docx_processor, xlsx_processor, zip_processor
  - Removed all hardcoded dependencies and fallback logic

### Status  
- ✅ **COMPLETED**: ALL handlers refactored to IoC framework classes
  - ✅ text_handler.py (template)
  - ✅ image_handler.py 
  - ✅ audio_handler.py
  - ✅ video_handler.py
  - ✅ application_handler.py
- ⚠️ **TESTING REQUIRED**: New framework classes need comprehensive testing
- ⚠️ Integration with main application pending

## [3.1.0-dev] - 2025-05-27 - Complete IoC Architecture Implementation (PROCESSOR LEVEL)

### Added
- **Complete core module IoC architecture** with standardized dependency injection
  - Implemented core/factory.py with factory functions for all core components
  - Created centralized processing_pipeline factory with dependency injection
  - Added fail-fast approach for missing core dependencies
  - Followed exact IoC pattern from CLAUDE.md specification
- **Complete format handlers processor architecture** with standardized dependency injection
  - Implemented "types determine processors" principle across ALL processors
  - Created two-tier processor hierarchy: ability processors + MIME-type specific
  - Built centralized factory system with consistent processor creation pattern
  - Added multi-dependency fallback system (e.g., openpyxl → pandas for XLSX)
  - Implemented automatic processor mocking for missing dependencies
- **Comprehensive architecture documentation** (`format_handlers/ARCHITECTURE.md`)
  - System overview with processor hierarchy and delegation patterns
  - Dependency injection examples and extension points
  - Complete architectural patterns and benefits documentation
- **Enhanced constants system** 
  - Fixed circular reference issues with @_classproperty
  - Centralized all availability checking and format definitions
  - Added processor-specific format sets and availability properties

### Changed
- **Refactored ALL core components** to follow IoC pattern
  - ContentExtractor: Added resources/configs parameters, moved registry to resources
  - OutputFormatter: Added resources/configs parameters, moved NormalizedContent to resources
  - TextNormalizer: Added resources/configs parameters, maintained normalizer functionality
  - FileFormatDetector: Completed _init_format_extensions method implementation
  - FileValidator: Enhanced with full dependency injection, removed direct file_format_detector import
- **Simplified core module exports**
  - core/__init__.py now only exports processing_pipeline from factory
  - Removed all direct imports and broken global instances
  - Clean separation between core components and external dependencies
- **Complete format_handlers/factory.py overhaul**
  - Standardized ALL processors to follow exact 5-step pattern
  - Simplified make_processor function with proper fallback logic
  - Eliminated duplicate imports and cleaned up architecture
- **Reorganized processor hierarchy**
  - Ability processors: text_processor, image_processor, video_processor, ocr_processor
  - MIME-type processors: xlsx_processor, pdf_processor, html_processor, csv_processor
  - Clear delegation: specific → ability → dependency modules
- **Consolidated video processing**
  - Video frames now handled by image_processor (frames are images)
  - Metadata extraction handled by MIME-type specific processors

## [2.0.0] - 2025-05-22 - Previous IoC Implementation

### Added
- Implemented Inversion of Control (IoC) pattern across all format handlers
  - Created `unified_handler.py` to implement composition over inheritance
  - Isolated third-party dependencies into dedicated processor modules
  - Added explicit dependency injection via resources dictionary
  - Implemented factory pattern for handler creation
  - Created centralized format registry with injected handlers
  - Added fail-fast approach for required resources
  - Extracted all third-party libraries to isolated modules
- Created processor modules for application format handling
  - Added `pdf_processor.py` for PDF document processing with PyPDF2
  - Added `docx_processor.py` for DOCX document processing with python-docx
  - Added `xlsx_processor.py` for XLSX spreadsheet processing with openpyxl

### Changed
- Refactored all format handlers to use composition instead of inheritance
  - Refactored `audio_handler.py` to use IoC pattern
  - Refactored `image_handler.py` to use IoC pattern
  - Refactored `text_handler.py` to use IoC pattern
  - Refactored `video_handler.py` to use IoC pattern
  - Refactored `application_handler.py` to use IoC pattern
  - Updated factory.py to centralize handler creation
  - Preserved backward compatibility throughout refactoring
  - Moved obsolete code to deprecated/ directory instead of deleting

### Technical Details
- Created dedicated processor modules in utils/dependency_modules/
  - PIL and SVG processors for image handling
  - pytesseract processor for OCR functionality
  - beautiful_soup_processor for HTML processing
  - lxml_processor for XML processing
  - icalendar_processor for calendar file handling
  - csv_processor for CSV handling
  - pymediainfo_processor for video metadata extraction
  - cv2_processor for video frame extraction 
  - ffmpeg_processor for video processing
- Implemented fail-fast approach for dependencies
- Improved testability with swappable components
- Enhanced code maintainability with decoupled dependencies

## [1.9.0] - 2025-03-23

### Added
- Enabled thumbnail extraction capability in VideoHandler
  - Added integration with video_processor.py for thumbnail generation
  - Implemented automatic feature detection based on processor availability
  - Added support for thumbnail extraction in both basic and enhanced extraction modes
  - Updated tests to dynamically check for thumbnail capabilities
  - Enhanced documentation to reflect new functionality
  - Marked all related tasks as complete in IMPLEMENTATION_STATUS.md

### Changed
- Updated VideoHandler documentation with enhanced descriptions
- Improved test resilience to accommodate feature presence without breaking tests
- Updated IMPLEMENTATION_STATUS.md to mark video_processor implementation as complete
- Consolidated misc. documentation in top-level directory into ROADMAP.md

## [1.8.0] - 2025-03-22

### Added
- Implemented refactoring of core classes to dataclasses and Pydantic models
  - Refactored ProcessingResult to dataclass for simplified instantiation and better equality comparisons
  - Refactored FormattedOutput to dataclass for cleaner code and automatic special methods
  - Refactored BatchResult to dataclass with post_init initialization for calculated fields
  - Refactored Content to Pydantic model with validation and serialization capabilities
  - Refactored NormalizedContent to extend the Pydantic Content model
  - Added new ValidationResult Pydantic model with comprehensive validation capabilities
  - Created test_validation_result.py with full test coverage for the new ValidationResult class
  - Regenerated documentation for all refactored classes

### Changed
- Updated to_dict() methods to use Pydantic's model_dump() for Pydantic models
- Preserved backward compatibility with all existing code
- Enhanced type checking with proper annotations and defaults
- Improved error handling with validation in Pydantic models

### Technical Details
- Used field(default_factory=list/dict) for proper mutable default values in dataclasses
- Used Pydantic Field(default_factory=list/dict) for validation
- Configured Pydantic models with proper Config class options
- Ensured datetime serialization is consistent with previous implementation
- Maintained all existing methods to preserve API compatibility

## [1.7.0] - 2025-03-22

### Added
- Added comprehensive test suite for future refactoring to dataclasses and Pydantic models
  - Added test_dataclass_refactoring.py with tests for ProcessingResult, BatchResult, and FormattedOutput
  - Added test_pydantic_refactoring.py with tests for Content, NormalizedContent, and a new ValidationResult
  - Added test_refactoring_integration.py to verify integration with other components
  - Generated detailed documentation for all refactoring tests
  - Added new refactoring tests section in documentation/tests/ directory
  - Updated main tests index to include refactoring tests

### Technical Details
- Tests verify functionality preservation when refactoring traditional classes to dataclasses
- Tests ensure compatibility with different versions of Pydantic (v1 and v2)
- Integration tests validate interactions with ProcessingPipeline, OutputFormatter, and TextNormalizer
- Added tests for validation benefits provided by Pydantic models
- Ensured tests run successfully in the current environment

## [1.6.0] - 2025-03-21

### Added
- Video processor implementation with thumbnail extraction
  - Added VideoProcessor with memory-efficient frame extraction
  - Implemented thumbnail generation using ffmpeg and OpenCV
  - Added key frame extraction at regular intervals
  - Added detailed video information extraction
  - Integrated with VideoHandler for seamless processing
  - Added support for all video format types (MP4, WebM, AVI, MKV, MOV)

### Fixed
- Fixed critical memory issues throughout the application
  - Fixed ResourceMonitor memory limit (from 1GB to 6GB)
  - Added aggressive garbage collection in batch processing
  - Implemented dynamic batch size adjustment for low-memory conditions
  - Added detailed memory usage logging for easier troubleshooting
  - Fixed memory leak in video processing with streaming extraction
  - Implemented memory-efficient mediainfo usage via streaming mode
  - Corrected memory reporting in resource utilization tests

### Changed
- Enhanced VideoHandler with processor architecture
  - Updated to use memory-efficient video processor
  - Added thumbnail extraction capability
  - Improved metadata extraction with streaming analysis
  - Added memory-safe fallback modes when processors are unavailable

## [1.5.6] - 2025-03-21

### Added
- Regenerated documentation for format_handlers and tests
  - Used documentation generator tool to create updated documentation
  - Updated format_handlers documentation with latest changes
  - Updated tests documentation in tests_updated folder
  - Ensured all recently modified code is properly documented
  - Generated cross-linked documentation for improved navigation

## [1.5.5] - 2025-03-21

### Fixed
- Fixed application handler test failures
  - Improved test file creation for PDF, DOCX, and XLSX formats
  - Updated tests to handle realistic file processing scenarios
  - Added proper document structure for Office document tests
  - Adjusted test assertions to accommodate processing variations
  - Fixed XLSX test file with proper shared strings handling

## [1.5.4] - 2025-03-21

### Added
- Regenerated comprehensive test documentation
  - Used documentation generator tool to create updated test documentation
  - Created tests_updated folder with latest test documentation
  - Generated detailed documentation for all test modules, classes, and methods
  - Improved navigability with proper cross-linking between test files

### Fixed
- Fixed multiple issues in audio processor tests
  - Corrected mock implementations for audio segment handling
  - Improved test assertions to match actual output formats
  - Added proper handling for tag data in metadata tests
  - Fixed test_extract_waveform to properly handle slice operations
  - Fixed test_process_audio to correctly match transcription output

## [1.5.3] - 2025-03-21

### Fixed
- Fixed bug in DOCX processor where non-numeric heading levels were causing errors
  - Improved heading level parsing to handle custom or non-standard heading styles
  - Added fallback to default level 1 when heading format is unexpected
  - Enhanced error handling for robust processing of a wider variety of DOCX files
  - Fixed failing tests in the test_docx_processor.py suite

- Fixed type issue in Python API for resource limits
  - Ensured proper type handling for resource limit parameters in convert_batch method
  - Updated test to pass appropriate parameter types

## [1.5.2] - 2025-03-21

### Changed
- Reorganized documentation folder for improved navigation and maintenance
  - Moved all documentation files to their respective subfolders
  - Grouped test documentation by component type (handlers, processors, managers, etc.)
  - Updated index files with comprehensive navigation structure
  - Created dedicated README with overview of documentation organization
  - Ensured latest versions of documentation files are preserved

## [1.5.1] - 2025-03-21

### Changed
- Enhanced test documentation with comprehensive docstrings
  - Updated test_text_handler.py with detailed method docstrings
  - Updated test_image_handler.py with detailed method docstrings
  - Updated test_audio_handler.py with detailed method docstrings
  - Updated test_video_handler.py with detailed method docstrings
  - Updated test_base_processor.py with detailed method docstrings
  - Updated test_python_api.py with detailed method docstrings
  - Updated test_interface_factory.py with detailed method docstrings
- Improved code readability and maintainability with clearer test descriptions
- Enhanced developer experience with more descriptive test failure messages

## [1.5.0] - 2025-03-21

### Added
- XLSX processor implementation using openpyxl
  - Added XlsxProcessor with full XLSX parsing capabilities
  - Added text extraction from worksheet cells with proper formatting
  - Added metadata extraction including title, creator, and document properties
  - Added structure extraction for sheets, including dimensions and sample data
  - Added support for multiple sheets in a workbook
  - Added comprehensive test coverage for all features
- Enhanced application handler to use XLSX processor
  - Integrated XLSX processor into the application handler pipeline
  - Added graceful fallback when openpyxl is not available
  - Preserved backward compatibility with existing code
- Updated project documentation
  - Added documentation for XLSX processor architecture
  - Updated implementation status to reflect XLSX completion
  - Updated dummy_implementations.md to reflect completed XLSX parsing

### Changed
- Refactored ApplicationHandler to use the processor architecture for XLSX files
- Updated documentation to reflect new XLSX capabilities
- Enhanced error handling for XLSX processing

### Technical Details
- Extended dependency checking for openpyxl library
- Added support for cell formatting with proper data types
- Implemented sheet dimension analysis
- Enhanced fallback ZIP-based extraction when library is not available

## [1.4.0] - 2025-03-21

### Added
- DOCX processor implementation using python-docx
  - Added DocxProcessor with full DOCX parsing capabilities
  - Added text extraction from paragraphs and tables
  - Added metadata extraction including title, author, and document properties
  - Added structure extraction for headings, sections, and tables
- Enhanced application handler to use DOCX processor
  - Integrated DOCX processor into the application handler pipeline
  - Added graceful fallback when python-docx is not available
  - Preserved backward compatibility with existing code
- Comprehensive test coverage for DOCX functionality
  - Unit tests for DocxProcessor component
  - Integration tests with ApplicationHandler
  - Tests for fallback behavior when python-docx is unavailable
- Added documentation for DOCX processor architecture

### Changed
- Refactored ApplicationHandler to use the processor architecture for DOCX files
- Updated implementation status in project documentation
- Enhanced error handling for DOCX processing

### Technical Details
- Extended dependency checking for python-docx library
- Added content extraction from tables and formatted text
- Implemented proper document structure analysis
- Enhanced fallback ZIP-based extraction when library is not available

## [1.3.0] - 2025-03-21

### Added
- OCR capability for image processing using PyTesseract
  - Added ImageProcessor interface for image processing
  - Implemented PyTesseractProcessor with OCR capabilities
  - Added text extraction from images with multiple language support
  - Added metadata extraction including dimensions, format, and EXIF data
  - Added visual feature extraction including text regions and bounding boxes
- Enhanced image handler to use OCR processor
  - Integrated OCR into the image processing pipeline
  - Added graceful fallback when Tesseract is not available
  - Preserved backward compatibility with existing code
- Comprehensive test coverage for OCR functionality
  - Unit tests for PyTesseractProcessor component
  - Integration tests with ImageHandler
  - Tests for fallback behavior when OCR is unavailable
- Expanded processor architecture documentation
  - Updated format handlers documentation with processor details
  - Added dedicated README for the processors module
  - Extended main documentation with recent updates

### Changed
- Refactored ImageHandler to use the processor architecture
- Updated documentation to reflect new OCR capabilities
- Updated implementation status in project documentation
- Enhanced error handling for OCR processing

### Technical Details
- Extended Strategy pattern across all processors for consistency
- Implemented proper dependency checking for Tesseract
- Added support for multiple OCR languages and configurations
- Implemented feature extraction capabilities beyond basic OCR

## [1.2.0] - 2025-03-18

### Added
- Enhanced format handlers with processor architecture using Strategy pattern
  - Created processor interfaces with dependency inversion
  - Implemented PDF processing with PyPDF2
  - Implemented speech-to-text with Whisper
  - Added support for text extraction from all PDF pages
  - Added support for PDF metadata extraction
  - Added support for audio transcription with timestamps
  - Added waveform data extraction for audio files
- Added comprehensive unit tests for manager components
  - Complete test coverage for BatchProcessor component
  - Complete test coverage for ResourceMonitor component
  - Complete test coverage for SecurityMonitor component
  - Integration tests for all manager components

### Changed
- Refactored PDF parsing to use PyPDF2 processor
- Refactored audio handler to use Whisper processor
- Updated documentation to reflect new architecture
- Added required dependencies to requirements.txt
- Improved error handling with graceful fallbacks

### Technical Details
- Implemented BaseProcessor and specialized processor interfaces
- Created modular processor implementations with dependency checks
- Added support for multiple Whisper models (tiny to large)
- Enhanced PDF processing with structure extraction
- Implemented robust test fixtures with mocking of external dependencies
- Added tests for edge cases in batch processing, resource monitoring, and security validation

## [1.1.0] - 2025-03-17

### Added
- Programmatic access with new PythonAPI and InterfaceFactory
  - PythonAPI implementation for programmatic file conversion
  - InterfaceFactory for creating different interface instances
  - Single file and batch conversion methods
  - Configuration management methods
  - Comprehensive test coverage for all API methods
  - Example scripts demonstrating API usage
  - Detailed documentation for programmatic usage
  - Integration with existing components (processing pipeline, batch processor, format registry)

## [1.0.0] - 2025-03-17

### Added
- Video format support with new VideoHandler class
  - MP4 format support
  - WebM format support
  - AVI format support
  - MKV format support
  - MOV format support
  - Comprehensive metadata extraction with pymediainfo
  - Support for video, audio, and subtitle track information
  - Fallback mode for environments without pymediainfo
  - Unit tests for VideoHandler
  - Integration with FormatRegistry
  - Increased format coverage from 80% to 100%
- Complete test coverage for all Manager components
  - Unit tests for BatchProcessor implementation
  - Unit tests for ResourceMonitor implementation
  - Unit tests for SecurityMonitor implementation
  - Integration tests for all Manager components
- Milestone: Achieved 100% format coverage across all MIME-type categories
  - Complete implementation of all planned format handlers
  - Full test coverage for all handlers
  - Comprehensive metadata extraction for all supported formats
  - Graceful fallbacks for all formats when specialized libraries are unavailable

## [0.6.0] - 2025-03-17

### Added
- Audio format support with new AudioHandler class
  - MP3 format support
  - WAV format support
  - OGG format support
  - FLAC format support
  - AAC format support
  - Comprehensive metadata extraction with pydub
  - Fallback mode for environments without pydub
  - Unit tests for AudioHandler
  - Integration with FormatRegistry
  - Increased format coverage from 60% to 80%

## [0.5.2] - 2025-03-17

### Added
- Enhanced documentation generator with path ignoring capabilities
  - Added ability to ignore specific paths when generating documentation
  - Support for a `.docignore` file to store paths to ignore
  - Command-line options to specify paths to ignore
  - Automatic saving of ignore paths for future use
  - Unit tests for the new ignore functionality
  - Updated TOOLS.md with documentation for the new features

## [0.5.1] - 2025-03-17

### Added
- Enhanced Command-Line Interface with batch processing
  - Directory processing support with BatchProcessor integration
  - Parallel processing with configurable thread count
  - Progress bar visualization using tqdm
  - Resource utilization reporting
  - Support for glob patterns and wildcards
  - Batch processing summary statistics

### Changed
- Updated main.py to use BatchProcessor for directory processing
- Enhanced command-line options with parallel processing and resource limits
- Updated IMPLEMENTATION_STATUS.md to mark CommandLineInterface as complete
- Updated PHASE16_README.md to reflect CLI implementation

## [0.5.0] - 2025-03-17

### Added
- Complete Manager Components
  - BatchProcessor: Orchestrates batch processing with parallel and sequential processing modes
  - ResourceMonitor: Monitors system resource usage with configurable CPU and memory limits
  - ErrorMonitor: Centralizes error handling with detailed error tracking and reporting
  - SecurityMonitor: Validates file security and sanitizes content with configurable rules
  - BatchResult: Tracks batch processing results with detailed statistics
- Test coverage for Manager components
  - Unit tests for BatchResult implementation
  - Unit tests for ErrorMonitor implementation
  - Unit tests for ResourceMonitor implementation
  - Unit tests for SecurityMonitor implementation
  - Unit tests for BatchProcessor implementation

### Changed
- Updated IMPLEMENTATION_STATUS.md to reflect completed Manager components
- Updated PHASE16_README.md to show Manager components are fully implemented
- Improved project stability with error tracking and resource monitoring

## [0.4.0] - 2025-03-16

### Added
- Complete Core Processing Pipeline
  - ProcessingPipeline: Orchestrates the entire conversion process
  - ContentExtractor: Extracts content using format handlers
  - TextNormalizer: Normalizes text with whitespace, line ending, and Unicode normalization
  - OutputFormatter: Formats text in txt, json, and markdown formats
  - ProcessingResult: Tracks and reports detailed processing results
- Enhanced CLI capabilities with format and normalizer options
- Support for different output formats (txt, json, markdown)
- Text normalization with configurable normalizers

### Changed
- Updated main.py to use full ProcessingPipeline for conversion
- Enhanced command-line interface with new options for normalization
- Updated IMPLEMENTATION_STATUS.md to reflect completed Core Processing components
- Updated PHASE16_README.md with complete Core Processing Class Group
- Reorganized next steps in documentation to focus on Manager components

## [0.3.0] - 2025-03-16

### Added
- FormatRegistry component for centralized format handling
  - Centralized handler registration and management
  - Unified interface for format detection and content extraction
  - Format categorization by MIME type
  - Comprehensive test suite for the registry
- Updated main.py to use FormatRegistry for content extraction
- Revised format listing to use categorized formats from registry

### Changed
- Simplified process_file function in main.py using FormatRegistry
- Updated IMPLEMENTATION_STATUS.md with completed FormatRegistry
- Updated PHASE16_README.md to include FormatRegistry in Format Handlers group
- Reorganized next steps in IMPLEMENTATION_STATUS.md

## [0.2.0] - 2025-03-16

### Added
- Application format support with new ApplicationHandler class
  - PDF format support
  - JSON format support
  - DOCX format support
  - XLSX format support
  - ZIP format support
- New test file for ApplicationHandler
- Comprehensive documentation for the ApplicationHandler
- Added a test JSON file for manual testing

### Changed
- Updated main.py to handle application formats
- Updated format_handlers/__init__.py with application handler info
- Increased format coverage from 40% to 60%
- Improved IMPLEMENTATION_STATUS.md with updated next steps
- Updated PHASE16_README.md to reflect current status
- Updated README.md with application format support information

### Fixed
- Fixed missing format support in --list-formats output

## [0.1.0] - 2025-03-15

### Added
- Initial implementation of the Omni-Converter
- Core utility modules:
  - Configuration management
  - File system operations
  - Format detection
  - Logging
  - Validation
- Format handlers:
  - Base handler interface
  - Text handler (HTML, XML, plain text, CSV, calendar)
  - Image handler (JPEG, PNG, GIF, WebP, SVG)
- Command-line interface in main.py
- Comprehensive test suite:
  - Format support coverage tests
  - Processing success rate tests
  - Resource utilization tests
  - Processing speed tests
  - Error handling tests
  - Security effectiveness tests
  - Text quality tests
- Documentation:
  - README.md
  - SAD.md (System Architecture Document)
  - PRD.md (Product Requirements Document)
  - PHASE16_README.md
  - IMPLEMENTATION_STATUS.md