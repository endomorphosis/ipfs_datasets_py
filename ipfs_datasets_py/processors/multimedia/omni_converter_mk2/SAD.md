# Omni-Converter:  Core Architecture - Last Updated 5-27-2025

## 1. Format Detection and Handling System
- Simple file signature and extension-based detection
- Direct integration with established libraries for common formats
- Basic format capability registry to track supported formats
- Focus on top 5 formats in each category for initial implementation
- Simple adapter pattern for future extensibility

## 2. Processing Pipeline
- Sequential processing with clearly defined stages:
    - Format detection
    - Basic validation
    - Content extraction
    - Text normalization
    - Output formatting
- Clean separation between stages for maintainability
- Simple logging of processing errors

## 3. Basic Resource Management
- Configurable global limits for memory and CPU usage
- Simple timeout mechanism for long-running processes
- Batch size control to prevent resource exhaustion
- Optional throttling for particularly resource-intensive formats

## 4. Error Handling
- Graceful failure for individual files without crashing batch processing
- Structured error logging with format-specific details
- Basic validation of input files before processing
- Simple skip-and-continue approach for corrupted files

## 5. Security Measures
- Input validation using file signatures and basic content checks
- Reliance on established libraries' security features
- Sanitization of output content
- Configurable limits on file sizes and processing complexity

## 6. Batch Processing
- Simple sequential batch processing with error isolation
- Status tracking for batch jobs
- Summary reporting of successful and failed conversions
- Interruptible processing with progress indicators

## 7. API and Interfaces
- Command-line interface with basic options
- Python API for programmatic access
- Simple GUI interface for future extensibility
- Clean separation of core functionality from interfaces
- Configuration file support for persistent settings

## Future Extensibility Considerations
The architecture is designed to allow for future enhancements:
- Format Support: The format handling system uses a simple adapter pattern that can evolve into a full plugin architecture in the future.
- Resource Management: The basic resource limits can be expanded to a more sophisticated monitoring and throttling system as needed.
- Processing Pipeline: The sequential pipeline can be enhanced to support parallel processing when resource constraints are better understood.
- Error Handling: The simple error logging can evolve into more sophisticated recovery mechanisms based on observed failure patterns.
- Security: The basic security measures can be enhanced with more robust sandboxing as security requirements evolve.
- Quality Assessment: Simple content extraction can be enhanced with formal quality metrics when reference data becomes available.
- Interface: The clean separation of core functionality and interfaces allows for addition of a GUI or other interfaces.

## Architecture Diagram
```mermaid
graph TD
    subgraph Interfaces
        CLI[Command Line Interface]
        API[Python API]
        Config[Configuration Manager]
    end

    subgraph Core["Core Processing System"]
        FD[Format Detection]
        BV[Basic Validation]
        CE[Content Extraction]
        TN[Text Normalization]
        OF[Output Formatting]
    end

    subgraph Managers
        BP[Batch Processor]
        RM[Resource Monitor]
        EH[Error Handler]
        SM[Security Manager]
    end

    subgraph FormatHandlers["Format Handlers"]
        TH[Text Handlers]
        IH[Image Handlers]
        AH[Audio Handlers]
        VH[Video Handlers]
        APH[Application Handlers]
    end

    subgraph Storage
        FS[File System]
        Logger
    end

    %% Interface Connections
    CLI --> BP
    API --> BP
    Config --> Core
    Config --> Managers

    %% Core Process Flow
    BP --> FD
    FD --> BV
    BV --> CE
    CE --> TN
    TN --> OF
    OF --> FS

    %% Manager Connections
    RM --> Core
    EH --> Core
    SM --> Core
    BP --> EH

    %% Format Handler Connections
    FD --> FormatHandlers
    CE --> FormatHandlers

    %% Logging
    Core --> Logger
    Managers --> Logger
    FormatHandlers --> Logger

    %% Storage Connection
    FormatHandlers --> FS

    classDef core fill:#f9f,stroke:#333,stroke-width:2px
    classDef manager fill:#bbf,stroke:#333,stroke-width:1px
    classDef interface fill:#bfb,stroke:#333,stroke-width:1px
    classDef handler fill:#fbb,stroke:#333,stroke-width:1px
    classDef storage fill:#ffd,stroke:#333,stroke-width:1px
    classDef future fill:#fff,stroke:#999,stroke-width:1px,stroke-dasharray: 5 5

    class Core core
    class Managers manager
    class Interfaces interface
    class FormatHandlers handler
    class Storage storage
    class FuturePlugin,FutureParallel,FutureSandbox,FutureQuality,FutureGUI future
```

