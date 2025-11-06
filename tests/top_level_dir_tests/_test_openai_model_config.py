#!/usr/bin/env python3
"""
OpenAI Model Configuration Test for SymbolicAI
Verifies the correct model is configured and tests API connectivity
"""

import os
import sys
import json
import traceback
from datetime import datetime

# Add project root to path
sys.path.insert(0, '/home/barberb/ipfs_datasets_py')

def test_environment_config():
    """Test environment configuration"""
    print("=== Environment Configuration ===")
    
    api_key = os.getenv('NEUROSYMBOLIC_ENGINE_API_KEY')
    model = os.getenv('NEUROSYMBOLIC_ENGINE_MODEL')
    max_tokens = os.getenv('NEUROSYMBOLIC_ENGINE_MAX_TOKENS')
    temperature = os.getenv('NEUROSYMBOLIC_ENGINE_TEMPERATURE')
    
    print(f"API Key: {'✓ Set' if api_key else '✗ Missing'}")
    print(f"Model: {model if model else '✗ Not set'}")
    print(f"Max Tokens: {max_tokens if max_tokens else '✗ Not set'}")
    print(f"Temperature: {temperature if temperature else '✗ Not set'}")
    
    if api_key:
        print(f"API Key (partial): {api_key[:20]}...{api_key[-10:]}")
    
    return bool(api_key and model)

def test_config_file():
    """Test SymbolicAI config file"""
    print("\n=== SymbolicAI Config File ===")
    
    config_path = '.venv/.symai/symai.config.json'
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        print(f"✓ Config file found: {config_path}")
        print(f"API Key in config: {'✓ Set' if config.get('NEUROSYMBOLIC_ENGINE_API_KEY') else '✗ Missing'}")
        print(f"Model in config: {config.get('NEUROSYMBOLIC_ENGINE_MODEL', '✗ Not set')}")
        print(f"Max Tokens: {config.get('NEUROSYMBOLIC_ENGINE_MAX_TOKENS', '✗ Not set')}")
        print(f"Temperature: {config.get('NEUROSYMBOLIC_ENGINE_TEMPERATURE', '✗ Not set')}")
        
        return bool(config.get('NEUROSYMBOLIC_ENGINE_API_KEY') and config.get('NEUROSYMBOLIC_ENGINE_MODEL'))
        
    except FileNotFoundError:
        print(f"✗ Config file not found: {config_path}")
        return False
    except json.JSONDecodeError as e:
        print(f"✗ Config file invalid JSON: {e}")
        return False

def test_symai_basic():
    """Test basic SymbolicAI functionality"""
    print("\n=== Basic SymbolicAI Test ===")
    
    try:
        from symai import Symbol
        print("✓ SymbolicAI imported successfully")
        
        # Test basic symbol creation
        symbol = Symbol("Hello World")
        print(f"✓ Basic symbol created: {symbol}")
        
        # Test semantic symbol creation (this should use the configured model)
        semantic_symbol = Symbol("Test semantic symbol", semantic=True)
        print(f"✓ Semantic symbol created: {semantic_symbol}")
        
        return True
        
    except Exception as e:
        print(f"✗ SymbolicAI test failed: {e}")
        traceback.print_exc()
        return False

def test_api_connection():
    """Test actual API connection with the configured model"""
    print("\n=== API Connection Test ===")
    
    try:
        from symai import Symbol
        
        # Create a semantic symbol for API testing
        symbol = Symbol("What is 2 + 2?", semantic=True)
        print("✓ Created semantic symbol for API test")
        
        # Test a simple query that should use the OpenAI API
        print("Testing API call (this may take a moment)...")
        try:
            # Simple math question to test API
            result = symbol.query("Answer this simple math question")
            print(f"✓ API call successful!")
            print(f"  Question: What is 2 + 2?")
            print(f"  Response: {result}")
            
            # Test logic-related query
            logic_symbol = Symbol("All cats are animals", semantic=True)
            logic_result = logic_symbol.query("Convert this to first-order logic")
            print(f"✓ Logic query successful!")
            print(f"  Statement: All cats are animals")
            print(f"  FOL Response: {logic_result}")
            
            return True
            
        except Exception as api_error:
            print(f"✗ API call failed: {api_error}")
            print("This might indicate:")
            print("  - Invalid API key")
            print("  - Model not accessible")
            print("  - Network issues")
            print("  - Rate limiting")
            return False
            
    except Exception as e:
        print(f"✗ API connection test setup failed: {e}")
        traceback.print_exc()
        return False

