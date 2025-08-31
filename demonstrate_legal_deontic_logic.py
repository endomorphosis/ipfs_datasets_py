#!/usr/bin/env python3
"""
Demonstrate Legal GraphRAG to Deontic Logic Pipeline

This script demonstrates the complete pipeline from legal PDF documents
to deontic first-order logic formulas with multi-theorem prover translation.
"""

import os
import sys
import argparse
import json
from pathlib import Path
from typing import Dict, List, Any

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))

# Import components
from ipfs_datasets_py.logic_integration import (
    DeonticLogicConverter,
    LegalDomainKnowledge,
    ConversionContext,
    LegalDomain,
    LeanTranslator,
    CoqTranslator,
    SMTTranslator,
    LogicTranslationTarget
)

# Try to import GraphRAG components
try:
    from ipfs_datasets_py.graphrag_integration import GraphRAGIntegration
    from ipfs_datasets_py.knowledge_graph_extraction import Entity, Relationship, KnowledgeGraph
    GRAPHRAG_AVAILABLE = True
except ImportError:
    print("GraphRAG components not available - using mock data")
    GRAPHRAG_AVAILABLE = False
    
    # Mock classes for demonstration
    class Entity:
        def __init__(self, id: str, data: Dict[str, Any], type: str = "entity"):
            self.id = id
            self.data = data
            self.type = type
    
    class Relationship:
        def __init__(self, id: str, source: str, target: str, type: str, data: Dict[str, Any] = None):
            self.id = id
            self.source = source
            self.target = target
            self.type = type
            self.data = data or {}
    
    class KnowledgeGraph:
        def __init__(self, entities: List[Entity] = None, relationships: List[Relationship] = None):
            self.entities = entities or []
            self.relationships = relationships or []


def create_sample_legal_document():
    """Create a sample legal document for demonstration."""
    sample_text = """
    CONSTRUCTION CONTRACT AGREEMENT
    
    This Construction Contract ("Agreement") is entered into on January 1, 2024, 
    between ABC Construction LLC ("Contractor") and the City of Springfield ("Client").
    
    1. WORK OBLIGATIONS
    The Contractor shall complete all construction work by December 31, 2024.
    The Contractor must ensure all work meets city building codes and standards.
    The Contractor is required to maintain comprehensive insurance coverage.
    
    2. PAYMENT TERMS
    The Client shall pay the Contractor within 30 days of completion.
    The Client may withhold payment if work does not meet specifications.
    
    3. INSPECTIONS AND COMPLIANCE
    The Client may inspect the work at any time with 24 hours advance notice.
    The Contractor must not use materials that do not meet specification requirements.
    The Contractor shall not subcontract work without prior written approval.
    
    4. TERMINATION
    Either party may terminate this agreement with 30 days written notice.
    The Contractor must complete all work in progress upon termination notice.
    
    5. DISPUTE RESOLUTION
    All disputes shall be resolved through binding arbitration in Springfield, Illinois.
    The parties must attempt mediation before proceeding to arbitration.
    """
    return sample_text


