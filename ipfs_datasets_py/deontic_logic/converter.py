"""
Automatic Deontic Logic Converter

This module provides automatic conversion of legal text into formal deontic logic expressions.
"""

import re
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

class ModalityType(Enum):
    """Types of deontic modalities"""
    OBLIGATION = "obligation"
    PERMISSION = "permission"  
    PROHIBITION = "prohibition"

@dataclass
class DeonticStatement:
    """Represents a deontic logic statement"""
    logic_expression: str
    natural_language: str
    confidence: float
    modality: ModalityType
    temporal_constraint: Optional[str] = None

class DeonticLogicConverter:
    """Converts legal text to formal deontic logic expressions"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._init_patterns()
    
    def _init_patterns(self):
        """Initialize regex patterns for legal modalities"""
        self.obligation_patterns = [
            r'must\s+([^.]+)',
            r'shall\s+([^.]+)',
            r'required\s+to\s+([^.]+)',
            r'obligated\s+to\s+([^.]+)',
            r'duty\s+to\s+([^.]+)'
        ]
        
        self.permission_patterns = [
            r'may\s+([^.]+)',
            r'permitted\s+to\s+([^.]+)',
            r'allowed\s+to\s+([^.]+)',
            r'authorized\s+to\s+([^.]+)',
            r'right\s+to\s+([^.]+)'
        ]
        
        self.prohibition_patterns = [
            r'shall\s+not\s+([^.]+)',
            r'must\s+not\s+([^.]+)',
            r'prohibited\s+from\s+([^.]+)',
            r'forbidden\s+to\s+([^.]+)',
            r'cannot\s+([^.]+)'
        ]
    
    def convert_text(self, legal_text: str) -> List[DeonticStatement]:
        """Convert legal text to deontic logic statements"""
        statements = []
        
        # Extract obligations
        for pattern in self.obligation_patterns:
            matches = re.finditer(pattern, legal_text, re.IGNORECASE)
            for match in matches:
                action = self._clean_action(match.group(1))
                if action:
                    logic_expr = f"O({action})"
                    confidence = self._calculate_confidence(match.group(0), ModalityType.OBLIGATION)
                    statements.append(DeonticStatement(
                        logic_expression=logic_expr,
                        natural_language=match.group(0),
                        confidence=confidence,
                        modality=ModalityType.OBLIGATION
                    ))
        
        # Extract permissions
        for pattern in self.permission_patterns:
            matches = re.finditer(pattern, legal_text, re.IGNORECASE)
            for match in matches:
                action = self._clean_action(match.group(1))
                if action:
                    logic_expr = f"P({action})"
                    confidence = self._calculate_confidence(match.group(0), ModalityType.PERMISSION)
                    statements.append(DeonticStatement(
                        logic_expression=logic_expr,
                        natural_language=match.group(0),
                        confidence=confidence,
                        modality=ModalityType.PERMISSION
                    ))
        
        # Extract prohibitions
        for pattern in self.prohibition_patterns:
            matches = re.finditer(pattern, legal_text, re.IGNORECASE)
            for match in matches:
                action = self._clean_action(match.group(1))
                if action:
                    logic_expr = f"F({action})"
                    confidence = self._calculate_confidence(match.group(0), ModalityType.PROHIBITION)
                    statements.append(DeonticStatement(
                        logic_expression=logic_expr,
                        natural_language=match.group(0),
                        confidence=confidence,
                        modality=ModalityType.PROHIBITION
                    ))
        
        return statements
    
    def _clean_action(self, action: str) -> str:
        """Clean and normalize action text"""
        action = re.sub(r'\s+', '_', action.strip())
        action = re.sub(r'[^a-zA-Z0-9_]', '', action)
        return action.lower()
    
    def _calculate_confidence(self, text: str, modality: ModalityType) -> float:
        """Calculate confidence score for deontic statement"""
        base_confidence = {
            ModalityType.OBLIGATION: 0.8,
            ModalityType.PERMISSION: 0.7,
            ModalityType.PROHIBITION: 0.85
        }
        
        confidence = base_confidence[modality]
        
        if any(word in text.lower() for word in ['must', 'shall', 'required']):
            confidence += 0.1
        if any(word in text.lower() for word in ['may', 'might', 'could']):
            confidence -= 0.1
            
        return min(0.95, max(0.5, confidence))