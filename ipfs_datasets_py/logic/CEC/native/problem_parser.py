"""
Problem File Parser for ShadowProver.

This module provides parsers for various theorem proving problem file formats:
- TPTP (Thousands of Problems for Theorem Provers) format
- Custom ShadowProver problem format

TPTP format is the standard format used in automated theorem proving.
"""

from typing import List, Optional
from dataclasses import dataclass
import re
import logging

try:
    from beartype import beartype
except ImportError:
    from typing import TypeVar, Callable, Any
    F = TypeVar('F', bound=Callable[..., Any])
    def beartype(func: F) -> F:
        return func

from .shadow_prover import ProblemFile, ModalLogic

logger = logging.getLogger(__name__)


@dataclass
class TPTPFormula:
    """A formula in TPTP format.
    
    Attributes:
        name: Formula identifier
        role: Formula role (axiom, conjecture, etc.)
        formula: Formula string
        annotations: Optional annotations
    """
    name: str
    role: str
    formula: str
    annotations: Optional[str] = None


class TPTPParser:
    """Parser for TPTP (Thousands of Problems for Theorem Provers) format.
    
    TPTP is the standard format for theorem proving problems.
    Supports fof() (first-order formula) and cnf() (clause normal form).
    """
    
    def __init__(self) -> None:
        """Initialize TPTP parser."""
        self.formulas: List[TPTPFormula] = []
        self.includes: List[str] = []
        
    @beartype  # type: ignore[untyped-decorator]
    def parse_file(self, filepath: str) -> ProblemFile:
        """Parse a TPTP problem file.
        
        Args:
            filepath: Path to TPTP file
            
        Returns:
            ProblemFile object
            
        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file format is invalid
        """
        try:
            with open(filepath, 'r') as f:
                content = f.read()
            return self.parse_string(content, filepath)
        except FileNotFoundError:
            raise FileNotFoundError(f"TPTP file not found: {filepath}")
        except Exception as e:
            raise ValueError(f"Error parsing TPTP file: {e}")
    
    @beartype  # type: ignore[untyped-decorator]
    def parse_string(self, content: str, name: str = "tptp_problem") -> ProblemFile:
        """Parse TPTP format string.
        
        Args:
            content: TPTP format string
            name: Problem name
            
        Returns:
            ProblemFile object
        """
        self.formulas = []
        self.includes = []
        
        # Remove comments
        lines = []
        for line in content.split('\n'):
            # Remove line comments
            if '%' in line:
                line = line[:line.index('%')]
            line = line.strip()
            if line:
                lines.append(line)
        
        content = '\n'.join(lines)
        
        # Parse formulas
        # fof(name, role, formula).
        fof_pattern = r'fof\s*\(\s*([^,]+)\s*,\s*([^,]+)\s*,\s*([^)]+)\s*\)\s*\.'
        for match in re.finditer(fof_pattern, content):
            name_part = match.group(1).strip()
            role = match.group(2).strip()
            formula = match.group(3).strip()
            
            self.formulas.append(TPTPFormula(
                name=name_part,
                role=role,
                formula=formula
            ))
        
        # cnf(name, role, clause).
        cnf_pattern = r'cnf\s*\(\s*([^,]+)\s*,\s*([^,]+)\s*,\s*([^)]+)\s*\)\s*\.'
        for match in re.finditer(cnf_pattern, content):
            name_part = match.group(1).strip()
            role = match.group(2).strip()
            clause = match.group(3).strip()
            
            self.formulas.append(TPTPFormula(
                name=name_part,
                role=role,
                formula=clause
            ))
        
        # Parse includes
        include_pattern = r'include\s*\(\s*["\']([^"\']+)["\']\s*\)'
        for match in re.finditer(include_pattern, content):
            self.includes.append(match.group(1))
        
        # Separate assumptions and goals
        assumptions = []
        goals = []
        
        for formula in self.formulas:
            if formula.role == 'axiom' or formula.role == 'hypothesis':
                assumptions.append(formula.formula)
            elif formula.role == 'conjecture' or formula.role == 'theorem':
                goals.append(formula.formula)
            elif formula.role == 'negated_conjecture':
                # Negate it to get the original conjecture
                goals.append(f"¬({formula.formula})")
        
        # Default to K logic for TPTP
        logic = ModalLogic.K
        
        return ProblemFile(
            name=name,
            logic=logic,
            assumptions=assumptions,
            goals=goals,
            metadata={
                "format": "tptp",
                "includes": self.includes,
                "total_formulas": len(self.formulas)
            }
        )