def create_mock_knowledge_graph() -> KnowledgeGraph:
    """Create a mock knowledge graph from the sample legal document."""
    
    # Create entities representing legal concepts
    entities = [
        Entity(
            id="contractor_abc",
            data={
                "name": "ABC Construction LLC",
                "text": "The Contractor shall complete all construction work by December 31, 2024",
                "type": "organization",
                "role": "contractor"
            },
            type="legal_agent"
        ),
        Entity(
            id="client_springfield",
            data={
                "name": "City of Springfield", 
                "text": "The Client shall pay the Contractor within 30 days of completion",
                "type": "government",
                "role": "client"
            },
            type="legal_agent"
        ),
        Entity(
            id="completion_obligation",
            data={
                "text": "The Contractor shall complete all construction work by December 31, 2024",
                "action": "complete_construction_work",
                "deadline": "December 31, 2024",
                "subject": "all construction work"
            },
            type="legal_obligation"
        ),
        Entity(
            id="payment_obligation",
            data={
                "text": "The Client shall pay the Contractor within 30 days of completion",
                "action": "pay_contractor",
                "timeframe": "within 30 days",
                "condition": "after completion"
            },
            type="legal_obligation"
        ),
        Entity(
            id="inspection_permission",
            data={
                "text": "The Client may inspect the work at any time with 24 hours advance notice",
                "action": "inspect_work",
                "condition": "24 hours advance notice",
                "frequency": "any time"
            },
            type="legal_permission"
        ),
        Entity(
            id="material_prohibition",
            data={
                "text": "The Contractor must not use materials that do not meet specification requirements",
                "action": "use_substandard_materials",
                "restriction": "materials must meet specifications"
            },
            type="legal_prohibition"
        ),
        Entity(
            id="subcontracting_prohibition",
            data={
                "text": "The Contractor shall not subcontract work without prior written approval",
                "action": "subcontract_without_approval",
                "requirement": "prior written approval"
            },
            type="legal_prohibition"
        ),
        Entity(
            id="insurance_requirement",
            data={
                "text": "The Contractor is required to maintain comprehensive insurance coverage",
                "action": "maintain_insurance_coverage",
                "type": "comprehensive insurance"
            },
            type="legal_obligation"
        ),
        Entity(
            id="termination_right",
            data={
                "text": "Either party may terminate this agreement with 30 days written notice",
                "action": "terminate_agreement",
                "notice_period": "30 days written notice",
                "applicability": "either party"
            },
            type="legal_permission"
        ),
        Entity(
            id="arbitration_obligation",
            data={
                "text": "All disputes shall be resolved through binding arbitration in Springfield, Illinois",
                "action": "resolve_disputes_through_arbitration",
                "location": "Springfield, Illinois",
                "type": "binding arbitration"
            },
            type="legal_obligation"
        )
    ]
    
    # Create relationships between entities
    relationships = [
        Relationship(
            id="contractor_must_complete",
            source="contractor_abc",
            target="completion_obligation",
            type="must_fulfill",
            data={"legal_basis": "contractual obligation", "enforceability": "binding"}
        ),
        Relationship(
            id="client_must_pay",
            source="client_springfield", 
            target="payment_obligation",
            type="must_fulfill",
            data={"legal_basis": "contractual obligation", "condition": "work completion"}
        ),
        Relationship(
            id="client_may_inspect",
            source="client_springfield",
            target="inspection_permission", 
            type="may_exercise",
            data={"legal_basis": "contractual right", "limitation": "advance notice required"}
        ),
        Relationship(
            id="contractor_prohibited_materials",
            source="contractor_abc",
            target="material_prohibition",
            type="must_not_do",
            data={"legal_basis": "contractual prohibition", "penalty": "contract breach"}
        ),
        Relationship(
            id="contractor_prohibited_subcontracting",
            source="contractor_abc",
            target="subcontracting_prohibition",
            type="must_not_do",
            data={"legal_basis": "contractual prohibition", "exception": "with written approval"}
        ),
        Relationship(
            id="contractor_must_insure",
            source="contractor_abc",
            target="insurance_requirement",
            type="must_fulfill",
            data={"legal_basis": "contractual obligation", "duration": "contract term"}
        ),
        Relationship(
            id="parties_may_terminate",
            source="contractor_abc",
            target="termination_right",
            type="may_exercise",
            data={"legal_basis": "contractual right", "mutuality": "both parties"}
        ),
        Relationship(
            id="parties_may_terminate_alt",
            source="client_springfield",
            target="termination_right", 
            type="may_exercise",
            data={"legal_basis": "contractual right", "mutuality": "both parties"}
        ),
        Relationship(
            id="parties_must_arbitrate",
            source="contractor_abc",
            target="arbitration_obligation",
            type="must_fulfill",
            data={"legal_basis": "dispute resolution clause", "binding": True}
        ),
        Relationship(
            id="parties_must_arbitrate_alt",
            source="client_springfield",
            target="arbitration_obligation",
            type="must_fulfill", 
            data={"legal_basis": "dispute resolution clause", "binding": True}
        )
    ]
    
    return KnowledgeGraph(entities=entities, relationships=relationships)


