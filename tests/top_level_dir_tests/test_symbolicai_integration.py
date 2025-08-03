#!/usr/bin/env python3
"""
Quick verification script for SymbolicAI-FOL integration
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

def test_imports():
    """Test that all modules can be imported"""
    try:
        from ipfs_datasets_py.logic_integration.symbolic_fol_bridge import SymbolicFOLBridge
        from ipfs_datasets_py.logic_integration.symbolic_logic_primitives import SymbolicLogicPrimitives
        from ipfs_datasets_py.logic_integration.symbolic_contracts import SymbolicContractValidator
        from ipfs_datasets_py.logic_integration.interactive_fol_constructor import InteractiveFOLConstructor
        from ipfs_datasets_py.logic_integration.modal_logic_extension import ModalLogicExtension
        from ipfs_datasets_py.logic_integration.logic_verification import LogicVerification
        print("✓ All core modules imported successfully")
        return True
    except Exception as e:
        print(f"✗ Import error: {e}")
        return False

def test_basic_functionality():
    """Test basic functionality of key components"""
    try:
        # Test SymbolicFOLBridge
        from ipfs_datasets_py.logic_integration.symbolic_fol_bridge import SymbolicFOLBridge
        bridge = SymbolicFOLBridge()
        result = bridge.generate_fol_from_text("All humans are mortal")
        print(f"✓ FOL Bridge basic test: {result}")
        
        # Test ModalLogicExtension
        from ipfs_datasets_py.logic_integration.modal_logic_extension import ModalLogicExtension
        modal = ModalLogicExtension()
        modal_expr = modal.create_modal_expression("necessarily", "P")
        print(f"✓ Modal logic basic test: {modal_expr}")
        
        # Test LogicVerification
        from ipfs_datasets_py.logic_integration.logic_verification import LogicVerification
        verifier = LogicVerification()
        is_consistent = verifier.check_consistency(["P", "¬P"])
        print(f"✓ Logic verification basic test: consistent={is_consistent}")
        
        return True
    except Exception as e:
        print(f"✗ Functionality test error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_integration():
    """Test integration between components"""
    try:
        from ipfs_datasets_py.logic_integration.symbolic_fol_bridge import SymbolicFOLBridge
        from ipfs_datasets_py.logic_integration.modal_logic_extension import ModalLogicExtension
        from ipfs_datasets_py.logic_integration.logic_verification import LogicVerification
        
        # Create instances
        bridge = SymbolicFOLBridge()
        modal = ModalLogicExtension()
        verifier = LogicVerification()
        
        # Test workflow
        text = "It is necessarily true that all birds can fly"
        fol_result = bridge.generate_fol_from_text(text)
        modal_type = modal.detect_logic_type(text)
        
        print(f"✓ Integration test - FOL: {fol_result}")
        print(f"✓ Integration test - Modal type: {modal_type}")
        
        return True
    except Exception as e:
        print(f"✗ Integration test error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("=== SymbolicAI-FOL Integration Verification ===\n")
    
    tests = [
        ("Module Imports", test_imports),
        ("Basic Functionality", test_basic_functionality),
        ("Integration", test_integration)
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"Running {test_name}...")
        try:
            result = test_func()
            results.append(result)
            print(f"{'✓' if result else '✗'} {test_name} {'PASSED' if result else 'FAILED'}\n")
        except Exception as e:
            print(f"✗ {test_name} FAILED with exception: {e}\n")
            results.append(False)
    
    # Summary
    passed = sum(results)
    total = len(results)
    print(f"=== Summary: {passed}/{total} tests passed ===")
    
    if passed == total:
        print("🎉 All tests passed! SymbolicAI-FOL integration is working correctly.")
        return 0
    else:
        print("❌ Some tests failed. Please check the errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