## 1. Interfaces - Class Diagram
```mermaid
classDiagram
    class CommandLineInterface {
        -ArgumentParser parser
        -Configs configs
        +parse_arguments() list
        +run_from_args(args) bool
        +display_help() void
        +display_version() void
        +display_results(batch_results) void
    }

    class PythonAPI {
        -Configs configs
        -BatchProcessor batch_processor
        +convert_file(file_path, output_path, options) Result
        +convert_batch(file_paths, output_dir, options) BatchResult
        +supported_formats dict
        +set_config(config_dict) bool
        +get_config() dict
    }

    class Configs {
        -dict default_config
        -str config_path
        -dict current_config
        +load_config(config_path) dict
        +save_config(config_path) bool
        +get_config_value(key, default) any
        +set_config_value(key, value) void
        +reset_to_defaults() void
        +validate_config() bool
    }

    class InterfaceFactory {
        +create_cli() CommandLineInterface
        +create_api() PythonAPI
        +configs Configs
    }

    InterfaceFactory --> CommandLineInterface : creates
    InterfaceFactory --> PythonAPI : creates 
    InterfaceFactory --> Configs : creates
    CommandLineInterface --> Configs : uses
    PythonAPI --> Configs : uses
```

## 2. Core Processing System - Class Diagram
```mermaid
classDiagram
    class ProcessingPipeline {
        -FileFormatDetector detector
        -FileValidator validator
        -ContentExtractor extractor
        -TextNormalizer normalizer
        -OutputFormatter formatter
        -ErrorMonitor error_monitor
        +process_file(file_path, output_path, options) Result
        +status Status
        +register_listeners(listener) void
    }

    class FileFormatDetector {
        -dict format_signatures
        -dict format_extensions
        -FormatRegistry registry
        +detect_format(file_path) Format
        +supported_formats list
        +is_format_supported(format) bool
    }

    class FileValidator {
        -dict validation_rules
        +validate_file(file_path, format) ValidationResult
        +is_valid_for_processing(file_path, format) bool
        +get_validation_errors(file_path, format) list
    }

    class ContentExtractor {
        -dict format_handlers
        -FormatRegistry registry
        +extract_content(file_path, format, options) Content
        +get_extraction_capabilities() dict
        +register_format_handler(format, handler) void
    }

    class TextNormalizer {
        -list normalizers
        +normalize_text(content) NormalizedContent
        +register_normalizer(normalizer) void
        +applied_normalizers list
    }

    class OutputFormatter {
        -dict output_formats
        -str default_format
        +format_output(content, format, options) FormattedOutput
        +available_formats list
        +register_format(format, formatter) void
    }

    class ProcessingResult {
        +bool success
        +str file_path
        +str output_path
        +str format
        +list errors
        +dict metadata
        +str content_hash
        +datetime timestamp
    }

    ProcessingPipeline --> FileFormatDetector
    ProcessingPipeline --> FileValidator
    ProcessingPipeline --> ContentExtractor
    ProcessingPipeline --> TextNormalizer
    ProcessingPipeline --> OutputFormatter
    ProcessingPipeline --> ProcessingResult : produces
```

## 3. Managers - Class Diagram
```mermaid
classDiagram
    class BatchProcessor {
        -ProcessingPipeline pipeline
        -ErrorMonitor error_monitor
        -ResourceMonitor resource_monitor
        -Logger logger
        -int max_batch_size
        -bool continue_on_error
        +process_batch(file_paths, output_dir, options) BatchResult
        +cancel_processing() void
        +processing_status BatchStatus
        +set_max_batch_size(size) void
        +set_continue_on_error(flag) void
    }

    class ResourceMonitor {
        -float cpu_limit_percent
        -int memory_limit
        -dict current_resource_usage
        -bool active_monitoring
        +start_monitoring() void
        +stop_monitoring() void
        +current_resource_usage dict
        +are_resources_available bool
        +set_resource_limits(cpu, memory) void
    }

    class ErrorMonitor {
        -Logger logger
        -dict error_counters
        -list error_types
        -bool suppress_errors
        +handle_error(error, context) void
        +log_error(error, context) void
        +error_statistics dict
        +reset_error_counters() void
        +set_error_suppression(flag) void
    }

    class SecurityMonitor {
        -list file_size_limits
        -list allowed_formats
        -dict security_rules
        +validate_security(file_path, format) SecurityResult
        +is_file_safe(file_path, format) bool
        +sanitize_content(content) SanitizedContent
        +set_security_rules(rules) void
    }

    class BatchResult {
        +int total_files
        +int successful_files
        +int failed_files
        +list results
        +dict statistics
        +datetime start_time
        +datetime end_time
        +get_summary() dict
        +get_failed_files() list
        +get_successful_files() list
    }

    BatchProcessor --> ResourceMonitor : uses
    BatchProcessor --> ErrorMonitor : uses
    BatchProcessor --> SecurityMonitor : uses
    BatchProcessor --> BatchResult : produces
```

