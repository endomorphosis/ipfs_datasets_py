# Python Docstring Adverb Analyzer - Project Requirements Document (PRD)

## Executive Summary

**Project**: Python Docstring Adverb Analyzer  
**Version**: 1.0  
**Date**: Created based on rigorous requirements analysis  

**Problem Statement**: Python developers need a tool to identify and eliminate weak, imprecise adverbs from their docstrings to improve documentation clarity and professionalism.

**Solution**: A command-line tool that analyzes Python files, extracts docstrings, identifies adverbs using NLTK POS tagging, and provides detailed reports for documentation quality improvement.

## Minimum Viable Product (MVP)

### Core Functionality
1. **Command-line interface** accepting Python file paths
2. **Docstring extraction** from modules, classes, functions, and methods
3. **Adverb identification** using NLTK natural language processing
4. **Formatted output** showing adverb locations with context
5. **Error handling** with specific exit codes and messages

### Success Criteria - Rigorously Defined

#### 1. Successfully Parse Valid Python Files

**Definition**: "Successfully parse valid Python files means":

- **File Reading Success**:
  - Read entire file content without encoding errors
  - Handle UTF-8, ASCII, and PEP 263 encoding declarations
  - File size limit: ≤ 100MB (prevent memory exhaustion)

- **AST Parsing Success**:
  - `ast.parse()` completes without raising `SyntaxError`
  - Produces valid Abstract Syntax Tree object
  - Handles all Python versions 3.6+ syntax features

- **Docstring Extraction Success**:
  - **Module docstring**: First statement if string literal
  - **Class docstring**: First statement in class body if string literal  
  - **Function docstring**: First statement in function body if string literal
  - **Method docstring**: First statement in method body if string literal
  - Correctly identify docstrings vs regular string literals (position-dependent)
  - Handle triple-quoted strings (`"""` and `'''`)
  - Handle regular quoted strings (`"` and `'`) when used as docstrings

- **Coverage Requirements**:
  - Extract 100% of docstrings from all function definitions (`def`, `async def`)
  - Extract 100% of docstrings from all class definitions (`class`)
  - Extract module-level docstring if present
  - Include nested classes and functions
  - Include methods within classes

- **Edge Case Handling**:
  - Empty docstrings (zero-length strings) are valid and counted
  - Docstrings containing only whitespace are valid
  - No false positives: string literals not in docstring position are ignored

**Quantifiable Metrics**:
- AST parsing success rate: 100% for syntactically valid Python files
- Docstring extraction accuracy: 100% precision, 100% recall against manual verification
- Memory usage: ≤ 2x file size during parsing

#### 2. Extract All Docstrings - Rigorously Defined

**Definition**: "Extract all docstrings (module, class, function level) means":

- **Docstring Definition (PEP 257 Compliant)**:
  - **Module docstring**: First statement in module if isinstance(node, ast.Constant) and isinstance(node.value, str)
  - **Class docstring**: First statement in class body if isinstance(node, ast.Constant) and isinstance(node.value, str)
  - **Function docstring**: First statement in function body if isinstance(node, ast.Constant) and isinstance(node.value, str)
  - **Position requirement**: Must be first statement, not first expression

- **AST Node Types to Process**:
  - **ast.Module**: Check first statement
  - **ast.ClassDef**: Check first statement in body
  - **ast.FunctionDef**: Check first statement in body  
  - **ast.AsyncFunctionDef**: Check first statement in body
  - **Nested structures**: Recursively process all levels

- **Docstring Extraction Rules**:
  - **Valid docstring node**: `ast.Expr` containing `ast.Constant` with string value
  - **Python 3.8+**: Use `ast.Constant` for string literals
  - **Python 3.7-**: Use `ast.Str` for string literals (backward compatibility)
  - **Quote style agnostic**: Handle `"""`, `'''`, `"`, `'`
  - **Preserve content**: Maintain original string including whitespace, newlines

- **Exclusion Rules** (NOT docstrings):
  - String literals not in first statement position
  - String literals inside expressions (e.g., `return "string"`)
  - String literals used as function arguments
  - String literals in assignments (e.g., `x = "string"`)
  - Comments (not AST nodes)

**Quantifiable Metrics**:
- **Precision**: 100% of extracted strings are actual docstrings per PEP 257
- **Recall**: 100% of actual docstrings are extracted
- **Coverage**: Process all AST node types that can contain docstrings
- **Accuracy**: Line numbers match source file exactly

#### 3. Accurately Identify Adverbs - Rigorously Defined

**Definition**: "Accurately identify adverbs using NLTK POS tagging means":

- **Text Preprocessing Requirements**:
  - Tokenize docstring text using `nltk.word_tokenize()`
  - Handle punctuation attachment (e.g., "quickly," → "quickly" + ",")
  - Preserve original case for output while normalizing for POS tagging
  - Handle contractions (e.g., "don't" → "do" + "n't")

