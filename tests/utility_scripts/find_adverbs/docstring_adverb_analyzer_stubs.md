# Python Docstring Adverb Analyzer - Function Documentation

## Overview
This document provides comprehensive function stubs and documentation for the Python Docstring Adverb Analyzer tool. Each function is documented with complete signatures, type hints, docstrings, and implementation requirements.

## Module: docstring_adverb_analyzer.py

### main() -> int
**Signature:** `def main() -> int:`

**Description:** Main control flow for Python docstring adverb analyzer. Follows the user flow defined in requirements, with proper error handling and exit codes for each failure condition.

**Returns:**
- `int`: Exit code following Unix conventions
  - 0 = Success
  - 1 = File not found
  - 2 = Permission denied  
  - 3 = Path is directory
  - 4 = Invalid Python syntax or encoding error
  - 5 = Not a Python file
  - 6 = NLTK data missing
  - 7 = NLTK not installed
  - 8 = Invalid arguments

**Raises:**
- `SystemExit`: Always exits with appropriate code

**Implementation Requirements:**
- Process arguments through _parse_arguments()
- Validate file system through _validate_file_system()
- Validate dependencies through _validate_dependencies()
- Read and parse file content
- Extract docstrings from AST
- Analyze adverbs in docstrings
- Generate summary statistics
- Output formatted results
- Handle all exceptions and convert to appropriate exit codes

---

### _parse_arguments() -> Optional[str]
**Signature:** `def _parse_arguments() -> Optional[str]:`

**Description:** Parse command line arguments and handle help requests.

**Returns:**
- `Optional[str]`: File path if valid arguments, None if help displayed

**Raises:**
- `SystemExit`: Code 8 if invalid arguments

**Implementation Requirements:**
- Use argparse to define command line interface
- Accept single positional argument for file path
- Support -h, --help flags
- Display usage information when help requested
- Validate argument count and format
- Return file path string or None (if help shown)

---

### _validate_file_system(file_path: str) -> None
**Signature:** `def _validate_file_system(file_path: str) -> None:`

**Description:** Validate file system requirements for the input file.

**Args:**
- `file_path (str)`: Path to validate

**Raises:**
- `SystemExit`: 
  - Code 1 for file not found
  - Code 2 for permission denied
  - Code 3 for path is directory
  - Code 5 for non-Python file

**Implementation Requirements:**
- Check file exists using pathlib.Path.exists()
- Check file is readable using os.access()
- Check path is regular file, not directory
- Check file has .py extension
- Generate specific error messages for each failure condition
- Exit immediately on any validation failure

---

### _validate_dependencies() -> None
**Signature:** `def _validate_dependencies() -> None:`

**Description:** Validate that required dependencies are available.

**Raises:**
- `SystemExit`:
  - Code 6 for NLTK data missing
  - Code 7 for NLTK not installed

**Implementation Requirements:**
- Attempt to import nltk module
- Check for required NLTK data: punkt, averaged_perceptron_tagger
- Use nltk.data.find() to verify data availability
- Provide specific installation instructions in error messages
- Exit immediately if dependencies not satisfied

---

### _read_file_content(file_path: str) -> str
**Signature:** `def _read_file_content(file_path: str) -> str:`

**Description:** Read and return file content with proper encoding handling.

**Args:**
- `file_path (str)`: Path to the file to read

**Returns:**
- `str`: File content as string

**Raises:**
- `SystemExit`: Code 4 for encoding errors

**Implementation Requirements:**
- Handle UTF-8, ASCII, and PEP 263 encoding declarations
- Use appropriate encoding detection and fallback
- Read entire file content into memory
- Handle UnicodeDecodeError and other encoding issues
- Return file content as string with preserved formatting

---

### _parse_python_syntax(file_content: str, file_path: str) -> ast.AST
**Signature:** `def _parse_python_syntax(file_content: str, file_path: str) -> ast.AST:`

**Description:** Parse Python file content into AST.

**Args:**
- `file_content (str)`: Python source code content
- `file_path (str)`: File path for error messages

**Returns:**
- `ast.AST`: Parsed abstract syntax tree

