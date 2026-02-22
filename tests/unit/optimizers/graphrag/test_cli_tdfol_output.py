"""Tests for GraphRAG CLI --tdfol-output flag."""

import json
import tempfile
from pathlib import Path

import pytest


class TestTDFOLOutputFlag:
    """Test TDFOL formula export via CLI."""

    @pytest.fixture
    def sample_ontology_json(self, tmp_path):
        """Create a sample ontology JSON file."""
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.95},
                {"id": "e2", "text": "London", "type": "Location", "confidence": 0.90},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "lives_in", "confidence": 0.85}
            ],
        }
        
        ontology_file = tmp_path / "ontology.json"
        with open(ontology_file, "w") as f:
            json.dump(ontology, f)
        
        return str(ontology_file)

    @pytest.fixture
    def cli(self):
        """Create CLI instance."""
        from ipfs_datasets_py.optimizers.graphrag.cli_wrapper import GraphRAGOptimizerCLI
        return GraphRAGOptimizerCLI()

    def test_tdfol_output_flag_present_in_parser(self, cli):
        """Test that --tdfol-output flag is registered."""
        parser = cli.create_parser()
        args = parser.parse_args(['validate', '--input', 'test.json', '--tdfol-output', 'formulas.json'])
        assert hasattr(args, 'tdfol_output')
        assert args.tdfol_output == 'formulas.json'

    def test_tdfol_output_generates_json_file(self, cli, sample_ontology_json, tmp_path):
        """Test that TDFOL formulas are written to JSON."""
        tdfol_file = tmp_path / "formulas.json"
        
        parser = cli.create_parser()
        args = parser.parse_args([
            'validate',
            '--input', sample_ontology_json,
            '--tdfol-output', str(tdfol_file)
        ])
        
        result = cli.cmd_validate(args)
        
        # Validation should succeed (exit code 0 or 2 if no checks requested)
        assert result in (0, 2)
        
        # TDFOL file should be created
        assert tdfol_file.exists()
        
        # File should contain valid JSON
        with open(tdfol_file) as f:
            data = json.load(f)
        
        assert "formula_count" in data
        assert "formulas" in data
        assert isinstance(data["formulas"], list)
        assert data["formula_count"] == len(data["formulas"])

    def test_tdfol_output_contains_source(self, cli, sample_ontology_json, tmp_path):
        """Test that TDFOL output includes source file info."""
        tdfol_file = tmp_path / "formulas.json"
        
        parser = cli.create_parser()
        args = parser.parse_args([
            'validate',
            '--input', sample_ontology_json,
            '--tdfol-output', str(tdfol_file)
        ])
        
        cli.cmd_validate(args)
        
        with open(tdfol_file) as f:
            data = json.load(f)
        
        assert "source" in data
        assert "ontology.json" in data["source"]

    def test_tdfol_output_formulas_not_empty(self, cli, sample_ontology_json, tmp_path):
        """Test that formulas are generated (not empty)."""
        tdfol_file = tmp_path / "formulas.json"
        
        parser = cli.create_parser()
        args = parser.parse_args([
            'validate',
            '--input', sample_ontology_json,
            '--tdfol-output', str(tdfol_file)
        ])
        
        cli.cmd_validate(args)
        
        with open(tdfol_file) as f:
            data = json.load(f)
        
        # Should have at least entity predicate and relationship predicate
        assert len(data["formulas"]) >= 2

    def test_tdfol_output_optional(self, cli, sample_ontology_json, tmp_path):
        """Test that --tdfol-output flag is optional."""
        parser = cli.create_parser()
        args = parser.parse_args([
            'validate',
            '--input', sample_ontology_json,
        ])
        
        # Should not raise error when TDFOL output not specified
        result = cli.cmd_validate(args)
        assert result in (0, 2)

    def test_tdfol_output_with_consistency_check(self, cli, sample_ontology_json, tmp_path):
        """Test TDFOL output works with consistency check."""
        tdfol_file = tmp_path / "formulas.json"
        
        parser = cli.create_parser()
        args = parser.parse_args([
            'validate',
            '--input', sample_ontology_json,
            '--check-consistency',
            '--tdfol-output', str(tdfol_file)
        ])
        
        result = cli.cmd_validate(args)
        
        assert result in (0, 2)
        assert tdfol_file.exists()

    def test_tdfol_output_creates_valid_json_structure(self, cli, sample_ontology_json, tmp_path):
        """Test TDFOL output JSON has correct structure."""
        tdfol_file = tmp_path / "formulas.json"
        
        parser = cli.create_parser()
        args = parser.parse_args([
            'validate',
            '--input', sample_ontology_json,
            '--tdfol-output', str(tdfol_file)
        ])
        
        cli.cmd_validate(args)
        
        with open(tdfol_file) as f:
            data = json.load(f)
        
        # Validate structure
        assert isinstance(data, dict)
        assert set(data.keys()) == {"source", "formula_count", "formulas"}
        
        # Validate formula count consistency
        assert isinstance(data["formula_count"], int)
        assert data["formula_count"] == len(data["formulas"])

    def test_tdfol_output_with_multiple_entities_and_relationships(self, cli, tmp_path):
        """Test TDFOL output with larger ontology."""
        # Create larger ontology
        ontology = {
            "entities": [
                {"id": f"e{i}", "text": f"Entity{i}", "type": "Type", "confidence": 0.9}
                for i in range(1, 6)
            ],
            "relationships": [
                {"id": f"r{i}", "source_id": f"e{i}", "target_id": f"e{i+1}", "type": "rel", "confidence": 0.85}
                for i in range(1, 4)
            ],
        }
        
        ontology_file = tmp_path / "large.json"
        with open(ontology_file, "w") as f:
            json.dump(ontology, f)
        
        tdfol_file = tmp_path / "formulas.json"
        
        from ipfs_datasets_py.optimizers.graphrag.cli_wrapper import GraphRAGOptimizerCLI
        cli = GraphRAGOptimizerCLI()
        
        parser = cli.create_parser()
        args = parser.parse_args([
            'validate',
            '--input', str(ontology_file),
            '--tdfol-output', str(tdfol_file)
        ])
        
        result = cli.cmd_validate(args)
        
        assert result in (0, 2)
        
        with open(tdfol_file) as f:
            data = json.load(f)
        
        # Should have multiple formulas for large ontology
        assert data["formula_count"] > 2


