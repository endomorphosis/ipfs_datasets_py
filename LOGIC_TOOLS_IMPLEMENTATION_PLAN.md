# Implementation Plan: Text to Logic Conversion Tools

## Overview

This document outlines the implementation plan for two new dataset tools:
1. **Text to First-Order Logic (FOL) Converter** - Converts natural language text into formal first-order logic representations
2. **Legal Text to Deontic Logic Converter** - Converts legal text into domain-specific deontic logic for legal reasoning

## Tool Specifications

### 1. Text to First-Order Logic (FOL) Converter

**File:** `text_to_fol.py`
**Function:** `convert_text_to_fol()`

#### Purpose
Convert natural language statements into First-Order Logic (FOL) formulas for formal reasoning, theorem proving, and logical analysis.

#### Input Parameters
- `text_input`: String or dataset containing natural language text
- `domain_predicates`: Optional list of domain-specific predicates
- `output_format`: Format for FOL output ('prolog', 'tptp', 'json', 'natural')
- `confidence_threshold`: Minimum confidence for conversion (0.0-1.0)
- `include_metadata`: Whether to include conversion metadata

#### Output Format
```json
{
  "status": "success",
  "fol_formulas": [
    {
      "original_text": "All cats are animals",
      "fol_formula": "∀x (Cat(x) → Animal(x))",
      "prolog_form": "animal(X) :- cat(X).",
      "tptp_form": "![X]: (cat(X) => animal(X))",
      "confidence": 0.95,
      "predicates_used": ["Cat", "Animal"],
      "quantifiers": ["∀"],
      "logical_operators": ["→"]
    }
  ],
  "summary": {
    "total_statements": 1,
    "successful_conversions": 1,
    "average_confidence": 0.95,
    "unique_predicates": ["Cat", "Animal"]
  }
}
```

#### Key Features
- Support for universal (∀) and existential (∃) quantifiers
- Logical operators: ∧ (and), ∨ (or), → (implies), ¬ (not), ↔ (iff)
- Predicate extraction and normalization
- Multiple output formats (symbolic logic, Prolog, TPTP)
- Confidence scoring for conversion quality

### 2. Legal Text to Deontic Logic Converter

**File:** `legal_text_to_deontic.py`
**Function:** `convert_legal_text_to_deontic()`

#### Purpose
Convert legal text (statutes, regulations, contracts) into deontic logic for legal reasoning, compliance checking, and normative analysis.

#### Input Parameters
- `legal_text`: String or dataset containing legal text
- `jurisdiction`: Legal jurisdiction context ('us', 'eu', 'uk', 'international')
- `document_type`: Type of legal document ('statute', 'regulation', 'contract', 'policy')
- `output_format`: Format for deontic logic output ('symbolic', 'defeasible', 'json')
- `extract_obligations`: Whether to extract obligation structures
- `include_exceptions`: Whether to include exception handling

#### Output Format
```json
{
  "status": "success",
  "deontic_formulas": [
    {
      "original_text": "Citizens must pay taxes by April 15th",
      "deontic_formula": "O(∀x (Citizen(x) → PayTaxes(x, april_15)))",
      "obligation_type": "mandatory",
      "subject": "Citizens",
      "action": "PayTaxes",
      "deadline": "april_15",
      "conditions": ["Citizen(x)"],
      "exceptions": [],
      "confidence": 0.92
    }
  ],
  "normative_structure": {
    "obligations": 1,
    "permissions": 0,
    "prohibitions": 0,
    "exceptions": 0
  },
  "legal_entities": ["Citizens"],
  "actions": ["PayTaxes"],
  "temporal_constraints": ["april_15"]
}
```

#### Key Features
- Deontic operators: O (obligation), P (permission), F (prohibition)
- Defeasible logic for exceptions and conflicting norms
- Legal entity and action extraction
- Temporal constraint handling
- Jurisdiction-specific rule patterns
- Normative conflict detection

## Implementation Architecture

### Directory Structure
```
ipfs_datasets_py/mcp_server/tools/dataset_tools/
├── __init__.py                 # Update to include new tools
├── text_to_fol.py             # FOL converter implementation
├── legal_text_to_deontic.py   # Deontic logic converter
├── logic_utils/               # Shared logic utilities
│   ├── __init__.py
│   ├── fol_parser.py         # FOL parsing and validation
│   ├── deontic_parser.py     # Deontic logic parsing
│   ├── predicate_extractor.py # Natural language to predicate mapping
│   └── logic_formatter.py    # Output formatting utilities
└── tests/
    ├── test_text_to_fol.py
    ├── test_legal_text_to_deontic.py
    └── test_logic_utils.py
```

### Dependencies