**Raises:**
- `SystemExit`: Code 4 for syntax errors

**Implementation Requirements:**
- Use ast.parse() to convert source code to AST
- Handle SyntaxError exceptions with detailed error reporting
- Include line number and error description in error messages
- Support all Python 3.6+ syntax features
- Return complete AST object for further processing

---

### _extract_docstrings(ast_tree: ast.AST, file_path: str) -> List[Dict[str, Any]]
**Signature:** `def _extract_docstrings(ast_tree: ast.AST, file_path: str) -> List[Dict[str, Any]]:`

**Description:** Extract all docstrings from the AST with metadata.

**Args:**
- `ast_tree (ast.AST)`: Parsed abstract syntax tree
- `file_path (str)`: File path for context

**Returns:**
- `List[Dict[str, Any]]`: List of docstring information dictionaries
  - Each dict contains: content, location, context, quote_style

**Implementation Requirements:**
- Walk AST for Module, ClassDef, FunctionDef, AsyncFunctionDef nodes
- Identify first statement string literals (ast.Constant/ast.Str for compatibility)
- Extract docstring content preserving original formatting
- Collect metadata: line numbers, column offsets, parent context
- Build hierarchical context information (module → class → function)
- Handle nested structures correctly
- Return list of DocstringInfo dictionaries

**DocstringInfo Dictionary Structure:**
```python
{
    'content': str,           # Raw docstring content
    'location': {
        'line': int,          # Starting line number
        'col_offset': int,    # Column offset
        'end_line': int,      # Ending line number  
        'end_col_offset': int # Ending column offset
    },
    'context': {
        'type': str,          # 'module', 'class', 'function', 'method'
        'name': str,          # Function/class name or '<module>'
        'parent_class': str,  # Class name if method, else None
        'full_path': str      # Complete dotted path
    },
    'quote_style': str        # '"""', "'''", '"', "'"
}
```

---

### _analyze_adverbs(docstring_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]
**Signature:** `def _analyze_adverbs(docstring_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:`

**Description:** Analyze docstrings to identify adverbs with context.

**Args:**
- `docstring_list (List[Dict[str, Any]])`: List of docstring information

**Returns:**
- `List[Dict[str, Any]]`: List of adverb findings with metadata
  - Each dict contains: word, pos_tag, line, context, location_info

**Implementation Requirements:**
- For each docstring: tokenize text using nltk.word_tokenize()
- Apply POS tagging using nltk.pos_tag()
- Filter tokens for adverb tags: RB, RBR, RBS
- Extract ±5 word context around each adverb
- Preserve original word casing and punctuation
- Calculate line numbers within docstring
- Collect location and hierarchy information
- Handle empty docstrings gracefully

**Adverb Finding Dictionary Structure:**
```python
{
    'word': str,              # Adverb as it appears in text
    'pos_tag': str,           # NLTK POS tag (RB, RBR, RBS)
    'line': int,              # Line number within docstring
    'context': str,           # ±5 words surrounding adverb
    'location_info': {
        'docstring_type': str, # 'module', 'class', 'function', 'method'
        'parent_name': str,    # Name of containing element
        'full_path': str       # Complete hierarchical path
    }
}
```

---

### _generate_statistics(adverb_findings: List[Dict[str, Any]], docstring_list: List[Dict[str, Any]]) -> Dict[str, Any]
**Signature:** `def _generate_statistics(adverb_findings: List[Dict[str, Any]], docstring_list: List[Dict[str, Any]]) -> Dict[str, Any]:`

**Description:** Generate summary statistics from adverb findings.

**Args:**
- `adverb_findings (List[Dict[str, Any]])`: List of adverb findings
- `docstring_list (List[Dict[str, Any]])`: List of processed docstrings

**Returns:**
- `Dict[str, Any]`: Summary statistics dictionary containing:
  - total_adverbs, unique_adverbs, most_frequent, docstrings_processed

**Implementation Requirements:**
- Count total adverbs found (including duplicates)
- Count unique adverbs (case-insensitive)
- Identify most frequently occurring adverb
- Count total docstrings processed
- Handle edge cases: no adverbs, no docstrings
- Calculate frequency distribution