class CustomProblemParser:
    """Parser for custom ShadowProver problem format.
    
    Custom format:
    ```
    LOGIC: K/S4/S5/Cognitive
    
    ASSUMPTIONS:
    P
    P → Q
    
    GOALS:
    Q
    ```
    """
    
    @beartype  # type: ignore[untyped-decorator]
    def parse_file(self, filepath: str) -> ProblemFile:
        """Parse a custom problem file.
        
        Args:
            filepath: Path to problem file
            
        Returns:
            ProblemFile object
        """
        try:
            with open(filepath, 'r') as f:
                content = f.read()
            return self.parse_string(content, filepath)
        except FileNotFoundError:
            raise FileNotFoundError(f"Problem file not found: {filepath}")
        except Exception as e:
            raise ValueError(f"Error parsing problem file: {e}")
    
    @beartype  # type: ignore[untyped-decorator]
    def parse_string(self, content: str, name: str = "custom_problem") -> ProblemFile:
        """Parse custom format string.
        
        Args:
            content: Custom format string
            name: Problem name
            
        Returns:
            ProblemFile object
        """
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        
        # Default values
        logic = ModalLogic.K
        assumptions = []
        goals = []
        
        current_section = None
        
        for line in lines:
            # Skip comments
            if line.startswith('#') or line.startswith('//'):
                continue
            
            # Check for section headers
            if line.startswith('LOGIC:'):
                logic_str = line.split(':', 1)[1].strip().upper()
                logic_map = {
                    'K': ModalLogic.K,
                    'T': ModalLogic.T,
                    'S4': ModalLogic.S4,
                    'S5': ModalLogic.S5,
                    'D': ModalLogic.D,
                    'COGNITIVE': ModalLogic.S5,  # Use S5 as base
                }
                logic = logic_map.get(logic_str, ModalLogic.K)
                
            elif line == 'ASSUMPTIONS:':
                current_section = 'assumptions'
                
            elif line == 'GOALS:':
                current_section = 'goals'
                
            else:
                # Add to current section
                if current_section == 'assumptions':
                    assumptions.append(line)
                elif current_section == 'goals':
                    goals.append(line)
        
        return ProblemFile(
            name=name,
            logic=logic,
            assumptions=assumptions,
            goals=goals,
            metadata={"format": "custom"}
        )


class ProblemParser:
    """Unified problem file parser.
    
    Automatically detects format and uses appropriate parser.
    """
    
    def __init__(self) -> None:
        """Initialize problem parser."""
        self.tptp_parser = TPTPParser()
        self.custom_parser = CustomProblemParser()
    
    @beartype  # type: ignore[untyped-decorator]
    def parse_file(self, filepath: str) -> ProblemFile:
        """Parse a problem file (auto-detects format).
        
        Args:
            filepath: Path to problem file
            
        Returns:
            ProblemFile object
        """
        # Try to detect format from file extension or content
        if filepath.endswith('.p') or filepath.endswith('.tptp'):
            logger.info(f"Parsing as TPTP format: {filepath}")
            return self.tptp_parser.parse_file(filepath)
        else:
            logger.info(f"Parsing as custom format: {filepath}")
            return self.custom_parser.parse_file(filepath)
    
    @beartype  # type: ignore[untyped-decorator]
    def parse_string(self, content: str, format_hint: Optional[str] = None) -> ProblemFile:
        """Parse a problem string.
        
        Args:
            content: Problem content
            format_hint: Optional format hint ('tptp' or 'custom')
            
        Returns:
            ProblemFile object
        """
        if format_hint == 'tptp' or 'fof(' in content or 'cnf(' in content:
            return self.tptp_parser.parse_string(content)
        else:
            return self.custom_parser.parse_string(content)


def parse_problem_file(filepath: str) -> ProblemFile:
    """Convenience function to parse a problem file.
    
    Args:
        filepath: Path to problem file
        
    Returns:
        ProblemFile object
    """
    parser = ProblemParser()
    return parser.parse_file(filepath)


def parse_problem_string(content: str, format_hint: Optional[str] = None) -> ProblemFile:
    """Convenience function to parse a problem string.
    
    Args:
        content: Problem content
        format_hint: Optional format hint
        
    Returns:
        ProblemFile object
    """
    parser = ProblemParser()
    return parser.parse_string(content, format_hint)
