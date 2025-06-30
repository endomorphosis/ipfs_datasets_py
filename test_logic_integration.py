#!/usr/bin/env python3
"""
Quick test script for SymbolicAI Logic Integration
"""

def test_components():
    """Test the new logic integration components."""
    print("Testing SymbolicAI Logic Integration Components...")
    print("=" * 50)
    
    # Test modal logic extension
    try:
        from ipfs_datasets_py.logic_integration.modal_logic_extension import (
            ModalLogicSymbol, AdvancedLogicConverter
        )
        print("✅ Modal logic extension imported successfully")
        
        converter = AdvancedLogicConverter()
        result = converter.detect_logic_type('All cats are animals')
        print(f"✅ Modal logic detection: {result.logic_type} (confidence: {result.confidence:.2f})")
        
        modal_result = converter.convert_to_modal_logic('Citizens must pay taxes')
        print(f"✅ Modal conversion: {modal_result.modal_type} - {modal_result.formula[:50]}...")
        
        # Test modal operators
        symbol = ModalLogicSymbol("All birds fly")
        necessary = symbol.necessarily()
        print(f"✅ Modal operators: {necessary.value}")
        
    except Exception as e:
        print(f"❌ Modal logic extension error: {e}")
        import traceback
        traceback.print_exc()
    
    print()
    
    # Test logic verification
    try:
        from ipfs_datasets_py.logic_integration.logic_verification import LogicVerifier
        print("✅ Logic verification imported successfully")
        
        verifier = LogicVerifier()
        stats = verifier.get_statistics()
        print(f"✅ Logic verifier initialized with {stats['axiom_count']} axioms")
        
        result = verifier.check_consistency(['P', 'P → Q'])
        print(f"✅ Consistency check: {result.is_consistent} (method: {result.method_used})")
        
        entailment = verifier.check_entailment(['P', 'P → Q'], 'Q')
        print(f"✅ Entailment check: {entailment.entails} (confidence: {entailment.confidence:.2f})")
        
        # Test proof generation
        proof = verifier.generate_proof(['P', 'P → Q'], 'Q')
        print(f"✅ Proof generation: {proof.is_valid} ({len(proof.steps)} steps)")
        
    except Exception as e:
        print(f"❌ Logic verification error: {e}")
        import traceback
        traceback.print_exc()
    
    print()
    
    # Test integration
    try:
        from ipfs_datasets_py.logic_integration.symbolic_fol_bridge import SymbolicFOLBridge
        from ipfs_datasets_py.logic_integration.modal_logic_extension import AdvancedLogicConverter
        from ipfs_datasets_py.logic_integration.logic_verification import LogicVerifier
        
        bridge = SymbolicFOLBridge()
        modal_converter = AdvancedLogicConverter()
        verifier = LogicVerifier()
        
        # Complete workflow test
        text = "All humans are mortal and Socrates is human"
        
        # Step 1: Bridge conversion
        symbol = bridge.create_semantic_symbol(text)
        components = bridge.extract_logical_components(symbol)
        print(f"✅ Bridge extraction: {len(components.get('entities', []))} entities found")
        
        # Step 2: Modal classification
        classification = modal_converter.detect_logic_type(text)
        print(f"✅ Modal classification: {classification.logic_type}")
        
        # Step 3: Verification
        consistency = verifier.check_consistency([text])
        print(f"✅ Verification: consistent={consistency.is_consistent}")
        
        print("\n🎉 Complete integration workflow successful!")
        
    except Exception as e:
        print(f"❌ Integration test error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_components()
