"""Financial Theorems for Temporal Deontic Logic System (thin MCP wrapper).

Business logic (``FinancialEventType``, ``FinancialTheorem``, ``FinancialTheoremLibrary``,
``TheoremApplication`` and pre-defined theorems) lives in:
    ipfs_datasets_py.processors.finance.finance_theorems_engine
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from ipfs_datasets_py.processors.finance.finance_theorems_engine import (  # noqa: F401
    FinancialEventType,
    FinancialTheorem,
    FinancialTheoremLibrary,
    TheoremApplication,
    STOCK_SPLIT_THEOREM,
    REVERSE_SPLIT_THEOREM,
    DIVIDEND_EX_DATE_THEOREM,
    MERGER_PRICE_CONVERGENCE_THEOREM,
    EARNINGS_ANNOUNCEMENT_THEOREM,
)

logger = logging.getLogger(__name__)


def list_financial_theorems(
    event_type: Optional[str] = None
) -> str:
    """
    MCP tool to list available financial theorems.
    
    Args:
        event_type: Optional filter by event type
    
    Returns:
        JSON string with theorem list
    """
    try:
        library = FinancialTheoremLibrary()
        
        if event_type:
            # Filter by event type
            try:
                evt_type = FinancialEventType(event_type.lower())
                theorems = library.get_theorems_by_event_type(evt_type)
            except ValueError:
                return json.dumps({
                    "error": f"Invalid event type: {event_type}",
                    "valid_types": [e.value for e in FinancialEventType]
                })
        else:
            # Get all theorems
            theorems = list(library.theorems.values())
        
        result = {
            "total_theorems": len(theorems),
            "event_type_filter": event_type,
            "theorems": [t.to_dict() for t in theorems]
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        logger.error(f"Error listing theorems: {e}", exc_info=True)
        return json.dumps({"error": str(e)})


def apply_financial_theorem(
    theorem_id: str,
    symbol: str,
    event_date: str,
    event_data: str
) -> str:
    """
    MCP tool to apply a financial theorem to market data.
    
    Args:
        theorem_id: ID of theorem to apply
        symbol: Stock symbol
        event_date: Date of event in ISO format
        event_data: JSON string with event details
    
    Returns:
        JSON string with application results
    """
    try:
        library = FinancialTheoremLibrary()
        theorem = library.get_theorem(theorem_id)
        
        if not theorem:
            return json.dumps({
                "error": f"Theorem not found: {theorem_id}"
            })
        
        # Parse inputs
        evt_date = datetime.fromisoformat(event_date)
        evt_data = json.loads(event_data)
        
        # Apply theorem (placeholder logic)
        # In production, integrate with actual market data and logic engine
        
        application = TheoremApplication(
            theorem_id=theorem_id,
            symbol=symbol,
            event_date=evt_date,
            expected_outcome={
                "description": f"Theorem {theorem.name} predicts specific outcome",
                "details": "See theorem formula for exact prediction"
            },
            confidence_score=theorem.confidence_threshold
        )
        
        result = {
            "success": True,
            "theorem": theorem.to_dict(),
            "application": application.to_dict(),
            "note": "This is a placeholder. Implement actual theorem evaluation."
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        logger.error(f"Error applying theorem: {e}", exc_info=True)
        return json.dumps({"error": str(e)})


__all__ = [
    "FinancialEventType",
    "FinancialTheorem",
    "FinancialTheoremLibrary",
    "TheoremApplication",
    "STOCK_SPLIT_THEOREM",
    "REVERSE_SPLIT_THEOREM",
    "DIVIDEND_EX_DATE_THEOREM",
    "MERGER_PRICE_CONVERGENCE_THEOREM",
    "EARNINGS_ANNOUNCEMENT_THEOREM",
    "list_financial_theorems",
    "apply_financial_theorem"
]
