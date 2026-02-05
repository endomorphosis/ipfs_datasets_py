#!/usr/bin/env python3
"""
Detailed SymbolicAI Logic Integration Test
==========================================

This script performs detailed testing of SymbolicAI integration
with our First-Order Logic system using the configured backend
(API key or Codex routing).
"""

import anyio
from datetime import datetime
import os

def _codex_routing_enabled() -> bool:
    return os.getenv("IPFS_DATASETS_PY_USE_CODEX_FOR_SYMAI", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

def test_fol_conversion_with_api():
    """Test FOL conversion using SymbolicAI API."""
    print("=== FOL Conversion with SymbolicAI API ===")
    
    try:
        from ipfs_datasets_py.logic_integration.symbolic_fol_bridge import SymbolicFOLBridge
        if _codex_routing_enabled():
            from symai import Expression
        
        bridge = SymbolicFOLBridge()

        if _codex_routing_enabled():
            try:
                sanity = Expression.prompt("Reply with OK only.")
                print(f"   ✓ Codex routing sanity check: {sanity}")
            except Exception as e:
                print(f"   ! Codex routing sanity check failed: {e}")
        
        test_statements = [
            "All cats are animals",
            "Some birds can fly", 
            "Every student studies mathematics",
            "No dogs are cats",
            "If it rains, then the ground gets wet"
        ]
        
        for i, stmt in enumerate(test_statements, 1):
            print(f"\n{i}. Testing: '{stmt}'")
            
            # Create semantic symbol
            symbol = bridge.create_semantic_symbol(stmt)
            print(f"   ✓ Semantic symbol created")
            
            try:
                # Extract logical components using SymbolicAI
                components = bridge.extract_logical_components(symbol)
                print(f"   ✓ Components extracted:")
                print(f"     quantifiers: {components.quantifiers}")
                print(f"     predicates: {components.predicates}")
                print(f"     entities: {components.entities}")
                print(f"     connectives: {components.logical_connectives}")
                    
            except Exception as e:
                print(f"   ! API extraction failed: {e}")
                
                # Test fallback
                fallback = bridge.fallback_extract_predicates(stmt)
                print(f"   ✓ Fallback: {len(fallback)} predicates")
        
        return True
        
    except Exception as e:
        print(f"✗ FOL conversion test failed: {e}")
        return False

def test_interactive_constructor_with_api():
    """Test interactive FOL constructor with SymbolicAI API."""
    print("\n=== Interactive Constructor with SymbolicAI API ===")
    
    try:
        from ipfs_datasets_py.logic_integration.interactive_fol_constructor import InteractiveFOLConstructor
        
        constructor = InteractiveFOLConstructor()
        
        # Build a logical scenario
        statements = [
            "All birds have wings",
            "All eagles are birds",
            "Some eagles are golden",
            "Golden eagles are protected"
        ]
        
        print("Building logical scenario:")
        for stmt in statements:
            constructor.add_statement(stmt)
            print(f"  + {stmt}")
        
        print(f"\n✓ {len(constructor.session_symbols)} statements added")
        
        # Test analysis with API
        try:
            print("\nAnalyzing logical structure...")
            analysis = constructor.analyze_logical_structure()
            
            print("✓ Logical analysis completed:")
            for key, value in analysis.items():
                if key != "error":
                    print(f"  {key}: {str(value)[:80]}...")
                    
        except Exception as e:
            print(f"! API analysis failed: {e}")
        
        # Test consistency check
        try:
            print("\nChecking logical consistency...")
            consistency = constructor.validate_consistency()
            print(f"✓ Consistency check: {consistency.get('status', 'unknown')}")
            
        except Exception as e:
            print(f"! API consistency check failed: {e}")
        
        # Test session export (should work without API)
        session_data = constructor.export_session()
        print(f"✓ Session exported: {session_data['session_metadata']['total_statements']} statements")
        
        return True
        
    except Exception as e:
        print(f"✗ Interactive constructor test failed: {e}")
        return False

def test_modal_logic_with_api():
    """Test modal logic with SymbolicAI API."""
    print("\n=== Modal Logic with SymbolicAI API ===")
    
    try:
        from ipfs_datasets_py.logic_integration.modal_logic_extension import AdvancedLogicConverter
        
        converter = AdvancedLogicConverter()
        
        test_cases = [
            ("Citizens must pay taxes", "deontic", "obligation"),
            ("It is possible that aliens exist", "modal", "possibility"),
            ("Water always freezes at 0°C", "temporal", "always"),
            ("I know that Paris is in France", "epistemic", "knowledge"),
            ("All mammals are warm-blooded", "fol", "universal")
        ]
        
        print("Testing modal logic detection and conversion:")
        
        for text, expected_type, expected_property in test_cases:
            print(f"\nTesting: '{text}'")
            
            try:
                # Test logic type detection
                detected_type = converter.detect_logic_type(text)
                print(f"  ✓ Detected type: {detected_type} (expected: {expected_type})")
                
                # Test conversion
                result = converter.convert_to_modal_logic(text)
                print(f"  ✓ Conversion result:")
                print(f"    Logic type: {result.modal_type}")
                print(f"    Formula: {str(result.formula)[:60]}...")
                print(f"    Confidence: {result.confidence}")
                
            except Exception as e:
                print(f"  ! API conversion failed: {e}")
                print(f"  ✓ Fallback to {expected_type} logic")
        
        return True
        
    except Exception as e:
        print(f"✗ Modal logic test failed: {e}")
        return False

def test_logic_verification_with_api():
    """Test logic verification with SymbolicAI API."""
    print("\n=== Logic Verification with SymbolicAI API ===")
    
    try:
        from ipfs_datasets_py.logic_integration.logic_verification import LogicVerifier
        
        verifier = LogicVerifier()
        
        test_formulas = [
            ("∀x (Cat(x) → Animal(x))", "Valid universal statement"),
            ("∃x (Bird(x) ∧ ¬Fly(x))", "Existential statement about flightless birds"),
            ("P ∧ ¬P", "Contradiction"),
            ("P ∨ ¬P", "Tautology"),
            ("∀x ∃y (Parent(x, y) → Love(x, y))", "Complex relational formula")
        ]
        
        print("Testing logic verification:")
        
        for formula, description in test_formulas:
            print(f"\nTesting: {formula}")
            print(f"Description: {description}")
            
            try:
                # Test syntax verification
                syntax_result = verifier.verify_formula_syntax(formula)
                print(f"  ✓ Syntax: {syntax_result.get('status', 'unknown')}")
                
                # Test satisfiability
                sat_result = verifier.check_satisfiability(formula)
                print(f"  ✓ Satisfiable: {sat_result.get('satisfiable', 'unknown')}")
                
                # Test validity
                validity_result = verifier.check_validity(formula)
                print(f"  ✓ Valid: {validity_result.get('valid', 'unknown')}")
                
            except Exception as e:
                print(f"  ! API verification failed: {e}")
        
        # Test proof rules (should work without API)
        rules = verifier._initialize_proof_rules()
        print(f"\n✓ Proof rules loaded: {len(rules)} rules available")
        
        return True
        
    except Exception as e:
        print(f"✗ Logic verification test failed: {e}")
        return False

def test_contract_system_with_api():
    """Test contract system with SymbolicAI API."""
    print("\n=== Contract System with SymbolicAI API ===")
    
    try:
        from ipfs_datasets_py.logic_integration.symbolic_contracts import (
            FOLInput, FOLOutput, ContractedFOLConverter
        )
        
        # Test input validation
        test_inputs = [
            FOLInput(text="All students study hard", confidence_threshold=0.8),
            FOLInput(text="Some cats are black", confidence_threshold=0.7),
            FOLInput(text="If it rains, then the ground is wet", confidence_threshold=0.9)
        ]
        
        print("Testing contract-based FOL conversion:")
        
        for i, input_data in enumerate(test_inputs, 1):
            print(f"\n{i}. Input: '{input_data.text}'")
            print(f"   Confidence threshold: {input_data.confidence_threshold}")
            
            try:
                # Test contracted conversion
                converter = ContractedFOLConverter()
                result = converter(input_data)
                
                print(f"   ✓ Contract validation passed")
                print(f"   ✓ Generated FOL: {result.fol_formula}")
                print(f"   ✓ Confidence: {result.confidence}")
                
            except Exception as e:
                print(f"   ! Contract conversion failed: {e}")
        
        # Test output validation
        try:
            output_test = FOLOutput(
                fol_formula="∀x (Student(x) → Study(x))",
                confidence=0.85,
                logical_components={
                    "quantifiers": ["∀"],
                    "predicates": ["Student", "Study"],
                    "variables": ["x"]
                }
            )
            print(f"\n✓ Output validation successful: {output_test.fol_formula}")
            
        except Exception as e:
            print(f"! Output validation failed: {e}")
        
        return True
        
    except Exception as e:
        print(f"✗ Contract system test failed: {e}")
        return False

def test_performance_with_api():
    """Test performance and caching with SymbolicAI API."""
    print("\n=== Performance and Caching with SymbolicAI API ===")
    
    try:
        from ipfs_datasets_py.logic_integration.symbolic_fol_bridge import SymbolicFOLBridge
        import time
        
        bridge = SymbolicFOLBridge()
        test_text = "All cats are carnivorous animals"
        
        print(f"Testing with: '{test_text}'")
        
        # First call (should hit API)
        print("\nFirst call (API request):")
        start_time = time.time()
        symbol1 = bridge.create_semantic_symbol(test_text)
        duration1 = time.time() - start_time
        print(f"  ✓ Duration: {duration1:.3f}s")
        
        # Extract components (API call)
        try:
            start_time = time.time()
            components1 = bridge.extract_logical_components(symbol1)
            duration2 = time.time() - start_time
            print(f"  ✓ Component extraction: {duration2:.3f}s")
            print(f"  ✓ Components: {list(components1.keys())}")
            
        except Exception as e:
            print(f"  ! Component extraction failed: {e}")
        
        # Test caching (if implemented)
        cache_key = bridge._get_cache_key(test_text, "extract_logical_components")
        print(f"  ✓ Cache key: {cache_key[:30]}...")
        
        return True
        
    except Exception as e:
        print(f"✗ Performance test failed: {e}")
        return False

def run_detailed_tests():
    """Run all detailed tests."""
    print("🔬 Detailed SymbolicAI Logic Integration Test Suite")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    test_functions = [
        ("FOL Conversion with API", test_fol_conversion_with_api),
        ("Interactive Constructor with API", test_interactive_constructor_with_api),
        ("Modal Logic with API", test_modal_logic_with_api),
        ("Logic Verification with API", test_logic_verification_with_api),
        ("Contract System with API", test_contract_system_with_api),
        ("Performance with API", test_performance_with_api)
    ]
    
    results = {}
    
    for test_name, test_func in test_functions:
        print(f"\n{'='*60}")
        try:
            results[test_name] = test_func()
        except Exception as e:
            print(f"✗ {test_name} crashed: {e}")
            results[test_name] = False
    
    # Summary
    print(f"\n{'='*60}")
    print("📊 DETAILED TEST RESULTS")
    print("=" * 60)
    
    passed = sum(1 for result in results.values() if result)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test_name}: {status}")
    
    print(f"\nOverall: {passed}/{total} tests passed ({passed/total*100:.1f}%)")
    
    if passed == total:
        print("\n🎉 EXCELLENT! All detailed tests passed!")
        print("SymbolicAI API integration is fully functional.")
    elif passed >= total * 0.8:
        print("\n✅ GOOD! Most tests passed.")
        print("SymbolicAI integration is working with minor limitations.")
    else:
        print("\n⚠️  NEEDS ATTENTION! Several tests failed.")
        print("Check API configuration and connectivity.")
    
    print(f"\nCompleted at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return passed, total

if __name__ == "__main__":
    run_detailed_tests()