#### Core Dependencies
```
# Natural Language Processing
spacy>=3.4.0
nltk>=3.8
transformers>=4.20.0

# Logic and Symbolic Reasoning
sympy>=1.11.0
pyke>=1.1.1
rdflib>=6.0.0

# Legal Text Processing
legalese>=0.1.0  # Custom legal NLP library
dateutil>=2.8.0  # For temporal constraint parsing

# Machine Learning (for confidence scoring)
scikit-learn>=1.1.0
torch>=1.12.0  # For transformer-based models
```

#### Optional Dependencies
```
# Theorem Proving Integration
prover9>=0.2.0
vampire>=4.5.0
tptp-parser>=0.1.0

# Legal Ontologies
owlready2>=0.39  # For legal ontology integration
```

## Implementation Details

### 1. Text to FOL Converter (`text_to_fol.py`)

#### Core Algorithm
1. **Text Preprocessing**
   - Sentence segmentation using spaCy
   - Part-of-speech tagging
   - Named entity recognition
   - Dependency parsing

2. **Logical Structure Extraction**
   - Identify quantifier words ("all", "some", "every", "no")
   - Extract predicate relationships from verb phrases
   - Map nouns to logical predicates
   - Identify logical connectives ("and", "or", "if...then")

3. **FOL Formula Generation**
   - Generate variable bindings
   - Construct quantified formulas
   - Apply logical operators
   - Validate formula syntax

4. **Multi-format Output**
   - Symbolic logic notation (Unicode)
   - Prolog clause format
   - TPTP format for theorem provers
   - JSON structured representation

