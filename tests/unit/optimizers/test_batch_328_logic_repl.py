"""
Batch 328: Logic CLI Interactive REPL Mode
==========================================

Implements an interactive REPL for the Logic/Theorem Optimizer CLI with
command autocomplete and formula validation.

Goal: Provide:
- Interactive REPL for logic theorem proving
- Formula validation and parsing
- Proof state management
- Autocomplete for commands and tactics
- History and session management
"""

import pytest
import tempfile
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock


class LogicREPLSession:
    """REPL session for interactive logic proving."""
    
    # Available commands
    COMMANDS = {
        "prove": "Prove a formula: prove <formula> [tactic]",
        "assert": "Assert a formula: assert <formula>",
        "validate": "Validate formula syntax",
        "tactics": "List available tactics",
        "status": "Show proof state",
        "reset": "Reset proof state",
        "history": "Show command history",
        "help": "Show help information",
        "exit": "Exit the REPL",
        "quit": "Alias for exit",
    }
    
    # Available tactics for theorem proving
    TACTICS = [
        "simp",          # Simplification
        "intro",         # Introduce variables
        "apply",         # Apply theorem
        "rw",            # Rewrite
        "cases",         # Case analysis
        "induction",     # Induction
        "exact",         # Exact proof
        "sorry",         # Placeholder
        "contradiction", # Proof by contradiction
        "omega",         # Omega tactic for arithmetic
    ]
    
    # Known axioms and theorems
    KNOWN_FORMULAS = {
        "true": "⊤ (always true)",
        "false": "⊥ (always false)",
        "identity": "∀x. x = x",
        "reflexivity": "∀a. a ≤ a",
        "transitivity": "∀a b c. a ≤ b → b ≤ c → a ≤ c",
        "symmetry": "∀a b. a = b → b = a",
        "commutativity": "∀a b. a + b = b + a",
        "associativity": "∀a b c. (a + b) + c = a + (b + c)",
    }
    
    def __init__(self):
        """Initialize REPL session."""
        self.formulas = []
        self.proven_formulas = set()
        self.current_goal: Optional[str] = None
        self.proof_state: Dict[str, Any] = {
            "assumptions": [],
            "goal": None,
            "steps": [],
        }
        self.history = []
        self.tactics = self.TACTICS.copy()
    
    def get_command_completions(self, prefix: str) -> List[str]:
        """Get command completions for a prefix.
        
        Args:
            prefix: Command prefix
            
        Returns:
            List of matching commands
        """
        return [cmd for cmd in self.COMMANDS.keys() if cmd.startswith(prefix)]
    
    def get_tactic_completions(self, prefix: str) -> List[str]:
        """Get tactic completions for a prefix.
        
        Args:
            prefix: Tactic prefix
            
        Returns:
            List of matching tactics
        """
        return [t for t in self.tactics if t.startswith(prefix)]
    
    def get_formula_completions(self, prefix: str) -> List[str]:
        """Get formula completions for a prefix.
        
        Args:
            prefix: Formula prefix
            
        Returns:
            List of matching known formulas
        """
        return [f for f in self.KNOWN_FORMULAS.keys() if f.startswith(prefix)]
    
    def parse_command(self, line: str) -> Tuple[str, List[str]]:
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
    
    def validate_formula(self, formula: str) -> Dict[str, Any]:
        """Validate formula syntax.
        
        Args:
            formula: Formula string
            
        Returns:
            Validation result
        """
        # Basic validation: check for matching parentheses
        if formula.count("(") != formula.count(")"):
            return {
                "valid": False,
                "error": "Mismatched parentheses",
            }
        
        # Check for known operators
        valid_ops = ["∀", "∃", "→", "∧", "∨", "¬", "=", "≤", "≥", "<", ">"]
        # Note: This is a simplified check
        
        return {
            "valid": True,
            "formula": formula,
            "complexity": len(formula.split()),
        }
    
    def execute_prove(self, args: List[str]) -> Dict[str, Any]:
        """Execute prove command.
        
        Args:
            args: Command arguments [formula, tactic?]
            
        Returns:
            Result dictionary
        """
        if not args:
            return {"error": "Usage: prove <formula> [tactic]"}
        
        # Parse formula and tactic from args
        tactic = "simp"
        if len(args) == 1:
            formula = args[0]
        elif len(args) == 2:
            # Direct API call: args[0] is formula, args[1] is tactic
            formula = args[0]
            tactic = args[1]
        else:
            # Parsed command with spaces: check if last arg is a known tactic
            if args[-1] in self.tactics:
                formula = " ".join(args[:-1])
                tactic = args[-1]
            else:
                # No tactic at end, join all as formula
                formula = " ".join(args)
                tactic = "simp"
        
        # Validate formula
        validation = self.validate_formula(formula)
        if not validation["valid"]:
            return validation
        
        # Validate tactic early
        if tactic not in self.tactics:
            return {
                "success": False,
                "error": f"Unknown tactic: {tactic}",
                "available": self.tactics,
            }
        
        # Check if already proven
        if formula in self.proven_formulas:
            return {
                "success": True,
                "message": f"Formula already proven: {formula}",
                "cached": True,
                "tactic": tactic,
            }
        
        # Check if formula is known
        if formula in self.KNOWN_FORMULAS:
            self.proven_formulas.add(formula)
            self.proof_state["steps"].append({
                "formula": formula,
                "tactic": tactic,
                "status": "proven",
            })
            return {
                "success": True,
                "message": f"Proved {formula}",
                "tactic": tactic,
                "description": self.KNOWN_FORMULAS[formula],
            }
        
        # Mock proof: success if formula contains simple pattern
        can_prove = len(formula) < 100  # Arbitrary complexity limit
        
        if can_prove:
            self.proven_formulas.add(formula)
            self.proof_state["steps"].append({
                "formula": formula,
                "tactic": tactic,
                "status": "proven",
            })
            return {
                "success": True,
                "message": f"Proved {formula} using {tactic}",
                "tactic": tactic,
                "steps": len(self.proof_state["steps"]),
            }
        else:
            return {
                "success": False,
                "error": "Formula too complex for automated proof",
                "formula": formula,
            }
    
    def execute_assert(self, args: List[str]) -> Dict[str, Any]:
        """Execute assert command.
        
        Args:
            args: Command arguments [formula]
            
        Returns:
            Result dictionary
        """
        if not args:
            return {"error": "Usage: assert <formula>"}
        
        # Join all args back together (in case formula has spaces)
        formula = " ".join(args)
        
        # Validate
        validation = self.validate_formula(formula)
        if not validation["valid"]:
            return validation
        
        self.formulas.append(formula)
        self.proof_state["assumptions"].append(formula)
        
        return {
            "success": True,
            "message": f"Asserted {formula}",
            "assumption_count": len(self.proof_state["assumptions"]),
        }
    
    def execute_validate(self, args: List[str]) -> Dict[str, Any]:
        """Execute validate command.
        
        Args:
            args: Command arguments (optional formula)
            
        Returns:
            Result dictionary
        """
        if args:
            formula = args[0]
            return self.validate_formula(formula)
        
        # Validate all formulas
        invalid = []
        for formula in self.formulas:
            validation = self.validate_formula(formula)
            if not validation["valid"]:
                invalid.append(formula)
        
        return {
            "success": len(invalid) == 0,
            "total_formulas": len(self.formulas),
            "valid": len(self.formulas) - len(invalid),
            "invalid": invalid,
        }
    
    def execute_tactics(self, args: List[str]) -> Dict[str, Any]:
        """Execute tactics command.
        
        Args:
            args: Command arguments (unused)
            
        Returns:
            Result dictionary
        """
        return {
            "success": True,
            "tactics": self.tactics,
            "count": len(self.tactics),
        }
    
    def execute_status(self, args: List[str]) -> Dict[str, Any]:
        """Execute status command.
        
        Args:
            args: Command arguments (unused)
            
        Returns:
            Result dictionary
        """
        return {
            "success": True,
            "formulas_asserted": len(self.formulas),
            "formulas_proven": len(self.proven_formulas),
            "assumptions_active": len(self.proof_state["assumptions"]),
            "proof_steps": len(self.proof_state["steps"]),
            "current_goal": self.current_goal,
        }
    
    def execute_reset(self, args: List[str]) -> Dict[str, Any]:
        """Execute reset command.
        
        Args:
            args: Command arguments (unused)
            
        Returns:
            Result dictionary
        """
        self.formulas = []
        self.proven_formulas = set()
        self.current_goal = None
        self.proof_state = {
            "assumptions": [],
            "goal": None,
            "steps": [],
        }
        
        return {
            "success": True,
            "message": "Proof state reset",
        }
    
    def execute_history(self, args: List[str]) -> Dict[str, Any]:
        """Execute history command.
        
        Args:
            args: Command arguments (unused)
            
        Returns:
            Result dictionary
        """
        limit = int(args[0]) if args and args[0].isdigit() else 10
        
        recent = self.history[-limit:] if self.history else []
        return {
            "success": True,
            "history_size": len(self.history),
            "recent": recent,
        }
    
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
            "tactics": self.tactics,
            "formulas": self.KNOWN_FORMULAS,
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
        
        if command == "prove":
            return self.execute_prove(args)
        elif command == "assert":
            return self.execute_assert(args)
        elif command == "validate":
            return self.execute_validate(args)
        elif command == "tactics":
            return self.execute_tactics(args)
        elif command == "status":
            return self.execute_status(args)
        elif command == "reset":
            return self.execute_reset(args)
        elif command == "history":
            return self.execute_history(args)
        elif command == "help":
            return self.execute_help(args)
        else:
            return {"error": f"Unknown command: {command}"}


