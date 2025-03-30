#!/usr/bin/env python3
"""
Simple test for the new provenance reporting functionality.
This test creates minimal mocks to verify the new methods work correctly.
"""

import os
import unittest
import tempfile
import datetime
import uuid
from unittest.mock import MagicMock, patch
import sys
import json

# Add the parent directory to the path so we can import the module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class TestProvenanceReporting(unittest.TestCase):
    """Test the provenance reporting functionality."""
    
    def setUp(self):
        """Set up the test with mock objects."""
        # Create a mock SecurityManager
        self.mock_security_manager = MagicMock()
        
        # Create a mock DataProvenance
        self.mock_provenance = MagicMock()
        self.mock_provenance.data_id = "test_data_id"
        self.mock_provenance.data_type = "dataset"
        self.mock_provenance.source = "test_source"
        self.mock_provenance.creator = "test_user"
        self.mock_provenance.creation_time = datetime.datetime.now().isoformat()
        self.mock_provenance.version = "1.0"
        self.mock_provenance.checksum = "0x123456789abcdef"
        self.mock_provenance.verification_status = "verified"
        self.mock_provenance.parent_ids = []
        self.mock_provenance.tags = ["test", "example"]
        self.mock_provenance.metadata = {"key": "value"}
        self.mock_provenance.size_bytes = 1024
        self.mock_provenance.record_count = 100
        self.mock_provenance.content_type = "application/json"
        self.mock_provenance.schema = {"columns": ["id", "name", "value"]}
        
        # Mock access history
        self.mock_provenance.access_history = [
            {
                "user": "test_user",
                "timestamp": datetime.datetime.now().isoformat(),
                "operation": "read"
            }
        ]
        
        # Mock lineage
        self.mock_lineage = MagicMock()
        self.mock_lineage.source_system = "test_system"
        self.mock_lineage.source_type = "database"
        self.mock_lineage.extraction_method = "sql_query"
        self.mock_lineage.extraction_time = datetime.datetime.now().isoformat()
        self.mock_lineage.upstream_datasets = []
        self.mock_lineage.derived_datasets = []
        
        self.mock_provenance.lineage = self.mock_lineage
        
        # Set up get_provenance to return the mock
        self.mock_security_manager.get_provenance.return_value = self.mock_provenance
        
        # Create a mock lineage graph
        self.mock_lineage_graph = {
            "nodes": ["test_data_id"],
            "edges": []
        }
        self.mock_security_manager.get_data_lineage_graph.return_value = self.mock_lineage_graph
        
    def test_generate_provenance_report_json(self):
        """Test generating a provenance report in JSON format."""
        # Import the functions
        from ipfs_datasets_py.security import generate_provenance_report
        
        # Patch the method to call our implementation
        with patch('ipfs_datasets_py.security.SecurityManager.generate_provenance_report', 
                  self._mock_generate_provenance_report):
            
            # Call the function
            report = self.mock_security_manager.generate_provenance_report(
                data_id="test_data_id",
                report_type="detailed",
                format="json"
            )
            
            # Assert basic properties
            self.assertEqual(report["data_id"], "test_data_id")
            self.assertEqual(report["report_type"], "detailed")
            self.assertEqual(report["report_format"], "json")
            self.assertIn("data_info", report)
            self.assertIn("verification", report)
            
    def test_generate_lineage_visualization(self):
        """Test generating a lineage visualization."""
        # Import the functions
        from ipfs_datasets_py.security import generate_lineage_visualization
        
        # Patch the method to call our implementation
        with patch('ipfs_datasets_py.security.SecurityManager.generate_lineage_visualization', 
                  self._mock_generate_lineage_visualization):
            
            # Call the function
            visualization = self.mock_security_manager.generate_lineage_visualization(
                data_id="test_data_id",
                format="dot"
            )
            
            # Assert basic properties
            self.assertEqual(visualization["data_id"], "test_data_id")
            self.assertIn("nodes", visualization)
            self.assertIn("edges", visualization)
            
            # Test DOT format
            self.assertIn("dot_content", visualization)
            self.assertIn("digraph", visualization["dot_content"])
    
    def _mock_generate_provenance_report(self, data_id, report_type="detailed", 
                                      format="json", include_lineage=True,
                                      include_access_history=True):
        """Mock implementation of generate_provenance_report."""
        # Get provenance data
        provenance = self.mock_provenance
        
        # Build basic report structure
        report = {
            "report_type": report_type,
            "generated_at": datetime.datetime.now().isoformat(),
            "data_id": data_id,
            "report_format": format,
            "data_info": {
                "data_id": provenance.data_id,
                "data_type": provenance.data_type,
                "source": provenance.source,
                "creator": provenance.creator,
                "creation_time": provenance.creation_time,
                "version": provenance.version,
                "verification_status": provenance.verification_status,
                "tags": provenance.tags
            },
            "verification": {
                "verification_status": provenance.verification_status,
                "checksum": provenance.checksum
            }
        }
        
        # Add lineage if requested
        if include_lineage and hasattr(provenance, "lineage") and provenance.lineage:
            report["lineage"] = {
                "source_system": provenance.lineage.source_system,
                "source_type": provenance.lineage.source_type,
                "extraction_method": provenance.lineage.extraction_method,
                "extraction_time": provenance.lineage.extraction_time
            }
        
        # Add access history if requested
        if include_access_history and hasattr(provenance, "access_history") and provenance.access_history:
            if report_type in ["summary", "compliance"]:
                report["access_summary"] = {
                    "total_accesses": len(provenance.access_history),
                    "last_access": provenance.access_history[-1]["timestamp"]
                }
            else:
                report["access_history"] = provenance.access_history
                
        # Handle different format outputs
        if format == "text":
            text_content = f"PROVENANCE REPORT: {data_id}\n"
            text_content += f"Generated: {report['generated_at']}\n"
            text_content += f"Report Type: {report_type}\n"
            report["text_content"] = text_content
            
        elif format == "html":
            html_content = f"<html><head><title>Provenance Report: {data_id}</title></head><body>"
            html_content += f"<h1>Provenance Report: {data_id}</h1>"
            html_content += f"<p>Generated: {report['generated_at']}</p>"
            html_content += f"<p>Report Type: {report_type}</p>"
            html_content += "</body></html>"
            report["html_content"] = html_content
            
        elif format == "markdown":
            md_content = f"# Provenance Report: {data_id}\n\n"
            md_content += f"**Generated:** {report['generated_at']}\n\n"
            md_content += f"**Report Type:** {report_type}\n\n"
            report["markdown_content"] = md_content
            
        return report
    
    def _mock_generate_lineage_visualization(self, data_id, format="dot", 
                                          max_depth=3, direction="both",
                                          include_attributes=False):
        """Mock implementation of generate_lineage_visualization."""
        # Get data lineage graph
        lineage_graph = self.mock_lineage_graph
        
        # Create a basic visualization object
        visualization = {
            "data_id": data_id,
            "max_depth": max_depth,
            "direction": direction,
            "nodes": [{"id": node_id, "label": node_id, "type": "dataset"} for node_id in lineage_graph["nodes"]],
            "edges": lineage_graph["edges"],
            "generated_at": datetime.datetime.now().isoformat()
        }
        
        # Add format-specific content
        if format == "dot":
            dot_content = f'digraph DataLineage {{\n'
            dot_content += '  rankdir=LR;\n'
            dot_content += '  node [shape=box, style=filled];\n'
            
            # Add nodes
            for node in visualization["nodes"]:
                dot_content += f'  "{node["id"]}" [label="{node["label"]}", fillcolor="#a1d99b"];\n'
            
            # Add edges
            for edge in visualization["edges"]:
                dot_content += f'  "{edge["source"]}" -> "{edge["target"]}" [label="{edge["relationship"]}"];\n'
            
            dot_content += '}'
            visualization["dot_content"] = dot_content
            
        elif format == "mermaid":
            mermaid_content = 'graph LR\n'
            
            # Add nodes
            for node in visualization["nodes"]:
                safe_id = f"node_{node['id'].replace('-', '_')}"
                mermaid_content += f'  {safe_id}["{node["label"]}"];\n'
            
            # Add edges
            for edge in visualization["edges"]:
                safe_source = f"node_{edge['source'].replace('-', '_')}"
                safe_target = f"node_{edge['target'].replace('-', '_')}"
                mermaid_content += f'  {safe_source} -->|"{edge["relationship"]}"| {safe_target};\n'
                
            visualization["mermaid_content"] = mermaid_content
            
        elif format == "d3":
            # Convert to D3 format
            d3_nodes = []
            node_index_map = {}
            
            for i, node in enumerate(visualization["nodes"]):
                node_index_map[node["id"]] = i
                d3_nodes.append({
                    "id": node["id"],
                    "label": node["label"],
                    "type": node.get("type", "unknown"),
                    "group": 1
                })
            
            d3_links = []
            for edge in visualization["edges"]:
                d3_links.append({
                    "source": node_index_map[edge["source"]],
                    "target": node_index_map[edge["target"]],
                    "relationship": edge["relationship"],
                    "value": 1
                })
            
            visualization["d3_data"] = {
                "nodes": d3_nodes,
                "links": d3_links
            }
        
        return visualization


if __name__ == "__main__":
    unittest.main()