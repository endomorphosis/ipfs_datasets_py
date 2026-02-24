"""Batch 262: Profile OntologyGenerator.generate() on 10k-token input

Profiles the complete generate_ontology() pipeline on a large (10k token) legal document
to identify performance bottlenecks and hot paths.

Test Conditions:
    - Input size: ~10,000 tokens (40KB legal text)
    - Domain: legal
    - Strategy: RULE_BASED
    - Measurement: cProfile with function-level timing

Expected Bottlenecks:
    - Entity extraction pattern matching
    - Relationship inference (O(n²) entity pairs)
    - Property extraction
    - Confidence calculations

Usage:
    python profile_batch_262_generate_10k.py
    # Outputs: profile_batch_262_generate_10k.prof + profile_batch_262_generate_10k.txt
"""

import cProfile
import pstats
import sys
import pathlib
import time

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    DataType,
    ExtractionStrategy,
)


def generate_large_legal_text(target_tokens: int = 10000) -> str:
    """Generate a large legal document by repeating realistic patterns.
    
    Args:
        target_tokens: Target token count (approximate)
        
    Returns:
        String with approximately target_tokens tokens
    """
    # Base clause patterns (each ~100-150 tokens)
    clauses = [
        """The parties hereby agree that this Agreement constitutes the entire agreement 
        between the parties with respect to the subject matter hereof and supersedes all prior 
        and contemporaneous agreements, proposals, or representations, written or oral, concerning 
        its subject matter. No modification, amendment, or waiver of any provision of this Agreement 
        shall be effective unless in writing and signed by the party against whom the modification, 
        amendment or waiver is to be asserted. The parties represent that they have carefully read 
        this Agreement, understand the contents herein, freely and voluntarily agree to all of its terms, 
        and intend it to be a complete and exclusive statement of the terms of the agreement between them.""",
        
        """Contractor agrees to provide professional services in accordance with industry standards 
        and best practices. Contractor shall use commercially reasonable efforts to complete the Work 
        in a timely manner and in accordance with any schedules provided by Client. Contractor shall 
        be responsible for providing all equipment, tools, supplies, and materials necessary to perform 
        the Work unless otherwise specified in writing. Any delays caused by Client or circumstances 
        beyond Contractor's reasonable control shall extend performance dates accordingly. Contractor 
        shall maintain insurance coverage including general liability and professional liability in 
        amounts no less than $1,000,000 per occurrence and $2,000,000 aggregate.""",
        
        """Client shall pay Contractor the agreed-upon fees in accordance with the payment schedule 
        set forth herein. All invoices are due within thirty (30) days of receipt unless otherwise 
        specified. Late payments shall accrue interest at a rate of one and one-half percent (1.5%) 
        per month or the maximum rate permitted by law, whichever is less. Client shall reimburse 
        Contractor for all pre-approved expenses incurred in connection with the Work, provided that 
        Contractor submits appropriate documentation and receipts. Payment terms may be modified only 
        by written agreement signed by both parties. All fees are exclusive of applicable taxes, which 
        Client shall be responsible for paying.""",
        
        """Either party may terminate this Agreement upon thirty (30) days written notice to the other 
        party. Client may terminate this Agreement for convenience upon payment of fees for Work performed 
        through the date of termination plus any committed costs or expenses incurred by Contractor. 
        Contractor may terminate this Agreement immediately upon written notice if Client fails to pay 
        any undisputed invoice within sixty (60) days of receipt. Upon termination, Contractor shall 
        deliver all completed Work and Work in progress to Client, and Client shall pay all amounts due 
        through the effective date of termination. The provisions regarding confidentiality, intellectual 
        property, indemnification, and limitation of liability shall survive termination.""",
        
        """Each party agrees to maintain the confidentiality of all Confidential Information disclosed 
        by the other party and to use such Confidential Information solely for purposes of performing 
        under this Agreement. Confidential Information includes, but is not limited to, technical data, 
        trade secrets, know-how, research, product plans, services, customer lists, financial information, 
        and business plans. The receiving party shall protect Confidential Information using the same 
        degree of care it uses to protect its own confidential information, but in no event less than 
        reasonable care. These confidentiality obligations shall not apply to information that: (a) is 
        or becomes publicly available through no breach of this Agreement; (b) was rightfully in the 
        receiving party's possession prior to disclosure; (c) is rightfully received from a third party 
        without breach; or (d) is independently developed.""",
    ]
    
    # Party definitions
    parties = [
        "TechCorp Industries, Inc.",
        "Global Services LLC",
        "Acme Consulting Group",
        "Premier Solutions Ltd.",
        "Innovative Systems Corp.",
    ]
    
    # Build large text by repeating patterns with variations
    text_parts = []
    text_parts.append(f"MASTER SERVICES AGREEMENT\n\n")
    text_parts.append(f"This Agreement is entered into as of January 15, 2024, by and between ")
    text_parts.append(f"{parties[0]} ('Client') and {parties[1]} ('Contractor').\n\n")
    text_parts.append("WHEREAS, Client desires to retain Contractor to provide certain services; and\n")
    text_parts.append("WHEREAS, Contractor desires to provide such services on the terms set forth herein.\n\n")
    text_parts.append("NOW, THEREFORE, in consideration of the mutual covenants and agreements herein,\n")
    text_parts.append("the parties agree as follows:\n\n")
    
    # Add numbered sections with clause variations
    current_tokens = len(" ".join(text_parts).split())
    section_num = 1
    
    while current_tokens < target_tokens:
        for clause in clauses:
            if current_tokens >= target_tokens:
                break
            
            # Add section header
            section_title = [
                "SCOPE OF SERVICES",
                "PAYMENT TERMS",
                "TERM AND TERMINATION",
                "CONFIDENTIALITY",
                "INTELLECTUAL PROPERTY",
                "WARRANTIES AND REPRESENTATIONS",
                "INDEMNIFICATION",
                "LIMITATION OF LIABILITY",
                "DISPUTE RESOLUTION",
                "MISCELLANEOUS PROVISIONS",
            ][section_num % 10]
            
            text_parts.append(f"\n{section_num}. {section_title}\n\n")
            
            # Add clause with minor variations
            modified_clause = clause.replace("Contractor", f"Contractor ({parties[section_num % len(parties)]})")
            modified_clause = modified_clause.replace("Client", f"Client ({parties[(section_num + 1) % len(parties)]})")
            text_parts.append(modified_clause + "\n")
            
            # Add subsections for variety
            if section_num % 3 == 0:
                text_parts.append(f"\n{section_num}.1 Additional Obligations. The obligations set forth in this Section ")
                text_parts.append(f"shall continue notwithstanding any termination or expiration of this Agreement. ")
                text_parts.append(f"Each party acknowledges the importance of compliance with all applicable laws and regulations.\n")
            
            section_num += 1
            current_tokens = len(" ".join(text_parts).split())
    
    # Add signature block
    text_parts.append("\n\nIN WITNESS WHEREOF, the parties have executed this Agreement as of the date first written above.\n\n")
    text_parts.append(f"{parties[0]}\n")
    text_parts.append("By: _________________________\n")
    text_parts.append("Name: John Smith\nTitle: Chief Executive Officer\nDate: _______________\n\n")
    text_parts.append(f"{parties[1]}\n")
    text_parts.append("By: _________________________\n")
    text_parts.append("Name: Jane Doe\nTitle: Managing Partner\nDate: _______________\n")
    
    return "".join(text_parts)