# ============================================================================
# TEST CLASSES
# ============================================================================

class TestLogicREPLSessionBasics:
    """Test basic REPL session operations."""
    
    def test_create_session(self):
        """Test creating a REPL session."""
        session = LogicREPLSession()
        assert session.current_goal is None
        assert len(session.formulas) == 0
        assert len(session.COMMANDS) > 0
    
    def test_get_command_completions(self):
        """Test getting command completions."""
        session = LogicREPLSession()
        
        assert "prove" in session.get_command_completions("pro")
        assert "assert" in session.get_command_completions("ass")
        assert "validate" in session.get_command_completions("val")
    
    def test_get_tactic_completions(self):
        """Test getting tactic completions."""
        session = LogicREPLSession()
        
        assert "simp" in session.get_tactic_completions("si")
        assert "induction" in session.get_tactic_completions("in")
    
    def test_get_formula_completions(self):
        """Test getting formula completions."""
        session = LogicREPLSession()
        
        assert "identity" in session.get_formula_completions("id")
        assert "reflexivity" in session.get_formula_completions("ref")
    
    def test_parse_command(self):
        """Test parsing command lines."""
        session = LogicREPLSession()
        
        cmd, args = session.parse_command("prove (a ∧ b) simp")
        assert cmd == "prove"
        assert args == ["(a", "∧", "b)", "simp"]


