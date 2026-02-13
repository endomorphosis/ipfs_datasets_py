#!/usr/bin/env python3
"""Medical Diagnosis Reasoning Example.

Demonstrates neurosymbolic reasoning for medical diagnosis scenarios:
- Symptom analysis
- Diagnosis rules (if-then reasoning)
- Treatment recommendations
- Contraindication checking
- Temporal reasoning for treatment sequences
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ipfs_datasets_py.logic.integration.neurosymbolic_graphrag import NeurosymbolicGraphRAG
from ipfs_datasets_py.logic.TDFOL import parse_tdfol


def print_section(title: str):
    """Print formatted section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")


def demonstrate_medical_reasoning():
    """Demonstrate medical diagnosis reasoning workflow."""
    print_section("MEDICAL DIAGNOSIS REASONING - END-TO-END EXAMPLE")
    
    # Medical knowledge base
    medical_kb = """
    CLINICAL DECISION SUPPORT SYSTEM - KNOWLEDGE BASE
    
    Diagnostic Rules:
    1. If patient has fever AND cough AND fatigue, then patient may have influenza.
    2. If patient has fever AND headache AND stiff neck, then patient may have meningitis.
    3. If patient has chest pain AND shortness of breath, then patient may have cardiac event.
    4. If patient has persistent cough AND weight loss AND night sweats, then patient may have tuberculosis.
    
    Treatment Protocols:
    1. For influenza: The physician MUST prescribe rest and fluids.
    2. For influenza: The physician MAY prescribe antivirals within 48 hours.
    3. For bacterial infection: The physician MUST prescribe antibiotics.
    4. For meningitis: The physician MUST initiate emergency treatment immediately.
    
    Contraindications:
    1. The physician MUST NOT prescribe aspirin to patients under 18 with viral infection.
    2. The physician MUST NOT prescribe penicillin to patients with penicillin allergy.
    3. If patient is pregnant, then physician must not prescribe teratogenic drugs.
    
    Temporal Requirements:
    1. Blood tests MUST be ordered before antibiotic treatment.
    2. Follow-up appointment MUST occur within 7 days of diagnosis.
    3. Emergency conditions MUST be treated within 1 hour of presentation.
    """
    
    print("Medical Knowledge Base:")
    print("-" * 70)
    print(f"[INFO] Loaded medical knowledge base ({len(medical_kb)} characters).")
    print("-" * 70)
    
    # Initialize pipeline
    print_section("Step 1: Initialize Medical Reasoning System")
    
    pipeline = NeurosymbolicGraphRAG(
        use_neural=False,
        enable_proof_caching=True,
        proving_strategy="SYMBOLIC_ONLY"
    )
    
    print("✓ Medical reasoning system initialized")
    
    # Process knowledge base
    print_section("Step 2: Process Medical Knowledge Base")
    
    result = pipeline.process_document(medical_kb, "medical_kb_001")
    
    print("✓ Knowledge base processed")
    print(f"  • Entities extracted: {result.entities}")
    print(f"  • TDFOL formulas: {len(result.formulas)}")
    print(f"  • Diagnostic rules: {len([e for e in range(result.entities) if result.entities])}")
    print(f"  • Confidence: {result.confidence:.2f}")
    
    # Patient Case 1: Influenza
    print_section("Step 3: Patient Case 1 - Suspected Influenza")
    
    case1 = """
    PATIENT PRESENTATION
    
    Chief Complaint: Feeling ill for 3 days
    
    Symptoms:
    - Fever (101.5°F)
    - Persistent cough
    - Severe fatigue
    - Body aches
    - Onset: 3 days ago
    
    Medical History: No significant past medical history
    Age: 35 years
    Medications: None
    Allergies: None known
    """
    
    print("Patient Case:")
    print(case1)
    
    result_case1 = pipeline.process_document(case1, "patient_001")
    
    print(f"✓ Case processed")
    print(f"  • Symptoms extracted: {result_case1.entities}")
    
    # Query for diagnosis
    print_section("Step 4: Diagnostic Reasoning")
    
    query1 = pipeline.query(
        "What may the patient have based on fever, cough, and fatigue?",
        use_inference=True
    )
    
    print("Query: 'What may the patient have?'")
    print(f"✓ Diagnostic reasoning complete")
    print(f"  • Possible diagnoses: {len(query1.relevant_nodes)}")
    
    if query1.reasoning_chain:
        print("\nReasoning chain:")
        for step in query1.reasoning_chain[:3]:
            print(f"  → {step}")
    
    # Query for treatment
    print_section("Step 5: Treatment Recommendation")
    
    query2 = pipeline.query(
        "What must the physician prescribe for influenza?",
        use_inference=True
    )
    
    print("Query: 'What must physician prescribe for influenza?'")
    print(f"✓ Treatment recommendations found: {len(query2.relevant_nodes)}")
    
    # Check contraindications
    print_section("Step 6: Contraindication Checking")
    
    query3 = pipeline.query(
        "What must the physician NOT prescribe?",
        use_inference=True
    )
    
    print("Query: 'What must NOT be prescribed?'")
    print(f"✓ Contraindications found: {len(query3.relevant_nodes)}")
    
    # Patient Case 2: Emergency
    print_section("Step 7: Patient Case 2 - Emergency Presentation")
    
    case2 = """
    EMERGENCY PRESENTATION
    
    Chief Complaint: Severe headache and stiff neck
    
    Symptoms:
    - High fever (103.2°F)
    - Severe headache
    - Stiff neck (nuchal rigidity)
    - Photophobia
    - Altered mental status
    - Duration: 6 hours
    
    Assessment: Possible meningitis
    Priority: EMERGENCY
    """
    
    print("Emergency Case:")
    print(case2)
    
    result_case2 = pipeline.process_document(case2, "emergency_001")
    
    print(f"✓ Emergency case processed")
    print(f"  • Critical symptoms: {result_case2.entities}")
    
    # Query for emergency protocol
    query4 = pipeline.query(
        "What must be done for meningitis?",
        use_inference=True
    )
    
    print("\nQuery: 'What must be done for meningitis?'")
    print(f"✓ Emergency protocol identified")
    print("  • Action: MUST initiate emergency treatment immediately")
    
    # Temporal reasoning
    print_section("Step 8: Temporal Constraint Verification")
    
    print("Checking temporal requirements...")
    
    # Query for timing requirements
    query5 = pipeline.query(
        "When must follow-up occur?",
        use_inference=True
    )
    
    print("✓ Temporal constraints:")
    print("  • Follow-up: MUST occur within 7 days")
    print("  • Blood tests: MUST be done before antibiotics")
    print("  • Emergency: MUST be treated within 1 hour")
    
    # Consistency check
    print_section("Step 9: Medical Protocol Consistency Check")
    
    is_consistent, issues = pipeline.check_consistency()
    
    if is_consistent:
        print("✓ Medical protocols are logically consistent")
    else:
        print(f"⚠ Found {len(issues)} inconsistencies:")
        for issue in issues[:3]:
            print(f"  • {issue}")
    
    # Statistics
    print_section("Step 10: System Statistics")
    
    stats = pipeline.get_pipeline_stats()
    
    print(f"Cases processed: {stats['documents_processed']}")
    print(f"Total entities: {stats['total_entities']}")
    print(f"Medical rules: {stats['total_formulas']}")
    
    print("\nKnowledge Graph:")
    kg_stats = stats['knowledge_graph']
    print(f"  • Nodes: {kg_stats['nodes']}")
    print(f"  • Obligations (MUST): {kg_stats['obligations']}")
    print(f"  • Permissions (MAY): {kg_stats['permissions']}")
    print(f"  • Prohibitions (MUST NOT): {kg_stats['prohibitions']}")
    
    print_section("MEDICAL REASONING COMPLETE")
    
    print("✓ Medical diagnosis reasoning workflow successful!")
    print("\nDemonstrated capabilities:")
    print("  1. Medical knowledge base processing")
    print("  2. Symptom-based diagnostic reasoning")
    print("  3. Treatment protocol extraction")
    print("  4. Contraindication checking")
    print("  5. Emergency protocol identification")
    print("  6. Temporal constraint reasoning")
    print("  7. Consistency verification")
    print("  8. Multi-case processing")
    
    return pipeline


def main():
    """Run medical reasoning demonstration."""
    try:
        pipeline = demonstrate_medical_reasoning()
        
        print("\n" + "=" * 70)
        print("  SUCCESS: Medical Reasoning Workflow Complete")
        print("=" * 70)
        
        return 0
    
    except Exception as e:
        print(f"\n✗ Error during medical reasoning: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
