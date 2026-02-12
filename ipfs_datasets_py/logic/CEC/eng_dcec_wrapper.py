"""
Eng-DCEC Converter Wrapper

This module provides a Python wrapper for the Eng-DCEC submodule,
which converts English text to DCEC (Deontic Cognitive Event Calculus) formulas.

Eng-DCEC uses Grammatical Framework (GF) to parse natural language
and generate corresponding formal logic representations.
"""

import sys
import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
import logging

# Add Eng-DCEC to Python path
ENG_DCEC_PATH = Path(__file__).parent / "Eng-DCEC" / "python"
if str(ENG_DCEC_PATH) not in sys.path:
    sys.path.insert(0, str(ENG_DCEC_PATH))

try:
    from beartype import beartype  # type: ignore
except ImportError:  # pragma: no cover
    def beartype(func):  # type: ignore
        return func

logger = logging.getLogger(__name__)


@dataclass
class ConversionResult:
    """Represents the result of converting English to DCEC."""
    english_text: str
    dcec_formula: Optional[str] = None
    parse_trees: Optional[List[str]] = None
    success: bool = False
    error_message: Optional[str] = None
    confidence: float = 0.0


class EngDCECWrapper:
    """
    Wrapper for Eng-DCEC converter providing a clean Python API.
    
    This wrapper manages the conversion from English natural language
    to DCEC formal logic formulas using Grammatical Framework.
    
    Attributes:
        converter: The underlying EngDCEC converter instance
        conversion_history: List of conversion attempts
        gf_server_url: URL of the GF server (if using HTTP mode)
    """
    
    def __init__(self, gf_server_url: Optional[str] = None):
        """
        Initialize the Eng-DCEC wrapper.
        
        Args:
            gf_server_url: Optional URL for GF HTTP server (e.g., "http://127.0.0.1:41296")
        """
        self.converter = None
        self.gf_server_url = gf_server_url or "http://127.0.0.1:41296"
        self.conversion_history: List[ConversionResult] = []
        self._initialized = False
        
    @beartype
    def initialize(self) -> bool:
        """
        Initialize the Eng-DCEC converter.
        
        Returns:
            bool: True if initialization succeeded, False otherwise
        """
        try:
            # Import Eng-DCEC modules
            from EngDCEC import parse_Simple, linearize_Simple, parse_Deep
            
            self.parse_simple = parse_Simple
            self.linearize_simple = linearize_Simple
            self.parse_deep = parse_Deep
            
            self._initialized = True
            logger.info("Eng-DCEC converter initialized successfully")
            return True
            
        except ImportError as e:
            logger.error(f"Failed to import Eng-DCEC: {e}")
            logger.warning("Eng-DCEC not available. Using fallback mode.")
            self._initialized = False
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Eng-DCEC: {e}")
            self._initialized = False
            return False
    
    @beartype
    def convert_to_dcec(
        self,
        english_text: str,
        use_deep_parsing: bool = False
    ) -> ConversionResult:
        """
        Convert English text to DCEC formula.
        
        Args:
            english_text: The English text to convert
            use_deep_parsing: If True, use deep parsing mode
            
        Returns:
            ConversionResult object with conversion results
        """
        if not self._initialized:
            logger.error("Eng-DCEC not initialized. Call initialize() first.")
            return ConversionResult(
                english_text=english_text,
                success=False,
                error_message="Converter not initialized"
            )
        
        try:
            if use_deep_parsing:
                # Use deep parsing mode
                result_str = self.parse_deep(english_text)
                parse_trees = [result_str]
            else:
                # Use simple parsing mode
                parse_trees = self.parse_simple(english_text)
            
            if not parse_trees:
                return ConversionResult(
                    english_text=english_text,
                    success=False,
                    error_message="No parse trees generated"
                )
            
            # Use first parse tree
            dcec_formula = parse_trees[0] if isinstance(parse_trees, list) else str(parse_trees)
            
            result = ConversionResult(
                english_text=english_text,
                dcec_formula=dcec_formula,
                parse_trees=parse_trees if isinstance(parse_trees, list) else [parse_trees],
                success=True,
                confidence=1.0 / len(parse_trees) if isinstance(parse_trees, list) else 1.0
            )
            
            self.conversion_history.append(result)
            logger.info(f"Successfully converted: {english_text[:50]}...")
            return result
            
        except Exception as e:
            logger.error(f"Error during conversion: {e}")
            result = ConversionResult(
                english_text=english_text,
                success=False,
                error_message=str(e)
            )
            self.conversion_history.append(result)
            return result
    
    @beartype
    def convert_from_dcec(self, dcec_formula: str) -> Optional[str]:
        """
        Convert DCEC formula back to English (linearization).
        
        Args:
            dcec_formula: The DCEC formula to convert
            
        Returns:
            English text or None if conversion fails
        """
        if not self._initialized:
            logger.error("Eng-DCEC not initialized")
            return None
            
        try:
            english_text = self.linearize_simple(dcec_formula)
            logger.info(f"Successfully linearized formula to: {english_text[:50]}...")
            return english_text
        except Exception as e:
            logger.error(f"Error during linearization: {e}")
            return None
    
    @beartype
    def batch_convert(
        self,
        texts: List[str],
        use_deep_parsing: bool = False
    ) -> List[ConversionResult]:
        """
        Convert multiple English texts to DCEC formulas.
        
        Args:
            texts: List of English texts to convert
            use_deep_parsing: If True, use deep parsing mode
            
        Returns:
            List of ConversionResult objects
        """
        results = []
        for text in texts:
            result = self.convert_to_dcec(text, use_deep_parsing)
            results.append(result)
        
        return results
    
    @beartype
    def get_conversion_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about conversion attempts.
        
        Returns:
            Dictionary with statistics
        """
        if not self.conversion_history:
            return {"total_conversions": 0}
            
        successful = sum(1 for c in self.conversion_history if c.success)
        failed = len(self.conversion_history) - successful
        
        avg_confidence = 0.0
        if successful > 0:
            confidences = [c.confidence for c in self.conversion_history if c.success]
            avg_confidence = sum(confidences) / len(confidences)
        
        return {
            "total_conversions": len(self.conversion_history),
            "successful": successful,
            "failed": failed,
            "success_rate": successful / len(self.conversion_history) if self.conversion_history else 0.0,
            "average_confidence": avg_confidence
        }
    
    @beartype
    def get_last_conversion(self) -> Optional[ConversionResult]:
        """
        Get the most recent conversion result.
        
        Returns:
            Most recent ConversionResult or None if no conversions
        """
        if not self.conversion_history:
            return None
        return self.conversion_history[-1]
    
    @beartype
    def clear_history(self) -> None:
        """Clear the conversion history."""
        self.conversion_history.clear()
        logger.info("Conversion history cleared")
    
    def __repr__(self) -> str:
        """String representation of the wrapper."""
        status = "initialized" if self._initialized else "not initialized"
        return f"EngDCECWrapper(status={status}, conversions={len(self.conversion_history)})"
