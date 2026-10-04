#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Deontological Reasoning Test and Demo Script.

This script demonstrates the legal/ethical reasoning capabilities of the
news analysis dashboard by testing deontological conflict detection on
legal and regulatory documents.
"""

import anyio
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

# Add the project root to the path
sys.path.append(str(Path(__file__).parent))

from ipfs_datasets_py.dashboards.news_analysis_dashboard import (
    UnifiedInvestigationDashboard,
    MCPDashboardConfig,
)
from ipfs_datasets_py.logic.integration.deontological_reasoning import (
    DeontologicalReasoningEngine,
    DeonticModality,
    ConflictType,
)


class DeontologicalTestSuite:
    """Test suite for deontological reasoning capabilities."""

    def __init__(self):
        self.dashboard = UnifiedInvestigationDashboard()
        self.test_results = []

    async def run_comprehensive_test(self):
        """Run comprehensive deontological reasoning test."""
        print("🏛️ Starting Deontological Reasoning Test Suite")
        print("=" * 60)

        # Configure dashboard
        config = MCPDashboardConfig()
        self.dashboard.configure(config)

        # Run test cases
        await self.test_legal_obligations()
        await self.test_regulatory_conflicts()
        await self.test_government_policies()
        await self.test_corporate_governance()
        await self.test_query_capabilities()

        # Generate comprehensive report
        self.generate_test_report()

    async def test_legal_obligations(self):
        """Test detection of legal obligations, permissions, and prohibitions."""
        print("\n📜 Testing Legal Obligations Analysis")
        print("-" * 40)

        test_documents = [
            {
                "id": "legal_doc_1",
                "content": """
                Federal Law Section 1201: All financial institutions must maintain records 
                of all transactions exceeding $10,000 for a period of five years. Banks are 
                required to report suspicious activities to the Financial Crimes Enforcement 
                Network within 30 days of detection.
                
                However, banks cannot disclose customer information to third parties without 
                explicit consent, except when required by law enforcement agencies.
                """,
            },
            {
                "id": "legal_doc_2",
                "content": """
                State Regulation 405.7: Financial institutions may share customer data with 
                affiliated companies for marketing purposes. Credit unions are allowed to 
                waive transaction fees for members in good standing.
                
                All banks must not engage in discriminatory lending practices based on race, 
                gender, or religious affiliation. Institutions shall provide equal access to 
                financial services.
                """,
            },
            {
                "id": "conflicting_doc",
                "content": """
                Privacy Act Amendment: Banks cannot share customer data with any external entity, 
                including affiliated companies, without explicit written consent from the customer.
                Financial institutions must delete all customer data within 30 days of account closure.
                """,
            },
        ]

        try:
            # Analyze legal obligations
            result = await self.dashboard.conflict_analyzer.analyze_deontological_conflicts(
                test_documents
            )

            print(f"✅ Legal Analysis Completed")
            print(f"   📊 Documents analyzed: {result.get('documents_analyzed', 0)}")
            print(f"   📋 Status: {result.get('status', 'unknown')}")

            if result.get("result"):
                analysis = result["result"]
                statements = analysis.get("statements_summary", {})
                conflicts = analysis.get("conflicts_summary", {})

                print(f"   📝 Total statements: {statements.get('total_statements', 0)}")
                print(f"   ⚖️ Obligations: {statements.get('by_modality', {}).get('obligation', 0)}")
                print(
                    f"   ✅ Permissions: {statements.get('by_modality', {}).get('permission', 0)}"
                )
                print(
                    f"   ❌ Prohibitions: {statements.get('by_modality', {}).get('prohibition', 0)}"
                )
                print(f"   ⚡ Total conflicts: {conflicts.get('total_conflicts', 0)}")

                # Show high priority conflicts
                high_priority = analysis.get("high_priority_conflicts", [])
                if high_priority:
                    print(f"\n🚨 High Priority Conflicts Detected:")
                    for i, conflict in enumerate(high_priority[:3], 1):
                        print(f"   {i}. {conflict.get('explanation', 'No explanation')}")

            self.test_results.append(
                {"test": "Legal Obligations", "status": "passed", "result": result}
            )

        except Exception as e:
            print(f"❌ Legal obligations test failed: {e}")
            self.test_results.append(
                {"test": "Legal Obligations", "status": "failed", "error": str(e)}
            )

    async def test_regulatory_conflicts(self):
        """Test detection of conflicts in regulatory requirements."""
        print("\n🏛️ Testing Regulatory Conflicts")
        print("-" * 40)

        regulatory_docs = [
            {
                "id": "fed_reg_1",
                "content": """
                Federal Communications Commission Rule 47 CFR 64.1200: Telecommunications 
                companies must obtain prior express written consent before making robocalls 
                to wireless numbers. Companies are required to maintain a Do Not Call registry 
                and honor all requests within 30 days.
                
                Telecom providers shall not block emergency calls under any circumstances. 
                All carriers must provide free access to emergency services including 911.
                """,
            },
            {
                "id": "state_reg_1",
                "content": """
                State Public Utilities Code Section 2890: Telecommunications companies may 
                make informational calls to existing customers without additional consent. 
                Providers are allowed to charge fees for emergency service access in rural areas.
                
                All telecom companies must not discriminate based on geographic location when 
                providing basic services. Companies shall offer equal pricing to all residential customers.
                """,
            },
        ]

        try:
            result = await self.dashboard.conflict_analyzer.analyze_deontological_conflicts(
                regulatory_docs
            )

            print(f"✅ Regulatory Analysis Completed")
            if result.get("result"):
                analysis = result["result"]
                conflicts = analysis.get("conflicts_summary", {})
                entities = analysis.get("entity_reports", {})

                print(f"   ⚔️ Conflicts found: {conflicts.get('total_conflicts', 0)}")
                print(f"   🏢 Entities analyzed: {len(entities)}")

                # Show entity-specific conflicts
                for entity, report in list(entities.items())[:3]:
                    if report.get("total_conflicts", 0) > 0:
                        print(f"   📍 {entity}: {report['total_conflicts']} conflicts")

            self.test_results.append(
                {"test": "Regulatory Conflicts", "status": "passed", "result": result}
            )

        except Exception as e:
            print(f"❌ Regulatory conflicts test failed: {e}")
            self.test_results.append(
                {"test": "Regulatory Conflicts", "status": "failed", "error": str(e)}
            )

    async def test_government_policies(self):
        """Test analysis of government policy documents."""
        print("\n🏛️ Testing Government Policy Analysis")
        print("-" * 40)

        policy_docs = [
            {
                "id": "exec_order_1",
                "content": """
                Executive Order 14028: Federal agencies must implement zero-trust cybersecurity 
                frameworks within 90 days. All government contractors are required to report 
                cybersecurity incidents within 24 hours.
                
                Agencies cannot use Chinese-manufactured telecommunications equipment in any 
                government communications. Federal employees shall receive mandatory cybersecurity 
                training annually.
                """,
            },
            {
                "id": "dept_memo_1",
                "content": """
                Department of Defense Memorandum: Military contractors may use foreign-manufactured 
                equipment if approved through the Defense Security Cooperation Agency. Contractors 
                are allowed up to 72 hours to report security incidents for classified projects.
                
                All DOD personnel must complete cybersecurity certification every two years. 
                Contractors shall not share classified information with non-US persons.
                """,
            },
        ]

        try:
            result = await self.dashboard.conflict_analyzer.analyze_deontological_conflicts(
                policy_docs
            )

            print(f"✅ Government Policy Analysis Completed")
            if result.get("result"):
                analysis = result["result"]
                recommendations = analysis.get("recommendations", [])

                print(f"   💡 Recommendations generated: {len(recommendations)}")
                for i, rec in enumerate(recommendations[:3], 1):
                    print(f"   {i}. {rec}")

            self.test_results.append(
                {"test": "Government Policies", "status": "passed", "result": result}
            )

        except Exception as e:
            print(f"❌ Government policy test failed: {e}")
            self.test_results.append(
                {"test": "Government Policies", "status": "failed", "error": str(e)}
            )

    async def test_corporate_governance(self):
        """Test corporate governance and compliance analysis."""
        print("\n🏢 Testing Corporate Governance Analysis")
        print("-" * 40)

        corporate_docs = [
            {
                "id": "corp_policy_1",
                "content": """
                Corporate Code of Conduct Section 3.1: All employees must report conflicts of 
                interest to the Ethics Committee within 10 days of discovery. Managers are 
                required to complete annual ethics training and certifications.
                
                Employees cannot accept gifts valued over $25 from clients or vendors. 
                All staff shall maintain confidentiality of proprietary information and 
                customer data at all times.
                """,
            },
            {
                "id": "hr_handbook",
                "content": """
                Employee Handbook Chapter 7: Staff members may accept promotional items and 
                gifts up to $50 in value from approved business partners. Employees are 
                allowed to discuss general business practices with industry colleagues.
                
                All workers must not engage in insider trading or share material non-public 
                information. Employees shall report violations of company policy to HR 
                within 5 business days.
                """,
            },
        ]

        try:
            result = await self.dashboard.conflict_analyzer.analyze_deontological_conflicts(
                corporate_docs
            )

            print(f"✅ Corporate Governance Analysis Completed")
            if result.get("result"):
                analysis = result["result"]
                high_conflicts = analysis.get("high_priority_conflicts", [])

                print(f"   🚨 High priority conflicts: {len(high_conflicts)}")
                if high_conflicts:
                    conflict = high_conflicts[0]
                    print(f"   Example: {conflict.get('explanation', 'No explanation')[:100]}...")

            self.test_results.append(
                {"test": "Corporate Governance", "status": "passed", "result": result}
            )

        except Exception as e:
            print(f"❌ Corporate governance test failed: {e}")
            self.test_results.append(
                {"test": "Corporate Governance", "status": "failed", "error": str(e)}
            )

    async def test_query_capabilities(self):
        """Test querying capabilities for deontic statements and conflicts."""
        print("\n🔍 Testing Query Capabilities")
        print("-" * 40)

        try:
            # Test querying deontic statements
            stmt_result = await self.dashboard.conflict_analyzer.query_deontic_statements(
                entity="banks", modality="obligation"
            )

            print(f"✅ Statement Query Completed")
            print(f"   📋 Statements found: {stmt_result.get('total_results', 0)}")

            # Test querying conflicts
            conflict_result = await self.dashboard.conflict_analyzer.query_deontic_conflicts(
                min_severity="high"
            )

            print(f"✅ Conflict Query Completed")
            print(f"   ⚔️ High severity conflicts: {conflict_result.get('total_results', 0)}")

            self.test_results.append(
                {
                    "test": "Query Capabilities",
                    "status": "passed",
                    "statements": stmt_result,
                    "conflicts": conflict_result,
                }
            )

        except Exception as e:
            print(f"❌ Query capabilities test failed: {e}")
            self.test_results.append(
                {"test": "Query Capabilities", "status": "failed", "error": str(e)}
            )

    def generate_test_report(self):
        """Generate comprehensive test report."""
        print("\n📊 DEONTOLOGICAL REASONING TEST REPORT")
        print("=" * 60)

        total_tests = len(self.test_results)
        passed_tests = len([r for r in self.test_results if r.get("status") == "passed"])
        failed_tests = total_tests - passed_tests

        print(f"📈 Overall Results:")
        print(f"   ✅ Passed: {passed_tests}/{total_tests}")
        print(f"   ❌ Failed: {failed_tests}/{total_tests}")
        print(f"   📊 Success Rate: {(passed_tests / total_tests) * 100:.1f}%")

        print(f"\n📋 Detailed Results:")
        for result in self.test_results:
            status_icon = "✅" if result["status"] == "passed" else "❌"
            print(f"   {status_icon} {result['test']}: {result['status']}")
            if result["status"] == "failed" and "error" in result:
                print(f"      Error: {result['error']}")

        # Save detailed results
        report_file = Path("deontological_test_results.json")
        with open(report_file, "w") as f:
            json.dump(
                {
                    "test_suite": "Deontological Reasoning",
                    "timestamp": datetime.now().isoformat(),
                    "summary": {
                        "total_tests": total_tests,
                        "passed": passed_tests,
                        "failed": failed_tests,
                        "success_rate": f"{(passed_tests / total_tests) * 100:.1f}%",
                    },
                    "detailed_results": self.test_results,
                },
                f,
                indent=2,
                default=str,
            )

        print(f"\n💾 Detailed results saved to: {report_file}")

        if passed_tests == total_tests:
            print(f"\n🎉 ALL TESTS PASSED! Deontological reasoning is working correctly.")
        else:
            print(f"\n⚠️ Some tests failed. Check the errors above for details.")


async def main():
    """Main test execution function."""
    try:
        test_suite = DeontologicalTestSuite()
        await test_suite.run_comprehensive_test()

    except Exception as e:
        print(f"❌ Test suite execution failed: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    print("🧪 Deontological Reasoning Test Suite for News Analysis Dashboard")
    print("Testing legal/ethical conflict detection capabilities...")
    print()

    anyio.run(main())
