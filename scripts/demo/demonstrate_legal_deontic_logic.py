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
        def __init__(self, entity_id: str = None, entity_type: str = "entity", name: str = "", 
                     properties: Dict[str, Any] = None, confidence: float = 1.0, source_text: str = None):
            self.entity_id = entity_id
            self.entity_type = entity_type
            self.name = name
            self.properties = properties or {}
            self.confidence = confidence
            self.source_text = source_text
    
    class Relationship:
        def __init__(self, relationship_id: str = None, source: str = "", target: str = "", 
                     relationship_type: str = "relationship", properties: Dict[str, Any] = None, 
                     confidence: float = 1.0, source_text: str = None):
            self.relationship_id = relationship_id
            self.source = source
            self.target = target
            self.relationship_type = relationship_type
            self.properties = properties or {}
            self.confidence = confidence
            self.source_text = source_text
    
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
            entity_id="contractor_abc",
            entity_type="legal_agent",
            name="ABC Construction LLC",
            properties={
                "text": "The Contractor shall complete all construction work by December 31, 2024",
                "role": "contractor"
            },
            source_text="The Contractor shall complete all construction work by December 31, 2024"
        ),
        Entity(
            entity_id="client_springfield",
            entity_type="legal_agent",
            name="City of Springfield",
            properties={
                "text": "The Client shall pay the Contractor within 30 days of completion",
                "role": "client"
            },
            source_text="The Client shall pay the Contractor within 30 days of completion"
        ),
        Entity(
            entity_id="completion_obligation",
            entity_type="legal_obligation",
            name="Construction Completion Obligation",
            properties={
                "text": "The Contractor shall complete all construction work by December 31, 2024",
                "action": "complete_construction_work",
                "deadline": "December 31, 2024",
                "subject": "all construction work"
            },
            source_text="The Contractor shall complete all construction work by December 31, 2024"
        ),
        Entity(
            entity_id="payment_obligation",
            entity_type="legal_obligation",
            name="Payment Obligation",
            properties={
                "text": "The Client shall pay the Contractor within 30 days of completion",
                "action": "pay_contractor",
                "timeframe": "within 30 days",
                "condition": "after completion"
            },
            source_text="The Client shall pay the Contractor within 30 days of completion"
        ),
        Entity(
            entity_id="inspection_permission",
            entity_type="legal_permission",
            name="Inspection Permission",
            properties={
                "text": "The Client may inspect the work at any time with 24 hours advance notice",
                "action": "inspect_work",
                "condition": "24 hours advance notice",
                "frequency": "any time"
            },
            source_text="The Client may inspect the work at any time with 24 hours advance notice"
        ),
        Entity(
            entity_id="material_prohibition",
            entity_type="legal_prohibition",
            name="Substandard Materials Prohibition",
            properties={
                "text": "The Contractor must not use materials that do not meet specification requirements",
                "action": "use_substandard_materials",
                "restriction": "materials must meet specifications"
            },
            source_text="The Contractor must not use materials that do not meet specification requirements"
        ),
        Entity(
            entity_id="subcontracting_prohibition",
            entity_type="legal_prohibition", 
            name="Unauthorized Subcontracting Prohibition",
            properties={
                "text": "The Contractor shall not subcontract work without prior written approval",
                "action": "subcontract_without_approval",
                "requirement": "prior written approval"
            },
            source_text="The Contractor shall not subcontract work without prior written approval"
        ),
        Entity(
            entity_id="insurance_requirement",
            entity_type="legal_obligation",
            name="Insurance Requirement",
            properties={
                "text": "The Contractor is required to maintain comprehensive insurance coverage",
                "action": "maintain_insurance_coverage",
                "type": "comprehensive insurance"
            },
            source_text="The Contractor is required to maintain comprehensive insurance coverage"
        ),
        Entity(
            entity_id="termination_right",
            entity_type="legal_permission",
            name="Termination Right",
            properties={
                "text": "Either party may terminate this agreement with 30 days written notice",
                "action": "terminate_agreement",
                "notice_period": "30 days written notice",
                "applicability": "either party"
            },
            source_text="Either party may terminate this agreement with 30 days written notice"
        ),
        Entity(
            entity_id="arbitration_obligation",
            entity_type="legal_obligation",
            name="Arbitration Obligation",
            properties={
                "text": "All disputes shall be resolved through binding arbitration in Springfield, Illinois",
                "action": "resolve_disputes_through_arbitration",
                "location": "Springfield, Illinois",
                "type": "binding arbitration"
            },
            source_text="All disputes shall be resolved through binding arbitration in Springfield, Illinois"
        )
    ]
    
    # Create relationships between entities
    entity_map = {entity.entity_id: entity for entity in entities}
    
    relationships = [
        Relationship(
            relationship_id="contractor_must_complete",
            relationship_type="must_fulfill",
            source_entity=entity_map["contractor_abc"],
            target_entity=entity_map["completion_obligation"],
            properties={"legal_basis": "contractual obligation", "enforceability": "binding"},
            source_text="The Contractor shall complete all construction work by December 31, 2024"
        ),
        Relationship(
            relationship_id="client_must_pay",
            relationship_type="must_fulfill",
            source_entity=entity_map["client_springfield"],
            target_entity=entity_map["payment_obligation"],
            properties={"legal_basis": "contractual obligation", "condition": "work completion"},
            source_text="The Client shall pay the Contractor within 30 days of completion"
        ),
        Relationship(
            relationship_id="client_may_inspect",
            relationship_type="may_exercise",
            source_entity=entity_map["client_springfield"],
            target_entity=entity_map["inspection_permission"],
            properties={"legal_basis": "contractual right", "limitation": "advance notice required"},
            source_text="The Client may inspect the work at any time with 24 hours advance notice"
        ),
        Relationship(
            relationship_id="contractor_prohibited_materials",
            relationship_type="must_not_do",
            source_entity=entity_map["contractor_abc"],
            target_entity=entity_map["material_prohibition"],
            properties={"legal_basis": "contractual prohibition", "penalty": "contract breach"},
            source_text="The Contractor must not use materials that do not meet specification requirements"
        ),
        Relationship(
            relationship_id="contractor_prohibited_subcontracting",
            relationship_type="must_not_do",
            source_entity=entity_map["contractor_abc"],
            target_entity=entity_map["subcontracting_prohibition"],
            properties={"legal_basis": "contractual prohibition", "exception": "with written approval"},
            source_text="The Contractor shall not subcontract work without prior written approval"
        ),
        Relationship(
            relationship_id="contractor_must_insure",
            relationship_type="must_fulfill",
            source_entity=entity_map["contractor_abc"],
            target_entity=entity_map["insurance_requirement"],
            properties={"legal_basis": "contractual obligation", "duration": "contract term"},
            source_text="The Contractor is required to maintain comprehensive insurance coverage"
        ),
        Relationship(
            relationship_id="parties_may_terminate",
            relationship_type="may_exercise", 
            source_entity=entity_map["contractor_abc"],
            target_entity=entity_map["termination_right"],
            properties={"legal_basis": "contractual right", "mutuality": "both parties"},
            source_text="Either party may terminate this agreement with 30 days written notice"
        ),
        Relationship(
            relationship_id="parties_may_terminate_alt",
            relationship_type="may_exercise",
            source_entity=entity_map["client_springfield"],
            target_entity=entity_map["termination_right"],
            properties={"legal_basis": "contractual right", "mutuality": "both parties"},
            source_text="Either party may terminate this agreement with 30 days written notice"
        ),
        Relationship(
            relationship_id="parties_must_arbitrate",
            relationship_type="must_fulfill",
            source_entity=entity_map["contractor_abc"],
            target_entity=entity_map["arbitration_obligation"],
            properties={"legal_basis": "dispute resolution clause", "binding": True},
            source_text="All disputes shall be resolved through binding arbitration in Springfield, Illinois"
        ),
        Relationship(
            relationship_id="parties_must_arbitrate_alt",
            relationship_type="must_fulfill",
            source_entity=entity_map["client_springfield"],
            target_entity=entity_map["arbitration_obligation"],
            properties={"legal_basis": "dispute resolution clause", "binding": True},
            source_text="All disputes shall be resolved through binding arbitration in Springfield, Illinois"
        )
    ]
    # Create knowledge graph and add entities
    knowledge_graph = KnowledgeGraph(name="Springfield Construction Contract")
    
    # Add entities to the knowledge graph
    for entity in entities:
        knowledge_graph.entities[entity.entity_id] = entity
        knowledge_graph.entity_types[entity.entity_type].add(entity.entity_id)
        knowledge_graph.entity_names[entity.name].add(entity.entity_id)
    
    # Add relationships to the knowledge graph
    for relationship in relationships:
        knowledge_graph.relationships[relationship.relationship_id] = relationship
        knowledge_graph.relationship_types[relationship.relationship_type].add(relationship.relationship_id)
        if relationship.source_entity:
            knowledge_graph.entity_relationships[relationship.source_entity.entity_id].add(relationship.relationship_id)
        if relationship.target_entity:
            knowledge_graph.entity_relationships[relationship.target_entity.entity_id].add(relationship.relationship_id)
    
    return knowledge_graph


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
    
    # Prepare output directory for all results
    output_dir = Path("./logic_conversion_results")
    output_dir.mkdir(exist_ok=True)
    
    # Step 7: Demonstrate IPLD storage with provenance
    print("Step 7: Demonstrating IPLD logic storage with provenance...")
    
    from ipfs_datasets_py.logic_integration import LogicIPLDStorage, LogicProvenanceTracker
    
    # Create IPLD storage
    logic_storage = LogicIPLDStorage("./logic_conversion_results/ipld_storage")
    provenance_tracker = LogicProvenanceTracker(logic_storage)
    
    # Store formulas with provenance
    formula_cids = []
    for formula in conversion_result.deontic_formulas:
        formula_cid = provenance_tracker.track_formula_creation(
            formula=formula,
            source_pdf_path=context.source_document_path,
            knowledge_graph_cid="mock_kg_cid",
            entity_cids=[f"entity_{i}" for i in range(3)]  # Mock entity CIDs
        )
        formula_cids.append(formula_cid)
    
    # Store translations
    for name, translator in translators:
        target = LogicTranslationTarget.LEAN if "Lean" in name else (
            LogicTranslationTarget.COQ if "Coq" in name else LogicTranslationTarget.SMT_LIB
        )
        for i, formula in enumerate(conversion_result.deontic_formulas):
            if i < len(formula_cids):
                translation_result = translation_results[name]["formula_translations"][i]
                if translation_result.success:
                    logic_storage.store_translation_result(
                        formula_cids[i], target, translation_result
                    )
    
    # Create collection
    collection_cid = logic_storage.store_logic_collection(
        formulas=conversion_result.deontic_formulas,
        collection_name="Springfield Construction Contract",
        source_doc_cid="mock_doc_cid"
    )
    
    # Generate provenance report
    provenance_report = provenance_tracker.export_provenance_report(
        output_dir / "provenance_report.json"
    )
    
    print(f"✓ Stored {len(formula_cids)} formulas in IPLD with provenance")
    print(f"✓ Collection CID: {collection_cid}")
    print(f"✓ Storage statistics: {logic_storage.get_storage_statistics()}")
    print()
    
    # Step 8: Demonstrate query capabilities
    print("Step 8: Demonstrating deontic logic query capabilities...")
    
    from ipfs_datasets_py.logic_integration import DeonticQueryEngine, QueryType
    
    # Create query engine
    query_engine = DeonticQueryEngine(conversion_result.rule_set)
    
    # Query obligations
    obligations = query_engine.query_obligations()
    print(f"✓ Found {obligations.total_matches} total obligations")
    
    # Query obligations for specific agent
    contractor_obligations = query_engine.query_obligations(agent="contractor")
    print(f"✓ Found {contractor_obligations.total_matches} obligations for contractor")
    
    # Query permissions
    permissions = query_engine.query_permissions()
    print(f"✓ Found {permissions.total_matches} total permissions")
    
    # Query prohibitions
    prohibitions = query_engine.query_prohibitions()
    print(f"✓ Found {prohibitions.total_matches} total prohibitions")
    
    # Test compliance checking
    compliance_result = query_engine.check_compliance(
        proposed_action="subcontract construction work without approval",
        agent="contractor"
    )
    print(f"✓ Compliance check: {'COMPLIANT' if compliance_result.is_compliant else 'NON-COMPLIANT'} "
          f"(score: {compliance_result.compliance_score:.2f})")
    
    # Test natural language query
    nl_query_result = query_engine.query_by_natural_language(
        "What must the contractor do regarding insurance?"
    )
    print(f"✓ Natural language query found {nl_query_result.total_matches} relevant rules")
    
    # Find conflicts
    conflicts = query_engine.find_conflicts()
    print(f"✓ Detected {len(conflicts)} potential logical conflicts")
    
    print()
    
    # Step 9: Save results (renamed from Step 8)
    
    print(f"Step 9: Saving results to {output_dir}")
    
    # Save conversion result as JSON (output_dir already defined above)
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