"""
Core conversion: legal text -> deontic logic.

DEPRECATED: This module provides backward-compatible async interface.
New code should use DeonticConverter from .converter module instead.

The convert_legal_text_to_deontic() function is maintained for backward compatibility
but internally uses DeonticConverter for all conversions.
"""

from __future__ import annotations

import logging
import warnings
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from .converter import DeonticConverter

logger = logging.getLogger(__name__)


async def convert_legal_text_to_deontic(
    legal_text: Union[str, Dict[str, Any]],
    jurisdiction: str = "us",
    document_type: str = "statute",
    output_format: str = "json",
    extract_obligations: bool = True,
    include_exceptions: bool = True,
) -> Dict[str, Any]:
    """
    Convert legal text (statutes, regs, contracts) into deontic logic.
    
    DEPRECATED: Use DeonticConverter instead for better performance and features.
    
    This function is maintained for backward compatibility. New code should use:
        from ipfs_datasets_py.logic.deontic import DeonticConverter
        converter = DeonticConverter(jurisdiction="us", document_type="statute")
        result = await converter.convert_async(text)
    
    Args:
        legal_text: Legal text string or dataset dictionary
        jurisdiction: Legal jurisdiction (us, eu, uk, international, general)
        document_type: Document type (statute, regulation, contract, policy, agreement)
        output_format: Output format (json, prolog, tptp)
        extract_obligations: Whether to extract obligations
        include_exceptions: Whether to include exceptions in analysis
        
    Returns:
        Dictionary with deontic formulas and metadata
    """
    # Issue deprecation warning
    warnings.warn(
        "convert_legal_text_to_deontic() is deprecated and will be removed in v2.0. "
        "Use DeonticConverter instead",
        DeprecationWarning,
        stacklevel=2
    )
    
    try:
        # Handle None input
        if legal_text is None:
            legal_text = ""
        
        # Normalize jurisdiction and document_type
        if jurisdiction not in ["us", "eu", "uk", "international", "general"]:
            logger.warning(f"Unknown jurisdiction '{jurisdiction}', using 'general'")
            jurisdiction = "general"
        
        if document_type not in ["statute", "regulation", "contract", "policy", "agreement", "general"]:
            logger.warning(f"Unknown document type '{document_type}', using 'general'")
            document_type = "general"
        
        # Extract text from dataset format if needed
        if isinstance(legal_text, dict):
            sections = extract_legal_text_from_dataset(legal_text)
        elif isinstance(legal_text, str):
            stripped = legal_text.strip()
            if not stripped:
                return _empty_success_result(jurisdiction, document_type, output_format)
            sections = [stripped]
        else:
            raise ValueError("Legal text input must be a string or dictionary")
        
        # Check if all sections are empty
        if not sections or all(not s.strip() for s in sections):
            return _empty_success_result(jurisdiction, document_type, output_format)
        
        # Create DeonticConverter with appropriate settings
        converter = DeonticConverter(
            jurisdiction=jurisdiction,
            document_type=document_type,
            use_cache=True,  # Enable caching for better performance
            use_ml=False,  # Use heuristic confidence to match original behavior
            enable_monitoring=False,  # Disable monitoring to avoid noise
            extract_obligations=extract_obligations,
            include_exceptions=include_exceptions,
            output_format=output_format
        )
        
        # Convert all sections
        results = []
        total_processed = 0
        successful_conversions = 0
        
        all_entities = set()
        all_actions = set()
        normative_dist = {"obligations": 0, "permissions": 0, "prohibitions": 0}
        
        for section in sections:
            section = section.strip()
            if not section:
                continue
            
            total_processed += 1
            
            # Convert using DeonticConverter
            conversion_result = await converter.convert_async(section)
            
            if conversion_result.success:
                successful_conversions += 1
                
                # Convert to legacy dict format
                formula_dict = _convert_result_to_legacy_format(
                    conversion_result,
                    section
                )
                
                results.append(formula_dict)
                
                # Track statistics
                if conversion_result.output.agent:
                    all_entities.add(conversion_result.output.agent.name)
                
                # Track operator distribution
                operator_str = str(conversion_result.output.operator)
                if "OBLIGATION" in operator_str:
                    normative_dist["obligations"] += 1
                elif "PERMISSION" in operator_str:
                    normative_dist["permissions"] += 1
                elif "PROHIBITION" in operator_str:
                    normative_dist["prohibitions"] += 1
        
        # Build summary
        summary = {
            "total_normative_statements": total_processed,
            "successful_conversions": successful_conversions,
            "conversion_rate": successful_conversions / max(1, total_processed),
            "average_confidence": sum(
                r["confidence"] for r in results
            ) / max(1, len(results)),
            "normative_distribution": normative_dist,
            "conflicts_detected": 0,  # Would need conflict detection
            "unique_entities": len(all_entities),
            "unique_actions": len(all_actions),
        }
        
        # Build normative structure
        normative_structure = {
            "obligations": [r for r in results if "OBLIGATION" in str(r.get("operator", ""))],
            "permissions": [r for r in results if "PERMISSION" in str(r.get("operator", ""))],
            "prohibitions": [r for r in results if "PROHIBITION" in str(r.get("operator", ""))],
        }
        
        if total_processed > 0:
            logger.info(
                "Successfully converted %s/%s legal statements to deontic logic",
                successful_conversions,
                total_processed
            )
        
        return {
            "status": "success",
            "deontic_formulas": results,
            "normative_structure": normative_structure,
            "legal_entities": list(all_entities),
            "actions": list(all_actions),
            "temporal_constraints": [],  # Would need extraction
            "conflicts": [],  # Would need detection
            "summary": summary,
            "metadata": {
                "tool": "legal_text_to_deontic",
                "version": "1.0.0",
                "jurisdiction": jurisdiction,
                "document_type": document_type,
                "output_format": output_format,
                "processing_timestamp": datetime.now().isoformat(),
            },
        }
    
    except Exception as exc:
        logger.error(f"Error in convert_legal_text_to_deontic: {exc}")
        return {
            "status": "error",
            "message": str(exc),
            "deontic_formulas": [],
            "normative_structure": {"obligations": [], "permissions": [], "prohibitions": []},
            "legal_entities": [],
            "actions": [],
            "temporal_constraints": [],
            "conflicts": [],
            "summary": {
                "total_normative_statements": 0,
                "successful_conversions": 0,
                "conversion_rate": 0.0,
                "average_confidence": 0.0,
                "normative_distribution": {"obligations": 0, "permissions": 0, "prohibitions": 0},
                "conflicts_detected": 0,
                "unique_entities": 0,
                "unique_actions": 0,
            },
        }