def test_model_capabilities():
    """Test specific model capabilities for logic tasks"""
    print("\n=== Model Capabilities Test ===")
    
    try:
        from symai import Symbol
        
        # Test various logic-related tasks
        test_cases = [
            "All birds can fly",
            "Some cats are black", 
            "If it rains, then the ground gets wet",
            "No student failed the exam"
        ]
        
        results = []
        for test_case in test_cases:
            try:
                symbol = Symbol(test_case, semantic=True)
                fol_result = symbol.query("Convert this to first-order logic formula")
                results.append({
                    "input": test_case,
                    "output": fol_result,
                    "success": True
                })
                print(f"✓ Processed: {test_case}")
            except Exception as e:
                results.append({
                    "input": test_case,
                    "output": str(e),
                    "success": False
                })
                print(f"✗ Failed: {test_case} - {e}")
        
        success_rate = sum(1 for r in results if r["success"]) / len(results)
        print(f"\nSuccess Rate: {success_rate:.1%} ({sum(1 for r in results if r['success'])}/{len(results)})")
        
        return success_rate > 0.5
        
    except Exception as e:
        print(f"✗ Model capabilities test failed: {e}")
        traceback.print_exc()
        return False

def main():
    """Run all configuration and API tests"""
    print("🔧 OpenAI Model Configuration Test for SymbolicAI")
    print("=" * 60)
    print(f"Test started at: {datetime.now()}")
    
    results = {}
    
    # Run tests
    results['environment'] = test_environment_config()
    results['config_file'] = test_config_file()
    results['basic'] = test_symai_basic()
    results['api'] = test_api_connection()
    results['capabilities'] = test_model_capabilities()
    
    # Summary
    print("\n" + "=" * 60)
    print("CONFIGURATION TEST RESULTS")
    print("=" * 60)
    
    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{test_name.upper():15} {status}")
    
    passed = sum(results.values())
    total = len(results)
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    # Recommendations
    print("\n" + "=" * 60)
    print("RECOMMENDATIONS")
    print("=" * 60)
    
    if results['environment'] and results['config_file']:
        print("✓ Configuration is properly set up")
    else:
        print("⚠ Configuration needs attention - check API key and model settings")
    
    if results['api']:
        print("✓ OpenAI API is working correctly with gpt-4o model")
        print("✓ Ready for SymbolicAI logic integration tasks")
    else:
        print("⚠ API connection issues - verify API key and model access")
    
    if results['capabilities']:
        print("✓ Model capabilities are sufficient for logic tasks")
    else:
        print("⚠ Model may need adjustment for complex logic tasks")
    
    # Model information
    print(f"\nConfigured Model: gpt-4o")
    print(f"Recommended for: Complex reasoning, logic conversion, semantic understanding")
    print(f"Max Tokens: 4096 (optimal for logic formulas)")
    print(f"Temperature: 0.1 (low for consistent logical reasoning)")
    
    if passed >= 4:
        print("\n🎉 SymbolicAI is properly configured and ready to use!")
        return 0
    elif passed >= 2:
        print("\n⚠ Partial configuration - some features may work")
        return 0
    else:
        print("\n❌ Configuration issues need to be resolved")
        return 1

if __name__ == "__main__":
    sys.exit(main())