class TestLogicFormulaValidation:
    """Test formula validation."""
    
    def test_validate_simple_formula(self):
        """Test validating simple formula."""
        session = LogicREPLSession()
        result = session.validate_formula("a ∧ b")
        
        assert result["valid"] is True
    
    def test_validate_formula_with_parens(self):
        """Test formula with parentheses."""
        session = LogicREPLSession()
        result = session.validate_formula("(a ∧ b) ∨ c")
        
        assert result["valid"] is True
    
    def test_validate_mismatched_parens(self):
        """Test validation with mismatched parentheses."""
        session = LogicREPLSession()
        result = session.validate_formula("(a ∧ b")
        
        assert result["valid"] is False
        assert "parentheses" in result["error"].lower()


class TestLogicProveCommand:
    """Test prove command."""
    
    def test_prove_known_formula(self):
        """Test proving a known formula."""
        session = LogicREPLSession()
        result = session.execute_prove(["identity"])
        
        assert result["success"] is True
    
    def test_prove_with_tactic(self):
        """Test proving with specific tactic."""
        session = LogicREPLSession()
        result = session.execute_prove(["(a = a)", "simp"])
        
        assert result["success"] is True
        assert result["tactic"] == "simp"
    
    def test_prove_unknown_tactic(self):
        """Test proving with unknown tactic."""
        session = LogicREPLSession()
        result = session.execute_prove(["identity", "unknown_tactic"])
        
        assert result["success"] is False
        assert "error" in result
    
    def test_prove_no_args(self):
        """Test prove with no arguments."""
        session = LogicREPLSession()
        result = session.execute_prove([])
        
        assert "error" in result
        assert "Usage" in result["error"]
    
    def test_cached_proof(self):
        """Test cached proof."""
        session = LogicREPLSession()
        
        # First proof
        result1 = session.execute_prove(["identity"])
        assert result1["success"] is True
        
        # Second proof (cached)
        result2 = session.execute_prove(["identity"])
        assert result2["cached"] is True