def profile_generate_ontology():
    """Profile OntologyGenerator.generate_ontology() on 10k-token input."""
    
    # Generate large text
    print("Generating 10k-token legal text...")
    text = generate_large_legal_text(target_tokens=10000)
    token_count = len(text.split())
    text_size_kb = len(text) / 1024
    
    print(f"Generated text: {token_count} tokens, {text_size_kb:.1f} KB")
    
    # Create generator and context
    print("\nInitializing OntologyGenerator...")
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    
    context = OntologyGenerationContext(
        data_source="profile_test_10k",
        data_type=DataType.TEXT,
        domain="legal",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )
    
    # Warm-up run (not profiled)
    print("Performing warm-up run...")
    start_warmup = time.perf_counter()
    _ = generator.generate_ontology(text[:1000], context)  # Small warmup
    warmup_time = time.perf_counter() - start_warmup
    print(f"Warm-up completed in {warmup_time:.3f}s")
    
    # Profiled run
    print("\nStarting profiled run...")
    profiler = cProfile.Profile()
    
    start_time = time.perf_counter()
    profiler.enable()
    
    ontology = generator.generate_ontology(text, context)
    
    profiler.disable()
    end_time = time.perf_counter()
    
    elapsed_ms = (end_time - start_time) * 1000
    
    # Print results summary
    entity_count = len(ontology.get("entities", []))
    relationship_count = len(ontology.get("relationships", []))
    
    print("\n" + "=" * 80)
    print("PROFILING RESULTS SUMMARY")
    print("=" * 80)
    print(f"Input size: {token_count} tokens ({text_size_kb:.1f} KB)")
    print(f"Execution time: {elapsed_ms:.2f} ms")
    print(f"Entities extracted: {entity_count}")
    print(f"Relationships inferred: {relationship_count}")
    print(f"Throughput: {token_count / (elapsed_ms / 1000):.0f} tokens/sec")
    print(f"Throughput: {entity_count / (elapsed_ms / 1000):.1f} entities/sec")
    
    # Save profiling data
    output_dir = pathlib.Path(__file__).parent
    prof_file = output_dir / "profile_batch_262_generate_10k.prof"
    txt_file = output_dir / "profile_batch_262_generate_10k.txt"
    
    profiler.dump_stats(str(prof_file))
    print(f"\nProfile data saved to: {prof_file}")
    
    # Generate text report
    with open(txt_file, "w") as f:
        f.write("=" * 80 + "\n")
        f.write("BATCH 262: OntologyGenerator.generate_ontology() Profile (10k tokens)\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Input size: {token_count} tokens ({text_size_kb:.1f} KB)\n")
        f.write(f"Execution time: {elapsed_ms:.2f} ms\n")
        f.write(f"Entities extracted: {entity_count}\n")
        f.write(f"Relationships inferred: {relationship_count}\n")
        f.write(f"Throughput: {token_count / (elapsed_ms / 1000):.0f} tokens/sec\n")
        f.write(f"Throughput: {entity_count / (elapsed_ms / 1000):.1f} entities/sec\n\n")
        
        f.write("=" * 80 + "\n")
        f.write("TOP 30 FUNCTIONS BY CUMULATIVE TIME\n")
        f.write("=" * 80 + "\n\n")
        
        stats = pstats.Stats(profiler, stream=f)
        stats.strip_dirs()
        stats.sort_stats('cumulative')
        stats.print_stats(30)
        
        f.write("\n" + "=" * 80 + "\n")
        f.write("TOP 30 FUNCTIONS BY TOTAL TIME\n")
        f.write("=" * 80 + "\n\n")
        
        stats.sort_stats('tottime')
        stats.print_stats(30)
        
        f.write("\n" + "=" * 80 + "\n")
        f.write("TOP 30 MOST CALLED FUNCTIONS\n")
        f.write("=" * 80 + "\n\n")
        
        stats.sort_stats('ncalls')
        stats.print_stats(30)
    
    print(f"Text report saved to: {txt_file}")
    
    # Print top 10 hotspots to console
    print("\n" + "=" * 80)
    print("TOP 10 HOTSPOTS (by cumulative time)")
    print("=" * 80)
    
    stats = pstats.Stats(profiler)
    stats.strip_dirs()
    stats.sort_stats('cumulative')
    stats.print_stats(10)
    
    return {
        "token_count": token_count,
        "text_size_kb": text_size_kb,
        "elapsed_ms": elapsed_ms,
        "entity_count": entity_count,
        "relationship_count": relationship_count,
        "tokens_per_sec": token_count / (elapsed_ms / 1000),
        "entities_per_sec": entity_count / (elapsed_ms / 1000),
    }


if __name__ == "__main__":
    results = profile_generate_ontology()
    
    print("\n" + "=" * 80)
    print("PROFILING COMPLETE")
    print("=" * 80)
    print(f"\nKey Metrics:")
    print(f"  - Execution time: {results['elapsed_ms']:.2f} ms")
    print(f"  - Throughput: {results['tokens_per_sec']:.0f} tokens/sec")
    print(f"  - Entities extracted: {results['entity_count']}")
    print(f"  - Relationships inferred: {results['relationship_count']}")
    print(f"\nFiles generated:")
    print(f"  - profile_batch_262_generate_10k.prof (binary profile data)")
    print(f"  - profile_batch_262_generate_10k.txt (text report)")
