#!/usr/bin/env python3
"""
Simple test for the core provenance report formatting functions.
This is a standalone test that doesn't import the actual code, just verifies our logic works.
"""

import unittest
import datetime
import json

class TestProvenanceFunctions(unittest.TestCase):
    """Test the provenance formatting and visualization functions."""
    
    def test_format_report_as_text(self):
        """Test formatting a report as text."""
        # Create a sample report
        report = {
            "data_id": "test_dataset",
            "generated_at": datetime.datetime.now().isoformat(),
            "report_type": "detailed",
            "data_info": {
                "data_id": "test_dataset",
                "data_type": "dataset",
                "source": "test_source",
                "creator": "test_user",
                "creation_time": datetime.datetime.now().isoformat(),
                "version": "1.0"
            },
            "verification": {
                "verification_status": "verified",
                "checksum": "0x123456789abcdef"
            }
        }
        
        # Format as text
        text_report = self._format_report_as_text(report)
        
        # Test the result
        self.assertEqual(text_report["data_id"], "test_dataset")
        self.assertIn("text_content", text_report)
        self.assertIn("PROVENANCE REPORT", text_report["text_content"])
        self.assertIn("DATA INFORMATION", text_report["text_content"])
        self.assertIn("VERIFICATION", text_report["text_content"])
        
    def test_format_report_as_html(self):
        """Test formatting a report as HTML."""
        # Create a sample report
        report = {
            "data_id": "test_dataset",
            "generated_at": datetime.datetime.now().isoformat(),
            "report_type": "detailed",
            "data_info": {
                "data_id": "test_dataset",
                "data_type": "dataset",
                "source": "test_source",
                "creator": "test_user",
                "creation_time": datetime.datetime.now().isoformat(),
                "version": "1.0"
            },
            "verification": {
                "verification_status": "verified",
                "checksum": "0x123456789abcdef"
            }
        }
        
        # Format as HTML
        html_report = self._format_report_as_html(report)
        
        # Test the result
        self.assertEqual(html_report["data_id"], "test_dataset")
        self.assertIn("html_content", html_report)
        self.assertIn("<!DOCTYPE html>", html_report["html_content"])
        self.assertIn("<title>Provenance Report", html_report["html_content"])
        self.assertIn("<h1>Provenance Report", html_report["html_content"])
        self.assertIn("<table>", html_report["html_content"])
        
    def test_format_report_as_markdown(self):
        """Test formatting a report as Markdown."""
        # Create a sample report
        report = {
            "data_id": "test_dataset",
            "generated_at": datetime.datetime.now().isoformat(),
            "report_type": "detailed",
            "data_info": {
                "data_id": "test_dataset",
                "data_type": "dataset",
                "source": "test_source",
                "creator": "test_user",
                "creation_time": datetime.datetime.now().isoformat(),
                "version": "1.0"
            },
            "verification": {
                "verification_status": "verified",
                "checksum": "0x123456789abcdef"
            }
        }
        
        # Format as Markdown
        md_report = self._format_report_as_markdown(report)
        
        # Test the result
        self.assertEqual(md_report["data_id"], "test_dataset")
        self.assertIn("markdown_content", md_report)
        self.assertIn("# Provenance Report", md_report["markdown_content"])
        self.assertIn("## Data Information", md_report["markdown_content"])
        self.assertIn("| Property | Value |", md_report["markdown_content"])
        
    def test_format_lineage_as_dot(self):
        """Test formatting lineage as DOT format."""
        # Create a sample visualization
        visualization = {
            "data_id": "test_dataset",
            "nodes": [
                {"id": "dataset_1", "label": "Dataset 1", "type": "dataset"},
                {"id": "dataset_2", "label": "Dataset 2", "type": "dataset"}
            ],
            "edges": [
                {"source": "dataset_1", "target": "dataset_2", "relationship": "derived_from"}
            ]
        }
        
        # Format as DOT
        dot_visualization = self._format_lineage_as_dot(visualization)
        
        # Test the result
        self.assertEqual(dot_visualization["data_id"], "test_dataset")
        self.assertIn("dot_content", dot_visualization)
        self.assertIn("digraph DataLineage", dot_visualization["dot_content"])
        self.assertIn('"dataset_1" [label="Dataset 1"', dot_visualization["dot_content"])
        self.assertIn('"dataset_1" -> "dataset_2"', dot_visualization["dot_content"])
    
    def _format_report_as_text(self, report):
        """Format the provenance report as human-readable text."""
        text_report = report.copy()
        text_content = []
        
        # Add report header
        text_content.append(f"PROVENANCE REPORT: {report['data_id']}")
        text_content.append(f"Generated: {report['generated_at']}")
        text_content.append(f"Report Type: {report['report_type']}")
        text_content.append("-" * 80)
        
        # Add data information
        text_content.append("DATA INFORMATION:")
        for key, value in report["data_info"].items():
            if value is not None:
                text_content.append(f"  {key}: {value}")
        
        # Add verification information
        text_content.append("\nVERIFICATION:")
        for key, value in report["verification"].items():
            if value is not None:
                text_content.append(f"  {key}: {value}")
        
        # Add lineage information if available
        if "lineage" in report:
            text_content.append("\nLINEAGE INFORMATION:")
            for key, value in report["lineage"].items():
                if value is not None and not isinstance(value, (dict, list)):
                    text_content.append(f"  {key}: {value}")
                    
            # Add upstream/downstream datasets if available
            if "upstream_datasets" in report["lineage"] and report["lineage"]["upstream_datasets"]:
                text_content.append("\n  Upstream Datasets:")
                for ds in report["lineage"]["upstream_datasets"]:
                    text_content.append(f"    - {ds}")
                    
            if "derived_datasets" in report["lineage"] and report["lineage"]["derived_datasets"]:
                text_content.append("\n  Derived Datasets:")
                for ds in report["lineage"]["derived_datasets"]:
                    text_content.append(f"    - {ds}")
        
        # Join all text content
        text_report["text_content"] = "\n".join(text_content)
        return text_report
    
    def _format_report_as_html(self, report):
        """Format the provenance report as HTML."""
        html_report = report.copy()
        html_content = []
        
        # Basic HTML structure
        html_content.append("<!DOCTYPE html>")
        html_content.append("<html>")
        html_content.append("<head>")
        html_content.append(f"<title>Provenance Report: {report['data_id']}</title>")
        html_content.append("<style>")
        html_content.append("body { font-family: Arial, sans-serif; margin: 20px; }")
        html_content.append("h1, h2, h3 { color: #2c3e50; }")
        html_content.append("table { border-collapse: collapse; width: 100%; }")
        html_content.append("th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }")
        html_content.append("th { background-color: #f2f2f2; }")
        html_content.append("tr:nth-child(even) { background-color: #f9f9f9; }")
        html_content.append("</style>")
        html_content.append("</head>")
        html_content.append("<body>")
        
        # Report header
        html_content.append(f"<h1>Provenance Report: {report['data_id']}</h1>")
        html_content.append(f"<p><strong>Generated:</strong> {report['generated_at']}</p>")
        html_content.append(f"<p><strong>Report Type:</strong> {report['report_type']}</p>")
        
        # Data information section
        html_content.append("<h2>Data Information</h2>")
        html_content.append("<table>")
        html_content.append("<tr><th>Property</th><th>Value</th></tr>")
        for key, value in report["data_info"].items():
            if value is not None:
                html_content.append(f"<tr><td>{key}</td><td>{value}</td></tr>")
        html_content.append("</table>")
        
        # Verification section
        html_content.append("<h2>Verification</h2>")
        html_content.append("<table>")
        html_content.append("<tr><th>Property</th><th>Value</th></tr>")
        for key, value in report["verification"].items():
            if value is not None:
                html_content.append(f"<tr><td>{key}</td><td>{value}</td></tr>")
        html_content.append("</table>")
        
        # Close HTML tags
        html_content.append("</body>")
        html_content.append("</html>")
        
        # Join all HTML content
        html_report["html_content"] = "\n".join(html_content)
        return html_report
    
    def _format_report_as_markdown(self, report):
        """Format the provenance report as Markdown."""
        md_report = report.copy()
        md_content = []
        
        # Report header
        md_content.append(f"# Provenance Report: {report['data_id']}")
        md_content.append(f"**Generated:** {report['generated_at']}  ")
        md_content.append(f"**Report Type:** {report['report_type']}  ")
        md_content.append("")
        
        # Data information section
        md_content.append("## Data Information")
        md_content.append("")
        md_content.append("| Property | Value |")
        md_content.append("| -------- | ----- |")
        for key, value in report["data_info"].items():
            if value is not None:
                md_content.append(f"| {key} | {value} |")
        md_content.append("")
        
        # Verification section
        md_content.append("## Verification")
        md_content.append("")
        md_content.append("| Property | Value |")
        md_content.append("| -------- | ----- |")
        for key, value in report["verification"].items():
            if value is not None:
                md_content.append(f"| {key} | {value} |")
        md_content.append("")
        
        # Join all markdown content
        md_report["markdown_content"] = "\n".join(md_content)
        return md_report
    
    def _format_lineage_as_dot(self, visualization):
        """Format lineage visualization as DOT format for GraphViz."""
        dot_visualization = visualization.copy()
        dot_lines = []
        
        # Start the digraph
        dot_lines.append(f'digraph DataLineage {{')
        dot_lines.append('  rankdir=LR;')
        dot_lines.append('  node [shape=box, style=filled];')
        
        # Add nodes
        for node in visualization["nodes"]:
            node_id = node["id"]
            label = node["label"]
            node_type = node.get("type", "unknown")
            
            # Choose color based on node type
            color = "#a1d99b"  # Default green
            if node_type == "model":
                color = "#9ecae1"  # Blue
            elif node_type == "index":
                color = "#bcbddc"  # Purple
            
            # Add node with attributes
            dot_lines.append(f'  "{node_id}" [label="{label}", fillcolor="{color}"];')
        
        # Add edges
        for edge in visualization["edges"]:
            source = edge["source"]
            target = edge["target"]
            relationship = edge["relationship"]
            
            # Add edge with label
            dot_lines.append(f'  "{source}" -> "{target}" [label="{relationship}"];')
        
        # Close the graph
        dot_lines.append('}')
        
        # Join all DOT content
        dot_visualization["dot_content"] = "\n".join(dot_lines)
        return dot_visualization


if __name__ == "__main__":
    unittest.main()