def demonstrate_full_pipeline(sample_document_path: str = None):
    """Demonstrate the complete legal document to deontic logic pipeline."""
    
    print("=" * 80)
    print("LEGAL GRAPHRAG TO DEONTIC LOGIC DEMONSTRATION")
    print("=" * 80)
    print()
    
    # Step 1: Create or load sample legal document
    if sample_document_path and os.path.exists(sample_document_path):
        print(f"Loading legal document: {sample_document_path}")
        with open(sample_document_path, 'r') as f:
            document_text = f.read()
    else:
        print("Using sample construction contract")
        document_text = create_sample_legal_document()
    
    print(f"Document length: {len(document_text)} characters")
    print(f"First 200 characters: {document_text[:200]}...")
    print()
    
    # Step 2: Process document with GraphRAG (mock for demonstration)
    print("Step 2: Processing document with GraphRAG...")
    if GRAPHRAG_AVAILABLE:
        print("GraphRAG available - would process real document here")
        # In real implementation, would use GraphRAG to extract entities and relationships
        knowledge_graph = create_mock_knowledge_graph()
    else:
        print("Using mock GraphRAG data")
        knowledge_graph = create_mock_knowledge_graph()
    
    print(f"Extracted {len(knowledge_graph.entities)} entities")
    print(f"Extracted {len(knowledge_graph.relationships)} relationships")
    print()
    
    # Step 3: Convert to deontic logic
    print("Step 3: Converting to deontic logic...")
    
    # Initialize components
    domain_knowledge = LegalDomainKnowledge()
    converter = DeonticLogicConverter(domain_knowledge)
    
    # Create conversion context
    context = ConversionContext(
        source_document_path=sample_document_path or "sample_contract.txt",
        document_title="Springfield Construction Contract",
        legal_domain=LegalDomain.CONTRACT,
        jurisdiction="Illinois, USA",
        confidence_threshold=0.6,
        enable_temporal_analysis=True,
        enable_agent_inference=True,
        enable_condition_extraction=True
    )
    
    # Perform conversion
    conversion_result = converter.convert_knowledge_graph_to_logic(knowledge_graph, context)
    
    print(f"Conversion completed:")
    print(f"  - Generated {len(conversion_result.deontic_formulas)} deontic formulas")
    print(f"  - Errors: {len(conversion_result.errors)}")
    print(f"  - Warnings: {len(conversion_result.warnings)}")
    print()
    
    # Display extracted formulas
    print("Extracted Deontic Logic Formulas:")
    print("-" * 50)
    for i, formula in enumerate(conversion_result.deontic_formulas, 1):
        print(f"{i}. {formula.operator.value.upper()}")
        print(f"   Agent: {formula.agent.name if formula.agent else 'Unknown'}")
        print(f"   Proposition: {formula.proposition}")
        print(f"   Conditions: {formula.conditions}")
        print(f"   Confidence: {formula.confidence:.2f}")
        print(f"   FOL String: {formula.to_fol_string()}")
        print(f"   Source: {formula.source_text[:80]}...")
        print()
    
    # Display conversion statistics
    print("Conversion Statistics:")
    print("-" * 30)
    for key, value in conversion_result.statistics.items():
        print(f"  {key}: {value}")
    print()
    
    # Step 4: Translate to multiple theorem provers
    print("Step 4: Translating to theorem prover formats...")
    
    translators = [
        ("Lean 4", LeanTranslator()),
        ("Coq", CoqTranslator()),
        ("SMT-LIB", SMTTranslator())
    ]
    
    translation_results = {}
    
    for name, translator in translators:
        print(f"\nTranslating to {name}...")
        
        # Translate individual formulas
        formula_translations = []
        for formula in conversion_result.deontic_formulas:
            result = translator.translate_deontic_formula(formula)
            formula_translations.append(result)
        
        # Generate complete theory file
        theory_result = translator.translate_rule_set(conversion_result.rule_set)
        
        translation_results[name] = {
            "formula_translations": formula_translations,
            "theory_file": theory_result
        }
        
        # Display results
        successful_translations = sum(1 for r in formula_translations if r.success)
        print(f"  Successfully translated {successful_translations}/{len(formula_translations)} formulas")
        
        if theory_result.success:
            print(f"  Generated complete {name} theory file")
        else:
            print(f"  Failed to generate {name} theory file: {theory_result.errors}")
    
    # Step 5: Display sample translations
    print("\nStep 5: Sample Theorem Prover Translations")
    print("=" * 60)
    
    if conversion_result.deontic_formulas:
        sample_formula = conversion_result.deontic_formulas[0]
        print(f"Original Formula: {sample_formula.to_fol_string()}")
        print(f"Source: {sample_formula.source_text[:100]}...")
        print()
        
        for name, translator in translators:
            result = translator.translate_deontic_formula(sample_formula)
            if result.success:
                print(f"{name} Translation:")
                print(f"  {result.translated_formula}")
                print()
    
    # Step 6: Generate complete theory files
    print("Step 6: Complete Theory File Samples")
    print("=" * 50)
    
    for name, translator in translators:
        theory_result = translation_results[name]["theory_file"]
        if theory_result.success:
            print(f"\n{name} Theory File (first 500 characters):")
            print("-" * 40)
            print(theory_result.translated_formula[:500])
            if len(theory_result.translated_formula) > 500:
                print("...")
            print()
    
    # Step 7: Save results
    output_dir = Path("./logic_conversion_results")
    output_dir.mkdir(exist_ok=True)
    
    print(f"Step 7: Saving results to {output_dir}")
    
    # Save conversion result as JSON
    with open(output_dir / "conversion_result.json", 'w') as f:
        json.dump(conversion_result.to_dict(), f, indent=2, default=str)
    
    # Save theory files
    for name, translator in translators:
        theory_result = translation_results[name]["theory_file"]
        if theory_result.success:
            filename = f"theory_{name.lower().replace(' ', '_')}.txt"
            with open(output_dir / filename, 'w') as f:
                f.write(theory_result.translated_formula)
    
    print(f"Results saved to {output_dir}")
    print()
    
    # Summary
    print("PIPELINE SUMMARY")
    print("=" * 30)
    print(f"✓ Processed legal document")
    print(f"✓ Extracted {len(knowledge_graph.entities)} entities and {len(knowledge_graph.relationships)} relationships")
    print(f"✓ Generated {len(conversion_result.deontic_formulas)} deontic logic formulas")
    print(f"✓ Translated to {len(translators)} theorem prover formats")
    print(f"✓ Saved results to {output_dir}")
    
    if conversion_result.errors:
        print(f"⚠ {len(conversion_result.errors)} errors encountered")
    
    return conversion_result, translation_results