def _empty_success_result(jurisdiction: str, document_type: str, output_format: str) -> Dict[str, Any]:
    """Return empty success result for empty input."""
    return {
        "status": "success",
        "deontic_formulas": [],
        "normative_structure": {"obligations": [], "permissions": [], "prohibitions": []},
        "legal_entities": [],
        "actions": [],
        "temporal_constraints": [],
        "conflicts": [],
        "summary": {
            "total_normative_statements": 0,
            "successful_conversions": 0,
            "conversion_rate": 0.0,
            "average_confidence": 0.0,
            "normative_distribution": {"obligations": 0, "permissions": 0, "prohibitions": 0},
            "conflicts_detected": 0,
            "unique_entities": 0,
            "unique_actions": 0,
        },
        "metadata": {
            "tool": "legal_text_to_deontic",
            "version": "1.0.0",
            "jurisdiction": jurisdiction,
            "document_type": document_type,
            "output_format": output_format,
            "processing_timestamp": datetime.now().isoformat(),
        },
    }


def _convert_result_to_legacy_format(conversion_result, original_text: str) -> Dict[str, Any]:
    """Convert ConversionResult to legacy dict format."""
    deontic_formula = conversion_result.output
    
    result = {
        "original_text": original_text,
        "deontic_formula": deontic_formula.proposition,
        "operator": str(deontic_formula.operator),
        "confidence": deontic_formula.confidence,
        "agent": deontic_formula.agent.name if deontic_formula.agent else None,
        "beneficiary": deontic_formula.beneficiary.name if deontic_formula.beneficiary else None,
        "conditions": deontic_formula.conditions,
        "temporal_constraints": [],  # Would need conversion
    }
    
    return result


def extract_legal_text_from_dataset(dataset: Dict[str, Any]) -> List[str]:
    """Extract legal text content from various dataset formats."""
    texts: List[str] = []
    
    # Check for direct text field
    if "text" in dataset:
        text = dataset["text"]
        if isinstance(text, str):
            texts.append(text.strip())
        elif isinstance(text, list):
            texts.extend(str(t).strip() for t in text)
    
    # Check for data field with nested structure
    elif "data" in dataset:
        data = dataset["data"]
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    for key in ["text", "content", "clause", "section", "provision"]:
                        if key in item:
                            texts.append(str(item[key]).strip())
                            break
                elif isinstance(item, str):
                    texts.append(item.strip())
    
    # Check for sections field
    elif "sections" in dataset:
        sections = dataset["sections"]
        if isinstance(sections, list):
            texts.extend(str(s).strip() for s in sections)
    
    # Fallback: try to extract any string values
    else:
        for value in dataset.values():
            if isinstance(value, str):
                texts.append(value.strip())
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        texts.append(item.strip())
    
    return [t for t in texts if t]  # Remove empty strings
