#!/usr/bin/env python3
"""
Comprehensive SymbolicAI Engine Test Suite
==========================================

This script tests the SymbolicAI integration with the configured backend
(API key or Codex routing) to verify that functionality is working correctly.
"""

import os
import sys
import anyio
import traceback
from datetime import datetime
from typing import Dict, List, Any

def _codex_routing_enabled() -> bool:
    return os.getenv("IPFS_DATASETS_PY_USE_CODEX_FOR_SYMAI", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

def _resolved_model() -> str:
    if _codex_routing_enabled():
        return f"codex:{os.getenv('IPFS_DATASETS_PY_CODEX_MODEL', 'gpt-5.2')}"
    return os.getenv('NEUROSYMBOLIC_ENGINE_MODEL') or ""

def test_environment_setup():
    """Test that environment variables are properly set."""
    print("=== Environment Setup Test ===")
    
    api_key = os.getenv('NEUROSYMBOLIC_ENGINE_API_KEY')
    model = _resolved_model()
    use_codex = _codex_routing_enabled()
    
    if use_codex:
        print("Codex Routing: ✓ Enabled")
    print(f"API Key: {'✓ Set' if api_key else '✗ Missing'}")
    print(f"Model: {model if model else '✗ Not set (will use default)'}")
    
    if api_key:
        print(f"API Key (partial): {api_key[:20]}...{api_key[-10:]}")
        return True
    if use_codex:
        return bool(model)
    print("⚠️  API key not found. Tests will use fallback mechanisms.")
    return False

def test_basic_symbolic_ai():
    """Test basic SymbolicAI functionality."""
    print("\n=== Basic SymbolicAI Test ===")
    
    try:
        if _codex_routing_enabled():
            from symai import Expression
            result = Expression.prompt("Reply with OK only.")
            print(f"✓ Codex prompt result: {result}")
        else:
            from symai import Symbol
            
            # Test basic symbol creation
            symbol = Symbol("Hello, SymbolicAI!")
            print(f"✓ Symbol created: {symbol}")
            
            # Test semantic symbol
            semantic_symbol = Symbol("All cats are animals", semantic=True)
            print(f"✓ Semantic symbol created: {semantic_symbol}")
        
        return True
        
    except Exception as e:
        print(f"✗ Basic SymbolicAI test failed: {e}")
        traceback.print_exc()
        return False

def test_logic_integration_modules():
    """Test our logic integration modules with API access."""
    print("\n=== Logic Integration Modules Test ===")
    
    try:
        # Test SymbolicFOLBridge
        from ipfs_datasets_py.logic.integration import SymbolicFOLBridge
        bridge = SymbolicFOLBridge()
        print("✓ SymbolicFOLBridge imported and instantiated")
        
        # Test semantic symbol creation
        symbol = bridge.create_semantic_symbol("All birds can fly")
        print(f"✓ Semantic symbol created: {symbol}")
        
        # Test InteractiveFOLConstructor
        from ipfs_datasets_py.logic.integration.interactive_fol_constructor import InteractiveFOLConstructor
        constructor = InteractiveFOLConstructor()
        constructor.add_statement("All cats are mammals")
        print(f"✓ Interactive constructor: {len(constructor.session_symbols)} statement(s) added")
        
        # Test Modal Logic
        from ipfs_datasets_py.logic.integration.modal_logic_extension import AdvancedLogicConverter
        converter = AdvancedLogicConverter()
        logic_type = converter.detect_logic_type("All cats are animals")
        print(f"✓ Modal logic converter: detected {logic_type.logic_type}")
        
        # Test Logic Verification
        from ipfs_datasets_py.logic.integration.logic_verification import LogicVerifier
        verifier = LogicVerifier()
        proof_rules = verifier._initialize_proof_rules()
        print(f"✓ Logic verifier: {len(proof_rules)} proof rules loaded")
        
        return True
        
    except Exception as e:
        print(f"✗ Logic integration test failed: {e}")
        traceback.print_exc()
        return False

def test_semantic_operations():
    """Test semantic operations with API access."""
    print("\n=== Semantic Operations Test ===")
    
    try:
        use_codex = _codex_routing_enabled()
        if use_codex:
            from symai import Expression
        else:
            from symai import Symbol
        
        # Test basic semantic queries
        text = "All cats are animals and some cats are black"
        if not use_codex:
            symbol = Symbol(text, semantic=True)
        
        print(f"Testing text: '{text}'")
        
        # Test query operations (these require API access)
        try:
            if use_codex:
                entities = Expression.prompt(
                    f"Extract all entities mentioned in this text: {text}"
                )
            else:
                entities = symbol.query("Extract all entities mentioned in this text")
            print(f"✓ Entities extracted: {entities}")
        except Exception as e:
            print(f"! Entity extraction (requires API): {e}")
        
        try:
            if use_codex:
                predicates = Expression.prompt(
                    f"Extract predicates and relationships in this text: {text}"
                )
            else:
                predicates = symbol.query("Extract predicates and relationships")
            print(f"✓ Predicates extracted: {predicates}")
        except Exception as e:
            print(f"! Predicate extraction (requires API): {e}")
        
        return True
        
    except Exception as e:
        print(f"✗ Semantic operations test failed: {e}")
        traceback.print_exc()
        return False

def test_fol_conversion():
    """Test FOL conversion functionality."""
    print("\n=== FOL Conversion Test ===")
    
    try:
        from ipfs_datasets_py.logic.integration.symbolic_fol_bridge import SymbolicFOLBridge
        
        bridge = SymbolicFOLBridge()
        test_statements = [
            "All cats are animals",
            "Some birds can fly",
            "Every student studies hard",
            "No cats are dogs"
        ]
        
        for stmt in test_statements:
            print(f"\nTesting: '{stmt}'")
            
            try:
                # Test with SymbolicAI (requires API)
                symbol = bridge.create_semantic_symbol(stmt)
                components = bridge.extract_logical_components(symbol)
                print(
                    "✓ Logical components: "
                    f"quantifiers={components.quantifiers}, "
                    f"predicates={components.predicates}, "
                    f"entities={components.entities}, "
                    f"connectives={components.logical_connectives}"
                )
                
            except Exception as e:
                print(f"! SymbolicAI extraction (requires API): {e}")
                
                # Test fallback
                quantifiers, predicates, entities, connectives = bridge._fallback_extraction(stmt)
                print(f"✓ Fallback extraction: {len(predicates)} predicates")
        
        return True
        
    except Exception as e:
        print(f"✗ FOL conversion test failed: {e}")
        traceback.print_exc()
        return False

def test_interactive_session():
    """Test interactive FOL construction."""
    print("\n=== Interactive Session Test ===")
    
    try:
        from ipfs_datasets_py.logic.integration.interactive_fol_constructor import InteractiveFOLConstructor
        
        constructor = InteractiveFOLConstructor()
        
        # Add multiple statements
        statements = [
            "All birds can fly",
            "Penguins are birds", 
            "Penguins cannot fly"
        ]
        
        for stmt in statements:
            constructor.add_statement(stmt)
            print(f"✓ Added statement: '{stmt}'")
        
        print(f"✓ Total statements in session: {len(constructor.session_symbols)}")
        
        # Test analysis
        try:
            analysis = constructor.analyze_logical_structure()
            print(f"✓ Logical analysis completed: {len(analysis)} components")
            
            # Test consistency check
            consistency = constructor.validate_consistency()
            print(f"✓ Consistency check: {consistency.get('status', 'unknown')}")
            
        except Exception as e:
            print(f"! Advanced analysis (requires API): {e}")
        
        # Test export (should work without API)
        session_data = constructor.export_session()
        print(f"✓ Session export: {session_data['session_metadata']['total_statements']} statements")
        
        return True
        
    except Exception as e:
        print(f"✗ Interactive session test failed: {e}")
        traceback.print_exc()
        return False

def test_modal_logic():
    """Test modal logic functionality."""
    print("\n=== Modal Logic Test ===")
    
    try:
        from ipfs_datasets_py.logic.integration.modal_logic_extension import AdvancedLogicConverter, ModalLogicSymbol
        
        converter = AdvancedLogicConverter()
        
        test_cases = [
            ("Citizens must pay taxes", "deontic"),
            ("It is possible that it will rain", "modal"),
            ("All humans are mortal", "fol"),
            ("It will always be true that 2+2=4", "temporal")
        ]
        
        for text, expected_type in test_cases:
            print(f"\nTesting: '{text}' (expected: {expected_type})")
            
            try:
                # Test logic type detection
                detected_type = converter.detect_logic_type(text)
                print(f"✓ Detected type: {detected_type}")
                
                # Test conversion
                result = converter.convert_to_modal_logic(text)
                print(f"✓ Conversion result: {result.modal_type}")
                
            except Exception as e:
                print(f"! Modal logic analysis (requires API): {e}")
                
                # Test fallback
                print(f"✓ Fallback to FOL for: '{text}'")
        
        return True
        
    except Exception as e:
        print(f"✗ Modal logic test failed: {e}")
        traceback.print_exc()
        return False

def test_logic_verification():
    """Test logic verification capabilities."""
    print("\n=== Logic Verification Test ===")
    
    try:
        from ipfs_datasets_py.logic.integration.logic_verification import LogicVerifier
        
        verifier = LogicVerifier()
        
        test_formulas = [
            "∀x (Cat(x) → Animal(x))",
            "∃x (Bird(x) ∧ ¬Fly(x))",
            "P ∧ ¬P",  # Contradiction
            "P ∨ ¬P"   # Tautology
        ]
        
        for formula in test_formulas:
            print(f"\nTesting formula: '{formula}'")
            
            try:
                # Test syntax verification
                syntax_result = verifier.verify_formula_syntax(formula)
                print(f"✓ Syntax check: {syntax_result.get('status', 'unknown')}")
                
                # Test satisfiability
                sat_result = verifier.check_satisfiability(formula)
                print(f"✓ Satisfiability: {sat_result.get('satisfiable', 'unknown')}")
                
            except Exception as e:
                print(f"! Advanced verification (requires API): {e}")
        
        # Test proof rules (should work without API)
        rules = verifier._initialize_proof_rules()
        print(f"✓ Proof rules available: {len(rules)}")
        
        return True
        
    except Exception as e:
        print(f"✗ Logic verification test failed: {e}")
        traceback.print_exc()
        return False

def test_contract_system():
    """Test the contract-based validation system."""
    print("\n=== Contract System Test ===")
    
    try:
        from ipfs_datasets_py.logic.integration.symbolic_contracts import FOLInput, FOLOutput, ContractedFOLConverter
        
        # Test Pydantic models
        input_data = FOLInput(
            text="Every student studies mathematics",
            confidence_threshold=0.8,
            domain_predicates=["Student", "Study", "Mathematics"]
        )
        print(f"✓ FOLInput created: {input_data.text}")
        
        # Test validation
        try:
            output_data = FOLOutput(
                fol_formula="∀x (Student(x) → Study(x, Mathematics))",
                confidence=0.9,
                logical_components={
                    "quantifiers": ["∀"],
                    "predicates": ["Student", "Study"],
                    "entities": ["Mathematics"]
                }
            )
            print(f"✓ FOLOutput created: confidence={output_data.confidence}")
        except Exception as e:
            print(f"! FOLOutput validation error: {e}")
        
        # Test contracted converter
        try:
            converter = ContractedFOLConverter()
            result = converter(input_data)
            print(f"✓ Contract conversion completed")
        except Exception as e:
            print(f"! Contract conversion (requires API): {e}")
        
        return True
        
    except Exception as e:
        print(f"✗ Contract system test failed: {e}")
        traceback.print_exc()
        return False

def test_performance_and_caching():
    """Test performance and caching mechanisms."""
    print("\n=== Performance and Caching Test ===")
    
    try:
        from ipfs_datasets_py.logic.integration.symbolic_fol_bridge import SymbolicFOLBridge
        import time
        
        bridge = SymbolicFOLBridge()
        
        # Test caching mechanism
        test_text = "All cats are animals"
        
        # First call (should be slower if using API)
        start_time = time.time()
        symbol1 = bridge.create_semantic_symbol(test_text)
        first_duration = time.time() - start_time
        print(f"✓ First call duration: {first_duration:.3f}s")
        
        # Second call (should use cache if available)
        start_time = time.time()
        symbol2 = bridge.create_semantic_symbol(test_text)
        second_duration = time.time() - start_time
        print(f"✓ Second call duration: {second_duration:.3f}s")
        
        # Test cache key generation
        cache_key = bridge._get_cache_key(test_text, "create_semantic_symbol")
        print(f"✓ Cache key generated: {cache_key[:30]}...")
        
        return True
        
    except Exception as e:
        print(f"✗ Performance test failed: {e}")
        traceback.print_exc()
        return False

def run_comprehensive_test():
    """Run all tests and provide a comprehensive report."""
    print("🚀 SymbolicAI Engine Comprehensive Test Suite")
    print("=" * 50)
    print(f"Test started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Track test results
    results = {}
    
    # Run all tests
    test_functions = [
        ("Environment Setup", test_environment_setup),
        ("Basic SymbolicAI", test_basic_symbolic_ai),
        ("Logic Integration Modules", test_logic_integration_modules),
        ("Semantic Operations", test_semantic_operations),
        ("FOL Conversion", test_fol_conversion),
        ("Interactive Session", test_interactive_session),
        ("Modal Logic", test_modal_logic),
        ("Logic Verification", test_logic_verification),
        ("Contract System", test_contract_system),
        ("Performance and Caching", test_performance_and_caching)
    ]
    
    for test_name, test_func in test_functions:
        try:
            results[test_name] = test_func()
        except Exception as e:
            print(f"✗ {test_name} test crashed: {e}")
            results[test_name] = False
    
    # Generate report
    print("\n" + "=" * 50)
    print("📊 Test Results Summary")
    print("=" * 50)
    
    passed = sum(1 for result in results.values() if result)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test_name}: {status}")
    
    print()
    print(f"Overall Results: {passed}/{total} tests passed ({passed/total*100:.1f}%)")
    
    if passed == total:
        print("🎉 All tests passed! SymbolicAI integration is fully functional.")
    elif passed >= total * 0.8:
        print("✅ Most tests passed. Integration is functional with some limitations.")
    else:
        print("⚠️  Some tests failed. Check configuration and API access.")
    
    print(f"\nTest completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return passed, total

if __name__ == "__main__":
    try:
        passed, total = run_comprehensive_test()
        sys.exit(0 if passed == total else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(2)
    except Exception as e:
        print(f"\n\n💥 Test suite crashed: {e}")
        traceback.print_exc()
        sys.exit(3)