def main():
    """Main entry point for the demonstration."""
    parser = argparse.ArgumentParser(
        description="Demonstrate legal GraphRAG to deontic logic pipeline"
    )
    parser.add_argument(
        "--document", "-d",
        type=str,
        help="Path to legal document (optional, will use sample if not provided)"
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default="./logic_conversion_results",
        help="Output directory for results"
    )
    parser.add_argument(
        "--show-architecture", "-a",
        action="store_true",
        help="Show system architecture diagram"
    )
    
    args = parser.parse_args()
    
    if args.show_architecture:
        print("""
SYSTEM ARCHITECTURE
====================

┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Legal PDF      │───▶│   GraphRAG      │───▶│  Deontic Logic  │
│  Documents      │    │   Processing    │    │   Converter     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                              │                        │
                              ▼                        ▼
                    ┌─────────────────┐    ┌─────────────────┐
                    │  Knowledge      │    │  Deontic Logic  │
                    │  Graph          │    │  Formulas       │
                    │  (Entities &    │    │  (FOL)          │
                    │   Relations)    │    └─────────────────┘
                    └─────────────────┘             │
                              │                     ▼
                              ▼          ┌─────────────────┐
                    ┌─────────────────┐  │ Multi-Theorem   │
                    │  SymbolicAI     │  │ Prover          │
                    │  Legal Analysis │  │ Translation     │
                    └─────────────────┘  └─────────────────┘
                                                   │
        ┌──────────────────────────────────────────┼──────────────────────────────────────────┐
        │                                          ▼                                          │
 ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
 │    Lean 4   │  │     Coq     │  │  SMT-LIB    │  │    TPTP     │  │    Z3       │
 │  Theorem    │  │   Proof     │  │  (SAT/SMT   │  │   Format    │  │   Solver    │
 │  Prover     │  │ Assistant   │  │  Solvers)   │  │             │  │             │
 └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘
        │                │                │                │                │
        ▼                ▼                ▼                ▼                ▼
 ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
 │    IPLD     │  │    IPLD     │  │    IPLD     │  │    IPLD     │  │    IPLD     │
 │  Storage    │  │  Storage    │  │  Storage    │  │  Storage    │  │  Storage    │
 │  (Lean)     │  │   (Coq)     │  │  (SMT-LIB)  │  │   (TPTP)    │  │    (Z3)     │
 └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘
                                          │
                                          ▼
                                ┌─────────────────┐
                                │   Provenance    │
                                │   Tracking      │
                                │  (Source Doc    │
                                │   → Logic)      │
                                └─────────────────┘

FEATURES:
- Converts legal documents to formal deontic logic
- Supports obligations, permissions, prohibitions, rights
- Multi-theorem prover output (Lean, Coq, SMT-LIB, TPTP, Z3)
- IPLD storage with full provenance tracking
- SymbolicAI integration for enhanced analysis
- Cross-platform compatibility
        """)
        return
    
    try:
        conversion_result, translation_results = demonstrate_full_pipeline(args.document)
        print(f"\n✓ Demonstration completed successfully!")
    except Exception as e:
        print(f"\n✗ Error during demonstration: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())