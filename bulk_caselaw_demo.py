#!/usr/bin/env python3
"""
Bulk Caselaw Processing Demonstration

This script demonstrates the bulk processing of entire caselaw corpus
to construct a unified temporal deontic logic system.
"""

import sys
import os
import asyncio
import tempfile
import json
from datetime import datetime
from pathlib import Path
sys.path.append(os.path.join(os.path.dirname(__file__), 'ipfs_datasets_py'))

def create_sample_caselaw_corpus():
    """Create a sample caselaw corpus for demonstration."""
    print("📂 Creating sample caselaw corpus...")
    
    # Create temporary directory for sample caselaw
    temp_dir = tempfile.mkdtemp(prefix="sample_caselaw_")
    
    # Sample legal cases in different formats
    cases = [
        {
            "filename": "federal_confidentiality_2015.json",
            "data": {
                "id": "fed_conf_2015_001",
                "title": "Confidentiality Standards Act Implementation",
                "text": """
                FEDERAL CONFIDENTIALITY STANDARDS ACT (2015)
                
                Section 1: Professional Obligations
                All licensed professionals SHALL NOT disclose confidential client information 
                to unauthorized third parties without explicit written consent.
                
                Section 2: Permitted Disclosures
                Professionals MAY disclose confidential information when required by court order
                or when necessary to prevent imminent harm.
                
                Section 3: Violations
                Any professional who violates these confidentiality requirements SHALL face
                immediate license suspension and potential criminal charges.
                """,
                "date": "2015-03-15",
                "jurisdiction": "Federal",
                "court": "Federal Legislative",
                "citation": "Fed. Conf. Act § 1-3 (2015)",
                "legal_domains": ["confidentiality", "professional_services"],
                "precedent_strength": 0.95
            }
        },
        {
            "filename": "employment_notice_2020.json", 
            "data": {
                "id": "emp_notice_2020_001",
                "title": "Employment Termination Notice Requirements",
                "text": """
                CASE: Smith Industries v. Workers Union (2020)
                
                HOLDING: The court finds that employers MUST provide written notice
                at least 30 days before terminating employment contracts. This requirement
                applies to all employees with more than 90 days of service.
                
                REASONING: Adequate notice protects employee interests and provides
                time for transition. Employers SHALL NOT terminate without proper notice
                except in cases of gross misconduct.
                
                PRECEDENT: This ruling establishes binding precedent for all employment
                terminations in this jurisdiction.
                """,
                "date": "2020-08-22",
                "jurisdiction": "Federal",
                "court": "Federal Circuit Court",
                "citation": "Smith Indus. v. Workers Union, 485 F.3d 123 (2020)",
                "legal_domains": ["employment", "contract"],
                "precedent_strength": 0.90
            }
        },
        {
            "filename": "business_access_rights_2018.json",
            "data": {
                "id": "bus_access_2018_001", 
                "title": "Business Information Access Rights",
                "text": """
                STATE SUPREME COURT DECISION
                Business Access Rights v. Privacy Advocates (2018)
                
                The court holds that employees MAY access confidential business information
                when such access is necessary for authorized job functions and business purposes.
                
                However, employees MUST NOT use such information for personal gain or
                competitive advantage. All access SHALL be logged and monitored.
                
                Employers are REQUIRED TO provide clear guidelines on acceptable use
                of confidential information and regular training on privacy policies.
                """,
                "date": "2018-11-12",
                "jurisdiction": "State",
                "court": "State Supreme Court", 
                "citation": "Bus. Access Rights v. Privacy Advoc., 234 St.Sup. 456 (2018)",
                "legal_domains": ["employment", "confidentiality", "business"],
                "precedent_strength": 0.85
            }
        },
        {
            "filename": "contract_disclosure_2019.txt",
            "content": """
            CONTRACT DISCLOSURE REQUIREMENTS CASE LAW
            
            Johnson v. Corporate Services Inc. (2019)
            Federal District Court
            
            FACTS: Employee signed confidentiality agreement but disclosed trade secrets
            to competitor. Company sued for breach of contract.
            
            HOLDING: Court ruled that confidentiality agreements ARE BINDING and employees
            MUST NOT disclose proprietary information even after termination.
            
            The court established that employees SHALL maintain confidentiality for
            a period of 5 years post-employment unless information becomes public knowledge.
            
            Companies MAY seek injunctive relief and damages for violations.
            This creates strong precedent for confidentiality enforcement.
            """
        },
        {
            "filename": "intellectual_property_2021.txt", 
            "content": """
            INTELLECTUAL PROPERTY PROTECTION RULING
            
            TechCorp v. Former Employee (2021)
            Circuit Court of Appeals
            
            DECISION: Employees working on proprietary technology MUST assign all
            intellectual property rights to their employer during employment.
            
            Former employees SHALL NOT use or disclose proprietary methods,
            algorithms, or trade secrets for competitive purposes.
            
            The court MAY grant preliminary injunctions to prevent ongoing harm
            from IP theft or misuse by former employees or competitors.
            
            This ruling strengthens IP protection for technology companies.
            """
        }
    ]
    
    # Write sample cases to files
    for case in cases:
        file_path = Path(temp_dir) / case["filename"]
        
        if case["filename"].endswith(".json"):
            with open(file_path, 'w') as f:
                json.dump(case["data"], f, indent=2)
        else:
            with open(file_path, 'w') as f:
                f.write(case["content"])
    
    print(f"✅ Created {len(cases)} sample caselaw documents in {temp_dir}")
    return temp_dir