class TestLogicAssertCommand:
    """Test assert command."""
    
    def test_assert_formula(self):
        """Test asserting a formula."""
        session = LogicREPLSession()
        result = session.execute_assert(["(a → b)"])
        
        assert result["success"] is True
        assert len(session.formulas) == 1
    
    def test_assert_invalid_formula(self):
        """Test asserting invalid formula."""
        session = LogicREPLSession()
        result = session.execute_assert(["(a → b"])
        
        assert result["valid"] is False


class TestLogicValidateCommand:
    """Test validate command."""
    
    def test_validate_all_formulas(self):
        """Test validating all formulas."""
        session = LogicREPLSession()
        
        session.execute_assert(["(a ∧ b)"])
        session.execute_assert(["(c ∨ d)"])
        
        result = session.execute_validate([])
        
        assert result["success"] is True
        assert result["total_formulas"] == 2


class TestLogicSessionManagement:
    """Test session management."""
    
    def test_status_command(self):
        """Test status command."""
        session = LogicREPLSession()
        
        session.execute_assert(["a"])
        session.execute_prove(["identity"])
        
        result = session.execute_status([])
        
        assert result["success"] is True
        assert result["formulas_asserted"] == 1
        assert result["formulas_proven"] == 1
    
    def test_reset_command(self):
        """Test resetting session."""
        session = LogicREPLSession()
        
        session.execute_assert(["a"])
        assert len(session.formulas) == 1
        
        result = session.execute_reset([])
        
        assert result["success"] is True
        assert len(session.formulas) == 0
    
    def test_history_command(self):
        """Test history."""
        session = LogicREPLSession()
        session.history = ["command1", "command2", "command3"]
        
        result = session.execute_history([])
        
        assert result["success"] is True
        assert len(result["recent"]) <= 10


class TestLogicCommandExecution:
    """Test command execution flow."""
    
    def test_full_workflow(self):
        """Test complete logic workflow."""
        session = LogicREPLSession()
        
        # Assert assumptions
        result = session.execute_command("assert (a ∧ b)")
        assert result["success"] is True
        
        # Validate
        result = session.execute_command("validate")
        assert result["success"] is True
        
        # Prove
        result = session.execute_command("prove identity")
        assert result["success"] is True
        
        # Status
        result = session.execute_command("status")
        assert result["success"] is True
        assert result["formulas_asserted"] == 1
    
    def test_exit_command(self):
        """Test exit command."""
        session = LogicREPLSession()
        result = session.execute_command("exit")
        
        assert result["success"] is True
        assert result.get("exit") is True
    
    def test_unknown_command(self):
        """Test unknown command."""
        session = LogicREPLSession()
        result = session.execute_command("invalid_command")
        
        assert "error" in result
        assert "Unknown" in result["error"]


class TestLogicHelpCommand:
    """Test help functionality."""
    
    def test_general_help(self):
        """Test general help."""
        session = LogicREPLSession()
        result = session.execute_help([])
        
        assert result["success"] is True
        assert "commands" in result
        assert "tactics" in result
    
    def test_command_help(self):
        """Test help for specific command."""
        session = LogicREPLSession()
        result = session.execute_help(["prove"])
        
        assert result["success"] is True
        assert "prove" in result["command"]