- **POS Tagging Accuracy**:
  - Use `nltk.pos_tag()` with Penn Treebank tagset
  - **Adverb tags to identify**: RB, RBR, RBS
    - RB: Adverb (quickly, never, here)
    - RBR: Adverb, comparative (faster, better)  
    - RBS: Adverb, superlative (fastest, best)
  - **Exclusions**: Do not tag as adverbs:
    - WRB: Wh-adverbs (when, where, how) - these are interrogative
    - Particles in phrasal verbs tagged RB (e.g., "turn *on*")

- **Known Limitations (Documented)**:
  - NLTK POS tagger baseline accuracy: ~97% on Penn Treebank
  - Context-dependent errors expected (e.g., "fast" as adjective vs adverb)
  - Domain-specific technical terms may be misclassified
  - Sentence boundary detection affects accuracy

- **Validation Requirements**:
  - **True Positives**: Words tagged RB/RBR/RBS that are actually adverbs
  - **False Positives**: Non-adverbs tagged as RB/RBR/RBS (acceptable ≤ 5%)
  - **False Negatives**: Actual adverbs not tagged as RB/RBR/RBS (acceptable ≤ 5%)

- **Output Precision**:
  - Report exact word as it appears in docstring (preserve case)
  - Include POS tag for transparency (e.g., "quickly (RB)")
  - Include sentence context (±3 words) for verification

**Quantifiable Metrics**:
- Precision: ≥ 95% of reported adverbs are actually adverbs
- Recall: ≥ 95% of actual adverbs in docstrings are identified
- Reproducibility: 100% consistent results on same input

#### 4. Provide Clear Output - Rigorously Defined

**Definition**: "Provide clear output showing adverb locations means":

- **Output Format Specification**:
  - **Header**: File path and summary count
  - **Body**: Structured list of findings
  - **Footer**: Summary statistics
  - Use consistent indentation (2 spaces per level)
  - Maximum line length: 80 characters (terminal-friendly)

- **Required Information Per Adverb**:
  - **Exact word**: As it appears in docstring (preserve case/punctuation)
  - **POS tag**: NLTK classification (RB, RBR, RBS)
  - **Location hierarchy**: Module → Class → Function/Method
  - **Line number**: Relative to start of docstring
  - **Context**: ±5 words surrounding the adverb

- **Sorting Requirements**:
  - Primary: Source code order (top to bottom)
  - Secondary: Within docstring by line number
  - Tertiary: Within line by character position

- **Edge Case Formatting**:
  - **No adverbs found**: "No adverbs found in docstrings"
  - **No docstrings**: "No docstrings found in file"
  - **Empty docstring**: "DOCSTRING: (empty)"
  - **Long contexts**: Truncate with "..." if > 80 chars
  - **Special characters**: Escape non-printable characters

- **Accessibility Requirements**:
  - Compatible with screen readers (no ASCII art/unicode boxes)
  - Colorblind-friendly (no color-only information)
  - Copy-pasteable (plain text format)

**Quantifiable Metrics**:
- 100% of required information present for each adverb
- Line length compliance: ≤ 80 characters per line
- Parsing time for output: Human can locate any adverb in ≤ 10 seconds
- Information density: All relevant data in ≤ 50 lines for typical file

#### 5. Handle Errors Gracefully - Rigorously Defined

**Definition**: "Handle errors gracefully means":

- **File System Errors**:
  - File not found: Exit with code 1, display "Error: File 'filepath' not found"
  - Permission denied: Exit with code 2, display "Error: Permission denied accessing 'filepath'"
  - Directory instead of file: Exit with code 3, display "Error: 'filepath' is a directory, not a file"

- **Python Syntax Errors**:
  - Invalid Python syntax: Exit with code 4, display "Error: Invalid Python syntax in 'filepath' at line X: [syntax error message]"
  - Non-Python file: Exit with code 5, display "Error: 'filepath' does not appear to be a Python file"

- **NLTK Errors**:
  - Missing NLTK data: Exit with code 6, display "Error: Required NLTK data not found. Run: python -m nltk.downloader punkt averaged_perceptron_tagger"
  - NLTK import failure: Exit with code 7, display "Error: NLTK not installed. Install with: pip install nltk"

- **General Requirements**:
  - All errors output to stderr, not stdout
  - No stack traces shown to user (logged internally if needed)
  - Each error message includes specific remediation steps
  - Program never crashes with unhandled exceptions
  - Exit codes follow Unix conventions (0 = success, >0 = error)

**Quantifiable Metrics**:
- 100% of anticipated error conditions have defined handling
- 0 unhandled exceptions reach the user
- All error messages ≤ 80 characters per line for terminal readability

## User Journey

### Primary User Persona
**Sarah**, Senior Python Developer leading documentation quality initiative

