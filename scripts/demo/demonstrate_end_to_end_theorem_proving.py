#!/usr/bin/env python3
"""
End-to-End Website to Theorem Prover Pipeline

This script demonstrates the complete pipeline from website text extraction
through GraphRAG processing, deontic logic conversion, to actual theorem proving.
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

def main():
    """Main entry point for end-to-end demonstration."""
    parser = argparse.ArgumentParser(
        description="End-to-end website to theorem prover pipeline"
    )
    parser.add_argument(
        "--url", "-u",
        type=str,
        default="https://www.law.cornell.edu/wex/contract",
        help="Website URL to extract text from (default: Cornell Law contract page)"
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
        default="./end_to_end_results",
        help="Output directory for results"
    )
    parser.add_argument(
        "--show-status", "-s",
        action="store_true",
        help="Show system status and available provers"
    )
    parser.add_argument(
        "--timeout", "-t",
        type=int,
        default=120,
        help="Timeout for proof execution in seconds (default: 120)"
    )
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("END-TO-END WEBSITE TO THEOREM PROVER PIPELINE")
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
    
    # Step 2: Show system status
    if args.show_status or args.install_provers:
        print("Step 2: System status...")
        
        try:
            from ipfs_datasets_py.logic.integration import create_proof_engine
            proof_engine = create_proof_engine(timeout=args.timeout)
            status = proof_engine.get_prover_status()
            
            print("Available theorem provers:")
            for prover, available in status["available_provers"].items():
                status_icon = "✓" if available else "✗"
                print(f"  {status_icon} {prover}: {'Available' if available else 'Not available'}")
            
            print(f"Proof execution timeout: {status['timeout']} seconds")
            print(f"Temporary directory: {status['temp_directory']}")
            print()
            
        except Exception as e:
            print(f"Error checking system status: {e}")
            print()
    
    # Step 3: Extract text from website
    print(f"Step 3: Extracting text from website: {args.url}")
    
    try:
        from ipfs_datasets_py import extract_website_text
        
        extraction_result = extract_website_text(args.url)
        
        if extraction_result.success:
            print(f"✓ Successfully extracted text from {args.url}")
            print(f"  Title: {extraction_result.title}")
            print(f"  Text length: {extraction_result.text_length:,} characters")
            print(f"  Extraction time: {extraction_result.extraction_time:.2f} seconds")
            print(f"  Method: {extraction_result.metadata.get('method', 'unknown')}")
            
            # Save extracted text
            from ipfs_datasets_py.web_text_extractor import WebTextExtractor
            extractor = WebTextExtractor()
            text_file = extractor.save_extracted_text(extraction_result, output_dir)
            print(f"  Saved to: {text_file}")
            print()
            
            # Show sample of extracted text
            sample_text = extraction_result.text[:500] + "..." if len(extraction_result.text) > 500 else extraction_result.text
            print("Sample extracted text:")
            print("-" * 40)
            print(sample_text)
            print()
            
        else:
            print(f"✗ Failed to extract text from {args.url}")
            print(f"  Errors: {extraction_result.errors}")
            return 1
            
    except Exception as e:
        print(f"Error during text extraction: {e}")
        return 1
    
    # Step 4: Process with GraphRAG
    print("Step 4: Processing with GraphRAG...")
    
    try:
        # Check if we have a real GraphRAG processor or need to use mock
        from ipfs_datasets_py import GraphRAGProcessor
        
        if GraphRAGProcessor is not None:
            processor = GraphRAGProcessor()
            
            # Process the extracted text
            graphrag_result = processor.process_text(
                text=extraction_result.text,
                title=extraction_result.title,
                source_url=args.url
            )
            
            print(f"✓ GraphRAG processing completed")
            print(f"  Entities extracted: {len(graphrag_result.entities) if hasattr(graphrag_result, 'entities') else 'N/A'}")
            print(f"  Relationships extracted: {len(graphrag_result.relationships) if hasattr(graphrag_result, 'relationships') else 'N/A'}")
            
        else:
            print("Using mock GraphRAG data (real GraphRAG processor not available)")
            # Create mock knowledge graph for demonstration
            from demonstrate_legal_deontic_logic import create_mock_knowledge_graph
            knowledge_graph = create_mock_knowledge_graph()
            
            print(f"✓ Mock GraphRAG data created")
            print(f"  Entities: {len(knowledge_graph.entities)}")
            print(f"  Relationships: {len(knowledge_graph.relationships)}")
            
    except Exception as e:
        print(f"Error during GraphRAG processing: {e}")
        print("Continuing with mock data...")
        
        # Fallback to mock data
        from demonstrate_legal_deontic_logic import create_mock_knowledge_graph
        knowledge_graph = create_mock_knowledge_graph()
        print(f"Using mock knowledge graph with {len(knowledge_graph.entities)} entities")
    
    print()
    
    # Step 5: Convert to deontic logic
    print("Step 5: Converting to deontic logic...")
    
    try:
        from ipfs_datasets_py.logic.integration import (
            DeonticLogicConverter, LegalDomainKnowledge, ConversionContext, LegalDomain
        )
        
        # Initialize converter
        domain_knowledge = LegalDomainKnowledge()
        converter = DeonticLogicConverter(domain_knowledge)
        
        # Create context
        context = ConversionContext(
            source_document_path=args.url,
            document_title=extraction_result.title,
            legal_domain=LegalDomain.CONTRACT,  # Assume contract domain
            jurisdiction="General",
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
        print(f"  Conversion errors: {len(conversion_result.errors)}")
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
        
        if len(conversion_result.deontic_formulas) > 3:
            print(f"... and {len(conversion_result.deontic_formulas) - 3} more formulas")
            print()
        
    except Exception as e:
        print(f"Error during deontic logic conversion: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Step 6: Execute proofs
    print("Step 6: Executing theorem proofs...")
    
    try:
        from ipfs_datasets_py.logic.integration import create_proof_engine
        
        proof_engine = create_proof_engine(
            temp_dir=str(output_dir / "proofs"),
            timeout=args.timeout
        )
        
        if args.prover == "all":
            # Prove with all available provers
            if not conversion_result.deontic_formulas:
                print("No formulas to prove")
                return 1
                
            sample_formula = conversion_result.deontic_formulas[0]
            print(f"Proving sample formula with all available provers:")
            print(f"Formula: {sample_formula.to_fol_string()}")
            print()
            
            proof_results = proof_engine.prove_multiple_provers(sample_formula)
            
            for prover, result in proof_results.items():
                status_icon = {
                    'success': '✓',
                    'failure': '✗', 
                    'timeout': '⏱',
                    'error': '✗',
                    'unsupported': '?'
                }.get(result.status.value, '?')
                
                print(f"  {status_icon} {prover}: {result.status.value}")
                if result.execution_time > 0:
                    print(f"    Execution time: {result.execution_time:.3f}s")
                if result.errors:
                    print(f"    Errors: {'; '.join(result.errors[:2])}")
                print()
            
            # Check consistency of entire rule set
            print("Checking rule set consistency...")
            consistency_result = proof_engine.prove_consistency(conversion_result.rule_set, "z3")
            
            status_icon = {
                'success': '✓',
                'failure': '✗',
                'timeout': '⏱',
                'error': '✗'
            }.get(consistency_result.status.value, '?')
            
            print(f"  {status_icon} Consistency check: {consistency_result.status.value}")
            if consistency_result.execution_time > 0:
                print(f"    Execution time: {consistency_result.execution_time:.3f}s")
            print()
            
        else:
            # Prove with specific prover
            if not conversion_result.deontic_formulas:
                print("No formulas to prove")
                return 1
                
            print(f"Proving formulas with {args.prover}...")
            
            proof_results = proof_engine.prove_rule_set(conversion_result.rule_set, args.prover)
            
            successful_proofs = sum(1 for r in proof_results if r.status.value == 'success')
            total_proofs = len(proof_results)
            
            print(f"✓ Completed {successful_proofs}/{total_proofs} proofs successfully")
            
            # Show detailed results
            for i, result in enumerate(proof_results[:5], 1):  # Show first 5
                status_icon = {
                    'success': '✓',
                    'failure': '✗',
                    'timeout': '⏱',
                    'error': '✗'
                }.get(result.status.value, '?')
                
                print(f"  {i}. {status_icon} {result.status.value} ({result.execution_time:.3f}s)")
                if result.errors:
                    print(f"     Errors: {'; '.join(result.errors[:1])}")
            
            if total_proofs > 5:
                print(f"  ... and {total_proofs - 5} more proofs")
            print()
        
    except Exception as e:
        print(f"Error during proof execution: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Step 7: Save comprehensive results
    print("Step 7: Saving results...")
    
    try:
        # Save extraction result
        with open(output_dir / "extraction_result.json", 'w') as f:
            json.dump(extraction_result.to_dict(), f, indent=2, default=str)
        
        # Save conversion result
        with open(output_dir / "conversion_result.json", 'w') as f:
            json.dump(conversion_result.to_dict(), f, indent=2, default=str)
        
        # Save proof results
        if args.prover == "all":
            with open(output_dir / "proof_results_all.json", 'w') as f:
                json.dump({k: v.to_dict() for k, v in proof_results.items()}, f, indent=2, default=str)
            
            with open(output_dir / "consistency_result.json", 'w') as f:
                json.dump(consistency_result.to_dict(), f, indent=2, default=str)
        else:
            with open(output_dir / f"proof_results_{args.prover}.json", 'w') as f:
                json.dump([r.to_dict() for r in proof_results], f, indent=2, default=str)
        
        print(f"✓ Results saved to {output_dir}")
        
        # Create summary report
        summary = {
            "pipeline_summary": {
                "source_url": args.url,
                "extraction_success": extraction_result.success,
                "text_length": extraction_result.text_length,
                "formulas_generated": len(conversion_result.deontic_formulas),
                "conversion_errors": len(conversion_result.errors),
                "prover_used": args.prover,
                "output_directory": str(output_dir)
            }
        }
        
        if args.prover == "all":
            summary["proof_summary"] = {
                "individual_proofs": {prover: result.status.value for prover, result in proof_results.items()},
                "consistency_check": consistency_result.status.value
            }
        else:
            successful_proofs = sum(1 for r in proof_results if r.status.value == 'success')
            summary["proof_summary"] = {
                "successful_proofs": successful_proofs,
                "total_proofs": len(proof_results),
                "success_rate": successful_proofs / len(proof_results) if proof_results else 0
            }
        
        with open(output_dir / "pipeline_summary.json", 'w') as f:
            json.dump(summary, f, indent=2, default=str)
        
        print()
        
    except Exception as e:
        print(f"Error saving results: {e}")
    
    # Final summary
    print("PIPELINE EXECUTION SUMMARY")
    print("=" * 40)
    print(f"✓ Text extracted from: {args.url}")
    print(f"✓ Text length: {extraction_result.text_length:,} characters")
    print(f"✓ Deontic formulas generated: {len(conversion_result.deontic_formulas)}")
    
    if args.prover == "all":
        successful_provers = sum(1 for r in proof_results.values() if r.status.value == 'success')
        print(f"✓ Proofs successful with {successful_provers}/{len(proof_results)} provers")
        print(f"✓ Rule set consistency: {consistency_result.status.value}")
    else:
        successful_proofs = sum(1 for r in proof_results if r.status.value == 'success')
        print(f"✓ Proofs successful: {successful_proofs}/{len(proof_results)} with {args.prover}")
    
    print(f"✓ Results saved to: {output_dir}")
    print()
    print("🎉 End-to-end pipeline completed successfully!")
    
    return 0


def test_with_legal_websites():
    """Test the pipeline with various legal websites."""
    legal_urls = [
        "https://www.law.cornell.edu/wex/contract",
        "https://www.law.cornell.edu/wex/tort", 
        "https://www.law.cornell.edu/wex/employment_law",
        "https://www.law.cornell.edu/wex/intellectual_property",
    ]
    
    print("Testing with multiple legal websites...")
    
    for url in legal_urls:
        print(f"\nTesting: {url}")
        try:
            # Run the pipeline for each URL
            sys.argv = ['demonstrate_end_to_end.py', '--url', url, '--prover', 'z3', '--timeout', '60']
            main()
        except Exception as e:
            print(f"Error processing {url}: {e}")
            continue
    
    print("\nMulti-website testing completed!")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test-multiple":
        test_with_legal_websites()
    else:
        sys.exit(main())