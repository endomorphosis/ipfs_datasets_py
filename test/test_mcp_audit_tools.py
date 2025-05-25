import unittest
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock
import datetime
import json
import tempfile
import shutil

# Add the parent directory to the path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock the AuditReportGenerator to avoid external dependencies and complex setup
class MockAuditReportGenerator:
    def __init__(self, metrics_aggregator=None, visualizer=None, pattern_detector=None, compliance_analyzer=None, output_dir="./audit_reports"):
        pass # Initialize with no-op

    def generate_security_report(self):
        return {
            "report_type": "security",
            "report_id": "mock-security-id",
            "timestamp": datetime.datetime.now().isoformat(),
            "summary": {"overall_risk_score": 0.5},
            "anomalies": [],
            "recommendations": ["Mock security recommendation"]
        }

    def generate_compliance_report(self):
        return {
            "report_type": "compliance",
            "report_id": "mock-compliance-id",
            "timestamp": datetime.datetime.now().isoformat(),
            "summary": {"overall_compliance_percentage": 75.0},
            "frameworks": {},
            "top_issues": [],
            "recommendations": ["Mock compliance recommendation"]
        }

    def generate_operational_report(self):
        return {
            "report_type": "operational",
            "report_id": "mock-operational-id",
            "timestamp": datetime.datetime.now().isoformat(),
            "summary": {"error_percentage": 2.0},
            "performance_metrics": {},
            "recommendations": ["Mock operational recommendation"]
        }

    def generate_comprehensive_report(self):
        return {
            "report_type": "comprehensive",
            "report_id": "mock-comprehensive-id",
            "timestamp": datetime.datetime.now().isoformat(),
            "executive_summary": {"overall_risk_score": 0.5, "overall_compliance_percentage": 75.0},
            "security": self.generate_security_report(),
            "compliance": self.generate_compliance_report(),
            "operations": self.generate_operational_report(),
            "top_recommendations": ["Mock comprehensive recommendation"]
        }

    def export_report(self, report, format, output_file):
        with open(output_file, 'w') as f:
            if format == 'json':
                json.dump(report, f)
            else:
                f.write(str(report))
        return output_file

# Patch the AuditReportGenerator import globally for tests in this file
@patch('ipfs_datasets_py.audit.audit_reporting.AuditReportGenerator', new=MockAuditReportGenerator)
class TestMCPAuditTools(unittest.IsolatedAsyncioTestCase):

    async def test_generate_audit_report_comprehensive(self):
        from ipfs_datasets_py.mcp_server.tools.audit_tools.generate_audit_report import generate_audit_report

        result = await generate_audit_report(report_type="comprehensive")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["report_type"], "comprehensive")
        self.assertIn("report", result)
        self.assertEqual(result["report"]["report_type"], "comprehensive")
        self.assertIn("executive_summary", result["report"])

    async def test_generate_audit_report_security(self):
        from ipfs_datasets_py.mcp_server.tools.audit_tools.generate_audit_report import generate_audit_report

        result = await generate_audit_report(report_type="security")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["report_type"], "security")
        self.assertIn("report", result)
        self.assertEqual(result["report"]["report_type"], "security")
        self.assertIn("summary", result["report"])

    async def test_generate_audit_report_with_output_path(self):
        from ipfs_datasets_py.mcp_server.tools.audit_tools.generate_audit_report import generate_audit_report

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_security_report.json")
            result = await generate_audit_report(
                report_type="security",
                output_path=output_path,
                output_format="json"
            )
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["output_path"], output_path)
            self.assertTrue(os.path.exists(output_path))
            with open(output_path, 'r') as f:
                content = json.load(f)
                self.assertEqual(content["report_type"], "security")

    async def test_generate_audit_report_error_handling(self):
        from ipfs_datasets_py.mcp_server.tools.audit_tools.generate_audit_report import generate_audit_report

        # Simulate an error in AuditReportGenerator's method
        with patch('ipfs_datasets_py.audit.audit_reporting.AuditReportGenerator.generate_comprehensive_report', side_effect=Exception("Test error")):
            result = await generate_audit_report(report_type="comprehensive")
            self.assertEqual(result["status"], "error")
            self.assertIn("Test error", result["message"])

    async def test_generate_audit_report_unsupported_type(self):
        from ipfs_datasets_py.mcp_server.tools.audit_tools.generate_audit_report import generate_audit_report

        result = await generate_audit_report(report_type="unsupported_type")
        self.assertEqual(result["status"], "error")
        self.assertIn("Unsupported report_type", result["message"])

if __name__ == '__main__':
    unittest.main()