**Statistics Dictionary Structure:**
```python
{
    'total_adverbs': int,        # Total count including duplicates
    'unique_adverbs': int,       # Count of unique adverb words
    'most_frequent': str,        # Most common adverb (or None)
    'most_frequent_count': int,  # Count of most frequent adverb
    'docstrings_processed': int, # Total docstrings analyzed
    'adverb_frequency': dict     # {adverb: count} distribution
}
```

---

### _generate_output(file_path: str, adverb_findings: List[Dict[str, Any]], summary_stats: Dict[str, Any]) -> None
**Signature:** `def _generate_output(file_path: str, adverb_findings: List[Dict[str, Any]], summary_stats: Dict[str, Any]) -> None:`

**Description:** Generate and display formatted output to stdout.

**Args:**
- `file_path (str)`: Original file path being analyzed
- `adverb_findings (List[Dict[str, Any]])`: List of adverb findings
- `summary_stats (Dict[str, Any])`: Summary statistics

**Implementation Requirements:**
- Print header with file path and summary count
- Group findings by hierarchical structure: MODULE → CLASS → FUNCTION
- Display each adverb with: word, POS tag, line number, context
- Maintain 80-character line limit for all output
- Handle long contexts with truncation and "..." 
- Print comprehensive summary statistics
- Handle edge cases: no adverbs found, no docstrings found
- Format output for readability and accessibility

**Output Format Template:**
```
Analyzing: /path/to/file.py
Found X adverbs in Y docstrings

MODULE DOCSTRING:
  Line 2: "quickly" (RB)
    Context: "...process data quickly and efficiently..."

CLASS: ClassName
  DOCSTRING:
    Line 1: "carefully" (RB) 
      Context: "...handle errors carefully to avoid..."
  
  METHOD: method_name
    DOCSTRING:
      Line 3: "efficiently" (RB)
        Context: "...runs efficiently on large datasets..."

FUNCTION: function_name
  DOCSTRING:
    Line 1: "better" (RBR)
      Context: "...performs better than previous version..."

SUMMARY:
- Total adverbs found: X
- Unique adverbs: Y  
- Most common: "quickly" (3 occurrences)
```

## Error Handling Requirements

### Exit Code Definitions
- **0**: Success - All processing completed successfully
- **1**: File not found - Input file does not exist
- **2**: Permission denied - Cannot read input file
- **3**: Path is directory - Input path is directory, not file
- **4**: Invalid Python syntax or encoding error - File cannot be parsed
- **5**: Not a Python file - File does not have .py extension
- **6**: NLTK data missing - Required NLTK resources not available
- **7**: NLTK not installed - NLTK package not available
- **8**: Invalid arguments - Command line arguments invalid
- **9**: Unexpected error - Unhandled exception occurred

### Error Message Requirements
All error messages must:
- Be written to stderr, not stdout
- Include specific remediation steps
- Be ≤ 80 characters per line
- Use consistent format: "Error: [description]"
- Provide actionable guidance for resolution

### Validation Requirements
- **Precision**: 100% of extracted docstrings are actual docstrings per PEP 257
- **Recall**: 100% of actual docstrings are extracted
- **Adverb Accuracy**: ≥ 95% precision and recall for adverb identification
- **Output Compliance**: All lines ≤ 80 characters
- **Error Handling**: 0 unhandled exceptions reach the user

## Implementation Notes

### Python Compatibility
- Support Python 3.6+ syntax features
- Handle both ast.Constant (3.8+) and ast.Str (3.7-) for string literals
- Use appropriate typing annotations
- Follow PEP 8 style guidelines

### NLTK Requirements
- Required data packages: punkt, averaged_perceptron_tagger
- POS tags to identify: RB (adverb), RBR (comparative), RBS (superlative)
- Exclude WRB (interrogative adverbs) and phrasal verb particles

### Testing Requirements
- All functions must have comprehensive test coverage
- Tests follow Given-When-Then pattern
- Edge cases and error conditions thoroughly tested
- Mock external dependencies (file system, NLTK)
- Validate all exit codes and error messages
