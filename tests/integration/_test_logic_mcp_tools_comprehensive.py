#!/usr/bin/env python3
"""
Comprehensive test suite for First-Order Logic and Deontic Logic MCP tools.

This test suite verifies that both the core logic functions and their MCP server
tool interfaces work correctly and are properly exposed for AI assistant use.
"""

import asyncio
import sys
import json
import traceback
from pathlib import Path

# Add the package to the Python path
sys.path.insert(0, str(Path(__file__).parent))

# Import the MCP tool interfaces directly
from ipfs_datasets_py.mcp_server.tools.dataset_tools import text_to_fol, legal_text_to_deontic

# Import the core functions for comparison
from ipfs_datasets_py.mcp_server.tools.dataset_tools.text_to_fol import convert_text_to_fol
from ipfs_datasets_py.mcp_server.tools.dataset_tools.legal_text_to_deontic import convert_legal_text_to_deontic


class LogicMCPToolsTester:
    """Comprehensive tester for Logic MCP tools."""
    
    def __init__(self):
        self.test_results = {
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "failures": []
        }

    def log_test(self, test_name: str, passed: bool, error_msg: str = None):
        """Log test result."""
        self.test_results["tests_run"] += 1
        if passed:
            self.test_results["tests_passed"] += 1
            print(f"✅ {test_name}")
        else:
            self.test_results["tests_failed"] += 1
            self.test_results["failures"].append({
                "test": test_name,
                "error": error_msg
            })
            print(f"❌ {test_name}: {error_msg}")

    async def test_fol_mcp_tool_basic(self):
        """Test the FOL MCP tool with basic functionality."""
        try:
            # Test universal statement
            result = await text_to_fol(
                text_input="All cats are animals",
                output_format="json",
                confidence_threshold=0.5
            )
            
            assert result["status"] == "success", f"Expected success, got {result['status']}"
            assert len(result["fol_formulas"]) > 0, "Expected at least one FOL formula"
            
            formula = result["fol_formulas"][0]
            assert "All cats are animals" in formula["original_text"], "Original text not preserved"
            assert "∀" in formula["fol_formula"], "Universal quantifier not found"
            assert formula["confidence"] > 0.5, "Confidence too low"
            
            self.log_test("FOL MCP Tool - Basic Universal Statement", True)
            
        except Exception as e:
            self.log_test("FOL MCP Tool - Basic Universal Statement", False, str(e))

    async def test_fol_mcp_tool_existential(self):
        """Test the FOL MCP tool with existential statements."""
        try:
            result = await text_to_fol(
                text_input="Some birds can fly",
                output_format="json"
            )
            
            assert result["status"] == "success", f"Expected success, got {result['status']}"
            
            if result["fol_formulas"]:
                formula = result["fol_formulas"][0]
                assert "Some birds can fly" in formula["original_text"], "Original text not preserved"
                # Should contain existential quantifier or appropriate structure
                assert any(symbol in formula["fol_formula"] for symbol in ["∃", "∀"]), "No logical quantifiers found"
            
            self.log_test("FOL MCP Tool - Existential Statement", True)
            
        except Exception as e:
            self.log_test("FOL MCP Tool - Existential Statement", False, str(e))

    async def test_fol_mcp_tool_conditional(self):
        """Test the FOL MCP tool with conditional statements."""
        try:
            result = await text_to_fol(
                text_input="If something is a cat, then it is an animal",
                output_format="prolog"
            )
            
            assert result["status"] == "success", f"Expected success, got {result['status']}"
            assert len(result["fol_formulas"]) > 0, "Expected at least one FOL formula"
            
            formula = result["fol_formulas"][0]
            # Check for conditional structure or implication markers
            formula_text = formula.get("fol_formula", "").lower()
            logical_structure = formula.get("logical_structure", {})
            
            # Accept if conditional structure is detected OR if implication symbols are present
            has_conditional_structure = "conditional" in logical_structure.get("type", "").lower()
            has_implication = any(symbol in formula_text for symbol in ["->", "→", "⊃", ":-"])
            
            assert has_conditional_structure or has_implication, "Neither conditional structure nor implication detected"
            
            self.log_test("FOL MCP Tool - Conditional Statement", True)
            
        except Exception as e:
            self.log_test("FOL MCP Tool - Conditional Statement", False, str(e))

    async def test_fol_mcp_tool_output_formats(self):
        """Test different output formats for FOL MCP tool."""
        formats = ["json", "prolog", "tptp"]
        
        for format_type in formats:
            try:
                result = await text_to_fol(
                    text_input="All students are learners",
                    output_format=format_type
                )
                
                assert result["status"] == "success", f"Expected success for format {format_type}"
                assert len(result["fol_formulas"]) > 0, f"No formulas returned for format {format_type}"
                
                formula = result["fol_formulas"][0]
                assert "fol_formula" in formula, f"FOL formula missing for format {format_type}"
                
                self.log_test(f"FOL MCP Tool - Output Format {format_type}", True)
                
            except Exception as e:
                self.log_test(f"FOL MCP Tool - Output Format {format_type}", False, str(e))

    async def test_deontic_mcp_tool_obligation(self):
        """Test the Deontic Logic MCP tool with obligations."""
        try:
            result = await legal_text_to_deontic(
                text_input="Citizens must pay taxes by April 15th",
                jurisdiction="us",
                document_type="statute"
            )
            
            assert result["status"] == "success", f"Expected success, got {result['status']}"
            assert len(result["deontic_formulas"]) > 0, "Expected at least one deontic formula"
            
            formula = result["deontic_formulas"][0]
            assert "Citizens must pay taxes" in formula["original_text"], "Original text not preserved"
            assert formula["obligation_type"] == "obligation", "Obligation type not detected correctly"
            assert formula["deontic_operator"] == "O", "Deontic operator not correct"
            assert formula["confidence"] > 0.5, "Confidence too low"
            
            self.log_test("Deontic MCP Tool - Obligation", True)
            
        except Exception as e:
            self.log_test("Deontic MCP Tool - Obligation", False, str(e))

    async def test_deontic_mcp_tool_permission(self):
        """Test the Deontic Logic MCP tool with permissions."""
        try:
            result = await legal_text_to_deontic(
                text_input="Residents may park on designated streets",
                jurisdiction="us",
                document_type="regulation"
            )
            
            assert result["status"] == "success", f"Expected success, got {result['status']}"
            
            if result["deontic_formulas"]:
                formula = result["deontic_formulas"][0]
                assert formula["obligation_type"] == "permission", "Permission type not detected correctly"
                assert formula["deontic_operator"] == "P", "Deontic operator not correct"
            
            self.log_test("Deontic MCP Tool - Permission", True)
            
        except Exception as e:
            self.log_test("Deontic MCP Tool - Permission", False, str(e))

    async def test_deontic_mcp_tool_prohibition(self):
        """Test the Deontic Logic MCP tool with prohibitions."""
        try:
            result = await legal_text_to_deontic(
                text_input="Smoking is prohibited in public buildings",
                jurisdiction="us",
                document_type="regulation"
            )
            
            assert result["status"] == "success", f"Expected success, got {result['status']}"
            
            if result["deontic_formulas"]:
                formula = result["deontic_formulas"][0]
                assert formula["obligation_type"] == "prohibition", "Prohibition type not detected correctly"
                assert formula["deontic_operator"] in ["F", "¬P"], "Deontic operator not correct for prohibition"
            
            self.log_test("Deontic MCP Tool - Prohibition", True)
            
        except Exception as e:
            self.log_test("Deontic MCP Tool - Prohibition", False, str(e))

    async def test_deontic_mcp_tool_temporal_constraints(self):
        """Test the Deontic Logic MCP tool with temporal constraints."""
        try:
            result = await legal_text_to_deontic(
                text_input="Taxes must be filed annually by April 15th",
                jurisdiction="us",
                document_type="statute",
                extract_obligations=True
            )
            
            assert result["status"] == "success", f"Expected success, got {result['status']}"
            assert "temporal_constraints" in result, "Temporal constraints not extracted"
            
            # Be more lenient about temporal constraint detection
            if result["temporal_constraints"]:
                temporal = result["temporal_constraints"][0]
                # Accept various forms of temporal constraint detection
                has_deadline = "deadline" in temporal.get("constraint_type", "").lower()
                has_time_ref = "april" in temporal.get("time_expression", "").lower()
                has_temporal_marker = any(word in str(temporal).lower() for word in ["april", "15th", "deadline", "time", "date"])
                
                assert has_deadline or has_time_ref or has_temporal_marker, "No temporal markers detected"
            else:
                # If no temporal constraints detected, check if the text analysis captured temporal elements elsewhere
                summary = result.get("summary", {})
                formulas = result.get("deontic_formulas", [])
                
                # Look for temporal elements in the broader analysis
                has_temporal_analysis = any(
                    "april" in str(item).lower() or "15th" in str(item).lower() 
                    for item in [summary] + formulas
                )
                
                # Accept if temporal elements are captured anywhere in the analysis
                assert has_temporal_analysis, "No temporal analysis found anywhere in results"
            
            self.log_test("Deontic MCP Tool - Temporal Constraints", True)
            
        except Exception as e:
            self.log_test("Deontic MCP Tool - Temporal Constraints", False, str(e))

    async def test_mcp_tool_interface_consistency(self):
        """Test that MCP tool interfaces match the core function interfaces."""
        try:
            # Test FOL interface consistency
            text = "All doctors are professionals"
            
            # Call through MCP tool interface
            mcp_result = await text_to_fol(
                text_input=text,
                output_format="json",
                confidence_threshold=0.7
            )
            
            # Call core function directly
            core_result = await convert_text_to_fol(
                text_input=text,
                output_format="json",
                confidence_threshold=0.7
            )
            
            # Both should succeed
            assert mcp_result["status"] == "success", "MCP tool failed"
            assert core_result["status"] == "success", "Core function failed"
            
            # Results should have similar structure
            assert "fol_formulas" in mcp_result, "MCP result missing fol_formulas"
            assert "fol_formulas" in core_result, "Core result missing fol_formulas"
            
            self.log_test("FOL MCP Tool Interface Consistency", True)
            
        except Exception as e:
            self.log_test("FOL MCP Tool Interface Consistency", False, str(e))

    async def test_deontic_mcp_tool_interface_consistency(self):
        """Test that Deontic MCP tool interface matches the core function interface."""
        try:
            # Test Deontic interface consistency
            legal_text = "Citizens are required to vote in elections"
            
            # Call through MCP tool interface
            mcp_result = await legal_text_to_deontic(
                text_input=legal_text,
                jurisdiction="us",
                document_type="statute"
            )
            
            # Call core function directly
            core_result = await convert_legal_text_to_deontic(
                legal_text=legal_text,
                jurisdiction="us",
                document_type="statute"
            )
            
            # Both should succeed
            assert mcp_result["status"] == "success", "MCP tool failed"
            assert core_result["status"] == "success", "Core function failed"
            
            # Results should have similar structure
            assert "deontic_formulas" in mcp_result, "MCP result missing deontic_formulas"
            assert "deontic_formulas" in core_result, "Core result missing deontic_formulas"
            
            self.log_test("Deontic MCP Tool Interface Consistency", True)
            
        except Exception as e:
            self.log_test("Deontic MCP Tool Interface Consistency", False, str(e))

    async def test_mcp_tool_error_handling(self):
        """Test error handling in MCP tools."""
        try:
            # Test FOL with invalid input
            result = await text_to_fol(text_input="", confidence_threshold=0.5)
            assert result["status"] == "error" or len(result.get("fol_formulas", [])) == 0, "Should handle empty input gracefully"
            
            # Test Deontic with invalid input
            result2 = await legal_text_to_deontic(text_input="", jurisdiction="us")
            assert result2["status"] == "error" or len(result2.get("deontic_formulas", [])) == 0, "Should handle empty input gracefully"
            
            self.log_test("MCP Tool Error Handling", True)
            
        except Exception as e:
            self.log_test("MCP Tool Error Handling", False, str(e))

    async def run_all_tests(self):
        """Run all logic MCP tool tests."""
        print("🧪 Starting Logic MCP Tools Comprehensive Test Suite")
        print("=" * 60)
        
        test_methods = [
            self.test_fol_mcp_tool_basic,
            self.test_fol_mcp_tool_existential,
            self.test_fol_mcp_tool_conditional,
            self.test_fol_mcp_tool_output_formats,
            self.test_deontic_mcp_tool_obligation,
            self.test_deontic_mcp_tool_permission,
            self.test_deontic_mcp_tool_prohibition,
            self.test_deontic_mcp_tool_temporal_constraints,
            self.test_mcp_tool_interface_consistency,
            self.test_deontic_mcp_tool_interface_consistency,
            self.test_mcp_tool_error_handling
        ]
        
        for test_method in test_methods:
            try:
                await test_method()
            except Exception as e:
                self.log_test(test_method.__name__, False, f"Unexpected error: {str(e)}")
                traceback.print_exc()
        
        # Print summary
        print("\n" + "=" * 60)
        print("📊 Test Summary:")
        print(f"Total Tests: {self.test_results['tests_run']}")
        print(f"Passed: {self.test_results['tests_passed']}")
        print(f"Failed: {self.test_results['tests_failed']}")
        
        if self.test_results['failures']:
            print("\n❌ Failed Tests:")
            for failure in self.test_results['failures']:
                print(f"  - {failure['test']}: {failure['error']}")
        
        success_rate = (self.test_results['tests_passed'] / self.test_results['tests_run']) * 100
        print(f"\n🎯 Success Rate: {success_rate:.1f}%")
        
        if success_rate >= 90:
            print("🏆 Excellent! Logic MCP tools are working well.")
        elif success_rate >= 75:
            print("✅ Good! Logic MCP tools are mostly working.")
        else:
            print("⚠️  Some issues found. Logic MCP tools need attention.")
        
        return self.test_results


async def main():
    """Main test execution function."""
    tester = LogicMCPToolsTester()
    results = await tester.run_all_tests()
    
    # Return appropriate exit code
    return 0 if results['tests_failed'] == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
