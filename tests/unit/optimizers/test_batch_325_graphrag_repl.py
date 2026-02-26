"""
Batch 325: Interactive GraphRAG REPL Mode
=========================================

Implements an interactive REPL (Read-Eval-Print Loop) for the GraphRAG CLI with
command autocomplete and session management.

Goal: Provide an interactive command-line interface for:
- Loading and extracting ontologies from documents
- Validating and criticizing ontologies
- Managing ontology sessions with save/load
- Real-time command autocomplete
"""

import pytest
import tempfile
import json
from pathlib import Path
from typing import List, Dict, Any
from unittest.mock import Mock, patch, MagicMock
from io import StringIO


class GraphRAGREPLSession:
    """REPL session for interactive GraphRAG operations."""
    
    # Available commands
    COMMANDS = {
        "extract": "Extract entities from a text file: extract <path> [domain]",
        "validate": "Validate the current ontology",
        "criticize": "Evaluate the current ontology",
        "save": "Save the current ontology: save <path>",
        "load": "Load an ontology: load <path>",
        "show": "Display the current ontology",
        "clear": "Clear the current ontology",
        "help": "Show available commands",
        "exit": "Exit the REPL",
        "quit": "Alias for exit",
    }
    
    # Available domains for autocomplete
    DOMAINS = ["general", "legal", "medical", "technical", "financial"]
    
    def __init__(self):
        """Initialize REPL session."""
        self.ontology = None
        self.ontology_path = None
        self.generator = None
        self.critic = None
        self.validator = None
        self.history = []
        self.domains = self.DOMAINS.copy()
    
    def get_command_completions(self, prefix: str) -> List[str]:
        """Get command completions for a prefix.
        
        Args:
            prefix: Command prefix
            
        Returns:
            List of matching commands
        """
        return [cmd for cmd in self.COMMANDS.keys() if cmd.startswith(prefix)]
    
    def get_domain_completions(self, prefix: str) -> List[str]:
        """Get domain completions for a prefix.
        
        Args:
            prefix: Domain prefix
            
        Returns:
            List of matching domains
        """
        return [d for d in self.domains if d.startswith(prefix)]
    
    def get_file_completions(self, prefix: str) -> List[str]:
        """Get file path completions for a prefix.
        
        Args:
            prefix: File path prefix
            
        Returns:
            List of matching file paths
        """
        try:
            path = Path(prefix)
            if path.is_dir():
                base_dir = path
                name_prefix = ""
            else:
                base_dir = path.parent if path.parent.exists() else Path.cwd()
                name_prefix = path.name
            
            matches = []
            for item in base_dir.iterdir():
                if item.name.startswith(name_prefix):
                    matches.append(str(item))
            return matches[:10]  # Limit to 10 results
        except (OSError, ValueError):
            return []
    
    def parse_command(self, line: str) -> tuple[str, List[str]]:
        """Parse a command line.
        
        Args:
            line: Command line string
            
        Returns:
            Tuple of (command, args)
        """
        parts = line.strip().split()
        if not parts:
            return "", []
        return parts[0].lower(), parts[1:]
    
    def execute_extract(self, args: List[str]) -> Dict[str, Any]:
        """Execute extract command.
        
        Args:
            args: Command arguments [path, domain?]
            
        Returns:
            Result dictionary
        """
        if not args:
            return {"error": "Usage: extract <path> [domain]"}
        
        file_path = Path(args[0])
        domain = args[1] if len(args) > 1 else "general"
        
        if not file_path.exists():
            return {"error": f"File not found: {file_path}"}
        
        try:
            with open(file_path, 'r') as f:
                text = f.read()
            
            # Mock extraction (in real implementation, use OntologyGenerator)
            # Ensure at least 1 entity for any non-empty text
            word_count = len(text.split())
            entity_count = max(word_count // 10, 1) if text.strip() else 0
            relationship_count = max(entity_count // 3, 0) if entity_count > 1 else 0
            
            self.ontology = {
                "entities": [{"id": f"e{i}", "type": "entity"} for i in range(entity_count)],
                "relationships": [{"id": f"r{i}", "source": f"e{i}", "target": f"e{(i+1) % entity_count}"} 
                                 for i in range(relationship_count)],
                "metadata": {
                    "source": str(file_path),
                    "domain": domain,
                    "entity_count": entity_count,
                    "relationship_count": relationship_count,
                }
            }
            
            result = {
                "success": True,
                "message": f"Extracted {entity_count} entities and {relationship_count} relationships from {file_path.name}",
                "entity_count": entity_count,
                "relationship_count": relationship_count,
            }
            self.history.append(("extract", result))
            return result
        except Exception as e:
            return {"error": f"Extraction failed: {str(e)}"}
    
    def execute_validate(self, args: List[str]) -> Dict[str, Any]:
        """Execute validate command.
        
        Args:
            args: Command arguments (unused)
            
        Returns:
            Result dictionary
        """
        if not self.ontology:
            return {"error": "No ontology loaded"}
        
        entity_count = len(self.ontology.get("entities", []))
        relationship_count = len(self.ontology.get("relationships", []))
        
        # Mock validation
        errors = []
        if entity_count == 0:
            errors.append("No entities in ontology")
        # Only require relationships if there are 2+ entities
        if relationship_count == 0 and entity_count > 2:
            errors.append("No relationships defined")
        
        result = {
            "success": len(errors) == 0,
            "valid": len(errors) == 0,
            "error_count": len(errors),
            "errors": errors,
            "entity_count": entity_count,
            "relationship_count": relationship_count,
        }
        self.history.append(("validate", result))
        return result
    
    def execute_criticize(self, args: List[str]) -> Dict[str, Any]:
        """Execute criticize command.
        
        Args:
            args: Command arguments (unused)
            
        Returns:
            Result dictionary
        """
        if not self.ontology:
            return {"error": "No ontology loaded"}
        
        # Mock criticism with sample dimensions
        score = {
            "completeness": 0.75,
            "consistency": 0.85,
            "connectivity": 0.70,
            "clarity": 0.80,
            "domain_alignment": 0.72,
            "overall": 0.76,
        }
        
        result = {
            "success": True,
            "scores": score,
            "recommendations": [
                "Add more relationships to improve connectivity",
                "Review domain alignment for specialized terms",
            ]
        }
        self.history.append(("criticize", result))
        return result
    
    def execute_save(self, args: List[str]) -> Dict[str, Any]:
        """Execute save command.
        
        Args:
            args: Command arguments [path]
            
        Returns:
            Result dictionary
        """
        if not args:
            return {"error": "Usage: save <path>"}
        
        if not self.ontology:
            return {"error": "No ontology to save"}
        
        file_path = Path(args[0])
        try:
            with open(file_path, 'w') as f:
                json.dump(self.ontology, f, indent=2)
            
            self.ontology_path = file_path
            result = {
                "success": True,
                "message": f"Ontology saved to {file_path}",
                "path": str(file_path),
            }
            self.history.append(("save", result))
            return result
        except Exception as e:
            return {"error": f"Save failed: {str(e)}"}
    
    def execute_load(self, args: List[str]) -> Dict[str, Any]:
        """Execute load command.
        
        Args:
            args: Command arguments [path]
            
        Returns:
            Result dictionary
        """
        if not args:
            return {"error": "Usage: load <path>"}
        
        file_path = Path(args[0])
        if not file_path.exists():
            return {"error": f"File not found: {file_path}"}
        
        try:
            with open(file_path, 'r') as f:
                self.ontology = json.load(f)
            
            self.ontology_path = file_path
            result = {
                "success": True,
                "message": f"Ontology loaded from {file_path}",
                "path": str(file_path),
                "entity_count": len(self.ontology.get("entities", [])),
                "relationship_count": len(self.ontology.get("relationships", [])),
            }
            self.history.append(("load", result))
            return result
        except Exception as e:
            return {"error": f"Load failed: {str(e)}"}
    
    def execute_show(self, args: List[str]) -> Dict[str, Any]:
        """Execute show command.
        
        Args:
            args: Command arguments (unused)
            
        Returns:
            Result dictionary
        """
        if not self.ontology:
            return {"error": "No ontology loaded"}
        
        entity_count = len(self.ontology.get("entities", []))
        relationship_count = len(self.ontology.get("relationships", []))
        
        result = {
            "success": True,
            "entity_count": entity_count,
            "relationship_count": relationship_count,
            "metadata": self.ontology.get("metadata", {}),
            "path": str(self.ontology_path) if self.ontology_path else None,
        }
        return result
    
    def execute_clear(self, args: List[str]) -> Dict[str, Any]:
        """Execute clear command.
        
        Args:
            args: Command arguments (unused)
            
        Returns:
            Result dictionary
        """
        self.ontology = None
        self.ontology_path = None
        
        result = {
            "success": True,
            "message": "Ontology cleared",
        }
        self.history.append(("clear", result))
        return result
    
    def execute_help(self, args: List[str]) -> Dict[str, Any]:
        """Execute help command.
        
        Args:
            args: Optional command name to get help for
            
        Returns:
            Result dictionary
        """
        if args and args[0] in self.COMMANDS:
            return {
                "success": True,
                "command": args[0],
                "help": self.COMMANDS[args[0]],
            }
        
        return {
            "success": True,
            "commands": self.COMMANDS,
            "domains": self.DOMAINS,
        }
    
    def execute_command(self, line: str) -> Dict[str, Any]:
        """Execute a command line.
        
        Args:
            line: Command line string
            
        Returns:
            Result dictionary
        """
        command, args = self.parse_command(line)
        
        if not command:
            return {"error": "No command provided"}
        
        if command in ("exit", "quit"):
            return {"success": True, "exit": True}
        
        if command == "extract":
            return self.execute_extract(args)
        elif command == "validate":
            return self.execute_validate(args)
        elif command == "criticize":
            return self.execute_criticize(args)
        elif command == "save":
            return self.execute_save(args)
        elif command == "load":
            return self.execute_load(args)
        elif command == "show":
            return self.execute_show(args)
        elif command == "clear":
            return self.execute_clear(args)
        elif command == "help":
            return self.execute_help(args)
        else:
            return {"error": f"Unknown command: {command}"}


# ============================================================================
# TEST CLASSES
# ============================================================================

class TestREPLSessionBasics:
    """Test basic REPL session operations."""
    
    def test_create_session(self):
        """Test creating a REPL session."""
        session = GraphRAGREPLSession()
        assert session.ontology is None
        assert session.ontology_path is None
        assert len(session.history) == 0
        assert len(session.COMMANDS) > 0
    
    def test_get_command_completions(self):
        """Test getting command completions."""
        session = GraphRAGREPLSession()
        
        # Test prefix matching
        assert "extract" in session.get_command_completions("ex")
        assert "validate" in session.get_command_completions("va")
        assert "save" in session.get_command_completions("sa")
        assert "load" in session.get_command_completions("lo")
        
        # Test no matches
        assert len(session.get_command_completions("xyz")) == 0
    
    def test_get_domain_completions(self):
        """Test getting domain completions."""
        session = GraphRAGREPLSession()
        
        assert "legal" in session.get_domain_completions("le")
        assert "medical" in session.get_domain_completions("me")
        assert "technical" in session.get_domain_completions("te")
    
    def test_parse_command(self):
        """Test parsing command lines."""
        session = GraphRAGREPLSession()
        
        cmd, args = session.parse_command("extract /path/to/file.txt legal")
        assert cmd == "extract"
        assert args == ["/path/to/file.txt", "legal"]
        
        cmd, args = session.parse_command("validate")
        assert cmd == "validate"
        assert args == []
        
        cmd, args = session.parse_command("")
        assert cmd == ""
        assert args == []
    
    def test_extract_command_missing_file(self):
        """Test extract command with missing file."""
        session = GraphRAGREPLSession()
        result = session.execute_extract(["/nonexistent/file.txt"])
        
        assert "error" in result
        assert "File not found" in result["error"]
    
    def test_extract_command_no_args(self):
        """Test extract command with no arguments."""
        session = GraphRAGREPLSession()
        result = session.execute_extract([])
        
        assert "error" in result
        assert "Usage" in result["error"]


class TestREPLExtractCommand:
    """Test extract command functionality."""
    
    def test_extract_with_file(self):
        """Test extracting ontology from file."""
        session = GraphRAGREPLSession()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("The patient presented with symptoms. The doctor examined the patient.")
            f.flush()
            
            try:
                result = session.execute_extract([f.name])
                
                assert result["success"] is True
                assert result["entity_count"] > 0
                assert "entities" in session.ontology
                assert "relationships" in session.ontology
                assert len(session.history) == 1
                assert session.history[0][0] == "extract"
            finally:
                Path(f.name).unlink()
    
    def test_extract_with_domain(self):
        """Test extracting with domain specification."""
        session = GraphRAGREPLSession()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("The court issued a ruling on the legal matter.")
            f.flush()
            
            try:
                result = session.execute_extract([f.name, "legal"])
                
                assert result["success"] is True
                assert session.ontology["metadata"]["domain"] == "legal"
            finally:
                Path(f.name).unlink()


class TestREPLValidateCommand:
    """Test validate command functionality."""
    
    def test_validate_without_ontology(self):
        """Test validation without loaded ontology."""
        session = GraphRAGREPLSession()
        result = session.execute_validate([])
        
        assert "error" in result
        assert "No ontology" in result["error"]
    
    def test_validate_with_ontology(self):
        """Test validation with loaded ontology."""
        session = GraphRAGREPLSession()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test entity one. Test entity two. Connection between them.")
            f.flush()
            
            try:
                session.execute_extract([f.name])
                result = session.execute_validate([])
                
                assert result["valid"] is True
                assert result["error_count"] == 0
                assert result["entity_count"] > 0
            finally:
                Path(f.name).unlink()


class TestREPLCriticizeCommand:
    """Test criticize command functionality."""
    
    def test_criticize_without_ontology(self):
        """Test criticism without loaded ontology."""
        session = GraphRAGREPLSession()
        result = session.execute_criticize([])
        
        assert "error" in result
        assert "No ontology" in result["error"]
    
    def test_criticize_with_ontology(self):
        """Test criticism with loaded ontology."""
        session = GraphRAGREPLSession()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Entity relationships matter. They define structure.")
            f.flush()
            
            try:
                session.execute_extract([f.name])
                result = session.execute_criticize([])
                
                assert result["success"] is True
                assert "scores" in result
                assert result["scores"]["overall"] > 0
                assert result["scores"]["overall"] <= 1.0
            finally:
                Path(f.name).unlink()


class TestREPLPersistence:
    """Test save/load functionality."""
    
    def test_save_ontology(self):
        """Test saving ontology to file."""
        session = GraphRAGREPLSession()
        
        # Create an ontology
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Sample text for extraction.")
            f.flush()
            
            try:
                session.execute_extract([f.name])
                
                # Save to file
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as save_file:
                    try:
                        result = session.execute_save([save_file.name])
                        
                        assert result["success"] is True
                        assert Path(save_file.name).exists()
                        assert session.ontology_path == Path(save_file.name)
                    finally:
                        Path(save_file.name).unlink()
            finally:
                Path(f.name).unlink()
    
    def test_load_ontology(self):
        """Test loading ontology from file."""
        old_session = GraphRAGREPLSession()
        
        # Create and save an ontology
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as text_file:
            text_file.write("Original text for ontology.")
            text_file.flush()
            
            try:
                old_session.execute_extract([text_file.name])
                
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as save_file:
                    try:
                        old_session.execute_save([save_file.name])
                        
                        # Load in new session
                        new_session = GraphRAGREPLSession()
                        result = new_session.execute_load([save_file.name])
                        
                        assert result["success"] is True
                        assert new_session.ontology is not None
                        assert new_session.ontology_path == Path(save_file.name)
                        assert result["entity_count"] == old_session.ontology["metadata"]["entity_count"]
                    finally:
                        Path(save_file.name).unlink()
            finally:
                Path(text_file.name).unlink()


class TestREPLSessionManagement:
    """Test REPL session management commands."""
    
    def test_show_command(self):
        """Test show command."""
        session = GraphRAGREPLSession()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test content for ontology display.")
            f.flush()
            
            try:
                session.execute_extract([f.name])
                result = session.execute_show([])
                
                assert result["success"] is True
                assert result["entity_count"] > 0
            finally:
                Path(f.name).unlink()
    
    def test_show_empty_session(self):
        """Test show command on empty session."""
        session = GraphRAGREPLSession()
        result = session.execute_show([])
        
        assert "error" in result
        assert "No ontology" in result["error"]
    
    def test_clear_command(self):
        """Test clearing session."""
        session = GraphRAGREPLSession()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Content to extract.")
            f.flush()
            
            try:
                session.execute_extract([f.name])
                assert session.ontology is not None
                
                result = session.execute_clear([])
                
                assert result["success"] is True
                assert session.ontology is None
                assert session.ontology_path is None
            finally:
                Path(f.name).unlink()
    
    def test_help_command(self):
        """Test help command."""
        session = GraphRAGREPLSession()
        result = session.execute_help([])
        
        assert result["success"] is True
        assert "commands" in result
        assert len(result["commands"]) > 0
    
    def test_help_for_command(self):
        """Test help for specific command."""
        session = GraphRAGREPLSession()
        result = session.execute_help(["extract"])
        
        assert result["success"] is True
        assert "extract" in result["command"]
        assert "help" in result


class TestREPLCommandExecution:
    """Test command execution flow."""
    
    def test_execute_full_workflow(self):
        """Test a complete REPL workflow."""
        session = GraphRAGREPLSession()
        
        # Create temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("The entity performed an action. The action had consequences.")
            f.flush()
            
            try:
                # Extract
                result = session.execute_command(f"extract {f.name}")
                assert result["success"] is True
                
                # Validate
                result = session.execute_command("validate")
                assert result["valid"] is True
                
                # Criticize
                result = session.execute_command("criticize")
                assert result["success"] is True
                
                # Show
                result = session.execute_command("show")
                assert result["success"] is True
                
                # Clear
                result = session.execute_command("clear")
                assert result["success"] is True
                
                # Verify cleared
                result = session.execute_command("show")
                assert "error" in result
            finally:
                Path(f.name).unlink()
    
    def test_exit_command(self):
        """Test exit command."""
        session = GraphRAGREPLSession()
        result = session.execute_command("exit")
        
        assert result["success"] is True
        assert result.get("exit") is True
    
    def test_unknown_command(self):
        """Test unknown command handling."""
        session = GraphRAGREPLSession()
        result = session.execute_command("invalid_command")
        
        assert "error" in result
        assert "Unknown command" in result["error"]


class TestREPLCommandHistory:
    """Test command history tracking."""
    
    def test_history_tracking(self):
        """Test that command history is tracked."""
        session = GraphRAGREPLSession()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test content.")
            f.flush()
            
            try:
                session.execute_extract([f.name])
                session.execute_validate([])
                session.execute_clear([])
                
                assert len(session.history) == 3
                assert session.history[0][0] == "extract"
                assert session.history[1][0] == "validate"
                assert session.history[2][0] == "clear"
            finally:
                Path(f.name).unlink()