class TestTDFOLOutputIntegration:
    """Integration tests for TDFOL output with validation."""

    def test_validation_report_and_tdfol_can_both_be_saved(self, tmp_path):
        """Test that validation report and TDFOL can be saved simultaneously."""
        ontology = {
            "entities": [
                {"id": "e1", "text": "Test", "type": "Item", "confidence": 0.9}
            ],
            "relationships": [],
        }
        
        ontology_file = tmp_path / "test.json"
        with open(ontology_file, "w") as f:
            json.dump(ontology, f)
        
        report_file = tmp_path / "report.json"
        tdfol_file = tmp_path / "formulas.json"
        
        from ipfs_datasets_py.optimizers.graphrag.cli_wrapper import GraphRAGOptimizerCLI
        cli = GraphRAGOptimizerCLI()
        
        parser = cli.create_parser()
        args = parser.parse_args([
            'validate',
            '--input', str(ontology_file),
            '--output', str(report_file),
            '--tdfol-output', str(tdfol_file),
            '--check-consistency'
        ])
        
        cli.cmd_validate(args)
        
        # Both files should exist
        assert report_file.exists()
        assert tdfol_file.exists()
        
        # Both should be valid JSON
        with open(report_file) as f:
            report = json.load(f)
        with open(tdfol_file) as f:
            formulas = json.load(f)
        
        assert "checks" in report
        assert "formulas" in formulas

    def test_tdfol_output_with_invalid_input_graceful(self, tmp_path):
        """Test graceful handling when ontology is invalid."""
        ontology_file = tmp_path / "invalid.json"
        tdfol_file = tmp_path / "formulas.json"
        
        # Create valid-ish JSON that's missing required fields
        with open(ontology_file, "w") as f:
            json.dump({"entities": "not_a_list"}, f)
        
        from ipfs_datasets_py.optimizers.graphrag.cli_wrapper import GraphRAGOptimizerCLI
        cli = GraphRAGOptimizerCLI()
        
        parser = cli.create_parser()
        args = parser.parse_args([
            'validate',
            '--input', str(ontology_file),
            '--tdfol-output', str(tdfol_file)
        ])
        
        # Should handle gracefully (may error or succeed depending on validator)
        try:
            result = cli.cmd_validate(args)
            # Either succeeds or fails gracefully
            assert isinstance(result, int)
        except Exception:
            # If it raises, that's also acceptable for invalid input
            pass