#### Example Implementation Snippet
```python
async def convert_text_to_fol(
    text_input: Union[str, Dict[str, Any]],
    domain_predicates: Optional[List[str]] = None,
    output_format: str = 'json',
    confidence_threshold: float = 0.7,
    include_metadata: bool = True
) -> Dict[str, Any]:
    """Convert natural language text to First-Order Logic."""
    
    try:
        # Initialize NLP pipeline
        nlp = spacy.load("en_core_web_sm")
        
        # Process input
        if isinstance(text_input, str):
            sentences = [text_input]
        elif isinstance(text_input, dict):
            sentences = extract_text_from_dataset(text_input)
        else:
            raise ValueError("Invalid input type")
        
        results = []
        for sentence in sentences:
            # Parse sentence
            doc = nlp(sentence)
            
            # Extract logical components
            logical_structure = extract_logical_structure(doc)
            
            # Generate FOL formula
            fol_formula = generate_fol_formula(logical_structure)
            
            # Calculate confidence
            confidence = calculate_conversion_confidence(doc, fol_formula)
            
            if confidence >= confidence_threshold:
                results.append({
                    "original_text": sentence,
                    "fol_formula": fol_formula,
                    "confidence": confidence,
                    # ... additional metadata
                })
        
        return {
            "status": "success",
            "fol_formulas": results,
            "summary": generate_summary(results)
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

### 2. Legal Text to Deontic Logic Converter (`legal_text_to_deontic.py`)

#### Core Algorithm
1. **Legal Text Analysis**
   - Legal document structure recognition
   - Normative sentence identification
   - Authority and subject extraction
   - Action and obligation detection

2. **Deontic Operator Mapping**
   - "must", "shall" → Obligation (O)
   - "may", "can" → Permission (P)
   - "must not", "shall not" → Prohibition (F)
   - "unless", "except" → Exception handling

3. **Temporal Constraint Extraction**
   - Date and deadline parsing
   - Duration and period identification
   - Temporal relationship mapping

4. **Normative Structure Generation**
   - Build obligation hierarchies
   - Identify conflicting norms
   - Generate defeasible rules

#### Example Implementation Snippet
```python
async def convert_legal_text_to_deontic(
    legal_text: Union[str, Dict[str, Any]],
    jurisdiction: str = 'us',
    document_type: str = 'statute',
    output_format: str = 'json',
    extract_obligations: bool = True,
    include_exceptions: bool = True
) -> Dict[str, Any]:
    """Convert legal text to deontic logic."""
    
    try:
        # Initialize legal NLP pipeline
        legal_nlp = initialize_legal_nlp(jurisdiction)
        
        # Process legal text
        if isinstance(legal_text, str):
            sections = [legal_text]
        elif isinstance(legal_text, dict):
            sections = extract_legal_sections(legal_text)
        else:
            raise ValueError("Invalid input type")
        
        results = []
        for section in sections:
            # Parse legal structure
            legal_doc = legal_nlp(section)
            
            # Extract normative components
            normative_elements = extract_normative_elements(
                legal_doc, document_type
            )
            
            # Generate deontic formulas
            for element in normative_elements:
                deontic_formula = generate_deontic_formula(element)
                
                results.append({
                    "original_text": element.text,
                    "deontic_formula": deontic_formula,
                    "obligation_type": element.norm_type,
                    # ... additional metadata
                })
        
        return {
            "status": "success",
            "deontic_formulas": results,
            "normative_structure": analyze_normative_structure(results)
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

## Testing Strategy

### Unit Tests
1. **Individual Component Tests**
   - Predicate extraction accuracy
   - Quantifier identification
   - Logical operator mapping
   - Confidence score validation

2. **Integration Tests**
   - End-to-end conversion pipeline
   - Multi-format output validation
   - Error handling and edge cases

3. **Domain-Specific Tests**
   - FOL: Mathematical statements, scientific descriptions
   - Deontic: Legal statutes, contracts, policies

### Test Data Sets
1. **FOL Test Cases**
   - Simple statements: "All birds can fly"
   - Complex statements: "If someone is a student and studies hard, then they will pass"
   - Mathematical statements: "For all real numbers x, if x > 0, then x² > 0"

2. **Deontic Test Cases**
   - Legal obligations: "Citizens must file tax returns annually"
   - Permissions: "Residents may park on designated streets"
   - Prohibitions: "Smoking is prohibited in public buildings"

### Validation Framework
```python
def validate_fol_conversion(original_text: str, fol_formula: str) -> Dict[str, Any]:
    """Validate FOL conversion accuracy."""
    return {
        "syntax_valid": check_fol_syntax(fol_formula),
        "semantic_preserving": check_semantic_preservation(original_text, fol_formula),
        "predicate_accuracy": validate_predicates(original_text, fol_formula),
        "quantifier_accuracy": validate_quantifiers(original_text, fol_formula)
    }

def validate_deontic_conversion(legal_text: str, deontic_formula: str) -> Dict[str, Any]:
    """Validate deontic logic conversion accuracy."""
    return {
        "normative_type_correct": check_normative_type(legal_text, deontic_formula),
        "subject_identified": validate_legal_subjects(legal_text, deontic_formula),
        "action_captured": validate_legal_actions(legal_text, deontic_formula),
        "temporal_constraints": validate_temporal_elements(legal_text, deontic_formula)
    }
```

## Integration Points

### MCP Server Registration
Both tools will be automatically registered with the MCP server through the existing pattern:

```python
# In __init__.py
from .text_to_fol import convert_text_to_fol
from .legal_text_to_deontic import convert_legal_text_to_deontic

__all__ = [
    # ... existing tools
    "convert_text_to_fol",
    "convert_legal_text_to_deontic"
]
```

### Dataset Processing Pipeline Integration
- Compatible with existing `process_dataset` workflows
- Can be chained with other dataset transformations
- Supports batch processing of large text corpora

### IPFS Integration
- Logic formulas can be stored on IPFS for decentralized access
- Supports versioning of logic knowledge bases
- Enables collaborative logic database construction

## Performance Considerations

### Scalability
- Batch processing for large datasets
- Streaming support for real-time conversion
- Parallel processing for independent text segments

### Optimization
- Caching of NLP models and parsers
- Incremental processing for updated documents
- Memory-efficient handling of large legal documents

### Quality Assurance
- Confidence scoring for conversion quality
- Human-in-the-loop validation workflows
- Automated regression testing

## Deployment Timeline

### Phase 1: Core Implementation (2-3 weeks)
- Basic FOL converter with essential features
- Simple deontic logic converter
- Unit tests and validation framework

### Phase 2: Advanced Features (2-3 weeks)
- Multi-format output support
- Confidence scoring and quality metrics
- Exception handling and edge cases

### Phase 3: Integration and Testing (1-2 weeks)
- MCP server integration
- Comprehensive test suite
- Documentation and examples

### Phase 4: Optimization and Production (1 week)
- Performance optimization
- Production deployment
- Monitoring and maintenance

## Risk Mitigation

### Technical Risks
- **NLP Model Accuracy**: Use multiple models and ensemble methods
- **Logic Complexity**: Start with simple cases, gradually increase complexity
- **Performance Issues**: Implement caching and optimization early

### Domain Risks
- **Legal Interpretation**: Collaborate with legal experts for validation
- **Logic Formalism**: Ensure compatibility with standard theorem provers
- **Ambiguity Handling**: Provide confidence scores and alternative interpretations

## Success Metrics

### Quantitative Metrics
- Conversion accuracy: >85% for simple statements, >70% for complex
- Processing speed: <1 second per sentence for most cases
- Coverage: Support for 95% of common logical constructs

### Qualitative Metrics
- User satisfaction with conversion quality
- Integration ease with existing workflows
- Contribution to downstream reasoning tasks

## Conclusion

This implementation plan provides a comprehensive roadmap for developing two specialized dataset tools that extend the IPFS datasets library with formal logic capabilities. The tools will enable users to convert natural language into machine-readable logical representations, opening new possibilities for automated reasoning, formal verification, and intelligent data processing.

The modular design ensures maintainability and extensibility, while the comprehensive testing strategy guarantees reliability and accuracy. Integration with the existing MCP server architecture provides seamless access to these advanced capabilities through the Model Context Protocol.
