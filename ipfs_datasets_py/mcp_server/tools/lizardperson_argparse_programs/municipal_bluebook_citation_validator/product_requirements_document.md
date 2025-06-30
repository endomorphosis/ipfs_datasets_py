# Bluebook Citation Validator - Product Requirements Document (PRD)

## 1. Executive Summary

### Problem Statement
Legal professionals need to validate 1.5M municipal law Bluebook citations against their source HTML documents. Citations must be accurate for attorney review, requiring comprehensive validation of format, content accuracy, and internal consistency.

### Solution Overview
Build an argparse-based batch processor that validates municipal law Bluebook citations through format checking, metadata cross-referencing, and consistency analysis, producing pass/fail results with detailed error reports and correction suggestions.

## 2. Product Vision & Goals

### Primary Goal
Validate Bluebook citations for municipal law to ensure they are correctly formatted and accurately represent their source documents.

### Success Metrics
- **Minimum Quality**: 95% correct validations
- **Target Quality**: As high as achievable through systematic validation
- **Coverage**: Process all 1.5M HTML documents with ~3-4.5M citations
- **Accuracy Priority**: Correctness over speed

## 3. Functional Requirements

### 3.1 Core Validation Types

#### Format Validation
- Verify municipal law Bluebook citation format: `Place, State, Code Type, §Section (Year)`
- Validate component structure and ordering
- Check abbreviations (e.g., "Ark." for Arkansas)
- Verify punctuation and spacing

#### Content Validation  
- Cross-reference citation components against source metadata
- Validate dates match between `date` field and `bluebook_citation` 
- Confirm section numbers match `title_num` field
- Verify place names and state codes are consistent
- Check that `bluebook_state_code` matches `state_code`

#### Consistency Validation
- Ensure multiple citations of same document use consistent formatting
- Flag conflicting information across related citations
- Identify potential duplicates with different citation strings

### 3.2 Input/Output Specifications

#### Input Data
- **Data Sources**: Parquet files and/or MySQL database
- **Required Fields**: `bluebook_citation`, `place_name`, `state_code`, `bluebook_state_code`, `date`, `title_num`, `cid`
- **Processing**: Batch mode via command-line interface

#### Output Requirements
- **Pass/Fail**: Binary validation result per citation
- **Error Reports**: Specific validation failures with descriptions
- **Suggested Corrections**: Fixes for known error patterns
- **Summary Report**: Overall statistics and error categories

### 3.3 Validation Rules

#### Municipal Law Citation Format
```
Expected: Place, State Abbrev., Code Type, §Section (Year)
Example: "Garland, Ark., County Code, §14-75 (2007)"
```

#### Component Validation
- **Place**: Must match `place_name` field
- **State**: Must use proper Bluebook abbreviation matching `bluebook_state_code`
- **Section**: Must match `title_num` field format
- **Year**: Must match year extracted from `date` field
- **Punctuation**: Commas, periods, and spacing per Bluebook format

## 4. Technical Requirements

### 4.1 Command-Line Interface
```bash
python validate_citations_against_html_and_references.py --input data.parquet --output results.json
python validate_citations_against_html_and_references.py --database mysql://connection --table citations
```

### 4.2 Core Processing
- Read citation data from Parquet or MySQL
- Apply validation rules to each citation
- Generate error reports with specific failure reasons
- Export results in structured format (JSON/CSV)

### 4.3 Error Categories
- **Format Errors**: Incorrect punctuation, spacing, abbreviations
- **Content Errors**: Mismatched dates, sections, places, states  
- **Consistency Errors**: Conflicting citations for same document
- **Missing Data**: Required fields empty or malformed

## 5. Minimum Viable Product (MVP)

### Core Components
1. **Citation Parser**: Extract components from `bluebook_citation` string
2. **Format Validator**: Check municipal law Bluebook format compliance
3. **Metadata Validator**: Cross-reference citation against source fields
4. **Error Reporter**: Generate detailed validation reports
5. **CLI Interface**: Argparse-based batch processing

### MVP Success Criteria
- Validates municipal law citation format correctly
- Identifies mismatches between citation and metadata
- Achieves 95% validation accuracy on test data
- Produces actionable error reports
- Processes sample dataset successfully

### Example Validation Logic
```python
def validate_citation(row):
    citation = row['bluebook_citation']
    
    # Parse: "Garland, Ark., County Code, §14-75 (2007)"
    parsed = parse_municipal_citation(citation)
    
    errors = []
    
    # Format validation
    if not follows_municipal_format(parsed):
        errors.append("Invalid municipal citation format")
    
    # Content validation  
    if parsed.place != row['place_name']:
        errors.append(f"Place mismatch: {parsed.place} vs {row['place_name']}")
    
    if parsed.year != extract_year(row['date']):
        errors.append(f"Year mismatch: {parsed.year} vs {extract_year(row['date'])}")
        
    return len(errors) == 0, errors
```

## 6. Constraints & Assumptions

### Technical Constraints
- Batch processing only (no real-time requirements)
- Municipal law citations only
- Existing data format (Parquet/MySQL)

### Business Constraints  
- Accuracy is more important than processing speed
- Must handle edge cases in citation formats
- Output suitable for legal professional review

### Assumptions
- Data structure remains consistent
- Municipal citations follow standard Bluebook format
- Source metadata is generally reliable

## 7. Success Metrics

### Validation Accuracy
- True positive rate (correctly identifying valid citations)
- True negative rate (correctly identifying invalid citations)  
- Error detection coverage (finding actual formatting/content errors)

### Processing Metrics
- Citations processed per hour
- Error categorization accuracy
- Suggested correction usefulness