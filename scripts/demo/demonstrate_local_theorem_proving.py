#!/usr/bin/env python3
"""
Local End-to-End Theorem Proving Demonstration

This script demonstrates the complete pipeline without requiring network access,
using simulated website content to show the full capability from text extraction
through GraphRAG processing to actual theorem proving.
"""

import os
import sys
import argparse
import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))


def create_sample_legal_website_content():
    """Create sample legal website content for demonstration."""
    return {
        "url": "https://example-law.edu/corporate-governance",
        "title": "Corporate Governance Legal Requirements",
        "text": """
Corporate Governance Legal Requirements

Overview
Corporate governance involves the mechanisms, relations, and processes by which corporations are directed and controlled. The governance structure specifies the distribution of rights and responsibilities among the different participants in the corporation and spells out the rules and procedures for decision-making on corporate affairs.

Board of Directors Obligations
The board of directors shall exercise oversight of the corporation's operations and strategic direction. Directors must act in good faith and in the best interests of the corporation and its shareholders. Each director has a fiduciary duty to exercise reasonable care in decision-making processes.

The board shall establish an audit committee comprised of independent directors. The audit committee must review and approve all material transactions between the corporation and related parties. Directors are prohibited from engaging in transactions that create conflicts of interest without proper disclosure and approval.

Executive Compensation Requirements  
The compensation committee shall determine executive compensation based on performance metrics aligned with shareholder value creation. Executive compensation packages must be disclosed in annual proxy statements. The corporation must maintain clawback provisions that allow recovery of compensation based on financial restatements.

Shareholder Rights
Shareholders have the right to vote on fundamental corporate matters including mergers, acquisitions, and major asset sales. Shareholders may inspect corporate books and records upon proper demand. The corporation shall provide shareholders with annual reports and quarterly financial statements.

Shareholders are entitled to elect directors through majority vote or cumulative voting procedures as specified in corporate bylaws. Any shareholder holding more than 5% of outstanding shares must disclose their ownership position.

Regulatory Compliance Obligations
The corporation must comply with all applicable securities laws and regulations. Financial statements must be prepared in accordance with generally accepted accounting principles (GAAP). The corporation shall maintain internal controls over financial reporting as required by the Sarbanes-Oxley Act.

Management must certify the accuracy of financial statements and internal controls annually. The corporation is required to establish a whistleblower program that protects employees who report violations of law or corporate policy.

Disclosure Requirements
The corporation must promptly disclose all material information that could affect the stock price. Insider trading is strictly prohibited, and the corporation must maintain policies preventing such activities. All material agreements and transactions must be disclosed in regulatory filings.

The corporation shall provide equal access to information for all shareholders and shall not engage in selective disclosure practices. Quarterly earnings calls and annual shareholder meetings must be open to all investors.

Enforcement and Penalties
Violation of corporate governance requirements may result in regulatory sanctions, including fines, cease and desist orders, and individual liability for directors and officers. The Securities and Exchange Commission has authority to investigate and prosecute violations of federal securities laws.

Shareholders may bring derivative lawsuits against directors and officers for breaches of fiduciary duty. Class action lawsuits may be filed for securities fraud or other violations of shareholder rights.
""",
        "metadata": {
            "method": "simulated",
            "content_length": 2847,
            "extraction_time": 0.001
        }
    }


