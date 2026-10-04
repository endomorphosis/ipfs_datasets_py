# Bluebook Citation Validator - Success Criteria & Mathematical Definitions (Part 1/3)

## 1. Rigorous Term Definitions

### 1.1 Validation Types and Correctness

#### Format Validation
**Definition**: The process of verifying that a citation string conforms to the structural pattern and syntactic rules of municipal law Bluebook citations.

**Formal Definition**: Given a citation string $c$, format validation $F(c)$ returns `True` if and only if:
1. $c$ matches the regex pattern: `^[^,]+,\s+[A-Z][a-z]+\.,\s+[^,]+,\s+§[\d-]+\s+\(\d{4}\)$`
2. State abbreviation component exists in approved Bluebook state abbreviation set $S_{bluebook}$
3. Punctuation follows exact Bluebook municipal format: comma-space after place, period after state abbreviation, comma-space after code type, space before and after section symbol, parentheses around year

#### Correct Format Validation  
**Definition**: A format validation result that accurately determines whether a citation follows proper municipal Bluebook format.

**Formal Definition**: Format validation $F(c)$ is correct if:
- $F(c) = True$ when citation $c$ objectively follows municipal Bluebook format rules
- $F(c) = False$ when citation $c$ objectively violates any municipal Bluebook format rule

**Ground Truth**: Determined by manual expert review against The Bluebook: A Uniform System of Citation, Rule 12.9 (Local Ordinances).

#### Correct Content Validation
**Definition**: A content validation result that accurately determines whether citation components match their corresponding metadata fields.

**Formal Definition**: Content validation $C(c, m)$ for citation $c$ and metadata $m$ is correct if:
- Place comparison: $extract\_place(c) = m.place\_name$ iff validator reports place match
- State comparison: $extract\_state(c) = m.bluebook\_state\_code$ iff validator reports state match  
- Section comparison: $extract\_section(c) = m.title\_num$ iff validator reports section match
- Year comparison: $extract\_year(c) = extract\_year(m.date)$ iff validator reports year match

**Ground Truth**: Determined by string equality after normalization (whitespace trimming, case standardization).

#### Consistent Validation
**Definition**: A consistency validation result that accurately determines whether multiple citations of the same source document use identical formatting and content.

**Formal Definition**: Consistency validation $K(C_g)$ for citation group $C_g = \{c_1, c_2, ..., c_n\}$ sharing the same source document is correct if:
- Reports consistent when $\forall i,j \in [1,n]: normalize(c_i) = normalize(c_j)$
- Reports inconsistent when $\exists i,j \in [1,n]: normalize(c_i) \neq normalize(c_j)$

**Where**: $normalize(c)$ applies standard formatting rules (spacing, capitalization, abbreviations) to citation $c$.

#### Error Definition
**Classification of Errors**:

**All Errors**: Any validation failure including:
- **Format Errors**: Citation fails structural/syntactic validation
- **Content Errors**: Citation components don't match metadata  
- **Consistency Errors**: Multiple citations of same document differ
- **Data Errors**: Missing or malformed required fields
- **Processing Errors**: System failures during validation

**Fatal Errors**: Errors that prevent citation from being legally usable:
- **Incorrect Legal Reference**: Wrong section, year, or jurisdiction
- **Invalid Format**: Completely unparseable citation string
- **Missing Critical Components**: No section number, year, or jurisdiction
- **Legal Compliance Violations**: Citations that would be rejected in legal proceedings

**Formal Definition**: Error $e$ is fatal if $e \in E_{fatal}$ where:
$$E_{fatal} = \{e : legal\_usability(citation\_with\_error(e)) = False\}$$

#### Correctly Classified
**Definition**: An error categorization that accurately identifies the true type and severity of a validation failure.

**Formal Definition**: Error classification $classify(e)$ is correct if:
$$classify(e) = ground\_truth\_category(e)$$

**Categories**: 
- $E_{format}$: Format violations (structure, punctuation, abbreviations)
- $E_{content}$: Content mismatches (place, state, section, year discrepancies)  
- $E_{consistency}$: Consistency violations (different formatting for same document)
- $E_{data}$: Data quality issues (missing fields, malformed input)

**Ground Truth**: Established through expert legal review and predefined rule mapping.

#### Successfully Processed
**Definition**: A citation that completed the entire validation pipeline and produced a definitive pass/fail result with error details.

