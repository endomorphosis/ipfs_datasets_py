# test_logic_tools.py
"""
Comprehensive test suite for the new logic conversion tools.

This script tests both the text-to-FOL and legal-text-to-deontic tools
along with their supporting utilities.
"""
import asyncio
import sys
import os
from typing import Dict, Any, List
import json
from datetime import datetime

# Add the project root to the path
sys.path.insert(0, '/home/barberb/ipfs_datasets_py')

from ipfs_datasets_py.mcp_server.tools.dataset_tools.text_to_fol import convert_text_to_fol
from ipfs_datasets_py.mcp_server.tools.dataset_tools.legal_text_to_deontic import convert_legal_text_to_deontic

class LogicToolsTestRunner:
    """Test runner for logic conversion tools."""
    
    def __init__(self):
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "test_suites": [],
            "summary": {
                "total_tests": 0,
                "passed": 0,
                "failed": 0,
                "errors": []
            }
        }
    
    async def run_all_tests(self) -> Dict[str, Any]:
        """Run all logic tools tests."""
        print("=" * 60)
        print("LOGIC CONVERSION TOOLS TEST SUITE")
        print("=" * 60)
        
        # Test Text to FOL conversion
        print("\n1. Testing Text to FOL Conversion Tool...")
        fol_results = await self.test_text_to_fol()
        self.results["test_suites"].append(fol_results)
        
        # Test Legal Text to Deontic Logic conversion
        print("\n2. Testing Legal Text to Deontic Logic Tool...")
        deontic_results = await self.test_legal_text_to_deontic()
        self.results["test_suites"].append(deontic_results)
        
        # Test Logic Utilities
        print("\n3. Testing Logic Utilities...")
        utils_results = await self.test_logic_utilities()
        self.results["test_suites"].append(utils_results)
        
        # Test Integration
        print("\n4. Testing Tool Integration...")
        integration_results = await self.test_integration()
        self.results["test_suites"].append(integration_results)
        
        # Calculate summary
        self.calculate_summary()
        
        # Print results
        self.print_summary()
        
        return self.results
    
    async def test_text_to_fol(self) -> Dict[str, Any]:
        """Test the text to FOL conversion tool."""
        suite_results = {
            "suite_name": "Text to FOL Conversion",
            "tests": [],
            "passed": 0,
            "failed": 0
        }
        
        # Test 1: Basic universal statement
        test_result = await self.run_test(
            "Basic Universal Statement",
            lambda: convert_text_to_fol("All cats are animals"),
            lambda result: (
                result["status"] == "success" and
                len(result["fol_formulas"]) > 0 and
                "∀" in result["fol_formulas"][0]["fol_formula"]
            )
        )
        suite_results["tests"].append(test_result)
        
        # Test 2: Existential statement
        test_result = await self.run_test(
            "Existential Statement",
            lambda: convert_text_to_fol("Some birds can fly"),
            lambda result: result["status"] == "success"
        )
        suite_results["tests"].append(test_result)
        
        # Test 3: Complex conditional
        test_result = await self.run_test(
            "Complex Conditional",
            lambda: convert_text_to_fol("If someone is a student and studies hard, then they will pass"),
            lambda result: result["status"] == "success"
        )
        suite_results["tests"].append(test_result)
        
        # Test 4: Multiple statements
        test_result = await self.run_test(
            "Multiple Statements",
            lambda: convert_text_to_fol({
                "sentences": ["All dogs are mammals", "Some mammals are carnivores"]
            }),
            lambda result: (
                result["status"] == "success" and
                len(result["fol_formulas"]) <= 2
            )
        )
        suite_results["tests"].append(test_result)
        
        # Test 5: Output formats
        test_result = await self.run_test(
            "Prolog Output Format",
            lambda: convert_text_to_fol("All humans are mortal", output_format='prolog'),
            lambda result: (
                result["status"] == "success" and
                (not result["fol_formulas"] or "prolog_form" in result["fol_formulas"][0])
            )
        )
        suite_results["tests"].append(test_result)
        
        # Test 6: Error handling
        test_result = await self.run_test(
            "Empty Input Error Handling",
            lambda: convert_text_to_fol(""),
            lambda result: result["status"] == "error"
        )
        suite_results["tests"].append(test_result)
        
        # Test 7: Confidence scoring
        test_result = await self.run_test(
            "Confidence Scoring",
            lambda: convert_text_to_fol("All cats are animals", confidence_threshold=0.1),
            lambda result: (
                result["status"] == "success" and
                (not result["fol_formulas"] or 
                 isinstance(result["fol_formulas"][0]["confidence"], (int, float)))
            )
        )
        suite_results["tests"].append(test_result)
        
        # Count passed/failed
        suite_results["passed"] = sum(1 for test in suite_results["tests"] if test["passed"])
        suite_results["failed"] = len(suite_results["tests"]) - suite_results["passed"]
        
        return suite_results
    
    async def test_legal_text_to_deontic(self) -> Dict[str, Any]:
        """Test the legal text to deontic logic conversion tool."""
        suite_results = {
            "suite_name": "Legal Text to Deontic Logic",
            "tests": [],
            "passed": 0,
            "failed": 0
        }
        
        # Test 1: Basic obligation
        test_result = await self.run_test(
            "Basic Obligation",
            lambda: convert_legal_text_to_deontic("Citizens must pay taxes"),
            lambda result: (
                result["status"] == "success" and
                (not result["deontic_formulas"] or 
                 result["deontic_formulas"][0]["obligation_type"] == "obligation")
            )
        )
        suite_results["tests"].append(test_result)
        
        # Test 2: Permission
        test_result = await self.run_test(
            "Permission Statement",
            lambda: convert_legal_text_to_deontic("Residents may park on designated streets"),
            lambda result: (
                result["status"] == "success" and
                (not result["deontic_formulas"] or 
                 result["deontic_formulas"][0]["obligation_type"] == "permission")
            )
        )
        suite_results["tests"].append(test_result)
        
        # Test 3: Prohibition
        test_result = await self.run_test(
            "Prohibition Statement",
            lambda: convert_legal_text_to_deontic("Smoking is prohibited in public buildings"),
            lambda result: (
                result["status"] == "success" and
                (not result["deontic_formulas"] or 
                 result["deontic_formulas"][0]["obligation_type"] == "prohibition")
            )
        )
        suite_results["tests"].append(test_result)
        
        # Test 4: Temporal constraints
        test_result = await self.run_test(
            "Temporal Constraints",
            lambda: convert_legal_text_to_deontic("Tax returns must be filed by April 15th"),
            lambda result: result["status"] == "success"
        )
        suite_results["tests"].append(test_result)
        
        # Test 5: Different jurisdictions
        test_result = await self.run_test(
            "Jurisdiction Handling",
            lambda: convert_legal_text_to_deontic("All citizens must register", jurisdiction='eu'),
            lambda result: (
                result["status"] == "success" and
                result["metadata"]["jurisdiction"] == "eu"
            )
        )
        suite_results["tests"].append(test_result)
        
        # Test 6: Complex legal text
        test_result = await self.run_test(
            "Complex Legal Text",
            lambda: convert_legal_text_to_deontic(
                "Employees must complete training. Supervisors may approve leave. Workers cannot operate without certification."
            ),
            lambda result: result["status"] == "success"
        )
        suite_results["tests"].append(test_result)
        
        # Test 7: Dataset input
        test_result = await self.run_test(
            "Dataset Input",
            lambda: convert_legal_text_to_deontic({
                "legal_text": ["All contractors must provide insurance", "Workers may request equipment"]
            }),
            lambda result: result["status"] == "success"
        )
        suite_results["tests"].append(test_result)
        
        # Test 8: Error handling
        test_result = await self.run_test(
            "Empty Input Error Handling",
            lambda: convert_legal_text_to_deontic(""),
            lambda result: result["status"] == "error"
        )
        suite_results["tests"].append(test_result)
        
        # Count passed/failed
        suite_results["passed"] = sum(1 for test in suite_results["tests"] if test["passed"])
        suite_results["failed"] = len(suite_results["tests"]) - suite_results["passed"]
        
        return suite_results
    
    async def test_logic_utilities(self) -> Dict[str, Any]:
        """Test the logic utilities modules."""
        suite_results = {
            "suite_name": "Logic Utilities",
            "tests": [],
            "passed": 0,
            "failed": 0
        }
        
        # Test predicate extraction
        test_result = await self.run_test(
            "Predicate Extraction",
            lambda: self.test_predicate_extraction_sync(),
            lambda result: result is True
        )
        suite_results["tests"].append(test_result)
        
        # Test FOL parsing
        test_result = await self.run_test(
            "FOL Parsing",
            lambda: self.test_fol_parsing_sync(),
            lambda result: result is True
        )
        suite_results["tests"].append(test_result)
        
        # Test deontic parsing
        test_result = await self.run_test(
            "Deontic Parsing",
            lambda: self.test_deontic_parsing_sync(),
            lambda result: result is True
        )
        suite_results["tests"].append(test_result)
        
        # Count passed/failed
        suite_results["passed"] = sum(1 for test in suite_results["tests"] if test["passed"])
        suite_results["failed"] = len(suite_results["tests"]) - suite_results["passed"]
        
        return suite_results
    
    def test_predicate_extraction_sync(self) -> bool:
        """Test predicate extraction functionality."""
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.logic_utils.predicate_extractor import extract_predicates, normalize_predicate
            
            text = "All cats are animals"
            predicates = extract_predicates(text)
            
            # Should return a dictionary with predicate categories
            if not isinstance(predicates, dict):
                return False
            
            # Test normalization
            normalized = normalize_predicate("the big cat")
            if not isinstance(normalized, str) or len(normalized) == 0:
                return False
            
            return True
        except Exception as e:
            print(f"Predicate extraction test error: {e}")
            return False
    
    def test_fol_parsing_sync(self) -> bool:
        """Test FOL parsing functionality."""
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.logic_utils.fol_parser import parse_quantifiers, validate_fol_syntax
            
            text = "All students study hard"
            quantifiers = parse_quantifiers(text)
            
            # Should return a list
            if not isinstance(quantifiers, list):
                return False
            
            # Test validation
            formula = "∀x (Student(x) → Study(x))"
            validation = validate_fol_syntax(formula)
            
            if not isinstance(validation, dict) or "valid" not in validation:
                return False
            
            return True
        except Exception as e:
            print(f"FOL parsing test error: {e}")
            return False
    
    def test_deontic_parsing_sync(self) -> bool:
        """Test deontic parsing functionality."""
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.logic_utils.deontic_parser import extract_normative_elements
            
            text = "Employees must complete training"
            elements = extract_normative_elements(text, "regulation")
            
            # Should return a list
            if not isinstance(elements, list):
                return False
            
            return True
        except Exception as e:
            print(f"Deontic parsing test error: {e}")
            return False
    
    async def test_integration(self) -> Dict[str, Any]:
        """Test integration between tools."""
        suite_results = {
            "suite_name": "Tool Integration",
            "tests": [],
            "passed": 0,
            "failed": 0
        }
        
        # Test importing tools in MCP context
        test_result = await self.run_test(
            "MCP Tool Import",
            lambda: self.test_mcp_import(),
            lambda result: result is True
        )
        suite_results["tests"].append(test_result)
        
        # Test async main functions
        test_result = await self.run_test(
            "Async Main Functions",
            lambda: self.test_async_main_functions(),
            lambda result: result is True
        )
        suite_results["tests"].append(test_result)
        
        # Count passed/failed
        suite_results["passed"] = sum(1 for test in suite_results["tests"] if test["passed"])
        suite_results["failed"] = len(suite_results["tests"]) - suite_results["passed"]
        
        return suite_results
    
    def test_mcp_import(self) -> bool:
        """Test that tools can be imported for MCP registration."""
        try:
            # Test importing the tools
            from ipfs_datasets_py.mcp_server.tools.dataset_tools import text_to_fol, legal_text_to_deontic
            
            # Check that functions are callable
            if not callable(text_to_fol) or not callable(legal_text_to_deontic):
                return False
            
            return True
        except Exception as e:
            print(f"MCP import test error: {e}")
            return False
    
    async def test_async_main_functions(self) -> bool:
        """Test that async main functions work."""
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.text_to_fol import main as fol_main
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.legal_text_to_deontic import main as deontic_main
            
            # Test FOL main function
            fol_result = await fol_main()
            if not isinstance(fol_result, dict) or fol_result.get("status") != "success":
                return False
            
            # Test deontic main function
            deontic_result = await deontic_main()
            if not isinstance(deontic_result, dict) or deontic_result.get("status") != "success":
                return False
            
            return True
        except Exception as e:
            print(f"Async main functions test error: {e}")
            return False
    
    async def run_test(self, test_name: str, test_func, validation_func) -> Dict[str, Any]:
        """Run a single test and return results."""
        print(f"  Running: {test_name}...", end=" ")
        
        test_result = {
            "name": test_name,
            "passed": False,
            "error": None,
            "duration": 0
        }
        
        start_time = datetime.now()
        
        try:
            # Check if test_func returns a coroutine and await it
            result = test_func()
            if asyncio.iscoroutine(result):
                result = await result
            
            # Validate the result
            test_result["passed"] = validation_func(result)
            
            if test_result["passed"]:
                print("✓ PASSED")
            else:
                print("✗ FAILED (validation failed)")
                
        except Exception as e:
            test_result["error"] = str(e)
            print(f"✗ FAILED ({e})")
        
        end_time = datetime.now()
        test_result["duration"] = (end_time - start_time).total_seconds()
        
        return test_result
    
    def calculate_summary(self):
        """Calculate overall test summary."""
        total_tests = 0
        total_passed = 0
        
        for suite in self.results["test_suites"]:
            total_tests += len(suite["tests"])
            total_passed += suite["passed"]
        
        self.results["summary"]["total_tests"] = total_tests
        self.results["summary"]["passed"] = total_passed
        self.results["summary"]["failed"] = total_tests - total_passed
    
    def print_summary(self):
        """Print test summary."""
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        
        for suite in self.results["test_suites"]:
            print(f"\n{suite['suite_name']}:")
            print(f"  Tests: {len(suite['tests'])}")
            print(f"  Passed: {suite['passed']} ✓")
            print(f"  Failed: {suite['failed']} ✗")
            
            if suite['failed'] > 0:
                print("  Failed tests:")
                for test in suite['tests']:
                    if not test['passed']:
                        error_msg = f" ({test['error']})" if test['error'] else ""
                        print(f"    - {test['name']}{error_msg}")
        
        summary = self.results["summary"]
        print(f"\nOVERALL RESULTS:")
        print(f"  Total Tests: {summary['total_tests']}")
        print(f"  Passed: {summary['passed']} ✓")
        print(f"  Failed: {summary['failed']} ✗")
        print(f"  Success Rate: {(summary['passed'] / max(1, summary['total_tests']) * 100):.1f}%")
        
        if summary['failed'] == 0:
            print("\n🎉 ALL TESTS PASSED! Logic conversion tools are ready for production.")
        else:
            print(f"\n⚠️  {summary['failed']} test(s) failed. Please review and fix issues.")

async def main():
    """Main test execution function."""
    runner = LogicToolsTestRunner()
    results = await runner.run_all_tests()
    
    # Save results to file
    results_file = "/home/barberb/ipfs_datasets_py/logic_tools_test_results.json"
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\nDetailed results saved to: {results_file}")
    
    return results

if __name__ == "__main__":
    asyncio.run(main())