### Journey Steps
1. **Problem Recognition**: Identifies weak adverbs in team's documentation
2. **Tool Discovery**: Finds and installs the analyzer
3. **Initial Exploration**: Tests on single file (`python analyze_docstring_adverbs.py src/api/core.py`)
4. **Batch Analysis**: Processes multiple files with output redirection
5. **Error Handling**: Encounters syntax errors, receives clear guidance
6. **Integration**: Adds to pre-commit hooks and CI/CD pipeline
7. **Success Measurement**: Achieves cleaner, more precise documentation

### Success Metrics
- Complete analysis of 50 files in <10 minutes
- Zero unhandled errors during operation
- Quick decision-making enabled by clear output format
- Seamless integration into existing development workflow

## Technical Specifications

### System Requirements
- **Python Version**: 3.6 or higher
- **Dependencies**: NLTK with punkt and averaged_perceptron_tagger data
- **Memory**: Maximum 2x input file size during processing
- **File Size Limit**: 100MB maximum input file size

### Performance Requirements
- **Processing Speed**: Handle typical Python files (1000-5000 lines) in <5 seconds
- **Memory Efficiency**: Process files without excessive memory usage
- **Startup Time**: Initialize and validate dependencies in <2 seconds

### Compatibility Requirements
- **Operating Systems**: Linux, macOS, Windows
- **Python Implementations**: CPython 3.6+
- **File Encodings**: UTF-8, ASCII, PEP 263 encoding declarations
- **Terminal Compatibility**: 80-character line limit for universal compatibility

## Implementation Architecture

### High-Level Flow
1. **🔧 Argument Processing**: Parse CLI arguments, handle help requests
2. **📁 File Validation**: Verify file existence, permissions, type
3. **📦 Dependency Validation**: Check NLTK installation and data
4. **🔍 File Processing**: Read content, parse Python syntax
5. **📝 Docstring Extraction**: Walk AST, extract docstring metadata
6. **🎯 Adverb Analysis**: Tokenize, POS tag, filter adverbs
7. **📊 Statistics Generation**: Calculate summary metrics
8. **📤 Output Generation**: Format and display results

### Error Handling Strategy
- **Fail-fast approach**: Exit immediately on any validation failure
- **Specific exit codes**: Each error type has unique exit code (1-8)
- **Remediation guidance**: Every error message includes resolution steps
- **Silent operation**: No output to stdout on error conditions

### Testing Strategy
- **Red-Green-Refactor**: Write failing tests first, implement to pass
- **Comprehensive coverage**: Test all functions, edge cases, error conditions
- **Mock dependencies**: Isolate units from file system and NLTK
- **Exit code validation**: Verify all error conditions produce correct codes

## Quality Assurance

### Validation Criteria
- **Code Quality**: PEP 8 compliance, type hints, comprehensive docstrings
- **Test Coverage**: 100% line coverage, all branches tested
- **Error Handling**: All anticipated errors handled with appropriate messages
- **Documentation**: Complete function stubs, usage examples, troubleshooting guide

### Acceptance Criteria
- [ ] All functions implemented with type hints and docstrings
- [ ] Complete test suite with Given-When-Then structure
- [ ] All exit codes tested and documented
- [ ] Error messages provide actionable guidance
- [ ] Output format meets 80-character limit requirement
- [ ] Memory usage within 2x file size limit
- [ ] Processing time <5 seconds for typical files
- [ ] NLTK integration handles missing data gracefully
- [ ] Docstring extraction achieves 100% precision and recall
- [ ] Adverb identification achieves ≥95% precision and recall

## Risk Assessment

### Technical Risks
- **NLTK Dependency**: Users may not have NLTK installed or configured
  - *Mitigation*: Clear error messages with installation instructions
- **File Encoding Issues**: Non-standard encodings may cause failures
  - *Mitigation*: Robust encoding detection and fallback mechanisms
- **Large File Performance**: Memory usage may be excessive for very large files
  - *Mitigation*: 100MB file size limit with appropriate error message

### User Experience Risks
- **Complex Output**: Users may find output format confusing
  - *Mitigation*: Clear documentation and consistent formatting
- **False Positives**: NLTK may misidentify non-adverbs as adverbs
  - *Mitigation*: Document known limitations, provide context for verification

## Success Metrics

### Functional Metrics
- **Accuracy**: ≥95% precision and recall for adverb identification
- **Coverage**: 100% docstring extraction from valid Python files
- **Reliability**: 0 unhandled exceptions in normal operation
- **Performance**: <5 second processing time for typical files

### User Experience Metrics
- **Usability**: Users can analyze files without consulting documentation
- **Clarity**: Output enables quick decision-making on documentation changes
- **Integration**: Tool fits seamlessly into existing development workflows
- **Error Recovery**: Clear guidance enables users to resolve all error conditions

This PRD serves as the definitive specification for the Python Docstring Adverb Analyzer, providing rigorous definitions for all success criteria and comprehensive guidance for implementation and testing.
