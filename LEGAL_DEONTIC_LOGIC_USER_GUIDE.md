# Legal GraphRAG to Deontic Logic User Guide

## Overview

This system provides a complete pipeline for converting legal documents processed through GraphRAG into formal deontic logic representations, with translation support for multiple theorem provers.

## Quick Start

### 1. Basic Usage

```python
from ipfs_datasets_py.logic_integration import (
    DeonticLogicConverter, LegalDomainKnowledge, ConversionContext, LegalDomain
)

# Initialize components
knowledge = LegalDomainKnowledge()
converter = DeonticLogicConverter(knowledge)

# Create conversion context
context = ConversionContext(
    source_document_path="contract.pdf",
    legal_domain=LegalDomain.CONTRACT,
    confidence_threshold=0.6
)

# Convert GraphRAG knowledge graph to deontic logic
result = converter.convert_knowledge_graph_to_logic(knowledge_graph, context)

print(f"Extracted {len(result.deontic_formulas)} deontic formulas")
```

### 2. Multi-Theorem Prover Translation

```python
from ipfs_datasets_py.logic_integration import LeanTranslator, CoqTranslator, SMTTranslator

# Initialize translators
lean = LeanTranslator()
coq = CoqTranslator()
smt = SMTTranslator()

# Translate formulas
for formula in result.deontic_formulas:
    lean_result = lean.translate_deontic_formula(formula)
    coq_result = coq.translate_deontic_formula(formula)
    smt_result = smt.translate_deontic_formula(formula)
    
    print(f"Lean: {lean_result.translated_formula}")
    print(f"Coq: {coq_result.translated_formula}")
    print(f"SMT: {smt_result.translated_formula}")
```

### 3. IPLD Storage with Provenance

```python
from ipfs_datasets_py.logic_integration import LogicIPLDStorage, LogicProvenanceTracker

# Create storage with provenance tracking
storage = LogicIPLDStorage("./legal_logic_storage")
tracker = LogicProvenanceTracker(storage)

# Store formulas with complete provenance
for formula in result.deontic_formulas:
    formula_cid = tracker.track_formula_creation(
        formula=formula,
        source_pdf_path="contract.pdf",
        knowledge_graph_cid=knowledge_graph_cid
    )
    print(f"Stored formula with CID: {formula_cid}")

# Export provenance report
provenance_report = tracker.export_provenance_report("./provenance_report.json")
```

### 4. Querying Legal Rules

```python
from ipfs_datasets_py.logic_integration import DeonticQueryEngine

# Create query engine
query_engine = DeonticQueryEngine(result.rule_set)

# Query obligations for specific agent
obligations = query_engine.query_obligations(agent="contractor")
print(f"Contractor has {obligations.total_matches} obligations")

# Query permissions
permissions = query_engine.query_permissions(action="inspect")
print(f"Found {permissions.total_matches} inspection permissions")

# Check compliance
compliance = query_engine.check_compliance(
    proposed_action="subcontract work without approval",
    agent="contractor"
)
print(f"Compliance: {'OK' if compliance.is_compliant else 'VIOLATION'}")

# Natural language query
result = query_engine.query_by_natural_language(
    "What are the contractor's insurance obligations?"
)
print(f"Found {result.total_matches} relevant rules")
```

### 5. SymbolicAI Enhanced Analysis

```python
from ipfs_datasets_py.logic_integration import LegalSymbolicAnalyzer, LegalReasoningEngine

# Create enhanced analyzer (requires SymbolicAI installation)
analyzer = LegalSymbolicAnalyzer()
reasoning_engine = LegalReasoningEngine(analyzer)

# Analyze legal document
analysis = analyzer.analyze_legal_document(document_text)
print(f"Legal domain: {analysis.legal_domain}")
print(f"Primary parties: {analysis.primary_parties}")

# Extract deontic propositions
propositions = analyzer.extract_deontic_propositions(document_text)
print(f"Found {len(propositions)} deontic propositions")

# Check consistency
consistency = reasoning_engine.check_legal_consistency(rule_texts)
print(f"Rules are {'consistent' if consistency['is_consistent'] else 'inconsistent'}")
```

## Complete Demonstration

Run the complete demonstration to see all features:

```bash
# Show system architecture
python demonstrate_legal_deontic_logic.py --show-architecture

# Run complete pipeline demonstration
python demonstrate_legal_deontic_logic.py

# Process custom legal document
python demonstrate_legal_deontic_logic.py --document my_contract.pdf
```

## Example Output

The system converts legal text like:

> "The contractor shall complete all construction work by December 31, 2024, provided the contract remains valid."

Into formal deontic logic:

```
O[contractor](U((contract_valid ∧ December_31) → (complete_construction_work)))
```

Which translates to:

**Lean 4:**
```lean
Obligatory complete_construction_work 
  (agent := contractor) 
  (conditions := [contract_valid, December_31])
```

**Coq:**
```coq
(contract_valid /\ December_31) -> (Obligatory complete_construction_work)
```

**SMT-LIB:**
```smt
(=> (and contract_valid December_31) 
    (obligatory contractor complete_construction_work))
```

## Features

- ✅ **Complete deontic logic support**: Obligations (O), Permissions (P), Prohibitions (F), Rights (R)
- ✅ **Multi-theorem prover output**: Lean 4, Coq, SMT-LIB formats
- ✅ **IPLD storage with provenance**: Full traceability from source to logic
- ✅ **Natural language querying**: Ask questions in plain English
- ✅ **Compliance checking**: Verify actions against legal rules
- ✅ **Conflict detection**: Find logical inconsistencies
- ✅ **SymbolicAI integration**: Enhanced legal understanding (optional)
- ✅ **Agent-based analysis**: Track obligations per legal party
- ✅ **Temporal reasoning**: Handle deadlines and time constraints

## Installation

The system auto-installs dependencies, but for manual installation:

```bash
pip install beartype  # Core requirement
pip install symbolicai>=0.13.1  # Optional, for enhanced analysis
```

## Supported Legal Domains

- Contract Law
- Employment Law  
- Corporate Law
- Tort Law
- Constitutional Law
- Criminal Law

## Architecture

The system follows a modular architecture:

1. **Legal Domain Knowledge**: Pattern recognition for legal concepts
2. **Deontic Logic Core**: Formal logic primitives and validation
3. **Knowledge Graph Converter**: GraphRAG to logic conversion
4. **Multi-Theorem Prover Translators**: Output for verification systems
5. **IPLD Storage**: Content-addressed storage with provenance
6. **Query Engine**: Natural language and structured querying
7. **SymbolicAI Integration**: Enhanced reasoning capabilities

## Testing

Run comprehensive tests:

```bash
python test_legal_implementation.py
```

## Troubleshooting

**Issue**: Import errors
**Solution**: Ensure `beartype` is installed: `pip install beartype`

**Issue**: SymbolicAI features not working
**Solution**: Install SymbolicAI: `pip install symbolicai>=0.13.1`

**Issue**: No formulas extracted
**Solution**: Check confidence threshold in ConversionContext (try lower values like 0.3)

## API Reference

See the demonstration script `demonstrate_legal_deontic_logic.py` for complete examples of all features.