def main():
    """Main entry point for local demonstration."""
    parser = argparse.ArgumentParser(
        description="Local end-to-end theorem proving demonstration"
    )
    parser.add_argument(
        "--prover", "-p",
        type=str,
        choices=["z3", "cvc5", "lean", "coq", "all"],
        default="z3",
        help="Theorem prover to use (default: z3)"
    )
    parser.add_argument(
        "--install-provers", "-i",
        action="store_true",
        help="Install theorem provers before running"
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default="./local_proof_results",
        help="Output directory for results"
    )
    parser.add_argument(
        "--timeout", "-t",
        type=int,
        default=60,
        help="Timeout for proof execution in seconds (default: 60)"
    )
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("LOCAL END-TO-END THEOREM PROVING DEMONSTRATION")
    print("=" * 80)
    print()
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)
    
    # Step 1: Install theorem provers if requested
    if args.install_provers:
        print("Step 1: Installing theorem provers...")
        
        try:
            from ipfs_datasets_py.auto_installer import get_installer
            installer = get_installer()
            
            # Install basic dependencies first
            installer.install_python_dependency('beartype')
            
            # Install theorem provers
            prover_results = installer.install_theorem_provers()
            
            print("Installation results:")
            for prover, success in prover_results.items():
                status = "✓" if success else "✗"
                print(f"  {status} {prover}: {'Success' if success else 'Failed'}")
            print()
            
        except Exception as e:
            print(f"Error installing theorem provers: {e}")
            print("Continuing with available provers...")
            print()
    
    # Step 2: Use simulated website content
    print("Step 2: Using simulated legal website content...")
    
    website_content = create_sample_legal_website_content()
    
    print(f"✓ Simulated content from: {website_content['url']}")
    print(f"  Title: {website_content['title']}")
    print(f"  Text length: {len(website_content['text']):,} characters")
    print()
    
    # Show sample of content
    sample_text = website_content['text'][:400] + "..." if len(website_content['text']) > 400 else website_content['text']
    print("Sample content:")
    print("-" * 40)
    print(sample_text)
    print()
    
    # Step 3: Create knowledge graph from text
    print("Step 3: Creating knowledge graph from content...")
    
    try:
        # Use the existing mock knowledge graph creation but adapt for corporate governance
        knowledge_graph = create_corporate_governance_knowledge_graph(website_content['text'])
        
        print(f"✓ Knowledge graph created")
        print(f"  Entities: {len(knowledge_graph.entities)}")
        print(f"  Relationships: {len(knowledge_graph.relationships)}")
        print()
        
    except Exception as e:
        print(f"Error creating knowledge graph: {e}")
        return 1
    
    # Step 4: Convert to deontic logic
    print("Step 4: Converting to deontic logic...")
    
    try:
        from ipfs_datasets_py.logic_integration import (
            DeonticLogicConverter, LegalDomainKnowledge, ConversionContext, LegalDomain
        )
        
        # Initialize converter
        domain_knowledge = LegalDomainKnowledge()
        converter = DeonticLogicConverter(domain_knowledge)
        
        # Create context for corporate governance
        context = ConversionContext(
            source_document_path=website_content['url'],
            document_title=website_content['title'],
            legal_domain=LegalDomain.CORPORATE,
            jurisdiction="Federal Securities Law, USA",
            confidence_threshold=0.6,
            enable_temporal_analysis=True,
            enable_agent_inference=True,
            enable_condition_extraction=True
        )
        
        # Convert to deontic logic
        conversion_result = converter.convert_knowledge_graph_to_logic(knowledge_graph, context)
        
        print(f"✓ Deontic logic conversion completed")
        print(f"  Generated formulas: {len(conversion_result.deontic_formulas)}")
        print(f"  Obligations: {conversion_result.statistics.get('obligations', 0)}")
        print(f"  Permissions: {conversion_result.statistics.get('permissions', 0)}")
        print(f"  Prohibitions: {conversion_result.statistics.get('prohibitions', 0)}")
        print()
        
        # Display sample formulas
        print("Sample extracted formulas:")
        print("-" * 40)
        for i, formula in enumerate(conversion_result.deontic_formulas[:3], 1):
            print(f"{i}. {formula.operator.value.upper()}: {formula.proposition}")
            print(f"   Agent: {formula.agent.name if formula.agent else 'N/A'}")
            print(f"   FOL: {formula.to_fol_string()}")
            print(f"   Source: {formula.source_text[:80]}...")
            print()
        
    except Exception as e:
        print(f"Error during deontic logic conversion: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Step 5: Execute theorem proofs
    print("Step 5: Executing theorem proofs...")
    
    try:
        from ipfs_datasets_py.logic_integration import create_proof_engine
        
        proof_engine = create_proof_engine(
            temp_dir=str(output_dir / "proofs"),
            timeout=args.timeout
        )
        
        # Show available provers
        prover_status = proof_engine.get_prover_status()
        available_provers = [p for p, available in prover_status["available_provers"].items() if available]
        
        print(f"Available provers: {available_provers}")
        print()
        
        if not conversion_result.deontic_formulas:
            print("No formulas to prove")
            return 1
        
        if args.prover == "all" and available_provers:
            # Test with first available prover if multiple requested
            test_prover = available_provers[0] if available_provers else "z3"
            print(f"Testing with first available prover: {test_prover}")
            
            sample_formula = conversion_result.deontic_formulas[0]
            print(f"Proving formula: {sample_formula.to_fol_string()}")
            print()
            
            proof_result = proof_engine.prove_deontic_formula(sample_formula, test_prover)
            
            status_icon = {
                'success': '✓',
                'failure': '✗', 
                'timeout': '⏱',
                'error': '✗',
                'unsupported': '?'
            }.get(proof_result.status.value, '?')
            
            print(f"  {status_icon} Proof result: {proof_result.status.value}")
            if proof_result.execution_time > 0:
                print(f"    Execution time: {proof_result.execution_time:.3f}s")
            if proof_result.proof_output:
                print(f"    Proof output: {proof_result.proof_output[:200]}...")
            if proof_result.errors:
                print(f"    Errors: {'; '.join(proof_result.errors)}")
            print()
            
        elif available_provers and args.prover in available_provers:
            # Prove with specific prover
            print(f"Proving formulas with {args.prover}...")
            
            # Prove first few formulas as demonstration
            sample_formulas = conversion_result.deontic_formulas[:3]
            
            for i, formula in enumerate(sample_formulas, 1):
                print(f"Proving formula {i}: {formula.to_fol_string()}")
                
                proof_result = proof_engine.prove_deontic_formula(formula, args.prover)
                
                status_icon = {
                    'success': '✓',
                    'failure': '✗',
                    'timeout': '⏱',
                    'error': '✗'
                }.get(proof_result.status.value, '?')
                
                print(f"  {status_icon} {proof_result.status.value} ({proof_result.execution_time:.3f}s)")
                if proof_result.errors:
                    print(f"    Errors: {'; '.join(proof_result.errors[:1])}")
                print()
        else:
            print(f"Prover {args.prover} not available or no provers installed")
            print("Available provers:", available_provers)
            return 1
        
    except Exception as e:
        print(f"Error during proof execution: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Step 6: Save results
    print("Step 6: Saving results...")
    
    try:
        # Save simulated extraction
        with open(output_dir / "simulated_extraction.json", 'w') as f:
            json.dump(website_content, f, indent=2)
        
        # Save conversion result
        with open(output_dir / "conversion_result.json", 'w') as f:
            json.dump(conversion_result.to_dict(), f, indent=2, default=str)
        
        # Save proof results
        if 'proof_result' in locals():
            with open(output_dir / f"proof_result_{args.prover}.json", 'w') as f:
                json.dump(proof_result.to_dict(), f, indent=2, default=str)
        
        print(f"✓ Results saved to {output_dir}")
        print()
        
    except Exception as e:
        print(f"Error saving results: {e}")
    
    # Final summary
    print("LOCAL DEMONSTRATION SUMMARY")
    print("=" * 40)
    print(f"✓ Simulated text extraction from corporate governance content")
    print(f"✓ Text length: {len(website_content['text']):,} characters")
    print(f"✓ Deontic formulas generated: {len(conversion_result.deontic_formulas)}")
    
    if 'proof_result' in locals():
        print(f"✓ Proof execution: {proof_result.status.value} with {args.prover}")
        print(f"✓ Execution time: {proof_result.execution_time:.3f}s")
    
    print(f"✓ Results saved to: {output_dir}")
    print()
    print("🎉 Local demonstration completed!")
    
    return 0


def create_corporate_governance_knowledge_graph(text: str):
    """Create a knowledge graph from corporate governance text."""
    
    # Import required classes
    try:
        from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import Entity, Relationship, KnowledgeGraph
    except ImportError:
        # Use mock classes from the legal demo
        from demonstrate_legal_deontic_logic import Entity, Relationship, KnowledgeGraph
    
    # Create entities representing corporate governance concepts
    entities = [
        Entity(
            entity_id="board_of_directors",
            entity_type="legal_agent",
            name="Board of Directors",
            properties={
                "text": "The board of directors shall exercise oversight of the corporation's operations",
                "role": "corporate_governance_body"
            },
            source_text="The board of directors shall exercise oversight of the corporation's operations and strategic direction"
        ),
        Entity(
            entity_id="directors",
            entity_type="legal_agent", 
            name="Directors",
            properties={
                "text": "Directors must act in good faith and in the best interests of the corporation",
                "role": "fiduciary"
            },
            source_text="Directors must act in good faith and in the best interests of the corporation and its shareholders"
        ),
        Entity(
            entity_id="audit_committee",
            entity_type="legal_agent",
            name="Audit Committee", 
            properties={
                "text": "The board shall establish an audit committee comprised of independent directors",
                "role": "oversight_committee"
            },
            source_text="The board shall establish an audit committee comprised of independent directors"
        ),
        Entity(
            entity_id="oversight_obligation",
            entity_type="legal_obligation",
            name="Corporate Oversight Obligation",
            properties={
                "text": "The board of directors shall exercise oversight of the corporation's operations",
                "action": "exercise_oversight",
                "subject": "corporation's operations and strategic direction"
            },
            source_text="The board of directors shall exercise oversight of the corporation's operations and strategic direction"
        ),
        Entity(
            entity_id="fiduciary_duty",
            entity_type="legal_obligation",
            name="Fiduciary Duty",
            properties={
                "text": "Directors must act in good faith and in the best interests of the corporation",
                "action": "act_in_good_faith",
                "beneficiary": "corporation and shareholders"
            },
            source_text="Directors must act in good faith and in the best interests of the corporation and its shareholders"
        ),
        Entity(
            entity_id="audit_committee_requirement",
            entity_type="legal_obligation",
            name="Audit Committee Establishment",
            properties={
                "text": "The board shall establish an audit committee comprised of independent directors",
                "action": "establish_audit_committee",
                "requirement": "independent directors"
            },
            source_text="The board shall establish an audit committee comprised of independent directors"
        ),
        Entity(
            entity_id="transaction_review_obligation",
            entity_type="legal_obligation",
            name="Related Party Transaction Review",
            properties={
                "text": "The audit committee must review and approve all material transactions between the corporation and related parties",
                "action": "review_and_approve_transactions",
                "scope": "material transactions with related parties"
            },
            source_text="The audit committee must review and approve all material transactions between the corporation and related parties"
        ),
        Entity(
            entity_id="conflict_prohibition",
            entity_type="legal_prohibition",
            name="Conflict of Interest Prohibition",
            properties={
                "text": "Directors are prohibited from engaging in transactions that create conflicts of interest",
                "action": "engage_in_conflict_transactions",
                "exception": "with proper disclosure and approval"
            },
            source_text="Directors are prohibited from engaging in transactions that create conflicts of interest without proper disclosure and approval"
        ),
        Entity(
            entity_id="disclosure_obligation",
            entity_type="legal_obligation",
            name="Material Information Disclosure",
            properties={
                "text": "The corporation must promptly disclose all material information that could affect the stock price",
                "action": "disclose_material_information",
                "timing": "promptly",
                "scope": "information affecting stock price"
            },
            source_text="The corporation must promptly disclose all material information that could affect the stock price"
        ),
        Entity(
            entity_id="insider_trading_prohibition",
            entity_type="legal_prohibition",
            name="Insider Trading Prohibition",
            properties={
                "text": "Insider trading is strictly prohibited",
                "action": "insider_trading",
                "enforcement": "strict prohibition"
            },
            source_text="Insider trading is strictly prohibited, and the corporation must maintain policies preventing such activities"
        ),
        Entity(
            entity_id="shareholder_voting_right",
            entity_type="legal_permission",
            name="Shareholder Voting Rights",
            properties={
                "text": "Shareholders have the right to vote on fundamental corporate matters",
                "action": "vote_on_corporate_matters",
                "scope": "fundamental matters including mergers, acquisitions, major asset sales"
            },
            source_text="Shareholders have the right to vote on fundamental corporate matters including mergers, acquisitions, and major asset sales"
        )
    ]
    
    # Create relationships
    entity_map = {entity.entity_id: entity for entity in entities}
    
    relationships = [
        Relationship(
            relationship_id="board_oversight_duty",
            relationship_type="must_fulfill",
            source_entity=entity_map["board_of_directors"],
            target_entity=entity_map["oversight_obligation"],
            properties={"legal_basis": "corporate governance law", "enforceability": "regulatory"},
            source_text="The board of directors shall exercise oversight of the corporation's operations and strategic direction"
        ),
        Relationship(
            relationship_id="directors_fiduciary_duty",
            relationship_type="must_fulfill", 
            source_entity=entity_map["directors"],
            target_entity=entity_map["fiduciary_duty"],
            properties={"legal_basis": "fiduciary law", "standard": "good faith and best interests"},
            source_text="Directors must act in good faith and in the best interests of the corporation and its shareholders"
        ),
        Relationship(
            relationship_id="board_audit_committee_duty",
            relationship_type="must_fulfill",
            source_entity=entity_map["board_of_directors"],
            target_entity=entity_map["audit_committee_requirement"],
            properties={"legal_basis": "securities regulation", "composition": "independent directors"},
            source_text="The board shall establish an audit committee comprised of independent directors"
        ),
        Relationship(
            relationship_id="audit_review_duty",
            relationship_type="must_fulfill",
            source_entity=entity_map["audit_committee"],
            target_entity=entity_map["transaction_review_obligation"],
            properties={"legal_basis": "audit committee charter", "scope": "related party transactions"},
            source_text="The audit committee must review and approve all material transactions between the corporation and related parties"
        ),
        Relationship(
            relationship_id="directors_conflict_prohibition",
            relationship_type="must_not_do",
            source_entity=entity_map["directors"],
            target_entity=entity_map["conflict_prohibition"],
            properties={"legal_basis": "conflict of interest rules", "exception": "disclosure and approval"},
            source_text="Directors are prohibited from engaging in transactions that create conflicts of interest without proper disclosure and approval"
        )
    ]
    
    # Create knowledge graph
    knowledge_graph = KnowledgeGraph()
    
    # Initialize dictionary-like structure to match expected interface
    if not hasattr(knowledge_graph, 'entities') or isinstance(knowledge_graph.entities, list):
        knowledge_graph.entities = {}
        knowledge_graph.entity_types = {}
        knowledge_graph.entity_names = {}
        knowledge_graph.entity_relationships = {}
        knowledge_graph.relationships = {}
        knowledge_graph.relationship_types = {}
        
        # Initialize default collections
        from collections import defaultdict
        knowledge_graph.entity_types = defaultdict(set)
        knowledge_graph.entity_names = defaultdict(set)
        knowledge_graph.entity_relationships = defaultdict(set)
        knowledge_graph.relationship_types = defaultdict(set)
    
    # Add entities
    for entity in entities:
        knowledge_graph.entities[entity.entity_id] = entity
        knowledge_graph.entity_types[entity.entity_type].add(entity.entity_id)
        knowledge_graph.entity_names[entity.name].add(entity.entity_id)
    
    # Add relationships
    for relationship in relationships:
        knowledge_graph.relationships[relationship.relationship_id] = relationship
        knowledge_graph.relationship_types[relationship.relationship_type].add(relationship.relationship_id)
        if hasattr(relationship, 'source_entity') and relationship.source_entity:
            knowledge_graph.entity_relationships[relationship.source_entity.entity_id].add(relationship.relationship_id)
        if hasattr(relationship, 'target_entity') and relationship.target_entity:
            knowledge_graph.entity_relationships[relationship.target_entity.entity_id].add(relationship.relationship_id)
    
    return knowledge_graph


if __name__ == "__main__":
    sys.exit(main())