async def demonstrate_bulk_processing():
    """Demonstrate bulk caselaw processing."""
    print("⚖️  BULK CASELAW PROCESSING DEMONSTRATION")
    print("Building Unified Temporal Deontic Logic System from Entire Caselaw Corpus") 
    print("=" * 80)
    
    try:
        # Import components
        from ipfs_datasets_py.logic_integration.caselaw_bulk_processor import (
            CaselawBulkProcessor, BulkProcessingConfig, create_bulk_processor
        )
        from ipfs_datasets_py.logic_integration.temporal_deontic_rag_store import TemporalDeonticRAGStore
        
        # Step 1: Create sample caselaw corpus
        caselaw_dir = create_sample_caselaw_corpus()
        
        # Step 2: Configure bulk processing
        print(f"\n🔧 Configuring Bulk Processing...")
        print("-" * 50)
        
        config = BulkProcessingConfig(
            caselaw_directories=[caselaw_dir],
            output_directory="unified_deontic_logic_system_demo",
            max_concurrent_documents=3,
            enable_parallel_processing=True,
            min_precedent_strength=0.7,
            enable_consistency_validation=True,
            enable_duplicate_detection=True,
            min_theorem_confidence=0.7
        )
        
        print(f"📁 Input Directory: {caselaw_dir}")
        print(f"📁 Output Directory: {config.output_directory}")
        print(f"⚡ Parallel Processing: {config.enable_parallel_processing}")
        print(f"🎯 Min Precedent Strength: {config.min_precedent_strength}")
        print(f"✅ Consistency Validation: {config.enable_consistency_validation}")
        
        # Step 3: Initialize processor
        print(f"\n🚀 Initializing Bulk Processor...")
        print("-" * 50)
        
        processor = CaselawBulkProcessor(config)
        print("✅ Bulk processor initialized")
        
        # Step 4: Process entire caselaw corpus
        print(f"\n📚 Processing Entire Caselaw Corpus...")
        print("-" * 50)
        print("This will:")
        print("  1. Discover all caselaw documents")
        print("  2. Extract temporal deontic logic theorems")
        print("  3. Build unified legal knowledge system") 
        print("  4. Validate system consistency")
        print("  5. Export unified system")
        print()
        
        # Run bulk processing
        stats = await processor.process_caselaw_corpus()
        
        # Step 5: Display results
        print(f"\n🎉 BULK PROCESSING COMPLETE!")
        print("=" * 80)
        
        print(f"\n📊 Processing Statistics:")
        print(f"  Total Documents: {stats.total_documents}")
        print(f"  Processed Documents: {stats.processed_documents}")
        print(f"  Extracted Theorems: {stats.extracted_theorems}")
        print(f"  Processing Errors: {stats.processing_errors}")
        print(f"  Success Rate: {stats.success_rate:.1%}")
        print(f"  Processing Time: {stats.processing_time}")
        
        print(f"\n🌍 Coverage:")
        print(f"  Jurisdictions: {', '.join(stats.jurisdictions_processed)}")
        print(f"  Legal Domains: {', '.join(stats.legal_domains_processed)}")
        if stats.temporal_range[0] and stats.temporal_range[1]:
            print(f"  Temporal Range: {stats.temporal_range[0].year} - {stats.temporal_range[1].year}")
        
        # Step 6: Show unified system details
        print(f"\n🏗️  Unified Deontic Logic System:")
        print("-" * 50)
        
        rag_store = processor.rag_store
        rag_stats = rag_store.get_statistics()
        
        print(f"  Total Theorems: {rag_stats['total_theorems']}")
        print(f"  Jurisdictions in System: {rag_stats['jurisdictions']}")
        print(f"  Legal Domains in System: {rag_stats['legal_domains']}")
        print(f"  Average Precedent Strength: {rag_stats['avg_precedent_strength']:.2f}")
        
        # Step 7: Sample theorem queries
        print(f"\n🔍 Sample Theorem Queries from Unified System:")
        print("-" * 50)
        
        from ipfs_datasets_py.logic_integration.deontic_logic_core import DeonticFormula, DeonticOperator, LegalAgent
        
        queries = [
            ("confidentiality violations", DeonticOperator.PROHIBITION),
            ("employment notice requirements", DeonticOperator.OBLIGATION),
            ("business information access", DeonticOperator.PERMISSION)
        ]
        
        for query_text, operator in queries:
            print(f"\n🔎 Query: '{query_text}' ({operator.name})")
            
            query_formula = DeonticFormula(
                operator=operator,
                proposition=query_text,
                agent=LegalAgent("query_agent", "Query Agent", "person")
            )
            
            relevant_theorems = rag_store.retrieve_relevant_theorems(
                query_formula=query_formula,
                temporal_context=datetime.now(),
                top_k=3
            )
            
            print(f"📋 Found {len(relevant_theorems)} relevant theorems:")
            for i, theorem in enumerate(relevant_theorems, 1):
                print(f"  {i}. {theorem.formula.operator.name}: {theorem.formula.proposition[:60]}...")
                print(f"     Source: {theorem.source_case}")
                print(f"     Jurisdiction: {theorem.jurisdiction}, Strength: {theorem.precedent_strength:.2f}")
        
        # Step 8: Show output files
        print(f"\n📁 Generated Output Files:")
        print("-" * 50)
        
        output_dir = Path(config.output_directory)
        if output_dir.exists():
            for file_path in output_dir.iterdir():
                if file_path.is_file():
                    size_kb = file_path.stat().st_size / 1024
                    print(f"  📄 {file_path.name} ({size_kb:.1f} KB)")
        
        print(f"\n🎯 Key Benefits of Unified System:")
        print("-" * 50)
        print("  ✅ Comprehensive coverage of all available caselaw")
        print("  ✅ Temporal awareness for legal precedent evolution")
        print("  ✅ Cross-jurisdictional consistency checking")
        print("  ✅ Automated theorem extraction from legal text")
        print("  ✅ Scalable processing of large legal corpora")
        print("  ✅ RAG-based semantic search of legal precedents")
        print("  ✅ Document consistency checking like a legal debugger")
        
        print(f"\n💡 Usage in Dashboard:")
        print("  🌐 Access via: /mcp/caselaw → Bulk Process Caselaw tab")
        print("  📂 Specify multiple caselaw directories")
        print("  ⚙️  Configure processing parameters")
        print("  ▶️  Start bulk processing with real-time progress")
        print("  📊 Monitor statistics and system building")
        print("  💾 Download unified system when complete")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Demonstration failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        # Cleanup sample directory
        try:
            import shutil
            if 'caselaw_dir' in locals():
                shutil.rmtree(caselaw_dir)
                print(f"\n🧹 Cleaned up sample directory: {caselaw_dir}")
        except Exception as e:
            print(f"Warning: Could not cleanup sample directory: {e}")


if __name__ == "__main__":
    print("Starting bulk caselaw processing demonstration...")
    success = asyncio.run(demonstrate_bulk_processing())
    exit(0 if success else 1)