**Formal Definition**: Citation $c$ is successfully processed if:
1. **Parsing Success**: $parse(c) \neq NULL$ (citation components extracted)
2. **Validation Completion**: All validation functions $\{F, C, K\}$ executed without exceptions
3. **Result Generation**: Validation result $R$ contains:
   - Binary pass/fail status
   - Complete error list (possibly empty)
   - Suggested corrections (where applicable)
4. **No System Failures**: No exceptions, timeouts, or crashes during processing

**Exclusions**: Citations marked as successfully processed do NOT include:
- System crashes during processing
- Incomplete validation due to missing dependencies
- Timeout failures on individual citations
- Invalid input data that cannot be parsed

#### Implemented Validation Rules
**Definition**: The complete set of algorithmic checks actually coded and executable in the validator system.

**Formal Definition**: $V_{implemented} = \{r_1, r_2, ..., r_n\}$ where each rule $r_i$ is:
- **Executable**: Can be invoked with citation and metadata inputs
- **Deterministic**: Same inputs always produce same validation result
- **Documented**: Has clear specification of what it validates
- **Testable**: Can be verified against known good/bad examples

**Examples**:
- `validate_municipal_format()`: Checks structural pattern compliance
- `validate_state_abbreviation()`: Verifies Bluebook state abbreviation
- `validate_section_format()`: Checks section number formatting
- `cross_reference_metadata()`: Compares citation vs. source data

#### Required Municipal Law Bluebook Format Rules
**Definition**: The complete set of formatting requirements from The Bluebook for municipal ordinances and codes.

**Formal Definition**: $V_{required} = \{rule_{bluebook\_i}\}$ derived from Bluebook Rule 12.9, including:

1. **Structure Rule**: `Place, State Abbrev., Code Type, §Section (Year)`
2. **Punctuation Rules**: 
   - Comma + space after place name
   - Period after state abbreviation  
   - Comma + space after code type
   - Section symbol (§) before section number
   - Parentheses around year with no internal spaces
3. **Abbreviation Rules**: State abbreviations per Bluebook Table T1
4. **Spacing Rules**: Single spaces between components, no trailing spaces
5. **Capitalization Rules**: Proper nouns capitalized, articles lowercase
6. **Section Formatting**: Numbers and hyphens only, no alphabetic suffixes

**Authority**: The Bluebook: A Uniform System of Citation (21st ed. 2020), Rule 12.9.

#### Detailed Descriptions
**Definition**: Error explanations that provide specific, actionable information about validation failures.

**Required Components**:
1. **Error Type**: Category classification (format/content/consistency)
2. **Specific Issue**: Exact nature of the problem
3. **Location**: Which component(s) of citation are affected
4. **Expected vs. Actual**: What was found vs. what should be present
5. **Context**: Relevant metadata for cross-reference errors

**Formal Definition**: Description $d$ is detailed if:
$$|components(d)| \geq 4 \land specificity(d) \geq threshold_{detail}$$

**Example Detailed Description**:
> "Format Error: Missing comma after place name. Expected 'Garland, Ark.' but found 'Garland Ark.' at position 7-8. Municipal citations require comma-space separation between place and state."

#### Correct Suggestions
**Definition**: Proposed corrections that, when applied, would resolve the identified validation error.

**Formal Definition**: Suggestion $s$ for error $e$ is correct if:
$$validate(apply\_suggestion(citation, s)) = Pass \land error\_resolved(e, s) = True$$

**Requirements for Correctness**:
1. **Targeted**: Addresses the specific error identified
2. **Minimal**: Changes only what's necessary to fix the error
3. **Valid**: Results in a properly formatted citation
4. **Preserves Intent**: Maintains the legal meaning of the original citation

**Example**: For missing comma error, suggest inserting ", " at specific position rather than rewriting entire citation.

#### Proper Municipal Format
**Definition**: A citation string that fully complies with Bluebook Rule 12.9 for municipal ordinances and local codes.

**Formal Definition**: Citation $c$ has proper municipal format if:
$$\forall r \in V_{required}: r(c) = Pass$$

**Template**: `[Place Name], [State Abbrev.], [Code Type], §[Section] ([Year])`

**Valid Example**: `"Garland, Ark., County Code, §14-75 (2007)"`

**Component Requirements**:
- **Place Name**: Full legal name of municipality/county
- **State Abbreviation**: Bluebook Table T1 standard abbreviation  
- **Code Type**: Legal designation (County Code, Municipal Code, etc.)
- **Section**: Numeric identifier with appropriate separators
- **Year**: Four-digit year of enactment or amendment

**Validation Check**: $proper\_municipal\_format(c) = \bigwedge_{r \in V_{required}} r(c)$