## 4. Format Handlers - Class Diagram
```mermaid
classDiagram
    class FormatHandler {
        <<interface>>
        +can_handle(file_path, format) bool
        +extract_content(file_path, options) Content
        +capabilities dict
    }

    class ServiceFormatHandler {
        <<service>>
        #str handler_name
        #list supported_formats
        #dict capabilities
        +can_handle(file_path, format) bool
        +extract_content(file_path, options) Content
        +capabilities dict
        #validate_input(file_path) ValidationResult
        #do_extraction(file_path, options) Content
    }

    class TextHandler {
        <<service>>
        -list text_formats
        -dict format_parsers
        +do_extraction(file_path, options) Content
        +register_parser(format, parser) void
    }

    class ImageHandler {
        <<service>>
        -list image_formats
        -OCREngine ocr_engine
        +do_extraction(file_path, options) Content
        +set_ocr_engine(engine) void
    }

    class AudioHandler {
        <<service>>
        -list audio_formats
        -SpeechToTextEngine stt_engine
        +do_extraction(file_path, options) Content
        +set_stt_engine(engine) void
    }

    class VideoHandler {
        <<service>>
        -list video_formats
        -SpeechToTextEngine stt_engine
        -ImageHandler image_handler
        +do_extraction(file_path, options) Content
        +set_stt_engine(engine) void
    }

    class ApplicationHandler {
        <<service>>
        -list application_formats
        -dict format_processors
        +do_extraction(file_path, options) Content
        +register_processor(format, processor) void
    }

    class FormatRegistry {
        <<service>>
        -dict handlers
        -dict format_to_handler_map
        +register_handler(format, handler) void
        +get_handler(format) FormatHandler
        +supported_formats list
        +is_format_supported(format) bool
    }

    class Content {
        +str text
        +dict metadata
        +list sections
        +str source_format
        +str source_path
        +datetime extraction_time
    }

    FormatHandler <|.. ServiceFormatHandler  : implements
    ServiceFormatHandler o-- TextHandler : injected via constructor
    ServiceFormatHandler o-- ImageHandler : injected via constructor
    ServiceFormatHandler o-- AudioHandler : injected via constructor
    ServiceFormatHandler o-- VideoHandler : injected via constructor
    ServiceFormatHandler o-- ApplicationHandler : injected via constructor
    FormatRegistry --> FormatHandler : manages
    ServiceFormatHandler --> Content : produces
```

## 5. Handler Example: Text Handler - Class Diagram
```mermaid
classDiagram
    class TextHandler {
        -list supported_formats
        -dict format_parsers
        +extract_content(file_path, options) Content
        +register_parser(format, parser) void
        +get_supported_formats() list
    }
```

## 6. Storage - Class Diagram
```mermaid
classDiagram
    class FileSystem {
        +read_file(file_path, mode) FileContent
        +write_file(file_path, content, mode) bool
        +list_files(directory, pattern) list
        +file_exists(file_path) bool
        +get_file_info(file_path) FileInfo
        +create_directory(directory_path) bool
    }

    class Logger {
        -str log_level
        -str log_file
        -bool console_output
        -dict log_formatters
        +log(level, message, context) void
        +debug(message, context) void
        +info(message, context) void
        +warning(message, context) void
        +error(message, context) void
        +critical(message, context) void
        +set_log_level(level) void
        +set_log_file(file_path) void
        +enable_console_output(flag) void
    }

    class FileInfo {
        +str path
        +int size
        +datetime modified_time
        +str mime_type
        +str extension
        +bool is_readable
        +bool is_writable
    }

    class FileContent {
        +bytes raw_content
        +str text_content
        +str encoding
        +int size
        +str mime_type
        +get_as_text(encoding) str
        +as_binary bytes
    }

    class LogRecord {
        +str level
        +str message
        +dict context
        +datetime timestamp
        +str source
        +str to_string() str
        +to_dict() dict
    }

    FileSystem --> FileInfo : provides
    FileSystem --> FileContent : provides
    Logger --> LogRecord : creates
```
